"""The pixel cap and the OCR capability, at the level that needs no browser.

Two things are pinned here. The first is the arithmetic: an image's cost to
the caller is `ceil(w/28) * ceil(h/28)` visual tokens computed over the
dimensions that actually came back, read out of the image header rather than
taken from the rectangle that was requested. The second is the honesty
floor: whether or not an OCR engine exists in this process, the completeness
ledger says which, and `read_image_text` refuses loudly instead of returning
an empty reading when it cannot run.
"""

from __future__ import annotations

import os
import struct
import zlib

import pytest

from kitchensink4web import ocr
from kitchensink4web.ops import capture, common


def _png(width: int, height: int) -> bytes:
    """A real, minimal PNG of the given dimensions."""
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                         8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1))
            + chunk(b"IEND", b""))


# ------------------------------------------------------------ the arithmetic


@pytest.mark.parametrize("w,h,expected", [
    (400, 120, 75),            # an error banner
    (1280, 800, 1334),         # the default viewport
    (1920, 1080, 2691),        # a 1080p viewport
    (28, 28, 1),               # exactly one patch
    (29, 29, 4),               # one pixel over, four patches
    (1, 1, 1),
])
def test_the_formula_is_the_published_one(w, h, expected):
    assert capture.visual_tokens(w, h) == expected


def test_a_region_is_far_cheaper_than_a_viewport():
    """The whole argument for target='region', as a number rather than a
    claim."""
    region = capture.visual_tokens(400, 120)
    viewport = capture.visual_tokens(1280, 800)
    assert viewport / region > 15


def test_dimensions_are_read_out_of_the_bytes():
    assert common.image_dimensions(_png(640, 480)) == (640, 480)
    assert common.image_dimensions(b"not an image at all") is None
    assert common.image_dimensions(b"\x89PNG\r\n\x1a\n") is None


def _meta_of(result):
    """An inline capture returns a ToolResult; a spilled one returns the
    dict. Both carry the same accounting."""
    return (result if isinstance(result, dict)
            else result.structured_content)


def test_the_estimate_is_computed_over_the_returned_dimensions():
    """Pin 3: the number describes the image that came back, never the one
    that was asked for."""
    data = _png(300, 150)
    meta = _meta_of(capture._image_result(data, meta={}, path=None,
                                          max_bytes=None, max_pixels=None))
    assert meta["pixels"] == {"width": 300, "height": 150}
    assert meta["visual_tokens"]["estimate"] == capture.visual_tokens(300,
                                                                     150)
    assert meta["visual_tokens"]["formula"] == "ceil(w/28)*ceil(h/28)"


def test_the_estimate_says_it_is_an_estimate():
    meta = _meta_of(capture._image_result(_png(64, 64), meta={}, path=None,
                                          max_bytes=None, max_pixels=None))
    assert "not a billing meter" in meta["visual_tokens"]["note"]


def test_unreadable_dimensions_give_no_number_rather_than_a_guess():
    block = capture._cost_block(b"\xff\xd8\xff truncated", 1568)
    assert block["visual_tokens"]["estimate"] is None
    assert "guessed" in block["visual_tokens"]["why_not"]


# --------------------------------------------------------------- the cap


def test_over_the_pixel_cap_spills_and_names_the_cost(tmp_path, monkeypatch):
    monkeypatch.setenv(common.ENV_DOWNLOAD_DIR, str(tmp_path))
    monkeypatch.setenv("KS4WEB_SHOT_SPILL_DIR", str(tmp_path))
    data = _png(2400, 300)
    meta = capture._image_result(data, meta={}, path=None,
                                 max_bytes=10_000_000, max_pixels=1568)
    assert meta["inline"] is False
    assert meta["saved_to"]
    assert "2400x300" in meta["spilled"]
    assert "1568" in meta["spilled"]
    assert "region" in meta["spilled"]


def test_under_both_caps_stays_inline():
    result = capture._image_result(_png(800, 600), meta={}, path=None,
                                   max_bytes=10_000_000, max_pixels=1568)
    # An inline return is a ToolResult, not a dict; that is the existing
    # contract and the pixel cap must not have changed it.
    assert not isinstance(result, dict)


def test_a_raised_cap_lets_a_big_image_stay_inline():
    result = capture._image_result(_png(2000, 400), meta={}, path=None,
                                   max_bytes=10_000_000, max_pixels=2576)
    assert not isinstance(result, dict)


def test_the_cap_comes_from_the_env_and_falls_back_loudly(monkeypatch):
    monkeypatch.setenv(capture.ENV_SHOT_EDGE, "900")
    assert capture._edge_cap(None) == 900
    monkeypatch.setenv(capture.ENV_SHOT_EDGE, "not a number")
    assert capture._edge_cap(None) == capture.DEFAULT_MAX_EDGE
    assert capture._edge_cap(2576) == 2576


# ------------------------------------------------------------- clamping


def test_pad_is_clamped_to_the_documented_range():
    assert capture._pad(None) == 0
    assert capture._pad(-40) == 0
    assert capture._pad(10_000) == capture.MAX_PAD_PX
    with pytest.raises(Exception):
        capture._pad("forty")


def test_a_clamped_box_reports_the_clamp():
    clip, note = capture._clamp({"x": -50, "y": -50, "width": 400,
                                 "height": 400}, 300, 300)
    assert clip == {"x": 0, "y": 0, "width": 300, "height": 300}
    assert note and "clipped" in note


def test_a_box_inside_the_document_reports_nothing():
    clip, note = capture._clamp({"x": 10, "y": 10, "width": 100,
                                 "height": 100}, 1000, 1000)
    assert note is None
    assert clip["width"] == 100


# ---------------------------------------------------- the OCR capability


def test_no_confidence_field_anywhere_in_the_ocr_module():
    """Pin 12. The engine has no such number, so the payload must not
    either: a fabricated confidence is worse than none."""
    import pathlib
    src = pathlib.Path(ocr.__file__).read_text(encoding="utf-8")
    body = "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))
    # The word appears in the module's prose explaining its absence. What
    # must not exist is a returned FIELD by that name.
    assert '"confidence"' not in body
    assert "'confidence'" not in body
    assert "confidence=" not in body


def test_the_capability_line_speaks_either_way(monkeypatch):
    monkeypatch.setenv(ocr.ENV_OCR, "off")
    ocr.probe(refresh=True)
    off = ocr.capability_line()
    assert "nothing here reads pixels" in off
    assert ocr.ENV_OCR in off
    assert len(off) < 80, "the ledger line has to be cheap to survive a rung"
    monkeypatch.delenv(ocr.ENV_OCR, raising=False)
    ocr.probe(refresh=True)


def test_the_reason_is_named_on_every_absence(monkeypatch):
    monkeypatch.setenv(ocr.ENV_OCR, "off")
    ok, why = ocr.probe(refresh=True)
    assert ok is False
    assert "off" in why
    monkeypatch.delenv(ocr.ENV_OCR, raising=False)
    ocr.probe(refresh=True)


def test_the_provenance_note_says_what_the_engine_cannot_do():
    note = ocr.PROVENANCE_NOTE
    assert "PIXELS" in note
    assert "no confidence score" in note
    assert "reading" in note


def test_the_timeout_is_bounded_and_survives_a_bad_value(monkeypatch):
    monkeypatch.setenv(ocr.ENV_TIMEOUT, "1200")
    assert ocr._timeout_s() == 1.2
    monkeypatch.setenv(ocr.ENV_TIMEOUT, "garbage")
    assert ocr._timeout_s() == 5.0
    monkeypatch.setenv(ocr.ENV_TIMEOUT, "0")
    assert ocr._timeout_s() >= 0.2


def test_read_raises_rather_than_returning_empty(monkeypatch):
    """The negative pin that matters: an unavailable engine RAISES. It does
    not return `lines: []`, which would read as "there is no text in those
    pixels" — a different claim, and the wrong one."""
    import asyncio
    monkeypatch.setenv(ocr.ENV_OCR, "off")
    ocr.probe(refresh=True)
    try:
        with pytest.raises(ocr.OcrUnavailable):
            asyncio.run(ocr.read(_png(40, 40)))
    finally:
        monkeypatch.delenv(ocr.ENV_OCR, raising=False)
        ocr.probe(refresh=True)


def test_read_image_text_is_classified():
    """Pin 13: the registration gate raises on an unclassified tool, so a
    new tool that forgets the table is caught at startup."""
    from kitchensink4web.policy import readonly
    assert readonly.is_mutating("read_image_text") is False
    assert readonly.read_only_hint("read_image_text") is False


def test_read_image_text_is_in_the_capture_pack():
    from kitchensink4web import packs
    assert "read_image_text" in packs.PLANNED_MEMBERS["capture"]
    assert packs.pack_of("read_image_text") == "capture"
