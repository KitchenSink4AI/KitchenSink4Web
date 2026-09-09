"""Lane resolution and the capabilities truth table, without a browser.

The table is measurement rather than inheritance: S4 ran twenty probes on both
`moz-firefox` (Firefox 154) and Chromium against a local deterministic fixture
server, with Chromium as the control, and every probe passed on Chromium, so
each Firefox row is a genuine lane difference. These tests hold the table to
what was measured and hold the refusals to the shape DESIGN 4.5a wrote.
"""

from __future__ import annotations

import pytest

from kitchensink4web.engine import FIREFOX_SAFETY_ARGS, lanes
from kitchensink4web.errors import BadParams, LaneUnsupported


# ------------------------------------------------------------- resolution


def test_lane_a_defaults_to_bundled_chromium():
    spec = lanes.resolve()
    assert (spec.lane, spec.engine, spec.channel) == ("A", "chromium", None)
    assert spec.headless is True


def test_lane_b_defaults_to_installed_chrome():
    spec = lanes.resolve(lane="B")
    assert (spec.lane, spec.engine, spec.channel) == ("B", "chromium", "chrome")


def test_moz_firefox_is_a_lane_b_channel_on_the_firefox_type():
    """S3, 2026-09-05: `moz-firefox` is present and shipping in
    playwright-python 1.62.0 and is NOT flag-gated at runtime. It launched the
    installed Firefox 154 and drove it end to end, so the Lane B Firefox
    dogfood premise stands and the executable_path contingency was not
    needed."""
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    assert spec.engine == "firefox"
    assert spec.is_bidi_firefox is True


def test_the_bundled_firefox_is_not_the_bidi_firefox():
    """Conflating them would attach S4's gap table to the wrong browser: the
    bundled build is Firefox source plus Playwright's Juggler protocol
    compiled in and carries none of those gaps."""
    spec = lanes.resolve(lane="A", engine="firefox")
    assert spec.is_firefox is True
    assert spec.is_bidi_firefox is False
    assert lanes.capability(spec, "history_navigation") == "ok"


def test_every_firefox_launch_carries_no_remote():
    """The constant, not a default (DESIGN 4.3 and 4.6). Playwright's
    BidiFirefox.defaultArgs omits `-no-remote`, unlike its own Juggler path,
    so a launch can be ADOPTED by a Firefox the user is already running no
    matter which profile directory was named."""
    for spec in (lanes.resolve(lane="A", engine="firefox"),
                 lanes.resolve(lane="B", channel="moz-firefox"),
                 lanes.resolve(lane="B", channel="moz-firefox",
                               headless=False)):
        assert "-no-remote" in spec.args
        assert "-no-remote" in lanes.launch_kwargs(spec, "C:/tmp/p")["args"]
    assert "-no-remote" in FIREFOX_SAFETY_ARGS


def test_chromium_launches_do_not_carry_firefox_args():
    spec = lanes.resolve(lane="A", engine="chromium")
    assert "args" not in lanes.launch_kwargs(spec, "C:/tmp/p")


def test_a_typo_is_an_error_rather_than_a_shrug():
    """chrome-devtools-mcp #2530 silently ignores a mistyped --browserUrl and
    DOWNGRADES attach mode to launch mode. Never degrade silently."""
    with pytest.raises(BadParams):
        lanes.resolve(lane="D")
    with pytest.raises(BadParams):
        lanes.resolve(lane="B", channel="netscape")    # not a channel
    with pytest.raises(BadParams):
        lanes.resolve(lane="A", engine="safari")


def test_lane_c_refuses_while_the_switch_is_off_and_says_which_switch(
        monkeypatch):
    """Lane C was 'not built' until Phase 1 measured its way past the two
    deferred spikes; what it is now is OFF BY DEFAULT, which is a different
    fact and needs a different sentence.

    The refusal has to name the switch, because a human who wants the lane
    cannot reach it from inside a session by design and would otherwise have
    nothing to act on."""
    monkeypatch.delenv(lanes.ENV_EXTENSION, raising=False)
    with pytest.raises(LaneUnsupported) as caught:
        lanes.resolve(lane="C")
    message = str(caught.value)
    assert lanes.ENV_EXTENSION in message
    assert "lane='A'" in message and "lane='B'" in message


def test_lane_c_resolves_when_the_human_turned_it_on(monkeypatch):
    """THE OTHER DIRECTION of the pin above. A switch that refused in both
    states would pass the refusal test on its own, which is how a lane ships
    unreachable."""
    monkeypatch.setenv(lanes.ENV_EXTENSION, "true")
    spec = lanes.resolve(lane="C")
    assert spec.lane == "C"
    assert spec.engine == "extension"
    assert spec.is_extension is True
    # Nothing is launched, so nothing is headless. A spec that claimed
    # headless would put a word in the status line that is not true of the
    # user's own window.
    assert spec.headless is False


def test_real_is_the_same_lane_as_c(monkeypatch):
    """`real` is the spelling the design spec uses at the tool surface and
    the one a human reaches for. An alias is not a silent degrade: it lands
    on the lane the caller obviously meant."""
    monkeypatch.setenv(lanes.ENV_EXTENSION, "true")
    assert lanes.resolve(lane="real") == lanes.resolve(lane="C")


def test_a_misspelled_extension_switch_refuses_rather_than_reading_as_off(
        monkeypatch):
    """The loud-typo rule, one switch along. A 'ture' that read as off would
    leave a human who turned the lane on wondering why it is not there."""
    monkeypatch.setenv(lanes.ENV_EXTENSION, "ture")
    with pytest.raises(BadParams):
        lanes.resolve(lane="C")


def test_lane_c_names_the_four_things_it_cannot_do(monkeypatch):
    """Every row is a fact about what an extension can OBSERVE, and each one
    would otherwise be a silent wrong answer: a confident zero for closed
    shadow roots, a null status read as a 200, a viewport crop read as the
    page, and a synthetic event read as a real one."""
    monkeypatch.setenv(lanes.ENV_EXTENSION, "true")
    spec = lanes.resolve(lane="C")
    assert lanes.capability(spec, "closed_shadow_count") == "unsupported"
    assert lanes.capability(spec, "navigation_status") == "unsupported"
    assert lanes.capability(spec, "full_page_screenshot") == "unsupported"
    # A COST, not a gap. The events work; they carry isTrusted: false and the
    # lane says so on every act rather than refusing to act at all.
    assert lanes.capability(spec, "trusted_events") == "cost"


def test_lane_c_keeps_every_capability_the_driver_gaps_were_about(monkeypatch):
    """The other direction: the extension column is not a shorter lane. The
    S4 gaps are BiDi driver gaps, and a lane with no driver does not have
    them, so nothing may be marked unsupported here by inheritance."""
    monkeypatch.setenv(lanes.ENV_EXTENSION, "true")
    spec = lanes.resolve(lane="C")
    for name in ("response_body_read", "request_body_read",
                 "history_navigation", "downloads", "http_auth"):
        assert lanes.capability(spec, name) == "ok", name


# ------------------------------------------------------- the capabilities


def test_the_two_measured_gaps_are_unsupported_on_firefox_bidi():
    """Two of the three DOCUMENTED gaps were refuted by measurement and two
    real ones were found. Both real ones fail silently or misleadingly in the
    driver, which is the failure class this product argues against, so both
    become loud refusals here."""
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    assert lanes.capability(spec, "request_body_read") == "unsupported"
    assert lanes.capability(spec, "history_navigation") == "unsupported"


def test_the_refuted_gaps_are_recorded_as_working():
    """Response bodies, downloads, and HTTP auth all work on Firefox/BiDi.
    The research's hole list was stale and the table replaces it."""
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    for capability in ("response_body_read", "downloads", "http_auth",
                       "header_override_across_redirect",
                       "click_in_css_transform", "locale_timezone_emulation"):
        assert lanes.capability(spec, capability) == "ok"


def test_request_bodies_are_write_yes_read_no():
    """The honest capability row. Writing works: route.continue_(post_data)
    was accepted and the fixture server received the tampered body verbatim."""
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    assert lanes.capability(spec, "request_body_write") == "ok"
    assert lanes.capability(spec, "request_body_read") == "unsupported"


def test_a_cost_is_not_a_gap():
    """page.pdf() works on Firefox/BiDi at 8.7 s against Chromium's 0.2 s.
    An operation that works and is slow is a different fact from one that does
    not work, and collapsing the two is how a capability table stops being
    useful. A cost row never refuses."""
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    assert lanes.capability(spec, "pdf_export") == "cost"
    lanes.require(spec, "pdf_export")            # must not raise
    report = lanes.capabilities_report(spec)
    assert any(row["capability"] == "pdf_export"
               for row in report["degraded_with_a_cost"])


def test_require_refuses_loudly_and_names_the_lane_that_works():
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    with pytest.raises(LaneUnsupported) as caught:
        lanes.require(spec, "history_navigation")
    message = str(caught.value)
    assert "Firefox/BiDi" in message
    assert "page.url goes stale" in message
    assert "Chromium supports back and forward normally" in message
    with pytest.raises(LaneUnsupported) as caught:
        lanes.require(spec, "request_body_read")
    assert "relaunch on Lane A or Lane B Chrome" in str(caught.value)


def test_chromium_supports_everything_the_table_lists():
    """Every S4 probe passed on Chromium, so a Chromium row that is not `ok`
    would mean the table drifted from the measurement."""
    spec = lanes.resolve(lane="A", engine="chromium")
    for capability in lanes.CAPABILITIES:
        assert lanes.capability(spec, capability) == "ok"
    report = lanes.capabilities_report(spec)
    assert report["unsupported"] == []


def test_the_capabilities_report_states_the_url_trust_rule():
    """`page.url` is never trusted after a history traversal on Firefox/BiDi,
    so no anchor logic, wait_for_url, or load-state wait may derive from it
    there (DESIGN 4.5a rule 2)."""
    firefox = lanes.capabilities_report(
        lanes.resolve(lane="B", channel="moz-firefox"))
    assert "not trusted after a history traversal" in firefox["url_trust"]
    chromium = lanes.capabilities_report(lanes.resolve(lane="A"))
    assert chromium["url_trust"] == "page.url is trusted"


def test_about_pages_are_unavailable_on_firefox_bidi():
    """S3: `Navigation to "about:support" is not allowed in this context`, so
    provenance comes from the process table and the user-agent string."""
    spec = lanes.resolve(lane="B", channel="moz-firefox")
    assert lanes.capability(spec, "about_pages") == "unsupported"


def test_an_unknown_capability_is_a_bad_param_not_a_default():
    with pytest.raises(BadParams):
        lanes.capability(lanes.resolve(), "teleportation")


# ------------------------------------------------- aliases and detection


def test_firefox_is_accepted_as_a_spelling_of_moz_firefox():
    """Field log 2 item U18. `moz-firefox` is genuinely undocumented
    upstream, the tester's first guess was `firefox`, and the round trip to
    a refusal that listed the real names was avoidable. The alias lands on
    the same lane; it does not invent one."""
    spec = lanes.resolve(lane="B", channel="firefox")
    assert spec.channel == "moz-firefox"
    assert spec.is_bidi_firefox is True
    # And it is a real Firefox launch, so it carries the safety flag.
    assert spec.args == FIREFOX_SAFETY_ARGS


def test_the_sibling_spellings_land_too():
    assert lanes.resolve(lane="B", channel="edge").channel == "msedge"
    assert lanes.resolve(lane="B",
                         channel="firefox-nightly").channel         == "moz-firefox-nightly"
    assert lanes.resolve(lane="B",
                         channel="google-chrome").channel == "chrome"


def test_an_alias_does_not_soften_a_real_typo():
    """The alias table is a spelling map, not a fuzzy matcher: a name nobody
    would call a browser still refuses, and the refusal now lists both the
    real channels and the accepted spellings."""
    with pytest.raises(BadParams) as caught:
        lanes.resolve(lane="B", channel="firefx")
    message = str(caught.value)
    assert "moz-firefox" in message
    assert "firefox" in message


def test_detection_reports_a_lane_for_every_browser_it_finds():
    """Whatever this machine has, each row has to be addressable: the lane
    string in the report is the lane a caller would pass."""
    for browser in lanes.detect_installed(refresh=True):
        assert browser["lane"] == f'B({browser["channel"]})'
        spec = lanes.resolve(lane="B", channel=browser["channel"])
        assert spec.label == browser["lane"]


def test_detection_is_cached_after_the_first_look():
    first = lanes.detect_installed(refresh=True)
    assert lanes.detect_installed() is first


def test_the_recommendation_steers_and_never_switches(monkeypatch):
    """Item 44, the user's own ask, and the standing doctrine: bundled
    Chromium is the vanilla default, an installed stock Firefox is the
    research default. The report says so and no code path reads it back."""
    monkeypatch.setattr(lanes, "_DETECTED", [
        {"name": "Firefox", "channel": "moz-firefox",
         "path": "/x/firefox", "lane": "B(moz-firefox)"}])
    report = lanes.recommended_lane()
    assert report["default"]["lane"] == "A(chromium)"
    assert report["research"]["lane"] == "B(moz-firefox)"
    assert "steering only" in report["note"]
    assert [b["lane"] for b in report["installed"]] == ["B(moz-firefox)"]


def test_with_no_installed_firefox_the_research_lane_falls_back_to_bundled(
        monkeypatch):
    """The fallback still names a Firefox, because the field campaign's
    finding is about the engine rather than about who installed it, and it
    says which one would be better."""
    monkeypatch.setattr(lanes, "_DETECTED", [
        {"name": "Edge", "channel": "msedge", "path": "/x/edge",
         "lane": "B(msedge)"}])
    report = lanes.recommended_lane()
    assert report["research"]["lane"] == "A(firefox)"
    assert "no installed Firefox was found" in report["research"]["why"]
