"""Action budgets, loop detection, and per-domain rate limiting (DESIGN 5.5).

Only browser-use documents any of this, and no MCP server does. Maps to
OWASP LLM10, Unbounded Consumption.

Three mechanisms, one module, because they share the counters:

- **Per-session budgets.** Max actions, max navigations, max distinct new
  origins, max downloads, and a wall-clock ceiling. Generous defaults,
  finite always. On trip: `BUDGET_EXHAUSTED` with every counter printed and
  the reset route named. **The reset route runs through the confirmation
  gate so a human answers, because a budget the model can reset by calling
  a tool is not a budget.**

- **Loop detection.** A rolling window over (tool, target fingerprint,
  argument hash). Repetition beyond a threshold, or a two-step cycle that
  keeps alternating, trips `LOOP_DETECTED` with the observed cycle printed.
  browser-use's `loop_detection_window: 20` is the only prior art in the
  field and the window size is inherited from it.

- **Per-domain rate limiting**, honoring HTTP 429 and `Retry-After`, which
  also serves the honest-tool posture (DESIGN 5.8): a site that said "slow
  down" gets a refusal on our side, not a retry.

This module is policy: it holds its own counters keyed by session id and
imports nothing from ops/ or engine/. The engine's `session.counters` dict is
the REPORTING copy that `manage_session(action='budget')` shows; this one is
the ENFORCING copy, and the choke point (`policy/engine.py`) is where every
charge lands.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import Counter, deque
from dataclasses import dataclass, field

from ..errors import BlockedBySite, BudgetExhausted, LoopDetected

#: Env-tunable limits. Generous defaults, finite always: an unset limit is a
#: default, never infinity.
LIMIT_ENVS: dict[str, tuple[str, int]] = {
    "actions": ("KS4WEB_MAX_ACTIONS", 300),
    "navigations": ("KS4WEB_MAX_NAVIGATIONS", 150),
    "new_origins": ("KS4WEB_MAX_NEW_ORIGINS", 30),
    "downloads": ("KS4WEB_MAX_DOWNLOADS", 40),
    "wall_clock_s": ("KS4WEB_MAX_SESSION_S", 4 * 3600),
}

LOOP_WINDOW = int(os.environ.get("KS4WEB_LOOP_WINDOW", "20"))
#: The same call this many times inside the window is a loop.
LOOP_REPEAT_THRESHOLD = int(os.environ.get("KS4WEB_LOOP_REPEATS", "5"))
#: An A-B-A-B alternation sustained this many full cycles is a loop too;
#: cycling between two failing calls is the commonest real loop shape.
LOOP_CYCLE_THRESHOLD = 4

#: When a 429 arrives without a Retry-After header, this is the honored wait.
DEFAULT_RETRY_AFTER_S = 60.0

#: Statuses that carry a rate limit or a temporary refusal with a wait
#: attached. 503 belongs here and was missing: an edge under load and a
#: Cloudflare "come back later" both answer 503 with `Retry-After`, and the
#: header was read on 429 alone, so the one case that most needs the number
#: reported was the case that dropped it.
RETRY_AFTER_STATUSES: frozenset[int] = frozenset({429, 503})

#: Nothing longer than this is honored as a backoff window. A header saying
#: "come back in three weeks" is a real answer and a useless timer: it is
#: reported as the fact it is and clamped for the purpose of the in-memory
#: window, which exists to stop a retry loop rather than to schedule one.
MAX_RETRY_AFTER_S = 24 * 3600.0


def parse_retry_after_unclamped(raw: str | None, *, now: float | None = None
                                ) -> float | None:
    """What the header SAID, in seconds, before the ceiling is applied.

    Split out from `parse_retry_after` for one reason: a caller that clamps
    has to be able to say so, and a value that arrives already clamped
    carries no evidence that it was. The clamp is a KS4Web decision and gets
    reported as one (fix wave 2026-09-08, V-07).

    Negative is still floored at zero here, because that is not a clamp: a
    wait that already elapsed is zero seconds of waiting, not a shortened
    version of some longer number the site sent."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        pass
    else:
        if seconds != seconds or seconds in (float("inf"), float("-inf")):
            return None
        return max(0.0, seconds)
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    try:
        from datetime import timezone
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        current = time.time() if now is None else now
        delta = when.timestamp() - current
    except (OverflowError, OSError, ValueError):
        return None
    return max(0.0, delta)


def parse_retry_after(raw: str | None, *, now: float | None = None
                      ) -> float | None:
    """`Retry-After` in seconds, from either spelling RFC 9110 allows.

    Two forms are legal and only one was read before: delta-seconds, and an
    HTTP-date. A date-form header parsed as a number is a header thrown away,
    and the sites most likely to send the date form are exactly the edges that
    rate-limit hardest.

    A date already in the past yields 0.0 rather than a negative wait, which
    means "the window has passed" and is a different fact from "there was no
    header". Anything unparseable yields None, and None is honest: the caller
    then falls back to the documented default instead of inventing a number
    from a malformed string."""
    seconds = parse_retry_after_unclamped(raw, now=now)
    if seconds is None:
        return None
    return min(seconds, MAX_RETRY_AFTER_S)

RESET_ROUTE = (
    "manage_session(action='reset_budgets') is the reset route, and it runs "
    "through the confirmation gate so a human answers it. A budget the model "
    "could reset by calling a tool would not be a budget.")


def limit(name: str) -> int:
    env, default = LIMIT_ENVS[name]
    try:
        value = int(os.environ.get(env, default))
    except ValueError:
        value = default
    return max(1, value)


@dataclass
class _SessionLedger:
    started: float = field(default_factory=time.monotonic)
    counters: Counter = field(default_factory=Counter)
    origins: set[str] = field(default_factory=set)
    window: deque = field(default_factory=lambda: deque(maxlen=LOOP_WINDOW))


class BudgetBook:
    """The enforcing counters, one ledger per session id."""

    def __init__(self) -> None:
        self._ledgers: dict[str, _SessionLedger] = {}
        #: domain -> monotonic time before which requests are refused.
        self._backoff: dict[str, float] = {}
        #: domain -> (status, came_from_a_header) for the window currently in
        #: force, so the refusal names the response that caused it instead of
        #: assuming one. Carried alongside rather than inside `_backoff`,
        #: because the timing dict is cleared directly by fixtures and a
        #: second dict that goes stale costs nothing: it is only read while a
        #: window is live.
        self._backoff_why: dict[str, tuple[int, bool]] = {}

    def _ledger(self, session: str) -> _SessionLedger:
        return self._ledgers.setdefault(session, _SessionLedger())

    # ------------------------------------------------------------- budgets

    def snapshot(self, session: str) -> dict:
        ledger = self._ledger(session)
        return {
            "counters": {k: ledger.counters.get(k, 0)
                         for k in ("actions", "navigations", "downloads")},
            "distinct_origins": len(ledger.origins),
            "wall_clock_s": round(time.monotonic() - ledger.started, 1),
            "limits": {k: limit(k) for k in LIMIT_ENVS},
        }

    def charge(self, session: str, kind: str, origin: str | None = None
               ) -> None:
        """Charge one unit against a budget, refusing when it is exhausted.

        EVERY check runs before EVERY increment (endurance F6). The
        docstring's own claim — "the counters it prints are the true spend,
        not the attempted one" — was true of the counter being checked and
        false of the one billed alongside it: the navigation increment ran
        first, so a call the ORIGIN check refused printed
        `navigations=31` for 30 navigations performed, and a session hitting
        off-list origins walked its navigation budget down for work that
        never happened."""
        ledger = self._ledger(session)
        elapsed = time.monotonic() - ledger.started
        if elapsed > limit("wall_clock_s"):
            raise BudgetExhausted(
                f"the session wall-clock budget is spent: "
                f"{elapsed:.0f}s against {limit('wall_clock_s')}s. "
                f"{self._printed(session)} {RESET_ROUTE}")
        counted = kind in ("actions", "navigations", "downloads")
        if counted and ledger.counters[kind] >= limit(kind):
            raise BudgetExhausted(
                f"the {kind} budget is spent: {ledger.counters[kind]} "
                f"against {limit(kind)}. {self._printed(session)} "
                f"{RESET_ROUTE}")
        if origin and origin not in ledger.origins \
                and len(ledger.origins) >= limit("new_origins"):
            raise BudgetExhausted(
                f"the distinct-origins budget is spent: {origin} would be "
                f"origin {len(ledger.origins) + 1} against "
                f"{limit('new_origins')}. {self._printed(session)} "
                f"{RESET_ROUTE}")
        # Both checks passed; now spend. No await between the checks and the
        # increments, so asyncio cannot interleave a second charge into the
        # gap (the property the concurrency round verified and this
        # reordering has to preserve).
        if counted:
            ledger.counters[kind] += 1
        if origin:
            ledger.origins.add(origin)

    def _printed(self, session: str) -> str:
        snap = self.snapshot(session)
        counts = ", ".join(f"{k}={v}" for k, v in snap["counters"].items())
        return (f"Counters: {counts}, distinct_origins="
                f"{snap['distinct_origins']}, wall_clock_s="
                f"{snap['wall_clock_s']}.")

    def reset(self, session: str, granted_by_gate: str) -> dict:
        """Reset one session's ledger. The ONLY caller is the choke point
        after a redeemed confirmation gate; `granted_by_gate` is the redeemed
        requestState token and is recorded in the audit trail."""
        if not granted_by_gate:
            raise BudgetExhausted(
                "a budget reset needs a redeemed confirmation gate; nothing "
                "was reset. " + RESET_ROUTE)
        before = self.snapshot(session)
        self._ledgers.pop(session, None)
        return {"reset": True, "granted_by_gate": granted_by_gate,
                "before": before}

    def drop(self, session: str) -> None:
        """Session closed; its ledger goes with it. Not a reset: a NEW
        session starting fresh is the designed behavior, and the wall-clock
        and origin budgets are per-session by definition."""
        self._ledgers.pop(session, None)

    # ------------------------------------------------------ loop detection

    def note_call(self, session: str, tool: str, target_fp: str | None,
                  args_fp: str | None) -> None:
        """Slide the window and trip on repetition or a two-step cycle."""
        ledger = self._ledger(session)
        signature = (tool, target_fp or "", args_fp or "")
        ledger.window.append(signature)
        window = list(ledger.window)
        if window.count(signature) >= LOOP_REPEAT_THRESHOLD:
            raise LoopDetected(
                f"the same call has repeated {window.count(signature)} times "
                f"in the last {len(window)} calls: {tool} on "
                f"{target_fp or '(no target)'} with identical arguments. "
                f"Observed cycle: {self._cycle_text(window)} Repeating it "
                f"again will not produce a different page; change approach, "
                f"or re-read the page to see what actually changed.")
        tail = window[-2 * LOOP_CYCLE_THRESHOLD:]
        if len(tail) == 2 * LOOP_CYCLE_THRESHOLD:
            a, b = tail[0], tail[1]
            if a != b and tail == [a, b] * LOOP_CYCLE_THRESHOLD:
                raise LoopDetected(
                    f"the last {len(tail)} calls alternate between two "
                    f"identical calls: {a[0]} on {a[1] or '(no target)'} and "
                    f"{b[0]} on {b[1] or '(no target)'}. Observed cycle: "
                    f"{self._cycle_text(tail)} Change approach rather than "
                    f"retrying.")

    @staticmethod
    def _cycle_text(window: list[tuple]) -> str:
        shown = [f"{t}({fp or '-'})" for t, fp, _ in window[-8:]]
        return " -> ".join(shown) + "."

    # -------------------------------------------------------- rate limiting

    def note_429(self, domain: str, retry_after_s: float | None, *,
                 status: int = 429) -> float:
        """A site said slow down. Honor it: further requests to the domain
        refuse until the window passes.

        NONE AND ZERO ARE DIFFERENT ANSWERS (fix wave 2026-09-08, V-07).
        `parse_retry_after` returns None for "there was no header" and 0.0 for
        "the window has already passed", and its docstring says the
        distinction matters; this method then tested the value for truth, so
        0.0 took the None branch and `Retry-After: 0` became a sixty-second
        block that the report attributed to the site. Only None takes the
        documented default now.

        An explicit zero neither opens a window nor closes one. It cannot
        open one, because a site saying "retry now" has asked for no wait at
        all and inventing one is the same fabrication in the other direction.
        It cannot close one, because the `max` below is the rule that a window
        only ever grows, and a zero that shortened an earlier 300-second
        window would let one response cancel a wait it never set."""
        wait = DEFAULT_RETRY_AFTER_S if retry_after_s is None \
            else max(0.0, min(float(retry_after_s), MAX_RETRY_AFTER_S))
        if wait <= 0:
            return 0.0
        key = domain.lower()
        until = time.monotonic() + wait
        if until >= self._backoff.get(key, 0):
            # The status is recorded WITH the window it opened, so the
            # refusal names the response that actually caused it, and so is
            # whether a header supplied the number at all. Only the response
            # that owns the current window gets to name it.
            self._backoff_why[key] = (int(status), retry_after_s is not None)
        self._backoff[key] = max(self._backoff.get(key, 0), until)
        return wait

    def note_retry_after(self, domain: str, raw_header: str | None, *,
                         status: int | None = None,
                         budget_ms: int | None = None) -> dict:
        """Honor a rate-limit response and report what was honored.

        KS4Web does not sleep here, and the reason is the caller's budget:
        `timeout_ms` is what the caller allotted for a navigation, and burning
        it inside a wait would turn an honest "the site asked for 90 seconds"
        into a timeout that blames the wrong thing. The window is recorded so
        the next request to the domain refuses instead of retrying into the
        wall, and the number is handed back as a fact for the caller to
        schedule around.

        `fits_in_budget` is the honest half of "respect it within the tool's
        bounds": it says whether the wait would have fitted inside the
        allotment this call was given, so the caller can tell a two-second
        pause from a two-hour one without doing the arithmetic."""
        asked = parse_retry_after_unclamped(raw_header)
        parsed = None if asked is None else min(asked, MAX_RETRY_AFTER_S)
        wait = self.note_429(domain, parsed,
                             status=status if status is not None else 429)
        report = {
            "seconds": round(wait, 1),
            "source": "Retry-After header" if parsed is not None
                      else "no Retry-After header; KS4Web's default window",
            "header": (raw_header or "").strip() or None,
            "honored": True,
            "waited": False,
            "domain": domain.lower(),
        }
        if status is not None:
            report["status"] = status
        if raw_header and parsed is None:
            report["header_unparsed"] = True
        if asked is not None and asked > MAX_RETRY_AFTER_S:
            # THE CLAMP IS DISCLOSED, in the shape `export_handle` already
            # uses for its TTL (fix wave 2026-09-08, V-07). A three-week
            # header reported as `seconds: 86400, source: Retry-After header`
            # is KS4Web's ceiling wearing the site's name.
            # FLAGGED (fix wave 2026-09-08): placeholder wording,
            # mechanically composed from MAX_RETRY_AFTER_S's own comment and
            # export_handle's clamp sentence.
            report["clamped"] = (
                f"Retry-After was clamped from {round(asked, 1)}s to "
                f"{round(wait, 1)}s; the ceiling is "
                f"{round(MAX_RETRY_AFTER_S, 1)}s, because the window exists "
                f"to stop a retry loop rather than to schedule one.")
        if budget_ms:
            report["call_budget_s"] = round(budget_ms / 1000.0, 1)
            report["fits_in_budget"] = wait <= (budget_ms / 1000.0)
        return report

    def remaining_backoff_s(self, domain: str) -> float:
        """How much of this domain's window is left, in seconds, or 0.0.

        The book's own number, read rather than recovered (fix wave
        2026-09-08, V-17). `monitor._remaining_backoff` used to regex the
        digits back out of `check_domain`'s refusal sentence, which made a
        user-facing string into load-bearing API: rewording the refusal would
        have silently changed how long a monitor recorded itself blocked."""
        remaining = self._backoff.get(domain.lower(), 0) - time.monotonic()
        return max(0.0, remaining)

    def backoff_why(self, domain: str) -> tuple[int, bool]:
        """(status, came_from_a_header) for the window in force here."""
        return self._backoff_why.get(domain.lower(), (429, False))

    def check_domain(self, domain: str) -> None:
        remaining = self.remaining_backoff_s(domain)
        if remaining > 0:
            # THE STATUS IS THE ONE THAT ANSWERED, and the window is named
            # for whoever set its length (fix wave 2026-09-08, V-17).
            # `RETRY_AFTER_STATUSES` holds 503 as well as 429, so a
            # Cloudflare "come back later" opened a window this sentence
            # reported as a 429 the site never sent; and a 429 with no header
            # at all opened KS4Web's own default window, which this sentence
            # called the site's Retry-After.
            # FLAGGED (fix wave 2026-09-08): placeholder wording,
            # mechanically composed from note_retry_after's own `source`
            # strings. The sentence is otherwise unchanged.
            status, from_header = self.backoff_why(domain)
            whose = "its Retry-After window" if from_header \
                else "KS4Web's default window"
            raise BlockedBySite(
                f"{domain} answered HTTP {status} and {whose} has "
                f"{remaining:.0f}s left. KS4Web honors a site's rate limit "
                f"rather than retrying against it; wait, or work on another "
                f"origin meanwhile.")


def fingerprint(payload) -> str:
    """A short stable hash for loop-detection signatures. Not a security
    primitive; a collision costs one early refusal at worst."""
    text = repr(payload)
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]


#: The process book. The choke point charges against it; tests may replace
#: ledgers via `drop`.
BOOK = BudgetBook()
