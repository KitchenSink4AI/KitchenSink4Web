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
import re
import time
from urllib.parse import urlparse

from .. import envelope as _envelope
from .. import pagedata as _pagedata
from ..errors import (AmbiguousLocation, BadParams, RangeOutOfBounds,
                      TargetNotFound)
from ..policy import budgets as _budgets
from ..policy import credentials as _credentials
from ..policy import engine as _policy
from ..projection import instrument as _instrument, ntok as _ntok, read_text
from ..projection import read_article as _read_article
from ..projection import read_schema as _read_schema
from ..projection.meter import ENCODING_NAME as _ENCODING
from . import act as _act
from . import common
from . import lite as _lite
from . import resource as _resource

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
        # A caption is page-authored, so the listing rides the envelope
        # (gauntlet 4, G4-08 class sweep).
        listing = "; ".join(
            f'index={t["index"]} {t["kind"]} "{t["caption"] or "(uncaptioned)"}"'
            f' ({t["rows"]} rows)' for t in got["choose"])
        raise AmbiguousLocation(
            f'this page has {got["count"]} data tables and none was named; '
            f'no tool acts on first match. Pass index=N or a location:\n'
            + _pagedata.wrap_line(listing, url=record.page.url))
    return got


#: The token ceiling `get_table` holds, matching `get_page_view`'s default.
#:
#: HOSTILE H-03, the only finding in that round that could end a caller's
#: session in one call. The tool was bounded by ROWS only (`max_rows=50`)
#: and by nothing else, so the PAGE chose the payload size: a 200x1000
#: table came back as 254,185 tokens from one default call, reproduced to
#: the token on both runs. Its own `budget` block reported a spend against
#: NO STATED LIMIT, while `get_page_view` on the same corpus reported
#: `{"used": ..., "limit": 5000, "margin_held": 500}` and held it, and
#: `get_list` and `get_links` came back at 1,415 and 1,322 tokens against
#: 50,000 items and 100,000 links. One tool with no budget, not a policy.
TABLE_BUDGET_TOKENS = 5000

#: The floor a caller may set. Below this a table cannot say anything
#: useful, and a budget nobody can meet is a refusal wearing a number.
TABLE_BUDGET_FLOOR = 500


async def get_table(
    page: str,
    location: dict | None = None,
    index: int | None = None,
    start_row: int = 0,
    max_rows: int = 50,
    budget_tokens: int = TABLE_BUDGET_TOKENS,
    max_columns: int | None = None,
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
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="get_table")
    sess.counters["reads"] += 1
    budget = int(budget_tokens or TABLE_BUDGET_TOKENS)
    if budget < TABLE_BUDGET_FLOOR:
        raise RangeOutOfBounds(
            f"budget_tokens {budget} is below the floor of "
            f"{TABLE_BUDGET_FLOOR}: a table read that small cannot carry a "
            f"header row and a data row, so it would report a shape rather "
            f"than a table. Ask for {TABLE_BUDGET_FLOOR} or more, or read "
            f"fewer rows with max_rows.")
    got = await _table_data(sess, record, location, index, start_row, max_rows)
    table = {k: got[k] for k in
             ("kind", "caption", "columns", "headers", "total_rows",
              "start_row", "rows", "next_start_row")}
    # THE COLUMN BOUND (hostile H-03). Rows were bounded and columns were
    # not, so a page could pick the payload size. Trimming reports what it
    # trimmed; a trim nobody is told about is the completeness lie this
    # product exists to refuse.
    trim = _fit_table(table, budget, max_columns)
    more = (f'get_table(page="{record.handle}", '
            f'start_row={table["next_start_row"]}'
            + (f', index={index}' if index is not None else '')
            + ') returns the next rows'
            if table["next_start_row"] is not None
            else "all rows in the table are included")
    if trim.get("columns_dropped"):
        more += (f'. {trim["columns_dropped"]} of {trim["columns_total"]} '
                 f'column(s) are NOT in this payload: the grid was trimmed '
                 f'to hold the token budget. Raise budget_tokens, or name '
                 f'max_columns and page through the table by row with a '
                 f'narrower grid')
    payload = {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "table": table,
        "continue": more,
        "accounting": {
            "spans_expanded": got["spans_expanded"],
            "clipped_cells": got["clipped_cells"],
            **trim,
            "note": ("merged cells are expanded: a value spanning rows or "
                     "columns is repeated into every position it covers, "
                     "which is what keeps later columns aligned"),
        },
    }
    payload["budget"] = {"used": _ntok(json.dumps(payload["table"])),
                         "limit": budget, "estimator": _ENCODING}
    return payload


def _fit_table(table: dict, budget: int, max_columns: int | None) -> dict:
    """Trim a grid's COLUMNS until it fits the budget, and say what went.

    Columns are trimmed from the right, which is where a wide table puts
    its least-load-bearing fields and, more to the point, is deterministic:
    a caller paging by row must get the same columns every call."""
    headers = list(table.get("headers") or [])
    rows = list(table.get("rows") or [])
    total = len(headers) or max((len(r) for r in rows), default=0)
    keep = total
    if max_columns is not None:
        keep = max(1, min(keep, int(max_columns)))

    def apply(n: int) -> None:
        if headers:
            table["headers"] = headers[:n]
        table["rows"] = [row[:n] for row in rows]
        table["columns"] = n

    apply(keep)
    # Halve until it fits. A linear walk down a 1,000-column grid would be
    # a thousand tokenizer runs, and this is a bound, not a fit.
    while keep > 1 and _ntok(json.dumps(table)) > budget:
        keep = max(1, keep // 2)
        apply(keep)
    if keep >= total:
        return {"columns_total": total, "columns_dropped": 0}
    dropped_names = [str(h) for h in headers[keep:keep + 6]]
    return {
        "columns_total": total,
        "columns_returned": keep,
        "columns_dropped": total - keep,
        "first_dropped_headers": dropped_names,
        "trim": ("columns were dropped from the right to hold the token "
                 "budget; the row count and every value returned are "
                 "unchanged"),
    }


# ------------------------------------------------------------------- lists

_LIST_JS = r"""
(arg) => {
// @@KS4WEB_HREF@@
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
    // ksHref, not link.href (fuzzer class 10): an SVG anchor's href is an
    // SVGAnimatedString and stringifying it fabricates a URL.
    if (link) { try { const u = new URL(ksHref(link), location.href); rec.href = u.pathname + u.search; } catch (e) { rec.href = link.getAttribute('href'); } }
    return rec;
  });
  return {
    tag: target.tagName.toLowerCase(),
    total_items: items.length, start_index: start, items: out,
    next_start_index: start + limit < items.length ? start + limit : null,
  };
}
"""
# The shared href reader is SPLICED, not duplicated (fuzzer class 10). These
# two blocks carry no instrument prelude, so the marker is all they need.
_LIST_JS = _instrument(_LIST_JS)


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
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="get_list")
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
        # The first item of each list is page text, so the listing rides the
        # envelope (gauntlet 4, G4-08 class sweep).
        listing = "; ".join(
            f'index={c["index"]} <{c["tag"]}> {c["items"]} items, first: '
            f'"{c["first"]}"' for c in got["choose"])
        raise AmbiguousLocation(
            f'this page has {got["count"]} candidate lists and none was '
            f'named; no tool acts on first match. Pass index=N or a '
            f'location:\n'
            + _pagedata.wrap_line(listing, url=record.page.url))
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
// @@KS4WEB_HREF@@
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
    // THE ATTRIBUTE, NOT THE PROPERTY, FOR SVG (fuzzer class 10). An SVG
    // `<a>` exposes `href` as an SVGAnimatedString rather than a string,
    // and stringifying the DOM property produced
    // "/[object%20SVGAnimatedString]": a plausible-looking URL that was
    // fabricated, presented as fact, with no flag on it. The attribute is
    // the page's own text either way, so resolving from it is correct for
    // HTML anchors too.
    try {
      const u = new URL(ksHref(a), location.href);
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
_LINKS_JS = _instrument(_LINKS_JS)


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
    kind = common.enum_arg(kind, kinds, default="all", tool="get_links",
                           name="kind")
    limit = common.count_arg(limit, name="limit", tool="get_links",
                             default=40, maximum=5000)
    if kind not in kinds:
        raise BadParams(f"unknown kind {kind!r}; the kinds are {list(kinds)}.")
    sess, record = common.locate(page)
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="get_links")
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
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="get_metadata")
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


#: The floor a substring match has to clear ON BOTH SIDES.
#:
#: `_norm` strips everything that is not alphanumeric, so a source key of
#: `"t)"` normalizes to `"t"`, and the length guard used to be on the NEEDLE
#: only: `len(n) > 3 and norm in n`. One character is a substring of almost
#: every field description in existence, so on the frozen Wikipedia
#: Versailles page the field `price` with the hint "the current price"
#: matched the key `"t)"` and confidently returned "destroyers" at
#: `match: partial` — and returned the same value for `published`. A
#: confident wrong answer from a read tool is the one failure this
#: product's whole doctrine exists to forbid.
#:
#: Four is the floor because it is the shortest string that carries a word:
#: `date`, `isbn`, `name`, `type`. Anything shorter still matches EXACTLY,
#: which is the match that needs no guard.
PARTIAL_MIN_CHARS = 4

#: How much of the longer string the shorter one has to account for before
#: a substring hit is evidence rather than a coincidence. `price` inside
#: `pricecurrency` is 0.38 and is a real hit; `t` inside `thecurrentprice`
#: is 0.07 and is noise. Deliberately permissive, because the FLOOR above
#: is what kills the defect and this is the second line.
PARTIAL_MIN_COVERAGE = 0.2


def _partial_matches(needle: str, by_norm: dict) -> list[tuple]:
    """Every source key that partially matches `needle`, best first.

    BOTH strings clear `PARTIAL_MIN_CHARS` and the overlap clears
    `PARTIAL_MIN_COVERAGE`. Ranked by coverage, then by overlap length,
    then alphabetically, so the answer does not depend on dict ordering:
    the old `next(...)` returned whichever key the page happened to emit
    first, which made a wrong answer non-reproducible as well as wrong."""
    if len(needle) < PARTIAL_MIN_CHARS:
        return []
    scored = []
    for norm, src in by_norm.items():
        if len(norm) < PARTIAL_MIN_CHARS:
            continue
        if needle in norm:
            overlap, container = len(needle), len(norm)
        elif norm in needle:
            overlap, container = len(norm), len(needle)
        else:
            continue
        coverage = overlap / container if container else 0.0
        if coverage < PARTIAL_MIN_COVERAGE:
            continue
        scored.append((coverage, overlap, norm, src))
    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return scored


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
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="extract_fields")
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
        hit, quality, alternates = None, None, ()
        for needle in needles:
            n = _norm(needle)
            if not n:
                continue
            if n in by_norm:
                hit, quality = by_norm[n], "exact"
                break
            scored = _partial_matches(n, by_norm)
            if scored:
                hit, quality = scored[0][3], "partial"
                alternates = tuple(row[3]["key"] for row in scored[1:4])
                break
        if hit:
            results[name] = {"found": True, "value": hit["value"],
                             "source": hit["by"], "matched_key": hit["key"],
                             "match": quality}
            if alternates:
                # Say when the substring match was not the only one. A
                # partial hit is a guess, and a guess with runners-up is a
                # guess the caller should be able to see.
                results[name]["other_partial_keys"] = list(alternates)
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


# ------------------------------------------------------- the tier ladder
#
# `extract_page` (#3) and `aggregate` (#7) share every line below. The ladder
# is four classes of EVIDENCE tried in order, and the boundary between them is
# "who asserted the relationship between the label and the value": the page's
# machine-readable declaration, the page's HTML semantics, the page's DOM
# structure, or nobody. There is no fifth tier, because the fifth tier is
# guessing, and a confident wrong answer from a read tool is the one failure
# this product's whole doctrine exists to forbid. When in doubt it refuses.

#: The tiers, in ladder order. `page-hint` is collected always and REACHABLE
#: only by naming it, because a class-token match is weak evidence and the
#: default surface must not be able to answer from one.
TIER_ORDER = ("declared", "labeled", "proximate", "page-hint")
TIER_MODES = ("all", "declared", "labeled", "proximate", "page-hint")

#: What `tiers="all"` admits. Tier 4 is deliberately not in it.
_ALL_TIERS = ("declared", "labeled", "proximate")

#: Match qualities, best first. `exact` and `all-words` may consult the field's
#: DESCRIPTION; `partial` consults the field NAME only, and that restriction is
#: a defect rather than a preference: with the description in play, a field
#: `product_name` described as "the product title" partial-matched the source
#: key `title` and returned the DOCUMENT title ("Lamp") instead of the product
#: name. Plausible, wrong, and confidently labeled.
_QUALITY_RANK = {"exact": 3, "all-words": 2, "partial": 1}

#: The floor a partial match clears ON BOTH SIDES, and the reason is
#: `PARTIAL_MIN_CHARS`'s reason one tool along: `_norm` strips everything that
#: is not alphanumeric, so a source key of `"t)"` normalizes to `"t"`, and one
#: character is a substring of almost every field description in existence.
#: Four is the shortest string that carries a word (`date`, `isbn`, `name`).
_PARTIAL_MIN = PARTIAL_MIN_CHARS

#: Function words, stripped from the content-word sets `all-words` compares.
#: Deliberately function words ONLY: `current` and `listed` carry meaning, and
#: stripping them would make "the current price" and "price" the same needle.
_STOPWORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "its", "my", "of", "on", "or", "our", "that", "the", "their",
    "these", "this", "those", "to", "was", "were", "with", "your"))

_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD = re.compile(r"[^0-9A-Za-zÀ-￿]+")

#: The per-value and per-key clips, and the per-tier retention caps. Every one
#: of them is REPORTED when it is hit: a cap nobody is told about is the
#: completeness lie this product exists to refuse.
SCHEMA_CAPS = {
    "key_clip": 90, "value_clip": VALUE_CLIP, "leaves": 6000,
    "declared": 1200, "labeled": 800, "proximate": 800, "hint": 900,
    "json_ld_nodes": 400, "value_shape_max": 120,
}

#: How many competing values an `ambiguous` outcome lists, and how many
#: lower-tier disagreements a filled field carries.
AMBIGUOUS_CANDIDATE_CAP = 6
DISAGREEMENT_CAP = 4

#: The most fields one call will match. A schema larger than this is a
#: different tool's job, and the refusal says so before anything is extracted.
MAX_SCHEMA_FIELDS = 40


def _words(text: str) -> frozenset[str]:
    """The word set of a key or a needle, camelCase split first so
    `priceCurrency` reads as two words rather than one."""
    spaced = _CAMEL_SPLIT.sub(" ", str(text or ""))
    return frozenset(
        part.lower() for part in _NON_WORD.split(spaced) if part)


def _content_words(text: str) -> frozenset[str]:
    return frozenset(w for w in _words(text) if w not in _STOPWORDS)


def _quality(key: str, name: str, description: str):
    """How well one source key answers one schema field: `(quality, extra)` or
    None, where `extra` counts the content words the KEY carries beyond the
    needle it matched.

    THE PARTIAL RULE IS A WORD-BOUNDARY RULE, never a bare substring test.
    `price` is one of `priceCurrency`'s words and that is a real hit; `t` is a
    substring of `thecurrentprice` and that is noise. Requiring both sides to
    clear four characters AND to align on a word boundary is what makes the
    difference structural rather than a threshold the page can sit under.

    `extra` is the SPECIFICITY tie-break and it is not a fudge factor. A
    schema.org Product declares both `offers.price` and `offers.priceCurrency`,
    and a field named `price` is a subset of both word sets, so without a
    tie-break the two compete and every commerce page in the world answers
    `ambiguous` for its own price. A key that says MORE than the field asked
    for is a worse answer to that field than a key that says exactly it, and
    that is a fact about the two keys rather than a confidence estimate. Keys
    that tie on specificity still tie, and a tie still refuses, which is what
    keeps the eight-author page answering `ambiguous`."""
    key_norm, key_words = _norm(key), _words(key)
    key_content = frozenset(w for w in key_words if w not in _STOPWORDS)
    for needle in (name, description):
        if needle and key_norm and _norm(needle) == key_norm:
            return "exact", 0
    for needle in (name, description):
        wanted = _content_words(needle) if needle else frozenset()
        if wanted and wanted <= key_words:
            return "all-words", len(key_content - wanted)
    name_norm, name_words = _norm(name), _words(name)
    if len(key_norm) >= _PARTIAL_MIN and len(name_norm) >= _PARTIAL_MIN:
        if key_norm in name_words or name_norm in key_words:
            return "partial", len(key_content - _content_words(name))
    return None


def _schema_arg(schema) -> dict:
    """The two accepted shapes, and a refusal that shows one of each."""
    if isinstance(schema, dict) and schema:
        wanted = {str(k): str(v or "") for k, v in schema.items()}
    elif isinstance(schema, (list, tuple)) and schema:
        wanted = {str(k): "" for k in schema}
    else:
        raise BadParams(
            "extract_page needs the schema to fill, in one of two shapes: a "
            "list of field names (['price', 'author']), or a dict of name to "
            "a natural-language description ({'price': 'the listed product "
            "price'}). The description sharpens the match and is never "
            "required. Nothing was extracted.")
    if len(wanted) > MAX_SCHEMA_FIELDS:
        raise BadParams(
            f"the schema names {len(wanted)} fields and the cap is "
            f"{MAX_SCHEMA_FIELDS}; no extraction ran. Split the schema across "
            f"calls, or scope the read with location= and ask for less.")
    return wanted


def _tiers_arg(tiers: str) -> tuple[str, ...]:
    mode = (tiers or "all").strip().lower()
    if mode not in TIER_MODES:
        raise BadParams(
            f"unknown tiers mode {tiers!r}. 'all' admits machine-readable "
            f"declarations, HTML-declared label/value relations, and the "
            f"three named structural relations. 'declared' admits only what "
            f"the page states in machine-readable form, which is the mode to "
            f"use when every filled field has to be defensible. 'labeled' and "
            f"'proximate' admit one tier each. 'page-hint' admits class, id, "
            f"and data-testid tokens, which is weak evidence and is why it is "
            f"never included in 'all'.")
    return _ALL_TIERS if mode == "all" else (mode,)


def _is_secret(src: dict) -> bool:
    """Re-derive the secret classification SERVER-SIDE from the descriptor.

    The collector already declines to read a page-classified secret's value;
    this is the authority. `policy/credentials.py` is the one classifier every
    other surface uses, and routing through it is what keeps a field that is
    secret in the projection from being readable here. Payment fields are in
    the never-read set for this tool specifically: a rendered card number is
    exactly the string that must not enter a transcript."""
    if src.get("by") != "form-field":
        return False
    if src.get("secret"):
        return True
    descriptor = {k: src.get(k) for k in
                  ("type", "autocomplete", "name", "label", "attr_id",
                   "placeholder")}
    return (_credentials.is_secret_field(descriptor)
            or _credentials.is_payment_field(descriptor))


def _buckets(raw: dict) -> dict:
    """The collector's four lists, with every secret value struck.

    A secret source stays in its bucket so a field whose only match IS a
    credential can report `secret` rather than `not_found`; what never survives
    is the value."""
    out = {"declared": list(raw.get("declared") or []),
           "labeled": list(raw.get("labeled") or []),
           "proximate": list(raw.get("proximate") or []),
           "page-hint": list(raw.get("hint") or [])}
    for tier, sources in out.items():
        for src in sources:
            src["tier"] = tier
            if _is_secret(src):
                src["secret"] = True
                src["value"] = ""
    return out


def _distinct(hits: list) -> list:
    """The distinct VALUES among a set of equally-good hits, first occurrence
    kept. Whitespace-squashed and case-sensitive: `$1,795.00` and `1795.00` are
    genuinely different strings and pretending otherwise is the tool deciding
    what a page meant."""
    seen, out = set(), []
    for src in hits:
        value = " ".join(str(src.get("value") or "").split())
        if value in seen:
            continue
        seen.add(value)
        out.append(src)
    return out


def _hit_shape(src: dict) -> dict:
    """One filled field's provenance, which is the honest half of the answer.
    A value whose provenance is unstated is worth less than no value: the
    caller cannot check it against the page."""
    out = {"value": src.get("value", ""), "by": src.get("by"),
           "matched_key": src.get("key"), "where": src.get("where") or None}
    if src.get("relation"):
        out["relation"] = src["relation"]
        out["gap_px"] = src.get("gap_px")
    return out


def _disagreements(name: str, desc: str, answer: str, tier: str,
                   enabled: tuple, buckets: dict) -> list:
    """Every LOWER enabled tier that held a different value for this field.

    The tool still answers, because the higher tier is better evidence and
    saying so is not a guess, but it never hides that the page said two things.
    A JSON-LD price of `1795.00` beside a rendered `$1,795.00` is a formatting
    difference and reads as one; a JSON-LD price that disagrees in MAGNITUDE
    with the rendered price is the case a caller has to be told about."""
    out, start = [], TIER_ORDER.index(tier) + 1
    for lower in TIER_ORDER[start:]:
        if lower not in enabled:
            continue
        for src in buckets[lower]:
            if src.get("secret") or not src.get("value"):
                continue
            if not _quality(src["key"], name, desc):
                continue
            if " ".join(src["value"].split()) == " ".join(answer.split()):
                continue
            out.append({"tier": lower, "value": src["value"],
                        "by": src.get("by"), "matched_key": src.get("key")})
            if len(out) >= DISAGREEMENT_CAP:
                return out
    return out


def _hint_note(name: str, desc: str, buckets: dict, enabled: tuple) -> dict:
    """What the page-hint tier holds for a field nothing else answered.

    THE STYLING-ONLY ANSWER IS SILENCE PLUS A FLAG. On a real product page a
    star rating exists only as `class="star-rating Three"` with no text
    anywhere: a human sees three stars and the page never wrote the number.
    Reading it would mean the tool learning one site's private encoding, so it
    stays silent, and it SAYS it stayed silent rather than reporting a bare
    `not_found` that reads as "this page does not have a rating"."""
    if "page-hint" in enabled:
        return {}
    hits = [src for src in buckets["page-hint"]
            if _quality(src["key"], name, desc)]
    if not hits:
        return {}
    styling = [src for src in hits if src.get("styling_only")]
    out = {"page_hint_candidates": len(hits)}
    if len(styling) == len(hits):
        out["styling_only"] = True
        out["styling_note"] = (
            f"this page names something like {name!r} in a class, id, or "
            f"data-testid token on an element that carries NO TEXT, so the "
            f"value exists only as styling. Reading it would mean guessing "
            f"one site's private encoding of its own class names, which this "
            f"tool does not do. The tokens are listed under tiers='page-hint' "
            f"and a screenshot is the honest route to a value only a human "
            f"eye can read.")
    else:
        out["hint_note"] = (
            f"a class, id, or data-testid token names something like "
            f"{name!r}. That is the page's own styling vocabulary rather than "
            f"a declaration, so it is never admitted under tiers='all'; "
            f"tiers='page-hint' returns it and states what it is.")
    return out


_NOT_FOUND_ROUTES = (
    "get_text reads whatever prose is here, get_table reads a tabular layout, "
    "and get_page_view shows what the page actually is.")


def _resolve(name: str, desc: str, enabled: tuple, buckets: dict,
             searched: dict) -> dict:
    """One schema field against the whole ladder. Returns the payload entry.

    Nothing here raises. A page with no match for a field is a normal page and
    the field comes back `found: false` with the reason, which is the contract
    that lets a caller ask five questions of a page that answers two."""
    for tier in TIER_ORDER:
        if tier not in enabled:
            continue
        best, hits = None, []
        for src in buckets[tier]:
            scored = _quality(src["key"], name, desc)
            if not scored:
                continue
            quality, extra = scored
            score = (_QUALITY_RANK[quality], -extra)
            if best is None or score > best:
                best, hits = score, [(quality, src)]
            elif score == best:
                hits.append((quality, src))
        if not hits:
            continue
        quality = hits[0][0]
        sources = [src for _, src in hits]

        if all(src.get("secret") for src in sources):
            # A credential is never read, not read-then-redacted. The routes
            # named are the two CREDENTIAL_REFUSED names and no others.
            return {"found": False, "reason": "secret", "confidence": tier,
                    "note": (
                        f"the only source matching {name!r} on this page is a "
                        f"secret field (a password, a one-time code, or a card "
                        f"number), and a credential never passes through the "
                        f"model's context. Its value was not read. The "
                        f"sanctioned routes are manage_session(action="
                        f"'handoff'), where a human types it in the headed "
                        f"window, and save_auth_state / load_auth_state "
                        f"(storage pack), which move a completed login through "
                        f"a file rather than through the transcript.")}
        sources = [src for src in sources if not src.get("secret")]
        filled = [src for src in sources if src.get("value")]
        if not filled and all(src.get("styling_only") for src in sources):
            # A CLASS TOKEN WITH NO TEXT IS NOT AN EMPTY FIELD. `star-rating
            # Three` on an element carrying no text is a value that exists only
            # as styling, and calling it `empty` would say the page has a
            # rating and left it blank. It does not: it drew it.
            entry = {"found": False, "reason": "not_found",
                     "searched": dict(searched)}
            entry.update(_hint_note(name, desc, buckets, ()))
            entry["note"] = (
                f"{name!r} matches a class, id, or data-testid token on this "
                f"page and that element carries no text at all, so there is "
                f"no value to return at any tier. {_NOT_FOUND_ROUTES}")
            return entry
        if not filled:
            # "the page has this field and it is blank" and "the page does not
            # have this field" are different facts about a page.
            src = sources[0]
            return {"found": False, "reason": "empty", "confidence": tier,
                    "match": quality, "by": src.get("by"),
                    "matched_key": src.get("key"),
                    "where": src.get("where") or None,
                    "note": (f"the page carries a source for {name!r} and its "
                             f"value is empty. An unfilled form field is the "
                             f"common case; this is not the same fact as the "
                             f"page not having the field at all.")}
        distinct = _distinct(filled)
        if len(distinct) > 1:
            # THE LISTING-PAGE ANSWER. Returning the first of eight authors
            # would be a first-match answer, which is the thing no tool in this
            # codebase does.
            return {
                "found": False, "reason": "ambiguous", "confidence": tier,
                "match": quality, "rivals": len(distinct),
                "candidates": [
                    {"value": src["value"], "by": src.get("by"),
                     "matched_key": src.get("key"),
                     "where": src.get("where") or None}
                    for src in distinct[:AMBIGUOUS_CANDIDATE_CAP]],
                "note": (
                    f"{len(distinct)} distinct values matched {name!r} equally "
                    f"well at the {tier} tier, so this page holds repeated "
                    f"records rather than one. No tool here answers on first "
                    f"match. Scope the call to one record with location= (a "
                    f"ref, region, form, or table from get_page_view or "
                    f"find_elements) and ask again."
                    + (f" {len(distinct) - AMBIGUOUS_CANDIDATE_CAP} further "
                       f"candidate(s) are not listed."
                       if len(distinct) > AMBIGUOUS_CANDIDATE_CAP else ""))}
        answer = distinct[0]
        out = {"found": True, "confidence": tier, "match": quality,
               **_hit_shape(answer)}
        clash = _disagreements(name, desc, answer.get("value", ""), tier,
                               enabled, buckets)
        if clash:
            out["conflict"] = True
            out["disagreement"] = clash
            out["conflict_note"] = (
                f"a lower evidence tier on this page holds a different value "
                f"for {name!r}. The answer above is the higher tier's, because "
                f"a machine-readable declaration is better evidence than a "
                f"rendering, and both are shown so the choice is yours rather "
                f"than the tool's.")
        return out
    entry = {"found": False, "reason": "not_found",
             "searched": dict(searched),
             "note": (f"no source on this page matched {name!r} at any "
                      f"admitted tier. {_NOT_FOUND_ROUTES}")}
    entry.update(_hint_note(name, desc, buckets, enabled))
    return entry


def _render_fields(fields: dict) -> str:
    """The page-authored half of the payload, rendered into the one block the
    envelope wraps. Keys, values, candidate listings, and element descriptors
    are all the page's own strings and all travel inside the delimiters."""
    lines = []
    for name, entry in fields.items():
        if entry.get("found"):
            lines.append(f'{name} = {entry["value"]}')
            lines.append(f'  from key "{entry["matched_key"]}"'
                         f' ({entry["by"]}'
                         + (f', {entry["where"]}' if entry.get("where") else '')
                         + ')')
            for clash in entry.get("disagreement") or []:
                lines.append(f'  {clash["tier"]} tier says: {clash["value"]}'
                             f' (key "{clash["matched_key"]}")')
        elif entry.get("reason") == "ambiguous":
            lines.append(f'{name} = (ambiguous, {entry["rivals"]} candidates)')
            for cand in entry["candidates"]:
                lines.append(f'  "{cand["matched_key"]}" -> {cand["value"]}'
                             + (f' ({cand["where"]})' if cand.get("where")
                                else ''))
        elif entry.get("reason") == "empty":
            lines.append(f'{name} = (empty, key "{entry["matched_key"]}")')
        else:
            lines.append(f'{name} = ({entry.get("reason")})')
    return "\n".join(lines)


async def _schema_read(sess, record, location, schema, tiers):
    """The shared body of `extract_page` and one `aggregate` row.

    Everything both tools do to ONE page lives here, so the batch tool cannot
    drift from the single-page tool: same collector, same ladder, same refusal
    contract, same accounting."""
    wanted = _schema_arg(schema)
    enabled = _tiers_arg(tiers)
    from .lite import _scope_root
    root = _scope_root(sess, record, location)
    raw = await _read_schema(record.page, root=root, caps=SCHEMA_CAPS)
    if raw.get("error") == "ROOT_GONE":
        raise TargetNotFound(
            f'location named {raw["asked_for"]!r} and that ref is not on '
            f'{record.handle} any more: the page moved on. Re-read the page '
            f'and use the ref that read returns.')
    buckets = _buckets(raw)
    searched = {tier: len(buckets[tier]) for tier in TIER_ORDER}
    fields = {name: _resolve(name, desc, enabled, buckets, searched)
              for name, desc in wanted.items()}
    counts = raw.get("counts") or {}
    tally = {"filled": 0, "not_found": 0, "ambiguous": 0, "empty": 0,
             "secret": 0, "conflicts": 0}
    for entry in fields.values():
        if entry.get("found"):
            tally["filled"] += 1
        else:
            tally[entry.get("reason", "not_found")] += 1
        if entry.get("conflict"):
            tally["conflicts"] += 1
    accounting = {
        "requested": len(wanted), **tally,
        "sources_searched": searched,
        "tiers_admitted": list(enabled),
        "tiers_withheld": [t for t in TIER_ORDER if t not in enabled],
        "scope": "one subtree" if raw.get("scoped") else "the whole page",
        "elements_walked": counts.get("walked", 0),
        "leaves_scanned": counts.get("leaves_scanned", 0),
        "hidden_values_excluded": counts.get("hidden_values_excluded", 0),
        "secret_fields_never_read": counts.get("secret_fields", 0),
        "shadow_roots_read": counts.get("shadow_roots_read", 0),
        "json_ld": {"blocks": counts.get("json_ld_blocks", 0),
                    "invalid": counts.get("json_ld_invalid", 0),
                    "nodes_walked": counts.get("json_ld_nodes", 0)},
        "note": ("no model is consulted and nothing is read out of prose: a "
                 "price mentioned in a paragraph is not this page's price. "
                 "The same page and schema always answer the same way."),
    }
    if raw.get("capped"):
        accounting["capped"] = {
            "dropped": raw["capped"],
            "why": ("the per-tier retention caps were reached and the sources "
                    "past them are NOT in the search above. Scope the read "
                    "with location= to search a subtree exhaustively rather "
                    "than the whole page partially."),
        }
    if raw.get("scoped"):
        accounting["scope_note"] = (
            "this read was scoped to one subtree, so page-level declarations "
            "(the document title, head meta tags, and JSON-LD outside the "
            "subtree) were not searched.")
    return fields, accounting, raw


async def extract_page(
    page: str,
    schema: dict | list,
    location: dict | None = None,
    tiers: str = "all",
) -> dict:
    """FLAGGED: placeholder wording, composed mechanically from the spec's
    FACTS TO CONVEY. The author or the main thread writes the shipped prose.

    Read the rendered page against a caller-named schema. Four evidence tiers
    are tried in order: machine-readable declarations (JSON-LD, meta tags,
    microdata, RDFa), HTML-declared label and value relations (definition
    lists, two-cell table rows, labeled form fields, aria-labels), three named
    structural relations between a visible label and a value, and page-authored
    class or testid tokens, which are off unless named. Every filled field
    states which tier, which source class, and which of the page's own keys
    produced it. No model is consulted, so the same page and schema always
    answer the same way. A field with no match returns not_found with the count
    of what was searched. A field with several equally-good competing values
    returns ambiguous with the candidates listed rather than the first one.
    Secret fields are never read. Prose is never mined: a price mentioned in a
    paragraph is not this page's price.
    """
    sess, record = common.locate(page)
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="extract_page")
    sess.counters["reads"] += 1
    fields, accounting, raw = await _schema_read(
        sess, record, location, schema, tiers)
    # Every extracted value, every matched key, and every candidate in an
    # ambiguous outcome is PAGE-AUTHORED, and this is the single most direct
    # injection channel the tool has: a schema-extraction tool exists to lift
    # page strings into the caller's reasoning.
    wrapped, note = _pagedata.wrap(_render_fields(fields), url=record.page.url)
    note["label"] += (
        " The structured fields beside this block carry the same content and "
        "exactly the same status: the values, the page's own keys, the "
        "element descriptors, and every candidate listed in an ambiguous "
        "outcome are all page-authored.")
    payload = {
        "page": record.handle, "session": sess.session_id,
        "url": record.page.url,
        "scope": location if location else "the whole page",
        "fields": fields,
        "fields_text": wrapped,
        "page_data": note,
        "accounting": accounting,
    }
    payload["budget"] = {"used": _ntok(json.dumps(fields)),
                         "estimator": _ENCODING}
    return payload


# --------------------------------------------------------------- aggregate

#: The hard ceiling on one batch. Above it the call REFUSES rather than
#: clamping: a caller who asks for 80 URLs and silently gets 50 has been given
#: a dataset that is missing 30 rows it believes are there, which is the
#: completeness lie in miniature.
AGGREGATE_URL_CEILING = 50

#: What the DEFAULT batch is derived from. A constant default is a guess about
#: a budget it cannot see; one fifth of the session's navigation limit affords
#: five full batches, and it tracks the limit when a deployment moves it. With
#: the shipped limit of 150 navigations this is 30.
AGGREGATE_BUDGET_DIVISOR = 5

#: Per-URL error codes that belong in that URL's slot rather than in a raise.
#: One dead host is not a dead batch.
_PER_URL_CODES = frozenset({
    "BLOCKED_BY_SITE", "AUTH_REQUIRED", "PAGE_UNREACHABLE",
    "NAVIGATION_BLOCKED", "NAVIGATION_FAILED", "TIMEOUT",
    "UNSUPPORTED_CONTENT", "DRIVER_FAILURE", "NOT_FOUND",
    "READ_ONLY_MODE", "CONFIRMATION_REQUIRED", "RANGE_OUT_OF_BOUNDS",
})


def default_batch_size() -> int:
    """The default `max_urls`, derived from the session navigation budget."""
    return max(1, min(AGGREGATE_URL_CEILING,
                      _budgets.limit("navigations") // AGGREGATE_BUDGET_DIVISOR))


def _aggregate_preflight(urls, max_urls) -> tuple[list[str], int]:
    """Validate the WHOLE list before any navigation, and name every bad entry
    at once. A batch tool that refuses on the first bad URL makes the caller
    discover a five-typo list five calls at a time."""
    if not isinstance(urls, (list, tuple)) or not urls:
        raise BadParams(
            "aggregate needs a non-empty list of URLs to visit, in the order "
            "you want them visited. Nothing was navigated.")
    cap = default_batch_size() if max_urls is None else int(max_urls)
    if cap < 1 or cap > AGGREGATE_URL_CEILING:
        raise BadParams(
            f"max_urls={max_urls} is outside 1 to {AGGREGATE_URL_CEILING}. "
            f"The ceiling is a real bound rather than a clamp: a batch that "
            f"silently returned {AGGREGATE_URL_CEILING} of the URLs asked for "
            f"would be a dataset missing rows the caller believes are in it. "
            f"The default on this server is {default_batch_size()}, which is "
            f"one fifth of the session navigation budget of "
            f"{_budgets.limit('navigations')}. Nothing was navigated.")
    bad = []
    cleaned = []
    for i, url in enumerate(urls):
        text = str(url or "").strip()
        try:
            checked = _lite._validated_url(text)
        except Exception as exc:
            bad.append(f"[{i}] {text!r}: {str(exc)[:120]}")
            continue
        # THE SCHEME CHECK IS PRE-FLIGHT HERE, and not because `approve()`
        # would miss it: the origin policy denies a non-web scheme at the
        # choke point and would put NAVIGATION_BLOCKED in that URL's slot. A
        # `file:///` in a list of product pages is an argument mistake rather
        # than a site condition, though, and the whole point of validating the
        # list first is that the caller learns about all of them at once
        # instead of finding a fifth typo on the fifth call.
        if urlparse(checked).scheme.lower() not in ("http", "https"):
            bad.append(f"[{i}] {text!r}: aggregate visits http(s) URLs only, "
                       f"and this names another scheme")
            continue
        cleaned.append(checked)
    if bad:
        raise BadParams(
            f"{len(bad)} of {len(urls)} URL(s) are not navigable and the "
            f"whole list is checked before anything is visited, so ZERO "
            f"navigations happened: " + "; ".join(bad[:8])
            + (f"; and {len(bad) - 8} more" if len(bad) > 8 else "")
            + ". Fix them and resend the list.")
    if len(cleaned) > cap:
        raise BadParams(
            f"the list holds {len(cleaned)} URLs and max_urls is {cap}, so "
            f"nothing was navigated. Raise max_urls (the ceiling is "
            f"{AGGREGATE_URL_CEILING}) or send the list in batches; each hop "
            f"is charged against the session navigation budget exactly as a "
            f"separate navigate call would be.")
    return cleaned, cap


#: The one driver string that means NO REQUEST WAS MADE. A failed hop leaves
#: Chromium committing `chrome-error://chromewebdata` asynchronously, and the
#: next `goto` issued while that commit is in flight is refused before it
#: touches the network. Retrying it once is the same hop rather than a second
#: one, which is why it is not charged again and why the retry is bounded to a
#: single attempt on this exact string.
_INTERRUPTED = "interrupted by another navigation"


async def _goto_once(record, url, timeout_ms):
    """One hop, with the dead-neighbour retry and nothing else."""
    try:
        return await record.page.goto(
            url, wait_until="load", timeout=timeout_ms)
    except Exception as exc:
        if _INTERRUPTED not in str(exc).lower():
            raise
        try:
            await record.page.wait_for_load_state("load", timeout=2000)
        except Exception:                               # noqa: BLE001
            pass
        return await record.page.goto(
            url, wait_until="load", timeout=timeout_ms)


async def _aggregate_one(sess, record, url, schema, tiers, wait,
                         per_url_timeout_ms) -> dict:
    """One URL, in the order that IS the contract. Raises on its own failures;
    the caller decides which raise is a slot and which is the batch."""
    # 1. The choke point, BEFORE the driver is touched: origin policy, 429
    #    backoff, loop detection, and the navigation budget, charged per URL
    #    exactly as if the caller had issued N navigate calls. A walk is not a
    #    way around a budget.
    _policy.approve(_policy.ActionRequest(
        tool="aggregate", kind="navigate", session=sess.session_id,
        page=record.handle, url=url, args={"action": "goto", "url": url},
        summary=f"aggregate visits {url} on {record.handle}"))
    before = record.page.url
    started = time.monotonic()
    try:
        response = await _goto_once(record, url, per_url_timeout_ms)
    except Exception as exc:
        _lite._raise_if_unreachable(exc, "aggregate", record)
        raise
    record.touch(record.page.url)
    sess.counters["navigations"] += 1
    _lite.note_origin(sess, record.page.url)
    if record.page.url != before:
        sess.invalidate_page(record.handle, f"aggregate navigated from {before}")
    # 2. The landed check: a redirect onto a denied origin aborts THIS URL
    #    rather than laundering its content into the dataset.
    await _lite._landed_origin_check(sess, record, tool="aggregate")
    status = response.status if response is not None else None
    try:
        headers = dict(response.headers) if response is not None else None
    except Exception:
        headers = None
    # 3. A site that said 429 stays said, and every LATER URL on that domain
    #    then refuses in its own slot through the choke point rather than
    #    hammering the host.
    if status == 429:
        raw_retry = (headers or {}).get("retry-after", "").strip()
        _budgets.BOOK.note_429(
            urlparse(record.page.url).hostname or "",
            float(raw_retry) if raw_retry.replace(".", "", 1).isdigit()
            else None)
    # 4. The wall verdict, before one character of the page is read.
    verdict = await _lite._wall_verdict(record.page, status, headers=headers)
    if verdict.get("wall") == "auth-wall":
        raise _lite._auth_refusal(record.page.url, verdict.get("marker"))
    if verdict.get("wall"):
        raise _lite._blocked_refusal(sess, record.page.url, status, verdict)
    # 5. The optional wait, through wait_for's own precheck-then-wait path.
    if wait:
        if not isinstance(wait, dict) or not wait.get("condition"):
            raise BadParams(
                "wait must be one wait_for spec: {'condition': 'text', "
                "'value': 'In stock'}. The conditions are the ones wait_for "
                "names, and the same spec is applied to every URL.")
        await _lite.wait_for(
            page=record.handle, condition=wait["condition"],
            value=wait.get("value"), location=wait.get("location"),
            timeout_ms=int(wait.get("timeout_ms") or per_url_timeout_ms))
    # 6. A URL that landed on a PDF is REPORTED as such rather than extracted
    #    as if it were HTML.
    held = await _resource.probe_page(record.page)
    slot = {"url": record.page.url, "ok": True, "status": status,
            "timing_ms": int((time.monotonic() - started) * 1000)}
    if verdict.get("wall") is None and verdict.get("status") is not None:
        slot["verdict"] = verdict
    if held is not None:
        slot["ok"] = False
        slot["error"] = {
            "code": "UNSUPPORTED_CONTENT",
            "message": _resource.navigate_note(held)["why"],
            "hint": _resource.escape_route(held)}
        return slot
    sess.counters["reads"] += 1
    fields, accounting, _raw = await _schema_read(
        sess, record, None, schema, tiers)
    slot["fields"] = fields
    slot["accounting"] = accounting
    return slot


def _rollup(schema_names, results) -> dict:
    """The per-field roll-up, COMPUTED rather than claimed. "price filled on 18
    of 20, ambiguous on 2" is the answer a competitive scan actually wants, and
    it is the number the caller would otherwise have to walk the slots for."""
    per_field = {name: {"filled": 0, "not_found": 0, "ambiguous": 0,
                        "empty": 0, "secret": 0} for name in schema_names}
    total = 0
    for slot in results:
        for name, entry in (slot.get("fields") or {}).items():
            row = per_field.setdefault(
                name, {"filled": 0, "not_found": 0, "ambiguous": 0,
                       "empty": 0, "secret": 0})
            if entry.get("found"):
                row["filled"] += 1
                total += 1
            else:
                key = entry.get("reason", "not_found")
                row[key] = row.get(key, 0) + 1
    return {"fields_filled_total": total, "per_field": per_field}


async def aggregate(
    urls: list,
    schema: dict | list,
    page: str | None = None,
    wait: dict | None = None,
    tiers: str = "all",
    max_urls: int | None = None,
    per_url_timeout_ms: int = 30000,
) -> dict:
    """FLAGGED: placeholder wording, composed mechanically from the spec's
    FACTS TO CONVEY. The author or the main thread writes the shipped prose.

    Visit each URL in turn, wait if a wait is named, and extract the same
    schema from each, returning one dataset with a slot per URL in the order
    they were given. A URL that fails carries its typed error in its own slot
    and the batch continues; the summary states how many succeeded and how many
    failed, so the dataset never reads as complete when it is not. Each hop is
    charged against the session's navigation and origin budgets exactly as
    separate calls would be. A site that answers 429 stops later hops to that
    host. Exhausting a budget part way through returns the results already
    collected rather than discarding them. One page handle is reused for the
    whole walk, so refs and read tokens minted before the call are gone
    afterwards.
    """
    cleaned, cap = _aggregate_preflight(urls, max_urls)
    _schema_arg(schema)                       # refuse a bad schema pre-flight
    _tiers_arg(tiers)
    auto_session = None
    if page is None:
        if not _lite.MANAGER.sessions:
            opened = await _lite.MANAGER.open()
            auto_session = (
                f"no session was open, so aggregate opened one: "
                f"{opened.session_id} ({opened.spec.label}, headless).")
        page = _lite.MANAGER.session(None).focused
    sess, record = common.locate(page)
    # THE PRE-FLIGHT BUDGET ADVISORY, and it is an advisory rather than a
    # refusal on purpose: a caller may legitimately want as many URLs as fit.
    # Nothing is silently truncated either; the number is simply stated.
    snapshot = _budgets.BOOK.snapshot(sess.session_id)
    left = (snapshot["limits"]["navigations"]
            - snapshot["counters"]["navigations"])
    budget_note = None
    if left < len(cleaned):
        budget_note = (
            f"this session has {left} navigation(s) left of "
            f"{snapshot['limits']['navigations']} and the batch asks for "
            f"{len(cleaned)}, so roughly {max(0, left)} URL(s) are affordable "
            f"before the budget trips. Nothing is truncated here: the walk "
            f"runs until the budget refuses, and that refusal carries every "
            f"row collected up to it.")
    results, stopped = [], None
    for url in cleaned:
        try:
            results.append(await _aggregate_one(
                sess, record, url, schema, tiers, wait, per_url_timeout_ms))
            continue
        except Exception as exc:                        # noqa: BLE001
            code = getattr(exc, "code", None) or _envelope.classify(exc)
            if code not in _PER_URL_CODES:
                # LOSING TWELVE SUCCESSFUL EXTRACTIONS BECAUSE THE THIRTEENTH
                # URL exhausted a budget is the failure mode this clause
                # exists to prevent. `envelope.refusal` reads `detail` off the
                # exception, so the partial dataset rides out WITH the refusal
                # instead of being discarded. Every batch-stopping raise gets
                # it, not only the budget one: whatever ended the walk, the
                # rows already collected belong to the caller.
                try:
                    exc.detail = {
                        "partial_results": results,
                        "requested": len(cleaned),
                        "completed": len(results),
                        "stopped_on": url,
                        "note": ("the batch stopped here and the rows already "
                                 "collected are attached and complete. They "
                                 "cover only the URLs listed in them."),
                    }
                except Exception:       # an exception with no attribute dict
                    pass
                raise
            # THE PER-URL ERROR IS THE TOP-LEVEL ERROR'S SHAPE, built by the
            # same function, so the caller has ONE parsing path for a refusal
            # wherever it happened.
            slot = {"url": url, "ok": False,
                    "error": _envelope.refusal(exc)["error"]}
        # A FAILED HOP LEAVES A PAGE MID-FAILURE, and the driver then refuses
        # the NEXT hop with "navigation is interrupted by another navigation
        # to chrome-error://chromewebdata". One dead URL taking the two after
        # it down is the batch-sinking this whole tool is built not to do, so
        # the page is parked to a known document before the walk continues.
        try:
            await _lite._park_to_blank(
                sess, record,
                f"aggregate parked the page after {url} failed")
        except Exception:                               # noqa: BLE001
            pass
        results.append(slot)
    succeeded = sum(1 for slot in results if slot.get("ok"))
    failed = len(results) - succeeded
    wrapped, note = _pagedata.wrap(
        "\n\n".join(
            f'--- {slot["url"]}\n' + _render_fields(slot.get("fields") or {})
            for slot in results if slot.get("ok")),
        url=record.page.url,
        frames=[{"fid": f'url[{i}]', "provenance": slot["url"]}
                for i, slot in enumerate(results) if slot.get("ok")] or None)
    note["label"] += (
        " Each row in this payload came from a DIFFERENT document, listed "
        "above, and the structured fields beside this block carry the same "
        "content with exactly the same status.")
    payload = {
        "session": sess.session_id, "page": record.handle,
        "requested": len(cleaned), "succeeded": succeeded, "failed": failed,
        "results": results,
        "summary": _rollup(list(_schema_arg(schema)), results),
        "dataset_text": wrapped,
        "page_data": note,
        "stopped": stopped,
        "continue": (
            f"this dataset covers the {succeeded} URL(s) whose slot says "
            f"ok=true and NOT the {failed} that failed; each failure carries "
            f"its own typed error in its own slot, in input order."
            if failed else
            f"every one of the {succeeded} URL(s) asked for is in this "
            f"dataset."),
        "refs": ("this walk navigated, so refs and read tokens minted before "
                 "it are gone; read the page you are on to mint fresh ones"),
    }
    if auto_session:
        payload["auto_session"] = auto_session
    payload["budget"] = {
        "used": _ntok(json.dumps([slot.get("fields") for slot in results])),
        "estimator": _ENCODING,
        "navigations_charged": len(results),
        **({"advisory": budget_note} if budget_note else {}),
    }
    return payload


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
    # The read gate (gauntlet 4, G4-04/05/06); an export is a content read
    # that happens to land on disk.
    await _lite._read_gate(sess, record, tool="export_data")
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


# ----------------------------------------------------------------- article


def _field(label: str, got: dict) -> str:
    """One metadata line, with WHERE it came from. A byline whose provenance
    is unstated is worth less than no byline: the caller cannot tell the
    page's author from the site's owner, and both live in the same markup."""
    if not got["value"]:
        return f"{label}: not marked up on this page"
    return f'{label}: {got["value"]} (from {got["source"]})'


def _tally(by_reason: dict) -> str:
    return ", ".join(f'{name}={rec["blocks"]}' for name, rec in
                     sorted(by_reason.items(), key=lambda kv: -kv[1]["blocks"]))


def _render_thread(thread: dict) -> str:
    """The thread shape, rendered into the one block the envelope wraps.

    Authors and timestamps are page-authored strings, so they travel INSIDE
    the delimiters with the post bodies rather than beside them."""
    lines = []
    for post in thread["posts"]:
        head = f'[post {post["index"]}]'
        if post["author"]:
            head += f' by {post["author"]}'
        if post["timestamp"] or post["timestamp_text"]:
            head += f' at {post["timestamp"] or post["timestamp_text"]}'
        if post["ref"]:
            head += f' ({post["ref"]})'
        lines.append(head)
        lines.append(post["text"])
    return "\n".join(lines)


async def get_article(
    page: str,
    location: dict | None = None,
    start_index: int = 0,
    max_chars: int = 20000,
    links: str = "inline",
) -> dict:
    """Read a page as an article: the title, the byline and published date
    where the page marks them up, and the body prose in reading order, with
    navigation, headers, footers, sidebars, related-story rails, comment
    streams, and share widgets excluded. What was excluded is COUNTED and
    returned by reason, so the trimming is never silent. In-prose links come
    back resolved as [text](path), tables are named and left to get_table
    rather than flattened, and hidden blocks are stripped and counted the way
    every read here counts them. A forum topic, issue thread, or comment
    stream comes back as posts with their authors and timestamps instead. A
    page that is an application rather than a document is REFUSED, with the
    evidence that decided it, and get_page_view is named as the read that
    shows what the page actually is. The body is paginated by start_index,
    and every field states which markup it came from.
    """
    if links not in ("inline", "none"):
        raise BadParams(
            f"unknown links mode {links!r}: 'inline' resolves in-prose links "
            f"into the body text as [text](path), and 'none' returns the "
            f"prose bare.")
    sess, record = common.locate(page)
    # THE READ GATE (gauntlet 4, G4-04/05/06): a page that moved
    # itself onto a wall, or a popup no door ever policed, is
    # refused before any of its content is returned.
    await _lite._read_gate(sess, record, tool="get_article")
    sess.counters["reads"] += 1
    # The SAME ref-to-node-ref resolver `get_page_view` and `get_text` scope
    # with, imported rather than reimplemented: the extractor keys its in-page
    # registry by the id IT assigned in the last read, and a pack tool that
    # worked that out for itself is a fourth copy waiting to drift.
    from .lite import _scope_root
    root = _scope_root(sess, record, location)
    got = await _read_article(record.page, root=root, start_index=start_index,
                              max_chars=max_chars, links=links)
    if got.get("error") == "ROOT_GONE":
        raise TargetNotFound(
            f'location named {got["asked_for"]!r} and that ref is not on '
            f'{record.handle} any more. Re-read the page and use the ref it '
            f'returns.')

    ev = got["evidence"]
    if got["shape"] == "none":
        # THE HONEST FALLBACK. An extractor that cannot refuse will hand back
        # a dashboard's button labels as an essay, which is the failure mode
        # that makes article extraction untrustworthy everywhere it ships
        # without one. The evidence is printed so the verdict is checkable.
        raise TargetNotFound(
            f"this page is not article-shaped; get_page_view shows what it "
            f"is. The scorer found {ev['prose_blocks']} paragraph-shaped "
            f"block(s) carrying {ev['article_chars']:,} characters, "
            f"{ev['link_density']:.0%} of the best candidate's text is link "
            f"text, and that candidate holds {ev['share_of_page']:.0%} of "
            f"the page's block prose. Failing: "
            f"{'; '.join(got['failed_tests'])}. get_text reads whatever prose "
            f"is here without pretending it is an article, and get_list or "
            f"get_table reach repeated records.")

    thread = got["thread"]
    body = _render_thread(thread) if got["shape"] == "thread" else got["text"]
    # The body is page prose, which is the single most common injection
    # channel, so it arrives inside the labeled data envelope (DESIGN 5.1,
    # H1) byte-identical to what the extractor returned. The note is extended
    # by one sentence because THIS payload also carries page-authored strings
    # in structured fields beside the text, and an envelope that covers only
    # the body would leave the byline unlabeled.
    wrapped, page_note = _pagedata.wrap(body, url=got["url"])
    page_note["label"] += (
        " The title, byline, date, and site fields beside this text are "
        "page-authored too and carry exactly the same status.")

    excluded = got["excluded"]
    hidden = got["hidden"]
    link_rec = got["links"]
    more = (f'get_article(page="{record.handle}", '
            f'start_index={got["next_start_index"]}) returns the next '
            f'{max_chars:,} characters'
            if got["next_start_index"] is not None
            else "this is the end of the article body")
    if got["shape"] == "thread":
        more = "the thread is returned whole; posts are not paginated"

    completeness = {
        "excluded": (
            f'{excluded["blocks"]} block(s) carrying {excluded["chars"]:,} '
            f'characters were page chrome and were excluded from the body, '
            f'counted rather than silently dropped '
            f'[{_tally(excluded["by_reason"]) or "none"}]'),
        "hidden": (
            f'{hidden["blocks"]} hidden block(s) carrying {hidden["chars"]:,} '
            f'characters were stripped from the body and counted '
            f'[{", ".join(f"{k}={v}" for k, v in sorted(hidden["reasons"].items(), key=lambda kv: -kv[1])[:6]) or "none"}]'
            + (f'; {hidden["injection_suspects"]} of them carried more than '
               f'20 characters, which is the shape of an injected instruction'
               if hidden["injection_suspects"] else '')
            + (f'; zero-width characters were removed from '
               f'{hidden["zero_width_blocks"]} block(s)'
               if hidden["zero_width_blocks"] else '')),
        "links": (
            f'{link_rec["resolved"]} in-prose link(s) were resolved'
            + (f' and then dropped from the body: the link markup came to '
               f'{link_rec["markup_chars"]:,} characters, over a quarter of '
               f'the prose, and a body that is mostly bracket syntax is not '
               f'readable. get_links lists them as data'
               if link_rec["dropped"]
               else (' into the body text as [text](path)'
                     if link_rec["mode"] == "inline" and link_rec["resolved"]
                     else '; links=inline resolves them into the body text'))),
        "tables": (
            f'{got["tables"]} table(s) in the body are named and left intact '
            f'rather than flattened into prose; get_table reads them as JSON'
            if got["tables"] else "no tables in the article body"),
    }
    if got.get("shadow_roots_read"):
        completeness["shadow"] = (
            f'prose was read from {got["shadow_roots_read"]} open shadow '
            f'root(s)'
            + (f'; {got["closed_shadow_roots"]} closed shadow root(s) are '
               f'unreadable by any tool' if got["closed_shadow_roots"] else ''))

    payload = {
        "page": record.handle, "session": sess.session_id,
        "url": got["url"], "shape": got["shape"],
        "scope": location if location else "the page's article body",
        "article": {
            "title": got["title"]["value"],
            "title_source": got["title"]["source"],
            "byline": got["byline"]["value"],
            "byline_source": got["byline"]["source"],
            "published": got["published"]["value"],
            "published_source": got["published"]["source"],
            "modified": got["modified"]["value"],
            "site_name": got["site_name"], "lang": got["lang"],
            "summary": " | ".join([
                _field("title", got["title"]),
                _field("byline", got["byline"]),
                _field("published", got["published"])]),
        },
        "text": wrapped,
        "page_data": page_note,
        "chars": {"returned": got["returned_chars"],
                  "total_in_article": got["total_chars"],
                  "start_index": got["start_index"],
                  "next_start_index": got["next_start_index"],
                  "blocks": got["blocks"]},
        "continue": more,
        "completeness": completeness,
        "budget": {"used": _ntok(body), "estimator": _ENCODING},
    }
    if got["shape"] == "thread":
        payload["thread"] = {
            "total_posts": thread["total_posts"],
            "with_author": thread["with_author"],
            "with_timestamp": thread["with_timestamp"],
            "refs": [p["ref"] for p in thread["posts"]],
            "note": ("this page did not pass the article tests and IS a "
                     "thread: repeated posts each carrying a machine-readable "
                     "timestamp. Post text, authors, and timestamps are "
                     "rendered inside the labeled text block above, headed "
                     "[post N] by AUTHOR at TIMESTAMP."),
        }
    return payload


#: The pack roster, in DESIGN 2.2 order. `server.register_all` registers
#: exactly this when the extract pack is selected.
#: Where a "next page" lives, in the order the page's own markup ranks it.
#: `rel=next` first because it is the declaration rather than a guess, then
#: an anchor whose accessible name IS a next-page word. Nothing here clicks:
#: every hop is a navigation to an href the page published, which is what
#: keeps this tool on the read side of the read-only line.
_NEXT_JS = r"""
() => {
  const out = [];
  const abs = (u) => { try { return new URL(u, location.href).href; }
                       catch (e) { return null; } };
  const bad = (u) => !u || /^(javascript:|mailto:|tel:|#)/i.test(u)
                     || abs(u) === location.href;
  const push = (href, how, label) => {
    if (bad(href)) return;
    const u = abs(href);
    if (u && !u.startsWith('http')) return;
    if (u) out.push({ url: u, how: how,
                      label: (label || '').replace(/\s+/g, ' ').trim().slice(0, 80) });
  };
  const head = document.querySelector('link[rel~="next" i][href]');
  if (head) push(head.getAttribute('href'), 'link rel=next', 'rel=next');
  const relA = document.querySelector('a[rel~="next" i][href]');
  if (relA) push(relA.getAttribute('href'), 'a rel=next', relA.textContent);
  const word = /^(next|next page|next ›|older|older posts|older entries|more|show more|load more|›|»|→|next\s*[›»→])$/i;
  for (const a of document.querySelectorAll('a[href]')) {
    const label = (a.getAttribute('aria-label') || a.textContent || '')
      .replace(/\s+/g, ' ').trim();
    if (word.test(label)) { push(a.getAttribute('href'), 'link text', label); break; }
  }
  return out;
}
"""


async def read_pages(
    page: str,
    max_pages: int = 5,
    max_chars: int = 8000,
    budget_chars: int = 40000,
) -> dict:
    """Read a paginated series in one call, following the page's own
    next-page link up to max_pages and stopping inside one character
    budget. Each page's prose comes back separately, labeled with the URL it
    came from, so a five-part article or a three-page result list arrives as
    one result instead of five navigate-and-read round trips. The next page
    is found from rel="next" first and from a link whose accessible name is
    a next-page word second; nothing is clicked and no URL is guessed, so a
    site with no such link stops rather than inventing one. Returns every
    page read, the reason the walk stopped (the page cap, the character
    budget, no next link, a link that leads back to a page already read, or
    a hop that landed on a bot wall or CAPTCHA interstitial, reported with
    its verdict rather than read as content), and the URL to resume from.
    """
    # Two independent ceilings and neither quietly widens the other: a
    # budget_chars under max_chars means the first page is read in full and
    # the walk stops there, which is what the caller asked for.
    max_pages = max(1, min(int(max_pages), 25))
    max_chars = max(500, int(max_chars))
    budget_chars = max(1, int(budget_chars))
    sess, record = common.locate(page)
    # The read gate on the page the walk STARTS on (gauntlet 4,
    # G4-04/05/06). Every later hop is classified in the loop below.
    await _lite._read_gate(sess, record, tool="read_pages")
    pages: list[dict] = []
    visited: list[str] = []
    total = 0
    stop = {"reason": "page-cap",
            "detail": f"the max_pages cap of {max_pages} was reached"}
    resume = None
    while True:
        held = await _resource.probe_page(record.page)
        if held is not None:
            stop = {"reason": "unreadable-resource",
                    "detail": _resource.navigate_note(held)["why"],
                    "route": _resource.escape_route(held)}
            break
        url = record.page.url
        visited.append(url)
        sess.counters["reads"] += 1
        got = await read_text(record.page, root=None, start_index=0,
                              max_chars=max_chars, include_hidden=False)
        wrapped, note = _pagedata.wrap(got["text"], url=got["url"])
        pages.append({
            "url": got["url"],
            "text": wrapped,
            "page_data": note,
            "chars": {"returned": got["returned_chars"],
                      "total_on_page": got["total_chars"],
                      "next_start_index": got["next_start_index"]},
            "clipped": got["next_start_index"] is not None,
        })
        total += got["returned_chars"]
        if len(pages) >= max_pages:
            stop = {"reason": "page-cap",
                    "detail": f"read {len(pages)} page(s), which is the "
                              f"max_pages cap"}
            break
        if total >= budget_chars:
            stop = {"reason": "char-budget",
                    "detail": f"{total:,} characters read, at or past the "
                              f"budget_chars ceiling of {budget_chars:,}"}
            break
        try:
            found = await record.page.evaluate(_NEXT_JS)
        except Exception:
            found = []
        # THE SCHEME CHECK IS SERVER-SIDE (gauntlet 3, F7). `_NEXT_JS` has
        # its own startsWith('http') guard, but it runs in the PAGE's JS
        # realm, where a hostile page can tamper String.prototype and pass
        # any URL through — which is exactly how a published file:/// next
        # link became a local-file read. The page-realm filter is a
        # convenience; this filter is the boundary, and the origin policy
        # (which now denies non-web schemes outright) is the backstop
        # behind it.
        harvested = [c for c in (found or []) if c.get("url")]
        candidate = next(
            (c for c in harvested
             if urlparse(c["url"]).scheme.lower() in ("http", "https")),
            None)
        if candidate is None:
            stop = {"reason": "end",
                    "detail": ("the only next-page link(s) this page "
                               "publishes are not http(s) URLs, which "
                               "read_pages never follows, so the series "
                               "ends here" if harvested else
                               "this page publishes no next-page link (no "
                               "rel=\"next\" and no link whose name is a "
                               "next-page word), so the series ends here as "
                               "far as the markup says")}
            break
        if candidate["url"] in visited:
            stop = {"reason": "loop",
                    "detail": f'the next-page link points back to '
                              f'{candidate["url"]}, which was already read '
                              f'in this walk, so the walk stopped rather '
                              f'than circling'}
            resume = None
            break
        # Every hop is a real navigation and goes through the real ladder:
        # origin policy, the 429 book, loop detection, and the navigation
        # budget, charged per page exactly as if the caller had made the
        # calls one at a time. A walk is not a way around a budget.
        _policy.approve(_policy.ActionRequest(
            tool="read_pages", kind="navigate", session=sess.session_id,
            page=record.handle, url=candidate["url"],
            args={"action": "goto", "url": candidate["url"]},
            summary=f'read_pages follows {candidate["how"]} to '
                    f'{candidate["url"]}'))
        before = record.page.url
        try:
            response = await record.page.goto(
                candidate["url"], wait_until="load", timeout=30000)
        except Exception as exc:
            stop = {"reason": "navigation-failed",
                    "detail": f'following {candidate["how"]} to '
                              f'{candidate["url"]} failed '
                              f'({type(exc).__name__}: {str(exc)[:160]}); '
                              f'the pages read before it are complete'}
            resume = candidate["url"]
            break
        record.touch(record.page.url)
        sess.counters["navigations"] += 1
        # Endurance F2: this door charged the ledger and never recorded the
        # origin it landed on, so the reported list silently omitted every
        # site reached by a page-walk hop.
        _lite.note_origin(sess, record.page.url)
        # THE LANDED CHECK ON THIS DOOR TOO (gauntlet 4, G4-06). The hop's
        # destination went through `approve()`, and a redirect on the way
        # laundered a deny-listed origin straight into the payload: the
        # walk completed the hop, put the blocked origin's content in the
        # result, and left the browser sitting on it.
        await _lite._landed_origin_check(sess, record, tool="read_pages")
        if record.page.url != before:
            sess.invalidate_page(
                record.handle,
                f"read_pages navigated from {before}")
        resume = record.page.url
        # EVERY HOP IS WALL-CLASSIFIED (gauntlet 3, F4). The hop loop always
        # asked one post-navigation question (the resource probe) and never
        # the other, so a rel=next chain that ended on a real Cloudflare
        # challenge read the interstitial as the next page. The verdict is
        # REPORTED in the stop record rather than raised — the pages read
        # before the wall are complete and belong to the caller — and the
        # wall page itself is never read as content.
        status = response.status if response is not None else None
        try:
            headers = dict(response.headers) if response is not None else None
        except Exception:
            headers = None
        verdict = await _lite._wall_verdict(record.page, status,
                                            headers=headers)
        if verdict.get("wall"):
            stop = {"reason": "wall",
                    "detail": f'{record.page.url} answered with a '
                              f'{verdict["wall"]} rather than the page '
                              f'(HTTP {status}); the pages read before it '
                              f'are complete',
                    "verdict": verdict}
            resume = None
            break
    if stop["reason"] in ("page-cap", "char-budget"):
        resume = resume or record.page.url
    return {
        "page": record.handle, "session": sess.session_id,
        "pages_read": len(pages),
        "pages": pages,
        "urls": visited,
        "stopped": stop,
        "chars_total": total,
        "resume": (f'read_pages(page="{record.handle}") continues from '
                   f'{record.page.url}' if stop["reason"] in
                   ("page-cap", "char-budget")
                   else "there is nothing to resume from; the walk ended "
                        "for the reason above rather than at a cap"),
        "refs": ("this walk navigated, so refs and read tokens minted "
                 "before it are gone; read the page you are on to mint "
                 "fresh ones" if len(visited) > 1 else
                 "nothing navigated, so refs minted earlier still hold"),
        "budget": {"used": _ntok(json.dumps([p["text"] for p in pages])),
                   "estimator": _ENCODING},
    }


TOOLS = (get_table, get_list, get_links, get_metadata, extract_fields,
         export_data, get_article, read_pages, extract_page, aggregate)
