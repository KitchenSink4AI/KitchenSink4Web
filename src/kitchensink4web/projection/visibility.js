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
    ksDeepEach(document, function (el) {
      if (((++seen) & 511) === 0 && Date.now() - t0 > KS_OCCLUDER_BUDGET_MS) {
        ksOccluderTruncated = true;
        return false;
      }
      var r = el.getBoundingClientRect();
      if (r.width < KS_LID_MIN_PX || r.height < KS_LID_MIN_PX) return;
      var s = ksCS(el);
      var a = ksLidAlpha(el, s);
      if (a <= KS_LID_ALPHA_FLOOR) return;
      out.push({ el: el, rect: r, z: ksPaintRank(el), a: a });
    });
  } catch (e) { out = []; }
  ksOccluderCache = out;
  return out;
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

function ksPaintsAbove(cand, el, ze) {
  if (cand.z !== ze) return cand.z > ze;
  // Equal stacking level: later in document order paints later.
  var a = ksOrderRef(el), b = ksOrderRef(cand.el);
  if (a === b) return b !== cand.el;      // the shadow child, not the host
  try { return !!(a.compareDocumentPosition(b) & 4); } catch (e) { return true; }
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

function ksOccludedReason(el) {
  if (!el || !el.getBoundingClientRect) return null;
  var r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;   // geometry speaks for itself
  var ze = ksPaintRank(el), over = [], all = ksOccluders();
  for (var k = 0; k < all.length; k++) {
    var c = all[k];
    if (c.el === el || ksContainsDeep(c.el, el) || ksContainsDeep(el, c.el)) continue;
    if (c.rect.right <= r.left || c.rect.left >= r.right
        || c.rect.bottom <= r.top || c.rect.top >= r.bottom) continue;
    if (!ksPaintsAbove(c, el, ze)) continue;
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
  if (!centre) return null;
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
