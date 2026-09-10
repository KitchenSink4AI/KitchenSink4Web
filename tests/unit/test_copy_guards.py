"""Copy guards: the standing rules that bind every word a user or a model
ever reads, checked mechanically instead of remembered.

This is the SKELETON. It covers what exists in Phase 0 (tool descriptions,
refusal hints, the server instructions string, and the packaging metadata)
and grows to cover README, the docs site, and llms.txt as those land in
Phase 9. The point of writing it now is that a rule enforced from commit one
never needs a cleanup pass.

The rules, from PLAN 8 and DESIGN 5:

- No em dashes anywhere public, in any language.
- Safety-copy grammar, absolute: reduces / gates / flags / logs / requires
  confirmation for. Never prevents, secure, safe, or protected as
  unqualified verbs.
- Never frame a feature by the attack it stops. "Our scanner catches
  white-on-white injection payloads" is a tutorial; "hidden regions are
  flagged" is the same fact with no recipe.
- No warranty or guarantee language, anywhere, in any beta framing.
- No license text, badge, or claim in any file until Q1 is ruled
  (DESIGN 10.3 rule 5). DISCHARGED 2026-09-06: Q1 was ruled, the license
  landed, and the guard inverted to check that it landed WHOLE.
"""

from __future__ import annotations

import asyncio
import functools
import re
from pathlib import Path

import pytest

from kitchensink4web import envelope, server

ROOT = Path(__file__).resolve().parents[2]

#: Unqualified safety verbs. Each is checked as a whole word so that a
#: qualified use ("reduces the risk that ... reaches") is not caught by a
#: substring, and so "safety" and "safely" do not trip the "safe" rule.
BANNED_SAFETY = (
    r"\bprevents?\b", r"\bsecure\b", r"\bsafe\b", r"\bprotected\b",
    r"\bguarantee[sd]?\b", r"\bwarrant(?:y|ies)\b", r"\bblocks? attacks?\b",
)

#: Attack-recipe framing. A feature described by the attack it stops.
BANNED_RECIPES = (
    r"white[- ]on[- ]white", r"injection payload", r"exfiltrat",
    r"\bmalicious\b", r"\battacker\b",
)

#: The one-read overclaim, banned since S1 (DESIGN 12 rule 2a). The claim
#: always carries its companion clause.
BANNED_OVERCLAIM = (
    r"one read and you can act on anything",
    r"everything you need in one read",
)


def _public_strings() -> dict[str, str]:
    """Every string a user or a model can see in Phase 0.

    THE GRADE IS RESTORED, and it is the same defect the `launch` fixture
    already carries in its own teardown one call site earlier. This helper
    runs OUTSIDE that fixture, and a bare `configure()` resolves the SHIPPED
    default grade, `browse`, so it left the whole process read-only for
    whatever ran next. Under a file order that puts this module last among
    the unit tests, two browser tests that assert the process is actable
    failed on nothing but their position in the run (found by re-attack 2's
    ordering check, 2026-09-06, and present on the baseline commit too).

    The CAPTURE runs under the shipped default, which is what a first
    session sees. The FULL surface is captured separately by
    `_every_tool_description` below and carries the same grammar rules, so
    the wave 5 gap is closed: `find_and_act`'s description used a word
    `BANNED_SAFETY` forbids and no run had ever read it, because a mutating
    tool is ABSENT under the default grade."""
    try:
        server.configure()
        tools = asyncio.run(server.mcp.list_tools())
        out = {f"tool:{t.name}": (t.description or "") for t in tools}
        out.update({f"hint:{c}": h for c, h in envelope.HINTS.items()})
        out["server:instructions"] = server.mcp.instructions or ""
        out["packaging:pyproject"] = (ROOT / "pyproject.toml").read_text(
            encoding="utf-8")
        return out
    finally:
        # A fresh process starts with no grade applied at all, so the honest
        # restore is the un-graded surface this helper found rather than the
        # launch default it configured.
        server.configure(read_only=False)


def _every_tool_description() -> dict[str, str]:
    """EVERY tool description in the product, not only the ones a default
    launch registers.

    The shipped default is `browse` with no packs, so the mutating tools and
    the seven packs are simply absent from `_public_strings`. Fix wave 5
    found what that costs: `find_and_act`'s description carried a banned
    word for its whole life and no guard had ever read the string, because
    the tool does not exist under the grade the guard ran at. The widest
    surface is the honest one to hold to the copy rules, since it is the
    surface a user who turns everything on actually reads."""
    try:
        server.configure(mode="full", read_only=False)
        tools = asyncio.run(server.mcp.list_tools())
        return {f"tool:{t.name}": (t.description or "") for t in tools}
    finally:
        server.configure(read_only=False)


def test_no_em_dashes_anywhere_public():
    for where, text in _public_strings().items():
        assert "—" not in text, f"em dash in {where}"


def test_no_em_dashes_in_any_tool_description():
    for where, text in _every_tool_description().items():
        assert "—" not in text, f"em dash in {where}"


def test_safety_copy_grammar():
    for where, text in _public_strings().items():
        if where.startswith("packaging:"):
            continue
        for pattern in BANNED_SAFETY:
            hit = re.search(pattern, text, re.IGNORECASE)
            assert not hit, (
                f"{where} uses banned safety copy {hit.group(0)!r}. The "
                f"grammar is reduces / gates / flags / logs / requires "
                f"confirmation for."
            )


#: Strings the widened guard found on its first run, on tools no earlier run
#: had ever read. Each one needs a REWRITE, and a rewrite of a tool
#: description is product copy the main thread writes, not something a guard
#: gets to paper over. So the list is explicit, it is named per tool and per
#: matched string, and `test_the_pending_copy_list_only_shrinks` fails the
#: moment one of these is fixed, which is what stops it becoming permanent.
#:
#: EMPTY as of fix wave 6. All three entries were rewritten by the main thread
#: and removed with their fixes: `upload_file` hands file content to the site,
#: `evaluate_script` can send what it reads anywhere, and the dry run is the
#: RIGHT first move rather than the safe one. The set stays because the two
#: guards above read it, and an empty one is the state they are meant to hold.
PENDING_MAIN_THREAD_COPY: set[tuple[str, str]] = set()


def test_safety_copy_grammar_covers_every_tool_description():
    """The wave 5 widening. Same rules, applied to the surface a user who
    loads every pack and allows acting is reading.

    Three strings were waiting there on the day this guard was widened, and
    they are listed above rather than fixed here. Everything else on the
    41-tool surface is held to the rules from this commit on."""
    surface = _every_tool_description()
    assert len(surface) > 30, (
        f"the full surface registered only {len(surface)} tools; this guard "
        f"is meant to read all of them")
    for where, text in surface.items():
        for pattern in BANNED_SAFETY + BANNED_RECIPES + BANNED_OVERCLAIM:
            hit = re.search(pattern, text, re.IGNORECASE)
            if not hit:
                continue
            if (where, hit.group(0).lower()) in PENDING_MAIN_THREAD_COPY:
                continue
            raise AssertionError(
                f"{where} uses banned copy {hit.group(0)!r}. The grammar is "
                f"reduces / gates / flags / logs / requires confirmation for."
            )


def test_the_pending_copy_list_only_shrinks():
    """A known-failures list that nobody prunes is a guard that was turned
    off. Every entry has to still be a real hit, so fixing one turns this
    red until the entry goes with it."""
    surface = _every_tool_description()
    stale = [
        entry for entry in sorted(PENDING_MAIN_THREAD_COPY)
        if not re.search(re.escape(entry[1]), surface.get(entry[0], ""),
                         re.IGNORECASE)
    ]
    assert not stale, (
        f"these entries are fixed or gone and must be deleted from "
        f"PENDING_MAIN_THREAD_COPY: {stale}")


def test_no_feature_is_framed_by_the_attack_it_stops():
    for where, text in _public_strings().items():
        if where.startswith("packaging:"):
            continue
        for pattern in BANNED_RECIPES:
            hit = re.search(pattern, text, re.IGNORECASE)
            assert not hit, (
                f"{where} names an attack technique ({hit.group(0)!r}). "
                f"State the behavior, not the recipe."
            )


def test_the_one_read_claim_is_never_overclaimed():
    """S1's positioning correction, enforced rather than remembered."""
    for where, text in _public_strings().items():
        for pattern in BANNED_OVERCLAIM:
            assert not re.search(pattern, text, re.IGNORECASE), \
                f"{where} overclaims the single read"


def test_the_license_landed_whole():
    """DESIGN 10.3 rule 5 held every license claim out of every file until
    the decision landed, and named the LICENSE file a Phase 9 artifact. Q1
    was ruled 2026-09-06 (the family AGPL), so the guard inverts: what used
    to be checked as absent is now checked as COMPLETE.

    Whole means all four pieces agree. A repository that claims AGPL in its
    README and ships a wheel with no license metadata has made the decision
    twice and landed it once, which is the failure this replaces."""
    license_file = ROOT / "LICENSE"
    notice = ROOT / "NOTICE.md"
    assert license_file.exists(), "the AGPL claim has no LICENSE file"
    assert notice.exists(), "the AGPL claim has no NOTICE.md"

    # The stock AGPL text, not a summary of it, and the same file the
    # siblings ship. Two structural markers rather than a digest, so a
    # line-ending normalization does not read as a licence change.
    text = license_file.read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 19 November 2007" in text
    assert "TERMS AND CONDITIONS" in text
    assert len(text.splitlines()) > 600, \
        "LICENSE is too short to be the AGPL text"

    # NOTICE.md is the retargeted half, and retargeted means retargeted.
    note = notice.read_text(encoding="utf-8")
    assert "KitchenSink4Web" in note
    assert "AGPL-3.0" in note
    for sibling in ("KitchenSink4XL", "KitchenSink4Word", "KitchenSink4PPT"):
        assert sibling not in note, \
            f"NOTICE.md still names {sibling}: it was copied, not retargeted"

    # And the package metadata says the same thing as the prose.
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "AGPL-3.0-only"' in pyproject
    assert 'license-files = ["LICENSE", "NOTICE.md"]' in pyproject


def test_every_published_surface_agrees_on_the_license():
    """One licence, stated the same way everywhere a reader meets it."""
    for where, text in _published_files().items():
        if where == "docs/llms.txt":
            continue          # the agent-facing file states no licence
        assert "AGPL-3.0" in text, f"{where} does not name the licence"


def _projection_strings() -> dict[str, str]:
    """The projection payload, which is the most-read public text in the
    product by a wide margin.

    Phase 1 extends the guards to cover it. A tool description is read once
    per session; a page view is read on every page, and the completeness
    block is where a careless sentence about hidden content would turn a
    stated behavior into a stated technique."""
    import json
    from pathlib import Path as _Path

    from kitchensink4web.projection import project

    data_dir = ROOT / "tests" / "data"
    meta = {"status": 200, "load_state": "load", "lane": "A(chromium)",
            "page": "p1", "read_token": "rt1", "ts": "2026-09-05T00:00:00"}
    out = {}
    for path in sorted(_Path(data_dir).glob("extract_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[f"projection:{path.stem}"] = project(data, meta,
                                                 budget=5000).text
    return out


def test_the_projection_payload_obeys_every_copy_rule():
    for where, text in _projection_strings().items():
        assert "—" not in text, f"em dash in {where}"
        for pattern in BANNED_SAFETY + BANNED_RECIPES + BANNED_OVERCLAIM:
            hit = re.search(pattern, text, re.IGNORECASE)
            assert not hit, (
                f"{where} carries banned copy {hit.group(0)!r}. The "
                f"projection is read on every page, so a careless sentence "
                f"there is the most-repeated sentence in the product.")


def test_no_trademark_or_affiliation_claim():
    """Nominative use only, no logos, no trade dress, and never an implied
    endorsement by a browser vendor."""
    for where, text in _public_strings().items():
        low = text.lower()
        for phrase in ("official", "endorsed by", "in partnership with",
                       "certified by"):
            assert phrase not in low, f"{where} implies affiliation: {phrase}"


# ---------------------------------------------------------------------------
# Phase 9: the published surfaces. The skeleton's own docstring says these
# arrive here when they land, and this is when they landed.
#
# SCOPE, stated so the gap is deliberate rather than forgotten. What is
# checked here is MECHANICAL: em dashes in any of the seven languages, the
# non-affiliation line, and the one-read overclaim. What is NOT checked here
# is the safety-verb and attack-recipe grammar, because the author's approved
# copy for these surfaces names "credential exfiltration attempts" as one item
# in a list of what the gate batteries cover, and a guard that fails on
# author-approved copy would be resolved by weakening the guard. That
# conflict belongs to the main thread, not to a test file.
# ---------------------------------------------------------------------------

#: Every file a reader or a crawler sees. The docs pages carry seven
#: languages in one file, so reading the bytes checks all seven at once.
PUBLISHED = ("README.md", "docs/index.html", "docs/llms.txt")

#: The line the xl ship proved a guard has to hold: a trademark page without
#: it reads as an endorsement it never had.
AFFILIATION_LINE = "Not affiliated with or endorsed by"


def _published_files() -> dict[str, str]:
    out = {}
    for rel in PUBLISHED:
        path = ROOT / rel
        if path.exists():
            out[rel] = path.read_text(encoding="utf-8")
    return out


def test_every_published_surface_exists():
    """A missing page is a silent pass for every guard below it."""
    missing = [rel for rel in PUBLISHED if not (ROOT / rel).exists()]
    assert not missing, f"published surfaces missing: {missing}"


def test_no_em_dashes_on_any_published_surface():
    """In any language. The page ships seven dictionaries in one file, so a
    translation that reached for an em dash is caught here too."""
    for where, text in _published_files().items():
        assert "—" not in text, f"em dash in {where}"


def test_the_page_carries_its_non_affiliation_line():
    """In all seven languages, since a reader who switched language is the
    reader most likely to be looking at the footer."""
    page = _published_files().get("docs/index.html", "")
    assert page, "docs/index.html is missing"
    assert page.count('data-i18n="f.affil"') >= 1, \
        "the page has no non-affiliation line"
    affil = re.findall(r'"f\.affil": "(.*?)"(?:,|\n)', page)
    assert len(affil) == 7, (
        f"the non-affiliation line is translated {len(affil)} times, "
        f"expected 7 (one per language)")
    for text in affil:
        assert "Google" in text and "Mozilla" in text and "Microsoft" in text


def test_the_mcp_name_marker_is_readme_line_one():
    """The registry validates the PyPI package against this marker, and it
    has to be there BEFORE the first release. PLAN W4 names it so the KS4PPT
    v1.0.1 lesson does not get relearned."""
    first = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert first == (
        "<!-- mcp-name: io.github.nometalalchemist/kitchensink4web -->"
    ), "README line 1 mcp-name marker was lost"


def test_the_server_json_description_fits_the_registry_cap():
    """The registry caps the description at 100 characters. XL's Phase A
    found a 127-character one and called it a likely hard publish failure,
    which is the check this repo gets to have in advance."""
    import json

    server_json = json.loads(
        (ROOT / "server.json").read_text(encoding="utf-8"))
    description = server_json["description"]
    assert len(description) < 100, (
        f"server.json description is {len(description)} characters and the "
        f"registry cap is 100")
    assert "—" not in description
    assert server_json["name"] == "io.github.nometalalchemist/kitchensink4web"


def test_version_is_consistent_across_manifests():
    """One version, six fields: pyproject, the package, server.json twice,
    and both bundle manifests with their own uvx pins. XL had this guard and
    it caught real drift; this one also covers the dev manifest, which is a
    file the siblings do not have."""
    import json
    import sys
    import tomllib

    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    server_json = json.loads(
        (ROOT / "server.json").read_text(encoding="utf-8"))
    assert server_json["version"] == version, "server.json version drifted"
    assert server_json["packages"][0]["version"] == version, \
        "server.json's PyPI package version drifted"

    for rel in ("manifest.json", "dev/manifest.json"):
        manifest = json.loads(
            (ROOT / "bundle" / rel).read_text(encoding="utf-8"))
        assert manifest["version"] == version, rel
        assert manifest["server"]["mcp_config"]["args"] == [
            f"kitchensink4web=={version}"
        ], f"{rel}'s uvx pin does not match the package version"

    # EIGHT fields since 1.0.1: `figures.json` ships inside the wheel and
    # names the version it was measured at, so a bump that forgets to
    # re-measure is caught here rather than by a user reading a figure from
    # the release before this one.
    shipped_figures = json.loads(
        (ROOT / "src" / "kitchensink4web" / "figures.json").read_text(
            encoding="utf-8"))
    assert shipped_figures["version"] == version, (
        f"figures.json was measured at {shipped_figures['version']} and "
        f"pyproject says {version}. Re-run "
        f"tools/measure_readme_numbers.py --tests-only.")

    sys.path.insert(0, str(ROOT / "src"))
    import kitchensink4web
    if kitchensink4web.__version__ == "0.0.0":
        pytest.skip(
            "package version not stamped yet; stamping "
            "src/kitchensink4web/__init__.py at ship turns this guard on"
        )
    assert kitchensink4web.__version__ == version, (
        f"src/kitchensink4web/__init__.py says "
        f"{kitchensink4web.__version__}, pyproject says {version}")

    # SEVEN fields, since 2026-09-08. The six above are files, and files
    # were all this guard checked while the running server introduced itself
    # to every client as 3.4.7: FastMCP answers `initialize` with its own
    # version when the constructor is not given one.
    assert server.mcp.version == version, (
        f"the server reports version {server.mcp.version} over the wire and "
        f"pyproject says {version}")


def test_no_beta_language_in_public_copy():
    """KS4Web ships as a full 1.0 born-right (author ruling, the XL
    pattern). No beta labels anywhere a reader meets the product."""
    for where, text in _published_files().items():
        assert not re.search(r"\bbeta\b", text, re.IGNORECASE), \
            f"{where} still carries a beta label"


def test_the_readme_carries_its_non_affiliation_line():
    readme = _published_files().get("README.md", "")
    assert AFFILIATION_LINE in readme, \
        "README has no non-affiliation line"


def test_no_published_surface_overclaims_the_single_read():
    for where, text in _published_files().items():
        for pattern in BANNED_OVERCLAIM:
            assert not re.search(pattern, text, re.IGNORECASE), \
                f"{where} overclaims the single read"


# --------------------------------------- the published figures, against LIVE
#
# The guard that used to stand here compared the published prose to
# `tools/readme_numbers_snapshot.json`, a file written by the same script that
# stamps the prose. Both sides of that comparison move together, so a figure
# that went stale in the product went stale in the snapshot at the same
# moment and the guard agreed with it. V-21 already found one instance of
# exactly that (the tool counts) and fixed it by asking the live process; the
# rest of the figures are asked live here, for the same reason.
#
# What can be measured without a browser is measured in this file. The page
# reads (the dump figure, the first-read projection, the delta) need a real
# page and live in `tests/browser/test_published_numbers_live.py`.


@functools.lru_cache(maxsize=1)
def _live_test_count() -> dict[str, int]:
    """pytest's own collection of both suites, run right now.

    `--collect-only` imports the test modules and stops, so this cannot
    recurse into itself, and it costs one import pass per directory."""
    import subprocess
    import sys

    counts = {}
    for name in ("unit", "browser"):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "pytest", f"tests/{name}",
             "--collect-only", "-q", "-p", "no:cacheprovider"],
            cwd=str(ROOT), capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        match = re.search(r"(\d+) tests? collected", proc.stdout)
        assert match, (
            f"collecting tests/{name} produced no count "
            f"(exit {proc.returncode}): {proc.stdout[-800:]}")
        assert proc.returncode == 0, (
            f"collecting tests/{name} exited {proc.returncode}: "
            f"{proc.stdout[-800:]}")
        counts[name] = int(match.group(1))
    counts["total"] = counts["unit"] + counts["browser"]
    return counts


@pytest.mark.needs_captures("corpus", "walls")
def test_the_published_test_count_matches_a_live_collection():
    """The suite count as the surfaces state it, against what pytest
    collects in this working tree at this moment.

    Checked only where the captures are, and the reason is arithmetic
    rather than caution: the fixtures that parametrize over a capture set
    collapse to a single empty-parameter placeholder when the captures are
    absent, so a clone without them collects a smaller suite than the one
    the published figure describes. Measuring the claim there would fail
    the claim for being true.

    The test count is the one published figure that moves every time
    somebody writes a test, so an exact match would turn "added a test"
    into "broke the suite". The rule is the family's own: never overstate,
    and do not go stale. An undercount is the honest direction, a claim of
    more tests than exist is not, and a figure more than 5 percent behind
    the suite is one nobody has looked at."""
    live = _live_test_count()
    measured = live["total"]
    for where, claimed in _published_test_counts().items():
        assert claimed <= measured, (
            f"{where} claims {claimed} tests and a live collection finds "
            f"{measured}. Never publish more evidence than exists.")
        assert claimed >= measured * 0.95, (
            f"{where} claims {claimed} tests against a live collection of "
            f"{measured}. Re-run tools/measure_readme_numbers.py and "
            f"restamp.")

    # The browser figure rides in the same sentence as the total on every
    # surface, and it is the harder half of the claim: "drives a real
    # browser" is the part a reader is entitled to check.
    for where, claimed in _published_browser_counts().items():
        assert claimed <= live["browser"], (
            f"{where} claims {claimed} browser tests and a live collection "
            f"finds {live['browser']}. Never publish more evidence than "
            f"exists.")
        assert claimed >= live["browser"] * 0.95, (
            f"{where} claims {claimed} browser tests against a live "
            f"collection of {live['browser']}. Re-run "
            f"tools/measure_readme_numbers.py and restamp.")


@pytest.mark.needs_captures("corpus", "walls")
def test_the_shipped_figure_file_matches_a_live_collection():
    """`src/kitchensink4web/figures.json` is a published surface with no page
    to read it off: it ships inside the wheel and `get_server_info` reads it
    out to whatever agent asks what it is talking to.

    Same rule and the same reason as the prose above. Never publish more
    evidence than exists, do not go stale, and check it only where the
    captures are, because a clone without them collects a smaller suite than
    the figure describes."""
    import json

    shipped = json.loads(
        (ROOT / "src" / "kitchensink4web" / "figures.json").read_text(
            encoding="utf-8"))
    live = _live_test_count()
    for key in ("unit", "browser", "total"):
        claimed = shipped["tests"][key]
        assert claimed <= live[key], (
            f"figures.json claims {claimed} {key} tests and a live "
            f"collection finds {live[key]}. Never publish more evidence "
            f"than exists.")
        assert claimed >= live[key] * 0.95, (
            f"figures.json claims {claimed} {key} tests against a live "
            f"collection of {live[key]}. Re-run "
            f"tools/measure_readme_numbers.py --tests-only.")
    assert shipped["tests"]["unit"] + shipped["tests"]["browser"] == \
        shipped["tests"]["total"], "figures.json does not add up"


def test_the_published_surface_and_ladder_figures_match_this_build():
    """The two surface token figures and the rung count, measured off the
    live registry and the live ladder rather than read out of a file."""
    from kitchensink4web import packs, projection

    def _surface_tokens(**kw) -> str:
        server.configure(**kw)
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        total = sum(packs.approx_tokens(t) for t in tools.values())
        return f"{total / 1000:.1f}k"

    try:
        lite = _surface_tokens(read_only=False)
        full = _surface_tokens(mode="full", read_only=False)
    finally:
        server.configure(read_only=False)

    readme = _published_files().get("README.md", "")
    assert lite in readme, (
        f"README does not carry the measured lite surface figure ({lite})")
    assert full in readme, (
        f"README does not carry the measured full surface figure ({full})")
    assert str(len(projection.RUNGS)) in readme, (
        f"README does not carry the measured rung count "
        f"({len(projection.RUNGS)})")


def _published_browser_counts() -> dict[str, int]:
    """The browser-test figure as each surface states it."""
    files = _published_files()
    out = {}
    patterns = {
        "README.md": r"tests, of which (\d[\d,]*) drive a real browser",
        "docs/llms.txt": r"tests, (\d[\d,]*) of which drive a real browser",
        "docs/index.html": r"tests, (\d[\d,]*) of them driving a real browser",
    }
    for where, pattern in patterns.items():
        match = re.search(pattern, files.get(where, ""))
        assert match, f"{where} does not state a browser-test count"
        out[where] = int(match.group(1).replace(",", ""))
    return out


def _published_test_counts() -> dict[str, int]:
    """The test figure as each surface states it, read out of the prose."""
    files = _published_files()
    out = {}
    patterns = {
        "README.md": r"(\d[\d,]*) tests, of which",
        "docs/llms.txt": r"(\d[\d,]*) tests, \d+ of which",
        "docs/index.html": r'<span class="n">(\d[\d,]*)</span>'
                           r'<span class="l" data-i18n="spec\.tests">',
    }
    for where, pattern in patterns.items():
        match = re.search(pattern, files.get(where, ""))
        assert match, f"{where} does not state a test count where expected"
        out[where] = int(match.group(1).replace(",", ""))
    return out


def test_no_unfilled_copy_markers_remain_on_any_surface():
    """The build renders missing copy as a visible marker rather than
    guessing at it, which only works if a marker cannot reach a reader."""
    for where, text in _published_files().items():
        assert "MISSING COPY" not in text, f"{where} still has an unfilled cell"
        assert 'class="todo"' not in text, f"{where} still has a TODO marker"


def test_the_comparison_table_and_the_demo_quote_the_same_numbers():
    """DEPT. 02's first row cites the two figures DEPT. 00 demonstrates. Two
    numbers for one measurement, on one page, is the failure that a reader
    catches before any of us does. Checked in every language, since the
    figures ride inside translated sentences.

    The two figures are read off the page's own demo tiles rather than out
    of a file beside them. The tiles are what the browser guard measures
    against a real read, so the chain here runs measurement -> tile -> every
    locale, with no link that can go stale on its own."""
    page = _published_files().get("docs/index.html", "")
    raw_tile = re.search(r'<span class="fig">([\d,]+)</span>', page)
    map_tile = re.search(r'<span class="fig" id="mapFig">([\d,]+)</span>',
                         page)
    assert raw_tile and map_tile, \
        "the demo tiles no longer state the two figures"
    raw, projected = raw_tile.group(1), map_tile.group(1)

    # Digit groups are punctuated per locale (33,073 / 33.073 / 33 073), so
    # the check is on the digits, not on the rendered separator.
    def spellings(figure: str) -> tuple[str, ...]:
        bare = figure.replace(",", "")
        return (figure, bare, f"{bare[:2]}.{bare[2:]}", f"{bare[:2]} {bare[2:]}",
                f"{bare[:1]}.{bare[1:]}", f"{bare[:1]} {bare[1:]}")

    for lang in ("en", "ko", "ja", "zh", "de", "fr", "es"):
        start = page.index(f"\n{lang}: {{\n")
        end = page.index("\n}", start)
        block = page[start:end]
        cell = re.search(r'^"cr1\.oth": "(.*?)",?$', block, re.M)
        ours = re.search(r'^"cr1\.us": "(.*?)",?$', block, re.M)
        assert cell and ours, f"{lang} is missing the first comparison row"
        assert any(s in cell.group(1) for s in spellings(raw)), (
            f"{lang} row 1 does not quote the measured dump figure {raw}")
        assert any(s in ours.group(1) for s in spellings(projected)), (
            f"{lang} row 1 does not quote the measured read figure "
            f"{projected}")


def test_the_survey_the_small_print_points_at_is_in_the_repository():
    """The comparison footnote says the sources are in the repository, so
    they have to be in the repository."""
    survey = ROOT / "research" / "20260906_browser_mcp_survey.md"
    assert survey.exists(), \
        "the comparison small print promises sources this repo does not carry"
    text = survey.read_text(encoding="utf-8")
    assert text.count("https://github.com/") >= 8, \
        "the survey carries no source list"


# ------------------------------------- the surface counts, against the SURFACE
#
# V-21, verify round 2026-09-08. `llms.txt` said 45 tools against a surface of
# 52, and README.md, `llms.txt` (twice) and `docs/index.html` all said the
# session starts on 16 when the lite roster is 19. The lite number is the
# first figure a prospective user reads and it is on the front page.
#
# The reason it went stale quietly is structural and it is the part worth
# fixing: `test_published_numbers_match_the_measuring_snapshot` above checks
# the published prose against `readme_numbers_snapshot.json`, so when the
# SNAPSHOT went stale too the guard agreed with it. Tool counts were not in
# its guarded key list at all. These two ask the live process instead, which
# is free: registering the surface needs no browser and no page read.


def _live_surface_counts() -> dict[str, int]:
    """{lite_acting, lite_shipped_default, full_acting} as this build
    actually registers them, right now, in this process."""
    import os

    from kitchensink4web import server

    saved = {k: v for k, v in os.environ.items() if k.startswith("KS4WEB_")}
    try:
        for key in list(saved):
            del os.environ[key]
        out = {
            "lite_acting": len(server.configure(read_only=False)["registered"]),
            "lite_shipped_default": len(server.configure()["registered"]),
        }
        os.environ["KS4WEB_ALL_PACKS"] = "true"
        out["full_acting"] = len(
            server.configure(read_only=False)["registered"])
        return out
    finally:
        for key in [k for k in os.environ if k.startswith("KS4WEB_")]:
            del os.environ[key]
        os.environ.update(saved)
        server.configure(read_only=False)


def test_every_published_tool_count_matches_the_live_surface():
    """The lite roster and the full surface, as the product states them on
    every surface a reader meets, against what the server registers."""
    live = _live_surface_counts()
    files = _published_files()
    claims = {
        "README.md": [(r"session management, (\d+) tools", "lite_acting")],
        "docs/llms.txt": [
            (r"ships on\. (\d+) tools at session", "lite_acting"),
            (r"start, (\d+) with every capability pack loaded", "full_acting"),
            (r"loads the lite pack: (\d+) tools", "lite_acting"),
            (r"default (\d+) of those \d+ are absent", None),
            (r"about [\d,]+ tokens for (\d+) tools", "lite_shipped_default"),
            (r"Everything loaded: (\d+) tools", "full_acting"),
        ],
        "docs/index.html": [
            (r"(\d+)\s+lite tools / ", "lite_acting"),
            (r"tokens;\s+(\d+) full / ", "full_acting"),
        ],
    }
    for where, rows in claims.items():
        text = files.get(where, "")
        for pattern, key in rows:
            found = re.search(pattern, text)
            assert found, f"{where} no longer states a count matching {pattern}"
            claimed = int(found.group(1))
            if key is None:
                # "N of those M are absent" is the arithmetic between the two.
                assert claimed == (live["lite_acting"]
                                   - live["lite_shipped_default"]), (
                    f"{where} says {claimed} lite tools are absent under the "
                    f"shipped default; the surface says "
                    f"{live['lite_acting'] - live['lite_shipped_default']}.")
                continue
            assert claimed == live[key], (
                f"{where} publishes {claimed} for {key} and the live surface "
                f"registers {live[key]}. Re-run scripts/measure_surface.py "
                f"and restamp.")


def test_the_measuring_snapshot_is_not_itself_stale_about_the_surface():
    """The guard above this section trusts the snapshot. So the snapshot has
    to be checked against something that cannot go stale, or a number that
    moved is agreed with twice instead of caught once."""
    import json

    snap = json.loads(
        (ROOT / "tools" / "readme_numbers_snapshot.json").read_text(
            encoding="utf-8"))
    live = _live_surface_counts()
    for key, row in snap["detail"]["surface"].items():
        assert row["tools"] == live[key], (
            f"the snapshot records {row['tools']} tools for {key} and the "
            f"live surface registers {live[key]}. Re-run "
            f"tools/measure_readme_numbers.py and restamp.")
    assert snap["fill"]["LITE_TOOL_COUNT"] == live["lite_acting"]
