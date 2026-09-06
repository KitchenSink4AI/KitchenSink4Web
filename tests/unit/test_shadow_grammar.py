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


def test_frame_came_back_as_a_real_modifier():
    """REVERSED by the same-origin frame build, 2026-09-06, hours after this
    file first asserted the opposite.

    The shadow build removed `frame` and its reasoning was right at the time:
    reaching into an iframe is different machinery, because the resolver runs
    in one execution context and a frame has its own. What changed is that the
    machinery got built, so the refusal this test used to pin would now be a
    lie about a capability that exists. The assertion that MATTERS survives
    the reversal unchanged: `frame` is a MODIFIER and never a selector, so it
    rides alongside exactly one selector and cannot be a location by itself."""
    assert "frame" in act._MODIFIERS
    group, value = act.selector_of({"css": "#x", "frame": "if1"})
    assert group == "css" and value == "#x"
    with pytest.raises(BadParams) as caught:
        act.selector_of({"frame": "if1"})
    assert "exactly one selector" in str(caught.value)


def test_the_selector_list_in_the_refusal_advertises_all_three_modifiers():
    with pytest.raises(BadParams) as caught:
        act.selector_of({"nonsense": "x"})
    message = str(caught.value)
    assert "shadow/exact/frame are modifiers" in message


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
