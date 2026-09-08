<!-- mcp-name: io.github.nometalalchemist/kitchensink4web -->

# 🚰 KitchenSink4Web

Everything plus the kitchen sink for the open web: a browser MCP server that reads a whole page
for the price of a paragraph, and starts out unable to change anything at all.

## Two numbers that matter

The same page, read two ways. A raw dump of the Treaty of Versailles article on Wikipedia costs
33,073 tokens of your assistant's memory. This server's first read of it costs 4,437. The
difference is not compression, it is a different product: a map of the page with a price on every
region, instead of the whole page whether you wanted it or not.

Numbers on this page are measured by scripts in `tools/`, not written by hand. Re-run them
yourself; the README is regenerated from their output.

```
.venv/Scripts/python.exe -X utf8 tools/measure_readme_numbers.py
```

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

The server starts lite: reading, navigation, and session management, 19 tools. Capability packs
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

## Context cost (measured)

| Surface | Tokens |
|---|---|
| Lite tool surface | 5.8k |
| Full surface (all packs) | 15.3k |
| First read of the Treaty of Versailles article on Wikipedia | 4,437 |
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

2,055 tests, of which 733 drive a real browser. Beyond the suite, every release passes gate
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

## Requirements

- Python 3.12 or newer (developed on 3.14)
- [uv](https://docs.astral.sh/uv/) on your PATH for the Claude Desktop bundle route, which uses
  `uvx` to start the server
- Playwright, installed as a dependency of this package
- A browser engine, downloaded by Playwright on first use rather than shipped in the wheel
- Windows, macOS, or Linux

## Install

Claude Desktop: install the `.mcpb` bundle and pick what you want on the
install screen. The checkboxes are the whole configuration: one to allow
clicking and typing (off means read-only browsing, the shipped default),
and one per capability pack. Launching the bundle requires `uv` (the `uvx`
command) on your machine; the server itself is fetched from PyPI on first
launch and drives its own bundled Chromium, never your browser or your
profile.

Any other MCP client:

```
uvx kitchensink4web
```

or

```
pip install kitchensink4web
python -m kitchensink4web.server
```

Packs and read-only mode are chosen at launch (`--packs`, `KS4WEB_MODE`,
`KS4WEB_ALLOW_ACTING`) and are identical for every connection to the
process.

> **Tip for Claude Desktop:** in Tool permissions, set this server's
> **Read-only tools** group to **Always Allow**. Those tools cannot change
> anything on any page, and it stops most permission prompts.

## License

**AGPL-3.0.** Free for individuals and personal use, and it stays that way.

Companies building it into their own products need a commercial license, with
terms worked out case by case.
[Open an issue](https://github.com/nometalalchemist/KitchenSink4Web/issues/new?template=commercial_license.yml)
and we will talk it through.

---

*Not affiliated with or endorsed by Google, Mozilla, Microsoft, or any website this server
visits. Chrome, Chromium, Firefox, and Edge are trademarks of their respective owners, used
nominatively to name the browsers this server can drive.*
