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
import os as _os
import re as _re
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
    # Union wave 2026-09-07. Four codes that exist because BAD_PARAMS was
    # the terminal fallback for four things that are not argument problems:
    # a dead browser, a site-authored navigation failure, an unwritable
    # output path, and an unrecognized driver fault. Every one of them sent
    # a caller to fix arguments that were correct.
    "SESSION_DEAD", "NAVIGATION_FAILED", "FILE_WRITE_FAILED",
    "DRIVER_FAILURE",
    # Fix wave 2026-09-08. The fifth thing BAD_PARAMS was standing in for,
    # and the one the union wave could not see because it needed a bug to
    # show it: a fault inside KS4Web itself. A framed page tripped a merge
    # over a counter of the wrong type, and the caller was told its
    # arguments were malformed and handed the interpreter's own sentence.
    # An internal fault is not the caller's to fix and there is nothing in
    # the arguments to change, so it gets its own code and says so.
    "INTERNAL_ERROR",
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
    (_err.SessionDead, "SESSION_DEAD"),
    (_err.NavigationFailed, "NAVIGATION_FAILED"),
    (_err.FileWriteFailed, "FILE_WRITE_FAILED"),
    (_err.DriverFailure, "DRIVER_FAILURE"),
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
    # Every other OSError is a filesystem refusal, not an argument fault.
    # Ordered AFTER its two subclasses above so those keep their codes.
    (OSError, "FILE_WRITE_FAILED"),
    (ValueError, "BAD_PARAMS"),
    (TypeError, "BAD_PARAMS"),
    # An AttributeError cannot be an argument fault at this boundary.
    # Arguments arrive as JSON and are validated before a tool body runs, so
    # every AttributeError that gets this far was raised by KS4Web's own code
    # against KS4Web's own object. `ValueError` and `TypeError` stay on
    # BAD_PARAMS because those two really can come from a caller's value.
    (AttributeError, "INTERNAL_ERROR"),
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
    # One code, two conditions, and the hint has to serve both honestly. A
    # NATIVE dialog stops the page's script and handle_dialog answers it; a
    # PAGE-DRAWN modal is ordinary DOM and its own control closes it. The
    # previous hint described only the first and told the caller the build
    # could not answer it, which stopped being true when handle_dialog landed.
    "MODAL_BLOCKED": (
        "something modal is in the way and the message says which. For a "
        "NATIVE dialog (alert, confirm, prompt, beforeunload): with nothing "
        "armed the driver dismisses it as it opens, which a confirm() reads "
        "as Cancel, so arm the answer BEFORE the click that raises it with "
        "handle_dialog(page=..., action='arm_accept' or 'arm_dismiss'), or "
        "action='hold' to keep the next one open and then answer it with "
        "action='accept' or 'dismiss'. Answering OK requires a human "
        "confirmation wherever OK would commit something. For a PAGE-DRAWN "
        "modal there is no dialog to answer: read the page and act on the "
        "modal's own close or cancel control, since a click behind it is not "
        "the click you asked for"
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
    # FLAGGED (union wave): placeholder wording, mechanically composed from
    # existing sentences in this file. The four new codes need the author's
    # eyes on their hints before ship.
    "SESSION_DEAD": (
        "the browser this session owns is gone, so no call on it can work "
        "and no re-read recovers it. Close the session with "
        "manage_session(action='close') and open a new one; refs, read "
        "tokens, and page handles from the old session do not carry over"
    ),
    "NAVIGATION_FAILED": (
        "the navigation reached the network and produced no document, for a "
        "reason the site owns rather than the arguments. The message names "
        "what the browser reported. Rewriting the URL does not help; a "
        "different URL, or a human in a headed window, might"
    ),
    "FILE_WRITE_FAILED": (
        "the file could not be written and nothing was saved. The message "
        "names the resolved path and what the filesystem reported. Choose a "
        "writable directory and a plain file name, or omit path to use the "
        "server's own downloads directory"
    ),
    "DRIVER_FAILURE": (
        "the browser driver failed for a reason this build does not have a "
        "specific code for, and the message carries what the driver said. "
        "The arguments are not the thing to fix. Check the session with "
        "manage_session(action='status') before retrying"
    ),
    # FLAGGED (fix wave 2026-09-08): placeholder wording, mechanically
    # composed from existing sentences in this file. Needs the author's eyes
    # before ship, like the union wave's four above it.
    "INTERNAL_ERROR": (
        "KS4Web itself failed, not the browser and not the arguments, so "
        "there is nothing in the call to fix and rewriting it does not "
        "help. The message carries what the interpreter reported. Retrying "
        "the same call reaches the same code; a different tool, or the same "
        "read with a narrower root, may not"
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


#: THE BROWSER IS GONE. Every one of these means the process or the driver
#: connection died, so the recovery is close-and-reopen and nothing else.
#: Union wave 2026-09-07: chaos C-01/C-04, endurance F7, and the author's
#: field report all landed on BAD_PARAMS or on a bare CONFLICT with no route.
DEAD_MARKERS: tuple[str, ...] = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "browser has disconnected",
    "connection closed while reading from the driver",
    "connection closed",
    "not attached to an active page",
    "target closed",
    "has been closed",
)

#: A RENDERER died and the browser survived. Distinguished from the above
#: because the recovery really is a fresh tab (M1), and conflating the two is
#: what made the crash refusal name a recovery that fails (chaos C-04).
CRASH_MARKERS: tuple[str, ...] = ("page crashed", "target crashed")

#: The DOCUMENT went away underneath the call, which a re-read does fix.
CONFLICT_MARKERS: tuple[str, ...] = (
    "execution context was destroyed",
    "frame was detached",
)

#: A navigation that reached the network and produced no document, for a
#: reason the SITE owns. Hostile round H-01, chaos C-01's redirect rows.
NAV_FAIL_MARKERS: tuple[tuple[str, str], ...] = (
    ("err_too_many_redirects", "the redirect chain never terminated"),
    ("ns_error_redirect_loop", "the redirect chain never terminated"),
    ("err_unsafe_redirect", "a redirect pointed at a scheme the browser "
                            "refuses to follow"),
    ("err_invalid_redirect", "a redirect was malformed"),
    ("err_blocked_by_client", "the browser itself blocked the request"),
    ("err_blocked_by_response", "a response header told the browser to "
                                "block the load"),
    ("err_unsafe_port", "the port is one the browser refuses to open"),
    ("err_invalid_url", "the browser refused the URL as unnavigable"),
    ("err_aborted", "the main-frame load was aborted before it produced a "
                    "document"),
    ("ns_binding_aborted", "the main-frame load was aborted before it "
                           "produced a document"),
)

#: Driver-shaped: a Playwright method name prefix, its call log, or a
#: browser-level error scheme. Nothing matching these may be answered
#: BAD_PARAMS, because none of them is an argument fault.
_DRIVER_SHAPE = _re.compile(
    r"(^[A-Z][A-Za-z]*\.[a-z_][A-Za-z_]*: )"
    r"|(\bcall log:)|(\bnet::)|(\bns_error_)|(\bprotocol error\b)"
    r"|(\bbrowsertype\.)|(\bbrowsercontext\.)|(\bplaywright\b)",
    _re.I | _re.M)


def is_driver_shaped(exc: BaseException) -> bool:
    """True when the exception text is the browser driver talking.

    Used by `classify` so an unrecognized driver string lands on
    DRIVER_FAILURE rather than on the terminal BAD_PARAMS, and by `refusal`
    so the raw text never ships unscrubbed."""
    if isinstance(exc, _err.WebMcpError):
        return False
    if "playwright" in type(exc).__module__.lower():
        return True
    return bool(_DRIVER_SHAPE.search(str(exc)))


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
    # A renderer crash (gauntlet 2026-09-06, M1) outranks the death markers
    # below, because a driver string can carry both and the crash recovery
    # (a fresh tab) is the narrower, correct one when the browser survives.
    if any(m in text for m in CRASH_MARKERS):
        return "CONFLICT"
    if any(m in text for m in DEAD_MARKERS):
        return "SESSION_DEAD"
    if "timeout" in name.lower():
        return "TIMEOUT"
    if any(m in text for m in CONFLICT_MARKERS):
        return "CONFLICT"
    if any(m in text for m, _ in NAV_FAIL_MARKERS):
        return "NAVIGATION_FAILED"
    if is_driver_shaped(exc):
        # THE STRUCTURAL FIX (chaos C-01). The transport table is an
        # allowlist, and everything it does not recognize used to fall
        # through to argument-blaming. An unrecognized DRIVER fault is
        # infrastructure by construction, so it gets an infrastructure code.
        return "DRIVER_FAILURE"
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


#: How much driver text may ride out inside a refusal. Chaos C-12 shipped a
#: 2,368-character message: the driver string, then the whole
#: `chrome-headless-shell.exe` launch line with every flag and the local
#: ms-playwright install path, then GPU crash lines with foreign PIDs. That
#: is a token bomb and a local-path disclosure inside an error.
DRIVER_DETAIL_CHARS = 200

#: The hint a crashed-renderer refusal carries INSTEAD of CONFLICT's generic
#: one. FLAGGED: placeholder, lifted from the crash message's own clauses.
CRASHED_HINT = (
    "this page handle is dead and re-reading it will not recover it; open a "
    "new tab with manage_tabs(action='open', url=...) and continue there"
)

#: Where a driver dump stops being the error and starts being the driver's
#: diary. Everything from the first of these onward is dropped.
_DUMP_HEADERS = ("call log:", "browser logs:", "=========================",
                 "note: use devtools protocol", "pid=", "[pid=")

#: Absolute paths that must not ride out. Built once from the environment
#: rather than matched by pattern, so the substitution is exact.
def _local_roots() -> tuple[tuple[str, str], ...]:
    roots: list[tuple[str, str]] = []
    for var, label in (("LOCALAPPDATA", "<localappdata>"),
                       ("APPDATA", "<appdata>"),
                       ("USERPROFILE", "<home>"),
                       ("HOME", "<home>"),
                       ("TEMP", "<temp>"), ("TMP", "<temp>")):
        value = (_os.environ.get(var) or "").strip().rstrip("\\/")
        if len(value) > 3:
            roots.append((value, label))
    # Longest first so <localappdata> wins over <home> for a nested path.
    roots.sort(key=lambda r: len(r[0]), reverse=True)
    return tuple(roots)


def scrub_driver_text(text: str, limit: int = DRIVER_DETAIL_CHARS) -> str:
    """Bound and de-identify a driver-supplied string before it ships.

    Three jobs, in order: cut the dump tail, replace local filesystem roots
    with a label, and clip. `_argument_message` already goes to real trouble
    to keep pydantic internals out of a refusal; this is the same discipline
    for the other side of the wire (chaos C-12, fuzzer class 1c)."""
    body = str(text or "")
    lowered = body.lower()
    cut = len(body)
    for header in _DUMP_HEADERS:
        found = lowered.find(header)
        if found != -1:
            cut = min(cut, found)
    body = body[:cut]
    for root, label in _local_roots():
        body = body.replace(root, label)
        body = body.replace(root.replace("\\", "/"), label)
    body = " ".join(body.split())
    if len(body) > limit:
        body = body[:limit].rstrip() + "..."
    return body


def _driver_cause(text: str) -> str | None:
    """The plain-English cause for a NAVIGATION_FAILED marker, if one of the
    known markers is present."""
    lowered = str(text).lower()
    for marker, cause in NAV_FAIL_MARKERS:
        if marker in lowered:
            return cause
    return None


def _sanitize(value: Any) -> Any:
    """Replace unpaired surrogates anywhere in a payload with U+FFFD.

    Cheap on the common path: a string with no surrogate encodes and is
    returned unchanged."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return value
        except UnicodeEncodeError:
            return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {_sanitize(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def refusal(exc: BaseException) -> dict:
    """Build the {ok: false, error: {code, message, hint}} payload."""
    code = getattr(exc, "code", None) or classify(exc)
    message = str(exc)
    hint_override: str | None = None
    if not isinstance(exc, _err.WebMcpError) \
            and ("page crashed" in message.lower()
                 or "target crashed" in message.lower()):
        # The honest crash refusal (M1), built at the choke point so every
        # path that observes a renderer crash says the same true thing
        # instead of leaking the raw driver string. The handle is marked
        # dead by the crash event, so reuse refuses in locate() with the
        # same recovery.
        detail = scrub_driver_text(message.splitlines()[0], 160)
        message = (
            f"the page's renderer process crashed (driver detail: "
            f"{detail}). The arguments were fine; the page itself died, "
            f"which extremely deep or pathological nesting can cause, in "
            f"the DOM or in shadow roots. "
            f"This page handle is dead and will not recover: open a NEW "
            f"tab with manage_tabs(action='open', url=...) and continue "
            f"there. Refs minted on the crashed page are gone.")
        # H-02: CONFLICT's generic "re-read to re-establish a baseline" is
        # the one action guaranteed to fail here.
        hint_override = CRASHED_HINT
    elif not isinstance(exc, _err.WebMcpError):
        # NO RAW DRIVER OR STDLIB STRING IS EVER THE WHOLE MESSAGE (union
        # wave, fuzzer class 1 + chaos C-05/C-11/C-12 + hostile H-01/H-02).
        # `envelope`'s own first stated rule is that no exception string
        # reaches a caller; before this branch `message = str(exc)` made
        # that rule false for every backstop code in CODE_MAP.
        # FLAGGED: placeholder wording, mechanically composed.
        detail = scrub_driver_text(message)
        if code == "SESSION_DEAD":
            message = (
                f"the browser for this session is gone (driver detail: "
                f"{detail}). No call on this session can work and no "
                f"re-read recovers it. Close it with "
                f"manage_session(action='close') and open a new one.")
        elif code == "NAVIGATION_FAILED":
            cause = _driver_cause(message)
            message = (
                f"the navigation produced no document: "
                f"{cause or 'the browser refused the load'} (driver "
                f"detail: {detail}). The site owns this outcome, not the "
                f"arguments, so rewriting the URL does not help.")
        elif code == "FILE_WRITE_FAILED":
            message = (
                f"the file could not be written and nothing was saved "
                f"(filesystem detail: {detail}).")
        elif code == "DRIVER_FAILURE":
            message = (
                f"the browser driver failed and this build has no more "
                f"specific code for it (driver detail: {detail}). The "
                f"arguments are not the thing to fix.")
        elif code == "INTERNAL_ERROR":
            message = (
                f"KS4Web failed inside its own code and the call did not "
                f"complete (internal detail: {detail}). The arguments were "
                f"not the problem and there is nothing in them to fix.")
        elif code == "BAD_PARAMS" and not (
                isinstance(exc, LookupError) and len(message) < 40):
            # THE TERMINAL FALLBACK, and the only backstop code that blames
            # the caller. A bare builtin reaching it was raised somewhere
            # this module cannot see, so the honest sentence names both
            # possibilities instead of asserting the arguments are wrong,
            # and the interpreter's own text rides as a bounded detail
            # rather than as the whole message. Before this branch the
            # `detail != message` test below let an unscrubbed stdlib
            # sentence ship verbatim whenever the scrubber had nothing to
            # change, which is most of the time.
            message = (
                f"the call failed and this build could not attribute the "
                f"fault (detail: {detail}). Check the arguments named in "
                f"the detail first; if they are right, the fault is "
                f"KS4Web's and the call cannot be made to work by "
                f"rewriting it.")
        elif detail != message:
            # Any other backstop code (CONFLICT, TIMEOUT, NOT_FOUND...):
            # keep the code's own meaning, ship the bounded text.
            message = detail
    if isinstance(exc, LookupError) and len(message) < 40:
        message = (
            f"internal lookup failed on {message}: a nested parameter "
            "probably has the wrong shape (a list where a dict belongs, or "
            "the reverse)"
        )
    # A raise site that already named a recovery keeps it (hostile H-02: the
    # crashed-renderer message says "open a NEW tab" and the generic CONFLICT
    # hint under it said "re-read to re-establish a baseline").
    hint = (getattr(exc, "hint", None) or hint_override
            or HINTS.get(code, ""))
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
        # LONE SURROGATES CANNOT COLLAPSE THE ENVELOPE (fuzzer class 11).
        # A refusal echoes its arguments, so an unpaired surrogate in any
        # string argument made the refusal itself unserializable and the
        # caller got the framework's bare exception text instead of an
        # envelope. Latent in production (a conforming JSON-RPC transport
        # rejects the frame first, and page content is sanitized to U+FFFD)
        # and one defensive substitution at the serializer.
        payload = _sanitize(payload)
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
