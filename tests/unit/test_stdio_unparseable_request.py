"""A client that never reads the server's stderr must never silence it.

What was reported: a stdio server went silent after a client sent
`server/discover` (the 2026-07-28 dual-era probe) or any unknown method
before `initialize`, and the `initialize` that followed was never answered.

What was measured on Web 1.0.3 (raw stdio probe, 2026-10-05): the protocol
side is fine. The SDK answers the probe with JSON-RPC -32602 and then answers
`initialize`, which is the fallback the 2026-07-28 stdio binding asks of a
legacy server. The hang is STDERR BACKPRESSURE: the SDK logs each
unparseable request as a WARNING carrying the whole pydantic error (about
8 KB for one `server/discover`), synchronously on the event loop's thread.
A client that pipes the server's stderr and never reads it, which the stdio
binding allows, leaves a 4096-byte pipe on Windows; startup already writes
about 2.6 KB of it, so the first probe blocked the server inside that write
and nothing after it was ever answered. The same happened after
`initialize`. Shorter lines alone only move the wall (the KitchenSink4XL
server went silent after about 36 bad requests with clipped lines), so log
lines now go through a bounded queue to a writer thread, and everything
else that writes to stderr (prints, raw writes, child processes) writes
into a pipe the server always drains (`stderrlog`). The process must also
still exit when the client closes stdin.
"""

from __future__ import annotations

import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import warnings

import pytest

from kitchensink4web import stderrlog

NOWIN = 0x08000000 if sys.platform == "win32" else 0

#: Startup on a loaded machine took up to 20 s in this session; the deadline
#: covers startup plus the exchange. A wedged server simply never answers.
DEADLINE_S = 150.0

#: Bad requests sent before `initialize`. Excel's clipped lines filled the
#: pipe after about 36; this is well past that.
BAD_BEFORE = 120


def _bad(i: int) -> dict:
    if i % 2:
        return {"jsonrpc": "2.0", "id": 1000 + i, "method": "server/discover",
                "params": {"_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "probe", "version": "0"}}}}
    return {"jsonrpc": "2.0", "id": 1000 + i, "method": "acme/whatever",
            "params": {"n": i}}


INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                         "clientInfo": {"name": "probe", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
CALL = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_server_info", "arguments": {}}}
BAD_AFTER = {"jsonrpc": "2.0", "id": 3, "method": "acme/whatever",
             "params": {}}
LIST = {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}}


@pytest.mark.timeout(DEADLINE_S + 60)
def test_120_bad_requests_with_stderr_never_read_then_initialize_and_a_call(
        tmp_path):
    """The real server process, its stderr piped and NEVER read."""
    env = dict(os.environ, KS4WEB_STATE_DIR=str(tmp_path),
               KS4WEB_STAR_NUDGE="off", PYTHONUTF8="1")
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c",
         "from kitchensink4web.server import main; main()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=NOWIN, env=env)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(raw) for raw in
                                     iter(proc.stdout.readline, b"")],
                     daemon=True).start()
    replies: dict = {}
    wanted = {1000 + i for i in range(BAD_BEFORE)} | {1, 2, 3, 4}
    try:
        script = [_bad(i) for i in range(BAD_BEFORE)]
        script += [INITIALIZE, INITIALIZED, CALL, BAD_AFTER, LIST]
        for msg in script:
            proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()
        end = time.monotonic() + DEADLINE_S
        while time.monotonic() < end and not wanted <= set(replies):
            try:
                raw = lines.get(timeout=0.25)
            except queue.Empty:
                continue
            obj = json.loads(raw)
            if "id" in obj:
                replies[obj["id"]] = obj
        # And it EXITS when the client closes stdin, stderr still unread:
        # interpreter shutdown must not wait on the stuck writer.
        proc.stdin.close()
        try:
            exit_code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            exit_code = None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)

    missing = sorted(wanted - set(replies))
    assert not missing, (
        f"{len(missing)} requests never answered (first: {missing[:5]}): "
        f"the server is wedged behind its own stderr")
    # Every probe got an answer, and none is a recognized modern error, so a
    # dual-era client falls back to `initialize` as the stdio binding says.
    for i in range(BAD_BEFORE):
        error = replies[1000 + i].get("error")
        assert error and error["code"] != -32022, replies[1000 + i]
    assert "result" in replies[1], replies[1]
    assert "result" in replies[2], replies[2]
    assert not replies[2]["result"].get("isError"), replies[2]
    assert "error" in replies[3], replies[3]
    assert "result" in replies[4], replies[4]
    assert exit_code == 0, (
        f"the server did not exit cleanly after stdin closed with its "
        f"stderr unread (exit code {exit_code})")


#: A process with the writer installed the way `main()` installs it, whose
#: stderr the parent never reads: a large print, a large raw write to
#: descriptor 2, and a child that inherits stderr and writes plenty to it
#: must all return, and the process must still exit 0.
EVERY_OTHER_WRITER = r"""
import os, subprocess, sys, time, json
from kitchensink4web import stderrlog
stderrlog.install()
t0 = time.monotonic()
print("p" * 200000, file=sys.stderr)
os.write(2, b"r" * 200000 + b"\n")
child = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.stderr.write('c' * 300000); sys.stderr.flush()"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=30,
    creationflags=0x08000000 if os.name == "nt" else 0)
out = {"secs": round(time.monotonic() - t0, 2), "child": child.returncode}
sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
"""


@pytest.mark.timeout(120)
def test_prints_raw_writes_and_children_never_wait_on_an_unread_stderr():
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", EVERY_OTHER_WRITER],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=NOWIN)
    got: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: got.put(proc.stdout.readline()),
                     daemon=True).start()
    try:
        try:
            line = got.get(timeout=60)
        except queue.Empty:
            line = b""
        assert line, "the writes blocked: nothing came back in 60 s"
        result = json.loads(line)
        assert result["child"] == 0
        assert result["secs"] < 30, result
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID",
                                str(proc.pid)], capture_output=True,
                               creationflags=NOWIN)
            else:
                proc.kill()
            proc.wait(timeout=30)


# ------------------------------------------------- the writer, in-process


class NeverAccepts:
    """A stderr that never accepts a byte: every write blocks until the test
    is over."""

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()

    def write(self, text):
        self.entered.set()
        self.release.wait()
        return len(text)

    def flush(self):
        pass


@pytest.fixture
def blocked():
    stream = NeverAccepts()
    writer = stderrlog.install(stream)
    try:
        yield stream, writer
    finally:
        stderrlog.uninstall()
        stream.release.set()


@pytest.fixture
def readable():
    stream = io.StringIO()
    writer = stderrlog.install(stream)
    try:
        yield stream, writer
    finally:
        stderrlog.uninstall()


def _sdk_validation_error(method: str, *, notification: bool = False):
    import mcp.types as t
    from pydantic import ValidationError
    model = t.ClientNotification if notification else t.ClientRequest
    try:
        model.model_validate({"method": method, "params": {}})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected the SDK model to reject " + method)


def test_logging_never_waits_on_a_stderr_that_never_accepts_a_byte(blocked):
    stream, writer = blocked
    dump = _sdk_validation_error("server/discover")
    fastmcp_log = logging.getLogger("fastmcp.server.server")

    def flood():
        for i in range(2000):
            # The SDK's own call, verbatim (mcp/shared/session.py).
            logging.warning(f"Failed to validate request: {dump}")
            fastmcp_log.warning("fastmcp line %d", i)
            warnings.warn(f"warning {i}", UserWarning, stacklevel=1)

    worker = threading.Thread(target=flood, daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(30)
    assert not worker.is_alive(), "a log call blocked on stderr"
    assert stream.entered.is_set(), "the writer never even tried stderr"
    assert writer.queue.qsize() <= stderrlog.QUEUE_LINES
    assert writer.dropped >= 4000
    assert time.monotonic() - started < 30


def test_an_event_loop_keeps_turning_while_stderr_is_stuck(blocked):
    """The property the server needs, stated the server's way."""
    import asyncio

    ticks = []

    async def ticker():
        for _ in range(20):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    async def noisy():
        for i in range(500):
            logging.warning("Failed to validate request: %s", "x" * 8000)
            await asyncio.sleep(0)

    async def both():
        await asyncio.wait_for(asyncio.gather(ticker(), noisy()), 20)

    worker = threading.Thread(target=lambda: asyncio.run(both()),
                              daemon=True)
    worker.start()
    worker.join(30)
    assert not worker.is_alive()
    assert len(ticks) == 20


def test_each_record_is_one_bounded_line(readable):
    stream, writer = readable
    dump = _sdk_validation_error("server/discover")
    assert len(str(dump).encode()) > 4096, "the dump this exists for"
    logging.warning(f"Failed to validate request: {dump}")
    note = _sdk_validation_error("notifications/acme", notification=True)
    logging.warning(f"Failed to validate notification: {note}. Message was: "
                    f"{ {'method': 'notifications/acme', 'x': 'y' * 9000} }")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.exception("handler failed\nsecond line")
    logging.getLogger("fastmcp.server.server").warning("from fastmcp")
    writer.flush(5)
    out = stream.getvalue().splitlines()
    assert len(out) == 4, out
    for line in out:
        assert len(line.encode()) + 1 <= stderrlog.MAX_LINE, line
    assert "server/discover" in out[0]
    assert "notifications/acme" in out[1]
    assert "Traceback" not in out[2] and "second line" in out[2]
    assert out[3].endswith("from fastmcp")


def test_dropped_lines_are_counted_and_reported_once_stderr_moves():
    stream = NeverAccepts()
    writer = stderrlog.NonBlockingStderr(stream, maxsize=4)
    log = logging.getLogger("ks4web-test-drop")
    log.propagate = False
    log.addHandler(writer.handler)
    try:
        for i in range(50):
            log.warning("line %d", i)
        assert writer.dropped >= 40
        seen = io.StringIO()
        writer.stream = seen
        stream.release.set()
        log.warning("after")
        writer.flush(5)
        assert "log lines dropped while stderr was not being read" \
            in seen.getvalue()
    finally:
        log.removeHandler(writer.handler)
        stream.release.set()


def test_thread_and_unraisable_exceptions_are_one_logged_line(readable):
    stream, writer = readable

    def boom():
        raise ValueError("thread went wrong")

    worker = threading.Thread(target=boom, name="probe-thread")
    worker.start()
    worker.join(10)

    class Noisy:
        def __del__(self):
            raise RuntimeError("finalizer went wrong")

    Noisy()
    writer.flush(5)
    out = stream.getvalue().splitlines()
    thread_lines = [x for x in out if "probe-thread" in x]
    assert len(thread_lines) == 1, out
    assert "ValueError: thread went wrong" in thread_lines[0]
    assert "(at test_stdio_unparseable_request.py:" in thread_lines[0]
    unraisable = [x for x in out if "finalizer went wrong" in x]
    assert len(unraisable) == 1, out
    assert "RuntimeError" in unraisable[0]
    for line in out:
        assert "Traceback" not in line
        assert len(line.encode()) + 1 <= stderrlog.MAX_LINE


def test_uninstall_restores_the_exception_hooks():
    before = (sys.unraisablehook, threading.excepthook)
    stderrlog.install(io.StringIO())
    assert sys.unraisablehook is not before[0]
    assert threading.excepthook is not before[1]
    stderrlog.uninstall()
    assert (sys.unraisablehook, threading.excepthook) == before


def test_flush_never_waits_on_a_stuck_writer(blocked):
    stream, writer = blocked
    logging.warning("one line the writer will get stuck on")
    assert stream.entered.wait(10)
    logging.warning("and one waiting behind it")
    started = time.monotonic()
    writer.flush(10.0)
    assert time.monotonic() - started < 2.0


def test_install_is_idempotent_and_uninstall_restores(readable):
    _, writer = readable
    assert stderrlog.install() is writer
    root = logging.getLogger()
    fm = logging.getLogger("fastmcp")
    assert root.handlers.count(writer.handler) == 1
    assert fm.handlers == [writer.handler]


def test_uninstall_puts_the_old_handlers_back():
    fm = logging.getLogger("fastmcp")
    before = list(fm.handlers)
    stderrlog.install(io.StringIO())
    stderrlog.uninstall()
    assert fm.handlers == before


def test_the_sdk_still_logs_with_the_prefixes_the_filter_matches():
    """A canary: if a future SDK rewords these warnings, the collapse would
    go inert without a sound (the queue still protects the server)."""
    import inspect

    import mcp.shared.session as s
    source = inspect.getsource(s)
    for prefix in stderrlog.PREFIXES:
        assert prefix.strip() in source, prefix


def test_main_installs_the_writer_first_and_flushes_it_last():
    import inspect

    from kitchensink4web import server
    body = inspect.getsource(server.main)
    assert body.index("stderrlog.install()") < body.index("configure(")
    assert body.index("mcp.run()") < body.index("_stderr.flush(")
