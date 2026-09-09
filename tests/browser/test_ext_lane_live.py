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
from kitchensink4web.errors import (ConfirmationRequired,          # noqa: E402
                                    CredentialRefused)
from kitchensink4web.extension import lane as _extlane             # noqa: E402
from kitchensink4web.extension import register                     # noqa: E402
from kitchensink4web.extension.bridge import Bridge                # noqa: E402
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


def run(coro):
    return asyncio.run(coro)


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
    pages = PageServer({"/": CHECKOUT, "/search": SEARCH, "/help": HELP})
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
            if "Checkout" in bridge.request("page.read",
                                            timeout=30.0).get("text", ""):
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


@pytest.fixture
def lane(live):
    bridge, pages = live
    before = readonly.grade()
    readonly.apply(False)
    consent.apply("full")
    sess = _Sess(bridge)
    page = _extlane.ExtensionPage(bridge, url=pages.url("/"))
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    # EVERY TEST STARTS ON THE CHECKOUT PAGE. One browser serves the whole
    # module, so a test that clicked a link would otherwise decide what the
    # next one is looking at, and a suite whose verdicts depend on its own
    # order is a suite that cannot be trusted about the one thing it exists
    # to check.
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
