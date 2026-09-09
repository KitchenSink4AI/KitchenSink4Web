"""Process hygiene: the three defenses, the owned-PID journal, and the reaper.

DESIGN 4.7. This is the least glamorous module in the build and possibly the
most winnable row in the category: chrome-devtools-mcp #2621 is open and
unanswered against 42 orphaned Chrome roots plus roughly 300 helpers across 83
connections, all at ppid=1, and MEASURED reproduced the same defect
first-party on this machine.

The generalizable lesson from the incumbent's own fix history is that it has
correct teardown on every path where it gets to run code and no teardown at
all on the path MCP clients actually use, because `process.on('SIGTERM')`
handlers do not run under SIGKILL and hosts routinely force-kill workers. So
none of the three defenses here is a signal handler.

**Defense 1: a liveness mechanism that outlives the parent.** Playwright's own
death pipe does the work today, proven by S7's breakaway re-run, and KS4Web
adds a Windows job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` as a
belt-and-braces backstop: the handle dies with the process whatever kills it,
the job closes, and Windows reaps the tree without any of our code running.

**Defense 2: a startup reaper, keyed on OWNED PID only.** House rule,
inherited and absolute: never sweep by process name, never touch a process
KS4Web did not spawn. The journal on disk is the authority, and every kill
passes two independent fences (recorded PID plus recorded process creation
time, which is what defeats PID reuse; the profile directory in the command
line is a third where a command line is available).

**Defense 3: an idle timeout** that parks dormant pages to `about:blank` and
then recycles the context. #2599 measured a dormant page burning 28 to 30
percent CPU for hours and dropping to 0.13 percent after exactly that park.
The park itself lives in `session.py`, which owns the pages; what lives here
is the CPU accounting that proves it worked.

Four mechanical facts from S7, all measured, all load-bearing:

1. Job objects work from plain CPython ctypes, **with the trap that HANDLE
   restypes must be `c_void_p`**. ctypes' default `c_int` restype truncates a
   pointer-sized handle on win64 and every later call fails with
   `ERROR_INVALID_HANDLE (6)`, after which the reaper silently does nothing.
   A silent no-op reaper passes every test that only checks the reaper exists,
   so the restypes are set explicitly below and a test asserts they are.
2. Child PID enumeration needs no third-party dependency. S7 used
   `Get-CimInstance Win32_Process` at roughly 1.0 s for 557 processes, which
   is shutdown speed rather than hot-path speed. This module improves on that
   with `CreateToolhelp32Snapshot`, which returns pid, ppid, and image name in
   single-digit milliseconds, and falls back to CIM when it cannot.
3. **Playwright's Python API does not expose the browser PID**, so the journal
   is populated from the process table at launch, not from the driver.
4. A bounded per-operation timeout genuinely frees the server, so hangs are a
   timeout concern rather than a hygiene one.

This module imports from `policy/` and never the other way round.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path

WINDOWS = os.name == "nt"

#: Where the owned-PID journal lives. One file per live session, named by the
#: owning process, so a LATER process can find what an earlier one left behind.
#: That is the whole point: the reaper runs at startup, after the crash.
STATE_DIR = Path(
    os.environ.get("KS4WEB_STATE_DIR")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ks4web")
)

#: Every profile directory KS4Web creates carries this marker in its name, so
#: a command line can be matched against it. It is a LATER fence, never the
#: first: matching on a name alone is how you kill somebody else's browser.
PROFILE_MARKER = "ks4web_profile_"

#: What may ENTER the journal. This is a filter on adoption, not a sweep: a
#: process still has to be a descendant of ours that appeared during our own
#: launch before its name is even considered. The house rule bans sweeping BY
#: name; deciding that a PowerShell process we happened to spawn for a CIM
#: query is not a browser we own is the opposite of that, and it keeps the
#: journal from ever authorizing a kill it should not.
BROWSER_PROCESS_NAMES = frozenset({
    "chrome.exe", "chrome-headless-shell.exe", "headless_shell.exe",
    "msedge.exe", "firefox.exe", "plugin-container.exe", "crashhelper.exe",
    "node.exe", "playwright.exe", "chromium.exe", "webkit.exe",
    "minibrowser.exe", "wpewebprocess.exe",
})

#: Command-line shapes that name a profile directory. Used by the reaper's
#: last fence to decline a PID whose command line names somebody ELSE's
#: profile, which is the one signal that survives a journal being wrong.
_PROFILE_FLAGS = ("--user-data-dir=", "--profile ", "-profile ")

JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000


# --------------------------------------------------------------- job objects


if WINDOWS:  # pragma: no branch - the module is Windows-first by design

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _JOB_BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_ulong),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                    ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong)]

    class _JOB_EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _JOB_BASIC),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260)]

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_ulong),
                    ("dwHighDateTime", ctypes.c_ulong)]


def _kernel32():
    """kernel32 with every HANDLE typed as a pointer.

    S7's trap, recorded in DESIGN 4.7 fact 1: leaving ctypes' default `c_int`
    restype on a handle-returning call truncates the handle on win64, every
    subsequent call fails with ERROR_INVALID_HANDLE, and the reaper becomes a
    silent no-op. That is the worst possible failure mode for a safety
    mechanism, because nothing observable changes."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    k32.Process32First.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4
    return k32


class ProcessJob:
    """Defense 1's backstop: a kill-on-close job holding this process.

    Children inherit the job, so when the server dies by any means at all,
    including a hard kill that runs none of our code, the last handle closes
    and Windows reaps the browser tree. Playwright's death pipe is doing this
    work already (S7 proved it under `CREATE_BREAKAWAY_FROM_JOB`); this is the
    second mechanism, cheap and provably functional.

    Set `KS4WEB_JOB_OBJECT=0` when embedding KS4Web inside a larger process
    whose tree should not be tied to KS4Web's lifetime. It stays ON by default
    because the default deployment is a server process the client owns."""

    def __init__(self) -> None:
        self.handle: int | None = None
        self.status: str = "not-attempted"

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("KS4WEB_JOB_OBJECT", "1").strip().lower() not in (
            "0", "false", "off", "no")

    def ensure(self) -> dict:
        """Idempotent. Returns a status dict rather than raising, because a
        job object is a backstop and failing to get one is a degraded defense
        rather than a reason to refuse a browser."""
        if self.handle is not None:
            return {"job": True, "status": self.status}
        if not WINDOWS:
            self.status = "skipped: not Windows"
            return {"job": False, "status": self.status}
        if not self.enabled():
            self.status = "disabled by KS4WEB_JOB_OBJECT=0"
            return {"job": False, "status": self.status}
        k32 = _kernel32()
        job = k32.CreateJobObjectW(None, None)
        if not job:
            self.status = f"CreateJobObjectW failed {ctypes.get_last_error()}"
            return {"job": False, "status": self.status}
        info = _JOB_EXTENDED()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
                job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            self.status = (
                f"SetInformationJobObject failed {ctypes.get_last_error()}")
            return {"job": False, "status": self.status}
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            self.status = (
                f"AssignProcessToJobObject failed {ctypes.get_last_error()}")
            return {"job": False, "status": self.status}
        self.handle = job  # held for the process lifetime, deliberately
        self.status = "kill-on-job-close"
        return {"job": True, "status": self.status}


JOB = ProcessJob()

JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
_JobObjectExtendedLimitInformation = 9


def job_context() -> dict:
    """What job object, if any, this process is already inside.

    S7's confound, generalized into something a gate can ask about. A shell
    that owns a `KILL_ON_JOB_CLOSE` job reaps the browser tree for you, so an
    orphan test run inside one comes back green whether or not the server has
    any teardown at all. That is not a passing gate, it is an untested one,
    and the difference is only visible from here."""
    res: dict = {"in_job": None}
    if not WINDOWS:
        return {"in_job": False, "why": "not Windows"}
    import ctypes.wintypes as wintypes

    k32 = _kernel32()
    k32.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.BOOL)]
    k32.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.c_void_p]
    flag = wintypes.BOOL()
    if not k32.IsProcessInJob(k32.GetCurrentProcess(), None,
                              ctypes.byref(flag)):
        return {"in_job": None, "why": "IsProcessInJob failed"}
    res["in_job"] = bool(flag.value)
    if not flag.value:
        return res
    info = _JOB_EXTENDED()
    written = ctypes.c_ulong()
    if not k32.QueryInformationJobObject(
            None, _JobObjectExtendedLimitInformation, ctypes.byref(info),
            ctypes.sizeof(info), ctypes.byref(written)):
        res["why"] = "QueryInformationJobObject failed"
        return res
    flags = info.BasicLimitInformation.LimitFlags
    res["limit_flags"] = hex(flags)
    res["kill_on_job_close"] = bool(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    res["breakaway_ok"] = bool(flags & JOB_OBJECT_LIMIT_BREAKAWAY_OK)
    res["silent_breakaway_ok"] = bool(
        flags & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK)
    return res


# ------------------------------------------------------------ process table


def snapshot_processes() -> list[dict]:
    """[{pid, ppid, name}] for every process, in single-digit milliseconds.

    Toolhelp32 rather than CIM. S7 measured `Get-CimInstance Win32_Process` at
    roughly 1.0 s for 557 processes, which is fine for shutdown and far too
    slow to run on every launch. This carries no command line; `command_lines`
    fetches those for the handful of PIDs that need one."""
    if not WINDOWS:
        return _cim_processes()
    k32 = _kernel32()
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return _cim_processes()
    out: list[dict] = []
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            out.append({
                "pid": int(entry.th32ProcessID),
                "ppid": int(entry.th32ParentProcessID),
                "name": entry.szExeFile.decode("mbcs", "replace"),
            })
            ok = k32.Process32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _cim_processes() -> list[dict]:
    """The S7 path, kept as a fallback and for command lines."""
    cmd = ("Get-CimInstance Win32_Process | Select-Object ProcessId,"
           "ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress "
           "-Depth 2")
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=120)
        data = json.loads(res.stdout)
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"pid": p.get("ProcessId"), "ppid": p.get("ParentProcessId"),
             "name": p.get("Name") or "",
             "cmd": (p.get("CommandLine") or "")[:600]} for p in data]


def command_lines(pids: set[int]) -> dict[int, str]:
    """Command lines for a named handful of PIDs. Used only by the reaper's
    third fence, and only when there is something to consider killing."""
    if not pids or not WINDOWS:
        return {}
    return {p["pid"]: p.get("cmd", "") for p in _cim_processes()
            if p.get("pid") in pids}


def creation_time(pid: int) -> int | None:
    """Process creation time as a FILETIME integer, or None.

    This is the fence that defeats PID reuse. A recorded PID that has been
    recycled by Windows onto some unrelated process has a different creation
    time, so the reaper declines it rather than killing a stranger."""
    if not WINDOWS:
        return None
    k32 = _kernel32()
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        created, exited, kern, user = (_FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(created),
                                   ctypes.byref(exited), ctypes.byref(kern),
                                   ctypes.byref(user)):
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        k32.CloseHandle(h)


def cpu_time(pid: int) -> float | None:
    """Kernel plus user CPU seconds for one process.

    Defense 3 is verified by CPU measurement rather than by asserting that a
    park happened, because "we called goto about:blank" is not evidence that
    the page stopped burning a core (chrome-devtools-mcp #2599: 28 to 30
    percent for hours, 0.13 percent after the park)."""
    if not WINDOWS:
        return None
    k32 = _kernel32()
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        created, exited, kern, user = (_FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(created),
                                   ctypes.byref(exited), ctypes.byref(kern),
                                   ctypes.byref(user)):
            return None
        total = ((kern.dwHighDateTime << 32) | kern.dwLowDateTime) + \
                ((user.dwHighDateTime << 32) | user.dwLowDateTime)
        return total / 1e7  # FILETIME is 100ns ticks
    finally:
        k32.CloseHandle(h)


def alive(pid: int) -> bool:
    """Running, as opposed to merely addressable.

    `OpenProcess` succeeds on a process that has already exited for as long as
    anyone still holds a handle to it, and a parent holding a `Popen` object
    holds one, so "the handle opened" is not evidence of life. The wait
    object is: a process handle signals when the process exits. Getting this
    wrong makes a teardown check report survivors that are already dead, which
    is the same disease as a false success in the other direction."""
    if not WINDOWS:
        return False
    k32 = _kernel32()
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    handle = k32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        return k32.WaitForSingleObject(handle, 0) != WAIT_OBJECT_0
    finally:
        k32.CloseHandle(handle)


def descendants(root_pid: int, table: list[dict] | None = None) -> list[dict]:
    """Every process below `root_pid`, transitively, with PID reuse defended.

    Windows recycles PIDs, and a parent-PID field points at a NUMBER rather
    than at a process, so a naive walk adopts any stranger whose parent PID
    happens to match a recycled one. On this machine that turned a five
    process browser tree into a forty process claim, which would have
    authorized forty kills. A child cannot predate its parent, so comparing
    creation times drops every one of those without dropping a real child."""
    table = table if table is not None else snapshot_processes()
    kids: dict[int, list[dict]] = {}
    for proc in table:
        kids.setdefault(proc["ppid"], []).append(proc)
    born: dict[int, int | None] = {root_pid: creation_time(root_pid)}
    out: list[dict] = []
    stack = [root_pid]
    seen = {root_pid}
    while stack:
        parent = stack.pop()
        for child in kids.get(parent, []):
            pid = child["pid"]
            if pid in seen:
                continue
            child_born = creation_time(pid)
            parent_born = born.get(parent)
            if (child_born is not None and parent_born is not None
                    and child_born < parent_born):
                continue     # older than its claimed parent: a recycled PID
            seen.add(pid)
            born[pid] = child_born
            out.append(child)
            stack.append(pid)
    return out


def kill(pid: int) -> bool:
    """Kill one PID. Never called except through the journal's fences."""
    try:
        res = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                             capture_output=True, text=True, timeout=30)
        return res.returncode == 0
    except Exception:
        return False


# ------------------------------------------------------- the owned journal


class OwnedProcesses:
    """The owned-PID journal: the only authority for what KS4Web may kill.

    One JSON file per live session under the state directory, carrying the
    owning server PID, the profile directory, and every browser PID with the
    creation time it had when we recorded it. Written at launch and deleted on
    a clean close, so anything still on disk is either live or a crash
    residue, and the reaper can tell which by asking whether the owner is."""

    def __init__(self, session_id: str, profile_dir: str, lane: str) -> None:
        self.session_id = session_id
        self.profile_dir = profile_dir
        self.lane = lane
        self.owner_pid = os.getpid()
        self.pids: dict[int, int | None] = {}
        self.names: dict[int, str] = {}
        self.path = STATE_DIR / f"session-{self.owner_pid}-{session_id}.json"

    def record(self, pids: list[int], names: dict[int, str] | None = None
               ) -> list[int]:
        for pid in pids:
            if pid not in self.pids:
                self.pids[pid] = creation_time(pid)
                if names and pid in names:
                    self.names[pid] = names[pid]
        self.flush()
        return sorted(self.pids)

    def adopt_descendants(self, since: set[int] | None = None) -> list[int]:
        """Record the browser processes this session started.

        DESIGN 4.7 fact 3: Playwright does not expose the browser PID, so the
        journal is populated from the process table. Everything below this
        process that was not there before the launch belongs to the launch,
        and of those, the browser-shaped ones are what the journal authorizes
        a kill against."""
        table = snapshot_processes()
        fresh = [p for p in descendants(os.getpid(), table)
                 if since is None or p["pid"] not in since]
        owned = [p for p in fresh
                 if p["name"].lower() in BROWSER_PROCESS_NAMES]
        return self.record([p["pid"] for p in owned],
                           {p["pid"]: p["name"] for p in owned})

    def flush(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "owner_pid": self.owner_pid,
            "session": self.session_id,
            "lane": self.lane,
            "profile_dir": self.profile_dir,
            "started": time.time(),
            "pids": {str(k): v for k, v in self.pids.items()},
            "names": {str(k): v for k, v in self.names.items()},
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def close(self) -> None:
        """A clean close removes the journal entry. What remains is residue."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def survivors(self) -> list[int]:
        """Recorded PIDs still running, past two fences that ask different
        questions.

        The creation time answers IDENTITY: this PID still names the process
        we recorded, rather than a stranger Windows recycled the number onto.
        It does not answer LIVENESS, and reading it as though it did is how
        this method used to report a browser alive after every process it
        owned was dead. `creation_time` opens a handle, and `alive` above
        explains why that keeps succeeding on a process that has already
        exited: somebody still holds a handle to it, the node driver being
        the somebody in the case that produced the wrong answer. So the wait
        object gets the second question, and a PID is a survivor only when it
        is both the process we recorded and one that is still running."""
        out = []
        for pid, born in self.pids.items():
            now = creation_time(pid)
            if now is None or (born is not None and now != born):
                continue     # gone, or a recycled PID wearing its number
            if alive(pid):
                out.append(pid)
        return sorted(out)


def _journal_files() -> list[Path]:
    if not STATE_DIR.is_dir():
        return []
    return sorted(STATE_DIR.glob("session-*.json"))


def reap_orphans(dry_run: bool = False) -> dict:
    """Defense 2. Run at startup, before any browser is launched.

    Every kill passes three fences and the order is the point:

    1. the PID is in a journal KS4Web wrote, and
    2. its creation time still matches what we recorded, which is what makes
       a recycled PID safe, and
    3. where a command line is readable, it names one of our own profile
       directories.

    A journal whose OWNER is still alive is left alone entirely: that is a
    concurrently running KS4Web, not a corpse, and killing its browsers would
    be exactly the "never touch a process we did not spawn" violation this
    function exists to avoid, one level up."""
    report = {"journals": 0, "skipped_live_owner": 0, "killed": [],
              "declined": [], "profiles_removed": [], "dry_run": dry_run}
    for path in _journal_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        report["journals"] += 1
        owner = int(data.get("owner_pid", 0))
        if owner and owner != os.getpid() and alive(owner):
            report["skipped_live_owner"] += 1
            continue
        recorded = {int(p): v for p, v in (data.get("pids") or {}).items()}
        candidates = {pid for pid, born in recorded.items()
                      if creation_time(pid) is not None
                      and (born is None or creation_time(pid) == born)}
        cmds = command_lines(candidates)
        profile = data.get("profile_dir") or ""
        for pid in sorted(candidates):
            cmd = cmds.get(pid, "")
            if _names_a_foreign_profile(cmd, profile):
                # The last fence, and it only fires on positive evidence that
                # this process belongs to somebody else. Requiring positive
                # evidence of OWNERSHIP instead would decline every browser
                # helper process, since a renderer does not always repeat the
                # profile flag its root was launched with, and declining to
                # kill a helper is how the orphan gets left behind.
                report["declined"].append(
                    {"pid": pid, "why": "its command line names a profile "
                                        "directory KS4Web does not own"})
                continue
            if dry_run or kill(pid):
                report["killed"].append(pid)
        profile = data.get("profile_dir")
        if profile and PROFILE_MARKER in str(profile) and not dry_run:
            _remove_tree(Path(profile))
            report["profiles_removed"].append(profile)
        if not dry_run:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    report["audits_removed"] = _reap_audits(dry_run)
    return report


#: How many audit files the state directory keeps, newest first, and how old
#: one may be before it goes regardless. Each FILE is bounded (the JSONL
#: rotates at 2x the 5,000-record ring); the COUNT was not, and the file is
#: named `audit-<pid>.jsonl`, so a client that restarts the server often
#: leaves one per launch forever. The endurance campaign's 30 launches left
#: 30 files totalling 6.1 MB, and the reaper swept journals and profiles and
#: never audits.
AUDIT_KEEP = 20
AUDIT_MAX_AGE_S = 14 * 24 * 3600


def _reap_audits(dry_run: bool = False) -> list[str]:
    """Sweep stale audit files at startup, alongside journals and profiles.

    The CURRENT process's own file is never a candidate: it does not exist
    yet at reap time, and the guard is here so a future caller cannot make
    the reaper eat the log it is writing."""
    try:
        files = sorted(STATE_DIR.glob("audit-*.jsonl"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    mine = STATE_DIR / f"audit-{os.getpid()}.jsonl"
    now = time.time()
    removed: list[str] = []
    for index, path in enumerate(files):
        if path == mine:
            continue
        try:
            too_old = (now - path.stat().st_mtime) > AUDIT_MAX_AGE_S
        except OSError:
            continue
        if index < AUDIT_KEEP and not too_old:
            continue
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        removed.append(str(path))
    return removed


def _names_a_foreign_profile(cmd: str, owned_profile: str) -> bool:
    """True when a command line explicitly names a profile that is not ours.

    Silence is not evidence either way, so an empty or profile-free command
    line returns False and the earlier fences decide."""
    if not cmd:
        return False
    lowered = cmd.lower()
    if not any(flag in lowered for flag in _PROFILE_FLAGS):
        return False
    if owned_profile and owned_profile.lower() in lowered:
        return False
    return PROFILE_MARKER not in lowered


def _remove_tree(path: Path | str) -> None:
    """Remove a profile directory, and only ever one of ours.

    The marker check is not decoration. This function takes a path from a
    journal file on disk, and a journal file is exactly the kind of input that
    should never be able to talk the server into deleting an arbitrary
    directory."""
    import shutil
    path = Path(path)
    if PROFILE_MARKER not in str(path):
        return
    shutil.rmtree(path, ignore_errors=True)


def new_profile_dir(tag: str = "a") -> Path:
    """A fresh, empty, owned profile directory. Never a copy of anything the
    user owns (DESIGN 4.6: KS4Web never opens the user's real profile, not
    read-write, not read-only, not just once)."""
    import tempfile
    base = os.environ.get("KS4WEB_PROFILE_ROOT") or tempfile.gettempdir()
    Path(base).mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{PROFILE_MARKER}{tag}_", dir=base))
