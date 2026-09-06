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
import threading
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


def is_payment_field(field: dict) -> bool:
    if field.get("payment"):
        return True
    ac = (field.get("autocomplete") or "").strip().lower()
    return any(token in ac for token in PAYMENT_AUTOCOMPLETE)


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
