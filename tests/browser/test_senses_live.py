"""Eyes where the DOM is blind: region capture, the pixel cap, and OCR.

Three properties are pinned here and the third is the one that matters
most.

**The cost is reported and enforced.** A capture says what looking at it
costs, computed over the dimensions that came back, and a capture past the
long-edge cap goes to disk with the number and the cheaper route named
rather than riding into the transcript unremarked.

**A region is a first-class target.** Element targeting needs an element,
and the cases this feature exists for often have none: part of a canvas, the
gap an overlay sits in, a chart legend. A rect that runs off the document is
clipped and the clipping is reported.

**Text read out of pixels is never mistaken for the page's text.** It rides
the untrusted-content envelope, it carries a provenance note saying what an
optical recognizer is, it never enters `get_text`, and where no engine can
run the call refuses loudly instead of returning an empty reading.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kitchensink4web import ocr, packs, pagedata
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import BadParams, UnsupportedContent
from kitchensink4web.ops import capture, common, lite
from kitchensink4web.policy import readonly

pytestmark = pytest.mark.browser

needs_ocr = pytest.mark.skipif(
    not ocr.available(),
    reason=f"no OCR engine in this process: {ocr.reason()}")


@pytest.fixture(autouse=True)
def loaded_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "_LOADED",
                        set(packs.PACK_SUMMARIES), raising=False)
    monkeypatch.setenv(common.ENV_DOWNLOAD_DIR, str(tmp_path / "dl"))
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


async def _open(base, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{base}{path}")
    return session, page


def _meta(result):
    return result if isinstance(result, dict) else result.structured_content


# ------------------------------------------------------- cost and region


def test_a_viewport_capture_reports_what_it_costs(fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/")
        meta = _meta(await capture.take_screenshot(page=page))
        estimate = meta["visual_tokens"]["estimate"]
        width = meta["pixels"]["width"]
        height = meta["pixels"]["height"]
        assert estimate == capture.visual_tokens(width, height)
        assert meta["visual_tokens"]["formula"] == "ceil(w/28)*ceil(h/28)"
    run(go())


def test_a_region_is_far_cheaper_than_the_viewport_it_came_from(
        fixture_site):
    """The product's own argument, measured rather than asserted."""
    async def go():
        _s, page = await _open(fixture_site, "/")
        whole = _meta(await capture.take_screenshot(page=page))
        part = _meta(await capture.take_screenshot(
            page=page, target="region",
            rect={"x": 0, "y": 0, "width": 400, "height": 120}))
        assert (part["visual_tokens"]["estimate"]
                < whole["visual_tokens"]["estimate"] / 10)
    run(go())


def test_a_region_running_off_the_document_is_clipped_and_says_so(
        fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/")
        meta = _meta(await capture.take_screenshot(
            page=page, target="region",
            rect={"x": 0, "y": 0, "width": 99999, "height": 99999}))
        assert meta["clipped_to_document"]
        assert "clipped" in meta["clipped_to_document"]
        assert meta["clip"]["width"] < 99999
    run(go())


def test_a_region_entirely_outside_the_document_refuses(fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/")
        with pytest.raises(BadParams) as exc:
            await capture.take_screenshot(
                page=page, target="region",
                rect={"x": 900000, "y": 900000, "width": 10, "height": 10})
        assert "outside this document" in str(exc.value)
        assert "extent" in str(exc.value)
    run(go())


@pytest.mark.parametrize("rect", [
    None, {"x": 0, "y": 0}, {"x": 0, "y": 0, "width": 0, "height": 10},
    {"x": "a", "y": 0, "width": 5, "height": 5},
])
def test_a_bad_rect_refuses_with_the_shape_named(fixture_site, rect):
    async def go():
        _s, page = await _open(fixture_site, "/")
        with pytest.raises(BadParams):
            await capture.take_screenshot(page=page, target="region",
                                          rect=rect)
    run(go())


def test_pad_expands_then_clamps_at_the_document_edge(fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/")
        bare = _meta(await capture.take_screenshot(
            page=page, target="region",
            rect={"x": 100, "y": 100, "width": 50, "height": 50}))
        padded = _meta(await capture.take_screenshot(
            page=page, target="region", pad_px=40,
            rect={"x": 100, "y": 100, "width": 50, "height": 50}))
        assert padded["clip"]["width"] == bare["clip"]["width"] + 80
        assert padded["pad_px"] == 40

        edge = _meta(await capture.take_screenshot(
            page=page, target="region", pad_px=400,
            rect={"x": 0, "y": 0, "width": 50, "height": 50}))
        assert edge["clip"]["x"] == 0
        assert edge["clipped_to_document"]
    run(go())


def test_pad_on_a_viewport_target_refuses_rather_than_being_ignored(
        fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/")
        with pytest.raises(BadParams) as exc:
            await capture.take_screenshot(page=page, pad_px=20)
        assert "pad_px" in str(exc.value)
    run(go())


def test_a_full_page_capture_over_the_cap_spills_with_the_cost_named(
        fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/tall")
        meta = _meta(await capture.take_screenshot(
            page=page, target="full", max_bytes=50_000_000))
        assert meta["inline"] is False
        assert meta["saved_to"]
        assert "visual tokens" in meta["spilled"]
        assert "region" in meta["spilled"]
        assert meta["visual_tokens"]["estimate"] > 1568
    run(go())


# ------------------------------------------------------ the honesty floor


def test_the_completeness_line_names_the_ocr_capability(fixture_site):
    """Whether or not an engine is here, the ledger SAYS which. A flag that
    only speaks when it is true is a flag nobody can rely on."""
    async def go():
        _s, page = await _open(fixture_site, "/canvastext")
        view = await lite.get_page_view(page=page)
        blob = json.dumps(view)
        assert "canvas-rendered regions with no text projection" in blob
        if ocr.available():
            assert "read_image_text reads text out of them here" in blob
        else:
            assert "no OCR engine is available here" in blob
    run(go())


def test_image_borne_text_joins_the_ledger(fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/muteimage")
        view = await lite.get_page_view(page=page)
        blob = json.dumps(view)
        assert "images with no text projection: 1" in blob, blob[-3000:]
    run(go())


@needs_ocr
def test_ocr_reads_text_the_dom_does_not_have(fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/canvastext")
        text = await lite.get_text(page=page)
        assert "402" not in text["text"], "the DOM should not carry it"

        got = await capture.read_image_text(
            page=page, target="region",
            rect={"x": 0, "y": 0, "width": 520, "height": 220})
        joined = " ".join(line["text"] for line in got["lines"]).upper()
        assert "402" in joined, got["lines"]
        for line in got["lines"]:
            assert line["words"] >= 1
            assert set(line["rect"]) == {"x", "y", "width", "height"}
    run(go())


@needs_ocr
def test_ocr_text_rides_the_envelope_and_is_labeled_a_reading(fixture_site):
    """An instruction painted into a canvas must arrive as page data, never
    as bare text in the server's voice."""
    async def go():
        _s, page = await _open(fixture_site, "/canvastext")
        got = await capture.read_image_text(
            page=page, target="region",
            rect={"x": 0, "y": 0, "width": 520, "height": 220})
        assert "KS4WEB-PAGE-DATA" in got["text"]
        assert got["page_data"]["nonce"] in got["text"]
        assert "UNTRUSTED PAGE CONTENT" in got["page_data"]["label"]
        prov = got["provenance"]
        assert prov["source"] == "ocr"
        assert prov["engine"] == ocr.ENGINE_NAME
        assert "no confidence score" in prov["note"]
        assert "confidence" not in json.dumps(got["lines"])
    run(go())


@needs_ocr
def test_ocr_text_never_enters_get_text(fixture_site):
    """The read that says it returns the page's own text must be
    byte-identical whether or not anything read the pixels beside it."""
    async def go():
        _s, page = await _open(fixture_site, "/canvastext")
        before = await lite.get_text(page=page)
        await capture.read_image_text(
            page=page, target="region",
            rect={"x": 0, "y": 0, "width": 520, "height": 220})
        after = await lite.get_text(page=page)
        # The nonce is minted per call by design, so the comparison is of
        # the CONTENT the envelope carries, not of the envelope.
        assert pagedata.unwrap(before["text"]) == pagedata.unwrap(
            after["text"])
        assert "402" not in after["text"]
    run(go())


@needs_ocr
def test_ocr_never_reads_a_masked_secret_field(fixture_site):
    """Run WITHOUT the password vaulted, so this proves the MASK works
    rather than proving the redaction scrub does."""
    from kitchensink4web.policy import credentials
    async def go():
        credentials.VAULT.clear()
        _s, page = await _open(fixture_site, "/canvassecret")
        got = await capture.read_image_text(
            page=page, target="region",
            rect={"x": 0, "y": 0, "width": 560, "height": 220})
        assert got["masked_fields"] >= 1
        blob = json.dumps(got).upper()
        assert "HUNTER2" not in blob
        assert "SECRETVALUE" not in blob
        # The painted text beside the field still reads, so this is a mask
        # rather than a refusal to look at the page.
        joined = " ".join(line["text"] for line in got["lines"]).upper()
        assert "SIGN IN" in joined or "REQUIRED" in joined
    run(go())


def test_read_image_text_refuses_loudly_when_no_engine_can_run(
        fixture_site, monkeypatch):
    """The negative pin. No engine means a refusal that names the reason
    and the route that exists instead, never `lines: []`."""
    monkeypatch.setenv(ocr.ENV_OCR, "off")
    ocr.probe(refresh=True)

    async def go():
        _s, page = await _open(fixture_site, "/canvastext")
        with pytest.raises(UnsupportedContent) as exc:
            await capture.read_image_text(
                page=page, target="region",
                rect={"x": 0, "y": 0, "width": 200, "height": 100})
        message = str(exc.value)
        assert ocr.ENV_OCR in message
        assert "take_screenshot" in message
        assert "get_text" in message
    try:
        run(go())
    finally:
        monkeypatch.delenv(ocr.ENV_OCR, raising=False)
        ocr.probe(refresh=True)


def test_read_image_text_has_no_full_target(fixture_site):
    async def go():
        _s, page = await _open(fixture_site, "/canvastext")
        with pytest.raises(BadParams) as exc:
            await capture.read_image_text(page=page, target="full")
        assert "get_text" in str(exc.value)
    run(go())
