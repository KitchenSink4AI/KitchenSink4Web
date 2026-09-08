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
    const g = ksGeometryHidden(el, null).reason;
    if (g) return g;
    // PAINT ORDER IS A HIDING TECHNIQUE TOO (fix wave 9b). A paragraph under
    // an opaque, identically-sized, higher-z-index sibling is invisible to a
    // human by exactly the mechanism `click` already refuses on, and this
    // read returned it as ordinary prose and left it out of the `stripped`
    // ledger as well. It is now a technique with a name, counted and named
    // beside the other eight. The rule itself lives in `visibility.js`.
    return ksPaintCloaked(el);
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
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);

  // THE READABLE SET IS NOW EVERY BLOCK-LEVEL BOX, not a fixed tag list
  // (hostile H-04). The list above was the whole readable set, so text in a
  // bare DIV was neither emitted NOR counted: `/bomb/divprose?n=400` served
  // 51,922 characters of ordinary English in 400 divs, nothing hidden, and
  // get_text answered `chars: {returned: 24, total_in_scope: 24,
  // next_start_index: null}` with "this is the end of the text in scope"
  // under it. `stripped` counts only HIDDEN blocks, so visible text the
  // classifier declined had no counter anywhere and `total_in_scope`
  // reported the extractor's total as if it were the page's. SPA output
  // routinely renders body copy as div, and get_page_view saw the problem
  // correctly on the same page ("prose is 0% of page text"), so the two
  // read surfaces disagreed about one document.
  //
  // Membership is the COMPUTED display rather than the tag, because that is
  // what decides whether a run of text is its own paragraph on screen. An
  // inline box is never emitted on its own: its text belongs to the block
  // that contains it, and `inlineText` already collects it there.
  const BLOCKISH = /^(block|flow-root|list-item|table|table-row|table-cell|table-caption|flex|grid|-webkit-box)$/;
  function isBlockBox(el, style) {
    if (BLOCK.has(el.tagName)) return true;
    if (!el.tagName || el.tagName === 'BR') return false;
    const d = (style || cs(el)).display || '';
    return BLOCKISH.test(d.split(' ')[0]);
  }

  // SVG carries real, visible, selectable text and the old SKIP entry never
  // even fired (an `<svg>` element's tagName is lowercase `svg`, and the set
  // held `SVG`), so the walk descended and then emitted nothing because no
  // SVG tag was in BLOCK. Five `<svg><text>` elements plus a `<title>` and a
  // `<desc>` — about 130 visible characters — appeared in no payload at all
  // and in no ledger row: the completeness block names iframes, shadow
  // roots, hidden nodes, canvas, virtualized containers and unlisted
  // affordances, and had no SVG vocabulary whatsoever (fuzzer class 2).
  // `<text>` is content and is emitted; `<title>` and `<desc>` are the SVG
  // spelling of alt text, so they are COUNTED rather than mixed into prose.
  const SVG_TEXT = new Set(['text', 'textPath']);
  const SVG_META = new Set(['title', 'desc']);
  function isSvgNode(el) {
    return el.namespaceURI === 'http://www.w3.org/2000/svg';
  }

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
      if (SKIP.has(node.tagName)) continue;
      // Stop at the next BOX, not just at the next tag from a fixed list,
      // or a div's paragraph-shaped children would be flattened into their
      // parent and emitted a second time by the walk (H-04's fix has to
      // preserve the de-duplication the original stop condition bought).
      if (isBlockBox(node)) continue;
      if (isSvgNode(node)
          && (SVG_TEXT.has(node.tagName) || SVG_META.has(node.tagName))) {
        continue;               // handled by the walk, on their own terms
      }
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
  let svgMetaBlocks = 0, svgMetaChars = 0;
  let unclassifiedBlocks = 0, unclassifiedChars = 0;
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
    if (isSvgNode(el) && SVG_META.has(el.tagName)) {
      // BEFORE the hidden check. An SVG `<title>` has no layout box at
      // all, so the geometry test calls it zero-size and the hidden
      // branch would swallow it into the hidden ledger. It is not hidden;
      // it is the SVG spelling of alt text, and it belongs in its own
      // ledger row where a caller can see what kind of text it is.
      const meta = squash(el.textContent || '');
      if (meta) { svgMetaBlocks++; svgMetaChars += meta.length; }
      return;
    }
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
      // THE WITHHELD TEXT INCLUDES WHAT THE OPEN ROOTS UNDER IT HOLD (fix
      // wave 9c). This walk descends into `el.shadowRoot` below, so a hidden
      // host's shadow prose is correctly never printed -- and it was measured
      // with `textContent`, which stops at the boundary, so on a component
      // with no light children the ledger reported nothing withheld while
      // three injection payloads had in fact been suppressed. The content was
      // right and the accounting was false, which this build treats as the
      // same defect: `get_page_view` counted the same page correctly and the
      // two reads contradicted each other.
      const text = squash(ksDeepTextContent(el));
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
    if ((isSvgNode(el) && SVG_TEXT.has(el.tagName))
        || isBlockBox(el)) {
      const parts = [];
      if (isSvgNode(el)) {
        // `<text>` holds `<tspan>` runs; they are inline within it.
        parts.push(el.textContent || '');
      } else {
        inlineText(el, parts);
      }
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
      if (isSvgNode(el)) return;      // tspans were consumed above
    } else {
      // NOTHING VISIBLE GOES UNCOUNTED (H-04). Anything left over after the
      // block-box widening is an inline box holding a text run its parent
      // did not claim; it has no counter of its own, so it gets one here
      // rather than vanishing under a completeness claim.
      const leftover = [];
      for (const node of el.childNodes) {
        if (node.nodeType === 3) leftover.push(node.nodeValue || '');
      }
      const stray = squash(leftover.join(''));
      if (stray) { unclassifiedBlocks++; unclassifiedChars += stray.length; }
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
    // THE TWO NEW LEDGER ROWS (hostile H-04, fuzzer class 2). `stripped`
    // counts only HIDDEN blocks, so before these rows there was no counter
    // anywhere for visible text a read declined, and `total_chars` was
    // reported as the page's total when it was only the extractor's.
    svg_meta: { blocks: svgMetaBlocks, chars: svgMetaChars },
    unclassified: { blocks: unclassifiedBlocks, chars: unclassifiedChars },
    hidden_sections: includeHidden ? hiddenSections : null
  };
}
