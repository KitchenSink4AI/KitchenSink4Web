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
//
// THE VOCABULARY IS NOT ENGLISH, and re-attack 2 (B1) is why it says so here.
// DESIGN's own statement of what this tier is for -- "the pages this defends
// against are exactly the ones that declare nothing while still calling the
// field something a human reads" -- has no language in it, and the list did:
// `kartennummer` was simply absent, and the squash below reduced a Korean
// 카드번호 or a Japanese カード番号 to the EMPTY STRING before a single token
// was compared. A live PAN went into all three ungated.
//
// SOURCES for the non-English terms, because inventing vocabulary for a
// security gate is how a gate ends up firing on the wrong thing:
//  * The localized card-field labels browser autofill matches on. Chromium's
//    autofill heuristics (`components/autofill/core/browser/*regex*`) carry
//    exactly this family -- `kartennummer`, `numero de carte`, `numero de
//    tarjeta`, `numero della carta`, `カード番号`, `카드번호`, `信用卡`,
//    `sicherheitscode`, `codigo de seguridad`, `セキュリティコード` -- because
//    they are what real checkout pages in those languages actually write.
//  * The WHATWG HTML autocomplete tokens (`cc-number`, `cc-exp`, `cc-csc`)
//    remain the declared tier above and are language-independent.
// Terms below are the ordinary rendering of "card number", "expiry", and
// "security code" in each language; each is the label a human in that market
// reads on a checkout page.

// TIER 1: A CARD NUMBER. A match here classifies the field on its own.
var KS_PAN_TERMS = [
  // English
  'cardnumber', 'cardnum', 'cardno', 'ccnumber', 'ccnum',
  'creditcard', 'debitcard', 'cardholder', 'nameoncard', 'cardname',
  // German: Kartennummer, Kreditkarte, Karteninhaber
  'kartennummer', 'kartennr', 'kreditkarte', 'karteninhaber',
  // French: numéro de carte, carte bancaire, carte de crédit
  'numerodecarte', 'numerodelacarte', 'cartebancaire', 'cartedecredit',
  'titulairedelacarte',
  // Spanish / Portuguese: número de tarjeta, tarjeta de crédito,
  // número do cartão, cartão de crédito
  'numerodetarjeta', 'tarjetadecredito', 'tarjetacredito',
  'numerodocartao', 'cartaodecredito', 'titulardelatarjeta',
  // Italian: numero della carta, carta di credito
  'numerodellacarta', 'numerodicarta', 'cartadicredito',
  // Korean: 카드번호 (card number), 신용카드 (credit card), 카드 소유자
  '카드번호', '신용카드', '체크카드', '카드소유자',
  // Japanese: カード番号, クレジットカード, カード名義
  'カード番号', 'クレジットカード', 'カードナンバー', 'カード名義',
  // Chinese: 卡号 (card number), 信用卡, 持卡人
  '卡号', '卡號', '信用卡', '持卡人', '銀行卡', '银行卡'
];

// TIER 2: THE CARD NUMBER'S NEIGHBOURS -- expiry and security code. These are
// GENERIC phrases in every language on this list ("expiry date", "security
// code", 유효기간, 有効期限), so a match classifies the field only where the
// same form also carries a card number. A passport expiry and a one-time-code
// box are not payment fields, and a gate that says they are is the gate DESIGN
// warns people learn to route around. The card-QUALIFIED compounds
// (`cardexpiry`, `ccexp`, `securitycode`) stay in tier 1's company below,
// because the qualifier is the disambiguation.
var KS_CARD_SIDE_TERMS = [
  // English, card-qualified: these classify alone.
  'cardexpiry', 'cardexpiration', 'cardexp', 'ccexpiry', 'ccexp',
  'securitycode', 'cardcode', 'cardsecurity', 'cvvnumber'
];
var KS_CARD_NEIGHBOUR_TERMS = [
  // German: gültig bis, Ablaufdatum, Prüfziffer, Prüfnummer, Sicherheitscode
  'gultigbis', 'ablaufdatum', 'prufziffer', 'prufnummer', 'sicherheitscode',
  // French: date d'expiration, cryptogramme visuel, code de sécurité
  'dateexpiration', 'dexpiration', 'cryptogramme', 'codedesecurite',
  // Spanish / Portuguese: fecha de caducidad, fecha de vencimiento,
  // código de seguridad, validade
  'fechadecaducidad', 'fechadevencimiento', 'codigodeseguridad', 'validade',
  // Italian: scadenza, codice di sicurezza
  'scadenza', 'codicedisicurezza',
  // Korean: 유효기간 (valid period), 보안코드 (security code)
  '유효기간', '보안코드', '유효기한',
  // Japanese: 有効期限, セキュリティコード, カード確認番号
  '有効期限', 'セキュリティコード', 'カード確認番号',
  // Chinese: 有效期, 安全码, 安全碼
  '有效期', '安全码', '安全碼'
];
var KS_PAYMENT_WORDS = /(^| )(cvv|cvv2|cvc|cvc2|csc|ccv)( |$)/;

// NOT EVERY "<something> card number" IS A PAYMENT FIELD. `cardnumber`
// matches as a substring, which is what makes `card_number` and `Card number`
// both work and also made `Library card number`, `Loyalty card number`, and
// `Boarding card number` payment fields (re-attack 2, B6). A payment
// confirmation on a library form is the erosion DESIGN names by name.
//
// B6's answer was the right rule wearing the wrong clothes. It said the token
// immediately preceding `card` names the INSTRUMENT, which is true, and then
// implemented it as a HAND-MAINTAINED LIST OF NON-PAYMENT INSTRUMENTS -- which
// is an instance list, and re-attack 3 (M4) found the unlisted member in one
// try: `Residence card number` classified as payment, and a residence card is
// the standard foreign-resident ID across this build's own market.
//
// So the rule is stated the way it was always meant to be, and the OPEN set
// is the one that stops being enumerated. The set of payment instruments is
// small and closed -- credit, debit, gift, bank, prepaid, and the networks --
// and the set of everything else a card can be is unbounded. A `card`
// qualified by anything outside the payment set is a foreign instrument
// whatever it is called, so `residence`, `fishing`, and `punch` need no entry.
//
// Two lists, and neither is an instrument list. `KS_PAYMENT_QUALIFIERS` is the
// closed payment set. `KS_TRANSPARENT_WORDS` is English grammar: a function
// word qualifies nothing, which is what keeps `Name on card` a card field.
var KS_PAYMENT_QUALIFIERS = [
  'credit', 'debit', 'gift', 'bank', 'prepaid', 'pre', 'charge', 'payment',
  'pay', 'visa', 'master', 'mastercard', 'amex', 'american', 'express',
  'discover', 'jcb', 'unionpay', 'maestro', 'atm', 'cash', 'store', 'travel'
];
var KS_TRANSPARENT_WORDS = [
  'on', 'the', 'a', 'an', 'my', 'your', 'our', 'their', 'this', 'that', 'of',
  'for', 'to', 'and', 'or', 'in', 'no', 'new', 'enter', 'please', 'valid',
  'number', 'nr', 'no'
];

// Strike every `<foreign> card` compound out of a spaced haystack, and say
// whether one was found. The qualifier goes with it, so `library card number`
// leaves `number` and matches nothing.
// The QUALIFIER only counts as one where it reads as a word naming a thing.
// A haystack is every identifier on the control run together, so `id=c_card`
// contributes the token pair `c card` and a rule that takes any preceding
// token would read `c` as an instrument. Three guards keep it honest: the
// qualifier is at least three characters, it is not `card` itself repeating
// from a second identifier, and it is not already a card term.
function ksIsForeignQualifier(prev) {
  if (!prev || prev.length < 3 || prev === 'card') return false;
  if (KS_PAYMENT_QUALIFIERS.indexOf(prev) >= 0) return false;
  if (KS_TRANSPARENT_WORDS.indexOf(prev) >= 0) return false;
  return !ksHasTerm(prev, KS_PAN_TERMS)
      && !ksHasTerm(prev, KS_CARD_SIDE_TERMS);
}

// The compound is broken rather than deleted: `card` becomes a space, which a
// substring match cannot cross, and the qualifier stays where it was. Deleting
// both is what let `Card number` written alongside an `id=c_card` lose its own
// `cardnumber` token to a cascade.
function ksForeignCardStrike(hay) {
  var words = String(hay || '').trim().split(' ');
  var out = [], foreign = false;
  for (var i = 0; i < words.length; i++) {
    if (words[i] === 'card' && i > 0 && ksIsForeignQualifier(words[i - 1])) {
      foreign = true;
      out.push(' ');
      continue;
    }
    out.push(words[i]);
  }
  return { text: out.join(''), foreign: foreign };
}

// The GLUED spellings, which the word rule above cannot reach because there is
// no space to read a preceding word from: `name=librarycard` is one token. The
// list stays for exactly that case and is no longer the whole rule.
var KS_NOT_PAYMENT_CARDS = [
  'library', 'loyalty', 'membership', 'member', 'boarding', 'id', 'identity',
  'sim', 'key', 'room', 'door', 'access', 'badge', 'business', 'report',
  'score', 'student', 'staff', 'employee', 'health', 'insurance', 'medicare',
  'social', 'birthday', 'greeting', 'memory', 'sd', 'graphics', 'video',
  'sound', 'rewards', 'reward', 'points', 'club', 'discount', 'stamp',
  'punch', 'time', 'swipe', 'game', 'gaming', 'phone', 'index', 'tarot',
  'wild'
];

// A `pattern` that spells a 13-to-19 digit run is a card number whatever the
// field is called. Nothing else common has that shape: a postcode is four to
// nine, a phone number is seven to fifteen and usually admits separators, and
// an account number is rarely constrained at all. `inputmode` was considered
// for this tier and REJECTED: `inputmode="numeric"` is on every quantity,
// postcode, and OTP box on the web, and a signal that fires on all of them
// would make the payment gate the thing people route around.
var KS_PAN_PATTERN = /\{\s*1[3-9]\s*(,\s*(1[3-9])?\s*)?\}/;

// A PAN SHAPE shown to the HUMAN rather than declared to the validator. The
// `pattern` tier above reads `{13,19}` off an attribute a page is free to
// omit; `placeholder="1234 5678 9012 3456"` is the same declaration aimed at
// the person filling the form, and a masked `value="**** **** **** ****"` is
// that declaration after the fact (re-attack 2, B3 and B4). Four groups of
// four, or a bare 13-to-19 digit run, and nothing else: an IBAN carries
// letters, a phone number carries punctuation, and a date is too short.
function ksPanShape(v) {
  if (!v) return false;
  var s = String(v).trim();
  if (s.length < 13 || s.length > 32) return false;
  var core = s.replace(/[ \-]/g, '');
  if (core.length < 13 || core.length > 19) return false;
  return /^[0-9]+$/.test(core) || /^[*x\u2022\u00b7#]+$/i.test(core);
}

// THE NORMALIZER, and it has to be Unicode-honest or the tier above cannot
// see the label at all. `[^a-z0-9]+ -> ' '` reduced 카드번호 and カード番号 to
// nothing, and the `length > 2` guard then dropped the field before any token
// was compared: the classifier was not missing a Korean word, it could not
// see any Korean word. Letters and digits of EVERY script survive; only
// separators collapse. Diacritics are folded (NFKD, strip the LATIN combining
// block, recompose) so `numéro` and `gültig` reduce to the ASCII spellings the
// vocabulary lists, and Hangul and kana recompose unharmed. The range matters:
// stripping every combining mark would also take U+3099, the Japanese voiced
// sound mark, which turns ド into ト and カード番号 into a word that matches
// nothing. The Python mirror does exactly this range and a test pins the two.
function ksSquashNames(raw) {
  var s = String(raw || '').slice(0, 400);
  s = s.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
  try {
    s = s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').normalize('NFC');
  } catch (e) { /* an engine without normalize keeps the raw string */ }
  return ' ' + s.replace(/[^\p{L}\p{N}]+/gu, ' ').trim() + ' ';
}

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
  return ksSquashNames(bits.filter(Boolean).join(' '));
}

// The de-spaced haystack with every foreign-instrument card compound struck
// out, so a substring match cannot land inside `librarycard`. Both routes run:
// the word rule reads the qualifier off the spaced string and reaches any
// qualifier at all, and the glued list catches the spellings that carry no
// space to read.
function ksPaymentCompactInfo(hay) {
  var struck = ksForeignCardStrike(hay);
  var compact = struck.text, foreign = struck.foreign;
  for (var i = 0; i < KS_NOT_PAYMENT_CARDS.length; i++) {
    var q = KS_NOT_PAYMENT_CARDS[i] + 'card';
    if (compact.indexOf(q) >= 0) {
      compact = compact.split(q).join(' ');
      foreign = true;
    }
  }
  return { compact: compact, foreign: foreign };
}

function ksPaymentCompact(hay) {
  return ksPaymentCompactInfo(hay).compact;
}

function ksHasTerm(compact, terms) {
  for (var i = 0; i < terms.length; i++) {
    if (compact.indexOf(terms[i]) >= 0) return true;
  }
  return false;
}

// The name tier, shared by the field question and the form question. TIER 1
// only: a card number, or a card-qualified expiry or security code. Returns
// the FOREIGN flag alongside the verdict, because a `<X> card number` is not
// simply "not a card": it is a card compound whose instrument is something
// else, and a form that also carries an expiry box or a declared `cc-number`
// token can still make it one (ruling on M4).
function ksPaymentNameInfo(el) {
  var hay = ksNameHaystack(el);
  if (hay.length < 3) return { name: false, foreign: false, hay: hay };
  if (KS_PAYMENT_WORDS.test(hay)) return { name: true, foreign: false, hay: hay };
  var info = ksPaymentCompactInfo(hay);
  var hit = ksHasTerm(info.compact, KS_PAN_TERMS)
    || ksHasTerm(info.compact, KS_CARD_SIDE_TERMS);
  return { name: hit, foreign: info.foreign && !hit, hay: hay };
}

function ksPaymentName(el) {
  return ksPaymentNameInfo(el).name;
}

// DOES ANYTHING ELSE ON THIS FORM SAY CARD. The corroboration the M4 ruling
// asks for, and the same signal the shape tiers below need: a declared
// `cc-*` token, a sibling expiry or security-code box, or a sibling the name
// tier already classifies. It never asks `ksPaymentField` back, so there is no
// recursion and no way for two weak signals to bootstrap each other.
var ksCorroborationCache = new Map();
function ksCardCorroborated(el) {
  var ac = (el.getAttribute && el.getAttribute('autocomplete') || '').toLowerCase();
  if (KS_PAYMENT_AC.test(ac)) return true;
  var form = ksFormOf(el);
  if (!form) return false;
  var v = ksCorroborationCache.get(form);
  if (v !== undefined) return v;
  v = false;
  try {
    var els = form.elements || [];
    for (var i = 0; i < els.length && i < 500; i++) {
      var x = els[i];
      if (!x || !x.getAttribute) continue;
      if (KS_PAYMENT_AC.test((x.getAttribute('autocomplete') || '').toLowerCase())) {
        v = true; break;
      }
      var info = ksPaymentCompactInfo(ksNameHaystack(x));
      if (ksHasTerm(info.compact, KS_CARD_NEIGHBOUR_TERMS)
          || ksHasTerm(info.compact, KS_CARD_SIDE_TERMS)) { v = true; break; }
    }
  } catch (e) { v = false; }
  ksCorroborationCache.set(form, v);
  return v;
}

// DOES THIS CONTROL CARRY A NAME AT ALL -- any identifier with letters in it.
// It decides whether the SHAPE tiers get to speak on their own (M3 and M5).
// A `pattern` of thirteen-to-nineteen digits, a PAN-shaped placeholder, and a
// masked PAN-shaped value are all real signals and none of them is a name: a
// phone field declaring `[0-9]{13,15}`, an IMEI field showing fifteen digits,
// a tracking-number field showing four groups of four, and a field labelled
// `IBAN` holding `**** **** **** ****` all gated as payment on shape alone.
// A page that NAMES its field is telling the truth about it, so the name
// governs, and the shape speaks where the page named nothing or where
// something else on the form corroborates it.
function ksHasNaming(hay) {
  try { return /\p{L}\p{L}/u.test(hay); } catch (e) { return /[a-z]{2}/.test(hay); }
}

// The neighbour tier, which needs a card number somewhere in the same form.
function ksPaymentNeighbourName(el) {
  var hay = ksNameHaystack(el);
  if (hay.length < 3) return false;
  return ksHasTerm(ksPaymentCompact(hay), KS_CARD_NEIGHBOUR_TERMS);
}

// A SPLIT CARD NUMBER, which is a mainstream checkout layout and was
// unclassified end to end (re-attack 2, B2): four boxes named `cc1..cc4`,
// `maxlength=4`, `pattern="[0-9]{4}"`, under a `<legend>Card number</legend>`
// the haystack never reads. No tier fired, so the FORM was not payment-shaped
// either and the submit that sends the number got the weaker gate.
//
// The class is a GROUP of short numeric boxes whose combined length reads as
// a PAN. The group is the fieldset or the shared parent, the count is two to
// six, and the digits total 13 to 19 -- which is what separates it from every
// other split field on the web: a date is 2+2+4, a phone is 3+3+4, an OTP is
// six boxes of one, and a split IBAN runs past 19. The measurements are
// returned as FACTS so the server-side re-derivation applies the same rule to
// the same numbers rather than trusting a verdict.
// A box's declared digit capacity. `maxlength` is the usual way to say "this
// holds four digits" and it is not the only one: re-attack 3 (R5) declared
// `size=4 pattern="[0-9]{4}" inputmode=numeric` with no `maxlength`, the group
// came back empty, and the full sixteen digits landed in the field because
// nothing even truncated them. A `pattern` that pins a length says the same
// thing the attribute says, so it counts, and `size` corroborates that the box
// is a short one rather than a full-width field with a validation rule.
function ksPatternLen(pat) {
  var m = /^\^?(?:\[0-9\]|\\d)\{(\d+)(?:,\s*(\d+))?\}\$?$/
    .exec(String(pat || '').replace(/\s+/g, ''));
  if (!m) return 0;
  var hi = m[2] ? parseInt(m[2], 10) : parseInt(m[1], 10);
  return (hi >= 1 && hi <= 6) ? hi : 0;
}

function ksNumericBoxLen(el) {
  if (!el || el.tagName !== 'INPUT') return 0;
  var t = (el.type || 'text').toLowerCase();
  if (t !== 'text' && t !== 'tel' && t !== 'number' && t !== 'password') return 0;
  var im = (el.getAttribute('inputmode') || '').toLowerCase();
  var pat = el.getAttribute('pattern') || '';
  var numeric = im === 'numeric' || im === 'decimal' || t === 'number'
    || t === 'tel' || /\[0-9\]|\\d/.test(pat);
  if (!numeric) return 0;
  var ml = parseInt(el.getAttribute('maxlength'), 10);
  if (ml === ml && ml >= 1 && ml <= 6) return ml;
  var pl = ksPatternLen(pat);
  if (!pl) return 0;
  var sz = parseInt(el.getAttribute('size'), 10);
  return (sz === sz && sz <= 8) ? pl : 0;
}

// WHAT THE REGION CALLS ITSELF: 1 where it names a card number, -1 where it
// names some other instrument, 0 where it says nothing either way. This is
// M1's answer. The split-group rule counted boxes and never read a name, so a
// `<legend>Library card number</legend>` over four 4-digit boxes gated as a
// payment form while B6 had already struck `librarycard` out of the NAME tier.
// One rule, two places it has to be asked.
function ksRegionCardName(scope) {
  var text = '';
  try { text = (scope.textContent || '').slice(0, 400); } catch (e) { return 0; }
  var info = ksPaymentCompactInfo(ksSquashNames(text));
  if (ksHasTerm(info.compact, KS_PAN_TERMS)
      || ksHasTerm(info.compact, KS_CARD_SIDE_TERMS)) return 1;
  return info.foreign ? -1 : 0;
}

// A SPLIT CARD NUMBER'S GROUP IS A RUN, NOT A PARENT. Re-attack 3 (R5) put one
// wrapper `<div>` around each box -- which is what every CSS framework does to
// build a column layout -- and `closest('fieldset') || parentElement` handed
// back a group of one. So the group is discovered by STRUCTURE: within the
// enclosing fieldset or form, take the boxes in document order and keep the
// unbroken run of short numeric ones this box belongs to. Wrappers are
// transparent because the run never looks at them.
function ksPanGroup(el) {
  if (!ksNumericBoxLen(el)) return null;
  var scope = null;
  try { scope = el.closest('fieldset') || ksFormOf(el) || el.parentElement; }
  catch (e) {}
  if (!scope) return null;
  var boxes, lens = [], idx = -1;
  try { boxes = scope.querySelectorAll('input'); } catch (e) { return null; }
  for (var i = 0; i < boxes.length && i < 200; i++) {
    lens.push(ksNumericBoxLen(boxes[i]));
    if (boxes[i] === el) idx = i;
  }
  if (idx < 0) return null;
  var lo = idx, hi = idx;
  while (lo > 0 && lens[lo - 1]) lo--;
  while (hi + 1 < lens.length && lens[hi + 1]) hi++;
  var size = 0, digits = 0, min = 99;
  for (var j = lo; j <= hi; j++) {
    size++;
    digits += lens[j];
    if (lens[j] < min) min = lens[j];
  }
  return { size: size, digits: digits, first: lens[lo], min: min,
           region: ksRegionCardName(scope) };
}

// IS THIS RUN A CARD NUMBER. Two to six boxes totalling thirteen to nineteen
// digits is the count, and it is not enough on its own: a date of birth plus a
// texted code is 2+2+4+6, four short numeric boxes and fourteen digits inside
// the same window (M2). What separates them is the PARTITION. Card numbers are
// written in groups of four or more -- 4-4-4-4, amex's 4-6-5, Diners' 4-6-4 --
// and nothing else on a form is, because a date leads with a two-digit day and
// a phone leads with a three-digit area code. So the run has to lead with four
// and hold no box shorter than four, and the region must not name a different
// instrument.
function ksPanGroupIsCard(g) {
  if (!g) return false;
  if (!(g.size >= 2 && g.size <= 6 && g.digits >= 13 && g.digits <= 19)) {
    return false;
  }
  if (g.region < 0) return false;
  return g.first >= 4 && g.min >= 4;
}

// IS THIS CONTROL A CARD FIELD. Declared token, then name, then the PAN-shaped
// pattern attribute, then the PAN shape a human is shown, then the split
// group, and last the neighbour tier which needs a card number in the form.
function ksPaymentField(el) {
  if (!el || !el.getAttribute) return false;
  var ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  if (KS_PAYMENT_AC.test(ac)) return true;
  var named = ksPaymentNameInfo(el);
  if (named.name) return true;
  if (named.foreign) return ksCardCorroborated(el);
  var pat = el.getAttribute('pattern') || '';
  var shaped = (pat && KS_PAN_PATTERN.test(pat) && /0-9|\\d/.test(pat))
    || ksPanShape(el.getAttribute('placeholder'))
    || ksPanShape(el.getAttribute('title'))
    || ksPanShape('value' in el ? el.value : '');
  if (shaped && (!ksHasNaming(named.hay) || ksCardCorroborated(el))) return true;
  if (ksPanGroupIsCard(ksPanGroup(el))) return true;
  return ksPaymentNeighbourName(el) && ksFormHasCard(ksFormOf(el));
}

// The tier-1 answer for a whole form, which the neighbour tier asks and which
// must NOT ask `ksPaymentField` back. Everything here is a card number or a
// card-qualified compound, so there is no recursion and no way for two
// neighbour fields to bootstrap each other into a payment form.
var ksFormCardCache = new Map();
function ksFormHasCard(formEl) {
  if (!formEl) return false;
  var v = ksFormCardCache.get(formEl);
  if (v !== undefined) return v;
  v = false;
  try {
    var els = formEl.elements || [];
    for (var i = 0; i < els.length && i < 500; i++) {
      var el = els[i];
      if (!el || !el.getAttribute) continue;
      if (KS_PAYMENT_AC.test((el.getAttribute('autocomplete') || '').toLowerCase())
          || ksPaymentName(el)
          || ksPanGroupIsCard(ksPanGroup(el))) { v = true; break; }
      var shaped = ksPanShape(el.getAttribute('placeholder'))
        || ksPanShape('value' in el ? el.value : '');
      if (shaped && !ksHasNaming(ksNameHaystack(el))) { v = true; break; }
    }
  } catch (e) { v = false; }
  ksFormCardCache.set(formEl, v);
  return v;
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
//
// The ancestry fallback climbs the FLATTENED tree, which is the same sweep
// R6 asked for in `activation.js`: a node slotted into a shadow form has the
// host as its light parent and `closest('form')` walks straight past the form
// that would actually submit it.
function ksFormOf(el) {
  if (!el) return null;
  if (el.form !== undefined && el.form !== null) return el.form;
  for (var n = el, guard = 0; n && guard++ < 64; n = ksUp(n)) {
    if (n.tagName === 'FORM') return n;
  }
  return null;
}
