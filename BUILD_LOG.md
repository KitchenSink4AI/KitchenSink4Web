# 🌿 KitchenSink4Web: The Build Log

**Author:** Nykolus Alvut (with Claude Code)
**Status:** DESIGN PHASE, review absorbed (BUILD-READY-WITH-EDITS, 15/15
applied). No code, no spikes run, no license chosen.
**Storefront department:** GARDEN, "browsing the great outdoors."

Private record (gitignored-class in spirit). The public repo, when it exists,
tells the sanitized version. Same voice as the Word, PPT, and XL build logs.

---

## Part I: the design phase (2026-09-04)

KS4Web is the fourth product in the family, after KitchenSink4Word (shipped,
v2.0.0), KitchenSink4PPT (shipped, v1.1.0), and KitchenSink4XL (four gates
green, beta pending). The browser is where the family's token thesis has its
largest measurable payoff and where its safety thesis has its most active
adversary, so it was always going to be the hardest and the loudest.

### The research round

Four parallel research agents on the evening of 2026-09-04, plus a banked token
measurement from earlier the same day. All five artifacts live in
`internal notes/` and are the permanent research record:

1. **`20260904_1918_browser_mcp_token_measurement.md`**: the number that
   anchors everything. One accessibility-tree snapshot of an ordinary Wikipedia
   article costs 156,347 tokens through playwright-mcp 0.0.80 and 177,168
   through chrome-devtools-mcp 1.8.0. That is 78 to 89 percent of a
   200,000-token window on one page. Measured on this machine, against the
   published packages, over raw JSON-RPC. Also produced the design targets:
   lite tier under 1,500 tokens, a page view under 5,000 regardless of page
   size, and every read returning actionable refs.
2. **`20260904_2113_ks4web_capability_demand.md`**: the capability landscape,
   the demand mining, eight landmines, the unserved-row matrix across 21
   servers, community sentiment, and the licensing column. The report that
   found the sharpest strategic conclusion available: the gap is not a
   capability gap, it is a licensing-and-deployment gap.
3. **`20260904_2114_ks4web_incumbent_study.md`**: the architecture study.
   Source-read where public. What each incumbent bet on, what it genuinely does
   well, where it is weak, and the five openings. Also the platform-constraints
   section, which is the most operationally important part of the whole record
   because several obvious designs turn out to be illegal under MCP 2026-07-28.
4. **`20260904_2134_ks4web_engine_analysis.md`**: the engine decision.
   playwright-python async, three lanes, and the finding that made Lane C
   interesting: Playwright ships undocumented `moz-firefox` channels driving
   stock Firefox over WebDriver BiDi, and Mozilla, unlike Chrome, places no
   restriction on enabling the remote agent against the default profile.
5. **`20260904_2134_ks4web_safety_landscape.md`**: the threat landscape, the
   incumbent safety coverage, eight candidate pillars with a differentiator
   judgment on each, and the marketing cautions. Four pillars came back unserved
   by every incumbent surveyed.

Nothing was posted, commented, or written to any remote in any of the four
rounds.

### What the design settled

**Positioning.** The flagship is the cheap FIRST read. Every incumbent has a
cheap second read (playwright-mcp's `browser_find`, Claude in Chrome's `find`)
and all of them share one precondition: the model must already know what string
to search for. Nobody has a cheap first read of an unfamiliar page. That is a
narrow enough claim to be true, and it is the one the incumbent has argued
itself out of on the record three separate times, most recently with "we are
optimizing for a 1M context window size at this point."

**Engine.** One engine, three lanes. playwright-python async (forced, not
chosen: FastMCP handlers run inside an asyncio loop and the sync API refuses to
run there). Lane A bundled and default, Lane B branded and flag-gated including
the `moz-firefox` dogfood path, Lane C live attach with a thin in-house BiDi
client for Firefox. The hard rule that came out of the engine report: **never
touch the user's real browser profile**, because Playwright's
`prepareUserDataDir` overwrites `user.js` wholesale on every launch and Firefox
holds an exclusive profile lock anyway. Seeded copies only.

**Safety.** Four unserved pillars lead: server-level read-only mode, credential
blindness at the tool level, action budgets with loop detection, and an audit
trail with replay. Plus the TOCTOU rule that binds every gate in the system: the
confirmation re-validates the target element at execution time, not just at
reasoning time.

**The spec constraint that killed the obvious design.** MCP revision 2026-07-28
states the tool set "MUST NOT vary per-connection or as a side effect of other
requests on the connection." The family's shipped `enable_tools` pattern, which
flips packs on mid-session using session-scoped visibility and a `list_changed`
notification, does both of those things. Assessment recorded in DESIGN 7.2, and
stated precisely after the design review: the family pattern **cannot survive
migration to 2026-07-28**, while remaining legal under the 2025-era revision
FastMCP negotiates today, so nothing shipped is non-conformant right now and the
trigger is a FastMCP version bump rather than any decision of ours. KS4Web will
not ship the pattern regardless, and instead tiers through launch-time packs plus
the client's own
progressive-disclosure machinery (`anthropic/alwaysLoad`, `anthropic/searchHint`)
plus in-tool parameters. Whether the three shipped siblings change is a
family-wide call flagged for the author.

That constraint also has a happy consequence. The strongest safety
differentiator, read-only mode with no mutating tools registered at all, is only
conformant as a launch-time property, which is also exactly what makes it a
provable property rather than a claim.

**The anchor scheme.** Two addresses per element: a cheap turn-local `ref` the
model sees, and a durable content-derived `anchor` the server keeps. The element
map is keyed by fingerprint rather than by snapshot, so an unchanged element
keeps its ref across re-reads. chrome-devtools-mcp proved the property is
achievable with `loaderId_backendNodeId` sticky uids; KS4Web has to reach it
without CDP because two of three lanes are not CDP, and has to survive React
re-renders, which backend node ids do not. Deltas fall out of the same design,
and deltas were the single most-demanded unshipped primitive in the whole
research corpus.

### The uncomfortable finding, recorded honestly

`TickTockBent/charlotte` independently arrived at nearly this exact design
(token-efficient structured snapshots, loadable profiles, spill-to-disk, a
snapshot differ), publishes 10x to 140x multipliers, and has 178 stars against
playwright-mcp's 36,788 seven months in. The most capable maintained
Puppeteer-family server in existence has 48 stars. **Building the right thing is
necessary and demonstrably not sufficient.** That is why distribution and proof
are a first-class parallel workstream in the plan rather than a Phase 9
afterthought, and why the benchmark has to be reproducible by a stranger rather
than merely published.

### What is deliberately not being built

Anti-detection and CAPTCHA solving (conflicts with the identity, and it is what
gets professional users' accounts terminated). A browser extension (second
toolchain, store review, permanent infobar, and structurally Chrome-only since
Firefox does not implement `chrome.debugger`). Raw CDP as an engine. Lighthouse
and performance tracing (a funded Chrome team owns that row). An agent loop
(browser-use's best ideas are client-side and structurally unavailable to an MCP
server, and saying so is better than pretending). Vision-first interaction.
Per-click permission prompts.

### License

**DEFERRED, by author ruling.** The architecture is written license-agnostic and
nothing in it depends on the choice. DESIGN Section 10 states what each of the
three options would require structurally, so the later decision is a swap rather
than a redesign, and three rules are adopted now regardless: a dependency
license ledger with no copyleft in the required install, spec-derived rather
than lifted third-party code (the BiDi client is written from the W3C spec even
though Playwright's Apache-2.0 sources would be legally fine), and a
`policy/` / `engine/` / `ops/` module boundary with a one-direction dependency
enforced by a test, so an open-core seam exists whether or not it is ever used.

### Status at the end of the design phase

- `DESIGN.md` and `PLAN.md` written, covering positioning, the tool surface by
  pack, the cheap-first-read design in depth, engine lanes and profile safety,
  the eight safety pillars as concrete tool behavior, the conformant tiering
  mechanism, the error vocabulary, the location object, the do-not-build list,
  the license section, and twelve open questions for the author.
- Ten spikes defined with explicit kill or fallback criteria, sequenced so the
  product thesis is tested before any delivery mechanism is.
- Ten phases with hard gates, three adversarial rounds, a seven-item
  distribution and proof workstream, and an explicit v1 scope fence.
- Ten research conflicts recorded in DESIGN Section 13 so a future session does
  not rediscover them, including two citation traps and one genuine
  contradiction between reports on runtime versus launch-time tiering.
- No code. No spikes run. No license. Nothing published anywhere.

**Next:** author review of DESIGN and PLAN, rulings on the twelve open
questions, then the spike phase. S1, the projection proof, decides whether the
flagship claim survives contact with a real page, and nothing gets built until
it reports.

---

## Part II: the design review, absorbed (2026-09-05 00:31 KST)

A Fable-tier adversarial review of DESIGN and PLAN at commit `2b0a948`, run as
verification rather than style critique: the MCP 2026-07-28 spec fetched live,
the installed Claude Code binary (v2.1.220, not the v2.1.92 the research was
built against) grepped directly, the Playwright source tree, the Chromium
developer blog, and Mozilla's source docs all checked against the load-bearing
claims. Report:
`internal notes/20260905_ks4web_design_review.md`.

**VERDICT: BUILD-READY-WITH-EDITS.** No design pillar was invalidated. The spec
quote is verbatim-correct, all five engine-lane facts hold against primary
sources, and the client-behavior facts came back four-for-five, with the fifth
being a sourcing error rather than a false belief. **All fifteen proposed edits
(E1 through E15) are applied.**

**The two genuine specification gaps**, both in the flagship subsystems and both
closed before the Phase 2 freeze rather than after it:

- **The rung-5 floor was not bounded.** The degradation ladder called its floor
  "structurally impossible" to overflow while that floor enumerated every field
  of every form, which a real airline booking page or a 500-field settings screen
  makes arbitrarily large. Rung 5 now caps its own inventories and the claim is
  true instead of hopeful.
- **Mid-batch rebind semantics were undefined.** `fill_form` is a batch, and
  typing into field one routinely re-renders its siblings on any React form, so a
  fingerprint change partway through a batch is the ORDINARY case, not a corner.
  The sibling pattern (validate every anchor, then execute) does not survive
  mutations the batch itself causes, and browser actions do not roll back. DESIGN
  3.5 now defines resolve-all-then-recheck-each, stop-on-refusal, completed items
  stay completed, remainder reported `not_attempted`. Round A was already
  scheduled to test batch behavior that no document defined.

**The correction worth remembering.** The 3,000-token subagent result cap was
recorded as verified from the Claude Code binary. It is not: no such constant
exists in v2.1.220 near that path, the issue (#75267) is a field report, and the
value almost certainly arrives through the same remote feature gate that carries
the 25,000-token limit. The misattribution began in the research and the design
inherited it. The `budget_tokens=2500` subagent recipe survives, relabeled as
tracking a MOVABLE limit that S8 measures rather than a constant to trust.

Also landed: the sibling-conformance framing tightened to per-negotiated-revision
with the FastMCP version bump named as the trigger (nothing shipped is
retroactively non-conformant); the `server/discover` MUST added to S8 as a
FastMCP question; the rebind ladder's entry conditions enumerated ahead of its
five outcomes; anchor-id exposure and delta-token retention stated; the token
estimator named (`tiktoken`, `o200k_base`, 10 percent margin) so the hard-cap
property is checkable; S4 given an objective demotion threshold in place of "does
it gut the surface"; corpus construction scheduled before S1 and S2 instead of
assumed; a latency gate added, since token-cheap and wall-clock-expensive is the
same user pain by another route and the hidden-content normalizer is
per-node-style-hungry; the S1 blind trial given a protocol; and Edge added to the
S9 probe, since Edge inheriting Chrome 136's default-profile restriction was
community-reported and would otherwise have shipped as an untested assumption.

### Two rulings recorded

**Q11, names. RULED by the author, 2026-09-04.** Product is KitchenSink4Web
(KS4Web), Garden department. Local registration alias `web`, by family
convention, since the siblings register as `word` and `ppt` and the alias is what
the author types in his own client. Genericity accepted knowingly: it is a local
registration name, not a package name or a market claim.

**Q6, browser verbs. RULED under standing author delegation, flagged for author
review.** Browser-native verbs (`navigate`, `click`, `type`, and the rest) are
correct where the domain demands them. The family grammar's principle is
one-name-per-concept, not identical verbs across products, and forcing `set_` or
`apply_` onto navigation would produce jargon nobody searches for. Reversible at
zero cost until ship.

The remaining ten questions are unruled, and PLAN now carries a **rulings
checkpoint** between the spike gate and Phase 0 saying which phase each one
blocks: Q2 and Q5 before Phases 3 and 7, Q10 before Phase 6, Q9 before S5 effort
is spent, Q3 before S9's scope is set, Q1 decoupled. The scope fence's claim that
the workflows pack drops "because nothing depends on it" is corrected: no CODE
depends on it, but DESIGN 6.8, DESIGN 5.6, and the Section 12 capability matrix
row all do, so dropping Phase 6 edits the matrix and the safety copy in the same
commit.

**Status unchanged otherwise:** no code, no spikes run, no license, nothing
published. `spikes/s1/` holds an environment prep venv and is untracked. Next is
still author review and the remaining rulings, then S1.

---

## Part III: Spike S1 absorbed (2026-09-05)

**S1 ran, and the thesis survived contact.** Report:
`internal notes/20260905_ks4web_spike_s1.md`. Verdict
**VALIDATED-WITH-CAVEATS**. Eleven pages, six blind agents, seventeen tasks.
Versailles projects to **3,726 tokens** against a 106,088-token accessibility
snapshot taken on the same machine, and that 28.5x is the conservative number
because our baseline lacks the per-node ref annotations playwright-mcp actually
emits (the banked figure through playwright-mcp itself is 156,347). Raw inputs
spanning a factor of 11,000 in size projected into a band spanning a factor of 9.
The property the whole design rests on is real.

**Neither kill criterion tripped**, and the reason one of them did not is the
most useful thing the spike found. The worst blind-agent failure was on a GitHub
repo page, where an agent asked to open the Issues list could not name a call
because all thirteen repository tabs had been buried under truncated commit
messages. That happened with **2,762 of 5,000 tokens unused**. The ranker threw
away the answer while comfortably under budget, which means it was never a
budget problem and no budget increase would have fixed it.

### What changed in the design

Six edits, each traceable to a specific blind-agent quote rather than to taste.

**1. Affordance ranking is now quota-based by class** (DESIGN 3.3 block 3).
Guaranteed floors for navigation and form controls, a high quota for primary
actions, and **a quota of zero for in-prose links inside a readable region**.
The zero quota removes roughly 2,700 of Versailles' 2,858 affordances and costs
nothing, since no agent was going to find its link inside a forty-item sample of
2,858. Hrefs are printed (the prototype extracted them and threw them away, and
an agent on CNN could not confirm that "Business" was a link rather than a menu
toggle). Duplicate labels are disambiguated (`e13` and `e42` both came back as
"Search (x2)" in the same region, and a pair labeled "Apache-2.0 license (x2)"
was listed out of numeric order, so the collapse was not even positional). The
GitHub Issues-tab failure is cited in the design as the motivating case.

Also measured, and it retires an assumption: the interactive-to-total node ratio
runs 2.0 to 28.3 percent, median 9.0. The design's 10-to-14-percent assumption
holds for app pages and fails for articles, and it fails because of exactly the
class that now has quota zero.

**2. Every printed price must be a real price** (new DESIGN 3.3a, the
cost-estimation contract). Three lies, all caught by blind agents unprompted.
Per-heading costs read `~10 tok` on nearly every heading because the walk used
`nextElementSibling`, which finds nothing on any site that wraps sections in
containers; an agent wrote that *"the one number an agent most needs, the price
of reading a named section, is the number the projection does not give."* The
`main` region was priced as the sum of every other region, so the single most
expensive and least useful call on the page sat at the top of NEXT CALLS. And
`0 regions not expanded` printed while thirty regions carried expand costs.

The fix is structural rather than three bug fixes. **A printed price and an
enforced budget come from the same arithmetic, in the same pass, over the same
units**, and the completeness block computes nothing at all: it renders the
ledger the budget meter already kept while enforcing the budget. That is what
makes the three lies impossible by construction rather than merely fixed, and
Phase 2 tests it by issuing every advertised call and comparing.

**3. Accessible names are computed, not scraped** (new DESIGN 3.7). The
prototype used `textContent` and labeled GitHub's entire main region **`"Uh
oh!"`** off a stray non-rendering error element, on a page returning HTTP 200
whose main region held the file listing, the README, and the sidebar. A blind
agent said an agent triaging by region label would "either panic or skip the only
region that matters." Same defect produced `General4`, `Data Entry18`, and an
entire menu concatenated and cut mid-word. Requirement: the W3C accname
algorithm or the driver's computed names, word-boundary truncation with an
explicit ellipsis, and `(unnamed)` plus a stable attribute rather than a CSS
class. The lead-paragraph gate goes the same way: it took the first long `<p>`
anywhere and returned CNN's DRM error string as the page's opening content.

**4. The ~390-token scaffold floor replaces the sub-300 target** (DESIGN 3.2).
example.com, one link, projects to 404. Three hundred tokens does not buy a
completeness block and a continuation protocol, so the old httpbin target was
asking the design to drop the two blocks that make it honest. httpbin is now
under 900 (measured 758) and the GDP target splits into structure and row page
priced as separate calls, since structure alone measured 2,854 of a 3,000 budget
that was also supposed to hold a row page. **Both losing rows get published with
their reason**, because the same scaffold that costs 390 tokens on a 46-node
page is what caps a 574,200-token page at 3,726.

**5. Positioning gains a companion clause, everywhere** (DESIGN 1.1, 3.1, 12
rule 2a; PLAN success metric and W3). The HARDER GATE came back SPLIT: the blind
agent did not ask for a second full read and did name a cheap route, so it passed
the letter, and it could not click the Fourteen Points link from the projection,
so it failed the intent. The honest reading is that a first read cannot carry
2,858 in-prose links and no budget changes that, because it is a category error
rather than a shortfall. So the claim is **cheap first read PLUS cheap targeted
follow-up**, with the limit stated in the same breath. "One read and you can act
on anything" is banned copy. Select and combobox options are recorded as the
known forced-second-read case, with a Phase 2 TODO for option inlining under a
size cap, since that was the only trial failure whose recovery cost more than the
first read.

**6. Ladder requirements from measurement** (DESIGN 3.4). Monotonicity, because
httpbin got BIGGER at rung 4 when the digest switched from a lead line to a
heading list. Finer and less correlated rungs, because a 2,500 budget on
Versailles skipped from 3,711 straight to 2,182, dropping 22 regions and the
whole lead when a smaller step would have fit. A content-aware floor, because the
prototype's floor kept every table row-count while dropping the digest, which on
an article is backwards. And the E-round's uncapped-floor fix was confirmed
empirically: the prototype refused Versailles at a 1,500 budget and refused eight
of eleven pages at 900.

Banked and worth repeating: **at the 5,000-token default the ladder never
engaged on any page in the set**, and at `budget_tokens=2500` every page landed
under budget unmutilated, so the subagent recipe is real.

### What the completeness block earned

Worth recording because it is the block that costs the least and was defended the
hardest. On the largest page in the set, the completeness block and the
continuation protocol together cost 370 tokens of 3,716, and a blind agent picked
the completeness block out unprompted as "the strongest part of the document,"
singling out `shadow roots: 0 open (traversed=no), 0 closed (unreachable by any
tool)` for separating "I did not look" from "no one can look" where most tools
collapse both into a confident zero. It also changed the agent's behavior, which
is the actual test: the agent said it would run `find_elements` before reporting
that the page lacked a control. **Honesty cost 370 tokens.** The field list grew
by seven entries (unlisted affordances by suppressing quota, omitted form fields
and forms, omitted tables and headings, regions listed but not expanded as
distinct from dropped, blocks omitted entirely, auth state, and a name-quality
flag), and the two-layer shadow-root phrasing is kept verbatim on that evidence.

### Plan changes

S1 is marked **DONE / VALIDATED-WITH-CAVEATS** with its gate table. The Phase 2
gate grew from five parts to nine: the four new parts are affordance quotas on
the adversarial cases, price accuracy tested by issuing every advertised call,
the completeness block proven derived rather than recomputed, and accname
correctness against fixtures built from S1's own failures. Each of the four is a
defect a blind agent caught while the projection was under budget, which is the
class a token-only gate does not see.

**One S1 obligation is transferred, not discharged. E11, the latency
measurement, moves to the engine-spike round now running.** S1 reported no
wall-clock table, and Phase 2's gate part 5 asserts against a bound that
measurement was supposed to set, so Phase 2 does not open until the engine round
reports it. A gate asserting against an unset number is not a gate.

Two smaller honesty items recorded rather than smoothed over. S1 counted with
`tiktoken` `cl100k_base` while this build's fixed convention is `o200k_base`, so
**no S1 figure is publishable as-is** and the Phase 2 harness re-measures. And
corpus A was never frozen before S1 as the plan required; S1 ran live and froze
its extraction outputs afterward, so the ladder numbers re-derive offline and the
per-page numbers do not. Corpus A is still owed before the Phase 2 harness.

**Status:** design updated, S1 green, S2 not run, engine spike running, no
production code yet, no license, nothing published.

---
