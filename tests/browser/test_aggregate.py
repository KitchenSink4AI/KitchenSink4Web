"""`aggregate` (#7): one schema across many URLs, against a real browser.

The whole feature is one rule: **a per-URL failure is DATA in that URL's slot,
and only a whole-batch failure raises.** A dead host does not sink a batch, a
bot wall does not sink a batch, and a budget that trips on the thirteenth URL
does not throw away the twelve rows already collected. What DOES stop the walk
stops it loudly and hands back everything it had.

The fixture server is local and keeps a request log, because "URLs 2 and 3 did
not hit the host" is a claim about requests and the only honest way to check it
is to count them.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.errors import BadParams, BudgetExhausted
from kitchensink4web.ops import extract as extract_ops
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets

pytestmark = pytest.mark.browser


def _product(name, price, sku):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{name}</title>"
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product",'
        f'"name":"{name}","sku":"{sku}",'
        f'"offers":{{"@type":"Offer","price":"{price}",'
        '"priceCurrency":"GBP"}}'
        "</script></head><body>"
        f"<main><h1>{name}</h1><p id=stock>In stock</p></main>"
        "</body></html>").encode()


#: Two records under one key, so the ambiguity outcome has a home in the
#: per-field roll-up.
_TWO_AUTHORS = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    "<title>Two</title></head><body>"
    '<div itemscope itemtype="https://schema.org/CreativeWork">'
    '<span itemprop="author">Ada Lovelace</span></div>'
    '<div itemscope itemtype="https://schema.org/CreativeWork">'
    '<span itemprop="author">Grace Hopper</span></div>'
    "</body></html>").encode()

REQUEST_LOG: list[str] = []


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, extra=()):
        self.send_response(status)
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(body)))
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        REQUEST_LOG.append(self.path)
        if self.path.startswith("/p/"):
            slug = self.path[3:]
            self._send(200, _product(f"Widget {slug}", f"{slug}.00",
                                     f"SKU-{slug}"))
        elif self.path == "/authors":
            self._send(200, _TWO_AUTHORS)
        elif self.path == "/wall":
            self._send(403, b"<html><head><title>Just a moment...</title>"
                            b"</head><body><h1>Just a moment...</h1>"
                            b"<p>Checking your browser.</p></body></html>",
                       extra=[("cf-mitigated", "challenge"),
                              ("server", "cloudflare")])
        elif self.path == "/limited":
            self._send(429, b"<html><body>slow down</body></html>",
                       extra=[("retry-after", "120")])
        else:
            self._send(404, b"<html><body>no</body></html>")


@pytest.fixture(scope="module")
def site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean_log():
    REQUEST_LOG.clear()
    yield
    REQUEST_LOG.clear()


def run(coro):
    async def main():
        from kitchensink4web.engine.session import MANAGER
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _session():
    from kitchensink4web.engine.session import MANAGER
    session = await MANAGER.open(headless=True)
    return session, session.focused


def _dead_url() -> str:
    """A port nothing is listening on, chosen by binding and releasing one.

    A hard-coded low port is not a dead host to Chromium, it is an UNSAFE
    port: `http://127.0.0.1:9/` never reaches the network and comes back
    NAVIGATION_FAILED (err_unsafe_port), which is a different fact from
    "nothing answered" and would make this test assert the wrong code."""
    probe = socketserver.socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return f"http://127.0.0.1:{port}/dead"


_DEAD = _dead_url()


# ------------------------------------------- 1. one dead URL is one dead row


def test_aggregate_dead_url_does_not_sink_batch(site):
    async def go():
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/11", _DEAD, f"{site}/p/13"],
            schema=["price", "sku"], page=page)
        assert got["requested"] == 3
        assert got["succeeded"] == 2, got["results"]
        assert got["failed"] == 1
        assert got["results"][0]["fields"]["price"]["value"] == "11.00"
        assert got["results"][2]["fields"]["price"]["value"] == "13.00"
        middle = got["results"][1]
        assert middle["ok"] is False
        assert middle["error"]["code"] == "PAGE_UNREACHABLE", middle
        assert "covers" in got["continue"]
    run(go())


def test_aggregate_wall_is_per_url(site):
    """A bot wall lands in its slot with the verdict, the other rows succeed,
    and the wall page's own text appears nowhere in the payload."""
    async def go():
        import json
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/21", f"{site}/wall", f"{site}/p/23"],
            schema=["price"], page=page)
        assert got["succeeded"] == 2
        blocked = got["results"][1]
        assert blocked["error"]["code"] == "BLOCKED_BY_SITE", blocked
        assert "bot-wall-or-captcha" in blocked["error"]["message"]
        flat = json.dumps(got, default=str)
        assert "Just a moment" not in flat
        assert "Checking your browser" not in flat
    run(go())


def test_aggregate_error_shape_matches_envelope(site):
    """A per-URL error parses IDENTICALLY to a top-level refusal, because it is
    built by the same function. One parsing path for a refusal wherever it
    happened."""
    async def go():
        from kitchensink4web import envelope
        from kitchensink4web.errors import BlockedBySite
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/31", f"{site}/wall"],
            schema=["price"], page=page)
        slot = got["results"][1]["error"]
        top = envelope.refusal(BlockedBySite("x"))["error"]
        assert set(top) <= set(slot), (sorted(top), sorted(slot))
        assert slot["hint"], slot
    run(go())


# ---------------------------------------------------------- 2. the budgets


def test_aggregate_charges_per_url(site):
    """The navigation counter delta equals the URL count, asserted against the
    enforcing ledger rather than against a number the tool reports about
    itself. A walk is not a way around a budget."""
    async def go():
        _s, page = await _session()
        from kitchensink4web.engine.session import MANAGER
        sess, _record = MANAGER.locate(page)
        before = budgets.BOOK.snapshot(
            sess.session_id)["counters"]["navigations"]
        await extract_ops.aggregate(
            urls=[f"{site}/p/41", f"{site}/p/42", f"{site}/p/43"],
            schema=["price"], page=page)
        after = budgets.BOOK.snapshot(
            sess.session_id)["counters"]["navigations"]
        assert after - before == 3, (before, after)
    run(go())


def test_aggregate_budget_exhaustion_returns_partials(site, monkeypatch):
    """Losing three completed extractions because the fourth URL exhausted a
    budget is the failure mode this clause exists to prevent."""
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "3")
    async def go():
        from kitchensink4web import envelope
        _s, page = await _session()
        with pytest.raises(BudgetExhausted) as exc:
            await extract_ops.aggregate(
                urls=[f"{site}/p/5{i}" for i in range(6)],
                schema=["price"], page=page, max_urls=6)
        detail = envelope.refusal(exc.value)["error"]["detail"]
        assert detail["completed"] == 3, detail
        assert detail["requested"] == 6
        rows = detail["partial_results"]
        assert [r["fields"]["price"]["value"] for r in rows] == \
            ["50.00", "51.00", "52.00"]
    run(go())


def test_aggregate_preflight_advises_when_the_budget_is_short(site,
                                                              monkeypatch):
    """An advisory, not a refusal: the caller may legitimately want as many as
    fit, and nothing is silently truncated either."""
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "2")
    async def go():
        _s, page = await _session()
        with pytest.raises(BudgetExhausted):
            await extract_ops.aggregate(
                urls=[f"{site}/p/6{i}" for i in range(4)],
                schema=["price"], page=page, max_urls=4)
    run(go())


def test_aggregate_429_stops_later_hops_to_that_domain(site):
    """URL 1 answers 429; URLs 2 and 3 on the same host refuse in their own
    slots without a request being issued. Asserted from the server's log."""
    async def go():
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/limited", f"{site}/p/71", f"{site}/p/72"],
            schema=["price"], page=page)
        assert got["succeeded"] == 0, got["results"]
        assert got["failed"] == 3
        for slot in got["results"][1:]:
            assert slot["error"]["code"] == "BLOCKED_BY_SITE", slot
            assert "429" in slot["error"]["message"]
        assert "/p/71" not in REQUEST_LOG, REQUEST_LOG
        assert "/p/72" not in REQUEST_LOG, REQUEST_LOG
        return got
    got = run(go())
    # The backoff is process-wide and would poison every later test in this
    # module against the same host.
    budgets.BOOK._backoff.clear()
    assert got["failed"] == 3


# --------------------------------------------------------- 3. the honesty


def test_aggregate_summary_counts_failures(site):
    """The failure count is in the summary, not only discoverable by walking
    the slots. A tool that returns 2 rows from 3 URLs and calls it a dataset is
    claiming completeness over omissions."""
    async def go():
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/81", _DEAD, f"{site}/p/83"],
            schema=["price"], page=page)
        assert got["failed"] == 1
        assert got["succeeded"] == 2
        assert got["requested"] == 3
        assert "2" in got["continue"] and "1" in got["continue"]
    run(go())


def test_aggregate_per_field_rollup(site):
    """filled / not_found / ambiguous per field, COMPUTED across mixed pages
    rather than claimed."""
    async def go():
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/91", f"{site}/p/92", f"{site}/authors"],
            schema=["price", "author"], page=page)
        per = got["summary"]["per_field"]
        assert per["price"] == {"filled": 2, "not_found": 1, "ambiguous": 0,
                                "empty": 0, "secret": 0}, per
        assert per["author"] == {"filled": 0, "not_found": 2, "ambiguous": 1,
                                 "empty": 0, "secret": 0}, per
        assert got["summary"]["fields_filled_total"] == 2
    run(go())


def test_aggregate_multi_origin_envelope(site):
    """One payload carrying several documents' text. The note names every
    contributing URL, so a caller cannot read the whole dataset as coming from
    the first one."""
    async def go():
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/1", f"{site}/p/2"], schema=["price"], page=page)
        note = got["page_data"]
        provenance = [f["provenance"] for f in note["frames"]]
        assert any("/p/1" in p for p in provenance), provenance
        assert any("/p/2" in p for p in provenance), provenance
        assert "embedded" in note["label"] or "DIFFERENT document" in \
            note["label"]
        assert note["nonce"] in got["dataset_text"]
    run(go())


def test_aggregate_refs_invalidated(site):
    """The walk navigated, so a ref minted before it is gone and the payload
    said it would be."""
    async def go():
        from kitchensink4web.errors import StaleAnchor, TargetNotFound
        _s, page = await _session()
        await lite.navigate(page=page, url=f"{site}/p/5")
        found = await lite.find_elements(page=page, query="#stock", kind="css")
        ref = found["results"].split("\n")[2].split(" | ")[0].strip()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/6", f"{site}/p/7"], schema=["price"], page=page)
        assert "refs" in got and "gone" in got["refs"]
        with pytest.raises((StaleAnchor, TargetNotFound)):
            await lite.get_text(page=page, location={"ref": ref})
    run(go())


# ------------------------------------------------------------ 4. pre-flight


def test_aggregate_preflight_validates_whole_list(site):
    """One bad scheme among five refuses BAD_PARAMS naming it, and ZERO
    navigations happened. A batch tool that refuses on the first bad URL makes
    a caller discover a five-typo list five calls at a time."""
    async def go():
        _s, page = await _session()
        with pytest.raises(BadParams) as exc:
            await extract_ops.aggregate(
                urls=[f"{site}/p/1", "file:///etc/passwd", f"{site}/p/3",
                      "javascript:alert(1)", f"{site}/p/5"],
                schema=["price"], page=page)
        message = str(exc.value)
        assert "file:///etc/passwd" in message, message
        assert "javascript:alert(1)" in message, message
        assert "ZERO" in message
        assert not [p for p in REQUEST_LOG if p.startswith("/p/")], REQUEST_LOG
    run(go())


def test_aggregate_bad_arguments_refuse(site):
    async def go():
        _s, page = await _session()
        with pytest.raises(BadParams) as empty:
            await extract_ops.aggregate(urls=[], schema=["price"], page=page)
        assert "non-empty" in str(empty.value)
        with pytest.raises(BadParams) as over:
            await extract_ops.aggregate(
                urls=[f"{site}/p/{i}" for i in range(3)],
                schema=["price"], page=page, max_urls=80)
        assert "50" in str(over.value), str(over.value)
        with pytest.raises(BadParams) as long_list:
            await extract_ops.aggregate(
                urls=[f"{site}/p/{i}" for i in range(5)],
                schema=["price"], page=page, max_urls=2)
        assert "max_urls" in str(long_list.value)
        with pytest.raises(BadParams):
            await extract_ops.aggregate(
                urls=[f"{site}/p/1"], schema=[], page=page)
        assert not [p for p in REQUEST_LOG if p.startswith("/p/")], REQUEST_LOG
    run(go())


def test_aggregate_default_batch_is_derived_from_the_budget(monkeypatch):
    """The default is budget math rather than a constant, so it tracks a
    deployment that moves the navigation limit instead of promising a batch
    size the session cannot afford."""
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "150")
    assert extract_ops.default_batch_size() == 30
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "10")
    assert extract_ops.default_batch_size() == 2
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "1000")
    assert extract_ops.default_batch_size() == extract_ops.AGGREGATE_URL_CEILING


# ------------------------------------------------------- 5. strict grade


def test_aggregate_strict_mode_holds_every_hop(site, monkeypatch):
    """Under `--read-only strict` the origin allowlist binds every hop, not
    only the first, and an off-list URL refuses in its OWN slot while the
    on-list ones succeed. Nothing here is re-expressed: it falls out of the
    choke point, which is the whole reason the walk goes through it per URL."""
    from kitchensink4web.policy import origins, readonly
    port = site.rsplit(":", 1)[1]
    # The allowlist names the HOST. `localhost` is a different host name that
    # resolves to the same server, so the off-list row is a URL that WOULD
    # have worked: the refusal is the allowlist doing its job rather than the
    # request failing for an unrelated reason.
    monkeypatch.setenv(origins.ENV_ALLOW, "127.0.0.1")
    readonly.apply("strict")
    try:
        async def go():
            _s, page = await _session()
            return await extract_ops.aggregate(
                urls=[f"{site}/p/1", f"http://localhost:{port}/p/9",
                      f"{site}/p/2"],
                schema=["price"], page=page)
        got = run(go())
    finally:
        readonly.apply(False)
    assert got["succeeded"] == 2, got["results"]
    assert got["results"][1]["ok"] is False, got["results"][1]
    assert got["results"][1]["error"]["code"] in (
        "READ_ONLY_MODE", "NAVIGATION_BLOCKED"), got["results"][1]


# ------------------------------------------------------------- 6. the wait


def test_aggregate_opens_its_own_session_and_says_so(site):
    """The manage_session round trip is optional here for the same reason it is
    optional on navigate, and the payload names the session it opened rather
    than leaving the caller to discover one appeared."""
    async def go():
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/1"], schema=["price"])
        assert got["succeeded"] == 1
        assert "auto_session" in got, sorted(got)
        assert "headless" in got["auto_session"]
    run(go())


def test_aggregate_wait_is_applied_per_url(site):
    async def go():
        _s, page = await _session()
        got = await extract_ops.aggregate(
            urls=[f"{site}/p/1", f"{site}/p/2"], schema=["price"], page=page,
            wait={"condition": "text", "value": "In stock"})
        assert got["succeeded"] == 2, got["results"]
        with pytest.raises(BadParams):
            await extract_ops.aggregate(
                urls=[f"{site}/p/1"], schema=["price"], page=page,
                wait={"value": "In stock"})
    run(go())
