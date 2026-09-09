"""The native messaging wire format.

Every message on the pipe between Firefox and the relay is a 4-byte unsigned
length in NATIVE byte order followed by that many bytes of UTF-8 JSON. Native
byte order is the part people get wrong: ``struct`` calls it ``"@I"``, and on
every platform KS4Web runs on that is little-endian, but writing ``"<I"``
hard-codes an assumption the protocol does not make.

Nothing else may ever be written to the stream this module owns. A stray
print, a warning, a traceback on stdout corrupts the next length prefix and
Firefox reports a size error naming a number that came from the middle of a
Python string. That is the failure the Mozilla Discourse thread on exceeding
the message limit is really describing, and it is why the relay redirects its
own stdout before doing anything else.
"""

from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO

# app -> extension. Documented and enforced by Firefox.
HOST_TO_EXTENSION_LIMIT = 1024 * 1024

# extension -> app. Documented as 4 GB; measured in Phase 1 rather than
# trusted, because the one field report of Windows trouble (Bugzilla 1573034)
# was closed without a reproduction and left no threshold behind.
EXTENSION_TO_HOST_LIMIT = 4 * 1024 * 1024 * 1024

_LENGTH = struct.Struct("@I")
LENGTH_BYTES = _LENGTH.size


class FramingError(Exception):
    """The stream carried something that is not a frame.

    ``recoverable`` says whether the reader still knows where it is. A frame
    whose length prefix was honest and whose body was read in full, but whose
    body was not JSON, leaves the stream positioned exactly at the next
    length prefix: that message can be dropped and reading can continue. A
    frame that ended early leaves the reader somewhere unknown in the middle
    of the stream, and the only safe move then is to hang up.

    The distinction was found by test, not by design. The first version of
    the relay treated both the same and a single unparseable message took the
    connection down with it.
    """

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


def encode(message: Any) -> bytes:
    """Serialise one message to its on-the-wire bytes."""
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _LENGTH.pack(len(body)) + body


def write_message(stream: BinaryIO, message: Any) -> int:
    """Write one message and flush. Returns the payload byte count."""
    frame = encode(message)
    stream.write(frame)
    stream.flush()
    return len(frame) - LENGTH_BYTES


def read_message(stream: BinaryIO) -> Any | None:
    """Read one message, or ``None`` at a clean end of stream.

    A short read of the length prefix at offset zero is the browser hanging
    up, which is normal. A short read anywhere else is a truncated frame, and
    that is an error worth naming rather than a silent ``None``.
    """
    header = _read_exactly(stream, LENGTH_BYTES, allow_empty=True)
    if header is None:
        return None
    (length,) = _LENGTH.unpack(header)
    if length == 0:
        return None
    body = _read_exactly(stream, length, allow_empty=False)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FramingError(
            f"frame of {length} bytes was not UTF-8 JSON: {exc}", recoverable=True
        ) from exc


def _read_exactly(stream: BinaryIO, count: int, *, allow_empty: bool) -> bytes | None:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        piece = stream.read(remaining)
        if not piece:
            if not chunks and allow_empty:
                return None
            raise FramingError(
                f"stream ended {remaining} bytes short of a {count}-byte read"
            )
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)
