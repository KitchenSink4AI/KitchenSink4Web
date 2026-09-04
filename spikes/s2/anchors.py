"""S2: the server-side half of the anchor scheme, and the rebind ladder.

DESIGN 3.5 specifies two addresses per element. `ref` is a short turn-local
handle the model pays for; `anchor` is a durable content-derived descriptor
stored server-side that can be re-resolved from nothing. The stickiness claim
is that an element whose fingerprint matches an existing entry KEEPS its ref,
which is what makes deltas expressible and what makes read-once-act-many cheap.

**The one design decision this prototype had to make, because the design does
not settle it: WHICH fields go in the sticky key.** Put ordinal in and a list
reorder breaks every ref. Leave it out and two identically named buttons in one
region collide. So the key is not one tuple. It is the CHEAPEST key that is
UNIQUE in the read where it was minted, chosen from a fixed priority ladder,
and recorded with the element so a later read tries the same ladder in the same
order. A page that offers a stable attribute gets an attribute key; a page that
offers only a duplicated name falls to an ordinal key and is honestly weaker.

`data-truth` and `node_uid` arrive from the extractor as INSTRUMENTS and are
excluded from every key by construction, checked by `assert_no_instruments`.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

#: Fields the harness supplies for scoring and the scheme must never read. A
#: scheme that fingerprinted ground truth would score a perfect run.
INSTRUMENTS = ("truth", "node_uid")

#: The key ladder, cheapest and most durable first. Each entry is a name plus
#: the fields it reads. Order is the whole design: an id survives a re-render,
#: a re-order, and a route change; an ordinal survives none of them.
#:
#: **Every rung is scoped by `page_key` (origin + path + hash), and that is a
#: correction the first run of this spike forced rather than a precaution.**
#: Without it, a ref minted on one page came back bound to a same-named
#: control on a different page, silently, at the strongest tier in the ladder.
KEY_LADDER = (
    ("testid", ("page_key", "landmark", "landmark_label", "attr_testid")),
    ("id", ("page_key", "landmark", "landmark_label", "attr_id")),
    ("named-control", ("page_key", "landmark", "landmark_label", "role",
                       "attr_name")),
    ("role-name-scoped", ("page_key", "landmark", "landmark_label",
                          "labelled_ancestor", "role", "name")),
    ("role-name-landmark", ("page_key", "landmark", "landmark_label", "role",
                            "name")),
    ("role-name-ordinal", ("page_key", "landmark", "landmark_label", "role",
                           "name", "ordinal")),
    ("role-ordinal", ("page_key", "landmark", "landmark_label", "role",
                      "ordinal")),
)

#: Which ladder entries require their distinguishing attribute to be present.
_REQUIRES = {"testid": "attr_testid", "id": "attr_id",
             "named-control": "attr_name"}


def assert_no_instruments() -> None:
    """The scheme's own guard rail, asserted rather than remembered."""
    for name, fields in KEY_LADDER:
        for f in fields:
            assert f not in INSTRUMENTS, f"{name} reads the instrument {f}"


def key_of(el: dict, kind: str) -> tuple | None:
    for name, fields in KEY_LADDER:
        if name != kind:
            continue
        need = _REQUIRES.get(name)
        if need and not el.get(need):
            return None
        if name.startswith("role-name") and not el.get("name"):
            return None
        return (name,) + tuple(str(el.get(f, "")) for f in fields)
    raise KeyError(kind)


def index(elements: list[dict]) -> dict[str, dict[tuple, list[dict]]]:
    """Every key for every element, so uniqueness is a lookup rather than a
    scan. Uniqueness is per READ: a key that is unique today may collide
    tomorrow, and that is a rebind refusal rather than a mint-time error."""
    out: dict[str, dict[tuple, list[dict]]] = {}
    for kind, _ in KEY_LADDER:
        bucket: dict[tuple, list[dict]] = {}
        for el in elements:
            k = key_of(el, kind)
            if k is not None:
                bucket.setdefault(k, []).append(el)
        out[kind] = bucket
    return out


def mint_key(el: dict, idx: dict) -> tuple[str, tuple] | None:
    """The cheapest key that is unique in THIS read."""
    for kind, _ in KEY_LADDER:
        k = key_of(el, kind)
        if k is None:
            continue
        if len(idx[kind].get(k, ())) == 1:
            return kind, k
    return None


class Outcome:
    OK = "ok"                        # (a) fingerprint still matches
    REBOUND = "rebound"              # (c) exactly one match, reported
    AMBIGUOUS = "AMBIGUOUS_LOCATION"  # (d) more than one, refuse
    STALE = "STALE_ANCHOR"           # (e) zero matches, refuse
    NOT_FOUND = "NOT_FOUND"          # never minted in this session
    BAD_PARAMS = "BAD_PARAMS"        # wrong page handle
    MODAL = "MODAL_BLOCKED"          # a dialog blocks interaction


@dataclass
class Entry:
    ref: str
    handle: str
    kind: str
    key: tuple
    anchor: dict
    url: str
    doc_epoch: str = ""
    gone: bool = False
    gone_as: str = ""
    #: Minted for this turn and deliberately NOT sticky, because nothing in
    #: the ladder distinguished the element from its siblings. Recorded so a
    #: later call can say that rather than saying the ref never existed.
    turn_local: bool = False


@dataclass
class Session:
    """One session's element map, keyed by fingerprint rather than by
    snapshot, which is what makes `e12` on read one still `e12` on read
    three."""
    entries: dict[str, Entry] = field(default_factory=dict)
    by_key: dict[tuple, str] = field(default_factory=dict)
    counter: int = 0
    reads: int = 0

    # ---------------------------------------------------------------- reads

    #: Whether the two ordinal rungs may bind a ref. Off is the tightening
    #: PLAN's S2 anticipates ("more required fingerprint fields, narrower
    #: fuzzy tier") and the run reports both settings.
    weak_keys: bool = False

    def _candidates(self, el: dict, idx: dict) -> list[tuple[str, tuple]]:
        """Every key this element can offer that is UNIQUE in this read, in
        ladder order. Uniqueness is checked per read because a key that is
        unique today can collide tomorrow, and a collision must become a
        refusal rather than a silent mismatch."""
        out = []
        for kind, _ in KEY_LADDER:
            if not self.weak_keys and kind.endswith("ordinal"):
                continue
            k = key_of(el, kind)
            if k is not None and len(idx[kind].get(k, ())) == 1:
                out.append((kind, k))
        return out

    def read(self, extraction: dict, handle: str = "p1") -> dict:
        """Mint refs for a read. An element whose key matches an existing
        entry KEEPS its ref; a new element gets a new one; a missing element
        is marked gone rather than deleted, so a later error can say what
        `e12` used to be.

        Every unique key an element offers is registered against its ref, not
        just the cheapest one, so a later read can recognise it through
        whichever of its addresses survived. Lookup still walks the ladder
        strongest-first, which is what keeps an id from losing to an ordinal."""
        self.reads += 1
        elements = extraction["elements"]
        idx = index(elements)
        seen: set[str] = set()
        result = []
        for el in elements:
            cands = self._candidates(el, idx)
            if not cands:
                # Nothing in the ladder distinguishes this element from its
                # neighbours in its own read. It still gets a ref for this
                # turn; it just cannot be sticky, and the scheme says so
                # rather than inventing a key that will collide later.
                self.counter += 1
                ref = f"e{self.counter}"
                self.entries[ref] = Entry(
                    ref=ref, handle=handle, kind="turn-local", key=(),
                    anchor=dict(el), url=extraction["url"],
                    doc_epoch=extraction.get("doc_epoch", ""), turn_local=True)
                seen.add(ref)
                result.append({"ref": ref, "sticky": False, "el": el})
                continue
            ref = None
            kind, key = cands[0]
            for k_kind, k_key in cands:
                prior = self.by_key.get((handle, k_kind) + k_key)
                if prior is not None and prior not in seen:
                    ref, kind, key = prior, k_kind, k_key
                    break
            reused = ref is not None
            if ref is None:
                self.counter += 1
                ref = f"e{self.counter}"
            for k_kind, k_key in cands:
                self.by_key[(handle, k_kind) + k_key] = ref
            self.entries[ref] = Entry(ref=ref, handle=handle, kind=kind,
                                      key=key, anchor=dict(el),
                                      url=extraction["url"],
                                      doc_epoch=extraction.get("doc_epoch", ""))
            seen.add(ref)
            result.append({"ref": ref, "sticky": True, "el": el,
                           "reused": reused, "key_kind": kind})
        for ref, entry in self.entries.items():
            if entry.handle == handle and ref not in seen and not entry.gone:
                entry.gone = True
                entry.gone_as = f"{entry.anchor.get('role')} \"{entry.anchor.get('name')}\""
        return {"minted": result, "index": idx, "extraction": extraction}

    # -------------------------------------------------------------- resolve

    def resolve(self, ref: str, state: dict, handle: str = "p1",
                allow_cross_page_rebind: bool = False,
                fuzzy: bool = True,
                cross_page_test: str = "url") -> dict:
        """The rebind ladder, with DESIGN 3.5's entry conditions checked
        first and in order. None of the entry conditions enters the fuzzy
        tier, which is the point of having them."""
        extraction = state["extraction"]
        idx = state["index"]

        # Entry condition 1: a modal blocks interaction, before any resolution
        # is attempted at all.
        if extraction.get("modal"):
            return {"outcome": Outcome.MODAL, "dialog": extraction["modal"],
                    "recovery": "click the dialog's own control, or "
                                "manage_session(action='dismiss_dialog')"}
        # Entry condition 2: never minted in this session.
        entry = self.entries.get(ref)
        if entry is None:
            return {"outcome": Outcome.NOT_FOUND,
                    "recovery": "refs are minted only by a read in this "
                                "session; call get_page_view first"}
        # Entry condition 3: minted against a different page handle.
        if entry.handle != handle:
            return {"outcome": Outcome.BAD_PARAMS, "minted_on": entry.handle,
                    "asked_for": handle}
        # Entry condition 5: the URL moved and cross-page rebinding is off. A
        # fuzzy match on a different URL IS a cross-page rebind under another
        # name, so this refuses before the ladder rather than inside it.
        # Two candidate definitions of "a different page", measured against
        # each other rather than assumed to be the same. `url` is what DESIGN
        # 3.5 says literally. `document` asks whether a navigation actually
        # happened, which is the question an SPA route change answers
        # differently: pushState moves the URL and keeps the document.
        if cross_page_test == "document":
            url_changed = entry.doc_epoch != extraction.get("doc_epoch", "")
        else:
            url_changed = entry.url != extraction["url"]
        if url_changed and not allow_cross_page_rebind:
            return {"outcome": Outcome.STALE, "reason": "url-changed",
                    "was": entry.url, "now": extraction["url"],
                    "gone_as": entry.gone_as or None,
                    "recovery": "re-read the page, or pass "
                                "allow_cross_page_rebind=true"}

        # A turn-local ref. It WAS minted, so NOT_FOUND would be a lie, and
        # nothing distinguishes its element from its siblings, so any tier of
        # the ladder would be a coin flip dressed as a resolution. The honest
        # answer is the ambiguity that made it turn-local in the first place.
        if entry.turn_local:
            a = entry.anchor
            same = [el for el in extraction["elements"]
                    if el["role"] == a["role"] and el["name"] == a["name"]]
            return {"outcome": Outcome.AMBIGUOUS, "tier": "turn-local ref",
                    "reason": "nothing in the anchor ladder distinguishes this "
                              "element from its siblings, so its ref was never "
                              "sticky",
                    "candidates": [
                        {"name": m["name"], "role": m["role"],
                         "landmark": m["landmark"], "ordinal": m["ordinal"]}
                        for m in same]}

        # (a) the key still resolves to exactly one element: proceed.
        hits = idx[entry.kind].get(key_of(entry.anchor, entry.kind) or (), [])
        if len(hits) == 1 and not entry.gone:
            return {"outcome": Outcome.OK, "element": hits[0],
                    "tier": "fingerprint"}

        # (b) re-resolve the stored anchor. Exact role plus name within the
        # original landmark, then role plus name anywhere, then name-only
        # fuzzy.
        a = entry.anchor
        elements = extraction["elements"]
        tiers = [
            ("role+name in landmark", [
                el for el in elements
                if el["role"] == a["role"] and el["name"] == a["name"]
                and el["landmark"] == a["landmark"]
                and el["landmark_label"] == a["landmark_label"]]),
            ("role+name anywhere", [
                el for el in elements
                if el["role"] == a["role"] and el["name"] == a["name"]]),
        ]
        if fuzzy:
            tiers.append(("name-only fuzzy", [
                el for el in elements
                if a["name"] and el["name"]
                and difflib.SequenceMatcher(
                    None, a["name"].lower(), el["name"].lower()).ratio() >= 0.85]))
        for tier, matches in tiers:
            if not matches:
                continue
            if len(matches) == 1:
                return {"outcome": Outcome.REBOUND, "element": matches[0],
                        "tier": tier, "was": entry.gone_as or
                        f'{a["role"]} "{a["name"]}"'}
            # (d) more than one match. House rule, absolute: no tool ever acts
            # on first match.
            return {"outcome": Outcome.AMBIGUOUS, "tier": tier,
                    "candidates": [
                        {"name": m["name"], "role": m["role"],
                         "landmark": m["landmark"], "ordinal": m["ordinal"]}
                        for m in matches]}
        # (e) zero matches anywhere.
        near = difflib.get_close_matches(
            a["name"], [el["name"] for el in elements if el["name"]], 1, 0.5)
        return {"outcome": Outcome.STALE, "reason": "no match",
                "gone_as": entry.gone_as or None,
                "nearest": near[0] if near else None,
                "recovery": "re-read the page and use the ref it returns"}
