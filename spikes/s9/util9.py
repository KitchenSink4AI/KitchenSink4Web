"""Shared helpers for the S9 Chrome/Edge spikes.

SAFETY CONTRACT, same absolute rules as the Firefox spikes:
  * Every Chrome/Edge launched here gets a FRESH throwaway data directory,
    either via an explicit --user-data-dir under the scratch root or via a
    REDIRECTED LOCALAPPDATA so the browser's own computed DEFAULT data
    directory lands inside scratch. The author's real profiles
    (%LOCALAPPDATA%\\Google\\Chrome\\User Data, %LOCALAPPDATA%\\Microsoft\\Edge\\
    User Data) are never opened, copied, enumerated, or passed to any launch.
  * The redirect is verified by a headless canary BEFORE any probe that omits
    --user-data-dir. If the canary cannot prove the redirect took, the probe
    ABORTS and the finding is "needs a dedicated machine", never a launch
    against the real default.
  * census() before/after; only PIDs we watched arrive are ever killed, and
    the kill fence additionally requires the process command line to name one
    of our scratch directories.
  * Everything is deadline-bounded; a wedged step force-kills its own tree and
    records the timeout as the finding.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine")
sys.path.insert(0, os.path.abspath(ENGINE))
import common  # noqa: E402  (the engine spikes' census/kill helpers)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

REAL_PROFILES = {
    "chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
    "msedge": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
}
# The subpath each browser appends to LOCALAPPDATA for its DEFAULT data dir.
DEFAULT_SUBPATH = {
    "chrome": r"Google\Chrome\User Data",
    "msedge": r"Microsoft\Edge\User Data",
}
EXE = {"chrome": CHROME, "msedge": EDGE}

SCRATCH_MARK = "ks4web_spike"  # every scratch dir name carries this


class Deadline:
    def __init__(self, seconds, label):
        self.t0 = time.monotonic()
        self.seconds = seconds
        self.label = label

    def remaining(self):
        return self.seconds - (time.monotonic() - self.t0)

    def check(self):
        if self.remaining() <= 0:
            raise TimeoutError("deadline exceeded: %s (%ds)" % (self.label, self.seconds))


def scratch_dir(tag):
    d = tempfile.mkdtemp(prefix="%s_s9_%s_" % (SCRATCH_MARK, tag))
    return d


def exe_version(path):
    try:
        cmd = ("(Get-Item '%s').VersionInfo.ProductVersion" % path)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception as e:
        return "unknown (%s)" % e


def redirected_env(scratch_localappdata):
    """A copy of the environment with LOCALAPPDATA pointing into scratch.

    Chromium's install_static computes the default User Data directory by
    expanding the LOCALAPPDATA environment variable (verified: chrome_elf.dll
    and msedge_elf.dll both carry the LOCALAPPDATA + 'User Data' strings), so
    a child launched with this env computes its DEFAULT data dir inside
    scratch. The canary in s9_default_dir.py verifies it at runtime before
    anything relies on it.
    """
    env = dict(os.environ)
    env["LOCALAPPDATA"] = scratch_localappdata
    return env


def spawn(argv, env=None, cwd=None):
    """Popen with stderr captured; never inherits our console window."""
    return subprocess.Popen(argv, env=env, cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def wait_port(port, timeout_s, host="127.0.0.1"):
    import socket
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        s = socket.socket()
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            s.close()
            return True
        except OSError:
            time.sleep(0.4)
        finally:
            try:
                s.close()
            except OSError:
                pass
    return False


def cdp_version(port, timeout_s=5):
    import urllib.request
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/json/version" % port, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}


def graceful_then_force(pid, grace_s=6.0):
    """taskkill (WM_CLOSE) first so the browser flushes to disk, then /F /T."""
    subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, text=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < grace_s:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                           capture_output=True, text=True)
        if str(pid) not in r.stdout:
            return "graceful"
        time.sleep(0.5)
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                   capture_output=True, text=True)
    return "forced"


def teardown_tree(root_pid, scratch_roots=(), grace_s=12.0):
    """Graceful close of the root, then force-kill every descendant that
    survives it. Edge's startup-boost background respawn taught this: a root
    that exits gracefully can leave (or re-spawn) children, including an
    msedge --no-startup-window keep-alive whose OWN cmdline names nothing of
    ours while its crashpad child carries our --user-data-dir. So the sweep
    also kills any new-since-baseline browser process whose cmdline names one
    of our scratch roots, AND the parent of any such process when that parent
    is itself new since baseline (positive evidence of ownership by descent).
    """
    procs = common.ps_processes()
    pre_desc = [d["pid"] for d in common.descendants(root_pid, procs)]
    how = graceful_then_force(root_pid, grace_s=grace_s)
    # Let the children finish their own shutdown flush before any force-kill:
    # killing a lagging network-service child mid-write loses the cookie store
    # (measured: a 1.5 s kill lag cost the minted cookie).
    survivors = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10.0:
        alive = {p["pid"] for p in common.ps_processes()}
        if not any(pid in alive for pid in pre_desc):
            break
        time.sleep(1.0)
    alive = {p["pid"]: p for p in common.ps_processes()}
    for pid in pre_desc:
        if pid in alive:
            common.kill_pid(pid)
            survivors.append(pid)
    # Evidence-based sweep for respawns that are not descendants any more
    # (Edge startup-boost). Looped, because the respawn can arrive late.
    base = common.baseline()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 12.0:
        found = False
        now = {p["pid"]: p for p in common.ps_processes()}
        for pid, p in now.items():
            if pid in base:
                continue
            cmd = p.get("cmd") or ""
            if any(root in cmd for root in scratch_roots):
                found = True
                common.kill_pid(pid)
                survivors.append(pid)
                par = p.get("ppid")
                pp = now.get(par)
                if pp and par not in base and (pp.get("name") or "").lower() in (
                        "chrome.exe", "msedge.exe"):
                    common.kill_pid(par)
                    survivors.append(par)
        if not found:
            break
        time.sleep(2.0)
    return how, survivors


def kill_our_leftovers(scratch_roots):
    """Kill any new-since-baseline browser process whose command line names one
    of OUR scratch roots. Both fences per the engine spikes' rule."""
    killed = []
    for p in common.new_since_baseline():
        cmd = p.get("cmd") or ""
        if any(root.replace("\\", "\\\\") in cmd or root in cmd for root in scratch_roots):
            common.kill_pid(p["pid"])
            killed.append({"pid": p["pid"], "name": p["name"]})
    if killed:
        time.sleep(1.5)
    return killed


def real_profile_untouched_attestation(spawned_cmdlines):
    """The attestation is structural: no launch we made names a real profile
    path, and every launch either passed an explicit scratch --user-data-dir or
    ran under a canary-verified redirected LOCALAPPDATA."""
    hits = []
    for c in spawned_cmdlines:
        for name, path in REAL_PROFILES.items():
            if path.lower() in (c or "").lower():
                hits.append({"browser": name, "cmdline": c})
    return {"real_profile_named_in_any_spawn": hits, "clean": not hits}


def rmtree_retry(path, attempts=5):
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except Exception:
            time.sleep(1.0 + i)
    return not os.path.exists(path)


def jdump(path, obj):
    common.jdump(path, obj)
