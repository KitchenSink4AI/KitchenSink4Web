"""The native messaging host: the process Firefox launches.

It does two things and nothing else. Frames arriving on stdin from the
extension are validated as responses and written to the bridge socket as
lines; lines arriving from the bridge are validated as commands and written
to stdout as frames.

Three properties matter more than the code:

1. It imports only the standard library. Firefox launches this in an
   environment nobody configured for it, and a missing dependency here shows
   up as a native messaging disconnect with no diagnosis attached.

2. It takes stdout away from the rest of the process on the first line of
   ``main``. Anything else that writes to stdout corrupts the next length
   prefix, and Firefox then reports a size error naming a number that came
   out of the middle of a Python string.

3. It keeps no memory of what it has forwarded. The browser can start and
   kill this process at will, so any state it accumulated would be state the
   system loses without noticing. Chunk reassembly lives in the bridge for
   that reason.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # launched as a bare script by a .bat wrapper
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from kitchensink4web.extension import bridge as bridge_mod
    from kitchensink4web.extension import framing, protocol
else:
    from . import bridge as bridge_mod
    from . import framing, protocol

CONNECT_TIMEOUT = 20.0
CONNECT_INTERVAL = 0.25


def _log_path() -> Path:
    return bridge_mod.default_state_dir() / "relay.log"


def _log(message: str) -> None:
    """Diagnostics go to a file. Never to stdout, and never to stderr either.

    Firefox captures the host's stderr into the browser console, which is
    useful right up until a long-running relay fills it. The file is the
    thing a support request can actually attach.
    """
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} [{os.getpid()}] {message}\n")
    except OSError:
        pass


def _claim_stdio() -> tuple[object, object]:
    """Take the real stdin/stdout as binary streams and blind the process.

    Returns the pair the relay will use. After this call ``sys.stdout`` no
    longer points at the pipe, so a stray print goes nowhere instead of
    corrupting a frame.
    """
    stdin_fd = os.dup(0)
    stdout_fd = os.dup(1)
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(stdin_fd, os.O_BINARY)
        msvcrt.setmode(stdout_fd, os.O_BINARY)
    reader = os.fdopen(stdin_fd, "rb", buffering=0)
    writer = os.fdopen(stdout_fd, "wb", buffering=0)

    devnull = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = devnull
    return reader, writer


def _connect_bridge(endpoint_path: Path, timeout: float = CONNECT_TIMEOUT):
    """Dial the running server, waiting for it to publish its endpoint."""
    deadline = time.monotonic() + timeout
    last_error = "endpoint file never appeared"
    while time.monotonic() < deadline:
        try:
            info = json.loads(endpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            last_error = f"endpoint unreadable: {exc}"
            time.sleep(CONNECT_INTERVAL)
            continue
        try:
            conn = socket.create_connection((info["host"], info["port"]), timeout=5.0)
        except OSError as exc:
            last_error = f"connect refused: {exc}"
            time.sleep(CONNECT_INTERVAL)
            continue
        conn_file = conn.makefile("rwb")
        hello = {"hello": "ks4web-relay", "token": info["token"], "pid": os.getpid()}
        conn_file.write(json.dumps(hello).encode("utf-8") + b"\n")
        conn_file.flush()
        ack_line = conn_file.readline()
        try:
            ack = json.loads(ack_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            ack = {"ok": False, "reason": "unparseable handshake reply"}
        if not ack.get("ok"):
            conn.close()
            raise ConnectionRefusedError(f"bridge refused the relay: {ack.get('reason')}")
        return conn, conn_file
    raise TimeoutError(f"no bridge within {timeout}s ({last_error})")


def _pump_browser_to_bridge(reader, conn_file, stop: threading.Event) -> None:
    """stdin frames (responses from the extension) -> bridge lines."""
    while not stop.is_set():
        try:
            message = framing.read_message(reader)
        except framing.FramingError as exc:
            if exc.recoverable:
                # The frame was whole, its contents were not. The reader is
                # still sitting on the next length prefix, so drop this one
                # and keep going: one bad message must not cost the session.
                _log(f"dropping unparseable frame from browser: {exc}")
                continue
            _log(f"stream desynced, hanging up: {exc}")
            break
        if message is None:
            _log("browser closed the native messaging pipe")
            break
        try:
            protocol.validate_response(message)
        except protocol.ProtocolError as exc:
            # Refused at the boundary, with the reason recorded. The
            # alternative is forwarding it inward to fail somewhere that
            # knows less about where it came from.
            _log(f"refusing malformed response: {exc}")
            continue
        try:
            conn_file.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
            conn_file.flush()
        except OSError as exc:
            _log(f"bridge write failed: {exc}")
            break
    stop.set()


def _pump_bridge_to_browser(conn_file, writer, stop: threading.Event) -> None:
    """bridge lines (commands from the server) -> stdout frames."""
    while not stop.is_set():
        try:
            line = conn_file.readline()
        except OSError as exc:
            _log(f"bridge read failed: {exc}")
            break
        if not line:
            _log("bridge closed the loopback connection")
            break
        if not line.strip():
            continue
        try:
            message = json.loads(line.decode("utf-8"))
            protocol.validate_command(message)
        except (UnicodeDecodeError, json.JSONDecodeError, protocol.ProtocolError) as exc:
            _log(f"refusing malformed command: {exc}")
            continue
        try:
            framing.write_message(writer, message)
        except OSError as exc:
            _log(f"browser write failed: {exc}")
            break
    stop.set()


def main(argv: list[str] | None = None) -> int:
    reader, writer = _claim_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Firefox passes the extension's origin (and on Windows the addon id) as
    # positional arguments. They are recorded, not parsed: the allowlist that
    # actually gates who may talk to this process is allowed_extensions in
    # the native host manifest, enforced by the browser before launch.
    endpoint = None
    for index, arg in enumerate(argv):
        if arg == "--endpoint" and index + 1 < len(argv):
            endpoint = Path(argv[index + 1])
    if endpoint is None:
        env_endpoint = os.environ.get("KS4WEB_EXTENSION_ENDPOINT")
        endpoint = Path(env_endpoint) if env_endpoint else (
            bridge_mod.default_state_dir() / bridge_mod.DEFAULT_ENDPOINT_NAME
        )

    _log(f"relay start: args={argv} endpoint={endpoint}")
    try:
        conn, conn_file = _connect_bridge(endpoint)
    except (OSError, TimeoutError) as exc:
        # Exiting is the correct move. The port drops, the background script
        # backs off and reconnects, and the browser launches a fresh relay
        # that gets another chance at a server which may by then be running.
        _log(f"no bridge, exiting so the extension can retry: {exc}")
        return 1

    _log("bridge connected")
    stop = threading.Event()
    up = threading.Thread(target=_pump_browser_to_bridge, args=(reader, conn_file, stop), daemon=True)
    down = threading.Thread(target=_pump_bridge_to_browser, args=(conn_file, writer, stop), daemon=True)
    up.start()
    down.start()
    try:
        while not stop.wait(0.2):
            pass
    except KeyboardInterrupt:
        stop.set()
    try:
        conn.close()
    except OSError:
        pass
    _log("relay exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
