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

Phase 0 landed `sandbox` and `readonly`. Phase 3 landed the rest, built
BEFORE the action tools by deliberate design: `credentials` (secret-field
blindness, the vault, the serializer redactor), `origins` (deny-first
allow/deny evaluator), `budgets` (per-session budgets, loop detection,
429/Retry-After honor), `gates` (the TOCTOU-re-validating confirmation
engine), `audit` (the bounded, redacted action log), and `engine` (the ONE
choke point every Phase 4 action tool calls through).
"""
