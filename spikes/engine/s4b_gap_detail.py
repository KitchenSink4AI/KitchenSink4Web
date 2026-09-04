"""S4b: exact failure shapes for the two moz-firefox gaps S4 found.

(1) request bodies: is post_data merely None (silent), does it raise anywhere,
    does the routed request expose it, and does continue_(post_data=...) work?
(2) go_back: does the URL move and only the load-state wait hang (silent
    partial), or does nothing happen at all? Does in-page history.back() work?

These are the transcripts the browser_capabilities honesty tool quotes.
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import fixtures_server  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
notes = []


def rec(k, v):
    notes.append({k: v})
    print("  %-42s %s" % (k, str(v)[:150].replace("\n", " ")))


def main():
    from playwright.sync_api import sync_playwright
    common.baseline()
    srv, base = fixtures_server.start()
    prof = common.throwaway_profile("s4b")
    with sync_playwright() as p:
        ctx = p.firefox.launch_persistent_context(prof, channel="moz-firefox",
                                                  headless=True, args=common.SAFE_FF_ARGS,
                                                  timeout=90000)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # ---- request body detail ----
        page.goto(base + "/poster", wait_until="load")
        with page.expect_request("**/echo") as ri:
            page.evaluate("() => window.doPost()")
        req = ri.value
        rec("req.method", req.method)
        rec("req.post_data", repr(req.post_data))
        rec("req.post_data_buffer", repr(req.post_data_buffer))
        try:
            rec("req.post_data_json", repr(req.post_data_json))
        except Exception as e:
            rec("req.post_data_json RAISES", "%s: %s" % (type(e).__name__, str(e)[:200]))
        hdrs = req.all_headers()
        rec("req.all_headers keys", sorted(hdrs.keys()))
        rec("req.headers content-length", hdrs.get("content-length"))

        holder = {}

        def handler(route):
            r = route.request
            holder["routed_post_data"] = repr(r.post_data)
            holder["routed_buffer"] = repr(r.post_data_buffer)
            try:
                route.continue_(post_data='{"hello":"tampered","n":7}')
                holder["continue_post_data"] = "accepted"
            except Exception as e:
                holder["continue_post_data"] = "%s: %s" % (type(e).__name__, str(e)[:250])
                route.continue_()
        page.route("**/echo", handler)
        page.goto(base + "/poster", wait_until="load")
        echoed = page.evaluate("() => window.doPost()")
        page.unroute("**/echo")
        for k, v in holder.items():
            rec(k, v)
        rec("server saw (after tamper attempt)", echoed[:160])

        # ---- go_back detail ----
        page.goto(base + "/", wait_until="load")
        page.goto(base + "/form", wait_until="load")
        rec("url before go_back", page.url)
        t0 = time.perf_counter()
        try:
            page.go_back(timeout=6000)
            rec("go_back", "returned")
        except Exception as e:
            rec("go_back error", "%s: %s" % (type(e).__name__, str(e)[:400]))
        rec("go_back elapsed_ms", round((time.perf_counter() - t0) * 1000))
        time.sleep(1.0)
        rec("url AFTER failed go_back", page.url)
        rec("document.readyState", page.evaluate("() => document.readyState"))
        rec("in-page marker after go_back",
            page.evaluate("() => (document.getElementById('marker')||{}).textContent"))

        # in-page history.back(), Playwright uninvolved in the navigation command
        page.goto(base + "/form", wait_until="load")
        page.evaluate("() => history.back()")
        time.sleep(1.5)
        rec("url after in-page history.back()", page.url)
        rec("marker after in-page history.back()",
            page.evaluate("() => (document.getElementById('marker')||{}).textContent"))

        # does go_forward behave the same?
        try:
            page.go_forward(timeout=6000)
            rec("go_forward", "returned -> " + page.url)
        except Exception as e:
            rec("go_forward error", "%s: %s" % (type(e).__name__, str(e)[:250]))

        # and reload, for completeness
        try:
            page.reload(timeout=8000)
            rec("reload", "OK -> " + page.url)
        except Exception as e:
            rec("reload error", "%s: %s" % (type(e).__name__, str(e)[:250]))

        ctx.close()
    time.sleep(1.5)
    left, _ = common.sweep_orphans(dry_run=True)
    srv.shutdown()
    shutil.rmtree(prof, ignore_errors=True)
    common.jdump(os.path.join(OUT, "s4b_gap_detail.json"),
                 {"notes": notes, "orphans_after": left})
    print("orphans:", len(left))


if __name__ == "__main__":
    main()
