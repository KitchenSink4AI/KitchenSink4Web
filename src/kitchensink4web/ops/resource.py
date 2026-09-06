"""What a tab is holding when it is not a readable HTML document, and the
honest way out of it.

**The demand data inverts the obvious feature.** Across the 2,657-issue
survey the ask is never "read this PDF inside Chromium's viewer" (the one
issue that asks for that sits at zero reactions). The ask is always to
ESCAPE the viewer: playwright-mcp #1006 "Cannot save blob URLs (PDFs, files
opened in browser viewers)", playwright-mcp #430 "PDF Download vs PDF
Viewer", browser-use #499 "always download PDFs instead of opening in chrome
viewer", browser-use #729, skyvern #1346, and Vercel agent-browser #192.
So this module is a DOWNLOADS feature wearing a reading feature's clothes.

Three rules it exists to keep:

1. **Never render-scrape a PDF.** Chromium's viewer is a canvas and a closed
   shadow shell, and Firefox's pdf.js is a text layer built for painting
   rather than for reading. Text pulled out of either is reordered, deduped
   wrongly, or missing entirely, and the read surface that returned it would
   look like it worked. The reads refuse instead, and the refusal names the
   route.
2. **Report the type, do not guess the content.** `classify` says what the
   evidence supports and nothing else: the media type the document itself
   reports, the URL scheme, and the file name the resource carries.
3. **A blob URL gets the truth, not a route that fails.** `blob:` is a
   handle into the page's own memory, not a server resource, so no re-fetch
   by URL can reach it. Saying "download it" there would be a promise the
   server cannot keep, which is the failure class this product argues
   against.
"""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlparse

#: Media types the browser paints rather than lays out as a document. A read
#: against any of them is a garbled read, so the read surfaces refuse.
PDF_TYPES: frozenset[str] = frozenset({
    "application/pdf", "application/x-pdf", "application/acrobat",
    "applications/vnd.pdf", "text/pdf", "text/x-pdf",
})

#: Type PREFIXES that are never a readable document. `text/` and the
#: XML/HTML family are deliberately absent: those the projection reads
#: normally and this module must not intercept.
BINARY_PREFIXES: tuple[str, ...] = (
    "image/", "audio/", "video/", "font/",
    "application/zip", "application/x-zip", "application/octet-stream",
    "application/vnd.openxmlformats", "application/vnd.ms-",
    "application/vnd.oasis", "application/msword", "application/rtf",
    "application/x-tar", "application/gzip", "application/x-7z",
    "application/x-rar", "application/epub",
)

#: The probe the read surfaces run. Cheap by construction: a few property
#: reads, one shallow walk over body's direct children, no text extraction.
#:
#: SCOPED TO THE DOCUMENT ROOT (gauntlet 3, F2), which is what the evidence
#: string always claimed. The old probe ran querySelectorAll over the whole
#: document, so a council-minutes page with one inline PDF preview refused
#: every read, and a hostile page bought total read denial with a 1x1
#: offscreen embed. An embed or object counts as the document root when it
#: is the only element child of body or when it covers at least half the
#: viewport — the wrapper documents browsers synthesize around a bare PDF
#: are exactly the first shape, and a full-page inline viewer is the
#: second. The pdf.js-shell heuristic takes the same dominance test, for
#: the same reason: matching the viewer's MARKUP anywhere in the document
#: let any page that copied two class names refuse all reads.
#:
#: AN OBJECT RENDERING ITS FALLBACK IS NOT A RESOURCE (gauntlet 4, G4-03).
#: `<object>` renders its child content when the resource it names fails to
#: load, so `<object type="application/pdf" data="/missing.pdf">…article…
#: </object>` is a page a human reads normally while the box math sees a
#: root-level PDF embed and every read surface refuses. The dominance test
#: cannot tell the two apart because it measures the box, not the load. The
#: children can: a loaded plugin paints instead of its fallback and lays out
#: none of it, so a child with a real layout box means the fallback is what
#: is on screen. The test is applied to BOTH arms, only-child and dominant,
#: because a hostile page picks whichever arm is cheaper. `<embed>` has no
#: fallback content and is unaffected.
PROBE_JS = r"""
() => {
  const d = document;
  const vw = Math.max(1, window.innerWidth || 0);
  const vh = Math.max(1, window.innerHeight || 0);
  const dominant = (el) => {
    const r = el.getBoundingClientRect();
    return (r.width * r.height) >= 0.5 * vw * vh;
  };
  const painted = (node) => {
    try {
      if (node.nodeType === 1) {
        const r = node.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }
      if (node.nodeType === 3 && node.nodeValue.trim()) {
        const rg = d.createRange();
        rg.selectNode(node);
        const r = rg.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }
    } catch (e) {}
    return false;
  };
  const showsFallback = (el) => {
    if (!/^object$/i.test(el.tagName)) return false;
    for (const c of el.childNodes) { if (painted(c)) return true; }
    return false;
  };
  const roots = [];
  const b = d.body;
  if (b) {
    const kids = Array.from(b.children).filter((e) =>
      !/^(script|style|link|meta|template)$/i.test(e.tagName));
    for (const e of kids) {
      if (!/^(embed|object)$/i.test(e.tagName)) continue;
      const t = (e.getAttribute('type') || '').toLowerCase();
      if (!t || t === 'text/html') continue;
      if (showsFallback(e)) continue;
      if (kids.length === 1 || dominant(e)) roots.push(t);
    }
  }
  const vc = d.querySelector('#viewerContainer');
  const pdfjs = !!(vc && d.querySelector('.pdfViewer') && dominant(vc));
  return {
    content_type: (d.contentType || '').toLowerCase(),
    url: location.href,
    embedded_types: Array.from(new Set(roots)).slice(0, 4),
    pdf_js_viewer: pdfjs,
  };
}
"""


#: Every character a file name may not carry into a refusal sentence
#: (gauntlet 4, G4-08). The disposition branch always stripped CR and LF; the
#: URL branch did not, and `unquote` turns `%0A` in a path into a real
#: newline, so a URL ending `report%0AKS4WEB%20NOTE:%20…pdf` put attacker
#: prose on its own line inside the server's own sentence. The strip is
#: applied to BOTH branches and covers every C0 and C1 control character
#: rather than only the two that were demonstrated, because a name is a name
#: whichever control byte is hiding in it.
_NAME_CONTROLS = {c: " " for c in
                  list(range(0x00, 0x20)) + [0x7F] + list(range(0x80, 0xA0))}


def _clean_name(value: str) -> str:
    """One file name, with control characters flattened and length capped."""
    return value.translate(_NAME_CONTROLS).strip()[:160]


def filename_for(url: str, disposition: str | None = None) -> str | None:
    """The name this resource would be saved under, from the
    Content-Disposition header when the server sent one and from the URL
    path otherwise. None when neither carries a name, because inventing one
    is how a download becomes a bare UUID (browser-use #1951)."""
    if disposition:
        text = disposition.replace("\r", " ").replace("\n", " ")
        for token in text.split(";"):
            token = token.strip()
            for key in ("filename*=", "filename="):
                if token.lower().startswith(key):
                    value = token[len(key):].strip().strip('"')
                    if key.endswith("*=") and "''" in value:
                        value = value.split("''", 1)[1]
                    value = posixpath.basename(unquote(value).replace("\\", "/"))
                    value = _clean_name(value)
                    if value:
                        return value
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return None
    name = _clean_name(posixpath.basename(unquote(parsed.path or "")))
    return name or None


def _kind_for(content_type: str, url: str, probe: dict) -> str | None:
    if content_type in PDF_TYPES or any(
            t in PDF_TYPES for t in probe.get("embedded_types") or ()):
        return "pdf"
    if probe.get("pdf_js_viewer"):
        return "pdf"
    if content_type.startswith(BINARY_PREFIXES):
        return "binary"
    return None


def classify(probe: dict) -> dict | None:
    """What this tab is holding, or None for an ordinary document.

    None is the answer for every HTML page, which is the overwhelmingly
    common case, so the callers pay one dictionary lookup and move on."""
    content_type = (probe.get("content_type") or "").split(";")[0] \
        .strip().lower()
    url = probe.get("url") or ""
    scheme = urlparse(url).scheme.lower()
    kind = _kind_for(content_type, url, probe)
    if kind is None and scheme == "blob":
        # A blob document with no type still is not a page anyone navigated
        # to on purpose; the caller deserves to know the URL is page-local.
        kind = "binary"
    if kind is None:
        return None
    evidence = []
    if content_type:
        evidence.append(f"document.contentType is {content_type}")
    if probe.get("embedded_types"):
        evidence.append("the document root is an embed of "
                        + ", ".join(probe["embedded_types"]))
    if probe.get("pdf_js_viewer"):
        evidence.append("the document is Firefox's pdf.js viewer shell")
    if scheme in ("blob", "data"):
        evidence.append(f"the URL scheme is {scheme}:")
    return {
        "kind": kind,
        "media_type": content_type or None,
        "url": url,
        "url_scheme": scheme,
        "filename": filename_for(url),
        "page_local": scheme in ("blob", "data"),
        "evidence": "; ".join(evidence) or "the document is not HTML",
        "readable_as_text": False,
    }


async def probe_page(page) -> dict | None:
    """Run the probe against a live page and classify the result. A driver
    that refuses the evaluate (a page mid-navigation, a crashed renderer)
    returns None rather than raising: this is an advisory, and a failed
    advisory must never turn a working read into an error."""
    try:
        raw = await page.evaluate(PROBE_JS)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return classify(raw)


# ------------------------------------------------------------- the wording


def _what(info: dict) -> str:
    if info["kind"] == "pdf":
        return "a PDF the browser is painting in its own viewer"
    return (f'a {info["media_type"]} resource'
            if info.get("media_type") else "a non-HTML resource")


def escape_route(info: dict) -> str:
    """The route out, and it differs by URL scheme because the truth does.

    An http(s) resource can be fetched again through the browser's own
    session, cookies and all, which is what `download(action='fetch')` does.
    A `blob:` URL cannot: it names memory inside the page, so there is
    nothing for any client to re-request, and the only way to disk is the
    page's own save control."""
    if info.get("page_local"):
        return (
            f'This URL is page-local ({info["url_scheme"]}:), which means it '
            f'names data held in the page rather than a resource on a '
            f'server, so no re-fetch by URL can reach it and KS4Web will not '
            f'pretend otherwise. The route to disk is the page\'s own save '
            f'or download control: download(page=..., action="click", '
            f'location=...) arms the download listener first and saves what '
            f'the click produces, with the file name the page suggests.')
    name = info.get("filename")
    return (
        f'Save it instead of reading it: download(page=..., '
        f'action="fetch", url="{info["url"]}") re-requests this exact '
        f'resource through the browser\'s own session, so a signed-in '
        f'document works, and writes it to the scoped downloads directory'
        + (f' as {name}' if name else '')
        + '. From there a PDF reader (or KS4XL for a spreadsheet) reads the '
          'real file rather than a scrape of a viewer.')


def read_refusal(info: dict, tool: str):
    """The refusal a read surface raises. UNSUPPORTED_CONTENT is the honest
    code: the content is genuinely unreachable as text through this tab, not
    missing and not a bad argument."""
    from ..errors import UnsupportedContent

    exc = UnsupportedContent(
        f'{info["url"]} is {_what(info)}, not a document with readable '
        f'text, so {tool} returns nothing rather than a scrape of the '
        f'viewer chrome. Evidence: {info["evidence"]}. Text pulled out of a '
        f'PDF viewer is reordered and partial, and a read that returned it '
        f'would look like it worked. {escape_route(info)}')
    exc.hint_tools = ("download",)
    exc.detail = {k: info[k] for k in
                  ("kind", "media_type", "filename", "page_local")}
    return exc


def navigate_note(info: dict) -> dict:
    """The advisory `navigate` attaches when a navigation lands on one of
    these. Navigation is not refused: going to a PDF in order to save it is
    a normal thing to do, and the caller only needs to be told that reading
    it is not the next move."""
    return {
        "kind": info["kind"],
        "media_type": info.get("media_type"),
        "filename": info.get("filename"),
        "page_local": info.get("page_local", False),
        "readable": False,
        "why": (f'this tab holds {_what(info)}. get_page_view and get_text '
                f'refuse on it rather than returning viewer chrome. '
                f'Evidence: {info["evidence"]}.'),
        "route": escape_route(info),
    }
