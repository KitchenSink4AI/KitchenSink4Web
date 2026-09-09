"""A hidden Chromium with the MV3 build loaded, and no debugging port.

The Firefox harness loads its add-on over the DevTools protocol because
Firefox has no command-line flag for it. Chromium does: ``--load-extension``
takes a directory, and the whole point of using it is that it is not a
debugging port. Phase 1 measured `navigator.webdriver` true under Firefox's
``--remote-debugging-port`` and false under ``--start-debugger-server``; the
equivalent question on this side is what ``--load-extension`` alone costs, and
the brief says measure rather than assume.

HOW THE MEASUREMENT IS TAKEN, because it decides the harness's shape. Reading
`navigator.webdriver` from Python would normally mean attaching CDP, which is
the exact thing whose absence is being measured: the answer would then be
about the probe. So the fixture page reads the flag with its OWN inline script
and writes it into the DOM, and the value travels back through the extension's
ordinary `page.read`. Nothing observes the browser except the extension that
is meant to be there.

Everything runs hidden, on a scratch profile, killed by pid tree at exit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

#: EDGE FIRST ON WINDOWS, and the ordering is a measurement rather than a
#: preference. Chrome 152 IGNORES ``--load-extension`` outright: the browser
#: starts, runs, serves pages, and simply never loads the directory, with
#: nothing in the log saying so. Adding
#: ``--disable-features=DisableLoadExtensionCommandLineSwitch``, which is the
#: documented escape for the Chrome 137 restriction, changes nothing on 152.
#: Edge on the same machine loads the same directory with no flags at all.
#:
#: This affects TESTING, not users. A person installing the extension uses
#: "Load unpacked" in the extensions page or installs a packed build, and
#: neither route goes through the command line. But it means a Chromium smoke
#: test on this machine has to run on Edge, and it means nobody should read a
#: green MV3 result as "tested on Chrome".
_WINDOWS_CANDIDATES = (
    (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "edge"),
    (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "edge"),
    (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "chrome"),
    (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "chrome"),
)
_PATH_CANDIDATES = (
    ("microsoft-edge", "edge"),
    ("chromium", "chromium"),
    ("chromium-browser", "chromium"),
    ("google-chrome", "chrome"),
)


def find_chromium() -> tuple[str, str] | None:
    """``(path, browser)`` for the first Chromium-family browser found.

    The second element is the key `register.BROWSERS` uses, because Chrome
    and Edge read DIFFERENT registry parents for native messaging hosts and a
    host registered under the wrong one is simply never found.
    """
    if os.name == "nt":
        for path, kind in _WINDOWS_CANDIDATES:
            if Path(path).is_file():
                return path, kind
    for name, kind in _PATH_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found, kind
    return None


class HeadlessChromium:
    """A hidden Chromium with one unpacked extension and nothing else."""

    def __init__(
        self,
        workdir: Path,
        extension_dir: Path,
        *,
        url: str | None = None,
        binary: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        found = (binary, "chrome") if binary else find_chromium()
        if not found:
            raise RuntimeError("no Chromium-family browser found")
        self.binary, self.browser = found
        self.workdir = Path(workdir)
        self.profile = self.workdir / "profile"
        self.profile.mkdir(parents=True, exist_ok=True)
        self.extension_dir = Path(extension_dir)

        args = [
            self.binary,
            # `=new` explicitly. Old headless could not run extensions at
            # all, and a silent fall back to it would look like the
            # extension failing rather than the mode being wrong.
            "--headless=new",
            f"--user-data-dir={self.profile}",
            f"--load-extension={self.extension_dir}",
            f"--disable-extensions-except={self.extension_dir}",
            # NO --remote-debugging-port. That is the whole experiment.
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--password-store=basic",
            "--use-mock-keychain",
            # Headless Chrome throttles or skips work in windows it thinks
            # nobody can see, which would make an extension's timing here
            # unlike an extension's timing on a desk.
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ]
        args += list(extra_args or [])
        if url:
            args.append(url)

        self.log_path = self.workdir / "chromium.log"
        self._log = self.log_path.open("wb")
        creationflags = CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self.args = args

    def observed_extension_id(self) -> str | None:
        """The id Chromium actually gave the unpacked extension.

        Read out of the profile rather than asked of the extension, because
        asking requires the native port and the native port requires the id
        to already be right. This is the independent check on the derivation
        in `artifact.unpacked_chromium_id`, and it is the only way to tell a
        wrong id apart from a broken connection.
        """
        for name in ("Default/Preferences", "Default/Secure Preferences"):
            path = self.profile / name
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            settings = (data.get("extensions") or {}).get("settings") or {}
            wanted = str(self.extension_dir).replace("/", "\\").lower()
            for ext_id, entry in settings.items():
                where = str(entry.get("path", "")).replace("/", "\\").lower()
                if where and (where == wanted or wanted.endswith(where)):
                    return ext_id
            # A profile with exactly one extension in it, which is what
            # `--disable-extensions-except` produces, needs no matching.
            if len(settings) == 1:
                return next(iter(settings))
        return None

    def kill(self, timeout: float = 10.0) -> None:
        """Kill this process tree and nothing else on the machine."""
        if self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=timeout,
                    check=False,
                )
            else:
                self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
        try:
            self._log.close()
        except OSError:
            pass

    def __enter__(self) -> "HeadlessChromium":
        return self

    def __exit__(self, *exc) -> None:
        self.kill()
