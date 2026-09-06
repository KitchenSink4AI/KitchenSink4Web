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

So every run interleaves a reference arm against the working tree's, in the
same process and on the same page, one repetition after the other. Three
outcomes, and none of them turns a red into a green:

  GREEN         the treatment is inside budget.
  RED           the treatment is over budget and the reference is inside it,
                so the cost is the code's.
  UNCERTIFIED   both are over the same budget, so this machine cannot run the
                gate right now. Reported as NOT GREEN, with the treatment's
                measured cost over the reference, and it exits non-zero
                exactly like a red.

**THE CONTROL ARM IS THE LAST CERTIFIED COMMIT, not HEAD** (2026-09-06). It
was `git show HEAD:extract.js`, which is a control that cannot see the thing
it exists to see: the moment a regression is committed, HEAD carries it, both
arms measure it, and the gate reports UNCERTIFIED on a machine that is
perfectly quiet. The reference now comes from a detached git WORKTREE at the
commit this gate file last certified, so the arms diverge exactly when the
code has changed since that certification, and a committed regression shows up
as the treatment costing more than the last thing that passed.

**AND THE ASSEMBLY BOUND GETS ITS OWN ARM.** The 10 ms Python assembly check
used to borrow the JS arm's over-budget signal as a load proxy, which is a
different measurement standing in for this one: an extractor inside its 500 ms
budget says nothing about whether the scheduler is stealing milliseconds from
a sub-millisecond `project()`. The worktree gives a real control, because the
reference package's own `project()` can be imported alongside the working
tree's and run on the SAME extraction, interleaved, in the same process.

With no certified commit recorded there is NO control arm, and the gate says
so and treats every miss as RED. A missing control is not an excuse; it is a
missing control.

Run:  .venv/Scripts/python.exe -X utf8 scripts/gate_latency.py
Exit code 0 means the gate is green, and a green run records the commit it
certified so the next run has something to control against.
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


GATE_FILE = ROOT / "gates" / "phase1_latency.json"


def _certified_commit() -> str | None:
    """The commit this gate last certified, which is what a control arm has
    to be. Recorded by a green run, read by the next one."""
    try:
        return json.loads(GATE_FILE.read_text(encoding="utf-8")).get(
            "certified_commit") or None
    except Exception:
        return None


def _head() -> str | None:
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


class ReferenceArms:
    """A detached worktree at the last certified commit, giving BOTH control
    arms: that commit's `extract.js` to run in the live page, and that
    commit's `projection.project()` to run in this process.

    The Python half needs the package under a different top-level name, since
    the working tree's is already imported. Every import inside the package
    is relative, so a copy under a new directory name is a second, independent
    package rather than a shadow of the first."""

    def __init__(self) -> None:
        self.commit = _certified_commit()
        self.dir = None
        self.js = None
        self.project = None
        self.why = "no certified commit recorded in the gate file"

    def __enter__(self):
        if not self.commit:
            return self
        import shutil
        import subprocess
        import tempfile
        self.dir = Path(tempfile.mkdtemp(prefix="ks4web_ref_"))
        wt = self.dir / "wt"
        try:
            r = subprocess.run(
                ["git", "worktree", "add", "--detach", str(wt), self.commit],
                cwd=ROOT, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                self.why = (f"could not create a worktree at "
                            f"{self.commit[:8]}: {r.stderr.strip()[:200]}")
                return self
            pkg = wt / "src" / "kitchensink4web"
            proj = pkg / "projection"
            raw = (proj / "extract.js").read_text(encoding="utf-8")
            vis_file = proj / "visibility.js"
            vis = (vis_file.read_text(encoding="utf-8")
                   if vis_file.exists() else "")
            # The reference source gets ITS visibility block and THIS
            # process's instrument channel, because the page in front of it
            # was instrumented by this process.
            self.js = projection.instrument(raw, visibility=vis)

            import importlib
            alias = self.dir / "refsrc" / "ks4web_reference"
            alias.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(pkg, alias)
            sys.path.insert(0, str(self.dir / "refsrc"))
            self.project = importlib.import_module(
                "ks4web_reference.projection").project
            self.why = f"worktree at {self.commit[:8]}"
        except Exception as exc:                        # noqa: BLE001
            self.why = f"reference arm unavailable: {type(exc).__name__}: {exc}"
        return self

    def __exit__(self, *exc):
        import shutil
        import subprocess
        if self.dir is not None:
            try:
                subprocess.run(["git", "worktree", "remove", "--force",
                                str(self.dir / "wt")], cwd=ROOT,
                               capture_output=True, timeout=120)
            except Exception:
                pass
            shutil.rmtree(self.dir, ignore_errors=True)
        return False


#: Filled by `main()` for the duration of the run.
REFERENCE_JS = None
REFERENCE_PROJECT = None

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
    reference_project_ms = []
    for _ in range(REPS):
        t = time.perf_counter()
        data = await projection.extract(page)
        extract_ms.append((time.perf_counter() - t) * 1000)
        # Interleaved rather than batched, so drift over the run hits both
        # arms equally instead of landing on whichever went second.
        if REFERENCE_JS:
            t = time.perf_counter()
            await page.evaluate(REFERENCE_JS, {"root": None, "pin": None})
            reference_ms.append((time.perf_counter() - t) * 1000)
        meta = {"status": 200, "load_state": "load", "lane": "A(chromium)",
                "page": "p1", "read_token": "rt1", "ts": "gate"}
        t = time.perf_counter()
        result = projection.project(data, meta, budget=5000)
        project_ms.append((time.perf_counter() - t) * 1000)
        # THE ASSEMBLY BOUND'S OWN CONTROL ARM. Same extraction, same
        # process, same interleave: the certified commit's `project()` run
        # beside the working tree's, so a miss on a sub-millisecond budget
        # can be attributed instead of guessed at from the extractor's.
        if REFERENCE_PROJECT is not None:
            try:
                t = time.perf_counter()
                REFERENCE_PROJECT(data, meta, budget=5000)
                reference_project_ms.append((time.perf_counter() - t) * 1000)
            except Exception:
                # An extraction shape the older renderer cannot read is an
                # honest absence of a control, not a failure of this run.
                reference_project_ms.clear()
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
        "reference_python_p50": (pct(reference_project_ms, 0.5)
                                 if reference_project_ms else None),
        "reference_python_p95": (pct(reference_project_ms, 0.95)
                                 if reference_project_ms else None),
        "python_cost_vs_reference_pct": (
            round(100.0 * (pct(project_ms, 0.5)
                           / pct(reference_project_ms, 0.5) - 1))
            if reference_project_ms and pct(reference_project_ms, 0.5)
            else None),
    }


async def _run(arms) -> int:
    global REFERENCE_JS, REFERENCE_PROJECT
    REFERENCE_JS, REFERENCE_PROJECT = arms.js, arms.project
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
                # ITS OWN CONTROL ARM (2026-09-06). Phase 3 found the assembly
                # p95 wobbling 0.3 to 1.5 ms against its 10.0 ms budget on
                # back-to-back runs of identical code, all clearing at idle, so
                # a scheduler hiccup was getting charged to the code. The
                # answer used to be the EXTRACTOR's over-budget flag standing
                # in as a load proxy, which is a 500 ms measurement vouching
                # for a sub-millisecond one. The certified commit's own
                # `project()` runs on the same extraction in the same
                # interleave now, so this attribution is this check's.
                ref_py = row["reference_python_p95"]
                py_loaded = (ref_py is not None
                             and ref_py > PYTHON_ASSEMBLY_BUDGET_MS * 0.8)
                target = uncertified if py_loaded else failures
                if ref_py is None:
                    note = (' (no assembly control arm on this run, so the '
                            'miss is charged to the code)')
                elif py_loaded:
                    note = (f' (the certified commit\'s own assembler measured '
                            f'{ref_py} ms here, also over 80% of the same '
                            f'budget, so the machine is loaded and a sub-ms '
                            f'assembly bound cannot be certified today)')
                else:
                    note = (f' (the certified commit\'s own assembler measured '
                            f'{ref_py} ms here, inside budget, so the cost is '
                            f'the code\'s: '
                            f'{row["python_cost_vs_reference_pct"]:+d}% at p50)')
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

    green = not failures and not uncertified
    head = _head()
    out = GATE_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"measured": time.strftime("%Y-%m-%d %H:%M"), "reps": REPS,
         "lane": "A(chromium) headless", "estimator": projection.ENCODING_NAME,
         "budgets": {"projection_p95_ms": dict(LADDER),
                     "python_assembly_p95_ms": PYTHON_ASSEMBLY_BUDGET_MS},
         "reference_arm": (
             f"the LAST CERTIFIED COMMIT, not HEAD: {arms.why}. Both control "
             f"arms come from it, the extractor run in the live page and the "
             f"assembler run in this process, each interleaved with the "
             f"working tree's on the same page and the same extraction."),
         "control_commit": arms.commit,
         # Only a GREEN run moves the certification forward. A red or an
         # uncertified run leaves the control where it was, which is the
         # point: the next run still measures against the last thing that
         # actually passed rather than against the thing that just did not.
         "certified_commit": (head if green else _certified_commit()),
         "rows": rows, "failures": failures,
         "uncertified": uncertified}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"control arm: {arms.why}")
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


async def main() -> int:
    with ReferenceArms() as arms:
        if arms.js is None:
            print(f"WARNING: no control arm ({arms.why}). Every miss on this "
                  f"run is charged to the code, because a gate that absolves "
                  f"itself with a missing control is not a gate.")
        return await _run(arms)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
