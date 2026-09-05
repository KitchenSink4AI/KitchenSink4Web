"""S9 part 1: Lane B on the BRANDED channels. playwright channel="chrome" and
channel="msedge", each with a fresh throwaway profile directory, driven through
the same battery S3 ran on moz-firefox: launch, navigate, read, click, fill,
select-free evaluate, screenshot, provenance (executable path from the process
table + UA string), headed smoke, clean teardown, zero orphans.

DESIGN 4.3 calls the Chrome side "mature, low risk"; this measures it instead
of assuming it, and puts Edge on the record for the first time.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import util9  # noqa: E402
import fixture9  # noqa: E402
from util9 import common  # noqa: E402

OUT = os.path.join(HERE, "out")
DEADLINE = util9.Deadline(600, "s9_lane_b whole run")

rows = []


def step(name, fn):
    DEADLINE.check()
    t0 = time.perf_counter()
    try:
        val = fn()
        rows.append({"step": name, "status": "OK",
                     "ms": round((time.perf_counter() - t0) * 1000),
                     "detail": str(val)[:400]})
        print("  OK   %-40s %6d ms  %s" % (name, (time.perf_counter() - t0) * 1000,
                                           str(val)[:90]))
        return val
    except Exception as e:
        rows.append({"step": name, "status": "FAIL",
                     "ms": round((time.perf_counter() - t0) * 1000),
                     "error_type": type(e).__name__, "error": str(e)[:1200]})
        print("  FAIL %-40s %6d ms  %s: %s" % (name, (time.perf_counter() - t0) * 1000,
                                               type(e).__name__,
                                               str(e)[:200].replace("\n", " ")))
        return None


def battery(p, channel, base, scratch_roots):
    print("\n=== Lane B battery: channel=%s ===" % channel)
    profile = util9.scratch_dir("laneb_%s" % channel)
    scratch_roots.append(profile)
    ctx = step("%s launch_persistent(headless)" % channel,
               lambda: p.chromium.launch_persistent_context(
                   profile, channel=channel, headless=True, timeout=90000))
    if ctx is None:
        return {"channel": channel, "verdict": "BROKEN: would not launch"}

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    step("%s navigate" % channel, lambda: page.goto(base + "/", timeout=20000).status)
    step("%s read title+marker" % channel,
         lambda: (page.title(), page.locator("#marker").inner_text()))
    step("%s click #bump" % channel, lambda: (
        page.locator("#bump").click(timeout=5000),
        page.locator("#count").inner_text())[1])
    step("%s fill input" % channel, lambda: (
        page.locator("#field").fill("lane-b", timeout=5000),
        page.locator("#field").input_value())[1])
    step("%s evaluate" % channel, lambda: page.evaluate("6*7"))
    step("%s screenshot" % channel, lambda: len(page.screenshot()))
    ua = step("%s user agent" % channel, lambda: page.evaluate("navigator.userAgent"))
    ver = step("%s browser.version" % channel, lambda: ctx.browser.version if ctx.browser else "n/a")

    # Provenance: the process actually launched must be the INSTALLED branded
    # binary, proven from the process table, never from the page.
    def provenance():
        want = util9.EXE[channel].lower()
        newly = [pr for pr in common.new_since_baseline()
                 if (pr.get("exe") or "").lower() == want]
        if not newly:
            raise AssertionError("no new process with exe == %s" % want)
        return "%d processes at installed path" % len(newly)
    step("%s provenance (process table)" % channel, provenance)

    step("%s close" % channel, lambda: ctx.close())

    # Headed smoke, the dogfood shape.
    profile2 = util9.scratch_dir("laneb_headed_%s" % channel)
    scratch_roots.append(profile2)
    ctx2 = step("%s launch_persistent(HEADED)" % channel,
                lambda: p.chromium.launch_persistent_context(
                    profile2, channel=channel, headless=False, timeout=90000))
    if ctx2 is not None:
        pg2 = ctx2.pages[0] if ctx2.pages else ctx2.new_page()
        step("%s headed navigate+read" % channel,
             lambda: (pg2.goto(base + "/", timeout=20000),
                      pg2.locator("#marker").inner_text())[1])
        step("%s headed close" % channel, lambda: ctx2.close())
    return {"channel": channel, "ua": ua, "version": ver}


def main():
    from playwright.sync_api import sync_playwright
    import playwright._repo_version as pwver

    common.baseline()
    srv, base = fixture9.start()
    print("fixtures at", base)

    env = {"python": sys.version.split()[0], "playwright_python": pwver.version,
           "chrome_exe": util9.CHROME, "chrome_version": util9.exe_version(util9.CHROME),
           "edge_exe": util9.EDGE, "edge_version": util9.exe_version(util9.EDGE)}
    print("env:", env)

    scratch_roots = []
    verdicts = []
    with sync_playwright() as p:
        for ch in ("chrome", "msedge"):
            if not os.path.exists(util9.EXE[ch]):
                verdicts.append({"channel": ch, "verdict": "NOT INSTALLED on this machine"})
                continue
            verdicts.append(battery(p, ch, base, scratch_roots))

    time.sleep(2.0)
    leftovers = common.new_since_baseline()
    killed = util9.kill_our_leftovers(scratch_roots)
    final = common.new_since_baseline()
    for d in scratch_roots:
        util9.rmtree_retry(d)

    result = {"env": env, "rows": rows, "verdicts": verdicts,
              "leftovers_before_sweep": leftovers, "swept": killed,
              "leftovers_after_sweep": final,
              "zero_orphans": not final,
              "scratch_dirs_removed": all(not os.path.exists(d) for d in scratch_roots)}
    util9.jdump(os.path.join(OUT, "s9_lane_b.json"), result)
    srv.shutdown()
    print("\nzero_orphans:", result["zero_orphans"],
          " scratch removed:", result["scratch_dirs_removed"])
    fails = [r for r in rows if r["status"] == "FAIL"]
    print("steps: %d OK / %d FAIL" % (len(rows) - len(fails), len(fails)))


if __name__ == "__main__":
    main()
