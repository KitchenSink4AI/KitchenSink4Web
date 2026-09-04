"""Phase 1 hygiene gate: zero orphans, proved rather than asserted.

PLAN Phase 1 calls this "a hard one" and it is the row where the
most-installed browser MCP server in the world is currently open and unfixed:
chrome-devtools-mcp #2621, 42 orphaned Chrome roots plus roughly 300 helpers
across 83 connections, all at ppid=1, no maintainer reply. MEASURED reproduced
the same defect first-party on this machine.

Four scenarios, and the second is the one that matters:

1. **Fifty session cycles.** Open, read, close, fifty times. Zero surviving
   PIDs by owned PID and zero leftover profile directories.
2. **A hard kill of the server parent**, which is SIGKILL by another name and
   the path MCP hosts actually use. Run twice: once with KS4Web's job object
   on and once with it off, because "the death pipe is doing the work and the
   job object is the backstop" is a claim that should be checked in both
   directions rather than asserted.
3. **The startup reaper**, against a deliberately orphaned journal, with a
   control process alongside that the reaper must NOT touch.
4. **The idle park, verified by CPU measurement**, because "we called goto
   about:blank" is not evidence that a page stopped burning a core.

**The gate breaks away from the ambient job object and would be worthless
otherwise.** S7's confound: the spike process was itself inside a job carrying
KILL_ON_JOB_CLOSE inherited from the harness shell, children inherit it, and
Windows then reaps the tree for you whatever the server does or fails to do.
Scenario 2 launches its victim with CREATE_BREAKAWAY_FROM_JOB and the victim
reports whether it really is outside a job; if it is not, this gate FAILS
rather than passing for the wrong reason.

Run:  .venv/Scripts/python.exe -X utf8 scripts/gate_hygiene.py [--cycles 50]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "spikes" / "engine"))

import fixtures_server  # noqa: E402

from kitchensink4web.engine import hygiene  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
PY = sys.executable


def _alive(pids) -> list[int]:
    return [p for p in pids if hygiene.alive(p)]


def _spawn_out_of_job(args: list[str]) -> tuple[int | None, str]:
    """Start a process genuinely outside every job this shell sits inside.

    `CREATE_BREAKAWAY_FROM_JOB` is the documented route and it does not
    survive contact with this machine: the ambient job carries
    KILL_ON_JOB_CLOSE plus SILENT_BREAKAWAY_OK, the flag is accepted, and the
    child lands in a kill-on-close job anyway. A gate that accepted that would
    be measuring the shell.

    So the victim is created through WMI instead. `Win32_Process::Create`
    builds the process from the WMI service rather than from us, which puts it
    outside our job hierarchy entirely and gives the reaping question back to
    the code under test. The victim reports the job it actually landed in and
    the gate believes that rather than this function."""
    cmdline = subprocess.list2cmdline(args).replace("'", "''")
    cwd = str(ROOT).replace("'", "''")
    ps = (f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
          f"-Arguments @{{CommandLine='{cmdline}'; CurrentDirectory='{cwd}'}};"
          f" Write-Output $r.ReturnValue; Write-Output $r.ProcessId")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=180)
        parts = [p.strip() for p in out.stdout.split() if p.strip()]
        if len(parts) >= 2 and parts[0] == "0":
            return int(parts[1]), "WMI Win32_Process::Create (out of job)"
        return None, f"WMI create failed: {out.stdout} {out.stderr}"[:300]
    except Exception as exc:
        return None, f"WMI create raised {type(exc).__name__}: {exc}"


def _spawn(args: list[str], env: dict | None = None, quiet: bool = False):
    """Spawn a child OUTSIDE any job this process inherited, or say why not.

    Two routes to the same place. `CREATE_BREAKAWAY_FROM_JOB` needs the
    ambient job to carry `BREAKAWAY_OK`, and fails with access denied when it
    does not. A job carrying `SILENT_BREAKAWAY_OK` instead breaks children out
    automatically and REJECTS the explicit flag, which looks like a failure
    and is the opposite of one. So the flag is attempted, the fallback is a
    plain spawn, and neither is trusted: the child reports whether it is
    really in a job and the gate believes that rather than this."""
    kw = dict(stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
              stderr=subprocess.DEVNULL if quiet else subprocess.PIPE)
    if not quiet:
        kw["text"] = True
    if env:
        kw["env"] = env
    try:
        return (subprocess.Popen(args, creationflags=CREATE_BREAKAWAY_FROM_JOB,
                                 **kw), "explicit CREATE_BREAKAWAY_FROM_JOB")
    except OSError:
        ctx = hygiene.job_context()
        return (subprocess.Popen(args, **kw),
                f"flag denied; relying on the ambient job's "
                f"silent_breakaway_ok={ctx.get('silent_breakaway_ok')} and on "
                f"the child's own IsProcessInJob report")


# ------------------------------------------------------- 1. session cycles


async def scenario_cycles(cycles: int, base: str) -> dict:
    """Open, use, and close a browser `cycles` times. Nothing may survive."""
    leaked: list[dict] = []
    profiles: list[str] = []
    t0 = time.perf_counter()
    for i in range(cycles):
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        page = session.page(session.focused).page
        await page.goto(base + "/form", wait_until="load")
        owned = sorted(session.journal.pids)
        profile = session.profile_dir
        report = await MANAGER.close(session.session_id)
        survivors = _alive(owned)
        if survivors:
            leaked.append({"cycle": i, "pids": survivors})
        if Path(profile).exists():
            profiles.append(profile)
        if report["survivors_killed"]:
            leaked.append({"cycle": i, "needed_killing":
                           report["survivors_killed"]})
    return {
        "cycles": cycles,
        "seconds": round(time.perf_counter() - t0, 1),
        "leaked": leaked,
        "profiles_left": profiles,
        "pass": not leaked and not profiles,
    }


# --------------------------------------------------- 2. the hard-kill path


def scenario_hard_kill(lane: str = "A", job_object: bool = True) -> dict:
    """Kill the server the way an MCP host does, and count what is left.

    Signal handlers provably do not run under a hard kill, which is exactly
    how chrome-devtools-mcp accumulated 42 orphaned Chromes, so nothing in
    KS4Web's teardown gets a chance to execute here."""
    pidfile = ROOT / "gates" / f"_victim_{lane}_{int(job_object)}.json"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.unlink(missing_ok=True)
    victim_pid, breakaway = _spawn_out_of_job(
        [PY, "-X", "utf8", str(ROOT / "scripts" / "_hygiene_victim.py"),
         str(pidfile), lane, "1" if job_object else "0"])
    if victim_pid is None:
        return {"lane": lane, "job_object": job_object, "pass": False,
                "why": breakaway}

    info = None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if pidfile.exists():
            time.sleep(0.4)
            try:
                info = json.loads(pidfile.read_text(encoding="utf-8"))
                break
            except ValueError:
                pass
        if not hygiene.alive(victim_pid):
            return {"lane": lane, "job_object": job_object, "pass": False,
                    "why": f"victim pid {victim_pid} exited before reporting"}
        time.sleep(0.5)
    if info is None:
        hygiene.kill(victim_pid)
        return {"lane": lane, "job_object": job_object, "pass": False,
                "why": "victim never reported"}

    inherited_kill_job = info["job_before_ks4web"].get("kill_on_job_close")
    # Watch what KS4Web CLAIMS to own. That is the honest scope: the journal
    # is what authorizes a kill, so the journal is what has to come out empty.
    watched = sorted(set(info["owned_pids"]) | set(info["browser_pids"]))
    for pid in [info["self_pid"], *info["node_pids"]]:
        hygiene.kill(pid)

    timeline, survivors = [], watched
    t0 = time.perf_counter()
    for _ in range(20):
        time.sleep(1.0)
        survivors = _alive(watched)
        timeline.append({"t_s": round(time.perf_counter() - t0, 1),
                         "alive": len(survivors)})
        if not survivors:
            break
    for pid in survivors:      # never leave the machine dirty, even on a fail
        hygiene.kill(pid)
    profile = info.get("profile")
    if profile:
        hygiene._remove_tree(profile)
    if info.get("journal"):
        Path(info["journal"]).unlink(missing_ok=True)
    pidfile.unlink(missing_ok=True)
    return {
        "lane": lane, "job_object": job_object,
        "job_before_ks4web": info["job_before_ks4web"],
        "job_after_ks4web": info["job_after_ks4web"],
        "job_status": info["job_status"],
        "spawned_via": breakaway,
        "inherited_kill_on_job_close": inherited_kill_job,
        "watched": len(watched), "browser_pids": info["browser_pids"],
        "reap_seconds": timeline[-1]["t_s"] if timeline else None,
        "orphans": survivors,
        "expect_orphans": lane == "raw",
        "pass": bool(survivors) if lane == "raw" else not survivors,
    }


# ----------------------------------------------------- 3. the startup reap


def scenario_startup_reap() -> dict:
    """A crash residue is cleaned; a process we did not spawn is not.

    The control is the whole test. A reaper that kills everything passes a
    naive orphan check and violates the one rule that matters: never touch a
    process KS4Web did not spawn."""
    control = _spawn([PY, "-c", "import time;time.sleep(120)"], quiet=True)[0]
    victim = _spawn([PY, "-c", "import time;time.sleep(120)"], quiet=True)[0]
    time.sleep(1.0)

    # A crash residue: the owner is long gone, so its browser is an orphan.
    dead_profile = hygiene.new_profile_dir("reapdead")
    (dead_profile / "marker.txt").write_text("residue", encoding="utf-8")
    residue = hygiene.OwnedProcesses("sDead", str(dead_profile), "A(chromium)")
    residue.owner_pid = 999999          # an owner that is definitely gone
    residue.path = hygiene.STATE_DIR / "session-999999-sDead.json"
    residue.record([victim.pid])

    # A concurrently running KS4Web: its owner is ALIVE, so the reaper must
    # leave the whole journal alone. Killing a live peer's browsers would be
    # the same violation as killing a stranger's, one level up.
    live_profile = hygiene.new_profile_dir("reaplive")
    live = hygiene.OwnedProcesses("sLive", str(live_profile), "A(chromium)")
    live.owner_pid = control.pid        # a real, living owner
    live.path = hygiene.STATE_DIR / f"session-{control.pid}-sLive.json"
    live.record([control.pid])

    report = hygiene.reap_orphans()
    time.sleep(1.0)
    victim_dead = not hygiene.alive(victim.pid)
    control_alive = hygiene.alive(control.pid)
    for proc in (control, victim):
        try:
            proc.kill()
        except Exception:
            pass
    live.close()
    residue.close()
    hygiene._remove_tree(live_profile)
    hygiene._remove_tree(dead_profile)
    return {
        "report": report,
        "orphan_reaped": victim_dead,
        "live_peer_journal_skipped": report["skipped_live_owner"] == 1,
        "control_untouched": control_alive,
        "residue_profile_removed": not dead_profile.exists(),
        "pass": (victim_dead and control_alive
                 and report["skipped_live_owner"] == 1
                 and not dead_profile.exists()),
    }


# --------------------------------------------------- 4. the idle park, by CPU


BUSY_PAGE = """
<!doctype html><title>busy</title><body><p id=o>0</p><script>
let n = 0;
setInterval(() => {
  const t = performance.now();
  while (performance.now() - t < 12) { n += Math.sqrt(n + 1); }
  document.getElementById('o').textContent = String(n | 0);
}, 16);
</script></body>
"""


async def scenario_idle_park() -> dict:
    """Park a busy page and prove it stopped burning CPU.

    chrome-devtools-mcp #2599 measured a dormant page at 28 to 30 percent CPU
    for hours, dropping to 0.13 percent after exactly this intervention."""
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    try:
        record = session.page(session.focused)
        await record.page.set_content(BUSY_PAGE)
        await asyncio.sleep(1.0)
        pids = sorted(session.journal.pids)

        def cpu() -> float:
            return sum(hygiene.cpu_time(p) or 0.0 for p in pids)

        before = cpu()
        await asyncio.sleep(3.0)
        busy = cpu() - before

        parked = await MANAGER.park_idle(force=True)
        await asyncio.sleep(1.0)
        before = cpu()
        await asyncio.sleep(3.0)
        quiet = cpu() - before
        return {
            "pids": pids, "busy_cpu_s_over_3s": round(busy, 3),
            "parked_cpu_s_over_3s": round(quiet, 3),
            "parked": parked["parked"],
            "drop": round(1 - (quiet / busy), 3) if busy else None,
            "pass": bool(parked["parked"]) and busy > 0.15 and quiet < busy * 0.5,
        }
    finally:
        await MANAGER.close(session.session_id)


# ------------------------------------------------------------------- main


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=50)
    parser.add_argument("--lanes", default="A",
                        help="comma list: A (bundled chromium), B (installed "
                             "moz-firefox). Lane B launches YOUR Firefox with "
                             "-no-remote and a throwaway profile and never "
                             "touches one you already have open.")
    args = parser.parse_args()

    srv, base = fixtures_server.start()
    results: dict = {"job_context_at_start": hygiene.job_context()}
    try:
        # ORDER MATTERS and it is the confound again, one level up. The
        # moment this process opens its own session it puts ITSELF in a
        # kill-on-close job, and every child spawned afterward inherits it,
        # which would make the hard-kill scenario prove the harness rather
        # than the server. So the hard kill runs FIRST, before this process
        # owns a job of its own, and the victim still reports what it sees.
        results["hard_kill"] = []
        print("[1/4] hard kill, NEGATIVE CONTROL (a browser with no teardown "
              "at all; it MUST survive or this gate proves nothing) ...")
        control = scenario_hard_kill("raw", False)
        results["hard_kill"].append(control)
        print("      ", json.dumps(control)[:300])
        for lane in [x.strip() for x in args.lanes.split(",") if x.strip()]:
            for job in (True, False):
                print(f"[1/4] hard kill, lane {lane}, "
                      f"KS4Web job object {'on' if job else 'off'} ...")
                row = scenario_hard_kill(lane, job)
                results["hard_kill"].append(row)
                print("      ", json.dumps(row)[:300])

        print(f"[2/4] {args.cycles} session cycles ...")
        results["cycles"] = await scenario_cycles(args.cycles, base)
        print("      ", json.dumps(results["cycles"])[:200])

        print("[3/4] startup reap with a control process ...")
        results["startup_reap"] = scenario_startup_reap()
        print("      ", json.dumps(results["startup_reap"])[:260])

        print("[4/4] idle park, verified by CPU ...")
        results["idle_park"] = await scenario_idle_park()
        print("      ", json.dumps(results["idle_park"])[:260])
    finally:
        await MANAGER.close_all()
        srv.shutdown()

    failures = []
    if not results["cycles"]["pass"]:
        failures.append("session cycles leaked")
    for row in results["hard_kill"]:
        if row.get("pass"):
            continue
        if row.get("lane") == "raw":
            failures.append(
                "NEGATIVE CONTROL DID NOT ORPHAN: a browser started with no "
                "teardown at all died anyway when its parent was killed, so "
                "something in this environment is reaping browser trees and "
                "every other zero-orphan result here proves nothing. "
                f'({row.get("why") or "no survivors"})')
        else:
            failures.append(
                f'hard kill lane {row.get("lane")} job={row.get("job_object")}: '
                f'{row.get("why") or row.get("orphans")}')
    if not results["startup_reap"]["pass"]:
        failures.append("startup reap wrong (orphan survived or control killed)")
    if not results["idle_park"]["pass"]:
        failures.append("idle park did not drop CPU")

    out = ROOT / "gates" / "phase1_hygiene.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"measured": time.strftime("%Y-%m-%d %H:%M"), "results": results,
         "failures": failures}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    if failures:
        print("HYGIENE GATE RED:")
        for f in failures:
            print("  -", f)
        return 1
    print("HYGIENE GATE GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
