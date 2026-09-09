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

#: The browsers `--setup-browser` knows how to register with, and where each
#: one looks. Firefox is the lane phases 1 to 3 proved; the Chromium family is
#: phase 4's addition and shares one manifest shape with a different id field.
#:
#: WHAT IS TESTED AND WHAT IS NOT, stated here rather than discovered later.
#: Only the Windows rows have been exercised on real hardware. The POSIX rows
#: are the documented locations, written from the vendor documentation, and
#: they are FILE-TIER: this module can write them and a test can check the
#: bytes, but nobody here has watched a Linux Firefox launch the relay. That
#: distinction is reported by `describe()` so a user on a Mac is told they are
#: the first rather than left to find out.
BROWSERS: dict[str, dict] = {
    "firefox": {
        "family": "gecko",
        # HKCU\Software\Mozilla\NativeMessagingHosts\<host>
        "registry": r"Software\Mozilla\NativeMessagingHosts",
        "linux": ".mozilla/native-messaging-hosts",
        "macos": "Mozilla/NativeMessagingHosts",
        "tested": ("windows",),
    },
    "chrome": {
        "family": "chromium",
        "registry": r"Software\Google\Chrome\NativeMessagingHosts",
        "linux": ".config/google-chrome/NativeMessagingHosts",
        "macos": "Google/Chrome/NativeMessagingHosts",
        "tested": (),
    },
    "chromium": {
        "family": "chromium",
        "registry": r"Software\Chromium\NativeMessagingHosts",
        "linux": ".config/chromium/NativeMessagingHosts",
        "macos": "Chromium/NativeMessagingHosts",
        "tested": (),
    },
    "edge": {
        "family": "chromium",
        "registry": r"Software\Microsoft\Edge\NativeMessagingHosts",
        "linux": ".config/microsoft-edge/NativeMessagingHosts",
        "macos": "Microsoft Edge/NativeMessagingHosts",
        "tested": (),
    },
}


def registry_parent(browser: str = "firefox") -> str:
    """The HKCU subkey a browser reads its native messaging hosts from."""
    try:
        return BROWSERS[browser]["registry"]
    except KeyError:
        raise ValueError(
            f"unknown browser {browser!r}; expected one of {sorted(BROWSERS)}"
        ) from None


def manifest_dir(browser: str = "firefox") -> Path:
    """Where the host manifest belongs on this platform.

    On Windows the manifest can live anywhere and the registry points at it,
    so this returns the per-user application directory we choose. On Linux and
    macOS there is no registry and the FILENAME AND DIRECTORY ARE THE
    REGISTRATION: the browser scans a fixed directory for ``<host>.json``.
    That is the whole platform difference and it is why `install` takes a
    different route on each.
    """
    spec = BROWSERS.get(browser)
    if spec is None:
        raise ValueError(
            f"unknown browser {browser!r}; expected one of {sorted(BROWSERS)}"
        )
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / spec["macos"]
    if os.name == "nt":
        return _windows_app_dir()
    return home / spec["linux"]


def _windows_app_dir() -> Path:
    """Our own per-user directory for the wrapper and the host manifest."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "KitchenSink4Web"


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


def write_shell_wrapper(
    path: Path,
    *,
    python_executable: str | None = None,
    src_dir: Path | None = None,
    endpoint: Path | None = None,
) -> Path:
    """The POSIX counterpart of the ``.bat``, for Linux and macOS.

    Same three jobs: name the interpreter, carry configuration as environment
    rather than arguments, and keep ``-u`` on. FILE-TIER -- the bytes are
    tested, a real Linux Firefox launching this has not been observed here.
    """
    python_executable = python_executable or sys.executable
    lines = ["#!/bin/sh"]
    if src_dir is not None:
        lines.append(f'PYTHONPATH="{src_dir}"; export PYTHONPATH')
    if endpoint is not None:
        lines.append(f'KS4WEB_EXTENSION_ENDPOINT="{endpoint}"; '
                     "export KS4WEB_EXTENSION_ENDPOINT")
    lines.append(f'exec "{python_executable}" -u -m kitchensink4web.extension.relay "$@"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def write_wrapper(
    directory: Path,
    *,
    host_name: str = HOST_NAME,
    python_executable: str | None = None,
    src_dir: Path | None = None,
    endpoint: Path | None = None,
) -> Path:
    """The wrapper this platform needs, under the name it needs."""
    if os.name == "nt":
        return write_batch_wrapper(
            directory / f"{host_name}_relay.bat",
            python_executable=python_executable,
            src_dir=src_dir, endpoint=endpoint,
        )
    return write_shell_wrapper(
        directory / f"{host_name}_relay.sh",
        python_executable=python_executable,
        src_dir=src_dir, endpoint=endpoint,
    )


def write_host_manifest(
    path: Path,
    *,
    executable: Path,
    host_name: str = HOST_NAME,
    extension_id: str = EXTENSION_ID,
    browser: str = "firefox",
) -> Path:
    """Write the native messaging host manifest.

    The one field that differs across the two browser families is how the
    caller is named. Firefox lists add-on ids in ``allowed_extensions``;
    Chrome lists ORIGINS in ``allowed_origins``, spelled
    ``chrome-extension://<id>/`` with the trailing slash, and a manifest
    carrying the wrong one of those two keys is silently ignored rather than
    rejected with a reason. That is the whole difference, and getting it
    wrong looks exactly like the host not being registered at all.
    """
    family = BROWSERS.get(browser, {}).get("family", "gecko")
    manifest = {
        "name": host_name,
        "description": "[COPY PENDING] native messaging host description",
        "path": str(executable),
        "type": "stdio",
    }
    if family == "chromium":
        manifest["allowed_origins"] = [f"chrome-extension://{extension_id}/"]
    else:
        manifest["allowed_extensions"] = [extension_id]
    path.parent.mkdir(parents=True, exist_ok=True)
    # json.dump escapes the backslashes, which is exactly what the format
    # wants; hand-written manifests are where the single-backslash bug lives.
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def register_windows(manifest_path: Path, *, host_name: str = HOST_NAME,
                     browser: str = "firefox") -> str:
    """Point HKCU at the manifest. Returns the key that was written."""
    if os.name != "nt":
        raise RuntimeError("registry registration is Windows-only")
    import winreg

    key_path = f"{registry_parent(browser)}\\{host_name}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    return f"HKEY_CURRENT_USER\\{key_path}"


def read_registration(host_name: str = HOST_NAME,
                      browser: str = "firefox") -> str | None:
    """What the browser will find, or ``None`` if there is nothing registered.

    On Windows that is the registry value. On Linux and macOS there is no
    registry and the answer is whether the file exists in the scanned
    directory, which is the same question asked of a different oracle.
    """
    if os.name != "nt":
        candidate = manifest_dir(browser) / f"{host_name}.json"
        return str(candidate) if candidate.is_file() else None
    import winreg

    key_path = f"{registry_parent(browser)}\\{host_name}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, "")
            return value
    except FileNotFoundError:
        return None


def unregister_windows(host_name: str = HOST_NAME,
                       browser: str = "firefox") -> bool:
    """Remove the registry key. Returns whether there was one to remove."""
    if os.name != "nt":
        return False
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                         f"{registry_parent(browser)}\\{host_name}")
        return True
    except FileNotFoundError:
        return False


def describe(browser: str = "firefox") -> dict:
    """Where this browser's registration lives on this machine, and whether
    anybody has ever watched it work here."""
    spec = BROWSERS.get(browser)
    if spec is None:
        raise ValueError(
            f"unknown browser {browser!r}; expected one of {sorted(BROWSERS)}"
        )
    platform = ("windows" if os.name == "nt"
                else "macos" if sys.platform == "darwin" else "linux")
    return {
        "browser": browser,
        "family": spec["family"],
        "platform": platform,
        "mechanism": "registry" if platform == "windows" else "manifest directory",
        "location": (f"HKEY_CURRENT_USER\\{spec['registry']}\\{HOST_NAME}"
                     if platform == "windows"
                     else str(manifest_dir(browser) / f"{HOST_NAME}.json")),
        # The honesty field. `False` does not mean broken, it means untested
        # here, and the two are different claims.
        "proven_on_this_platform": platform in spec["tested"],
    }


def install(
    target_dir: Path,
    *,
    host_name: str = HOST_NAME,
    extension_id: str = EXTENSION_ID,
    python_executable: str | None = None,
    src_dir: Path | None = None,
    endpoint: Path | None = None,
    touch_registry: bool = True,
    browser: str = "firefox",
) -> dict:
    """Write all three artefacts and report exactly what was written.

    The Windows signature is phase 1's, unchanged, because phase 1 proved it
    and a proven path should not move to make room for an unproven one. What
    is new is ``browser`` and the POSIX route: on Linux and macOS the host
    manifest must be written INTO the directory the browser scans, so
    ``target_dir`` holds the wrapper and the manifest goes where the platform
    demands.
    """
    target_dir = Path(target_dir)
    wrapper = write_wrapper(
        target_dir,
        host_name=host_name,
        python_executable=python_executable,
        src_dir=src_dir,
        endpoint=endpoint,
    )
    if os.name == "nt":
        manifest_at = target_dir / f"{host_name}.json"
    else:
        manifest_at = manifest_dir(browser) / f"{host_name}.json"
    manifest = write_host_manifest(
        manifest_at,
        executable=wrapper,
        host_name=host_name,
        extension_id=extension_id,
        browser=browser,
    )
    registry_key = None
    if touch_registry and os.name == "nt":
        registry_key = register_windows(manifest, host_name=host_name,
                                        browser=browser)
    return {
        "host_name": host_name,
        "browser": browser,
        # `batch` is phase 1's key and callers use it; `wrapper` is the name
        # that is true on every platform. Both, so nothing breaks and nothing
        # lies.
        "batch": str(wrapper),
        "wrapper": str(wrapper),
        "manifest": str(manifest),
        "registry_key": registry_key,
        "extension_id": extension_id,
    }


def uninstall(
    target_dir: Path | None = None,
    *,
    host_name: str = HOST_NAME,
    browser: str = "firefox",
) -> dict:
    """Undo `install`, and report each piece separately.

    Every removal is reported as its own boolean rather than rolled into one
    success flag. A cleanup that removed the registry key and left the
    manifest behind is a different state from one that removed both, and a
    user chasing "why is it still connecting?" needs to be told which.
    Nothing here raises when a piece is already gone: removing twice is the
    normal case after a partial failure.
    """
    removed = {"registry_key": False, "manifest": False, "wrapper": False}
    manifest_path = read_registration(host_name, browser) if os.name == "nt" else None

    if os.name == "nt":
        removed["registry_key"] = unregister_windows(host_name, browser=browser)
        candidates = []
        if manifest_path:
            candidates.append(Path(manifest_path))
        if target_dir is not None:
            candidates.append(Path(target_dir) / f"{host_name}.json")
        candidates.append(_windows_app_dir() / f"{host_name}.json")
    else:
        candidates = [manifest_dir(browser) / f"{host_name}.json"]
        if target_dir is not None:
            candidates.append(Path(target_dir) / f"{host_name}.json")

    for candidate in candidates:
        if candidate.is_file():
            candidate.unlink()
            removed["manifest"] = True

    wrapper_dirs = [Path(target_dir)] if target_dir is not None else []
    if os.name == "nt":
        wrapper_dirs.append(_windows_app_dir())
    else:
        wrapper_dirs.append(Path.home() / ".local" / "share" / "KitchenSink4Web")
    for directory in wrapper_dirs:
        for name in (f"{host_name}_relay.bat", f"{host_name}_relay.sh"):
            candidate = directory / name
            if candidate.is_file():
                candidate.unlink()
                removed["wrapper"] = True

    return {"host_name": host_name, "browser": browser, "removed": removed}
