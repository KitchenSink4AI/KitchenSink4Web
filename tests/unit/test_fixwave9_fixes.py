"""Fix wave 9 (2026-09-08) unit pins, against the fresh-eyes verify round
`20260908_verify_round.md`. The browser half is
`tests/browser/test_fixwave9_fixes.py`.

- V-19: `policy/submissions.py:classify` had no payment vocabulary, so a
  card-less "Pay now" was the residual `form_submit`, which the GET rule
  then admitted as query-shaped and submitted unprompted. The ladder's own
  irreversibility contract and `query_shaped`'s own defence were both untrue
  until this landed.
- V-01 (second half): a bare `AttributeError` raised inside KS4Web's own
  frame merge reached the caller as BAD_PARAMS carrying the interpreter's
  sentence as the whole message. `envelope`'s first stated rule is that no
  exception string ever reaches a caller.
"""

from __future__ import annotations

import pytest

from kitchensink4web import envelope
from kitchensink4web.policy import submissions


def census(**over):
    base = {"method": "GET", "secret": False, "payment": False,
            "has_file": False, "enctype": "", "field_count": 1,
            "textarea": False, "recipient": False, "submitter": "Search",
            "action": "/search", "checkbox_labels": ""}
    base.update(over)
    return base


# -------------------------------------------------------------------- V-19


@pytest.mark.parametrize("submitter", [
    "Pay now", "Place your order", "Buy now", "Confirm payment",
    "Complete purchase", "Donate $50", "Checkout", "Pay securely",
])
def test_v19_a_payment_named_submitter_is_payment_form(submitter):
    """The exact eight the verify round measured landing on `form_submit`
    -> `in_grade`, which means submitted with zero prompts. `Delete my
    account` on the identical page shape gated correctly; it was the word
    "Pay" that nothing read."""
    found = submissions.classify(census(submitter=submitter))
    assert found and found[0] == "payment_form", (submitter, found)


@pytest.mark.parametrize("submitter,action", [
    ("Continue", "/checkout/session"),
    ("Go", "https://shop.example/payment/confirm"),
    ("Continue", "/donate"),
])
def test_v19_the_action_path_carries_payment_the_way_it_carries_deletion(
        submitter, action):
    """Destructive and broadcast both fire on the action path alone. Payment
    now does too, and for the same reason: the path is what the site
    published about where the submission goes."""
    found = submissions.classify(census(submitter=submitter, action=action))
    assert found and found[0] == "payment_form", (submitter, action, found)


@pytest.mark.parametrize("submitter", [
    "Confirm $19.99", "Continue - 50 USD", "Complete — 12 000 원",
])
def test_v19_a_bare_confirm_word_needs_a_price_beside_it(submitter):
    """The multi-signal rule, the same one `BROADCAST_SEND` follows.
    `Confirm` and `Continue` are the labels on half the buttons on the web,
    so they classify only WITH a corroborating money signal. The price is
    read off the RAW text, because `squash` deletes every currency symbol on
    its way to word boundaries: "Donate $50" reaches the matcher as
    " donate 50 "."""
    found = submissions.classify(census(submitter=submitter))
    assert found and found[0] == "payment_form", (submitter, found)


@pytest.mark.parametrize("submitter", [
    "Search", "Sign in", "Send", "Save changes", "Filter results",
    "Next page", "Log in", "Apply", "Update profile", "Add to cart",
    "Submit", "Order by date", "Continue", "Confirm", "Subscribe",
])
def test_v19_the_control_arm_stays_ungated(submitter):
    """A gate that fires on everything is the same failure as a gate that
    fires on nothing, from the other side. Every battery over this module
    carries a control arm and this is payment's.

    `Add to cart` is in here on purpose: adding to a basket moves no money.
    `Subscribe` is in here because bare `subscribe` is a newsletter on most
    of the web, which is why the strong table carries `start subscription`
    and not the bare verb."""
    found = submissions.classify(census(submitter=submitter))
    assert not (found and found[0] == "payment_form"), (submitter, found)


def test_v19_payment_outranks_every_other_submission_class():
    """ORDER IS IRREVERSIBILITY and it is the contract. Payment is first
    here because it is already first in `act.action_class_for`, which
    decides the class from the FIELDS before this function is called; this
    branch is the other half of the same decision."""
    found = submissions.classify(census(
        submitter="Pay now and delete my account", secret=True,
        checkbox_labels="I agree to the terms"))
    assert found[0] == "payment_form", found


def test_v19_the_census_payment_flag_is_read_at_last():
    """`ksFormPayment` computes this in the page and only
    `act.action_class_for` ever consulted it. A census reaching classify
    through the delegate path carried the answer and nobody looked."""
    found = submissions.classify(census(submitter="Continue", payment=True))
    assert found and found[0] == "payment_form", found


def test_v19_an_unrelated_submission_class_still_wins_its_own_case():
    """The three vocabularies that were already here are untouched."""
    assert submissions.classify(
        census(submitter="Delete my account"))[0] == "destructive_submit"
    assert submissions.classify(
        census(submitter="I agree to the terms"))[0] == "legal_assent"
    assert submissions.classify(
        census(submitter="Post comment"))[0] == "broadcast_submit"
    assert submissions.classify(
        census(submitter="Sign in", secret=True))[0] == "credential_submit"


# ------------------------------------------------------- V-01, second half


def test_v01_an_internal_fault_is_not_reported_as_the_callers_fault():
    """A bare `AttributeError` cannot be an argument fault at this boundary:
    arguments arrive as JSON and are validated before a tool body runs, so
    every one that gets here was raised by KS4Web's own code against
    KS4Web's own object. The frame merge raised exactly this and the caller
    was told to go fix arguments that were correct."""
    exc = AttributeError("'int' object has no attribute 'items'")
    assert envelope.classify(exc) == "INTERNAL_ERROR"
    payload = envelope.refusal(exc)
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert payload["error"]["code"] in envelope.CLOSED_CODES
    assert payload["error"]["hint"]
    # The interpreter's sentence rides as a bounded detail, never as the
    # whole message.
    assert payload["error"]["message"] != str(exc)
    assert "'int' object has no attribute 'items'" \
        in payload["error"]["message"]


@pytest.mark.parametrize("exc", [
    ValueError("some internal value went wrong in a way nobody anticipated"),
    TypeError("unsupported operand type(s) for +: 'int' and 'NoneType'"),
])
def test_v01_no_bare_interpreter_sentence_is_ever_the_whole_message(exc):
    """`envelope`'s own first stated rule. Before this wave the terminal
    `elif detail != message` branch let an unscrubbed stdlib sentence ship
    verbatim whenever the scrubber had nothing to change, which is most of
    the time."""
    payload = envelope.refusal(exc)
    assert payload["error"]["message"] != str(exc)
    assert str(exc) in payload["error"]["message"]
    assert payload["error"]["code"] in envelope.CLOSED_CODES


def test_v01_a_typed_refusal_is_still_delivered_word_for_word():
    """The composition must not reach the refusals that already name their
    own recovery. Every one of those is a `WebMcpError`."""
    from kitchensink4web import errors
    exc = errors.TargetNotFound("nothing matched that ref on this page.")
    assert envelope.refusal(exc)["error"]["message"] == str(exc)
