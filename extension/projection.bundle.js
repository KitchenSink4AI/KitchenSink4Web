/*
 * KS4Web projection bundle. GENERATED FILE, DO NOT EDIT.
 *
 * Produced by src/kitchensink4web/extension/bundle.py from the sources in
 * src/kitchensink4web/projection/. `test_ext_bundle.py` pins this file equal
 * to what that module generates, so an edit to a projection source that is
 * not rebuilt here fails the suite rather than shipping a Lane C that reads
 * pages differently from every other lane.
 *
 * Injected ON DEMAND by the background script, never from the manifest. The
 * shared blocks are hoisted once here rather than spliced into each script,
 * which is the difference between 290 KB and 575 KB; even so, parsing this
 * in every frame of every page the user visits is a cost no page that is
 * never read should pay. A page that IS read pays one injection, once,
 * and the guard below makes a second injection into the same document free.
 *
 * Rebuild: python -m kitchensink4web.extension.bundle
 */

(function () {
  'use strict';
  if (window["__ks4webScripts"]) { return; }

// The instrument channel, isolated-world edition. See extension/bundle.py.
//
// The page cannot reach this object. A content script's global scope is not
// addressable from page script, so the state needs no accessor, no secret,
// and no non-configurable property descriptor: the three mechanisms
// `projection/instrument.js` uses to survive in the page's own realm.
//
// `closed` is null and stays null. Counting closed shadow roots means
// patching Element.prototype.attachShadow where PAGE script will call it,
// and Element.prototype reached from here is the Xray view, so a patch
// applied on this side would count nothing and report a confident zero. A
// number this lane did not earn is worse than no number, so the field is an
// absence and the Python side renders it as one.
const KS4WEB_STATE = {
  refs: new Map(),
  refof: new WeakMap(),
  seq: 0,
  act: Object.create(null),
  actseq: 0,
  closed: null,
  doc: 0,
  frameid: new WeakMap(),
  frameseq: 0
};


// ---- the shared blocks, hoisted once ----
// THE ONE HIDDEN-DETECTION SOURCE. Spliced into extract.js, find.js, text.js
// and the acting resolver at load time (`projection/__init__.py`), so there is
// exactly one implementation of "can a human see this" in the build.
//
// It exists because three copies of the rule drifted apart and every gap
// between them became a finding. Gauntlet 2 (2026-09-06) measured the cost:
// `find.js`'s copy knew five techniques while `extract.js`'s knew eleven, so
// `find_elements` returned an element parked 99,999px to the left as an
// in-view match while the same read's completeness block counted it as hidden
// (M4), and `text.js`'s copy knew nothing about a collapsed `<details>` (H3).
// A shared rule set is not tidiness here: a divergence between two detectors
// is a page-controlled channel for showing one thing to a human and another
// to the agent.
//
// The technique set is the union of everything the three copies knew plus the
// four classes the gauntlet demonstrated:
//
//  * NEAR-ZERO opacity, by threshold and CUMULATIVELY down the ancestor chain,
//    not `opacity === 0` on one element. `opacity: 0.01` renders as nothing
//    and the page's own `checkVisibility()` calls it visible.
//  * FILTER chains that end in invisibility: `filter: opacity(0)` (the
//    opacity functions in the chain multiply) and `filter: blur(Npx)` past
//    the point where text is legible.
//  * COLOUR invisibility: a transparent or near-transparent foreground, and a
//    foreground whose luminance matches the nearest opaque background. The
//    old contrast check ignored the alpha channel, so `color: transparent`
//    read as pure black and never tripped.
//  * NOT RENDERED AT ALL: `content-visibility: hidden`, a node inside a
//    collapsed `<details>`, and a light child of a shadow host that no slot
//    ever assigned.
//
// Two rules about WHERE a technique applies, and both are correctness rather
// than economy:
//
//  * INHERITED properties are checked on the element ITSELF, never on an
//    ancestor. `visibility`, `color`, and `font-size` all inherit and all can
//    be overridden by a descendant, so an ancestor carrying
//    `visibility: hidden` says nothing about a child carrying
//    `visibility: visible` — which a human reads and every tool in this build
//    used to miss (L2, same gauntlet). The element's own COMPUTED value
//    already carries the inherited answer, so checking it there is both
//    simpler and right.
//  * COMPOSITED properties (`display`, `opacity`, filters,
//    `content-visibility`) are checked up the chain, because a descendant
//    cannot undo them.
//
// The climb is the FLATTENED tree (`assignedSlot` first), not the light tree.
// A slotted node renders inside its slot's shadow tree, so the slot's
// ancestors are the ones that can hide it, and the light-tree climb walked
// past every one of them.

// THE THRESHOLDS, and each number is a decision with a reason (re-attack R5,
// 2026-09-06, which walked an agent through all three of them).
//
// OPACITY is INCLUSIVE. `opacity: 0.05` was the exact value the old `<`
// comparison let through, which is the oldest bug shape there is: a page
// picks the floor itself and sits on it. Nothing about 0.05 is legible that
// 0.049 is not.
var KS_OPACITY_FLOOR = 0.05;    // at or below this, nothing is legible
// BLUR at 6px was set without a fixture. A 16px control blurred by 5px is a
// grey smear -- the round-trip through a rendered fixture is in
// `corpus/ra/thresh.html`, where `blur(5px)` on 13px text leaves no readable
// glyph -- so the floor comes down to 4px, which is still well above the 1-2px
// a designer uses for a soft shadow or a focus halo.
var KS_BLUR_FLOOR = 4;          // px of blur past which text is not readable
// CONTRAST is a RATIO now, not a luminance subtraction. The old
// `|lum(fg) - lum(bg)| < 0.02` is not a perceptual measure at all: near white
// a 0.02 luminance gap is invisible, and near black it is a comfortable
// read, so the check simultaneously missed `#fbfbfb` on `#ffffff` (a gap of
// 0.019, which it passed by a hair) and would have cloaked legitimate dark-on-
// dark design.
//
// The number is 1.15:1, and the rationale is that it must sit far BELOW any
// accessibility threshold. WCAG AA is 4.5:1 for body text and 3:1 for large
// text, and AA failures are ordinary on real sites -- grey-on-white helper
// text, disabled controls, watermarks -- so cloaking at an AA boundary would
// strip real interfaces. 1.15:1 is not a design choice anyone makes. The
// measured neighbours on a white page: `#fbfbfb` is 1.03:1 and `#f0f0f0` is
// 1.14:1, both cloaked and neither readable by anyone; `#e0e0e0` is 1.32:1
// and `#cccccc` (the ordinary disabled-control grey) is 1.61:1, both left
// alone; `#949494`, the lightest grey in common use for faint-but-legible
// text, is 3.03:1 and nowhere near the floor.
var KS_CONTRAST_RATIO_FLOOR = 1.15;
// The canvas a page paints on when no ancestor paints a background. The
// browser default is white and the old hunt returned NO ANSWER instead, so
// `color: #ffffff` on a page that sets no background anywhere -- white text
// on the white canvas, invisible to a human -- scored as unmeasurable and
// passed.
var KS_DEFAULT_CANVAS = { r: 255, g: 255, b: 255, a: 1 };

var ksStyleCache = new Map();
function ksCS(el) {
  var v = ksStyleCache.get(el);
  if (v === undefined) { v = getComputedStyle(el); ksStyleCache.set(el, v); }
  return v;
}

// THE FLATTENED-TREE PARENT, and it is security code rather than tidiness.
// The first child of a shadow root has `parentElement === null`, so a climb
// written on `.parentElement` alone STOPS at the boundary and reports "no
// hidden ancestor" for content sitting under a `display:none` host. The slot
// hop is the same defect one boundary further in: a slotted node's light
// parent is the host, so a light-tree climb never sees the slot, the shadow
// wrapper, or anything else that actually renders it.
function ksUp(n) {
  if (!n) return null;
  if (n.assignedSlot) return n.assignedSlot;
  if (n.parentElement) return n.parentElement;
  var r = n.getRootNode && n.getRootNode();
  return (r && r.host) ? r.host : null;
}

// The LIGHT-tree climb, kept for the callers that mean document structure
// (landmark ancestry, region ownership) rather than rendering.
function ksUpLight(n) {
  if (!n) return null;
  if (n.parentElement) return n.parentElement;
  var r = n.getRootNode && n.getRootNode();
  return (r && r.host) ? r.host : null;
}

// THE ONE DEEP WALK: the light tree plus every OPEN shadow root, in host
// order, depth first. It lives here for the same reason `ksHiddenReason`
// does. Three copies of this recursion existed (the search's root sweep, the
// acting resolver's, and the extractor's) and the OCCLUSION scan had a fourth
// shape that was not a recursion at all -- a flat `querySelectorAll('*')`
// that stops dead at every shadow boundary. Re-attack 2 (A3) walked through
// exactly that gap: a `position:fixed` opaque lid inside an open root was
// unreachable by the scan while the same page's read counted the root two
// lines away. A component library that renders a skeleton loader into its own
// root defeats a light-tree-only scan by accident, so this is ordinary
// furniture rather than an attack.
//
// `fn` returning `false` STOPS the walk, which is how a caller spends a
// budget without the walk having to know what the budget is about. Closed
// roots stay unreachable and are counted at creation instead, which is the
// build's standing answer everywhere else.
function ksDeepEach(root, fn) {
  var stopped = false;
  (function walk(r) {
    var all;
    try { all = r.querySelectorAll('*'); } catch (e) { return; }
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (fn(el) === false) { stopped = true; return; }
      if (el.shadowRoot) { walk(el.shadowRoot); if (stopped) return; }
    }
  })(root);
  return !stopped;
}

// Every open shadow root under `root`, discovered by the walk above, with an
// optional per-element callback so a caller that also has to count something
// (iframes, for the search's `not_searched` block) gets it from the SAME
// sweep rather than a second one.
function ksOpenRoots(root, onEl) {
  var out = [];
  ksDeepEach(root, function (el) {
    if (onEl) onEl(el);
    if (el.shadowRoot) out.push(el.shadowRoot);
  });
  return out;
}

// THE TEXT OF A SUBTREE INCLUDING ITS OPEN SHADOW ROOTS, for the ledgers.
//
// `textContent` stops dead at every shadow boundary, and fix wave 9c is where
// that showed up as a false completeness claim rather than a leak.
// `corpus/g2/shadow_cloak.html` parks seven components inside seven
// containers, three of them hidden, and each component keeps its prose in its
// own OPEN root with no light children at all. `get_text` filtered the three
// correctly and then measured what it had withheld with `el.textContent`,
// which on a host with no light children is the empty string: three
// prompt-injection payloads suppressed, and a `stripped` line reading "0
// hidden block(s) carrying 0 characters ... [none]". `get_page_view` counted
// the same page correctly on the same read, because its walk is `ksDeepEach`.
// A caller comparing the two ledgers was told two different stories about one
// document, which is the disagreement this file exists to end.
//
// SLOTTED CONTENT IS NOT DOUBLE-COUNTED: a `<slot>`'s own text is its
// FALLBACK content, so a shadow root's `textContent` never contains the light
// nodes assigned into it, and those are already in the host's own.
var KS_DEEP_TEXT_MAX_ROOTS = 500;
function ksDeepTextContent(node, state) {
  if (!node) return '';
  var st = state || { roots: 0 };
  var out = node.textContent || '';
  if (node.shadowRoot && st.roots++ < KS_DEEP_TEXT_MAX_ROOTS) {
    out += ' ' + ksDeepTextContent(node.shadowRoot, st);
  }
  if (node.querySelectorAll) {
    var all = node.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      if (all[i].shadowRoot && st.roots++ < KS_DEEP_TEXT_MAX_ROOTS) {
        out += ' ' + ksDeepTextContent(all[i].shadowRoot, st);
      }
    }
  }
  return out;
}

// Containment across shadow boundaries. `a.contains(b)` is light-tree only,
// so a host does not contain its own shadow content by that measure, and the
// occlusion scan's "skip my own ancestors and descendants" filter needs the
// flattened answer or it compares a control against the component that
// renders it.
function ksContainsDeep(a, b) {
  for (var n = b; n; n = ksUp(n)) if (n === a) return true;
  return false;
}

function ksParseColor(v) {
  var m = /rgba?\(([^)]+)\)/.exec(v || '');
  if (!m) return null;
  var p = m[1].split(',').map(function (x) { return parseFloat(x); });
  return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
}

function ksLum(c) {
  var f = function (x) {
    x /= 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
}

// The product of every `opacity()` in a filter chain. `filter: opacity(0)`
// and `filter: opacity(50%) opacity(2%)` both end at nothing visible.
function ksFilterOpacity(s) {
  var f = s.filter;
  if (!f || f === 'none') return 1;
  var out = 1, m, re = /opacity\(\s*([0-9.]+)(%?)\s*\)/g;
  while ((m = re.exec(f))) {
    var v = parseFloat(m[1]);
    if (v !== v) continue;
    out *= (m[2] === '%' ? v / 100 : v);
  }
  return out;
}

// The largest blur radius in a filter chain, in CSS pixels.
function ksFilterBlur(s) {
  var f = s.filter;
  if (!f || f === 'none') return 0;
  var out = 0, m, re = /blur\(\s*([0-9.]+)px\s*\)/g;
  while ((m = re.exec(f))) {
    var v = parseFloat(m[1]);
    if (v === v && v > out) out = v;
  }
  return out;
}

// The WCAG contrast ratio between two luminances, which is what "can a human
// tell these apart" actually means. A luminance SUBTRACTION, which is what
// this used to do, is not a perceptual measure: the same 0.02 gap is
// invisible near white and an easy read near black.
function ksContrastRatio(a, b) {
  var hi = Math.max(a, b), lo = Math.min(a, b);
  return (hi + 0.05) / (lo + 0.05);
}

// A foreground that cannot be told from what is behind it. The alpha channel
// is read FIRST: `color: transparent` is `rgba(0,0,0,0)`, which the old
// luminance-only check scored as pure black against a white page and passed
// as high contrast. The background hunt bails on any background IMAGE in the
// chain, because a gradient or a sprite is a background this cannot measure
// and guessing there would strip real controls off real pages.
//
// When the hunt reaches the top of the chain WITHOUT finding a painted
// background, the answer is the browser's default canvas -- white -- and not
// "unmeasurable". Returning no answer there was R5's third break: a page that
// sets no background anywhere and writes in `#ffffff` is white on white, a
// human sees a blank area, and the check declined to look.
function ksInvisibleColor(el, s) {
  var fg = ksParseColor(s.color);
  if (!fg) return null;
  if (fg.a <= KS_OPACITY_FLOOR) return 'transparent-text';
  var node = el, bg = null, reachedRoot = false;
  for (var i = 0; node && i < 40; i++) {
    var ns = (node === el) ? s : ksCS(node);
    if (ns.backgroundImage && ns.backgroundImage !== 'none') return null;
    var c = ksParseColor(ns.backgroundColor);
    if (c && c.a > 0.1) { bg = c; break; }
    var next = ksUp(node);
    if (!next) { reachedRoot = true; break; }
    node = next;
  }
  // The canvas default applies only where the climb genuinely REACHED the
  // top and found nothing painted. A climb that merely ran out of budget
  // knows nothing about what is behind the element, and guessing white there
  // would cloak white-on-dark text sitting deep in a tree.
  if (!bg) {
    if (!reachedRoot) return null;
    bg = KS_DEFAULT_CANVAS;
  }
  return ksContrastRatio(ksLum(fg), ksLum(bg)) < KS_CONTRAST_RATIO_FLOOR
    ? 'low-contrast' : null;
}

// Techniques a DESCENDANT cannot undo, so they are checked up the chain.
function ksCompositedHidden(el, s) {
  if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
  if (el.hasAttribute && el.hasAttribute('hidden')) return 'hidden-attr';
  if (s.display === 'none') return 'display-none';
  if (s.contentVisibility === 'hidden') return 'content-visibility-hidden';
  if (ksFilterOpacity(s) <= KS_OPACITY_FLOOR) return 'filter-transparent';
  if (ksFilterBlur(s) >= KS_BLUR_FLOOR) return 'filter-blur';
  // Structural non-rendering, both one level up and both cheap to ask. The
  // parent here is the LIGHT parent and specifically NOT the boundary hop: an
  // element inside a shadow root has the host as its hopped parent, and the
  // host has a shadow root by definition, so hopping would call every top
  // node of every open root unslotted and hide the whole component.
  var p = el.parentElement;
  if (p && p.tagName === 'DETAILS' && !p.open && el.tagName !== 'SUMMARY') {
    return 'details-collapsed';
  }
  if (p && p.shadowRoot && !el.assignedSlot && el.tagName !== 'SLOT') {
    // A light child of a shadow host that no slot ever assigned is in the
    // DOM and is not on the screen. `find_elements` returned these as
    // ordinary visible matches (gauntlet M4) and acting on one dead-ends.
    return 'unslotted';
  }
  return null;
}

// Techniques carried by INHERITED properties, checked on the element itself.
// Its computed value already answers the inherited question, and reading it
// off an ancestor is what made a `visibility: visible` child of a
// `visibility: hidden` parent invisible to every tool in the build.
function ksInheritedHidden(el, s) {
  if (s.visibility === 'hidden' || s.visibility === 'collapse') return 'visibility-hidden';
  var fs = parseFloat(s.fontSize);
  if (fs === fs && fs < 2) return 'font-size-0';
  return ksInvisibleColor(el, s);
}

// ONE element, every technique, no climb.
function ksHiddenReason(el, style) {
  if (!el || el.nodeType !== 1) return null;
  var s = style || ksCS(el);
  var op = parseFloat(s.opacity);
  if (op === op && op <= KS_OPACITY_FLOOR) {
    return op === 0 ? 'opacity-0' : 'near-transparent';
  }
  return ksCompositedHidden(el, s) || ksInheritedHidden(el, s);
}

// Geometry, which is measured rather than computed and so stays separate:
// the extractor counts a zero-size or parked element differently from a
// styled-away one, and the rect is wanted by the caller either way.
function ksGeometryHidden(el, style) {
  var r = el.getBoundingClientRect();
  // BOTH axes, deliberately. A single-axis test was tried for H-05 and
  // reverted: a wrapper holding only floated or absolutely positioned
  // children legitimately measures zero height while its children paint,
  // and `text.js` RETURNS on a hidden verdict, so calling that wrapper
  // hidden would count its whole subtree as withheld. H-05's real
  // mechanism is the ancestor clip below, which is unambiguous.
  if (r.width === 0 && r.height === 0) return { reason: 'zero-size', rect: r };
  var x = r.left + window.scrollX, y = r.top + window.scrollY;
  if (x + r.width < -500 || y + r.height < -500 || x > 100000) {
    return { reason: 'offscreen', rect: r };
  }
  var s = style || ksCS(el);
  if (s.textIndent && parseFloat(s.textIndent) < -900) {
    return { reason: 'offscreen', rect: r };
  }
  var clipped = ksClippedAway(el, r, s);
  if (clipped) return { reason: clipped, rect: r };
  return { reason: null, rect: r };
}

// THE ANCESTOR CLIP (hostile H-05).
//
// `* { width:0; height:0; overflow:hidden }` leaves a button measuring 16x6
// in Chromium, because a button's border box survives `width:0`, so NO test
// of the element's own geometry can see it: the read offered
// `e1 | button | "Continue"` under "unlisted affordances: none, every
// control is listed", and the click then paid the full 15-second
// actionability timeout to find out, twice (15.09 s and 15.07 s). The
// sibling page zeroing only the BUTTON reported it correctly and refused in
// 0.01 s. One CSS effect, two verdicts.
//
// The ancestor is where the answer is. A zero-size box with `overflow:
// hidden` paints nothing inside it, and an element whose rect does not
// intersect such an ancestor at all is clipped out of the page.
//
// Only `hidden` and `clip` count. `scroll` and `auto` are REACHABLE:
// content scrolled out of an `overflow:auto` container is one scroll away,
// and calling it invisible would strip real controls off real pages, which
// is the direction this family of checks must never fail in. A `fixed`
// element escapes its ancestors' clipping entirely and is exempt.
function ksClippedAway(el, rect, style) {
  var s = style || ksCS(el);
  if (s.position === 'fixed') return null;
  var depth = 0;
  for (var n = ksUp(el); n && depth < 40; n = ksUp(n), depth++) {
    if (n === document.documentElement) break;
    var ns = ksCS(n);
    var ov = (ns.overflow || '') + ' ' + (ns.overflowX || '') + ' '
           + (ns.overflowY || '');
    if (!/\b(hidden|clip)\b/.test(ov)) {
      if (ns.position === 'fixed') break;
      continue;
    }
    var box = n.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return 'clipped-away';
    if (rect.right <= box.left || rect.left >= box.right
        || rect.bottom <= box.top || rect.top >= box.bottom) {
      return 'clipped-away';
    }
  }
  return null;
}

// THE CHAIN. The element's own techniques, then every composited technique up
// the flattened tree, with opacity accumulated as a PRODUCT so a chain of
// three 0.3s is correctly read as 0.027 and reported hidden.
function ksHiddenChain(el, stopAt) {
  var own = ksHiddenReason(el, null);
  if (own) return own;
  var eff = 1;
  for (var n = el; n && n !== stopAt; n = ksUp(n)) {
    if (n === document.documentElement) break;
    var s = ksCS(n);
    var op = parseFloat(s.opacity);
    if (op === op) eff *= op;
    if (eff <= KS_OPACITY_FLOOR) return eff === 0 ? 'opacity-0' : 'near-transparent';
    if (n !== el) {
      var r = ksCompositedHidden(n, s);
      if (r) return r;
    }
  }
  return null;
}

// The verdict the acting and searching surfaces use: styled away, structurally
// unrendered, or measured off the page. One answer, one vocabulary.
function ksHiddenAnywhere(el) {
  return ksHiddenChain(el, null) || ksGeometryHidden(el, null).reason || null;
}

// ---------------------------------------------------------------- OCCLUSION
//
// Something opaque is painted ON TOP of the control and the human sees the
// something. The re-attack (2026-09-06 R4) buried a real "Transfer balance to
// 9912" button under a white panel carrying a "Loading, please wait..." decoy
// and the agent's trusted click landed on the transfer.
//
// THIS HAS TO LIVE HERE rather than being left to the driver, and the fixture
// says exactly why. The panel was `pointer-events: none`, so it takes no
// pointer at all: Playwright's actionability net (which asks whether the
// element receives the click) sees a clean target, `checkVisibility()` returns
// true, and `document.elementFromPoint` at the button's own centre returns the
// BUTTON, because hit testing skips a `pointer-events: none` box by
// definition. Every hit-test-shaped answer is the wrong answer here. What a
// human sees is what is PAINTED, and painting is what this measures.
//
// The measure is PAINT ONLY, and the boundary with the driver is deliberate.
// When the thing on top DOES take the pointer, the click genuinely cannot
// land, Playwright's actionability check catches it, and the refusal it
// writes ("intercepted by another element") is both true and more useful than
// a cloak verdict would be -- corpus B's `#shield` is `rgba(255,0,0,.06)`, a
// human can see the button straight through it, and calling that invisible
// would be wrong. What no driver covers is the panel that paints over a
// control and declines the pointer, so that is exactly the case this owns.
//
// FALSE POSITIVES are the real risk, because sticky headers, toasts, and
// cookie bars legitimately overlap the EDGES of controls all day. Two rules
// keep those alone. The sample point is the element's CENTRE, not its corner,
// so a bar clipping the top of a button is not occlusion. And when the centre
// IS covered, a majority of a nine-point grid must be covered too; a control
// whose centre is under a toast while most of it is clear is reported VISIBLE,
// on the principle that a human who can see most of a control can see it. The
// choice trades a missed cloak for never stripping a real control off a real
// page, which is the direction this whole check has to fail in.

// ------------------------------------------------------------ PAINT ORDER
//
// A Z-INDEX ORDERS SIBLINGS INSIDE ONE STACKING CONTEXT AND NOTHING ELSE, and
// re-attack 3 (R2) is why this is a tree walk rather than a number. The rule
// this replaces returned the innermost DECLARED z-index up an element's chain
// and compared two of them as if they sat on one scale. They do not: a button
// declaring `z-index:9999` inside a wrapper whose own context is painted at 0
// is entirely beneath a lid at 1, which is what the browser draws and what the
// pixel proof reported, while the comparison said the button was on top.
//
// So the comparison happens where CSS says it happens: build each node's chain
// of stacking contexts up to the root, find the context the two share, and
// compare only the two entries that sit directly in it. Everything below that
// point paints with its container and cannot reorder itself out of it.

//: `will-change` promises a property that would establish a context, and the
//: browser establishes one up front to keep the promise.
var KS_CTX_WILL_CHANGE =
  /transform|opacity|filter|perspective|isolation|mix-blend-mode|backdrop/;

// Does this element start a new painting group. The list is the CSS
// stacking-context set, plus POSITIONED-WITH-AUTO-Z, which is not formally a
// stacking context and orders exactly like one: CSS 2.1 Appendix E paints
// every positioned z-auto descendant as its own unit, so for the question
// "which of these two boxes is on top" it behaves identically and leaving it
// out puts a positioned box's children on the wrong scale.
function ksEstablishesContext(el, s) {
  if (!el || el === document.documentElement) return true;
  if (s.position !== 'static') return true;
  var op = parseFloat(s.opacity);
  if (op === op && op < 1) return true;
  if (s.isolation === 'isolate') return true;
  if (s.mixBlendMode && s.mixBlendMode !== 'normal') return true;
  if (s.transform && s.transform !== 'none') return true;
  if (s.filter && s.filter !== 'none') return true;
  if ((s.backdropFilter || s.webkitBackdropFilter || 'none') !== 'none') return true;
  if (s.perspective && s.perspective !== 'none') return true;
  if (s.clipPath && s.clipPath !== 'none') return true;
  if (s.maskImage && s.maskImage !== 'none') return true;
  if (s.contain && /paint|layout|strict|content/.test(s.contain)) return true;
  if (s.willChange && KS_CTX_WILL_CHANGE.test(s.willChange)) return true;
  // A flex or grid ITEM with a declared z-index establishes one even though
  // it is not positioned.
  if (s.zIndex !== 'auto') {
    var p = ksUp(el);
    if (p && /flex|grid/.test(ksCS(p).display)) return true;
  }
  return false;
}

// The chain from the root down to the node, one entry per painting group the
// node sits inside. Consecutive entries are container and contained, so two
// chains share a prefix exactly as far as the two nodes share a context.
var ksCtxPathCache = new Map();
function ksCtxPath(node) {
  var hit = ksCtxPathCache.get(node);
  if (hit) return hit;
  var path = [], n = node, guard = 0;
  while (n && guard++ < 64) {
    path.push(n);
    var c = ksUp(n);
    while (c && !ksEstablishesContext(c, ksCS(c))) c = ksUp(c);
    if (!c || c === n) break;
    n = c;
  }
  path.reverse();
  ksCtxPathCache.set(node, path);
  return path;
}

// The chain for an OCCLUDER RECORD, which may be a pseudo-element. A
// pseudo-element paints inside its generator when the generator starts a
// group of its own, and alongside the generator when it does not, so the
// record is appended or substituted accordingly.
function ksEntryPath(c) {
  if (!c.ksPseudo) return ksCtxPath(c.el);
  var base = ksCtxPath(c.el).slice();
  if (!ksEstablishesContext(c.el, ksCS(c.el))) base.pop();
  base.push(c);
  return base;
}

// WHERE IN ITS OWN GROUP A BOX PAINTS, on one scale so two siblings compare.
// A declared z-index wins; a positioned box with `auto` paints at the level of
// z-index 0; an in-flow box paints below both and above any negative z-index.
function ksPaintLevel(n) {
  var s = n.ksPseudo ? n.ps : ksCS(n);
  var z = parseInt(s.zIndex, 10);
  if (z === z) return z * 4 + 2;
  return s.position !== 'static' ? 2 : 0;
}

// Document order between two entries in the same group, across shadow
// boundaries and with a pseudo-element ordered against its own generator: a
// `::before` paints under the generator's content and a `::after` over it.
function ksEntryOrder(a, b) {
  var ea = a.ksPseudo ? a.el : a, eb = b.ksPseudo ? b.el : b;
  if (ea === eb) {
    if (a.ksPseudo === b.ksPseudo) return 0;
    var av = a.ksPseudo === '::after' ? 1 : (a.ksPseudo === '::before' ? -1 : 0);
    var bv = b.ksPseudo === '::after' ? 1 : (b.ksPseudo === '::before' ? -1 : 0);
    return av - bv;
  }
  var ra = ksOrderRef(ea), rb = ksOrderRef(eb);
  if (ra === rb) return ra === ea ? -1 : 1;   // the shadow child, not the host
  try { return (ra.compareDocumentPosition(rb) & 4) ? -1 : 1; }
  catch (e) { return -1; }
}

// Does the candidate paint above the target. The two chains are compared at
// the group they share; nothing deeper than that can change the answer.
function ksPaintsAbove(cand, el) {
  var a = ksEntryPath(cand), b = ksCtxPath(el), i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  if (i >= a.length) return false;      // the candidate contains the target
  if (i >= b.length) return true;       // the target contains the candidate
  var la = ksPaintLevel(a[i]), lb = ksPaintLevel(b[i]);
  if (la !== lb) return la > lb;
  return ksEntryOrder(b[i], a[i]) < 0;
}

// THE LID DEFINITION IS "ANYTHING THAT PAINTS", and re-attack 2 is the reason
// it is written that way rather than as a list. Fix wave 4 learned "opaque"
// from the one lid R4 presented -- a `<div>` carrying `background:#ffffff` --
// and the rule it wrote asked two questions: is the background colour at
// least half opaque, or is there a background image. Seven constructions
// walked through the gap in a single round, and none of them is exotic:
//
//   * A REPLACED element paints its CONTENT and declares no background at
//     all. An `<img>`, `<canvas>`, `<video>`, an `<iframe>`, an `<svg>`: a
//     full-bleed loading spinner is an image, a consent wall and a chat
//     widget are iframes, and a drawing overlay is a canvas.
//   * `backdrop-filter` paints nothing of its own and re-renders everything
//     behind it. `blur(14px) brightness(2.4)` over a control leaves a blank
//     white rectangle, which is the strongest cloak in the set.
//   * STACKED translucent boxes each sit under a per-box threshold while the
//     stack transmits nothing. Five layers at alpha 0.45 pass 3% of what is
//     behind them, and a threshold a page can sit under one box at a time is
//     R5's bug one property along.
//   * A STATIC box overlaps by design in CSS. Same-cell grid items, table
//     cells, negative margins and floats all do it, and the old
//     `position:static && z-index:auto -> skip` early-out was a performance
//     shortcut standing in for a correctness claim.
//
// So the measure is one number per box: HOW MUCH of what is behind this does
// it replace, from 0 (nothing) to 1 (everything). Coverage at a point is the
// stack composited, not any single box tested.
//
// A MORE TRUTHFUL PRIMITIVE WAS LOOKED FOR. Two exist and both are
// disqualified, for reasons worth writing down so the next wave does not
// re-derive them.
//
//  * `document.elementsFromPoint` is HIT TESTING, and R4's own fixture is the
//    disqualification: the lid that started all of this is
//    `pointer-events:none`, so every hit test walks straight through it and
//    returns the button.
//  * IntersectionObserver v2 (`trackVisibility: true`) is the real candidate.
//    It asks the compositor whether the target is occluded or distorted, it
//    was designed for exactly this threat, and it would handle every class
//    above at once. It is not used, for four reasons that stack: it is
//    ASYNCHRONOUS and the spec requires `delay >= 100`, so every acting call
//    would wait on a timer; it is Chromium-only, and a visibility rule that
//    differs by engine is the divergence this file exists to remove; the spec
//    explicitly permits FALSE NEGATIVES ("the implementation may return
//    false"), which is a licence a refusal cannot be built on; and it returns
//    ONE BOOLEAN for the whole element with no technique named and no
//    majority rule, so a sticky header clipping a button's top edge is
//    reported the same way a full-bleed lid is. That last one is the
//    shipability question, not a detail.
//
// There is no synchronous "what paints above this rect" API, so the scan
// composites the boxes itself.

// The tags whose CONTENT is the paint. The class is HTML's replaced elements
// (HTML 4.7-4.8 embedded content), which the box model describes as a box
// with something else drawn into it, plus `<input type=image>`, which is a
// submit button wearing a picture.
var KS_REPLACED_TAGS = {
  IMG: 1, CANVAS: 1, VIDEO: 1, IFRAME: 1, FRAME: 1, EMBED: 1, OBJECT: 1,
  SVG: 1, MODEL: 1
};

function ksPaintsOwnContent(el) {
  var t = (el.tagName || '').toUpperCase();
  if (t === 'IMG') {
    // An image with nothing to draw paints nothing: a missing or failed src
    // renders as alt text, and calling that a lid would cloak real controls
    // sitting beside a broken image.
    if (!(el.currentSrc || el.getAttribute('src'))) return false;
    return !(el.complete && el.naturalWidth === 0);
  }
  if (KS_REPLACED_TAGS[t]) return true;
  return t === 'INPUT' && (el.type || '').toLowerCase() === 'image';
}

// A `backdrop-filter` that CHANGES what is behind it past legibility. The
// blur floor is the one already defended in R5 for the element's own filter,
// used here on the property that filters everything underneath; any non-blur
// function (brightness, contrast, invert, grayscale, opacity, saturate) is
// taken at its word, because none of them is applied to a backdrop by
// accident. A 1-2px glass blur on a nav bar is left alone.
function ksBackdropObliterates(s) {
  var f = s.backdropFilter || s.webkitBackdropFilter || '';
  if (!f || f === 'none') return false;
  if (/(brightness|contrast|invert|grayscale|sepia|saturate|opacity|hue-rotate|drop-shadow|url)\(/.test(f)) {
    return true;
  }
  return ksFilterBlur({ filter: f }) >= KS_BLUR_FLOOR;
}

// The effective opacity of a box including every ancestor's, which is what
// decides how much of ITS paint actually lands. Kept separate from
// `ksHiddenChain` for the reason the old `ksPaintsAtAll` was: that one
// answers whether a human can READ the element, and by that measure a modal
// backdrop is black-on-black low-contrast while being the most opaque thing
// on the page.
function ksPaintOpacity(el, s) {
  if (s.visibility === 'hidden' || s.visibility === 'collapse') return 0;
  if (s.contentVisibility === 'hidden') return 0;
  var eff = 1;
  for (var n = el; n; n = ksUp(n)) {
    if (n === document.documentElement) break;
    var ns = (n === el) ? s : ksCS(n);
    if (ns.display === 'none') return 0;
    eff *= ksFilterOpacity(ns);
    var op = parseFloat(ns.opacity);
    if (op === op) eff *= op;
    if (eff <= 0.02) return 0;
  }
  return eff;
}

//: How much of what is behind this box it replaces, in [0, 1]. Anything at or
//: below this is not paint anyone can see through a stack of.
var KS_LID_ALPHA_FLOOR = 0.02;

function ksLidAlpha(el, s) {
  var base = 0;
  if (ksPaintsOwnContent(el)) base = 1;
  else if (s.backgroundImage && s.backgroundImage !== 'none') base = 1;
  else {
    var bgc = ksParseColor(s.backgroundColor);
    if (bgc) base = bgc.a;
  }
  if (base < 1 && ksBackdropObliterates(s)) base = 1;
  if (base <= KS_LID_ALPHA_FLOOR) return 0;
  return base * ksPaintOpacity(el, s);
}

//: The scan's runaway guard, and it is a TIME budget rather than a count. The
//: count caps it replaces (the first 60 qualifying boxes, the first 8,000
//: nodes) were a bypass: 70 decorative 12x12 boxes earlier in document order
//: filled the budget with chaff and the scan stopped before the box that
//: mattered (re-attack 2, A6). A cap that silently converts to "not occluded"
//: is the wrong default, so selection is now geometric -- every box that
//: paints and is big enough to hide something, however far down the document
//: it sits -- and the only limit left is the wall-clock one that stops a
//: pathological page from hanging the tool.
var KS_OCCLUDER_BUDGET_MS = 1000;

//: Smaller than this in either dimension and a box cannot hide a control.
var KS_LID_MIN_PX = 8;

// A PSEUDO-ELEMENT IS PAINT WITH NO ELEMENT, which is re-attack 3's R1 and
// the reason the walk below asks two extra questions per node. `ksDeepEach`
// enumerates ELEMENTS; `::before` and `::after` generate boxes that paint and
// are not elements, so `body::after{position:fixed;inset:0;background:#fff}`
// is a full-bleed scrim in three declarations that no `getComputedStyle` call
// in the old scan ever saw. It reported zero overlapping boxes on a page whose
// button rendered as blank white.
//
// THE SCOPE IS THE POSITIONED PSEUDO-ELEMENT, and the boundary is a
// measurement problem rather than a judgement. A pseudo-element has no
// `getBoundingClientRect`, so its rect has to be reconstructed from computed
// values, and Chromium resolves `left/top/width/height` to used pixels only
// where the box is positioned. An in-flow `::before` also cannot cover a
// control it does not generate space for -- it displaces layout instead --
// so the class this leaves out is the one that cannot be a lid. A pseudo
// moved over a control by a negative margin is the stated residual, and the
// pixel arbiter on the acting path is what would catch it if it mattered.
var KS_PSEUDOS = ['::before', '::after'];

function ksPseudoRect(el, s, ps) {
  var pos = ps.position;
  if (pos !== 'fixed' && pos !== 'absolute') return null;
  var w = parseFloat(ps.width), h = parseFloat(ps.height);
  if (!(w === w) || !(h === h) || w < KS_LID_MIN_PX || h < KS_LID_MIN_PX) {
    return null;
  }
  var l = parseFloat(ps.left), t = parseFloat(ps.top);
  var bx = 0, by = 0;
  if (pos === 'fixed') {
    if (!(l === l)) {
      var rr = parseFloat(ps.right);
      l = (rr === rr) ? (window.innerWidth - rr - w) : 0;
    }
    if (!(t === t)) {
      var bb = parseFloat(ps.bottom);
      t = (bb === bb) ? (window.innerHeight - bb - h) : 0;
    }
  } else {
    // The containing block is the nearest positioned ancestor, starting with
    // the generator itself; with none, it is the initial containing block.
    var cb = null;
    for (var n = el; n; n = ksUp(n)) {
      if (((n === el) ? s : ksCS(n)).position !== 'static') { cb = n; break; }
    }
    var base = cb ? cb.getBoundingClientRect()
                  : { left: -window.scrollX, top: -window.scrollY };
    bx = base.left; by = base.top;
    if (!(l === l)) l = 0;
    if (!(t === t)) t = 0;
    l += bx; t += by;
  }
  return { left: l, top: t, right: l + w, bottom: t + h,
           width: w, height: h };
}

// A pseudo-element's own paint, on the same 0-to-1 scale as a box's. It
// cannot go through `ksLidAlpha`, which reads the GENERATOR's tag: a
// `::after` on an `<img>` is not an image and paints nothing but what it
// declares. What it does share is the generator's ancestor chain, because
// every opacity and filter above the generator lands on the pseudo too.
function ksPseudoAlpha(el, ps) {
  if (ps.visibility === 'hidden' || ps.visibility === 'collapse') return 0;
  var base = 0;
  if (ps.backgroundImage && ps.backgroundImage !== 'none') base = 1;
  else {
    var c = ksParseColor(ps.backgroundColor);
    if (c) base = c.a;
  }
  if (base < 1 && ksBackdropObliterates(ps)) base = 1;
  if (base <= KS_LID_ALPHA_FLOOR) return 0;
  var own = parseFloat(ps.opacity);
  if (own === own) base *= own;
  base *= ksFilterOpacity(ps);
  return base * ksPaintOpacity(el, ksCS(el));
}

// WHICH ELEMENTS CAN GENERATE A PSEUDO-ELEMENT AT ALL, read off the page's own
// style rules. Asking `getComputedStyle(el, '::after')` twice per node is the
// exhaustive answer and it is the expensive one, so the scan first tries to
// name the hosts: a pseudo-element exists only because a rule declares
// `content` for one, an inline `style` attribute cannot create one, and the
// selectors that do are enumerable. A stylesheet this document cannot read
// (a cross-origin one) makes the set incomplete, and an incomplete set would
// be a page-controlled blind spot, so the answer is `null` there and the scan
// falls back to asking everything.
function ksPseudoHosts(roots) {
  var set = new Set(), scopes = [document].concat(roots), ok = true;
  for (var i = 0; i < scopes.length && ok; i++) {
    var scope = scopes[i];
    var lists = [scope.styleSheets || [], scope.adoptedStyleSheets || []];
    for (var b = 0; b < lists.length && ok; b++) {
      for (var j = 0; j < lists[b].length && ok; j++) {
        var rules;
        try { rules = lists[b][j].cssRules; } catch (e) { return null; }
        if (!rules) return null;
        ok = ksCollectPseudoHosts(rules, set, scopes, 0);
      }
    }
  }
  return ok ? set : null;
}

function ksCollectPseudoHosts(rules, set, scopes, depth) {
  if (depth > 4) return true;
  for (var i = 0; i < rules.length; i++) {
    var r = rules[i];
    // A RULE CAN BE BOTH. Nested CSS gave every `CSSStyleRule` its own
    // `cssRules` list, so an `if (r.cssRules) { recurse; continue; }` shape
    // treats every ordinary rule as a grouping rule and never reads a single
    // selector -- which is exactly how this returned an empty host set on a
    // page whose `#deco::after` was sitting in the first stylesheet.
    if (r.cssRules && r.cssRules.length
        && !ksCollectPseudoHosts(r.cssRules, set, scopes, depth + 1)) {
      return false;
    }
    var sel = r.selectorText;
    if (!sel || (sel.indexOf(':before') < 0 && sel.indexOf(':after') < 0)) continue;
    var parts = sel.split(',');
    for (var j = 0; j < parts.length; j++) {
      var base = parts[j].replace(/::?(before|after)\b[\s\S]*$/i, '').trim();
      if (!base || base === ':root' || base === ':host') base = '*';
      for (var k = 0; k < scopes.length; k++) {
        var hit;
        try { hit = scopes[k].querySelectorAll(base); } catch (e) { return false; }
        for (var m = 0; m < hit.length; m++) set.add(hit[m]);
      }
    }
  }
  return true;
}

// The page's painting boxes, scanned ONCE per injected call. The geometry
// test comes before the style read on purpose: `getBoundingClientRect` is
// cheap after the first forced layout and `getComputedStyle` is not, so the
// scan pays full price only for boxes big enough to hide something.
var ksOccluderCache = null;
var ksOccluderTruncated = false;
function ksOccluders() {
  if (ksOccluderCache) return ksOccluderCache;
  var out = [];
  ksOccluderTruncated = false;
  try {
    var t0 = Date.now(), seen = 0;
    var hosts = ksPseudoHosts(ksOpenRoots(document));
    ksDeepEach(document, function (el) {
      if (((++seen) & 511) === 0 && Date.now() - t0 > KS_OCCLUDER_BUDGET_MS) {
        ksOccluderTruncated = true;
        return false;
      }
      var r = el.getBoundingClientRect();
      var s = null;
      if (r.width >= KS_LID_MIN_PX && r.height >= KS_LID_MIN_PX) {
        s = ksCS(el);
        var a = ksLidAlpha(el, s);
        if (a > KS_LID_ALPHA_FLOOR) {
          out.push({ el: el, rect: r, a: a, ksPseudo: null });
        }
      }
      if (hosts && !hosts.has(el)) return;
      for (var i = 0; i < KS_PSEUDOS.length; i++) {
        var ps;
        try { ps = getComputedStyle(el, KS_PSEUDOS[i]); } catch (e) { continue; }
        if (!ps || !ps.content || ps.content === 'none' || ps.content === 'normal') continue;
        if (ps.display === 'none') continue;
        var pr = ksPseudoRect(el, s || (s = ksCS(el)), ps);
        if (!pr) continue;
        var pa = ksPseudoAlpha(el, ps);
        if (pa <= KS_LID_ALPHA_FLOOR) continue;
        out.push({ el: el, rect: pr, a: pa, ksPseudo: KS_PSEUDOS[i], ps: ps });
      }
    });
  } catch (e) { out = []; }
  ksOccluderCache = out;
  return out;
}

// Drop everything the paint scan memoized. The caches are correct for one
// layout and one style recalculation, and the acting path deliberately
// re-takes the verdict after letting the page's own queued work run.
function ksResetPaintCaches() {
  ksOccluderCache = null;
  ksReadLidCache = null;
  ksStyleCache = new Map();
  ksCtxPathCache = new Map();
}

// Document order across shadow boundaries. `compareDocumentPosition` between
// two different trees reports DISCONNECTED and an implementation-specific
// order, so each node is compared at the ancestor that lives in the document
// tree -- a shadow child paints with its host. Two nodes that reduce to the
// same host are ordered by depth: the component's own tree paints after the
// host's background.
function ksOrderRef(n) {
  for (var p = n; p;) {
    var r = p.getRootNode ? p.getRootNode() : document;
    if (r === document || !r.host) return p;
    p = r.host;
  }
  return n;
}

// COVERAGE AT A POINT: the stack composited, not one box tested. Each layer
// passes `1 - alpha` of what is behind it, so five boxes at 0.45 leave
// 0.55^5 = 3% showing and the point is covered, while corpus B's
// `rgba(255,0,0,.06)` shield leaves 94% showing and is not.
function ksCoverageAt(over, x, y) {
  var through = 1;
  for (var i = 0; i < over.length; i++) {
    var b = over[i].rect;
    if (x >= b.left && x <= b.right && y >= b.top && y <= b.bottom) {
      through *= (1 - over[i].a);
      if (through <= 0.5) return 1;
    }
  }
  return 1 - through;
}

function ksPointCovered(over, x, y) {
  return ksCoverageAt(over, x, y) >= 0.5;
}

// WHAT THE MAJORITY RULE IS APPLIED TO. The rule itself does not move: the
// centre must be covered and a majority of a nine-point grid with it, which
// is what keeps sticky headers, toasts, and cookie bars from cloaking the
// controls they clip. What re-attack 2 (A8) showed is that the grid was
// sampling the wrong rectangle. A 340x12 band sited exactly on a button's
// LABEL covers three of nine points on the button's box and every point of
// the text, and a human recognises a control by its label rather than by its
// bounding box, so the sample set is the accessible name's own client rects
// where the element renders text and the box grid where it does not (an icon
// button, an input, an image). The header arms stay green because a bar
// clipping a button's top edge covers neither its centre nor most of its
// label, and the documented centre-badge trade (A9) stays exactly where wave
// 4 put it: a 60x20 badge over a 195px label is one column of three.
function ksTextRects(el) {
  var out = [];
  try {
    if (!el.textContent || !el.textContent.trim()) return out;
    var rng = document.createRange();
    rng.selectNodeContents(el);
    var rects = rng.getClientRects();
    for (var i = 0; i < rects.length && out.length < 8; i++) {
      var r = rects[i];
      if (r.width >= 4 && r.height >= 4) out.push(r);
    }
  } catch (e) { return []; }
  return out;
}

function ksSampleRects(el, box) {
  var t = ksTextRects(el);
  return t.length ? t : [box];
}

// The box-math pass: which boxes paint above this control, and do enough of
// them land on it. Returns the candidates alongside the verdict, because the
// pixel arbiter on the acting path needs to know which lids to take out of
// the paint before it can ask the compositor whether they matter.
function ksOcclusionScan(el) {
  if (!el || !el.getBoundingClientRect) return null;
  var r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;   // geometry speaks for itself
  var over = [], all = ksOccluders();
  for (var k = 0; k < all.length; k++) {
    var c = all[k];
    // A pseudo-element is never an ancestor of anything, so the containment
    // filter applies to its GENERATOR only in the descendant direction: a
    // `::after` on the control itself or on something inside it is the
    // control's own rendering, and one on an ancestor is a scrim.
    if (!c.ksPseudo && (c.el === el || ksContainsDeep(c.el, el))) continue;
    if (ksContainsDeep(el, c.el)) continue;
    if (c.rect.right <= r.left || c.rect.left >= r.right
        || c.rect.bottom <= r.top || c.rect.top >= r.bottom) continue;
    if (!ksPaintsAbove(c, el)) continue;
    over.push(c);
  }
  if (!over.length) return null;
  var boxes = ksSampleRects(el, r), covered = 0, total = 0, centre = false;
  for (var b = 0; b < boxes.length; b++) {
    var q = boxes[b];
    if (ksPointCovered(over, q.left + q.width / 2, q.top + q.height / 2)) {
      centre = true;
    }
    for (var i = 1; i <= 3; i++) {
      for (var j = 1; j <= 3; j++) {
        total++;
        if (ksPointCovered(over, q.left + q.width * (i / 4),
                           q.top + q.height * (j / 4))) covered++;
      }
    }
  }
  if (!centre || covered * 2 <= total) return null;
  return { reason: 'occluded', over: over, rect: r, boxes: boxes };
}

function ksOccludedReason(el) {
  var scan = ksOcclusionScan(el);
  return scan ? scan.reason : null;
}

// ---------------------------------------------- THE READ-SIDE CLOAK CHECK
//
// PAINT-ORDER OCCLUSION, ON THE READ SIDE (fix wave 9b, 2026-09-08). The
// acting path refuses a click on a control an opaque panel is painted over,
// and every read surface in the build handed the SAME construction back as
// ordinary prose: `corpus/g2/cloak_light.html` parks a paragraph under an
// identically-sized `#fff` sibling at a higher z-index, a human never sees a
// character of it, and `get_text` printed it as content and did not even
// count it in the `stripped` ledger. That is the read-side sibling of the
// R4 click bug, and prose is where it actually lives: a hidden instruction a
// tool reads out as legitimate visible text is the whole injection game.
//
// THIS CHECK IS DELIBERATELY NARROWER THAN THE ACTING PATH'S, and the
// narrowing is measured rather than assumed. `ksOcclusionScan` is box math,
// and box math produces false positives that only the pixel arbiter can
// clear -- run unmodified over the blocks `get_text` emits it strips 53
// blocks of real prose from the frozen Wikipedia article in `corpus/a`
// (navbox `v`/`t`/`e` links under in-flow `<th>` cells of a nested table
// that overlap them in that snapshot) and costs 420ms of scan on top of the
// page-wide occluder pass. The read cannot afford the screenshot arbiter
// that would clear those, so it asks a stricter question instead:
//
//   1. THE LID IS OUT OF FLOW. Only `fixed`, `absolute`, and `sticky` boxes
//      count, plus positioned pseudo-elements (`ksPseudoRect` already
//      demands that of them). This is the same predicate `viewportLid` in
//      `extract.js` already uses for the page-level answer the read has
//      trusted since H-09, so the two agree by construction. Measured: it
//      takes both frozen Wikipedia pages to zero false positives and 26ms.
//   2. THE PAINT IS EFFECTIVELY TOTAL. Composited coverage at or above
//      KS_READ_CLOAK_ALPHA, computed exactly rather than through
//      `ksCoverageAt`'s at-or-above-half shortcut, so an ordinary modal
//      backdrop at `rgba(0,0,0,.6)` is NOT a read cloak. A human reads
//      dimmed text; a human reads nothing at all under an opaque box. The
//      acting path keeps its own at-or-above-half rule, because clicking
//      through a scrim is the harm and reading through one is not.
//   3. THE WHOLE BOX IS COVERED, not a majority of it: 25 sample points,
//      corners inset by a pixel. A sticky header clipping a paragraph's top
//      edge leaves 20 of them clear on the first point tested.
//
// The residual, stated because an unstated one is what this fix exists to
// remove: an IN-FLOW static box that covers text -- the `static-grid` class
// in the lid battery -- is caught by the acting path and not by this one.
// Widening to static boxes is what produced the 53 false positives above.
var KS_READ_CLOAK_ALPHA = 0.95;

// -------------------------------------------- AND AN ALPHA IT CAN TRUST
//
// FIX WAVE 9C, and the finding is 9b's own fix pointed the other way. The
// re-verify round ran the seven constructions the pixel arbiter exists to
// clear through the READ's question and six of them came back cloaked: a
// `clip-path` lid, a transparent mask, a decorative full-viewport `<svg>`, an
// undrawn `<canvas>`, a 1x1 spacer `<img>`, and `mix-blend-mode: multiply`.
// A publisher's continue-reading fade -- `position:absolute; bottom:0;
// background:linear-gradient(rgba(255,255,255,.15), rgba(255,255,255,.35))`,
// which is ordinary markup on a large fraction of the web -- took the whole
// article body out of `get_text` and reported it as hidden content "with the
// shape of an injected instruction". That is this build's cardinal defect
// class running in the direction that costs a reader content.
//
// THE THREE CONDITIONS WERE NEVER THE PROBLEM. Thirteen boundary shapes were
// attacked and all thirteen landed on their documented side: 0.94 reads,
// 0.95 cloaks, two stacked 0.8 lids composite to 0.96 and cloak, in-flow
// static stays the stated residual. The defect is in the ALPHA the lid is
// credited with BEFORE the 0.95 threshold ever sees it. `ksLidAlpha` has two
// shortcuts that hand out 1.0 on a tag name or on the mere presence of a
// background image:
//
//     if (ksPaintsOwnContent(el)) base = 1;
//     else if (s.backgroundImage && s.backgroundImage !== 'none') base = 1;
//
// A CSS gradient IS a background-image, so every gradient lid is opaque by
// construction and no narrowing of the threshold can reach it -- the number
// being compared does not mean what its name says. And `ksPaintsOwnContent`
// answers on the tag for `IMG, CANVAS, VIDEO, IFRAME, FRAME, EMBED, OBJECT,
// SVG, MODEL`, so a transparent spacer GIF and an out-of-flow ad iframe are
// both totally opaque lids.
//
// Those shortcuts are CORRECT for the consumer they were written for. The
// acting path takes the box math as a PROPOSAL and confirms it against a
// screenshot, so a generous alpha there costs a second measurement and
// nothing else. The read has no arbiter and cannot afford one, so it must
// not consume a number that was calibrated for one.
//
// SO THE READ FAILS TOWARD READING. A lid whose alpha this file cannot
// compute from CSS alone is not a read lid at all: unknown paint means the
// prose comes back. The acting path is unchanged and still refuses the click
// on every one of these, with the arbiter still deciding, so the safety
// property 9b bought is exactly where it was. What the read gives up is the
// cloaked-gradient case, which needs a screenshot to tell from a publisher's
// fade and which no box can answer.
//
// What "cannot compute" means, and it is a closed list rather than a
// judgement: paint clipped away (`clip-path`), paint masked away (`mask`),
// paint composited by something other than source-over (`mix-blend-mode`),
// paint that comes from an image or gradient rather than a colour
// (`background-image`), and paint that IS the element's content (the
// replaced tags). Everything else is a background colour with an alpha
// channel, which is arithmetic. `backdrop-filter` still counts as total,
// because it changes what is behind it past legibility by its own
// declaration rather than by a paint this file has to guess at.
function ksReadPaintUnknown(el, s) {
  if (s.clipPath && s.clipPath !== 'none') return 'clipped';
  var mask = s.maskImage || s.webkitMaskImage || '';
  if (mask && mask !== 'none') return 'masked';
  if (s.mixBlendMode && s.mixBlendMode !== 'normal') return 'blended';
  if (s.backgroundImage && s.backgroundImage !== 'none') return 'image';
  if (el && ksPaintsOwnContent(el)) return 'replaced';
  return null;
}

//: A clip or a mask on an ANCESTOR clips the lid's paint too, and the climb
//: is affordable because it runs only over boxes that already survived the
//: out-of-flow filter. Bounded by the same document-element stop every other
//: climb in this file uses.
function ksReadPaintUnknownChain(el, s) {
  var own = ksReadPaintUnknown(el, s);
  if (own) return own;
  for (var n = ksUp(el); n && n !== document.documentElement; n = ksUp(n)) {
    var ns = ksCS(n);
    if (ns.clipPath && ns.clipPath !== 'none') return 'clipped-ancestor';
    var m = ns.maskImage || ns.webkitMaskImage || '';
    if (m && m !== 'none') return 'masked-ancestor';
    if (ns.mixBlendMode && ns.mixBlendMode !== 'normal') return 'blended-ancestor';
  }
  return null;
}

// The read's own alpha for one occluder. Returns null when the paint is not
// computable, which drops the candidate rather than rounding it up to 1.
function ksReadLidAlpha(cand) {
  var el = cand.el;
  var s = cand.ksPseudo ? cand.ps : ksCS(el);
  // A pseudo-element has no element of its own, so the replaced-tag half of
  // the question does not apply to it; its generator's chain still does.
  if (cand.ksPseudo) {
    if (ksReadPaintUnknown(null, s)) return null;
    if (ksReadPaintUnknownChain(el, ksCS(el))) return null;
  } else if (ksReadPaintUnknownChain(el, s)) {
    return null;
  }
  var base = 0;
  var bgc = ksParseColor(s.backgroundColor);
  if (bgc) base = bgc.a;
  if (base < 1 && ksBackdropObliterates(s)) base = 1;
  if (base <= KS_LID_ALPHA_FLOOR) return 0;
  if (cand.ksPseudo) {
    var own = parseFloat(s.opacity);
    if (own === own) base *= own;
    base *= ksFilterOpacity(s);
    return base * ksPaintOpacity(el, ksCS(el));
  }
  return base * ksPaintOpacity(el, s);
}

var ksReadLidCache = null;
function ksReadLids() {
  if (ksReadLidCache) return ksReadLidCache;
  var out = [], all = ksOccluders();
  for (var i = 0; i < all.length; i++) {
    var c = all[i];
    if (!c.ksPseudo) {
      var pos = ksCS(c.el).position;
      if (pos !== 'fixed' && pos !== 'absolute' && pos !== 'sticky') continue;
    }
    var a = ksReadLidAlpha(c);
    if (a === null || a <= KS_LID_ALPHA_FLOOR) continue;
    // A COPY, never the acting path's record. The two paths credit the same
    // box with different alphas on purpose and they run in the same process
    // over the same cache, so writing this number onto the shared object
    // would silently re-grade every click on the page.
    out.push({ el: c.el, rect: c.rect, a: a, ksPseudo: c.ksPseudo,
               ps: c.ps });
  }
  ksReadLidCache = out;
  return out;
}

// `ksCoverageAt` returns 1 the moment the stack passes half, which is the
// right shortcut for a question whose threshold IS half. This one has to
// report the real composited number, because the read's threshold is 0.95.
function ksExactCoverage(over, x, y) {
  var through = 1;
  for (var i = 0; i < over.length; i++) {
    var b = over[i].rect;
    if (x >= b.left && x <= b.right && y >= b.top && y <= b.bottom) {
      through *= (1 - over[i].a);
    }
  }
  return 1 - through;
}

function ksPaintCloaked(el) {
  var lids = ksReadLids();
  if (!lids.length) return null;            // the common page stops here
  if (!el || !el.getBoundingClientRect) return null;
  var r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;
  var over = [];
  for (var i = 0; i < lids.length; i++) {
    var c = lids[i];
    if (!c.ksPseudo && (c.el === el || ksContainsDeep(c.el, el))) continue;
    if (ksContainsDeep(el, c.el)) continue;
    if (c.rect.right <= r.left || c.rect.left >= r.right
        || c.rect.bottom <= r.top || c.rect.top >= r.bottom) continue;
    if (!ksPaintsAbove(c, el)) continue;
    over.push(c);
  }
  if (!over.length) return null;
  var xs = [r.left + 1, r.left + r.width / 4, r.left + r.width / 2,
            r.left + r.width * 3 / 4, r.right - 1];
  var ys = [r.top + 1, r.top + r.height / 4, r.top + r.height / 2,
            r.top + r.height * 3 / 4, r.bottom - 1];
  for (var xi = 0; xi < xs.length; xi++) {
    for (var yi = 0; yi < ys.length; yi++) {
      if (ksExactCoverage(over, xs[xi], ys[yi]) < KS_READ_CLOAK_ALPHA) {
        return null;
      }
    }
  }
  return 'paint-cloaked';
}

// ------------------------------------------------------- THE PIXEL ARBITER
//
// BOX MATH PROPOSES, THE COMPOSITOR DISPOSES. Re-attack 3's R4 opened the one
// direction DESIGN says this check may not fail in: seven ordinary
// constructions -- `clip-path`, a transparent mask, a decorative full-viewport
// `<svg>`, an undrawn `<canvas>`, a scrolled `overflow` container, a spacer
// `<img>`, and `mix-blend-mode` -- made every acting call on the page refuse
// while the control was fully visible. Three separate root causes, and one
// sentence covers all three: a box's DECLARED paint is not what reaches the
// pixel. `getBoundingClientRect` is not the painted region, a tag is not its
// content, and compositing is not multiplication.
//
// Chasing those one at a time is the instance-list mistake three re-attacks in
// a row have now named, and the browser already holds the answer. So when the
// box math says a control is covered, the acting path CONFIRMS it against the
// rendering: screenshot the control's own area as the page stands, hide the
// candidate lids, screenshot it again, and compare the bytes. Identical means
// the lids paint nothing over the control and the refusal would be a false
// positive; different means something really is on top and the refusal stands.
// That is the attacker's own OVERLAY-NO-OP proof, run as a gate.
//
// The arbiter runs ONLY on the acting path and ONLY where the box math has
// already flagged, so an ordinary page pays nothing for it: the cheap pass is
// still the cheap pass, and the expensive pass runs on the handful of calls
// that were about to be refused. The read path keeps the box-math answer, on
// the reasoning the occlusion check has always used -- reading a covered
// control is not the harm, clicking one is.
//
// `visibility:hidden` is the hiding mechanism rather than `display:none`
// because it takes the box out of the PAINT and leaves it in the LAYOUT.
// Removing a lid from the layout would move everything under it and the
// second screenshot would differ for a reason that has nothing to do with
// occlusion.
var KS_ARBITER_STYLE_ID = 'ks4web-arbiter-hide';
var KS_ARBITER_ATTR = 'data-ks4web-lid';

function ksPixelPrep(el) {
  var scan = ksOcclusionScan(el);
  if (!scan) return null;
  var flags = { '': false, 'b': false, 'a': false };
  for (var i = 0; i < scan.over.length; i++) {
    var c = scan.over[i];
    var kind = c.ksPseudo === '::before' ? 'b' : (c.ksPseudo === '::after' ? 'a' : '');
    try { c.el.setAttribute(KS_ARBITER_ATTR + (kind ? '-' + kind : ''), ''); }
    catch (e) { continue; }
    flags[kind] = true;
  }
  // The area a human would be looking at: the sample rects the majority rule
  // ran on, clipped to the viewport, which is the only region a screenshot
  // can address.
  var left = 1e9, top = 1e9, right = -1e9, bottom = -1e9;
  for (var b = 0; b < scan.boxes.length; b++) {
    var q = scan.boxes[b];
    if (q.left < left) left = q.left;
    if (q.top < top) top = q.top;
    if (q.right > right) right = q.right;
    if (q.bottom > bottom) bottom = q.bottom;
  }
  left = Math.max(0, Math.floor(left));
  top = Math.max(0, Math.floor(top));
  right = Math.min(window.innerWidth, Math.ceil(right));
  bottom = Math.min(window.innerHeight, Math.ceil(bottom));
  if (right - left < 1 || bottom - top < 1) { ksPixelRelease(); return null; }
  return { x: left, y: top, width: right - left, height: bottom - top,
           lids: scan.over.length, flags: flags };
}

//: The three attributes the prep pass writes, and the rules that take the
//: boxes carrying them out of the paint.
var KS_ARBITER_ATTRS = ['data-ks4web-lid', 'data-ks4web-lid-b',
                        'data-ks4web-lid-a'];
var KS_ARBITER_CSS =
  '[data-ks4web-lid]{visibility:hidden!important}'
  + '[data-ks4web-lid-b]::before{content:none!important;display:none!important}'
  + '[data-ks4web-lid-a]::after{content:none!important;display:none!important}';

// The rules go into EVERY open root as well as the document, because a
// document stylesheet does not reach inside a shadow tree and a lid rendered
// by a component library lives in one (re-attack 2, A3).
function ksPixelHide() {
  var scopes = [document].concat(ksOpenRoots(document));
  for (var i = 0; i < scopes.length; i++) {
    var scope = scopes[i];
    if (scope.getElementById && scope.getElementById(KS_ARBITER_STYLE_ID)) continue;
    var st = document.createElement('style');
    st.id = KS_ARBITER_STYLE_ID;
    st.textContent = KS_ARBITER_CSS;
    var host = (scope === document)
      ? (document.head || document.documentElement) : scope;
    try { host.appendChild(st); } catch (e) { /* a root that refuses */ }
  }
  return true;
}

function ksPixelRelease() {
  var scopes = [document].concat(ksOpenRoots(document));
  for (var i = 0; i < scopes.length; i++) {
    var st = scopes[i].getElementById
      ? scopes[i].getElementById(KS_ARBITER_STYLE_ID) : null;
    if (st && st.parentNode) st.parentNode.removeChild(st);
  }
  ksDeepEach(document, function (el) {
    if (!el.removeAttribute) return;
    for (var k = 0; k < KS_ARBITER_ATTRS.length; k++) {
      if (el.hasAttribute(KS_ARBITER_ATTRS[k])) {
        el.removeAttribute(KS_ARBITER_ATTRS[k]);
      }
    }
  });
  return true;
}

// The subset that means CLOAKED: the element is laid out, hit-testable, and
// dispatches trusted input, and a human still cannot see it. Acting on one of
// these is the steer-the-agent-onto-an-invisible-button attack, so the acting
// path refuses and names the technique. Geometry is deliberately NOT in this
// set: an element parked off-screen is a layout fact the driver scrolls to,
// and `display:none` is not here either because it refuses on its own.
var KS_CLOAK_TECHNIQUES = {
  'opacity-0': 'its opacity is zero',
  'near-transparent': 'its opacity is near zero',
  'filter-transparent': 'a CSS filter reduces it to full transparency',
  'filter-blur': 'a CSS filter blurs it past legibility',
  'transparent-text': 'its foreground colour is transparent',
  'low-contrast': 'its foreground colour matches its background',
  'content-visibility-hidden': 'content-visibility:hidden stops it rendering',
  'details-collapsed': 'it sits inside a collapsed <details>',
  'unslotted': 'it is a light child of a component that never slotted it',
  'visibility-hidden': 'visibility:hidden stops it rendering',
  'occluded': 'an opaque panel is painted over it'
};

// The ACTING verdict. `occluded` is computed HERE and deliberately not inside
// `ksHiddenChain`, which is the difference between this function and
// `ksHiddenAnywhere`, and the reason is cost rather than doctrine:
// `ksHiddenChain` runs once per element on every extraction of a ten-thousand
// node page, and occlusion needs a page-wide scan plus up to nine hit tests
// per element. Reading an occluded control is also not the harm; CLICKING one
// is, so the check sits on the path where the harm is. The read route stays
// open and says what it always said.
function ksCloakReason(el) {
  var r = ksHiddenChain(el, null);
  if (r && KS_CLOAK_TECHNIQUES[r]) return r;
  return ksOccludedReason(el);
}
// THE ONE PAYMENT-SHAPE SOURCE. Spliced into extract.js and the acting
// scripts at load time (`projection/__init__.py`), so there is exactly one
// in-page implementation of "is this a card field" and "does this form carry
// one" in the build.
//
// It exists for the reason visibility.js exists. The rule had FOUR in-page
// copies (the extractor's `formPayment`, the extractor's per-affordance and
// per-field `payment`, the acting resolver's, and the focused-descriptor
// reader's) and every one of them was the same two lines of autocomplete
// regex. The 2026-09-06 re-attack (R3) walked through the gap those copies
// share rather than a gap between them: a page that simply omits
// `autocomplete` is unclassified by all four at once.
//
// Two rules here, and they answer different questions:
//
//  * `ksPaymentField(el)` -- is THIS control a card field. Declared
//    autocomplete first, because a page that labels its own fields is telling
//    the truth about them; then the field's NAMES, because a page that
//    declares nothing still has to call the field something a human reads.
//  * `ksFormPayment(form)` -- does this form carry one anywhere, which is what
//    makes SUBMITTING it a payment action rather than a plain one.
//
// `ksFormPayment` walks `form.elements`, NOT `form.querySelectorAll`. An
// input carrying `form="pay"` is form-ASSOCIATED wherever it sits in the
// document -- the HTML spec puts it in `form.elements` and it submits with
// the form -- and a descendant-only query walks straight past it. Moving the
// card field one sibling out of the <form> tag was a one-attribute bypass of
// the payment gate.

// Autocomplete tokens that declare a payment field. The `cc-name` token is
// here for the FORM question and not for the field question: a cardholder
// name is a payment field's neighbour rather than a credential, and it makes
// the form payment-shaped without being the number itself.
var KS_PAYMENT_AC = /cc-number|cc-exp|cc-csc|cc-name/;

// Payment NAMES, matched on a field's squashed identifiers, in two tiers
// because the short ones are initialisms that collide with ordinary words.
// A long token matches as a SUBSTRING of the de-spaced string, so
// `card_number`, `cardNumber`, `card-number` and `Card number` all reduce to
// `cardnumber`. A short one must stand as its own WORD, so `cvc` classifies
// and `cvcompany` does not.
//
// THE VOCABULARY IS NOT ENGLISH, and re-attack 2 (B1) is why it says so here.
// DESIGN's own statement of what this tier is for -- "the pages this defends
// against are exactly the ones that declare nothing while still calling the
// field something a human reads" -- has no language in it, and the list did:
// `kartennummer` was simply absent, and the squash below reduced a Korean
// 카드번호 or a Japanese カード番号 to the EMPTY STRING before a single token
// was compared. A live PAN went into all three ungated.
//
// SOURCES for the non-English terms, because inventing vocabulary for a
// security gate is how a gate ends up firing on the wrong thing:
//  * The localized card-field labels browser autofill matches on. Chromium's
//    autofill heuristics (`components/autofill/core/browser/*regex*`) carry
//    exactly this family -- `kartennummer`, `numero de carte`, `numero de
//    tarjeta`, `numero della carta`, `カード番号`, `카드번호`, `信用卡`,
//    `sicherheitscode`, `codigo de seguridad`, `セキュリティコード` -- because
//    they are what real checkout pages in those languages actually write.
//  * The WHATWG HTML autocomplete tokens (`cc-number`, `cc-exp`, `cc-csc`)
//    remain the declared tier above and are language-independent.
// Terms below are the ordinary rendering of "card number", "expiry", and
// "security code" in each language; each is the label a human in that market
// reads on a checkout page.

// TIER 1: A CARD NUMBER. A match here classifies the field on its own.
var KS_PAN_TERMS = [
  // English
  'cardnumber', 'cardnum', 'cardno', 'ccnumber', 'ccnum',
  'creditcard', 'debitcard', 'cardholder', 'nameoncard', 'cardname',
  // German: Kartennummer, Kreditkarte, Karteninhaber
  'kartennummer', 'kartennr', 'kreditkarte', 'karteninhaber',
  // French: numéro de carte, carte bancaire, carte de crédit
  'numerodecarte', 'numerodelacarte', 'cartebancaire', 'cartedecredit',
  'titulairedelacarte',
  // Spanish / Portuguese: número de tarjeta, tarjeta de crédito,
  // número do cartão, cartão de crédito
  'numerodetarjeta', 'tarjetadecredito', 'tarjetacredito',
  'numerodocartao', 'cartaodecredito', 'titulardelatarjeta',
  // Italian: numero della carta, carta di credito
  'numerodellacarta', 'numerodicarta', 'cartadicredito',
  // Korean: 카드번호 (card number), 신용카드 (credit card), 카드 소유자
  '카드번호', '신용카드', '체크카드', '카드소유자',
  // Japanese: カード番号, クレジットカード, カード名義
  'カード番号', 'クレジットカード', 'カードナンバー', 'カード名義',
  // Chinese: 卡号 (card number), 信用卡, 持卡人
  '卡号', '卡號', '信用卡', '持卡人', '銀行卡', '银行卡'
];

// TIER 2: THE CARD NUMBER'S NEIGHBOURS -- expiry and security code. These are
// GENERIC phrases in every language on this list ("expiry date", "security
// code", 유효기간, 有効期限), so a match classifies the field only where the
// same form also carries a card number. A passport expiry and a one-time-code
// box are not payment fields, and a gate that says they are is the gate DESIGN
// warns people learn to route around. The card-QUALIFIED compounds
// (`cardexpiry`, `ccexp`, `securitycode`) stay in tier 1's company below,
// because the qualifier is the disambiguation.
var KS_CARD_SIDE_TERMS = [
  // English, card-qualified: these classify alone.
  'cardexpiry', 'cardexpiration', 'cardexp', 'ccexpiry', 'ccexp',
  'securitycode', 'cardcode', 'cardsecurity', 'cvvnumber'
];
var KS_CARD_NEIGHBOUR_TERMS = [
  // German: gültig bis, Ablaufdatum, Prüfziffer, Prüfnummer, Sicherheitscode
  'gultigbis', 'ablaufdatum', 'prufziffer', 'prufnummer', 'sicherheitscode',
  // French: date d'expiration, cryptogramme visuel, code de sécurité
  'dateexpiration', 'dexpiration', 'cryptogramme', 'codedesecurite',
  // Spanish / Portuguese: fecha de caducidad, fecha de vencimiento,
  // código de seguridad, validade
  'fechadecaducidad', 'fechadevencimiento', 'codigodeseguridad', 'validade',
  // Italian: scadenza, codice di sicurezza
  'scadenza', 'codicedisicurezza',
  // Korean: 유효기간 (valid period), 보안코드 (security code)
  '유효기간', '보안코드', '유효기한',
  // Japanese: 有効期限, セキュリティコード, カード確認番号
  '有効期限', 'セキュリティコード', 'カード確認番号',
  // Chinese: 有效期, 安全码, 安全碼
  '有效期', '安全码', '安全碼'
];
var KS_PAYMENT_WORDS = /(^| )(cvv|cvv2|cvc|cvc2|csc|ccv)( |$)/;

// NOT EVERY "<something> card number" IS A PAYMENT FIELD. `cardnumber`
// matches as a substring, which is what makes `card_number` and `Card number`
// both work and also made `Library card number`, `Loyalty card number`, and
// `Boarding card number` payment fields (re-attack 2, B6). A payment
// confirmation on a library form is the erosion DESIGN names by name.
//
// B6's answer was the right rule wearing the wrong clothes. It said the token
// immediately preceding `card` names the INSTRUMENT, which is true, and then
// implemented it as a HAND-MAINTAINED LIST OF NON-PAYMENT INSTRUMENTS -- which
// is an instance list, and re-attack 3 (M4) found the unlisted member in one
// try: `Residence card number` classified as payment, and a residence card is
// the standard foreign-resident ID across this build's own market.
//
// So the rule is stated the way it was always meant to be, and the OPEN set
// is the one that stops being enumerated. The set of payment instruments is
// small and closed -- credit, debit, gift, bank, prepaid, and the networks --
// and the set of everything else a card can be is unbounded. A `card`
// qualified by anything outside the payment set is a foreign instrument
// whatever it is called, so `residence`, `fishing`, and `punch` need no entry.
//
// Two lists, and neither is an instrument list. `KS_PAYMENT_QUALIFIERS` is the
// closed payment set. `KS_TRANSPARENT_WORDS` is English grammar: a function
// word qualifies nothing, which is what keeps `Name on card` a card field.
var KS_PAYMENT_QUALIFIERS = [
  'credit', 'debit', 'gift', 'bank', 'prepaid', 'pre', 'charge', 'payment',
  'pay', 'visa', 'master', 'mastercard', 'amex', 'american', 'express',
  'discover', 'jcb', 'unionpay', 'maestro', 'atm', 'cash', 'store', 'travel'
];
var KS_TRANSPARENT_WORDS = [
  'on', 'the', 'a', 'an', 'my', 'your', 'our', 'their', 'this', 'that', 'of',
  'for', 'to', 'and', 'or', 'in', 'no', 'new', 'enter', 'please', 'valid',
  'number', 'nr', 'no'
];

// Strike every `<foreign> card` compound out of a spaced haystack, and say
// whether one was found. The qualifier goes with it, so `library card number`
// leaves `number` and matches nothing.
// The QUALIFIER only counts as one where it reads as a word naming a thing.
// A haystack is every identifier on the control run together, so `id=c_card`
// contributes the token pair `c card` and a rule that takes any preceding
// token would read `c` as an instrument. Three guards keep it honest: the
// qualifier is at least three characters, it is not `card` itself repeating
// from a second identifier, and it is not already a card term.
function ksIsForeignQualifier(prev) {
  if (!prev || prev === 'card') return false;
  if (KS_PAYMENT_QUALIFIERS.indexOf(prev) >= 0) return false;
  // The SHORT qualifiers stay on the named list, because two characters is
  // also the length of an identifier fragment: `id_card_number` squashes to
  // `id card number` and so does `cc_card_number`, and only one of them names
  // a foreign instrument. `id` is on the list and `cc` is not, which is
  // exactly the distinction a length threshold cannot draw.
  if (prev.length < 3) return KS_NOT_PAYMENT_CARDS.indexOf(prev) >= 0;
  if (KS_TRANSPARENT_WORDS.indexOf(prev) >= 0) return false;
  return !ksHasTerm(prev, KS_PAN_TERMS)
      && !ksHasTerm(prev, KS_CARD_SIDE_TERMS);
}

// The compound is broken rather than deleted: `card` becomes a space, which a
// substring match cannot cross, and the qualifier stays where it was. Deleting
// both is what let `Card number` written alongside an `id=c_card` lose its own
// `cardnumber` token to a cascade.
function ksForeignCardStrike(hay) {
  var words = String(hay || '').trim().split(' ');
  var out = [], foreign = false;
  for (var i = 0; i < words.length; i++) {
    if (words[i] === 'card' && i > 0 && ksIsForeignQualifier(words[i - 1])) {
      foreign = true;
      out.push(' ');
      continue;
    }
    out.push(words[i]);
  }
  return { text: out.join(''), foreign: foreign };
}

// The GLUED spellings, which the word rule above cannot reach because there is
// no space to read a preceding word from: `name=librarycard` is one token. The
// list stays for exactly that case and is no longer the whole rule.
var KS_NOT_PAYMENT_CARDS = [
  'library', 'loyalty', 'membership', 'member', 'boarding', 'id', 'identity',
  'sim', 'key', 'room', 'door', 'access', 'badge', 'business', 'report',
  'score', 'student', 'staff', 'employee', 'health', 'insurance', 'medicare',
  'social', 'birthday', 'greeting', 'memory', 'sd', 'graphics', 'video',
  'sound', 'rewards', 'reward', 'points', 'club', 'discount', 'stamp',
  'punch', 'time', 'swipe', 'game', 'gaming', 'phone', 'index', 'tarot',
  'wild'
];

// A `pattern` that spells a 13-to-19 digit run is a card number whatever the
// field is called. Nothing else common has that shape: a postcode is four to
// nine, a phone number is seven to fifteen and usually admits separators, and
// an account number is rarely constrained at all. `inputmode` was considered
// for this tier and REJECTED: `inputmode="numeric"` is on every quantity,
// postcode, and OTP box on the web, and a signal that fires on all of them
// would make the payment gate the thing people route around.
var KS_PAN_PATTERN = /\{\s*1[3-9]\s*(,\s*(1[3-9])?\s*)?\}/;

// A PAN SHAPE shown to the HUMAN rather than declared to the validator. The
// `pattern` tier above reads `{13,19}` off an attribute a page is free to
// omit; `placeholder="1234 5678 9012 3456"` is the same declaration aimed at
// the person filling the form, and a masked `value="**** **** **** ****"` is
// that declaration after the fact (re-attack 2, B3 and B4). Four groups of
// four, or a bare 13-to-19 digit run, and nothing else: an IBAN carries
// letters, a phone number carries punctuation, and a date is too short.
function ksPanShape(v) {
  if (!v) return false;
  var s = String(v).trim();
  if (s.length < 13 || s.length > 32) return false;
  var core = s.replace(/[ \-]/g, '');
  if (core.length < 13 || core.length > 19) return false;
  return /^[0-9]+$/.test(core) || /^[*x\u2022\u00b7#]+$/i.test(core);
}

// THE NORMALIZER, and it has to be Unicode-honest or the tier above cannot
// see the label at all. `[^a-z0-9]+ -> ' '` reduced 카드번호 and カード番号 to
// nothing, and the `length > 2` guard then dropped the field before any token
// was compared: the classifier was not missing a Korean word, it could not
// see any Korean word. Letters and digits of EVERY script survive; only
// separators collapse. Diacritics are folded (NFKD, strip the LATIN combining
// block, recompose) so `numéro` and `gültig` reduce to the ASCII spellings the
// vocabulary lists, and Hangul and kana recompose unharmed. The range matters:
// stripping every combining mark would also take U+3099, the Japanese voiced
// sound mark, which turns ド into ト and カード番号 into a word that matches
// nothing. The Python mirror does exactly this range and a test pins the two.
function ksSquashNames(raw) {
  var s = String(raw || '').slice(0, 400);
  s = s.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
  try {
    s = s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').normalize('NFC');
  } catch (e) { /* an engine without normalize keeps the raw string */ }
  return ' ' + s.replace(/[^\p{L}\p{N}]+/gu, ' ').trim() + ' ';
}

// Every string on a control that can NAME it, squashed to lowercase words.
// camelCase is split first, so `cardNumber` reads as two words, and every
// separator collapses to one space.
function ksNameHaystack(el) {
  if (!el || !el.getAttribute) return '';
  var bits = [el.getAttribute('name'), el.id,
    el.getAttribute('aria-label'), el.getAttribute('placeholder'),
    el.getAttribute('title'), el.getAttribute('data-testid')];
  // The field's own <label>, which is what a human actually reads, and the
  // only one of these a well-built page is guaranteed to have.
  try {
    var labels = el.labels;
    if (labels) {
      for (var i = 0; i < labels.length && i < 4; i++) {
        bits.push(labels[i].textContent);
      }
    }
    var ariaLb = el.getAttribute('aria-labelledby');
    if (ariaLb) {
      var lb = document.getElementById(ariaLb.split(/\s+/)[0]);
      if (lb) bits.push(lb.textContent);
    }
  } catch (e) {}
  return ksSquashNames(bits.filter(Boolean).join(' '));
}

// The de-spaced haystack with every foreign-instrument card compound struck
// out, so a substring match cannot land inside `librarycard`. Both routes run:
// the word rule reads the qualifier off the spaced string and reaches any
// qualifier at all, and the glued list catches the spellings that carry no
// space to read.
// Break a glued `<foreign>card` spelling inside ONE word. The match has to
// start the word, or the qualifier has to be four characters or more:
// searching the whole de-spaced haystack for `idcard` found it inside
// `prepaidcardnumber` and struck a real payment instrument out of its own
// name, which is what a two-letter token does to a boundary-free search.
function ksStrikeGlued(word) {
  for (var i = 0; i < KS_NOT_PAYMENT_CARDS.length; i++) {
    var q = KS_NOT_PAYMENT_CARDS[i], token = q + 'card';
    if (word.indexOf(token) === 0) {
      return { text: ' ' + word.slice(token.length), hit: true };
    }
    if (q.length >= 4 && word.indexOf(token) > 0) {
      return { text: word.split(token).join(' '), hit: true };
    }
  }
  return { text: word, hit: false };
}

function ksPaymentCompactInfo(hay) {
  var words = String(hay || '').trim().split(' ');
  var out = [], foreign = false;
  for (var i = 0; i < words.length; i++) {
    if (words[i] === 'card' && i > 0 && ksIsForeignQualifier(words[i - 1])) {
      foreign = true;
      out.push(' ');
      continue;
    }
    var g = ksStrikeGlued(words[i]);
    if (g.hit) foreign = true;
    out.push(g.text);
  }
  return { compact: out.join(''), foreign: foreign };
}

function ksPaymentCompact(hay) {
  return ksPaymentCompactInfo(hay).compact;
}

function ksHasTerm(compact, terms) {
  for (var i = 0; i < terms.length; i++) {
    if (compact.indexOf(terms[i]) >= 0) return true;
  }
  return false;
}

// The name tier, shared by the field question and the form question. TIER 1
// only: a card number, or a card-qualified expiry or security code. Returns
// the FOREIGN flag alongside the verdict, because a `<X> card number` is not
// simply "not a card": it is a card compound whose instrument is something
// else, and a form that also carries an expiry box or a declared `cc-number`
// token can still make it one (ruling on M4).
function ksPaymentNameInfo(el) {
  var hay = ksNameHaystack(el);
  if (hay.length < 3) return { name: false, foreign: false, hay: hay };
  if (KS_PAYMENT_WORDS.test(hay)) return { name: true, foreign: false, hay: hay };
  var info = ksPaymentCompactInfo(hay);
  var hit = ksHasTerm(info.compact, KS_PAN_TERMS)
    || ksHasTerm(info.compact, KS_CARD_SIDE_TERMS);
  return { name: hit, foreign: info.foreign && !hit, hay: hay };
}

function ksPaymentName(el) {
  return ksPaymentNameInfo(el).name;
}

// DOES ANYTHING ELSE ON THIS FORM SAY CARD. The corroboration the M4 ruling
// asks for, and the same signal the shape tiers below need: a declared
// `cc-*` token, a sibling expiry or security-code box, or a sibling the name
// tier already classifies. It never asks `ksPaymentField` back, so there is no
// recursion and no way for two weak signals to bootstrap each other.
var ksCorroborationCache = new Map();
function ksCardCorroborated(el) {
  var ac = (el.getAttribute && el.getAttribute('autocomplete') || '').toLowerCase();
  if (KS_PAYMENT_AC.test(ac)) return true;
  var form = ksFormOf(el);
  if (!form) return false;
  var v = ksCorroborationCache.get(form);
  if (v !== undefined) return v;
  v = false;
  try {
    var els = form.elements || [];
    for (var i = 0; i < els.length && i < 500; i++) {
      var x = els[i];
      if (!x || !x.getAttribute) continue;
      if (KS_PAYMENT_AC.test((x.getAttribute('autocomplete') || '').toLowerCase())) {
        v = true; break;
      }
      var info = ksPaymentCompactInfo(ksNameHaystack(x));
      if (ksHasTerm(info.compact, KS_CARD_NEIGHBOUR_TERMS)
          || ksHasTerm(info.compact, KS_CARD_SIDE_TERMS)) { v = true; break; }
    }
  } catch (e) { v = false; }
  ksCorroborationCache.set(form, v);
  return v;
}

// DOES THIS CONTROL CARRY A NAME AT ALL -- any identifier with letters in it.
// It decides whether the SHAPE tiers get to speak on their own (M3 and M5).
// A `pattern` of thirteen-to-nineteen digits, a PAN-shaped placeholder, and a
// masked PAN-shaped value are all real signals and none of them is a name: a
// phone field declaring `[0-9]{13,15}`, an IMEI field showing fifteen digits,
// a tracking-number field showing four groups of four, and a field labelled
// `IBAN` holding `**** **** **** ****` all gated as payment on shape alone.
// A page that NAMES its field is telling the truth about it, so the name
// governs, and the shape speaks where the page named nothing or where
// something else on the form corroborates it.
function ksHasNaming(hay) {
  try { return /\p{L}\p{L}/u.test(hay); } catch (e) { return /[a-z]{2}/.test(hay); }
}

// The neighbour tier, which needs a card number somewhere in the same form.
function ksPaymentNeighbourName(el) {
  var hay = ksNameHaystack(el);
  if (hay.length < 3) return false;
  return ksHasTerm(ksPaymentCompact(hay), KS_CARD_NEIGHBOUR_TERMS);
}

// A SPLIT CARD NUMBER, which is a mainstream checkout layout and was
// unclassified end to end (re-attack 2, B2): four boxes named `cc1..cc4`,
// `maxlength=4`, `pattern="[0-9]{4}"`, under a `<legend>Card number</legend>`
// the haystack never reads. No tier fired, so the FORM was not payment-shaped
// either and the submit that sends the number got the weaker gate.
//
// The class is a GROUP of short numeric boxes whose combined length reads as
// a PAN. The group is the fieldset or the shared parent, the count is two to
// six, and the digits total 13 to 19 -- which is what separates it from every
// other split field on the web: a date is 2+2+4, a phone is 3+3+4, an OTP is
// six boxes of one, and a split IBAN runs past 19. The measurements are
// returned as FACTS so the server-side re-derivation applies the same rule to
// the same numbers rather than trusting a verdict.
// A box's declared digit capacity. `maxlength` is the usual way to say "this
// holds four digits" and it is not the only one: re-attack 3 (R5) declared
// `size=4 pattern="[0-9]{4}" inputmode=numeric` with no `maxlength`, the group
// came back empty, and the full sixteen digits landed in the field because
// nothing even truncated them. A `pattern` that pins a length says the same
// thing the attribute says, so it counts, and `size` corroborates that the box
// is a short one rather than a full-width field with a validation rule.
function ksPatternLen(pat) {
  var m = /^\^?(?:\[0-9\]|\\d)\{(\d+)(?:,\s*(\d+))?\}\$?$/
    .exec(String(pat || '').replace(/\s+/g, ''));
  if (!m) return 0;
  var hi = m[2] ? parseInt(m[2], 10) : parseInt(m[1], 10);
  return (hi >= 1 && hi <= 6) ? hi : 0;
}

function ksNumericBoxLen(el) {
  if (!el || el.tagName !== 'INPUT') return 0;
  var t = (el.type || 'text').toLowerCase();
  if (t !== 'text' && t !== 'tel' && t !== 'number' && t !== 'password') return 0;
  var im = (el.getAttribute('inputmode') || '').toLowerCase();
  var pat = el.getAttribute('pattern') || '';
  var numeric = im === 'numeric' || im === 'decimal' || t === 'number'
    || t === 'tel' || /\[0-9\]|\\d/.test(pat);
  if (!numeric) return 0;
  var ml = parseInt(el.getAttribute('maxlength'), 10);
  if (ml === ml && ml >= 1 && ml <= 6) return ml;
  var pl = ksPatternLen(pat);
  if (!pl) return 0;
  var sz = parseInt(el.getAttribute('size'), 10);
  return (sz === sz && sz <= 8) ? pl : 0;
}

// WHAT THE REGION CALLS ITSELF: 1 where it names a card number, -1 where it
// names some other instrument, 0 where it says nothing either way. This is
// M1's answer. The split-group rule counted boxes and never read a name, so a
// `<legend>Library card number</legend>` over four 4-digit boxes gated as a
// payment form while B6 had already struck `librarycard` out of the NAME tier.
// One rule, two places it has to be asked.
//: Memoized per region, because the extractor asks it once per short numeric
//: box and a split card number is four of them sharing one fieldset. Reading
//: a form's whole `textContent` four times to get the same answer is the kind
//: of per-element cost the latency gate exists to catch.
var ksRegionNameCache = new Map();
function ksRegionCardName(scope) {
  var seen = ksRegionNameCache.get(scope);
  if (seen !== undefined) return seen;
  var answer = ksRegionCardNameUncached(scope);
  ksRegionNameCache.set(scope, answer);
  return answer;
}

function ksRegionCardNameUncached(scope) {
  var text = '';
  try { text = (scope.textContent || '').slice(0, 400); } catch (e) { return 0; }
  var info = ksPaymentCompactInfo(ksSquashNames(text));
  if (ksHasTerm(info.compact, KS_PAN_TERMS)
      || ksHasTerm(info.compact, KS_CARD_SIDE_TERMS)) return 1;
  return info.foreign ? -1 : 0;
}

// A SPLIT CARD NUMBER'S GROUP IS A RUN, NOT A PARENT. Re-attack 3 (R5) put one
// wrapper `<div>` around each box -- which is what every CSS framework does to
// build a column layout -- and `closest('fieldset') || parentElement` handed
// back a group of one. So the group is discovered by STRUCTURE: within the
// enclosing fieldset or form, take the boxes in document order and keep the
// unbroken run of short numeric ones this box belongs to. Wrappers are
// transparent because the run never looks at them.
function ksPanGroup(el) {
  if (!ksNumericBoxLen(el)) return null;
  var scope = null;
  try { scope = el.closest('fieldset') || ksFormOf(el) || el.parentElement; }
  catch (e) {}
  if (!scope) return null;
  var boxes, lens = [], idx = -1;
  try { boxes = scope.querySelectorAll('input'); } catch (e) { return null; }
  for (var i = 0; i < boxes.length && i < 200; i++) {
    lens.push(ksNumericBoxLen(boxes[i]));
    if (boxes[i] === el) idx = i;
  }
  if (idx < 0) return null;
  var lo = idx, hi = idx;
  while (lo > 0 && lens[lo - 1]) lo--;
  while (hi + 1 < lens.length && lens[hi + 1]) hi++;
  var size = 0, digits = 0, min = 99;
  for (var j = lo; j <= hi; j++) {
    size++;
    digits += lens[j];
    if (lens[j] < min) min = lens[j];
  }
  return { size: size, digits: digits, first: lens[lo], min: min,
           region: ksRegionCardName(scope) };
}

// IS THIS RUN A CARD NUMBER. Two to six boxes totalling thirteen to nineteen
// digits is the count, and it is not enough on its own: a date of birth plus a
// texted code is 2+2+4+6, four short numeric boxes and fourteen digits inside
// the same window (M2). What separates them is the PARTITION. Card numbers are
// written in groups of four or more -- 4-4-4-4, amex's 4-6-5, Diners' 4-6-4 --
// and nothing else on a form is, because a date leads with a two-digit day and
// a phone leads with a three-digit area code. So the run has to lead with four
// and hold no box shorter than four, and the region must not name a different
// instrument.
function ksPanGroupIsCard(g) {
  if (!g) return false;
  if (!(g.size >= 2 && g.size <= 6 && g.digits >= 13 && g.digits <= 19)) {
    return false;
  }
  if (g.region < 0) return false;
  return g.first >= 4 && g.min >= 4;
}

// IS THIS CONTROL A CARD FIELD. Declared token, then name, then the PAN-shaped
// pattern attribute, then the PAN shape a human is shown, then the split
// group, and last the neighbour tier which needs a card number in the form.
function ksPaymentField(el) {
  if (!el || !el.getAttribute) return false;
  var ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  if (KS_PAYMENT_AC.test(ac)) return true;
  var named = ksPaymentNameInfo(el);
  if (named.name) return true;
  if (named.foreign) return ksCardCorroborated(el);
  var pat = el.getAttribute('pattern') || '';
  var shaped = (pat && KS_PAN_PATTERN.test(pat) && /0-9|\\d/.test(pat))
    || ksPanShape(el.getAttribute('placeholder'))
    || ksPanShape(el.getAttribute('title'))
    || ksPanShape('value' in el ? el.value : '');
  if (shaped && (!ksHasNaming(named.hay) || ksCardCorroborated(el))) return true;
  if (ksPanGroupIsCard(ksPanGroup(el))) return true;
  return ksPaymentNeighbourName(el) && ksFormHasCard(ksFormOf(el));
}

// The tier-1 answer for a whole form, which the neighbour tier asks and which
// must NOT ask `ksPaymentField` back. Everything here is a card number or a
// card-qualified compound, so there is no recursion and no way for two
// neighbour fields to bootstrap each other into a payment form.
var ksFormCardCache = new Map();
function ksFormHasCard(formEl) {
  if (!formEl) return false;
  var v = ksFormCardCache.get(formEl);
  if (v !== undefined) return v;
  v = false;
  try {
    var els = formEl.elements || [];
    for (var i = 0; i < els.length && i < 500; i++) {
      var el = els[i];
      if (!el || !el.getAttribute) continue;
      if (KS_PAYMENT_AC.test((el.getAttribute('autocomplete') || '').toLowerCase())
          || ksPaymentName(el)
          || ksPanGroupIsCard(ksPanGroup(el))) { v = true; break; }
      var shaped = ksPanShape(el.getAttribute('placeholder'))
        || ksPanShape('value' in el ? el.value : '');
      if (shaped && !ksHasNaming(ksNameHaystack(el))) { v = true; break; }
    }
  } catch (e) { v = false; }
  ksFormCardCache.set(formEl, v);
  return v;
}

// DOES THIS FORM CARRY ONE. Memoized per form: `form_payment` is asked once
// per affordance and a checkout page has one form with thirty controls in it.
var ksFormPaymentCache = new Map();
function ksFormPayment(formEl) {
  if (!formEl) return false;
  var v = ksFormPaymentCache.get(formEl);
  if (v !== undefined) return v;
  v = false;
  try {
    var els = formEl.elements || [];
    for (var i = 0; i < els.length && i < 500; i++) {
      if (ksPaymentField(els[i])) { v = true; break; }
    }
  } catch (e) { v = false; }
  ksFormPaymentCache.set(formEl, v);
  return v;
}

// The form a control belongs to, by ASSOCIATION and not by ancestry, so a
// `form="pay"` field reports the form it actually submits with.
//
// The ancestry fallback climbs the FLATTENED tree, which is the same sweep
// R6 asked for in `activation.js`: a node slotted into a shadow form has the
// host as its light parent and `closest('form')` walks straight past the form
// that would actually submit it.
function ksFormOf(el) {
  if (!el) return null;
  if (el.form !== undefined && el.form !== null) return el.form;
  for (var n = el, guard = 0; n && guard++ < 64; n = ksUp(n)) {
    if (n.tagName === 'FORM') return n;
  }
  return null;
}
// THE ONE ACTIVATION-TARGET SOURCE. Spliced into `extract.js` and the acting
// scripts at load time (`projection/__init__.py`), so there is exactly one
// in-page answer to "which element does this click actually activate".
//
// It exists because re-attack 2 (C1) asked a question no fix wave had asked.
// R1 widened the submit-button test from one instance to HTML's three submit
// states, which was right, and left the PRIOR question untouched: the
// classifier models the element the tool TOUCHES, and the browser routes the
// activation somewhere else. `<label for="go">Continue</label>` over a submit
// button parked off-screen is an ordinary styling pattern, and clicking the
// label submitted a form carrying a live card number with no class computed
// at all, because a `<label>` is not a payment field and is not a submitter.
//
// THE CLASS IS DELEGATED ACTIVATION, and HTML defines its members rather than
// leaving them to a list anyone maintains by hand:
//
//  * A `<label>` runs LABEL ACTIVATION BEHAVIOUR and forwards the activation
//    to `label.control`. `for=` and a wrapping label are the same mechanism
//    and `HTMLLabelElement.control` answers for both.
//  * A node with no activation behaviour of its own delegates UP: the click
//    bubbles and the nearest ancestor that IS an activatable control is what
//    runs. Clicking the `<span>` inside a submit button presses the button;
//    clicking the `<img>` inside a link follows the link.
//
// So the rule is one climb and one hop, and the answer feeds the SAME choke
// point everything else does: `action_class_for` reads the activation
// target's submission facts alongside the touched element's own.

//: Controls the browser activates. `[role=button]` is here because ARIA says
//: a click on one is a button press and pages build them out of divs.
var KS_ACTIVATABLE = 'button,input,select,textarea,a[href],label,summary,'
  + 'option,area[href],[role="button"],[role="link"],[role="menuitem"]';

//: The tags that ARE their own activation target, so the climb can be skipped
//: entirely. This is correctness before it is economy: the browser runs the
//: INNERMOST activatable element's behaviour, so a control that is itself one
//: is the answer and no ancestor can take the activation from it. The economy
//: matters too, because the extractor asks this question once per affordance
//: and `closest()` with a five-clause selector on a 100,000-node page is the
//: kind of per-element cost the latency gate exists to catch.
var KS_SELF_ACTIVATING = {
  BUTTON: 1, INPUT: 1, SELECT: 1, TEXTAREA: 1, SUMMARY: 1, OPTION: 1
};
var KS_ACTIVATION_ROLES = { button: 1, link: 1, menuitem: 1 };

// The effective submission type, and the ONE copy of the rule. The HTML spec
// says a `<button>` with a missing or invalid type IS a submit button; only
// `button` and `reset` opt out. An EXPLICIT `type=submit` keeps its declared
// semantics anywhere, matching `<input type=submit>`; the default-submit case
// applies only inside a form, where a click can actually submit something.
// `<input type=submit>` and `<input type=image>` need no folding, because the
// IDL `type` getter already reports both.
function ksSubmitTypeOf(el, inForm) {
  if (!el || !el.tagName) return null;
  if (el.tagName === 'INPUT') return (el.type || 'text').toLowerCase();
  if (el.tagName !== 'BUTTON') return null;
  var raw = ((el.getAttribute('type') || '').trim().toLowerCase());
  if (raw === 'button' || raw === 'reset') return raw;
  if (raw === 'submit') return 'submit';
  return inForm ? 'submit' : (raw || null);
}

// THE NEAREST ACTIVATABLE ANCESTOR IN THE FLATTENED TREE, and the tree is the
// whole point (re-attack 3, R6). This used to be `el.closest(KS_ACTIVATABLE)`,
// and `closest()` walks the LIGHT tree: a light-DOM `<span>` slotted into a
// shadow-root submit button climbs `span -> pay-box -> body` and finds no
// activatable ancestor at all, so a click on it submitted a card-carrying
// shadow form with no class computed and no gate. The element the browser
// activates is the shadow `<button>`, because the browser runs the INNERMOST
// activatable element's behaviour in the FLATTENED tree -- which is the
// principle stated at the top of this file, and which `closest()` does not
// implement. Slotting a light child into a shadow control is what every
// component library does; it is furniture, not an attack.
//
// `ksUp` is `visibility.js`'s flattened-tree parent, spliced in alongside
// this block, so the slot hop and the host hop are the same ones every other
// subsystem in the build has used since the shadow rebuild.
function ksActivatableAncestor(el) {
  for (var n = ksUp(el), guard = 0; n && guard++ < 64; n = ksUp(n)) {
    if (n.nodeType !== 1) continue;
    try { if (n.matches && n.matches(KS_ACTIVATABLE)) return n; }
    catch (e) { return null; }   // a selector engine that dislikes the list
  }
  return null;
}

// The element the browser activates when this one is clicked.
function ksActivationTarget(el) {
  if (!el || el.nodeType !== 1) return el;
  var tag = el.tagName;
  // The overwhelmingly common case, answered without a climb: a control that
  // is itself activatable IS the activation target, because the browser runs
  // the innermost one's behaviour.
  if (KS_SELF_ACTIVATING[tag]) return el;
  if (tag === 'A' && el.hasAttribute && el.hasAttribute('href')) return el;
  if (tag !== 'LABEL' && el.getAttribute) {
    var role = (el.getAttribute('role') || '').trim().toLowerCase();
    if (KS_ACTIVATION_ROLES[role]) return el;
  }
  var n = ksActivatableAncestor(el) || el;
  if (n && n.tagName === 'LABEL') {
    // `control` is null on a label that labels nothing, in which case the
    // label is the end of the line and activates only itself.
    var c = null;
    try { c = n.control; } catch (e) { c = null; }
    if (c) n = c;
  }
  return n || el;
}

// The submission-relevant facts of the activation target, or `null` where the
// browser activates the touched element itself and the descriptor already
// says everything there is to say. Returned as FACTS, not as a verdict: the
// classifier that reads them is the same one that reads the touched
// element's, so a delegated click cannot reach a gate the direct click would
// not have reached, and cannot skip one either.
function ksDelegatedActivation(el) {
  var target = ksActivationTarget(el);
  if (!target || target === el) return null;
  var form = ksFormOf(target);
  return {
    tag: target.tagName,
    type: ksSubmitTypeOf(target, !!form),
    in_form: !!form,
    form_payment: ksFormPayment(form),
    // The DELEGATE'S form census (consent ladder, 2026-09-07), for the same
    // reason its payment facts are here: a `<label>` parked outside the
    // `<form>` tag still submits the form its control belongs to, so the
    // classifier has to read that form and not the touched element's.
    // Guarded because `consent.js` is spliced into the ACTING scripts only:
    // the extractor splices this block too and has no census to compute.
    form_census: (typeof ksFormCensus === 'function'
      ? ksFormCensus(form) : null),
    payment: ksPaymentField(target),
    name: (target.getAttribute && (target.getAttribute('aria-label')
      || target.getAttribute('name'))) || target.id || ''
  };
}
// KS4Web ARIA state: THE ONE STATE SOURCE for every read that prints an
// affordance.
//
// The field asked a question neither incumbent answers: "which tab is
// active?" The projection carried a partial answer (expanded, selected when
// true, current with its value thrown away) and `find_elements` carried
// almost none (three native DOM properties and nothing declared), so the same
// element described itself two ways depending on which tool found it. That is
// the divergence `visibility.js`, `payment.js`, and `activation.js` were each
// written to end, one classification along.
//
// Two rules the vocabulary follows, and the difference between them is not
// cosmetic:
//
// - A NATIVE property is printed BARE: `disabled`, `checked`, `required`,
//   `readonly`. The browser itself enforces these, so their presence is the
//   whole fact and a `=true` would be noise on every one of them.
// - A DECLARED (aria-) state is printed WITH ITS VALUE: `expanded=false`,
//   `selected=true`, `pressed=mixed`, `current=page`. The value is the
//   answer, and `aria-selected="false"` is a statement the page made, which
//   is a different fact from an element that never spoke. Dropping the false
//   half is what made "which tab is active" unanswerable: with only the true
//   half printed, silence meant either "not selected" or "not a tab", and the
//   caller could not tell which.
//
// COST. The aria half runs one pass over `el.attributes` rather than eight
// `getAttribute` calls, so an element with no aria-* attribute pays for the
// attributes it does have and nothing more. A page of plain links and inputs
// is charged the loop and no branch inside it.
function ksAriaState(el) {
  const native = [];
  if (el.disabled) native.push('disabled');
  if (el.checked) native.push('checked');
  if (el.required) native.push('required');
  if (el.readOnly) native.push('readonly');

  const attrs = el.attributes;
  if (!attrs || !attrs.length) return native;

  // Collected by key first, then emitted in a FIXED order below, so the
  // state string is a property of the element rather than of the order the
  // author happened to type the attributes in. A test that pins
  // `[expanded=false,selected=true]` must not fail because a page shipped
  // the attributes the other way round.
  const declared = {};
  for (let i = 0; i < attrs.length; i++) {
    const name = attrs[i].name;
    if (name.lastIndexOf('aria-', 0) !== 0) continue;
    const raw = attrs[i].value;
    if (typeof raw !== 'string') continue;
    const value = raw.trim().toLowerCase();
    if (!value) continue;
    switch (name) {
      case 'aria-expanded':
        if (value === 'true' || value === 'false') declared.expanded = value;
        break;
      case 'aria-selected':
        if (value === 'true' || value === 'false') declared.selected = value;
        break;
      case 'aria-pressed':
        if (value === 'true' || value === 'false' || value === 'mixed')
          declared.pressed = value;
        break;
      case 'aria-checked':
        // A native `checked` property already answered this for an INPUT.
        // Only a role-built checkbox, radio, switch, or menuitemcheckbox
        // needs the declared value, and printing both would be one fact
        // twice under two spellings.
        if (!('checked' in el)
            && (value === 'true' || value === 'false' || value === 'mixed'))
          declared.checked = value;
        break;
      case 'aria-disabled':
        // Deliberately NOT folded into the bare `disabled`. The browser does
        // not block a click on an aria-disabled div, so an actor that treats
        // the two as identical is wrong about what happens next. Same fact,
        // different enforcement, different spelling.
        if (value === 'true' && !el.disabled) declared.disabled = value;
        break;
      case 'aria-readonly':
        if (value === 'true' && !el.readOnly) declared.readonly = value;
        break;
      case 'aria-required':
        if (value === 'true' && !el.required) declared.required = value;
        break;
      case 'aria-current':
        // The VALUE is the point: `page`, `step`, `date`, `location`, and
        // `true` are five different claims about which item you are on, and
        // the old code printed the bare word `current` for all of them.
        if (value !== 'false') declared.current = value;
        break;
      case 'aria-invalid':
        if (value !== 'false') declared.invalid = value;
        break;
      case 'aria-busy':
        if (value === 'true') declared.busy = value;
        break;
      default:
        break;
    }
  }

  const ORDER = ['expanded', 'selected', 'checked', 'pressed', 'current',
                 'disabled', 'readonly', 'required', 'invalid', 'busy'];
  const out = native.slice();
  for (let i = 0; i < ORDER.length; i++) {
    const key = ORDER[i];
    if (declared[key] !== undefined) out.push(key + '=' + declared[key]);
  }
  return out;
}
// THE ONE FORM-CENSUS SOURCE (consent ladder, 2026-09-07). Spliced into the
// acting scripts at load time (`projection/__init__.py`), so there is exactly
// one in-page answer to "what kind of form is this".
//
// It exists because the gate table could not tell a search from a bank
// transfer: `form_submit` covered both, so unlocking write mode bought the
// tools and bought nothing at all in the approval budget. The consent ladder
// needs facts the descriptor never carried -- the form's effective METHOD
// above all, because RFC 9110 section 9.2.1 defines GET as a SAFE method and
// that is the load-bearing signal that lets a search box submit silently for
// a stated reason rather than for convenience.
//
// THIS FILE COMPUTES FACTS AND MAKES NO DECISION. The vocabularies that say
// what a submitter's name MEANS live once, in `policy/submissions.py`, and
// this block hands them squashed haystacks to read. That is the opposite of
// the payment split (where the decision is in-page and the Python list is the
// mirror) and it is deliberate: a decision needs one home, and for these four
// classes the home with the multilingual vocabulary is the better one.
//
// FORM MEMBERSHIP FOLLOWS `form.elements`, NEVER `querySelectorAll`. A field
// carrying `form="pay"` submits with that form from anywhere in the document,
// and reading only descendants was a one-attribute bypass the payment work
// already found and fixed. `ksFormOf` (payment.js) is the association-aware
// lookup and this block uses it rather than a second climb.

//: The autocomplete tokens that mark a field secret. The exact mirror of
//: `policy/credentials.SECRET_AUTOCOMPLETE`; a divergence would let a field
//: be secret at the choke point and invisible in the census.
var KS_SECRET_AC = ['current-password', 'new-password', 'one-time-code'];

//: Field name / autocomplete tokens that mark a form as addressed AT someone.
//: HTML tokens, not natural language, so they belong in-page: a `to`, `cc`,
//: `bcc`, or `recipient` field is a recipient field in every language.
var KS_RECIPIENT_NAMES = ['to', 'cc', 'bcc', 'recipient', 'recipients',
  'sendto', 'send_to', 'mailto', 'addressee'];

function ksIsSecretField(el) {
  if (!el || !el.getAttribute) return false;
  var type = (el.type || '').toLowerCase();
  if (type === 'password') return true;
  var ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  for (var i = 0; i < KS_SECRET_AC.length; i++) {
    if (ac.indexOf(KS_SECRET_AC[i]) >= 0) return true;
  }
  return false;
}

// The squash `policy/submissions.squash` mirrors: camelCase splits first,
// Latin diacritics fold, every other script survives intact, separators
// collapse to one space, and the result is padded so a whole-word test is a
// substring test. The combining range is payment.js's, for payment.js's
// reason: stripping every combining mark also takes U+3099 and turns
// カード into a word that matches nothing.
function ksSquashConsent(raw) {
  var s = String(raw || '').slice(0, 400);
  s = s.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
  try {
    s = s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').normalize('NFC');
  } catch (e) { /* an engine without normalize keeps the raw string */ }
  return ' ' + s.replace(/[^\p{L}\p{N}]+/gu, ' ').trim() + ' ';
}

function ksAccessibleish(el) {
  if (!el || !el.getAttribute) return '';
  var bits = [el.getAttribute('aria-label'), el.value, el.textContent,
    el.getAttribute('name'), el.getAttribute('title'), el.id];
  var out = [];
  for (var i = 0; i < bits.length; i++) {
    if (bits[i]) out.push(String(bits[i]).slice(0, 120));
  }
  return out.join(' ');
}

function ksLabelTextOf(el) {
  var bits = [el.getAttribute && el.getAttribute('aria-label'),
    el.getAttribute && el.getAttribute('name'), el.id];
  try {
    var labels = el.labels;
    if (labels) {
      for (var i = 0; i < labels.length && i < 3; i++) {
        bits.push(labels[i].textContent);
      }
    }
  } catch (e) { /* a control without a labels collection */ }
  return bits.filter(Boolean).join(' ');
}

// THE FORM'S DEFAULT SUBMITTER: what an implicit submission (Enter in a
// single-line field, or `fill_form(submit=True)`) actually presses. Without
// it a batch submit reaches the classifier with no name at all, which is the
// half a per-click classifier cannot see.
function ksDefaultSubmitter(els) {
  for (var i = 0; i < els.length && i < 500; i++) {
    var el = els[i];
    if (!el || !el.tagName) continue;
    var t = ksSubmitTypeOf(el, true);
    if (t === 'submit' || t === 'image') return el;
  }
  return null;
}

var ksCensusCache = new Map();

function ksFormCensus(formEl) {
  if (!formEl) return null;
  var cached = ksCensusCache.get(formEl);
  if (cached !== undefined) return cached;
  var out = {
    method: 'GET', secret: false, payment: false, has_file: false,
    enctype: '', field_count: 0, textarea: false, recipient: false,
    submitter: null, action: '', checkbox_labels: ''
  };
  try {
    out.method = String(formEl.getAttribute('method') || 'get').toUpperCase();
    if (out.method !== 'POST' && out.method !== 'GET'
        && out.method !== 'DIALOG') {
      // An unrecognized method attribute means GET per the HTML spec's
      // invalid-value default. Naming it here rather than trusting the
      // string keeps a `method="delete"` typo from reading as a POST.
      out.method = 'GET';
    }
    out.enctype = String(formEl.getAttribute('enctype') || '').toLowerCase();
    out.action = String(formEl.getAttribute('action') || '');
    out.payment = ksFormPayment(formEl);
    var els = formEl.elements || [];
    var labels = [];
    for (var i = 0; i < els.length && i < 500; i++) {
      var el = els[i];
      if (!el || !el.tagName) continue;
      var tag = el.tagName;
      var type = (el.type || '').toLowerCase();
      if (ksIsSecretField(el)) out.secret = true;
      if (tag === 'INPUT' && type === 'file') out.has_file = true;
      if (tag === 'TEXTAREA') out.textarea = true;
      if (tag === 'INPUT' && type === 'checkbox') {
        labels.push(ksLabelTextOf(el));
      }
      if (tag === 'TEXTAREA'
          || (tag === 'INPUT' && type !== 'hidden' && type !== 'submit'
              && type !== 'button' && type !== 'reset' && type !== 'image')
          || tag === 'SELECT') {
        out.field_count++;
      }
      var nm = String((el.getAttribute && el.getAttribute('name')) || '')
        .toLowerCase().replace(/[^a-z]/g, '');
      var ac = String((el.getAttribute && el.getAttribute('autocomplete'))
        || '').toLowerCase();
      if (KS_RECIPIENT_NAMES.indexOf(nm) >= 0) out.recipient = true;
      if (ac.indexOf('email') >= 0 && tag !== 'BUTTON') {
        // An email field is a recipient field only in a form that also
        // carries free text; on a sign-up form it is the human's own
        // address. The Python side applies that pairing rule; this only
        // records the fact.
        out.recipient_email = true;
      }
    }
    out.checkbox_labels = labels.join(' ').slice(0, 600);
    if (out.recipient_email && out.textarea) out.recipient = true;
    var submitter = ksDefaultSubmitter(els);
    if (submitter) out.submitter = ksAccessibleish(submitter).slice(0, 160);
  } catch (e) { /* a form the engine will not enumerate keeps the defaults */ }
  ksCensusCache.set(formEl, out);
  return out;
}

// THE PAGE'S OWN AGE DECLARATION, relayed and not judged. This server ships
// no topic classifier and will not: any list of "risky topics" imposes one
// person's values on every user and would gate a nuclear-weapons and DPRK
// research corpus on day one. What is honest to report is a claim the PAGE
// made about itself, in the metadata the labelling schemes define for exactly
// this purpose.
var KS_AGE_META = ['rating', 'RATING'];
var KS_AGE_VALUES = /\b(rta-5042|adult|mature|restricted|18\+|xxx)\b/i;

function ksAgeDeclared() {
  try {
    for (var i = 0; i < KS_AGE_META.length; i++) {
      var nodes = document.querySelectorAll(
        'meta[name="' + KS_AGE_META[i] + '"]');
      for (var j = 0; j < nodes.length; j++) {
        var content = nodes[j].getAttribute('content') || '';
        if (KS_AGE_VALUES.test(content)) return content.slice(0, 80);
      }
    }
    var link = document.querySelector('link[rel="meta"][href*="labels"]');
    if (link) return 'a content-label link';
  } catch (e) { /* a document that will not answer declares nothing */ }
  return null;
}
// THE ONE HREF SOURCE (union wave 2026-09-07, fuzzer class 10).
//
// An SVG `<a>` exposes `href` as an SVGAnimatedString, not a string. Every
// site in the build read `element.href` and stringified it, which on an SVG
// anchor produced `/[object%20SVGAnimatedString]`: a plausible-looking URL
// that was fabricated, returned as fact, with no flag on it. `get_links` was
// the site the fuzzer named; the class sweep found four more, all reading
// the same property the same way — `get_list`'s per-item link, the article
// extractor, the page projection, and the element search.
//
// The ATTRIBUTE is the page's own text on both element kinds, so resolving
// from it is correct for an HTML anchor too. `xlink:href` is the older SVG
// spelling and is still what a lot of generated SVG emits.
//
// A LOCAL const, spliced per script, not a window global: a page can
// reassign anything on `window`, and a page-writable object wearing this
// build's name is the exact defect the instrument closure exists to remove.
const ksHref = function (el) {
  if (!el || !el.getAttribute) return '';
  if (el.namespaceURI === 'http://www.w3.org/2000/svg') {
    return el.getAttribute('href') || el.getAttribute('xlink:href') || '';
  }
  return el.href || el.getAttribute('href') || '';
};
// THE ONE RENDERED-TEXT SOURCE. Spliced into `schema.js` and into the extract
// pack's field, table, and list readers at load time, so there is exactly one
// implementation of "what does this element actually say" in the build.
//
// IT REQUIRES `visibility.js` IN THE SAME SCOPE as of fix wave 9c, because
// `ksVisibleRenderedText` at the bottom of this file asks the shared hidden
// rule of every node it descends into. Every consumer splices both markers;
// a consumer that splices only this one gets a ReferenceError on the first
// value harvest rather than a quietly weaker check, which is the direction
// this build fails in on purpose.
//
// It exists because `textContent` is not what the element says. It is every
// character in the subtree, INCLUDING the ones no browser has ever painted:
// the rules inside a `<style>`, the source inside a `<script>`, and the markup
// inside a `<noscript>`. On the vast majority of pages that difference never
// shows, which is why it survived this long, and on one extremely common page
// shape it is a confident wrong value.
//
// The shape is a Wikipedia infobox. MediaWiki inlines a
// `<style data-mw-deduplicate="TemplateStyles:...">` element into the first
// cell that needs it, so the cell's `textContent` is three CSS rules followed
// by the value. The 2026-09-08 field test watched `extract_fields` answer the
// field `Official languages` with 100 percent stylesheet garbage: the right
// row matched, the key was correct, the provenance was correct, and the value
// was CSS. Nothing in the payload said anything was wrong with it.
//
// That is the exact defect class this product's doctrine exists to forbid, and
// it is not exotic markup: every large Wikipedia article carries it, and
// `<script type="application/json">` payloads sit inside cells on commerce and
// news pages for the same reason.
//
// THE SET IS DELIBERATELY THE UNAMBIGUOUS FOUR. `<style>`, `<script>`,
// `<noscript>`, and `<template>` are never painted by any browser under any
// stylesheet, so excluding them is a statement about HTML rather than a
// judgement about a page. `<title>` is NOT here on purpose: an SVG `<title>`
// is the accessible name of the graphic and the union wave deliberately put
// SVG text into the readable set. Anything hidden by CSS is a different
// question with a different answer, and `visibility.js` owns it.
var KS_UNRENDERED_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1 };

//: A depth bound, because this build has a renderer-crash history on
//: pathological nesting and a recursion that walks an arbitrary page is a
//: recursion the page chose the depth of.
var KS_TEXT_MAX_DEPTH = 60;

function ksRenderedText(el, depth) {
  if (!el) return '';
  if (el.nodeType === 3) return el.nodeValue || '';
  if (el.nodeType !== 1) return '';
  if (KS_UNRENDERED_TAGS[(el.tagName || '').toUpperCase()]) return '';
  var d = depth || 0;
  if (d > KS_TEXT_MAX_DEPTH) return el.textContent || '';
  var out = '';
  for (var n = el.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 3) out += n.nodeValue;
    else if (n.nodeType === 1) out += ksRenderedText(n, d + 1);
  }
  return out;
}

// ------------------------------------------- THE VALUE HALF OF THE QUESTION
//
// `ksRenderedText` answers "which characters in this subtree would a browser
// paint at all", and fix wave 9c is the round that found out that is the
// right question for a KEY and the wrong one for a VALUE.
//
// The repro is `corpus/g2/cloak_extract.html`. A `<b>Balance:</b>` label, and
// as the label block's next sibling a positioned wrapper holding the value
// paragraph with an opaque, same-size, higher-z-index box painted over it --
// the identical construction `get_text` had correctly stripped and counted as
// `paint-cloaked` since fix wave 9b. `extract_page` returned
// `CLOAKED-VALUE-99999-do-not-trust` as a `found`, `proximate`, `exact`,
// labeled fact with `hidden_values_excluded: 0`, in the same tool-call batch
// where `get_text` on the same page reported the same value withheld.
//
// The wiring was not missing. `schema.js` asked the shared rule, and asked it
// of the element the ladder MATCHED -- the wrapper, which is not hidden and
// is not cloaked, because the lid is INSIDE it. Then it read that element's
// aggregate rendered text, recursively, and the recursion asked nothing of
// anything. THE CHECKED UNIT AND THE RETURNED UNIT WERE DIFFERENT NODES, and
// every gap of that shape is a page-controlled channel: a page picks its own
// nesting, so it picks which node the check lands on.
//
// So the walk itself carries the rule. Every element it descends into is
// asked, the subtree of one that answers is skipped, and the answer is
// COUNTED into the caller's sink rather than dropped -- a value silently
// shortened is the same completeness lie as a value silently included.
//
// VALUES, NOT KEYS, and the line is drawn where the harm is. A value is a
// claim about what a human sees on the page, so hidden text may not become
// one. A LABEL is a lookup token: `class="sr-only"` labels are how the
// accessible web names its own fields, and running this rule over keys would
// blind every value harvest to every screen-reader-labelled control on the
// web. Keys keep `ksRenderedText`; values get this.
function ksVisibleRenderedText(el, sink, depth) {
  if (!el) return '';
  if (el.nodeType === 3) return el.nodeValue || '';
  if (el.nodeType !== 1) return '';
  if (KS_UNRENDERED_TAGS[(el.tagName || '').toUpperCase()]) return '';
  var d = depth || 0;
  if (d > KS_TEXT_MAX_DEPTH) return el.textContent || '';
  var out = '';
  for (var n = el.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 3) { out += n.nodeValue; continue; }
    if (n.nodeType !== 1) continue;
    var reason = ksHiddenAnywhere(n) || ksPaintCloaked(n);
    if (reason) {
      if (sink) {
        sink.excluded = (sink.excluded || 0) + 1;
        sink.chars = (sink.chars || 0) + (n.textContent || '').length;
        if (!sink.reasons) sink.reasons = {};
        sink.reasons[reason] = (sink.reasons[reason] || 0) + 1;
      }
      continue;
    }
    out += ksVisibleRenderedText(n, sink, d + 1);
  }
  return out;
}

// The same rule asked of the element ITSELF, for the callers whose harvest
// starts at a node they were handed rather than at one they descended into.
// Returns null when the element is hidden outright, which is a different
// answer from "it renders and holds nothing".
function ksVisibleTextOf(el, sink) {
  if (!el) return null;
  var reason = ksHiddenAnywhere(el) || ksPaintCloaked(el);
  if (reason) {
    if (sink) {
      sink.excluded = (sink.excluded || 0) + 1;
      sink.chars = (sink.chars || 0) + (el.textContent || '').length;
      if (!sink.reasons) sink.reasons = {};
      sink.reasons[reason] = (sink.reasons[reason] || 0) + 1;
    }
    return null;
  }
  return ksVisibleRenderedText(el, sink, 0);
}

// ---- the scripts ----
const KS4WEB_SCRIPTS = {
  extract: (
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
(opts) => {
  const KS = KS4WEB_STATE;
// (hoisted to bundle scope) @@KS4WEB_HREF@@
// (hoisted to bundle scope) @@KS4WEB_VISIBILITY@@
// (hoisted to bundle scope) @@KS4WEB_PAYMENT@@
// (hoisted to bundle scope) @@KS4WEB_ACTIVATION@@
// (hoisted to bundle scope) @@KS4WEB_ARIA@@
// (hoisted to bundle scope) @@KS4WEB_CONSENT@@
  opts = opts || {};
  // `location=` scoping. The read is the same read, run over a subtree: the
  // same blocks, the same ladder, the same completeness discipline, over a
  // smaller document. A scoped read that quietly became a different KIND of
  // read would make the advertised expand prices unverifiable, and DESIGN
  // 3.3a's contract is that every printed price is executable.
  let scopeRoot = null, scopeRef = null;
  if (opts.root) {
    scopeRoot = KS.refs.get(opts.root) || null;
    if (!scopeRoot) return { error: 'ROOT_GONE', asked_for: opts.root };
    scopeRef = opts.root;
  }
  // `opts.pin`: ONE element that is collected even past the affordance cap.
  //
  // The cap is right for a read and it broke the flagship pairing for an
  // ACT. `find_elements` searches every candidate on purpose, because the
  // link the design's own example names sits past the two thousandth on that
  // page; it minted a ref for a match at position 301, and the acting path
  // then resolved that ref against an extraction that stops at 300, so the
  // rebind ladder found no candidate and refused STALE. A search whose
  // results cannot be acted on is the operation DESIGN 3.5 says must not
  // exist, and it shipped that way until 2026-09-06.
  //
  // The pin widens the HAYSTACK and never picks the needle: the ladder still
  // matches by anchor key, still refuses ambiguity, and still refuses a
  // fingerprint that moved. An element pinned in but no longer matching its
  // stored anchor refuses exactly as it did before.
  const pinEl = opts.pin ? (KS.refs.get(opts.pin) || null) : null;

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

  // Styles, colours, the shadow-boundary hop, and the whole hidden-technique
  // set come from the ONE shared source spliced in above. This file held the
  // richest of the three copies and still missed four classes a page can use
  // today: near-zero opacity, a filter chain ending in transparency or a blur
  // past legibility, a transparent foreground (the old contrast check ignored
  // the alpha channel, so `color: transparent` scored as pure black), and
  // content that is not rendered at all -- `content-visibility: hidden`, a
  // collapsed `<details>`, an unslotted light child. Gauntlet 2's H2 walked
  // an agent onto five invisible buttons on one fixture using four of them.
  const cs = ksCS;
  const up = ksUp;
  const parseColor = ksParseColor;
  const lum = ksLum;
  // An IDREF (aria-labelledby, aria-describedby) resolves inside the tree
  // that holds it, so a shadow-borne label must be looked up in the shadow
  // root rather than in the document, where it is not.
  function byId(el, id) {
    const r = el.getRootNode ? el.getRootNode() : document;
    if (r && typeof r.getElementById === 'function') return r.getElementById(id);
    return document.getElementById(id);
  }

  // A form is payment-shaped when ANY field in it is, so every control in
  // that form -- its submit button included -- classifies as one action
  // class. The rule and its memo live in the ONE payment source spliced in
  // above; this used to be a fourth private copy of the same autocomplete
  // regex, and all four missed a page that simply declares no token (R3).
  const formPayment = ksFormPayment;

  const hiddenReason = ksHiddenReason;
  const geometryHidden = ksGeometryHidden;

  function hiddenBetween(el, stopAt) {
    // Hidden anywhere between an element and its region ancestor counts as
    // hidden, because that is how a display:none wrapper hides a heading that
    // is itself perfectly visible in its own computed style.
    return ksHiddenChain(el, stopAt) !== null;
  }

  function lowContrast(el, style) {
    return ksInvisibleColor(el, style || cs(el)) !== null;
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
        const target = byId(el, id);
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
        // `<input type=image>` NAMES ITSELF FROM alt (HTML-AAM), and it had
        // no rung here at all, so the one submit control this build calls
        // out by name (the 2026-09-06 R1 incident) read as unnamed: an
        // unnamed control anchors turn-local, so a ref minted for it did
        // not survive its own re-resolution. The image submitter is now
        // addressable by the word the page put on it.
        if (!raw && tag === 'INPUT' && type === 'image') {
          const alt = squash(el.getAttribute('alt') || '');
          if (alt) { raw = alt; how = 'alt'; }
        }
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

  const NAV_ROLE = /^(navigation|tablist|menubar|menu)$/;
  const climbCache = new Map();

  //: 'prose' | {li: element} | null, for the chain above a starting parent.
  function climbFrom(start) {
    if (!start) return null;
    const hit = climbCache.get(start);
    if (hit !== undefined) return hit;
    let out = null;
    let p = start, hops = 0;
    while (p && hops++ < 8) {
      const r = (p.getAttribute('role') || '').trim().split(/\s+/)[0];
      if (p.tagName === 'NAV' || NAV_ROLE.test(r)) break;
      if (p.tagName === 'LI') { out = { li: p }; break; }
      if (PROSE_ANCESTOR.has(p.tagName)) { out = 'prose'; break; }
      p = up(p);
    }
    climbCache.set(start, out);
    return out;
  }

  const TEXT_BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT', 'FIGCAPTION']);
  //: What `get_text` emits as one line, which is what the rate sample has to
  //: reproduce: a navbox of 150 one-word links costs a line boundary per
  //: link, and a sample that glues those links into sentences measures a
  //: page that does not exist.
  const LINE_BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT',
    'FIGCAPTION', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TD', 'TH']);
  const PROSE_ANCESTOR = new Set(['P', 'LI', 'BLOCKQUOTE', 'DD', 'FIGCAPTION']);

  // ------------------------------------------------- the anchor descriptor
  //
  // DESIGN 3.5's durable half, produced by the SAME walk that produces the
  // projection rather than by a second evaluate. The descriptor is role,
  // accessible name, a scoping path (nearest landmark, then nearest labelled
  // ancestor, then ordinal among same-role siblings), stable attributes where
  // the page offers them, and the page key it was minted on.
  //
  // The landmark here is computed by climbing ancestors rather than read off
  // the projection's region stack, and that is deliberate: the region list is
  // CAPPED (forty regions, three deep) because it is a menu a human reads,
  // and an anchor scoped by a capped structure would silently lose its
  // scoping on exactly the pages that need it most.
  const LM_ANCHOR_TAG = {
    HEADER: 'banner', NAV: 'navigation', MAIN: 'main', ASIDE: 'complementary',
    FOOTER: 'contentinfo', FORM: 'form', SECTION: 'region', DIALOG: 'dialog'
  };
  const LM_ANCHOR_ROLE = new Set(['banner', 'navigation', 'main',
    'complementary', 'contentinfo', 'form', 'region', 'search', 'dialog',
    'alertdialog', 'tablist']);

  // Both of these walk ancestors, and on a deep page every affordance walks
  // most of the same chain again. Memoizing per ancestor turns the pair from
  // O(affordances x depth) into O(distinct ancestors), which is what keeps
  // the anchor descriptor inside the latency budget: unmemoized it cost 505
  // ms p95 at 50,000 nodes against a 500 ms bound, for work that is the same
  // answer every time.
  const lmCache = new Map();
  function landmarkFrom(n) {
    if (!n) return { node: document.body, kind: 'document', label: '' };
    const hit = lmCache.get(n);
    if (hit !== undefined) return hit;
    const explicit = (n.getAttribute('role') || '').trim().split(/\s+/)[0];
    const kind = (explicit && LM_ANCHOR_ROLE.has(explicit)) ? explicit
      : LM_ANCHOR_TAG[n.tagName];
    let out = null;
    if (kind) {
      const label = squash(n.getAttribute('aria-label'))
        || squash(n.getAttribute('name'))
        || (n.getAttribute('aria-labelledby')
            ? squash((byId(n,
                n.getAttribute('aria-labelledby').split(/\s+/)[0])
                || {}).textContent)
            : '');
      // An unlabelled <section> is not a landmark under HTML-AAM, and
      // treating it as one scopes anchors to a container the page does not
      // consider structural.
      if (!(n.tagName === 'SECTION' && !label)) {
        out = { node: n, kind: kind, label: label };
      }
    }
    if (out === null) out = landmarkFrom(up(n));
    lmCache.set(n, out);
    return out;
  }

  function landmarkOf(el) {
    return landmarkFrom(up(el));
  }

  const laCache = new Map();
  function labelledFrom(n) {
    if (!n) return null;
    const hit = laCache.get(n);
    if (hit !== undefined) return hit;
    let out = null;
    const al = squash(n.getAttribute('aria-label'));
    if (al) {
      out = { node: n, label: al };
    } else {
      const lb = n.getAttribute('aria-labelledby');
      if (lb) {
        const t = byId(n, lb.split(/\s+/)[0]);
        if (t && squash(t.textContent)) out = { node: n, label: squash(t.textContent) };
      }
    }
    if (out === null) out = labelledFrom(up(n));
    laCache.set(n, out);
    return out;
  }

  function labelledAncestorOf(el, stopAt) {
    const found = labelledFrom(up(el));
    // Memoization answers "nearest labelled ancestor anywhere above", so the
    // landmark boundary is applied here: a label found AT or ABOVE the
    // landmark is the landmark's own label, not a scoping refinement inside
    // it, and using it would collapse the two rungs into one.
    if (!found || found.node === stopAt || found.node.contains(stopAt)) {
      return '';
    }
    return found.label;
  }

  // The page key, on every anchor KEY and not merely in the descriptor. S2
  // found the distinction by producing the failure: a ref minted on one page
  // came back bound to a same-named control on another, seven per run, at the
  // STRONGEST tier of the ladder rather than in the fuzzy tail where anyone
  // would look for it. The hash is in because a hash route is a page by every
  // meaning that matters to a ref.
  const PAGE_KEY = location.origin + location.pathname + location.hash;
  const anchorOrdinals = {};

  function anchorOf(el, role, name) {
    const lm = landmarkOf(el);
    const scope = lm.kind + ':' + lm.label + '|' + role;
    anchorOrdinals[scope] = (anchorOrdinals[scope] || 0) + 1;
    return {
      page_key: PAGE_KEY,
      role: role,
      name: name,
      landmark: lm.kind,
      landmark_label: lm.label,
      labelled_ancestor: labelledAncestorOf(el, lm.node),
      // Scopes a lookup and NEVER binds a ref. A virtualized list rewrites
      // its rendered window while keeping every ordinal, which put row 0's
      // ref onto row 3,998 and did the same for twenty-one of its
      // neighbours. Carried here for the candidate list an ambiguous refusal
      // prints, not for the key ladder.
      ordinal: anchorOrdinals[scope],
      attr_id: el.id || '',
      attr_testid: el.getAttribute('data-testid') || '',
      attr_name: el.getAttribute('name') || ''
    };
  }

  // Column headers come from THIS table's own header row, never from every
  // `th` in the subtree. The first version took `querySelectorAll('th')` and
  // sliced eight, which on a Wikipedia navbox returned the header cells of
  // tables nested inside it: the GDP page printed
  // `cols: show Lists of countries by... | Trade | Investment | Funds` for a
  // one-column layout table, which are not that table's column headers and
  // are not column headers at all. A wrong header list is the same disease as
  // a wrong accessible name, a confident answer to a question nobody asked.
  //
  // A single-column table has no column header list worth printing, so it
  // returns none rather than the one cell that happens to lead it.
  function columnHeaders(table, cols) {
    if (cols < 2) return [];
    const rows = table.rows || [];
    for (let i = 0; i < rows.length && i < 3; i++) {
      const cells = Array.from(rows[i].cells || []).filter(
        c => c.tagName === 'TH');
      if (cells.length >= 2) {
        return cells.slice(0, 8).map(
          x => clip(contentName(x, 0, new Set()), 28).text).filter(Boolean);
      }
    }
    return [];
  }

  // ----------------------------------------------------------- the walk

  const regions = [];
  const regionStack = [];
  const affordances = [];
  const headings = [];
  const forms = [];
  const tables = [];
  const canvases = [];
  // Images that are laid out, big enough to carry a sentence, and
  // contribute ZERO characters to the read. This is where a rendered error
  // notice, a screenshotted table, and a text-as-image banner live: the
  // extractor already counts images and reads `alt` where it exists, and
  // the case nobody counted is the one with no alt and no accessible name
  // at all. The floor is shared with the canvas geometry below so the two
  // thresholds cannot drift apart.
  const muteImages = [];
  // The floor targets an image that could carry a SENTENCE, which is the
  // case this counter exists for: a rendered error notice, a screenshotted
  // table, a text-as-image banner. A line of legible text needs width more
  // than height, so the test is 200 by 80 rather than a square: an 80x80
  // square is an icon, and counting every alt-less icon on a page would
  // cost the ledger a line of budget to report something nobody can act on.
  const IMG_TEXT_MIN_W = 200;
  const IMG_TEXT_MIN_H = 80;
  // Is anything actually drawn on this canvas? (fuzzer class 3.)
  //
  // Sampled rather than read whole: a full getImageData on a 4K canvas is
  // megabytes of pixels for a boolean. Sixteen points on a grid catches a
  // painted toolbar, a chart, or a line of text, and misses only a canvas
  // whose entire content is thinner than one sixteenth of it in both axes.
  // `null` where the answer cannot be had, never a guess: a tainted canvas
  // (a cross-origin image drawn into it) throws a SecurityError on read,
  // and "I could not look" is a different statement from "nothing is there".
  function canvasPainted(el) {
    try {
      const ctx = el.getContext && el.getContext('2d');
      if (!ctx) return null;              // WebGL, or no context at all
      const w = el.width, h = el.height;
      if (!w || !h) return false;
      const steps = 4;
      for (let i = 0; i < steps; i++) {
        for (let j = 0; j < steps; j++) {
          const x = Math.min(w - 1, Math.floor(w * (i + 0.5) / steps));
          const y = Math.min(h - 1, Math.floor(h * (j + 0.5) / steps));
          const sw = Math.max(1, Math.floor(w / steps));
          const sh = Math.max(1, Math.floor(h / steps));
          const data = ctx.getImageData(
            Math.max(0, x - (sw >> 1)), Math.max(0, y - (sh >> 1)),
            Math.min(sw, w), Math.min(sh, h)).data;
          for (let k = 3; k < data.length; k += 4) {
            if (data[k] !== 0) return true;
          }
        }
      }
      return false;
    } catch (e) {
      return null;
    }
  }
  // Is an opaque panel covering the whole viewport? (hostile H-09.)
  //
  // One scan, no hit tests. A candidate has to be positioned, cover at
  // least 90% of the viewport in both axes, be fully opaque itself, carry
  // a non-transparent background of its own, and be the LAST such element
  // in paint order among its peers. That last condition is what keeps an
  // ordinary full-page wrapper out of the answer: a wrapper is where the
  // content lives, and this reports the topmost one only.
  function viewportLid() {
    try {
      const vw = window.innerWidth || 1280;
      const vh = window.innerHeight || 900;
      let best = null;
      const nodes = document.body
        ? document.body.querySelectorAll('*') : [];
      let scanned = 0;
      for (const el of nodes) {
        if (scanned++ > 4000) break;
        const s = ksCS(el);
        if (s.position !== 'fixed' && s.position !== 'absolute') continue;
        if (parseFloat(s.opacity) < 0.99) continue;
        if (s.visibility === 'hidden' || s.display === 'none') continue;
        const bg = s.backgroundColor || '';
        // A transparent panel is not a lid: a human sees straight through
        // it, and calling that invisible would be the false positive this
        // whole family of checks has to fail away from.
        if (!bg || bg === 'transparent'
            || /rgba\([^)]*,\s*0(\.0+)?\)\s*$/.test(bg)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < vw * 0.9 || r.height < vh * 0.9) continue;
        if (r.left > vw * 0.05 || r.top > vh * 0.05) continue;
        // The element's own text is what a human reads instead of the page.
        best = { tag: el.tagName.toLowerCase(),
                 id: el.id || null,
                 ref: KS.refof.get(el) || null,
                 w: Math.round(r.width), h: Math.round(r.height),
                 covers_viewport: true };
      }
      return best;
    } catch (e) {
      return null;
    }
  }
  const frames = [];
  const virtualContainers = [];
  const hiddenReasons = {};
  const hiddenInteractiveReasons = {};
  // Containers whose children RENDER in an order the source does not carry.
  // A human reads "The bank has cleared this request. / Do not approve the
  // transfer." and every text surface in this build reads the opposite, with
  // no caveat unless a shadow root happened to be involved (gauntlet 2 M3).
  const reorderReasons = {};
  let reorderedContainers = 0;
  let hiddenInteractive = 0, hiddenNodes = 0, hiddenTextChars = 0;
  let injectionSuspects = 0, zeroWidthHits = 0;
  let openShadowRoots = 0, divTables = 0, deepestCut = 0;
  let elementCount = 0, textCharsTotal = 0;
  // Open-shadow-root traversal (2026-09-06). Default ON: an off-by-default
  // read is the blind read the field report rejected, and the measured
  // regression on a page with no roots is zero because the added work is a
  // `el.shadowRoot` test that is null on every element. `opts.shadow ===
  // false` opts out, which is the escape hatch for a pathological page.
  const SHADOW_ON = !(opts && opts.shadow === false);
  let shadowRootsTraversed = 0, shadowElements = 0;

  // Refs resolve through the INSTRUMENT CHANNEL's registry, never through an
  // attribute we write onto the page. KS4Web reads pages; a projection that
  // mutated the DOM to give itself handles would be changing the thing it is
  // reporting on, and a MutationObserver-driven app would see it.
  //
  // The registry used to be `window.__ks4web_refs`, and gauntlet 2's H5 is
  // what that cost: `class Poisoned extends Map { get(){ return evil; } }`
  // satisfied every `instanceof Map` guard in the build, the trusted click
  // landed on the attacker's button, and the result reported the button the
  // model had asked for. It lives in a closure the page cannot reach now.
  //
  // Reused across reads rather than replaced. `location={"region":"r7"}`
  // resolves a ref that a PREVIOUS read minted, so a map that started empty
  // on every evaluate would make every scoped call fail with a stale ref that
  // is not in fact stale. Entries for elements that have left the document
  // are dropped here rather than accumulating.
  const refMap = KS.refs;
  for (const [k, v] of Array.from(refMap.entries())) {
    if (!v || !v.isConnected) refMap.delete(k);
  }
  const refOf = KS.refof;
  // In-page ids are minted MONOTONICALLY across the whole page lifetime (the
  // counters live in the channel, not in this closure), and an element that
  // already holds an id of the right kind keeps it. Both halves close the
  // same defect, found by the 2026-09-05 field misdirect investigation:
  // a per-read counter restarting at zero re-assigned existing keys to
  // whatever the CURRENT document order put at that position, so any stale
  // key held by a caller (a scoped read's root, a leaked node id) silently
  // meant a different element after a re-render. A monotonic key can only
  // ever mean one element or nothing.
  const mintRef = (prefix, el) => {
    const prior = refOf.get(el);
    if (prior && prior.charAt(0) === prefix && refMap.get(prior) === el) {
      return prior;
    }
    const ref = mintId(prefix);
    refMap.set(ref, el);
    refOf.set(el, ref);
    return ref;
  };
  // An id with no map registration, for units counted past their cap: the
  // id keeps the payload's cross-references unique without pretending an
  // unreturned unit is resolvable.
  KS.counters = KS.counters || Object.create(null);
  const mintId = (prefix) => {
    return prefix + (KS.counters[prefix] = (KS.counters[prefix] || 0) + 1);
  };
  let affordancesUncollected = 0;
  let currentHeading = null;
  const roleOrdinals = {};
  const classTotals = {};
  //: How many `nav`-classified controls each region holds, counted over
  //: EVERY one rather than the returned sample, so the demotion below is
  //: made on the page's number.
  const navByRegion = {};

  function bump(field, n) {
    const reg = regionStack.length ? regionStack[regionStack.length - 1] : null;
    if (reg) reg.net[field] += n;
  }

  // ------------------------------------------- tokenization rate samples
  //
  // A price is a TOKEN count, the tokenizer lives in Python, and characters
  // do not convert to tokens at one rate. On the frozen GDP article the
  // prose runs 5.3 characters to the token and the article's own data table
  // runs 1.8, so a table priced at the page's rate was under-priced by very
  // nearly three times: the number was arithmetic about a different kind of
  // content. Rather than hand a table a table-shaped constant, the walk
  // sends back a bounded sample of each unit's OWN text and the meter
  // measures the rate on it with the same tokenizer that enforces the
  // budget, which is DESIGN 3.3a's "one arithmetic" rule applied to the
  // conversion as well as to the counting.
  //
  // The sample is DECIMATED as it fills rather than truncated, so it stays
  // spread across everything the unit holds: a region whose first screen is
  // prose and whose body is a numeric table must not be described by its
  // opening paragraph. Everything here is bounded twice, per unit and per
  // read, because a page carrying 595 tables would otherwise ship a sample
  // larger than the payload.
  //: Per unit, and measured in CHARACTERS rather than in pieces: a table
  //: whose cells read "Ghana" and "1,234" fills twenty pieces with 140
  //: characters, and a rate measured on 140 characters of a 6,500-character
  //: table is a rate about its first column.
  const SAMPLE_UNIT_CHARS = 1500;
  //: Long enough that a run of prose tokenizes like prose. Fifty-character
  //: pieces measured 2.9 characters to the token on text that really runs
  //: 4.8, because every piece pays the boundary twice, and the regions the
  //: over-short sample described were then over-priced by half. Two hundred
  //: was measured against the same corpus at 2.5 percent median error.
  const SAMPLE_SNIPPET_CHARS = 200;
  //: Per read, over every unit, bounding two things at once: what crosses
  //: the boundary, and how much text the meter tokenizes on the far side.
  const SAMPLE_TOTAL_CHARS = 40000;
  let sampledChars = 0;

  //: Which line the walk is currently inside. Text carried by two different
  //: blocks is two lines when it is read back, and one run when it is not.
  let blockSeq = 0;

  function newSampler() {
    return { parts: [], buf: '', chars: 0, seen: 0, stride: 1, line: -1 };
  }

  // Text arrives one text NODE at a time, and a text node is not a run of
  // prose: a Wikipedia paragraph broken by six inline links arrives as seven
  // fragments of twenty characters. Measuring a rate on fragments measures
  // the fragmentation, because every piece pays a boundary at each end, and
  // it over-priced the flagship article's prose regions by a quarter. So the
  // fragments are re-joined into runs first, and it is whole RUNS that are
  // kept or skipped.
  function sampleInto(s, text) {
    if (!s || !text || sampledChars >= SAMPLE_TOTAL_CHARS) return;
    const join = s.line === blockSeq ? ' ' : '\n';
    s.line = blockSeq;
    s.buf = s.buf ? s.buf + join + text : text;
    if (s.buf.length < SAMPLE_SNIPPET_CHARS) return;
    const snippet = s.buf.slice(0, SAMPLE_SNIPPET_CHARS);
    s.buf = '';
    if (s.seen++ % s.stride) return;
    s.parts.push(snippet);
    s.chars += snippet.length;
    sampledChars += snippet.length;
    while (s.chars > SAMPLE_UNIT_CHARS && s.parts.length > 3) {
      const kept = [];
      let chars = 0;
      for (let i = 0; i < s.parts.length; i += 2) {
        kept.push(s.parts[i]);
        chars += s.parts[i].length;
      }
      sampledChars -= (s.chars - chars);
      s.parts = kept;
      s.chars = chars;
      s.stride *= 2;
    }
  }

  // A unit smaller than one run is described by what it has: the leftover
  // buffer is the whole of a short region's text rather than a remainder.
  function sampleOf(s) {
    if (!s) return null;
    if (s.parts.length) return s.parts.join('\n');
    return s.buf || null;
  }

  // The same sample, taken from a string rather than accumulated over a
  // walk: a table's text is read once, as one piece.
  function sampleString(text) {
    if (!text || sampledChars >= SAMPLE_TOTAL_CHARS) return null;
    if (text.length <= SAMPLE_UNIT_CHARS) {
      sampledChars += text.length;
      return text;
    }
    const pieces = Math.ceil(SAMPLE_UNIT_CHARS / SAMPLE_SNIPPET_CHARS);
    const step = Math.floor(text.length / pieces);
    const parts = [];
    for (let i = 0; i < pieces; i++) {
      parts.push(text.substr(i * step, SAMPLE_SNIPPET_CHARS));
    }
    const out = parts.join('\n');
    sampledChars += out.length;
    return out;
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

  // Counting a shadow root is NOT the same job as walking into it, and
  // conflating them was a real defect: `openShadowRoots++` used to ride
  // inside the body of `walk()`, which returns early on a hidden subtree, so
  // a host under a `display:none` ancestor was never counted. The injection
  // fixture reported 5 open roots on a page with 7. The count now happens
  // before any early return, and a subtree the walk SKIPS still has its roots
  // tallied here, because "what I did not look at" is exactly the number the
  // completeness block exists to state.
  // Counts roots strictly BELOW `node`, in the light tree and through every
  // open root it finds. `node` itself is counted by the caller, before any
  // early return, so a host is never double counted.
  function countRootsUnder(node, kids) {
    for (const k of (kids || node.querySelectorAll('*'))) {
      if (k.shadowRoot) { openShadowRoots++; countRootsUnder(k.shadowRoot); }
    }
  }

  // Only asked when a `visibility: hidden` element is actually met, so the
  // page that never uses the override pays nothing for the question.
  function hasVisibleDescendant(el) {
    if (!el.querySelectorAll) return false;
    const kids = el.querySelectorAll('*');
    for (let i = 0; i < kids.length && i < 500; i++) {
      if (cs(kids[i]).visibility === 'visible') return true;
    }
    return false;
  }

  function walk(el, depth) {
    elementCount++;
    if (el.shadowRoot) openShadowRoots++;
    if (depth > 400) {                          // pathological nesting, reported
      // No root sweep here, deliberately. The cut can fire once per sibling
      // and a sweep per cut is the O(n^2) shape the hidden branch below
      // warns about, on the exact pages that shape hurts most. Roots below
      // 400 levels of nesting go uncounted; the cut itself is reported, so
      // the read still says a subtree was skipped.
      deepestCut++;
      return;
    }
    const style = cs(el);
    let hr = hiddenReason(el, style);
    if (hr === 'visibility-hidden' && hasVisibleDescendant(el)) {
      // `visibility` INHERITS and a descendant can turn it back on, which a
      // human then reads and every surface in this build used to miss
      // (gauntlet 2 L2). The subtree accounting below assumes a hidden branch
      // is hidden all the way down, so where a descendant overrides, the walk
      // continues and each node answers for itself. The element's own text is
      // still withheld and still counted.
      const own = squash(el.textContent || '');
      hiddenNodes += 1;
      hiddenReasons[hr] = (hiddenReasons[hr] || 0) + 1;
      if (own.length > 20) injectionSuspects++;
      hr = null;
    }
    if (hr) {
      // The whole subtree is accounted for HERE and the walk stops, which is
      // what keeps the normalizer linear: counting a hidden subtree at every
      // level of itself is the O(n^2) version of the same answer.
      const kids = el.querySelectorAll('*');
      const n = 1 + kids.length;
      countRootsUnder(el, kids);
      if (el.shadowRoot) countRootsUnder(el.shadowRoot);
      hiddenNodes += n;
      hiddenReasons[hr] = (hiddenReasons[hr] || 0) + n;
      const nInteractive = el.querySelectorAll(INTERACTIVE_SEL).length
        + (isInteractive(el) ? 1 : 0);
      hiddenInteractive += nInteractive;
      // THE TECHNIQUE, named beside the count. "4 nodes (1 interactive)" told
      // a caller how much was withheld and nothing about how it was hidden,
      // and the four cloaked buttons gauntlet 2 walked an agent onto were the
      // ones that never reached this branch at all. Now they do, and the
      // ledger says which disguise each one wore.
      if (nInteractive) {
        hiddenInteractiveReasons[hr] =
          (hiddenInteractiveReasons[hr] || 0) + nInteractive;
      }
      const txt = squash(el.textContent || '');
      hiddenTextChars += txt.length;
      if (txt.length > 20) injectionSuspects++;
      return;
    }

    // RENDERED ORDER versus SOURCE ORDER, measured where it is decided. Four
    // techniques reverse a page for a human without touching the DOM order
    // every text surface in this build reports: `flex-direction: *-reverse`,
    // the `order` property, explicit grid placement, and a component that
    // reorders its slots. The read cannot cheaply reorder itself, so it says
    // so instead: an unstated inversion is a page telling the agent the
    // opposite of what it tells the user.
    const disp = style.display;
    if (disp === 'flex' || disp === 'inline-flex'
        || disp === 'grid' || disp === 'inline-grid') {
      // MEASURED, not inferred. Asking "does this container use a technique
      // that CAN reorder" flags every named-area grid on the web, most of
      // which place their children in source order anyway. Asking "do the
      // boxes come out in a different sequence than the source" is the
      // question the caveat actually answers, and it covers all four
      // techniques with one test.
      // Only children that are IN FLOW and carry text. An absolutely
      // positioned child sits wherever its coordinates put it and was never
      // in the reading sequence (a visually-hidden radio behind a styled
      // label puts one in front of its own label on every design system on
      // the web), and a container of icons has no reading order to invert.
      const kids = [];
      let textual = 0;
      for (let c = el.firstElementChild; c && kids.length < 40;
           c = c.nextElementSibling) {
        const ccs = cs(c);
        if (ccs.position === 'absolute' || ccs.position === 'fixed') continue;
        const r = c.getBoundingClientRect();
        if (!(r.width || r.height)) continue;
        if (squash(c.textContent || '')) textual++;
        kids.push({ i: kids.length, t: r.top, b: r.bottom, l: r.left });
      }
      if (kids.length > 1 && textual > 1) {
        // READING ORDER, not raw top-then-left. A row of boxes with different
        // heights has different tops, and sorting on top alone would call
        // every `align-items: flex-end` row on the web reordered. Boxes whose
        // vertical extents overlap are one line and are read across it.
        const rtl = style.direction === 'rtl';
        const byLine = kids.slice().sort((a, b) => (a.t - b.t) || (a.l - b.l));
        const lines = [];
        for (const k of byLine) {
          const line = lines.length ? lines[lines.length - 1] : null;
          if (line && k.t < line.b - 1) {
            line.items.push(k);
            if (k.b > line.b) line.b = k.b;
          } else {
            lines.push({ b: k.b, items: [k] });
          }
        }
        const flat = [];
        for (const line of lines) {
          line.items.sort((a, b) => rtl ? (b.l - a.l) : (a.l - b.l));
          for (const k of line.items) flat.push(k.i);
        }
        let inverted = false;
        for (let i = 0; i < flat.length; i++) {
          if (flat[i] !== i) { inverted = true; break; }
        }
        if (inverted) {
          const why = /-reverse$/.test(style.flexDirection || '')
            ? 'flex-reverse'
            : (disp.indexOf('grid') >= 0 ? 'grid-placement' : 'order-property');
          reorderedContainers++;
          reorderReasons[why] = (reorderReasons[why] || 0) + 1;
        }
      }
    }

    let pushed = false;
    const kind = regionCandidate(el);
    if (kind && !hr && regions.length < MAX_REGIONS && regionStack.length < MAX_REGION_DEPTH) {
      const geo = geometryHidden(el, style);
      if (!geo.reason && (geo.rect.height >= 24 || geo.rect.width >= 24)) {
        const ref = mintRef('r', el);
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
        const finalLabel = label || '(' + el.tagName.toLowerCase() + ')';
        const rec = {
          ref: ref, kind: kind, label: finalLabel,
          anchor: anchorOf(el, kind, finalLabel),
          name_quality: named.quality,
          tag: el.tagName.toLowerCase(),
          depth: regionStack.length,
          parent: regionStack.length ? regionStack[regionStack.length - 1].ref : null,
          // `prose_links` is a SUBSET of `interactive`, tracked separately
          // because the class carries a quota of zero and a region ranker
          // that counts it ranks a footnote block above the page's own data
          // table. It is not subtracted from `interactive`, because the
          // region's real interactive count is a completeness fact.
          net: { interactive: 0, text_blocks: 0, images: 0, chars: 0,
                 words: 0, headings: 0, prose_links: 0 },
          sampler: newSampler(),
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
    // Entering a block opens a new line, for the rate sample's purposes.
    // Everything below it belongs to that line until the next block opens.
    if (LINE_BLOCK.has(tag)) blockSeq++;

    // direct text, attributed to the innermost region and the current section
    let direct = 0, directWords = 0, directText = '';
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const s = node.nodeValue || '';
        if (ZERO_WIDTH.test(s)) { zeroWidthHits++; }
        const t = squash(s);
        direct += t.length;
        if (t) {
          directWords += t.split(' ').length;
          directText = directText ? directText + ' ' + t : t;
        }
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
        // AND PAINT ORDER, which is neither style nor geometry (fix wave
        // 9b). Text under an opaque out-of-flow box is invisible for the
        // same reason a control under one is unclickable, and this walk
        // counted the characters as content. Asked only where there is
        // enough text to hide, on the rule in `visibility.js`.
        if (!geoReason) geoReason = ksPaintCloaked(el);
      }
      if (geoReason) {
        hiddenNodes++;
        hiddenReasons[geoReason] = (hiddenReasons[geoReason] || 0) + 1;
        hiddenTextChars += direct;
        if (direct > 20) injectionSuspects++;
      } else {
        textCharsTotal += direct;
        bump('chars', direct);
        // The same characters that are COUNTED are the ones sampled, so the
        // rate the meter measures is a rate about the text the price is
        // being charged for.
        const sampleReg = regionStack.length
          ? regionStack[regionStack.length - 1] : null;
        if (sampleReg) sampleInto(sampleReg.sampler, directText);
        if (currentHeading) sampleInto(currentHeading.sampler, directText);
        // Words as well as characters, because tokens track WORDS far more
        // closely than they track characters across content classes. A cell
        // of "1,234" and a clause of English prose have very different
        // characters per token and similar tokens per word, and a region
        // price built on characters alone under-priced a numeric table by a
        // factor of three while pricing the prose beside it correctly.
        bump('words', directWords);
        if (currentHeading) {
        currentHeading.section_chars += direct;
        currentHeading.section_words += directWords;
      }
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
          // CAP WHAT YOU RETURN, TALLY WHAT YOU COUNT (DESIGN 3.6a), applied
          // to the anchor descriptor as well as to the payload. Minting an
          // anchor for every heading on a 5,000-heading page costs two
          // ancestor walks apiece for 4,850 descriptors nothing will ever
          // return, and that alone was most of the Phase 2 latency
          // regression. The heading is still COUNTED, and its section extent
          // is still tracked, so no completeness figure moves.
          const keep = headings.length < MAX_HEADINGS;
          const rec = {
            ref: keep ? mintRef('h', el) : mintId('h'),
            level: +tag[1], text: named.name,
            anchor: keep ? anchorOf(el, 'heading', named.name) : null,
            name_quality: named.quality,
            region: region ? region.ref : null,
            section_chars: 0, section_words: 0, section_affordances: 0,
            section_known: true, sampler: newSampler()
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

      // THE CLOAK CHECK STOPS AT PROSE, AND THE LINE IS THE FINDING'S OWN
      // (fix wave 9b, and it was tried the other way first). The acting
      // path's refusal already discloses that "the read surfaces do not
      // compute per-element occlusion", which is TRUE of controls and was
      // the gap for TEXT -- the round put it exactly that way: the
      // disclosure "is scoped to interactive controls; it does not cover
      // prose/text nodes, and prose extraction is where this gap actually
      // lives". Dropping cloaked CONTROLS out of the affordance list broke
      // more than it fixed: the anchor ladder rebinds a ref by matching it
      // against the affordances of a fresh read, so a control the read
      // stopped listing became unresolvable, and `find_and_act` on
      // `ra/overlay.html` answered R4's own page with a StaleAnchor instead
      // of "an opaque panel is painted over it". The read reports the
      // cloaked TEXT; the acting path stays the authority on controls,
      // where it can run the pixel arbiter and the read cannot.
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
            const collect = affordances.length < MAX_AFFORDANCES
              || (pinEl !== null && el === pinEl);
            const named = collect ? accName(el, role)
              : { name: '', quality: 'not-collected' };
            const formEl = el.form || el.closest('form');
            // Submission semantics (C1, gauntlet 2026-09-06). The HTML spec
            // says a <button> with a missing or invalid type IS a submit
            // button; only 'button' and 'reset' opt out. This affordance's
            // `type` is what the ref path's action classifier reads, and
            // when it carried null for <button type=submit> the form_submit
            // confirmation gate never fired on the canonical read->ref->act
            // flow. An EXPLICIT type=submit keeps its declared semantics
            // anywhere, matching <input type=submit>; the default-submit
            // case applies only inside a form, where a click can actually
            // submit something.
            const type = ksSubmitTypeOf(el, !!formEl);
            const ac = ((el.getAttribute && el.getAttribute('autocomplete')) || '').toLowerCase();
            const secret = type === 'password' ||
              /current-password|new-password|one-time-code/.test(ac);
            const payment = ksPaymentField(el);
            const panGroup = ksPanGroup(el);
            // The same rule as the headings above: DISPLAY detail is computed
            // only for the elements that will be returned, while everything
            // CLASSIFICATION needs is computed for all of them so the
            // completeness tallies stay the page's numbers. `new URL()` on
            // every one of six thousand links, to produce a path string that
            // three hundred of them will print, is the expensive half of that
            // distinction.
            // THE SHARED STATE SOURCE (`aria.js`, spliced above). What lived
            // here read three DOM properties and three attributes, kept only
            // the true half of `aria-selected`, and threw away the VALUE of
            // `aria-current`, so "which tab is active" and "which nav item am
            // I on" were both unanswerable from a page read. `find.js` had a
            // thinner copy again. One implementation now answers both.
            const state = collect ? ksAriaState(el) : [];

            let href = null, path = null, external = false;
            if (tag === 'A') {
              // The raw attribute is cheap and the citation test below needs
              // it, so it is read for every link; the URL PARSE is not.
              href = el.getAttribute('href');
              if (collect) {
                try {
                  const u = new URL(ksHref(el), location.href);
                  external = u.origin !== location.origin;
                  path = external ? u.origin + u.pathname : (u.pathname + u.search + u.hash);
                } catch (e) { path = href; }
              }
            }

            // Quota class. Order matters: a link inside prose is a prose link
            // even when it also sits under a nav-shaped ancestor, and a form
            // control is a form control wherever it lives.
            // **A list item is not prose.** The first version treated any
            // LI ancestor as evidence of prose, and navigation menus are
            // `<ul><li><a>` by universal convention, so the zero quota
            // suppressed every real navigation bar on the web. On the frozen
            // GitHub repo page that removed all six repository tabs,
            // including Issues, which is S1's original failure returning
            // through a different door: buried by a quota this time instead
            // of by a proximity score.
            //
            // So an LI is prose only when the link sits INSIDE A SENTENCE,
            // measured as the item carrying substantially more text than the
            // link itself. `<li><a>Code</a></li>` is a menu item;
            // `<li>See also the <a>Fourteen Points</a> for context</li>` is
            // prose. And the climb stops at a navigation ancestor, so a menu
            // nested somewhere under an article never inherits prose from a
            // paragraph far above it.
            // Only LINKS can be in-prose, so the ancestor climb is gated on
            // the role rather than run for every button and input, and the
            // link's own text is measured only if an LI is actually reached.
            // Both were unconditional in the first version and the pair cost
            // roughly 45 percent of extract time on a link-heavy page, for
            // an answer most elements never use.
            let inProse = false;
            if (role === 'link') {
              // Memoized on the STARTING PARENT, which is exact: the climb
              // is deterministic in the parent and the hop budget, and both
              // are the same for every link. On a link-heavy page the links
              // share ancestors, so this turns 8 getAttribute calls per link
              // into 8 per distinct container.
              const found = climbFrom(up(el));
              if (found === 'prose') {
                inProse = true;
              } else if (found && found.li) {
                // The one part that cannot be memoized, because it is a
                // property of the LINK rather than of the chain: a list item
                // is prose only when the link sits inside a sentence.
                const own = squash(el.textContent || '').length;
                if (squash(found.li.textContent || '').length > own + 40) {
                  inProse = true;
                }
              }
            }
            // A CITATION MARKER is a reference, not an affordance, and it is
            // recognizable by its own shape rather than by its ancestor. The
            // ancestor test alone misses every marker that sits in an
            // infobox cell or a caption instead of a paragraph, which is how
            // `[ 1 ]`, `[ 2 ]`, `[ n. 1 ]` came back among the top
            // affordances on the flagship article after the prose rule was
            // otherwise correct. A whole name that is a short bracketed
            // token, pointing at a fragment of the SAME page, is a footnote
            // by construction.
            // Read from the element rather than from the computed name, so
            // the class is the same whether or not this one was collected.
            // A tally that changed at the 300th element would make the
            // completeness figures a property of the cap.
            const citation = role === 'link'
              && (href || '').charAt(0) === '#'
              && el.textContent.length < 24
              && /^\[\s*[^\]]{0,12}\s*\]$/.test(squash(el.textContent));
            let cls;
            if (role === 'link' && (inProse || citation)) cls = 'prose_link';
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
            if (cls === 'prose_link') bump('prose_links', 1);
            if (cls === 'nav') {
              const rk = region ? region.ref : '(unowned)';
              navByRegion[rk] = (navByRegion[rk] || 0) + 1;
            }
            if (collect) {
              roleOrdinals[role] = (roleOrdinals[role] || 0) + 1;
              const ref = mintRef('e', el);
              affordances.push({
                ref: ref, anchor: anchorOf(el, role, named.name),
                role: role, name: named.name,
                name_quality: named.quality,
                cls: cls, region: region ? region.ref : null,
                region_label: region ? region.label : null,
                ordinal: roleOrdinals[role],
                state: state.join(','), secret: secret, payment: payment,
                tag: tag,
                placeholder: (el.getAttribute('placeholder') || ''),
                editable: !!el.isContentEditable,
                pan_shape: ksPanShape('value' in el ? el.value : ''),
                pan_group_size: panGroup ? panGroup.size : null,
                pan_group_digits: panGroup ? panGroup.digits : null,
                pan_group_first: panGroup ? panGroup.first : null,
                pan_group_min: panGroup ? panGroup.min : null,
                pan_group_region: panGroup ? panGroup.region : null,
                // Which element a click on this one ACTIVATES (re-attack 2,
                // C1): a <label> forwards to its control, and a node with no
                // activation behaviour delegates to the nearest ancestor that
                // has one.
                activates: ksDelegatedActivation(el),
                href: href, path: path, external: external, type: type,
                in_viewport: geo.rect.top < window.innerHeight
                  && geo.rect.bottom > 0 && geo.rect.left < window.innerWidth,
                top: Math.round(geo.rect.top + window.scrollY),
                area: Math.round(geo.rect.width * geo.rect.height),
                form: formEl ? true : false,
                form_payment: formPayment(formEl),
                // THE FORM CENSUS (consent ladder, 2026-09-07). Carried on
                // the affordance so the LADDER-resolved path classifies the
                // same way the live-resolved path does: a rebind must not
                // quietly demote a "Delete account" button to the
                // undifferentiated class by losing the facts that named it.
                // Memoized per form, so a checkout page with one form and
                // thirty controls pays for the walk once.
                form_census: ksFormCensus(formEl),
                heading: currentHeading ? currentHeading.ref : null
              });
            } else {
              affordancesUncollected++;
            }
          }
        }
      }

      if (tag === 'FORM') {
        const fref = mintRef('f', el);
        forms.push({ el: el, ref: fref, region: region ? region.ref : null });
      } else if (tag === 'TABLE') {
        const rows = el.rows ? el.rows.length : 0;
        if (rows) {
          const named = accName(el, 'table');
          const cols = el.rows[0] ? el.rows[0].cells.length : 0;
          const tableText = squash(el.textContent || '');
          const tref = mintRef('t', el);
          tables.push({
            ref: tref, caption: named.name,
            anchor: anchorOf(el, 'table', named.name),
            name_quality: named.quality,
            rows: rows, cols: cols,
            headers: columnHeaders(el, cols),
            region: region ? region.ref : null,
            chars: tableText.length,
            sample: sampleString(tableText),
            spans: el.querySelectorAll('[rowspan],[colspan]').length
          });
        }
      } else if (tag === 'CANVAS') {
        // THE LEDGER WAS INVERTED BY AN AREA HEURISTIC (fuzzer class 3).
        // The old test was "bigger than 80x80", which is a guess about
        // whether a canvas matters and answers the wrong question in both
        // directions: a 200x60 canvas with `fillText('SMALLCANVASTEXT')`
        // painted on it reported "canvas-rendered regions: none", and a
        // 900x600 canvas that was completely blank reported one region of
        // unread content. `UNSUPPORTED_CONTENT`'s hint promises "the
        // completeness block of the last read counts it", and on the small
        // one it counted zero.
        //
        // Every canvas that is LAID OUT is counted now, whatever its size,
        // because size is not evidence about content and the ledger's job
        // is to say what was not read. `painted` is the cheap, honest
        // signal the payload can carry beside it: a canvas whose backing
        // store is entirely transparent has nothing on it, and one that is
        // too large to sample says so rather than guessing.
        const geo = geometryHidden(el, style);
        if (!geo.reason && geo.rect.width >= 1 && geo.rect.height >= 1) {
          canvases.push({
            region: region ? region.ref : null,
            w: Math.round(geo.rect.width), h: Math.round(geo.rect.height),
            painted: canvasPainted(el)
          });
        }
      } else if (tag === 'IMG') {
        const geo2 = geometryHidden(el, style);
        if (!geo2.reason && geo2.rect.width >= IMG_TEXT_MIN_W
            && geo2.rect.height >= IMG_TEXT_MIN_H) {
          const alt = (el.getAttribute('alt') || '').trim();
          const aria = (el.getAttribute('aria-label') || '').trim();
          const titleAttr = (el.getAttribute('title') || '').trim();
          const labelledby = (el.getAttribute('aria-labelledby') || '').trim();
          if (!alt && !aria && !titleAttr && !labelledby) {
            muteImages.push({
              region: region ? region.ref : null,
              w: Math.round(geo2.rect.width),
              h: Math.round(geo2.rect.height),
              decorative: el.getAttribute('alt') === ''
                || el.getAttribute('role') === 'presentation'
                || el.getAttribute('role') === 'none'
            });
          }
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

      // Virtualization detection, and the geometric test is the one that
      // catches the real thing. The attribute and class-name tests find a
      // library that announces itself; react-window does not, and it is the
      // library the fixture uses because it is the library people use. A
      // windowed list is a SCROLLABLE BOX WHOSE SCROLL EXTENT IS FAR LARGER
      // THAN WHAT IT HOLDS, which is exactly the shape a projection would
      // otherwise report as a complete twenty-row list.
      const setsize = el.getAttribute('aria-setsize') || el.getAttribute('aria-rowcount');
      const clsName = typeof el.className === 'string' ? el.className : '';
      let windowed = null;
      if (!setsize && !/virtual|infinite|windowed/i.test(clsName)) {
        const ov = style.overflowY;
        if ((ov === 'auto' || ov === 'scroll') && el.clientHeight > 40
            && el.scrollHeight > el.clientHeight * 3) {
          windowed = { extent: el.scrollHeight, visible: el.clientHeight };
        }
      }
      if (setsize || windowed || /virtual|infinite|windowed/i.test(clsName)) {
        // The rendered rows are the leaf-ish children of the scrolling box,
        // one level deeper when the library wraps them in a sizing element,
        // which is what react-window does.
        let host = el;
        if (el.children.length === 1 && el.children[0].children.length > 2) {
          host = el.children[0];
        }
        const kids = host.children.length;
        if (kids > 2 || setsize) {
          virtualContainers.push({
            region: region ? region.ref : null, dom_count: kids,
            claimed: setsize ? parseInt(setsize, 10) : null,
            how: setsize ? 'aria-setsize'
              : (windowed ? 'scroll extent ' + windowed.extent + 'px in a '
                 + windowed.visible + 'px box' : 'class name'),
            hint: clip(clsName, 30).text
          });
        }
      }
      const r2 = el.getAttribute('role');
      if (r2 && /^(table|grid|treegrid)$/.test(r2.trim())) divTables++;
    }

    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child, depth + 1);
    }
    // OPEN-SHADOW-ROOT DESCENT, and the placement is the whole design.
    //
    // It sits INSIDE the host's own walk, after `hiddenReason()` has already
    // returned for the host. A hidden host therefore never gets here: its
    // shadow payload is accounted in the hidden ledger and cannot enter the
    // projection. Sitting here also means the depth cut, the region stack,
    // the ref minting, and the budget accounting all apply to shadow content
    // unchanged, rather than being re-derived by a second pass.
    //
    // `<slot>` assigned nodes are NOT followed: an assigned node is still a
    // light child of the host and the loop above already has it, so following
    // the slot would count it twice. The price is ORDER, since a shadow tree
    // can render its slotted children in any sequence and this walk reports
    // source order. That caveat is stated in the completeness block rather
    // than left silent. A slot's own FALLBACK children are walked, and are
    // not double counted because they only render when nothing is assigned.
    if (SHADOW_ON && el.shadowRoot) {
      shadowRootsTraversed++;
      shadowElements += el.shadowRoot.querySelectorAll('*').length;
      for (let child = el.shadowRoot.firstElementChild; child;
           child = child.nextElementSibling) {
        walk(child, depth + 1);
      }
    } else if (el.shadowRoot) {
      countRootsUnder(el.shadowRoot);   // opted out: still counted, not read
    }
    if (pushed) regionStack.pop();
  }

  const walkRoot = scopeRoot || document.body;
  if (walkRoot) walk(walkRoot, 0);

  // The navigation class carries a GUARANTEED FLOOR, filled before any other
  // class, and DESIGN 3.3 justifies that with "this is what an agent asks for
  // most and it is small." The second half is a premise, so it is checked
  // rather than assumed: a Wikipedia navbox is a nav-shaped landmark holding
  // 155 links, and a guaranteed floor sized for a tab bar becomes a flood
  // when a related-links block claims it. That is the same failure as the
  // form-control quota before it was scoped to controls inside a form.
  //
  // A navigation region larger than this is a link collection, not the page's
  // navigation, and its members compete in `other` on their merits.
  const NAV_BAR_MAX = 30;
  const floodedRegions = new Set(
    Object.keys(navByRegion).filter(k => navByRegion[k] > NAV_BAR_MAX));
  if (floodedRegions.size) {
    for (const key of floodedRegions) {
      const n = navByRegion[key];
      classTotals['nav'] = (classTotals['nav'] || 0) - n;
      classTotals['other'] = (classTotals['other'] || 0) + n;
    }
    for (const aff of affordances) {
      if (aff.cls === 'nav'
          && floodedRegions.has(aff.region || '(unowned)')) {
        aff.cls = 'other';
      }
    }
  }
  for (const h of headings) delete h.parentHeading;

  // A heading with no attributed text has no determinable section, so the
  // projection prints NO price for it rather than a number derived from a
  // walk that found nothing (DESIGN 3.3a rule 1).
  for (const h of headings) h.section_known = h.section_chars > 0;

  // The samplers are working state; what crosses the boundary is one string
  // per unit, which is what the meter measures its rate on.
  for (const r of regions) { r.sample = sampleOf(r.sampler); delete r.sampler; }
  for (const h of headings) {
    h.section_sample = sampleOf(h.sampler);
    delete h.sampler;
  }

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
        payment: ksPaymentField(field),
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
      anchor: anchorOf(el, 'form', named.name || el.getAttribute('name') || el.id || ''),
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
  const paras = Array.from(walkRoot.querySelectorAll('p,article>div>p'))
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
  const readableHost = scopeRoot
    || document.querySelector('main,[role=main],article');
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
      // The anchor key's page scope, computed once and carried, so the
      // Python side never rebuilds it from a URL string and never disagrees
      // with what the descriptors were minted under.
      page_key: PAGE_KEY,
      // Dies with the document and survives pushState, which is the line
      // between "the app routed" and "the browser navigated". S2 measured
      // document identity as the alternative cross-page test and it is worse
      // in both directions, so this is REPORTED and not used as the test.
      doc_epoch: (KS.doc = KS.doc
                  || String(Date.now()) + ':' + Math.random()),
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
      ref: r.ref, kind: r.kind, label: r.label, anchor: r.anchor,
      name_quality: r.name_quality,
      tag: r.tag, depth: r.depth, parent: r.parent, children: r.children,
      net: r.net, top: r.top, in_viewport: r.in_viewport,
      nav_shaped: r.nav_shaped,
      // The bounded text sample the meter measures this region's own
      // characters-per-token rate on. It is never printed.
      sample: r.sample
    })),
    affordances: affordances,
    // Totals over EVERY interactive element, including the ones past the
    // return cap, so "unlisted affordances: N" is the real number.
    affordance_class_totals: classTotals,
    //: Named so the completeness block could say it if the author wants it
    //: said, and so a test can assert the demotion happened rather than
    //: inferring it from a token count.
    nav_regions_demoted: Array.from(floodedRegions),
    affordance_total: affordances.length + affordancesUncollected,
    headings: headings.slice(0, MAX_HEADINGS),
    headings_total: headings.length,
    lead: leadEl || '',
    // Entry condition one of the rebind ladder: a pending modal blocks
    // interaction before any resolution is attempted at all, and it beats
    // every other entry condition including a ref that was never minted.
    modal: (() => {
      const d = document.querySelector(
        '[role="dialog"][aria-modal="true"], [role="alertdialog"], dialog[open]');
      if (!d) return null;
      return squash(d.getAttribute('aria-label'))
        || clip(contentName(d, 0, new Set()), 40).text || 'dialog';
    })(),
    forms: formOut,
    tables: tables,
    div_tables: divTables,
    completeness: {
      frames: frames,
      frames_same: frames.filter(f => f.same_origin).length,
      frames_cross: frames.filter(f => !f.same_origin).length,
      open_shadow_roots: openShadowRoots,
      shadow_roots_traversed: shadowRootsTraversed,
      shadow_traversal: SHADOW_ON,
      closed_shadow_roots: (KS.closed || 0),
      virtual: virtualContainers, canvases: canvases,
      mute_images: muteImages,
      // THE FULL-VIEWPORT LID (hostile H-09). Per-element occlusion stays
      // on the acting path for the cost reason `visibility.js` documents:
      // a page-wide scan plus nine hit tests per element, on every
      // extraction of a ten-thousand-node page. The one case that does NOT
      // need that is this one, because a panel covering the whole viewport
      // is a single page-level question asked once.
      //
      // It was worth asking. A `position:fixed; inset:0; opacity:1;
      // pointer-events:auto` panel raised over everything left the read
      // saying "unlisted affordances: none, every control is listed" with
      // the covered button listed above it, while `click` refused with "an
      // opaque panel is painted over it ... the read's completeness block
      // counts it as hidden interactive with the technique named". It did
      // not. A refusal advertising a cross-check the read demonstrably
      // fails to produce is the worst version of the defect: an agent told
      // to trust the completeness block is told so by a message the
      // completeness block contradicts.
      // AND WHICH LISTED CONTROLS THE CLICK PATH WOULD ACTUALLY REFUSE
      // (fix wave 9b, 2026-09-08). The lid line asserted that "a click on
      // any of them refuses", and on `corpus/ra/modal.html` -- an ordinary
      // modal, where the backdrop sits BELOW the panel by design -- the
      // click on the panel's own Confirm button succeeded, exactly as the
      // fixture intends. The read was making a confident claim about the
      // acting path that the acting path contradicted on the same page.
      //
      // So the split is MEASURED with the acting path's own rule
      // (`ksOccludedReason`, the at-or-above-half nine-point test in
      // `visibility.js`) rather than inferred from the lid's existence, and
      // it is measured only where a lid was found and only over the
      // affordances the read actually listed, so an ordinary page pays
      // nothing for it.
      viewport_lid: (function () {
        var lid = viewportLid();
        if (!lid) return null;
        var behind = 0, above = 0, aboveRefs = [];
        for (var i = 0; i < affordances.length; i++) {
          var el = KS.refs.get(affordances[i].ref);
          if (!el || !el.isConnected) continue;
          if (ksOccludedReason(el)) { behind++; continue; }
          above++;
          if (aboveRefs.length < 8) aboveRefs.push(affordances[i].ref);
        }
        lid.listed = affordances.length;
        lid.behind = behind;
        lid.above = above;
        lid.above_refs = aboveRefs;
        return lid;
      })(),
      hidden_interactive: hiddenInteractive, hidden_nodes: hiddenNodes,
      hidden_text_chars: hiddenTextChars, hidden_reasons: hiddenReasons,
      hidden_interactive_reasons: hiddenInteractiveReasons,
      reordered_containers: reorderedContainers,
      reorder_reasons: reorderReasons,
      injection_suspects: injectionSuspects, zero_width_hits: zeroWidthHits,
      name_fallbacks: nameFallbacks,
      scope: scopeRef,
      // Shadow content is part of the document the walk covered, so it is
      // part of the denominator too. Without this a traversing read reports
      // more elements walked than the page is said to have.
      total_elements: (scopeRoot
        ? scopeRoot.getElementsByTagName('*').length + 1
        : document.getElementsByTagName('*').length) + shadowElements,
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
  ),
  find: (
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
  const KS = KS4WEB_STATE;
// (hoisted to bundle scope) @@KS4WEB_HREF@@
// (hoisted to bundle scope) @@KS4WEB_VISIBILITY@@
// (hoisted to bundle scope) @@KS4WEB_ARIA@@
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
  ),
  text: (
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
  const KS = KS4WEB_STATE;
// (hoisted to bundle scope) @@KS4WEB_VISIBILITY@@
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
  ),
  article: (
// KS4Web article extraction: the body kept, the chrome COUNTED, the refusal
// honest.
//
// The research found both incumbents refusing this on the record, so it is
// differentiation territory rather than catch-up, and the reason they refuse
// is worth stating: article extraction is a HEURISTIC, and a heuristic that
// cannot say "this is not an article" produces confident nonsense on the
// nine tenths of the web that is an application. So this file ships two
// things and the second is the load-bearing one: a Readability-class scorer,
// and a shape verdict that refuses rather than mangling.
//
// Implemented in-house against the machinery that is already here. There is
// no new dependency: the hidden-content rule is the SAME spliced
// `visibility.js` every other read uses (a `display:none` injection inside
// an article body is counted and withheld here exactly as it is in
// `get_text`), the block walk is `text.js`'s, and the instrument channel is
// the one the projection mints refs into.
//
// FOUR PROPERTIES, and the third is the one the brief asked for by name:
//
// 1. **Reading order, not DOM soup.** One depth-first walk emits headings,
//    paragraphs, list items, quotes, and code in the order a human reads
//    them, with tables named as tables and pointed at `get_table` rather
//    than flattened into prose.
// 2. **Links resolved.** An in-prose link arrives as `[text](/path)` with the
//    href resolved against the document, same-origin paths shortened the way
//    `get_links` shortens them. When the link markup would cost more than a
//    quarter of the body, it is dropped WHOLESALE and the drop is stated;
//    a body that is 40 percent bracket syntax is not a readable article.
// 3. **Boilerplate is EXCLUDED AND COUNTED, never silently dropped.** Every
//    block outside the article body is classified (nav, header, footer,
//    sidebar, comments, related, share, promo, form, other) and returned as
//    a per-reason tally of blocks and characters. A caller can always see
//    what the tool decided not to show it, which is the difference between
//    an extractor and a summarizer.
// 4. **A shape verdict.** An application page comes back `shape: "none"`
//    with the evidence that decided it, and the Python side turns that into
//    a refusal naming `get_page_view`. A thread-shaped page (a forum topic,
//    an issue, a comment stream) comes back `shape: "thread"` with its posts
//    and their authors and timestamps, because that shape rides this same
//    walk for the cost of one extra pass.
(opts) => {
  const KS = KS4WEB_STATE;
// (hoisted to bundle scope) @@KS4WEB_HREF@@
// (hoisted to bundle scope) @@KS4WEB_VISIBILITY@@
  const startIndex = Math.max(0, opts.start_index || 0);
  const maxChars = Math.max(200, Math.min(200000, opts.max_chars || 20000));
  const LINK_MODE = opts.links === 'none' ? 'none' : 'inline';

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };

  // The ONE hidden-content rule, spliced above. Copies drift; there is one
  // copy, and it is the same one the page view and the prose read consult.
  function hiddenReason(el) {
    const r = ksHiddenReason(el, null);
    if (r) return r;
    if (el.tagName === 'BODY' || !el.getBoundingClientRect) return null;
    const g = ksGeometryHidden(el, null).reason;
    if (g) return g;
    // Paint-order cloaking, same rule and same source as the prose read
    // (fix wave 9b). An article body is the surface an injected instruction
    // most wants to ride out on, so the technique is excluded here and
    // counted in this read's own reason ledger like every other one.
    return ksPaintCloaked(el);
  }

  const BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT',
    'FIGCAPTION', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6']);
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG',
    'IFRAME', 'OBJECT', 'CANVAS']);
  const ZERO_WIDTH = /[​-‏‪-‮⁠-⁤﻿]/g;

  // Readability's class weights, transcribed rather than invented: two
  // decades of pages have been tuned against these exact words and a fresh
  // guess would be a worse answer with more confidence.
  const POSITIVE = /article|body|content|entry|hentry|h-entry|main|page|post|story|text|blog|column|prose|markdown/i;
  const NEGATIVE = /combx|comment|contact|foot|footer|footnote|masthead|media|meta|outbrain|promo|related|recirc|scroll|shoutbox|sidebar|sponsor|shopping|tags|tool|widget|nav|menu|banner|social|share|breadcrumb|pagination|newsletter|subscribe|modal|popup|cookie|disqus|byline|utility|skip|hidden/i;

  function idclass(el) {
    return ((el.className && typeof el.className === 'string' ? el.className : '')
      + ' ' + (el.id || ''));
  }

  // ------------------------------------------------------------ scoring

  function linkDensity(el) {
    const total = squash(el.textContent || '').length;
    if (!total) return 1;
    let linked = 0;
    const anchors = el.querySelectorAll ? el.querySelectorAll('a[href]') : [];
    for (let i = 0; i < anchors.length; i++) {
      linked += squash(anchors[i].textContent || '').length;
    }
    return Math.min(1, linked / total);
  }

  function classWeight(el) {
    let weight = 0;
    const bag = idclass(el);
    if (bag) {
      if (NEGATIVE.test(bag)) weight -= 25;
      if (POSITIVE.test(bag)) weight += 25;
    }
    const tag = el.tagName;
    if (tag === 'ARTICLE') weight += 30;
    else if (tag === 'MAIN') weight += 25;
    else if (tag === 'SECTION') weight += 8;
    else if (tag === 'DIV') weight += 5;
    else if (tag === 'ASIDE' || tag === 'NAV' || tag === 'FOOTER'
             || tag === 'HEADER' || tag === 'FORM') weight -= 30;
    const role = el.getAttribute ? (el.getAttribute('role') || '') : '';
    if (role === 'main' || role === 'article') weight += 25;
    if (role === 'navigation' || role === 'banner' || role === 'contentinfo'
        || role === 'complementary' || role === 'search') weight -= 30;
    const itemprop = el.getAttribute ? (el.getAttribute('itemprop') || '') : '';
    if (/articlebody|articleBody/i.test(itemprop)) weight += 40;
    return weight;
  }

  // The scored pass. Every paragraph-shaped block donates its own weight to
  // its ancestors, full to the parent and falling off by depth, which is
  // what makes a container that holds twenty paragraphs beat one that holds
  // the single longest.
  const scores = new Map();
  const paraChars = new Map();
  let bodyProseChars = 0, bodyProseBlocks = 0;

  function addScore(el, amount, chars) {
    if (!el || el.nodeType !== 1 || el.tagName === 'BODY'
        || el.tagName === 'HTML') return;
    if (!scores.has(el)) scores.set(el, classWeight(el));
    scores.set(el, scores.get(el) + amount);
    paraChars.set(el, (paraChars.get(el) || 0) + chars);
  }

  const paragraphs = document.querySelectorAll('p, pre, blockquote, dd');
  for (let i = 0; i < paragraphs.length; i++) {
    const p = paragraphs[i];
    const text = squash(p.textContent || '');
    if (text.length < 25) continue;
    if (hiddenReason(p)) continue;
    bodyProseChars += text.length;
    bodyProseBlocks++;
    const commas = (text.match(/[,、，]/g) || []).length;
    const base = 1 + commas + Math.min(Math.floor(text.length / 100), 3);
    let node = p.parentElement;
    for (let depth = 0; node && depth < 5; depth++) {
      addScore(node, base / (depth + 1), text.length);
      node = node.parentElement;
    }
  }

  let best = null, bestScore = 0;
  scores.forEach((score, el) => {
    const adjusted = score * (1 - linkDensity(el));
    if (adjusted > bestScore) { bestScore = adjusted; best = el; }
  });

  // Climb one or two levels when the parent is nearly as good and holds
  // meaningfully more prose. Readability's sibling-merge step solves the same
  // problem (a body split across two divs) and this is the cheap half of it:
  // it never widens the selection to a container that is mostly chrome,
  // because the parent's own adjusted score is what gates the move.
  if (best) {
    for (let hop = 0; hop < 2; hop++) {
      const parent = best.parentElement;
      if (!parent || parent.tagName === 'BODY' || parent.tagName === 'HTML') break;
      const parentScore = (scores.get(parent) || 0) * (1 - linkDensity(parent));
      const gained = (paraChars.get(parent) || 0) - (paraChars.get(best) || 0);
      if (parentScore >= bestScore * 0.9 && gained > (paraChars.get(best) || 0) * 0.15) {
        best = parent; bestScore = parentScore;
      } else break;
    }
  }

  // A caller-named root SKIPS the scorer entirely. "Read this region as an
  // article" is a different question from "find the article on this page",
  // and answering the first by running the second would quietly relocate the
  // read somewhere the caller did not point at.
  let root, rootWas = 'auto';
  if (opts.root) {
    root = KS.refs.get(opts.root) || null;
    if (!root) return {error: 'ROOT_GONE', asked_for: opts.root};
    rootWas = opts.root;
  } else {
    root = best || document.body || document.documentElement;
  }

  // ---------------------------------------------------------- the walk

  const blocks = [];
  const hiddenReasons = {};
  let hiddenBlocks = 0, hiddenChars = 0, injectionSuspects = 0;
  let zeroWidth = 0, shadowRootsRead = 0;
  let linksResolved = 0, linkMarkupChars = 0, tablesSeen = 0;

  function resolveHref(a) {
    try {
      const u = new URL(ksHref(a), location.href);
      return u.origin !== location.origin ? u.origin + u.pathname
        : (u.pathname + u.search + u.hash);
    } catch (e) { return a.getAttribute('href') || ''; }
  }

  // A block's own inline run, collected twice in ONE pass: `plain` is the
  // text, `rich` is the same text with in-prose links resolved. Both come
  // out of the same walk because the link-cost guard below has to compare
  // them, and walking twice to compare two walks is how they drift.
  function inlineText(el, plain, rich) {
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const v = node.nodeValue || '';
        plain.push(v); rich.push(v);
        continue;
      }
      if (node.nodeType !== 1) continue;
      if (SKIP.has(node.tagName) || BLOCK.has(node.tagName)) continue;
      if (hiddenReason(node)) continue;
      if (node.tagName === 'A' && node.hasAttribute('href')) {
        const inner = squash(node.textContent || '');
        const href = resolveHref(node);
        plain.push(' ' + inner + ' ');
        if (inner && href) {
          linksResolved++;
          const markup = '[' + inner + '](' + href + ')';
          linkMarkupChars += markup.length - inner.length;
          rich.push(' ' + markup + ' ');
        } else {
          rich.push(' ' + inner + ' ');
        }
        continue;
      }
      plain.push(' '); rich.push(' ');
      inlineText(node, plain, rich);
    }
  }

  function noteHidden(el, reason) {
    const text = squash(el.textContent || '');
    if (!text) return;
    hiddenBlocks++;
    hiddenChars += text.length;
    hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
    // The same rule `get_text` applies: a hidden block carrying real
    // sentences is the shape of a prompt injection. It is counted, named,
    // and never printed as article body.
    if (text.length > 20) injectionSuspects++;
  }

  // Ported from `text.js` rather than reinvented (gauntlet 2, L2): a
  // `visibility: hidden` block whose descendant sets `visibility: visible`
  // renders that descendant, and a walk that returns at the hidden ancestor
  // hands a page a reliable way to show a human something no tool reads. The
  // scan runs only when a visibility-hidden element is actually met.
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
      // Count this element's OWN inline run as withheld, then keep going: the
      // recursion re-asks the question of every child, so one that inherits
      // `hidden` is counted in its turn and one that overrides it is read.
      const ownPlain = [], ownRich = [];
      inlineText(el, ownPlain, ownRich);
      const own = squash(ownPlain.join(''));
      if (own) {
        hiddenBlocks++;
        hiddenChars += own.length;
        hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
        if (own.length > 20) injectionSuspects++;
      }
      for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
        walk(child);
      }
      return;
    }
    if (reason) { noteHidden(el, reason); return; }

    if (el.tagName === 'TABLE') {
      const rows = el.rows ? el.rows.length : 0;
      const cols = (el.rows && el.rows[0]) ? el.rows[0].cells.length : 0;
      tablesSeen++;
      blocks.push({
        tag: 'table', ref: KS.refof.get(el) || null,
        text: '[table: ' + rows + ' row(s) x ' + cols
              + ' column(s). get_table reads it as JSON]',
        rich: null});
      return;
    }

    if (BLOCK.has(el.tagName)) {
      const plainParts = [], richParts = [];
      inlineText(el, plainParts, richParts);
      let plain = plainParts.join('');
      let rich = richParts.join('');
      // `replace` rather than `test`, because `test` on a /g/ regex carries
      // `lastIndex` between calls and the second block on the page would be
      // asked the question starting halfway through itself.
      const stripped = plain.replace(ZERO_WIDTH, '');
      if (stripped.length !== plain.length) {
        zeroWidth++;
        plain = stripped;
        rich = rich.replace(ZERO_WIDTH, '');
      }
      const text = squash(plain);
      if (text) {
        blocks.push({tag: el.tagName.toLowerCase(),
                     ref: KS.refof.get(el) || null,
                     text: text, rich: squash(rich)});
      }
    }
    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child);
    }
    if (el.shadowRoot) {
      shadowRootsRead++;
      for (let child = el.shadowRoot.firstElementChild; child;
           child = child.nextElementSibling) {
        walk(child);
      }
    }
  })(root);

  // ------------------------------------------- boilerplate, excluded and COUNTED

  // Every prose block on the page that the article body did not claim, with
  // WHY it was not claimed. This is the accounting the brief asked for by
  // name: the exclusion is never silent, so a caller who thinks the tool cut
  // something can see the shape and the size of what it cut.
  const EXCLUSION_TESTS = [
    ['nav', 'nav, [role="navigation"], [role="menubar"], [role="tablist"]'],
    ['header', 'header, [role="banner"]'],
    ['footer', 'footer, [role="contentinfo"]'],
    ['sidebar', 'aside, [role="complementary"]'],
    ['form', 'form, [role="search"]'],
  ];
  const NAMED_PATTERNS = [
    ['comments', /comment|disqus|respond|discussion|replies/i],
    ['related', /related|recirc|recommend|more-from|read-next|readnext|trending|popular|also-like/i],
    ['share', /share|social|follow-us/i],
    // Ahead of nothing and behind `share` on purpose: a newsletter block is
    // a promotion, not a share widget, and putting `newsletter` in the share
    // pattern classified `promo-newsletter` as share on the first fixture
    // that carried one.
    ['promo', /promo|advert|\bads?\b|ad-|sponsor|paywall|upsell|banner|newsletter|subscribe/i],
  ];

  function exclusionReason(el) {
    for (let i = 0; i < EXCLUSION_TESTS.length; i++) {
      if (el.closest(EXCLUSION_TESTS[i][1])) return EXCLUSION_TESTS[i][0];
    }
    let node = el;
    for (let hop = 0; node && hop < 8; hop++) {
      const bag = idclass(node);
      if (bag) {
        for (let i = 0; i < NAMED_PATTERNS.length; i++) {
          if (NAMED_PATTERNS[i][1].test(bag)) return NAMED_PATTERNS[i][0];
        }
      }
      node = node.parentElement;
    }
    return 'other';
  }

  const excluded = {};
  let excludedBlocks = 0, excludedChars = 0;
  const pageBlocks = document.querySelectorAll(
    'p, li, blockquote, pre, dd, dt, figcaption, h1, h2, h3, h4, h5, h6');
  for (let i = 0; i < pageBlocks.length; i++) {
    const el = pageBlocks[i];
    if (root.contains(el)) continue;
    if (hiddenReason(el)) continue;           // already in the hidden ledger
    const text = squash(el.textContent || '');
    if (!text) continue;
    const reason = exclusionReason(el);
    if (!excluded[reason]) excluded[reason] = {blocks: 0, chars: 0};
    excluded[reason].blocks++;
    excluded[reason].chars += text.length;
    excludedBlocks++;
    excludedChars += text.length;
  }

  // --------------------------------------------------------- the metadata

  function metaContent(sel) {
    const el = document.querySelector(sel);
    if (!el) return null;
    const v = squash(el.getAttribute('content'));
    return v || null;
  }

  // JSON-LD, read only for the article types. A Website or Organization node
  // is not this page's byline and using it would be a confident wrong answer.
  const LD_TYPES = /^(Article|NewsArticle|BlogPosting|Report|ScholarlyArticle|TechArticle|LiveBlogPosting|DiscussionForumPosting|Posting|WebPage)$/i;
  let ld = null;
  const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (let i = 0; i < ldScripts.length && !ld; i++) {
    let parsed;
    try { parsed = JSON.parse(ldScripts[i].textContent); } catch (e) { continue; }
    const queue = Array.isArray(parsed) ? parsed.slice() : [parsed];
    while (queue.length && !ld) {
      const node = queue.shift();
      if (!node || typeof node !== 'object') continue;
      if (Array.isArray(node['@graph'])) {
        for (const sub of node['@graph']) queue.push(sub);
      }
      const types = [].concat(node['@type'] || []);
      for (const t of types) {
        if (typeof t === 'string' && LD_TYPES.test(t)) { ld = node; break; }
      }
    }
  }

  function ldPerson(value) {
    if (!value) return null;
    if (typeof value === 'string') return squash(value) || null;
    if (Array.isArray(value)) {
      const names = value.map(ldPerson).filter(Boolean);
      return names.length ? names.join(', ') : null;
    }
    if (typeof value === 'object' && value.name)
      return squash(String(value.name)) || null;
    return null;
  }

  // Each field states WHERE it came from. A byline that could be the page's
  // author or could be the site's owner is worth less than no byline, so the
  // source travels with the value and a field with no source is null rather
  // than a best guess.
  function pick(candidates) {
    for (let i = 0; i < candidates.length; i++) {
      const value = candidates[i][1];
      if (value) return {value: clip(String(value), 300), source: candidates[i][0]};
    }
    return {value: null, source: null};
  }

  const h1 = root.querySelector ? root.querySelector('h1') : null;
  const pageH1 = document.querySelector('h1');
  const title = pick([
    ['json-ld', ld ? (ld.headline || ld.name) : null],
    ['h1', h1 ? squash(h1.textContent) : null],
    ['og:title', metaContent('meta[property="og:title"]')],
    ['h1', pageH1 ? squash(pageH1.textContent) : null],
    ['document.title', squash(document.title)],
  ]);

  function domByline() {
    const sels = ['[itemprop="author"]', '[rel="author"]', 'a[rel~="author"]',
                  '.byline', '.author', '.post-author', '[class*="byline"]',
                  '[class*="author"]', '[data-testid*="author"]'];
    for (let i = 0; i < sels.length; i++) {
      let el = null;
      try { el = document.querySelector(sels[i]); } catch (e) { continue; }
      if (!el || hiddenReason(el)) continue;
      const text = squash(el.getAttribute('content') || el.textContent);
      // A byline is a name, not a paragraph. The length bound is what keeps
      // a `.author-bio` block from arriving as the byline.
      if (text && text.length <= 120) return text;
    }
    return null;
  }
  const byline = pick([
    ['json-ld', ld ? ldPerson(ld.author) : null],
    ['meta[name=author]', metaContent('meta[name="author"]')],
    ['markup', domByline()],
  ]);

  function timeEl(scope) {
    const el = scope.querySelector
      ? scope.querySelector('time[datetime], [itemprop="datePublished"][content], [datetime]')
      : null;
    if (!el) return null;
    return squash(el.getAttribute('datetime') || el.getAttribute('content')
                  || el.textContent) || null;
  }
  const published = pick([
    ['json-ld', ld ? (ld.datePublished || null) : null],
    ['meta[article:published_time]',
     metaContent('meta[property="article:published_time"]')],
    ['time[datetime]', timeEl(root)],
    ['meta[name=date]', metaContent('meta[name="date"]')],
    ['time[datetime]', timeEl(document)],
  ]);
  const modified = pick([
    ['json-ld', ld ? (ld.dateModified || null) : null],
    ['meta[article:modified_time]',
     metaContent('meta[property="article:modified_time"]')],
  ]);

  // ----------------------------------------------------- the shape verdict

  const articleChars = blocks.reduce((n, b) => n + b.text.length, 0);
  const proseBlocks = blocks.filter(
    (b) => b.tag === 'p' || b.tag === 'blockquote' || b.tag === 'pre').length;
  const rootDensity = linkDensity(root);
  // THE DENOMINATOR WAS THE DEFECT, NOT THE THRESHOLD (ledger A1, verify
  // round V-04). It used to be `articleChars + excludedChars`: the SELECTED
  // ROOT'S OWN NEIGHBOURHOOD, not the page. Two things follow from that
  // arithmetic and both of them are bad. Its floor is `articleChars`, so on
  // a page with no p/li/h* outside the root the share is exactly 1.00 by
  // construction however small the root is; and when the scorer picks a
  // lede <div> and books the real body as chrome, the ratio is
  // 1739/(1739+1333) = 0.57, a confident pass, while the true share against
  // what `get_text` returns is 1811/11651 = 0.16. The BBC field case cleared
  // the same guard at 18.7%. Raising the threshold could never have fixed
  // it: the number being compared did not mean what its name said.
  //
  // `innerText` and not `textContent`, which is the objection the old
  // comment here raised and it was right: textContent counts script bodies
  // and inline JSON as page text. innerText is the RENDERED text, so script
  // and style bodies and display:none subtrees are already out of it, which
  // is the same content `get_text` counts by walking visible block boxes.
  // One call, one layout flush, and a fallback to the old arithmetic if the
  // engine will not give it, because a missing denominator must not take the
  // read down.
  let pageChars = 0;
  try {
    pageChars = squash((document.body || document.documentElement).innerText
      || '').length;
  } catch (e) { pageChars = 0; }
  // The neighbourhood number is kept and reported beside it. It is what the
  // scorer's own exclusion ledger accounts for, so a caller comparing the
  // two can see the gap the ledger does not cover.
  const scoredChars = articleChars + excludedChars;
  if (pageChars < scoredChars) pageChars = scoredChars;

  // Four tests, each one a way a non-article fails. They are reported
  // individually rather than as a verdict, because "not article-shaped" with
  // no reason is the answer a caller cannot act on.
  const evidence = {
    prose_blocks: proseBlocks,
    article_chars: articleChars,
    link_density: Math.round(rootDensity * 100) / 100,
    share_of_page: pageChars ? Math.round((articleChars / pageChars) * 100) / 100 : 0,
    page_chars: pageChars,
    scored_chars: scoredChars,
    share_of_scored: scoredChars
      ? Math.round((articleChars / scoredChars) * 100) / 100 : 0,
  };
  const failed = [];
  if (proseBlocks < 3) failed.push('fewer than 3 paragraph-shaped blocks');
  if (articleChars < 400) failed.push('under 400 characters of body prose');
  if (rootDensity > 0.5) failed.push('over half the body text is link text');
  if (pageChars && articleChars / pageChars < 0.15)
    failed.push('the body holds under 15 percent of the page text');

  // ------------------------------------------------------ the thread shape

  // The research's issue/blog/forum ask. It rides this same walk: a thread is
  // repeated sibling containers each carrying a machine-readable timestamp,
  // which is the one structural signal every forum, issue tracker, and
  // comment stream actually ships. Nothing here guesses: no timestamps, no
  // thread, and the tool says so rather than inventing a post list.
  function detectThread() {
    const stamps = document.querySelectorAll('time[datetime], [datetime]');
    if (stamps.length < 3) return null;
    const groups = new Map();
    for (let i = 0; i < stamps.length; i++) {
      const stamp = stamps[i];
      if (hiddenReason(stamp)) continue;
      let node = stamp;
      for (let hop = 0; hop < 8 && node && node.parentElement; hop++) {
        const parent = node.parentElement;
        if (parent === document.body || parent.tagName === 'HTML') break;
        let siblingsWithStamps = 0;
        for (let c = parent.firstElementChild; c; c = c.nextElementSibling) {
          if (c.querySelector && (c.querySelector('time[datetime], [datetime]')
              || (c.matches && c.matches('time[datetime], [datetime]'))))
            siblingsWithStamps++;
        }
        if (siblingsWithStamps >= 3) {
          if (!groups.has(parent)) groups.set(parent, []);
          const seen = groups.get(parent);
          if (seen.indexOf(node) < 0) seen.push(node);
          break;
        }
        node = parent;
      }
    }
    let container = null, posts = null;
    groups.forEach((members, parent) => {
      if (!posts || members.length > posts.length) {
        container = parent; posts = members;
      }
    });
    if (!container || !posts || posts.length < 3) return null;

    const AUTHOR_SEL = '[itemprop="author"], [rel="author"], a[rel~="author"], '
      + '.author, .username, .user, [class*="author"], [class*="username"], '
      + '[data-testid*="author"], h3 a, h4 a';
    const out = [];
    let totalChars = 0;
    for (let i = 0; i < posts.length && i < 200; i++) {
      const post = posts[i];
      if (hiddenReason(post)) continue;
      const stamp = post.matches && post.matches('time[datetime], [datetime]')
        ? post : post.querySelector('time[datetime], [datetime]');
      let author = null;
      try {
        const a = post.querySelector(AUTHOR_SEL);
        if (a) {
          const text = squash(a.getAttribute('content') || a.textContent);
          if (text && text.length <= 120) author = text;
        }
      } catch (e) { /* selector unsupported here; author stays null */ }
      const body = squash(post.textContent || '');
      totalChars += body.length;
      out.push({
        index: i,
        ref: KS.refof.get(post) || null,
        author: author,
        timestamp: stamp ? squash(stamp.getAttribute('datetime')
                                  || stamp.getAttribute('content') || '') || null : null,
        timestamp_text: stamp ? clip(stamp.textContent, 60) || null : null,
        text: clip(body, 1200),
      });
    }
    if (out.length < 3 || totalChars < 200) return null;
    return {
      posts: out,
      total_posts: out.length,
      with_author: out.filter((p) => p.author).length,
      with_timestamp: out.filter((p) => p.timestamp).length,
      chars: totalChars,
    };
  }

  const thread = failed.length ? detectThread() : null;
  const shape = !failed.length ? 'article' : (thread ? 'thread' : 'none');

  // ----------------------------------------------------------- the payload

  // LINKS. The resolved form is the default and it is what makes the body
  // useful, but a body that is a quarter bracket syntax is not readable, so
  // the guard drops the markup WHOLESALE and says it did. Half-linked prose
  // would be the worst of both.
  const plainBody = blocks.map((b) => (/^h[1-6]$/.test(b.tag)
    ? '\n' + b.text + '\n' : b.text)).join('\n');
  let linksDropped = false;
  let body = plainBody;
  if (LINK_MODE === 'inline' && linksResolved) {
    if (plainBody.length && linkMarkupChars / plainBody.length > 0.25) {
      linksDropped = true;
    } else {
      body = blocks.map((b) => {
        const t = b.rich === null ? b.text : b.rich;
        return /^h[1-6]$/.test(b.tag) ? '\n' + t + '\n' : t;
      }).join('\n');
    }
  }

  const slice = body.slice(startIndex, startIndex + maxChars);
  const nextIndex = startIndex + slice.length;

  return {
    shape: shape,
    root: rootWas,
    url: location.href,
    lang: document.documentElement.getAttribute('lang') || null,
    site_name: metaContent('meta[property="og:site_name"]'),
    title: title, byline: byline, published: published, modified: modified,
    text: shape === 'none' ? '' : slice,
    start_index: startIndex,
    next_start_index: (shape !== 'none' && nextIndex < body.length)
      ? nextIndex : null,
    total_chars: body.length,
    returned_chars: shape === 'none' ? 0 : slice.length,
    blocks: blocks.length,
    tables: tablesSeen,
    thread: thread,
    links: {
      mode: LINK_MODE,
      resolved: linksResolved,
      dropped: linksDropped,
      markup_chars: linkMarkupChars,
    },
    excluded: {
      blocks: excludedBlocks, chars: excludedChars, by_reason: excluded,
    },
    hidden: {
      blocks: hiddenBlocks, chars: hiddenChars, reasons: hiddenReasons,
      injection_suspects: injectionSuspects, zero_width_blocks: zeroWidth,
    },
    shadow_roots_read: shadowRootsRead,
    closed_shadow_roots: (KS.closed || 0),
    evidence: evidence,
    failed_tests: failed,
  };
}
  ),
  schema: (
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
  const KS = KS4WEB_STATE;
// (hoisted to bundle scope) @@KS4WEB_VISIBILITY@@
// (hoisted to bundle scope) @@KS4WEB_RENDERED@@
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
                   hidden_values_excluded: 0, hidden_value_reasons: {},
                   secret_fields: 0, shadow_roots_read: 0 };
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
  // Paint order is part of that rule as of fix wave 9b: a value a human
  // cannot see because an opaque out-of-flow box is painted over it is not a
  // value this tool may report as read off the page.
  //
  // AND THE RULE FOLLOWS THE TEXT DOWN, as of fix wave 9c. Asking it of the
  // matched element alone checked one node and returned the aggregate text of
  // a whole subtree, so `corpus/g2/cloak_extract.html` -- a label whose value
  // sits in a positioned wrapper with the lid INSIDE that wrapper -- passed
  // the check at the wrapper and handed back the cloaked value underneath it,
  // at `found: true, confidence: proximate, match: exact`, with
  // `hidden_values_excluded: 0`. `ksVisibleRenderedText` carries the rule into
  // the walk, and the exclusions land in the same counter, because a value
  // silently shortened is the same completeness lie as a value silently
  // included.
  function hiddenHere(el) {
    return ksHiddenAnywhere(el) || ksPaintCloaked(el);
  }

  // `lastWithheld` is read by the caller IMMEDIATELY after the call, and it
  // is what lets the ladder answer "this field's value is hidden from a
  // human" rather than "this field is blank". Those are different facts about
  // a page and the second one, said of a cloaked value, is its own small
  // confident wrong answer: an unfilled form field is the common reading of
  // `empty`, and a page that painted over its own value is not that.
  let lastWithheld = false;
  function visibleText(el) {
    const sink = {};
    const out = ksVisibleTextOf(el, sink);
    lastWithheld = !!sink.excluded;
    counts.hidden_values_excluded += (sink.excluded || 0);
    for (const r of Object.keys(sink.reasons || {})) {
      counts.hidden_value_reasons[r] =
        (counts.hidden_value_reasons[r] || 0) + sink.reasons[r];
    }
    return out === null ? null : squash(out);
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
            pushLabeled(dt, text, 'definition-list', child, 'text',
                        lastWithheld ? { withheld: true } : null);
          }
        }
      }
    }
    if (tag === 'TR' && el.cells && el.cells.length === 2) {
      const k = squash(ksRenderedText(el.cells[0]));
      if (k && k.length < 80) {
        const text = visibleText(el.cells[1]);
        if (text !== null) {
          pushLabeled(k, text, 'table-row', el.cells[1], 'text',
                      lastWithheld ? { withheld: true } : null);
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
        // Pushed even when the harvest came back EMPTY because content was
        // withheld: the page does carry a source for this key, and dropping
        // the record here would make the ladder say `not_found` about a page
        // that has the field and painted over its value.
        if (text || (text !== null && lastWithheld)) {
          pushLabeled(key, text, 'aria-label', el, 'text',
                      lastWithheld ? { withheld: true } : null);
        }
      }
    }

    // --- tier 3 ---------------------------------------------------------
    if (el.children.length === 0 && counts.leaves_scanned < MAX_LEAVES) {
      counts.leaves_scanned++;
      const raw = squash(ksRenderedText(el));
      if (labelShaped(raw)) {
        const label = raw.replace(/:$/, '').trim();
        if (label && !hiddenHere(el)) {
          const found = proximateFor(el, raw);
          if (found && found.el) {
            const text = visibleText(found.el);
            const withheld = lastWithheld;
            if (text !== null && (valueShaped(text) || (!text && withheld))) {
              const rec = {
                key: clip(label, KEY_CLIP), value: clip(text, VALUE_CLIP),
                by: found.relation, relation: found.relation,
                where: where(found.el), from: 'text',
                gap_px: gapPx(el, found.el), empty: !text };
              if (withheld) rec.withheld = true;
              note(proximate, 'proximate', MAX_PROXIMATE, rec);
            }
          }
        }
      }
    }

    // --- tier 4 ---------------------------------------------------------
    if (hint.length < MAX_HINT) {
      const tokens = hintTokens(el);
      if (tokens.length) {
        // The same walk as every other tier's value (fix wave 9c). This one
        // does NOT count into `hidden_values_excluded`: the hint tier is off
        // unless a caller names it, and it mints a record per token per
        // element, so counting here would inflate the ledger by the page's
        // own class-attribute density rather than by anything withheld.
        const raw4 = ksVisibleTextOf(el, null);
        const text = raw4 === null ? null : squash(raw4);
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
  ),
};

  window["__ks4webState"] = KS4WEB_STATE;
  window["__ks4webScripts"] = KS4WEB_SCRIPTS;
})();
