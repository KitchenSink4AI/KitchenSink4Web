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

import os
import time
from pathlib import Path

from .. import envelope
from ..engine.session import MANAGER
from ..errors import UnsupportedContent
from ..policy import audit as _audit
from ..policy import sandbox

ENV_DOWNLOAD_DIR = "KS4WEB_DOWNLOAD_DIR"
ENV_SPILL_DIR = "KS4WEB_SPILL_DIR"


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


def write_text_file(path, text: str, purpose: str) -> str:
    """Sandbox-checked, REDACTED text write. Every text file leaving the
    server passes the same redaction seam a payload does (DESIGN 5.3), so a
    tool that forgot its own scrubbing is still caught here."""
    p = Path(sandbox.check_path(os.fspath(path), purpose))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(envelope.redact(text), encoding="utf-8", newline="")
    return str(p)


def write_bytes_file(path, data: bytes, purpose: str) -> str:
    """Sandbox-checked binary write (images, PDFs, MHTML). Binary payloads
    carry pixels rather than strings, so the redaction seam does not apply;
    the sandbox containment still does."""
    p = Path(sandbox.check_path(os.fspath(path), purpose))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
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
