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
    payment: ksPaymentField(target),
    name: (target.getAttribute && (target.getAttribute('aria-label')
      || target.getAttribute('name'))) || target.id || ''
  };
}
