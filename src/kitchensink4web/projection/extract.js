// KS4Web in-page extraction. One depth-first walk over the document, one
// computed style per element, and every number the projection prints is
// derived from this pass.
//
// Three S1 corrections are implemented HERE rather than in the renderer,
// because each was a data defect rather than a formatting one:
//
//  * accessible names are computed by an accname walk with space-separated
//    contributions, never `textContent` and never a CSS class (DESIGN 3.7).
//    S1 labelled GitHub's whole `main` region "Uh oh!" from a stray
//    error-state element, and a blind agent said an agent reading that would
//    "either panic or skip the only region that matters."
//  * affordances carry a CLASS, because ranking is by per-class quota with
//    guaranteed floors and not by one proximity score (DESIGN 3.3 block 3).
//    S1's single score buried all thirteen tabs of a repository navigation
//    bar with 2,762 tokens of headroom unused.
//  * a section's extent is the document-order run from its heading to the
//    next heading of the same or higher level, spanning wrapper elements. S1
//    walked `nextElementSibling`, which returns almost nothing on any site
//    that wraps sections in containers, so every heading priced at ~10 tok
//    while one of them was really ~6,399.
//
// Region ownership comes from a stack maintained during the walk, so every
// count is NET of nested regions and a parent can be priced net of its
// children (DESIGN 3.3a rule 2). Nothing is double counted, and the net
// counts of all regions plus the unowned remainder sum to the document.
(opts) => {
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_HREF@@
// @@KS4WEB_VISIBILITY@@
// @@KS4WEB_PAYMENT@@
// @@KS4WEB_ACTIVATION@@
// @@KS4WEB_ARIA@@
  opts = opts || {};
  // `location=` scoping. The read is the same read, run over a subtree: the
  // same blocks, the same ladder, the same completeness discipline, over a
  // smaller document. A scoped read that quietly became a different KIND of
  // read would make the advertised expand prices unverifiable, and DESIGN
  // 3.3a's contract is that every printed price is executable.
  let scopeRoot = null, scopeRef = null;
  if (opts.root) {
    scopeRoot = KS.refs.get(opts.root) || null;
    if (!scopeRoot) return { error: 'ROOT_GONE', asked_for: opts.root };
    scopeRef = opts.root;
  }
  // `opts.pin`: ONE element that is collected even past the affordance cap.
  //
  // The cap is right for a read and it broke the flagship pairing for an
  // ACT. `find_elements` searches every candidate on purpose, because the
  // link the design's own example names sits past the two thousandth on that
  // page; it minted a ref for a match at position 301, and the acting path
  // then resolved that ref against an extraction that stops at 300, so the
  // rebind ladder found no candidate and refused STALE. A search whose
  // results cannot be acted on is the operation DESIGN 3.5 says must not
  // exist, and it shipped that way until 2026-09-06.
  //
  // The pin widens the HAYSTACK and never picks the needle: the ladder still
  // matches by anchor key, still refuses ambiguity, and still refuses a
  // fingerprint that moved. An element pinned in but no longer matching its
  // stored anchor refuses exactly as it did before.
  const pinEl = opts.pin ? (KS.refs.get(opts.pin) || null) : null;

  const MAX_REGIONS = 40;       // listed regions; deeper ones fold into parents
  const MAX_REGION_DEPTH = 3;   // nesting depth that still earns its own ref
  // Caps on what is RETURNED, not on what is counted. Every interactive
  // element and every heading is classified and tallied whatever these say,
  // so the completeness block's suppression figures stay exact while the
  // payload that crosses the driver boundary stays bounded. A 5,000-heading
  // page serialized in full costs more in transfer than the whole walk costs
  // in the page, which is a bill nobody sees and everybody pays.
  const MAX_AFFORDANCES = 300;
  const MAX_HEADINGS = 150;
  const NAME_CAP = 80;
  const OPTION_INLINE_MAX = 12; // DESIGN 3.3 block 5, Phase 2 sets it by measurement
  const OPTION_INLINE_CHARS = 240;

  const ZERO_WIDTH = /[​-‏‪-‮⁠-⁤﻿]/;
  const t0 = performance.now();

  // ------------------------------------------------------------- utilities

  // Strict about its input on purpose. A DOM property that LOOKS like a
  // string is not always one: named-property access on a <form> makes
  // `form.title` return the child input named "title", and Wikipedia's
  // search form has exactly that. A permissive squash would then stringify
  // an element into an accessible name, which is the confident-wrong-answer
  // failure 3.7 exists to stop. A non-string is not a name, so it is ''.
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();

  function clip(s, n) {
    s = squash(s);
    if (s.length <= n) return { text: s, truncated: false };
    // Word boundary with an explicit ellipsis. A name cut inside a word reads
    // as a different string than the page contains, which is what breaks
    // string matching downstream (DESIGN 3.7 sub-rule 3).
    let cut = s.lastIndexOf(' ', n);
    if (cut < n * 0.6) cut = n;
    return { text: s.slice(0, cut) + '...', truncated: true };
  }

  // Styles, colours, the shadow-boundary hop, and the whole hidden-technique
  // set come from the ONE shared source spliced in above. This file held the
  // richest of the three copies and still missed four classes a page can use
  // today: near-zero opacity, a filter chain ending in transparency or a blur
  // past legibility, a transparent foreground (the old contrast check ignored
  // the alpha channel, so `color: transparent` scored as pure black), and
  // content that is not rendered at all -- `content-visibility: hidden`, a
  // collapsed `<details>`, an unslotted light child. Gauntlet 2's H2 walked
  // an agent onto five invisible buttons on one fixture using four of them.
  const cs = ksCS;
  const up = ksUp;
  const parseColor = ksParseColor;
  const lum = ksLum;
  // An IDREF (aria-labelledby, aria-describedby) resolves inside the tree
  // that holds it, so a shadow-borne label must be looked up in the shadow
  // root rather than in the document, where it is not.
  function byId(el, id) {
    const r = el.getRootNode ? el.getRootNode() : document;
    if (r && typeof r.getElementById === 'function') return r.getElementById(id);
    return document.getElementById(id);
  }

  // A form is payment-shaped when ANY field in it is, so every control in
  // that form -- its submit button included -- classifies as one action
  // class. The rule and its memo live in the ONE payment source spliced in
  // above; this used to be a fourth private copy of the same autocomplete
  // regex, and all four missed a page that simply declares no token (R3).
  const formPayment = ksFormPayment;

  const hiddenReason = ksHiddenReason;
  const geometryHidden = ksGeometryHidden;

  function hiddenBetween(el, stopAt) {
    // Hidden anywhere between an element and its region ancestor counts as
    // hidden, because that is how a display:none wrapper hides a heading that
    // is itself perfectly visible in its own computed style.
    return ksHiddenChain(el, stopAt) !== null;
  }

  function lowContrast(el, style) {
    return ksInvisibleColor(el, style || cs(el)) !== null;
  }

  // ------------------------------------------------------------ roles

  const TAG_ROLE = {
    A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox',
    SUMMARY: 'button', OPTION: 'option', IMG: 'img', TABLE: 'table',
    H1: 'heading', H2: 'heading', H3: 'heading', H4: 'heading',
    H5: 'heading', H6: 'heading'
  };
  const INPUT_ROLE = {
    checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button',
    reset: 'button', image: 'button', range: 'slider', file: 'file-input',
    search: 'searchbox', email: 'textbox', password: 'textbox', text: 'textbox',
    tel: 'textbox', url: 'textbox', number: 'spinbutton', date: 'textbox',
    hidden: 'hidden', color: 'colorpicker', month: 'textbox', time: 'textbox',
    'datetime-local': 'textbox', week: 'textbox'
  };
  // Roles whose accessible name comes from their own contents (accname step 2F).
  const NAME_FROM_CONTENT = new Set([
    'button', 'link', 'heading', 'cell', 'columnheader', 'rowheader', 'gridcell',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'radio',
    'checkbox', 'switch', 'tab', 'treeitem', 'tooltip', 'row', 'legend'
  ]);

  function roleOf(el) {
    const explicit = el.getAttribute && el.getAttribute('role');
    if (explicit) return explicit.trim().split(/\s+/)[0];
    if (el.tagName === 'INPUT') return INPUT_ROLE[(el.type || 'text').toLowerCase()] || 'textbox';
    if (el.tagName === 'A') return el.hasAttribute('href') ? 'link' : 'generic';
    return TAG_ROLE[el.tagName] || 'generic';
  }

  // ---------------------------------------------------- the accname walk

  // A subset of W3C accname 1.2, in the specified order. What it deliberately
  // is NOT: a `textContent` read. The four sub-rules of DESIGN 3.7 are all
  // implemented here, including "refuse to emit a CSS class as a stand-in
  // name", which is why the last fallback is an id or data-testid and then
  // nothing at all. Unnamed and honest beats named and wrong.
  function contentName(el, depth, seen) {
    if (depth > 4 || seen.has(el)) return '';
    seen.add(el);
    const parts = [];
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const s = squash(node.nodeValue);
        if (s) parts.push(s);
      } else if (node.nodeType === 1) {
        const st = cs(node);
        if (st.display === 'none' || st.visibility === 'hidden') continue;
        if (node.getAttribute('aria-hidden') === 'true') continue;
        const lbl = node.getAttribute('aria-label');
        if (lbl && squash(lbl)) { parts.push(squash(lbl)); continue; }
        if (node.tagName === 'IMG') {
          const alt = squash(node.getAttribute('alt') || '');
          if (alt) parts.push(alt);
          continue;
        }
        const inner = contentName(node, depth + 1, seen);
        if (inner) parts.push(inner);
      }
    }
    // Space-separated contributions, so a heading and its count badge never
    // fuse into one token ("General4", "Data Entry18").
    return parts.join(' ');
  }

  function accName(el, role) {
    let raw = '', how = 'content';
    const lb = el.getAttribute && el.getAttribute('aria-labelledby');
    if (lb) {
      const parts = lb.trim().split(/\s+/).map(id => {
        const target = byId(el, id);
        if (!target) return '';
        const own = target.getAttribute('aria-label');
        return squash(own) || contentName(target, 0, new Set());
      }).filter(Boolean);
      if (parts.length) { raw = parts.join(' '); how = 'labelledby'; }
    }
    if (!raw) {
      const al = el.getAttribute && el.getAttribute('aria-label');
      if (al && squash(al)) { raw = squash(al); how = 'aria-label'; }
    }
    if (!raw) {
      const tag = el.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
        const type = (el.type || '').toLowerCase();
        if (tag === 'INPUT' && (type === 'submit' || type === 'button' || type === 'reset')
            && el.value) { raw = squash(el.value); how = 'value'; }
        // `<input type=image>` NAMES ITSELF FROM alt (HTML-AAM), and it had
        // no rung here at all, so the one submit control this build calls
        // out by name (the 2026-09-06 R1 incident) read as unnamed: an
        // unnamed control anchors turn-local, so a ref minted for it did
        // not survive its own re-resolution. The image submitter is now
        // addressable by the word the page put on it.
        if (!raw && tag === 'INPUT' && type === 'image') {
          const alt = squash(el.getAttribute('alt') || '');
          if (alt) { raw = alt; how = 'alt'; }
        }
        if (!raw) {
          try {
            if (el.labels && el.labels.length) {
              raw = squash(Array.from(el.labels).map(l => contentName(l, 0, new Set())).join(' '));
              how = 'label';
            }
          } catch (e) { /* labels can throw on exotic shadow hosts */ }
        }
        if (!raw && el.placeholder) { raw = squash(el.placeholder); how = 'placeholder'; }
        if (!raw) { const tt = el.getAttribute('title'); if (squash(tt)) { raw = squash(tt); how = 'title'; } }
      } else if (tag === 'IMG' || tag === 'AREA') {
        raw = squash(el.getAttribute('alt') || ''); how = 'alt';
      } else if (tag === 'FIELDSET') {
        const lg = el.querySelector('legend');
        if (lg) { raw = contentName(lg, 0, new Set()); how = 'legend'; }
      } else if (tag === 'TABLE') {
        if (el.caption) { raw = contentName(el.caption, 0, new Set()); how = 'caption'; }
      }
    }
    if (!raw && NAME_FROM_CONTENT.has(role)) {
      raw = contentName(el, 0, new Set());
      how = 'content';
    }
    // getAttribute, not the property: `.title` is a named-property trap on
    // form elements and the attribute is what accname actually specifies.
    if (!raw && el.getAttribute) {
      const tt = el.getAttribute('title');
      if (squash(tt)) { raw = squash(tt); how = 'title'; }
    }
    if (!raw) {
      // NEVER a CSS class (S1 printed `.mw-file-description` as a name). A
      // stable attribute or nothing, and the completeness block counts it.
      const id = el.getAttribute && (el.getAttribute('data-testid') || el.id);
      if (id) return { name: '#' + id, quality: 'attribute-fallback' };
      return { name: '', quality: 'none' };
    }
    const c = clip(raw, NAME_CAP);
    const quality = c.truncated ? 'truncated'
      : (how === 'content' || how === 'aria-label' || how === 'labelledby'
         || how === 'label' || how === 'alt' || how === 'value'
         || how === 'legend' || how === 'caption') ? 'computed' : ('fallback:' + how);
    return { name: c.text, quality: quality };
  }

  // -------------------------------------------------------- region shapes

  const LM_TAG = {
    HEADER: 'banner', NAV: 'navigation', MAIN: 'main', ASIDE: 'complementary',
    FOOTER: 'contentinfo', FORM: 'form', DIALOG: 'dialog', ARTICLE: 'article'
  };
  const LM_ROLE = new Set(['banner', 'navigation', 'main', 'complementary',
    'contentinfo', 'search', 'form', 'region', 'dialog', 'alertdialog',
    'article', 'tablist', 'menubar', 'feed', 'table', 'grid']);
  const NAV_REGION = new Set(['navigation', 'tablist', 'menubar', 'banner']);

  const INTERACTIVE_SEL = 'a[href],button,input,select,textarea,summary,' +
    '[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],' +
    '[role=menuitem],[role=menuitemcheckbox],[role=menuitemradio],' +
    '[role=switch],[role=combobox],[role=searchbox],[role=textbox],' +
    '[role=option],[role=slider],[onclick],[tabindex]:not([tabindex="-1"])';

  function isInteractive(el) {
    const tag = el.tagName;
    if (tag === 'A') return el.hasAttribute('href');
    if (tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT'
        || tag === 'TEXTAREA' || tag === 'SUMMARY') return true;
    if (el.hasAttribute('onclick')) return true;
    const ti = el.getAttribute('tabindex');
    if (ti !== null && ti !== '-1') return true;
    const r = el.getAttribute('role');
    return !!r && /^(button|link|checkbox|radio|tab|menuitem|menuitemcheckbox|menuitemradio|switch|combobox|searchbox|textbox|option|slider|spinbutton)$/.test(r.trim().split(/\s+/)[0]);
  }

  const NAV_ROLE = /^(navigation|tablist|menubar|menu)$/;
  const climbCache = new Map();

  //: 'prose' | {li: element} | null, for the chain above a starting parent.
  function climbFrom(start) {
    if (!start) return null;
    const hit = climbCache.get(start);
    if (hit !== undefined) return hit;
    let out = null;
    let p = start, hops = 0;
    while (p && hops++ < 8) {
      const r = (p.getAttribute('role') || '').trim().split(/\s+/)[0];
      if (p.tagName === 'NAV' || NAV_ROLE.test(r)) break;
      if (p.tagName === 'LI') { out = { li: p }; break; }
      if (PROSE_ANCESTOR.has(p.tagName)) { out = 'prose'; break; }
      p = up(p);
    }
    climbCache.set(start, out);
    return out;
  }

  const TEXT_BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT', 'FIGCAPTION']);
  //: What `get_text` emits as one line, which is what the rate sample has to
  //: reproduce: a navbox of 150 one-word links costs a line boundary per
  //: link, and a sample that glues those links into sentences measures a
  //: page that does not exist.
  const LINE_BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT',
    'FIGCAPTION', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TD', 'TH']);
  const PROSE_ANCESTOR = new Set(['P', 'LI', 'BLOCKQUOTE', 'DD', 'FIGCAPTION']);

  // ------------------------------------------------- the anchor descriptor
  //
  // DESIGN 3.5's durable half, produced by the SAME walk that produces the
  // projection rather than by a second evaluate. The descriptor is role,
  // accessible name, a scoping path (nearest landmark, then nearest labelled
  // ancestor, then ordinal among same-role siblings), stable attributes where
  // the page offers them, and the page key it was minted on.
  //
  // The landmark here is computed by climbing ancestors rather than read off
  // the projection's region stack, and that is deliberate: the region list is
  // CAPPED (forty regions, three deep) because it is a menu a human reads,
  // and an anchor scoped by a capped structure would silently lose its
  // scoping on exactly the pages that need it most.
  const LM_ANCHOR_TAG = {
    HEADER: 'banner', NAV: 'navigation', MAIN: 'main', ASIDE: 'complementary',
    FOOTER: 'contentinfo', FORM: 'form', SECTION: 'region', DIALOG: 'dialog'
  };
  const LM_ANCHOR_ROLE = new Set(['banner', 'navigation', 'main',
    'complementary', 'contentinfo', 'form', 'region', 'search', 'dialog',
    'alertdialog', 'tablist']);

  // Both of these walk ancestors, and on a deep page every affordance walks
  // most of the same chain again. Memoizing per ancestor turns the pair from
  // O(affordances x depth) into O(distinct ancestors), which is what keeps
  // the anchor descriptor inside the latency budget: unmemoized it cost 505
  // ms p95 at 50,000 nodes against a 500 ms bound, for work that is the same
  // answer every time.
  const lmCache = new Map();
  function landmarkFrom(n) {
    if (!n) return { node: document.body, kind: 'document', label: '' };
    const hit = lmCache.get(n);
    if (hit !== undefined) return hit;
    const explicit = (n.getAttribute('role') || '').trim().split(/\s+/)[0];
    const kind = (explicit && LM_ANCHOR_ROLE.has(explicit)) ? explicit
      : LM_ANCHOR_TAG[n.tagName];
    let out = null;
    if (kind) {
      const label = squash(n.getAttribute('aria-label'))
        || squash(n.getAttribute('name'))
        || (n.getAttribute('aria-labelledby')
            ? squash((byId(n,
                n.getAttribute('aria-labelledby').split(/\s+/)[0])
                || {}).textContent)
            : '');
      // An unlabelled <section> is not a landmark under HTML-AAM, and
      // treating it as one scopes anchors to a container the page does not
      // consider structural.
      if (!(n.tagName === 'SECTION' && !label)) {
        out = { node: n, kind: kind, label: label };
      }
    }
    if (out === null) out = landmarkFrom(up(n));
    lmCache.set(n, out);
    return out;
  }

  function landmarkOf(el) {
    return landmarkFrom(up(el));
  }

  const laCache = new Map();
  function labelledFrom(n) {
    if (!n) return null;
    const hit = laCache.get(n);
    if (hit !== undefined) return hit;
    let out = null;
    const al = squash(n.getAttribute('aria-label'));
    if (al) {
      out = { node: n, label: al };
    } else {
      const lb = n.getAttribute('aria-labelledby');
      if (lb) {
        const t = byId(n, lb.split(/\s+/)[0]);
        if (t && squash(t.textContent)) out = { node: n, label: squash(t.textContent) };
      }
    }
    if (out === null) out = labelledFrom(up(n));
    laCache.set(n, out);
    return out;
  }

  function labelledAncestorOf(el, stopAt) {
    const found = labelledFrom(up(el));
    // Memoization answers "nearest labelled ancestor anywhere above", so the
    // landmark boundary is applied here: a label found AT or ABOVE the
    // landmark is the landmark's own label, not a scoping refinement inside
    // it, and using it would collapse the two rungs into one.
    if (!found || found.node === stopAt || found.node.contains(stopAt)) {
      return '';
    }
    return found.label;
  }

  // The page key, on every anchor KEY and not merely in the descriptor. S2
  // found the distinction by producing the failure: a ref minted on one page
  // came back bound to a same-named control on another, seven per run, at the
  // STRONGEST tier of the ladder rather than in the fuzzy tail where anyone
  // would look for it. The hash is in because a hash route is a page by every
  // meaning that matters to a ref.
  const PAGE_KEY = location.origin + location.pathname + location.hash;
  const anchorOrdinals = {};

  function anchorOf(el, role, name) {
    const lm = landmarkOf(el);
    const scope = lm.kind + ':' + lm.label + '|' + role;
    anchorOrdinals[scope] = (anchorOrdinals[scope] || 0) + 1;
    return {
      page_key: PAGE_KEY,
      role: role,
      name: name,
      landmark: lm.kind,
      landmark_label: lm.label,
      labelled_ancestor: labelledAncestorOf(el, lm.node),
      // Scopes a lookup and NEVER binds a ref. A virtualized list rewrites
      // its rendered window while keeping every ordinal, which put row 0's
      // ref onto row 3,998 and did the same for twenty-one of its
      // neighbours. Carried here for the candidate list an ambiguous refusal
      // prints, not for the key ladder.
      ordinal: anchorOrdinals[scope],
      attr_id: el.id || '',
      attr_testid: el.getAttribute('data-testid') || '',
      attr_name: el.getAttribute('name') || ''
    };
  }

  // Column headers come from THIS table's own header row, never from every
  // `th` in the subtree. The first version took `querySelectorAll('th')` and
  // sliced eight, which on a Wikipedia navbox returned the header cells of
  // tables nested inside it: the GDP page printed
  // `cols: show Lists of countries by... | Trade | Investment | Funds` for a
  // one-column layout table, which are not that table's column headers and
  // are not column headers at all. A wrong header list is the same disease as
  // a wrong accessible name, a confident answer to a question nobody asked.
  //
  // A single-column table has no column header list worth printing, so it
  // returns none rather than the one cell that happens to lead it.
  function columnHeaders(table, cols) {
    if (cols < 2) return [];
    const rows = table.rows || [];
    for (let i = 0; i < rows.length && i < 3; i++) {
      const cells = Array.from(rows[i].cells || []).filter(
        c => c.tagName === 'TH');
      if (cells.length >= 2) {
        return cells.slice(0, 8).map(
          x => clip(contentName(x, 0, new Set()), 28).text).filter(Boolean);
      }
    }
    return [];
  }

  // ----------------------------------------------------------- the walk

  const regions = [];
  const regionStack = [];
  const affordances = [];
  const headings = [];
  const forms = [];
  const tables = [];
  const canvases = [];
  // Is anything actually drawn on this canvas? (fuzzer class 3.)
  //
  // Sampled rather than read whole: a full getImageData on a 4K canvas is
  // megabytes of pixels for a boolean. Sixteen points on a grid catches a
  // painted toolbar, a chart, or a line of text, and misses only a canvas
  // whose entire content is thinner than one sixteenth of it in both axes.
  // `null` where the answer cannot be had, never a guess: a tainted canvas
  // (a cross-origin image drawn into it) throws a SecurityError on read,
  // and "I could not look" is a different statement from "nothing is there".
  function canvasPainted(el) {
    try {
      const ctx = el.getContext && el.getContext('2d');
      if (!ctx) return null;              // WebGL, or no context at all
      const w = el.width, h = el.height;
      if (!w || !h) return false;
      const steps = 4;
      for (let i = 0; i < steps; i++) {
        for (let j = 0; j < steps; j++) {
          const x = Math.min(w - 1, Math.floor(w * (i + 0.5) / steps));
          const y = Math.min(h - 1, Math.floor(h * (j + 0.5) / steps));
          const sw = Math.max(1, Math.floor(w / steps));
          const sh = Math.max(1, Math.floor(h / steps));
          const data = ctx.getImageData(
            Math.max(0, x - (sw >> 1)), Math.max(0, y - (sh >> 1)),
            Math.min(sw, w), Math.min(sh, h)).data;
          for (let k = 3; k < data.length; k += 4) {
            if (data[k] !== 0) return true;
          }
        }
      }
      return false;
    } catch (e) {
      return null;
    }
  }
  // Is an opaque panel covering the whole viewport? (hostile H-09.)
  //
  // One scan, no hit tests. A candidate has to be positioned, cover at
  // least 90% of the viewport in both axes, be fully opaque itself, carry
  // a non-transparent background of its own, and be the LAST such element
  // in paint order among its peers. That last condition is what keeps an
  // ordinary full-page wrapper out of the answer: a wrapper is where the
  // content lives, and this reports the topmost one only.
  function viewportLid() {
    try {
      const vw = window.innerWidth || 1280;
      const vh = window.innerHeight || 900;
      let best = null;
      const nodes = document.body
        ? document.body.querySelectorAll('*') : [];
      let scanned = 0;
      for (const el of nodes) {
        if (scanned++ > 4000) break;
        const s = ksCS(el);
        if (s.position !== 'fixed' && s.position !== 'absolute') continue;
        if (parseFloat(s.opacity) < 0.99) continue;
        if (s.visibility === 'hidden' || s.display === 'none') continue;
        const bg = s.backgroundColor || '';
        // A transparent panel is not a lid: a human sees straight through
        // it, and calling that invisible would be the false positive this
        // whole family of checks has to fail away from.
        if (!bg || bg === 'transparent'
            || /rgba\([^)]*,\s*0(\.0+)?\)\s*$/.test(bg)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < vw * 0.9 || r.height < vh * 0.9) continue;
        if (r.left > vw * 0.05 || r.top > vh * 0.05) continue;
        // The element's own text is what a human reads instead of the page.
        best = { tag: el.tagName.toLowerCase(),
                 id: el.id || null,
                 ref: KS.refof.get(el) || null,
                 w: Math.round(r.width), h: Math.round(r.height),
                 covers_viewport: true };
      }
      return best;
    } catch (e) {
      return null;
    }
  }
  const frames = [];
  const virtualContainers = [];
  const hiddenReasons = {};
  const hiddenInteractiveReasons = {};
  // Containers whose children RENDER in an order the source does not carry.
  // A human reads "The bank has cleared this request. / Do not approve the
  // transfer." and every text surface in this build reads the opposite, with
  // no caveat unless a shadow root happened to be involved (gauntlet 2 M3).
  const reorderReasons = {};
  let reorderedContainers = 0;
  let hiddenInteractive = 0, hiddenNodes = 0, hiddenTextChars = 0;
  let injectionSuspects = 0, zeroWidthHits = 0;
  let openShadowRoots = 0, divTables = 0, deepestCut = 0;
  let elementCount = 0, textCharsTotal = 0;
  // Open-shadow-root traversal (2026-09-06). Default ON: an off-by-default
  // read is the blind read the field report rejected, and the measured
  // regression on a page with no roots is zero because the added work is a
  // `el.shadowRoot` test that is null on every element. `opts.shadow ===
  // false` opts out, which is the escape hatch for a pathological page.
  const SHADOW_ON = !(opts && opts.shadow === false);
  let shadowRootsTraversed = 0, shadowElements = 0;

  // Refs resolve through the INSTRUMENT CHANNEL's registry, never through an
  // attribute we write onto the page. KS4Web reads pages; a projection that
  // mutated the DOM to give itself handles would be changing the thing it is
  // reporting on, and a MutationObserver-driven app would see it.
  //
  // The registry used to be `window.__ks4web_refs`, and gauntlet 2's H5 is
  // what that cost: `class Poisoned extends Map { get(){ return evil; } }`
  // satisfied every `instanceof Map` guard in the build, the trusted click
  // landed on the attacker's button, and the result reported the button the
  // model had asked for. It lives in a closure the page cannot reach now.
  //
  // Reused across reads rather than replaced. `location={"region":"r7"}`
  // resolves a ref that a PREVIOUS read minted, so a map that started empty
  // on every evaluate would make every scoped call fail with a stale ref that
  // is not in fact stale. Entries for elements that have left the document
  // are dropped here rather than accumulating.
  const refMap = KS.refs;
  for (const [k, v] of Array.from(refMap.entries())) {
    if (!v || !v.isConnected) refMap.delete(k);
  }
  const refOf = KS.refof;
  // In-page ids are minted MONOTONICALLY across the whole page lifetime (the
  // counters live in the channel, not in this closure), and an element that
  // already holds an id of the right kind keeps it. Both halves close the
  // same defect, found by the 2026-09-05 field misdirect investigation:
  // a per-read counter restarting at zero re-assigned existing keys to
  // whatever the CURRENT document order put at that position, so any stale
  // key held by a caller (a scoped read's root, a leaked node id) silently
  // meant a different element after a re-render. A monotonic key can only
  // ever mean one element or nothing.
  const mintRef = (prefix, el) => {
    const prior = refOf.get(el);
    if (prior && prior.charAt(0) === prefix && refMap.get(prior) === el) {
      return prior;
    }
    const ref = mintId(prefix);
    refMap.set(ref, el);
    refOf.set(el, ref);
    return ref;
  };
  // An id with no map registration, for units counted past their cap: the
  // id keeps the payload's cross-references unique without pretending an
  // unreturned unit is resolvable.
  KS.counters = KS.counters || Object.create(null);
  const mintId = (prefix) => {
    return prefix + (KS.counters[prefix] = (KS.counters[prefix] || 0) + 1);
  };
  let affordancesUncollected = 0;
  let currentHeading = null;
  const roleOrdinals = {};
  const classTotals = {};
  //: How many `nav`-classified controls each region holds, counted over
  //: EVERY one rather than the returned sample, so the demotion below is
  //: made on the page's number.
  const navByRegion = {};

  function bump(field, n) {
    const reg = regionStack.length ? regionStack[regionStack.length - 1] : null;
    if (reg) reg.net[field] += n;
  }

  // ------------------------------------------- tokenization rate samples
  //
  // A price is a TOKEN count, the tokenizer lives in Python, and characters
  // do not convert to tokens at one rate. On the frozen GDP article the
  // prose runs 5.3 characters to the token and the article's own data table
  // runs 1.8, so a table priced at the page's rate was under-priced by very
  // nearly three times: the number was arithmetic about a different kind of
  // content. Rather than hand a table a table-shaped constant, the walk
  // sends back a bounded sample of each unit's OWN text and the meter
  // measures the rate on it with the same tokenizer that enforces the
  // budget, which is DESIGN 3.3a's "one arithmetic" rule applied to the
  // conversion as well as to the counting.
  //
  // The sample is DECIMATED as it fills rather than truncated, so it stays
  // spread across everything the unit holds: a region whose first screen is
  // prose and whose body is a numeric table must not be described by its
  // opening paragraph. Everything here is bounded twice, per unit and per
  // read, because a page carrying 595 tables would otherwise ship a sample
  // larger than the payload.
  //: Per unit, and measured in CHARACTERS rather than in pieces: a table
  //: whose cells read "Ghana" and "1,234" fills twenty pieces with 140
  //: characters, and a rate measured on 140 characters of a 6,500-character
  //: table is a rate about its first column.
  const SAMPLE_UNIT_CHARS = 1500;
  //: Long enough that a run of prose tokenizes like prose. Fifty-character
  //: pieces measured 2.9 characters to the token on text that really runs
  //: 4.8, because every piece pays the boundary twice, and the regions the
  //: over-short sample described were then over-priced by half. Two hundred
  //: was measured against the same corpus at 2.5 percent median error.
  const SAMPLE_SNIPPET_CHARS = 200;
  //: Per read, over every unit, bounding two things at once: what crosses
  //: the boundary, and how much text the meter tokenizes on the far side.
  const SAMPLE_TOTAL_CHARS = 40000;
  let sampledChars = 0;

  //: Which line the walk is currently inside. Text carried by two different
  //: blocks is two lines when it is read back, and one run when it is not.
  let blockSeq = 0;

  function newSampler() {
    return { parts: [], buf: '', chars: 0, seen: 0, stride: 1, line: -1 };
  }

  // Text arrives one text NODE at a time, and a text node is not a run of
  // prose: a Wikipedia paragraph broken by six inline links arrives as seven
  // fragments of twenty characters. Measuring a rate on fragments measures
  // the fragmentation, because every piece pays a boundary at each end, and
  // it over-priced the flagship article's prose regions by a quarter. So the
  // fragments are re-joined into runs first, and it is whole RUNS that are
  // kept or skipped.
  function sampleInto(s, text) {
    if (!s || !text || sampledChars >= SAMPLE_TOTAL_CHARS) return;
    const join = s.line === blockSeq ? ' ' : '\n';
    s.line = blockSeq;
    s.buf = s.buf ? s.buf + join + text : text;
    if (s.buf.length < SAMPLE_SNIPPET_CHARS) return;
    const snippet = s.buf.slice(0, SAMPLE_SNIPPET_CHARS);
    s.buf = '';
    if (s.seen++ % s.stride) return;
    s.parts.push(snippet);
    s.chars += snippet.length;
    sampledChars += snippet.length;
    while (s.chars > SAMPLE_UNIT_CHARS && s.parts.length > 3) {
      const kept = [];
      let chars = 0;
      for (let i = 0; i < s.parts.length; i += 2) {
        kept.push(s.parts[i]);
        chars += s.parts[i].length;
      }
      sampledChars -= (s.chars - chars);
      s.parts = kept;
      s.chars = chars;
      s.stride *= 2;
    }
  }

  // A unit smaller than one run is described by what it has: the leftover
  // buffer is the whole of a short region's text rather than a remainder.
  function sampleOf(s) {
    if (!s) return null;
    if (s.parts.length) return s.parts.join('\n');
    return s.buf || null;
  }

  // The same sample, taken from a string rather than accumulated over a
  // walk: a table's text is read once, as one piece.
  function sampleString(text) {
    if (!text || sampledChars >= SAMPLE_TOTAL_CHARS) return null;
    if (text.length <= SAMPLE_UNIT_CHARS) {
      sampledChars += text.length;
      return text;
    }
    const pieces = Math.ceil(SAMPLE_UNIT_CHARS / SAMPLE_SNIPPET_CHARS);
    const step = Math.floor(text.length / pieces);
    const parts = [];
    for (let i = 0; i < pieces; i++) {
      parts.push(text.substr(i * step, SAMPLE_SNIPPET_CHARS));
    }
    const out = parts.join('\n');
    sampledChars += out.length;
    return out;
  }

  function regionCandidate(el) {
    const role = el.getAttribute && el.getAttribute('role');
    if (role) {
      const first = role.trim().split(/\s+/)[0];
      if (LM_ROLE.has(first)) return first;
    }
    if (LM_TAG[el.tagName]) return LM_TAG[el.tagName];
    if (el.tagName === 'SECTION' &&
        (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'))) return 'region';
    return null;
  }

  // Counting a shadow root is NOT the same job as walking into it, and
  // conflating them was a real defect: `openShadowRoots++` used to ride
  // inside the body of `walk()`, which returns early on a hidden subtree, so
  // a host under a `display:none` ancestor was never counted. The injection
  // fixture reported 5 open roots on a page with 7. The count now happens
  // before any early return, and a subtree the walk SKIPS still has its roots
  // tallied here, because "what I did not look at" is exactly the number the
  // completeness block exists to state.
  // Counts roots strictly BELOW `node`, in the light tree and through every
  // open root it finds. `node` itself is counted by the caller, before any
  // early return, so a host is never double counted.
  function countRootsUnder(node, kids) {
    for (const k of (kids || node.querySelectorAll('*'))) {
      if (k.shadowRoot) { openShadowRoots++; countRootsUnder(k.shadowRoot); }
    }
  }

  // Only asked when a `visibility: hidden` element is actually met, so the
  // page that never uses the override pays nothing for the question.
  function hasVisibleDescendant(el) {
    if (!el.querySelectorAll) return false;
    const kids = el.querySelectorAll('*');
    for (let i = 0; i < kids.length && i < 500; i++) {
      if (cs(kids[i]).visibility === 'visible') return true;
    }
    return false;
  }

  function walk(el, depth) {
    elementCount++;
    if (el.shadowRoot) openShadowRoots++;
    if (depth > 400) {                          // pathological nesting, reported
      // No root sweep here, deliberately. The cut can fire once per sibling
      // and a sweep per cut is the O(n^2) shape the hidden branch below
      // warns about, on the exact pages that shape hurts most. Roots below
      // 400 levels of nesting go uncounted; the cut itself is reported, so
      // the read still says a subtree was skipped.
      deepestCut++;
      return;
    }
    const style = cs(el);
    let hr = hiddenReason(el, style);
    if (hr === 'visibility-hidden' && hasVisibleDescendant(el)) {
      // `visibility` INHERITS and a descendant can turn it back on, which a
      // human then reads and every surface in this build used to miss
      // (gauntlet 2 L2). The subtree accounting below assumes a hidden branch
      // is hidden all the way down, so where a descendant overrides, the walk
      // continues and each node answers for itself. The element's own text is
      // still withheld and still counted.
      const own = squash(el.textContent || '');
      hiddenNodes += 1;
      hiddenReasons[hr] = (hiddenReasons[hr] || 0) + 1;
      if (own.length > 20) injectionSuspects++;
      hr = null;
    }
    if (hr) {
      // The whole subtree is accounted for HERE and the walk stops, which is
      // what keeps the normalizer linear: counting a hidden subtree at every
      // level of itself is the O(n^2) version of the same answer.
      const kids = el.querySelectorAll('*');
      const n = 1 + kids.length;
      countRootsUnder(el, kids);
      if (el.shadowRoot) countRootsUnder(el.shadowRoot);
      hiddenNodes += n;
      hiddenReasons[hr] = (hiddenReasons[hr] || 0) + n;
      const nInteractive = el.querySelectorAll(INTERACTIVE_SEL).length
        + (isInteractive(el) ? 1 : 0);
      hiddenInteractive += nInteractive;
      // THE TECHNIQUE, named beside the count. "4 nodes (1 interactive)" told
      // a caller how much was withheld and nothing about how it was hidden,
      // and the four cloaked buttons gauntlet 2 walked an agent onto were the
      // ones that never reached this branch at all. Now they do, and the
      // ledger says which disguise each one wore.
      if (nInteractive) {
        hiddenInteractiveReasons[hr] =
          (hiddenInteractiveReasons[hr] || 0) + nInteractive;
      }
      const txt = squash(el.textContent || '');
      hiddenTextChars += txt.length;
      if (txt.length > 20) injectionSuspects++;
      return;
    }

    // RENDERED ORDER versus SOURCE ORDER, measured where it is decided. Four
    // techniques reverse a page for a human without touching the DOM order
    // every text surface in this build reports: `flex-direction: *-reverse`,
    // the `order` property, explicit grid placement, and a component that
    // reorders its slots. The read cannot cheaply reorder itself, so it says
    // so instead: an unstated inversion is a page telling the agent the
    // opposite of what it tells the user.
    const disp = style.display;
    if (disp === 'flex' || disp === 'inline-flex'
        || disp === 'grid' || disp === 'inline-grid') {
      // MEASURED, not inferred. Asking "does this container use a technique
      // that CAN reorder" flags every named-area grid on the web, most of
      // which place their children in source order anyway. Asking "do the
      // boxes come out in a different sequence than the source" is the
      // question the caveat actually answers, and it covers all four
      // techniques with one test.
      // Only children that are IN FLOW and carry text. An absolutely
      // positioned child sits wherever its coordinates put it and was never
      // in the reading sequence (a visually-hidden radio behind a styled
      // label puts one in front of its own label on every design system on
      // the web), and a container of icons has no reading order to invert.
      const kids = [];
      let textual = 0;
      for (let c = el.firstElementChild; c && kids.length < 40;
           c = c.nextElementSibling) {
        const ccs = cs(c);
        if (ccs.position === 'absolute' || ccs.position === 'fixed') continue;
        const r = c.getBoundingClientRect();
        if (!(r.width || r.height)) continue;
        if (squash(c.textContent || '')) textual++;
        kids.push({ i: kids.length, t: r.top, b: r.bottom, l: r.left });
      }
      if (kids.length > 1 && textual > 1) {
        // READING ORDER, not raw top-then-left. A row of boxes with different
        // heights has different tops, and sorting on top alone would call
        // every `align-items: flex-end` row on the web reordered. Boxes whose
        // vertical extents overlap are one line and are read across it.
        const rtl = style.direction === 'rtl';
        const byLine = kids.slice().sort((a, b) => (a.t - b.t) || (a.l - b.l));
        const lines = [];
        for (const k of byLine) {
          const line = lines.length ? lines[lines.length - 1] : null;
          if (line && k.t < line.b - 1) {
            line.items.push(k);
            if (k.b > line.b) line.b = k.b;
          } else {
            lines.push({ b: k.b, items: [k] });
          }
        }
        const flat = [];
        for (const line of lines) {
          line.items.sort((a, b) => rtl ? (b.l - a.l) : (a.l - b.l));
          for (const k of line.items) flat.push(k.i);
        }
        let inverted = false;
        for (let i = 0; i < flat.length; i++) {
          if (flat[i] !== i) { inverted = true; break; }
        }
        if (inverted) {
          const why = /-reverse$/.test(style.flexDirection || '')
            ? 'flex-reverse'
            : (disp.indexOf('grid') >= 0 ? 'grid-placement' : 'order-property');
          reorderedContainers++;
          reorderReasons[why] = (reorderReasons[why] || 0) + 1;
        }
      }
    }

    let pushed = false;
    const kind = regionCandidate(el);
    if (kind && !hr && regions.length < MAX_REGIONS && regionStack.length < MAX_REGION_DEPTH) {
      const geo = geometryHidden(el, style);
      if (!geo.reason && (geo.rect.height >= 24 || geo.rect.width >= 24)) {
        const ref = mintRef('r', el);
        const named = accName(el, 'region');
        let label = named.name;
        if (!label) {
          // The heading that names a region must be one a reader can SEE.
          // S1 labelled GitHub's entire `main` region "Uh oh!" by taking the
          // first heading in the subtree, which belonged to an error state
          // that never rendered, and a blind agent said an agent reading that
          // would either panic or skip the only region that matters.
          const candidates = el.querySelectorAll('h1,h2,h3,legend,caption');
          for (let i = 0; i < candidates.length && i < 12; i++) {
            if (hiddenBetween(candidates[i], el)) continue;
            label = clip(contentName(candidates[i], 0, new Set()), 60).text;
            if (label) break;
          }
        }
        const finalLabel = label || '(' + el.tagName.toLowerCase() + ')';
        const rec = {
          ref: ref, kind: kind, label: finalLabel,
          anchor: anchorOf(el, kind, finalLabel),
          name_quality: named.quality,
          tag: el.tagName.toLowerCase(),
          depth: regionStack.length,
          parent: regionStack.length ? regionStack[regionStack.length - 1].ref : null,
          // `prose_links` is a SUBSET of `interactive`, tracked separately
          // because the class carries a quota of zero and a region ranker
          // that counts it ranks a footnote block above the page's own data
          // table. It is not subtracted from `interactive`, because the
          // region's real interactive count is a completeness fact.
          net: { interactive: 0, text_blocks: 0, images: 0, chars: 0,
                 words: 0, headings: 0, prose_links: 0 },
          sampler: newSampler(),
          children: [],
          top: Math.round(geo.rect.top + window.scrollY),
          in_viewport: geo.rect.top < window.innerHeight && geo.rect.bottom > 0,
          nav_shaped: NAV_REGION.has(kind)
        };
        if (rec.parent) {
          regionStack[regionStack.length - 1].children.push(ref);
        }
        regions.push(rec);
        regionStack.push(rec);
        pushed = true;
      }
    }

    const tag = el.tagName;
    const region = regionStack.length ? regionStack[regionStack.length - 1] : null;
    // Entering a block opens a new line, for the rate sample's purposes.
    // Everything below it belongs to that line until the next block opens.
    if (LINE_BLOCK.has(tag)) blockSeq++;

    // direct text, attributed to the innermost region and the current section
    let direct = 0, directWords = 0, directText = '';
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const s = node.nodeValue || '';
        if (ZERO_WIDTH.test(s)) { zeroWidthHits++; }
        const t = squash(s);
        direct += t.length;
        if (t) {
          directWords += t.split(' ').length;
          directText = directText ? directText + ' ' + t : t;
        }
      }
    }
    if (direct) {
      // Text carried by an element parked off screen is hidden by geometry
      // rather than by style, and the style sweep alone never sees it. This
      // is the one place the walk pays for a rect on a non-interactive
      // element, and it pays only where there is text to hide.
      let geoReason = null;
      if (direct > 8) {
        geoReason = geometryHidden(el, style).reason;
      }
      if (geoReason) {
        hiddenNodes++;
        hiddenReasons[geoReason] = (hiddenReasons[geoReason] || 0) + 1;
        hiddenTextChars += direct;
        if (direct > 20) injectionSuspects++;
      } else {
        textCharsTotal += direct;
        bump('chars', direct);
        // The same characters that are COUNTED are the ones sampled, so the
        // rate the meter measures is a rate about the text the price is
        // being charged for.
        const sampleReg = regionStack.length
          ? regionStack[regionStack.length - 1] : null;
        if (sampleReg) sampleInto(sampleReg.sampler, directText);
        if (currentHeading) sampleInto(currentHeading.sampler, directText);
        // Words as well as characters, because tokens track WORDS far more
        // closely than they track characters across content classes. A cell
        // of "1,234" and a clause of English prose have very different
        // characters per token and similar tokens per word, and a region
        // price built on characters alone under-priced a numeric table by a
        // factor of three while pricing the prose beside it correctly.
        bump('words', directWords);
        if (currentHeading) {
        currentHeading.section_chars += direct;
        currentHeading.section_words += directWords;
      }
        if (direct > 20 && lowContrast(el, style)) {
          injectionSuspects++;
          hiddenReasons['low-contrast'] =
            (hiddenReasons['low-contrast'] || 0) + 1;
        }
      }
    }

    if (!hr) {
      if (TEXT_BLOCK.has(tag)) bump('text_blocks', 1);
      if (tag === 'IMG' || tag === 'PICTURE' || tag === 'SVG') bump('images', 1);

      if (/^H[1-6]$/.test(tag)) {
        const named = accName(el, 'heading');
        if (named.name) {
          // CAP WHAT YOU RETURN, TALLY WHAT YOU COUNT (DESIGN 3.6a), applied
          // to the anchor descriptor as well as to the payload. Minting an
          // anchor for every heading on a 5,000-heading page costs two
          // ancestor walks apiece for 4,850 descriptors nothing will ever
          // return, and that alone was most of the Phase 2 latency
          // regression. The heading is still COUNTED, and its section extent
          // is still tracked, so no completeness figure moves.
          const keep = headings.length < MAX_HEADINGS;
          const rec = {
            ref: keep ? mintRef('h', el) : mintId('h'),
            level: +tag[1], text: named.name,
            anchor: keep ? anchorOf(el, 'heading', named.name) : null,
            name_quality: named.quality,
            region: region ? region.ref : null,
            section_chars: 0, section_words: 0, section_affordances: 0,
            section_known: true, sampler: newSampler()
          };
          headings.push(rec);
          bump('headings', 1);
          // A section runs to the next heading of the same or higher level,
          // in document order, spanning wrappers.
          while (currentHeading && currentHeading.level >= rec.level) {
            currentHeading = currentHeading.parentHeading || null;
          }
          rec.parentHeading = currentHeading;
          currentHeading = rec;
        }
      }

      if (isInteractive(el)) {
        const geo = geometryHidden(el, style);
        if (geo.reason) {
          hiddenInteractive++;
          hiddenReasons[geo.reason] = (hiddenReasons[geo.reason] || 0) + 1;
        } else {
          const role = roleOf(el);
          if (role !== 'hidden') {
            bump('interactive', 1);
            if (currentHeading) currentHeading.section_affordances++;
            const collect = affordances.length < MAX_AFFORDANCES
              || (pinEl !== null && el === pinEl);
            const named = collect ? accName(el, role)
              : { name: '', quality: 'not-collected' };
            const formEl = el.form || el.closest('form');
            // Submission semantics (C1, gauntlet 2026-09-06). The HTML spec
            // says a <button> with a missing or invalid type IS a submit
            // button; only 'button' and 'reset' opt out. This affordance's
            // `type` is what the ref path's action classifier reads, and
            // when it carried null for <button type=submit> the form_submit
            // confirmation gate never fired on the canonical read->ref->act
            // flow. An EXPLICIT type=submit keeps its declared semantics
            // anywhere, matching <input type=submit>; the default-submit
            // case applies only inside a form, where a click can actually
            // submit something.
            const type = ksSubmitTypeOf(el, !!formEl);
            const ac = ((el.getAttribute && el.getAttribute('autocomplete')) || '').toLowerCase();
            const secret = type === 'password' ||
              /current-password|new-password|one-time-code/.test(ac);
            const payment = ksPaymentField(el);
            const panGroup = ksPanGroup(el);
            // The same rule as the headings above: DISPLAY detail is computed
            // only for the elements that will be returned, while everything
            // CLASSIFICATION needs is computed for all of them so the
            // completeness tallies stay the page's numbers. `new URL()` on
            // every one of six thousand links, to produce a path string that
            // three hundred of them will print, is the expensive half of that
            // distinction.
            // THE SHARED STATE SOURCE (`aria.js`, spliced above). What lived
            // here read three DOM properties and three attributes, kept only
            // the true half of `aria-selected`, and threw away the VALUE of
            // `aria-current`, so "which tab is active" and "which nav item am
            // I on" were both unanswerable from a page read. `find.js` had a
            // thinner copy again. One implementation now answers both.
            const state = collect ? ksAriaState(el) : [];

            let href = null, path = null, external = false;
            if (tag === 'A') {
              // The raw attribute is cheap and the citation test below needs
              // it, so it is read for every link; the URL PARSE is not.
              href = el.getAttribute('href');
              if (collect) {
                try {
                  const u = new URL(ksHref(el), location.href);
                  external = u.origin !== location.origin;
                  path = external ? u.origin + u.pathname : (u.pathname + u.search + u.hash);
                } catch (e) { path = href; }
              }
            }

            // Quota class. Order matters: a link inside prose is a prose link
            // even when it also sits under a nav-shaped ancestor, and a form
            // control is a form control wherever it lives.
            // **A list item is not prose.** The first version treated any
            // LI ancestor as evidence of prose, and navigation menus are
            // `<ul><li><a>` by universal convention, so the zero quota
            // suppressed every real navigation bar on the web. On the frozen
            // GitHub repo page that removed all six repository tabs,
            // including Issues, which is S1's original failure returning
            // through a different door: buried by a quota this time instead
            // of by a proximity score.
            //
            // So an LI is prose only when the link sits INSIDE A SENTENCE,
            // measured as the item carrying substantially more text than the
            // link itself. `<li><a>Code</a></li>` is a menu item;
            // `<li>See also the <a>Fourteen Points</a> for context</li>` is
            // prose. And the climb stops at a navigation ancestor, so a menu
            // nested somewhere under an article never inherits prose from a
            // paragraph far above it.
            // Only LINKS can be in-prose, so the ancestor climb is gated on
            // the role rather than run for every button and input, and the
            // link's own text is measured only if an LI is actually reached.
            // Both were unconditional in the first version and the pair cost
            // roughly 45 percent of extract time on a link-heavy page, for
            // an answer most elements never use.
            let inProse = false;
            if (role === 'link') {
              // Memoized on the STARTING PARENT, which is exact: the climb
              // is deterministic in the parent and the hop budget, and both
              // are the same for every link. On a link-heavy page the links
              // share ancestors, so this turns 8 getAttribute calls per link
              // into 8 per distinct container.
              const found = climbFrom(up(el));
              if (found === 'prose') {
                inProse = true;
              } else if (found && found.li) {
                // The one part that cannot be memoized, because it is a
                // property of the LINK rather than of the chain: a list item
                // is prose only when the link sits inside a sentence.
                const own = squash(el.textContent || '').length;
                if (squash(found.li.textContent || '').length > own + 40) {
                  inProse = true;
                }
              }
            }
            // A CITATION MARKER is a reference, not an affordance, and it is
            // recognizable by its own shape rather than by its ancestor. The
            // ancestor test alone misses every marker that sits in an
            // infobox cell or a caption instead of a paragraph, which is how
            // `[ 1 ]`, `[ 2 ]`, `[ n. 1 ]` came back among the top
            // affordances on the flagship article after the prose rule was
            // otherwise correct. A whole name that is a short bracketed
            // token, pointing at a fragment of the SAME page, is a footnote
            // by construction.
            // Read from the element rather than from the computed name, so
            // the class is the same whether or not this one was collected.
            // A tally that changed at the 300th element would make the
            // completeness figures a property of the cap.
            const citation = role === 'link'
              && (href || '').charAt(0) === '#'
              && el.textContent.length < 24
              && /^\[\s*[^\]]{0,12}\s*\]$/.test(squash(el.textContent));
            let cls;
            if (role === 'link' && (inProse || citation)) cls = 'prose_link';
            // A form control is a control INSIDE A FORM. The quota that says
            // "complete whenever the form fits, never sampled" is a promise
            // about forms, and letting every loose input on an app shell
            // claim it turns the guarantee into the flood it was written to
            // prevent.
            else if (formEl && (tag === 'INPUT' || tag === 'SELECT'
                                || tag === 'TEXTAREA')) cls = 'form_control';
            else if (role === 'searchbox' || role === 'combobox') cls = 'primary';
            else if (region && region.nav_shaped) cls = 'nav';
            else if (role === 'tab' || role === 'menuitem' || role === 'menuitemcheckbox'
                     || role === 'menuitemradio') cls = 'nav';
            else if (type === 'submit' || el.getAttribute('aria-haspopup')
                     || el.getAttribute('aria-expanded') !== null
                     || (role === 'button' && region &&
                         (region.kind === 'main' || region.kind === 'dialog'
                          || region.kind === 'alertdialog' || region.kind === 'form'
                          || region.kind === 'search'))) cls = 'primary';
            else cls = 'other';

            classTotals[cls] = (classTotals[cls] || 0) + 1;
            if (cls === 'prose_link') bump('prose_links', 1);
            if (cls === 'nav') {
              const rk = region ? region.ref : '(unowned)';
              navByRegion[rk] = (navByRegion[rk] || 0) + 1;
            }
            if (collect) {
              roleOrdinals[role] = (roleOrdinals[role] || 0) + 1;
              const ref = mintRef('e', el);
              affordances.push({
                ref: ref, anchor: anchorOf(el, role, named.name),
                role: role, name: named.name,
                name_quality: named.quality,
                cls: cls, region: region ? region.ref : null,
                region_label: region ? region.label : null,
                ordinal: roleOrdinals[role],
                state: state.join(','), secret: secret, payment: payment,
                tag: tag,
                placeholder: (el.getAttribute('placeholder') || ''),
                editable: !!el.isContentEditable,
                pan_shape: ksPanShape('value' in el ? el.value : ''),
                pan_group_size: panGroup ? panGroup.size : null,
                pan_group_digits: panGroup ? panGroup.digits : null,
                pan_group_first: panGroup ? panGroup.first : null,
                pan_group_min: panGroup ? panGroup.min : null,
                pan_group_region: panGroup ? panGroup.region : null,
                // Which element a click on this one ACTIVATES (re-attack 2,
                // C1): a <label> forwards to its control, and a node with no
                // activation behaviour delegates to the nearest ancestor that
                // has one.
                activates: ksDelegatedActivation(el),
                href: href, path: path, external: external, type: type,
                in_viewport: geo.rect.top < window.innerHeight
                  && geo.rect.bottom > 0 && geo.rect.left < window.innerWidth,
                top: Math.round(geo.rect.top + window.scrollY),
                area: Math.round(geo.rect.width * geo.rect.height),
                form: formEl ? true : false,
                form_payment: formPayment(formEl),
                heading: currentHeading ? currentHeading.ref : null
              });
            } else {
              affordancesUncollected++;
            }
          }
        }
      }

      if (tag === 'FORM') {
        const fref = mintRef('f', el);
        forms.push({ el: el, ref: fref, region: region ? region.ref : null });
      } else if (tag === 'TABLE') {
        const rows = el.rows ? el.rows.length : 0;
        if (rows) {
          const named = accName(el, 'table');
          const cols = el.rows[0] ? el.rows[0].cells.length : 0;
          const tableText = squash(el.textContent || '');
          const tref = mintRef('t', el);
          tables.push({
            ref: tref, caption: named.name,
            anchor: anchorOf(el, 'table', named.name),
            name_quality: named.quality,
            rows: rows, cols: cols,
            headers: columnHeaders(el, cols),
            region: region ? region.ref : null,
            chars: tableText.length,
            sample: sampleString(tableText),
            spans: el.querySelectorAll('[rowspan],[colspan]').length
          });
        }
      } else if (tag === 'CANVAS') {
        // THE LEDGER WAS INVERTED BY AN AREA HEURISTIC (fuzzer class 3).
        // The old test was "bigger than 80x80", which is a guess about
        // whether a canvas matters and answers the wrong question in both
        // directions: a 200x60 canvas with `fillText('SMALLCANVASTEXT')`
        // painted on it reported "canvas-rendered regions: none", and a
        // 900x600 canvas that was completely blank reported one region of
        // unread content. `UNSUPPORTED_CONTENT`'s hint promises "the
        // completeness block of the last read counts it", and on the small
        // one it counted zero.
        //
        // Every canvas that is LAID OUT is counted now, whatever its size,
        // because size is not evidence about content and the ledger's job
        // is to say what was not read. `painted` is the cheap, honest
        // signal the payload can carry beside it: a canvas whose backing
        // store is entirely transparent has nothing on it, and one that is
        // too large to sample says so rather than guessing.
        const geo = geometryHidden(el, style);
        if (!geo.reason && geo.rect.width >= 1 && geo.rect.height >= 1) {
          canvases.push({
            region: region ? region.ref : null,
            w: Math.round(geo.rect.width), h: Math.round(geo.rect.height),
            painted: canvasPainted(el)
          });
        }
      } else if (tag === 'IFRAME') {
        let same = false;
        try { same = !!el.contentDocument; } catch (e) { same = false; }
        frames.push({
          ref: 'if' + (frames.length + 1),
          src: clip(el.getAttribute('src') || '(srcdoc)', 70).text,
          same_origin: same, title: clip(el.getAttribute('title') || '', 40).text,
          region: region ? region.ref : null
        });
      }

      // Virtualization detection, and the geometric test is the one that
      // catches the real thing. The attribute and class-name tests find a
      // library that announces itself; react-window does not, and it is the
      // library the fixture uses because it is the library people use. A
      // windowed list is a SCROLLABLE BOX WHOSE SCROLL EXTENT IS FAR LARGER
      // THAN WHAT IT HOLDS, which is exactly the shape a projection would
      // otherwise report as a complete twenty-row list.
      const setsize = el.getAttribute('aria-setsize') || el.getAttribute('aria-rowcount');
      const clsName = typeof el.className === 'string' ? el.className : '';
      let windowed = null;
      if (!setsize && !/virtual|infinite|windowed/i.test(clsName)) {
        const ov = style.overflowY;
        if ((ov === 'auto' || ov === 'scroll') && el.clientHeight > 40
            && el.scrollHeight > el.clientHeight * 3) {
          windowed = { extent: el.scrollHeight, visible: el.clientHeight };
        }
      }
      if (setsize || windowed || /virtual|infinite|windowed/i.test(clsName)) {
        // The rendered rows are the leaf-ish children of the scrolling box,
        // one level deeper when the library wraps them in a sizing element,
        // which is what react-window does.
        let host = el;
        if (el.children.length === 1 && el.children[0].children.length > 2) {
          host = el.children[0];
        }
        const kids = host.children.length;
        if (kids > 2 || setsize) {
          virtualContainers.push({
            region: region ? region.ref : null, dom_count: kids,
            claimed: setsize ? parseInt(setsize, 10) : null,
            how: setsize ? 'aria-setsize'
              : (windowed ? 'scroll extent ' + windowed.extent + 'px in a '
                 + windowed.visible + 'px box' : 'class name'),
            hint: clip(clsName, 30).text
          });
        }
      }
      const r2 = el.getAttribute('role');
      if (r2 && /^(table|grid|treegrid)$/.test(r2.trim())) divTables++;
    }

    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child, depth + 1);
    }
    // OPEN-SHADOW-ROOT DESCENT, and the placement is the whole design.
    //
    // It sits INSIDE the host's own walk, after `hiddenReason()` has already
    // returned for the host. A hidden host therefore never gets here: its
    // shadow payload is accounted in the hidden ledger and cannot enter the
    // projection. Sitting here also means the depth cut, the region stack,
    // the ref minting, and the budget accounting all apply to shadow content
    // unchanged, rather than being re-derived by a second pass.
    //
    // `<slot>` assigned nodes are NOT followed: an assigned node is still a
    // light child of the host and the loop above already has it, so following
    // the slot would count it twice. The price is ORDER, since a shadow tree
    // can render its slotted children in any sequence and this walk reports
    // source order. That caveat is stated in the completeness block rather
    // than left silent. A slot's own FALLBACK children are walked, and are
    // not double counted because they only render when nothing is assigned.
    if (SHADOW_ON && el.shadowRoot) {
      shadowRootsTraversed++;
      shadowElements += el.shadowRoot.querySelectorAll('*').length;
      for (let child = el.shadowRoot.firstElementChild; child;
           child = child.nextElementSibling) {
        walk(child, depth + 1);
      }
    } else if (el.shadowRoot) {
      countRootsUnder(el.shadowRoot);   // opted out: still counted, not read
    }
    if (pushed) regionStack.pop();
  }

  const walkRoot = scopeRoot || document.body;
  if (walkRoot) walk(walkRoot, 0);

  // The navigation class carries a GUARANTEED FLOOR, filled before any other
  // class, and DESIGN 3.3 justifies that with "this is what an agent asks for
  // most and it is small." The second half is a premise, so it is checked
  // rather than assumed: a Wikipedia navbox is a nav-shaped landmark holding
  // 155 links, and a guaranteed floor sized for a tab bar becomes a flood
  // when a related-links block claims it. That is the same failure as the
  // form-control quota before it was scoped to controls inside a form.
  //
  // A navigation region larger than this is a link collection, not the page's
  // navigation, and its members compete in `other` on their merits.
  const NAV_BAR_MAX = 30;
  const floodedRegions = new Set(
    Object.keys(navByRegion).filter(k => navByRegion[k] > NAV_BAR_MAX));
  if (floodedRegions.size) {
    for (const key of floodedRegions) {
      const n = navByRegion[key];
      classTotals['nav'] = (classTotals['nav'] || 0) - n;
      classTotals['other'] = (classTotals['other'] || 0) + n;
    }
    for (const aff of affordances) {
      if (aff.cls === 'nav'
          && floodedRegions.has(aff.region || '(unowned)')) {
        aff.cls = 'other';
      }
    }
  }
  for (const h of headings) delete h.parentHeading;

  // A heading with no attributed text has no determinable section, so the
  // projection prints NO price for it rather than a number derived from a
  // walk that found nothing (DESIGN 3.3a rule 1).
  for (const h of headings) h.section_known = h.section_chars > 0;

  // The samplers are working state; what crosses the boundary is one string
  // per unit, which is what the meter measures its rate on.
  for (const r of regions) { r.sample = sampleOf(r.sampler); delete r.sampler; }
  for (const h of headings) {
    h.section_sample = sampleOf(h.sampler);
    delete h.sampler;
  }

  // --------------------------------------------------------- form fields

  const formOut = [];
  for (const f of forms) {
    const el = f.el;
    const fields = [];
    for (const field of Array.from(el.querySelectorAll('input,select,textarea'))) {
      const type = field.tagName === 'INPUT'
        ? (field.type || 'text').toLowerCase() : field.tagName.toLowerCase();
      if (type === 'hidden') continue;
      if (hiddenReason(field, null)) continue;
      const role = roleOf(field);
      const named = accName(field, role);
      const ac = (field.getAttribute('autocomplete') || '').toLowerCase();
      const secret = type === 'password' ||
        /current-password|new-password|one-time-code/.test(ac);
      let options = null, optionCount = null;
      if (field.tagName === 'SELECT') {
        const all = Array.from(field.options).map(o => squash(o.label || o.text || o.value));
        optionCount = all.length;
        const joined = all.join(', ');
        if (all.length <= OPTION_INLINE_MAX && joined.length <= OPTION_INLINE_CHARS) {
          options = all;
        }
      }
      fields.push({
        ref: refOf.get(field) || null,
        label: named.name, name_quality: named.quality, type: type,
        required: !!field.required, secret: secret,
        payment: ksPaymentField(field),
        options: options, option_count: optionCount,
        // Secret values are NEVER read, not even redacted in place. Reading a
        // redacted value and reading no value are different guarantees.
        value_state: secret ? 'never-read'
          : (field.value ? (String(field.value).length > 30
              ? 'set(' + String(field.value).length + ' chars)'
              : 'set:"' + clip(field.value, 30).text + '"') : 'empty')
      });
    }
    const named = accName(el, 'form');
    formOut.push({
      ref: f.ref, region: f.region,
      anchor: anchorOf(el, 'form', named.name || el.getAttribute('name') || el.id || ''),
      name: named.name || el.getAttribute('name') || el.id || '',
      action: clip(el.getAttribute('action') || '(same page)', 60).text,
      method: (el.getAttribute('method') || 'get').toUpperCase(),
      fields: fields
    });
  }

  // ------------------------------------------------------- the page shape

  // The readability gate, tuned against measurement rather than a threshold
  // picked in advance. S1's gate (prose > 1200 chars and >= 4 paragraphs)
  // gave CNN an article-shaped digest while reporting ~336 characters of
  // prose across a twenty-section homepage, so the gate and the thing it
  // gated disagreed inside one payload. This one requires the prose to be a
  // real SHARE of the page and to contain at least one substantial paragraph,
  // and the projection states which shape it chose and why.
  const paras = Array.from(walkRoot.querySelectorAll('p,article>div>p'))
    .filter(p => !hiddenReason(p, null));
  let proseChars = 0, longest = 0, leadEl = null, leadRegion = null;
  const proseByRegion = {};
  for (const p of paras) {
    const s = squash(p.textContent || '');
    proseChars += s.length;
    if (s.length > longest) { longest = s.length; }
  }
  // The lead comes from the READABLE REGION only, never document order. S1's
  // lead took the first <p> over 80 chars anywhere, which on CNN returned a
  // DRM error string as the site's headline.
  let bestRegion = null;
  for (const rec of regions) {
    if (rec.kind === 'main' || rec.kind === 'article' || rec.kind === 'region') {
      if (!bestRegion || rec.net.chars > bestRegion.net.chars) bestRegion = rec;
    }
  }
  const readableHost = scopeRoot
    || document.querySelector('main,[role=main],article');
  const hostParas = readableHost
    ? Array.from(readableHost.querySelectorAll('p')).filter(p => !hiddenReason(p, null))
    : paras;
  let hostProse = 0;
  for (const p of hostParas) hostProse += squash(p.textContent || '').length;
  for (const p of hostParas) {
    const s = squash(p.textContent || '');
    if (s.length >= 120) { leadEl = s; leadRegion = bestRegion ? bestRegion.ref : null; break; }
  }
  // Clamped: the prose total collapses whitespace across a paragraph's whole
  // subtree while the page total collapses it per text node, so a paragraph
  // full of inline links can score fractionally over 1. A ratio above 100
  // percent is a measurement artifact, and printing one would make a reader
  // distrust every other number in the block.
  const proseRatio = textCharsTotal
    ? Math.min(1, hostProse / textCharsTotal) : 0;
  const readable = hostParas.length >= 4 && hostProse >= 1200
    && proseRatio >= 0.25 && longest >= 200;
  let shapeKind, shapeWhy;
  if (readable) {
    shapeKind = 'article';
    shapeWhy = hostParas.length + ' paragraphs, ' + hostProse + ' prose chars, '
      + Math.round(proseRatio * 100) + '% of page text, longest paragraph '
      + longest + ' chars';
  } else if (formOut.length && formOut.some(f => f.fields.length >= 2)) {
    shapeKind = 'form';
    shapeWhy = formOut.length + ' form(s) and prose is '
      + Math.round(proseRatio * 100) + '% of page text';
  } else {
    shapeKind = 'app';
    shapeWhy = 'prose is ' + Math.round(proseRatio * 100)
      + '% of page text over ' + hostParas.length + ' paragraphs';
  }

  const nameFallbacks = affordances.filter(
    a => a.name_quality !== 'computed').length
    + regions.filter(r => r.name_quality !== 'computed' && r.name_quality !== 'none').length;

  const docH = document.documentElement.scrollHeight;
  const vpH = window.innerHeight || 900;

  return {
    identity: {
      url: location.href, title: document.title,
      lang: document.documentElement.lang || '',
      origin: location.origin,
      // The anchor key's page scope, computed once and carried, so the
      // Python side never rebuilds it from a URL string and never disagrees
      // with what the descriptors were minted under.
      page_key: PAGE_KEY,
      // Dies with the document and survives pushState, which is the line
      // between "the app routed" and "the browser navigated". S2 measured
      // document identity as the alternative cross-page test and it is worse
      // in both directions, so this is REPORTED and not used as the test.
      doc_epoch: (KS.doc = KS.doc
                  || String(Date.now()) + ':' + Math.random()),
      viewport: (window.innerWidth || 1280) + 'x' + vpH,
      screens: Math.max(1, Math.round((docH / vpH) * 10) / 10)
    },
    shape: {
      kind: shapeKind, why: shapeWhy, readable: readable,
      readable_region: leadRegion, prose_chars: hostProse,
      prose_ratio: Math.round(proseRatio * 100) / 100,
      paragraphs: hostParas.length, longest_paragraph: longest
    },
    regions: regions.map(r => ({
      ref: r.ref, kind: r.kind, label: r.label, anchor: r.anchor,
      name_quality: r.name_quality,
      tag: r.tag, depth: r.depth, parent: r.parent, children: r.children,
      net: r.net, top: r.top, in_viewport: r.in_viewport,
      nav_shaped: r.nav_shaped,
      // The bounded text sample the meter measures this region's own
      // characters-per-token rate on. It is never printed.
      sample: r.sample
    })),
    affordances: affordances,
    // Totals over EVERY interactive element, including the ones past the
    // return cap, so "unlisted affordances: N" is the real number.
    affordance_class_totals: classTotals,
    //: Named so the completeness block could say it if the author wants it
    //: said, and so a test can assert the demotion happened rather than
    //: inferring it from a token count.
    nav_regions_demoted: Array.from(floodedRegions),
    affordance_total: affordances.length + affordancesUncollected,
    headings: headings.slice(0, MAX_HEADINGS),
    headings_total: headings.length,
    lead: leadEl || '',
    // Entry condition one of the rebind ladder: a pending modal blocks
    // interaction before any resolution is attempted at all, and it beats
    // every other entry condition including a ref that was never minted.
    modal: (() => {
      const d = document.querySelector(
        '[role="dialog"][aria-modal="true"], [role="alertdialog"], dialog[open]');
      if (!d) return null;
      return squash(d.getAttribute('aria-label'))
        || clip(contentName(d, 0, new Set()), 40).text || 'dialog';
    })(),
    forms: formOut,
    tables: tables,
    div_tables: divTables,
    completeness: {
      frames: frames,
      frames_same: frames.filter(f => f.same_origin).length,
      frames_cross: frames.filter(f => !f.same_origin).length,
      open_shadow_roots: openShadowRoots,
      shadow_roots_traversed: shadowRootsTraversed,
      shadow_traversal: SHADOW_ON,
      closed_shadow_roots: (KS.closed || 0),
      virtual: virtualContainers, canvases: canvases,
      // THE FULL-VIEWPORT LID (hostile H-09). Per-element occlusion stays
      // on the acting path for the cost reason `visibility.js` documents:
      // a page-wide scan plus nine hit tests per element, on every
      // extraction of a ten-thousand-node page. The one case that does NOT
      // need that is this one, because a panel covering the whole viewport
      // is a single page-level question asked once.
      //
      // It was worth asking. A `position:fixed; inset:0; opacity:1;
      // pointer-events:auto` panel raised over everything left the read
      // saying "unlisted affordances: none, every control is listed" with
      // the covered button listed above it, while `click` refused with "an
      // opaque panel is painted over it ... the read's completeness block
      // counts it as hidden interactive with the technique named". It did
      // not. A refusal advertising a cross-check the read demonstrably
      // fails to produce is the worst version of the defect: an agent told
      // to trust the completeness block is told so by a message the
      // completeness block contradicts.
      viewport_lid: viewportLid(),
      hidden_interactive: hiddenInteractive, hidden_nodes: hiddenNodes,
      hidden_text_chars: hiddenTextChars, hidden_reasons: hiddenReasons,
      hidden_interactive_reasons: hiddenInteractiveReasons,
      reordered_containers: reorderedContainers,
      reorder_reasons: reorderReasons,
      injection_suspects: injectionSuspects, zero_width_hits: zeroWidthHits,
      name_fallbacks: nameFallbacks,
      scope: scopeRef,
      // Shadow content is part of the document the walk covered, so it is
      // part of the denominator too. Without this a traversing read reports
      // more elements walked than the page is said to have.
      total_elements: (scopeRoot
        ? scopeRoot.getElementsByTagName('*').length + 1
        : document.getElementsByTagName('*').length) + shadowElements,
      walked_elements: elementCount,
      text_chars: textCharsTotal,
      doc_height: docH, viewport_height: vpH,
      affordances_collected: affordances.length,
      affordances_uncollected: affordancesUncollected,
      headings_uncollected: Math.max(0, headings.length - MAX_HEADINGS),
      affordance_cap_hit: affordancesUncollected > 0,
      region_cap_hit: regions.length >= MAX_REGIONS,
      depth_cut_subtrees: deepestCut,
      extract_ms: Math.round((performance.now() - t0) * 10) / 10
    }
  };
}
