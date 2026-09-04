# PLAN.md: KitchenSink4Web v1 build plan, spikes, gates, and the proof workstream

**Status:** INTERNAL planning document. Not shipped, not public copy. Written
against `DESIGN.md`, the four KS4Web research artifacts, the banked token
measurement, and the shipped family build plans (KS4PPT v1, KS4XL v1). Read
DESIGN.md first; this plan is how it gets built, not what it is.

**The external success metric:** be the browser MCP that a working
professional can point at an unfamiliar page and read for under five thousand
tokens, act on with references that still work three turns later, run in
read-only mode when the task does not need to touch anything, and audit
afterward. Plus a benchmark a stranger can re-run.

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
| View / batch layer STRUCTURE (anchored projection, validate every anchor before executing any, one lock and one commit per batch) | pptx `ops/view.py`, `ops/batch.py`; xlsx `get_grid_view` | The PATTERN ports; the internals are entirely new. |
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

---

## 2. The spike phase

**Nothing is built until the spikes report.** The architecture freezes only
after the spike gate. Every spike has an explicit kill or fallback criterion so
it ends in a decision rather than a vibe.

Spikes are ordered by information value per hour, with one deliberate change
from the engine research's ordering: **S1 (the projection proof) comes first**,
ahead of the engine spikes, because it tests the product thesis and every engine
spike tests a delivery mechanism for it. If S1 fails, the engine questions stop
mattering.

### S1: The projection proof (THE spike, run first)

Build a throwaway projector against the frozen benchmark set and measure it.
Not production code, not integrated, no MCP server. Playwright script, page in,
projection out, token count printed.

- **GATE:** the Treaty of Versailles article projects to **under 5,000 tokens**
  at `detail=standard`, the GDP table page to under 3,000 for structure plus
  the first row page, and the httpbin form to under 300.
- **THE HARDER GATE:** a fresh agent given only the projection can complete
  "find and click the link to the Fourteen Points" without asking for a second
  full read. A cheap read that is not actionable is not the product. Run this as
  a blind trial with an agent that has not seen the page.
- **KILL CRITERION:** if the token target is reachable only by dropping the
  affordance set below actionable, or if actionability requires more than 5,000
  tokens on an ordinary article, **the flagship claim is wrong** and the
  positioning changes before a line of production code is written. Escalate to
  the author immediately; do not proceed to S2.
- Output: the measured degradation ladder, the real ratio of interactive to
  total nodes on each fixture, and the first honest version of the
  completeness-block field list.

### S2: Anchor durability

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

### S3: `moz-firefox` reality check

Launch stock Firefox via `channel="moz-firefox"` with a throwaway `user_data_dir`.

- **GATE:** it launches, navigates, clicks, fills a form, screenshots, and reads
  text. `about:support` confirms it is the installed build and not a Playwright
  download.
- **KILL CRITERION:** if this fails on Windows with the installed Firefox, the
  whole Lane B Firefox dogfood premise collapses and Lane B Firefox becomes
  bundled-only. S5 (Lane C Firefox) proceeds independently, since it uses a
  different mechanism entirely.

### S4: BiDi gap inventory

Draft the tool surface first (rough is fine), then run every candidate operation
on `moz-firefox` and record supported / degraded / unsupported. Probe the known
bad set specifically: response-body capture, download events, HTTP auth,
`set_extra_http_headers` on redirects, locale and timezone emulation, and
clicking inside a CSS-transformed element.

- **GATE:** is the unsupported set small enough to declare as documented
  limitations, or does it gut the surface?
- Output: **the seed of the `manage_session(capabilities)` truth table and every
  `LANE_UNSUPPORTED` message.** This spike literally produces a product feature.
- **FALLBACK:** Firefox lanes demote to read-mostly and Chromium becomes the
  only full-surface engine, documented honestly rather than papered over.

### S5: Firefox live attach over raw BiDi

Start Firefox manually with `--remote-debugging-port=9222` on the real profile,
connect a bare WebSocket, and drive `session.new`, `browsingContext.getTree`,
`script.evaluate`, `browsingContext.captureScreenshot`, `input.performActions`.

- **GATE:** a read-mostly Lane C toolset is achievable in a few hundred lines.
- **Why it runs early even though Lane C may ship later:** this is the one
  capability no competing MCP server has, because Playwright cannot attach to an
  existing BiDi session and Chrome forbids the equivalent. Knowing whether it is
  real changes the positioning.
- **FALLBACK:** Lane C Firefox moves to v1.1 and Lane C ships Chrome-only, which
  is the weaker story (DESIGN 4.4).

### S6: Seeded-profile fidelity

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

### S7: Async plumbing and process hygiene under FastMCP

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

### S8: MCP conformance and client-behavior probe

Every one of these is a binary fact the design depends on, and all are cheap to
check against the installed client.

- Launch-time pack selection produces an identical `tools/list` on every
  connection.
- `anthropic/alwaysLoad` and `anthropic/searchHint` behave as documented in the
  binary read, on the installed Claude Code version.
- Elicitation is advertised; sampling is not; MRTR `InputRequiredResult` round-trips.
- The 25,000-token result cap and the 3,000-token subagent cap, confirmed
  empirically.
- `readOnlyHint: true` actually unlocks concurrent execution.
- Tool descriptions truncate at 2,048 characters.
- **GATE:** every assumption in DESIGN Section 7 is confirmed or the design
  adapts before Phase 7 builds on it.

### S9: Chrome Lane B and C, and the App-Bound Encryption question

`channel="chrome"` with a KS4Web profile directory, then `connect_over_cdp`
against a Chrome started with a non-default `--user-data-dir`.

- **GATE:** confirm firsthand that Chrome 136+ ignores the debugging flag on the
  default data directory. Do not take the blog post's word for the exact failure
  mode.
- **Open empirical question this resolves:** does a Chrome `User Data` directory
  copied to a non-default path still decrypt its cookies on the same machine and
  user account? App-Bound Encryption makes this genuinely uncertain and it
  determines whether Chrome seeded profiles are useful at all.

### S10: Weight and install measurement

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

Spike outputs are saved as permanent artifacts to `Draft/Working Files/Agent
Results/` with DTG names, per house rule.

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

### Phase 2: Projection and anchors (the keystone)

The two modules everything else is downstream of. Built together because deltas
require sticky refs and sticky refs are only useful because reads are cheap.

- `projection/`: readability gate, landmark segmenter, affordance ranker,
  content digest, form and table inventories, DOM projection with attribute
  allowlist, hidden-content normalizer, completeness accounting, degradation
  ladder, budget meter.
- `anchors/`: fingerprints, sticky element map, rebind ladder, delta engine.
- `get_page_view`, `find_elements`, `get_text` land here as the first three
  tools.
- **GATE, four parts, all required:**
  1. **The measured token bill meets every target in DESIGN 3.2** on the frozen
     benchmark set. Reported by the harness, not by hand.
  2. **Refs are sticky** across re-reads on every fixture, and **zero false
     rebinds** on the pathological fixture.
  3. **The completeness block is accurate**, verified by construction: the
     virtualized list, the closed shadow roots, the cross-origin iframe, and the
     canvas region in fixture B must each be REPORTED, and a deliberately
     injected hidden element must be counted rather than missed or silently
     included.
  4. **The degradation ladder never truncates mid-structure**, verified by
     forcing every rung on the 50,000-node fixture.

### Phase 3: The policy layer (built BEFORE the action tools, deliberately)

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

### Phase 4: Action tools and verified outcomes

- `click`, `type_text`, `fill_form`, `press_keys`, `scroll`, `wait_for`,
  `navigate`, `manage_tabs`.
- Verified outcomes on every action (DESIGN 5.7).
- Trusted input dispatch through the driver, never JS synthesis.
- **GATE:** on the pathological fixture, **no false successes.** The
  `event.isTrusted` React control, the overlay-intercepted click, the
  `<div onclick>` button, the moving target, and the portal dropdown each
  produce either a correct action with a verified effect or an honest refusal
  with a named recovery. Nothing returns bare `ok` with `effect: "none-observed"`
  unreported.
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

### Phase 6: Workflows and replay

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
- **GATE:** `measure_surface` reports **lite under 1,500 tokens** and the
  largest single schema **under 250**; full surface under 4,000. Plus the
  **discoverability round**: fresh agents given tasks requiring each pack must
  correctly name the pack and the launch flag they need, unprompted, from a lite
  session, and must not attempt a workaround (lite carries no degraded stand-in,
  by rule). Any failure is a red gate and a docstring or refusal-message fix, not
  a waiver.

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
  action/target combos must map to `BAD_PARAMS`), `apply`-style batch atomicity
  under stale anchors and mid-batch kill, and a check that no raw exception
  string ever reaches a caller.
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
set, the documented tokenizer convention, raw results committed. The category is
full of vendor multipliers with no methodology; the differentiator is that a
third party can re-run ours and get the same answer. This is also an internal
regression detector: a phase that quietly inflates the page bill gets caught the
same day.

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
| Lane C Firefox, if S5 fails | Moves to v1.1; Lane C ships Chrome-only. |
| Lane C at all, if S5 and S9 both disappoint | Lanes A and B alone are still a complete product. |
| `workflows` pack, if Phase 6 runs long | Drops to v1.1 without touching anything else, because nothing depends on it. |

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
