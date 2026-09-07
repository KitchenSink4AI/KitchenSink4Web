"""Proactive page monitoring against a real browser (lifecycle spec §8.2).

The unit half proves the state model. This half proves the three things
only a real browser can falsify: that a monitor never touches the caller's
session, that each condition detects its own change and only its own, and
that a monitor leaves no browser process behind.

The site here is a MUTABLE one, started in-process for this file, because
every condition needs a page whose content changes between two checks and
the shared fixture site is deliberately deterministic. Nothing touches the
network and nothing opens a window.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
import time

import pytest

from kitchensink4web.engine import monitors as _monitors
from kitchensink4web.engine import session as _session
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import NavigationBlocked, PageUnreachable
from kitchensink4web.ops import lite
from kitchensink4web.ops import monitor as _monitor_ops
from kitchensink4web.policy import budgets as _budgets

pytestmark = pytest.mark.browser

#: What the mutable site currently serves, and how many times it has been
#: asked. The 429 pin needs the request COUNT, because "we did not retry"
#: is a claim about requests that left this machine.
STATE = {"text": "quiet", "items": 2, "status": 200, "requests": 0}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802
        STATE["requests"] += 1
        if STATE["status"] == 429:
            self.send_response(429)
            self.send_header("Retry-After", "60")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>slow down</body></html>")
            return
        items = "".join(f"<li>item {i}</li>" for i in range(STATE["items"]))
        body = (f"<html><body><p id='t'>{STATE['text']}</p>"
                f"<ul>{items}</ul></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):                      # noqa: D102
        return                                          # silent by design


@pytest.fixture(scope="module")
def mutable_site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(_monitors, "STORE",
                        _monitors.MonitorStore(tmp_path / "monitors.json"))
    STATE.update({"text": "quiet", "items": 2, "status": 200, "requests": 0})
    _budgets.BOOK._backoff.clear()
    yield
    _budgets.BOOK._backoff.clear()


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await _monitor_ops.stop_scheduler()
            await MANAGER.close_all()

    return asyncio.run(main())


def _monitor_sessions() -> list:
    return [s for s in MANAGER.sessions.values()
            if getattr(s, "role", "user") == "monitor"]


# -------------------------------------------------------------------- M-12

def test_m12_a_monitor_never_touches_the_callers_session(session_factory,
                                                         fixture_site,
                                                         mutable_site):
    """A monitor navigating in the caller's session would charge their
    budget and destroy every ref they were holding on that page. That is
    disqualifying, so it is pinned rather than assumed."""
    async def go():
        mine = await session_factory()
        page = mine.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        await lite.get_page_view(page=page)
        refs_before = lite._live_refs(mine, page)
        assert refs_before > 0
        budget_before = json.dumps(
            _budgets.BOOK.snapshot(mine.session_id)["counters"])
        url_before = mine.pages[page].page.url

        await _monitor_ops.monitor(action="create", url=f"{mutable_site}/",
                                   condition="selector_count", value="li",
                                   check_interval_minutes=5)
        record = _monitors.STORE.monitors[0]
        record["next_due"] = time.time() - 1
        await _monitor_ops.tick_once()

        assert lite._live_refs(mine, page) == refs_before, (
            "the monitor invalidated the caller's refs")
        assert json.dumps(
            _budgets.BOOK.snapshot(mine.session_id)["counters"]) \
            == budget_before, "the monitor charged the caller's budget"
        assert mine.pages[page].page.url == url_before
        assert len(_monitor_sessions()) == 1

    run(go())


# -------------------------------------------------------------------- M-13

def test_m13_the_monitor_session_is_visible_and_not_the_default(mutable_site):
    """A browser process the user did not open must never be invisible in
    the status report, and must never be what a call naming no session
    lands on."""
    async def go():
        await _monitor_ops.monitor(action="create", url=f"{mutable_site}/",
                                   condition="text_appears", value="quiet")
        assert len(_monitor_sessions()) == 1
        with pytest.raises(Exception) as caught:
            MANAGER.session(None)
        assert "monitor" in str(caught.value).lower()
        status = await lite.manage_session(action="status")
        rows = [r for r in status["sessions"] if r.get("role") == "monitor"]
        assert rows, "the monitor session is absent from the status report"

    run(go())


# -------------------------------------------------------------------- M-14

def test_m14_a_denied_origin_is_refused_at_create(mutable_site, monkeypatch):
    async def go():
        monkeypatch.setenv("KS4WEB_DENY_ORIGINS", "127.0.0.1")
        with pytest.raises(NavigationBlocked):
            await _monitor_ops.monitor(
                action="create", url=f"{mutable_site}/",
                condition="text_appears", value="quiet")
        listed = await _monitor_ops.monitor(action="list")
        assert listed["monitors"] == []
        assert not _monitor_sessions(), (
            "a refused create left a browser running")

    run(go())


# -------------------------------------------------------------------- M-15

def test_m15_an_unreachable_url_creates_nothing():
    """A monitor whose baseline is 'we never saw it' cannot report a
    change, so no monitor is created at all."""
    async def go():
        with pytest.raises(PageUnreachable):
            await _monitor_ops.monitor(
                action="create", url="http://127.0.0.1:45601/nothing",
                condition="text_appears", value="hello")
        listed = await _monitor_ops.monitor(action="list")
        assert listed["monitors"] == []

    run(go())


# -------------------------------------------------------------------- M-16

def test_m16_the_page_is_parked_and_its_refs_invalidated(mutable_site):
    async def go():
        await _monitor_ops.monitor(action="create", url=f"{mutable_site}/",
                                   condition="selector_count", value="li")
        sess = _monitor_sessions()[0]
        record = sess.pages[sess.focused]
        assert record.page.url == _session.PARKED_URL, (
            "the monitor left a live page loaded between checks")
        assert record.parked is True
        assert all(entry.gone for entry in sess.element_map.entries.values()
                   if entry.handle == record.handle)

    run(go())


# -------------------------------------------------------------------- M-17

def test_m17_a_429_is_honoured_not_retried(mutable_site):
    async def go():
        await _monitor_ops.monitor(action="create", url=f"{mutable_site}/",
                                   condition="selector_count", value="li")
        STATE["status"] = 429
        record = _monitors.STORE.monitors[0]
        record["next_due"] = time.time() - 1
        await _monitor_ops.tick_once()
        after_first = STATE["requests"]
        record["next_due"] = time.time() - 1
        await _monitor_ops.tick_once()
        assert STATE["requests"] == after_first, (
            "a second request went out inside the Retry-After window")
        row = (await _monitor_ops.monitor(action="report"))["monitors"][0]
        assert row["state"] == "blocked"
        assert row["blocked_for_s"] > 0

    run(go())


# -------------------------------------------------------------------- M-18

@pytest.mark.parametrize("condition,value,mutate", [
    ("selector_count", "li", lambda: STATE.update(items=3)),
    ("content_hash", None, lambda: STATE.update(text="loud")),
    ("text_appears", "loud", lambda: STATE.update(text="loud")),
    ("text_gone", "quiet", lambda: STATE.update(text="loud")),
])
def test_m18_each_condition_detects_its_own_change(mutable_site, condition,
                                                   value, mutate):
    async def go():
        await _monitor_ops.monitor(action="create", url=f"{mutable_site}/",
                                   condition=condition, value=value)
        record = _monitors.STORE.monitors[0]
        # No mutation: nothing fires.
        first = await _monitor_ops.monitor(action="check_now",
                                           monitor=record["id"])
        assert first["checked_now"]["fired"] is False
        mutate()
        second = await _monitor_ops.monitor(action="check_now",
                                            monitor=record["id"])
        assert second["checked_now"]["fired"] is True
        assert second["state"] == "changed"
        # And it stays quiet once the change has been reported.
        third = await _monitor_ops.monitor(action="check_now",
                                           monitor=record["id"])
        assert third["checked_now"]["fired"] is False

    run(go())


# -------------------------------------------------------------------- M-19

def test_m19_zero_orphans_after_monitor_teardown(mutable_site):
    async def go():
        from kitchensink4web.engine import hygiene

        created = await _monitor_ops.monitor(
            action="create", url=f"{mutable_site}/",
            condition="selector_count", value="li")
        sess = _monitor_sessions()[0]
        pids = list(sess.journal.pids)
        assert pids, "the monitor session journalled no owned PIDs"
        await _monitor_ops.monitor(action="delete",
                                   monitor=created["monitor"])
        assert not _monitor_sessions(), (
            "the monitor session outlived the last monitor")
        assert not [pid for pid in pids if hygiene.alive(pid)]

    run(go())


# ------------------------------------------------- the report, end to end

def test_a_failed_check_after_a_success_reports_stale(mutable_site):
    """M-1 against a real browser: the site goes away between two checks
    and the monitor says so instead of saying nothing changed."""
    async def go():
        created = await _monitor_ops.monitor(
            action="create", url=f"{mutable_site}/",
            condition="selector_count", value="li")
        record = _monitors.STORE.monitors[0]
        record["url"] = "http://127.0.0.1:45601/gone"
        await _monitor_ops.monitor(action="check_now",
                                   monitor=created["monitor"])
        row = (await _monitor_ops.monitor(action="report"))["monitors"][0]
        assert row["state"] == "stale"
        assert row["last_error"]["code"] == "PAGE_UNREACHABLE"
        assert row["last_success_at"] is not None

    run(go())
