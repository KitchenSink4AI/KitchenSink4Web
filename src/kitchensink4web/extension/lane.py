"""Lane C's page object: the extension, wearing the shape the ops layer reads.

`projection/` states its own seam in its module docstring: *"This package
never imports playwright. It takes a page-like object with an `evaluate`
method."* That sentence is the whole design of this file. `ExtensionPage`
is that object, and every block downstream of the projection -- the ranker,
the meter, the render ladder, the anchor map, `act.target_descriptor`,
`act.action_class_for`, the gate fingerprint -- then applies to Lane C
unchanged, because it is looking at units produced by the same `extract.js`.

**`evaluate` takes a NAME, not source, and the mapping is closed.** A
Playwright page compiles whatever string it is handed. A content script
cannot, without `unsafe-eval` in the manifest, and should not want to: the
other end of this pipe is a native messaging host. So the extension ships
the five projection scripts as a bundle and this class maps the SOURCE the
ops layer hands it back to the NAME the extension knows, by identity against
`projection.EXTRACT_JS` and its siblings. A source that is not one of the
five refuses, naming what Lane C can run.

**What the lane does not own.** The browser is the user's. `hygiene` never
learns a pid for it, `close` disconnects and leaves every window where it
was, and nothing in this file kills anything.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any

from .. import projection as _projection
from ..errors import BadParams, Conflict, LaneUnsupported
from .bridge import Bridge, BridgeError, NoBrowserConnected


class PageMoved(Conflict):
    """The page changed between the read that was judged and the act.

    Not an error the caller ever sees. It is raised by `act()` when the
    browser refused a guarded action because the document had moved, and
    `ops/extops._act` answers it by re-reading the page and putting the new
    descriptor through the same `TargetChanged` comparison the lane has always
    run. A guard that produced a user-visible failure where phase 2 succeeded
    would be a regression wearing an optimisation's name.
    """

#: Source -> the name the extension bundle knows it by. Built once, from the
#: same module the Playwright lane evaluates, so a projection source that
#: changes changes both sides at once or fails the bundle drift test.
def _script_names() -> dict[int, str]:
    return {
        id(_projection.EXTRACT_JS): "extract",
        id(_projection.FIND_JS): "find",
        id(_projection.TEXT_JS): "text",
        id(_projection.ARTICLE_JS): "article",
        id(_projection.SCHEMA_JS): "schema",
    }


#: The same table keyed by the source text, for a caller that rebuilt the
#: string rather than passing the module constant through.
def _script_texts() -> dict[str, str]:
    return {
        _projection.EXTRACT_JS: "extract",
        _projection.FIND_JS: "find",
        _projection.TEXT_JS: "text",
        _projection.ARTICLE_JS: "article",
        _projection.SCHEMA_JS: "schema",
    }


def origin_of(url: str | None) -> str | None:
    """The scheme-and-host origin of a URL, or None when it has none.

    Deliberately NOT the hostname: the browser-side gate compares
    `new URL(url).origin`, so a mismatch in what the two sides call an origin
    would show up as a page nobody can read rather than as an error."""
    if not url:
        return None
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def script_name(source: str) -> str | None:
    """The bundle name for a projection source, or None when it is not one."""
    found = _script_names().get(id(source))
    if found:
        return found
    return _script_texts().get(source)


class ExtensionPage:
    """One tab and one frame of it, reachable through the extension.

    The surface is what the ops layer actually reads off a page object, and
    no more. `url` is a PROPERTY on a Playwright page and a property here,
    which means it has to be answered without a round trip: the value is
    what the last command reported, refreshed by every navigate, read, and
    act, exactly as the driver's own cached URL is.
    """

    def __init__(self, bridge: Bridge, tab_id: int | None = None,
                 frame_id: int = 0, url: str = "about:blank",
                 title: str = "") -> None:
        self._bridge = bridge
        self.tab_id = tab_id
        self.frame_id = frame_id
        self._url = url
        self._title = title
        #: The last read's `navigator.webdriver`, carried on every payload
        #: this lane produces. Phase 1 made the claim checkable in production
        #: rather than arguing it once in a design document, and Phase 2 does
        #: not get to stop checking it.
        self.webdriver: bool | None = None
        self.last_ms: float | None = None
        #: The digest the LAST evaluate was taken at, or None when the
        #: document was in a state the browser would not stand behind (a
        #: running animation, a mutation during the walk). The acting path
        #: passes it back down as the staleness guard; None means it takes
        #: the two-walk route phase 2 always took.
        self.last_digest: str | None = None
        #: THE UNCHANGED-PAGE CACHE. One extraction per (script, arguments),
        #: within one digest generation: the moment a walk comes back stamped
        #: differently from the stored generation, every entry is stale and
        #: all of them go, which is what keeps this bounded on a page being
        #: read with several different arguments.
        self._cache: dict[tuple, Any] = {}
        self._cache_digest: str | None = None
        #: Counters, for the measurement harness and the tests. Nothing in
        #: the payload reads them: a cached read and a walked read are the
        #: same answer, and a caller who could tell them apart would start
        #: branching on which one it got.
        self.cache_hits = 0
        self.cache_misses = 0

    # ---------------------------------------------------------------- identity

    @property
    def url(self) -> str:
        return self._url

    @property
    def bridge(self) -> Bridge:
        return self._bridge

    async def title(self) -> str:
        return self._title

    def _params(self, extra: dict | None = None) -> dict:
        params: dict = {"frameId": self.frame_id}
        if self.tab_id is not None:
            params["tabId"] = self.tab_id
        if extra:
            params.update(extra)
        return params

    async def _call(self, method: str, params: dict | None = None,
                    timeout: float = 30.0) -> Any:
        """One command, off the event loop.

        The bridge is threads and blocking sockets, because the relay it
        talks to is a process the BROWSER starts and stops at times nothing
        here controls. `to_thread` is the seam between that and the ops
        layer's asyncio, and it is one place rather than every call site.
        """
        try:
            return await asyncio.to_thread(
                self._bridge.request, method, params, timeout)
        except NoBrowserConnected as exc:
            raise _no_browser(exc) from exc
        except BridgeError as exc:
            raise _extension_refusal(exc, method) from exc

    def _absorb(self, result: dict) -> dict:
        """Take the identity facts every page command carries."""
        if not isinstance(result, dict):
            return result
        if result.get("url"):
            self._url = result["url"]
        if result.get("title") is not None:
            self._title = result["title"]
        if result.get("tabId") is not None:
            self.tab_id = result["tabId"]
        if result.get("webdriver") is not None:
            self.webdriver = bool(result["webdriver"])
        if result.get("readMs") is not None:
            self.last_ms = result["readMs"]
        return result

    # -------------------------------------------------------------- the seam

    async def evaluate(self, source: str, arg: Any = None,
                       timeout: float = 60.0) -> Any:
        """Run a projection script in the page. THE SEAM.

        Refuses a source that is not one of the five the extension shipped,
        and the refusal names them: an ops path that reaches Lane C with an
        ad-hoc snippet is a real gap in the port, and finding out about it
        as a typed refusal beats finding out as a page that quietly did not
        do the thing.
        """
        name = script_name(source)
        if name is None:
            raise LaneUnsupported(
                "[lane C(extension)] this lane runs the projection scripts "
                "the extension shipped and cannot compile source sent over "
                "the wire: a content script has no eval without "
                "'unsafe-eval' in the manifest, and a native messaging pipe "
                "that could carry code is a shape this build will not ship. "
                f"The scripts it runs are {sorted(_script_texts().values())}. "
                "Open the session on lane 'A' or 'B' for anything else.")
        key = (name, _argkey(arg))
        params = {"script": name, "arg": arg or {}}
        held = self._cache.get(key)
        if held is not None and self._cache_digest:
            # THE CHECK AND THE WALK ARE ONE MESSAGE, deliberately. Asking
            # "has anything changed?" and then asking for the walk would be
            # two round trips with a page running between them, and the
            # answer to the first would be about a document the second one no
            # longer describes. The browser compares and decides in one
            # synchronous turn; a miss costs exactly what a plain read cost.
            params["ifChangedFrom"] = self._cache_digest
        result = self._absorb(await self._call(
            "page.evaluate", self._params(params), timeout=timeout))
        digest = result.get("digest")
        self.last_digest = digest
        if result.get("unchanged"):
            self.cache_hits += 1
            return copy.deepcopy(held)
        self.cache_misses += 1
        data = result.get("data")
        if isinstance(data, dict):
            data = _lane_completeness(data)
        self._remember(key, digest, data)
        return data

    def _remember(self, key: tuple, digest: str | None, data: Any) -> None:
        """Hold one walk against the digest the browser took it at.

        Nothing is held without a digest, and a digest the browser would not
        vouch for arrives as None: a document with a running animation, or one
        that mutated while the walk was running, is one where the answer and
        the state it describes have already come apart.
        """
        if digest != self._cache_digest:
            # A DIFFERENT DOCUMENT STATE, so every entry taken at the old one
            # describes a page that no longer exists. They go together rather
            # than aging out one at a time, which is what makes "the cache is
            # never stale" a property of the structure instead of a claim
            # about eviction order.
            self._cache.clear()
            self._cache_digest = digest
        if not digest or not isinstance(data, dict) or data.get("error"):
            self._cache.pop(key, None)
            self._cache_digest = None if not digest else self._cache_digest
            return
        self._cache[key] = copy.deepcopy(data)

    async def stamp(self, timeout: float = 15.0) -> dict:
        """The digest on its own. For the tests and the harness."""
        return self._absorb(await self._call("page.stamp", self._params(),
                                             timeout=timeout))

    # ------------------------------------------------------------ the commands

    async def read(self, timeout: float = 30.0) -> dict:
        """The cheap text read Phase 1 proved, kept for probes and for the
        readiness settle."""
        return self._absorb(await self._call("page.read", self._params(),
                                             timeout=timeout))

    async def ready(self, timeout: float = 15.0) -> dict:
        return self._absorb(await self._call("page.ready", self._params(),
                                             timeout=timeout))

    def forget(self) -> None:
        """Drop the page-state cache. A new document is a new everything.

        The digest carries a per-document id, so a stale entry could not
        match across a navigation in any case; this makes that structural
        rather than incidental, and it stops a session holding three hundred
        kilobytes of a page it has left."""
        self._cache.clear()
        self._cache_digest = None
        self.last_digest = None

    async def goto(self, url: str, wait_until: str = "complete",
                   timeout_ms: int = 30000) -> dict:
        self.forget()
        result = self._absorb(await self._call(
            "page.navigate",
            self._params({"url": url, "waitUntil": wait_until,
                          "timeoutMs": timeout_ms}),
            timeout=(timeout_ms / 1000.0) + 10.0))
        return result

    async def history(self, action: str, timeout_ms: int = 30000) -> dict:
        self.forget()
        return self._absorb(await self._call(
            "page.navigate",
            self._params({"action": action, "timeoutMs": timeout_ms}),
            timeout=(timeout_ms / 1000.0) + 10.0))

    async def act(self, action: str, ref: str, value: Any = None,
                  timeout: float = 30.0,
                  expect_digest: str | None = None) -> dict:
        """One act, optionally fenced by the state the decision was made on.

        `expect_digest` is the digest the judged read was taken at. The
        browser compares it in the same synchronous turn as the dispatch, so
        nothing can run between the comparison and the action; a mismatch
        does nothing and raises `PageMoved` here, which the ops layer answers
        with the full re-read and the `TargetChanged` comparison.
        """
        params = {"action": action, "ref": ref, "value": value}
        if expect_digest:
            params["expectDigest"] = expect_digest
        # A write we are about to make is a change the page-state cache
        # cannot see coming, and the browser bumps its own revision for it;
        # dropping the local copy here means a read racing this act on
        # another task cannot be served from a generation this act ended.
        self._cache.clear()
        self._cache_digest = None
        return self._absorb(await self._call(
            "page.act", self._params(params), timeout=timeout))

    async def mask(self, selector: str, timeout: float = 15.0) -> dict:
        """Paint over the secret and payment fields, and say how many.

        The selector is `capture.MASK_CSS`, the same string the Playwright
        lane hands its own masking, sent as DATA. The count is what lets the
        caller fail closed: a page with secret fields whose mask did not go
        on must not be captured."""
        return await self._call("page.mask",
                                self._params({"selector": selector}),
                                timeout=timeout)

    async def unmask(self, timeout: float = 15.0) -> dict:
        return await self._call("page.unmask", self._params(),
                                timeout=timeout)

    async def screenshot(self, image_format: str = "png",
                         quality: int | None = None,
                         timeout: float = 60.0) -> dict:
        params = self._params({"format": image_format})
        if quality is not None:
            params["quality"] = quality
        return self._absorb(await self._call("page.screenshot", params,
                                             timeout=timeout))

    async def frames(self, timeout: float = 15.0) -> list[dict]:
        result = await self._call("bg.frames", self._params(), timeout=timeout)
        return result.get("frames", [])


#: Where the honest absence goes. `extract.js` writes `closed_shadow_roots`
#: from `KS.closed`, and on this lane that field is null: counting closed
#: shadow roots means patching `Element.prototype.attachShadow` where PAGE
#: script calls it, and `Element.prototype` reached from a content script is
#: the Xray view. A zero this lane did not earn would be a completeness claim
#: it cannot back, which is the exact failure the closed-root line exists to
#: prevent, so the field stays None and the renderers print the absence.
def _lane_completeness(data: dict) -> dict:
    completeness = data.get("completeness")
    if isinstance(completeness, dict) and "closed_shadow_roots" in completeness:
        if not completeness.get("closed_shadow_roots"):
            completeness["closed_shadow_roots"] = None
    return data


def _no_browser(exc: Exception) -> Exception:
    return Conflict(
        "[lane C(extension)] no browser is connected to this session: the "
        "KS4Web extension is not installed, not enabled, or the browser it "
        "runs in is not open. Nothing was done. "
        "[COPY PENDING] Lane C install instruction sentence."
        f" ({exc})")


def _argkey(arg: Any) -> str:
    """A stable key for an evaluate's argument.

    `json.dumps` with sorted keys rather than `repr`, because two dicts that
    differ only in insertion order describe the same call and must not get two
    cache entries. `default=str` keeps an unexpected type from raising in a
    caching path, where an exception would be the optimisation breaking the
    read it was meant to speed up."""
    try:
        return json.dumps(arg or {}, sort_keys=True, default=str)
    except Exception:                                    # pragma: no cover
        return repr(arg)


def _extension_refusal(exc: BridgeError, method: str) -> Exception:
    text = str(exc)
    code = text.split(":", 1)[0].strip()
    if code == "STATE_CHANGED":
        return PageMoved(
            f"[lane C(extension)] the page moved between the read the policy "
            f"judged and the act; nothing was done. {text}")
    if code == "ORIGIN_NOT_CONSENTED":
        return Conflict(
            f"[lane C(extension)] the browser refused {method}: {text}")
    if code == "RATE_LIMITED":
        return Conflict(
            f"[lane C(extension)] the extension is throttling commands: "
            f"{text}")
    if code in ("STALE_REF", "BUNDLE_MISSING"):
        return Conflict(f"[lane C(extension)] {text}")
    if code == "REFUSED_SCHEME":
        return BadParams(f"[lane C(extension)] {text}")
    return Conflict(f"[lane C(extension)] {method} failed: {text}")


class ExtensionContext:
    """The Lane C stand-in for a Playwright browser context.

    A cookie jar this server does not own and must never treat as one. There
    is no profile directory to remove, no process to kill, and no
    `add_init_script` to install: the jar is the user's own browser profile
    and the only thing this object holds is the pipe to it.
    """

    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.pages: list[ExtensionPage] = []
        self.opened = time.time()
        #: THE ORIGINS THE LADDER HAS APPROVED, this session, in order.
        #: Seeded at open with the tab the human was already on, because the
        #: `real_profile_browse` answer they just gave was about the browser
        #: as it stands. Everything after that is added only once
        #: `policy.engine.approve` has passed for a navigation there, so the
        #: set is a record of decisions rather than a list somebody typed.
        self.consented: list[str] = []

    async def probe(self, timeout: float = 15.0) -> dict:
        try:
            return await asyncio.to_thread(
                self.bridge.request, "bg.ping", None, timeout)
        except NoBrowserConnected as exc:
            raise _no_browser(exc) from exc

    async def tabs(self, timeout: float = 15.0) -> list[dict]:
        result = await asyncio.to_thread(
            self.bridge.request, "bg.tabs", None, timeout)
        return result.get("tabs", [])

    async def set_consent(self, origins, timeout: float = 15.0) -> dict:
        """Record the ladder's answer browser-side.

        The Python consent ladder is the authority and is what asks the
        human. This is the browser's copy of the answer, so a command that
        somehow reached the pipe for an origin nobody approved never touches
        a page. Defence in depth, and stated as that rather than as the
        gate: the gate is `policy/engine.approve`.
        """
        self.consented = sorted(set(origins))
        return await asyncio.to_thread(
            self.bridge.request, "consent.set",
            {"origins": self.consented}, timeout)

    async def allow_origin(self, url: str | None,
                           timeout: float = 15.0) -> bool:
        """Widen the browser-side set by ONE origin the ladder just passed.

        Called from the navigate body after `approve()` returns and never
        before it, which is what makes this list a record of decisions
        instead of a second policy nobody audits. Returns whether anything
        changed, so an ordinary navigation inside one site costs no round
        trip at all.
        """
        origin = origin_of(url)
        if origin is None or origin in self.consented:
            return False
        await self.set_consent(self.consented + [origin], timeout=timeout)
        return True

    async def audit(self, limit: int = 100, timeout: float = 15.0) -> dict:
        return await asyncio.to_thread(
            self.bridge.request, "audit.read", {"limit": limit}, timeout)

    async def close(self) -> None:
        """Disconnect. THE BROWSER IS NOT CLOSED and no window moves.

        Lane A and Lane B own their browsers and tear them down; this one is
        the user's, was running before the session opened, and goes on
        running after it. A close that took the user's windows down with it
        would be the single worst thing this lane could do.
        """
        self.pages.clear()
