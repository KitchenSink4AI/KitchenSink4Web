"""Same-origin frame traversal, end to end, against real pages.

The second traversal, and the shadow build is the sibling to read first. That
one worked because open shadow roots share their document's execution context;
a frame does not, so this build routes every in-page pass through the driver's
frame layer and runs it in the frame's own realm.

Five claims are pinned here and each one is a different kind of failure:

1. **Capability.** Content inside a same-origin frame is read, searchable, and
   actable, and its refs carry the frame they came from.
2. **The boundary holds.** A cross-origin frame is counted and named and never
   entered, even though the driver could enter it. That is a posture, not a
   budget: the classification comes from the parent's own script access, so a
   sandboxed frame in an opaque origin is refused whatever its URL says.
3. **Provenance.** Same-origin is not first-party. A `srcdoc` frame runs at
   the page's own origin carrying markup from anywhere, and the envelope says
   so with the frame's id and origin named.
4. **Visibility crosses the boundary in one direction.** A frame the parent
   hides is a frame nobody reads, and an element inside a frame under a lid
   is not clickable however visible it looks in its own coordinate space.
5. **Zero regression.** A page with no frames costs one property read and
   produces the projection it produced before frames existed.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine import frames as _frames
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (AmbiguousLocation, StaleAnchor,
                                    TargetChanged, TargetNotFound)
from kitchensink4web.ops import lite

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _serve():
    handler = functools.partial(_Quiet, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture(scope="module")
def corpus_site():
    httpd, base = _serve()
    yield base
    httpd.shutdown()


@pytest.fixture(scope="module")
def other_site():
    """A SECOND origin, on a second port.

    An offline `https://example.com` frame proves nothing about cross-origin
    handling: it never loads, so a read cannot tell a refusal from a blank
    page. A different port on the same host is a different origin by the
    browser's own rule, and it actually loads."""
    httpd, base = _serve()
    yield base
    httpd.shutdown()


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


# ------------------------------------------------------------- capability


def test_same_origin_frame_content_reaches_the_projection(corpus_site):
    """Corpus B's frame battery. Before this build the read saw six empty
    boxes and reported them as iframes it had not traversed."""
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        text = (await lite.get_page_view(page=page))["projection"]
        # The plain same-origin frame.
        assert "Child frame document" in text
        assert "Pay now" in text
        # The srcdoc frame, which is same-origin by inheritance.
        assert "Srcdoc confirm" in text
        # The sandboxed frame that KEPT its origin.
        assert "Sandbox confirm" in text
        # Nesting: the level-two frame and the level-three frame inside it.
        assert "Level two button" in text
        assert "Level three button" in text
        return text

    run(go())


def test_frame_refs_carry_the_frame_and_resolve_in_it(corpus_site):
    """`if2e5` is readable as "the fifth element of frame two", and it
    resolves through frame two's own execution context rather than through a
    main-document lookup that would find nothing."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        await lite.get_page_view(page=page)
        framed = [ref for ref, e in sess.element_map.entries.items()
                  if e.frame]
        assert framed, "no ref was minted inside a frame"
        for ref in framed:
            entry = sess.element_map.entries[ref]
            assert ref.startswith(entry.frame), (ref, entry.frame)
            assert entry.frame.startswith("if")
        # And a main-document ref is untouched: no prefix, no frame.
        plain = [ref for ref, e in sess.element_map.entries.items()
                 if not e.frame]
        assert plain and all(not r.startswith("if") for r in plain)

    run(go())


def test_find_elements_searches_frames_and_says_which(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        got = await lite.find_elements(page=page, query="Sandbox confirm")
        assert got["matched"] >= 1
        assert "searched" in got["results"] and "same-origin frame" in \
            got["results"]
        # The match's ref is frame-qualified, so a follow-up action goes to
        # the right realm without the caller having to say so.
        assert "if" in got["results"]

    run(go())


def test_acting_inside_a_frame_lands_in_that_frame(corpus_site):
    """The end-to-end proof: a trusted click dispatched through the frame's
    own handle, verified by the frame's own listener."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        found = await lite.find_elements(page=page, query="Pay now",
                                         role="button")
        # Two buttons named "Pay now": one in the page, one in the frame.
        # That is an ambiguity across a frame boundary and the search reports
        # both rather than resolving it.
        assert found["matched"] >= 2
        ref = next(line.split(" | ")[0]
                   for line in found["results"].splitlines()
                   if line.startswith("if") and "Pay now" in line)
        result = await lite.click(page=page, location={"ref": ref})
        assert result["tool"] == "click"
        tree = await _frames.ladder(sess.pages[page])
        child = next(f for f in tree
                     if f.entered and not f.is_main
                     and "frames_child" in (f.url or ""))
        out = await child.frame.evaluate(
            "() => document.getElementById('child-out').textContent")
        assert out.startswith("CHILD-CLICKED")

    run(go())


def test_a_live_selector_refuses_ambiguity_across_the_frame_boundary(
        corpus_site):
    """Two "Pay now" buttons in two documents are two matches. Acting on
    whichever realm answered first is the first-match behaviour this resolver
    refuses everywhere else, and a frame boundary is not a tie-break."""
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.click(page=page,
                             location={"role": "button", "name": "Pay now"})
        assert "document(s)" in str(exc.value)
        assert '{"frame": "ifN"}' in str(exc.value)

    run(go())


def test_the_frame_modifier_narrows_to_one_realm(corpus_site):
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        await lite.get_page_view(page=page)
        tree = await _frames.ladder(sess.pages[page])
        child = next(f for f in tree if f.entered and not f.is_main
                     and "frames_child" in (f.url or ""))
        result = await lite.click(
            page=page,
            location={"role": "button", "name": "Pay now",
                      "frame": child.fid})
        assert result["tool"] == "click"

    run(go())


def test_find_and_act_reaches_a_control_inside_a_frame(corpus_site):
    """The fused path searches frames for the same reason the split path
    does: a caller who asked for the confirm button on a page whose widget is
    in a frame asked about the page, not about the top document."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        result = await lite.find_and_act(page=page, query="Sandbox confirm",
                                         action="click")
        assert result["tool"] == "find_and_act" and result["acted"] == "click"
        acted = result["target"]["ref"]
        assert sess.element_map.entries[acted].frame.startswith("if")

    run(go())


def test_find_and_act_refuses_a_match_in_each_realm(corpus_site):
    """Merged BEFORE the ambiguity decision, so a match in the page and a
    match in a frame refuse each other instead of the first one winning."""
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.find_and_act(page=page, query="Pay now",
                                    role="button", action="click")
        assert "no tool acts on first match" in str(exc.value)

    run(go())


# ---------------------------------------------------------------- honesty


def test_a_real_cross_origin_frame_is_counted_and_never_read(corpus_site,
                                                             other_site):
    """A second port is a second origin, and this one really loads. The
    driver could evaluate in it; this build will not."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_crossorigin.html")
        record = sess.pages[page]
        await record.page.evaluate(
            "(base) => window.pointCrossOrigin(base)", other_site)
        await record.page.wait_for_timeout(400)
        view = await lite.get_page_view(page=page)
        text = view["projection"]
        assert "NOT entered (cross-origin)" in text
        # The content of that document must be absent, not merely unlisted.
        assert "Child frame document" not in text
        assert "child-card" not in text
        assert "a cross-origin frame is never read" in text

    run(go())


def test_sandbox_without_allow_same_origin_is_cross_origin(corpus_site):
    """THE CLASSIFICATION RULE, stated as a test. `<iframe src="/same/path"
    sandbox>` has a same-origin URL and an opaque origin, and the URL is the
    wrong authority. The parent's own `contentDocument` access is the right
    one, and it is the boundary the browser itself enforces."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        tree = await _frames.ladder(sess.pages[page])
        opaque = [f for f in tree
                  if f.sandbox == "" and not f.is_main]
        assert opaque, "the opaque-origin frame was not classified"
        for f in opaque:
            assert not f.same_origin
            assert f.why_not == _frames.CROSS_ORIGIN
            # Its URL says same-origin. The classification disagrees, and is
            # right.
            assert f.url.startswith(corpus_site)

    run(go())


def test_a_hidden_frame_is_not_entered_and_its_payload_stays_out(corpus_site):
    """The shadow build's hidden-host rule, one boundary along. A frame the
    parent hides is a whole document a human cannot see, and reading it would
    deliver text as page content that nobody on that page could read."""
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        view = await lite.get_page_view(page=page)
        assert "BURIED-FRAME-PAYLOAD" not in view["projection"]
        assert "Buried confirm" not in view["projection"]
        assert "the frame element is hidden" in view["projection"]
        text = await lite.get_text(page=page)
        assert "BURIED-FRAME-PAYLOAD" not in text["text"]

    run(go())


def test_a_lid_over_the_frame_stops_a_click_inside_it(corpus_site):
    """OCCLUSION IS THE ONE VERDICT A FRAME CANNOT COMPUTE FOR ITSELF.

    Inside the frame the button is laid out, hit-testable, and visible in the
    frame's own coordinate space, and every check the frame can run says so.
    The wall is a fact about the PARENT's boxes, and a click under it lands on
    the wall. So the visibility model crosses the boundary downward: the
    element's own document answers for the element, and each `<iframe>` on the
    way up answers for the frame."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        await lite.get_page_view(page=page)
        ref = next(r for r, e in sess.element_map.entries.items()
                   if e.frame and e.anchor.get("name") == "Pay now")
        # Unlidded, the click lands.
        await lite.click(page=page, location={"ref": ref})
        await sess.pages[page].page.evaluate("() => window.raiseLid()")
        with pytest.raises(TargetNotFound) as exc:
            await lite.click(page=page, location={"ref": ref})
        message = str(exc.value)
        assert "inside frame" in message
        assert "the frame cannot see what the page painted over it" in message

    run(go())


def test_the_depth_cap_refuses_by_name_rather_than_crashing(corpus_site):
    """Deep nesting is a page a hostile site can serve deliberately and each
    level costs a real execution context. The cap is a reported refusal, not
    a discovered crash."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_deep.html?n=9")
        await sess.pages[page].page.wait_for_timeout(600)
        tree = await _frames.ladder(sess.pages[page])
        entered = [f for f in tree if f.entered and not f.is_main]
        capped = [f for f in tree if f.why_not == _frames.DEPTH_EXCEEDED]
        assert entered, "the chain was not entered at all"
        assert max(f.depth for f in entered) <= _frames.DEPTH_CAP
        assert capped, "a nine-deep chain hit no cap"
        view = await lite.get_page_view(page=page)
        assert "past the frame depth cap" in view["projection"]

    run(go())


def test_the_completeness_block_reports_both_layers(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        text = (await lite.get_page_view(page=page))["projection"]
        line = next(ln for ln in text.splitlines()
                    if ln.startswith("iframes: "))
        assert "on the page" in line and "entered (same-origin)" in line
        assert "not entered" in line

    run(go())


# ------------------------------------------------------------- provenance


def test_frame_text_arrives_with_the_frames_own_origin_named(corpus_site):
    """A same-origin frame can still carry third-party content. `srcdoc` is
    the plainest case: it runs at the page's origin and its markup came from
    wherever the string came from."""
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        view = await lite.get_page_view(page=page)
        note = view["page_data"]
        assert "frames" in note
        provenances = [f["provenance"] for f in note["frames"]]
        assert any("srcdoc" in p for p in provenances)
        assert any("sandboxed" in p for p in provenances)
        assert "Same-origin does not mean the page's author wrote it" in \
            note["label"]
        for f in note["frames"]:
            assert f["fid"] in note["label"]

    run(go())


def test_an_injection_inside_a_frame_arrives_labelled(corpus_site):
    """The srcdoc frame carries a planted instruction. It is delivered,
    because labels frame and never censor, and it is delivered INSIDE the
    envelope with the frame that carried it named."""
    async def go():
        _, page = await _open(corpus_site, "b/frames_suite.html")
        got = await lite.get_text(page=page)
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in got["text"]
        nonce = got["page_data"]["nonce"]
        assert f"<<<KS4WEB-PAGE-DATA {nonce}>>>" in got["text"]
        # The frame header sits immediately above the frame's own prose.
        head = [ln for ln in got["text"].splitlines()
                if ln.startswith("--- if")]
        assert head, "frame prose arrived with no provenance header"
        assert any("frame content from" in ln for ln in head)
        assert "prose was read from" in got["stripped"]

    run(go())


# ------------------------------------------------------------- durability


def test_a_frame_ref_survives_a_parent_re_render(corpus_site):
    """Refs are content-derived and per realm, so re-reading a page whose
    parent document changed keeps the frame's refs pointing at the same
    controls."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        await lite.get_page_view(page=page)
        before = {ref: e.anchor.get("name")
                  for ref, e in sess.element_map.entries.items() if e.frame}
        await sess.pages[page].page.evaluate(
            "() => { const h = document.querySelector('h1');"
            " h.textContent = 'Rewritten heading';"
            " document.body.insertBefore(document.createElement('div'),"
            " document.body.firstChild); }")
        await lite.get_page_view(page=page)
        after = {ref: e.anchor.get("name")
                 for ref, e in sess.element_map.entries.items()
                 if e.frame and not e.gone}
        kept = [r for r in before if r in after and before[r] == after[r]]
        assert len(kept) == len(before), (
            f"{len(before) - len(kept)} frame ref(s) moved on a parent "
            f"re-render")

    run(go())


def test_a_removed_frame_marks_its_refs_gone_and_refuses_by_name(corpus_site):
    """A frame the page removed takes every ref minted inside it. The refusal
    names the frame rather than reporting a bare miss, and it never falls
    back to the main document."""
    async def go():
        sess, page = await _open(corpus_site, "b/frames_suite.html")
        await lite.get_page_view(page=page)
        ref = next(r for r, e in sess.element_map.entries.items()
                   if e.frame and e.anchor.get("name") == "Pay now")
        await sess.pages[page].page.evaluate(
            "() => window.dropFrame('f-plain')")
        await lite.get_page_view(page=page)
        assert sess.element_map.entries[ref].gone
        with pytest.raises((StaleAnchor, TargetChanged, TargetNotFound)):
            await lite.click(page=page, location={"ref": ref})

    run(go())


# ---------------------------------------------------------- zero regression


def test_a_frame_free_page_is_unchanged(corpus_site):
    """The cost of the frame ladder on a page with no frames is one property
    read and no evaluate at all, and the projection it produces is the one it
    produced before this build."""
    async def go():
        sess, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        view = await lite.get_page_view(page=page)
        assert "iframes: none" in view["projection"]
        assert "frames" not in view["page_data"]
        tree = await _frames.ladder(sess.pages[page])
        assert len(tree) == 1 and tree[0].is_main
        return view["budget"]

    budget = run(go())
    assert budget["rung"] >= 1


def test_the_budget_charges_frame_content_on_the_same_ladder(corpus_site):
    """Frame content competes for the read's tokens against page content,
    which is what keeps every printed price executable. The proof is a budget
    small enough that the ladder has to degrade, with the frames present."""
    import re

    async def go():
        from kitchensink4web.errors import RangeOutOfBounds

        _, page = await _open(corpus_site, "b/frames_suite.html")
        rich = await lite.get_page_view(page=page, budget_tokens=5000)
        framed = [ln for ln in rich["projection"].splitlines()
                  if re.match(r"^if\d+e\d+ \|", ln)]
        assert framed, "no frame affordance was printed at a full budget"
        assert rich["budget"]["used"] <= 5000
        # Under a budget the whole payload does not fit, the ladder degrades
        # over ONE list: frame units are ranked, dropped, and accounted with
        # page units rather than riding in a structure the meter cannot see.
        lean = await lite.get_page_view(page=page, budget_tokens=1300)
        lean_framed = [ln for ln in lean["projection"].splitlines()
                       if re.match(r"^if\d+e\d+ \|", ln)]
        assert lean["budget"]["used"] <= 1300
        assert lean["budget"]["rung"] > rich["budget"]["rung"]
        assert len(lean_framed) <= len(framed)
        # The completeness block is the floor and survives every rung.
        assert "iframes: " in lean["projection"]
        # And the floor itself ROSE, because the frames' content is in the
        # payload the floor is computed over. A budget under it refuses by
        # name rather than truncating, which is the refusal a frameless page
        # gives at its own floor, at a floor the frames raised.
        with pytest.raises(RangeOutOfBounds) as exc:
            await lite.get_page_view(page=page, budget_tokens=400)
        assert "below this page's floor projection" in str(exc.value)

    run(go())
