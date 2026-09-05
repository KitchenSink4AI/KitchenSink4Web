"""Region-scoped search, which until 2026-09-06 was not scoped at all.

The shadow build found it while auditing the traversal seam:
`find_elements(location={'region': 'r7'})` computed a scope root, passed it
into `find.js` as `opts.root`, and `find.js` never read the key. The search
covered the whole page, the result line said nothing about it, and a caller
who asked about one region got answers from every region on the page. That is
worse than an unsupported argument, because an unsupported argument refuses.

Four claims, each a different way the old build was wrong or the new one
could be:

1. **Narrowing is real.** The same query returns fewer matches scoped than
   unscoped, and returns exactly the region's own.
2. **Shadow content INSIDE the scope is reached.** The region owns a
   component; the search crosses that boundary. Scoping and traversal are
   the two features most likely to cancel each other out.
3. **Shadow content OUTSIDE the scope is not.** The counterfactual for
   claim 2: the sibling region's component stays unfound. A traversal that
   sweeps from `document` and then trims light-DOM matches would pass claim
   2 and fail this one.
4. **The result line says what was searched.** A scoped search that reads
   like a page-wide one is how a caller concludes a string is absent from
   the page when it is only absent from the region.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import pagedata
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import TargetNotFound
from kitchensink4web.ops import lite

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
PAGE = "b/regions_shadow.html"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def corpus_site():
    handler = functools.partial(_Quiet, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


async def _open(site):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{PAGE}")
    # The read is what mints r1/r2/r3; a scope ref has no other source.
    await lite.get_page_view(page=page)
    return session, page


def test_a_region_scope_narrows_the_search(corpus_site):
    """Five Save controls on the page, two of them in the draft panel."""
    async def go():
        session, page = await _open(corpus_site)
        truth = await session.page(page).page.evaluate("() => window.__truth")
        wide = await lite.find_elements(page=page, query="Save", limit=50)
        assert wide["matched"] == truth["save_buttons_page_wide"] == 5
        scoped = await lite.find_elements(page=page, query="Save",
                                          location={"region": "r1"}, limit=50)
        assert scoped["matched"] == truth["save_buttons_in_draft_panel"] == 2
        body = pagedata.unwrap(scoped["results"])
        # The region's own Save and the one inside the component it owns.
        assert '"Save"' in body
        assert "Save inside draft-widget" in body
        # And nothing from the neighbours.
        assert "archive-widget" not in body
        assert "Restore archive" not in body

    run(go())


def test_a_component_inside_the_scope_is_searched(corpus_site):
    """Claim 2 on its own: the match is two boundaries in (region, then open
    shadow root), and the ref it comes back with is actable like any other."""
    async def go():
        session, page = await _open(corpus_site)
        found = await lite.find_elements(page=page, query="draft-widget",
                                         location={"region": "r1"})
        assert found["matched"] == 1
        body = pagedata.unwrap(found["results"])
        assert "Save inside draft-widget" in body
        assert "searched 1 of 1 open shadow root(s)" in body
        ref = body.splitlines()[1].split(" | ")[0]
        assert session.element_map.entries[ref].kind == "affordance"
        out = await lite.click(page=page, location={"ref": ref})
        assert out["target"]["name"] == "Save inside draft-widget"

    run(go())


def test_a_component_outside_the_scope_is_not_searched(corpus_site):
    """Claim 3, the counterfactual. The archive panel's component holds a
    control whose name is unique on the page; scoped to the draft panel the
    search must not find it, and must not find it via any of the three
    routes (name search, css, absolute xpath)."""
    async def go():
        _, page = await _open(corpus_site)
        by_name = await lite.find_elements(page=page, query="archive-widget",
                                           location={"region": "r1"})
        assert by_name["matched"] == 0
        by_css = await lite.find_elements(
            page=page, query="button", kind="css",
            location={"region": "r1"}, limit=50)
        names = pagedata.unwrap(by_css["results"])
        assert "archive" not in names.lower()
        # An ABSOLUTE xpath ignores its context node, so this one is the
        # containment filter's test rather than the context node's.
        by_xpath = await lite.find_elements(
            page=page, query="//button", kind="xpath",
            location={"region": "r1"}, limit=50)
        assert by_xpath["matched"] == 2       # #draft-save and #draft-only
        assert "archive" not in pagedata.unwrap(by_xpath["results"]).lower()

    run(go())


def test_the_result_line_names_the_scope(corpus_site):
    """Claim 4. Scoped and unscoped searches must not read alike."""
    async def go():
        _, page = await _open(corpus_site)
        wide = pagedata.unwrap(
            (await lite.find_elements(page=page, query="Save"))["results"])
        assert "within" not in wide.splitlines()[0]
        assert "not searched: 0 iframe(s)" in wide

        scoped = await lite.find_elements(page=page, query="Save",
                                          location={"region": "r2"})
        head = pagedata.unwrap(scoped["results"]).splitlines()
        assert 'within r2 (region "Archive panel")' in head[0]
        assert "not searched: everything outside r2" in head[-1]
        assert scoped["scope"] == {"region": "r2"}

    run(go())


def test_shadow_false_still_opts_out_inside_a_scope(corpus_site):
    """The modifier and the scope compose rather than fighting: scoped AND
    not piercing returns the region's light-DOM control alone."""
    async def go():
        _, page = await _open(corpus_site)
        found = await lite.find_elements(
            page=page, query="Save",
            location={"region": "r1", "shadow": False}, limit=50)
        assert found["matched"] == 1
        body = pagedata.unwrap(found["results"])
        assert "Save inside draft-widget" not in body
        assert "searched 0 of 1 open shadow root(s)" in body

    run(go())


def test_a_scope_that_left_the_page_refuses_with_the_callers_ref(corpus_site):
    """ROOT_GONE, which the search used to be incapable of reaching because
    it never looked the root up. The ref NAMED is the caller's r1, not the
    in-page id the extractor keys on, which is the same distinction the
    field misdirect investigation drew for action results."""
    async def go():
        session, page = await _open(corpus_site)
        await session.page(page).page.evaluate(
            "() => document.querySelector('section').remove()")
        with pytest.raises(TargetNotFound) as caught:
            await lite.find_elements(page=page, query="Save",
                                     location={"region": "r1"})
        assert "'r1'" in str(caught.value)
        assert "Re-read the page" in str(caught.value)

    run(go())
