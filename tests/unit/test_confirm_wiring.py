"""The S8 confirmation wiring: deposit, consume, and fail-closed.

S8 proved MRTR does not round-trip on the installed client and elicitation
does. These tests pin the seam that follows: a gate ASKS (raises) on the
first pass, the server's plumbing redeems it out of band and deposits it,
and a second pass CONSUMES the deposit instead of raising. Nothing here is
reachable from a tool argument, which is the property that keeps the model
from confirming its own gate.
"""

from __future__ import annotations

import pytest

from kitchensink4web.errors import ConfirmationRequired, ValidationFailed
from kitchensink4web.policy import gates


@pytest.fixture(autouse=True)
def fresh():
    gates.ENGINE._pending.clear()
    gates.clear_grant()
    yield
    gates.clear_grant()


def _ask():
    return gates.ENGINE.ask(
        "form_submit", tool="fill_form", session="s1", page="p1",
        target={"role": "button", "name": "Submit", "page_key": "k"},
        summary="submit?")


def test_first_pass_raises_and_records_the_gate():
    with pytest.raises(ConfirmationRequired) as ei:
        _ask()
    token = ei.value.detail["requestState"]
    assert ei.value.detail["resultType"] == "input_required"
    assert token in {g["requestState"] for g in gates.ENGINE.pending()}


def test_a_deposited_grant_is_consumed_not_raised():
    # First pass: ask raises and mints the pending gate.
    with pytest.raises(ConfirmationRequired) as ei:
        _ask()
    token = ei.value.detail["requestState"]
    # Out-of-band redemption by the plumbing (never a tool argument).
    grant = gates.ENGINE.redeem(token, {"allow": True})
    gates.deposit_grant(grant)
    # Second pass: ask returns the grant instead of raising.
    returned = _ask()
    assert returned is grant
    # Single-use: the deposit is gone after consumption.
    assert gates.peek_grant("form_submit") is None


def test_deposit_only_matches_its_own_action_class():
    with pytest.raises(ConfirmationRequired) as ei:
        _ask()
    grant = gates.ENGINE.redeem(ei.value.detail["requestState"],
                                {"allow": True})
    gates.deposit_grant(grant)
    # A different class does not see this deposit.
    assert gates.peek_grant("download_to_disk") is None
    with pytest.raises(ConfirmationRequired):
        gates.ENGINE.ask("download_to_disk", tool="download", session="s1",
                         page="p1", target={}, summary="dl?")


def test_verify_execute_still_holds_the_toctou_line_on_a_consumed_grant():
    with pytest.raises(ConfirmationRequired) as ei:
        _ask()
    grant = gates.ENGINE.redeem(ei.value.detail["requestState"],
                                {"allow": True})
    # The element changed between confirmation and execution.
    with pytest.raises(Exception) as ex:
        gates.ENGINE.verify_execute(
            grant, {"role": "button", "name": "Delete everything",
                    "page_key": "k"})
    assert "TARGET_CHANGED" in getattr(ex.value, "code", "") \
        or "changed" in str(ex.value).lower()


def test_a_declined_answer_never_produces_a_grant():
    with pytest.raises(ConfirmationRequired) as ei:
        _ask()
    with pytest.raises(ValidationFailed):
        gates.ENGINE.redeem(ei.value.detail["requestState"], {"allow": False})


def test_redeem_is_single_use():
    with pytest.raises(ConfirmationRequired) as ei:
        _ask()
    token = ei.value.detail["requestState"]
    gates.ENGINE.redeem(token, {"allow": True})
    with pytest.raises(ValidationFailed):
        gates.ENGINE.redeem(token, {"allow": True})
