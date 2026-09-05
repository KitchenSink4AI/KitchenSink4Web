"""Budgets, loop detection, and rate limiting (DESIGN 5.5): finite always,
counters printed on every trip, the reset gated, and 429 honored."""

from __future__ import annotations

import pytest

from kitchensink4web.errors import (BlockedBySite, BudgetExhausted,
                                    LoopDetected)
from kitchensink4web.policy import budgets


@pytest.fixture
def book():
    return budgets.BudgetBook()


def test_action_budget_trips_at_the_limit_with_counters_printed(
        book, monkeypatch):
    monkeypatch.setenv("KS4WEB_MAX_ACTIONS", "3")
    for _ in range(3):
        book.charge("s1", "actions")
    with pytest.raises(BudgetExhausted) as exc:
        book.charge("s1", "actions")
    text = str(exc.value)
    assert "actions" in text and "3" in text
    assert "reset_budgets" in text  # the reset route is named
    assert "human" in text


def test_new_origin_budget_counts_distinct_origins_only(book, monkeypatch):
    monkeypatch.setenv("KS4WEB_MAX_NEW_ORIGINS", "2")
    book.charge("s1", "navigations", origin="a.example")
    book.charge("s1", "navigations", origin="a.example")  # revisit is free
    book.charge("s1", "navigations", origin="b.example")
    with pytest.raises(BudgetExhausted):
        book.charge("s1", "navigations", origin="c.example")


def test_budgets_are_per_session(book, monkeypatch):
    monkeypatch.setenv("KS4WEB_MAX_ACTIONS", "1")
    book.charge("s1", "actions")
    book.charge("s2", "actions")  # a different session, a different ledger
    with pytest.raises(BudgetExhausted):
        book.charge("s1", "actions")


def test_reset_requires_a_gate_token_and_drop_is_not_reset(book):
    book.charge("s1", "actions")
    with pytest.raises(BudgetExhausted):
        book.reset("s1", "")
    out = book.reset("s1", "gate-token-abc")
    assert out["before"]["counters"]["actions"] == 1
    assert book.snapshot("s1")["counters"]["actions"] == 0


def test_loop_detection_trips_on_repetition_and_prints_the_cycle(book):
    with pytest.raises(LoopDetected) as exc:
        for _ in range(budgets.LOOP_REPEAT_THRESHOLD):
            book.note_call("s1", "click", "fp-a", "args-1")
    assert "click" in str(exc.value)
    assert "->" in str(exc.value)  # the observed cycle, printed


def test_loop_detection_trips_on_a_two_step_cycle(book):
    with pytest.raises(LoopDetected) as exc:
        for _ in range(budgets.LOOP_CYCLE_THRESHOLD + 1):
            book.note_call("s1", "click", "fp-a", "x")
            book.note_call("s1", "scroll", "fp-b", "y")
    assert "alternate" in str(exc.value)


def test_varied_calls_never_trip(book):
    for i in range(60):
        book.note_call("s1", "click", f"fp-{i}", f"args-{i}")


def test_429_backoff_refuses_until_the_window_passes(book):
    wait = book.note_429("api.example", 30.0)
    assert wait == 30.0
    with pytest.raises(BlockedBySite) as exc:
        book.check_domain("API.EXAMPLE")  # case-insensitive
    assert "429" in str(exc.value)
    book.check_domain("other.example")  # other domains unaffected


def test_429_without_retry_after_uses_the_default(book):
    wait = book.note_429("api.example", None)
    assert wait == budgets.DEFAULT_RETRY_AFTER_S
