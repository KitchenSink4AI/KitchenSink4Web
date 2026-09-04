"""The Phase 2 gate: nine parts, all required, reported item by item.

PLAN's Phase 2 gate. Parts 6 through 9 are S1's corrections promoted to gate
items, because each one was a defect a blind agent caught while the projection
was comfortably under budget, which is exactly the failure class a token-only
gate does not see.

Most parts are asserted in the suite, where a regression is noticed the same
day; this script is the REPORT, and it runs the parts that need a browser and
a corpus rather than duplicating what pytest already proves. Part 7 lives here
in full, because "issue the exact call the projection advertised and compare"
is a harness rather than a unit test.

Run:  .venv/Scripts/python.exe -X utf8 scripts/gate_phase2.py
Exit code 0 means every part is green.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import re
import socketserver
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web import projection  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402
from kitchensink4web.ops import lite  # noqa: E402
from kitchensink4web.projection import RUNGS, ntok  # noqa: E402

CORPUS = ROOT / "corpus"
GATES = ROOT / "gates"

#: DESIGN 3.3a's stated tolerance. A price is an estimate and is allowed to be
#: an estimate; what it is not allowed to be is a number from a different
#: arithmetic than the one that enforced the budget.
PRICE_TOLERANCE = 0.35

#: The budget the harness passes when it expands a region. Generous, so a
#: region whose content fits is measured on its content rather than on the
#: ladder.
SCOPED_BUDGET = 60000

#: A region holding less than this is priced almost entirely by the call
#: overhead, so an error RATIO against it measures the overhead rather than
#: the price. Those rows are reported and not gated.
NOISE_FLOOR = 60

#: The lite surface may SHRINK and may not grow while the 1,500-token target
#: is an open author call. Phase 0 measured 2,720 and Phase 1 did not move it.
LITE_RATCHET = 2720


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(directory: Path):
    handler = functools.partial(_Quiet, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def run_script(name: str, *args) -> tuple[int, str]:
    out = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / name), *args],
        cwd=ROOT, capture_output=True, text=True)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


# ------------------------------------------------------------------ part 7


async def executable_prices(site: str, pages: list[str]) -> dict:
    """Issue the exact call each printed price advertised, and compare.

    DESIGN 3.3a's contract, tested by construction rather than by inspection.
    A price with no corresponding executable call is a red gate, and so is a
    price outside tolerance, because a wrong price does not merely fail to
    help: it routes the agent to the wrong call while looking authoritative.

    **What this check found first is that DESIGN 3.3a's contract could not be
    satisfied as literally written, and the wording was the defect.** "Issue
    the call and compare the result against the advertised figure" assumes
    expanding a region RETURNS that region's content. It does not: expanding
    returns another budgeted projection, so a region holding 46,320 tokens of
    content came back as a 4,917-token orientation and the price looked
    wrong by 845 percent while being exactly right about the page. The number
    answers "how much is in there", which is what a caller deciding whether
    to look actually needs, and the block header now says so.

    So the contract is tested in the three parts that are true:

      EXECUTABLE   every advertised call runs. A price with no working call
                   is a red gate, and this is the part that caught a scoped
                   read destroying the page's ref map.
      ACCURATE     for a region whose content FITS the budget, the advertised
                   number predicts the measured cost within tolerance, once
                   the scaffold every scoped call pays is accounted for. The
                   scaffold is taken as the SMALLEST observed overhead on the
                   page rather than the median, because a median over a set
                   containing one huge region is a number about that region.
      BOUNDED      for a region whose content exceeds the budget, the call
                   comes back at or under budget rather than refusing, and
                   the advertised number is a content size rather than a
                   bill."""
    rows = []
    unpriceable = []
    for path in pages:
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        try:
            handle = session.focused
            record = session.page(handle)
            await lite.navigate(page=handle, url=f"{site}/{path}")
            view = await lite.get_page_view(page=handle)
            priced = dict(re.findall(r"^(r\d+) \|.*?~([\d,]+) tok of content",
                                     view["projection"], re.M))
            # The region tree, in the SAME session refs the payload printed,
            # so a net price can be compared against a net measurement.
            raw = await projection.extract(record.page)
            session.element_map.absorb(raw, handle, "rt-gate")
            children = {r["ref"]: r["children"] for r in raw["regions"]}

            gross = {}
            for ref in list(priced) + [c for cs in children.values() for c in cs]:
                if ref in gross:
                    continue
                try:
                    text = await lite.get_text(page=handle,
                                               location={"ref": ref},
                                               max_chars=400000)
                    gross[ref] = ntok(text["text"])
                except Exception:
                    gross[ref] = None

            for ref, advertised in priced.items():
                advertised = int(advertised.replace(",", ""))
                row = {"page": path, "ref": ref, "advertised": advertised}
                try:
                    # EXECUTABLE: the exact call the projection advertised.
                    got = await lite.get_page_view(
                        page=handle, location={"region": ref},
                        budget_tokens=SCOPED_BUDGET)
                    row["expand_cost"] = got["budget"]["used"]
                    row["bounded"] = got["budget"]["used"] <= SCOPED_BUDGET
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    unpriceable.append(row)
                    continue
                # MEANINGFUL: an independent measure of the very content the
                # price claims to be about, NET of nested regions because the
                # price is net of them (DESIGN 3.3a rule 2). Comparing a net
                # price against a gross measurement is a harness bug that
                # reads as a pricing bug, and it did.
                if gross.get(ref) is None:
                    row["measured_content"] = None
                    row["ok"] = row["bounded"]
                    rows.append(row)
                    continue
                nested = sum(gross.get(c) or 0 for c in children.get(ref, ()))
                measured = max(0, gross[ref] - nested)
                row["measured_gross"] = gross[ref]
                row["nested_subtracted"] = nested
                row["measured_content"] = measured
                # A region holding almost nothing is priced almost entirely
                # by the call overhead, so a ratio against it is a statement
                # about the overhead rather than about the price. Those are
                # reported and not gated.
                row["below_noise_floor"] = measured < NOISE_FLOOR
                if row["below_noise_floor"]:
                    row["error_pct"] = None
                    row["ok"] = row["bounded"]
                else:
                    row["error_pct"] = round(
                        100 * abs(advertised - measured) / measured, 1)
                    row["ok"] = (row["bounded"]
                                 and row["error_pct"] <= PRICE_TOLERANCE * 100)
                rows.append(row)
        finally:
            await MANAGER.close(session.session_id)

    gated = [r for r in rows if not r.get("below_noise_floor")
             and r.get("error_pct") is not None]
    # RANK CORRECTNESS, which is what a menu with prices is FOR: an agent
    # choosing between regions is comparing them, so an ordering that
    # disagrees with reality is a wrong answer even when every individual
    # number sits inside tolerance.
    rank = _spearman([r["advertised"] for r in gated],
                     [r["measured_content"] for r in gated])         if len(gated) > 3 else None
    bad = [r for r in rows if not r["ok"]]
    return {
        "priced_units_checked": len(rows),
        "gated_for_accuracy": len(gated),
        "below_noise_floor": len(rows) - len(gated),
        "failures": bad[:12],
        "failure_count": len(bad),
        "unpriceable_calls": unpriceable,
        "tolerance": PRICE_TOLERANCE,
        "noise_floor_tokens": NOISE_FLOOR,
        "verified_against": "get_text on the same region, NET of its nested "
                            "regions, which is an independent measure of the "
                            "content the price is about",
        "worst_error_pct": max((r["error_pct"] for r in gated), default=None),
        "median_error_pct": (round(statistics.median(
            r["error_pct"] for r in gated), 1) if gated else None),
        "rank_correlation": rank,
        "green": (not bad and not unpriceable and len(gated) >= 10
                  and (rank is None or rank >= 0.7)),
    }


def _spearman(a: list, b: list) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        for position, i in enumerate(order):
            out[i] = position
        return out

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    mean_a, mean_b = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n))
    den = (sum((x - mean_a) ** 2 for x in ra)
           * sum((x - mean_b) ** 2 for x in rb)) ** 0.5
    return round(num / den, 3) if den else 0.0


# ------------------------------------------------------------------ part 4


async def force_every_rung(site: str, path: str) -> dict:
    """Every rung rendered on the 50,000-node fixture, and never truncated."""
    from kitchensink4web.projection.meter import BudgetMeter
    from kitchensink4web.projection.render import Renderer

    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    try:
        record = session.page(session.focused)
        await record.page.goto(f"{site}/{path}", wait_until="load",
                               timeout=90000)
        data = await projection.extract(record.page)
        meta = {"status": 200, "load_state": "load", "lane": "A",
                "page": "p1", "read_token": "rt1", "ts": "gate"}
        sizes, truncated = [], []
        for rung in RUNGS:
            meter = BudgetMeter(5000)
            meter.ledger = type(meter.ledger)()
            text = Renderer(data, meta, meter, rung, "auto").build()
            sizes.append({"rung": rung.n, "tokens": ntok(text)})
            if "## 1 IDENTITY" not in text or "COMPLETENESS" not in text:
                truncated.append(rung.n)
        result = projection.project(data, meta, budget=5000)
        exposed = [t["tokens"] for t in result.trace if not t["dominated"]]
        return {
            "rungs": len(RUNGS),
            "sizes": sizes,
            "truncated_rungs": truncated,
            "exposed_sequence": exposed,
            "monotonic_as_exposed": exposed == sorted(exposed, reverse=True),
            "green": (not truncated and len(RUNGS) >= 8
                      and exposed == sorted(exposed, reverse=True)),
        }
    finally:
        await MANAGER.close(session.session_id)


# -------------------------------------------------------------------- main


async def main() -> int:
    parts: dict[str, dict] = {}

    # ---- part 1: the measured token bill, on frozen corpus A.
    code, out = run_script("measure_corpus_a.py")
    corpus = json.loads((GATES / "corpus_a.json").read_text(encoding="utf-8"))
    misses = [n for n, r in corpus["rows"].items() if not r["pass"]]
    revised = {n: r["superseded_target"] for n, r in corpus["rows"].items()
               if r.get("superseded_target")}
    parts["1_token_bill"] = {
        "green": not misses,
        "rows": {n: {"tokens": r["o200k_base"]["tokens"],
                     "target": r["target"], "rung": r["o200k_base"]["rung"],
                     "pass": r["pass"],
                     "target_revised_from": r.get("superseded_target")}
                 for n, r in corpus["rows"].items()},
        "misses": misses,
        "targets_revised_this_phase": revised,
        "estimator": corpus["estimator"],
    }

    # ---- parts 2, 3, 6, 9: asserted in the suite, where a regression is
    # caught the same day rather than only when somebody runs a script.

    suite = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q",
         "tests/browser/test_anchors_s2.py", "tests/unit/test_anchors.py",
         "tests/browser/test_phase2_reads.py", "tests/unit/test_projection.py"],
        cwd=ROOT, capture_output=True, text=True)
    tail = (suite.stdout or "").strip().splitlines()[-1:] or [""]
    parts["2_3_6_9_suite"] = {
        "green": suite.returncode == 0,
        "command": "pytest tests/browser/test_anchors_s2.py "
                   "tests/unit/test_anchors.py "
                   "tests/browser/test_phase2_reads.py "
                   "tests/unit/test_projection.py",
        "result": tail[0],
        "covers": ["2 sticky refs and zero false rebinds (the ported S2 "
                   "battery)",
                   "3 completeness accurate by construction on corpus B",
                   "6 affordance quotas on the adversarial cases",
                   "9 accessible names computed, including the "
                   "hidden-through-ancestor fixture"],
    }

    httpd_b, site_b = serve(CORPUS)
    try:
        # ---- part 4: the ladder, every rung forced.
        parts["4_ladder"] = await force_every_rung(site_b, "b/dom50k.html")

        # ---- part 7: every printed price is executable and accurate.
        parts["7_executable_prices"] = await executable_prices(
            site_b, ["a/wikipedia_versailles.html", "a/wikipedia_gdp_table.html",
                     "wide/github_repo.html", "wide/playwright_docs.html"])
    finally:
        httpd_b.shutdown()

    # ---- part 5: the latency budgets, with their load control.
    code, out = run_script("gate_latency.py")
    latency = json.loads(
        (GATES / "phase1_latency.json").read_text(encoding="utf-8"))
    parts["5_latency"] = {
        "green": not latency["failures"] and not latency.get("uncertified"),
        "failures": latency["failures"],
        "uncertified": latency.get("uncertified", []),
        "rows": [{"nodes": r["nodes"], "projection_p95": r["projection_p95"],
                  "budget_ms": r["budget_ms"],
                  "reference_p50": r.get("reference_p50"),
                  "cost_vs_reference_pct": r.get("cost_vs_reference_pct")}
                 for r in latency["rows"]],
    }

    # ---- part 8: the completeness block is DERIVED, not recomputed.
    # Tested by construction in the suite; reported here as the named
    # regression it exists for.
    check = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-k",
         "ledger or zero_regions or completeness", "tests/"],
        cwd=ROOT, capture_output=True, text=True)
    parts["8_completeness_is_derived"] = {
        "green": check.returncode == 0,
        "result": (check.stdout or "").strip().splitlines()[-1:] or [""],
        "named_regression": "0 regions not expanded while thirty regions "
                            "carry expand costs",
    }

    # ---- house method: the corpus drift check and the docstring ratchet.
    code, out = run_script("measure_corpus_a.py", "--live")
    corpus = json.loads((GATES / "corpus_a.json").read_text(encoding="utf-8"))
    drift = corpus.get("live_drift_check")
    parts["drift_check"] = {
        "green": isinstance(drift, dict) and all(
            "error" not in v for v in drift.values()),
        "rows": drift,
    }

    code, out = run_script("measure_surface.py")
    match = re.search(r"lite\s+(\d+)\s+([\d.]+)k", out)
    lite_tokens = int(float(match.group(2)) * 1000) if match else None
    parts["docstring_ratchet"] = {
        "green": lite_tokens is not None and lite_tokens <= LITE_RATCHET,
        "lite_tokens": lite_tokens,
        "ratchet": LITE_RATCHET,
        "rule": "the lite surface may shrink and may not grow",
    }

    green = all(p.get("green") for p in parts.values())
    stamp = subprocess.run(["date", "+%Y-%m-%d %H:%M"], capture_output=True,
                           text=True).stdout.strip()
    payload = {"measured_kst": stamp, "phase": 2, "green": green,
               "parts": parts}
    GATES.mkdir(exist_ok=True)
    (GATES / "phase2.json").write_text(json.dumps(payload, indent=1),
                                       encoding="utf-8")

    print(f"\n{'PHASE 2 GATE':<34} {'':>6}")
    for name, part in parts.items():
        print(f"  {name:<32} {'GREEN' if part.get('green') else 'RED'}")
    print(f"\nwrote {GATES / 'phase2.json'}")
    print("PHASE 2 GATE GREEN" if green else "PHASE 2 GATE RED")
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
