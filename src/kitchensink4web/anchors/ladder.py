"""The rebind ladder: how a ref becomes an element, or honestly refuses.

DESIGN 3.5. Every action tool resolves a ref through this before it touches
anything. The five outcomes (a) through (e) are exhaustive for *resolving a
known ref on the current page*, and they say nothing about how a call gets to
the ladder in the first place, so six entry conditions are decided first and
none of them enters a fuzzy tier.

**A false rebind is worse than a failure**, because a failure is visible and a
false rebind clicks the wrong thing while reporting success. That is the whole
weighting of this module: it refuses often and it never acts on first match.
S2 measured the result at **zero false rebinds and zero false stickiness
across 396 resolutions in 18 scenarios**, against real React 18.3.1 and real
react-window 1.8.10.

**One ordering correction, found building this and reported as a design
finding.** DESIGN 3.5's entry-condition table lists the gone-marked row ABOVE
the URL-changed row. Evaluated in that printed order, a gone-marked ref skips
straight to re-resolution (b), and after a navigation EVERY ref on the page is
gone-marked by the next read, so the URL test below it would never run and
cross-page rebinding would be on by default for exactly the refs most likely
to rebind wrongly. The URL condition is therefore evaluated FIRST here, which
is the order S2 measured zero false rebinds under. The outcomes are unchanged;
only the order is, and the table in DESIGN is corrected to match.
"""

from __future__ import annotations

import difflib

from . import keys as _keys


class Outcome:
    OK = "ok"                          # (a) the fingerprint still matches
    REBOUND = "rebound"                # (c) exactly one match, reported
    AMBIGUOUS = "AMBIGUOUS_LOCATION"   # (d) more than one, refuse
    STALE = "STALE_ANCHOR"             # (e) zero matches, refuse
    NOT_FOUND = "NOT_FOUND"            # never minted in this session
    BAD_PARAMS = "BAD_PARAMS"          # a ref from a different page handle
    MODAL = "MODAL_BLOCKED"            # a dialog blocks interaction


def _candidates(anchor: dict, matches: list[dict]) -> list[dict]:
    return [{"role": m.get("role"), "name": m.get("name"),
             "landmark": m.get("landmark"),
             "landmark_label": m.get("landmark_label"),
             "ordinal": m.get("ordinal")} for m in matches[:12]]


def resolve(element_map, ref: str, extraction: dict, handle: str,
            kind: str = "affordance",
            allow_cross_page_rebind: bool = False) -> dict:
    """Resolve one ref against the page as it is RIGHT NOW.

    `extraction` is a fresh read of the live page, so every resolution is
    against current truth rather than against the snapshot the ref was minted
    in. That is the whole point of a content-derived anchor."""
    identity = extraction.get("identity", {})
    url = identity.get("url", "")

    # ---------------------------------------------------- entry conditions

    # 1. A pending modal blocks interaction before any resolution is
    #    attempted at all, and it beats every other condition including a ref
    #    that was never minted. S2 asserts the ORDER by asking with a ref
    #    that would otherwise refuse NOT_FOUND.
    if extraction.get("modal"):
        return {"outcome": Outcome.MODAL, "dialog": extraction["modal"],
                "recovery": "dismiss the dialog with its own control first; "
                            "a click behind a modal is not the click you "
                            "asked for even when the element is present"}

    entry = element_map.entries.get(ref)
    # 2. Never minted in this session: a model typo, or a ref quoted from
    #    another session or a saved workflow.
    if entry is None:
        return {"outcome": Outcome.NOT_FOUND, "ref": ref,
                "recovery": "refs are minted only by a read in THIS session; "
                            "call get_page_view(page=...) and use the ref it "
                            "returns"}
    # 3. Minted against a different page handle. Never silently retargeted.
    if entry.handle != handle:
        return {"outcome": Outcome.BAD_PARAMS, "ref": ref,
                "minted_on": entry.handle, "asked_for": handle,
                "recovery": f"{ref} belongs to page {entry.handle}; pass that "
                            f"handle, or re-read {handle} for its own refs"}
    # 4. The URL moved and cross-page rebinding is off. A fuzzy match on a
    #    different URL IS a cross-page rebind under another name, so this
    #    refuses BEFORE the ladder rather than inside it. The test is literal:
    #    S2 measured document identity as the plausible refinement and it
    #    fails in both directions at once, rebinding across a route change and
    #    refusing everything after a reload that returned to the same page.
    if entry.url != url and not allow_cross_page_rebind:
        return {"outcome": Outcome.STALE, "ref": ref, "reason": "url-changed",
                "was": entry.url, "now": url,
                "gone_as": entry.gone_as or None,
                "recovery": "re-read the page and use the refs it returns. "
                            "allow_cross_page_rebind=true exists and is off "
                            "by default: turning it on produced 6 false "
                            "rebinds in 22 attempts on a page carrying the "
                            "same landmarks and the same control names"}

    anchors = [u.get("anchor") or {} for u in _units(extraction, entry.kind)]
    units = _units(extraction, entry.kind)

    # 5. A turn-local ref. It WAS minted, so NOT_FOUND would be a lie, and
    #    nothing distinguishes its element from its siblings, so any tier of
    #    the ladder would be a coin flip dressed as a resolution. The honest
    #    answer is the ambiguity that made it turn-local in the first place.
    #    S2 added this row after finding the obvious implementation refusing
    #    NOT_FOUND here, which sends the caller to re-read the page when
    #    re-reading is exactly what will not help.
    if entry.turn_local:
        a = entry.anchor
        same = [m for m in anchors
                if m.get("role") == a.get("role")
                and m.get("name") == a.get("name")]
        return {"outcome": Outcome.AMBIGUOUS, "ref": ref,
                "tier": "turn-local ref",
                "reason": "nothing in the anchor key ladder distinguishes "
                          "this element from its siblings, so its ref was "
                          "never sticky",
                "candidates": _candidates(a, same),
                "recovery": "address it with a narrower locator: "
                            "find_elements(query=...) with the surrounding "
                            "text, or a css or xpath selector"}

    # 6. A gone-marked entry skips to (b) and re-resolves the stored anchor,
    #    carrying the gone record into whatever message results.

    # ----------------------------------------------------------- the ladder

    idx = _keys.index(anchors)
    key = _keys.key_of(entry.anchor, entry.key_kind) \
        if entry.key_kind in _keys.KEY_KINDS else None
    hits = idx.get(entry.key_kind, {}).get(key or (), []) if key else []
    # (a) found, still attached, fingerprint still matches.
    if len(hits) == 1 and not entry.gone:
        return {"outcome": Outcome.OK, "ref": ref, "tier": "fingerprint",
                "unit": units[hits[0]], "key_kind": entry.key_kind}

    # (b) handle detached or fingerprint changed: re-resolve the stored
    #     anchor. Exact role plus name within the original landmark, then role
    #     plus name anywhere. There is no third tier: the name-only fuzzy tier
    #     is CUT from v1 on measurement, because across every S2 scenario it
    #     changed no resolution's correctness and its entire effect was to
    #     convert STALE refusals into AMBIGUOUS ones.
    a = entry.anchor
    tiers = (
        ("role+name in landmark", [
            i for i, m in enumerate(anchors)
            if m.get("role") == a.get("role") and m.get("name") == a.get("name")
            and m.get("landmark") == a.get("landmark")
            and m.get("landmark_label") == a.get("landmark_label")]),
        ("role+name anywhere", [
            i for i, m in enumerate(anchors)
            if m.get("role") == a.get("role")
            and m.get("name") == a.get("name")]),
    )
    for tier, positions in tiers:
        if not positions:
            continue
        if len(positions) == 1:
            # (c) exactly one match. Proceed, and report it. NEVER silently:
            #     a rebind the transcript cannot see is the same disease as a
            #     silent false success.
            return {"outcome": Outcome.REBOUND, "ref": ref, "tier": tier,
                    "unit": units[positions[0]],
                    "was": entry.gone_as or
                          f'{a.get("role")} "{a.get("name")}"',
                    "now": f'{anchors[positions[0]].get("role")} '
                           f'"{anchors[positions[0]].get("name")}"'}
        # (d) more than one match. House rule, inherited and absolute: no
        #     tool ever acts on first match.
        return {"outcome": Outcome.AMBIGUOUS, "ref": ref, "tier": tier,
                "candidates": _candidates(a, [anchors[i] for i in positions]),
                "recovery": "name one of the candidates above with "
                            "find_elements, or re-read the page"}

    # (e) zero matches anywhere.
    names = [m.get("name") for m in anchors if m.get("name")]
    # A generous cutoff on purpose. The commonest real change is a label that
    # GAINED words ("Save" becoming "Saved changes", ratio 0.47), and the
    # whole job of this line is to turn a dead end into a one-turn recovery,
    # so a hint that only fires on near-identical strings would be a hint
    # that fires when the caller did not need one.
    near = difflib.get_close_matches(a.get("name") or "", names, 1, 0.4)
    return {"outcome": Outcome.STALE, "ref": ref, "reason": "no match",
            "was": entry.gone_as or f'{a.get("role")} "{a.get("name")}"',
            "landmark_present": any(
                m.get("landmark") == a.get("landmark")
                and m.get("landmark_label") == a.get("landmark_label")
                for m in anchors),
            "nearest_by_name": near[0] if near else None,
            "recovery": "re-read the page and use the ref it returns"}


def resolve_anchor(anchor: dict, extraction: dict,
                   kind: str = "affordance") -> dict:
    """Resolve a STORED anchor descriptor against the page as it is right
    now, with no session ref involved. This is replay's resolver (DESIGN
    5.6): a saved workflow records anchors rather than refs because a later
    session has no refs, and the dry run's whole job is to run this for
    every step before anything executes.

    Same weighting as `resolve()`: strongest keys first, the two role+name
    tiers after, no fuzzy tier, no first-match action, ambiguity and absence
    refuse with the same vocabulary. The page key is checked FIRST, because
    an anchor minted on one page resolving on another is the cross-page
    rebind S2 priced at 27 percent false."""
    if extraction.get("modal"):
        return {"outcome": Outcome.MODAL, "dialog": extraction["modal"],
                "recovery": "dismiss the dialog with its own control first"}

    identity = extraction.get("identity", {})
    page_key = identity.get("page_key") or identity.get("url", "")
    want_key = anchor.get("page_key")
    if want_key and page_key and want_key != page_key:
        return {"outcome": Outcome.STALE, "reason": "page-key-differs",
                "was": f'{anchor.get("role")} "{anchor.get("name")}" on '
                       f'{want_key}',
                "now": page_key,
                "recovery": "navigate to the page this anchor was recorded "
                            "on; replay runs its own navigate steps first"}

    units = _units(extraction, kind)
    anchors = [u.get("anchor") or {} for u in units]
    idx = _keys.index(anchors)

    # Strongest first: every unique key the stored anchor offers, against
    # the live read's own uniqueness index.
    for key_kind in _keys.KEY_KINDS:
        key = _keys.key_of(anchor, key_kind)
        if key is None:
            continue
        hits = idx.get(key_kind, {}).get(key, [])
        if len(hits) == 1:
            return {"outcome": Outcome.OK, "tier": key_kind,
                    "unit": units[hits[0]]}

    tiers = (
        ("role+name in landmark", [
            i for i, m in enumerate(anchors)
            if m.get("role") == anchor.get("role")
            and m.get("name") == anchor.get("name")
            and m.get("landmark") == anchor.get("landmark")
            and m.get("landmark_label") == anchor.get("landmark_label")]),
        ("role+name anywhere", [
            i for i, m in enumerate(anchors)
            if m.get("role") == anchor.get("role")
            and m.get("name") == anchor.get("name")]),
    )
    for tier, positions in tiers:
        if not positions:
            continue
        if len(positions) == 1:
            return {"outcome": Outcome.REBOUND, "tier": tier,
                    "unit": units[positions[0]],
                    "was": f'{anchor.get("role")} "{anchor.get("name")}"',
                    "now": f'{anchors[positions[0]].get("role")} '
                           f'"{anchors[positions[0]].get("name")}"'}
        return {"outcome": Outcome.AMBIGUOUS, "tier": tier,
                "candidates": _candidates(anchor,
                                          [anchors[i] for i in positions]),
                "recovery": "the page now holds several elements this anchor "
                            "matches; re-record the workflow against the "
                            "current page"}

    names = [m.get("name") for m in anchors if m.get("name")]
    near = difflib.get_close_matches(anchor.get("name") or "", names, 1, 0.4)
    return {"outcome": Outcome.STALE, "reason": "no match",
            "was": f'{anchor.get("role")} "{anchor.get("name")}"',
            "nearest_by_name": near[0] if near else None,
            "recovery": "the element this step was recorded against is no "
                        "longer on the page; re-record the workflow"}


def _units(extraction: dict, kind: str) -> list[dict]:
    return {
        "affordance": extraction.get("affordances") or [],
        "region": extraction.get("regions") or [],
        "heading": extraction.get("headings") or [],
        "form": extraction.get("forms") or [],
        "table": extraction.get("tables") or [],
    }[kind]


# --------------------------------------------------------- batch semantics


PROCEED = (Outcome.OK, Outcome.REBOUND)
#: A batch STOPS on these. Browser actions do not roll back, so completed
#: items stay completed and the remainder is reported `not_attempted`.
STOPS_THE_BATCH = (Outcome.AMBIGUOUS, Outcome.STALE, Outcome.NOT_FOUND,
                   Outcome.BAD_PARAMS, Outcome.MODAL)


def batch_outcome(per_item: list[dict]) -> dict:
    """Roll a batch's per-item outcomes into the envelope DESIGN 3.5 defines.

    Validating every anchor at batch start, the pattern inherited from the
    sibling servers, does not survive mutations the batch itself causes:
    typing into field one of a real form routinely re-renders its siblings, so
    a fingerprint change partway through a batch is the ORDINARY case on SPA
    forms rather than an adversarial corner. So every ref resolves before
    anything executes, and each target is re-checked immediately before its
    own execution. A batch never skips a failed item and continues, and never
    retries silently."""
    completed = [r for r in per_item if r.get("status") == "completed"]
    rebound = [r for r in per_item if r.get("outcome") == Outcome.REBOUND]
    failed = next((r for r in per_item
                   if r.get("outcome") in STOPS_THE_BATCH), None)
    not_attempted = [r for r in per_item
                     if r.get("status") == "not_attempted"]
    return {
        "items": per_item,
        "completed": len(completed),
        "rebound": len(rebound),
        "stopped_at": failed.get("ref") if failed else None,
        "stopped_because": failed.get("outcome") if failed else None,
        "not_attempted": [r.get("ref") for r in not_attempted],
        "rollback": "none. Browser actions do not roll back, so the items "
                    "listed as completed above HAVE happened and the form "
                    "state read-back is the authority on what the page now "
                    "holds.",
    }
