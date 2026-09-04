"""S1 spike driver: load each benchmark page, measure the incumbent-style raw
snapshot, build the KS4Web projection, record numbers. Lane A only (bundled
Chromium, KS4Web-owned temp profile). Never touches a user profile."""
from __future__ import annotations

import asyncio
import datetime
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

import projector as P

HERE = Path(__file__).parent
OUT = HERE / "out"
RAW = OUT / "raw"
OUT.mkdir(exist_ok=True)
RAW.mkdir(exist_ok=True)

PAGES = [
    ("wikipedia_versailles", "https://en.wikipedia.org/wiki/Treaty_of_Versailles", "article (banked baseline)"),
    ("wikipedia_gdp_table", "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)", "data table"),
    ("github_repo", "https://github.com/microsoft/playwright", "github repo page"),
    ("news_homepage", "https://www.bbc.com/news", "dense news homepage"),
    ("httpbin_form", "https://httpbin.org/forms/post", "small form (banked baseline)"),
    ("github_advanced_search", "https://github.com/search/advanced", "form-heavy app page"),
    ("spa_realworld", "https://demo.realworld.show/", "JS-heavy SPA (client-rendered)"),
    ("example_com", "https://example.com", "minimal page (parity check)"),
    ("cnn_homepage", "https://www.cnn.com/", "dense news homepage #2"),
    ("spa_antdesign", "https://ant.design/components/overview/", "heavy React SPA (docs app)"),
    ("canvas_openlayers", "https://openlayers.org/en/latest/examples/icon.html", "canvas-rendered map"),
]

BUDGET = 5000


async def measure_raw(page):
    """Incumbent-shaped baselines measured on this machine."""
    out = {}
    try:
        snap = await page._snapshot_for_ai()  # exactly what playwright-mcp serializes
        out["ai_snapshot_chars"] = len(snap)
        out["ai_snapshot_tokens"] = P.ntok(snap)
        out["_snap"] = snap
    except Exception as e:  # noqa
        out["ai_snapshot_error"] = repr(e)[:200]
    try:
        aria = await page.locator("body").aria_snapshot()
        out["aria_snapshot_chars"] = len(aria)
        out["aria_snapshot_tokens"] = P.ntok(aria)
    except Exception as e:  # noqa
        out["aria_snapshot_error"] = repr(e)[:200]
    html = await page.content()
    out["html_chars"] = len(html)
    out["html_tokens"] = P.ntok(html)
    return out


async def run_one(ctx, slug, url, kind, results):
    page = await ctx.new_page()
    await page.add_init_script(P.CLOSED_SHADOW_HOOK)
    status = "?"
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        status = resp.status if resp else "?"
    except Exception as e:  # noqa
        print(f"  !! goto failed {slug}: {e!r}")
        await page.close()
        results[slug] = {"error": repr(e)[:300]}
        return
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
        load = "networkidle"
    except Exception:
        load = "domcontentloaded+settle"
    await page.wait_for_timeout(2000)

    raw = await measure_raw(page)
    snap = raw.pop("_snap", None)
    if snap is not None:
        (RAW / f"{slug}.ai_snapshot.txt").write_text(snap, encoding="utf-8")

    d = await page.evaluate(P.EXTRACT_JS)
    (RAW / f"{slug}.extract.json").write_text(json.dumps(d), encoding="utf-8")
    meta = {"status": status, "load_state": load,
            "ts": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z KST")}
    text, rung, toks, trace = P.project(d, meta, budget=BUDGET)
    (OUT / f"{slug}.projection.txt").write_text(text, encoding="utf-8")

    interactive_visible = d["aff_total"]
    results[slug] = {
        "url": url, "kind": kind, "status": status, "load": load,
        "raw": raw,
        "projection_tokens": toks, "projection_chars": len(text), "rung": rung,
        "ladder_trace": trace,
        "dom_nodes": d["completeness"]["total_elements"],
        "interactive_visible": interactive_visible,
        "hidden_interactive_stripped": d["completeness"]["hidden_interactive"],
        "regions": len(d["regions"]),
        "headings": len(d["headings"]),
        "forms": len(d["forms"]),
        "tables": len(d["tables"]),
        "frames": len(d["completeness"]["frames"]),
        "readable": d["readable"],
        "ratio_interactive_to_nodes": round(interactive_visible / max(1, d["completeness"]["total_elements"]), 4),
    }
    base = raw.get("ai_snapshot_tokens") or raw.get("aria_snapshot_tokens") or 0
    if base:
        results[slug]["multiple_vs_ai_snapshot"] = round(base / max(1, toks), 1)
    print(f"  {slug:26} raw_ai={base:>8,}  proj={toks:>6,} tok  rung={rung}  "
          f"nodes={d['completeness']['total_elements']:>6,}  act={interactive_visible}")
    await page.close()


async def main():
    only = sys.argv[1:] or None
    results = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        for slug, url, kind in PAGES:
            if only and slug not in only:
                continue
            print(f"[{slug}] {url}")
            await run_one(ctx, slug, url, kind, results)
        await ctx.close()
        await browser.close()
    prev = {}
    mf = OUT / "metrics.json"
    if mf.exists():
        prev = json.loads(mf.read_text(encoding="utf-8"))
    prev.update(results)
    mf.write_text(json.dumps(prev, indent=2), encoding="utf-8")
    print("\nwrote", mf)


if __name__ == "__main__":
    asyncio.run(main())
