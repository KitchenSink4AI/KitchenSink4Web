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

## Part IV: the engine spikes absorbed (2026-09-05)

S3, S4, S7's Windows slice, and the latency measurement S1 owed all ran on the
`spike-engine` branch. Report:
`internal notes/20260905_ks4web_engine_spikes.md`. **Every
one holds.** The engine round found no kill and no demotion, refuted more of
the design's own pessimism than it confirmed, and produced one safety line that
is now a constant rather than a default.

### The safety line, first, because it is the most important thing here

**Playwright's `BidiFirefox.defaultArgs` does not pass `-no-remote`.** Its own
Juggler Firefox path does. Without it, a Firefox launch can be adopted by an
instance the user is already running, regardless of what profile directory was
named. The whole profile-safety section was written to keep KS4Web out of the
author's browser, and it turns out a fresh profile directory alone does not
deliver that on this lane. **KS4Web now supplies `-no-remote` on every Firefox
launch, on every lane, in every mode, with no flag to disable it** (DESIGN 4.3
and 4.6, and a Phase 1 acceptance item rather than Phase 4 polish). The spike
ran under it throughout and never touched the author's open Firefox.

### S3: moz-firefox holds, and it is not even flag-gated

The channel is present and shipping in playwright-python 1.62.0 with no
environment variable and no experimental opt-in: the driver registers the three
`moz-` channels and routes any of them to the `BidiFirefox` browser type. It
launched the installed Firefox 154.0.1 from Program Files (confirmed twice, by
process `ExecutablePath` and by an `rv:154.0` user agent), then drove it
through navigation, clicks, a filled form, a select, a checkbox, a JS handler,
an aria snapshot, a screenshot, and a real POST round trip, headless and
headed. 18 of 20 steps green. **The Lane B Firefox dogfood premise survives
and the `executable_path` fallback was never needed.**

Of the two failures, one became a design edit: `about:support` is refused by
BiDi outright, so **provenance never comes from an `about:` page**. It comes
from the process table and the UA string, which is what the spike used. Any
future version banner or `about:config` read is unavailable on this lane.

### S4: the research was stale, and two of three gaps do not exist

This is the round's biggest correction and it runs in the pleasant direction.
Twenty probes on both lanes against a local fixture server, with Chromium as a
control that passed every one, so each Firefox row is a genuine lane difference
rather than a broken probe.

**Refuted:** response bodies work, downloads work, HTTP auth works. Also
working against what the design assumed: header overrides survive a 302, clicks
land inside a `rotate(37deg) scale(1.6)` element, and locale plus timezone
emulation both apply. The design had been carrying a hole list quoted from an
older state of the backend, and DESIGN 4.5a now carries a measured one.

**Confirmed, and reshaped:** request body READS return `None` with no exception
raised, while `content-length: 24` proves the body is there. Writing a body
works. So the honest capability row is "request bodies: write yes, read no,"
which is a more useful sentence than the one it replaces.

**New, and worse than the one it joins:** `go_back` and `go_forward` time out,
**and the navigation actually happens**. The DOM is the previous page while
`page.url` still reports the old one. In-page `history.back()` shows the same
stale URL, so this is BiDi URL tracking rather than a `go_back()` wiring bug.
A driver that reports a lie is a harder problem than one that reports nothing,
and it produced a standing rule: **`page.url` is never trusted after a history
traversal on Firefox/BiDi.**

Neither gap is lite core, so **the Firefox lanes do not demote to read-mostly**
under S4's own threshold. They carry two `LANE_UNSUPPORTED` rows, both drafted
as product text in DESIGN 4.5a, and both are LOUD REFUSALS at the KS4Web layer
precisely because the driver fails silently at both.

One surprise recorded as a COST rather than a gap: `page.pdf()` works on
Firefox/BiDi, which nobody expected, at 8.7 seconds against Chromium's 0.2. An
operation that works slowly is a different fact from one that does not work,
and no new error code was added for it. The closed vocabulary stays closed.

### S7: zero orphans, and a confound that changes how we test

Ten scenarios across both lanes including the harshest available, server and
Node driver both hard-killed. **Zero orphans every time**, full reap in 2.0 to
3.5 seconds, Chromium at 4 processes per session and moz-firefox at 10 or 11.

The confound is the interesting part. The spike process was itself inside a
Windows job object with `KILL_ON_JOB_CLOSE`, inherited from the harness shell,
and children inherit it, which would have made every green result the harness's
doing rather than Playwright's. Re-running the harshest scenario with
`CREATE_BREAKAWAY_FROM_JOB` granted still reaped cleanly, so the death pipe is
genuinely doing the work. **The consequence is a Phase 1 gate requirement: the
orphan test must break away from the ambient job or it proves nothing.** A gate
that silently cannot fail is worse than no gate, and this one silently could
not.

Three mechanics banked so Phase 1 does not rediscover them. Job objects work
from plain CPython ctypes, **with the trap that HANDLE restypes must be
`c_void_p` or every call fails with `ERROR_INVALID_HANDLE` and the reaper
silently does nothing**, which is the worst failure mode a safety mechanism can
have because it passes any test that merely checks the reaper exists. Child-PID
enumeration via `Get-CimInstance Win32_Process` costs about 1.0 s for 557
processes, so it is shutdown-and-sweep speed and never hot-path speed. And
Playwright's Python API does not expose the browser PID at all, so the
owned-PID journal is populated from the process table or from a job KS4Web
owns, which was previously an assumption.

### The latency gate, set from measurement

E11 transferred from S1 and discharged here. Against the unmodified S1
projector, ten runs per fixture, with a synthetic ladder bracketing the
50,000-node fixture the S1 corpus never reached: **341 ms p95 at 50,000
nodes**, under 0.9 s at 100,000, 241 ms on Versailles. The design's stated
worry was the hidden-content normalizer, since contrast and position and font
size all imply per-node style computation. **That worry is retired with a
number:** the full sweep is 64 ms of a 288 ms extract, roughly 22 percent, and
restricting it to interactive candidates would buy 14 percent while losing
hidden-content detection on every non-interactive node. **The normalizer sweeps
everything in Phase 2**, which also removes a completeness field the design was
preparing to need (a normalizer cap it will never have to report).

Phase 2's budget: projection p95 at or under 500 ms to 50,000 nodes, at or
under 1.0 s to 100,000, Python assembly at or under 10 ms.

And the finding that reframes the user-facing story: **cold navigation with a
`networkidle` settle cost 12.8 seconds on cnn.com against a 90 ms projection on
the same page.** Page load dominates wall-clock and we do not. Any latency
story KS4Web tells is a story about load-state policy, not about the
projection, and selling a projection optimization the user cannot feel would be
the wrong pitch.

### What did not run, and why it matters

**S5 and S6 are DEFERRED BY SAFETY, not descoped.** Both need the author's real
Firefox: S5 attaches to a user-launched instance, S6 copies from a real
profile. The author's Firefox was open, the standing rule is that agent rounds
never attach to the live daily browser, and the spike stopped rather than
making an exception for itself. They run at the next Firefox-closed window.
Until then **the Lane C Firefox differentiator stays UNVERIFIED**, which is the
one capability no competing MCP server has, so it stays out of public copy too.
Q9 should be ruled before that effort is spent.

**Status:** S1, S3, S4, and S7's Windows slice green. S2 is now the only thing
between here and the spike gate. S5 and S6 wait on a closed browser. No license,
nothing published.

---

## Part V: Phase 0, scaffold and ports (2026-09-05)

**GATE GREEN. 81 tests, all passing. No browser code, no license file, nothing
published.** First code in the repo that is not a throwaway spike.

### What landed

`pyproject.toml` (`kitchensink4web`, src layout, Python >= 3.12, console scripts
`web-mcp` and `kitchensink4web`, **no license field and no LICENSE file** per
DESIGN 10.3 rule 5), the three-package boundary, the envelope, the policy ports,
the lite roster as stubs, 81 tests, `scripts/measure_surface.py`, `glama.json`,
`DEPENDENCY_LEDGER.md`, and CI on `checkout@v7` plus `setup-python@v7`.

**The envelope carries the browser vocabulary**, twenty codes: the eight
inherited from the document family plus the twelve browser additions from
DESIGN 8.3. Three tests do the load-bearing work. One asserts the vocabulary
matches a literal transcription of the design rather than agreeing with itself.
One asserts `HINTS` is TOTAL over every code, because a refusal with no recovery
dead-ends the caller and that is the failure the whole vocabulary exists to
prevent. One asserts every typed exception class is mapped, so a new failure
class cannot silently fall through to `BAD_PARAMS`.

`NOT_IMPLEMENTED` is the Phase 0 stub code and it is deliberately kept OUT of
`CLOSED_CODES`, in a separate `SCAFFOLD_CODES` set that a test asserts is
disjoint. A scaffold code that quietly joins the shipped vocabulary is how a
temporary thing becomes permanent, and Phase 9's gate asserts the scaffold set
is empty.

**The redaction seam ships and no redactor does.** DESIGN 5.3 puts redaction at
the serializer because that is the one place it can be enforced globally. Phase
0 wires `set_redactor` and a test installs its own to prove the seam reaches
both success payloads and refusals. Phase 3 installs the real one and its gate
proves it against a deliberately leaky tool.

**Read-only mode is real in Phase 0, not deferred.** The mechanism is absence:
`policy/readonly.py` classifies every tool and `server.register` never hands a
mutating tool to FastMCP when the mode is on. `--read-only` registers 10 tools
instead of 14, and a test walks an in-process MCP client to confirm the mutating
four are genuinely missing from `tools/list` rather than merely refusing. A tool
nobody classified RAISES at startup rather than defaulting in either direction,
because defaulting to non-mutating would register a write tool in read-only mode
and make the headline claim false.

**Packs are launch-time and there is no runtime toggle**, which is the family
departure DESIGN 7.2 argues for on conformance grounds. `enable_tools` and
`disable_tools` do not exist and a test asserts they never appear. A pack typo
refuses to start with exit code 2 and a message naming the known packs, which
inverts chrome-devtools-mcp #2530 rather than shrugging like it does. The pack
hint in a refusal names `--packs extract` and `KS4WEB_MODE=extract`, since
there is no enable call to name (DESIGN 7.4).

**The open-core seam is enforced by AST, not by convention.** `policy/` may not
import `ops/` or `engine/`, checked statically over the source, because an
import inside a function body would pass a runtime probe and still couple the
packages. A second test asserts the direction is actually exercised, so the
rule cannot pass vacuously on an empty folder.

**`engine/` is empty except for one constant**, and that is deliberate.
`FIREFOX_SAFETY_ARGS = ("-no-remote",)` lives there with the S3 finding written
above it, so the Phase 1 author of the launch path cannot miss it. Playwright's
`BidiFirefox.defaultArgs` omits `-no-remote` and a launch can be adopted by the
user's running Firefox regardless of profile directory. A rule that lives only
in a design document gets re-derived; a rule that lives in a test does not.

### The two membership decisions, applied and recorded

The design review's arithmetic note predicted both and Phase 0 executes them.
**`request_handoff` folds into `manage_session` as an action**, since handing a
headed window to a human IS a session operation. **`emulate` drops out of lite**
into the `capture` pack, since its case was always a token argument rather than
a capability one, and KS4Web does not need a second cost lever when the
projection is the first one. Lite is **14 tools**, and a test asserts the roster
literally so the decisions are checked rather than commented.

### The Phase 0 finding: the lite target is not reachable by trimming prose

`measure_surface` reports the lite surface at **~2.72k tokens** against DESIGN
3.2's published **1,500**. This is the risk the design review flagged as a
watch-item, now a number, and it is worse than "tight."

The arithmetic: 1,500 across 14 tools is 107 tokens per tool INCLUDING its JSON
schema. The measured split is ~1.44k of descriptions and ~1.28k of schemas, and
the cheapest tool in the roster costs 138 with its description already at the
80-token floor. **No amount of editing gets there.** It needs a smaller roster
or a revised number, and that is an author decision rather than something a
build session should make quietly.

So the test is a RATCHET rather than a gate: the surface may shrink and may not
grow, and the 1,500 gate stays where the plan puts it, at **Phase 7**, by which
time the roster will have been decided. The plan wins on gate placement and the
measurement is on the record from the day it appeared instead of arriving as a
surprise at the Phase 7 gate.

Two related numbers, both comfortable: the largest single schema is
`get_page_view` at **~148 tokens** against a 250 ceiling, so the flagship's
eight parameters fit; and read-only lite is **~1.93k**, which is closer to the
target for the reason that it is a smaller surface.

For context rather than comfort: 2.72k still beats playwright-mcp's 4,637 and
chrome-devtools' 6,460 measured the same way. It is a 1.7x beat rather than the
published 3.1x, and **the published number is the one that has to change or the
roster is.**

### The gate

| Phase 0 gate item (PLAN) | Result |
|---|---|
| Ported machinery's own tests green | **PASS**, 81 tests |
| `measure_surface` runs | **PASS**, output above |
| Import-direction test passes | **PASS** |
| No browser needed yet | **PASS**, and asserted: no module imports playwright, and playwright is an optional extra |

Plus, beyond the plan's four: the dependency ledger is enforced by a test that
fails if `pyproject` grows a dependency the ledger does not list; the copy
guards check em dashes, the safety-copy grammar, attack-recipe framing, the
one-read overclaim banned since S1, affiliation language, and the absence of any
license claim; and the console script parses, starts, and refuses a pack typo
with exit code 2.

### Divergences from the plan, stated

Three, all additive or gate-placement rather than substitutions.

1. **Tool registrations are in Phase 0.** PLAN's Phase 0 is scaffold and ports
   and does not mention tools; the lite roster as stubs was asked for on top.
   It costs nothing and it is what made the lite-budget finding available now
   rather than at Phase 7.
2. **The lite-budget gate stays at Phase 7**, where PLAN puts it, rather than
   binding here. PLAN 1.1 does say the docstring test enforces "the 80-120
   token description budget and the sub-250 per-schema ceiling" from day one,
   and both of those DO bind now and both pass. The 1,500 total is a different
   number in a different phase.
3. **Corpus A is still owed.** Phase 0 needs no fixtures, but the freeze the
   plan requires before S1 never happened and is still outstanding before the
   Phase 2 harness.

**Status:** Phase 0 green. Phase 1 is blocked on the spike gate, which is
blocked on S2. No license, no browser code, nothing published.

---

## Part VI: Phase 1, the browser core (2026-09-05 02:07 KST)

**GATE GREEN on all four parts. 213 tests, all passing. Zero orphans across 50
session cycles and four hard-kill scenarios on both lanes, projection p95 417 ms
at 50,000 nodes, lite surface unchanged at 2.72k.** First code in the repo that
touches a browser.

### What landed

`engine/lanes.py`, `engine/hygiene.py`, `engine/session.py`, the whole
`projection/` package, four lite tools wired to a real browser
(`manage_session`, `manage_tabs`, `navigate`, `get_page_view`, plus
`get_workflows`, which needed no browser), two gate scripts, a fixture corpus,
and 132 new tests.

### The engine

**Lane A and Lane B, and Lane C refuses rather than pretends.** Lane B carries
`moz-firefox` per S3, and the S4 capability table is now code that
`manage_session(action="capabilities")` reads rather than a table in a document
somebody has to remember to update. Both measured gaps are LOUD REFUSALS:
`navigate(action="back")` on Firefox/BiDi raises `LANE_UNSUPPORTED` naming the
stale-URL behavior and the substitute, and the substitute is real because
KS4Web tracks its own page history per handle. Lane C refuses with a message
that says S5 and S6 are deferred by a standing safety rule rather than by a
finding, so nothing in the product implies a capability nobody has verified.

**`-no-remote` is a constant on every Firefox launch**, asserted from three
directions: the Phase 0 constant test, a lanes test over every Firefox spec
including the headed one, and the live Lane B test that drives the author's
installed Firefox 154 on a throwaway profile.

**Playwright is imported inside functions, never at module scope.** Lazy install
is also lazy start, and codex #21984 names eager startup of GUI-capable MCP
tools as the root cause of the worst leak reports. A test proves it in a FRESH
interpreter, because a browser test earlier in the same session would leave
playwright in `sys.modules` and make an in-process assertion pass for the wrong
reason. A second test confines the playwright import to `engine/` entirely:
`projection/` takes a page-like object with an `evaluate` method and never
imports the driver, which is what keeps the whole projection testable against a
recorded extraction.

### The hygiene layer, and the gate that can actually fail

Three defenses, all built: a kill-on-close job object alongside Playwright's own
death pipe, a startup reaper keyed on OWNED PID only, and an idle park verified
by CPU measurement rather than by asserting that a park happened.

**Four mechanical findings, three of them bugs this build made and fixed.**

1. **`alive()` was wrong in the dangerous direction.** `OpenProcess` succeeds on
   a process that has already exited for as long as anyone holds a handle to it,
   and a parent holding a `Popen` object holds one. The first version reported
   dead processes as survivors. It now waits on the process handle, which
   signals on exit.
2. **`descendants()` adopted strangers.** A parent-PID field points at a NUMBER,
   Windows recycles PIDs, and a naive walk pulls in any process whose parent PID
   matches a recycled one. On this machine that turned a five process browser
   tree into a forty process claim, which would have authorized forty kills. A
   child cannot predate its parent, so creation-time comparison drops every one
   of those without dropping a real child.
3. **The journal has an adoption filter, and it is not a sweep by name.** Only
   browser-shaped descendants that appeared during our own launch enter the
   journal, so a PowerShell process spawned for a CIM query can never be
   authorized as a kill. The house rule bans sweeping BY name; this is the
   opposite of that.
4. **The reaper's last fence fires on positive evidence of somebody ELSE'S
   ownership**, never on the absence of evidence of ours. The first version
   required a command line naming an owned profile, which declines every browser
   helper process, since a renderer does not always repeat the profile flag its
   root was launched with, and declining to kill a helper is how the orphan gets
   left behind.

Toolhelp32 replaced the spike's `Get-CimInstance` for the process table: single
digit milliseconds against S7's measured 1.0 second for 557 processes, which is
what makes a per-launch census affordable. CIM stays for command lines, which
only the reaper's last fence needs.

### The confound, and the divergence from PLAN's gate wording

PLAN Phase 1 requires the orphan test to break away from the ambient job object
(`CREATE_BREAKAWAY_FROM_JOB`), on the grounds that a shell owning a
`KILL_ON_JOB_CLOSE` job reaps the tree for you and every result comes back green
whether or not the server has any teardown at all. That requirement is right and
**its stated mechanism does not work on this machine.**

The ambient job here carries `0x3000`: `KILL_ON_JOB_CLOSE` plus
`SILENT_BREAKAWAY_OK`, with `BREAKAWAY_OK` off. The explicit flag is therefore
rejected with access denied on some paths and accepted on others, and in every
case the child still lands inside a kill-on-close job. Creating the victim
through WMI `Win32_Process::Create`, which builds the process from the service
rather than from us, does not escape it either.

**So the gate gets its falsifiability from a NEGATIVE CONTROL instead, which is
a stronger instrument than the one the plan named.** Before the KS4Web
scenarios run, the gate hard-kills a parent holding a browser started by plain
`Popen`, with no death pipe, no job object, and no teardown of any kind. That
browser MUST survive. It does, leaving 11 orphaned processes, which proves the
environment is not quietly reaping browser trees. Only then do the KS4Web
scenarios mean anything, and they leave zero. **This is a divergence from the
plan's wording and it serves the plan's purpose better than compliance would
have:** breakaway is a proxy for "the harness is not doing the work," and the
negative control measures that directly.

The four hard-kill rows, with the parent and the Node driver both hard-killed:

| scenario | processes | orphans | reap |
|---|---|---|---|
| negative control, no teardown at all | 13 | **11, as required** | never |
| Lane A chromium, KS4Web job object ON | 4 | 0 | 1.0 s |
| Lane A chromium, KS4Web job object OFF | 4 | 0 | 1.0 s |
| Lane B moz-firefox, job object ON | 10 | 0 | 1.0 s |
| Lane B moz-firefox, job object OFF | 10 | 0 | 1.0 s |

Running each lane with the job object OFF is what turns "the death pipe is doing
the work and the job object is a backstop" from a claim into a measurement.
S7 said it; this confirms it on the shipped code.

### The projection

The S1 prototype is not ported. It is rebuilt around the three corrections S1
forced, and each one has a fixture that would catch the defect coming back.

**One depth-first walk, one computed style per element.** Region ownership comes
from a stack maintained during the walk, so every count is NET of nested regions
and a parent can be priced net of its children without a second pass. The walk
also stops at a hidden subtree and accounts for the whole thing there, which is
what keeps the normalizer linear rather than quadratic.

**Accessible names are computed by an accname walk**, with space-separated
contributions, word-boundary truncation carrying an explicit ellipsis, and a
refusal to emit a CSS class as a stand-in name. The `names` fixture carries
every S1 failure: a heading glued to its count badge now reads `General 4`, the
hidden error element no longer names the `main` region, `.mw-file-description`
is `(unnamed)` plus its href, and a long name cuts on a space. **The region
label bug was reproduced and fixed during this phase**: the first version took
the first heading in the subtree and picked up the hidden `Uh oh!` exactly as S1
did, because a heading that is itself visible can sit inside a `display:none`
wrapper. The label now requires the whole chain up to the region to be visible.

**Affordances are selected by per-class quota with guaranteed floors.** The
`appshell` fixture is S1's GitHub failure in miniature: thirteen repository tabs
competing with sixty truncated commit-message links. All thirteen tabs appear.
On the `article` fixture, 140 in-prose links are suppressed by a quota of zero
and the completeness block states the count and the class. One correction made
during the build: a control only counts as a form control when it is INSIDE a
form, because letting every loose input on an app shell claim the "complete,
never sampled" guarantee turns the guarantee into the flood it was written to
prevent.

**Prices and budgets are one arithmetic.** The budget meter estimates with
`tiktoken` on `o200k_base`, holds a 10 percent drift margin in reserve, and
keeps a ledger of every unit and its disposition. Sections are priced over their
true extent in document order, spanning wrappers, and a heading whose extent
cannot be determined prints no price and says so. Regions are priced net of
their children. **The completeness block computes nothing**; it renders the
ledger, and the "0 regions not expanded" case is a named regression test.

**The ladder has eight rungs and is monotonic as exposed.** The caps are
non-increasing by construction, and one more mechanism was needed: dropping a
unit can occasionally cost MORE than it saves, because the completeness block
then has to account for what went. The `names` fixture grew by 37 tokens at rung
7 for exactly that reason. A rung that costs more than a rung above it is
DOMINATED and never chosen, which makes the ladder the caller sees monotonic
even when a single step is not. The other half of that fix was a real defect:
the suppression line was explaining the in-prose rule even when no in-prose link
had been suppressed.

**The floor is content-aware**: the field listing survives on a form page and
the digest survives on an article, which is the inverse of what S1's floor did.

### The latency budget, held

Measured on the same synthetic ladder the engine round used, ten warm
repetitions per fixture after one discarded pass, against the shipped projector.

| nodes | extract p95 | Python assembly p95 | projection p95 | budget |
|---|---|---|---|---|
| 5,012 | 80 ms | 3.8 ms | 84 ms | 500 ms |
| 10,012 | 100 ms | 4.1 ms | 104 ms | 500 ms |
| 25,012 | 288 ms | 6.6 ms | 294 ms | 500 ms |
| 50,012 | 411 ms | 5.9 ms | **417 ms** | 500 ms |
| 100,012 | 671 ms | 5.1 ms | **676 ms** | 1,000 ms |

Two findings worth banking. **The payload crossing the driver boundary was the
bill, not the walk.** The first version returned every heading on the page, and
a 5,000-heading fixture cost more in JSON transfer than the entire in-page pass
cost in the browser: 604 ms round trip against 245 ms of actual work. Capping
what is RETURNED while tallying everything that is COUNTED fixed it without
costing a single completeness figure, because the suppression counts come from
the extractor's own tally rather than from the list in hand.

**Per-line token measurement had to be memoized.** The budget line states the
total of the payload it sits inside, so it is self-referential and the ladder
renders to a fixpoint, which means most lines get measured twice. Memoizing the
line-level counts and switching to `encode_ordinary` took Python assembly from
14 ms to under 6 ms. The estimator warms when a browser starts, so the one-off
cost of loading the BPE table does not land inside the first read.

### The fixture corpus, and why the recordings are committed

`tests/fixtures/pages.py` holds five hand-written pages, one per failure class,
and `scripts/capture_fixtures.py` records one extraction each into
`tests/data/`. The projection is a pure function of an extraction plus a budget,
so 72 projection tests run in half a second with no browser and cannot flake.
**The recordings are committed on purpose: a diff in those files IS a change in
what every read sees**, which makes them a review surface rather than a build
artifact.

### The gate

| Phase 1 gate item (PLAN) | Result |
|---|---|
| Zero orphans after 50 session cycles | **PASS**, 50 cycles in 39.9 s, no survivors, no leftover profile directories |
| Including SIGKILL of the server parent | **PASS**, both lanes, with and without KS4Web's job object |
| Verified by owned PID on Windows | **PASS**, and the journal is the only thing that authorizes a kill |
| Clean startup reap of deliberately orphaned profile dirs | **PASS**, with a control process the reaper must not touch and a live-peer journal it must skip entirely |
| Idle-timeout park verified by CPU measurement | **PASS**, 2.53 CPU-seconds over 3 s down to 0.00 |
| The orphan test must be able to FAIL | **PASS by a different mechanism.** Breakaway is unavailable on this machine; a negative control that orphans 11 processes proves it directly |
| `-no-remote` on every Firefox launch | **PASS**, three independent assertions |
| Projection p95 at or under 500 ms to 50,000 nodes | **PASS**, 417 ms |
| Projection p95 at or under 1.0 s to 100,000 nodes | **PASS**, 676 ms |
| Python-side assembly at or under 10 ms | **PASS**, 5.9 ms at 50,000 nodes |
| Full suite green | **PASS**, 213 tests |
| `measure_surface` runs | **PASS**, lite unchanged at 2.72k |

### Divergences from the plan, stated

Four.

1. **`navigate` and `manage_tabs` moved up from Phase 4 into Phase 1**, on
   instruction: the phase was defined as the browser core including the
   navigation and lifecycle tools. The action tools (`click`, `type_text`,
   `fill_form`, `press_keys`, `scroll`, `wait_for`) stay in Phase 4 behind the
   policy layer, and every one of them still refuses honestly.
2. **The orphan gate's falsifiability comes from a negative control rather than
   from `CREATE_BREAKAWAY_FROM_JOB`**, because the flag cannot deliver an
   out-of-job child on this machine. Recorded above in full.
3. **Phase 1 opened before the spike gate closed.** S2 (anchor durability) has
   not run, so this phase built no anchors: refs are minted per read, and the
   rebind ladder, the sticky element map, and deltas are all Phase 2. Nothing
   here depends on the S2 answer, and `get_page_view(since=...)` refuses by
   naming the phase rather than pretending.
4. **The copy guards were extended to cover the projection payload**, which the
   Phase 0 skeleton did not reach. It is the most-read public text in the
   product by a wide margin.

### Open items carried forward

- **Corpus A is still owed.** The four MEASURED pages are not frozen, and PLAN
  1.3 requires that before the Phase 2 harness. The Phase 1 fixtures are corpus
  B's first slice, not corpus A.
- **The lite budget question is still an author call.** 2.72k measured against a
  published 1,500 target, unchanged this phase because the roster and the
  docstrings were not touched. The ratchet holds at 2,900.
- **`view="read"`, `"links"`, and `"dom"`** are refused by name pending Phase 2,
  along with `location`, `since`, `cursor`, and `include_hidden`.
- **The select-options cap** is set at 12 options and 240 characters from taste,
  and DESIGN 3.3 block 5 says Phase 2 sets it from measurement.

**Status:** Phase 1 green. No license, nothing published, no anchors yet.

---

## Part VII: Phase 1 absorbed into the design (2026-09-05 02:18 KST)

Ten findings from the Phase 1 report written into DESIGN and PLAN. No code
changed and no test changed, which is the point: these are the documents
catching up to what the build learned, so the next session reads the corrected
rule instead of re-deriving it.

### What moved, and where it landed

**Three went to DESIGN 4.7 (Windows process hygiene) as mechanical facts 5
through 7**, joining the four S7 banked. `OpenProcess` succeeds on a process
that has already exited for as long as anyone holds a handle to it, so liveness
waits on the process handle; the naive check fails toward "everything leaked,"
which sounds conservative and makes the reaper's evidence worthless. A
parent-PID walk adopts strangers through recycled PIDs, and the recorded number
is the one that makes the case: a five-process browser tree came back as a
forty-process claim on this machine, which would have authorized forty kills.
And the journal's adoption filter is an arrival DIFFERENCE rather than a name
match, which is what the cheap census buys.

**The census swap is recorded inside fact 2 rather than as a new fact**, since
it revises the CIM measurement S7 banked rather than adding to it. Toolhelp32
at single-digit milliseconds against CIM at ~1.0 second for the same table,
with CIM kept for the command line that only the reaper's last fence reads. The
paragraph says why this is architectural and not an optimization: a census
affordable per launch is what makes the before-and-after difference available,
and the difference is the whole adoption filter.

**The negative control is now in the gate DEFINITION, in both documents**, and
it is the primary instrument rather than a substitute for breakaway. DESIGN 4.7
and PLAN Phase 1 both carry it: breakaway is not portable (the ambient job here
is `0x3000`, `SILENT_BREAKAWAY_OK` with `BREAKAWAY_OK` off, and WMI
`Win32_Process::Create` does not escape it either), so the gate requires a
teardown-free browser under a hard-killed parent that MUST survive, and keeps
breakaway as an optional second instrument. Phase 1's 11 orphans from that
control are the licensing measurement for its zero-orphan rows. The plan's
wording changed from "MUST break away" to "MUST demonstrate that it can FAIL,"
which is what the requirement always meant.

**DESIGN 3.6a gained the driver-boundary term**, 604 ms of round trip against
245 ms of in-page work on a 5,000-heading fixture, stated as the rule **cap what
you RETURN, tally what you COUNT**. It is written as a latency finding with a
correctness edge, because an implementation that derives "omitted 2,700" from a
list it holds has to hold 2,700 things to say the number. The memoization
finding went in the same section: the budget line states the total of the
payload it sits inside, so the render is a fixpoint and most lines get measured
twice. Both are consequences that shape a Phase 2 rebuild rather than trivia.
PLAN's Phase 2 gate item 5 gained the same term as a checked property.

**DESIGN 3.4's monotonicity requirement got its mechanism.** The old text asked
for a monotonic ladder and the caps were non-increasing by construction, and a
step still grew by 37 tokens because dropping a unit costs what the
completeness block then spends accounting for it. Reasoning about caps is
reasoning about inputs; the property is about outputs. So the requirement is now
**monotonic AS EXPOSED**, enforced by never choosing a dominated rung, and the
gate asserts the sequence a caller can actually be handed. The distinction
matters enough to state because the stronger-sounding version is the one that
is false.

**DESIGN 3.7 gained sub-rule 5, the whole-ancestor-chain visibility rule.** The
`"Uh oh!"` case was reproduced during Phase 1 by an implementation that
believed rule 1 had retired it, because the error heading is itself visible and
sits inside a `display:none` wrapper. PLAN's Phase 2 gate item 9 now requires
the fixture to hide the heading through an ANCESTOR, since a fixture that hides
the element itself passes an element-local check and tests nothing.

**DESIGN 3.3's form-control quota is scoped to controls inside a form**, in the
quota table and in a paragraph next to the zero-quota one, with the reason
stated: an app shell's loose inputs claiming the "complete, never sampled"
guarantee turns the guarantee into the flood it was written to prevent, which
is the ranker failure arriving from the opposite direction. Loose controls are
not dropped, they lose only the exemption from sampling.

### The two author items

**DESIGN 11 gained Q11a and Q11b under the ruling that spawned them**, with a
new preamble line saying that a ruled question can reopen a narrower one. Q11a
tables all twelve `KS4WEB_` variables Phase 1 added, against the three the
ruling named plus the one Phase 0 added, and asks three things: which are
supported surface rather than escape hatches, whether the launch-shape four
collapse into one `KS4WEB_LANE` string, and whether `KS4WEB_JOB_OBJECT=0`
belongs in public documentation at all given that it turns off a backstop.
**Q11b records the `manage_session` lane string for ratification**, with the
schema-budget reason it was chosen, the four-parameter alternative it displaced,
and its cost stated (a string is not self-documenting the way named parameters
are). Both are recorded as reversible-until-ship in the same standing as Q6, and
PLAN's rulings checkpoint gives them a row: they block nothing until Phase 9,
when they become compatibility surface.

**Suite unchanged and green, 189 unit tests in 3.8 s.** Documents only.

## Part VIII: Corpus A frozen, and the numbers re-measured (2026-09-05 02:31 KST)

**The four MEASURED pages are frozen to disk and committed, every DESIGN 3.2
figure is now the shipped projector under `o200k_base`, and two published
targets do not survive contact with the measurement. 218 tests, all passing.**

### The freeze

`corpus/a/` holds the four pages, `corpus/a/MANIFEST.json` records the fetch
DTG in KST, the final URL, the MediaWiki revision id where one is published
(Versailles 1371877530, GDP 1372799821), a sha256 per file, and what the
capture strips. `scripts/freeze_corpus_a.py` rebuilds it. This closes the item
PLAN 1.3 has carried as NOT MET since S1, which ran against live pages and
froze only its extraction outputs.

**A naive capture is not a freeze, and the reason is the projection's own
subject matter.** An `outerHTML` dump loses every stylesheet, visibility on the
web is a CSS property, and the projection's hidden-content normalizer sweeps
every node, so a projection run against a bare dump would compute different
answers than the live page did. The capture therefore serializes the post-load
DOM, inlines every stylesheet in document order with external sheets fetched
through the browser's own request context, and strips `<script>` and
`<noscript>` because a page that rehydrates is not frozen. **No `<base>` tag is
injected, deliberately:** Wikipedia's internal links are root-relative, so a
page served from localhost still matches origin and still prints paths rather
than full URLs, which is what keeps the count comparable. A base pointing at
the live origin would make every internal link cross-origin and inflate the
exact number the corpus exists to pin down.

The freeze is enforced rather than asserted. `tests/unit/test_corpus_a.py`
verifies each file against its recorded digest, so a re-freeze is a deliberate
act with a visible diff, and checks that no frozen page carries script.

### Corpus A found a defect on its first run, before it measured anything

`Page.evaluate: TypeError: (s || "").replace is not a function`, thrown on the
Treaty of Versailles page by the shipped extractor. **A `<form>` exposes its
named controls as properties, so a form holding `<input name="title">` answers
`form.title` with the INPUT ELEMENT rather than a string.** Wikipedia's search
form has exactly that field. Two fixes, and the second one is the general one.
The `title` reads became `getAttribute('title')`, which is what accname
specifies anyway. And `squash()` is now strict: a non-string is empty rather
than something to coerce, because the permissive version would have
stringified a DOM element into an accessible name on any page where it did not
happen to throw, which is the confident-wrong-answer failure DESIGN 3.7 exists
to stop. The `formpage` fixture grew the trap and a regression test asserts no
object tag ever reaches a name or the payload.

**This is the argument for corpus A stated as an event rather than a
principle.** Five hand-written fixtures and a 50,000-node synthetic ladder did
not contain a form with a control named `title`, and no amount of care would
have invented one. Real pages carry constructs nobody would write on purpose.

### The numbers, o200k against the frozen pages, budget 5,000

| page | nodes | o200k | rung | cl100k | delta | target | |
|---|---|---|---|---|---|---|---|
| example.com | 13 | **570** | 1 | 572 | -2 | the floor | measured |
| httpbin form | 47 | **809** | 1 | 812 | -3 | under 900 | **PASS**, 91 to spare |
| GDP table | 5,644 | **3,166** | 1 | 3,169 | -3 | under 3,000 | **FAIL by 166** |
| Versailles | 10,737 | **3,683** | **3** | 3,719 | -36 | under 5,000 | PASS, ladder engaged |

**The tokenizer was not the story, and the design expected it to be.** Conflict
record #4 has tokenizers disagreeing by roughly 3x on this class of content, so
both encodings were run over the same payloads. The gap is **0.3 to 1.0
percent** and `o200k_base` is the cheaper one on every page. A projection
payload is structured English with short identifier tokens, which is the
content class the encoders agree on; the 3x disagreement lives in raw markup
and minified script, which the projection never emits. The practical
consequence is worth more than the caveat it retires: **the incumbent baselines
do not need re-counting under `o200k_base` before the comparison is
publishable**, because a sub-1-percent encoder gap cannot move a 20x to 48x
multiple.

**So everything that moved, moved because of the Phase 1 rebuild.** The
scaffold floor went from 404 to **570**. On a thirteen-node page the whole 570
is scaffold, and the completeness block is fourteen lines of it, because it
names every class of thing the read did not see on a page that has none of
them. That is the design working as argued rather than a regression, since a
block that only appears when it has bad news cannot distinguish "I did not
look" from "there is nothing there." It does make the two losing rows worse
(httpbin 1.8x the incumbent, example.com 5.4x), and both stay published with
the reason attached, which is what DESIGN 12 rule 2 was written for before the
number moved.

### Two findings that need the author

**The GDP structure read fails its target by 166 tokens, 5.5 percent.** It is
recorded as a failure rather than quietly restated, because the target was set
at S1 from a 2,854 prototype measurement and the shipped projector is a rebuild
rather than a regression of it. Lowering the number means either dropping the
affordance quota on a table-of-links page or moving the target to what the
structure read actually costs, and the design does not make that call in a
build session.

**Versailles engages the ladder at the default budget, and the gap between
rungs is the finding.** The undegraded read is 4,965 against a 4,500 effective
budget (5,000 less the 10 percent drift margin), rung 2 is 4,589, rung 3 is
3,683. The guarantee holds: under budget, nothing truncated, 22 collapsed
regions stated in the completeness block. The margin claim does not, and
"holds with 25 percent of margin" is now false. **The step that fits is 906
tokens below the step that does not, a 20 percent drop where a 3 percent one
would have fit.** That is S1's finer-rungs finding recurring at the TOP of the
ladder after the rungs were already refined from five to eight, so it is a real
Phase 2 item: a partial-collapse step that sheds the lowest-priority regions
rather than all of them.

### The live drift check, which makes the same point from the other side

PLAN 1.3 asks for the live run as a drift check and this is what it bought.
Three of four sit within 2 percent of their frozen twins (example.com -1.9,
httpbin -1.1, GDP -1.8), which is the answer a freeze wants. **Versailles reads
+15.3 percent live, 4,246 against 3,683, on a 1.5 percent content difference**
(10,572 nodes against 10,737). The whole gap is the cliff: live rung 2 lands at
4,246, under the effective budget, and frozen rung 2 lands at 4,589, over it.
A 1.5 percent content difference produced a 15 percent token difference, so the
published number for a page near a rung boundary is discontinuous in page size.
That is not a defect in the freeze and not a defect in the check. It is the
strongest available argument for the finer step, and it is a caveat the
published benchmark states rather than one a reproducer discovers.

### What changed in the documents

DESIGN 3.2's measured column is replaced wholesale and now names its source
(`gates/corpus_a.json`, `corpus/a/MANIFEST.json`), with the encoder finding,
the floor restatement, the GDP failure, the Versailles cliff, and the drift
check each written out. DESIGN 1.1 and 12 rule 2 carry the new floor and the
new Versailles figure. PLAN 1.3's corpus A row is MET with the artifacts named,
PLAN's Phase 2 gate item 1 names the two rows that need a ruling before it can
be called, and W1's "no S1 number is publishable as-is" is discharged with the
encoder finding recorded in its place.

**Suite: 218 tests, all passing** (194 unit, 24 browser), up from 213 by the
corpus digest checks and the named-property regression.
