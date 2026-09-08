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
