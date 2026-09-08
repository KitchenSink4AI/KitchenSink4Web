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


#: THE ONLY BOXES THE SHIPPED INSTALL SCREEN STARTS TICKED (orchestrator
#: ruling, fix wave 10). The field report's item 4 said a default install
#: "can read but not act" and called the configuration surface daunting; the
#: answer taken was to start the two READ packs on, and nothing else. Both
#: are read-only capabilities, so the safety default is untouched: acting is
#: still off, storage is still off, and everything that can change a page,
#: reach the filesystem, or run a script is still a deliberate tick.
#: Named here rather than asserted inline so a future default change is a
#: visible edit to a named list rather than a loosened assertion.
DEFAULT_ON = {"pack_extract", "pack_capture"}


def test_manifest_source_carries_every_toggle():
    """Parity between the pack table and the .mcpb manifest source: every
    pack has its checkbox and its env mapping, plus the master toggle and
    the acting checkbox, and every boolean outside DEFAULT_ON starts off."""
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
        assert config[key]["description"].strip(), (
            f"{pack} has no what-you-get sentence")
        assert env[packs.ENV_PACK_PREFIX + pack.upper()] == \
            f"${{user_config.{key}}}"
    for key, entry in config.items():
        assert entry["default"] is (key in DEFAULT_ON), (
            f"{key} default is {entry['default']}; the shipped install "
            f"screen starts exactly {sorted(DEFAULT_ON)} ticked")


def test_nothing_that_can_change_anything_starts_on():
    """THE BOTH-DIRECTION PIN on the default change. Whatever the read
    defaults become, the write switch and every pack that can alter a page,
    touch the filesystem, or run a script must be a deliberate tick.

    Written as its own test rather than as a line inside the one above,
    because the list above is a calibration a future wave may reasonably
    edit and this one is not."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    config = manifest["user_config"]
    for key in ("allow_acting", "all_packs", "pack_storage", "pack_files",
                "pack_diagnostics", "pack_network", "pack_workflows"):
        assert config[key]["default"] is False, (
            f"{key} starts on. Read-only and the deliberate-tick rule are "
            f"the shipped defaults; this box can change something.")


def test_the_dangerous_boxes_carry_a_danger_label():
    """Two tiers, four boxes. A checkbox whose whole job is to hand over a
    capability that can act on the user's behalf has to say so on the screen
    where it is ticked, not only in a document.

    STRONG WARNING: `allow_acting` is the write switch, and
    `pack_diagnostics` carries evaluate_script, which runs arbitrary page
    script. CAUTION: `pack_storage` reaches saved logins and `pack_files`
    reaches the filesystem and the clipboard."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    config = manifest["user_config"]
    for key in ("allow_acting", "pack_diagnostics"):
        assert "STRONG WARNING" in config[key]["description"], key
    for key in ("pack_storage", "pack_files"):
        assert "CAUTION" in config[key]["description"], key
    # And no box that is not one of those four wears a label, so the labels
    # keep meaning something.
    labelled = {"allow_acting", "pack_diagnostics", "pack_storage",
                "pack_files"}
    for key, entry in config.items():
        if key in labelled:
            continue
        assert "STRONG WARNING" not in entry["description"], key
        assert "CAUTION" not in entry["description"], key


def test_the_manifest_names_where_to_get_help():
    """homepage / documentation / support, mirroring the shape KitchenSink4XL
    ships. An install screen with no route to the docs or to an issue tracker
    leaves a stuck user with nowhere to go."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    for field in ("homepage", "documentation", "support"):
        assert manifest.get(field), f"the manifest has no {field}"
        assert manifest[field].startswith("https://"), field
    assert manifest["support"].endswith("/issues")
    assert "#readme" in manifest["documentation"]
    # The org migration will repoint these; what must never drift is that
    # they and the repository field name the same project.
    repo = manifest["repository"]["url"]
    assert manifest["documentation"].startswith(repo), (
        manifest["documentation"], repo)
    assert manifest["support"].startswith(repo)


def test_dev_manifest_differs_only_in_defaults():
    """The FIELD-TEST manifest (bundle/dev/manifest.json). It runs the same
    server; it exists so a field test does not spend its first hour signing
    in.

    What this holds: same pack checkboxes and same env mapping as the
    shipped manifest, storage ON, acting still OFF (the safety default is
    not a test convenience), and no field that differs from the shipped
    manifest beyond a default."""
    shipped = json.loads((ROOT / "bundle" / "manifest.json")
                         .read_text(encoding="utf-8"))
    dev = json.loads((ROOT / "bundle" / "dev" / "manifest.json")
                     .read_text(encoding="utf-8"))
    assert dev["name"] != shipped["name"]
    assert dev["server"]["mcp_config"]["args"] == \
        shipped["server"]["mcp_config"]["args"]
    env = dev["server"]["mcp_config"]["env"]
    config = dev["user_config"]
    for pack in ALL:
        assert env[packs.ENV_PACK_PREFIX + pack.upper()] == \
            f"${{user_config.pack_{pack}}}"
    assert config["pack_storage"]["default"] is True
    assert config["allow_acting"]["default"] is False
    # Same field set as the shipped manifest: the two builds differ in what a
    # box starts at, never in which boxes exist.
    assert set(config) == set(shipped["user_config"])
    assert set(env) == set(shipped["server"]["mcp_config"]["env"])
    # Every pack except storage stays off here too.
    for pack in ALL:
        if pack != "storage":
            assert config[f"pack_{pack}"]["default"] is False


def test_every_install_screen_box_is_a_toggle():
    """No free-text or numeric field on any install screen. A typed value is
    a typo waiting to break an install, and the mcpb manifest schema has no
    enum type to make one safe (user_config.type is string, number, boolean,
    directory, or file, with additionalProperties false), so booleans are the
    only control this surface gets."""
    for rel in ("manifest.json", "dev/manifest.json"):
        manifest = json.loads((ROOT / "bundle" / rel)
                              .read_text(encoding="utf-8"))
        for key, entry in manifest["user_config"].items():
            assert entry["type"] == "boolean", (
                f"{rel}: {key} is a {entry['type']} field; install-screen "
                f"settings are toggles only")
        env = manifest["server"]["mcp_config"]["env"]
        for var, ref in env.items():
            referenced = ref.removeprefix("${user_config.").removesuffix("}")
            assert referenced in manifest["user_config"], (
                f"{rel}: {var} points at {referenced}, which no box defines")


def test_empty_lane_env_resolves_to_the_bundled_default(monkeypatch):
    """Lane selection lives in environment variables, not on the install
    screen, and an unset variable arrives as an empty string often enough
    that empty must mean "the default lane", not a typo refusal."""
    from kitchensink4web.engine import lanes
    monkeypatch.setenv("KS4WEB_LANE", "")
    monkeypatch.setenv("KS4WEB_CHANNEL", "")
    spec = lanes.resolve()
    assert spec.lane == "A" and spec.engine == "chromium"
    monkeypatch.setenv("KS4WEB_LANE", "B")
    monkeypatch.setenv("KS4WEB_CHANNEL", "moz-firefox")
    spec = lanes.resolve()
    assert spec.lane == "B" and spec.engine == "firefox"


def test_manifest_version_tracks_the_package_and_its_own_pin():
    """One version, three places, checked rather than remembered: the
    package, the manifest, and the uvx pin inside the manifest. A bundle
    whose pin lags its own version installs a different server than the one
    the install screen describes."""
    import re

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    for rel in ("manifest.json", "dev/manifest.json"):
        manifest = json.loads((ROOT / "bundle" / rel)
                              .read_text(encoding="utf-8"))
        assert manifest["version"] == version, rel
        assert manifest["server"]["mcp_config"]["args"] == \
            [f"kitchensink4web=={version}"], rel


def test_the_readme_pack_table_quotes_the_manifest_sentences():
    """The README's pack table is the install screen's own wording, not a
    paraphrase of it. Two descriptions of one pack is how a user learns that
    the documentation and the product disagree."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for pack in ALL:
        sentence = manifest["user_config"][f"pack_{pack}"]["description"]
        assert sentence in readme, (
            f"the README's {pack} row does not quote the manifest sentence "
            f"verbatim: {sentence!r}")


def test_the_packed_bundles_match_their_manifests():
    """The two `.mcpb` artifacts in the tree, against the manifests they are
    built from. Both are tracked files, so a manifest edit that is not
    repacked ships an install screen nobody wrote.

    This is the second drift of that shape. The config-fix pass of
    2026-09-07 repacked `bundle/dev/kitchensink4web-dev.mcpb` after finding
    it still carrying a retired eleven-field manifest, and by 2026-09-08
    BOTH artifacts were nine settings against their manifests' ten: the
    senses wave added the accessibility pack to the manifests and neither
    zip was rebuilt. Unzipping a bundle to check it is something people
    remember to do once."""
    import zipfile

    for mcpb, source in (
            ("bundle/kitchensink4web.mcpb", "bundle/manifest.json"),
            ("bundle/dev/kitchensink4web-dev.mcpb", "bundle/dev/manifest.json")):
        with zipfile.ZipFile(ROOT / mcpb) as bundle:
            assert sorted(bundle.namelist()) == ["icon.png", "manifest.json"], \
                f"{mcpb} holds {sorted(bundle.namelist())}"
            packed = json.loads(bundle.read("manifest.json"))
        tracked = json.loads((ROOT / source).read_text(encoding="utf-8"))
        assert packed == tracked, (
            f"{mcpb} does not match {source}. Settings in the zip: "
            f"{sorted(packed.get('user_config', {}))}; in the manifest: "
            f"{sorted(tracked.get('user_config', {}))}. Repack it.")
