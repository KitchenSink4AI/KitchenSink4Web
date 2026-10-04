"""The server's last words reach a client that reads its stderr, and a
dying pump cannot leave descriptor 2 writers blocked.

From an independent review of the descriptor-2 redirect, all three red
against it as first written:

- `test_startup_refusal_reaches_a_client_that_reads_stderr`: "KS4Web
  refusing to start" was printed into the redirected pipe and the process
  ended before the pump and the writer passed it on; the client saw an
  empty stderr and exit code 2.
- `test_crash_traceback_reaches_a_client_that_reads_stderr`: a traceback
  printed after `main()` returned arrived as its first line only.
- `test_pump_thread_dying_leaves_descriptor_2_writers_blocked_FINDING`: a
  fault in the pump stopped it for good, so the redirected pipe filled and
  every descriptor-2 writer blocked, even with a client reading stderr.

The test bodies are the reviewer's, unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from kitchensink4web import stderrlog

SRC = str(Path(stderrlog.__file__).resolve().parent.parent)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WIN = os.name == "nt"

PRELUDE = textwrap.dedent(r"""
    import json, logging, os, subprocess, sys, threading, time, asyncio
    NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    def out(obj):
        sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
    def fill_client_pipe():
        for i in range(400):
            logging.getLogger("v").warning("fill %d %s", i, "y" * 200)
        time.sleep(1.0)
    def stderr_handle_type_child(timeout=8):
        code = ("import ctypes,sys; k=ctypes.windll.kernel32; "
                "k.GetFileType(k.GetStdHandle(-12)); sys.stdout.write('ok')"
                if os.name == "nt" else
                "import os,sys; os.fstat(2); sys.stdout.write('ok')")
        t0 = time.monotonic()
        try:
            subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, timeout=timeout,
                           creationflags=NOWIN)
            return round(time.monotonic() - t0, 2)
        except subprocess.TimeoutExpired:
            return "HUNG"
""")


def _run(body: str, *, timeout: float = 120.0, read_stderr: bool = False,
         env_extra: dict | None = None):
    """Run PRELUDE + body in a child whose stderr is never read. Returns
    (last JSON line on stdout or None, exit code or None, seconds,
    stderr bytes if read_stderr)."""
    code = PRELUDE + textwrap.dedent(body)
    env = {**os.environ, "PYTHONPATH": SRC, **(env_extra or {})}
    proc = subprocess.Popen([sys.executable, "-X", "utf8", "-c", code],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env,
                            creationflags=NOWIN)
    lines: list[bytes] = []
    errbuf = bytearray()

    def rd():
        for raw in proc.stdout:
            lines.append(raw)
    threading.Thread(target=rd, daemon=True).start()
    if read_stderr:
        def er():
            while True:
                c = proc.stderr.read1(65536)
                if not c:
                    break
                errbuf.extend(c)
        threading.Thread(target=er, daemon=True).start()
    t0 = time.monotonic()
    try:
        code_ = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code_ = None
    took = round(time.monotonic() - t0, 2)
    if proc.poll() is None:
        if WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=NOWIN)
        else:
            proc.kill()
        proc.wait(10)
    time.sleep(0.2)
    last = None
    for raw in lines:
        try:
            last = json.loads(raw)
        except ValueError:
            pass
    return last, code_, took, bytes(errbuf)



# ------------------------------------------- the pump dying (F9)


@pytest.mark.timeout(120)
def test_pump_thread_dying_leaves_descriptor_2_writers_blocked_FINDING():
    """Fault injection: the pump raises once (stand-in for any bug in the
    line splitter). Nothing restarts it and nothing falls back, so the
    redirected pipe fills and every descriptor-2 writer blocks again, even
    with a client that DOES read stderr."""
    res, code, took, err = _run(r"""
        from kitchensink4web import stderrlog
        orig = stderrlog.NonBlockingStderr._raw
        def bad(self, data):
            raise RuntimeError("injected pump fault")
        stderrlog.NonBlockingStderr._raw = bad
        w = stderrlog.install()
        os.write(2, b"trigger\n")              # pump calls _raw -> dies
        time.sleep(0.5)
        stderrlog.NonBlockingStderr._raw = orig
        pump_alive = any(t.name == "ks4web-stderr-pump" and t.is_alive()
                         for t in threading.enumerate())
        box = {}
        def big():
            os.write(2, b"x" * 200000); box["done"] = True
        th = threading.Thread(target=big, daemon=True); th.start(); th.join(5)
        out({"pump_alive": pump_alive, "fd2_write_200k_done": bool(box)})
        os._exit(0)
    """, read_stderr=True)
    assert res is not None
    print(res)
    assert res["pump_alive"] or res["fd2_write_200k_done"], (
        "pump died and descriptor-2 writes now block (client stderr IS "
        "being read in this case)")



# ------------------------------- F8: last words lost at exit


def _server_exit_stderr(code: str, extra: dict) -> tuple[int, str]:
    import tempfile
    env = {**os.environ, "PYTHONPATH": SRC, "KS4WEB_STAR_NUDGE": "off",
           "KS4WEB_STATE_DIR": tempfile.mkdtemp(), **extra}
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       stdin=subprocess.DEVNULL, capture_output=True,
                       env=env, timeout=90, creationflags=NOWIN)
    return r.returncode, r.stderr.decode("utf8", "replace")


@pytest.mark.timeout(200)
def test_startup_refusal_reaches_a_client_that_reads_stderr():
    """`KS4Web refusing to start: ...` is printed after install() and the
    process exits at once; nothing drains the redirected pipe before the
    daemon threads stop. Measured 0/10 delivered on 78111fa, 10/10 on main."""
    code = ("import sys; sys.argv=['web-mcp']\n"
            "from kitchensink4web.server import main\nmain()\n")
    got = 0
    for _ in range(3):
        rc, err = _server_exit_stderr(code, {
            "KS4WEB_PREAUTH": "payment_form@example.com",
            "KS4WEB_ALLOW_ACTING": "1"})
        assert rc == 2
        got += "refusing to start" in err
    assert got == 3, f"refusal message delivered {got}/3"


@pytest.mark.timeout(200)
def test_crash_traceback_reaches_a_client_that_reads_stderr():
    """An exception escaping main(): only 'Traceback (most recent call
    last):' arrived on 78111fa (5/5), the error line never did."""
    code = ("import sys; sys.argv=['web-mcp']\n"
            "import kitchensink4web.server as s\n"
            "def boom(*a, **k):\n"
            "    raise RuntimeError('VERIFIER-CRASH-MARKER')\n"
            "s.mcp.run = boom\ns.main()\n")
    got = 0
    for _ in range(3):
        rc, err = _server_exit_stderr(code, {})
        assert rc == 1
        got += "VERIFIER-CRASH-MARKER" in err
    assert got == 3, f"crash error line delivered {got}/3"
