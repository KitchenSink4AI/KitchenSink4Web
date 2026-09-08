"""Fix wave 10: the three-layer cascade a Cloudflare wall set off in the field.

WHAT HAPPENED, and the mechanism was one line. A Cloudflare wall killed a
Firefox browser. The Playwright driver behind it went down, and because the
whole process shared ONE driver, the monitor's Chromium browser died beside
it having never visited the site. Then every attempt to open a new session
launched against the dead driver and failed, until the tester found the dead
monitor session by hand and closed it, which emptied `MANAGER.sessions`,
which was the only condition under which the old code replaced the driver.

Three properties are pinned here and each one severs a different layer:

  1. a dead session never blocks a new one (`open()` reaps it);
  2. a driver death is confined to its own slot, so a user browser's death
     cannot reach the monitor's;
  3. the death is NAMED, in the status report and in the SESSION_DEAD
     recovery facts, instead of being something a tester has to deduce.

Every one has a both-direction partner: a LIVE session must never be reaped,
and a slot with sessions still on it must never have its driver stopped.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web.engine import session as _session
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import lite, monitor as _monitor

pytestmark = pytest.mark.browser


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


def _kill_browsers(sess) -> None:
    """Kill every OS process one session owns, and leave the handle behind.

    This is the field shape: the Session object is still in the manager's
    dict, still listed by status, and its browser is gone."""
    from kitchensink4web.engine import hygiene
    for jar in sess.contexts.values():
        for pid in list(jar.journal.pids):
            hygiene.kill(pid)


# ---------------------------------------------------- LAYER 3: the blocker


def test_a_dead_session_does_not_block_a_new_one(session_factory):
    """THE SHIP BLOCKER. Before the fix the dead handle stayed in the list
    and the shared driver stayed cached, and every open after it failed."""
    async def go():
        doomed = await session_factory()
        _kill_browsers(doomed)
        assert doomed.browser_alive() is False
        fresh = await session_factory()
        assert fresh.session_id in MANAGER.sessions
        assert doomed.session_id not in MANAGER.sessions, (
            "the dead session survived the open that should have reaped it")
        stone = MANAGER.tombstone(doomed.session_id)
        assert stone and stone["reason"] == "reaped_dead"

    run(go())


def test_the_open_that_reaped_says_what_it_reaped(session_factory):
    """A handle disappearing between two calls is a thing the caller is owed
    an explanation for."""
    async def go():
        doomed = await session_factory()
        _kill_browsers(doomed)
        result = await lite.manage_session(action="open")
        assert doomed.session_id in [r["session"] for r in result["reaped"]]
        assert "never blocks a new one" in result["reaped_note"]
        await MANAGER.close(result["session"])

    run(go())


def test_a_live_session_is_never_reaped(session_factory):
    """THE BOTH-DIRECTION PIN. A reaper that took a working browser would be
    a far worse bug than the one it fixes."""
    async def go():
        keeper = await session_factory()
        await session_factory()
        assert keeper.session_id in MANAGER.sessions
        assert keeper.browser_alive() is not False
        assert MANAGER.last_reap == []

    run(go())


# ------------------------------------------ LAYER 2: the shared driver seam


def test_a_user_session_and_the_monitor_run_on_different_drivers(
        session_factory):
    """The coupling, measured rather than assumed. Two slots means two node
    processes, and a driver is the parent of every browser it launched."""
    async def go():
        user = await session_factory()
        monitor_session = await MANAGER.open(headless=True, role="monitor")
        try:
            assert user.driver_slot == "user"
            assert monitor_session.driver_slot == "monitor"
            assert MANAGER._drivers["user"] is not MANAGER._drivers["monitor"]
        finally:
            await MANAGER.close(monitor_session.session_id)

    run(go())


def test_killing_a_user_browser_leaves_the_monitor_alive(session_factory):
    """THE FIELD REPRO, inverted into a pin. In the field a user browser's
    death took the monitor's with it; here it must not."""
    async def go():
        user = await session_factory()
        monitor_session = await MANAGER.open(headless=True, role="monitor")
        try:
            _kill_browsers(user)
            assert user.browser_alive() is False
            assert monitor_session.browser_alive() is not False, (
                "the monitor's browser died with a user session's browser")
            # And a new session still opens, which is layer 3 seen from here.
            fresh = await session_factory()
            assert fresh.browser_alive() is not False
        finally:
            if monitor_session.session_id in MANAGER.sessions:
                await MANAGER.close(monitor_session.session_id)

    run(go())


def test_closing_the_last_user_session_leaves_the_monitor_driver_up(
        session_factory):
    """THE BOTH-DIRECTION PIN on the per-slot teardown. The old code stopped
    THE driver when the LAST session closed; stopping the user slot's driver
    must not reach across and take the monitor's down."""
    async def go():
        user = await session_factory()
        monitor_session = await MANAGER.open(headless=True, role="monitor")
        try:
            await MANAGER.close(user.session_id)
            assert "user" not in MANAGER._drivers, (
                "the user slot's driver outlived its last session")
            assert MANAGER._drivers.get("monitor") is not None
            assert monitor_session.browser_alive() is not False
        finally:
            if monitor_session.session_id in MANAGER.sessions:
                await MANAGER.close(monitor_session.session_id)

    run(go())


def test_a_slot_with_sessions_on_it_keeps_its_driver(session_factory):
    """THE BOTH-DIRECTION PIN, second arm. Closing one of two sessions on a
    slot must leave the driver the other one is using alone."""
    async def go():
        first = await session_factory()
        second = await session_factory()
        await MANAGER.close(first.session_id)
        assert MANAGER._drivers.get("user") is not None
        assert second.browser_alive() is not False

    run(go())


def test_a_dead_driver_is_replaced_rather_than_handed_back(session_factory):
    """THE FIELD MECHANISM, reproduced exactly and then severed.

    Killing the driver process is what actually happened: the browsers it
    launched are its children and go with it, and the old code kept handing
    the corpse back to every `open()` until the session count reached zero.
    Here the next open buries it, names its casualties, and starts a fresh
    one."""
    async def go():
        from kitchensink4web.engine import hygiene
        doomed = await session_factory()
        transport = _session._driver_transport(MANAGER._drivers["user"])
        hygiene.kill(transport._proc.pid)
        for _ in range(40):                     # the exit is not instant
            if _session.driver_alive(MANAGER._drivers["user"]) is False:
                break
            await asyncio.sleep(0.1)
        assert _session.driver_alive(MANAGER._drivers["user"]) is False

        fresh = await session_factory()
        assert fresh.browser_alive() is not False, (
            "a new session launched against the dead driver")
        assert doomed.session_id not in MANAGER.sessions
        assert MANAGER._drivers["user"] is not None
        assert _session.driver_alive(MANAGER._drivers["user"]) is True
        # The death is a fact the status report carries, not a mystery.
        report = await lite.manage_session(action="status")
        deaths = report["driver_deaths"]
        assert deaths and deaths[-1]["slot"] == "user"
        assert doomed.session_id in deaths[-1]["sessions_lost"]
        # ATTRIBUTED TO THE DRIVER, not to an unexplained dead browser.
        stone = MANAGER.tombstone(doomed.session_id)
        assert stone["reason"] == "driver_died", stone

    run(go())


def test_a_user_driver_death_does_not_reach_the_monitors(session_factory):
    """THE WHOLE POINT OF THE SPLIT, on the real mechanism rather than on a
    browser-PID kill. In the field this is the step that killed a Chromium
    session which had never visited the site."""
    async def go():
        from kitchensink4web.engine import hygiene
        await session_factory()
        monitor_session = await MANAGER.open(headless=True, role="monitor")
        try:
            transport = _session._driver_transport(MANAGER._drivers["user"])
            hygiene.kill(transport._proc.pid)
            for _ in range(40):
                if _session.driver_alive(MANAGER._drivers["user"]) is False:
                    break
                await asyncio.sleep(0.1)
            assert _session.driver_alive(MANAGER._drivers["monitor"]) is True
            assert monitor_session.browser_alive() is not False, (
                "the monitor's browser died with the user slot's driver")
        finally:
            if monitor_session.session_id in MANAGER.sessions:
                await MANAGER.close(monitor_session.session_id)

    run(go())


# ------------------------------------------------- LAYER 1 + 3: it is NAMED


def test_the_status_report_names_a_dead_monitor_out_loud(session_factory):
    """The tester found the dead monitor by accident, three layers in."""
    async def go():
        monitor_session = await MANAGER.open(headless=True, role="monitor")
        try:
            _kill_browsers(monitor_session)
            report = await lite.manage_session(action="status")
            assert report["monitor_session"]["browser"] == "dead"
            assert report["monitor_session"]["session"] == \
                monitor_session.session_id
        finally:
            if monitor_session.session_id in MANAGER.sessions:
                await MANAGER.close(monitor_session.session_id)

    run(go())


def test_a_healthy_monitor_is_named_too(session_factory):
    """BOTH-DIRECTION PIN. "The monitor is fine" is the answer that stops a
    caller hunting, and it is worth as much as the other one."""
    async def go():
        monitor_session = await MANAGER.open(headless=True, role="monitor")
        try:
            report = await lite.manage_session(action="status")
            assert report["monitor_session"]["browser"] == "alive"
        finally:
            await MANAGER.close(monitor_session.session_id)

    run(go())


def test_no_monitor_no_monitor_line(session_factory):
    """BOTH-DIRECTION PIN. A block about a scheduler nobody started is noise
    in the payload a caller reaches for when everything else is refusing.

    Skipped rather than forced where the machine running the suite has
    monitors stored on disk: a monitor defined and not currently running IS
    a thing the line exists to report, and asserting its absence there would
    be pinning the opposite of the contract."""
    async def go():
        if _monitor._active_monitors():
            pytest.skip("this machine has monitors defined")
        await session_factory()
        report = await lite.manage_session(action="status")
        assert "monitor_session" not in report

    run(go())


def test_session_dead_carries_machine_readable_recovery(session_factory):
    """Field item 7. The refusal named a recovery in prose and left the
    caller to discover the rest of the casualties by hand."""
    async def go():
        from kitchensink4web import envelope
        doomed = await session_factory()
        page = doomed.focused
        _kill_browsers(doomed)
        # The tools raise; `envelope.refusal` is what the server wrapper
        # turns the exception into, and the recovery has to survive that
        # trip rather than only existing on the exception object.
        with pytest.raises(Exception) as caught:
            await lite.get_text(page=page)
        result = envelope.refusal(caught.value)
        assert result["ok"] is False
        assert result["error"]["code"] == "SESSION_DEAD"
        recovery = result["error"]["recovery"]
        assert recovery["new_session_is_not_blocked"] is True
        assert recovery["status_call"] == "manage_session(action='status')"
        assert recovery["session"] == doomed.session_id
        # No wall was met on this session, so no lane hint is invented.
        assert "wall_preceded_death" not in recovery

    run(go())


def test_the_monitor_session_restarts_and_reports_the_restart():
    """Auto-restart, and the restart is a reported fact rather than a
    silently-replaced browser."""
    async def go():
        _monitor.SESSION_RESTARTS.clear()
        first = await _monitor._monitor_session()
        _kill_browsers(first)
        second = await _monitor._monitor_session()
        try:
            assert second.session_id != first.session_id
            assert second.browser_alive() is not False
            restarts = _monitor.session_restarts()
            assert restarts and restarts[-1]["replaced"] == first.session_id
            assert restarts[-1]["opened"] == second.session_id
            health = _monitor.monitor_session_health()
            assert health["restarts"], health
        finally:
            _monitor.SESSION_RESTARTS.clear()

    run(go())


def test_a_live_monitor_session_is_reused_not_restarted():
    """BOTH-DIRECTION PIN. A restart on every tick would be a browser churn
    far worse than a stale report."""
    async def go():
        _monitor.SESSION_RESTARTS.clear()
        first = await _monitor._monitor_session()
        second = await _monitor._monitor_session()
        assert second.session_id == first.session_id
        assert not _monitor.session_restarts()

    run(go())


def test_the_failure_valve_is_untouched_by_the_restart():
    """The auto-restart must not turn a monitor that cannot work into one
    that retries forever. `note_failure` still counts and still pauses."""
    from kitchensink4web.engine import monitors as _m
    record = {"id": "m1", "state": "active", "consecutive_failures": 0,
              "history": [], "url": "https://example.com"}
    limit = _m.limit("max_failures")
    for _ in range(limit):
        _m.note_failure(record, "SESSION_DEAD", "the browser is gone")
    assert record["state"] == "paused"
    assert record["auto_paused"] is True


def test_the_probe_reads_a_REAL_driver(session_factory):
    """THE PIN THAT MATTERS, and it is here because the synthetic one below
    is not enough on its own.

    The first cut of `driver_alive` read `_connection` off the async API
    wrapper. That wrapper is thin: the connection lives on `_impl_obj`, so
    the probe answered `None` for every real driver and the whole
    death-detection path would have been dead code in production, while the
    synthetic pin below passed happily. A capability probe is only worth
    what it answers about the real thing."""
    async def go():
        await session_factory()
        driver = MANAGER._drivers["user"]
        assert _session.driver_alive(driver) is True, (
            "the liveness probe cannot see a running driver, so nothing "
            "would ever detect a dead one")

    run(go())


def test_a_stopped_driver_reads_as_dead():
    """The other end of the same probe, against a real driver that really
    stopped rather than a hand-built stand-in."""
    async def go():
        from playwright.async_api import async_playwright
        driver = await async_playwright().start()
        assert _session.driver_alive(driver) is True
        await driver.stop()
        assert _session.driver_alive(driver) is False

    asyncio.run(go())


def test_a_driver_this_cannot_see_is_treated_as_alive():
    """The probe reads a private Playwright attribute, so it is allowed to
    move under us. A release that renames it must cost this wave's fix and
    must never cost a working driver."""
    class _Opaque:
        pass

    assert _session.driver_alive(_Opaque()) is None

    class _Dead:
        class _connection:
            class _transport:
                class _proc:
                    returncode = 1
            _transport = _transport()
        _connection = _connection()

    assert _session.driver_alive(_Dead()) is False
