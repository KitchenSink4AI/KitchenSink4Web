# KitchenSink4Web Cookbook

The ten most common jobs, with the calls that do them. Every recipe works in
read-only mode unless marked ACTING (needs "click and type" on) or a pack
name (needs that pack checked at install).

## 1. Read a webpage
`navigate(url=...)` then `get_page_view(page=...)` for the map, then
`get_text(page=..., location={"ref": "h3"})` for the section you want.
For a repeat look after something changed, pass `since=<read_token>` and pay
only for the difference.

## 2. Read an article cleanly
`navigate` then `get_article(page=...)`. Returns title, byline, date, and
body with the chrome stripped and counted. If the page is not article-shaped
it refuses with the numbers that say why; fall back to `get_text`.

## 3. Extract structured data
`extract_page(page=..., schema={"title": "the paper title", "price": "the
listed price"})`. Every filled field names its evidence tier and source;
no match is `not_found`, never a guess. For tables: `get_table`. For
repeated records: `get_list`. (extract pack)

## 4. Compare across several pages
`aggregate(urls=[...], schema={...})`. One call, one dataset, one slot per
URL in order; a 404 or bot wall lands in its own slot and the rest continue.
(extract pack)

## 5. Fill out a form (ACTING)
One field: `find_and_act(query="Customer name", action="type", text=...)`.
Whole form: `fill_form(fields=[{"ref": "e12", "value": "..."}, ...])`; the
key is `value`. Multi-step: `batch(steps=[...])` with find, wait, assert,
and navigate steps. Submissions that carry money, passwords, posts, or
deletions stop and ask the human first, always.

## 6. Log into a site and keep the login (ACTING + cookies pack)
`manage_session(action="handoff")` hands you a visible window; log in
yourself, then `manage_session(action="close", auth_state="save")` writes
the session (never the password) to a file. Next time:
`manage_session(action="open", auth_state=<path>)`.

## 7. Watch a page for changes
`monitor(action="create", url=..., condition="text_appears", value=...)`,
then `monitor(action="report")` whenever you want answers. Monitors live on
your machine, survive restarts, and pause themselves rather than hammer a
failing site. Nothing pushes; the report is how you ask.

## 8. Record a flow once, replay it later (ACTING + workflows pack)
Do the flow once, then `save_workflow(name=...)` from the session's audit
trail, with typed values as named parameters. Later:
`run_workflow(name=..., params={...})`; a mandatory dry run re-resolves
every step against the live page before anything executes.

## 9. Handle a bot wall
Read the refusal: it names the wall and what this machine has measured.
`manage_session(action="open", lane="B:moz-firefox")` uses your real
installed Firefox, which passes where headless Chromium is refused on many
sites; `action="handoff"` hands you the window for a check only a human
should pass. A CAPTCHA is always yours: KS4Web does not solve them.

## 10. Grab a PDF
`navigate` identifies a PDF and refuses to pretend it is a page;
`download(action="goto", url=...)` fetches it into the downloads folder
(files pack). Pair with a PDF reader tool from there.

**The reading strategy in one line:** orientation `get_page_view`, prose
`get_text`, article `get_article`, one value `extract_page`, table
`get_table`, many pages `aggregate`.
