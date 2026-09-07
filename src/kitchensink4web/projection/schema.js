// KS4Web schema-directed source collection: the four evidence tiers.
//
// One in-page pass produces every candidate `{key, value}` pair the page
// offers, grouped by the TIER of evidence that produced it. The tier boundary
// is "who asserted the relationship between the label and the value": the
// page's machine-readable declaration, the page's HTML semantics, the page's
// DOM structure, or nobody. There is no fifth tier, because the fifth tier is
// guessing.
//
// NOTHING HERE MATCHES. This file collects and the Python side matches, for
// the same reason `extract.js` collects and `ranker.py` selects: the matcher
// is where the confident-wrong-answer defects live, and a matcher in page
// script is a matcher a page can profile against.
//
// THE HIDDEN CHECK IS THE SHARED ONE. `ksHiddenAnywhere` is spliced from
// `visibility.js` above, never re-expressed. Three private copies of that rule
// is the drift `visibility.js` was created to end, and a divergence between
// two visibility detectors is a page-controlled channel for showing one thing
// to a human and another to the agent.
//
// WHERE THE HIDDEN CHECK APPLIES, and the line is principled rather than
// convenient: a value read from RENDERED TEXT is a claim about what a human
// sees, so it must pass. A value read from an ATTRIBUTE (`content`,
// `datetime`, JSON-LD source text) is a DECLARATION, which is not rendered by
// definition; `<meta>` computes to `display:none` in every browser, so
// applying the check there would drop every machine-readable source on the
// web. Both facts are reported: a text value carries `from: "text"` and an
// attribute value carries `from: "attr"`.
//
// GEOMETRY IS REPORTED, NEVER A FINDER. Tier 3 records the pixel gap between
// a label and the value it settled on, and nothing in this file consults it.
// A relation the DOM does not declare is not rescued by two boxes happening to
// sit near each other.
(opts) => {
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_VISIBILITY@@
// @@KS4WEB_RENDERED@@
  const caps = opts.caps || {};
  const KEY_CLIP = caps.key_clip || 90;
  const VALUE_CLIP = caps.value_clip || 300;
  const MAX_LEAVES = caps.leaves || 6000;
  const MAX_DECLARED = caps.declared || 1200;
  const MAX_LABELED = caps.labeled || 800;
  const MAX_PROXIMATE = caps.proximate || 800;
  const MAX_HINT = caps.hint || 900;
  const MAX_JSONLD_NODES = caps.json_ld_nodes || 400;
  // A tier-3 VALUE that is a paragraph is not a value, it is prose. The prose
  // decoy is the fixture: a blog post whose heading reads "Pricing" and whose
  // next sibling is four hundred characters about pricing has a label-shaped
  // leaf and a next-element sibling, and every structural test passes. What
  // separates it from a real `Price: $49.99` pair is the SIZE of the thing on
  // the right.
  const VALUE_SHAPE_MAX = caps.value_shape_max || 120;

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };

  let root = null;
  if (opts.root) {
    root = KS.refs.get(opts.root) || null;
    if (!root) return { error: 'ROOT_GONE', asked_for: opts.root };
  }
  const scoped = !!root;
  // THE ROOT OF AN UNSCOPED READ IS THE DOCUMENT ELEMENT, not the body. Every
  // machine-readable declaration a page makes lives in `<head>`: the JSON-LD
  // blocks, the meta tags, the canonical link. A sweep rooted at `<body>` (the
  // prose reads' root, which is right for prose) collects the rendered half of
  // the page and none of the declared half, so the DECLARED tier comes back
  // empty and the ladder answers from the tier below it. That is a wrong
  // answer arrived at by an omission, which is the shape this build refuses.
  const scope = root || document.documentElement || document.body;

  const declared = [], labeled = [], proximate = [], hint = [];
  const counts = { walked: 0, leaves_scanned: 0, json_ld_blocks: 0,
                   json_ld_invalid: 0, json_ld_nodes: 0,
                   hidden_values_excluded: 0, secret_fields: 0,
                   shadow_roots_read: 0 };
  const capped = {};
  function note(list, name, limit, rec) {
    if (list.length >= limit) { capped[name] = (capped[name] || 0) + 1; return; }
    list.push(rec);
  }

  // A short element descriptor, for `where`. Page-authored (the id and the
  // class tokens are the page's own strings), so it rides the envelope with
  // everything else.
  function where(el) {
    if (!el || !el.tagName) return '';
    let out = el.tagName.toLowerCase();
    if (el.id) out += '#' + clip(el.id, 40);
    else {
      const cls = (typeof el.className === 'string' ? el.className : '')
        .trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
      if (cls) out += '.' + clip(cls, 40);
    }
    return out;
  }

  // Rendered text is subject to the shared hidden rule; a declaration is not.
  function visibleText(el) {
    const reason = ksHiddenAnywhere(el);
    if (reason) { counts.hidden_values_excluded++; return null; }
    return squash(ksRenderedText(el));
  }

  // ------------------------------------------------------ TIER 1: DECLARED

  function pushDeclared(key, value, by, el, from) {
    key = clip(key, KEY_CLIP);
    value = clip(value, VALUE_CLIP);
    if (!key) return;
    note(declared, 'declared', MAX_DECLARED, {
      key: key, value: value, by: by, where: where(el), from: from,
      empty: !value });
  }

  // JSON-LD, walked including `@graph`, with dotted paths and the node's own
  // `@type` carried in `by`. Depth- and node-bounded, because a page picks the
  // size of its own JSON-LD and an unbounded walk is a payload the page chose.
  function walkJsonLd(node, path, type, state) {
    if (!node || typeof node !== 'object') return;
    if (state.nodes++ > MAX_JSONLD_NODES) return;
    counts.json_ld_nodes = state.nodes;
    if (Array.isArray(node)) {
      for (let i = 0; i < node.length && i < 40; i++) {
        walkJsonLd(node[i], path, type, state);
      }
      return;
    }
    const own = node['@type'] ? String(node['@type']) : type;
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (v == null) continue;
      if (k === '@graph') { walkJsonLd(v, path, own, state); continue; }
      if (k.charAt(0) === '@') continue;
      const key = path ? path + '.' + k : k;
      if (typeof v === 'object') {
        if (Array.isArray(v)) {
          const flat = v.filter((x) => x != null && typeof x !== 'object');
          if (flat.length) {
            pushDeclared(key, flat.join(', '),
                         own ? 'json-ld(' + own + ')' : 'json-ld',
                         state.el, 'attr');
          }
          walkJsonLd(v, key, own, state);
        } else {
          walkJsonLd(v, key, own, state);
        }
        continue;
      }
      pushDeclared(key, String(v),
                   own ? 'json-ld(' + own + ')' : 'json-ld', state.el, 'attr');
    }
  }

  // ------------------------------------------------------- TIER 2: LABELED

  function pushLabeled(key, value, by, el, from, extra) {
    key = clip(key, KEY_CLIP);
    if (!key) return;
    const rec = { key: key, value: clip(value == null ? '' : value, VALUE_CLIP),
                  by: by, where: where(el), from: from };
    rec.empty = !rec.value;
    if (extra) for (const k of Object.keys(extra)) rec[k] = extra[k];
    note(labeled, 'labeled', MAX_LABELED, rec);
  }

  // ----------------------------------------------------- TIER 3: PROXIMATE
  //
  // A visible label-shaped leaf and a value in ONE OF THREE NAMED STRUCTURAL
  // RELATIONS. The list is closed and each relation is reported by name.

  // A label does not ask a question and does not exclaim. `?` and `!` are
  // excluded for that reason and it is load-bearing: an article heading
  // reading "What about the price?" is a leaf, is inside the length bound, and
  // has a paragraph as its next sibling, so without this rule the prose decoy
  // answers `price` with four hundred characters of blog post.
  const LABEL_SHAPE = /^[^\W\d_][^?!]{0,38}:?$/u;
  function labelShaped(text) {
    if (text.length < 2 || text.length > 40) return false;
    if (!LABEL_SHAPE.test(text)) return false;
    return /[^\W\d_]/u.test(text);            // at least one letter
  }

  function valueShaped(text) {
    return !!text && text.length <= VALUE_SHAPE_MAX;
  }

  function gapPx(a, b) {
    try {
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const dx = Math.max(0, Math.max(ra.left, rb.left) - Math.min(ra.right, rb.right));
      const dy = Math.max(0, Math.max(ra.top, rb.top) - Math.min(ra.bottom, rb.bottom));
      return Math.round(Math.sqrt(dx * dx + dy * dy));
    } catch (e) { return null; }
  }

  const CELL = 'td, th, [role="cell"], [role="gridcell"], [role="columnheader"], [role="rowheader"]';

  function proximateFor(leaf, label) {
    // 1. next-sibling: the label element's immediate next element sibling.
    const sib = leaf.nextElementSibling;
    if (sib) return { el: sib, relation: 'next-sibling' };
    // 2. parent-next-sibling: the label is the only child of its box, and the
    //    value is that box's next sibling.
    const box = leaf.parentElement;
    if (box && box.children.length === 1 && box.nextElementSibling
        && !box.matches(CELL)) {
      return { el: box.nextElementSibling, relation: 'parent-next-sibling' };
    }
    // 3. same-row-next-cell: label in a cell, value in the next.
    const cell = leaf.matches(CELL) ? leaf
      : (leaf.closest ? leaf.closest(CELL) : null);
    if (cell && cell.nextElementSibling
        && squash(ksRenderedText(cell)) === label) {
      return { el: cell.nextElementSibling, relation: 'same-row-next-cell' };
    }
    return null;
  }

  // ---------------------------------------------------- TIER 4: PAGE-HINT
  //
  // The page's own class / id / data-testid tokens name the datum. Weak
  // evidence by construction (a token soup produces ~900 candidates on a
  // Wikipedia page), which is why the Python side keeps this tier off unless
  // the caller names it.
  //
  // A token whose element carries NO TEXT is recorded with no value and marked
  // `styling_only`. That is the `class="star-rating Three"` case: a human sees
  // three stars and the page never wrote the number anywhere. Reading it would
  // mean the tool learning one site's private encoding, so it stays silent and
  // says why, in every tier including this one.
  const HINT_SKIP = /^(?:col|row|is|has|js|no|ng|v|u|p|m|mt|mb|ml|mr|px|py|d|w|h|sm|md|lg|xl|xs|active|hidden|show|hide|clearfix|container|wrapper|inner|outer|left|right|center|top|bottom|first|last|odd|even)(?:-|$)/;
  function hintTokens(el) {
    const out = [];
    const raw = [];
    if (el.id) raw.push(el.id);
    const cls = (typeof el.className === 'string' ? el.className : '');
    if (cls) for (const t of cls.trim().split(/\s+/)) raw.push(t);
    const testid = el.getAttribute ? (el.getAttribute('data-testid')
      || el.getAttribute('data-test-id') || el.getAttribute('data-test')) : null;
    if (testid) raw.push(testid);
    for (const token of raw) {
      if (!token || token.length < 3 || token.length > 60) continue;
      if (HINT_SKIP.test(token)) continue;
      out.push(token);
      if (out.length >= 4) break;
    }
    return out;
  }

  // ------------------------------------------------------------- ONE SWEEP

  const INTERACTIVE = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="textbox"], [tabindex]';
  const SECRET_AC = /current-password|new-password|one-time-code|cc-number|cc-csc/;

  function visit(el) {
    counts.walked++;
    const tag = el.tagName;
    if (tag === 'SCRIPT') {
      if ((el.getAttribute('type') || '').toLowerCase() === 'application/ld+json') {
        counts.json_ld_blocks++;
        try {
          walkJsonLd(JSON.parse(el.textContent), '', null,
                     { nodes: 0, el: el });
        } catch (e) { counts.json_ld_invalid++; }
      }
      return;
    }
    if (tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEMPLATE') return;

    // --- tier 1 ---------------------------------------------------------
    if (tag === 'META') {
      const key = el.getAttribute('name') || el.getAttribute('property')
        || el.getAttribute('itemprop');
      const content = squash(el.getAttribute('content'));
      if (key && content) pushDeclared(key, content, 'meta', el, 'attr');
      return;
    }
    const itemprop = el.getAttribute ? el.getAttribute('itemprop') : null;
    if (itemprop) {
      const holder = el.closest ? el.closest('[itemscope][itemtype]') : null;
      const itemtype = holder ? (holder.getAttribute('itemtype') || '') : '';
      const short = itemtype ? itemtype.split(/[\/#]/).pop() : '';
      const by = short ? 'microdata(' + short + ')' : 'microdata';
      const attr = el.getAttribute('content') || el.getAttribute('datetime');
      if (attr != null && squash(attr)) {
        pushDeclared(itemprop, attr, by, el, 'attr');
      } else {
        const text = visibleText(el);
        if (text) pushDeclared(itemprop, text, by, el, 'text');
      }
    }
    const rdfa = el.getAttribute ? el.getAttribute('property') : null;
    if (rdfa && tag !== 'META') {
      const attr = el.getAttribute('content');
      if (attr != null && squash(attr)) {
        pushDeclared(rdfa, attr, 'rdfa', el, 'attr');
      } else {
        const text = visibleText(el);
        if (text) pushDeclared(rdfa, text, 'rdfa', el, 'text');
      }
    }
    if (tag === 'TIME') {
      const dt = squash(el.getAttribute('datetime'));
      if (dt) pushDeclared('datetime', dt, 'time', el, 'attr');
    }

    // --- tier 2 ---------------------------------------------------------
    if (tag === 'DL') {
      let dt = null;
      for (const child of el.children) {
        if (child.tagName === 'DT') dt = squash(ksRenderedText(child));
        else if (child.tagName === 'DD' && dt) {
          const text = visibleText(child);
          if (text !== null) {
            pushLabeled(dt, text, 'definition-list', child, 'text');
          }
        }
      }
    }
    if (tag === 'TR' && el.cells && el.cells.length === 2) {
      const k = squash(ksRenderedText(el.cells[0]));
      if (k && k.length < 80) {
        const text = visibleText(el.cells[1]);
        if (text !== null) {
          pushLabeled(k, text, 'table-row', el.cells[1], 'text');
        }
      }
    }
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
      const type = (el.type || '').toLowerCase();
      const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
      let label = '';
      if (el.labels && el.labels.length) label = squash(ksRenderedText(el.labels[0]));
      if (!label) {
        label = squash(el.getAttribute('aria-label')
          || el.getAttribute('placeholder') || el.name || '');
      }
      // THE VALUE OF A SECRET FIELD IS NEVER READ, not read-then-redacted: a
      // redaction that runs after the value is in memory has already lost on
      // any path that logs before it. The DESCRIPTOR travels instead, and
      // `policy/credentials.py` re-derives the classification server-side, so
      // this in-page rule is a floor rather than the authority.
      const pageSecret = (type === 'password' || type === 'hidden'
                          || SECRET_AC.test(ac));
      if (label) {
        if (pageSecret) counts.secret_fields++;
        pushLabeled(label, pageSecret ? '' : (
          tag === 'SELECT'
            ? (el.selectedOptions.length
               ? squash(ksRenderedText(el.selectedOptions[0])) : '')
            : squash(el.value)),
          'form-field', el, 'attr', {
            secret: pageSecret, type: type, autocomplete: ac,
            name: clip(el.name || '', 60), label: clip(label, KEY_CLIP),
            attr_id: clip(el.id || '', 60),
            placeholder: clip(el.getAttribute('placeholder') || '', 60) });
      }
    }
    const aria = el.getAttribute ? el.getAttribute('aria-label') : null;
    const ariaBy = el.getAttribute ? el.getAttribute('aria-labelledby') : null;
    if ((aria || ariaBy) && !(el.matches && el.matches(INTERACTIVE))) {
      let key = squash(aria);
      if (!key && ariaBy) {
        const t = document.getElementById(String(ariaBy).split(/\s+/)[0]);
        key = t ? squash(ksRenderedText(t)) : '';
      }
      if (key) {
        const text = visibleText(el);
        if (text) pushLabeled(key, text, 'aria-label', el, 'text');
      }
    }

    // --- tier 3 ---------------------------------------------------------
    if (el.children.length === 0 && counts.leaves_scanned < MAX_LEAVES) {
      counts.leaves_scanned++;
      const raw = squash(ksRenderedText(el));
      if (labelShaped(raw)) {
        const label = raw.replace(/:$/, '').trim();
        if (label && !ksHiddenAnywhere(el)) {
          const found = proximateFor(el, raw);
          if (found && found.el) {
            const text = visibleText(found.el);
            if (text !== null && valueShaped(text)) {
              note(proximate, 'proximate', MAX_PROXIMATE, {
                key: clip(label, KEY_CLIP), value: clip(text, VALUE_CLIP),
                by: found.relation, relation: found.relation,
                where: where(found.el), from: 'text',
                gap_px: gapPx(el, found.el), empty: false });
            }
          }
        }
      }
    }

    // --- tier 4 ---------------------------------------------------------
    if (hint.length < MAX_HINT) {
      const tokens = hintTokens(el);
      if (tokens.length) {
        const hidden = ksHiddenAnywhere(el);
        const text = hidden ? null : squash(ksRenderedText(el));
        for (const token of tokens) {
          note(hint, 'hint', MAX_HINT, {
            key: clip(token, KEY_CLIP),
            value: (text && text.length <= VALUE_SHAPE_MAX) ? clip(text, VALUE_CLIP) : '',
            by: 'page-hint', where: where(el), from: 'text',
            styling_only: !(text && text.length <= VALUE_SHAPE_MAX),
            empty: !(text && text.length <= VALUE_SHAPE_MAX) });
        }
      }
    }
  }

  // document.title is a DECLARATION about the whole document, so it is
  // collected only for an unscoped read: a read scoped to one product card on
  // a listing page must not be able to answer from the page's own title.
  if (!scoped) {
    const title = squash(document.title);
    if (title) pushDeclared('title', title, 'document-title', null, 'attr');
  }

  const completed = ksDeepEach(scope, function (el) {
    if (el.shadowRoot) counts.shadow_roots_read++;
    visit(el);
  });

  return {
    declared: declared, labeled: labeled, proximate: proximate, hint: hint,
    counts: counts, capped: capped, scoped: scoped, walk_completed: completed,
    url: location.href,
  };
}
