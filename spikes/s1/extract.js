// S1 spike: in-page extraction. Throwaway prototype, not product code.
// Returns one JSON blob: regions, affordances, digest, forms, tables, completeness facts.
() => {
  const CAP_AFF = 600;
  const CAP_REGIONS = 30;

  const txt = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim();

  const styleCache = new Map();
  function cs(el) {
    let v = styleCache.get(el);
    if (!v) { v = getComputedStyle(el); styleCache.set(el, v); }
    return v;
  }

  function hiddenReason(el) {
    if (!el.isConnected) return 'detached';
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
    if (el.hasAttribute && el.hasAttribute('hidden')) return 'hidden-attr';
    const s = cs(el);
    if (s.display === 'none') return 'display-none';
    if (s.visibility === 'hidden' || s.visibility === 'collapse') return 'visibility-hidden';
    if (parseFloat(s.opacity) === 0) return 'opacity-0';
    const fs = parseFloat(s.fontSize);
    if (fs && fs < 2) return 'font-size-0';
    const r = el.getBoundingClientRect();
    if (r.width <= 1 && r.height <= 1) return 'zero-size';
    if (r.right < 0 || r.bottom < 0) {
      if (r.right < -1000 || r.bottom < -1000) return 'offscreen';
    }
    return null;
  }
  const visible = (el) => hiddenReason(el) === null;

  const TAG_ROLE = {
    A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox',
    SUMMARY: 'button', OPTION: 'option', IMG: 'img',
    H1: 'heading', H2: 'heading', H3: 'heading', H4: 'heading', H5: 'heading', H6: 'heading'
  };
  const INPUT_ROLE = {
    checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button',
    reset: 'button', image: 'button', range: 'slider', file: 'file-input',
    search: 'searchbox', email: 'textbox', password: 'textbox', text: 'textbox',
    tel: 'textbox', url: 'textbox', number: 'spinbutton', date: 'textbox',
    hidden: 'hidden', color: 'colorpicker', month: 'textbox', time: 'textbox'
  };

  function roleOf(el) {
    const explicit = el.getAttribute && el.getAttribute('role');
    if (explicit) return explicit.split(/\s+/)[0];
    if (el.tagName === 'INPUT') return INPUT_ROLE[(el.type || 'text').toLowerCase()] || 'textbox';
    if (el.tagName === 'A') return el.hasAttribute('href') ? 'link' : 'generic';
    return TAG_ROLE[el.tagName] || 'generic';
  }

  function accName(el) {
    let n = el.getAttribute && el.getAttribute('aria-label');
    if (n && n.trim()) return n.trim().slice(0, 90);
    const lb = el.getAttribute && el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => {
        const e = document.getElementById(id); return e ? txt(e) : '';
      }).join(' ').trim();
      if (t) return t.slice(0, 90);
    }
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
      try {
        if (el.labels && el.labels.length) {
          const t = Array.from(el.labels).map(l => txt(l)).join(' ').trim();
          if (t) return t.slice(0, 90);
        }
      } catch (e) { }
      if (el.placeholder) return el.placeholder.slice(0, 90);
      if (tag === 'INPUT' && (el.type === 'submit' || el.type === 'button') && el.value) return el.value.slice(0, 90);
      if (el.title) return el.title.slice(0, 90);
      if (el.name) return el.name.slice(0, 90);
      return '';
    }
    if (tag === 'IMG') return (el.alt || '').slice(0, 90);
    let t = txt(el);
    if (!t) {
      const im = el.querySelector && el.querySelector('img[alt]');
      if (im && im.alt) t = im.alt;
    }
    if (!t && el.title) t = el.title;
    if (!t && el.getAttribute) {
      const cls = el.getAttribute('class') || '';
      const dti = el.getAttribute('data-testid') || el.getAttribute('id') || '';
      if (dti) t = '#' + dti;
      else if (cls) t = '.' + cls.split(/\s+/)[0];
    }
    return (t || '').slice(0, 90);
  }

  // ---------- landmark regions ----------
  const LM_TAG = { HEADER: 'banner', NAV: 'navigation', MAIN: 'main', ASIDE: 'complementary', FOOTER: 'contentinfo', FORM: 'form', DIALOG: 'dialog' };
  const LM_ROLE = new Set(['banner', 'navigation', 'main', 'complementary', 'contentinfo', 'search', 'form', 'region', 'dialog', 'alertdialog', 'article', 'tablist', 'menu', 'menubar', 'feed']);

  const cands = Array.from(document.querySelectorAll('header,nav,main,aside,footer,form,dialog,section,[role]'));
  let regionEls = [];
  for (const el of cands) {
    const r = el.getAttribute('role');
    let kind = null;
    if (r && LM_ROLE.has(r.split(/\s+/)[0])) kind = r.split(/\s+/)[0];
    else if (LM_TAG[el.tagName]) kind = LM_TAG[el.tagName];
    else if (el.tagName === 'SECTION' && (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'))) kind = 'region';
    if (!kind) continue;
    if (!visible(el)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.height < 24 && rect.width < 24) continue;
    regionEls.push({ el, kind, rect });
  }
  // unlabeled major containers when the page has few landmarks (app shells)
  if (regionEls.length < 3 && document.body) {
    const walk = Array.from(document.body.querySelectorAll(':scope > div, :scope > div > div'));
    for (const el of walk) {
      if (!visible(el)) continue;
      const rect = el.getBoundingClientRect();
      const n = el.querySelectorAll('*').length;
      if (n < 20) continue;
      if (rect.height < 80) continue;
      if (regionEls.some(x => x.el === el)) continue;
      regionEls.push({ el, kind: 'container', rect });
    }
  }
  // drop a region fully contained by another region of the same kind (dedupe nesting noise)
  regionEls = regionEls.filter((a, i) =>
    !regionEls.some((b, j) => j !== i && b.el !== a.el && b.el.contains(a.el) && b.kind === a.kind));

  if (regionEls.length > CAP_REGIONS) {
    regionEls.sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
    regionEls = regionEls.slice(0, CAP_REGIONS);
  }
  // document order
  regionEls.sort((a, b) => {
    const p = a.el.compareDocumentPosition(b.el);
    return (p & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1;
  });

  const regionOf = new Map();
  const regions = [];
  const INTERACTIVE_SEL = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=switch],[role=combobox],[role=searchbox],[role=textbox],[role=option],[onclick],[tabindex]:not([tabindex="-1"])';

  regionEls.forEach((r, i) => {
    const ref = 'r' + (i + 1);
    regionOf.set(r.el, ref);
    const t = txt(r.el);
    let label = r.el.getAttribute('aria-label') || '';
    if (!label) {
      const lb = r.el.getAttribute('aria-labelledby');
      if (lb) { const e = document.getElementById(lb.split(/\s+/)[0]); if (e) label = txt(e); }
    }
    if (!label) { const h = r.el.querySelector('h1,h2,h3,legend,caption'); if (h) label = txt(h); }
    if (!label) label = r.el.id ? '#' + r.el.id : (r.el.className && typeof r.el.className === 'string' ? '.' + r.el.className.split(/\s+/)[0] : r.el.tagName.toLowerCase());
    regions.push({
      ref, kind: r.kind, label: (label || '').slice(0, 70),
      tag: r.el.tagName.toLowerCase(),
      interactive: r.el.querySelectorAll(INTERACTIVE_SEL).length,
      text_blocks: r.el.querySelectorAll('p,li,blockquote,pre,dd,dt').length,
      images: r.el.querySelectorAll('img,svg,picture').length,
      chars: t.length,
      top: Math.round(r.rect.top + window.scrollY),
      in_viewport: r.rect.top < window.innerHeight && r.rect.bottom > 0
    });
  });

  function ownerRegion(el) {
    let p = el;
    while (p && p !== document.body) {
      if (regionOf.has(p)) return regionOf.get(p);
      p = p.parentElement;
    }
    return '-';
  }

  // ---------- affordances ----------
  const allInteractive = Array.from(document.querySelectorAll(INTERACTIVE_SEL));
  const hiddenCounts = {};
  let hiddenInteractive = 0;
  const aff = [];
  let eCounter = 0;
  for (const el of allInteractive) {
    const hr = hiddenReason(el);
    if (hr) { hiddenInteractive++; hiddenCounts[hr] = (hiddenCounts[hr] || 0) + 1; continue; }
    const role = roleOf(el);
    if (role === 'hidden') continue;
    const rect = el.getBoundingClientRect();
    const name = accName(el);
    const type = el.tagName === 'INPUT' ? (el.type || 'text').toLowerCase() : null;
    const ac = (el.getAttribute && (el.getAttribute('autocomplete') || '')).toLowerCase();
    const secret = type === 'password' || /current-password|new-password|one-time-code/.test(ac);
    let state = [];
    if (el.disabled) state.push('disabled');
    if (el.checked) state.push('checked');
    if (el.required) state.push('required');
    const ae = el.getAttribute && el.getAttribute('aria-expanded'); if (ae) state.push('expanded=' + ae);
    const asel = el.getAttribute && el.getAttribute('aria-selected'); if (asel === 'true') state.push('selected');
    const ref = 'e' + (++eCounter);
    const inVp = rect.top < window.innerHeight && rect.bottom > 0 && rect.left < window.innerWidth;
    const reg = ownerRegion(el);
    const regKind = (regions.find(x => x.ref === reg) || {}).kind || '';
    let score = 0;
    if (inVp) score += 40;
    if (regKind === 'main' || regKind === 'dialog' || regKind === 'alertdialog') score += 30;
    if (regKind === 'search' || regKind === 'form') score += 22;
    if (regKind === 'navigation') score += 10;
    if (regKind === 'contentinfo') score -= 12;
    if (role === 'button' || role === 'searchbox' || role === 'combobox' || role === 'textbox') score += 14;
    if (type === 'submit') score += 18;
    if (name) score += 8; else score -= 25;
    score += Math.min(14, Math.sqrt(Math.max(0, rect.width * rect.height)) / 12);
    score -= Math.min(20, (rect.top + window.scrollY) / 900);
    aff.push({
      ref, role, name, state: state.join(','), region: reg, score: Math.round(score),
      in_viewport: inVp, secret,
      href: el.tagName === 'A' ? (el.getAttribute('href') || '').slice(0, 60) : null,
      type
    });
  }
  aff.sort((a, b) => b.score - a.score);

  // ---------- content digest ----------
  const headings = [];
  let hCounter = 0;
  for (const h of Array.from(document.querySelectorAll('h1,h2,h3,h4'))) {
    if (!visible(h)) continue;
    const t = txt(h);
    if (!t) continue;
    headings.push({ ref: 'h' + (++hCounter), level: +h.tagName[1], text: t.slice(0, 80), region: ownerRegion(h), chars: 0 });
  }
  // approximate section weight: text between this heading and the next
  const hEls = Array.from(document.querySelectorAll('h1,h2,h3,h4')).filter(visible);
  hEls.forEach((h, i) => {
    let c = 0, n = h.nextElementSibling;
    while (n && !/^H[1-4]$/.test(n.tagName)) { c += (n.textContent || '').length; n = n.nextElementSibling; }
    if (headings[i]) headings[i].chars = c;
  });

  const paras = Array.from(document.querySelectorAll('p')).filter(visible);
  const proseChars = paras.reduce((a, p) => a + txt(p).length, 0);
  let lead = '';
  for (const p of paras) { const t = txt(p); if (t.length > 80) { lead = t; break; } }
  const readable = proseChars > 1200 && paras.length >= 4;

  // ---------- forms ----------
  const forms = [];
  let fCounter = 0;
  for (const f of Array.from(document.querySelectorAll('form'))) {
    if (!visible(f)) continue;
    const fields = [];
    for (const el of Array.from(f.querySelectorAll('input,select,textarea'))) {
      const type = el.tagName === 'INPUT' ? (el.type || 'text').toLowerCase() : el.tagName.toLowerCase();
      if (type === 'hidden') continue;
      const hr = hiddenReason(el);
      if (hr) continue;
      const a = aff.find(x => x.name === accName(el) && x.role === roleOf(el));
      const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
      const secret = type === 'password' || /current-password|new-password|one-time-code/.test(ac);
      fields.push({
        ref: a ? a.ref : null, label: accName(el), type,
        required: !!el.required, secret,
        value_state: secret ? 'never-read' : (el.value ? (el.value.length > 30 ? 'set(' + el.value.length + ' chars)' : 'set:"' + el.value.slice(0, 30) + '"') : 'empty'),
        payment: /cc-number|cc-exp|cc-csc/.test(ac)
      });
    }
    forms.push({
      ref: 'f' + (++fCounter),
      name: f.getAttribute('name') || f.getAttribute('id') || f.getAttribute('aria-label') || '',
      action: (f.getAttribute('action') || '(same page)').slice(0, 60),
      method: (f.getAttribute('method') || 'get').toUpperCase(),
      region: ownerRegion(f), fields
    });
  }

  // ---------- tables ----------
  const tables = [];
  let tCounter = 0;
  for (const t of Array.from(document.querySelectorAll('table'))) {
    if (!visible(t)) continue;
    const rows = t.rows ? t.rows.length : 0;
    if (rows === 0) continue;
    const cols = t.rows[0] ? t.rows[0].cells.length : 0;
    const hdr = Array.from(t.querySelectorAll('th')).slice(0, 8).map(x => txt(x).slice(0, 28));
    const cap = t.caption ? txt(t.caption).slice(0, 60) : '';
    const cls = (t.getAttribute('class') || '').slice(0, 40);
    tables.push({
      ref: 't' + (++tCounter), caption: cap || cls, rows, cols, headers: hdr,
      region: ownerRegion(t), chars: txt(t).length,
      spans: t.querySelectorAll('[rowspan],[colspan]').length
    });
  }
  // div-tables
  let divTables = 0;
  for (const g of Array.from(document.querySelectorAll('[role=table],[role=grid],[role=treegrid]'))) {
    if (visible(g)) divTables++;
  }

  // ---------- completeness ----------
  const frames = Array.from(document.querySelectorAll('iframe'));
  let sameOrigin = 0, crossOrigin = 0;
  const frameList = [];
  frames.forEach((fr, i) => {
    let same = false;
    try { same = !!fr.contentDocument; } catch (e) { same = false; }
    if (same) sameOrigin++; else crossOrigin++;
    frameList.push({ ref: 'if' + (i + 1), src: (fr.getAttribute('src') || '(srcdoc)').slice(0, 70), same_origin: same, title: fr.getAttribute('title') || '' });
  });

  let openShadow = 0;
  const allEls = document.querySelectorAll('*');
  for (const el of allEls) { if (el.shadowRoot) openShadow++; }

  const virtual = [];
  for (const el of Array.from(document.querySelectorAll('[aria-setsize],[aria-rowcount],[class*=virtual i],[class*=Virtual],[class*=infinite i]'))) {
    if (!visible(el)) continue;
    const claimed = el.getAttribute('aria-setsize') || el.getAttribute('aria-rowcount') || null;
    const domCount = el.children.length;
    virtual.push({ region: ownerRegion(el), dom_count: domCount, claimed: claimed, hint: (el.getAttribute('class') || '').slice(0, 30) });
  }

  const canvases = Array.from(document.querySelectorAll('canvas')).filter(visible).map(c => {
    const r = c.getBoundingClientRect();
    return { region: ownerRegion(c), w: Math.round(r.width), h: Math.round(r.height) };
  }).filter(c => c.w > 80 && c.h > 80);

  const docH = document.documentElement.scrollHeight;
  const vpH = window.innerHeight;

  return {
    identity: {
      url: location.href, title: document.title,
      lang: document.documentElement.lang || '',
      screens: Math.max(1, Math.round((docH / vpH) * 10) / 10),
      viewport: window.innerWidth + 'x' + vpH
    },
    regions, affordances: aff.slice(0, CAP_AFF), aff_total: aff.length,
    headings, lead, readable, prose_chars: proseChars,
    forms, tables, div_tables: divTables,
    completeness: {
      frames: frameList, frames_same: sameOrigin, frames_cross: crossOrigin,
      open_shadow_roots: openShadow,
      closed_shadow_roots: (window.__ks4web_closedShadow || 0),
      virtual, canvases,
      hidden_interactive: hiddenInteractive, hidden_reasons: hiddenCounts,
      total_elements: allEls.length,
      doc_height: docH, viewport_height: vpH
    }
  };
}
