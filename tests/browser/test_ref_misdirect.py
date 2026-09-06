"""Field friction #3, reproduced and pinned: the post-click type misdirect.

The field session (Developer Feedback/General Feedback/KS4Web_feedback_log.md,
friction #3): after a click that re-rendered the DOM (a GitHub upvote), a
type_text on the comment box ref landed in the SEARCH BAR with no refusal,
and `effect: navigated` reported only after the damage.

The investigation found the seam OUTSIDE the two proven subsystems. The
anchor ladder re-resolved the ref correctly against a fresh extraction, and
the TOCTOU gate guards gated classes; neither guards the DISPATCH. type_text's
non-clearing path was::

    await handle.focus()
    await record.page.keyboard.type(text)

`page.keyboard.type` is PAGE-scoped, not element-scoped: it delivers
keystrokes to whatever holds focus at that instant. A React-style re-render
that replaces the target node between the focus and the keystrokes (GitHub
mounts its rich editor exactly there, on focus) drops focus to <body>; a
GitHub-style global hotkey handler then focuses the search bar on the first
printable key; the rest of the text lands there, and a "\n" in the text is
pressed as Enter, which submits the search form: a full-page navigation. The
resolution ladder never made an error, so no refusal ever fired. The unbound
keyboard is a positional fallback under another name, and no positional
fallback may silently win.

The fixture below rebuilds that page shape deterministically and drives it
through the REAL tool surface. The pinned properties:

- text typed at a ref never lands in a different element, whatever the page
  does between resolution and dispatch: either it lands in the resolved
  target or the call refuses with a typed error naming what moved;
- the search input stays empty and the page does not navigate;
- after the re-render, the same session ref still reaches the comment box
  through the ladder (the S2 property, re-proven over the remount);
- a ref that exists only in the in-page map (never session-minted) refuses
  NOT_FOUND rather than resolving by DOM position;
- an action result's `target.ref` is a ref the session map can resolve, so
  reusing it in the next call rides the ladder rather than a raw map lookup.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import WebMcpError
from kitchensink4web import pagedata
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets, readonly

pytestmark = pytest.mark.browser


_PAGE = """<!doctype html>
<title>Issue 42: no way to turn off the d-pad</title>
<header>
  <form action="/results" method="get">
    <input name="q" id="global-search" type="search" aria-label="Search">
  </form>
</header>
<main>
  <h1>Issue 42: no way to turn off the d-pad</h1>
  <button id="upvote" aria-label="Upvote">Upvote (12)</button>
  <form action="/comment" method="post" id="comment-form">
    <textarea id="comment-box" name="comment_body"
              aria-label="Add a comment"></textarea>
    <button type="submit">Comment</button>
  </form>
</main>
<script>
  // GitHub-style global hotkey: a printable key while nothing is focused
  // focuses the search bar. This is what turned a dropped focus into typing
  // into the wrong element in the field.
  document.addEventListener('keydown', (ev) => {
    const a = document.activeElement;
    if ((a === document.body || a === document.documentElement)
        && ev.key && ev.key.length === 1) {
      document.getElementById('global-search').focus();
    }
  });
  // The upvote arms a re-render; the comment box's NEXT focus replaces the
  // node synchronously, exactly like a rich editor mounting on focus after
  // a state change. The replacement is an identical textarea (same id, same
  // label), so the ladder can and should re-find it afterward.
  let armed = false;
  document.getElementById('upvote').addEventListener('click', (ev) => {
    ev.preventDefault();
    document.getElementById('upvote').textContent = 'Upvote (13)';
    armed = true;
  });
  document.addEventListener('focusin', (ev) => {
    if (!armed) return;
    const el = ev.target;
    if (el && el.id === 'comment-box') {
      armed = false;
      const clone = el.cloneNode(true);
      el.replaceWith(clone);   // destroys the focused node: focus -> body
    }
  }, true);
</script>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/issue":
            self._send(200, _PAGE)
        elif self.path.startswith("/results"):
            self._send(200, "<title>Search results</title><body>"
                            "<h1>Results</h1></body>")
        else:
            self._send(404, "<title>nope</title>")


@pytest.fixture(scope="module")
def issue_site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    readonly.apply(False)
    yield
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _open_issue(site):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/issue")
    return session, page


async def _comment_ref(page) -> str:
    found = await lite.find_elements(page=page, query="Add a comment")
    # The first token of the first result line after the header is the ref.
    line = pagedata.unwrap(found["results"]).splitlines()[1]
    return line.split(" | ")[0].strip()


def test_type_after_rerender_never_lands_in_another_element(issue_site):
    """The field case itself: upvote, then type into the comment box ref.

    Acceptable outcomes: the text is in the comment box, or a typed refusal.
    NOT acceptable: text in the search bar, a navigation, or a success
    report for typing that landed anywhere but the resolved target."""
    async def go():
        _, page = await _open_issue(issue_site)
        ref = await _comment_ref(page)
        await lite.click(page=page, location={"text": "Upvote"})
        outcome = {"refused": None, "result": None}
        try:
            outcome["result"] = await lite.type_text(
                page=page, location={"ref": ref},
                text="Confirming this issue\nthanks")
        except WebMcpError as exc:
            outcome["refused"] = exc
        sess, record = MANAGER.locate(page)
        state = await record.page.evaluate(
            "() => ({url: location.href,"
            " search: document.getElementById('global-search') ? "
            "document.getElementById('global-search').value : null,"
            " comment: document.getElementById('comment-box') ? "
            "document.getElementById('comment-box').value : null})")
        return outcome, state

    (outcome, state) = run(go())
    # The page must not have navigated away under a type call.
    assert "/results" not in state["url"], (
        "the typed text submitted the search form: the field misdirect "
        f"reproduced (url={state['url']!r})")
    # Nothing may land in the search bar, refusal or not.
    assert not state["search"], (
        f"text landed in the search bar: {state['search']!r} (the field "
        f"misdirect). Refusal={outcome['refused']}")
    if outcome["result"] is not None:
        # A reported success must mean the text is IN the comment box.
        assert state["comment"] == "Confirming this issue\nthanks", (
            f"type_text reported success but the comment box holds "
            f"{state['comment']!r}")
    else:
        # A refusal must be typed and must name a recovery.
        assert isinstance(outcome["refused"], WebMcpError)


def test_ladder_still_reaches_the_comment_box_after_the_remount(issue_site):
    """The S2 property over this fixture's remount: once the re-render has
    settled, the SAME session ref reaches the replacement textarea through
    the ladder, and the text verifiably lands there."""
    async def go():
        _, page = await _open_issue(issue_site)
        ref = await _comment_ref(page)
        await lite.click(page=page, location={"text": "Upvote"})
        # Trip the armed replacement outside a type call, then settle.
        await MANAGER.locate(page)[1].page.evaluate(
            "() => { document.getElementById('comment-box').focus(); "
            "document.activeElement.blur && document.activeElement.blur(); }")
        res = await lite.type_text(page=page, location={"ref": ref},
                                   text="landed after remount")
        state = await MANAGER.locate(page)[1].page.evaluate(
            "() => document.getElementById('comment-box').value")
        return res, state

    res, state = run(go())
    assert state == "landed after remount"
    assert res["value_state"] == "landed after remount"


def test_in_page_only_ref_refuses_not_found(issue_site):
    """A ref living only in the in-page map (never session-minted) must
    refuse NOT_FOUND rather than resolving by DOM position. This closes the
    positional fallback: identity comes from the session map and the ladder
    or not at all."""
    from kitchensink4web.errors import TargetNotFound

    async def go():
        _, page = await _open_issue(issue_site)
        sess, record = MANAGER.locate(page)
        # Plant a key in the in-page registry that the session never minted,
        # the shape a leaked per-read extractor id or a model-invented ref
        # takes. It goes in through the instrument channel because that is
        # where the registry lives now; a page cannot reach it at all, which
        # is the point of H5's fix, so this plants what a BUG could plant.
        from kitchensink4web import projection
        await record.page.evaluate(projection.instrument("""
            () => {
            // @@KS4WEB_INSTRUMENT@@
              KS.refs.set('e9999', document.getElementById('global-search'));
            }"""))
        await lite.type_text(page=page, location={"ref": "e9999"},
                             text="must not land")
    with pytest.raises(TargetNotFound):
        run(go())


def test_action_result_ref_is_session_resolvable(issue_site):
    """`target.ref` in an action result must be reusable: the next call that
    quotes it back has to ride the session map and the ladder, not a raw
    in-page lookup. Live-selector resolutions absorb into the session map
    for exactly this reason."""
    async def go():
        _, page = await _open_issue(issue_site)
        res = await lite.click(page=page, location={"text": "Upvote"})
        ref = res["target"]["ref"]
        sess, _record = MANAGER.locate(page)
        assert ref in sess.element_map.entries, (
            f"action result surfaced {ref!r}, which the session map cannot "
            f"resolve: reusing it would bypass the ladder")
        # And reusing it acts on the same element, through the ladder.
        res2 = await lite.click(page=page, location={"ref": ref})
        assert res2["target"]["name"] and "Upvote" in res2["target"]["name"]
    run(go())
