"""S3: does playwright-python's `moz-firefox` channel actually drive the STOCK
installed Firefox over WebDriver BiDi on this machine?

GATE (PLAN S3): it launches, navigates, clicks, fills a form, screenshots, and
reads text; about:support (or the process's executable path) confirms it is the
INSTALLED build and not a Playwright download.

SAFETY: throwaway profile dir + `-no-remote`, always. The user's running Firefox
is never attached to, enumerated, or read.
"""
import os
import shutil
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import fixtures_server  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
HEADLESS = os.environ.get("SPIKE_HEADED", "") != "1"

rows = []


def step(name, fn):
    t0 = time.perf_counter()
    try:
        val = fn()
        rows.append({"step": name, "status": "OK", "ms": round((time.perf_counter() - t0) * 1000),
                     "detail": str(val)[:400]})
        print("  OK   %-34s %6d ms  %s" % (name, (time.perf_counter() - t0) * 1000, str(val)[:90]))
        return val
    except Exception as e:
        rows.append({"step": name, "status": "FAIL", "ms": round((time.perf_counter() - t0) * 1000),
                     "error_type": type(e).__name__, "error": str(e)[:1200]})
        print("  FAIL %-34s %6d ms  %s: %s" % (name, (time.perf_counter() - t0) * 1000,
                                               type(e).__name__, str(e)[:200].replace("\n", " ")))
        return None


def main():
    from playwright.sync_api import sync_playwright
    import playwright._repo_version as ver

    common.baseline()
    srv, base = fixtures_server.start()
    print("fixtures at", base)

    env = {
        "python": sys.version.split()[0],
        "playwright_python": ver.version,
        "firefox_installed": common.firefox_path(),
        "headless": HEADLESS,
    }
    print("env:", env)

    profile = common.throwaway_profile("s3")
    print("throwaway profile:", profile)
    assert not os.listdir(profile), "profile dir must start empty"

    result = {"env": env, "profile_dir": profile, "rows": rows}
    ctx = None
    launched_pids = []
    with sync_playwright() as p:
        # 1. channel availability
        def launch():
            return p.firefox.launch_persistent_context(
                profile,
                channel="moz-firefox",
                headless=HEADLESS,
                args=common.SAFE_FF_ARGS,        # -no-remote, mandatory
                timeout=90000,
            )
        ctx = step("launch_persistent(moz-firefox)", launch)
        if ctx is None:
            result["verdict"] = "BROKEN: channel would not launch"
            common.jdump(os.path.join(OUT, "s3_moz_firefox.json"), result)
            srv.shutdown()
            return result

        procs = common.new_since_baseline()
        launched_pids = [q["pid"] for q in procs]
        ff = [q for q in procs if q["name"].lower() == "firefox.exe"]
        result["spawned"] = procs
        step("process is installed build",
             lambda: [q["exe"] for q in ff] or "no firefox.exe child found")

        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        step("goto index", lambda: page.goto(base + "/", wait_until="load").status)
        step("read text", lambda: page.locator("#marker").inner_text())
        step("click link -> nav", lambda: (page.click("#lnk-form"),
                                           page.wait_for_url("**/form"), page.title())[-1])
        step("fill input", lambda: (page.fill("#name", "spike"),
                                    page.input_value("#name"))[-1])
        step("fill textarea", lambda: (page.fill("#msg", "hello from bidi"),
                                       page.input_value("#msg"))[-1])
        step("select_option", lambda: page.select_option("#color", "b"))
        step("check checkbox", lambda: (page.check("#chk"), page.is_checked("#chk"))[-1])
        step("click button (js handler)",
             lambda: (page.click("#counter"), page.locator("#count").inner_text())[-1])
        step("evaluate", lambda: page.evaluate("() => document.querySelectorAll('*').length"))
        step("aria_snapshot", lambda: len(page.locator("body").aria_snapshot()))
        step("screenshot", lambda: len(page.screenshot()))
        step("form submit -> POST",
             lambda: (page.click("#submit"), page.wait_for_load_state(),
                      page.locator("body").inner_text()[:120])[-1])
        step("go_back", lambda: (page.go_back(), page.url)[-1])
        step("new_page in context", lambda: (ctx.new_page().goto(base + "/", timeout=30000)).status)
        step("user_agent", lambda: page.evaluate("() => navigator.userAgent"))

        # about:support -- the PLAN's named provenance check
        def about_support():
            pg = ctx.new_page()
            pg.goto("about:support", timeout=30000)
            txt = pg.locator("body").inner_text()
            ver_line = ""
            for key in ("Application Binary", "Version", "Profile Directory", "Profile Folder"):
                for line in txt.splitlines():
                    if line.strip().startswith(key):
                        ver_line += line.strip()[:200] + " | "
            pg.close()
            return ver_line or txt[:300]
        step("about:support", about_support)

        # Non-persistent launch() on the same channel
        def ephemeral():
            b = p.firefox.launch(channel="moz-firefox", headless=HEADLESS,
                                 args=common.SAFE_FF_ARGS, timeout=90000)
            pg = b.new_page()
            pg.goto(base + "/")
            t = pg.locator("#marker").inner_text()
            b.close()
            return t
        step("launch() ephemeral profile", ephemeral)

        step("close context", lambda: ctx.close())

    time.sleep(2.0)
    left, _ = common.sweep_orphans(dry_run=True)
    result["orphans_after"] = left
    result["launched_pids"] = launched_pids
    srv.shutdown()

    ok = [r for r in rows if r["status"] == "OK"]
    result["summary"] = "%d/%d steps OK" % (len(ok), len(rows))
    gate_steps = ["launch_persistent(moz-firefox)", "goto index", "read text",
                  "click link -> nav", "fill input", "screenshot", "process is installed build"]
    result["gate_pass"] = all(any(r["step"] == s and r["status"] == "OK" for r in rows)
                              for s in gate_steps)
    common.jdump(os.path.join(OUT, "s3_moz_firefox.json"), result)
    print("\nsummary:", result["summary"], "| gate_pass:", result["gate_pass"],
          "| orphans:", len(left))
    try:
        shutil.rmtree(profile, ignore_errors=True)
    except Exception:
        pass
    return result


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        left, killed = common.sweep_orphans(dry_run=False)
        print("emergency sweep killed:", killed)
