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
from kitchensink4web.policy import consent

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

#: THE FREE-TEXT FIELDS on the install screen. Empty, and pinned empty.
#:
#: There were two, for one wave. `consent_scope` and `preauth` were added in
#: fix wave 10 so that `consent.PREAUTH_TEACHING` would stop pointing a
#: Desktop user at a control nobody had built, and the author rejected both
#: on sight: the install screen is checkboxes, a value a user has to spell
#: correctly is a typo that stops the server from starting, and there is
#: nobody on an install screen to read the error. `consent_scope` became the
#: checkbox it always was underneath (it only ever had two values) and
#: `preauth` left the screen entirely, with the teaching string corrected to
#: say what is now true: pre-authorization is a launch-time setting and has
#: no Desktop field, deliberately.
TYPED_FIELDS: set[str] = set()

#: The two boxes that carry the danger label, and the exact string. A
#: checkbox whose whole job is to hand over a capability that can act on the
#: user's behalf says so where it is ticked.
DANGER_LABEL = "Warning: DANGEROUS"
DANGEROUS_BOXES = {"allow_acting", "pack_diagnostics"}


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
        if key in TYPED_FIELDS:
            continue
        assert entry["default"] is (key in DEFAULT_ON), (
            f"{key} default is {entry['default']}; the shipped install "
            f"screen starts exactly {sorted(DEFAULT_ON)} ticked")
    # The consent box ships unticked, which is the posture the server takes
    # with the variable unset, so accepting every default reproduces the
    # old install exactly.
    assert config["consent_scope"]["type"] == "boolean"
    assert config["consent_scope"]["default"] is False
    assert env[consent.ENV_SCOPE] == "${user_config.consent_scope}"
    # And pre-authorization is off the screen entirely: no box, no wiring.
    assert "preauth" not in config
    assert consent.ENV_PREAUTH not in env


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
                "pack_diagnostics", "pack_network", "pack_workflows",
                "consent_scope"):
        assert config[key]["default"] is False, (
            f"{key} starts on. Read-only and the deliberate-tick rule are "
            f"the shipped defaults; this box can change something.")


def test_the_dangerous_boxes_carry_a_danger_label():
    """Two boxes, one label, in the TITLE. A checkbox whose whole job is to
    hand over a capability that can act on the user's behalf has to say so on
    the screen where it is ticked, not only in a document, and it has to say
    it in the line a person reads before they read anything else.

    `allow_acting` is the write switch and `pack_diagnostics` carries
    evaluate_script, which runs arbitrary page script. The first release
    candidate carried the tiers only inside copy markers addressed to a
    future writer, which is how a manifest with zero danger strings reached
    an install screen; the label now sits in the title, where a scan cannot
    miss it.

    Both directions. The label stays on exactly those two, because a warning
    on everything is a warning on nothing."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    config = manifest["user_config"]
    for key, entry in config.items():
        if key in DANGEROUS_BOXES:
            assert entry["title"].startswith(DANGER_LABEL), (
                f"{key} is a box that hands over a capability and its title "
                f"does not open with {DANGER_LABEL!r}: {entry['title']!r}")
        else:
            assert DANGER_LABEL not in entry["title"], key
    # Cookies-and-logins is the third box that reaches something a user
    # cares about, and it carries its own softer line rather than the
    # danger label.
    assert config["pack_storage"]["description"].startswith("Use with care."), \
        config["pack_storage"]["description"]


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
    """Toggles only, with NO exceptions.

    The rule and the reason both still stand: a typed value is a typo
    waiting to break an install, and the mcpb manifest schema has no enum
    type to make one safe (user_config.type is string, number, boolean,
    directory, or file, with additionalProperties false).

    Fix wave 10 carved out two exceptions for `consent_scope` and `preauth`,
    on the reasoning that `consent.PREAUTH_TEACHING` named a control nobody
    had built and the manifest had better build it. The author rejected that
    trade on sight. The screen is where a stranger meets this product and
    there is nobody standing next to them to read a startup error, so the
    third option, the one nobody took, was the right one: the consent field
    became the checkbox its two values always were, the pre-authorization
    field left the screen, and the teaching string stopped naming a Desktop
    control because there is no longer one to name.

    The sanctioned set is now EMPTY, both directions, so the next free-text
    box needs its own ruling and cannot arrive on the strength of the two
    that were withdrawn."""
    for rel in ("manifest.json", "dev/manifest.json"):
        manifest = json.loads((ROOT / "bundle" / rel)
                              .read_text(encoding="utf-8"))
        typed = {key for key, entry in manifest["user_config"].items()
                 if entry["type"] != "boolean"}
        assert typed == TYPED_FIELDS, (
            f"{rel}: the typed install-screen fields are {sorted(typed)}, "
            f"and the sanctioned set is {sorted(TYPED_FIELDS)}. A new "
            f"free-text box needs a ruling of its own.")
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


def test_the_consent_checkbox_reaches_the_scope_it_promises(
        monkeypatch, launch):
    """THE WIRING BEHIND THE BOX, pinned in both directions.

    The screen asks one question, whether routine form submissions go
    through without asking each time, and the two answers are the two scopes
    that already existed. Claude Desktop writes the literal strings "true"
    and "false" for a user_config boolean, exactly as it does for
    KS4WEB_ALLOW_ACTING, so this is the same route `readonly.parse_allow`
    already travels rather than a second mechanism.

    A tick has to arrive as `full`, because a box that reads as permission
    and grants nothing is a lie in the safe direction and still a lie. An
    untick, and an install that never touched the box at all, has to arrive
    as the narrow default."""
    launch(read_only=False)

    for ticked in ("true", "1", "on", "yes"):
        monkeypatch.setenv(consent.ENV_SCOPE, ticked)
        assert consent.apply() == "full", ticked
    for unticked in ("false", "0", "off", "no", ""):
        monkeypatch.setenv(consent.ENV_SCOPE, unticked)
        assert consent.apply() == consent.DEFAULT_SCOPE, unticked
    monkeypatch.delenv(consent.ENV_SCOPE)
    assert consent.apply() == consent.DEFAULT_SCOPE

    # The typed spelling survives for launch files and shells, where a human
    # can read an error and try again, and garbage there still refuses to
    # start rather than guessing at a consent posture.
    monkeypatch.setenv(consent.ENV_SCOPE, "full")
    assert consent.apply() == "full"
    monkeypatch.setenv(consent.ENV_SCOPE, "reserch")
    with pytest.raises(BadParams) as bad_scope:
        consent.apply()
    assert "research" in str(bad_scope.value)
    assert "full" in str(bad_scope.value)
    monkeypatch.delenv(consent.ENV_SCOPE)


def test_preauth_is_a_launch_time_setting_and_still_refuses_loudly(
        monkeypatch, launch):
    """Pre-authorization left the install screen, not the product.

    It is now reachable one way, the environment variable a human sets in a
    launch file before the server starts, and everything that was true of it
    there is still true: a malformed entry refuses to START rather than
    running with a posture the user did not choose, naming an irreducible
    class refuses instead of quietly dropping it, and empty is a clean
    no-op."""
    launch(read_only=False)

    monkeypatch.setenv(consent.ENV_PREAUTH, "evaluate_script")
    with pytest.raises(BadParams) as bad_form:
        consent.apply()
    assert "<class>@<origin>" in str(bad_form.value)

    monkeypatch.setenv(consent.ENV_PREAUTH, "payment_form@example.com")
    with pytest.raises(BadParams) as irreducible:
        consent.apply()
    assert "cannot be pre-authorized" in str(irreducible.value)

    monkeypatch.setenv(consent.ENV_PREAUTH, "")
    assert consent.apply() == consent.DEFAULT_SCOPE
    assert consent.preauth_entries() == []


def test_the_preauth_teaching_names_no_field_that_does_not_exist():
    """THE GAP, closed from the other side.

    `consent.PREAUTH_TEACHING` told a Desktop user to fill "the
    pre-authorization field in the server's settings", and no such field
    existed. Fix wave 10 closed that by building the field; the author threw
    the field out, so the same sentence would have gone back to describing a
    control nobody has. The clause naming it was deleted instead.

    Both directions, because either half can rot. The teaching names the
    launch-time variable and only that, AND the manifest defines no box for
    it, so the one route the string describes is the one route that exists.
    A future wave that puts the field back has to fail here first."""
    manifest = json.loads((ROOT / "bundle" / "manifest.json")
                          .read_text(encoding="utf-8"))
    teaching = consent.PREAUTH_TEACHING
    assert consent.ENV_PREAUTH in teaching
    assert "<class>@<origin>" in teaching
    for named_control in ("field in the server's settings",
                          "pre-authorization field",
                          "install screen"):
        assert named_control not in teaching, (
            f"PREAUTH_TEACHING points a Desktop user at {named_control!r}, "
            f"which the install screen does not have. The screen is "
            f"checkboxes; this setting lives in the launch file.")
    assert "preauth" not in manifest["user_config"], (
        "the free-text pre-authorization box is back on the install screen. "
        "It was withdrawn deliberately: a value a user has to spell "
        "correctly stops the server from starting, and there is nobody on "
        "an install screen to read the error.")
    assert consent.ENV_PREAUTH not in manifest["server"]["mcp_config"]["env"]
