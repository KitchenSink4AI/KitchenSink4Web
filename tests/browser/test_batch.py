"""`batch`: N-call fusion with per-step re-resolution, against live Chromium.

Red-first pins for feature #2. The fixture is
`tests/fixtures/batch_site.html`, served locally, no network.

The file is two halves, and the second is the larger one for the same reason
`test_find_and_act.py` is shaped that way.

**Half one: the fusion works.** A four-step comment flow costs one call, a
target that does not exist until an earlier step creates it is found when its
turn comes, and a re-rendered target is re-resolved rather than remembered.

**Half two: the fusion buys nothing it should not.** Step 1's ambiguity
refuses the whole batch with the page untouched. A gated step does not
re-run the steps that already completed, which is the `server._wrap` retry
trap and the single easiest thing here to get catastrophically wrong. Six
clicks spend six actions. A mid-run failure returns a partial report and
never a success flag. And the replay trail a batch leaves behind records
every step, not just the last one.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import re
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import confirm
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (AmbiguousLocation, BadParams,
                                    TargetNotFound, ValidationFailed)
from kitchensink4web.ops import lite, workflows
from kitchensink4web.policy import audit, budgets, credentials, gates, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
PATH = "tests/fixtures/batch_site.html"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(_Quiet, directory=str(ROOT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
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


async def _do(fn, **kwargs):
    """Call an op and record it exactly as the server wrapper does, so the
    audit trail carries what `save_workflow` reads back."""
    try:
        result = await fn(**kwargs)
    except Exception as exc:
        audit.LOG.record(fn.__name__, getattr(exc, "code", None) or "error",
                         args=kwargs)
        raise
    audit.LOG.record(fn.__name__, "ok", args=kwargs)
    return result


async def _open(site, query=""):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{PATH}{query}")
    await lite.get_page_view(page=page)
    return session, page


async def _counts(page):
    _sess, record = MANAGER.locate(page)
    return await record.page.evaluate("() => window.__counts")


# ------------------------------------------------------------- half one


def test_the_four_step_comment_flow_is_one_call(site):
    """B1, the headline. Click, type, click, wait: sixteen calls in the
    field measurement, one here."""
    async def go():
        _, page = await _open(site)
        out = await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Add a comment"}, "action": "click"},
            {"find": {"query": "Markdown value"}, "action": "type",
             "text": "the fusion works"},
            {"find": {"query": "Post comment", "role": "button"},
             "action": "click"},
            {"wait": {"condition": "text", "value": "the fusion works"}},
        ])
        assert out["outcome"] == "complete"
        assert out["completed"] == 4
        assert out["stopped_at"] is None
        assert out["not_attempted"] == []
        assert [s["status"] for s in out["steps"]] == ["completed"] * 4
        counts = await _counts(page)
        assert counts["open"] == 1 and counts["post"] == 1

        rows = [r for r in audit.LOG.read(limit=50)["records"]
                if r["tool"] == "batch"]
        assert len(rows) == 1, "a batch writes exactly one audit record"
        assert len(rows[0]["batch"]["lines"]) == 4

    run(go())


def test_a_later_target_that_does_not_exist_yet_is_not_a_preflight_failure(
        site):
    """B3. The composer does not exist until step 0 clicks. This is the
    normal case the feature exists to serve, so advisory pre-flight reports
    it and runs anyway."""
    async def go():
        _, page = await _open(site)
        out = await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Add a comment"}, "action": "click"},
            {"find": {"query": "Markdown value"}, "action": "type",
             "text": "later"},
        ])
        assert out["outcome"] == "complete"
        pre = out["preflight"]
        assert pre["mode"] == "advisory"
        verdicts = {s["step"]: s["verdict"] for s in pre["steps"]}
        assert verdicts[0] == "resolves"
        assert verdicts[1] == "not-found-now"
        assert "only step 0" in pre["note"]

    run(go())


def test_strict_preflight_refuses_what_advisory_reports(site):
    """The same batch, one word different, and the mode is the whole
    difference: strict makes a later step's absence a refusal."""
    async def go():
        _, page = await _open(site)
        with pytest.raises(ValidationFailed):
            await lite.batch(page=page, preflight="strict", steps=[
                {"find": {"query": "Add a comment"}, "action": "click"},
                {"find": {"query": "Markdown value"}, "action": "type",
                 "text": "later"},
            ])
        counts = await _counts(page)
        assert counts["open"] == 0, "strict refused, so nothing ran"

    run(go())


def test_per_step_re_resolution_survives_a_re_render(site):
    """B10. Step 0 replaces the node step 1 targets with a fresh node of the
    same accessible name. An implementation that cached step 1's pre-flight
    handle acts on a detached element."""
    async def go():
        _, page = await _open(site, "?rerender=1")
        out = await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Add a comment"}, "action": "click"},
            {"find": {"query": "Markdown value"}, "action": "type",
             "text": "fresh node"},
        ])
        assert out["outcome"] == "complete", out["steps"]
        _sess, record = MANAGER.locate(page)
        assert await record.page.evaluate(
            "() => document.getElementById('body').value") == "fresh node"

    run(go())


def test_a_location_step_acts_on_a_ref_already_held(site):
    """The second step kind. Forcing a redundant search on a ref the caller
    already holds would be a worse tool than the two-call path it replaces,
    and a location step reaches arguments find_and_act does not expose."""
    async def go():
        _, page = await _open(site)
        found = await lite.find_elements(page=page, query="Add a comment")
        ref = re.search(r"\b(e\d+) \|", found["results"]).group(1)
        out = await _do(lite.batch, page=page, steps=[
            {"location": {"ref": ref}, "action": "click", "click_count": 1},
        ])
        assert out["outcome"] == "complete"
        assert (await _counts(page))["open"] == 1

    run(go())


def test_an_assert_step_reports_state_not_a_timeout(site):
    """The assert kind exists because the failure REPORT differs, and that
    difference is the whole value: a zero-timeout wait would send the caller
    off tuning a timeout that was never the problem."""
    async def go():
        _, page = await _open(site)
        out = await _do(lite.batch, page=page, steps=[
            {"assert": {"condition": "text", "value": "Issue 1"}},
            {"assert": {"condition": "text", "value": "not on this page"}},
            {"find": {"query": "Add a comment"}, "action": "click"},
        ])
        assert out["outcome"] == "partial"
        assert out["stopped"]["code"] == "VALIDATION_FAILED"
        assert out["stopped_at"] == 1
        assert out["not_attempted"] == [2]
        assert (await _counts(page))["open"] == 0

    run(go())


# ------------------------------------------------------------- half two


def test_step_one_ambiguity_refuses_the_whole_batch(site):
    """B2. Two visible "Post comment" buttons. Nothing runs, and the assertion is
    on the page's own counters rather than on the absence of an exception
    from a later step."""
    async def go():
        _, page = await _open(site, "?ambiguous=1")
        before = await _counts(page)
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.batch(page=page, steps=[
                {"find": {"query": "Post comment", "role": "button"},
                 "action": "click"},
                {"find": {"query": "Add a comment"}, "action": "click"},
            ])
        text = str(exc.value)
        assert "Nothing in this batch was executed" in text
        assert await _counts(page) == before

    run(go())


def test_a_malformed_later_step_stops_the_good_first_one(site):
    """B12. The shape checks run before anything executes, so a good step 0
    beside a malformed step 1 does not run."""
    async def go():
        _, page = await _open(site)
        with pytest.raises(BadParams):
            await lite.batch(page=page, steps=[
                {"find": {"query": "Add a comment"}, "action": "click"},
                {"action": "click"},
            ])
        assert (await _counts(page))["open"] == 0

    run(go())


def test_a_ref_after_a_navigate_never_navigates(site):
    """B6. The refusal is free and structural, so the browser must not have
    moved when it fires."""
    async def go():
        _sess, page = await _open(site)
        record = MANAGER.locate(page)[1]
        url_before = record.page.url
        with pytest.raises(ValidationFailed):
            await lite.batch(page=page, steps=[
                {"navigate": {"url": "https://example.com/"}},
                {"location": {"ref": "e1"}, "action": "click"},
            ])
        assert record.page.url == url_before

    run(go())


def test_a_ref_from_another_page_refuses_upfront(site):
    """Structural check 6. A ref minted elsewhere refuses now rather than at
    step 4."""
    async def go():
        _, page = await _open(site)
        with pytest.raises((TargetNotFound, ValidationFailed)) as exc:
            await lite.batch(page=page, steps=[
                {"find": {"query": "Add a comment"}, "action": "click"},
                {"location": {"ref": "e999"}, "action": "click"},
            ])
        assert "e999" in str(exc.value)
        assert (await _counts(page))["open"] == 0

    run(go())


def test_the_gate_does_not_re_run_completed_steps(site, monkeypatch):
    """B4, the pin for the `server._wrap` re-run trap. `_wrap` catches
    ConfirmationRequired at the TOOL boundary and re-runs the whole call, so
    a batch whose step 2 is gated would click steps 0 and 1 twice. The
    fixture's own counters are the proof, not the step report."""
    async def go():
        steps = [
            {"find": {"query": "Add a comment"}, "action": "click"},
            {"find": {"query": "Tick 1", "role": "button"},
             "action": "click"},
            {"find": {"query": "Save account", "role": "button"},
             "action": "click"},
            {"find": {"query": "Tick 2", "role": "button"},
             "action": "click"},
        ]

        # FAIL CLOSED: no human answers.
        async def refuse(_exc):
            return None
        monkeypatch.setattr(confirm, "attempt", refuse)
        _, page = await _open(site, "?counters=1")
        closed = await _do(lite.batch, page=page, steps=steps)
        assert closed["outcome"] == "partial"
        assert closed["completed"] == 2
        assert closed["stopped_at"] == 2
        assert closed["stopped"]["code"] == "CONFIRMATION_REQUIRED"
        counts = await _counts(page)
        assert counts["open"] == 1, counts
        assert counts["tick1"] == 1, counts
        assert counts.get("tick2") in (None, 0)

        # ACCEPT: the gate is redeemed for THAT step and only that step
        # retries. Steps 0 and 1 still show exactly one click each.
        async def accept(exc):
            token = (getattr(exc, "detail", {}) or {}).get("requestState")
            return gates.ENGINE.redeem(token, {"allow": True})
        monkeypatch.setattr(confirm, "attempt", accept)
        _, page2 = await _open(site, "?counters=1")
        done = await _do(lite.batch, page=page2, steps=steps)
        assert done["outcome"] == "complete", done["steps"]
        assert done["completed"] == 4
        counts2 = await _counts(page2)
        assert counts2["open"] == 1, counts2
        assert counts2["tick1"] == 1, counts2
        assert counts2["save"] == 1, counts2

    run(go())


def test_the_budget_is_charged_once_per_step(site, monkeypatch):
    """B5. Batching saves calls and tokens, never budget. Charging one unit
    for a whole batch would turn a 300-action budget into a 300-BATCH
    budget, which at 20 steps a batch is 6,000 actions."""
    monkeypatch.setenv("KS4WEB_MAX_ACTIONS", "3")

    async def go():
        session, page = await _open(site, "?counters=1")
        out = await _do(lite.batch, page=page, steps=[
            {"find": {"query": f"Tick {i}", "role": "button"},
             "action": "click"} for i in range(1, 6)])
        assert out["outcome"] == "partial"
        assert out["completed"] == 3
        assert out["stopped_at"] == 3
        assert out["steps"][3]["outcome"] == "BUDGET_EXHAUSTED"
        snap = budgets.BOOK.snapshot(session.session_id)
        assert out["spend"]["actions"] == 3
        assert snap["counters"]["actions"] == 3

    run(go())


def test_three_batches_of_one_cost_what_one_batch_of_three_costs(site):
    """B5, second assertion. The fusion is not a discount."""
    async def go():
        session, page = await _open(site, "?counters=1")
        for i in (1, 2, 3):
            await lite.batch(page=page, steps=[
                {"find": {"query": f"Tick {i}", "role": "button"},
                 "action": "click"}])
        singles = budgets.BOOK.snapshot(session.session_id)["counters"][
            "actions"]

        session2, page2 = await _open(session and site, "?counters=1")
        await lite.batch(page=page2, steps=[
            {"find": {"query": f"Tick {i}", "role": "button"},
             "action": "click"} for i in (4, 5, 6)])
        fused = budgets.BOOK.snapshot(session2.session_id)["counters"][
            "actions"]
        assert singles == fused == 3

    run(go())


def test_a_partial_run_never_claims_completeness(site):
    """B9. A batch that did something RETURNS a report; raising would
    discard the record of what already executed, and browser actions do not
    roll back."""
    async def go():
        _, page = await _open(site, "?ambiguous=1")
        out = await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Add a comment"}, "action": "click"},
            {"find": {"query": "Post comment", "role": "button"},
             "action": "click"},
            {"wait": {"condition": "text", "value": "never"}},
        ])
        assert out["outcome"] == "partial"
        assert out["completed"] == 1
        assert out["stopped_at"] == 1
        assert out["stopped"]["code"] == "AMBIGUOUS_LOCATION"
        assert out["not_attempted"] == [2]
        assert "do not roll back" in out["rollback"]
        counts = await _counts(page)
        assert counts["open"] == 1 and counts["post"] == 0
        assert counts["decoy"] == 0

    run(go())


def test_page_authored_text_in_the_result_is_labelled(site):
    """§0.3. Accessible names ride the labeled envelope, in the result and
    in the refusal both."""
    async def go():
        _, page = await _open(site)
        out = await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Add a comment"}, "action": "click"}])
        assert "page_data" in out
        assert "steps[].target.name" in out["page_data"]["covers"]

    run(go())


# --------------------------------------------------- the recording trail


def test_the_replay_trail_records_every_step_not_the_last_one(site):
    """B7, the pin for the defect this feature would otherwise introduce.
    `_drain_annotations` merges annotations into one dict, so a per-step
    `replay` annotation would leave a five-step batch saved as ONE step, and
    the workflow would replay wrong, quietly."""
    async def go():
        session, page = await _open(site, "?counters=1")
        await _do(lite.batch, page=page, steps=[
            {"find": {"query": f"Tick {i}", "role": "button"},
             "action": "click"} for i in range(1, 6)])
        saved = await workflows.save_workflow(session=session.session_id,
                                              name="five-ticks")
        assert saved["steps"] == 5, saved["step_list"]
        assert len(saved["step_list"]) == 5

    run(go())


def test_a_js_wait_step_is_never_recordable(site, monkeypatch):
    """B8. `wait_for` already refuses to record a js predicate ("a workflow
    must never smuggle evaluate-shaped work past the gate that names it").
    A batch must not become the second door onto it."""
    async def accept(exc):
        token = (getattr(exc, "detail", {}) or {}).get("requestState")
        return gates.ENGINE.redeem(token, {"allow": True})
    monkeypatch.setattr(confirm, "attempt", accept)

    async def go():
        session, page = await _open(site)
        await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Add a comment"}, "action": "click"},
            {"wait": {"condition": "js", "value": "() => true"}},
        ])
        saved = await workflows.save_workflow(session=session.session_id,
                                              name="js-wait")
        assert saved["steps"] == 1, saved["step_list"]
        assert not any("wait" in line for line in saved["step_list"])

    run(go())
