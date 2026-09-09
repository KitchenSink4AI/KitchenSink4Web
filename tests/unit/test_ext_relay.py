"""The relay and the bridge, with a mock extension standing in for Firefox.

No browser here. The relay is launched exactly the way Firefox launches it,
as a subprocess whose stdin and stdout are pipes, and the test plays the
extension on the far end of those pipes. That covers the whole Python path
including the framing, the loopback handshake and the chunk reassembly, and
it runs in a second.

Everything spawned is hidden and killed by pid.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kitchensink4web.extension import framing
from kitchensink4web.extension.bridge import Bridge, BridgeError, NoBrowserConnected

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class MockExtension:
    """Speaks native messaging on the relay's pipes and answers commands."""

    def __init__(self, endpoint: Path) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env["KS4WEB_EXTENSION_ENDPOINT"] = str(endpoint)
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "kitchensink4web.extension.relay"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        self.received: list[dict] = []
        self.handler = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                command = framing.read_message(self.process.stdout)
            except (framing.FramingError, ValueError, OSError):
                return
            if command is None:
                return
            self.received.append(command)
            if self.handler is None:
                continue
            for reply in self.handler(command):
                try:
                    framing.write_message(self.process.stdin, reply)
                except (OSError, ValueError):
                    return

    def send_raw_frame(self, payload: bytes) -> None:
        """Write bytes onto the pipe without going through the encoder."""
        self.process.stdin.write(struct.pack("@I", len(payload)) + payload)
        self.process.stdin.flush()

    def close(self) -> None:
        self._stop.set()
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass


@pytest.fixture
def wired(tmp_path):
    """A bridge with a relay attached and a mock extension on the far side."""
    bridge = Bridge(endpoint_path=tmp_path / "endpoint.json")
    extension = MockExtension(tmp_path / "endpoint.json")
    try:
        assert bridge.wait_for_browser(30.0), "the relay never dialled the bridge"
        yield bridge, extension
    finally:
        extension.close()
        bridge.close()


def echo_handler(command):
    yield {"id": command["id"], "result": {"echoed": command["method"], "params": command["params"]}}


# -- the round trip ---------------------------------------------------------


def test_a_command_reaches_the_extension_and_its_answer_comes_back(wired):
    bridge, extension = wired
    extension.handler = echo_handler
    result = bridge.request("page.read", {"budget": 5000}, timeout=20.0)
    assert result == {"echoed": "page.read", "params": {"budget": 5000}}
    assert extension.received[-1]["method"] == "page.read"


def test_ids_are_distinct_and_answers_match_their_own_command(wired):
    bridge, extension = wired
    extension.handler = echo_handler
    first = bridge.request("bg.ping", {"n": 1}, timeout=20.0)
    second = bridge.request("bg.ping", {"n": 2}, timeout=20.0)
    assert first["params"]["n"] == 1
    assert second["params"]["n"] == 2
    assert extension.received[0]["id"] != extension.received[1]["id"]


def test_an_error_response_raises_carrying_the_extensions_own_words(wired):
    bridge, extension = wired
    extension.handler = lambda c: [
        {"id": c["id"], "error": {"code": "NOT_FOUND", "message": "no such element"}}
    ]
    with pytest.raises(BridgeError) as caught:
        bridge.request("page.read", timeout=20.0)
    assert "NOT_FOUND" in str(caught.value)
    assert "no such element" in str(caught.value)


def test_a_chunked_response_arrives_as_one_whole_result(wired):
    bridge, extension = wired
    payload = {"text": "z" * 40000, "chars": 40000}

    def chunker(command):
        text = json.dumps(payload)
        size = 4096
        pieces = [text[i : i + size] for i in range(0, len(text), size)]
        for seq, data in enumerate(pieces):
            yield {"id": command["id"], "chunk": {"seq": seq, "total": len(pieces), "data": data}}

    extension.handler = chunker
    assert bridge.request("page.read", timeout=30.0) == payload


def test_a_large_single_frame_survives_the_whole_path(wired):
    # One megabyte in the extension -> server direction, unchunked. The
    # documented ceiling that way is 4 GB and the live run cleared 64 MB;
    # this pins the Python half of that at a size the old 1 MB folklore says
    # should hurt.
    bridge, extension = wired
    blob = "q" * (1024 * 1024)
    extension.handler = lambda c: [{"id": c["id"], "result": {"blob": blob}}]
    assert bridge.request("page.read", timeout=60.0)["blob"] == blob


def test_a_slow_extension_times_out_rather_than_hanging(wired):
    bridge, extension = wired
    extension.handler = lambda c: []
    with pytest.raises(TimeoutError):
        bridge.request("page.read", timeout=1.0)


# -- refusals, both directions ---------------------------------------------


def test_the_relay_refuses_a_malformed_response_instead_of_forwarding_it(wired):
    bridge, extension = wired

    def bad_then_good(command):
        # A response with neither result nor error is not a response. The
        # relay must drop it at the boundary; the second frame proves the
        # relay is still alive and still forwarding valid traffic.
        yield {"id": command["id"], "nonsense": True}
        yield {"id": command["id"], "result": {"recovered": True}}

    extension.handler = bad_then_good
    assert bridge.request("page.read", timeout=20.0) == {"recovered": True}


def test_the_relay_survives_a_frame_that_is_not_json(wired):
    bridge, extension = wired
    extension.handler = echo_handler
    extension.send_raw_frame(b"<html>this is not json</html>")
    time.sleep(0.3)
    # A garbage frame corrupts nothing that follows it.
    assert bridge.request("bg.ping", timeout=20.0)["echoed"] == "bg.ping"


def test_a_command_with_no_browser_is_refused_not_queued(tmp_path):
    bridge = Bridge(endpoint_path=tmp_path / "endpoint.json")
    try:
        with pytest.raises(NoBrowserConnected):
            bridge.request("page.read", timeout=1.0)
    finally:
        bridge.close()


def test_the_bridge_refuses_a_relay_with_the_wrong_token(tmp_path):
    bridge = Bridge(endpoint_path=tmp_path / "endpoint.json")
    try:
        conn = socket.create_connection(("127.0.0.1", bridge.port), timeout=5.0)
        conn_file = conn.makefile("rwb")
        conn_file.write(json.dumps({"hello": "ks4web-relay", "token": "wrong"}).encode() + b"\n")
        conn_file.flush()
        ack = json.loads(conn_file.readline().decode())
        assert ack["ok"] is False
        assert "token" in ack["reason"]
        assert not bridge.connected
        conn.close()
    finally:
        bridge.close()


def test_the_bridge_accepts_a_relay_with_the_right_token(tmp_path):
    bridge = Bridge(endpoint_path=tmp_path / "endpoint.json")
    try:
        conn = socket.create_connection(("127.0.0.1", bridge.port), timeout=5.0)
        conn_file = conn.makefile("rwb")
        conn_file.write(json.dumps({"hello": "ks4web-relay", "token": bridge.token}).encode() + b"\n")
        conn_file.flush()
        ack = json.loads(conn_file.readline().decode())
        assert ack["ok"] is True
        assert bridge.wait_for_browser(5.0)
        conn.close()
    finally:
        bridge.close()


def test_the_relay_exits_when_there_is_no_bridge_to_dial(tmp_path, monkeypatch):
    # The right behaviour is to exit, not to sit on the pipe: the background
    # script backs off and reconnects, which gets a fresh relay a fresh
    # chance at a server that may by then be running.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["KS4WEB_EXTENSION_ENDPOINT"] = str(tmp_path / "nothing-here.json")
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "kitchensink4web.extension.relay"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        # CONNECT_TIMEOUT is 20s; give it a little more than that.
        assert process.wait(timeout=40) == 1
    finally:
        if process.poll() is None:
            process.kill()


# -- the pipe that has to outlive a pause ------------------------------------


def test_a_quiet_bridge_does_not_make_the_relay_hang_up(wired):
    """THE SESSION-KILLING ONE, and it was invisible until a test paused.

    `create_connection` returns a socket in timeout mode, `makefile`
    inherits it, and the pump spends its whole life in `readline()` waiting
    for a command. Five idle seconds raised `socket.timeout`, the pump read
    that as a dead bridge, and the relay exited. Firefox then fired
    `onDisconnect`, the background script cleared its consent set, and the
    next command on a session the human had already approved came back
    "consent not configured" with nothing anywhere saying why.

    Six seconds is longer than the handshake timeout and shorter than a
    person thinking about what to ask for next.
    """
    bridge, extension = wired
    extension.handler = echo_handler
    time.sleep(6.0)
    assert extension.process.poll() is None, "the relay exited while idle"
    assert bridge.connected
    assert bridge.request("bg.ping", timeout=20.0)["echoed"] == "bg.ping"


def test_the_pump_socket_is_left_blocking_rather_than_timed_out(tmp_path):
    """The mechanism above, checked where it lives rather than by its effect.

    A test that only measures the six seconds passes on any build whose
    timeout happens to be seven.
    """
    from kitchensink4web.extension import relay as relay_mod

    bridge = Bridge(endpoint_path=tmp_path / "endpoint.json")
    conn = None
    try:
        conn, _conn_file = relay_mod._connect_bridge(tmp_path / "endpoint.json")
        assert conn.gettimeout() is None
    finally:
        if conn is not None:
            conn.close()
        bridge.close()


def test_the_handshake_still_gives_up_rather_than_waiting_forever(tmp_path):
    """The other direction. The five seconds were removed from the pump and
    NOT from the handshake, so a listener that accepts and never answers is
    still abandoned rather than waited on."""
    from kitchensink4web.extension import relay as relay_mod

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    held: list = []

    def accept_and_say_nothing():
        try:
            held.append(listener.accept()[0])
        except OSError:
            pass

    thread = threading.Thread(target=accept_and_say_nothing, daemon=True)
    thread.start()

    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text(json.dumps(
        {"host": "127.0.0.1", "port": port, "token": "t"}), encoding="utf-8")
    started = time.monotonic()
    try:
        with pytest.raises(OSError):
            relay_mod._connect_bridge(endpoint, timeout=60.0)
        assert time.monotonic() - started < 30.0
    finally:
        for sock in held:
            sock.close()
        listener.close()


def test_the_endpoint_file_is_removed_when_the_bridge_closes(tmp_path):
    endpoint = tmp_path / "endpoint.json"
    bridge = Bridge(endpoint_path=endpoint)
    assert endpoint.exists()
    published = json.loads(endpoint.read_text(encoding="utf-8"))
    assert published["port"] == bridge.port
    assert published["token"] == bridge.token
    bridge.close()
    assert not endpoint.exists()
