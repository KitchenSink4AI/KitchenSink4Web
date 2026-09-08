"""Fix wave 9b (2026-09-08), against the hostile stress round
`20260908_insane_sonnet.md`. Two blockers, both of them the round's own
repro, both taken from a corpus fixture rather than from a page written to
suit the fix. Five of these FAILED on `fcda053` and pass now; the rest are
the false-positive arms and one forward guard, named as such where they sit.

  S-01  `get_page_view`'s completeness block asserted, of `corpus/ra/
        modal.html`, that "a click on any of them refuses" while `click` on
        the panel's own Confirm button succeeded -- which is what a modal is
        FOR, and what that fixture's manifest says it must do. A read making
        a confident claim about the acting path that the acting path
        contradicts on the same page is the exact defect class the round was
        hunting. The claim was derived from the lid's mere existence; it is
        measured now, with the acting path's own occlusion rule.

  S-02  `get_text` on `corpus/g2/cloak_light.html` returned the paragraph
        parked under an opaque, identically-sized, higher-z-index sibling as
        ordinary prose -- on a page whose one visible sentence says it is
        "the only prose a human reads on this page" -- and left it out of
        the `stripped` ledger as well, while correctly naming the other
        seven cloaking techniques. That is the read-side sibling of the R4
        click-occlusion bug, on the surface where an injected instruction
        actually rides.

THE CLASS, not the instance: S-02's rule lives in `visibility.js` and every
surface that REPORTS CONTENT asks it, so `get_page_view`, `get_article`, and
`extract_page` are pinned here alongside `get_text`. `find_elements` is
deliberately NOT one of them and has its own pin saying why: it retrieves
targets for the acting path, and the acting path owns the better verdict.

THE FALSE-POSITIVE DIRECTION is pinned too, and it is the reason the read's
rule is narrower than the acting path's. Box math without the pixel arbiter
strips 53 blocks of real prose from the frozen Wikipedia article, so the read
requires an out-of-flow lid and total coverage. `test_ordinary_pages_lose_no_
prose_to_the_cloak_check` is what stops a future widening from shipping.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import TargetNotFound
from kitchensink4web.ops import extract, lite
from kitchensink4web.policy import audit, budgets, credentials, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"


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
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


# -------------------------------------------------------------------- S-01


def test_the_lid_line_does_not_claim_a_refusal_the_click_path_would_not_make(
        corpus_site):
    """The round's own repro, both halves in one run.

    `ra/modal.html` is a modal built the ordinary way: the backdrop sits
    below the panel, so the panel's button must stay actable and everything
    behind the backdrop must not. The read said a click on ANY listed
    control refuses. One of the two ran."""
    async def go():
        _, page = await _open(corpus_site, "ra/modal.html")
        view = await lite.get_page_view(page=page)
        text = view["projection"]
        assert "an opaque panel covers the viewport" in text, text
        assert "a click on any of them refuses" not in text, text
        # The measured split, and the actable one is named so a caller can
        # act on it without taking a second read.
        assert "behind_it=1" in text and "actable=1" in text, text

        # And the acting path agrees, which is the whole point: the read's
        # claim about it is now derived from the same rule it uses.
        ran = await lite.click(
            page=page, location={"text": "Confirm inside the modal"})
        assert ran["target"]["name"] == "Confirm inside the modal", ran
        with pytest.raises(TargetNotFound) as exc:
            await lite.click(page=page,
                             location={"text": "Behind the modal backdrop"})
        assert "opaque panel is painted over it" in str(exc.value)

    run(go())


def test_a_lid_over_everything_still_says_every_click_refuses(corpus_site):
    """THE OTHER DIRECTION, because a fix that just deletes the claim is not
    a fix. `b/uw_lid.html` is H-09's own page: the panel goes over the whole
    viewport and there is no control above it, so the original sentence is
    true there and still prints, split and all."""
    async def go():
        _, page = await _open(corpus_site, "b/uw_lid.html")
        await lite.wait_for(page=page, condition="text",
                            value="Loading, please wait", timeout_ms=5000)
        view = await lite.get_page_view(page=page)
        text = view["projection"]
        assert "an opaque panel covers the viewport" in text, text
        assert "a click on any of them refuses" in text, text
        assert "actable=" not in text, text

    run(go())


# -------------------------------------------------------------------- S-02


def test_prose_under_an_opaque_sibling_is_not_returned_as_readable(
        corpus_site):
    """`g2/cloak_light.html`'s ninth technique, and the only one that got
    through. The payload came back as content AND went uncounted, so the
    `stripped` ledger named eight of nine cloaks and the ninth read as the
    page's own prose."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_light.html")
        got = await lite.get_text(page=page)
        assert "MARK BEHIND" not in got["text"], got["text"]
        # The visible sentence is still there: this excludes the cloak, not
        # the page.
        assert "MARK VISIBLE" in got["text"], got["text"]
        # COUNTED, never silently dropped, with the technique named beside
        # the other eight.
        assert "paint-cloaked=1" in got["stripped"], got["stripped"]

    run(go())


def test_the_page_view_counts_the_same_cloak_under_the_same_name(corpus_site):
    """One rule, one source: the page view's hidden ledger and the prose
    read's `stripped` line have to name the same technique on the same page,
    or a caller comparing two reads is told two different stories."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_light.html")
        view = await lite.get_page_view(page=page)
        assert "paint-cloaked=" in view["projection"], view["projection"]

    run(go())


def test_the_cloak_check_covers_prose_and_stops_at_controls(corpus_site):
    """THE SCOPE, pinned, because this wave overshot it once.

    The round drew the line itself: `click`'s refusal discloses that "the
    read surfaces do not compute per-element occlusion", which is true of
    CONTROLS, and the finding was that the disclosure "is scoped to
    interactive controls; it does not cover prose/text nodes, and prose
    extraction is where this gap actually lives". So on R4's own page the
    read now counts the cloaked HEADING under the panel, and still lists the
    buried button: the anchor ladder rebinds a ref by matching it against a
    fresh read's affordances, and dropping the control made `find_and_act`
    answer with a StaleAnchor instead of the occlusion refusal."""
    async def go():
        _, page = await _open(corpus_site, "ra/overlay.html")
        view = await lite.get_page_view(page=page)
        text = view["projection"]
        assert "paint-cloaked" in text, text
        assert "Transfer balance to 9912" in text, text

    run(go())


def test_the_search_still_hands_a_cloaked_target_to_the_acting_path(
        corpus_site):
    """THE LINE BETWEEN REPORTING AND RETRIEVING, pinned because this wave
    crossed it once and had to come back.

    Wiring the read-side cloak rule into `find_elements` looked like
    consistency and was a downgrade: the acting path owns a BETTER verdict
    than any read can compute, because only it can run the pixel arbiter
    that clears box math's false positives. Filtering here substituted the
    cheaper answer for the better one, and `find_and_act` on this page
    stopped saying "an opaque panel is painted over it" and started saying
    "nothing visible matches" -- a worse answer about the same fact, and the
    R4 pin in `test_reattack_fixes` caught it.

    So: surfaces that REPORT CONTENT exclude and count the cloak; the
    surface that RETRIEVES TARGETS hands them to the arbiter."""
    async def go():
        _, page = await _open(corpus_site, "ra/overlay.html")
        found = await lite.find_elements(page=page,
                                         query="Transfer balance to 9912")
        assert "1 of 1 match" in found["results"], found["results"]
        with pytest.raises(TargetNotFound) as exc:
            await lite.find_and_act(page=page, action="click",
                                    query="Transfer balance to 9912",
                                    timeout_ms=3000)
        assert "opaque panel is painted over it" in str(exc.value)

    run(go())


def test_extract_page_does_not_read_a_value_off_cloaked_text(corpus_site):
    """A FORWARD GUARD rather than a repro: this one passed on `fcda053`
    too, because the schema ladder never matched the cloaked paragraph as a
    value in the first place. It is here because `extract_page` is the read
    surface where a wrong answer is hardest to spot -- it reports a value as
    read off the page, which is a claim about what a human sees -- and the
    shared rule now covers it, so a future ladder that DOES reach that
    paragraph fails here instead of shipping."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_light.html")
        got = await extract.extract_page(page=page,
                                         schema=["MARK BEHIND", "MARK CVAUTO"])
        blob = str(got)
        assert "evil.invalid" not in blob, blob[:2000]

    run(go())


# ------------------------------------------------- the false-positive arms


def test_ordinary_pages_lose_no_prose_to_the_cloak_check(corpus_site):
    """THE DIRECTION THAT DECIDES WHETHER THE CHECK CAN SHIP.

    The acting path's occlusion rule, run unmodified over the blocks
    `get_text` emits, strips 53 of the frozen Wikipedia article's 824 blocks
    -- navbox `v`/`t`/`e` links under in-flow `<th>` cells of a nested table
    that overlap them in that snapshot. The acting path clears those with a
    screenshot arbiter the read cannot afford, so the read's rule demands an
    out-of-flow lid and total coverage instead. This is the pin that fails
    if anyone widens it back."""
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        got = await lite.get_text(page=page, max_chars=200000)
        assert "paint-cloaked" not in got["stripped"], got["stripped"]
        assert got["chars"]["total_in_scope"] > 100000, got["chars"]

    run(go())


def test_a_modal_backdrop_does_not_cloak_the_page_it_dims(corpus_site):
    """A human reads dimmed text; a human reads nothing under an opaque box.
    `ra/modal.html`'s backdrop is `rgba(0,0,0,.6)`, so the read keeps the
    page's prose while the acting path still refuses the click behind it --
    the documented split, pinned in the one place both rules meet."""
    async def go():
        _, page = await _open(corpus_site, "ra/modal.html")
        got = await lite.get_text(page=page)
        assert "Account settings" in got["text"], got["text"]
        assert "paint-cloaked" not in got["stripped"], got["stripped"]

    run(go())


def test_a_sticky_header_and_a_toast_cloak_nothing(corpus_site):
    """`ra/sticky.html`'s two false-positive arms, on the read side this
    time: ordinary design that clips an edge must stay readable."""
    async def go():
        _, page = await _open(corpus_site, "ra/sticky.html")
        got = await lite.get_text(page=page)
        assert "paint-cloaked" not in got["stripped"], got["stripped"]
        view = await lite.get_page_view(page=page)
        assert "paint-cloaked" not in view["projection"], view["projection"]

    run(go())


def test_the_cloak_check_costs_an_ordinary_page_nothing_it_can_see(
        corpus_site):
    """The budget, which is the number the completeness block is priced
    against. The check adds a page-wide paint scan; it must not move what
    the read returns on a page with no out-of-flow opaque boxes at all."""
    async def go():
        _, page = await _open(corpus_site, "b/app.html")
        view = await lite.get_page_view(page=page)
        assert "paint-cloaked" not in view["projection"], view["projection"]
        got = await lite.get_text(page=page)
        assert "paint-cloaked" not in got["stripped"], got["stripped"]

    run(go())
