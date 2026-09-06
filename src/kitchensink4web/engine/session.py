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
from .. import dialogs as _dialogs
from ..errors import BadParams, Conflict, ModalBlocked, TargetNotFound, Timeout
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

#: The pack-recorder seam. Ops modules (network, diagnostics, files) append
#: a callable here at import; every newly opened session is passed through
#: each one so recorders attach their event listeners at open rather than at
#: first read, which is the difference between "the log starts when the
#: session does" and "the log starts when somebody remembered to ask".
#: Each hook checks its own pack is loaded before doing anything, so an
#: imported-but-unselected pack records nothing. Hooks are synchronous and
#: their failures propagate: a recorder that cannot attach is a launch
#: problem to surface, not one to swallow.
SESSION_OPEN_HOOKS: list = []


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
    #: Set when the renderer crashed (the driver's `crash` event, or a
    #: "Page crashed" driver error). A crashed page never recovers: every
    #: later call through this handle refuses and names the recovery
    #: (gauntlet 2026-09-06, M1: a deep-DOM hostile page crashed the
    #: renderer and the poisoned handle kept answering with a misleading
    #: BAD_PARAMS).
    crashed: str | None = None

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
    #: Where and when this session's auth state was last written, if it ever
    #: was. Field finding 41 (2026-09-05): close reported "none were saved"
    #: minutes after an explicit save_auth_state, because it consulted only
    #: the close call's own arguments. A save history the session remembers
    #: is what lets the close message tell the truth.
    saved_auth_at: float | None = None
    saved_auth_path: str | None = None
    #: What the caller asked this context to look like at open (device
    #: preset, viewport, locale, time zone). Empty means every default is
    #: untouched, which is the common case and is worth being able to SAY:
    #: a status that reports an emulation nobody set is as misleading as one
    #: that hides an emulation somebody did.
    emulation: dict = field(default_factory=dict)

    def record_auth_save(self, path: str) -> None:
        self.saved_auth_at = time.time()
        self.saved_auth_path = path

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
                   channel: str | None = None, headless: bool | None = None,
                   device: str | None = None, viewport=None,
                   locale: str | None = None, timezone: str | None = None
                   ) -> Session:
        """Launch a browser on an owned profile and mint a session handle.

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
            profile = hygiene.new_profile_dir(spec.engine[:2])
            sid = self._next_session_id()
            journal = hygiene.OwnedProcesses(sid, str(profile), spec.label)
            before = {p["pid"] for p in hygiene.snapshot_processes()}
            kwargs = lanes.launch_kwargs(spec, str(profile), emulation)
            browser_type = getattr(pw, spec.engine)
            try:
                context = await browser_type.launch_persistent_context(**kwargs)
            except Exception as exc:
                hygiene._remove_tree(profile)
                raise BadParams(
                    f"could not launch {spec.label}: {type(exc).__name__}: "
                    f"{str(exc)[:300]}"
                    + (f". The emulation asked for was {emulation_report}; a "
                       f"time zone the browser does not know and a device "
                       f"preset an engine cannot honor both fail at launch "
                       f"like this."
                       if emulation_report else "")) from exc
            context.set_default_timeout(DEFAULT_TIMEOUT_MS)
            # THE INSTRUMENT CHANNEL, bound before any page script in any
            # document of this session runs. It carries the closed-root
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
            session = Session(session_id=sid, spec=spec, context=context,
                              profile_dir=str(profile), journal=journal,
                              emulation=emulation_report)
            for page in context.pages:
                self._attach_page(session, page)
            if not session.pages:
                self._attach_page(session, await context.new_page())
            self.sessions[sid] = session
            for hook in SESSION_OPEN_HOOKS:
                hook(session)
            return session

    def _attach_page(self, session: Session, page: Any) -> PageHandle:
        handle = self._next_page_handle()
        record = PageHandle(handle=handle, page=page)
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
        self._attach_dialog_desk(session, record)
        session.pages[handle] = record
        session.counters["pages_opened"] += 1
        if session.focused is None:
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
            # The hold-expiry timers die with the session they belong to.
            # A task still sleeping when its loop closes is a "destroyed but
            # pending" warning at best and a dismissal against a closed page
            # at worst, and neither is a thing to leave lying around.
            desk = getattr(session, "_dialogs", None)
            for task in list(desk.tasks) if desk is not None else ():
                task.cancel()
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
                if record.crashed:
                    # A crashed renderer never recovers on the same page:
                    # replaying the driver's "Page crashed" against a dead
                    # handle is a loop, not a recovery. manage_tabs reaches
                    # the record through Session.page() and can still close
                    # or list it; everything that would READ or ACT refuses
                    # here with the real recovery.
                    raise Conflict(
                        f"page {page_handle} is dead: {record.crashed}. A "
                        f"crashed renderer does not recover on the same "
                        f"page handle. Open a fresh tab with manage_tabs("
                        f"session={session.session_id!r}, action='open', "
                        f"url=...) and continue there; this handle can only "
                        f"be closed (manage_tabs action='close'). Refs "
                        f"minted on it are gone. Extremely deep or "
                        f"pathological nesting is a known crash cause, in "
                        f"the DOM or in shadow roots.")
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
