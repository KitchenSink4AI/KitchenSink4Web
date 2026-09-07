"""Parameterized workflows: the file rules, the security boundary, the run.

Red-first pins for feature #10, the half that needs no browser. Everything
here is a file on disk and a call that refuses before a page is ever needed,
which is itself the property: a workflow whose parameters do not add up is
refused on the declaration, not half way through a replay.

THE BOUNDARY, and it is the whole design: a parameter is DATA. It fills in
what gets typed, or a piece of a URL, and nothing else. It never names an
element, a wait condition, a key, or a piece of script. The slot lives OUT
OF BAND as a span, so a recorded literal containing `{{` is just a literal
and substitution is a splice by index rather than a parse.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kitchensink4web.errors import (BadParams, NavigationBlocked,
                                    ValidationFailed)
from kitchensink4web.ops import workflows
from kitchensink4web.policy import audit


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    yield tmp_path


def _write(name: str, doc: dict) -> None:
    path = workflows._path_of(name)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _record(tool: str, args: dict, anchor: dict | None = None) -> dict:
    return {"tool": tool, "args": args, "anchor": anchor,
            "anchor_id": "a1" if anchor else None,
            "page_key": "https://example.com/new", "url": "https://example.com/new"}


ANCHOR = {"page_key": "https://example.com/new", "role": "textbox",
          "name": "Title", "landmark": "form", "landmark_label": "",
          "attr_id": "title", "attr_testid": "", "attr_name": "title"}


def _doc(steps, parameters=None) -> dict:
    doc = {"name": "wf", "created": "2026-09-07T00:00:00", "session": "s1",
           "origins": ["example.com"], "steps": steps}
    if parameters is not None:
        doc["parameters"] = parameters
    return doc


def _log(rows):
    """Put replayable rows in the audit log the way a real session would."""
    for row in rows:
        audit.annotate(replay=row, url=row.get("url"))
        audit.LOG.record(row["tool"], "ok", args={})


def save(**kwargs):
    return asyncio.run(workflows.save_workflow(**kwargs))


def run(**kwargs):
    return asyncio.run(workflows.run_workflow(**kwargs))


# ------------------------------------------------------------ at SAVE


def test_a_parameter_that_binds_nothing_refuses_and_lists_what_is_there():
    """W11, half one. Never save a workflow with a dangling parameter."""
    _log([_record("type_text", {"text": "D-pad bug"}, ANCHOR)])
    with pytest.raises(BadParams) as exc:
        save(name="wf", parameters=[{"name": "title", "example": "nothing"}])
    text = str(exc.value)
    assert "title" in text and "D-pad bug" in text
    assert not workflows._path_of("wf").exists()


def test_a_bare_name_says_what_it_needs():
    _log([_record("type_text", {"text": "D-pad bug"}, ANCHOR)])
    with pytest.raises(BadParams) as exc:
        save(name="wf", parameters=["title"])
    text = str(exc.value)
    assert "example" in text and "field" in text
    assert "D-pad bug" in text


def test_a_malformed_parameter_name_refuses():
    _log([_record("type_text", {"text": "D-pad bug"}, ANCHOR)])
    for bad in ("Title", "1st", "a" * 33, "my-title"):
        with pytest.raises(BadParams):
            save(name="wf", parameters=[{"name": bad, "example": "D-pad"}])


def test_condition_is_not_slottable():
    """W3. A slot on `args.condition` would let a recorded text wait become
    a js wait, which is the hole the fix wave closed from the other side."""
    _log([_record("wait_for", {"condition": "text", "value": "Saved"})])
    with pytest.raises(BadParams) as exc:
        save(name="wf",
             parameters=[{"name": "c", "step": 0, "field": "args.condition"}])
    assert "args.value" in str(exc.value)
    assert not workflows._path_of("wf").exists()


def test_capture_by_example_ambiguity_refuses_and_all_binds_both():
    """W14. Nothing binds first match: this is find_and_act's ambiguity
    doctrine applied to a different resolver."""
    _log([_record("type_text", {"text": "same"}, ANCHOR),
          _record("type_text", {"text": "same"}, ANCHOR)])
    with pytest.raises(Exception) as exc:
        save(name="wf", parameters=[{"name": "v", "example": "same"}])
    assert "step 0" in str(exc.value) and "step 1" in str(exc.value)
    out = save(name="wf2",
               parameters=[{"name": "v", "example": "same", "all": True}])
    assert len(out["parameters"][0]["bound_to"]) == 2


def test_save_reports_parity_and_the_next_call():
    _log([_record("type_text", {"text": "D-pad bug"}, ANCHOR)])
    out = save(name="wf", parameters=[{"name": "title",
                                       "example": "D-pad bug"}])
    assert "1 parameter" in out["parity"]
    assert "parameters=" in out["next"]
    assert out["parameters"][0]["kind"] == "text"
    doc = json.loads(workflows._path_of("wf").read_text(encoding="utf-8"))
    assert doc["steps"][0]["slots"] == [
        {"param": "title", "field": "args.text", "span": [0, 9]}]


def test_a_url_slot_records_its_origin():
    _log([_record("navigate", {"url": "https://example.com/issues/new"})])
    out = save(name="wf", parameters=[{"name": "path", "example": "issues"}])
    assert out["parameters"][0]["kind"] == "url"
    doc = json.loads(workflows._path_of("wf").read_text(encoding="utf-8"))
    assert doc["steps"][0]["slots"][0]["recorded_origin"] == "example.com"


# ------------------------------------------------------------ at LOAD


def test_a_hand_edited_slot_on_condition_refuses_and_blames_the_file():
    """W4. The caller passed a name, not a file, so the message never
    accuses them."""
    _write("hand", _doc(
        [{"tool": "wait_for", "args": {"condition": "text", "value": "x"},
          "slots": [{"param": "c", "field": "args.condition",
                     "span": [0, 4]}]}],
        [{"name": "c", "required": True, "kind": "text"}]))
    with pytest.raises(ValidationFailed) as exc:
        run(name="hand", page="p1", dry_run=True, parameters={"c": "js"})
    text = str(exc.value)
    assert "edited" in text.lower()
    for accusation in ("you passed", "your ", "you gave"):
        assert accusation not in text.lower()


def test_a_js_condition_in_a_file_refuses_the_whole_workflow():
    """W5. On both dry and real runs, before any step executes."""
    _write("js", _doc([{"tool": "wait_for",
                        "args": {"condition": "js", "value": "1"}}]))
    for dry in (True, False):
        with pytest.raises(ValidationFailed):
            run(name="js", page="p1", dry_run=dry)


def test_a_js_predicate_cannot_be_reached_through_a_value_slot(monkeypatch):
    """W6. The second guard, independent of the first."""
    _write("sneak", _doc(
        [{"tool": "wait_for", "args": {"condition": "js", "value": "1"},
          "slots": [{"param": "v", "field": "args.value", "span": [0, 1]}]}],
        [{"name": "v", "required": True, "kind": "text"}]))
    from kitchensink4web.ops import lite

    async def never(*a, **k):
        raise AssertionError("the predicate reached the driver")
    monkeypatch.setattr(lite, "wait_for", never)
    with pytest.raises(ValidationFailed):
        run(name="sneak", page="p1", dry_run=True,
            parameters={"v": "fetch('http://x')"})


def test_an_unknown_key_inside_a_slot_refuses():
    """A slot is a security-relevant structure, and tolerating an unknown
    key there is how a future field gets honored by accident."""
    _write("extra", _doc(
        [{"tool": "type_text", "args": {"text": "hello"}, "anchor": ANCHOR,
          "slots": [{"param": "v", "field": "args.text", "span": [0, 5],
                     "eval": True}]}],
        [{"name": "v", "required": True, "kind": "text"}]))
    with pytest.raises(ValidationFailed) as exc:
        run(name="extra", page="p1", dry_run=True, parameters={"v": "x"})
    assert "eval" in str(exc.value)


def test_a_span_out_of_bounds_refuses():
    _write("span", _doc(
        [{"tool": "type_text", "args": {"text": "hi"}, "anchor": ANCHOR,
          "slots": [{"param": "v", "field": "args.text", "span": [0, 99]}]}],
        [{"name": "v", "required": True, "kind": "text"}]))
    with pytest.raises(ValidationFailed):
        run(name="span", page="p1", dry_run=True, parameters={"v": "x"})


# ------------------------------------------------------------- at RUN


def _param_doc():
    return _doc(
        [{"tool": "navigate", "args": {"url": "https://example.com/new"},
          "slots": [{"param": "where", "field": "args.url",
                     "span": [20, 23], "recorded_origin": "example.com"}]},
         {"tool": "type_text", "args": {"text": "D-pad bug"},
          "anchor": ANCHOR, "anchor_id": "a1",
          "slots": [{"param": "title", "field": "args.text",
                     "span": [0, 9]}]}],
        [{"name": "where", "required": False, "kind": "url",
          "default": "new"},
         {"name": "title", "required": True, "kind": "text",
          "description": "the issue title"}])


def test_a_missing_required_parameter_refuses_and_lists_the_declared_set():
    _write("p", _param_doc())
    with pytest.raises(BadParams) as exc:
        run(name="p", page="p1", dry_run=True, parameters={})
    text = str(exc.value)
    assert "title" in text and "where" in text
    assert "the issue title" in text


def test_an_extra_parameter_refuses_rather_than_being_ignored():
    """Silently ignoring one is the failure mode where a caller believes it
    configured something it did not."""
    _write("p", _param_doc())
    with pytest.raises(BadParams) as exc:
        run(name="p", page="p1", dry_run=True,
            parameters={"title": "x", "nope": "y"})
    assert "nope" in str(exc.value)


def test_parameters_passed_to_a_workflow_that_declares_none_refuse():
    """W12, half two. Backward compatibility runs the other way freely."""
    _write("old", _doc([{"tool": "navigate",
                         "args": {"url": "https://example.com/new"}}]))
    with pytest.raises(BadParams) as exc:
        run(name="old", page="p1", dry_run=True, parameters={"a": "b"})
    assert "save_workflow" in str(exc.value)


def test_a_value_of_the_wrong_type_or_over_the_cap_refuses():
    _write("p", _param_doc())
    for value in ({"a": 1}, ["a"], 7):
        with pytest.raises(BadParams):
            run(name="p", page="p1", dry_run=True,
                parameters={"title": value})
    with pytest.raises(BadParams) as exc:
        run(name="p", page="p1", dry_run=True,
            parameters={"title": "x" * 8193})
    assert "8192" in str(exc.value).replace(",", "")


def test_control_characters_refuse_but_a_newline_does_not():
    _write("p", _param_doc())
    with pytest.raises(BadParams):
        run(name="p", page="p1", dry_run=True,
            parameters={"title": "a\x00b"})
    # A newline is legitimate and reaches the field's own honest refusal.
    with pytest.raises(Exception) as exc:
        run(name="p", page="p1", dry_run=True, parameters={"title": "a\nb"})
    assert "\\x" not in str(exc.value)
    assert not isinstance(exc.value, BadParams) or "control" not in str(
        exc.value).lower()


def test_a_url_slot_that_changes_origin_refuses():
    """W9. A workflow named for one site, pointed at another, is a
    redirection of a flow the caller trusts by name."""
    doc = _param_doc()
    doc["steps"][0]["slots"][0]["span"] = [8, 19]     # the host itself
    _write("p", doc)
    with pytest.raises(NavigationBlocked) as exc:
        run(name="p", page="p1", dry_run=True,
            parameters={"title": "t", "where": "evil.test"})
    text = str(exc.value)
    assert "example.com" in text and "evil.test" in text
    assert "allow_origin_change" in text


def test_an_origin_change_declared_at_save_is_permitted():
    doc = _param_doc()
    doc["steps"][0]["slots"][0]["span"] = [8, 19]
    doc["parameters"][0]["allow_origin_change"] = True
    _write("p", doc)
    # It gets past the parameter layer and fails later, on the page handle,
    # which is the layer under test being satisfied.
    with pytest.raises(Exception) as exc:
        run(name="p", page="p1", dry_run=True,
            parameters={"title": "t", "where": "evil.test"})
    assert not isinstance(exc.value, NavigationBlocked)


def test_a_recorded_literal_containing_braces_survives():
    """W2, the pin for the whole out-of-band design. An in-band token
    implementation fails this."""
    doc = _doc(
        [{"tool": "type_text", "args": {"text": "use {{name}} here"},
          "anchor": ANCHOR, "anchor_id": "a1"},
         {"tool": "type_text", "args": {"text": "D-pad bug"},
          "anchor": ANCHOR, "anchor_id": "a1",
          "slots": [{"param": "title", "field": "args.text",
                     "span": [0, 9]}]}],
        [{"name": "title", "required": True, "kind": "text"}])
    _write("braces", doc)
    filled = workflows._fill(doc, {"title": "REPLACED"})
    assert filled["steps"][0]["args"]["text"] == "use {{name}} here"
    assert filled["steps"][1]["args"]["text"] == "REPLACED"


def test_a_default_is_never_silent():
    """W8."""
    doc = _param_doc()
    filled, report = workflows._apply_parameters(doc, {"title": "t"})
    assert report["defaulted"][0]["name"] == "where"
    assert report["supplied"] == ["title"]


def test_values_are_reported_by_length_not_by_value():
    """W13. A workflow parameter is exactly the shape a password gets typed
    into by mistake, and echoing it back adds no information the caller
    lacks and one more place a secret can land."""
    doc = _param_doc()
    _filled, report = workflows._apply_parameters(
        doc, {"title": "a very long issue title"})
    applied = [a for a in report["applied"] if a["param"] == "title"][0]
    assert applied["value_length"] == 23
    assert "a very long issue title" not in json.dumps(report)
    # A url slot reports its result in full, because the resolved URL IS the
    # information.
    url = [a for a in report["applied"] if a["param"] == "where"][0]
    assert url["result"].startswith("https://example.com/")


def test_list_workflows_reports_parameters():
    _write("p", _param_doc())
    out = asyncio.run(workflows.list_workflows())
    row = [w for w in out["workflows"] if w["name"] == "wf"][0]
    assert [p["name"] for p in row["parameters"]] == ["where", "title"]
