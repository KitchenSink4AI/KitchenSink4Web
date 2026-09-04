"""S1 spike: exercise the degradation ladder offline against cached extractions.
Re-projects each page at descending budgets and reports which rung it lands on
and what that rung dropped."""
from __future__ import annotations

import json
from pathlib import Path

import projector as P

HERE = Path(__file__).parent
RAW = HERE / "out" / "raw"
OUT = HERE / "out"

BUDGETS = [5000, 2500, 1500, 900, 500]
META = {"status": 200, "load_state": "networkidle", "ts": "cached"}


def summarize_drop(d, spec):
    rung, region_cap, aff_cap, digest = spec
    regs = len(d["regions"])
    dropped_regions = 0 if region_cap is None else max(0, regs - region_cap)
    return (f"regions {regs - dropped_regions}/{regs}, affordance groups<={aff_cap} "
            f"(of {d['aff_total']} elements), digest={digest}")


def main():
    rows = []
    for f in sorted(RAW.glob("*.extract.json")):
        slug = f.name.replace(".extract.json", "")
        d = json.loads(f.read_text(encoding="utf-8"))
        for b in BUDGETS:
            text, rung, toks, trace = P.project(d, META, budget=b)
            spec = next((s for s in P.RUNGS if s[0] == rung), None)
            drop = summarize_drop(d, spec) if spec else "REFUSED (floor over budget)"
            rows.append({"page": slug, "budget": b, "rung": rung, "tokens": toks,
                         "kept": drop,
                         "rung_costs": {t["rung"]: t["tokens"] for t in trace}})
            if b == 900:
                (OUT / f"{slug}.projection.b900.txt").write_text(text, encoding="utf-8")
    (OUT / "ladder.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"{'page':26} {'budget':>7} {'rung':>5} {'tokens':>7}  kept")
    for r in rows:
        print(f"{r['page']:26} {r['budget']:>7} {r['rung']:>5} {r['tokens']:>7}  {r['kept']}")
    print()
    print("Per-page cost of each rung (tokens):")
    seen = set()
    for r in rows:
        if r["page"] in seen:
            continue
        seen.add(r["page"])
        print(f"  {r['page']:26} " + "  ".join(f"r{k}={v}" for k, v in sorted(r["rung_costs"].items())))


if __name__ == "__main__":
    main()
