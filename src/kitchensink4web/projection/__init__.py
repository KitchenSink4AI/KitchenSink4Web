"""The cheap first read: extraction, ranking, pricing, and the ladder.

DESIGN 3. This package is the product, and everything else in the server is
downstream of it. The claim it implements, stated with the companion clause it
is never allowed to ship without: **a cheap first read plus a cheap targeted
follow-up.** The projection makes the model know what string to search for,
and `find_elements` retrieves it for tens of tokens. "One read and you can act
on anything" is banned copy, because an arbitrary in-prose link on a page
holding 2,858 of them is not one-readable at any budget.

Four modules, and the split is the design's:

- `extract.js` runs one depth-first walk in the page and produces every fact.
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

__all__ = ["EXTRACT_JS", "CLOSED_SHADOW_HOOK", "Projection", "project",
           "extract", "read_page", "ntok", "ENCODING_NAME", "RUNGS"]

EXTRACT_JS = (Path(__file__).parent / "extract.js").read_text(encoding="utf-8")

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


async def extract(page) -> dict:
    """Run the in-page pass. One evaluate, one walk, one style per element."""
    return await page.evaluate(EXTRACT_JS)


async def read_page(page, meta: dict, budget: int = 5000,
                    view: str = "auto") -> Projection:
    """Extract and project in one call, which is what `get_page_view` does."""
    data = await extract(page)
    return project(data, meta, budget=budget, view=view)
