"""The 14-day update check: one calm line, never an install, silent skips.

Every test drives the network seam through a monkeypatched urlopen; nothing
here touches the real PyPI."""

from __future__ import annotations

import io
import json
import time

import pytest

from kitchensink4web import updatecheck
from kitchensink4web.policy import audit


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _pypi(version):
    return _Resp(json.dumps({"info": {"version": version}}).encode())


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv(updatecheck.ENV_OPT_OUT, raising=False)
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    monkeypatch.setattr(updatecheck, "_installed_version", lambda: "1.0.0")
    yield tmp_path


def test_behind_speaks_one_calm_line(monkeypatch):
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.2.0"))
    line = updatecheck.status_line()
    assert line is not None
    assert "1.0.0" in line and "1.2.0" in line
    assert "Nothing updates itself" in line
    assert "pip install -U kitchensink4web" in line


def test_up_to_date_and_ahead_stay_silent(monkeypatch):
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.0.0"))
    assert updatecheck.status_line() is None
    (audit.STATE_DIR / "update_check.json").unlink()
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("0.9.0"))
    assert updatecheck.status_line() is None


def test_opt_out_skips_cache_and_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the opt-out must not reach the network")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", boom)
    monkeypatch.setenv(updatecheck.ENV_OPT_OUT, "1")
    assert updatecheck.status_line() is None


def test_network_failure_is_a_silent_skip(monkeypatch, isolated):
    def down(*a, **k):
        raise OSError("no route to host")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", down)
    assert updatecheck.status_line() is None
    assert not (isolated / "update_check.json").exists(), (
        "a failed fetch must not write a cache entry")


def test_fresh_cache_answers_without_the_network(monkeypatch, isolated):
    (isolated / "update_check.json").write_text(json.dumps(
        {"checked_at": time.time(), "latest": "2.0.0"}), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("a fresh cache must not reach the network")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", boom)
    line = updatecheck.status_line()
    assert line and "2.0.0" in line


def test_stale_cache_refetches_and_rewrites(monkeypatch, isolated):
    (isolated / "update_check.json").write_text(json.dumps(
        {"checked_at": time.time() - updatecheck.CACHE_MAX_AGE_S - 60,
         "latest": "1.5.0"}), encoding="utf-8")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.6.0"))
    line = updatecheck.status_line()
    assert line and "1.6.0" in line
    cached = json.loads((isolated / "update_check.json")
                        .read_text(encoding="utf-8"))
    assert cached["latest"] == "1.6.0"


def test_unparsable_versions_stay_silent(monkeypatch):
    monkeypatch.setattr(updatecheck, "_installed_version",
                        lambda: "1.0.0.dev3")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("2.0.0"))
    assert updatecheck.status_line() is None
