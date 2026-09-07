"""Axis B: the CONSENT SCOPE, and the ladder gates consult before asking.

DESIGN 5.4a. The defect this module closes, stated once: the policy grade
and the gate table were two orthogonal systems that never consulted each
other. `policy/readonly.py` decided which tools EXIST; `policy/gates.py`
decided which actions ASK a human; and the gate table was identical at every
grade. Unlocking acting bought the tools and bought nothing at all in the
approval budget, so a search box and a bank transfer raised the same prompt
with the same sentence.

**A grade stops being a capability switch and becomes a CONSENT
DECLARATION.** Granting one is standing approval for every ordinary
in-grade action inside it, and gates fire on EXCEEDS-GRADE events only.

Two axes, kept deliberately separate so the provable property survives:

- **Axis A, TOOL PRESENCE** (`policy/readonly.py`). Launch-time, enforced by
  ABSENCE. Untouched by anything here. Nothing in this module changes which
  tools register, so the absence claim is exactly as strong as it was.
- **Axis B, CONSENT SCOPE** (this module). Launch-time, applies only when
  acting is allowed. Decides which consequential classes the human
  pre-approved. It changes no tool's presence; it changes what asks.

**Launch-time for the same reason the grade is.** A runtime toggle would let
an injected page widen its own consent, and MCP 2026-07-28 forbids varying
the surface per connection anyway. `apply()` is callable only from
`server.configure`, the same static tree scan that guards `readonly.apply()`
covers it, and no tool argument, gate class, or elicitation answer can reach
the scope, the preauth table, or the sensitive-origin list.

**The three tiers, and the tier is a property of the ACTION CLASS, never of
an input string.** The author's complaint was that "always allow" is useless
because input strings vary; a class is the unit that does not vary.

    TIER 0  in-grade, never gates. Reads, navigation, clicks, ordinary
            typing, and a QUERY-SHAPED form submission (see `query_shaped`).
    TIER 1  grade-cleared: gates under `research`, silent under `full`, and
            preauthorizable per origin at the settings surface.
    TIER 2  irreducible: gates under every scope. No grade, no preauth, and
            no in-session grant clears one.

**What a clearance clears and what it does not.** A cleared class skips the
ASK. It never skips the TOCTOU re-validation: `engine.approve` still builds
a grant record and still runs `gates.verify_execute()`, so a page that swaps
the control between resolve and execute still gets `TARGET_CHANGED`. A
clearance is permission to skip the question, never permission to skip the
verification.

**Audit honesty is non-negotiable.** Every grant record carries
`cleared_by`, and it distinguishes four causes: `"human"` (an elicitation
accept), `"grade"` (in-grade under the scope in force), `"preauth"` (a
launch-time pre-authorization), `"grant"` (an in-session standing grant). A
trail that recorded a grade-cleared action as though a human answered would
be a false record, and the audit's own framing cannot survive one.
"""

from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

from ..errors import BadParams
from . import origins, readonly, sandbox

# --------------------------------------------------------------- the scopes

#: The consent scopes, widest last. `research` is the proposed default when
#: acting is unlocked: a stranger's first bad surprise is the one that
#: uninstalls the product, and every consequential class still asks there.
SCOPES: tuple[str, ...] = ("research", "full")

#: THE DEFAULT when acting is allowed, deliberately one constant, the same
#: shape `readonly.DEFAULT_GRADE` uses. Both values are fully built.
DEFAULT_SCOPE = "research"

ENV_SCOPE = "KS4WEB_CONSENT"
ENV_PREAUTH = "KS4WEB_PREAUTH"
ENV_SENSITIVE_ORIGINS = "KS4WEB_SENSITIVE_ORIGINS"

#: The in-session "remember for 30 minutes" answer. On by default (author
#: ruling 2026-09-07); an off value drops the elicitation schema back to the
#: bare accept/decline the build shipped with, which is the kill switch if a
#: client renders the schema'd prompt badly.
ENV_REMEMBER = "KS4WEB_REMEMBER"

# ------------------------------------------------------------- the tiering

#: TIER 2. Gates under every scope. Nothing in this set is preauthorizable
#: and nothing in it is grantable in-session; `apply()` refuses to START if
#: one is named in KS4WEB_PREAUTH, rather than silently dropping the entry.
IRREDUCIBLE: frozenset[str] = frozenset({
    "payment_form",
    "credential_submit",
    "broadcast_submit",
    "destructive_submit",
    "legal_assent",
    "navigation_offlist",
    "action_offlist",
    "budget_reset",
    "age_gate_detected",
    "sensitive_origin",
    "credential_injection",
})

#: TIER 1 classes a human may pre-authorize per origin at the settings
#: surface. `evaluate_script`, `storage_load`, and `clipboard_read` are here
#: and NOT in GRADE_CLEARED: no scope widens them, a human names an origin
#: or they keep asking.
PREAUTHORIZABLE: frozenset[str] = frozenset({
    "form_submit",
    "file_upload",
    "download_to_disk",
    "storage_clear",
    "dialog_accept",
    "evaluate_script",
    "storage_load",
    "clipboard_read",
})

#: Class -> the scopes that clear it by grade alone. A class absent here is
#: never cleared by a scope; a class present is cleared only when its own
#: conditions hold too (see `_grade_conditions`).
GRADE_CLEARED: dict[str, tuple[str, ...]] = {
    "form_submit": ("full",),
    "file_upload": ("full",),
    "download_to_disk": ("research", "full"),
    "storage_clear": ("full",),
    "dialog_accept": ("full",),
}

#: What `decide()` returns. `ASK_LIVE_ONLY` is Tier 2: it asks a human where
#: one can answer and REFUSES where none can, and no configuration changes
#: that. `ASK` is Tier 1: it asks, and its refusal names the preauth route.
IN_GRADE = "in_grade"
PREAUTH = "preauth"
GRANT = "grant"
ASK = "ask"
ASK_LIVE_ONLY = "ask_live_only"

#: The audit's `cleared_by` label per outcome. `"human"` is set by the
#: elicitation path, never here.
_CLEARED_BY = {IN_GRADE: "grade", PREAUTH: "preauth", GRANT: "grant"}


class Decision:
    """One consent verdict: the outcome, the audit label, and the reason a
    human or a log reader needs to understand it."""

    __slots__ = ("outcome", "cleared_by", "reason", "action_class")

    def __init__(self, outcome: str, action_class: str, reason: str) -> None:
        self.outcome = outcome
        self.action_class = action_class
        self.reason = reason
        self.cleared_by = _CLEARED_BY.get(outcome)

    @property
    def clears(self) -> bool:
        return self.outcome in (IN_GRADE, PREAUTH, GRANT)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Decision({self.outcome!r}, {self.action_class!r}, "
                f"{self.reason!r})")


# ------------------------------------------------------------ the scope state

_scope: str | None = None
_source: str = "default"


def parse_scope(value) -> str:
    """Resolve a KS4WEB_CONSENT value to a scope.

    An EMPTY value fails CLOSED to the narrowest scope, and an unrecognized
    one refuses to START. Both follow `readonly.parse_allow`'s discipline for
    the same reason: silently widening a consent scope because of a typo is
    the exact inversion of the failure DESIGN 8.3 names."""
    text = ("" if value is None else str(value)).strip().lower()
    if not text:
        return SCOPES[0]                      # empty NEVER widens
    if text in SCOPES:
        return text
    raise BadParams(
        f"unknown {ENV_SCOPE} value {value!r}: the consent scopes are "
        f"{list(SCOPES)}. 'research' pre-approves reading, navigating, "
        f"clicking, typing, and query-shaped form submission; 'full' also "
        f"pre-approves ordinary form submission, sandboxed uploads and "
        f"downloads, storage clears, and unrecognized dialog accepts. "
        f"Refusing to start rather than guessing, because guessing here "
        f"would silently widen a consent scope.")


def apply(value: str | None = None) -> str | None:
    """Resolve and record the consent scope ONCE, before registration.

    STARTUP ONLY. The only sanctioned caller is `server.configure`; the
    read-only invariant test scans the tree for any other call site, because
    a second caller is a runtime consent toggle wearing a disguise.

    Returns None when the server is read-only: Axis B is INERT on Axis A's
    read-only setting, because the mutating tools are absent and there is
    nothing to consent to."""
    global _scope, _source
    _reset_runtime_state()
    if readonly.active():
        _scope = None
        _source = "read-only (Axis B inert)"
        _parse_preauth()          # still parsed: a typo must refuse to start
        _parse_sensitive()
        return None
    if value is not None:
        _scope = parse_scope(value)
        _source = "cli"
    else:
        env = os.environ.get(ENV_SCOPE)
        if env is not None:
            _scope = parse_scope(env)
            _source = ENV_SCOPE
        else:
            _scope = DEFAULT_SCOPE
            _source = "default"
    _parse_preauth()
    _parse_sensitive()
    return _scope


def scope() -> str | None:
    return _scope


def source() -> str:
    """What decided the scope in force: 'cli', the env var name, 'default',
    or the read-only note. Surfaced in describe() so a surprising posture
    names its own cause."""
    return _source


def active() -> bool:
    """Whether Axis B decides anything in this process. False under every
    read-only grade."""
    return _scope is not None


# --------------------------------------------------- launch-time preauth

#: One parsed KS4WEB_PREAUTH entry. `expires` is monotonic and absent means
#: "for the life of this process"; nothing here is ever written to disk,
#: because a grant that survives a restart the human did not intend is not a
#: grant they gave.
class _Preauth:
    __slots__ = ("action_class", "pattern", "expires", "spelling")

    def __init__(self, action_class, pattern, expires, spelling):
        self.action_class = action_class
        self.pattern = pattern
        self.expires = expires
        self.spelling = spelling


_preauth: tuple[_Preauth, ...] = ()
_sensitive: tuple[str, ...] = ()

_TTL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_ttl(text: str) -> float:
    unit = text[-1]
    if unit not in _TTL_UNITS or not text[:-1].isdigit():
        raise BadParams(
            f"{ENV_PREAUTH}: {text!r} is not a time-to-live. A ttl is a "
            f"whole number followed by s, m, h, or d, for example '30m' or "
            f"'8h'. Omit it entirely for the life of this process. Refusing "
            f"to start rather than guessing.")
    seconds = int(text[:-1]) * _TTL_UNITS[unit]
    if seconds <= 0:
        raise BadParams(
            f"{ENV_PREAUTH}: a ttl of {text!r} is zero or negative, which "
            f"would authorize nothing while reading as though it authorized "
            f"something. Refusing to start.")
    return float(seconds)


def _check_pattern(pattern: str, whole: str) -> str:
    """An origin pattern, validated STRICTLY in both directions.

    A misspelled CLASS fails safe on its own (nothing matches it), but a
    well-spelled class with a sloppily-parsed origin is how a parser widens
    consent to every origin by accident. So: `*` must be spelled exactly, a
    bare host may not carry a colon (`localhost:3000` is a host:port nobody's
    matcher reads as an origin, and accepting it silently would authorize
    NOTHING while reading as though it authorized something), and a path,
    a query, or whitespace refuses."""
    text = pattern.strip()
    if not text:
        raise BadParams(
            f"{ENV_PREAUTH}: the entry {whole!r} names no origin. The form "
            f"is <class>@<origin>[:<ttl>], for example "
            f"'evaluate_script@localhost' or 'storage_load@github.com'.")
    if text == "*":
        return text
    lowered = text.lower()
    if "://" in lowered:
        parts = urlparse(lowered)
        if not parts.scheme or not parts.hostname:
            raise BadParams(
                f"{ENV_PREAUTH}: {pattern!r} looks like a full origin and "
                f"names no scheme or no host. A full origin is written "
                f"'https://example.com' or 'https://example.com:8443'.")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise BadParams(
                f"{ENV_PREAUTH}: {pattern!r} carries a path or a query. A "
                f"pre-authorization names an ORIGIN, never a URL: a path "
                f"glob would let one entry match every site that happens to "
                f"serve that path. Refusing to start.")
        return lowered
    if any(ch.isspace() for ch in lowered) or "/" in lowered:
        raise BadParams(
            f"{ENV_PREAUTH}: {pattern!r} is not an origin pattern. The "
            f"forms are a bare host ('github.com'), a wildcard "
            f"('*.example.com'), a full origin ('https://example.com:8443'), "
            f"or '*' spelled exactly for every origin.")
    if ":" in lowered:
        raise BadParams(
            f"{ENV_PREAUTH}: {pattern!r} carries a port with no scheme, and "
            f"the origin matcher reads a port only on a FULL origin, so this "
            f"entry would match nothing while reading as though it "
            f"authorized something. Write it as "
            f"'https://{lowered}' instead. Refusing to start.")
    return lowered


def _parse_preauth() -> None:
    """KS4WEB_PREAUTH -> the pre-authorization table, or refuse to start.

    Why this is legitimate where an in-session "always allow" would not be:
    it is a human action at a human surface, the same settings panel that
    already carries "Allow this server to click and type". Nothing in-session
    can reach it, no tool argument can set it, no injected page instruction
    can write it, and no model can read a value back and echo it. It
    inherits the read-only mode's entire safety property by construction,
    and it is the answer for a client that receives an elicitation and does
    not render it."""
    global _preauth
    raw = os.environ.get(ENV_PREAUTH, "")
    entries: list[_Preauth] = []
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        if "@" not in entry:
            raise BadParams(
                f"{ENV_PREAUTH}: {entry!r} is not a pre-authorization. The "
                f"form is <class>@<origin>[:<ttl>], for example "
                f"'evaluate_script@localhost', 'storage_load@github.com', "
                f"or 'download_to_disk@*:8h'.")
        klass, rest = entry.split("@", 1)
        klass = klass.strip().lower()
        ttl = None
        # A ttl is a trailing ':<number><unit>'; the unit is REQUIRED, which
        # is what keeps ':8443' reading as the port it is.
        if ":" in rest:
            head, tail = rest.rsplit(":", 1)
            tail = tail.strip()
            if tail and tail[-1].lower() in _TTL_UNITS and tail[:-1].isdigit():
                ttl = _parse_ttl(tail.lower())
                rest = head
        if klass in IRREDUCIBLE:
            raise BadParams(
                f"{ENV_PREAUTH}: {klass!r} cannot be pre-authorized, so this "
                f"server is refusing to start rather than starting with an "
                f"entry that does nothing. Paying, submitting a credential, "
                f"sending something that reaches other people, deleting, "
                f"accepting legal terms, acting off an allowlist, and "
                f"resetting the budgets always stop and ask a human, at "
                f"every consent scope and under every setting. Remove "
                f"{klass!r} from {ENV_PREAUTH}.")
        if klass not in PREAUTHORIZABLE:
            raise BadParams(
                f"{ENV_PREAUTH}: {klass!r} is not an action class. The "
                f"pre-authorizable classes are "
                f"{sorted(PREAUTHORIZABLE)}. Refusing to start rather than "
                f"dropping the entry, because a silently-dropped entry looks "
                f"exactly like one that is working.")
        pattern = _check_pattern(rest, entry)
        entries.append(_Preauth(
            klass, pattern,
            None if ttl is None else time.monotonic() + ttl, entry.strip()))
    _preauth = tuple(entries)


def _parse_sensitive() -> None:
    """KS4WEB_SENSITIVE_ORIGINS -> origins the human always wants asked about.

    THE SERVER HOLDS NO OPINION ABOUT CONTENT. There is no topic classifier
    here and none is planned: any list of "risky topics" this server shipped
    would impose one person's values on every user, would gate a nuclear-
    weapons and DPRK research corpus on day one, and would be trivially
    defeated anyway. What ships instead is this list, which the human writes,
    plus the page's own declaration (`age_gate_detected`), which relays a
    claim the PAGE made rather than a judgment the server made."""
    global _sensitive
    raw = os.environ.get(ENV_SENSITIVE_ORIGINS, "")
    _sensitive = tuple(p.strip().lower() for p in raw.split(",") if p.strip())


def preauth_entries() -> list[dict]:
    """The active pre-authorizations, for `manage_session(status)`. Class and
    origin PATTERN only; there is no value here to leak and never will be."""
    now = time.monotonic()
    return [{"action_class": e.action_class, "origin": e.pattern,
             "expires_in_s": (None if e.expires is None
                              else max(0, round(e.expires - now)))}
            for e in _preauth if e.expires is None or e.expires > now]


def sensitive_origins() -> list[str]:
    return list(_sensitive)


def _origin_matches(pattern: str, url: str | None) -> bool:
    if not url:
        return False
    if pattern == "*":
        return True
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    return origins._matches(pattern, parts)


def _preauth_for(action_class: str, url: str | None) -> _Preauth | None:
    now = time.monotonic()
    for entry in _preauth:
        if entry.action_class != action_class:
            continue
        if entry.expires is not None and entry.expires <= now:
            continue
        if _origin_matches(entry.pattern, url):
            return entry
    return None


def is_sensitive_origin(url: str | None) -> bool:
    return any(_origin_matches(p, url) for p in _sensitive)


# ------------------------------------------------ in-session standing grants

#: The in-session "remember this for 30 minutes" answer (author ruling,
#: 2026-09-07). The scope of a grant is (origin, action CLASS, ttl) and
#: never a raw string, never a target fingerprint, never a URL with a query,
#: which is what makes it a consent unit rather than the string-matching
#: "always allow" the author correctly called useless.
GRANT_TTL_S = 1800.0

#: A hard ceiling nothing may exceed, and the grants die with the process
#: whatever it says.
GRANT_MAX_TTL_S = 3600.0

_grants: dict[tuple[str, str], float] = {}
_grants_lock = threading.Lock()


def remember_enabled() -> bool:
    """Whether the elicitation prompt offers the 30-minute remember answer.
    The kill switch exists because a schema'd elicitation renders differently
    on every client and the field test already found one client that renders
    these badly."""
    value = os.environ.get(ENV_REMEMBER, "on").strip().lower()
    return value not in ("0", "false", "off", "no")


def grantable(action_class: str | None) -> bool:
    """Whether a human may attach 'remember this' to THIS prompt. Tier 2 is
    never grantable, so the money, credential, broadcast, deletion, legal,
    off-list, and budget prompts keep the bare accept/decline they ship
    with."""
    return bool(action_class) and action_class not in IRREDUCIBLE \
        and remember_enabled()


def origin_of(url: str | None) -> str | None:
    """The scheme+host+port an in-session grant is scoped to. A grant for
    origin A never clears the same class on origin B, so this is the whole
    key and the query string is deliberately not in it."""
    if not url:
        return None
    try:
        parts = urlparse(url)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    netloc = parts.hostname.lower()
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme.lower()}://{netloc}"


def add_grant(action_class: str, url: str | None,
              ttl_s: float = GRANT_TTL_S) -> dict | None:
    """Record a human's "remember this for 30 minutes" answer.

    CALLERS: the confirmation plumbing only, and only after a human ACCEPTED
    with the remember answer set. Tier 2 refuses here as well as at the
    prompt, so a client that invents the field cannot mint one."""
    if action_class in IRREDUCIBLE:
        return None
    origin = origin_of(url)
    if not origin:
        return None
    ttl = min(float(ttl_s), GRANT_MAX_TTL_S)
    with _grants_lock:
        _grants[(action_class, origin)] = time.monotonic() + ttl
    return {"action_class": action_class, "origin": origin,
            "expires_in_s": int(ttl)}


def _grant_for(action_class: str, url: str | None) -> bool:
    origin = origin_of(url)
    if not origin:
        return False
    key = (action_class, origin)
    with _grants_lock:
        expires = _grants.get(key)
        if expires is None:
            return False
        if expires <= time.monotonic():
            _grants.pop(key, None)
            return False
    return True


def clear_grants() -> int:
    """Drop every in-session grant. Called on session close: a grant is
    scoped to the session the human answered in."""
    with _grants_lock:
        count = len(_grants)
        _grants.clear()
    return count


def grants() -> list[dict]:
    now = time.monotonic()
    with _grants_lock:
        rows = [{"action_class": k[0], "origin": k[1],
                 "expires_in_s": max(0, round(v - now))}
                for k, v in _grants.items() if v > now]
    return sorted(rows, key=lambda r: (r["action_class"], r["origin"]))


# ----------------------------------------------- the confirmation channel

#: A cancel returned faster than this is a machine answering, not a human
#: reading. S8 measured a headless client auto-cancelling `elicitation/create`
#: in 0.0 s.
FAST_CANCEL_S = 0.5

#: Two of them before the session is called unattended, so one fast decline
#: by a human with a hair trigger does not change the posture.
UNATTENDED_AFTER = 2

_fast_cancels = 0
_no_channel = False


def note_confirmation(outcome: str, elapsed_s: float) -> None:
    """Record what the confirmation channel did. CALLERS: `confirm.attempt`.

    DETECTION, NEVER ASSUMPTION. The flag says a human could not be reached,
    and it NEVER widens consent: it only changes what happens after a
    refusal, and for Tier 2 what happens is still a refusal."""
    global _fast_cancels, _no_channel
    if outcome == "accepted":
        _fast_cancels = 0
        _no_channel = False
        return
    if outcome == "no_channel":
        _no_channel = True
        return
    if outcome in ("cancelled", "declined") and elapsed_s < FAST_CANCEL_S:
        _fast_cancels += 1


def unattended() -> bool:
    """Whether this process has evidence that no human is answering."""
    return _no_channel or _fast_cancels >= UNATTENDED_AFTER


def unattended_reason() -> str | None:
    if _no_channel:
        return ("the client advertises no confirmation channel, so a "
                "confirmation prompt has nowhere to go")
    if _fast_cancels >= UNATTENDED_AFTER:
        return (f"{_fast_cancels} confirmation prompts were cancelled in "
                f"under {FAST_CANCEL_S}s, which is a client answering rather "
                f"than a human reading")
    return None


def _reset_runtime_state() -> None:
    global _fast_cancels, _no_channel
    _fast_cancels = 0
    _no_channel = False
    clear_grants()


# ------------------------------------------------------- the query-shaped rule

#: The form-census fields the projection computes beside `ksFormPayment`.
#: Membership follows `form.elements`, not `querySelectorAll`: a field
#: carrying `form="pay"` submits with that form from anywhere in the
#: document, and reading only descendants was a one-attribute bypass the
#: payment work already found and fixed.
CENSUS_FIELDS = ("method", "secret", "payment", "has_file", "enctype",
                 "field_count", "textarea", "recipient", "assent",
                 "submitter", "action")


def census_of(desc: dict | None) -> dict:
    """The form census off a descriptor, or an empty dict. The delegate's
    census wins where a click is delegated, because a `<label>` parked
    outside the `<form>` tag still submits the form its control belongs
    to."""
    if not isinstance(desc, dict):
        return {}
    census = desc.get("form_census")
    if isinstance(census, dict) and census:
        return census
    delegate = desc.get("activates")
    if isinstance(delegate, dict):
        census = delegate.get("form_census")
        if isinstance(census, dict):
            return census
    return {}


def query_shaped(census: dict) -> bool:
    """Is this submission query-shaped, and therefore Tier 0?

    SPEC-BACKED, NOT HEURISTIC, and that is the whole reason this rule is
    defensible. RFC 9110 section 9.2.1 defines GET as a SAFE method: a GET
    form submission is by specification not supposed to cause side effects
    on the server, so a page that publishes a GET form has made a claim
    about its own operation and this server takes it at its word.

    All five must hold:

    1. the effective method is GET;
    2. no field in the form classifies secret;
    3. no field classifies payment and the form is not payment-shaped;
    4. the form carries no `<input type=file>`;
    5. the enctype is not multipart/form-data.

    A search box, a library catalog query, a database filter, a date-range
    picker, and an academic advanced-search panel are all GET, all in-grade,
    and all silent, which is the majority of the routine-research prompts
    this whole redesign exists to remove.

    THE HONEST LIMIT, and it ships in the docs: a site that implements its
    search over POST still gates under `research`. That is the site making a
    claim about its own operation and this server believing it, which is the
    correct direction to be wrong in.

    THE RULE IS AN ADMISSION TEST, NEVER AN EXEMPTION. A GET checkout form
    still gates, because payment is classified before this is ever consulted
    and a Tier 2 class never reaches here.

    THE RESIDUAL, NAMED RATHER THAN PAPERED OVER. Everywhere else in this
    build, page-authored text may classify UP into a gate and may never
    classify DOWN out of one. This rule is the exception: `method` is page
    authored and reading it as GET is a DOWN classification. A form declaring
    `method="get"` whose own `submit` listener rewrites the method, or which
    posts by `fetch()` from that listener, is Tier 0 on the declaration and
    something else in fact.

    Three things bound it and none of them closes it. The declaration is what
    the site published about itself, so a site doing this is lying about its
    own markup rather than exploiting a parser. The write paths that focus a
    field re-take the census at the write (`recheck_at_write`), so a flip
    visible at focus time is caught and re-classified. And nothing Tier 2 can
    ride it: payment, credentials, sends, deletions, and assent are all
    classified before the method is consulted, so what a successful flip buys
    is an unprompted ORDINARY POST, which is exactly what the `full` scope
    grants anyway. Under `research` it is a real gap of one prompt."""
    if not census:
        return False
    if (census.get("method") or "").strip().upper() != "GET":
        return False
    if census.get("secret") or census.get("payment"):
        return False
    if census.get("has_file"):
        return False
    enctype = (census.get("enctype") or "").strip().lower()
    return "multipart/form-data" not in enctype


# ------------------------------------------------------------ grade clearing

def _grade_conditions(action_class: str, *, url: str | None,
                      desc: dict | None, dest_path: str | None,
                      origin_verdict: str) -> tuple[bool, str]:
    """The per-class conditions a scope clearance ALSO requires.

    Returns (cleared, reason). A class in GRADE_CLEARED whose conditions do
    not hold falls through to the ask, which is why the table alone is never
    the answer."""
    if action_class == "form_submit":
        return True, "an ordinary form submission under full consent"
    if action_class == "storage_clear":
        return True, "clearing site storage under full consent"
    if action_class == "download_to_disk":
        # DEMOTED (spec 2, download_to_disk). With a sandbox configured the
        # containment check, the downloads budget, and the audit trail
        # already bound the harm, and the gate's friction cost is the
        # highest in the table for a research user. With NO sandbox
        # configured the destination is anywhere on the disk, so it still
        # asks.
        if not sandbox.active():
            return False, ("no download sandbox is configured, so the "
                           "destination is anywhere on this disk")
        if dest_path and not sandbox.contains(dest_path):
            return False, ("the destination resolves outside "
                           f"{sandbox.ENV_VAR}")
        return True, ("the destination is inside the configured "
                      f"{sandbox.ENV_VAR} sandbox")
    if action_class == "file_upload":
        if not sandbox.active():
            return False, (f"no {sandbox.ENV_VAR} sandbox is configured, so "
                           "the source file could be any file on this disk")
        if dest_path and not sandbox.contains(dest_path):
            return False, (f"the source resolves outside {sandbox.ENV_VAR}")
        if not origins.active()["allow"]:
            return False, ("no origin allowlist is configured, so the "
                           "destination origin is unconstrained")
        if origin_verdict != "allowed":
            return False, "the destination origin is not on the allowlist"
        return True, ("the source is inside the sandbox and the destination "
                      "origin is on the allowlist")
    if action_class == "dialog_accept":
        # `dialogs.gate_reason_for_accept` already returned None for an
        # `alert`, so anything reaching here is a confirm/prompt/beforeunload.
        # A message matching a destructive shape is escalated to Tier 2
        # before this is consulted; what is left is the unrecognized case.
        if not desc:
            # ARMING an accept for a dialog that has not opened. There is no
            # message to have been unrecognized, so nothing here is the
            # unrecognized case and a scope cannot clear it: this would be
            # standing consent for whatever wording opens next.
            return False, ("the dialog has not opened yet, so its message is "
                           "not known")
        if not origins.active()["allow"]:
            return False, ("no origin allowlist is configured, and the "
                           "message is one this server does not recognize")
        if origin_verdict != "allowed":
            return False, "the page is not on the origin allowlist"
        return True, ("the dialog message matches no destructive shape and "
                      "the page is on the allowlist")
    return False, ""


# --------------------------------------------------------------- the verdict

def decide(action_class: str | None, *, url: str | None = None,
           desc: dict | None = None, dest_path: str | None = None,
           origin_verdict: str = "allowed", kind: str = "act",
           age_declared: bool = False) -> Decision:
    """THE consent verdict for one gated action, consulted by
    `engine.approve` immediately before it would ask a human.

    ORDER IS THE CONTRACT and it runs most-protective first. Every branch
    that can REFUSE a clearance comes before every branch that can grant one,
    which is what makes the ladder readable top to bottom:

    1. read-only: Axis B decides nothing and the existing ladder stands;
    2. a sensitive origin the human named makes any ACT there Tier 2;
    3. a page's own adult-only declaration does the same;
    4. a Tier 2 class asks, always, and refuses where no human can answer;
    5. an off-list origin clears nothing, whatever else is configured;
    6. a dialog whose own message describes something consequential is
       Tier 2, because page text may classify up and never down;
    7. a query-shaped GET submission is Tier 0;
    8. the scope in force clears the class IF its own conditions hold;
    9. a launch-time pre-authorization for this class AND this origin;
    10. an in-session standing grant for this class AND this origin;
    11. otherwise, ask."""
    if not action_class:
        return Decision(IN_GRADE, "", "no gated class")
    if not active():
        # Read-only: Axis B is inert and the existing ladder stands exactly
        # as it was. Nothing here clears anything.
        return Decision(ASK, action_class,
                        "the server is read-only, so consent scope decides "
                        "nothing")

    if kind in ("act", "download") and is_sensitive_origin(url):
        return Decision(
            ASK_LIVE_ONLY, action_class,
            f"this origin is on {ENV_SENSITIVE_ORIGINS}, the list of sites "
            f"you asked to always be consulted about")

    if kind in ("act", "download") and age_declared:
        # The PAGE declared this about itself and the server relays the
        # claim. No judgment of content happens anywhere in this build.
        return Decision(ASK_LIVE_ONLY, action_class,
                        "the page declares itself adult-only")

    if action_class in IRREDUCIBLE:
        return Decision(ASK_LIVE_ONLY, action_class,
                        "this class always asks a human")

    if origin_verdict == "off-list":
        # AN ALLOWLIST THE HUMAN CONFIGURED IS NOT CLEARED BY ANYTHING HERE.
        # `navigation_offlist` and `action_offlist` are Tier 2 already, but
        # they are only ASSIGNED when the action carries no class of its own
        # (`engine.approve` step 3), so `evaluate_script` on an off-list
        # origin arrives here wearing its own class. Without this line a
        # `evaluate_script@*` pre-authorization would quietly clear the
        # allowlist for that class, which is not what a human who wrote both
        # settings asked for: the whole point of the allowlist is that it is
        # the narrower of the two.
        return Decision(ASK_LIVE_ONLY, action_class,
                        f"this origin is outside {origins.ENV_ALLOW}, the "
                        f"allowlist you configured")

    if action_class == "dialog_accept" and (desc or {}).get(
            "dialog_destructive"):
        # The page wrote the message and OK commits whatever it does next.
        # Page-authored text may classify UP into a gate and may never
        # classify DOWN out of one, which is the payment classifier's rule
        # applied to a dialog.
        return Decision(ASK_LIVE_ONLY, action_class,
                        "the dialog's own message describes something "
                        "consequential")

    census = census_of(desc)
    if action_class == "form_submit" and query_shaped(census):
        return Decision(
            IN_GRADE, action_class,
            "the form's method is GET and it carries no secret, payment, or "
            "file field, so RFC 9110 calls the submission safe")

    scopes = GRADE_CLEARED.get(action_class, ())
    if _scope in scopes:
        cleared, why = _grade_conditions(
            action_class, url=url, desc=desc, dest_path=dest_path,
            origin_verdict=origin_verdict)
        if cleared:
            return Decision(IN_GRADE, action_class,
                            f"consent scope {_scope!r}: {why}")

    entry = _preauth_for(action_class, url)
    if entry is not None:
        return Decision(PREAUTH, action_class,
                        f"pre-authorized at launch by {ENV_PREAUTH} entry "
                        f"{entry.spelling!r}")

    if _grant_for(action_class, url):
        return Decision(GRANT, action_class,
                        "a human allowed this class on this origin earlier "
                        "in this session and asked to be remembered")

    return Decision(ASK, action_class, "this class asks under the consent "
                                       f"scope {_scope!r}")


def describe() -> dict:
    """What the consent posture permits, for `manage_session(status)`.

    States the LIMIT alongside the permission, the same honesty grammar
    `readonly.describe()` uses: a surface that lists what is allowed without
    listing what still asks teaches the wrong lesson."""
    if not active():
        return {
            "consent_scope": None,
            "decided_by": _source,
            "note": ("the server is read-only, so consent scope decides "
                     "nothing: the mutating tools are absent and there is "
                     "nothing to consent to."),
        }
    out = {
        "consent_scope": _scope,
        "decided_by": _source,
        "always_asks": sorted(IRREDUCIBLE),
        "preauthorizable": sorted(PREAUTHORIZABLE),
        "preauthorized": preauth_entries(),
        "remembered_this_session": grants(),
        "sensitive_origins": sensitive_origins(),
        "unattended": unattended(),
    }
    reason = unattended_reason()
    if reason:
        out["unattended_because"] = reason
    return out
