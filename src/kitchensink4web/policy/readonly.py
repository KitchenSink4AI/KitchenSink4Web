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
"""

from __future__ import annotations

import os

from ..errors import BadParams

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

_grade: str | None = None


def parse_grade(value: str | bool | None) -> str | None:
    """Resolve a --read-only flag or KS4WEB_READ_ONLY value to a grade.

    A bare flag means `browse`. An unrecognized value is an ERROR, never a
    shrug: silently downgrading a safety mode because of a typo is the exact
    inversion of chrome-devtools-mcp #2530 that DESIGN 8.3 names."""
    if value is None or value is False:
        return None
    if value is True:
        return "browse"
    text = str(value).strip().lower()
    if not text or text in ("0", "false", "off", "no"):
        return None
    if text in ("1", "true", "on", "yes", ""):
        return "browse"
    if text in GRADES:
        return text
    raise BadParams(
        f"unknown read-only grade {value!r}: the grades are "
        f"{list(GRADES)}. A bare --read-only flag means 'browse'. "
        f"Refusing to start rather than guessing, because guessing here "
        f"would silently weaken a safety mode."
    )


def apply(value: str | bool | None = None) -> str | None:
    """Resolve and record the grade ONCE, before registration. Returns the
    grade in force, or None when the server is not read-only."""
    global _grade
    if value is None:
        value = os.environ.get("KS4WEB_READ_ONLY")
    _grade = parse_grade(value)
    return _grade


def grade() -> str | None:
    return _grade


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
        return {"read_only": False}
    return {
        "read_only": True,
        "grade": _grade,
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
    }
