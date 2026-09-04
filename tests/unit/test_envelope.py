"""The typed error envelope: the closed vocabulary, the code map, the
refusal shape, and the redaction seam.

These are the Phase 0 gate's "ported machinery's own tests" for the envelope
half. The vocabulary tests are the load-bearing ones: a code that exists in
the design and not in the code, or the reverse, is how a refusal ends up
uncatchable by a caller who read the docs.
"""

from __future__ import annotations

import pytest

from kitchensink4web import envelope, errors

# DESIGN 8.3, transcribed. This list is deliberately a literal rather than a
# derivation, so a code silently added to envelope.py fails here instead of
# agreeing with itself.
DESIGN_CODES = {
    "AMBIGUOUS_LOCATION", "NOT_FOUND", "RANGE_OUT_OF_BOUNDS", "STALE_ANCHOR",
    "UNSUPPORTED_CONTENT", "VALIDATION_FAILED", "CONFLICT", "BAD_PARAMS",
    "TARGET_CHANGED", "NAVIGATION_BLOCKED", "BLOCKED_BY_SITE",
    "AUTH_REQUIRED", "CREDENTIAL_REFUSED", "BUDGET_EXHAUSTED",
    "LOOP_DETECTED", "CONFIRMATION_REQUIRED", "READ_ONLY_MODE",
    "LANE_UNSUPPORTED", "MODAL_BLOCKED", "TIMEOUT",
}


def test_closed_vocabulary_matches_the_design():
    assert envelope.CLOSED_CODES == DESIGN_CODES


def test_scaffold_codes_are_disjoint_from_the_shipped_vocabulary():
    """NOT_IMPLEMENTED is a build-phase code and must never join the closed
    set by accident. Phase 9's gate asserts SCAFFOLD_CODES is empty."""
    assert envelope.SCAFFOLD_CODES & envelope.CLOSED_CODES == frozenset()
    assert "NOT_IMPLEMENTED" in envelope.SCAFFOLD_CODES


def test_every_code_names_a_recovery():
    """A refusal with no hint dead-ends the caller, which is the failure the
    vocabulary exists to prevent. HINTS must be TOTAL over every code."""
    missing = sorted(c for c in envelope.ALL_CODES
                     if not envelope.HINTS.get(c, "").strip())
    assert not missing, f"codes with no recovery hint: {missing}"


def test_no_hint_promises_more_than_it_can():
    """Safety-copy grammar (DESIGN 5, absolute): reduces / gates / flags /
    logs / requires confirmation for. Never 'prevents', 'secure', 'safe', or
    'protected' as unqualified verbs, anywhere a user reads them."""
    banned = ("prevents", "guarantee", "guarantees", "is secure",
              "keeps you safe", "fully protected")
    for code, hint in envelope.HINTS.items():
        low = hint.lower()
        for word in banned:
            assert word not in low, f"{code} hint uses banned copy: {word!r}"


def test_no_em_dashes_in_hints():
    for code, hint in envelope.HINTS.items():
        assert "—" not in hint, f"{code} hint has an em dash"


@pytest.mark.parametrize("exc,code", [
    (errors.AmbiguousLocation("x"), "AMBIGUOUS_LOCATION"),
    (errors.StaleAnchor("x"), "STALE_ANCHOR"),
    (errors.TargetChanged("x"), "TARGET_CHANGED"),
    (errors.TargetNotFound("x"), "NOT_FOUND"),
    (errors.BlockedBySite("x"), "BLOCKED_BY_SITE"),
    (errors.CredentialRefused("x"), "CREDENTIAL_REFUSED"),
    (errors.BudgetExhausted("x"), "BUDGET_EXHAUSTED"),
    (errors.LoopDetected("x"), "LOOP_DETECTED"),
    (errors.ReadOnlyMode("x"), "READ_ONLY_MODE"),
    (errors.LaneUnsupported("x"), "LANE_UNSUPPORTED"),
    (errors.ModalBlocked("x"), "MODAL_BLOCKED"),
    (errors.Timeout("x"), "TIMEOUT"),
    (errors.NotImplementedYet("x"), "NOT_IMPLEMENTED"),
    (errors.BadParams("x"), "BAD_PARAMS"),
    (ValueError("x"), "BAD_PARAMS"),
    (TimeoutError("x"), "TIMEOUT"),
    (KeyError("x"), "BAD_PARAMS"),
])
def test_code_map_classifies(exc, code):
    assert envelope.classify(exc) == code


def test_every_error_class_is_mapped():
    """A typed exception with no map entry falls through to BAD_PARAMS,
    which would silently mislabel a real failure class."""
    classes = [
        v for v in vars(errors).values()
        if isinstance(v, type) and issubclass(v, errors.WebMcpError)
        and v is not errors.WebMcpError
    ]
    mapped = {t for t, _ in envelope.CODE_MAP}
    unmapped = sorted(c.__name__ for c in classes if c not in mapped)
    assert not unmapped, f"unmapped error classes: {unmapped}"


def test_refusal_shape_and_iserror():
    r = envelope.refuse(errors.BlockedBySite("cloudflare interstitial"))
    assert r.is_error is True
    assert r["ok"] is False
    assert r["error"]["code"] == "BLOCKED_BY_SITE"
    assert r["error"]["message"] == "cloudflare interstitial"
    assert r["error"]["hint"]


def test_refusal_carries_candidates_when_ambiguous():
    """House rule: no tool ever acts on first match, and the refusal carries
    every candidate so the caller can disambiguate in one turn."""
    exc = errors.AmbiguousLocation("two buttons named Search")
    exc.matches = [{"ref": "e13", "region": "r4"},
                   {"ref": "e42", "region": "r4", "nth": 2}]
    r = envelope.refusal(exc)
    assert r["error"]["matches"] == exc.matches


def test_no_raw_exception_string_escapes():
    """Every catchable exception produces the envelope shape, never a
    traceback or a bare repr."""
    for exc in (ValueError("bad"), KeyError(0), IndexError("x"),
                RecursionError("deep"), FileNotFoundError("nope")):
        payload = envelope.refusal(exc)
        assert payload["ok"] is False
        assert payload["error"]["code"] in envelope.ALL_CODES
        assert isinstance(payload["error"]["message"], str)


def test_bare_lookup_error_gets_a_real_message():
    payload = envelope.refusal(KeyError(0))
    assert "wrong shape" in payload["error"]["message"]


def test_redaction_seam_applies_to_refusals_and_successes():
    """DESIGN 5.3: redaction lives at the serializer, so it must reach every
    outgoing payload, not just successes. Phase 0 ships the seam and no
    redactor; this installs one to prove the seam is real."""
    seen = []

    def redactor(payload):
        seen.append(payload)
        if isinstance(payload, dict) and "cookie" in payload:
            payload = {**payload, "cookie": "<redacted>"}
        return payload

    envelope.set_redactor(redactor)
    try:
        ok = envelope.success({"cookie": "session=abc123"})
        bad = envelope.refusal(errors.BadParams("nope"))
        assert ok["cookie"] == "<redacted>"
        assert bad["ok"] is False
        assert len(seen) == 2
    finally:
        envelope.set_redactor(None)

    assert envelope.success({"cookie": "raw"})["cookie"] == "raw"


def test_success_shape_is_lane_canonical():
    """DESIGN 8.1: Lane A is canonical and other lanes ADD keys, so ok is
    always present and always first-class."""
    out = envelope.success({"page": "p1", "lane": "A"})
    assert out["ok"] is True
    assert out["page"] == "p1"
