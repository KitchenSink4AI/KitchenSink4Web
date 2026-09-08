"""Fix wave 10, items 9-12: the live purchase field test.

An Opus agent drove its own KS4Web instance through a real Porkbun cart and a
real Stripe checkout, and handed the window to the author to pay. Four findings
came back and the first is the sharpest thing anyone has found in this build:
the observability channel leaked a live payment capability URL to the agent
during the exact window the handoff exists to keep the agent out of.

Every pin here has its both-direction partner, because three of the four fixes
narrow something that is currently loud and the fourth widens what a payload
says. A redactor that shortened every URL, or a payment classifier that let a
real checkout through, would each be worse than the bug being fixed.
"""

from __future__ import annotations

import pytest

from kitchensink4web.policy import credentials, submissions


# ------------------------------------------------- 9. the capability-URL leak


#: The shape the field test caught, with the live id replaced. The `cs_live_`
#: token sits in the PATH, which is why an origin-plus-path rule would still
#: have published the credential.
STRIPE_URL = ("https://checkout.stripe.com/c/pay/"
              "cs_live_a1TplABCdefGHIjkl0123456789#fidkdWxOYHwnPyd1blpx")


def test_a_payment_capability_url_is_never_published_whole():
    safe, note = credentials.safe_page_url(STRIPE_URL)
    assert "cs_live_" not in safe, safe
    assert "fidkdWxOYHwn" not in safe, safe
    assert safe.startswith("https://checkout.stripe.com/c/pay/")
    assert note, "a redaction that does not say so is indistinguishable"


def test_the_token_in_the_path_is_the_point():
    """An origin-plus-path rule would have passed the credential through,
    because Stripe puts the session id in a path segment."""
    safe, _ = credentials.redact_url(STRIPE_URL, reason="payment_origin")
    assert credentials.URL_REDACTED in safe
    assert safe.count("/") == STRIPE_URL.split("#")[0].count("/"), (
        "the path SHAPE is kept; only the minted segment goes")


def test_a_handed_off_page_loses_its_query_and_fragment():
    url = "https://accounts.example.com/signin?continue=/checkout&token=abc123"
    safe, note = credentials.safe_page_url(url, handed_off=True)
    assert safe == "https://accounts.example.com/signin"
    assert "handed to the human" in note


def test_an_ordinary_page_keeps_its_whole_url():
    """THE BOTH-DIRECTION PIN, and it is the one that matters most. A
    redactor that quietly shortened every URL would cost the caller the
    thing it uses URLs for."""
    url = "https://en.wikipedia.org/wiki/Treaty_of_Versailles?action=history"
    safe, note = credentials.safe_page_url(url)
    assert safe == url
    assert note is None


def test_an_ordinary_page_in_a_handed_off_session_keeps_its_path():
    """Redaction is not blanking. A watcher still has to be able to see
    WHERE the human is, which is the whole reason it polls."""
    safe, note = credentials.safe_page_url(
        "https://porkbun.com/checkout/cart", handed_off=True)
    assert safe == "https://porkbun.com/checkout/cart"
    assert note is None, "nothing was removable, so nothing is claimed"


@pytest.mark.parametrize("host", [
    "checkout.stripe.com", "stripe.com", "js.stripe.com",
    "www.paypal.com", "checkout.paypal.com", "pay.google.com",
    "checkout.adyen.com", "checkout.razorpay.com",
])
def test_payment_origins_are_recognised(host):
    assert credentials.is_payment_origin(f"https://{host}/x")


@pytest.mark.parametrize("host", [
    "example.com", "en.wikipedia.org", "porkbun.com",
    "notstripe.com", "stripe.com.evil.example",
])
def test_ordinary_origins_are_not_payment_origins(host):
    """BOTH-DIRECTION PIN, including the suffix trap: `stripe.com.evil.example`
    is not Stripe, and matching a bare substring would have said it was."""
    assert not credentials.is_payment_origin(f"https://{host}/x")


@pytest.mark.parametrize("segment,expected", [
    ("cs_live_short", True),
    ("pi_1234", True),
    ("how-to-bake-sourdough-bread-at-home", False),
    ("Treaty_of_Versailles", False),
    ("2026", False),
    ("a1b2c3d4e5f6a7b8c9d0e1f2a3b4", True),
    ("checkout", False),
])
def test_which_path_segments_read_as_a_minted_id(segment, expected):
    assert credentials._segment_is_a_token(segment) is expected


def test_an_unparseable_url_near_a_payment_page_is_withheld():
    safe, note = credentials.redact_url("http://[", reason="payment_origin")
    assert safe == credentials.URL_REDACTED
    assert note


# ------------------------------------------- 10. the Porkbun search false pos


def _census(**kw):
    base = {"method": "GET", "field_count": 1, "secret": False,
            "payment": False, "action": "/checkout/search",
            "submitter": None, "checkbox_labels": ""}
    base.update(kw)
    return base


def test_the_porkbun_domain_search_box_is_not_a_payment_form():
    """A one-field GET posting to `/checkout/search`. `checkout` is in the
    strong payment vocabulary, so the PATH alone classified a search box as
    a payment form and the submit failed closed, on a site whose search had
    no other route in."""
    assert submissions.classify(_census(), "Domain Search") is None


def test_a_real_checkout_still_gates():
    """BOTH-DIRECTION PIN. The exemption may not reach a form that can move
    money: a checkout POSTs, collects several fields, and carries a payment
    field, so it fails three of the conditions at once."""
    got = submissions.classify(
        _census(method="POST", field_count=6, payment=True,
                action="/checkout/pay", submitter="Pay now"), "Pay now")
    assert got and got[0] == "payment_form"


def test_a_search_shaped_form_whose_button_says_pay_still_gates():
    """BOTH-DIRECTION PIN. What the control SAYS is a stronger claim than
    what the endpoint is called, and the exemption narrows only the weaker
    of the two."""
    got = submissions.classify(_census(submitter="Pay now"), "Pay now")
    assert got and got[0] == "payment_form"


def test_a_search_shaped_form_printing_a_price_still_gates():
    got = submissions.classify(
        _census(submitter="Continue $49"), "Search")
    assert got and got[0] == "payment_form"


def test_a_one_field_post_to_checkout_still_gates():
    """GET is one of the required conditions: a POST to a checkout path is
    not a search box however few fields it has."""
    got = submissions.classify(_census(method="POST"), "Domain Search")
    assert got and got[0] == "payment_form"


def test_a_two_field_get_to_checkout_still_gates():
    got = submissions.classify(_census(field_count=2), "Domain Search")
    assert got and got[0] == "payment_form"


def test_a_search_box_carrying_a_password_field_is_not_exempt():
    """A secret field disqualifies the exemption, so the path signal stands
    and the form gates.

    It gates as `payment_form` rather than `credential_submit` because this
    module orders its classes by irreversibility and money leaving outranks
    a credential leaving. Asserted as "it gates" plus the class the ordering
    actually produces, rather than as the class this test first guessed."""
    got = submissions.classify(_census(secret=True), "Search")
    assert got is not None
    assert got[0] == "payment_form", got


def test_the_search_shape_needs_a_search_word_somewhere():
    """Without search semantics in the path or in the control's own name,
    the exemption does not apply and the path signal stands."""
    got = submissions.classify(
        _census(action="/checkout/step2"), "Domain name")
    assert got and got[0] == "payment_form"


@pytest.mark.parametrize("name", ["Domain Search", "Buscar dominio",
                                  "도메인 검색", "Rechercher"])
def test_search_semantics_are_read_from_the_controls_name(name):
    assert submissions.classify(_census(action="/checkout/x"), name) is None
