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
under five thousand tokens and hands back references you can act on.**

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

Two rows genuinely contested rather than unserved, and the design must not
claim them: snapshot deltas and spill-to-disk are both shipped by Charlotte
(`src/state/differ.ts`, `output_file`), and the delta idea is independently
endorsed by a chrome-devtools-mcp maintainer in #835. KS4Web builds both
because they are correct, not because they are unclaimed.

### 3.2 The targets, from the banked measurement

| Read | Incumbents | KS4Web target | Multiple |
|---|---|---|---|
| Tool-schema bill (lite) | 4,637 / 6,460 | **under 1,500** | 3.1x / 4.3x |
| Full-surface ceiling | n/a | under 4,000 | undercuts the incumbent DEFAULT |
| Largest single schema | 413 / 459 | under 250 | |
| Article page (Wikipedia, Treaty of Versailles) | 156,347 / 177,168 | **under 5,000, regardless of page size** | 31x to 35x |
| Data-table page (GDP nominal) | 66,146 / 64,635 | under 3,000 for structure plus first row page | 22x |
| Form page (httpbin) | 440 / 314 | under 300, and hold it on a real app form where incumbents balloon with shell chrome | |
| Minimal page (example.com) | 105 / 90 | parity, do not chase | |

MEASURED is explicit that a 3-5x beat is the wrong ambition here: 156,347
divided by 5 is still 31,269 tokens, which still ruins a session after six
pages. The honest target is a hard cap with paging, stated as a property rather
than a hope: **a page view never exceeds its budget regardless of page size.**

One platform constraint shapes the default. INCUMBENT verified from the Claude
Code binary that there is an undocumented **3,000-token cap on tool results
inside subagents** (claude-code #75267). Since "delegate the page read to a
subagent" is the exact mitigation playwright-mcp's maintainer recommends, the
default 5,000-token budget would fail inside the very workaround people use.
`get_page_view` therefore takes `budget_tokens`, documents 2,500 as the
subagent-safe setting, and `get_workflows` ships that recipe.

### 3.3 What a page view returns

`get_page_view` returns an ORIENTATION, not a transcript. Eight blocks, built
in priority order, measured as they are built.

**1. Identity.** Final URL after redirects, title, HTTP status, load state,
engine lane, page handle, read token (for deltas), and a timestamp.

**2. Page shape.** Landmark regions (header, nav, main, aside, footer, dialog,
form, plus unlabeled major containers) each carrying a ref, a one-line label,
counts of interactive elements and text blocks and images, and **an estimated
token cost to expand.** The regions are a menu with prices, so the model can
budget instead of guess. Nothing in the field does this.

**3. Affordances.** The ranked interactive surface: `ref | role | accessible
name | state`. Ranking is in-viewport first, then main-or-dialog landmark, then
size and semantic weight (submit buttons, primary nav). Capped at N with an
exact count of what was omitted and the call that gets the rest. The community
measurement KS4Web is designing against is roughly 62 to 93 accessibility nodes
per view of which about 9 are interactive, and the incumbent line counts are
consistent with that ratio, which is the entire reason this fits in a few
hundred tokens.

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

**8. The continuation protocol, taught inside the payload.** The reference MCP
fetch server's idiom, stolen outright because it is the best idea in the
extractor field:

> `<error>Content truncated. Call the fetch tool with a start_index of
> {next_start} to get more content.</error>`

The tool teaches the model its own continuation protocol in the result. No
extra schema, no documentation dependency. KS4Web's version names the exact
next call for each unexpanded region, each unread table, each untraversed
frame.

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
budget. If even rung 5 exceeded budget, which should be structurally
impossible, the tool refuses with the size and the three cheaper routes rather
than returning a mutilated tree.

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

Three caveats, all real. The channel is **not in the public docs**
(`docs/src/browsers.md` never mentions it), so it can move. It rides Playwright's
BiDi backend, which is experimental with a documented hole list (no request or
response bodies, no `resourceType`, no locale or timezone emulation, no content
quads so clicks inside CSS-transformed elements are inaccurate, plus
Firefox-specific bugs: `browsingContext.downloadWillBegin` not firing,
`network.continueWithAuth` failing, header overrides failing on redirects).
And version skew becomes the user's problem, since whatever Firefox they have
installed is what gets driven.

**Everything in Lane B Firefox is contingent on Spike 1.** If stock Firefox does
not drive on this machine, Lane B Firefox degrades to bundled-only and the
dogfood premise for Firefox dies. The plan sequences that spike before anything
depends on it.

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

### 4.6 Profile safety: the hard rule

**KS4Web never opens the user's real browser profile. Not read-write, not
read-only, not "just once."**

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
So gates are a **retry pattern, not a callback.** KS4Web implements MRTR first,
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
an argument on subsequent calls." Connection-scoped browser state is no longer
conformant, which is why `manage_tabs` and `manage_session` mint and return
explicit page and session handles that every other tool accepts.

### 7.2 Re-examining the family's `enable_tools` pattern, as instructed

The family pattern, read from the shipped word-mcp `packs.py`: every tool is
registered with FastMCP up front, non-lite tools start disabled, and
`enable_tools` flips packs on mid-session using **session-scoped**
`ctx.enable_components` / `disable_components`, which "send
ToolListChangedNotification to the session only."

Measured against the spec text, that does both forbidden things. The tool set
varies **per connection** (the toggle is session-scoped by design, so two
concurrent clients see different sets) and it varies **as a side effect of
another request on the connection** (the `enable_tools` call is that request).
The "MAY vary by the authorization presented" carve-out does not apply, because a
local stdio server presents no authorization and the variation is driven by a
tool call rather than by credentials.

**Assessment: the family's runtime enable_tools pattern is not conformant with
MCP 2026-07-28.** It was conformant, or at least unaddressed, under the revisions
it was designed against. KS4Web will not ship it. Whether the shipped siblings
change, stay, or wait for a spec clarification is a family-wide decision above
this document's pay grade and is Open Question 4.

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
(verified from binary v2.1.92): `anthropic/alwaysLoad` (boolean, exempts a tool
from deferral so it is always in context) and `anthropic/searchHint` (string,
extra text indexed for tool-search matching). Tool search engages by default once
definitions exceed roughly 10 percent of the context budget.

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
**2,048 characters** by the client, silently. The default tool-result limit is
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
   the shipped runtime-toggle pattern is not conformant with MCP 2026-07-28.
   KS4Web will not ship it. Do the shipped siblings change, stay, or wait for a
   spec clarification? This is a family-wide call, and it affects three live
   products.

5. **Read-only by default?** Shipping with read-only ON by default, requiring an
   explicit flag to act, would be the strongest possible brand statement and the
   most differentiated default in the category. It would also surprise every user
   who expects a browser server to click things. Ruling requested.

6. **The browser verb extension** to the family naming grammar (Section 8.2).
   Approve `navigate` / `click` / `type` / `press` / `hover` / `scroll` / `wait`
   / `select` / `upload` / `download`, or force browser actions into the existing
   table?

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
3. **Never publish a percentage without the methodology.** If any safety
   resistance figure is ever quoted, the test set, the date, and the model are
   named in the same breath. Anthropic's own three figures (23.6/11.2, 1 percent,
   under 0.08 percent) are the live example of how legitimate numbers from one
   vendor get misread as one series.
4. **Competitor comparison is a CAPABILITY MATRIX**, not count against count:

| Capability | KS4Web | playwright-mcp | chrome-devtools-mcp | charlotte | Skyvern |
|---|---|---|---|---|---|
| Cheap FIRST read of an unfamiliar page | yes | no (find needs the string) | no | partial | no |
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
