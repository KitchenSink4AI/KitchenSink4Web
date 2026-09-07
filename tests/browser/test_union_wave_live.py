"""Union wave (2026-09-07) — the LIVE half of the insane-round pins.

The unit half is `tests/unit/test_union_wave_fixes.py`. Everything here
needs a real browser and a real page, because the findings are about what
the read surfaces say about a document: a completeness claim is only a lie
against a document that contradicts it.

Fixtures live in `corpus/b/uw_*.html` alongside the rest of the
pathological set, hand-written and commented with the finding each one
carries.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.errors import Timeout
from kitchensink4web.ops import extract as extract_ops
from kitchensink4web.ops import lite

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"

#: The HTTP line terminator, built from code points rather than escapes so
#: no editing pass can turn it into a real line break inside a literal.
CRLF = bytes([13, 10])

pytestmark = pytest.mark.browser


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def corpus_site():
    handler = functools.partial(_Quiet, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def run(coro):
    async def main():
        from kitchensink4web.engine.session import MANAGER
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _open(site, path):
    from kitchensink4web.engine.session import MANAGER
    session = await MANAGER.open(headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


# ------------------------------------------------- super-class 2: reads


def test_bare_div_prose_is_read_rather_than_silently_dropped(corpus_site):
    """hostile H-04. The readable set was a fixed tag list, so text in a
    bare DIV was neither emitted NOR counted: `total_in_scope: 24` on a
    page of ordinary visible English, with "this is the end of the text in
    scope" printed under it and `stripped` counting only hidden blocks."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_divprose.html")
        got = await lite.get_text(page=page)
        assert "The committee met on a Tuesday" in got["text"]
        assert "the room was needed for something else" in got["text"].lower()
        # Every div is in the total, not just the h1 and the trailing p.
        assert got["chars"]["total_in_scope"] > 500, got["chars"]
    run(go())


def test_svg_text_is_read_and_svg_metadata_is_counted(corpus_site):
    """fuzzer class 2. Five `<svg><text>` elements of visible, rendered,
    selectable text appeared in NO payload and in no ledger row: the
    completeness block names iframes, shadow roots, hidden nodes, canvas,
    virtualized containers and unlisted affordances, and had no SVG
    vocabulary at all, so the read declared itself complete."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_svgtext.html")
        got = await lite.get_text(page=page)
        for marker in ("SVGLINEONE", "SVGLINETWO", "SVGLINETHREE"):
            assert marker in got["text"], marker
        # <title> and <desc> are the SVG spelling of alt text: counted,
        # never mixed into prose.
        assert "SVGTITLEMETA" not in got["text"]
        assert got["omitted"]["svg_title_desc"]["chars"] > 0
        assert "SVG <title>/<desc>" in got["stripped"]
    run(go())


def test_an_svg_link_href_is_the_attribute_not_a_fabricated_url(corpus_site):
    """fuzzer class 10. An SVG `<a>` exposes href as an SVGAnimatedString,
    and stringifying the DOM property produced the plausible-looking
    `/[object%20SVGAnimatedString]`, returned as fact with no flag."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_svgtext.html")
        got = await extract_ops.get_links(page=page)
        hrefs = [row["href"] for row in got["links"]]
        assert not any("SVGAnimatedString" in str(h) for h in hrefs), hrefs
        assert "/svgtarget" in hrefs, hrefs
    run(go())


def test_a_wide_table_holds_a_stated_budget(corpus_site):
    """hostile H-03, the only finding in that round that could end a
    caller's session in one call. `get_table` was bounded by rows only, so
    the PAGE picked the payload size: 254,185 tokens from one default
    call, against no stated limit."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_widetable.html")
        got = await extract_ops.get_table(page=page)
        assert got["budget"]["limit"] == extract_ops.TABLE_BUDGET_TOKENS
        assert got["budget"]["used"] <= got["budget"]["limit"], got["budget"]
        # And the trim is stated, not silent.
        acc = got["accounting"]
        assert acc["columns_dropped"] > 0
        assert acc["columns_total"] == 400
        assert "column(s) are NOT in this payload" in got["continue"]
    run(go())


def test_a_narrow_table_is_untouched(corpus_site):
    """The guard on the guard: the bound must not trim an ordinary table."""
    async def go():
        _, page = await _open(corpus_site, "b/tables.html")
        got = await extract_ops.get_table(page=page, index=0)
        assert got["accounting"]["columns_dropped"] == 0
    run(go())


def test_the_canvas_ledger_is_not_inverted(corpus_site):
    """fuzzer class 3. The counter ran on an area heuristic (>80x80) and
    was wrong in both directions: a 200x60 canvas with text painted on it
    reported "canvas-rendered regions: none", and a blank 900x600 one
    reported unread content."""
    async def go():
        _, page = await _open(corpus_site, "b/canvas.html")
        got = await lite.get_page_view(page=page)
        assert "canvas-rendered regions: none" not in got["projection"]
        assert "canvas-rendered regions with no text projection: 1" \
            in got["projection"]
        assert "pixels drawn on them" in got["projection"]
    run(go())


# --------------------------------------- super-class 3: honored timeouts


def test_wait_for_visible_actually_waits(corpus_site):
    """hostile H-08. The `visible` and `hidden` conditions resolved their
    location EAGERLY, once, before the wait, and a resolution miss aborted
    the call: `timeout_ms` was never consulted, so the one condition
    designed for "this control appears later" refused NOT_FOUND in 0.01 s
    for exactly that case."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_latereveal.html")
        got = await lite.wait_for(page=page, condition="visible",
                                  location={"css": "#name"},
                                  timeout_ms=8000)
        assert got["resolved"] is True
    run(go())


def test_wait_for_visible_reports_the_elapsed_time_it_really_spent(
        corpus_site):
    """chaos C-07. The failure asserted the BUDGET rather than the elapsed
    time: a wait that came back in 0.01 s reported "did not resolve within
    5000 ms", which is a fabricated claim about a wait that never
    happened."""
    async def go():
        import time as _time
        _, page = await _open(corpus_site, "b/uw_latereveal.html")
        started = _time.monotonic()
        with pytest.raises(Timeout) as caught:
            await lite.wait_for(page=page, condition="visible",
                                location={"css": "#never-appears"},
                                timeout_ms=2000)
        elapsed = _time.monotonic() - started
        assert 1.5 <= elapsed <= 6.0, elapsed
        assert "ms elapsed" in str(caught.value)
    run(go())


# ------------------------------------ super-class 2: the affordance ledger


def test_a_read_names_an_opaque_panel_over_the_viewport(corpus_site):
    """hostile H-09. A full-viewport opaque lid left the read saying
    "unlisted affordances: none, every control is listed" with the covered
    button listed above it, while `click` refused citing "the read's
    completeness block counts it as hidden interactive with the technique
    named" — a cross-check the read demonstrably failed to produce."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_lid.html")
        # Read AFTER the lid is confirmed composited, which is the shape
        # the finding was taken in: the panel goes up on animation frame 5,
        # past the two-frame yield the arming probe takes.
        await lite.wait_for(page=page, condition="text",
                            value="Loading, please wait", timeout_ms=5000)
        got = await lite.get_page_view(page=page)
        assert "an opaque panel covers the viewport" in got["projection"]
    run(go())


def test_a_control_zeroed_in_one_axis_is_not_offered(corpus_site):
    """hostile H-05. `ksGeometryHidden` tested width AND height, so
    `* { width:0; height:0; overflow:hidden }` left a button measuring 0 by
    its line-height: the read listed it as a live affordance and the click
    then spent the full 15-second actionability timeout finding out."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_zero.html")
        got = await lite.get_page_view(page=page)
        # The button is CLIPPED away by a zero-size overflow:hidden
        # ancestor, so it is not offered as a live affordance and the
        # ledger names the technique instead.
        assert 'button | "ZEROBTN"' not in got["projection"]
        assert "clipped-away" in got["projection"]
    run(go())


def test_a_frame_gated_page_is_read_after_the_frames_it_needs(corpus_site):
    """hostile H-06. Fix wave 8 gave the ARMING probe a two-animation-frame
    yield; the READ path got no equivalent, so a page revealing its
    controls on frame 5 read as having none and the completeness block
    affirmed it. An empty read looked final."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_raf.html")
        got = await lite.get_page_view(page=page)
        assert "REVEALED" in got["projection"] or "Continue" in got["projection"]
    run(go())


# ------------------------------- super-class 4: completion truthfulness


def test_at_end_is_not_asserted_over_a_growing_document(corpus_site):
    """hostile H-11. Four consecutive `scroll(action='end')` calls answered
    `at_end: true` and "0 screen(s) below the current view" every time,
    while the document went from 367,286 px to 1,428,086 px: roughly
    357,000 px arriving below the view between each pair of calls."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_infinite.html")
        got = await lite.scroll(page=page, action="end")
        assert got["at_end"] is False, got
        assert "growing" in got
        assert "no end to be at" in got["growing"]
    run(go())


def test_the_two_virtualization_detectors_agree(corpus_site):
    """hostile H-11, second half. `scroll` reported
    `virtualized: [{"tag": "HTML", ...}]` one call after get_page_view's
    completeness block said "virtualized or infinite-scroll containers:
    none detected", about the same page in the same session."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_infinite.html")
        scrolled = await lite.scroll(page=page, action="end")
        view = await lite.get_page_view(page=page)
        says_none = ("virtualized or infinite-scroll containers: none"
                     in view["projection"])
        assert says_none == (not scrolled["virtualized"]), (
            scrolled["virtualized"], says_none)
    run(go())


def test_a_dead_origin_is_not_read_as_an_empty_page(corpus_site):
    """chaos C-09. With the origin dead, `navigate` honestly reported
    PAGE_UNREACHABLE and the very next `get_text` answered ok with
    `{"url":"chrome-error://chromewebdata/","text":"","chars":{"returned":
    0}}` while `get_page_view` printed `status: 200 | load: load | dom
    nodes: 3` and "unlisted affordances: none, every control is listed".
    An agent that read after a failed navigation concluded the site had
    returned an empty 200, which is the most expensive wrong conclusion
    available here.

    Two shapes, one class. Bundled Chromium parks on `about:blank` when the
    connection is refused from a fresh tab and paints `chrome-error://` when
    a LOADED page's origin goes away under a reload; the read has to be
    honest about both, and neither may come back as an empty page."""
    import socket
    import threading

    class _Once(threading.Thread):
        """Serves one real page, then stops listening."""

        daemon = True

        def __init__(self):
            super().__init__()
            self.sock = socket.socket()
            self.sock.bind(("127.0.0.1", 0))
            self.sock.listen(4)
            self.port = self.sock.getsockname()[1]

        def run(self):
            while True:
                try:
                    conn, _ = self.sock.accept()
                except OSError:
                    return
                try:
                    conn.recv(4096)
                    body = (b"<!doctype html><html><body>"
                            b"<p>ORIGIN-ALIVE</p></body></html>")
                    head = (b"HTTP/1.1 200 OK" + CRLF
                            + b"Content-Type: text/html" + CRLF
                            + b"Content-Length: "
                            + str(len(body)).encode() + CRLF + CRLF)
                    conn.sendall(head + body)
                    conn.close()
                except OSError:
                    pass

    async def go():
        from kitchensink4web.errors import PageUnreachable
        from kitchensink4web.engine.session import MANAGER
        session = await MANAGER.open(headless=True)
        page = session.focused

        # Shape 1: a fresh tab, connection refused. The tab stays blank and
        # the read says why rather than returning an empty page.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
        probe.close()
        with pytest.raises(Exception):
            await lite.navigate(page=page, url=f"http://127.0.0.1:{free}/x")
        # The interstitial loads AFTER the failed navigation returns, so
        # the read gate sees about:blank and the extractor sees
        # chrome-error://. Either way the read refuses rather than
        # answering ok with an empty page.
        with pytest.raises(PageUnreachable) as caught:
            await lite.get_text(page=page)
        assert "network-error interstitial" in str(caught.value)
        with pytest.raises(PageUnreachable):
            await lite.get_page_view(page=page)

        # Shape 2: a loaded page whose origin dies under it.
        await lite.navigate(page=page, url=f"http://127.0.0.1:{once.port}/")
        once.sock.close()
        with pytest.raises(Exception):
            await lite.navigate(page=page, action="reload")
        # Either the browser painted its interstitial (a refusal) or it
        # left the old document up (a note). Both are honest; an empty page
        # served as the site's is not.
        try:
            reread = await lite.get_text(page=page)
        except PageUnreachable as exc:
            assert "network-error interstitial" in str(exc)
        else:
            assert "ORIGIN-ALIVE" in reread["text"], reread["text"][:200]

    once = _Once()
    once.start()
    try:
        run(go())
    finally:
        try:
            once.sock.close()
        except OSError:
            pass


def test_a_truncated_document_never_reads_back_as_complete():
    """chaos C-08. A body reset mid-transfer made `navigate` refuse
    honestly and the very next `get_text` answered `total_in_scope: 668`
    with "this is the end of the text in scope" under it, while
    `get_page_view`'s identity line read `status: 200 | load: load` and the
    completeness block never once said the document had not finished
    arriving. `load: load` asserted by the READ for a load state the
    PREVIOUS call refused to reach."""
    import socket
    import threading

    class _Loris(threading.Thread):
        """Declares a long body and sends a fraction of it, then closes."""

        daemon = True

        def __init__(self):
            super().__init__()
            self.sock = socket.socket()
            self.sock.bind(("127.0.0.1", 0))
            self.sock.listen(4)
            self.port = self.sock.getsockname()[1]
            self.stop = False

        def run(self):
            while not self.stop:
                try:
                    conn, _ = self.sock.accept()
                except OSError:
                    return
                try:
                    conn.recv(4096)
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/html\r\n"
                        b"Content-Length: 100000\r\n\r\n"
                        b"<!doctype html><html><body><p>"
                        b"TRUNCATED-BODY-MARKER</p>")
                    conn.close()
                except OSError:
                    pass

    async def go():
        from kitchensink4web.engine.session import MANAGER
        session = await MANAGER.open(headless=True)
        page = session.focused
        with pytest.raises(Exception):
            await lite.navigate(page=page,
                                url=f"http://127.0.0.1:{loris.port}/cut",
                                timeout_ms=4000)
        got = await lite.get_text(page=page)
        assert "not the end of the page" in got["continue"], got["continue"]
        assert "document" in got
        view = await lite.get_page_view(page=page)
        assert "INCOMPLETE DOCUMENT" in view["projection"]

    loris = _Loris()
    loris.start()
    try:
        run(go())
    finally:
        loris.stop = True
        loris.sock.close()


def test_a_self_navigating_page_refuses_honestly(corpus_site):
    """hostile H-02. A meta refresh onto the same URL made every read
    surface refuse CONFLICT with the raw driver string under a hint that
    named re-reading as the recovery, which is the one action guaranteed to
    fail forever on that page."""
    async def go():
        from kitchensink4web.errors import Conflict
        from kitchensink4web.engine.session import MANAGER
        session = await MANAGER.open(headless=True)
        page = session.focused
        try:
            await lite.navigate(page=page,
                                url=f"{corpus_site}/b/uw_selfnav.html",
                                timeout_ms=4000)
        except Exception:
            pass
        for tool in (lite.get_page_view, lite.get_text):
            with pytest.raises(Conflict) as caught:
                await tool(page=page)
            said = str(caught.value)
            assert "replaces its own document" in said, said[:200]
            assert "Re-reading will not help" in said
    run(go())
