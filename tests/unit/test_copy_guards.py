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
  (DESIGN 10.3 rule 5). The LICENSE file is a Phase 9 artifact.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

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
    """Every string a user or a model can see in Phase 0."""
    server.configure()
    tools = asyncio.run(server.mcp.list_tools())
    out = {f"tool:{t.name}": (t.description or "") for t in tools}
    out.update({f"hint:{c}": h for c, h in envelope.HINTS.items()})
    out["server:instructions"] = server.mcp.instructions or ""
    out["packaging:pyproject"] = (ROOT / "pyproject.toml").read_text(
        encoding="utf-8")
    return out


def test_no_em_dashes_anywhere_public():
    for where, text in _public_strings().items():
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


def test_no_license_claim_exists_yet():
    """DESIGN 10.3 rule 5: no license text, badge, or claim in any file
    until Q1 is ruled. The LICENSE file is a Phase 9 artifact, and a
    placeholder now is how a deferred decision becomes an accidental one."""
    assert not (ROOT / "LICENSE").exists()
    assert not (ROOT / "LICENSE.txt").exists()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in pyproject.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("license"), \
            f"pyproject declares a license before Q1 is ruled: {stripped!r}"


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
    assert str(fill["TEST_COUNT"]) in readme and str(fill["TEST_COUNT"]) in page
    assert str(fill["RUNG_COUNT"]) in readme
