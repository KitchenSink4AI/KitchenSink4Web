"""Phase 6 workflows engine, the parts that need no browser.

The browser gate (`tests/browser/test_phase6_workflows.py`) proves record ->
save -> dry-run -> replay end to end on live Chromium. This file pins the
pure logic: slug rules, save from a synthetic audit log, the anchor-only
recording (never refs), list and load, the replay resolver's page-key and
tier discipline, and the closed replayable set.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web.anchors import Outcome, ladder
from kitchensink4web.errors import BadParams, TargetNotFound, ValidationFailed
from kitchensink4web.ops import workflows
from kitchensink4web.policy import audit


@pytest.fixture(autouse=True)
def scratch(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    yield


def _seed_flow():
    """Three replayable actions plus a non-replayable one, in the log."""
    audit.LOG.record("navigate", "ok", args={},
                     replay={"tool": "navigate",
                             "args": {"url": "http://x/a", "wait_until": "load"}})
    audit.LOG.record("click", "ok", args={},
                     replay={"tool": "click", "args": {"button": "left"},
                             "anchor": {"role": "button", "name": "Add",
                                        "page_key": "http://x/a"},
                             "anchor_id": "aXXXXX", "page_key": "http://x/a"})
    audit.LOG.record("get_page_view", "ok", args={})  # not replayable
    audit.LOG.record("type_text", "ok", args={},
                     replay={"tool": "type_text", "args": {"text": "hi"},
                             "anchor": {"role": "textbox", "name": "Name",
                                        "page_key": "http://x/a"},
                             "anchor_id": "aYYYYY", "page_key": "http://x/a"})


def test_slug_rules():
    assert workflows._slug("Nightly Report") == "nightly-report"
    with pytest.raises(BadParams):
        workflows._slug("has spaces and !!!")
    with pytest.raises(BadParams):
        workflows._slug("")


def test_save_pulls_only_replayable_actions_and_records_anchors():
    _seed_flow()
    saved = asyncio.run(workflows.save_workflow(name="flow"))
    assert saved["steps"] == 3          # the get_page_view is excluded
    doc_tools = [s.split(":")[1].strip().split()[0]
                 for s in saved["step_list"]]
    assert doc_tools == ["navigate", "click", "type_text"]
    # Anchors, never refs: the file carries anchor descriptors.
    import json
    doc = json.loads(workflows._path_of("flow").read_text(encoding="utf-8"))
    for step in doc["steps"]:
        assert "ref" not in step
        if step["tool"] != "navigate":
            assert step["anchor"]["role"]


def test_save_refuses_when_nothing_replayable():
    audit.LOG.record("get_page_view", "ok", args={})
    with pytest.raises(ValidationFailed):
        asyncio.run(workflows.save_workflow(name="empty"))


def test_save_slice_selects_a_range():
    _seed_flow()
    saved = asyncio.run(workflows.save_workflow(name="slice", start_index=1,
                                                end_index=2))
    assert saved["steps"] == 1
    assert "click" in saved["step_list"][0]


def test_list_and_load_missing():
    _seed_flow()
    asyncio.run(workflows.save_workflow(name="flow"))
    listing = asyncio.run(workflows.list_workflows())
    assert [w["name"] for w in listing["workflows"]] == ["flow"]
    with pytest.raises(TargetNotFound):
        workflows._load("does-not-exist")


def test_run_needs_a_page():
    _seed_flow()
    asyncio.run(workflows.save_workflow(name="flow"))
    with pytest.raises(BadParams):
        asyncio.run(workflows.run_workflow(name="flow", page=None))


# ------------------------------------------------ the replay resolver

def _extraction(page_key, affordances):
    return {"identity": {"page_key": page_key, "url": page_key},
            "affordances": affordances}


def _aff(role, name, page_key, **extra):
    return {"anchor": {"role": role, "name": name, "page_key": page_key,
                       **extra}, "role": role, "name": name, "ref": "e1"}


def test_resolve_anchor_ok_on_a_unique_match():
    anchor = {"role": "button", "name": "Add", "page_key": "p"}
    data = _extraction("p", [_aff("button", "Add", "p")])
    out = ladder.resolve_anchor(anchor, data)
    assert out["outcome"] == Outcome.OK


def test_resolve_anchor_refuses_a_cross_page_match():
    anchor = {"role": "button", "name": "Add", "page_key": "p1"}
    data = _extraction("p2", [_aff("button", "Add", "p2")])
    out = ladder.resolve_anchor(anchor, data)
    assert out["outcome"] == Outcome.STALE
    assert out["reason"] == "page-key-differs"


def test_resolve_anchor_stale_when_gone():
    anchor = {"role": "button", "name": "Enroll", "page_key": "p"}
    data = _extraction("p", [_aff("button", "Add", "p")])
    out = ladder.resolve_anchor(anchor, data)
    assert out["outcome"] == Outcome.STALE
    assert out["nearest_by_name"] in (None, "Add")


def test_resolve_anchor_ambiguous_never_first_match():
    anchor = {"role": "link", "name": "Open", "page_key": "p"}
    data = _extraction("p", [_aff("link", "Open", "p"),
                             _aff("link", "Open", "p")])
    out = ladder.resolve_anchor(anchor, data)
    assert out["outcome"] == Outcome.AMBIGUOUS
    assert len(out["candidates"]) == 2


def test_resolve_anchor_survives_a_name_change_via_id():
    # The id key holds where role+name does not: the anchor recorded an id.
    # Since the field misdirect fix, a name change under an attribute key
    # PROCEEDS as a reported REBOUND rather than a silent OK: the element
    # is still found, and the transcript now says its label moved.
    anchor = {"role": "button", "name": "Add", "page_key": "p",
              "attr_id": "addbtn"}
    data = _extraction("p", [_aff("button", "Saved changes", "p",
                                  attr_id="addbtn")])
    out = ladder.resolve_anchor(anchor, data)
    assert out["outcome"] == Outcome.REBOUND
    assert out["tier"].startswith("id")
    assert "Saved changes" in out["now"]


def test_resolve_anchor_refuses_an_id_reassigned_across_roles():
    # The volatile-id theft shape (React useId on a remount): the stored id
    # now sits on an element of a DIFFERENT role. The attribute key must not
    # win; with no same-role match anywhere, the honest answer is STALE.
    anchor = {"role": "textbox", "name": "Add a comment", "page_key": "p",
              "attr_id": ":r2:"}
    data = _extraction("p", [_aff("searchbox", "Search", "p",
                                  attr_id=":r2:")])
    out = ladder.resolve_anchor(anchor, data)
    assert out["outcome"] == Outcome.STALE


def test_replayable_set_excludes_evaluate_script():
    assert "evaluate_script" not in workflows.REPLAYABLE
    assert set(workflows.REPLAYABLE) == {
        "navigate", "click", "type_text", "fill_form", "press_keys",
        "scroll", "wait_for"}
