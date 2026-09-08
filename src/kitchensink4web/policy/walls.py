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
    ("x-akamai-transformed", "", "Akamai"),
    ("x-datadome", "", "DataDome"),
    ("x-cdn", "imperva", "Imperva"),
    ("x-iinfo", "", "Imperva"),
    # AWS CloudFront serves an enormous share of the ordinary web and says
    # nothing whatever about a block. It sits here on exactly the same
    # footing as `server: cloudflare`, for naming only, and its block-only
    # companion is `x-amzn-waf-action` below.
    ("server", "cloudfront", "AWS CloudFront"),
    ("x-amz-cf-id", "", "AWS CloudFront"),
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
    # AWS WAF, from a live capture: SimilarWeb answered `HTTP 202 Accepted`
    # with `Server: CloudFront`, `x-amzn-waf-action: challenge`, an empty
    # title and no body text. PRESENCE is the signal and the value is
    # deliberately not matched here: the observed value was `challenge`, AWS
    # documents `captcha` and `block` as well, and pinning a matcher to one
    # string is how the `x-dd-b` matcher would have failed (vendor docs said
    # 1, a live block carried 3). The value is consulted in exactly one
    # place, `classify.py`'s choice between the botwall and captcha
    # categories, and never to decide that anything fired at all.
    ("x-amzn-waf-action", None, "AWS WAF",
     "AWS WAF set the x-amzn-waf-action response header, which it sends "
     "only when it has challenged, captcha'd, or blocked the request"),
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


# ------------------------------------------------------ tier: SOFT-BLOCK
#
# THE RUNG THE FIELD TEST ASKED FOR, and the reason it needed asking. Two
# independent model runs (2026-09-08) drove the same finding: the detector
# above recognizes a wall only when it recognizes the VENDOR, and it says
# nothing at all otherwise. Reddit answered a "You've been blocked by
# network security" page and JSTOR answered an Akamai "Client Challenge"
# CAPTCHA, and both came back `ok: true, status: 200, wall: null`, which is
# strictly worse than a refusal because nothing downstream thinks to look
# twice. Both runs recommended the same shape independently: a vendor-
# agnostic backstop for HTTP 200 pages that carry a challenge signal and no
# readable prose.
#
# WHY THIS DOES NOT REOPEN F1, and this is the whole argument. The status
# gate on the visible-text tiers exists because `innerText` includes
# offscreen text, so one absolutely-positioned div of wall phrases let a
# hostile 200 page cloak itself from every agent while a human read the page
# unchanged. The cost of that misfire was the PAGE: a false wall verdict
# withholds real content. A soft block cannot pay that cost, because it
# fires only when there is no readable prose to withhold. A page carrying an
# article cannot cloak itself this way; the prose test fails.
#
# AND IT IS NOT A LENGTH HEURISTIC. The fixture corpus is emphatic that body
# length is not a wall signal in either direction: a paywalled Science
# article carries 32,248 visible characters and a perfectly working Channel 4
# homepage carries 44. Length here is a NECESSARY CONDITION on a rung whose
# firing signal is something else entirely, never a signal in its own right.
# Channel 4 and the 6-character Notion shell both sit under the floor and
# neither classifies, because neither carries a challenge signal.

#: A page with fewer visible characters than this has nothing on it a caller
#: could have wanted. It is a floor on "is there anything to read", not a
#: threshold on "is this a wall": nothing in this module fires on it alone.
NO_READABLE_PROSE_CHARS = 200

#: Titles a challenge or block interstitial carries when no vendor header
#: does. Every one of them is generic enough that it fires ONLY as half of
#: the soft-block pair, never alone.
CHALLENGE_TITLES: tuple[tuple[str, str, str], ...] = (
    # JSTOR, live 2026-09-08, HTTP 200. Akamai Bot Manager's interactive
    # challenge; the body was the single line "Enter the characters seen in
    # the image below".
    ("client challenge", "Akamai", "the Akamai Client Challenge title"),
    ("access denied", None, "an access-denied title"),
    ("attention required", "Cloudflare", "the Cloudflare challenge title"),
    ("just a moment", "Cloudflare", "the Cloudflare challenge title"),
    # Crunchbase served this instead of "Just a moment...", with a different
    # ellipsis character, from the same vendor. Vendor title matching is a
    # corroborator and never a gate, and this pair is why.
    ("one moment, please", "Cloudflare", "the Cloudflare challenge title"),
    ("security check", None, "a security-check title"),
    ("bot verification", None, "a bot-verification title"),
    ("are you a robot", None, "a bot-check title"),
    # PubMed, live 2026-09-08, field report item 20. It served the title
    # "Checking your browser - reCAPTCHA" and the verdict came back
    # insufficient_evidence, because the rung that catches exactly this
    # shape was already built and neither string was in its vocabulary.
    # Both needles are here rather than one: the tester's page carried both,
    # but a browser-check interstitial and a reCAPTCHA shell each appear
    # without the other on other sites.
    ("checking your browser", None, "a browser-check challenge title"),
    ("recaptcha", None, "a reCAPTCHA challenge title"),
    ("blocked", None, "a block title"),
    ("forbidden", None, "a forbidden title"),
)

#: Visible-text needles a challenge shell carries. Same rule: half of a
#: pair, never alone.
CHALLENGE_TEXT: tuple[tuple[str, str, str], ...] = (
    ("enter the characters seen in the image", None,
     "an image-CAPTCHA prompt"),
    ("blocked by network security", None,
     "a network-security block notice"),
    ("you've been blocked", None, "a block notice"),
    ("verify you are a human", None, "a human-verification prompt"),
    ("verifying you are human", None, "a human-verification prompt"),
    ("enable javascript and cookies to continue", "Cloudflare",
     "the Cloudflare challenge instruction"),
    ("checking if the site connection is secure", "Cloudflare",
     "the Cloudflare connection-check line"),
    ("additional security check is required", None,
     "an additional-security-check notice"),
    # The body half of the PubMed pair. A browser-check interstitial writes
    # this line into the document as often as into the title.
    ("checking your browser", None, "a browser-check line"),
)

#: QUERY PARAMETERS THE SITE ITSELF PUT ON THE LANDED URL. This is the
#: strongest signal on the rung and the one that caught Reddit, whose block
#: page rendered no title and no readable text at all: the redirect landed on
#: `?js_challenge=1&jsc_token=...`. A query parameter on the landed URL is
#: written by the SERVER's redirect, not by the document, so it is not the
#: page-controlled channel the F1 gate exists to distrust.
CHALLENGE_URL_PARAMS: tuple[tuple[str, str | None, str], ...] = (
    ("js_challenge", None, "a js_challenge parameter on the landed URL"),
    ("jsc_token", None, "a jsc_token parameter on the landed URL"),
    ("__cf_chl_tk", "Cloudflare", "a Cloudflare challenge token on the URL"),
    ("__cf_chl_rt_tk", "Cloudflare",
     "a Cloudflare challenge token on the URL"),
    ("cf_chl_jschl_tk", "Cloudflare",
     "a Cloudflare challenge token on the URL"),
    ("awswaf", "AWS WAF", "an AWS WAF parameter on the landed URL"),
    ("px-captcha", "HUMAN (PerimeterX)",
     "a HUMAN captcha parameter on the landed URL"),
    ("incident_id", "Imperva", "an Imperva incident id on the landed URL"),
)


def soft_block(status: int | None, *, title: str, body: str,
               landed_url: str | None = None,
               visible_chars: int | None = None
               ) -> tuple[str | None, str] | None:
    """A block a vendor header never named, on a status that says nothing.

    Returns `(vendor_or_None, evidence)` or None. Two halves, and BOTH are
    required: a challenge signal, and a document with no readable prose. See
    the section comment above for why the pair is what keeps the F1 cloaking
    property intact.

    SOFT means soft, and the status bound is load-bearing. At a refusing
    status the vendor tables and the status branches already own the verdict,
    and this rung's title needles are generic enough ("forbidden", "access
    denied", "blocked") that letting them run there reclassified an
    application's own explained 403 as a bot wall, which is a shape
    `tests/browser/test_wall_headers.py` protects on purpose: a refusal that
    speaks for itself is not an edge refusal. The rung exists for the case
    nothing else covers, a 200 that is not a page."""
    if status is not None and (status >= 400 or status == 202):
        return None
    chars = visible_chars if visible_chars is not None else len(
        (body or "").strip())
    if chars >= NO_READABLE_PROSE_CHARS:
        return None
    low_title = (title or "").lower()
    low_body = (body or "").lower()
    low_url = (landed_url or "").lower()
    for needle, vendor, evidence in CHALLENGE_URL_PARAMS:
        if needle in low_url:
            return vendor, (f"{evidence}, and the document carries "
                            f"{chars} characters of readable text")
    for needle, vendor, evidence in CHALLENGE_TITLES:
        if needle in low_title:
            return vendor, (f"{evidence}, and the document carries "
                            f"{chars} characters of readable text")
    for needle, vendor, evidence in CHALLENGE_TEXT:
        if needle in low_body or needle in low_title:
            return vendor, (f"{evidence}, and the document carries "
                            f"{chars} characters of readable text")
    return None


#: DataDome ships one template for a solvable CAPTCHA and for a flat refusal.
#: `captcha/datadome_captcha_nytimes.html` and
#: `botwall/datadome_block_economist.html` are the same 403, the same markup,
#: and the same visible string. The ONLY discriminators are the vendor's own
#: config field and the script it loads, so there is no text needle to write
#: for this boundary and inventing one would be a guess.
DATADOME_KIND: tuple[tuple[str, str], ...] = (
    ("'rt':'c'", "captcha"),
    ('"rt":"c"', "captcha"),
    ("/c.js", "captcha"),
    ("'rt':'i'", "botwall"),
    ('"rt":"i"', "botwall"),
    ("/i.js", "botwall"),
)


def datadome_kind(source: str) -> str | None:
    """`captcha` or `botwall` for a DataDome page, from its own config."""
    lowered = (source or "").lower()
    for needle, kind in DATADOME_KIND:
        if needle in lowered:
            return kind
    return None


def all_vendors(headers: dict | None, title: str = "", body: str = "",
                source: str = "") -> list[str]:
    """EVERY vendor this response names, not the first one matched.

    G2 answered a DataDome body while setting Cloudflare's `__cf_bm` cookie
    in the same response. A scan that stops at the first match reports one of
    two walls and hides the other, and which one it reports depends on table
    order rather than on the page."""
    found: list[str] = []
    lookup = _lower_headers(headers)

    def add(vendor: str | None) -> None:
        if vendor and vendor not in found:
            found.append(vendor)

    for name, needle, vendor in EDGE_HEADERS:
        value = lookup.get(name)
        if value is None or (needle and needle not in value):
            continue
        add(vendor)
    for name, needle, vendor, _evidence in BLOCK_HEADERS:
        value = lookup.get(name)
        if value is None or (needle is not None and needle not in value):
            continue
        add(vendor)
    cookies = lookup.get("set-cookie", "")
    for needle, vendor in (("__cf_bm", "Cloudflare"), ("cf_clearance",
                                                       "Cloudflare"),
                           ("datadome", "DataDome"), ("_abck", "Akamai"),
                           ("ak_bmsc", "Akamai"), ("incap_ses", "Imperva"),
                           ("visid_incap", "Imperva"), ("_px", "HUMAN "
                                                        "(PerimeterX)")):
        if needle in cookies:
            add(vendor)
    haystack = f"{title or ''}\n{body or ''}".lower()
    for needle, vendor, _evidence in BLOCK_TEXT:
        if needle in haystack:
            add(vendor)
    lowered = (source or "").lower()
    for needle, vendor, _evidence in BLOCK_SOURCE:
        if needle in lowered:
            add(vendor)
    if "challenges.cloudflare.com" in lowered:
        add("Cloudflare")
    return found


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
        # THE VALUE IS CLAMPED BEFORE IT MAY BE QUOTED (gauntlet 4, G4-02),
        # exactly as `reference_ids` clamps its own (gauntlet 3, F5). Two of
        # the three block headers match on PRESENCE ONLY, so the value is
        # entirely the site's to write, and this string ends up inside the
        # `Evidence:` sentence of a refusal in the server's own voice — the
        # one sentence an agent reads most carefully, outside any page-data
        # envelope. A live probe put 322 characters of attacker prose there,
        # and 5,000 characters of header produced a 5,136-character evidence
        # string, so the channel was unbounded as well as unvalidated. A
        # value that fails the clamp is DROPPED, never truncated: the
        # evidence still names the header and the vendor, which is the part
        # that carries the verdict, and a half-quoted value is worse than
        # none. The verdict itself is unchanged — a block-only header still
        # fires on its own presence at any status.
        safe = _safe_reference(value)
        detail = f"{evidence} (`{name}: {safe}`)" if safe else evidence
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
