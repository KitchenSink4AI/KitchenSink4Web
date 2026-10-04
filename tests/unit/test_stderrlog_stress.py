"""Stress and lifecycle cases for the non-blocking stderr writer.

Written by an independent review of the first version of `stderrlog`, two
of them red against it:

- `test_exit_is_not_held_by_a_stuck_writer`: with stderr piped and never
  read, once the writer thread was blocked mid-write the process could not
  exit. The thread held the stderr buffer's lock inside the write;
  interpreter shutdown flushes sys.stderr, waited for that lock, then raised
  "Fatal Python error: _enter_buffered_busy ... possibly due to daemon
  threads", and writing THAT message to the full pipe blocked forever.
- `test_child_inheriting_stderr_starts_while_writer_stuck` (Windows): while
  any thread has a blocking write pending on the full pipe, a child that
  inherits stderr and merely queries it (the Playwright node driver does)
  blocks at startup, so the first browser tool never answered.

The others check the queue under a flood from many threads and the drop
count.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kitchensink4web import stderrlog

SRC = str(Path(stderrlog.__file__).resolve().parent.parent)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FILL_THEN_RETURN = r"""
import logging, sys, time
from kitchensink4web import stderrlog
w = stderrlog.install()
for i in range(400):
    logging.getLogger('v').warning('line %d %s', i, 'y' * 200)
time.sleep(1.0)
w.flush(1.0)
sys.stdout.write('RETURNING\n'); sys.stdout.flush()
"""


def _spawn(code: str) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": SRC}
    return subprocess.Popen([sys.executable, "-X", "utf8", "-c", code],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env,
                            creationflags=NOWIN)


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=NOWIN)
        else:
            proc.kill()
        proc.wait(10)


@pytest.mark.timeout(90)
def test_exit_is_not_held_by_a_stuck_writer():
    proc = _spawn(FILL_THEN_RETURN)
    try:
        line = proc.stdout.readline()
        assert b"RETURNING" in line
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            code = None
        assert code == 0, (
            "process with an unread, full stderr did not exit within 10 s "
            "of main returning (writer thread holds the stderr buffer lock "
            "at finalization)")
    finally:
        _kill(proc)


SPAWN_CHILD_WHILE_STUCK = r"""
import logging, subprocess, sys, time, json
from kitchensink4web import stderrlog
stderrlog.install()
for i in range(400):
    logging.getLogger('v').warning('line %d %s', i, 'y' * 200)
time.sleep(1.0)
t0 = time.monotonic()
try:
    subprocess.run([sys.executable, '-c',
        'import ctypes,sys; k=ctypes.windll.kernel32; '
        'k.GetFileType(k.GetStdHandle(-12)); sys.stdout.write("ok")'],
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=8,
        creationflags=0x08000000)
    out = {'child_hung': False, 's': round(time.monotonic() - t0, 2)}
except subprocess.TimeoutExpired:
    out = {'child_hung': True}
sys.stdout.write(json.dumps(out) + '\n'); sys.stdout.flush()
import os; os._exit(0)
"""


@pytest.mark.skipif(os.name != "nt", reason="Windows synchronous-pipe lock")
@pytest.mark.timeout(90)
def test_child_inheriting_stderr_starts_while_writer_stuck():
    import json
    proc = _spawn(SPAWN_CHILD_WHILE_STUCK)
    try:
        res = json.loads(proc.stdout.readline() or b"{}")
        assert res.get("child_hung") is False, (
            "a child inheriting stderr hung at startup while the writer "
            "thread was blocked on the full pipe (the Playwright driver "
            "does this, so browser tools hang)")
    finally:
        _kill(proc)


class _Stuck:
    """A stderr whose write blocks until released, recording what lands."""

    def __init__(self):
        self.release = threading.Event()
        self.written: list[str] = []

    def write(self, text):
        self.release.wait()
        self.written.append(text)

    def flush(self):
        pass


@pytest.fixture
def writer():
    stderrlog.uninstall()
    stuck = _Stuck()
    w = stderrlog.install(stuck)
    yield w, stuck
    stuck.release.set()
    stderrlog.uninstall()


def test_background_flood_from_many_threads_never_blocks_the_loop(writer):
    w, stuck = writer
    n_threads, per = 8, 2000
    gaps: list[float] = []

    async def ticker(stop):
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.005)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    def flood(k):
        log = logging.getLogger(f"verify.flood{k}")
        for i in range(per):
            log.warning("flood %d %d %s", k, i, "z" * 500)

    async def main():
        stop = asyncio.Event()
        t = asyncio.create_task(ticker(stop))
        threads = [threading.Thread(target=flood, args=(k,))
                   for k in range(n_threads)]
        for th in threads:
            th.start()
        # the loop itself also logs (as the SDK does on the loop thread)
        for i in range(500):
            logging.getLogger("mcp.shared.session").warning(
                "Failed to validate request: %s", "x\n" * 4000)
            await asyncio.sleep(0)
        while any(th.is_alive() for th in threads):
            await asyncio.sleep(0.01)
        stop.set()
        await t

    asyncio.run(main())
    emitted = n_threads * per + 500
    assert max(gaps) < 0.5, f"loop stalled {max(gaps):.3f}s"
    assert w.queue.qsize() <= stderrlog.QUEUE_LINES
    in_flight = 1          # the line the writer is stuck writing
    assert w.dropped == emitted - w.queue.qsize() - in_flight - len(
        stuck.written)


def test_drop_count_is_reported_once_stderr_moves(writer):
    w, stuck = writer
    log = logging.getLogger("verify.drop")
    for i in range(1000):
        log.warning("line %d", i)
    dropped_before = w.dropped
    assert dropped_before > 0
    stuck.release.set()
    w.flush(5.0)
    log.warning("after release")
    w.flush(5.0)
    import re
    reports = [s for s in stuck.written if "log lines dropped" in s]
    assert reports, "drop count never reported"
    total = sum(int(re.search(r"(\d+) log lines dropped", r).group(1))
                for r in reports)
    assert total == w.dropped == dropped_before
    assert any("after release" in s for s in stuck.written)
    assert all(len(s.encode()) <= stderrlog.MAX_LINE for s in stuck.written)
