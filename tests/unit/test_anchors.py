"""The anchor system as a pure function of an extraction.

`anchors/` never touches a browser, which is what lets the key ladder, the
six entry conditions, the five outcomes, the batch semantics, and the delta
engine be tested in milliseconds against recorded pages. The live half, where
React actually remounts and react-window actually recycles, is
`tests/browser/test_anchors_s2.py`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from kitchensink4web import anchors
from kitchensink4web.anchors import keys as _keys
from kitchensink4web.errors import BadParams

DATA = Path(__file__).resolve().parents[1] / "data"


def load(name: str) -> dict:
    return json.loads((DATA / f"extract_{name}.json").read_text(
        encoding="utf-8"))


# ------------------------------------------------------------- the key rules


def test_no_key_rung_can_bind_an_ordinal():
    """An ordinal may scope a lookup and may never bind a ref (DESIGN 3.5).

    An ordinal is a property of the RENDERED WINDOW, and a virtualized list
    rewrites that window while keeping every ordinal: scrolling a
    react-window list of 5,000 rows from row 0 to row 4,000 put row 0's ref
    onto row 3,998 and did the same for twenty-one of its neighbours."""
    anchors.assert_no_ordinal_binding()
    for name, fields in anchors.KEY_LADDER:
        assert "ordinal" not in fields, name


def test_every_key_rung_carries_the_page_key():
    """S2 found this by producing the failure: with origin and path in the
    descriptor but not in the KEY, a ref minted on one page came back bound to
    a same-named control on another, seven per run, silently, at the strongest
    tier of the ladder."""
    for name, fields in anchors.KEY_LADDER:
        assert fields[0] == "page_key", name


def test_the_name_only_fuzzy_tier_is_absent():
    """CUT from v1 on measurement rather than caution: across every S2
    scenario it changed no resolution's correctness, and its entire effect was
    to convert eight STALE_ANCHOR refusals into eight AMBIGUOUS_LOCATION
    ones."""
    assert not any("fuzzy" in name for name, _ in anchors.KEY_LADDER)


def test_a_rung_that_reads_an_ordinal_is_rejected_at_import(monkeypatch):
    """The guard rail has to be able to FAIL, or it is decoration."""
    monkeypatch.setattr(
        _keys, "KEY_LADDER",
        (("bad", ("page_key", "role", "ordinal")),))
    with pytest.raises(AssertionError) as caught:
        _keys.assert_no_ordinal_binding()
    assert "may never bind a ref" in str(caught.value)


def test_every_unique_key_is_registered_not_only_the_cheapest():
    """What lets a control survive a change to its own accessible name: its
    id key holds where its role-plus-name key does not, and that is not
    derivable from a list of fields."""
    anchor = {"page_key": "https://x/", "landmark": "form",
              "landmark_label": "Profile", "role": "button",
              "name": "Save", "attr_id": "save-btn", "attr_testid": "",
              "attr_name": "", "labelled_ancestor": ""}
    idx = anchors.index([anchor])
    offered = anchors.unique_keys(anchor, idx)
    kinds = [k for k, _ in offered]
    assert "id" in kinds and "role-name-landmark" in kinds
    assert kinds.index("id") < kinds.index("role-name-landmark"), (
        "lookup must walk strongest first, or an id loses to a name")


# --------------------------------------------------------------- stickiness


def _extraction(url="https://example.test/a", affordances=None):
    return {
        "identity": {"url": url, "page_key": url, "doc_epoch": "d1"},
        "affordances": affordances or [],
        "regions": [], "headings": [], "forms": [], "tables": [],
        "completeness": {}, "shape": {},
    }


def _aff(ref, name, role="button", **over):
    anchor = {"page_key": "https://example.test/a", "role": role,
              "name": name, "landmark": "main", "landmark_label": "",
              "labelled_ancestor": "", "ordinal": 1, "attr_id": "",
              "attr_testid": "", "attr_name": ""}
    anchor.update({k: v for k, v in over.items() if k in anchor})
    return {"ref": ref, "anchor": anchor, "role": role, "name": name,
            "state": over.get("state", "")}


def test_a_ref_survives_a_re_read():
    element_map = anchors.ElementMap()
    first = _extraction(affordances=[_aff("e1", "Save"), _aff("e2", "Cancel")])
    element_map.absorb(first, "p1", "rt1")
    saved = first["affordances"][0]["ref"]
    second = _extraction(affordances=[_aff("e1", "Save"), _aff("e2", "Cancel")])
    element_map.absorb(second, "p1", "rt2")
    assert second["affordances"][0]["ref"] == saved


def test_a_control_survives_a_change_to_its_own_name_through_its_id():
    element_map = anchors.ElementMap()
    first = _extraction(affordances=[_aff("e1", "Save", attr_id="btn")])
    element_map.absorb(first, "p1", "rt1")
    was = first["affordances"][0]["ref"]
    second = _extraction(affordances=[_aff("e1", "Save changes",
                                           attr_id="btn")])
    element_map.absorb(second, "p1", "rt2")
    assert second["affordances"][0]["ref"] == was


def test_two_identical_controls_are_turn_local_rather_than_guessed():
    """The stated cost of refusing to bind an ordinal: an element nothing can
    tell apart cannot be durably addressed, and the design's answer for it is
    AMBIGUOUS_LOCATION rather than a coin flip."""
    element_map = anchors.ElementMap()
    data = _extraction(affordances=[_aff("e1", "Delete"), _aff("e2", "Delete")])
    element_map.absorb(data, "p1", "rt1")
    refs = [a["ref"] for a in data["affordances"]]
    assert all(element_map.entries[r].turn_local for r in refs)


def test_a_removed_element_is_marked_gone_rather_than_deleted():
    element_map = anchors.ElementMap()
    first = _extraction(affordances=[_aff("e1", "Save"), _aff("e2", "Cancel")])
    element_map.absorb(first, "p1", "rt1")
    cancel = first["affordances"][1]["ref"]
    element_map.absorb(_extraction(affordances=[_aff("e1", "Save")]),
                       "p1", "rt2")
    entry = element_map.entries[cancel]
    assert entry.gone and "Cancel" in entry.gone_as


# ------------------------------------------------------- the entry conditions


def _map_with(url="https://example.test/a"):
    element_map = anchors.ElementMap()
    data = _extraction(url=url, affordances=[
        _aff("e1", "Save", attr_id="save"), _aff("e2", "Cancel")])
    element_map.absorb(data, "p1", "rt1")
    return element_map, data


def test_a_modal_blocks_before_any_resolution_is_attempted():
    """Entry condition one, and the ORDER is the assertion: it is asked with a
    ref that would otherwise refuse NOT_FOUND, so a modal that only blocked
    valid refs would pass a weaker test."""
    element_map, data = _map_with()
    blocked = copy.deepcopy(data)
    blocked["modal"] = "Confirm deletion"
    result = anchors.resolve(element_map, "e999", blocked, "p1")
    assert result["outcome"] == anchors.Outcome.MODAL
    assert result["dialog"] == "Confirm deletion"


def test_a_ref_nobody_minted_names_the_mint_rule():
    element_map, data = _map_with()
    result = anchors.resolve(element_map, "e999", data, "p1")
    assert result["outcome"] == anchors.Outcome.NOT_FOUND
    assert "minted only by a read in THIS session" in result["recovery"]


def test_a_ref_from_another_page_handle_is_never_silently_retargeted():
    element_map, data = _map_with()
    ref = data["affordances"][0]["ref"]
    result = anchors.resolve(element_map, ref, data, "p2")
    assert result["outcome"] == anchors.Outcome.BAD_PARAMS
    assert result["minted_on"] == "p1" and result["asked_for"] == "p2"


def test_a_changed_url_refuses_before_the_ladder_rather_than_inside_it():
    """A fuzzy match on a different URL IS a cross-page rebind under another
    name. The test is literal: S2 measured document identity as the plausible
    refinement and it fails in both directions at once."""
    element_map, data = _map_with()
    ref = data["affordances"][0]["ref"]
    elsewhere = _extraction(url="https://example.test/b",
                            affordances=[_aff("e1", "Save", attr_id="save")])
    result = anchors.resolve(element_map, ref, elsewhere, "p1")
    assert result["outcome"] == anchors.Outcome.STALE
    assert result["reason"] == "url-changed"
    assert "6 false rebinds in 22 attempts" in result["recovery"]


def test_the_url_condition_is_checked_before_the_gone_condition():
    """The design finding this build produced. DESIGN 3.5's table lists the
    gone-marked row ABOVE the URL-changed row, and evaluated in that printed
    order a gone-marked ref skips straight to re-resolution. After a
    navigation EVERY ref is gone-marked by the next read, so cross-page
    rebinding would be on by default for exactly the refs most likely to
    rebind wrongly."""
    element_map, data = _map_with()
    ref = data["affordances"][0]["ref"]
    element_map.entries[ref].gone = True
    element_map.entries[ref].gone_as = 'button "Save"'
    elsewhere = _extraction(url="https://example.test/b",
                            affordances=[_aff("e1", "Save", attr_id="save")])
    result = anchors.resolve(element_map, ref, elsewhere, "p1")
    assert result["outcome"] == anchors.Outcome.STALE, (
        "a gone-marked ref rebound across a navigation, which is the "
        "confused-deputy failure the whole entry table exists to prevent")


def test_a_turn_local_ref_refuses_ambiguous_rather_than_not_found():
    """S2 added this row after finding the obvious implementation refusing
    NOT_FOUND here. That is a lie, since the ref WAS minted this session, and
    it sends the caller to re-read the page when re-reading is exactly what
    will not help."""
    element_map = anchors.ElementMap()
    data = _extraction(affordances=[_aff("e1", "Delete"), _aff("e2", "Delete")])
    element_map.absorb(data, "p1", "rt1")
    ref = data["affordances"][0]["ref"]
    result = anchors.resolve(element_map, ref, data, "p1")
    assert result["outcome"] == anchors.Outcome.AMBIGUOUS
    assert result["tier"] == "turn-local ref"
    assert len(result["candidates"]) == 2


def test_the_entry_table_has_six_rows_and_they_are_all_reachable():
    """The table gained a sixth row at S2. A table with an unreachable row is
    a table that is documenting something other than the code."""
    element_map, data = _map_with()
    ref = data["affordances"][0]["ref"]
    modal = copy.deepcopy(data)
    modal["modal"] = "d"
    reached = {
        anchors.resolve(element_map, "e999", modal, "p1")["outcome"],
        anchors.resolve(element_map, "e999", data, "p1")["outcome"],
        anchors.resolve(element_map, ref, data, "p2")["outcome"],
        anchors.resolve(element_map, ref,
                        _extraction(url="https://example.test/b"),
                        "p1")["outcome"],
    }
    assert reached == {anchors.Outcome.MODAL, anchors.Outcome.NOT_FOUND,
                       anchors.Outcome.BAD_PARAMS, anchors.Outcome.STALE}


# ------------------------------------------------------------- the outcomes


def test_an_unchanged_fingerprint_proceeds_without_a_rebind():
    element_map, data = _map_with()
    ref = data["affordances"][0]["ref"]
    result = anchors.resolve(element_map, ref, data, "p1")
    assert result["outcome"] == anchors.Outcome.OK
    assert result["tier"] == "fingerprint"


def test_a_rebind_is_never_silent():
    """A rebind the transcript cannot see is the same disease as a silent
    false success."""
    element_map = anchors.ElementMap()
    data = _extraction(affordances=[_aff("e1", "Save", attr_id="save")])
    element_map.absorb(data, "p1", "rt1")
    ref = data["affordances"][0]["ref"]
    # Same element, its id gone: the id key no longer resolves and the
    # role-plus-name tier has to carry it.
    moved = _extraction(affordances=[_aff("e1", "Save")])
    result = anchors.resolve(element_map, ref, moved, "p1")
    assert result["outcome"] == anchors.Outcome.REBOUND
    assert result["was"] and result["now"]
    assert result["tier"].startswith("role+name")


def test_two_matches_refuse_rather_than_acting_on_the_first():
    """House rule, inherited and absolute: no tool ever acts on first match."""
    element_map = anchors.ElementMap()
    data = _extraction(affordances=[_aff("e1", "Save", attr_id="save")])
    element_map.absorb(data, "p1", "rt1")
    ref = data["affordances"][0]["ref"]
    twins = _extraction(affordances=[_aff("e1", "Save"), _aff("e2", "Save")])
    result = anchors.resolve(element_map, ref, twins, "p1")
    assert result["outcome"] == anchors.Outcome.AMBIGUOUS
    assert len(result["candidates"]) == 2


def test_zero_matches_refuse_and_name_what_changed():
    element_map, data = _map_with()
    ref = data["affordances"][0]["ref"]
    gone = _extraction(affordances=[_aff("e1", "Saved changes")])
    result = anchors.resolve(element_map, ref, gone, "p1")
    assert result["outcome"] == anchors.Outcome.STALE
    assert result["nearest_by_name"] == "Saved changes"
    assert result["landmark_present"] is True


# --------------------------------------------------------- batch semantics


def test_a_batch_stops_and_leaves_completed_items_completed():
    """Browser actions do not roll back, so a batch that failed halfway has
    to say what already happened rather than implying an undo."""
    rolled = anchors.batch_outcome([
        {"ref": "e1", "status": "completed", "outcome": anchors.Outcome.OK},
        {"ref": "e2", "status": "completed", "outcome": anchors.Outcome.REBOUND},
        {"ref": "e3", "status": "failed",
         "outcome": anchors.Outcome.AMBIGUOUS},
        {"ref": "e4", "status": "not_attempted"},
    ])
    assert rolled["completed"] == 2
    assert rolled["rebound"] == 1
    assert rolled["stopped_at"] == "e3"
    assert rolled["not_attempted"] == ["e4"]
    assert "do not roll back" in rolled["rollback"]


def test_every_refusing_outcome_stops_a_batch():
    for outcome in (anchors.Outcome.AMBIGUOUS, anchors.Outcome.STALE,
                    anchors.Outcome.NOT_FOUND, anchors.Outcome.BAD_PARAMS,
                    anchors.Outcome.MODAL):
        assert outcome in anchors.STOPS_THE_BATCH


# ---------------------------------------------------------------- the deltas


def test_a_delta_reports_added_removed_changed_and_stable():
    element_map = anchors.ElementMap()
    store = anchors.ReadStore()
    first = _extraction(affordances=[_aff("e1", "Save", attr_id="s"),
                                     _aff("e2", "Cancel", attr_id="c")])
    before = element_map.absorb(first, "p1", store.mint_token("p1"))
    store.put(before)
    second = _extraction(affordances=[_aff("e1", "Save changes", attr_id="s"),
                                      _aff("e3", "Help", attr_id="h")])
    after = element_map.absorb(second, "p1", store.mint_token("p1"))
    store.put(after)
    delta = anchors.diff(before, after)
    assert [a["name"] for a in delta["added"]] == ["Help"]
    assert [r["name"] for r in delta["removed"]] == ["Cancel"]
    assert delta["changed"][0]["changes"][0]["now"] == "Save changes"
    text = anchors.render(delta, "p1")
    assert "+ " in text and "- " in text and "~ " in text


def test_a_delta_with_no_changes_says_so_rather_than_going_quiet():
    """"Nothing happened" and "I did not look" are different answers, and a
    delta that only speaks when it has news cannot tell them apart."""
    element_map = anchors.ElementMap()
    store = anchors.ReadStore()
    first = _extraction(affordances=[_aff("e1", "Save", attr_id="s")])
    before = element_map.absorb(first, "p1", store.mint_token("p1"))
    store.put(before)
    second = _extraction(affordances=[_aff("e1", "Save", attr_id="s")])
    after = element_map.absorb(second, "p1", store.mint_token("p1"))
    delta = anchors.diff(before, after)
    text = anchors.render(delta, "p1")
    assert "nothing changed" in text
    assert "still present" in text


def test_read_tokens_age_out_under_a_bounded_lru_and_say_why():
    """Retention is bounded and STATED. A token that has aged out is not an
    error the model has to guess at."""
    element_map = anchors.ElementMap()
    store = anchors.ReadStore(retained=2)
    tokens = []
    for _ in range(4):
        token = store.mint_token("p1")
        tokens.append(token)
        store.put(element_map.absorb(
            _extraction(affordances=[_aff("e1", "Save", attr_id="s")]),
            "p1", token))
    assert store.get("p1", tokens[-1]) is not None
    with pytest.raises(BadParams) as caught:
        store.get("p1", tokens[0])
    message = str(caught.value)
    assert "aged out" in message and "re-establish a baseline" in message


def test_a_token_nobody_minted_names_the_three_invalidations():
    store = anchors.ReadStore()
    with pytest.raises(BadParams) as caught:
        store.get("p1", "rt999")
    message = str(caught.value)
    assert "navigation" in message and "close" in message
    assert "session end" in message


def test_a_navigation_invalidates_refs_and_tokens_together():
    element_map = anchors.ElementMap()
    store = anchors.ReadStore()
    token = store.mint_token("p1")
    store.put(element_map.absorb(
        _extraction(affordances=[_aff("e1", "Save", attr_id="s")]),
        "p1", token))
    assert element_map.invalidate_page("p1", "the page navigated") == 1
    assert store.invalidate("p1", "the page navigated") == 1
    with pytest.raises(BadParams):
        store.get("p1", token)


# ------------------------------------------- the whole payload, not just refs


def test_every_printed_unit_gets_a_sticky_ref_not_only_affordances():
    """A delta over half a payload is not a delta, and a NEXT CALLS line
    naming `r7` has to still mean r7 after a re-read."""
    element_map = anchors.ElementMap()
    first = load("article")
    element_map.absorb(copy.deepcopy(first), "p1", "rt1")
    second = copy.deepcopy(load("article"))
    element_map.absorb(second, "p1", "rt2")
    kinds = {element_map.entries[u["ref"]].kind
             for group in ("affordances", "regions", "headings", "tables")
             for u in second.get(group) or []}
    assert {"affordance", "region", "heading"} <= kinds


def test_renaming_a_unit_renames_everything_that_points_at_it():
    """Renaming a unit without renaming its referrers leaves the payload
    naming refs that no longer exist, which is the same disease as a stale ref
    wearing a different hat."""
    element_map = anchors.ElementMap()
    data = copy.deepcopy(load("article"))
    element_map.absorb(data, "p1", "rt1")
    live = {r["ref"] for r in data["regions"]}
    for region in data["regions"]:
        assert region["parent"] in live or region["parent"] is None
        for child in region["children"]:
            assert child in live, f"{region['ref']} names a dead child {child}"
    for aff in data["affordances"]:
        assert aff["region"] in live or aff["region"] is None
