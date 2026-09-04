// S2: the in-page half of the anchor scheme.
//
// One pass over the interactive surface producing, per element, the
// content-derived descriptor DESIGN 3.5 specifies: role, accessible name, a
// scoping path (nearest landmark, then nearest labelled ancestor, then ordinal
// among same-role siblings), stable attributes when present, and the origin
// and path it was minted on.
//
// Two fields here are INSTRUMENTS rather than parts of the scheme, and they
// are marked so nothing downstream can confuse them for signal:
//
//  * `truth` is the fixture's own semantic identity (`data-truth`). It is the
//    harness's ground truth and the anchor scheme never reads it. A scheme
//    that fingerprinted it would score a perfect run and mean nothing.
//  * `node_uid` is a per-DOM-node serial handed out from a WeakMap that
//    outlives the evaluate. It answers "did this DOM node survive" as
//    distinct from "did this element survive", which is exactly the
//    distinction a React re-render destroys and the one chrome-devtools-mcp's
//    backendNodeId scheme depends on.
() => {
  if (!window.__s2_nodes) { window.__s2_nodes = new WeakMap(); window.__s2_seq = 0; }
  // Dies with the document and survives pushState, which is exactly the line
  // between "the app routed" and "the browser navigated". The design says a
  // URL change means cross-page; an SPA changes the URL without changing the
  // document, so the two policies are measured against each other rather than
  // assumed to be the same policy.
  if (!window.__s2_doc) window.__s2_doc = String(Date.now()) + ':' + Math.random();
  const uid = (el) => {
    let v = window.__s2_nodes.get(el);
    if (v === undefined) { v = ++window.__s2_seq; window.__s2_nodes.set(el, v); }
    return v;
  };

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();

  const LANDMARK_TAG = {
    HEADER: 'banner', NAV: 'navigation', MAIN: 'main', ASIDE: 'complementary',
    FOOTER: 'contentinfo', FORM: 'form', SECTION: 'region',
  };
  const LANDMARK_ROLE = new Set(['banner', 'navigation', 'main', 'complementary',
    'contentinfo', 'form', 'region', 'search', 'dialog', 'tablist']);

  const TAG_ROLE = {
    A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox',
    SUMMARY: 'button', OPTION: 'option',
  };
  const INPUT_ROLE = {
    checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button',
    reset: 'button', search: 'searchbox', email: 'textbox', password: 'textbox',
    text: 'textbox', tel: 'textbox', url: 'textbox', number: 'spinbutton',
  };

  function roleOf(el) {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.trim().split(/\s+/)[0];
    if (el.tagName === 'INPUT') return INPUT_ROLE[(el.type || 'text').toLowerCase()] || 'textbox';
    return TAG_ROLE[el.tagName] || el.tagName.toLowerCase();
  }

  function nameOf(el) {
    const labelled = el.getAttribute('aria-labelledby');
    if (labelled) {
      const parts = labelled.split(/\s+/).map(id => {
        const t = document.getElementById(id);
        return t ? squash(t.textContent) : '';
      }).filter(Boolean);
      if (parts.length) return squash(parts.join(' '));
    }
    const al = el.getAttribute('aria-label');
    if (squash(al)) return squash(al);
    if (el.labels && el.labels.length) {
      const t = squash(Array.from(el.labels).map(l => l.textContent).join(' '));
      if (t) return t;
    }
    if (el.tagName === 'INPUT') {
      const type = (el.type || '').toLowerCase();
      if ((type === 'submit' || type === 'button') && typeof el.value === 'string') {
        return squash(el.value);
      }
      const ph = el.getAttribute('placeholder');
      if (squash(ph)) return squash(ph);
      return '';
    }
    if (el.tagName === 'IMG') return squash(el.getAttribute('alt'));
    return squash(el.textContent);
  }

  function accessibleAncestorName(el, stopAt) {
    for (let n = el.parentElement; n && n !== stopAt; n = n.parentElement) {
      const al = squash(n.getAttribute('aria-label'));
      if (al) return al;
      const lb = n.getAttribute('aria-labelledby');
      if (lb) {
        const t = document.getElementById(lb.split(/\s+/)[0]);
        if (t && squash(t.textContent)) return squash(t.textContent);
      }
    }
    return '';
  }

  function landmarkOf(el) {
    for (let n = el.parentElement; n; n = n.parentElement) {
      const explicit = n.getAttribute('role');
      const kind = (explicit && LANDMARK_ROLE.has(explicit)) ? explicit
        : LANDMARK_TAG[n.tagName];
      if (!kind) continue;
      // An unlabelled <section> is not a landmark, per the HTML-AAM rule, and
      // treating it as one would scope anchors to a container the page does
      // not consider structural.
      const label = squash(n.getAttribute('aria-label'))
        || squash(n.getAttribute('name'))
        || (n.tagName === 'FORM' ? squash(n.getAttribute('name')) : '');
      if (n.tagName === 'SECTION' && !label) continue;
      return {node: n, kind: kind, label: label};
    }
    return {node: document.body, kind: 'document', label: ''};
  }

  const SELECTOR = 'a[href], button, input, select, textarea, summary, '
    + '[role="button"], [role="link"], [role="tab"], [role="menuitem"], '
    + '[role="checkbox"], [role="radio"], [role="switch"]';

  const out = [];
  const roleCounters = new Map();
  for (const el of document.querySelectorAll(SELECTOR)) {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if (el.type === 'hidden') continue;
    const lm = landmarkOf(el);
    const role = roleOf(el);
    const lmKey = lm.kind + ':' + lm.label;
    const counterKey = lmKey + '|' + role;
    const ordinal = (roleCounters.get(counterKey) || 0) + 1;
    roleCounters.set(counterKey, ordinal);
    out.push({
      truth: el.getAttribute('data-truth'),      // INSTRUMENT, never fingerprinted
      node_uid: uid(el),                          // INSTRUMENT, never fingerprinted
      tag: el.tagName,
      role: role,
      name: nameOf(el).slice(0, 80),
      landmark: lm.kind,
      landmark_label: lm.label,
      labelled_ancestor: accessibleAncestorName(el, lm.node),
      ordinal: ordinal,
      attr_id: el.id || '',
      attr_testid: el.getAttribute('data-testid') || '',
      attr_name: el.getAttribute('name') || '',
      href_path: el.tagName === 'A' && el.href
        ? (new URL(el.href, location.href)).pathname
          + (new URL(el.href, location.href)).hash
        : '',
      origin: location.origin,
      path: location.pathname,
      // DESIGN 3.5 says an anchor carries "the origin and path pattern it was
      // minted on". The first version of this prototype put those fields in
      // the descriptor and left them OUT of the sticky key, which is how a
      // ref minted on one page came back bound to a same-named control on
      // another. The hash is in here because an SPA route lives there and
      // two routes are two pages by every meaning that matters to a ref.
      page_key: location.origin + location.pathname + location.hash,
    });
  }
  const dialog = document.querySelector('[role="dialog"][aria-modal="true"], dialog[open]');
  return {
    elements: out,
    url: location.href,
    origin: location.origin,
    path: location.pathname,
    doc_epoch: window.__s2_doc,
    modal: dialog ? (squash(dialog.getAttribute('aria-label')) || 'dialog') : null,
  };
}
