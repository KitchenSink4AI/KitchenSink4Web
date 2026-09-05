"""The origin allow/deny evaluator: deny first, wildcards, strict grade,
and the landed-phase refusal text (DESIGN 5.9, 5.2)."""

from __future__ import annotations

import pytest

from kitchensink4web.errors import NavigationBlocked, ReadOnlyMode
from kitchensink4web.policy import origins


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(origins.ENV_DENY, raising=False)
    monkeypatch.delenv(origins.ENV_ALLOW, raising=False)


def test_no_lists_means_allowed():
    assert origins.evaluate("https://example.com/x") == "allowed"


def test_deny_is_evaluated_first_even_when_allowed_too(monkeypatch):
    monkeypatch.setenv(origins.ENV_DENY, "example.com")
    monkeypatch.setenv(origins.ENV_ALLOW, "example.com")
    assert origins.evaluate("https://example.com/") == "denied"


def test_wildcard_matches_subdomains_and_bare_domain(monkeypatch):
    monkeypatch.setenv(origins.ENV_DENY, "*.tracker.example")
    assert origins.evaluate("https://tracker.example/") == "denied"
    assert origins.evaluate("https://a.b.tracker.example/") == "denied"
    assert origins.evaluate("https://nottracker.example/") == "allowed"


def test_full_origin_pattern_matches_scheme_host_port(monkeypatch):
    monkeypatch.setenv(origins.ENV_DENY, "https://example.com:8443")
    assert origins.evaluate("https://example.com:8443/x") == "denied"
    assert origins.evaluate("https://example.com/x") == "allowed"
    assert origins.evaluate("http://example.com:8443/x") == "allowed"


def test_allowlist_makes_unlisted_offlist_not_denied(monkeypatch):
    monkeypatch.setenv(origins.ENV_ALLOW, "docs.example")
    assert origins.evaluate("https://docs.example/a") == "allowed"
    assert origins.evaluate("https://other.example/a") == "off-list"


def test_exempt_schemes_always_allowed(monkeypatch):
    """about:blank must stay reachable: it is where an aborted navigation
    parks, and a policy that blocked the abort target would deadlock."""
    monkeypatch.setenv(origins.ENV_ALLOW, "docs.example")
    assert origins.evaluate("about:blank") == "allowed"


def test_check_navigation_denied_raises_and_names_the_env(monkeypatch):
    monkeypatch.setenv(origins.ENV_DENY, "blocked.example")
    with pytest.raises(NavigationBlocked) as exc:
        origins.check_navigation("https://blocked.example/", None)
    assert origins.ENV_DENY in str(exc.value)
    assert "not started" in str(exc.value)


def test_landed_phase_says_the_redirect_already_happened(monkeypatch):
    monkeypatch.setenv(origins.ENV_DENY, "blocked.example")
    with pytest.raises(NavigationBlocked) as exc:
        origins.check_navigation("https://blocked.example/", None,
                                 phase="landed")
    assert "about:blank" in str(exc.value)
    assert "nothing was read" in str(exc.value)


def test_strict_grade_refuses_offlist_with_read_only_mode(monkeypatch):
    monkeypatch.setenv(origins.ENV_ALLOW, "docs.example")
    with pytest.raises(ReadOnlyMode):
        origins.check_navigation("https://other.example/", "strict")
    # browse grade routes off-list to the gate instead of refusing.
    assert origins.check_navigation(
        "https://other.example/", "browse") == "off-list"
