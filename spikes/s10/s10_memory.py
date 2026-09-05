"""S10 part 2: resident memory, measured per PLAN S10: a headless bundled
Chromium page against a headed `moz-firefox` page (plus headed bundled
Chromium as a free comparison row), each loading the same frozen corpus A
Versailles page served locally, settled, then summed over the browser's own
process tree (working set + private bytes), with the Playwright node driver
reported separately.

SAFETY: moz-firefox rides the installed firefox.exe with -no-remote and a
fresh temp profile, per the standing Firefox rules. Attribution is by
descendant walk from the root we spawned, never by process name, so the
author's own running Firefox is never counted or touched.
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "spikes", "engine"))
sys.path.insert(0, os.path.join(REPO, "spikes", "s9"))
import common  # noqa: E402
import util9  # noqa: E402

OUT = os.path.join(HERE, "out")
PAGE_PATH = os.path.join(REPO, "corpus", "a", "wikipedia_versailles.html")
SETTLE_S = 6.0


class PageHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        with open(PAGE_PATH, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 8856), PageHandler)
    srv.allow_reuse_address = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:8856/versailles"


def mem_of(pids):
    if not pids:
        return {"count": 0, "working_set_mb": 0, "private_mb": 0}
    idlist = ",".join(str(p) for p in pids)
    cmd = ("Get-Process -Id %s -ErrorAction SilentlyContinue | "
           "Select-Object Id,WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress"
           % idlist)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=60)
    try:
        data = json.loads(r.stdout)
    except Exception:
        return {"count": 0, "working_set_mb": 0, "private_mb": 0, "raw": r.stdout[:200]}
    if isinstance(data, dict):
        data = [data]
    ws = sum(d.get("WorkingSet64", 0) for d in data)
    pv = sum(d.get("PrivateMemorySize64", 0) for d in data)
    return {"count": len(data), "working_set_mb": round(ws / 2**20, 1),
            "private_mb": round(pv / 2**20, 1)}


def measure_tree(before_pids, want_exe_substring, profile_marker=None):
    """Attribute processes: new since `before`, rooted at a process whose exe
    (or cmdline) matches, then the descendant walk from those roots."""
    procs = common.ps_processes()
    new = [p for p in procs if p["pid"] not in before_pids]
    roots = []
    for p in new:
        exe = (p.get("exe") or "").lower()
        cmd = (p.get("cmd") or "").lower()
        if want_exe_substring in exe and (profile_marker is None
                                          or profile_marker.lower() in cmd):
            roots.append(p)
    tree_pids = set(p["pid"] for p in roots)
    for r in roots:
        for d in common.descendants(r["pid"], procs):
            if d["pid"] not in before_pids:
                tree_pids.add(d["pid"])
    node_pids = [p["pid"] for p in new
                 if p["name"].lower() == "node.exe" and p["pid"] not in tree_pids]
    root_exes = sorted({p.get("exe") or "" for p in roots})
    return sorted(tree_pids), node_pids, root_exes


def scenario(name, launch_fn, url, want_exe, profile_marker=None):
    print("\n=== %s ===" % name)
    before = {p["pid"] for p in common.ps_processes()}
    handle = launch_fn()
    ctx, page = handle["ctx"], handle["page"]
    page.goto(url, timeout=45000)
    time.sleep(SETTLE_S)
    tree, node, root_exes = measure_tree(before, want_exe, profile_marker)
    browser_mem = mem_of(tree)
    node_mem = mem_of(node)
    row = {"scenario": name, "browser_tree_pids": len(tree),
           "root_exes": root_exes,
           "browser": browser_mem, "node_driver": node_mem}
    print("  browser tree: %d procs, WS %.1f MB, private %.1f MB; driver WS %.1f MB"
          % (browser_mem["count"], browser_mem["working_set_mb"],
             browser_mem["private_mb"], node_mem["working_set_mb"]))
    ctx.close()
    time.sleep(2.0)
    return row


def main():
    from playwright.sync_api import sync_playwright
    common.baseline()
    srv, url = serve()
    rows = []
    profiles = []
    with sync_playwright() as p:
        # 1. bundled Chromium, headless (the expected Lane A default)
        def launch_chromium_headless():
            b = p.chromium.launch(headless=True)
            pg = b.new_page()
            return {"ctx": b, "page": pg}
        rows.append(scenario("bundled chromium, headless",
                             launch_chromium_headless, url, "ms-playwright"))

        # 2. bundled Chromium, headed (free comparison row)
        def launch_chromium_headed():
            b = p.chromium.launch(headless=False)
            pg = b.new_page()
            return {"ctx": b, "page": pg}
        rows.append(scenario("bundled chromium, headed",
                             launch_chromium_headed, url, "ms-playwright"))

        # 3. moz-firefox, headed (the dogfood shape PLAN S10 names)
        prof = common.throwaway_profile("s10ff")
        profiles.append(prof)

        def launch_moz_headed():
            c = p.firefox.launch_persistent_context(
                prof, channel="moz-firefox", headless=False,
                args=common.SAFE_FF_ARGS, timeout=90000)
            pg = c.pages[0] if c.pages else c.new_page()
            return {"ctx": c, "page": pg}
        rows.append(scenario("moz-firefox (installed Firefox), headed",
                             launch_moz_headed, url,
                             "mozilla firefox", profile_marker=prof))

    time.sleep(2.0)
    leftovers = common.new_since_baseline()
    out = {"date_kst": time.strftime("%Y-%m-%d %H:%M"), "settle_seconds": SETTLE_S,
           "page": "corpus/a/wikipedia_versailles.html served on loopback",
           "rows": rows, "leftovers": leftovers, "zero_orphans": not leftovers}
    common.jdump(os.path.join(OUT, "s10_memory.json"), out)
    for d in profiles:
        util9.rmtree_retry(d)
    srv.shutdown()
    print("\nzero_orphans:", out["zero_orphans"])


if __name__ == "__main__":
    main()
