# Browser-Automation MCP Servers: How They Answer Six User Requests

**Survey date:** 2026-09-06 (KST). Agent: web-cmp-survey. Research only, no repo writes.
**Purpose:** ground the KS4Web product-page comparison matrix. This document is EVIDENCE, not page copy.

**Rule followed throughout:** where a server's documentation or source does not address a request, the cell says
**UNDOCUMENTED** — not "cannot". Several servers may do the thing without documenting it. Claims marked
[SOURCE-VERIFIED] were read directly out of the repository source, not from a doc summary.

---

## Servers surveyed, with versions and dates

| # | Server | Package / location | Version surveyed | Date evidence | Notes |
|---|--------|-------------------|------------------|---------------|-------|
| 1 | **Microsoft Playwright MCP** | `@playwright/mcp`, github.com/microsoft/playwright-mcp | **v0.0.80** | released 2026-09-01; repo pushed 2026-09-04; 36,833 stars | Active, the reference implementation |
| 2 | **Chrome DevTools MCP** (Google) | `chrome-devtools-mcp`, github.com/ChromeDevTools/chrome-devtools-mcp | **v1.8.0** | released 2026-08-25; repo pushed 2026-09-04; 51,055 stars | Active, official Google |
| 3 | **Puppeteer MCP** (reference) | `@modelcontextprotocol/server-puppeteer`, modelcontextprotocol/servers-archived | archived | repo is `servers-archived`; no longer maintained | Still widely installed |
| 4 | **browser-use (local MCP server)** | `browser-use`, github.com/browser-use/browser-use | **0.13.10** | released 2026-09-04; 112,392 stars | Active, largest star count |
| 5 | **Browserbase MCP (Stagehand)** | github.com/browserbase/mcp-server-browserbase | v3.0.0 self-host; hosted at `mcp.browserbase.com/mcp` | **repo archived 2026-07-20**; last release 2026-03-31 | README: "This repository is archived and no longer maintained." Hosted server is the live product |
| 6 | **Claude in Chrome** (Anthropic extension) | `mcp__claude-in-chrome__*` | tool schemas read live from the running extension, 2026-09-06 | schemas observed in this session | Tool descriptions below are verbatim from the live schemas |
| 7 | **Firecrawl MCP** | `firecrawl-mcp`, github.com/firecrawl/firecrawl-mcp-server | v3.2.1 | repo pushed 2026-09-05; 7,403 stars | Adjacent: a page-read specialist, not a full automation server. Included because it is the mainstream answer to request 1 |
| 8 | **Browser MCP** | github.com/BrowserMCP/mcp | no releases | **repo last pushed 2025-04-24** (~16 months stale) | A `playwright-mcp` fork driving the user's own Chrome via extension. Included as the popular "use my real browser" option; treat as unmaintained |

Sources for this table: `gh api` calls against each repository on 2026-09-06, plus each README.

- https://github.com/microsoft/playwright-mcp
- https://github.com/ChromeDevTools/chrome-devtools-mcp
- https://github.com/modelcontextprotocol/servers-archived/tree/main/src/puppeteer
- https://github.com/browser-use/browser-use
- https://github.com/browserbase/mcp-server-browserbase
- https://code.claude.com/docs/en/chrome and https://support.claude.com/en/articles/12902446-claude-in-chrome-permissions-guide
- https://github.com/firecrawl/firecrawl-mcp-server
- https://github.com/BrowserMCP/mcp

---

## THE MATRIX

### Request 1 — "Read this article and tell me what actually matters."
*What does a page read return, and at what token scale?*

| Server | Evidence |
|---|---|
| **Playwright MCP v0.0.80** | Returns an accessibility-tree snapshot, not HTML or markdown. `browser_snapshot`: "Capture accessibility snapshot of the current page, this is better than screenshot." Official docs claim "~200-400 tokens per snapshot vs thousands for DOM/screenshots" (playwright.dev/mcp/introduction). That figure is for a small demo page. A third-party measurement on Salesforce Lightning using `@playwright/mcp@0.0.75` reports "each browser snapshot on a Lightning page runs between 10,000 and 50,000 tokens on its own," accumulating "roughly 114,000 tokens of accessibility-tree data" over a 5-15 snapshot session (Provar, © 2026). Budgeting knobs exist but are opt-in: `depth` limits the snapshot tree, `target` scopes it to one element, `--snapshot-mode none` suppresses snapshots in responses entirely, and `--mobile` is documented as a token-saving measure: "Mobile pages are usually lighter, which saves tokens." No automatic budgeting. |
| **Chrome DevTools MCP v1.8.0** | `take_snapshot`: "Take a text snapshot of the target page based on the a11y tree. The snapshot lists page elements along with a unique identifier (uid)." No markdown conversion, no article extraction. Design Principles doc states the intent — "Token-Optimized: Return semantic summaries... Files are the right location for large amounts of data" and "Reference over Value: for heavy assets (screenshots, traces, videos), return a file path or resource URI, never the raw data stream" — but that discipline is applied to traces and screenshots, not to the a11y snapshot itself. Token scale for a snapshot: UNDOCUMENTED. |
| **Puppeteer MCP (archived)** | No page-read tool at all in the structured sense. The seven tools are navigate, screenshot, click, hover, fill, select, evaluate. To read a page the agent must call `puppeteer_evaluate` ("Execute JavaScript in the browser console") and return DOM text itself, or take a screenshot. Token scale: entirely determined by whatever JS the agent writes. UNDOCUMENTED. |
| **browser-use 0.13.10** | Two paths. `browser_get_state` ("Get the current state of the page including all interactive elements") returns JSON with url, title, tabs, viewport/page/scroll geometry, and an `interactive_elements` array — **not article prose**. `browser_get_html` returns "the raw HTML of the current page or a specific element by CSS selector." `browser_extract_content` ("Extract structured content from the current page based on a query") is the article-reading path, and it runs a **second LLM** server-side: the source returns "Error: LLM not initialized (set OPENAI_API_KEY)" if none is configured. [SOURCE-VERIFIED, `browser_use/mcp/server.py`] |
| **Browserbase / Stagehand** | `extract` — "Extract data from the page" with an optional natural-language `instruction`. Also LLM-backed: the hosted server defaults to Gemini 2.5 Flash Lite and the README states Browserbase "provide[s] the LLM costs for Gemini, the best performing model in Stagehand." The tool returns `JSON.stringify({ success: true, data: extraction })`. [SOURCE-VERIFIED, `src/tools/extract.ts`] So the model never sees the page — it sees another model's summary of it. |
| **Claude in Chrome** | The only surveyed server with a purpose-built article reader. `get_page_text`: "Extract raw text content from the page, prioritizing article content. Ideal for reading articles, blog posts, or other text-heavy pages. Returns plain text without HTML formatting." Separately `read_page` gives the a11y tree with an explicit character budget: "Output is limited to 50000 characters by default." [verbatim from live tool schemas, 2026-09-06] |
| **Firecrawl MCP v3.2.1** | The markdown answer. `firecrawl_scrape` takes `formats: ["markdown"]` plus `onlyMainContent: true`; the docs recommend exactly that pair for article extraction and say "Using `onlyMainContent` is recommended for efficiency." Also `includeTags`/`excludeTags` for manual pruning and `maxAge` for cache reuse. No token accounting. |
| **Browser MCP** | Fork of Playwright MCP's snapshot tool set — same a11y-snapshot return. No budgeting parameters observed in `src/tools/snapshot.ts`. Stale since 2025-04. |

---

### Request 2 — "Find the issue about the broken d-pad. There are 771 open ones."
*Is there a search tool, or does the agent scroll and dump?*

| Server | Evidence |
|---|---|
| **Playwright MCP v0.0.80** | **Has a real search tool, and this is recent.** `browser_find`: "Search the accessibility snapshot of the current page for text or a regular expression. Returns matching snapshot nodes with a few lines of surrounding context (like search snippets), each shown under its path from the root of the tree, which is cheaper than capturing the whole snapshot when you only need to locate an element and its ref." Parameters: `text` (string) or `regex` (string). Introduced in the Playwright 1.62-alpha roll of 2026-07-09, shipped in v0.0.78 (2026-07-09). **Any comparison written before July 2026 is out of date on this point.** Note the scope limit: it searches the *snapshot*, so it finds what the snapshot contains. Pagination across a 771-item list: UNDOCUMENTED — no page/offset parameter on `browser_find`. |
| **Chrome DevTools MCP v1.8.0** | No search-within-page tool in the 60+ tool reference. Closest are `wait_for` ("Wait for the specified text to appear on the selected page"), which is a wait not a search, and `evaluate_script`, where the agent writes its own DOM query. Pagination *does* exist, but only on log lists: `list_network_requests` and `list_console_messages` both take `pageIdx` ("Page number to return (0-based)") and `pageSize`, as do the heap-snapshot query tools. Page content itself has no paging. |
| **Puppeteer MCP (archived)** | No search tool. The agent writes a `puppeteer_evaluate` script or screenshots and scrolls. No pagination anywhere. |
| **browser-use 0.13.10** | No content-search tool. The loop is `browser_get_state` -> `browser_scroll` -> `browser_get_state` again. `browser_scroll` is fixed-step: the implementation dispatches `ScrollEvent(direction, amount=500)` — 500 pixels, not configurable from the tool. It returns the string `Scrolled {direction}` with no position or remaining-content report. [SOURCE-VERIFIED] Nearest thing to search is `browser_extract_content`, which sends a query to the secondary LLM. No pagination. |
| **Browserbase / Stagehand** | `observe` — "Observe actionable elements on the page" with a natural-language `instruction` — is the closest analogue, and it is LLM-mediated rather than a deterministic search. Result count limits, pagination: UNDOCUMENTED. |
| **Claude in Chrome** | **Has natural-language search with an explicit overflow warning.** `find`: "Find elements on the page using natural language. Can search for elements by their purpose (e.g., 'search bar', 'login button') or by text content (e.g., 'organic mango product'). **Returns up to 20 matching elements** with references that can be used with other tools. **If more than 20 matches exist, you'll be notified to use a more specific query.**" There is no page-2 — the remedy offered is a narrower query, not pagination. `read_page` also takes `ref_id` to re-read one subtree, which is a manual drill-down substitute. [verbatim from live schemas] |
| **Firecrawl MCP v3.2.1** | Not a page-search server. `firecrawl_search` searches *the web*, `firecrawl_map` discovers URLs on a site, `firecrawl_crawl` walks multiple pages. For a single long page the answer is scrape-then-the-agent-greps-the-markdown itself. |
| **Browser MCP** | No search tool in the forked tool set. Snapshot and scroll. |

---

### Request 3 — "Before you read that page: what will it cost me?"
*Any cost or size preview before committing to a read?*

| Server | Evidence |
|---|---|
| **Playwright MCP v0.0.80** | **UNDOCUMENTED.** No tool reports what a read would cost, and there is no dry-run mode. What exists is prevention, not preview: `browser_find` is described as "cheaper than capturing the whole snapshot," `depth` and `target` shrink a snapshot you have already decided to take, `--snapshot-mode none` turns response snapshots off wholesale, and the README's own framing is that the CLI is preferred because MCP calls "avoid loading large tool schemas and verbose accessibility trees into the model context." The cost is acknowledged; it is never measured for you. |
| **Chrome DevTools MCP v1.8.0** | **UNDOCUMENTED.** No size or cost preview tool. `--slim` reduces the *tool surface* ahead of time ("Exposes a 'slim' set of 3 tools covering navigation, script execution and screenshots only") and the `--categoryX` flags exclude whole tool groups, but nothing reports the cost of a pending page read. |
| **Puppeteer MCP (archived)** | **UNDOCUMENTED.** No such concept. |
| **browser-use 0.13.10** | **UNDOCUMENTED** as a preview. Note the inverse: `browser_extract_content` incurs a *hidden* second cost — an extra LLM call billed to the user's own `OPENAI_API_KEY` — and nothing announces it before the call. [SOURCE-VERIFIED] |
| **Browserbase / Stagehand** | **UNDOCUMENTED.** Same hidden-inference shape as browser-use, except the hosted server absorbs the model bill ("we host the server and provide the LLM costs for Gemini"). The user pays in Browserbase credits rather than tokens, and neither is previewed. |
| **Claude in Chrome** | **Closest thing found to an answer, but it is after-the-fact, not before.** `read_page` returns a truncated result *plus* "a note giving the full size" — so the agent learns the true cost of the full read only by attempting a capped read first. That is a probe, not a preview, but it is more than any other server offers. [verbatim from live schema] |
| **Firecrawl MCP v3.2.1** | **UNDOCUMENTED** for token cost. `maxAge` gives *latency/credit* control ("Set `maxAge: 0` to force a live fetch"), and Firecrawl bills in credits per scrape, but no tool reports the projected size of a page before scraping it. |
| **Browser MCP** | **UNDOCUMENTED.** |

---

### Request 4 — "Fill in this form, but only because I said you could."
*Acting permission model: are write tools always present? Server-level read-only? Per-action gates?*

| Server | Evidence |
|---|---|
| **Playwright MCP v0.0.80** | Acting tools are **always present** — `browser_click`, `browser_type`, `browser_fill_form`, `browser_select_option`, `browser_file_upload`, `browser_evaluate`, and `browser_run_code_unsafe` are all in the core (non-opt-in) set. Every tool carries an MCP `Read-only: true/false` annotation in the generated README (e.g. `browser_snapshot` -> Read-only: **true**; `browser_click` -> Read-only: **false**), which is a *hint to the client*, not an enforcement. I grepped the full README options table (v0.0.80, 2026-09-06): **there is no `--read-only` flag and no way to omit the core write tools**; `--caps` only *adds* optional groups (vision, pdf, devtools, config, network, storage, testing). The only per-action mechanism is the optional `element` parameter, "Human-readable element description used to obtain permission to interact with the element" — i.e. the server hands the client a string to show a human; the gate lives in the client. Security controls that do exist are network-shaped: `--allowed-origins`, `--blocked-origins`, `--isolated`, `--secrets`. |
| **Chrome DevTools MCP v1.8.0** | Acting tools always present. Tools carry `readOnlyHint` annotations, and in practice a client enforcing read-only (e.g. Gemini CLI Plan Mode) leaves only the inspection subset callable — but **the server has no read-only mode of its own**; I read the full auto-generated options list and found none. What the server does offer: `--slim` (3 tools), six `--categoryX` toggles, `--redactNetworkHeaders` ("redacts some of the network headers considered sensitive before returning to the client"), and a filesystem sandbox — "By default, file-writing tools are restricted to the OS temp directory when no roots are configured" (`--filesystemRoot` / `--allowUnrestrictedPaths`). The README carries a blunt disclaimer: "`chrome-devtools-mcp` exposes content of the browser instance to the MCP clients allowing them to inspect, debug, and modify any data in the browser or DevTools. Avoid sharing sensitive or personal information that you don't want to share with MCP clients." Per-action confirmation: **UNDOCUMENTED** (only `handle_dialog` for the page's own dialogs). |
| **Puppeteer MCP (archived)** | Acting tools always present; no modes at all. One safety affordance: `puppeteer_navigate` has an `allowDangerous` flag for launch options. The README warns: "This server can access local files and local/internal IP addresses since it runs a browser on your machine." No read-only mode, no confirmation gates. |
| **browser-use 0.13.10** | Acting tools always present (`browser_click`, `browser_type`, and the escape hatch `retry_with_browser_use_agent`, "Run a complete browser automation task with an AI agent (use as last resort when direct control fails)" — which hands an autonomous agent the wheel). Read-only mode, per-action confirmation: **UNDOCUMENTED**. |
| **Browserbase / Stagehand** | `act` — "Perform an action on the page" — takes a free-text `action` string, so the acting surface is a single natural-language door. Read-only mode, confirmation gates: **UNDOCUMENTED**. |
| **Claude in Chrome** | **By far the most developed permission model of anything surveyed, and it is product-level rather than tool-level.** Three modes: "Manually approve (Manual): Claude pauses and asks for approval before each action"; "Automatically approve (Auto): Claude keeps working and reviews each action for safety, automatically blocking anything it determines to be unsafe"; "Skip all approvals (Skip): Claude doesn't pause to ask and nothing checks its actions automatically." Regardless of mode, explicit consent is always required for "Modifying permissions settings," "Granting authorizations," and "Inputting potentially sensitive information into websites." Site-level grants are two-tier — "Allow this action" (single use) vs "Always allow actions on this site" — and even under an always-allow grant Claude still asks before downloading files or entering sensitive data. A hard-prohibited category exists on top: purchases, account creation, handling credit-card/ID data, permanent deletions, executing trades, modifying system files. Source: support.claude.com Claude-in-Chrome permissions guide. |
| **Firecrawl MCP v3.2.1** | Mostly read-shaped by nature (scrape/crawl/map/search); `firecrawl_interact` adds browser actions. Read-only mode: **UNDOCUMENTED**. |
| **Browser MCP** | Acting tools always present, driving the **user's own logged-in Chrome profile** ("Uses your existing browser profile, keeping you logged into all your services"), which raises the stakes. Read-only mode, confirmation gates: **UNDOCUMENTED**. Unmaintained since 2025-04. |

---

### Request 5 — "What did you NOT read on that page?"
*Does the server report truncation, omissions, or hidden content?*

| Server | Evidence |
|---|---|
| **Playwright MCP v0.0.80** | **No truncation reporting documented.** I grepped the v0.0.80 README for truncat/limit/token: the only `limit` hit is `depth` — "Limit the depth of the snapshot tree" — which is an omission the *agent* requests, and nothing states that a depth-limited snapshot announces what was pruned. On what the snapshot covers: official docs describe it as "a structured tree of accessible elements with refs for interaction" and are silent on shadow DOM and iframes. A filed Playwright issue (#39955) reports the inverse problem — the snapshot "returns ALL elements in the DOM regardless of whether they are in the current viewport," causing agents to act on unreachable UI. So the honest summary is: over-inclusion is a known complaint, under-inclusion is unreported. |
| **Chrome DevTools MCP v1.8.0** | **Partial, and only in one subsystem.** The heap-snapshot tooling emits a genuine truncation notice: `Note: results are truncated, the following limits were reached: ${reached.join(', ')}.` [SOURCE-VERIFIED, `src/McpResponse.ts`]. Nothing equivalent exists for `take_snapshot` page content — I found no truncation or size accounting in the snapshot path. Page titles are silently clipped at 50 chars (`truncateTitle(title, maxLength = 50)`), which is cosmetic but is still an unannounced cut. |
| **Puppeteer MCP (archived)** | **UNDOCUMENTED.** No reads to truncate; whatever `puppeteer_evaluate` returns is returned. |
| **browser-use 0.13.10** | **Silent truncation, confirmed in source.** In `_get_browser_state`, each element's text is cut with `element.get_all_children_text(max_depth=2)[:100]` — a hard 100-character clip per element with no marker and no note. The state also reports only elements in the `selector_map` (interactive elements), so ordinary body prose never appears in `browser_get_state` at all, and nothing says so. [SOURCE-VERIFIED] |
| **Browserbase / Stagehand** | **UNDOCUMENTED.** `extract` returns `{success: true, data: extraction}` with no coverage or completeness metadata; whatever the extraction model chose to omit is invisible by construction. [SOURCE-VERIFIED] |
| **Claude in Chrome** | **The best answer found anywhere in this survey, and the only server that states the rule in the tool description itself.** `read_page`: "Output is limited to 50000 characters by default. **If the output exceeds this limit it is truncated at a line boundary, with a note giving the full size** — pass a larger `max_chars`, or use `depth`/`ref_id` to focus on part of the page." Three properties at once: a declared budget, a clean cut, and a reported true size with named remedies. Its `find` tool has the matching behavior for result sets: "If more than 20 matches exist, you'll be notified." [verbatim from live schemas, 2026-09-06] Caveat: `get_page_text` carries no equivalent statement — truncation behavior there is UNDOCUMENTED. |
| **Firecrawl MCP v3.2.1** | `onlyMainContent: true` deliberately discards nav, footers, and boilerplate, and `excludeTags` discards more. Whether the response enumerates what was dropped: **UNDOCUMENTED**. |
| **Browser MCP** | **UNDOCUMENTED.** |

**Shadow DOM, across the board.** No surveyed server's official documentation makes an explicit shadow-DOM support claim. Third-party analysis (QASkills.sh, 2026) reports that a11y-tree snapshots miss elements inside shadow roots on Lit/Shoelace-style component libraries, and that same-origin iframes appear inline while cross-origin iframes appear only as the iframe element. Treat that as third-party, not vendor-confirmed; the vendor position is silence.

---

### Request 6 — "Click send, and prove to me what happened."
*Does an action return a verified outcome, or fire-and-forget?*

| Server | Evidence |
|---|---|
| **Playwright MCP v0.0.80** | `browser_click`: "Perform click on a web page." What the response contains after the click is **not documented** in the README or the docs site. Behaviorally the server appends a fresh snapshot to responses under the default `--snapshot-mode full`, so the agent can *infer* the outcome by diffing state — and setting `--snapshot-mode none` removes even that. An open feature request (#1639, "Action tool responses should support inline accessibility snapshots, not just file references") indicates the response contract is still being argued about. There is no explicit "navigated to X" / "form submitted" assertion. |
| **Chrome DevTools MCP v1.8.0** | **The strongest outcome reporting of any surveyed server, and it is real, not marketing.** Every input tool wraps its action in `page.waitForEventsAfterAction(...)` and then calls `response.attachWaitForResult(result)` — verified in `src/tools/input.ts` for click, click_at, hover, fill, fill_form, and type_text. The response formatter then emits `Page navigated to ${url}.` when a navigation occurred, and surfaces any dialog the action opened as a `# Open dialog` block with type, message, and default value — plus a matching `structuredContent` object (`navigatedToUrl`, `dialog`). [SOURCE-VERIFIED, `src/McpResponse.ts`] The README's own phrasing: "Uses puppeteer to automate actions in Chrome and **automatically wait for action results**." Limits worth being fair about: `includeSnapshot` defaults to **false** on click/fill/fill_form/drag, so the post-action page state is opt-in; and what is proven is *navigation and dialogs*, not "the form was accepted." |
| **Puppeteer MCP (archived)** | Fire-and-forget. `puppeteer_click` — "Click elements on the page" — with no documented result payload. The only way to check is a follow-up screenshot or `puppeteer_evaluate`. |
| **browser-use 0.13.10** | Fire-and-forget, confirmed in source. The normal click path dispatches `ClickElementEvent` and returns the literal string `f'Clicked element {index}'`. One partial exception: the new-tab path returns `f'Clicked element {index} and opened in new tab {full_url[:20]}...'` — and note that URL is itself truncated to 20 characters. `_type_text`, `_scroll`, and `_go_back` follow the same "did the thing" string pattern. [SOURCE-VERIFIED] |
| **Browserbase / Stagehand** | `act` returns `JSON.stringify({ success: true, data: result })` [SOURCE-VERIFIED, `src/tools/act.ts`]. That `success` flag reports that Stagehand executed an action, not that the site accepted it — and since the action was chosen by a second LLM from a free-text instruction, "success" also does not confirm the *intended* element was the one clicked. |
| **Claude in Chrome** | `computer` with `left_click` is a coordinate/ref-based click; the schema documents no post-action outcome payload — outcome verification is left to a follow-up `screenshot` or `read_page`. The tool's own guidance is visual-loop shaped: "Whenever you intend to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor... If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your click location." Structured outcome reporting: **UNDOCUMENTED**. |
| **Firecrawl MCP v3.2.1** | `firecrawl_interact` performs actions; documented outcome payload: **UNDOCUMENTED**. The scrape-shaped tools return the resulting page content, which is de facto proof of the end state. |
| **Browser MCP** | Fork of Playwright MCP's click; same undocumented response contract, on a codebase last touched 2025-04. |

---

## PER-REQUEST SYNTHESIS — "the typical answer is X"

**1. Reading an article.** The typical answer is: you get an accessibility-tree dump, and you get all of it. Playwright MCP and Chrome DevTools MCP both return a11y snapshots; Puppeteer MCP returns nothing structured at all and makes the agent write JavaScript; Browser MCP inherits Playwright's snapshot. Only two of eight return anything resembling prose, and they take opposite routes: Firecrawl converts to markdown server-side (`onlyMainContent: true`), and Claude in Chrome has a dedicated `get_page_text` that prioritizes article content. Two more (browser-use, Browserbase) answer article questions by spending a *second LLM call* on the page and handing back that model's summary, which trades tokens for a different opacity. On scale, the vendor claim and the field reports are far apart: Playwright's docs advertise "~200-400 tokens per snapshot," while an independent measurement on a real enterprise page reports "between 10,000 and 50,000 tokens" per snapshot and ~114,000 tokens across a normal session. Nobody budgets automatically; the knobs that exist (`depth`, `target`, `--snapshot-mode`, `--mobile`, `onlyMainContent`) all require the agent to already suspect the page is expensive.

**2. Finding one item in a long list.** This is the request where the field moved most recently, and any comparison written before July 2026 will get it wrong. Playwright MCP shipped `browser_find` in v0.0.78 (2026-07-09) — text or regex over the snapshot, returning snippets with tree paths, explicitly justified as "cheaper than capturing the whole snapshot." Claude in Chrome has `find` with natural-language queries, capped at 20 results with an explicit over-cap notification. Those two are genuinely equipped. Everyone else is not: Chrome DevTools MCP, Puppeteer MCP, browser-use, and Browser MCP have no content-search tool, and the fallback is snapshot-scroll-snapshot (browser-use scrolls a fixed 500px per call and returns only `Scrolled down`). Pagination of *page content* is universally absent — Chrome DevTools MCP has `pageIdx`/`pageSize`, but only on network logs, console logs, and heap queries, never on the page. For 771 issues, the two searchers find a match or overflow; the rest scroll.

**3. Cost preview before a read.** The typical answer is that nothing exists, and this is the cleanest gap in the entire survey. Zero of eight servers document a tool that reports what a read would cost before the read happens. Every mitigation on offer is either prevention (shrink the read you already decided to take) or configuration (turn off tool groups at startup). The nearest approach is Claude in Chrome's cap-then-report behavior on `read_page`, which tells you the true size only after you have paid for a 50k-character attempt — a probe, not a preview. Two servers make the situation actively worse by adding an *undisclosed* second cost: browser-use bills the user's own OpenAI key for `browser_extract_content`, and Browserbase bills its own Gemini inference into your credit balance, neither announced at call time.

**4. Permission to act.** The typical answer is that write tools are always loaded and there is no server-side brake. Playwright MCP and Chrome DevTools MCP both ship click/type/fill/evaluate in the default surface, both annotate tools with MCP `readOnly` hints, and **neither has a server-level read-only flag** — a client that enforces read-only (Plan Mode and similar) gets the effect, but the server never refuses. Puppeteer MCP, browser-use, Browserbase, Firecrawl, and Browser MCP document no gate of any kind. The safety machinery that does exist is aimed elsewhere: origin allow/block lists, isolated profiles, network-header redaction, filesystem roots, and dialog handling. The one genuine exception is Claude in Chrome, whose permission model is a product feature rather than a tool feature — three approval modes, site-level grants with a single-use/always split, a category of actions that always require consent regardless of mode (permissions changes, authorizations, sensitive-data entry), and a hard-prohibited list (purchases, account creation, trades, permanent deletion). Notably, that model lives in the extension's UI, not in the tool schemas, so it does not travel to a generic MCP client.

**5. Reporting what was NOT read.** The typical answer is silence, and in two measurable cases silence over a real cut. browser-use clips every element's text at exactly 100 characters and truncates a new-tab URL to 20, with no marker either time. Chrome DevTools MCP silently clips page titles at 50 characters, and does have a real truncation notice — "Note: results are truncated, the following limits were reached" — but only inside the heap-snapshot subsystem, never for page content. Playwright MCP documents `depth` as a way to prune the tree but never says the pruned result announces what it dropped; the community complaint there is the opposite failure, snapshots including off-viewport elements the agent then tries to click. Exactly one server states the honest contract in the tool description itself: Claude in Chrome's `read_page` declares its 50,000-character budget, promises to cut at a line boundary, and returns "a note giving the full size" with three named remedies. On shadow DOM, no vendor in the survey makes any support claim at all — a11y-snapshot servers inherit whatever the accessibility tree exposes, and the only statements about shadow roots and cross-origin iframes come from third-party testing write-ups.

**6. Proving what a click did.** The typical answer is a confirmation that the *call* ran, not that the *page* changed. browser-use returns the string `Clicked element 3`. Puppeteer MCP returns nothing documented. Browserbase returns `{success: true}` from a second LLM's chosen action, which confirms execution and not intent. Playwright MCP leaves the response contract undocumented and relies on the next snapshot to show the difference, which vanishes under `--snapshot-mode none` and is the subject of an open design issue. Chrome DevTools MCP is the clear outlier and deserves credit: it wraps every input action in `waitForEventsAfterAction`, then reports `Page navigated to <url>` and any dialog the action opened, in both prose and `structuredContent`. Its limits are equally worth stating — the post-action snapshot is opt-in (`includeSnapshot` defaults to false), and what it proves is navigation and dialogs, not that a submission was accepted. Across all eight, nobody claims to verify a form submission *result*.

---

## THINGS COMPETITORS DO BETTER (or at least as well) — include these honestly

1. **Chrome DevTools MCP genuinely verifies action outcomes.** `waitForEventsAfterAction` + `attachWaitForResult` on click, click_at, hover, fill, fill_form, and type_text, producing `Page navigated to <url>` and structured dialog reporting with a `structuredContent` mirror. This is the single strongest competitor capability found, it is real in source, and any "everyone else is fire-and-forget" line on the product page would be wrong. The correct framing is that CDT proves *navigation and dialogs*, not submission results.
2. **Playwright MCP has had a real page-search tool since 2026-07-09.** `browser_find` (text or regex, returns snippets under their tree path) with the vendor's own efficiency rationale. Do not claim competitors have no search. Its real limits — snapshot-scoped, no pagination — are the fair angle.
3. **Claude in Chrome's truncation honesty is better than a typical implementation.** Declared 50k budget, line-boundary cut, note giving the full size, named remedies (`max_chars`, `depth`, `ref_id`), plus `find`'s over-20 notification. If KS4Web's completeness story is the differentiator, this is the one comparison where the honest answer is "an existing tool already does a version of this."
4. **Claude in Chrome's permission model is more developed than any server-side gate.** Three modes, site-level grants, always-confirm categories, hard-prohibited actions. Caveat that helps the KS4Web story: it is an extension product feature, not something a generic MCP client inherits.
5. **Chrome DevTools MCP's tool-surface budgeting is real.** `--slim` (3 tools), six `--categoryX` toggles, `--redactNetworkHeaders`, and a temp-dir filesystem sandbox by default. That is a thoughtful answer to the tool-schema cost problem even though it does nothing for page-read cost.
6. **Playwright MCP's snapshot-shrinking knobs are more numerous than expected.** `depth`, `target`, `boxes`, `--snapshot-mode none`, and `--mobile` documented explicitly as a token saver ("Mobile pages are usually lighter, which saves tokens").
7. **Microsoft says the quiet part out loud.** The playwright-mcp README concedes that CLI+Skills beat MCP on token efficiency because MCP calls "avoid loading large tool schemas and verbose accessibility trees" only in the CLI case, and positions MCP for workflows "where maintaining continuous browser context outweighs token cost concerns." Quoting a vendor's own caveat is stronger and fairer than asserting it ourselves.
8. **Firecrawl's markdown path is the right shape for request 1.** `formats: ["markdown"]` + `onlyMainContent: true` is a clean article read, and `maxAge` caching is a real cost lever. It is not a browser-automation peer (no acting, no live page state), so compare it only on the reading row.
9. **Chrome DevTools MCP's design principles document the right instincts** even where the implementation has not reached page content: "Token-Optimized: Return semantic summaries... Files are the right location for large amounts of data" and "Reference over Value... never the raw data stream."
10. **Browserbase absorbs its own inference cost** on the hosted server ("we host the server and provide the LLM costs for Gemini"), which is a real user benefit even though it makes the true cost of a read invisible.

---

## CAVEATS FOR WHOEVER WRITES THE PAGE COPY

- **Do not write "no competitor can search a page."** Two can, and one of them is Microsoft's. Write about scope and pagination instead.
- **Do not write "every competitor is fire-and-forget on clicks."** Chrome DevTools MCP is not.
- **Do not write "no competitor reports truncation."** Claude in Chrome does, in the tool description itself.
- **The cost-preview row (request 3) is the one where a clean sweep is defensible.** Zero of eight document a pre-read cost estimate. That is the strongest honest claim available.
- **The read-only-mode row is nearly as clean.** Playwright MCP and Chrome DevTools MCP both lack a server-level read-only switch (I checked both option lists directly); the rest document nothing. Client-side Plan Mode is the industry workaround, and saying so is more credible than ignoring it.
- **Version-date every competitor claim on the page.** Playwright MCP moved on request 2 in July 2026; something else will move before the page is stale. Two of the eight surveyed (Puppeteer MCP, Browserbase self-host) are formally archived, and Browser MCP has been untouched since April 2025 — comparing against archived software should be labeled as such, not quietly counted as a peer.
- **Token numbers:** the "~200-400 tokens" figure is Playwright's own doc; the "10,000-50,000 per snapshot / ~114,000 per session" figure is Provar's third-party measurement against `@playwright/mcp@0.0.75`. Attribute both. Do not present either as a neutral benchmark.

---

## SOURCE URLS

- Playwright MCP repo/README (v0.0.80): https://github.com/microsoft/playwright-mcp — raw README: https://raw.githubusercontent.com/microsoft/playwright-mcp/main/README.md
- Playwright MCP docs: https://playwright.dev/mcp/introduction and https://playwright.dev/mcp/snapshots
- Playwright MCP issue #39955 (off-viewport elements in snapshot): https://github.com/microsoft/playwright/issues/39955
- Playwright MCP issue #1639 (action responses / inline snapshots): https://github.com/microsoft/playwright-mcp/issues/1639
- Chrome DevTools MCP repo: https://github.com/ChromeDevTools/chrome-devtools-mcp
- Chrome DevTools MCP tool reference: https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/tool-reference.md
- Chrome DevTools MCP configuration: https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/main/docs/configuration.md
- Chrome DevTools MCP design principles: https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/main/docs/design-principles.md
- Chrome DevTools MCP source (`src/tools/input.ts`, `src/McpResponse.ts`): https://github.com/ChromeDevTools/chrome-devtools-mcp/tree/main/src
- Puppeteer MCP (archived): https://github.com/modelcontextprotocol/servers-archived/tree/main/src/puppeteer
- browser-use MCP server docs: https://docs.browser-use.com/open-source/customize/integrations/mcp-server
- browser-use MCP server source: https://github.com/browser-use/browser-use/blob/main/browser_use/mcp/server.py
- Browserbase MCP (archived): https://github.com/browserbase/mcp-server-browserbase — hosted: https://www.browserbase.com/mcp
- Stagehand MCP docs: https://docs.stagehand.dev/v3/integrations/mcp/introduction
- Claude in Chrome docs: https://code.claude.com/docs/en/chrome
- Claude in Chrome permissions guide: https://support.claude.com/en/articles/12902446-claude-in-chrome-permissions-guide
- Claude in Chrome safety: https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely
- Firecrawl MCP tools: https://docs.firecrawl.dev/mcp-server/tools — repo: https://github.com/firecrawl/firecrawl-mcp-server
- Browser MCP: https://github.com/BrowserMCP/mcp
- Provar, "The 114K Token Problem" (third-party measurement, © 2026): https://provar.com/blog/thought-leadership/the-114k-token-problem-why-playwright-mcp-burns-your-ai-coding-agents-control-on-salesforce/
- QASkills.sh, Playwright iframe & Shadow DOM guide (third-party, 2026): https://qaskills.sh/blog/playwright-iframe-shadow-dom-guide

END OF REPORT
