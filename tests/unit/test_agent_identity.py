"""Agent identification: a checkbox, default off, and never a lie.

Some sites explicitly welcome agent traffic and have no way to tell that this
one is here. The option to say so is a TOGGLE rather than a text field, which
is the family's config-surface rule and also the whole reason this is safe: a
caller who could compose the header could compose a claim about who they are,
and this feature exists only because it never does that.

The pin that carries the doctrine is the last one. Turned on or off, the
browser's own user agent is untouched: no product token spliced into it, no
`navigator.userAgent` patch, no fingerprint that says one thing to a script
and another to a server.
"""

from __future__ import annotations

import pytest

from kitchensink4web.engine import lanes
from kitchensink4web.errors import BadParams

SPEC = lanes.LaneSpec(lane="A", engine="chromium")


def test_identification_is_off_by_default(monkeypatch):
    monkeypatch.delenv(lanes.ENV_AGENT_ID, raising=False)
    assert lanes.agent_identity() is None
    assert "extra_http_headers" not in lanes.launch_kwargs(SPEC, "profile")


def test_turning_it_on_sends_one_honest_header(monkeypatch):
    monkeypatch.setenv(lanes.ENV_AGENT_ID, "true")
    identity = lanes.agent_identity()
    assert identity["on"] is True
    headers = lanes.launch_kwargs(SPEC, "profile")["extra_http_headers"]
    assert list(headers) == [lanes.AGENT_HEADER]
    assert headers[lanes.AGENT_HEADER].startswith("KitchenSink4Web/")


def test_the_payload_says_what_the_header_cannot_prove(monkeypatch):
    monkeypatch.setenv(lanes.ENV_AGENT_ID, "true")
    identity = lanes.agent_identity()
    assert "cannot verify" in identity["verification"]
    assert identity["off_switch"] == f"{lanes.ENV_AGENT_ID}=false"
    assert "every request" in identity["applies_to"]


@pytest.mark.parametrize("value", ["", "false", "0", "off", "no"])
def test_the_off_spellings_are_off(monkeypatch, value):
    monkeypatch.setenv(lanes.ENV_AGENT_ID, value)
    assert lanes.agent_identity() is None


@pytest.mark.parametrize("value", [
    "KS4Web crawler", "yes please", "Mozilla/5.0", "tru", "1;true",
])
def test_a_value_that_is_not_a_toggle_refuses(monkeypatch, value):
    """It is a checkbox. Anything that looks like an attempt to WRITE the
    identity is a loud refusal rather than a silently ignored setting."""
    monkeypatch.setenv(lanes.ENV_AGENT_ID, value)
    with pytest.raises(BadParams) as caught:
        lanes.agent_identity()
    assert lanes.ENV_AGENT_ID in str(caught.value)


def test_the_user_agent_is_never_touched_either_way(monkeypatch):
    monkeypatch.setenv(lanes.ENV_AGENT_ID, "true")
    kwargs = lanes.launch_kwargs(SPEC, "profile")
    assert "user_agent" not in kwargs
    assert lanes.AGENT_HEADER.lower() != "user-agent"
    assert "user-agent" not in {
        k.lower() for k in kwargs["extra_http_headers"]}
    assert lanes.agent_identity()["user_agent"].startswith("unchanged")


def test_emulation_options_still_reach_the_launch(monkeypatch):
    """The identification header rides alongside the context options rather
    than replacing them."""
    monkeypatch.setenv(lanes.ENV_AGENT_ID, "true")
    kwargs = lanes.launch_kwargs(SPEC, "profile", {"locale": "ko-KR"})
    assert kwargs["locale"] == "ko-KR"
    assert kwargs["extra_http_headers"]


def test_a_misconfigured_toggle_is_reported_by_status_not_raised(monkeypatch):
    """Status is the surface an agent reaches for when everything else is
    refusing, so it has to be able to SAY what is wrong. Opening a session
    still refuses loudly, which is where the typo costs something."""
    from kitchensink4web.ops import lite

    monkeypatch.setenv(lanes.ENV_AGENT_ID, "KS4Web crawler")
    line = lite._identification_line()
    assert line["agent_identification"]["on"] is False
    assert lanes.ENV_AGENT_ID in line["agent_identification"]["misconfigured"]
