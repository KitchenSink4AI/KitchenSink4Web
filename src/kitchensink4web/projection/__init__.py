"""The cheap first read: extraction, ranking, pricing, and the ladder.

DESIGN 3. This package is the product, and everything else in the server is
downstream of it. The claim it implements, stated with the companion clause it
is never allowed to ship without: **a cheap first read plus a cheap targeted
follow-up.** The projection makes the model know what string to search for,
and `find_elements` retrieves it for tens of tokens. "One read and you can act
on anything" is banned copy, because an arbitrary in-prose link on a page
holding 2,858 of them is not one-readable at any budget.

The modules, and the split is the design's:

- `extract.js` runs one depth-first walk in the page and produces every fact,
  including the anchor descriptor for every unit it will print.
- `find.js` is the targeted follow-up, and it is deliberately a SEPARATE pass:
  the extractor caps what it returns at 300 affordances, which is right for an
  orientation and fatal for a search, since the link the flagship example
  names sits past the two thousandth in-prose link on that page.
- `text.js` is bounded prose extraction with hidden content counted.
- `article.js` is the article-shaped read: a Readability-class scorer, the
  body in reading order, the chrome excluded AND counted by reason, and a
  refusal on a page that is an application rather than a document.
- `aria.js` is the one state source both reads splice, so an affordance
  describes itself identically whichever tool found it.
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

__all__ = ["EXTRACT_JS", "FIND_JS", "TEXT_JS", "ARTICLE_JS", "VISIBILITY_JS",
           "PAYMENT_JS", "ACTIVATION_JS", "ARIA_JS", "HREF_JS",
           "CLOSED_SHADOW_HOOK", "INSTRUMENT_KEY", "instrument",
           "Projection", "project", "extract", "find", "read_text",
           "read_article", "read_page", "stitch", "ntok",
           "ENCODING_NAME", "RUNGS"]

_HERE = Path(__file__).parent

#: The splice markers. A source file names where the shared block goes; the
#: block itself exists once on disk.
_VIS_MARK = "// @@KS4WEB_VISIBILITY@@"
_INSTR_MARK = "// @@KS4WEB_INSTRUMENT@@"
_PAY_MARK = "// @@KS4WEB_PAYMENT@@"
_ACT_MARK = "// @@KS4WEB_ACTIVATION@@"
_ARIA_MARK = "// @@KS4WEB_ARIA@@"
_HREF_MARK = "// @@KS4WEB_HREF@@"

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

#: THE ONE HREF SOURCE (union wave, fuzzer class 10). Same story again, one
#: property along: five sites read `element.href` and stringified it, and on
#: an SVG anchor that property is an SVGAnimatedString, so the payload
#: carried "/[object%20SVGAnimatedString]" as a fact.
HREF_JS = (_HERE / "href.js").read_text(encoding="utf-8")

#: THE ONE ACTIVATION-TARGET SOURCE (re-attack 2 C1, 2026-09-06). Same story
#: one question earlier: every classifier in the build modelled the element
#: the tool TOUCHES, and the browser routes a click on a `<label>` to the
#: control it labels. Clicking `<label for=submitButton>` submitted a
#: card-carrying form with no class computed. "Which element does this
#: activate" now has one implementation and every consumer splices it.
ACTIVATION_JS = (_HERE / "activation.js").read_text(encoding="utf-8")

#: THE ONE ARIA-STATE SOURCE. Same story again, one question along: "what
#: state is this affordance in" had two implementations, a fuller one in
#: `extract.js` and a three-property one in `find.js`, so the same tab came
#: back `[selected]` from a page read and bare from a search. The rule now
#: lives in `aria.js` and is spliced into both, which is what makes "which
#: tab is active" answerable from whichever read found the tab.
ARIA_JS = (_HERE / "aria.js").read_text(encoding="utf-8")

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
    if _ARIA_MARK in source:
        source = source.replace(_ARIA_MARK, ARIA_JS)
    if _HREF_MARK in source:
        source = source.replace(_HREF_MARK, HREF_JS)
    if _INSTR_MARK in source:
        source = source.replace(_INSTR_MARK, INSTRUMENT_PRELUDE)
    return source


EXTRACT_JS = instrument((_HERE / "extract.js").read_text(encoding="utf-8"))
FIND_JS = instrument((_HERE / "find.js").read_text(encoding="utf-8"))
TEXT_JS = instrument((_HERE / "text.js").read_text(encoding="utf-8"))
ARTICLE_JS = instrument((_HERE / "article.js").read_text(encoding="utf-8"))


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
    data = _checked(await page.evaluate(
        EXTRACT_JS, {"root": root, "pin": pin}))
    if _looks_unfinished(data):
        # THE READ PATH GETS THE ARMING PROBE'S YIELD (hostile H-06). Fix
        # wave 8 gave the CLICK path a two-animation-frame yield so a lid
        # raised in `requestAnimationFrame` is composited before the verdict;
        # the read path got no equivalent, so `/time/raf?f=5` — an h1, a
        # paragraph and a button revealed on frame 5 — read as a page with
        # no controls and the completeness block affirmed it ("unlisted
        # affordances: none, every control is listed"). An empty read looked
        # final, and nothing in it signalled that the page was still
        # materialising.
        #
        # The yield is paid ONLY on a read that came back with nothing to
        # show, which is the shape the defect has and is not the shape an
        # ordinary page has, so no page that had content pays for it.
        try:
            await page.evaluate(_FRAME_YIELD)
            data = _checked(await page.evaluate(
                EXTRACT_JS, {"root": root, "pin": pin}))
            data.setdefault("completeness", {})["re_read_after_frames"] = 2
        except Exception:
            pass                # a page that went away keeps the first read
    return data


#: What "the first read found nothing" looks like. Deliberately narrow: a
#: page with any affordance, any heading, or any readable prose is a page
#: this build has something to say about, and it pays nothing here.
def _looks_unfinished(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("affordances") or data.get("headings"):
        return False
    if (data.get("shape") or {}).get("prose_chars"):
        return False
    return bool(data.get("identity"))


#: Two animation frames and a task turn, the same window `_ARMING_PROBE`
#: uses, for the same reason: it is exactly as far as a page can schedule
#: without a timer.
_FRAME_YIELD = """
() => new Promise(function (done) {
  let settled = false;
  const finish = function () {
    if (settled) return;
    settled = true;
    setTimeout(done, 0);
  };
  requestAnimationFrame(function () { requestAnimationFrame(finish); });
  setTimeout(finish, 250);
})
"""


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


async def read_article(page, root: str | None = None, start_index: int = 0,
                       max_chars: int = 20000, links: str = "inline") -> dict:
    """The article-shaped read: one walk, the body kept, the chrome counted.

    Returns the shape verdict alongside the content, so a page that is not an
    article says so with its evidence rather than coming back as mangled
    prose. See `article.js` for the scoring and the refusal rule."""
    return _checked(await page.evaluate(ARTICLE_JS, {
        "root": root, "start_index": start_index, "max_chars": max_chars,
        "links": links}))


#: The completeness counters that ADD across frames, and the ones that do not.
#: A frame's hidden nodes are hidden nodes on this page; a frame's viewport
#: height is its own and means nothing merged.
_SUMMED = (
    "hidden_interactive", "hidden_nodes", "hidden_text_chars",
    "open_shadow_roots", "shadow_roots_traversed", "closed_shadow_roots",
    "injection_suspects", "zero_width_hits", "reordered_containers",
    "total_elements", "walked_elements", "text_chars",
    "affordances_collected", "affordances_uncollected",
    "headings_uncollected", "depth_cut_subtrees", "extract_ms",
)
_MERGED_MAPS = ("hidden_reasons", "hidden_interactive_reasons",
                "reorder_reasons", "name_fallbacks")


def stitch(main: dict, parts: list) -> dict:
    """Fold each frame's extraction into the main document's, IN PLACE.

    The design decision this function is: frame content joins the SAME
    payload and therefore the SAME degradation ladder, rather than riding in a
    parallel structure the budget does not see. A control inside a checkout
    frame competes for the read's tokens against a control in the page chrome,
    which is what "frame-scoped budget charging on the same ladder" means and
    what keeps every printed price executable. Nothing here re-ranks: the
    ranker and the meter run once, afterward, over one list.

    Each part is `(frame_id, extraction, frame_facts)`. Units arrive carrying
    the session refs their own absorb minted, which are already frame-
    qualified (`if2e5`), so no relabelling happens here and no unit can
    collide with a unit from another realm."""
    c = main["completeness"]
    for fid, data, facts in parts:
        for group in ("affordances", "regions", "headings", "forms", "tables"):
            for unit in data.get(group) or []:
                unit["frame"] = fid
            (main.setdefault(group, [])).extend(data.get(group) or [])
        totals = data.get("affordance_class_totals") or {}
        merged = main.setdefault("affordance_class_totals", {})
        for cls, n in totals.items():
            merged[cls] = merged.get(cls, 0) + n
        main["affordance_total"] = (main.get("affordance_total", 0)
                                    + data.get("affordance_total", 0))
        main["headings_total"] = (main.get("headings_total", 0)
                                  + data.get("headings_total", 0))
        # A modal inside a frame blocks that frame, not the page. Reporting it
        # as the page's modal would make every ref on the page refuse
        # MODAL_BLOCKED because a cookie widget opened a dialog in its own
        # document, so it is recorded and not promoted.
        if data.get("modal"):
            c.setdefault("frame_modals", []).append(
                {"frame": fid, "dialog": data["modal"]})
        fc = data.get("completeness") or {}
        for key in _SUMMED:
            if key in fc:
                c[key] = (c.get(key) or 0) + (fc.get(key) or 0)
        for key in _MERGED_MAPS:
            src = fc.get(key) or {}
            dst = c.setdefault(key, {})
            for reason, n in src.items():
                dst[reason] = dst.get(reason, 0) + n
        c.setdefault("frames_read", []).append(
            {"frame": fid, "url": facts.get("url", ""),
             "elements": (fc.get("walked_elements") or 0),
             "affordances": len(data.get("affordances") or [])})
    return main


async def read_page(page, meta: dict, budget: int = 5000,
                    view: str = "auto", root: str | None = None,
                    absorb=None, mode: str = "auto", frames=None,
                    frame_ladder=None) -> Projection:
    """Extract and project in one call, which is what `get_page_view` does.

    `absorb` is the anchor layer's hook, called with the raw extraction before
    anything is rendered. It rewrites every unit's per-read extractor id into
    the session's sticky ref, so `e12` on read one is still `e12` on read
    three and the renderer never learns the difference. It is called once per
    frame, with the frame id, because refs are minted per realm.

    `frames` is the list of `(frame_id, page_like, facts)` this read may
    enter, decided by `engine/frames.py` and never by this package: which
    frames are same-origin is a question about the browser's own boundaries,
    and the projection deliberately knows nothing about browsers."""
    data = await extract(page, root=root)
    if data.get("error"):
        return data
    if absorb is not None:
        absorb(data, "")
    parts = []
    for fid, target, facts in (frames or []):
        # A frame that navigates or detaches mid-read is a real event on a
        # live page and not an error in the read. It is dropped from the
        # stitch and reported as unreachable, because a partial extraction
        # from a document that is being replaced is worse than an honest gap.
        try:
            got = await extract(target)
        except Exception as exc:
            facts["error"] = type(exc).__name__
            continue
        if got.get("error"):
            facts["error"] = got["error"]
            continue
        if absorb is not None:
            absorb(got, fid)
        parts.append((fid, got, facts))
    if parts:
        stitch(data, parts)
    if frame_ladder:
        # EVERY frame on the page, entered or not. The completeness block
        # reports the ones this build refused to touch as loudly as the ones
        # it read, which is the closed-shadow-root shape one boundary along.
        data["completeness"]["frame_ladder"] = frame_ladder
    return project(data, meta, budget=budget, view=view, mode=mode)
