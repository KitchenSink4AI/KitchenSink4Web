"""Where the lane database meets `navigate`: the refusal, the one automatic
choice, and the outcomes that are deliberately not learned from.

The pin that protects the doctrine is `test_a_believed_bad_lane_never_picks
_when_a_session_is_open`. Auto-switching the lane of a session that is
already running would discard cookies, loaded auth, open pages, and the
session's capability table, which is the silent degrade `resolve()` exists to
refuse. The database advises everywhere and decides in exactly one place,
where there is nothing yet to lose.
"""

from __future__ import annotations

from datetime import date

import pytest

from kitchensink4web.engine import lanedb, lanes
from kitchensink4web.ops import lite

CHROME = "chromium:cdp:headless"
FIREFOX_BIDI = "firefox:bidi:headless"


class _FakeSpec:
    def __init__(self, engine="chromium", channel=None, headless=True):
        self.engine = engine
        self.channel = channel
        self.headless = headless
        self.lane = "A"
        self.label = f"A({engine})"

    @property
    def is_bidi_firefox(self):
        return self.channel in lanes.FIREFOX_CHANNELS


class _FakeSession:
    def __init__(self, spec=None):
        self.spec = spec or _FakeSpec()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(lanedb, "STATE_DIR", tmp_path)
    monkeypatch.delenv("KS4WEB_LANE_DB", raising=False)
    monkeypatch.delenv("KS4WEB_LANE_AUTOPICK", raising=False)
    monkeypatch.setenv("KS4WEB_LANE_DB_FLUSH_S", "0")
    lanedb.reset_for_tests()
    yield lanedb
    lanedb.reset_for_tests()


# ------------------------------------------------- the refusal that learned


def test_the_hint_names_the_measured_lane_with_its_date(db):
    db.record("walled.example.org", FIREFOX_BIDI, "ok")
    hint = lite._lane_hint(_FakeSession(), "https://walled.example.org/page",
                           "bot-wall-or-captcha")
    assert "walled.example.org" in hint
    assert FIREFOX_BIDI in hint
    assert date.today().isoformat() in hint
    assert 'lane="B:moz-firefox"' in hint


def test_an_empty_database_falls_back_to_the_shipped_sentence(db):
    """It ships empty on every machine, so this is what a new user sees."""
    hint = lite._lane_hint(_FakeSession(), "https://unknown.example.org/",
                           "bot-wall-or-captcha")
    assert "often serve" in hint
    assert "B:moz-firefox" in hint


def test_when_every_lane_failed_the_refusal_stops_naming_lanes(db):
    for key in (CHROME, FIREFOX_BIDI, "firefox:juggler:headless"):
        db.record("hopeless.example.org", key, "blocked")
    hint = lite._lane_hint(_FakeSession(), "https://hopeless.example.org/",
                           "bot-wall-or-captcha")
    assert "switching lanes is not the move" in hint
    assert "B:moz-firefox" not in hint


def test_a_stale_good_record_does_not_become_a_recommendation(db, tmp_path,
                                                              monkeypatch):
    import json
    (tmp_path / lanedb.DB_NAME).write_text(json.dumps(
        {"schema": 1, "hosts": {"aged.example.org": {FIREFOX_BIDI: {
            "ok": 1, "blocked": 0, "dropped": 0, "last": "ok",
            "last_ok": "2020-01-01", "last_bad": None}}}}), encoding="utf-8")
    hint = lite._lane_hint(_FakeSession(), "https://aged.example.org/",
                           "bot-wall-or-captcha")
    assert "2020-01-01" not in hint


def test_a_verdict_that_is_not_about_the_lane_gets_no_lane_sentence(db):
    for wall in ("auth-wall", "rate-limited", None):
        assert lite._lane_hint(_FakeSession(), "https://h.example.org/",
                               wall) == ""


def test_the_lane_walls_are_the_three_that_describe_a_lane():
    assert lite._LANE_WALLS == frozenset({
        "bot-wall-or-captcha", "forbidden-challenge",
        "service-unavailable-or-bot-wall"})
    assert "auth-wall" not in lite._LANE_WALLS
    assert "rate-limited" not in lite._LANE_WALLS


# ------------------------------------------------------- what is NOT learned


def test_only_connection_level_causes_count_as_a_drop():
    assert "err_connection_reset" in lite._DROP_CAUSES
    assert "err_connection_closed" in lite._DROP_CAUSES
    assert "ns_error_net_reset" in lite._DROP_CAUSES
    for never in ("err_name_not_resolved", "err_internet_disconnected",
                  "err_network_changed", "ns_error_offline", "err_cert_",
                  "ssl_error", "err_timed_out", "err_connection_refused"):
        assert never not in lite._DROP_CAUSES, never


def test_every_drop_cause_is_a_cause_the_driver_table_knows():
    known = {marker for marker, _cause in lite._NET_CAUSES}
    assert lite._DROP_CAUSES <= known


# ------------------------------------------------------- the one auto-pick


def test_no_url_no_pick(db):
    assert lite._autopick(None) is None


def test_an_empty_database_never_picks(db):
    assert lite._autopick("https://unknown.example.org/") is None


def test_a_good_record_alone_never_picks(db, monkeypatch):
    """Condition 4: the lane that would otherwise open has to be one this
    host already turned away. A site that serves everything gets the
    default."""
    monkeypatch.setattr(lanes, "lane_available", lambda key: True)
    db.record("fine.example.org", FIREFOX_BIDI, "ok")
    assert lite._autopick("https://fine.example.org/") is None


def test_the_pick_fires_when_all_four_conditions_hold(db, monkeypatch):
    monkeypatch.setattr(lanes, "lane_available", lambda key: True)
    db.record("split.example.org", CHROME, "blocked")
    db.record("split.example.org", FIREFOX_BIDI, "ok")
    picked = lite._autopick("https://split.example.org/article")
    assert picked["open"] == {"lane": "B", "channel": "moz-firefox",
                              "headless": True}
    assert "split.example.org" in picked["why"]
    assert "already open is never switched" in picked["why"]
    assert "KS4WEB_LANE_AUTOPICK=0" in picked["why"]


def test_a_lane_this_machine_cannot_open_is_not_picked(db, monkeypatch):
    monkeypatch.setattr(lanes, "lane_available", lambda key: False)
    db.record("split.example.org", CHROME, "blocked")
    db.record("split.example.org", FIREFOX_BIDI, "ok")
    assert lite._autopick("https://split.example.org/") is None


def test_a_sibling_answer_never_drives_the_pick(db, monkeypatch):
    monkeypatch.setattr(lanes, "lane_available", lambda key: True)
    db.record("split.example.org", CHROME, "blocked")
    db.record("split.example.org", "firefox:juggler:headless", "ok")
    picked = lite._autopick("https://split.example.org/")
    assert picked is not None
    assert picked["open"]["lane"] == "A", "the DIRECT hit, not its sibling"


def test_the_kill_switch_stops_the_pick_dead(db, monkeypatch):
    monkeypatch.setenv("KS4WEB_LANE_AUTOPICK", "0")
    monkeypatch.setattr(lanes, "lane_available", lambda key: True)
    db.record("split.example.org", CHROME, "blocked")
    db.record("split.example.org", FIREFOX_BIDI, "ok")
    assert lite._autopick("https://split.example.org/") is None


def test_an_intranet_host_never_reaches_the_pick(db, monkeypatch):
    monkeypatch.setattr(lanes, "lane_available", lambda key: True)
    assert lite._autopick("http://wiki.corp.local/page") is None
    assert lite._autopick("http://127.0.0.1:8931/") is None


def test_a_believed_bad_lane_never_picks_when_a_session_is_open(db,
                                                                monkeypatch):
    """THE DOCTRINE PIN. `_autopick` is reachable from exactly one place, the
    branch where navigate has no session at all. A session that exists is a
    browser process with cookies, loaded auth, open pages, and a capability
    table, and nothing in this feature may take it away."""
    import ast
    import inspect
    source = inspect.getsource(lite.navigate)
    tree = ast.parse(source.lstrip())
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and getattr(node.func, "id", None) == "_autopick"]
    assert len(calls) == 1, "auto-pick has exactly one call site"
    whole = inspect.getsource(lite)
    assert whole.count("_autopick(") == 2, \
        "the definition and the one call, and nothing else"


def test_the_lanes_action_is_a_read_surface_by_default(db):
    out = lite._lanes_action(site=None, op=None, path=None)
    assert out["lane_database"]["learning"] == "learning"
    assert sorted(out["lane_keys"]) == sorted(lanedb.LANE_KEYS)


def test_the_lanes_report_names_the_dates_and_the_counts(db):
    db.record("seen.example.org", CHROME, "blocked", vendor="Cloudflare")
    out = lite._lanes_action(site="seen.example.org", op="show", path=None)
    row = out["lanes"][0]
    assert row["lane_key"] == CHROME
    assert row["vendor"] == "Cloudflare"
    assert row["last_bad"] == date.today().isoformat()


def test_forgetting_everything_is_one_call(db):
    db.record("seen.example.org", CHROME, "ok")
    out = lite._lanes_action(site="all", op="forget", path=None)
    assert out["forgot"] == "all"
    assert lite._lanes_action(site=None, op=None, path=None) \
        ["lane_database"]["hosts"] == 0
