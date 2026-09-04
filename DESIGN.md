# DESIGN.md: KitchenSink4Web (KS4Web) v1, the settled design

**Status:** INTERNAL planning document. Not shipped, not public copy. Written
for a senior review pass, so it favors completeness and explicit reasoning over
polish. Every non-obvious choice states the evidence behind it and the
alternative it rejected.

**Produced:** 2026-09-04 KST, against four research artifacts:

- `20260904_2113_ks4web_capability_demand.md` (capability landscape, demand
  mining, landmines, unserved rows, community sentiment, the commercial and
  licensing column). Cited below as **DEMAND**.
- `20260904_2114_ks4web_incumbent_study.md` (architecture study of
  playwright-mcp, chrome-devtools-mcp, claude-in-chrome, browser-use, the
  alternative-representation field, platform constraints, the five openings).
  Cited as **INCUMBENT**.
- `20260904_2134_ks4web_engine_analysis.md` (engine decision, three lanes,
  profile safety, spike list). Cited as **ENGINE**.
- `20260904_2134_ks4web_safety_landscape.md` (threat landscape, incumbent
  safety coverage, the eight candidate pillars, marketing cautions). Cited as
  **SAFETY**.
- Plus the banked measurement `20260904_1918_browser_mcp_token_measurement.md`,
  which supplies every numeric target in Section 3. Cited as **MEASURED**.

Family patterns are inherited, not re-derived: the response envelope, the
closed error vocabulary, the location object, the naming grammar, tiered
loading, the honest-refusal discipline, and the gate-per-phase build style all
come from KitchenSink4Word v2, KitchenSink4PPT, and KitchenSink4XL. Where
KS4Web departs from a settled family pattern, the departure is named and
justified (Sections 7 and 9 carry the two real ones).

KS4Web is the fourth product in the family. Storefront department: **GARDEN**,
"browsing the great outdoors." Final aisle copy happens at site build; design
docs use Garden. Glazing was considered and rejected by the author.

---

## 1. Positioning

### 1.1 The one-sentence thesis

**Every browser MCP server makes you pay six figures of tokens to look at a
page before you can touch it, and KS4Web is the one that reads a page for
under five thousand tokens and hands back references you can act on, plus a
targeted follow-up that costs tens of tokens when the thing you want was not
in the first read.**

**The companion clause is not decoration and it is required everywhere the
claim appears.** The Treaty of Versailles article projects to 3,683 tokens on
the frozen corpus, and S1 put six blind agents against eleven projections of it
and its neighbours; the read carried
navigation, forms, controls, sections, and tables well enough for eleven of
seventeen tasks to be actioned from the projection alone. It did not carry an
arbitrary in-prose link, and no budget makes it. That page holds 2,858 in-prose
links, so a first read that contained the one the task named would be a
transcript, not an orientation. The honest pitch is therefore **cheap first
read plus cheap targeted follow-up** (`get_page_view` then `find_elements`),
and it is still a category win, because the incumbents' equivalent is a
156,347-token dump followed by the same cheap find. Never write "one read and
you can act on anything."

### 1.2 The measured gap

MEASURED, on this machine, 2026-09-04: one accessibility-tree snapshot of an
ordinary Wikipedia article costs **156,347 tokens** through playwright-mcp
0.0.80 and **177,168 tokens** through chrome-devtools-mcp 1.8.0 (448,705 with
`verbose: true`). That is 78 to 89 percent of a 200,000-token window spent on
one page, before the agent does anything with it.

The tool-schema bill, which is where the Word work trained the family to look
first, is the small problem here: 4,637 and 6,460 tokens respectively, once per
session. The recurring page-read cost is **25 to 40 times larger than the
entire tool surface**, and it repeats on every page.

Both vendors already fixed the smaller half. A click or a type now costs 9 to
56 tokens on either server (chrome-devtools-mcp PR #821 made post-action
snapshots opt-in; playwright-mcp defers the navigate-time snapshot to a file
and returns a link). What neither fixed is that **refs only come from the
snapshot**, so the cheap action is gated behind the expensive read.

### 1.3 Why the gap is durable

INCUMBENT establishes that this is a stated philosophy, not a backlog item.
playwright-mcp's maintainer, verbatim across three years:

> "We believe that the tokens will get cheaper faster than we can elaborate a
> meaningful pagination solution." (2025-05, #395)

> "We should not make the tool smart, that's LLM's business. For example, we
> should not be using heuristics to abbreviate or paginate the snapshot, we
> should provide the snapshot and LLM should summarize it." (2025-09, #889;
> that comment carries 25 thumbs-down and no thumbs-up)

> "We are optimizing for a 1M context window size at this point." (2026-08,
> playwright #42077)

The stance hardened as the complaint intensified, and the repo has since
stopped accepting issues entirely (#1664 is a pinned redirect). A gap defended
by a published philosophy does not close when the incumbent ships next
quarter's patch.

The direct rebuttal to "tokens will get cheaper" is not ours, it is the
category's, and it is the strongest single argument available (DEMAND, Part
Five): *"computer use cost doesn't close as models get better because the
bottleneck isn't vision quality, it's the number of screenshots required by the
interface. Better models = cheaper screenshots, not fewer of them."* The
interface determines the step count. No model improvement changes that.

### 1.4 The four things the thesis alone does not win

DEMAND section 6 is the most important strategic input in the whole research
record, and it is a caution rather than an encouragement. `TickTockBent/
charlotte` independently arrived at nearly this exact design (token-efficient
structured snapshots, loadable tool profiles, spill-to-disk, a snapshot
differ), publishes 10x to 140x multipliers, and has **178 stars against
playwright-mcp's 36,788** seven months in. The most capable maintained
Puppeteer-family server in existence has **48 stars**. Building the right thing
is necessary and demonstrably not sufficient.

So the thesis is the entry ticket and these four are the product:

1. **Completeness.** 43 tools is a good browser server, not a kitchen sink.
   The rows Charlotte and both first-party servers leave thin are auth and
   session persistence, downloads, network mocking, storage with redaction,
   PDF, iframes, and structured table and list extraction.
2. **Safety as a shipped layer.** Four pillars are unserved by every incumbent
   surveyed (SAFETY section 6). Nobody local-first is doing this.
3. **Family integration.** A downloaded spreadsheet that lands in KS4XL, a
   downloaded report that lands in KS4Word. No standalone browser server can
   copy that, structurally.
4. **Published, reproducible proof.** Charlotte publishes multipliers, so the
   category now expects a number. Ours has to be reproducible by a third party
   against pinned versions, which is the part vendor benchmarks never are.

### 1.5 How to sell it, because the obvious pitch half-misses

DEMAND, Part Five, the most commercially important line in the research:

> "I'm paying a fixed amount on Claude and other agents, so 'more tokens' is
> 'free' for me."

A pure cost pitch bounces off subscription users, who are a large share of the
audience. The pitch that reaches both audiences is **quality**: fewer tokens
means less context rot, fewer auto-compaction events that drop the user's
original instructions, fewer wrong clicks, and more turns before the session
degrades. Cost is the secondary argument. Rate limits are the bridge argument
that does reach subscribers ("even simple browser automation tasks fully
consume claude desktop's 5 hour limit").

---

## 2. Tool surface sketch by pack

Naming follows the family verb grammar, with one sanctioned extension
(Section 8.2): the browser action verbs `navigate`, `click`, `type`, `press`,
`hover`, `scroll`, `wait`, `select`, `upload`, `download` join the fixed table,
because forcing "click a button" into `set_` or `apply_` produces names no
agent guesses. Every other tool is `verb_object` from the inherited table, and
`manage_` remains the sanctioned action-parameter pattern for object
lifecycles.

Counts below are PLANNING ESTIMATES. Every published figure comes from
`scripts/measure_surface.py` and an operations counter, never hand-math (house
rule, inherited).

### 2.1 The lite core (always on, target under 1,500 tokens)

MEASURED sets the target: under 1,500 tokens against Playwright's 4,637 and
chrome-devtools' 6,460, a 3.1x and 4.3x beat. At the family's observed
docstring density that buys roughly 10 to 14 tools, and the largest single
schema must stay under 250 tokens (the incumbents' worst are 413 and 459).

| # | Tool | What it does |
|---|---|---|
| 1 | `get_page_view` | THE flagship read. Projection + detail + budget + cursor + delta. Section 3. |
| 2 | `find_elements` | Query-first read: text, role plus name, natural-language description, CSS, XPath. Returns actionable refs and a completeness note. |
| 3 | `get_text` | Prose projection (Readability-shaped), paginated by `start_index`. |
| 4 | `navigate` | goto / back / forward / reload / stop / wait_for_load. Returns identity, status, robots advisory, and a bot-wall or auth-wall verdict. |
| 5 | `click` | ref or anchor primary, coordinate fallback. Returns a VERIFIED outcome (Section 5.7). |
| 6 | `type_text` | Into a ref. clear-first, press-enter. Refuses secret fields (Section 5.3). |
| 7 | `fill_form` | Batch field set in one call, per-item validation, reads the form state back. The largest single token saving in the interaction category. |
| 8 | `press_keys` | Key chords with repeat. |
| 9 | `scroll` | By amount, to element, to end, inner container, and the incremental "next chunk" that keeps position across calls. |
| 10 | `wait_for` | Text appear/disappear, element state, URL, request/response, JS predicate, download. Real timeout, diagnostic failure message. |
| 11 | `manage_tabs` | list / open / select / close / focused, popup capture. Mints and returns the page handles the 2026-07-28 spec requires (Section 7.1). |
| 12 | `manage_session` | open / close / status / **capabilities** / budget counters. The capabilities action is the `LANE_UNSUPPORTED` truth table (Section 4.5). |
| 13 | `get_audit` | The action log, paginated. Always on because it is the brand (Section 5.6). |
| 14 | `get_workflows` | House pattern: recipes, pack-naming, continuation protocols. |

`request_handoff` (pause and hand the headed window to the human for a login,
MFA, or bot wall) is a lite candidate; it may fold into `manage_session` as an
action if the measured bill runs hot.

**Two lite-membership decisions worth a senior look.**

`take_screenshot` is deliberately NOT in lite. The whole thesis is that
structured reads beat pixels (the Reflex benchmark: 53 steps and 550,976 tokens
for a vision agent against 8 steps and 12,151 for structured access on the same
task), and putting a screenshot in the default surface invites the expensive
default back in through the front door. Family discoverability rule 1 forbids a
degraded stand-in in lite, so lite carries no pixel path at all, and rule 2
makes the refusal the signpost: when `get_page_view` meets a canvas-rendered
region it says so and names the `capture` pack and the exact launch flag. This
is an author question (Section 11, Q2).

`emulate` is a lite candidate on TOKEN grounds rather than capability grounds.
Playwright's own agent skill recommends emulating a mobile device because
"mobile pages are usually lighter, so snapshots are smaller and cheaper." That
makes device emulation a cost lever, not a testing nicety. Whether it earns the
budget is a measurement decision, not a design one.

### 2.2 The packs

Cost-aware pack rule, inherited from KS4XL and binding here: a pack justifies
on both grouping and token cost. Sub-1.5k packs merge into a neighbor unless
they are environment-gated or genuinely rare-use.

| Pack | Contents | Why it exists |
|---|---|---|
| **extract** | `get_table` (row-range paging, rowspan/colspan aware, div-tables detected and named as such), `get_list` (repeated records), `get_links`, `get_metadata` (OpenGraph, JSON-LD, schema.org, feeds), `extract_fields` (schema-directed, deterministic matching where possible, honest about unfilled fields), `export_data` (CSV/JSON, and the file handoff to KS4XL) | DEMAND: deterministic non-LLM table-to-JSON extraction is served by **zero** of 21 servers inspected. This is where the token thesis produces its largest demonstrable multiplier, and it is the family bridge. |
| **capture** | `take_screenshot` (viewport / full / element, format and quality and max-dimension caps, media-type correctness enforced, secret masking, hard byte cap with spill-to-file), `export_pdf`, `save_page` (MHTML) | Both incumbents have a documented failure where a malformed screenshot causes a permanent API 400 that poisons the whole session (playwright-mcp #1211, 30 comments; browser-use #4742). #1211 is a PNG returned under an `image/jpeg` media type. That is a one-line fix that prevents unrecoverable session corruption. |
| **network** | `list_requests` (paginated, filtered, ad and analytics domains blocked by default), `get_request` (budgeted body, spill to file), `export_har`, `set_routing` (block, mock, throttle, offline, headers) | HAR export is strategically important, not a nicety. The pattern sophisticated practitioners already use is: capture the traffic, have the model write an OpenAPI spec, then call the API directly. A browser server that helps an agent **graduate off the browser** for repeat tasks is aligned with where the users already are, and nobody is selling that. |
| **diagnostics** | `list_console` (errors-only default, level filter, paginated, deduplicated), `get_page_errors` (uncaught exceptions with stacks), `evaluate_script` | Console logging shipped as an improvement became a token regression at the incumbent, by the maintainer's own admission; chrome-devtools-mcp #171 reports `list_console_messages` repeating each line four times (40,000 tokens against 8,000). Errors-only with an explicit widen is the correct default. `evaluate_script` is named for what it is and gated (Section 6.8). |
| **storage** | `manage_cookies`, `manage_storage` (local, session, IndexedDB), `save_auth_state` / `load_auth_state` | Values masked by default. `save_auth_state` writes credentials to a FILE so auth can be reused without ever passing through the model's context. Playwright ships the mechanism; nobody frames it as the safety feature it is. |
| **files** | `download` (trigger, wait, list, read, scoped directory), `upload_file` (file inputs, multi-file, and synthetic-DataTransfer dropzones) | DEMAND: downloads are literally unserved by all four surveyed servers, chronically broken in browser-use (#499, #729, #1951 saving as a bare UUID with no extension, #5132 completion callback never firing) and open with zero comments since 2025-10 in chrome-devtools-mcp (#2397, #284). It is also the only row a single-purpose competitor structurally cannot match, because a downloaded xlsx is what KS4XL consumes. |
| **workflows** | `save_workflow`, `run_workflow` (deterministic replay over durable anchors, `dry_run` first), `list_workflows` | playwright-mcp closed the macro request by pointing users at `browser_run_code_unsafe`, and the filer's rebuttal is the sharpest statement in the corpus: *"the only way to reuse a multi-step flow is to keep an arbitrary-code-execution tool enabled. Deployments that disable it for safety lose workflow reuse entirely."* Named replayable workflows as safe first-class primitives close that fork. |

Frames and shadow DOM get **no pack and no tools**. They are location-object
features (Section 6.3) plus a line in every completeness block. That is the
right shape because payment fields, consent managers, and embedded editors live
in iframes, so frame addressing is not an advanced capability, it is checkout.

Rough totals: **40 to 44 tools, roughly 110 to 130 operations.** Notably leaner
than Skyvern's 116 verified tool registrations, so the completeness claim rests
on the operations count and the capability matrix, never on tool count. Family
rule, inherited: the headline metric is OPERATIONS, and the low tool count is
framed as engineering, never apologized for.

---

## 3. THE CHEAP FIRST READ (the flagship)

This section gets the most depth because it is the product.

### 3.1 What is actually unserved

Be precise about the claim, because the incumbents have partially moved and
overclaiming here would be caught immediately by anyone who reads the source.

Every incumbent has a cheap SECOND read. playwright-mcp's `browser_find` is
well built and its own description says it "is cheaper than capturing the whole
snapshot when you only need to locate an element and its ref." Claude in
Chrome's `find` takes natural language. Both share one precondition: **the
model must already know what string to search for.** chrome-devtools-mcp's
`take_snapshot` has no scope, depth, or size control at all, in a codebase that
paginates everything else.

So the universal opening move on an unfamiliar page is still the full dump.
**Nobody has a cheap first read.** That is the unserved row, and it is narrow
enough to be true.

**And the two halves are one product, which S1 made concrete.** The precondition
the incumbents cannot meet is knowing what string to search for; the projection's
job is to make the model know the string, and the blind trials showed it doing
exactly that. On the one task the projection could not answer directly (the
Fourteen Points link, buried among 2,858 in-prose links), the agent named
`find_elements(page="p1", query="Fourteen Points")` unprompted and correctly
priced it against the alternatives. That is the shape of the claim: the first
read is what makes the second read cheap and targeted rather than a guess.
Selling the first read alone overstates it, and selling the pair understates
nothing.

Two rows genuinely contested rather than unserved, and the design must not
claim them: snapshot deltas and spill-to-disk are both shipped by Charlotte
(`src/state/differ.ts`, `output_file`), and the delta idea is independently
endorsed by a chrome-devtools-mcp maintainer in #835. KS4Web builds both
because they are correct, not because they are unclaimed.

### 3.2 The targets, from the banked measurement

| Read | Incumbents | KS4Web target | Measured, o200k, frozen corpus A | Multiple |
|---|---|---|---|---|
| Tool-schema bill (lite) | 4,637 / 6,460 | **under 1,500** | **2,720** (Phase 0, unchanged) | 1.7x / 2.4x |
| Full-surface ceiling | n/a | under 4,000 | not yet built | undercuts the incumbent DEFAULT |
| Largest single schema | 413 / 459 | under 250 | **148** (`get_page_view`) | |
| Article page (Wikipedia, Treaty of Versailles) | 156,347 / 177,168 | **under 5,000, regardless of page size** | **3,683 at rung 3**; the undegraded read is 4,965 | 42x / 48x at the delivered rung, 31x / 36x undegraded |
| Data-table page (GDP nominal) | 66,146 / 64,635 | under 3,000 for the page structure, **the first row page priced separately as its own `get_table` call** | **3,166 structure. FAILS the target by 166** | 21x |
| Form page (httpbin) | 440 / 314 | **under 900**, and hold it on a real app form where incumbents balloon with shell chrome | **809** | a deliberate loss, 1.8x the incumbent |
| Minimal page (example.com) | 105 / 90 | the scaffold floor, measured rather than targeted | **570** | a deliberate loss, 5.4x the incumbent |

**Every number in that column is the SHIPPED projector against FROZEN pages
under `o200k_base`, measured 2026-09-05** (`gates/corpus_a.json`,
`corpus/a/MANIFEST.json`). It replaces S1's column, which was a prototype
against live pages under `cl100k_base`. Both halves of that sentence moved at
once, so the paragraphs below separate them rather than letting one hide inside
the other.

**The tokenizer was not the story, and that is worth stating because the design
expected it to be.** Conflict record #4 shows tokenizers disagreeing by roughly
3x on this class of content, so the re-measurement reported both encodings on
the same payloads. The gap is **0.3 to 1.0 percent, and `o200k_base` is the
cheaper of the two on every page**: minus 2 tokens on example.com, minus 3 on
httpbin, minus 3 on the GDP table, minus 36 on Versailles. A projection payload
is structured English prose with short identifier tokens, which is the content
class the two encoders agree on; the 3x disagreement lives in raw markup and
minified script, which the projection never emits. **The practical consequence
is that the incumbent baselines do not need re-measuring under `o200k_base`
before the comparison is publishable**, since a sub-1-percent encoder gap
cannot move a 20x to 48x multiple. Say the encoder in the benchmark and say
that it was checked against the other one.

**The scaffold floor is 570 tokens, up from the 390 to 404 this section used to
publish, and it is a property of the design rather than a defect to optimize
away.** example.com is thirteen nodes and one link, so the whole 570 is what
the blocks cost when the page contributes almost nothing. The increase is the
Phase 1 rebuild rather than the encoder: the completeness block alone is
fourteen lines on that page, because it names every class of thing the read did
not see (iframes, open and closed shadow roots, virtualization, below-the-fold
extent, stripped hidden content, canvas, auth state, unlisted affordances by
class, unlisted form fields, headings, tables, unexpanded regions, dropped
regions, blocks omitted entirely, name quality) and it names them on a page
that has none of them. **That is the design working as argued**, since the
whole point of the block is that "I did not look" and "there is nothing there"
are different answers, and a block that only appears when it has bad news
cannot make that distinction. **Any target below the floor is unreachable by
construction**, which is why example.com and httpbin are published as losses
with the reason attached rather than as rows to chase. Two numbers this table
used to carry were retired at S1 for exactly that reason, and the frozen
re-measurement has something to add to each.

The httpbin "under 300" was the first. Three hundred tokens does not buy a
completeness block and a continuation protocol, so the old target was asking the
design to drop the two blocks that make it honest in order to win a row against
a 440-token incumbent read of a trivial page. The target is now under 900, **the
frozen measurement is 809, and the margin is 91 tokens.** The row is documented
as a **deliberate loss on tiny pages**: the projection is 1.8x the incumbent
read on a 46-node page, which is the correct trade, because the same scaffold is
what caps a 574,200-token page at 3,683. Say that plainly in the published
benchmark rather than hiding the row. The 91-token margin is thin enough to be
a watch item rather than a comfort, and it is the row to re-run after any change
to the completeness block.

The GDP "under 3,000 for structure plus first row page" was the second. S1
measured the structure alone at 2,854, leaving 146 tokens for a row page, which
is not a row page. The two reads are now priced separately, which is also the
truer shape: the structure comes from `get_page_view` and the rows come from
`get_table` with row-range paging, and conflating them into one number was
comparing a KS4Web pair against a single incumbent dump. **The frozen
measurement is 3,166 and the target is 3,000, so this row FAILS by 166 tokens,
5.5 percent.** It is recorded as a failure rather than quietly restated,
because the target was set at S1 from a 2,854 measurement and the shipped
projector is a rebuild rather than a regression of that prototype. The
arithmetic the ruling needs: the page carries 300 collected affordances against
5,644 nodes, the read lands on rung 1 with the ladder never engaging, and
lowering the number means either dropping the affordance quota on a
table-of-links page or moving the target to something the structure read
actually costs. **Author call, and the design does not make it here.**

**The Versailles row no longer holds with 25 percent of margin, and the reason
is a ladder cliff rather than a size problem.** The frozen page's undegraded
read is 4,965 against an effective budget of 4,500 (5,000 less the 10 percent
drift margin), rung 2 is 4,589, and rung 3 is 3,683. So the delivered read is
rung 3 and the ladder ENGAGES on the flagship page at the default budget, where
S1 reported it never engaging on any of eleven pages. Two things follow. The
guarantee holds: the read is under budget, nothing was truncated, and the
completeness block states the 22 regions that collapsed. The margin claim does
not: the flagship's full read is 465 tokens over the effective budget, and the
step that fits is 906 tokens below the one that does not, **which is a 20
percent drop where a 3 percent one would have fit.** That is S1's
finer-rungs finding recurring at the top of the ladder after the rungs were
already refined from five to eight, so it is a real Phase 2 item and not a
restatement: **the rungs between full and collapsed are still too coarse on a
long article, and the fix is a partial-collapse step that sheds the lowest
priority regions rather than all of them.**

**The live drift check makes the same point from the other side, and it is the
reason PLAN 1.3 asks for one.** Run against the live pages immediately after
the freeze, three of the four sit within 2 percent of their frozen twins
(example.com minus 1.9 percent, httpbin minus 1.1, the GDP table minus 1.8),
which is the answer a freeze wants: the frozen copy still tells the truth about
the real page. Versailles reads **plus 15.3 percent**, 4,246 live against 3,683
frozen, and the underlying content differs by 1.5 percent (10,572 nodes against
10,737). The whole gap is the cliff: the live page's rung 2 lands at 4,246,
which is under the 4,500 effective budget, and the frozen page's rung 2 lands at
4,589, which is not. **A 1.5 percent content difference produced a 15 percent
token difference**, so the published number for a page sitting near a rung
boundary is discontinuous in page size. That is not a defect in the freeze and
it is not a defect in the drift check. It is the strongest available argument
for the finer step above, and it is a caveat the published benchmark states
rather than discovers when somebody reproduces it.

MEASURED is explicit that a 3-5x beat is the wrong ambition here: 156,347
divided by 5 is still 31,269 tokens, which still ruins a session after six
pages. The honest target is a hard cap with paging, stated as a property rather
than a hope: **a page view never exceeds its budget regardless of page size.**

One platform constraint shapes the default. A **roughly 3,000-token cap on tool
results inside subagents** is reported in claude-code #75267, filed against
v2.1.202, quoting the exact error text and reporting that `MAX_MCP_OUTPUT_TOKENS`
raises the cap. **The attribution matters: this is a corroborated FIELD REPORT,
not a binary-verified constant.** No 3,000 constant exists in the installed
client binary anywhere near that code path, and the consistent explanation is
that the value arrives through the same remote feature gate that carries the
25,000-token result limit, which means it can move without a client release. The
research record carried this under a binary-verified header and the design
repeated it; the correct standing is "field-reported, apparently
remote-delivered." Since "delegate the page read to a subagent" is the exact
mitigation playwright-mcp's maintainer recommends, the default 5,000-token budget
would still fail inside the very workaround people use, so `get_page_view` takes
`budget_tokens`, documents 2,500 as the subagent-safe setting, and
`get_workflows` ships that recipe. The recipe survives, but 2,500 tracks a
**movable limit**, which makes S8's empirical confirmation against the installed
client the load-bearing check rather than any binary read, and makes the number a
thing to re-measure rather than a constant to trust. **S1 confirmed the recipe
is real:** at `budget_tokens=2500` every one of eleven pages landed under budget
and none was mutilated, with Versailles degrading to rung 4 at 2,184 and most
pages never leaving rung 1.

### 3.3 What a page view returns

`get_page_view` returns an ORIENTATION, not a transcript. Eight blocks, built
in priority order, measured as they are built.

**1. Identity.** Final URL after redirects, title, HTTP status, load state,
engine lane, page handle, read token (for deltas), and a timestamp.

**2. Page shape.** Landmark regions (header, nav, main, aside, footer, dialog,
form, plus unlabeled major containers) each carrying a ref, a one-line label,
counts of interactive elements and text blocks and images, and **an estimated
token cost to expand.** The regions are a menu with prices, so the model can
budget instead of guess. Nothing in the field does this, and the prices are
therefore the design's genuine novelty, which is why Section 3.3a makes them a
correctness requirement rather than a nicety.

**3. Affordances: quota-based by class, never a single proximity score.** The
interactive surface as `ref | role | accessible name | href-or-target | state`,
selected by **per-class quotas with guaranteed floors**, then ranked within each
class. It is not one ranked list capped at N.

S1 forced this, and the motivating case is worth stating exactly because it is
the failure this rule exists to prevent. On `github.com/microsoft/playwright`,
the prototype's single score (in-viewport +40, main-or-dialog +30, size,
semantic weight) surfaced dozens of truncated commit-message links from the file
listing and **buried all thirteen tabs of the repository navigation bar**,
including Issues. A blind agent asked to open the repository's issues could not
name a call. It was not a budget failure: the projection used 2,238 of 5,000
tokens, the entire tab bar would have cost roughly 130, and 2,762 tokens of
headroom went unused. **The ranker threw away the answer while under budget.**
Proximity scoring on a 51-screen article does the same thing in the other
direction, where "in-viewport" means the lead paragraph and the top forty
affordances come back as citation markers (`[n. 1]`, `[ii]`, `[4]`).

The classes and their quotas:

| Class | Quota |
|---|---|
| Site and page navigation: nav landmarks, tab bars, menubars, breadcrumbs | **Guaranteed floor, filled before any other class.** This is what an agent asks for most and it is small. |
| Form controls, scoped to controls INSIDE a form | **Complete whenever the form fits the budget, never sampled.** A half-listed form is not a form. |
| Primary actions: submit controls, buttons in `main` or a dialog, anything with `aria-expanded` or `aria-haspopup` | High quota. |
| In-prose links inside a readable region | **Quota of zero.** |

The zero quota is the load-bearing one. On Versailles it removes roughly 2,700
of 2,858 affordances and costs nothing, because no agent was ever going to find
its link inside a forty-item sample of 2,858. Those links belong to the content
digest, which names the sections they live in, and to `find_elements`, which
retrieves one by name for tens of tokens. The completeness block states the
suppressed count and the class it belongs to, so the absence is reported rather
than implied.

**The form-control scope is the second load-bearing one, and Phase 1 had to
narrow it during the build.** A control counts as a form control only when it
is inside a `<form>`. The first version classified by element type, so every
loose `<input>` on an app shell claimed the "complete, never sampled"
guarantee, and an app shell has search boxes, filter toggles, and inline
controls scattered outside any form element. The guarantee then applies to a
population it was never sized for and turns into the flood it was written to
prevent, which is the same failure as the ranker burying the tab bar, arriving
from the opposite direction. Loose controls are not dropped; they compete in
the primary-actions class on their merits like everything else, and they lose
only the exemption from sampling.

Two corollaries, both cheap and both answering a specific blind-trial failure:

- **Print the href path for links.** The prototype extracted `href` and never
  printed it, and a blind agent on CNN could not confirm that an affordance
  labeled "Business" went to a business section rather than opening a menu. The
  data was already in hand. Path only, not the full URL, when the origin matches
  the page.
- **Never collapse two elements onto one line without a distinguishing token.**
  S1 emitted `e13` and `e42` as two buttons both labeled "Search (x2)" in the
  same region, and `e216,e134 | link | "Apache-2.0 license" (x2)` out of numeric
  order, so the grouping was not even positional. Duplicate labels are
  disambiguated by the smallest sufficient discriminator: the containing region,
  the ordinal within it, the href path, or the nearest labelled ancestor. If no
  discriminator can be computed, the elements are listed separately rather than
  grouped.

The community measurement KS4Web is designing against is roughly 62 to 93
accessibility nodes per view of which about 9 are interactive. **S1 measured the
real range and the assumption holds only for app pages.** Interactive-to-total
node ratio across eleven pages: 2.0 percent to 28.3 percent, median 9.0 percent.
App shells and homepages sit at 8 to 15 percent as assumed; articles do not, and
Versailles is 26.6 percent precisely because its interactive elements are inline
citations. That single number is why quotas replaced a global cap: the class
that explodes on articles is the class with quota zero.

**4. Content digest.** For a readable page: a condensed lead plus the section
headings, each heading carrying a ref so the model can expand exactly one
section. For an app shell: the structural skeleton instead. The choice is made
by a cheap pre-check, generalizing Mozilla's `isProbablyReaderable(document)`
into a gate that selects between projections per page rather than committing to
one representation for a whole session.

**5. Forms inventory.** Each form as one line (ref, name or action, field
count), then the fields as `ref | label | type | required | value-state`. Values
of secret-typed fields are never present, not even redacted-in-place, and the
field is marked `secret: true` (Section 5.3).

**Select and combobox options are inlined under a size cap, and this is a known
open item rather than a settled mechanism.** S1 recorded the only failure in its
trial set that forced an EXPENSIVE second read, and it was this one: a blind
agent planning a fill-and-submit on GitHub's advanced search reached
`e17 | "Written in this language" | combobox` with no option values, wrote *"I
am guessing the option label is exactly `Python`... this is the single most
likely call to fail,"* and then priced its only recovery at roughly 4,757
tokens, more than 2.5x the entire first read, because the projection offered no
narrower call for one select's option list. **Options are cheap and their
absence is expensive**, so a `<select>` whose option list fits a per-element cap
(a small option count and a small token cost, both stated in the tool docstring)
has its options printed inline. Over the cap, the inventory prints the option
count and names the call that retrieves them. **TODO, Phase 2: set the cap from
measurement rather than taste**, and decide whether a dedicated narrow retrieval
call is warranted or whether `get_page_view(view="forms", location=...)` scoped
to the one control is already the right answer. Recorded as the known
forced-second-read case so the positioning does not quietly assume it away.

**6. Tables inventory.** Each table as `ref | caption | rows x cols | column
headers`. Never the cells. Cells come from `get_table` with row-range paging,
because a table is the one case where the user may genuinely want the data, so
the answer is pagination and a row count, not truncation.

**7. The completeness block.** This is the answer to landmine L3, confident
wrongness, and it is as important as the token number. Every projection reports
what it did NOT see and why:

- iframes not traversed, with counts split same-origin and cross-origin, each
  carrying a ref
- closed shadow roots present and unreachable, counted and named honestly
  rather than silently omitted
- virtualized or infinite-scroll containers detected, with the DOM count and
  the claimed total where the page exposes one ("region r7 holds 20 rows of a
  list the page reports as ~5,000")
- content below the viewport, in screens
- hidden regions stripped, with the count and the reason class (Section 5.1)
- canvas-rendered regions with no text projection, naming the `capture` pack
- **budget accounting**: tokens used against budget, which degradation rung
  the projection landed on, and which regions were not expanded
- **auth state** (signed-in / signed-out / unknown), and how it was determined.
  Arguably block 1, kept here because it is a completeness fact. A blind agent
  on the GitHub repo page reverse-engineered it from an affordance label to
  correctly predict that a star click would fail, which is the right answer
  reached the wrong way.
- **unlisted affordances**, as a count and a group count, broken out by the
  class quota that suppressed them
- **omitted form fields and omitted forms**
- **omitted tables and omitted headings**
- **regions listed but not expanded**, stated distinctly from regions dropped
  by the degradation ladder, because they are different facts
- **blocks omitted entirely** because the page has none of that thing
- **name-quality flag** when any accessible name was truncated or could not be
  computed (Section 3.7)

The two-layer phrasing on shadow roots is kept verbatim, on evidence: a blind
agent singled out `shadow roots: 0 open (traversed=no), 0 closed (unreachable by
any tool)` as the most useful line in the whole document, because it separates
"I did not look" from "no one can look" where most tools collapse both into a
confident zero. **Every completeness field carries that distinction where it
applies.**

**The accounting rule, and it is the important part of this block.** S1's
completeness block printed `0 regions not expanded` while thirty regions carried
expand costs and none had been expanded. Three independent blind agents caught
it, and one of them put the general defect precisely: *"The completeness report
is honest about the DOM boundaries it could not cross and silent about the
content it chose not to print."* The cause was structural rather than a typo. The
block recomputed its own numbers after the fact, so it reported on the
degradation ladder (which had not engaged) instead of on the projection (which
had omitted most of the page).

**So the completeness block does not compute anything. It renders the ledger the
budget meter already kept.** The meter measures as it builds (3.4), which means
it necessarily knows, per unit, whether that unit was printed, summarized,
suppressed by a class quota, dropped by a rung, or never reached. That ledger IS
the accounting, and the completeness block is a view over it. A number that
appears in the block and was not produced by the same pass that enforced the
budget is a defect by construction, and the Phase 2 gate tests it as one: a
projection is generated, the ledger is compared against ground truth from the
fixture, and any figure the block can produce independently of the meter fails
the gate.

Two consequences fall out. The block **separates the two facts the old budget
line conflated**: tokens used against budget is one statement, content
deliberately not printed is another, and printing the first while implying the
second is what produced "0 regions not expanded" on a page with thirty priced
regions. And **section numbering is dynamic, or every block is always emitted
with an explicit "none."** S1 hardcoded the numbering while omitting empty
blocks, so a page with no forms and no tables jumped from section 4 to section 7,
and a blind agent noted that two sections had vanished with no disclosure
"including in the section that exists specifically to disclose what the read did
not cover." Either fix is acceptable; silently renumbering is not.

**8. The continuation protocol, taught inside the payload.** The reference MCP
fetch server's idiom, stolen outright because it is the best idea in the
extractor field:

> `<error>Content truncated. Call the fetch tool with a start_index of
> {next_start} to get more content.</error>`

The tool teaches the model its own continuation protocol in the result. No
extra schema, no documentation dependency. KS4Web's version names the exact
next call for each unexpanded region, each unread table, each untraversed
frame.

**Next calls are ranked by expected value, never by size.** S1 put
`expand r5 (main, ~73,716 tok)` at the top of its recommended-call list on
Versailles. That region overlapped a dozen others and was simultaneously the
most expensive and least useful call available on the page. Ranking by cost, in
either direction, is what produced it. The ranking is by what the call is likely
to answer, and an overlapping parent region is demoted below its own children
rather than promoted above them.

### 3.3a The cost-estimation contract

Every price the projection prints must be a real price. This is stated as its
own contract because "regions are a menu with prices" is the design's
differentiator, and S1 caught three separate lies in one prototype, each of which
a blind agent noticed unprompted. A wrong price is worse than no price: it does
not merely fail to help, it routes the agent to the wrong call while looking
authoritative.

**The three caught lies, and the rule each one produces.**

1. **Per-heading costs were `~10 tok` on almost every heading.** A blind agent
   wrote: *"Every single content heading is priced identically... Read quickly,
   that says a section costs ten tokens, when in fact the 'Reactions' region
   alone is ~6,399 tok to expand. The one number an agent most needs, the price
   of reading a named section, is the number the projection does not give."* The
   cause was a `nextElementSibling` walk from the heading to the next heading,
   which returns almost nothing on any site that wraps sections in containers,
   which is most sites. **RULE: a section's cost is computed over its true
   section container, from the heading to the next heading of the same or higher
   level, spanning wrapper elements.** If the true container cannot be
   determined, the projection prints no price for that heading and says so,
   rather than printing a number derived from a walk that found nothing.

2. **The `main` region was priced as the sum of every other region.** It
   overlapped its own children, so the most expensive call on the page also
   looked like the most complete one. **RULE: overlapping regions are priced NET
   of their children.** A parent's advertised cost is what expanding it adds
   beyond expanding its children, and where a parent is genuinely just a
   container, its price says so.

3. **`0 regions not expanded` was printed while thirty regions carried expand
   costs.** Covered above: the completeness block renders the budget meter's
   ledger and computes nothing of its own.

**The general rule these three collapse into, and it is the one to enforce
mechanically: a printed price and an enforced budget come from the same
arithmetic, in the same pass, over the same units.** The budget meter estimates
with `tiktoken` on `o200k_base` (3.4) as it builds. Any cost the projection
advertises is the meter's own estimate for the unit that call would produce, not
a separate heuristic that happens to live nearby. Two estimators mean two
answers, and the one the user sees would be the one nothing tested.

**Phase 2 tests this by construction, not by inspection.** For each priced unit
on the fixture set, the harness issues the exact call the projection advertised,
measures the result under the same estimator, and compares. A price that is wrong
by more than a stated tolerance is a red gate, and a price with no corresponding
executable call is a red gate too, because an unpriceable call should print no
price rather than a plausible one.

### 3.4 The projection parameter, and the degradation ladder

Projection is a first-class PARAMETER, not a tool choice. The four
representations (accessibility tree, sanitized DOM, markdown prose, pixels) are
four projections of one page, each right for a different question, and every
existing server picks one and makes the others awkward. Firecrawl's `formats`
array is the proven interface for letting the caller declare the shape of the
answer and pay only for that shape.

```
get_page_view(
  page=<handle>,           # explicit handle, per spec 2026-07-28
  view="auto"|"outline"|"read"|"act"|"forms"|"tables"|"links"|"dom",
  detail="lite"|"standard"|"full",
  location=<location object>,   # scope to a region, form, table, frame
  budget_tokens=5000,
  cursor=<opaque>,         # continuation, in ARGUMENTS not protocol pagination
  since=<read token>,      # delta mode
  include_hidden=false
)
```

`view="dom"` is the selective DOM projection playwright-mcp declined in #103
(closed **not planned**, and two third-party servers were advertised in that
thread specifically to fill the hole). Users were explicit about what the
accessibility tree drops: *"Aria snapshot is not enough for `data-testid` for
example."* KS4Web's DOM projection carries a configurable attribute allowlist
(id, data-testid, name, type, href, aria-*, role) and strips the rest. One
measured detail worth carrying: removing `[cursor=pointer]` alone was **12
percent** of an incumbent payload.

**The degradation ladder** enforces the cap without the failure mode the
incumbent maintainer correctly identified. His objection is right and the design
must respect it: a hard character cap on a tree serialization truncates
mid-structure and can silently remove the one node the model needed, converting
a loud overflow into a quiet wrong answer. A commenter put it exactly:
*"a hard cut can also lop off the exact element you needed, so you trade an
overflow for a silent miss."* His second correct objection is that an
accessibility tree with the text stripped out is close to information-free,
because on that tree the accessible name IS most of the signal.

So KS4Web never truncates and never ships a text-free summary. It degrades by
**dropping whole units in reverse priority order** and reporting exactly what it
dropped:

1. Full regions expanded, full affordance list, full digest.
2. Lower-priority regions collapse to one summary line each (ref, label,
   counts, expand cost).
3. The affordance list caps and states the omitted count.
4. The content digest shortens to headings only.
5. Landmark counts plus forms plus tables plus the completeness block, which is
   the floor and is never dropped.

Rung 5 on a pathological page is still a usable orientation and is still under
budget, and the floor is bounded by construction rather than by hope. The forms
inventory is the reason this needs saying: enumerating every field of every form
is unbounded, and a real airline booking page or an enterprise settings screen
with several hundred fields would push the floor past any budget. **Rung 5
therefore caps its own inventories: forms collapse to one line each (ref, name,
field count) when the field-level listing would breach budget, and tables were
never more than one line each. With inventories capped, the floor is bounded and
a page view never refuses; the full field listing is one
`get_page_view(view="forms")` away and the floor says so.**

**S1 confirmed the floor problem empirically and added two more ladder
requirements.** The prototype's uncapped floor refused Versailles at a 1,500
budget (floor 1,629) and refused eight of eleven pages at 900, which is exactly
the unbounded-floor case the capped inventories above now close. Two further
defects the prototype exposed, both stated as requirements rather than notes:

- **The ladder is monotonic as EXPOSED, which is a weaker requirement than
  every rung being smaller than the one above it, and the weaker requirement is
  the correct one.** On httpbin the prototype got BIGGER at rung 4 (743 to 793
  tokens) because the digest switched from a short `lead:` line to a heading
  list. A rung the caller can be handed that costs more than a rung above it is
  a defect, and the harness asserts monotonicity per page across every rung.

  **Phase 1 found that non-increasing caps do not deliver the property.** The
  caps are non-increasing by construction and a step still grew: dropping a
  unit occasionally costs more than it saves, because the completeness block
  then has to account for what went, and on the `names` fixture rung 7 came
  back 37 tokens larger than rung 6 for exactly that reason. Reasoning about
  the caps is reasoning about the inputs; the property is about the outputs. So
  the mechanism is **never choose a dominated rung**: a rung whose rendered
  cost is at or above the cost of any rung above it is DOMINATED and the
  selector skips it, which makes the ladder the caller sees monotonic whether
  or not every individual step was. The other half of that fix was a real
  defect the domination check exposed rather than papered over, a suppression
  line that explained the in-prose rule even on pages where nothing in prose
  had been suppressed, so the check earns its place twice.
- **The rungs are finer than five and less correlated.** Measured steps on
  Versailles bought 20 percent, then 9 percent, then 17 percent, so a 2,500
  budget skipped the projection from 3,711 straight to 2,182, dropping 22
  regions and the entire lead paragraph when a smaller step would have fit.
  Degradation is chosen to land just under budget, not to jump to the first rung
  that fits.
- **The floor's shape is content-aware.** The prototype's floor kept every table
  row-count and every form field while dropping the digest, which on an article
  is backwards. The floor keeps what the page is FOR: the digest survives on a
  readable page, the form inventory survives on a form page.

Not a defect and worth banking: **at the 5,000-token default the ladder never
engaged on any of eleven pages spanning four orders of magnitude of raw size.**
The ladder is the guarantee, not the normal path.

**The budget is enforced against ESTIMATED tokens, and the estimator is named
rather than assumed.** "A page view never exceeds its budget" is a hard-cap
property, and conflict record #4 already shows tokenizers disagreeing by roughly
3x on this exact class of content, so an unnamed estimator would make the
property unfalsifiable. The budget meter estimates with `tiktoken` on
`o200k_base`, holds a stated safety margin (10 percent of budget) in reserve
against client-side tokenizer drift, and reports both the estimate and the
margin in the completeness block's budget accounting. The published benchmark
reproduces the same estimator, so the measured numbers and the enforced cap are
the same arithmetic.

Where the payload genuinely must be large (a full table export, a response
body, a DOM dump), the answer is spill-to-file with a queryable handle. This is
what a practitioner built his own wrapper to do, and what the best-articulated
complaint in the entire corpus asked for: *"If it returned a link to a temp
file, then the AI could grep it intelligently."*

### 3.5 The anchor scheme: how refs stay durable across re-reads

This is the second half of the flagship, and it is what converts a cheap read
into a cheap SESSION.

**Prior art, studied.** chrome-devtools-mcp is the exception that proves the
problem is solvable. Its identity key is `` `${node.loaderId}_${backendNodeId}`
``, cached in a `uniqueBackendNodeIdToMcpId` map across snapshots; the display
id is `` `${snapshotId}_${idCounter}` ``. Existing nodes reuse their id when the
backend node id matches a previous snapshot, so **a uid for an unchanged
element survives re-snapshotting**. The id LOOKS ephemeral and is not.
Combined with `includeSnapshot: false`, that is precisely what makes read-once-
act-many cheap there, and it is the single design in the field most worth
copying.

Two reasons KS4Web cannot copy it directly. `backendNodeId` is a CDP concept,
and KS4Web runs three lanes including WebDriver BiDi where it does not exist.
And a backend node id does not survive a React re-render that replaces the node
or a navigation that rebuilds the page, which is the failure users actually
report.

**The design: two addresses per element.**

1. **`ref`** (`e12`) is a short, cheap, turn-local handle. It is what appears in
   payloads and what the model passes back. Refs are unique across the session,
   not per page, so a bare `e12` is never ambiguous, and the envelope always
   states which page it belongs to.

2. **`anchor`** is a durable, content-derived descriptor that can be
   re-resolved from nothing: role, accessible name, a scoping path (nearest
   landmark, then nearest labelled ancestor, then ordinal among same-role
   siblings), plus stable attributes when present (id, `data-testid`, name), plus
   the origin and path pattern it was minted on. **Anchors are stored
   server-side keyed by ref and normally never enter the model's context.** The
   model pays for `e12`; KS4Web keeps the durability.

The emerging community answer to stale refs is "content-derived hashes over
role, accessible name, and ancestry rather than positional refs, and nobody has
shipped it at scale." That is exactly this, and shipping it is the point.

**Stickiness across re-reads.** The element map is keyed by the anchor
fingerprint, not by the snapshot. On a re-read, an element whose fingerprint
matches an existing entry **keeps its ref**. `e12` on read one is still `e12` on
read three if it is still the same element. New elements get new refs. Removed
elements keep their entry marked gone, so a later error can say what `e12` used
to be rather than just that it is missing.

That property is also what makes deltas expressible. `get_page_view(since=...)`
returns only what changed: new refs, gone refs, changed names and states, and a
count of stable regions. DEMAND calls deltas "the number one unmet ask in the
whole corpus," confirmed across six-plus independent threads, with every major
server re-sending the entire page every step. Deltas are impossible without
sticky refs, which is why the two designs are one design.

**Resolution at action time: the rebind ladder.** Every action tool resolves a
ref through this ladder before it touches anything.

**Entry conditions, checked before the ladder runs.** The five outcomes below are
exhaustive for *resolving a known ref on the current page*, and they say nothing
about how a call gets to the ladder in the first place. These cases are decided
first, in this order, and none of them enters the fuzzy tier:

| Input case | Outcome |
|---|---|
| A pending modal or dialog blocks interaction | `MODAL_BLOCKED` before any resolution is attempted, naming the dialog and the call that dismisses it |
| Ref was never minted in this session (model typo, or a ref quoted from another session or a saved workflow) | `NOT_FOUND`, stating the mint rule (refs are minted only by a read in this session) and naming the read that mints one |
| Ref exists but belongs to a different page handle than the one passed | `BAD_PARAMS`, naming both handles, never silently retargeting |
| Ref's entry is marked gone | Skip to (b) and re-resolve the stored anchor, carrying the gone record into any resulting message so the error can say what `e12` used to be |
| Page URL changed since the ref was minted and `allow_cross_page_rebind=false` | `STALE_ANCHOR` directly, with no fuzzy tier, because a fuzzy match on a different URL IS a cross-page rebind under another name |

- **a.** Ref found, handle still attached, fingerprint still matches. Proceed.
- **b.** Handle detached or fingerprint changed. Re-resolve the stored anchor:
  exact role plus name within the original landmark, then role plus name
  anywhere, then name-only fuzzy.
- **c.** Exactly one match. Proceed, and report `rebound: true` in the envelope
  with the old and new identity. **Never silently.** A rebind the transcript
  cannot see is the same disease as a silent false success.
- **d.** More than one match. Refuse `AMBIGUOUS_LOCATION` with every candidate
  and its unambiguous address. House rule, inherited and absolute: **no tool
  ever acts on first match.**
- **e.** Zero matches. Refuse `STALE_ANCHOR` naming what changed (URL changed,
  landmark gone, nearest misses by name distance) and the named recovery.

Cross-page rebinding is **off by default** (`allow_cross_page_rebind=false`).
Silently clicking a same-named button on a different page is exactly the
confused-deputy failure the whole safety layer exists to reduce.

**Batch actions have their own semantics, because per-action rules do not cover
them.** Typing into field one of a real form routinely re-renders its siblings
(country and state cascades, React controlled inputs), so a fingerprint change
partway through a batch is the ordinary case on SPA forms rather than an
adversarial corner, and browser actions cannot be rolled back once taken.
Validating every anchor at batch start, the pattern inherited from the siblings,
does not survive mutations the batch itself causes. So: **batch actions
(`fill_form`, and any future multi-target tool) resolve every ref before
executing any, then re-check each target's fingerprint immediately before its own
execution, because earlier items in the batch can legitimately re-render later
targets. On a mid-batch outcome (c), the rebind is reported per item. On a
mid-batch outcome (d) or (e), the batch STOPS: completed items stay completed
(browser actions do not roll back), the failing item is refused with its ladder
error, remaining items are reported `not_attempted`, and the envelope carries the
per-item outcome list plus the form state read-back. A batch never skips a failed
item and continues, and never retries silently.**

**The ladder and the confirmation gates compose, and it is worth stating because
it is load-bearing.** A target that rebinds between a gate's ASK and its EXECUTE
is caught by the gate's TOCTOU fingerprint re-validation and aborts with
`TARGET_CHANGED` rather than acting on the rebound element. Rebinding never
launders a stale confirmation.

**Where anchor ids surface.** Anchors are stored server-side and are not part of
any default payload, so the `{"anchor": "a3f9"}` selector in Section 9 is only
usable because two paths deliberately expose ids: `get_audit` records the anchor
id alongside every resolved action, and saved workflow files record anchors
rather than refs, since a replay in a later session has no refs to speak of. A
model that never reads an audit record or a workflow file never sees an anchor
id, which is the intended default.

**Delta state retention.** `since=<read token>` requires keeping the prior
projection state a token names. Read tokens are retained per page handle under a
bounded LRU (the most recent N reads per page, N small and stated in the tool
docstring), and they invalidate on navigation of that page, on close of the page
handle, and on session end. A token that has aged out or been invalidated is not
an error the model has to guess at: the delta call refuses with the reason and
falls back by naming the full read that re-establishes a baseline.

**Why this matters beyond convenience.** The measurement's structural insight is
that actions are already cheap (9 to 56 tokens) and refs are the toll gate. If
refs are durable, one read pays for an entire multi-step interaction. That is
the same lever Stagehand's `observe()` pulls, where an observed action replays
through `act()` with "no LLM call, no snapshot, no DOM-settle wait," which is
the single biggest cost lever in the field. Stagehand is an SDK, not an MCP
server. No MCP server ships it.

**The rule that follows for every read tool.** Every read returns actionable
refs. A filtered view, a text extraction, a find result, a table read, and a
form dump all carry refs the action tools accept. **There is no operation whose
only purpose is to unlock other operations.** That single rule is the difference
between KS4Web's read layer and the incumbents'.

### 3.6 What the default read never does

- It never attaches a snapshot to a mutating action. chrome-devtools-mcp's
  `includeSnapshot: false` default is the correct inverse of playwright-mcp's
  unconditional `setIncludeSnapshot()`, and it costs nothing. This is the
  cheapest correct decision available in the entire design.
- It never returns unbounded output. Every read is budgeted, every overrun
  degrades and reports, and the caller opts into more. This is a property of the
  response framework, not a flag on individual tools, because the incumbent's own
  history proves per-tool discipline fails the moment someone adds a feature
  (console logging shipped as an improvement and became a 6x token regression).
- It never silently omits. Everything not returned is counted in the
  completeness block.

### 3.6a The projection's wall-clock cost, measured

Token-cheap and wall-clock-expensive is the same user pain by another route,
so the latency question was a real one rather than a note. It was measured in
the engine-spike round (E11, transferred from S1), against the unmodified S1
projector on Lane A headless Chromium, ten repetitions per fixture.

**The projection is not slow, and the normalizer is not the bill.** A
50,000-node page projects in **341 ms p95** in-page plus 1.7 ms of Python
assembly, an order of magnitude inside the "a few seconds" line the plan drew.
A 100,000-node page stays under 0.9 s. The Treaty of Versailles article, the
flagship fixture, projects in 241 ms p95.

The design's stated worry was the hidden-content normalizer, since white-on-white
contrast, off-screen position, and near-zero font size all imply per-node style
computation. **That worry is now retired with a number.** At 50,000 nodes the
full per-node computed-style sweep is 64 ms of a 288 ms extract, roughly 22
percent. Restricting it to interactive candidates would save about 39 ms, some
14 percent, in exchange for losing hidden-content detection on every
non-interactive node. That is a bad trade at any price and a very bad one at
14 percent. **The normalizer sweeps every node in Phase 2. It is not sampled,
not capped, and the completeness block therefore never has to report a
normalizer cap**, which removes a field the design was preparing to need.
Revisit only if a fixture beyond 100,000 nodes appears.

The remaining roughly 60 percent of extract time is the affordance,
accessible-name, and digest work plus the JSON hand-back. That is where any
future optimization aims, and it is worth knowing before Phase 2 starts
optimizing the wrong thing.

**The Phase 2 latency budget, set from measurement:** projection p95 at or
under **500 ms up to 50,000 nodes** and at or under **1.0 s up to 100,000
nodes**, with Python-side assembly at or under 10 ms. The prototype passes
both with margin, and so does the shipped projector: 417 ms p95 at 50,012
nodes and 676 ms at 100,012, with Python assembly at 5.9 ms.

**The hand-back is a term of its own, and on a wide page it is the dominant
one.** Phase 1 built the projector against a fixture carrying 5,000 headings
and found the round trip costing **604 ms against 245 ms of actual in-page
work**, which means more than half the wall clock was JSON crossing the driver
boundary rather than anything the walk did. The extractor was returning every
heading it found so the Python side could count them and then discard almost
all of them, and the transfer scaled with the page while the answer did not.
**The rule that follows is cap what you RETURN, tally what you COUNT.** The
in-page pass counts every unit it sees and hands back its tallies as integers
alongside a capped list of the units that will actually be rendered, so the
completeness block's suppression figures come from the extractor's own count
rather than from the length of the list in hand. No completeness figure was
lost to the cap, which is the test of whether the split was drawn in the right
place. This is a latency finding with a correctness edge: an implementation
that derives its "omitted 2,700" from a list it holds in memory has to hold
2,700 things to say the number, and one that carries the tally does not.

**Per-line token measurement has to be memoized, for a structural reason
rather than a performance one.** The budget line states the total of the
payload it sits inside, so the render is self-referential and resolves to a
fixpoint, which means most lines are measured at least twice. Memoizing the
line-level counts and using `encode_ordinary` took Python assembly from 14 ms
to under 6 ms. The estimator's BPE table is warmed when a browser starts, so
the one-off load never lands inside the first read a user waits on.

**One finding that reframes the whole latency story for users.** Cold
navigation with a `networkidle` settle cost 12.8 seconds on cnn.com and on
ant.design, against a roughly 90 ms projection on the same pages. **Page load
dominates wall-clock and KS4Web does not.** Any latency story this product
tells is therefore a story about load-state policy (what `wait_until` default
is right, and when `networkidle` is worth its cost), not about the projection.
Saying otherwise would be selling an optimization the user cannot feel.

### 3.7 Accessible names are computed, not scraped

**REQUIREMENT: KS4Web computes accessible names by the W3C accname algorithm,
or reads the driver's own computed names, and never falls back to
`textContent`.** This is stated as a requirement because S1 used `textContent`
on containers and the resulting failures were not cosmetic. An accessible name
is most of the signal in a structured page read, so a wrong name is a wrong
answer with a confident face on it.

**The case that names the rule.** On `github.com/microsoft/playwright`, the
prototype labeled the entire `main` region **`"Uh oh!"`**, a stray pickup from an
error-state element that never rendered. The page returned HTTP 200 and that
region demonstrably held the file listing, the README, and the sidebar. A blind
agent triaging by region label said it plainly: an agent reading that would
*"either panic or skip the only region that matters."* The single most valuable
region on the page was labeled as an error, from a name computation that was a
property access rather than an algorithm.

The same defect produced a family of failures across the trial set: `"General4"`
and `"Data Entry18"` where a heading was glued to its adjacent count badge, so a
search for the literal string "Data Display" would miss and a report of the
section title would be wrong; `"main179 Branches165 TagsGo to fileCode..."` as a
single affordance name; `"Components OverviewChangelogv6.6.2GeneralButtonFloat
ButtonIconTypographyLayout DividerFlexG"` as a menu name, an entire navigation
run together and then cut mid-word; and commit messages truncated inside an open
parenthesis.

Four sub-rules follow, all mechanical:

1. **Compute by accname, or use the driver's computed name.** Playwright exposes
   correct computed names and they are cheap. The in-house BiDi client for Lane C
   implements the algorithm or reports that it cannot, per lane, in
   `manage_session(capabilities)`.
2. **Separate inline text nodes with spaces** wherever a fallback is genuinely
   unavoidable, so a heading and its badge never fuse into one token.
3. **Truncate on word boundaries with an explicit ellipsis**, never mid-token.
   A name cut inside a word reads as a different string than the page contains,
   which is what breaks string matching downstream.
4. **Refuse to emit a CSS class as a stand-in name.** S1 printed
   `.mw-file-description` as an affordance name. The correct output is
   `(unnamed)` plus one stable attribute (id, `data-testid`, or role plus
   ordinal). Unnamed and honest beats named and wrong, and the completeness
   block's name-quality flag counts how often it happened.

5. **A region label requires the WHOLE ancestor chain up to the region to be
   visible, not just the labelling element itself.** This is the sub-rule that
   actually fixes the `"Uh oh!"` case, and Phase 1 discovered it by reproducing
   that exact failure while believing the rule above had already retired it.
   The obvious implementation takes the first heading in the region's subtree
   and checks that the heading is visible, which the GitHub error heading
   passes: it carries real text, it has no `hidden` attribute, and its own
   computed style says it renders. It never rendered because a wrapper several
   levels above it carried `display:none`, and visibility on the web is a
   property of a chain rather than of an element. So the label walk climbs from
   the candidate to the region boundary and rejects the candidate if any link
   in that chain is hidden. **The general lesson is worth more than the fix:**
   any per-element visibility test in the projection is answering a question
   about an element's ancestors, and one that stops at the element gives a
   confident wrong answer rather than a missing one.

**The digest gate needs the same treatment, and it is the same disease.** The
prototype's `lead:` field took the first `<p>` over 80 characters anywhere in the
document. On CNN that returned *"It looks like your browser doesn't support the
Digital Rights Management (DRM) system required to play this content..."*, so a
model trusting `lead:` as the top of the page would have reported a DRM failure
as CNN's headline. **The lead comes from the readable region only**, extracted
Readability-shaped rather than by document order, and if no readable region is
identified there is no `lead:` line at all.

The readability gate itself needs tuning against measurement rather than a
threshold picked in advance: S1's gate (`prose_chars > 1200` and at least four
paragraphs) gave CNN an article-shaped digest while reporting roughly 336
characters of prose across a twenty-section homepage, which means the gate and
the thing it gated disagreed inside one payload. Phase 2 sets the gate from the
frozen corpus, and the projection states which shape it chose and why.

---

## 4. Engine lanes and profile safety

### 4.1 One engine

**playwright-python, async API, as the single automation engine.** Apache-2.0,
one surface over Chromium, Firefox, and WebKit, and the de facto substrate the
rest of the ecosystem already builds on.

The async choice is forced, not preferred. FastMCP tool handlers run inside an
asyncio loop, and Playwright's sync API explicitly refuses to run inside a
running loop (the guard is in `playwright/sync_api/_context_manager.py`). The
sync API would only be usable by pushing every call into a worker thread with
its own Playwright instance, which is strictly worse.

Weight, and what it implies: the wheel is 38.2 MB on Windows because it bundles
a Node runtime plus the playwright-core driver, and browsers are roughly 281 MB
(Chromium), 187 MB (Firefox), 180 MB (WebKit). **Ship with no browsers, install
per engine on first use.** Lazy install is also lazy start, which matters for a
different reason in Section 4.6.

### 4.2 Lane A: driven (the default)

KS4Web launches a bundled browser with a KS4Web-owned profile. Headless or
headed. This is the reproducible, parallel-safe, CI-capable lane and it is what
most users get.

### 4.3 Lane B: branded (the dogfood lane, flag-gated)

KS4Web launches the user's **installed** Chrome or Firefox, still with a
KS4Web-owned profile.

- Chrome side: `channel="chrome"` / `"msedge"`. Mature, low risk.
- Firefox side: `channel="moz-firefox"`. This is the most interesting finding in
  the engine research and the most contingent. Playwright registers three
  undocumented channels (`moz-firefox`, `-beta`, `-nightly`) via
  `_createBidiFirefoxChannel`, resolving `\Mozilla Firefox\firefox.exe` under
  LOCALAPPDATA / PROGRAMFILES with `installType: 'none'`, and routes them to a
  BiDi backend rather than the patched Juggler build. Both `launch` and
  `launch_persistent_context` are supported. `C:\Program Files\Mozilla Firefox\
  firefox.exe` exists on this machine, which is exactly where the lookup goes.

**S3 ran on 2026-09-05 and the channel HOLDS.** `moz-firefox` is present and
shipping in playwright-python 1.62.0, **not flag-gated at runtime**: the driver
registers `moz-firefox` / `-beta` / `-nightly` as `_createBidiFirefoxChannel`
executables and `Firefox.launch()` routes any `moz-` channel to the
`BidiFirefox` browser type, with no environment variable and no experimental
opt-in. It launched the installed `C:\Program Files\Mozilla Firefox\
firefox.exe` (Firefox 154.0.1, confirmed by both the process `ExecutablePath`
and an `rv:154.0` user agent), then navigated, clicked, filled inputs and a
textarea, selected an option, checked a box, ran a JS handler, evaluated,
took an aria snapshot, screenshotted, and round-tripped a form POST. Headed
mode works too, which is the dogfood shape. **Lane B Firefox stands, and the
`executable_path` contingency was not needed.**

Three caveats survive, in revised form. The channel is **not in the public
docs** (`docs/src/browsers.md` never mentions it), so it can still move. Version
skew is still the user's problem, since whatever Firefox they have installed is
what gets driven. And it rides Playwright's BiDi backend, whose hole list is
**materially smaller than the research believed** and is now measured rather
than quoted (Section 4.5a).

**One new gap S3 found, and it changes an implementation assumption rather
than the lane's standing:** `about:` pages cannot be navigated on this lane.
The refusal is explicit (`Protocol error (browsingContext.navigate):
unsupported operation. Navigation to "about:support" is not allowed in this
context`). So **provenance never comes from `about:support`**; it comes from
the process table and the user-agent string, both of which S3 used
successfully. Any future version banner, profile-provenance check, or
`about:config` read is unavailable on Firefox/BiDi and must say so.

**CRITICAL SAFETY REQUIREMENT, found in S3 and binding on every Firefox
launch KS4Web ever makes.** Playwright's `BidiFirefox.defaultArgs` builds
`["--remote-debugging-port=0", "--headless"|"--foreground", "--profile",
<dir>]` and **does NOT pass `-no-remote`**, unlike its own Juggler Firefox
path, which does. Without `-no-remote`, a launch can be picked up by a
Firefox instance the user is already running, which is precisely the
collision Section 4.6 exists to prevent, arrived at from a direction that
section did not anticipate. **KS4Web supplies `-no-remote` itself on every
Firefox launch, on every lane, in every mode, with no flag to turn it off.**
This is not a default; it is a constant. The spike ran under it throughout
and never touched the author's open browser.

Note what makes the bundled Firefox unsuitable for dogfooding in the first
place: it is Firefox release-branch source plus Playwright's Juggler protocol
compiled in, with its own binary and its own update path. Playwright says so
plainly: "Playwright doesn't work with the branded version of Firefox since it
relies on patches." Dogfooding it means dogfooding a browser the author does not
otherwise use, which defeats the point.

### 4.4 Lane C: live attach (the unique position)

KS4Web attaches to a browser the user is already running.

**Chrome side.** `connect_over_cdp` to a Chrome the user launched with
`--remote-debugging-port` **and a non-default `--user-data-dir`**. Chrome 136
closed the interesting case: the debugging flags "will no longer be respected if
attempting to debug the default Chrome data directory," because "we've seen an
increase in attackers using Chrome Remote Debugging to extract cookies." So
"attach to the Chrome you are already logged into, on your normal profile" is
dead, permanently, and any Chrome Lane C story involves a second profile. That
must be documented as a worse story than Firefox's rather than papered over.
Playwright itself calls this connection "significantly lower fidelity."

**Firefox side, and this is the differentiator.** Mozilla's remote agent is
enabled only by a command-line flag, with no runtime toggle, so you cannot turn
BiDi on in an already-running Firefox. But Mozilla imposes **no restriction on
using that flag with the default profile.** A user who adds
`--remote-debugging-port=9222` to their Firefox shortcut exposes a BiDi endpoint
on loopback for that browser's entire lifetime, on their real profile, with
their real logins and extensions. **That is the one place in this entire
category where "your actual logged-in browser, right now" is truthfully
deliverable**, and it is available precisely because Firefox went the opposite
direction from Chrome.

Playwright cannot reach it. `browserType.ts` defines `connectOverCDP` and
nothing else; there is no `connectOverBiDi` and no public way to hand Playwright
an existing BiDi WebSocket. So Lane C Firefox needs **a thin in-house BiDi
client** speaking to `ws://127.0.0.1:9222/session`. BiDi is a clean, specified,
JSON-RPC-shaped protocol (W3C Editor's Draft, ten modules), unlike CDP's sprawl,
so a read-mostly client is bounded work. It is written from the W3C spec, not
lifted from Playwright's bidi sources, which keeps every license future open
(Section 10).

The security posture must be stated plainly in every user-facing surface: no
auth, no encryption, loopback only, and **anything on the machine that can reach
that port can drive the browser.**

### 4.5 Lane C is not the same tools pointed elsewhere

This is the discipline the family already proved in word-mcp, where the
visible-instance path is three operations and not the whole surface. KS4Web
inherits it exactly.

Lane C is by definition operating inside a session holding the user's real
credentials, so the Lane C toolset is small, explicitly enumerated, and
read-mostly:

**Allowed in Lane C:** `get_page_view`, `find_elements`, `get_text`,
`get_table`, `get_metadata`, `manage_tabs` (list and select only),
`take_screenshot`, `get_audit`.

**Never in Lane C:** navigating the user's tabs out from under them, storage
reads or writes, network routing, emulation, downloads, uploads, and
`evaluate_script`. Typing and clicking are **opt-in behind an explicit launch
flag**, and when enabled every action goes through a confirmation gate with no
"always allow" path.

`manage_session(action="capabilities")` is the honest-refusal instrument for all
of this. It reports what the current lane supports, degrades, and cannot do, and
`LANE_UNSUPPORTED` refuses loudly with the lane named and the lane that would
support the operation. The engine research asked for exactly this tool by name,
and the alternative is the silent degradation the whole category suffers from.

### 4.5a The BiDi capability table, measured (S4, 2026-09-05)

**The research's documented hole list was stale, and this table replaces it.**
Twenty probes ran on both `moz-firefox` (Firefox 154) and Chromium against a
local deterministic fixture server, with Chromium as the control. **Every
probe passed on Chromium**, so each Firefox difference below is a genuine lane
difference rather than a broken probe. This is the seed of the truth table
`manage_session(capabilities)` returns, and it is measurement rather than
inheritance.

**Two of the three documented gaps are REFUTED.** They were carried into this
design from research that quoted an older state of the backend:

| Believed gap | Measured |
|---|---|
| No response bodies | **WORKS.** `response.body()` returned 708 bytes for a document and a full JSON body for an XHR POST. |
| Downloads broken (`browsingContext.downloadWillBegin` not firing) | **WORKS.** Download event fired and the file landed on disk at 460 bytes. |
| HTTP auth fails (`network.continueWithAuth`) | **WORKS.** A 401 challenge was answered and the protected resource returned. |

Also measured as working, against expectations the design carried: header
overrides survive a 302 redirect, clicks land correctly inside a
`rotate(37deg) scale(1.6)` transformed element, and locale plus timezone
emulation both apply. `route.fulfill`, `route.abort`, `route.fetch()`, cookies,
dialogs, `set_input_files`, full-page screenshots, and request events all work.

**Two gaps are real, and the shape of each matters more than its existence.**

| Gap | Behavior | Row |
|---|---|---|
| **Request body READS** | `request.post_data`, `post_data_buffer`, and `post_data_json` all return `None` with **no exception raised**, on both a fetch POST and a form submit, while `content-length: 24` proves the body exists. The same holds inside a route handler. **Writing works**: `route.continue_(post_data=...)` was accepted and the fixture server received the tampered body verbatim. | `LANE_UNSUPPORTED` on read. The honest capability row is "request bodies: write yes, read no," never "no request bodies." |
| **History navigation** | `go_back` and `go_forward` time out after their full budget, and **the navigation actually happened**: the DOM is the previous page while `page.url` still reports the old one. In-page `history.back()` shows the same stale URL, so this is Playwright's BiDi URL tracking on history traversal rather than a `go_back()` wiring bug. | `LANE_UNSUPPORTED`. This is the worse of the two, because the failure is not absence, it is a lie. |

The two `LANE_UNSUPPORTED` messages, which are product text and not notes:

> **request body capture is unavailable on Firefox/BiDi.** Playwright returns
> null rather than raising, so KS4Web refuses explicitly instead of returning
> an empty body. Chromium supports it; relaunch on Lane A or Lane B Chrome to
> read request bodies.

> **history navigation (back and forward) is unavailable on Firefox/BiDi.**
> The page does navigate, but the driver never reports it and `page.url` goes
> stale afterward, so KS4Web refuses rather than calling it. Navigate to the
> previous URL directly instead; KS4Web tracks page history for exactly this.
> Chromium supports back and forward normally.

**Two rules follow, and they are the reason this table is in the design rather
than in a spike file.** First, both gaps fail SILENTLY or MISLEADINGLY in the
driver, which is the failure class this entire product argues against, so both
become LOUD REFUSALS at the KS4Web layer rather than pass-throughs. Second,
**`page.url` is not trusted after any history traversal on Firefox/BiDi**, so
no anchor logic, `wait_for_url`, or load-state wait may derive from it there.

**One cost row that is not a gap.** `page.pdf()` works on Firefox/BiDi, which
is itself a surprise, since PDF generation was assumed Chromium-only. It
produced 232 KB in **8.7 seconds** against Chromium's 240 KB in **0.2
seconds**, roughly 45x slower. That is recorded as a COST in the capability
table and named in the tool's own result, not as an unsupported row and not as
a new error code: an operation that works and is slow is a different fact from
one that does not work, and collapsing the two is how a capabilities table
stops being useful.

**Gate ruling (PLAN S4's stated threshold).** Neither missing capability is
lite core. Reading request bodies is a `network` pack concern, and back and
forward is a navigation convenience with a working substitute. **The Firefox
lanes survive at full standing**, carrying two `LANE_UNSUPPORTED` rows and one
cost row.

### 4.6 Profile safety: the hard rule

**KS4Web never opens the user's real browser profile. Not read-write, not
read-only, not "just once."**

**And the rule needs a second clause that S3 found, because the first clause
alone does not deliver it on Firefox.** Passing a fresh profile directory is
not sufficient to stay out of the user's running browser: Playwright's
`BidiFirefox.defaultArgs` omits `-no-remote`, which its own Juggler Firefox
path includes, so a launch can be adopted by an already-running instance
regardless of what profile directory was named. **KS4Web supplies `-no-remote`
on every Firefox launch, unconditionally, with no flag to disable it**
(Section 4.3). The hard rule is therefore: an owned profile directory AND
`-no-remote`, together, every time.

Two independent reasons on Firefox. Playwright's `BidiFirefox.prepareUserDataDir`
calls `createProfile`, which calls `writePreferences`, which **overwrites
`user.js` wholesale** in the target directory with roughly a hundred testing
preferences and backs up any existing `prefs.js`. And `browserType.ts` calls
`prepareUserDataDir` on **every** launch, persistent or not. Separately, Firefox
holds an exclusive lock on an in-use profile, so the daily browser and KS4Web
cannot share it concurrently in any case.

On Chromium the docs are equally clear: "Due to recent Chrome policy changes,
automating the default Chrome user profile is not supported. Pointing
`userDataDir` to Chrome's main 'User Data' directory may result in pages not
loading or the browser exiting."

**The sanctioned pattern is a seeded copy.** A KS4Web-owned profile directory,
populated once from a named subset of the real profile, with the real profile
closed:

- Copy: `cookies.sqlite`, `key4.db` **and** `logins.json` together (the login
  store and its key must travel as a pair), `places.sqlite`, `permissions.sqlite`,
  and `extensions/` plus `extensions.json` if extensions are wanted.
- Never copy: `user.js` (Playwright is about to write its own), `parent.lock`,
  or any cache directory.
- Seeding and re-seeding are **manual, explicit operations, never automatic**,
  because a profile copy is a credential copy and it belongs in the audit log.
- After any seed, verify the SOURCE profile's `user.js` is untouched. This is a
  spike gate, not a hope.

Whether copied Chrome profiles decrypt at a non-default path is an open
empirical question (App-Bound Encryption), resolved by Spike 6, not guessed.

### 4.7 Windows process hygiene: three defenses, not one

This is the least glamorous opening and possibly the most winnable, and the
family already owns the discipline from the COM work.

The evidence is severe. chrome-devtools-mcp #2621 (open against 1.8.0, no
maintainer reply): **42 orphaned Chrome root processes plus roughly 300 helper
processes, ages from five minutes to nine-plus hours, across 83 MCP
connections**, all at ppid=1. #2599: a dormant page burning 28 to 30 percent CPU
continuously for hours, dropping to 0.13 percent after parking to `about:blank`.
playwright-mcp #1568: 11 orphaned profile directories totaling ~1 GB after eight
days. Client-side reports name playwright-mcp as victim at 213 orphaned pairs
and 13.6 GB, and 1,300 zombies at 37 GB. And MEASURED reproduced it first-party
on this Windows machine: chrome-devtools-mcp orphaned eight `chrome.exe`
processes under a dead parent when its stdio client disconnected, while
playwright-mcp cleaned up correctly under identical conditions.

The generalizable lesson from the incumbent's own fix history: it has correct
teardown on every path where it gets to run code, and no teardown at all on the
path MCP clients actually use, because `process.on('SIGTERM')` handlers **do not
run under SIGKILL** and MCP hosts routinely force-kill workers.

So, three defenses:

1. **A liveness mechanism that outlives the parent.** Own process group plus a
   death-pipe sentinel the child watches, so the browser dies when the server is
   SIGKILLed. Signal handlers are necessary and provably not sufficient.
2. **A startup reaper.** Sweep stale KS4Web profile directories whose owner PID
   is gone. Inherited house rule, absolute: **never sweep by process name, only
   by owned PID**, and never touch a browser process KS4Web did not spawn.
3. **A default idle timeout.** Park dormant pages to `about:blank`, then recycle
   the context.

Plus **lazy browser start**, because codex #21984 names "eager startup and
session-lifetime retention of GUI-capable MCP tools" as the root cause of the
worst leak reports. And a Windows-native install path that invokes the
interpreter by absolute path rather than routing through a shim, since the
node-side analog (npx.cmd breaking stdio pipes under `cmd /c`) is a documented
first-class Windows defect and the Python console-script shim needs the same
scrutiny.

**S7's Windows slice ran on 2026-09-05 and the position HOLDS, with the
implementation hooks confirmed as available.** Ten scenarios across both lanes,
including the harshest (server process and the Node driver both hard-killed
with `taskkill /F`): **zero orphans in every one**, with full reap in 2.0 to
3.5 seconds. Chromium spawns 4 processes per session and `moz-firefox` spawns
10 or 11, and all of them died.

**The confound was found and ruled out, and that finding changes how KS4Web is
TESTED rather than how it is built.** The spike process was itself already
inside a Windows job object carrying `KILL_ON_JOB_CLOSE`, inherited from the
harness shell, and spawned children inherit it, which would have made every
"zero orphans" result the harness's doing rather than Playwright's. The
harshest scenario was re-run with the child created under
`CREATE_BREAKAWAY_FROM_JOB` (granted), genuinely outside any job, and both
lanes still reaped cleanly. So Playwright's own death pipe is doing the work
today. **The consequence is a testing requirement: the orphan gate must prove
it can FAIL, or it proves nothing**, because an orphan bug is invisible when
the server is launched from a shell that owns a kill-on-close job. That is now
a named part of the gate rather than a footnote.

**The gate definition names TWO instruments, and the second one is the
requirement.** Breakaway was the mechanism S7 used and Phase 1 found it is not
portable: the ambient job on this machine carries `0x3000`,
`KILL_ON_JOB_CLOSE` plus `SILENT_BREAKAWAY_OK` with `BREAKAWAY_OK` off, so the
explicit flag is denied on some paths and accepted on others, and the child
lands inside a kill-on-close job either way. Creating the victim through WMI
`Win32_Process::Create`, which builds the process from the service rather than
from us, does not escape it either. **So the gate requires a NEGATIVE CONTROL
and takes breakaway as an optional second instrument where the environment
grants it.** The control starts a browser under plain `Popen` with no death
pipe, no job object, and no teardown of any kind, hard-kills its parent, and
requires that the browser SURVIVE. Phase 1 measured 11 orphaned processes from
that control, which is what licenses the zero-orphan rows that follow it.
Breakaway is a proxy for "the harness is not doing the work"; the negative
control measures that property directly, on whatever machine the gate happens
to run, which is why it is the primary instrument rather than the substitute.

**Four mechanical facts a Python implementation needs, all measured:**

1. **Job objects are fully available from plain CPython via ctypes.**
   `CreateJobObjectW`, `SetInformationJobObject` with
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, and `AssignProcessToJobObject` all
   succeed. **One trap, hit and fixed in the spike: HANDLEs are pointer-sized,
   and ctypes' default `c_int` restype truncates them on win64**, after which
   every call fails with `ERROR_INVALID_HANDLE (6)`. `restype` and `argtypes`
   must be `c_void_p` or the reaper silently does nothing, which is the worst
   possible failure mode for a safety mechanism. This is recorded here because
   a silent no-op reaper would pass every test that checks the reaper exists.
2. **Child PID enumeration needs no third-party dependency**:
   `Get-CimInstance Win32_Process` supplies pid, ppid, name, executable path,
   and command line. Cost measured at roughly **1.0 second for 557
   processes**, which is far too slow for a hot path and entirely fine for
   shutdown and for a periodic sweep. **Phase 1 replaced it for the census.**
   The Toolhelp32 snapshot API (`CreateToolhelp32Snapshot`, `Process32FirstW`,
   `Process32NextW`) supplies pid, ppid, and image name through the same ctypes
   route at **single-digit milliseconds** for the same process table, which is
   three orders of magnitude cheaper and makes a per-launch census affordable
   rather than something the design has to ration. CIM stays for the one field
   Toolhelp32 does not carry, the command line, which only the reaper's last
   fence reads. **The consequence is architectural rather than cosmetic:** a
   census cheap enough to run on every launch is what lets the journal record
   who was already there before we started, and that before-and-after
   difference is the whole adoption filter in defense 2.
3. **Playwright's Python API does not expose the browser process PID**
   (`context._impl_obj` carries no pid or process attribute), so the owned-PID
   journal cannot be populated from the driver. It comes from the process
   table at launch, or from a job object KS4Web owns. That is a real
   constraint on how defense 2 is built and it was previously an assumption.
4. **A bounded per-operation timeout genuinely frees the server.**
   `page.goto()` against an endpoint that never answers returned a
   `TimeoutError` at 3,017 ms against a 3,000 ms budget on both lanes, and the
   browser was fully usable afterward.

**Three more facts came out of building the layer in Phase 1, and each one is
a defect the obvious implementation has.** They are recorded here because all
three fail in the direction that authorizes a kill or hides a survivor, which
is the direction a hygiene layer must never fail in.

5. **`OpenProcess` succeeding does not mean the process is alive.** A handle
   keeps the process object resident after the process has exited, and a parent
   holding a `Popen` holds exactly such a handle, so the naive liveness check
   reports every dead child as a survivor for as long as its parent lives.
   **Liveness waits on the process HANDLE**, which signals on exit, rather than
   asking whether the PID can be opened. The naive version fails toward
   "everything leaked," which sounds conservative and in practice makes the
   reaper's evidence worthless.

6. **A parent-PID walk adopts strangers, because a ppid field points at a
   NUMBER and Windows recycles PIDs.** An unrelated process whose parent PID
   happens to match a recycled value enters the walk as a child. Measured on
   this machine, a genuine five-process browser tree came back as a
   **forty-process claim**, which would have authorized forty kills. **A child
   cannot predate its parent**, so every candidate's creation time is compared
   against its claimed parent's, and every one of those thirty-five dropped out
   without dropping a real child. The rule generalizes past this walk: any
   Windows process relationship inferred from a PID needs a creation-time
   check, since the PID alone is not an identity.

7. **The journal's adoption filter is a difference, not a name match.** Only
   browser-shaped descendants that appeared between the pre-launch census and
   the post-launch one enter the journal, which is what makes fact 2's cheap
   census load-bearing. This is the opposite of the banned pattern rather than
   a soft version of it: sweeping BY name would authorize killing a browser the
   user started, and the filter here can only ever authorize something we
   watched arrive. The reaper's last fence then fires on **positive evidence of
   somebody else's ownership**, never on the absence of evidence of ours,
   because requiring a command line that names an owned profile declines every
   helper process that does not repeat its root's flags, and declining to kill
   a helper is how the orphan gets left behind.

**Design read: the death pipe is doing the work, and the job object is a
cheap, provably functional belt-and-braces backstop.** Both hooks the three
defenses wanted exist, so defense 1 ships as death pipe PLUS job object rather
than either alone.

---

## 5. Safety pillars as concrete tool behavior

SAFETY identifies four pillars unserved by every incumbent surveyed. Those four
lead. The other four are built because they are correct.

Two copy rules bind every word written about any of this, and they bind the
design too, because a feature framed by the attack it stops gets described that
way forever:

- **"Reduces, gates, flags, logs, requires confirmation for."** Never
  "prevents," "secure," "safe," or "protected" as unqualified verbs.
- **Never frame a feature by the attack it stops.** "Our hidden-text scanner
  catches white-on-white injection payloads" is a tutorial. "Page text is
  delivered to the model as labeled data, with hidden regions flagged" is the
  same fact with no recipe.

The constraint that outranks all eight pillars: KS4Web holds all three legs of
the lethal trifecta by default. It runs in a logged-in browser (private data),
reads arbitrary pages (untrusted content), and can navigate and submit forms
(exfiltration channel). The pillars reduce risk; they do not resolve it. The
honest architectural answer is to make it easy to run **without one of the
legs**, and to say so plainly instead of claiming the combination has been made
safe.

### 5.1 P1: untrusted-content projection

- **Labeled envelope.** All page-derived text is delivered inside an explicit
  data envelope with a per-call nonce delimiter, never as bare text in the tool
  result. Spotlighting measured attack success dropping from over 50 percent to
  under 2 percent with provenance marking, on GPT-family models, with minimal
  task-efficacy cost. It is a prompt-layer signal, argue-past-able, not a
  guarantee, and the copy says so.
- **Provenance per region.** Each chunk carries its origin URL, whether it came
  from first-party markup or an embedded frame, and whether it sits in a
  user-generated-shaped container. That last one is a heuristic and is labeled as
  a heuristic.
- **Hidden-content normalization.** Nodes hidden via `display:none`,
  `visibility:hidden`, `opacity:0`, near-zero font size, off-screen positioning,
  `aria-hidden`, zero size, white-on-white contrast, HTML comments, and
  zero-width Unicode are stripped from the content and **counted in the
  completeness block**. Never silently dropped, never silently included.
  `include_hidden=true` routes them into a separately labeled section, never
  mixed into the main text. This technique class is what the Comet exfiltration
  depended on, and it is definitionally bypassable (image-rendered text, plausible
  visible text), which the copy states.
- **Read/act separation** is the MCP-colors direction: reads are red (exposed to
  untrusted content), acting tools are blue. Advertised in `_meta`, **enforced
  server-side**, because the spec is explicit that clients "MUST consider tool
  annotations to be untrusted unless they come from trusted servers." Annotations
  are the advertisement; the server is the control.

### 5.2 P2: server-level read-only mode (the strongest differentiator)

**Nobody ships this.** playwright-mcp tags individual tools read-only and leaves
enforcement to the client's allowlist. chrome-devtools-mcp has nothing. Neither
do Claude for Chrome, Operator, Atlas, Comet, or browser-use. Everyone gates
individual actions; nobody offers a mode-level guarantee that no mutating call
can occur.

In KS4Web read-only mode, **mutating tools are not registered at all.** They do
not appear in `tools/list`, so there is nothing to allowlist, nothing to
misconfigure, and nothing for an injected instruction to reach for. It is the
browser equivalent of opening a document without a write handle.

Two grades, because navigation is genuinely ambiguous:

- **`browse` (default when the flag is bare):** navigation, back/forward,
  scroll, and every read tool. No clicking, typing, submitting, uploading,
  downloading, storage writes, routing, or script evaluation.
- **`strict`:** as above, but navigation is limited to the origin allowlist.

The honest statement, which the copy must carry: read-only removes the ACT leg
of the trifecta, and navigation remains an outbound channel, so `strict` paired
with an origin allowlist is what closes it. The claim is "no tool in this mode
can click, type, submit, upload, download, evaluate script, or write storage,"
never "cannot change anything," because a URL can mutate server state.

**Spec interaction, and it is load-bearing:** this is a LAUNCH-TIME property,
process-wide and identical for every connection. It cannot be a runtime toggle
without varying the tool set per connection, which the 2026-07-28 spec forbids
(Section 7.1). The strongest safety differentiator in the design is therefore
only conformant as a launch flag, which is a genuine synthesis point across two
research reports that did not talk to each other.

### 5.3 P4: credential blindness

Unserved as a tool-level control. Every incumbent architects the secret out of
the model's context (1Password relay, Operator takeover mode, browser-use
placeholder substitution) and none makes the tool itself password-blind. Two
security issues on playwright-mcp are unowned to this day: **#1566, accessibility
snapshot serializes password input values as plaintext**, and #1479, indirect
prompt injection via snapshots.

Concrete behavior:

- Any element with `type=password`, or `autocomplete` in the
  current-password / new-password / one-time-code family, is projected as
  `ref | role=textbox | name="Password" | secret=true` and **its value is never
  read**, not even redacted in place. Reading a redacted value and reading no
  value are different guarantees.
- `type_text` and `fill_form` **refuse** to write into a secret field, with
  `CREDENTIAL_REFUSED` naming the two sanctioned routes: a server-side secrets
  file where the value is substituted at execution time and never passes through
  the model, or `request_handoff`, where the run pauses and the human types it in
  the headed window.
- Screenshots mask secret-tagged elements before the image is returned, using
  Playwright's `mask=` where available. **Fail closed:** if masking cannot be
  applied on the current lane, the screenshot is refused, not returned unmasked.
- Cookie and storage reads return names and metadata with values masked.
  `unmask=true` is per-call, explicit, audited, and refused under
  `KS4WEB_CREDENTIAL_BLIND=strict` (the default).
- `save_auth_state(path)` writes session state to a FILE, so authentication can
  be reused across runs without ever entering the model's context. This is the
  key move and it is the one nobody frames as a safety feature.
- **Redaction lives in the envelope serializer**, applied to every outgoing
  payload and every file write, not per tool. playwright-mcp's `redactSecrets()`
  in `Response.serialize()` is the right architecture and is copied. Per-tool
  discipline fails the moment someone adds a feature; the incumbent's own console
  regression is the proof.

### 5.4 P3: confirmation gates that re-validate at execution time

Everyone gates. The TOCTOU research shows naive gates are defeatable, and only
Anthropic is documented as re-snapshotting. The attack: a page times its own DOM
so the coordinates the agent reasoned about (a benign "Continue" button) are
swapped for a real destructive control between the screenshot and the click.

**The TOCTOU rule, binding on every gate in the system:** the gate captures an
identity fingerprint at ASK time (anchor fingerprint, accessible name, bounding
box, the form's action URL, the visible label of the control) and **re-computes
it at EXECUTE time**. Any mismatch aborts with `TARGET_CHANGED`, printing what
changed. This applies to coordinate actions too, where the check is the element
currently under the point.

Gated classes: form submit, payment-shaped forms (detected by `cc-number` /
`cc-exp` autocomplete tokens), file upload, download to disk, storage clear,
script evaluation, navigation to an origin outside the allowlist, and any action
inside an origin not on the allowlist.

**Mechanism, constrained by the platform.** Sampling is deprecated in the
2026-07-28 spec (SEP-2577, "New implementations SHOULD NOT adopt it") and Claude
Code does not advertise it. It DOES advertise elicitation. The spec's replacement
for server-initiated requests is MRTR: the server returns `InputRequiredResult`
with `resultType: "input_required"` and the client retries with `inputResponses`.
The retry carries `requestState`, the server's own correlation token, and the
gate engine depends on it: that token is how an arriving retry is matched back to
the pending gate, its captured fingerprint, and its TOCTOU re-validation, so it
is stored with the gate record rather than treated as protocol noise. Under
2026-07-28 elicitation itself is delivered through MRTR, as `inputRequests`
entries carrying `method: "elicitation/create"`, which is why the two paths below
are one implementation with two shapes. So gates are a **retry pattern, not a
callback.** KS4Web implements MRTR first,
elicitation where advertised, and **fails closed** where the client advertises
neither: the gated action refuses rather than proceeding.

`_meta["anthropic/requiresUserInteraction"]`, which would force a prompt even
under bypass permissions, requires Claude Code v2.1.199+ and is **absent from
2.1.92**, the version verified in the research. The gate design therefore cannot
depend on it today. It is set when present and never assumed.

**The permissions paradox**, which nobody in any thread answers and which this
design answers directly:

> "When every operation needs to be approved (every button click, every form
> entry, etc.) does it even make sense to use an agent?"
> "How is there not an actual deterministic traditionally programmed layer
> in-between the LLM and whatever it wants to do?"

The second quote is a specification. A deterministic policy layer that gates a
small set of irreversible action CLASSES, rather than prompting per click, is the
answer to both. Claude for Chrome is the cautionary example: *"I click 'Always
allow actions on this site.' The very next action on that same domain prompts
again... So a long browsing task dies waiting on a click you never saw."*

### 5.5 P6: action budgets and loop detection

Only browser-use documents any of this, and no MCP server does. It also maps to
OWASP LLM10, Unbounded Consumption.

- **Per-session budgets:** max actions, max navigations, max distinct new
  origins, max downloads, wall-clock ceiling. Generous defaults, finite always.
- **On trip:** `BUDGET_EXHAUSTED`, with the counters printed and the reset route
  named. The reset route runs through the MRTR gate so a human answers, because a
  budget the model can reset by calling a tool is not a budget.
- **Loop detection:** a rolling window over (tool, target anchor fingerprint,
  argument hash). Repetition or cycling beyond a threshold trips `LOOP_DETECTED`
  with the observed cycle printed. browser-use's `loop_detection_window: 20` is
  the only prior art in the field.
- **Per-domain rate limiting**, respecting HTTP 429 and `Retry-After`, which
  also serves the honest-tool posture.

### 5.6 P7: audit trail and replay

Unserved. No browser agent ships a user-facing action log. The vendor features
that look adjacent (one-click "delete all browsing data," memory archiving) let a
user **erase** what happened, not review it. This is the closest true analog to
the document-side backup pillar: you cannot always undo a web action, but you can
always know exactly what was done.

Every tool call appends a structured record: timestamp, lane, page handle, URL,
tool, the resolved target (anchor fingerprint plus its human label), an argument
summary with secrets already redacted by the serializer, the outcome, any rebind
event, any gate decision, and the budget counters at that moment. JSONL under a
session directory. `get_audit` renders it, paginated.

**Replay is the part that earns its keep.** Because anchors are content-derived,
the log is sufficient to re-execute a run. `run_workflow(..., dry_run=true)`
re-resolves every anchor and reports which still resolve **before executing
anything**. That closes the #1645 fork: a deployment that disables script
evaluation for safety does not lose workflow reuse.

Honest framing, and it is a marketing caution not a technical one: this is an
operational log for the user. It is **not** forensic and **not** evidence.
Calling it forensic invites reliance the implementation cannot bear.

### 5.7 Verified outcomes (the silent-false-success answer)

Not one of SAFETY's eight pillars, but it belongs here because it is the same
disease. browser-use #5438 and #5361: `click`, `dropdown_options`,
`select_dropdown`, `scroll`, `input`, and `find_text` all return "element not
found" as a **non-error result**, so the agent records success and continues.
*"the browser action objectively did not happen, but the agent loop records
success and keeps executing queued effects."* chrome-devtools-mcp's version is
stale page ids silently rebinding to different pages (#2339, #2304). A crash is
visible; a false success corrupts everything downstream while looking fine.

And there is a mechanical cause almost nobody knows: **modern React UIs check
`event.isTrusted` and silently no-op on synthetic clicks.** No error, the handler
quietly does nothing. That single fact explains a large share of "the agent
clicked but nothing happened," it compounds with the false-success failure, and
it is fixable by dispatching trusted input through the driver rather than
synthesizing DOM events. Playwright's input path already does this; the raw-BiDi
Lane C client must use `input.performActions` and never JS synthesis.

So every action tool returns an OUTCOME, not a bare ok: did the DOM change, did
navigation start, did focus move, did the target's own state change (checked,
expanded, value)? If nothing observable happened, the result says
`effect: "none-observed"` with a warning. **An action that cannot verify it
happened must say so.**

### 5.8 P8: the honest-tool posture

Rules OUT, permanently: fingerprint spoofing, `navigator.webdriver` patching,
CAPTCHA solving or CAPTCHA-service integration, residential proxy bundling,
stealth-branded modes, and any feature whose stated purpose is defeating a
site's access controls.

Rules IN: robots.txt surfaced as an advisory on navigate, an identifiable user
agent, Web Bot Auth signing when the ecosystem supports it (Cloudflare's Ed25519
and RFC 9421 HTTP Message Signatures scheme is the honest-agent-identity road
and the natural destination for a tool that refuses evasion), respecting 429 and
`Retry-After`, per-domain rate limiting, and **clear refusal when a site blocks
the agent rather than silent retry escalation**.

That last one is the capability, and it is unserved: bot-wall and CAPTCHA
detection with an honest handoff. Cloudflare interstitials, CAPTCHAs, rate
limits, bot-detection redirects, and expired sessions all currently surface to an
agent as a timeout or an empty page, so the agent burns turns retrying against a
wall it cannot pass. `BLOCKED_BY_SITE` names the wall and the handoff route in
one line.

The stakes argument is what sells this to a professional user, and it is not
"requests get blocked." It is account termination: a user's App Store Connect
account was terminated for fraud after an agent filled forms. Detect-and-report
is not the timid option, it is the option that does not get a working
professional's account killed.

Both incumbents have vacated this row explicitly. chrome-devtools-mcp #553:
"Right now we don't plan to add mechanisms to avoid bot detection." playwright-mcp
#58: "out of scope for this project, yes." A commenter in that thread named the
position precisely: *"there's a bit of a no-man's-land between reliability and
evasion."* That no-man's-land is where KS4Web sits.

### 5.9 P5: session scoping

Explicit choice of isolated versus seeded profile, a loud statement of which is
in use in `manage_session(status)`, per-domain origin allow and deny lists with
the deny list evaluated first, and the standing caveat that an origin list is a
convenience defense and not a security boundary (playwright-mcp's own honest
phrasing on its file guardrail is the model to copy: "a convenience defense to
catch unintended file access, not a secure boundary").

One design gap nobody has closed and KS4Web should attempt: **credentials scoped
per active task domain**, so an authenticated session on one site is not
reachable while the agent is operating on another. Feasible via per-origin
storage partitioning across separate contexts. Flagged as ambitious rather than
committed.

---

## 6. What we deliberately do NOT build

Every entry names the reason, because the value of this list is that it stops
future sessions relitigating settled ground.

1. **Anti-detection, stealth, CAPTCHA solving, residential proxies.** Conflicts
   with the family identity, the row is crowded (camoufox-mcp, WEBGhosting-MCP,
   puppeteer-real-browser and others), and it is what gets professional users'
   accounts terminated. Both incumbents vacated the row and demand keeps
   arriving; we take the honest half of it (detect and report), not the evasion
   half.

2. **A browser extension (MV3 plus native messaging).** Two shipping products
   converge on this design and both are big companies. The cost is a Web Store
   listing and review cycle, a stable extension ID pinned into every
   native-messaging manifest, per-OS registry or file installation, a second
   build pipeline in a different language, an update cadence coupled to store
   review, and a **permanent browser-wide infobar the user can cancel out from
   under you** (verified in Chromium source:
   `extension_dev_tools_infobar_delegate.cc`). It is also structurally
   Chrome-only, because **Firefox does not implement `chrome.debugger`**
   (bugzil.la/1316741), so a Firefox extension could do DOM reads and clicks and
   could not synthesize trusted input, intercept network traffic, or reach
   cross-origin frames. That is a scraper, not an engine. Revisit only if Lane C
   launch-flag friction proves fatal.

3. **Raw CDP as the engine.** It buys the ~50 CDP domains Playwright does not
   surface and costs everything Playwright does above the wire: frame and target
   lifecycle, execution-context tracking across navigations, auto-waiting and
   actionability, the selector engine, shadow piercing, trusted input synthesis,
   download and dialog handling, and interception plumbing. Multi-month, and the
   failures are intermittent and expensive. Playwright's own warning that
   `connect_over_cdp` is "significantly lower fidelity" is Microsoft saying their
   CDP path is the degraded one. **The escape hatch stays:** `CDPSession` is
   reachable from inside a Playwright Chromium context for any specific domain we
   need.

4. **Lighthouse, performance traces, heap snapshots, Core Web Vitals.**
   chrome-devtools-mcp owns this row with a funded Chrome team, a 13-tool heap
   query language with retainers and dominators and paginated retaining paths,
   and roughly ten million npm installs a month. Do not contest it. Say so, and
   point at the `CDPSession` escape hatch for anyone who needs a specific piece.

5. **An agent loop.** browser-use's best ideas are client-side and structurally
   unavailable to an MCP server: the browser state occupying **one slot that is
   overwritten each step rather than appended**, only the current screenshot
   retained, `max_history_items` keeping the first item plus an omitted marker
   plus the most recent N-1, and `maybe_compact_messages()`. That single decision
   is the real answer to snapshot accumulation, it is implemented because
   browser-use owns the loop, and a pure MCP server cannot do it. Say that
   plainly rather than pretending otherwise. What KS4Web CAN do is make each
   individual read small enough that accumulation matters less, and ship deltas so
   repeat reads are near-free.

6. **Cloud browser infrastructure.** Local-first is the position, and it is the
   position with no permissively-licensed complete occupant.

7. **Any path that touches the user's real browser profile.** Section 4.6.
   Seeded copies only, forever.

8. **An unnamed dangerous tool.** `evaluate_script` ships, named for what it is,
   off by default, refused under read-only, gated, and audited. playwright-mcp
   got this right by calling its version `browser_run_code_unsafe` and putting
   "RCE-equivalent" in the description where the model cannot miss it. An
   independent audit found three of four browser MCP tools expose arbitrary
   page-context JS. Crucially, **because eval exists, workflows must not require
   it**, which is the whole point of Section 2.2's workflows pack.

9. **Vision-first interaction.** The Reflex benchmark: the same admin-panel task
   took a vision agent 53 steps, ~17 minutes, and 550,976 input tokens against 8
   steps, 19.7 seconds, and 12,151 tokens through structured access. Screenshots
   are a fallback for canvas, video, and PDF viewers where DOM parsing fails, and
   a verification aid, and they are hard-capped and format-validated.

10. **Per-click permission prompts.** Section 5.4.

11. **Protocol-level pagination of tool results.** It does not exist, in any
    spec revision (Section 7.2). Pagination lives in tool arguments. Building
    toward a protocol feature that is not coming would be a wasted phase.

12. **Deferred to v1.1, not rejected:** WebSocket and SSE frame capture, service
    worker and web worker inspection, visual regression diffing, video recording,
    and a code-mode execution surface. All four of the first are verified unserved
    across all 21 servers inspected, which makes them a strong v1.1 slate rather
    than v1 scope creep.

---

## 7. The tiering mechanism versus the spec constraint

This is the hardest constraint in the design and it kills the obvious answer.

### 7.1 The constraint

MCP spec revision **2026-07-28** (current; not 2025-06-18) states that the tool
set "MUST NOT vary per-connection or as a side effect of other requests on the
connection. The set MAY vary by the authorization presented."

The same revision **removed protocol sessions** and names browser automation as
its motivating example: "Servers that need to maintain state across calls, a
shopping cart, **an open browser context**, a database transaction, should do so
by returning an explicit handle from a creation tool and accepting that handle as
an argument on subsequent calls." That handle passage sits in the spec's
**non-normative** "Stateful Tools" guidance and uses "should," so the precise
statement is not that connection-scoped browser state is forbidden by a MUST: the
normative basis is the removal of protocol sessions and `Mcp-Session-Id`
(SEP-2567), which makes connection-scoped state unreliable and unsupported rather
than illegal. The consequence for this design is the same either way, which is
why `manage_tabs` and `manage_session` mint and return explicit page and session
handles that every other tool accepts.

### 7.2 Re-examining the family's `enable_tools` pattern, as instructed

The family pattern, read from the shipped word-mcp `packs.py`: every tool is
registered with FastMCP up front, non-lite tools start disabled, and
`enable_tools` flips packs on mid-session using **session-scoped**
`ctx.enable_components` / `disable_components`, which "send
ToolListChangedNotification to the session only."

Measured against the spec text, that does both forbidden things, and the order
matters. The tool set varies **as a side effect of another request on the
connection**, and the `enable_tools` call is that request. That is the prong that
bites on every transport, including a single-client stdio process, and it is the
one to lead with. The set also varies **per connection**, but that prong is
largely unobservable on per-process stdio servers, where each client spawns its
own process and no two connections share a tool set to differ. The "MAY vary by
the authorization presented" carve-out does not apply either way, because a local
stdio server presents no authorization and the variation is driven by a tool call
rather than by credentials.

**Assessment: the family's runtime enable_tools pattern cannot survive migration
to MCP 2026-07-28.** Stated precisely, because it implicates three shipped
products: conformance is judged per NEGOTIATED REVISION, not retroactively. The
siblings negotiate whatever revision FastMCP advertises, which today is a
2025-era revision under which the pattern is legal, so nothing shipped is
non-conformant now. **The trigger is not a KS4Web decision and not a spec event;
it is FastMCP bumping its advertised revision in a future release**, at which
point the siblings become silently non-conformant without a line of their code
changing. That version bump is the thing to watch, and Open Question 4 names it.
KS4Web will not ship the pattern regardless. Whether the shipped siblings change,
stay, or wait is a family-wide decision above this document's pay grade.

Two mechanical details reinforce the conclusion rather than soften it. Under
2026-07-28, `tools/list` results carry `ttlMs` and `cacheScope`, and `cacheScope`
can be `"public"`, so per-connection variation would actively poison shared
caches; the requirement has teeth beyond its prose. And the FastMCP machinery the
pattern rides on changes shape under that revision anyway, since `list_changed`
notifications flow only to clients holding a `subscriptions/listen` stream with
`toolsListChanged: true` (the old push path is gone) and the `initialize`
handshake was removed (SEP-2575).

Worth noting for that decision: this is a conformance question, not a
functionality question. Nothing breaks today. Claude Code honors `list_changed`
and the pattern works in practice. The risk is future clients enforcing the MUST
NOT, plus a registry or reviewer flagging it.

### 7.3 The conformant mechanism KS4Web ships

Three layers, none of which mutate `tools/list` mid-session.

**Layer 1: launch-time packs.** `KS4WEB_MODE` (lite, full, or a comma-separated
pack list) and `--packs`, resolved once at startup. Every connection to that
process sees an identical tool set, which satisfies the MUST NOT: the set does
not vary per connection or as a side effect of any request. Different users
configuring different processes is not per-connection variation. Read-only mode
(Section 5.2) rides the same mechanism, which is what makes "the mutating tools
do not exist" a provable property rather than a claim.

The cost is real and should not be minimized: a user who needs the storage pack
once a week either pays for it all week or does not have it in the moment. That
is exactly the criticism the family levels at playwright-mcp's `--caps`. Layers 2
and 3 are what buy most of it back.

**Layer 2: client-side progressive disclosure.** The `tools/list` result is
**identical on every connection**, and the CLIENT decides what enters the model's
context. Claude Code exposes two undocumented `_meta` fields for exactly this
(originally read from binary v2.1.92, re-verified against v2.1.220):
`anthropic/alwaysLoad` (boolean, exempts a tool from deferral so it is always in
context) and `anthropic/searchHint` (string, extra text indexed for tool-search
matching). Tool search engages by default once definitions exceed roughly 10
percent of the context budget. One asymmetry worth knowing: the client carries
its own server-side `search_hints` override table, and that table OUTRANKS a
tool's own `_meta` searchHint, so the hint is a suggestion the client may
overrule. Since the research baseline moves with every client release, **the
version of record is the client installed at spike time**, and S8 re-runs these
checks against it rather than against a quoted version number.

So: pin the lite core with `alwaysLoad`, enrich the long tail with
`searchHint`, and let the client's own machinery do the deferral. This is
strictly better than the family pattern for the token goal, since it is the
client, not the server, that controls what the model sees, and it is fully
conformant because the server's advertised set never changes.

Dependency risk, stated: these fields are undocumented and Anthropic-specific.
They are set opportunistically and nothing depends on them. On a client that
ignores them, Layer 1 is still the floor.

**Layer 3: parameters inside a stable surface.** The deepest tiering happens
inside tools rather than between them. `get_page_view`'s `view` and `detail` and
`budget_tokens` do more for the token bill than any pack boundary, because the
recurring cost is page reads and not schemas. This is the layer the incumbents
neglect entirely and it is where the 31x lives.

**Also inherited, and free:** mark every read tool `readOnlyHint: true`. Verified
from the Claude Code binary: `isConcurrencySafe(){return
_.annotations?.readOnlyHint ?? false}`. **A browser tool without
`readOnlyHint: true` is serialized and cannot run in parallel.** Marking reads
read-only unlocks concurrent execution for nothing.

**Constraints that shape every schema:** tool descriptions are truncated at
**2,048 characters** by the client. The truncation is silent toward the USER but
marked toward the MODEL, which sees an explicit "… [truncated]" appended to the
cut text while the client's internal copy keeps the full string. The mechanical
consequence for KS4Web is unchanged, since a description over budget still loses
its tail: the docstring-budget test enforces the limit at build time. The default
tool-result limit is
25,000 tokens and is **remotely reconfigurable server-side** by a feature gate
that no documentation mentions. Oversized results are persisted to disk first and
truncated only if that fails, and the client's own failure message tells the
model *"If this MCP server provides pagination or filtering tools, use them."*
The client is effectively specifying the behavior no server supplies.

### 7.4 The discoverability consequence

Family discoverability rule 2 says every refusal for out-of-scope work names the
pack and the exact `enable_tools` call. Under launch-time packs there is no
enable call to name. **The rule adapts rather than lapses:** the refusal names
the pack, the launch flag, and the environment variable, and `get_workflows` in
lite carries the full menu. The Phase 7 discoverability gate changes accordingly:
a fresh agent must correctly name the pack and flag it needs, and must not
attempt a workaround, since lite carries no degraded stand-in by rule 1.

This is a real regression against the sibling experience and the author should
see it as one. It is the price of conformance.

---

## 8. Error vocabulary and the envelope

### 8.1 The envelope

Inherited verbatim from KS4W v2 and KS4XL. File-mode-canonical shape becomes
lane-canonical here: **Lane A is canonical, and Lanes B and C ADD keys and never
change shape**, so there is one parsing path for every caller.

Success:

```json
{"ok": true,
 "page": "p1", "url": "https://...", "lane": "A",
 "changed": {"effect": "navigated", "from": "...", "to": "..."},
 "refs": [...],
 "budget": {"used": 3120, "limit": 5000, "rung": 1},
 "completeness": {...},
 "warnings": ["e12 was rebound: 'Submit' moved from form f1 to form f2"]}
```

Refusal, never a raw exception string:

```json
{"ok": false,
 "error": {"code": "...", "message": "...", "hint": "...",
           "matches": [...], "detail": {...}}}
```

### 8.2 Naming grammar

Inherited from KS4W v2 verbatim: `verb_object` from the fixed verb table
(create, insert, delete, set, get, list, find, replace, apply, format, validate,
convert, export, import, manage), plurality follows arrays, `manage_` is the
sanctioned action-parameter pattern for object lifecycles, capped.

**The one sanctioned extension:** browser action verbs (`navigate`, `click`,
`type`, `press`, `hover`, `scroll`, `wait`, `select`, `upload`, `download`) join
the table. Justification: the browser domain's core operations are physical
actions with universally understood names, and forcing them into `set_` or
`apply_` produces names no agent guesses and no human recognizes. Every incumbent
uses these verbs. This is Open Question 6.

Prefix policy adapts from the document family's file/COM/live split to lanes:

- **No prefix:** available on every lane, subject to `manage_session
  (capabilities)`.
- **`live_`:** the Lane C read-mostly set, reserved and enumerated in
  Section 4.5. The prefix and the routing seam ship from day one even if Lane C
  slips, so it bolts on without breakage. Same discipline as the family's
  deferred live tiers.

### 8.3 The closed code vocabulary

Inherited: `AMBIGUOUS_LOCATION`, `NOT_FOUND`, `RANGE_OUT_OF_BOUNDS`,
`STALE_ANCHOR`, `UNSUPPORTED_CONTENT`, `VALIDATION_FAILED`, `CONFLICT`,
`BAD_PARAMS`.

Browser additions, each with a named recovery in every message:

| Code | Fires when | The message names |
|---|---|---|
| `STALE_ANCHOR` | ref detached, page navigated, or rebind found zero matches | what the ref used to be, what changed, and the re-read call |
| `TARGET_CHANGED` | TOCTOU re-validation failed between gate and execution | the fingerprint fields that differ |
| `NAVIGATION_BLOCKED` | origin policy denied a navigation | the origin, the policy, and the flag that would allow it |
| `BLOCKED_BY_SITE` | bot wall, CAPTCHA, 403 challenge, rate limit | the wall type, any `Retry-After`, and the handoff route |
| `AUTH_REQUIRED` | login wall or expired session detected | which, and the handoff or `load_auth_state` route |
| `CREDENTIAL_REFUSED` | secret-field read or write attempted outside a sanctioned route | the two sanctioned routes |
| `BUDGET_EXHAUSTED` | any budget tripped | every counter and the gated reset route |
| `LOOP_DETECTED` | the rolling window found repetition or a cycle | the observed cycle, printed |
| `CONFIRMATION_REQUIRED` | a gated action class was requested | carries the MRTR / elicitation payload |
| `READ_ONLY_MODE` | a borderline operation (navigation under `strict`) was attempted | the grade in force and what it permits |
| `LANE_UNSUPPORTED` | the operation is unavailable on the current engine lane | the lane, the specific gap, and which lane supports it |
| `MODAL_BLOCKED` | a dialog or file chooser is pending | the pending modal and the tool that clears it |
| `TIMEOUT` | a wait expired | what was being waited for and what was observed instead |

Three failure-message designs stolen outright because they are the best in the
field, and one anti-pattern to invert:

- chrome-devtools-mcp's three distinct uid errors, each naming its recovery: no
  snapshot at all, uid absent from the current snapshot, and element detached.
- playwright-mcp's modal-state refusal, which names the blocking state and the
  tool that clears it, rather than timing out with an unrelated-looking error.
- Claude in Chrome's 20-match cap that says "use a more specific query." **The
  nudge is the important half: the refusal teaches the recovery.**
- The inversion: chrome-devtools-mcp #2530, where a typo in `--browserUrl` is
  silently ignored and **downgrades attach mode to launch mode**. Unknown flags
  are an error in KS4Web, not a shrug. Same for playwright-mcp #1388, where
  `--storage-state` silently applied zero cookies and was closed "works for me,"
  then reproduced by three more users. **Never degrade silently** is the whole
  subsystem in four words.

---

## 9. The location object

Inherited shape: every positional tool takes `location` with **exactly one**
selector key, and multiple matches REFUSE with every candidate rather than
acting on the first.

```json
{"ref": "e12"}                                   a live element reference
{"anchor": "a3f9"}                               a durable content-derived anchor
{"role": "button", "name": "Submit"}             role plus accessible name
{"text": "Sign in", "exact": false}              text match
{"describe": "the primary search box"}           natural-language description
{"css": "#main > button.submit"}                 CSS escape hatch
{"xpath": "//button[@type='submit']"}            XPath escape hatch
{"testid": "submit-button"}                      data-testid
{"region": "r4"}                                 a landmark region from the view
{"nth": {"role": "listitem", "index": 3}}        ordinal within a role
{"coordinate": {"x": 412, "y": 260}}             pixel fallback, last resort
```

`anchor` is the one selector a model cannot obtain from an ordinary page read.
Anchors live server-side keyed by ref, and their ids reach the model only through
`get_audit` records and saved workflow files (Section 3.5), which is exactly what
the key is for: replay and audit-driven recovery, not routine addressing.

Two modifiers apply to any selector: `frame` (a frame ref from the completeness
block, so cross-origin iframe addressing is a modifier and not a separate tool
family) and `shadow` (pierce open roots; closed roots refuse honestly with
`UNSUPPORTED_CONTENT` naming the count, because a closed shadow root is genuinely
unreachable and a server should say so rather than reporting "element not
found").

Zero matches refuse with nearest-miss candidates by name distance. That is
directly aimed at the top reliability complaint in the field: *"even for static
websites like hackernews front page it takes a couple tries of to and fro for the
llm to get it right."* Returning the candidates it considered turns a terminal
error into a one-turn recovery.

`describe` is the natural-language selector and it is the one place where a
non-deterministic resolution enters the design. Stagehand's 343 open issues
against 24k stars is the evidence that natural-language-to-selector has a long
failure tail. KS4Web resolves `describe` **deterministically first** (fuzzy match
over role, accessible name, placeholder, label, and nearby text) and never
resolves ambiguity by guessing: multiple candidates refuse with the list. No
inference call happens inside the server.

---

## 10. The license decision

**DEFERRED.** The author does not yet know how the family monetizes and has
declined to decide. **Nothing in this architecture depends on the license
choice.** This section states what each option would require STRUCTURALLY if
chosen, so the later decision is a swap and not a redesign.

### 10.1 What the research says is at stake

The sharpest strategic conclusion in the whole record (DEMAND, Part Six,
verified by source inspection across 21 servers): **the gap is not a capability
gap, it is a licensing-and-deployment gap.** Everything KS4Web would build exists
somewhere. It has never existed in one permissively-licensed, locally-run,
complete server.

- Skyvern is the only true kitchen sink at **116 verified tool registrations**
  (HAR, frames, dialogs, clipboard, credential vaults, state save and load), and
  it is **AGPL-3.0** and platform-heavy.
- Notte relicensed to **SSPL-1.0** and removed the local MCP server from main;
  it is cloud-only now.
- Browserless has the only complete download lifecycle and is paid.
- playwright-mcp and chrome-devtools-mcp are Apache-2.0, local, and
  well-maintained, and they **deliberately exclude** HAR, downloads, clipboard,
  iframes-as-tools, WebSocket capture, and shadow piercing.

So a professional or enterprise user who wants completeness must accept
copyleft; one who wants permissive must accept the deliberate exclusions. For
the constituency this family already serves, copyleft and cloud dependency are
frequently disqualifying at the procurement level, entirely independent of
quality. That constituency currently has no option at all.

That is an argument, not a decision. It is presented because it is the single
most consequential input to the choice.

### 10.2 What each option requires structurally

**(a) AGPL-3.0 dual-license, like the siblings.**
- A CLA is required for the dual-license to work. The family already has
  `CLA.md` and `CONTRIBUTING.md` shapes to copy, so this is a file drop.
- A `NOTICE` file plus a clean provenance ledger for every third-party snippet.
- Dependency compatibility: Playwright is Apache-2.0, which is one-way
  compatible into AGPL-3.0, so the core dependency is fine. Every additional
  dependency must be checked in the same direction.
- The structural cost is on future relicensing: any contribution not covered by
  the CLA permanently constrains the option set. This is a process requirement
  from commit one, not a ship-time one.

**(b) Permissive distribution flagship (MIT or Apache-2.0).**
- Prefer **Apache-2.0** over MIT if the patent grant matters, which it plausibly
  does for a browser-automation tool in a space with active commercial players.
- Hard requirement: **no copyleft or source-available dependency anywhere in the
  required install.** Every optional heavy dependency lives behind an extra
  (`pip install kitchensink4web[...]`) so a dependency's license never becomes
  the server's problem. This rule is adopted regardless of the license choice,
  because it is the only rule that keeps (b) reachable.
- Vendored code provenance must be clean. Concretely: **the thin BiDi client is
  written from the W3C specification, not lifted from Playwright's `bidi`
  sources.** Those sources are Apache-2.0 and would be legally fine, but writing
  from the spec keeps every option open at negligible cost. That decision is made
  now, in the design, precisely because it is cheap now and expensive later.
- No CLA is strictly required, though one is still worth having.

**(c) Open-core hybrid.**
- Requires a clean module boundary decided NOW, before any code, so that the
  boundary is architectural rather than retrofitted.
- **The boundary the architecture already builds:** `policy/` (read-only mode,
  gates, budgets, loop detection, audit, replay, redaction) is a separate package
  from `engine/` (lanes, process hygiene, handles) and `ops/` (the tools), with a
  **one-direction dependency: ops and engine depend on policy, never the
  reverse.** A plugin or entry-point seam at that boundary means any of the three
  futures is a packaging change and not a refactor.
- **The tension, stated because it is the real objection:** the safety pillars
  are the differentiator (Section 5). Putting the audit trail, the gates, and
  read-only mode behind a paywall would gut the free product's entire positioning
  and hand the "safety" story to nobody. If open-core is chosen, the seam almost
  certainly has to run somewhere else, and the honest candidates are
  cross-family integration, managed or hosted operation, or enterprise policy
  administration (org-wide allowlists, centralized audit collection, SSO), none of
  which the individual user needs. That is a product decision the design cannot
  make.

### 10.3 The license-agnostic rules adopted now

Binding from Phase 0 regardless of the eventual choice:

1. A dependency license ledger, maintained from the first commit. **No copyleft
   or source-available dependency in the required install.** Anything
   questionable is an optional extra.
2. No vendored third-party code without a provenance note. The BiDi client is
   spec-derived.
3. The `policy/` / `engine/` / `ops/` module boundary with a one-direction
   dependency, so the open-core seam exists whether or not it is ever used.
4. A CLA-shaped contribution process from the first external PR, since adding one
   later is far harder than having one unused.
5. No license text, badge, or claim in any file until the decision lands. The
   `LICENSE` file is a Phase 9 artifact.

---

## 11. Open questions for the author

Genuinely undecided, flagged rather than guessed. The spike phase resolves the
empirical ones; these need a ruling.

**Ruled questions keep their question text**, so the record shows what was asked
as well as what was decided, with the ruling recorded underneath. Two are ruled
as of 2026-09-05: **Q11 (names)** by the author on 2026-09-04, and **Q6 (browser
verbs)** under standing author delegation, flagged for author review and
reversible until ship. The rest are open, and PLAN's rulings checkpoint says
which phase each one blocks.

**A ruled question can reopen a narrower one, and Q11 did.** Building an engine
turns a naming ruling into an inventory, so Q11 now carries two sub-questions
(11a, the twelve environment variables Phase 1 added; 11b, the `manage_session`
lane string) recorded underneath the ruling that spawned them. Neither blocks a
phase and both are cheaper to rule on now than after the first release makes
them compatibility surface.

1. **The license.** Which of the three, and if open-core, where does the seam
   run given that the safety layer is the differentiator (Section 10.2c)?

2. **`take_screenshot` out of the lite core.** The design argues structured-first
   and makes the refusal the signpost to the `capture` pack. That is aggressive
   for a browser server and an agent hitting a canvas app on turn one will feel
   it. Ruling requested (Section 2.1).

3. **Chrome Lane C friction.** Chrome 136 means Lane C on Chrome always requires
   the user to relaunch Chrome with a non-default profile. Does Chrome Lane C
   ship in v1 anyway for market parity, or wait, given that Firefox Lane C is the
   actual differentiator and carries no such cost?

4. **The family's `enable_tools` conformance question.** Section 7.2 concludes
   the shipped runtime-toggle pattern cannot survive migration to MCP 2026-07-28,
   while remaining legal under the 2025-era revision the siblings negotiate
   today. KS4Web will not ship it. Do the shipped siblings change, stay, or wait
   for a spec clarification? This is a family-wide call, and it affects three live
   products. **Name the trigger when ruling: the siblings go non-conformant the
   day FastMCP bumps its advertised protocol revision to 2026-07-28, with no
   change to their own code.** So the watch item is a FastMCP release note, not a
   spec announcement, and the ruling should say what happens on that day (pin the
   FastMCP version, migrate the pattern to launch-time packs as KS4Web does, or
   accept the flag).

5. **Read-only by default?** Shipping with read-only ON by default, requiring an
   explicit flag to act, would be the strongest possible brand statement and the
   most differentiated default in the category. It would also surprise every user
   who expects a browser server to click things. Ruling requested.

6. **The browser verb extension** to the family naming grammar (Section 8.2).
   Approve `navigate` / `click` / `type` / `press` / `hover` / `scroll` / `wait`
   / `select` / `upload` / `download`, or force browser actions into the existing
   table?

   **RULED 2026-09-05, under standing author delegation. FLAGGED FOR AUTHOR
   REVIEW.** The browser-native verbs are approved. Where a domain has its own
   settled vocabulary, the family grammar takes that vocabulary rather than
   overwriting it: the principle the grammar actually enforces is
   **one name per concept**, not identical verbs across products. Forcing
   `set_` or `apply_` onto navigation would produce jargon nobody searches for
   and no browser user recognizes, which is the failure the grammar exists to
   prevent, not an example of it. The consistency the family gets is that
   `click` means clicking everywhere in KS4Web and nothing else does. This is
   reversible at zero cost until the first public release, so the author can
   overrule it any time before ship.

7. **Cross-family handoff scope.** Should `download` write into a directory
   KS4XL and KS4Word see by convention, and should `get_workflows` ship
   cross-server recipes? This is the one differentiator a single-purpose
   competitor structurally cannot copy, and it is also the one that couples three
   products together.

8. **Budget reset mechanism.** Gated through MRTR so a human answers, or terminal
   for the session with a restart required? The first is friendlier and the
   second is stricter.

9. **The dogfood commitment.** Lane C Firefox's entire value rests on the author
   being willing to run stock Firefox with `--remote-debugging-port` permanently
   on the daily profile, and on that being a thing we are comfortable
   recommending publicly given the stated posture (no auth, no encryption,
   anything local can drive it). Is that acceptable?

10. **v1 scope fence.** Is the pack list in Section 2.2 right, and does the
    `workflows` pack (replay) make v1 or v1.1?

11. **Names.** Package `kitchensink4web`, alias `web`, console scripts `web-mcp`
    and `kitchensink4web`, env `KS4WEB_MODE` / `KS4WEB_PACK_POLICY` /
    `KS4WEB_ALLOWED_ROOTS`. Confirm, especially `web` as an alias, which is
    generic in a way `xl` and `ppt` are not.

    **RULED by the author, 2026-09-04.** The product is **KitchenSink4Web
    (KS4Web)**, in the **Garden** department. The local registration alias is
    **`web`**, by family convention: the siblings register as `word` and `ppt`,
    the alias is what the author types in his own client, and breaking the
    pattern to dodge a genericity worry would cost more in muscle memory than it
    buys. **Genericity accepted**, knowingly, since the alias is a local
    registration name and not a package name or a market claim. The package,
    console scripts, and env prefixes stand as written.

    **11a. OPEN SUB-QUESTION, raised by Phase 1: the env-var inventory grew
    from three to fifteen and nobody ruled on the twelve.** The ruling above
    named `KS4WEB_MODE`, `KS4WEB_PACK_POLICY`, and `KS4WEB_ALLOWED_ROOTS`, and
    Phase 0 added `KS4WEB_READ_ONLY` as the environment form of `--read-only`.
    Phase 1 added twelve more as it built the engine, each one reasonable on its
    own and none of them reviewed as a set:

    | Variable | Governs | Default |
    |---|---|---|
    | `KS4WEB_LANE` | default lane when the call names none | `A` |
    | `KS4WEB_ENGINE` | bundled engine on Lane A | `chromium` |
    | `KS4WEB_CHANNEL` | installed channel on Lane B | `chrome` |
    | `KS4WEB_HEADLESS` | headed or headless launches | headless |
    | `KS4WEB_FIREFOX_PATH` | explicit Firefox binary for Lane B | discovered |
    | `KS4WEB_AUTO_INSTALL` | whether a missing browser installs on demand | on |
    | `KS4WEB_TIMEOUT_MS` | per-operation timeout | 30,000 |
    | `KS4WEB_IDLE_PARK_S` | idle park to `about:blank` | 300 |
    | `KS4WEB_IDLE_CLOSE_S` | idle context recycle | 1,800 |
    | `KS4WEB_PROFILE_ROOT` | where throwaway profiles are created | temp dir |
    | `KS4WEB_STATE_DIR` | where the owned-PID journal lives | state dir |
    | `KS4WEB_JOB_OBJECT` | the job-object backstop, for embedding | on |

    Three things need a ruling and none of them is urgent enough to block a
    phase. **Which of these are supported surface** and which are escape
    hatches that may change without notice, since a documented variable is a
    compatibility promise and twelve of them is a large promise to make by
    accident. **Whether the launch-shape four (`LANE`, `ENGINE`, `CHANNEL`,
    `HEADLESS`) should collapse into one `KS4WEB_LANE` string** matching the
    `lane` parameter in 11b below, which would take the inventory to nine and
    leave exactly one way to express a launch shape rather than two. And
    **whether `KS4WEB_JOB_OBJECT=0` belongs in public documentation at all**,
    given that it turns off a safety backstop and its only stated use is
    embedding KS4Web inside a larger process that owns its own job. The
    variables are recorded here rather than only in the code so the ruling has
    something to rule on.

    **11b. The `manage_session` lane string, RECORDED FOR RATIFICATION.**
    Phase 1 needed a way to express the launch shape and chose one parameter
    carrying the whole thing: `lane="A"`, `"A:firefox"`, `"B:chrome"`,
    `"B:msedge"`, `"B:moz-firefox"`, any of them with `"+headed"`. The
    alternative was four parameters (lane, engine, channel, headless), and the
    reason for the string is schema budget: four parameters on `manage_session`
    is roughly thirty tokens of schema on a tool whose whole job is lifecycle,
    and DESIGN 3.2's per-schema ceiling is tight enough that the flagship needs
    the room more. A typo refuses by naming every accepted form rather than
    downgrading to some other lane, which is the property that makes a
    stringly-typed parameter acceptable here at all. **This is a build decision
    standing in for an author ruling and it is reversible until ship**, in the
    same standing as Q6. The cost of the string is that it is not
    self-documenting in a schema the way named parameters are, and the
    docstring carries the whole grammar to compensate.

12. **Launch shape.** Own Show HN or a family launch? The research is blunt that
    the right thing does not win by itself, and that a Show HN escaping this exact
    problem already drew 189 points. The author's account handles the post; the
    build's job is to have a reproducible benchmark and an honest limitations page
    ready when it happens.

---

## 12. Marketing metric strategy (inherited, adapted)

1. **Headline metric is OPERATIONS, not tools.** "~120 browser operations,
   ~42 tools, deliberately consolidated." The low tool count is framed as
   engineering, never apologized for. Exact counts come from
   `scripts/measure_surface.py` and an operations counter, never hand-math.
2. **The token numbers are the second headline, and they must be reproducible.**
   Publish the harness, the pinned versions, the page set, and the tokenizer
   convention. The category is full of vendor multipliers with no methodology; a
   third party being able to re-run ours is the differentiator.

   **Publish the losing rows too.** The measured set includes pages where the
   projection is larger than the incumbent read: httpbin at 1.8x and
   example.com at 5.4x, both because the scaffold floor is 570 tokens and a
   trivial page cannot amortize it (Section 3.2). Those rows go in the
   published table with the reason stated. A benchmark that shows only wins is
   the kind of vendor multiplier this build exists to be distinguishable from,
   and the losing rows are cheap to defend: the same scaffold that costs 570
   tokens on a 46-node page is what caps a 574,200-token page at 3,683. The
   floor grew from 404 to 570 between S1 and the frozen re-measurement, so the
   losing rows got worse and they are still published, which is the whole
   point of writing the rule down before the number moved.

2a. **The one-read claim never ships without its companion clause** (Section
   1.1). Every public sentence about the cheap read pairs it with the cheap
   targeted follow-up, and the honest limit is stated in the same breath: an
   arbitrary in-prose link on a long article is not one-readable at any budget,
   and `find_elements` is what retrieves it for tens of tokens. Blind-trial
   result, for the record and for the copy: 11 ACT, 3 PARTIAL, 3 FAIL over 17
   tasks from the projection alone, with two of the three failures recovering
   through a cheap targeted call the agent named unprompted.
3. **Never publish a percentage without the methodology.** If any safety
   resistance figure is ever quoted, the test set, the date, and the model are
   named in the same breath. Anthropic's own three figures (23.6/11.2, 1 percent,
   under 0.08 percent) are the live example of how legitimate numbers from one
   vendor get misread as one series.
4. **Competitor comparison is a CAPABILITY MATRIX**, not count against count:

| Capability | KS4Web | playwright-mcp | chrome-devtools-mcp | charlotte | Skyvern |
|---|---|---|---|---|---|
| Cheap FIRST read of an unfamiliar page | yes | no (find needs the string) | no | partial | no |
| Cheap TARGETED follow-up after that read | yes | yes (`browser_find`) | no | partial | no |
| Hard budget with graceful degradation | yes | declined (#395/#889) | no (take_snapshot unbounded) | yes | partial |
| Sticky refs across re-reads | yes | no | yes (CDP-only) | no | no |
| Durable anchors that survive re-render | yes | partial (generate_locator) | no | no | no |
| Snapshot deltas | yes | no | no (#835 open) | yes | no |
| Server-level read-only mode | yes | no | no | no | no |
| Credential blindness at tool level | yes | partial (secrets redaction) | partial (header redaction) | no | no |
| Action budgets and loop detection | yes | no | no | no | no |
| Audit trail and replay | yes | no | no | no | no |
| Deterministic table extraction | yes | no | no | unclear | no |
| Download lifecycle | yes | declined ("very niche") | broken/open | no | partial |
| Bot-wall detection and honest handoff | yes | declined (#58) | declined (#553) | no | no |
| Verified action outcomes | yes | no | no | no | no |
| Local-first | yes | yes | yes | yes | platform-heavy |
| Office-family handoff | yes | no | no | no | no |

5. Standing copy rules unchanged: **no em dashes anywhere public**, no warranty
   or guarantee language, nominative trademark use only, non-affiliation
   disclaimer, "plus the kitchen sink" framing, nothing personal, and the
   safety-copy grammar of Section 5.

---

## 13. Known research conflicts carried into the build

Recorded here so a future session does not rediscover them. Full detail in the
PLAN's verification notes.

1. **Charlotte contradicts the "unserved" claim on two rows.** DEMAND Part One
   section 6 names Charlotte as shipping a snapshot differ and spill-to-disk;
   DEMAND Part Six's 21-server matrix omits Charlotte entirely and lists those
   rows as unserved. **Resolution: those rows are CONTESTED, not unserved.** Do
   not claim them as unclaimed ground anywhere public.
2. **Runtime versus launch-time gating.** MEASURED Target 1 and DEMAND both
   recommend runtime tier switching over launch-time flags. INCUMBENT 5.3
   establishes that the 2026-07-28 spec forbids it. **Resolution: Section 7.3.**
   This is the sharpest cross-report conflict in the record.
3. **Playwright's "policy commitment" framing needs qualifying.** The maintainer
   declined size limits on principle, and the codebase since shipped
   `browser_find`, `depth`, `target`, `filename`, and `--output-max-size`. The
   gap that remains open is the cheap FIRST read and the expensive default, not
   "no size controls at all." Overclaiming here is instantly checkable.
4. **Tool-definition token figures do not agree.** 4,024 (o200k_base), 4,637
   (chars/4), 11,717 (an HN claim), 14,400 (playwright-mcp #1290, a third of it
   descriptions). Different configurations and tokenizers. **Never publish a
   single number without naming the configuration**; reproduce the MEASURED
   methodology.
5. **Anthropic's three injection figures** (23.6 to 11.2, 1 percent, under 0.08
   percent) are different measurements from different dates and methodologies.
   Citing them as one series would be an error.
6. **`browser_snapshot`'s parameter set.** A source read shows `target`,
   `filename`, `depth`, `boxes`; a README read added `max_chars`. Trust the source
   read; confirm before citing `max_chars`.
7. **browser-use stealth marketing** is an unresolved discrepancy between an
   earlier README read and the docs site. Do not position against browser-use on
   that axis until resolved.
8. **Two citation traps.** playwright-mcp #1636 (24.6 GB OOM) and #1611 (Windows
   taskkill stdio pollution) were both **retracted by their own reporters as
   misattributions.** They look like excellent citations and are not.
9. **Close-state labels are unreliable and differ per repo.** playwright-mcp uses
   "completed" for outright refusals, browser-use closes aggressively regardless
   of resolution, chrome-devtools-mcp closes on ship. Read the maintainer comment,
   never the close state.
10. **playwright-mcp stopped accepting issues in June 2026** (#1664 is a pinned
    redirect). Its corpus is a closed historical record. Current demand reads from
    `microsoft/playwright` under the `playwright-mcp` label.
