"""Freeze corpus A: the four MEASURED benchmark pages, captured once and
committed, so every published KS4Web number is reproducible after the live
pages change.

PLAN 1.3 requires this before the Phase 2 harness and it was owed from S1,
which ran against live pages and froze only its extraction outputs. The
difference matters: a frozen extraction re-derives the ladder offline but
cannot re-derive a page number after `extract.js` changes, and `extract.js`
changed substantially in Phase 1. A frozen PAGE can.

**What "frozen" means here, stated because a naive capture is not frozen.**
A single `outerHTML` dump loses every stylesheet, and visibility on the web is
a CSS property, so a projection run against that dump would compute different
hidden-content answers than the live page did. The capture therefore:

- serializes the post-load DOM (`document.documentElement.outerHTML`), which
  is the tree the projection actually walks rather than the source HTML;
- inlines every stylesheet in document order, external ones fetched through
  the browser's own request context so cross-origin sheets are not lost;
- strips every `<script>`, because a frozen page that rehydrates is not
  frozen, and a page that mutates after load makes the benchmark
  irreproducible in exactly the way freezing was supposed to fix;
- keeps hrefs untouched. Wikipedia's internal links are root-relative, so a
  page served from localhost still matches origin and still prints paths
  rather than full URLs, which is what keeps the token count comparable to
  the live read.

No `<base>` tag is injected, deliberately. A base pointing at the live origin
would make every internal link absolute and cross-origin, which would change
the affordance lines and inflate the very number this corpus exists to fix.

Run:  .venv/Scripts/python.exe -X utf8 scripts/freeze_corpus_a.py
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

OUT = ROOT / "corpus" / "a"

#: The four pages the banked MEASURED baseline used, so every KS4Web figure
#: is directly comparable to the incumbent numbers without re-measuring them
#: (PLAN 1.3, DESIGN 3.2).
PAGES = {
    "wikipedia_versailles": "https://en.wikipedia.org/wiki/Treaty_of_Versailles",
    "wikipedia_gdp_table":
        "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)",
    "httpbin_form": "https://httpbin.org/forms/post",
    "example_com": "https://example.com/",
}

#: Read before the scripts are stripped. MediaWiki publishes the exact
#: revision the response was built from, which is the only real version
#: identifier in the set; the others get a content hash and say so.
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
  let revision = null;
  try {
    if (window.mw && mw.config && mw.config.get) {
      revision = mw.config.get('wgCurRevisionId') || mw.config.get('wgRevisionId');
    }
  } catch (e) { revision = null; }
  return {
    sheets,
    revision: revision === null ? null : String(revision),
    url: location.href,
    title: document.title,
    nodes: document.getElementsByTagName('*').length,
  };
})()
"""

_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
_SCRIPT_EMPTY = re.compile(r"<script\b[^>]*/?>", re.I)
_LINK_SHEET = re.compile(
    r"<link\b[^>]*\brel\s*=\s*[\"']?[^\"'>]*stylesheet[^\"'>]*[\"']?[^>]*>",
    re.I)
_NOSCRIPT = re.compile(r"<noscript\b[^>]*>.*?</noscript\s*>", re.I | re.S)


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


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = _kst()
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    manifest = {
        "corpus": "A",
        "purpose": "the four MEASURED benchmark pages, frozen (PLAN 1.3)",
        "fetched_kst": fetched,
        "lane": "A(chromium) headless",
        "capture": {
            "dom": "post-load document.documentElement.outerHTML",
            "styles": "inlined in document order, external sheets fetched "
                      "through the browser request context",
            "stripped": "script, noscript, link[rel~=stylesheet]",
            "base_tag": "none, deliberately: hrefs stay as the live page "
                        "wrote them so origin matching is unchanged",
        },
        "pages": {},
    }
    try:
        record = session.page(session.focused)
        page = record.page
        for name, url in PAGES.items():
            await page.goto(url, wait_until="load", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
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
            html = await page.evaluate(
                "document.documentElement.outerHTML")
            html = "<!doctype html>\n" + _freeze_html(html, "\n".join(texts))
            path = OUT / f"{name}.html"
            path.write_text(html, encoding="utf-8")
            digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
            manifest["pages"][name] = {
                "url": url,
                "final_url": info["url"],
                "title": info["title"],
                "revision": info["revision"],
                "revision_source": ("MediaWiki wgCurRevisionId"
                                    if info["revision"] else
                                    "none published; sha256 IS the version"),
                "live_nodes_at_capture": info["nodes"],
                "stylesheets_inlined": len(info["sheets"]),
                "bytes": len(html.encode("utf-8")),
                "sha256": digest,
                "file": f"corpus/a/{name}.html",
            }
            print(f"{name:>22}: {info['nodes']:>6} nodes, "
                  f"{len(info['sheets']):>2} sheets, "
                  f"{len(html) / 1024:>7.0f} KB, rev={info['revision']}")
    finally:
        await MANAGER.close(session.session_id)

    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\nfrozen {fetched} KST -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
