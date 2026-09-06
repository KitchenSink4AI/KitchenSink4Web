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

var KS_OPACITY_FLOOR = 0.05;    // below this, nothing is legible
var KS_BLUR_FLOOR = 6;          // px of blur past which text is not readable
var KS_CONTRAST_FLOOR = 0.02;   // luminance separation below which text vanishes

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

// A foreground that cannot be told from what is behind it. The alpha channel
// is read FIRST: `color: transparent` is `rgba(0,0,0,0)`, which the old
// luminance-only check scored as pure black against a white page and passed
// as high contrast. The background hunt bails on any background IMAGE in the
// chain, because a gradient or a sprite is a background this cannot measure
// and guessing there would strip real controls off real pages.
function ksInvisibleColor(el, s) {
  var fg = ksParseColor(s.color);
  if (!fg) return null;
  if (fg.a < KS_OPACITY_FLOOR) return 'transparent-text';
  var node = el, bg = null;
  for (var i = 0; node && i < 6; i++, node = ksUp(node)) {
    var ns = (node === el) ? s : ksCS(node);
    if (ns.backgroundImage && ns.backgroundImage !== 'none') return null;
    var c = ksParseColor(ns.backgroundColor);
    if (c && c.a > 0.1) { bg = c; break; }
  }
  if (!bg) return null;
  return Math.abs(ksLum(fg) - ksLum(bg)) < KS_CONTRAST_FLOOR
    ? 'low-contrast' : null;
}

// Techniques a DESCENDANT cannot undo, so they are checked up the chain.
function ksCompositedHidden(el, s) {
  if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
  if (el.hasAttribute && el.hasAttribute('hidden')) return 'hidden-attr';
  if (s.display === 'none') return 'display-none';
  if (s.contentVisibility === 'hidden') return 'content-visibility-hidden';
  if (ksFilterOpacity(s) < KS_OPACITY_FLOOR) return 'filter-transparent';
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
  if (op === op && op < KS_OPACITY_FLOOR) {
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
    if (eff < KS_OPACITY_FLOOR) return eff === 0 ? 'opacity-0' : 'near-transparent';
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
  'visibility-hidden': 'visibility:hidden stops it rendering'
};

function ksCloakReason(el) {
  var r = ksHiddenChain(el, null);
  return (r && KS_CLOAK_TECHNIQUES[r]) ? r : null;
}
