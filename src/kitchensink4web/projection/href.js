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
