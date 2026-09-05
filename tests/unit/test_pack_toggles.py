"""The install-screen pack toggles (Phase 8 config work).

Packs are launch-fixed, so the .mcpb install screen is the only chooser a
non-developer ever sees. The contract under test: envs accept the literal
strings 'true' and 'false' (what Desktop writes for a user_config boolean),
empty means off, garbage refuses loudly, and precedence runs
--packs > KS4WEB_MODE > KS4WEB_ALL_PACKS > KS4WEB_PACK_<NAME>. A parity
test holds the manifest source to the pack table, so a pack added in code
cannot silently miss its checkbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kitchensink4web import packs
from kitchensink4web.errors import BadParams

ROOT = Path(__file__).resolve().parents[2]
ALL = sorted(packs.PACK_SUMMARIES)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("KS4WEB_MODE", raising=False)
    monkeypatch.delenv(packs.ENV_ALL_PACKS, raising=False)
    for pack in ALL:
        monkeypatch.delenv(packs.ENV_PACK_PREFIX + pack.upper(),
                           raising=False)


def test_master_toggle_loads_everything(monkeypatch):
    monkeypatch.setenv(packs.ENV_ALL_PACKS, "true")
    assert packs.resolve_startup_packs() == ALL


def test_per_pack_toggles_load_exactly_what_is_true(monkeypatch):
    monkeypatch.setenv("KS4WEB_PACK_EXTRACT", "true")
    monkeypatch.setenv("KS4WEB_PACK_FILES", "true")
    monkeypatch.setenv("KS4WEB_PACK_CAPTURE", "false")
    assert packs.resolve_startup_packs() == ["extract", "files"]


def test_empty_means_off(monkeypatch):
    monkeypatch.setenv(packs.ENV_ALL_PACKS, "")
    monkeypatch.setenv("KS4WEB_PACK_NETWORK", "")
    assert packs.resolve_startup_packs() == []


def test_garbage_refuses_loudly(monkeypatch):
    monkeypatch.setenv("KS4WEB_PACK_STORAGE", "yes please")
    with pytest.raises(BadParams, match="KS4WEB_PACK_STORAGE"):
        packs.resolve_startup_packs()
    monkeypatch.delenv("KS4WEB_PACK_STORAGE")
    monkeypatch.setenv(packs.ENV_ALL_PACKS, "1")
    with pytest.raises(BadParams, match="KS4WEB_ALL_PACKS"):
        packs.resolve_startup_packs()


def test_mode_beats_the_master_toggle(monkeypatch):
    """A developer's explicit KS4WEB_MODE wins over a leftover checkbox,
    in BOTH directions."""
    monkeypatch.setenv(packs.ENV_ALL_PACKS, "true")
    monkeypatch.setenv("KS4WEB_MODE", "lite")
    assert packs.resolve_startup_packs() == []
    monkeypatch.setenv("KS4WEB_MODE", "extract")
    assert packs.resolve_startup_packs() == ["extract"]


def test_mode_beats_per_pack_toggles(monkeypatch):
    monkeypatch.setenv("KS4WEB_PACK_NETWORK", "true")
    monkeypatch.setenv("KS4WEB_MODE", "capture")
    assert packs.resolve_startup_packs() == ["capture"]


def test_cli_beats_everything(monkeypatch):
    monkeypatch.setenv(packs.ENV_ALL_PACKS, "true")
    monkeypatch.setenv("KS4WEB_MODE", "full")
    assert packs.resolve_startup_packs(cli_packs=["files"]) == ["files"]


def test_unset_everything_is_still_lite():
    assert packs.resolve_startup_packs() == []


def test_manifest_source_carries_every_toggle():
    """Parity between the pack table and the .mcpb manifest source: every
    pack has its checkbox and its env mapping, plus the master toggle and
    the acting checkbox, and every boolean defaults OFF (lite, read-only
    shipped defaults)."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    config = manifest["user_config"]
    env = manifest["server"]["mcp_config"]["env"]
    assert "allow_acting" in config
    assert env["KS4WEB_ALLOW_ACTING"] == "${user_config.allow_acting}"
    assert "all_packs" in config
    assert env[packs.ENV_ALL_PACKS] == "${user_config.all_packs}"
    for pack in ALL:
        key = f"pack_{pack}"
        assert key in config, f"manifest misses the {pack} checkbox"
        assert config[key]["type"] == "boolean"
        assert config[key]["default"] is False
        assert config[key]["description"].strip(), (
            f"{pack} has no what-you-get sentence")
        assert env[packs.ENV_PACK_PREFIX + pack.upper()] == \
            f"${{user_config.{key}}}"
    for key, entry in config.items():
        assert entry["default"] is False, (
            f"{key} must default off: lite and read-only are the shipped "
            f"defaults")
