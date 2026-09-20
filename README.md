<!-- mcp-name: io.github.nometalalchemist/kitchensink4web -->
<!-- The line above verifies the name server.json declares today. The line below
     is the org namespace the next version bump moves to; both may sit here, because
     the registry looks for the one string that matches server.json. -->
<!-- mcp-name: io.github.KitchenSink4AI/kitchensink4web -->

# 🚰 KitchenSink4Web Community Edition

[![Tests](https://github.com/KitchenSink4AI/KitchenSink4Web/actions/workflows/tests.yml/badge.svg)](https://github.com/KitchenSink4AI/KitchenSink4Web/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/kitchensink4web)](https://pypi.org/project/kitchensink4web/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

[Landing page](https://kitchensink4.ai/KitchenSink4Web/) · [llms.txt](https://kitchensink4.ai/KitchenSink4Web/llms.txt) (machine-readable capability manifest for agents and LLM crawlers)

**Read websites and extract data with your AI assistant, read-only by default, with clicking and typing when you allow it.**

Read websites and pull out the data you need from Claude Code, Codex CLI, Copilot CLI or any other MCP client that runs local tools. KitchenSink4Web drives a browser on your computer, returns a page within a size budget and says what it left unread, and exports tables to CSV or JSON. It starts read-only; clicking, typing and form filling are switched on only when you choose. Websites receive ordinary browsing requests; what reaches your AI provider is decided by your AI app. The Community edition is free under the AGPL. The Business edition adds a Windows installer, a signed update channel, a license your company can approve and support.

**Works on:** Windows, macOS and Linux for the browser tools. Image-text recognition uses Windows OCR. A browser download and some optional dependencies may be needed.

## Install

Pick the route for your AI app. The commands go in PowerShell on Windows or a terminal on macOS and Linux, not into an AI chat. The package routes need Python 3.12 or newer.

**Claude Desktop**

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then quit and reopen Claude Desktop. Download the `.mcpb` file from [KitchenSink4Web releases](https://github.com/KitchenSink4AI/KitchenSink4Web/releases/latest). In Claude Desktop open Settings, then Extensions, then Advanced settings, then Install extension, and choose the file. The bundle fetches the Python package the first time it starts, so the first launch needs a network connection. Restart your session and check that the tools show as connected.

**Claude Code or Codex CLI**

Install uv, then run the line for your app and restart your session:

```sh
claude mcp add web -s user -- uvx kitchensink4web
```

```sh
codex mcp add web -- uvx kitchensink4web
```

**Any other local MCP client**

Use `uvx` as the command and `kitchensink4web` as its argument, or install the package and use `kitchensink4web` as the server command:

```sh
pip install kitchensink4web
```

Then follow your client's guide for adding a local MCP server. Installing the package on its own does not connect it to an AI app.

**Business edition**

Compare the editions on the [pricing page](https://kitchensink4.ai/pricing/). Already purchased? Your Windows installer and download link are in your [license portal](https://get.kitchensink4.ai/my-license/).

## What it can do

53 tools with every pack and browser actions enabled. The default read-only lite launch exposes 12; lite with actions has 20.

- Read a page within a chosen size budget and see what was left unread.
- Find one section or element without fetching the whole page again.
- Extract tables, lists and article text, then export CSV or JSON.
- Take screenshots or save a page as PDF.
- Read only what changed on a page you already read.
- Watch a page for changes while the server runs.
- Turn on clicking, typing and form filling when a task needs them.
- Record a browser task and replay it with checks, with the workflow pack.
- Run automated accessibility checks with the optional dependency.

What is available depends on the packs you enable and the applications installed. The full tool reference is below.

## Business edition

Need a license your company can approve and a setup someone supports? The Business edition pairs these tools with a Windows installer, a signed update channel and support under the Business terms. Update checks tell you when a covered release is available; nothing installs on its own. Compare the options on the [pricing page](https://kitchensink4.ai/pricing/). The Community edition stays free under the AGPL, including business use that meets its terms.

## Privacy Policy

The tools run on your computer, and KitchenSink4AI receives no documents and no usage data from them. Your AI app may send prompts, file contents and tool results to its own provider under that app's settings and terms. Installing downloads packages, and the Community version check contacts PyPI unless you disable it; those requests carry connection details such as your network address and never your documents. The browser connects to the websites you ask it to use, and those sites see ordinary browsing requests. A missing tokenizer table may be downloaded once; the text being measured is never sent. Cloud folders and backups follow their own settings. The [Privacy Policy](https://kitchensink4.ai/privacy/) covers the product, purchases and support records.

*Not affiliated with or endorsed by Google, Mozilla, Microsoft, or any website this server
visits. Chrome, Chromium, Firefox, and Edge are trademarks of their respective owners, used
nominatively to name the browsers this server can drive.*

## The cheap first read

`get_page_view` returns the page's shape: what it is, what is on it section by section, what each
section costs to open, and what the sensible next call would be. You set the budget and the read
never exceeds it, so the question is never whether a page fits, only how much detail you bought.
Every read ends with a completeness block naming what was left out and what it would cost to get
it back. Nothing is swept under the rug.

From there the pattern is cheap and gets cheaper. Expand one region instead of raising the
budget. Chain delta reads: pass the token a read returns and the next read prices only what
changed. Elements come back as short-lived refs your assistant can act on directly, and searches
by text and role survive re-renders that break refs.

Open shadow roots are read and their contents are actable like anything else, which is what makes
component-built sites (Reddit, MDN, most of the modern web) readable at all. Closed roots cannot
be reached by any tool; they are counted and reported rather than silently skipped. Same-origin
iframes are read and searched like the page they sit in, each labeled with its own origin; a
cross-origin frame is counted and named, never entered.

## The packs

The server starts lite: reading, navigation, and session management, 20 tools. Capability packs
are chosen at launch and are fixed for the whole session, which means an absent pack is provably
absent, not merely switched off:

| Pack | What you get |
|---|---|
| extract | Tables, lists, links, and article text, with CSV and JSON export. |
| capture | Screenshots (passwords blurred), PDF export, and saving pages as files. |
| network | See the requests a page makes behind the scenes. Useful for debugging websites; most people leave it off. |
| storage | Use with care. Saves a signed-in session so Claude does not have to log in every time. It saves the session, never your password; treat the saved file like one anyway. |
| files | Download files from pages into one folder, and upload files into page forms. Every one asks you first. |
| diagnostics | Lets Claude run JavaScript on a page, one script at a time, each one shown to you for approval first. This is the most powerful and most dangerous setting on this page. Leave it off unless you know you need it. |
| workflows | Record a multi-step task once and replay it later. Every replay checks that the page still matches before anything runs. |
| accessibility | Checks a page against the WCAG accessibility rules using axe-core, groups what it finds by rule, and says plainly what automated testing cannot check. Needs an optional extra installed; the tool tells you how if it is missing. |

## Browsers and lanes

The default lane drives the server's own bundled Chromium. It never touches your browser or your
profile; sessions open in a fresh profile that is deleted on close unless you explicitly save
signed-in state to a file.

Lane B drives a browser you already have installed (Chrome, Edge, or Firefox), still with its own
separate profile, never yours. Installed Firefox is the lane to reach for on research-heavy work:
sites that turn away automated Chromium routinely serve Firefox normally, and both Firefox lanes
pass bot checks that block headless Chromium. That is lane steering, not evasion; the server does
not disguise what it is, it just lets you use a browser the site treats better.

Signed-in sessions are saved and reloaded with `save_auth_state` and `auth_state=` on open. The
state file records when its session cookies expire, and loading a stale file says so plainly
instead of letting the login fail mysteriously.

`manage_session(action='status')` reports which browsers are installed and which lane it would
recommend for the page you are on. It never switches lanes for you.

## The safety model

A browser is where your logins, your money, and your mistakes all live, so the safety layer is
the product, not a feature of it.

**Read-only unless you say otherwise.** Out of the box the tools that click, type, and submit do
not exist. They are not disabled, they are absent from the tool list, and no instruction on any
webpage can talk your assistant into using a tool that is not there. One switch at install
(`allow acting` in the bundle, `KS4WEB_ALLOW_ACTING=true` elsewhere) brings them in.

**Credential blindness.** The server never reads what you type into password fields, and secrets
observed in cookies and site storage are vaulted: they cannot leak into your assistant's
conversation, because the text that would carry them is redacted before it leaves the server.

**Hidden text is evidence, not instructions.** Text a page hides from human eyes is the oldest
trick for slipping commands to an AI. This server strips it from the reading channel, counts it,
reports the count, and wraps everything a page says in labeled provenance markers, so your
assistant always knows which words came from a stranger.

**Confirmation gates.** Form submissions, payments, and page scripts stop and ask you first,
through the client's own confirmation prompt. As of 2026-09 that prompt displays in Claude
Desktop and Claude Code; the claude.ai web client does not display it yet, so gated actions
refuse there instead of proceeding unconfirmed.

**Honest refusals.** When something cannot be done, from a login wall to a bot check to a page
that crashed its own renderer, the answer names what stood in the way and what to try next. A
refusal that explains itself is cheaper than a retry loop.

### Two different things ask you for permission

Your MCP client's own permission prompt names a tool (something like `mcp__web__type_text`) and
comes from the client, not from KS4Web; approving a read-only tool group there is safe and stops
most of the asking. A KS4Web gate names an action in plain words ("submitting this form sends a
password") and cannot be pre-approved away for payments, credentials, posts, deletions, or legal
assent. If a prompt names a tool, it is the client; if it names what is about to happen in the
world, it is KS4Web.

### Consent scope

Out of the box the consent scope is `research`: reading and navigation are free, query-shaped
submissions (a search box) proceed, and everything else asks first. The `full` scope lets ordinary
form submissions proceed without asking; the irreducible set asks under every scope, always. The
install screen's "Submit routine forms without asking each time" checkbox is the whole choice.

The GET rule is the one place page-authored text classifies down rather than up: a form that looks
like a search is allowed to proceed as one, and what a mistaken call in that direction buys is an
unprompted ordinary submission, never a payment, credential, post, or deletion; those always ask.
In the other direction, a submit button that says nothing recognizable in any shipped language
passes ungated under the `full` scope; if that risk matters to you, stay on `research`.

### Client compatibility

If a feature refuses with `CONFIRMATION_REQUIRED` on claude.ai web, it works on Desktop and Code.

| Client | What works |
| --- | --- |
| Claude Desktop | Everything, with confirmations rendered. |
| Claude Code | Everything, with confirmations rendered. |
| claude.ai web | All reading, navigation, and search. Gated actions refuse honestly because no confirmation can render; pre-authorized classes work if configured at launch. |

## Two numbers that matter

The same page, read two ways. A raw dump of the Treaty of Versailles article on Wikipedia costs
33,073 tokens of your assistant's memory. This server's first read of it costs 4,445. The
difference is not compression, it is a different product: a map of the page with a price on every
region, instead of the whole page whether you wanted it or not.

Numbers on this page are measured by scripts in `tools/`, not written by hand. Re-run them
yourself; the README is regenerated from their output.

```
.venv/Scripts/python.exe -X utf8 tools/measure_readme_numbers.py
```

## Context cost (measured)

| Surface | Tokens |
|---|---|
| Lite tool surface | 6.9k |
| Full surface (all packs) | 17.9k |
| First read of the Treaty of Versailles article on Wikipedia | 4,445 |
| Delta read after one click | 82 |

The budget ladder has 16 rungs; every read reports which rung it printed at and what a deeper
read would cost. Inside a subagent, start at `budget_tokens=2500`; tool results are capped more
tightly there.

## Update check (opt-out)

The server compares its version against PyPI's when you call
`manage_session(action='status')`, and never at any other time: nothing runs at startup and nothing
runs on a background thread. At most one request per seven days, with a two-second timeout. It never
installs anything. The request is a plain HTTPS GET to pypi.org for this package's public release
index; it sends no identifier, no usage data, no page content and no session state. A check that
could not complete says so and says how long ago the last successful one was, rather than showing
nothing. `KS4WEB_UPDATE_CHECK=off` switches it off, and the status report then says it is off; the
older `KS4WEB_NO_UPDATE_CHECK=1` spelling is still honored.

## Testing

2,066 tests, of which 733 drive a real browser. Beyond the suite, every release passes gate
batteries that re-run the adversarial findings of four attack rounds: prompt injection through
page content, hidden-text smuggling, credential-theft attempts, gate bypasses, workflow
replay tampering, and resource abuse. The gates are not aspirational; each one exists because an
adversarial round or a field tester actually broke something, and the fix is pinned by the test
that would catch its return.

The current tuning came out of a live field campaign: two sessions, twelve real sites, three
browser engines, and 141KB of logged friction, retests, and design notes. The findings, and what
shipped in response, are in the repository history rather than a marketing page.

## Maturity: what the version number does and does not claim

This is the newest member of the family, and the version number says so honestly. It grew up
under the house rules: every claim measured, every release attacked before it ships, every
refusal honest about its reason. What it has not had yet is a long life in strangers' browsers.
The safety net while it earns one: it starts read-only, it prices every read before taking it,
and it tells you what it could not see. Bring it your strangest pages and file what breaks.

## Known limits

- Cross-origin iframes are never entered; the completeness block names each frame and says why.
  Same-origin iframes are read, searched, and acted in, each labeled with its own origin.
- Closed shadow roots cannot be reached by any tool. They are counted so you can tell a
  component-heavy page from an empty one.
- Confirmation-gated actions (auth loading, page scripts, submits) refuse on the claude.ai web
  client until it renders MCP confirmation prompts; Claude Desktop and Claude Code work today.
- Bot walls and CAPTCHAs are reported, never solved or evaded. The Firefox lanes get through
  device checks that block headless Chromium; a wall that blocks everything is a wall.
- `sendBeacon` and ping requests bypass network routing rules; that is a Playwright limit,
  documented rather than hidden.

**Automated accessibility checking finds a minority of real-world issues.** Deque, who build the
axe-core engine this tool runs, publish 57% as their own figure for their own tooling. A clean
report here means the automated checks passed, not that the page is accessible. There is no score,
because every 0-to-100 accessibility number is somebody's weighting rather than a measurement.

**Nothing taps you on the shoulder.** No MCP client in use today delivers a server-initiated
message into a conversation, so monitors run only while KS4Web runs, and the report is how you ask
what happened; after a restart, the report names the window that went unchecked. A monitor watches
one URL for one deterministic change and does not understand what changed: `content_hash` is noisy
on pages with clocks or counters, only the main document is watched, and a change that appeared and
reverted between two checks is invisible. A monitor cannot get past a login or a bot wall, and one
that keeps failing pauses itself rather than hammering the site. Five minutes minimum between
checks; everything stays on this machine.

**A session handle transfer moves a live session between conversations on the same machine**,
inside the same running KS4Web. Nothing is copied: it is the same browser, so a page the other
conversation navigated has lost your refs, and the report says which. It does not survive a server
restart, and it does not cross between Claude Desktop's chat and Code panels, which run separate
servers. The session dies with KS4Web on purpose; that is what keeps orphaned browsers off your
machine. A token works once, expires in an hour, and is not a lock: any conversation on this server
can already see the session. The budget travels with the session.

**Two identities cost two browser processes and two profile directories**, which is real memory.
The action budget is shared across them on purpose, so opening a second identity does not double
what a session may do to the world, and two contexts visiting the same site cost one origin against
the origin budget. Auth state saves and loads per identity. Closing one identity leaves the others
working; closing the last one tells you to close the session instead. Every context shares the
session's lane and emulation; two lanes means two sessions.

**The lane database is a list of which websites this computer has visited with which browser**:
hostnames and dates, no pages, no addresses, nothing typed. It exists so a site that refused one
browser can be read with one that works. It is stored on this machine, it never leaves unless you
export it, learning can be turned off with one switch, and one call erases it entirely.

## Install options and settings

The install routes are at the top of this file. This section covers what you
choose when the server starts.

The Claude Desktop bundle puts the whole configuration on its install screen
as checkboxes: one to allow clicking and typing (off means read-only
browsing, the shipped default), and one per capability pack. The server
drives its own bundled Chromium, never your browser or your profile.

Packs and read-only mode are chosen at launch (`--packs`, `KS4WEB_MODE`,
`KS4WEB_ALLOW_ACTING`) and are identical for every connection to the
process.

> **Tip for Claude Desktop:** in Tool permissions, set this server's
> **Read-only tools** group to **Always Allow**. Those tools cannot change
> anything on any page, and it stops most permission prompts.

## Privacy Policy

KitchenSink4Web runs on your computer and processes the pages and browser actions you request. It sends no page content or usage telemetry to KitchenSink4AI. Tool results return to your MCP client; your AI provider handles those results under its own settings and privacy policy.

Browsing contacts the websites you visit. If you enable writing and clicking and authorize a form submission or other action, the destination receives that request and any submitted information under its own policies. Read-only operation is the default.

Browser state, downloaded files and local logs stay where you or your software store them. Retention depends on your local session and storage settings. The server may download a public tokenizer table and, when session status is requested, check PyPI's public package endpoint for updates. These requests carry no page content or customer identifier to KitchenSink4AI; the external hosts receive ordinary network request information. Set `KS4WEB_UPDATE_CHECK=off` to disable the update check. It does not install updates.

If you contact us, the information you choose to send is handled under our [Privacy Policy](https://kitchensink4.ai/privacy/), which covers service providers, retention and contact rights. Do not include private pages or session data in public issue reports. Privacy questions: admin@kitchensink4.ai.

## License

KitchenSink4Web is dual-licensed:

**AGPL-3.0 (open source).** Free for anyone (individuals, academics, and businesses) for any use that complies with the AGPL's terms. Those terms include sharing source, including your modifications, when you distribute the software or make it available over a network.

**Commercial license.** For organizations that want to build KitchenSink4Web into their own products or services without the AGPL's source-sharing obligations. Contact licensing@kitchensink4.ai.

Copyright (c) 2026 Alvut Consulting, LLC. KitchenSink4AI is a product line of Alvut Consulting, LLC.

---

*Not affiliated with or endorsed by Google, Mozilla, Microsoft, or any website this server
visits. Chrome, Chromium, Firefox, and Edge are trademarks of their respective owners, used
nominatively to name the browsers this server can drive.*
