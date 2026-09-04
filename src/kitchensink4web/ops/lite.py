"""The lite core: the tools every user gets with no flags at all.

DESIGN 2.1, with two membership decisions applied from the design review's
arithmetic note and recorded here rather than only in the BUILD_LOG:

- **`request_handoff` is folded into `manage_session` as an action.** It was
  lite candidate 15. The design already flagged the fold as the likely
  outcome if the measured bill ran hot, and the review's arithmetic made
  that concrete: the density math says under 1,500 tokens buys roughly 10 to
  14 tools, and the roster already listed 14. Folding costs nothing
  conceptually, since handing a headed window to a human IS a session
  operation, and `manage_session` is already the action-parameter tool for
  session lifecycle.
- **`emulate` is dropped from lite** and lives in the `capture` pack. It was
  candidate 16, and its case was always a token argument rather than a
  capability one (Playwright's own agent skill recommends mobile emulation
  because mobile pages produce smaller snapshots). KS4Web does not need that
  lever, because the projection is what makes reads small, so paying lite
  budget for a second cost lever is paying twice for one thing.

Result: **14 lite tools**, which is the top of the affordable range rather
than over it, with the two candidates resolved rather than carried.

PHASE 1 STATUS. Four tools are wired to a real browser: `manage_session`,
`manage_tabs`, `navigate`, and `get_page_view`, which is the engine core plus
the projection's first real integration. The action tools (`click`,
`type_text`, `fill_form`, `press_keys`, `scroll`, `wait_for`) land in Phase 4
behind the policy layer, and `find_elements`, `get_text`, and `get_audit` land
with the anchors and the audit writer. Every one of those still refuses
honestly rather than returning plausible output, because a tool that reports
success without doing anything is the exact disease this product argues
against.

Docstrings are unchanged from Phase 0 on purpose. The description budget is a
ratchet: the lite surface may shrink and may not grow while the 1,500-token
target is an open author call.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

from ..engine import lanes, session as _session
from ..errors import (AuthRequired, BadParams, BlockedBySite, LaneUnsupported,
                      NotImplementedYet)
from ..policy import readonly
from ..projection import ENCODING_NAME as _ENCODING, RUNGS as _RUNGS, read_page
from ..projection.render import VIEWS as _PROJECTION_VIEWS

MANAGER = _session.MANAGER

#: `detail` scales the budget rather than switching representation. The
#: representation is what `view` chooses; detail is how much of it you are
#: willing to pay for, which is the honest reading of a knob whose whole job
#: is the token bill.
_DETAIL_SCALE = {"lite": 0.5, "standard": 1.0, "full": 2.0}


def _stub(name: str, phase: str) -> None:
    raise NotImplementedYet(
        f"{name} is registered but has no engine yet. Phase 1 built the "
        f"browser core (sessions, lanes, process hygiene, navigation) and "
        f"the projection. {name} lands in {phase}, and until then it refuses "
        f"rather than returning something plausible."
    )


def _parse_lane(lane: str | None) -> dict:
    """`lane` carries the whole launch shape in one string.

    Accepted: 'A' (bundled Chromium), 'A:firefox', 'B:chrome', 'B:msedge',
    'B:moz-firefox', any of them with '+headed'. One parameter rather than
    four keeps the flagship schemas inside the per-tool ceiling, and a typo is
    an error rather than a silent downgrade to some other lane."""
    if not lane:
        return {}
    text = lane.strip()
    headless = True
    if "+headed" in text:
        headless = False
        text = text.replace("+headed", "")
    parts = [p for p in text.split(":") if p]
    if not parts:
        raise BadParams(
            "lane is empty. Use 'A' for a bundled browser, 'A:firefox' for "
            "the bundled Firefox, or 'B:chrome' / 'B:msedge' / "
            "'B:moz-firefox' for your installed one. Append '+headed' for a "
            "visible window.")
    name = parts[0].upper()
    which = parts[1] if len(parts) > 1 else None
    if name == "B":
        return {"lane": "B", "channel": which or "chrome", "headless": headless}
    return {"lane": name, "engine": which or "chromium", "headless": headless}


def _identity(record, status=None, load_state=None) -> dict:
    return {"page": record.handle, "url": record.page.url,
            "status": status, "load_state": load_state}


async def _robots_advisory(sess, url: str) -> dict:
    """robots.txt surfaced as an ADVISORY, per the honest-tool posture.

    KS4Web does not evade access controls and does not claim compliance with
    any site's terms on the user's behalf either. What it can do is tell you
    what the site published, which is the honest half of the row both
    incumbents vacated."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"checked": False, "why": "not an http(s) origin"}
        origin = f"{parsed.scheme}://{parsed.netloc}"
        cache = getattr(sess, "_robots", None)
        if cache is None:
            cache = sess._robots = {}
        if origin not in cache:
            res = await sess.context.request.get(
                origin + "/robots.txt", timeout=5000)
            cache[origin] = await res.text() if res.ok else ""
        body = cache[origin]
        if not body:
            return {"checked": True, "found": False}
        path = parsed.path or "/"
        disallowed = []
        applies = False
        for raw in body.splitlines():
            line = raw.split("#")[0].strip()
            if not line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                applies = value == "*"
            elif key == "disallow" and applies and value:
                disallowed.append(value)
        hit = next((d for d in disallowed if path.startswith(d)), None)
        return {"checked": True, "found": True,
                "path_disallowed_for_wildcard_agent": bool(hit),
                "rule": hit}
    except Exception as exc:  # an advisory that fails is still only advisory
        return {"checked": False, "why": f"{type(exc).__name__}"}


#: Markers that mean a wall rather than a page. Conservative on purpose: a
#: false refusal costs the user a page, and the alternative failure (burning
#: turns retrying against a wall) is what this detection exists to stop.
_WALL_MARKERS = (
    "just a moment...", "checking your browser", "cf-challenge",
    "attention required! | cloudflare", "captcha-delivery",
    "please verify you are a human", "unusual traffic from your computer",
)


async def _wall_verdict(page, status: int | None) -> dict:
    """Detect a bot wall, a CAPTCHA interstitial, or an auth wall and say so.

    Cloudflare interstitials, CAPTCHAs, rate limits, and expired sessions all
    currently surface to an agent as a timeout or an empty page, so the agent
    burns turns retrying against a wall it cannot pass. The stakes argument is
    not "requests get blocked": a user's App Store Connect account was
    terminated for fraud after an agent filled forms."""
    verdict = {"wall": None, "status": status}
    try:
        title = (await page.title() or "").lower()
    except Exception:
        title = ""
    body = ""
    try:
        body = (await page.evaluate(
            "() => (document.body ? document.body.innerText : '')"
            ".slice(0, 4000)") or "").lower()
    except Exception:
        pass
    marker = next((m for m in _WALL_MARKERS if m in title or m in body), None)
    if marker:
        verdict["wall"] = "bot-wall-or-captcha"
        verdict["marker"] = marker
    elif status == 429:
        verdict["wall"] = "rate-limited"
    elif status == 403 and ("captcha" in body or "blocked" in title):
        verdict["wall"] = "forbidden-challenge"
    return verdict


# --------------------------------------------------------------- the reads


async def get_page_view(
    page: str,
    view: str = "auto",
    detail: str = "standard",
    location: dict | None = None,
    budget_tokens: int = 5000,
    cursor: str | None = None,
    since: str | None = None,
    include_hidden: bool = False,
) -> dict:
    """Read a page as an ORIENTATION, not a transcript, under a token budget
    it never exceeds whatever the page size. Returns identity, landmark
    regions each priced with the cost to expand it, the interactive surface
    with refs you can act on, a digest or app skeleton, form and table
    inventories, an account of what was NOT read and why, and the next call
    for anything unexpanded. `location` scopes to one region or frame,
    `since` gives a delta, `budget_tokens=2500` suits a subagent.
    """
    for name, value in (("location", location), ("cursor", cursor),
                        ("since", since)):
        if value:
            _stub(f"get_page_view({name}=...)", "Phase 2 (anchors and deltas)")
    if include_hidden:
        _stub("get_page_view(include_hidden=True)", "Phase 2")
    if view not in _PROJECTION_VIEWS:
        raise BadParams(
            f"unknown view {view!r}. Phase 1 serves {sorted(_PROJECTION_VIEWS)}; "
            f"'read', 'links', and 'dom' land in Phase 2 with get_text and the "
            f"DOM projection.")
    if detail not in _DETAIL_SCALE:
        raise BadParams(
            f"unknown detail {detail!r}; the levels are "
            f"{sorted(_DETAIL_SCALE)}.")
    sess, record = MANAGER.locate(page)
    budget = max(200, int(budget_tokens * _DETAIL_SCALE[detail]))
    record.touch(record.page.url)
    sess.counters["reads"] += 1
    meta = {"status": getattr(record, "last_status", None),
            "load_state": getattr(record, "last_load_state", "load"),
            "lane": sess.spec.label, "page": record.handle,
            "read_token": f"rt{sess.counters['reads']}",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    result = await read_page(record.page, meta, budget=budget, view=view)
    return {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url, "lane": sess.spec.lane,
        # The projection IS the payload. Nothing structured here repeats what
        # the text already carries, because the measured token bill is what
        # the client actually pays and duplicating the completeness block into
        # a parallel dict would double it.
        "projection": result.text,
        "budget": {"used": result.tokens, "limit": budget,
                   "margin_held": result.meter.margin, "rung": result.rung,
                   "rungs": len(_RUNGS), "estimator": _ENCODING},
    }


async def find_elements(
    page: str,
    query: str,
    kind: str = "auto",
    limit: int = 20,
    location: dict | None = None,
) -> dict:
    """Find elements by text, role plus accessible name, natural-language
    description, CSS, or XPath, and get back refs you can act on plus a note
    on what was not searched. This is the cheap targeted follow-up that
    pairs with get_page_view: the page view tells you what string to look
    for, and this retrieves it for a fraction of a full read. Ambiguous
    results are listed rather than resolved, and zero results come back with
    the nearest misses so a miss is a one-turn recovery.
    """
    _stub("find_elements", "Phase 2")
    return {}


async def get_text(
    page: str,
    location: dict | None = None,
    start_index: int = 0,
    max_chars: int = 20000,
    include_hidden: bool = False,
) -> dict:
    """Extract readable prose from a page or one region of it, paginated by
    `start_index` so a long article is read in bounded pieces rather than
    one unbounded dump. Text arrives as labeled data with its origin stated,
    hidden regions are stripped and counted rather than silently dropped or
    silently included, and the result carries refs so anything mentioned in
    the prose can still be acted on without a second read.
    """
    _stub("get_text", "Phase 2")
    return {}


# ------------------------------------------------------------- the actions


async def navigate(
    page: str,
    action: str = "goto",
    url: str | None = None,
    wait_until: str = "load",
    timeout_ms: int = 30000,
) -> dict:
    """Go to a URL, or go back, forward, reload, or stop, and wait for the
    load state you name. Returns the final identity after redirects, the
    HTTP status, a robots.txt advisory, and a verdict on whether the
    destination is a bot wall, a CAPTCHA interstitial, or a login wall, so a
    blocked request is reported as blocked instead of surfacing as a timeout
    or an empty page that invites a retry loop.
    """
    sess, record = MANAGER.locate(page)
    before = record.page.url
    status = None
    action = (action or "goto").strip().lower()

    if action in ("back", "forward"):
        # LOUD refusal rather than a pass-through. On Firefox/BiDi the
        # navigation actually happens, the driver never reports it, and
        # page.url goes stale afterward, so the failure is not an absence, it
        # is a lie. KS4Web tracks page history for exactly this substitute.
        if lanes.capability(sess.spec, "history_navigation") == "unsupported":
            row = lanes.CAPABILITIES["history_navigation"]
            previous = record.previous_url
            raise LaneUnsupported(
                f'[lane {sess.spec.label}] {row["message"]}'
                + (f' The previous URL on this page was {previous}.'
                   if previous else ''))
        response = await _session.with_timeout(
            record.page.go_back() if action == "back"
            else record.page.go_forward(), timeout_ms, f"navigate({action})")
        status = response.status if response else None
    elif action == "reload":
        response = await _session.with_timeout(
            record.page.reload(wait_until=wait_until), timeout_ms,
            "navigate(reload)")
        status = response.status if response else None
    elif action == "stop":
        await record.page.evaluate("() => window.stop()")
    elif action == "wait_for_load":
        await _session.with_timeout(
            record.page.wait_for_load_state(wait_until), timeout_ms,
            f"navigate(wait_for_load, {wait_until})")
    elif action == "goto":
        if not url:
            raise BadParams(
                "navigate(action='goto') needs a url. The other actions are "
                "'back', 'forward', 'reload', 'stop', and 'wait_for_load'.")
        response = await _session.with_timeout(
            record.page.goto(url, wait_until=wait_until, timeout=timeout_ms),
            timeout_ms + 2000, f"navigate(goto, {url})")
        status = response.status if response else None
        sess.counters["navigations"] += 1
        sess.origins.add(urlparse(record.page.url).netloc)
        sess.counters["origins"] = len(sess.origins)
    else:
        raise BadParams(
            f"unknown navigate action {action!r}: the actions are 'goto', "
            f"'back', 'forward', 'reload', 'stop', and 'wait_for_load'.")

    record.touch(record.page.url)
    record.last_status = status
    record.last_load_state = wait_until
    verdict = await _wall_verdict(record.page, status)
    if status == 401:
        raise _auth_refusal(record.page.url)
    if verdict["wall"]:
        raise BlockedBySite(
            f'{record.page.url} answered with a {verdict["wall"]} rather than '
            f'the page (HTTP {status}). KS4Web does not retry against a wall '
            f'and does not defeat one: open the page in a headed window with '
            f'manage_session(action="handoff") so a human can clear it, or '
            f'come back later. Evidence: '
            f'{verdict.get("marker") or "HTTP status"}.')
    return {
        "session": sess.session_id, "page": record.handle,
        "lane": sess.spec.lane,
        "changed": {"effect": "navigated" if record.page.url != before
                    else "same-url", "from": before, "to": record.page.url},
        "url": record.page.url, "status": status,
        "title": await record.page.title(),
        "load_state": wait_until,
        "robots": await _robots_advisory(sess, record.page.url),
        "verdict": verdict,
        "history_depth": len(record.history),
    }


def _auth_refusal(url: str):
    return AuthRequired(
        f"{url} answered 401: it needs a signed-in session. Load a saved "
        f"state with the storage pack (--packs storage, load_auth_state), or "
        f"hand the headed window to a human with "
        f"manage_session(action='handoff') so the login happens outside the "
        f"model's context.")


async def click(
    page: str,
    location: dict,
    button: str = "left",
    click_count: int = 1,
    modifiers: list[str] | None = None,
    timeout_ms: int = 15000,
) -> dict:
    """Click an element addressed by ref, anchor, role and name, text, or as
    a last resort a coordinate. Input is dispatched through the driver as
    trusted input, never synthesized as DOM events, because modern React
    handlers check event.isTrusted and silently do nothing on synthetic
    clicks. Returns a VERIFIED outcome: what actually changed, or an
    explicit none-observed with a warning rather than a bare ok.
    """
    _stub("click", "Phase 4")
    return {}


async def type_text(
    page: str,
    location: dict,
    text: str,
    clear_first: bool = False,
    press_enter: bool = False,
    delay_ms: int = 0,
) -> dict:
    """Type into a field addressed by any selector, optionally clearing it
    first or pressing Enter after. Refuses to write into a password,
    new-password, or one-time-code field and names the two sanctioned routes
    instead, so a credential never passes through the model's context.
    Returns a verified outcome including the field's value state read back,
    so a silently rejected input is visible rather than reported as success.
    """
    _stub("type_text", "Phase 4")
    return {}


async def fill_form(
    page: str,
    fields: list[dict],
    location: dict | None = None,
    submit: bool = False,
) -> dict:
    """Set many form fields in one call and read the form state back. This
    is the largest single token saving available in the interaction
    category. Every ref resolves before anything executes, and each target
    is re-checked immediately before its own turn, because typing into one
    field routinely re-renders its siblings. A failure stops the batch:
    completed items stay completed, the rest report not_attempted.
    """
    _stub("fill_form", "Phase 4")
    return {}


async def press_keys(
    page: str,
    keys: str,
    location: dict | None = None,
    repeat: int = 1,
    delay_ms: int = 0,
) -> dict:
    """Press a key or a chord, optionally repeated, either globally or with
    a named element focused first. Accepts the usual spellings for modifiers
    and named keys. Dispatched as trusted input through the driver rather
    than synthesized, and returns a verified outcome so a chord the page
    ignored is reported as none-observed instead of as a success the agent
    then builds several more steps on top of.
    """
    _stub("press_keys", "Phase 4")
    return {}


async def scroll(
    page: str,
    action: str = "by",
    amount: int = 1,
    location: dict | None = None,
    timeout_ms: int = 10000,
) -> dict:
    """Scroll by an amount, to a named element, to the end, or inside a
    specific container, plus a next-chunk mode that remembers position
    across calls so a long page is walked without re-reading it. Reports how
    much content is now reachable and how much remains below, and names
    virtualized containers where the DOM holds far fewer rows than the page
    claims, rather than presenting a partial list as complete.
    """
    _stub("scroll", "Phase 4")
    return {}


async def wait_for(
    page: str,
    condition: str,
    value: str | None = None,
    location: dict | None = None,
    timeout_ms: int = 30000,
) -> dict:
    """Wait for text to appear or disappear, an element to reach a state, a
    URL to match, a request or response, a download, or a JS predicate to
    hold. Real timeouts, and a failure that says what was awaited and what
    was observed instead rather than a bare expiry. Use this instead of
    guessing at sleeps: a wait that names its condition is also a wait the
    audit log can explain afterward.
    """
    _stub("wait_for", "Phase 4")
    return {}


# ------------------------------------------------------------ the plumbing


async def manage_tabs(
    session: str,
    action: str = "list",
    page: str | None = None,
    url: str | None = None,
) -> dict:
    """List, open, select, or close tabs, report which is focused, and
    capture pages a click opened in a popup. Mints and returns the explicit
    page handles every other tool accepts, which is how browser state
    survives across calls without relying on protocol sessions. Closing a
    page invalidates its refs and its delta read tokens, and the result says
    so rather than leaving a later failure to explain it.
    """
    sess = MANAGER.session(session)
    action = (action or "list").strip().lower()

    if action == "list":
        pass
    elif action == "focused":
        return {"session": sess.session_id, "focused": sess.focused,
                "url": sess.page(sess.focused).page.url}
    elif action == "open":
        new_page = await sess.context.new_page()
        record = MANAGER._attach_page(sess, new_page)
        sess.focused = record.handle
        if url:
            await _session.with_timeout(
                new_page.goto(url), _session.DEFAULT_TIMEOUT_MS,
                f"manage_tabs(open, {url})")
            record.touch(new_page.url)
            sess.counters["navigations"] += 1
    elif action == "select":
        record = sess.page(page)
        await record.page.bring_to_front()
        sess.focused = record.handle
        record.touch()
    elif action == "close":
        record = sess.page(page)
        await record.page.close()
        sess.pages.pop(record.handle, None)
        if sess.focused == record.handle:
            sess.focused = next(iter(sess.pages), None)
        return {
            "session": sess.session_id, "closed": record.handle,
            "focused": sess.focused,
            "invalidated": (
                f"every ref minted on {record.handle} is now gone, and so is "
                f"its delta read token. {record.handle} is never reused."),
            "pages": _tab_list(sess),
        }
    else:
        raise BadParams(
            f"unknown manage_tabs action {action!r}: the actions are 'list', "
            f"'open', 'select', 'close', and 'focused'.")
    return {"session": sess.session_id, "focused": sess.focused,
            "pages": _tab_list(sess)}


def _tab_list(sess) -> list[dict]:
    out = []
    for record in sess.pages.values():
        try:
            url = record.page.url
        except Exception:
            url = "(closing)"
        out.append({"page": record.handle, "url": url,
                    "focused": record.handle == sess.focused,
                    "parked": record.parked})
    return out


async def manage_session(
    action: str = "status",
    session: str | None = None,
    lane: str | None = None,
    reason: str | None = None,
) -> dict:
    """Open, close, or inspect a browser session, report the current lane's
    capabilities, read the budget counters, or hand the headed window to the
    human for a login, an MFA prompt, or a bot wall. The capabilities action
    is the honest-refusal instrument for the whole design: it states what
    this lane supports, what it degrades, and what it cannot do at all,
    naming the lane that would support each gap.
    """
    action = (action or "status").strip().lower()

    if action == "open":
        sess = await MANAGER.open(**_parse_lane(lane))
        return {
            "session": sess.session_id, "lane": sess.spec.lane,
            "engine": sess.spec.label, "pages": _tab_list(sess),
            "focused": sess.focused,
            "profile": (
                "a freshly created KS4Web-owned directory. KS4Web never opens "
                "your real browser profile, and every Firefox launch carries "
                "-no-remote so it cannot be adopted by a Firefox you are "
                "already running."),
            "hygiene": {"job_object": _session.hygiene.JOB.status,
                        "owned_pids": len(sess.journal.pids),
                        "startup_reap": MANAGER.startup_reap},
        }
    if action == "close":
        return await MANAGER.close(MANAGER.session(session).session_id)
    if action == "capabilities":
        sess = MANAGER.session(session)
        return lanes.capabilities_report(sess.spec)
    if action == "budget":
        sess = MANAGER.session(session)
        return {"session": sess.session_id, "counters": dict(sess.counters),
                "origins": sorted(sess.origins),
                "note": "budgets and loop detection are enforced from Phase 3; "
                        "these counters are the reporting half and are live now"}
    if action == "handoff":
        sess = MANAGER.session(session)
        if sess.spec.headless:
            raise BadParams(
                "a handoff needs a window a human can see and this session is "
                "headless. Reopen with manage_session(action='open', "
                "lane='A+headed') or 'B:chrome+headed', then hand off. Reason "
                f"given: {reason or '(none)'}.")
        return {"session": sess.session_id, "handoff": "the headed window is "
                "yours; nothing is automated until you call manage_session "
                "again", "reason": reason,
                "pages": _tab_list(sess)}
    if action == "status":
        return {
            "sessions": [
                {"session": s.session_id, "lane": s.spec.label,
                 "pages": len(s.pages), "focused": s.focused,
                 "profile_dir": s.profile_dir,
                 "owned_pids": sorted(s.journal.pids),
                 "counters": dict(s.counters)}
                for s in MANAGER.sessions.values()],
            "read_only": readonly.describe(),
            "hygiene": {"job_object": _session.hygiene.JOB.status,
                        "startup_reap": MANAGER.startup_reap,
                        "idle_park_s": _session.IDLE_PARK_S,
                        "idle_recycle_s": _session.IDLE_CLOSE_S},
        }
    raise BadParams(
        f"unknown manage_session action {action!r}: the actions are 'open', "
        f"'close', 'status', 'capabilities', 'budget', and 'handoff'.")


async def get_audit(
    session: str | None = None,
    start_index: int = 0,
    limit: int = 50,
    tool: str | None = None,
) -> dict:
    """Read the action log. Returns one record per call, paginated, carrying
    the timestamp, lane, page, URL, resolved target with its human label,
    redacted arguments, outcome, any rebind, any confirmation decision, and
    the budget counters at that moment. This is an operational record for
    the user, so you can always know exactly what was done even where a web
    action cannot be undone. It is not forensic and not evidence.
    """
    _stub("get_audit", "Phase 3")
    return {}


async def get_workflows(topic: str | None = None) -> dict:
    """Get recipes for this server. Returns the cheap-read-then-act pattern,
    the subagent budget setting, how to address frames and shadow roots, how
    refs stay valid across turns, what each capability pack contains with
    the exact launch flag that loads it, and how to record and replay a
    multi-step flow. Packs are chosen at launch rather than at runtime, so
    this is where you learn which flag you need before restarting.
    """
    from .. import packs

    recipes = {
        "cheap-read-then-act": [
            "manage_session(action='open')  opens a browser and mints s1/p1",
            "navigate(page='p1', url=...)   returns identity, status, a "
            "robots advisory, and a bot-wall verdict",
            "get_page_view(page='p1')       an orientation under a token "
            "budget it never exceeds, with refs you can act on",
            "find_elements(page='p1', query='...')  the cheap targeted "
            "follow-up when what you wanted was not in that read. This pair "
            "is the product: the first read tells you what string to look "
            "for, and an arbitrary in-prose link on a long article is not "
            "reachable in one read at any budget",
        ],
        "subagent-budget": [
            "get_page_view(page='p1', budget_tokens=2500) inside a subagent. "
            "Tool results are capped more tightly there, the cap is delivered "
            "remotely and can move, and 2,500 held on eleven pages spanning "
            "four orders of magnitude of raw size",
        ],
        "lanes": [
            "manage_session(action='open', lane='A')             bundled "
            "Chromium, the default",
            "manage_session(action='open', lane='A:firefox')     bundled "
            "Firefox",
            "manage_session(action='open', lane='B:chrome')      your "
            "installed Chrome, still on a KS4Web-owned profile",
            "manage_session(action='open', lane='B:moz-firefox') your "
            "installed Firefox, with -no-remote so it cannot be adopted by a "
            "Firefox you already have open",
            "add '+headed' to any of them for a visible window",
            "manage_session(action='capabilities') reports what the running "
            "lane supports, degrades, and cannot do, with the lane that would "
            "support each gap named",
        ],
        "packs": packs.menu(),
        "packs-are-launch-time": (
            "There is no runtime enable call. The tool set is fixed when the "
            "server starts, which is what MCP 2026-07-28 requires, so a "
            "capability you do not have needs a restart with --packs or "
            "KS4WEB_MODE rather than a call."),
        "read-only": readonly.describe(),
    }
    if topic:
        key = topic.strip().lower()
        if key not in recipes:
            raise BadParams(
                f"no workflow topic {topic!r}: the topics are "
                f"{sorted(recipes)}.")
        return {"topic": key, "workflow": recipes[key]}
    return {"workflows": recipes}


#: The lite roster, in the order DESIGN 2.1 lists it. `server.py` registers
#: exactly this and nothing else in Phase 0.
LITE_TOOLS = (
    get_page_view,
    find_elements,
    get_text,
    navigate,
    click,
    type_text,
    fill_form,
    press_keys,
    scroll,
    wait_for,
    manage_tabs,
    manage_session,
    get_audit,
    get_workflows,
)
