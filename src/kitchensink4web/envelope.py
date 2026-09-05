"""The KS4Web response envelope: typed refusals with isError=true, a closed
browser code vocabulary, and the one place redaction can be enforced.

Ported in SHAPE from word-mcp `envelope.py` (itself carried from KS4PPT).
The machinery is the family's; the code map is entirely new, because the
browser vocabulary shares only eight codes with the document family and adds
thirteen of its own (DESIGN 8.3).

Three things this module is responsible for, all of them load-bearing:

1. **Refusals are structured and never raw.** No exception string ever
   reaches a caller. The payload is {ok: false, error: {code, message, hint}}
   with a closed code vocabulary, and RefusalResult sets isError=true on the
   wire (the production-test finding that refusals were riding out as
   isError=false successes).

2. **Every message names a recovery.** That is the family's honest-refusal
   discipline and it is the reason HINTS below is exhaustive rather than
   partial. Claude in Chrome's 20-match cap ("use a more specific query") is
   the model: the nudge is the important half.

3. **Redaction lives HERE, not in the tools.** DESIGN 5.3: the secrets hook
   applies to every outgoing payload and every file write, at the serializer,
   because per-tool discipline fails the moment someone adds a feature. The
   incumbent's own console-logging regression is the proof. Phase 0 wires the
   SEAM (`set_redactor`) and ships no redactor; Phase 3 installs the real one
   and the Phase 3 gate proves it against a deliberately leaky test tool.

Phase 0 note: the discoverability signpost names the LAUNCH FLAG rather than
an enable_tools call, because KS4Web does not ship runtime pack toggling
(DESIGN 7.2, a conformance decision). Family discoverability rule 2 adapts
rather than lapses (DESIGN 7.4).
"""

from __future__ import annotations

import json as _json
from typing import Any, Callable

from fastmcp.tools.tool import ToolResult as _FmcpToolResult

from . import errors as _err

# --------------------------------------------------------------- vocabulary

#: The SHIPPED closed vocabulary (DESIGN 8.3). Eight inherited from the
#: document family, thirteen browser additions. Nothing outside this set may
#: appear in a shipped refusal.
CLOSED_CODES: frozenset[str] = frozenset({
    # inherited
    "AMBIGUOUS_LOCATION", "NOT_FOUND", "RANGE_OUT_OF_BOUNDS",
    "STALE_ANCHOR", "UNSUPPORTED_CONTENT", "VALIDATION_FAILED",
    "CONFLICT", "BAD_PARAMS",
    # browser additions
    "TARGET_CHANGED", "NAVIGATION_BLOCKED", "BLOCKED_BY_SITE",
    "PAGE_UNREACHABLE",
    "AUTH_REQUIRED", "CREDENTIAL_REFUSED", "BUDGET_EXHAUSTED",
    "LOOP_DETECTED", "CONFIRMATION_REQUIRED", "READ_ONLY_MODE",
    "LANE_UNSUPPORTED", "MODAL_BLOCKED", "TIMEOUT",
})

#: Codes that exist only while the build is unfinished. Kept OUT of
#: CLOSED_CODES on purpose: a scaffold code that quietly joins the shipped
#: vocabulary is how a temporary thing becomes permanent. A test asserts the
#: two sets are disjoint, and the Phase 9 ship gate asserts this one is
#: empty.
SCAFFOLD_CODES: frozenset[str] = frozenset({"NOT_IMPLEMENTED"})

ALL_CODES: frozenset[str] = CLOSED_CODES | SCAFFOLD_CODES

# Order matters: specific classes before their WebMcpError base.
CODE_MAP: tuple[tuple[type[BaseException], str], ...] = (
    (_err.AmbiguousLocation, "AMBIGUOUS_LOCATION"),
    (_err.StaleAnchor, "STALE_ANCHOR"),
    (_err.TargetChanged, "TARGET_CHANGED"),
    (_err.RangeOutOfBounds, "RANGE_OUT_OF_BOUNDS"),
    (_err.TargetNotFound, "NOT_FOUND"),
    (_err.NavigationBlocked, "NAVIGATION_BLOCKED"),
    (_err.BlockedBySite, "BLOCKED_BY_SITE"),
    (_err.PageUnreachable, "PAGE_UNREACHABLE"),
    (_err.AuthRequired, "AUTH_REQUIRED"),
    (_err.CredentialRefused, "CREDENTIAL_REFUSED"),
    (_err.BudgetExhausted, "BUDGET_EXHAUSTED"),
    (_err.LoopDetected, "LOOP_DETECTED"),
    (_err.ConfirmationRequired, "CONFIRMATION_REQUIRED"),
    (_err.ReadOnlyMode, "READ_ONLY_MODE"),
    (_err.LaneUnsupported, "LANE_UNSUPPORTED"),
    (_err.ModalBlocked, "MODAL_BLOCKED"),
    (_err.Timeout, "TIMEOUT"),
    (_err.UnsupportedContent, "UNSUPPORTED_CONTENT"),
    (_err.ValidationFailed, "VALIDATION_FAILED"),
    (_err.Conflict, "CONFLICT"),
    (_err.NotImplementedYet, "NOT_IMPLEMENTED"),
    (_err.BadParams, "BAD_PARAMS"),
    (_err.WebMcpError, "BAD_PARAMS"),
    # Backstops. Ops-level guards refuse first with better messages; these
    # exist so a stray builtin never reaches a caller as a raw traceback,
    # which is the failure the family widened this map to catch.
    (TimeoutError, "TIMEOUT"),
    (FileExistsError, "CONFLICT"),
    (FileNotFoundError, "NOT_FOUND"),
    (NotImplementedError, "NOT_IMPLEMENTED"),
    (ValueError, "BAD_PARAMS"),
    (TypeError, "BAD_PARAMS"),
    (AttributeError, "BAD_PARAMS"),
    (RecursionError, "UNSUPPORTED_CONTENT"),
    (OverflowError, "BAD_PARAMS"),
    (KeyError, "BAD_PARAMS"),
    (IndexError, "BAD_PARAMS"),
)
CATCHABLE: tuple[type[BaseException], ...] = tuple(t for t, _ in CODE_MAP)

#: Every code names a recovery. This mapping is asserted TOTAL by a test:
#: a code without a hint is a refusal that dead-ends, which is the failure
#: mode the whole vocabulary exists to prevent.
HINTS: dict[str, str] = {
    "AMBIGUOUS_LOCATION": (
        "several elements matched; the message lists every candidate with "
        "an unambiguous address, so re-send with one of those"
    ),
    "NOT_FOUND": (
        "nothing matched. Refs are minted only by a read in this session: "
        "run get_page_view or find_elements and use a ref from that result"
    ),
    "RANGE_OUT_OF_BOUNDS": (
        "the range exceeds what exists; the message names the valid bounds"
    ),
    "STALE_ANCHOR": (
        "the element moved or the page changed since the ref was minted; "
        "re-run get_page_view (or get_page_view(since=...) for just the "
        "delta) and resend with a fresh ref"
    ),
    "TARGET_CHANGED": (
        "the target changed between the confirmation and the execution, so "
        "nothing was done; re-read, re-confirm, and retry"
    ),
    "NAVIGATION_BLOCKED": (
        "the origin policy denied this navigation; the message names the "
        "origin and the flag that would allow it"
    ),
    "BLOCKED_BY_SITE": (
        "the site is refusing automated access; do not retry in a loop. "
        "The message names the wall type, any Retry-After, and the handoff "
        "route that lets a human clear it"
    ),
    "PAGE_UNREACHABLE": (
        "the request never reached a server, so the URL is not the thing "
        "to fix. The message names what the network reported (no "
        "connection, DNS failure, refused connection). Check connectivity "
        "or the host name, and do not retry in a tight loop"
    ),
    "AUTH_REQUIRED": (
        "the page needs a signed-in session; use load_auth_state with a "
        "previously saved state file, or hand off to the human in a headed "
        "window. get_workflows(topic='auth') has the four-step recipe"
    ),
    "CREDENTIAL_REFUSED": (
        "secret fields are never read or written through the model. Hand "
        "off with manage_session(action='handoff') so the human types it "
        "in the headed window, then reuse the login across runs with "
        "save_auth_state / load_auth_state (storage pack)"
    ),
    "BUDGET_EXHAUSTED": (
        "a session budget tripped and every counter is printed above; the "
        "reset route is named and needs a human to answer it"
    ),
    "LOOP_DETECTED": (
        "the same call is repeating; the observed cycle is printed. Change "
        "approach rather than retrying"
    ),
    "CONFIRMATION_REQUIRED": (
        "this action class needs a human confirmation; answer the attached "
        "request and the call will re-validate its target before acting"
    ),
    "READ_ONLY_MODE": (
        "this server is running read-only; the message names the grade in "
        "force and what it permits. Restart without --read-only to act"
    ),
    "LANE_UNSUPPORTED": (
        "the current engine lane cannot do this; the message names the gap "
        "and which lane supports it. manage_session(action='capabilities') "
        "lists the full truth table"
    ),
    "MODAL_BLOCKED": (
        "a dialog or file chooser is pending and nothing else can proceed; "
        "the message names it and the tool that clears it"
    ),
    "TIMEOUT": (
        "the wait expired; the message names what was awaited and what was "
        "observed instead"
    ),
    "UNSUPPORTED_CONTENT": (
        "this content is genuinely unreachable rather than missing (a "
        "closed shadow root, a canvas region); the completeness block of "
        "the last read counts it"
    ),
    "VALIDATION_FAILED": (
        "a pre-flight check refused and nothing was touched; the message "
        "says what failed"
    ),
    "CONFLICT": (
        "two handles or two callers disagree about state; re-read to "
        "re-establish a baseline"
    ),
    "BAD_PARAMS": (
        "the arguments are malformed. A location object takes exactly one "
        "selector key, and a ref belongs to the page handle that minted it"
    ),
    "NOT_IMPLEMENTED": (
        "this tool is registered but its engine is not built yet (Phase 0 "
        "scaffold). No browser code exists in this build"
    ),
}

# --------------------------------------------------------- redaction seam

_redactor: Callable[[Any], Any] | None = None


def set_redactor(fn: Callable[[Any], Any] | None) -> None:
    """Install the secrets redactor. DESIGN 5.3 puts redaction at the
    serializer because it is the ONE place it can be enforced globally, and
    Phase 3's gate proves it there by driving a deliberately leaky test tool
    that tries to emit a cookie value.

    Phase 0 ships the seam and no redactor. `redact` is therefore identity
    today, and the test that proves the seam works installs its own."""
    global _redactor
    _redactor = fn


def redact(payload: Any) -> Any:
    """Every outgoing payload and every file write passes through here."""
    return _redactor(payload) if _redactor is not None else payload


# ------------------------------------------------------------- classifying


def classify(exc: BaseException) -> str:
    for etype, code in CODE_MAP:
        if isinstance(exc, etype):
            return code
    # The driver backstop (field test 2026-09-05: a mid-keystroke navigation
    # surfaced as a raw "Execution context was destroyed" string). Playwright
    # errors are not importable here without breaking the lazy-import rule,
    # so the classification is by name and message, which is exactly enough
    # to keep the closed vocabulary closed.
    name = type(exc).__name__
    text = str(exc).lower()
    if "timeout" in name.lower():
        return "TIMEOUT"
    if ("execution context was destroyed" in text
            or "target closed" in text
            or "has been closed" in text
            or "frame was detached" in text
            # A renderer crash (gauntlet 2026-09-06, M1): before this row it
            # fell through to BAD_PARAMS and inherited the location-selector
            # hint, which sent the caller to fix arguments that were fine.
            or "page crashed" in text):
        return "CONFLICT"
    return "BAD_PARAMS"


def pack_hint(exc: BaseException) -> str | None:
    """Discoverability rule 2, adapted for launch-time packs (DESIGN 7.4).

    There is no enable_tools call to name, so the refusal names the PACK,
    the LAUNCH FLAG, and the ENV VAR instead. The raise site declares the
    tools via `hint_tools`; the message text is never scanned."""
    from . import packs as _packs  # local: keeps envelope importable alone

    names = getattr(exc, "hint_tools", None)
    if not names:
        return None
    needed: dict[str, str] = {}
    for name in names:
        pack = _packs.pack_of(name)
        if pack in (None, "lite"):
            continue
        if not _packs.is_pack_loaded(pack):
            needed[name] = pack
    if not needed:
        return None
    pack_list = sorted(set(needed.values()))
    named = ", ".join(f"{n} (pack {p!r})" for n, p in sorted(needed.items()))
    flags = " ".join(f"--packs {p}" for p in pack_list)
    env = ",".join(pack_list)
    return (
        f"the tool(s) named here exist but are not loaded in this process: "
        f"{named}. Packs are chosen at LAUNCH, not at runtime, so restart "
        f"the server with {flags} (or set KS4WEB_MODE={env}) and retry. "
        f"get_workflows carries the full menu."
    )


def refusal(exc: BaseException) -> dict:
    """Build the {ok: false, error: {code, message, hint}} payload."""
    code = getattr(exc, "code", None) or classify(exc)
    message = str(exc)
    if not isinstance(exc, _err.WebMcpError) \
            and "page crashed" in message.lower():
        # The honest crash refusal (M1), built at the choke point so every
        # path that observes a renderer crash says the same true thing
        # instead of leaking the raw driver string. The handle is marked
        # dead by the crash event, so reuse refuses in locate() with the
        # same recovery.
        detail = message.splitlines()[0][:160]
        message = (
            f"the page's renderer process crashed (driver detail: "
            f"{detail}). The arguments were fine; the page itself died, "
            f"which extremely deep or pathological DOM nesting can cause. "
            f"This page handle is dead and will not recover: open a NEW "
            f"tab with manage_tabs(action='open', url=...) and continue "
            f"there. Refs minted on the crashed page are gone.")
    if isinstance(exc, LookupError) and len(message) < 40:
        message = (
            f"internal lookup failed on {message}: a nested parameter "
            "probably has the wrong shape (a list where a dict belongs, or "
            "the reverse)"
        )
    hint = HINTS.get(code, "")
    ph = pack_hint(exc)
    if ph:
        hint = f"{hint} {ph}".strip()
    error: dict[str, Any] = {"code": code, "message": message, "hint": hint}
    matches = getattr(exc, "matches", None)
    if matches:
        error["matches"] = matches
    detail = getattr(exc, "detail", None)
    if detail:
        error["detail"] = detail
    return redact({"ok": False, "error": error})


class RefusalResult(_FmcpToolResult):
    """A structured refusal that is BOTH indexable like the
    {ok: false, error: ...} dict (in-process callers and the test harness)
    AND a FastMCP ToolResult whose MCP serialization sets isError=true."""

    def __init__(self, payload: dict):
        text = _json.dumps(payload, indent=2, ensure_ascii=False)
        super().__init__(
            content=text, structured_content=payload, is_error=True
        )

    def __getitem__(self, key):
        return self.structured_content[key]

    def __contains__(self, key) -> bool:
        return key in self.structured_content

    def get(self, key, default=None):
        return self.structured_content.get(key, default)

    def keys(self):
        return self.structured_content.keys()


def refuse(exc: BaseException) -> RefusalResult:
    """One-call convenience for the tool wrapper."""
    return RefusalResult(refusal(exc))


def success(payload: dict) -> dict:
    """The success shape (DESIGN 8.1). Lane A is canonical: Lanes B and C
    ADD keys and never change shape, so there is one parsing path for every
    caller. Passes through the redaction seam like every other payload."""
    out: dict[str, Any] = {"ok": True}
    out.update(payload)
    return redact(out)
