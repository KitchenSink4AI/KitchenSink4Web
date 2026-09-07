"""Exception types for KS4Web. Every one maps to a code in the closed
vocabulary (DESIGN 8.3) through envelope.CODE_MAP.

Ported in shape from word-mcp `core/errors.py`; the taxonomy itself is new,
because the browser has no file to corrupt and a whole class of failures the
document family never sees (bot walls, stale anchors on a re-rendered SPA,
lane gaps, TOCTOU target swaps).

This module lives at the package top level rather than under policy/,
engine/, or ops/, so all three can raise from it without any of them
importing each other. The import-direction test depends on that placement.

Every message is user-facing and every message names a recovery. The house
rule that produced this file, in four words: NEVER DEGRADE SILENTLY.
"""

from __future__ import annotations


class WebMcpError(Exception):
    """Base class; message text is user-facing and names a recovery."""

    #: Tools that would serve this request but are not in the running pack
    #: set. Declared at the raise site, never scraped from the message
    #: (pptx finding M8: a message echoing user input that happens to match
    #: a tool name must not trigger the hint).
    hint_tools: tuple[str, ...] = ()

    #: A raise-site hint that REPLACES the per-code one. None means the
    #: code's HINTS entry stands, which is the case for almost every refusal
    #: in the tree. Set it where the code's generic hint would contradict the
    #: message: hostile H-02 found the crashed-renderer message saying "open
    #: a NEW tab, this handle will not recover" with CONFLICT's "re-read to
    #: re-establish a baseline" printed underneath it.
    hint: str | None = None


# --------------------------------------------------------- inherited family


class AmbiguousLocation(WebMcpError):
    """More than one element matched the location object. No tool ever acts
    on first match; the refusal carries every candidate."""


class TargetNotFound(WebMcpError):
    """The location object matched nothing, or a ref was never minted in
    this session."""


class RangeOutOfBounds(WebMcpError):
    """A row range, a start_index, or a screen offset exceeds what exists."""


class UnsupportedContent(WebMcpError):
    """Content that is genuinely unreachable rather than merely missing: a
    closed shadow root, a canvas region with no text projection."""


class ValidationFailed(WebMcpError):
    """A pre-flight check refused before anything was touched."""


class Conflict(WebMcpError):
    """Two callers or two handles disagree about state."""


class BadParams(WebMcpError):
    """Malformed arguments: two selectors at once, zero selectors, a ref
    belonging to another page handle, an unknown enum value."""


# ------------------------------------------------------- browser additions


class StaleAnchor(WebMcpError):
    """A ref detached, the page navigated, or the rebind ladder found zero
    matches. The message names what the ref used to be, what changed, and
    the read that mints a fresh one (DESIGN 3.5)."""


class TargetChanged(WebMcpError):
    """TOCTOU re-validation failed between a gate's ASK and its EXECUTE. The
    message names the fingerprint fields that differ. Rebinding never
    launders a stale confirmation (DESIGN 5.4)."""


class NavigationBlocked(WebMcpError):
    """The origin policy denied a navigation. Names the origin, the policy,
    and the flag that would allow it."""


class BlockedBySite(WebMcpError):
    """A bot wall, CAPTCHA, 403 challenge, or rate limit. Names the wall
    type, any Retry-After, and the handoff route. This refusal exists so an
    agent stops burning turns against a wall it cannot pass (DESIGN 5.8)."""


class PageUnreachable(WebMcpError):
    """The request never reached a server: no network, DNS did not resolve,
    the connection was refused or reset, TLS failed.

    Separate from NAVIGATION_BLOCKED (this server's own policy said no) and
    from BLOCKED_BY_SITE (a server answered, hostilely). The field test
    2026-09-05 is why it exists: navigating with the network down came back
    as BAD_PARAMS, which tells an agent it typed the URL wrong and sends it
    off rewriting a URL that was correct."""


class AuthRequired(WebMcpError):
    """A login wall or an expired session. Names which, and the handoff or
    load_auth_state route."""


class CredentialRefused(WebMcpError):
    """A secret-field read or write outside a sanctioned route. Names the
    two sanctioned routes: the server-side secrets file, or the human typing
    it in the headed window (DESIGN 5.3)."""


class BudgetExhausted(WebMcpError):
    """A per-session budget tripped. Prints every counter and names the
    gated reset route, because a budget the model can reset by calling a
    tool is not a budget (DESIGN 5.5)."""


class LoopDetected(WebMcpError):
    """The rolling window over (tool, target fingerprint, argument hash)
    found repetition or a cycle. Prints the observed cycle."""


class ConfirmationRequired(WebMcpError):
    """A gated action class was requested. Carries the MRTR or elicitation
    payload. Fails closed where the client advertises neither."""


class ReadOnlyMode(WebMcpError):
    """A borderline operation was attempted under read-only. Names the grade
    in force and what it permits.

    Note the narrow scope: outright mutating tools are NOT REGISTERED under
    read-only (DESIGN 5.2), so they cannot raise this. This fires only where
    a permitted tool meets a limit of its grade, such as navigation outside
    the origin allowlist under `strict`."""


class LaneUnsupported(WebMcpError):
    """The operation is unavailable on the current engine lane. Names the
    lane, the specific gap, and which lane supports it. This is the
    honest-refusal instrument for the whole BiDi hole list (DESIGN 4.5)."""


class ModalBlocked(WebMcpError):
    """Something modal is in the way. Names it rather than timing out with an
    unrelated error.

    TWO conditions share this code and the hint serves both. A NATIVE dialog
    (alert, confirm, prompt, beforeunload) stops the page's script, and
    `handle_dialog` answers it; with nothing armed the driver dismisses it as
    it opens, which a confirm() reads as Cancel. A PAGE-DRAWN modal is
    ordinary DOM and no dialog call reaches it: its own close or cancel
    control is the route, because a click behind a modal is not the click that
    was asked for.

    The carried flag is DISCHARGED: `upload_file` used to raise this for an
    element that is not a file input, which is not a modal of either kind, and
    it now refuses with VALIDATION_FAILED. That mattered more once the hint
    started naming handle_dialog, since a hint about answering dialogs is
    actively misleading attached to a wrong-element refusal."""


class Timeout(WebMcpError):
    """A wait expired. Names what was being waited for and what was observed
    instead."""


class SessionDead(WebMcpError):
    """The browser process, or the driver connection to it, is gone. Nothing
    on this session can work again and no re-read recovers it.

    Separate from Conflict (a crashed RENDERER, where the browser survives
    and a fresh tab is the route) because the recovery differs: a dead
    browser needs manage_session close + open, and the fresh-tab advice the
    crash refusal gives fails when the whole browser is gone.

    Union wave 2026-09-07: chaos C-01/C-02/C-04, endurance F7, and the
    author's own field report (a Cloudflare challenge killing the Firefox
    process, after which every call answered BAD_PARAMS) are one condition
    with one name."""


class NavigationFailed(WebMcpError):
    """A navigation reached servers and did not produce a document, for a
    reason the SITE owns: a redirect loop, a redirect to a scheme the
    browser refuses, an aborted main-frame load.

    Separate from PageUnreachable (nothing answered at all) and from
    BlockedBySite (something answered, hostilely, with a wall). Before this
    code these fell through the transport table into BAD_PARAMS, which
    blamed the caller for a loop the site built."""


class FileWriteFailed(WebMcpError):
    """A file the caller asked the server to write could not be written: the
    directory refuses, the name is a device, the path is too long, the file
    is held open elsewhere.

    Exists so an `[Errno 13] Permission denied` stops arriving as
    BAD_PARAMS with a hint about location objects."""


class DriverFailure(WebMcpError):
    """The browser driver refused or failed for a reason none of the typed
    codes above covers.

    The terminal backstop for driver-shaped exceptions. Its whole purpose is
    that it is NOT BAD_PARAMS: an unrecognized transport or protocol error
    is infrastructure, and telling a caller its arguments were malformed
    sends it to rewrite arguments that were correct."""


# ----------------------------------------------------------- scaffold only


class NotImplementedYet(WebMcpError):
    """Phase 0 only: a registered tool whose engine does not exist.

    This maps to the SCAFFOLD code NOT_IMPLEMENTED, which is deliberately
    kept OUT of the shipped closed vocabulary and tracked separately so it
    cannot quietly become a permanent member of it. A test asserts the two
    sets are disjoint, and the Phase 9 gate asserts the scaffold set is
    empty."""
