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
  if (r.width === 0 && r.height === 0) return { reason: 'zero-size', rect: r };
  var x = r.left + window.scrollX, y = r.top + window.scrollY;
  if (x + r.width < -500 || y + r.height < -500 || x > 100000) {
    return { reason: 'offscreen', rect: r };
  }
  var s = style || ksCS(el);
  if (s.textIndent && parseFloat(s.textIndent) < -900) {
    return { reason: 'offscreen', rect: r };
  }
  return { reason: null, rect: r };
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

// The nearest z-index that actually applies, which is the innermost one up the
// chain; `auto` everywhere means 0.
function ksPaintRank(n) {
  for (var p = n; p; p = ksUp(p)) {
    var v = parseInt(ksCS(p).zIndex, 10);
    if (v === v) return v;
  }
  return 0;
}

// Does this box PAINT at all, which is deliberately NOT `ksHiddenChain`.
// That one answers whether a human can READ the element, and by that measure
// a modal backdrop is black-on-black low-contrast while being the most opaque
// thing on the page -- which is how the first draft of this scan skipped
// every backdrop it was written to catch.
function ksPaintsAtAll(el, s) {
  if (s.visibility === 'hidden' || s.visibility === 'collapse') return false;
  if (s.contentVisibility === 'hidden') return false;
  if (ksFilterOpacity(s) <= KS_OPACITY_FLOOR) return false;
  var eff = 1;
  for (var n = el; n; n = ksUp(n)) {
    if (n === document.documentElement) break;
    var ns = (n === el) ? s : ksCS(n);
    if (ns.display === 'none') return false;
    var op = parseFloat(ns.opacity);
    if (op === op) eff *= op;
    if (eff < 0.5) return false;      // see-through enough to read through
  }
  return true;
}

// The page's opaque positioned boxes, scanned ONCE per injected call. The
// geometry test comes before the style read on purpose: `getBoundingClientRect`
// is cheap after the first forced layout and `getComputedStyle` is not, so the
// scan pays full price only for boxes big enough to hide something.
var ksOccluderCache = null;
function ksOccluders() {
  if (ksOccluderCache) return ksOccluderCache;
  var out = [];
  try {
    var all = document.querySelectorAll('*');
    var n = Math.min(all.length, 8000);
    for (var i = 0; i < n && out.length < 60; i++) {
      var el = all[i];
      var r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) continue;
      var s = ksCS(el);
      if (s.position === 'static' && s.zIndex === 'auto') continue;
      var bgc = ksParseColor(s.backgroundColor);
      var opaque = (bgc && bgc.a >= 0.5)
        || (s.backgroundImage && s.backgroundImage !== 'none');
      if (!opaque) continue;
      if (!ksPaintsAtAll(el, s)) continue;     // a cloaked lid hides nothing
      out.push({ el: el, rect: r, z: ksPaintRank(el) });
    }
  } catch (e) { out = []; }
  ksOccluderCache = out;
  return out;
}

function ksPaintsAbove(cand, el, ze) {
  if (cand.z !== ze) return cand.z > ze;
  // Equal stacking level: later in document order paints later.
  return !!(el.compareDocumentPosition(cand.el) & 4);
}

function ksPointCovered(over, x, y) {
  for (var i = 0; i < over.length; i++) {
    var b = over[i].rect;
    if (x >= b.left && x <= b.right && y >= b.top && y <= b.bottom) return true;
  }
  return false;
}

function ksOccludedReason(el) {
  if (!el || !el.getBoundingClientRect) return null;
  var r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;   // geometry speaks for itself
  var ze = ksPaintRank(el), over = [], all = ksOccluders();
  for (var k = 0; k < all.length; k++) {
    var c = all[k];
    if (c.el === el || c.el.contains(el) || el.contains(c.el)) continue;
    if (c.rect.right <= r.left || c.rect.left >= r.right
        || c.rect.bottom <= r.top || c.rect.top >= r.bottom) continue;
    if (!ksPaintsAbove(c, el, ze)) continue;
    over.push(c);
  }
  if (!over.length) return null;
  var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  if (!ksPointCovered(over, cx, cy)) return null;
  var covered = 0, total = 0;
  for (var i = 1; i <= 3; i++) {
    for (var j = 1; j <= 3; j++) {
      total++;
      if (ksPointCovered(over, r.left + r.width * (i / 4),
                         r.top + r.height * (j / 4))) covered++;
    }
  }
  return (covered * 2 > total) ? 'occluded' : null;
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
