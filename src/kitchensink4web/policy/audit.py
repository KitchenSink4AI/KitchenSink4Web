"""The audit trail: every tool call recorded, bounded, redacted at write.

DESIGN 5.6. Unserved: no browser agent ships a user-facing action log. The
vendor features that look adjacent let a user ERASE what happened, not
review it. This is the closest true analog to the document family's backup
pillar: you cannot always undo a web action, but you can always know
exactly what was done.

The record shape: timestamp, lane, page handle, URL, tool, the resolved
target (anchor fingerprint plus its human label plus the anchor id, which is
one of exactly two places anchor ids ever surface, DESIGN 3.5), an argument
summary with secrets already redacted, the outcome, any rebind event, any
gate decision, and the budget counters at that moment. JSONL under the
state directory; `get_audit` renders it, paginated.

**Redaction happens at write, through the same vault the serializer
checks**, so the log cannot hold what the transcript must not. **Storage is
bounded**: an in-memory ring serves `get_audit`, and the JSONL file rotates
at a cap with the dropped count carried forward, because an audit trail
that can fill a disk is its own denial of service.

Honest framing, binding on every description of this feature: it is an
operational log for the user. It is NOT forensic and NOT evidence.

The base record for every call is written by the server's tool wrapper; ops
code enriches the current call's record through `annotate()`, a
context-local channel, so the policy layer needs no import from ops and the
enrichment cannot leak across concurrent calls.
"""

from __future__ import annotations

import contextvars
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..errors import RangeOutOfBounds
from . import credentials, sandbox

#: Same env var the engine's journal uses; the default is duplicated rather
#: than imported because policy/ may not import engine/ (DESIGN 10.3).
STATE_DIR = Path(
    os.environ.get("KS4WEB_STATE_DIR")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ks4web")
)

MAX_RECORDS = max(100, int(os.environ.get("KS4WEB_AUDIT_MAX", "5000")))

#: How much of any single argument value the summary keeps. The audit is a
#: log of WHAT was done, not a second copy of every payload.
ARG_CLIP = 200

_annotations: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "ks4web_audit_annotations", default=None)


def annotate(**fields: Any) -> None:
    """Enrich the CURRENT tool call's audit record (session, page, url,
    target, rebind, gate). Context-local, so concurrent calls cannot cross."""
    current = _annotations.get()
    if current is None:
        current = {}
        _annotations.set(current)
    current.update(fields)


def take_annotation(field: str) -> Any:
    """Remove one field from the CURRENT call's annotations and return it.

    THE COMPOSITE'S TOOL (2026-09-07, from the batch build). Annotations
    merge into one dict at write, so a composite that calls several
    replayable tools inside a single registered tool call keeps only the
    LAST one's `replay` block: a five-step batch would be saved as one step,
    quietly, by a `save_workflow` that has no way to know it. A composite
    takes each step's block as that step finishes and republishes the list
    under its own key, and taking it also clears the buffer, so the
    composite's own record cannot inherit a member's block as though it
    described the whole call."""
    current = _annotations.get()
    if not current:
        return None
    return current.pop(field, None)


def _drain_annotations() -> dict:
    current = _annotations.get() or {}
    _annotations.set(None)
    return current


def observe_secret_args(args: dict | None, _depth: int = 0) -> None:
    """Vault every credential-SHAPED argument value before the log is written.

    THE CLASS, not one tool (union wave, 2026-09-07, from the dream-boundary
    review). `record()` scrubs its entry against the vault, and the vault
    only holds what something called `observe` on. Nothing on the tool-call
    path ever did, so a value that arrives as a tool ARGUMENT and is never
    read back out of a cookie jar or a storage item was never observed and
    the scrub had nothing to match. `server._wrap` records `args=kwargs` for
    every successful call, so a bearer token handed to
    `set_routing(action='headers', headers={'Authorization': 'Bearer ...'})`
    was written verbatim into `audit-<pid>.jsonl` on disk.

    The classifier is the same `classify_name` the cookie and storage doors
    use, so the calibration is shared: a preference-shaped key never enters
    the vault, and the field test's over-redaction lesson (a five-character
    `light` garbling every read that quotes it) is not re-learned here.
    Nested dicts and lists are walked, because `headers` is a dict and
    `fields` is a list of dicts."""
    if _depth > 6 or not args:
        return
    for key, value in (args.items() if isinstance(args, dict)
                       else enumerate(args)):
        if isinstance(value, dict):
            observe_secret_args(value, _depth + 1)
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, (dict, list, tuple)):
                    observe_secret_args(item, _depth + 1)
            continue
        if isinstance(value, str) and _is_secret_arg(key):
            credentials.VAULT.observe(value)


#: Argument and header names that carry credential material and that the
#: cookie/storage classifier deliberately does not name. Kept HERE rather
#: than added to `SECURITY_NAME_TOKENS`, because that list also decides what
#: gets vaulted out of every cookie jar, and widening it there is how the
#: 2026-09-05 over-redaction gets re-learned.
_SECRET_ARG_TOKENS = ("cookie", "authorization", "proxy-authorization",
                      "x-api", "x-auth", "private_key", "privatekey",
                      "client_secret", "refresh")


def _is_secret_arg(key: Any) -> bool:
    text = ("" if key is None else str(key)).strip().lower()
    if not text:
        return False
    if credentials.classify_name(text) == "credential":
        return True
    return any(token in text for token in _SECRET_ARG_TOKENS)


def summarize_args(args: dict | None) -> dict:
    """Scrub, then clip. THE ORDER IS THE POINT (union wave): clipping first
    cuts a long secret into a prefix the vault's substring match no longer
    recognizes, so the scrub at write would sail straight past a bearer
    token that had been truncated to 200 characters."""
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        text = value if isinstance(value, (int, float, bool, type(None))) \
            else str(value)
        if isinstance(text, str):
            text = credentials.redactor(text)
            if len(text) > ARG_CLIP:
                text = text[:ARG_CLIP] + f"… [{len(text)} chars]"
        out[key] = text
    return out


class AuditLog:
    """One process run's log: a bounded ring plus a rotating JSONL file."""

    def __init__(self) -> None:
        self._ring: deque[dict] = deque(maxlen=MAX_RECORDS)
        self._seq = 0
        self._dropped = 0
        self._file_records = 0
        self._path: Path | None = None

    # ------------------------------------------------------------- writing

    def _file(self) -> Path:
        if self._path is None:
            directory = STATE_DIR / "audit"
            if sandbox.active():
                sandbox.check_path(str(directory), "write the audit log")
            directory.mkdir(parents=True, exist_ok=True)
            self._path = directory / f"audit-{os.getpid()}.jsonl"
        return self._path

    def record(self, tool: str, outcome: str, args: dict | None = None,
               **fields: Any) -> dict:
        """Append one record. Every value passes the vault scrub, so a
        credential observed anywhere in the process cannot land in the log."""
        self._seq += 1
        # OBSERVE BEFORE SUMMARIZING. The scrub below can only replace what
        # the vault holds, and a secret arriving as a tool argument was
        # never observed by anything (union wave; see observe_secret_args).
        # This also vaults it for every LATER payload in the process, which
        # is the point of the vault being process-wide.
        observe_secret_args(args)
        entry: dict[str, Any] = {
            "seq": self._seq,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "outcome": outcome,
            "args": summarize_args(args),
        }
        entry.update(_drain_annotations())
        entry.update(fields)
        entry = credentials.redactor(entry)
        if len(self._ring) == self._ring.maxlen:
            self._dropped += 1
        self._ring.append(entry)
        try:
            path = self._file()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._file_records += 1
            if self._file_records > 2 * MAX_RECORDS:
                self._rotate(path)
        except OSError:
            # The ring still holds the record; a full or unwritable disk
            # must not turn every tool call into a refusal.
            pass
        return entry

    def _rotate(self, path: Path) -> None:
        """Keep the newest MAX_RECORDS on disk; the count of what rotation
        has dropped is part of the read payload rather than a silent loss."""
        keep = list(self._ring)
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for entry in keep:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        tmp.replace(path)
        self._file_records = len(keep)

    # ------------------------------------------------------------- reading

    def read(self, start_index: int = 0, limit: int = 50,
             tool: str | None = None, session: str | None = None) -> dict:
        """Paginated view over the ring, newest last, filters ANDed."""
        if start_index < 0:
            raise RangeOutOfBounds(
                f"start_index {start_index} is negative; the log starts at 0.")
        rows = [r for r in self._ring
                if (tool is None or r.get("tool") == tool)
                and (session is None or r.get("session") == session)]
        window = rows[start_index:start_index + max(1, min(limit, 500))]
        next_index = start_index + len(window)
        return {
            "records": window,
            "total_matching": len(rows),
            "start_index": start_index,
            "next_start_index": next_index if next_index < len(rows) else None,
            "retention": {
                "ring_capacity": MAX_RECORDS,
                "dropped_from_ring": self._dropped,
                "file": str(self._path) if self._path else None,
            },
            "framing": ("an operational log for the user: what was done, "
                        "against what, with what outcome. Not forensic and "
                        "not evidence."),
        }

    def reset(self) -> None:
        """Test harness only: a fresh log for a fresh launch shape."""
        self._ring.clear()
        self._seq = 0
        self._dropped = 0
        self._file_records = 0
        self._path = None


#: The process log. The server wrapper writes to it; get_audit reads it.
LOG = AuditLog()
