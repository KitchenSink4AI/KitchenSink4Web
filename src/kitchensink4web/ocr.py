"""Reading text out of pixels, and being honest about not being able to.

Image-borne error text and canvas-painted text are invisible to every DOM
read. The projection already counts the blind spot; this reads it where the
machine can, and says so plainly where it cannot.

**The engine is the one already on the machine.** Windows ships an OCR
engine inside the operating system, reachable from Python through the
PyWinRT projection packages (MIT, wheels, no native install, no subprocess,
no network, no API key). Tesseract was evaluated and declined: it is a
native binary the user installs separately plus tens of megabytes of
language data, invoked per call through a subprocess, on a product that
does not even bundle a browser. The one thing it has that Windows OCR lacks
is a confidence number, and a confidence number is not worth a native
install.

**The floor is the honest flag, not the engine.** Whether or not OCR is
available, a reader is told that pixels carry text and whether anything read
them. That is what makes a false capability flag safe: it is a stated
absence rather than a silent one. Non-Windows is therefore an explicit,
named condition, never a silent empty result.

**There is no confidence score and none is invented.** The Windows engine's
documented surface is lines, words, and bounding rectangles. `OcrWord`
carries `text` and `bounding_rect` and nothing else; `OcrResult` carries
`lines`, `text`, and `text_angle`. Verified against the shipped type stubs
of the pinned packages, not inferred from documentation. So this module
returns word counts and geometry, which the engine does report, plus a
provenance note in words. A fabricated confidence would be worse than none,
and emitting `confidence: null` would invite a reader to treat its absence
as a degraded reading rather than an engine that never had the concept.

Env vars: KS4WEB_OCR (`off` disables it even where available),
KS4WEB_OCR_TIMEOUT_MS (hard per-call wall clock, default 5000).
"""

from __future__ import annotations

import asyncio
import os
import sys

ENV_OCR = "KS4WEB_OCR"
ENV_TIMEOUT = "KS4WEB_OCR_TIMEOUT_MS"

ENGINE_NAME = "Windows.Media.Ocr"

#: The extra that carries the engine, named in every refusal so a reader
#: who can fix the absence knows the exact string to type.
EXTRA = "kitchensink4web[ocr]"

#: The sentence attached to every OCR payload. It is the deliverable as much
#: as the text is: it labels the provenance, states the limits, and refuses
#: to let a reading be mistaken for the page's own text.
PROVENANCE_NOTE = (
    "this text was read from PIXELS by an optical character recognizer, not "
    "from the page's own DOM. It can misread characters, drop lines, and "
    "reorder text. This engine reports no confidence score, so none is "
    "given here; the word counts and bounding boxes are what it does "
    "report. Treat every string as a reading, not as the page's text.")

_probe: tuple[bool, str] | None = None


def _timeout_s() -> float:
    try:
        return max(0.2, int(os.environ.get(ENV_TIMEOUT, "5000")) / 1000)
    except ValueError:
        return 5.0


def _probe_engine() -> tuple[bool, str]:
    """(available, reason). The reason is stated whichever way it goes."""
    if (os.environ.get(ENV_OCR) or "").strip().lower() == "off":
        return (False, f"{ENV_OCR}=off in this process, so text is not read "
                       f"out of pixels here even though the machine could")
    if sys.platform != "win32":
        return (False, f"this build reads text out of pixels through "
                       f"{ENGINE_NAME}, which is part of Windows, and this "
                       f"process is running on {sys.platform!r}. No OCR "
                       f"engine is available here")
    try:
        from winrt.windows.media.ocr import OcrEngine
    except ImportError:
        return (False, f"the optional OCR extra is not installed in this "
                       f"environment (pip install {EXTRA}), so no engine is "
                       f"available to read text out of pixels")
    try:
        engine = OcrEngine.try_create_from_user_profile_languages()
    except Exception as exc:                     # a broken projection
        return (False, f"the {ENGINE_NAME} engine could not be constructed "
                       f"({type(exc).__name__}), so no text was read out of "
                       f"the pixels")
    if engine is None:
        return (False, f"{ENGINE_NAME} is present but no OCR language pack "
                       f"on this device matches the user profile languages, "
                       f"so the engine could not be created. Windows "
                       f"Settings > Time & language > Language & region "
                       f"installs one")
    return (True, f"{ENGINE_NAME}, language "
                  f"{engine.recognizer_language.language_tag}")


def probe(*, refresh: bool = False) -> tuple[bool, str]:
    """(available, reason), cached. A capability is a launch-time property
    of the machine, so it is asked once and remembered."""
    global _probe
    if _probe is None or refresh:
        _probe = _probe_engine()
    return _probe


def available() -> bool:
    return probe()[0]


def reason() -> str:
    return probe()[1]


def languages() -> list[str]:
    """Every OCR language this device carries, or an empty list."""
    if sys.platform != "win32":
        return []
    try:
        from winrt.windows.media.ocr import OcrEngine
        return [lang.language_tag
                for lang in OcrEngine.available_recognizer_languages]
    except Exception:
        return []


def max_image_dimension() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.media.ocr import OcrEngine
        return int(OcrEngine.max_image_dimension)
    except Exception:
        return None


class OcrUnavailable(Exception):
    """Raised by `read` when no engine can run. Carries the named reason;
    the caller turns it into the tool's refusal."""


class OcrLanguageMissing(OcrUnavailable):
    """A specific requested language is not on this device."""


async def _decode(png: bytes):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import (DataWriter,
                                               InMemoryRandomAccessStream)
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    return await decoder.get_software_bitmap_async()


def _engine_for(language: str | None):
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    if not language:
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrLanguageMissing(probe(refresh=True)[1])
        return engine
    try:
        wanted = Language(language)
    except Exception as exc:
        raise OcrLanguageMissing(
            f"{language!r} is not a language tag this system recognizes "
            f"({type(exc).__name__}). Use a BCP-47 tag such as 'en-US'. "
            f"This device carries {languages()}.") from exc
    engine = OcrEngine.try_create_from_language(wanted)
    if engine is None:
        raise OcrLanguageMissing(
            f"no OCR language pack for {language!r} is installed on this "
            f"device, so nothing was read. The packs present are "
            f"{languages()}; Windows Settings > Time & language installs "
            f"more.")
    return engine


async def _recognize(png: bytes, language: str | None) -> dict:
    bitmap = await _decode(png)
    engine = _engine_for(language)
    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        words = list(line.words)
        rects = [w.bounding_rect for w in words]
        if rects:
            left = min(r.x for r in rects)
            top = min(r.y for r in rects)
            right = max(r.x + r.width for r in rects)
            bottom = max(r.y + r.height for r in rects)
            rect = {"x": round(left, 1), "y": round(top, 1),
                    "width": round(right - left, 1),
                    "height": round(bottom - top, 1)}
        else:
            rect = None
        lines.append({"text": line.text, "rect": rect, "words": len(words)})
    angle = result.text_angle
    return {
        "lines": lines,
        "language": engine.recognizer_language.language_tag,
        # The engine's own reading of how rotated the text is. Reported
        # because a non-zero angle is the usual explanation for a garbled
        # line, and withholding it leaves the reader with no account of it.
        "text_angle": (round(float(angle), 2) if angle is not None else None),
    }


async def read(png: bytes, *, language: str | None = None) -> dict:
    """Read text out of PNG bytes. Raises `OcrUnavailable` when no engine
    can run and `TimeoutError` when the hard wall clock expires."""
    ok, why = probe()
    if not ok:
        raise OcrUnavailable(why)
    out = await asyncio.wait_for(_recognize(png, language), _timeout_s())
    out["provenance"] = {
        "source": "ocr",
        "engine": ENGINE_NAME,
        "language": out["language"],
        "note": PROVENANCE_NOTE,
    }
    return out


#: The short form of each absence, for the completeness line. The full
#: sentence lives in `reason()` and in the refusal; a ledger line that costs
#: forty tokens to explain a capability is a line a budgeted read has to
#: drop, and a dropped honesty flag is the failure this whole feature is
#: written against.
_SHORT_REASONS = (
    ("=off", f"{ENV_OCR}=off"),
    ("part of Windows", "not Windows"),
    ("optional OCR extra", "extra not installed"),
    ("language pack", "no OCR language pack"),
)


def short_reason() -> str:
    why = probe()[1]
    for needle, short in _SHORT_REASONS:
        if needle in why:
            return short
    return "no engine"


def capability_line() -> str:
    """One SHORT clause for the completeness ledger, whichever way it falls.

    It is short on purpose. A budgeted read drops what does not fit, and a
    capability flag that costs forty tokens is the first thing to go."""
    if probe()[0]:
        return "read_image_text reads text out of them here"
    return f"nothing here reads pixels ({short_reason()})"
