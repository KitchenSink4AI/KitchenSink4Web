"""S9 part 2 (THE GATE): the Chrome 136+ default-data-directory debugging
restriction, probed as far as this machine allows WITHOUT touching the
author's real profiles, plus the source-pinned mechanism for what cannot be
run here.

WHAT THE SHIPPED SOURCE SAYS (chromium tag 152.0.7977.76, fetched 2026-09-05,
chrome/browser/devtools/remote_debugging_server.cc + chrome/common/
chrome_paths_win.cc + chrome/install_static/user_data_dir.cc):
  * The check is a PATH COMPARISON, not switch presence:
    `chrome::IsUsingDefaultDataDirectory()` feeds `IsRemoteDebuggingAllowed`,
    which returns `NotStartedReason::kDisabledByDefaultUserDataDir` when the
    resolved data dir equals the computed default. Branded builds only
    (BUILDFLAG), Win/Mac/Linux.
  * A policy pref gates it too: `prefs::kDevToolsRemoteDebuggingAllowed`
    false -> `kDisabledByPolicy`.
  * 152 additionally carries `features::kDevToolsAcceptDebuggingConnections`
    (an approval mode for debugging connections).
  * ASYMMETRY, measured to matter: the USED dir (no switch) is derived by
    install_static via GetEnvironmentString(L"LOCALAPPDATA"), but the DEFAULT
    it is compared against comes from base::PathService DIR_LOCAL_APP_DATA
    (shell known-folder API, ignores the env var). So a redirected
    LOCALAPPDATA cannot reproduce the refusal: it produces a scratch data dir
    that compares NON-default. That turns the redirect into a BYPASS probe,
    and it means the true refusal is only observable on a machine whose real
    default profile is disposable. That run is DEFERRED BY RULE, not skipped
    by accident.

WHAT THIS SCRIPT MEASURES, safely:
  H1  headless=new + debug port + NO --user-data-dir, redirected env. Where
      does the profile actually land (chrome://version Profile Path over CDP)
      and does the port open?
  H2  same with a CLEAN env, run ONLY if H1 proved headless uses an ephemeral
      temp profile (then the real default is never in play).
  A   headed + debug port + NO --user-data-dir, redirected env: the bypass
      row. A 2.0 s watchdog kills the launch if the scratch User Data does
      not appear (that branch would mean the shipped binary contradicts its
      tagged source; a post-scan of the real profile is run either way).
  C   headed + debug port + explicit scratch --user-data-dir: the positive
      control and the Lane C precondition.
  D   the true-default refusal: NOT RUN HERE, recorded as a finding with what
      it needs (a machine with a disposable default profile).
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import util9  # noqa: E402
from util9 import common  # noqa: E402

OUT = os.path.join(HERE, "out")
DEADLINE = util9.Deadline(700, "s9_default_dir whole run")
PORTS = {"chrome": {"h1": 9611, "h2": 9612, "a": 9613, "c": 9614},
         "msedge": {"h1": 9621, "h2": 9622, "a": 9623, "c": 9624}}
SOURCE_FACTS = {
    "tag": "152.0.7977.76",
    "mechanism": "path comparison: chrome::IsUsingDefaultDataDirectory() -> "
                 "IsRemoteDebuggingAllowed -> NotStartedReason::"
                 "kDisabledByDefaultUserDataDir; branded builds, Win/Mac/Linux",
    "policy_gate": "prefs::kDevToolsRemoteDebuggingAllowed false -> kDisabledByPolicy",
    "approval_feature": "features::kDevToolsAcceptDebuggingConnections (152)",
    "asymmetry": "used dir: install_static GetEnvironmentString(LOCALAPPDATA); "
                 "comparison default: PathService DIR_LOCAL_APP_DATA (shell API)",
    "fetched": "2026-09-05 via chromium.googlesource.com",
}

spawned_cmdlines = []


def profile_path_via_cdp(p, port):
    """Read chrome://version's Profile Path through connect_over_cdp."""
    b = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % port, timeout=15000)
    try:
        ctx = b.contexts[0] if b.contexts else b.new_context()
        pg = ctx.new_page()
        pg.goto("chrome://version", timeout=15000)
        txt = pg.evaluate(
            "() => { const e = document.getElementById('profile_path');"
            " return e ? e.textContent : document.body.innerText.slice(0, 4000); }")
        pg.close()
        return (txt or "").strip()
    finally:
        b.close()


def launch(browser, extra, env, tag):
    argv = [util9.EXE[browser], "--no-first-run", "--no-default-browser-check",
            *extra, "about:blank"]
    spawned_cmdlines.append("[%s] " % tag + subprocess.list2cmdline(argv))
    return util9.spawn(argv, env=env)


def teardown(proc):
    if proc.poll() is None:
        how = util9.graceful_then_force(proc.pid)
    else:
        how = "exited on its own (code %s)" % proc.poll()
    try:
        _, err = proc.communicate(timeout=15)
        return how, err.decode("utf-8", "replace").strip()[:2000]
    except subprocess.TimeoutExpired:
        proc.kill()
        return how, "(stderr harvest timed out)"


def headless_row(p, browser, env_label, env, port):
    DEADLINE.check()
    print("  [%s/H %s] headless=new, no --user-data-dir, port %d" %
          (browser, env_label, port))
    proc = launch(browser, ["--headless=new", "--disable-gpu",
                            "--remote-debugging-port=%d" % port], env,
                  "H-%s-%s" % (env_label, browser))
    port_open = util9.wait_port(port, 15)
    row = {"mode": "headless=new, no user-data-dir, %s env" % env_label,
           "port_open": port_open}
    if port_open:
        row["cdp_version"] = util9.cdp_version(port)
        try:
            row["profile_path"] = profile_path_via_cdp(p, port)
        except Exception as e:
            row["profile_path_error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    how, stderr = teardown(proc)
    row["teardown"], row["stderr"] = how, stderr
    print("    port_open=%s profile=%s" % (port_open, row.get("profile_path", "?")[:90]))
    return row


def headed_bypass_row(p, browser, scratch_la, env, port):
    """Row A: headed, redirected env, NO switch. Watchdog: scratch UD must
    appear within 2.0 s or the tree is killed on the spot."""
    DEADLINE.check()
    default_ud = os.path.join(scratch_la, util9.DEFAULT_SUBPATH[browser])
    print("  [%s/A] HEADED bypass probe, watchdog on %s" % (browser, default_ud))
    proc = launch(browser, ["--remote-debugging-port=%d" % port], env,
                  "A-%s" % browser)
    t0 = time.monotonic()
    appeared = False
    while time.monotonic() - t0 < 2.0:
        if os.path.isdir(default_ud):
            appeared = True
            break
        time.sleep(0.1)
    row = {"mode": "HEADED, no user-data-dir, redirected env (bypass probe)",
           "scratch_ud_appeared_s": round(time.monotonic() - t0, 2)
           if appeared else None}
    if not appeared:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
        how, stderr = teardown(proc)
        row.update({"aborted": "WATCHDOG: scratch UD absent at 2.0 s, tree killed",
                    "teardown": how, "stderr": stderr, "port_open": None})
        print("    WATCHDOG ABORT")
        return row
    port_open = util9.wait_port(port, 15)
    row["port_open"] = port_open
    if port_open:
        row["cdp_version"] = util9.cdp_version(port)
        try:
            row["profile_path"] = profile_path_via_cdp(p, port)
        except Exception as e:
            row["profile_path_error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    devtools_file = os.path.join(default_ud, "DevToolsActivePort")
    row["devtools_active_port_file"] = os.path.exists(devtools_file)
    how, stderr = teardown(proc)
    row["teardown"], row["stderr"] = how, stderr
    print("    port_open=%s profile=%s" % (port_open, row.get("profile_path", "?")[:90]))
    return row


def pos_row(browser, port, scratch_roots):
    DEADLINE.check()
    ud = util9.scratch_dir("posud_%s" % browser)
    scratch_roots.append(ud)
    print("  [%s/C] positive control, explicit --user-data-dir" % browser)
    proc = launch(browser, ["--user-data-dir=%s" % ud,
                            "--remote-debugging-port=%d" % port], None,
                  "C-%s" % browser)
    port_open = util9.wait_port(port, 25)
    row = {"mode": "HEADED, explicit scratch --user-data-dir",
           "port_open": port_open,
           "cdp_version": util9.cdp_version(port) if port_open else None}
    how, stderr = teardown(proc)
    row["teardown"], row["stderr"] = how, stderr
    print("    port_open=%s" % port_open)
    return row


def real_profile_scan(browser, minutes=90):
    """Read-only: count files modified recently under the REAL profile."""
    ud = util9.REAL_PROFILES[browser]
    if not os.path.isdir(ud):
        return {"real_ud": ud, "exists": False}
    cutoff = time.time() - minutes * 60
    count, newest = 0, None
    for root, _dirs, files in os.walk(ud):
        for f in files:
            try:
                m = os.path.getmtime(os.path.join(root, f))
            except OSError:
                continue
            if m > cutoff:
                count += 1
                if newest is None or m > newest:
                    newest = m
    return {"real_ud": ud, "exists": True,
            "files_modified_last_%dmin" % minutes: count,
            "newest": time.strftime("%H:%M:%S", time.localtime(newest))
            if newest else None}


def probe_browser(p, browser, scratch_roots):
    print("\n=== default-dir probes: %s (%s) ===" %
          (browser, util9.exe_version(util9.EXE[browser])))
    scratch_la = util9.scratch_dir("la_%s" % browser)
    scratch_roots.append(scratch_la)
    env = util9.redirected_env(scratch_la)
    ports = PORTS[browser]
    res = {"browser": browser, "version": util9.exe_version(util9.EXE[browser])}

    res["h1_redirected"] = headless_row(p, browser, "redirected", env, ports["h1"])

    # H2 only if H1 proved the headless profile is ephemeral (in TEMP, not in
    # scratch and therefore not resolved through the default computation).
    pp = (res["h1_redirected"].get("profile_path") or "").lower()
    ephemeral = bool(pp) and (tempfile.gettempdir().lower() in pp
                              or "\\temp\\" in pp) and scratch_la.lower() not in pp
    res["h1_profile_is_ephemeral_temp"] = ephemeral
    if ephemeral:
        res["h2_clean_env"] = headless_row(p, browser, "clean", None, ports["h2"])
    else:
        res["h2_clean_env"] = {"skipped": "H1 did not prove ephemeral; a clean-env "
                                          "headless launch could resolve to the real "
                                          "default and is forbidden"}

    res["a_headed_bypass"] = headed_bypass_row(p, browser, scratch_la, env, ports["a"])
    res["c_positive"] = pos_row(browser, ports["c"], scratch_roots)
    res["d_true_default_refusal"] = {
        "status": "DEFERRED BY RULE",
        "why": "the only directory IsUsingDefaultDataDirectory() recognizes as "
               "default on this machine is the author's real profile, and the "
               "profile rule is absolute",
        "needs": "any machine (or throwaway Windows account) whose default "
                 "Chrome/Edge profile is disposable; run: <browser> "
                 "--remote-debugging-port=9222 with no --user-data-dir and "
                 "record stderr + port state",
        "expected_per_source": "port never opens; NotStartedReason::"
                               "kDisabledByDefaultUserDataDir (branded builds)"}
    res["real_profile_scan"] = real_profile_scan(browser)
    return res


def main():
    from playwright.sync_api import sync_playwright
    common.baseline()
    scratch_roots = []
    results = {"source_facts": SOURCE_FACTS}
    with sync_playwright() as p:
        for b in ("chrome", "msedge"):
            if not os.path.exists(util9.EXE[b]):
                results[b] = {"verdict": "NOT INSTALLED on this machine"}
                continue
            results[b] = probe_browser(p, b, scratch_roots)

    time.sleep(2.0)
    swept = util9.kill_our_leftovers(scratch_roots)
    final = common.new_since_baseline()
    for d in scratch_roots:
        util9.rmtree_retry(d)
    attest = util9.real_profile_untouched_attestation(spawned_cmdlines)
    out = {"results": results, "swept": swept,
           "leftovers_after_sweep": final, "zero_orphans": not final,
           "spawned_cmdlines": spawned_cmdlines,
           "real_profile_attestation": attest,
           "scratch_dirs_removed": all(not os.path.exists(d) for d in scratch_roots)}
    util9.jdump(os.path.join(OUT, "s9_default_dir.json"), out)
    print("\nzero_orphans:", out["zero_orphans"],
          " real profiles never named in any spawn:", attest["clean"])


if __name__ == "__main__":
    main()
