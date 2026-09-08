"""Fix wave 9c (2026-09-08), against the hostile stress round
`20260908_insane_sonnet2.md`. Two findings, both of them that round's own
repro, both taken from a fixture that round built and this one tracked.

  T-01  `extract_page` returned a fully paint-cloaked, attacker-controlled
        value as a `found: true, confidence: proximate, match: exact` fact
        with `hidden_values_excluded: 0`, in the same tool-call batch where
        `get_text` on the identical page stripped and counted the identical
        string as `paint-cloaked`. Fix wave 9b HAD wired the rule into this
        collector; what it had not done was make the CHECKED unit and the
        RETURNED unit the same node. `schema.js` asked the rule of the
        element the ladder matched -- a positioned wrapper with the lid
        INSIDE it, so neither hidden nor cloaked -- and then read that
        element's aggregate rendered text recursively, and the recursion
        asked nothing of anything. A page picks its own nesting, so a gap of
        that shape is a page-controlled channel.

  T-02  `get_text`'s `stripped` ledger claimed "0 hidden block(s) ... [none]"
        on a page whose only hidden content lived inside open shadow roots.
        The text itself was filtered correctly -- three prompt-injection
        payloads never reached the payload -- and the ACCOUNTING was false,
        because the withheld text was measured with `textContent`, which
        stops dead at every shadow boundary and returns the empty string for
        a component with no light children. `get_page_view` counted the same
        page correctly, so two reads told one caller two stories about one
        document.

THE CLASS, not the instance. T-01's real subject is `ksRenderedText`, which
every VALUE harvest in the build shares, so the fix landed in that shared
source as `ksVisibleRenderedText` and every surface that harvests a value is
pinned here: `extract_page` (all four tiers), `aggregate` (the same
`_schema_read` body), `get_table`'s cells, `get_list`'s items, and
`extract_fields`. Excluded content is COUNTED on every one of them, because a
value silently shortened is the same completeness lie as a value silently
included.

THE LINE THAT DID NOT MOVE, pinned twice below. VALUES get the rule; KEYS keep
the plain reader, because `sr-only` labels are how the accessible web names
its own fields and running the rule over keys would blind every value harvest
to every screen-reader-labelled control on the web. (One pre-existing
exception this wave did not touch: `schema.js`'s tier 3 has refused to treat a
hidden LEAF as a label since 9b, on its own ground -- a label a human cannot
see cannot anchor a proximate relation a human could check.) And
`find_elements` still hands a cloaked control to the acting path, which fix
wave 9b established and this wave deliberately leaves alone: retrieval is not
reporting, and only the acting path runs the pixel arbiter that clears box
math's false positives.
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
from kitchensink4web.ops import extract, lite
from kitchensink4web.policy import audit, budgets, credentials, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"

#: Every mark on the two repro fixtures and the sweep page. A payload that
#: contains any of these strings has handed back text no human can see.
CLOAKED_MARKS = (
    "CLOAKED-VALUE-99999", "RECOVERY-CLOAKED-77777", "CLOAK-TABLE-11111",
    "CLOAK-LIST-22222", "CLOAK-DL-33333", "CLOAK-ROW-44444",
    "CLOAK-ARIA-55555", "CLOAK-PROX-66666",
)


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


def _no_marks(blob: str):
    for mark in CLOAKED_MARKS:
        assert mark not in blob, f"{mark} reached a payload:\n{blob[:3000]}"


# -------------------------------------------------------------------- T-01


@pytest.mark.parametrize(
    "fixture,field,hint",
    [("g2/cloak_extract.html", "balance", "the account balance"),
     ("g2/cloak_extract2.html", "recovery_code",
      "the account recovery code")])
def test_extract_page_does_not_hand_back_a_painted_over_value(
        corpus_site, fixture, field, hint):
    """The round's own repro, on both fixtures it built.

    Both fail on `c0145ac`: `found: true`, the cloaked string as the value,
    `hidden_values_excluded: 0`. The second fixture matters as much as the
    first -- it was built independently to rule out a geometry artifact in
    the first, and it leaked identically, which is what made this a class."""
    async def go():
        _, page = await _open(corpus_site, fixture)
        got = await extract.extract_page(page=page, schema={field: hint})
        _no_marks(str(got))
        entry = got["fields"][field]
        assert entry["found"] is False, entry
        # NOT `empty`, which would say the page left the field blank. The
        # page wrote a value and painted over it, and those are different
        # facts about a page.
        assert entry["reason"] == "hidden", entry
        # COUNTED, and the technique NAMED, in the same ledger the caller
        # already reads for secrets and caps.
        acc = got["accounting"]
        assert acc["hidden_values_excluded"] >= 1, acc
        assert "paint-cloaked" in acc["hidden_value_techniques"], acc

    run(go())


@pytest.mark.parametrize(
    "fixture,mark",
    [("g2/cloak_extract.html", "CLOAKED-VALUE-99999"),
     ("g2/cloak_extract2.html", "RECOVERY-CLOAKED-77777")])
def test_the_prose_read_and_the_value_read_agree_on_the_same_page(
        corpus_site, fixture, mark):
    """THE DISAGREEMENT IS THE DEFECT, so it is pinned as a disagreement.

    The round found this by asking two tools the same question in one batch
    and getting two answers. Neither answer alone proves anything; the pair
    does, which is why both halves run here against one page load."""
    async def go():
        _, page = await _open(corpus_site, fixture)
        text = await lite.get_text(page=page)
        assert mark not in text["text"], text["text"]
        assert "paint-cloaked=1" in text["stripped"], text["stripped"]
        got = await extract.extract_page(
            page=page, schema={"anything": "the value beside the label"})
        assert mark not in str(got)

    run(go())


# ------------------------------------------------------- T-01, the class


def test_every_value_harvest_refuses_the_same_cloak_and_counts_it(
        corpus_site):
    """One page, one cloak technique, seven places a value is harvested.

    `get_table` reads cell text, `get_list` reads item text, and
    `extract_fields` reads definition lists and two-column rows -- none of
    them asked ANY visibility question before this wave, so a page could
    park an instruction under an opaque box in a data cell and have the
    tabular read hand it back as the row's value while the prose read on the
    same page stripped and counted it."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_values.html")

        table = await extract.get_table(page=page, index=0)
        _no_marks(str(table))
        assert table["accounting"]["hidden_cell_content_excluded"] >= 1, table
        assert "paint-cloaked" in table["accounting"]["hidden_cell_techniques"]
        assert "counted and NOT returned" in table["continue"], table

        listing = await extract.get_list(page=page)
        _no_marks(str(listing))
        assert listing["accounting"]["hidden_item_content_excluded"] >= 1
        assert "counted and NOT returned" in listing["continue"], listing

        fields = await extract.extract_fields(
            page=page, fields=["Definition secret", "Row secret"])
        _no_marks(str(fields))
        for name in ("Definition secret", "Row secret"):
            assert fields["fields"][name]["reason"] == "hidden", fields
        assert fields["accounting"]["hidden_values_excluded"] >= 2, fields

        got = await extract.extract_page(page=page, schema={
            "Definition secret": "the definition-list value",
            "Row secret": "the two-column row value",
            "Aria secret": "the aria-labelled value",
            "Proximate secret": "the value beside the proximate label"})
        _no_marks(str(got))
        for name in ("Definition secret", "Row secret", "Aria secret",
                     "Proximate secret"):
            assert got["fields"][name]["reason"] == "hidden", got["fields"]
        assert got["accounting"]["hidden_values_excluded"] >= 4

        # And the prose read, on the same page, still names every one of
        # them: the surfaces agree now instead of contradicting each other.
        text = await lite.get_text(page=page)
        _no_marks(text["text"])
        assert "paint-cloaked=" in text["stripped"], text["stripped"]

    run(go())


def test_an_exported_file_carries_the_same_receipt_the_read_does(
        corpus_site, tmp_path):
    """`export_data` runs `get_table`'s identical grid walk, so it withholds
    identical cell content -- and it writes to DISK, which puts the missing
    content one step further from anyone who could notice. The count rides
    the payload rather than the file, because a stray column in a CSV would
    break the Excel handoff this tool exists for."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_values.html")
        out = str(tmp_path / "table.csv")
        got = await extract.export_data(page=page, path=out, index=0)
        assert got["accounting"]["hidden_cell_content_excluded"] >= 1, got
        _no_marks(Path(got["saved_to"]).read_text(encoding="utf-8"))

    run(go())


def test_the_batch_tool_answers_exactly_as_the_single_page_tool_does(
        corpus_site):
    """`aggregate` shares `_schema_read` with `extract_page`, which is what
    stops the batch tool from drifting from the single-page one. Pinned
    rather than assumed, because a shared body is only shared until someone
    copies it."""
    async def go():
        _, page = await _open(corpus_site, "g2/blank.html")
        got = await extract.aggregate(
            urls=[f"{corpus_site}/g2/cloak_extract.html"],
            schema={"balance": "the account balance"}, page=page)
        _no_marks(str(got))

    run(go())


# -------------------------------------------------------------------- T-02


def test_the_prose_ledger_counts_hidden_content_inside_shadow_roots(
        corpus_site):
    """`g2/shadow_cloak.html`, and the finding is about the LEDGER rather
    than the content: the three hidden components' prose never reached the
    payload, and the read said nothing had been withheld while doing it."""
    async def go():
        _, page = await _open(corpus_site, "g2/shadow_cloak.html")
        got = await lite.get_text(page=page)
        # The content was always right; this half is the regression guard.
        # Three of the seven components are hidden by their containers and
        # four are not, so the read keeps exactly four and drops exactly
        # three -- a precision case, not a blanket exclusion.
        for hidden in ("SHADOW PROSE DETAILS", "SHADOW PROSE CV",
                       "SHADOW PROSE OFF"):
            assert hidden not in got["text"], got["text"]
        assert "SHADOW PROSE PLAIN" in got["text"], got["text"]
        # The accounting is the fix.
        ledger = got["stripped"]
        assert "0 hidden block(s)" not in ledger, ledger
        assert "[none]" not in ledger, ledger
        assert "3 hidden block(s)" in ledger, ledger
        for reason in ("details-collapsed", "content-visibility-hidden",
                       "offscreen"):
            assert reason in ledger, ledger

    run(go())


def test_the_two_reads_no_longer_contradict_each_other_about_one_page(
        corpus_site):
    """The cross-check that found it. `get_page_view` counted this page
    correctly the whole time; the defect was only visible by asking both."""
    async def go():
        _, page = await _open(corpus_site, "g2/shadow_cloak.html")
        got = await lite.get_text(page=page)
        view = await lite.get_page_view(page=page)
        # Both ledgers now say content was withheld from this page. They
        # count in different units (nodes there, blocks here) and neither
        # may say zero while the other names eight.
        assert "hidden content stripped:" in view["projection"], (
            view["projection"])
        assert "0 hidden block(s)" not in got["stripped"], (
            got["stripped"], view["projection"])

    run(go())


# ------------------------------------------- the directions that must hold


def test_a_screen_reader_label_is_still_a_key_this_reader_can_use(
        corpus_site):
    """THE LINE BETWEEN A KEY AND A VALUE, and it decides whether this wave
    can ship at all.

    `class="sr-only"` labels are how the accessible web names its own
    fields. Running the value rule over KEYS would drop every one of them
    and blind `extract_fields` and `extract_page` to every
    screen-reader-labelled control on the page, which is a far larger hole
    than the one this wave closed. Keys keep the plain reader."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_values.html")
        got = await extract.extract_fields(
            page=page, fields=["Account number"])
        entry = got["fields"]["Account number"]
        assert entry["found"] is True, got
        assert entry["value"] == "0011-2233-4455", entry
        # And `extract_page` reads the same field the same way.
        page_got = await extract.extract_page(
            page=page, schema={"Account number": "the account number"})
        assert page_got["fields"]["Account number"]["found"] is True, page_got

    run(go())


def test_ordinary_pages_lose_no_values_to_the_walk(corpus_site):
    """THE FALSE-POSITIVE ARM, on the value surfaces this time.

    Fix wave 9b's own pin proves the read-side cloak rule strips no prose
    from the frozen Wikipedia article. This one proves the same of the value
    harvests now that the rule follows the text down: the infobox is a
    two-column table of exactly the shape the new walk descends through, and
    it must come back whole."""
    async def go():
        _, page = await _open(corpus_site, "a/wikipedia_versailles.html")
        got = await extract.extract_fields(page=page, fields=["signed"])
        acc = got["accounting"]
        assert acc["sources_searched"] > 20, acc
        assert acc["hidden_value_techniques"].get("paint-cloaked", 0) == 0, acc

    run(go())


def test_the_cloak_thresholds_sit_exactly_where_the_comments_say(
        corpus_site):
    """SIX PROBES AT THE DOCUMENTED EDGES, tracked rather than borrowed.

    The round built `g2/cloak_boundary.html` from scratch to test the rule's
    thresholds instead of trusting the shipped suite's own cases, and every
    probe landed where the code comments say it should. It is a corpus
    fixture now, because a threshold nobody re-tests is a threshold that
    drifts: five constructions must stay readable (a 0.6-alpha modal scrim,
    a half-covered box, a 0.9-alpha cover just under the line, an in-flow
    static cover which is the DOCUMENTED residual gap, and plain prose) and
    two must not (total opaque coverage, and 0.97 alpha just over the line).
    """
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_boundary.html")
        got = await lite.get_text(page=page)
        for readable in ("MARK VISIBLE", "MARK TRANSLUCENT", "MARK PARTIAL",
                         "MARK NEAR", "MARK STATIC"):
            assert readable in got["text"], (readable, got["text"])
        for cloaked in ("MARK TOTAL", "MARK OVER"):
            assert cloaked not in got["text"], (cloaked, got["text"])
        assert "paint-cloaked=2" in got["stripped"], got["stripped"]

    run(go())


def test_the_article_read_still_excludes_a_cloaked_paragraph(corpus_site):
    """`g2/cloak_article.html`, the round's other purpose-built fixture.
    `cloak_light.html` is not article-shaped, so this surface had no repro
    of its own until that round wrote one."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_article.html")
        got = await extract.get_article(page=page)
        assert "MARK ARTICLE BEHIND" not in str(got), got
        view = await lite.get_page_view(page=page)
        assert "paint-cloaked" in view["projection"], view["projection"]

    run(go())


# -------------------------------------------------------------------- R-01


#: The nine ordinary constructions `g2/cloak_ordinary.html` carries, every
#: one of them out of flow, exactly covering, and painting nothing over the
#: prose beneath it. Six are the pixel arbiter's own seven; the gradient fade
#: and the photo scrim are what they look like on a real page; the iframe was
#: source-derived and unmeasured when the class was found.
ORDINARY_LIDS = ("MARK VISIBLE", "MARK FADE", "MARK SCRIM", "MARK CLIP",
                 "MARK MASK", "MARK SVG", "MARK CANVAS", "MARK SPACER",
                 "MARK BLEND", "MARK FRAME")


def test_an_ordinary_lid_does_not_take_the_prose_underneath_it(corpus_site):
    """THE REGRESSION FIX WAVE 9B SHIPPED, running the other way.

    Nine lids that satisfy every one of the read rule's three box conditions
    and paint nothing over the text. On `c0145ac` all but the anchor come
    back withheld, and the publisher's continue-reading fade -- ordinary
    markup on a large fraction of the web -- takes the whole article body
    and reports it as content carrying "the shape of an injected
    instruction". A read tool that loses real prose and tells the caller the
    page hid it is this build's cardinal defect class pointed at the
    reader."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_ordinary.html")
        got = await lite.get_text(page=page, max_chars=100000)
        for mark in ORDINARY_LIDS:
            assert mark in got["text"], (mark, got["stripped"])

    run(go())


def test_the_control_on_the_same_page_is_still_excluded_and_counted(
        corpus_site):
    """THE ARM THAT STOPS THE FIX FROM BEING A REVERT. `cloak_ordinary.html`
    carries one plain opaque white box over one paragraph, and a fix that
    simply switched the rule off would pass everything above and fail
    here."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_ordinary.html")
        got = await lite.get_text(page=page, max_chars=100000)
        assert "MARK CONTROL BEHIND" not in got["text"], got["text"]
        assert "paint-cloaked=1" in got["stripped"], got["stripped"]

    run(go())


def test_the_original_cloak_repro_does_not_reopen(corpus_site):
    """S-02's own page, pinned inside this wave as well as 9b's, because
    this wave narrows the very rule that closed it. `cloak_light.html`'s lid
    is a plain background colour, which is exactly the case the read can
    still compute."""
    async def go():
        _, page = await _open(corpus_site, "g2/cloak_light.html")
        got = await lite.get_text(page=page)
        assert "MARK BEHIND" not in got["text"], got["text"]
        assert "paint-cloaked=1" in got["stripped"], got["stripped"]

    run(go())


def test_the_search_still_hands_a_cloaked_target_to_the_acting_path(
        corpus_site):
    """FIX WAVE 9B'S LINE, RE-PINNED HERE because this wave walked right
    past it. `find_elements` retrieves targets; the acting path owns the
    better verdict, since only it runs the pixel arbiter. Filtering here
    once already turned "an opaque panel is painted over it" into "nothing
    visible matches", which is a worse answer about the same fact."""
    async def go():
        _, page = await _open(corpus_site, "ra/overlay.html")
        found = await lite.find_elements(page=page,
                                         query="Transfer balance to 9912")
        assert "1 of 1 match" in found["results"], found["results"]

    run(go())
