# PLAN.md: KitchenSink4Web v1 build plan, spikes, gates, and the proof workstream

**Status:** INTERNAL planning document. Not shipped, not public copy. Written
against `DESIGN.md`, the four KS4Web research artifacts, the banked token
measurement, and the shipped family build plans (KS4PPT v1, KS4XL v1). Read
DESIGN.md first; this plan is how it gets built, not what it is.

**The external success metric:** be the browser MCP that a working
professional can point at an unfamiliar page and read for under five thousand
tokens, follow up on for tens of tokens when the thing they wanted was not in
that read, act on with references that still work three turns later, run in
read-only mode when the task does not need to touch anything, and audit
afterward. Plus a benchmark a stranger can re-run.

The follow-up clause is not padding. S1 measured the first read as genuinely
actionable for navigation, forms, controls, sections, and tables, and genuinely
NOT actionable for an arbitrary in-prose link on a 2,858-link article, at any
budget. **Cheap first read plus cheap targeted follow-up** is the claim
everywhere it appears, in this plan and in every public surface (DESIGN 1.1,
DESIGN 12 rule 2a).

**The internal success metric:** the author dogfoods it daily on their own
Firefox from Phase 4 onward, and field bugs outrank new features.

---

## 1. Reuse ledger

The family question, answered honestly for the browser domain: **KS4Web reuses
the least family infrastructure of any sibling and writes the most new domain
code.** Word v2 was a re-front of a shipped engine. KS4PPT and KS4XL inherited a
whole safety-and-envelope stack that happened to be file-format-agnostic. KS4Web
inherits the DISCIPLINE and very little of the CODE, because the browser has no
file to save, no package to round-trip, no COM tier, and no corruption story.

### 1.1 What ports

| Piece | Source | Work |
|---|---|---|
| Response envelope, `isError=true` refusals, closed-code discipline, pack-hint discoverability | word-mcp `envelope.py` | Port the shape and the serializer seam. Replace the code map wholesale with the browser vocabulary (DESIGN 8.3). **The secrets-redaction hook lands in this serializer**, which is the one place it can be enforced globally. |
| Sandbox / allowed-roots, realpath plus commonpath escape check | word-mcp `sandbox.py` | Copy; rename to `KS4WEB_ALLOWED_ROOTS`. Governs the download directory, the spill-to-file directory, the audit directory, and the seeded-profile directory. |
| Error taxonomy and ReDoS guard | word-mcp `core/errors.py`, `_regex.py` | Copy; extend the taxonomy. The regex guard matters more here than in the document family because `find_elements` takes user regex against page text. |
| `scripts/measure_surface.py` plus the operations counter | word-mcp `scripts/` | Port. Every public count comes from running it, never hand-math. |
| Docstring budget test and the no-em-dash test | word-mcp / pptx tests | Port. Enforces the 80-120 token description budget and the sub-250 per-schema ceiling mechanically from day one, which is how the lite bill stays under 1,500. |
| Process-hygiene DISCIPLINE (owned-PID journal, never sweep by name, never touch a process we did not spawn, two-phase verify with a grace window) | word-mcp / pptx / xlsx `com_gates` | The RULES port verbatim and are the reason KS4Web will not repeat chrome-devtools-mcp's 42-orphan defect. The MECHANISM is new: browser process trees, death-pipe sentinels, and profile-dir reaping instead of COM PIDs. |
| View / batch layer STRUCTURE (anchored projection, validate every anchor before executing any, one lock and one commit per batch) | pptx `ops/view.py`, `ops/batch.py`; xlsx `get_grid_view` | The PATTERN ports; the internals are entirely new. **One place it does not port cleanly:** validate-all-then-execute assumes the batch cannot invalidate its own targets, which is false in a browser, where filling field one re-renders its siblings. DESIGN 3.5's mid-batch rebind rules replace the file-format assumption, and there is no commit to roll back. |
| Pack registry shape and `KS4WEB_MODE` env contract | word-mcp `packs.py` | **Shape only.** The runtime `enable_tools` machinery is deliberately NOT ported (DESIGN 7.2, a conformance decision). What ports is the pack membership table, the startup-mode parsing including the "typos fail loudly" fix, and the surface-report math. |
| CI workflows with trusted publishing, Dockerfile, registry manifest, `glama.json` two-field claim file, `mcp-name` marker discipline | word-mcp / pptx repos | Copy the shapes; fill KS4Web specifics. The KS4PPT v1.0.1 lesson stands: the `mcp-name` marker and the sub-100-char `server.json` description exist BEFORE the first release. |

Roughly 400 to 600 lines of ported machinery. Less than half of what KS4XL
inherited.

### 1.2 Genuinely new engine code

| Module | Est. scale | Notes |
|---|---|---|
| `engine/lanes.py` | ~400 LOC | Lane A/B/C resolution, lazy browser install, lazy browser start, channel handling, the capabilities truth table that backs `manage_session(capabilities)` and `LANE_UNSUPPORTED`. |
| `engine/hygiene.py` | ~350 LOC | The three defenses: own process group plus death-pipe sentinel, startup reaper for orphaned KS4Web profile dirs by owned PID, idle timeout that parks pages to `about:blank` then recycles. Windows-first. The single most likely source of field bug reports. |
| `engine/bidi.py` | ~500 LOC | The thin in-house WebDriver BiDi client for Lane C Firefox. **Written from the W3C spec, not lifted from Playwright's bidi sources** (DESIGN 10.3, a license-futures decision). Read-mostly surface: `session.new`, `browsingContext.getTree`, `script.evaluate`, `browsingContext.captureScreenshot`, `input.performActions`. Contingent on Spike 5. |
| **`projection/`** | **~1,200 LOC, the keystone** | The cheap first read. The readability gate, the landmark segmenter, the affordance ranker, the content digest, the form and table inventories, the DOM projection with its attribute allowlist, the hidden-content normalizer, the completeness accounting, the degradation ladder, and the budget meter that measures as it builds. Everything else in the product is downstream of this. |
| **`anchors/`** | **~600 LOC, the second keystone** | Fingerprint minting (role, accessible name, scoping path, stable attributes, origin pattern), the sticky element map, the rebind ladder with its five outcomes, the delta engine over stable refs. |
| `policy/` | ~700 LOC | Read-only mode enforcement at registration time, credential blindness, redaction in the serializer, the origin allow/deny evaluator, budgets and loop detection, the gate engine with TOCTOU re-validation, the audit writer. **One-direction dependency: ops and engine depend on policy, never the reverse** (DESIGN 10.3). |
| `ops/` per family | the bulk | Reads, actions, extraction, capture, network, storage, files, workflows. Mechanical once projection, anchors, and policy exist. |
| `ops/workflows.py` | ~350 LOC | Save from the audit log, dry-run anchor re-resolution, deterministic replay. |
| Tests, the adversarial fixture site, and the benchmark harness | large | Section 1.3. |

Honest read: this is closer to a cold start than any sibling. The safety
discipline, the envelope, the refusal grammar, the measurement culture, and the
gate-per-phase build style all carry over, and none of the engine does.

### 1.3 The corpus, built once, gates every phase

Three distinct fixture sets, and none is optional.

**A. The benchmark page set (frozen, public, matches MEASURED exactly).** The
same four pages the banked measurement used, so every KS4Web number is directly
comparable to the incumbent baseline without re-measuring them:
`en.wikipedia.org/wiki/Treaty_of_Versailles`, `en.wikipedia.org/wiki/
List_of_countries_by_GDP_(nominal)`, `httpbin.org/forms/post`, `example.com`.
Plus a widened set added in Phase 2: a heavy SPA, a documentation site, an
e-commerce product page, a login page, and a GitHub repo page. **Snapshots of
each are frozen to disk** so the benchmark is reproducible after the live pages
change, with the live run kept as a drift check.

**B. The pathological fixture site (local, served from the repo).** Every
landmine, deliberately: a 50,000-node DOM; an infinite-scroll list; a
react-window virtualized list holding 20 of 5,000 rows; a canvas-rendered UI;
three levels of nested iframes including a cross-origin one; open and closed
shadow roots; a cookie banner and a modal overlay that dominate the first read;
a page that mutates every 100ms; a table with rowspan and colspan; a "table"
rendered as nested divs; lazy images with placeholder `src`; a React control that
checks `event.isTrusted` and silently no-ops on synthetic clicks; a `<div
onclick>` button invisible to role-based selectors; an element that moves under
the cursor mid-animation; an overlay that intercepts clicks; a portal-rendered
dropdown that is absent from the a11y tree; a page emitting thousands of console
lines; and a form with `type=password` and `cc-number` fields.

**C. The adversarial safety fixture (local, never networked).** Hidden-text
injection payloads across every hiding technique (display:none,
visibility:hidden, opacity:0, font-size:0, off-screen, aria-hidden, HTML
comment, white-on-white, zero-width Unicode); a base64-encoded payload, because
encoding defeated a shipped exfiltration filter in a documented incident; a
TOCTOU control that swaps a benign button for a destructive one on a timer; a
mid-action redirect to a blocked origin; a simulated bot wall and a simulated
CAPTCHA interstitial; an expired-session login redirect; and a page that tries to
get a storage dump into the transcript.

Fixtures B and C are **synthetic and live in the repo.** No real user data, no
private pages, no live third-party sites in any automated gate.

**The corpus is a build item and it is scheduled, not assumed.** S1 cannot run
without corpus A frozen, and S2 cannot run without the React re-render, the
virtualized list, and the route change from corpus B, so "nothing is built until
the spikes report" has one stated exception and this is it. The sequence:

| Corpus work | Due |
|---|---|
| Corpus A: the four MEASURED pages fetched and frozen to disk as snapshots, with the fetch date and page revision recorded | **Before S1 starts.** S1 measures against the frozen copies, not the live pages. **NOT MET as run (2026-09-05):** S1 ran against live pages and froze the extraction outputs afterward (`spikes/s1/out/raw/*.extract.json`), plus the eleven blind-trial inputs byte-for-byte. Its ladder numbers re-derive offline and its per-page numbers do not. **MET 2026-09-05 02:20 KST**, ahead of the Phase 2 harness: `corpus/a/` holds the four pages with `corpus/a/MANIFEST.json` recording the fetch DTG, the final URL, the MediaWiki revision id where one is published, a sha256 per file, and what the capture strips. `scripts/freeze_corpus_a.py` rebuilds it and `scripts/measure_corpus_a.py --live` re-measures it with the live drift check. Every DESIGN 3.2 figure now comes from this corpus. |
| Corpus B subset: React re-render page, react-window virtualized list, client-side route change, plus the 50,000-node DOM (S1 needs it for the degradation rungs and the latency measurement) | **Before S1 and S2 start.** **BUILT 2026-09-05 as part of S2**, at `spikes/s2/fixtures/`: a React SPA carrying a node-replacing remount, a label change, a list reorder, hash routing, duplicate control names and a modal; a real react-window `FixedSizeList` rendering 20 of 5,000; and a look-alike page for the cross-navigation case. React 18.3.1 and react-window 1.8.10 are vendored as UMD builds, so there is no build step and no network at run time. The 50,000-node DOM was built in Phase 1 as the latency ladder. **These move into the repo's corpus B proper before Phase 2 closes**; they live under `spikes/` today because S2 built them. |
| The rest of corpus B: iframes, shadow roots, canvas, mutating page, rowspan tables, div-tables, lazy images, `isTrusted` control, `<div onclick>`, moving target, overlay, portal dropdown, console flood, secret fields | Before **Phase 2** opens, since the Phase 2 gate is verified against them. |
| Corpus C in full | Before **Phase 3** opens, since the Phase 3 gate IS corpus C driven end to end. **MET 2026-09-05**: `corpus/c/`, nine synthetic pages with `MANIFEST.json`, never networked; `scripts/gate_phase3.py` drives it. |

The widened benchmark set (heavy SPA, documentation site, e-commerce product
page, login page, GitHub repo page) is frozen with the rest of B, before Phase 2.
Fixture pages are hand-written HTML with no framework build step where possible,
so the corpus itself never becomes a maintenance project.

---

## 2. The spike phase

**Nothing is built until the spikes report**, with the single scheduled
exception named in 1.3: the corpus A freeze and the S1/S2 subset of corpus B are
built FIRST, because the spikes measure against them and a spike run against
live pages is not reproducible. The architecture freezes only after the spike
gate. Every spike has an explicit kill or fallback criterion so it ends in a
decision rather than a vibe, and that rule binds this document too: a gate
phrased as a judgment call is a defect in the plan, not a spike that happens to
be qualitative.

Spikes are ordered by information value per hour, with one deliberate change
from the engine research's ordering: **S1 (the projection proof) comes first**,
ahead of the engine spikes, because it tests the product thesis and every engine
spike tests a delivery mechanism for it. If S1 fails, the engine questions stop
mattering.

### S1: The projection proof (THE spike, run first) — **DONE 2026-09-05, VALIDATED-WITH-CAVEATS**

**Report:** `internal notes/20260905_ks4web_spike_s1.md`.
**Code:** `spikes/s1/` on branch `spike-s1`, throwaway prototype, Lane A only.
**Absorbed into DESIGN and PLAN 2026-09-05**; the edit list is in the BUILD_LOG.

Eleven pages spanning four orders of magnitude of raw size, six blind agents,
seventeen tasks. Headline: **Versailles projects to 3,726 tokens against a
106,088-token unannotated accessibility snapshot on the same machine**, a 28.5x
multiple that is conservative because the baseline lacks playwright-mcp's
per-node ref annotations (the banked figure through playwright-mcp itself is
156,347). Projection size proved essentially independent of page size: raw inputs
spanning a factor of 11,000 projected into a band spanning a factor of 9.

| S1 gate | Result |
|---|---|
| Versailles under 5,000 at `detail=standard` | **PASS**, 3,726 |
| GDP table under 3,000 for structure plus first row page | **FAIL as written.** Structure alone is 2,854. Target restated in DESIGN 3.2: structure and row page priced as separate calls. |
| httpbin form under 300 | **FAIL as written.** 758 measured against a ~390-token scaffold floor. Target replaced with under 900 in DESIGN 3.2. |
| HARDER GATE: blind agent clicks "Fourteen Points" without a second full read | **SPLIT.** Passes the letter (no full re-read requested, cheap route named unprompted); fails the intent (no ref was available to click). Drives the positioning change. |
| KILL: token target reachable only by dropping affordances below actionable | **NOT TRIGGERED.** The GitHub failure happened with 2,762 tokens of headroom unused. A ranking defect, not a budget defect. |
| KILL: actionability needs more than 5,000 on an ordinary article | **NOT TRIGGERED.** |

Blind trials: **11 ACT / 3 PARTIAL / 3 FAIL over 17 tasks.** Two of three
failures recovered through a cheap targeted call the agent named unprompted,
putting 82 percent of tasks inside a 5,000-token budget for the whole
interaction. One task (select options on a form) forced an expensive second read
and is recorded in DESIGN 3.3 block 5 as the known case with a Phase 2 TODO.

**The three corrections the prototype forced, all now in DESIGN:** affordance
ranking is quota-based by class with a zero quota for in-prose links (3.3 block
3, motivated by the GitHub Issues-tab failure); every printed price is real and
derived from the budget meter's own ledger (3.3a, the cost-estimation contract);
accessible names are computed by accname rather than scraped from `textContent`
(3.7, the `"Uh oh!"` case). Plus the ~390-token scaffold floor replacing the
sub-300 target (3.2), ladder monotonicity and finer rungs (3.4), and the
completeness field list extended with seven new fields (3.3 block 7).

**One S1 obligation did not discharge in S1 itself. E11, the latency
measurement, transferred to the engine-spike round and was DISCHARGED there on
2026-09-05.** S1 reported no wall-clock table; the engine round measured one
against the unmodified S1 projector, ten repetitions per fixture, with a
synthetic ladder bracketing the 50,000-node fixture the S1 corpus never
reached. Result: **341 ms p95 at 50,000 nodes**, under 0.9 s at 100,000, and
the hidden-content normalizer is 22 percent of extract rather than the bill the
design feared, so **it is not sampled or capped in Phase 2**. The Phase 2 bound
is set from that measurement (gate part 5 below) and no longer blocks the phase
opening. Full numbers in DESIGN 3.6a. Nothing else about S1 is outstanding.

**Tokenizer caveat, carried:** S1 counted with `tiktoken` `cl100k_base`, not the
`o200k_base` convention this plan fixes (W1). Its figures are indicative and are
re-measured under the convention by the Phase 2 harness before publication.

The original spike definition follows, kept verbatim as the record of what was
asked.

Build a throwaway projector against the frozen benchmark set and measure it.
Not production code, not integrated, no MCP server. Playwright script, page in,
projection out, token count printed.

- **GATE:** the Treaty of Versailles article projects to **under 5,000 tokens**
  at `detail=standard`, the GDP table page to under 3,000 for structure plus
  the first row page, and the httpbin form to under 300.
- **The tokenizer convention is fixed before the first measurement**, per DESIGN
  3.4: counts are `tiktoken` on `o200k_base`, the same estimator the budget meter
  enforces against, and every reported number names it. A number measured with a
  different tokenizer is not comparable to the MEASURED baseline and does not
  count toward this gate.
- **THE HARDER GATE:** a fresh agent given only the projection can complete
  "find and click the link to the Fourteen Points." A cheap read that is not
  actionable is not the product. Run this as a blind trial with an agent that has
  not seen the page.
- **The blind-trial protocol, defined so the gate means one thing.** The agent
  gets the initial projection and may make **up to three follow-up calls** drawn
  only from the cheap set (`find_elements`, or a region or section expansion via
  `get_page_view(location=...)`). It may NOT request a second full-page read at
  any budget, and it may not be told anything about the page beyond the
  projection. **Success is the correct ref for the Fourteen Points link,
  identified within that allowance.** A mid-prose link will often not survive the
  capped affordance ranking, so the follow-up allowance is exactly what is being
  tested: the claim is that the orientation names the cheap route to the answer,
  not that the first payload contains everything. Record the number of follow-up
  calls used, since that count is the honest measure of how good the orientation
  is. Run the trial on at least three of the frozen pages, not only Versailles.
- **Wall-clock is measured here too, and it is a real number, not a note.** A
  read that is token-cheap and wall-clock-expensive is the same user pain by
  another route, and the projection pipeline is computed-style-hungry: the
  hidden-content normalizer (white-on-white contrast, off-screen position,
  near-zero font size) implies per-node style computation, and the 50,000-node
  fixture is where that bill lands. Report wall-clock per projection for every
  fixture, cold and warm, with the p50 and p95 over ten runs. **The measured p95
  on the fixture set becomes the Phase 2 latency budget**, so this spike sets the
  bound rather than guessing one in advance.
- **KILL CRITERION:** if the token target is reachable only by dropping the
  affordance set below actionable, or if actionability requires more than 5,000
  tokens on an ordinary article, **the flagship claim is wrong** and the
  positioning changes before a line of production code is written. Escalate to
  the author immediately; do not proceed to S2. **A latency finding is not a kill
  and it is not nothing:** if the 50,000-node fixture projects slower than a few
  seconds, the normalizer's cost model is a Phase 2 design input (batch the style
  reads in one evaluated pass, sample rather than sweep, or cap the node count
  the normalizer visits and report the cap in the completeness block).
- Output: the measured degradation ladder, the real ratio of interactive to
  total nodes on each fixture, the first honest version of the
  completeness-block field list, and the latency table that sets the Phase 2
  bound.

### S2: Anchor durability — **DONE 2026-09-05, GREEN**

**Report:** `internal notes/20260905_ks4web_spike_s2.md`.
**Code:** `spikes/s2/` on `master`. **Raw:** `spikes/s2/out/s2.json`.

**Zero false rebinds and zero false stickiness across 396 resolutions in 18
scenarios**, against real React 18.3.1 and real react-window 1.8.10 vendored as
UMD builds. Neither gate tripped and the fallback is not needed.

The headline pair: a React remount destroyed **77 percent of the DOM nodes**
and **100 percent of distinguishable elements kept their refs**, which turns
DESIGN 3.5's argument against copying `backendNodeId` from a claim into a
measurement. Same-URL reload, label change, list reorder, and virtualized
scroll all hold at 100 percent.

**It was not zero on the first run, and the corrections are the substance.**
Three false-identity classes, each now a design rule (DESIGN 3.5): the page key
belongs in every anchor KEY and not only in the descriptor (7 wrong bindings
per run at the strongest tier, on a look-alike page); an ordinal may scope a
lookup and may never bind a ref (22 wrong bindings from one virtualized scroll,
because a recycled window keeps its ordinals); and every unique key an element
offers is registered rather than only the cheapest, which is what let a control
survive a change to its own accessible name.

Four further findings, all absorbed. **The URL test is literal**: document
identity was measured as the plausible refinement and is worse in both
directions, rebinding across a route change and refusing everything after a
reload. **The name-only fuzzy tier is CUT from v1**: it changed no
resolution's correctness anywhere and only converted STALE refusals into
AMBIGUOUS ones. **Cross-page rebinding stays off and now has a number**: 6
false rebinds in 22 attempts, 27 percent. **The entry-condition table gained a
sixth row** for turn-local refs, which the obvious implementation refuses
`NOT_FOUND` when the ref was in fact minted this session.

One cost is stated rather than buried: scoping the key by origin, path, and
hash means a persistent app shell loses its refs on a hash route change, five
of twenty-two elements on the fixture. The alternative buys them back and costs
a false rebind, and the harder gate settles it.

### S2 (original definition, kept as the record of what was asked)

Mint anchors on a React SPA and on the pathological fixture, then force a
re-render, a route change, a virtualized-list recycle, and a full navigation.

- **GATE:** an unchanged element keeps its ref across re-reads on every fixture.
  Rebind succeeds where the element genuinely persists.
- **THE HARDER GATE: zero false rebinds.** A false rebind is worse than a
  failure, because a failure is visible and a false rebind clicks the wrong
  thing while reporting success. If the false-rebind rate is not zero on the
  fixture set, the rebind ladder tightens (more required fingerprint fields,
  narrower fuzzy tier) until it is.
- **FALLBACK:** if durable anchors cannot be made reliable, refs degrade to
  sticky-within-page only, deltas still work, and cross-navigation rebinding is
  cut from v1. That is a materially weaker product and it is still shippable.

### S3: `moz-firefox` reality check — **DONE 2026-09-05, HOLDS**

**Report:** `internal notes/20260905_ks4web_engine_spikes.md`.
**Code:** `spikes/engine/` on branch `spike-engine`.

`channel="moz-firefox"` is **present and shipping in playwright-python 1.62.0
and is not flag-gated at runtime.** It launched the installed
`C:\Program Files\Mozilla Firefox\firefox.exe` (Firefox 154.0.1), navigated,
clicked, filled inputs and a textarea, selected an option, checked a box, ran
a JS handler, evaluated, aria-snapshotted, screenshotted, and round-tripped a
form POST, headless and headed. 18 of 20 steps green. **The kill criterion did
not trip and Lane B Firefox stands**, dogfood premise intact.

Two of the twenty steps failed and both became design edits rather than lane
problems. `about:support` is **refused by BiDi** ("Navigation to
`about:support` is not allowed in this context"), so provenance comes from the
process table and the user-agent string, both of which worked. `go_back` timed
out, which S4 then characterized properly.

**The safety finding this spike produced is the most important line in the
round, and it is now a DESIGN constant (4.3, 4.6).** Playwright's
`BidiFirefox.defaultArgs` does NOT pass `-no-remote`, unlike its own Juggler
Firefox path. Without it, a launch can be adopted by the user's already-running
Firefox no matter what profile directory was named, which defeats the profile
rule from a direction that rule did not anticipate. **KS4Web supplies
`-no-remote` on every Firefox launch, unconditionally.** The spike ran under it
throughout and never touched the author's open browser.

### S3 (original definition, kept as the record of what was asked)

Launch stock Firefox via `channel="moz-firefox"` with a throwaway `user_data_dir`.

- **GATE:** it launches, navigates, clicks, fills a form, screenshots, and reads
  text. `about:support` confirms it is the installed build and not a Playwright
  download.
- **KILL CRITERION:** if this fails on Windows with the installed Firefox, the
  whole Lane B Firefox dogfood premise collapses and Lane B Firefox becomes
  bundled-only. S5 (Lane C Firefox) proceeds independently, since it uses a
  different mechanism entirely.

### S4: BiDi gap inventory — **DONE 2026-09-05, LANES SURVIVE AT FULL STANDING**

Twenty probes on both `moz-firefox` (Firefox 154) and Chromium against a local
deterministic fixture server, with Chromium as the control. Every probe passed
on Chromium, so every Firefox difference is a genuine lane difference. **The
measured table is DESIGN 4.5a and it replaces the research's hole list, which
was stale.**

**Two of the three documented gaps are REFUTED.** Response bodies work (708 B
document, full JSON on an XHR POST). Downloads work (event fired, 460 bytes on
disk). HTTP auth works (401 answered). Also working against expectation: header
overrides across a 302, clicks inside a `rotate(37deg) scale(1.6)` element, and
locale plus timezone emulation.

**Two gaps are real.** Request body READS return `None` with no exception
raised, while `content-length` proves the body exists; writing a body works, so
the honest row is "write yes, read no." And history navigation is the NEW gap
and the worse one: `go_back` and `go_forward` time out, the navigation
actually happens, and `page.url` goes stale afterward, so the driver reports a
lie rather than an absence. In-page `history.back()` shows the same stale URL,
so it is BiDi URL tracking rather than a `go_back()` wiring bug.

**Gate ruling against this spike's stated threshold: neither gap is lite
core.** Request bodies are a `network` pack concern and back/forward has a
working substitute (`goto` the previous URL, which KS4Web tracks anyway). **The
Firefox lanes do NOT demote to read-mostly.** They carry two `LANE_UNSUPPORTED`
rows, drafted in DESIGN 4.5a, plus one COST row: `page.pdf()` works on
Firefox/BiDi, which is itself a surprise, at 8.7 s against Chromium's 0.2 s.
A cost is not a gap and does not get an error code.

**Both gaps become LOUD REFUSALS at the KS4Web layer**, because both fail
silently or misleadingly in the driver, which is the failure class this
product argues against. And `page.url` is never trusted after a history
traversal on Firefox/BiDi, so no anchor logic or URL wait may derive from it
there.

### S4 (original definition, kept as the record of what was asked)

Draft the tool surface first (rough is fine), then run every candidate operation
on `moz-firefox` and record supported / degraded / unsupported. Probe the known
bad set specifically: response-body capture, download events, HTTP auth,
`set_extra_http_headers` on redirects, locale and timezone emulation, and
clicking inside a CSS-transformed element.

- **GATE, stated as a threshold rather than a judgment call.** The dividing line
  is the LITE CORE, because that is the set a user gets with no flags and the set
  the positioning promises on every lane. **If any lite-core operation is
  unsupported, or silently degraded rather than loudly refused, on
  `moz-firefox`, the Firefox lanes demote to read-mostly.** If the affected
  operations are pack-tier only, they become `LANE_UNSUPPORTED` entries in the
  capabilities truth table and the lane survives at full standing. Silent
  degradation counts as unsupported for this test, because an operation that
  reports success without acting is worse than one that refuses.
- **The probe is run per operation and recorded as a row**, supported / degraded
  / unsupported, with the observed failure mode quoted. A row without an observed
  failure mode is not a finding.
- Output: **the seed of the `manage_session(capabilities)` truth table and every
  `LANE_UNSUPPORTED` message.** This spike literally produces a product feature.
- **FALLBACK:** Firefox lanes demote to read-mostly and Chromium becomes the
  only full-surface engine, documented honestly rather than papered over.

### S5: Firefox live attach over raw BiDi — **DONE 2026-09-05, GATE PASSES**

Run in the authorized Firefox-closed window it was deferred to (the deferral
record is in git history: agent rounds never attach to the author's live
browser, so the spike waited rather than making an exception for itself). The
user side was simulated faithfully: stock installed `firefox.exe` launched the
way a Lane C user would launch it (`-no-remote -profile <seeded>
--remote-debugging-port=9667`), then a **thin in-house BiDi client** (~140
lines, websocket + JSON written from the W3C spec, `spikes/attach/
bidi_client.py`) attached to `ws://127.0.0.1:9667/session`.

**All five commands round-trip.** `session.new` in 1.9 s (capabilities
returned, including `moz:profile` and `moz:processID`), `browsingContext.
getTree` enumerated the context, `navigate` with `wait:"complete"` in 293 ms,
`script.evaluate` read title and text, `captureScreenshot` returned a valid
23 KB PNG in 241 ms, and an `input.performActions` click landed (verified by
the page's own state change). **Lane C Firefox is real**, and Playwright was
not involved at any point: the client is spec-derived, which keeps the
Section 10 license future open.

**Two protocol quirks measured, and both flip S4/S3 findings in Lane C's
favor.** `about:support` refuses over RAW BiDi with the same `unsupported
operation` error S3 saw, so that is a Firefox remote-agent restriction rather
than a Playwright artifact and it binds on every lane. But
`browsingContext.traverseHistory` **works truthfully over the raw client**:
back returned in 163 ms and `getTree`'s URL, `location.pathname`, and the DOM
all agree. **The S4 history desync is Playwright's client-side URL tracking,
not the protocol**, so the in-house Lane C client does NOT inherit the
`LANE_UNSUPPORTED` history row that Playwright-driven Firefox lanes carry.

**One Windows implementation trap for Phase C:** `firefox.exe` is a launcher
process that spawns the real browser root and exits 0 within seconds, so a
Popen PID is useless for the owned-PID journal. Track the browser by command
line (profile dir + `-no-remote`, excluding `-contentproc`) and tree-kill that
PID. The spike ended at a zero-firefox census.

### S5 (original definition)

Start Firefox manually with `--remote-debugging-port=9222` on the real profile,
connect a bare WebSocket, and drive `session.new`, `browsingContext.getTree`,
`script.evaluate`, `browsingContext.captureScreenshot`, `input.performActions`.

- **GATE, stated operationally:** all five commands round-trip successfully
  against a user-launched Firefox on a real profile, driving a read and a click
  end to end. "A few hundred lines" is the expectation, not the criterion; the
  criterion is that the five round-trip.
- **Why it runs early even though Lane C may ship later:** this is the one
  capability no competing MCP server has, because Playwright cannot attach to an
  existing BiDi session and Chrome forbids the equivalent. Knowing whether it is
  real changes the positioning.
- **FALLBACK:** Lane C Firefox moves to v1.1 and Lane C ships Chrome-only, which
  is the weaker story (DESIGN 4.4).

### S6: Seeded-profile fidelity — **DONE 2026-09-05, GATE PASSES**

Run in the same authorized Firefox-closed window as S5, under the full safety
protocol: firefox.exe-not-running gate before every copy, a hashed manifest of
the real profile before and after (24,170 files, **IDENTICAL**), copies
confined to the session scratchpad and random-overwritten then deleted at
spike end (verified gone), and cookie content never read beyond one sanctioned
HOST-presence query against a fixed low-stakes candidate list, booleans only.

**Sessions survive the copy.** The DESIGN 4.6 subset (`cookies.sqlite` with
`-wal` and `-shm`, `key4.db` + `logins.json` as a pair, `places.sqlite`,
`permissions.sqlite`) was seeded into a fresh directory, stock Firefox
launched against the COPY, and a logged-in session on a low-stakes site the
author uses verified **structurally** (a boolean presence check, never account
content): logged in. A second candidate site with cookies present reported
logged-out, which is the honest note that cookie presence does not equal
session validity; the gate needed one real session and got it.

**The measured minimal set is smaller than the design's list: `cookies.sqlite`
+ `-wal` + `-shm` ALONE carries web sessions.** A second launch seeded with
only the cookie store reproduced the logged-in state. `key4.db`/`logins.json`
are the saved-password store (Firefox mints fresh ones when absent), wanted
for autofill but not for session continuity; `places.sqlite` is history and
awesomebar quality-of-life. The WAL sidecars matter: the live profile had a
700 KB un-checkpointed WAL, so copying the bare `.sqlite` would silently drop
the newest cookies. Seed copies checkpoint the WAL on the COPY after copying
all three.

**Breakage list, measured:** nothing user-visible broke. Firefox treated the
seed as a normal profile, minting `compatibility.ini`, `parent.lock`,
`prefs.js`, `cert9.db`, `times.json`, and (Firefox 154) a `logins.db` derived
from the seeded pair. Omitting `compatibility.ini` from the copy caused no
refresh prompt (same-version launch; version skew remains untested). The
source profile's lock files were never touched and `user.js` hazards never
reached the source because the launch was direct `firefox.exe`, not
Playwright's `prepareUserDataDir` path. **The seeded-copy dogfood path is real
for Lane B daily use**, with seeding kept manual and explicit per 4.6.

### S6 (original definition)

Copy the named file subset (DESIGN 4.6) into a fresh directory, launch
`moz-firefox` against it, and check whether the author is still logged into two
or three real sites.

- **GATE:** sessions survive the copy.
- **MANDATORY VERIFICATION, not optional:** the SOURCE profile's `user.js` is
  byte-identical afterward. Checksum before and after. This is the rule the whole
  profile-safety section exists to protect.
- **FALLBACK:** "works with your logged-in browser" downgrades to "log in once
  inside KS4Web's profile," which is weaker and still shippable. Say the weaker
  thing rather than the stronger one.

### S7: Async plumbing and process hygiene under FastMCP — **WINDOWS SLICE DONE 2026-09-05, HOLDS**

Ten scenarios across both lanes, including the harshest available (server
process and the Node driver both `taskkill /F`d, which is the SIGKILL case the
whole section exists for). **Zero orphans in every scenario**, with full reap in
2.0 to 3.5 seconds. Chromium spawns 4 processes per session, `moz-firefox`
spawns 10 or 11, and all of them died. A hung navigation returned a
`TimeoutError` at 3,017 ms against a 3,000 ms budget on both lanes and the
browser stayed usable afterward, so a bounded per-operation timeout does free
the server.

**The confound was found and ruled out, and it becomes a GATE REQUIREMENT.**
The spike process was itself inside a Windows job object carrying
`KILL_ON_JOB_CLOSE`, inherited from the harness shell, and children inherit it,
which would have made every result the harness's doing. The harshest scenario
was re-run with `CREATE_BREAKAWAY_FROM_JOB` granted, genuinely outside any job,
and both lanes still reaped cleanly, so Playwright's death pipe is doing the
work. **The Phase 1 orphan gate must break away from the ambient job or it
proves nothing**, which is now written into that gate below.

Implementation hooks, all confirmed available and all now in DESIGN 4.7: job
objects work from plain CPython ctypes, **with the trap that HANDLE restypes
must be `c_void_p` or every call fails with `ERROR_INVALID_HANDLE` and the
reaper silently does nothing**; child-PID enumeration via
`Get-CimInstance Win32_Process` costs roughly 1.0 s for 557 processes, which is
shutdown-and-sweep speed rather than hot-path speed; and **Playwright's Python
API does not expose the browser PID**, so the owned-PID journal is populated
from the process table or from a job object KS4Web owns.

**Still outstanding for this spike:** the FastMCP integration half. This slice
measured process hygiene under hard kills, not a live FastMCP server holding a
Playwright instance across tool calls with a lifespan-managed browser and an
asyncio lock. That is Phase 1 work and the gate below still binds.

### S7 (original definition)

A minimal FastMCP server holding one `async_api` Playwright instance across tool
calls, with a lifespan-managed browser, an asyncio lock around context mutation,
a bounded per-operation timeout, and a kill path that terminates only the tree
KS4Web spawned.

- **GATE:** the browser survives across calls without leaking processes, a hung
  navigation is killed cleanly rather than hanging the server, and **SIGKILL of
  the parent leaves zero orphans**. That last one is the whole point: signal
  handlers provably do not survive SIGKILL, which is exactly how chrome-devtools-mcp
  accumulated 42 orphaned Chromes.
- **Not a kill criterion, a blocker.** If this is wrong, nothing ships until it
  is right.

### S8: MCP conformance and client-behavior probe — **DONE 2026-09-05, GATE MET; MRTR REFUTED, ELICITATION IS THE CHANNEL**

**Report:** `internal notes/20260905_ks4web_spike_s8.md`.
**Code:** `spikes/s8/` (raw stdio probe server plus a raw probe OF FastMCP),
wire logs preserved. **Client of record: Claude Code 2.1.220**, negotiating
protocol **2025-11-25**. Server stack: FastMCP 3.4.7 / mcp SDK 1.29.1.

Ten verdicts, each from the wire rather than from a doc:

1. **MRTR does not round-trip and `requestState` does not survive.** The
   2026-07-28 `input_required` shape passes through to the model as ordinary
   content; the "retry" that came back was a plain tools/call with the model
   paraphrasing `inputResponses` and no token. The kill criterion is honored
   the designed way: gates stay structurally fail-closed, and the echoed-token
   path the model produced is exactly what `redeem()` already refuses.
2. **Elicitation IS advertised (sampling is not) and the round-trip works
   mechanically**: a server-initiated `elicitation/create` was answered
   `{"action":"cancel"}` in 0.0 s by the headless client, so a gated action
   fails closed instantly with no hang. The interactive accept path is the
   author's one-line dogfood observation; Phase 6 wires gates to elicitation
   with fail-closed on cancel/decline/timeout/absence.
3. **The fail-closed classes complete end-to-end exactly as designed**: the
   simulated gated submit asked, was auto-cancelled, refused with nothing
   submitted. Where a human answers accept (interactive), the same wiring
   completes; headless stays refusal.
4. **The ~3,000-token subagent cap is REFUTED at 2.1.220**: 21,000 tokens
   arrived inline inside a real Task subagent; 24,000 spilled to a file with a
   2 KB preview. The subagent limit is materially the main-thread cap. The
   2,500 recipe stays with softened wording and a re-measure near ship.
5. **The 25,000-token cap manifests as spill-to-file with the path handed to
   the model**, not as truncation (30k-token result: "exceeds maximum allowed
   tokens. Output has been saved to ...").
6. **`readOnlyHint: true` unlocks real concurrency**: two hinted 3 s calls
   overlapped (3.2 s total); the unhinted pair serialized (6.0 s).
7. **Descriptions truncate at ~2,048 chars** with a model-facing
   "… [truncated]" marker; the tail sentinel was gone. The docstring-budget
   test's hard limit is confirmed load-bearing.
8. **`anthropic/alwaysLoad` and `anthropic/searchHint` behave as documented**
   on a 152-tool surface: the alwaysLoad tool stayed directly callable under
   deferral, and ToolSearch matched a word that exists only in a searchHint.
   The client's server-side `search_hints` override table has no entry for a
   third-party server, so our hints are what get indexed.
9. **FastMCP 3.4.7 does not implement 2026-07-28**: offered that revision it
   negotiates down to 2025-11-25, and `server/discover` errors -32602. **Q4's
   trigger has NOT fired**; under the negotiated revision the conformance
   claim has no hole.
10. **tools/list is identical across connections** of the shipped server
    (sha256-equal, two fresh stdio connections), and the Desktop
    mid-conversation checkbox question is **DEFERRED-NEEDS-HUMAN**: the one
    installed .mcpb carries no `user_config` at all, so there is no checkbox
    on this machine to observe, and the author's one-sentence manual check is
    in the report.

The original spike definition follows, kept verbatim as the record of what
was asked.

Every one of these is a binary fact the design depends on, and all are cheap to
check against the installed client.

**Run every check against the client version installed AT SPIKE TIME, and record
that version in the spike output.** The research baseline (v2.1.92) is already
well over a hundred releases stale, and at least one of these facts appears to be
delivered remotely rather than compiled in, so a quoted version number is not a
substitute for a fresh run.

- Launch-time pack selection produces an identical `tools/list` on every
  connection.
- **Does the installed FastMCP implement the `server/discover` RPC?** MCP
  2026-07-28 makes it a MUST for servers, and KS4Web does not implement the
  protocol layer itself, so this is a framework question with a framework answer:
  either FastMCP supplies it at the negotiated revision, or KS4Web's conformance
  claim has a hole it does not control. Record the FastMCP version and the
  revision it advertises, since that same version number is the trigger named in
  DESIGN Open Question 4.
- `anthropic/alwaysLoad` and `anthropic/searchHint` behave as documented in the
  binary read, on the installed Claude Code version. Check whether the client's
  server-side `search_hints` override table overrides a tool's own `_meta` hint.
- Elicitation is advertised; sampling is not; MRTR `InputRequiredResult`
  round-trips, and `requestState` survives the retry so the gate engine can
  correlate.
- The 25,000-token result cap, confirmed empirically. **And the subagent cap,
  measured rather than assumed:** DESIGN 3.2 records it as a field report of
  roughly 3,000 tokens that is apparently remote-delivered and therefore movable,
  so the job here is to find the CURRENT number by bisecting result sizes inside
  a subagent, and to re-check it near ship rather than trusting this run forever.
  The 2,500 subagent-safe recipe is set from what this measures.
- `readOnlyHint: true` actually unlocks concurrent execution.
- Tool descriptions truncate at 2,048 characters, and the model-facing text
  carries the "[truncated]" marker DESIGN 7.3 describes.
- **GATE:** every assumption in DESIGN Section 7 is confirmed or the design
  adapts before Phase 7 builds on it.

### S9: Chrome Lane B and C, and the App-Bound Encryption question — **DONE 2026-09-05, LANES GREEN; GATE ANSWERED AT SOURCE AND BINARY LEVEL, LIVE REFUSAL DEFERRED BY RULE**

**Report:** `internal notes/20260905_ks4web_spikes_s9_s10.md`.
**Code:** `spikes/s9/` on master, raw JSON in `spikes/s9/out/`. Chrome
152.0.7977.76 and Edge 151.0.4129.107 (152.0.4191.62 staged), both installed.

**Lane B is green on both branded channels.** `channel="chrome"` and
`channel="msedge"` each ran the full S3-shaped battery, 28 of 28 steps OK:
persistent context on a throwaway profile, navigate, read, click, fill,
evaluate, screenshot, headless and headed, with provenance proven from the
process table (every new process at the installed binary's path). DESIGN 4.3
called the Chrome side "mature, low risk"; it is now measured rather than
assumed, and Edge is on the record for the first time.

**Lane C works end to end on both browsers, including the fact Lane C cannot
live without.** A user-style launch (headed branded binary, scratch
`--user-data-dir`, `--remote-debugging-port`) accepted `connect_over_cdp`,
drove a read, a click, and a screenshot, and **`browser.close()` DISCONNECTS
without killing the user-side browser** on both Chrome and Edge, verified by
the launched process surviving the disconnect. No approval prompt interfered
at Chrome 152 on a non-default directory.

**The gate, honestly.** The spike was told not to take the blog post's word
for the Chrome 136 failure mode, and it did not; it also could not observe the
refusal live, because the only directory Chrome's check recognizes as default
on this machine is the author's real profile, and the profile rule is
absolute. What it did instead:

- **Mechanism pinned from the shipped source tag (152.0.7977.76):** the check
  is a PATH COMPARISON, `chrome::IsUsingDefaultDataDirectory()` feeding
  `IsRemoteDebuggingAllowed`, refusing with `NotStartedReason::
  kDisabledByDefaultUserDataDir` on branded builds, with a policy gate
  (`prefs::kDevToolsRemoteDebuggingAllowed` -> `kDisabledByPolicy`) and, new
  in the 152 era, `features::kDevToolsAcceptDebuggingConnections`, an
  approval mode for debugging connections.
- **The exact refusal text extracted from the shipped binaries on this
  machine**, not from any blog: `DevTools remote debugging requires a
  non-default data directory. Specify this using --user-data-dir.` It is
  byte-identical in `chrome.dll` 152 and `msedge.dll` 151 AND 152, which
  moves the Edge-inherits-the-restriction community claim from "reported"
  to "the identical code path ships in Edge's binary." The live behavioral
  run on a true default profile is the one residue, deferred to any machine
  or throwaway Windows account whose default profile is disposable.
- **Headless never hits the restriction, measured:** `--headless=new` with a
  debug port and no `--user-data-dir` opens the port on BOTH browsers because
  headless uses an EPHEMERAL profile (`%TEMP%\HeadlessChrome<digits>` /
  `HeadlessEdge<digits>`, read via `chrome://version` over CDP), never the
  default directory.
- **A bypass exists and is now measured, because Chrome computes the two
  paths differently:** the USED directory (no switch) comes from
  install_static expanding the `LOCALAPPDATA` environment variable, while the
  default it is COMPARED against comes from the shell known-folder API, which
  ignores the environment. A launch under a redirected `LOCALAPPDATA` (the
  spike's scratch-default method) therefore minted its "default" User Data in
  scratch and **got the debug port**, headed, no switch, on both browsers.
  Chrome 136's restriction is real and also not airtight.

**The App-Bound Encryption question is answered, with one deferred edge.**
Cookie stores minted in ANY non-default data directory are **v10 DPAPI, not
v20 app-bound**, and the reason is in the shipped source: the ABE provider
checks the data dir and withholds the app-bound key
(`SupportLevel::kNotUsingDefaultUserDataDir` ->
`KeyError::kTemporarilyUnavailable`). Measured on both browsers: a profile
minted at a (scratch) default path, whole `User Data` tree copied to a
non-default path, **cookies decrypt and are served after the copy**, same
machine and user, verified server-side by the fixture receiving the Cookie
header. The consequences split cleanly: KS4Web-owned Chrome and Edge profiles
always run DPAPI-mode cookies, so copies and relocations of THOSE are safe;
but a REAL default profile's cookies are v20 app-bound values that the
provider cannot unwrap at any non-default path, so **seeding a Chrome profile
from the user's real profile is expected NOT to carry sessions**, pending the
same disposable-default-machine run. Chrome seeded profiles are the opposite
of Firefox's S6 result, and DESIGN 4.4's "worse story than Firefox" now has
its mechanism.

**Two hygiene findings the probes forced, both now design inputs (DESIGN
4.7).** Edge's startup-boost keep-alive (`msedge --no-startup-window`) can
RESPAWN after a graceful close, holding the profile's Cookies store, with a
command line that names nothing of ours while its crashpad CHILD names the
profile directory, so teardown sweeps must loop and may take a parent on the
child's evidence. And force-killing a browser's lagging children too soon
after a graceful root exit loses the cookie flush (measured: a 1.5 s kill lag
cost the minted cookie; a 10 s descendant-wait recovered it).

Zero orphans of ours in every script, with third-party churn attributed
rather than hidden: the author's Firefox restarted itself on its real profile
mid-run (14:55:24 parent.lock, bare command line, never touched), and another
tool's debug Chrome appeared and was correctly refused by both kill fences.
The author's real Chrome profile was scanned read-only afterward: zero files
modified. No spawn ever named a real profile path.

### S9 (original definition, kept as the record of what was asked)

`channel="chrome"` with a KS4Web profile directory, then `connect_over_cdp`
against a Chrome started with a non-default `--user-data-dir`.

- **GATE:** confirm firsthand that Chrome 136+ ignores the debugging flag on the
  default data directory. Do not take the blog post's word for the exact failure
  mode.
- **Probe Edge alongside Chrome, same two tests.** DESIGN 4.3 offers `msedge` as
  a Lane B channel, and Edge inheriting the Chrome 136 default-profile
  restriction is community-reported rather than officially documented, so it is
  an assumption the plan would otherwise carry into a shipped lane untested. If
  Edge behaves differently in either direction, that belongs in the capabilities
  truth table and the Known Limitations page.
- **Open empirical question this resolves:** does a Chrome `User Data` directory
  copied to a non-default path still decrypt its cookies on the same machine and
  user account? App-Bound Encryption makes this genuinely uncertain and it
  determines whether Chrome seeded profiles are useful at all.

### S10: Weight and install measurement — **DONE 2026-09-05, GATE DECIDED: NO BROWSERS SHIPPED, CHROMIUM LAZY ON FIRST USE**

**Report:** `internal notes/20260905_ks4web_spikes_s9_s10.md`.
**Code:** `spikes/s10/` on master, raw JSON in `spikes/s10/out/`. Everything
ran in scratch (fresh venv, scratch `PLAYWRIGHT_BROWSERS_PATH`) and was
deleted after measuring; the user's Playwright cache was never touched.

**Install bill, measured 2026-09-05 (network times are network times):**
fresh venv 11.1 s; `pip install playwright --no-cache-dir` 11.0 s and
**+108.2 MB** of site-packages (the 38.2 MB wheel, installed) at 1.62.0;
`playwright install chromium` 43.9 s and **701.0 MB on disk** (chromium plus
the headless shell plus ffmpeg and winldd, which is why the on-disk figure
dwarfs the 281 MB download the design quoted); `firefox` 21.3 s and
**+336.5 MB**; `webkit` 10.7 s and **+169.1 MB**. All three engines together:
**1,206.7 MB** on disk plus a 119.5 MB venv.

**Resident memory on the same frozen Versailles page, settled 6 s, summed
over the browser's own process tree** (working set overstates a multi-process
tree because shared pages count once per process; private bytes is the
honest cross-tree sum): bundled Chromium HEADLESS 4 processes, 267.5 MB WS /
**129.6 MB private**; bundled Chromium headed 7 processes, 490.2 / 286.4;
`moz-firefox` headed (the dogfood shape) 12 processes, 1,178.6 / **898.4 MB
private**, roughly 6.9x headless Chromium. The Playwright node driver idles
at 104.7 WS / 91.4 private alongside any of them.

**GATE, decided on the numbers:** ship with NO browsers. Install Chromium
lazily on first use (44 s and 701 MB, once, and the cheapest RAM at run
time). Firefox and WebKit stay opt-in downloads, and `moz-firefox` remains
the zero-download lane when Firefox is already installed, at a measured and
disclosed memory premium. This is the expectation the spike was asked to
check, now held up by measurement rather than by preference.

### S10 (original definition, kept as the record of what was asked)

Time and measure `pip install playwright` plus `playwright install` per engine;
measure resident memory for a headless Chromium page against a headed
`moz-firefox` page.

- **GATE:** decide the default install profile. The expectation is ship with no
  browsers, install Chromium on first use, and treat Firefox and WebKit as
  opt-in, since `moz-firefox` needs no download at all when Firefox is already
  installed.

### The spike gate

**The architecture freezes only when S1 and S2 are green and S3 through S10 have
reported.** S1 green means the product exists. S2 green means it is cheap for a
whole session and not just one call. Everything else is a delivery decision.

**Status 2026-09-05, after the S1 and engine rounds:**

| Spike | Status |
|---|---|
| S1 projection proof | **GREEN**, VALIDATED-WITH-CAVEATS, absorbed |
| S2 anchor durability | **GREEN**, zero false rebinds over 396 resolutions, absorbed |
| S3 `moz-firefox` | **GREEN**, HOLDS, absorbed |
| S4 BiDi gaps | **GREEN**, lanes at full standing, absorbed |
| S5 Firefox live attach | **GREEN**, all five commands round-trip over the in-house raw BiDi client; Lane C Firefox is real |
| S6 seeded profile | **GREEN**, sessions survive; minimal set is cookies.sqlite + WAL sidecars; source profile hash-identical |
| S7 process hygiene (Windows slice) | **GREEN**, HOLDS; FastMCP integration half is Phase 1 |
| S8 MCP conformance | **DONE 2026-09-05, GATE MET**: MRTR refuted on the installed client, elicitation is the live channel, subagent 3k cap refuted, hints and readOnlyHint confirmed |
| S9 Chrome and Edge Lane B/C | **DONE 2026-09-05**: Lane B green on both branded channels (28/28), Lane C works on both incl. disconnect-leaves-browser-running; restriction pinned at source and binary (Edge ships the identical code path); ABE answered: non-default dirs mint v10 DPAPI and copies decrypt, real-profile v20 seeding expected NOT to carry sessions; live default-dir refusal deferred by the profile rule to a disposable machine |
| S10 weight and install | **DONE 2026-09-05, GATE DECIDED**: no browsers shipped, Chromium lazy on first use (43.9 s / 701 MB); all engines 1,206.7 MB; headless Chromium 129.6 MB private vs headed moz-firefox 898.4 MB |
| E11 latency (transferred from S1) | **DISCHARGED**, bound set |

**S1 is green and its two failed numeric targets were the design's numbers
rather than the design's thesis**, both restated in DESIGN 3.2 from
measurement. Neither S1 kill criterion tripped and neither did S3's or S4's.

**The gate is PASSABLE as of 2026-09-05.** S1 green means the product exists;
S2 green means it is cheap for a whole session rather than one call, and it is
now measured: 396 resolutions, zero false rebinds, zero false stickiness, with
100 percent ref survival through a re-render that destroyed 77 percent of the
DOM nodes. The architecture freezes. **Every spike has now reported: S8, S9,
and S10 closed on 2026-09-05**, each a delivery decision rather than a test of
whether the product exists, and none tripped a kill. S5 and S6 ran on 2026-09-05 in the authorized
Firefox-closed window and both gates PASS: **the Lane C Firefox differentiator
is VERIFIED** (raw BiDi attach to a user-style stock launch, five commands
round-tripping, no Playwright involved) and the seeded-copy dogfood path is
real, with the source profile hash-verified untouched. Q9 (the dogfood
commitment) is now the only thing between Lane C and its public claim.

Spike outputs are saved as permanent artifacts to `Draft/Working Files/Agent
Results/` with DTG names, per house rule.

### The rulings checkpoint

The twelve open questions in DESIGN Section 11 are not schedule-neutral, and a
plan that never says when they get answered will discover the coupling by
building the wrong thing first. Rulings are collected here, between the spike
gate and Phase 0, because several of them decide what Phase 0 writes down.

| Question | Blocks | Why it blocks |
|---|---|---|
| Q11 names, alias, env vars | **Phase 0** | Q11 IS the Phase 0 `pyproject`: package name, console scripts, env prefixes. **RULED 2026-09-04** (KitchenSink4Web / KS4Web, Garden department, alias `web`). |
| Q11a the twelve env vars Phase 1 added, Q11b the `manage_session` lane string | **nothing, until Phase 9** | Neither blocks a phase and both become compatibility surface at first release, so the deadline is the docs pass rather than a gate. Q11a asks which variables are supported surface and whether the launch-shape four collapse into one; Q11b ratifies or overturns a build decision taken on schema-budget grounds. Both recorded in DESIGN 11. |
| Q6 browser verb grammar | **Phase 0 and Phase 2** | Q6 names the first three tools Phase 2 lands, and a reversal after Phase 2 renames the whole surface. **RULED 2026-09-05** under standing delegation, flagged for author review, reversible until ship. |
| Q2 screenshot in lite | **Phase 3, and Phase 7's gate** | Changes the lite budget arithmetic and the wording of discoverability rule 1, since lite currently promises no pixel path at all and the Phase 7 gate tests exactly that refusal. |
| Q5 read-only by default | **Phase 3** | Read-only is enforced at registration time, so the default decides Phase 3's registration behavior, every quickstart line, and the dogfood default the author lives with from Phase 4. |
| Q10 workflows in v1 | **Phase 6** | Decides whether Phase 6 runs at all, and the drop is not free (see the scope fence). |
| Q9 dogfood commitment | **S5 and W7** | Decide before S5 effort is spent, not after: if the author declines to run `--remote-debugging-port` permanently, Lane C Firefox stays technically real but loses its dogfood log, its demo, and the standing to recommend publicly what the author does not do personally. |
| Q3 Chrome Lane C in v1 | **S9 scope** | Sets how much of the Chrome Lane C probe is worth running. |
| Q1 license | nothing structural | Genuinely decoupled. DESIGN 10.3's license-agnostic rules bind from Phase 0 regardless, and the `LICENSE` file is a Phase 9 artifact. |

Q4 (the family `enable_tools` question) blocks nothing in this build, since
KS4Web does not ship the pattern, but S8 supplies the FastMCP version and
negotiated revision that the ruling should name.

---

## 3. Build phases

**Every phase ends the same way: full suite green, the phase gate green, a git
commit on the build branch, a dated BUILD_LOG entry, and a memory checkpoint
appended to `project_mcp_tooling.md`. No phase starts until the prior one is
saved.** Rate limits checked (`/token-check`) before every agent batch.

Standing safety rule for this build, the browser analog of the family's
Excel-closed and PowerPoint-closed rules: **agent rounds never attach to the
author's live browser.** Lane C work uses a deliberately-launched fixture
Firefox, never the daily one, until the author personally runs the dogfood pass.

### Phase 0: Scaffold and ports

- Repo, `pyproject` (`kitchensink4web`, alias `web`, console scripts), src
  layout, Python >= 3.12, **no LICENSE file** (DESIGN 10.3 rule 5).
- Ports per 1.1: envelope with the browser code map, sandbox, errors, regex
  guard, `measure_surface.py`, docstring-budget and no-em-dash tests.
- **The dependency license ledger starts here**, with the rule enforced by a
  test: no copyleft or source-available dependency in the required install.
- The `policy/` / `engine/` / `ops/` package boundary with a **test that fails
  if `policy/` ever imports from `ops/` or `engine/`**. The open-core seam is
  cheap to keep and expensive to retrofit, so it is enforced mechanically from
  commit one.
- `glama.json` as a two-field claim file; `mcp-name` marker discipline noted for
  the ship phase.
- **GATE:** ported machinery's own tests green, `measure_surface` runs, the
  import-direction test passes, no browser needed yet.

### Phase 1: Engine core

- Lane A/B/C resolution, lazy install, lazy start, the session and page handle
  model (explicit handles per spec 2026-07-28), `manage_session`, the
  capabilities truth table seeded from S4.
- `engine/hygiene.py`: all three defenses plus the owned-PID journal.
- **GATE (a hard one):** zero orphan processes after 50 session cycles including
  **SIGKILL of the server parent**, verified by owned PID on Windows, plus a
  clean startup reap of deliberately-orphaned profile dirs, plus an idle-timeout
  park verified by CPU measurement. This is the gate that makes "we do not leak
  browsers" true rather than asserted, and it is the row where the most-installed
  browser MCP server in the world is currently open and unfixed.
- **The orphan test MUST demonstrate that it can FAIL**, per S7's confound. A
  shell that owns a `KILL_ON_JOB_CLOSE` job reaps the tree for you and every
  result comes back green whether or not the server has any teardown at all. A
  gate that cannot fail is not a gate, and this one silently could not.

  **The gate definition names two instruments and requires the second
  (revised 2026-09-05, from the Phase 1 run).** As originally written it named
  breakaway (`CREATE_BREAKAWAY_FROM_JOB`) alone, and breakaway is not portable:
  the ambient job on this machine carries `SILENT_BREAKAWAY_OK` with
  `BREAKAWAY_OK` off, so the flag is denied on some paths and accepted on
  others and the child stays inside a kill-on-close job either way, WMI
  `Win32_Process::Create` included. **So the required instrument is a NEGATIVE
  CONTROL** run before the KS4Web scenarios: a browser started under plain
  `Popen` with no death pipe, no job object, and no teardown, whose parent is
  hard-killed and which MUST survive. Phase 1 measured 11 orphans from that
  control against zero from every KS4Web row. Breakaway stays as an optional
  second instrument wherever the environment grants it. This is a revision that
  serves the original requirement rather than relaxing it: breakaway was a
  proxy for "the harness is not doing the work" and the control measures that
  property directly on whatever machine the gate runs.
- **`-no-remote` on every Firefox launch is a Phase 1 acceptance item**, not a
  Phase 4 polish item (DESIGN 4.3, 4.6). It is the difference between an owned
  profile and an owned browser.
- Two mechanics are already known and do not need rediscovering: ctypes HANDLE
  restypes must be `c_void_p` or the job-object reaper silently no-ops, and
  Playwright does not expose the browser PID, so the owned-PID journal is
  populated from the process table or from a job KS4Web owns.
- **Three more are now known, from the Phase 1 build, and each is a defect the
  obvious implementation has** (DESIGN 4.7, facts 5 through 7). `OpenProcess`
  succeeds on a process that has exited while anyone holds a handle to it, so
  liveness waits on the process handle rather than asking whether the PID
  opens. A parent-PID walk adopts strangers through recycled PIDs, turning a
  five-process tree into a forty-process claim on this machine, so every
  inferred parent relationship carries a creation-time check. And the process
  census runs on Toolhelp32 at single-digit milliseconds rather than CIM at
  ~1.0 s, which is what makes a per-launch census affordable and therefore what
  makes the journal's arrival-difference filter possible at all.

### Phase 2: Projection and anchors (the keystone) — **RUN 2026-09-05, GATE GREEN, ALL NINE ITEMS**

**Status.** The suite is 285 tests, up from 218. The anchor system landed
whole (`anchors/`: the key ladder, the sticky element map, the rebind ladder,
the delta engine) and the S2 battery is ported into it, running against the
SHIPPED code rather than the prototype: **zero false rebinds and zero false
stickiness across 9 scenarios, 145 resolutions**, with the documented cost of
the page key (an app shell loses its refs on a hash route change) asserted
rather than denied. `get_page_view` gained `location` and `since`;
`find_elements` and `get_text` landed. Corpus B is built (19 pathological
pages) and the widened benchmark set is frozen (5 pages, GitHub nav bar
intact).

**Both measured debts are discharged.** The Versailles rung cliff is gone: the
steps around the default budget are 2.2, 2.9, 4.0, 3.4 and 4.9 percent against
the 19.7 percent step that made a page 465 tokens over budget arrive 817 under
it, and the delivered read is 4,356 rather than 3,683. The live drift on that
page fell from plus 15.3 percent to plus 2.4, which is the independent
confirmation. The GDP structure read recovered 124 tokens from two real
defects and then SPENT 363 restoring the page navigation a third defect was
suppressing, so **the published target moved from 3,000 to 3,500 and the gate
prints `PASS (target REVISED from 3000)` rather than a bare green.**

**Gate part 7, the executable prices, closed on its second pass.** 65 priced
units on four frozen pages, 36 above the noise floor: **median error 6.3
percent, worst 27.1, rank correlation 0.993, nothing outside the 35 percent
band.** The five outliers that held it red were two defects rather than one.
Four of them were the MEASUREMENT: `get_text` was flattening hidden and
nested text into what it returned, which also means it was handing callers a
hidden menu while its own counter reported the same characters as withheld.
The fifth was the price, and it was the article's own data table charged at
the prose rate of the page around it. Units now carry a bounded sample of
their own text and are priced at their own measured characters-per-token
rate, and the price carries no call overhead because it is a content size.
Nothing is calibrated per fixture and no content-class constant was
introduced; the live drift check on corpus A is the standing check that it
stays honest. Full numbers in `gates/phase2.json`; the reasoning is in
DESIGN 3.3a and the finding list is in the BUILD_LOG.

The two modules everything else is downstream of. Built together because deltas
require sticky refs and sticky refs are only useful because reads are cheap.

- `projection/`: readability gate, landmark segmenter, affordance ranker,
  content digest, form and table inventories, DOM projection with attribute
  allowlist, hidden-content normalizer, completeness accounting, degradation
  ladder, budget meter.
- `anchors/`: fingerprints, sticky element map, rebind ladder, delta engine.
- `get_page_view`, `find_elements`, `get_text` land here as the first three
  tools.
- **GATE, nine parts, all required.** Parts 6 through 9 are S1's corrections
  promoted to gate items, because each one was a defect that a blind agent
  caught while the projection was comfortably under budget, which is exactly the
  failure class a token-only gate does not see.
  1. **The measured token bill meets every target in DESIGN 3.2** on the frozen
     benchmark set. Reported by the harness, not by hand, and counted with the
     named estimator (`tiktoken`, `o200k_base`) so the gate number and the
     enforced budget are the same arithmetic. **The revised targets bind**, not
     the pre-S1 ones: under 900 on httpbin, structure and row page priced
     separately on the GDP table, and the 570-token scaffold floor
     acknowledged rather than chased. **Two rows are already known to need a
     ruling before this gate can be called** (DESIGN 3.2, re-measured on frozen
     corpus A 2026-09-05): the GDP structure read is 3,166 against a 3,000
     target, and the Versailles read is delivered at rung 3 because its
     undegraded form is 4,965 against a 4,500 effective budget.
  2. **Refs are sticky** across re-reads on every fixture, and **zero false
     rebinds** on the pathological fixture.
  3. **The completeness block is accurate**, verified by construction: the
     virtualized list, the closed shadow roots, the cross-origin iframe, and the
     canvas region in fixture B must each be REPORTED, and a deliberately
     injected hidden element must be counted rather than missed or silently
     included.
  4. **The degradation ladder never truncates mid-structure**, verified by
     forcing every rung on the 50,000-node fixture. Rung 5's capped inventories
     (DESIGN 3.4) are exercised specifically: a fixture form with several hundred
     fields must collapse to the one-line form summary and stay under budget
     rather than refusing. **The ladder is also asserted MONOTONIC AS EXPOSED**
     per page across every rung, since S1's prototype got bigger at rung 4 on
     httpbin. **Phase 1 found that non-increasing caps do not deliver that**:
     dropping a unit can cost more than it saves once the completeness block
     accounts for what went, measured at 37 tokens on the `names` fixture, so
     the property is enforced by **never choosing a dominated rung** rather than
     by reasoning about the caps. The gate asserts the exposed sequence, which
     is what a caller can actually be handed, and permits an internal step to
     grow as long as no caller ever receives it.
  5. **The latency budget holds, and the numbers are now set from
     measurement** (E11, discharged in the engine round; DESIGN 3.6a):
     **projection p95 at or under 500 ms up to 50,000 nodes, at or under 1.0 s
     up to 100,000 nodes, Python-side assembly at or under 10 ms.** Written
     into the harness rather than remembered, and tracked at every phase gate
     afterward. Two consequences that shape Phase 2's build rather than only
     its gate: **the hidden-content normalizer sweeps every node** and is not
     sampled or capped, because the full sweep is 22 percent of extract and
     restricting it to interactive candidates would buy 14 percent while losing
     hidden-content detection on non-interactive nodes; and optimization
     effort, if any is needed, aims at the affordance, accessible-name, and
     digest work, which is the other 60 percent. **A third consequence arrived
     with the Phase 1 build and it outranks both:** the payload crossing the
     driver boundary is a cost term of its own, measured at 604 ms of round
     trip against 245 ms of in-page work on a 5,000-heading fixture, so the
     extractor **caps what it RETURNS and tallies what it COUNTS**. The
     completeness figures come from the extractor's own integer tallies rather
     than from the length of any list held in Python, which is what let the cap
     land without costing a single figure. The gate checks that property
     directly, since an implementation that derives "omitted 2,700" from a list
     has to carry 2,700 things to say the number.
  6. **Affordance quotas hold on the adversarial cases.** On the frozen GitHub
     repo page, every tab in the repository navigation bar appears in the
     projection. On Versailles, in-prose citation links appear zero times in the
     affordance list and their suppressed count appears in the completeness
     block. Every link affordance prints an href path, and no two affordances
     share a line without a distinguishing token. This part exists because S1's
     proximity ranker buried thirteen navigation tabs with 2,762 tokens of
     headroom unused. **The form-control quota is scoped to controls INSIDE a
     form** (DESIGN 3.3, narrowed during the Phase 1 build): the "complete,
     never sampled" guarantee applies to form members only, because letting
     every loose input on an app shell claim it turns the guarantee into the
     flood it was written to prevent. The gate exercises an app-shell fixture
     carrying loose controls outside any form and requires them to compete in
     the primary-actions class rather than arriving exempt.
  7. **Every printed price is executable and accurate.** For each priced unit,
     the harness issues the exact call the projection advertised, measures the
     result under the same estimator, and compares against the advertised
     figure. Section costs computed over true section containers, overlapping
     regions priced net of children, and NEXT CALLS ranked by expected value
     rather than size (no overlapping parent ranked above its own children). A
     price with no executable call, or a price outside tolerance, is a red gate.
     **Amended 2026-09-05, twice, both times because the run found the
     definition wrong rather than the code.** First: "compare the result
     against the advertised figure" assumes expanding a region returns that
     region, and it returns another budgeted projection, so the comparison is
     against `get_text` on the same region net of its nested regions, which is
     an independent measure of the content the price is about (DESIGN 3.3a).
     Second: regions holding under 60 tokens are reported and NOT gated, since
     an error ratio against them is a statement about call overhead rather
     than about the price. The band itself was not moved and no price was
     marked low-confidence to pass: the outliers were fixed. **Closed green on
     the second pass: 36 gated units, median 6.3 percent, worst 27.1, rank
     correlation 0.993.**
  8. **The completeness block is derived, not recomputed.** Its accounting comes
     from the same ledger the budget meter kept while enforcing the budget
     (DESIGN 3.3 block 7). Tested by construction: any figure the block can
     produce independently of the meter fails, and the "0 regions not expanded
     while thirty regions carry expand costs" case is a named regression test.
     Dynamic section numbering or always-emitted blocks with an explicit "none";
     a silent jump from section 4 to section 7 fails.
  9. **Accessible names are computed, not scraped.** Verified against fixtures
     built from the S1 failures: a heading with an adjacent count badge must not
     fuse (`General4`), a region must not take a name from a non-rendering
     error element (`"Uh oh!"`), names truncate on word boundaries with an
     explicit ellipsis, and a CSS class is never emitted as a name. **The
     `"Uh oh!"` fixture must specifically hide the heading through an
     ANCESTOR**, not on the heading itself, because that is the shape of the
     real page and it is the shape that defeats an element-local visibility
     check. Phase 1 reproduced the original bug while believing the rule had
     retired it, for exactly that reason. A region label requires the whole
     ancestor chain up to the region to be visible (DESIGN 3.7, sub-rule 5). The
     name-quality flag in the completeness block counts every fallback. The
     lead paragraph comes from the readable region only, tested against a
     fixture carrying a DRM-style error string ahead of the real content.

### Phase 3: The policy layer (built BEFORE the action tools, deliberately) — **RUN 2026-09-05, GATE GREEN, ALL ELEVEN PARTS**

**Status.** The suite is 361 tests, up from 285. Corpus C is built (9
adversarial pages, `corpus/c/`) and the gate (`scripts/gate_phase3.py`,
record in `gates/phase3.json`) drives it end to end on live Chromium: the
leaky tool caught by the SERIALIZER on the wire, the TOCTOU swap aborting
`TARGET_CHANGED` against the live page with the E6 rebind interlock
asserted, the mid-action redirect to a denied origin parked to about:blank
with nothing read from the landing, all nine hiding techniques in the counts
and never in the content (base64 and zero-width included), read-only
registering zero mutating tools under both grades and BOTH defaults behind
the one `DEFAULT_GRADE` constant, the disable-gates page finding no
mechanical path, gates failing closed structurally (forged and unredeemed
tokens never execute), budgets and loops tripping with the reset gated, the
three walls named, secret values reaching no payload, and the whole run
recorded redacted and bounded in the audit log.

**Three fresh author rulings landed this phase and are recorded in DESIGN**
(5.2 + Q5: read-only built completely under a CONDITIONAL default, one
constant, the .mcpb checkbox UX, and the never-flippable-in-session
invariant enforced by `tests/unit/test_readonly_invariant.py`; Q2:
screenshots stay out of lite; 2.1/3.2: token budgets are SOFT, the lite
ratchet advisory with measured honesty in `gates/docstring_budget.json`).

**One real defect found by the gate and fixed:** `get_text`'s hidden
detector had no contrast, geometry, or text-indent rule, so a
white-on-white injection stripped from the page view rode out of the prose
read as content. The two detectors now share every technique rule (DESIGN
5.1), and the Phase 2 gate was re-run green afterward to prove the shared
instrument moved no measured number.

**Wired live this phase:** `navigate` runs the full policy ladder including
the landed-origin re-check and Retry-After honor; `get_audit` is built;
`get_text(include_hidden=True)` returns the labeled hidden section;
`manage_session` gained `budget` (enforced) and `reset_budgets` (gated).
Phase 4's action tools call `policy/engine.approve()` and inherit all of it.

The original phase definition follows, kept as the record of what was asked.

This ordering is a design decision, not a convenience. If the action tools exist
first, some of them will be written outside the policy path, and the incumbent's
own history proves that per-tool discipline fails the moment someone adds a
feature.

- Read-only mode enforced at REGISTRATION time (mutating tools are absent from
  `tools/list`, both grades).
- Credential blindness: secret-field detection, refusal on write, masking on
  screenshot with **fail-closed** behavior when masking is unavailable, masked
  storage reads, `save_auth_state`.
- **Redaction in the envelope serializer**, on every outgoing payload and every
  file write.
- Origin allow/deny evaluator, deny evaluated first.
- Budgets, loop detection, per-domain rate limiting with 429 and `Retry-After`.
- The gate engine with TOCTOU re-validation, over MRTR first and elicitation
  where advertised, **failing closed** where the client advertises neither.
- The audit writer.
- **GATE:** the adversarial safety fixture (corpus C) is driven end to end and
  every class is refused, gated, or logged as designed. Specifically: a
  deliberately leaky test tool that tries to emit a cookie value into a payload
  must be caught **by the serializer**, not by the tool. A TOCTOU swap must abort
  with `TARGET_CHANGED`. A mid-action redirect to a blocked origin must abort. A
  hidden-text injection payload must appear in the completeness count and not in
  the content. Read-only mode must show zero mutating tools in `tools/list`.

### Phase 4: Action tools and verified outcomes — **RUN 2026-09-05, GATE GREEN, ALL EIGHT PARTS**

**Status.** The suite is 384 tests, up from 361. The six acting tools
(`click`, `type_text`, `fill_form`, `press_keys`, `scroll`, `wait_for`) are
wired through the Phase 3 choke point via one shared machinery module
(`ops/act.py`): resolution against the LIVE page (the rebind ladder for a
stored ref over a fresh extraction, a deterministic live resolver for css /
xpath / text / role+name / testid / coordinate / nth / describe that refuses
ambiguity with the candidate list), trusted input through the driver, and a
verified outcome (MutationObserver + url / activeElement / target-state diff).
`navigate` and `manage_tabs` were wired in earlier phases and were not
duplicated. Gate `scripts/gate_phase4.py`, record `gates/phase4.json`, on live
Chromium against corpus B (pathological) and corpus C (toctou).

**The two folded-in items are done.** The latency gate's assembly check now
carries the same reference-arm load control the projection check has (a loaded
machine reports UNCERTIFIED, not RED, on a sub-ms wobble). The completeness
block discloses how many priced units fell back to page-rate pricing, one
honest count emitted only when the 40,000-character sample budget was actually
spent; it moved the two large corpus-A pages +44 tokens each (GDP 3,399 ->
3,443, Versailles 4,364 -> 4,408, both still under target) and left the two
trivial pages unchanged, re-measured in `gates/corpus_a.json` and the Phase 2
gate re-run green.

- `click`, `type_text`, `fill_form`, `press_keys`, `scroll`, `wait_for`,
  `navigate`, `manage_tabs`.
- Verified outcomes on every action (DESIGN 5.7).
- Trusted input dispatch through the driver, never JS synthesis.
- **GATE:** on the pathological fixture, **no false successes.** The
  `event.isTrusted` React control, the overlay-intercepted click, the
  `<div onclick>` button, the moving target, and the portal dropdown each
  produce either a correct action with a verified effect or an honest refusal
  with a named recovery. Nothing returns bare `ok` with `effect: "none-observed"`
  unreported. **MET:** trusted input fires the isTrusted control and the div
  button (verified via the fixture's own `window.__effects`), the overlay and
  the moving target refuse `TIMEOUT` naming the cause and never fire, the portal
  trigger's click is verified by the menu it opens. Plus the run's
  non-negotiables: every mutating action tool proven refused-invisible under
  read-only over a real MCP client (both grades, uncallable); the Phase 3 TOCTOU
  battery re-run against real action execution (a swap between confirm and
  execute aborts `TARGET_CHANGED` at the choke point and the destructive form
  never submits); session isolation characterized (each session owns a disjoint
  browser process tree and sticky map, so the document family's cross-process
  single-instance concern is structurally absent); latency re-verified; suite
  green; the lite docstring bill measured and published honestly (budgets SOFT).
- **The author's dogfood pass starts here.** From this phase forward the author
  runs KS4Web daily on Lane B, and field bugs outrank new features.

### Phase 5: The capability packs

Parallelizable across disjoint modules with one integrator, the KS4XL wave
pattern.

- Wave A: `extract` (tables, lists, links, metadata, schema-directed fields,
  export).
- Wave B: `capture` (screenshot with caps and masking and **media-type
  correctness**, PDF, save page) and `emulate`.
- Wave C: `network` (requests, bodies, HAR, routing with ad and analytics
  blocking by default).
- Wave D: `storage` and `files` (downloads with a scoped directory, uploads
  including synthetic-DataTransfer dropzones).
- Wave E: `diagnostics` (console errors-only default with dedup, page errors,
  `evaluate_script` gated and audited).
- **GATE per wave:** module suite green. **GATE for the phase:** a screenshot
  round-trip cannot produce a mismatched media type under any code path (a
  regression test aimed directly at the defect that permanently poisons
  sessions), and `list_console` on the thousand-line fixture returns a bounded,
  deduplicated result.

### Phase 6: Workflows and replay — **RUN 2026-09-05, GATE GREEN, ALL SEVEN PARTS**

**Status.** The suite is 438 tests, up from 415. The three honest Phase 5
stubs are real tools. The audit trail is the recording substrate exactly as
DESIGN 5.6 argues: every replayable lite tool now enriches its audit record
with a `replay` block carrying the full arguments and the target's durable
ANCHOR (never its ref); `save_workflow` reads those back into a JSON file of
anchors; `run_workflow` re-resolves every anchor against the live page
through a new `ladder.resolve_anchor` (page-key first, strongest keys, the
two role+name tiers, no fuzzy tier, no first-match action), runs the
mandatory dry run first, and replays each step through the REAL lite tools so
every step inherits the whole policy ladder. `list_workflows` enumerates the
store. Nothing here can evaluate script: the replayable set is CLOSED and
excludes `evaluate_script`, which closes the #1645 fork.

**The confirmation wiring is what S8 proved, not what the design assumed.**
A gated step rides the elicitation channel (`confirm.attempt`): on an
explicit human ACCEPT the gate is redeemed and DEPOSITED context-locally, the
refused call re-runs once, `gates.ENGINE.ask` consumes the deposit instead of
raising, and the TOCTOU re-validation holds the action to the confirmed
fingerprint. No token ever rides a tool argument. Fail-closed is the default
everywhere else (headless auto-cancel, decline, timeout, no elicitation).
`fill_form(submit=True)` now actually submits behind that gate where it only
asked before. Gate record `gates/phase6.json`; script `scripts/gate_phase6.py`.

- `save_workflow` from the audit log, `run_workflow` with mandatory `dry_run`
  reporting before execution, `list_workflows`.
- **GATE (seven parts, all GREEN):** a recorded FIVE-step flow (the opening
  navigate plus four actions) replays green after a full page reload and
  after a cosmetic DOM change (and the replayed click really fires); the dry
  run names EXACTLY the broken steps after a structural change (the name
  field and the submit button lose their identity) and a real run refuses
  OUTRIGHT rather than half-running; a gated submit step fails closed with no
  human and COMPLETES on an explicit accept through the elicitation seam; the
  replayable set excludes `evaluate_script`; every gate session closes with
  zero owned browser PID surviving. **MET.** The original phase definition
  follows.

The original phase definition:

- `save_workflow` from the audit log, `run_workflow` with mandatory `dry_run`
  reporting before execution, `list_workflows`.
- **GATE:** a recorded five-step flow on the fixture site replays green after a
  full page reload and after a cosmetic DOM change, and the dry run correctly
  predicts which anchors will fail after a structural change.

### Phase 7: Tiered loading, wired conformantly

- Launch-time packs, `KS4WEB_MODE`, `--packs`, `--read-only`.
- `_meta` hints: `alwaysLoad` on the lite core, `searchHint` on the long tail,
  `readOnlyHint: true` on every read tool.
- Description budget enforcement against the 2,048-character client truncation.
- **GATE (REVISED 2026-09-05 by the soft-budget ruling, DESIGN 2.1):**
  `measure_surface` reports the HONEST numbers and they are published as
  measured; the 1,500-token lite figure, the 250-token schema ceiling, and
  the 4,000-token full surface are ADVISORY references, never a reason to
  delete useful docstring information. What stays red-gateable: the
  2,048-character client truncation (information loss), and the
  **discoverability round**: fresh agents given tasks requiring each pack must
  correctly name the pack and the launch flag they need, unprompted, from a lite
  session, and must not attempt a workaround (lite carries no degraded stand-in,
  by rule). Any discoverability failure is a red gate and a docstring or
  refusal-message fix, not a waiver.

### Phase 8: Adversarial rounds (RED GATES, plural)

**The law of this family: every adversarial round finds bugs.** The Word rounds
found 6, 7, 11, 7, and then 57 in a single day. Budget for findings; a round
that finds nothing means the round was too gentle.

Three rounds, run through the raw stdio transport, not through a friendly
client.

- **Round A, transport and grammar.** Schema fuzzing, location-object abuse
  (every selector with every wrong type, two selectors at once, zero selectors),
  handle abuse (page handle from a closed page, session handle from a dead
  session, refs from another page), multiplex discriminator abuse (wrong
  action/target combos must map to `BAD_PARAMS`), batch behavior under stale
  anchors and mid-batch kill **tested against the semantics DESIGN 3.5 defines**
  (resolve all, re-check each target immediately before its own execution,
  outcome (c) reported per item, outcome (d) or (e) stops the batch with
  completed items left completed and the remainder reported `not_attempted`),
  the pre-ladder input cases from the same section (unknown ref, ref belonging to
  another page handle, gone-marked ref, URL changed with cross-page rebinding
  off, pending modal), and a check that no raw exception string ever reaches a
  caller. Browser batches are not atomic and the round tests the stated behavior
  rather than an assumed rollback.
- **Round B, safety.** The full adversarial fixture, run by an agent that is
  TOLD to try to get a credential into the transcript, to get an ungated
  destructive action through, to exceed a budget, and to make a hidden
  instruction land. Every success is a red finding.
- **Round C, robustness and token discipline.** The pathological fixture at
  full size, plus a long session: 200 page reads across mixed sites with the
  token bill tracked per call, verifying the cap holds on every single one and
  that no read ever exceeds budget regardless of page.
- **GATE:** all findings fixed with regression tests, all three rounds re-run
  green, reports saved to `internal notes/` with DTG names.

### Phase 9: Docs, proof, and ship

- README, docs site, and `llms.txt` built from measured counts only. **The
  Known Limitations page is a first-class deliverable** (workstream W2), not a
  footnote.
- The published benchmark: harness, pinned versions, page set, tokenizer
  convention, and results, all reproducible by a stranger.
- `mcp-name` marker in README line 1 and a sub-100-char `server.json`
  description BEFORE the first release.
- Ship order, exact, from the family runbook: version stamping across all three
  files, merge to main with CI green on both platforms, `gh release create`,
  PyPI via trusted publishing, mcpb pack and release upload, registry publish
  **immediately after device auth** (the JWT dies in under an hour, confirmed
  twice in the family), Glama, landing page.
- **GATE:** a count-grep proves no stale figure survives anywhere public; the
  em-dash grep is clean across every language; the author READOUT of all public
  copy before the commit (standing rule); and the beta-worthiness gate below.

---

## 4. The beta-worthiness gate

The family's ship precondition, adapted to a domain with no file to corrupt.
Beta labels are allowed on incomplete FEATURES. They are never allowed on the
safety core.

1. **The token claim is PROVEN, not asserted.** Phase 2's gate is green and the
   published benchmark reproduces it from a clean checkout on a second machine.
   If the headline number cannot be reproduced by someone else, it does not get
   published.
2. **The safety core is PROVEN, not asserted.** Phase 3's gate and Round B are
   green. Read-only mode genuinely registers no mutating tools. Redaction is
   enforced at the serializer and demonstrated against a deliberately leaky tool.
   Gates re-validate at execution. **This gate cannot be waived or beta-labeled.**
3. **The hygiene gate is green.** Zero orphans after 50 cycles including SIGKILL.
   This is a correctness claim the category currently fails, and claiming it
   falsely would be worse than not claiming it.
4. **No false successes** on the pathological fixture (Phase 4 gate).
5. **The Known Limitations page is complete and honest**, naming every
   `LANE_UNSUPPORTED` gap, every completeness case, and everything in DESIGN
   Section 6 that we chose not to build. No incumbent ships one of these, which
   is exactly why it is a credibility asset rather than a liability.
6. **Honest beta labels ARE allowed** for: Lane C in general, WebKit support
   beyond "it launches," schema-directed extraction coverage, `describe`
   selector reliability, and workflow replay. Each says plainly what it does and
   does not do.
7. **Default is HOLD.** Absent green gates and an author readout, it does not
   ship. No warranty or guarantee language anywhere, in any beta framing.

---

## 5. The distribution and proof workstream (parallel, first-class)

The market caution, stated once more because it is the thing most likely to make
this build a nice repo nobody uses: **the best-maintained Puppeteer-family
browser MCP server in existence has 48 stars.** Charlotte, which independently
arrived at nearly this design and publishes benchmark multipliers, has 178 after
seven months. Building the right thing is necessary and demonstrably not
sufficient. So proof and distribution run in parallel from Phase 0, not as a
Phase 9 afterthought.

**W1: The benchmark harness.** Built in Phase 2, run at every phase gate
thereafter, and published at ship. Pinned incumbent versions, the frozen page
set, the documented tokenizer convention, raw results committed. **The tokenizer
convention is `tiktoken` on `o200k_base`, named in every published number**, the
same estimator the budget meter enforces against (DESIGN 3.4), which is what
makes "never exceeds its budget" a checkable claim rather than a slogan; conflict
record #4 is the reason, since the same content measured four ways produced
4,024, 4,637, 11,717, and 14,400. The harness reports wall-clock alongside tokens
from the first run, so the latency budget is tracked with the same discipline as
the token bill. The category is
full of vendor multipliers with no methodology; the differentiator is that a
third party can re-run ours and get the same answer. This is also an internal
regression detector: a phase that quietly inflates the page bill gets caught the
same day.

**The published table includes the rows KS4Web loses**, per DESIGN 12 rule 2:
httpbin and example.com, where the 570-token scaffold floor makes the
projection larger than an incumbent read of a trivial page, with the reason
stated inline. A benchmark showing only wins is the thing this workstream exists
to be distinguishable from. **The `o200k_base` re-measurement is DONE** (2026-09-05,
`gates/corpus_a.json`), which discharges the "no S1 number is publishable as-is"
item: every figure in DESIGN 3.2 is now the shipped projector on frozen pages
under the named encoder. The finding the harness inherits is that the encoder
was not the variable. `o200k_base` and `cl100k_base` differ by 0.3 to 1.0
percent on projection payloads, so the incumbent baselines do not need
re-counting before publication and the benchmark says so.

**W2: The Known Limitations page**, written continuously as the build discovers
limits rather than reconstructed at the end. Every `LANE_UNSUPPORTED` entry, the
BiDi hole list, the closed-shadow-root case, the virtualized-list case, the
"we do not build an agent loop and here is why" case. Nobody in this category
ships one. It is a credibility asset with the security-literate audience most
likely to evaluate a browser MCP.

**W3: Positioning copy, drafted early and reviewed by the author.** Lead with
QUALITY (context rot, fewer compaction events, fewer wrong clicks, more turns
before degradation), because the pure cost pitch bounces off subscription users
who say "more tokens is free for me." Rate limits are the bridge argument that
reaches subscribers. Cost is secondary. Safety copy follows the Section 5
grammar without exception.

**Binding since S1: the one-read claim always carries its companion clause.**
Cheap first read PLUS cheap targeted follow-up, with the limit stated in the
same breath rather than in a footnote: an arbitrary in-prose link on a long
article is not one-readable at any budget, and `find_elements` retrieves it for
tens of tokens. "One read and you can act on anything" is banned copy. The pair
is still the category win, since the incumbents' equivalent is a 156,347-token
dump followed by the same cheap find, and stating the limit is what makes the
rest of the claim survive a reader who tests it.

**W4: Registry and packaging presence**, prepared in parallel and executed in
Phase 9: PyPI, mcpb, mcp-publisher, Glama claim file, the `mcp-name` marker in
README line one before the first release. The KS4PPT v1.0.1 lesson does not get
relearned.

**W5: The launch artifact, not the launch post.** A Show HN is the author's
move, on the author's account. The build's job is to have the reproducible
benchmark, the limitations page, and a two-minute demo ready when the author
decides. Note that a Show HN whose entire premise was escaping this exact
problem already drew 189 points, so the audience is demonstrably there and
already annoyed.

**W6: The cross-family proof.** Record the demo no standalone browser server can
run: navigate to a report, download the spreadsheet, put the tables into Excel
through KS4XL. That is the one differentiator a single-purpose competitor cannot
copy, and it needs to exist as a thirty-second video rather than a bullet point.

**W7: The dogfood log.** The author runs KS4Web daily from Phase 4 on Lane B,
and on Lane C once S5 and S6 report. Field bugs outrank new features, which is
the rule that made the Word server good. The log is also the honest source for
W2.

---

## 6. The v1 scope fence

Explicitly IN v1: Lane A on Chromium and Firefox; Lane B on Chrome, Edge, and
`moz-firefox` (contingent on S3); the lite core; the `extract`, `capture`,
`network`, `storage`, `files`, and `diagnostics` packs; all eight safety
pillars; the audit trail; launch-time tiering; the published benchmark; the
Known Limitations page.

Explicitly OUT of v1, with the reason:

| Out | Reason |
|---|---|
| Browser extension (MV3 plus native messaging) | DESIGN 6.2. Second toolchain, store review, permanent infobar, Chrome-only. |
| Anti-detection, stealth, CAPTCHA solving, proxies | DESIGN 6.1. Permanent, not deferred. |
| Raw CDP as an engine | DESIGN 6.3. `CDPSession` escape hatch only. |
| Lighthouse, performance traces, heap snapshots | DESIGN 6.4. Occupied by a funded Chrome team. |
| An agent loop | DESIGN 6.5. Structurally unavailable to an MCP server. |
| Cloud or hosted operation | Local-first is the position. |
| WebKit beyond "it launches and reads" | Real support is a v1.1 promise, not a v1 claim. |
| i18n of the docs site | The family does this at scale; it waits for a shipped v1. |
| WebSocket and SSE frame capture | Verified unserved across 21 servers. v1.1 slate, not v1 scope creep. |
| Service worker and web worker inspection | Same. |
| Visual regression diffing | Same. |
| Video recording | Same, and it is heavy. |
| Code mode / programmatic execution surface | Cannot be inherited from the platform (MCP tools are excluded from programmatic tool calling), so building it is a real project. v1.1 at the earliest. |
| Server-side secrets file (execution-time credential substitution) | DESIGN 5.3 names it as the second sanctioned credential route and NO mechanism backs it in this build; the 2026-09-05 field test caught the `CREDENTIAL_REFUSED` message promising it, and the message was corrected to the routes that exist (headed handoff, plus auth-state reuse via the storage pack). Build the substitution mechanism before the error copy names it again. |
| Lane C Firefox, if S5 fails | Moves to v1.1; Lane C ships Chrome-only. |
| Lane C at all, if S5 and S9 both disappoint | Lanes A and B alone are still a complete product. |
| ~~`workflows` pack, if Phase 6 runs long~~ | **RESOLVED: workflows MAKE v1.** The standing ruling under author delegation kept the pack in v1 (Q10: positioning-load-bearing, the capability-matrix row and the eval-alternative safety story depend on it), and **Phase 6 ran on 2026-09-05 with its gate GREEN, seven parts.** `save_workflow` / `run_workflow` / `list_workflows` are real tools over durable anchors with a mandatory dry run, replaying through the whole policy ladder and never requiring `evaluate_script`. The Section 12 matrix "Audit trail and replay: yes" now stands on shipped code. |

**Anti-scope-creep rule for this build:** every "while we are in here" addition
must name which v1 gate it serves. If it serves none, it goes on the v1.1 list
in the BUILD_LOG and nowhere else.

---

## 7. Effort estimate and critical path

Family reference points: KS4PPT went research-to-shipped in one overnight with
heavy reuse; Word v2 was two overnight-scale sessions of mostly-mechanical
re-fronting; KS4XL was estimated at three to four.

**KS4Web: four to five overnight-scale sessions**, and the honest reason is that
the reuse share is the lowest in the family. The safety scaffold, envelope,
packs, measurement, and gate discipline port; the entire engine, the projection,
the anchor system, and the policy layer are new.

| Block | Scale |
|---|---|
| Spikes S1 through S10 | ~one session. Gates the freeze. Cannot be skipped or shortened. |
| Phase 0 (scaffold and ports) | ~half an evening |
| Phase 1 (engine core and hygiene) | ~half a session; the hygiene gate is fiddly and Windows-specific |
| Phase 2 (projection and anchors) | **~one and a half sessions; the keystone and the single biggest block** |
| Phase 3 (policy layer) | ~one session |
| Phase 4 (actions and verified outcomes) | ~half a session |
| Phase 5 (packs, parallel waves) | ~one overnight, mostly mechanical once Phases 2 and 3 exist |
| Phase 6 (workflows) | ~2 to 3 hours |
| Phase 7 (tiered loading) | ~2 to 3 hours |
| Phase 8 (three adversarial rounds plus fixes) | ~one session; history says findings WILL come |
| Phase 9 (docs, benchmark publication, ship) | ~half a session plus author readout and device auth |

**Critical path:** S1 (the thesis proof) into S2 (durability) freezes the
architecture; projection plus anchors gate everything that reads; the policy
layer gates everything that acts; server integration is a single-file bottleneck
with one integrator; the three adversarial rounds gate the ship. The Phase 5
waves parallelize. The spikes, the keystone, the integrator, and the gates do
not.

**Riskiest parts, named:**

1. **The projection hitting 5,000 tokens while staying actionable.** This is the
   product. S1 exists to fail fast if it is not achievable.
2. **False rebinds in the anchor system.** A silent wrong click is worse than
   every failure mode this design otherwise prevents, and it is the one bug class
   that would be genuinely dangerous rather than merely annoying.
3. **Windows process hygiene.** Three defenses, timing-dependent, and the exact
   row where the most-installed competitor is currently open and unfixed. Hard to
   get right, easy to regress, and highly visible when it breaks.
4. **The `moz-firefox` dependency.** Undocumented channel on an experimental
   backend. It could move under us, and we accept that knowingly for a lane that
   is flag-gated rather than default.
5. **The BiDi hole list becoming a support burden.** Every gap is a bug report
   from someone who did not read the limitations page. `manage_session
   (capabilities)` and loud `LANE_UNSUPPORTED` refusals are the mitigation, and
   they only work if they are exhaustive.

---

## 8. Standing rules binding this build

- No em dashes anywhere public, in any language. No warranty or guarantee
  language. Nothing personal. Nominative trademark use only, no logos or trade
  dress, non-affiliation disclaimer. "Plus the kitchen sink" framing.
- **Safety copy grammar, absolute:** reduces / gates / flags / logs / requires
  confirmation for. Never prevents, secure, safe, or protected as unqualified
  verbs. **Never frame a feature by the attack it stops.** Never publish a
  percentage without its methodology, test set, date, and model. Never describe
  the audit trail as forensic or as evidence. Never claim the lethal trifecta is
  solved, or imply the user is relieved of responsibility, or claim compliance
  with any site's terms on the user's behalf.
- Conservative refusals over guesses. Nothing ships red. The safety gate and the
  token gate cannot be waived.
- **Never touch the author's real browser profile**, in any phase, by any agent,
  for any reason. Seeded copies only, and seeding is a manual author-run
  operation. Agent rounds never attach to a live daily browser.
- Never kill a browser process KS4Web did not spawn. The owned-PID journal is
  authoritative. Never sweep by process name.
- Counts and token figures in public copy come from scripts, never hand-math or
  memory.
- Author readout before the public-copy commit and before ship. Device-auth steps
  name the author explicitly.
- Rate limits checked before every agent batch. BUILD_LOG entry plus memory
  checkpoint after every phase. No phase begins until the prior one is saved.
- The five family discoverability rules bind, as adapted in DESIGN 7.4 (refusals
  name the pack and the LAUNCH FLAG, since there is no runtime enable call). The
  Phase 7 discoverability round is a red gate.
- **The model-downgrade halt applies:** before every phase start and agent batch,
  check the session model. An undirected change means checkpoint everything and
  halt until the author rules.
