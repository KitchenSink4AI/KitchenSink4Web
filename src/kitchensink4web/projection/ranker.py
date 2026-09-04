"""Affordance selection: per-class quotas with guaranteed floors.

DESIGN 3.3 block 3, and it is a correction rather than a refinement. S1 ranked
the whole interactive surface with one proximity score (in-viewport +40,
main-or-dialog +30, size, semantic weight) and capped the result. On
`github.com/microsoft/playwright` that surfaced dozens of truncated
commit-message links and **buried all thirteen tabs of the repository
navigation bar**, including Issues, so a blind agent asked to open the
repository's issues could not name a call. It was not a budget failure: the
projection used 2,238 of 5,000 tokens and the whole tab bar would have cost
roughly 130. The ranker threw away the answer while under budget.

The same score fails in the other direction on a long article, where
"in-viewport" means the lead paragraph and the top forty affordances come back
as citation markers.

So selection is by CLASS first and rank second:

| Class | Quota |
|---|---|
| navigation | guaranteed floor, filled before any other class |
| form controls | complete whenever the form fits, never sampled |
| primary actions | high quota |
| in-prose links | **zero** |

The zero quota is the load-bearing one. On the Treaty of Versailles article it
removes roughly 2,700 of 2,858 affordances and costs nothing, because no agent
was ever going to find its link inside a forty-item sample of 2,858. Those
links belong to the content digest, which names the sections they live in, and
to `find_elements`, which retrieves one by name for tens of tokens. What makes
that honest rather than lossy is that the completeness block states the
suppressed count and the class it belongs to.
"""

from __future__ import annotations

import math

#: Filled in this order. Navigation first, deliberately: it is what an agent
#: asks for most and it is small.
CLASS_ORDER = ("nav", "form_control", "primary", "other", "prose_link")

CLASS_LABEL = {
    "nav": "site and page navigation",
    "form_control": "form controls",
    "primary": "primary actions",
    "other": "other controls",
    "prose_link": "in-prose links",
}


def rank_score(aff: dict) -> float:
    """Rank WITHIN a class. Never across classes, which is the whole point."""
    score = 0.0
    if aff.get("name"):
        score += 8
    else:
        score -= 6
    if aff.get("in_viewport"):
        score += 6
    score += min(6.0, math.sqrt(max(0, aff.get("area", 0))) / 20.0)
    score -= min(6.0, (aff.get("top", 0) or 0) / 2000.0)
    if aff.get("state"):
        score += 1
    return score


def select(affordances: list[dict], quotas: dict[str, int],
           class_totals: dict[str, int] | None = None) -> tuple[
        list[dict], dict[str, int]]:
    """Return (selected, suppressed_by_class).

    Form controls are complete or they are honestly incomplete: a half-listed
    form is not a form, so the class either fits under its quota entirely or
    reports how many it dropped.

    `class_totals` is the extractor's tally over EVERY interactive element,
    including any past its return cap. Suppression counts come from it rather
    than from the list in hand, so the completeness figure is the page's
    number and not the payload's."""
    by_class: dict[str, list[dict]] = {c: [] for c in CLASS_ORDER}
    for aff in affordances:
        by_class.setdefault(aff.get("cls", "other"), []).append(aff)
    totals = dict(class_totals or {})

    selected: list[dict] = []
    suppressed: dict[str, int] = {}
    for cls in CLASS_ORDER:
        members = by_class.get(cls, [])
        total = totals.get(cls, len(members))
        quota = quotas.get(cls, 0)
        if not members and not total:
            continue
        if quota <= 0:
            suppressed[cls] = total
            continue
        if len(members) <= quota:
            selected.extend(members)
            if total > len(members):
                suppressed[cls] = total - len(members)
            continue
        members = sorted(members, key=rank_score, reverse=True)
        selected.extend(members[:quota])
        suppressed[cls] = total - quota
    # Document order for the printed list: an agent reads a page top to
    # bottom and a ranked jumble reads as noise even when every item earned
    # its place.
    order = {aff["ref"]: i for i, aff in enumerate(affordances)}
    selected.sort(key=lambda a: order.get(a["ref"], 0))
    return selected, suppressed


def disambiguate(selected: list[dict]) -> dict[str, str]:
    """A discriminator for every printed affordance that needs one.

    DESIGN 3.3: never collapse two elements onto one line without a
    distinguishing token, and never group them at all if no discriminator can
    be computed. S1 emitted `e13` and `e42` as two buttons both labelled
    "Search (x2)" in the same region, and grouped `e216,e134` out of numeric
    order, so the grouping was not even positional. KS4Web prints every
    element on its own line and adds the SMALLEST sufficient discriminator:
    the href path, then the containing region, then the ordinal within its
    role."""
    seen: dict[tuple, list[dict]] = {}
    for aff in selected:
        seen.setdefault((aff.get("role"), aff.get("name")), []).append(aff)
    out: dict[str, str] = {}
    for (_role, _name), group in seen.items():
        if len(group) < 2:
            continue
        paths = {a.get("path") for a in group}
        regions = {a.get("region_label") for a in group}
        for aff in group:
            if len(paths) == len(group) and aff.get("path"):
                out[aff["ref"]] = ""          # the path is already printed
            elif len(regions) == len(group) and aff.get("region_label"):
                out[aff["ref"]] = f"in {aff['region_label']}"
            else:
                out[aff["ref"]] = f"#{aff.get('ordinal', 0)} of its role"
    return out
