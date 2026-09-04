"""Phase 1 latency gate: the projection's wall-clock cost, measured.

Token-cheap and wall-clock-expensive is the same user pain by another route,
so the bound is a gate rather than a note. The numbers come from E11 in the
engine-spike round (DESIGN 3.6a), which measured the S1 projector at 341 ms
p95 on a 50,000-node page and under 0.9 s at 100,000, and set the budget from
that measurement rather than guessing one in advance:

    projection p95 <= 500 ms up to 50,000 nodes
    projection p95 <= 1.0 s up to 100,000 nodes
    Python-side assembly p95 <= 10 ms

The fixture ladder is `spikes/engine/fixtures_server.py`, reused rather than
rebuilt so the Phase 1 numbers sit on the same synthetic pages E11 used. The
projection code under test is the shipped one, not a prototype.

Run:  .venv/Scripts/python.exe -X utf8 scripts/gate_latency.py
Exit code 0 means the gate is green.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "spikes" / "engine"))

import fixtures_server  # noqa: E402

from kitchensink4web import projection  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402

REPS = 10

#: (node target, p95 budget in ms). Set by measurement, per DESIGN 3.6a.
LADDER = ((5000, 500), (10000, 500), (25000, 500), (50000, 500),
          (100000, 1000))
PYTHON_ASSEMBLY_BUDGET_MS = 10.0


def pct(values: list[float], q: float) -> float:
    values = sorted(values)
    k = min(len(values) - 1, int(round((len(values) - 1) * q)))
    return round(values[k], 1)


async def measure(page, url: str) -> dict:
    await page.goto(url, wait_until="load", timeout=90000)
    extract_ms: list[float] = []
    project_ms: list[float] = []
    data = None

    # One discarded pass. The first extraction after a navigation pays for a
    # layout the page has not been asked for yet, and the budget is a warm
    # number: the cold cost is reported alongside rather than hidden.
    cold = time.perf_counter()
    data = await projection.extract(page)
    cold_ms = round((time.perf_counter() - cold) * 1000, 1)

    for _ in range(REPS):
        t = time.perf_counter()
        data = await projection.extract(page)
        extract_ms.append((time.perf_counter() - t) * 1000)
        meta = {"status": 200, "load_state": "load", "lane": "A(chromium)",
                "page": "p1", "read_token": "rt1", "ts": "gate"}
        t = time.perf_counter()
        result = projection.project(data, meta, budget=5000)
        project_ms.append((time.perf_counter() - t) * 1000)
    return {
        "url": url,
        "nodes": data["completeness"]["total_elements"],
        "affordances": data["completeness"]["affordances_collected"],
        "extract_cold_ms": cold_ms,
        "extract_p50": pct(extract_ms, 0.5), "extract_p95": pct(extract_ms, 0.95),
        "python_p50": pct(project_ms, 0.5), "python_p95": pct(project_ms, 0.95),
        "projection_p95": round(pct(extract_ms, 0.95) + pct(project_ms, 0.95), 1),
        "in_page_self_report_ms": data["completeness"]["extract_ms"],
        "tokens": result.tokens, "rung": result.rung,
        "reps": REPS,
        "extract_mean": round(statistics.mean(extract_ms), 1),
    }


async def main() -> int:
    srv, base = fixtures_server.start()
    rows: list[dict] = []
    failures: list[str] = []
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    try:
        page = session.page(session.focused).page
        for nodes, budget_ms in LADDER:
            row = await measure(page, f"{base}/big?n={nodes}")
            row["budget_ms"] = budget_ms
            row["pass"] = (row["projection_p95"] <= budget_ms
                           and row["python_p95"] <= PYTHON_ASSEMBLY_BUDGET_MS)
            if row["projection_p95"] > budget_ms:
                failures.append(
                    f'{row["nodes"]} nodes: projection p95 '
                    f'{row["projection_p95"]} ms over the {budget_ms} ms budget')
            if row["python_p95"] > PYTHON_ASSEMBLY_BUDGET_MS:
                failures.append(
                    f'{row["nodes"]} nodes: Python assembly p95 '
                    f'{row["python_p95"]} ms over the '
                    f'{PYTHON_ASSEMBLY_BUDGET_MS} ms budget')
            rows.append(row)
            print(f'{row["nodes"]:>7} nodes | extract p50 {row["extract_p50"]:>7} '
                  f'p95 {row["extract_p95"]:>7} | python p95 {row["python_p95"]:>6} '
                  f'| projection p95 {row["projection_p95"]:>7} ms '
                  f'(budget {budget_ms}) | {row["tokens"]} tok, rung {row["rung"]}'
                  f' | {"PASS" if row["pass"] else "FAIL"}')
    finally:
        await MANAGER.close(session.session_id)
        srv.shutdown()

    out = ROOT / "gates" / "phase1_latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"measured": time.strftime("%Y-%m-%d %H:%M"), "reps": REPS,
         "lane": "A(chromium) headless", "estimator": projection.ENCODING_NAME,
         "budgets": {"projection_p95_ms": dict(LADDER),
                     "python_assembly_p95_ms": PYTHON_ASSEMBLY_BUDGET_MS},
         "rows": rows, "failures": failures}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    if failures:
        print("LATENCY GATE RED:")
        for f in failures:
            print("  -", f)
        return 1
    print("LATENCY GATE GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
