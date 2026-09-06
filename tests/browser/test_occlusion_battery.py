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
import inspect
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


# ------------------------------------------------------ BATTERY 3: THE SCOPE
#
# VARY WHERE THE LID LIVES, and hold the technique fixed. Re-attack 3 named
# the shape every one of its six HIGH findings shared: the SCOPE of a correct
# rule rather than the rule itself. Wave 5 asked "what paints" and answered it
# over the same set of nodes as before; it asked "how opaque is this box" and
# read the answer off a declaration; it asked "which is on top" and compared
# two numbers from different scales. The measurement got better and the domain
# it was measured over did not move.
#
# So this battery fixes the technique -- ONE `background:#ffffff` panel over
# the same button, the same expected refusal -- and varies the only thing
# left: where the panel is attached. On an element, on a pseudo-element, on an
# ANCESTOR's pseudo-element, inside a foreign stacking context, inside an open
# shadow root, behind an overflow clip, and one microtask later. A scope this
# build cannot reach fails here by name.
_SCOPE_LID = 'background:#ffffff;pointer-events:none'

SCOPE_CLASSES: dict[str, str] = {
    # The floor: the lid is an element, in the document, at the root.
    "element": f'<div class=lid style="{_SCOPE_LID}">Loading…</div>',
    # A pseudo-element paints and is not an element, so an element walk never
    # sees it however many paint MEANS it knows (R1).
    "pseudo-element": '<style>#scrim{position:fixed;left:0;top:0;width:1px;'
                      'height:1px}#scrim::after{content:"Loading…";'
                      'position:fixed;left:20px;top:100px;width:380px;'
                      f'height:100px;z-index:10;pointer-events:none;{_SCOPE_LID}'
                      '}</style><div id=scrim></div>',
    # The same technique on an ANCESTOR of the target, which is where a
    # full-bleed scrim actually lives and which the containment filter used to
    # skip twice over.
    "ancestor-pseudo-element": '<style>body::after{content:"";position:fixed;'
                               f'inset:0;z-index:10;{_SCOPE_LID}}}</style>',
    # A FOREIGN STACKING CONTEXT. The button declares z-index:9999 and sits
    # inside a context painted at 0, entirely beneath a lid at 1 (R2).
    "foreign-stacking-context":
        '<style>#ctx{position:relative;z-index:0}'
        '#real{position:relative!important;z-index:9999;left:0!important;'
        'top:0!important}</style>'
        '<script>var b=document.getElementById("real");'
        'var c=document.createElement("div");c.id="ctx";'
        'c.style.cssText="position:absolute;left:40px;top:120px";'
        'b.parentNode.insertBefore(c,b);c.appendChild(b);</script>'
        f'<div class=lid style="{_SCOPE_LID};z-index:1">Loading…</div>',
    # An open shadow root, which a light-tree query stops dead at.
    "shadow-root": '<div id=host></div><script>'
                   'document.getElementById("host").attachShadow({mode:"open"})'
                   '.innerHTML=\'<div style="position:fixed;left:20px;top:100px;'
                   f'width:380px;height:100px;z-index:10;{_SCOPE_LID}">'
                   'Loading…</div>\';</script>',
    # A SCROLLED CONTAINER, on the lid side this time: the panel is inside an
    # overflow box and really is painted over the control, so the pixel
    # arbiter has to confirm rather than clear it.
    "scrolled-container":
        '<div style="position:fixed;left:20px;top:100px;width:380px;'
        'height:100px;overflow:auto;z-index:10;pointer-events:none">'
        '<div style="height:60px"></div>'
        f'<div style="height:400px;{_SCOPE_LID}">Loading…</div></div>'
        '<script>document.currentScript.previousElementSibling'
        '.scrollTop=60;</script>',
    # ONE MICROTASK LATER, raised by the focus the acting path itself causes
    # (R3). Deterministic, not a timing race: it fires on every run.
    "one-microtask-later":
        '<script>document.getElementById("real").addEventListener("focus",'
        'function(){queueMicrotask(function(){'
        'var d=document.createElement("div");d.className="lid";'
        f'd.style.cssText="{_SCOPE_LID}";d.textContent="Loading…";'
        'document.body.appendChild(d);});});</script>',
    # And one animation frame later, which is the same window one queue along.
    "one-frame-later":
        '<script>document.getElementById("real").addEventListener("focus",'
        'function(){requestAnimationFrame(function(){'
        'var d=document.createElement("div");d.className="lid";'
        f'd.style.cssText="{_SCOPE_LID}";d.textContent="Loading…";'
        'document.body.appendChild(d);});});</script>',
}


# ------------------------------------------------- BATTERY 4: THE CLEAR SIDE
#
# THE SEVEN ORDINARY CONSTRUCTIONS, as permanent must-stay-visible fixtures.
# Wave 5's clear arm had five rows and all five varied the GEOMETRY of an
# overlay that really does paint. Not one row varied whether the overlay
# PAINTS AT ALL, which is why seven constructions that paint nothing over the
# control refused every acting call on the page. DESIGN states the invariant
# in its own words -- the choice trades a missed cloak for never stripping a
# real control off a real page, which is the direction this whole check has to
# fail in -- so the direction gets its own battery and its own row per
# construction.
#
# Every one of these is furniture on real marketing and checkout pages, and
# every one declares an opaque box over the control while painting nothing
# there. The common thread is that a DECLARATION is not a pixel, which is what
# the arbiter exists to settle.
CLEAR_SIDE_CLASSES: dict[str, str] = {
    # The rect is not the painted region: clip-path moves the paint away.
    "clip-path": '<div class=lid style="background:#ffffff;'
                 'clip-path:inset(0 0 0 100%)">x</div>',
    # The same, by a mask that keeps nothing.
    "transparent-mask": '<div class=lid style="background:#ffffff;'
                        '-webkit-mask-image:linear-gradient(transparent,'
                        'transparent);mask-image:linear-gradient(transparent,'
                        'transparent)">x</div>',
    # A tag is not its content: a decorative full-viewport <svg> whose one
    # painted path is in a corner. The confetti and wave-divider layer.
    "decorative-svg": '<svg style="position:fixed;inset:0;width:100%;'
                      'height:100%;z-index:50;pointer-events:none" '
                      'viewBox="0 0 100 100" preserveAspectRatio=none>'
                      '<circle cx=95 cy=95 r=2 fill="#f0f"/></svg>',
    # The same, as a canvas that has never been drawn to.
    "undrawn-canvas": '<canvas width=800 height=900 style="position:fixed;'
                      'inset:0;width:100%;height:100%;z-index:50;'
                      'pointer-events:none"></canvas>',
    # AN ANCESTOR'S OVERFLOW CLIP. A chat log, a sidebar, a long table: the
    # children's bounding rects run far outside the clip and sweep over
    # everything. Nothing about this page is hostile.
    "scrolled-overflow": '<div id=sc style="position:absolute;left:0;top:400px;'
                         'width:420px;height:200px;overflow:auto">'
                         + "".join(
                             f'<div style="height:120px;background:#ffffff;'
                             f'border-bottom:1px solid #ccc">Message {i}</div>'
                             for i in range(12))
                         + '</div><script>document.getElementById("sc")'
                           '.scrollTop=900;</script>',
    # A loaded <img> whose every pixel is alpha 0: the oldest spacer trick on
    # the web, still shipping in email-derived layouts.
    "transparent-spacer-img": '<img class=lid style="width:380px;height:100px" '
                              'src="data:image/gif;base64,R0lGODlhAQABAIAAAAAA'
                              'AP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">',
    # Compositing is not multiplication: white multiplied is identity.
    "mix-blend-mode": '<div class=lid style="background:#ffffff;'
                      'mix-blend-mode:multiply"></div>',
}


#: THE PARITY ARM. Same technique, same page shape, a control you TYPE into
#: rather than click. Re-attack 3 recorded that `type_text` caught the
#: microtask lid while `click` did not, and named the parity gap itself as the
#: tell: the one-turn design is what created the window, and the path that did
#: less in one turn was the one that was safe. Both paths refuse now, and this
#: is what stops them drifting apart again.
_TYPE_TARGET = """
<h1>Account</h1>
<input id=real style="position:absolute;left:40px;top:120px;width:320px;
   height:40px;font-size:17px" placeholder="Note">
"""

SCOPE_CLASSES_TYPING = (
    '<script>document.getElementById("real").addEventListener("focus",'
    'function(){queueMicrotask(function(){'
    'var d=document.createElement("div");d.className="lid";'
    'd.style.cssText="background:#ffffff;pointer-events:none";'
    'd.textContent="Loading\\u2026";document.body.appendChild(d);});});</script>'
)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def battery_site():
    """One directory, one page per class, generated from the tables above so
    that adding a class is adding a dict entry and nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, lid in {**LID_CLASSES, **CLEAR_CLASSES,
                          **{f"scope_{k}": v for k, v in SCOPE_CLASSES.items()},
                          **{f"clear_{k}": v
                             for k, v in CLEAR_SIDE_CLASSES.items()}}.items():
            (root / f"{name}.html").write_text(_HEAD + _TARGET + lid,
                                               encoding="utf-8")
        (root / "type_scope.html").write_text(_HEAD + _TYPE_TARGET
                                              + SCOPE_CLASSES_TYPING,
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


# ------------------------------------------------------ BATTERY 3: THE SCOPE


@pytest.mark.parametrize("scope_class", sorted(SCOPE_CLASSES))
def test_the_scope_battery(battery_site, scope_class):
    """ONE technique, ONE expected verdict, EVERY place the lid can live.

    This is re-attack 3's own prescription, and it is aimed at the failure
    mode three waves in a row have shared: a rule that is correct over the set
    of things it happens to be measured across. Wave 5 could see a `<canvas>`
    lid and could not see a `::after` one; it could measure a lid's alpha
    exactly and could not tell which of two boxes the browser paints on top.
    Nothing about the technique changed between those rows -- only where the
    panel was attached."""
    async def go():
        session, page = await _open(battery_site, f"scope_{scope_class}.html")
        live = session.page(page).page
        verdict = await _verdict(lambda: lite.click(
            page=page, location={"css": "#real"}))
        clicked = await live.evaluate("() => window.__clicked")
        assert verdict == "refused_cloak", f"{scope_class}: {verdict}"
        assert clicked is None, f"{scope_class} clicked the buried control"
    run(go())


def test_click_and_type_refuse_the_same_lid(battery_site):
    """THE PARITY ARM, and the parity is the point.

    A microtask queued by the focus handler defeated `click` and was caught by
    `type_text`, purely because the typing path took more round trips before
    it read its verdict. A cloak check whose answer depends on how many round
    trips a tool happens to make is not a check, so the arming probe now
    yields the same distance on both paths and both refuse."""
    async def go():
        session, page = await _open(battery_site, "type_scope.html")
        live = session.page(page).page
        typing = await _verdict(lambda: lite.type_text(
            page=page, text="4111 1111 1111 1111",
            location={"css": "#real"}))
        assert typing == "refused_cloak", typing
        assert await live.evaluate(
            "() => document.getElementById('real').value") == ""

        session2, page2 = await _open(battery_site, "scope_one-microtask-later.html")
        clicking = await _verdict(lambda: lite.click(
            page=page2, location={"css": "#real"}))
        assert clicking == typing, (clicking, typing)
    run(go())


# ------------------------------------------------- BATTERY 4: THE CLEAR SIDE


@pytest.mark.parametrize("clear_class", sorted(CLEAR_SIDE_CLASSES))
def test_the_clear_side_battery(battery_site, clear_class):
    """SEVEN ORDINARY CONSTRUCTIONS THAT MUST STAY ACTABLE, permanently.

    Each row declares an opaque box over the control and paints nothing there,
    which is the case wave 5's clear arm had no row for: all five of its rows
    varied the geometry of an overlay that really does paint. A cloak check
    that strips working interfaces off ordinary pages fails in the direction
    DESIGN says it may not fail in, and it fails TOTALLY -- one decorative
    overlay and no acting tool works anywhere beneath it."""
    async def go():
        session, page = await _open(battery_site, f"clear_{clear_class}.html")
        live = session.page(page).page
        verdict = await _verdict(lambda: lite.click(
            page=page, location={"css": "#real"}))
        assert verdict == "ran", f"{clear_class}: {verdict}"
        assert await live.evaluate("() => window.__clicked") \
            == "REAL-transfer-9912"
    run(go())


def test_the_clear_side_is_settled_by_pixels_and_not_by_a_technique_list():
    """The battery's completeness check, and it names the class rather than
    the members. Every row above is one of three ways a DECLARATION diverges
    from a PIXEL, and the answer to all three is the same: ask the compositor.
    A new member that fits none of them is a new class and wants its own
    reasoning; a new member that fits one of them needs no code at all, which
    is the property this wave was buying."""
    rect_is_not_paint = {"clip-path", "transparent-mask", "scrolled-overflow"}
    tag_is_not_content = {"decorative-svg", "undrawn-canvas",
                          "transparent-spacer-img"}
    compositing = {"mix-blend-mode"}
    assert rect_is_not_paint | tag_is_not_content | compositing \
        == set(CLEAR_SIDE_CLASSES)

    from kitchensink4web.ops import act
    assert "screenshot" in inspect.getsource(act._pixel_confirms_occlusion), (
        "the clear side is held by the pixel arbiter; if the arbiter stops "
        "taking screenshots these rows are passing for another reason")


def test_the_arbiter_only_second_guesses_occlusion():
    """The boundary, pinned. Every other cloak technique is a property of the
    element ITSELF -- its own opacity, its own filter, its own colour against
    its own background -- and the style already is the answer. `occluded` is
    the one verdict that is a claim about OTHER boxes, so it is the one that
    gets a second opinion. Sending the rest through a screenshot would buy
    nothing and cost every acting call a render."""
    import asyncio as _asyncio

    from kitchensink4web.ops import act

    async def go():
        for reason in sorted(act._CLOAK_WHY):
            if reason == "occluded":
                continue
            kept = await act._arbitrate(None, None, {"reason": reason,
                                                     "why": "x"})
            assert kept is not None, reason
        assert await act._arbitrate(None, None, None) is None

    _asyncio.run(go())


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
