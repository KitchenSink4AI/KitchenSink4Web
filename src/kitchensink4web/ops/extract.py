"""The `extract` pack: deterministic structured extraction (DESIGN 2.2).

DEMAND: deterministic non-LLM table-to-JSON extraction is served by ZERO of
the 21 servers the research inspected. This is where the token thesis
produces its largest demonstrable multiplier, and it is the family bridge:
`export_data` writes the file KS4XL consumes.

Everything here is a READ. No tool in this module mutates page state, none
passes through the acting branch of the policy choke point, and all six are
registered under read-only mode. What binds them instead:

- **Deterministic, not generative.** A table becomes JSON by walking the
  grid, carrying every rowspan and colspan value forward cell by cell, so
  "Q1 belongs to 2024 and to North America" survives the flattening. No
  model is consulted and the same page always produces the same JSON.
- **Div-tables are detected and named as such** (`role="table"` /
  `role="grid"` built from divs), because that is the shape application
  frameworks actually ship, and an inventory keyed on the TABLE tag reports
  half the page.
- **Honesty about what was not extracted.** Row paging states the total and
  the next start row; clipped cells are counted; a field the deterministic
  matcher cannot fill comes back `found: false` with the strategies that
  were tried, never a guess.
"""

from __future__ import annotations

import csv
import io
import json

from ..errors import AmbiguousLocation, BadParams, TargetNotFound
from ..projection import ntok as _ntok
from ..projection.meter import ENCODING_NAME as _ENCODING
from . import act as _act
from . import common

#: Per-cell and per-value clip lengths. Clipping is counted, never silent.
CELL_CLIP = 200
VALUE_CLIP = 300

#: The zero-candidate refusals. A page with nothing to extract is a normal
#: page, not a malformed call, so it gets an honest NOT_FOUND that says what
#: the tool looked for and where to look instead. Both messages name
#: get_page_view, because "what IS here" is the only useful next move.
_NO_TABLES = (
    "this page has no data tables the tool recognizes. It looks for real "
    "TABLE elements and ARIA div-tables (role=\"table\" or role=\"grid\"), "
    "and it skips layout tables, which older sites use for page structure "
    "rather than data. get_page_view shows what IS on the page, and "
    "get_list or get_text reach content that is not tabular.")
_NO_LISTS = (
    "this page has no lists the tool recognizes. It looks for UL, OL, DL, "
    "and role=\"list\" elements holding two or more items, and it skips "
    "navigation lists. Repeated content laid out in TABLE rows or bare "
    "divs is not a semantic list, which is what Hacker News-style layouts "
    "do. get_page_view shows what IS on the page, and get_table reads "
    "tabular layouts.")


# ------------------------------------------------------------------ tables

_TABLE_JS = r"""
(arg) => {
  const opts = arg.opts || {};
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const CLIP = opts.cell_clip || 200;
  let clipped = 0;
  const clip = (s) => { s = squash(s); if (s.length <= CLIP) return s; clipped++; return s.slice(0, CLIP) + '...'; };

  const SEL = 'table, [role="table"], [role="grid"], [role="treegrid"]';
  function kindOf(el) {
    if ((el.getAttribute('role') || '') === 'presentation') return 'layout';
    if (el.tagName === 'TABLE') return 'table';
    const role = el.getAttribute('role') || '';
    return role === 'grid' || role === 'treegrid' ? 'div-grid' : 'div-table';
  }
  function captionOf(el) {
    if (el.tagName === 'TABLE' && el.caption) return squash(el.caption.textContent);
    const al = el.getAttribute('aria-label'); if (al) return squash(al);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = document.getElementById(lb.split(/\s+/)[0]); if (t) return squash(t.textContent); }
    return '';
  }
  function rowsOf(el) {
    if (el.tagName === 'TABLE') return Array.from(el.rows);
    return Array.from(el.querySelectorAll('[role="row"]'));
  }
  function cellsOf(rowEl, real) {
    if (real) return Array.from(rowEl.cells);
    return Array.from(rowEl.querySelectorAll(
      '[role="columnheader"], [role="rowheader"], [role="cell"], [role="gridcell"]'));
  }

  // ------------------------------------------------ choose the target table
  let target = null;
  if (arg.el) {
    target = arg.el.matches && arg.el.matches(SEL) ? arg.el
      : (arg.el.querySelector ? arg.el.querySelector(SEL) : null);
    if (!target) return { error: 'no-table-in-element' };
  } else {
    const all = Array.from(document.querySelectorAll(SEL))
      .filter((el) => !el.closest('[role="presentation"] *'))
      .filter((el) => kindOf(el) !== 'layout');
    // nested role tables inside a TABLE would double-count; keep outermost
    const tables = all.filter((el) => !all.some((o) => o !== el && o.contains(el)));
    if (typeof opts.index === 'number') {
      if (opts.index < 0 || opts.index >= tables.length)
        return { error: 'index-out-of-range', tables: tables.length };
      target = tables[opts.index];
    } else if (tables.length === 1) {
      target = tables[0];
    } else {
      return { choose: tables.map((el, i) => ({
        index: i, kind: kindOf(el), caption: clip(captionOf(el)),
        rows: rowsOf(el).length })), count: tables.length };
    }
  }

  const real = target.tagName === 'TABLE';
  const kind = kindOf(target);
  const rowEls = rowsOf(target);

  // -------------------------------------- expand the grid, spans carried
  const matrix = [];
  let spans = 0;
  rowEls.forEach((tr, r) => {
    matrix[r] = matrix[r] || [];
    let c = 0;
    for (const cell of cellsOf(tr, real)) {
      while (matrix[r][c] !== undefined) c++;
      const rs = parseInt(cell.getAttribute('rowspan') || cell.getAttribute('aria-rowspan') || '1', 10) || 1;
      const cs = parseInt(cell.getAttribute('colspan') || cell.getAttribute('aria-colspan') || '1', 10) || 1;
      const text = clip(cell.textContent);
      const th = real ? cell.tagName === 'TH'
        : /columnheader|rowheader/.test(cell.getAttribute('role') || '');
      const inHead = real && !!cell.closest('thead');
      for (let dr = 0; dr < rs; dr++) {
        for (let dc = 0; dc < cs; dc++) {
          matrix[r + dr] = matrix[r + dr] || [];
          matrix[r + dr][c + dc] = { t: text, th: th, h: inHead };
          if (dr || dc) spans++;
        }
      }
      c += cs;
    }
  });

  // ------------------------------------------- header rows, then data rows
  let headerRows = 0;
  for (const row of matrix) {
    const cells = row.filter(Boolean);
    if (cells.length && (cells.every((x) => x.th) || cells.every((x) => x.h))) headerRows++;
    else break;
  }
  const width = Math.max(0, ...matrix.map((r) => r.length));
  const headers = [];
  for (let c = 0; c < width; c++) {
    const parts = [];
    for (let r = 0; r < headerRows; r++) {
      const cell = matrix[r] && matrix[r][c];
      const t = cell ? cell.t : '';
      if (t && parts[parts.length - 1] !== t) parts.push(t);
    }
    headers.push(parts.join(' / '));
  }
  const data = matrix.slice(headerRows).map(
    (row) => Array.from({ length: width }, (_, c) => (row[c] ? row[c].t : '')));

  const start = Math.max(0, opts.start_row || 0);
  const limit = Math.max(1, opts.max_rows || 50);
  return {
    kind: kind, caption: captionOf(target), columns: width,
    header_rows: headerRows, headers: headers,
    total_rows: data.length, start_row: start,
    rows: data.slice(start, start + limit),
    next_start_row: start + limit < data.length ? start + limit : null,
    spans_expanded: spans, clipped_cells: clipped,
  };
}
"""


async def _table_data(sess, record, location, index, start_row, max_rows):
    """One extraction path for get_table and export_data."""
    el = None
    if location:
        resolved = await _act.resolve(sess, record, location, tool="get_table")
        el = resolved["handle"]
    got = await record.page.evaluate(_TABLE_JS, {
        "el": el, "opts": {"index": index, "start_row": start_row,
                           "max_rows": max_rows, "cell_clip": CELL_CLIP}})
    if got.get("error") == "no-table-in-element":
        raise TargetNotFound(
            "the located element is not a table and contains none. Point at "
            "a table ref from a read (location={'table': 't1'}), a CSS "
            "selector for one, or call get_table with no location to see the "
            "page's table inventory.")
    if got.get("error") == "index-out-of-range":
        if not got["tables"]:
            raise TargetNotFound(_NO_TABLES)
        raise BadParams(
            f"index is out of range: this page has {got['tables']} data "
            f"table(s), so the valid indexes are 0 to {got['tables'] - 1}.")
    # Zero candidates arrives here as an EMPTY choose list, which is falsy:
    # the field test (2026-09-05) watched it skip the refusal below and
    # fall through to got["next_start_row"], where the KeyError became a
    # bogus "internal lookup failed" BAD_PARAMS. Membership, not truth.
    if "choose" in got and not got["choose"]:
        raise TargetNotFound(_NO_TABLES)
    if got.get("choose"):
        listing = "; ".join(
            f'index={t["index"]} {t["kind"]} "{t["caption"] or "(uncaptioned)"}"'
            f' ({t["rows"]} rows)' for t in got["choose"])
        raise AmbiguousLocation(
            f'this page has {got["count"]} data tables and none was named; '
            f'no tool acts on first match. Pass index=N or a location: '
            f'{listing}.')
    return got


async def get_table(
    page: str,
    location: dict | None = None,
    index: int | None = None,
    start_row: int = 0,
    max_rows: int = 50,
) -> dict:
    """Read one table as deterministic JSON: headers plus rows of plain
    strings, with every rowspan and colspan value carried forward into the
    cells it spans, so the grid you get back is rectangular and aligned
    rather than silently shifted after the first merged cell. Returns the
    table kind as detected (a real TABLE, or a div-table built from ARIA
    roles, named as such), the caption, the total row count, and a paged
    row slice with the next start_row stated, so a ten-thousand-row table
    is read in bounded pieces. With no location and several tables on the
    page, the inventory comes back as a refusal listing each candidate.
    """
    sess, record = common.locate(page)
    sess.counters["reads"] += 1
    got = await _table_data(sess, record, location, index, start_row, max_rows)
    more = (f'get_table(page="{record.handle}", '
            f'start_row={got["next_start_row"]}'
            + (f', index={index}' if index is not None else '')
            + ') returns the next rows'
            if got["next_start_row"] is not None
            else "all rows in the table are included")
    payload = {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "table": {k: got[k] for k in
                  ("kind", "caption", "columns", "headers", "total_rows",
                   "start_row", "rows", "next_start_row")},
        "continue": more,
        "accounting": {
            "spans_expanded": got["spans_expanded"],
            "clipped_cells": got["clipped_cells"],
            "note": ("merged cells are expanded: a value spanning rows or "
                     "columns is repeated into every position it covers, "
                     "which is what keeps later columns aligned"),
        },
    }
    payload["budget"] = {"used": _ntok(json.dumps(payload["table"])),
                         "estimator": _ENCODING}
    return payload


# ------------------------------------------------------------------- lists

_LIST_JS = r"""
(arg) => {
  const opts = arg.opts || {};
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };
  const SEL = 'ul, ol, dl, [role="list"], [role="listbox"], [role="menu"]';

  function itemsOf(el) {
    if (el.tagName === 'DL') {
      const out = []; let dt = null;
      for (const child of el.children) {
        if (child.tagName === 'DT') dt = squash(child.textContent);
        else if (child.tagName === 'DD')
          out.push({ term: dt, el: child });
      }
      return out.map((x) => ({ el: x.el, term: x.term }));
    }
    const li = el.querySelectorAll(':scope > li, :scope > [role="listitem"], :scope > [role="option"], :scope > [role="menuitem"]');
    if (li.length) return Array.from(li).map((e) => ({ el: e }));
    return Array.from(el.children).map((e) => ({ el: e }));
  }

  let target = null;
  if (arg.el) {
    target = arg.el.matches && arg.el.matches(SEL) ? arg.el
      : (arg.el.querySelector ? arg.el.querySelector(SEL) : arg.el);
  } else {
    const all = Array.from(document.querySelectorAll(SEL))
      .filter((el) => !el.closest('nav'))
      .filter((el) => itemsOf(el).length >= 2);
    const top = all.filter((el) => !all.some((o) => o !== el && o.contains(el)));
    if (typeof opts.index === 'number') {
      if (opts.index < 0 || opts.index >= top.length)
        return { error: 'index-out-of-range', lists: top.length };
      target = top[opts.index];
    } else if (top.length === 1) {
      target = top[0];
    } else {
      return { choose: top.slice(0, 12).map((el, i) => ({
        index: i, tag: el.tagName.toLowerCase(),
        items: itemsOf(el).length,
        first: clip(itemsOf(el)[0].el.textContent, 80) })),
        count: top.length };
    }
  }
  if (!target) return { error: 'no-list-in-element' };

  const items = itemsOf(target);
  const start = Math.max(0, opts.start_index || 0);
  const limit = Math.max(1, opts.max_items || 50);
  const out = items.slice(start, start + limit).map((x, i) => {
    const link = x.el.querySelector ? x.el.querySelector('a[href]') : null;
    const rec = { i: start + i, text: clip(x.el.textContent, 200) };
    if (x.term) rec.term = x.term;
    if (link) { try { rec.href = new URL(link.href, location.href).pathname + new URL(link.href, location.href).search; } catch (e) { rec.href = link.getAttribute('href'); } }
    return rec;
  });
  return {
    tag: target.tagName.toLowerCase(),
    total_items: items.length, start_index: start, items: out,
    next_start_index: start + limit < items.length ? start + limit : null,
  };
}
"""


async def get_list(
    page: str,
    location: dict | None = None,
    index: int | None = None,
    start_index: int = 0,
    max_items: int = 50,
) -> dict:
    """Read a list of repeated records (a UL, OL, DL, or an ARIA list) as
    plain items: each one's text, its definition term where the list is a
    DL, and the first link path it carries. Returns the total item count
    and a paged slice with the next start_index stated, so a long feed is
    read in bounded pieces rather than one dump. With no location and
    several lists on the page, the candidates come back as a refusal
    listing each one's size and first item, so the second call names its
    target exactly. Navigation lists are excluded from auto-selection
    because get_page_view already carries them.
    """
    sess, record = common.locate(page)
    sess.counters["reads"] += 1
    el = None
    if location:
        resolved = await _act.resolve(sess, record, location, tool="get_list")
        el = resolved["handle"]
    got = await record.page.evaluate(_LIST_JS, {
        "el": el, "opts": {"index": index, "start_index": start_index,
                           "max_items": max_items}})
    if got.get("error") == "no-list-in-element":
        raise TargetNotFound(
            "the located element is not a list and contains none. Pass a ref "
            "from a read, a CSS selector, or no location to see the page's "
            "list inventory.")
    if got.get("error") == "index-out-of-range":
        if not got["lists"]:
            raise TargetNotFound(_NO_LISTS)
        raise BadParams(
            f"index is out of range: this page has {got['lists']} list(s), "
            f"so the valid indexes are 0 to {got['lists'] - 1}.")
    # Same empty-choose fallthrough as get_table; see the note there.
    if "choose" in got and not got["choose"]:
        raise TargetNotFound(_NO_LISTS)
    if got.get("choose"):
        listing = "; ".join(
            f'index={c["index"]} <{c["tag"]}> {c["items"]} items, first: '
            f'"{c["first"]}"' for c in got["choose"])
        raise AmbiguousLocation(
            f'this page has {got["count"]} candidate lists and none was '
            f'named; no tool acts on first match. Pass index=N or a '
            f'location: {listing}.')
    more = (f'get_list(page="{record.handle}", '
            f'start_index={got["next_start_index"]}'
            + (f', index={index}' if index is not None else '')
            + ') returns the next items'
            if got["next_start_index"] is not None
            else "all items in the list are included")
    return {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "list": got,
        "continue": more,
        "budget": {"used": _ntok(json.dumps(got)), "estimator": _ENCODING},
    }


# ------------------------------------------------------------------- links

_LINKS_JS = r"""
(arg) => {
  const opts = arg.opts || {};
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };
  const root = arg.el || document;
  const seen = new Map();
  let scanned = 0;
  const counts = { nav: 0, prose: 0, other: 0 };
  for (const a of root.querySelectorAll('a[href]')) {
    scanned++;
    let href;
    try {
      const u = new URL(a.href, location.href);
      href = u.origin !== location.origin ? u.origin + u.pathname
        : u.pathname + u.search + u.hash;
    } catch (e) { href = a.getAttribute('href'); }
    const name = clip(a.textContent, 100) || clip(a.getAttribute('aria-label'), 100);
    const kind = a.closest('nav, [role="navigation"], header, footer') ? 'nav'
      : (a.closest('p, blockquote, figcaption') ? 'prose' : 'other');
    counts[kind]++;
    if (opts.kind && opts.kind !== 'all' && kind !== opts.kind) continue;
    if (opts.pattern) {
      const p = String(opts.pattern).toLowerCase();
      if (name.toLowerCase().indexOf(p) < 0 && String(href).toLowerCase().indexOf(p) < 0) continue;
    }
    const key = kind + '|' + name + '|' + href;
    if (seen.has(key)) { seen.get(key).count++; continue; }
    seen.set(key, { name: name, href: href, kind: kind, count: 1 });
  }
  return { scanned: scanned, counts: counts,
           links: Array.from(seen.values()) };
}
"""


async def get_links(
    page: str,
    location: dict | None = None,
    kind: str = "all",
    pattern: str | None = None,
    start_index: int = 0,
    limit: int = 40,
) -> dict:
    """List a page's links as data: accessible name, href path, and a class
    per link (nav for navigation and chrome, prose for links inside running
    text, other for the rest), deduplicated with repeat counts. Returns the
    total per class, so "2,858 in-prose citation links" arrives as one
    number rather than as 2,858 lines, plus a paged slice filtered by kind
    or by a substring pattern over names and hrefs. This is the bulk
    complement to find_elements: use find_elements to retrieve one link you
    can name, and this to survey what is there.
    """
    kinds = ("all", "nav", "prose", "other")
    if kind not in kinds:
        raise BadParams(f"unknown kind {kind!r}; the kinds are {list(kinds)}.")
    sess, record = common.locate(page)
    sess.counters["reads"] += 1
    el = None
    if location:
        resolved = await _act.resolve(sess, record, location, tool="get_links")
        el = resolved["handle"]
    got = await record.page.evaluate(_LINKS_JS, {
        "el": el, "opts": {"kind": kind, "pattern": pattern}})
    chunk, total, nxt = common.page_slice(got["links"], start_index, limit)
    more = (f'get_links(page="{record.handle}", start_index={nxt}) returns '
            f'the next links' if nxt is not None
            else "all matching links are included")
    return {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "totals": {"scanned": got["scanned"], **got["counts"],
                   "matched": total},
        "links": chunk,
        "continue": more,
        "budget": {"used": _ntok(json.dumps(chunk)), "estimator": _ENCODING},
    }


# --------------------------------------------------------------- metadata

_META_JS = r"""
() => {
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const out = {
    url: location.href, title: squash(document.title),
    lang: document.documentElement.getAttribute('lang') || null,
    meta: {}, open_graph: {}, twitter: {}, json_ld: [],
    json_ld_invalid: 0, json_ld_truncated: 0,
    feeds: [], canonical: null, microdata_itemtypes: [],
  };
  for (const m of document.querySelectorAll('meta[name], meta[property]')) {
    const key = (m.getAttribute('name') || m.getAttribute('property') || '').toLowerCase();
    const content = squash(m.getAttribute('content'));
    if (!key || !content) continue;
    if (key.startsWith('og:')) out.open_graph[key] = content.slice(0, 300);
    else if (key.startsWith('twitter:')) out.twitter[key] = content.slice(0, 300);
    else if (['description', 'author', 'keywords', 'robots', 'generator', 'theme-color'].includes(key))
      out.meta[key] = content.slice(0, 300);
  }
  const canon = document.querySelector('link[rel="canonical"]');
  if (canon) out.canonical = canon.href;
  for (const l of document.querySelectorAll('link[rel="alternate"]')) {
    const type = (l.getAttribute('type') || '').toLowerCase();
    if (/rss|atom|json/.test(type))
      out.feeds.push({ type: type, href: l.href, title: l.getAttribute('title') || null });
  }
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(s.textContent);
      let text = JSON.stringify(parsed);
      if (text.length > 2000) { text = text.slice(0, 2000); out.json_ld_truncated++; }
      const types = [];
      (Array.isArray(parsed) ? parsed : [parsed]).forEach((n) => {
        if (n && n['@type']) types.push(String(n['@type']));
      });
      out.json_ld.push({ types: types, data: text });
    } catch (e) { out.json_ld_invalid++; }
    if (out.json_ld.length >= 8) break;
  }
  const seen = new Set();
  for (const el of document.querySelectorAll('[itemscope][itemtype]')) {
    const t = el.getAttribute('itemtype'); if (t && !seen.has(t)) { seen.add(t); }
    if (seen.size >= 10) break;
  }
  out.microdata_itemtypes = Array.from(seen);
  return out;
}
"""


async def get_metadata(page: str) -> dict:
    """Read a page's machine-readable metadata in one call: title, language,
    canonical URL, the description and robots meta tags, OpenGraph and
    Twitter card properties, parsed JSON-LD blocks with their schema.org
    types named (each block size-capped, with the truncated and invalid
    counts stated), microdata itemtypes, and any RSS, Atom, or JSON feeds
    the page advertises. Returns it all as labeled data from the page's own
    markup, deterministically: nothing here is inferred from prose, so the
    same page always answers the same way.
    """
    sess, record = common.locate(page)
    sess.counters["reads"] += 1
    got = await record.page.evaluate(_META_JS)
    return {
        "page": record.handle, "session": sess.session_id,
        "metadata": got,
        "budget": {"used": _ntok(json.dumps(got)), "estimator": _ENCODING},
    }


# ------------------------------------------------------- schema-directed

_FIELDS_JS = r"""
() => {
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };
  const sources = [];  // {key, value, by}

  // 1. JSON-LD, flattened one level deep with dotted paths.
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(s.textContent);
      const nodes = Array.isArray(parsed) ? parsed : [parsed];
      for (const node of nodes) {
        if (!node || typeof node !== 'object') continue;
        for (const [k, v] of Object.entries(node)) {
          if (v == null || k.startsWith('@')) continue;
          if (typeof v === 'object' && !Array.isArray(v)) {
            for (const [k2, v2] of Object.entries(v)) {
              if (v2 != null && typeof v2 !== 'object')
                sources.push({ key: k + '.' + k2, value: clip(String(v2), 300), by: 'json-ld' });
            }
          } else {
            const flat = Array.isArray(v) ? v.filter((x) => typeof x !== 'object').join(', ') : String(v);
            if (flat) sources.push({ key: k, value: clip(flat, 300), by: 'json-ld' });
          }
        }
      }
    } catch (e) {}
  }
  // 2. meta tags.
  for (const m of document.querySelectorAll('meta[name], meta[property]')) {
    const key = m.getAttribute('name') || m.getAttribute('property');
    const content = squash(m.getAttribute('content'));
    if (key && content) sources.push({ key: key, value: clip(content, 300), by: 'meta' });
  }
  // 3. microdata itemprops.
  for (const el of document.querySelectorAll('[itemprop]')) {
    const key = el.getAttribute('itemprop');
    const value = squash(el.getAttribute('content') || el.textContent);
    if (key && value) sources.push({ key: key, value: clip(value, 300), by: 'microdata' });
  }
  // 4. definition lists.
  for (const dl of document.querySelectorAll('dl')) {
    let dt = null;
    for (const child of dl.children) {
      if (child.tagName === 'DT') dt = squash(child.textContent);
      else if (child.tagName === 'DD' && dt)
        sources.push({ key: dt, value: clip(child.textContent, 300), by: 'definition-list' });
    }
  }
  // 5. two-column tables: row header -> row value.
  for (const table of document.querySelectorAll('table')) {
    for (const tr of table.rows) {
      if (tr.cells.length === 2) {
        const k = squash(tr.cells[0].textContent);
        const v = squash(tr.cells[1].textContent);
        if (k && v && k.length < 80) sources.push({ key: k, value: clip(v, 300), by: 'table-row' });
      }
    }
  }
  // 6. labeled non-secret form values.
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const type = (el.type || '').toLowerCase();
    if (type === 'password' || type === 'hidden') continue;
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    if (/current-password|new-password|one-time-code/.test(ac)) continue;
    let label = '';
    if (el.labels && el.labels.length) label = squash(el.labels[0].textContent);
    if (!label) label = squash(el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '');
    const value = el.tagName === 'SELECT'
      ? (el.selectedOptions.length ? squash(el.selectedOptions[0].textContent) : '')
      : squash(el.value);
    if (label && value) sources.push({ key: label, value: clip(value, 300), by: 'form-field' });
  }
  return { sources: sources.slice(0, 800), total_sources: sources.length };
}
"""


def _norm(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


async def extract_fields(page: str, fields: list | dict) -> dict:
    """Fill a caller-named schema from a page by deterministic matching, and
    be honest about what did not fill. Pass field names (a list, or a dict
    of name to hint); each is matched against the page's JSON-LD keys, meta
    tags, microdata itemprops, definition lists, two-column table rows, and
    labeled non-secret form values, exact name first and substring second.
    Returns per field the value, where it was found, and the match quality,
    or found=false with the sources that were searched, never a guess.
    Secret fields (passwords, one-time codes) are never read and can never
    fill a schema. No model is consulted: the same page and schema always
    return the same answer.
    """
    if isinstance(fields, dict):
        wanted = {str(k): str(v or "") for k, v in fields.items()}
    elif isinstance(fields, list) and fields:
        wanted = {str(k): "" for k in fields}
    else:
        raise BadParams(
            "extract_fields needs the schema to fill: a list of field names "
            "(['price', 'author']) or a dict of name to hint "
            "({'price': 'the listed product price'}).")
    sess, record = common.locate(page)
    sess.counters["reads"] += 1
    got = await record.page.evaluate(_FIELDS_JS)
    sources = got["sources"]
    by_norm: dict[str, dict] = {}
    for src in sources:
        by_norm.setdefault(_norm(src["key"]), src)

    results: dict[str, dict] = {}
    unfilled = 0
    for name, hint in wanted.items():
        needles = [name] + ([hint] if hint else [])
        hit, quality = None, None
        for needle in needles:
            n = _norm(needle)
            if not n:
                continue
            if n in by_norm:
                hit, quality = by_norm[n], "exact"
                break
            partial = next((src for norm, src in by_norm.items()
                            if n in norm or (len(n) > 3 and norm in n)), None)
            if partial is not None:
                hit, quality = partial, "partial"
                break
        if hit:
            results[name] = {"found": True, "value": hit["value"],
                             "source": hit["by"], "matched_key": hit["key"],
                             "match": quality}
        else:
            unfilled += 1
            results[name] = {
                "found": False,
                "note": (f"no deterministic source matched {name!r}. "
                         f"{got['total_sources']} candidate keys were "
                         f"searched across json-ld, meta, microdata, "
                         f"definition lists, table rows, and labeled form "
                         f"fields. The value may live in prose (get_text) "
                         f"or a table (get_table)."),
            }
    return {
        "page": record.handle, "session": sess.session_id,
        "fields": results,
        "accounting": {"requested": len(wanted), "filled":
                       len(wanted) - unfilled, "unfilled": unfilled,
                       "sources_searched": got["total_sources"]},
        "budget": {"used": _ntok(json.dumps(results)),
                   "estimator": _ENCODING},
    }


# ------------------------------------------------------------------ export


async def export_data(
    page: str,
    path: str | None = None,
    location: dict | None = None,
    index: int | None = None,
    format: str = "csv",
    max_rows: int = 5000,
) -> dict:
    """Export a table to a CSV or JSON file and hand back the path, not the
    data, so a ten-thousand-row table moves to disk for tens of tokens
    instead of through the transcript. The extraction is the same
    deterministic spanned-grid walk get_table uses; the file lands in the
    scoped downloads directory unless a path is named, every write is
    checked against KS4WEB_ALLOWED_ROOTS, and the payload returns the saved
    path, the row and column counts, and any clipping, which is the honest
    receipt. A CSV written here opens directly in Excel or KS4XL, which is
    the family handoff this pack exists for.
    """
    if format not in ("csv", "json"):
        raise BadParams(
            f"unknown format {format!r}: the formats are 'csv' and 'json'.")
    sess, record = common.locate(page)
    got = await _table_data(sess, record, location, index,
                            start_row=0, max_rows=max_rows)
    truncated = got["next_start_row"] is not None
    out = path or str(common.downloads_dir()
                      / f"table_{common.stamp()}.{format}")
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        if any(got["headers"]):
            writer.writerow(got["headers"])
        writer.writerows(got["rows"])
        saved = common.write_text_file(out, buf.getvalue(),
                                       "export table data")
    else:
        body = json.dumps({k: got[k] for k in
                           ("kind", "caption", "headers", "rows",
                            "total_rows")}, indent=2, ensure_ascii=False)
        saved = common.write_text_file(out, body, "export table data")
    return {
        "page": record.handle, "session": sess.session_id,
        "saved_to": saved, "format": format,
        "rows_written": len(got["rows"]), "columns": got["columns"],
        "total_rows": got["total_rows"],
        "truncated": (f"the table holds {got['total_rows']} rows and only "
                      f"the first {len(got['rows'])} were written; raise "
                      f"max_rows to take them all" if truncated else False),
        "accounting": {"spans_expanded": got["spans_expanded"],
                       "clipped_cells": got["clipped_cells"]},
    }


#: The pack roster, in DESIGN 2.2 order. `server.register_all` registers
#: exactly this when the extract pack is selected.
TOOLS = (get_table, get_list, get_links, get_metadata, extract_fields,
         export_data)
