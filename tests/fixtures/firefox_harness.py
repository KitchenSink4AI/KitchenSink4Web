"""A headless Firefox that loads the extension without a webdriver flag.

The point of the extension architecture is that the page cannot tell it is
being driven, so a validation run that itself sets ``navigator.webdriver``
proves nothing. That rules out ``--remote-debugging-port`` (the Remote Agent,
which serves WebDriver BiDi and flips the flag) and ``--marionette``.

What is left is the old DevTools remote protocol behind
``--start-debugger-server``. It is a length-prefixed JSON protocol, it can
install a temporary add-on, and Phase 1 MEASURES whether it moves
``navigator.webdriver`` rather than assuming it does not: ``probe_webdriver``
launches the same browser with and without the flag and asks a plain page.

Everything here runs hidden: ``-headless``, CREATE_NO_WINDOW, stdin closed,
a scratch profile that is never the user's, and a kill that names its own
process tree.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

FIREFOX_CANDIDATES = [
    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    "/usr/bin/firefox",
    "/Applications/Firefox.app/Contents/MacOS/firefox",
]

PROFILE_PREFS = {
    # The debugger server, and the prompt that would otherwise wait for a
    # human to approve the connection.
    "devtools.debugger.remote-enabled": True,
    "devtools.debugger.prompt-connection": False,
    "devtools.chrome.enabled": True,
    # Everything below exists to make a fresh profile start silently.
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "browser.aboutwelcome.enabled": False,
    "browser.newtabpage.enabled": False,
    "browser.sessionstore.resume_from_crash": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    "datareporting.healthreport.uploadEnabled": False,
    "toolkit.telemetry.enabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "app.update.auto": False,
    "app.update.enabled": False,
    "extensions.update.enabled": False,
    "extensions.autoDisableScopes": 0,
    "signon.rememberSignons": False,
    "browser.tabs.warnOnClose": False,
    "browser.warnOnQuit": False,
    "network.captive-portal-service.enabled": False,
}


def find_firefox() -> str | None:
    for candidate in FIREFOX_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("firefox")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# A page server. Content scripts do not match file:// URLs, so the fixture
# page needs a real http origin.
# ---------------------------------------------------------------------------


class PageServer:
    """Serves one page and collects anything the page reports back."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.reports: "queue.Queue[dict]" = queue.Queue()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path, _, query = self.path.partition("?")
                if path == "/report":
                    fields = {}
                    for pair in query.split("&"):
                        if "=" in pair:
                            key, value = pair.split("=", 1)
                            fields[key] = value
                    outer.reports.put(fields)
                    self.send_response(204)
                    self.end_headers()
                    return
                body = outer.pages.get(path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "PageServer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# The DevTools remote protocol, enough of it to install a temporary add-on.
# ---------------------------------------------------------------------------


class RDPClient:
    """Length-prefixed JSON over TCP: ``<bytes>:<json>``."""

    def __init__(self, port: int, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
                break
            except OSError as exc:
                last = exc
                time.sleep(0.25)
        else:
            raise TimeoutError(f"devtools server never opened on {port}: {last}")
        self._sock.settimeout(30.0)
        self._buffer = b""
        self._greeting = self._read_packet()

    @property
    def greeting(self) -> dict:
        return self._greeting

    def _read_packet(self) -> dict:
        while b":" not in self._buffer:
            self._buffer += self._recv()
        header, _, rest = self._buffer.partition(b":")
        length = int(header)
        self._buffer = rest
        while len(self._buffer) < length:
            self._buffer += self._recv()
        body, self._buffer = self._buffer[:length], self._buffer[length:]
        return json.loads(body.decode("utf-8"))

    def _recv(self) -> bytes:
        piece = self._sock.recv(65536)
        if not piece:
            raise ConnectionError("devtools server closed the connection")
        return piece

    def send(self, packet: dict) -> dict:
        body = json.dumps(packet).encode("utf-8")
        self._sock.sendall(str(len(body)).encode("ascii") + b":" + body)
        # Skip unsolicited notifications; a reply carries the actor we asked.
        target = packet.get("to")
        while True:
            reply = self._read_packet()
            if reply.get("from") == target or "error" in reply:
                return reply

    def install_temporary_addon(self, addon_dir: Path) -> dict:
        root = self.send({"to": "root", "type": "getRoot"})
        actor = root.get("addonsActor")
        if not actor:
            raise RuntimeError(f"devtools root exposed no addonsActor: {sorted(root)}")
        reply = self.send(
            {"to": actor, "type": "installTemporaryAddon", "addonPath": str(addon_dir)}
        )
        if "error" in reply:
            raise RuntimeError(f"installTemporaryAddon failed: {reply}")
        return reply

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The browser itself.
# ---------------------------------------------------------------------------


class HeadlessFirefox:
    """A hidden Firefox on a scratch profile, killed by pid at exit."""

    def __init__(
        self,
        workdir: Path,
        *,
        url: str | None = None,
        debugger_port: int | None = None,
        extra_args: list[str] | None = None,
        binary: str | None = None,
    ) -> None:
        self.binary = binary or find_firefox()
        if not self.binary:
            raise RuntimeError("no Firefox binary found")
        self.workdir = Path(workdir)
        self.profile = self.workdir / "profile"
        self.profile.mkdir(parents=True, exist_ok=True)
        self.debugger_port = debugger_port
        self._write_prefs()

        args = [self.binary, "-headless", "-no-remote", "-profile", str(self.profile)]
        if debugger_port:
            args += ["--start-debugger-server", str(debugger_port)]
        args += list(extra_args or [])
        if url:
            args.append(url)

        self.log_path = self.workdir / "firefox.log"
        self._log = self.log_path.open("wb")
        env = dict(os.environ)
        # Belt and braces on top of -headless: on a machine with a display,
        # this is the setting Firefox itself checks.
        env["MOZ_HEADLESS"] = "1"
        creationflags = CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=env,
        )
        self.args = args

    def _write_prefs(self) -> None:
        prefs = dict(PROFILE_PREFS)
        lines = []
        for key, value in prefs.items():
            lines.append(f"user_pref({json.dumps(key)}, {json.dumps(value)});")
        (self.profile / "user.js").write_text("\n".join(lines) + "\n", encoding="utf-8")

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

    def __enter__(self) -> "HeadlessFirefox":
        return self

    def __exit__(self, *exc: object) -> None:
        self.kill()


# ---------------------------------------------------------------------------
# The webdriver probe: does the load path itself flag the browser?
# ---------------------------------------------------------------------------

PROBE_PAGE = """<!doctype html>
<title>ks4web webdriver probe</title>
<body><h1>probe</h1>
<script>
  fetch('/report?webdriver=' + (navigator.webdriver === true)
        + '&ua=' + encodeURIComponent(navigator.userAgent.slice(0, 40)));
</script>
</body>
"""


def probe_webdriver(workdir: Path, mode: str, timeout: float = 90.0) -> dict:
    """Launch a plain page and ask it what ``navigator.webdriver`` says.

    ``mode`` is ``"plain"``, ``"debugger"`` (``--start-debugger-server``, the
    flag the extension harness uses) or ``"remote"``
    (``--remote-debugging-port``, the one the research says flags the
    browser). Running all three is what turns a claim into a measurement.
    """
    extra: list[str] = []
    debugger_port = None
    if mode == "debugger":
        debugger_port = free_port()
    elif mode == "remote":
        extra = ["--remote-debugging-port", str(free_port())]
    elif mode != "plain":
        raise ValueError(f"unknown probe mode {mode!r}")

    with PageServer({"/": PROBE_PAGE}) as pages:
        browser = HeadlessFirefox(
            workdir,
            url=pages.url("/"),
            debugger_port=debugger_port,
            extra_args=extra,
        )
        try:
            report = pages.reports.get(timeout=timeout)
        finally:
            browser.kill()
    return {
        "mode": mode,
        "webdriver": report.get("webdriver"),
        "args": [a for a in browser.args if not a.endswith("firefox.exe")],
    }


def main() -> int:
    """``python -m`` entry for a quick manual probe of the three modes."""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="ks4web-probe-"))
    try:
        for mode in ("plain", "debugger", "remote"):
            result = probe_webdriver(root / mode, mode)
            print(f"{mode:9s} navigator.webdriver = {result['webdriver']}", file=sys.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
