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


def test_secret_write_refuses_and_names_only_routes_that_exist():
    """Field test 2026-09-05: the old message promised a server-side secrets
    file no mechanism backs. The refusal now names the routes that exist
    (headed handoff, then auth-state reuse) and the phantom route is a PLAN
    future item, not an error-string promise."""
    with pytest.raises(CredentialRefused) as exc:
        credentials.refuse_secret_write(
            {"type": "password", "name": "Password"}, "type_text")
    text = str(exc.value)
    assert "handoff" in text
    assert "save_auth_state" in text
    assert "secrets file" not in text
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
    # The floor moved to 8 after the field test: "light" is a preference
    # value, not a secret, and vaulting it shredded ordinary prose.
    credentials.VAULT.observe("light")
    assert credentials.VAULT.scrub("light and dark") == "light and dark"


# ------------------------------------------------- calibration (field test)


def test_short_values_match_on_token_boundaries_not_inside_words():
    """The 2026-09-05 field test: a vaulted five-character preference value
    turned "highlights" into "high[REDACTED:secret]s" for a whole session.
    Short values are now redacted only where they stand alone."""
    credentials.VAULT.observe("darkmode")  # 8 chars, under the substring floor
    out = credentials.VAULT.scrub(
        "darkmode is on; the darkmodeswitch and the xdarkmode flag are not")
    assert "darkmodeswitch" in out
    assert "xdarkmode" in out
    assert out.startswith(credentials.MASK)


def test_long_values_still_match_as_raw_substrings():
    """A real credential rides inside a sentence at least as often as it
    rides alone, so nothing changes at credential length."""
    secret = "KS4WEB-COOKIE-SECRET-9f3a1c77d2"
    assert len(secret) >= credentials.SUBSTRING_MIN_LENGTH
    credentials.VAULT.observe(secret)
    out = credentials.VAULT.scrub(f"prefix{secret}suffix")
    assert secret not in out
    assert credentials.MASK in out


def test_cookie_classification_vaults_credentials_and_passes_preferences():
    assert credentials.cookie_is_credential(
        {"name": "_gh_sess", "httpOnly": True, "value": "x" * 40})
    assert credentials.cookie_is_credential(
        {"name": "csrf_token", "httpOnly": False, "value": "x" * 40})
    assert credentials.cookie_is_credential(
        {"name": "user_session", "httpOnly": False, "value": "x" * 40})
    # Preferences and identity are not credentials. dotcom_user is the case
    # that redacted a username out of every GitHub URL in the field test.
    assert not credentials.cookie_is_credential(
        {"name": "preferred_color_mode", "value": "light"})
    assert not credentials.cookie_is_credential(
        {"name": "tz", "value": "Asia/Seoul"})
    assert not credentials.cookie_is_credential(
        {"name": "cpu_bucket", "value": "xlarge"})
    assert not credentials.cookie_is_credential(
        {"name": "dotcom_user", "value": "nometalalchemist"})


def test_observe_cookie_only_vaults_what_it_classifies():
    assert credentials.VAULT.observe_cookie(
        {"name": "session_token", "value": "KS4WEB-COOKIE-SECRET-9f3a1c77d2"})
    assert not credentials.VAULT.observe_cookie(
        {"name": "dotcom_user", "value": "nometalalchemist"})
    text = credentials.VAULT.scrub(
        "https://github.com/nometalalchemist/repo carries "
        "KS4WEB-COOKIE-SECRET-9f3a1c77d2")
    assert "github.com/nometalalchemist/repo" in text
    assert "KS4WEB-COOKIE-SECRET" not in text


def test_observe_storage_item_classifies_by_key():
    assert credentials.VAULT.observe_storage_item(
        "api_key", "KS4WEB-LS-SECRET-51be00aa41")
    assert not credentials.VAULT.observe_storage_item(
        "theme_preference", "dark-high-contrast")
    out = credentials.VAULT.scrub("theme is dark-high-contrast")
    assert "dark-high-contrast" in out


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
