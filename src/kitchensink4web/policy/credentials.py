"""Credential blindness: the tool itself is password-blind (DESIGN 5.3).

Unserved as a tool-level control anywhere in the field. Every incumbent
architects the secret out of the model's context and none makes the TOOL
blind; playwright-mcp #1566 (accessibility snapshot serializes password
values as plaintext) is unowned to this day.

Three mechanisms live here, and their division of labor matters:

1. **Classification.** What counts as a secret field is decided ONCE, here,
   and the projection's extractor applies the same rule in-page (extract.js:
   `type=password` or an autocomplete token in the current-password /
   new-password / one-time-code family). A secret field's value is NEVER
   READ, not read-then-redacted: a redaction that runs after the value is in
   memory has already lost on any path that logs before it.

2. **The vault.** Some code paths must touch credential-bearing values to do
   their jobs (cookie reads, storage reads, auth-state save). The contract,
   binding on every such path: **observe the value into the vault BEFORE it
   goes anywhere.** The vault is what the serializer redactor checks, so an
   observed value can never ride out in any payload or file write, whichever
   tool tries to emit it. The Phase 3 gate proves this with a deliberately
   leaky test tool caught by the serializer, not by the tool.

3. **Masking.** Storage and cookie reads return names and metadata with
   values masked by default. `unmask=true` is per-call, explicit, audited,
   and REFUSED under `KS4WEB_CREDENTIAL_BLIND=strict`, which is the default.

The write-refusal half (type_text / fill_form refusing secret targets with
`CREDENTIAL_REFUSED`) is enforced at the policy choke point
(`policy/engine.py`), because per-tool discipline fails the moment someone
adds a feature.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from typing import Any

from ..errors import CredentialRefused

#: Autocomplete tokens that mark a field as a secret. The same family the
#: extractor tests in-page; a divergence between the two lists would let a
#: field be secret in the projection and writable at the choke point.
SECRET_AUTOCOMPLETE = ("current-password", "new-password", "one-time-code")

#: Autocomplete tokens that mark a form as payment-shaped, which is a GATED
#: class (DESIGN 5.4) rather than a blind one: the user may genuinely want to
#: pay, and the gate is confirmation, not refusal.
PAYMENT_AUTOCOMPLETE = ("cc-number", "cc-exp", "cc-csc")

ENV_STRICT = "KS4WEB_CREDENTIAL_BLIND"

#: Values shorter than this never enter the vault. Redacting "1" or "ok"
#: out of every payload would shred ordinary output while adding nothing: a
#: secret that short is not protected by redaction anyway.
#:
#: Raised from 4 to 8 after the 2026-09-05 field test, where a preference
#: cookie holding the five-character value "light" garbled the word
#: "highlights" in every subsequent read for the rest of the session. No
#: real credential is under eight characters; plenty of preference values
#: are.
MIN_SECRET_LENGTH = 8

#: At or above this length, accidental containment inside ordinary prose is
#: implausible, so a vaulted value is matched as a raw substring (a leaked
#: cookie rides inside a sentence at least as often as it rides alone).
#: Below it, matching is token-bounded: the value is redacted where it
#: stands alone, not where it happens to sit inside a longer word.
SUBSTRING_MIN_LENGTH = 16

#: Characters that continue a token. A short vaulted value surrounded by
#: any of these on either side is part of a longer word and is left alone.
_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")

#: Cookie and storage NAMES that mark a value as credential-shaped. Checked
#: as substrings of a lowercased name, so `_gh_sess`, `user_session`,
#: `PHPSESSID`, `csrftoken`, and `remember_user_token` all classify.
SECURITY_NAME_TOKENS = (
    "session", "sess", "token", "auth", "csrf", "xsrf", "secret",
    "credential", "jwt", "password", "passwd", "bearer", "signature",
    "api_key", "apikey", "access_key",
)

#: Names known to carry a display or locale PREFERENCE rather than a
#: credential. Checked first, so a name that contains a security token by
#: coincidence still passes through. These are the values the field test
#: watched shred ordinary reads.
PREFERENCE_NAME_TOKENS = (
    "color_mode", "colour_mode", "color_scheme", "theme", "locale", "lang",
    "language", "timezone", "tz", "cpu_bucket", "font", "layout", "density",
    "sidebar", "collapsed", "dismissed", "consent", "banner", "screen",
    "viewport", "width", "height", "zoom",
)

MASK = "[REDACTED:secret]"


def strict() -> bool:
    """Strict is the DEFAULT. Only an explicit off-value relaxes it."""
    value = os.environ.get(ENV_STRICT, "strict").strip().lower()
    return value not in ("0", "false", "off", "no", "open")


def is_secret_field(field: dict) -> bool:
    """Classify a field descriptor (an anchor, a form-inventory line, or a
    find_elements match). The extractor sets `secret` in-page from the same
    rule; this re-derives it server-side so a caller-supplied descriptor
    cannot simply omit the flag."""
    if field.get("secret"):
        return True
    if (field.get("type") or "").strip().lower() == "password":
        return True
    ac = (field.get("autocomplete") or "").strip().lower()
    return any(token in ac for token in SECRET_AUTOCOMPLETE)


#: Payment NAMES, matched on a field's squashed identifiers, and the exact
#: mirror of `projection/payment.js` (`test_credentials.py` pins the two lists
#: equal, the way the secret rule is pinned to the extractor's). Two tiers,
#: because the short ones are initialisms that collide with ordinary words: a
#: long token matches as a SUBSTRING of the de-spaced string, so `card_number`,
#: `cardNumber`, `card-number` and `Card number` all reduce to `cardnumber`,
#: while a short one must stand as its own WORD.
#: TIER 1, a card number in any language. See `projection/payment.js` for the
#: sourcing note: the non-English terms are the localized card labels browser
#: autofill heuristics match on, because they are what real checkout pages in
#: those markets write. The list was English-only until re-attack 2 (B1) put a
#: live PAN into `Kartennummer`, 카드번호, and カード番号 ungated.
PAYMENT_PAN_TERMS = (
    "cardnumber", "cardnum", "cardno", "ccnumber", "ccnum", "cardholder",
    "creditcard", "debitcard", "nameoncard", "cardname",
    "kartennummer", "kartennr", "kreditkarte", "karteninhaber",
    "numerodecarte", "numerodelacarte", "cartebancaire", "cartedecredit",
    "titulairedelacarte",
    "numerodetarjeta", "tarjetadecredito", "tarjetacredito",
    "numerodocartao", "cartaodecredito", "titulardelatarjeta",
    "numerodellacarta", "numerodicarta", "cartadicredito",
    "카드번호", "신용카드", "체크카드", "카드소유자",
    "カード番号", "クレジットカード", "カードナンバー", "カード名義",
    "卡号", "卡號", "信用卡", "持卡人", "銀行卡", "银行卡",
)

#: Card-QUALIFIED expiry and security-code compounds. The qualifier is the
#: disambiguation, so these classify a field on their own.
PAYMENT_CARD_SIDE_TERMS = (
    "cardexpiry", "cardexpiration", "cardexp", "ccexpiry", "ccexp",
    "securitycode", "cardcode", "cardsecurity", "cvvnumber",
)

#: The card number's NEIGHBOURS: expiry and security code as they are written
#: in each language, all of them generic phrases on their own. A passport
#: expiry and a one-time-code box are not payment fields, so a match here
#: classifies only where the same FORM carries a card number.
PAYMENT_NEIGHBOUR_TERMS = (
    "gultigbis", "ablaufdatum", "prufziffer", "prufnummer", "sicherheitscode",
    "dateexpiration", "dexpiration", "cryptogramme", "codedesecurite",
    "fechadecaducidad", "fechadevencimiento", "codigodeseguridad", "validade",
    "scadenza", "codicedisicurezza",
    "유효기간", "보안코드", "유효기한",
    "有効期限", "セキュリティコード", "カード確認番号",
    "有效期", "安全码", "安全碼",
)

#: THE PAYMENT INSTRUMENTS, which is the closed set. Re-attack 2 (B6) named
#: the right rule -- the token before `card` names the instrument -- and then
#: implemented it as a list of the things a card can be that are NOT payment
#: instruments, which is unbounded. Re-attack 3 (M4) found the unlisted member
#: on the first try: `Residence card number` classified as payment. Enumerate
#: the small side instead, and `residence`, `fishing`, and `punch` need no
#: entry. The mirror of `KS_PAYMENT_QUALIFIERS`.
PAYMENT_CARD_QUALIFIERS = (
    "credit", "debit", "gift", "bank", "prepaid", "pre", "charge", "payment",
    "pay", "visa", "master", "mastercard", "amex", "american", "express",
    "discover", "jcb", "unionpay", "maestro", "atm", "cash", "store", "travel",
)

#: English function words, which qualify nothing. Without these `Name on card`
#: would read as an `on` card and stop being a payment field. The mirror of
#: `KS_TRANSPARENT_WORDS`.
TRANSPARENT_QUALIFIERS = (
    "on", "the", "a", "an", "my", "your", "our", "their", "this", "that",
    "of", "for", "to", "and", "or", "in", "no", "new", "enter", "please",
    "valid", "number", "nr",
)

#: The GLUED spellings the word rule cannot reach, because `librarycard` is one
#: token with no space to read a preceding word from. This list stays for that
#: case and is no longer the whole rule.
NOT_PAYMENT_CARDS = (
    "library", "loyalty", "membership", "member", "boarding", "id", "identity",
    "sim", "key", "room", "door", "access", "badge", "business", "report",
    "score", "student", "staff", "employee", "health", "insurance", "medicare",
    "social", "birthday", "greeting", "memory", "sd", "graphics", "video",
    "sound", "rewards", "reward", "points", "club", "discount", "stamp",
    "punch", "time", "swipe", "game", "gaming", "phone", "index", "tarot",
    "wild",
)

#: Every tier-1 term, kept as one name because four call sites and one drift
#: test read it.
PAYMENT_NAME_SUBSTRINGS = PAYMENT_PAN_TERMS + PAYMENT_CARD_SIDE_TERMS
PAYMENT_NAME_WORDS = ("cvv", "cvv2", "cvc", "cvc2", "csc", "ccv")

#: A `pattern` spelling a 13-to-19 digit run is a card number whatever the
#: field is called. Nothing else common has that shape: a postcode is four to
#: nine, a phone number is seven to fifteen and usually admits separators, and
#: an account number is rarely constrained at all.
_PAN_PATTERN = re.compile(r"\{\s*1[3-9]\s*(,\s*(1[3-9])?\s*)?\}")

#: A PAN SHAPE shown to a HUMAN rather than declared to a validator: four
#: groups of four, or a bare 13-to-19 digit run, in a placeholder or a mask.
#: The mirror of `ksPanShape`.
_PAN_SHAPE_CORE = re.compile(r"^(?:[0-9]{13,19}|[*x•·#]{13,19})$",
                             re.IGNORECASE)


def pan_shape(value) -> bool:
    """Whether this string reads as a card number to the person filling the
    form. An IBAN carries letters, a phone number carries punctuation, and a
    date is too short, so none of them lands here."""
    if not value:
        return False
    text = str(value).strip()
    if not 13 <= len(text) <= 32:
        return False
    return bool(_PAN_SHAPE_CORE.match(text.replace(" ", "").replace("-", "")))


#: Descriptor keys that can NAME a field.
_NAME_KEYS = ("name", "label", "attr_name", "attr_id", "id", "placeholder",
              "aria_label", "title")

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
#: SEPARATORS collapse; LETTERS AND DIGITS OF EVERY SCRIPT survive. The old
#: `[^a-z0-9]+` reduced a Korean 카드번호 or a Japanese カード番号 to the empty
#: string, so the classifier was not missing a Korean word, it could not see
#: any Korean word (re-attack 2, B1).
_NONWORD = re.compile(r"[^\w]+|_+", re.UNICODE)


#: The LATIN combining diacritics, and only those. Stripping every combining
#: mark instead (`unicodedata.combining(c)`) also strips U+3099, the Japanese
#: voiced sound mark, which turns ド into ト and カード番号 into a word that
#: matches nothing. The mirror in `payment.js` strips this same range.
_COMBINING_LATIN = range(0x0300, 0x0370)


def _fold(text: str) -> str:
    """Fold diacritics so `numéro` and `gültig` reduce to the ASCII spellings
    the vocabulary lists, leaving Hangul and kana recomposed and intact."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed
                       if ord(c) not in _COMBINING_LATIN)
    return unicodedata.normalize("NFC", stripped)


def payment_haystack(field: dict) -> str:
    """Every identifier on a descriptor, squashed to space-delimited lowercase
    words. camelCase splits first, so `cardNumber` reads as two words."""
    raw = " ".join(str(field.get(k)) for k in _NAME_KEYS if field.get(k))
    raw = _CAMEL.sub(r"\1 \2", raw)[:400]
    return " " + _NONWORD.sub(" ", _fold(raw.lower())).strip() + " "


def _is_foreign_qualifier(prev: str) -> bool:
    """Does this token read as a word naming an instrument.

    A haystack is every identifier on the control run together, so `id=c_card`
    contributes the token pair `c card` and a rule that took any preceding
    token would read `c` as an instrument. Three guards: at least three
    characters, not `card` repeating from a second identifier, and not already
    a card term."""
    if len(prev) < 3 or prev == "card":
        return False
    if prev in PAYMENT_CARD_QUALIFIERS or prev in TRANSPARENT_QUALIFIERS:
        return False
    return not any(token in prev for token in PAYMENT_NAME_SUBSTRINGS)


def foreign_card_strike(hay: str) -> tuple[str, bool]:
    """Break every `<foreign> card` compound in a spaced haystack.

    `card` becomes a space, which a substring match cannot cross, and the
    qualifier stays where it was: deleting both is what let a `Card number`
    label written alongside an `id=c_card` lose its own `cardnumber` token to
    a cascade. So `library card number` leaves `library number` and matches
    nothing, while `gift card number` and `name on card` survive -- a gift
    card is a payment instrument and `on` is a function word."""
    out: list[str] = []
    foreign = False
    words = hay.strip().split(" ")
    for i, word in enumerate(words):
        if word == "card" and i and _is_foreign_qualifier(words[i - 1]):
            foreign = True
            out.append(" ")
            continue
        out.append(word)
    return "".join(out), foreign


def payment_compact_info(hay: str) -> tuple[str, bool]:
    """The de-spaced haystack with every foreign-instrument card compound
    struck out, plus whether one was struck. Both routes run: the word rule
    reads the qualifier off the spaced string and reaches ANY qualifier, and
    the glued list catches the spellings that carry no space to read."""
    compact, foreign = foreign_card_strike(hay)
    for qualifier in NOT_PAYMENT_CARDS:
        token = qualifier + "card"
        if token in compact:
            compact = compact.replace(token, " ")
            foreign = True
    return compact, foreign


def payment_compact(hay: str) -> str:
    """The de-spaced, struck haystack on its own, for the callers that do not
    need to know whether a foreign instrument was named."""
    return payment_compact_info(hay)[0]


#: Any identifier carrying two letters in a row, which is what "this field has
#: a name" means. It decides whether the SHAPE tiers may speak alone.
_HAS_LETTERS = re.compile(r"[^\W\d_]{2}", re.UNICODE)


def has_naming(hay: str) -> bool:
    """Whether the page NAMED this field. A page that names a field is telling
    the truth about it, so the name governs and the shape tiers below become
    corroboration; a page that names nothing leaves the shape to speak."""
    return bool(_HAS_LETTERS.search(hay))


def is_payment_field(field: dict) -> bool:
    """Classify a field descriptor as payment-shaped.

    MULTI-SIGNAL since the 2026-09-06 re-attack (R3), which walked a live card
    number into `<input name="cardnumber" type="tel" inputmode="numeric">`
    with no gate, because this asked one question: does the page declare an
    `autocomplete` token. A page that wants the gate to fire declares one; the
    pages this exists to defend against are exactly the ones that do not, and
    the field the human reads as "Card number" is a card field whatever the
    markup omits. The rule now re-derives server-side from the identifiers the
    way `is_secret_field` re-derives from the type, so a caller-supplied
    descriptor cannot classify itself harmless by leaving the flag out.

    `inputmode` was considered as a signal and REJECTED. `inputmode="numeric"`
    sits on every quantity box, postcode, OTP field, and page number on the
    web, and a payment gate that fires on all of them is a gate people learn
    to route around. It is corroboration a human can read in the audit record,
    not a classifier input.
    """
    if field.get("payment"):
        return True
    ac = (field.get("autocomplete") or "").strip().lower()
    if any(token in ac for token in PAYMENT_AUTOCOMPLETE):
        return True
    hay = payment_haystack(field)
    foreign = False
    if len(hay) > 2:
        if any(f" {word} " in hay for word in PAYMENT_NAME_WORDS):
            return True
        compact, foreign = payment_compact_info(hay)
        if any(token in compact for token in PAYMENT_NAME_SUBSTRINGS):
            return True
        # The neighbour tier: an expiry or a security code as it is written in
        # some language, which is a card field only where the same form
        # carries a card number. The form-level answer comes from the page,
        # exactly as `secret` comes from the live type.
        if (field.get("form_payment")
                and any(token in compact for token in PAYMENT_NEIGHBOUR_TERMS)):
            return True
    # `<X> card number` where X is not a payment instrument. Not a card field
    # on its own (M4), and still one where the form corroborates it: a declared
    # `cc-*` token or a form the page itself says is payment-shaped.
    if foreign:
        return bool(field.get("form_payment"))
    # THE SHAPE TIERS, which are subordinate to the NAME (M3, M5). A phone
    # field declaring `[0-9]{13,15}`, an IMEI field showing fifteen digits, a
    # tracking-number field showing four groups of four, and a field labelled
    # IBAN holding `**** **** **** ****` all gated as payment on shape alone.
    # `pan_shape` rides the descriptor for the one string that must never
    # travel with it, the field's current VALUE: a masked card number is
    # evidence and putting it in the audit record would leak the thing this
    # gate protects.
    pattern = str(field.get("pattern") or "")
    shaped = bool(
        (pattern and _PAN_PATTERN.search(pattern)
         and ("0-9" in pattern or "\\d" in pattern))
        or field.get("pan_shape")
        or pan_shape(field.get("placeholder")))
    if shaped and (not has_naming(hay) or field.get("form_payment")):
        return True
    # A SPLIT card number. The page supplies the measurements -- how many short
    # numeric boxes belong to this box's run, how many digits they total, what
    # the run leads with, its shortest box, and whether the region names an
    # instrument -- and the rule is applied HERE, the way `pattern` is supplied
    # and read here, so a descriptor cannot classify itself harmless by
    # asserting a verdict.
    size = field.get("pan_group_size")
    digits = field.get("pan_group_digits")
    if not (isinstance(size, int) and isinstance(digits, int)
            and 2 <= size <= 6 and 13 <= digits <= 19):
        return False
    if field.get("pan_group_region") == -1:
        return False
    first = field.get("pan_group_first")
    shortest = field.get("pan_group_min")
    if isinstance(first, int) and first < 4:
        return False
    return not (isinstance(shortest, int) and shortest < 4)


def refuse_secret_write(field: dict, tool: str) -> None:
    """The write refusal, naming only the routes that exist in this build.

    The field test (2026-09-05) caught the previous message promising a
    server-side secrets file no mechanism backs; that route is recorded as
    a future-phase item in PLAN and stays OUT of the error text until it is
    real, because a refusal that names an unpaved road is a broken
    recovery."""
    if not is_secret_field(field):
        return
    label = field.get("name") or field.get("label") or "(unnamed)"
    raise CredentialRefused(
        f'{tool} will not write into {label!r}: it is a secret field '
        f'(password, new-password, or one-time-code), and a credential must '
        f'never pass through the model\'s context. The sanctioned route is '
        f'manage_session(action="handoff"): the run pauses and the human '
        f'types it in the headed window. A completed login can then be '
        f'reused across runs with save_auth_state / load_auth_state '
        f'(storage pack), which move it through a file, never through the '
        f'transcript.')


#: How much of a cookie NAME a sentence in the server's own voice will quote.
#: Chromium accepted a 3,000-character name in gauntlet 2's probe, so the only
#: bound on the old interpolation was the ~4 KB cookie limit.
NAME_QUOTE_CAP = 48


def quoted_name(name: Any) -> str:
    """A cookie or storage NAME, safe to put in a sentence the server writes.

    Cookie names are attacker-controlled on any page the agent visits, and
    gauntlet 2 (M2) put a full prompt injection in one: the auth-expiry line
    interpolated it raw, unbounded and unlabelled, into prose sitting next to
    a note promising that values never entered the transcript. The value did
    not; the name did. Three changes and each closes a different half:
    control characters go (a newline in a name forges a line break in the
    server's own output), the string is CAPPED, and what survives is QUOTED
    and marked as the page's rather than the server's."""
    text = "" if name is None else str(name)
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = " ".join(text.split())
    if len(text) > NAME_QUOTE_CAP:
        text = text[:NAME_QUOTE_CAP] + "..."
    return f'"{text}"'


def classify_name(name: Any) -> str:
    """Classify a cookie or storage NAME as 'credential', 'preference', or
    'unknown'.

    Only 'credential' values enter the vault at observe time. The field test
    (2026-09-05) is the calibration: `dotcom_user=nometalalchemist` is
    sixteen characters and not httpOnly, and vaulting it redacted the
    username out of every GitHub URL for the rest of the session. It is
    identity, not a credential, and it lands here as 'unknown'.
    """
    text = ("" if name is None else str(name)).strip().lower()
    if not text:
        return "unknown"
    # PREFERENCES FIRST, which is what `PREFERENCE_NAME_TOKENS`'s own comment
    # has always said and what the code did in the other order until
    # 2026-09-06 (gauntlet 2 L1). `theme_session`, `lang_token`, and
    # `sidebar_auth` all classify as credentials on the security-first order
    # and get vaulted, which is the over-redaction the 2026-09-05 field fix
    # was written to stop: a five-character preference value in the vault
    # garbles every read that quotes it. An httpOnly cookie is still a
    # credential by construction whatever its name says, and that check runs
    # in `cookie_is_credential` above this one.
    if any(token in text for token in PREFERENCE_NAME_TOKENS):
        return "preference"
    if any(token in text for token in SECURITY_NAME_TOKENS):
        return "credential"
    return "unknown"


def cookie_is_credential(cookie: dict) -> bool:
    """An httpOnly cookie is credential-shaped by construction: the site
    deliberately put it out of scripting's reach. Everything else is judged
    by name."""
    if cookie.get("httpOnly"):
        return True
    return classify_name(cookie.get("name")) == "credential"


def storage_is_credential(key: Any) -> bool:
    """Web storage carries no httpOnly signal, so the name is the whole
    evidence. localStorage is where sites keep UI preferences as often as
    tokens, which is exactly why this is not vault-everything."""
    return classify_name(key) == "credential"


def mask_value(value: Any) -> str:
    """Full mask plus length. Reading a masked value and reading no value are
    different guarantees, and this is the weaker one: it exists for cookie
    and storage METADATA, never for secret form fields, whose values are not
    read at all."""
    text = "" if value is None else str(value)
    return f"[masked, {len(text)} chars]"


def check_unmask(purpose: str) -> None:
    """`unmask=true` is per-call, explicit, audited, and refused under
    strict mode, which is the default."""
    if strict():
        raise CredentialRefused(
            f"unmask=true refused for {purpose}: {ENV_STRICT} is 'strict' "
            f"(the default). Set {ENV_STRICT}=open at launch to permit "
            f"explicit per-call unmasking; the call is audited either way.")


# ------------------------------------------------------------------ vault


def _bounded_replace(text: str, secret: str) -> str:
    """Replace `secret` only where it stands as its own token.

    Hand-rolled rather than regex-driven so no vaulted value is ever
    compiled as a pattern, and so the boundary rule is one readable
    definition instead of an escaping puzzle.
    """
    out = []
    i = 0
    n = len(secret)
    while True:
        hit = text.find(secret, i)
        if hit < 0:
            out.append(text[i:])
            break
        before = text[hit - 1] if hit > 0 else ""
        after = text[hit + n] if hit + n < len(text) else ""
        standalone = (before not in _TOKEN_CHARS
                      and after not in _TOKEN_CHARS)
        out.append(text[i:hit])
        out.append(MASK if standalone else secret)
        i = hit + n
    return "".join(out)


class SecretVault:
    """Process-wide registry of observed secret values.

    The serializer redactor checks it on EVERY outgoing payload and file
    write, which is what makes the guarantee structural: a tool that touches
    a credential and forgets its own redaction is still caught, because the
    observation happened where the value was first read."""

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def observe(self, value: Any) -> None:
        """Vault a value the caller already knows is credential-bearing.

        This is the raw entry point and it stays unconditional (past the
        length floor): a caller that reaches it has classified already. The
        name-aware doors are `observe_cookie` and `observe_storage_item`.
        """
        text = "" if value is None else str(value)
        if len(text) >= MIN_SECRET_LENGTH:
            with self._lock:
                self._values.add(text)

    def observe_cookie(self, cookie: dict) -> bool:
        """Vault a cookie value only if the cookie is credential-shaped.
        Returns whether it was vaulted."""
        if not cookie_is_credential(cookie):
            return False
        self.observe(cookie.get("value", ""))
        return True

    def observe_storage_item(self, key: Any, value: Any) -> bool:
        """Vault a web-storage value only if its key is credential-shaped.
        Returns whether it was vaulted."""
        if not storage_is_credential(key):
            return False
        self.observe(value)
        return True

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        return len(self._values)

    def scrub(self, payload: Any, _depth: int = 0) -> Any:
        """Deep-walk a payload, replacing every occurrence of every observed
        value.

        Long values (>= SUBSTRING_MIN_LENGTH) are searched as raw
        substrings, because a leaked cookie rides inside a sentence at least
        as often as it rides alone. Short ones are matched on token
        boundaries only: the field test watched a vaulted "light" turn
        "highlights" into "high[REDACTED:secret]s" across a whole session,
        which is the redactor eating the reading feature it exists to
        protect.
        """
        if _depth > 32 or not self._values:
            return payload
        if isinstance(payload, str):
            out = payload
            for secret in self._values:
                if secret not in out:
                    continue
                if len(secret) >= SUBSTRING_MIN_LENGTH:
                    out = out.replace(secret, MASK)
                else:
                    out = _bounded_replace(out, secret)
            return out
        if isinstance(payload, dict):
            return {k: self.scrub(v, _depth + 1) for k, v in payload.items()}
        if isinstance(payload, (list, tuple)):
            scrubbed = [self.scrub(v, _depth + 1) for v in payload]
            return scrubbed if isinstance(payload, list) else tuple(scrubbed)
        return payload


#: The process vault. One instance; the serializer redactor closes over it.
VAULT = SecretVault()


def redactor(payload: Any) -> Any:
    """Installed into `envelope.set_redactor` at server configure time, so it
    runs on every outgoing payload and every file write (DESIGN 5.3: the
    serializer is the ONE place redaction can be enforced globally)."""
    return VAULT.scrub(payload)
