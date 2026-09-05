// KS4Web prose extraction: readable text, bounded, with its origin stated.
//
// DESIGN 3.6: it never returns unbounded output, and it never silently omits.
// Hidden regions are stripped and COUNTED rather than silently dropped or
// silently included, which is the difference between this and a `innerText`
// read: an injected instruction hidden in a display:none block shows up in
// the count and never in the content.
//
// The lead and the readable region are decided the same way the projection
// decides them, from the readable host rather than from document order. S1's
// version took the first paragraph over eighty characters anywhere in the
// document, which on CNN returned a DRM error string as the site's headline.
(opts) => {
  const startIndex = Math.max(0, opts.start_index || 0);
  const maxChars = Math.max(200, Math.min(200000, opts.max_chars || 20000));
  const includeHidden = !!opts.include_hidden;

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const styleCache = new Map();
  function cs(el) {
    let v = styleCache.get(el);
    if (v === undefined) { v = getComputedStyle(el); styleCache.set(el, v); }
    return v;
  }
  // The FULL technique set (DESIGN 5.1), matching the extractor's hygiene
  // layer. Phase 3's corpus C gate caught the divergence that used to live
  // here: this function had no contrast, geometry, or text-indent check, so
  // a white-on-white injection stripped from the page view rode out of
  // get_text as content. The two detectors now share every rule.
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
  function lowContrast(el, s) {
    const fg = parseColor(s.color);
    if (!fg) return false;
    let node = el, bg = null;
    for (let i = 0; node && i < 6; i++, node = node.parentElement) {
      const c = parseColor(cs(node).backgroundColor);
      if (c && c.a > 0.1) { bg = c; break; }
    }
    if (!bg) return false;
    return Math.abs(lum(fg) - lum(bg)) < 0.02;
  }
  function hiddenReason(el) {
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
    if (el.hasAttribute && el.hasAttribute('hidden')) return 'hidden-attr';
    const s = cs(el);
    if (s.display === 'none') return 'display-none';
    if (s.visibility === 'hidden' || s.visibility === 'collapse') return 'visibility-hidden';
    if (parseFloat(s.opacity) === 0) return 'opacity-0';
    const fs = parseFloat(s.fontSize);
    if (fs === fs && fs < 2) return 'font-size-0';
    if (s.textIndent && parseFloat(s.textIndent) < -900) return 'offscreen';
    if (el.getBoundingClientRect) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0 && el.tagName !== 'BODY') return 'zero-size';
      const x = r.left + window.scrollX, y = r.top + window.scrollY;
      if (x + r.width < -500 || y + r.height < -500 || x > 100000) return 'offscreen';
    }
    if (lowContrast(el, s)) return 'low-contrast';
    return null;
  }

  let root = null, rootWas = 'document';
  if (opts.root) {
    const map = window.__ks4web_refs;
    root = map ? map.get(opts.root) : null;
    if (!root) {
      return { error: 'ROOT_GONE', asked_for: opts.root };
    }
    rootWas = opts.root;
  }
  root = root || document.body || document.documentElement;

  const BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT',
    'FIGCAPTION', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TD', 'TH']);
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG']);

  // A block's own text is the text of the INLINE run it contains: its text
  // nodes plus the text of inline wrappers around them, stopping wherever a
  // nested block begins and wherever a hidden element begins.
  //
  // `textContent` on an inline child answers neither of those questions, and
  // reading it was two defects at once. It flattened every HIDDEN descendant
  // back into the payload, so the read returned a `visibility:hidden`
  // navigation menu and a `display:none` sidebar as content while the hygiene
  // counter, walking separately, recorded the same characters as hidden and
  // withheld: 1,426 characters on the frozen GitHub page and 666 on the
  // frozen Wikipedia article. Hidden text reaching a caller is the exact
  // thing DESIGN 3.6 says this tool does not do, and an injected instruction
  // parked under an inline wrapper travelled straight through it. It also
  // flattened every nested BLOCK descendant, which the walk then emitted
  // again a moment later, so a navbox whose cells wrap their lists in a div
  // came back at two and a half times its true length. The over-long text was
  // the measurement the price gate was failing against.
  // Hidden inline content is stripped from the MAIN text unconditionally.
  // include_hidden does not relax this: DESIGN 5.1 routes hidden content
  // into a separately labeled section, never mixed into the main text, so
  // the main text is byte-identical whichever way the flag is set.
  function inlineText(el, into) {
    for (const node of el.childNodes) {
      if (node.nodeType === 3) { into.push(node.nodeValue || ''); continue; }
      if (node.nodeType !== 1) continue;
      if (SKIP.has(node.tagName) || BLOCK.has(node.tagName)) continue;
      if (hiddenReason(node)) continue;
      into.push(' ');
      inlineText(node, into);
    }
  }

  const blocks = [];
  const hiddenReasons = {};
  const hiddenSections = [];
  let hiddenBlocks = 0, hiddenChars = 0, injectionSuspects = 0;
  let zeroWidth = 0;
  const ZERO_WIDTH = /[​-‏‪-‮⁠-⁤﻿]/g;
  const HIDDEN_SECTION_CAP = 2000;      // per section
  const HIDDEN_TOTAL_CAP = 20000;       // per read
  let hiddenCollected = 0;

  (function walk(el) {
    if (SKIP.has(el.tagName)) return;
    const reason = hiddenReason(el);
    if (reason) {
      const text = squash(el.textContent || '');
      if (text) {
        hiddenBlocks++;
        hiddenChars += text.length;
        hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
        // A hidden block carrying real sentences is the shape of a prompt
        // injection, so it is counted as a suspect and named as one. It is
        // never printed in the main text; with include_hidden it lands in
        // the labeled section below, bounded, and nowhere else.
        if (text.length > 20) injectionSuspects++;
        if (includeHidden && hiddenCollected < HIDDEN_TOTAL_CAP) {
          const clipped = text.slice(0, HIDDEN_SECTION_CAP);
          hiddenCollected += clipped.length;
          hiddenSections.push({
            reason: reason,
            truncated: clipped.length < text.length,
            text: clipped
          });
        }
      }
      return;
    }
    if (BLOCK.has(el.tagName)) {
      const parts = [];
      inlineText(el, parts);
      let own = parts.join('');
      if (ZERO_WIDTH.test(own)) {
        zeroWidth++;
        own = own.replace(ZERO_WIDTH, '');
      }
      const text = squash(own);
      if (text) {
        blocks.push({
          tag: el.tagName.toLowerCase(),
          ref: (window.__ks4web_refof && window.__ks4web_refof.get(el)) || null,
          text: text
        });
      }
    }
    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child);
    }
  })(root);

  // One string, then a window over it, so `start_index` means the same thing
  // on every call and a long article is read in bounded pieces rather than
  // one unbounded dump.
  const full = blocks.map(b => (/^h[1-6]$/.test(b.tag) ? '\n' + b.text + '\n'
    : b.text)).join('\n');
  const slice = full.slice(startIndex, startIndex + maxChars);
  const nextIndex = startIndex + slice.length;

  return {
    root: rootWas,
    url: location.href,
    text: slice,
    start_index: startIndex,
    next_start_index: nextIndex < full.length ? nextIndex : null,
    total_chars: full.length,
    returned_chars: slice.length,
    blocks: blocks.length,
    hidden: {
      blocks: hiddenBlocks, chars: hiddenChars, reasons: hiddenReasons,
      injection_suspects: injectionSuspects, zero_width_blocks: zeroWidth,
      included: includeHidden
    },
    hidden_sections: includeHidden ? hiddenSections : null
  };
}
