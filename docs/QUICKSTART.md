# KitchenSink4Web Quickstart

Five minutes from install to your first page.

## 1. Install

**Claude Desktop:** install the KitchenSink4Web extension. The checkboxes on
the install screen are the whole configuration: out of the box it can read
pages but not click anything, and the two boxes marked "Warning: DANGEROUS"
stay off until you decide otherwise. You need `uv` on your machine (one
installer from astral.sh); the server fetches itself on first launch and
drives its own private browser, never yours.

**Claude Code or any MCP client:** `uvx kitchensink4web` as the server
command. Done.

One tip that removes most permission pop-ups: in Claude Desktop's Tool
permissions for this server, set the Read-only tools group to Always Allow.
Those tools cannot change anything, so approving them once is safe, and
Claude stops asking about every read.

## 2. Read a page

Ask Claude: "Read https://en.wikipedia.org/wiki/Kitchen_sink and tell me the
history section."

Claude navigates, gets a small map of the page with the cost of each section,
opens only what it needs, and tells you if anything went unread. A long page
costs a fraction of what a raw dump would, and the leftovers are named, not
hidden.

## 3. Click a button (when you allow it)

Out of the box, asking Claude to click gets an honest refusal that names the
setting: "Warning: DANGEROUS. Let Claude click and type on pages," on the
extension's settings screen. Check it, **press Save** (Claude Desktop only
applies settings on Save; forgetting it is the single most common setup
problem), and the acting tools appear on restart. Even then, payments,
passwords, posts that reach people, and deletions stop and ask you first,
every time, and no setting turns that off.

## 4. When a site says no

Some sites block automated browsers. KS4Web tells you plainly (a bot wall, a
login wall, a rate limit) instead of pretending the page was empty, and it
suggests what actually works: a different browser lane it has measured on
this machine, or handing you the window to pass a check yourself. One thing
to know: a Cloudflare challenge can kill the browser session outright. If
that happens, close the session and open a new one; the error will already
have said so.

## 5. Where everything else lives

Ask Claude to call `get_workflows` for recipes (reading strategies, logins,
monitoring, workflow recording), see the COOKBOOK for the ten most common
jobs with exact calls, and the ARCHITECTURE page for how packs, lanes,
consent, and the vault fit together. Monitors, saved logins, and the lane
database all live on your machine and survive restarts; nothing about your
browsing leaves it.
