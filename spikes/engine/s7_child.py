"""S7 victim process: stands in for the KS4Web server holding a live browser.

Launches one browser on the named lane, writes every PID it can see to a JSON
file, then blocks. The orchestrator kills it in various ways and counts what is
left behind.

Usage: s7_child.py <lane> <pidfile> [job|nojob]
  job -> the child first puts ITSELF in a Windows job object with
         JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, which is the reaper design under
         test: if the last handle dies with the process, Windows kills the tree
         even on an unhandleable SIGKILL-equivalent.
"""
import ctypes
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def enter_job():
    """Put this process (and every descendant) into a kill-on-close job."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_ulong),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                    ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    # HANDLEs are pointer-sized; ctypes' default c_int restype truncates them on
    # win64 and every subsequent call fails with ERROR_INVALID_HANDLE (6).
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                            ctypes.c_void_p, ctypes.c_ulong]
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return {"job": False, "err": "CreateJobObjectW failed %d" % ctypes.get_last_error()}
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                     ctypes.byref(info), ctypes.sizeof(info))
    if not ok:
        return {"job": False, "err": "SetInformationJobObject failed %d" % ctypes.get_last_error()}
    ok = k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())
    if not ok:
        return {"job": False, "err": "AssignProcessToJobObject failed %d" % ctypes.get_last_error()}
    globals()["_job_handle"] = job  # keep the handle alive for process lifetime
    return {"job": True}


def main():
    lane = sys.argv[1]
    pidfile = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "nojob"
    info = {"lane": lane, "mode": mode, "self_pid": os.getpid()}
    if mode == "job":
        info["job_result"] = enter_job()

    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    prof = common.throwaway_profile("s7_" + lane.replace("-", ""))
    info["profile"] = prof
    if lane == "moz-firefox":
        ctx = p.firefox.launch_persistent_context(prof, channel="moz-firefox", headless=True,
                                                  args=common.SAFE_FF_ARGS, timeout=90000)
    else:
        ctx = p.chromium.launch_persistent_context(prof, headless=True, timeout=90000)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("about:blank")

    kids = common.descendants(os.getpid())
    info["descendants"] = kids
    info["descendant_pids"] = [k["pid"] for k in kids]
    info["browser_pids"] = [k["pid"] for k in kids
                            if k["name"].lower() in ("firefox.exe", "chrome.exe",
                                                     "chrome-headless-shell.exe")]
    info["node_pids"] = [k["pid"] for k in kids if k["name"].lower() == "node.exe"]
    info["ready"] = True
    with open(pidfile, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    print("child ready", json.dumps(info["browser_pids"]))
    sys.stdout.flush()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
