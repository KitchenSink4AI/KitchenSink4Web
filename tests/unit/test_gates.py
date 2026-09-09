"""The gate engine (DESIGN 5.4): TOCTOU re-validation, the requestState
correlation token, single-use redemption, fail-closed, and the E6 rebind
interlock. Plus the structural property that no gate touches policy."""

from __future__ import annotations

import time

import pytest

from kitchensink4web.errors import (ConfirmationRequired, TargetChanged,
                                    ValidationFailed)
from kitchensink4web.policy import gates


@pytest.fixture
def engine():
    return gates.GateEngine()


BENIGN = {"role": "button", "name": "Continue", "label": "Continue",
          "page_key": "http://x|/setup|", "landmark": "form",
          "action": "/setup/finish"}
SWAPPED = {"role": "button", "name": "Delete account and all data",
           "label": "Delete account and all data",
           "page_key": "http://x|/setup|", "landmark": "form",
           "action": "/account/delete-everything"}


def _ask(engine, target=BENIGN, action_class="form_submit"):
    with pytest.raises(ConfirmationRequired) as exc:
        engine.ask(action_class, tool="click", session="s1", page="p1",
                   target=target, summary="Submit the setup form.")
    return exc.value


def test_ask_always_refuses_and_carries_the_mrtr_payload(engine):
    exc = _ask(engine)
    detail = exc.detail
    assert detail["resultType"] == "input_required"
    assert detail["requestState"]
    assert detail["inputRequests"][0]["method"] == "elicitation/create"
    assert "FAILS CLOSED" in str(exc)
    assert "Nothing has been done" in str(exc)


def test_redeem_matches_the_request_state_and_is_single_use(engine):
    token = _ask(engine).detail["requestState"]
    gate = engine.redeem(token, {"allow": True})
    assert gate.redeemed is True
    with pytest.raises(ValidationFailed):
        engine.redeem(token, {"allow": True})  # single-use


def test_a_declined_answer_closes_the_gate(engine):
    token = _ask(engine).detail["requestState"]
    with pytest.raises(ValidationFailed) as exc:
        engine.redeem(token, {"allow": False})
    assert "declined" in str(exc.value)


def test_an_unknown_or_forged_request_state_refuses(engine):
    with pytest.raises(ValidationFailed):
        engine.redeem("forged-token", {"allow": True})


def test_toctou_swap_aborts_with_target_changed_naming_fields(engine):
    """The corpus C attack, in miniature: confirmed against the benign
    fingerprint, executed against the swapped one."""
    token = _ask(engine).detail["requestState"]
    gate = engine.redeem(token, {"allow": True})
    with pytest.raises(TargetChanged) as exc:
        engine.verify_execute(gate, SWAPPED)
    text = str(exc.value)
    assert "name" in text and "action" in text
    assert "Nothing was done" in text.replace("nothing was done",
                                              "Nothing was done")


def test_unchanged_target_executes_and_returns_the_grant(engine):
    token = _ask(engine).detail["requestState"]
    gate = engine.redeem(token, {"allow": True})
    grant = engine.verify_execute(gate, dict(BENIGN))
    assert grant["gate"] == token
    assert grant["action_class"] == "form_submit"


def test_the_rebind_interlock_never_launders_a_stale_confirmation(engine):
    """E6: a rebind may be legitimate on its own terms and it still aborts
    a confirmed action, because the human confirmed a specific element."""
    token = _ask(engine).detail["requestState"]
    gate = engine.redeem(token, {"allow": True})
    with pytest.raises(TargetChanged) as exc:
        engine.verify_execute(gate, dict(BENIGN),
                              resolution_outcome="rebound")
    assert "REBOUND" in str(exc.value)
    assert "launders" in str(exc.value)


def test_an_unredeemed_gate_never_executes(engine):
    _ask(engine)
    ghost = gates.Gate(token="t", action_class="form_submit", tool="click",
                       session="s1", page="p1",
                       target=gates.fingerprint(BENIGN), summary="x")
    with pytest.raises(ValidationFailed):
        engine.verify_execute(ghost, dict(BENIGN))


def test_expired_gates_refuse_and_are_swept(engine, monkeypatch):
    token = _ask(engine).detail["requestState"]
    monkeypatch.setattr(gates, "GATE_TTL_S", 0.0)
    # PAST ONE CLOCK TICK. Expiry is `monotonic() - created > GATE_TTL_S`,
    # and Windows' monotonic advances in steps of about 15.6 ms: ask inside
    # the same step and the age reads exactly 0.0, which is not greater than
    # 0.0, so a gate that is conceptually long dead answers as fresh. The
    # row went red on 3.12 and green on 3.13 in the same CI run on nothing
    # but where the tick fell. A real wait makes the gate really older.
    time.sleep(0.05)
    with pytest.raises(ValidationFailed) as exc:
        engine.redeem(token, {"allow": True})
    assert "expired" in str(exc.value) or "no pending" in str(exc.value)


def test_unknown_action_class_is_a_design_error(engine):
    with pytest.raises(ValidationFailed):
        engine.ask("disable_safety", tool="x", session="s1", page=None,
                   target=None, summary="")


def test_no_gate_class_touches_policy_state():
    """The structural half of the read-only invariant: the class set is
    CLOSED and pinned here, so a class that unlocks read-only, loads a pack,
    or widens an origin list cannot arrive without failing this test and
    being seen. `budget_reset` resets COUNTERS, never limits, and is the
    only policy-adjacent member by design. `navigation_offlist` and
    `action_offlist` gate GOING off the list, never changing it."""
    assert set(gates.GATED_CLASSES) == {
        "form_submit", "payment_form", "file_upload", "download_to_disk",
        "storage_clear", "storage_load", "evaluate_script", "dialog_accept",
        "navigation_offlist", "action_offlist", "budget_reset",
        "clipboard_read",
        # The consent ladder's seven (2026-09-07). The first four are what
        # `form_submit` SPLITS INTO, so the table grew to say what a
        # submission actually is; the last three are classes the old table
        # had no member for at all. Every one of them still authorizes an
        # ACTION and none names policy, which the loop at the bottom of this
        # test re-proves over the whole grown table.
        "credential_submit", "broadcast_submit", "destructive_submit",
        "legal_assent", "age_gate_detected", "sensitive_origin",
        "credential_injection",
        # Lane C's door (2026-09-09). It authorizes a CONNECTION to the
        # browser the human is signed in to; it names no policy, unlocks no
        # mode, widens no origin list, and loads no pack, and every action
        # taken over that connection meets this same table again.
        "real_profile_browse",
    }
    # dialog_accept joined 2026-09-06 with handle_dialog. It gates ANSWERING
    # a native dialog with OK and never dismissal, because dismissal is the
    # posture the server already has with nothing armed.
    assert "OK" in gates.GATED_CLASSES["dialog_accept"]
    # storage_load split off from storage_clear on 2026-09-06: the live
    # ship-route test caught a LOAD asking the human to allow "clearing
    # cookies or site storage", and someone reading carefully declines a
    # load that describes itself as a wipe.
    assert "clear" not in gates.GATED_CLASSES["storage_load"]
    assert "load" in gates.GATED_CLASSES["storage_load"]
    # clipboard_read joined 2026-09-06 by author ruling (gauntlet 3, F6):
    # the clipboard holds whatever the human last copied from any
    # application, and the read used to run with no human in the loop
    # outside read-only mode.
    assert "clipboard" in gates.GATED_CLASSES["clipboard_read"]
    assert "copied" in gates.GATED_CLASSES["clipboard_read"]
    for name in gates.GATED_CLASSES:
        for forbidden in ("read_only", "readonly", "unlock", "disable",
                          "enable", "allow", "policy", "safety"):
            assert forbidden not in name, (
                f"gate class {name!r} names a policy mutation")
