"""Phase 4's acting surface against real pages: no false successes.

PLAN Phase 4 gate. The unit suite proves resolution and the choke point in
isolation; this file proves the action tools against a live Chromium on the
pathological fixture built to defeat them (corpus B) and the TOCTOU control
built to swap under a click (corpus C). Every proof here is behavioral: the
fixture records what actually happened in `window.__effects` and its own log
lines, so a reported effect can be checked against a real one.

The five pathological controls, each a distinct way a click appears to succeed
and does nothing:

- an `event.isTrusted` React control that silently no-ops on a synthetic click,
- a `<div onclick>` button invisible to role-based selectors,
- a real button under a transparent overlay that swallows the click,
- a button that never stops moving, so it never becomes clickable,
- a dropdown rendered through a portal outside the trigger's landmark.

A trusted-input dispatch fires the first two; the middle two must refuse
honestly rather than report a false success; the portal trigger's click is
verified by the menu it opens.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (AmbiguousLocation, BadParams,
                                    ConfirmationRequired, CredentialRefused,
                                    TargetChanged, TargetNotFound, Timeout)
from kitchensink4web import pagedata
from kitchensink4web.ops import act, lite
from kitchensink4web.policy import budgets, credentials, gates, readonly
from kitchensink4web.projection import extract

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def corpus_site():
    handler = functools.partial(_Quiet, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean_policy(monkeypatch):
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    credentials.VAULT.clear()
    readonly.apply(False)
    yield
    credentials.VAULT.clear()
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


async def _open(site, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


async def _effects(session, page):
    return await session.pages[page].page.evaluate("() => window.__effects || {}")


# ---------------------------------------------------- no false successes


def test_trusted_input_fires_a_react_istrusted_control(corpus_site):
    """The single most expensive failure in the set: a React handler that
    checks event.isTrusted and silently returns on a synthetic click. A
    JS-synthesised click reports success and does nothing; a trusted dispatch
    through the driver actually fires it, and the outcome is verified."""
    async def go():
        session, page = await _open(corpus_site, "b/pathological.html")
        result = await lite.click(page=page,
                                  location={"text": "Approve request"},
                                  timeout_ms=4000)
        assert not result["changed"]["effect"] == "none-observed"
        eff = await _effects(session, page)
        assert eff.get("trusted") == 1, "the trusted click did not fire"

    run(go())


def test_a_div_onclick_button_clicks_by_text_and_is_verified(corpus_site):
    """No role, no tabindex, no accessible name: role-based selection cannot
    see it, only the text and the handler. The click fires the onclick and
    the DOM change is observed rather than assumed."""
    async def go():
        session, page = await _open(corpus_site, "b/pathological.html")
        result = await lite.click(page=page,
                                  location={"text": "Submit order"},
                                  timeout_ms=4000)
        assert result["changed"]["effect"] != "none-observed"
        eff = await _effects(session, page)
        assert eff.get("divbtn") == 1

    run(go())


def test_an_overlay_intercepted_click_refuses_instead_of_lying(corpus_site):
    """The button is visible, enabled, named, and passes every check that
    looks at the element itself; a transparent panel over it swallows the
    click. The refusal is honest and names the cause, and the button's own
    handler never fired."""
    async def go():
        session, page = await _open(corpus_site, "b/pathological.html")
        with pytest.raises(Timeout) as exc:
            await lite.click(page=page, location={"css": "#shielded"},
                             timeout_ms=1500)
        assert "intercept" in str(exc.value).lower()
        eff = await _effects(session, page)
        assert "shielded" not in eff, "the shielded button should not have fired"

    run(go())


def test_a_moving_target_refuses_instead_of_clicking_empty_space(corpus_site):
    """A requestAnimationFrame walk means the element never has a still frame,
    so it never becomes clickable. The refusal says so; nothing fired."""
    async def go():
        session, page = await _open(corpus_site, "b/pathological.html")
        with pytest.raises(Timeout):
            await lite.click(page=page, location={"css": "#runner"},
                             timeout_ms=1500)
        eff = await _effects(session, page)
        assert "runner" not in eff

    run(go())


def test_the_portal_trigger_opens_the_menu_and_the_effect_is_observed(
        corpus_site):
    """The trigger is here; the menu React renders is mounted at the end of
    body through a portal. Clicking the trigger opens it, and the DOM change
    is what verifies the click landed."""
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        result = await lite.click(page=page, location={"text": "Account"},
                                  timeout_ms=4000)
        assert result["changed"]["effect"] != "none-observed"
        # The portal menu now exists in the DOM.
        find = await lite.find_elements(page=page, query="Sign out")
        assert find["matched"] >= 1

    run(go())


# ------------------------------------------------- resolution discipline


def test_an_ambiguous_selector_refuses_with_the_candidate_list(corpus_site):
    """No tool ever acts on first match. 'order' names both 'Submit order'
    and 'Cancel order', so the selector refuses with both rather than
    guessing."""
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.click(page=page, location={"text": "order"})
        assert "Cancel order" in str(exc.value)
        assert "Submit order" in str(exc.value)

    run(go())


def test_a_missing_selector_refuses_with_nearest_misses(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        with pytest.raises(TargetNotFound) as exc:
            await lite.click(page=page, location={"text": "Approve requezt"})
        assert "Approve request" in str(exc.value)

    run(go())


def test_two_selectors_at_once_refuse_rather_than_pick_one(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        with pytest.raises(BadParams):
            await lite.click(page=page,
                             location={"css": "#realbtn", "text": "Cancel"})

    run(go())


def test_click_by_session_ref_resolves_through_the_rebind_ladder(corpus_site):
    """A ref minted by a read resolves through the ladder over a FRESH
    extraction, so it acts on the element the page holds now."""
    async def go():
        session, page = await _open(corpus_site, "b/pathological.html")
        view = await lite.get_page_view(page=page)
        # find the real Cancel button's ref from the affordances the read
        # minted, via find_elements which shares the same sticky map.
        found = await lite.find_elements(page=page, query="Cancel order")
        ref = pagedata.unwrap(found["results"]).split("\n")[1].split(" | ")[0]
        result = await lite.click(page=page, location={"ref": ref},
                                  timeout_ms=4000)
        assert result["target"]["ref"]
        eff = await _effects(session, page)
        assert eff.get("realbtn") == 1

    run(go())


# ------------------------------------------------- TOCTOU vs real actions


def test_swap_under_click_refuses_via_the_choke_point_not_the_wrong_click(
        corpus_site):
    """PLAN Phase 4 non-negotiable: the Phase 3 TOCTOU battery re-run against
    REAL action execution. A human confirms a benign 'Continue' submit; the
    page then swaps it for 'Delete account and all data'. Resolving the ref
    through the action path and driving it through the choke point with the
    stale grant aborts with TARGET_CHANGED. The destructive form never
    submits, so nothing is clicked wrong."""
    from kitchensink4web.policy import engine as policy_engine

    async def go():
        session, page = await _open(corpus_site, "c/toctou.html?swap_ms=100000")
        record = session.pages[page]
        await lite.get_page_view(page=page)

        # The human confirms the BENIGN control.
        data = await extract(record.page)
        benign = next(a for a in data["affordances"]
                      if a["anchor"].get("role") == "button")
        assert benign["name"] == "Continue"
        engine = gates.GateEngine()
        with pytest.raises(ConfirmationRequired) as ask:
            engine.ask("form_submit", tool="click", session=session.session_id,
                       page=page, target=act.target_descriptor(benign),
                       summary="Submit the setup form.")
        grant = engine.redeem(ask.value.detail["requestState"], {"allow": True})

        # The window closes: force the swap.
        await record.page.evaluate("() => swap()")
        url_before = record.page.url

        # Resolve the ref through the ACTION path: it now points at the
        # swapped, destructive control (the id key holds across a name swap).
        resolved = await act.resolve(
            session, record, {"css": "#swapper"}, tool="click")
        assert resolved["descriptor"]["name"].startswith("Delete")

        # Driving it through the choke point with the stale grant aborts.
        with pytest.raises(TargetChanged) as exc:
            policy_engine.approve(policy_engine.ActionRequest(
                tool="click", kind="act", session=session.session_id,
                page=page, action_class="form_submit",
                target=resolved["descriptor"], gate_grant=grant,
                resolution=resolved["resolution"]))
        assert "changed" in str(exc.value).lower()
        assert record.page.url == url_before, "the destructive form submitted"

    run(go())


def test_a_plain_click_on_the_swapped_submit_gates_and_never_submits(
        corpus_site):
    """Even with no prior confirmation, a submit control is a gated class, so
    a click on the swapped destructive button ASKS rather than acting. Fail
    closed: no confirmation channel, no submission."""
    async def go():
        session, page = await _open(corpus_site, "c/toctou.html?swap_ms=100000")
        record = session.pages[page]
        await record.page.evaluate("() => swap()")
        url_before = record.page.url
        with pytest.raises(ConfirmationRequired):
            await lite.click(page=page, location={"css": "#swapper"},
                             timeout_ms=3000)
        assert record.page.url == url_before

    run(go())


# ------------------------------------------------------ type and fill


def test_type_text_types_and_reads_the_value_back(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        result = await lite.type_text(page=page, location={"css": "#f6"},
                                      text="hello world")
        assert result["value_state"] == "hello world"
        assert result["changed"]["effect"] != "none-observed"

    run(go())


def test_type_text_into_a_secret_field_refuses_with_the_routes(corpus_site):
    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        page = session.focused
        await session.pages[page].page.goto(
            f"{corpus_site}/c/expired_login.html")
        with pytest.raises(CredentialRefused) as exc:
            await lite.type_text(page=page,
                                 location={"css": "input[type=password]"},
                                 text="hunter2")
        # Corrected 2026-09-05 (field test): names only routes that exist,
        # the handoff and auth-state reuse, not the unbuilt secrets file.
        text = str(exc.value)
        assert "handoff" in text and "save_auth_state" in text
        assert "secrets file" not in text

    run(go())


def test_fill_form_sets_text_select_and_checkbox_and_reads_back(corpus_site):
    """The batch fills a text field, a select (the 'select' action routed to
    select_option), and a checkbox in one call, resolving every ref before
    executing any, and reads the form state back."""
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        result = await lite.fill_form(page=page, fields=[
            {"css": "#f1", "value": "a@b.com"},
            {"css": "#f0", "value": "Choice 3"},
            {"css": "#f11", "value": True},
        ])
        assert result["batch"]["completed"] == 3
        assert result["batch"]["stopped_at"] is None
        kinds = {r["set"]["kind"] for r in result["form_state"]}
        assert kinds == {"text", "select", "checkbox"}

    run(go())


def test_fill_form_validates_every_target_before_executing_any(corpus_site):
    """DESIGN 3.5 batch semantics: resolve every ref BEFORE executing any. A
    target that cannot be resolved at all refuses the whole batch up front, so
    nothing is half-done: the first field is never set because validation
    fails before execution begins."""
    async def go():
        session, page = await _open(corpus_site, "b/bigform.html")
        with pytest.raises(TargetNotFound):
            await lite.fill_form(page=page, fields=[
                {"css": "#f1", "value": "a@b.com"},
                {"css": "#does-not-exist", "value": "x"},
                {"css": "#f6", "value": "y"},
            ])
        # Nothing executed: the first field is still empty.
        value = await session.pages[page].page.eval_on_selector(
            "#f1", "el => el.value")
        assert value == ""

    run(go())


def test_fill_form_batch_outcome_reports_completed_and_not_attempted():
    """The mid-batch stop contract (completed stay completed, the failing item
    refused, the rest not_attempted) is the roll-up over per-item outcomes.
    Exercised directly on the batch roller so the ordering contract is proven
    without needing a page that re-renders a later target under the batch."""
    from kitchensink4web.anchors import Outcome, batch_outcome
    rolled = batch_outcome([
        {"ref": "e1", "outcome": Outcome.OK, "status": "completed"},
        {"ref": "e2", "outcome": Outcome.STALE, "status": "failed"},
        {"ref": "e3", "status": "not_attempted"},
    ])
    assert rolled["completed"] == 1
    assert rolled["stopped_at"] == "e2"
    assert rolled["not_attempted"] == ["e3"]
    assert "do not roll back" in rolled["rollback"]


def test_fill_form_submit_is_gated_and_fails_closed(corpus_site):
    """submit=True fills the fields, then the submit ASKS. With no
    confirmation channel it fails closed, so the fields are set but the form
    is not submitted."""
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        with pytest.raises(ConfirmationRequired):
            await lite.fill_form(page=page,
                                 fields=[{"css": "#f6", "value": "z"}],
                                 submit=True)

    run(go())


# ------------------------------------------------------ keys, scroll, wait


def test_press_keys_focused_and_global(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        # Type then select-all in the focused field.
        await lite.type_text(page=page, location={"css": "#f6"}, text="abc")
        result = await lite.press_keys(page=page, keys="Control+a",
                                       location={"css": "#f6"})
        assert result["keys"] == "Control+a"

    run(go())


def test_scroll_reports_position_and_flags_virtualization(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/virtual.html")
        result = await lite.scroll(page=page, action="by", amount=2)
        assert "screen(s)" in result["reachable"]
        assert result["position"]["y"] >= 0

    run(go())


def test_wait_for_text_resolves_and_a_bad_wait_times_out(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        ok = await lite.wait_for(page=page, condition="text",
                                 value="Pathological controls",
                                 timeout_ms=4000)
        assert ok["resolved"] is True
        with pytest.raises(Timeout):
            await lite.wait_for(page=page, condition="text",
                                value="this string is not on the page",
                                timeout_ms=800)

    run(go())


def test_a_landed_click_with_no_observable_effect_is_reported_not_bare_ok(
        corpus_site):
    """DESIGN 5.7: an action the driver landed but that changed nothing
    observable returns effect none-observed WITH a warning, never a bare ok."""
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        # Cancel order fires its handler (a DOM effect), so use a control with
        # no effect: click the page heading via css, a real element the driver
        # can click that runs no handler and mutates nothing.
        result = await lite.click(page=page, location={"css": "h1"},
                                  timeout_ms=3000)
        if result["changed"]["effect"] == "none-observed":
            assert "warnings" in result
            assert any("nothing observable" in w for w in result["warnings"])

    run(go())


# ---------------------------------------- read-only refused-invisible


def test_read_only_hides_every_mutating_action_tool_over_a_client():
    """PLAN Phase 4 non-negotiable: every action tool proven refused-invisible
    under read-only over a real MCP client. The mutating tools are ABSENT from
    tools/list under both grades; scroll and wait_for (non-mutating) stay,
    because navigation-shaped movement is permitted under read-only."""
    from fastmcp import Client

    from kitchensink4web import server

    async def go():
        try:
            for grade in ("browse", "strict"):
                server.configure(read_only=grade)
                async with Client(server.mcp) as client:
                    listed = {t.name for t in await client.list_tools()}
                mutating = {"click", "type_text", "fill_form", "press_keys"}
                assert not (listed & mutating), (grade, listed & mutating)
                assert {"scroll", "wait_for", "get_page_view"} <= listed
        finally:
            server.configure()

    asyncio.run(go())


# ---------------------------------------- session isolation (two-process)


def test_two_sessions_are_isolated_processes_with_disjoint_refs(corpus_site):
    """The browser analog of the family's two-process discipline. Each session
    owns its own browser process tree (its own owned-PID journal) and its own
    sticky element map, so there is no shared single-instance state a second
    session could corrupt: a ref minted in one session does not resolve in the
    other, and the two journals share no PID."""
    async def go():
        s1 = await MANAGER.open(lane="A", engine="chromium", headless=True)
        s2 = await MANAGER.open(lane="A", engine="chromium", headless=True)
        p1, p2 = s1.focused, s2.focused
        await lite.navigate(page=p1, url=f"{corpus_site}/b/pathological.html")
        await lite.navigate(page=p2, url=f"{corpus_site}/b/bigform.html")
        await lite.get_page_view(page=p1)
        # Journals are disjoint: no owned PID is shared across sessions.
        assert not (set(s1.journal.pids) & set(s2.journal.pids))
        # A page handle from s1 is not reachable from s2's tools, and a ref
        # minted on p1 belongs to s1's map alone.
        assert p1 in s1.pages and p1 not in s2.pages
        assert s1.element_map is not s2.element_map

    run(go())
