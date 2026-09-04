"""Process hygiene, tested where it can be tested without launching a browser.

The end-to-end proof is `scripts/gate_hygiene.py`, which hard-kills a real
server holding a real browser and counts what is left. What lives here is
everything that can fail SILENTLY, because a silent failure in this subsystem
is invisible until somebody has 42 orphaned Chromes.

The ctypes test is the important one. S7 hit the trap and DESIGN 4.7 records
it: HANDLEs are pointer-sized, ctypes' default `c_int` restype truncates them
on win64, every subsequent call fails with ERROR_INVALID_HANDLE, and the
reaper silently does nothing. A silent no-op reaper passes every test that
only checks the reaper exists.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

import pytest

from kitchensink4web.engine import hygiene

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.skipif(not WINDOWS, reason="Windows-first by design")


# ------------------------------------------------------------- the ctypes


def test_handle_restypes_are_pointer_sized():
    """The trap, asserted rather than remembered."""
    k32 = hygiene._kernel32()
    for name in ("CreateJobObjectW", "GetCurrentProcess",
                 "CreateToolhelp32Snapshot", "OpenProcess"):
        assert getattr(k32, name).restype is ctypes.c_void_p, (
            f"{name} returns a HANDLE and its restype is not c_void_p; on "
            f"win64 that truncates the handle and every later call fails "
            f"with ERROR_INVALID_HANDLE while the reaper reports nothing "
            f"wrong")


def test_the_job_object_can_actually_be_created():
    """A job object that fails to create is a defense that is not there. The
    status string says which, and it is reported in manage_session."""
    job = hygiene.ProcessJob()
    result = job.ensure()
    assert result["job"] is True, result
    assert job.handle
    assert job.ensure()["status"] == "kill-on-job-close"    # idempotent


def test_the_job_object_can_be_turned_off_for_embedding(monkeypatch):
    monkeypatch.setenv("KS4WEB_JOB_OBJECT", "0")
    job = hygiene.ProcessJob()
    assert job.ensure()["job"] is False
    assert "disabled" in job.status


def test_job_context_reports_the_ambient_job():
    """What a gate needs to know before it believes a zero-orphan result: an
    inherited kill-on-close job reaps the tree for you."""
    context = hygiene.job_context()
    assert set(context) >= {"in_job"}
    if context["in_job"]:
        assert "kill_on_job_close" in context


# ------------------------------------------------------- the process table


def test_the_process_table_is_fast_and_carries_parentage():
    table = hygiene.snapshot_processes()
    assert len(table) > 10
    me = next(p for p in table if p["pid"] == os.getpid())
    assert me["ppid"] > 0
    assert me["name"].lower().startswith("python")


def test_alive_distinguishes_running_from_merely_addressable():
    """OpenProcess succeeds on an exited process for as long as anyone holds
    a handle, and a parent holding a Popen object holds one. Getting this
    wrong makes a teardown check report survivors that are already dead."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert hygiene.alive(proc.pid) is False
    assert hygiene.alive(os.getpid()) is True


def test_descendants_defends_against_pid_reuse():
    """A parent-PID field points at a NUMBER rather than at a process. A
    naive walk adopts any stranger whose parent PID matches a recycled one,
    and on this machine that turned a five process browser tree into a forty
    process claim, which would have authorized forty kills."""
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        kids = hygiene.descendants(os.getpid())
        assert proc.pid in [k["pid"] for k in kids]

        fake_parent = proc.pid
        table = hygiene.snapshot_processes() + [
            {"pid": 424242, "ppid": fake_parent, "name": "impostor.exe"}]
        # 424242 does not exist, so it has no creation time and cannot be
        # excluded by age; what matters is that a REAL older process claiming
        # a younger parent is dropped.
        older = min((p for p in table if p["pid"] not in (0, 4)),
                    key=lambda p: hygiene.creation_time(p["pid"]) or 1 << 62)
        table.append({"pid": older["pid"], "ppid": fake_parent,
                      "name": older["name"]})
        walked = [k["pid"] for k in hygiene.descendants(os.getpid(), table)]
        assert older["pid"] not in walked, (
            "a process older than its claimed parent was adopted as a child")
    finally:
        proc.kill()


def test_creation_time_is_the_identity_fence():
    assert hygiene.creation_time(os.getpid()) is not None
    assert hygiene.creation_time(999999) is None


def test_cpu_time_is_readable_for_the_idle_park_check():
    """Defense 3 is verified by CPU measurement rather than by asserting that
    a park happened."""
    value = hygiene.cpu_time(os.getpid())
    assert value is not None and value >= 0


# ------------------------------------------------------------ the journal


def test_the_journal_only_adopts_browser_shaped_children(tmp_path,
                                                         monkeypatch):
    """A filter on ADOPTION, not a sweep by name. A PowerShell process we
    happened to spawn for a CIM query is not a browser we own, and keeping it
    out of the journal is what stops the journal from ever authorizing a kill
    it should not."""
    monkeypatch.setattr(hygiene, "STATE_DIR", tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"])
    try:
        journal = hygiene.OwnedProcesses("s1", str(tmp_path / "profile"), "A")
        journal.adopt_descendants()
        assert proc.pid not in journal.pids, (
            "a plain python child was adopted as a browser process")
    finally:
        proc.kill()
        journal.close()


def test_survivors_ignore_a_recycled_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(hygiene, "STATE_DIR", tmp_path)
    journal = hygiene.OwnedProcesses("s1", str(tmp_path / "profile"), "A")
    journal.record([os.getpid()])
    assert journal.survivors() == [os.getpid()]
    journal.pids[os.getpid()] = 1              # a creation time that is not ours
    assert journal.survivors() == []
    journal.close()


def test_a_journal_with_a_live_owner_is_left_alone(tmp_path, monkeypatch):
    """A concurrently running KS4Web is not a corpse. Killing its browsers
    would be the same violation as killing a stranger's, one level up."""
    monkeypatch.setattr(hygiene, "STATE_DIR", tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"])
    try:
        journal = hygiene.OwnedProcesses("sLive", str(tmp_path / "p"), "A")
        journal.owner_pid = proc.pid
        journal.path = tmp_path / f"session-{proc.pid}-sLive.json"
        journal.record([proc.pid])
        report = hygiene.reap_orphans(dry_run=True)
        assert report["skipped_live_owner"] == 1
        assert report["killed"] == []
    finally:
        proc.kill()


def test_the_reaper_declines_a_foreign_profile(tmp_path, monkeypatch):
    """The last fence fires only on positive evidence that a process belongs
    to somebody else. Requiring positive evidence of OWNERSHIP instead would
    decline every browser helper, since a renderer does not always repeat the
    profile flag its root was launched with, and declining to kill a helper is
    how the orphan gets left behind."""
    owned = r"C:\Temp\ks4web_profile_a_xyz"
    assert hygiene._names_a_foreign_profile(
        r'chrome.exe --user-data-dir="C:\Users\me\AppData\Chrome" about:blank',
        owned) is True
    assert hygiene._names_a_foreign_profile(
        f'chrome.exe --user-data-dir={owned} about:blank', owned) is False
    assert hygiene._names_a_foreign_profile(
        "chrome.exe --type=renderer --lang=en", owned) is False
    assert hygiene._names_a_foreign_profile("", owned) is False


def test_only_owned_profile_directories_are_ever_removed(tmp_path):
    """A journal file on disk is exactly the kind of input that should never
    be able to talk the server into deleting an arbitrary directory."""
    stranger = tmp_path / "important_user_data"
    stranger.mkdir()
    (stranger / "file.txt").write_text("keep me", encoding="utf-8")
    hygiene._remove_tree(stranger)
    assert stranger.exists()

    ours = tmp_path / f"{hygiene.PROFILE_MARKER}a_abc"
    ours.mkdir()
    hygiene._remove_tree(ours)
    assert not ours.exists()


def test_new_profile_directories_are_fresh_empty_and_marked(monkeypatch,
                                                            tmp_path):
    """KS4Web never opens the user's real profile: not read-write, not
    read-only, not just once. Every profile is a freshly created empty
    directory, never a copy of anything the user owns."""
    monkeypatch.setenv("KS4WEB_PROFILE_ROOT", str(tmp_path))
    profile = hygiene.new_profile_dir("ff")
    try:
        assert profile.is_dir()
        assert not list(profile.iterdir())
        assert hygiene.PROFILE_MARKER in profile.name
        assert str(tmp_path) in str(profile)
    finally:
        hygiene._remove_tree(profile)
