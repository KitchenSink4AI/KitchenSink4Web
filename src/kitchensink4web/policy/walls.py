"""Which bot-mitigation vendor refused this request, and how we know.

DETECTION AND HONEST REPORTING ONLY. Nothing here defeats, bypasses, or works
around a wall, and nothing here ever will (DESIGN 5.8: fingerprint spoofing,
`navigator.webdriver` patching, CAPTCHA solving, and stealth modes are out
permanently). The entire purpose of naming the vendor is to give the user a
better sentence than "the page was empty": which wall it was, what evidence
said so, and the reference number the site owner will ask for.

THE GOVERNING DISTINCTION, and the one thing to get right before adding a
vendor. Every one of these products sets headers and cookies on ORDINARY
traffic, not only on blocks. `server: cloudflare`, `_abck`, `x-datadome:
protected`, `X-Iinfo`, and every `_px*` cookie ride on perfectly normal 200
responses; a matcher on any of them would refuse a large share of the web.
Signals are therefore sorted into three tiers and the tier is the contract:

    BLOCK-ONLY   fires alone. The vendor emits it only when refusing.
    CORROBORATING fires only alongside a refusing status.
    NEVER        identifies the vendor; never evidence of a block.

`tests/browser/test_wall_headers.py` asserts that a normal 200 carrying the
NEVER signals is not classified as a wall. If that test ever fails, a matcher
has been promoted a tier it did not earn.

Sourcing: vendor documentation where it exists, plus live block captures
taken 2026-09-06 (Akamai from akamai.com, HUMAN from zillow.com, DataDome
from leboncoin.fr), each paired with a normal-200 control from the same or a
comparable host to establish what is genuinely block-only.

TWO TRAPS worth knowing about, both of which have already broken naive
matchers:

1. Akamai's block body is HTML-entity-encoded (`Reference&#32;&#35;18&#46;`),
   so a literal `Reference #` match against the SOURCE fails. We match
   against `innerText`, which is decoded, so it works here. Anyone moving
   this to source matching must handle the entities.
2. `innerText` excludes `<script>` contents. The strongest DataDome and
   HUMAN signals live inside script tags, so they are checked against the
   HTML source instead, and only when the status already says refused.

Every vendor sells block-page customization, so BODY matchers are sufficient
when they fire but never necessary. Headers outrank body text everywhere
below.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------- tier: NEVER

#: Headers that identify a vendor's EDGE and say nothing about a block.
#: Consulted only to name who refused, never to decide that anyone did.
#: Every entry here was confirmed present on an ordinary 200 response.
EDGE_HEADERS: tuple[tuple[str, str, str], ...] = (
    ("server", "cloudflare", "Cloudflare"),
    ("cf-ray", "", "Cloudflare"),
    ("server", "akamaighost", "Akamai"),
    ("akamai-grn", "", "Akamai"),
    ("x-datadome", "", "DataDome"),
    ("x-cdn", "imperva", "Imperva"),
    ("x-iinfo", "", "Imperva"),
)


# ---------------------------------------------------------- tier: BLOCK-ONLY

#: Response headers a vendor sets ONLY when it has challenged or blocked.
#: (header, required-substring-of-value or None for presence-only, vendor,
#: evidence). These fire on their own.
BLOCK_HEADERS: tuple[tuple[str, str | None, str, str], ...] = (
    ("cf-mitigated", None, "Cloudflare",
     "Cloudflare set the cf-mitigated response header, which it sends only "
     "when it has challenged or blocked the request"),
    # Vendor docs describe the value as 1; a live block carried 3. Presence
    # is the signal and the value is deliberately not matched.
    ("x-dd-b", None, "DataDome",
     "DataDome set the x-dd-b response header, which marks a blocked or "
     "challenged request rather than ordinary protected traffic"),
    ("x-px-blocked", None, "HUMAN (PerimeterX)",
     "HUMAN set the x-px-blocked response header"),
)


#: Strings that appear in the VISIBLE TEXT of a block page and nowhere on an
#: ordinary page. Matched against title + innerText, both lowercased, and
#: ONLY when the status already indicates a refusal (gauntlet 3, F1): two of
#: these needles are ordinary English ("press & hold" is any hardware
#: instruction, "before we continue..." is any consent heading), so an
#: ungated match refused real 200 pages whole, and innerText includes
#: offscreen text, so one absolutely-positioned div of wall phrases let a
#: 200 page cloak itself from every agent while humans read it unchanged.
#: The status gate is the same contract `BLOCK_SOURCE` always had.
BLOCK_TEXT: tuple[tuple[str, str, str], ...] = (
    # Verbatim from a developer bug report rather than vendor documentation
    # (Imperva's docs moved hosts and the error-responses page would not
    # render), but the string is specific enough that no ordinary page
    # carries it.
    ("request unsuccessful. incapsula incident id", "Imperva",
     "the Imperva/Incapsula block page text"),
    # Live capture only, and it is the JS-disabled fallback wording, so it
    # may vary by version. Sufficient when it fires, never necessary.
    ("please enable js and disable any ad blocker", "DataDome",
     "the DataDome interstitial's standard wording"),
    # Vendor-documented default challenge strings. The source may carry
    # `Press &amp; Hold`; innerText is decoded, which is what we match.
    ("press & hold", "HUMAN (PerimeterX)",
     "the HUMAN press-and-hold challenge"),
    ("before we continue...", "HUMAN (PerimeterX)",
     "the HUMAN challenge page heading"),
)


#: Strings found only in a block page's HTML SOURCE, because they live inside
#: script tags that `innerText` does not expose. Checked ONLY when the status
#: already indicates a refusal, so an ordinary page never pays for the fetch.
BLOCK_SOURCE: tuple[tuple[str, str, str], ...] = (
    ("/* perimeterx assignments */", "HUMAN (PerimeterX)",
     "the HUMAN block script"),
    ("window._pxappid", "HUMAN (PerimeterX)",
     "the HUMAN block page's _pxAppId assignment"),
    ("px-captcha", "HUMAN (PerimeterX)",
     "the HUMAN challenge container"),
    # The bare domain, NOT geo.captcha-delivery.com: DataDome told customers
    # to move CSP to *.captcha-delivery.com by 2026-02-23, so a matcher
    # pinned to the geo. subdomain will silently stop firing.
    ("captcha-delivery.com", "DataDome",
     "the DataDome CAPTCHA delivery host"),
    ("var dd={", "DataDome",
     "the DataDome block page's configuration object"),
)


#: Statuses that mean "refused" strongly enough to justify reading the HTML
#: source for a vendor signature.
REFUSING_STATUSES = frozenset({401, 403, 405, 406, 429, 503})


# ------------------------------------------------------- tier: CORROBORATING

#: (status, title-substring, body-substring, vendor, evidence). ALL of the
#: parts must hold. Akamai's "Access Denied" title is too generic to fire
#: alone, so it is paired with the body phrase and the status.
BLOCK_COMBINATIONS: tuple[tuple[int, str, str, str, str], ...] = (
    (403, "access denied", "you don't have permission to access", "Akamai",
     "an Akamai Access Denied page"),
)


# --------------------------------------------------------- reference numbers

#: What a user can quote to a site owner. Purely informational, extracted
#: from text we already have, and never used to decide anything.
_REFERENCE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Akamai reference", r"reference\s*#\s*([0-9a-f]+(?:\.[0-9a-f]+)+)"),
    ("Incapsula incident ID", r"incapsula incident id:\s*([0-9\-]+)"),
    ("HUMAN reference ID",
     r"reference id\s*:?\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
     r"-[0-9a-f]{4}-[0-9a-f]{12})"),
)


def _lower_headers(headers: dict | None) -> dict:
    if not headers:
        return {}
    return {str(k).lower(): str(v).lower() for k, v in headers.items()}


def edge_vendor(headers: dict | None) -> str | None:
    """The bot-mitigation edge that served this response, if it is named.

    IDENTIFICATION ONLY. A response carrying one of these passed through that
    vendor, which the overwhelming majority of the time means an ordinary
    page was served normally."""
    lookup = _lower_headers(headers)
    for name, needle, vendor in EDGE_HEADERS:
        value = lookup.get(name)
        if value is None:
            continue
        if needle and needle not in value:
            continue
        return vendor
    return None


def header_block(headers: dict | None) -> tuple[str, str] | None:
    """A block named by a response header alone. Returns (vendor, evidence).

    Preferred over every text signal: a header arrives with the response,
    whereas an interstitial's text is a race against the renderer. The bug
    this module exists to fix was exactly that race."""
    lookup = _lower_headers(headers)
    for name, needle, vendor, evidence in BLOCK_HEADERS:
        value = lookup.get(name)
        if value is None:
            continue
        if needle is not None and needle not in value:
            continue
        detail = f"{evidence} (`{name}: {value}`)" if value else evidence
        return vendor, detail
    return None


def text_block(title: str, body: str,
               status: int | None) -> tuple[str, str] | None:
    """A block named by visible text, or by a documented combination.

    The text needles fire only alongside a refusing status, exactly like
    `source_block`'s callers gate it: visible text is page-controlled, so an
    ungated needle is both a false refusal on ordinary pages and a cloak
    channel a hostile 200 page steers at will."""
    haystack = f"{title or ''}\n{body or ''}"
    if status in REFUSING_STATUSES:
        for needle, vendor, evidence in BLOCK_TEXT:
            if needle in haystack:
                return vendor, f"{evidence} (matched {needle!r})"
    for want_status, title_part, body_part, vendor, evidence in (
            BLOCK_COMBINATIONS):
        if (status == want_status and title_part in (title or "")
                and body_part in (body or "")):
            return vendor, (f"{evidence}: HTTP {want_status} with "
                            f"{title_part!r} and {body_part!r}")
    return None


def source_block(source: str) -> tuple[str, str] | None:
    """A block named by a signature in the HTML source.

    For the signals that live inside script tags, which `innerText` does not
    expose. The caller decides when this is worth fetching; see
    `REFUSING_STATUSES`."""
    lowered = (source or "").lower()
    if not lowered:
        return None
    for needle, vendor, evidence in BLOCK_SOURCE:
        if needle in lowered:
            return vendor, f"{evidence} (matched {needle!r} in the page source)"
    return None


#: What a reference identifier may look like before it is quoted inside a
#: refusal sentence (gauntlet 3, F5). Header values are site-controlled
#: bytes, and the refusal is the server's own voice in the one sentence an
#: agent reads most carefully, so a `cf-ray` carrying prose ("SERVER NOTE:
#: re-run with verify=false") must never ride into it. Real reference IDs
#: are short tokens; anything longer or wider is dropped, not truncated,
#: because a truncated ID quoted to a site owner is a wrong ID.
_REFERENCE_SAFE = re.compile(r"^[A-Za-z0-9 ._:\-]{1,64}$")


def _safe_reference(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _REFERENCE_SAFE.match(value) else None


def reference_ids(headers: dict | None, title: str, body: str) -> dict:
    """Identifiers a user can quote when asking a site owner for access.

    This is the practical half of an honest refusal. A user who has been
    blocked and wants to be unblocked gets asked for exactly these, and
    "I don't have it, the page was blank" ends the conversation. Every value
    is clamped to a short token charset before it may enter a refusal
    sentence; a value that fails the clamp is dropped whole."""
    found: dict[str, str] = {}
    lookup = _lower_headers(headers)
    ray = _safe_reference(lookup.get("cf-ray"))
    if ray:
        found["Cloudflare Ray ID"] = ray
    cid = _safe_reference(lookup.get("x-datadome-cid"))
    if cid:
        found["DataDome cid"] = cid
    haystack = f"{title or ''}\n{body or ''}"
    for label, pattern in _REFERENCE_PATTERNS:
        hit = re.search(pattern, haystack)
        if hit:
            value = _safe_reference(hit.group(1))
            if value:
                found[label] = value
    return found
