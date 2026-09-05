"""The browser core against a real browser: handles, navigation, hygiene,
and the projection end to end.

Everything here runs on a local deterministic fixture site. Nothing touches
the network and nothing touches a browser the user started.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from kitchensink4web.engine import hygiene, lanes
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (BadParams, LaneUnsupported, RangeOutOfBounds,
                                    TargetNotFound)
from kitchensink4web.ops import lite

pytestmark = pytest.mark.browser

FIREFOX_INSTALLED = any(
    os.path.exists(p) for p in
    (r"C:\Program Files\Mozilla Firefox\firefox.exe",
     r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"))


def run(coro):
    """Run a test body and close every session inside the SAME event loop.

    A Playwright instance is bound to the loop that started it, so a teardown
    running in a fresh loop cannot stop it. That is not a test-harness detail:
    it is the same constraint the server lives under, which is why the session
    manager refuses a cross-loop reuse rather than papering over it."""
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


# ------------------------------------------------------------- lifecycle


def test_a_session_mints_handles_and_owns_its_processes(session_factory,
                                                        fixture_site):
    async def go():
        session = await session_factory()
        assert session.session_id.startswith("s")
        assert session.focused and session.focused.startswith("p")
        # DESIGN 4.7 fact 3: Playwright does not expose the browser PID, so
        # the journal is populated from the process table at launch.
        assert session.journal.pids, "no owned PIDs were journalled"
        assert Path(session.journal.path).is_file()
        assert hygiene.PROFILE_MARKER in session.profile_dir
        assert Path(session.profile_dir).is_dir()
        return session

    run(go())


def test_close_verifies_the_teardown_by_owned_pid(session_factory):
    async def go():
        session = await session_factory()
        owned = sorted(session.journal.pids)
        report = await MANAGER.close(session.session_id)
        assert report["owned_pids"] == owned
        assert report["survivors_killed"] == []
        assert not Path(session.profile_dir).exists()
        assert not Path(session.journal.path).exists()
        assert [pid for pid in owned if hygiene.alive(pid)] == []

    run(go())


def test_three_cycles_leak_nothing(session_factory, fixture_site):
    """The 50-cycle version is `scripts/gate_hygiene.py`; three here keep the
    property in the suite where a regression is noticed the same day."""
    async def go():
        for _ in range(3):
            session = await MANAGER.open(lane="A", engine="chromium",
                                         headless=True)
            page = session.page(session.focused).page
            await page.goto(fixture_site + "/form", wait_until="load")
            owned = sorted(session.journal.pids)
            profile = session.profile_dir
            await MANAGER.close(session.session_id)
            assert [pid for pid in owned if hygiene.alive(pid)] == []
            assert not Path(profile).exists()

    run(go())


def test_the_idle_park_stops_a_busy_page(session_factory):
    """Verified by CPU, because "we called goto about:blank" is not evidence
    that a page stopped burning a core (chrome-devtools-mcp #2599: 28 to 30
    percent for hours, 0.13 percent after the park)."""
    async def go():
        session = await session_factory()
        record = session.page(session.focused)
        await record.page.set_content(
            "<script>setInterval(()=>{const t=performance.now();"
            "while(performance.now()-t<12){}},16)</script>")
        await asyncio.sleep(1.0)
        pids = sorted(session.journal.pids)

        def cpu():
            return sum(hygiene.cpu_time(p) or 0.0 for p in pids)

        start = cpu()
        await asyncio.sleep(2.0)
        busy = cpu() - start
        result = await MANAGER.park_idle(force=True)
        await asyncio.sleep(0.5)
        start = cpu()
        await asyncio.sleep(2.0)
        quiet = cpu() - start
        assert result["parked"] == [record.handle]
        assert record.page.url == "about:blank"
        assert busy > 0.1, f"the busy page never burned CPU ({busy}s)"
        assert quiet < busy * 0.5, (
            f"parking did not reduce CPU: {busy}s busy, {quiet}s parked")

    run(go())


def test_the_startup_reaper_runs_before_the_first_browser(session_factory):
    async def go():
        MANAGER.startup_reap = None
        session = await session_factory()
        assert MANAGER.startup_reap is not None
        assert "killed" in MANAGER.startup_reap
        del session

    run(go())


# ------------------------------------------------------------- the handles


def test_unknown_handles_refuse_by_naming_the_mint_rule(session_factory):
    async def go():
        await session_factory()
        with pytest.raises(TargetNotFound) as caught:
            MANAGER.locate("p999")
        assert "minted by" in str(caught.value)
        with pytest.raises(TargetNotFound):
            MANAGER.session("s999")

    run(go())


def test_tabs_are_listed_opened_selected_and_closed(session_factory,
                                                    fixture_site):
    async def go():
        session = await session_factory()
        first = session.focused
        opened = await lite.manage_tabs(session=session.session_id,
                                        action="open",
                                        url=fixture_site + "/form")
        assert len(opened["pages"]) == 2
        second = opened["focused"]
        assert second != first
        await lite.manage_tabs(session=session.session_id, action="select",
                               page=first)
        assert (await lite.manage_tabs(session=session.session_id,
                                       action="focused"))["focused"] == first
        closed = await lite.manage_tabs(session=session.session_id,
                                        action="close", page=second)
        assert closed["closed"] == second
        assert "now gone" in closed["invalidated"]
        assert "delta read token" in closed["invalidated"]
        assert second not in [p["page"] for p in closed["pages"]]

    run(go())


def test_an_unknown_action_is_an_error_rather_than_a_default(session_factory):
    async def go():
        session = await session_factory()
        with pytest.raises(BadParams):
            await lite.manage_tabs(session=session.session_id, action="teleport")
        with pytest.raises(BadParams):
            await lite.manage_session(action="teleport")

    run(go())


# ------------------------------------------------------------ navigation


def test_navigate_returns_identity_status_robots_and_a_verdict(
        session_factory, fixture_site):
    async def go():
        session = await session_factory()
        page = session.focused
        result = await lite.navigate(page=page, url=fixture_site + "/form")
        assert result["status"] == 200
        assert result["url"].endswith("/form")
        assert result["title"] == "fixture form"
        assert result["changed"]["effect"] == "navigated"
        assert result["robots"]["checked"] is True
        assert result["verdict"]["wall"] is None
        assert result["history_depth"] >= 1

    run(go())


def test_history_is_tracked_by_ks4web_itself(session_factory, fixture_site):
    """KS4Web keeps its own page history, which is what lets the Firefox
    back/forward refusal name a working substitute instead of just saying no."""
    async def go():
        session = await session_factory()
        record = session.page(session.focused)
        await lite.navigate(page=record.handle, url=fixture_site + "/")
        await lite.navigate(page=record.handle, url=fixture_site + "/form")
        assert record.previous_url.endswith("/")
        assert len(record.history) >= 2

    run(go())


def test_back_and_forward_work_on_chromium(session_factory, fixture_site):
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/")
        await lite.navigate(page=page, url=fixture_site + "/form")
        result = await lite.navigate(page=page, action="back")
        assert result["url"].rstrip("/").endswith(fixture_site.rstrip("/"))

    run(go())


def test_goto_without_a_url_refuses(session_factory):
    async def go():
        session = await session_factory()
        with pytest.raises(BadParams):
            await lite.navigate(page=session.focused, action="goto")

    run(go())


def test_a_hung_navigation_frees_the_server(session_factory, fixture_site):
    """S7 measured a TimeoutError at 3,017 ms against a 3,000 ms budget with
    the browser fully usable afterward. A bounded per-operation timeout is
    what makes that true rather than hoped for."""
    async def go():
        session = await session_factory()
        page = session.focused
        with pytest.raises(Exception) as caught:
            await lite.navigate(page=page, url=fixture_site + "/hang",
                                timeout_ms=3000)
        assert "Timeout" in type(caught.value).__name__ or \
               "timeout" in str(caught.value).lower()
        # and the browser still answers afterward
        result = await lite.navigate(page=page, url=fixture_site + "/form")
        assert result["status"] == 200

    run(go())


# ---------------------------------------------------------- the lane rows


def test_capabilities_report_names_the_lane_and_its_gaps(session_factory):
    async def go():
        session = await session_factory()
        report = await lite.manage_session(action="capabilities",
                                           session=session.session_id)
        assert report["lane"] == "A"
        assert report["unsupported"] == []
        assert "response_body_read" in report["supported"]
        assert "S4" in report["measured"]

    run(go())


def test_manage_session_status_reports_the_hygiene_state(session_factory):
    async def go():
        session = await session_factory()
        status = await lite.manage_session(action="status")
        assert any(s["session"] == session.session_id
                   for s in status["sessions"])
        assert status["hygiene"]["job_object"]
        assert status["read_only"]["read_only"] is False
        # Item 44: what this machine has, and which lane suits what. Whether
        # anything is installed depends on the machine, so the shape and the
        # steering discipline are what get asserted, not a browser list.
        browsers = status["browsers"]
        assert browsers["default"]["lane"] == "A(chromium)"
        assert browsers["research"]["lane"].endswith("firefox)")
        assert "steering only" in browsers["note"]
        assert isinstance(browsers["installed"], list)

    run(go())


def test_a_headless_handoff_auto_upgrades_to_headed(session_factory):
    """Phase 7 field ruling: the intent of a handoff is a window a human
    can see, so a headless session upgrades to a headed one instead of
    refusing (the old BadParams naming '+headed' was a predictable
    round-trip). The old session closes, the new one is headed, and the
    response says exactly what moved."""
    async def go():
        session = await session_factory()
        old_id = session.session_id
        res = await lite.manage_session(action="handoff",
                                        session=old_id,
                                        reason="a login")
        assert res.get("upgraded") and old_id in res["upgraded"]
        new_id = res["session"]
        assert new_id != old_id
        assert old_id not in lite.MANAGER.sessions
        assert lite.MANAGER.session(new_id).spec.headless is False
        await lite.manage_session(action="close", session=new_id)

    run(go())


@pytest.mark.skipif(not FIREFOX_INSTALLED, reason="no installed Firefox")
def test_lane_b_moz_firefox_launches_with_no_remote(session_factory,
                                                    fixture_site):
    """S3's lane, and the safety requirement that rides with it.

    The author's Firefox may be open. This launch carries `-no-remote` and a
    freshly created throwaway profile, so it cannot be adopted by, and never
    touches, an instance the user is already running."""
    async def go():
        session = await session_factory(lane="B", channel="moz-firefox")
        assert session.spec.is_bidi_firefox
        assert "-no-remote" in session.spec.args
        result = await lite.navigate(page=session.focused,
                                     url=fixture_site + "/form")
        assert result["status"] == 200
        assert result["title"] == "fixture form"

        # The measured gap becomes a loud refusal rather than a silent lie.
        with pytest.raises(LaneUnsupported) as caught:
            await lite.navigate(page=session.focused, action="back")
        assert "page.url goes stale" in str(caught.value)

        report = await lite.manage_session(action="capabilities",
                                           session=session.session_id)
        gaps = [row["capability"] for row in report["unsupported"]]
        assert "history_navigation" in gaps
        assert "request_body_read" in gaps

    run(go())


# ------------------------------------------------- the projection, live


def test_get_page_view_projects_a_real_page_under_budget(session_factory,
                                                         fixture_site):
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/form")
        result = await lite.get_page_view(page=page)
        assert result["budget"]["used"] <= 5000
        assert result["budget"]["estimator"] == "o200k_base"
        assert "## 1 IDENTITY" in result["projection"]
        assert "COMPLETENESS" in result["projection"]
        assert '"Name"' in result["projection"]

    run(go())


def test_the_budget_holds_on_a_fifty_thousand_node_page(session_factory,
                                                        fixture_site):
    """The property the whole design rests on: a page view never exceeds its
    budget regardless of page size."""
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/big?n=50000")
        for budget in (5000, 2500, 1500):
            result = await lite.get_page_view(page=page,
                                              budget_tokens=budget)
            assert result["budget"]["used"] <= budget, (
                f"a {budget}-token read returned "
                f"{result['budget']['used']} tokens")

        # And the other half of the property, which used to be tested by
        # hardcoding a budget a few tokens above the floor and therefore
        # broke whenever the floor moved by a line. A refusal that quotes a
        # number is making a claim, so the claim is what gets tested: read at
        # the budget the refusal named and it must fit. This is DESIGN 3.3a's
        # executable-price rule applied to the floor message itself.
        try:
            await lite.get_page_view(page=page, budget_tokens=200)
            raise AssertionError("a 200-token budget did not refuse")
        except Exception as exc:
            message = str(exc)
        assert "below this page's floor projection" in message
        named = int(message.split("Raise budget_tokens to at least ")[1]
                    .split(",")[0])
        result = await lite.get_page_view(page=page, budget_tokens=named)
        assert result["budget"]["used"] <= named, (
            f"the floor refusal named {named} tokens and a read at exactly "
            f"{named} returned {result['budget']['used']}")

    run(go())


def test_the_subagent_recipe_holds(session_factory, fixture_site):
    """`budget_tokens=2500` is documented as the subagent-safe setting, and
    the number tracks a movable, remotely delivered cap rather than a
    constant. What has to hold is that the read is not mutilated at it."""
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/big?n=25000")
        result = await lite.get_page_view(page=page, budget_tokens=2500)
        assert result["budget"]["used"] <= 2500
        text = result["projection"]
        assert "## 1 IDENTITY" in text and "COMPLETENESS" in text
        assert "NEXT CALLS" in text

    run(go())


def test_detail_scales_the_budget(session_factory, fixture_site):
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/big?n=10000")
        lite_read = await lite.get_page_view(page=page, detail="lite")
        full_read = await lite.get_page_view(page=page, detail="full")
        assert lite_read["budget"]["limit"] == 2500
        assert full_read["budget"]["limit"] == 10000

    run(go())


def test_an_impossible_budget_refuses_by_naming_the_floor(session_factory,
                                                          fixture_site):
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/big?n=5000")
        with pytest.raises(RangeOutOfBounds) as caught:
            await lite.get_page_view(page=page, budget_tokens=200)
        assert "floor projection" in str(caught.value)

    run(go())


def test_the_parameters_that_are_still_unbuilt_refuse_honestly(
        session_factory, fixture_site):
    """`location` and `since` landed in Phase 2, and Phase 3 ruled on
    `include_hidden`: the ORIENTATION never carries hidden content, and the
    refusal names the labeled get_text route instead. `cursor` is still
    unbuilt (spill-to-file paging was not built in Phase 5) and refuses
    honestly rather than returning something plausible."""
    async def go():
        session = await session_factory()
        page = session.focused
        await lite.navigate(page=page, url=fixture_site + "/form")
        with pytest.raises(Exception) as caught:
            await lite.get_page_view(page=page, cursor="aff:40")
        assert "not built" in str(caught.value)
        with pytest.raises(Exception) as caught:
            await lite.get_page_view(page=page, include_hidden=True)
        assert "get_text" in str(caught.value)
        assert "separately labeled" in str(caught.value)

        # A ref nobody minted refuses by naming the mint rule, which is the
        # entry condition rather than a not-implemented stub.
        with pytest.raises(Exception) as caught:
            await lite.get_page_view(page=page, location={"region": "r99"})
        assert "never minted in this session" in str(caught.value)

        # And a read token nobody minted names the retention rule.
        with pytest.raises(Exception) as caught:
            await lite.get_page_view(page=page, since="rt999")
        assert "re-establish a baseline" in str(caught.value)

    run(go())


def test_closed_shadow_roots_are_counted_as_they_are_created(session_factory):
    """A closed shadow root is unreachable afterward, so the only honest way
    to report "0 closed (unreachable by any tool)" rather than guessing is to
    count them at creation. The hook is an init script on the context."""
    async def go():
        session = await session_factory()
        record = session.page(session.focused)
        await record.page.goto("about:blank")
        await record.page.set_content(
            "<div id=a></div><div id=b></div>"
            "<script>document.getElementById('a').attachShadow({mode:'closed'});"
            "document.getElementById('b').attachShadow({mode:'open'});</script>")
        result = await lite.get_page_view(page=record.handle)
        # The open root is read now (2026-09-06); the closed one is counted
        # and stays unreachable, which is the half this test is about.
        assert "1 open (traversed=yes, 1 read), 1 closed (unreachable by any " \
               "tool)" in result["projection"]

    run(go())
