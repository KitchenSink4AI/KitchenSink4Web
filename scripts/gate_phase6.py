"""The Phase 6 gate: the workflows engine, proven against real pages.

PLAN Phase 6 gate, stated as a threshold rather than a judgment call:

  1 record_is_the_substrate  a flow DONE through the real lite tools is
                             recovered from the audit log by save_workflow,
                             recorded as durable ANCHORS and never refs, and
                             the non-replayable calls (a page read) are
                             excluded
  2 replays_after_reload     the five-step flow dry-runs all-resolve and
                             then REPLAYS green after a full page reload,
                             where every ref is gone and only anchors remain
  3 replays_after_cosmetic   the same flow replays green after a cosmetic
                             DOM change (classes and decoys move, controls
                             do not), and the replayed action really fires
  4 dry_run_predicts_break   after a STRUCTURAL change (the name field and
                             the submit button lose their identity) the
                             mandatory dry run names exactly the broken
                             steps and a real run refuses OUTRIGHT rather
                             than half-running; nothing was executed
  5 gate_fails_closed        a gated submit step fails closed with no human
                             (the replay stops, batch semantics hold) and
                             COMPLETES on an explicit accept through the S8
                             elicitation seam
  6 no_eval_in_workflows     the replayable set is closed and excludes
                             evaluate_script, which is the whole point of
                             the pack (DESIGN 6.8): workflow reuse without an
                             arbitrary-code tool enabled
  7 orphan_census            every session the gate opens is closed and no
                             owned browser PID survives

Exit 0 only when every part is green.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web import confirm  # noqa: E402
from kitchensink4web.engine import hygiene  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402
from kitchensink4web.errors import ValidationFailed  # noqa: E402
from kitchensink4web.ops import lite, workflows  # noqa: E402
from kitchensink4web.policy import (audit, budgets, credentials,  # noqa: E402
                                    gates, readonly)

GATES = ROOT / "gates"
PATH = "tests/fixtures/workflow_site.html"
PARTS: dict[str, dict] = {}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _fresh_state(tmp: Path) -> None:
    audit.LOG = audit.AuditLog()
    budgets.BOOK = budgets.BudgetBook()
    audit.STATE_DIR = tmp
    credentials.VAULT.clear()
    readonly.apply(False)


async def _do(fn, **kwargs):
    result = await fn(**kwargs)
    audit.LOG.record(fn.__name__, "ok", args=kwargs)
    return result


async def _open(site, query=""):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await _do(lite.navigate, page=page, url=f"{site}/{PATH}{query}")
    return session, page


async def _record(page):
    await _do(lite.type_text, page=page,
              location={"role": "textbox", "name": "Your name"},
              text="Ada", clear_first=True)
    await _do(lite.fill_form, page=page,
              fields=[{"role": "combobox", "name": "Team", "value": "Blue"}])
    await _do(lite.click, page=page,
              location={"role": "checkbox", "name": "Subscribe to updates"})
    await _do(lite.click, page=page, location={"text": "Add member"})


async def gate_record_and_replays(site, tmp: Path) -> None:
    _fresh_state(tmp)
    session, page = await _open(site)
    await _record(page)
    saved = await workflows.save_workflow(session=session.session_id,
                                          name="add-member")
    import json as _j
    doc = _j.loads(workflows._path_of("add-member").read_text(
        encoding="utf-8"))
    anchors_only = all("ref" not in s for s in doc["steps"])
    tools = [s["tool"] for s in doc["steps"]]
    # The five-step flow PLAN's gate names: the navigate that opened the
    # page is a legitimate replayable first step, then the four actions.
    expected = ["navigate", "type_text", "fill_form", "click", "click"]
    PARTS["record_is_the_substrate"] = {
        "green": saved["steps"] == 5 and tools == expected and anchors_only,
        "steps": saved["steps"], "tools": tools, "anchors_only": anchors_only}

    # After a full reload.
    await _do(lite.navigate, page=page, action="reload")
    dry = await workflows.run_workflow(name="add-member", page=page,
                                       dry_run=True)
    reload_ok = not dry["would_fail"]
    real = await workflows.run_workflow(name="add-member", page=page,
                                        dry_run=False)
    PARTS["replays_after_reload"] = {
        "green": reload_ok and real["stopped_at"] is None,
        "would_fail": dry["would_fail"], "completed": real["completed"]}

    # After a cosmetic change.
    session2, page2 = await _open(site, query="?cosmetic=1")
    cos = await workflows.run_workflow(name="add-member", page=page2,
                                       dry_run=False)
    added = await session2.pages[page2].page.evaluate("() => window.__added")
    PARTS["replays_after_cosmetic"] = {
        "green": cos["stopped_at"] is None and added == 1,
        "completed": cos["completed"], "added": added}

    # After a structural change: dry run names the break, real run refuses.
    session3, page3 = await _open(site, query="?structural=1")
    struct = await workflows.run_workflow(name="add-member", page=page3,
                                          dry_run=True)
    broken = [struct["steps"][i]["line"] for i in struct["would_fail"]]
    names_name = any("Your name" in b for b in broken)
    names_btn = any("Add member" in b for b in broken)
    refused = False
    added_after = 1
    try:
        await workflows.run_workflow(name="add-member", page=page3,
                                     dry_run=False)
    except ValidationFailed:
        refused = True
        added_after = await session3.pages[page3].page.evaluate(
            "() => window.__added")
    PARTS["dry_run_predicts_break"] = {
        "green": bool(struct["would_fail"]) and names_name and names_btn
                 and refused and added_after == 0,
        "would_fail": struct["would_fail"], "refused": refused,
        "added_after_refusal": added_after}


async def gate_fails_closed(site, tmp: Path) -> None:
    _fresh_state(tmp)
    session, page = await _open(site)
    await _do(lite.type_text, page=page,
              location={"role": "textbox", "name": "Your name"},
              text="Bo", clear_first=True)
    await _do(lite.fill_form, page=page,
              fields=[{"role": "textbox", "name": "Your name",
                       "value": "Bo2"}])
    await workflows.save_workflow(session=session.session_id, name="gated")
    # Force the last step to submit.
    import json as _j
    wf = workflows._path_of("gated")
    doc = _j.loads(wf.read_text(encoding="utf-8"))
    doc["steps"][-1]["args"]["submit"] = True
    wf.write_text(_j.dumps(doc), encoding="utf-8")

    original = confirm.attempt

    async def refuse(_exc):
        return None
    confirm.attempt = refuse
    session2, page2 = await _open(site)
    closed = await workflows.run_workflow(name="gated", page=page2,
                                          dry_run=False)
    stopped = closed["stopped_at"] is not None and any(
        s.get("outcome") == "CONFIRMATION_REQUIRED"
        for s in closed["steps"] if s["status"] == "failed")

    async def accept(exc):
        token = (getattr(exc, "detail", {}) or {}).get("requestState")
        return gates.ENGINE.redeem(token, {"allow": True})
    confirm.attempt = accept
    session3, page3 = await _open(site)
    done = await workflows.run_workflow(name="gated", page=page3,
                                        dry_run=False)
    confirm.attempt = original
    PARTS["gate_fails_closed"] = {
        "green": stopped and done["stopped_at"] is None,
        "closed_stop": closed["stopped_at"], "accepted_stop": done["stopped_at"]}


def gate_no_eval() -> None:
    ok = ("evaluate_script" not in workflows.REPLAYABLE
          and set(workflows.REPLAYABLE) == {
              "navigate", "click", "type_text", "fill_form", "press_keys",
              "scroll", "wait_for"})
    PARTS["no_eval_in_workflows"] = {"green": ok,
                                     "replayable": list(workflows.REPLAYABLE)}


def gate_orphan_census(opened: set) -> None:
    """Every PID this gate spawned must be gone after close_all."""
    survivors = [pid for pid in opened if hygiene.alive(pid)]
    for pid in survivors:
        hygiene.kill(pid)
    PARTS["orphan_census"] = {
        "green": not survivors and not MANAGER.sessions,
        "opened": len(opened), "survivors": survivors}


async def main() -> int:
    import tempfile
    handler = functools.partial(_Quiet, directory=str(ROOT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{httpd.server_address[1]}"
    opened: set = set()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            await gate_record_and_replays(site, tmp)
            await gate_fails_closed(site, tmp)
            gate_no_eval()
        finally:
            opened |= set(MANAGER.owned_pids())
            await MANAGER.close_all()
            httpd.shutdown()
            credentials.VAULT.clear()
            readonly.apply(False)
    gate_orphan_census(opened)

    GATES.mkdir(exist_ok=True)
    out = GATES / "phase6.json"
    green = all(p["green"] for p in PARTS.values())
    out.write_text(json.dumps(
        {"measured_kst": time.strftime("%Y-%m-%d %H:%M"),
         "phase": 6,
         "corpus": "workflow_site.html (synthetic, deterministic, never "
                   "networked) plus its cosmetic and structural variants",
         "lane": "A(chromium) headless",
         "confirmation_channel": "elicitation (S8: MRTR does not round-trip "
                                 "on the installed client; the gate rides "
                                 "elicitation and fails closed)",
         "parts": PARTS, "green": green}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    for name, part in PARTS.items():
        print(f"  {'GREEN' if part['green'] else 'RED  '}  {name}")
    print(f"PHASE 6 GATE {'GREEN' if green else 'RED'}")
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
