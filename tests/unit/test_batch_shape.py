"""`batch`: the checks that need no browser, and the registration contract.

Red-first pins for feature #2, shape half. Everything here runs before the
tool ever locates a page, which is itself the property under test: a
malformed step list must refuse without opening, touching, or moving
anything, so the refusals below are reachable with a page handle that does
not exist.

The live half (per-step re-resolution, the gate trap, budgets, the replay
trail) is `tests/browser/test_batch.py`.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

import pytest

from kitchensink4web.errors import BadParams, ValidationFailed
from kitchensink4web.ops import lite
from kitchensink4web.policy import readonly


def call(**kwargs):
    return asyncio.run(lite.batch(**kwargs))


# --------------------------------------------------------- registration


def test_batch_is_a_lite_tool_and_classified_mutating():
    assert lite.batch in lite.LITE_TOOLS
    assert "batch" in readonly.MUTATING
    assert "batch" not in readonly.NON_MUTATING
    assert "batch" not in readonly.GENUINELY_READ_ONLY


def test_batch_is_absent_under_read_only(launch, live_tools):
    launch(read_only="browse")
    assert "batch" not in live_tools()


def test_batch_is_present_when_acting(launch, live_tools):
    launch(read_only=False)
    assert "batch" in live_tools()


# ------------------------------------------------------------- shape (A)


def test_empty_steps_refuses():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[])
    assert "steps" in str(exc.value)


def test_steps_must_be_a_list_of_objects():
    with pytest.raises(BadParams):
        call(page="p1", steps=["click the thing"])


def test_unknown_step_kind_names_the_five():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"tap": {"query": "Go"}}])
    text = str(exc.value)
    for kind in ("find", "location", "wait", "assert", "navigate"):
        assert kind in text


def test_two_discriminating_keys_in_one_step_refuses():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"find": {"query": "Go"},
                                "location": {"ref": "e1"}, "action": "click"}])
    assert "one" in str(exc.value).lower()


def test_a_fields_step_names_fill_form():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"fields": [{"ref": "e1", "value": "x"}]}])
    assert "fill_form" in str(exc.value)


def test_unknown_action_names_the_closed_set():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"find": {"query": "Go"}, "action": "hover"}])
    text = str(exc.value)
    assert "click" in text and "scroll_to" in text


def test_type_step_needs_text_and_press_step_needs_keys():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"find": {"query": "Body"}, "action": "type"}])
    assert "text" in str(exc.value)
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"find": {"query": "Body"}, "action": "press"}])
    assert "keys" in str(exc.value)


def test_a_find_step_needs_a_query_a_role_or_a_selector_kind():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"find": {}, "action": "click"}])
    assert "role" in str(exc.value)


def test_click_count_on_a_find_step_names_the_location_form():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"find": {"query": "Go"}, "action": "click",
                                "click_count": 2}])
    text = str(exc.value)
    assert "click_count" in text and "location" in text


def test_per_step_timeouts_over_the_whole_batch_bound_name_both_numbers():
    steps = [{"find": {"query": f"Go {i}"}, "action": "click",
              "timeout_ms": 20000} for i in range(5)]
    with pytest.raises(ValidationFailed) as exc:
        call(page="p1", steps=steps, max_total_ms=30000)
    text = str(exc.value)
    assert "100000" in text.replace(",", "") and "30000" in text.replace(",", "")


def test_an_unknown_wait_condition_refuses():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"wait": {"condition": "vibes"}}])
    assert "text_gone" in str(exc.value)


def test_an_unknown_preflight_mode_refuses():
    with pytest.raises(BadParams) as exc:
        call(page="p1", steps=[{"navigate": {"url": "https://example.com"}}],
             preflight="paranoid")
    text = str(exc.value)
    assert "advisory" in text and "strict" in text


# ----------------------------------------------- cross-step structure (B)


def test_a_ref_after_a_navigate_refuses_naming_both_step_indexes():
    """B6, message half. A ref does not survive a navigation, so the batch
    cannot possibly work and saying so costs nothing."""
    steps = [{"find": {"query": "Go"}, "action": "click"},
             {"navigate": {"url": "https://example.com/new"}},
             {"find": {"query": "Body"}, "action": "type", "text": "hi"},
             {"location": {"ref": "e12"}, "action": "click"}]
    with pytest.raises(ValidationFailed) as exc:
        call(page="p1", steps=steps)
    text = str(exc.value)
    assert "e12" in text
    assert "3" in text and "1" in text
    assert "nothing was executed" in text.lower()


# --------------------------------------------------------- no second path


def test_batch_dispatches_only_through_the_real_tools():
    """B11. The parity argument `find_and_act` makes at lite.py:3275 holds
    with more force here: a batch that inlined acting would carry a second
    implementation of clicking, and every gate would then be a test rather
    than a construction. The dispatcher may call only the registered tool
    functions and the resolver, never the driver."""
    source = inspect.getsource(lite._dispatch_step)
    tree = ast.parse(inspect.cleandoc(source))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                called.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                called.add(fn.attr)
    allowed = {"find_and_act", "click", "type_text", "press_keys", "scroll",
               "wait_for", "navigate"}
    driver = {"fill", "press", "check", "select_option", "tap", "hover",
              "evaluate", "wait_for_function", "goto"}
    assert allowed & called, "the dispatcher calls none of the real tools"
    assert not (driver & called), f"the dispatcher reaches the driver: " \
                                  f"{sorted(driver & called)}"


def test_the_docstring_says_batching_never_discounts_the_budget():
    """§1.5. A caller who reads the fusion as a discount would be reading a
    300-action budget as a 300-batch budget."""
    doc = (lite.batch.__doc__ or "").lower()
    assert "budget" in doc
    assert "calls" in doc


def test_the_docstring_states_the_pre_flight_difference_from_fill_form():
    """§1.3. A reader who knows `fill_form` would otherwise assume every
    target is resolved before anything executes."""
    doc = (lite.batch.__doc__ or "")
    assert "fill_form" in doc
