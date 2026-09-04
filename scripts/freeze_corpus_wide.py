"""Freeze the WIDENED benchmark set: the five page shapes PLAN 1.3 adds in
Phase 2, captured once and committed alongside corpus A.

Corpus A is four pages of one shape family: two encyclopedia articles, one
bare form, one scaffold. That set proved the projection on prose and on a
wide table and it cannot say anything about the shapes the product will
actually be pointed at. This corpus adds them:

    github_repo     an app shell whose navigation bar is the whole point
    ant_design      a heavy client-rendered SPA
    playwright_docs a documentation site
    ecommerce       a product page with a buy affordance
    github_login    a login page, where credential blindness has to hold

**The GitHub repo page is the one that gates.** The Phase 2 gate requires
every tab in the repository navigation bar to appear in the projection, which
is the failure that made affordance ranking quota-based in the first place, so
this script checks for the tab strip at capture time and records what it found
rather than trusting that a 200 means the page is usable.

Capture semantics are IDENTICAL to `freeze_corpus_a.py`, deliberately, so the
two corpora are comparable and one reading of "frozen" covers both: post-load
`outerHTML`, every stylesheet inlined in document order through the browser's
own request context, every `<script>` and `<noscript>` stripped, no `<base>`
tag injected, sha256 per file, fetch DTG in KST.

One thing corpus A never had to face: these pages can refuse. A bot wall, a
consent interstitial, or a timeout is a real outcome and it goes in the
manifest as `"captured": false` with the observed failure. Nothing here is
faked and nothing is silently substituted. The e-commerce slot is the one
place a substitution is allowed, because no single product URL is stable
enough to hard-code, and the manifest records WHICH candidate answered and
which ones were tried and refused.

Run:  .venv/Scripts/python.exe -X utf8 scripts/freeze_corpus_wide.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web.engine.session import MANAGER  # noqa: E402

OUT = ROOT / "corpus" / "wide"

#: Each slot is a list of candidates tried in order. Every slot but the
#: e-commerce one has exactly one candidate, because PLAN 1.3 names the URL;
#: the product page does not have a named URL and no product URL survives
#: forever, so that slot carries fallbacks and the manifest records the winner.
PAGES: dict[str, dict] = {
    "github_repo": {
        "why": "app shell; the repository nav bar must survive ranking",
        "attempts": 3,
        "candidates": ["https://github.com/microsoft/playwright"],
    },
    "ant_design": {
        "why": "heavy client-rendered SPA",
        "attempts": 2,
        "candidates": ["https://ant.design/components/overview"],
    },
    "playwright_docs": {
        "why": "documentation site",
        "attempts": 2,
        "candidates": ["https://playwright.dev/python/docs/intro"],
    },
    "ecommerce": {
        "why": "product page with a buy affordance, no login required",
        "attempts": 2,
        "candidates": [
            # A real store first. If any of these bot-wall, the last
            # candidate is a purpose-built public scraping sandbox that has
            # been stable for years, which is a weaker fixture but an honest
            # one, and the manifest says which was used.
            "https://www.apple.com/shop/buy-mac/macbook-air",
            "https://www.gap.com/browse/product.do?pid=440793002",
            "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/"
            "index.html",
        ],
    },
    "github_login": {
        "why": "login page; credential blindness has to hold here",
        "attempts": 2,
        "candidates": ["https://github.com/login"],
    },
}

#: Read before the scripts are stripped: the stylesheet inventory, the node
#: count, and the two structural probes the Phase 2 gate cares about (the
#: repository tab strip, and whether any password field is present).
CAPTURE_JS = """
(() => {
  const sheets = [];
  for (const node of document.querySelectorAll('link[rel~="stylesheet"], style')) {
    if (node.tagName === 'STYLE') {
      sheets.push({kind: 'inline', text: node.textContent || ''});
    } else if (node.href) {
      sheets.push({kind: 'link', href: node.href, media: node.media || ''});
    }
  }
  // The repository navigation bar, probed by the shapes GitHub actually
  // ships it in rather than by one brittle selector.
  const tabs = [];
  const seen = new Set();
  const sel = 'nav[aria-label*="Repository" i] a, [role="tablist"] a, ' +
              '.UnderlineNav-item, [data-tab-item]';
  for (const a of document.querySelectorAll(sel)) {
    const t = (a.textContent || '').replace(/\\s+/g, ' ').trim();
    if (t && t.length < 40 && !seen.has(t)) { seen.add(t); tabs.push(t); }
  }
  return {
    sheets,
    url: location.href,
    title: document.title,
    nodes: document.getElementsByTagName('*').length,
    text_chars: (document.body ? (document.body.innerText || '') : '').length,
    nav_tabs: tabs,
    password_fields: document.querySelectorAll('input[type=password]').length,
    forms: document.querySelectorAll('form').length,
    iframes: document.querySelectorAll('iframe').length,
  };
})()
"""

_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
_SCRIPT_EMPTY = re.compile(r"<script\b[^>]*/?>", re.I)
_LINK_SHEET = re.compile(
    r"<link\b[^>]*\brel\s*=\s*[\"']?[^\"'>]*stylesheet[^\"'>]*[\"']?[^>]*>",
    re.I)
_NOSCRIPT = re.compile(r"<noscript\b[^>]*>.*?</noscript\s*>", re.I | re.S)

#: A page that answered with a bot wall is not a captured page. These are the
#: strings the walls actually print; a hit does not abort the capture, it gets
#: recorded next to it so a reader can see why a number looks wrong.
WALL_MARKERS = (
    "verify you are human", "checking your browser", "enable javascript and "
    "cookies", "access denied", "request unsuccessful", "unusual traffic",
    "are you a robot", "captcha",
)


def _kst() -> str:
    out = subprocess.run(["date", "+%Y-%m-%d %H:%M"], capture_output=True,
                         text=True, shell=False)
    return out.stdout.strip() if out.returncode == 0 else ""


async def _sheet_text(context, sheet: dict) -> str:
    if sheet["kind"] == "inline":
        return sheet["text"]
    try:
        response = await context.request.get(sheet["href"], timeout=30000)
        if not response.ok:
            return f"/* unavailable: {sheet['href']} ({response.status}) */"
        return await response.text()
    except Exception as exc:  # noqa: BLE001
        return f"/* unavailable: {sheet['href']} ({exc.__class__.__name__}) */"


def _freeze_html(html: str, style_block: str) -> str:
    """Strip behaviour, inline appearance, leave structure alone."""
    html = _SCRIPT.sub("", html)
    html = _SCRIPT_EMPTY.sub("", html)
    # noscript content becomes visible once scripts are gone, which would ADD
    # affordances the live page never showed. Drop it with the scripts.
    html = _NOSCRIPT.sub("", html)
    html = _LINK_SHEET.sub("", html)
    marker = "</head>"
    at = html.lower().find(marker)
    block = f"<style data-ks4web-frozen>\n{style_block}\n</style>\n"
    if at == -1:
        return block + html
    return html[:at] + block + html[at:]


async def _capture_once(page, url: str) -> dict:
    """One attempt. Returns the frozen html plus what the probe saw."""
    response = await page.goto(url, wait_until="load", timeout=60000)
    status = response.status if response is not None else None
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:  # noqa: BLE001
        pass
    info = await page.evaluate(CAPTURE_JS)
    texts = []
    for sheet in info["sheets"]:
        text = await _sheet_text(page.context, sheet)
        media = sheet.get("media") or ""
        if media and media not in ("all", "screen"):
            text = f"@media {media} {{\n{text}\n}}"
        texts.append(text)
    html = await page.evaluate("document.documentElement.outerHTML")
    html = "<!doctype html>\n" + _freeze_html(html, "\n".join(texts))
    low = html[:400000].lower()
    walls = [m for m in WALL_MARKERS if m in low]
    return {"html": html, "info": info, "status": status, "walls": walls}


async def _capture_slot(page, name: str, spec: dict) -> dict:
    """Work the candidate list, retrying each per the slot's attempt budget."""
    tried: list[dict] = []
    for url in spec["candidates"]:
        for attempt in range(1, spec["attempts"] + 1):
            try:
                got = await _capture_once(page, url)
            except Exception as exc:  # noqa: BLE001
                tried.append({"url": url, "attempt": attempt,
                              "failure": f"{exc.__class__.__name__}: "
                                         f"{str(exc)[:200]}"})
                print(f"  {name}: attempt {attempt} on {url} failed "
                      f"({exc.__class__.__name__})")
                continue
            info = got["info"]
            # A 200 that carries a bot wall and almost no text is a refusal
            # wearing a success code. Retry it; report it if it never clears.
            thin = info["text_chars"] < 500
            if got["walls"] and thin and attempt < spec["attempts"]:
                tried.append({"url": url, "attempt": attempt,
                              "failure": f"bot wall markers {got['walls']}, "
                                         f"{info['text_chars']} text chars"})
                print(f"  {name}: attempt {attempt} on {url} hit a wall "
                      f"{got['walls']}")
                continue
            got["url"] = url
            got["tried"] = tried
            got["attempt"] = attempt
            return got
    return {"html": None, "tried": tried}


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = _kst()
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    manifest = {
        "corpus": "wide",
        "purpose": "the widened benchmark set PLAN 1.3 adds in Phase 2: a "
                   "GitHub repo page, a heavy SPA, a documentation site, an "
                   "e-commerce product page, and a login page",
        "fetched_kst": fetched,
        "lane": "A(chromium) headless, bundled Chromium",
        "capture": {
            "dom": "post-load document.documentElement.outerHTML",
            "styles": "inlined in document order, external sheets fetched "
                      "through the browser request context",
            "stripped": "script, noscript, link[rel~=stylesheet]",
            "base_tag": "none, deliberately: hrefs stay as the live page "
                        "wrote them so origin matching is unchanged",
            "identical_to": "scripts/freeze_corpus_a.py, so corpus A and "
                            "corpus wide are directly comparable",
        },
        "gate_note": "PLAN 1.3 / Phase 2: every tab in the GitHub repository "
                     "navigation bar must appear in the projection. "
                     "nav_tabs_at_capture is the list the frozen page "
                     "actually carries; a projection that prints fewer is a "
                     "gate failure, and a capture that carries none is a "
                     "corpus failure and has to be refrozen.",
        "pages": {},
    }
    try:
        record = session.page(session.focused)
        page = record.page
        for name, spec in PAGES.items():
            print(f"{name}:")
            got = await _capture_slot(page, name, spec)
            if got["html"] is None:
                manifest["pages"][name] = {
                    "captured": False,
                    "why": spec["why"],
                    "candidates": spec["candidates"],
                    "attempts": got["tried"],
                    "observed_failure": (got["tried"][-1]["failure"]
                                         if got["tried"] else "no attempt"),
                }
                print(f"  {name}: NOT CAPTURED")
                continue
            info = got["info"]
            html = got["html"]
            path = OUT / f"{name}.html"
            path.write_text(html, encoding="utf-8")
            entry = {
                "captured": True,
                "why": spec["why"],
                "url": got["url"],
                "final_url": info["url"],
                "http_status": got["status"],
                "title": info["title"],
                "attempt": got["attempt"],
                "earlier_attempts": got["tried"],
                "other_candidates_not_used": [
                    c for c in spec["candidates"] if c != got["url"]],
                "live_nodes_at_capture": info["nodes"],
                "text_chars_at_capture": info["text_chars"],
                "stylesheets_inlined": len(info["sheets"]),
                "forms": info["forms"],
                "iframes": info["iframes"],
                "password_fields": info["password_fields"],
                "nav_tabs_at_capture": info["nav_tabs"],
                "bot_wall_markers_in_html": got["walls"],
                "bytes": len(html.encode("utf-8")),
                "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                "file": f"corpus/wide/{name}.html",
                "revision": None,
                "revision_source": "none published; sha256 IS the version",
            }
            manifest["pages"][name] = entry
            print(f"  {name:>16}: {info['nodes']:>6} nodes, "
                  f"{len(info['sheets']):>2} sheets, "
                  f"{len(html) / 1024:>7.0f} KB, "
                  f"{len(info['nav_tabs'])} nav tabs, "
                  f"{info['password_fields']} password fields")
    finally:
        await MANAGER.close(session.session_id)

    captured = [n for n, p in manifest["pages"].items() if p.get("captured")]
    manifest["captured"] = sorted(captured)
    manifest["not_captured"] = sorted(
        n for n in manifest["pages"] if n not in captured)
    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\nfrozen {fetched} KST -> {OUT}")
    print(f"captured: {manifest['captured']}")
    print(f"not captured: {manifest['not_captured']}")


if __name__ == "__main__":
    asyncio.run(main())
