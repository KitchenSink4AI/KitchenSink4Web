"""The policy layer: read-only mode, path policy, gates, budgets, loop
detection, audit, and redaction.

**This package imports from NEITHER `ops/` NOR `engine/`, ever.** The
one-direction dependency is DESIGN 10.3 rule 3 and it is enforced by
`tests/unit/test_import_direction.py`, which fails the build rather than
warning. The open-core seam is cheap to keep and expensive to retrofit, so
it is mechanical from commit one whether or not it is ever used.

Shared leaves (`errors`, `envelope`, `packs`) sit at the package top level
precisely so all three subpackages can use them without importing each
other.

Phase 0 lands two members: `sandbox` (the path policy governing the download
directory, the spill-to-file directory, the audit directory, and the seeded
profile directory) and `readonly` (the registration-time mode that is the
design's strongest safety differentiator). Phase 3 lands the rest.
"""
