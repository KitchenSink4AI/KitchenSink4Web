"""S7b: is the zero-orphan result of S7 real, or an artifact of an ambient job?

If the shell that runs the spike already puts everything in a job object with
KILL_ON_JOB_CLOSE, then "no orphans after killing the parent" would be the
harness reaping the tree, not Playwright's death pipe, and the finding would not
transfer to a KS4Web server started from a desktop MCP client. This checks
whether this process is already in a job and what that job's limit flags are,
then re-runs the harshest kill with the child explicitly broken out of any
inherited job (CREATE_BREAKAWAY_FROM_JOB).
"""
import ctypes
import ctypes.wintypes as w
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402

OUT = os.path.join(HERE, "out")
PY = os.path.join(HERE, "..", "s1", ".venv", "Scripts", "python.exe")
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

JobObjectExtendedLimitInformation = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulonglong)] * 1 + [
        ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong),
        ("e", ctypes.c_ulonglong), ("f", ctypes.c_ulonglong)]


class BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_ulong),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_ulong),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", ctypes.c_ulong),
                ("SchedulingClass", ctypes.c_ulong)]


class EXTENDED(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def job_context():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(w.BOOL)]
    injob = w.BOOL()
    ok = k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(injob))
    res = {"IsProcessInJob_call_ok": bool(ok), "in_job": bool(injob.value)}
    if injob.value:
        info = EXTENDED()
        ret = ctypes.c_ulong()
        k32.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                  ctypes.c_void_p, ctypes.c_ulong,
                                                  ctypes.c_void_p]
        got = k32.QueryInformationJobObject(None, JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info),
                                            ctypes.byref(ret))
        res["query_ok"] = bool(got)
        flags = info.BasicLimitInformation.LimitFlags if got else None
        res["LimitFlags_hex"] = hex(flags) if flags is not None else None
        if flags is not None:
            res["KILL_ON_JOB_CLOSE"] = bool(flags & 0x2000)
            res["BREAKAWAY_OK"] = bool(flags & 0x0800)
            res["SILENT_BREAKAWAY_OK"] = bool(flags & 0x1000)
    return res


def breakaway_kill_test(lane="chromium"):
    """Child launched OUTSIDE any inherited job, then parent+driver hard-killed."""
    pidfile = os.path.join(OUT, "s7b_child_%s.json" % lane.replace("-", ""))
    if os.path.exists(pidfile):
        os.remove(pidfile)
    flags = CREATE_BREAKAWAY_FROM_JOB
    try:
        proc = subprocess.Popen([PY, "-X", "utf8", os.path.join(HERE, "s7_child.py"),
                                 lane, pidfile, "nojob"],
                                creationflags=flags,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        breakaway = "granted"
    except OSError as e:
        breakaway = "DENIED (%s) -- falling back to inherited job" % e
        proc = subprocess.Popen([PY, "-X", "utf8", os.path.join(HERE, "s7_child.py"),
                                 lane, pidfile, "nojob"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    info = None
    for _ in range(120):
        if os.path.exists(pidfile):
            time.sleep(0.4)
            try:
                info = json.load(open(pidfile, encoding="utf-8"))
                break
            except Exception:
                pass
        if proc.poll() is not None:
            o, e = proc.communicate()
            return {"breakaway": breakaway, "error": (o + e)[-500:]}
        time.sleep(0.5)
    watch = info["descendant_pids"] + [info["self_pid"]]
    for pid in [info["self_pid"]] + info["node_pids"]:
        common.kill_pid(pid, force=True)
    t0 = time.perf_counter()
    survivors = watch
    timeline = []
    for _ in range(20):
        time.sleep(1.0)
        live = {p["pid"] for p in common.ps_processes()}
        survivors = [p for p in watch if p in live]
        timeline.append({"t_s": round(time.perf_counter() - t0, 1), "n_alive": len(survivors)})
        if not survivors:
            break
    out = {"lane": lane, "breakaway": breakaway, "watched": len(watch), "browser_pids": info["browser_pids"],
           "timeline": timeline, "orphans": survivors}
    for pid in survivors:
        common.kill_pid(pid)
    shutil.rmtree(info.get("profile", ""), ignore_errors=True)
    return out


if __name__ == "__main__":
    common.baseline()
    ctxinfo = job_context()
    print("job context of the spike process:", json.dumps(ctxinfo))
    lanes = sys.argv[1:] or ["chromium", "moz-firefox"]
    allres = []
    for lane in lanes:
        res = breakaway_kill_test(lane)
        print("breakaway kill test [%s]:" % lane, json.dumps(res)[:600])
        allres.append(res)
    common.jdump(os.path.join(OUT, "s7b_job_context.json"),
                 {"job_context": ctxinfo, "breakaway_kill": allres})
