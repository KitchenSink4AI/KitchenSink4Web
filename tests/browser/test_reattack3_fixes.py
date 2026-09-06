"""Re-attack 3's findings, each pinned by the fixture that found it.

The two batteries in `test_occlusion_battery.py` carry R1 through R4 and the
click/type parity gap, because those are the findings whose class is "vary the
scope" and a battery is the right shape for them. What lives here is the rest:
the split-PAN group, delegated activation across a shadow boundary, and the
five over-gates, each of which is one rule answering one question and wants a
named test rather than a table row.

Every page below is the attacker's own fixture, transcribed rather than
paraphrased, so a regression fails against the markup that actually broke.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import tempfile
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import ConfirmationRequired, TargetNotFound
from kitchensink4web.ops import lite
from kitchensink4web.policy import audit, budgets, credentials, readonly

pytestmark = pytest.mark.browser


_HEAD = ('<!doctype html><meta charset=utf-8><title>pay</title>'
         '<body style="font:15px system-ui">')
_SUBMITTED = '<script>window.__submitted=null;</script>'


def _form(inner: str) -> str:
    return (_HEAD + '<form id=f action="about:blank" '
            'onsubmit="window.__submitted=true;return false">' + inner
            + '<button id=go type=submit>Continue</button></form>' + _SUBMITTED)


def _boxes(spec, wrap: bool = False) -> str:
    out = []
    for i, ml in enumerate(spec):
        box = (f'<input id=n{i} name=cc{i} type=text maxlength={ml} '
               f'inputmode=numeric pattern="[0-9]{{{ml}}}">')
        out.append(f'<div class=col>{box}</div>' if wrap else box)
    return "".join(out)


#: name -> (html, fill verdict, submit verdict). The fill and the submit are
#: BOTH asserted on every row, because B2's end-to-end failure was that the
#: number went in ungated AND the submit that sent it got the weaker gate, and
#: a fix that closes one of those is half a fix.
PAGES: dict[str, tuple[str, str, str]] = {
    # R5. The same four boxes wave 5 closed, each in its own column <div>,
    # which is what every CSS framework does to build a row. The group was
    # `closest('fieldset') || parentElement`, so each box was alone in a group
    # of one and no tier fired.
    "split-wrapped-in-columns": (
        _form('<div>Card number</div><div class=row>'
              + _boxes([4, 4, 4, 4], wrap=True) + '</div>'),
        "payment_form", "payment_form"),
    # R5, one attribute along. `size` and a `pattern` say what `maxlength`
    # says, and nothing truncated the input either, so the full sixteen digits
    # landed in the field.
    "split-no-maxlength": (
        _form('<fieldset><legend>Card number</legend>'
              + "".join(f'<input id=n{i} name=cc{i} size=4 inputmode=numeric '
                        'pattern="[0-9]{4}">' for i in range(4))
              + '</fieldset>'),
        "payment_form", "payment_form"),
    # M1. B6 struck `librarycard` out of the NAME tier and the GROUP tier
    # never read a name, so the same rule gave two answers on one page.
    "split-library-card": (
        _form('<fieldset><legend>Library card number</legend>'
              + _boxes([4, 4, 4, 4]) + '</fieldset>'),
        "ran", "form_submit"),
    # M2. A date of birth and a texted code: four short numeric boxes,
    # fourteen digits, inside the same count window and nothing like a card.
    "dob-plus-code": (
        _form('<fieldset><legend>Your details</legend>'
              '<label for=n0>Day</label>'
              '<input id=n0 name=dd type=text maxlength=2 inputmode=numeric>'
              '<label for=n1>Month</label>'
              '<input id=n1 name=mm type=text maxlength=2 inputmode=numeric>'
              '<label for=n2>Year</label>'
              '<input id=n2 name=yyyy type=text maxlength=4 inputmode=numeric>'
              '<label for=n3>Code we texted you</label>'
              '<input id=n3 name=otp type=text maxlength=6 inputmode=numeric>'
              '</fieldset>'),
        "ran", "form_submit"),
    # M3. Sixteen mask characters in four groups is structurally a masked PAN;
    # what says otherwise is that the page named the field IBAN.
    "masked-iban": (
        _form('<label for=n0>IBAN</label>'
              '<input id=n0 name=iban type=text value="**** **** **** ****">'),
        "ran", "form_submit"),
    # THE TRUE POSITIVES, in the same file and the same run. A rule that stops
    # over-gating by under-gating has not been fixed.
    "split-flat-control": (
        _form('<fieldset><legend>Card number</legend>'
              + _boxes([4, 4, 4, 4]) + '</fieldset>'),
        "payment_form", "payment_form"),
    "split-amex-4-6-5": (
        _form('<fieldset><legend>Card</legend>' + _boxes([4, 6, 5])
              + '</fieldset>'),
        "payment_form", "payment_form"),
    # THE GATE CONDITION on the neighbour tier, which is the erosion direction:
    # an expiry in Korean with no card number anywhere must not gate.
    "korean-expiry-only": (
        _form('<label for=n0>유효기간</label><input id=n0 name=exp type=text>'),
        "ran", "form_submit"),
}

#: R6. A `<pay-box>` whose open shadow root holds the form and the submit
#: button, and one light-DOM `<span>` the slot renders INSIDE that button.
#: `closest()` climbs span -> pay-box -> body and finds nothing activatable,
#: so the class was never computed and the card-carrying form went.
_SHADOW_ACTIVATION = """<!doctype html><meta charset=utf-8><title>sa</title>
<body style="font:15px system-ui">
<pay-box><span id=go>Pay now</span></pay-box>
<script>window.__submitted=null;
class PayBox extends HTMLElement{connectedCallback(){
  const r=this.attachShadow({mode:'open'});
  r.innerHTML='<form id=f><label for=cc>Card number</label>'
    +'<input id=cc name=cardnumber>'
    +'<button id=b type=submit><slot></slot></button></form>';
  r.getElementById('f').addEventListener('submit',function(e){
    window.__submitted=true;e.preventDefault();});
}}
customElements.define('pay-box',PayBox);</script>
"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def ra3_site():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, (html, _, _) in PAGES.items():
            (root / f"{name}.html").write_text(html, encoding="utf-8")
        (root / "shadow_activation.html").write_text(_SHADOW_ACTIVATION,
                                                     encoding="utf-8")
        handler = functools.partial(_Quiet, directory=str(root))
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
    try:
        await call()
        return "ran"
    except ConfirmationRequired as exc:
        text = str(exc)
        if "payment-shaped" in text:
            return "payment_form"
        if "submitting a form" in text:
            return "form_submit"
        return "gated"
    except TargetNotFound:
        return "refused_cloak"


@pytest.mark.parametrize("page_name", sorted(PAGES))
def test_the_split_pan_group_is_a_run_and_reads_its_region(ra3_site, page_name):
    """One page, both halves. The write into the first box and the submit that
    would send the number are asserted together, because the group rule feeds
    both and a fix that only reaches one of them leaves the number ungated on
    the way in or the submit under-gated on the way out."""
    _, fill_expect, click_expect = PAGES[page_name]

    async def go():
        session, page = await _open(ra3_site, f"{page_name}.html")
        live = session.page(page).page
        got_fill = await _verdict(lambda: lite.fill_form(
            page=page, fields=[{"css": "#n0", "value": "4111111111111111"}]))
        assert got_fill == fill_expect, f"{page_name} fill: {got_fill}"
        if fill_expect != "ran":
            assert await live.evaluate(
                "() => document.getElementById('n0').value") == "", \
                f"{page_name} wrote the number before the gate"
        # A FRESH LOAD for the submit half, and the reason is a real rule
        # rather than hygiene: on the rows where the write is allowed to run,
        # the value it wrote is a live PAN sitting in the field, which makes
        # the form payment-shaped on its own. Asserting the submit against a
        # page carrying a card number would be asserting the wrong thing.
        await lite.navigate(page=page, url=f"{ra3_site}/{page_name}.html")
        got_click = await _verdict(lambda: lite.click(
            page=page, location={"css": "#go"}))
        assert got_click == click_expect, f"{page_name} submit: {got_click}"
        assert await live.evaluate("() => window.__submitted") is None
    run(go())


def test_a_slotted_span_activates_the_shadow_button_it_sits_inside(ra3_site):
    """R6. The browser runs the innermost activatable element's behaviour in
    the FLATTENED tree, which is what `activation.js` states at the top and
    what `closest()` cannot see. Clicking the span pressed a submit button
    inside an open shadow root and sent a form carrying a card number with no
    class computed at all."""
    async def go():
        session, page = await _open(ra3_site, "shadow_activation.html")
        live = session.page(page).page
        got = await _verdict(lambda: lite.click(page=page,
                                                location={"css": "#go"}))
        assert got == "payment_form", got
        assert await live.evaluate("() => window.__submitted") is None
    run(go())


def test_the_instrument_qualifier_is_the_closed_set_and_not_the_open_one():
    """M4, and it is the shape of the whole wave. B6 named the right rule --
    the token before `card` names the instrument -- and enumerated the things
    a card can be that are NOT payment instruments, which is unbounded.
    `Residence card number` was the unlisted member and it is the standard
    foreign-resident ID across this build's own market. The payment
    instruments are the small closed set, so anything outside it is foreign
    without anybody adding an entry."""
    for name in ("Residence card number", "Fishing card number",
                 "Parking card number", "Library card number",
                 "Boarding card number", "Vaccination card number"):
        assert not credentials.is_payment_field({"name": name}), name
    for name in ("Card number", "Credit card number", "Gift card number",
                 "Debit card number", "Bank card number", "Name on card",
                 "Prepaid card number"):
        assert credentials.is_payment_field({"name": name}), name
    # The corroborated case: a form the page itself says is payment-shaped
    # brings the foreign compound back in.
    assert credentials.is_payment_field({"name": "Residence card number",
                                         "form_payment": True})


def test_a_shape_never_outranks_a_name():
    """M3 and M5. A PAN-shaped `pattern`, placeholder, or mask is a real
    signal and none of them is a NAME, so a phone field declaring
    `[0-9]{13,15}`, an IMEI field showing fifteen digits, a tracking-number
    field showing four groups of four, and a field labelled IBAN holding a
    sixteen-character mask all gated as payment on shape alone. A page that
    names its field is telling the truth about it."""
    named_but_not_a_card = [
        {"attr_name": "phone", "pattern": "[0-9]{13,15}"},
        {"label": "IMEI", "attr_name": "imei",
         "placeholder": "123456789012345"},
        {"name": "Tracking number", "placeholder": "1234 5678 9012 3456"},
        {"label": "IBAN", "attr_name": "iban", "pan_shape": True},
        {"name": "Account number", "placeholder": "1234 5678 9012 3456"},
    ]
    for field in named_but_not_a_card:
        assert not credentials.is_payment_field(field), field

    # UNNAMED, so the shape is all there is and it speaks. These are B3/B4's
    # own rows and they must not move.
    for field in ({"placeholder": "1234 5678 9012 3456"}, {"pan_shape": True},
                  {"pattern": "[0-9]{13,19}"}):
        assert credentials.is_payment_field(field), field

    # NAMED and corroborated: the same masked value on a form the page says is
    # payment-shaped is a card number again.
    assert credentials.is_payment_field(
        {"label": "IBAN", "attr_name": "iban", "pan_shape": True,
         "form_payment": True})


def test_the_split_group_partition_is_what_separates_a_pan_from_a_date():
    """M2 server-side. The count is two-to-six boxes and thirteen-to-nineteen
    digits, and a date of birth plus a texted code sits inside it. Card
    numbers are written in groups of four or more; a date leads with a
    two-digit day, so the run has to lead with four and hold no box shorter
    than four."""
    card = {"pan_group_size": 4, "pan_group_digits": 16,
            "pan_group_first": 4, "pan_group_min": 4, "pan_group_region": 0}
    assert credentials.is_payment_field(card)
    assert credentials.is_payment_field(
        dict(card, pan_group_size=3, pan_group_digits=15, pan_group_min=4))
    assert not credentials.is_payment_field(
        dict(card, pan_group_digits=14, pan_group_first=2, pan_group_min=2))
    assert not credentials.is_payment_field(dict(card, pan_group_region=-1))
    # The measurements a page omits leave B2's original rule in force, so an
    # older descriptor cannot be replayed to weaken the gate.
    assert credentials.is_payment_field({"pan_group_size": 4,
                                         "pan_group_digits": 16})


def test_every_payment_splice_site_also_splices_the_visibility_block():
    """A wiring invariant, and it is load-bearing rather than tidy.
    `payment.js` and `activation.js` both climb the FLATTENED tree now, which
    means both call `ksUp`, which lives in `visibility.js`. A script that
    splices one block and not the other loads fine and throws at call time,
    which is the worst way for a classifier to fail."""
    import re

    from kitchensink4web import projection

    root = Path(projection.__file__).parent.parent
    for path in sorted(root.rglob("*.py")) + sorted(root.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for mark in ("@@KS4WEB_PAYMENT@@", "@@KS4WEB_ACTIVATION@@"):
            for hit in re.finditer(re.escape(mark), text):
                before = text[max(0, hit.start() - 400):hit.start()]
                assert "@@KS4WEB_VISIBILITY@@" in before, (
                    f"{path.name} splices {mark} without the visibility block "
                    f"above it; the flattened-tree climb would throw")


def test_the_new_payment_tables_do_not_drift():
    """The same pin the token lists already carry, extended to the two lists
    that replaced the hand-maintained one."""
    from kitchensink4web import projection

    source = projection.PAYMENT_JS
    for table in (credentials.PAYMENT_CARD_QUALIFIERS,
                  credentials.TRANSPARENT_QUALIFIERS):
        for token in table:
            assert f"'{token}'" in source, token
    # And the strike itself agrees on both sides, which is what the two lists
    # are for.
    for hay, expect_foreign in ((" library card number ", True),
                                (" gift card number ", False),
                                (" name on card ", False),
                                (" card number ", False),
                                (" residence card number ", True)):
        _, foreign = credentials.foreign_card_strike(hay)
        assert foreign is expect_foreign, hay
