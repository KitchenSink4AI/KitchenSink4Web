"""`do`: registration, the verb lexicon, and the shared-constant checks.

Red-first pins for feature #6, the half that needs no browser.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

import pytest

from kitchensink4web.errors import BadParams
from kitchensink4web.ops import lite
from kitchensink4web.policy import readonly


def call(**kwargs):
    return asyncio.run(lite.do(**kwargs))


def test_do_is_a_lite_tool_and_classified_mutating():
    assert lite.do in lite.LITE_TOOLS
    assert "do" in readonly.MUTATING
    assert "do" not in readonly.GENUINELY_READ_ONLY


def test_do_is_absent_under_read_only(launch, live_tools):
    """It clicks, so the mode whose whole claim is that nothing in it can
    click does not have it."""
    launch(read_only="browse")
    assert "do" not in live_tools()
    launch(read_only=False)
    assert "do" in live_tools()


def test_an_empty_intent_refuses_before_the_page_is_located():
    with pytest.raises(BadParams) as exc:
        call(page="p1", intent="")
    assert "find_and_act" in str(exc.value)


def test_an_unknown_verb_lists_the_four_families():
    with pytest.raises(BadParams) as exc:
        call(page="p1", intent="ponder the login form")
    text = str(exc.value).lower()
    for verb in ("click", "type", "press", "scroll"):
        assert verb in text


def test_a_conjunction_of_goals_refuses():
    for intent in ("submit the form and then close the dialog",
                   "type hello and press enter",
                   "click save; close the dialog"):
        with pytest.raises(BadParams):
            call(page="p1", intent=intent)


def test_a_type_intent_without_text_refuses():
    with pytest.raises(BadParams) as exc:
        call(page="p1", intent="type into the search box")
    assert "text" in str(exc.value)


def test_a_press_intent_needs_a_key_from_the_closed_set():
    """`do` takes no `keys` argument, so a keyboard-shaped intent names its
    key or it refuses. The set is closed on purpose: recognizing 'Enter' is
    not the same act as inventing a value out of prose, which is why `text`
    is never read from an intent at all."""
    with pytest.raises(BadParams) as exc:
        call(page="p1", intent="press the ctrl+a key")
    text = str(exc.value)
    assert "Enter" in text and "press_keys" in text


def test_action_is_not_a_parameter():
    """The verb comes from the intent; that is the whole tool. A caller who
    knows the verb should call find_and_act."""
    assert "action" not in inspect.signature(lite.do).parameters


def test_do_dispatches_only_through_the_real_tools():
    """The composite must not carry a second implementation of acting: every
    gate is inherited by construction, not by test."""
    tree = ast.parse(inspect.getsource(lite._do_dispatch))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.id if isinstance(fn, ast.Name) else
                       getattr(fn, "attr", ""))
    assert called & {"click", "type_text", "press_keys", "scroll"}
    assert not (called & {"fill", "press", "goto", "evaluate", "hover"})


def test_the_next_page_lexicon_is_shared_with_read_pages():
    """Pin 12. `read_pages` already ranks next-page links and `do` must not
    grow a second, drifting copy of that ranking."""
    from kitchensink4web.ops import common, extract
    # An identity check, not a string comparison: `do` holds the compiled
    # object common authored, and read_pages splices the JS literal from the
    # same alternation.
    assert lite._DO_NEXT_LABEL is common.NEXT_LABEL
    assert common.NEXT_LABEL_RE in extract._NEXT_JS
    assert common.NEXT_LABEL_ALTERNATION in common.NEXT_LABEL.pattern


def test_nothing_in_do_calls_a_language_model():
    """The resolution is deterministic scoring. A version that asked a model
    which element to click would make the answer unreproducible and put a
    guess behind a trusted click."""
    source = inspect.getsource(lite.do) + inspect.getsource(lite._do_resolve)
    for word in ("openai", "anthropic", "completion(", "llm"):
        assert word not in source.lower()
