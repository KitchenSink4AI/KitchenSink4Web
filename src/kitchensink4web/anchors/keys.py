"""The key ladder: which fields make a ref durable, and which never may.

DESIGN 3.5 gives two addresses per element. `ref` (`e12`) is a short cheap
turn-local handle the model pays for; `anchor` is a durable content-derived
descriptor stored server-side that can be re-resolved from nothing. This
module owns the KEY, which is not the same thing as the descriptor, and S2
found all three of the rules below by producing the failure each one prevents.

**The page key is part of every anchor key.** Origin, path, and hash, on every
rung. The first S2 prototype carried origin and path in the descriptor and
left them out of the key, and a ref minted on one page came back bound to a
same-named control on another: seven per run, silently, at the STRONGEST tier
of the ladder rather than in the fuzzy tail where anyone would look for it.

**An ordinal may scope a lookup and may never bind a ref.** An ordinal is a
property of the rendered window, and a virtualized list rewrites that window
while keeping every ordinal. On a react-window list of 5,000 rows, scrolling
from row 0 to row 4,000 put row 0's ref onto row 3,998 and did the same for
twenty-one of its neighbours. So the ladder below carries NO ordinal rung.
That is S2's `weak_keys=off`, the configuration its zero-false-rebind number
was measured under, and the cost is stated rather than hidden: a control the
page gives no way to distinguish is not sticky, and the design's answer for it
is a turn-local ref that refuses `AMBIGUOUS_LOCATION` rather than a key that
will collide later.

**Register every unique key an element offers, and look up strongest first.**
Not only the cheapest one. That is what lets a control survive a change to its
own accessible name, since its `id` key holds where its role-plus-name key does
not, and it is not derivable from a list of fields.
"""

from __future__ import annotations

#: Cheapest and most durable first. Each entry is a name plus the descriptor
#: fields it reads. Order IS the design: an id survives a re-render, a
#: re-order, and a name change; a role-plus-name key survives none of those on
#: a page of near-duplicate labels.
#:
#: The name-only fuzzy tier is absent by measurement rather than by caution.
#: Run on and off across every S2 scenario it changed no resolution's
#: correctness, its entire effect was to convert eight `STALE_ANCHOR` refusals
#: into eight `AMBIGUOUS_LOCATION` refusals, and it is the tier most able to
#: produce a wrong answer. A tier that contributes no correct rebinds and owns
#: the largest share of the risk is not a tier worth shipping.
KEY_LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("testid", ("page_key", "landmark", "landmark_label", "attr_testid")),
    ("id", ("page_key", "landmark", "landmark_label", "attr_id")),
    ("named-control", ("page_key", "landmark", "landmark_label", "role",
                       "attr_name")),
    ("role-name-scoped", ("page_key", "landmark", "landmark_label",
                          "labelled_ancestor", "role", "name")),
    ("role-name-landmark", ("page_key", "landmark", "landmark_label", "role",
                            "name")),
)

KEY_KINDS: tuple[str, ...] = tuple(name for name, _ in KEY_LADDER)

#: Rungs that need their distinguishing attribute to exist at all.
_REQUIRES = {"testid": "attr_testid", "id": "attr_id",
             "named-control": "attr_name"}

#: Fields that may appear in a descriptor and may NEVER appear in a key. The
#: ordinal is the one that matters and it is here rather than in a comment,
#: asserted by `assert_no_ordinal_binding` so the rule cannot rot into prose.
NEVER_IN_A_KEY = ("ordinal", "top", "area", "in_viewport", "state",
                  "doc_epoch", "truth", "node_uid")


def assert_no_ordinal_binding() -> None:
    """The ladder's own guard rail, asserted rather than remembered."""
    for name, fields in KEY_LADDER:
        for field in fields:
            if field in NEVER_IN_A_KEY:
                raise AssertionError(
                    f"key rung {name!r} reads {field!r}, which may scope a "
                    f"lookup and may never bind a ref (DESIGN 3.5)")
        if "page_key" not in fields:
            raise AssertionError(
                f"key rung {name!r} has no page key, which is how a ref "
                f"minted on one page binds to a same-named control on "
                f"another (DESIGN 3.5)")


def key_of(anchor: dict, kind: str) -> tuple | None:
    """This element's key at one rung, or None when it cannot offer that one."""
    for name, fields in KEY_LADDER:
        if name != kind:
            continue
        need = _REQUIRES.get(name)
        if need and not anchor.get(need):
            return None
        if name.startswith("role-name") and not anchor.get("name"):
            return None
        return (name,) + tuple(str(anchor.get(f, "")) for f in fields)
    raise KeyError(kind)


def index(anchors: list[dict]) -> dict[str, dict[tuple, list[int]]]:
    """Every key for every element in one read, so uniqueness is a lookup.

    Uniqueness is per READ. A key that is unique today may collide tomorrow,
    and that is a rebind refusal rather than a mint-time error, which is why
    the index is rebuilt on every read rather than cached."""
    out: dict[str, dict[tuple, list[int]]] = {}
    for kind in KEY_KINDS:
        bucket: dict[tuple, list[int]] = {}
        for position, anchor in enumerate(anchors):
            key = key_of(anchor, kind)
            if key is not None:
                bucket.setdefault(key, []).append(position)
        out[kind] = bucket
    return out


def unique_keys(anchor: dict, idx: dict) -> list[tuple[str, tuple]]:
    """Every key this element offers that is unique in THIS read, strongest
    first. All of them get registered; lookup walks them in this order."""
    out: list[tuple[str, tuple]] = []
    for kind in KEY_KINDS:
        key = key_of(anchor, kind)
        if key is not None and len(idx[kind].get(key, ())) == 1:
            out.append((kind, key))
    return out
