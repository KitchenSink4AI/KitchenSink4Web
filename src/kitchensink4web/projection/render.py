"""The projection itself: eight blocks, the degradation ladder, and the floor.

DESIGN 3.3 and 3.4. `get_page_view` returns an ORIENTATION, not a transcript,
and the blocks are built in priority order and measured as they are built.

**Nothing here truncates.** The incumbent maintainer's objection to hard caps
is correct and this design respects it: a character cap on a tree
serialization can lop off the exact element you needed, trading a loud
overflow for a silent miss. So the ladder drops WHOLE UNITS in reverse
priority order and reports exactly what it dropped, and the floor keeps the
completeness block whatever else goes.

Three ladder properties S1 forced, all implemented here:

* **Monotonic.** S1's httpbin projection got BIGGER at rung 4 (743 to 793
  tokens) because the digest switched from a short lead line to a heading
  list. Every cap below is non-increasing across rungs in every dimension, so
  a rung cannot cost more than the rung above it, and a test asserts it per
  page across every rung on every fixture.
* **Finer than five.** S1's steps bought 20 percent, then 9, then 17, so a
  2,500 budget skipped from 3,711 straight to 2,182, dropping 22 regions and
  the whole lead paragraph when a smaller step would have fit. Eight rungs,
  and the ladder stops at the first one that fits rather than at the first
  one that obviously fits.
* **The floor is content-aware.** S1's floor kept every table row count and
  every form field while dropping the digest, which on an article is
  backwards. The floor keeps what the page is FOR: the digest survives on a
  readable page, the form inventory survives on a form page, the navigation
  survives on an app shell.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import RangeOutOfBounds
from . import ranker
from .meter import (CONTAINER_ONLY, DROPPED_RUNG, LISTED_NOT_EXPANDED,
                    NO_CONTENT, PRINTED, SAFETY_MARGIN, SUPPRESSED_QUOTA,
                    SUMMARIZED, BudgetMeter, ntok, ntok_line)


@dataclass(frozen=True)
class Rung:
    """One step of the ladder. Every cap is non-increasing down the table."""

    n: int
    regions: int | None
    quotas: dict[str, int]
    lead_chars: int
    headings: int
    field_cap: int
    forms_detail: str      # fields | summary
    tables_detail: str     # full | summary
    next_calls: int
    #: How many forms and tables are LISTED at all. These exist because the
    #: floor was not bounded by construction the way DESIGN 3.4 argued it
    #: was: "tables were never more than one line each" is true and
    #: insufficient, since one line each is unbounded in the number of
    #: tables. The 50,000-node fixture carries 595 of them and its floor came
    #: to 12,727 tokens, so a default read REFUSED a page instead of
    #: degrading it, which is the one thing the ladder exists to prevent.
    forms_cap: int = 10 ** 6
    tables_cap: int = 10 ** 6


def _q(nav: int, form: int, primary: int, other: int) -> dict[str, int]:
    #: in-prose links are quota ZERO on every rung, which is the point.
    return {"nav": nav, "form_control": form, "primary": primary,
            "other": other, "prose_link": 0}


#: Sixteen rungs, and the granularity between the top few is the point.
#: (The count is published on the docs page and in the README, both of
#: which read it from len(RUNGS) rather than from this line.)
#:
#: The frozen corpus A re-measure found the flagship page engaging the ladder
#: at the DEFAULT budget through a cliff rather than a size problem: the
#: Treaty of Versailles read was 4,965 undegraded, 4,589 at the old rung 2 and
#: 3,683 at the old rung 3, against an effective budget of 4,500. So a page
#: 465 tokens over budget was delivered 817 tokens under it, because the step
#: that fit was 906 tokens below the step that did not. **A 20 percent drop
#: where a 3 percent one would have fit** is exactly the defect S1 named at
#: the bottom of the ladder, recurring at the top after the rungs had already
#: gone from five to eight.
#:
#: The cliff was the region cap moving from "all of them" straight to twenty,
#: because a region line costs roughly 40 tokens and a long Wikipedia article
#: carries forty regions. So the region cap now sheds the lowest-priority
#: regions a few at a time (40, 34, 30, 26, 23, 20, ...), which is what DESIGN
#: 3.2 means by a partial-collapse step, and the other caps step alongside it
#: rather than in one lurch. Degradation lands just under budget instead of
#: jumping to the first rung that obviously fits.
#:
#: The dominated-rung rule still governs and is what actually guarantees the
#: exposed ladder is monotonic: finer steps make a non-monotonic INTERNAL step
#: more likely, not less, because shedding one region can cost more in
#: completeness accounting than the line it saved.
RUNGS: tuple[Rung, ...] = (
    Rung(1, None, _q(60, 120, 32, 24), 420, 40, 40, "fields", "full", 6,
         10**6, 10**6),
    Rung(2, 36, _q(58, 118, 31, 23), 410, 39, 39, "fields", "full", 6,
         10**6, 10**6),
    Rung(3, 33, _q(55, 114, 30, 22), 395, 38, 38, "fields", "full", 6,
         10**6, 10**6),
    Rung(4, 30, _q(52, 110, 29, 21), 380, 36, 36, "fields", "full", 6,
         60, 60),
    Rung(5, 27, _q(49, 104, 28, 20), 365, 35, 35, "fields", "full", 5,
         50, 50),
    Rung(6, 24, _q(46, 98, 26, 18), 350, 33, 33, "fields", "full", 5,
         40, 40),
    Rung(7, 22, _q(43, 92, 25, 17), 330, 31, 31, "fields", "full", 5,
         32, 32),
    Rung(8, 20, _q(40, 86, 23, 15), 310, 30, 30, "fields", "full", 5,
         26, 26),
    Rung(9, 18, _q(36, 78, 21, 13), 280, 28, 27, "fields", "full", 5,
         22, 22),
    Rung(10, 16, _q(32, 68, 19, 11), 250, 25, 24, "fields", "full", 4,
         18, 18),
    Rung(11, 14, _q(28, 56, 17, 9), 220, 22, 21, "fields", "full", 4,
         15, 15),
    Rung(12, 12, _q(24, 44, 15, 7), 180, 19, 18, "fields", "summary", 4,
         12, 12),
    Rung(13, 11, _q(22, 36, 13, 5), 140, 17, 15, "fields", "summary", 4,
         10, 10),
    Rung(14, 10, _q(20, 28, 11, 3), 0, 14, 12, "fields", "summary", 3,
         8, 8),
    Rung(15, 8, _q(16, 20, 8, 0), 0, 10, 6, "summary", "summary", 3,
         6, 6),
    Rung(16, 6, _q(12, 12, 6, 0), 0, 6, 4, "summary", "summary", 2,
         4, 4),
)

#: `view="forms"` asks for the forms, so its field cap is the rung's cap
#: scaled up rather than the cap sized for a mixed page. Without this the
#: collapsed-form line advertises `get_page_view(view="forms") lists them`
#: and that call lists forty of three hundred and twenty, which is a printed
#: promise that does not execute: DESIGN 3.3a's contract applied to a
#: recovery route rather than to a price. The scaling is uniform, so the caps
#: stay non-increasing down the ladder and the view still degrades.
FORMS_VIEW_FIELD_SCALE = 12

#: What each `view` prints. The deepest tiering in this design happens inside
#: tools rather than between them (DESIGN 7.3 layer 3), and this is it.
VIEWS: dict[str, tuple[str, ...]] = {
    "auto": ("shape", "affordances", "digest", "forms", "tables"),
    "outline": ("shape", "digest"),
    "act": ("affordances", "forms"),
    "forms": ("forms",),
    "tables": ("tables",),
}


@dataclass
class Projection:
    text: str
    rung: int
    tokens: int
    budget: int
    meter: BudgetMeter
    trace: list[dict] = field(default_factory=list)
    shape: str = "app"


# --------------------------------------------------------------- helpers


def _num(n) -> str:
    return f"{n:,}"


def _owns(region: dict) -> bool:
    """Does this landmark hold any content of its own?

    Net counts, so a parent that is genuinely just a wrapper answers False
    however much its children hold. That is the same net arithmetic the price
    uses (DESIGN 3.3a rule 2), asked as a yes-or-no question."""
    net = region["net"]
    return bool(net["interactive"] or net["text_blocks"] or net["images"]
                or net["headings"] or net["chars"])


def _aff_line(aff: dict, discriminator: str | None) -> str:
    bits = [aff["ref"], aff["role"], f'"{aff["name"] or "(unnamed)"}"']
    if aff.get("state"):
        bits.append(f'[{aff["state"]}]')
    if aff.get("secret"):
        bits.append("[secret: value never read]")
    if aff.get("payment"):
        bits.append("[payment-shaped: gated]")
    if aff.get("path"):
        # DESIGN 3.3: print the href PATH. S1 extracted href and never printed
        # it, and a blind agent could not tell whether an affordance labelled
        # "Business" went to a section or opened a menu.
        bits.append(aff["path"])
    if discriminator:
        bits.append(discriminator)
    return " | ".join(bits)


def _heading_line(heading: dict, price: int | None) -> str:
    indent = "  " * max(0, heading["level"] - 1)
    tail = (f"~{_num(price)} tok" if price is not None
            else "cost unknown (no determinable section container)")
    return f'{indent}{heading["ref"]} | h{heading["level"]} | {heading["text"]} | {tail}'


# ---------------------------------------------------------------- blocks


class Renderer:
    """One render at one rung. Holds no state between rungs."""

    def __init__(self, data: dict, meta: dict, meter: BudgetMeter,
                 rung: Rung, view: str) -> None:
        self.d = data
        self.meta = meta
        self.meter = meter
        self.rung = rung
        self.view = view
        self.blocks = VIEWS.get(view, VIEWS["auto"])
        self.shape = data["shape"]["kind"]
        self.n = 0
        self.omitted_blocks: list[str] = []
        self.selected: list[dict] = []
        self.suppressed: dict[str, int] = {}
        self.listed_regions: list[dict] = []

    # Dynamic numbering: S1 hardcoded the numbers while omitting empty
    # blocks, so a page with no forms and no tables jumped from section 4 to
    # section 7 and a blind agent noted that two sections had vanished with no
    # disclosure, "including in the section that exists specifically to
    # disclose what the read did not cover."
    def head(self, title: str) -> str:
        self.n += 1
        return f"## {self.n} {title}"

    # ------------------------------------------------------------ identity

    def identity(self) -> list[str]:
        i = self.d["identity"]
        c = self.d["completeness"]
        s = self.d["shape"]
        return [
            self.head("IDENTITY"),
            f'url: {i["url"]}',
            f'title: {i["title"]}',
            f'status: {self.meta.get("status", "?")} | load: '
            f'{self.meta.get("load_state", "?")} | lane: {self.meta.get("lane", "?")} '
            f'| page: {self.meta.get("page", "p?")} | read: {self.meta.get("read_token", "-")} '
            f'| t={self.meta.get("ts", "")}',
            f'viewport: {i["viewport"]} | page height: {i["screens"]} screens | '
            f'dom nodes: {_num(c["total_elements"])} | shape: {s["kind"]} '
            f'({s["why"]})',
        ]

    # --------------------------------------------------------------- shape

    def page_shape(self) -> list[str]:
        regions = self.d["regions"]
        if not regions:
            self.omitted_blocks.append("page shape (no landmark regions found)")
            return []
        # A region that owns nothing is not a menu item, and it is the same
        # class of lie DESIGN 3.3a was written against. `~40 tok to expand` on
        # an empty landmark is the meter's call overhead and nothing else, so
        # the price is real arithmetic over an empty set: the call it advertises
        # returns nothing at all. A landmark that owns nothing but holds nested
        # regions is real STRUCTURE, so it is listed and says it is a container
        # rather than quoting a price for a call its children already answer.
        empty = [r for r in regions if not _owns(r) and not r["children"]]
        empty_refs = {r["ref"] for r in empty}
        listable = [r for r in regions if r["ref"] not in empty_refs]
        ranked = sorted(listable, key=lambda r: -self.meter.price_region(r))
        keep = ranked if self.rung.regions is None else ranked[:self.rung.regions]
        keep_refs = {r["ref"] for r in keep}
        self.listed_regions = [r for r in listable if r["ref"] in keep_refs]
        lines = [self.head(
            "PAGE SHAPE (regions, each priced with this read's own estimate "
            "of how much CONTENT it holds; expanding one returns a "
            "projection of that content under whatever budget you pass, so a "
            "large price means a lot is in there rather than a large bill)")]
        for r in self.listed_regions:
            where = "in-view" if r["in_viewport"] else f'y={r["top"]}'
            net = r["net"]
            head = (f'{r["ref"]} | {r["kind"]} | "{r["label"]}" | '
                    f'{net["interactive"]} act, {net["text_blocks"]} blocks, '
                    f'{net["images"]} img | {where}')
            kids = r["children"]
            if not _owns(r):
                # No price, deliberately. Expanding a wrapper returns what
                # expanding its children returns, so a number here would be a
                # price for a call that answers nothing of its own.
                line = (f'{head} | container of {", ".join(kids[:6])}'
                        + (f' +{len(kids) - 6} more' if len(kids) > 6 else ''))
                lines.append(line)
                self.meter.ledger.add("region", r["ref"], CONTAINER_ONLY,
                                      tokens=ntok_line(line))
                continue
            price = self.meter.price_region(r)
            child_note = ""
            if kids:
                child_note = (f' (net of {len(kids)} nested region(s): '
                              + ", ".join(kids[:6])
                              + (f' +{len(kids) - 6} more' if len(kids) > 6
                                 else '') + ')')
            line = f'{head} | ~{_num(price)} tok of content{child_note}'
            lines.append(line)
            self.meter.ledger.add("region", r["ref"], LISTED_NOT_EXPANDED,
                                  tokens=ntok_line(line), price=price)
        for r in listable:
            if r["ref"] not in keep_refs:
                self.meter.ledger.add("region", r["ref"], DROPPED_RUNG)
        for r in empty:
            self.meter.ledger.add("region", r["ref"], NO_CONTENT)
        return lines

    # ---------------------------------------------------------- affordances

    def affordances(self) -> list[str]:
        affs = self.d["affordances"]
        if not affs:
            self.omitted_blocks.append("affordances (no interactive elements)")
            return []
        self.selected, self.suppressed = ranker.select(
            affs, self.rung.quotas,
            self.d.get("affordance_class_totals"))
        marks = ranker.disambiguate(self.selected)
        prose_included = self.rung.quotas.get("prose_link", 0) > 0
        lines = [self.head(
            "AFFORDANCES (per-class quotas: navigation first, form controls "
            "complete, in-prose links included at the caller's request)"
            if prose_included else
            "AFFORDANCES (per-class quotas: navigation first, form controls "
            "complete, in-prose links suppressed by design)")]
        for aff in self.selected:
            line = _aff_line(aff, marks.get(aff["ref"]) or None)
            lines.append(line)
            self.meter.ledger.add("affordance", aff["ref"], PRINTED,
                                  tokens=ntok_line(line), cls=aff.get("cls"))
        # One aggregated entry per class rather than 2,700 individual ones.
        # The number is the extractor's tally over the whole page, so it is
        # the page's figure and not the payload's.
        for cls, n in self.suppressed.items():
            if n:
                self.meter.ledger.add("affordance", f"suppressed:{cls}",
                                      SUPPRESSED_QUOTA, cls=cls, count=n)
        return lines

    # --------------------------------------------------------------- digest

    def digest(self) -> list[str]:
        headings = self.d["headings"]
        lead = self.d["lead"]
        if not headings and not lead:
            self.omitted_blocks.append("content digest (no headings and no "
                                       "readable lead)")
            return []
        s = self.d["shape"]
        lines = [self.head(
            f'CONTENT DIGEST ({s["kind"]} projection: {s["why"]})')]
        if lead and self.rung.lead_chars:
            text = lead[:self.rung.lead_chars]
            if len(lead) > self.rung.lead_chars:
                cut = text.rfind(" ")
                text = text[:cut if cut > self.rung.lead_chars * 0.6
                            else self.rung.lead_chars] + "..."
            line = f"lead: {text}"
            lines.append(line)
            self.meter.ledger.add("lead", "lead", PRINTED, tokens=ntok_line(line))
        elif lead:
            self.meter.ledger.add("lead", "lead", DROPPED_RUNG)
        shown = headings[:self.rung.headings]
        for h in shown:
            line = _heading_line(h, self.meter.price_section(h))
            lines.append(line)
            self.meter.ledger.add("heading", h["ref"], PRINTED,
                                  tokens=ntok_line(line))
        dropped = len(headings) - len(shown) + max(
            0, self.d.get("headings_total", len(headings)) - len(headings))
        if dropped:
            self.meter.ledger.add("heading", "dropped", DROPPED_RUNG,
                                  count=dropped)
        if self.d["shape"]["prose_chars"]:
            lines.append(
                f'prose: ~{_num(self.d["shape"]["prose_chars"])} chars in the '
                f'readable region; read one section with '
                f'get_text(page="{self.meta.get("page", "p1")}", '
                f'location={{"ref":"h<n>"}})')
        return lines

    # ---------------------------------------------------------------- forms

    @property
    def field_cap(self) -> int:
        if self.view == "forms":
            return self.rung.field_cap * FORMS_VIEW_FIELD_SCALE
        return self.rung.field_cap

    def forms(self) -> list[str]:
        forms = self.d["forms"]
        if not forms:
            self.omitted_blocks.append("forms (page has none)")
            return []
        lines = [self.head("FORMS")]
        shown = forms[:self.rung.forms_cap]
        omitted = forms[self.rung.forms_cap:]
        for f in omitted:
            self.meter.ledger.add("form", f["ref"], DROPPED_RUNG)
        for f in shown:
            detail = self.rung.forms_detail
            # Content-aware floor: on a FORM page the field listing is what
            # the page is for, so it survives a rung that would collapse it
            # elsewhere. **Only where it FITS**, which is the half Phase 2
            # had to add: DESIGN 3.4 says forms collapse to one line "when
            # the field-level listing would breach budget", and an
            # unconditional override on a 320-field fixture reinstates
            # exactly the unbounded floor rung 5's caps exist to close.
            if (detail == "summary" and self.shape == "form"
                    and len(f["fields"]) <= self.field_cap):
                detail = "fields"
            head = (f'{f["ref"]} | "{f["name"] or f["action"]}" | '
                    f'{f["method"]} {f["action"]} | {len(f["fields"])} fields'
                    + (f' | in {f["region"]}' if f["region"] else ""))
            lines.append(head)
            self.meter.ledger.add("form", f["ref"], PRINTED, tokens=ntok_line(head))
            if detail == "summary":
                self.meter.ledger.add("field", f'{f["ref"]}:summarized',
                                      SUMMARIZED, count=len(f["fields"]))
                lines.append(
                    f'   [{len(f["fields"])} fields not listed at this budget; '
                    f'get_page_view(view="forms") lists them]')
                continue
            for fl in f["fields"][:self.field_cap]:
                bits = [f'   {fl["ref"] or "-"}', fl["label"] or "(unlabeled)",
                        fl["type"]]
                if fl["required"]:
                    bits.append("required")
                if fl["secret"]:
                    bits.append("secret: value never read")
                if fl["payment"]:
                    bits.append("payment-shaped: gated")
                bits.append(fl["value_state"])
                if fl.get("options"):
                    bits.append("options: " + ", ".join(fl["options"]))
                elif fl.get("option_count"):
                    bits.append(
                        f'{fl["option_count"]} options, over the inline cap; '
                        f'get_page_view(view="forms", location='
                        f'{{"ref":"{fl["ref"]}"}})')
                line = " | ".join(bits)
                lines.append(line)
                self.meter.ledger.add("field", fl["ref"] or fl["label"],
                                      PRINTED, tokens=ntok_line(line))
            extra = f["fields"][self.field_cap:]
            if extra:
                self.meter.ledger.add("field", f'{f["ref"]}:dropped',
                                      DROPPED_RUNG, count=len(extra))
                lines.append(f'   [{len(extra)} more fields in this form]')
        if omitted:
            lines.append(
                f'[{len(omitted)} more form(s) on this page were not listed '
                f'at this budget; get_page_view(view="forms") lists them]')
        return lines

    # --------------------------------------------------------------- tables

    def tables(self) -> list[str]:
        tables = self.d["tables"]
        if not tables and not self.d["div_tables"]:
            self.omitted_blocks.append("tables (page has none)")
            return []
        lines = [self.head("TABLES (structure only; cells come from get_table)")]
        shown = tables[:self.rung.tables_cap]
        dropped_tables = tables[self.rung.tables_cap:]
        for t in dropped_tables:
            self.meter.ledger.add("table", t["ref"], DROPPED_RUNG)
        for t in shown:
            spans = f', {t["spans"]} spanned cells' if t["spans"] else ""
            cols = " | ".join(t["headers"]) if t["headers"] else "(no th)"
            line = (f'{t["ref"]} | "{t["caption"] or "(unnamed)"}" | '
                    f'{t["rows"]}x{t["cols"]}{spans}'
                    + (f" | cols: {cols}" if self.rung.tables_detail == "full"
                       else "")
                    + f' | ~{_num(self.meter.price_table(t))} tok if fully read')
            lines.append(line)
            self.meter.ledger.add("table", t["ref"], PRINTED, tokens=ntok_line(line))
        if dropped_tables:
            lines.append(
                f'[{len(dropped_tables)} more table(s) on this page were not '
                f'listed at this budget; get_page_view(view="tables") lists '
                f'them]')
        if self.d["div_tables"]:
            lines.append(
                f'[{self.d["div_tables"]} div-rendered grids (role=table or '
                f'grid) detected and named as such; get_list reads these]')
        return lines

    # --------------------------------------------------------- completeness

    def completeness(self) -> list[str]:
        """The block that computes nothing.

        Every number below is a query against the ledger the budget meter kept
        while enforcing the budget. That is the whole design of DESIGN 3.3
        block 7: S1's block recomputed its own figures after the fact and so
        reported on the degradation ladder (which had not engaged) instead of
        on the projection (which had omitted most of the page)."""
        c = self.d["completeness"]
        led = self.meter.ledger
        lines = [self.head(
            "COMPLETENESS (what this read did NOT see, rendered from the "
            "budget meter's own ledger)")]

        if c["frames"]:
            lines.append(
                f'iframes not traversed: {c["frames_same"]} same-origin, '
                f'{c["frames_cross"]} cross-origin')
            for fr in c["frames"][:6]:
                origin = "same-origin" if fr["same_origin"] else "cross-origin"
                lines.append(
                    f'   {fr["ref"]} | {origin} | {fr["title"] or fr["src"]}')
        else:
            lines.append("iframes: none")

        # The two-layer phrasing, kept on evidence: a blind agent singled this
        # line out as the most useful in the whole document, because it
        # separates "I did not look" from "no one can look" where most tools
        # collapse both into a confident zero. The traversal build changed
        # which layer the open roots sit in, not the shape of the sentence.
        # `traversed=no` survives for two cases that are still real: a read
        # that opted out, and a host the walk never reached because it sits
        # under hidden content, whose roots are counted here all the same.
        traversed = c.get("shadow_roots_traversed")
        lines.append(
            f'shadow roots: {c["open_shadow_roots"]} open '
            + (f'(traversed=yes, {traversed} read)' if traversed
               else '(traversed=no)')
            + f', {c["closed_shadow_roots"]} closed (unreachable by any tool)')
        if traversed:
            # The fidelity caveat, printed only where it can bite. A shadow
            # tree can render its slotted children in any order it likes and
            # this walk reports source order, so on a component that reorders
            # its slots the sequence above is not the reading sequence.
            lines.append(
                '   shadow content is reported in source order; a component '
                'that reorders its slots is read out of rendered order')

        if c["virtual"]:
            for v in c["virtual"][:4]:
                claimed = (f'; the page reports ~{v["claimed"]} total'
                           if v["claimed"] else "; total not exposed by the page")
                lines.append(
                    f'virtualized or infinite container in '
                    f'{v["region"] or "(unowned)"}: {v["dom_count"]} rows in '
                    f'the DOM{claimed}'
                    + (f' [detected by {v["how"]}]' if v.get("how") else ''))
        else:
            lines.append("virtualized or infinite-scroll containers: none detected")

        lines.append(
            f'below the fold: {self.d["identity"]["screens"]} screens; this '
            f'read covered the whole DOM rather than the viewport')

        reasons = ", ".join(
            f"{k}={v}" for k, v in sorted(c["hidden_reasons"].items(),
                                          key=lambda kv: -kv[1])[:6])
        # The INTERACTIVE half of the ledger names its techniques separately.
        # "4 nodes (1 interactive)" says how much was withheld and nothing
        # about how it was hidden, and a control a page cloaked is the half a
        # reader most needs to see named (gauntlet 2 H2).
        hi_reasons = ", ".join(
            f"{k}={v}" for k, v in sorted(
                (c.get("hidden_interactive_reasons") or {}).items(),
                key=lambda kv: -kv[1])[:6])
        lines.append(
            f'hidden content stripped: {_num(c["hidden_nodes"])} nodes '
            f'({c["hidden_interactive"]} interactive, '
            f'{_num(c["hidden_text_chars"])} chars of text) [{reasons or "none"}]'
            + (f'; hidden interactive by technique: {hi_reasons}'
               if hi_reasons else "")
            + (f'; {c["injection_suspects"]} hidden regions carried more than '
               f'20 characters of text' if c["injection_suspects"] else ""))
        # RENDERED ORDER, said on the page that does it rather than only where
        # a shadow root happens to be involved. Three of the four techniques
        # need no shadow DOM at all, so the shadow-only caveat below used to
        # imply that source-order divergence was a components problem.
        if c.get("reordered_containers"):
            how = ", ".join(
                f"{k}={v}" for k, v in sorted(
                    (c.get("reorder_reasons") or {}).items(),
                    key=lambda kv: -kv[1]))
            lines.append(
                f'reading order: {c["reordered_containers"]} container(s) '
                f'render their children in an order the source does not carry '
                f'[{how}]; everything above is reported in SOURCE order, so on '
                f'those containers it is not the order a person reads')
        if c["zero_width_hits"]:
            lines.append(
                f'zero-width characters found in {c["zero_width_hits"]} text '
                f'nodes and removed from the content')

        if c["canvases"]:
            lines.append(
                f'canvas-rendered regions with no text projection: '
                f'{len(c["canvases"])}; pixels need the capture pack '
                f'(--packs capture)')
        else:
            lines.append("canvas-rendered regions: none")

        lines.append(f'auth state: {self._auth_state()}')

        suppressed = led.by_class("affordance", SUPPRESSED_QUOTA)
        total_suppressed = sum(suppressed.values())
        if total_suppressed:
            detail = ", ".join(
                f"{ranker.CLASS_LABEL.get(k, k)}={v}"
                for k, v in sorted(suppressed.items(), key=lambda kv: -kv[1]))
            # The in-prose clause is printed only when in-prose links were
            # actually suppressed. Explaining a rule that did not fire is how
            # a completeness block becomes something a reader skims.
            why = (" In-prose links carry a quota of zero by design; "
                   "find_elements retrieves one by name for a fraction of a "
                   "read." if suppressed.get("prose_link") else "")
            lines.append(
                f'unlisted affordances: {total_suppressed} in '
                f'{len(suppressed)} class(es) [{detail}].{why}')
        else:
            lines.append("unlisted affordances: none, every control is listed")
        if c["affordance_cap_hit"]:
            lines.append(
                f'{c["affordances_uncollected"]} of those were counted but '
                f'not ranked: the extractor returns at most '
                f'{c["affordances_collected"]} candidates per read, so the '
                f'totals above are the page\'s and the ranking is over the '
                f'first {c["affordances_collected"]}')

        fields_dropped = led.count(kind="field", status=DROPPED_RUNG) + \
            led.count(kind="field", status=SUMMARIZED)
        lines.append(
            f'form fields not listed: {fields_dropped} '
            f'(of {led.count(kind="field")} found); forms omitted: '
            f'{led.count(kind="form", status=DROPPED_RUNG)} of '
            f'{led.count(kind="form")}')

        headings_dropped = led.count(kind="heading", status=DROPPED_RUNG)
        lines.append(
            f'headings not listed: {headings_dropped} of '
            f'{led.count(kind="heading")}; tables omitted: '
            f'{led.count(kind="table", status=DROPPED_RUNG)} of '
            f'{led.count(kind="table")}')

        listed = led.count(kind="region", status=LISTED_NOT_EXPANDED)
        dropped = led.count(kind="region", status=DROPPED_RUNG)
        containers = led.count(kind="region", status=CONTAINER_ONLY)
        empty = led.count(kind="region", status=NO_CONTENT)
        lines.append(
            f'regions listed but not expanded: {listed} (their expand costs '
            f'are printed above); regions dropped by the degradation rung: '
            f'{dropped}'
            + (f'; {containers} listed as containers, priced at nothing '
               f'because their content is their children'
               if containers else '')
            + (f'; {empty} region(s) own nothing at all and were not listed'
               if empty else ''))

        if self.omitted_blocks:
            lines.append("blocks omitted entirely: " +
                         "; ".join(self.omitted_blocks))

        fallbacks = c["name_fallbacks"]
        if fallbacks:
            lines.append(
                f'name quality: {fallbacks} accessible name(s) came from a '
                f'fallback or were truncated on a word boundary; a name that '
                f'could not be computed is printed as (unnamed) rather than '
                f'guessed from a CSS class')
        else:
            lines.append("name quality: every accessible name was computed")

        if c.get("depth_cut_subtrees"):
            lines.append(
                f'{c["depth_cut_subtrees"]} subtree(s) below 400 levels of '
                f'nesting were not walked')

        # How many priced units fell back to the page-wide rate because their
        # own text sample was unavailable or this read's 40,000-character
        # sample budget (first-come) was already spent. Folded in with
        # Phase 4: one honest count, emitted only when a fallback happened,
        # like the zero-width line above it, so a page that never spends its
        # sample budget carries no extra line.
        fell = len(self.meter.page_rate_units)
        if fell:
            lines.append(
                f'priced at page rate: {fell} of '
                f'{len(self.meter.priced_units)} priced unit(s) used the '
                f'page-wide characters-per-token rate because their own text '
                f'sample was unavailable or this read\'s 40,000-character '
                f'sample budget was already spent')

        # The budget accounting is a SEPARATE statement from the content
        # accounting above it. Printing the first while implying the second is
        # what produced S1's "0 regions not expanded" on a page carrying
        # thirty priced regions.
        lines.append(self.meter.budget_line(self.rung.n, len(RUNGS)))
        return lines

    def _auth_state(self) -> str:
        """Signed-in, signed-out, or unknown, and HOW it was determined.

        A blind agent on the GitHub repo page reverse-engineered this from an
        affordance label to correctly predict that a star click would fail,
        which is the right answer reached the wrong way. Stating it is cheap;
        the honest part is naming the evidence, because this is a heuristic."""
        names = " ".join((a.get("name") or "").lower()
                         for a in self.d["affordances"][:400])
        if any(k in names for k in ("sign out", "log out", "logout",
                                    "your profile", "account menu")):
            return "signed-in (a sign-out control is present); heuristic"
        if any(k in names for k in ("sign in", "log in", "login", "sign up")):
            return "signed-out (a sign-in control is present); heuristic"
        return "unknown (no sign-in or sign-out control was found); heuristic"

    # ---------------------------------------------------------- next calls

    def next_calls(self) -> list[str]:
        """Ranked by what the call is likely to ANSWER, never by size.

        S1 put `expand r5 (main, ~73,716 tok)` at the top of its recommended
        list on Versailles. That region overlapped a dozen others and was
        simultaneously the most expensive and least useful call on the page.
        Ranking by cost in either direction is what produced it, so an
        overlapping parent is demoted below its own children here rather than
        promoted above them."""
        page = self.meta.get("page", "p1")
        lines = [self.head("NEXT CALLS (ranked by what each is likely to "
                           "answer, not by size)")]
        candidates = []
        for r in self.listed_regions:
            price = self.meter.price_region(r)
            net = r["net"]  # noqa: F841 (kept for the value arithmetic below)
            # In-prose links carry a quota of zero, so counting them here
            # ranks a region by exactly the affordances the projection has
            # already decided not to print. On the GDP page that put the
            # footnote block (446 citation links) above the article's own
            # data table, which is the ranking-by-size defect wearing a
            # different hat.
            acts = max(0, net["interactive"] - net.get("prose_links", 0))
            value = acts * 2 + net["headings"] * 3 + min(40, net["text_blocks"])
            if r["children"]:
                value *= 0.4   # a parent that wraps its own children answers less
            candidates.append((value, price, r))
        candidates.sort(key=lambda t: -t[0])
        for value, price, r in candidates[:self.rung.next_calls]:
            if value <= 0:
                continue
            lines.append(
                f'expand {r["ref"]} ("{r["label"]}"): get_page_view('
                f'page="{page}", location={{"region":"{r["ref"]}"}})  '
                f'~{_num(price)} tok')
        if self.d["tables"]:
            t = self.d["tables"][0]
            lines.append(
                f'read table {t["ref"]}: get_table(page="{page}", '
                f'ref="{t["ref"]}", rows="1-50")  ({t["rows"]} rows total)')
        if self.meter.ledger.count(kind="affordance", status=SUPPRESSED_QUOTA):
            lines.append(
                f'find a control or link by name: find_elements(page="{page}", '
                f'query="<the text you are looking for>")  tens of tokens')
        lines.append(
            f'act on any ref above: click(page="{page}", '
            f'location={{"ref":"e<n>"}}) | type_text(...) | fill_form(...)')
        return lines

    # ------------------------------------------------------------- assembly

    def build(self) -> str:
        body: list[str] = []
        body += self.identity()
        for name in self.blocks:
            block = getattr(self, {"shape": "page_shape",
                                   "affordances": "affordances",
                                   "digest": "digest",
                                   "forms": "forms",
                                   "tables": "tables"}[name])()
            if block:
                body += [""] + block
        # Completeness and next-calls are the floor and are never dropped.
        body += [""] + self.completeness()
        body += [""] + self.next_calls()
        return "\n".join(body)


# ----------------------------------------------------------------- ladder


def project(data: dict, meta: dict, budget: int = 5000,
            view: str = "auto", mode: str = "auto") -> Projection:
    """Run the ladder and return the richest projection that fits the budget.

    The budget is enforced against the meter's ESTIMATE with a 10 percent
    safety margin held back, so "a page view never exceeds its budget" is a
    checkable property rather than a slogan.

    `mode="links"` lifts the prose-link quota of zero (field request: the
    suppressed in-prose links forced a find_elements round-trip when the
    caller KNEW it needed a link mentioned in the body). The cost is real
    and the ladder charges it honestly: on a link-heavy page the projection
    lands on a lower rung or needs a bigger budget, which is the stated
    price of asking for everything."""
    meter = BudgetMeter(budget)
    _calibrate(data, meter, view)
    rungs = RUNGS
    if mode == "links":
        from dataclasses import replace as _replace
        rungs = tuple(
            _replace(r, quotas={**r.quotas, "prose_link": 100000})
            for r in RUNGS)
    trace: list[dict] = []
    chosen: Projection | None = None
    previous = None
    for rung in rungs:
        text, tokens = _render_to_fixpoint(data, meta, meter, rung, view)
        # A rung that costs MORE than the rung above it is dominated: the
        # richer projection is also the smaller one, so there is never a
        # reason to choose this one. Dropping a unit occasionally costs more
        # than it saves, because the completeness block has to account for
        # what went, and this is the enforcement that keeps the ladder
        # monotonic as EXPOSED even when a single step is not.
        dominated = previous is not None and tokens > previous
        trace.append({"rung": rung.n, "tokens": tokens,
                      "dominated": dominated})
        previous = tokens if previous is None else min(previous, tokens)
        if dominated:
            continue
        if tokens <= meter.effective:
            chosen = Projection(text=text, rung=rung.n, tokens=tokens,
                                budget=budget, meter=meter, trace=trace,
                                shape=data["shape"]["kind"])
            break
    if chosen is None:
        floor = trace[-1]["tokens"]
        raise RangeOutOfBounds(
            f"budget_tokens={budget} is below this page's floor projection of "
            f"~{floor} tokens (with a {meter.margin}-token drift margin held "
            f"back). The floor is the identity, a capped region list, the "
            f"navigation, one line per form and table, and the completeness "
            f"block, and it is what makes the read honest rather than "
            f"truncated. Raise budget_tokens to at least "
            f"{_smallest_budget_that_fits(data, meta, view, floor)}, or scope "
            f"the read with view='outline'.")
    return chosen


def _smallest_budget_that_fits(data: dict, meta: dict, view: str,
                               floor: int) -> int:
    """The budget the refusal names, VERIFIED rather than computed.

    The obvious arithmetic is `floor / (1 - margin)`, and it is wrong often
    enough to matter, because the budget line states the budget INSIDE the
    payload it is measuring: raising the budget from 200 to 1,201 lengthens
    that line and the floor grows by a token or two, so the number the
    refusal quoted no longer fits when the caller uses it. A refusal that
    names a number is making a claim, and DESIGN 3.3a's contract is that
    every printed price is executable. So this renders the floor at the
    candidate budget and walks the candidate up until the claim is true."""
    candidate = int(floor / (1 - SAFETY_MARGIN)) + 1
    for _ in range(6):
        meter = BudgetMeter(candidate)
        _calibrate(data, meter, view)
        _, tokens = _render_to_fixpoint(data, meta, meter, RUNGS[-1], view)
        if tokens <= meter.effective:
            return candidate
        candidate = int(tokens / (1 - SAFETY_MARGIN)) + 1
    return candidate


def _render_to_fixpoint(data: dict, meta: dict, meter: BudgetMeter,
                        rung: Rung, view: str) -> tuple[str, int]:
    """Render until the printed budget figure IS the measured total.

    The budget line states the token count of the payload it sits inside, so
    it is self-referential and needs a fixpoint rather than an estimate. Two
    passes normally suffice; the loop stops either way and the last render is
    what ships, so the printed number is never more than a digit's width off
    and is usually exact."""
    text, tokens = "", 0
    for _ in range(4):
        meter.begin_pass()
        renderer = Renderer(data, meta, meter, rung, view)
        text = renderer.build()
        tokens = ntok(text)
        if tokens == meter.used:
            break
        meter.used = tokens
    return text, tokens


def _calibrate(data: dict, meter: BudgetMeter, view: str) -> None:
    """Set the meter's per-unit rates from THIS page's own printed lines.

    A price is the meter's estimate of what the advertised call would produce,
    so the rates have to come from lines this page actually renders. Two
    estimators would mean two answers, and the one the user sees would be the
    one nothing tested."""
    top = RUNGS[0]
    selected, _ = ranker.select(data["affordances"], top.quotas)
    aff_lines = [_aff_line(a, None) for a in selected[:24]]
    head_lines = [_heading_line(h, 1000) for h in data["headings"][:24]]
    lead = data.get("lead") or ""
    meter.calibrate(aff_lines, head_lines, len(lead), lead)
