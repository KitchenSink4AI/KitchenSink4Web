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
var KS_PAYMENT_SUBSTRINGS = [
  'cardnumber', 'cardnum', 'cardno', 'ccnumber', 'ccnum', 'cardholder',
  'creditcard', 'debitcard', 'nameoncard', 'cardname',
  'cardexpiry', 'cardexpiration', 'cardexp', 'ccexpiry', 'ccexp',
  'securitycode', 'cardcode', 'cardsecurity', 'cvvnumber'
];
var KS_PAYMENT_WORDS = /(^| )(cvv|cvv2|cvc|cvc2|csc|ccv)( |$)/;

// A `pattern` that spells a 13-to-19 digit run is a card number whatever the
// field is called. Nothing else common has that shape: a postcode is four to
// nine, a phone number is seven to fifteen and usually admits separators, and
// an account number is rarely constrained at all. `inputmode` was considered
// for this tier and REJECTED: `inputmode="numeric"` is on every quantity,
// postcode, and OTP box on the web, and a signal that fires on all of them
// would make the payment gate the thing people route around.
var KS_PAN_PATTERN = /\{\s*1[3-9]\s*(,\s*(1[3-9])?\s*)?\}/;

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
  var raw = bits.filter(Boolean).join(' ').slice(0, 400);
  raw = raw.replace(/([a-z0-9])([A-Z])/g, '$1 $2');
  return ' ' + raw.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim() + ' ';
}

// The name tier, shared by the field question and the form question.
function ksPaymentName(el) {
  var hay = ksNameHaystack(el);
  if (hay.length < 3) return false;
  if (KS_PAYMENT_WORDS.test(hay)) return true;
  var compact = hay.replace(/ /g, '');
  for (var i = 0; i < KS_PAYMENT_SUBSTRINGS.length; i++) {
    if (compact.indexOf(KS_PAYMENT_SUBSTRINGS[i]) >= 0) return true;
  }
  return false;
}

// IS THIS CONTROL A CARD FIELD. Declared token, then name, then the PAN-shaped
// pattern attribute.
function ksPaymentField(el) {
  if (!el || !el.getAttribute) return false;
  var ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  if (KS_PAYMENT_AC.test(ac)) return true;
  if (ksPaymentName(el)) return true;
  var pat = el.getAttribute('pattern') || '';
  return !!pat && KS_PAN_PATTERN.test(pat) && /0-9|\\d/.test(pat);
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
function ksFormOf(el) {
  if (!el) return null;
  if (el.form !== undefined && el.form !== null) return el.form;
  return el.closest ? el.closest('form') : null;
}
