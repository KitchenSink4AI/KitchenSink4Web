"""Staging an extension, and the two things that must never move.

One: the Firefox build's JavaScript is the JavaScript phases 1 to 3 tested.
The whole reason the Chromium differences live in a shim is that the proven
lane should not be rewritten to make room for an unproven one, and a test
that lets `background.js` drift on the Firefox side would give that away.

Two: the bundle is compiled here, from this install's projection. That is the
property the packaging decision rests on and it is asserted directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kitchensink4web.extension import artifact, bundle, manifests

ROOT = Path(__file__).resolve().parents[2]


def test_each_flavor_stages_exactly_the_files_its_manifest_names():
    ff = artifact.files("firefox")
    assert set(ff) == {"manifest.json", "background.js", "content.js",
                       "projection.bundle.js"}

    cr = artifact.files("chromium")
    assert set(cr) == {"manifest.json", "background.js", "content.js",
                       "compat.js", "projection.bundle.js"}


def test_the_firefox_background_script_is_the_asset_untouched():
    """The proven build ships proven. If this fails, the Firefox lane is
    running something no live test has ever exercised."""
    asset = (artifact.assets_dir() / "background.js").read_text(encoding="utf-8")
    assert artifact.files("firefox")["background.js"] == asset


def test_the_chromium_background_is_the_shim_then_the_same_asset():
    """Concatenation, in that order, with the original body intact.

    Both halves matter. The shim has to come first or `browser` is undefined
    at the first line that reads it; the body has to be verbatim or the
    Chromium build is a fork of the file rather than a wrapping of it.
    """
    asset = (artifact.assets_dir() / "background.js").read_text(encoding="utf-8")
    shim = (artifact.assets_dir() / "compat.js").read_text(encoding="utf-8")
    built = artifact.files("chromium")["background.js"]

    assert built.startswith(shim)
    assert built.endswith(asset)
    assert built.index(shim) < built.index(asset)


def test_the_content_script_is_identical_on_both_builds():
    """Spec section 10 says `content.js` is shared and identical. It is, and
    the shim is what buys that."""
    assert artifact.files("firefox")["content.js"] == \
        artifact.files("chromium")["content.js"]


def test_the_staged_bundle_is_compiled_from_the_projection_not_copied():
    """The packaging argument, asserted.

    A staged bundle equal to `bundle.build()` is a bundle generated from the
    projection sources this interpreter can import. Nothing here reads a
    prebuilt file, so there is no build machine whose state could leak into
    an install.
    """
    for flavor in manifests.FLAVORS:
        assert artifact.files(flavor)["projection.bundle.js"] == bundle.build()


def test_staging_writes_every_file_and_reports_what_it_wrote(tmp_path):
    result = artifact.stage(tmp_path / "ext", "firefox")
    written = {p.name for p in (tmp_path / "ext").iterdir()}

    assert written == set(artifact.files("firefox"))
    assert set(result["files"]) == written
    assert result["digest"] == artifact.digest("firefox")
    for name, size in result["bytes"].items():
        assert (tmp_path / "ext" / name).stat().st_size > 0
        assert size > 0


def test_a_flavor_switch_does_not_leave_the_other_browsers_files_behind(tmp_path):
    """The hazard is specific: Chromium loading a Firefox `background.js`
    finds no `browser` global and dies on the first line with an error that
    names nothing useful."""
    dest = tmp_path / "ext"
    artifact.stage(dest, "chromium")
    assert (dest / "compat.js").is_file()

    artifact.stage(dest, "firefox")
    assert not (dest / "compat.js").exists()
    assert (dest / "background.js").read_text(encoding="utf-8") == \
        artifact.files("firefox")["background.js"]


def test_a_stray_file_in_the_staging_directory_is_removed(tmp_path):
    dest = tmp_path / "ext"
    dest.mkdir()
    (dest / "leftover.js").write_text("// from some previous life", encoding="utf-8")
    (dest / "olddir").mkdir()

    artifact.stage(dest, "firefox")
    assert not (dest / "leftover.js").exists()
    assert not (dest / "olddir").exists()


def test_keeping_the_directory_is_possible_when_asked(tmp_path):
    dest = tmp_path / "ext"
    dest.mkdir()
    (dest / "notes.txt").write_text("mine", encoding="utf-8")
    artifact.stage(dest, "firefox", clean=False)
    assert (dest / "notes.txt").is_file()


def test_the_digest_separates_the_two_flavors():
    """Two builds of the same version are not the same artefact, and a
    digest that could not tell them apart would answer 'is the extension in
    my browser the one this server compiled?' wrongly."""
    assert artifact.digest("firefox") != artifact.digest("chromium")


def test_the_digest_is_stable_across_calls():
    assert artifact.digest("firefox") == artifact.digest("firefox")


def test_an_unknown_flavor_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError, match="opera"):
        artifact.stage(tmp_path / "ext", "opera")
    assert not (tmp_path / "ext").exists() or not any((tmp_path / "ext").iterdir())


def test_the_unpacked_chromium_id_has_the_shape_chromium_assigns(tmp_path):
    """Thirty-two characters drawn from a to p. Chromium hashes the path and
    maps hex nibbles onto that alphabet, so an id with a digit in it or a
    letter past 'p' is not an id Chromium would ever produce."""
    got = artifact.unpacked_chromium_id(tmp_path)
    assert len(got) == 32
    assert set(got) <= set("abcdefghijklmnop")


def test_the_unpacked_id_follows_the_directory(tmp_path):
    a = artifact.unpacked_chromium_id(tmp_path / "a")
    b = artifact.unpacked_chromium_id(tmp_path / "b")
    assert a != b
    assert a == artifact.unpacked_chromium_id(tmp_path / "a")


def test_the_repository_staging_matches_what_the_generator_produces():
    """The drift pin, extended from the bundle to the whole directory.

    `extension/` is what the live tests load. If it can drift from the
    generator, then the thing under test and the thing shipped are two
    different extensions and every live result is about the wrong one.
    """
    staged = artifact.repo_extension_dir(ROOT)
    expected = artifact.files("firefox")

    assert {p.name for p in staged.iterdir()} == set(expected)
    for name, text in expected.items():
        # read_text normalises line endings, so this compares CONTENT and
        # does not fail on a checkout with CRLF in the working tree.
        assert (staged / name).read_text(encoding="utf-8") == text, (
            f"extension/{name} is stale: regenerate it with "
            "`python -m kitchensink4web.extension.artifact`"
        )
