"""The `monitor` tool and the one background tick in this server.

The state model, the store, and the limits live in `engine/monitors.py`;
this module is the tool surface, the browser half of a check, and the
scheduler. Three commitments, each of which a naive implementation gets
wrong in a way that only shows up in the field:

- **A monitor never uses the caller's session.** It would charge their
  budget and, worse, every check navigates, and a navigation destroys
  every ref minted on the page it leaves. A conversation holding refs on a
  page a monitor decided to re-check would watch them die for reasons it
  could not see. Monitors get one dedicated headless session,
  `role="monitor"`, which is listed in the status report like any other
  browser process because a browser the user did not open must never be
  invisible.
- **The scheduler starts lazily and only when there is something to
  check.** Eager startup of GUI-capable MCP servers is the root cause
  named in the worst leak reports in this field, and a Desktop launching
  five servers at login must not have one of them loading web pages before
  the human has typed anything.
- **A check that did not happen is never reported as no change.** That
  contract is enforced in `monitors.state_of`, and everything here feeds
  it honestly: a failure writes `last_attempt_ok=False` and deliberately
  does NOT touch `last_success_at`.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import unicodedata
from collections import deque
from urllib.parse import urlparse

from ..engine import monitors as _monitors
from ..engine import session as _session
from ..engine.session import MANAGER
from ..envelope import classify as _classify
from ..errors import (BadParams, BlockedBySite, BudgetExhausted, Conflict,
                      TargetNotFound)
from ..policy import audit as _audit
from ..policy import budgets as _budgets
from ..policy import origins as _origins
from ..policy import readonly

ACTIONS = ("report", "create", "list", "pause", "resume", "delete",
           "check_now")

#: The page-side half of each predicate. Deliberately tiny and deliberately
#: main-frame only: a monitor that silently included or excluded frames
#: would make `content_hash` irreproducible between runs, so the frame
#: census is REPORTED at create instead of being quietly folded in.
_PROBE_JS = """
(args) => {
  const out = {frames: window.frames.length};
  if (args.kind === 'selector_count') {
    out.count = document.querySelectorAll(args.value).length;
    return out;
  }
  let root = document.body;
  if (args.selector) {
    root = document.querySelector(args.selector);
    if (!root) { out.missing = true; return out; }
  }
  out.text = (root && root.innerText) || '';
  return out;
}
"""


def _normalise(text: str) -> str:
    """What a human reads, with the noise a machine adds taken out.

    Text rather than DOM shape, on purpose: a DOM-shape hash on a modern
    single-page application changes on every load, so the monitor would
    report a change every interval forever, which is the same disease as
    having no monitor."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _hash(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()


# ------------------------------------------------------- the monitor session


#: EVERY TIME THE SCHEDULER'S BROWSER DIED AND WAS REPLACED, newest last.
#: Read by `monitor(action='report')` and by `manage_session(action='status')`.
#: A restart is a thing that HAPPENED to the user's machine, so it is
#: reported as a fact and not smoothed over; the field report's tester
#: found a dead monitor by accident, three layers into a cascade, and
#: that is the discovery path this list exists to replace.
SESSION_RESTARTS: deque = deque(maxlen=16)


def session_restarts() -> list[dict]:
    return list(SESSION_RESTARTS)


def monitor_session_health() -> dict | None:
    """What the scheduler's browser is doing, or None if it holds none.

    Named separately from the session list because a caller who does not
    know monitors open sessions will not recognise one in that list."""
    for session in MANAGER.sessions.values():
        if getattr(session, "role", "user") == "monitor":
            alive = session.browser_alive()
            return {
                "session": session.session_id,
                "lane": session.spec.label,
                "browser": ("dead" if alive is False else
                            "alive" if alive else "unknown"),
                "monitors_active": len(_active_monitors()),
                **({"restarts": session_restarts()}
                   if SESSION_RESTARTS else {}),
            }
    if SESSION_RESTARTS or _active_monitors():
        return {"session": None,
                "browser": "none open",
                "monitors_active": len(_active_monitors()),
                **({"restarts": session_restarts()}
                   if SESSION_RESTARTS else {})}
    return None


async def _monitor_session():
    """The one session the scheduler owns. Headless always, and it never
    auto-upgrades to a headed window the way `manage_session(handoff)`
    does: nothing a monitor runs may put a window on the user's screen.

    A DEAD ONE IS REPLACED, AND THE REPLACEMENT IS REPORTED. The old code
    handed back whatever session carried the monitor role without asking
    whether its browser was still running, so once the scheduler's browser
    died every tick afterwards failed against a corpse and the only symptom
    was stale results. The restart does not weaken the failure valve:
    `note_failure` still counts every check that did not happen and still
    auto-pauses a monitor at KS4WEB_MONITOR_MAX_FAILURES in a row, so a
    browser that dies as fast as it is replaced stops the monitor rather
    than looping."""
    for session in MANAGER.sessions.values():
        if getattr(session, "role", "user") != "monitor":
            continue
        if session.browser_alive() is not False:
            return session
        # Dead. Clear it out of the way before opening its replacement, so
        # the status report never shows two monitor sessions at once.
        sid = session.session_id
        try:
            await MANAGER.close(sid, reason="crash")
        except Exception:
            MANAGER.sessions.pop(sid, None)
        SESSION_RESTARTS.append({
            "at": time.time(),
            "replaced": sid,
            "why": ("every browser process the scheduler's session owned "
                    "had exited, so its checks could not run"),
        })
        break
    session = await MANAGER.open(headless=True, role="monitor")
    if SESSION_RESTARTS and SESSION_RESTARTS[-1].get("opened") is None:
        SESSION_RESTARTS[-1]["opened"] = session.session_id
    return session


async def _close_monitor_session() -> None:
    for sid, session in list(MANAGER.sessions.items()):
        if getattr(session, "role", "user") == "monitor":
            await MANAGER.close(sid, reason="explicit_close")


def _active_monitors() -> list[dict]:
    _monitors.STORE.load()
    return [r for r in _monitors.STORE.monitors if r.get("state") == "active"]


async def _retire_session_if_idle() -> None:
    """A browser held for monitors that no longer exist is exactly the
    forgotten-process failure this server's hygiene work exists to
    prevent."""
    if not _active_monitors():
        await _close_monitor_session()


# ------------------------------------------------------------- one check


async def _run_check(record: dict, *, first: bool = False) -> dict:
    """Navigate the monitor session to one URL and evaluate one predicate.

    The ladder is `policy/engine.approve`'s, in the same order, minus the
    confirmation gate (no human is present in a tick, and gates fail closed
    by construction) and with the monitor's own budget in place of the
    per-session one. `engine/monitors.py` carries the reasoning."""
    url = record["url"]
    # 1. THE PINNED ORIGIN VERDICT, re-evaluated against the CURRENT lists.
    #    A verdict decided at create time can stop holding across a restart,
    #    and a monitor that kept navigating on a stale permission would be
    #    the origin policy's own bypass.
    verdict = _origins.evaluate(url)
    pinned = record.get("origin_verdict_at_create")
    if verdict in ("denied", "denied-scheme"):
        # `check_navigation` owns the wording for both of these and raises.
        _origins.check_navigation(url, readonly.grade())
    if verdict != pinned:
        raise Conflict(
            f"the origin policy now rules {url} {verdict!r}, and this "
            f"monitor was created when it was {pinned!r}. Nothing was "
            f"fetched. Delete the monitor, or restore the origin lists this "
            f"monitor was created under and resume it.")
    # 2. A DOMAIN THAT ANSWERED 429 STAYS ANSWERED until its window passes.
    host = urlparse(url).hostname
    if host:
        _budgets.BOOK.check_domain(host)
    # 3. The monitor's own budget, charged before anything is fetched.
    _monitors.charge_check()

    sess = await _monitor_session()
    page_record = sess.page(sess.focused)
    try:
        response = await _session.with_timeout(
            page_record.page.goto(url), _session.DEFAULT_TIMEOUT_MS,
            f"monitor check of {url}")
    except Exception as exc:
        from . import lite as _lite
        _lite._raise_if_unreachable(exc, f"monitor check of {url}",
                                    page_record)
        raise
    page_record.touch(page_record.page.url)
    # A SITE THAT SAID SLOW DOWN IS BELIEVED THE FIRST TIME. The backoff is
    # registered on the shared domain book, so a monitor and a
    # conversation cannot walk into the same window from two directions.
    #
    # ONE PARSER, NOT THREE (fix wave 2026-09-08, V-17). This branch used to
    # read the header itself, on 429 alone and as a bare integer alone, so
    # `120.5` and every HTTP-date form fell through to the default and a 503
    # with a wait attached lost its number entirely. `navigate` already routes
    # the parse, the record, and the report through `budgets`; so does this,
    # for the same statuses and with the same reasoning about a bare 503.
    status = getattr(response, "status", None) if response is not None \
        else None
    if host and status in _budgets.RETRY_AFTER_STATUSES:
        try:
            raw = dict(response.headers).get("retry-after") or ""
        except Exception:
            raw = ""
        if status == 429 or raw.strip():
            rate_limit = _budgets.BOOK.note_retry_after(host, raw,
                                                        status=status)
            # THE SOURCE IS THE REPORT'S OWN. A default KS4Web chose must not
            # be worded as the window the site asked for, and the book already
            # says which one it is.
            # FLAGGED (fix wave 2026-09-08): placeholder wording,
            # mechanically composed from this refusal's own clauses and the
            # report's `source` field.
            raise BlockedBySite(
                f"{host} answered HTTP {status} for this monitor's URL and "
                f"the honored window is {rate_limit['seconds']:.0f}s "
                f"({rate_limit['source']}). The next check is scheduled past "
                f"the window; KS4Web honours a site's rate limit rather than "
                f"retrying against it.")
    # 4. WHERE IT LANDED, not only where it was aimed. A redirect must not
    #    launder a blocked origin, and a background tick cannot ask a human
    #    about an off-list landing, so it refuses instead of gating.
    landed = page_record.page.url
    _origins.check_navigation(landed, readonly.grade(), phase="landed")
    if _origins.evaluate(landed) == "off-list":
        raise Conflict(
            f"the monitor's URL redirected to {landed}, which is outside "
            f"the origin allowlist. A scheduled check has no conversation "
            f"to ask a human in, so it refuses rather than reading the "
            f"page. Nothing was read.")
    page_record.vetted_url = landed

    condition = record["condition"]
    probe = await page_record.page.evaluate(
        _PROBE_JS, {"kind": condition, "value": record.get("value"),
                    "selector": record.get("selector")})
    if probe.get("missing"):
        raise TargetNotFound(
            f"the selector {record.get('selector')!r} matched nothing on "
            f"{landed}, so there was nothing to hash. The page may have "
            f"changed its markup. Delete this monitor and create one "
            f"against a selector the page still has.")
    if condition == "selector_count":
        value = {"kind": "count", "value": int(probe.get("count", 0))}
    elif condition == "content_hash":
        value = {"kind": "hash", "value": _hash(probe.get("text") or "")}
    else:
        needle = record.get("value") or ""
        present = needle in _normalise(probe.get("text") or "")
        value = {"kind": "present", "value": bool(present)}
    result = {"ok": True, "value": value, "frames": int(probe.get("frames", 0))}
    # 5. PARK BETWEEN CHECKS, and invalidate with it. A park is a
    #    navigation, so anything minted on the document dies with it, and
    #    saying so is what keeps a later call from resolving a ref against
    #    about:blank.
    try:
        sess.invalidate_page(
            page_record.handle,
            "the monitor parked this page between checks")
        await page_record.page.goto(_session.PARKED_URL, timeout=10000)
        page_record.parked = True
    except Exception:
        pass                    # a park that fails costs nothing here
    return result


def _remaining_backoff(url: str) -> float:
    """How long the shared domain book still refuses this host. Read rather
    than re-derived, so the monitor and the conversation surfaces cannot
    disagree about the same window."""
    # ASKED, NOT SCRAPED (fix wave 2026-09-08, V-17). This read the number
    # back out of `check_domain`'s refusal with a regex, which made a
    # user-facing sentence into load-bearing API: rewording the refusal, or
    # dropping the word "left" from it, would have silently changed how long
    # a monitor recorded itself blocked. The book is asked for its own
    # number instead.
    return _budgets.BOOK.remaining_backoff_s(urlparse(url).hostname or "")


async def _check_and_record(record: dict) -> dict:
    """One check plus its bookkeeping, for both the tick and `check_now`."""
    previous = (record.get("last_value") or {}).get("value")
    try:
        outcome = await _run_check(record)
    except BlockedBySite as exc:
        remaining = _remaining_backoff(record["url"])
        _monitors.note_blocked(record, str(exc), time.time() + remaining)
        _monitors.STORE.save()
        return {"ok": False, "code": "BLOCKED_BY_SITE",
                "blocked_for_s": round(remaining, 1)}
    except BudgetExhausted as exc:
        # The daily ceiling suspends every monitor rather than deleting
        # one, and the report leads with it.
        for other in _monitors.STORE.monitors:
            other["state"] = "suspended"
            other["why"] = str(exc)
        _monitors.STORE.save()
        return {"ok": False, "code": "BUDGET_EXHAUSTED"}
    except Exception as exc:
        code = _classify(exc)
        _monitors.note_failure(record, code, str(exc))
        _monitors.STORE.save()
        return {"ok": False, "code": code}
    record.pop("blocked_until", None)
    record.pop("blocked_why", None)
    value = outcome["value"]
    fired = (previous is not None
             and _monitors.fires(record["condition"], previous,
                                 value["value"]))
    _monitors.note_success(record, value, fired, previous=previous)
    _monitors.STORE.save()
    return {"ok": True, "fired": fired, "value": value["value"]}


# --------------------------------------------------------- the scheduler


_TASK: asyncio.Task | None = None


def ensure_scheduler() -> None:
    """Start the tick, once, and only when there is something to check.

    Called from the server's tool wrapper, so the first thing a monitor
    waits for is a human saying anything at all to this server in any
    conversation. That is the cost of the lazy-start rule and the report
    states it rather than hiding it: the first report of a run can
    legitimately say a window was missed."""
    global _TASK
    if _TASK is not None and not _TASK.done():
        return
    try:
        _monitors.STORE.load()
    except Exception:
        return
    if not _active_monitors():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _monitors.note_restart_gaps()
    _TASK = loop.create_task(_tick_forever())


async def stop_scheduler() -> None:
    global _TASK
    if _TASK is not None:
        _TASK.cancel()
        try:
            await _TASK
        except (asyncio.CancelledError, Exception):
            pass
        _TASK = None


async def _tick_forever() -> None:
    while True:
        try:
            await asyncio.sleep(_monitors.limit("tick_s"))
            await tick_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A tick that raised must not take the loop with it. The
            # failure is already on the monitor's own record.
            pass


async def tick_once() -> dict:
    """One pass of the scheduler. Exposed so the pins can drive it
    deterministically rather than sleeping."""
    _monitors.STORE.load()
    now = time.time()
    due = [r for r in _active_monitors()
           if float(r.get("next_due", 0)) <= now]
    ran = []
    for record in due[:_monitors.limit("batch")]:
        if record.get("_running"):
            # A check still running when its next slot arrives is SKIPPED,
            # not queued behind itself, and the skip is counted so the
            # report can say a monitor's checks routinely outrun its
            # interval.
            record["checks_missed"] = int(record.get("checks_missed", 0)) + 1
            continue
        record["_running"] = True
        try:
            outcome = await _check_and_record(record)
        finally:
            record.pop("_running", None)
        ran.append({"monitor": record["id"], **outcome})
    if not _active_monitors():
        await _retire_session_if_idle()
    return {"checked": ran, "due": len(due)}


# --------------------------------------------------------------- the tool


async def monitor(
    action: str = "report",
    url: str | None = None,
    condition: str | None = None,
    value: str | None = None,
    selector: str | None = None,
    check_interval_minutes: int = 30,
    monitor: str | None = None,
    label: str | None = None,
    since: str | None = None,
) -> dict:
    """Watches one URL for one deterministic change while this server runs.
    Four conditions: content_hash, text_appears, text_gone, selector_count;
    the same page state always answers the same way. Nothing is pushed
    anywhere: report is how you ask what happened, and check_now forces a
    check. A monitor that could not check reports stale with the failure,
    never unchanged. Checks run in a dedicated headless session, never the
    caller's. There is a floor on the interval and caps on monitors and daily
    checks; a 429 is honored rather than retried; a monitor that keeps
    failing pauses itself.
    """
    action = _common_enum(action)
    _monitors.STORE.load()
    _audit.annotate(monitor=monitor)

    if action == "create":
        return await _create(url, condition, value, selector,
                             check_interval_minutes, label)
    if action == "list":
        return {
            "monitors": [{
                "monitor": r["id"], "label": r.get("label"),
                "url": r.get("url"), "condition": r.get("condition"),
                "value": r.get("value"), "selector": r.get("selector"),
                "interval_minutes": r.get("interval_minutes"),
                "state": r.get("state"), "created": r.get("created"),
                "origin_verdict_at_create": r.get(
                    "origin_verdict_at_create"),
            } for r in _monitors.STORE.monitors],
            "limits": _monitors.published_limits(),
        }
    if action == "report":
        return _report()
    if action == "check_now":
        record = _require(monitor)
        outcome = await _check_and_record(record)
        row = _monitors.state_of(record)
        return {"monitor": record["id"], "checked_now": outcome, **row,
                "limits": _monitors.published_limits()}
    if action in ("pause", "resume"):
        record = _require(monitor)
        record["state"] = "paused" if action == "pause" else "active"
        if action == "resume":
            record.pop("auto_paused", None)
            record.pop("auto_paused_why", None)
            record["consecutive_failures"] = 0
            record["next_due"] = time.time()
        record["state_changed_at"] = time.time()
        _monitors.STORE.save()
        if action == "resume":
            ensure_scheduler()
        else:
            await _retire_session_if_idle()
        return {"monitor": record["id"], "state": record["state"],
                **_monitors.state_of(record)}
    if action == "delete":
        record = _require(monitor)
        removed = _monitors.STORE.remove(record["id"])
        await _retire_session_if_idle()
        return {
            "deleted": removed["id"],
            "label": removed.get("label"),
            "url": removed.get("url"),
            "checks_run": int(removed.get("checks_run", 0)),
            "history_discarded": len(removed.get("history", [])),
            "note": ("the observations this monitor accumulated are gone "
                     "with it; nothing else holds a copy."),
        }
    raise BadParams(
        f"unknown monitor action {action!r}: the actions are "
        f"{sorted(ACTIONS)}.")


def _common_enum(action) -> str:
    from . import common as _common
    return _common.enum_arg(action, ACTIONS, default="report",
                            tool="monitor")


def _require(monitor_id: str | None) -> dict:
    if not monitor_id:
        raise BadParams(
            f"this action needs a monitor id, for example "
            f"monitor(action='pause', monitor='m1'). The open monitors are "
            f"{_monitors.STORE.known_ids() or 'none'}.")
    record = _monitors.STORE.get(monitor_id)
    if record is None:
        raise TargetNotFound(
            f"no monitor {monitor_id!r}. The monitors are "
            f"{_monitors.STORE.known_ids() or 'none'}. Ids are minted by "
            f"monitor(action='create') and are never reused.")
    return record


async def _create(url, condition, value, selector, interval, label) -> dict:
    from . import lite as _lite

    if condition not in _monitors.CONDITIONS:
        raise BadParams(
            f"unknown condition {condition!r}: the conditions are "
            f"{sorted(_monitors.CONDITIONS)}. Nothing was created.")
    spec = _monitors.CONDITIONS[condition]
    if spec["needs_value"] and not value:
        raise BadParams(
            f"the {condition!r} condition needs a `value`: the text to look "
            f"for, or the CSS selector to count. Nothing was created.")
    checked_url = _lite._validated_url(url)
    cap = _monitors.limit("max_monitors")
    if len(_monitors.STORE.monitors) >= cap:
        raise Conflict(
            f"this server already holds {len(_monitors.STORE.monitors)} "
            f"monitor(s) against a cap of {cap}, and each one is a page "
            f"load on a timer against somebody else's site. See what is "
            f"using the cap with monitor(action='list') and delete one, or "
            f"raise {_monitors.LIMIT_ENVS['max_monitors'][0]} at the next "
            f"launch. Nothing was created.")
    floor = _monitors.limit("min_interval_min")
    asked = interval if isinstance(interval, int) else 30
    minutes = max(floor, asked)
    # THE ORIGIN VERDICT IS RESOLVED NOW, while a human is in the loop, and
    # PINNED: no human is present at check time, so a gate encountered
    # there could only fail closed.
    verdict = _origins.check_navigation(checked_url, readonly.grade())
    if verdict == "off-list":
        # ONE DOOR. This asked the gate engine directly, which is the
        # twelfth door the consent wave closed on 2026-09-07 and the two
        # waves never saw each other: a door outside `policy.engine.confirm`
        # never sees the consent scope, so a pre-authorization a human wrote
        # applies to `navigate` and not to the monitor that navigates on a
        # timer. `confirm` also carries the unattended refusal, which is the
        # honest answer when a scheduler has nobody to ask.
        from ..policy import engine as _policy
        _policy.confirm(
            "navigation_offlist", tool="monitor", session=None, page=None,
            target=None, url=checked_url, kind="navigate",
            origin_verdict=verdict,
            summary=f"Create a monitor that will re-check {checked_url} "
                    f"every {minutes} minutes? That origin is outside "
                    f"{_origins.ENV_ALLOW}, and a scheduled check has no "
                    f"conversation to ask this in later.")
    record = {
        "id": _monitors.STORE.next_id(),
        "label": label,
        "url": checked_url,
        "origin_verdict_at_create": verdict,
        "condition": condition,
        "value": value,
        "selector": selector,
        "interval_minutes": minutes,
        "created": time.time(),
        "created_by_pid": _monitors.os.getpid(),
        "state": "active",
        "baseline": None,
        "last_value": None,
        "last_success_at": None,
        "last_attempt_at": None,
        "last_attempt_ok": None,
        "last_error": None,
        "consecutive_failures": 0,
        "checks_run": 0,
        "checks_missed": 0,
        "last_reported_at": None,
        "next_due": time.time() + minutes * 60,
        "history": [],
    }
    # THE BASELINE IS TAKEN NOW, synchronously, and a create that cannot
    # reach the page creates NOTHING. A monitor whose baseline is "we never
    # saw it" cannot report a change against anything.
    outcome = await _run_check(record, first=True)
    baseline = outcome["value"]
    record["baseline"] = {**baseline, "taken": time.time()}
    record["last_value"] = baseline
    now = time.time()
    record["last_success_at"] = now
    record["last_attempt_at"] = now
    record["last_attempt_ok"] = True
    record["checks_run"] = 1
    _monitors.STORE.add(record)
    ensure_scheduler()
    return {
        "monitor": record["id"],
        "label": label,
        "url": checked_url,
        "condition": condition,
        "value": value,
        "selector": selector,
        "interval_minutes": minutes,
        "baseline": record["baseline"],
        "what_it_notices": {"notices": spec["notices"],
                            "cannot": spec["cannot"]},
        "next_check_due": _monitors._iso(record["next_due"]),
        "origin_verdict_at_create": verdict,
        **({"clamped": (
            f"check_interval_minutes was clamped from {asked} to {minutes}: "
            f"the floor is {floor} minutes, because below it this server "
            f"is a scraper hammering somebody else's site.")}
           if asked != minutes else {}),
        **({"frames": (
            f"this page has {outcome['frames']} frame(s) and a monitor "
            f"reads the main document only, so anything inside them is not "
            f"watched.")} if outcome.get("frames") else {}),
        "stored": (
            "the URL is written to this machine's KS4Web state directory so "
            "the monitor survives a restart. Monitor a URL with no "
            "credentials in its query string."),
        "limits": _monitors.published_limits(),
    }


def _report() -> dict:
    _monitors.note_restart_gaps()
    rows = [_monitors.state_of(r) for r in _monitors.STORE.monitors]
    for entry in _monitors.STORE.unreadable:
        rows.append({
            "monitor": _unreadable_id(entry),
            "state": "blocked",
            "why": ("this monitor's stored record could not be read by this "
                    "version of KS4Web. It was left on disk unchanged and "
                    "excluded from scheduling; nothing was deleted."),
        })
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    # BROKEN FIRST. A monitor that is not working is more urgent than one
    # with nothing to report, and a caller who reads "unchanged" stops
    # looking.
    order = {"stale": 0, "blocked": 1, "suspended": 2, "changed": 3,
             "paused": 4, "never_checked": 5, "unchanged": 6}
    rows.sort(key=lambda r: order.get(r["state"], 9))
    now = time.time()
    for record in _monitors.STORE.monitors:
        record["last_reported_at"] = now
    if _monitors.STORE.monitors:
        _monitors.STORE.save()
    restart = [r for r in _monitors.STORE.monitors
               if r.get("restart_note")]
    return {
        "monitors": rows,
        "summary": ", ".join(f"{n} {state}"
                             for state, n in sorted(counts.items())) or
                   "no monitors are defined",
        **({"restart": [r["restart_note"] for r in restart]}
           if restart else {}),
        # THE SCHEDULER'S OWN BROWSER, named here rather than left to be
        # recognised in the session list. A monitor reporting `stale` and
        # a dead monitor browser are the same event seen from two ends,
        # and the field report's tester had to work that out by hand.
        **({"session": health} if (health := monitor_session_health())
           else {}),
        "checks_today": _monitors.STORE.checks_today.get("count", 0),
        "limits": _monitors.published_limits(),
        "how_this_works": (
            "monitors run only while this KS4Web process runs, and nothing "
            "is pushed to you: this report is how you ask. A monitor that "
            "could not check reports stale with the reason, never "
            "unchanged."),
    }


def _unreadable_id(entry) -> str:
    if isinstance(entry, dict) and isinstance(entry.get("id"), str):
        return entry["id"]
    return "(a record with no readable id)"


TOOLS = (monitor,)
