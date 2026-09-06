"""TWO BATTERIES THAT VARY THE THING, not the check.

`test_the_mechanism_battery` (re-attack 1) fixed the tool and the expected
verdict and varied the SUBMISSION MECHANISM, and it is the reason R1 and R2
cannot come back. Re-attack 2 (2026-09-06) found seven more breaks and every
one of them was the same shape one question along, so it asked for the same
treatment twice more:

  **VARY THE LID.** One buried button, one expected verdict, N constructions
  of the thing on top. Occlusion is not a list of techniques; it is the
  question "is this box covered", and fix wave 4 answered it for the single
  construction R4 happened to present -- a `<div>` with `background:#ffffff`.
  An `<img>`, a `<canvas>`, an `<iframe>`, an `<svg>`, a `backdrop-filter`, a
  stack of translucent boxes, a static grid item, a box inside an open shadow
  root, and a lid parked past the scan's budget all walked through.

  **VARY THE TARGET.** One card-carrying form, one expected verdict, N
  elements to click. The classifier modelled the element the tool TOUCHES, and
  the browser activates something else: `<label for=submitButton>` submitted
  the form ungated, and a wrapping label and a span inside a button are the
  same mechanism.

Both batteries carry their CONTROL side in the same file and the same run,
because a check that cloaks everything and a gate that fires on everything are
the same failure from the other direction. A sticky header clipping a button's
top edge, a toast beside it, a translucent shield a human reads straight
through, the documented centre badge, and a `type=button` control all have to
come back clean.

ADDING A CLASS IS ADDING A DICT ENTRY. Both batteries are parametrized over
the tables below, so a lid construction or an activation route that this build
does not classify fails a named test rather than shipping.
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


# --------------------------------------------------------------- the target
#
# ONE control, byte-identical on every page in the lid battery: R4's own
# "Transfer balance to 9912" button, so `ran` always means the trusted click
# landed on a real transfer and a refusal always means the technique was
# caught. Nothing about the target varies, which is what makes the lid the
# only variable.

_TARGET = """
<h1>Account</h1>
<button id=real style="position:absolute;left:40px;top:120px;width:320px;
   height:56px;font-size:17px">Transfer balance to 9912</button>
<script>window.__clicked=null;
document.getElementById('real').addEventListener('click',
  function(e){ window.__clicked = 'REAL-transfer-9912'; });</script>
"""

_HEAD = """<!doctype html><meta charset=utf-8><title>lid</title>
<style>body{margin:0;font:15px system-ui;background:#fff;height:900px}
.lid{position:fixed;left:20px;top:100px;width:380px;height:100px;
  z-index:10;pointer-events:none}</style>
"""

#: A 8x8 opaque black PNG and a 1x1 transparent GIF, inline so the battery
#: needs no network and no files on disk.
_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSnc"
        "AAAAD0lEQVR4nGP4jwMwDC0JALoev0Ewkwr8AAAAAElFTkSuQmCC")

#: EVERY LID CLASS, each one a construction that paints over the control while
#: declaring nothing the old two-question test could see. `pointer-events:none`
#: throughout, because a lid that takes the pointer is the driver's problem and
#: gets the driver's honest "intercepted by another element" refusal.
LID_CLASSES: dict[str, str] = {
    # The one wave 4 was written against, kept as the control for the class.
    "div-background": '<div class=lid style="background:#ffffff">Loading…</div>',
    # REPLACED ELEMENTS: the content is the paint and the background is
    # transparent, which is why the background test could not see any of them.
    "img": f'<img class=lid src="{_PNG}" style="width:380px;height:100px">',
    "canvas": '<canvas class=lid width=380 height=100 id=cv></canvas>'
              '<script>var c=document.getElementById("cv").getContext("2d");'
              'c.fillStyle="#fff";c.fillRect(0,0,380,100);</script>',
    "iframe": '<iframe class=lid srcdoc="<body style=\'background:#fff\'>'
              'Loading…</body>"></iframe>',
    "svg": '<svg class=lid viewBox="0 0 380 100">'
           '<rect width="380" height="100" fill="#ffffff"/></svg>',
    "video": '<video class=lid poster="' + _PNG + '"></video>',
    "object": f'<object class=lid data="{_PNG}" type="image/png"></object>',
    # PAINTS NOTHING AND OBLITERATES EVERYTHING.
    "backdrop-filter": '<div class=lid style="background:transparent;'
                       'backdrop-filter:blur(14px) brightness(2.4)"></div>',
    # A THRESHOLD NOBODY CAN SIT UNDER, one box at a time.
    "stacked-alpha": "".join(
        f'<div class=lid style="z-index:{10 + i};'
        f'background:rgba(255,255,255,.45)"></div>' for i in range(5)),
    # OVERLAP WITHOUT POSITIONING. Same-cell grid items are the standard way
    # to stack a loading state over content, and both boxes are `static`.
    "static-grid": '<style>.g{display:grid;grid-template-columns:1fr;'
                   'width:420px;position:absolute;left:20px;top:120px}'
                   '.g>*{grid-area:1/1}</style>'
                   '<div class=g><div id=under style="height:56px"></div>'
                   '<div style="background:#ffffff;height:56px;'
                   'pointer-events:none">Loading…</div></div>',
    # THE SCAN'S OWN BLIND SPOT: a light-tree query stops at every boundary.
    "shadow-root-box": '<div id=host></div><script>'
                       'document.getElementById("host").attachShadow({mode:"open"})'
                       '.innerHTML=\'<div style="position:fixed;left:20px;'
                       'top:100px;width:380px;height:100px;background:#fff;'
                       'z-index:10;pointer-events:none">Loading…</div>\';'
                       '</script>',
    # PAST THE BUDGET: 70 decorative boxes earlier in document order used to
    # fill a 60-occluder cap with chaff before the lid was reached.
    "past-the-cap": "".join(
        f'<div style="position:absolute;left:{2 + i * 3}px;top:600px;'
        f'width:12px;height:12px;background:#eee;z-index:1"></div>'
        for i in range(70))
        + '<div class=lid style="background:#fff">Loading…</div>',
    # RAISED BY THE ACTING PATH'S OWN FOCUS: clean at resolution, clean when
    # the class is computed, opaque by the time the click lands.
    "raised-on-focus": '<script>'
                       'document.getElementById("real").addEventListener('
                       '"focus", function(){'
                       'var d=document.createElement("div");d.className="lid";'
                       'd.style.background="#fff";d.textContent="Loading…";'
                       'document.body.appendChild(d);});</script>',
}

#: THE CONTROL SIDE, in the same battery and the same run. Every one of these
#: is ordinary furniture on real pages and every one must still act, because a
#: cloak check that strips working interfaces cannot ship at all.
CLEAR_CLASSES: dict[str, str] = {
    # A sticky header clipping the button's top edge and nothing else.
    "sticky-clip": '<div style="position:fixed;top:0;left:0;width:100%;'
                   'height:130px;background:#fff;z-index:900">A sticky header'
                   '</div>',
    # A toast overlapping one corner, well clear of the label.
    "corner-toast": '<div style="position:fixed;left:300px;top:150px;'
                    'width:200px;height:60px;background:#333;color:#fff;'
                    'z-index:900;pointer-events:none">Saved</div>',
    # A tint a human reads straight through: corpus B's shield alpha.
    "translucent-shield": '<div class=lid style="background:'
                          'rgba(255,0,0,.06)"></div>',
    # The documented centre-badge trade (wave 4, re-attack 2 A9): most of the
    # label is legible, so the control stays actable.
    "centre-badge": '<div style="position:fixed;left:170px;top:138px;'
                    'width:60px;height:20px;background:#fff;z-index:10;'
                    'pointer-events:none">Sign out</div>',
    # Nothing on top at all, which is the floor of the whole battery.
    "nothing": "",
}


# ------------------------------------------------------- the target battery
#
# One card-carrying form; every row is a different ELEMENT TO CLICK and every
# row submits the same form, so every row must reach `payment_form`. The
# negative arm submits nothing and must stay ungated.

_FORM_PAGE = """<!doctype html><meta charset=utf-8><title>targets</title>
<body style="font:15px system-ui">
<form id=pay action="about:blank" onsubmit="window.__submitted=true;return false">
  <label for=cc>Card number</label><input id=cc name=cardnumber>
  <button id=t_button type=submit>Pay now</button>
  <input id=t_input type=submit value="Pay by input">
  <input id=t_image type=image alt="Pay by image"
     src="data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==">
  <button id=t_typeless>Pay typeless</button>
  <button id=t_wrapper type=submit><span id=t_span>Pay by span</span></button>
  <button id=t_hidden type=submit style="position:absolute;left:-9999px">go</button>
  <label id=t_labelfor for=t_hidden style="display:inline-block;padding:8px">
    Continue</label>
  <label id=t_labelwrap style="display:inline-block;padding:8px">
    Wrapped<input id=t_wrapped type=submit value="Pay wrapped"></label>
  <button id=t_plain type=button onclick="window.__plain='ran'">Not a submit</button>
</form>
<script>window.__submitted=null;window.__plain=null;</script>
"""

#: EVERY WAY A CLICK REACHES THE SUBMIT. The first four are the element
#: itself; the rest are DELEGATED -- the browser activates something other
#: than the node the tool touched.
TARGET_CLASSES: dict[str, str] = {
    "button-type-submit": "#t_button",
    "input-type-submit": "#t_input",
    "input-type-image": "#t_image",
    "typeless-button-in-form": "#t_typeless",
    "span-inside-a-button": "#t_span",
    "label-for": "#t_labelfor",
    "label-wrapping-its-control": "#t_labelwrap",
}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def battery_site():
    """One directory, one page per class, generated from the tables above so
    that adding a class is adding a dict entry and nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, lid in {**LID_CLASSES, **CLEAR_CLASSES}.items():
            (root / f"{name}.html").write_text(_HEAD + _TARGET + lid,
                                               encoding="utf-8")
        (root / "targets.html").write_text(_FORM_PAGE, encoding="utf-8")
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


# ------------------------------------------------------ BATTERY 1: THE LID


@pytest.mark.parametrize("lid_class", sorted(LID_CLASSES))
def test_the_lid_battery(battery_site, lid_class):
    """SAME target, SAME expected verdict, EVERY construction of the thing on
    top. A lid this build cannot see fails here, by name, rather than shipping
    as a trusted click on a control the human never saw."""
    async def go():
        session, page = await _open(battery_site, f"{lid_class}.html")
        live = session.page(page).page
        verdict = await _verdict(lambda: lite.click(
            page=page, location={"css": "#real"}))
        clicked = await live.evaluate("() => window.__clicked")
        assert verdict == "refused_cloak", f"{lid_class}: {verdict}"
        assert clicked is None, f"{lid_class} clicked the buried control"
    run(go())


@pytest.mark.parametrize("clear_class", sorted(CLEAR_CLASSES))
def test_the_lid_battery_leaves_legitimate_overlap_alone(battery_site,
                                                         clear_class):
    """THE FALSE-POSITIVE DIRECTION, run in the same battery. A header
    clipping an edge, a toast beside the control, a tint a human reads through
    and the documented centre badge are all ordinary, and cloaking any of them
    would strip a working interface."""
    async def go():
        session, page = await _open(battery_site, f"{clear_class}.html")
        live = session.page(page).page
        verdict = await _verdict(lambda: lite.click(
            page=page, location={"css": "#real"}))
        assert verdict == "ran", f"{clear_class}: {verdict}"
        assert await live.evaluate("() => window.__clicked") \
            == "REAL-transfer-9912"
    run(go())


def test_every_lid_class_is_a_paint_class_and_not_a_tag_list():
    """The battery's own completeness check. These are the four MEANS by which
    a box paints over a control, and every entry above belongs to one of them:
    a declared background, an element whose content is its paint, a filter
    applied to the backdrop, and a stack that composites. A new entry that
    fits none of them is a new class and wants its own reasoning."""
    replaced = {"img", "canvas", "iframe", "svg", "video", "object"}
    background = {"div-background", "static-grid", "past-the-cap",
                  "raised-on-focus", "shadow-root-box"}
    assert replaced | background | {"backdrop-filter", "stacked-alpha"} \
        == set(LID_CLASSES)


# --------------------------------------------------- BATTERY 2: THE TARGET


@pytest.mark.parametrize("target_class", sorted(TARGET_CLASSES))
def test_the_target_battery(battery_site, target_class):
    """SAME form, SAME expected verdict, EVERY element a click reaches the
    submit through. The last three are DELEGATED activation: the browser runs
    the control's activation behaviour on behalf of the node that was clicked,
    and the classifier has to model the element that acts rather than the
    element that was touched."""
    async def go():
        session, page = await _open(battery_site, "targets.html")
        live = session.page(page).page
        verdict = await _verdict(lambda: lite.click(
            page=page, location={"css": TARGET_CLASSES[target_class]}))
        assert verdict == "payment_form", f"{target_class}: {verdict}"
        assert await live.evaluate("() => window.__submitted") is None, \
            f"{target_class} submitted the form before the gate"
    run(go())


def test_the_target_battery_gates_nothing_that_does_not_submit(battery_site):
    """The direction that keeps the battery a safety property rather than a
    mute button: `type=button` activates itself, submits nothing, and must run
    ungated even though it sits inside the card-carrying form."""
    async def go():
        session, page = await _open(battery_site, "targets.html")
        live = session.page(page).page
        await lite.click(page=page, location={"css": "#t_plain"})
        assert await live.evaluate("() => window.__plain") == "ran"
        assert await live.evaluate("() => window.__submitted") is None
    run(go())


def test_a_delegated_click_is_classified_as_its_control():
    """The unit half, so the rule is pinned without a browser. The descriptor
    the tool sees says `label`, which is neither a payment field nor a
    submitter; the delegate says otherwise and the delegate is what acts."""
    from kitchensink4web.ops import act

    label = {"role": "generic", "tag": "LABEL", "name": "Continue",
             "activates": {"tag": "BUTTON", "type": "submit", "in_form": True,
                           "form_payment": True}}
    assert act.action_class_for(label) == "payment_form"

    plain = dict(label, activates=dict(label["activates"],
                                       form_payment=False))
    assert act.action_class_for(plain) == "form_submit"

    nothing = {"role": "generic", "tag": "SPAN", "name": "just text"}
    assert act.action_class_for(nothing) is None

    # A label over a card FIELD is a write to that field.
    field = {"role": "generic", "tag": "LABEL", "name": "Card number",
             "activates": {"tag": "INPUT", "type": "text",
                           "attr_name": "cardnumber", "in_form": True}}
    assert act.action_class_for(field) == "payment_form"


def test_the_two_cloak_vocabularies_do_not_drift():
    """The same pin the payment token lists carry. The write-time re-check
    reads a cloak REASON off the live-field probe rather than running the
    cloak probe a second time, so the refusal text it prints comes from a
    Python mirror of `KS_CLOAK_TECHNIQUES`, and a technique added to one and
    not the other would refuse with the reason code instead of a sentence."""
    from kitchensink4web import projection
    from kitchensink4web.ops import act

    source = projection.VISIBILITY_JS
    block = source.split("KS_CLOAK_TECHNIQUES = {", 1)[1].split("};", 1)[0]
    in_page = {line.split("'")[1] for line in block.splitlines()
               if "'" in line and ":" in line}
    assert in_page == set(act._CLOAK_WHY), in_page ^ set(act._CLOAK_WHY)


def test_enter_is_a_submission_only_in_a_single_line_control():
    """C2, the other side of the same coin. The browser inserts a newline in a
    textarea and submits nothing, so a confirmation prompt there is a gate
    people learn to click through; `key_submits`' own docstring already said
    'single-line' and nothing implemented it."""
    from kitchensink4web.ops import act

    assert act.key_submits("Enter", {"in_form": True, "tag": "INPUT"})
    assert not act.key_submits("Enter", {"in_form": True, "tag": "TEXTAREA"})
    assert not act.key_submits("Enter", {"in_form": True, "tag": "DIV",
                                         "editable": True})
    # A missing tag is single-line: a global press_keys with no location knows
    # least about where the keystroke lands and must not lose the gate.
    assert act.key_submits("Enter", {"in_form": True})
    # And the ACTIVATION branch is untouched by the tag: Space on a focused
    # submitter presses it wherever it lives.
    assert act.key_submits("Space", {"in_form": True, "tag": "INPUT",
                                     "type": "image"})
