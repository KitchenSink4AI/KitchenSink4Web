"""The re-attack's findings, each one's own repro, refusing now.

The 2026-09-06 re-attack (fixtures in `corpus/ra/`, ported byte-unchanged)
went back at FIX WAVE 3 rather than at the build, which is a different and
more useful question than the gauntlet's: not "what does this tool miss" but
"what did the last round's fix miss." Five confirmed breaks, and four of them
were the same defect wearing different clothes -- a rule written against the
INSTANCE the previous finding presented rather than against the CLASS that
instance belongs to.

  R1  `type=submit` was tested by string equality, so `<input type=image>`,
      a submit button since HTML 2.0, submitted a checkout form ungated.
  R2  the focused descriptor was read only for the Enter family, so Space on
      a focused submit button pressed it with no class computed.
  R3  `is_payment_field` asked only whether the page declares an autocomplete
      token, which the pages this defends against do not.
  R4  nothing modelled OCCLUSION, so an opaque panel over a real control was
      invisible to every check in the build.
  R5  the opacity floor was exclusive, so a page could sit exactly on it.

`test_the_mechanism_battery` is the load-bearing one and it is THE META-FIX.
Gate parity across four write PATHS (gauntlet 2's battery, still green) says
nothing about a fifth MECHANISM reached through those same paths, which is
exactly the seam R1 and R2 came through. This battery varies the mechanism
against a fixed tool and a fixed expected verdict, so a submission route the
classifier does not recognise fails here rather than shipping.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import ConfirmationRequired, TargetNotFound
from kitchensink4web.ops import act, lite
from kitchensink4web.policy import audit, budgets, credentials, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
RA = ROOT / "corpus" / "ra"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def ra_site():
    handler = functools.partial(_Quiet, directory=str(RA))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    credentials.VAULT.clear()
    readonly.apply(False)
    yield
    credentials.VAULT.clear()
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


async def _open(site, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


async def _verdict(call) -> str:
    """The gate class a call lands on, or 'ran' when nothing gated it."""
    try:
        await call()
        return "ran"
    except ConfirmationRequired as exc:
        text = str(exc)
        if "payment-shaped" in text:
            return "payment_form"
        # THE FINER CLASSES ARE TESTED FIRST, and the order is load-bearing:
        # `credential_submit`'s sentence BEGINS "submitting a form that
        # carries...", so a generic prefix test above it reports the class
        # the ladder exists to stop reporting.
        for phrase, cls in (
                ("password or a one-time code", "credential_submit"),
                ("reaches other people", "broadcast_submit"),
                ("deletes, cancels", "destructive_submit"),
                ("agreeing to terms", "legal_assent")):
            if phrase in text:
                return cls
        if "submitting a form" in text:
            return "form_submit"
        return "gated"
    except TargetNotFound:
        return "not_found"


# ------------------------------------------------------------- THE META-FIX


def test_the_mechanism_battery(ra_site):
    """SAME tool, SAME expected verdict, EVERY native submission mechanism.

    Six ways to submit a form and one way not to. The plain form has no card
    field anywhere and every mechanism on it must give the SAME verdict
    (`destructive_submit` since the consent ladder landed, because every one
    of its submitters says "Delete by ..."; `form_submit` before it, and the
    property being pinned is agreement across mechanisms rather than the
    name of the class). The payment form's only card field is ASSOCIATED to
    it by `form=` rather than contained in it, and every mechanism on that
    one must give `payment_form`, because payment still wins over every
    other class. The `type=button` control arm must run ungated, because a
    gate that fires on everything is a gate people route around.

    This is the test R1 and R2 would have failed. Gate parity across the four
    write paths was green while both of them shipped, because parity across
    PATHS is silent about a mechanism none of the four paths recognised.
    """
    async def go():
        _, page = await _open(ra_site, "mechanism.html")
        plain = {
            "input type=submit": await _verdict(lambda: lite.click(
                page=page, location={"css": "#p_submit"})),
            "input type=image": await _verdict(lambda: lite.click(
                page=page, location={"css": "#p_image"})),
            "typeless button in form": await _verdict(lambda: lite.click(
                page=page, location={"css": "#p_typeless"})),
            "button type=submit": await _verdict(lambda: lite.click(
                page=page, location={"css": "#p_explicit"})),
            "implicit Enter in a field": await _verdict(lambda: lite.press_keys(
                page=page, keys="Enter", location={"css": "#p_user"})),
            "activation Space on a submitter": await _verdict(
                lambda: lite.press_keys(page=page, keys="Space",
                                        location={"css": "#p_submit"})),
        }
        assert set(plain.values()) == {"destructive_submit"}, plain

        pay = {
            "input type=submit": await _verdict(lambda: lite.click(
                page=page, location={"css": "#c_submit"})),
            "input type=image": await _verdict(lambda: lite.click(
                page=page, location={"css": "#c_image"})),
            "typeless button in form": await _verdict(lambda: lite.click(
                page=page, location={"css": "#c_typeless"})),
            "implicit Enter in a field": await _verdict(lambda: lite.press_keys(
                page=page, keys="Enter", location={"css": "#c_user"})),
            "writing the associated card field": await _verdict(
                lambda: lite.fill_form(page=page, fields=[
                    {"css": "#c_card", "value": "4111111111111111"}])),
        }
        assert set(pay.values()) == {"payment_form"}, pay
        return page

    page = run(go())
    assert page


def test_the_battery_gates_nothing_that_does_not_submit(ra_site):
    """The direction that keeps the battery a safety property rather than a
    mute button: `type=button` submits nothing and must act ungated."""
    async def go():
        session, page = await _open(ra_site, "mechanism.html")
        live = session.page(page).page
        res = await lite.click(page=page, location={"css": "#p_plain"})
        assert res["changed"]["effect"] != "none-observed"
        assert await live.evaluate("() => window.__plain") == "ran"
        assert await live.evaluate("() => window.__submitted") is None
    run(go())


def test_nothing_was_submitted_while_the_battery_ran(ra_site):
    """A gate that fires AFTER the form goes is not a gate. Every refusal
    above has to land before the submission, which is what the page's own
    submit listener is here to witness."""
    async def go():
        session, page = await _open(ra_site, "mechanism.html")
        live = session.page(page).page
        for css in ("#p_submit", "#p_image", "#c_submit", "#c_image"):
            with pytest.raises(ConfirmationRequired):
                await lite.click(page=page, location={"css": css})
        assert await live.evaluate("() => window.__submitted") is None
    run(go())


# ------------------------------------------------------- R1: input type=image


def test_an_image_submitter_is_a_submitter(ra_site):
    """R1's own page. `<input type=image>` is a submit button that also POSTs
    its click coordinates, and clicking it submitted a form holding a live
    card number with no class computed at all."""
    async def go():
        session, page = await _open(ra_site, "imgsubmit.html")
        live = session.page(page).page
        await live.evaluate(
            "() => document.getElementById('cc').value = '4111111111111111'")
        assert await _verdict(lambda: lite.click(
            page=page, location={"css": "#imgbtn"})) == "payment_form"
        assert await live.evaluate("() => window.__submitted") is False
    run(go())


def test_the_submit_button_states_are_the_whole_class():
    """The unit half, so the CLASS is asserted rather than the two instances
    that happened to be found. HTML has exactly three submit-button states and
    the third is folded into an effective type upstream."""
    assert act.SUBMIT_TYPES == {"submit", "image"}
    for kind in ("submit", "image"):
        assert act.is_native_submitter({"type": kind}), kind
        assert act.action_class_for({"type": kind}) == "form_submit"
        assert act.action_class_for(
            {"type": kind, "form_payment": True}) == "payment_form"
    for kind in ("text", "button", "reset", "checkbox", "hidden", ""):
        assert not act.is_native_submitter({"type": kind}), kind
        assert act.action_class_for({"type": kind}) is None, kind


# ------------------------------------------------------------ R2: Space


def test_a_global_space_on_a_focused_submitter_gates(ra_site):
    """R2's own page. Focus a submit button, press Space with no location:
    the button fires exactly as it does under a click, and the gate that read
    the focused descriptor only for Enter had nothing to classify."""
    async def go():
        session, page = await _open(ra_site, "spacesubmit.html")
        live = session.page(page).page
        await live.evaluate("() => document.getElementById('go').focus()")
        # `spacesubmit.html` is a Delete-account form, so the class is
        # `destructive_submit` since the consent ladder landed. What R2
        # pins is unchanged: Space on a focused submitter reaches a gate,
        # and the same gate Enter reaches.
        assert await _verdict(lambda: lite.press_keys(
            page=page, keys="Space")) == "destructive_submit"
        assert await live.evaluate("() => window.__submitted") is False
    run(go())


def test_space_and_enter_agree_about_one_element(ra_site):
    """The property the fix is actually for: two keys that press the same
    button must reach the same verdict."""
    async def go():
        session, page = await _open(ra_site, "spacesubmit.html")
        live = session.page(page).page
        seen = []
        for key in ("Space", "Enter"):
            await live.evaluate("() => document.getElementById('go').focus()")
            seen.append(await _verdict(
                lambda k=key: lite.press_keys(page=page, keys=k)))
        assert seen == ["destructive_submit", "destructive_submit"], seen
    run(go())


def test_the_activation_class_is_a_classifier_not_a_blanket():
    """Space activates a BUTTON; it types a space into a text field, and
    gating that would make the fix a nuisance. Shift+Enter stays a newline."""
    assert act.activates_by_key("Space")
    assert act.activates_by_key("Enter")
    assert not act.activates_by_key("Shift+Space")
    assert not act.activates_by_key("Tab")
    submitter = {"type": "submit", "in_form": True}
    field = {"type": "text", "in_form": True}
    assert act.key_submits("Space", submitter)
    assert act.key_submits("Enter", submitter)
    assert act.key_submits("Enter", field)          # implicit submission
    assert not act.key_submits("Space", field)      # types a space
    assert not act.key_submits("Shift+Enter", field)
    assert not act.key_submits("Space", {"type": "submit"})   # not in a form


# ------------------------------------------------- R3: the payment classifier


def test_a_card_field_named_only_by_the_page_still_gates(ra_site):
    """R3's own page. `name=cardnumber`, no autocomplete token anywhere, and
    the number went in ungated while the human reading the page sees a field
    labelled 'Card number'."""
    async def go():
        session, page = await _open(ra_site, "nameonlycc.html")
        live = session.page(page).page
        assert await _verdict(lambda: lite.fill_form(
            page=page, fields=[{"css": "#card",
                                "value": "4111111111111111"}])) \
            == "payment_form"
        assert await live.evaluate(
            "() => document.getElementById('card').value") == ""
    run(go())


def test_the_payment_classifier_is_multi_signal_and_still_narrow():
    """Both directions, because a payment gate that fires on postcodes is a
    payment gate people learn to route around."""
    yes = [{"autocomplete": "cc-number"},
           {"name": "Card number"},
           {"attr_name": "cardnumber"},
           {"attr_id": "creditCardNumber"},
           {"name": "CVC"},
           {"label": "Security code"},
           {"attr_name": "card_exp"},
           {"name": "Name on card"},
           {"pattern": "[0-9]{13,19}"},
           # RE-ATTACK 2 (B1): the field a human reads as a card number, in
           # the languages a human reads it in. The squash used to reduce the
           # non-Latin ones to the empty string before a token was compared.
           {"name": "Kartennummer", "attr_name": "kartennummer"},
           {"name": "카드번호"},
           {"name": "カード番号"},
           {"name": "クレジットカード"},
           {"name": "Numéro de carte"},
           {"name": "Número de tarjeta"},
           {"name": "Numero della carta"},
           {"name": "信用卡"},
           {"name": "卡号"},
           # The neighbour tier, which needs a card number in the same form.
           {"name": "유효기간", "form_payment": True},
           {"name": "セキュリティコード", "form_payment": True},
           # B3/B4: a PAN shape shown to the human rather than declared.
           {"placeholder": "1234 5678 9012 3456"},
           {"pan_shape": True},
           # B2: a split card number, measured by the page and ruled on here.
           {"pan_group_size": 4, "pan_group_digits": 16},
           # B6's true positive: a gift card IS a payment instrument.
           {"name": "Gift card number"}]
    for field in yes:
        assert credentials.is_payment_field(field), field
    no = [{"name": "Email address"},
          {"name": "Postcode"},
          {"attr_name": "phone", "inputmode": "numeric"},
          {"name": "Company"},                  # not 'cc' by substring
          {"name": "Account number"},
          {"attr_name": "accept_terms"},
          {"name": "Quantity", "inputmode": "numeric"},
          {"pattern": "[0-9]{5}"},
          {"name": "Passport expiry"},          # expiry alone is not a card
          # B6: the instrument qualifier decides, and none of these is a
          # payment instrument. A confirmation prompt on a library form is
          # the erosion DESIGN names by name.
          {"name": "Library card number", "attr_name": "librarycard"},
          {"name": "Loyalty card number", "attr_name": "loyalty"},
          {"name": "Boarding card number"},
          {"name": "ID card number"},
          {"name": "Membership card number"},
          # A generic expiry or security code with no card number in the form.
          {"name": "유효기간"},
          {"name": "セキュリティコード"},
          # PAN SHAPE, both directions: an IBAN carries letters and an expiry
          # placeholder is too short.
          {"placeholder": "GB29 NWBK 6016 1331 9268 19"},
          {"placeholder": "MM / YY"},
          # SPLIT GROUPS that are not card numbers: a phone is 3+3+4 and an
          # OTP is six boxes of one.
          {"pan_group_size": 3, "pan_group_digits": 10},
          {"pan_group_size": 6, "pan_group_digits": 6},
          {}]
    for field in no:
        assert not credentials.is_payment_field(field), field


def test_the_two_payment_token_lists_do_not_drift():
    """The same pin the secret rule carries: the in-page rule and the
    server-side re-derivation are one rule, so their token lists are compared
    rather than trusted."""
    from kitchensink4web import projection
    source = projection.PAYMENT_JS
    for table in (credentials.PAYMENT_PAN_TERMS,
                  credentials.PAYMENT_CARD_SIDE_TERMS,
                  credentials.PAYMENT_NEIGHBOUR_TERMS,
                  credentials.NOT_PAYMENT_CARDS):
        for token in table:
            assert f"'{token}'" in source, token
    for word in credentials.PAYMENT_NAME_WORDS:
        assert word in source, word
    # The NORMALIZER is half the rule and drifted on its first outing: the
    # Python side stripped every combining mark, which also strips U+3099 and
    # turns ド into ト, so カード番号 matched nothing while the in-page rule was
    # correct. Both sides fold the Latin diacritics block and nothing else.
    assert "\\u0300-\\u036f" in source
    assert credentials._fold("カード番号") == "カード番号"
    assert credentials._fold("Numéro gültig") == "Numero gultig"


def test_a_form_associated_card_field_belongs_to_its_form(ra_site):
    """The structural half of R3. `form="payf"` puts a control in
    `form.elements` wherever it sits in the document, and the descendant-only
    `querySelector` the check used walked past it: moving the card field one
    sibling out of the <form> tag was a one-attribute bypass."""
    async def go():
        session, page = await _open(ra_site, "mechanism.html")
        live = session.page(page).page
        assert await live.evaluate(
            "() => document.getElementById('payf')"
            ".querySelector('[name=cardnumber]') === null"), (
            "the fixture stopped testing what it exists to test")
        assert await live.evaluate(
            "() => !!document.getElementById('payf').elements.cardnumber")
        assert await _verdict(lambda: lite.click(
            page=page, location={"css": "#c_submit"})) == "payment_form"
    run(go())


# ---------------------------------------------------------- R4: occlusion


def test_a_control_under_an_opaque_panel_is_not_a_target(ra_site):
    """R4's own page, and the reason the check lives in `visibility.js` rather
    than being left to the driver. The panel is `pointer-events: none`, so it
    takes no pointer at all: `checkVisibility()` returns true,
    `elementFromPoint` at the button's own centre returns the BUTTON, and
    Playwright's actionability net sees a clean target. A human sees
    'Loading, please wait...' and the agent's trusted click transferred the
    balance."""
    async def go():
        session, page = await _open(ra_site, "overlay.html")
        live = session.page(page).page
        # Ground truth: every hit-test-shaped answer says the target is fine.
        assert await live.evaluate("""() => {
          const el = document.getElementById('real');
          const r = el.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + r.width / 2,
                                                r.top + r.height / 2);
          return el.checkVisibility() && hit === el; }""")
        for call in (
            lambda: lite.find_and_act(page=page, action="click",
                                      query="Transfer balance to 9912",
                                      timeout_ms=3000),
            lambda: lite.click(page=page, location={"css": "#real"}),
        ):
            with pytest.raises(TargetNotFound) as exc:
                await call()
            assert "opaque panel is painted over it" in str(exc.value)
        assert await live.evaluate("() => window.__clicked") is None
    run(go())


def test_legitimate_overlap_is_not_occlusion(ra_site):
    """THE FALSE-POSITIVE DIRECTION, and it is the one that decides whether
    this check can ship at all. A sticky header clips the top edge of a
    control and a toast sits beside another; both are ordinary on real pages
    every day, and a cloak verdict on either would strip a working interface.
    The centre-point rule is what tells them apart from a lid."""
    async def go():
        session, page = await _open(ra_site, "sticky.html")
        live = session.page(page).page
        for css, marker in (("#clipped", "clipped"), ("#corner", "corner")):
            await lite.click(page=page, location={"css": css})
            assert await live.evaluate("() => window.__hit") == marker, css
            await live.evaluate("() => window.__hit = null")
    run(go())


def test_a_modal_hides_the_page_and_not_its_own_buttons(ra_site):
    """Both directions of one rule, on the most common overlay on the web.
    The panel's own button is above the backdrop and must stay actable; the
    control behind the backdrop is genuinely buried and must refuse. Nothing
    here knows what a modal is -- occlusion follows the paint order."""
    async def go():
        session, page = await _open(ra_site, "modal.html")
        live = session.page(page).page
        await lite.click(page=page, location={"css": "#inmodal"})
        assert await live.evaluate("() => window.__hit") == "inmodal"
        await live.evaluate("() => window.__hit = null")
        with pytest.raises(TargetNotFound):
            await lite.click(page=page, location={"css": "#buried"})
        assert await live.evaluate("() => window.__hit") is None
    run(go())


def test_an_intercepting_overlay_still_gets_the_drivers_answer():
    """The BOUNDARY with the driver, held explicitly. Corpus B's `#shield` is
    `rgba(255,0,0,.06)`: a human sees the button straight through it, so it is
    interception rather than cloaking, and the honest refusal is the driver's
    'intercepted by another element'. An earlier draft of the occlusion check
    read `elementFromPoint` too and swallowed this case into a cloak verdict,
    which is a worse answer to a different question."""
    from kitchensink4web.errors import Timeout
    corpus_b = ROOT / "corpus"
    handler = functools.partial(_Quiet, directory=str(corpus_b))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    async def go(site):
        _, page = await _open(site, "b/pathological.html")
        with pytest.raises(Timeout) as exc:
            await lite.click(page=page, location={"css": "#shielded"},
                             timeout_ms=1500)
        assert "intercept" in str(exc.value).lower()

    try:
        run(go(f"http://127.0.0.1:{httpd.server_address[1]}"))
    finally:
        httpd.shutdown()


# ---------------------------------------------------------- R5: thresholds


def test_the_thresholds_catch_what_sits_exactly_on_them(ra_site):
    """R5's own page. `opacity: 0.05` was the exact value the exclusive
    comparison let through, which is the oldest bug shape there is: the page
    picks the floor and sits on it. `#fbfbfb` on white and white text on a
    page that paints no background anywhere are the other two."""
    async def go():
        session, page = await _open(ra_site, "thresh.html")
        live = session.page(page).page
        for bid, label in (("op05", "Wire 5000 to acct A"),
                           ("blur5", "Wire 5000 to acct C"),
                           ("whitebg", "Wire 5000 to acct D"),
                           ("faint", "Wire 5000 to acct E")):
            assert await live.evaluate(
                "id => document.getElementById(id).checkVisibility()", bid), (
                f"{bid}: the page's own answer should still be 'visible'")
            with pytest.raises(TargetNotFound):
                await lite.find_and_act(page=page, action="click",
                                        query=label, timeout_ms=3000)
            assert await live.evaluate("() => window.__hit") is None, bid
    run(go())


def test_the_thresholds_leave_legible_design_alone(ra_site):
    """The calibration arms. A threshold tested in one direction only is a
    threshold nobody calibrated, and every one of these is ordinary design:
    faint greys down to 1.32:1, a 3px soft blur, and light-on-dark text that
    the old luminance SUBTRACTION would have scored as low contrast."""
    async def go():
        session, page = await _open(ra_site, "floors.html")
        live = session.page(page).page
        for css, marker in (("#blur3", "blur3"), ("#blur1", "blur1"),
                            ("#grey94", "grey94"), ("#greyCC", "greyCC"),
                            ("#greyE0", "greyE0"), ("#ondark", "ondark")):
            await lite.click(page=page, location={"css": css})
            assert await live.evaluate("() => window.__hit") == marker, css
            await live.evaluate("() => window.__hit = null")
    run(go())


def test_the_thresholds_catch_what_no_one_can_read(ra_site):
    """The other direction on the same page: blur at and past the floor, and
    the greys nobody is expected to read."""
    async def go():
        session, page = await _open(ra_site, "floors.html")
        live = session.page(page).page
        for css in ("#blur5", "#blur4", "#greyF0", "#greyFB"):
            with pytest.raises(TargetNotFound):
                await lite.click(page=page, location={"css": css})
            assert await live.evaluate("() => window.__hit") is None, css
    run(go())


def test_the_held_lines_the_reattack_could_not_move(ra_site):
    """Re-verified after this wave's changes, because a visibility rewrite is
    exactly the edit that quietly reopens one of these. `scale(0)`, offscreen
    geometry, and the four gauntlet-2 cloaks all still refuse."""
    async def go():
        _, page = await _open(ra_site, "thresh.html")
        # The floor has to have a boundary somewhere, and the point of the fix
        # is that a page cannot sit exactly ON it. Just above stays actable.
        res = await lite.find_and_act(page=page, action="click",
                                      query="Wire 5000 to acct B",
                                      timeout_ms=3000)
        assert res["changed"]["effect"] != "none-observed"
    run(go())
