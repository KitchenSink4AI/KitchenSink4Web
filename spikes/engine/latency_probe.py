"""Latency reality check for the S1 projection pipeline (the design review's
missing gate).

PLAN S1 says wall-clock is a real number, not a note, and warns that the
hidden-content normalizer implies per-node computed-style work whose bill lands
on the 50,000-node fixture. The S1 run measured tokens but not time, so this
probe measures it, on the S1 code unmodified (`projector.EXTRACT_JS` imported
from ../s1) and on DOM sizes that bracket the pathological fixture.

Measured per fixture, 10 repetitions, p50/p95:
  navigate+settle (cold, once)   -- context, not the projection's bill
  extract_js                     -- the in-page pass (styles, rects, digest)
  project_python                 -- block assembly + tiktoken accounting
and, to answer "where does the time go", four in-page micro-phases:
  qsa_all / style_sweep_all / rect_sweep_all / style_sweep_interactive_only
The last one is the sampling alternative priced out: what the normalizer would
cost if it visited only interactive candidates instead of every node.
"""
import json
import os
import shutil
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "s1"))
import common  # noqa: E402
import fixtures_server  # noqa: E402
import projector as P  # noqa: E402  (the S1 prototype, unmodified)

OUT = os.path.join(HERE, "out")
REPS = int(os.environ.get("SPIKE_REPS", "10"))

MICRO_JS = """() => {
  const t = () => performance.now();
  const out = {};
  let a = t();
  const all = document.querySelectorAll('*');
  out.qsa_all = t() - a;
  out.node_count = all.length;

  a = t();
  let acc = 0;
  for (const el of all) {
    const s = getComputedStyle(el);
    if (s.display === 'none') acc++;
    if (s.visibility === 'hidden') acc++;
    if (parseFloat(s.opacity) === 0) acc++;
    if (parseFloat(s.fontSize) < 2) acc++;
  }
  out.style_sweep_all = t() - a;
  out.style_hits = acc;

  a = t();
  let area = 0;
  for (const el of all) { const r = el.getBoundingClientRect(); area += r.width; }
  out.rect_sweep_all = t() - a;

  const SEL = 'a[href],button,input,select,textarea,summary,[role],[onclick],[tabindex]';
  a = t();
  const cand = document.querySelectorAll(SEL);
  let acc2 = 0;
  for (const el of cand) {
    const s = getComputedStyle(el);
    if (s.display === 'none') acc2++;
    const r = el.getBoundingClientRect();
    if (r.width <= 1) acc2++;
  }
  out.style_sweep_interactive_only = t() - a;
  out.interactive_candidates = cand.length;

  a = t();
  const txt = document.body.innerText || '';
  out.innertext = t() - a;
  out.text_chars = txt.length;
  return out;
}"""


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = min(len(xs) - 1, int(round((len(xs) - 1) * q)))
    return round(xs[k], 1)


def measure(page, slug, url, results, wait="load"):
    print("[%s] %s" % (slug, url))
    t0 = time.perf_counter()
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    nav_ms = (time.perf_counter() - t0) * 1000

    ex, pj, tk = [], [], []
    d = None
    for i in range(REPS):
        a = time.perf_counter()
        d = page.evaluate(P.EXTRACT_JS)
        ex.append((time.perf_counter() - a) * 1000)
        meta = {"status": 200, "load_state": "networkidle", "ts": "spike"}
        a = time.perf_counter()
        text, rung, toks, trace = P.project(d, meta, budget=5000)
        pj.append((time.perf_counter() - a) * 1000)
        a = time.perf_counter()
        P.ntok(text)
        tk.append((time.perf_counter() - a) * 1000)

    micro = page.evaluate(MICRO_JS)
    row = {
        "url": url,
        "nodes": d["completeness"]["total_elements"],
        "affordances": d["aff_total"],
        "nav_cold_ms": round(nav_ms),
        "extract_js": {"p50": pct(ex, .5), "p95": pct(ex, .95), "min": round(min(ex), 1),
                       "max": round(max(ex), 1), "mean": round(st.mean(ex), 1), "n": REPS},
        "project_python": {"p50": pct(pj, .5), "p95": pct(pj, .95)},
        "tokenize_only": {"p50": pct(tk, .5), "p95": pct(tk, .95)},
        "e2e_warm_p95_ms": round((pct(ex, .95) or 0) + (pct(pj, .95) or 0), 1),
        "micro": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in micro.items()},
    }
    results[slug] = row
    m = row["micro"]
    print("   nodes=%-7s extract p50=%-8s p95=%-8s | project p50=%-6s | style_all=%-7s "
          "style_interactive=%-6s rects=%-7s"
          % (row["nodes"], row["extract_js"]["p50"], row["extract_js"]["p95"],
             row["project_python"]["p50"], m["style_sweep_all"],
             m["style_sweep_interactive_only"], m["rect_sweep_all"]))
    return row


def main():
    from playwright.sync_api import sync_playwright
    common.baseline()
    srv, base = fixtures_server.start()
    results = {}
    prof = common.throwaway_profile("lat")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            prof, headless=True, viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.add_init_script(P.CLOSED_SHADOW_HOOK)

        # synthetic scaling ladder: brackets the pathological 50k-node fixture
        for n in (5000, 10000, 25000, 50000, 100000):
            measure(page, "synthetic_%dk" % (n // 1000), base + "/big?n=%d" % n, results)

        # the heaviest real fixtures from the S1 corpus
        for slug, url in (
                ("wikipedia_versailles", "https://en.wikipedia.org/wiki/Treaty_of_Versailles"),
                ("wikipedia_gdp_table",
                 "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)"),
                ("cnn_homepage", "https://www.cnn.com/"),
                ("spa_antdesign", "https://ant.design/components/overview/")):
            try:
                measure(page, slug, url, results)
            except Exception as e:
                results[slug] = {"error": "%s: %s" % (type(e).__name__, str(e)[:300])}
                print("   !! %s" % str(e)[:200])
        ctx.close()
    shutil.rmtree(prof, ignore_errors=True)
    time.sleep(1.5)
    left, _ = common.sweep_orphans(dry_run=True)
    srv.shutdown()
    common.jdump(os.path.join(OUT, "latency.json"),
                 {"reps": REPS, "lane": "chromium headless (S1 lane A)",
                  "results": results, "orphans_after": left})
    print("\norphans:", len(left))
    print(json.dumps({k: {"nodes": v.get("nodes"),
                          "extract_p95": (v.get("extract_js") or {}).get("p95")}
                      for k, v in results.items()}, indent=1))


if __name__ == "__main__":
    main()
