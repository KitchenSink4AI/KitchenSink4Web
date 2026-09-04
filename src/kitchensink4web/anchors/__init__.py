"""The anchor system: two addresses per element, and how refs stay durable.

DESIGN 3.5, the second keystone. `ref` (`e12`) is a short cheap turn-local
handle the model pays for and passes back; `anchor` is a durable
content-derived descriptor kept server-side that can be re-resolved from
nothing. The model pays for `e12`; KS4Web keeps the durability.

Four modules, and the split is the design's:

- `keys.py` owns the KEY, which is not the descriptor: the ladder of fields
  that make a ref durable, the page key that is on every rung, and the
  ordinal rule (scopes a lookup, never binds a ref).
- `map.py` is the sticky element map. An element whose fingerprint matches an
  existing entry KEEPS its ref, which is what makes deltas expressible.
- `ladder.py` resolves a ref at action time, through six entry conditions and
  then five outcomes, and refuses rather than guessing.
- `deltas.py` answers `since=<read token>` under a bounded LRU.

**This package imports nothing from `ops/` or `engine/`** and never touches a
browser. It takes an extraction dict and returns decisions, which is what
makes the S2 regression battery runnable against recorded pages as well as
live ones.
"""

from __future__ import annotations

from .deltas import RETAINED_READS, ReadStore, diff, render
from .keys import (KEY_KINDS, KEY_LADDER, assert_no_ordinal_binding, index,
                   key_of, unique_keys)
from .ladder import PROCEED, STOPS_THE_BATCH, Outcome, batch_outcome, resolve
from .map import NAMESPACES, ElementMap, Entry, ReadState

__all__ = [
    "KEY_LADDER", "KEY_KINDS", "key_of", "index", "unique_keys",
    "assert_no_ordinal_binding",
    "ElementMap", "Entry", "ReadState", "NAMESPACES",
    "Outcome", "resolve", "batch_outcome", "PROCEED", "STOPS_THE_BATCH",
    "ReadStore", "diff", "render", "RETAINED_READS",
]

#: Asserted at import, not in a test that someone can forget to run. A key
#: ladder that acquires an ordinal rung is a false-rebind generator and the
#: cost of finding that out at import time is one tuple walk.
assert_no_ordinal_binding()
