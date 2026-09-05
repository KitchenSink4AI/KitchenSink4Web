"""The `capture` pack: pixels and documents (DESIGN 2.2), plus `emulate`.

Screenshots are deliberately NOT in lite (author ruling Q2, 2026-09-05):
the thesis is that structured reads beat pixels, and the default surface
carries no pixel path at all. This pack is the explicit opt-in.

Three rules bind everything here:

1. **Media-type correctness is enforced at ONE chokepoint.** Both
   incumbents have a documented failure where a malformed screenshot
   poisons the whole session with a permanent API 400 (playwright-mcp
   #1211 is a PNG returned under image/jpeg). Every code path in this
   module that returns or saves an image goes through `_image_result`,
   which derives the format, the media type, AND the file extension from
   one sniff of the actual bytes. A mismatch is structurally impossible
   and unidentifiable bytes are refused rather than mislabeled.

2. **Secret masking fails CLOSED** (DESIGN 5.3). Secret-tagged and
   payment-tagged fields are masked before any image is returned; if the
   page carries such fields and the mask cannot be applied on the current
   code path, the screenshot is refused, never returned unmasked.

3. **Hard byte cap with spill-to-file.** An image over the inline cap
   lands in the sandbox-governed spill directory and the payload carries
   the path, so an oversized capture costs tens of tokens instead of
   flooding the transcript.

Env vars this module adds (for the Q11a docs-pass ruling):
KS4WEB_SHOT_MAX_BYTES (inline cap, default 700000).
"""

from __future__ import annotations

import json as _json
import os
import time

from ..engine import lanes
from ..errors import BadParams, CredentialRefused, LaneUnsupported
from ..policy import engine as _policy
from . import act as _act
from . import common

ENV_SHOT_MAX = "KS4WEB_SHOT_MAX_BYTES"

#: The fields a screenshot masks: the secret family (never read at all) plus
#: the payment family (gated, and value-bearing on screen). One selector so
#: the projection's classification and the pixel masking cannot drift.
MASK_CSS = (
    'input[type="password"], '
    'input[autocomplete*="current-password" i], '
    'input[autocomplete*="new-password" i], '
    'input[autocomplete*="one-time-code" i], '
    'input[autocomplete*="cc-number" i], '
    'input[autocomplete*="cc-exp" i], '
    'input[autocomplete*="cc-csc" i]'
)


def _inline_cap(max_bytes: int | None) -> int:
    if max_bytes:
        return max(1024, int(max_bytes))
    try:
        return max(1024, int(os.environ.get(ENV_SHOT_MAX, "700000")))
    except ValueError:
        return 700000


def _image_result(data: bytes, *, meta: dict, path: str | None,
                  max_bytes: int | None):
    """THE media-type chokepoint. Every image leaves through here."""
    fmt, mime = common.sniff_image(data)
    meta = {**meta, "format": fmt, "media_type": mime, "bytes": len(data)}
    cap = _inline_cap(max_bytes)
    if path or len(data) > cap:
        out = path or str(common.spill_dir()
                          / f"shot_{common.stamp()}.{fmt}")
        saved = common.write_bytes_file(out, data, "save screenshot")
        meta["saved_to"] = saved
        meta["inline"] = False
        if not path:
            meta["spilled"] = (
                f"the image is {len(data):,} bytes against the "
                f"{cap:,}-byte inline cap, so it was written to disk "
                f"instead of the transcript")
        return meta
    from fastmcp.tools.tool import ToolResult
    from fastmcp.utilities.types import Image
    from .. import envelope
    meta["inline"] = True
    payload = envelope.success(meta)
    return ToolResult(
        content=[Image(data=data, format=fmt).to_image_content(),
                 _json.dumps(payload, ensure_ascii=False)],
        structured_content=payload)


async def take_screenshot(
    page: str,
    target: str = "viewport",
    location: dict | None = None,
    format: str = "png",
    quality: int | None = None,
    max_bytes: int | None = None,
    path: str | None = None,
) -> dict:
    """Capture the viewport, the full page, or one element as an image whose
    reported media type is derived from the actual bytes, never from the
    request, so a mislabeled image can never poison the session. Returns
    the image inline under a byte cap and spills larger captures to a file
    in the scoped directory with the path named. Password, one-time-code,
    and payment fields are masked before capture, and if the page carries
    such fields where masking cannot be applied the capture refuses rather
    than returning them unmasked. Structured reads are cheaper than pixels;
    this exists for canvas regions, visual checks, and the record.
    """
    if target not in ("viewport", "full", "element"):
        raise BadParams(
            f"unknown target {target!r}: the targets are 'viewport', "
            f"'full', and 'element' (element needs a location).")
    if format not in ("png", "jpeg"):
        raise BadParams(
            f"unknown format {format!r}: the formats are 'png' and 'jpeg'.")
    if quality is not None and format != "jpeg":
        raise BadParams(
            "quality applies to jpeg only; png is lossless. Either drop "
            "quality or ask for format='jpeg'.")
    sess, record = common.locate(page)
    p = record.page

    # Masking, fail closed. Count the fields FIRST so a mask failure on a
    # page that has any is a refusal rather than an unmasked return.
    secret_count = await p.locator(MASK_CSS).count()
    masks = [p.locator(MASK_CSS)] if secret_count else []

    kwargs: dict = {"type": format}
    if quality is not None:
        kwargs["quality"] = max(0, min(100, int(quality)))
    if masks:
        kwargs["mask"] = masks

    clip = None
    if target == "element":
        if not location:
            raise BadParams(
                "target='element' needs a location naming the element, for "
                "example {'ref': 'e12'} or {'css': '#chart'}.")
        resolved = await _act.resolve(sess, record, location,
                                      tool="take_screenshot")
        box = await resolved["handle"].bounding_box()
        if not box or box["width"] < 1 or box["height"] < 1:
            raise BadParams(
                "the located element has no visible box to capture; it may "
                "be hidden or zero-sized. Verify with get_page_view.")
        # Clip through page.screenshot rather than element.screenshot so
        # the mask parameter applies on every path (fail-closed masking).
        clip = {k: box[k] for k in ("x", "y", "width", "height")}
        kwargs["clip"] = clip
    elif target == "full":
        kwargs["full_page"] = True

    started = time.monotonic()
    try:
        data = await p.screenshot(**kwargs)
    except TypeError as exc:
        if masks:
            raise CredentialRefused(
                f"this page carries {secret_count} secret or payment "
                f"field(s) and the mask could not be applied on this code "
                f"path ({str(exc)[:120]}), so the screenshot is refused "
                f"rather than returned unmasked. Capture a region without "
                f"those fields, or read the page structurally instead.")
        raise
    meta = {
        "page": record.handle, "session": sess.session_id,
        "url": p.url, "target": target,
        "masked_fields": secret_count,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
    if clip:
        meta["clip"] = clip
    return _image_result(data, meta=meta, path=path, max_bytes=max_bytes)


async def export_pdf(
    page: str,
    path: str | None = None,
    landscape: bool = False,
    scale: float = 1.0,
) -> dict:
    """Render the page to a PDF file and return the saved path, the byte
    count, and the elapsed time, verified to be a real PDF before anything
    is reported. Runs on headless Chromium at full speed and on Firefox
    over BiDi at a measured ~45x cost, which the result names honestly
    when it applies; a lane or mode that cannot render PDF refuses with
    the lanes that can. The file lands in the scoped downloads directory
    unless a path is named, checked against KS4WEB_ALLOWED_ROOTS.
    """
    sess, record = common.locate(page)
    cost = lanes.capability(sess.spec, "pdf_export")
    started = time.monotonic()
    try:
        data = await record.page.pdf(landscape=landscape,
                                     scale=max(0.1, min(2.0, float(scale))))
    except Exception as exc:
        detail = str(exc).splitlines()[0][:200]
        raise LaneUnsupported(
            f"[lane {sess.spec.label}] PDF rendering failed here: {detail}. "
            f"PDF export works on headless Chromium (the lane A default) "
            f"and on Firefox over BiDi (slowly). A headed window cannot "
            f"render PDF; reopen headless, or save the page with "
            f"save_page instead.") from exc
    if not data.startswith(b"%PDF"):
        raise LaneUnsupported(
            f"[lane {sess.spec.label}] the driver returned "
            f"{len(data)} bytes that are not a PDF, so nothing was saved "
            f"or reported under that label. Retry, or use save_page.")
    out = path or str(common.downloads_dir() / f"page_{common.stamp()}.pdf")
    saved = common.write_bytes_file(out, data, "export PDF")
    result = {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "saved_to": saved, "bytes": len(data),
        "media_type": "application/pdf",
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
    if cost == "cost":
        result["lane_cost"] = lanes.CAPABILITIES["pdf_export"]["message"]
    return result


async def save_page(
    page: str,
    path: str | None = None,
    format: str = "mhtml",
) -> dict:
    """Save the page to disk for the record: MHTML (the whole page with its
    subresources in one file, Chromium lanes only, via the DevTools
    snapshot) or plain HTML (the current serialized DOM, any lane).
    Returns the saved path, the byte count, and the format actually
    written. On a non-Chromium lane an MHTML request refuses loudly and
    names both the lanes that support it and the html fallback, rather
    than degrading silently. Files land in the scoped downloads directory
    unless a path is named, checked against KS4WEB_ALLOWED_ROOTS.
    """
    if format not in ("mhtml", "html"):
        raise BadParams(
            f"unknown format {format!r}: the formats are 'mhtml' (whole "
            f"page with subresources, Chromium lanes) and 'html' (the "
            f"serialized DOM, any lane).")
    sess, record = common.locate(page)
    if format == "mhtml":
        if sess.spec.engine != "chromium":
            raise LaneUnsupported(
                f"[lane {sess.spec.label}] MHTML capture rides on the "
                f"Chromium DevTools snapshot and this lane is "
                f"{sess.spec.engine}. Relaunch on lane A (bundled Chromium) "
                f"or lane B chrome/msedge, or use save_page(format='html') "
                f"here.")
        cdp = await record.page.context.new_cdp_session(record.page)
        try:
            res = await cdp.send("Page.captureSnapshot", {"format": "mhtml"})
        finally:
            try:
                await cdp.detach()
            except Exception:
                pass
        body = res.get("data", "")
        out = path or str(common.downloads_dir()
                          / f"page_{common.stamp()}.mhtml")
        saved = common.write_text_file(out, body, "save page as MHTML")
    else:
        body = await record.page.content()
        out = path or str(common.downloads_dir()
                          / f"page_{common.stamp()}.html")
        saved = common.write_text_file(out, body, "save page as HTML")
    return {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "saved_to": saved, "format": format,
        "bytes": len(body.encode("utf-8", "replace")),
    }


async def emulate(
    page: str,
    viewport: dict | None = None,
    color_scheme: str | None = None,
    reduced_motion: str | None = None,
    media: str | None = None,
) -> dict:
    """Change what the page believes about its environment: viewport size
    ({'width': .., 'height': ..}), preferred color scheme ('light', 'dark',
    or 'no-preference'), reduced motion ('reduce' or 'no-preference'), and
    media type ('screen' or 'print'). Returns what was applied and the
    page's own report of the resulting media state, read back rather than
    assumed. Locale and timezone are launch-time properties of a session
    and cannot be changed here; reopen the session for those. Emulation
    mutates page state, so this tool is absent under read-only mode.
    """
    sess, record = common.locate(page)
    if not any((viewport, color_scheme, reduced_motion, media)):
        raise BadParams(
            "emulate needs at least one of viewport, color_scheme, "
            "reduced_motion, or media. Locale and timezone are set when a "
            "session opens, not here.")
    _policy.approve(_policy.ActionRequest(
        tool="emulate", kind="act", session=sess.session_id,
        page=record.handle, url=record.page.url,
        args={"viewport": viewport, "color_scheme": color_scheme,
              "reduced_motion": reduced_motion, "media": media},
        summary=f"emulate on {record.handle}"))
    applied: dict = {}
    if viewport:
        if not (isinstance(viewport, dict)
                and viewport.get("width") and viewport.get("height")):
            raise BadParams(
                "viewport takes {'width': N, 'height': N} in CSS pixels.")
        await record.page.set_viewport_size(
            {"width": int(viewport["width"]),
             "height": int(viewport["height"])})
        applied["viewport"] = {"width": int(viewport["width"]),
                               "height": int(viewport["height"])}
    kwargs = {}
    if color_scheme is not None:
        if color_scheme not in ("light", "dark", "no-preference"):
            raise BadParams(
                "color_scheme is 'light', 'dark', or 'no-preference'.")
        kwargs["color_scheme"] = color_scheme
    if reduced_motion is not None:
        if reduced_motion not in ("reduce", "no-preference"):
            raise BadParams(
                "reduced_motion is 'reduce' or 'no-preference'.")
        kwargs["reduced_motion"] = reduced_motion
    if media is not None:
        if media not in ("screen", "print"):
            raise BadParams("media is 'screen' or 'print'.")
        kwargs["media"] = media
    if kwargs:
        await record.page.emulate_media(**kwargs)
        applied.update(kwargs)
    state = await record.page.evaluate(
        "() => ({dark: matchMedia('(prefers-color-scheme: dark)').matches,"
        " reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,"
        " print: matchMedia('print').matches,"
        " width: innerWidth, height: innerHeight})")
    return {
        "page": record.handle, "session": sess.session_id,
        "applied": applied,
        "page_reports": state,
    }


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (take_screenshot, export_pdf, save_page, emulate)
