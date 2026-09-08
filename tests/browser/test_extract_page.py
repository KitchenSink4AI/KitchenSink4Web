"""`extract_page` (#3): the tier ladder, against a real browser.

The spec's prototype receipt is the acceptance bar and it is a NEGATIVE bar:
zero wrong values across its ten-page battery, including a prose decoy where
all four fields must come back not_found and a `display:none` price that must
not appear anywhere. A wrong extraction delivered with a straight face is the
one unforgivable defect in this tool, so most of what is pinned here is what
the tool REFUSES to say.

Fixtures live in `corpus/b/xp_*.html`, hand-written and commented with the
defect each one carries. Nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.errors import BadParams, BlockedBySite, TargetNotFound
from kitchensink4web.ops import extract as extract_ops
from kitchensink4web.ops import lite

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"

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


def _flat(payload) -> str:
    """The whole payload as one searchable string, for the never-appears
    assertions. A value that must not be returned must not be returned
    ANYWHERE, including inside an accounting note or a candidate listing."""
    import json
    return json.dumps(payload, ensure_ascii=False, default=str)


# ------------------------------------------------- 1. the matcher's guards


def test_extract_page_partial_needs_both_guards(corpus_site):
    """A one-character source key can never fill a field, and the shipped
    `extract_fields` is held to the same bar on the same page."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_shortkey.html")
        got = await extract_ops.extract_page(
            page=page, schema={"price": "the current price",
                               "published": "the publication date"})
        fields = got["fields"]
        assert fields["price"]["found"] is False, fields["price"]
        assert fields["published"]["found"] is False, fields["published"]
        assert "destroyers" not in _flat(got["fields"])
        # The shipped tool, on the same page, for the same reason.
        legacy = await extract_ops.extract_fields(
            page=page, fields={"price": "the current price",
                               "published": "the publication date"})
        assert legacy["fields"]["price"]["found"] is False
        assert "destroyers" not in _flat(legacy["fields"])
        return got
    run(go())


def test_extract_page_description_never_partials(corpus_site):
    """The description sharpens exact and all-words matching and never feeds a
    partial, so a field described as "the product title" cannot come back with
    the DOCUMENT title."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_lamp.html")
        got = await extract_ops.extract_page(
            page=page, schema={"product_name": "the product title"})
        entry = got["fields"]["product_name"]
        if entry["found"]:
            assert entry["value"] == "Anglepoise Type 75 Desk Lamp", entry
        assert entry.get("value") != "Lamp"
    run(go())


# ---------------------------------------------------- 2. the doctrine test


def test_extract_page_prose_decoy_finds_nothing(corpus_site):
    """Zero tolerance. A blog post that MENTIONS a price is not a page with a
    price, and there is no prose tier at any setting."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_prose_decoy.html")
        for tiers in ("all", "declared", "labeled", "proximate", "page-hint"):
            got = await extract_ops.extract_page(
                page=page, tiers=tiers,
                schema={"price": "the listed product price",
                        "rating": "the average customer rating",
                        "review_count": "how many reviews there are",
                        "sku": "the stock keeping unit"})
            for name, entry in got["fields"].items():
                assert entry["found"] is False, (tiers, name, entry)
            flat = _flat(got["fields"])
            assert "49.99" not in flat, (tiers, flat[:400])
            assert "3.8 out of 5" not in flat, tiers
            assert "400" not in flat, tiers
    run(go())


# ---------------------------------------------- 3. the shared hidden rule


def test_extract_page_hidden_value_excluded(corpus_site):
    """A display:none price beside a visible one resolves to the visible one
    with no rival, and the hidden value appears in no tier and no payload."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_hidden_price.html")
        got = await extract_ops.extract_page(
            page=page, schema=["price", "name"])
        price = got["fields"]["price"]
        assert price["found"] is True, price
        assert "189.00" in price["value"], price
        assert price.get("rivals") is None
        assert "0.01" not in _flat(got), _flat(got)[:600]
        assert got["accounting"]["hidden_values_excluded"] >= 1
        return got
    run(go())


def test_extract_page_styling_only_value_refuses_with_a_flag(corpus_site):
    """A rating that exists only as `class="star-rating Three"` is not found,
    at any tier, and the not_found SAYS the value exists only as styling
    rather than reading as "this page has no rating"."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_hidden_price.html")
        for tiers in ("all", "page-hint"):
            got = await extract_ops.extract_page(
                page=page, tiers=tiers, schema=["star_rating"])
            entry = got["fields"]["star_rating"]
            assert entry["found"] is False, (tiers, entry)
            assert entry.get("styling_only") is True, (tiers, entry)
            assert "styling" in (entry.get("styling_note") or entry["note"])
    run(go())


# ------------------------------------------------------- 4. repeated records


def test_extract_page_repeated_records_refuse(corpus_site):
    """Eight authors is not one author. The candidates are listed and
    `location=` is named as the recovery."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_records.html")
        got = await extract_ops.extract_page(page=page, schema=["author"])
        entry = got["fields"]["author"]
        assert entry["found"] is False
        assert entry["reason"] == "ambiguous", entry
        assert entry["rivals"] == 8, entry
        values = [c["value"] for c in entry["candidates"]]
        assert "Albert Einstein" in values
        assert len(entry["candidates"]) <= 6
        assert "location=" in entry["note"]
        assert got["accounting"]["ambiguous"] == 1
    run(go())


def test_extract_page_scope_resolves_ambiguity(corpus_site):
    """The same page, scoped to one record, answers that record's value."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_records.html")
        found = await lite.find_elements(page=page, query="#rec3", kind="css")
        assert found["matched"] == 1, found["results"]
        ref = found["results"].split("\n")[2].split(" | ")[0].strip()
        got = await extract_ops.extract_page(
            page=page, schema=["author"], location={"ref": ref})
        entry = got["fields"]["author"]
        assert entry["found"] is True, entry
        assert entry["value"] == "Marilyn Monroe", entry
        assert entry["confidence"] == "declared"
        assert got["accounting"]["scope"] == "one subtree"
        assert "scope_note" in got["accounting"]
    run(go())


def test_extract_page_dead_scope_ref_refuses(corpus_site):
    async def go():
        _s, page = await _open(corpus_site, "b/xp_records.html")
        with pytest.raises(TargetNotFound):
            await extract_ops.extract_page(
                page=page, schema=["author"], location={"ref": "e999"})
    run(go())


# ------------------------------------------------------------- 5. the tiers


def test_extract_page_tiers_declared_only(corpus_site):
    """Div soup is tier-3 evidence. `tiers="declared"` is the mode a caller
    uses when every filled field has to be defensible, and on this page that
    means nothing fills."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_divsoup.html")
        schema = ["capacity", "material", "warranty"]
        loose = await extract_ops.extract_page(
            page=page, schema=schema, tiers="all")
        assert loose["fields"]["capacity"]["value"] == "1.0 L"
        assert loose["fields"]["capacity"]["relation"] == "next-sibling"
        assert loose["fields"]["material"]["relation"] == "parent-next-sibling"
        assert loose["fields"]["warranty"]["confidence"] == "labeled"
        assert isinstance(loose["fields"]["capacity"]["gap_px"], int)
        strict = await extract_ops.extract_page(
            page=page, schema=schema, tiers="declared")
        for name in schema:
            assert strict["fields"][name]["found"] is False, name
        assert strict["accounting"]["tiers_withheld"] == [
            "labeled", "proximate", "page-hint"]
    run(go())


def test_extract_page_hint_tier_off_by_default(corpus_site):
    """A field answerable only from a class token is not_found under `all` and
    found under `page-hint`, and the not_found says the token is there."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_hint.html")
        default = await extract_ops.extract_page(
            page=page, schema=["listing_price"])
        entry = default["fields"]["listing_price"]
        assert entry["found"] is False, entry
        assert entry["page_hint_candidates"] >= 1, entry
        assert "page-hint" in entry["hint_note"]
        named = await extract_ops.extract_page(
            page=page, schema=["listing_price"], tiers="page-hint")
        hit = named["fields"]["listing_price"]
        assert hit["found"] is True, hit
        assert "42.00" in hit["value"]
        assert hit["confidence"] == "page-hint"
    run(go())


# ------------------------------------------------- 6. empty, secret, conflict


def test_extract_page_empty_vs_not_found(corpus_site):
    async def go():
        _s, page = await _open(corpus_site, "b/xp_form.html")
        got = await extract_ops.extract_page(
            page=page, schema=["nickname", "account holder", "shoe_size"])
        assert got["fields"]["nickname"]["reason"] == "empty", \
            got["fields"]["nickname"]
        assert got["fields"]["account holder"]["found"] is True
        assert got["fields"]["shoe_size"]["reason"] == "not_found"
        assert got["accounting"]["empty"] == 1
    run(go())


def test_extract_page_secret_never_read(corpus_site):
    """The value is not read, not read-then-redacted, and it appears nowhere
    in the payload."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_form.html")
        got = await extract_ops.extract_page(page=page, schema=["password"])
        entry = got["fields"]["password"]
        assert entry["found"] is False
        assert entry["reason"] == "secret", entry
        assert "hunter2" not in _flat(got), _flat(got)[:600]
        assert "handoff" in entry["note"]
        assert got["accounting"]["secret_fields_never_read"] >= 1
    run(go())


def test_extract_page_disagreement_reported(corpus_site):
    """The page said 999.00 and 199.00 about its own price. The declared tier
    answers and BOTH are surfaced, with the conflict marked."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_conflict.html")
        got = await extract_ops.extract_page(page=page, schema=["price"])
        entry = got["fields"]["price"]
        assert entry["found"] is True, entry
        assert entry["value"] == "999.00", entry
        assert entry["confidence"] == "declared"
        assert entry["conflict"] is True, entry
        lower = {row["value"] for row in entry["disagreement"]}
        assert "199.00" in lower, entry
        assert got["accounting"]["conflicts"] == 1
    run(go())


# ------------------------------------------------- 7. envelope and read gate


def test_extract_page_envelope(corpus_site):
    """Every page-authored string rides the nonce-carrying envelope, and the
    label names the structured fields beside it as carrying the same status."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_hidden_price.html")
        got = await extract_ops.extract_page(
            page=page, schema=["price", "name", "availability"])
        nonce = got["page_data"]["nonce"]
        assert got["fields_text"].startswith(f"<<<KS4WEB-PAGE-DATA {nonce}>>>")
        assert got["fields_text"].rstrip().endswith(
            f"<<<END-KS4WEB-PAGE-DATA {nonce}>>>")
        assert "UNTRUSTED PAGE CONTENT" in got["page_data"]["label"]
        assert "page-authored" in got["page_data"]["label"]
        for entry in got["fields"].values():
            if entry.get("found"):
                assert entry["value"] in got["fields_text"], entry
                assert entry["matched_key"] in got["fields_text"], entry
    run(go())


class _WallHandler(http.server.BaseHTTPRequestHandler):
    """A page that moves ITSELF onto a Cloudflare challenge, which is how a
    real interstitial usually arrives. `navigate` classifies the 200 shell it
    was handed and the response listener records the 403 and the header on the
    object the read surfaces hold."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/shell":
            body = (b"<html><head><title>Loading</title>"
                    b"<meta http-equiv='refresh' content='0;url=/wall'>"
                    b"</head><body><p>one moment</p></body></html>")
            self.send_response(200)
        else:
            body = (b"<html><head><title>Just a moment...</title></head>"
                    b"<body><h1>Just a moment...</h1>"
                    b"<p>Checking your browser.</p></body></html>")
            self.send_response(403)
            self.send_header("cf-mitigated", "challenge")
            self.send_header("server", "cloudflare")
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def wall_site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _WallHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_extract_page_read_gate(wall_site):
    """A page parked on a recorded bot wall refuses before a field is read,
    and the wall's own text never reaches the payload.

    WHICH SURFACE REPORTS IT IS A RACE, and the assertions are on the answer
    rather than on the surface (fix wave 10). The shell meta-refreshes with
    `content='0;...'`, so whether `navigate` sees the shell or the already
    painted challenge is a matter of milliseconds. That race has always been
    here; adding "checking your browser" to the challenge vocabulary made
    `navigate` win it often enough to notice. A wall caught one call EARLIER
    is the safer direction and the same true answer, so the test accepts
    either surface and holds both properties that matter on whichever one
    speaks: the category is named, and the challenge page's own words never
    ride out in the message."""
    async def go():
        from kitchensink4web.engine.session import MANAGER
        session = await MANAGER.open(headless=True)
        page = session.focused
        try:
            await lite.navigate(page=page, url=f"{wall_site}/shell")
        except BlockedBySite as exc:
            return str(exc)
        await asyncio.sleep(1.5)
        with pytest.raises(BlockedBySite) as exc:
            await extract_ops.extract_page(
                page=page, schema=["title", "price"])
        return str(exc.value)

    message = run(go())
    assert "bot-wall-or-captcha" in message, message
    assert "Just a moment" not in message, message


# -------------------------------------------------- 8. the prototype battery


#: The spec's prototype ran a candidate ladder against ten pages and reported
#: ZERO WRONG VALUES. That is the acceptance bar, and it is reproduced here on
#: the four frozen real pages plus the synthetic product shapes. The two LIVE
#: sites the prototype also used are deliberately absent: the corpus is
#: hermetic by rule and a test that needs the network is a test that fails on a
#: train.
_BATTERY_SCHEMA = {
    "price": "the current price",
    "rating": "the average customer rating",
    "review_count": "how many reviews there are",
    "sku": "the stock keeping unit",
    "shipping_weight": "the shipping weight",
    "signed": "the date the treaty was signed",
}


@pytest.mark.parametrize("path", [
    "a/wikipedia_gdp_table.html", "a/httpbin_form.html", "a/example_com.html"])
def test_extract_page_non_commerce_pages_fill_nothing(corpus_site, path):
    """`price` and `rating` on a page that sells nothing is not_found, on
    every frozen real page in the corpus."""
    async def go():
        _s, page = await _open(corpus_site, path)
        got = await extract_ops.extract_page(
            page=page, schema=_BATTERY_SCHEMA)
        for name, entry in got["fields"].items():
            assert entry["found"] is False, (path, name, entry)
        return got
    run(go())


def test_extract_page_versailles_infobox_row(corpus_site):
    """The frozen Wikipedia Versailles page: the infobox `Signed` date fills
    from a two-column table row, and the six commerce fields do not fill at
    all. Both halves are the same claim."""
    async def go():
        _s, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        got = await extract_ops.extract_page(
            page=page, schema=_BATTERY_SCHEMA)
        signed = got["fields"]["signed"]
        assert signed["found"] is True, signed
        assert signed["confidence"] == "labeled"
        assert signed["by"] == "table-row"
        assert "28 June 1919" in signed["value"]
        for name in ("price", "rating", "review_count", "sku",
                     "shipping_weight"):
            assert got["fields"][name]["found"] is False, (
                name, got["fields"][name])
        # The retention caps were reached on a page this size and the payload
        # SAYS so: a cap nobody is told about is a completeness lie.
        assert got["accounting"]["capped"]["dropped"], got["accounting"]
    run(go())


def test_extract_page_json_ld_product(corpus_site):
    """Five of six on a declared product, and the sixth is honestly absent."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_jsonld_product.html")
        got = await extract_ops.extract_page(
            page=page,
            schema={"price": "the current price", "sku": "the sku",
                    "brand": "the manufacturer", "rating_value": "the rating",
                    "review_count": "how many reviews",
                    "shipping_weight": "the shipping weight"})
        f = got["fields"]
        assert f["price"]["value"] == "79.00", f["price"]
        assert f["price"]["confidence"] == "declared"
        assert f["price"]["by"] == "json-ld(Offer)", f["price"]
        assert f["sku"]["value"] == "EM77-1000"
        assert f["brand"]["value"] == "Stelton"
        assert f["rating_value"]["value"] == "4.6"
        assert f["review_count"]["value"] == "318"
        assert f["shipping_weight"]["found"] is False
        assert got["accounting"]["filled"] == 5
    run(go())


def test_extract_page_microdata_and_definition_list(corpus_site):
    async def go():
        _s, page = await _open(corpus_site, "b/xp_microdata_product.html")
        got = await extract_ops.extract_page(
            page=page, schema=["name", "sku", "price", "material",
                               "shipping weight"])
        f = got["fields"]
        assert f["name"]["value"] == "Ercol Windsor Chair"
        assert f["sku"]["value"] == "ERC-4820"
        assert f["price"]["value"] == "245.00"
        assert f["price"]["by"].startswith("microdata(")
        assert f["material"]["value"] == "Steam-bent beech"
        assert f["material"]["by"] == "definition-list"
        assert f["shipping weight"]["value"] == "7.4 kg"
        assert got["accounting"]["filled"] == 5
    run(go())


# ------------------------------------------- 9. text that no browser paints


def test_stylesheet_text_is_never_a_value(corpus_site):
    """A Wikipedia infobox inlines a TemplateStyles `<style>` element into the
    cell that needs it, so `textContent` on that cell is three CSS rules
    followed by the value. The 2026-09-08 field test watched `extract_fields`
    answer `Official languages` with 100 percent stylesheet garbage: right row,
    right key, correct provenance, and the value was CSS, with nothing in the
    payload saying anything was wrong.

    Every reader that quotes an element's text is held to it, because they all
    splice the same rule now."""
    async def go():
        _s, page = await _open(corpus_site, "b/xp_infobox_style.html")
        schema = ["official languages", "capital", "population"]
        fresh = await extract_ops.extract_page(page=page, schema=schema)
        assert fresh["fields"]["official languages"]["value"] == \
            "English, Fixturese", fresh["fields"]["official languages"]
        assert fresh["fields"]["population"]["value"] == "4,120"
        assert "mw-parser-output" not in _flat(fresh)
        assert "not a value" not in _flat(fresh)
        # The shipped schema tool, on the same cell.
        legacy = await extract_ops.extract_fields(page=page, fields=schema)
        assert legacy["fields"]["official languages"]["value"] == \
            "English, Fixturese", legacy["fields"]["official languages"]
        assert "mw-parser-output" not in _flat(legacy)
        # And the table reader, which quotes every cell.
        table = await extract_ops.get_table(page=page)
        assert table["table"]["rows"][0] == ["Official languages",
                                             "English, Fixturese"]
        assert "mw-parser-output" not in _flat(table)
    run(go())


# ----------------------------------------------------------- 10. bad params


def test_extract_page_bad_arguments_refuse(corpus_site):
    async def go():
        _s, page = await _open(corpus_site, "b/xp_hint.html")
        with pytest.raises(BadParams) as empty:
            await extract_ops.extract_page(page=page, schema=[])
        assert "['price', 'author']" in str(empty.value)
        with pytest.raises(BadParams) as many:
            await extract_ops.extract_page(
                page=page, schema=[f"f{i}" for i in range(41)])
        assert "41" in str(many.value) and "40" in str(many.value)
        # The caller may raise it as far as the ceiling and no further: a
        # bound the caller sets is not a bound.
        wide = await extract_ops.extract_page(
            page=page, schema=[f"f{i}" for i in range(41)], max_fields=50)
        assert wide["accounting"]["requested"] == 41
        with pytest.raises(BadParams) as ceiling:
            await extract_ops.extract_page(
                page=page, schema=["price"], max_fields=5000)
        assert "200" in str(ceiling.value)
        with pytest.raises(BadParams) as tier:
            await extract_ops.extract_page(
                page=page, schema=["price"], tiers="prose")
        assert "declared" in str(tier.value)
        with pytest.raises(BadParams):
            await extract_ops.extract_page(
                page=page, schema=["price"], location={"nonsense": 1})
    run(go())
