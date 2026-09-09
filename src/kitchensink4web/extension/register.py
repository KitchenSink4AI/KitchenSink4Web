"""Registering the native messaging host with Firefox.

Three artefacts, in this order, and the order matters because Firefox reads
them in it:

1. A ``.bat`` wrapper. Windows needs one: the manifest's ``path`` must point
   at something the shell can execute, and pointing it straight at a ``.py``
   file depends on the file association being intact. The wrapper also
   carries the ``-u`` flag, which is not optional -- buffered stdio corrupts
   the length prefixes.
2. A native host manifest JSON naming that wrapper and the one extension id
   allowed to launch it.
3. A registry value under ``HKCU\\Software\\Mozilla\\NativeMessagingHosts``
   whose default value is the path to that manifest.

This module is the Phase 1 core of what Phase 4 will expose as
``kitchensink4web --setup-browser``. It uses no third-party package: the
``nativemessaging-ng`` route the research suggested would add a dependency
for about twenty lines of ``winreg``, and it does not handle the 32-bit
registry view question (Bugzilla 1494709) any better than doing it here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOST_NAME = "ks4web"
EXTENSION_ID = "web@kitchensink4.ai"
REGISTRY_PARENT = r"Software\Mozilla\NativeMessagingHosts"


def write_batch_wrapper(
    path: Path,
    *,
    python_executable: str | None = None,
    src_dir: Path | None = None,
    endpoint: Path | None = None,
) -> Path:
    """Write the ``.bat`` Firefox will execute.

    ``src_dir`` exists for development, where the package is not installed
    into the interpreter that will run the relay. A shipped install leaves it
    unset and relies on the console-script interpreter. ``endpoint`` moves the
    bridge's address off the default path, which the validation run needs so
    that a test never dials a server the author is actually using.

    Both travel as environment variables rather than arguments, because
    Firefox appends its own positional arguments (the manifest path and the
    calling extension) and anything we add has to survive sharing the line
    with them.
    """
    python_executable = python_executable or sys.executable
    lines = ["@echo off", "setlocal"]
    if src_dir is not None:
        lines.append(f'set "PYTHONPATH={src_dir}"')
    if endpoint is not None:
        lines.append(f'set "KS4WEB_EXTENSION_ENDPOINT={endpoint}"')
    # -u is load-bearing: without it Windows buffers stdout and the 4-byte
    # length prefix arrives detached from its body.
    lines.append(f'"{python_executable}" -u -m kitchensink4web.extension.relay %*')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def write_host_manifest(
    path: Path,
    *,
    executable: Path,
    host_name: str = HOST_NAME,
    extension_id: str = EXTENSION_ID,
) -> Path:
    """Write the native messaging host manifest."""
    manifest = {
        "name": host_name,
        "description": "[COPY PENDING] native messaging host description",
        "path": str(executable),
        "type": "stdio",
        "allowed_extensions": [extension_id],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # json.dump escapes the backslashes, which is exactly what the format
    # wants; hand-written manifests are where the single-backslash bug lives.
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def register_windows(manifest_path: Path, *, host_name: str = HOST_NAME) -> str:
    """Point HKCU at the manifest. Returns the key that was written."""
    if os.name != "nt":
        raise RuntimeError("registry registration is Windows-only")
    import winreg

    key_path = f"{REGISTRY_PARENT}\\{host_name}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    return f"HKEY_CURRENT_USER\\{key_path}"


def read_registration(host_name: str = HOST_NAME) -> str | None:
    """What Firefox will find, or ``None`` if there is nothing registered."""
    if os.name != "nt":
        return None
    import winreg

    key_path = f"{REGISTRY_PARENT}\\{host_name}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, "")
            return value
    except FileNotFoundError:
        return None


def unregister_windows(host_name: str = HOST_NAME) -> bool:
    """Remove the registry key. Returns whether there was one to remove."""
    if os.name != "nt":
        return False
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{REGISTRY_PARENT}\\{host_name}")
        return True
    except FileNotFoundError:
        return False


def install(
    target_dir: Path,
    *,
    host_name: str = HOST_NAME,
    extension_id: str = EXTENSION_ID,
    python_executable: str | None = None,
    src_dir: Path | None = None,
    endpoint: Path | None = None,
    touch_registry: bool = True,
) -> dict:
    """Write all three artefacts and report exactly what was written."""
    target_dir = Path(target_dir)
    batch = write_batch_wrapper(
        target_dir / f"{host_name}_relay.bat",
        python_executable=python_executable,
        src_dir=src_dir,
        endpoint=endpoint,
    )
    manifest = write_host_manifest(
        target_dir / f"{host_name}.json",
        executable=batch,
        host_name=host_name,
        extension_id=extension_id,
    )
    registry_key = None
    if touch_registry and os.name == "nt":
        registry_key = register_windows(manifest, host_name=host_name)
    return {
        "host_name": host_name,
        "batch": str(batch),
        "manifest": str(manifest),
        "registry_key": registry_key,
        "extension_id": extension_id,
    }
