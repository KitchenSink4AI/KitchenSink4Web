"""The budget meter and its ledger: one arithmetic for prices and budgets.

DESIGN 3.3a states the rule this module exists to make mechanical: **a printed
price and an enforced budget come from the same arithmetic, in the same pass,
over the same units.** S1 shipped three separate lies in one prototype because
the prices came from heuristics living near the renderer while the budget came
from counting the finished string, and a blind agent caught each one:

1. every heading priced at `~10 tok` while one section was really ~6,399,
2. `main` priced as the sum of every other region because it overlapped its
   own children, so the most expensive call on the page also looked like the
   most complete one,
3. `0 regions not expanded` printed while thirty regions carried expand costs.

The fix for all three is structural. The meter measures every unit as the
projection builds it, keeps a LEDGER of what happened to each one, and answers
three questions from that single record: what did this cost, what would that
other call cost, and what did this read not print. **The completeness block
computes nothing; it renders the ledger** (DESIGN 3.3 block 7).

The estimator is named rather than assumed: `tiktoken` on `o200k_base`, the
convention fixed in DESIGN 3.4 and PLAN W1. Conflict record #4 shows tokenizers
disagreeing by roughly 3x on this exact class of content, so an unnamed
estimator would make "a page view never exceeds its budget" unfalsifiable. The
meter also holds a 10 percent safety margin against client-side tokenizer
drift and reports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

#: DESIGN 3.4 and PLAN W1. Every published number names this.
ENCODING_NAME = "o200k_base"

#: Held back against client-side tokenizer drift, and reported rather than
#: hidden: the budget line prints the estimate AND the margin.
SAFETY_MARGIN = 0.10


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    return tiktoken.get_encoding(ENCODING_NAME)


def warm() -> None:
    """Load the encoder before the first read needs it.

    `get_encoding` reads (and on a cold machine downloads) the BPE table, and
    paying that inside the first projection would put a one-off cost of a few
    hundred milliseconds on a number the latency budget is measuring. The
    session manager calls this when a browser starts, which is a moment that
    is already slow for honest reasons."""
    _encoding().encode_ordinary("warm")


def ntok(text: str) -> int:
    """Estimated tokens, under the named convention and nothing else.

    `encode_ordinary` rather than `encode`: the special-token scan is a
    meaningful share of the cost at this call volume and page text has no
    special tokens to find."""
    if not text:
        return 0
    return len(_encoding().encode_ordinary(text))


@lru_cache(maxsize=8192)
def _ntok_cached(line: str) -> int:
    return len(_encoding().encode_ordinary(line))


def ntok_line(line: str) -> int:
    """Per-line measurement, memoized.

    The ladder renders a page more than once (the budget line states the
    total it sits inside, so it needs a fixpoint) and most lines are identical
    between renders. Measuring each one once is the difference between a
    Python assembly bill of 4 ms and 14 ms, and the number is the same
    arithmetic either way."""
    if not line:
        return 0
    if len(line) > 400:
        return len(_encoding().encode_ordinary(line))
    return _ntok_cached(line)


@lru_cache(maxsize=1024)
def _measured_rate(sample: str) -> float:
    """Characters per token on one sample, measured once.

    The ladder prices the same unit on every rung and on every fixpoint pass
    inside a rung, and the refusal path builds fresh meters to verify the
    budget it names, so a page's samples are asked for their rate on the
    order of a hundred times. Measuring them once is the difference between
    a Python assembly bill inside its 10 ms budget and one over it; the
    answer is identical either way, which is what makes the cache safe."""
    tokens = ntok(sample)
    return max(1.0, len(sample) / tokens) if tokens else 0.0


#: What happened to a unit. The completeness block is a view over these, and
#: the distinctions are the ones S1 conflated: a region LISTED but not
#: expanded is a different fact from a region DROPPED by a degradation rung,
#: and both differ from content suppressed by a class quota.
PRINTED = "printed"
SUMMARIZED = "summarized"
SUPPRESSED_QUOTA = "suppressed_by_quota"
DROPPED_RUNG = "dropped_by_rung"
LISTED_NOT_EXPANDED = "listed_not_expanded"
NOT_REACHED = "not_reached"
#: A landmark that owns nothing of its own and exists to hold nested regions.
#: Listed, because the structure is real, but with NO price: expanding it
#: returns nothing that expanding its children would not.
CONTAINER_ONLY = "listed_container_only"
#: A landmark that owns nothing and holds no nested region either. Not listed
#: at all, and counted here so the completeness block can say so.
NO_CONTENT = "no_content"


@dataclass
class Unit:
    """One thing the projection could print, and what became of it.

    `count` exists so a class of suppressed items can be recorded as one
    entry rather than 2,700 of them. That is an accounting shortcut, not an
    accuracy one: the count is the real number, and it comes from a tally the
    extractor keeps over every element rather than from what fit in the
    payload. A per-item record for content nobody prints is a bill paid on
    every read for a number the block states in one line."""

    kind: str            # affordance | region | heading | form | field | table
    key: str             # its ref, where it has one
    status: str
    tokens: int = 0
    cls: str | None = None      # the affordance quota class, where it applies
    count: int = 1
    detail: dict = field(default_factory=dict)


class Ledger:
    """Every unit the projection considered, and its disposition.

    A figure the completeness block can produce independently of this ledger
    is a defect by construction, and the Phase 2 gate tests it as one."""

    def __init__(self) -> None:
        self.units: list[Unit] = []

    def add(self, kind: str, key: str, status: str, tokens: int = 0,
            cls: str | None = None, count: int = 1, **detail) -> Unit:
        unit = Unit(kind=kind, key=key, status=status, tokens=tokens, cls=cls,
                    count=count, detail=detail)
        self.units.append(unit)
        return unit

    def select(self, kind: str | None = None, status: str | None = None,
               cls: str | None = None) -> list[Unit]:
        return [u for u in self.units
                if (kind is None or u.kind == kind)
                and (status is None or u.status == status)
                and (cls is None or u.cls == cls)]

    def count(self, **kw) -> int:
        """How many THINGS, not how many records. Aggregated units carry the
        real number, so the block never under-reports what it suppressed."""
        return sum(u.count for u in self.select(**kw))

    def tokens(self, **kw) -> int:
        return sum(u.tokens for u in self.select(**kw))

    def by_class(self, kind: str, status: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for unit in self.select(kind=kind, status=status):
            key = unit.cls or "unclassified"
            out[key] = out.get(key, 0) + unit.count
        return out


@dataclass
class Rates:
    """Per-unit costs, calibrated on THIS page from what was actually printed.

    A price is only honest if it is the meter's own estimate of what the
    advertised call would produce, so the rates come from measured lines on
    the page in hand rather than from constants chosen once against some other
    page. The fallbacks apply only when nothing of that kind was printed."""

    affordance: float = 15.0
    heading: float = 12.0
    text_block: float = 3.0
    #: The PAGE's rate, and the fallback for a unit that sent no sample of
    #: its own. It is never the whole story: see `BudgetMeter.rate_for`.
    chars_per_token: float = 3.7
    #: Kept because the walk counts it and it is a real content statistic,
    #: and because the experiment that produced it is worth not repeating: a
    #: words-based price was measured against the same 37 regions and came
    #: out WORSE than characters (17.8 percent median error against 13.6),
    #: so characters stayed. The intuition that tokens track words more
    #: closely than characters is right about prose and wrong about the
    #: mixed content a landmark actually holds.
    tokens_per_word: float = 1.45

    def from_chars(self, chars: int, rate: float | None = None) -> int:
        return int(chars / (rate or self.chars_per_token))

    def from_words(self, words: int) -> int:
        return int(words * self.tokens_per_word)


class BudgetMeter:
    """Measures as it builds, and is the only source of any number printed."""

    def __init__(self, budget: int) -> None:
        self.budget = int(budget)
        self.margin = int(round(self.budget * SAFETY_MARGIN))
        self.effective = max(120, self.budget - self.margin)
        self.ledger = Ledger()
        self.rates = Rates()
        self.used = 0

    # ------------------------------------------------------------ measuring

    def measure(self, text: str) -> int:
        return ntok(text)

    def calibrate(self, affordance_lines: list[str], heading_lines: list[str],
                  sample_chars: int, sample_text: str) -> None:
        """Set the rates from what this page's own lines actually cost."""
        if affordance_lines:
            self.rates.affordance = sum(
                ntok(line) for line in affordance_lines) / len(affordance_lines)
        if heading_lines:
            self.rates.heading = sum(
                ntok(line) for line in heading_lines) / len(heading_lines)
        if sample_chars > 200 and sample_text:
            tokens = ntok(sample_text)
            if tokens:
                self.rates.chars_per_token = max(2.0, len(sample_text) / tokens)
                words = len(sample_text.split())
                if words:
                    self.rates.tokens_per_word = min(
                        3.0, max(1.0, tokens / words))

    # -------------------------------------------------------------- pricing

    def rate_for(self, sample: str | None) -> float:
        """Characters per token for ONE unit, measured on its own text.

        A page does not have a characters-per-token rate. The frozen GDP
        article runs 5.3 characters to the token in its prose and 1.8 in its
        own data table, a factor of three, and the single page-level rate
        that priced both was the residual under-pricing gate part 7 spent a
        phase on: four of its five outliers were the page's most numeric or
        most link-dense regions.

        The walk sends back a bounded, decimated sample of each unit's own
        text (extract.js, `sampleInto`) and this measures the rate on it with
        `tiktoken`, the same tokenizer that enforces the budget. It is the
        one-arithmetic rule of DESIGN 3.3a applied to the character-to-token
        conversion rather than only to the counting, and it introduces no
        content-class constants: a table of numbers, a navbox of link labels
        and a paragraph of prose are each described by their own text rather
        than by a category somebody assigned them.

        A unit that sent no sample (nothing sampleable, or the read's sample
        budget was already spent) falls back to the page rate, which is the
        behaviour that shipped before this and is still better than nothing.
        """
        if not sample or len(sample) < 40:
            return self.rates.chars_per_token
        return _measured_rate(sample) or self.rates.chars_per_token

    def price_region(self, region: dict) -> int:
        """What expanding this region would cost, NET of its children.

        DESIGN 3.3a rule 2. The extractor's counts are already net, because
        region ownership is assigned to the INNERMOST region during the walk,
        so a parent that is genuinely just a container prices as one and says
        so rather than inheriting the sum of everything it wraps.

        **It counts the region's characters ONCE.** The first version added a
        per-affordance rate, a per-heading rate, and a per-text-block rate on
        top of the character count, and every one of those units contributes
        its own text to that same character count, so the price was two to
        three times the content. Measured against `get_text` on the same
        region across four frozen pages, the median error was 96 percent; on
        characters plus the call overhead alone it is 23 percent. That is the
        difference between a menu with prices and a menu with plausible
        numbers on it, and DESIGN 3.3a makes it a correctness requirement
        rather than a nicety.

        **And it counts CONTENT, not a call.** The price used to carry a
        40-token call overhead, from the days when the number meant "what
        this call will cost you". Phase 2 corrected that contract, because
        expanding a region returns another budgeted projection rather than
        the region: the number now answers "how much is in there", and a
        scaffold the caller pays regardless has no place inside it. The
        constant was also most of the residual error on small regions, which
        it over-priced by exactly itself."""
        net = region["net"]
        return int(self.rates.from_chars(net["chars"],
                                         self.rate_for(region.get("sample"))))

    def price_section(self, heading: dict) -> int | None:
        """What reading one named section would cost.

        DESIGN 3.3a rule 1: computed over the section's TRUE extent, which the
        extractor attributes in document order from the heading to the next
        heading of the same or higher level. Where the extent cannot be
        determined, this returns None and the projection prints no price
        rather than a number derived from a walk that found nothing.

        The section's characters are counted ONCE, for the same reason the
        region price counts its own once: an affordance inside the section
        contributes its accessible name to that character total already."""
        if not heading.get("section_known"):
            return None
        return int(self.rates.from_chars(
            heading["section_chars"],
            self.rate_for(heading.get("section_sample"))))

    def price_table(self, table: dict) -> int:
        """What the table's cells hold, at the table's OWN rate.

        This is the unit the page-level rate was worst about. A table of
        formatted numbers tokenizes at roughly half the characters per token
        of the prose around it, so on a statistical article the two most
        expensive calls on the page were the two the old price understated
        most."""
        return int(self.rates.from_chars(table["chars"],
                                         self.rate_for(table.get("sample"))))

    # -------------------------------------------------------- the accounting

    def budget_line(self, rung: int, rung_count: int) -> str:
        pct = round(100 * self.used / self.budget) if self.budget else 0
        return (f"budget: {self.used:,} of {self.budget:,} tokens used "
                f"({pct}%), {self.margin:,} held as tokenizer-drift margin, "
                f"estimator tiktoken/{ENCODING_NAME} | degradation rung "
                f"{rung} of {rung_count}")
