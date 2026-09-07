"""The half of the taxonomy a raw HTTP response cannot answer.

`tests/unit/test_classify.py` runs the fixture corpus, which was collected
with `curl` and is therefore authoritative for status codes, response headers
and HTML-source signatures, and for nothing else. Three things live only
here:

- **The structural families.** A consent wall is a blocking overlay and an
  age gate is a form in the way, and both are facts about what
  `elementFromPoint` returns rather than about what the server sent. The
  corpus carries no evidence about them in either direction.
- **The field defects.** Reddit's own block page and JSTOR's Akamai Client
  Challenge both came back `ok: true, status: 200, wall: null` in the
  2026-09-08 model runs, on two engines, and both are replayed here by shape.
- **The embedded-viewer ruling.** Whether a read returns the abstract or
  refuses the whole page is a question about a rendered document.

EVERY FIXTURE IS A LOCAL SERVER REPLAYING A RECORDED SHAPE, the same rule
`test_wall_headers.py` states: hammering somebody's live wall to watch it say
no is both rude and unreliable, and the shapes are what matter.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import BlockedBySite, UnsupportedContent
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets, readonly

pytestmark = pytest.mark.browser


_ABSTRACT = (
    "<h2>Abstract</h2><p>" + ("This study examines the question at hand and "
                              "reports what it found. ") * 12 + "</p>")

_PAYWALL_ARTICLE = (
    "<html><head><title>An article behind a barrier</title>"
    "<meta name='citation_doi' content='10.1000/example'>"
    "<meta name='citation_title' content='An article behind a barrier'>"
    "<meta name='citation_journal_title' content='Journal of Examples'>"
    "<script type='application/ld+json'>"
    '{"@type":"ScholarlyArticle","hasPart":{"isAccessibleForFree":false}}'
    "</script></head><body><main>"
    f"{_ABSTRACT}"
    "<div class='paywall'><p>Restricted access</p>"
    "<p>Sign in via your institution</p>"
    "<p>Purchase 24 hour online access to this article</p></div>"
    "</main></body></html>")

_CONSENT_WALL = (
    "<html><head><title>Nachrichten</title>"
    "<script src='https://cdn.privacy-mgmt.com/sourcepoint/messaging.js'>"
    "</script></head><body>"
    "<main><p>" + ("Der Artikel steht hier in voller Laenge. " * 30) +
    "</p></main>"
    "<div id='sp_message_container' style='position:fixed;top:0;left:0;"
    "width:100vw;height:100vh;background:#fff;z-index:99'>"
    "<h2>Wir schaetzen Ihre Privatsphaere</h2>"
    "<button>Alle akzeptieren</button></div>"
    "</body></html>")

_AGE_GATE = (
    "<html><head><title>Distillery</title></head><body>"
    "<main><p>" + ("Our whiskey has been made here since 1866. " * 30) +
    "</p></main>"
    "<div class='age-gate' style='position:fixed;top:0;left:0;width:100vw;"
    "height:100vh;background:#111;color:#fff;z-index:99'>"
    "<h2>You must be of legal drinking age to enter</h2>"
    "<form><select name='birth_year'><option>1990</option></select>"
    "</form></div></body></html>")

#: The cloak, carried into the families where the status gate is unavailable.
#: Every phrase a 200-page family looks for, offscreen, with no structural
#: companion anywhere in the document.
_CLOAKED = (
    "<html><head><title>An ordinary article</title></head><body>"
    "<main><p>" + ("Ordinary readable prose about an ordinary topic. " * 40) +
    "</p></main>"
    "<div style='position:absolute;left:-9999px;top:-9999px'>"
    "sign in via your institution. are you 18 or over? accept all cookies. "
    "subscribe to continue. too many requests. page not found."
    "</div></body></html>")

_EMBEDDED_VIEWER = (
    "<html><head><title>Article record</title>"
    "<meta name='citation_doi' content='10.2307/2539079'>"
    "<meta name='citation_title' content='An article with a viewer'>"
    "</head><body><main>"
    f"{_ABSTRACT}"
    "<object type='application/pdf' data='/paper.pdf' "
    "style='width:100vw;height:80vh'></object>"
    "</main></body></html>")

_BARE_VIEWER = (
    "<html><head><title></title></head><body style='margin:0'>"
    "<embed type='application/pdf' src='/paper.pdf' "
    "style='width:100vw;height:100vh'>"
    "</body></html>")


class _Handler(http.server.BaseHTTPRequestHandler):
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
        path = self.path.split("?")[0]
        # --- the field defects, by shape ------------------------------
        if path == "/akamai-client-challenge":
            # JSTOR, 2026-09-08: HTTP 200, title "Client Challenge", and the
            # body was one line. Both models' runs reported `wall: null`.
            self._send(200,
                       "<html><head><title>Client Challenge</title></head>"
                       "<body>Enter the characters seen in the image below"
                       "</body></html>",
                       extra=[("server", "AkamaiGHost")])
        elif path == "/js-challenge":
            # Reddit, 2026-09-08: HTTP 200, blank title, ZERO characters of
            # readable text, and the only tell was the challenge parameter
            # the site's own redirect put on the URL.
            if "js_challenge" not in self.path:
                self.send_response(302)
                self.send_header(
                    "location", "/js-challenge?js_challenge=1&jsc_token=abc")
                self.end_headers()
                return
            self._send(200, "<html><head></head><body></body></html>")
        elif path == "/ordinary-short":
            # Channel 4's homepage carries 44 characters of visible text and
            # is a perfectly working page. Nothing here may classify.
            self._send(200, "<html><head><title>Home</title></head>"
                            "<body><main>Watch now</main></body></html>")
        # --- the structural families ----------------------------------
        elif path == "/consent-wall":
            self._send(200, _CONSENT_WALL)
        elif path == "/age-gate":
            self._send(200, _AGE_GATE)
        elif path == "/cloaked":
            self._send(200, _CLOAKED)
        # --- the paywall, which must be READ rather than refused ------
        elif path == "/paywalled-article":
            self._send(200, _PAYWALL_ARTICLE)
        elif path == "/ordinary-article":
            self._send(200, "<html><head><title>An article</title></head>"
                            f"<body><main>{_ABSTRACT}</main></body></html>")
        # --- the embedded-viewer ruling -------------------------------
        elif path == "/embedded-viewer":
            self._send(200, _EMBEDDED_VIEWER)
        elif path == "/bare-viewer":
            self._send(200, _BARE_VIEWER)
        elif path == "/paper.pdf":
            self._send(200, "%PDF-1.4 not a real pdf",
                       ctype="application/pdf")
        else:
            self._send(200, "<html><head><title>ok</title></head>"
                            "<body>ok</body></html>")


@pytest.fixture(scope="module")
def site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
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


def run(coro_factory):
    async def main():
        try:
            return await coro_factory()
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _open():
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    return session.focused


def _go(site, path):
    async def main():
        return await lite.navigate(page=await _open(), url=f"{site}{path}")
    return run(main)


def _go_then_view(site, path, **kwargs):
    async def main():
        page = await _open()
        nav = await lite.navigate(page=page, url=f"{site}{path}")
        view = await lite.get_page_view(page=page, **kwargs)
        return nav, view
    return run(main)


def _categories(result) -> set:
    found = (result.get("verdict") or {}).get("classification") or {}
    return {e["category"] for e in found.get("categories") or ()}


# --------------------------------------------------- the two field defects


def test_the_akamai_client_challenge_is_no_longer_a_silent_success(site):
    """JSTOR, and the reason the soft-block rung exists.

    A 200 with a challenge title and one line of text used to come back
    `ok: true, wall: null`, which is worse than a refusal because nothing
    downstream thinks to look at it twice."""
    with pytest.raises(BlockedBySite) as caught:
        _go(site, "/akamai-client-challenge")
    message = str(caught.value)
    assert "Akamai" in message, message
    assert "readable text" in message, (
        f"the refusal must name both halves of the rung it fired on: "
        f"{message}")


def test_a_challenge_parameter_on_the_landed_url_is_a_wall(site):
    """Reddit, whose block page rendered no title and no text at all. The
    only evidence was the parameter the site's own redirect wrote onto the
    URL, which is a server signal rather than a page-controlled one."""
    with pytest.raises(BlockedBySite) as caught:
        _go(site, "/js-challenge")
    assert "js_challenge" in str(caught.value)


def test_a_short_ordinary_page_is_not_a_wall(site):
    """The other side of the same rung, and the corpus correction that makes
    it necessary: a working Channel 4 homepage carries 44 visible characters.
    Length is a necessary condition on the rung, never a signal."""
    result = _go(site, "/ordinary-short")
    assert result["verdict"]["wall"] is None
    assert not _categories(result)


# ------------------------------------------------- the structural families


def test_a_blocking_consent_overlay_classifies_and_does_not_refuse(site):
    """A consent choice is a legal act by a person, so KS4Web names the
    banner and hands it over. It never clicks Accept all, and it never
    withholds the page the banner is sitting on."""
    result = _go(site, "/consent-wall")
    assert result["verdict"]["wall"] is None
    assert "gdpr_consent" in _categories(result)


def test_an_age_gate_classifies_and_does_not_refuse(site):
    result = _go(site, "/age-gate")
    assert result["verdict"]["wall"] is None
    assert "age_gated" in _categories(result)


def test_e4_the_cloak_holds_on_a_200_page(site):
    """Every 200-family phrase at once, in an offscreen div, with no
    structural companion. innerText includes offscreen text, so this is the
    F1 attack carried into the families where the status gate is unavailable
    and something else had to take its place."""
    result = _go(site, "/cloaked")
    assert result["verdict"]["wall"] is None
    assert not _categories(result), (
        "an offscreen div of wall phrases classified a readable page")


# ------------------------------------------------- the paywall is READ


def test_e5_a_paywall_reports_and_the_page_still_loads(site):
    result = _go(site, "/paywalled-article")
    assert result["verdict"]["wall"] is None, (
        "a paywall that raises makes the abstract unreachable through the "
        "tool that exists to read pages")
    assert "paywall_academic" in _categories(result)


def test_e15_a_read_of_a_paywalled_page_returns_the_page(site):
    nav, view = _go_then_view(site, "/paywalled-article")
    assert "Abstract" in view["projection"] or "abstract" in \
        view["projection"].lower()
    assert view["classification"]["category"] == "paywall_academic"
    assert view["classification"]["access_path"]


def test_e2_an_ordinary_article_classifies_to_nothing(site):
    nav, view = _go_then_view(site, "/ordinary-article")
    assert not _categories(nav)
    assert "classification" not in view


# ------------------------------------------- the embedded-viewer ruling


def test_the_embedded_viewer_page_is_read_and_the_document_is_disclosed(site):
    """THE ACCEPTANCE TEST for the author's 2026-09-08 ruling. The page's own
    content comes back, and the document that cannot be read from this tab is
    named with its own URL rather than swallowed."""
    nav, view = _go_then_view(site, "/embedded-viewer")
    assert "Abstract" in view["projection"] or "abstract" in \
        view["projection"].lower()
    handoff = view["document_handoff"]
    assert handoff["documents"][0]["url"].endswith("/paper.pdf")
    assert handoff["documents"][0]["fetchable_by_url"] is True
    assert handoff["readable_from_here"] is False
    assert handoff["citation"]["doi"] == "10.2307/2539079"
    assert handoff["read_from_page"]


def test_a_bare_viewer_wrapper_still_refuses(site):
    """The other half of the ruling, unchanged. A browser's synthesized
    wrapper around a PDF has one `<embed>` and nothing to read, so a read of
    it would return viewer chrome under a payload shape that looks like a
    real read."""
    async def main():
        page = await _open()
        await lite.navigate(page=page, url=f"{site}/bare-viewer")
        with pytest.raises(UnsupportedContent) as caught:
            await lite.get_page_view(page=page)
        return caught.value

    exc = run(main)
    assert "document_handoff" in exc.detail
    assert exc.detail["document_handoff"]["documents"][0]["url"].endswith(
        "/paper.pdf")


def test_navigate_to_a_direct_pdf_url_hands_off_the_document(site):
    """A direct file URL makes Chromium download rather than paint, so the
    navigation stops before there is any page to probe (Desktop High-6). The
    caller has just been told "this is a file, not a page", which is exactly
    the caller who needs the document's facts, so the handoff rides on the
    refusal."""
    from kitchensink4web.errors import ValidationFailed

    async def main():
        page = await _open()
        with pytest.raises(ValidationFailed) as caught:
            await lite.navigate(page=page, url=f"{site}/paper.pdf")
        return caught.value

    exc = run(main)
    handoff = exc.detail["document_handoff"]
    assert handoff["documents"][0]["url"].endswith("/paper.pdf")
    assert handoff["documents"][0]["filename"] == "paper.pdf"
    assert handoff["documents"][0]["fetchable_by_url"] is True


# ---------------------------------------------------------- the cost pins


def test_e16_an_ordinary_read_costs_what_it_costs_today(site):
    """The pin against widening the cheap read gate. `get_page_view` on an
    ordinary 200 page must not gain an evaluate for the taxonomy's benefit:
    the classification it reports was computed at navigation time and is only
    read out of the record."""
    counted = {"n": 0}

    async def main():
        page = await _open()
        await lite.navigate(page=page, url=f"{site}/ordinary-article")
        _sess, record = MANAGER.locate(page)
        original = record.page.evaluate

        async def counting(*args, **kwargs):
            counted["n"] += 1
            return await original(*args, **kwargs)

        record.page.evaluate = counting
        await lite.get_page_view(page=page)
        return counted["n"]

    ordinary = run(main)

    counted["n"] = 0

    async def paywalled():
        page = await _open()
        await lite.navigate(page=page, url=f"{site}/paywalled-article")
        _sess, record = MANAGER.locate(page)
        original = record.page.evaluate

        async def counting(*args, **kwargs):
            counted["n"] += 1
            return await original(*args, **kwargs)

        record.page.evaluate = counting
        await lite.get_page_view(page=page)
        return counted["n"]

    walled = run(paywalled)
    assert ordinary == walled, (
        f"a read of a paywalled page cost {walled} evaluates against "
        f"{ordinary} for an ordinary one; the read path must not probe")
