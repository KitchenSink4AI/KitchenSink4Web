"""What the relay accepts at the boundary, and what it refuses.

Every refusal here is pinned in both directions. A validator that only ever
gets tested with bad input can be a function that returns False, and one that
only ever gets tested with good input can be a function that returns True;
neither is a validator.
"""

from __future__ import annotations

import json

import pytest

from kitchensink4web.extension import protocol


# -- commands ---------------------------------------------------------------


def test_a_well_formed_command_is_accepted():
    command = {"id": 1, "method": "page.read", "params": {"budget": 5000}}
    assert protocol.validate_command(command) is command


def test_a_command_with_no_params_is_accepted():
    assert protocol.validate_command({"id": 2, "method": "bg.ping"})


@pytest.mark.parametrize(
    "command, expected",
    [
        ([1, 2, 3], "must be an object"),
        ({"method": "page.read"}, "no id"),
        ({"id": "one", "method": "page.read"}, "id must be an int"),
        ({"id": 1}, "no method"),
        ({"id": 1, "method": ""}, "no method"),
        ({"id": 1, "method": 42}, "no method"),
        ({"id": 1, "method": "page.read", "params": "nope"}, "params must be an object"),
    ],
)
def test_malformed_commands_are_refused_with_a_reason(command, expected):
    with pytest.raises(protocol.ProtocolError) as caught:
        protocol.validate_command(command)
    assert expected in str(caught.value)


def test_an_oversized_command_is_refused():
    # Commands are small by construction. A large one is a payload going the
    # wrong way down the pipe, and the ceiling is where that gets caught.
    command = {"id": 1, "method": "page.read", "params": {"blob": "x" * protocol.MAX_COMMAND_BYTES}}
    with pytest.raises(protocol.ProtocolError) as caught:
        protocol.validate_command(command)
    assert "command ceiling" in str(caught.value)


def test_a_command_just_under_the_ceiling_is_accepted():
    command = {"id": 1, "method": "page.read", "params": {"blob": "x" * 1000}}
    assert protocol.validate_command(command)


# -- responses --------------------------------------------------------------


def test_a_result_response_is_accepted():
    assert protocol.validate_response({"id": 1, "result": {"text": "hi"}})


def test_an_error_response_is_accepted():
    assert protocol.validate_response({"id": 1, "error": {"code": "NOT_FOUND", "message": "x"}})


def test_a_chunk_response_is_accepted():
    assert protocol.validate_response({"id": 1, "chunk": {"seq": 0, "total": 2, "data": "ab"}})


@pytest.mark.parametrize(
    "response, expected",
    [
        ("string", "must be an object"),
        ({"result": 1}, "no id"),
        ({"id": None, "result": 1}, "id must be an int"),
        ({"id": 1}, "exactly one of result, error, chunk"),
        ({"id": 1, "result": 1, "error": {"code": "a", "message": "b"}}, "exactly one"),
        ({"id": 1, "error": {"code": "a"}}, "code and message"),
        ({"id": 1, "error": "boom"}, "code and message"),
        ({"id": 1, "chunk": {"seq": 0, "total": 2}}, "chunk has no data"),
        ({"id": 1, "chunk": {"seq": "0", "total": 2, "data": "a"}}, "must be ints"),
        ({"id": 1, "chunk": {"seq": 5, "total": 2, "data": "a"}}, "out of range"),
        ({"id": 1, "chunk": {"seq": 0, "total": 0, "data": "a"}}, "out of range"),
    ],
)
def test_malformed_responses_are_refused_with_a_reason(response, expected):
    with pytest.raises(protocol.ProtocolError) as caught:
        protocol.validate_response(response)
    assert expected in str(caught.value)


# -- reassembly -------------------------------------------------------------


def test_a_whole_response_passes_straight_through():
    assembler = protocol.ChunkAssembler()
    message = {"id": 1, "result": {"a": 1}}
    assert assembler.feed(message) is message
    assert assembler.outstanding == 0


def test_chunks_reassemble_into_the_original_object():
    payload = {"text": "x" * 5000, "chars": 5000}
    text = json.dumps(payload)
    size = 900
    chunks = [text[i : i + size] for i in range(0, len(text), size)]
    assembler = protocol.ChunkAssembler()
    result = None
    for seq, data in enumerate(chunks):
        result = assembler.feed(
            {"id": 3, "chunk": {"seq": seq, "total": len(chunks), "data": data}}
        )
        if seq < len(chunks) - 1:
            assert result is None
    assert result == {"id": 3, "result": payload}
    assert assembler.outstanding == 0


def test_chunks_arriving_out_of_order_still_reassemble():
    text = json.dumps({"v": "abcdefghij"})
    chunks = [text[i : i + 4] for i in range(0, len(text), 4)]
    assembler = protocol.ChunkAssembler()
    order = list(reversed(range(len(chunks))))
    result = None
    for seq in order:
        result = assembler.feed(
            {"id": 9, "chunk": {"seq": seq, "total": len(chunks), "data": chunks[seq]}}
        )
    assert result == {"id": 9, "result": {"v": "abcdefghij"}}


def test_two_responses_chunked_at_once_do_not_bleed_into_each_other():
    first = json.dumps({"who": "first"})
    second = json.dumps({"who": "second"})
    assembler = protocol.ChunkAssembler()
    assembler.feed({"id": 1, "chunk": {"seq": 0, "total": 2, "data": first[:4]}})
    assembler.feed({"id": 2, "chunk": {"seq": 0, "total": 2, "data": second[:4]}})
    assert assembler.outstanding == 2
    done_two = assembler.feed({"id": 2, "chunk": {"seq": 1, "total": 2, "data": second[4:]}})
    done_one = assembler.feed({"id": 1, "chunk": {"seq": 1, "total": 2, "data": first[4:]}})
    assert done_two == {"id": 2, "result": {"who": "second"}}
    assert done_one == {"id": 1, "result": {"who": "first"}}
    assert assembler.outstanding == 0


def test_a_changed_chunk_count_is_refused():
    assembler = protocol.ChunkAssembler()
    assembler.feed({"id": 1, "chunk": {"seq": 0, "total": 3, "data": "a"}})
    with pytest.raises(protocol.ProtocolError) as caught:
        assembler.feed({"id": 1, "chunk": {"seq": 1, "total": 5, "data": "b"}})
    assert "changed its chunk count" in str(caught.value)


def test_chunks_that_do_not_reassemble_into_json_are_refused():
    assembler = protocol.ChunkAssembler()
    assembler.feed({"id": 1, "chunk": {"seq": 0, "total": 2, "data": "{not"}})
    with pytest.raises(protocol.ProtocolError) as caught:
        assembler.feed({"id": 1, "chunk": {"seq": 1, "total": 2, "data": " json}"}})
    assert "is not JSON" in str(caught.value)
