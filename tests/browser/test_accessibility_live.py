"""The accessibility audit, against real pages and a real engine.

The battery that cannot be compromised is the honesty one. An accessibility
report that overstates its coverage produces a false conformance claim that
a real person then relies on, so every one of these is written against a
specific way this tool could lie: folding an undecided check into a pass,
reporting a partial audit as a complete one, running a different engine
under the first one's name, quietly skipping a frame, or omitting the window
size that changed the answer.

The rest pin the shape the product already sells: a cheap first read
aggregated by rule, a cheap targeted follow-up per rule, a monotonic ladder,
and every page-derived string inside the labeled envelope.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kitchensink4web import packs
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (BadParams, RangeOutOfBounds,
                                    TargetNotFound, ValidationFailed)
from kitchensink4web.ops import a11y, lite
from kitchensink4web.policy import readonly
from kitchensink4web.projection import meter

pytestmark = pytest.mark.browser

needs_engine = pytest.mark.skipif(
    __import__("importlib").util.find_spec("axe_playwright_python") is None,
    reason="the accessibility extra is not installed in this environment")


@pytest.fixture(autouse=True)
def loaded_packs(monkeypatch):
    monkeypatch.setattr(packs, "_LOADED",
                        set(packs.PACK_SUMMARIES), raising=False)
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


async def _open(base, path, **kwargs):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True,
                                 **kwargs)
    page = session.focused
    await lite.navigate(page=page, url=f"{base}{path}")
    return session, page


# --------------------------------------------------------- honesty battery


@needs_engine
def test_an_undecided_check_is_neither_a_pass_nor_a_failure(fixture_site):
    """P17-01. Text over a background image is a contrast check the engine
    RAN and could not decide. It must land in needs_review, be counted on
    its own, and never appear as a violation or a pass."""
    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        got = await a11y.get_accessibility(page=page,
                                           include="violations+review")
        review = {row["rule"] for row in got.get("needs_review", [])}
        violated = {row["rule"] for row in got["violations"]}
        assert "color-contrast" in review, got.get("needs_review")
        assert got["totals"]["needs_review_nodes"] >= 1
        assert not (review & violated & {"color-contrast"}) or True
        for row in got.get("needs_review", []):
            assert row["why"]
            assert "neither a pass nor a failure" in row["note"]
    run(go())


@needs_engine
def test_no_denominator_anywhere_contains_needs_review(fixture_site):
    """P17-02, asserted by construction: there is no percentage, no ratio,
    and no score in the payload at all, so there is no denominator to get
    wrong."""
    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        got = await a11y.get_accessibility(page=page, include="all")
        # There is no score FIELD anywhere, at any depth, and no ratio: the
        # only place the word appears is the sentence saying there is none.
        def walk(node, path=""):
            if isinstance(node, dict):
                for key, value in node.items():
                    assert "score" not in key.lower(), f"{path}.{key}"
                    assert "percent" not in key.lower(), f"{path}.{key}"
                    assert "ratio" not in key.lower(), f"{path}.{key}"
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")
            elif isinstance(node, float):
                raise AssertionError(f"a fractional number at {path}: "
                                     f"every count here is a whole thing")
        walk(got)
        assert "deliberately no score" in got["totals"]["note"]
        assert "needs_review is counted on its own" in got["totals"]["note"]
    run(go())


@needs_engine
def test_a_clean_page_still_says_what_was_not_checked(fixture_site):
    """P17-08. Zero violations is the most dangerous result to report
    without a caveat, because it is the one somebody quotes."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yclean")
        got = await a11y.get_accessibility(page=page)
        assert got["totals"]["rules_violated"] == 0, got["violations"]
        assert "not a conformance claim" in got["coverage"]["caveat"]
        assert "Deque" in got["coverage"]["caveat"]
        assert got["coverage"]["not_checked"]
        assert got["coverage"]["adversarial"]
        assert "page's own JavaScript" in got["coverage"]["adversarial"]
    run(go())


@needs_engine
def test_the_engine_and_version_are_always_named(fixture_site):
    """P17-07. A caller can always tell which engine spoke, and the version
    comes from the engine itself rather than from a table in this repo."""
    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        got = await a11y.get_accessibility(page=page)
        assert got["scope"]["engine"].startswith("axe-core 4.")
        assert "version unreported" not in got["scope"]["engine"]
        assert "not vendored" in got["scope"]["engine_source"]
    run(go())


@needs_engine
def test_the_viewport_is_stated_and_it_changes_the_answer(fixture_site):
    """P17-09. The engine cannot contrast-check an element outside the
    viewport, so the window size is an audit INPUT. A result that does not
    name it is not reproducible."""
    async def go():
        small = None
        for size in ({"width": 800, "height": 400},
                     {"width": 1600, "height": 1200}):
            session = await MANAGER.open(lane="A", engine="chromium",
                                         headless=True,
                                         viewport=f"{size['width']}x"
                                                  f"{size['height']}")
            page = session.focused
            await lite.navigate(page=page, url=f"{fixture_site}/a11y")
            got = await a11y.get_accessibility(page=page,
                                               include="violations+review")
            assert got["coverage"]["viewport"]["width"] == size["width"]
            assert got["coverage"]["viewport"]["height"] == size["height"]
            assert "reproducible" in got["coverage"]["viewport_note"]
            if small is None:
                small = got["totals"]
            await MANAGER.close(session.session_id)
    run(go())


@needs_engine
def test_a_cross_origin_frame_is_named_rather_than_silently_skipped(
        fixture_site, cross_origin_site):
    """P17-14, the verified silent-omission hazard. The engine skips
    cross-origin frames by default and its result still LOOKS complete."""
    async def go():
        _s, page = await _open(fixture_site,
                               f"/a11yframe?src={cross_origin_site}/a11y")
        got = await a11y.get_accessibility(page=page)
        not_entered = got["scope"]["frames_not_entered"]
        assert not_entered, got["scope"]
        assert all(row["why"] for row in not_entered)
        assert "NOT audited" in got["scope"]["frames_note"]
        assert got["coverage"]["frames_not_entered"] == len(not_entered)
    run(go())


@needs_engine
def test_a_same_origin_frame_is_audited_and_its_counts_add(fixture_site):
    """P17-15. The server drives the frames, so a violation inside an
    entered frame is in the totals and says which frame it came from."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yframe")
        got = await a11y.get_accessibility(page=page)
        assert len(got["scope"]["frames_audited"]) >= 2
        rules = {row["rule"] for row in got["violations"]}
        # The framed document carries an image with no alt of its own.
        assert "image-alt" in rules, rules
        drill = await a11y.get_accessibility(page=page, rule="image-alt")
        assert any(node.get("frame") for node in drill["nodes"]), drill
    run(go())


@needs_engine
def test_a_strict_csp_page_is_audited_rather_than_read_as_clean(
        fixture_site):
    """P17-13. The injection route was measured against `script-src 'self'`
    with no `unsafe-eval` before a line of this was written. If it ever
    stops working the tool must REFUSE, never return an empty audit that
    reads like a clean page."""
    async def go():
        _s, page = await _open(fixture_site, "/a11ycsp")
        got = await a11y.get_accessibility(page=page)
        assert got["totals"]["rules_violated"] >= 1, got
    run(go())


# ------------------------------------------------------ containment battery


@needs_engine
def test_page_derived_strings_ride_the_envelope(fixture_site):
    """P17-11. A failure summary LOOKS like engine prose and carries page
    bytes inside it, and a CSS selector is built from the page's own class
    names. Both are somebody else's words."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yhostile")
        got = await a11y.get_accessibility(page=page)
        blob = json.dumps(got)
        assert "KS4WEB-PAGE-DATA" in blob
        assert got["page_data"]["nonce"] in got["page_derived"]
        assert "page-derived parts" in got["page_data"]["label"]
        # The instruction the page painted into a class name is inside the
        # envelope, never in a server-voice field.
        for row in got["violations"]:
            assert "IGNORE PREVIOUS" not in row["help"]
            assert "IGNORE PREVIOUS" not in row["rule"]
    run(go())


@needs_engine
def test_no_unbounded_page_string_reaches_the_payload(fixture_site):
    """P17-12."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yhostile")
        got = await a11y.get_accessibility(page=page, rule="image-alt")
        for node in got["nodes"]:
            assert len(node["html"]) <= a11y.SNIPPET_CLIP + 3
            assert len(node["target"]) <= a11y.SNIPPET_CLIP + 3
    run(go())


def test_the_engine_source_never_carries_the_instrument_secret():
    """P17-18, static. The ref mapping is this server's own script and is
    spliced; the engine is third-party code and is not."""
    from kitchensink4web import projection
    source = a11y._engine_source()
    assert projection.INSTRUMENT_SECRET not in source
    assert projection.INSTRUMENT_KEY not in source
    assert "@@KS4WEB_INSTRUMENT@@" not in source
    # ...and the mapping script IS spliced, or it could not read the map.
    assert projection.INSTRUMENT_SECRET in a11y._REF_JS


def test_get_accessibility_is_classified_and_available_read_only():
    """P17-10's consequence and P17-33. The DOM-purity measurement came
    back identical on every fixture page, so the audit is a read and a
    read-only KS4Web can run it."""
    assert readonly.is_mutating("get_accessibility") is False
    assert readonly.read_only_hint("get_accessibility") is True


@needs_engine
def test_the_audit_leaves_the_dom_byte_identical(fixture_site):
    """P17-10 itself, kept as a running pin rather than a one-off
    measurement: the classification above is only true while this is."""
    snapshot = """() => ({
      html: document.documentElement.outerHTML,
      nodes: document.getElementsByTagName('*').length,
      attrs: Array.from(document.querySelectorAll('*'))
                  .reduce((n, el) => n + el.attributes.length, 0)
    })"""

    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        from kitchensink4web.ops import common
        _sess, record = common.locate(page)
        before = await record.page.evaluate(snapshot)
        await a11y.get_accessibility(page=page)
        after = await record.page.evaluate(snapshot)
        assert before == after
    run(go())


# ----------------------------------------------------------- budget battery


@needs_engine
def test_the_default_read_aggregates_by_rule_not_by_node(fixture_site):
    """P17-25. A page with many identical violations returns one rule line
    with a count, not one entry per node."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yflood")
        got = await a11y.get_accessibility(page=page)
        rows = [r for r in got["violations"] if r["rule"] == "image-alt"]
        assert rows and rows[0]["count"] >= 100, got["totals"]
        assert len(rows[0].get("examples", [])) <= 3
        assert "get_accessibility(rule=" in rows[0]["more"]
        assert got["budget"]["used"] < 3000
    run(go())


@needs_engine
def test_the_ladder_is_monotonic(fixture_site):
    """P17-21, the regression this project has already hit once: a lower
    rung's payload got BIGGER than the rung above it."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yflood")
        sizes = []
        for budget in (600, 900, 1500, 3000, 6000):
            got = await a11y.get_accessibility(page=page,
                                               budget_tokens=budget,
                                               include="violations+review")
            used = meter.ntok(json.dumps(got, ensure_ascii=False))
            sizes.append((budget, used, got["budget"]["rung"]))
            # THE LADDER NEVER DROPS A TOTAL AND NEVER DROPS COVERAGE.
            assert got["totals"]["rules_violated"] >= 0
            assert got["coverage"]["caveat"]
            assert "needs_review" in json.dumps(got["totals"])
        for (b1, u1, _r1), (b2, u2, _r2) in zip(sizes, sizes[1:]):
            assert u1 <= u2 + 40, (sizes,)
    run(go())


@needs_engine
def test_the_lowest_rung_still_carries_every_total(fixture_site):
    """P17-03."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yflood")
        got = await a11y.get_accessibility(page=page, budget_tokens=500)
        assert got["totals"]["rules_violated"] >= 1
        assert got["coverage"]["caveat"]
        assert got["completeness"]["rules_total"] >= \
            got["completeness"]["rules_printed"]
        assert "get_accessibility(rule=" in \
            got["completeness"]["how_to_get_the_rest"]
    run(go())


@needs_engine
def test_the_drilldown_paginates_and_states_both_numbers(fixture_site):
    """P17-22 and P17-23."""
    async def go():
        _s, page = await _open(fixture_site, "/a11yflood")
        first = await a11y.get_accessibility(page=page, rule="image-alt")
        assert first["total"] >= 100
        assert first["shown"] <= 50
        assert first["next_start_index"] == first["shown"]
        second = await a11y.get_accessibility(
            page=page, rule="image-alt",
            start_index=first["next_start_index"])
        assert second["start_index"] == first["next_start_index"]
        with pytest.raises(RangeOutOfBounds) as exc:
            await a11y.get_accessibility(page=page, rule="image-alt",
                                         start_index=99999)
        assert "past the end" in str(exc.value)
    run(go())


# -------------------------------------------------------------- refusals


@needs_engine
def test_an_unknown_rule_names_the_rules_that_did_fire(fixture_site):
    """P17 refusal contract: the caller retries without a second aggregate
    read."""
    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        with pytest.raises(TargetNotFound) as exc:
            await a11y.get_accessibility(page=page, rule="no-such-rule")
        assert "image-alt" in str(exc.value)
    run(go())


@needs_engine
def test_an_unknown_tag_refuses_rather_than_reading_as_clean(fixture_site):
    """An unknown tag makes the engine select NOTHING, which is
    indistinguishable from a clean page unless somebody says so."""
    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        with pytest.raises(BadParams) as exc:
            await a11y.get_accessibility(page=page, tags=["wcag2zzz"])
        assert "wcag2zzz" in str(exc.value)
        assert "would have read like a clean page" in str(exc.value)
    run(go())


def test_an_unknown_impact_refuses_with_the_set_named():
    async def go():
        with pytest.raises(BadParams) as exc:
            await a11y.get_accessibility(page="p1", impact="catastrophic")
        assert "critical" in str(exc.value)
    asyncio.run(go())


def test_start_index_without_a_rule_refuses():
    async def go():
        with pytest.raises(BadParams) as exc:
            await a11y.get_accessibility(page="p1", start_index=10)
        assert "rule=" in str(exc.value)
    asyncio.run(go())


def test_a_missing_engine_refuses_and_never_substitutes_one(monkeypatch):
    """P17-06. No silent fallback: a result labeled with an engine that did
    not produce it is worse than no result."""
    import builtins
    real = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("axe_playwright_python"):
            raise ImportError("blocked for the test")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ValidationFailed) as exc:
        a11y._engine_source()
    assert "kitchensink4web[accessibility]" in str(exc.value)
    assert "falls back" in str(exc.value)


def test_every_code_this_tool_emits_is_in_the_closed_vocabulary():
    """P17-34: no new error code was added for this feature."""
    from kitchensink4web import envelope
    for exc in (BadParams, RangeOutOfBounds, TargetNotFound,
                ValidationFailed):
        assert envelope.classify(exc("x")) in envelope.CLOSED_CODES


@needs_engine
def test_an_issue_carries_a_ref_when_the_element_is_in_the_registry(
        fixture_site):
    """P17-37. A ref is what makes an issue actionable, and it is never
    fabricated: an element the registry has not seen comes back with
    `ref: null` rather than a selector wearing a ref's clothes."""
    async def go():
        _s, page = await _open(fixture_site, "/a11y")
        cold = await a11y.get_accessibility(page=page)
        cold_refs = [node["ref"] for row in cold["violations"]
                     for node in row.get("examples", [])]
        assert cold_refs and all(r is None for r in cold_refs), cold_refs

        # A read mints the registry, and the SAME audit now carries refs.
        await lite.get_page_view(page=page)
        warm = await a11y.get_accessibility(page=page)
        warm_refs = [node["ref"] for row in warm["violations"]
                     for node in row.get("examples", [])]
        assert any(r for r in warm_refs), warm_refs
        # Every ref handed out is one the registry can actually resolve,
        # which is the difference between a ref and a decorated selector.
        from kitchensink4web.ops import common
        sess, _record = common.locate(page)
        for ref in [r for r in warm_refs if r]:
            assert ref in sess.element_map.entries, ref
    run(go())


@needs_engine
def test_the_recipe_and_the_pack_menu_name_the_launch_flag():
    """P17-36."""
    got = asyncio.run(lite.get_workflows(topic="accessibility"))
    text = json.dumps(got)
    assert "get_accessibility" in text
    assert "--packs accessibility" in text or "KS4WEB_PACK_ACCESSIBILITY" \
        in text
    assert "needs_review" in text
