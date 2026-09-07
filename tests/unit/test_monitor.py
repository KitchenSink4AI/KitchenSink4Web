"""Proactive page monitoring (#8): the state model and the honesty contract.

The lifecycle spec §8.1, written RED against `45fc986`. The pin to read
first is M-1, because it is the whole feature: a monitor that could not
check must never report that nothing changed. Everything else here is the
machinery that makes that answer cheap to give.

Nothing in this file opens a browser. The scheduler and the checks live in
`tests/browser/test_monitor_live.py`.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from kitchensink4web import envelope, errors
from kitchensink4web.engine import monitors as _monitors
from kitchensink4web.engine import session as _session
from kitchensink4web.ops import monitor as _monitor_ops
from kitchensink4web.policy import readonly

HOUR = 3600.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "monitors.json"
    monkeypatch.setattr(_monitors, "STORE", _monitors.MonitorStore(path))
    _session.MANAGER.sessions.clear()
    yield _monitors.STORE
    _session.MANAGER.sessions.clear()


def _call(**kwargs) -> dict:
    return asyncio.run(_monitor_ops.monitor(**kwargs))


def _refuses(code: str, **kwargs) -> str:
    with pytest.raises(errors.WebMcpError) as caught:
        _call(**kwargs)
    assert envelope.classify(caught.value) == code, (
        f"expected {code}, got {envelope.classify(caught.value)}: "
        f"{caught.value}")
    return str(caught.value)


def _planted(store, **overrides) -> dict:
    """One monitor record placed straight into the store, so the state
    model can be driven without a browser."""
    now = time.time()
    record = {
        "id": overrides.pop("id", "m1"),
        "label": "planted",
        "url": "https://example.org/thing",
        "origin_verdict_at_create": "allowed",
        "condition": "selector_count",
        "value": "li",
        "selector": None,
        "interval_minutes": 30,
        "created": now - HOUR,
        "created_by_pid": _monitors.os.getpid(),
        "state": "active",
        "baseline": {"kind": "count", "value": 14, "taken": now - HOUR},
        "last_value": {"kind": "count", "value": 14},
        "last_success_at": now - 60,
        "last_attempt_at": now - 60,
        "last_attempt_ok": True,
        "last_error": None,
        "consecutive_failures": 0,
        "checks_run": 2,
        "checks_missed": 0,
        "last_reported_at": now - HOUR,
        "next_due": now + 60,
        "history": [],
    }
    record.update(overrides)
    store.add(record)
    return record


# --------------------------------------------------------------------- M-1

def test_m1_a_failed_last_check_is_stale_never_unchanged(store):
    """THE INTEGRITY PIN. `unchanged` is derived from a SUCCESSFUL check
    since the last report, never from the absence of a recorded change."""
    now = time.time()
    _planted(store, last_success_at=now - 600, last_attempt_at=now - 60,
             last_attempt_ok=False, consecutive_failures=1,
             last_error={"code": "PAGE_UNREACHABLE",
                         "message": "DNS did not resolve example.org"})
    row = _call(action="report")["monitors"][0]
    assert row["state"] == "stale"
    assert "unchanged" not in json.dumps(row)
    assert row["last_error"]["code"] == "PAGE_UNREACHABLE"
    assert row["consecutive_failures"] == 1
    assert "last_success_at" in row


# --------------------------------------------------------------------- M-2

def test_m2_a_monitor_that_never_checked_says_so(store):
    _planted(store, last_success_at=None, last_attempt_at=None,
             last_attempt_ok=None, checks_run=0,
             baseline=None, next_due=time.time() + 300)
    row = _call(action="report")["monitors"][0]
    assert row["state"] == "never_checked"
    assert "unchanged" not in json.dumps(row)


# --------------------------------------------------------------------- M-3

def test_m3_a_long_gap_is_stale_even_after_a_success(store):
    now = time.time()
    _planted(store, interval_minutes=30, last_success_at=now - 3 * HOUR,
             last_attempt_at=now - 3 * HOUR, last_attempt_ok=True)
    row = _call(action="report")["monitors"][0]
    assert row["state"] == "stale"
    assert row["gap_s"] >= 3 * HOUR - 5


def test_m3b_a_recent_successful_check_that_did_not_fire_is_unchanged(store):
    now = time.time()
    _planted(store, last_success_at=now - 60, last_attempt_at=now - 60,
             last_attempt_ok=True, last_reported_at=now - HOUR)
    row = _call(action="report")["monitors"][0]
    assert row["state"] == "unchanged"


def test_m3c_a_fired_check_since_the_last_report_is_changed(store):
    now = time.time()
    _planted(store, last_success_at=now - 60, last_attempt_at=now - 60,
             last_attempt_ok=True, last_reported_at=now - HOUR,
             last_value={"kind": "count", "value": 16},
             history=[{"at": now - 60, "ok": True, "value": 16,
                       "fired": True, "from": 14}])
    row = _call(action="report")["monitors"][0]
    assert row["state"] == "changed"
    assert row["from"] == 14 and row["to"] == 16


def test_a_report_marks_what_it_reported(store):
    """A change reported once is not news the second time."""
    now = time.time()
    _planted(store, last_success_at=now - 60, last_attempt_at=now - 60,
             last_reported_at=now - HOUR,
             history=[{"at": now - 60, "ok": True, "value": 16,
                       "fired": True, "from": 14}])
    assert _call(action="report")["monitors"][0]["state"] == "changed"
    assert _call(action="report")["monitors"][0]["state"] == "unchanged"


# --------------------------------------------------------------------- M-4

def test_m4_a_restart_is_reported_not_hidden(store):
    now = time.time()
    _planted(store, interval_minutes=30, last_success_at=now - 2 * HOUR,
             last_attempt_at=now - 2 * HOUR, last_attempt_ok=True)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["written_by_pid"] = _monitors.os.getpid() + 1000
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    store.reload()
    report = _call(action="report")
    assert "restart" in json.dumps(report).lower()
    row = report["monitors"][0]
    assert row["missed_since_restart"] >= 3


# --------------------------------------------------------------------- M-5

def test_m5_an_unreadable_record_is_kept_and_named(store):
    _planted(store, id="m1")
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["monitors"].append({"id": "m2", "url": "https://example.org/broken"})
    before = json.dumps(raw, indent=1)
    store.path.write_text(before, encoding="utf-8")
    store.reload()
    report = _call(action="report")
    ids = {r["monitor"] for r in report["monitors"]}
    assert "m1" in ids, "a readable monitor stopped scheduling"
    bad = [r for r in report["monitors"] if r["monitor"] == "m2"]
    assert bad and bad[0]["state"] == "blocked"
    assert "m2" in json.dumps(bad)
    # The corrupt record survives on disk BYTE FOR BYTE. Dropping what a
    # version cannot parse is the inversion this build refuses.
    kept = json.loads(store.path.read_text(encoding="utf-8"))
    assert {"id": "m2", "url": "https://example.org/broken"} \
        in kept["monitors"]


# --------------------------------------------------------------------- M-6

def test_m6_the_interval_floor_clamps_and_says_it_clamped(store,
                                                          monkeypatch):
    monkeypatch.setattr(_monitor_ops, "_run_check", _fake_check)
    out = _call(action="create", url="https://example.org/thing",
                condition="text_appears", value="hello",
                check_interval_minutes=1)
    assert out["interval_minutes"] == _monitors.limit("min_interval_min")
    assert "clamped" in json.dumps(out)


async def _fake_check(record, *, first: bool = False):
    """Stands in for the browser half: a successful check with a value."""
    return {"ok": True, "value": {"kind": "text", "value": True},
            "frames": 0}


# --------------------------------------------------------------------- M-7

@pytest.mark.parametrize("name,env", [
    ("min_interval_min", "KS4WEB_MONITOR_MIN_INTERVAL_MIN"),
    ("max_monitors", "KS4WEB_MONITOR_MAX"),
    ("max_checks_day", "KS4WEB_MONITOR_MAX_CHECKS_DAY"),
    ("max_failures", "KS4WEB_MONITOR_MAX_FAILURES"),
    ("history", "KS4WEB_MONITOR_HISTORY"),
])
def test_m7_every_monitor_limit_is_finite(store, monkeypatch, name, env):
    monkeypatch.delenv(env, raising=False)
    default = _monitors.limit(name)
    assert default == _monitors.LIMIT_ENVS[name][1]
    monkeypatch.setenv(env, "not a number")
    assert _monitors.limit(name) == default, (
        "a garbage env value became something other than the default")
    monkeypatch.setenv(env, "0")
    assert _monitors.limit(name) >= 1, "a limit resolved to zero or infinity"
    monkeypatch.delenv(env, raising=False)
    assert str(_monitors.limit(name)) in json.dumps(_call(action="report"))


# --------------------------------------------------------------------- M-8

def test_m8_the_refusal_vocabulary_is_closed(store):
    _planted(store)
    seen = set()
    for kwargs in (
        {"action": "nonsense"},
        {"action": "create", "url": "https://example.org/x",
         "condition": "vibes"},
        {"action": "create", "url": "https://example.org/x",
         "condition": "text_appears"},
        {"action": "delete", "monitor": "m404"},
        {"action": "pause", "monitor": None},
    ):
        with pytest.raises(errors.WebMcpError) as caught:
            _call(**kwargs)
        seen.add(envelope.classify(caught.value))
    assert seen <= envelope.CLOSED_CODES, seen - envelope.CLOSED_CODES


def test_an_unknown_monitor_id_lists_the_known_ones(store):
    _planted(store, id="m1")
    message = _refuses("NOT_FOUND", action="delete", monitor="m9")
    assert "m1" in message
    assert "never reused" in message


def test_a_delete_says_what_it_is_discarding(store):
    now = time.time()
    _planted(store, checks_run=62,
             history=[{"at": now, "ok": True, "value": 1, "fired": False}])
    out = _call(action="delete", monitor="m1")
    assert out["checks_run"] == 62
    assert out["history_discarded"] == 1
    assert not _call(action="list")["monitors"]


# --------------------------------------------------------------------- M-9

def test_m9_monitor_is_classified_and_registers_under_read_only(launch,
                                                                live_tools):
    assert "monitor" in readonly.NON_MUTATING
    assert "monitor" not in readonly.MUTATING
    assert "monitor" not in readonly.GENUINELY_READ_ONLY, (
        "monitor creates browser processes, writes files, and issues "
        "outbound requests, so readOnlyHint would be a false safety claim")
    launch(read_only="browse")
    assert "monitor" in live_tools()


# -------------------------------------------------------------------- M-10

def test_m10_no_monitor_action_mutates_policy(store, monkeypatch):
    monkeypatch.setattr(_monitor_ops, "_run_check", _fake_check)
    from kitchensink4web import packs
    from kitchensink4web.policy import budgets, origins
    before = (readonly.grade(), sorted(packs.tool_names()),
              origins.active(),
              {k: budgets.limit(k) for k in budgets.LIMIT_ENVS})
    _call(action="create", url="https://example.org/thing",
          condition="text_appears", value="hi")
    for kwargs in ({"action": "list"}, {"action": "report"},
                   {"action": "pause", "monitor": "m1"},
                   {"action": "resume", "monitor": "m1"},
                   {"action": "delete", "monitor": "m1"}):
        _call(**kwargs)
    after = (readonly.grade(), sorted(packs.tool_names()),
             origins.active(),
             {k: budgets.limit(k) for k in budgets.LIMIT_ENVS})
    assert before == after


# -------------------------------------------------------------------- M-11

def test_m11_persistence_is_atomic(store, monkeypatch):
    _planted(store, id="m1")
    good = store.path.read_bytes()

    def boom(self, target):
        raise OSError("disk went away")

    monkeypatch.setattr(_monitors.Path, "replace", boom)
    _planted(store, id="m2")
    assert store.path.read_bytes() == good, (
        "a failed write left the store half-written")
    leftovers = list(store.path.parent.glob("*.tmp"))
    assert not leftovers, f"a temp file survived: {leftovers}"


# ------------------------------------------------------------- the budget

def test_the_daily_check_budget_suspends_rather_than_deletes(store,
                                                             monkeypatch):
    monkeypatch.setenv("KS4WEB_MONITOR_MAX_CHECKS_DAY", "1")
    _planted(store, id="m1")
    store.checks_today = {"window_start": time.time(), "count": 1}
    with pytest.raises(errors.BudgetExhausted) as caught:
        _monitors.charge_check()
    assert "suspended" in str(caught.value)
    assert "delete" in str(caught.value).lower()


def test_the_monitor_cap_refuses_with_the_count(store, monkeypatch):
    monkeypatch.setenv("KS4WEB_MONITOR_MAX", "1")
    monkeypatch.setattr(_monitor_ops, "_run_check", _fake_check)
    _planted(store, id="m1")
    message = _refuses("CONFLICT", action="create",
                       url="https://example.org/other",
                       condition="text_appears", value="x")
    assert "1" in message
    assert "monitor(action='list')" in message


def test_repeated_failure_auto_pauses(store, monkeypatch):
    monkeypatch.setenv("KS4WEB_MONITOR_MAX_FAILURES", "2")
    now = time.time()
    record = _planted(store, consecutive_failures=1, last_attempt_ok=False,
                      last_success_at=now - 600,
                      last_error={"code": "PAGE_UNREACHABLE", "message": "x"})
    _monitors.note_failure(record, "PAGE_UNREACHABLE", "still gone")
    assert record["state"] == "paused"
    assert record["auto_paused"] is True
    row = _call(action="report")["monitors"][0]
    assert row["state"] == "stale"
    assert row["auto_paused"] is True


def test_history_is_bounded(store, monkeypatch):
    monkeypatch.setenv("KS4WEB_MONITOR_HISTORY", "3")
    record = _planted(store)
    for i in range(10):
        _monitors.note_success(record, {"kind": "count", "value": i},
                               fired=False)
    assert len(record["history"]) == 3


# ------------------------------------------------------------- create path

def test_create_refuses_an_unknown_condition_and_lists_the_four(store):
    message = _refuses("BAD_PARAMS", action="create",
                       url="https://example.org/x", condition="vibes")
    for name in _monitors.CONDITIONS:
        assert name in message


def test_create_refuses_a_condition_with_no_value(store):
    for condition in ("text_appears", "text_gone", "selector_count"):
        message = _refuses("BAD_PARAMS", action="create",
                           url="https://example.org/x", condition=condition)
        assert "value" in message


def test_create_returns_the_conditions_own_honest_description(store,
                                                              monkeypatch):
    monkeypatch.setattr(_monitor_ops, "_run_check", _fake_check)
    out = _call(action="create", url="https://example.org/x",
                condition="content_hash")
    assert out["condition"] == "content_hash"
    assert "cannot" in json.dumps(out["what_it_notices"]).lower()
    assert out["baseline"] is not None


def test_a_create_that_cannot_reach_the_page_creates_nothing(store,
                                                             monkeypatch):
    async def unreachable(record, *, first=False):
        raise errors.PageUnreachable("the host did not answer")

    monkeypatch.setattr(_monitor_ops, "_run_check", unreachable)
    _refuses("PAGE_UNREACHABLE", action="create",
             url="https://example.org/x", condition="text_appears",
             value="hi")
    assert not _call(action="list")["monitors"], (
        "a monitor with no baseline was created, and it can never report a "
        "change against a page it has not seen")


# ------------------------------------------------- V-17: one Retry-After
#
# The check parsed the header itself, on 429 alone and as a bare integer
# alone, so `120.5` and every HTTP-date form fell through to the default and
# a 503 with a wait attached lost its number entirely. The refusal then
# reported KS4Web's own default as the site's window. The parse, the record,
# and the report belong to `budgets`, which `navigate` already uses.


class _FakeResponse:
    def __init__(self, status, headers):
        self.status = status
        self.headers = headers


class _FakePage:
    def __init__(self, response, url):
        self._response = response
        self.url = url

    async def goto(self, url, **kwargs):
        return self._response


class _FakeRecord:
    def __init__(self, page):
        self.page = page
        self.handle = "p1"
        self.parked = False
        self.vetted_url = None

    def touch(self, url):
        pass


class _FakeSession:
    focused = "p1"

    def __init__(self, record):
        self._record = record

    def page(self, handle):
        return self._record

    def invalidate_page(self, handle, why):
        pass


def _answering(store, monkeypatch, status, headers):
    """Drive one check against a canned response, no browser involved."""
    record = _planted(store)
    page = _FakePage(_FakeResponse(status, headers),
                     "https://example.org/thing")
    sess = _FakeSession(_FakeRecord(page))

    async def _fake_session():
        return sess

    monkeypatch.setattr(_monitor_ops, "_monitor_session", _fake_session)
    _monitor_ops._budgets.BOOK._backoff.clear()
    with pytest.raises(errors.BlockedBySite) as caught:
        asyncio.run(_monitor_ops._run_check(record))
    return str(caught.value)


def test_a_fractional_retry_after_is_read_rather_than_defaulted(store,
                                                                monkeypatch):
    message = _answering(store, monkeypatch, 429, {"retry-after": "120.5"})
    assert "120" in message and "60s" not in message


def test_a_503_with_a_wait_is_honored_like_a_429(store, monkeypatch):
    message = _answering(store, monkeypatch, 503, {"retry-after": "90"})
    assert "90" in message
    assert _monitor_ops._budgets.BOOK.remaining_backoff_s("example.org") > 0


def test_an_http_date_is_honored_in_a_check_too(store, monkeypatch):
    import re
    from email.utils import formatdate
    when = formatdate(time.time() + 300, usegmt=True)
    message = _answering(store, monkeypatch, 429, {"retry-after": when})
    found = re.search(r"(\d+)s", message)
    assert found and int(found.group(1)) >= 250, message


def test_the_default_window_is_not_worded_as_the_sites_own(store,
                                                           monkeypatch):
    """A 429 with no header still backs off, but the sentence must not
    attribute KS4Web's default to the site's Retry-After."""
    message = _answering(store, monkeypatch, 429, {})
    assert "60" in message
    assert "its Retry-After window" not in message


def test_the_remaining_backoff_is_read_from_the_book_not_the_sentence(
        store, monkeypatch):
    """The refusal string is a user-facing sentence, not an API. Rewording
    it must not change what the monitor records as its blocked window."""
    _monitor_ops._budgets.BOOK._backoff.clear()
    _monitor_ops._budgets.BOOK.note_retry_after("example.org", "300",
                                                status=429)
    monkeypatch.setattr(
        _monitor_ops._budgets.BOOK, "check_domain",
        lambda domain: (_ for _ in ()).throw(
            errors.BlockedBySite("the window is still open")))
    assert 290 <= _monitor_ops._remaining_backoff(
        "https://example.org/thing") <= 300


# ---------------------------------------------------------- the predicates

@pytest.mark.parametrize("condition,before,after,fired", [
    ("content_hash", "abc", "abd", True),
    ("content_hash", "abc", "abc", False),
    ("text_appears", False, True, True),
    ("text_appears", True, True, False),
    ("text_gone", True, False, True),
    ("text_gone", True, True, False),
    ("text_gone", False, False, False),
    ("selector_count", 14, 16, True),
    ("selector_count", 14, 14, False),
])
def test_each_condition_fires_only_on_its_own_change(condition, before,
                                                     after, fired):
    assert _monitors.fires(condition, before, after) is fired
