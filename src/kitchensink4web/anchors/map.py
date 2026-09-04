"""The sticky element map: `e12` on read one is still `e12` on read three.

DESIGN 3.5. The map is keyed by the anchor fingerprint rather than by the
snapshot, which is the whole difference from the incumbent scheme. S2 measured
the property rather than assuming it, and the number that settles the argument
is a pair: forcing React to unmount and remount a route subtree destroyed
**77 percent of the DOM nodes** under it and **100 percent of distinguishable
elements kept their refs**. The incumbent's key, a `backendNodeId`, is
precisely what that re-render destroyed.

Every unit the projection prints gets a ref from here, not only the
affordances, because a delta over half a payload is not a delta and
`location={"region":"r7"}` in a NEXT CALLS line has to still mean r7 after a
re-read. Regions, headings, forms, and tables travel the same machinery under
their own namespaces.

Removed elements keep their entry MARKED GONE rather than being deleted, so a
later error can say what `e12` used to be instead of only that it is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keys as _keys

#: One namespace per printed unit kind: the ref prefix, and the descriptor
#: fields whose change should be reported by a delta.
NAMESPACES: dict[str, str] = {
    "affordance": "e",
    "region": "r",
    "heading": "h",
    "form": "f",
    "table": "t",
}


@dataclass
class Entry:
    """One durable address, stored server-side and normally never in context.

    The model pays for `e12`; KS4Web keeps the durability. Anchors surface in
    exactly two places by design (DESIGN 3.5): `get_audit` records the anchor
    id alongside every resolved action, and a saved workflow records anchors
    rather than refs, because a replay in a later session has no refs."""

    ref: str
    kind: str                      # the namespace: affordance, region, ...
    handle: str                    # the page handle it was minted against
    key_kind: str                  # which ladder rung bound it
    key: tuple
    anchor: dict
    url: str
    page_key: str
    doc_epoch: str = ""
    gone: bool = False
    gone_as: str = ""
    #: Minted for this turn and deliberately NOT sticky, because nothing in
    #: the ladder distinguished the element from its siblings. Recorded so a
    #: later call can say THAT rather than saying the ref never existed, which
    #: is the lie S2 caught the obvious implementation telling.
    turn_local: bool = False


@dataclass
class ReadState:
    """One read, kept so a later `since=` can be answered against it."""

    token: str
    handle: str
    url: str
    page_key: str
    #: ref -> the descriptor as it stood at that read.
    units: dict[str, dict] = field(default_factory=dict)
    #: ref -> the live in-page id the extractor assigned in that read, which
    #: is what `window.__ks4web_refs` is keyed by.
    node_refs: dict[str, str] = field(default_factory=dict)
    ts: str = ""
    #: The ref this read was scoped to, or None for a whole-page read. A
    #: delta between two different scopes is not a delta, and the store
    #: refuses one rather than reporting the rest of the page as removed.
    scope: str | None = None


class ElementMap:
    """One session's map. Refs are unique across the SESSION, not per page, so
    a bare `e12` is never ambiguous and the envelope always states which page
    it belongs to."""

    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}
        #: (handle, kind, key_kind) + key -> ref. Every unique key an element
        #: offers is registered here, not only the cheapest, which is what
        #: lets a control survive a change to its own accessible name.
        self.by_key: dict[tuple, str] = {}
        self.counters: dict[str, int] = {k: 0 for k in NAMESPACES}
        self.latest: dict[str, ReadState] = {}
        #: handle -> {ref: node_ref}, MERGED across reads rather than
        #: replaced. A scoped read (`location={"region":"r7"}`) sees only the
        #: units inside its scope, so replacing this map with the scoped
        #: read's own would forget every other region on the page and the
        #: NEXT call the projection just advertised would refuse. That is the
        #: read-once-expand-many flow, and it broke the first time the
        #: executable-price harness expanded two regions from one read.
        self.node_refs: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------- minting

    def _mint(self, kind: str) -> str:
        self.counters[kind] += 1
        return f"{NAMESPACES[kind]}{self.counters[kind]}"

    def absorb(self, extraction: dict, handle: str, token: str,
               ts: str = "", scope: str | None = None) -> ReadState:
        """Give every printed unit in this read its session ref, IN PLACE.

        The extractor numbers what it finds in document order, which is a
        per-read numbering and cannot be sticky. So each unit's extractor id
        is kept as `node_ref` (that is the key `window.__ks4web_refs` holds,
        and therefore how an action tool reaches the real element), and `ref`
        is overwritten with the session ref the map decides. The renderer
        never learns the difference, and no second evaluate is needed."""
        identity = extraction.get("identity", {})
        url = identity.get("url", "")
        page_key = identity.get("page_key", url)
        doc_epoch = identity.get("doc_epoch", "")
        state = ReadState(token=token, handle=handle, url=url,
                          page_key=page_key, ts=ts, scope=scope)
        seen: set[str] = set()

        remap: dict[str, dict[str, str]] = {}
        for kind in NAMESPACES:
            units = _units_of(extraction, kind)
            anchors = [u.get("anchor") or {} for u in units]
            idx = _keys.index(anchors)
            table: dict[str, str] = {}
            for unit, anchor in zip(units, anchors):
                node_ref = unit.get("ref")
                ref = self._bind(kind, anchor, handle, url, page_key,
                                 doc_epoch, idx, seen)
                unit["node_ref"] = node_ref
                unit["ref"] = ref
                seen.add(ref)
                if node_ref:
                    table[node_ref] = ref
                state.units[ref] = dict(anchor)
                state.units[ref]["_state"] = unit.get("state", "")
                state.units[ref]["_kind"] = kind
                # Carried so a delta can tell "this is new" from "this was
                # never sticky and got re-minted", which are different facts
                # and only one of them is news.
                state.units[ref]["_turn_local"] = (
                    self.entries[ref].turn_local)
                state.node_refs[ref] = node_ref
            remap[kind] = table
        # Every id is decided before anything that POINTS at an id is
        # rewritten. Renaming a unit without renaming its referrers would
        # leave the payload naming refs that no longer exist, which is the
        # same disease as a stale ref wearing a different hat.
        _relabel_cross_references(extraction, remap)

        # An element that was on this page and is not in this read is GONE,
        # not deleted. The record is what lets a later refusal say what the
        # ref used to be. **A SCOPED read never marks anything gone**: it
        # looked at one region, so "not in this read" says nothing at all
        # about the rest of the page, and treating it as evidence would mark
        # most of the page dead every time a caller expanded a section.
        if scope is None:
            for ref, entry in self.entries.items():
                if entry.handle == handle and ref not in seen                         and not entry.gone:
                    entry.gone = True
                    entry.gone_as = (f'{entry.anchor.get("role")} '
                                     f'"{entry.anchor.get("name")}"')
        self.latest[handle] = state
        self.node_refs.setdefault(handle, {}).update(state.node_refs)
        return state

    def _bind(self, kind: str, anchor: dict, handle: str, url: str,
              page_key: str, doc_epoch: str, idx: dict,
              seen: set[str]) -> str:
        candidates = _keys.unique_keys(anchor, idx)
        if not candidates:
            # Nothing in the ladder distinguishes this element from its
            # neighbours in its own read. It still gets a ref for this turn;
            # it just cannot be sticky, and the map says so rather than
            # inventing a key that will collide later.
            ref = self._mint(kind)
            self.entries[ref] = Entry(
                ref=ref, kind=kind, handle=handle, key_kind="turn-local",
                key=(), anchor=dict(anchor), url=url, page_key=page_key,
                doc_epoch=doc_epoch, turn_local=True)
            return ref

        ref = None
        key_kind, key = candidates[0]
        # Strongest first: an id key must not lose to a role-plus-name key
        # that happens to have been registered by some other element.
        for candidate_kind, candidate_key in candidates:
            prior = self.by_key.get((handle, kind, candidate_kind)
                                    + candidate_key)
            if prior is not None and prior not in seen:
                ref, key_kind, key = prior, candidate_kind, candidate_key
                break
        if ref is None:
            ref = self._mint(kind)
        for candidate_kind, candidate_key in candidates:
            self.by_key[(handle, kind, candidate_kind) + candidate_key] = ref
        self.entries[ref] = Entry(
            ref=ref, kind=kind, handle=handle, key_kind=key_kind, key=key,
            anchor=dict(anchor), url=url, page_key=page_key,
            doc_epoch=doc_epoch)
        return ref

    # -------------------------------------------------------- invalidation

    def invalidate_page(self, handle: str, why: str) -> int:
        """Navigation, page close, or session end. Refs minted on a page do
        not survive it, and the count is returned so the caller can say so."""
        touched = 0
        for ref, entry in self.entries.items():
            if entry.handle == handle and not entry.gone:
                entry.gone = True
                entry.gone_as = (f'{entry.anchor.get("role")} '
                                 f'"{entry.anchor.get("name")}" ({why})')
                touched += 1
        self.latest.pop(handle, None)
        self.node_refs.pop(handle, None)
        return touched


def _units_of(extraction: dict, kind: str) -> list[dict]:
    return {
        "affordance": extraction.get("affordances") or [],
        "region": extraction.get("regions") or [],
        "heading": extraction.get("headings") or [],
        "form": extraction.get("forms") or [],
        "table": extraction.get("tables") or [],
    }[kind]


def _relabel_cross_references(extraction: dict,
                              remap: dict[str, dict[str, str]]) -> None:
    """Rewrite the extractor's ids wherever one unit points at another.

    Regions name their parent and their children, affordances name the region
    and the heading they sit under, forms and tables name their region, and
    the completeness block names the region a virtualized container or a
    canvas lives in."""
    regions = remap["region"]
    headings = remap["heading"]

    for region in _units_of(extraction, "region"):
        if region.get("parent") in regions:
            region["parent"] = regions[region["parent"]]
        region["children"] = [regions.get(c, c)
                              for c in region.get("children", [])]
    for group in ("affordances", "headings", "forms", "tables"):
        for unit in extraction.get(group) or []:
            if unit.get("region") in regions:
                unit["region"] = regions[unit["region"]]
            if unit.get("region_label") is None:
                unit["region_label"] = None
            if unit.get("heading") in headings:
                unit["heading"] = headings[unit["heading"]]
    completeness = extraction.get("completeness") or {}
    for group in ("virtual", "canvases", "frames"):
        for entry in completeness.get(group) or []:
            if entry.get("region") in regions:
                entry["region"] = regions[entry["region"]]
    shape = extraction.get("shape") or {}
    if shape.get("readable_region") in regions:
        shape["readable_region"] = regions[shape["readable_region"]]
