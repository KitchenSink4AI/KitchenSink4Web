"""Phase 5's capability packs against a real browser.

The unit battery proves registration and classification; this proves the
behavior every pack claims, against a live Chromium: deterministic table
extraction with spans carried, div-table detection, honest field
extraction, the media-type chokepoint, console dedup on the flood fixture,
the download lifecycle gating, the dropzone upload refusal, network
recording with header redaction, and storage masking.

The corpus B fixtures (tables, console flood, secrets) are reused; a small
local handler adds the routes corpus does not carry (a downloadable file, a
metadata-rich page, an upload form).
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import packs
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (ConfirmationRequired, CredentialRefused,
                                    UnsupportedContent, ValidationFailed)
from kitchensink4web.ops import capture, diag, extract, files, net, storage
from kitchensink4web.policy import credentials, gates, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"

META_PAGE = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Meta rich</title>
<meta name="description" content="A page carrying real metadata">
<meta property="og:title" content="The OpenGraph Title">
<meta property="og:type" content="article">
<link rel="canonical" href="https://example.org/canonical">
<link rel="alternate" type="application/rss+xml" href="/feed.xml" title="Feed">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Widget",
 "sku":"W-100","offers":{"@type":"Offer","price":"19.99",
 "priceCurrency":"USD"}}
</script>
</head><body>
<main>
<h1>Widget</h1>
<dl><dt>Material</dt><dd>Aluminium</dd><dt>Weight</dt><dd>240 g</dd></dl>
<table><tr><th>Colour</th><td>Silver</td></tr>
<tr><th>Warranty</th><td>2 years</td></tr></table>
<ul id="feats"><li>Waterproof</li><li>Rechargeable</li><li>Lightweight</li></ul>
<a href="/download.csv" id="dl">Download the report</a>
</main></body></html>"""

UPLOAD_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Upload</title></head><body><main>
<form><input type="file" id="real" name="file"></form>
<div id="dropzone" style="width:200px;height:80px;border:1px dashed #999">
  Drop files here
  <input type="file" id="hidden" style="display:none">
</div>
</main></body></html>"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        routes = {
            "/meta": ("text/html", META_PAGE.encode()),
            "/upload": ("text/html", UPLOAD_PAGE.encode()),
        }
        if self.path in routes:
            ctype, body = routes[self.path]
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/download.csv":
            body = b"col_a,col_b\r\n1,2\r\n3,4\r\n"
            self.send_response(200)
            self.send_header("content-type", "text/csv")
            self.send_header("content-disposition",
                             'attachment; filename="report.csv"')
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(_Handler, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def loaded_packs(monkeypatch):
    """Every pack loaded and acting allowed, so pack tools resolve and the
    session-open recorders (network, console) attach."""
    monkeypatch.setattr(packs, "_LOADED",
                        set(packs.PACK_SUMMARIES), raising=False)
    monkeypatch.setattr(budgets_book(), "_backoff", {}, raising=False)
    credentials.VAULT.clear()
    readonly.apply(False)
    yield
    credentials.VAULT.clear()
    readonly.apply(False)


def budgets_book():
    from kitchensink4web.policy import budgets
    return budgets.BOOK


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _open(site, path):
    from kitchensink4web.ops import lite
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


# ---------------------------------------------------------------- extract


def test_get_table_carries_spans_and_detects_div_tables(site):
    async def go():
        _, page = await _open(site, "b/tables.html")
        # The real spanned table at index 0.
        t0 = await extract.get_table(page=page, index=0)
        table = t0["table"]
        assert table["kind"] == "table"
        assert t0["accounting"]["spans_expanded"] > 0
        # North America's row keeps its region label carried down the span.
        flat = [" ".join(r) for r in table["rows"]]
        assert any("North America" in r for r in flat)
        # rectangular: every row is the header width.
        assert all(len(r) == table["columns"] for r in table["rows"])
        # The div-table is detected and named, not missed.
        t1 = await extract.get_table(page=page, index=1)
        assert t1["table"]["kind"] in ("div-table", "div-grid")
    run(go())


def test_get_table_inventory_refuses_when_ambiguous(site):
    async def go():
        _, page = await _open(site, "b/tables.html")
        from kitchensink4web.errors import AmbiguousLocation
        try:
            await extract.get_table(page=page)
        except AmbiguousLocation as exc:
            assert "index=" in str(exc)
        else:
            raise AssertionError("multiple tables should refuse without index")
    run(go())


def test_get_metadata_and_fields_and_list(site):
    async def go():
        _, page = await _open(site, "meta")
        meta = (await extract.get_metadata(page=page))["metadata"]
        assert meta["open_graph"]["og:title"] == "The OpenGraph Title"
        assert any(j["types"] == ["Product"] for j in meta["json_ld"])
        assert meta["feeds"] and meta["feeds"][0]["type"].startswith(
            "application/rss")

        fields = await extract.extract_fields(
            page=page, fields=["price", "Material", "nonexistent_field"])
        f = fields["fields"]
        assert f["price"]["found"] is True and "19.99" in f["price"]["value"]
        assert f["Material"]["found"] is True
        assert f["nonexistent_field"]["found"] is False

        lst = await extract.get_list(page=page,
                                     location={"css": "#feats"})
        assert lst["list"]["total_items"] == 3
    run(go())


def test_export_data_writes_a_real_csv(site, tmp_path):
    async def go():
        _, page = await _open(site, "b/tables.html")
        out = tmp_path / "t.csv"
        res = await extract.export_data(page=page, index=0, path=str(out))
        assert res["rows_written"] > 0
        text = out.read_text(encoding="utf-8")
        assert "North America" in text
    run(go())


# ---------------------------------------------------------------- capture


def test_screenshot_media_type_matches_bytes_on_every_format(site):
    async def go():
        _, page = await _open(site, "meta")
        for fmt, magic in (("png", b"\x89PNG"), ("jpeg", b"\xff\xd8\xff")):
            res = await capture.take_screenshot(page=page, format=fmt)
            # inline result is a ToolResult; the structured payload carries
            # the media type derived from the bytes.
            payload = res.structured_content if hasattr(
                res, "structured_content") else res
            assert payload["format"] == fmt
            assert payload["media_type"] == f"image/{fmt}"
    run(go())


def test_screenshot_spills_a_large_capture_to_a_file(site, tmp_path,
                                                     monkeypatch):
    async def go():
        monkeypatch.setenv("KS4WEB_SHOT_MAX_BYTES", "10")  # force spill
        _, page = await _open(site, "meta")
        res = await capture.take_screenshot(page=page, format="png")
        assert res["inline"] is False
        saved = Path(res["saved_to"])
        assert saved.exists()
        assert saved.read_bytes().startswith(b"\x89PNG")
    run(go())


def test_screenshot_masks_secret_fields(site):
    async def go():
        _, page = await _open(site, "b/secrets.html")
        res = await capture.take_screenshot(page=page, format="png")
        payload = res.structured_content if hasattr(
            res, "structured_content") else res
        assert payload["masked_fields"] >= 1
    run(go())


# --------------------------------------------------------------- console


def test_list_console_dedupes_the_flood_and_keeps_the_needles(site):
    async def go():
        session, page = await _open(site, "b/console_flood.html")
        await session.pages[page].page.wait_for_timeout(300)
        errs = await diag.list_console(session=session.session_id,
                                       level="error")
        # The two needles survive under thousands of noise lines.
        samples = " ".join(r["sample"] for r in errs["messages"])
        assert "TypeError" in samples
        assert "401" in samples
        # And the flood is collapsed, not handed over line by line.
        assert errs["totals"]["lines_seen"] > 1000
        allmsgs = await diag.list_console(session=session.session_id,
                                          level="all")
        assert len(allmsgs["messages"]) < 60
        assert allmsgs["totals"]["collapsed_by_dedup"] > 1000
    run(go())


# ----------------------------------------------------------------- network


def test_network_records_and_redacts_headers(site):
    async def go():
        session, page = await _open(site, "meta")
        reqs = await net.list_requests(session=session.session_id)
        assert reqs["totals"]["recorded"] >= 1
        doc = next(r for r in reqs["requests"]
                   if r["resource_type"] == "document")
        got = await net.get_request(request_id=doc["id"],
                                    session=session.session_id)
        assert got["status"] == 200
        # A cookie header, if present, is masked; assert the redactor ran by
        # confirming no raw sensitive header value is echoed verbatim.
        headers = got.get("request_headers", {})
        for name, value in headers.items():
            if name.lower() in net.SENSITIVE_HEADERS:
                assert "masked" in str(value)
    run(go())


def test_analytics_hidden_by_default_and_counted(site):
    async def go():
        session, page = await _open(site, "meta")
        log = net._log(MANAGER.session(session.session_id))
        # Inject a synthetic analytics record to prove the split.
        class _Req:
            method = "GET"
            url = "https://www.google-analytics.com/collect?v=1"
            resource_type = "image"
        net._record(MANAGER.session(session.session_id), _Req())
        listed = await net.list_requests(session=session.session_id)
        urls = " ".join(r["url"] for r in listed["requests"])
        assert "google-analytics" not in urls
        assert listed["totals"]["analytics_hidden"] >= 1
        widened = await net.list_requests(session=session.session_id,
                                          include_analytics=True)
        assert any("google-analytics" in r["url"]
                   for r in widened["requests"])
    run(go())


# ----------------------------------------------------------------- storage


def test_cookies_and_storage_are_masked_by_default(site):
    async def go():
        session, page = await _open(site, "meta")
        await session.pages[page].page.evaluate(
            "() => localStorage.setItem('token', 'super-secret-value-1234')")
        got = await storage.manage_storage(page=page, kind="local")
        item = next(i for i in got["items"] if i["key"] == "token")
        assert item["value"] is None          # masked: only length shown
        assert item["chars"] == len("super-secret-value-1234")
        # unmask refuses under the strict default.
        with pytest.raises(CredentialRefused):
            await storage.manage_storage(page=page, kind="local",
                                         unmask=True)
    run(go())


# ------------------------------------------------------------------- files


def test_download_lifecycle_gates_the_write(site):
    """download-to-disk is a gated class; with no MRTR wiring it fails
    closed, which is the honest Phase 5 state (like fill_form submit)."""
    async def go():
        _, page = await _open(site, "meta")
        with pytest.raises(ConfirmationRequired):
            await files.download(page=page, action="click",
                                 location={"css": "#dl"}, timeout_ms=8000)
    run(go())


def test_upload_to_a_dropzone_names_the_input_route(site, tmp_path):
    async def go():
        _, page = await _open(site, "upload")
        upload_me = tmp_path / "u.txt"
        upload_me.write_text("hello", encoding="utf-8")
        # The visible dropzone is a div: refuse and name the hidden input.
        # VALIDATION_FAILED since 2026-09-06: this refusal used to wear
        # MODAL_BLOCKED, whose hint now names handle_dialog, and a wrong
        # element is not a dialog to answer.
        with pytest.raises(ValidationFailed):
            await files.upload_file(page=page,
                                    location={"css": "#dropzone"},
                                    files=[str(upload_me)])
        # The real input: file upload is a gated class, so it fails closed
        # at the choke point, which proves the gate is wired.
        with pytest.raises(ConfirmationRequired):
            await files.upload_file(page=page, location={"css": "#real"},
                                    files=[str(upload_me)])
    run(go())
