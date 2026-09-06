"""Live Cloudflare challenges the classifier used to score as no wall.

The 2026-09-06 design spike measured six Cloudflare-fronted sites across five
lanes and found two shapes that answered `wall: null` while plainly being
walls:

- openai.com: HTTP 403, `cf-mitigated: challenge`, empty title, empty body.
  The 403 branch required "captcha" in the body or "blocked" in the title,
  and a challenge that has not painted yet has neither.
- g2.com: HTTP 403 from a Cloudflare edge, empty body, no challenge text,
  refused identically on all five lanes.

Both left the agent retrying against a wall it cannot pass, which is the
precise failure DESIGN 5.8 names as the reason this product exists. The first
is now caught by the `cf-mitigated` response header and the second by the
403-from-an-edge-with-an-empty-body shape.

EVERY FIXTURE HERE IS A LOCAL SERVER REPLAYING A RECORDED SHAPE. No test in
this file touches a real protected site: hammering somebody's bot wall to
watch it say no is both rude and unreliable, and the shapes are what matter.
The recorded status codes, header names, and header values come from the
spike's `probe*_result.json`.

The false-positive tests are not padding. This classifier's failure mode is
symmetric: a miss burns the agent's turns, and a false hit costs the user a
page they could have read. The ordinary-Cloudflare-page and application-403
cases below are the ones that would break first if a matcher grew careless.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import BlockedBySite
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets, readonly, walls

pytestmark = pytest.mark.browser


class _EdgeHandler(http.server.BaseHTTPRequestHandler):
    """Replays recorded bot-wall response shapes, byte-for-byte in the parts
    the classifier reads: status, headers, title, body."""

    def log_message(self, *a):
        pass

    def _send(self, code, body, extra=(), ctype="text/html"):
        data = body.encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # --- the recorded misses -------------------------------------
        if self.path == "/cf-challenge-unpainted":
            # openai.com, spike probe run 1: the challenge had not painted.
            self._send(403, "<html><head></head><body></body></html>",
                       extra=[("cf-mitigated", "challenge"),
                              ("server", "cloudflare")])
        elif self.path == "/cf-403-empty":
            # g2.com: a Cloudflare edge 403 with nothing rendered at all.
            self._send(403, "<html><head><title>g2.com</title></head>"
                            "<body></body></html>",
                       extra=[("server", "cloudflare")])
        elif self.path == "/cf-challenge-painted":
            # The same challenge one second later, once it has painted. It
            # was already caught by the title marker; it must stay caught.
            self._send(403, "<html><head><title>Just a moment...</title>"
                            "</head><body>Checking your browser</body></html>",
                       extra=[("cf-mitigated", "challenge"),
                              ("server", "cloudflare")])
        elif self.path == "/cf-security-verification":
            # The interstitial wording added to _WALL_MARKERS, served with
            # NO telltale header so the body marker is what has to catch it.
            self._send(200, "<html><head><title>Loading</title></head><body>"
                            "<p>example.com needs to review the security of "
                            "your connection before performing security "
                            "verification.</p></body></html>")
        # --- the shapes that must NOT be called walls -----------------
        elif self.path == "/cf-ordinary":
            # An ordinary page behind Cloudflare. `server: cloudflare` rides
            # on every response the vendor proxies, so if edge identity ever
            # became a wall signal on its own, this is what would break.
            self._send(200, "<html><head><title>A normal page</title></head>"
                            "<body><h1>Real content</h1></body></html>",
                       extra=[("server", "cloudflare")])
        elif self.path == "/app-403":
            # The application's own 403, behind Cloudflare, explaining
            # itself. A refusal that speaks is not an edge refusal.
            self._send(403, "<html><head><title>Forbidden</title></head>"
                            "<body><h1>You do not have permission to view "
                            "this project.</h1></body></html>",
                       extra=[("server", "cloudflare")])
        elif self.path == "/app-403-no-edge":
            # A bare application 403 with no vendor at all: empty body, but
            # nothing identifies an edge, so it stays unclassified.
            self._send(403, "<html><head></head><body></body></html>")
        # --- sibling vendors, from live captures 2026-09-06 -----------
        elif self.path == "/akamai-denied":
            # Captured from akamai.com itself. The body is HTML-entity-
            # encoded in the source; innerText decodes it, which is what the
            # classifier reads.
            self._send(403,
                       "<html><head><title>Access Denied</title></head><body>"
                       "<h1>Access Denied</h1><p>You don't have permission to "
                       "access \"http&#58;&#47;&#47;www&#46;akamai&#46;com&#47;\" "
                       "on this server.<p>Reference&#32;&#35;18&#46;67023517"
                       "&#46;1788677576&#46;393f8f0</p></body></html>",
                       extra=[("server", "AkamaiGHost")])
        elif self.path == "/datadome-block":
            # leboncoin.fr, verbatim shape: the title is the CUSTOMER's
            # hostname, so title matching is useless here. The real signals
            # are the x-dd-b header and the script contents.
            self._send(403,
                       "<html><head><title>leboncoin.fr</title></head>"
                       "<body style='margin:0'><p id='cmsg'>Please enable JS "
                       "and disable any ad blocker</p>"
                       "<script>var dd={'rt':'i','cid':'AHrlqAAAAAMATJl2',"
                       "'host':'geo.captcha-delivery.com'}</script>"
                       "</body></html>",
                       extra=[("x-dd-b", "3"),
                              ("x-datadome", "protected"),
                              ("x-datadome-cid", "AHrlqAAAAAMATJl2")])
        elif self.path == "/datadome-scripts-only":
            # The same block with the visible text stripped, so ONLY the
            # script-embedded signature can catch it. This is the case that
            # proves the HTML-source path works: innerText is empty here.
            self._send(403,
                       "<html><head><title>shop.example</title></head><body>"
                       "<script>var dd={'rt':'i','host':"
                       "'geo.captcha-delivery.com'}</script></body></html>")
        elif self.path == "/human-block":
            self._send(403,
                       "<html><head><title>Access to this page has been "
                       "denied</title></head><body>"
                       "<h1>Before we continue...</h1>"
                       "<p>Press &amp; Hold to confirm you are a human "
                       "(and not a bot).</p>"
                       "<p>Reference ID 95a00f66-a9c0-11f1-a932-eea9ac4e2086"
                       "</p><div id='px-captcha'></div>"
                       "<script>/* PerimeterX assignments */ "
                       "window._pxAppId='PXAbc123';</script>"
                       "</body></html>",
                       extra=[("x-px-blocked", "1")])
        elif self.path == "/imperva-block":
            self._send(403,
                       "<html><head><title>example.com</title></head><body>"
                       "Request unsuccessful. Incapsula incident ID: "
                       "1360000730081493218-3309035269316929</body></html>",
                       extra=[("x-cdn", "Imperva"), ("x-iinfo", "9-12345-0")])
        # --- vendor edges serving ORDINARY pages ----------------------
        elif self.path == "/akamai-ordinary":
            self._send(200, "<html><head><title>A normal page</title></head>"
                            "<body><h1>Real content</h1></body></html>",
                       extra=[("server", "AkamaiGHost"),
                              ("akamai-grn", "0.abc"),
                              ("set-cookie", "_abck=ABC~-1~; Path=/")])
        elif self.path == "/datadome-ordinary":
            self._send(200, "<html><head><title>A normal page</title></head>"
                            "<body><h1>Real content</h1></body></html>",
                       extra=[("x-datadome", "protected"),
                              ("set-cookie", "datadome=xyz; Path=/")])
        elif self.path == "/imperva-ordinary":
            self._send(200, "<html><head><title>A normal page</title></head>"
                            "<body><h1>Real content</h1></body></html>",
                       extra=[("x-cdn", "Imperva"), ("x-iinfo", "9-12345-0"),
                              ("set-cookie", "incap_ses_1=abc; Path=/")])
        else:
            self._send(200, "<html><head><title>ok</title></head>"
                            "<body>ok</body></html>")


@pytest.fixture(scope="module")
def edge_site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _EdgeHandler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    readonly.apply(False)
    yield
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _page():
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    return session.focused


def _navigate(site, path):
    async def go():
        return await lite.navigate(page=await _page(), url=f"{site}{path}")
    return run(go())


# ------------------------------------------------------- the recorded misses


def test_cf_mitigated_header_is_a_wall_before_the_challenge_paints(edge_site):
    """THE BUG. 403 + cf-mitigated + empty title + empty body scored null."""
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/cf-challenge-unpainted")
    message = str(caught.value)
    assert "cf-mitigated" in message, (
        "the refusal must name the evidence it acted on, so a user can tell "
        f"this from a guess. Got: {message}")


def test_cloudflare_403_with_an_empty_body_is_a_wall(edge_site):
    """The g2.com shape: an edge 403 that renders nothing."""
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/cf-403-empty")
    assert "Cloudflare" in str(caught.value)


def test_a_painted_challenge_is_still_caught(edge_site):
    """The header path must not have displaced the title/body path."""
    with pytest.raises(BlockedBySite):
        _navigate(edge_site, "/cf-challenge-painted")


def test_security_verification_wording_is_a_wall(edge_site):
    """The marker added from the observed interstitial text, caught with no
    header help at all."""
    with pytest.raises(BlockedBySite):
        _navigate(edge_site, "/cf-security-verification")


def test_the_refusal_still_steers_to_another_lane(edge_site):
    """Lane steering is the honest alternative to defeating the wall, and it
    is what makes the refusal actionable rather than merely correct."""
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/cf-challenge-unpainted")
    message = str(caught.value)
    assert "firefox" in message.lower()
    assert "handoff" in message


# --------------------------------------------------- the false-positive wall


def test_an_ordinary_cloudflare_page_is_not_a_wall(edge_site):
    """`server: cloudflare` is on every response the vendor proxies. If this
    test ever fails, a matcher has started refusing a fifth of the web."""
    result = _navigate(edge_site, "/cf-ordinary")
    assert result["verdict"]["wall"] is None
    assert result["status"] == 200


def test_an_application_403_that_explains_itself_is_not_an_edge_wall(edge_site):
    """A 403 with real content is the application answering, not the edge
    refusing, and the agent should read it rather than be told to try
    Firefox."""
    async def go():
        page = await _page()
        try:
            await lite.navigate(page=page, url=f"{edge_site}/app-403")
        except BlockedBySite as exc:      # pragma: no cover - the failure
            pytest.fail(f"an explained application 403 was called a wall: {exc}")
    run(go())


def test_a_bare_403_with_no_edge_named_is_not_a_wall(edge_site):
    """Empty body alone is not enough. Without a named edge there is nothing
    to attribute the refusal to, and guessing is what produces false
    refusals."""
    async def go():
        page = await _page()
        try:
            await lite.navigate(page=page, url=f"{edge_site}/app-403-no-edge")
        except BlockedBySite as exc:      # pragma: no cover - the failure
            pytest.fail(f"a bare 403 was called a wall: {exc}")
    run(go())


# ------------------------------------------------------ the sibling vendors


def test_akamai_access_denied_is_a_wall(edge_site):
    """403 + "Access Denied" title + the permission phrase. The combination
    is required: "Access Denied" alone is far too common to fire on."""
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/akamai-denied")
    assert "Akamai" in str(caught.value)


def test_akamai_reference_number_is_surfaced(edge_site):
    """The reference is entity-encoded in the source and decoded in
    innerText. It is what a site owner asks for, so the refusal carries it."""
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/akamai-denied")
    assert "18.67023517.1788677576.393f8f0" in str(caught.value)


def test_datadome_block_is_a_wall(edge_site):
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/datadome-block")
    assert "DataDome" in str(caught.value)


def test_datadome_is_caught_from_scripts_alone(edge_site):
    """The visible text is empty and there is no telltale header, so only the
    HTML-source path can catch this. innerText does not expose script
    contents, which is exactly why that path exists."""
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/datadome-scripts-only")
    assert "DataDome" in str(caught.value)


def test_human_block_is_a_wall(edge_site):
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/human-block")
    assert "HUMAN" in str(caught.value)


def test_imperva_block_is_a_wall(edge_site):
    with pytest.raises(BlockedBySite) as caught:
        _navigate(edge_site, "/imperva-block")
    message = str(caught.value)
    assert "Imperva" in message
    assert "1360000730081493218-3309035269316929" in message


# ------------------------------- the vendors serving ordinary pages
# Each of these carries the vendor headers and cookies that scraper folklore
# treats as bot-wall signals, on a perfectly normal 200. The research behind
# policy/walls.py confirmed every one of them on live non-blocked traffic.
# If any of these starts failing, a matcher has been promoted a tier it did
# not earn and users are losing pages they could have read.


@pytest.mark.parametrize("path", ["/akamai-ordinary", "/datadome-ordinary",
                                  "/imperva-ordinary", "/cf-ordinary"])
def test_a_vendor_edge_serving_a_normal_page_is_not_a_wall(edge_site, path):
    result = _navigate(edge_site, path)
    assert result["verdict"]["wall"] is None, (
        f"{path} is an ordinary 200 behind a bot-mitigation vendor and must "
        f"not be refused. Verdict: {result['verdict']}")
    assert result["status"] == 200


# ------------------------------------------------------------- unit coverage


def test_header_classifier_is_case_insensitive():
    """Header names and values arrive in whatever case the origin chose."""
    assert lite._header_wall({"CF-Mitigated": "CHALLENGE"}) is not None
    assert lite._header_wall({"cf-mitigated": "challenge"}) is not None


def test_header_classifier_ignores_unrelated_headers():
    assert lite._header_wall({"server": "cloudflare"}) is None
    assert lite._header_wall({"content-type": "text/html"}) is None
    assert lite._header_wall({}) is None
    assert lite._header_wall(None) is None


def test_edge_vendor_identifies_without_accusing():
    """Naming the edge is not the same as calling the response a block."""
    assert lite._edge_vendor({"server": "cloudflare"}) == "Cloudflare"
    assert lite._edge_vendor({"server": "nginx"}) is None
    assert lite._edge_vendor(None) is None


def test_every_wall_header_carries_its_evidence_string():
    """A wall verdict with no evidence is a verdict a user cannot check."""
    for name, _needle, vendor, evidence in lite._WALL_HEADERS:
        assert name == name.lower(), f"{name} must be lowercase to match"
        assert vendor, f"{name} must name the vendor it implicates"
        assert len(evidence) > 30, f"{name} needs a real explanation"


# ------------------------------------------------- the tier contract itself
# policy/walls.py sorts signals into BLOCK-ONLY (fires alone), CORROBORATING
# (needs a refusing status), and NEVER (identifies the vendor, never
# evidence). These tests defend the boundary between the first and the last,
# which is where a careless addition would do real damage.


def test_no_edge_header_is_also_a_block_header():
    """The two tables must stay disjoint. A header that identifies a vendor
    AND is treated as a block would refuse every page behind that vendor."""
    block = {name for name, _, _, _ in walls.BLOCK_HEADERS}
    edge = {name for name, _, _ in walls.EDGE_HEADERS}
    overlap = block & edge
    assert not overlap, (
        f"{overlap} appear in both tables. A header cannot be both 'this "
        f"vendor served the response' and 'this vendor blocked it'.")


@pytest.mark.parametrize("headers", [
    {"server": "cloudflare"}, {"cf-ray": "a36b905f3c593067-ICN"},
    {"server": "AkamaiGHost"}, {"akamai-grn": "0.abc"},
    {"x-datadome": "protected"}, {"x-cdn": "Imperva"},
    {"x-iinfo": "9-12345-0"},
])
def test_present_always_headers_never_signal_a_block(headers):
    """Every one of these was confirmed on live NON-blocked traffic."""
    assert walls.header_block(headers) is None, (
        f"{headers} rides on ordinary responses and must never be read as a "
        f"block on its own.")
    assert walls.edge_vendor(headers) is not None, (
        f"{headers} should still identify its vendor.")


def test_block_headers_fire_on_their_own():
    for name, _needle, vendor, _evidence in walls.BLOCK_HEADERS:
        hit = walls.header_block({name: "1"})
        assert hit is not None, f"{name} is BLOCK-ONLY and must fire alone"
        assert hit[0] == vendor


def test_datadome_matcher_is_not_pinned_to_the_geo_subdomain():
    """DataDome moved customers to *.captcha-delivery.com in Feb 2026, so a
    matcher pinned to geo. would silently stop firing as regions roll out."""
    for needle, _vendor, _evidence in walls.BLOCK_SOURCE:
        assert not needle.startswith("geo."), (
            f"{needle!r} is pinned to a subdomain that is being migrated "
            f"away from")
    assert walls.source_block(
        "<script>var x='https://ct.captcha-delivery.com/i.js'</script>")


def test_akamai_access_denied_alone_is_not_enough():
    """The title phrase is generic. Without the status and the body phrase it
    must not classify."""
    assert walls.text_block("access denied", "", 403) is None
    assert walls.text_block("access denied", "", 200) is None
    assert walls.text_block(
        "access denied", "you don't have permission to access", 200) is None
    assert walls.text_block(
        "access denied", "you don't have permission to access", 403)


def test_reference_ids_are_extracted_but_never_decide_anything():
    found = walls.reference_ids(
        {"cf-ray": "a36b905f3c593067-ICN"}, "", "")
    assert found["Cloudflare Ray ID"] == "a36b905f3c593067-icn"
    assert walls.reference_ids({}, "", "") == {}
