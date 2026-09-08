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
//
// The search reaches into OPEN shadow roots (2026-09-06). Closed roots stay
// unreachable and are counted at creation instead. XPath is the exception and
// searches the light DOM only.
//
// `opts.root` SCOPES the search to one subtree (2026-09-06). It arrived with
// the location grammar and was never read: `find_elements(location={'region':
// 'r7'})` computed a scope root, handed it here, and got a whole-page search
// back with a result line that did not say so. A narrowing that silently does
// not narrow is worse than no narrowing, because the caller reasons about a
// region and receives the document. Scope is now enforced in three places at
// once, since one of them alone leaks: the shadow sweep starts AT the root so
// a component inside the region is reached and one outside it is not, every
// selector query runs against the root, and every surviving candidate is
// re-checked for containment with a climb that hops shadow boundaries. XPath
// gets the root as its context node AND the containment check, because an
// absolute expression ignores a context node.
(opts) => {
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_HREF@@
// @@KS4WEB_VISIBILITY@@
// @@KS4WEB_ARIA@@
  const query = opts.query || '';
  const kind = opts.kind || 'auto';
  const wantRole = (opts.role || '').toLowerCase() || null;
  const limit = Math.max(1, Math.min(200, opts.limit || 20));
  const t0 = performance.now();
  const SHADOW_ON = !(opts && opts.shadow === false);

  let scopeRoot = null;
  if (opts.root) {
    scopeRoot = KS.refs.get(opts.root) || null;
    // Same refusal shape the extractor and the text pass return, so one
    // Python branch covers all three.
    if (!scopeRoot || !scopeRoot.isConnected) {
      return { error: 'ROOT_GONE', asked_for: opts.root };
    }
  }
  const searchBase = scopeRoot || document;

  // ONE sweep, and it is the SAME sweep this pass already ran.
  //
  // Before traversal, `find.js` swept `document.querySelectorAll('*')` at the
  // very end purely to count open roots and iframes for the `not_searched`
  // block. The traversal needs exactly that sweep to discover roots, so the
  // two are merged rather than run twice: on a page with no shadow roots the
  // work is byte-for-byte what it always was, which is why the regression on
  // the shadow-free fixture is zero rather than the +2.8 ms the prototype
  // measured with a second sweep bolted on.
  //
  // Roots come back in host order, depth first, so a match inside a root is
  // reported right after the light-DOM matches of the tree that holds it.
  // Under a scope the sweep starts at the scope root, so the counts in
  // `not_searched` describe the region the caller asked about rather than the
  // page it happens to sit on.
  //
  // The recursion itself is `ksOpenRoots`, the ONE deep walk from
  // `visibility.js`, rather than a fourth private copy of it. The copies
  // drifted the way the hidden-detection copies drifted: the occlusion scan's
  // was a flat `querySelectorAll('*')` that stopped at every shadow boundary,
  // and re-attack 2 put an opaque lid inside an open root that this pass
  // would have walked straight into (A3).
  const openRoots = [];
  let frames = 0;
  const countFrames = (el) => { if (el.tagName === 'IFRAME') frames++; };
  // A scope root that is ITSELF a shadow host owns a root the light-DOM
  // sweep below cannot see: `host.querySelectorAll('*')` returns slotted
  // light children, never the component's own tree. Scoping to a component
  // and finding nothing inside it is the exact shape of the defect this
  // block fixes, so the host's own root is taken first and swept.
  if (scopeRoot && scopeRoot.shadowRoot) {
    openRoots.push(scopeRoot.shadowRoot);
    for (const r of ksOpenRoots(scopeRoot.shadowRoot, countFrames)) {
      openRoots.push(r);
    }
  }
  for (const r of ksOpenRoots(searchBase, countFrames)) openRoots.push(r);
  const openShadow = openRoots.length;
  const searchedRoots = SHADOW_ON ? openRoots : [];

  function queryAll(sel) {
    const out = [];
    // The scope root itself is a candidate. `querySelectorAll` on an element
    // returns descendants only, and the extractor counts the root in its own
    // scoped totals (`getElementsByTagName('*').length + 1`), so leaving it
    // out here would make a search for the region's own button miss it.
    if (scopeRoot) {
      try { if (scopeRoot.matches(sel)) out.push(scopeRoot); } catch (e) { /* :has() etc */ }
    }
    for (const el of searchBase.querySelectorAll(sel)) out.push(el);
    for (const root of searchedRoots) {
      for (const el of root.querySelectorAll(sel)) out.push(el);
    }
    // SLOTTED CONTENT, which is inside the region for the person looking at
    // it and outside every DOM query that builds this list. `section
    // .querySelectorAll('*')` returns the component's own tree and the slot
    // element, never the light children the slot renders, so scoping to a
    // component's panel returned "0 of 0 match(es)" for a control sitting
    // visibly inside it (gauntlet 2 M5). Membership follows the FLATTENED
    // tree, here and in `withinScope`, because that is the tree a human sees.
    if (scopeRoot) {
      const slots = [];
      try {
        if (scopeRoot.tagName === 'SLOT') slots.push(scopeRoot);
        for (const s of searchBase.querySelectorAll('slot')) slots.push(s);
        for (const root of searchedRoots) {
          for (const s of root.querySelectorAll('slot')) slots.push(s);
        }
      } catch (e) { /* no slots here */ }
      for (const slot of slots) {
        let assigned = [];
        try { assigned = slot.assignedElements({ flatten: true }); }
        catch (e) { assigned = []; }
        for (const el of assigned) {
          try { if (el.matches(sel)) out.push(el); } catch (e) { /* :has() */ }
          for (const kid of el.querySelectorAll(sel)) out.push(kid);
        }
      }
    }
    // One element can arrive by two routes (a slot inside a searched root
    // that also sits under the base), and a duplicate candidate would count
    // as two matches and refuse a search as ambiguous against itself.
    const seen = new Set(), uniq = [];
    for (const el of out) { if (!seen.has(el)) { seen.add(el); uniq.push(el); } }
    return uniq;
  }

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  function clip(s, n) {
    s = squash(s);
    if (s.length <= n) return s;
    let cut = s.lastIndexOf(' ', n);
    if (cut < n * 0.6) cut = n;
    return s.slice(0, cut) + '...';
  }

  // The shadow-boundary hop, the slot hop, and every hidden technique come
  // from the ONE shared source spliced in above. This file used to carry its
  // own five-technique copy while the extractor's knew eleven, and gauntlet 2
  // (M4) measured what that bought a page: `position:absolute; left:-99999px`
  // came back as `1 of 1 match ... in-view` from here while the same read's
  // completeness block counted the same element as offscreen hidden, and
  // acting on it then dead-ended in a STALE_ANCHOR refusal for an element
  // that was still in the DOM. Two detectors disagreeing is a channel.
  const up = ksUp;
  const cs = ksCS;
  function byId(el, id) {
    const r = el.getRootNode ? el.getRootNode() : document;
    if (r && typeof r.getElementById === 'function') return r.getElementById(id);
    return document.getElementById(id);
  }
  // The scope guarantee, checked per candidate rather than trusted from the
  // query. `Node.contains` does not cross a shadow boundary and an absolute
  // XPath ignores its context node, so a query-side narrowing alone is two
  // silent leaks. The climb is the FLATTENED tree: a slotted node's light
  // parent is the host, so the light-tree climb walked straight past the slot
  // and every ancestor between it and the host, and scoping to a component's
  // own panel returned "0 of 0" for a control rendering inside that panel
  // (gauntlet 2 M5). Membership is what a human sees, so it is the rendered
  // tree that decides it.
  function withinScope(el) {
    if (!scopeRoot) return true;
    for (let n = el; n; n = up(n)) if (n === scopeRoot) return true;
    // A scope root that is a shadow HOST owns the panel its slotted children
    // render into, so its own root counts as inside it.
    if (scopeRoot.shadowRoot) {
      for (let n = el; n; n = up(n)) {
        if (n.getRootNode && n.getRootNode() === scopeRoot.shadowRoot) return true;
      }
    }
    return false;
  }
  // THE PAINT-ORDER CLOAK IS DELIBERATELY NOT ASKED HERE (fix wave 9b, and
  // it was tried the other way first). Every surface that REPORTS CONTENT --
  // `get_text`, `get_article`, the page view's digest, `extract_page` --
  // excludes cloaked text and counts it, because reporting it as ordinary
  // prose is a claim about what a human sees. This surface does something
  // else: it mints refs for the ACTING path, and the acting path owns a
  // better verdict than any read can compute, since only it can run the
  // pixel arbiter that clears box math's false positives. Filtering here
  // substituted the cheaper, more conservative answer for the better one and
  // cost the R4 refusal its whole point: `find_and_act` on `ra/overlay.html`
  // stopped saying "an opaque panel is painted over it" and started saying
  // "nothing visible matches", which is a worse answer about the same fact.
  function hiddenAnywhere(el) { return ksHiddenAnywhere(el) !== null; }

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
      const t = byId(el, lb.trim().split(/\s+/)[0]);
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
      // `<input type=image>` names itself from alt (HTML-AAM). The same
      // rung the extractor was missing, missing here too, so a search for
      // the word on the button could not find the button.
      if (type === 'image') {
        const alt = squash(el.getAttribute('alt') || '');
        if (alt) return alt;
      }
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
    for (let n = up(el); n; n = up(n)) {
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
    for (let n = up(el); n && n !== stopAt; n = up(n)) {
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
      candidates = queryAll(query);
    } else if (kind === 'xpath') {
      // XPath is the one selector that does NOT reach shadow content:
      // `document.evaluate` has no defined behaviour across a shadow
      // boundary, and faking it per root would give expressions like
      // `//body//button` a meaning they do not have. The docstring says so
      // rather than the search quietly answering a smaller question.
      // Under a scope the root is the context node, so `.//a` means what a
      // caller expects. An ABSOLUTE expression ignores a context node, which
      // is why the containment filter below is not optional here.
      const it = document.evaluate(query, scopeRoot || document, null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      for (let i = 0; i < it.snapshotLength; i++) candidates.push(it.snapshotItem(i));
      candidates = candidates.filter(n => n.nodeType === 1);
    } else {
      // `auto` and `text` both search the interactive surface first, because
      // a found element that cannot be acted on is the operation this design
      // says should not exist. `any` widens to every element with text.
      candidates = queryAll(kind === 'any' ? '*' : INTERACTIVE_SEL);
      how = kind === 'any' ? 'any element' : 'interactive elements';
    }
  } catch (e) {
    selectorError = String(e && e.message || e);
    candidates = [];
  }
  if (scopeRoot) candidates = candidates.filter(withinScope);

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
      // A role filter with no query matches every element of that role.
      hit = needle ? hay.indexOf(needle) >= 0 : !!wantRole;
    }
    if (!hit) continue;
    if (wantRole && role !== wantRole) continue;
    total++;
    if (hiddenAnywhere(el)) { hiddenMatches++; continue; }
    if (matches.length >= limit) continue;
    const ref = 'x' + (KS.seq = (KS.seq || 0) + 1);
    KS.refs.set(ref, el);
    KS.refof.set(el, ref);
    let path = null;
    if (el.tagName === 'A') {
      try {
        const u = new URL(ksHref(el), location.href);
        path = u.origin !== location.origin ? u.origin + u.pathname
          : (u.pathname + u.search + u.hash);
      } catch (e) { path = el.getAttribute('href'); }
    }
    const rect = el.getBoundingClientRect();
    matches.push({
      ref: ref, anchor: anchorOf(el, role, clip(name, 80)),
      role: role, name: clip(name, 80), path: path,
      // THE SHARED STATE SOURCE (`aria.js`, spliced above). Three DOM
      // properties and nothing declared is what used to be here, so a tab
      // the page view described as selected came back from a search with an
      // empty state, and the answer to "which tab is active" depended on
      // which tool happened to find the tab.
      state: ksAriaState(el).join(','),
      // BOTH axes. The vertical-only test printed "in-view" for a control
      // parked 99,999 pixels to the left, which is the one word in a result
      // line a caller uses to decide whether an element needs scrolling to.
      in_viewport: rect.top < window.innerHeight && rect.bottom > 0
        && rect.left < window.innerWidth && rect.right > 0,
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

  const closedShadow = KS.closed || 0;
  // What the search actually covered, so the result line can say it. The
  // whole-page case stays null and the sentence stays what it always was.
  let scope = null;
  if (scopeRoot) {
    // A landmark names itself as the landmark the page view called it, not as
    // the 'generic' its tag maps to: a caller who read `r1 | region | "Draft
    // panel"` and scoped to it should see the same words back.
    const explicit = (scopeRoot.getAttribute('role') || '')
      .trim().split(/\s+/)[0];
    const asLandmark = (explicit && LM_ROLE.has(explicit))
      ? explicit : LM_TAG[scopeRoot.tagName];
    const r = roleOf(scopeRoot);
    scope = {
      ref: opts.root,
      role: asLandmark || r,
      name: clip(nameOf(scopeRoot, r)
        || squash(scopeRoot.getAttribute('aria-label')), 60),
      tag: scopeRoot.tagName
    };
  }

  return {
    query: query, kind: kind, searched: how,
    scope: scope,
    selector_error: selectorError,
    candidates_scanned: candidates.length,
    matches: matches,
    total_matches: total,
    returned: matches.length,
    hidden_matches: hiddenMatches,
    nearest_misses: near,
    not_searched: {
      open_shadow_roots: openShadow,
      shadow_roots_searched: searchedRoots.length,
      closed_shadow_roots: closedShadow,
      iframes: frames
    },
    url: location.href,
    page_key: PAGE_KEY,
    ms: Math.round((performance.now() - t0) * 10) / 10
  };
}
