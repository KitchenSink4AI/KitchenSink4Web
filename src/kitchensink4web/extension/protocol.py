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

import base64
import binascii
import gzip
import json
from typing import Any

# Commands are tiny by construction. A command larger than this is either a
# bug or an attempt to push a payload the wrong way down the pipe.
MAX_COMMAND_BYTES = 64 * 1024

#: The one compressed encoding this build speaks. `CompressionStream('gzip')`
#: is what the extension has and base64 is what survives a JSON string, so
#: the pair travels as one name rather than two independent fields nobody
#: validates together.
GZIP_B64 = "gzip+base64"

#: What a payload may be encoded as. `None` is the identity encoding and is
#: not spelled out on the wire; anything else has to be in this set, so an
#: unknown name refuses at the boundary instead of arriving as a string the
#: caller thinks is JSON.
ENCODINGS = (None, GZIP_B64)


class ProtocolError(Exception):
    """A message did not have the shape the protocol requires."""


#: How many commands one batch may carry. A batch exists to turn a five-field
#: form fill into one round trip, not to become a scripting language on the
#: pipe: past this the size of the reply stops being predictable and the rate
#: limit in the background script stops meaning anything.
MAX_BATCH_STEPS = 32


def validate_command(message: Any) -> dict:
    """Check a server -> extension command. Returns it unchanged."""
    if not isinstance(message, dict):
        raise ProtocolError(f"command must be an object, got {type(message).__name__}")
    if "id" not in message:
        raise ProtocolError("command has no id")
    if not isinstance(message["id"], int):
        raise ProtocolError(f"command id must be an int, got {type(message['id']).__name__}")
    if "batch" in message:
        steps = message["batch"]
        if not isinstance(steps, list) or not steps:
            raise ProtocolError("batch must be a non-empty array")
        if len(steps) > MAX_BATCH_STEPS:
            raise ProtocolError(
                f"batch carries {len(steps)} steps, over the "
                f"{MAX_BATCH_STEPS}-step ceiling")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ProtocolError(f"batch step {index} must be an object")
            if not isinstance(step.get("method"), str) or not step["method"]:
                raise ProtocolError(f"batch step {index} has no method")
            if not isinstance(step.get("params", {}), dict):
                raise ProtocolError(f"batch step {index} params must be an object")
    else:
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


def decode_payload(text: str, encoding: str | None) -> Any:
    """Turn a wire payload back into the object the extension serialised.

    The identity encoding parses; `gzip+base64` un-base64s, gunzips, and then
    parses. A payload that does not survive either step is a ProtocolError
    naming which step failed, because "not JSON" and "not valid base64" send
    a reader looking in different places."""
    if encoding is None:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"payload is not JSON: {exc}") from exc
    if encoding != GZIP_B64:
        raise ProtocolError(
            f"unknown payload encoding {encoding!r}; this build speaks "
            f"{[e for e in ENCODINGS if e]} and the identity encoding")
    try:
        packed = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError(f"payload is not valid base64: {exc}") from exc
    try:
        raw = gzip.decompress(packed)
    except (OSError, EOFError) as exc:
        raise ProtocolError(f"payload did not gunzip: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(
            f"payload gunzipped to something that is not JSON: {exc}") from exc


def validate_response(message: Any) -> dict:
    """Check an extension -> server response. Returns it unchanged."""
    if not isinstance(message, dict):
        raise ProtocolError(f"response must be an object, got {type(message).__name__}")
    if "event" in message and "id" not in message:
        # AN UNSOLICITED EVENT is the one message with no id, and it is not a
        # malformed response. The extension pushes one when the PAGE changes
        # something the server believes it knows: an SPA history update moves
        # the document under refs that were minted against the old one.
        if not isinstance(message["event"], str):
            raise ProtocolError("event must be a string")
        return message
    if "id" not in message:
        raise ProtocolError("response has no id")
    if not isinstance(message["id"], int):
        raise ProtocolError(f"response id must be an int, got {type(message['id']).__name__}")
    present = [key for key in ("result", "error", "chunk", "encoded") if key in message]
    if len(present) != 1:
        raise ProtocolError(
            "response must carry exactly one of result, error, chunk, encoded; got "
            + (str(present) or "none")
        )
    if "encoded" in message:
        encoded = message["encoded"]
        if not isinstance(encoded, dict):
            raise ProtocolError("encoded must be an object")
        if not isinstance(encoded.get("data"), str):
            raise ProtocolError("encoded data must be a string")
        if encoded.get("encoding") not in ENCODINGS:
            raise ProtocolError(
                f"unknown payload encoding {encoded.get('encoding')!r}")
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
        self._encodings: dict[int, str | None] = {}

    def feed(self, message: dict) -> dict | None:
        if "encoded" in message:
            # Compressed and whole. The encoding is resolved here rather than
            # by the caller so that a chunked reply and an unchunked one are
            # the same object by the time anything downstream sees them.
            return {"id": message["id"],
                    "result": decode_payload(message["encoded"]["data"],
                                             message["encoded"].get("encoding"))}
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
        encoding = chunk.get("encoding")
        if encoding not in ENCODINGS:
            raise ProtocolError(
                f"response {ident} chunk {chunk['seq']} names an unknown "
                f"encoding {encoding!r}")
        first = self._encodings.setdefault(ident, encoding)
        if first != encoding:
            # A stream that changed encoding mid-flight cannot be reassembled
            # into anything, and guessing which half to believe is worse than
            # saying so.
            raise ProtocolError(
                f"response {ident} changed its encoding from {first!r} to "
                f"{encoding!r} between chunks")
        slices = self._pending.setdefault(ident, {})
        slices[chunk["seq"]] = chunk["data"]
        if len(slices) < total:
            return None
        text = "".join(slices[seq] for seq in range(total))
        del self._pending[ident]
        del self._totals[ident]
        self._encodings.pop(ident, None)
        try:
            result = decode_payload(text, encoding)
        except ProtocolError as exc:
            raise ProtocolError(
                f"response {ident} reassembled from {total} chunks: {exc}"
            ) from exc
        return {"id": ident, "result": result}

    @property
    def outstanding(self) -> int:
        return len(self._pending)
