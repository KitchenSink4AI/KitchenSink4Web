"""Measure the Phase 2 tools against a real page, through the real lane.

Phase 1 measured the PIPE: a ping and an `innerText` read. Phase 2's numbers
have to be about the tools a caller actually uses, which means the whole
projection running in the page and the whole policy ladder running in Python,
because that is what a `get_page_view` costs on this lane.

Everything runs hidden: `-headless`, `CREATE_NO_WINDOW`, stdin at DEVNULL, a
scratch profile in the scratchpad, and a kill that names its own process
tree. Nothing appears on the desk.

    python scripts/ext_phase2_measure.py --json out.json
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
from tests.fixtures.firefox_harness import (                       # noqa: E402
    HeadlessFirefox, PageServer, RDPClient, find_firefox, free_port)

#: A page with real structure on it, so the extractor has work to do. Two
#: hundred links, a nav, a form, a table: the shape of an ordinary content
#: page rather than a synthetic one with a single button.
def heavy_page(links: int = 200, paragraphs: int = 60) -> str:
    nav = "".join(
        f'<li><a href="/x{i}">Section {i}</a></li>' for i in range(20))
    body = "".join(
        f"<h2>Heading {i}</h2><p>{'Ordinary prose about the subject. ' * 12}"
        f'<a href="/deep{i}">read more {i}</a></p>' for i in range(paragraphs))
    rest = "".join(f'<a href="/l{i}">link {i}</a> ' for i in range(links))
    rows = "".join(
        f"<tr><td>row {i}</td><td>{i * 7}</td><td>value {i}</td></tr>"
        for i in range(40))
    return f"""<!doctype html>
<title>KS4Web phase 2 measurement page</title>
<body>
  <nav><ul>{nav}</ul></nav>
  <main>
    <h1>Measurement</h1>
    <button id="noop" type="button">No-op</button>
    {body}
    <form method="post" action="/submit">
      <label for="a">Name</label><input id="a" name="a" type="text">
      <label for="b">Email</label><input id="b" name="b" type="email">
      <button id="go" type="submit">Send</button>
    </form>
    <table><tbody>{rows}</tbody></table>
    <p>{rest}</p>
  </main>
</body>
"""

LIGHT_PAGE = """<!doctype html>
<title>KS4Web phase 2 light page</title>
<body><h1>Light</h1><p>One heading, one paragraph, one link.</p>
<a id="only" href="/other">Only link</a></body>
"""


class _Ctx:
    def __init__(self, bridge):
        self.context = _extlane.ExtensionContext(bridge)


class _Sess:
    _seq = 0

    def __init__(self, bridge):
        _Sess._seq += 1
        self.session_id = f"m{_Sess._seq}"
        self.spec = lanes.LaneSpec(lane="C", engine="extension",
                                   headless=False)
        self.element_map = anchors.ElementMap()
        self.reads = anchors.ReadStore()
        self.contexts = {"c1": _Ctx(bridge)}

    def bump(self, kind, page=None):
        pass

    def invalidate_page(self, handle, why):
        return None


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


async def timed(call, rounds: int, warmup: int = 3,
                reset=None) -> tuple[dict, object]:
    """Time one call, `rounds` times, with the clock around the call only.

    `reset` runs BEFORE the clock starts on every round and exists for one
    reason: the loop detector is a product feature and it is right to fire
    on fifteen identical calls in a row. Nothing about it is being disabled
    here; the ledger is cleared between rounds so that what is being timed
    is the tool rather than the detector, and the detector is left exactly
    as it is for every caller who is not a stopwatch.
    """
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

    page = _extlane.ExtensionPage(bridge, url=pages.url("/heavy"))
    record = _session.PageHandle(handle="p1", page=page, context="c1")

    await extops.navigate(sess, record, url=pages.url("/heavy"))

    # The FIRST read on a fresh document pays the bundle injection; every
    # read after it does not. Both numbers matter and they are different
    # questions, so they are measured separately rather than averaged.
    await extops.navigate(sess, record, url=pages.url("/light"))
    await extops.navigate(sess, record, url=pages.url("/heavy"))
    start = time.perf_counter()
    await extops.get_page_view(sess, record, budget_tokens=5000)
    findings["first_read_after_navigation_ms"] = round(
        (time.perf_counter() - start) * 1000.0, 2)

    stats, payload = await timed(
        lambda: extops.get_page_view(sess, record, budget_tokens=5000),
        rounds, reset=fresh)
    findings["get_page_view_heavy"] = stats
    findings["get_page_view_heavy"]["budget_used"] = payload["budget"]["used"]
    findings["get_page_view_heavy"]["refs_minted"] = len(
        sess.element_map.entries)

    await extops.navigate(sess, record, url=pages.url("/light"))
    stats, _ = await timed(
        lambda: extops.get_page_view(sess, record, budget_tokens=5000),
        rounds, reset=fresh)
    findings["get_page_view_light"] = stats

    await extops.navigate(sess, record, url=pages.url("/heavy"))
    await extops.get_page_view(sess, record, budget_tokens=5000)
    # A BUTTON THAT DOES NOTHING is the honest thing to time. Clicking a
    # link would navigate, so every round after the first would be timing a
    # click on whatever page the previous round landed on, which is a
    # different measurement each time and not the one the number claims.
    ref = next(r for r, e in sess.element_map.entries.items()
               if e.anchor.get("name") == "No-op")
    stats, _ = await timed(
        lambda: extops.click(sess, record, location={"ref": ref}), rounds,
        warmup=1, reset=fresh)
    findings["click"] = stats

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
    findings["take_screenshot"]["masked_fields"] = shot["masked_fields"]

    # The wire, for comparison against Phase 1's own numbers on the same
    # machine. A regression here would be the pipe rather than the tools.
    def ping():
        return asyncio.to_thread(bridge.request, "bg.ping", None, 30.0)
    stats, _ = await timed(ping, rounds)
    findings["bg_ping"] = stats

    findings["session_ids_used"] = _Sess._seq
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--rounds", type=int, default=15)
    args = parser.parse_args()

    if not find_firefox():
        print("no Firefox on this machine", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="ks4web-phase2-"))
    endpoint = workdir / "endpoint.json"
    bridge = Bridge(endpoint_path=endpoint)
    pages = PageServer({"/heavy": heavy_page(), "/light": LIGHT_PAGE})
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
        budgets.BOOK._ledgers.clear() if hasattr(budgets.BOOK, "_ledgers") \
            else None

    text = json.dumps(findings, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
