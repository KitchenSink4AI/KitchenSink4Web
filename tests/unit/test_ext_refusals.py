"""What the client is handed when the browser says no.

A refusal is a product surface. The one thing that must never travel is a
Python traceback or a raw `BridgeError` repr, because the caller on the
other side of the tool boundary is a model reading a string, and a string
that reads like a crash is treated like one.

The error codes are read OUT OF THE JAVASCRIPT rather than listed here, so
a code added to `background.js` or `content.js` without a decision about
what it means on the Python side fails this file instead of shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kitchensink4web.errors import BadParams, Conflict, WebMcpError
from kitchensink4web.extension.lane import PageMoved
from kitchensink4web.extension.bridge import BridgeError
from kitchensink4web.extension.lane import _extension_refusal

ASSETS = (Path(__file__).resolve().parents[2]
          / "src" / "kitchensink4web" / "extension" / "assets")

#: Every code the extension can put on the wire, taken from the source that
#: emits them. Two files, because the content script raises its own.
CODES = sorted({
    match.group(1)
    for name in ("background.js", "content.js")
    for match in re.finditer(r'code:\s*"([A-Z_]+)"',
                             (ASSETS / name).read_text(encoding="utf-8"))
})

#: The codes with a mapping of their own, and what each one means. The rest
#: land on the generic refusal, which is a decision rather than an oversight:
#: `UNKNOWN_METHOD`, `UNKNOWN_SCRIPT`, `UNKNOWN_ACTION` and `BAD_MESSAGE`
#: are this project failing its own closed sets, and there is nothing a
#: caller can do differently about any of them.
MAPPED = {
    "STATE_CHANGED": PageMoved,
    "ORIGIN_NOT_CONSENTED": Conflict,
    "RATE_LIMITED": Conflict,
    "STALE_REF": Conflict,
    "BUNDLE_MISSING": Conflict,
    "REFUSED_SCHEME": BadParams,
}


def test_the_javascript_really_does_emit_codes_to_check():
    """The list above is derived, so an empty derivation would make every
    test below pass by having nothing to check."""
    assert len(CODES) >= 10, CODES


@pytest.mark.parametrize("code", CODES)
def test_every_code_the_extension_emits_comes_back_as_a_typed_refusal(code):
    raised = _extension_refusal(BridgeError(f"{code}: something went wrong"),
                                "page.read")
    assert isinstance(raised, WebMcpError), (code, type(raised))
    assert str(raised).startswith("[lane C"), str(raised)


@pytest.mark.parametrize("code", CODES)
def test_no_refusal_reads_like_a_crash(code):
    """The negative half, and the one that matters to a reader.

    A message carrying `Traceback`, a module path, or an exception class
    repr is a crash as far as the thing reading it is concerned, whatever
    the type system says about it.
    """
    text = str(_extension_refusal(
        BridgeError(f"{code}: something went wrong"), "page.read"))
    for tell in ("Traceback", "BridgeError(", "kitchensink4web.",
                 ".py\", line", "  File "):
        assert tell not in text, (code, tell, text)


@pytest.mark.parametrize("code, expected", sorted(MAPPED.items()))
def test_the_codes_with_a_meaning_of_their_own_keep_it(code, expected):
    """The mapping, both directions: the named codes get their own type and
    an unnamed one does not accidentally acquire it."""
    assert type(_extension_refusal(BridgeError(f"{code}: x"), "page.read")) \
        is expected


def test_an_unmapped_code_lands_on_the_generic_refusal_naming_the_method():
    """A caller told only "it failed" cannot tell which call failed, and on
    a lane where one command is six round trips that matters."""
    raised = _extension_refusal(BridgeError("EXECUTION_FAILED: nope"),
                                "page.act")
    assert type(raised) is Conflict
    assert "page.act" in str(raised)


def test_every_code_is_either_mapped_or_deliberately_generic():
    """THE FORWARD-LOOKING HALF. A code added to the JavaScript without a
    decision about what it means here fails this test rather than quietly
    becoming a generic Conflict in the field."""
    known_generic = {"UNKNOWN_METHOD", "UNKNOWN_SCRIPT", "UNKNOWN_ACTION",
                     "BAD_MESSAGE", "EXECUTION_FAILED", "NO_FORM"}
    assert set(CODES) == set(MAPPED) | known_generic, (
        "the extension emits a code this file has no ruling on: "
        f"{sorted(set(CODES) - set(MAPPED) - known_generic)}")


def test_a_refusal_that_carries_a_copy_pending_slot_is_still_a_whole_message():
    """THE PLACEHOLDER RULE. The refusal strings are unwritten, and until
    they are written the slot has to be visible to a human and harmless to a
    parser: a marked gap inside an otherwise complete envelope, never an
    empty string and never a broken sentence.
    """
    text = str(_extension_refusal(
        BridgeError("REFUSED_SCHEME: [COPY PENDING] refusal text for scheme "
                    "about:"), "page.read"))
    assert "[COPY PENDING]" in text
    assert text.startswith("[lane C")
    assert "REFUSED_SCHEME" in text
    # The slot is a marker inside a message, not the whole message.
    assert len(text.replace("[COPY PENDING]", "").strip()) > 30
