"""Server-level read-only mode, enforced at REGISTRATION time.

DESIGN 5.2. Nobody in the category ships this. playwright-mcp tags individual
tools read-only and leaves enforcement to the client's allowlist;
chrome-devtools-mcp has nothing; neither do Claude for Chrome, Operator,
Atlas, Comet, or browser-use. Everyone gates individual actions and nobody
offers a mode-level property.

**The mechanism is absence, not refusal.** In read-only mode the mutating
tools are never registered, so they do not appear in tools/list. There is
nothing to allowlist, nothing to misconfigure, and nothing for an injected
page instruction to reach for. That is what makes it a provable property
rather than a claim, and it is why this module is consulted during
registration rather than inside tool bodies.

It is also why it is a LAUNCH-TIME property. A runtime toggle would vary the
tool set per connection, which MCP 2026-07-28 forbids (DESIGN 7.1). The
spec constraint that killed the family's enable_tools pattern is the same
constraint that makes the strongest safety feature in this design provable,
which is a genuinely pleasant accident.

**The claim, phrased exactly.** "No tool in this mode can click, type,
submit, upload, download, evaluate script, or write storage." NEVER "cannot
change anything," because a URL can mutate server state. Read-only removes
the ACT leg of the lethal trifecta; navigation remains an outbound channel,
and `strict` paired with an origin allowlist is what closes it.

**The in-session invariant (author ruling, 2026-09-05): the agent can NEVER
flip this mode.** No tool, no argument, no MRTR or elicitation path may
change the grade once the process started. Mechanically: `apply()` is
callable only from server startup (`server.configure`), a static test scans
the tree for any other caller, no gate class touches policy, and a runtime
test drives every registered tool with flip-shaped arguments and asserts the
grade and the tool set never move. That invariant is what makes the safety
provable rather than asserted.
"""

from __future__ import annotations

import os

from ..errors import BadParams

#: THE DEFAULT, deliberately a single constant (author ruling, 2026-09-05).
#: DECIDED 2026-09-05 from field-test evidence, per the conditional ruling:
#: the read-only field test (internal notes/20260905_ks4web_readonly_field_
#: test.md) ran ten everyday tasks over a real MCP connection and read-only
#: carried 7 of 8 read-shaped tasks with ZERO mode-caused friction; the
#: predicted killer (search boxes) failed identically under full grade in a
#: controlled re-test, because the wall is the site's bot detection rather
#: than the missing keyboard; and the credential gate refuses passwords in
#: BOTH grades, so a full default buys a first-run user far less than it
#: appears to. The middle grade was assessed and rejected: it guts the
#: provable absence property for exactly the two most dangerous tools.
#:
#:     None      -> acting allowed unless --read-only or a grade env is set
#:     "browse"  -> read-only by default; acting needs an explicit opt-in
#:                  (KS4WEB_ALLOW_ACTING=true, or the .mcpb user_config
#:                  checkbox "Allow this server to click and type")
#:
#: An explicit env value or CLI flag ALWAYS beats this constant, in either
#: direction, which is what makes the checkbox UX work under both defaults.
#: Both defaults remain fully built; the constant is the whole switch.
DEFAULT_GRADE: str | None = "browse"

#: The positively-named grade env (Phase 7 release condition). The .mcpb
#: checkbox "Allow this server to click and type" maps here LITERALLY:
#: Claude Desktop writes "true" or "false", and the polarity reads the way
#: the checkbox does. An EMPTY value fails CLOSED to browse (the old env's
#: empty-unlocks behavior was a fail-open defect); an unrecognized value
#: refuses to start.
ENV_ALLOW = "KS4WEB_ALLOW_ACTING"

#: DEPRECATED alias, honored for one release. KS4WEB_ALLOW_ACTING wins when
#: both are set. Its one behavior change: an EMPTY value now fails closed
#: to browse instead of unlocking.
ENV_LEGACY = "KS4WEB_READ_ONLY"

#: The unlock teaching (the field test's BLOCKING condition): under a
#: read-only default every new user meets the absent-tool wall on day one,
#: so every surface that says WHAT the mode is must also say HOW a human
#: unlocks it. This is a LAUNCH-TIME instruction for the human, never an
#: in-session route for the agent: nothing here is callable, redeemable, or
#: echoable, which is what keeps the teaching from becoming a bypass.
#:
#: The in-conversation wording is CONFIRMED by field observation (the
#: author watched the tool list grow 40 -> 69 live in the same chat):
#: Claude Desktop restarts the server when its settings change and the
#: client refreshes the tool list in place, so the change applies to the
#: current conversation. The restart is still real, hence the open-pages
#: nuance: a new server process owns a new browser.
UNLOCK_TEACHING = (
    "To allow acting (a settings choice a human makes, not something any "
    "tool call can do): in Claude Desktop, tick 'Allow this server to "
    "click and type' in the server's settings; from a shell, restart the "
    "server with KS4WEB_ALLOW_ACTING=true or without the --read-only "
    "flag. The settings change applies in this conversation: the server "
    "restarts and the tool list refreshes in place. Note that the restart "
    "closes the browser, so any open pages will reload."
)

#: `browse` is the default when the flag is bare: navigation, back and
#: forward, scroll, and every read tool. `strict` is the same tool set with
#: navigation limited to the origin allowlist, which is enforced at call
#: time and refuses with READ_ONLY_MODE.
GRADES: tuple[str, ...] = ("browse", "strict")

#: Tools that MUTATE and are therefore absent under every read-only grade.
#: Membership is declared here, in the policy layer, and never inferred from
#: a tool's name or its docstring. A new mutating tool that forgets to
#: declare itself is caught by `test_readonly.py`, which asserts that every
#: registered tool is classified explicitly.
MUTATING: frozenset[str] = frozenset({
    # lite core
    "click", "type_text", "fill_form", "press_keys",
    # packs (planned; listed now so Phase 5 inherits the classification
    # instead of rediscovering it one tool at a time)
    "set_routing", "evaluate_script",
    "manage_cookies", "manage_storage", "load_auth_state", "save_auth_state",
    "download", "upload_file",
    "save_workflow", "run_workflow",
    "emulate",
})

#: Tools that read or move without mutating page state. `navigate` and
#: `scroll` are here deliberately and the design says why: navigation is
#: genuinely ambiguous, so it is permitted under `browse` and constrained
#: under `strict` rather than removed outright.
NON_MUTATING: frozenset[str] = frozenset({
    # lite core
    "get_page_view", "find_elements", "get_text", "navigate", "scroll",
    "wait_for", "manage_tabs", "manage_session", "get_audit",
    "get_workflows",
    # packs (planned)
    "get_table", "get_list", "get_links", "get_metadata", "extract_fields",
    "export_data", "take_screenshot", "export_pdf", "save_page",
    "list_requests", "get_request", "export_har",
    "list_console", "get_page_errors", "list_workflows",
})

#: Tools that are GENUINELY read-only for the MCP readOnlyHint annotation:
#: they modify nothing at all, not the page, not the browser, not the
#: filesystem, not the web. This is deliberately STRICTER than NON_MUTATING:
#: `navigate` issues requests and rewrites browser state, `scroll` moves the
#: viewport, `manage_session`/`manage_tabs` create and destroy processes and
#: pages, and the export/save/screenshot tools write files, so none of them
#: may carry the hint however read-shaped they feel. An honest hint is what
#: buys the client-side permission lenience and the safe-concurrency
#: treatment; an optimistic one would be a false safety claim in metadata.
GENUINELY_READ_ONLY: frozenset[str] = frozenset({
    # lite core
    "get_page_view", "find_elements", "get_text", "get_audit",
    "get_workflows", "wait_for",
    # packs
    "get_table", "get_list", "get_links", "get_metadata", "extract_fields",
    "list_requests", "get_request", "list_console", "get_page_errors",
    "list_workflows",
})


def read_only_hint(tool_name: str) -> bool:
    """The MCP readOnlyHint for one tool: true only for the genuinely
    read-only set, never inferred from the mutating classification."""
    return tool_name in GENUINELY_READ_ONLY


_grade: str | None = None
_source: str = "default"


def parse_grade(value: str | bool | None) -> str | None:
    """Resolve a --read-only flag or KS4WEB_READ_ONLY value to a grade.

    A bare flag means `browse`. An EMPTY value FAILS CLOSED to `browse`
    (the Phase 7 fix: an empty env used to unlock, which is a fail-open
    defect in a safety setting). An unrecognized value is an ERROR, never a
    shrug: silently downgrading a safety mode because of a typo is the exact
    inversion of chrome-devtools-mcp #2530 that DESIGN 8.3 names."""
    if value is None or value is False:
        return None
    if value is True:
        return "browse"
    text = str(value).strip().lower()
    if not text:
        return "browse"                       # empty NEVER unlocks
    if text in ("0", "false", "off", "no"):
        return None
    if text in ("1", "true", "on", "yes"):
        return "browse"
    if text in GRADES:
        return text
    raise BadParams(
        f"unknown read-only grade {value!r}: the grades are "
        f"{list(GRADES)}. A bare --read-only flag means 'browse'. "
        f"Refusing to start rather than guessing, because guessing here "
        f"would silently weaken a safety mode."
    )


def parse_allow(value: str) -> str | None:
    """Resolve a KS4WEB_ALLOW_ACTING value to a grade, POSITIVE polarity:
    the value reads the way the Desktop checkbox does. Claude Desktop
    writes the literal strings "true" and "false" for a user_config
    boolean, and both are honored with the meaning the checkbox shows the
    human. An EMPTY value fails CLOSED to browse; garbage refuses to
    start."""
    text = str(value).strip().lower()
    if not text:
        return "browse"                       # empty NEVER unlocks
    if text in ("1", "true", "on", "yes", "act", "acting", "allow"):
        return None                           # acting allowed
    if text in ("0", "false", "off", "no"):
        return "browse"
    if text in GRADES:
        return text
    raise BadParams(
        f"unknown {ENV_ALLOW} value {value!r}: use 'true' to allow "
        f"acting, 'false' for read-only browsing, or a grade name from "
        f"{list(GRADES)}. Refusing to start rather than guessing, because "
        f"guessing here would silently weaken a safety mode."
    )


def apply(value: str | bool | None = None) -> str | None:
    """Resolve and record the grade ONCE, before registration. Returns the
    grade in force, or None when the server is not read-only.

    STARTUP ONLY. The only sanctioned caller is `server.configure`; the
    read-only invariant test scans the tree for any other call site, because
    a second caller is a runtime toggle wearing a disguise. Precedence:
    explicit value (CLI) beats KS4WEB_ALLOW_ACTING beats the deprecated
    KS4WEB_READ_ONLY beats DEFAULT_GRADE, and an explicit unlocking value
    beats the default in the unlocking direction too. An EMPTY env value
    fails closed to browse under either name."""
    global _grade, _source
    if value is not None:
        _grade = parse_grade(value)
        _source = "cli"
        return _grade
    allow = os.environ.get(ENV_ALLOW)
    if allow is not None:
        _grade = parse_allow(allow)
        _source = ENV_ALLOW
        return _grade
    legacy = os.environ.get(ENV_LEGACY)
    if legacy is not None:
        _grade = parse_grade(legacy)
        _source = f"{ENV_LEGACY} (deprecated; use {ENV_ALLOW})"
        return _grade
    _grade = DEFAULT_GRADE
    _source = "default"
    return _grade


def grade() -> str | None:
    return _grade


def source() -> str:
    """What decided the grade in force: 'cli', an env var name, or
    'default'. Surfaced at startup and in describe() so a surprising mode
    names its own cause."""
    return _source


def active() -> bool:
    return _grade is not None


def is_mutating(tool_name: str) -> bool:
    """Classify a tool. Unknown names raise rather than defaulting, because
    a default in either direction is wrong: defaulting to mutating hides a
    read tool, and defaulting to non-mutating registers a write tool in
    read-only mode, which would make the headline claim false."""
    if tool_name in MUTATING:
        return True
    if tool_name in NON_MUTATING:
        return False
    raise BadParams(
        f"tool {tool_name!r} is not classified in policy/readonly.py. "
        f"Every tool must be declared MUTATING or NON_MUTATING before it "
        f"can be registered, because read-only mode is enforced by absence "
        f"and an unclassified tool would be registered by accident."
    )


def should_register(tool_name: str) -> bool:
    """The read-only half of the registration gate."""
    if not active():
        return True
    return not is_mutating(tool_name)


def describe() -> dict:
    """What the mode permits, for manage_session(status) and for the
    refusal message. States the limit alongside the permission, per the
    safety-copy grammar."""
    if not active():
        return {"read_only": False, "decided_by": _source}
    return {
        "read_only": True,
        "grade": _grade,
        "decided_by": _source,
        "permits": (
            "reads, navigation, and scrolling"
            if _grade == "browse"
            else "reads and scrolling, with navigation limited to the "
                 "origin allowlist"
        ),
        "absent_tools": sorted(MUTATING),
        "note": (
            "No tool in this mode can click, type, submit, upload, "
            "download, evaluate script, or write storage. Navigation "
            "remains an outbound channel, so this does not mean nothing "
            "can change on a server you visit."
        ),
        "unlock": UNLOCK_TEACHING,
    }
