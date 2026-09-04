"""The ported policy machinery: the path sandbox and the ReDoS guard.

These are the "ported machinery's own tests" half of the Phase 0 gate. The
sandbox algorithm is copied unchanged from word-mcp, so these tests are the
family's escape cases re-run against the KS4WEB_ALLOWED_ROOTS spelling: a
path check that passes in one product and fails in another because the env
var was renamed is exactly the kind of thing a port introduces.
"""

from __future__ import annotations

import os

import pytest

from kitchensink4web.errors import WebMcpError
from kitchensink4web.policy import _regex, sandbox


@pytest.fixture
def roots(tmp_path, monkeypatch):
    allowed = tmp_path / "downloads"
    allowed.mkdir()
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setenv(sandbox.ENV_VAR, str(allowed))
    yield tmp_path, allowed


def test_env_var_is_the_ruled_name():
    """Q11, RULED 2026-09-04. A renamed env var that nobody updated is a
    sandbox that silently does nothing."""
    assert sandbox.ENV_VAR == "KS4WEB_ALLOWED_ROOTS"


def test_unset_means_no_restriction(monkeypatch):
    monkeypatch.delenv(sandbox.ENV_VAR, raising=False)
    assert sandbox.active() is False
    assert sandbox.check_path("C:/anywhere/at/all") == "C:/anywhere/at/all"


def test_inside_a_root_is_allowed(roots):
    _tmp, allowed = roots
    target = allowed / "report.xlsx"
    assert sandbox.check_path(str(target), "save a download")


def test_outside_a_root_refuses(roots):
    tmp, _allowed = roots
    with pytest.raises(sandbox.SandboxViolation):
        sandbox.check_path(str(tmp / "elsewhere" / "secrets.txt"),
                           "read an upload source")


def test_traversal_cannot_escape(roots):
    _tmp, allowed = roots
    escape = os.path.join(str(allowed), "..", "elsewhere", "secrets.txt")
    with pytest.raises(sandbox.SandboxViolation):
        sandbox.check_path(escape, "save a download")


def test_prefix_collision_is_not_containment(tmp_path, monkeypatch):
    """Root 'C:/x/Downloads' must never admit 'C:/x/Downloads2'."""
    root = tmp_path / "Downloads"
    root.mkdir()
    sibling = tmp_path / "Downloads2"
    sibling.mkdir()
    monkeypatch.setenv(sandbox.ENV_VAR, str(root))
    with pytest.raises(sandbox.SandboxViolation):
        sandbox.check_path(str(sibling / "f.txt"), "save a download")


def test_null_byte_refuses(roots):
    with pytest.raises(sandbox.SandboxViolation):
        sandbox.check_path("C:/downloads/x\x00.txt", "save a download")


def test_unc_refuses_when_no_root_is_unc(roots):
    with pytest.raises(sandbox.SandboxViolation):
        sandbox.check_path(r"\\server\share\f.txt", "save a download")


def test_violation_is_a_web_mcp_error(roots):
    """The violation must ride the KS4Web taxonomy so the envelope maps it
    rather than letting it escape as a raw exception."""
    assert issubclass(sandbox.SandboxViolation, WebMcpError)


def test_violation_message_names_the_env_var(roots):
    tmp, _allowed = roots
    with pytest.raises(sandbox.SandboxViolation) as exc:
        sandbox.check_path(str(tmp / "elsewhere" / "x"), "read a HAR")
    text = str(exc.value)
    assert "KS4WEB_ALLOWED_ROOTS" in text
    assert "read a HAR" in text


# --------------------------------------------------------- the ReDoS guard


def test_valid_pattern_matches():
    hits = _regex.finditer(r"Fourteen \w+", "the Fourteen Points speech")
    assert len(hits) == 1


def test_invalid_pattern_refuses_typed():
    with pytest.raises(WebMcpError):
        _regex.compile_user_pattern("(unclosed")


def test_guard_has_a_finite_timeout():
    """find_elements takes a caller pattern and runs it against PAGE TEXT,
    so both halves of a catastrophic-backtracking pair are reachable by an
    adversary. The guard must be bounded, not merely present."""
    assert 0 < _regex.TIMEOUT_S <= 30
