"""The session and page handle model, and the browser manager that owns them.

MCP 2026-07-28 removed protocol sessions and names browser automation as its
motivating example: servers that need state across calls, "an open browser
context," should return an explicit handle from a creation tool and accept it
as an argument afterward. So `manage_session` mints `s1` and `manage_tabs`
mints `p1`, and every other tool takes them (DESIGN 7.1).

What this module owns:

- one `async_api` Playwright instance across tool calls, started lazily on the
  first session and stopped when the last one closes, so a server nobody asks
  to browse never spawns a Node driver at all
- an asyncio lock around context mutation, because two tool calls can land
  concurrently the moment reads are marked `readOnlyHint: true`
- a bounded per-operation timeout, which S7 measured as genuinely freeing the
  server: a `goto` against an endpoint that never answers returned at 3,017 ms
  against a 3,000 ms budget and the browser stayed usable
- the owned-PID journal and the idle park, wired to `hygiene.py`
- **the page history we keep ourselves**, which is what lets the Firefox
  back/forward refusal name a working substitute instead of just saying no

Two safety properties are enforced here rather than documented:
`-no-remote` rides on every Firefox launch through `lanes.launch_kwargs`, and
every profile directory is a freshly created empty one under
`hygiene.new_profile_dir`. KS4Web never opens the user's real profile.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .. import anchors
from .. import dialogs as _dialogs
from ..envelope import CRASHED_HINT as CRASHED_PAGE_HINT
from ..errors import (BadParams, Conflict, LaneUnsupported, ModalBlocked,
                      SessionDead, StaleAnchor, TargetNotFound, Timeout,
                      ValidationFailed)
from ..projection import CLOSED_SHADOW_HOOK
from ..projection.meter import warm as _warm_estimator
from . import hygiene, lanes

#: Bounded per-operation timeout. Generous, finite always.
DEFAULT_TIMEOUT_MS = int(os.environ.get("KS4WEB_TIMEOUT_MS", "30000"))

#: The two IDLE ADVISORY bounds. They decide when `manage_session(status)`
#: calls a session quiet and prints the close advice, and they do nothing
#: else. DESIGN 4.7 frames parking as Defense 3, and the measurement behind
#: it is real (a dormant page burning 28 to 30 percent CPU for hours, down
#: to 0.13 percent parked).
#:
#: NOTHING PARKS AND NOTHING RECYCLES ON ITS OWN, and the surface says so
#: (endurance F3, closed 2026-09-07). `park_idle` was implemented, complete,
#: and had no caller anywhere in the shipped tree, while the status payload
#: reported these bounds inside the same hygiene block as the job object and
#: the startup reaper — both of which are real — so an inert mechanism read
#: as a live defense. A session left alone for 6.7x the recycle bound still
#: held five browser processes and about 500 MB.
#:
#: The mandate was "wire it or remove the claim, and the shipped behaviour
#: must be honest". WIRING IT WAS BUILT AND REVERTED the same night, on the
#: lifecycle review's evidence: an automatic recycle closes a session out
#: from under a caller, and with no session TOMBSTONE the next call answers
#: "no session 's1'", which is indistinguishable from a close the caller
#: made itself; the same review has the coming session-handoff feature
#: depending on pages NOT being parked. Reintroducing parking needs
#: tombstones built alongside it, which is a lifecycle-build job. What ships
#: is the truth: these bounds only decide when the advisory speaks, and
#: closing a session is the caller's move.
#:
#: `park_idle` stays as an explicitly-called method, carrying the
#: ref-invalidation it always needed, so that build inherits a correct
#: mechanism rather than a landmine.
IDLE_PARK_S = float(os.environ.get("KS4WEB_IDLE_PARK_S", "300"))
IDLE_CLOSE_S = float(os.environ.get("KS4WEB_IDLE_CLOSE_S", "1800"))

PARKED_URL = "about:blank"

#: How many pre-frame navigation responses a session parks for its popups.
#: Was 16, which a 25-popup flood defeated deterministically (concurrency
#: C-2). Each entry is a URL, a status, and a header dict, so the memory at
#: this bound is trivial next to one page.
PENDING_NAV_MAX = 512

#: The pack-recorder seam. Ops modules (network, diagnostics, files) append
#: a callable here at import; every newly opened session is passed through
#: each one so recorders attach their event listeners at open rather than at
#: first read, which is the difference between "the log starts when the
#: session does" and "the log starts when somebody remembered to ask".
#: Each hook checks its own pack is loaded before doing anything, so an
#: imported-but-unselected pack records nothing. Hooks are synchronous and
#: their failures propagate: a recorder that cannot attach is a launch
#: problem to surface, not one to swallow.
#:
#: SIGNATURE: `hook(session, contexts)`, where `contexts` is the list of
#: ContextHandles this call is responsible for. A recorder must attach to
#: EVERY cookie jar or a page in the second one records nothing while its
#: tool reports an empty list as though that were the truth, and passing
#: only the new jars is what lets a context added to a live session get its
#: listeners without the existing jars getting a second copy.
SESSION_OPEN_HOOKS: list = []

#: HOW MANY CLOSED SESSIONS ARE REMEMBERED (defect D3, lifecycle review).
#: A closed session used to leave nothing at all: `close()` popped it from
#: the dict and deleted its journal file, so `MANAGER.session('s1')`
#: afterwards could only say the handle is not open. That one message had
#: to serve four different situations — you closed it, something recycled
#: it, its browser crashed, or you are talking to a different server
#: process — and a caller cannot act on the difference it is not told.
#: The ring is in memory and bounded, and it is deliberately not persisted:
#: its whole job is to explain a disappearance INSIDE one process, and a
#: token presented to a different process is already answered by the
#: process-identity check with a better message.
TOMBSTONE_MAX = 32

#: The closed set of reasons a session can end. `crash` is derived rather
#: than declared: a close that finds every owned PID already gone did not
#: happen the way an explicit close does, and saying so is free.
CLOSE_REASONS = ("explicit_close", "idle_recycle", "crash", "shutdown")

#: HOW MANY COOKIE JARS ONE SESSION MAY HOLD. Each is a separate browser
#: process on its own profile directory, so the cap is about memory on this
#: machine rather than about anything the driver limits.
ENV_MAX_CONTEXTS = "KS4WEB_MAX_CONTEXTS"


def _max_contexts() -> int:
    try:
        return max(1, int(os.environ.get(ENV_MAX_CONTEXTS, "4")))
    except ValueError:
        return 4


MAX_CONTEXTS = _max_contexts()


@dataclass
class PageHandle:
    """One page, its handle, and the history KS4Web tracks itself."""

    handle: str
    page: Any
    #: WHICH COOKIE JAR THIS PAGE LIVES IN. Handles stay flat and globally
    #: unique, so this is reporting rather than addressing: every payload
    #: that lists pages says which context each belongs to, and a per-jar
    #: call reaches the right one without the caller having to know.
    context: str = "c1"
    history: list[str] = field(default_factory=list)
    opened: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    parked: bool = False
    last_status: int | None = None
    last_load_state: str = "load"
    #: Set when the renderer crashed (the driver's `crash` event, or a
    #: "Page crashed" driver error). A crashed page never recovers: every
    #: later call through this handle refuses and names the recovery
    #: (gauntlet 2026-09-06, M1: a deep-DOM hostile page crashed the
    #: renderer and the poisoned handle kept answering with a misleading
    #: BAD_PARAMS).
    crashed: str | None = None
    #: STICKY FRAME IDS, keyed by the frame's identity rather than by its
    #: position in the tree. Discovery order is not an identity: removing the
    #: first of three frames renumbers the other two, and a ref carrying a
    #: renumbered frame (`if2e5`) would then address a different document
    #: while looking unchanged. The key is the parent's own id plus the ref
    #: the parent minted for the `<iframe>` ELEMENT, which is monotonic per
    #: element for the life of the document, so a frame keeps its id while it
    #: exists and its id is never handed to another frame afterward.
    frame_ids: dict = field(default_factory=dict)
    frame_seq: int = 0
    #: THE LAST NAVIGATION RESPONSE, per realm (gauntlet 3, F4). The wall
    #: verdict needs the status and headers of the response that produced
    #: the CURRENT document, and only `navigate` used to hold one (its own
    #: goto's). A click that navigates, a read_pages hop, and a child frame
    #: landing on a challenge all navigate without a response in hand, so a
    #: page-level listener records the last main-frame navigation response
    #: here and the last per-child-frame ones in `frame_nav`, keyed by the
    #: driver's Frame object and pruned so a frame-churning page cannot grow
    #: it without bound.
    #: The URL that response was for (gauntlet 4, G4-04). A recorded status
    #: is only evidence about the document that is on screen NOW, and a page
    #: can push a main-frame navigation to something else afterwards, so
    #: every consumer that reads the record outside a navigation it just
    #: performed compares this against `page.url` first and ignores a
    #: mismatched record rather than reasoning from a stale one.
    last_nav_url: str | None = None
    last_nav_status: int | None = None
    last_nav_headers: dict | None = None
    frame_nav: dict = field(default_factory=dict)
    #: THE URL THE ORIGIN POLICY LAST RULED ON for this page (gauntlet 4,
    #: G4-04 / G4-05 / G4-06). A page can arrive at a URL no tool asked for:
    #: a meta refresh, a `location.href` assignment, or a popup the browser
    #: opened from `window.open`. Comparing this against `page.url` is how
    #: the read and act surfaces know the document in front of them has
    #: never been through the deny/allow lists, and it is set only where a
    #: check actually passed.
    vetted_url: str | None = None
    #: True when the BROWSER opened this page (a `window.open` popup adopted
    #: by the context hook) rather than a tool call. Such a page's own first
    #: navigation response is the one `pending_nav` parks, so a missing
    #: record here means something different than it does on a page a tool
    #: navigated (concurrency C-2).
    adopted: bool = False
    #: Where the page was when `park_idle` parked it. The recovery a later
    #: call needs is the URL, not the word "parked".
    parked_from: str | None = None
    #: THE LAST NAVIGATION THAT DID NOT FINISH, and the URL it was for
    #: (chaos C-08). A body reset mid-transfer, a load event that never
    #: fires, a slow-loris origin: `navigate` refuses honestly and the very
    #: next read used to report the half-delivered document as complete,
    #: with `load: load` asserted for a load state the previous call had
    #: refused to reach. Cleared by the next navigation that succeeds.
    load_failed: dict | None = None
    #: THE PER-PAGE WRITE LOCK (concurrency C-3). Nothing serialized writes
    #: to a page or to an element: `SessionManager._lock` guards session
    #: open and close and nothing else, so four concurrent `type_text` calls
    #: interleaved at the KEYSTROKE level and left a field holding
    #: `vvaalvl0a1vla2l3` while all four returned ok, and two concurrent
    #: `fill_form` calls left one field holding both values concatenated
    #: while both callers held receipts saying their own clean value was
    #: set. The sibling document servers state the opposite property
    #: outright ("COM calls serialize server-side: one call reaches Word at
    #: a time, concurrent live calls queue"); here there was no queue.
    #: Created on first use, because a Lock binds to the running loop.
    _writes: Any = None

    def write_lock(self):
        if self._writes is None:
            self._writes = asyncio.Lock()
        return self._writes

    def frame_id(self, key: str) -> str:
        if key not in self.frame_ids:
            self.frame_seq += 1
            self.frame_ids[key] = f"if{self.frame_seq}"
        return self.frame_ids[key]

    def touch(self, url: str | None = None) -> None:
        self.last_used = time.time()
        self.parked = False
        if url and (not self.history or self.history[-1] != url):
            self.history.append(url)

    @property
    def previous_url(self) -> str | None:
        return self.history[-2] if len(self.history) > 1 else None


def _fresh_counters() -> dict[str, int]:
    return {"navigations": 0, "reads": 0, "actions": 0, "pages_opened": 0,
            "origins": 0}


@dataclass
class ContextHandle:
    """ONE COOKIE JAR: a browser context, the profile it runs on, and the
    processes it owns.

    A persistent context has no `.browser`, so `browser.new_context()` is
    not reachable from the way this server launches (`lanes` builds
    `launch_persistent_context` kwargs). A second cookie jar is therefore a
    second browser process on its own KS4Web-owned profile directory, which
    costs real memory and is stated rather than hidden, and which buys
    isolation strictly stronger than sibling contexts give: separate
    profiles, separate processes, no shared storage partition, and crash
    isolation for free. Every existing mechanism (the launch kwargs, the
    `-no-remote` Firefox rule, the owned-PID journal, `adopt_descendants`,
    profile-tree removal, the instrument channel, the dialog desk, the
    context-level page adoption hook and response recorder) then works per
    context with no change to its own logic."""

    label: str
    context: Any
    profile_dir: str
    journal: hygiene.OwnedProcesses
    spec: lanes.LaneSpec
    opened: float = field(default_factory=time.time)
    #: THE REPORTING COUNTERS LIVE HERE, not on the session, so the
    #: per-context breakdown is real rather than derived and the session
    #: line is the sum of real numbers rather than a second copy of them.
    #: The ENFORCING ledger stays session-wide in `policy/budgets`.
    counters: dict[str, int] = field(default_factory=_fresh_counters)
    #: An auth save is per cookie jar by definition, so the save history
    #: that lets the close message tell the truth (field finding 41) is per
    #: jar too. A session-level "none were saved" while c2 was in fact
    #: saved is that same wrong answer in a new shape.
    saved_auth_at: float | None = None
    saved_auth_path: str | None = None

    def alive(self) -> bool | None:
        """Is this jar's browser actually running? None means cannot tell."""
        pids = list(self.journal.pids)
        if not pids:
            return None
        if self.journal.survivors():
            return True
        if not hygiene.WINDOWS:
            return None
        return False

    def record_auth_save(self, path: str) -> None:
        self.saved_auth_at = time.time()
        self.saved_auth_path = path


@dataclass
class Session:
    """One or more cookie jars, their pages, and everything owned alongside.

    PAGE HANDLES STAY FLAT AND GLOBALLY UNIQUE (`p1`, `p2`, `p3`) rather
    than being namespaced per context. `MANAGER.locate` scans every session
    and every page and the whole codebase depends on a bare handle being
    unambiguous; refs are session-unique for the same reason. What changes
    under multiple contexts is that every payload listing pages says which
    jar each page belongs to."""

    session_id: str
    spec: lanes.LaneSpec
    contexts: dict[str, ContextHandle] = field(default_factory=dict)
    focused_context: str = "c1"
    pages: dict[str, PageHandle] = field(default_factory=dict)
    focused: str | None = None
    opened: float = field(default_factory=time.time)
    origins: set[str] = field(default_factory=set)
    #: NAVIGATION RESPONSES THAT ARRIVED BEFORE THEIR PAGE DID (gauntlet
    #: 4, G4-05). A popup's own first navigation is issued BEFORE the
    #: frame that will hold it exists — the driver refuses to name a
    #: frame for it at all — so the per-page recorder cannot have seen
    #: it and there is no record to write it on either. Without this the
    #: read surfaces held an adopted popup with no recorded status and
    #: served a 403 interstitial as ordinary content. Keyed by the
    #: response URL, because the URL is the only identity such a response
    #: carries; claimed by `nav_record` the first time a tool asks about
    #: the page that landed there, and bounded so a popup-spamming site
    #: cannot grow it.
    pending_nav: dict = field(default_factory=dict)
    #: How many pending records the bound has had to drop. Concurrency C-2:
    #: the bound was 16, a page opening 25 popups evicted the first nine,
    #: and the adopted popups with no surviving record then served a 403
    #: interstitial behind `cf-mitigated: challenge` as ordinary content —
    #: the exact defect G4-05 was written to close, reappearing whenever a
    #: site opens more windows than the buffer holds. The bound is now large
    #: enough that a session has to be pathological to reach it, and when it
    #: IS reached the count is what lets a read say it cannot rule.
    pending_nav_evicted: int = 0
    #: The sticky element map and the delta store, per SESSION rather than
    #: per page, because refs are unique across the session (DESIGN 3.5) so a
    #: bare `e12` is never ambiguous. The engine owns them and the anchors
    #: package never learns what a browser is.
    element_map: Any = field(default_factory=anchors.ElementMap)
    reads: Any = field(default_factory=anchors.ReadStore)
    #: What the caller asked this context to look like at open (device
    #: preset, viewport, locale, time zone). Empty means every default is
    #: untouched, which is the common case and is worth being able to SAY:
    #: a status that reports an emulation nobody set is as misleading as one
    #: that hides an emulation somebody did.
    emulation: dict = field(default_factory=dict)
    #: The launch kwargs that emulation resolved to, kept so a context
    #: added later is built the same way. Every context in a session shares
    #: the session's lane and its emulation: a session is one lane by
    #: definition, `sess.spec` is read all over the ops layer for
    #: capability reporting, and a per-context lane would turn the
    #: capabilities truth table into a per-page question. A caller who
    #: wants two lanes wants two sessions. Per-context locale and time
    #: zone is the natural later extension and is not in this version.
    emulation_kwargs: dict = field(default_factory=dict)
    #: WHO OPENED THIS SESSION AND WHAT IT IS FOR. `user` is a session some
    #: conversation asked for; `monitor` is the one the monitor scheduler
    #: owns (feature #8). The distinction is load-bearing in three places:
    #: the single-session shortcut in `SessionManager.session(None)` must
    #: not hand a caller the scheduler's browser, the status report must
    #: name a browser process the user did not open, and a handle transfer
    #: refuses to hand the scheduler's session to a conversation that would
    #: then fight it for the same page.
    role: str = "user"

    # ----------------------------------------------------- the focused jar

    @property
    def jar_handle(self) -> ContextHandle:
        handle = self.contexts.get(self.focused_context)
        if handle is None:
            handle = next(iter(self.contexts.values()))
        return handle

    @property
    def context(self) -> Any:
        """The FOCUSED jar's Playwright context, so nothing breaks on a
        single-context session. Every call site that means "one cookie jar"
        should reach it through `jar()` instead, which refuses rather than
        guessing when there is more than one."""
        return self.jar_handle.context

    @property
    def journal(self) -> Any:
        return self.jar_handle.journal

    @property
    def profile_dir(self) -> str:
        return self.jar_handle.profile_dir

    @property
    def saved_auth_at(self) -> float | None:
        return self.jar_handle.saved_auth_at

    @property
    def saved_auth_path(self) -> str | None:
        return self.jar_handle.saved_auth_path

    @property
    def counters(self) -> dict[str, int]:
        """The session line, SUMMED from the per-context counters rather
        than kept as a second copy of them. Read-only by construction: a
        `counters[k] += 1` against this would be lost, which is why every
        writer goes through `bump()`."""
        total = _fresh_counters()
        for handle in self.contexts.values():
            for key, value in handle.counters.items():
                total[key] = total.get(key, 0) + value
        total["origins"] = len(self.origins)
        return total

    def bump(self, kind: str, page: str | None = None,
             context: str | None = None) -> None:
        """Increment one reporting counter on the jar that earned it."""
        label = context
        if label is None and page is not None:
            record = self.pages.get(page)
            label = getattr(record, "context", None)
        handle = self.contexts.get(label or self.focused_context)
        if handle is None and self.contexts:
            handle = next(iter(self.contexts.values()))
        if handle is not None:
            handle.counters[kind] = handle.counters.get(kind, 0) + 1

    def record_auth_save(self, path: str, context: str | None = None) -> None:
        self.jar(context).record_auth_save(path)

    def jar(self, label: str | None = None) -> ContextHandle:
        """Resolve one cookie jar, REFUSING rather than guessing.

        The same doctrine `SessionManager.session(None)` applies when
        several sessions are open: name the one you mean rather than
        letting the server pick. A single-context session keeps the current
        implicit behaviour exactly, so nothing existing changes."""
        if label is None:
            if len(self.contexts) <= 1:
                return self.jar_handle
            raise BadParams(
                f"session {self.session_id} has {len(self.contexts)} "
                f"separate cookie jars ({sorted(self.contexts)}) and this "
                f"call acts on one of them, so name the one you mean with "
                f"context=... rather than letting the server pick. This is "
                f"the same rule that applies when several sessions are "
                f"open.")
        if label not in self.contexts:
            raise TargetNotFound(
                f"no context {label!r} in session {self.session_id}. The "
                f"contexts are {sorted(self.contexts)}. Context labels are "
                f"minted at open and are never reused.")
        return self.contexts[label]

    def pages_in(self, label: str) -> list[str]:
        return [h for h, r in self.pages.items()
                if getattr(r, "context", "c1") == label]

    # ------------------------------------------------------- ground truth

    def browser_alive(self) -> bool | None:
        """Is the browser this session owns actually running?

        THE GROUND-TRUTH CHECK (chaos C-02, endurance F7). `_session_status`
        derived `state` from idle timing alone and printed `owned_pids`
        straight out of the journal without asking `hygiene.alive` about a
        single one, so a session whose every owned PID was dead reported
        `state: "active"` while every real call refused. The status surface
        is the one an agent reaches for when everything else is refusing,
        and it was the one confirming the fiction.

        Under multiple contexts the aggregate is the CONSERVATIVE one: True
        only when every jar that can answer is alive, False when every one
        of them is dead, and None when nothing can tell. A session reported
        alive because one of its two browsers is would be the
        completeness-over-omissions failure the doctrine names; `health()`
        is what says `degraded` and names which jar died."""
        verdicts = [h.alive() for h in self.contexts.values()]
        answered = [v for v in verdicts if v is not None]
        if not answered:
            return None
        if all(v is False for v in answered):
            return False
        if all(v is True for v in answered):
            return True
        return None

    def health(self) -> dict:
        """Per-jar liveness plus the honest aggregate word."""
        rows = []
        for label, handle in self.contexts.items():
            alive = handle.alive()
            row = {"context": label,
                   "health": ("alive" if alive else
                              "dead" if alive is False else "unknown"),
                   "pages": len(self.pages_in(label)),
                   "owned_pids": sorted(handle.journal.pids)}
            if alive is False:
                row["reason"] = ("every process this context owns has "
                                 "exited")
                others = [o for o in self.contexts if o != label]
                row["recommendation"] = (
                    f"close this context with manage_session("
                    f"action='close', session={self.session_id!r}, "
                    f"context={label!r}) and open another"
                    + (f"; {sorted(others)} are unaffected" if others else
                       ", or close the session and open a new one"))
            rows.append(row)
        words = {r["health"] for r in rows}
        if words == {"alive"}:
            aggregate = "alive"
        elif words == {"dead"}:
            aggregate = "dead"
        elif "alive" in words and "dead" in words:
            aggregate = "degraded"
        else:
            aggregate = "unknown"
        return {"health": aggregate, "contexts": rows}

    def dead_pages(self) -> list[str]:
        """Handles whose renderer crashed. `manage_tabs(list)` used to print
        these as ordinary live tabs in the same second `locate` was refusing
        them as dead (chaos C-03)."""
        return sorted(h for h, r in self.pages.items() if r.crashed)

    def nav_record(self, record) -> dict | None:
        """The navigation response that produced the document CURRENTLY on
        `record`, or None when nothing recorded describes it.

        The URL comparison is the point (gauntlet 4, G4-04): a recorded
        status is evidence about one document, and a page that pushes a
        main-frame navigation afterwards would otherwise poison every
        later verdict with a status that belongs to something else. The
        `pending_nav` fallback is the popup case, where the response was
        dispatched before any frame existed to attribute it to; the first
        lookup claims it onto the record so it is only resolved once."""
        try:
            url = record.page.url
        except Exception:
            return None
        if record.last_nav_url == url:
            return {"url": url, "status": record.last_nav_status,
                    "headers": record.last_nav_headers}
        pending = self.pending_nav.pop(url, None)
        if pending is not None:
            record.last_nav_url = pending["url"]
            record.last_nav_status = pending["status"]
            record.last_nav_headers = pending["headers"]
            return pending
        return None
    def invalidate_page(self, handle: str, why: str) -> dict:
        """A navigation, a page close, or a session end. Refs and read tokens
        minted on a page do not survive it, and the counts come back so the
        caller can SAY so rather than leaving a later failure to explain it."""
        record = self.pages.get(handle)
        if record is not None:
            # The frame ids die with the document too. They are keyed on refs
            # minted inside the page's own instrument state, which a
            # navigation replaces, so carrying them across would let a new
            # page's first frame inherit the old page's id.
            record.frame_ids.clear()
            record.frame_seq = 0
        return {"refs_invalidated": self.element_map.invalidate_page(handle, why),
                "read_tokens_invalidated": self.reads.invalidate(handle, why),
                "why": why}

    def page(self, handle: str | None) -> PageHandle:
        if handle is None:
            handle = self.focused
        if handle is None:
            raise TargetNotFound(
                f"session {self.session_id} has no open page. Open one with "
                f"manage_tabs(session='{self.session_id}', action='open', "
                f"url=...).")
        if handle not in self.pages:
            known = sorted(self.pages)
            raise TargetNotFound(
                f"no page {handle!r} in session {self.session_id}. Open pages "
                f"are {known or 'none'}. Page handles are minted by "
                f"manage_tabs and by opening a session, and a closed page's "
                f"handle is never reused.")
        return self.pages[handle]


#: What a failed launch means, keyed by the marker in the driver's text.
#: The author's own field report has A:firefox answering "Tool execution
#: failed" with no error detail at all (Desktop Critical-2), and the fuzzer
#: has the same site shipping the whole `chrome-headless-shell.exe` command
#: line and the local ms-playwright install path inside a BAD_PARAMS.
_LAUNCH_CAUSES: tuple[tuple[str, str], ...] = (
    ("executable doesn't exist",
     "the browser binary for this lane is not installed"),
    ("looks like playwright was just installed or updated",
     "the browser binary for this lane is not installed"),
    ("please run the following command to download new browsers",
     "the browser binary for this lane is not installed"),
    ("browsertype.launch: target page, context or browser has been closed",
     "the browser started and exited before it was ready"),
    ("timeout", "the browser did not become ready inside the launch timeout"),
    ("access is denied",
     "the operating system refused to start the browser binary"),
    ("permission denied",
     "the operating system refused to start the browser binary"),
    ("invalid parameters",
     "the browser refused one of the context options this launch asked for"),
    ("no such file or directory",
     "something the launch needs is missing from the install"),
)


def _launch_refusal(spec, exc: Exception, emulation_report) -> Exception:
    """One honest refusal for a launch that failed.

    Three things it has to do that the old one did not: name a CAUSE rather
    than only echoing the driver, keep the local install path and the launch
    command line out of the message (chaos C-12, fuzzer class 1c), and stop
    wearing BAD_PARAMS, since a browser that will not start is not a
    malformed argument."""
    from ..envelope import scrub_driver_text
    text = str(exc).lower()
    cause = next((c for marker, c in _LAUNCH_CAUSES if marker in text), None)
    detail = scrub_driver_text(str(exc))
    install = ("Install it with `python -m playwright install "
               f"{spec.engine}`. " if cause and "not installed" in cause
               else "")
    body = (
        f"could not launch {spec.label}: "
        f"{cause or 'the browser did not start'} "
        f"({type(exc).__name__}: {detail}). {install}"
        f"manage_session(action='capabilities') lists the lanes this build "
        f"supports and what each one can do."
        + (f" The emulation asked for was {emulation_report}; a time zone "
           f"the browser does not know and a device preset an engine cannot "
           f"honor both fail at launch like this."
           if emulation_report else ""))
    if cause and "not installed" in cause:
        return LaneUnsupported(body)
    return SessionDead(body)


#: What each end reason MEANS, in one clause. PLACEHOLDER WORDING: these
#: are the facts a refusal has to carry, not the final English.
REASON_TEXT: dict[str, str] = {
    "explicit_close": "a manage_session(action='close') call closed it",
    "idle_recycle": "an idle recycle closed it after a quiet period",
    "crash": ("its browser process exited on its own, so this was a crash "
              "rather than a close"),
    "shutdown": "the server closed it while shutting down",
}


def tombstone_line(stone: dict | None) -> str:
    """The half of a stale-handle refusal that says WHY, not just that.

    Returns an empty string when nothing is recorded, and the empty case is
    informative too: a session that ended by any route this build knows
    about leaves a record, so no record means it ended by a route that does
    not leave one, which the import refusal states in its own words."""
    if not stone:
        return ""
    when = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stone["closed"]))
    what = REASON_TEXT.get(stone["reason"], stone["reason"])
    auth = stone.get("auth_state_saved_to")
    return (f" That session ended at {when}: {what}. It held "
            f"{stone['pages_at_close']} page(s) at the time."
            + (f" Its auth state had been saved to {auth}, so the login is "
               f"recoverable with load_auth_state." if auth else ""))


def monitor_session_line(sessions: dict) -> str:
    """Name the scheduler's session in an ambiguity refusal. A session the
    caller never opened, appearing in a list of sessions to choose between,
    is otherwise a mystery the message creates."""
    monitors = sorted(sid for sid, s in sessions.items()
                      if getattr(s, "role", "user") == "monitor")
    if not monitors:
        return ""
    return (f" {monitors} belong(s) to the monitor scheduler rather than to "
            f"a conversation; monitor(action='list') is what inspects those.")


class SessionManager:
    """Process-wide browser state. One instance, held at module level."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._session_seq = 0
        self._page_seq = 0
        self.startup_reap: dict | None = None
        #: Closed sessions, newest last, bounded at TOMBSTONE_MAX.
        self.tombstones: deque = deque(maxlen=TOMBSTONE_MAX)

    # ------------------------------------------------------------ lifecycle

    def _next_session_id(self) -> str:
        self._session_seq += 1
        return f"s{self._session_seq}"

    def _next_page_handle(self) -> str:
        self._page_seq += 1
        return f"p{self._page_seq}"

    async def _playwright(self) -> Any:
        """Start the driver lazily, and only once per event loop.

        A Playwright instance is bound to the loop that started it, so a
        stale one is a hard error rather than something to paper over: reusing
        it across loops is exactly the kind of silent breakage this design
        refuses elsewhere."""
        loop = asyncio.get_running_loop()
        if self._pw is not None and self._loop is loop:
            return self._pw
        if self._pw is not None and self.sessions:
            raise Conflict(
                "the browser driver belongs to a different event loop and "
                "sessions are still open. Close them from the loop that "
                "opened them.")
        from playwright.async_api import async_playwright  # lazy: DESIGN 4.1

        self._pw = await async_playwright().start()
        self._loop = loop
        return self._pw

    async def open(self, lane: str | None = None, engine: str | None = None,
                   channel: str | None = None, headless: bool | None = None,
                   device: str | None = None, viewport=None,
                   locale: str | None = None, timezone: str | None = None,
                   role: str = "user", contexts: int = 1) -> Session:
        """Launch a browser on an owned profile and mint a session handle.

        `contexts` is how many independent cookie jars this session gets.
        Two jars means two logins to the same site side by side, and it
        costs one browser process and one profile directory each, which is
        real memory and is reported rather than hidden.

        The startup reaper runs here rather than at import: it is the first
        thing that happens before the first browser of the process starts, so
        a crash residue from a previous run is cleared before a new one is
        created, and a server nobody asks to browse never sweeps anything.

        `device`, `viewport`, `locale`, and `timezone` are Playwright context
        options and they belong HERE because a context takes them at
        construction: a locale or a time zone changed afterward is a lie the
        page's own scripts can see through. Omitting them all leaves every
        default exactly where it was."""
        spec = lanes.resolve(lane=lane, engine=engine, channel=channel,
                             headless=headless)
        jars = contexts if isinstance(contexts, int) else 0
        if jars < 1 or jars > MAX_CONTEXTS:
            raise BadParams(
                f"contexts must be between 1 and {MAX_CONTEXTS}, and "
                f"{contexts!r} is not. Each cookie jar is a separate "
                f"browser process on its own profile directory, which is "
                f"real memory on this machine, so the cap is deliberate. "
                f"{ENV_MAX_CONTEXTS} raises it at the next launch. Nothing "
                f"was opened.")
        async with self._lock:
            if self.startup_reap is None:
                self.startup_reap = hygiene.reap_orphans()
            hygiene.JOB.ensure()
            _warm_estimator()
            pw = await self._playwright()
            lanes.ensure_installed(spec, pw)
            emulation, emulation_report = lanes.emulation_kwargs(
                spec, pw, device=device, viewport=viewport, locale=locale,
                timezone=timezone)
            sid = self._next_session_id()
            session = Session(session_id=sid, spec=spec,
                              emulation=emulation_report,
                              emulation_kwargs=dict(emulation), role=role)
            built: list[ContextHandle] = []
            try:
                for index in range(jars):
                    built.append(await self._launch_context(
                        session, spec, emulation, emulation_report, pw,
                        label=f"c{index + 1}"))
            except Exception:
                # A FAILURE AT CONTEXT K TEARS DOWN 1..K-1 BEFORE RE-RAISING.
                # Half a session is a state nothing else in this code
                # expects, and inventing one to be permissive is how a
                # TargetNotFound surfaces three calls later with no
                # explanation.
                for handle in built:
                    await self._teardown_context(session, handle)
                raise
            session.focused_context = built[0].label
            self.sessions[sid] = session
            for hook in SESSION_OPEN_HOOKS:
                hook(session, built)
            return session

    async def _launch_context(self, session: Session, spec, emulation,
                              emulation_report, pw,
                              label: str) -> ContextHandle:
        """One cookie jar: its own profile, its own browser, its own journal.

        Three lines here are order-sensitive and one of them is the single
        most damaging thing in the feature to get wrong:

        - `before` is re-taken IMMEDIATELY BEFORE EACH LAUNCH. It is the
          baseline `adopt_descendants` uses to decide which processes this
          launch created, so taking it once outside the loop would make c2's
          journal adopt c1's browser processes, and closing c2 would then
          kill c1's browser. It fails silently until a close.
        - the profile directory is created PER CONTEXT. Two contexts sharing
          one profile share a cookie jar, which is the feature not working
          while appearing to.
        - the journal is named `{sid}-{label}` with a HYPHEN. The journal
          writes `session-{owner_pid}-{session_id}.json`, and a colon in a
          Windows filename fails the write, which would leave a live browser
          with no journal and therefore nothing the reaper is ever permitted
          to kill.
        """
        profile = hygiene.new_profile_dir(spec.engine[:2])
        journal = hygiene.OwnedProcesses(f"{session.session_id}-{label}",
                                         str(profile), spec.label)
        before = {p["pid"] for p in hygiene.snapshot_processes()}
        kwargs = lanes.launch_kwargs(spec, str(profile), emulation)
        browser_type = getattr(pw, spec.engine)
        try:
            context = await browser_type.launch_persistent_context(**kwargs)
        except Exception as exc:
            hygiene._remove_tree(profile)
            raise _launch_refusal(spec, exc, emulation_report) from exc
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        # THE INSTRUMENT CHANNEL, bound before any page script in any
        # document of this context runs. It carries the closed-root
        # counter (counted as roots are created, because a closed root is
        # unreachable afterward and a guess is not a completeness figure)
        # and the ref registry, both of which used to be page-writable
        # globals: gauntlet 2 rewrote one and subclassed the other to
        # redirect a trusted click.
        await context.add_init_script(CLOSED_SHADOW_HOOK)
        # The launch page already has a document, so the init script has
        # not run in it. Every read would answer INSTRUMENT_MISSING until
        # the first navigation; installing it directly costs one evaluate
        # on an about:blank page with no scripts in it.
        for page in context.pages:
            try:
                await page.evaluate(CLOSED_SHADOW_HOOK)
            except Exception:
                pass            # a page mid-navigation gets it from the hook
        journal.adopt_descendants(since=before)
        handle = ContextHandle(label=label, context=context,
                               profile_dir=str(profile), journal=journal,
                               spec=spec)
        session.contexts[label] = handle
        for page in context.pages:
            self._attach_page(session, page, context_label=label)
        if not session.pages_in(label):
            self._attach_page(session, await context.new_page(),
                              context_label=label)
        # POPUPS ARE ADOPTED (gauntlet 4, G4-05). `_attach_page` used to
        # run for `context.pages` at open and for `manage_tabs(open)` and
        # nowhere else, so a page a click opened in a new tab really
        # existed in the browser and had no handle, was absent from
        # `manage_tabs(list)`, and carried no policy of any kind — no
        # origin check, no wall verdict, nothing. The context event is
        # the only place the browser reports one. Attaching here gives it
        # the same handle, the same dialog desk, the same crash mark and
        # the same navigation-response recorder every other page has; its
        # `vetted_url` stays unset, so the first read or act on it runs
        # the origin check the popup itself never got.
        try:
            context.on("page", lambda p: self._attach_page(
                session, p, adopted=True, context_label=label))
        except Exception:
            pass                # a lane without the event keeps the old shape
        # THE CONTEXT-LEVEL RESPONSE RECORDER (gauntlet 4, G4-05). The
        # per-page recorder in `_attach_page` cannot see a popup's own
        # first navigation response, because the response is dispatched
        # before the `page` event hands us the page to attach it to.
        # This listener exists from before the first popup can be
        # created and parks such a response for `_attach_page` to
        # drain. It writes nothing when a record already exists: the
        # per-page recorder owns that case and the two must not
        # disagree about which response is the last one.
        def on_context_response(response):
            try:
                if not response.request.is_navigation_request():
                    return
            except Exception:
                return
            try:
                response.request.frame
                return          # a frame exists; the per-page
            except Exception:   # recorder owns that case
                pass
            try:
                session.pending_nav[response.url] = {
                    "url": response.url, "status": response.status,
                    "headers": dict(response.headers)}
                while len(session.pending_nav) > PENDING_NAV_MAX:
                    session.pending_nav.pop(
                        next(iter(session.pending_nav)))
                    session.pending_nav_evicted += 1
            except Exception:
                pass

        try:
            context.on("response", on_context_response)
        except Exception:
            pass
        return handle

    async def add_context(self, session: Session) -> ContextHandle:
        """A second identity discovered after the first one is logged in.

        The comparison flow ("what does an admin see that a regular user
        does not") reaches this point already signed in as one of them, and
        forcing a whole new session there throws that login away."""
        if len(session.contexts) >= MAX_CONTEXTS:
            raise BadParams(
                f"session {session.session_id} already holds "
                f"{len(session.contexts)} cookie jar(s) against a cap of "
                f"{MAX_CONTEXTS} ({ENV_MAX_CONTEXTS}). Each one is a "
                f"separate browser process and a separate profile "
                f"directory, which is real memory on this machine.")
        async with self._lock:
            pw = await self._playwright()
            label = f"c{len(session.contexts) + 1}"
            while label in session.contexts:
                label = f"c{int(label[1:]) + 1}"
            handle = await self._launch_context(
                session, session.spec, dict(session.emulation_kwargs),
                session.emulation, pw, label=label)
            for hook in SESSION_OPEN_HOOKS:
                hook(session, [handle])
            return handle

    def _attach_page(self, session: Session, page: Any,
                     adopted: bool = False,
                     context_label: str | None = None) -> PageHandle:
        # IDEMPOTENT BY PAGE IDENTITY (gauntlet 4, G4-05). `context.new_page()`
        # fires the context's own `page` event before it returns, so the
        # adoption hook and `manage_tabs(open)`'s explicit call both arrive
        # for the same object; a second handle for one page would mean two
        # dialog desks, two response recorders, and a tab list that
        # double-counts.
        for existing in session.pages.values():
            if existing.page is page:
                return existing
        handle = self._next_page_handle()
        label = context_label or session.focused_context
        if label not in session.contexts and session.contexts:
            label = next(iter(session.contexts))
        record = PageHandle(handle=handle, page=page, context=label,
                            adopted=bool(adopted))
        # The renderer-crash mark (M1). The event is the reliable signal:
        # whichever call OBSERVES the crash, the handle is dead from the
        # moment it fires, and locate() refuses reuse with the recovery
        # named instead of replaying the driver's "Page crashed" forever.
        try:
            page.on("crash", lambda _page: setattr(
                record, "crashed",
                f"the renderer crashed at "
                f"{time.strftime('%Y-%m-%dT%H:%M:%S')}"))
        except Exception:
            pass  # a lane without the event still gets the message-sniff path
        # The navigation-response recorder (gauntlet 3, F4). One listener,
        # attached at page creation like the dialog desk, so every door onto
        # a page — navigate, an action that navigates, a read_pages hop, a
        # child frame's own load — leaves the status and headers the wall
        # classifier needs. Synchronous, swallows everything: a recorder
        # must never turn a working navigation into an error.
        def on_response(response):
            try:
                request = response.request
                if not request.is_navigation_request():
                    return
                frame = request.frame
                if frame == page.main_frame:
                    record.last_nav_url = response.url
                    record.last_nav_status = response.status
                    record.last_nav_headers = dict(response.headers)
                else:
                    record.frame_nav[frame] = {
                        "status": response.status,
                        "headers": dict(response.headers)}
                    while len(record.frame_nav) > 32:
                        record.frame_nav.pop(next(iter(record.frame_nav)))
            except Exception:
                pass

        try:
            page.on("response", on_response)
        except Exception:
            pass  # a lane without the event keeps navigate's own response
        self._attach_dialog_desk(session, record)
        session.pages[handle] = record
        session.bump("pages_opened", context=label)
        if session.focused is None and not adopted:
            # A popup never steals the focused handle: the caller is working
            # on the page it opened from, and a tool call with no `page`
            # argument must not be redirected onto a page the site opened.
            session.focused = handle
        return record

    @staticmethod
    def _attach_dialog_desk(session: Session, record: PageHandle) -> None:
        """Attach the native-dialog and file-chooser listeners to one page.

        This runs for EVERY page, at attach time, with no pack guard: a
        dialog stops the page whatever launch shape the server is running, so
        the recording has to be there under all of them. It is also the moment
        the driver's own behavior changes: with
        no listener Playwright dismisses dialogs itself, and with one it
        dismisses nothing. The handler below therefore reproduces the old
        dismissal exactly as its default branch, and the difference is that
        the dismissal is now recorded and can be overridden per page.
        """
        desk = _dialogs.desk(session)
        page = record.page

        async def on_dialog(dialog):
            kind = (getattr(dialog, "type", "") or "").strip().lower()
            pending = _dialogs.Pending(
                dialog_id=desk.next_id("d"), kind=kind,
                message=getattr(dialog, "message", "") or "",
                default_value=getattr(dialog, "default_value", "") or "",
                page=record.handle, url=record.page.url, driver=dialog)
            arm = desk.arm_for(record.handle)
            if arm is not None and arm.covers(kind):
                if arm.once:
                    desk.disarm(record.handle)
                if arm.disposition == "hold":
                    desk.note_pending(pending)
                    SessionManager._schedule_hold_expiry(desk, pending)
                    return
                if arm.disposition == "accept":
                    text = arm.prompt_text or ""
                    try:
                        await dialog.accept(text)
                    except Exception:
                        pass        # already answered, or the page went away
                    desk.record(pending, "accepted", prompt_text=text or None,
                                why="an armed accept answered it")
                    return
                try:
                    await dialog.dismiss()
                except Exception:
                    pass
                desk.record(pending, "dismissed",
                            why="an armed dismiss answered it")
                return
            try:
                await dialog.dismiss()
            except Exception:
                pass
            desk.record(pending, "dismissed", why=_dialogs.DEFAULT_WHY)

        def on_chooser(chooser):
            try:
                multiple = bool(chooser.is_multiple())
            except Exception:
                multiple = False
            desk.note_chooser(_dialogs.Chooser(
                chooser_id=desk.next_id("fc"), page=record.handle,
                url=record.page.url, multiple=multiple))

        try:
            page.on("dialog", on_dialog)
            # Attaching this listener is also what keeps a click on a file
            # input from reaching the operating system's own picker: the
            # driver intercepts the chooser only while something is listening.
            page.on("filechooser", on_chooser)
        except Exception:
            pass  # a lane without these events keeps the driver's own posture

    @staticmethod
    def _schedule_hold_expiry(desk, pending) -> None:
        """A held dialog is bounded. The hold exists so a caller can read the
        dialog and answer it, and a page frozen because nobody came back is a
        worse outcome than the Cancel the default posture would have sent."""
        async def expire():
            try:
                await asyncio.sleep(_dialogs.hold_ttl_s())
                if desk.pending_for(pending.page) is not pending:
                    return
                desk.resolve_pending(pending.page)
                try:
                    await pending.driver.dismiss()
                except Exception:
                    pass
                desk.record(pending, "dismissed", why=_dialogs.EXPIRED_WHY)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        try:
            task = asyncio.get_running_loop().create_task(expire())
        except RuntimeError:
            return  # no loop: the hold simply lives until the page closes
        desk.tasks.add(task)
        task.add_done_callback(desk.tasks.discard)

    # ------------------------------------------------------- tombstones

    def entomb(self, session: Session, reason: str | None = None) -> dict:
        """Record how one session ended, before it stops existing.

        `reason` defaults to a DERIVED one rather than to `explicit_close`:
        a close that finds every owned PID already gone is not the same
        event as a caller closing a working browser, and the caller of the
        close is usually the one that cannot tell the difference."""
        if reason is None:
            reason = "crash" if session.browser_alive() is False \
                else "explicit_close"
        urls = []
        for record in session.pages.values():
            try:
                urls.append(record.page.url)
            except Exception:
                pass
        stone = {
            "session": session.session_id,
            "lane": session.spec.label,
            "role": getattr(session, "role", "user"),
            "opened": session.opened,
            "closed": time.time(),
            "reason": reason,
            "pages_at_close": len(session.pages),
            "last_urls": urls[:8],
            "auth_state_saved_to": session.saved_auth_path,
        }
        self.tombstones.append(stone)
        return stone

    def tombstone(self, session_id: str) -> dict | None:
        """The most recent record for one session id, or None. Handles are
        never reused, so the newest match is the only match."""
        for stone in reversed(self.tombstones):
            if stone["session"] == session_id:
                return stone
        return None

    async def close(self, session_id: str, reason: str | None = None) -> dict:
        """Close one session and verify the teardown by owned PID.

        The verification is the point. "We called context.close()" is a claim;
        "every PID this session started is gone" is the property, and it is
        the row where the most-installed browser MCP server in the world is
        currently open and unfixed."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session is None:
                raise TargetNotFound(
                    f"no session {session_id!r}. Open sessions are "
                    f"{sorted(self.sessions) or 'none'}."
                    + tombstone_line(self.tombstone(session_id)))
            # BEFORE the teardown, because `browser_alive()` is what
            # distinguishes a crash from a close and the journal is closed
            # below.
            stone = self.entomb(session, reason)
            # The hold-expiry timers die with the session they belong to.
            # A task still sleeping when its loop closes is a "destroyed but
            # pending" warning at best and a dismissal against a closed page
            # at worst, and neither is a thing to leave lying around.
            desk = getattr(session, "_dialogs", None)
            for task in list(desk.tasks) if desk is not None else ():
                task.cancel()
            # EVERY jar is asked to close before ANY of them is verified, so
            # the grace window is spent once rather than once per context.
            for handle in session.contexts.values():
                try:
                    await asyncio.wait_for(handle.context.close(), timeout=30)
                except Exception:
                    pass
            if not self.sessions and self._pw is not None:
                try:
                    await self._pw.stop()
                finally:
                    self._pw = None
                    self._loop = None
            rows = []
            for handle in session.contexts.values():
                survivors = await self._await_exit(handle.journal)
                for pid in survivors:
                    hygiene.kill(pid)
                handle.journal.close()
                hygiene._remove_tree(handle.profile_dir)
                rows.append({"context": handle.label,
                             "owned_pids": sorted(handle.journal.pids),
                             "survivors_killed": survivors,
                             "profile_removed": True})
            # The enforcing budget ledger dies with the session. Not a
            # reset: budgets are per-session by definition (policy/budgets).
            from ..policy import budgets as _budgets
            _budgets.BOOK.drop(session_id)
            return {
                "session": session_id,
                "owned_pids": sorted(pid for row in rows
                                     for pid in row["owned_pids"]),
                "survivors_killed": sorted(pid for row in rows
                                           for pid in row["survivors_killed"]),
                "profile_removed": True,
                "contexts": rows,
                "ended": stone["reason"],
            }

    async def close_context(self, session: Session, label: str) -> dict:
        """Close ONE cookie jar and leave the rest of the session working.

        Closing the LAST one refuses. A session with zero contexts is a
        state nothing else in this code expects, and inventing one to be
        permissive is how a TargetNotFound surfaces three calls later with
        no explanation."""
        handle = session.jar(label)
        if len(session.contexts) <= 1:
            raise ValidationFailed(
                f"context {handle.label} is the only cookie jar in session "
                f"{session.session_id}, and a session with none is a state "
                f"nothing else here expects. To close the session, call "
                f"manage_session(action='close', "
                f"session={session.session_id!r}). Nothing was closed.")
        async with self._lock:
            closed_pages = session.pages_in(handle.label)
            invalidated = 0
            tokens = 0
            for page_handle in closed_pages:
                dropped = session.invalidate_page(
                    page_handle,
                    f"context {handle.label} was closed and every page in "
                    f"it with it")
                invalidated += dropped["refs_invalidated"]
                tokens += dropped["read_tokens_invalidated"]
                session.pages.pop(page_handle, None)
            try:
                await asyncio.wait_for(handle.context.close(), timeout=30)
            except Exception:
                pass
            survivors = await self._await_exit(handle.journal)
            for pid in survivors:
                hygiene.kill(pid)
            handle.journal.close()
            hygiene._remove_tree(handle.profile_dir)
            session.contexts.pop(handle.label, None)
            if session.focused_context == handle.label:
                session.focused_context = next(iter(session.contexts))
            if session.focused in closed_pages or session.focused is None:
                session.focused = next(iter(session.pages), None)
            return {
                "session": session.session_id,
                "closed_context": handle.label,
                "pages_closed": closed_pages,
                "refs_invalidated": invalidated,
                "read_tokens_invalidated": tokens,
                "owned_pids": sorted(handle.journal.pids),
                "survivors_killed": survivors,
                "profile_removed": True,
                "contexts": sorted(session.contexts),
                "focused_context": session.focused_context,
                "focused": session.focused,
            }

    async def _teardown_context(self, session: Session,
                                handle: ContextHandle) -> None:
        """Undo one context that a failed multi-context launch already
        built. Nothing is reported: the launch refusal is the answer."""
        for page_handle in session.pages_in(handle.label):
            session.pages.pop(page_handle, None)
        try:
            await asyncio.wait_for(handle.context.close(), timeout=30)
        except Exception:
            pass
        for pid in await self._await_exit(handle.journal, grace_s=3.0):
            hygiene.kill(pid)
        handle.journal.close()
        hygiene._remove_tree(handle.profile_dir)
        session.contexts.pop(handle.label, None)

    @staticmethod
    async def _await_exit(journal, grace_s: float = 6.0) -> list[int]:
        """Two-phase verify with a grace window, inherited from the family's
        COM gates. A process that has been asked to exit is not the same as a
        process that has exited, and polling with a bound is the difference
        between a teardown and a hope."""
        deadline = time.monotonic() + grace_s
        survivors = journal.survivors()
        while survivors and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            survivors = journal.survivors()
        return survivors

    async def close_all(self) -> list[dict]:
        return [await self.close(sid, reason="shutdown")
                for sid in list(self.sessions)]

    # --------------------------------------------------------------- lookup

    def session(self, session_id: str | None) -> Session:
        if session_id is None:
            # THE SHORTCUT IS FOR USER SESSIONS ONLY. A conversation with
            # one session of its own plus the monitor scheduler's session
            # would otherwise be handed the scheduler's browser by a call
            # that named no session at all, and every later refusal would
            # be about the wrong browser.
            mine = [s for s in self.sessions.values()
                    if getattr(s, "role", "user") == "user"]
            if len(mine) == 1:
                return mine[0]
            if not self.sessions:
                raise TargetNotFound(
                    "no browser session is open. Open one with "
                    "manage_session(action='open').")
            if not mine:
                raise TargetNotFound(
                    "no browser session of your own is open. The only open "
                    "session belongs to the monitor scheduler and is not "
                    "yours to use. Open one with "
                    "manage_session(action='open').")
            raise BadParams(
                f"several sessions are open ({sorted(self.sessions)}); name "
                f"the one you mean rather than letting the server pick."
                + monitor_session_line(self.sessions))
        if session_id not in self.sessions:
            raise TargetNotFound(
                f"no session {session_id!r}. Open sessions are "
                f"{sorted(self.sessions) or 'none'}. A session handle is "
                f"minted by manage_session(action='open') and is never "
                f"reused after a close."
                + tombstone_line(self.tombstone(session_id)))
        return self.sessions[session_id]

    def locate(self, page_handle: str, *, allow_pending_dialog: bool = False
               ) -> tuple[Session, PageHandle]:
        """Find a page by its handle across every session.

        Refs and page handles are unique across the process, so a bare `p3` is
        never ambiguous and the envelope can always say which session it
        belongs to.

        This is also where a HELD native dialog stops everything. A dialog
        stops the page's script, so a read or an action attempted underneath
        one does not fail, it hangs until its timeout and then reports
        whatever the timeout was about instead of the dialog. Refusing here
        means every tool that addresses a page reports the real condition,
        and no tool has to remember to check. `allow_pending_dialog=True` is
        for the two callers that legitimately work on a held dialog:
        `handle_dialog` itself, which answers it, and the desk reporting."""
        for session in self.sessions.values():
            if page_handle in session.pages:
                record = session.pages[page_handle]
                # THE BROWSER CHECK RUNS FIRST (chaos C-04/C-05). One
                # message used to serve two different deaths: it named
                # `manage_tabs(action='open')` as the recovery, which is
                # right for a crashed renderer and a dead end when the whole
                # browser is gone (that call answers "Target page, context
                # or browser has been closed"), and it blamed deep DOM
                # nesting for a browser somebody killed from outside.
                # THE PAGE'S OWN JAR is what decides this, not the session
                # as a whole: under multiple contexts one browser can die
                # while the other lives, and a page in the dead one has to
                # refuse even though the session is only degraded.
                jar = session.contexts.get(
                    getattr(record, "context", session.focused_context))
                if jar is not None and jar.alive() is False:
                    survivors = sorted(
                        set(session.contexts) - {jar.label})
                    raise SessionDead(
                        f"the browser for session {session.session_id} "
                        f"context {jar.label} is gone: every process it owns "
                        f"has exited ({sorted(jar.journal.pids)}). Page "
                        f"{page_handle} and every other handle in that "
                        f"context are dead with it, and opening a fresh tab "
                        f"there fails the same way. "
                        + (f"Contexts {survivors} are unaffected; close this "
                           f"one with manage_session(action='close', "
                           f"session={session.session_id!r}, "
                           f"context={jar.label!r})."
                           if survivors else
                           f"Close the session with manage_session("
                           f"session={session.session_id!r}, "
                           f"action='close') and open a new one")
                        + " Refs, read tokens, and page handles do not carry "
                          "over.")
                if record.crashed:
                    # A crashed renderer never recovers on the same page:
                    # replaying the driver's "Page crashed" against a dead
                    # handle is a loop, not a recovery. manage_tabs reaches
                    # the record through Session.page() and can still close
                    # or list it; everything that would READ or ACT refuses
                    # here with the real recovery.
                    exc = Conflict(
                        f"page {page_handle} is dead: {record.crashed}. A "
                        f"crashed renderer does not recover on the same "
                        f"page handle. Open a fresh tab with manage_tabs("
                        f"session={session.session_id!r}, action='open', "
                        f"url=...) and continue there; this handle can only "
                        f"be closed (manage_tabs action='close'). Refs "
                        f"minted on it are gone. Extremely deep or "
                        f"pathological nesting is a known crash cause in the "
                        f"DOM or in shadow roots, and so is the browser "
                        f"being killed or running out of memory; this build "
                        f"cannot tell which from the page.")
                    # H-02: CONFLICT's own hint says "re-read to re-establish
                    # a baseline", which is the one action this message has
                    # just said will never work.
                    exc.hint = CRASHED_PAGE_HINT
                    raise exc
                if record.parked and record.parked_from:
                    # Nothing parks automatically (endurance F3), so this
                    # fires only after an explicit `park_idle`. The refusal
                    # names the URL the page was on, because "the page is
                    # parked" is not a recovery and the URL is.
                    was = record.parked_from
                    record.parked = False
                    record.parked_from = None
                    raise StaleAnchor(
                        f"page {page_handle} was idle long enough to be "
                        f"parked to about:blank, so the document it held is "
                        f"gone and every ref and read token minted on it "
                        f"with it. It was on {was}. Navigate there again "
                        f"with navigate(page={page_handle!r}, url={was!r}) "
                        f"and re-read. Parking is what stops a dormant page "
                        f"burning CPU and memory for hours, and nothing in "
                        f"this build does it on its own.")
                if not allow_pending_dialog:
                    held = _dialogs.desk(session).pending_for(page_handle)
                    if held is not None:
                        raise ModalBlocked(_dialogs.held_refusal(held))
                return session, record
        known = sorted(h for s in self.sessions.values() for h in s.pages)
        raise TargetNotFound(
            f"no page {page_handle!r}. Open pages are {known or 'none'}. "
            f"Page handles are minted by manage_session(action='open') and "
            f"manage_tabs(action='open'), and a closed page's handle is never "
            f"reused.")

    # ----------------------------------------------------------- idle park

    async def park_idle(self, park_after_s: float | None = None,
                        close_after_s: float | None = None,
                        force: bool = False) -> dict:
        """Defense 3: park dormant pages, then recycle dormant sessions.

        Parking is `about:blank`, which is the exact intervention
        chrome-devtools-mcp #2599 measured taking a dormant page from 28 to 30
        percent CPU down to 0.13 percent. Recycling closes the whole session,
        which returns the memory as well as the CPU."""
        park_after = IDLE_PARK_S if park_after_s is None else park_after_s
        close_after = IDLE_CLOSE_S if close_after_s is None else close_after_s
        now = time.time()
        parked, recycled = [], []
        for sid, session in list(self.sessions.items()):
            idle_for = now - max(
                [p.last_used for p in session.pages.values()] or [session.opened])
            if not force and idle_for >= close_after:
                await self.close(sid, reason="idle_recycle")
                recycled.append(sid)
                continue
            for record in session.pages.values():
                if record.parked:
                    continue
                if force or (now - record.last_used) >= park_after:
                    try:
                        # A park is a NAVIGATION, so the refs and read
                        # tokens minted on the old document die with it,
                        # exactly as they do for any other navigation.
                        # Without this a ref survived a park and resolved
                        # against about:blank (found for endurance F3; the
                        # mechanism has never run in a shipped process, so
                        # nothing had exercised it).
                        record.parked_from = record.page.url
                        session.invalidate_page(
                            record.handle,
                            f"the page was idle for "
                            f"{int(now - record.last_used)}s and was parked "
                            f"to about:blank to free the browser")
                        await record.page.goto(PARKED_URL, timeout=10000)
                        record.parked = True
                        parked.append(record.handle)
                    except Exception:
                        pass
        return {"parked": parked, "recycled": recycled,
                "park_after_s": park_after, "close_after_s": close_after}

    def owned_pids(self) -> list[int]:
        return sorted({pid for s in self.sessions.values()
                       for c in s.contexts.values()
                       for pid in c.journal.pids})


#: The process-wide manager. One browser tree, one journal, one lock.
MANAGER = SessionManager()


async def with_timeout(coro, ms: int, what: str):
    """Every driver call runs under a bound. A hung navigation must free the
    server rather than wedge it, and the failure must name what was awaited."""
    try:
        return await asyncio.wait_for(coro, timeout=ms / 1000)
    except asyncio.TimeoutError as exc:
        raise Timeout(
            f"{what} did not complete within {ms} ms. The browser is still "
            f"usable; retry with a longer timeout_ms, or use a cheaper "
            f"wait_until such as 'domcontentloaded'.") from exc
