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
