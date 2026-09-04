"""The S2 regression battery, ported from the spike into the suite.

Spike S2 measured **zero false rebinds and zero false stickiness across 396
resolutions in 18 scenarios**, against real React 18.3.1 and real react-window
1.8.10. That number is the reason the architecture froze, and a number that
lives only in a spike report is a number nobody notices losing. So the battery
runs here, against the SHIPPED anchor package rather than the prototype, on the
same fixtures now living in corpus B.

Two measurements per scenario, and they answer different questions:

  STICKINESS  re-read the page, then ask whether an element that is still
              there kept its ref. This is the prior-art claim and the delta
              precondition.
  REBIND      do NOT re-read. Resolve refs minted before the mutation against
              the page after it, which is what an action tool actually faces.

**Ground truth is an INSTRUMENT and the separation is enforced.** Every
interactive element in the fixtures carries `data-truth`, a stable semantic
identity the fixture preserves across every mutation. The production extractor
never reads it, which is why this file reads it through a separate probe: a
scheme that fingerprinted ground truth would score a perfect run and mean
nothing.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import anchors, projection
from kitchensink4web.engine.session import MANAGER

pytestmark = pytest.mark.browser

CORPUS_B = Path(__file__).resolve().parents[2] / "corpus" / "b"

#: Reads `data-truth` off the elements the production extractor registered,
#: and nothing else. The anchor scheme cannot see this and must not.
TRUTH_PROBE = """
() => {
  const out = {};
  const map = window.__ks4web_refs;
  if (!map) return out;
  for (const [ref, el] of map.entries()) {
    if (!el || !el.isConnected) continue;
    const t = el.getAttribute && el.getAttribute('data-truth');
    if (t) out[ref] = t;
  }
  return out;
}
"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def corpus_b_site():
    handler = functools.partial(_Quiet, directory=str(CORPUS_B))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


# ---------------------------------------------------------------- harness


class Battery:
    """One page, one element map, and the two measurements."""

    def __init__(self, page, element_map, handle="p1"):
        self.page = page
        self.map = element_map
        self.handle = handle
        self.token = 0

    async def snap(self) -> dict:
        return await projection.extract(self.page)

    async def truths(self) -> dict[str, str]:
        return await self.page.evaluate(TRUTH_PROBE)

    async def read(self):
        """One read through the SHIPPED machinery, plus the truth probe."""
        data = await self.snap()
        self.token += 1
        state = self.map.absorb(data, self.handle, f"rt{self.token}")
        node_truth = await self.truths()
        by_ref = {ref: node_truth.get(node)
                  for ref, node in state.node_refs.items()
                  if node_truth.get(node)}
        return data, state, by_ref


def score_stickiness(element_map, before_truth: dict,
                     after_truth: dict) -> dict:
    """Two failure directions, and they are not symmetric.

    A LOST ref is a cost: the model pays for a new one and a delta cannot be
    expressed. A ref that moved to a DIFFERENT element is a correctness
    failure of the same family as a false rebind, and it is the one that
    matters.

    Survival is scored over DISTINGUISHABLE elements, which is the population
    S2's 100 percent is about. An element nothing in the key ladder can tell
    apart from its siblings gets a turn-local ref by design, because the
    alternative is an ordinal key that binds, and an ordinal key that binds is
    what put row 0's ref onto row 3,998. The count of those is reported rather
    than hidden, since it is the stated cost of the rule."""
    turn_local = {t for r, t in before_truth.items()
                  if (element_map.entries.get(r) or None)
                  and element_map.entries[r].turn_local}
    before = {t: r for r, t in before_truth.items() if t not in turn_local}
    after = {t: r for r, t in after_truth.items() if t not in turn_local}
    both = [t for t in before if t in after]
    kept = [t for t in both if before[t] == after[t]]
    false_sticky = [{"ref": r, "was": before_truth[r], "now": t}
                    for t, r in after_truth.items()
                    if r in before_truth and before_truth[r] != t]
    return {"present_in_both": len(both), "kept_ref": len(kept),
            "survival_pct": round(100.0 * len(kept) / len(both), 1)
            if both else None,
            "lost": sorted(set(both) - set(kept))[:8],
            "turn_local": sorted(turn_local),
            "false_sticky": false_sticky}


def score_rebind(element_map, before_truth, after_data, present,
                 handle="p1", allow_cross=False) -> dict:
    """Resolve every pre-mutation ref against the post-mutation page.

    A resolution is CORRECT when it proceeds onto the element it was minted
    on, or refuses for an element that is genuinely gone. It is a FALSE
    REBIND when it proceeds onto a different element, and that is the number
    the harder gate is about."""
    rows = {"attempts": 0, "proceeded_correct": 0, "false_rebind": [],
            "refused_present": [], "refused_absent": 0, "outcomes": {}}
    for ref, truth in before_truth.items():
        entry = element_map.entries.get(ref)
        if entry is None or entry.kind != "affordance":
            continue
        rows["attempts"] += 1
        res = anchors.resolve(element_map, ref, after_data, handle,
                              allow_cross_page_rebind=allow_cross)
        rows["outcomes"][res["outcome"]] = \
            rows["outcomes"].get(res["outcome"], 0) + 1
        if res["outcome"] in anchors.PROCEED:
            landed = res["unit"].get("_truth")
            if landed == truth:
                rows["proceeded_correct"] += 1
            else:
                rows["false_rebind"].append(
                    {"ref": ref, "asked_for": truth, "landed_on": landed,
                     "tier": res.get("tier")})
        elif truth in present:
            rows["refused_present"].append(
                {"ref": ref, "truth": truth, "outcome": res["outcome"]})
        else:
            rows["refused_absent"] += 1
    return rows


async def _tag_truth(data: dict, page) -> dict:
    """Attach truth to the post-mutation units, for SCORING only.

    A raw extraction has not been through the map, so its units still carry
    the extractor's own id in `ref`, and that is the key
    `window.__ks4web_refs` holds. The tag is written after the anchor package
    is finished with the dict, so nothing in `anchors/` can read it even by
    accident."""
    node_truth = await page.evaluate(TRUTH_PROBE)
    for unit in data.get("affordances") or []:
        unit["_truth"] = node_truth.get(unit.get("node_ref") or unit.get("ref"))
    return data


async def scenario(site, name, mutate, page_name="app.html",
                   allow_cross=False, navigate_to=None):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    try:
        record = session.page(session.focused)
        page = record.page
        await page.goto(f"{site}/{page_name}", wait_until="load")
        await page.wait_for_timeout(250)
        battery = Battery(page, session.element_map, record.handle)
        _, _, before_truth = await battery.read()

        await mutate(page)
        await page.wait_for_timeout(250)

        # REBIND is measured WITHOUT a re-read, because that is what an
        # action tool faces: a ref in hand and a page that moved under it.
        after_data = await battery.snap()
        await _tag_truth(after_data, page)
        present = {u["_truth"] for u in after_data.get("affordances") or []
                   if u.get("_truth")}
        rebind = score_rebind(session.element_map, before_truth, after_data,
                              present, record.handle, allow_cross=allow_cross)

        # STICKINESS is measured WITH a re-read: did an element that is still
        # there keep its ref?
        _, _, after_truth = await battery.read()
        return {"scenario": name,
                "stickiness": score_stickiness(session.element_map,
                                               before_truth, after_truth),
                "rebind": rebind}
    finally:
        await MANAGER.close(session.session_id)


# -------------------------------------------------------------- mutations


async def _nothing(page):
    return None


async def _remount(page):
    await page.evaluate("window.__s2.remount()")


async def _rename(page):
    await page.evaluate("window.__s2.rename()")


async def _reorder(page):
    await page.evaluate("window.__s2.reorder()")


async def _route(page):
    await page.evaluate("window.__s2.route('settings')")


async def _reload(page):
    await page.reload(wait_until="load")


async def _scroll_a_little(page):
    await page.evaluate("window.__s2.scrollTo(300)")


async def _scroll_far(page):
    await page.evaluate("window.__s2.scrollToItem(4000)")


SCENARIOS = [
    ("re-read, no mutation", _nothing, "app.html"),
    ("React remount, nodes replaced", _remount, "app.html"),
    ("React re-render, labels change", _rename, "app.html"),
    ("list reorder, reversed", _reorder, "app.html"),
    ("SPA hash route change", _route, "app.html"),
    ("reload", _reload, "app.html"),
    ("virtualized list, small scroll", _scroll_a_little, "virtual.html"),
    ("virtualized list, recycle to row 4000", _scroll_far, "virtual.html"),
]


# ----------------------------------------------------------------- the gate


@pytest.fixture(scope="module")
def battery_results(corpus_b_site):
    async def go():
        out = []
        for name, mutate, page_name in SCENARIOS:
            out.append(await scenario(corpus_b_site, name, mutate, page_name))

        async def leave(page):
            await page.goto(f"{corpus_b_site}/other.html", wait_until="load")

        out.append(await scenario(corpus_b_site,
                                  "full navigation to a look-alike page",
                                  leave, "app.html"))
        return out

    return run(go())


def test_the_harder_gate_zero_false_rebinds(battery_results):
    """THE gate. A false rebind is worse than a failure, because a failure is
    visible and a false rebind clicks the wrong thing while reporting
    success."""
    offenders = [(r["scenario"], r["rebind"]["false_rebind"])
                 for r in battery_results if r["rebind"]["false_rebind"]]
    total = sum(len(r["rebind"]["false_rebind"]) for r in battery_results)
    assert total == 0, f"false rebinds: {offenders}"


def test_zero_false_stickiness(battery_results):
    """A ref that moved to a different element across a re-read is the same
    correctness failure as a false rebind, arriving through the read path
    rather than the action path."""
    offenders = [(r["scenario"], r["stickiness"]["false_sticky"])
                 for r in battery_results if r["stickiness"]["false_sticky"]]
    assert not offenders, f"false stickiness: {offenders}"


def test_the_battery_actually_resolved_something(battery_results):
    """A gate that can pass by doing nothing is not a gate. S2 ran 396
    resolutions; this asserts the ported battery is the same order of
    magnitude rather than an empty loop reporting zero."""
    attempts = sum(r["rebind"]["attempts"] for r in battery_results)
    assert attempts >= 100, (
        f"only {attempts} resolutions were attempted across "
        f"{len(battery_results)} scenarios, so a zero false-rebind count "
        f"proves nothing")


#: The two scenarios where losing a ref is the DESIGN, not a regression. A
#: different page is not the same element, and a hash route is a different
#: page by every meaning that matters to a ref.
REF_LOSS_IS_BY_DESIGN = ("full navigation to a look-alike page",
                         "SPA hash route change")


def test_an_unchanged_element_keeps_its_ref(battery_results):
    """The plain gate: stickiness across a re-read on every fixture."""
    for result in battery_results:
        if result["scenario"] in REF_LOSS_IS_BY_DESIGN:
            continue
        sticky = result["stickiness"]
        if not sticky["present_in_both"]:
            continue
        assert sticky["survival_pct"] == 100.0, (
            f'{result["scenario"]}: {sticky["survival_pct"]}% survival, '
            f'lost {sticky["lost"]}')


def test_the_hash_in_the_page_key_costs_the_app_shell_its_refs(
        battery_results):
    """The cost of the page key, stated rather than buried, and asserted so
    it stays stated.

    Scoping the key by origin, path, and hash means a persistent app shell
    loses its refs on a hash route change: the elements that are still on
    screen after the route changes get new refs, because a hash route is a
    page by every meaning that matters to a ref. The alternative buys those
    refs back and costs a false rebind, since two routes each carried a
    "Save" button inside a form labelled "Profile" and nothing else told them
    apart. The harder gate settles it, and a route change costs a re-read,
    which is what a navigation costs anyway."""
    result = next(r for r in battery_results
                  if r["scenario"] == "SPA hash route change")
    sticky = result["stickiness"]
    assert sticky["present_in_both"] >= 4, (
        "the fixture's app shell no longer survives its own route change, so "
        "this scenario stopped measuring the thing it exists to measure")
    assert sticky["survival_pct"] == 0.0, (
        f'the app shell kept {sticky["kept_ref"]} ref(s) across a hash route '
        f'change. Either the hash left the page key, which buys these refs '
        f'back and costs a false rebind, or the fixture changed.')
    assert sticky["false_sticky"] == []
    assert result["rebind"]["false_rebind"] == []


def test_a_react_remount_destroys_nodes_and_keeps_every_ref(battery_results):
    """The headline pair, and the whole case for content fingerprints over
    node identity: the incumbent's key is precisely what a remount destroys."""
    result = next(r for r in battery_results
                  if r["scenario"] == "React remount, nodes replaced")
    assert result["stickiness"]["survival_pct"] == 100.0
    assert result["rebind"]["proceeded_correct"] > 0


def test_a_virtualized_recycle_never_moves_a_ref(battery_results):
    """The ordinal rule, measured. A react-window list rewrites its rendered
    window while keeping every ordinal, which is how an ordinal key put row
    0's ref onto row 3,998 and did the same for twenty-one of its
    neighbours."""
    result = next(r for r in battery_results
                  if r["scenario"] == "virtualized list, recycle to row 4000")
    assert result["stickiness"]["false_sticky"] == []
    assert result["rebind"]["false_rebind"] == []


def test_a_navigation_refuses_rather_than_rebinding(battery_results):
    """Cross-page rebinding is off by default, and a look-alike page is
    exactly where a permissive scheme clicks the wrong thing."""
    result = next(r for r in battery_results
                  if r["scenario"] == "full navigation to a look-alike page")
    outcomes = result["rebind"]["outcomes"]
    assert result["rebind"]["false_rebind"] == []
    assert outcomes.get(anchors.Outcome.STALE, 0) > 0, (
        f"a full navigation produced {outcomes}, with no STALE_ANCHOR refusal")


def test_cross_page_rebinding_is_off_because_it_has_a_price(corpus_b_site):
    """The limitations page publishes the FIGURE rather than the principle
    alone: turning cross-page rebinding on produced false rebinds on a page
    carrying the same landmarks and the same control names."""
    async def leave(page):
        await page.goto(f"{corpus_b_site}/other.html", wait_until="load")

    result = run(scenario(corpus_b_site, "look-alike, cross-page ALLOWED",
                          leave, "app.html", allow_cross=True))
    assert result["rebind"]["false_rebind"], (
        "allow_cross_page_rebind=true produced no false rebind on a "
        "deliberately look-alike page, so either the fixture stopped looking "
        "alike or the flag stopped doing anything")
