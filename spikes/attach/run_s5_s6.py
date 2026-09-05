"""S5 (live attach over raw BiDi) + S6 (seeded-profile fidelity), one run.

Sequence:
  0. Gate: firefox.exe not running. Hash a manifest of the REAL profile.
  1. S6 seed: copy the named subset into a scratchpad throwaway, checkpoint the
     sqlite WALs on the COPY, write a hygiene user.js (updates/first-run off).
  2. Cookie HOST presence on the COPY against a fixed low-stakes candidate
     list (booleans only; no values, no enumeration).
  3. Launch the INSTALLED stock firefox.exe headed:
        -no-remote -profile <copy> --remote-debugging-port=<port>
     which simulates the Lane C user's own launch.
  4. S5: attach with the in-house raw BiDi client. session.new, getTree,
     navigate, script.evaluate read, captureScreenshot, performActions click.
     Quirk probes: about:support navigate, traverseHistory URL truthfulness.
  5. S6: navigate to a present candidate site; STRUCTURAL logged-in boolean.
  6. Teardown A. Then launch B: cookies.sqlite-only copy, repeat the login
     check (empirical minimal set).
  7. Wipe both copies (random overwrite + delete, verified). Kill everything
     we spawned; zero-firefox census; re-hash the real profile and diff.

Results land in out/*.json (sanitized: verdicts and mechanics only, no
credentials, no cookie values, no history). Manifests stay in the scratchpad.
"""
import asyncio
import base64
import http.server
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time

import safety
from bidi_client import BidiClient, BidiError

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.join(
    os.environ["LOCALAPPDATA"], "Temp", "claude",
    "C--Users-user-Documents-Obsidian-Vault",
    "3cc4e4a8-3e83-4151-bf55-6b0883ffd94a", "scratchpad", "s5s6")
FIREFOX = r"C:\Program Files\Mozilla Firefox\firefox.exe"
FIXTURE_PORT = 8931

SEED_SET_FULL = [
    "cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm",
    "key4.db", "logins.json",
    "places.sqlite", "places.sqlite-wal", "places.sqlite-shm",
    "permissions.sqlite",
]
SEED_SET_MIN = ["cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm"]

HYGIENE_USERJS = "\n".join([
    'user_pref("browser.shell.checkDefaultBrowser", false);',
    'user_pref("browser.startup.page", 0);',
    'user_pref("browser.startup.homepage", "about:blank");',
    'user_pref("startup.homepage_welcome_url", "about:blank");',
    'user_pref("startup.homepage_welcome_url.additional", "");',
    'user_pref("app.update.auto", false);',
    'user_pref("browser.aboutwelcome.enabled", false);',
    'user_pref("datareporting.healthreport.uploadEnabled", false);',
    'user_pref("toolkit.telemetry.enabled", false);',
]) + "\n"

# Low-stakes candidates: (label, cookie host LIKE pattern, url, structural
# logged-in expression that returns a BOOLEAN and never account content)
CANDIDATES = [
    ("github", "%github.com", "https://github.com/",
     "(document.querySelector('meta[name=\"user-login\"]')?.content || '').length > 0"),
    ("wikipedia", "%wikipedia.org", "https://en.wikipedia.org/wiki/Main_Page",
     "!!(document.getElementById('pt-userpage') || document.getElementById('pt-userpage-2'))"),
    ("stackoverflow", "%stackoverflow.com", "https://stackoverflow.com/",
     "!!document.querySelector('.s-topbar--item.s-user-card, a.s-user-card')"),
    ("reddit", "%reddit.com", "https://www.reddit.com/",
     "(() => { const a = document.querySelector('shreddit-app');"
     " return !!a && a.getAttribute('user-logged-in') === 'true'; })()"),
]

RESULTS = {"started_kst": time.strftime("%Y-%m-%d %H:%M:%S"), "s5": {}, "s6": {},
           "quirks": {}, "safety": {}}


# ---------------------------------------------------------------- fixtures
PAGE1 = (b"<!doctype html><title>P1</title>"
         b"<button id='b' style='position:absolute;left:40px;top:60px;"
         b"width:160px;height:40px' onclick=\"document.title='CLICKED'\">go</button>"
         b"<a id='l' href='/page2'>two</a><p id='t'>fixture page one</p>")
PAGE2 = b"<!doctype html><title>P2</title><p>fixture page two</p>"


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE1 if self.path != "/page2" else PAGE2
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_fixture():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", FIXTURE_PORT), Fixture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- seeding
def seed_profile(name, file_set):
    safety.assert_firefox_closed("pre-copy gate for %s" % name)
    dst = os.path.join(SCRATCH, name)
    if os.path.isdir(dst):          # stale copy from an aborted run: wipe first
        safety.secure_wipe_tree(dst)
    os.makedirs(dst, exist_ok=True)
    copied = []
    for fn in file_set:
        src = os.path.join(safety.REAL_PROFILE, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, fn))
            copied.append([fn, os.path.getsize(src)])
    # Merge WALs on the COPY so the seeded DBs are self-contained.
    for db in ("cookies.sqlite", "places.sqlite", "permissions.sqlite", "key4.db"):
        p = os.path.join(dst, db)
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.close()
            except sqlite3.Error as e:
                copied.append([db + " CHECKPOINT_FAIL", str(e)])
    with open(os.path.join(dst, "user.js"), "w", encoding="utf-8") as f:
        f.write(HYGIENE_USERJS)
    return dst, copied


def cookie_host_presence(seeded_dir):
    """Booleans only, fixed candidate list only. Never values, never a dump."""
    conn = sqlite3.connect(os.path.join(seeded_dir, "cookies.sqlite"))
    out = {}
    for label, pattern, _url, _expr in CANDIDATES:
        n = conn.execute("SELECT COUNT(*) FROM moz_cookies WHERE host LIKE ?",
                         (pattern,)).fetchone()[0]
        out[label] = n > 0
    conn.close()
    return out


# ---------------------------------------------------------------- launch
def find_browser_root(profile_dir):
    """The real browser root PID: on Windows firefox.exe is a LAUNCHER that
    spawns the browser and exits 0, so the Popen pid is useless. Identify our
    browser by its command line naming OUR seeded profile dir + -no-remote."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='firefox.exe'\" | "
           "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout or "null")
    except json.JSONDecodeError:
        return None
    if data is None:
        return None
    if isinstance(data, dict):
        data = [data]
    marker = profile_dir.lower()
    for p in data:
        cl = (p.get("CommandLine") or "").lower()
        if marker in cl and "-no-remote" in cl and "-contentproc" not in cl:
            return p.get("ProcessId")
    return None


def launch_firefox(profile_dir, bidi_port, log_name):
    log = open(os.path.join(SCRATCH, log_name), "w", encoding="utf-8")
    subprocess.Popen(
        [FIREFOX, "-no-remote", "-profile", profile_dir,
         "--remote-debugging-port=%d" % bidi_port],
        stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", bidi_port), timeout=1):
                pid = find_browser_root(profile_dir)
                return pid, log
        except OSError:
            time.sleep(0.5)
    raise SystemExit("BiDi port %d never opened" % bidi_port)


def kill_firefox(pid):
    """Tree-kill OUR browser root only (its command line named our seed dir),
    then verify a globally zero firefox census (valid because the author's
    Firefox is closed for the whole spike window)."""
    if pid:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, text=True)
    for _ in range(20):
        if not safety.firefox_running():
            return True
        time.sleep(0.5)
    return not safety.firefox_running()


# ---------------------------------------------------------------- S5 probes
async def s5_probes(c):
    r = {}
    t0 = time.time()
    new = await c.session_new()
    r["session.new"] = {"ok": True, "ms": round((time.time() - t0) * 1000),
                       "sessionId_present": bool(c.session_id),
                       "capabilities_keys": sorted((new.get("capability") or
                                                    new.get("capabilities") or {}).keys())}
    tree = await c.get_tree()
    ctxs = tree.get("contexts", [])
    r["browsingContext.getTree"] = {"ok": True, "context_count": len(ctxs),
                                    "urls": [x.get("url") for x in ctxs]}
    ctx = ctxs[0]["context"]

    t0 = time.time()
    nav = await c.navigate(ctx, "http://127.0.0.1:%d/page1" % FIXTURE_PORT)
    r["browsingContext.navigate"] = {"ok": True, "ms": round((time.time() - t0) * 1000),
                                     "reported_url": nav.get("url")}

    ev = await c.evaluate(ctx, "document.title + '|' + document.getElementById('t').textContent")
    r["script.evaluate"] = {"ok": True, "value": ev.get("value")}

    t0 = time.time()
    shot = await c.screenshot(ctx)
    png = base64.b64decode(shot.get("data", ""))
    r["browsingContext.captureScreenshot"] = {
        "ok": png[:8] == b"\x89PNG\r\n\x1a\n", "bytes": len(png),
        "ms": round((time.time() - t0) * 1000)}

    coords = await c.evaluate(
        ctx, "(() => { const b = document.getElementById('b').getBoundingClientRect();"
             " return JSON.stringify({x: b.x + b.width/2, y: b.y + b.height/2}); })()")
    xy = json.loads(coords["value"])
    await c.click_at(ctx, xy["x"], xy["y"])
    await asyncio.sleep(0.3)
    title = await c.evaluate(ctx, "document.title")
    r["input.performActions_click"] = {"ok": title.get("value") == "CLICKED",
                                       "title_after": title.get("value")}
    return r, ctx


async def quirk_probes(c, ctx):
    q = {}
    # Quirk 1: about:support over RAW BiDi (S3 saw a refusal via Playwright).
    try:
        nav = await c.navigate(ctx, "about:support", timeout=15)
        val = await c.evaluate(ctx, "document.location.href")
        q["about_support"] = {"navigated": True, "reported": nav.get("url"),
                              "location_href": val.get("value")}
    except (BidiError, asyncio.TimeoutError) as e:
        q["about_support"] = {"navigated": False, "error": str(e)[:300]}

    # Quirk 2: history traversal truthfulness (S4's Playwright client desync).
    await c.navigate(ctx, "http://127.0.0.1:%d/page1" % FIXTURE_PORT)
    await c.navigate(ctx, "http://127.0.0.1:%d/page2" % FIXTURE_PORT)
    try:
        t0 = time.time()
        await c.traverse_history(ctx, -1)
        ms = round((time.time() - t0) * 1000)
        await asyncio.sleep(0.5)
        tree = await c.get_tree()
        tree_url = next((x.get("url") for x in tree.get("contexts", [])
                         if x.get("context") == ctx), None)
        loc = await c.evaluate(ctx, "document.location.pathname + '|' + document.title")
        q["traverseHistory"] = {
            "returned": True, "ms": ms,
            "getTree_url_after_back": tree_url,
            "page_truth": loc.get("value"),
            "urls_agree": bool(tree_url and tree_url.endswith("/page1")
                               and loc.get("value", "").startswith("/page1"))}
    except (BidiError, asyncio.TimeoutError) as e:
        q["traverseHistory"] = {"returned": False, "error": str(e)[:300]}
    return q


async def login_check(c, presence):
    """Structural logged-in booleans on up to two present candidates."""
    out = {}
    tree = await c.get_tree()
    ctx = tree["contexts"][0]["context"]
    tested = 0
    for label, _pattern, url, expr in CANDIDATES:
        if not presence.get(label) or tested >= 2:
            continue
        try:
            await c.navigate(ctx, url, timeout=60)
            await asyncio.sleep(2.0)
            val = await c.evaluate(ctx, expr)
            out[label] = {"logged_in_structurally": val.get("value"),
                          "type": val.get("type")}
        except (BidiError, asyncio.TimeoutError) as e:
            out[label] = {"error": str(e)[:300]}
        tested += 1
    return out


# ---------------------------------------------------------------- main
async def run_session(profile_dir, port, log_name, do_s5, presence):
    listing_before = sorted(os.listdir(profile_dir))
    pid, log = launch_firefox(profile_dir, port, log_name)
    res = {"pid": pid}
    try:
        c = BidiClient(port)
        await c.connect()
        if do_s5:
            res["probes"], ctx = await s5_probes(c)
            res["quirks"] = await quirk_probes(c, ctx)
        else:
            await c.session_new()
        res["login"] = await login_check(c, presence)
        try:
            await c.session_end()
            res["session_end"] = "clean"
        except (BidiError, asyncio.TimeoutError) as e:
            res["session_end"] = str(e)[:200]
        await c.close()
    finally:
        res["killed_clean"] = kill_firefox(pid)
        log.close()
    listing_after = sorted(os.listdir(profile_dir))
    res["profile_files_created_by_firefox"] = [
        f for f in listing_after if f not in listing_before]
    return res


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    safety.assert_firefox_closed("spike start")
    RESULTS["safety"]["firefox_closed_at_start"] = True

    print("[0] hashing real-profile manifest (read-only)...")
    before = safety.profile_manifest()
    safety.jdump(os.path.join(SCRATCH, "manifest_before.json"), before)
    RESULTS["safety"]["manifest_files"] = before["file_count"]

    fixture = start_fixture()

    print("[1] seeding FULL profile copy...")
    full_dir, copied = seed_profile("seed_full", SEED_SET_FULL)
    RESULTS["s6"]["seed_full_copied"] = copied
    presence = cookie_host_presence(full_dir)
    RESULTS["s6"]["candidate_cookie_presence"] = presence
    print("    presence:", presence)

    print("[2] launch A (full seed) + S5 probes + S6 login check...")
    a = asyncio.run(run_session(full_dir, 9667, "ff_a.log", True, presence))
    RESULTS["s5"] = {k: a[k] for k in ("probes", "quirks") if k in a}
    RESULTS["s6"]["full_seed_session"] = {
        "pid": a["pid"], "login": a.get("login"),
        "session_end": a.get("session_end"), "killed_clean": a["killed_clean"],
        "profile_files_created_by_firefox": a["profile_files_created_by_firefox"]}

    print("[3] seeding MINIMAL copy (cookies only) + launch B...")
    min_dir, copied_min = seed_profile("seed_min", SEED_SET_MIN)
    RESULTS["s6"]["seed_min_copied"] = copied_min
    b = asyncio.run(run_session(min_dir, 9668, "ff_b.log", False, presence))
    RESULTS["s6"]["min_seed_session"] = {
        "pid": b["pid"], "login": b.get("login"),
        "session_end": b.get("session_end"), "killed_clean": b["killed_clean"],
        "profile_files_created_by_firefox": b["profile_files_created_by_firefox"]}

    fixture.shutdown()

    print("[4] wiping seeded copies...")
    RESULTS["safety"]["wipe_full"] = safety.secure_wipe_tree(full_dir)
    RESULTS["safety"]["wipe_min"] = safety.secure_wipe_tree(min_dir)

    print("[5] zero-orphan census + real-profile re-hash...")
    RESULTS["safety"]["firefox_pids_at_end"] = safety.firefox_census()
    after = safety.profile_manifest()
    safety.jdump(os.path.join(SCRATCH, "manifest_after.json"), after)
    diff = safety.manifest_diff(before, after)
    RESULTS["safety"]["real_profile_diff"] = diff or "IDENTICAL"

    RESULTS["finished_kst"] = time.strftime("%Y-%m-%d %H:%M:%S")
    safety.jdump(os.path.join(HERE, "out", "s5_s6_results.json"), RESULTS)
    print(json.dumps(RESULTS, indent=1, default=str))


if __name__ == "__main__":
    main()
