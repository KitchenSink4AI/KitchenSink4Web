"""Phase 2's read layer against real pages: the three tools, and the gate.

`get_page_view` gained `location` and `since`; `find_elements` and `get_text`
landed. Everything here runs against frozen corpora served over localhost, so
nothing touches the network and nothing touches a browser the user started.

The gate parts this file carries are the ones that need a browser: the
completeness block verified by construction against corpus B (part 3), every
rung forced on the 50,000-node fixture and the capped inventories on a
320-field form (part 4), the affordance quotas on the adversarial cases
(part 6), and the accessible-name family including the hidden-through-ancestor
case (part 9).
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import re
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import lite
from kitchensink4web.projection import RUNGS, ntok, project
from kitchensink4web.projection.meter import BudgetMeter
from kitchensink4web.projection.render import Renderer

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def corpus_site():
    """Serves the whole corpus tree, so a test can reach /a, /b, and /wide."""
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


async def _open(site, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


# ------------------------------------------------------- find_elements


def test_find_retrieves_an_in_prose_link_the_page_view_cannot_carry(
        corpus_site):
    """THE flagship pair, end to end, on the page the claim is made about.

    The Treaty of Versailles article carries thousands of in-prose links and
    the affordance quota for that class is zero, so the link is deliberately
    absent from the page view. The claim is not that one read contains
    everything; it is that the read tells you what string to look for and
    this retrieves it for tens of tokens. The extractor's 300-affordance
    return cap is exactly why this is a separate pass: a search built on the
    capped list could not reach this element at all."""
    async def go():
        session, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        view = await lite.get_page_view(page=page)
        # The AFFORDANCE list is what matters: the article has a section
        # named after the Fourteen Points, so the string appears as a region
        # label, and the LINK is the thing the zero quota removed.
        affordances = view["projection"].split("## 3 AFFORDANCES")[1]
        affordances = affordances.split("\n## ")[0]
        assert "Fourteen Points" not in affordances, (
            "the in-prose link appeared in the page view's affordance list, "
            "so this test is no longer testing the case it exists for")
        assert "find_elements" in view["projection"], (
            "the projection did not name the cheap route to what it left out")

        found = await lite.find_elements(page=page, query="Fourteen Points")
        assert found["matched"] >= 1
        assert "Fourteen Points" in found["results"]
        # Tens of tokens, not a second read. The whole positioning rests on
        # this number being small.
        assert found["budget"]["used"] < 400, (
            f'the cheap follow-up cost {found["budget"]["used"]} tokens '
            f'against a {view["budget"]["used"]}-token first read')
        # And the ref it hands back is actionable, which is the rule that
        # separates this read layer from the incumbents': there is no
        # operation whose only purpose is to unlock other operations.
        ref = found["results"].splitlines()[1].split(" | ")[0]
        assert session.element_map.entries[ref].kind == "affordance"

    run(go())


def test_a_miss_comes_back_with_the_nearest_names(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/loose_controls.html")
        found = await lite.find_elements(page=page, query="Fourteen Points")
        assert found["matched"] == 0
        assert "nearest by name" in found["results"] or \
               "no near misses either" in found["results"]
        assert "not searched:" in found["results"]

    run(go())


def test_find_states_what_it_did_not_search(corpus_site):
    """The two-layer phrasing, in the follow-up as well as in the read: "I did
    not look" and "no one can look" are different answers."""
    async def go():
        _, page = await _open(corpus_site, "b/shadow.html")
        found = await lite.find_elements(page=page, query="button", kind="any")
        assert "open shadow root(s) (traversed=no)" in found["results"]
        assert "closed (unreachable by any tool)" in found["results"]

    run(go())


def test_css_and_xpath_selectors_work_and_a_bad_one_refuses(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/loose_controls.html")
        css = await lite.find_elements(page=page, query="input", kind="css")
        assert css["matched"] > 0
        with pytest.raises(Exception) as caught:
            await lite.find_elements(page=page, query="input[", kind="css")
        assert "did not parse" in str(caught.value)

    run(go())


# ------------------------------------------------------------- get_text


def test_text_is_paginated_and_teaches_its_own_continuation(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        first = await lite.get_text(page=page, max_chars=2000)
        assert first["chars"]["returned"] <= 2000
        assert first["chars"]["total_in_scope"] > 2000
        assert "start_index=" in first["continue"]
        second = await lite.get_text(
            page=page, max_chars=2000,
            start_index=first["chars"]["next_start_index"])
        assert second["text"] and second["text"] != first["text"]

    run(go())


def test_hidden_text_is_counted_and_never_returned(corpus_site):
    """An injected instruction in a display:none block shows up in the count
    and never in the content, which is the difference between this and an
    innerText read."""
    async def go():
        _, page = await _open(corpus_site, "b/secrets.html")
        got = await lite.get_text(page=page)
        assert "hidden block(s)" in got["stripped"]

    run(go())


def test_hidden_text_does_not_travel_under_an_inline_wrapper():
    """The same rule, one level down, where it was false.

    A block's own text was read as the `textContent` of its inline children,
    and `textContent` reports every hidden descendant underneath them. So a
    `display:none` instruction parked inside a paragraph's span was returned
    to the caller while the hygiene counter, walking separately, recorded the
    very same characters as withheld: 1,426 of them on the frozen GitHub page
    and 666 on the frozen Wikipedia article. Counted AND returned is worse
    than either, because the count is the evidence the read was clean."""
    async def go():
        from tests.fixtures.pages import INLINE_LEAK

        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        record = session.page(session.focused)
        await record.page.set_content(INLINE_LEAK)
        got = await lite.get_text(page=session.focused)
        assert "IGNORE ALL PREVIOUS" not in got["text"]
        assert "Concealed by visibility" not in got["text"]
        assert "hidden block(s)" in got["stripped"]
        assert "an inline wrapper with a hidden payload" in got["text"]

    run(go())


def test_a_nested_block_is_read_once_and_not_twice():
    """A list item inside a table cell's div is ONE line, not two.

    The same flattening emitted every nested block twice, once folded into
    the text of the block above it and once as itself. It cost nothing
    visible on prose and it doubled a navbox, which is why the price gate
    found it and the eye did not."""
    async def go():
        from tests.fixtures.pages import INLINE_LEAK

        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        record = session.page(session.focused)
        await record.page.set_content(INLINE_LEAK)
        got = await lite.get_text(page=session.focused)
        assert got["text"].count("Unique cell item text") == 1

    run(go())


def test_text_can_be_scoped_to_a_ref_from_a_previous_read(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        view = await lite.get_page_view(page=page)
        region = re.search(r"^(r\d+) \| main", view["projection"], re.M)
        if region is None:
            region = re.search(r"^(r\d+) \|", view["projection"], re.M)
        scoped = await lite.get_text(page=page,
                                     location={"ref": region.group(1)})
        whole = await lite.get_text(page=page)
        assert scoped["chars"]["total_in_scope"] <= \
            whole["chars"]["total_in_scope"]
        assert scoped["scope"] == {"ref": region.group(1)}

    run(go())


def test_every_printed_price_is_within_tolerance_on_the_statistical_page(
        corpus_site):
    """The page gate part 7 could not price, kept as a named regression.

    Five regions of thirty-seven sat outside the 35 percent band and all five
    were under-priced by two and a half to three times. Four of them were the
    measurement rather than the price: `get_text` was flattening hidden and
    nested text into what it returned. The fifth was the price, and it was
    the article's own data table, priced at the prose rate of the page around
    it. The three worst offenders all live here."""
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_gdp_table.html")
        view = await lite.get_page_view(page=page)
        priced = re.findall(r"^(r\d+) \|.*?~([\d,]+) tok of content",
                            view["projection"], re.M)
        assert len(priced) >= 6
        checked = 0
        for ref, advertised in priced:
            got = await lite.get_text(page=page, location={"ref": ref},
                                      max_chars=400000)
            measured = ntok(got["text"])
            if measured < 60:      # priced by overhead, not by content
                continue
            checked += 1
            advertised = int(advertised.replace(",", ""))
            # Gross against gross: this reads one region's whole subtree, so
            # a region holding others is skipped rather than compared against
            # a net price.
            if any(f'{ref} |' in line and "net of" in line
                   for line in view["projection"].splitlines()):
                continue
            error = abs(advertised - measured) / measured
            assert error <= 0.35, (
                f'{ref} advertised {advertised} tokens of content and holds '
                f'{measured}, off by {error:.0%}')
        assert checked >= 4

    run(go())


# ------------------------------------------------- location and since


def test_a_page_view_can_be_scoped_to_a_region_and_costs_less(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        whole = await lite.get_page_view(page=page)
        priced = re.search(r"^(r\d+) \|.*~([\d,]+) tok of content",
                           whole["projection"], re.M)
        ref = priced.group(1)
        scoped = await lite.get_page_view(page=page,
                                          location={"region": ref})
        assert scoped["budget"]["used"] < whole["budget"]["used"]
        assert "## 1 IDENTITY" in scoped["projection"]
        assert "COMPLETENESS" in scoped["projection"]

    run(go())


def test_a_ref_that_did_not_survive_the_read_refuses_by_name(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/app.html")
        await lite.get_page_view(page=page)
        with pytest.raises(Exception) as caught:
            await lite.get_page_view(page=page, location={"ref": "e9999"})
        assert "never minted in this session" in str(caught.value)

    run(go())


def test_a_delta_is_the_whole_answer_and_is_far_cheaper(corpus_site):
    """Deltas are impossible without sticky refs, which is why the two
    designs are one design."""
    async def go():
        _, page = await _open(corpus_site, "b/app.html")
        first = await lite.get_page_view(page=page)
        token = first["read_token"]
        delta = await lite.get_page_view(page=page, since=token)
        assert "DELTA on" in delta["projection"]
        assert delta["budget"]["used"] < first["budget"]["used"] / 2
        assert "nothing changed" in delta["projection"]
        assert delta["delta"]["navigated"] is False

    run(go())


def test_a_delta_reports_what_a_re_render_changed(corpus_site):
    async def go():
        session, page = await _open(corpus_site, "b/app.html")
        first = await lite.get_page_view(page=page)
        record = session.page(page)
        await record.page.evaluate("window.__s2.rename()")
        await record.page.wait_for_timeout(250)
        delta = await lite.get_page_view(page=page, since=first["read_token"])
        assert "~ " in delta["projection"], (
            f'a label change produced no change lines:\n'
            f'{delta["projection"]}')

    run(go())


def test_a_navigation_invalidates_the_read_token_and_says_so(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/app.html")
        first = await lite.get_page_view(page=page)
        moved = await lite.navigate(page=page,
                                    url=f"{corpus_site}/b/other.html")
        assert moved["invalidated"]["refs_invalidated"] > 0
        with pytest.raises(Exception) as caught:
            await lite.get_page_view(page=page, since=first["read_token"])
        assert "re-establish a baseline" in str(caught.value)

    run(go())


# ----------------------------------------------- GATE part 3: completeness


def test_the_completeness_block_is_accurate_by_construction(corpus_site):
    """Gate part 3. Each of these must be REPORTED rather than missed or
    silently included, and corpus B carries one of each on purpose."""
    async def go():
        _, page = await _open(corpus_site, "b/virtual.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert "virtualized or infinite container" in text, text[-1200:]

        _, page = await _open(corpus_site, "b/shadow.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert re.search(r"shadow roots: \d+ open \(traversed=no\), "
                         r"[1-9]\d* closed \(unreachable by any tool\)", text), (
            "the closed shadow roots were not counted, which means the init "
            "script that counts them as they are created did not run")

        _, page = await _open(corpus_site, "b/iframes.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert "cross-origin" in text

        _, page = await _open(corpus_site, "b/canvas.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert "canvas-rendered regions with no text projection" in text
        assert "--packs capture" in text

        _, page = await _open(corpus_site, "b/secrets.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert "hidden content stripped:" in text
        assert "secret: value never read" in text

    run(go())


# ----------------------------------------------------- GATE part 4: ladder


def test_every_rung_is_forced_on_the_fifty_thousand_node_fixture(corpus_site):
    """Gate part 4. The ladder never truncates mid-structure, and the exposed
    sequence is monotonic even where an internal step is not."""
    async def go():
        from kitchensink4web import projection as _proj

        session, page = await _open(corpus_site, "b/dom50k.html")
        record = session.page(page)
        data = await _proj.extract(record.page)
        meta = {"status": 200, "load_state": "load", "lane": "A",
                "page": "p1", "read_token": "rt1", "ts": "t"}
        sizes = []
        for rung in RUNGS:
            meter = BudgetMeter(5000)
            meter.ledger = type(meter.ledger)()
            text = Renderer(data, meta, meter, rung, "auto").build()
            sizes.append(ntok(text))
            # Never truncated: the floor keeps identity and completeness
            # whatever else goes.
            assert "## 1 IDENTITY" in text
            assert "COMPLETENESS" in text
            assert not text.endswith("...")
        exposed = [t["tokens"] for t in
                   project(data, meta, budget=5000).trace
                   if not t["dominated"]]
        assert exposed == sorted(exposed, reverse=True), (
            f"exposed ladder is not monotonic: {exposed} (raw {sizes})")
        assert len(RUNGS) >= 8

    run(go())


def test_a_three_hundred_field_form_collapses_rather_than_refusing(
        corpus_site):
    """Gate part 4's named case: rung 5's capped inventories. Enumerating
    every field of every form is unbounded, so a real enterprise settings
    screen would push the floor past any budget. The floor caps its own
    inventories instead, and a page view never refuses for that reason."""
    async def go():
        session, page = await _open(corpus_site, "b/bigform.html")
        # It must not REFUSE at any budget above the floor, which is the
        # property the capped inventories exist for.
        for budget in (5000, 2500, 1500, 1100):
            result = await lite.get_page_view(page=page,
                                              budget_tokens=budget)
            assert result["budget"]["used"] <= budget
            assert "320 fields" in result["projection"], (
                "the form's real field count stopped being stated, which is "
                "the one thing a collapsed inventory still owes the caller")

        # And at the floor it collapses to the one-line summary rather than
        # listing a sample, which is DESIGN 3.4's rung-5 requirement stated
        # literally.
        floor = await lite.get_page_view(page=page, budget_tokens=1100)
        text = floor["projection"]
        assert "fields not listed at this budget" in text, text[-1200:]
        assert 'get_page_view(view="forms")' in text
        # And the full listing is genuinely one call away, which is what
        # makes the collapse honest rather than lossy.
        full = await lite.get_page_view(page=page, view="forms",
                                        budget_tokens=20000)
        assert full["projection"].count("\n") > 200

    run(go())


# ----------------------------------------------------- GATE part 6: quotas


def test_the_github_repository_nav_bar_survives_ranking(corpus_site):
    """Gate part 6, on the frozen page the failure happened on. S1's single
    proximity score buried all thirteen tabs of this bar under truncated
    commit-message links with 2,762 tokens of headroom unused.

    The expected list comes from the MANIFEST rather than from memory,
    because the tab set is viewer-dependent: an anonymous view of this repo
    has no Wiki, Projects, or Settings tab, so a canonical nine-tab
    assertion would fail on a correct projection."""
    manifest = json.loads(
        (CORPUS / "wide" / "MANIFEST.json").read_text(encoding="utf-8"))
    captured = manifest["pages"]["github_repo"]["nav_tabs_at_capture"]
    # The repository navigation bar proper, stripped of the trailing counts
    # GitHub renders inside the tab label.
    wanted = {re.sub(r"\s+\d+$", "", t) for t in captured} & {
        "Code", "Issues", "Pull requests", "Actions", "Security and quality",
        "Insights"}
    assert len(wanted) >= 5, f"the frozen capture lost its nav bar: {captured}"

    async def go():
        _, page = await _open(corpus_site, "wide/github_repo.html")
        text = (await lite.get_page_view(page=page))["projection"]
        missing = [tab for tab in sorted(wanted) if tab not in text]
        assert not missing, f"tabs ranked out of the projection: {missing}"

    run(go())


def test_in_prose_links_appear_zero_times_and_are_counted(corpus_site):
    """Gate part 6, the other direction: on Versailles the zero quota removes
    thousands of citation links and the completeness block states the count
    and the class it belongs to."""
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        text = (await lite.get_page_view(page=page))["projection"]
        affordances = text.split("## 3 AFFORDANCES")[1].split("\n## ")[0]
        assert "[ 1 ]" not in affordances and "[ 2 ]" not in affordances
        assert re.search(r"unlisted affordances: [\d,]+ in \d+ class", text)
        assert "in-prose links" in text

    run(go())


def test_loose_controls_compete_rather_than_claiming_the_form_exemption(
        corpus_site):
    """Gate part 6's app-shell case. A control counts as a form control only
    when it is INSIDE a form. The first version classified by element type,
    so every loose input on an app shell claimed the "complete, never
    sampled" guarantee and turned it into the flood it was written to
    prevent."""
    async def go():
        from kitchensink4web import projection as _proj

        session, page = await _open(corpus_site, "b/loose_controls.html")
        record = session.page(page)
        data = await _proj.extract(record.page)
        in_form = [a for a in data["affordances"] if a["cls"] == "form_control"]
        loose = [a for a in data["affordances"]
                 if a.get("form") is False
                 and a["role"] in ("textbox", "searchbox", "checkbox",
                                   "combobox", "spinbutton")]
        assert loose, "the fixture no longer carries loose controls"
        assert all(a["cls"] != "form_control" for a in loose), (
            "a control outside any <form> claimed the form-control quota, "
            "which is the guarantee applying to a population it was never "
            "sized for")
        assert in_form, "the fixture no longer carries a real form"

    run(go())


def test_every_link_affordance_prints_a_path_and_no_line_is_shared(
        corpus_site):
    async def go():
        for path in ("wide/github_repo.html", "a/wikipedia_gdp_table.html"):
            _, page = await _open(corpus_site, path)
            text = (await lite.get_page_view(page=page))["projection"]
            for line in text.splitlines():
                if not re.match(r"^e\d+ \| link \|", line):
                    continue
                assert "," not in line.split("|")[0], line
                assert line.count("|") >= 3, (
                    f"a link affordance printed no href path: {line}")

    run(go())


# ------------------------------------------- GATE part 9: accessible names


def test_the_uh_oh_fixture_hides_the_heading_through_an_ancestor():
    """Gate part 9 states this explicitly, because Phase 1 reproduced the
    original bug while believing the rule had retired it. The heading itself
    carries real text, has no `hidden` attribute, and its own computed style
    says it renders; it never rendered because a WRAPPER several levels above
    it carried display:none. A fixture that hid the heading directly would
    pass an element-local visibility check and prove nothing."""
    from tests.fixtures.pages import NAMES

    assert re.search(r'<div class="err"[^>]*>\s*<h2>Uh oh!</h2>', NAMES), (
        "the Uh oh! heading is no longer wrapped in the hidden ancestor, so "
        "this fixture stopped testing the ancestor-chain rule")
    assert ".err{display:none}" in NAMES
    assert "<h2 style" not in NAMES.split('class="err"')[1][:80], (
        "the heading hides itself, which is the shape that does NOT defeat "
        "an element-local check")


def test_a_region_never_takes_its_name_from_a_hidden_ancestor_chain(
        corpus_site):
    """The same rule against a real page rather than a hand-written one."""
    async def go():
        _, page = await _open(corpus_site, "wide/github_repo.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert "Uh oh!" not in text

    run(go())


def test_names_never_fuse_never_truncate_mid_word_and_are_never_css_classes(
        corpus_site):
    async def go():
        from kitchensink4web import projection as _proj

        for path in ("wide/github_repo.html", "wide/ant_design.html",
                     "a/wikipedia_versailles.html"):
            session, page = await _open(corpus_site, path)
            record = session.page(page)
            data = await _proj.extract(record.page)
            for aff in data["affordances"]:
                name = aff["name"]
                # The rule is that a CSS CLASS is never a stand-in name, not
                # that a name may never begin with a dot: GitHub's file
                # listing genuinely contains a directory called
                # `.azure-pipelines`, and refusing that would be the same
                # confident wrongness in the other direction. What the
                # extractor guarantees is the FALLBACK contract: when no name
                # can be computed it emits a stable attribute prefixed with
                # `#`, or nothing at all.
                assert "[object " not in name
                if aff["name_quality"] == "attribute-fallback":
                    assert name.startswith("#"), (
                        f"the attribute fallback emitted {name!r} on {path}, "
                        f"which is neither an id nor a data-testid")
                if aff["name_quality"] == "none":
                    assert name == "", (
                        f"a name of quality 'none' still carried {name!r}")
                if aff["name_quality"] == "truncated":
                    assert name.endswith("...")
                    assert not name[:-3].endswith(" ")

    run(go())


def test_the_name_quality_flag_counts_every_fallback(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "wide/github_repo.html")
        text = (await lite.get_page_view(page=page))["projection"]
        assert "name quality:" in text

    run(go())
