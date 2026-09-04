"""KitchenSink4Web (KS4Web): the browser MCP server for the Garden aisle.

The thesis, stated once and carried everywhere (DESIGN 1.1): a cheap FIRST
read of an unfamiliar page, plus a cheap TARGETED follow-up when the thing
you wanted was not in that read. Both halves, always. Spike S1 measured the
first read at 3,726 tokens on a page the incumbents charge 156,347 for, and
also measured the limit: an arbitrary in-prose link on a 2,858-link article
is not reachable in one read at any budget, which is why the second half of
the claim is not optional.

Phase 0 is scaffold and ports only. There is no browser code in this package
yet and no tool here touches a page; every lite-core registration is a stub
that refuses with NOT_IMPLEMENTED. The engine lands in Phase 1.

Package boundary (DESIGN 10.3 rule 3), enforced by a test:

    policy/   read-only mode, path policy, gates, budgets, audit, redaction
    engine/   lanes, process hygiene, session and page handles
    ops/      the tools

    ops and engine depend on policy. policy depends on NEITHER, ever.
"""

__version__ = "0.0.0"
