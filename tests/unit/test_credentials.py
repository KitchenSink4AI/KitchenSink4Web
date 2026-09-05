"""Credential blindness (DESIGN 5.3): classification, the vault, the
serializer redactor, masking, and strict mode.

The load-bearing test here is the LEAKY TOOL one: a payload that carries an
observed secret is scrubbed by the ENVELOPE, not by the tool that emitted
it, which is the architecture the Phase 3 gate proves end to end.
"""

from __future__ import annotations

import pytest

from kitchensink4web import envelope
from kitchensink4web.errors import CredentialRefused
from kitchensink4web.policy import credentials


@pytest.fixture(autouse=True)
def clean_vault():
    credentials.VAULT.clear()
    yield
    credentials.VAULT.clear()


# ------------------------------------------------------------ classification


def test_secret_field_classification_matches_the_extractor_rule():
    assert credentials.is_secret_field({"type": "password"})
    assert credentials.is_secret_field({"autocomplete": "current-password"})
    assert credentials.is_secret_field({"autocomplete": "new-password"})
    assert credentials.is_secret_field({"autocomplete": "one-time-code"})
    assert credentials.is_secret_field({"secret": True})
    assert not credentials.is_secret_field({"type": "email"})
    assert not credentials.is_secret_field({"autocomplete": "username"})
    assert not credentials.is_secret_field({})


def test_payment_classification():
    assert credentials.is_payment_field({"autocomplete": "cc-number"})
    assert credentials.is_payment_field({"autocomplete": "cc-exp"})
    assert not credentials.is_payment_field({"autocomplete": "email"})


def test_secret_write_refuses_and_names_both_sanctioned_routes():
    with pytest.raises(CredentialRefused) as exc:
        credentials.refuse_secret_write(
            {"type": "password", "name": "Password"}, "type_text")
    text = str(exc.value)
    assert "secrets file" in text
    assert "handoff" in text
    # A non-secret field passes silently.
    credentials.refuse_secret_write({"type": "text"}, "type_text")


# --------------------------------------------------------------- the vault


def test_vault_scrubs_observed_values_from_nested_payloads():
    credentials.VAULT.observe("KS4WEB-COOKIE-SECRET-9f3a1c77d2")
    payload = {
        "ok": True,
        "note": "the cookie is KS4WEB-COOKIE-SECRET-9f3a1c77d2 today",
        "rows": [{"v": "prefix KS4WEB-COOKIE-SECRET-9f3a1c77d2 suffix"}],
        "count": 3,
    }
    out = credentials.VAULT.scrub(payload)
    text = str(out)
    assert "KS4WEB-COOKIE-SECRET" not in text
    assert credentials.MASK in out["note"]
    assert out["count"] == 3  # non-strings ride through untouched


def test_vault_ignores_trivially_short_values():
    credentials.VAULT.observe("ab")
    assert credentials.VAULT.scrub("ab ab ab") == "ab ab ab"


def test_the_leaky_tool_is_caught_by_the_serializer_not_the_tool():
    """DESIGN 5.3 / the Phase 3 gate contract: redaction lives in the
    envelope, so a tool that tries to emit an observed credential is caught
    on the way out whether or not the tool has any discipline of its own."""
    credentials.VAULT.observe("hunter2-super-secret")
    envelope.set_redactor(credentials.redactor)
    try:
        leaked = envelope.success(
            {"leak": "value=hunter2-super-secret", "fine": "kept"})
        assert "hunter2-super-secret" not in str(leaked)
        assert leaked["fine"] == "kept"
        # The refusal path passes through the same seam.
        exc = ValueError("the cookie hunter2-super-secret leaked into an "
                         "error message")
        refusal = envelope.refusal(exc)
        assert "hunter2-super-secret" not in str(refusal)
    finally:
        envelope.set_redactor(credentials.redactor)


# ------------------------------------------------------- masking and strict


def test_mask_value_reveals_length_only():
    masked = credentials.mask_value("secret-value-123")
    assert "secret" not in masked.replace("chars", "")
    assert "16" in masked


def test_unmask_refused_under_strict_default(monkeypatch):
    monkeypatch.delenv(credentials.ENV_STRICT, raising=False)
    assert credentials.strict() is True  # strict IS the default
    with pytest.raises(CredentialRefused):
        credentials.check_unmask("cookie read")
    monkeypatch.setenv(credentials.ENV_STRICT, "open")
    assert credentials.strict() is False
    credentials.check_unmask("cookie read")  # permitted, still audited
