"""Safety enforcement for the S5/S6 attach spikes.

THE PROFILE SAFETY CONTRACT (enforced in code, not by convention):
  * The real profile (%APPDATA%\\Mozilla\\Firefox\\Profiles\\*) is READ-ONLY
    SOURCE material. It is never opened by a browser, never written to, never
    launched against. Reads happen only to (a) hash a before/after manifest and
    (b) copy the named seed subset OUT.
  * Any profile copy is preceded by a firefox.exe process check; if Firefox is
    running the copy ABORTS.
  * Seeded copies live in the session scratchpad, are securely wiped (random
    overwrite then delete) at spike end, and their CONTENT is never read except
    for one sanctioned query: cookie HOST presence against a fixed candidate
    list (names only, never values, never a full enumeration).
  * Every Firefox launched here gets -no-remote plus the seeded/throwaway
    profile path. All spawned PIDs are journaled and killed at exit; the spike
    ends with a zero-firefox census and a manifest re-hash of the source.
"""
import hashlib
import json
import os
import shutil
import subprocess

REAL_PROFILE = os.path.join(os.environ["APPDATA"], "Mozilla", "Firefox",
                            "Profiles", "ryq08noe.default-release")

# Files whose full content is hashed in the manifest (the seed set plus the
# files Playwright-style prepareUserDataDir hazards would touch).
HASHED_FILES = [
    "cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm",
    "key4.db", "logins.json",
    "places.sqlite", "places.sqlite-wal", "places.sqlite-shm",
    "permissions.sqlite",
    "prefs.js", "user.js", "compatibility.ini", "times.json",
    "extensions.json", "cert9.db",
]


def firefox_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq firefox.exe", "/FO", "CSV"],
                       capture_output=True, text=True)
    return "firefox.exe" in (r.stdout or "")


def assert_firefox_closed(stage):
    if firefox_running():
        raise SystemExit("ABORT (%s): firefox.exe is running; the profile "
                         "safety rule forbids touching the profile now." % stage)


def sha256_file(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def profile_manifest(root=REAL_PROFILE):
    """Recursive stat manifest (relpath, size, mtime_ns) of the REAL profile,
    plus sha256 of the top-level files named in HASHED_FILES. Reads only."""
    stats = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            try:
                st = os.stat(p)
                stats[rel] = [st.st_size, st.st_mtime_ns]
            except OSError as e:
                stats[rel] = ["STAT_ERROR", str(e)]
    hashes = {}
    for fn in HASHED_FILES:
        p = os.path.join(root, fn)
        if os.path.exists(p):
            hashes[fn] = sha256_file(p)
        else:
            hashes[fn] = None
    return {"root": root, "file_count": len(stats), "stats": stats, "hashes": hashes}


def manifest_diff(before, after):
    """Compare two manifests. Returns a dict of differences; empty == untouched."""
    diff = {"hash_changed": [], "stat_changed": [], "added": [], "removed": []}
    for fn, h in before["hashes"].items():
        if after["hashes"].get(fn) != h:
            diff["hash_changed"].append(fn)
    b, a = before["stats"], after["stats"]
    for rel in b:
        if rel not in a:
            diff["removed"].append(rel)
        elif a[rel] != b[rel]:
            diff["stat_changed"].append({"file": rel, "before": b[rel], "after": a[rel]})
    for rel in a:
        if rel not in b:
            diff["added"].append(rel)
    return {k: v for k, v in diff.items() if v}


def secure_wipe_tree(root):
    """Overwrite every file with random bytes, then delete the tree, then
    verify it is gone. For the seeded credential copies."""
    if not os.path.isdir(root):
        return {"wiped": 0, "gone": not os.path.exists(root)}
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(p)
                os.chmod(p, 0o600)
                with open(p, "r+b") as f:
                    remaining = size
                    while remaining > 0:
                        chunk = min(remaining, 1 << 20)
                        f.write(os.urandom(chunk))
                        remaining -= chunk
                    f.flush()
                    os.fsync(f.fileno())
                n += 1
            except OSError:
                pass
    shutil.rmtree(root, ignore_errors=True)
    return {"wiped": n, "gone": not os.path.exists(root)}


def firefox_census():
    """Every live firefox.exe pid (for the zero-orphan attestation)."""
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq firefox.exe", "/FO", "CSV"],
                       capture_output=True, text=True)
    pids = []
    for line in (r.stdout or "").splitlines():
        if line.startswith('"firefox.exe"'):
            parts = line.split('","')
            if len(parts) > 1:
                pids.append(int(parts[1]))
    return pids


def jdump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)
