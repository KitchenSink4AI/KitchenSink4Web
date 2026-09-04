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
  function hiddenReason(el) {
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
    if (el.hasAttribute && el.hasAttribute('hidden')) return 'hidden-attr';
    const s = cs(el);
    if (s.display === 'none') return 'display-none';
    if (s.visibility === 'hidden' || s.visibility === 'collapse') return 'visibility-hidden';
    if (parseFloat(s.opacity) === 0) return 'opacity-0';
    const fs = parseFloat(s.fontSize);
    if (fs === fs && fs < 2) return 'font-size-0';
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
  function inlineText(el, into) {
    for (const node of el.childNodes) {
      if (node.nodeType === 3) { into.push(node.nodeValue || ''); continue; }
      if (node.nodeType !== 1) continue;
      if (SKIP.has(node.tagName) || BLOCK.has(node.tagName)) continue;
      if (hiddenReason(node) && !includeHidden) continue;
      into.push(' ');
      inlineText(node, into);
    }
  }

  const blocks = [];
  const hiddenReasons = {};
  let hiddenBlocks = 0, hiddenChars = 0, injectionSuspects = 0;
  let zeroWidth = 0;
  const ZERO_WIDTH = /[​-‏‪-‮⁠-⁤﻿]/g;

  (function walk(el) {
    if (SKIP.has(el.tagName)) return;
    const reason = hiddenReason(el);
    if (reason && !includeHidden) {
      const text = squash(el.textContent || '');
      if (text) {
        hiddenBlocks++;
        hiddenChars += text.length;
        hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
        // A hidden block carrying real sentences is the shape of a prompt
        // injection, so it is counted as a suspect and named as one. It is
        // still never printed.
        if (text.length > 20) injectionSuspects++;
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
    }
  };
}
