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
MIN_SECRET_LENGTH = 4

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
    """The write refusal, with the two sanctioned routes named."""
    if not is_secret_field(field):
        return
    label = field.get("name") or field.get("label") or "(unnamed)"
    raise CredentialRefused(
        f'{tool} will not write into {label!r}: it is a secret field '
        f'(password, new-password, or one-time-code), and a credential must '
        f'never pass through the model\'s context. The two sanctioned routes: '
        f'a server-side secrets file, where the value is substituted at '
        f'execution time; or manage_session(action="handoff"), where the run '
        f'pauses and the human types it in the headed window.')


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
        text = "" if value is None else str(value)
        if len(text) >= MIN_SECRET_LENGTH:
            with self._lock:
                self._values.add(text)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        return len(self._values)

    def scrub(self, payload: Any, _depth: int = 0) -> Any:
        """Deep-walk a payload, replacing every occurrence of every observed
        value. Strings are searched as substrings, because a leaked cookie
        rides inside a sentence at least as often as it rides alone."""
        if _depth > 32 or not self._values:
            return payload
        if isinstance(payload, str):
            out = payload
            for secret in self._values:
                if secret in out:
                    out = out.replace(secret, MASK)
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
