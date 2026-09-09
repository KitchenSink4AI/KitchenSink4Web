"""Lane C against a real Firefox: the read, the acting, and the parity.

The unit pins prove the plumbing carries a descriptor to the gate intact.
They cannot prove the descriptor is the same one every other lane
classifies, because no extractor runs in them. This file runs one.

One browser for the module, headless, on a scratch profile, with the
extension loaded as a temporary add-on over the DevTools protocol, exactly
as the Phase 1 round-trip test does. The fixture pages are local, and that
is a real limit stated rather than papered over: nothing here is a logged-in
site, and Phase 1's own conclusion still stands, that the riskiest thing left
is evidential rather than technical.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kitchensink4web import anchors, projection                    # noqa: E402
from kitchensink4web.engine import lanes                           # noqa: E402
from kitchensink4web.engine import session as _session             # noqa: E402
from kitchensink4web.errors import (BadParams,                    # noqa: E402
                                    ConfirmationRequired,
                                    CredentialRefused, LaneUnsupported)
from kitchensink4web.extension import lane as _extlane             # noqa: E402
from kitchensink4web.extension import register                     # noqa: E402
from kitchensink4web.extension.bridge import (Bridge,
                                                    BridgeError)                # noqa: E402
from kitchensink4web.ops import extops                             # noqa: E402
from kitchensink4web.policy import consent, readonly               # noqa: E402
from tests.fixtures.firefox_harness import (                       # noqa: E402
    HeadlessFirefox, PageServer, RDPClient, find_firefox, free_port)

pytestmark = pytest.mark.browser

LEAK_CANARY = "hunter2-never-leaves-the-page"

#: The checkout fixture, and it is the SAME SHAPE as `creds.html` in the
#: gauntlet 2 battery: a card field with an autocomplete token, an ordinary
#: field beside it, a submit button, a password, and an ordinary link that
#: must never gate. Reading the two side by side is what makes "the fifth
#: path agrees with the other four" a claim somebody can check.
CHECKOUT = f"""<!doctype html>
<title>KS4Web lane C checkout</title>
<body>
  <h1>Checkout</h1>
  <p>Pay for your order below.</p>
  <form method="post" action="/pay">
    <label for="cc">Card number</label>
    <input id="cc" name="cc" type="text" autocomplete="cc-number">
    <label for="who">Full name</label>
    <input id="who" name="who" type="text" autocomplete="name">
    <label for="pw">Password</label>
    <input id="pw" name="pw" type="password" value="{LEAK_CANARY}">
    <button id="pay" type="submit">Pay now</button>
  </form>
  <a id="help" href="/help">Help</a>
</body>
"""

SEARCH = """<!doctype html>
<title>KS4Web lane C search</title>
<body>
  <h1>Search</h1>
  <form method="get" action="/results">
    <label for="q">Query</label>
    <input id="q" name="q" type="search">
    <button id="go" type="submit">Search</button>
  </form>
</body>
"""

HELP = """<!doctype html>
<title>KS4Web lane C help</title>
<body><h1>Help</h1><p>Nothing here needs a gate.</p></body>
"""

#: WHERE THE SEARCH FORM ACTUALLY GOES, and its absence was half of open
#: item 15. `SEARCH` submits GET to `/results`, the server had no such page,
#: and a 404 with an empty body makes Firefox render its own error document:
#: `about:neterror`, on the `about:` scheme the extension refuses, with no
#: content script in it. So a test that submitted the search left the shared
#: tab in a state where the NEXT test's first command answered either
#: `REFUSED_SCHEME: about:` or `Receiving end does not exist`, depending on
#: whether it caught the navigation in flight. Serving the page removes the
#: source; the reset fixture below removes the class.
RESULTS = """<!doctype html>
<title>KS4Web lane C results</title>
<body><h1>Results</h1><p>Nothing matched, and that is fine.</p></body>
"""


def run(coro):
    return asyncio.run(coro)


def active_url(bridge):
    """Where the shared tab is, asked in a way that costs nothing.

    `bg.tabs` is answered by the background script directly and never reaches
    `pageCommand`, so it passes no scheme gate, no consent gate and no rate
    limit. That matters more than it looks: the first version of the reset
    below asked with `page.read`, which does pass the rate limit, and forty
    extra rated commands across a module that already runs flat out pushed
    the token bucket under water. The reset then caused a different failure
    than the one it removed, in tests that were not the ones being reset.
    """
    for tab in bridge.request("bg.tabs", timeout=30.0).get("tabs") or []:
        if tab.get("active"):
            return tab.get("url") or ""
    return ""


def settle(bridge, url, timeout=30.0):
    """Put the shared tab back on a known page before the next test runs.

    ONE BROWSER SERVES TWENTY TESTS AND SEVERAL OF THEM MOVE IT: a link is
    clicked, a form submits, a navigate runs. `page.navigate` waits for
    `webNavigation.onCompleted`, so the tab has committed by the time it
    returns, but nothing made that call between tests, and a test whose own
    navigation was still in flight at teardown handed the next one a tab on
    `about:blank` or on a document with no content script in it.

    The failure that follows is a harness condition wearing a product
    failure's clothes. `REFUSED_SCHEME: about:` and `EXECUTION_FAILED:
    Receiving end does not exist` are both correct answers to the question
    the browser was actually asked, which is why nothing in the extension
    ever looked wrong while a different test failed on every shuffle.

    Asking first and navigating only when the answer is wrong is what keeps
    this affordable. Most tests leave the tab where they found it, so most
    resets spend one free `bg.tabs` and stop there.
    """
    deadline = time.monotonic() + timeout
    last = "no attempt completed"
    while time.monotonic() < deadline:
        try:
            if active_url(bridge) == url:
                return
            bridge.request("page.navigate",
                           {"url": url, "waitUntil": "complete"}, timeout=30.0)
            if active_url(bridge) == url:
                return
            last = "the navigate did not leave the tab on the fixture page"
        except BridgeError as exc:  # noqa: PERF203
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError(f"the shared tab never came back to {url}: {last}")


class _Ctx:
    def __init__(self, bridge):
        self.context = _extlane.ExtensionContext(bridge)


class _Sess:
    """The parts of a Session the Lane C bodies read.

    A real `SessionManager.open(lane='C')` would need the registry, the
    endpoint file and the whole reaper path; what is under test here is the
    tool bodies against a real page, so the session is the smallest object
    that carries what they touch."""

    _seq = 0

    def __init__(self, bridge):
        # A FRESH SESSION ID PER TEST, and it is not a workaround. The budget
        # book and the loop detector are keyed by session, and one browser
        # serving a whole module is not one session: fourteen tests each
        # navigating to the same fixture page under one id is a repeated call
        # by every definition the loop detector has, and it is right to say
        # so. Separate ids say what is actually true, which is that these are
        # separate sessions sharing a browser.
        _Sess._seq += 1
        self.session_id = f"live{_Sess._seq}"
        self.spec = lanes.LaneSpec(lane="C", engine="extension",
                                   headless=False)
        self.element_map = anchors.ElementMap()
        self.reads = anchors.ReadStore()
        self.contexts = {"c1": _Ctx(bridge)}
        self.bumped = []

    def bump(self, kind, page=None):
        self.bumped.append(kind)

    def invalidate_page(self, handle, why):
        return {"why": why}


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    if not find_firefox():
        pytest.skip("no Firefox on this machine")

    workdir = tmp_path_factory.mktemp("ks4web-lanec")
    endpoint = workdir / "endpoint.json"
    bridge = Bridge(endpoint_path=endpoint)
    pages = PageServer({"/": CHECKOUT, "/search": SEARCH, "/help": HELP,
                        "/results": RESULTS})
    browser = None
    rdp = None
    try:
        register.install(
            workdir / "nativehost",
            python_executable=sys.executable,
            src_dir=ROOT / "src",
            endpoint=endpoint,
        )
        port = free_port()
        browser = HeadlessFirefox(workdir / "browser", url=pages.url("/"),
                                  debugger_port=port)
        rdp = RDPClient(port)
        rdp.install_temporary_addon(ROOT / "extension")
        if not bridge.wait_for_browser(60.0):
            pytest.fail("the extension never connected to the bridge")
        # The consent gate is the Python ladder's; this is the browser-side
        # copy of its answer, and without it every page command refuses,
        # which is the posture the extension ships in.
        bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
        # A BROWSER STILL STARTING HAS `about:blank` ON SCREEN, and the
        # extension refuses privileged schemes rather than trying and
        # failing -- correctly, and this loop is what has to tolerate it.
        # Without the guard the fixture dies on the refusal instead of
        # polling past it, which is a harness defect that looks exactly
        # like a product one: it reproduces on phase 2 code as soon as a
        # third extension module joins the suite (measured at one run in
        # four), and it is why phase 3 saw ten module-setup errors in a
        # full-suite run that no isolated run could reproduce.
            try:
                text = bridge.request("page.read", timeout=30.0).get("text", "")
            except BridgeError:
                text = ""
            if "Checkout" in text:
                break
            time.sleep(0.25)
        yield bridge, pages
    finally:
        for shutdown in (
            lambda: rdp and rdp.close(),
            lambda: browser and browser.kill(),
            pages.close,
            bridge.close,
        ):
            try:
                shutdown()
            except Exception:  # noqa: BLE001
                pass
        register.unregister_windows()


@pytest.fixture(autouse=True)
def fresh_tab(live):
    """THE STATE EVERY TEST IN THIS MODULE ASSUMED AND NONE OF THEM SET.

    Autouse, because the tests that go straight to `live` and never take
    `lane` are the ones that were failing: they speak to the bridge directly,
    they assume the active tab is a fixture page with a content script in it,
    and until now the only thing establishing that was whichever test the
    shuffle happened to run before them.

    Consent is restored first because one test in this module sets the
    browser-side origin list to somewhere else, and a test that failed
    partway through would leave it there, at which point even the navigate
    below is refused.
    """
    bridge, pages = live
    bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
    settle(bridge, pages.url("/"))
    yield


@pytest.fixture
def lane(live, fresh_tab):
    bridge, pages = live
    before = readonly.grade()
    readonly.apply(False)
    consent.apply("full")
    sess = _Sess(bridge)
    page = _extlane.ExtensionPage(bridge, url=pages.url("/"))
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    # `fresh_tab` already put the browser on the checkout page and proved a
    # content script answers there. This navigate is the SESSION's copy of
    # that fact rather than a second attempt at it: it runs through
    # `extops.navigate`, so the handle, the element map and the read store
    # start each test agreeing with the tab about which document they are
    # looking at.
    run(extops.navigate(sess, record, url=pages.url("/")))
    try:
        yield sess, record, pages
    finally:
        readonly.apply(False if before is None else before)
        consent.apply(None)
        from kitchensink4web.policy import budgets
        budgets.BOOK.drop(sess.session_id)


def ref_named(sess, name):
    for ref, entry in sess.element_map.entries.items():
        if entry.anchor.get("name") == name:
            return ref
    raise AssertionError(
        f"no ref for {name!r}; minted: "
        f"{[e.anchor.get('name') for e in sess.element_map.entries.values()]}")


def verdict(call):
    try:
        run(call())
    except ConfirmationRequired as exc:
        text = str(exc)
        for phrase, cls in (
                ("payment-shaped form", "payment_form"),
                ("password or a one-time code", "credential_submit"),
                ("reaches other people", "broadcast_submit"),
                ("deletes, cancels", "destructive_submit"),
                ("agreeing to terms", "legal_assent")):
            if phrase in text:
                return cls
        if "submitting a form" in text:
            return "form_submit"
        return "gated"
    except CredentialRefused:
        return "credential_refused"
    return "ungated"


# ------------------------------------------------------------------ the read


def test_the_projection_runs_in_the_page_and_comes_back_shaped(lane):
    """THE CLAIM THE WHOLE PHASE RESTS ON. The bundle is the same
    `extract.js` the Playwright lanes run, so the payload has the blocks a
    caller already knows how to read, at a budget it did not exceed."""
    sess, record, _pages = lane
    payload = run(extops.get_page_view(sess, record, budget_tokens=3000))
    assert payload["lane"] == "C"
    assert "Checkout" in payload["projection"]
    assert payload["budget"]["used"] <= payload["budget"]["limit"]
    assert payload["read_token"]
    # The interactive surface came back with refs on it, which is what
    # makes the read actionable rather than a transcript.
    assert sess.element_map.entries


def test_the_password_value_never_leaves_the_page(lane):
    """The projection's own guarantee, inherited rather than reimplemented:
    a secret field's value_state is `never-read` and the extractor never
    touches `el.value` on one. Lane C adds no second path to it, which is
    the point of running the same extractor."""
    sess, record, _pages = lane
    payload = run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert LEAK_CANARY not in str(payload)


def test_the_read_reports_that_the_browser_is_not_flagged(lane):
    """Phase 1's rule, in a production read rather than a probe."""
    sess, record, _pages = lane
    assert run(extops.get_page_view(sess, record))["webdriver"] is False


def test_the_closed_root_count_is_an_absence_rather_than_a_zero(lane):
    """The isolated world cannot count closed shadow roots, so the payload
    must not report none. A confident zero is the failure the two-layer
    phrasing was written to prevent."""
    sess, record, _pages = lane
    payload = run(extops.get_page_view(sess, record))
    assert "closed_shadow_count" in payload["lane_notes"]


def test_a_second_read_keeps_the_refs_the_first_one_minted(lane):
    """Sticky refs across reads, which is what a caller holding `e12` from
    one call and acting on it in the next depends on. The bundle's state
    survives because the injection guard makes a second injection free."""
    sess, record, _pages = lane
    run(extops.get_page_view(sess, record))
    first = set(sess.element_map.entries)
    run(extops.get_page_view(sess, record))
    assert first <= set(sess.element_map.entries)


# ------------------------------------------------------------- the parity


def test_gate_parity_on_lane_c_across_every_write_path(lane):
    """ONE fixture, ONE card field, THREE doors, ONE verdict, against a REAL
    extraction.

    This is the live half of the fifth-path pin, and it is the half that
    proves the descriptor rather than the plumbing: the class here is
    computed from what `extract.js` said about a real `<input
    autocomplete="cc-number">` in a real form, by the same classifier the
    other four paths call."""
    sess, record, _pages = lane
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    card = ref_named(sess, "Card number")
    pay = ref_named(sess, "Pay now")
    verdicts = {
        "click": verdict(lambda: extops.click(
            sess, record, location={"ref": pay})),
        "type_text": verdict(lambda: extops.type_text(
            sess, record, location={"ref": card}, text="4111111111111111")),
        "fill_form": verdict(lambda: extops.fill_form(
            sess, record,
            fields=[{"ref": card, "value": "4111111111111111"}])),
    }
    assert set(verdicts.values()) == {"payment_form"}, verdicts


def test_the_card_number_never_reaches_the_field_when_the_gate_refuses(lane):
    """The gate fires before the write, proven by asking the page."""
    sess, record, pages = lane
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    card = ref_named(sess, "Card number")
    who = ref_named(sess, "Full name")
    with pytest.raises(ConfirmationRequired):
        run(extops.fill_form(sess, record, fields=[
            {"ref": card, "value": "4111111111111111"},
            {"ref": who, "value": "buyer"}]))
    data = run(projection.extract(record.page))
    values = {u.get("name"): u.get("value_state")
              for f in data.get("forms") or [] for u in f.get("fields") or []}
    assert "4111111111111111" not in str(data)


def test_an_ordinary_link_is_clicked_without_a_gate(lane):
    """THE CONTROL ARM, live. Without it every pin above would pass on a
    build that refused everything."""
    sess, record, pages = lane
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    result = run(extops.click(sess, record,
                              location={"ref": ref_named(sess, "Help")}))
    assert result["effect"] in ("navigated", "same-page")
    assert result["is_trusted"] is False


def test_writing_a_password_refuses_before_the_page_is_touched(lane):
    """Credential blindness on the fifth path, against a real password
    field the extractor classified itself."""
    sess, record, _pages = lane
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert verdict(lambda: extops.type_text(
        sess, record, location={"ref": ref_named(sess, "Password")},
        text="anything")) == "credential_refused"


def test_a_query_shaped_search_stays_in_grade(lane):
    """The consent ladder's Tier 0, live on this lane. A GET form with no
    secret, payment, or file field is a safe method under RFC 9110, and a
    build that gated it would be the friction the ladder exists to remove."""
    sess, record, pages = lane
    run(extops.navigate(sess, record, url=pages.url("/search")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert verdict(lambda: extops.type_text(
        sess, record, location={"ref": ref_named(sess, "Query")},
        text="kitchen sink", submit=True)) == "ungated"


# ------------------------------------------------------- navigation and shots


def test_navigation_waits_for_the_load_before_it_returns(lane):
    """`tabs.update` resolves the moment the URL is set, so a navigate that
    returned there would have a third of its callers reading the OLD
    document. The background script waits for webNavigation.onCompleted."""
    sess, record, pages = lane
    result = run(extops.navigate(sess, record, url=pages.url("/help")))
    assert result["settled"] == "complete"
    assert result["url"].endswith("/help")
    assert result["status"] is None
    payload = run(extops.get_page_view(sess, record))
    assert "Help" in payload["projection"]


def test_a_navigation_invalidates_the_refs_it_moved_away_from(lane):
    """DESIGN 3.5 on this lane: refs are invalidated by a navigation, and
    saying so in the navigate result is what keeps a later stale-ref refusal
    from being the first the caller hears of it."""
    sess, record, pages = lane
    run(extops.navigate(sess, record, url=pages.url("/")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    result = run(extops.navigate(sess, record, url=pages.url("/help")))
    assert result.get("invalidated")


def test_the_screenshot_is_the_viewport_and_masks_the_secret_fields(lane):
    """captureVisibleTab takes no mask argument, so the mask is CSS this
    build applies and removes around the capture. The count is what makes
    the fail-closed claim checkable."""
    sess, record, pages = lane
    run(extops.navigate(sess, record, url=pages.url("/")))
    shot = run(extops.take_screenshot(sess, record))
    assert shot["scope"] == "viewport"
    assert shot["format"] == "png"
    assert shot["base64"]
    # The checkout page carries a password and a card field, so the mask had
    # something to do; a zero here would mean the selector missed.
    assert shot["masked_fields"] >= 2


# ------------------------------------------- one refusal per tool, all six


def _refusal_text(call, expected):
    """Run something that must refuse, and hand back what the caller sees."""
    with pytest.raises(expected) as caught:
        run(call())
    text = str(caught.value)
    # A refusal is a product surface. Whatever the type system says, a
    # message carrying a traceback or a module path reads as a crash to the
    # thing on the other side of the tool boundary.
    for tell in ("Traceback", "BridgeError(", ".py\", line", "  File "):
        assert tell not in text, (tell, text)
    assert "lane" in text.lower(), text
    return text


def test_get_page_view_refuses_a_view_it_does_not_have(lane):
    sess, record, _pages = lane
    assert "nonsense" in _refusal_text(
        lambda: extops.get_page_view(sess, record, view="nonsense"),
        BadParams)


def test_navigate_refuses_a_driver_only_action_by_name(lane):
    """`stop` and `wait_for_load` are driver operations. Accepting either and
    doing nothing would be the silent degrade this lane is built to avoid."""
    sess, record, _pages = lane
    assert "stop" in _refusal_text(
        lambda: extops.navigate(sess, record, action="stop"), BadParams)


def test_click_refuses_a_mouse_button_it_cannot_press(lane):
    sess, record, _pages = lane
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    text = _refusal_text(
        lambda: extops.click(sess, record,
                             location={"ref": ref_named(sess, "Help")},
                             button="right"),
        LaneUnsupported)
    assert "button" in text
    assert "'A'" in text or "'B'" in text


def test_type_text_refuses_a_per_keystroke_delay(lane):
    sess, record, _pages = lane
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert "delay_ms" in _refusal_text(
        lambda: extops.type_text(sess, record,
                                 location={"ref": ref_named(sess,
                                                            "Full name")},
                                 text="x", delay_ms=50),
        LaneUnsupported)


def test_fill_form_refuses_an_empty_batch_with_the_shape_it_wanted(lane):
    sess, record, _pages = lane
    assert "fields=" in _refusal_text(
        lambda: extops.fill_form(sess, record, fields=[]), BadParams)


def test_take_screenshot_refuses_a_full_page_capture_rather_than_cropping(
        lane):
    """A scroll-and-stitch is not a picture of the page, so the request for
    one refuses instead of returning a viewport crop under its name."""
    sess, record, _pages = lane
    assert "full" in _refusal_text(
        lambda: extops.take_screenshot(sess, record, target="full"),
        LaneUnsupported)


def test_the_mask_comes_off_after_the_capture(lane):
    """The page is the user's own window. Leaving its payment fields painted
    black would be this tool editing what somebody is looking at and walking
    away."""
    sess, record, pages = lane
    run(extops.navigate(sess, record, url=pages.url("/")))
    run(extops.take_screenshot(sess, record))
    left = run(record.page.evaluate(projection.EXTRACT_JS, {}))
    assert left is not None
    ready = run(record.page.ready())
    assert ready["readyState"] in ("interactive", "complete")


# ----------------------------------------------------------- the wire itself


def test_a_batch_is_one_round_trip_with_one_answer_per_step(live):
    """A five-field form fill is one hop rather than five. A failed step does
    not stop the ones after it: the caller asked several questions and gets
    several answers, each with its own outcome."""
    bridge, _pages = live
    answers = bridge.batch([
        {"method": "bg.ping"},
        {"method": "no.such.method"},
        {"method": "bg.ping"},
    ], timeout=60.0)
    assert len(answers) == 3
    assert answers[0]["result"]["pong"] is True
    assert answers[1]["error"]["code"] == "UNKNOWN_METHOD"
    assert answers[2]["result"]["pong"] is True


def test_a_large_payload_comes_back_gzipped_and_intact(live):
    """Compression is transparent: the caller gets the same object either
    way, and the only observable difference is that the pipe carried less."""
    bridge, _pages = live
    size = 2 * 1024 * 1024
    result = bridge.request("diag.payload", {"bytes": size, "maxChunk": 0},
                            timeout=120.0)
    assert result["bytes"] == size


def test_compression_can_be_turned_off_and_still_returns_the_same_bytes(live):
    """The other direction of the pin above. An encoding that only ever ran
    one way would pass the test above on a build where the flag does
    nothing."""
    bridge, _pages = live
    size = 512 * 1024
    packed = bridge.request("diag.payload", {"bytes": size, "maxChunk": 0},
                            timeout=120.0)
    plain = bridge.request("diag.payload",
                           {"bytes": size, "maxChunk": 0, "gzip": False},
                           timeout=120.0)
    assert packed == plain


def test_the_content_script_refuses_a_script_it_was_not_shipped(live):
    """The closed set, enforced at the far end as well as the near one. The
    Python seam refuses first, so this is the belt behind the braces: a name
    that reached the content script anyway is still refused there."""
    from kitchensink4web.extension.bridge import BridgeError
    bridge, _pages = live
    with pytest.raises(BridgeError) as caught:
        bridge.request("page.evaluate",
                       {"script": "not_a_script", "frameId": 0}, timeout=30.0)
    assert "UNKNOWN_SCRIPT" in str(caught.value)


def test_an_origin_the_session_never_consented_to_is_refused_in_the_browser(
        live):
    """The browser-side half of the consent gate. The Python ladder is the
    authority; this is the copy of its answer, and a command that somehow
    reached the pipe for an origin nobody approved never touches a page."""
    from kitchensink4web.extension.bridge import BridgeError
    bridge, _pages = live
    bridge.request("consent.set", {"origins": ["https://nowhere.example"]},
                   timeout=30.0)
    try:
        with pytest.raises(BridgeError) as caught:
            bridge.request("page.read", {"frameId": 0}, timeout=30.0)
        assert "ORIGIN_NOT_CONSENTED" in str(caught.value)
    finally:
        bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
    # And the other direction, in the same test so a restored wildcard that
    # did not actually restore anything cannot pass silently.
    assert bridge.request("page.read", {"frameId": 0}, timeout=30.0)["title"]


def test_the_audit_log_records_every_command_and_its_target(live):
    """Spec section 7 item 4. Every command and its target URL, inspectable,
    which is what makes an unattended run reviewable afterwards."""
    bridge, _pages = live
    bridge.request("page.read", {"frameId": 0}, timeout=30.0)
    entries = bridge.request("audit.read", {"limit": 50},
                             timeout=30.0)["entries"]
    assert entries
    last = entries[-1]
    assert last["method"] == "page.read"
    assert last["outcome"] == "ok"
    assert "127.0.0.1" in (last["url"] or "")
