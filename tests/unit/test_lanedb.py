"""The learned lane database: what it records, what it refuses to record,
and what it survives.

Every pin here was written before the module existed and fails against
45fc986. The privacy pins are the ones that matter most: a file mapping
hostnames to "you went there" is a coarse browsing history, and the rules
that keep a corporate hostname or a URL path out of it have to be mechanical
rather than careful, which means they have to be tested rather than
documented.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from kitchensink4web.engine import lanedb, lanes

CHROME = "chromium:cdp:headless"
FIREFOX = "firefox:bidi:headless"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh database in a throwaway state directory, learning on."""
    monkeypatch.setattr(lanedb, "STATE_DIR", tmp_path)
    monkeypatch.delenv("KS4WEB_LANE_DB", raising=False)
    monkeypatch.delenv("KS4WEB_LANE_DB_TTL_DAYS", raising=False)
    monkeypatch.delenv("KS4WEB_LANE_DB_MAX_HOSTS", raising=False)
    monkeypatch.setenv("KS4WEB_LANE_DB_FLUSH_S", "0")
    lanedb.reset_for_tests()
    yield lanedb
    lanedb.reset_for_tests()


def _stamp(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _write(tmp_path, payload) -> None:
    (tmp_path / lanedb.DB_NAME).write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8")


# ------------------------------------------------------------- the lane key


def test_the_lane_key_is_a_class_not_a_channel():
    """A user driving installed Chrome and a user on bundled Chromium produce
    the SAME key, because the thing that gets them turned away is the same."""
    bundled = lanes.resolve(lane="A", engine="chromium")
    installed = lanes.resolve(lane="B", channel="chrome")
    assert lanes.lane_key(bundled) == lanes.lane_key(installed) == CHROME


def test_the_two_firefox_backends_are_different_keys():
    bundled = lanes.lane_key(lanes.resolve(lane="A", engine="firefox"))
    branded = lanes.lane_key(lanes.resolve(lane="B", channel="moz-firefox"))
    assert bundled == "firefox:juggler:headless"
    assert branded == "firefox:bidi:headless"
    assert bundled != branded


def test_headed_and_headless_are_different_keys():
    headed = lanes.lane_key(lanes.resolve(lane="A", headless=False))
    assert headed == "chromium:cdp:headed"
    assert headed in lanedb.LANE_KEYS


def test_every_key_the_resolver_can_produce_is_in_the_vocabulary():
    for lane, engine, channel in (("A", "chromium", None),
                                  ("A", "firefox", None),
                                  ("A", "webkit", None),
                                  ("B", None, "chrome"),
                                  ("B", None, "msedge"),
                                  ("B", None, "moz-firefox")):
        for headless in (True, False):
            spec = lanes.resolve(lane=lane, engine=engine, channel=channel,
                                 headless=headless)
            assert lanes.lane_key(spec) in lanedb.LANE_KEYS


def test_siblings_share_an_engine_and_never_cross_one():
    assert lanedb.siblings(FIREFOX) == ["firefox:juggler:headless"]
    assert CHROME not in lanedb.siblings(FIREFOX)
    assert lanedb.siblings("chromium:cdp:headed") == []


# ------------------------------------------------------ learning and belief


def test_a_block_is_recorded_with_its_vendor_and_wall(db):
    assert db.record("https://blocked.example.org/x", CHROME, "blocked",
                     vendor="Cloudflare", wall="bot-wall-or-captcha")
    got = db.lookup("blocked.example.org", CHROME)
    assert got["blocked"] == 1 and got["ok"] == 0
    assert got["last"] == "blocked"
    assert got["last_bad"] == date.today().isoformat()
    assert got["vendor"] == "Cloudflare"
    assert got["belief"] == "believed_bad"


def test_a_success_is_recorded(db):
    db.record("https://served.example.org/", FIREFOX, "ok")
    got = db.lookup("served.example.org", FIREFOX)
    assert got["ok"] == 1 and got["belief"] == "believed_good"
    assert got["last_ok"] == date.today().isoformat()


def test_one_success_after_three_blocks_clears_the_warning(db):
    for _ in range(3):
        db.record("flaky.example.org", CHROME, "blocked")
    db.record("flaky.example.org", CHROME, "ok")
    got = db.lookup("flaky.example.org", CHROME)
    assert got["belief"] == "believed_good"
    assert got["blocked"] == 3, "the history stays visible"


def test_the_www_prefix_is_stripped_and_the_walk_goes_up_not_down(db):
    db.record("https://www.news.example.org/", CHROME, "blocked")
    assert db.lookup("news.example.org", CHROME)["host"] == "news.example.org"
    # A subdomain inherits the parent's answer, marked as not exact.
    child = db.lookup("edition.news.example.org", CHROME)
    assert child["host"] == "news.example.org" and child["exact_host"] is False
    # The parent NEVER inherits the child's.
    db.record("scholar.search.example.org", CHROME, "blocked")
    assert db.lookup("search.example.org", CHROME) is None


def test_a_sibling_lane_answers_and_says_that_it_did(db):
    db.record("split.example.org", "firefox:juggler:headless", "ok")
    got = db.lookup("split.example.org", FIREFOX)
    assert got["from_sibling_lane"] is True
    assert got["answered_by"] == "firefox:juggler:headless"
    assert got not in db.good_lanes("split.example.org"), \
        "a sibling answer advises and never drives a choice"


def test_all_lanes_failed_is_only_true_when_something_is_known(db):
    assert db.all_lanes_failed("nothing.example.org") is False
    db.record("walled.example.org", CHROME, "blocked")
    db.record("walled.example.org", FIREFOX, "blocked")
    assert db.all_lanes_failed("walled.example.org") is True
    db.record("walled.example.org", FIREFOX, "ok")
    assert db.all_lanes_failed("walled.example.org") is False


# ------------------------------------------------ staleness, decay, the cap


def test_a_record_past_the_ttl_is_reported_stale(db, tmp_path, monkeypatch):
    _write(tmp_path, {"schema": 1, "hosts": {"old.example.org": {
        CHROME: {"ok": 0, "blocked": 2, "dropped": 0, "last": "blocked",
                 "last_ok": None, "last_bad": _stamp(90)}}}})
    got = db.lookup("old.example.org", CHROME)
    assert got["stale"] is True and got["measured_days_ago"] == 90
    monkeypatch.setenv("KS4WEB_LANE_DB_TTL_DAYS", "365")
    lanedb.reset_for_tests()
    assert db.lookup("old.example.org", CHROME)["stale"] is False


def test_old_evidence_halves_before_the_next_verdict_lands(db, tmp_path):
    _write(tmp_path, {"schema": 1, "hosts": {"aged.example.org": {
        CHROME: {"ok": 0, "blocked": 4, "dropped": 0, "last": "blocked",
                 "last_ok": None, "last_bad": _stamp(45)}}}})
    db.record("aged.example.org", CHROME, "blocked")
    assert db.lookup("aged.example.org", CHROME)["blocked"] == 3   # 4//2 + 1


def test_recent_evidence_does_not_decay(db, tmp_path):
    _write(tmp_path, {"schema": 1, "hosts": {"fresh.example.org": {
        CHROME: {"ok": 0, "blocked": 4, "dropped": 0, "last": "blocked",
                 "last_ok": None, "last_bad": _stamp(10)}}}})
    db.record("fresh.example.org", CHROME, "blocked")
    assert db.lookup("fresh.example.org", CHROME)["blocked"] == 5


def test_the_cap_evicts_the_oldest_evidence_first(db, monkeypatch):
    monkeypatch.setenv("KS4WEB_LANE_DB_MAX_HOSTS", "3")
    for i in range(5):
        db.record(f"host{i}.example.org", CHROME, "ok")
    remaining = {row for row in db.export(scope="all")["hosts"]}
    assert len(remaining) == 3
    assert "host4.example.org" in remaining


# ---------------------------------------------------------------- what is
# NOT recorded. The contract in `record()` is the whole feature's honesty.


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "10.0.0.5", "192.168.1.1", "intranet",
    "wiki.corp.local", "build.internal", "printer.lan", "box.home.arpa",
    "::1", "[::1]",
])
def test_a_private_host_is_never_written(db, host):
    assert db.record(host, CHROME, "blocked") is False
    assert db.lookup(host, CHROME) is None
    assert db.export(scope="all")["hosts"] == {}


def test_a_non_standard_port_is_never_written(db):
    assert db.record("https://fixture.example.org:8931/", CHROME, "ok") is False
    assert db.record("http://127.0.0.1:8931/page", CHROME, "ok") is False
    assert db.export(scope="all")["hosts"] == {}


@pytest.mark.parametrize("url", [
    "file:///C:/secrets.txt", "data:text/html,<h1>x", "about:blank",
    "chrome://settings", "",
])
def test_a_non_web_scheme_is_never_written(db, url):
    assert db.record(url, CHROME, "ok") is False


def test_nothing_below_the_host_reaches_the_file(db, tmp_path):
    db.record("https://h.example.org/secret/path?token=abc#frag", CHROME, "ok")
    db.flush()
    body = (tmp_path / lanedb.DB_NAME).read_text(encoding="utf-8")
    for leak in ("secret", "path", "token", "abc", "frag", "https"):
        assert leak not in body, f"{leak!r} reached the lane database"
    assert "h.example.org" in body


def test_no_field_anywhere_carries_a_time_of_day(db, tmp_path):
    db.record("dated.example.org", CHROME, "blocked", vendor="Cloudflare")
    db.record("dated.example.org", FIREFOX, "ok")
    db.flush()
    payload = json.loads((tmp_path / lanedb.DB_NAME).read_text("utf-8"))
    for lanes_ in payload["hosts"].values():
        for entry in lanes_.values():
            for field in ("last_ok", "last_bad"):
                stamp = entry.get(field)
                assert stamp is None or lanedb._DATE.match(stamp)
                assert stamp is None or ":" not in stamp


def test_an_unknown_lane_key_is_refused(db):
    assert db.record("h.example.org", "chromium:cdp:invisible", "ok") is False
    assert db.record("h.example.org", "'; DROP TABLE", "ok") is False


def test_an_unknown_outcome_is_refused(db):
    assert db.record("h.example.org", CHROME, "auth-wall") is False
    assert db.record("h.example.org", CHROME, "rate-limited") is False


# ------------------------------------------------------------ off switches


def test_the_off_switch_creates_no_file_and_reads_nothing(db, tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("KS4WEB_LANE_DB", "off")
    lanedb.reset_for_tests()
    assert db.record("h.example.org", CHROME, "blocked") is False
    assert db.lookup("h.example.org", CHROME) is None
    db.flush()
    assert not (tmp_path / lanedb.DB_NAME).exists()
    assert db.status()["learning"] == "off"


def test_read_mode_reads_an_existing_file_and_never_writes(db, tmp_path,
                                                           monkeypatch):
    _write(tmp_path, {"schema": 1, "hosts": {"known.example.org": {
        CHROME: {"ok": 0, "blocked": 1, "dropped": 0, "last": "blocked",
                 "last_ok": None, "last_bad": _stamp(1)}}}})
    before = (tmp_path / lanedb.DB_NAME).read_bytes()
    monkeypatch.setenv("KS4WEB_LANE_DB", "read")
    lanedb.reset_for_tests()
    assert db.lookup("known.example.org", CHROME)["blocked"] == 1
    assert db.record("new.example.org", CHROME, "ok") is False
    db.flush()
    assert (tmp_path / lanedb.DB_NAME).read_bytes() == before


def test_a_typo_in_the_switch_resolves_to_off_and_says_so(db, monkeypatch):
    monkeypatch.setenv("KS4WEB_LANE_DB", "learnn")
    lanedb.reset_for_tests()
    assert lanedb.mode() == "off"
    note = lanedb.take_note()
    assert note and "learnn" in note


def test_a_read_only_server_grade_never_learns(db, monkeypatch):
    from kitchensink4web.policy import readonly
    readonly.apply("browse")
    try:
        assert lanedb.mode() == "read"
        assert db.record("h.example.org", CHROME, "ok") is False
    finally:
        readonly.apply(False)


# -------------------------------------- corrupt, hostile, impossible files


@pytest.mark.parametrize("body", [
    "{", "", "not json at all", "[]", '"a string"', "42", "null",
    '{"schema": "one", "hosts": {}}', '{"hosts": {}}',
    '{"schema": 1}', '{"schema": 1, "hosts": []}',
])
def test_a_spoiled_file_is_quarantined_and_learning_restarts(db, tmp_path,
                                                             body):
    _write(tmp_path, body)
    assert db.lookup("anything.example.org", CHROME) is None
    assert db.record("after.example.org", CHROME, "ok") is True
    assert db.take_note(), "the degraded state is reported once"
    spoiled = list(tmp_path.glob("lanes.corrupt-*.json"))
    assert len(spoiled) == 1
    db.flush()
    assert db.lookup("after.example.org", CHROME)["ok"] == 1


def test_garbage_records_are_dropped_and_the_good_ones_survive(db, tmp_path):
    _write(tmp_path, {"schema": 1, "hosts": {
        "good.example.org": {CHROME: {"ok": 2, "blocked": 0, "dropped": 0,
                                  "last": "ok", "last_ok": _stamp(1),
                                  "last_bad": None}},
        "strings.example.org": {CHROME: {"ok": "two", "blocked": 0, "dropped": 0,
                                     "last": "ok"}},
        "negative.example.org": {CHROME: {"ok": -5, "blocked": 0, "dropped": 0,
                                      "last": "ok"}},
        "badword.example.org": {CHROME: {"ok": 1, "blocked": 0, "dropped": 0,
                                     "last": "yesterday"}},
        "baddate.example.org": {CHROME: {"ok": 1, "blocked": 0, "dropped": 0,
                                     "last": "ok", "last_ok": "yesterday"}},
        "badlane.example.org": {"chromium:cdp:invisible": {"ok": 1, "blocked": 0,
                                                       "dropped": 0}},
        ("x" * 400 + ".example.org"): {CHROME: {"ok": 1, "blocked": 0,
                                            "dropped": 0, "last": "ok"}},
        "localhost": {CHROME: {"ok": 9, "blocked": 0, "dropped": 0,
                               "last": "ok"}},
    }})
    assert db.lookup("good.example.org", CHROME)["ok"] == 2
    for host in ("strings.example.org", "negative.example.org", "badword.example.org",
                 "baddate.example.org", "badlane.example.org", "localhost"):
        assert db.lookup(host, CHROME) is None, host
    assert db.status()["hosts"] == 1


def test_a_newer_schema_is_read_and_never_rewritten(db, tmp_path):
    _write(tmp_path, {"schema": 999, "hosts": {"future.example.org": {
        CHROME: {"ok": 3, "blocked": 0, "dropped": 0, "last": "ok",
                 "last_ok": _stamp(1), "last_bad": None}}}})
    before = (tmp_path / lanedb.DB_NAME).read_bytes()
    assert db.lookup("future.example.org", CHROME)["ok"] == 3
    assert db.record("new.example.org", CHROME, "ok") is False
    db.flush()
    assert (tmp_path / lanedb.DB_NAME).read_bytes() == before
    assert db.take_note(), "the read-only fallback is reported"


def test_an_absurd_file_is_not_parsed(db, tmp_path, monkeypatch):
    monkeypatch.setenv("KS4WEB_LANE_DB_MAX_BYTES", "2048")
    lanedb.reset_for_tests()
    _write(tmp_path, {"schema": 1, "hosts": {
        f"h{i}.example.org": {CHROME: {"ok": 1, "blocked": 0, "dropped": 0,
                                   "last": "ok"}} for i in range(200)}})
    assert db.lookup("h1.example.org", CHROME) is None
    assert list(tmp_path.glob("lanes.corrupt-*.json"))


def test_an_unwritable_state_directory_never_raises(db, tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr(lanedb, "STATE_DIR", tmp_path / "nope" / "deeper")
    lanedb.reset_for_tests()

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(lanedb.Path, "mkdir", boom)
    assert db.record("h.example.org", CHROME, "ok") is True   # in memory
    assert db.flush() is False
    assert db.take_note()


# ------------------------------------------------- sharing and forgetting


def test_the_default_export_carries_only_the_bad_rows(db):
    db.record("served.example.org", CHROME, "ok")
    db.record("walled.example.org", CHROME, "blocked", vendor="Cloudflare")
    default = db.export()
    assert list(default["hosts"]) == ["walled.example.org"]
    every = db.export(scope="all")
    assert set(every["hosts"]) == {"served.example.org", "walled.example.org"}
    assert "path" not in json.dumps(default)


def test_import_is_a_dry_run_until_it_is_asked_twice(db):
    payload = {"format": lanedb.EXPORT_FORMAT, "schema": 1, "hosts": {
        "shared.example.org": {CHROME: {"ok": 0, "blocked": 2, "dropped": 0,
                                    "last": "blocked", "last_ok": None,
                                    "last_bad": _stamp(2)}}}}
    dry = db.import_payload(payload, label="friend")
    assert dry["merged"] is False and dry["new_hosts"] == 1
    assert db.lookup("shared.example.org", CHROME) is None
    real = db.import_payload(payload, label="friend", dry_run=False)
    assert real["merged"] is True
    got = db.lookup("shared.example.org", CHROME)
    assert got["blocked"] == 2 and got["source"] == "imported:friend"


def test_counts_add_and_a_local_observation_outranks_an_import(db):
    db.record("both.example.org", CHROME, "ok")
    db.import_payload({"schema": 1, "hosts": {"both.example.org": {
        CHROME: {"ok": 0, "blocked": 3, "dropped": 0, "last": "blocked",
                 "last_ok": None, "last_bad": date.today().isoformat()}}}},
        label="friend", dry_run=False)
    got = db.lookup("both.example.org", CHROME)
    assert got["ok"] == 1 and got["blocked"] == 3
    assert got["last"] == "ok", "a same-date tie goes to the local record"


def test_forgetting_one_import_leaves_the_local_records(db):
    db.record("mine.example.org", CHROME, "blocked")
    db.import_payload({"schema": 1, "hosts": {"theirs.example.org": {
        CHROME: {"ok": 0, "blocked": 1, "dropped": 0, "last": "blocked",
                 "last_ok": None, "last_bad": _stamp(1)}}}},
        label="x", dry_run=False)
    db.forget(source="imported:x")
    assert db.lookup("theirs.example.org", CHROME) is None
    assert db.lookup("mine.example.org", CHROME)["blocked"] == 1


def test_forgetting_everything_deletes_the_file(db, tmp_path):
    db.record("h.example.org", CHROME, "ok")
    db.flush()
    assert (tmp_path / lanedb.DB_NAME).exists()
    out = db.forget(all_records=True)
    assert out["file_deleted"] is True
    assert not (tmp_path / lanedb.DB_NAME).exists()
    assert db.status()["hosts"] == 0


def test_two_processes_both_keep_their_learning(db, tmp_path):
    """The flush is a read-modify-write, because several KS4Web processes
    share one state directory and a last-write-wins flush would silently lose
    another session's learning."""
    db.record("first.example.org", CHROME, "ok")
    db.flush()
    other = {"schema": 1, "hosts": {"second.example.org": {
        FIREFOX: {"ok": 1, "blocked": 0, "dropped": 0, "last": "ok",
                  "last_ok": date.today().isoformat(), "last_bad": None}}}}
    existing = json.loads((tmp_path / lanedb.DB_NAME).read_text("utf-8"))
    existing["hosts"].update(other["hosts"])
    _write(tmp_path, existing)
    db.record("third.example.org", CHROME, "ok")
    db.flush()
    on_disk = json.loads((tmp_path / lanedb.DB_NAME).read_text("utf-8"))
    assert set(on_disk["hosts"]) == {"first.example.org", "second.example.org",
                                     "third.example.org"}
