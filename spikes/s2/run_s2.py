"""S2: anchor durability, measured against real React and real react-window.

PLAN's S2 asks two questions with different weights.

  GATE:        an unchanged element keeps its ref across re-reads on every
               fixture, and rebind succeeds where the element genuinely
               persists.
  HARDER GATE: **zero false rebinds.** A failure is visible; a false rebind
               clicks the wrong thing and reports success.

Both need ground truth, so every interactive element in the fixtures carries
`data-truth`, a stable semantic identity the fixture preserves across every
mutation and the anchor scheme never reads. Scoring compares the truth of what
a ref resolved to against the truth of what it was minted on, which is the only
way "the right element" means anything.

Two measurements per scenario, and they answer different questions:

  STICKINESS  re-read the page, then ask whether an element that is still
              there kept its ref. This is the prior-art claim and the delta
              precondition.
  REBIND      do NOT re-read. Resolve refs minted before the mutation against
              the page after it, which is what an action tool actually faces.

Run:  .venv/Scripts/python.exe -X utf8 spikes/s2/run_s2.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import anchors  # noqa: E402
from anchors import Outcome, Session  # noqa: E402

from kitchensink4web.engine.session import MANAGER  # noqa: E402

EXTRACT = (HERE / "anchor_extract.js").read_text(encoding="utf-8")
OUT = HERE / "out"

PROCEED = (Outcome.OK, Outcome.REBOUND)


def _truths(extraction: dict) -> dict[str, dict]:
    return {el["truth"]: el for el in extraction["elements"] if el["truth"]}


async def snap(page) -> dict:
    return await page.evaluate(EXTRACT)


def score_stickiness(before: dict, after: dict) -> dict:
    """Did an element that is still there keep its ref?

    Two failure directions and they are not symmetric. A LOST ref is a cost:
    the model pays for a new one and a delta cannot be expressed. A ref that
    moved to a DIFFERENT element is a correctness failure of the same family
    as a false rebind, so it is counted separately and it is the one that
    matters."""
    b = {m["el"]["truth"]: m["ref"] for m in before["minted"] if m["el"]["truth"]}
    a = {m["el"]["truth"]: m["ref"] for m in after["minted"] if m["el"]["truth"]}
    ref_to_truth_before = {v: k for k, v in b.items()}
    both = [t for t in b if t in a]
    kept = [t for t in both if b[t] == a[t]]
    false_sticky = []
    for truth, ref in a.items():
        was = ref_to_truth_before.get(ref)
        if was is not None and was != truth:
            false_sticky.append({"ref": ref, "was": was, "now": truth})
    node_survived = 0
    bt, at = _truths(before["extraction"]), _truths(after["extraction"])
    for t in both:
        if bt[t]["node_uid"] == at[t]["node_uid"]:
            node_survived += 1
    return {
        "present_in_both": len(both),
        "kept_ref": len(kept),
        "survival_pct": round(100.0 * len(kept) / len(both), 1) if both else None,
        "lost": sorted(set(both) - set(kept))[:8],
        "false_sticky": false_sticky,
        "dom_node_survived": node_survived,
        "dom_node_survival_pct":
            round(100.0 * node_survived / len(both), 1) if both else None,
    }


def score_rebind(session: Session, before: dict, after_state: dict,
                 **kw) -> dict:
    """Resolve every pre-mutation ref against the post-mutation page.

    A resolution is CORRECT when it proceeds onto the element it was minted
    on, or refuses for an element that is genuinely gone. It is a FALSE
    REBIND when it proceeds onto a different element, and that is the number
    the harder gate is about."""
    after_truths = _truths(after_state["extraction"])
    rows = {"proceeded_correct": 0, "false_rebind": [], "refused_present": [],
            "refused_absent": 0, "outcomes": {}, "attempts": 0}
    for m in before["minted"]:
        truth = m["el"]["truth"]
        if not truth:
            continue
        rows["attempts"] += 1
        res = session.resolve(m["ref"], after_state, **kw)
        rows["outcomes"][res["outcome"]] = \
            rows["outcomes"].get(res["outcome"], 0) + 1
        still_there = truth in after_truths
        if res["outcome"] in PROCEED:
            landed = res["element"]["truth"]
            if landed == truth:
                rows["proceeded_correct"] += 1
            else:
                rows["false_rebind"].append(
                    {"ref": m["ref"], "asked_for": truth, "landed_on": landed,
                     "tier": res.get("tier")})
        elif still_there:
            rows["refused_present"].append(
                {"ref": m["ref"], "truth": truth, "outcome": res["outcome"]})
        else:
            rows["refused_absent"] += 1
    persisted = rows["proceeded_correct"] + len(rows["refused_present"]) \
        + len([f for f in rows["false_rebind"] if f["asked_for"] in after_truths])
    rows["rebind_survival_pct"] = (
        round(100.0 * rows["proceeded_correct"] / persisted, 1)
        if persisted else None)
    rows["false_rebind_pct"] = (
        round(100.0 * len(rows["false_rebind"]) / rows["attempts"], 2)
        if rows["attempts"] else None)
    rows["refused_present"] = rows["refused_present"][:8]
    return rows


# --------------------------------------------------------------- scenarios

async def _goto(page, port, name):
    await page.goto(f"http://127.0.0.1:{port}/{name}", wait_until="load")
    await page.wait_for_timeout(250)


async def scenario(page, port, name, setup, mutate, *, cross_page_test="url",
                   fuzzy=True, weak_keys=True, allow_cross=False,
                   page_name="app.html"):
    session = Session()
    session.weak_keys = weak_keys
    await _goto(page, port, page_name)
    if setup:
        await setup(page)
    before_snap = await snap(page)
    before = session.read(before_snap)
    await mutate(page)
    await page.wait_for_timeout(250)
    after_snap = await snap(page)
    after_state = {"extraction": after_snap,
                   "index": anchors.index(after_snap["elements"])}
    rebind = score_rebind(session, before, after_state,
                          fuzzy=fuzzy, cross_page_test=cross_page_test,
                          allow_cross_page_rebind=allow_cross)
    after = session.read(after_snap)
    return {
        "scenario": name,
        "elements_before": len(before_snap["elements"]),
        "elements_after": len(after_snap["elements"]),
        "url_before": before_snap["url"], "url_after": after_snap["url"],
        "same_document": before_snap["doc_epoch"] == after_snap["doc_epoch"],
        "stickiness": score_stickiness(before, after),
        "rebind": rebind,
    }


async def entry_conditions(page, port) -> dict:
    """DESIGN 3.5's five pre-ladder cases, each exercised for real.

    They are checked in order and none of them enters the fuzzy tier, which
    is the whole reason they exist as a separate table."""
    out = {}
    session = Session()
    await _goto(page, port, "app.html")
    s1 = await snap(page)
    before = session.read(s1)
    state = {"extraction": s1, "index": anchors.index(s1["elements"])}
    save = next(m["ref"] for m in before["minted"]
                if m["el"]["truth"] == "btn-save")

    out["never_minted"] = session.resolve("e9999", state)
    out["wrong_handle"] = session.resolve(save, state, handle="p2")

    await page.evaluate("window.__s2.dialog(true)")
    await page.wait_for_timeout(200)
    s_modal = await snap(page)
    modal_state = {"extraction": s_modal,
                   "index": anchors.index(s_modal["elements"])}
    # The modal case must beat every other condition, so it is asked with a
    # ref that would otherwise refuse NOT_FOUND. Order is the assertion.
    out["modal_blocks_first"] = session.resolve("e9999", modal_state)
    out["modal_blocks_valid_ref"] = session.resolve(save, modal_state)
    await page.evaluate("window.__s2.dialog(false)")
    await page.wait_for_timeout(200)

    # A gone entry: route away, re-read so the entry is marked gone, then ask
    # for it. The refusal must carry what the ref used to be.
    await page.evaluate("window.__s2.route('settings')")
    await page.wait_for_timeout(250)
    s2 = await snap(page)
    session.read(s2)
    state2 = {"extraction": s2, "index": anchors.index(s2["elements"])}
    out["gone_entry_url_policy"] = session.resolve(save, state2)
    out["gone_entry_document_policy"] = session.resolve(
        save, state2, cross_page_test="document")
    out["gone_entry_cross_page_allowed"] = session.resolve(
        save, state2, cross_page_test="document", allow_cross_page_rebind=True)

    # And the ambiguity case, which is not an entry condition but is the
    # house rule the ladder exists to protect: two "Delete" buttons in one
    # form, resolved after a remount that destroys the fingerprints.
    session3 = Session()
    await _goto(page, port, "app.html")
    s3 = await snap(page)
    b3 = session3.read(s3)
    dref = next(m["ref"] for m in b3["minted"]
                if m["el"]["truth"] == "btn-delete-a")
    await page.evaluate("window.__s2.rename()")
    await page.wait_for_timeout(250)
    s4 = await snap(page)
    out["duplicate_names_after_rename"] = session3.resolve(
        dref, {"extraction": s4, "index": anchors.index(s4["elements"])})
    return out


async def main() -> None:
    import functools
    import http.server
    import socketserver
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(HERE / "fixtures"))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    anchors.assert_no_instruments()
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    results = []
    try:
        page = session.page(session.focused).page

        async def nothing(p):
            return None

        async def remount(p):
            await p.evaluate("window.__s2.remount()")

        async def rename(p):
            await p.evaluate("window.__s2.rename()")

        async def reorder(p):
            await p.evaluate("window.__s2.reorder()")

        async def route(p):
            await p.evaluate("window.__s2.route('settings')")

        async def leave(p):
            await p.goto(f"http://127.0.0.1:{port}/other.html",
                         wait_until="load")

        async def reload(p):
            await p.reload(wait_until="load")

        async def scroll_a_little(p):
            await p.evaluate("window.__s2.scrollTo(300)")

        async def scroll_far(p):
            await p.evaluate("window.__s2.scrollToItem(4000)")

        for fuzzy in (True, False):
            for weak in (True, False):
                tag = f"fuzzy={'on' if fuzzy else 'off'},weak_keys={'on' if weak else 'off'}"
                common = dict(fuzzy=fuzzy, weak_keys=weak)
                results.append(await scenario(
                    page, port, f"re-read, no mutation [{tag}]",
                    None, nothing, **common))
                results.append(await scenario(
                    page, port, f"React remount (nodes replaced) [{tag}]",
                    None, remount, **common))
                results.append(await scenario(
                    page, port, f"React re-render, labels change [{tag}]",
                    None, rename, **common))
                results.append(await scenario(
                    page, port, f"list reorder (reversed) [{tag}]",
                    None, reorder, **common))
                results.append(await scenario(
                    page, port, f"SPA route change, url policy [{tag}]",
                    None, route, **common))
                results.append(await scenario(
                    page, port, f"SPA route change, document policy [{tag}]",
                    None, route, cross_page_test="document", **common))
                results.append(await scenario(
                    page, port,
                    f"SPA route change, document policy, cross-page ALLOWED [{tag}]",
                    None, route, cross_page_test="document",
                    allow_cross=True, **common))
                results.append(await scenario(
                    page, port, f"full navigation to a look-alike page [{tag}]",
                    None, leave, cross_page_test="document", **common))
                results.append(await scenario(
                    page, port,
                    f"full navigation to a look-alike page, cross-page ALLOWED [{tag}]",
                    None, leave, cross_page_test="document",
                    allow_cross=True, **common))
                results.append(await scenario(
                    page, port, f"reload, document policy [{tag}]",
                    None, reload, cross_page_test="document", **common))
                results.append(await scenario(
                    page, port, f"reload, url policy [{tag}]",
                    None, reload, cross_page_test="url", **common))
                results.append(await scenario(
                    page, port, f"virtualized list, small scroll [{tag}]",
                    None, scroll_a_little, page_name="virtual.html", **common))
                results.append(await scenario(
                    page, port, f"virtualized list, recycle to row 4000 [{tag}]",
                    None, scroll_far, page_name="virtual.html", **common))

        entries = await entry_conditions(page, port)
    finally:
        await MANAGER.close(session.session_id)
        httpd.shutdown()

    stamp = subprocess.run(["date", "+%Y-%m-%d %H:%M"], capture_output=True,
                           text=True).stdout.strip()
    # The recommended configuration, separated from the experiments. Every
    # other row in the run exists to price a departure from it.
    def picked(r):
        n = r["scenario"]
        return ("weak_keys=off" in n and "document policy" not in n
                and "ALLOWED" not in n)

    rec = [r for r in results if picked(r)]
    summary = {
        "recommended_config": "weak_keys=off (no ordinal rungs), "
                              "cross-page test = URL, "
                              "allow_cross_page_rebind=false",
        "scenarios": len(rec),
        "resolutions_attempted": sum(r["rebind"]["attempts"] for r in rec),
        "false_rebinds": sum(len(r["rebind"]["false_rebind"]) for r in rec),
        "false_stickiness": sum(len(r["stickiness"]["false_sticky"])
                                for r in rec),
        "cost_of_allowing_cross_page": sum(
            len(r["rebind"]["false_rebind"]) for r in results
            if "ALLOWED" in r["scenario"] and "weak_keys=off" in r["scenario"]),
        "cost_of_document_identity_policy": sum(
            len(r["rebind"]["false_rebind"]) for r in results
            if "document policy" in r["scenario"]
            and "ALLOWED" not in r["scenario"]
            and "weak_keys=off" in r["scenario"]),
        "cost_of_ordinal_key_rungs": sum(
            len(r["stickiness"]["false_sticky"]) for r in results
            if "weak_keys=on" in r["scenario"]),
    }
    payload = {"measured_kst": stamp, "summary": summary,
               "scenarios": results, "entry_conditions": entries,
               "key_ladder": [k for k, _ in anchors.KEY_LADDER]}
    OUT.mkdir(exist_ok=True)
    (OUT / "s2.json").write_text(json.dumps(payload, indent=1, default=str),
                                 encoding="utf-8")

    print(f"{'scenario':<62} {'stick':>6} {'rebind':>7} {'false':>6}")
    for r in results:
        s = r["stickiness"]
        b = r["rebind"]
        print(f"{r['scenario']:<62} {str(s['survival_pct']):>6} "
              f"{str(b['rebind_survival_pct']):>7} "
              f"{len(b['false_rebind']):>6}")
    total_false = sum(len(r["rebind"]["false_rebind"]) for r in results)
    total_false_sticky = sum(len(r["stickiness"]["false_sticky"])
                             for r in results)
    print("\nRECOMMENDED CONFIG: " + summary["recommended_config"])
    for k in ("scenarios", "resolutions_attempted", "false_rebinds",
              "false_stickiness", "cost_of_allowing_cross_page",
              "cost_of_document_identity_policy", "cost_of_ordinal_key_rungs"):
        print(f"  {k:<36} {summary[k]}")
    print(f"\nfalse rebinds across every scenario: {total_false}")
    print(f"false stickiness across every scenario: {total_false_sticky}")
    print(f"wrote {OUT / 's2.json'}")


if __name__ == "__main__":
    asyncio.run(main())
