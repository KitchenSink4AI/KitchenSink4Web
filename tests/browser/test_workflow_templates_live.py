"""Parameterized workflows, replayed for real: record once, run with values.

Red-first pins W1 and W10 for feature #10. The unit file next door carries
the file rules and the security boundary; this one carries the only claim
that needs a browser to be true, which is that a recorded flow replays with
the caller's values in place of the recorded ones.

The fixture is the Phase 6 replay target, unchanged.
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
from kitchensink4web.ops import lite, workflows
from kitchensink4web.policy import audit, budgets, credentials, readonly

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
    try:
        result = await fn(**kwargs)
    except Exception as exc:
        audit.LOG.record(fn.__name__, getattr(exc, "code", None) or "error",
                         args=kwargs)
        raise
    audit.LOG.record(fn.__name__, "ok", args=kwargs)
    return result


async def _open(site):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{PATH}")
    await lite.get_page_view(page=page)
    return session, page


async def _record_and_save(site, name, parameters):
    session, page = await _open(site)
    await _do(lite.type_text, page=page, location={"css": "#name"},
              text="Ada Lovelace")
    await _do(lite.click, page=page, location={"css": "#add"})
    saved = await workflows.save_workflow(session=session.session_id,
                                          name=name, parameters=parameters)
    return session, page, saved


def test_a_recorded_flow_replays_with_the_callers_value(site):
    """W1, the headline. Record a name, save it as a parameter, replay with
    a different one, and the page receives the NEW value."""
    async def go():
        _s, _p, saved = await _record_and_save(
            site, "member", [{"name": "member", "example": "Ada Lovelace",
                              "description": "who to add"}])
        assert saved["parameters"][0]["bound_to"] == [
            "step 0 args.text [0:12]"]
        assert "<member>" in saved["step_list"][0]

        _s2, page2 = await _open(site)
        out = await workflows.run_workflow(
            name="member", page=page2, dry_run=False,
            parameters={"member": "Grace Hopper"})
        assert out["stopped_at"] is None, out["steps"]
        _sess, record = MANAGER.locate(page2)
        roster = await record.page.evaluate(
            "() => document.getElementById('roster').textContent")
        assert "Grace Hopper" in roster
        assert "Ada Lovelace" not in roster
        assert out["parameters"]["applied"][0]["value_length"] == 12

    run(go())


def test_the_dry_run_shows_the_filled_value_not_the_template(site):
    """W10. A dry run that showed the recorded value rather than what will
    actually be typed would be exactly the wrong information at exactly the
    moment it matters."""
    async def go():
        await _record_and_save(
            site, "member2", [{"name": "member", "example": "Ada Lovelace"}])
        _s2, page2 = await _open(site)
        out = await workflows.run_workflow(
            name="member2", page=page2, dry_run=True,
            parameters={"member": "Grace Hopper"})
        assert out["parameters"]["supplied"] == ["member"]
        assert out["would_fail"] == []
        _sess, record = MANAGER.locate(page2)
        assert await record.page.evaluate("() => window.__added") == 0

    run(go())


def test_a_workflow_recorded_from_a_batch_can_be_parameterized(site):
    """The two features meet here: a batch leaves a per-step replay trail,
    save_workflow expands it, and a parameter binds inside one of those
    steps. Without the replay_steps expansion this workflow would have one
    step and the parameter would bind to the wrong thing."""
    async def go():
        session, page = await _open(site)
        await _do(lite.batch, page=page, steps=[
            {"find": {"query": "Your name"}, "action": "type",
             "text": "Ada Lovelace"},
            {"find": {"query": "Add member"}, "action": "click"},
        ])
        saved = await workflows.save_workflow(
            session=session.session_id, name="from-batch",
            parameters=[{"name": "member", "example": "Ada Lovelace"}])
        assert saved["steps"] == 2, saved["step_list"]
        assert saved["parameters"][0]["bound_to"] == [
            "step 0 args.text [0:12]"]

    run(go())
