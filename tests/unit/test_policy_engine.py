"""The choke point (policy/engine.py): one ladder, checked in order, that
every Phase 4 action tool will describe its action to rather than
implementing policy itself."""

from __future__ import annotations

import pytest

from kitchensink4web.errors import (BudgetExhausted, ConfirmationRequired,
                                    CredentialRefused, NavigationBlocked,
                                    ReadOnlyMode, ValidationFailed)
from kitchensink4web.policy import budgets, engine, gates, origins, readonly


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(gates, "ENGINE", gates.GateEngine())
    monkeypatch.delenv(origins.ENV_DENY, raising=False)
    monkeypatch.delenv(origins.ENV_ALLOW, raising=False)
    readonly.apply(False)
    yield
    readonly.apply(False)


def _req(**kw):
    base = dict(tool="click", kind="act", session="s1", page="p1")
    base.update(kw)
    return engine.ActionRequest(**base)


def test_a_plain_action_is_approved_and_charged():
    permit = engine.approve(_req())
    assert permit["allowed"] is True
    assert budgets.BOOK.snapshot("s1")["counters"]["actions"] == 1


def test_read_only_refuses_mutating_kinds_as_defense_in_depth():
    readonly.apply("browse")
    with pytest.raises(ReadOnlyMode):
        engine.approve(_req())


def test_secret_write_refuses_before_anything_is_charged():
    with pytest.raises(CredentialRefused):
        engine.approve(_req(writes_value=True,
                            target={"type": "password", "name": "pw"}))
    assert budgets.BOOK.snapshot("s1")["counters"]["actions"] == 0


def test_denied_origin_refuses_before_anything_is_charged(monkeypatch):
    monkeypatch.setenv(origins.ENV_DENY, "blocked.example")
    with pytest.raises(NavigationBlocked):
        engine.approve(_req(tool="navigate", kind="navigate",
                            url="https://blocked.example/"))
    assert budgets.BOOK.snapshot("s1")["counters"]["navigations"] == 0


def test_offlist_origin_becomes_a_gate_and_fails_closed(monkeypatch):
    monkeypatch.setenv(origins.ENV_ALLOW, "docs.example")
    with pytest.raises(ConfirmationRequired) as exc:
        engine.approve(_req(tool="navigate", kind="navigate",
                            url="https://other.example/"))
    assert exc.value.detail["requestState"]
    # The action never ran; the charge DID land (the gate is the last rung,
    # so everything above it already passed).
    assert budgets.BOOK.snapshot("s1")["counters"]["navigations"] == 1


def test_429_backoff_is_enforced_at_the_choke_point():
    budgets.BOOK.note_429("api.example", 60)
    from kitchensink4web.errors import BlockedBySite
    with pytest.raises(BlockedBySite):
        engine.approve(_req(tool="navigate", kind="navigate",
                            url="https://api.example/"))


def test_budget_exhaustion_trips_here(monkeypatch):
    monkeypatch.setenv("KS4WEB_MAX_ACTIONS", "2")
    engine.approve(_req(args={"a": 1}))
    engine.approve(_req(args={"a": 2}))
    with pytest.raises(BudgetExhausted):
        engine.approve(_req(args={"a": 3}))


def test_loop_detection_trips_before_the_budget(monkeypatch):
    from kitchensink4web.errors import LoopDetected
    monkeypatch.setenv("KS4WEB_MAX_ACTIONS", "1000")
    with pytest.raises(LoopDetected):
        for _ in range(budgets.LOOP_REPEAT_THRESHOLD + 1):
            engine.approve(_req(target={"role": "button", "name": "Go"},
                                args={"same": True}))


def test_gate_grant_must_be_a_real_gate_record_not_an_echoed_token():
    """A token the model can echo back through a tool argument is not a
    confirmation. Anything but the Gate record from redeem() refuses."""
    with pytest.raises(ValidationFailed):
        engine.approve(_req(action_class="form_submit",
                            target={"role": "button", "name": "Send"},
                            gate_grant={"requestState": "echoed"}))


def test_the_full_gated_roundtrip_with_toctou_verification():
    target = {"role": "button", "name": "Send", "page_key": "k"}
    with pytest.raises(ConfirmationRequired) as exc:
        engine.approve(_req(action_class="form_submit", target=target,
                            summary="Send the form."))
    grant = gates.ENGINE.redeem(exc.value.detail["requestState"],
                                {"allow": True})
    permit = engine.approve(_req(action_class="form_submit", target=target,
                                 gate_grant=grant))
    assert permit["gate"]["action_class"] == "form_submit"


def test_reset_budgets_only_behind_a_redeemed_budget_reset_gate():
    with pytest.raises(ValidationFailed):
        engine.reset_budgets("s1", None)
    with pytest.raises(ValidationFailed):
        engine.reset_budgets("s1", "a-string-token")
    budgets.BOOK.charge("s1", "actions")
    with pytest.raises(ConfirmationRequired) as exc:
        gates.ENGINE.ask("budget_reset", tool="manage_session", session="s1",
                         page=None, target=None, summary="reset")
    grant = gates.ENGINE.redeem(exc.value.detail["requestState"],
                                {"allow": True})
    out = engine.reset_budgets("s1", grant)
    assert out["reset"] is True
    assert budgets.BOOK.snapshot("s1")["counters"]["actions"] == 0


def test_hidden_content_policy_default_and_off(monkeypatch):
    monkeypatch.delenv(engine.ENV_HIDDEN, raising=False)
    assert engine.hidden_content_allowed() is True
    monkeypatch.setenv(engine.ENV_HIDDEN, "off")
    assert engine.hidden_content_allowed() is False
