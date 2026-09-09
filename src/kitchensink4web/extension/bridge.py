"""The server side of the loopback hop.

The relay cannot be the MCP server, because Firefox LAUNCHES the native
messaging host and the server is already running when that happens (gaps
research, GAP 7). So the server listens on loopback, publishes where it is
listening in a small endpoint file, and the relay dials in once the browser
starts it.

The endpoint file carries a per-run token. Loopback is reachable by every
process on the machine, and the extension's whole value is access to logged
in pages, so an unauthenticated listener would hand that access to anything
that could guess a port number. The token is not a security boundary against
a process that can read the file; it is the boundary against one that
cannot.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from pathlib import Path
from typing import Any

from . import protocol

PROTOCOL_VERSION = 1
DEFAULT_ENDPOINT_NAME = "extension_endpoint.json"

#: Unsolicited pushes kept for the next caller who asks. The extension sends
#: one per SPA history update, and a session that never reads them must not
#: grow a list forever.
EVENT_MAX = 200


def default_state_dir() -> Path:
    """Where the endpoint file lives when nobody says otherwise."""
    base = os.environ.get("KS4WEB_STATE_DIR")
    if base:
        return Path(base)
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(root) / "kitchensink4web"
    return Path(os.path.expanduser("~")) / ".kitchensink4web"


def _pid_alive(pid: int) -> bool:
    """Whether a process is running. Unknown counts as ALIVE.

    The caller is deciding whether to take something away from that process,
    so an unanswerable question has to fall on the side of leaving it
    alone."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


class BridgeError(Exception):
    """The bridge could not do what was asked."""


class NoBrowserConnected(BridgeError):
    """A command was issued with no relay on the other end."""


class Bridge:
    """Listens for the relay, then speaks request/response over the socket.

    One relay at a time. A second connection is closed rather than queued,
    because two browsers answering the same command id is a correctness
    problem, not a capacity one.
    """

    def __init__(self, endpoint_path: Path | None = None) -> None:
        self.endpoint_path = Path(endpoint_path) if endpoint_path else (
            default_state_dir() / DEFAULT_ENDPOINT_NAME
        )
        self.token = secrets.token_hex(24)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(4)
        self.port = self._listener.getsockname()[1]

        self._conn: socket.socket | None = None
        self._conn_file = None
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._next_id = 1
        self._waiters: dict[int, threading.Event] = {}
        self._replies: dict[int, dict] = {}
        self._events: list[dict] = []
        self._stopped = threading.Event()
        #: Whether THIS bridge wrote the endpoint file. `close` unlinks it
        #: only when so: a bridge that refused to clobber another server's
        #: endpoint must not delete that server's endpoint on its way out,
        #: which would turn a polite refusal into the outage it prevented.
        self._owns_endpoint = False

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        try:
            self._write_endpoint()
        except BaseException:
            # A refusal here must not leave a bound listener and a live
            # thread behind: the caller is going to see an exception and will
            # not be holding anything it could close.
            self.close()
            raise

    # -- lifecycle -------------------------------------------------------

    def _write_endpoint(self) -> None:
        self._refuse_to_clobber()
        self.endpoint_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PROTOCOL_VERSION,
            "host": "127.0.0.1",
            "port": self.port,
            "token": self.token,
            "pid": os.getpid(),
        }
        tmp = self.endpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.endpoint_path)
        self._owns_endpoint = True

    def _refuse_to_clobber(self) -> None:
        """A SECOND SERVER DOES NOT STEAL THE FIRST ONE'S BROWSER.

        The endpoint file is a single well-known path, so a second KS4Web
        process writing it would point every future relay at itself and the
        first server's Lane C would go quiet with no error anywhere. The pid
        in the file is what makes that detectable: a live owner is a refusal
        naming it, and a dead one is a stale file this process may replace.

        This is the Phase 1 open question answered. The check is not a lock
        and does not pretend to be: two servers starting in the same
        millisecond can both pass it. What it removes is the ordinary case,
        which is a human with a second client open.
        """
        try:
            existing = json.loads(
                self.endpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        pid = existing.get("pid")
        if not isinstance(pid, int) or pid == os.getpid():
            return
        if not _pid_alive(pid):
            return
        raise BridgeError(
            f"another KS4Web server (pid {pid}) already owns the browser "
            f"extension endpoint at {self.endpoint_path}. One browser answers "
            f"one server: taking the endpoint would point the extension here "
            f"and leave that server's Lane C silently dead. Close the other "
            f"server, or point this one somewhere else with KS4WEB_STATE_DIR.")

    def close(self) -> None:
        self._stopped.set()
        with self._lock:
            conn = self._conn
            self._conn = None
        for sock in (conn, self._listener):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if self._owns_endpoint:
            try:
                self.endpoint_path.unlink()
            except OSError:
                pass
        for event in list(self._waiters.values()):
            event.set()

    def __enter__(self) -> "Bridge":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- connection ------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def wait_for_browser(self, timeout: float = 30.0) -> bool:
        return self._connected.wait(timeout)

    def _accept_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                conn, _addr = self._listener.accept()
            except OSError:
                return
            try:
                conn_file = conn.makefile("rwb")
                hello_line = conn_file.readline()
                hello = json.loads(hello_line.decode("utf-8"))
                if hello.get("token") != self.token:
                    # Both directions of this are pinned in the unit tests:
                    # the right token connects, the wrong one is refused with
                    # the reason named rather than dropped in silence.
                    conn_file.write(
                        json.dumps({"ok": False, "reason": "token mismatch"}).encode("utf-8") + b"\n"
                    )
                    conn_file.flush()
                    conn.close()
                    continue
                conn_file.write(json.dumps({"ok": True, "version": PROTOCOL_VERSION}).encode("utf-8") + b"\n")
                conn_file.flush()
            except (OSError, ValueError, json.JSONDecodeError):
                try:
                    conn.close()
                except OSError:
                    pass
                continue

            with self._lock:
                if self._conn is not None:
                    try:
                        conn.close()
                    except OSError:
                        pass
                    continue
                self._conn = conn
                self._conn_file = conn_file
            self._connected.set()
            threading.Thread(target=self._read_loop, args=(conn, conn_file), daemon=True).start()

    def _read_loop(self, conn: socket.socket, conn_file) -> None:
        # Reassembly belongs here rather than in the relay. The relay stays a
        # validating pipe with no memory of what it has forwarded, which is
        # what lets it be restarted by the browser at any moment; the bridge
        # is the side that already tracks outstanding ids.
        assembler = protocol.ChunkAssembler()
        try:
            for line in conn_file:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if "event" in message and "id" not in message:
                    # An unsolicited push. It correlates with no request, so
                    # it goes on the event list for whoever asks next rather
                    # than into the reply table keyed by an id it has not got.
                    with self._lock:
                        self._events.append(message)
                        while len(self._events) > EVENT_MAX:
                            self._events.pop(0)
                    continue
                ident = message.get("id")
                if not isinstance(ident, int):
                    continue
                try:
                    whole = assembler.feed(message)
                except protocol.ProtocolError as exc:
                    # A reply that cannot be reassembled must not leave its
                    # caller waiting out the full timeout for an answer that
                    # is never coming. The waiter is woken with the reason.
                    self._replies[ident] = {
                        "id": ident,
                        "error": {"code": "BAD_PAYLOAD", "message": str(exc)},
                    }
                    waiter = self._waiters.get(ident)
                    if waiter is not None:
                        waiter.set()
                    continue
                if whole is None:
                    continue
                message = whole
                self._replies[ident] = message
                waiter = self._waiters.get(ident)
                if waiter is not None:
                    waiter.set()
        except OSError:
            pass
        finally:
            with self._lock:
                if self._conn is conn:
                    self._conn = None
                    self._conn_file = None
                    self._connected.clear()
            try:
                conn.close()
            except OSError:
                pass

    # -- request / response ----------------------------------------------

    def request(self, method: str, params: dict | None = None, timeout: float = 20.0) -> Any:
        """Send one command and wait for its answer.

        Raises ``NoBrowserConnected`` when nothing is listening, ``TimeoutError``
        when the browser never answers, and ``BridgeError`` carrying the
        extension's own code and message when it answers with a refusal.
        """
        message = self.send_raw(method, params)
        return self._await(message["id"], timeout, method)

    def batch(self, steps: list[dict], timeout: float = 60.0,
              params: dict | None = None) -> list[dict]:
        """Send several commands as ONE round trip.

        Returns one entry per step, in order, each carrying `result` or
        `error`. A failed step does NOT stop the ones after it: the caller
        asked several questions and gets several answers, which is the shape
        that makes a five-field form fill one hop instead of five. A caller
        that wants stop-on-first-error checks the entries; a batch that
        stopped early would leave it unable to tell "not run" from "ran and
        said nothing".
        """
        if not steps:
            raise BridgeError("a batch needs at least one step")
        message = self._send(
            {"batch": [{"method": s["method"], "params": s.get("params") or {}}
                       for s in steps],
             "params": params or {}})
        result = self._await(message["id"], timeout, "batch")
        entries = result.get("batch")
        if not isinstance(entries, list) or len(entries) != len(steps):
            raise BridgeError(
                f"a batch of {len(steps)} step(s) came back with "
                f"{len(entries) if isinstance(entries, list) else 'no'} "
                f"answer(s); the pairing is by position and cannot be "
                f"reconstructed from a mismatched list")
        return entries

    def events(self, drain: bool = True) -> list[dict]:
        """The unsolicited pushes since the last call. SPA history updates
        arrive here, because they correlate with no request."""
        with self._lock:
            found = list(self._events)
            if drain:
                self._events.clear()
        return found

    def _await(self, ident: int, timeout: float, what: str):
        event = self._waiters[ident]
        if not event.wait(timeout):
            self._waiters.pop(ident, None)
            raise TimeoutError(f"{what} (id {ident}) went unanswered for {timeout}s")
        self._waiters.pop(ident, None)
        reply = self._replies.pop(ident)
        if "error" in reply:
            error = reply["error"]
            raise BridgeError(f"{error.get('code')}: {error.get('message')}")
        return reply.get("result")

    def send_raw(self, method: str, params: dict | None = None) -> dict:
        return self._send({"method": method, "params": params or {}})

    def _send(self, body: dict) -> dict:
        with self._lock:
            conn_file = self._conn_file
            if conn_file is None:
                raise NoBrowserConnected(
                    "[COPY PENDING] no-browser refusal text (extension not connected)"
                )
            ident = self._next_id
            self._next_id += 1
            message = {"id": ident, **body}
            self._waiters[ident] = threading.Event()
            conn_file.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
            conn_file.flush()
        return message
