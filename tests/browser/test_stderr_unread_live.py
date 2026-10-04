"""Browser tools still work when the client never reads the server's stderr.

The first version of the non-blocking log writer kept the protocol replies
flowing, but on Windows the first `navigate` after the stderr pipe filled
never answered: the writer thread had a write pending on the full pipe, and
the Playwright driver, which inherits the server's stderr, blocked at
startup the moment it queried that handle. Children now inherit a pipe the
server always drains (`stderrlog`), so this drives the real server over
stdio, fills the client's stderr pipe with bad requests, never reads it,
and then needs a real navigation and a clean exit.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

import pytest

NOWIN = 0x08000000 if sys.platform == "win32" else 0

#: Bad requests before `initialize`: each logs a WARNING line, so the
#: client's pipe is long full before the browser is started.
BAD = 60

#: A cold browser start on a loaded runner is slow; a wedged one never
#: answers at all.
DEADLINE_S = 150.0


def _rpc(i, method, params=None):
    msg = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


@pytest.mark.timeout(DEADLINE_S + 120)
def test_navigate_answers_and_the_server_exits_with_stderr_never_read(
        fixture_site, tmp_path):
    from kitchensink4web.engine import hygiene

    env = dict(os.environ, KS4WEB_STATE_DIR=str(tmp_path / "state"),
               KS4WEB_PROFILE_ROOT=str(tmp_path), KS4WEB_STAR_NUDGE="off",
               PYTHONUTF8="1")
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
    tree: list[int] = []

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()

    def wait_for(ident, limit):
        end = time.monotonic() + limit
        while time.monotonic() < end and ident not in replies:
            try:
                obj = json.loads(lines.get(timeout=0.25))
            except queue.Empty:
                continue
            if "id" in obj:
                replies[obj["id"]] = obj
        return replies.get(ident)

    exit_code = None
    try:
        for i in range(BAD):
            send(_rpc(1000 + i, "server/discover", {}))
        send(_rpc(1, "initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"}}))
        assert wait_for(1, DEADLINE_S), "initialize was never answered"
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        started = time.monotonic()
        send(_rpc(2, "tools/call", {"name": "navigate",
                                    "arguments": {"url": fixture_site}}))
        nav = wait_for(2, DEADLINE_S)
        took = time.monotonic() - started
        # Note the browser tree while it is alive, for the cleanup below.
        tree = [row["pid"] for row in hygiene.descendants(proc.pid)]
        assert nav is not None, (
            f"navigate never answered in {DEADLINE_S:.0f} s with the "
            f"client's stderr unread (a child blocked on the inherited "
            f"stderr handle)")
        assert not nav["result"].get("isError"), nav["result"]
        send(_rpc(3, "tools/call", {"name": "get_server_info",
                                    "arguments": {}}))
        assert wait_for(3, 60), "the server stopped answering after navigate"
        send(_rpc(4, "tools/call", {"name": "manage_session",
                                    "arguments": {"action": "close"}}))
        wait_for(4, 60)
        proc.stdin.close()
        try:
            exit_code = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            exit_code = None
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID",
                                str(proc.pid)], capture_output=True,
                               creationflags=NOWIN)
            else:
                proc.kill()
            proc.wait(timeout=30)
        for pid in tree:                    # never leave the machine dirty
            if hygiene.alive(pid):
                hygiene.kill(pid)
    assert exit_code == 0, (
        f"the server did not exit cleanly after stdin closed with its "
        f"stderr unread (exit code {exit_code}); navigate took {took:.1f} s")
