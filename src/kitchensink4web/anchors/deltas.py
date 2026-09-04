"""Deltas over sticky refs: `since=<read token>` returns only what changed.

DESIGN 3.5. The measurement's structural insight is that actions are already
cheap (9 to 56 tokens) and refs are the toll gate, so a durable ref makes one
read pay for an entire multi-step interaction. Deltas are impossible without
sticky refs, which is why the two designs are one design, and DEMAND calls
them "the number one unmet ask in the whole corpus" with every major server
re-sending the entire page every step.

**Retention is bounded and stated rather than unlimited and hoped for.** Read
tokens are kept per page handle under an LRU of the most recent
`RETAINED_READS`, and they invalidate on navigation of that page, on close of
the page handle, and on session end. A token that has aged out or been
invalidated is not an error the model has to guess at: the delta refuses with
the reason and names the full read that re-establishes a baseline.
"""

from __future__ import annotations

from collections import OrderedDict

from ..errors import BadParams
from .map import ReadState

#: Small, and stated in the tool docstring rather than only here. Each
#: retained read holds one descriptor per printed unit, so the cost is a few
#: hundred small dicts per page rather than a page snapshot.
RETAINED_READS = 5

#: Descriptor fields whose change is worth a delta line. `ordinal` is not
#: among them: it moves whenever anything above the element is inserted, so
#: reporting it would fill every delta with noise about elements that did not
#: change.
WATCHED = ("name", "landmark", "landmark_label", "_state")

_LABEL = {"name": "name", "landmark": "landmark",
          "landmark_label": "landmark label", "_state": "state"}


class ReadStore:
    """The per-session token store, bounded per page handle."""

    def __init__(self, retained: int = RETAINED_READS) -> None:
        self.retained = retained
        self._by_handle: dict[str, OrderedDict[str, ReadState]] = {}
        self._counter = 0
        #: Tokens deliberately dropped, and why, so the refusal can say which
        #: of the three invalidations happened rather than only that the token
        #: is unknown.
        self._invalidated: dict[str, str] = {}

    def mint_token(self, handle: str) -> str:
        self._counter += 1
        return f"rt{self._counter}"

    def put(self, state: ReadState) -> None:
        reads = self._by_handle.setdefault(state.handle, OrderedDict())
        reads[state.token] = state
        reads.move_to_end(state.token)
        while len(reads) > self.retained:
            dropped, _ = reads.popitem(last=False)
            self._invalidated[dropped] = (
                f"aged out of the {self.retained}-read window kept for "
                f"{state.handle}")

    def get(self, handle: str, token: str) -> ReadState:
        reads = self._by_handle.get(handle) or {}
        state = reads.get(token)
        if state is not None:
            return state
        why = self._invalidated.get(
            token, "no read in this session ever minted it")
        raise BadParams(
            f"since={token!r} cannot be answered on page {handle}: {why}. "
            f"Read tokens are kept for the most recent {self.retained} reads "
            f"per page and invalidate on navigation of that page, on close of "
            f"the page, and on session end. Call get_page_view(page="
            f"{handle!r}) without `since` to re-establish a baseline; the "
            f"read token it returns is the one to pass next time.")

    def invalidate(self, handle: str, why: str) -> int:
        reads = self._by_handle.pop(handle, None) or {}
        for token in reads:
            self._invalidated[token] = why
        return len(reads)


def diff(before: ReadState, after: ReadState) -> dict:
    """What changed between two reads, expressed in refs the caller already
    holds. New refs, gone refs, changed names and states, and a count of what
    stayed put, which is the fact that makes the rest of it trustworthy."""
    # An element nothing in the key ladder can distinguish from its siblings
    # gets a fresh ref on every read by design, so a no-op delta would report
    # it as both gone and new. That is true and it is not NEWS, and a delta
    # that fills with it is a delta nobody reads. It is reported as its own
    # fact instead, because the churn IS the stated cost of never binding an
    # ordinal and hiding it entirely would be the other kind of dishonesty.
    added = [ref for ref in after.units
             if ref not in before.units
             and not after.units[ref].get("_turn_local")]
    removed = [ref for ref in before.units
               if ref not in after.units
               and not before.units[ref].get("_turn_local")]
    re_minted = sum(1 for ref in after.units
                    if ref not in before.units
                    and after.units[ref].get("_turn_local"))
    changed = []
    stable_by_kind: dict[str, int] = {}
    for ref, now in after.units.items():
        was = before.units.get(ref)
        if was is None:
            continue
        moves = [(field, was.get(field), now.get(field))
                 for field in WATCHED
                 if (was.get(field) or "") != (now.get(field) or "")]
        if moves:
            changed.append({"ref": ref, "kind": now.get("_kind"),
                            "changes": [{"field": _LABEL.get(f, f),
                                         "was": w, "now": n}
                                        for f, w, n in moves]})
        else:
            kind = now.get("_kind", "unit")
            stable_by_kind[kind] = stable_by_kind.get(kind, 0) + 1
    return {
        "since": before.token, "read": after.token,
        "url_before": before.url, "url_after": after.url,
        "navigated": before.url != after.url,
        "added": [{"ref": r, "kind": after.units[r].get("_kind"),
                   "role": after.units[r].get("role"),
                   "name": after.units[r].get("name")} for r in added],
        "removed": [{"ref": r, "kind": before.units[r].get("_kind"),
                     "role": before.units[r].get("role"),
                     "name": before.units[r].get("name")} for r in removed],
        "changed": changed,
        "stable": stable_by_kind,
        "re_minted_not_sticky": re_minted,
    }


def render(delta: dict, handle: str) -> str:
    """The delta as the payload the caller pays for.

    Same discipline as the projection: it states what did NOT change as well
    as what did, because "nothing happened" and "I did not look" are different
    answers and a delta that only speaks when it has news cannot tell them
    apart."""
    lines = [f'## DELTA on {handle} since {delta["since"]} '
             f'(read {delta["read"]})']
    if delta["navigated"]:
        lines.append(f'the page NAVIGATED: {delta["url_before"]} -> '
                     f'{delta["url_after"]}. Refs minted before the '
                     f'navigation do not survive it.')
    total_stable = sum(delta["stable"].values())
    churn = delta.get("re_minted_not_sticky") or 0
    not_sticky = (f' {churn} unit(s) that nothing distinguishes from their '
                  f'siblings were re-minted with new refs, which is the '
                  f'stated cost of never binding an ordinal rather than a '
                  f'change to the page.' if churn else '')
    if not (delta["added"] or delta["removed"] or delta["changed"]):
        lines.append(f'nothing changed. {total_stable} unit(s) are still '
                     f'present and still carry the refs you already have.'
                     + not_sticky)
        return "\n".join(lines)
    for item in delta["added"]:
        lines.append(f'+ {item["ref"]} | {item["kind"]} | {item["role"]} | '
                     f'"{item["name"]}"')
    for item in delta["removed"]:
        lines.append(f'- {item["ref"]} | {item["kind"]} | {item["role"]} | '
                     f'"{item["name"]}" (gone; the ref is kept so a later '
                     f'error can say what it used to be)')
    for item in delta["changed"]:
        moves = "; ".join(f'{m["field"]}: "{m["was"]}" -> "{m["now"]}"'
                          for m in item["changes"])
        lines.append(f'~ {item["ref"]} | {item["kind"]} | {moves}')
    detail = ", ".join(f"{k}={v}" for k, v in sorted(delta["stable"].items()))
    lines.append(f'unchanged: {total_stable} unit(s) [{detail}], still '
                 f'holding the refs you already have.' + not_sticky)
    return "\n".join(lines)
