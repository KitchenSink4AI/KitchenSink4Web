"""S4: BiDi gap verification.

Confirms or refutes, empirically and with exact error shapes, the three
documented Playwright-over-BiDi gaps (no request/response bodies, downloads
broken, continueWithAuth broken) plus the adjacent probes PLAN S4 names
(extra headers across a redirect, locale/timezone emulation, clicking inside a
CSS-transformed element), and anything else that fell over along the way.

Every probe runs on BOTH lanes so the row reads "works on Chromium, fails on
moz-firefox" rather than "fails" -- that difference is what the
browser_capabilities honesty tool has to report.

Usage:  python -X utf8 s4_bidi_gaps.py [moz-firefox|chromium|both]
SAFETY: throwaway profile + -no-remote for every Firefox launch.
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


class Probe:
    def __init__(self, lane):
        self.lane = lane
        self.rows = []

    def run(self, name, fn, expect=None):
        t0 = time.perf_counter()
        row = {"lane": self.lane, "probe": name}
        try:
            val = fn()
            row["status"] = "SUPPORTED"
            row["observed"] = str(val)[:500]
        except Exception as e:
            row["status"] = "UNSUPPORTED"
            row["error_type"] = type(e).__name__
            row["error"] = str(e)[:1500]
            row["observed"] = ""
        row["ms"] = round((time.perf_counter() - t0) * 1000)
        if expect is not None and row["status"] == "SUPPORTED":
            try:
                if not expect(row["observed"]):
                    row["status"] = "DEGRADED"
                    row["note"] = "call returned without error but the result is wrong/empty"
            except Exception:
                pass
        self.rows.append(row)
        print("  %-11s %-38s %6dms  %s" % (row["status"], name, row["ms"],
                                           (row.get("observed") or row.get("error", ""))[:95]
                                           .replace("\n", " ")))
        return row


def make_context(p, lane, profile, **kw):
    if lane == "moz-firefox":
        return p.firefox.launch_persistent_context(
            profile, channel="moz-firefox", headless=HEADLESS,
            args=common.SAFE_FF_ARGS, timeout=90000, **kw)
    return p.chromium.launch_persistent_context(
        profile, headless=HEADLESS, timeout=90000, **kw)


def run_lane(p, lane, base):
    print("\n=== lane: %s ===" % lane)
    pr = Probe(lane)
    profile = common.throwaway_profile("s4_" + lane.replace("-", ""))
    ctx = make_context(p, lane, profile)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(base + "/", wait_until="load")

    # --- GAP 1: bodies -------------------------------------------------
    def doc_response_body():
        resp = page.goto(base + "/form", wait_until="load")
        return "len=%d head=%r" % (len(resp.body()), resp.text()[:40])
    pr.run("response.body() [document]", doc_response_body,
           expect=lambda o: "len=0" not in o)

    def xhr_response_body():
        page.goto(base + "/poster", wait_until="load")
        with page.expect_response("**/echo") as ri:
            page.evaluate("() => window.doPost()")
        r = ri.value
        return "status=%d body=%r" % (r.status, r.text()[:80])
    pr.run("response.body() [xhr POST]", xhr_response_body,
           expect=lambda o: "body=''" not in o)

    def post_data():
        page.goto(base + "/poster", wait_until="load")
        with page.expect_request("**/echo") as ri:
            page.evaluate("() => window.doPost()")
        req = ri.value
        return "method=%s post_data=%r post_data_buffer=%r" % (
            req.method, req.post_data, (req.post_data_buffer or b"")[:60])
    pr.run("request.post_data [fetch POST]", post_data,
           expect=lambda o: "post_data=None" not in o and "post_data=''" not in o)

    def form_post_data():
        page.goto(base + "/form", wait_until="load")
        page.fill("#name", "spike")
        with page.expect_request(lambda r: r.method == "POST") as ri:
            page.click("#submit")
        return "post_data=%r" % (ri.value.post_data,)
    pr.run("request.post_data [form submit]", form_post_data,
           expect=lambda o: "post_data=None" not in o)

    # --- routing (bodies' close cousin) --------------------------------
    def routing_fulfill():
        def handler(route):
            route.fulfill(status=200, content_type="text/html",
                          body="<p id='marker'>ROUTED</p>")
        page.route("**/routed", handler)
        page.goto(base + "/routed", wait_until="load")
        t = page.locator("#marker").inner_text()
        page.unroute("**/routed")
        return t
    pr.run("route.fulfill", routing_fulfill, expect=lambda o: "ROUTED" in o)

    def routing_abort():
        page.route("**/file.txt", lambda r: r.abort())
        page.goto(base + "/download", wait_until="load")
        st = page.evaluate("""async () => { try { const r = await fetch('/file.txt');
            return 'fetched ' + r.status; } catch (e) { return 'blocked: ' + e.message; } }""")
        page.unroute("**/file.txt")
        return st
    pr.run("route.abort", routing_abort, expect=lambda o: "blocked" in o)

    def route_fetch_body():
        holder = {}

        def handler(route):
            try:
                resp = route.fetch()
                holder["body"] = resp.text()[:60]
            except Exception as e:
                holder["err"] = "%s: %s" % (type(e).__name__, str(e)[:200])
            route.continue_()
        page.route("**/headers", handler)
        page.goto(base + "/headers", wait_until="load")
        page.unroute("**/headers")
        if "err" in holder:
            raise RuntimeError(holder["err"])
        return holder.get("body", "")
    pr.run("route.fetch() body", route_fetch_body, expect=lambda o: len(o) > 5)

    # --- GAP 2: downloads ----------------------------------------------
    def download():
        page.goto(base + "/download", wait_until="load")
        with page.expect_download(timeout=15000) as di:
            page.click("#dl")
        d = di.value
        path = d.path()
        size = os.path.getsize(path) if path else -1
        return "suggested=%s bytes=%d" % (d.suggested_filename, size)
    pr.run("download event + save", download, expect=lambda o: "bytes=-1" not in o)

    # --- adjacent probes ------------------------------------------------
    def extra_headers_redirect():
        page.set_extra_http_headers({"x-ks4web": "spike-value"})
        page.goto(base + "/redirect", wait_until="load")
        body = page.locator("body").inner_text()
        page.set_extra_http_headers({})
        return "header_seen=%s" % ("spike-value" in body)
    pr.run("extra_http_headers across 302", extra_headers_redirect,
           expect=lambda o: "True" in o)

    def transformed_click():
        page.goto(base + "/transform", wait_until="load")
        page.click("#tgt", timeout=10000)
        return page.locator("#res").inner_text()
    pr.run("click inside CSS transform", transformed_click,
           expect=lambda o: "CLICKED" in o)

    def go_back_probe():
        page.goto(base + "/", wait_until="load")
        page.goto(base + "/form", wait_until="load")
        page.go_back(timeout=15000)
        return page.url
    pr.run("go_back (plain GET history)", go_back_probe,
           expect=lambda o: o.rstrip("/").endswith("127.0.0.1:%s" % base.rsplit(":", 1)[1]))

    def go_back_after_post():
        page.goto(base + "/form", wait_until="load")
        page.click("#submit")
        page.wait_for_load_state()
        page.go_back(timeout=15000)
        return page.url
    pr.run("go_back (after form POST)", go_back_after_post)

    def cookies():
        ctx.add_cookies([{"name": "ks4web", "value": "1", "url": base}])
        got = [c["name"] for c in ctx.cookies()]
        return got
    pr.run("cookies add/read", cookies, expect=lambda o: "ks4web" in o)

    def dialog():
        seen = {}
        page.once("dialog", lambda d: (seen.update(msg=d.message), d.accept()))
        page.goto(base + "/", wait_until="load")
        page.evaluate("() => alert('hi from spike')")
        return seen.get("msg", "")
    pr.run("dialog handling", dialog, expect=lambda o: "hi from spike" in o)

    def file_upload():
        page.goto(base + "/form", wait_until="load")
        page.evaluate("() => { const i=document.createElement('input'); i.type='file'; "
                      "i.id='up'; document.body.appendChild(i); }")
        tmp = os.path.join(OUT, "upload_probe.txt")
        os.makedirs(OUT, exist_ok=True)
        open(tmp, "w").write("payload")
        page.set_input_files("#up", tmp)
        return page.evaluate("() => document.getElementById('up').files[0].name")
    pr.run("set_input_files", file_upload, expect=lambda o: "upload_probe" in o)

    def full_page_shot():
        page.goto(base + "/big?n=3000", wait_until="load")
        return len(page.screenshot(full_page=True))
    pr.run("screenshot full_page", full_page_shot, expect=lambda o: int(o or 0) > 1000)

    def pdf():
        return len(page.pdf())
    pr.run("page.pdf", pdf)

    def net_events():
        seen = []
        page.on("request", lambda r: seen.append(r.url))
        page.goto(base + "/form", wait_until="load")
        page.wait_for_timeout(300)
        return "requests_seen=%d" % len(seen)
    pr.run("request events fire", net_events, expect=lambda o: "=0" not in o)

    ctx.close()
    shutil.rmtree(profile, ignore_errors=True)

    # --- GAP 3: HTTP auth (needs its own context) ------------------------
    p2 = common.throwaway_profile("s4auth_" + lane.replace("-", ""))
    ctx2 = make_context(p, lane, p2, http_credentials={"username": fixtures_server.AUTH_USER,
                                                       "password": fixtures_server.AUTH_PASS})
    pg2 = ctx2.pages[0] if ctx2.pages else ctx2.new_page()

    def http_auth():
        r = pg2.goto(base + "/auth", wait_until="load", timeout=20000)
        txt = pg2.locator("body").inner_text()
        return "status=%s body=%r" % (r.status if r else None, txt[:60])
    pr.run("http_credentials (continueWithAuth)", http_auth,
           expect=lambda o: "AUTH-OK" in o)
    ctx2.close()
    shutil.rmtree(p2, ignore_errors=True)

    # --- locale / timezone emulation ------------------------------------
    p3 = common.throwaway_profile("s4loc_" + lane.replace("-", ""))
    try:
        ctx3 = make_context(p, lane, p3, locale="fr-FR", timezone_id="Asia/Tokyo")
        pg3 = ctx3.pages[0] if ctx3.pages else ctx3.new_page()

        def loc():
            pg3.goto(base + "/locale", wait_until="load")
            return "tz=%s lang=%s" % (pg3.locator("#tz").inner_text(),
                                      pg3.locator("#lang").inner_text())
        pr.run("locale + timezone emulation", loc,
               expect=lambda o: "Asia/Tokyo" in o and "fr" in o)
        ctx3.close()
    except Exception as e:
        pr.rows.append({"lane": lane, "probe": "locale + timezone emulation",
                        "status": "UNSUPPORTED", "error_type": type(e).__name__,
                        "error": str(e)[:1000], "note": "failed at context creation"})
        print("  UNSUPPORTED locale/timezone (context creation): %s" % str(e)[:150])
    shutil.rmtree(p3, ignore_errors=True)
    return pr.rows


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    lanes = ["moz-firefox", "chromium"] if which == "both" else [which]
    from playwright.sync_api import sync_playwright
    import playwright._repo_version as ver

    common.baseline()
    srv, base = fixtures_server.start()
    print("fixtures at", base, "| playwright", ver.version)
    all_rows = []
    with sync_playwright() as p:
        for lane in lanes:
            try:
                all_rows += run_lane(p, lane, base)
            except Exception:
                traceback.print_exc()
                all_rows.append({"lane": lane, "probe": "LANE ABORTED", "status": "ERROR",
                                 "error": traceback.format_exc()[-1500:]})
    time.sleep(2)
    left, _ = common.sweep_orphans(dry_run=True)
    srv.shutdown()
    common.jdump(os.path.join(OUT, "s4_bidi_gaps_%s.json" % which),
                 {"playwright": ver.version, "firefox": common.firefox_path(),
                  "rows": all_rows, "orphans_after": left})
    print("\norphans after S4:", len(left))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("emergency sweep:", common.sweep_orphans(dry_run=False)[1])
