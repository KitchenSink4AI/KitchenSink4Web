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

PHASE 0 STATUS: every function here is a STUB. It carries its real docstring,
because the description budget binds from day one and is how the lite bill
stays under 1,500 tokens, and it refuses with NOT_IMPLEMENTED. None of them
touches a browser, because no browser code exists in this build.
"""

from __future__ import annotations

from ..errors import NotImplementedYet


def _stub(name: str, phase: str) -> None:
    raise NotImplementedYet(
        f"{name} is registered but has no engine yet. This build is the "
        f"Phase 0 scaffold: the package, the envelope, the policy layer, "
        f"and the tool surface exist, and no browser code does. {name} "
        f"lands in {phase}."
    )


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
    _stub("get_page_view", "Phase 2")
    return {}


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
    _stub("navigate", "Phase 4")
    return {}


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
    _stub("manage_tabs", "Phase 1")
    return {}


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
    _stub("manage_session", "Phase 1")
    return {}


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
    _stub("get_workflows", "Phase 0")
    return {}


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
