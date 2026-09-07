// THE ONE RENDERED-TEXT SOURCE. Spliced into `schema.js` and into the extract
// pack's field, table, and list readers at load time, so there is exactly one
// implementation of "what does this element actually say" in the build.
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
