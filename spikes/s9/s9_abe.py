"""S9 part 4: the App-Bound Encryption question. Does a Chrome `User Data`
directory copied to a non-default path still decrypt its cookies on the same
machine and user account? DESIGN 4.6 marks this as the open empirical fact
that decides whether Chrome seeded profiles are useful at all.

METHOD, all synthetic, zero contact with real profiles:
  A. MINT a profile at the browser's own DEFAULT path, computed under a
     redirected LOCALAPPDATA (so the browser believes it is the default and
     applies exactly the crypto it would apply to a real default profile).
     Navigate to the local fixture's /set-cookie via the command line, dwell,
     close gracefully so the cookie store flushes.
  B. SAME-PATH control: relaunch against the same (scratch-default) profile
     and hit /cookie-echo. The fixture server records the Cookie header
     SERVER-SIDE, so the verdict never depends on reading the page. Proves the
     mint persisted and the harness works.
  C. COPY the whole User Data tree to a second scratch path, launch with an
     explicit --user-data-dir at the copy, hit /cookie-echo again. Whether the
     cookie arrives IS the answer.
Plus at-rest evidence: the encrypted_value prefix in the Cookies sqlite
(v20 = app-bound, v10 = DPAPI) and which os_crypt keys Local State carries,
read from OUR scratch profile only.

Run for Chrome (required by the spike) and Edge (same question for the
DESIGN 4.3 msedge channel).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import util9  # noqa: E402
import fixture9  # noqa: E402
from util9 import common  # noqa: E402

OUT = os.path.join(HERE, "out")
DEADLINE = util9.Deadline(700, "s9_abe whole run")
spawned_cmdlines = []


def visit(browser, url, env, extra=(), wait_event=None, base_t=None,
          dwell_s=6.0, wait_s=35, scratch_roots=()):
    """Launch headed to a URL, wait until the fixture server SEES the request
    (or timeout), dwell so the browser can flush, close gracefully, then kill
    every surviving descendant (Edge's startup-boost respawn made this
    mandatory: a gracefully-closed root can leave a background keep-alive
    holding the Cookies sqlite lock)."""
    DEADLINE.check()
    argv = [util9.EXE[browser], "--no-first-run", "--no-default-browser-check",
            *extra, url]
    spawned_cmdlines.append(subprocess.list2cmdline(argv))
    t0 = time.time() if base_t is None else base_t
    proc = util9.spawn(argv, env=env)
    seen = None
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if wait_event:
            hits = [e for e in fixture9.events_since(t0)
                    if e["path"] == wait_event[0] and e["tag"] == wait_event[1]]
            if hits:
                seen = hits[-1]
                break
        time.sleep(0.5)
    if seen:
        time.sleep(dwell_s)
    how, survivors = util9.teardown_tree(proc.pid, scratch_roots=scratch_roots)
    if survivors:
        how = "%s + %d surviving descendants force-killed" % (how, len(survivors))
    time.sleep(1.5)
    return seen, how


def cookie_at_rest(user_data_dir):
    """Read OUR scratch profile's cookie store: row present? prefix v10/v20?"""
    candidates = [os.path.join(user_data_dir, "Default", "Network", "Cookies"),
                  os.path.join(user_data_dir, "Default", "Cookies")]
    src = next((c for c in candidates if os.path.exists(c)), None)
    if not src:
        return {"store": None, "row": None}
    tmp = os.path.join(tempfile.mkdtemp(prefix="ks4web_spike_ck_"), "Cookies")
    last = None
    for attempt in range(8):
        try:
            shutil.copy2(src, tmp)
            last = None
            break
        except PermissionError as e:
            last = e
            time.sleep(1.5)
    if last is not None:
        return {"store": src.replace(user_data_dir, "<UD>"),
                "error": "locked after retries: %s" % last}
    for side in ("-wal", "-shm"):
        if os.path.exists(src + side):
            try:
                shutil.copy2(src + side, tmp + side)
            except PermissionError:
                pass
    try:
        con = sqlite3.connect(tmp)
        cur = con.execute(
            "SELECT host_key, name, hex(substr(encrypted_value,1,3)) "
            "FROM cookies WHERE name = ?", (fixture9.COOKIE_NAME,))
        rows = cur.fetchall()
        con.close()
    except Exception as e:
        rows = [("error", str(e), "")]
    prefix = None
    if rows and rows[0][2]:
        prefix = bytes.fromhex(rows[0][2]).decode("ascii", "replace")
    return {"store": src.replace(user_data_dir, "<UD>"),
            "row_count": len(rows), "encrypted_value_prefix": prefix}


def local_state_crypt(user_data_dir):
    p = os.path.join(user_data_dir, "Local State")
    try:
        with open(p, "r", encoding="utf-8") as f:
            ls = json.load(f)
        oc = ls.get("os_crypt", {})
        return {"os_crypt_keys": sorted(oc.keys())}
    except Exception as e:
        return {"error": str(e)}


def abe_probe(browser, base, scratch_roots):
    print("\n=== ABE probe: %s (%s) ===" % (browser, util9.exe_version(util9.EXE[browser])))
    scratch_la = util9.scratch_dir("abe_la_%s" % browser)
    scratch_roots.append(scratch_la)
    env = util9.redirected_env(scratch_la)
    default_ud = os.path.join(scratch_la, util9.DEFAULT_SUBPATH[browser])
    res = {"browser": browser, "version": util9.exe_version(util9.EXE[browser]),
           "default_ud": default_ud}

    # A. Mint at the (redirected) default path.
    t0 = time.time()
    seen, how = visit(browser, base + "/set-cookie?tag=%s-mint" % browser, env,
                      wait_event=("/set-cookie", "%s-mint" % browser), base_t=t0,
                      scratch_roots=(scratch_la,))
    res["mint"] = {"server_saw_request": bool(seen), "teardown": how,
                   "default_ud_created": os.path.isdir(default_ud)}
    print("  mint: server_saw=%s ud_created=%s" %
          (bool(seen), os.path.isdir(default_ud)))
    if not os.path.isdir(default_ud):
        res["verdict"] = "ABORT: default UD not created under redirect"
        return res
    res["at_rest"] = cookie_at_rest(default_ud)
    res["local_state"] = local_state_crypt(default_ud)
    print("  at rest:", res["at_rest"], res["local_state"])

    # B. Same-path control.
    t1 = time.time()
    seen1, _ = visit(browser, base + "/cookie-echo?tag=%s-same" % browser, env,
                     wait_event=("/cookie-echo", "%s-same" % browser), base_t=t1,
                     dwell_s=1.0, scratch_roots=(scratch_la,))
    same_cookie = (seen1 or {}).get("cookie", "")
    res["same_path"] = {"cookie_header": same_cookie,
                        "cookie_sent": fixture9.COOKIE_NAME in same_cookie}
    print("  same-path echo:", res["same_path"]["cookie_sent"], repr(same_cookie)[:80])

    # C. The copy. Whole User Data tree to a non-default path.
    copy_ud = util9.scratch_dir("abe_copy_%s" % browser)
    scratch_roots.append(copy_ud)
    copy_ud = os.path.join(copy_ud, "User Data")
    # BrowserMetrics/Crashpad hold locked .pma files and carry nothing the
    # cookie question needs; a straggler holding one must not fail the copy.
    def _ignore(_d, names):
        return [n for n in names if n in ("BrowserMetrics", "Crashpad")]
    for attempt in range(3):
        try:
            shutil.copytree(default_ud, copy_ud, ignore=_ignore)
            break
        except shutil.Error:
            shutil.rmtree(copy_ud, ignore_errors=True)
            time.sleep(3.0)
    else:
        res["verdict"] = "ABORT: copytree kept failing on locked files"
        return res
    res["copy_ud"] = copy_ud
    t2 = time.time()
    seen2, _ = visit(browser, base + "/cookie-echo?tag=%s-copied" % browser,
                     env=None,  # normal environment; the copy rides an explicit flag
                     extra=("--user-data-dir=%s" % copy_ud,),
                     wait_event=("/cookie-echo", "%s-copied" % browser), base_t=t2,
                     dwell_s=1.0, scratch_roots=(scratch_la, copy_ud))
    copied_cookie = (seen2 or {}).get("cookie", "")
    res["copied_path"] = {"cookie_header": copied_cookie,
                          "cookie_sent": fixture9.COOKIE_NAME in copied_cookie}
    res["copied_at_rest"] = cookie_at_rest(copy_ud)
    print("  copied echo:", res["copied_path"]["cookie_sent"], repr(copied_cookie)[:80])

    if not res["same_path"]["cookie_sent"]:
        res["verdict"] = "HARNESS INCONCLUSIVE: cookie did not survive even at the same path"
    elif res["copied_path"]["cookie_sent"]:
        res["verdict"] = ("DECRYPTS AFTER COPY: a User Data tree minted at the default "
                          "path still serves its cookies from a non-default path, "
                          "same machine + user")
    else:
        res["verdict"] = ("DOES NOT DECRYPT AFTER COPY: same-path control sent the "
                          "cookie, the copied path did not")
    print("  VERDICT:", res["verdict"])
    return res


def main():
    common.baseline()
    srv, base = fixture9.start(8855)
    scratch_roots = []
    results = []
    for browser in ("chrome", "msedge"):
        if not os.path.exists(util9.EXE[browser]):
            results.append({"browser": browser, "verdict": "NOT INSTALLED"})
            continue
        try:
            results.append(abe_probe(browser, base, scratch_roots))
        except Exception as e:
            results.append({"browser": browser,
                            "verdict": "%s: %s" % (type(e).__name__, str(e)[:400])})

    time.sleep(2.0)
    swept = util9.kill_our_leftovers(scratch_roots)
    final = common.new_since_baseline()
    for d in scratch_roots:
        util9.rmtree_retry(d)
    attest = util9.real_profile_untouched_attestation(spawned_cmdlines)
    source_facts = {
        "tag": "152.0.7977.76",
        "file": "chrome/browser/os_crypt/app_bound_encryption_provider_win.cc",
        "fact": "app-bound encryption checks the user data dir: "
                "SupportLevel::kNotUsingDefaultUserDataDir -> the app-bound key "
                "is withheld (KeyError::kTemporarilyUnavailable) and cookies "
                "mint v10 DPAPI, which is what this probe measured (fetched "
                "2026-09-05)",
        "consequence": "a KS4Web-owned (non-default) Chrome profile always runs "
                       "DPAPI-mode cookies, so copies decrypt; a REAL default "
                       "profile mints v20 app-bound values that the provider "
                       "cannot unwrap at a non-default path, so seeding from a "
                       "real profile is expected NOT to carry v20 sessions; "
                       "behavioral confirmation of the v20 side needs a "
                       "disposable default profile"}
    ours = [p for p in final if "ks4web_spike" in (p.get("cmd") or "")]
    out = {"results": results, "source_facts": source_facts,
           "swept": swept, "leftovers_after_sweep": final,
           "zero_orphans": not final,
           "zero_orphans_ours": not ours,
           "note": "leftovers_after_sweep can include third-party browser "
                   "activity that began mid-run (e.g. another tool's debug "
                   "Chrome); only processes naming our scratch dirs are ours "
                   "and only those are ever killed",
           "spawned_cmdlines": spawned_cmdlines,
           "real_profile_attestation": attest,
           "scratch_dirs_removed": all(not os.path.exists(d) for d in scratch_roots)}
    util9.jdump(os.path.join(OUT, "s9_abe.json"), out)
    srv.shutdown()
    print("\nzero_orphans:", out["zero_orphans"],
          " real profiles never named:", attest["clean"])


if __name__ == "__main__":
    main()
