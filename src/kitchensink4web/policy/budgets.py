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

        The check runs BEFORE the increment, so the refusal fires on the
        first call past the limit and the counters it prints are the true
        spend, not the attempted one."""
        ledger = self._ledger(session)
        elapsed = time.monotonic() - ledger.started
        if elapsed > limit("wall_clock_s"):
            raise BudgetExhausted(
                f"the session wall-clock budget is spent: "
                f"{elapsed:.0f}s against {limit('wall_clock_s')}s. "
                f"{self._printed(session)} {RESET_ROUTE}")
        if kind in ("actions", "navigations", "downloads"):
            if ledger.counters[kind] >= limit(kind):
                raise BudgetExhausted(
                    f"the {kind} budget is spent: {ledger.counters[kind]} "
                    f"against {limit(kind)}. {self._printed(session)} "
                    f"{RESET_ROUTE}")
            ledger.counters[kind] += 1
        if origin:
            if (origin not in ledger.origins
                    and len(ledger.origins) >= limit("new_origins")):
                raise BudgetExhausted(
                    f"the distinct-origins budget is spent: {origin} would be "
                    f"origin {len(ledger.origins) + 1} against "
                    f"{limit('new_origins')}. {self._printed(session)} "
                    f"{RESET_ROUTE}")
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

    def note_429(self, domain: str, retry_after_s: float | None) -> float:
        """A site said slow down. Honor it: further requests to the domain
        refuse until the window passes."""
        wait = retry_after_s if (retry_after_s and retry_after_s > 0) \
            else DEFAULT_RETRY_AFTER_S
        until = time.monotonic() + wait
        self._backoff[domain.lower()] = max(
            self._backoff.get(domain.lower(), 0), until)
        return wait

    def check_domain(self, domain: str) -> None:
        until = self._backoff.get(domain.lower(), 0)
        remaining = until - time.monotonic()
        if remaining > 0:
            raise BlockedBySite(
                f"{domain} answered HTTP 429 and its Retry-After window has "
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
