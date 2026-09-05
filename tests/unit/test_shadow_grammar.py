"""The location grammar after the shadow traversal build, and the crash row.

Two things landed together on 2026-09-06 and both are about not pretending.

The audit that preceded the build found `frame` and `shadow` were accepted by
`selector_of` and read by nothing: a caller who wrote either one got a silent
no-op, which is worse than a refusal because it looks like it worked. The build
made `shadow` real and removed `frame`, and these tests pin both halves so the
grammar cannot drift back into accepting a key nothing consumes.

The crash row is the same discipline one layer down. The driver has two strings
for one event, "Page crashed" and "Target crashed", and the M1 work caught only
the first. The shadow spike hit the second: bundled Chromium kills its own
renderer laying out a chain of roughly 28 nested open shadow roots, which is a
page a hostile site can serve on purpose. Unclassified, it fell through to
BAD_PARAMS and inherited the location-selector hint, sending the caller to fix
arguments that were fine.
"""

from __future__ import annotations

import pytest

from kitchensink4web import envelope
from kitchensink4web.errors import BadParams
from kitchensink4web.ops import act


def test_shadow_is_a_modifier_and_rides_alongside_a_selector():
    assert act.selector_of({"css": "#x", "shadow": True}) == ("css", "#x")
    assert act.selector_of({"css": "#x", "shadow": False}) == ("css", "#x")
    assert "shadow" in act._MODIFIERS


def test_frame_is_gone_from_the_grammar_and_refuses_by_name():
    assert "frame" not in act._MODIFIERS
    with pytest.raises(BadParams) as caught:
        act.selector_of({"css": "#x", "frame": "f1"})
    message = str(caught.value)
    assert "no 'frame' modifier" in message
    # The refusal names the route that does exist rather than dead-ending.
    assert "completeness block" in message


def test_the_selector_list_in_the_refusal_no_longer_advertises_frame():
    with pytest.raises(BadParams) as caught:
        act.selector_of({"nonsense": "x"})
    message = str(caught.value)
    assert "shadow/exact are modifiers" in message
    assert "frame/shadow/exact" not in message


def test_both_driver_spellings_of_a_renderer_crash_classify_as_conflict():
    for text in ("Page.evaluate: Target crashed ",
                 "Page.goto: Target crashed",
                 "locator.click: Page crashed"):
        assert envelope.classify(RuntimeError(text)) == "CONFLICT", text


def test_a_target_crash_refusal_names_the_recovery_not_the_arguments():
    payload = envelope.refusal(RuntimeError("Page.evaluate: Target crashed "))
    message = payload["error"]["message"]
    assert payload["error"]["code"] == "CONFLICT"
    assert "renderer process crashed" in message
    assert "shadow roots" in message           # the cause this build can hit
    assert "manage_tabs(action='open'" in message
    # The old failure: the caller was told to fix a location selector.
    assert "not a selector" not in message
