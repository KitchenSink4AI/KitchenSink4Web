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

from pathlib import Path

from .meter import ENCODING_NAME, ntok
from .render import RUNGS, Projection, project

__all__ = ["EXTRACT_JS", "FIND_JS", "TEXT_JS", "CLOSED_SHADOW_HOOK",
           "Projection", "project", "extract", "find", "read_text",
           "read_page", "ntok", "ENCODING_NAME", "RUNGS"]

_HERE = Path(__file__).parent
EXTRACT_JS = (_HERE / "extract.js").read_text(encoding="utf-8")
FIND_JS = (_HERE / "find.js").read_text(encoding="utf-8")
TEXT_JS = (_HERE / "text.js").read_text(encoding="utf-8")

#: Installed as an init script before any page script runs. A closed shadow
#: root is genuinely unreachable afterward, so the only honest way to report
#: "0 closed (unreachable by any tool)" rather than guessing is to count them
#: as they are created. A blind agent named that two-layer phrasing the most
#: useful line in the whole projection, because it separates "I did not look"
#: from "no one can look" where most tools collapse both into a confident zero.
CLOSED_SHADOW_HOOK = """
(() => {
  if (window.__ks4web_closed_shadow !== undefined) return;
  window.__ks4web_closed_shadow = 0;
  const original = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (init) {
    if (init && init.mode === 'closed') window.__ks4web_closed_shadow++;
    return original.apply(this, arguments);
  };
})();
"""


async def extract(page, root: str | None = None) -> dict:
    """Run the in-page pass. One evaluate, one walk, one style per element."""
    return await page.evaluate(EXTRACT_JS, {"root": root})


async def find(page, query: str, kind: str = "auto", limit: int = 20,
               root: str | None = None, role: str | None = None,
               shadow: bool = True) -> dict:
    """The targeted follow-up pass, uncapped in what it searches."""
    return await page.evaluate(
        FIND_JS, {"query": query, "kind": kind, "limit": limit, "root": root,
                  "role": role, "shadow": shadow})


async def read_text(page, root: str | None = None, start_index: int = 0,
                    max_chars: int = 20000,
                    include_hidden: bool = False) -> dict:
    """Bounded prose, with what was stripped counted rather than dropped."""
    return await page.evaluate(TEXT_JS, {
        "root": root, "start_index": start_index, "max_chars": max_chars,
        "include_hidden": include_hidden})


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
