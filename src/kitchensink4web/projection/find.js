// KS4Web targeted search: the cheap follow-up half of the flagship pair.
//
// DESIGN 1.1 and 3.1. The first read makes the model know what string to
// search for; this retrieves it for tens of tokens. That pairing is the
// claim, and the limit is stated in the same breath rather than in a
// footnote: an arbitrary in-prose link on a 2,858-link article is not
// one-readable at any budget, and this is what gets it.
//
// **This search is NOT the projection's walk and must not be.** The extractor
// caps what it RETURNS at 300 affordances, which is right for an orientation
// and fatal here: the Fourteen Points link on the Treaty of Versailles
// article sits somewhere past the two thousandth in-prose link, so a search
// built on the capped list could not find the one element the whole
// positioning rests on. So this pass searches every candidate and caps only
// the MATCHES.
//
// It mints anchor descriptors in the same shape the extractor mints them, so
// a found element gets a ref from the same sticky map and is immediately
// actionable. DESIGN 3.5: there is no operation whose only purpose is to
// unlock other operations.
(opts) => {
  const query = opts.query || '';
  const kind = opts.kind || 'auto';
  const limit = Math.max(1, Math.min(200, opts.limit || 20));
  const t0 = performance.now();

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  function clip(s, n) {
    s = squash(s);
    if (s.length <= n) return s;
    let cut = s.lastIndexOf(' ', n);
    if (cut < n * 0.6) cut = n;
    return s.slice(0, cut) + '...';
  }

  const styleCache = new Map();
  function cs(el) {
    let v = styleCache.get(el);
    if (v === undefined) { v = getComputedStyle(el); styleCache.set(el, v); }
    return v;
  }
  function hiddenAnywhere(el) {
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return true;
      if (n.hasAttribute && n.hasAttribute('hidden')) return true;
      const s = cs(n);
      if (s.display === 'none' || s.visibility === 'hidden') return true;
      if (parseFloat(s.opacity) === 0) return true;
    }
    return false;
  }

  const TAG_ROLE = {
    A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox',
    SUMMARY: 'button', OPTION: 'option', IMG: 'img', TABLE: 'table',
    H1: 'heading', H2: 'heading', H3: 'heading', H4: 'heading',
    H5: 'heading', H6: 'heading'
  };
  const INPUT_ROLE = {
    checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button',
    reset: 'button', image: 'button', range: 'slider', file: 'file-input',
    search: 'searchbox', email: 'textbox', password: 'textbox',
    text: 'textbox', tel: 'textbox', url: 'textbox', number: 'spinbutton'
  };
  function roleOf(el) {
    const explicit = el.getAttribute && el.getAttribute('role');
    if (explicit) return explicit.trim().split(/\s+/)[0];
    if (el.tagName === 'INPUT') return INPUT_ROLE[(el.type || 'text').toLowerCase()] || 'textbox';
    if (el.tagName === 'A') return el.hasAttribute('href') ? 'link' : 'generic';
    return TAG_ROLE[el.tagName] || 'generic';
  }
  // Deliberately simpler than the extractor's accname walk and deliberately
  // never a raw `textContent` on a container: aria-label, then the label
  // element, then the element's own text when the role takes its name from
  // content. A search that matched on a container's concatenated text would
  // report a hit on a whole page section.
  const NAME_FROM_CONTENT = new Set(['button', 'link', 'heading', 'tab',
    'menuitem', 'option', 'checkbox', 'radio', 'switch', 'cell',
    'columnheader', 'rowheader', 'gridcell', 'treeitem']);
  function nameOf(el, role) {
    const al = squash(el.getAttribute && el.getAttribute('aria-label'));
    if (al) return al;
    const lb = el.getAttribute && el.getAttribute('aria-labelledby');
    if (lb) {
      const t = document.getElementById(lb.trim().split(/\s+/)[0]);
      if (t) { const s = squash(t.textContent); if (s) return s; }
    }
    try {
      if (el.labels && el.labels.length) {
        const s = squash(Array.from(el.labels).map(l => l.textContent).join(' '));
        if (s) return s;
      }
    } catch (e) { /* labels can throw on exotic shadow hosts */ }
    if (el.tagName === 'INPUT') {
      const type = (el.type || '').toLowerCase();
      if ((type === 'submit' || type === 'button' || type === 'reset')
          && typeof el.value === 'string') return squash(el.value);
      const ph = el.getAttribute('placeholder');
      if (squash(ph)) return squash(ph);
      return '';
    }
    if (el.tagName === 'IMG') return squash(el.getAttribute('alt'));
    if (NAME_FROM_CONTENT.has(role)) return squash(el.textContent);
    const tt = el.getAttribute && el.getAttribute('title');
    return squash(tt);
  }

  const LM_TAG = {
    HEADER: 'banner', NAV: 'navigation', MAIN: 'main', ASIDE: 'complementary',
    FOOTER: 'contentinfo', FORM: 'form', SECTION: 'region', DIALOG: 'dialog'
  };
  const LM_ROLE = new Set(['banner', 'navigation', 'main', 'complementary',
    'contentinfo', 'form', 'region', 'search', 'dialog', 'alertdialog',
    'tablist']);
  function landmarkOf(el) {
    for (let n = el.parentElement; n; n = n.parentElement) {
      const explicit = (n.getAttribute('role') || '').trim().split(/\s+/)[0];
      const k = (explicit && LM_ROLE.has(explicit)) ? explicit : LM_TAG[n.tagName];
      if (!k) continue;
      const label = squash(n.getAttribute('aria-label'))
        || squash(n.getAttribute('name'));
      if (n.tagName === 'SECTION' && !label) continue;
      return { node: n, kind: k, label: label || '' };
    }
    return { node: document.body, kind: 'document', label: '' };
  }
  function labelledAncestorOf(el, stopAt) {
    for (let n = el.parentElement; n && n !== stopAt; n = n.parentElement) {
      const al = squash(n.getAttribute('aria-label'));
      if (al) return al;
    }
    return '';
  }

  const PAGE_KEY = location.origin + location.pathname + location.hash;
  const ordinals = {};
  function anchorOf(el, role, name) {
    const lm = landmarkOf(el);
    const scope = lm.kind + ':' + lm.label + '|' + role;
    ordinals[scope] = (ordinals[scope] || 0) + 1;
    return {
      page_key: PAGE_KEY, role: role, name: name,
      landmark: lm.kind, landmark_label: lm.label,
      labelled_ancestor: labelledAncestorOf(el, lm.node),
      ordinal: ordinals[scope],
      attr_id: el.id || '',
      attr_testid: el.getAttribute('data-testid') || '',
      attr_name: el.getAttribute('name') || ''
    };
  }

  // ------------------------------------------------------ candidate sets

  const INTERACTIVE_SEL = 'a[href],button,input,select,textarea,summary,'
    + '[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],'
    + '[role=menuitem],[role=switch],[role=combobox],[role=searchbox],'
    + '[role=textbox],[role=option],[role=slider],[onclick],'
    + '[tabindex]:not([tabindex="-1"])';

  let candidates = [], how = kind, selectorError = null;
  try {
    if (kind === 'css') {
      candidates = Array.from(document.querySelectorAll(query));
    } else if (kind === 'xpath') {
      const it = document.evaluate(query, document, null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      for (let i = 0; i < it.snapshotLength; i++) candidates.push(it.snapshotItem(i));
      candidates = candidates.filter(n => n.nodeType === 1);
    } else {
      // `auto` and `text` both search the interactive surface first, because
      // a found element that cannot be acted on is the operation this design
      // says should not exist. `any` widens to every element with text.
      candidates = Array.from(document.querySelectorAll(
        kind === 'any' ? '*' : INTERACTIVE_SEL));
      how = kind === 'any' ? 'any element' : 'interactive elements';
    }
  } catch (e) {
    selectorError = String(e && e.message || e);
    candidates = [];
  }

  const needle = query.toLowerCase();
  const matches = [];
  let total = 0, hiddenMatches = 0;
  for (const el of candidates) {
    if (!el || el.nodeType !== 1) continue;
    const role = roleOf(el);
    const name = nameOf(el, role);
    let hit;
    if (kind === 'css' || kind === 'xpath') {
      hit = true;
    } else {
      const hay = (name + ' ' + (el.getAttribute('title') || '') + ' '
        + (el.getAttribute('placeholder') || '')).toLowerCase();
      hit = needle ? hay.indexOf(needle) >= 0 : false;
    }
    if (!hit) continue;
    total++;
    if (hiddenAnywhere(el)) { hiddenMatches++; continue; }
    if (matches.length >= limit) continue;
    const ref = 'x' + (window.__ks4web_seq = (window.__ks4web_seq || 0) + 1);
    if (!window.__ks4web_refs) window.__ks4web_refs = new Map();
    window.__ks4web_refs.set(ref, el);
    let path = null;
    if (el.tagName === 'A') {
      try {
        const u = new URL(el.href, location.href);
        path = u.origin !== location.origin ? u.origin + u.pathname
          : (u.pathname + u.search + u.hash);
      } catch (e) { path = el.getAttribute('href'); }
    }
    const rect = el.getBoundingClientRect();
    matches.push({
      ref: ref, anchor: anchorOf(el, role, clip(name, 80)),
      role: role, name: clip(name, 80), path: path,
      state: [el.disabled ? 'disabled' : '', el.checked ? 'checked' : '',
              el.required ? 'required' : ''].filter(Boolean).join(','),
      in_viewport: rect.top < window.innerHeight && rect.bottom > 0,
      top: Math.round(rect.top + window.scrollY)
    });
  }

  // Nearest misses, so a zero-result search is a one-turn recovery rather
  // than a dead end. Cheap: it only runs when nothing matched.
  const near = [];
  if (!matches.length && needle && kind !== 'css' && kind !== 'xpath') {
    const seen = new Set();
    for (const el of candidates) {
      const role = roleOf(el);
      const name = nameOf(el, role);
      if (!name || seen.has(name)) continue;
      const low = name.toLowerCase();
      let score = 0;
      for (const word of needle.split(/\s+/)) {
        if (word && low.indexOf(word) >= 0) score++;
      }
      if (score) { seen.add(name); near.push({ name: clip(name, 60), role: role, score: score }); }
      if (near.length > 200) break;
    }
    near.sort((a, b) => b.score - a.score);
    near.length = Math.min(near.length, 6);
  }

  let closedShadow = window.__ks4web_closed_shadow || 0;
  let openShadow = 0, frames = 0;
  for (const el of document.querySelectorAll('*')) {
    if (el.shadowRoot) openShadow++;
    if (el.tagName === 'IFRAME') frames++;
  }

  return {
    query: query, kind: kind, searched: how,
    selector_error: selectorError,
    candidates_scanned: candidates.length,
    matches: matches,
    total_matches: total,
    returned: matches.length,
    hidden_matches: hiddenMatches,
    nearest_misses: near,
    not_searched: {
      open_shadow_roots: openShadow,
      closed_shadow_roots: closedShadow,
      iframes: frames
    },
    url: location.href,
    page_key: PAGE_KEY,
    ms: Math.round((performance.now() - t0) * 10) / 10
  };
}
