"""Measure every number the README publishes, and print them as a fill table.

The README carries no hand-written figures. Each `{PLACEHOLDER}` in the copy
source is filled from a row this script prints, so a reader can re-run it and
compare, and so a figure that moves is caught by re-running rather than by
somebody remembering.

Three groups, measured three different ways and never mixed in one table:

- **Page reads** (`{RAW_DUMP_TOKENS}`, `{PROJECTION_TOKENS}`, `{DELTA_TOKENS}`)
  use tiktoken on `o200k_base`, the convention DESIGN 3.4 fixes and the meter
  enforces. They run against the FROZEN corpus over localhost with every
  off-origin request aborted, so the numbers re-derive after the live pages
  change.
- **Tool surface** (`{LITE_TOOL_COUNT}`, `{LITE_SURFACE_TOKENS}`,
  `{FULL_SURFACE_TOKENS}`) comes from the LIVE FastMCP registry under each
  launch shape, through the same chars/4 estimator `scripts/measure_surface.py`
  uses. It is a schema estimate, not a tiktoken count, and the two are never
  added together.
- **Repo facts** (`{RUNG_COUNT}`, `{TEST_COUNT}`, `{BROWSER_TEST_COUNT}`) are
  counted out of the code and out of pytest's own collection.

**What the raw-dump number means, stated so it can be argued with.** Three
flavors of "just give me the page" are measured: the visible text, the
serialized DOM, and a flat role-and-name listing of every element, which is
the shape snapshot-based browser tools emit. The published figure is the
CHEAPEST of the three, so the comparison understates the gap rather than
flattering it. All three are printed.

Run:  .venv/Scripts/python.exe -X utf8 tools/measure_readme_numbers.py
      .venv/Scripts/python.exe -X utf8 tools/measure_readme_numbers.py --json
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import re
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web import packs, projection, server  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402
from kitchensink4web.ops import lite  # noqa: E402

#: The flagship page, and the one DESIGN 3.2 sets its published target
#: against. Frozen in corpus A, so this is reproducible.
DEMO_FILE = "wikipedia_versailles"
DEMO_PAGE_NAME = "the Treaty of Versailles article on Wikipedia"

#: The delta read is measured here because a delta after a click needs a page
#: that actually changes when clicked, and every page in corpus A has its
#: scripts stripped by the freeze. This fixture's "Account" control opens a
#: portal dropdown: three new affordances appear, the URL does not move, and
#: the rest of the page holds still, which is the ordinary case.
DELTA_FILE = "pathological"

#: The default a caller gets when they pass no budget.
DEFAULT_BUDGET = 5000

#: Every element, as a role-and-name line. This is the shape a snapshot-based
#: browser tool hands back, approximated closely enough to be a fair floor:
#: no refs, no attributes, no nesting indentation, all of which cost more.
FLAT_DUMP_JS = """() => {
  const out = [];
  const els = document.querySelectorAll('*');
  for (const el of els) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'script' || tag === 'style' || tag === 'noscript') continue;
    const role = el.getAttribute('role') || tag;
    let name = el.getAttribute('aria-label') || '';
    if (!name) {
      for (const node of el.childNodes) {
        if (node.nodeType === 3) name += node.nodeValue;
      }
    }
    name = name.replace(/\\s+/g, ' ').trim();
    out.push(name ? role + ' "' + name + '"' : role);
  }
  return out.join('\\n');
}"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102, ANN002
        pass


def _serve(directory: Path) -> tuple[int, socketserver.TCPServer]:
    handler = functools.partial(_Quiet, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1], httpd


def _fmt_k(n: int) -> str:
    """A published token figure, to one decimal of a thousand."""
    return f"{n / 1000:.1f}k"


def _ntok(text: str) -> int:
    return projection.ntok(text)


async def _page_numbers() -> dict:
    """Every page-read figure, taken from the SHIPPED tools.

    The reads go through `get_page_view` rather than through the projection
    module underneath it, because the published number is what a caller pays
    and the tool is the thing that decides that.
    """
    a_port, a_httpd = _serve(ROOT / "corpus" / "a")
    b_port, b_httpd = _serve(ROOT / "corpus" / "b")
    server.configure(read_only=False)          # the click needs the tool
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    out: dict = {}
    try:
        handle = session.focused
        record = session.page(handle)
        await record.page.route(
            "**/*",
            lambda route: asyncio.ensure_future(
                route.continue_() if "127.0.0.1" in route.request.url
                else route.abort()))

        # ---- the cheap first read, and the three raw dumps it replaces ----
        url = f"http://127.0.0.1:{a_port}/{DEMO_FILE}.html"
        await lite.navigate(page=handle, url=url, timeout_ms=60000)
        view = await lite.get_page_view(page=handle,
                                        budget_tokens=DEFAULT_BUDGET)

        dumps = {
            "visible_text": _ntok(
                await record.page.evaluate("() => document.body.innerText")),
            "serialized_dom": _ntok(await record.page.evaluate(
                "() => document.documentElement.outerHTML")),
            "flat_role_and_name": _ntok(
                await record.page.evaluate(FLAT_DUMP_JS)),
        }
        out["demo"] = {
            "page": DEMO_PAGE_NAME,
            "file": DEMO_FILE,
            "budget": DEFAULT_BUDGET,
            "projection_tokens": view["budget"]["used"],
            "projection_rung": view["budget"]["rung"],
            "raw_dumps": dumps,
            "raw_dump_published": min(dumps.values()),
            "raw_dump_published_flavor": min(dumps, key=dumps.get),
        }

        # ---- the delta read, after one real click ----
        url = f"http://127.0.0.1:{b_port}/{DELTA_FILE}.html"
        await lite.navigate(page=handle, url=url, timeout_ms=60000)
        await record.page.wait_for_selector("button", timeout=30000)
        first = await lite.get_page_view(page=handle,
                                         budget_tokens=DEFAULT_BUDGET)
        # Not a form's Save button (a submit is confirmation-gated and would
        # need a human here) and not a route link (a client-side navigation
        # makes the delta fall back to a full read, which would publish a
        # number that is not a delta at all).
        await lite.find_and_act(page=handle, query="Account", role="button",
                                action="click")
        await record.page.wait_for_timeout(250)
        after = await lite.get_page_view(page=handle,
                                         budget_tokens=DEFAULT_BUDGET,
                                         since=first["read_token"])
        out["delta"] = {
            "file": DELTA_FILE,
            "first_read_tokens": first["budget"]["used"],
            "delta_tokens": after["budget"]["used"],
            "fell_back_to_full_read": after.get("delta", {}).get(
                "fell_back_to_full_read", False),
        }
    finally:
        await MANAGER.close(session.session_id)
        a_httpd.shutdown()
        b_httpd.shutdown()
    return out


def _surface_numbers() -> dict:
    def _shape(**kw) -> dict:
        server.configure(**kw)
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        return {"tools": len(tools),
                "tokens": sum(packs.approx_tokens(t) for t in tools.values())}

    lite = _shape(read_only=False)
    full = _shape(mode="full", read_only=False)
    lite_default = _shape()
    server.configure(read_only=False)
    return {"lite_acting": lite, "full_acting": full,
            "lite_shipped_default": lite_default}


def _test_counts() -> dict:
    """pytest's own collection, per directory. Counted, never estimated."""
    counts = {}
    for name in ("unit", "browser"):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "pytest",
             f"tests/{name}", "--collect-only", "-q"],
            cwd=str(ROOT), capture_output=True, text=True)
        match = re.search(r"(\d+) tests? collected", proc.stdout)
        counts[name] = int(match.group(1)) if match else None
    if counts["unit"] and counts["browser"]:
        counts["total"] = counts["unit"] + counts["browser"]
    return counts


def main() -> None:
    page = asyncio.run(_page_numbers())
    surface = _surface_numbers()
    tests = _test_counts()
    demo, delta = page["demo"], page["delta"]

    payload = {
        "DEMO_PAGE_NAME": demo["page"],
        "RAW_DUMP_TOKENS": f'{demo["raw_dump_published"]:,}',
        "PROJECTION_TOKENS": f'{demo["projection_tokens"]:,}',
        "DELTA_TOKENS": f'{delta["delta_tokens"]:,}',
        "LITE_TOOL_COUNT": surface["lite_acting"]["tools"],
        "LITE_SURFACE_TOKENS": _fmt_k(surface["lite_acting"]["tokens"]),
        "FULL_SURFACE_TOKENS": _fmt_k(surface["full_acting"]["tokens"]),
        "RUNG_COUNT": len(projection.RUNGS),
        "TEST_COUNT": tests.get("total"),
        "BROWSER_TEST_COUNT": tests.get("browser"),
    }

    if "--json" in sys.argv:
        print(json.dumps({"fill": payload, "detail": {
            "page": page, "surface": surface, "tests": tests}},
            indent=1, sort_keys=True))
        return

    print("\nREADME fill table")
    print("-" * 60)
    for key, value in payload.items():
        print(f"{key:<22} {value}")

    print("\nraw-dump flavors on the demo page (o200k_base)")
    print("-" * 60)
    for flavor, cost in sorted(demo["raw_dumps"].items(),
                               key=lambda kv: kv[1]):
        mark = " <- published (cheapest)" \
            if flavor == demo["raw_dump_published_flavor"] else ""
        print(f"{flavor:<22} {cost:>9,}{mark}")
    print(f'{"projection":<22} {demo["projection_tokens"]:>9,} '
          f'(rung {demo["projection_rung"]}, budget {demo["budget"]})')
    print(f'{"delta after one click":<22} {delta["delta_tokens"]:>9,} '
          f'(first read {delta["first_read_tokens"]:,} on '
          f'{delta["file"]}.html, fell back to a full read: '
          f'{delta["fell_back_to_full_read"]})')

    print("\ntool surface (chars/4 schema estimate, NOT tiktoken)")
    print("-" * 60)
    for label, row in surface.items():
        print(f'{label:<22} {row["tools"]:>3} tools  {_fmt_k(row["tokens"]):>7}')

    print("\ntests collected")
    print("-" * 60)
    for label, count in tests.items():
        print(f"{label:<22} {count}")


if __name__ == "__main__":
    main()
