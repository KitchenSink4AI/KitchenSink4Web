"""`--setup-browser`, both directions.

Every test that touches the real registry uses a HOST NAME OF ITS OWN and
removes it. The author's machine has a working Lane C registration on it and
a test that clobbered `ks4web` would break their browser to prove a point.
"""

from __future__ import annotations

import json
import os

import pytest

from kitchensink4web.extension import artifact, manifests, register, setup

#: Never `ks4web`. See the module docstring.
TEST_HOST = "ks4web_test_phase4"


@pytest.fixture
def installed(tmp_path):
    """A firefox install in a temp directory, registry untouched."""
    return setup.install("firefox", install_dir=tmp_path / "app",
                         touch_registry=False, host_name=TEST_HOST)


# ------------------------------------------------------------------ installing

def test_the_install_writes_the_extension_the_relay_and_the_host(installed, tmp_path):
    app = tmp_path / "app"
    assert (app / "extension" / "firefox" / "manifest.json").is_file()
    assert (app / f"{TEST_HOST}_relay.bat").is_file() or os.name != "nt"
    assert (app / f"{TEST_HOST}.json").is_file() or os.name != "nt"
    assert installed["verified"]["extension_complete"] is True
    assert installed["verified"]["missing_files"] == []


def test_the_staged_extension_is_the_one_the_generator_makes(installed, tmp_path):
    """An install that staged something other than what this server compiles
    would be the drift the whole packaging decision exists to prevent."""
    staged = tmp_path / "app" / "extension" / "firefox"
    for name, text in artifact.files("firefox").items():
        assert (staged / name).read_text(encoding="utf-8") == text


def test_firefox_trusts_the_id_its_manifest_pins(installed):
    assert installed["extension_id"] == manifests.GECKO_ID
    assert installed["extension_id_source"] == "pinned in the manifest"

    manifest = json.loads(open(installed["registration"]["manifest"],
                               encoding="utf-8").read())
    assert manifest["allowed_extensions"] == [manifests.GECKO_ID]
    # The Chromium spelling must NOT be there: a host manifest carrying the
    # wrong key is ignored in silence rather than rejected with a reason.
    assert "allowed_origins" not in manifest


def test_chromium_trusts_the_id_derived_from_where_the_extension_landed(tmp_path):
    result = setup.install("chrome", install_dir=tmp_path / "app",
                           touch_registry=False, host_name=TEST_HOST)
    staged = tmp_path / "app" / "extension" / "chromium"

    assert result["extension_id"] == artifact.unpacked_chromium_id(staged)
    assert "derived" in result["extension_id_source"]

    manifest = json.loads(open(result["registration"]["manifest"],
                               encoding="utf-8").read())
    assert manifest["allowed_origins"] == \
        [f"chrome-extension://{result['extension_id']}/"]
    assert "allowed_extensions" not in manifest


def test_a_supplied_id_wins_over_the_derived_one(tmp_path):
    """The escape hatch for a PACKED Chromium extension, whose id comes from
    a signing key and cannot be computed from a path."""
    result = setup.install("chrome", install_dir=tmp_path / "app",
                           touch_registry=False, host_name=TEST_HOST,
                           extension_id="abcdefghijklmnopabcdefghijklmnop")
    assert result["extension_id"] == "abcdefghijklmnopabcdefghijklmnop"
    assert result["extension_id_source"] == "supplied by the caller"


def test_the_two_browsers_stage_into_different_directories(tmp_path):
    app = tmp_path / "app"
    setup.install("firefox", install_dir=app, touch_registry=False,
                  host_name=TEST_HOST)
    setup.install("chrome", install_dir=app, touch_registry=False,
                  host_name=TEST_HOST)
    assert (app / "extension" / "firefox" / "manifest.json").is_file()
    assert (app / "extension" / "chromium" / "compat.js").is_file()
    assert not (app / "extension" / "firefox" / "compat.js").exists()


def test_an_unknown_browser_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError, match="safari"):
        setup.install("safari", install_dir=tmp_path / "app",
                      touch_registry=False, host_name=TEST_HOST)
    assert not (tmp_path / "app" / "extension").exists()


# -------------------------------------------------------------------- removing

def test_remove_takes_the_extension_and_the_files_off(tmp_path):
    app = tmp_path / "app"
    setup.install("firefox", install_dir=app, touch_registry=False,
                  host_name=TEST_HOST)
    assert (app / "extension" / "firefox").is_dir()

    result = setup.remove("firefox", install_dir=app, host_name=TEST_HOST)
    assert result["removed"]["extension"] is True
    assert not (app / "extension" / "firefox").exists()
    if os.name == "nt":
        assert result["removed"]["manifest"] is True
        assert result["removed"]["wrapper"] is True


def test_remove_reports_each_piece_separately(tmp_path):
    """A cleanup that took the registry key and left the manifest is a
    different state from one that took both, and the user chasing 'why is it
    still connecting?' has to be told which."""
    result = setup.remove("firefox", install_dir=tmp_path / "never-installed",
                          host_name=TEST_HOST)
    assert set(result["removed"]) == {"registry_key", "manifest", "wrapper",
                                      "extension"}
    assert all(v is False for v in result["removed"].values())


def test_removing_twice_is_not_an_error(tmp_path):
    app = tmp_path / "app"
    setup.install("firefox", install_dir=app, touch_registry=False,
                  host_name=TEST_HOST)
    setup.remove("firefox", install_dir=app, host_name=TEST_HOST)
    again = setup.remove("firefox", install_dir=app, host_name=TEST_HOST)
    assert again["removed"]["extension"] is False


def test_remove_can_be_told_to_keep_the_staged_extension(tmp_path):
    app = tmp_path / "app"
    setup.install("firefox", install_dir=app, touch_registry=False,
                  host_name=TEST_HOST)
    setup.remove("firefox", install_dir=app, host_name=TEST_HOST,
                 keep_extension=True)
    assert (app / "extension" / "firefox" / "manifest.json").is_file()


def test_remove_says_out_loud_what_it_cannot_do(tmp_path):
    """No command can take an add-on out of a browser. A removal that
    reported success without saying so would leave the user believing the
    extension was gone."""
    result = setup.remove("firefox", install_dir=tmp_path / "app",
                          host_name=TEST_HOST)
    assert "add-on" in result["requires_human"]


# ---------------------------------------------------------- the real registry

@pytest.mark.skipif(os.name != "nt", reason="the registry is Windows-only")
def test_the_registry_round_trip_writes_reads_and_removes(tmp_path):
    """The full loop through the oracle the browser itself uses.

    Under a test host name, so the author's own `ks4web` registration is
    never touched, and removed in a finally so a failing assert does not
    leave a key behind on their machine.
    """
    assert register.read_registration(TEST_HOST) is None
    try:
        result = setup.install("firefox", install_dir=tmp_path / "app",
                               host_name=TEST_HOST)
        assert result["verified"]["host_registered"] is True
        assert register.read_registration(TEST_HOST) == \
            result["registration"]["manifest"]
        assert result["verified"]["host_manifest_exists"] is True

        removal = setup.remove("firefox", install_dir=tmp_path / "app",
                               host_name=TEST_HOST)
        assert removal["removed"]["registry_key"] is True
        assert removal["still_registered"] is None
    finally:
        register.unregister_windows(TEST_HOST)
    assert register.read_registration(TEST_HOST) is None


@pytest.mark.skipif(os.name != "nt", reason="the registry is Windows-only")
def test_each_browser_gets_its_own_registry_key(tmp_path):
    """Chrome and Firefox read different keys. One registration that landed
    under the wrong parent is a host the browser will never find."""
    try:
        setup.install("chrome", install_dir=tmp_path / "app",
                      host_name=TEST_HOST)
        assert register.read_registration(TEST_HOST, "chrome") is not None
        # And nothing leaked into Firefox's key.
        assert register.read_registration(TEST_HOST, "firefox") is None
    finally:
        register.unregister_windows(TEST_HOST, browser="chrome")
        register.unregister_windows(TEST_HOST, browser="firefox")


# ---------------------------------------------------------------- what it says

def test_the_printed_output_names_every_path_and_flags_the_manual_step(installed):
    text = setup.render(installed)
    assert installed["extension"]["path"] in text
    assert installed["registration"]["wrapper"] in text
    assert installed["extension"]["digest"] in text
    assert "[COPY PENDING]" in text
    assert "--remove" in text


def test_the_output_does_not_claim_a_registration_it_did_not_make(installed):
    """`touch_registry=False` wrote files and registered nothing. Printing
    'registered' there is the confident wrong line this project exists to
    not print."""
    text = setup.render(installed)
    if os.name == "nt":
        assert "NOT registered" in text


def test_the_removal_output_lists_the_pieces(tmp_path):
    result = setup.remove("firefox", install_dir=tmp_path / "app",
                          host_name=TEST_HOST)
    text = setup.render(result)
    for piece in ("registry_key", "manifest", "wrapper", "extension"):
        assert piece in text


def test_an_untested_platform_says_so(installed):
    """Firefox on Windows is proven here; Chrome is not. A user on an
    unexercised combination is told they are the first rather than left to
    find out."""
    assert register.describe("firefox")["proven_on_this_platform"] is (os.name == "nt")
    assert register.describe("chrome")["proven_on_this_platform"] is False
