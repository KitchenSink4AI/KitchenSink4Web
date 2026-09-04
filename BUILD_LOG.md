# 🌿 KitchenSink4Web: The Build Log

**Author:** Nykolus Alvut (with Claude Code)
**Status:** DESIGN PHASE. No code, no spikes run, no license chosen.
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
notification, does both of those things. Assessment recorded in DESIGN 7.2: the
family pattern is not conformant with the current revision. KS4Web will not ship
it, and instead tiers through launch-time packs plus the client's own
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
