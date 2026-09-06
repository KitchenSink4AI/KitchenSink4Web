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
//
// It descends into OPEN shadow roots, the same as `get_page_view` and in the
// same change, because the alternative was a page view that sees a component's
// text and a prose read that does not. Two tools disagreeing about what is on
// the page is worse than either answer on its own.
(opts) => {
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_VISIBILITY@@
  const startIndex = Math.max(0, opts.start_index || 0);
  const maxChars = Math.max(200, Math.min(200000, opts.max_chars || 20000));
  const includeHidden = !!opts.include_hidden;
  const SHADOW_ON = !(opts && opts.shadow === false);

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const up = ksUp;
  const cs = ksCS;
  // The FULL technique set comes from the ONE shared source spliced in above
  // (DESIGN 5.1). Phase 3's corpus C gate caught the first divergence that
  // lived here: no contrast, geometry, or text-indent check, so a
  // white-on-white injection stripped from the page view rode out of get_text
  // as content. Gauntlet 2 caught the second (H3): a payload inside a
  // collapsed `<details>` or under `content-visibility: hidden` reached the
  // main text while the ledger said three blocks were withheld and named
  // neither. Copies drift; there is one copy now.
  function hiddenReason(el) {
    const r = ksHiddenReason(el, null);
    if (r) return r;
    // Geometry is measured rather than computed, and BODY is exempt because a
    // body with no laid-out box is a page state, not a hiding technique.
    if (el.tagName === 'BODY' || !el.getBoundingClientRect) return null;
    return ksGeometryHidden(el, null).reason;
  }

  let root = null, rootWas = 'document';
  if (opts.root) {
    root = KS.refs.get(opts.root) || null;
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
  let zeroWidth = 0, shadowRootsRead = 0;
  const ZERO_WIDTH = /[​-‏‪-‮⁠-⁤﻿]/g;
  const HIDDEN_SECTION_CAP = 2000;      // per section
  const HIDDEN_TOTAL_CAP = 20000;       // per read
  let hiddenCollected = 0;

  // A `visibility: hidden` block whose descendant sets `visibility: visible`
  // renders that descendant, and until 2026-09-06 this walk returned at the
  // hidden ancestor and never reached it (gauntlet 2 L2). The direction was
  // the safe one, and it still handed a page a reliable way to show a human
  // something no tool would ever read. The scan runs only when a
  // visibility-hidden element is actually met, so the common page pays
  // nothing for it.
  function hasVisibleDescendant(el) {
    if (!el.querySelectorAll) return false;
    const kids = el.querySelectorAll('*');
    for (let i = 0; i < kids.length && i < 500; i++) {
      if (ksCS(kids[i]).visibility === 'visible') return true;
    }
    return false;
  }

  (function walk(el) {
    if (SKIP.has(el.tagName)) return;
    const reason = hiddenReason(el);
    if (reason === 'visibility-hidden' && hasVisibleDescendant(el)) {
      // Count this element's OWN inline run as withheld, then keep going:
      // the recursion re-asks the same question of every child, so a child
      // that inherits `hidden` is counted in its turn and one that overrides
      // it is read.
      const ownParts = [];
      inlineText(el, ownParts);
      const ownText = squash(ownParts.join(''));
      if (ownText) {
        hiddenBlocks++;
        hiddenChars += ownText.length;
        hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
        if (ownText.length > 20) injectionSuspects++;
        if (includeHidden && hiddenCollected < HIDDEN_TOTAL_CAP) {
          const clipped = ownText.slice(0, HIDDEN_SECTION_CAP);
          hiddenCollected += clipped.length;
          hiddenSections.push({ reason: reason, truncated: false,
                                text: clipped });
        }
      }
      for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
        walk(child);
      }
      return;
    }
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
          ref: KS.refof.get(el) || null,
          text: text
        });
      }
    }
    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child);
    }
    // The descent sits after the hidden check above has already returned for
    // a hidden host, so shadow prose under a display:none component is
    // counted in the hidden ledger and never printed as text. Slot-assigned
    // nodes are not followed: they are light children the loop above already
    // read, and following them would print the same sentence twice.
    if (SHADOW_ON && el.shadowRoot) {
      shadowRootsRead++;
      for (let child = el.shadowRoot.firstElementChild; child;
           child = child.nextElementSibling) {
        walk(child);
      }
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
    shadow_roots_read: shadowRootsRead,
    closed_shadow_roots: (KS.closed || 0),
    hidden: {
      blocks: hiddenBlocks, chars: hiddenChars, reasons: hiddenReasons,
      injection_suspects: injectionSuspects, zero_width_blocks: zeroWidth,
      included: includeHidden
    },
    hidden_sections: includeHidden ? hiddenSections : null
  };
}
