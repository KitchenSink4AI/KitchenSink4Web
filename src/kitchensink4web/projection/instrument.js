// THE INSTRUMENT CHANNEL. Installed as a context init script, so it binds
// before any page script in any document of the session runs.
//
// Everything load-bearing this server keeps in the page used to be a plain
// main-world global: `window.__ks4web_refs`, `__ks4web_refof`, `__ks4web_seq`,
// `__ks4web_closed_shadow`, `__ks4web_act`, `__ks4web_doc`. Gauntlet 2
// (2026-09-06) turned two of them into working attacks:
//
//   H5. `window.__ks4web_refs = new (class extends Map { get(){ return
//       evilButton; } })` passed the `instanceof Map` guard, so the trusted
//       click landed on the attacker's button while the result reported the
//       button the model had asked for.
//   H4. `window.__ks4web_closed_shadow = 0` rewrote the completeness block's
//       closed-root count, and so did creating the roots with a pristine
//       `attachShadow` lifted out of a same-origin iframe. Either way the
//       read asserted a completeness that did not hold, which is the exact
//       honesty property the traversal work exists to guarantee.
//
// The state now lives in THIS closure and nowhere else. What the page can
// reach is one non-enumerable, non-writable, NON-CONFIGURABLE function that
// hands the state back only to a caller carrying a secret minted by the
// server at process start and baked into the injected script sources. The
// page cannot read the state, cannot write it, cannot replace the accessor,
// and cannot pre-patch anything this script touches, because no page script
// has run when it runs.
//
// Three consequences worth stating plainly:
//
//  * `instanceof` is not a guard anywhere in this build any more. Nothing
//    validates a page-supplied object by its prototype, because a subclass
//    satisfies that check and a Proxy satisfies almost any other.
//  * A CHILD FRAME reports its closed roots UP to the top document's state
//    when the two are same-origin, so lifting a pristine `attachShadow` out
//    of a same-origin iframe now increments the same counter the top-level
//    read prints. A cross-origin frame keeps its own count, which is honest:
//    nothing in this build reads across that boundary anyway.
//  * `Element.prototype.attachShadow` is redefined NON-CONFIGURABLE. A page
//    that legitimately wants to patch it (a web-components polyfill on an
//    engine that already ships the native method) will fail to. That is a
//    deliberate trade: the closed-root line is a completeness claim, and a
//    claim a page can edit is worse than no claim.
//
// RESIDUAL, stated rather than papered over: the accessor's PRESENCE is
// detectable, so a page can still tell that automation is driving it. That
// was already true of the six globals this replaces, and hiding it is not
// something this design pretends to do.
(() => {
  'use strict';
  const KEY = '__KS4WEB_KEY__';
  const SECRET = '__KS4WEB_SECRET__';
  try {
    if (Object.getOwnPropertyDescriptor(window, KEY)) return;
  } catch (e) { return; }

  const state = {
    refs: new Map(),          // node ref -> element
    refof: new WeakMap(),     // element -> node ref
    seq: 0,
    act: Object.create(null), // observation tokens
    actseq: 0,
    closed: 0,                // closed shadow roots, counted at creation
    doc: 0,                   // document epoch
    // FRAME IDENTITY, in its own map on purpose. `refof` is shared by every
    // pass and each one overwrites an element's entry with a ref in its own
    // namespace, so an `<iframe>` that the search happened to classify would
    // silently lose the id the frame ladder keyed on and the ladder would
    // mint a second one for the same frame. A frame's identity has to
    // outlive every other pass's bookkeeping, so it does not share a map
    // with any of them.
    frameid: new WeakMap(),
    frameseq: 0
  };

  const open = function (secret) { return secret === SECRET ? state : null; };
  try {
    Object.defineProperty(window, KEY, {
      value: open, writable: false, configurable: false, enumerable: false
    });
  } catch (e) { return; }

  // Where a closed-root count belongs: the TOP document's state when it is
  // reachable, so a root created through a frame's own realm is counted where
  // the read will look for it.
  function ledger() {
    try {
      if (window.top !== window && typeof window.top[KEY] === 'function') {
        const s = window.top[KEY](SECRET);
        if (s) return s;
      }
    } catch (e) { /* cross-origin top: keep our own count */ }
    return state;
  }

  const original = Element.prototype.attachShadow;
  if (typeof original === 'function') {
    const patched = function attachShadow(init) {
      if (init && init.mode === 'closed') ledger().closed++;
      return original.apply(this, arguments);
    };
    // A page that fingerprints by reading the source gets the native string
    // back. This is not a claim of undetectability; it removes the cheapest
    // tell for the cost of one line.
    try {
      patched.toString = function () { return original.toString(); };
    } catch (e) { /* frozen Function.prototype */ }
    try {
      Object.defineProperty(Element.prototype, 'attachShadow', {
        value: patched, writable: false, configurable: false, enumerable: false
      });
    } catch (e) { /* already locked by something else: leave it alone */ }
  }
})();

