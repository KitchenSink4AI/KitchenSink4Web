"""The page-read figures the product publishes, measured against a real read.

The guard these replace compared the published prose to
`tools/readme_numbers_snapshot.json`, a file written by the same script that
stamps the prose. One edit moved both sides at once, so a figure that went
stale in the product went stale in its own guard at the same moment. V-21
found one instance of that (the tool counts) and fixed it by asking the live
process. The page reads are asked live here, on the frozen corpus, with every
off-origin request aborted: the same setup, and the same two servers, that
`tools/measure_readme_numbers.py` publishes from.

Three figures, checked where each surface states them:

  the dump figure   the cheapest of three "just give me the page" flavors on
                    the demo article. The published number is the floor of
                    the comparison, so this asserts it IS the cheapest of the
                    three and not one of the others. All three are pinned,
                    because `llms.txt` prints all three.
  the first read    what `get_page_view` charges for the same page at the
                    default budget.
  the delta         what a second read costs after one real click.

TOKEN_SLACK, and why an exact match would be wrong here. The page's own URL
rides inside the projection, so the loopback port the fixture server happens
to get changes the count by a token or two between runs. The publishing
script has the same exposure. The slack is far below any restamp this guard
exists to catch: the stale figure it was written against sat 189 tokens off.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import re
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import projection
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import lite
from kitchensink4web.policy import audit, budgets, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]

#: The flagship page and the delta page, each served from its own corpus
#: directory exactly as the publishing script serves them. The served
#: directory is part of the measurement: a page reached at `/a/page.html`
#: costs a few tokens more than the same page at `/page.html`.
DEMO = "wikipedia_versailles.html"
DELTA = "pathological.html"

#: The default a caller gets when they pass no budget.
DEFAULT_BUDGET = 5000

#: The loopback-URL allowance, in tokens. See the module docstring.
TOKEN_SLACK = 10

#: Every element as a role-and-name line: the shape a snapshot-based browser
#: tool hands back, approximated closely enough to be a fair floor.
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
    def log_message(self, *args):
        pass


def _serve(directory: Path):
    handler = functools.partial(_Quiet, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture(scope="module")
def demo_site():
    httpd, base = _serve(ROOT / "corpus" / "a")
    yield base
    httpd.shutdown()


@pytest.fixture(scope="module")
def delta_site():
    httpd, base = _serve(ROOT / "corpus" / "b")
    yield base
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    readonly.apply(False)
    yield
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


async def _open(site, path):
    """A session on one corpus page, with the frozen page held frozen: every
    request that is not loopback is aborted, so nothing here reaches the
    network and a figure cannot move because a CDN did."""
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    handle = session.focused
    record = session.page(handle)
    await record.page.route(
        "**/*",
        lambda route: asyncio.ensure_future(
            route.continue_() if "127.0.0.1" in route.request.url
            else route.abort()))
    await lite.navigate(page=handle, url=f"{site}/{path}", timeout_ms=60000)
    return session, handle, record


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _stated(rel: str, pattern: str, label: str) -> int:
    found = re.search(pattern, _text(rel))
    assert found, f"{rel} no longer states the {label} where expected"
    return int(found.group(1).replace(",", ""))


def _pin(sites: dict[str, str], measured: int, label: str) -> None:
    """Each surface's own words for one figure, against the measurement."""
    for rel, pattern in sites.items():
        claimed = _stated(rel, pattern, label)
        assert abs(claimed - measured) <= TOKEN_SLACK, (
            f"{rel} publishes {claimed:,} for the {label} and a live read "
            f"measures {measured:,}. Re-run "
            f"tools/measure_readme_numbers.py and restamp.")


def test_the_published_dump_figure_is_the_cheapest_measured_dump(demo_site):
    """Three flavors of "just give me the page", and the published number is
    the smallest of them: the comparison understates the gap rather than
    flattering it, and this is where that stays true."""
    async def measure():
        session, _handle, record = await _open(demo_site, DEMO)
        try:
            return {
                "visible_text": projection.ntok(
                    await record.page.evaluate(
                        "() => document.body.innerText")),
                "serialized_dom": projection.ntok(
                    await record.page.evaluate(
                        "() => document.documentElement.outerHTML")),
                "flat_role_and_name": projection.ntok(
                    await record.page.evaluate(FLAT_DUMP_JS)),
            }
        finally:
            await MANAGER.close(session.session_id)

    dumps = run(measure())
    cheapest = min(dumps.values())
    assert min(dumps, key=dumps.get) == "visible_text", (
        f"the published dump figure is the visible-text flavor and it is no "
        f"longer the cheapest of the three: {dumps}")
    _pin({
        "README.md": r"costs\s+([\d,]+) tokens of your assistant's memory",
        "docs/llms.txt": r"dumped as visible text costs ([\d,]+)",
        "docs/index.html": r'<span class="fig">([\d,]+)</span>',
    }, cheapest, "dump figure")

    # `llms.txt` prints the other two flavors beside it, so they are pinned
    # too: an unchecked figure on a published surface is a figure that goes
    # stale quietly, which is the whole failure this file exists to end.
    _pin({"docs/llms.txt": r"flat role-and-name listing ([\d,]+)"},
         dumps["flat_role_and_name"], "flat dump figure")
    _pin({"docs/llms.txt": r"as serialized DOM ([\d,]+)"},
         dumps["serialized_dom"], "serialized-DOM dump figure")


def test_the_published_first_read_is_what_the_page_view_charges(demo_site):
    """The front-page number, taken from the shipped tool at the default
    budget rather than from the projection module underneath it: the
    published figure is what a caller pays, and the tool is the thing that
    decides that."""
    async def measure():
        session, handle, _record = await _open(demo_site, DEMO)
        try:
            view = await lite.get_page_view(page=handle,
                                            budget_tokens=DEFAULT_BUDGET)
            return view["budget"]["used"]
        finally:
            await MANAGER.close(session.session_id)

    used = run(measure())
    _pin({
        "README.md": r"first read of it costs ([\d,]+)",
        "docs/llms.txt": r"it costs ([\d,]+) tokens at the",
        "docs/index.html": r'<span class="fig" id="mapFig">([\d,]+)</span>',
    }, used, "first read")
    _pin({"README.md":
          r"\| First read of the Treaty of Versailles article on Wikipedia "
          r"\| ([\d,]+) \|"}, used, "first read")
    # The demo's own script counts down from the same figure the tile above
    # it prints, so the animation cannot open on a number the page has
    # already stopped publishing.
    _pin({"docs/index.html": r"var BASE = (\d+);"}, used, "first read")


def test_the_published_delta_is_what_a_second_read_charges(delta_site):
    """One real click, then a read that asks only for what moved."""
    async def measure():
        session, handle, record = await _open(delta_site, DELTA)
        try:
            await record.page.wait_for_selector("button", timeout=30000)
            first = await lite.get_page_view(page=handle,
                                             budget_tokens=DEFAULT_BUDGET)
            await lite.find_and_act(page=handle, query="Account",
                                    role="button", action="click")
            await record.page.wait_for_timeout(250)
            after = await lite.get_page_view(page=handle,
                                             budget_tokens=DEFAULT_BUDGET,
                                             since=first["read_token"])
            return first["budget"]["used"], after
        finally:
            await MANAGER.close(session.session_id)

    first_used, after = run(measure())
    assert not after.get("delta", {}).get("fell_back_to_full_read", False), \
        "the delta read fell back to a full read, so it is not a delta"
    _pin({
        "README.md": r"\| Delta read after one click \| ([\d,]+) \|",
        "docs/llms.txt": r"Measured at ([\d,]+) tokens after one click",
    }, after["budget"]["used"], "delta read")
    _pin({"docs/llms.txt": r"whose first read cost\s+([\d,]+)"},
         first_used, "delta page's first read")
