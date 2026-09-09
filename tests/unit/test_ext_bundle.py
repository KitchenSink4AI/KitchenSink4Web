"""THE DRIFT PIN on the projection bundle, and what it is protecting.

`projection/visibility.js`, `payment.js`, `aria.js`, `activation.js`,
`consent.js`, `href.js` and `rendered.js` exist as single files because every
gap between duplicated copies of those rules was a finding: an element the
projection counted as hidden came back from a search as in-view, a card field
that declared no autocomplete token was unclassified everywhere at once, and
a `<label>` over a submit button submitted a form carrying a live PAN with no
class computed.

The extension bundle is a SIXTH consumer of those blocks and it is the first
one that lives on disk rather than being built at import. So it is the first
one that can go stale, and a stale copy is exactly the defect the
consolidation removed: Lane C would classify a page by last month's payment
rule while every other lane used this month's, and both would return a
confident answer.

The pin is a byte comparison against what the generator makes from the
sources as they are right now. Rebuild with:

    python -m kitchensink4web.extension.bundle
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kitchensink4web import projection
from kitchensink4web.extension import bundle

ROOT = Path(__file__).resolve().parents[2]


def test_the_bundle_on_disk_matches_the_sources_it_was_built_from():
    """The whole point of the file. A projection source edited without a
    rebuild fails HERE, loudly, rather than in a page nobody is watching."""
    path = bundle.bundle_path(ROOT)
    assert path.exists(), (
        f"{path} is missing. Build it with "
        f"`python -m kitchensink4web.extension.bundle`.")
    on_disk = path.read_text(encoding="utf-8")
    assert on_disk == bundle.build(), (
        "the projection bundle in extension/ is stale: a source under "
        "src/kitchensink4web/projection/ changed and the bundle was not "
        "rebuilt, so Lane C would read pages by an older rule than every "
        "other lane. Run `python -m kitchensink4web.extension.bundle`.")


def test_the_bundle_carries_every_script_the_lane_can_run():
    """The other direction: a name in the closed set with no script behind it
    would refuse at the content script with UNKNOWN_SCRIPT, which is a
    confusing way to find out the generator dropped one."""
    text = bundle.build()
    for name in bundle.EXTENSION_SCRIPTS:
        assert re.search(rf"^  {name}: \($", text, re.M), name


def test_the_shared_blocks_are_in_the_bundle_exactly_once():
    """HOISTED, not spliced per script. Splicing put `visibility.js` in four
    times and doubled the file to 575 KB, and this bundle is parsed in a real
    page: the size is a latency cost somebody pays."""
    text = bundle.build()
    # The shared block's OWN name, not the local `hiddenReason` wrappers
    # `article.js` and `text.js` each build around it. Those wrappers are
    # per-script by design and are a different thing from a duplicated rule.
    for marker in ("function ksHiddenReason", "function ksPaymentField",
                   "function ksDelegatedActivation"):
        assert text.count(marker) == 1, (
            f"{marker} appears {text.count(marker)} times; the shared blocks "
            f"are meant to be emitted once at bundle scope and closed over.")


def test_no_script_body_still_carries_a_splice_mark():
    """A mark left behind is a block that did not land, and the script would
    then fail on an undefined function at read time rather than here."""
    text = bundle.build()
    for mark in ("@@KS4WEB_VISIBILITY@@", "@@KS4WEB_PAYMENT@@",
                 "@@KS4WEB_ARIA@@", "@@KS4WEB_ACTIVATION@@",
                 "@@KS4WEB_CONSENT@@", "@@KS4WEB_HREF@@",
                 "@@KS4WEB_INSTRUMENT@@", "@@KS4WEB_RENDERED@@"):
        # The hoist leaves a note naming the mark, so the bare mark is what
        # must be gone rather than every mention of the word.
        assert f"// {mark}" not in text, mark


def test_the_bundle_carries_no_process_secret():
    """The Playwright prelude bakes a per-process secret into every injected
    source. A generated file that carried one would differ on every run (so
    the drift pin above could never pass) and would ship a secret from
    whichever machine built it."""
    text = bundle.build()
    assert projection.INSTRUMENT_SECRET not in text
    assert projection.INSTRUMENT_KEY not in text
    # And the reason it does not need one: the state is a closure in the
    # content script's own world, which page script cannot address.
    assert "const KS = KS4WEB_STATE;" in text


def test_generating_twice_produces_the_same_bytes():
    """The pin is a byte comparison, so the generator has to be
    deterministic. A dict iteration order or a timestamp in here would make
    the suite fail intermittently for a reason that is not drift."""
    assert bundle.build() == bundle.build()


def test_the_closed_root_counter_is_an_absence_and_not_a_zero():
    """The completeness block's closed-root line is a claim about what NO
    tool can reach. The isolated world cannot count them (Element.prototype
    there is the Xray view), so the state carries null and the Python side
    renders the absence. A zero here would be the confident-zero failure the
    two-layer phrasing exists to prevent."""
    text = bundle.build()
    assert "closed: null," in text
    # NO PATCH, and the check is for the patching CODE rather than for the
    # word: the state's own comment explains why the patch is absent, and a
    # test that banned the word would ban the explanation with it.
    assert "Object.defineProperty(Element.prototype" not in text, (
        "the isolated world must not pretend to patch attachShadow: the "
        "patch would apply to the Xray view and count nothing.")


@pytest.mark.parametrize("name", ["extract", "find", "text"])
def test_every_bundled_script_is_the_playwright_lane_s_own_source(name):
    """The claim this whole file protects, stated as a test: the difference
    between the two copies is the instrument prelude and the hoist, and
    nothing else. A body that diverged would be a second reader."""
    source = (Path(projection.__file__).parent / f"{name}.js").read_text(
        encoding="utf-8")
    # Take a line from deep inside the body, past every splice mark.
    tail = [ln for ln in source.splitlines()
            if ln.strip() and not ln.strip().startswith("//")][-3]
    assert tail in bundle.build(), (
        f"{name}.js's own body is not in the bundle verbatim")
