"""The native messaging wire format, and the ways a stream can lie about it."""

from __future__ import annotations

import io
import json
import struct

import pytest

from kitchensink4web.extension import framing


def test_encode_is_length_prefix_then_utf8_json():
    frame = framing.encode({"id": 1, "method": "page.read"})
    (length,) = struct.unpack("@I", frame[:4])
    assert length == len(frame) - 4
    assert json.loads(frame[4:].decode("utf-8")) == {"id": 1, "method": "page.read"}


def test_encode_uses_native_byte_order():
    # Not "<I". The protocol says native order, and hard-coding little-endian
    # would be a silent bug on the day somebody runs this somewhere else.
    frame = framing.encode({"a": 1})
    assert frame[:4] == struct.pack("@I", len(frame) - 4)


def test_round_trip_through_a_stream():
    buffer = io.BytesIO()
    framing.write_message(buffer, {"id": 7, "result": {"text": "héllo wörld"}})
    buffer.seek(0)
    assert framing.read_message(buffer) == {"id": 7, "result": {"text": "héllo wörld"}}


def test_round_trip_of_several_messages_preserves_order():
    buffer = io.BytesIO()
    for index in range(5):
        framing.write_message(buffer, {"id": index})
    buffer.seek(0)
    assert [framing.read_message(buffer)["id"] for _ in range(5)] == [0, 1, 2, 3, 4]


def test_empty_stream_reads_as_a_clean_end():
    assert framing.read_message(io.BytesIO(b"")) is None


def test_truncated_body_is_an_unrecoverable_error():
    # The distinction is the whole point: a clean hangup is normal, a frame
    # that stops halfway leaves the reader somewhere unknown in the stream,
    # and the only safe move after that is to hang up.
    stream = io.BytesIO(struct.pack("@I", 100) + b"only ten..")
    with pytest.raises(framing.FramingError) as caught:
        framing.read_message(stream)
    assert caught.value.recoverable is False


def test_truncated_length_prefix_is_an_unrecoverable_error():
    stream = io.BytesIO(b"\x01\x02")
    with pytest.raises(framing.FramingError) as caught:
        framing.read_message(stream)
    assert caught.value.recoverable is False


def test_a_whole_frame_with_a_non_json_body_is_recoverable():
    # The length was honest and the body was read in full, so the reader is
    # sitting exactly on the next prefix. Callers may drop this message and
    # carry on, which is what the relay does.
    body = b"<html>not json</html>"
    stream = io.BytesIO(struct.pack("@I", len(body)) + body)
    with pytest.raises(framing.FramingError) as caught:
        framing.read_message(stream)
    assert caught.value.recoverable is True


def test_the_reader_resumes_after_a_recoverable_frame():
    body = b"not json"
    stream = io.BytesIO(struct.pack("@I", len(body)) + body + framing.encode({"id": 5}))
    with pytest.raises(framing.FramingError):
        framing.read_message(stream)
    assert framing.read_message(stream) == {"id": 5}


def test_write_message_reports_the_payload_size():
    buffer = io.BytesIO()
    written = framing.write_message(buffer, {"x": "y" * 100})
    assert written == len(buffer.getvalue()) - framing.LENGTH_BYTES


def test_a_message_at_the_documented_host_limit_still_encodes():
    # Encoding does not enforce the limit; Firefox does, in one direction
    # only. The constant exists so callers can check, not so framing can
    # refuse.
    payload = {"id": 1, "result": "x" * (framing.HOST_TO_EXTENSION_LIMIT // 2)}
    frame = framing.encode(payload)
    assert len(frame) > framing.HOST_TO_EXTENSION_LIMIT // 2
