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


def test_no_trademark_or_affiliation_claim():
    """Nominative use only, no logos, no trade dress, and never an implied
    endorsement by a browser vendor."""
    for where, text in _public_strings().items():
        low = text.lower()
        for phrase in ("official", "endorsed by", "in partnership with",
                       "certified by"):
            assert phrase not in low, f"{where} implies affiliation: {phrase}"
