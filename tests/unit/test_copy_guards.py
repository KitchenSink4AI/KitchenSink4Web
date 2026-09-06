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
PENDING_MAIN_THREAD_COPY = {
    # "an upload exfiltrates file content to the site as surely as a read
    # does" - states the behavior by naming the technique.
    ("tool:upload_file", "exfiltrat"),
    # "can read anything the page can, exfiltrate it, or act as the
    # logged-in user"
    ("tool:evaluate_script", "exfiltrat"),
    # "The dry run is the safe first move" - `safe` as an unqualified verb,
    # the same class as find_and_act's, which the main thread has already
    # ruled on once.
    ("tool:list_workflows", "safe"),
}


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


def test_published_numbers_match_the_measuring_snapshot():
    """Every figure the README and the page publish is in the snapshot the
    measuring script writes. A number that moved and was not re-published
    fails here rather than being spotted by a reader."""
    import json

    snap = ROOT / "tools" / "readme_numbers_snapshot.json"
    assert snap.exists(), "tools/readme_numbers_snapshot.json is missing"
    fill = json.loads(snap.read_text(encoding="utf-8"))["fill"]
    files = _published_files()
    readme = files.get("README.md", "")
    page = files.get("docs/index.html", "")
    for key in ("RAW_DUMP_TOKENS", "PROJECTION_TOKENS", "DELTA_TOKENS",
                "LITE_SURFACE_TOKENS", "FULL_SURFACE_TOKENS"):
        assert str(fill[key]) in readme, \
            f"README does not carry the measured {key} ({fill[key]})"
    for key in ("RAW_DUMP_TOKENS", "PROJECTION_TOKENS"):
        assert str(fill[key]) in page, \
            f"the page does not carry the measured {key} ({fill[key]})"
    assert str(fill["RUNG_COUNT"]) in readme

    # The test count is the one published figure that moves every time
    # somebody writes a test, so an exact match would turn "added a test"
    # into "broke the suite". The rule is the family's own: never overstate,
    # and do not go stale. An undercount is the honest direction, a claim of
    # more tests than exist is not, and a figure more than 5 percent behind
    # the suite is one nobody has looked at.
    published = _published_test_counts()
    measured = int(fill["TEST_COUNT"])
    for where, claimed in published.items():
        assert claimed <= measured, (
            f"{where} claims {claimed} tests and the suite collects "
            f"{measured}. Never publish more evidence than exists.")
        assert claimed >= measured * 0.95, (
            f"{where} claims {claimed} tests against a suite of {measured}. "
            f"Re-run tools/measure_readme_numbers.py and restamp.")


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
    figures ride inside translated sentences."""
    import json

    page = _published_files().get("docs/index.html", "")
    fill = json.loads((ROOT / "tools" / "readme_numbers_snapshot.json")
                      .read_text(encoding="utf-8"))["fill"]
    raw, projected = fill["RAW_DUMP_TOKENS"], fill["PROJECTION_TOKENS"]

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
