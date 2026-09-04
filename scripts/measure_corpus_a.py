"""Measure the shipped projection against frozen corpus A, under the named
estimator, with the cl100k delta reported rather than assumed.

Two things this settles that S1 could not. **The pages are frozen**, so the
numbers re-derive after Wikipedia edits its article, which is what makes a
published benchmark a benchmark. And **the estimator is `o200k_base`**, the
convention DESIGN 3.4 fixes and the meter enforces, where S1's figures were
`cl100k_base` and therefore indicative only. Conflict record #4 shows
tokenizers disagreeing by roughly 3x on this class of content, so the delta is
measured here rather than reasoned about.

The frozen pages are served over localhost and every off-origin request is
aborted, so the run is hermetic: no network, no live-page drift, no CDN
timing in the numbers.

Run:  .venv/Scripts/python.exe -X utf8 scripts/measure_corpus_a.py
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web import projection  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402
from kitchensink4web.projection import meter as meter_mod  # noqa: E402

CORPUS = ROOT / "corpus" / "a"
GATES = ROOT / "gates"

#: DESIGN 3.2's published targets, transcribed so the script reports PASS or
#: FAIL rather than leaving the reader to compare two tables by eye.
TARGETS = {
    "wikipedia_versailles": 5000,
    # REVISED IN PHASE 2, from 3,000, and recorded as a revision rather than
    # restated as a pass. The 3,000 came from S1's 2,854 measurement, taken
    # against a prototype whose scaffold was roughly 180 tokens cheaper and
    # which was WRONGLY SUPPRESSING the page's navigation: every link inside
    # an `<li>` was classified in-prose, and navigation menus are
    # `<ul><li><a>` by convention. Phase 2 recovered 124 tokens from two real
    # defects (a price quoted for expanding an empty landmark, and column
    # headers scraped out of nested tables) and then SPENT 363 restoring the
    # navigation the ranker had been discarding. The read got more useful and
    # more expensive, in that order. See DESIGN 3.2.
    "wikipedia_gdp_table": 3500,
    "httpbin_form": 900,
    "example_com": None,   # the scaffold floor, measured rather than targeted
}

#: What each target USED to be, carried so the gate report can say "revised"
#: rather than quietly printing a pass against a number nobody remembers
#: moving.
SUPERSEDED_TARGETS = {"wikipedia_gdp_table": 3000}

#: What S1 measured on the LIVE pages under cl100k_base (DESIGN 3.2). Carried
#: so the report states the two moves separately: the tokenizer change and
#: everything Phase 1 rebuilt.
S1_CL100K = {
    "wikipedia_versailles": 3726,
    "wikipedia_gdp_table": 2854,
    "httpbin_form": 758,
    "example_com": 404,
}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102, ANN002
        pass


def _serve(directory: Path) -> tuple[int, socketserver.TCPServer]:
    handler = functools.partial(_Quiet, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1], httpd


async def _measure(page, name: str, url: str, budget: int,
                   dump: Path | None = None) -> dict:
    await page.goto(url, wait_until="load", timeout=60000)
    data = await projection.extract(page)
    meta = {"url": url, "title": data["identity"]["title"], "status": 200,
            "load_state": "load", "lane": "A", "page": "p1"}
    out = {}
    for encoding in ("o200k_base", "cl100k_base"):
        meter_mod.ENCODING_NAME = encoding
        meter_mod._encoding.cache_clear()
        meter_mod._ntok_cached.cache_clear()
        proj = projection.project(data, meta, budget=budget)
        out[encoding] = {
            "tokens": proj.tokens,
            "rung": proj.rung,
            "floor_tokens": proj.trace[-1]["tokens"],
            "shape": proj.shape,
            # The whole ladder, not just the rung chosen. A page that lands on
            # rung 3 at a 5,000 budget is saying something about rungs 1 and 2
            # and the trace is where it says it.
            "trace": proj.trace,
        }
        if dump is not None and encoding == "o200k_base":
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text(proj.text, encoding="utf-8")
    meter_mod.ENCODING_NAME = "o200k_base"
    meter_mod._encoding.cache_clear()
    meter_mod._ntok_cached.cache_clear()
    return {
        "url": url,
        "nodes": data["completeness"]["total_elements"],
        "affordances_seen": data["completeness"]["affordances_collected"],
        "hidden_elements": data["completeness"].get("hidden_elements"),
        "budget": budget,
        "o200k_base": out["o200k_base"],
        "cl100k_base": out["cl100k_base"],
    }


async def main() -> None:
    manifest = json.loads((CORPUS / "MANIFEST.json").read_text(encoding="utf-8"))
    port, httpd = _serve(CORPUS)
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    rows: dict = {}
    drift: dict = {}
    try:
        record = session.page(session.focused)
        page = record.page
        # Hermetic: the frozen page is the only thing this run may read.
        await page.route(
            "**/*",
            lambda route: asyncio.ensure_future(
                route.continue_() if "127.0.0.1" in route.request.url
                else route.abort()))
        for name in manifest["pages"]:
            row = await _measure(page, name,
                                 f"http://127.0.0.1:{port}/{name}.html",
                                 budget=5000,
                                 dump=CORPUS / "out" / f"{name}.projection.txt")
            row["target"] = TARGETS.get(name)
            row["superseded_target"] = SUPERSEDED_TARGETS.get(name)
            row["s1_cl100k_live"] = S1_CL100K.get(name)
            o = row["o200k_base"]["tokens"]
            c = row["cl100k_base"]["tokens"]
            row["delta_o200k_vs_cl100k"] = o - c
            row["delta_pct"] = round(100.0 * (o - c) / c, 1) if c else None
            row["pass"] = row["target"] is None or o <= row["target"]
            rows[name] = row
            target = row["target"]
            verdict = "floor" if target is None else \
                ("PASS" if row["pass"] else "FAIL")
            # Never restate a miss as a pass. A row whose target MOVED says
            # so on the same line as its verdict, so nobody reads a green
            # PASS without seeing that the bar moved to meet it.
            if row["superseded_target"]:
                verdict += f' (target REVISED from {row["superseded_target"]})'
            print(f"{name:>22}: {row['nodes']:>6} nodes | o200k {o:>5} "
                  f"(rung {row['o200k_base']['rung']}) | cl100k {c:>5} | "
                  f"delta {o - c:>+5} | target {target} {verdict}")
        # PLAN 1.3: the live run is kept as a DRIFT CHECK against the freeze.
        # It is not the benchmark and never becomes it, because a live page
        # cannot be re-measured after it changes. Its whole job is to answer
        # "is the frozen copy still telling the truth about the real page."
        if "--live" in sys.argv:
            await page.unroute_all()
            for name, meta in manifest["pages"].items():
                try:
                    live = await _measure(page, name, meta["url"], budget=5000)
                except Exception as exc:  # noqa: BLE001
                    drift[name] = {"error": f"{exc.__class__.__name__}"}
                    continue
                frozen = rows[name]["o200k_base"]["tokens"]
                got = live["o200k_base"]["tokens"]
                drift[name] = {
                    "frozen_tokens": frozen,
                    "live_tokens": got,
                    "delta": got - frozen,
                    "delta_pct": round(100.0 * (got - frozen) / frozen, 1),
                    "frozen_nodes": rows[name]["nodes"],
                    "live_nodes": live["nodes"],
                }
                print(f"{name:>22}: DRIFT frozen {frozen:>5} -> live "
                      f"{got:>5} ({got - frozen:+d}, "
                      f"{drift[name]['delta_pct']:+.1f}%)")
    finally:
        await MANAGER.close(session.session_id)
        httpd.shutdown()

    payload = {
        "measured_kst": None,
        "corpus": "A (frozen)",
        "manifest_fetched_kst": manifest["fetched_kst"],
        "estimator": "o200k_base (DESIGN 3.4, PLAN W1)",
        "comparison_estimator": "cl100k_base (what S1 used)",
        "lane": "A(chromium) headless, all off-origin requests aborted",
        "budget_tokens": 5000,
        "rows": rows,
        "live_drift_check": drift or "not run (pass --live)",
    }
    import subprocess
    stamp = subprocess.run(["date", "+%Y-%m-%d %H:%M"], capture_output=True,
                           text=True)
    payload["measured_kst"] = stamp.stdout.strip()
    GATES.mkdir(exist_ok=True)
    (GATES / "corpus_a.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {GATES / 'corpus_a.json'}")


if __name__ == "__main__":
    asyncio.run(main())
