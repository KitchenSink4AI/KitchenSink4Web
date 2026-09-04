"""The victim process for the orphan gate: a KS4Web server holding a browser.

Stands in for the real thing on the path MCP clients actually use. It opens a
session, writes down every PID it can see, and then blocks forever so the gate
can kill it in ways that run none of its code.

Usage: _hygiene_victim.py <pidfile> [lane] [job_object 0|1]

The job-object setting arrives as an ARGUMENT rather than an environment
variable because the gate launches this out-of-job through WMI, which creates
the process from the service and takes no environment with it.

It also records whether it is inside a Windows job object, because that single
fact is what makes the gate meaningful. S7 found the spike process sitting
inside a shell-owned job carrying KILL_ON_JOB_CLOSE, which reaps the tree for
you and makes every result green whether or not the server has any teardown at
all. A gate that cannot fail is not a gate, so the gate launches this with
CREATE_BREAKAWAY_FROM_JOB and this file reports what it sees.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if len(sys.argv) > 3:
    os.environ["KS4WEB_JOB_OBJECT"] = sys.argv[3]

from kitchensink4web.engine import hygiene  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402


def raw_control(pidfile: str) -> None:
    """The NEGATIVE control: a browser started with no teardown at all.

    This is what makes the orphan gate falsifiable on a machine where
    CREATE_BREAKAWAY_FROM_JOB cannot deliver an out-of-job child. If the
    environment were quietly reaping browser trees for us, this browser would
    die when its parent is killed too, and every green result elsewhere would
    be the environment's doing rather than KS4Web's. It is launched by plain
    Popen, so there is no death pipe, no job object, and nothing that could
    clean it up. It is EXPECTED to survive, and the gate kills it afterward.
    """
    import subprocess

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        exe = p.chromium.executable_path
    profile = hygiene.new_profile_dir("rawctl")
    proc = subprocess.Popen(
        [exe, "--headless=new", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4.0)
    kids = hygiene.descendants(os.getpid())
    Path(pidfile).write_text(json.dumps({
        "self_pid": os.getpid(), "lane": "raw", "mode": "negative-control",
        "profile": str(profile),
        "job_before_ks4web": hygiene.job_context(),
        "job_after_ks4web": hygiene.job_context(),
        "job_status": "none: this control deliberately has no teardown",
        "journal": "",
        "owned_pids": [proc.pid],
        "descendant_pids": [k["pid"] for k in kids],
        "node_pids": [],
        "browser_pids": [proc.pid] + [
            k["pid"] for k in kids
            if k["name"].lower() in ("chrome.exe", "chrome-headless-shell.exe")],
    }, indent=1), encoding="utf-8")
    print("raw control ready", flush=True)
    while True:
        time.sleep(1)


async def main() -> None:
    pidfile = sys.argv[1]
    lane = sys.argv[2] if len(sys.argv) > 2 else "A"
    kwargs = ({"lane": "B", "channel": "moz-firefox"} if lane == "B"
              else {"lane": "A", "engine": "chromium"})
    # What matters is not whether this process is in SOME job (on modern
    # Windows almost everything is) but whether the job it inherited would
    # reap the browser tree for us. Only KILL_ON_JOB_CLOSE does that, so that
    # single flag is the confound.
    job_before = hygiene.job_context()
    session = await MANAGER.open(headless=True, **kwargs)
    table = hygiene.snapshot_processes()
    kids = hygiene.descendants(os.getpid(), table)
    payload = {
        "self_pid": os.getpid(),
        "lane": lane,
        "profile": session.profile_dir,
        "job_before_ks4web": job_before,
        "job_after_ks4web": hygiene.job_context(),
        "job_status": hygiene.JOB.status,
        "journal": str(session.journal.path),
        "owned_pids": sorted(session.journal.pids),
        "descendant_pids": [k["pid"] for k in kids],
        "node_pids": [k["pid"] for k in kids
                      if k["name"].lower() == "node.exe"],
        "browser_pids": [k["pid"] for k in kids
                         if k["name"].lower() in ("chrome.exe", "firefox.exe",
                                                  "chrome-headless-shell.exe")],
    }
    page = session.page(session.focused).page
    await page.goto("about:blank")
    Path(pidfile).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print("victim ready", flush=True)
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    # The raw control never enters an asyncio loop: it uses the sync
    # Playwright API to find the browser binary, and that API refuses to run
    # inside a running loop (DESIGN 4.1).
    if len(sys.argv) > 2 and sys.argv[2] == "raw":
        raw_control(sys.argv[1])
    else:
        asyncio.run(main())
