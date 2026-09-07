"""Shared plumbing for the Phase 5 capability packs.

Small on purpose. Three things live here because more than one pack needs
them and duplicating any of them is how the packs drift apart:

1. **Locate-and-annotate.** Every pack tool resolves its page or session the
   same way the lite core does and annotates the audit record the same way,
   so a pack call reads identically in `get_audit` to a lite call.

2. **The scoped directories.** Downloads, exports, and oversized-payload
   spills all land in directories the sandbox governs (DESIGN: the download
   directory and the spill-to-file directory are two of the four places
   KS4Web touches a filesystem). Every write goes through
   `sandbox.check_path` first, and text writes pass the envelope's redaction
   seam so a file write can never carry what a payload could not.

3. **Image sniffing.** The media type of any returned or saved image is
   derived from the BYTES, never from the requested format. playwright-mcp
   #1211 is a PNG returned under an image/jpeg media type, and that one-line
   mismatch permanently poisons a session with an API 400. Deriving format,
   media type, and file extension from one sniff of the magic numbers makes
   the mismatch structurally impossible rather than merely tested-for.

Env vars this module adds (recorded for the Q11a docs-pass ruling):
KS4WEB_DOWNLOAD_DIR, KS4WEB_SPILL_DIR.
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

from .. import envelope
from ..engine.session import MANAGER
from ..errors import FileWriteFailed, UnsupportedContent, ValidationFailed
from ..policy import audit as _audit
from ..policy import credentials as _credentials
from ..policy import sandbox

ENV_DOWNLOAD_DIR = "KS4WEB_DOWNLOAD_DIR"
ENV_SPILL_DIR = "KS4WEB_SPILL_DIR"


# --------------------------------------------------- auth-state refusals

#: Anything past this is not a plausible seconds-since-epoch expiry (it is
#: the year 5138), so a value above it is milliseconds. Firefox writes
#: `moz_cookies.expiry` in milliseconds and Playwright asserts
#: `expires <= 253402300799`, rejecting the WHOLE add_cookies call over one
#: cookie (ship-route test, 2026-09-06).
_MS_EXPIRY_FLOOR = 1e11


def auth_file_refusal(checked: str, cookies: list, exc: Exception):
    """Name the state file, the offending cookie, and the units.

    The ship-route test caught the old behavior: a rejected add_cookies came
    back as generic BAD_PARAMS whose hint talked about location objects and
    refs, neither of which is anywhere near an auth-state load. A refusal
    that misdirects is worse than a bare one."""
    detail = str(exc).splitlines()[0][:200]
    offenders = [c.get("name") for c in cookies
                 if isinstance(c.get("expires"), (int, float))
                 and c["expires"] > _MS_EXPIRY_FLOOR]
    scale = ""
    if offenders:
        shown = ", ".join(str(n) for n in offenders[:4] if n)
        scale = (
            f" {len(offenders)} cookie(s) in the file carry an `expires` "
            f"value past the year 5138 ({shown}), which is what a "
            f"MILLISECOND timestamp looks like where seconds are expected. "
            f"Firefox stores cookie expiry in milliseconds and Playwright "
            f"rejects the whole batch over a single one, so divide those "
            f"values by 1000 (or use -1 for a session cookie) and load "
            f"again.")
    return ValidationFailed(
        f"the browser rejected the cookies in the state file {checked}, so "
        f"no authentication was loaded and nothing partial was left behind. "
        f"Driver detail: {detail}.{scale} A state file written by "
        f"save_auth_state loads as-is; a file built by hand or exported "
        f"from a browser profile has to match Playwright's storage_state "
        f"shape (name, value, domain, path, expires in SECONDS, httpOnly, "
        f"secure, sameSite).")


# ----------------------------------------------------------- cookie expiry

#: Inside this much of its expiry, a saved login is worth a word at load
#: time. A day is long enough that a state file saved last night still reads
#: as fine this morning, and short enough to catch the case the field log
#: asked about twice: a file that will die mid-run.
NEAR_EXPIRY_S = 24 * 3600


def human_span(seconds: float) -> str:
    seconds = abs(float(seconds))
    if seconds < 90:
        return f"{int(seconds)} second(s)"
    if seconds < 90 * 60:
        return f"{int(round(seconds / 60))} minute(s)"
    if seconds < 36 * 3600:
        return f"{int(round(seconds / 3600))} hour(s)"
    return f"{int(round(seconds / 86400))} day(s)"


def auth_expiry(cookies: list) -> dict | None:
    """The earliest expiry among the AUTH-RELEVANT cookies, or None.

    Auth-relevant is `credentials.cookie_is_credential`, the same classifier
    the vault uses, so a preference cookie's short life never masquerades as
    a login about to lapse. Session cookies (`expires` at or below zero) have
    no expiry to report and are counted instead. A millisecond value is read
    as milliseconds rather than as the year 55000, matching the units repair
    the load refusal already teaches."""
    earliest = None
    session_cookies = 0
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        if not _credentials.cookie_is_credential(cookie):
            continue
        raw = cookie.get("expires")
        if not isinstance(raw, (int, float)) or raw <= 0:
            session_cookies += 1
            continue
        when = float(raw) / 1000.0 if raw > _MS_EXPIRY_FLOOR else float(raw)
        if earliest is None or when < earliest["expires"]:
            earliest = {"name": cookie.get("name") or "(unnamed)",
                        "domain": cookie.get("domain") or "",
                        "expires": when}
    if earliest is None:
        return {"session_cookies": session_cookies} if session_cookies else None
    earliest["session_cookies"] = session_cookies
    return earliest


def expiry_note(info: dict | None, now: float | None = None) -> str | None:
    """The one line a caller sees when a saved login is past or near its
    expiry, or None when there is nothing worth saying. Silence is the
    common case and is deliberate: a note on every load is a note nobody
    reads by the third one."""
    if not info or "expires" not in info:
        return None
    now = time.time() if now is None else now
    left = info["expires"] - now
    # The name is the PAGE's, quoted and capped, never interpolated raw into
    # a sentence the server writes (gauntlet 2 M2).
    name = _credentials.quoted_name(info.get("name"))
    where = (f' for {_credentials.quoted_name(info["domain"])}'
             if info.get("domain") else "")
    if left <= 0:
        return (f'the earliest auth cookie in this file (name as set by the '
                f'site: {name}{where}) expired {human_span(left)} ago; a '
                f'fresh login is likely needed')
    if left <= NEAR_EXPIRY_S:
        return (f'the earliest auth cookie in this file (name as set by the '
                f'site: {name}{where}) expires in {human_span(left)}; a '
                f'fresh login is likely needed soon')
    return None


# ------------------------------------------------------- locate and annotate


def locate(page: str):
    """The page-addressed entry every pack tool shares with the lite core."""
    sess, record = MANAGER.locate(page)
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=record.page.url, lane=sess.spec.label)
    record.touch(record.page.url)
    return sess, record


def session_of(session: str | None):
    """The session-addressed entry, with the same audit annotation."""
    sess = MANAGER.session(session)
    _audit.annotate(session=sess.session_id, lane=sess.spec.label)
    return sess


# ----------------------------------------------------- the scoped directories


def downloads_dir() -> Path:
    """The one directory downloads and default exports land in. Governed by
    the sandbox when KS4WEB_ALLOWED_ROOTS is set; created on first use."""
    raw = os.environ.get(ENV_DOWNLOAD_DIR) \
        or str(Path.home() / "Downloads" / "KS4Web")
    path = Path(sandbox.check_path(raw, "resolve the downloads directory"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def spill_dir() -> Path:
    """Where oversized payloads spill instead of flooding the transcript."""
    raw = os.environ.get(ENV_SPILL_DIR)
    if not raw:
        base = os.environ.get(ENV_DOWNLOAD_DIR) \
            or str(Path.home() / "Downloads" / "KS4Web")
        raw = str(Path(base) / "spill")
    path = Path(sandbox.check_path(raw, "resolve the spill directory"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def stamp() -> str:
    """A filename-safe local timestamp for default output names."""
    return time.strftime("%Y%m%d_%H%M%S")


#: Windows device names. Opening one of these succeeds, consumes the bytes,
#: and persists nothing, so `saved_to: "CON"` with a byte count was a
#: fabricated receipt for a file that does not exist (fuzzer class 4).
_DEVICE_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)])


def resolve_out_path(path, purpose: str) -> Path:
    """The ONE resolution every output path goes through.

    `saved_to` has to be an honest answer to "where did it go", and before
    the union wave it was the caller's own string echoed back: `~/x.txt`
    created a directory literally named `~`, `%TEMP%/x.txt` one named
    `%TEMP%`, and `../../../../x.txt` was echoed unresolved while the file
    landed relative to a server CWD the caller cannot see (fuzzer class 4).

    Three steps: expand the shell tokens the caller plainly meant, run the
    sandbox check on what that resolves to (so containment sees the real
    target rather than the token), and return an ABSOLUTE path. A device
    name refuses rather than reporting a write that persisted nothing."""
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    expanded = os.path.expandvars(os.path.expanduser(raw.strip()))
    if not expanded:
        raise FileWriteFailed(
            f"refusing to {purpose}: the path is empty. Give a file path, "
            f"or omit path to use the server's downloads directory.")
    # The device check runs on the name the CALLER gave, before abspath:
    # `os.path.abspath("CON")` already rewrites it to the `\\.\CON` device
    # form, where the basename is empty and the check would miss.
    leaf = os.path.basename(expanded.replace("\\", "/").rstrip("/")) or expanded
    if ":" in leaf:
        # An NTFS alternate data stream. The bytes land somewhere no
        # directory listing shows, which is not what any caller asking for
        # `x.txt:stream` means (fuzzer class 4).
        raise FileWriteFailed(
            f"refusing to {purpose}: {leaf!r} names an alternate data "
            f"stream rather than a file. The bytes would not appear in any "
            f"directory listing. Use a file name with no colon in it.")
    if leaf.split(".")[0].strip().lower() in _DEVICE_NAMES:
        raise FileWriteFailed(
            f"refusing to {purpose}: {leaf!r} is a reserved device name on "
            f"this platform. Writing to it consumes the bytes and persists "
            f"no file, so the receipt would name a file that does not "
            f"exist. Choose an ordinary file name.")
    checked = sandbox.check_path(expanded, purpose)
    return Path(os.path.abspath(checked))


def write_failed(p: Path, purpose: str, exc: OSError) -> FileWriteFailed:
    """One typed refusal for every filesystem fault on the write path.

    Chaos C-11 and fuzzer class 1a: five tools answered BAD_PARAMS with a
    bare `[Errno 13] Permission denied: '...'` and the location-object hint
    under it, and an over-long Windows path answered NOT_FOUND ("no such
    file") for a file the caller had asked the server to CREATE."""
    detail = envelope.scrub_driver_text(str(exc))
    cause = ""
    if isinstance(exc, PermissionError):
        cause = ("the directory or the file refuses writes, or something "
                 "else holds it open. ")
    elif isinstance(exc, IsADirectoryError):
        cause = "a directory already occupies that name. "
    elif isinstance(exc, FileNotFoundError) and len(str(p)) > 240:
        cause = (f"the path is {len(str(p))} characters, past the limit this "
                 f"platform accepts. ")
    elif isinstance(exc, FileNotFoundError):
        cause = "part of the path does not exist and could not be created. "
    elif getattr(exc, "errno", None) == errno.ENOSPC:
        cause = "the volume is full. "
    return FileWriteFailed(
        f"could not {purpose}: {cause}Nothing was written. Target was "
        f"{p} (filesystem detail: {detail}). Choose a writable directory, "
        f"or omit path to use the server's downloads directory.")


def write_text_file(path, text: str, purpose: str) -> str:
    """Sandbox-checked, REDACTED text write. Every text file leaving the
    server passes the same redaction seam a payload does (DESIGN 5.3), so a
    tool that forgot its own scrubbing is still caught here."""
    p = resolve_out_path(path, purpose)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(envelope.redact(text), encoding="utf-8", newline="")
    except OSError as exc:
        raise write_failed(p, purpose, exc) from exc
    return str(p)


def write_bytes_file(path, data: bytes, purpose: str) -> str:
    """Sandbox-checked binary write (images, PDFs, MHTML). Binary payloads
    carry pixels rather than strings, so the redaction seam does not apply;
    the sandbox containment still does."""
    p = resolve_out_path(path, purpose)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except OSError as exc:
        raise write_failed(p, purpose, exc) from exc
    return str(p)


# ------------------------------------------------------------ image sniffing

#: Magic-number table. Format, media type, and file extension are ALL derived
#: from this one sniff; nothing downstream may restate any of the three.
_IMAGE_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
)


def sniff_image(data: bytes) -> tuple[str, str]:
    """(format, media_type) from the bytes, or a refusal. An image whose
    bytes cannot be identified is never returned under a guessed media type,
    because a mismatched type is the defect that permanently poisons a
    session (playwright-mcp #1211)."""
    for magic, fmt, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return fmt, mime
    raise UnsupportedContent(
        f"the captured bytes ({len(data)} of them) are not a PNG or a JPEG, "
        f"so no media type can be honestly attached and nothing is returned. "
        f"Retry the capture; if this repeats, the lane's screenshot encoder "
        f"is misbehaving and the page can still be read with get_page_view.")


# ------------------------------------------------------------------ paging


def page_slice(items: list, start_index: int, limit: int):
    """(chunk, total, next_start_index) with the house continuation shape."""
    total = len(items)
    start = max(0, int(start_index))
    chunk = items[start:start + max(1, int(limit))]
    nxt = start + len(chunk)
    return chunk, total, (nxt if nxt < total else None)


def clip(text, n: int) -> str:
    s = " ".join(str("" if text is None else text).split())
    return s if len(s) <= n else s[:n] + "..."
