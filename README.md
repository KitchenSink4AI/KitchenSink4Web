<!-- mcp-name: io.github.nometalalchemist/kitchensink4web -->

# 🚰 KitchenSink4Web

Everything plus the kitchen sink for the open web: a browser MCP server that reads a whole page
for the price of a paragraph, and starts out unable to change anything at all.

## Two numbers that matter

The same page, read two ways. A raw dump of the Treaty of Versailles article on Wikipedia costs
33,073 tokens of your assistant's memory. This server's first read of it costs 4,306. The
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
| extract | Pulls structured data off pages: tables, lists, links, and page details, with CSV and JSON export, and reads long documents page by page so one read never floods the conversation. |
| capture | Takes screenshots (passwords masked) and saves pages as PDF or archive files. |
| network | Shows the page's network requests and responses, and lets Claude block or mock them for testing. |
| storage | Works with cookies and site storage, and saves a signed-in session to a file so it can be reused next time. It saves the session, never the password. [COPY PENDING: manifest.pack_storage.danger | CAUTION tier] FACTS TO CONVEY: this pack reaches saved sign-ins. It can write a signed-in session to a file on this machine and load one back, which means a file that grants access to your account exists on disk until you delete it. It stores the session, never the password, and loading one stops to ask first. |
| files | Downloads files from pages into one dedicated folder, fetches a file by URL through the same checks, uploads files into page forms, and reads or writes the clipboard, with every write stopping to ask first. [COPY PENDING: manifest.pack_files.danger | CAUTION tier] FACTS TO CONVEY: this pack reaches your filesystem and your clipboard. Downloads land in one dedicated folder and nowhere else, uploads send a file you name into a page's form, and a clipboard write stops to ask first. What leaves this machine is whatever you upload. |
| diagnostics | Reads the page's own error messages and console output, and can run a page script only after you confirm it. [COPY PENDING: manifest.pack_diagnostics.danger | STRONG WARNING tier] FACTS TO CONVEY: this pack carries evaluate_script, which runs arbitrary JavaScript inside the page with that page's full privileges, including its logged-in session. Every script is shown and confirmed before it runs, one confirmation per script, and none runs unattended. The rest of the pack only reads the page's own errors and console output. |
| workflows | Records a multi-step flow once and replays it later, checking every step still matches the page before anything runs. |
| accessibility | Checks a page against the WCAG accessibility rules using axe-core, groups what it finds by rule, and says plainly what automated testing cannot check. |

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
| Lite tool surface | 6.5k |
| Full surface (all packs) | 16.0k |
| First read of the Treaty of Versailles article on Wikipedia | 4,306 |
| Delta read after one click | 82 |

The budget ladder has 16 rungs; every read reports which rung it printed at and what a deeper
read would cost. Inside a subagent, start at `budget_tokens=2500`; tool results are capped more
tightly there.

## Update check (opt-out)

<!-- [COPY PENDING: readme.update_check] The prose below is a plain factual
placeholder written mechanically in fix wave 10, not final copy. The section
it replaced described the superseded design (a startup thread, a 14-day
window, and the KS4WEB_NO_UPDATE_CHECK variable) and was factually wrong
after the conversion, so it could not be left standing. FACTS TO CONVEY:
nothing runs at startup and nothing runs on a thread; the check happens only
when you call manage_session(action='status'); at most one request per seven
days, cached in the state directory; a two-second timeout; it never installs
anything; the only thing it sends is a plain HTTPS GET to pypi.org for this
package's public release index, carrying no identifier, no usage data, no
page content and no session state; a check that could not run says so and
says how old the last successful one was, rather than showing nothing;
KS4WEB_UPDATE_CHECK=off switches it off and the status then says it is off;
the older KS4WEB_NO_UPDATE_CHECK spelling is still honored. -->

The server compares its version against PyPI's when you call
`manage_session(action='status')`, and never at any other time: nothing runs at startup and nothing
runs on a background thread. At most one request per seven days, with a two-second timeout. It never
installs anything. The request is a plain HTTPS GET to pypi.org for this package's public release
index; it sends no identifier, no usage data, no page content and no session state. A check that
could not complete says so and says how long ago the last successful one was, rather than showing
nothing. `KS4WEB_UPDATE_CHECK=off` switches it off, and the status report then says it is off; the
older `KS4WEB_NO_UPDATE_CHECK=1` spelling is still honored.

## Testing

2,006 tests, of which 733 drive a real browser. Beyond the suite, every release passes gate
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
