# Dependency license ledger

Maintained from the first commit, per DESIGN 10.3 rule 1 and PLAN Phase 0.
Enforced by `tests/unit/test_dependency_ledger.py`, which fails the build if
`pyproject.toml` grows a required dependency that is not listed here.

## The rule

**No copyleft and no source-available dependency anywhere in the REQUIRED
install.** Anything questionable lives behind an optional extra
(`pip install kitchensink4web[...]`), so a dependency's license never
becomes the server's problem.

This rule is adopted regardless of which license KS4Web eventually ships
under (Q1 is unruled), because it is the only rule that keeps the permissive
option reachable. A copyleft dependency added today would quietly remove a
choice the author has not made yet.

## Required install

The package name is the FIRST column, and the license the SECOND, in every
table in this file. The enforcing test reads them positionally.

| Package | License | Direction | Note |
|---|---|---|---|
| `fastmcp` | Apache-2.0 | permissive, one-way into anything | Pinned `>=3.4,<4` from day one. The Word v2 lesson: never ship unpinned fastmcp, because a minor bump moved the visibility API mid-build. |
| `regex` | Apache-2.0 (CNRI-derived, permissive) | permissive | Backs the caller-pattern ReDoS guard in `policy/_regex.py`. Needed rather than convenient: stdlib `re` has no match timeout, and `find_elements` runs caller patterns against page text. |
| `playwright` | Apache-2.0 | permissive, one-way into anything including AGPL-3.0 | The engine (DESIGN 4.1). Moved from the `engine` extra into the required install when Phase 1 opened, as the ledger said it would. The 38.2 MB wheel bundles a Node runtime and the playwright-core driver; the browsers are downloaded at runtime and are not dependencies (see below). |
| `tiktoken` | MIT | permissive | The budget meter's estimator, fixed at `o200k_base` by DESIGN 3.4 and named in every published number. Required rather than optional because the hard-cap property is the product: without a named estimator, "never exceeds its budget" is unfalsifiable. |

## Optional extras

The package name is the FIRST column in every table here, because the test
that enforces this ledger reads the first backticked cell of each row.

| Package | License | Extra | Why it is optional |
|---|---|---|---|
| `pytest` | MIT | `dev` | Test-time only, never distributed. |
| `pytest-timeout` | MIT | `dev` | Test-time only. Present from Phase 0 because a hung browser test is the family's most common CI failure and an unbounded one wedges the runner. |

## Transitive obligations

`fastmcp` pulls its own tree (`mcp`, `pydantic`, `httpx`, and friends), all
of which are permissive at the versions pinned. **This ledger tracks DIRECT
dependencies; a full transitive audit runs at Phase 9**, before the first
release, since that is when the dependency set stops moving and an audit
becomes meaningful rather than a snapshot of an unfinished tree.

## Browser binaries, which are not dependencies

Chromium, Firefox, and WebKit are DOWNLOADED at runtime by Playwright's own
installer, not bundled and not redistributed. KS4Web ships with no browsers
and installs one on first use (DESIGN 4.1). That keeps them outside this
ledger entirely, which is the correct outcome and worth stating so a later
session does not try to list Chromium's license here.

## Vendored code

None, and one decision already made to keep it that way: **the thin BiDi
client for Lane C is written from the W3C specification, not lifted from
Playwright's `bidi` sources** (DESIGN 10.3 rule 2). Those sources are
Apache-2.0 and would be legally fine. Writing from the spec keeps every
license option open at negligible cost, and that is cheap now and expensive
later.

Any future vendored snippet gets a provenance note here before it is
committed, not after.
