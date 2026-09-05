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
from dataclasses import dataclass, field
from typing import Any

from .. import anchors
from ..errors import BadParams, Conflict, TargetNotFound, Timeout
from ..projection import CLOSED_SHADOW_HOOK
from ..projection.meter import warm as _warm_estimator
from . import hygiene, lanes

#: Bounded per-operation timeout. Generous, finite always.
DEFAULT_TIMEOUT_MS = int(os.environ.get("KS4WEB_TIMEOUT_MS", "30000"))

#: Idle park and recycle. Defense 3 (DESIGN 4.7): a dormant page burning 28 to
#: 30 percent CPU for hours is the measured incumbent behavior, and parking to
#: about:blank dropped it to 0.13 percent.
IDLE_PARK_S = float(os.environ.get("KS4WEB_IDLE_PARK_S", "300"))
IDLE_CLOSE_S = float(os.environ.get("KS4WEB_IDLE_CLOSE_S", "1800"))

PARKED_URL = "about:blank"


@dataclass
class PageHandle:
    """One page, its handle, and the history KS4Web tracks itself."""

    handle: str
    page: Any
    history: list[str] = field(default_factory=list)
    opened: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    parked: bool = False
    last_status: int | None = None
    last_load_state: str = "load"

    def touch(self, url: str | None = None) -> None:
        self.last_used = time.time()
        self.parked = False
        if url and (not self.history or self.history[-1] != url):
            self.history.append(url)

    @property
    def previous_url(self) -> str | None:
        return self.history[-2] if len(self.history) > 1 else None


@dataclass
class Session:
    """One browser context, its pages, and everything owned alongside it."""

    session_id: str
    spec: lanes.LaneSpec
    context: Any
    profile_dir: str
    journal: hygiene.OwnedProcesses
    pages: dict[str, PageHandle] = field(default_factory=dict)
    focused: str | None = None
    opened: float = field(default_factory=time.time)
    counters: dict[str, int] = field(
        default_factory=lambda: {"navigations": 0, "reads": 0, "actions": 0,
                                 "pages_opened": 0, "origins": 0})
    origins: set[str] = field(default_factory=set)
    #: The sticky element map and the delta store, per SESSION rather than
    #: per page, because refs are unique across the session (DESIGN 3.5) so a
    #: bare `e12` is never ambiguous. The engine owns them and the anchors
    #: package never learns what a browser is.
    element_map: Any = field(default_factory=anchors.ElementMap)
    reads: Any = field(default_factory=anchors.ReadStore)

    def invalidate_page(self, handle: str, why: str) -> dict:
        """A navigation, a page close, or a session end. Refs and read tokens
        minted on a page do not survive it, and the counts come back so the
        caller can SAY so rather than leaving a later failure to explain it."""
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
                   channel: str | None = None, headless: bool | None = None
                   ) -> Session:
        """Launch a browser on an owned profile and mint a session handle.

        The startup reaper runs here rather than at import: it is the first
        thing that happens before the first browser of the process starts, so
        a crash residue from a previous run is cleared before a new one is
        created, and a server nobody asks to browse never sweeps anything."""
        spec = lanes.resolve(lane=lane, engine=engine, channel=channel,
                             headless=headless)
        async with self._lock:
            if self.startup_reap is None:
                self.startup_reap = hygiene.reap_orphans()
            hygiene.JOB.ensure()
            _warm_estimator()
            pw = await self._playwright()
            lanes.ensure_installed(spec, pw)
            profile = hygiene.new_profile_dir(spec.engine[:2])
            sid = self._next_session_id()
            journal = hygiene.OwnedProcesses(sid, str(profile), spec.label)
            before = {p["pid"] for p in hygiene.snapshot_processes()}
            kwargs = lanes.launch_kwargs(spec, str(profile))
            browser_type = getattr(pw, spec.engine)
            try:
                context = await browser_type.launch_persistent_context(**kwargs)
            except Exception as exc:
                hygiene._remove_tree(profile)
                raise BadParams(
                    f"could not launch {spec.label}: {type(exc).__name__}: "
                    f"{str(exc)[:300]}") from exc
            context.set_default_timeout(DEFAULT_TIMEOUT_MS)
            # Counted as they are created, because a closed shadow root is
            # unreachable afterward and a guess is not a completeness figure.
            await context.add_init_script(CLOSED_SHADOW_HOOK)
            journal.adopt_descendants(since=before)
            session = Session(session_id=sid, spec=spec, context=context,
                              profile_dir=str(profile), journal=journal)
            for page in context.pages:
                self._attach_page(session, page)
            if not session.pages:
                self._attach_page(session, await context.new_page())
            self.sessions[sid] = session
            return session

    def _attach_page(self, session: Session, page: Any) -> PageHandle:
        handle = self._next_page_handle()
        record = PageHandle(handle=handle, page=page)
        session.pages[handle] = record
        session.counters["pages_opened"] += 1
        if session.focused is None:
            session.focused = handle
        return record

    async def close(self, session_id: str) -> dict:
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
                    f"{sorted(self.sessions) or 'none'}.")
            try:
                await asyncio.wait_for(session.context.close(), timeout=30)
            except Exception:
                pass
            if not self.sessions and self._pw is not None:
                try:
                    await self._pw.stop()
                finally:
                    self._pw = None
                    self._loop = None
            survivors = await self._await_exit(session)
            for pid in survivors:
                hygiene.kill(pid)
            session.journal.close()
            hygiene._remove_tree(session.profile_dir)
            # The enforcing budget ledger dies with the session. Not a
            # reset: budgets are per-session by definition (policy/budgets).
            from ..policy import budgets as _budgets
            _budgets.BOOK.drop(session_id)
            return {
                "session": session_id,
                "owned_pids": sorted(session.journal.pids),
                "survivors_killed": survivors,
                "profile_removed": True,
            }

    @staticmethod
    async def _await_exit(session: Session, grace_s: float = 6.0) -> list[int]:
        """Two-phase verify with a grace window, inherited from the family's
        COM gates. A process that has been asked to exit is not the same as a
        process that has exited, and polling with a bound is the difference
        between a teardown and a hope."""
        deadline = time.monotonic() + grace_s
        survivors = session.journal.survivors()
        while survivors and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            survivors = session.journal.survivors()
        return survivors

    async def close_all(self) -> list[dict]:
        return [await self.close(sid) for sid in list(self.sessions)]

    # --------------------------------------------------------------- lookup

    def session(self, session_id: str | None) -> Session:
        if session_id is None:
            if len(self.sessions) == 1:
                return next(iter(self.sessions.values()))
            if not self.sessions:
                raise TargetNotFound(
                    "no browser session is open. Open one with "
                    "manage_session(action='open').")
            raise BadParams(
                f"several sessions are open ({sorted(self.sessions)}); name "
                f"the one you mean rather than letting the server pick.")
        if session_id not in self.sessions:
            raise TargetNotFound(
                f"no session {session_id!r}. Open sessions are "
                f"{sorted(self.sessions) or 'none'}. A session handle is "
                f"minted by manage_session(action='open') and is never "
                f"reused after a close.")
        return self.sessions[session_id]

    def locate(self, page_handle: str) -> tuple[Session, PageHandle]:
        """Find a page by its handle across every session.

        Refs and page handles are unique across the process, so a bare `p3` is
        never ambiguous and the envelope can always say which session it
        belongs to."""
        for session in self.sessions.values():
            if page_handle in session.pages:
                return session, session.pages[page_handle]
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
                await self.close(sid)
                recycled.append(sid)
                continue
            for record in session.pages.values():
                if record.parked:
                    continue
                if force or (now - record.last_used) >= park_after:
                    try:
                        await record.page.goto(PARKED_URL, timeout=10000)
                        record.parked = True
                        parked.append(record.handle)
                    except Exception:
                        pass
        return {"parked": parked, "recycled": recycled,
                "park_after_s": park_after, "close_after_s": close_after}

    def owned_pids(self) -> list[int]:
        return sorted({pid for s in self.sessions.values()
                       for pid in s.journal.pids})


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
