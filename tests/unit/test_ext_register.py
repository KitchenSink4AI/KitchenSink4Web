"""Native messaging host registration, artefact by artefact.

The registry half runs against a host name no shipped build uses and deletes
itself afterwards, so a test run never leaves a key pointing at a path that
no longer exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kitchensink4web.extension import register

TEST_HOST = "ks4web_unittest_host"


def test_the_batch_wrapper_carries_the_unbuffered_flag(tmp_path):
    # -u is not decoration. Buffered stdout detaches the 4-byte length prefix
    # from its body and Firefox reports a size error naming a number that
    # came out of the middle of a string.
    path = register.write_batch_wrapper(tmp_path / "w.bat", python_executable=r"C:\py\python.exe")
    text = path.read_text(encoding="utf-8")
    assert " -u " in text
    assert "kitchensink4web.extension.relay" in text
    assert "%*" in text


def test_the_batch_wrapper_passes_the_dev_paths_as_environment(tmp_path):
    path = register.write_batch_wrapper(
        tmp_path / "w.bat",
        python_executable="python.exe",
        src_dir=Path(r"C:\repo\src"),
        endpoint=Path(r"C:\state\endpoint.json"),
    )
    text = path.read_text(encoding="utf-8")
    assert 'set "PYTHONPATH=C:\\repo\\src"' in text
    assert 'set "KS4WEB_EXTENSION_ENDPOINT=C:\\state\\endpoint.json"' in text
    # They travel as environment because Firefox appends its own positional
    # arguments and anything we add has to share the line with them.
    assert text.index("PYTHONPATH") < text.index("%*")


def test_the_batch_wrapper_omits_what_it_was_not_given(tmp_path):
    text = register.write_batch_wrapper(tmp_path / "w.bat").read_text(encoding="utf-8")
    assert "PYTHONPATH" not in text
    assert "KS4WEB_EXTENSION_ENDPOINT" not in text


def test_the_host_manifest_has_the_four_fields_firefox_reads(tmp_path):
    path = register.write_host_manifest(tmp_path / "h.json", executable=tmp_path / "w.bat")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["name"] == register.HOST_NAME
    assert manifest["type"] == "stdio"
    assert manifest["path"] == str(tmp_path / "w.bat")
    assert manifest["allowed_extensions"] == [register.EXTENSION_ID]


def test_the_manifest_escapes_windows_separators(tmp_path):
    path = register.write_host_manifest(tmp_path / "h.json", executable=Path(r"C:\a b\w.bat"))
    raw = path.read_text(encoding="utf-8")
    if os.name == "nt":
        # The single-backslash manifest is the classic Windows bug. Going
        # through json.dumps is what prevents it, and this is the assertion
        # that would catch somebody hand-formatting it later.
        assert r"C:\\a b\\w.bat" in raw
    assert json.loads(raw)["path"] == r"C:\a b\w.bat"


def test_the_allowlist_names_exactly_one_extension(tmp_path):
    manifest = json.loads(
        register.write_host_manifest(
            tmp_path / "h.json", executable=tmp_path / "w.bat", extension_id="only@example.org"
        ).read_text(encoding="utf-8")
    )
    assert manifest["allowed_extensions"] == ["only@example.org"]


def test_install_without_touching_the_registry_still_writes_both_files(tmp_path):
    result = register.install(tmp_path / "host", host_name=TEST_HOST, touch_registry=False)
    assert Path(result["batch"]).exists()
    assert Path(result["manifest"]).exists()
    assert result["registry_key"] is None


@pytest.mark.skipif(os.name != "nt", reason="the registry only exists on Windows")
def test_registration_writes_a_key_firefox_can_read_and_removes_it_again(tmp_path):
    assert register.read_registration(TEST_HOST) is None
    result = register.install(tmp_path / "host", host_name=TEST_HOST)
    try:
        assert result["registry_key"].endswith(f"NativeMessagingHosts\\{TEST_HOST}")
        assert register.read_registration(TEST_HOST) == result["manifest"]
    finally:
        assert register.unregister_windows(TEST_HOST) is True
    assert register.read_registration(TEST_HOST) is None
    # Removing what is not there is a no-op that says so, not an exception.
    assert register.unregister_windows(TEST_HOST) is False
