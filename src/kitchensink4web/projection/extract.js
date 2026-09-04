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
() => {
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

  const styleCache = new Map();
  function cs(el) {
    let v = styleCache.get(el);
    if (v === undefined) { v = getComputedStyle(el); styleCache.set(el, v); }
    return v;
  }

  function parseColor(v) {
    const m = /rgba?\(([^)]+)\)/.exec(v || '');
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }

  function lum(c) {
    const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }

  // Hidden-content normalization. Every technique class DESIGN 5.1 names, and
  // the result is COUNTED rather than silently dropped or silently included.
  function hiddenReason(el, style) {
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
    if (el.hasAttribute && el.hasAttribute('hidden')) return 'hidden-attr';
    const s = style || cs(el);
    if (s.display === 'none') return 'display-none';
    if (s.visibility === 'hidden' || s.visibility === 'collapse') return 'visibility-hidden';
    if (parseFloat(s.opacity) === 0) return 'opacity-0';
    const fs = parseFloat(s.fontSize);
    if (fs === fs && fs < 2) return 'font-size-0';
    return null;
  }

  function geometryHidden(el, style) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return { reason: 'zero-size', rect: r };
    const x = r.left + window.scrollX, y = r.top + window.scrollY;
    if (x + r.width < -500 || y + r.height < -500 || x > 100000) {
      return { reason: 'offscreen', rect: r };
    }
    if ((style || cs(el)).textIndent && parseFloat((style || cs(el)).textIndent) < -900) {
      return { reason: 'offscreen', rect: r };
    }
    return { reason: null, rect: r };
  }

  function hiddenBetween(el, stopAt) {
    // Hidden anywhere between an element and its region ancestor counts as
    // hidden, because that is how a display:none wrapper hides a heading that
    // is itself perfectly visible in its own computed style.
    for (let n = el; n && n !== stopAt; n = n.parentElement) {
      if (hiddenReason(n, null)) return true;
    }
    return false;
  }

  function lowContrast(el, style) {
    const fg = parseColor(style.color);
    if (!fg) return false;
    let node = el, bg = null;
    for (let i = 0; node && i < 6; i++, node = node.parentElement) {
      const c = parseColor(cs(node).backgroundColor);
      if (c && c.a > 0.1) { bg = c; break; }
    }
    if (!bg) return false;
    return Math.abs(lum(fg) - lum(bg)) < 0.02;
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
        const target = document.getElementById(id);
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

  const TEXT_BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT', 'FIGCAPTION']);
  const PROSE_ANCESTOR = new Set(['P', 'LI', 'BLOCKQUOTE', 'DD', 'FIGCAPTION']);

  // ----------------------------------------------------------- the walk

  const regions = [];
  const regionStack = [];
  const affordances = [];
  const headings = [];
  const forms = [];
  const tables = [];
  const canvases = [];
  const frames = [];
  const virtualContainers = [];
  const hiddenReasons = {};
  let hiddenInteractive = 0, hiddenNodes = 0, hiddenTextChars = 0;
  let injectionSuspects = 0, zeroWidthHits = 0;
  let openShadowRoots = 0, divTables = 0, deepestCut = 0;
  let elementCount = 0, textCharsTotal = 0;

  // Refs resolve through a map on `window`, never through an attribute we
  // write onto the page. KS4Web reads pages; a projection that mutated the
  // DOM to give itself handles would be changing the thing it is reporting
  // on, and a MutationObserver-driven app would see it.
  const refMap = new Map();
  const refOf = new WeakMap();
  window.__ks4web_refs = refMap;
  window.__ks4web_refof = refOf;
  let eCounter = 0, rCounter = 0, hCounter = 0, fCounter = 0, tCounter = 0;
  let affordancesUncollected = 0;
  let currentHeading = null;
  const roleOrdinals = {};
  const classTotals = {};

  function bump(field, n) {
    const reg = regionStack.length ? regionStack[regionStack.length - 1] : null;
    if (reg) reg.net[field] += n;
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

  function walk(el, depth) {
    elementCount++;
    if (depth > 400) { deepestCut++; return; }  // pathological nesting, reported
    const style = cs(el);
    const hr = hiddenReason(el, style);
    if (hr) {
      // The whole subtree is accounted for HERE and the walk stops, which is
      // what keeps the normalizer linear: counting a hidden subtree at every
      // level of itself is the O(n^2) version of the same answer.
      const n = 1 + el.querySelectorAll('*').length;
      hiddenNodes += n;
      hiddenReasons[hr] = (hiddenReasons[hr] || 0) + n;
      hiddenInteractive += el.querySelectorAll(INTERACTIVE_SEL).length
        + (isInteractive(el) ? 1 : 0);
      const txt = squash(el.textContent || '');
      hiddenTextChars += txt.length;
      if (txt.length > 20) injectionSuspects++;
      return;
    }

    let pushed = false;
    const kind = regionCandidate(el);
    if (kind && !hr && regions.length < MAX_REGIONS && regionStack.length < MAX_REGION_DEPTH) {
      const geo = geometryHidden(el, style);
      if (!geo.reason && (geo.rect.height >= 24 || geo.rect.width >= 24)) {
        const ref = 'r' + (++rCounter);
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
        const rec = {
          ref: ref, kind: kind, label: label || '(' + el.tagName.toLowerCase() + ')',
          name_quality: named.quality,
          tag: el.tagName.toLowerCase(),
          depth: regionStack.length,
          parent: regionStack.length ? regionStack[regionStack.length - 1].ref : null,
          net: { interactive: 0, text_blocks: 0, images: 0, chars: 0, headings: 0 },
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

    // direct text, attributed to the innermost region and the current section
    let direct = 0;
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const s = node.nodeValue || '';
        if (ZERO_WIDTH.test(s)) { zeroWidthHits++; }
        direct += squash(s).length;
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
        if (currentHeading) currentHeading.section_chars += direct;
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
          const rec = {
            ref: 'h' + (++hCounter), level: +tag[1], text: named.name,
            name_quality: named.quality,
            region: region ? region.ref : null,
            section_chars: 0, section_affordances: 0, section_known: true
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
            const collect = affordances.length < MAX_AFFORDANCES;
            const named = collect ? accName(el, role)
              : { name: '', quality: 'not-collected' };
            const type = tag === 'INPUT' ? (el.type || 'text').toLowerCase() : null;
            const ac = ((el.getAttribute && el.getAttribute('autocomplete')) || '').toLowerCase();
            const secret = type === 'password' ||
              /current-password|new-password|one-time-code/.test(ac);
            const payment = /cc-number|cc-exp|cc-csc|cc-name/.test(ac);
            const state = [];
            if (el.disabled) state.push('disabled');
            if (el.checked) state.push('checked');
            if (el.required) state.push('required');
            const ae = el.getAttribute('aria-expanded'); if (ae) state.push('expanded=' + ae);
            if (el.getAttribute('aria-selected') === 'true') state.push('selected');
            if (el.getAttribute('aria-current')) state.push('current');

            let href = null, path = null, external = false;
            if (tag === 'A') {
              href = el.getAttribute('href');
              try {
                const u = new URL(el.href, location.href);
                external = u.origin !== location.origin;
                path = external ? u.origin + u.pathname : (u.pathname + u.search + u.hash);
              } catch (e) { path = href; }
            }

            // Quota class. Order matters: a link inside prose is a prose link
            // even when it also sits under a nav-shaped ancestor, and a form
            // control is a form control wherever it lives.
            let inProse = false;
            let p = el.parentElement, hops = 0;
            while (p && hops++ < 6) {
              if (PROSE_ANCESTOR.has(p.tagName)) { inProse = true; break; }
              p = p.parentElement;
            }
            const formEl = el.form || el.closest('form');
            let cls;
            if (role === 'link' && inProse) cls = 'prose_link';
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
            if (collect) {
              roleOrdinals[role] = (roleOrdinals[role] || 0) + 1;
              const ref = 'e' + (++eCounter);
              refMap.set(ref, el);
              refOf.set(el, ref);
              affordances.push({
                ref: ref, role: role, name: named.name,
                name_quality: named.quality,
                cls: cls, region: region ? region.ref : null,
                region_label: region ? region.label : null,
                ordinal: roleOrdinals[role],
                state: state.join(','), secret: secret, payment: payment,
                href: href, path: path, external: external, type: type,
                in_viewport: geo.rect.top < window.innerHeight
                  && geo.rect.bottom > 0 && geo.rect.left < window.innerWidth,
                top: Math.round(geo.rect.top + window.scrollY),
                area: Math.round(geo.rect.width * geo.rect.height),
                form: formEl ? true : false,
                heading: currentHeading ? currentHeading.ref : null
              });
            } else {
              affordancesUncollected++;
            }
          }
        }
      }

      if (tag === 'FORM') {
        forms.push({ el: el, ref: 'f' + (++fCounter), region: region ? region.ref : null });
      } else if (tag === 'TABLE') {
        const rows = el.rows ? el.rows.length : 0;
        if (rows) {
          const named = accName(el, 'table');
          tables.push({
            ref: 't' + (++tCounter), caption: named.name,
            name_quality: named.quality,
            rows: rows, cols: el.rows[0] ? el.rows[0].cells.length : 0,
            headers: Array.from(el.querySelectorAll('th')).slice(0, 8)
              .map(x => clip(contentName(x, 0, new Set()), 28).text),
            region: region ? region.ref : null,
            chars: squash(el.textContent || '').length,
            spans: el.querySelectorAll('[rowspan],[colspan]').length
          });
        }
      } else if (tag === 'CANVAS') {
        const geo = geometryHidden(el, style);
        if (!geo.reason && geo.rect.width > 80 && geo.rect.height > 80) {
          canvases.push({
            region: region ? region.ref : null,
            w: Math.round(geo.rect.width), h: Math.round(geo.rect.height)
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

      const setsize = el.getAttribute('aria-setsize') || el.getAttribute('aria-rowcount');
      const clsName = typeof el.className === 'string' ? el.className : '';
      if (setsize || /virtual|infinite|windowed/i.test(clsName)) {
        const kids = el.children.length;
        if (kids > 2 || setsize) {
          virtualContainers.push({
            region: region ? region.ref : null, dom_count: kids,
            claimed: setsize ? parseInt(setsize, 10) : null,
            hint: clip(clsName, 30).text
          });
        }
      }
      const r2 = el.getAttribute('role');
      if (r2 && /^(table|grid|treegrid)$/.test(r2.trim())) divTables++;
      if (el.shadowRoot) openShadowRoots++;
    }

    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child, depth + 1);
    }
    if (pushed) regionStack.pop();
  }

  if (document.body) walk(document.body, 0);
  for (const h of headings) delete h.parentHeading;

  // A heading with no attributed text has no determinable section, so the
  // projection prints NO price for it rather than a number derived from a
  // walk that found nothing (DESIGN 3.3a rule 1).
  for (const h of headings) h.section_known = h.section_chars > 0;

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
        payment: /cc-number|cc-exp|cc-csc|cc-name/.test(ac),
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
  const paras = Array.from(document.querySelectorAll('p,article>div>p'))
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
  const readableHost = document.querySelector('main,[role=main],article');
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
      ref: r.ref, kind: r.kind, label: r.label, name_quality: r.name_quality,
      tag: r.tag, depth: r.depth, parent: r.parent, children: r.children,
      net: r.net, top: r.top, in_viewport: r.in_viewport,
      nav_shaped: r.nav_shaped
    })),
    affordances: affordances,
    // Totals over EVERY interactive element, including the ones past the
    // return cap, so "unlisted affordances: N" is the real number.
    affordance_class_totals: classTotals,
    affordance_total: affordances.length + affordancesUncollected,
    headings: headings.slice(0, MAX_HEADINGS),
    headings_total: headings.length,
    lead: leadEl || '',
    forms: formOut,
    tables: tables,
    div_tables: divTables,
    completeness: {
      frames: frames,
      frames_same: frames.filter(f => f.same_origin).length,
      frames_cross: frames.filter(f => !f.same_origin).length,
      open_shadow_roots: openShadowRoots,
      closed_shadow_roots: (window.__ks4web_closed_shadow || 0),
      virtual: virtualContainers, canvases: canvases,
      hidden_interactive: hiddenInteractive, hidden_nodes: hiddenNodes,
      hidden_text_chars: hiddenTextChars, hidden_reasons: hiddenReasons,
      injection_suspects: injectionSuspects, zero_width_hits: zeroWidthHits,
      name_fallbacks: nameFallbacks,
      total_elements: document.getElementsByTagName('*').length,
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
