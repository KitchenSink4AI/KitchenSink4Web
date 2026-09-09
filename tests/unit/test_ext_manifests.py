"""Two manifests off one description, and the properties that hold on both.

The failure this file exists to catch is drift: a permission added to Firefox
and forgotten on Chromium, which ships a capability that works for whoever
built it and silently does not for a user on the other browser. Generating
both from one description makes that hard; these tests make it fail loudly.
"""

from __future__ import annotations

import json

import pytest

from kitchensink4web.extension import manifests


def test_the_two_manifests_declare_the_same_powers():
    """MV2 and MV3 spell host access differently and must still ask for it.

    MV2 puts `<all_urls>` in `permissions`; MV3 moved it to
    `host_permissions`. A build that dropped it from one of them would read
    pages on one browser and refuse on the other, which is the exact drift
    two hand-edited files produce.
    """
    ff = manifests.firefox()
    cr = manifests.chromium()

    assert manifests.ALL_URLS in ff["permissions"]
    assert manifests.ALL_URLS not in cr["permissions"]
    assert cr["host_permissions"] == [manifests.ALL_URLS]

    shared = set(manifests._COMMON_PERMISSIONS)
    assert shared <= set(ff["permissions"])
    assert shared <= set(cr["permissions"])


def test_only_the_mv3_build_asks_for_scripting():
    """`scripting` is MV3's name for a power MV2 already had.

    Asking for it under MV2 would be a permission prompt for nothing, and it
    is exactly the sort of surplus scope that draws an AMO reviewer.
    """
    assert "scripting" in manifests.chromium()["permissions"]
    assert "scripting" not in manifests.firefox()["permissions"]


def test_the_background_is_a_persistent_page_on_firefox_and_a_worker_on_chromium():
    ff = manifests.firefox()["background"]
    assert ff["scripts"] == ["background.js"]
    assert ff["persistent"] is True

    cr = manifests.chromium()["background"]
    assert cr["service_worker"] == "background.js"
    assert "scripts" not in cr
    # NOT a module. `compat.js` is welded on at staging time precisely so
    # that `background.js` keeps being parsed as the classic script three
    # phases of live testing were run against.
    assert "type" not in cr


def test_the_shim_loads_before_the_content_script_and_only_on_chromium():
    """Order is load-bearing: `content.js` reads `browser` at top level."""
    cr = manifests.chromium()["content_scripts"][0]["js"]
    assert cr == ["compat.js", "content.js"]

    ff = manifests.firefox()["content_scripts"][0]["js"]
    assert ff == ["content.js"]
    assert "compat.js" not in ff


def test_both_content_scripts_run_in_every_frame():
    """FIELD CORRECTION 2's precondition. Descending into a named subframe
    needs the script to be there; naming frame 0 at the call site is what
    stops an ad iframe answering for the page."""
    for manifest in (manifests.firefox(), manifests.chromium()):
        entry = manifest["content_scripts"][0]
        assert entry["all_frames"] is True
        assert entry["run_at"] == "document_idle"
        assert entry["matches"] == [manifests.ALL_URLS]


def test_the_gecko_id_is_the_one_the_native_host_allowlists():
    """If these two ever disagree the browser cannot reach the relay, and the
    symptom is silence rather than an error."""
    from kitchensink4web.extension import register

    assert manifests.firefox()["browser_specific_settings"]["gecko"]["id"] == \
        manifests.GECKO_ID
    assert register.EXTENSION_ID == manifests.GECKO_ID


def test_the_chromium_manifest_carries_no_gecko_block():
    assert "browser_specific_settings" not in manifests.chromium()


def test_the_data_collection_key_is_present_and_the_version_floor_allows_it():
    """AMO requires the key on new extensions and the key requires 142.

    Both halves are asserted because they are one decision: the key without
    the floor lints at two warnings, and the floor without the key lints at
    one. Moving either alone puts the manifest back in a state web-ext
    complains about.
    """
    gecko = manifests.firefox()["browser_specific_settings"]["gecko"]
    assert "data_collection_permissions" in gecko
    assert gecko["data_collection_permissions"]["required"] == \
        manifests.DATA_COLLECTION_REQUIRED
    assert float(gecko["strict_min_version"].split(".")[0]) >= 142


def test_the_key_pins_the_chromium_id_only_when_given():
    assert "key" not in manifests.chromium()
    assert manifests.chromium(key="AAAB")["key"] == "AAAB"


def test_an_unknown_flavor_is_refused_by_name():
    with pytest.raises(ValueError, match="safari"):
        manifests.build("safari")


def test_the_rendered_manifest_is_json_a_browser_will_take():
    for flavor in manifests.FLAVORS:
        text = manifests.render(flavor)
        assert text.endswith("\n")
        assert json.loads(text) == manifests.build(flavor)


def test_the_version_is_one_number_both_builds_share():
    """A Firefox .xpi and a Chrome package that claim different versions of
    the same extension is a support conversation nobody can win."""
    assert manifests.firefox()["version"] == manifests.chromium()["version"]
    assert manifests.firefox()["version"] == manifests.VERSION
