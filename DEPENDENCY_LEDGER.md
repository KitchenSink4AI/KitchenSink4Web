# Dependency license ledger

Maintained from the first commit, per DESIGN 10.3 rule 1 and PLAN Phase 0.
Enforced by `tests/unit/test_dependency_ledger.py`, which fails the build if
`pyproject.toml` grows a required dependency that is not listed here.

## The rule

**No copyleft and no source-available dependency anywhere in the REQUIRED
install.** Anything questionable lives behind an optional extra
(`pip install kitchensink4web[...]`), so a dependency's license never
becomes the server's problem.

This rule was adopted while the ship license was undecided, because it was
the only rule that kept the permissive option reachable. **Q1 was ruled on
2026-09-06: the ship license is AGPL-3.0-only** (`pyproject.toml`), so the
original rationale has expired. The RULE stands on its own merits and is
unchanged: a required dependency's license becomes every downstream user's
problem, and an optional extra's does not. What is stale is only the
parenthetical about an unmade choice.

## Required install

The package name is the FIRST column, and the license the SECOND, in every
table in this file. The enforcing test reads them positionally.

| Package | License | Direction | Note |
|---|---|---|---|
| `fastmcp` | Apache-2.0 | permissive, one-way into anything | Pinned `>=3.4,<4` from day one. The Word v2 lesson: never ship unpinned fastmcp, because a minor bump moved the visibility API mid-build. |
| `regex` | Apache-2.0 (CNRI-derived, permissive) | permissive | Backs the caller-pattern ReDoS guard in `policy/_regex.py`. Needed rather than convenient: stdlib `re` has no match timeout, and `find_elements` runs caller patterns against page text. |
| `playwright` | Apache-2.0 | permissive, one-way into anything including AGPL-3.0 | The engine (DESIGN 4.1). Moved from the `engine` extra into the required install when Phase 1 opened, as the ledger said it would. The 38.2 MB wheel bundles a Node runtime and the playwright-core driver; the browsers are downloaded at runtime and are not dependencies (see below). |
| `tiktoken` | MIT | permissive | The budget meter's estimator, fixed at `o200k_base` by DESIGN 3.4 and named in every published number. Required rather than optional because the hard-cap property is the product: without a named estimator, "never exceeds its budget" is unfalsifiable. |

## Vendored fixture assets (not dependencies, and in the repo anyway)

Nothing here is installed, imported, or distributed with the package. They are
browser assets served to a headless page by a spike harness, and they are
listed because the rule this ledger enforces is about what enters the repo,
not only about what `pip` resolves. Both are permissive and both are pinned by
the vendored file itself rather than by a range.

| Package | License | Where | Why it is vendored |
|---|---|---|---|
| `react` 18.3.1 (UMD) | MIT | `spikes/s2/fixtures/vendor/` | S2 measures anchor durability against a REAL re-render, and a hand-rolled imitation of React's reconciliation would have proved nothing about React. |
| `react-dom` 18.3.1 (UMD) | MIT | `spikes/s2/fixtures/vendor/` | Same. |
| `react-window` 1.8.10 (UMD) | MIT | `spikes/s2/fixtures/vendor/` | PLAN 1.3's corpus B names this library specifically, and DOM node RECYCLING is the failure being tested. |

Vendored rather than fetched at run time so the fixture needs no network and
no build step, per PLAN 1.3's rule that the corpus must never become a
maintenance project.

## Optional extras

The package name is the FIRST column in every table here, because the test
that enforces this ledger reads the first backticked cell of each row.

| Package | License | Extra | Why it is optional |
|---|---|---|---|
| `pytest` | MIT | `dev` | Test-time only, never distributed. |
| `pytest-timeout` | MIT | `dev` | Test-time only. Present from Phase 0 because a hung browser test is the family's most common CI failure and an unbounded one wedges the runner. |
| `winrt-runtime` | MIT | `ocr` | The PyWinRT runtime the four projection packages below sit on. Pinned `==3.2.1`. Windows-only wheels (win32, win_amd64, win_arm64), Python 3.9 to 3.14. Verified against the PyPI metadata of the pinned release rather than inferred from the project's documentation. |
| `winrt-Windows.Media.Ocr` | MIT | `ocr` | The OCR engine that ships inside Windows itself, reached through the PyWinRT projection. No native install, no language-data download, no subprocess, no network, no API key: the engine is already on the machine. Pinned `==3.2.1`. |
| `winrt-Windows.Graphics.Imaging` | MIT | `ocr` | `SoftwareBitmap` and `BitmapDecoder`, which is how PNG bytes become something the recognizer accepts. Pinned `==3.2.1`. |
| `winrt-Windows.Storage.Streams` | MIT | `ocr` | The in-memory stream the decoder reads from, so nothing touches disk on the way. Pinned `==3.2.1`. |
| `winrt-Windows.Globalization` | MIT | `ocr` | `Language`, for the BCP-47 tag a caller may name. Pinned `==3.2.1`. |
| `axe-playwright-python` | MIT (wrapper); bundles axe-core under MPL-2.0 | `accessibility` | The accessibility engine, as a PINNED DEPENDENCY rather than a vendored file (author ruling 2026-09-07: a dependency yes, bundling no). Pinned `==0.1.8`. KS4Web imports the engine SOURCE from the installed package and drives the run itself, because the server decides which frames are entered and the engine's own iframe traversal would make that decision twice. |

**Tesseract was evaluated for the `ocr` extra and declined.** Not on
license: Apache-2.0 is one-way into AGPL-3.0 and would have been legal in
either the required install or an extra. It was declined on packaging. It is
a native binary the user installs separately plus tens of megabytes of
language data, the Python wrappers shell out to a subprocess per call, and a
missing binary fails at RUN time on a machine where `pip install` succeeded,
which is the worst shape of failure this codebase has. That is a
disproportionate install burden on a product that does not even bundle a
browser. The one capability it has that Windows OCR lacks is a per-word
confidence score, and `ocr.py` explains why no confidence number is worth
that.

**The `accessibility` extra carries copyleft and that is exactly why it is
an extra.** axe-core is MPL-2.0, which is weak, file-scoped copyleft and one
of the licenses MPL-2.0 section 1.12 names as compatible with AGPL-3.0. The
ledger's rule keeps it out of the REQUIRED install, where a dependency's
license becomes every user's problem, and an extra is where the rule says
such a thing belongs. Nothing of axe-core is redistributed by this project:
it arrives through `pip` from its own publisher, with its own license files,
under its own name.

**Engine currency, checked on 2026-09-07 rather than assumed.**
`axe-playwright-python` 0.1.8 (released 2026-07-24) bundles axe-core 4.12.1
(released 2026-06-10); upstream axe-core's current stable is 4.13.0
(released 2026-08-05). The wrapper is therefore one minor version and about
a month behind upstream, on a release cadence that has shipped four times in
the last fourteen months. `get_accessibility` reports the engine version it
actually ran, read from the engine itself rather than from this table, so a
result is never attributed to a version that did not produce it. Re-check
this row when the extra is bumped.

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

**Article extraction takes no dependency (2026-09-06).** `get_article` is the
obvious place for one: Readability is the reference implementation and every
port of it is a package away. It is not taken. The JS port is Apache-2.0 and
would be legally fine, but it is a 100 KB script this server would have to
inject and keep in step with its own visibility, shadow, and instrument
rules, and the Python ports each drag an HTML parser behind them for a
document the browser has already parsed. `projection/article.js` is written
in-house against the machinery that is here: it splices the SAME
`visibility.js` every other read uses, so a `display:none` injection inside
an article body is counted and withheld by the one rule rather than by a
second opinion. What IS borrowed is the class-weight vocabulary, the word
lists two decades of pages have been tuned against, and that is inspiration
rather than code.
