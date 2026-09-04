"""S7 (Windows slice): process hygiene under failure injection.

Scenarios per lane (chromium, moz-firefox):
  A  graceful close                     -> baseline, must leave nothing
  B  parent killed with taskkill /F     -> the SIGKILL-equivalent; does the
                                           node driver's death pipe reap the
                                           browser, or do we get orphans?
  C  same kill, child inside a Windows  -> does the job-object reaper design
     job with KILL_ON_JOB_CLOSE            actually work as the backstop?
  D  hung navigation with a bounded     -> does a timeout free the server, and
     timeout                               is the browser still usable after?

Also measures the mechanics a reaper needs: child-PID enumeration cost, whether
Playwright hands us the browser PID directly, and job-object availability from
plain CPython (ctypes, no pywin32).

Only PIDs this spike started are ever killed; a pre-run census fences off
everything of the user's.
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import fixtures_server  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PY = os.path.join(HERE, "..", "s1", ".venv", "Scripts", "python.exe")
results = []


def alive(pids):
    live = {p["pid"] for p in common.ps_processes()}
    return [p for p in pids if p in live]


def start_child(lane, mode):
    pidfile = os.path.join(OUT, "s7_child_%s_%s.json" % (lane.replace("-", ""), mode))
    if os.path.exists(pidfile):
        os.remove(pidfile)
    proc = subprocess.Popen([PY, "-X", "utf8", os.path.join(HERE, "s7_child.py"),
                             lane, pidfile, mode],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(120):
        if os.path.exists(pidfile):
            time.sleep(0.4)
            try:
                with open(pidfile, encoding="utf-8") as f:
                    return proc, json.load(f)
            except Exception:
                pass
        if proc.poll() is not None:
            out, err = proc.communicate()
            raise RuntimeError("child died early: %s %s" % (out[-400:], err[-600:]))
        time.sleep(0.5)
    raise RuntimeError("child never became ready")


def scenario(lane, mode, kill_style):
    """kill_style: 'graceful' | 'taskkill_f' """
    print("\n-- %s / mode=%s / kill=%s" % (lane, mode, kill_style))
    proc, info = start_child(lane, mode)
    watch = info["descendant_pids"] + [info["self_pid"]]
    row = {"lane": lane, "mode": mode, "kill": kill_style,
           "child_pid": info["self_pid"],
           "browser_pids": info["browser_pids"], "node_pids": info["node_pids"],
           "descendant_names": sorted({d["name"] for d in info["descendants"]}),
           "job_result": info.get("job_result")}
    print("   child=%s node=%s browser=%s" % (info["self_pid"], info["node_pids"],
                                              info["browser_pids"]))
    t0 = time.perf_counter()
    if kill_style == "graceful":
        proc.terminate()   # CTRL-less TerminateProcess on Windows == hard kill
    elif kill_style == "parent_and_driver":
        # The nastiest realistic case: the server AND the node driver both die
        # at once, so the death pipe has nobody left to act on it.
        for pid in [info["self_pid"]] + info["node_pids"]:
            common.kill_pid(pid, force=True)
        row["killed"] = [info["self_pid"]] + info["node_pids"]
    else:
        rc, out = common.kill_pid(info["self_pid"], force=True)
        row["taskkill_rc"] = rc
        row["taskkill_out"] = out.strip()[:200]

    # poll for up to 20 s to see whether the tree reaps itself
    timeline = []
    for i in range(20):
        time.sleep(1.0)
        still = alive(watch)
        timeline.append({"t_s": round(time.perf_counter() - t0, 1), "alive": still})
        if not still:
            break
    row["timeline"] = timeline
    survivors = alive(watch)
    row["survivors"] = [p for p in common.ps_processes() if p["pid"] in survivors]
    row["orphan_count"] = len(survivors)
    row["reap_seconds"] = timeline[-1]["t_s"] if not survivors else None
    print("   orphans after 20s: %d %s" % (len(survivors), survivors))

    if survivors:  # clean up only what we started
        for pid in survivors:
            common.kill_pid(pid)
        time.sleep(1.5)
        row["after_cleanup"] = alive(watch)
    shutil.rmtree(info.get("profile", ""), ignore_errors=True)
    results.append(row)
    return row


def hung_navigation(lane, base):
    """Scenario D: bounded timeout on a navigation that never answers."""
    from playwright.sync_api import sync_playwright
    print("\n-- %s / hung navigation" % lane)
    row = {"lane": lane, "scenario": "hung_navigation"}
    prof = common.throwaway_profile("s7hang")
    with sync_playwright() as p:
        if lane == "moz-firefox":
            ctx = p.firefox.launch_persistent_context(prof, channel="moz-firefox",
                                                      headless=True,
                                                      args=common.SAFE_FF_ARGS, timeout=90000)
        else:
            ctx = p.chromium.launch_persistent_context(prof, headless=True, timeout=90000)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        t0 = time.perf_counter()
        try:
            page.goto(base + "/hang", timeout=3000)
            row["timeout_raised"] = False
        except Exception as e:
            row["timeout_raised"] = True
            row["error_type"] = type(e).__name__
            row["error"] = str(e)[:300]
        row["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        try:
            page.goto(base + "/", timeout=15000)
            row["browser_usable_after"] = page.locator("#marker").inner_text()
        except Exception as e:
            row["browser_usable_after"] = "FAILED: %s" % str(e)[:200]
        ctx.close()
    shutil.rmtree(prof, ignore_errors=True)
    print("   ", {k: row[k] for k in ("timeout_raised", "elapsed_ms", "browser_usable_after")})
    results.append(row)
    return row


def mechanics():
    """Can a reaper get what it needs from plain Python on Windows?"""
    m = {}
    t0 = time.perf_counter()
    procs = common.ps_processes()
    m["cim_enumeration_ms"] = round((time.perf_counter() - t0) * 1000)
    m["cim_process_count"] = len(procs)
    # job object creation from plain ctypes
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.CreateJobObjectW(None, None)
    m["CreateJobObjectW"] = bool(h)
    if h:
        k32.CloseHandle(h)
    # does Playwright expose the browser process pid?
    from playwright.sync_api import sync_playwright
    prof = common.throwaway_profile("s7mech")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(prof, headless=True)
        impl = getattr(ctx, "_impl_obj", None)
        m["context_impl_attrs"] = [a for a in dir(impl) if "pid" in a.lower()
                                   or "process" in a.lower()][:10]
        b = ctx.browser
        m["context_browser_is_none"] = b is None
        kids = common.descendants(os.getpid())
        m["descendants_of_this_python"] = [(k["name"], k["pid"]) for k in kids]
        ctx.close()
    shutil.rmtree(prof, ignore_errors=True)
    return m


def main():
    common.baseline()
    srv, base = fixtures_server.start()
    lanes = ["chromium", "moz-firefox"]
    mech = mechanics()
    print("mechanics:", json.dumps(mech, indent=1)[:800])
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        lanes = [only]
    for lane in lanes:
        scenario(lane, "nojob", "graceful")
        scenario(lane, "nojob", "taskkill_f")
        scenario(lane, "job", "taskkill_f")
        scenario(lane, "nojob", "parent_and_driver")
        scenario(lane, "job", "parent_and_driver")
        hung_navigation(lane, base)
    time.sleep(2)
    left, _ = common.sweep_orphans(dry_run=True)
    srv.shutdown()
    common.jdump(os.path.join(OUT, "s7_process_hygiene.json"),
                 {"mechanics": mech, "scenarios": results, "orphans_at_exit": left})
    print("\nORPHANS AT EXIT:", len(left), left)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print("emergency sweep:", common.sweep_orphans(dry_run=False)[1])
