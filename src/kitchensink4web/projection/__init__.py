"""The cheap first read: extraction, ranking, pricing, and the ladder.

DESIGN 3. This package is the product, and everything else in the server is
downstream of it. The claim it implements, stated with the companion clause it
is never allowed to ship without: **a cheap first read plus a cheap targeted
follow-up.** The projection makes the model know what string to search for,
and `find_elements` retrieves it for tens of tokens. "One read and you can act
on anything" is banned copy, because an arbitrary in-prose link on a page
holding 2,858 of them is not one-readable at any budget.

Six modules, and the split is the design's:

- `extract.js` runs one depth-first walk in the page and produces every fact,
  including the anchor descriptor for every unit it will print.
- `find.js` is the targeted follow-up, and it is deliberately a SEPARATE pass:
  the extractor caps what it returns at 300 affordances, which is right for an
  orientation and fatal for a search, since the link the flagship example
  names sits past the two thousandth in-prose link on that page.
- `text.js` is bounded prose extraction with hidden content counted.
- `ranker.py` selects affordances by per-class quota with guaranteed floors.
- `meter.py` prices and accounts, and owns the ledger the completeness block
  renders.
- `render.py` builds the eight blocks and runs the degradation ladder.

**This package never imports playwright.** It takes a page-like object with an
`evaluate` method, which keeps the projection testable against a recorded
extraction and keeps the engine seam honest.
"""

from __future__ import annotations

import secrets as _secrets
from pathlib import Path

from .meter import ENCODING_NAME, ntok
from .render import RUNGS, Projection, project

__all__ = ["EXTRACT_JS", "FIND_JS", "TEXT_JS", "VISIBILITY_JS", "PAYMENT_JS",
           "ACTIVATION_JS",
           "CLOSED_SHADOW_HOOK", "INSTRUMENT_KEY", "instrument",
           "Projection", "project", "extract", "find", "read_text",
           "read_page", "ntok", "ENCODING_NAME", "RUNGS"]

_HERE = Path(__file__).parent

#: The splice markers. A source file names where the shared block goes; the
#: block itself exists once on disk.
_VIS_MARK = "// @@KS4WEB_VISIBILITY@@"
_INSTR_MARK = "// @@KS4WEB_INSTRUMENT@@"
_PAY_MARK = "// @@KS4WEB_PAYMENT@@"
_ACT_MARK = "// @@KS4WEB_ACTIVATION@@"

#: THE ONE HIDDEN-DETECTION SOURCE (gauntlet 2 H2/H3/M4/L2, 2026-09-06).
#: `hiddenReason` used to exist three times, in `extract.js`, `find.js`, and
#: `text.js`, and every gap between the copies was a finding: an element the
#: projection counted as hidden came back from `find_elements` as an in-view
#: match, and a payload inside a collapsed `<details>` arrived as main text
#: while the ledger said nothing was withheld. The rule now lives in
#: `visibility.js` and is spliced into every consumer at load, so a technique
#: added there is added everywhere at once.
VISIBILITY_JS = (_HERE / "visibility.js").read_text(encoding="utf-8")

#: THE ONE PAYMENT-SHAPE SOURCE (re-attack R3, 2026-09-06). Same story one
#: classification along: the "is this a card field" rule had four in-page
#: copies and all four asked only about `autocomplete`, so a page that
#: declares no token at all was unclassified everywhere at once. The rule now
#: lives in `payment.js` and is spliced into every consumer at load.
PAYMENT_JS = (_HERE / "payment.js").read_text(encoding="utf-8")

#: THE ONE ACTIVATION-TARGET SOURCE (re-attack 2 C1, 2026-09-06). Same story
#: one question earlier: every classifier in the build modelled the element
#: the tool TOUCHES, and the browser routes a click on a `<label>` to the
#: control it labels. Clicking `<label for=submitButton>` submitted a
#: card-carrying form with no class computed. "Which element does this
#: activate" now has one implementation and every consumer splices it.
ACTIVATION_JS = (_HERE / "activation.js").read_text(encoding="utf-8")

#: The per-process instrument secret. It is baked into the injected script
#: SOURCES, never passed as an evaluate argument and never written into the
#: page, because a Playwright script's source is not readable from page
#: script while an argument travels through main-world deserialization.
INSTRUMENT_SECRET = _secrets.token_hex(24)

#: The window property the instrument channel answers on. Randomized per
#: process so the name is not a constant to grep for, though the design does
#: not pretend the channel's PRESENCE is undetectable.
INSTRUMENT_KEY = "__ks4web_" + _secrets.token_hex(8)

#: Installed as an init script before any page script runs. A closed shadow
#: root is genuinely unreachable afterward, so the only honest way to report
#: "0 closed (unreachable by any tool)" rather than guessing is to count them
#: as they are created. A blind agent named that two-layer phrasing the most
#: useful line in the whole projection, because it separates "I did not look"
#: from "no one can look" where most tools collapse both into a confident zero.
#: Gauntlet 2 (H4) then falsified the count two ways, so the counter and every
#: other piece of in-page state moved into the closure this script owns.
CLOSED_SHADOW_HOOK = (
    (_HERE / "instrument.js").read_text(encoding="utf-8")
    .replace("__KS4WEB_KEY__", INSTRUMENT_KEY)
    .replace("__KS4WEB_SECRET__", INSTRUMENT_SECRET))

#: The prelude every injected script opens with: reach the instrument state or
#: refuse. There is no window fallback on purpose. A fallback would be a
#: page-writable object wearing the channel's name, which is the defect this
#: whole mechanism exists to remove, so a document the init script never
#: reached returns a typed error and the Python side says so.
INSTRUMENT_PRELUDE = (
    f'  const KS = (typeof window["{INSTRUMENT_KEY}"] === "function")\n'
    f'    ? window["{INSTRUMENT_KEY}"]("{INSTRUMENT_SECRET}") : null;\n'
    f"  if (!KS) return {{ error: 'INSTRUMENT_MISSING' }};\n")


def instrument(source: str, *, visibility: str | None = None) -> str:
    """Splice the shared blocks into one injected script source.

    `visibility` overrides the shared block, which exists for exactly one
    caller: the latency gate's control arm runs an OLDER `extract.js` in the
    live page, and that source has to carry the visibility block IT was
    written against while still reaching THIS process's instrument channel."""
    if _VIS_MARK in source:
        source = source.replace(
            _VIS_MARK, VISIBILITY_JS if visibility is None else visibility)
    if _PAY_MARK in source:
        source = source.replace(_PAY_MARK, PAYMENT_JS)
    if _ACT_MARK in source:
        source = source.replace(_ACT_MARK, ACTIVATION_JS)
    if _INSTR_MARK in source:
        source = source.replace(_INSTR_MARK, INSTRUMENT_PRELUDE)
    return source


EXTRACT_JS = instrument((_HERE / "extract.js").read_text(encoding="utf-8"))
FIND_JS = instrument((_HERE / "find.js").read_text(encoding="utf-8"))
TEXT_JS = instrument((_HERE / "text.js").read_text(encoding="utf-8"))


def _checked(data: dict) -> dict:
    """Refuse loudly when the instrument channel is not in this document.

    There is deliberately no page-side fallback: a fallback would be a
    page-writable object wearing the channel's name, which is the whole defect
    the channel removes. A document the init script never reached is a real
    condition (a page adopted from outside this server's context, a driver
    that dropped the script) and it gets a typed refusal rather than a
    silently weaker read."""
    if isinstance(data, dict) and data.get("error") == "INSTRUMENT_MISSING":
        from ..errors import Conflict
        raise Conflict(
            "this page was not instrumented by this server, so the read has "
            "no registry to mint refs into and no honest closed-shadow-root "
            "count to report. Open the page through manage_tabs or navigate "
            "in this session; a document adopted from outside it cannot be "
            "read safely.")
    return data


async def extract(page, root: str | None = None,
                  pin: str | None = None) -> dict:
    """Run the in-page pass. One evaluate, one walk, one style per element.

    `pin` is one in-page ref that is collected even past the extractor's
    300-affordance return cap. The acting path passes the ref it is about to
    resolve, so an element `find_elements` located past the cap is in the
    candidate list the rebind ladder searches. It widens the haystack only:
    the ladder still matches by anchor key and still refuses."""
    return _checked(await page.evaluate(
        EXTRACT_JS, {"root": root, "pin": pin}))


async def find(page, query: str, kind: str = "auto", limit: int = 20,
               root: str | None = None, role: str | None = None,
               shadow: bool = True) -> dict:
    """The targeted follow-up pass, uncapped in what it searches."""
    return _checked(await page.evaluate(
        FIND_JS, {"query": query, "kind": kind, "limit": limit, "root": root,
                  "role": role, "shadow": shadow}))


async def read_text(page, root: str | None = None, start_index: int = 0,
                    max_chars: int = 20000,
                    include_hidden: bool = False) -> dict:
    """Bounded prose, with what was stripped counted rather than dropped."""
    return _checked(await page.evaluate(TEXT_JS, {
        "root": root, "start_index": start_index, "max_chars": max_chars,
        "include_hidden": include_hidden}))


async def read_page(page, meta: dict, budget: int = 5000,
                    view: str = "auto", root: str | None = None,
                    absorb=None, mode: str = "auto") -> Projection:
    """Extract and project in one call, which is what `get_page_view` does.

    `absorb` is the anchor layer's hook, called with the raw extraction before
    anything is rendered. It rewrites every unit's per-read extractor id into
    the session's sticky ref, so `e12` on read one is still `e12` on read
    three and the renderer never learns the difference."""
    data = await extract(page, root=root)
    if data.get("error"):
        return data
    if absorb is not None:
        absorb(data)
    return project(data, meta, budget=budget, view=view, mode=mode)
