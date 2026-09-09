"""Measure phase 3 against the same fixtures phase 2 measured, plus phase 1's.

Every number here is a MEDIAN of repeated rounds on the same page, taken
after a warm-up, with the clock around the tool call only. What is new versus
`ext_phase2_measure.py`:

- WALK COUNTING. The expensive thing on this lane is the in-page pass, so the
  harness counts `page.evaluate` calls per tool as well as timing them. A
  latency number that got better because the machine was quiet reads the same
  as one that got better because the tool stopped walking the page twice; the
  walk count tells them apart.
- CACHE ACCOUNTING. Hits and misses on the unchanged-page path, so a
  repeated-read number is reported alongside whether the fast path was the
  thing that produced it.
- THE COLD FIRST READ, measured in a subprocess. Phase 2 reported 419 ms for
  the first read after a navigation and read it as the bundle injection. Most
  of it was the tokenizer, which loads once per process, so a harness that has
  already rendered a projection cannot see it at all.
- PHASE 1'S 228 KB PAGE, which phase 2 did not read through the tool surface.

    python scripts/ext_phase3_measure.py --json out.json

Everything runs hidden: `-headless`, `CREATE_NO_WINDOW`, stdin at DEVNULL, a
scratch profile outside the vault, and a kill that names its own process tree.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web import anchors                                # noqa: E402
from kitchensink4web.engine import lanes                           # noqa: E402
from kitchensink4web.engine import session as _session             # noqa: E402
from kitchensink4web.extension import lane as _extlane             # noqa: E402
from kitchensink4web.extension import register                     # noqa: E402
from kitchensink4web.extension.bridge import Bridge                # noqa: E402
from kitchensink4web.ops import extops                             # noqa: E402
from kitchensink4web.policy import budgets, consent, readonly      # noqa: E402
from kitchensink4web.projection import meter as _meter             # noqa: E402
from tests.fixtures.firefox_harness import (                       # noqa: E402
    HeadlessFirefox, PageServer, RDPClient, find_firefox, free_port)

sys.path.insert(0, str(ROOT / "scripts"))
from ext_phase1_validate import heavy_page as phase1_heavy_page    # noqa: E402
from ext_phase2_measure import LIGHT_PAGE, heavy_page              # noqa: E402


FORM_PAGE = """<!doctype html>
<title>KS4Web phase 3 form page</title>
<body><h1>Form</h1>
<form method="post" action="/submit">
  <label for="a">Name</label><input id="a" name="a" type="text">
  <label for="b">Email</label><input id="b" name="b" type="email">
  <label for="c">City</label><input id="c" name="c" type="text">
  <label for="d">Note</label><input id="d" name="d" type="text">
  <button id="go" type="submit">Send</button>
</form></body>
"""


class _Ctx:
    def __init__(self, bridge):
        self.context = _extlane.ExtensionContext(bridge)


class _Sess:
    _seq = 0

    def __init__(self, bridge):
        _Sess._seq += 1
        self.session_id = f"m{_Sess._seq}"
        self.spec = lanes.LaneSpec(lane="C", engine="extension", headless=False)
        self.element_map = anchors.ElementMap()
        self.reads = anchors.ReadStore()
        self.contexts = {"c1": _Ctx(bridge)}

    def bump(self, kind, page=None):
        pass

    def invalidate_page(self, handle, why):
        return None


class CountingBridge:
    """The real bridge, with a tally of what went over it.

    Wrapping rather than subclassing on purpose: what is being counted is the
    traffic the tools generate, and a wrapper that forwards every call is the
    version of that where nothing in the bridge had to be changed to be
    measured."""

    def __init__(self, inner):
        self._inner = inner
        self.counts: dict[str, int] = {}

    def request(self, method, params=None, timeout=20.0):
        self.counts[method] = self.counts.get(method, 0) + 1
        return self._inner.request(method, params, timeout)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def take(self) -> dict:
        counts, self.counts = self.counts, {}
        return counts


#: SLEEP BETWEEN ROUNDS, OUTSIDE THE CLOCK, and the reason is a phase 3
#: finding rather than a harness detail. The extension throttles at 40 burst
#: and 20 commands a second, which phase 2's loop never reached because a read
#: took 68 ms. A repeated read now costs about a sixth of that, so a tight
#: benchmark loop trips the browser-side rate limit and measures the throttle
#: instead of the tool. The pause holds the harness under the limit; nothing
#: about the limit is disabled, and it is left exactly as it is for every
#: caller who is not a stopwatch.
PACE_S = 0.16


def summarize(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "min_ms": round(ordered[0], 2),
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[min(len(ordered) - 1,
                                    int(len(ordered) * 0.95))], 2),
        "max_ms": round(ordered[-1], 2),
    }


async def timed(call, rounds: int, warmup: int = 3, reset=None):
    last = None
    for _ in range(warmup):
        if reset is not None:
            reset()
        last = await call()
    samples = []
    for _ in range(rounds):
        if reset is not None:
            reset()
        start = time.perf_counter()
        last = await call()
        samples.append((time.perf_counter() - start) * 1000.0)
    return summarize(samples), last


async def measure(bridge, pages, rounds: int) -> dict:
    findings: dict = {}
    sess = _Sess(bridge)

    def fresh():
        budgets.BOOK.drop(sess.session_id)
        time.sleep(PACE_S)

    page = _extlane.ExtensionPage(bridge, url=pages.url("/heavy"))
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    await extops.navigate(sess, record, url=pages.url("/heavy"))

    # The first read after a navigation, with the estimator already warm --
    # which is what production does now, because `_connect_extension` warms it
    # at session open. The cold number is measured in a subprocess below.
    fresh()
    await extops.navigate(sess, record, url=pages.url("/light"))
    fresh()
    await extops.navigate(sess, record, url=pages.url("/heavy"))
    firsts = []
    for _ in range(5):
        time.sleep(0.5)
        start = time.perf_counter()
        await extops.get_page_view(sess, record, budget_tokens=5000)
        firsts.append((time.perf_counter() - start) * 1000.0)
        fresh()
        await extops.navigate(sess, record, url=pages.url("/light"))
        fresh()
        await extops.navigate(sess, record, url=pages.url("/heavy"))
    findings["first_read_after_navigation"] = summarize(firsts)

    # ---------------------------------------------------------------- reads
    bridge.take()
    stats, payload = await timed(
        lambda: extops.get_page_view(sess, record, budget_tokens=5000),
        rounds, reset=fresh)
    findings["get_page_view_heavy"] = stats
    findings["get_page_view_heavy"]["budget_used"] = payload["budget"]["used"]
    findings["get_page_view_heavy"]["refs_minted"] = len(
        sess.element_map.entries)
    findings["get_page_view_heavy"]["wire_calls"] = bridge.take()
    findings["get_page_view_heavy"]["cache_hits"] = page.cache_hits
    findings["get_page_view_heavy"]["cache_misses"] = page.cache_misses

    # A REPEATED READ OF A PAGE NOBODY TOUCHED. The same tool, called twice in
    # a row on a document that did not move; the second call is the one the
    # unchanged path exists for.
    hits_before = page.cache_hits
    repeat = []
    await extops.get_page_view(sess, record, budget_tokens=5000)
    for _ in range(rounds):
        fresh()
        fresh()
        start = time.perf_counter()
        await extops.get_page_view(sess, record, budget_tokens=5000)
        repeat.append((time.perf_counter() - start) * 1000.0)
    findings["repeated_read_unchanged_page"] = summarize(repeat)
    findings["repeated_read_unchanged_page"]["cache_hits"] = (
        page.cache_hits - hits_before)

    await extops.navigate(sess, record, url=pages.url("/light"))
    fresh()
    stats, _ = await timed(
        lambda: extops.get_page_view(sess, record, budget_tokens=5000),
        rounds, reset=fresh)
    findings["get_page_view_light"] = stats

    # --------------------------------------------------- phase 1's big page
    fresh()
    await extops.navigate(sess, record, url=pages.url("/phase1"))
    bridge.take()
    hits_before = page.cache_hits
    stats, payload = await timed(
        lambda: extops.get_page_view(sess, record, budget_tokens=5000),
        rounds, reset=fresh)
    findings["get_page_view_228k"] = stats
    findings["get_page_view_228k"]["budget_used"] = payload["budget"]["used"]
    findings["get_page_view_228k"]["wire_calls"] = bridge.take()
    findings["get_page_view_228k"]["cache_hits"] = page.cache_hits - hits_before

    # --------------------------------------------------------------- acting
    fresh()
    await extops.navigate(sess, record, url=pages.url("/heavy"))
    await extops.get_page_view(sess, record, budget_tokens=5000)
    ref = next(r for r, e in sess.element_map.entries.items()
               if e.anchor.get("name") == "No-op")
    bridge.take()
    stats, _ = await timed(
        lambda: extops.click(sess, record, location={"ref": ref}), rounds,
        warmup=1, reset=fresh)
    findings["click"] = stats
    findings["click"]["wire_calls_total"] = bridge.take()
    findings["click"]["evaluates_per_click"] = round(
        findings["click"]["wire_calls_total"].get("page.evaluate", 0)
        / float(rounds + 1), 2)

    # ------------------------------------------------------------ fill_form
    #
    # A SESSION OF ITS OWN, because the element map is session-wide and the
    # heavy page carries a form with fields called Name and Email too. Picking
    # refs by label out of the shared map found the heavy page's fields and
    # asked the form page for them, which is a harness bug that looks exactly
    # like a product one.
    fresh()
    await extops.navigate(sess, record, url=pages.url("/form"))
    fsess = _Sess(bridge)
    frecord = _session.PageHandle(handle="p1", page=page, context="c1")

    def ffresh():
        budgets.BOOK.drop(fsess.session_id)
        time.sleep(PACE_S)

    await extops.get_page_view(fsess, frecord, budget_tokens=5000)
    by_name = {}
    for r, e in fsess.element_map.entries.items():
        name = e.anchor.get("name")
        if name in ("Name", "Email", "City", "Note"):
            by_name.setdefault(name, r)
    fields = [{"ref": by_name[n], "value": f"v-{n}"}
              for n in ("Name", "Email", "City", "Note") if n in by_name]
    findings["fill_form_fields"] = len(fields)
    if fields:
        bridge.take()
        rounds_ff = max(4, rounds // 3)
        stats, _ = await timed(
            lambda: extops.fill_form(fsess, frecord, fields=fields),
            rounds_ff, warmup=1, reset=ffresh)
        findings["fill_form_4_fields"] = stats
        calls = bridge.take()
        findings["fill_form_4_fields"]["wire_calls_total"] = calls
        findings["fill_form_4_fields"]["evaluates_per_call"] = round(
            calls.get("page.evaluate", 0) / float(rounds_ff + 1), 2)

    # ---------------------------------------------------------- other tools
    fresh()
    await extops.navigate(sess, record, url=pages.url("/heavy"))
    stats, _ = await timed(
        lambda: extops.navigate(sess, record, url=pages.url("/heavy")),
        max(4, rounds // 4), warmup=1, reset=fresh)
    findings["navigate_reload_same_url"] = stats

    stats, shot = await timed(
        lambda: extops.take_screenshot(sess, record), max(4, rounds // 4),
        warmup=1, reset=fresh)
    findings["take_screenshot"] = stats
    findings["take_screenshot"]["base64_chars"] = len(shot["base64"])

    def ping():
        return asyncio.to_thread(bridge.request, "bg.ping", None, 30.0)
    stats, _ = await timed(ping, rounds, reset=lambda: time.sleep(PACE_S))
    findings["bg_ping"] = stats

    stats, _ = await timed(lambda: page.stamp(), rounds,
                           reset=lambda: time.sleep(PACE_S))
    findings["page_stamp"] = stats
    return findings


def build_pages() -> PageServer:
    return PageServer({
        "/heavy": heavy_page(),
        "/light": LIGHT_PAGE,
        "/form": FORM_PAGE,
        "/phase1": phase1_heavy_page(),
    })


async def cold_first_read(bridge, pages) -> dict:
    """The first read of a fresh PROCESS, which is the number phase 2 quoted.

    Run under `--cold`, which does one read and exits, because the cost being
    measured is paid once per process and nothing can see it twice."""
    sess = _Sess(bridge)
    page = _extlane.ExtensionPage(bridge, url=pages.url("/heavy"))
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    await extops.navigate(sess, record, url=pages.url("/heavy"))
    out = {}
    if "--warm-estimator" in sys.argv:
        start = time.perf_counter()
        _meter.warm()
        out["estimator_warm_ms"] = round((time.perf_counter() - start) * 1000, 2)
    start = time.perf_counter()
    await extops.get_page_view(sess, record, budget_tokens=5000)
    out["cold_first_read_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--cold", action="store_true")
    parser.add_argument("--warm-estimator", action="store_true")
    args = parser.parse_args()

    if not find_firefox():
        print("no Firefox on this machine", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="ks4web-phase3-"))
    endpoint = workdir / "endpoint.json"
    bridge = CountingBridge(Bridge(endpoint_path=endpoint))
    pages = build_pages()
    browser = None
    rdp = None
    before_grade = readonly.grade()
    readonly.apply(False)
    consent.apply("full")
    try:
        register.install(workdir / "nativehost",
                         python_executable=sys.executable,
                         src_dir=ROOT / "src", endpoint=endpoint)
        port = free_port()
        browser = HeadlessFirefox(workdir / "browser",
                                  url=pages.url("/light"), debugger_port=port)
        rdp = RDPClient(port)
        rdp.install_temporary_addon(ROOT / "extension")
        if not bridge.wait_for_browser(60.0):
            print("the extension never connected", file=sys.stderr)
            return 3
        bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if "Light" in bridge.request("page.read", timeout=30.0).get(
                    "text", ""):
                break
            time.sleep(0.25)
        if args.cold:
            findings = asyncio.run(cold_first_read(bridge, pages))
        else:
            findings = asyncio.run(measure(bridge, pages, args.rounds))
    finally:
        for shutdown in (lambda: rdp and rdp.close(),
                         lambda: browser and browser.kill(),
                         pages.close, bridge.close):
            try:
                shutdown()
            except Exception:  # noqa: BLE001
                pass
        register.unregister_windows()
        readonly.apply(False if before_grade is None else before_grade)
        consent.apply(None)

    text = json.dumps(findings, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
