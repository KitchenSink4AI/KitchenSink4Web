"""S9 part 3: Chrome/Edge Lane C. A user-style launch (headed branded binary,
explicit non-default --user-data-dir, --remote-debugging-port), then playwright
connect_over_cdp against it, a read and a click driven end to end, and the
Lane C-critical teardown fact: does browser.close() on a CDP connection
DISCONNECT (leaving the user's browser running, which Lane C requires) or kill?

The launched browser is the SIMULATED user side, per the S5 pattern: scratch
profile, our own process, never the author's browser.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import util9  # noqa: E402
import fixture9  # noqa: E402
from util9 import common  # noqa: E402

OUT = os.path.join(HERE, "out")
DEADLINE = util9.Deadline(420, "s9_lane_c whole run")
PORT = {"chrome": 9631, "msedge": 9632}

rows = []


def step(name, fn):
    DEADLINE.check()
    t0 = time.perf_counter()
    try:
        val = fn()
        rows.append({"step": name, "status": "OK",
                     "ms": round((time.perf_counter() - t0) * 1000),
                     "detail": str(val)[:400]})
        print("  OK   %-44s %6d ms  %s" % (name, (time.perf_counter() - t0) * 1000,
                                           str(val)[:80]))
        return val
    except Exception as e:
        rows.append({"step": name, "status": "FAIL",
                     "ms": round((time.perf_counter() - t0) * 1000),
                     "error_type": type(e).__name__, "error": str(e)[:1200]})
        print("  FAIL %-44s %6d ms  %s: %s" % (name, (time.perf_counter() - t0) * 1000,
                                               type(e).__name__,
                                               str(e)[:200].replace("\n", " ")))
        return None


def lane_c(p, browser, base, scratch_roots):
    print("\n=== Lane C: %s ===" % browser)
    ud = util9.scratch_dir("lanec_%s" % browser)
    scratch_roots.append(ud)
    port = PORT[browser]
    argv = [util9.EXE[browser], "--user-data-dir=%s" % ud,
            "--remote-debugging-port=%d" % port,
            "--no-first-run", "--no-default-browser-check", "about:blank"]
    proc = util9.spawn(argv)
    if not util9.wait_port(port, 30):
        util9.graceful_then_force(proc.pid)
        return {"browser": browser, "verdict": "BROKEN: debug port never opened"}
    ver = util9.cdp_version(port)
    print("  endpoint:", (ver or {}).get("Browser"))

    b = step("%s connect_over_cdp" % browser,
             lambda: p.chromium.connect_over_cdp("http://127.0.0.1:%d" % port,
                                                 timeout=20000))
    verdict = {"browser": browser, "endpoint": ver}
    if b is None:
        util9.graceful_then_force(proc.pid)
        verdict["verdict"] = "BROKEN: connect_over_cdp failed"
        return verdict

    ctxs = step("%s contexts" % browser, lambda: len(b.contexts))
    ctx = b.contexts[0]
    page = step("%s adopt page" % browser,
                lambda: ctx.pages[0] if ctx.pages else ctx.new_page())
    step("%s navigate" % browser, lambda: page.goto(base + "/", timeout=20000).status)
    step("%s read marker" % browser, lambda: page.locator("#marker").inner_text())
    step("%s click #bump -> count" % browser, lambda: (
        page.locator("#bump").click(timeout=5000),
        page.locator("#count").inner_text())[1])
    step("%s screenshot" % browser, lambda: len(page.screenshot()))
    step("%s browser.close() (disconnect)" % browser, lambda: b.close())
    time.sleep(1.5)
    still_alive = proc.poll() is None
    verdict["disconnect_leaves_browser_running"] = still_alive
    print("  disconnect left the user-side browser running:", still_alive)
    how = util9.graceful_then_force(proc.pid)
    verdict["teardown"] = how
    verdict["contexts"] = ctxs
    verdict["verdict"] = "WORKS" if all(
        r["status"] == "OK" for r in rows if r["step"].startswith(browser)) else "SEE ROWS"
    return verdict


def main():
    from playwright.sync_api import sync_playwright
    common.baseline()
    srv, base = fixture9.start(8854)
    scratch_roots = []
    verdicts = []
    with sync_playwright() as p:
        for browser in ("chrome", "msedge"):
            if not os.path.exists(util9.EXE[browser]):
                verdicts.append({"browser": browser, "verdict": "NOT INSTALLED"})
                continue
            verdicts.append(lane_c(p, browser, base, scratch_roots))

    time.sleep(2.0)
    swept = util9.kill_our_leftovers(scratch_roots)
    final = common.new_since_baseline()
    for d in scratch_roots:
        util9.rmtree_retry(d)
    out = {"rows": rows, "verdicts": verdicts, "swept": swept,
           "leftovers_after_sweep": final, "zero_orphans": not final,
           "scratch_dirs_removed": all(not os.path.exists(d) for d in scratch_roots)}
    util9.jdump(os.path.join(OUT, "s9_lane_c.json"), out)
    srv.shutdown()
    print("\nzero_orphans:", out["zero_orphans"])


if __name__ == "__main__":
    main()
