"""Shared helpers for the KS4Web engine spikes.

SAFETY CONTRACT (enforced here, not by convention):
  * Every Firefox we launch gets a FRESHLY CREATED throwaway profile directory
    under the system temp dir and the `-no-remote` flag, so it cannot hand off
    to, attach to, or otherwise disturb a Firefox the user already has running.
  * The user's real profile directory is never read, copied, or enumerated.
  * `census()` snapshots browser PIDs before/after so every process this spike
    starts is accounted for and no pre-existing process is ever killed.
"""
import json
import os
import subprocess
import tempfile
import time

BROWSER_NAMES = ("firefox.exe", "chrome.exe", "chrome-headless-shell.exe",
                 "msedge.exe", "node.exe", "plugin-container.exe",
                 "crashhelper.exe")

# Anything already running when a spike starts is the USER's and is off limits.
_BASELINE = None


def ps_processes():
    """pid, ppid, name, exe for every process, via CIM (no third-party deps)."""
    cmd = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,"
           "Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress -Depth 2")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                         capture_output=True, text=True, timeout=120)
    try:
        data = json.loads(out.stdout)
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    res = []
    for p in data:
        res.append({"pid": p.get("ProcessId"), "ppid": p.get("ParentProcessId"),
                    "name": (p.get("Name") or ""), "exe": p.get("ExecutablePath") or "",
                    "cmd": (p.get("CommandLine") or "")[:400]})
    return res


def census(names=BROWSER_NAMES):
    return [p for p in ps_processes() if p["name"].lower() in [n.lower() for n in names]]


def baseline():
    """PIDs that existed before we started. Never touch these."""
    global _BASELINE
    if _BASELINE is None:
        _BASELINE = {p["pid"] for p in census()}
    return _BASELINE


def new_since_baseline():
    base = baseline()
    return [p for p in census() if p["pid"] not in base]


def descendants(root_pid, procs=None):
    procs = procs or ps_processes()
    kids = {}
    for p in procs:
        kids.setdefault(p["ppid"], []).append(p)
    out, stack = [], [root_pid]
    while stack:
        cur = stack.pop()
        for k in kids.get(cur, []):
            out.append(k)
            stack.append(k["pid"])
    return out


def throwaway_profile(tag="ff"):
    """A fresh, empty directory. Never a copy of anything the user owns."""
    d = tempfile.mkdtemp(prefix="ks4web_spike_%s_" % tag)
    return d


def kill_pid(pid, force=True):
    args = ["taskkill", "/PID", str(pid)]
    if force:
        args.insert(1, "/F")
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def kill_tree(pid):
    r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


PROFILE_MARK = "ks4web_spike"


def sweep_orphans(dry_run=True):
    """Report (and optionally kill) browser processes we started that survived.

    Two independent fences before anything is killed: the PID must be absent
    from the pre-run baseline, AND its command line must name one of our
    throwaway profile directories (every launch here passes one). A browser the
    user opened mid-run satisfies neither test and is never touched.
    """
    leftovers = new_since_baseline()
    killed = []
    if not dry_run:
        for p in leftovers:
            if PROFILE_MARK in (p.get("cmd") or ""):
                kill_pid(p["pid"])
                killed.append(p["pid"])
        time.sleep(1.0)
    return leftovers, killed


# Firefox launch args that MUST accompany any use of the installed binary.
SAFE_FF_ARGS = ["-no-remote"]


def firefox_path():
    for c in (r"C:\Program Files\Mozilla Firefox\firefox.exe",
              r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"):
        if os.path.exists(c):
            return c
    return None


def jdump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)
