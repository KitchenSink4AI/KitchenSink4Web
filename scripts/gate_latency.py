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

**A LOAD CONTROL, added in Phase 2, and it is the same discipline the orphan
gate needed for the opposite reason.** That gate had to prove it could FAIL;
this one has to prove that a failure is the CODE'S. Wall-clock on a shared
developer machine is not a property of the code alone: a Phase 2 run measured
798 ms p95 at 50,000 nodes against the 500 ms bound, and the COMMITTED PHASE 1
EXTRACTOR measured 963 ms on the same machine minutes later, against the 417
ms it had recorded when the machine was quiet. A gate reporting RED under
those conditions is reporting on the machine and calling it a code
regression.

So every run interleaves a reference arm, the extractor exactly as committed
at HEAD, against the working tree's, in the same process and on the same page,
one repetition after the other. Three outcomes, and none of them turns a red
into a green:

  GREEN         the treatment is inside budget.
  RED           the treatment is over budget and the reference is inside it,
                so the cost is the code's.
  UNCERTIFIED   both are over the same budget, so this machine cannot run the
                gate right now. Reported as NOT GREEN, with the treatment's
                measured cost over the reference, and it exits non-zero
                exactly like a red.

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

#: Twenty rather than ten, and it is a correctness fix rather than a comfort
#: one. With ten samples `pct(values, 0.95)` selects index 9, which IS the
#: maximum, so the gate was calling the slowest of ten runs a p95 and failing
#: on any single scheduling hiccup. Twenty puts the 95th percentile at the
#: second-slowest, which is what the number claims to be.
REPS = 20


def _reference_extractor():
    """The reference arm, read through git so it cannot drift with the
    working tree. A control that moves with the thing it controls for is not
    a control."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:src/kitchensink4web/projection/extract.js"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 and out.stdout else None
    except Exception:
        return None


REFERENCE_JS = _reference_extractor()

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

    reference_ms = []
    for _ in range(REPS):
        t = time.perf_counter()
        data = await projection.extract(page)
        extract_ms.append((time.perf_counter() - t) * 1000)
        # Interleaved rather than batched, so drift over the run hits both
        # arms equally instead of landing on whichever went second.
        if REFERENCE_JS:
            t = time.perf_counter()
            await page.evaluate(REFERENCE_JS, {"root": None})
            reference_ms.append((time.perf_counter() - t) * 1000)
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
        "reference_p50": pct(reference_ms, 0.5) if reference_ms else None,
        "reference_p95": pct(reference_ms, 0.95) if reference_ms else None,
        "cost_vs_reference_pct": (
            round(100.0 * (pct(extract_ms, 0.5) / pct(reference_ms, 0.5) - 1))
            if reference_ms and pct(reference_ms, 0.5) else None),
    }


async def main() -> int:
    srv, base = fixtures_server.start()
    rows: list[dict] = []
    failures: list[str] = []
    uncertified = []
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    try:
        page = session.page(session.focused).page
        for nodes, budget_ms in LADDER:
            row = await measure(page, f"{base}/big?n={nodes}")
            row["budget_ms"] = budget_ms
            row["pass"] = (row["projection_p95"] <= budget_ms
                           and row["python_p95"] <= PYTHON_ASSEMBLY_BUDGET_MS)
            # A control needs HEADROOM to be a control. A reference arm
            # sitting two percent under the budget is not evidence that the
            # machine could have passed; it is evidence that the machine is
            # nearly failing too, and attributing the miss to the code on
            # that basis is a coin flip wearing a verdict.
            reference_over = (row["reference_p95"] is not None
                              and row["reference_p95"] > budget_ms * 0.8)
            row["reference_also_over_budget"] = reference_over
            if row["projection_p95"] > budget_ms:
                # Attribution, not absolution. When the reference arm is over
                # the same budget on the same machine in the same run, this
                # machine cannot certify the bound today, and saying so is
                # more useful than a red that blames the code.
                note = (f' (reference arm {row["reference_p95"]} ms, ALSO '
                        f'over budget here; the treatment costs '
                        f'{row["cost_vs_reference_pct"]:+d}% over it at p50)'
                        if reference_over else
                        f' (reference arm {row["reference_p95"]} ms, inside '
                        f'budget, so the cost is the code\'s)')
                (uncertified if reference_over else failures).append(
                    f'{row["nodes"]} nodes: projection p95 '
                    f'{row["projection_p95"]} ms over the {budget_ms} ms '
                    f'budget' + note)
            if row["python_p95"] > PYTHON_ASSEMBLY_BUDGET_MS:
                # The SAME load control the projection check has, folded in
                # with Phase 4. Phase 3 found the assembly p95 wobbling 0.3 to
                # 1.5 ms against its 10.0 ms budget on back-to-back runs of
                # identical code, all clearing at idle: a scheduler hiccup was
                # getting charged to the code because this check, unlike the
                # projection check, had no machine-load escape. When the JS
                # reference arm is ALSO over 80 percent of its budget on the
                # same interleaved run, this machine cannot certify a
                # sub-millisecond assembly bound today, so the miss is
                # UNCERTIFIED rather than RED. It still exits non-zero; it
                # never turns a red into a green.
                target = uncertified if reference_over else failures
                note = (' (reference arm also over its budget on this run, so '
                        'the machine is loaded; a sub-ms assembly bound cannot '
                        'be certified here today)' if reference_over else '')
                target.append(
                    f'{row["nodes"]} nodes: Python assembly p95 '
                    f'{row["python_p95"]} ms over the '
                    f'{PYTHON_ASSEMBLY_BUDGET_MS} ms budget' + note)
            rows.append(row)
            print(f'{row["nodes"]:>7} nodes | extract p50 {row["extract_p50"]:>7} '
                  f'p95 {row["extract_p95"]:>7} | python p95 {row["python_p95"]:>6} '
                  f'| ref p50 {str(row["reference_p50"]):>7} '
                  f'| projection p95 {row["projection_p95"]:>7} ms '
                  f'(budget {budget_ms}) | {row["tokens"]} tok, rung {row["rung"]}'
                  f' | {"PASS" if row["pass"] else ("UNCERTIFIED" if row["reference_also_over_budget"] else "FAIL")}')
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
         "reference_arm": "extract.js as committed at HEAD, interleaved",
         "rows": rows, "failures": failures,
         "uncertified": uncertified}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    if failures:
        print("LATENCY GATE RED (the code is over budget):")
        for f in failures:
            print("  -", f)
    if uncertified:
        print("LATENCY GATE UNCERTIFIED (this machine cannot run it now: the "
              "reference arm is over the same budget):")
        for f in uncertified:
            print("  -", f)
    if failures or uncertified:
        return 1
    print("LATENCY GATE GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
