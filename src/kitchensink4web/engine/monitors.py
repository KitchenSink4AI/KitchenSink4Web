"""Proactive page monitoring: the state model, the store, and the limits.

A monitor is a standing instruction to re-check ONE url for ONE
deterministic condition on an interval, inside this server process, and to
remember what it saw. It is not an alert. Nothing is pushed anywhere,
because nothing can be: no MCP client in use today delivers a
server-initiated message into a model's context, and the mechanism that was
tried for it was closed as not planned. The value is that when a
conversation asks, the answer is a checked history rather than a fresh page
load, and that a monitor which could not check SAYS SO.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE. `unchanged` is derived from a
successful check since the last report and from nothing else. It is never
derived from the absence of a recorded change, because "we did not manage
to look" and "we looked and nothing moved" are different answers and only
one of them is safe to act on. `state_of()` below is the only place that
word is produced, and `test_monitor.py` M-1 fails the moment it can be
reached without a success.

WHY THE CHECK LADDER IS NOT `policy.engine.approve`. Every acting call in
the server goes through that choke point, and a monitor check runs the same
ladder in the same order with two deliberate differences, both of which the
lifecycle spec settles:

- **No confirmation gate.** A background tick has no conversation to
  elicit into and gates fail closed by construction, so a gated verdict
  encountered mid-check could only ever refuse. Gated verdicts are
  therefore resolved at CREATE time, while a human is in the loop, and
  pinned into the record; the tick re-evaluates the pinned verdict against
  the current lists and refuses to navigate if it no longer holds.
- **Its own budget ledger.** `policy/budgets` is keyed per session and is
  finite per session by design, including a four-hour wall clock. A
  monitor legitimately runs for days, so sharing that ledger would mean
  every monitor dying at hour four with a budget message about a session
  nobody opened. The limits below are the monitor's own, they are finite,
  and they are published in every report.

The store is local process state, not a document. Nothing syncs.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from ..errors import BudgetExhausted
from . import hygiene

STORE_VERSION = 1

#: THE FOUR CONDITIONS, and what each one honestly cannot notice. The
#: description is returned by `create` so a caller reads it once, at the
#: moment the choice is being made, rather than discovering the limit from
#: a monitor that has been quietly useless for a week.
CONDITIONS: dict[str, dict] = {
    "content_hash": {
        "needs_value": False,
        "notices": ("that the page's visible text changed, as a hash of the "
                    "normalised innerText of the body, or of the element "
                    "`selector` names when a selector is given"),
        "cannot": ("what changed, or whether the change matters. A clock, a "
                   "view counter, or a rotating advert fires this every "
                   "interval. Scope it with `selector` on a busy page."),
    },
    "text_appears": {
        "needs_value": True,
        "notices": "that a string that was absent from the body text is now "
                   "present",
        "cannot": ("text inside a closed shadow root, text in a "
                   "cross-origin frame, and text painted only into a canvas"),
    },
    "text_gone": {
        "needs_value": True,
        "notices": "that a string that was present in the body text is now "
                   "absent",
        "cannot": ("text inside a closed shadow root, text in a "
                   "cross-origin frame, and text painted only into a canvas"),
    },
    "selector_count": {
        "needs_value": True,
        "notices": "that the number of elements matching a CSS selector "
                   "changed",
        "cannot": ("a change that leaves the count identical, such as one "
                   "item added and one removed. It is a proxy for 'something "
                   "was added to this list', not a reading of the list."),
    },
}

#: Env-tunable, finite always: an unset limit is a default, never infinity,
#: and a garbage value is the default rather than a crash or a bypass. The
#: same shape `policy/budgets.LIMIT_ENVS` uses, for the same reason.
LIMIT_ENVS: dict[str, tuple[str, int]] = {
    "min_interval_min": ("KS4WEB_MONITOR_MIN_INTERVAL_MIN", 5),
    "max_monitors": ("KS4WEB_MONITOR_MAX", 10),
    "max_checks_day": ("KS4WEB_MONITOR_MAX_CHECKS_DAY", 500),
    "max_failures": ("KS4WEB_MONITOR_MAX_FAILURES", 6),
    "history": ("KS4WEB_MONITOR_HISTORY", 50),
    "batch": ("KS4WEB_MONITOR_BATCH", 3),
    "tick_s": ("KS4WEB_MONITOR_TICK_S", 30),
}

#: There is NO in-conversation reset, deliberately, and for the same reason
#: `policy/budgets.RESET_ROUTE` gives: a ceiling the model can lift by
#: calling a tool is not a ceiling. The recovery is to delete monitors, or
#: to raise the environment variable at the next launch.
BUDGET_ROUTE = (
    "There is no in-conversation reset for the monitor budget. Delete "
    "monitors with monitor(action='delete', monitor=...), or raise "
    "KS4WEB_MONITOR_MAX_CHECKS_DAY at the next launch. A monitor that hit "
    "this is suspended, not deleted, and its history is intact.")


def limit(name: str) -> int:
    env, default = LIMIT_ENVS[name]
    try:
        value = int(os.environ.get(env, default))
    except ValueError:
        value = default
    return max(1, value)


def published_limits() -> dict:
    return {name: limit(name) for name in LIMIT_ENVS}


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


# --------------------------------------------------------------- the store


class MonitorStore:
    """`STATE_DIR/monitors.json`, written after every state transition
    rather than on a timer, so a hard kill loses at most one in-flight
    check.

    A record this version cannot read is LEFT ON DISK UNTOUCHED, excluded
    from scheduling, and reported once. Dropping what a parser does not
    recognise is the inversion this build refuses everywhere else, and a
    monitor silently disappearing after an upgrade is the exact shape of
    it."""

    REQUIRED = ("id", "url", "condition", "interval_minutes", "state")

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._loaded = False
        self.monitors: list[dict] = []
        #: Raw entries kept verbatim for the rewrite, never scheduled.
        self.unreadable: list[dict] = []
        self.checks_today: dict = {"window_start": time.time(), "count": 0}
        #: The PID that wrote the file we loaded. A different one means the
        #: server restarted, which is a gap to REPORT rather than to hide.
        self.previous_pid: int | None = None
        self.restarted: bool = False
        self._seq = 0

    @property
    def path(self) -> Path:
        return self._path or (hygiene.STATE_DIR / "monitors.json")

    # -------------------------------------------------------------- load

    def reload(self) -> None:
        self._loaded = False
        self.load()

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.monitors, self.unreadable = [], []
        self.previous_pid, self.restarted = None, False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.previous_pid = raw.get("written_by_pid")
        self.restarted = (self.previous_pid is not None
                          and self.previous_pid != os.getpid())
        today = raw.get("checks_today")
        if isinstance(today, dict) and "count" in today:
            self.checks_today = today
        for entry in raw.get("monitors") or []:
            if isinstance(entry, dict) and all(k in entry
                                               for k in self.REQUIRED):
                self.monitors.append(entry)
            else:
                self.unreadable.append(entry)
        for record in self.monitors:
            number = str(record.get("id", "m0"))[1:]
            if number.isdigit():
                self._seq = max(self._seq, int(number))

    # ------------------------------------------------------------- write

    def save(self) -> None:
        self.load()
        payload = {
            "version": STORE_VERSION,
            "written": _iso(time.time()),
            "written_by_pid": os.getpid(),
            "checks_today": self.checks_today,
            # The records this version could not read ride along BYTE FOR
            # BYTE, so an upgrade that misreads a field cannot delete the
            # monitor while it is being fixed.
            "monitors": self.monitors + self.unreadable,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # The previous file stands and the in-memory state still
            # serves this process. A monitor store that turned an
            # unwritable disk into a refused tool call would be worse than
            # one that loses a check.
            try:
                tmp.unlink(missing_ok=True)
            except (OSError, UnboundLocalError, NameError):
                pass

    # ------------------------------------------------------------ access

    def next_id(self) -> str:
        self.load()
        self._seq += 1
        return f"m{self._seq}"

    def get(self, monitor_id: str) -> dict | None:
        self.load()
        for record in self.monitors:
            if record["id"] == monitor_id:
                return record
        return None

    def known_ids(self) -> list[str]:
        self.load()
        return [r["id"] for r in self.monitors]

    def add(self, record: dict) -> None:
        self.load()
        self.monitors.append(record)
        self.save()

    def remove(self, monitor_id: str) -> dict | None:
        self.load()
        for i, record in enumerate(self.monitors):
            if record["id"] == monitor_id:
                self.monitors.pop(i)
                self.save()
                return record
        return None


STORE = MonitorStore()


# ------------------------------------------------------------ the budget


def charge_check() -> None:
    """One check against the rolling daily ceiling. Checked before the
    increment, so a refused check is never billed."""
    STORE.load()
    window = STORE.checks_today
    started = float(window.get("window_start", 0))
    if time.time() - started > 86400:
        window = {"window_start": time.time(), "count": 0}
        STORE.checks_today = window
    ceiling = limit("max_checks_day")
    if int(window.get("count", 0)) >= ceiling:
        raise BudgetExhausted(
            f"the monitor check budget for the last 24 hours is spent: "
            f"{window['count']} checks against {ceiling}. Every monitor is "
            f"suspended until the window rolls over at "
            f"{_iso(started + 86400)}. {BUDGET_ROUTE}")
    window["count"] = int(window.get("count", 0)) + 1
    STORE.checks_today = window


# ------------------------------------------------------- the state model


def fires(condition: str, before, after) -> bool:
    """Did this condition's change happen between two observed values?

    Each condition fires on ITS OWN change and on nothing else, which is
    what keeps `content_hash` from claiming a count moved and
    `selector_count` from claiming text arrived."""
    if condition in ("content_hash", "selector_count"):
        return before != after
    if condition == "text_appears":
        return bool(after) and not bool(before)
    if condition == "text_gone":
        # Both text conditions store the same observation, "the string is
        # present", so the pair is symmetric and there is one predicate to
        # get right rather than two. This one fires on the disappearance.
        return bool(before) and not bool(after)
    return False


def note_success(record: dict, value: dict, fired: bool,
                 previous=None) -> None:
    now = time.time()
    record["last_success_at"] = now
    record["last_attempt_at"] = now
    record["last_attempt_ok"] = True
    record["last_error"] = None
    record["consecutive_failures"] = 0
    record["checks_run"] = int(record.get("checks_run", 0)) + 1
    record["last_value"] = value
    entry = {"at": now, "ok": True, "value": value.get("value"),
             "fired": bool(fired)}
    if fired:
        entry["from"] = previous
    _append_history(record, entry)
    _reschedule(record)


def note_blocked(record: dict, why: str, until: float) -> None:
    """A site's own rate limit, honoured rather than retried.

    Deliberately NOT a failure: `consecutive_failures` is the counter that
    auto-pauses a monitor, and a site saying "slow down" is the monitor
    working correctly. The record stays `active` so it resumes on its own
    when the window passes, and `state_of` reports `blocked` until then."""
    record["blocked_until"] = until
    record["blocked_why"] = why
    record["last_attempt_at"] = time.time()
    record["next_due"] = until
    _append_history(record, {"at": record["last_attempt_at"], "ok": False,
                             "code": "BLOCKED_BY_SITE"})


def note_failure(record: dict, code: str, message: str) -> None:
    """A failed attempt. The success timestamp is deliberately NOT touched,
    because it is the number the stale row reports and the number the
    `unchanged` derivation reads."""
    now = time.time()
    record["last_attempt_at"] = now
    record["last_attempt_ok"] = False
    record["last_error"] = {"code": code, "message": message}
    record["consecutive_failures"] = int(
        record.get("consecutive_failures", 0)) + 1
    _append_history(record, {"at": now, "ok": False, "code": code})
    if record["consecutive_failures"] >= limit("max_failures"):
        # A monitor failing forever is generating traffic and telling
        # nobody. It pauses itself and the report leads with the reason.
        record["state"] = "paused"
        record["auto_paused"] = True
        record["auto_paused_why"] = (
            f"{record['consecutive_failures']} checks in a row failed with "
            f"{code}, which is the configured limit "
            f"({LIMIT_ENVS['max_failures'][0]}={limit('max_failures')}). "
            f"Nothing is retried until it is resumed.")
    _reschedule(record)


def _append_history(record: dict, entry: dict) -> None:
    history = record.setdefault("history", [])
    history.append(entry)
    keep = limit("history")
    if len(history) > keep:
        del history[:len(history) - keep]


def _reschedule(record: dict) -> None:
    """Next due, with plus or minus ten percent of jitter so ten monitors
    on one site do not synchronise into a burst against it."""
    interval = float(record.get("interval_minutes", 30)) * 60
    record["next_due"] = time.time() + interval * random.uniform(0.9, 1.1)


def state_of(record: dict, now: float | None = None) -> dict:
    """One monitor's reported row, and the ONLY place the seven state words
    are produced.

    The order of these branches is the honesty contract: everything that
    means "this monitor is not working" outranks everything that means
    "nothing happened", because a broken monitor is more urgent than an
    unchanged one and a caller who reads `unchanged` will stop looking."""
    now = time.time() if now is None else now
    interval_s = float(record.get("interval_minutes", 30)) * 60
    success = record.get("last_success_at")
    attempt = record.get("last_attempt_at")
    reported = record.get("last_reported_at") or 0
    row = {
        "monitor": record["id"],
        "label": record.get("label"),
        "url": record.get("url"),
        "condition": record.get("condition"),
        "value": record.get("value"),
        "interval_minutes": record.get("interval_minutes"),
        "checks_run": int(record.get("checks_run", 0)),
        "checks_missed": int(record.get("checks_missed", 0)),
        "last_success_at": _iso(success),
        "last_attempt_at": _iso(attempt),
    }
    if record.get("auto_paused"):
        row["auto_paused"] = True
        row["auto_paused_why"] = record.get("auto_paused_why")
    if record.get("last_error"):
        row["last_error"] = record["last_error"]

    stored = record.get("state")
    if stored == "unreadable":
        row["state"] = "blocked"
        row["why"] = record.get("why")
        return row
    if stored == "suspended":
        row["state"] = "suspended"
        row["why"] = record.get("why") or BUDGET_ROUTE
        row["checks_today"] = STORE.checks_today.get("count", 0)
        return row
    if stored == "blocked":
        row["state"] = "blocked"
        row["why"] = record.get("why")
        return row
    # A 429 WINDOW OUTRANKS THE STALE BRANCH. The last attempt did not
    # succeed, but the reason is that the site asked to be left alone and
    # this server agreed, which is a different fact from a monitor that is
    # broken, and it clears itself.
    blocked_until = float(record.get("blocked_until") or 0)
    if blocked_until > now:
        row["state"] = "blocked"
        row["why"] = record.get("blocked_why")
        row["blocked_for_s"] = round(blocked_until - now, 1)
        return row

    # A FAILED LAST ATTEMPT IS STALE, ALWAYS, and outranks a pause: a
    # monitor that broke and then auto-paused is broken first.
    failed = record.get("last_attempt_ok") is False
    gap = (now - success) if success else None
    aged = gap is not None and gap > 2 * interval_s
    if failed or aged:
        row["state"] = "stale"
        row["gap_s"] = round(gap, 1) if gap is not None else None
        row["consecutive_failures"] = int(
            record.get("consecutive_failures", 0))
        row["why"] = ("the last attempt failed" if failed else
                      "no check has succeeded for longer than twice the "
                      "interval")
        if record.get("missed_since_restart"):
            row["missed_since_restart"] = record["missed_since_restart"]
            row["restart_note"] = record.get("restart_note")
        return row
    if stored == "paused":
        row["state"] = "paused"
        row["resume"] = (f"monitor(action='resume', "
                         f"monitor={record['id']!r})")
        return row
    if success is None:
        row["state"] = "never_checked"
        row["created"] = _iso(record.get("created"))
        row["first_check_due"] = _iso(record.get("next_due"))
        return row

    fired = [h for h in record.get("history", [])
             if h.get("fired") and float(h.get("at", 0)) > reported]
    if fired:
        latest = fired[-1]
        row["state"] = "changed"
        row["at"] = _iso(latest.get("at"))
        row["from"] = latest.get("from")
        row["to"] = latest.get("value")
        row["checks_since_report"] = len(
            [h for h in record.get("history", [])
             if float(h.get("at", 0)) > reported])
        return row
    # THE ONLY ROUTE TO `unchanged`, and it requires a successful check.
    row["state"] = "unchanged"
    row["successful_checks"] = len(
        [h for h in record.get("history", [])
         if h.get("ok") and float(h.get("at", 0)) > reported])
    if record.get("missed_since_restart"):
        row["missed_since_restart"] = record["missed_since_restart"]
        row["restart_note"] = record.get("restart_note")
    return row


def note_restart_gaps() -> None:
    """Work out what a restart cost, once, and write it onto each record.

    A gap is a fact about the world, not an error, and hiding it would let
    the first report after a restart read as though the monitors had been
    running the whole time."""
    STORE.load()
    if not STORE.restarted:
        return
    now = time.time()
    for record in STORE.monitors:
        last = record.get("last_attempt_at") or record.get("created")
        interval_s = float(record.get("interval_minutes", 30)) * 60
        if not last or interval_s <= 0:
            continue
        missed = int(max(0.0, now - float(last)) // interval_s)
        if missed:
            record["missed_since_restart"] = missed
            record["restart_note"] = (
                f"this monitor did not check between {_iso(float(last))} and "
                f"{_iso(now)} because the KS4Web server restarted, and about "
                f"{missed} interval(s) were missed. Monitors run only while "
                f"the server runs.")
            record["checks_missed"] = int(
                record.get("checks_missed", 0)) + missed
    STORE.restarted = False
    STORE.save()
