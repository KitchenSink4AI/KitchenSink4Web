"""What a command and a response are allowed to look like.

The relay validates structure before forwarding in either direction (spec
section 7, item 6). The point is not to second-guess the extension, it is
that the relay sits on a pipe the browser launched and a malformed frame
should be refused at the boundary with a reason, not passed inward to fail
somewhere with less context.

Chunk reassembly lives here too. The extension splits a large response into
frames carrying slices of the SERIALISED result; the assembler concatenates
the slices and parses once, so a chunked response and a whole one are
byte-identical to the caller.
"""

from __future__ import annotations

import json
from typing import Any

# Commands are tiny by construction. A command larger than this is either a
# bug or an attempt to push a payload the wrong way down the pipe.
MAX_COMMAND_BYTES = 64 * 1024


class ProtocolError(Exception):
    """A message did not have the shape the protocol requires."""


def validate_command(message: Any) -> dict:
    """Check a server -> extension command. Returns it unchanged."""
    if not isinstance(message, dict):
        raise ProtocolError(f"command must be an object, got {type(message).__name__}")
    if "id" not in message:
        raise ProtocolError("command has no id")
    if not isinstance(message["id"], int):
        raise ProtocolError(f"command id must be an int, got {type(message['id']).__name__}")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError("command has no method")
    params = message.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError(f"command params must be an object, got {type(params).__name__}")
    encoded = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_COMMAND_BYTES:
        raise ProtocolError(
            f"command is {len(encoded)} bytes, over the {MAX_COMMAND_BYTES}-byte command ceiling"
        )
    return message


def validate_response(message: Any) -> dict:
    """Check an extension -> server response. Returns it unchanged."""
    if not isinstance(message, dict):
        raise ProtocolError(f"response must be an object, got {type(message).__name__}")
    if "id" not in message:
        raise ProtocolError("response has no id")
    if not isinstance(message["id"], int):
        raise ProtocolError(f"response id must be an int, got {type(message['id']).__name__}")
    present = [key for key in ("result", "error", "chunk") if key in message]
    if len(present) != 1:
        raise ProtocolError(
            "response must carry exactly one of result, error, chunk; got " + (str(present) or "none")
        )
    if "error" in message:
        error = message["error"]
        if not isinstance(error, dict) or "code" not in error or "message" not in error:
            raise ProtocolError("error must be an object with code and message")
    if "chunk" in message:
        chunk = message["chunk"]
        if not isinstance(chunk, dict):
            raise ProtocolError("chunk must be an object")
        for field in ("seq", "total", "data"):
            if field not in chunk:
                raise ProtocolError(f"chunk has no {field}")
        if not isinstance(chunk["seq"], int) or not isinstance(chunk["total"], int):
            raise ProtocolError("chunk seq and total must be ints")
        if not isinstance(chunk["data"], str):
            raise ProtocolError("chunk data must be a string")
        if chunk["total"] < 1 or not (0 <= chunk["seq"] < chunk["total"]):
            raise ProtocolError(f"chunk {chunk['seq']} of {chunk['total']} is out of range")
    return message


class ChunkAssembler:
    """Collects chunk frames until a response is whole.

    ``feed`` returns the completed response the moment the last slice lands,
    and ``None`` while one is still outstanding. Out-of-order arrival is
    tolerated because the slices are indexed, not appended.
    """

    def __init__(self) -> None:
        self._pending: dict[int, dict[int, str]] = {}
        self._totals: dict[int, int] = {}

    def feed(self, message: dict) -> dict | None:
        if "chunk" not in message:
            return message
        ident = message["id"]
        chunk = message["chunk"]
        total = chunk["total"]
        known = self._totals.setdefault(ident, total)
        if known != total:
            raise ProtocolError(
                f"response {ident} changed its chunk count from {known} to {total}"
            )
        slices = self._pending.setdefault(ident, {})
        slices[chunk["seq"]] = chunk["data"]
        if len(slices) < total:
            return None
        text = "".join(slices[seq] for seq in range(total))
        del self._pending[ident]
        del self._totals[ident]
        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProtocolError(
                f"response {ident} reassembled from {total} chunks is not JSON: {exc}"
            ) from exc
        return {"id": ident, "result": result}

    @property
    def outstanding(self) -> int:
        return len(self._pending)
