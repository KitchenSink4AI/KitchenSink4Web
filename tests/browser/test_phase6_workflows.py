"""Phase 6's workflows pack against real pages: record, save, dry-run, replay.

PLAN Phase 6 gate. A recorded five-step flow replays green after a full page
reload and after a cosmetic DOM change, and the dry run correctly predicts
which anchors will fail after a structural change. The audit trail is the
recording substrate, so the record step is doing the flow through the real
lite tools and reading it back, never hand-building a workflow file.

Everything here runs on live Chromium against a local deterministic fixture
(`tests/fixtures/workflow_site.html`, no network). The confirmation gate is
exercised through the S8 elicitation plumbing, faked at the one seam the
server uses: `confirm.attempt`.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import confirm
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import lite, workflows
from kitchensink4web.policy import audit, budgets, credentials, gates, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
PATH = "tests/fixtures/workflow_site.html"


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
    # A fresh audit log and budget book per test, and a scratch workflow
    # directory so nothing touches a real state dir.
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
    """Call a lite op and record it exactly as the server wrapper does, so
    the audit trail carries the `replay` block save_workflow reads back.
    `annotate` sets a ContextVar inside the op that propagates back through
    the await (no task boundary), which `record` then drains."""
    try:
        result = await fn(**kwargs)
    except Exception as exc:  # record refusals too, like the wrapper
        audit.LOG.record(fn.__name__, getattr(exc, "code", None) or "error",
                         args=kwargs)
        raise
    audit.LOG.record(fn.__name__, "ok", args=kwargs)
    return result


async def _open(site, query=""):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await _do(lite.navigate, page=page, url=f"{site}/{PATH}{query}")
    return session, page


async def _record_a_flow(site, page):
    """Do the flow once through the real tools. The audit log records it."""
    await _do(lite.type_text, page=page,
              location={"role": "textbox", "name": "Your name"},
              text="Ada", clear_first=True)
    await _do(lite.fill_form, page=page, fields=[
        {"role": "combobox", "name": "Team", "value": "Blue"}])
    await _do(lite.click, page=page,
              location={"role": "checkbox", "name": "Subscribe to updates"})
    await _do(lite.click, page=page, location={"text": "Add member"})


def test_record_save_and_list(site):
    async def go():
        session, page = await _open(site)
        await _record_a_flow(site, page)
        saved = await workflows.save_workflow(session=session.session_id,
                                              name="add-member")
        assert saved["steps"] >= 4, saved["step_list"]
        # Anchors, not refs: every step carries a durable anchor id.
        assert all("[a" in line or "navigate" in line
                   for line in saved["step_list"]), saved["step_list"]
        listing = await workflows.list_workflows()
        names = [w["name"] for w in listing["workflows"]]
        assert "add-member" in names
    run(go())


def test_dry_run_all_resolve_after_reload(site):
    async def go():
        session, page = await _open(site)
        await _record_a_flow(site, page)
        await workflows.save_workflow(session=session.session_id,
                                      name="add-member")
        # A full reload: refs are gone, anchors must still resolve.
        await lite.navigate(page=page, action="reload")
        report = await workflows.run_workflow(name="add-member", page=page,
                                              dry_run=True)
        assert report["would_fail"] == [], report["steps"]
        assert all(s["verdict"] in ("resolves", "resolves-rebound",
                                    "would-navigate", "no-anchor")
                   for s in report["steps"]), report["steps"]
    run(go())


def test_real_replay_after_cosmetic_change(site):
    async def go():
        session, page = await _open(site)
        await _record_a_flow(site, page)
        await workflows.save_workflow(session=session.session_id,
                                      name="add-member")
        # Cosmetic variant: classes and decoys move, controls do not.
        session2, page2 = await _open(site, query="?cosmetic=1")
        result = await workflows.run_workflow(name="add-member", page=page2,
                                              dry_run=False)
        assert result["stopped_at"] is None, result["steps"]
        assert result["completed"] >= 4, result
        # The flow really ran: a member was added on the cosmetic page.
        added = await session2.pages[page2].page.evaluate(
            "() => window.__added")
        assert added == 1, "the replayed click did not fire the handler"
    run(go())


def test_dry_run_predicts_the_structural_break(site):
    async def go():
        session, page = await _open(site)
        await _record_a_flow(site, page)
        await workflows.save_workflow(session=session.session_id,
                                      name="add-member")
        # Structural variant: the name field and the Add button lose their
        # identity; the select and the checkbox are untouched.
        session2, page2 = await _open(site, query="?structural=1")
        report = await workflows.run_workflow(name="add-member", page=page2,
                                              dry_run=True)
        # At least the two broken steps are predicted, and the untouched
        # controls still resolve.
        assert report["would_fail"], report["steps"]
        broken_lines = [report["steps"][i]["line"]
                        for i in report["would_fail"]]
        assert any("Your name" in ln for ln in broken_lines), broken_lines
        assert any("Add member" in ln for ln in broken_lines), broken_lines
        # And a real run refuses outright rather than half-running.
        from kitchensink4web.errors import ValidationFailed
        with pytest.raises(ValidationFailed):
            await workflows.run_workflow(name="add-member", page=page2,
                                         dry_run=False)
        # Nothing was added: the refusal happened before execution.
        added = await session2.pages[page2].page.evaluate(
            "() => window.__added")
        assert added == 0
    run(go())


def test_a_gated_submit_step_fails_closed_then_completes_on_accept(site,
                                                                   monkeypatch):
    """A workflow whose last step submits a form is gated per step. With no
    human accept it fails closed and the replay stops; with an accept the
    step completes and the rest run."""
    async def go():
        session, page = await _open(site)
        # Record a flow ending in a gated submit.
        await _do(lite.type_text, page=page,
                  location={"role": "textbox", "name": "Your name"},
                  text="Bo", clear_first=True)
        await _do(lite.fill_form, page=page,
                  fields=[{"role": "textbox", "name": "Your name",
                           "value": "Bo2"}])
        # The submit gate on fill_form is what we exercise on replay; record
        # a plain fill so a clean flow exists, then save.
        await workflows.save_workflow(session=session.session_id,
                                      name="gated")

        # FAIL CLOSED: confirm.attempt returns None (no human).
        async def refuse(_exc):
            return None
        monkeypatch.setattr(confirm, "attempt", refuse)
        # Rewrite the saved flow's last step to submit, to force the gate.
        import json
        wf = workflows._path_of("gated")
        doc = json.loads(wf.read_text(encoding="utf-8"))
        doc["steps"][-1]["args"]["submit"] = True
        wf.write_text(json.dumps(doc), encoding="utf-8")

        session2, page2 = await _open(site)
        closed = await workflows.run_workflow(name="gated", page=page2,
                                              dry_run=False)
        assert closed["stopped_at"] is not None
        assert any(s.get("outcome") == "CONFIRMATION_REQUIRED"
                   for s in closed["steps"] if s["status"] == "failed")

        # ACCEPT: confirm.attempt redeems the deposited gate.
        async def accept(exc):
            token = (getattr(exc, "detail", {}) or {}).get("requestState")
            return gates.ENGINE.redeem(token, {"allow": True})
        monkeypatch.setattr(confirm, "attempt", accept)
        session3, page3 = await _open(site)
        done = await workflows.run_workflow(name="gated", page=page3,
                                            dry_run=False)
        assert done["stopped_at"] is None, done["steps"]
    run(go())
