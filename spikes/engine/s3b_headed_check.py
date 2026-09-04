"""S3b: brief HEADED launch of the installed Firefox (the Lane B dogfood mode).

Same safety contract: freshly created throwaway profile, -no-remote, killed
within seconds. It never touches, attaches to, or reads the user's profile.
"""
import os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, fixtures_server
from playwright.sync_api import sync_playwright

common.baseline()
srv, base = fixtures_server.start()
prof = common.throwaway_profile("s3b_headed")
res = {}
with sync_playwright() as p:
    t0 = time.perf_counter()
    ctx = p.firefox.launch_persistent_context(prof, channel="moz-firefox", headless=False,
                                              args=common.SAFE_FF_ARGS, timeout=90000)
    res["launch_ms"] = round((time.perf_counter() - t0) * 1000)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(base + "/form")
    page.fill("#name", "headed")
    page.click("#counter")
    res["marker"] = page.locator("#marker").inner_text()
    res["count"] = page.locator("#count").inner_text()
    res["value"] = page.input_value("#name")
    res["screenshot_bytes"] = len(page.screenshot())
    res["ff_exe"] = sorted({q["exe"] for q in common.new_since_baseline()
                            if q["name"].lower() == "firefox.exe"})
    ctx.close()
time.sleep(1.5)
res["orphans"] = len(common.sweep_orphans(dry_run=True)[0])
srv.shutdown(); shutil.rmtree(prof, ignore_errors=True)
common.jdump(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "s3b_headed.json"), res)
print(res)
