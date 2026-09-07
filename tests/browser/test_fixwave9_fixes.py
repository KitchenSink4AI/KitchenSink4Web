"""Fix wave 9 (2026-09-08), against the fresh-eyes verify round
`20260908_verify_round.md`. Each test is that round's own repro, asserting
the fixed behavior. Every one of them FAILED before its fix.

- V-01: `get_page_view` died with `AttributeError: 'int' object has no
  attribute 'items'` on any page holding a same-origin frame that reported a
  NON-ZERO `name_fallbacks`, because that counter is an int listed among the
  per-frame maps the stitch merges with `.items()`. The `or {}` guard is why
  it looked page-specific in the field: BBC did not crash, Reuters did.
- V-02: `get_accessibility(impact=...)` filtered the violations before every
  total was computed and disclosed nothing, so `impact="minor"` on a page
  with five critical-or-serious failures was byte-for-byte a clean page.
- V-03: `get_table` read a nested layout wrapper as a data table, asserted
  "all rows in the table are included" beside `clipped_cells: 1`, and never
  offered the inner table that actually holds the rows.
- V-04: `get_article` measured `share_of_page` against the selected root's
  own neighbourhood, so booking the real body as chrome scored 0.57 while
  the true share of the page was 0.16, and the payload then said "this is
  the end of the article body".
- V-08: `get_list`'s refusal named Hacker News and sent the caller to the
  tool that garbled Hacker News.
- V-19: a `method="get"` checkout confirm with no card field anywhere on it
  and `<button>Pay now</button>` submitted with ZERO prompts, while the same
  page shape gated on POST and the same GET shape gated when the button said
  "Delete my account". It was the word "Pay" that nothing read.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import ConfirmationRequired, TargetNotFound
from kitchensink4web.ops import a11y, extract, lite
from kitchensink4web.policy import audit, budgets, credentials, readonly

pytestmark = pytest.mark.browser


# ------------------------------------------------------------ the fixtures

#: V-01. A parent holding a same-origin frame whose only control gets its
#: accessible name from a FALLBACK (a title attribute, no text content), so
#: the frame reports name_fallbacks >= 1 and the merge is reached with a
#: non-zero int. A frame reporting zero never tripped it, which is the whole
#: reason this went to the field instead of to a pin.
_FRAME_PARENT = """<!doctype html><title>framed page</title><body>
<h1>Parent document</h1>
<p>Ordinary prose in the parent so the read has something to project.</p>
<iframe src="/framechild" width="400" height="200" title="A child frame">
</iframe>
</body>"""

_FRAME_CHILD = """<!doctype html><title>child</title><body>
<p>Inside the frame.</p>
<button title="Close the dialog"></button>
<button aria-label="Open the menu"></button>
</body>"""

#: V-03. Hacker News's actual shape: an outer TABLE used for page structure,
#: carrying NO role attribute (real HN is
#: `<table id="hnmain" border="0" cellpadding="0" width="85%">`), wrapping
#: the inner table that holds the rows. Both fixtures the tree already had
#: declared `role="presentation"`, which is the one attribute the old
#: one-line detection recognized, so the pins passed on a fixture generous
#: enough to make the old code sufficient.
_NESTED = """<!doctype html><title>nested layout table</title><body>
<table border="0" cellpadding="0" width="85%"><tr><td>
  <table>
    <tr><td>1.</td><td><a href="/a">Show HN: a tiny static site generator</a>
        </td><td>142 points by alice | 88 comments</td></tr>
    <tr><td>2.</td><td><a href="/b">Why we moved off Kubernetes</a></td>
        <td>310 points by bob | 245 comments</td></tr>
    <tr><td>3.</td><td><a href="/c">A gentle introduction to lattices</a></td>
        <td>77 points by carol | 19 comments</td></tr>
    <tr><td>4.</td><td><a href="/d">The case against microservices</a></td>
        <td>208 points by dave | 301 comments</td></tr>
  </table>
</td></tr></table>
<p>Ordinary prose so the page is not empty.</p>
</body>"""

#: V-04. One article container holding an h1, a link-dense nav, a
#: three-paragraph lede in its own div, a four-paragraph body, and a
#: link-dense footer, on a page carrying a great deal of other text that the
#: old denominator counted in neither the numerator nor the denominator.
_LEDE = "The opening passage runs long enough to look like a body. " * 6
_BODY_P = "Body prose that the scorer booked as page chrome, at length. " * 5
_CHROME = "".join(
    f'<div class="rail-item"><a href="/r{i}">Related story {i}</a> '
    f'<span>A sentence of promotional text that the page counts as text '
    f'the reader can see, repeated down the rail.</span></div>'
    for i in range(24))
_ARTICLE = f"""<!doctype html><title>lede-split article</title><body>
<nav><a href="/1">Home</a> <a href="/2">World</a> <a href="/3">Business</a>
 <a href="/4">Tech</a> <a href="/5">Sport</a></nav>
<article>
  <h1>The headline of the piece</h1>
  <nav class="crumbs"><a href="/x">Section</a> <a href="/y">Subsection</a></nav>
  <div class="lede"><p>{_LEDE}</p><p>{_LEDE}</p><p>{_LEDE}</p></div>
  <div class="body"><p>{_BODY_P}</p><p>{_BODY_P}</p><p>{_BODY_P}</p>
  <p>{_BODY_P}</p></div>
  <footer><a href="/t">Terms</a> <a href="/p">Privacy</a></footer>
</article>
<aside class="rails">{_CHROME}</aside>
</body>"""

#: V-19. A stored-card confirm step. There is no card input anywhere on it,
#: which is what a modern checkout confirm, a one-click buy, and a donation
#: confirm all look like: the card was captured on a previous step or lives
#: in the wallet.
_PAY = """<!doctype html><title>confirm order</title><body>
<h1>Confirm your order</h1>
<p>Paying with your saved Visa ending 4242</p>
<form method="get" action="/charge">
  <input type="hidden" name="order" value="A-91822">
  <button type="submit">Pay now</button>
</form>
<form method="get" action="/close">
  <input type="hidden" name="account" value="A-91822">
  <button type="submit">Delete my account</button>
</form>
<form method="get" action="/search">
  <input type="text" name="q" value="">
  <button type="submit">Search</button>
</form>
</body>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body):
        data = body.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/framechild"):
            self._send(_FRAME_CHILD)
        elif path.startswith("/frames"):
            self._send(_FRAME_PARENT)
        elif path.startswith("/nested"):
            self._send(_NESTED)
        elif path.startswith("/article"):
            self._send(_ARTICLE)
        elif path.startswith("/pay") or path.startswith("/charge") \
                or path.startswith("/close"):
            self._send(_PAY)
        else:
            self._send("<!doctype html><title>x</title><p>nothing here</p>")


@pytest.fixture(scope="module")
def fw9_site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    credentials.VAULT.clear()
    readonly.apply(False)
    yield
    credentials.VAULT.clear()
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _open(site, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}{path}")
    return session, page


# -------------------------------------------------------------------- V-01


def test_a_framed_page_with_name_fallbacks_is_read_instead_of_crashing(
        fw9_site):
    """The Reuters crash, root-caused and pinned.

    The whole repro is a frame reporting a NON-ZERO count. Before the fix
    this raised AttributeError inside `stitch`, which the envelope then
    mapped to BAD_PARAMS and handed the caller as raw interpreter text: the
    caller was told its arguments were wrong when they were correct, and the
    payload never reached it at all."""
    async def go():
        _, page = await _open(fw9_site, "/frames")
        return await lite.get_page_view(page=page)

    got = run(go())
    assert got["page"]
    projection = got["projection"]
    # The frame was entered, which is the precondition for the crash.
    assert "1 entered (same-origin)" in projection, projection
    # And the counter merged as a NUMBER: the completeness section prints it
    # as a count, which is what it always was and what the merge table
    # denied it was.
    assert "name quality:" in projection, projection
    assert "every accessible name was computed" not in projection, projection


def test_the_merge_would_still_crash_if_the_table_were_wrong(fw9_site):
    """The mechanism, isolated, so the pin above cannot pass for the wrong
    reason. `stitch` dispatches on the two tables and not on the value,
    deliberately: a merge that silently coped with either shape would turn a
    classification bug into a wrong number nobody sees. So this drives the
    real frame extraction and hands it to `stitch` with the OLD table."""
    from kitchensink4web import projection as _proj

    async def go():
        session, page = await _open(fw9_site, "/frames")
        record = session.page(page)
        main = await _proj.extract(record.page)
        frames = record.page.frames
        child = [f for f in frames if "framechild" in (f.url or "")]
        part = await _proj.extract(child[0])
        return main, part

    main, part = run(go())
    assert part["completeness"]["name_fallbacks"] > 0, "fixture is not red"
    old = ("hidden_reasons", "hidden_interactive_reasons", "reorder_reasons",
           "name_fallbacks")
    with pytest.raises(AttributeError):
        # The pre-fix table, on the pre-fix code path.
        c = dict(main["completeness"])
        for key in old:
            src = (part["completeness"].get(key) or {})
            dst = c.setdefault(key, {})
            for reason, n in src.items():
                dst[reason] = dst.get(reason, 0) + n


def test_the_counter_tables_match_what_an_extraction_actually_emits(fw9_site):
    """The class-kill half. `stitch` dispatches on two tuples and not on the
    value, deliberately, so the tables are what has to be right. This drives
    a real page and asks the extraction whether they are."""
    from kitchensink4web import projection

    async def go():
        session, page = await _open(fw9_site, "/frames")
        record = session.page(page)
        return await projection.extract(record.page)

    data = run(go())
    assert not projection.check_counter_shapes(data["completeness"])


# -------------------------------------------------------------------- V-02


def test_the_impact_filter_cannot_report_a_clean_page_over_a_dirty_one(
        fw9_site):
    """`impact='minor'` on a page whose failures are all more serious than
    minor returned zeros, a `completeness` block affirming the total was
    zero, and the standard reassuring note. Nothing in the payload recorded
    that a filter had run. This is the identical failure the `tags` guard
    exists to prevent, on the sibling parameter."""
    async def go():
        _, page = await _open(fw9_site, "/article")
        whole = await a11y.get_accessibility(page=page)
        filtered = await a11y.get_accessibility(page=page, impact="minor")
        return whole, filtered

    whole, filtered = run(go())
    assert whole["totals"]["rules_violated"] > 0, "the fixture is not dirty"
    # The filter is named where the run's scope is described...
    assert filtered["scope"]["impact"] == "minor"
    assert whole["scope"]["impact"] != "minor"
    # ...and what it removed is countable from the payload itself.
    removed = filtered["scope"]["impact_filtered_out"]
    assert removed["rules"] == (whole["totals"]["rules_violated"]
                                - filtered["totals"]["rules_violated"])
    assert "impact" in filtered["scope"]["impact_note"]


# -------------------------------------------------------------------- V-03


def test_a_nested_layout_wrapper_does_not_win_by_default(fw9_site):
    """Three untruths in one payload, and all three are downstream of one
    line: the layout test was `role="presentation"` and nothing else, so a
    bare `<table border=0>` wrapper classified as data, the containment
    dedupe kept it over the table it wraps, one candidate meant no inventory
    refusal fired, and the inner table came back as ONE clipped cell
    described as a complete read."""
    async def go():
        _, page = await _open(fw9_site, "/nested")
        return await extract.get_table(page=page)

    got = run(go())
    table = got["table"]
    assert table["total_rows"] >= 4, table
    assert table["columns"] >= 3, table
    # The garble was one row holding every story concatenated.
    assert not any(len(row) == 1 and "Show HN" in row[0]
                   and "Kubernetes" in row[0] for row in table["rows"]), table


def test_a_truncated_cell_is_not_called_a_complete_read(fw9_site):
    """`clipped_cells: 1` sat under `accounting` and nothing read it, so the
    payload could say "all rows in the table are included" in one key and
    contradict it in another. The column trim already had this cross-check;
    the cell clip did not."""
    async def go():
        _, page = await _open(fw9_site, "/nested")
        return await extract.get_table(page=page, max_rows=200)

    got = run(go())
    if got["accounting"]["clipped_cells"]:
        assert "truncated" in got["continue"], got["continue"]
    else:
        assert "all rows in the table are included" in got["continue"]


def test_a_data_table_inside_a_declared_layout_wrapper_is_reachable(fw9_site):
    """The other direction of the nesting case, and it was wrong too. The
    old first filter dropped every DESCENDANT of a `role="presentation"`
    element, so a page that marked its wrapper HONESTLY lost its real table
    with it and `get_table` refused with "no data tables" on a page holding
    one."""
    async def go():
        session, page = await _open(fw9_site, "/nested")
        record = session.page(page)
        await record.page.evaluate(
            "document.querySelector('table')"
            ".setAttribute('role', 'presentation')")
        return await extract.get_table(page=page)

    got = run(go())
    assert got["table"]["total_rows"] >= 4, got["table"]


# -------------------------------------------------------------------- V-08


def test_the_no_lists_refusal_no_longer_points_at_a_tool_that_garbles(
        fw9_site):
    """The refusal named Hacker News and then sent the caller to the tool
    that garbled Hacker News. With layout tables now skipped rather than
    read as data, the old promise is false in the other direction too, so
    the sentence says what `get_table` actually does."""
    async def go():
        _, page = await _open(fw9_site, "/nested")
        with pytest.raises(TargetNotFound) as exc:
            await extract.get_list(page=page)
        return str(exc.value)

    text = run(go())
    assert "reads tabular layouts" not in text, text
    assert "skips layout tables" in text, text
    assert "get_text" in text, text


# -------------------------------------------------------------------- V-04


def test_the_article_share_is_measured_against_the_page_and_not_the_root(
        fw9_site):
    """The denominator was `articleChars + excludedChars`: the selected
    root's own NEIGHBOURHOOD. Its floor is the numerator, so on a page with
    no p/li/h* outside the root the share is 1.00 by construction. Here it
    scored a confident pass while the body was a fraction of the page, and
    the payload said "this is the end of the article body" over it."""
    async def go():
        _, page = await _open(fw9_site, "/article")
        try:
            return "read", await extract.get_article(page=page,
                                                     max_chars=200000)
        except TargetNotFound as exc:
            return "refused", str(exc)

    how, result = run(go())
    if how == "refused":
        # An honest refusal is a correct outcome here: the guard now
        # measures the thing its name says.
        assert "rendered text" in result, result
        return
    share = result["completeness"]["share_of_page"]
    assert "rendered text" in share, share
    # THE WHOLE FINDING IN ONE ASSERTION: the denominator the payload prints
    # is the PAGE's, and it is strictly bigger than the scorer's own
    # neighbourhood on a page carrying text outside the article. When the
    # two were the same number the ratio could not detect anything, and on a
    # page with no p/li/h* outside the root it was 1.00 by construction.
    import re as _re
    found = _re.search(
        r"is (\d+)% .*?\(([\d,]+) of ([\d,]+) characters\)"
        r".*?accounts for ([\d,]+)", share)
    assert found, share
    printed_pct = int(found.group(1))
    body_chars, page_chars, scored_chars = (
        int(found.group(n).replace(",", "")) for n in (2, 3, 4))
    assert page_chars > scored_chars, share
    assert body_chars <= scored_chars <= page_chars, share
    assert abs(printed_pct / 100.0 - body_chars / page_chars) < 0.02, share


# -------------------------------------------------------------------- V-19


def _payment_verdict(text: str) -> str:
    if "payment-shaped" in text:
        return "payment_form"
    if "deletes, cancels" in text:
        return "destructive_submit"
    if "submitting a form" in text:
        return "form_submit"
    return "gated"


def test_a_stored_card_confirm_gates_even_with_no_card_field_on_the_page(
        fw9_site):
    """The GET-checkout question, answered. Payment was a FIELD property and
    only a field property, so a form whose only control says "Pay now" and
    whose fields carry no payment signal was never assigned `payment_form`
    at all, was admitted by the GET rule as query-shaped, and submitted with
    zero prompts. The browser navigated to /charge and no human was asked.

    The controls on the same page are the proof the fix is narrow: the
    delete button on the identical GET shape gated before this wave and
    still does, and the search form on the identical GET shape stayed
    ungated before this wave and still does."""
    async def verdict(page, query):
        try:
            await lite.find_and_act(page=page, query=query, action="click",
                                    timeout_ms=3000)
            return "ran"
        except ConfirmationRequired as exc:
            return _payment_verdict(str(exc))

    async def go():
        _, page = await _open(fw9_site, "/pay")
        pay = await verdict(page, "Pay now")
        _, page2 = await _open(fw9_site, "/pay")
        delete = await verdict(page2, "Delete my account")
        _, page3 = await _open(fw9_site, "/pay")
        search = await verdict(page3, "Search")
        return pay, delete, search

    pay, delete, search = run(go())
    assert pay == "payment_form", pay
    assert delete == "destructive_submit", delete
    # THE CONTROL ARM. A gate that fires on everything is the same failure
    # as a gate that fires on nothing, from the other side.
    #
    # It asserts NOT-PAYMENT rather than NOT-GATED, and that is deliberate.
    # Whether a GET search button submits ungated in this harness is the
    # question underneath the nine GET-form submit-gate pins, and that is
    # the AUTHOR'S pending ruling, not this pin's to decide. What this pin
    # owns is that the new vocabulary did not widen to swallow a search box,
    # and it says exactly that.
    assert search != "payment_form", search
