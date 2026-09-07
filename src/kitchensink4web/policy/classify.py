"""What KIND of not-the-page a page is, with the evidence that said so.

`walls.py` answers one question: which bot-mitigation vendor refused this
request. This module answers the wider one a caller actually has, which is
why the page in front of it is not the page it wanted. A paywall, a login
wall, a consent modal, an age gate, a region notice, a missing page, a
maintenance window and a rate limit are all different problems with
different ways out, and today they all arrive as either a bare status code
or as nothing at all.

FOUR PROPERTIES THIS INHERITS FROM `walls.py` AND MUST NOT WEAKEN.

1. **The three-tier signal contract.** BLOCK-ONLY fires alone, because the
   thing that emits it emits it only when refusing. CORROBORATING fires only
   with a gate held, because it also appears on ordinary pages. NEVER
   identifies a technology and is never evidence of anything. Every table
   below declares its tier and the tier is the contract.
2. **Page-authored text never rides raw in the server's voice.** An evidence
   `detail` quotes OUR needle, never the page's surrounding prose, and a
   count or a ratio is preferred to a quotation wherever it carries the same
   information.
3. **Nothing acts on first match.** Classification is multi-label and the
   whole list is reported.
4. **The classifier never raises.** A probe that failed, a page that
   navigated mid-read, an evaluate that threw: all of them degrade to fewer
   signals and a lower confidence. A classifier that can fail a navigation
   is worse than no classifier.

THE DECISION THAT SHAPES EVERYTHING ELSE: a paywall is REPORTED, not
refused. A paywalled article is a real 200 page carrying the abstract, the
metadata, the DOI, and often the whole first paragraph, which is most of
what a research agent needed in order to decide whether to chase the full
text. Refusing it would withhold the content in the name of protecting the
caller from it. The same holds for a consent banner (the caller can act on
its own control), an age gate, a region notice, and a 404 (whose body often
names the right URL). Only the categories where CONTINUING is the mistake
map onto a `wall` value and raise: a bot wall or CAPTCHA nobody here can
pass, a rate limit the server asked us to honor, a login wall where every
read is a read of the login page, and a maintenance page with nothing
behind it.

WHAT THE FIXTURE CORPUS CHANGED, because six of these were assumptions
before 32 real samples across 25 hosts contradicted them (the corpus is in
`tests/data/walls/`, with its collection notes and the robots.txt of every
host it touched):

- Body length is NOT a wall signal. A paywalled Science article carries
  32,248 visible characters; a working Channel 4 homepage carries 44. Length
  correlates with rendering strategy, not with blocking. No table here
  contains a length heuristic.
- `isAccessibleForFree` is a hint and not a verdict. Nature encodes the
  boolean `false`, Le Monde encodes the string `"False"`, and Statista
  reports `true` while redacting the data inline. It is parsed three ways
  and it never fires alone.
- 4xx and 5xx are bucketed by CLASS, never by equality: NRK answered a
  missing page with `400 Bad Request`.
- HTTP 202 is a block. Any rule shaped "2xx means we got the page" passes an
  AWS WAF challenge straight through.
- `Sign in`, `Login`, `Subscribe`, the literal token `paywall`, and
  `noindex` are everywhere, including on an ordinary free article. All of
  them are NEVER-tier on their own.
- One host serves different walls on different paths, so nothing here is
  ever keyed on a host name.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from . import walls as _walls

# --------------------------------------------------------------- vocabulary

#: Every category this module can emit. `soft_404` is separate from
#: `http_404` deliberately: one is a server saying the page is gone and the
#: other is a server saying 200 about a page that is gone anyway, and the
#: recovery differs.
CATEGORIES: tuple[str, ...] = (
    "botwall", "captcha", "rate_limited", "login_required", "maintenance",
    "http_500", "http_404", "soft_404",
    "paywall_academic", "paywall_news", "paywall_saas",
    "geo_blocked", "age_gated", "gdpr_consent",
)

#: Severity, highest first. Two categories on one page is normal (a 404 that
#: is also age-gated, a news paywall that is also a consent wall), so
#: something has to decide which one the `wall` mapping reads, and the answer
#: is the most severe rather than the most confident: a page that is both a
#: bot wall and a consent wall is a bot wall.
SEVERITY: tuple[str, ...] = CATEGORIES

#: Category to the EXISTING `wall` vocabulary. The `wall` key keeps its exact
#: current values and its exact current behavior, because `navigate` raises
#: on it and several call sites branch on it, so a new value there would
#: change what raises on pages that used to load fine. New categories appear
#: only under `classification`.
WALL_FOR: dict[str, str] = {
    "botwall": "bot-wall-or-captcha",
    "captcha": "bot-wall-or-captcha",
    "rate_limited": "rate-limited",
    "login_required": "auth-wall",
    "maintenance": "service-unavailable-or-bot-wall",
}

#: Confidence, derived rather than judged.
CONFIDENCE_RANK: dict[str, int] = {
    "confirmed": 3, "probable": 2, "possible": 1,
    "insufficient_evidence": 0, "none": 0,
}


# ------------------------------------------------------------- pending copy
#
# EVERY SENTENCE A USER READS OUT OF THIS MODULE IS A PLACEHOLDER, and that
# is deliberate rather than unfinished. Product copy is written by the main
# thread or the author, never by the agent that builds the machinery
# (standing rule, 2026-09-04). The access path is the sentence that matters
# most in the whole feature, since it is the one a blocked caller acts on,
# and it is also a sentence a page must never be able to influence, so it
# comes from a CLOSED TABLE keyed by category and is never assembled from
# anything the page wrote.
#
# `tests/unit/test_classify.py` asserts that every category has a key here
# and that no key is missing, so a category added without its copy fails
# loudly rather than shipping an empty string. The facts each key has to
# convey are recorded with the build report.

def _pending(key: str) -> str:
    return f"[COPY PENDING: classify.{key}]"


ACCESS_PATHS: dict[str, str] = {name: _pending(f"access_path.{name}")
                                for name in CATEGORIES}

NOTES: dict[str, str] = {
    "none": _pending("note.no_category"),
    "insufficient_evidence": _pending("note.insufficient_evidence"),
    "geo_blocked_limitation": _pending("note.geo_blocked_limitation"),
    "paywall_saas_weak": _pending("note.paywall_saas_weak"),
}


# ------------------------------------------------------------- signal tables
#
# Naming, so a reader can tell at a glance what kind of thing is being
# trusted: `S` HTTP status, `H` response header, `R` redirect chain or landed
# URL, `T` title and visible text (page-controlled), `X` a bounded HTML
# source slice (page-controlled), `D` a targeted DOM query (structural).
#
# THE TEXT NEEDLES ARE SPLIT IN TWO, and the split is the F1 defense carried
# to the families where the status gate is unavailable. The whole paywall,
# consent and age-gate world lives on HTTP 200, so `status in
# REFUSING_STATUSES` cannot gate anything there and something else has to.
#
#   GATED needles are ordinary English that any page may carry ("sign in via
#   your institution", "are you 18 or over", "accept all cookies"). One
#   absolutely-positioned offscreen div of these is exactly the cloak F1 was
#   written against, so a GATED needle is consulted only after a STRUCTURAL
#   signal in the same family has already held.
#
#   SPECIFIC needles are publisher-platform strings that ordinary pages do
#   not carry ("restricted access", "purchase 24 hour online access to").
#   These corroborate on their own, and they still cannot reach `confirmed`
#   without a structural or header signal, so the worst a cloaked page buys
#   is a `possible` label on a page that is still returned in full.
#
# The asymmetry is deliberate and it is bounded by consequence: these
# families do not map to a `wall`, so a misfire costs a wrong label in a
# report and never costs the caller the page. Categories that DO raise take
# the strict gate, and `_maps_to_wall` below is where that is enforced.

#: Tokens that are on the whole web and are never evidence of anything.
#: Listed rather than merely omitted, because the next person to add a
#: category will reach for exactly these.
NEVER_TOKENS: tuple[str, ...] = (
    "sign in", "log in", "login", "subscribe", "paywall", "noindex",
    "cookie policy", "privacy policy", "__tcfapi", "doi.org",
)

#: X-tier markup that says a paywall CONTAINER exists in the document. The
#: bare token `paywall` is deliberately absent: an ordinary free Medium
#: article carries it.
PAYWALL_MARKUP: tuple[tuple[str, str], ...] = (
    ("data-paywall", "a data-paywall attribute"),
    ("data-paywall-trigger", "a data-paywall-trigger attribute"),
    ("data-paywall-type", "a data-paywall-type attribute"),
    ('class="paywall', "a paywall container class"),
    ('id="paywall', "a paywall container id"),
    ("js-paywall", "a paywall behavior hook"),
    ("__paywall", "a paywall component class"),
    ("-paywall__", "a paywall component class"),
    ("ismarkedpaywallonly\":true", "a marked-paywall-only flag"),
    ("islockedpreviewonly\":true", "a locked-preview-only flag"),
)

#: SPECIFIC academic-platform strings. Each names a purchase or access
#: barrier in wording an ordinary article does not use.
ACADEMIC_SPECIFIC: tuple[str, ...] = (
    "restricted access",
    "log in to view the full text",
    "purchase 24 hour online access",
    "purchase pdf",
    "buy this article",
    "rent this article",
    "get access to the full version of this article",
    "this article is available to subscribers",
)

#: GATED academic strings. Ordinary English, so a structural companion is
#: required before any of them is consulted.
ACADEMIC_GATED: tuple[str, ...] = (
    "sign in via your institution",
    "access through your institution",
    "institutional login",
    "get access",
    "full text access",
)

NEWS_SPECIFIC: tuple[str, ...] = (
    "subscribe to read",
    "subscribe to continue reading",
    "this article is for subscribers",
    "already a subscriber",
    "abonnez-vous pour lire",
    "article reserve aux abonnes",
    "artikel ist nur fur abonnenten",
)

NEWS_GATED: tuple[str, ...] = (
    "subscribe to continue",
    "free articles remaining",
    "free articles this month",
    "continue reading",
    "unlock this article",
)

SAAS_SPECIFIC: tuple[str, ...] = (
    "upgrade your plan",
    "this feature requires",
    "available with a paid plan",
    "start your free trial to unlock",
)

#: PUBLISHER ACCESS HEADERS. One publisher's own access decision, sent as a
#: response header, which is stronger than anything in the body and weaker
#: than a vendor block header, since the same header carries the ALLOW case
#: on an article that was served. Matched on the deny value only.
ACCESS_HEADERS: tuple[tuple[str, str, str], ...] = (
    ("ft-access-decision-policy", "denied",
     "the publisher's own access-decision header reported a denial"),
    ("x-access-decision", "denied",
     "the publisher's own access-decision header reported a denial"),
)

#: X-tier CMP identification. A NAMED consent-management vendor in the source
#: is what separates "this site has a consent layer" from the bare
#: `__tcfapi` stub, which every site with a CMP exposes whether or not a
#: banner is currently blocking anything.
CONSENT_VENDORS: tuple[tuple[str, str], ...] = (
    ("cdn.cookielaw.org", "OneTrust"),
    ("optanon", "OneTrust"),
    ("sourcepoint", "Sourcepoint"),
    ("sp-prod.net", "Sourcepoint"),
    ("didomi", "Didomi"),
    ("cookiebot", "Cookiebot"),
    ("quantcast", "Quantcast"),
    ("consentmanager.net", "consentmanager"),
    ("usercentrics", "Usercentrics"),
    ("cmp.osano", "Osano"),
)

CONSENT_GATED: tuple[str, ...] = (
    "accept all", "accept cookies", "reject all",
    "manage your choices", "gerer mes choix", "gérer mes choix",
    "zustimmung", "alle akzeptieren", "einwilligung",
    "aceptar todo", "accetta tutto", "we value your privacy",
    "we use cookies",
)

#: X-tier age-gate markup. Client-rendered age gates put these in component
#: config even when no rendered copy carries the words.
AGE_MARKUP: tuple[tuple[str, str], ...] = (
    ("age-gate", "an age-gate component"),
    ("agegate", "an age-gate component"),
    ("age_gate", "an age-gate component"),
    ("/agecheck", "an age-check path"),
    ("agecheck", "an age-check component"),
    ("birthdate", "a birth-date field"),
    ("date_of_birth", "a birth-date field"),
    ("dateofbirth", "a birth-date field"),
    ("ageverification", "an age-verification component"),
)

AGE_GATED: tuple[str, ...] = (
    "are you 18 or over", "are you 21 or over", "must be of legal drinking age",
    "enter your date of birth", "verify your age", "please enter your birth",
    "you must be of legal", "sind sie mindestens", "confirm your age",
)

#: R-tier paths a site redirects to when it is telling you where you are.
GEO_PATHS: tuple[str, ...] = (
    "/restricted", "/geo", "/not-available", "/unavailable",
    "/region", "/country-block",
)

GEO_GATED: tuple[str, ...] = (
    "not available in your country", "unavailable in this country",
    "not available in your region", "unavailable in your region",
    "outside the united states", "only available in",
    "in your location", "in your country or region",
)

#: R-tier paths that mean a SaaS product answered a content request with a
#: sales page.
PRICING_PATHS: tuple[str, ...] = (
    "/pricing", "/upgrade", "/billing", "/plans", "/subscribe",
)

#: A landed path that looks like a login page. This is the pattern
#: `ops/lite.py` has always used, moved here so the classifier does not have
#: to import an ops module (the import direction is one-way and
#: `tests/unit/test_import_direction.py` enforces it); lite aliases this name
#: so its own call sites are unchanged.
LOGIN_PATH = re.compile(
    r"/(login|log-in|signin|sign-in|sign_in|sessions?(/new)?|auth(orize)?)"
    r"(/|$|\?)", re.IGNORECASE)

#: R-tier continuation parameters. The corpus is clear that a redirect alone
#: means nothing (Nature runs a four-hop identity chain on a fully open
#: article); the login tell is a parameter naming the URL you asked for,
#: observed on GitHub (`return_to`) and Dropbox (`cont`).
CONTINUATION_PARAMS: tuple[str, ...] = (
    "return_to", "returnto", "returnurl", "return", "cont", "continue",
    "next", "redirect_to", "redirectto", "redirect", "service", "target_url",
)

LOGIN_SPECIFIC: tuple[str, ...] = (
    "your session has expired", "session expired",
    "please log in again", "sign in to continue",
    "you must be logged in to", "login or sign up",
)

#: A session interstitial rather than a login form, and the corpus caught one
#: (`journals.sagepub.com/action/cookieAbsent`). The recovery is the same as
#: a login wall's, so it rides the same category.
LOGIN_MARKUP: tuple[tuple[str, str], ...] = (
    ('type="password"', "a password field"),
    ("type='password'", "a password field"),
    ("cookieabsent", "a cookies-required interstitial"),
    ("login_field", "a login form field"),
    ("name=\"password\"", "a password field"),
)

MAINTENANCE_GATED: tuple[str, ...] = (
    "maintenance", "be back shortly", "be right back", "scheduled downtime",
    "temporarily unavailable", "wartungsarbeiten", "under maintenance",
)

RATE_GATED: tuple[str, ...] = (
    "too many requests", "slow down", "rate limit", "rate-limited",
    "you are being rate limited",
)

NOT_FOUND_GATED: tuple[str, ...] = (
    "page not found", "404", "not found", "seite nicht gefunden",
    "page introuvable", "no encontrada", "pagina non trovata",
    "does not exist", "no longer available",
)


# ------------------------------------------------------- the needle registry
#
# What the in-page probe searches the WHOLE document for. Every entry is a
# server constant, and what comes back is the list of constants that matched,
# never any of the page's own bytes. That is what lets the classifier see a
# barrier 30,000 characters into a publisher page without a single extra byte
# of page text crossing back.

TEXT_NEEDLES: tuple[str, ...] = tuple(sorted(set(
    ACADEMIC_SPECIFIC + ACADEMIC_GATED + NEWS_SPECIFIC + NEWS_GATED
    + SAAS_SPECIFIC + CONSENT_GATED + AGE_GATED + GEO_GATED
    + MAINTENANCE_GATED + RATE_GATED + LOGIN_SPECIFIC + NOT_FOUND_GATED)))

SOURCE_NEEDLES: tuple[str, ...] = tuple(sorted(set(
    [n for n, _d in PAYWALL_MARKUP] + [n for n, _d in AGE_MARKUP]
    + [n for n, _d in LOGIN_MARKUP] + [n for n, _v in CONSENT_VENDORS]
    + ["citation_doi", "citation_title", "citation_journal_title",
       "data-paywall-trigger", "px-captcha", "g-recaptcha", "h-captcha",
       "cf-turnstile", "challenges.cloudflare.com/turnstile"])))


# --------------------------------------------------------------- evidence

def _sig(signal: str, tier: str, detail: str) -> dict:
    return {"signal": signal, "tier": tier, "detail": detail}


#: The clamp every page-derived token passes before it may be quoted in the
#: server's own voice. DROPS rather than truncates, following
#: `walls._safe_reference` and the G4-02 header-value precedent: a
#: half-quoted value is worse than none.
_TOKEN_SAFE = re.compile(r"^[A-Za-z0-9 ._:/\-]{1,48}$")


def _safe_token(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _TOKEN_SAFE.match(value) else None


# ------------------------------------------------------------- the context

class _Ctx:
    """Everything one classification may consult, normalized once.

    Every field is optional, and `absent` records which ones were not
    supplied, because a classifier that reports the same confidence on
    partial input is claiming completeness over its own omissions."""

    def __init__(self, status, headers, title, body, source, structural,
                 redirect_chain, landed_url, requested_url):
        self.status = status
        self.headers = _walls._lower_headers(headers)
        self.title = (title or "").lower()
        self.body = (body or "").lower()
        self.source = (source or "").lower()
        self.structural = structural or {}
        self.chain = list(redirect_chain or ())
        self.landed = landed_url or ""
        self.requested = requested_url or ""
        self.absent = [name for name, value in (
            ("headers", headers), ("title", title), ("body", body),
            ("source", source), ("structural", structural),
            ("redirect_chain", redirect_chain)) if not value]
        self.text = f"{self.title}\n{self.body}"
        self.text_hits = {str(h).lower()
                          for h in self.structural.get("text_hits") or ()}
        self.source_hits = {str(h).lower()
                            for h in self.structural.get("source_hits") or ()}
        chars = self.structural.get("visible_chars")
        self.visible_chars = (chars if isinstance(chars, int)
                              else len(self.body.strip()))

    # -- cheap accessors, each naming the tier it answers for

    def header(self, name: str) -> str | None:
        return self.headers.get(name)

    def in_source(self, needle: str) -> bool:
        """A markup needle, anywhere in the document.

        THE SLICES ARE NOT THE DOCUMENT, and pretending otherwise is how a
        paywall on a long publisher page goes unnoticed. The verdict path
        reads a 4,000-character text slice and a 20,000-character source
        slice, both bounded on purpose, and a Science article carries 32,248
        visible characters with its access barrier well past both. The
        answer is not a bigger slice, which costs bytes on every ordinary
        page: the probe matches OUR OWN needles inside the page and returns
        booleans, so the whole document is searched and nothing but a list of
        server constants comes back."""
        return needle in self.source or needle in self.source_hits

    def in_text(self, needle: str) -> bool:
        return needle in self.text or needle in self.text_hits

    def landed_path(self) -> str:
        return (urlparse(self.landed).path or "").lower()

    def json_ld(self) -> list:
        """The ld+json blocks, from the structural probe when a browser ran
        one and from the source slice otherwise."""
        blocks = self.structural.get("jsonld")
        if isinstance(blocks, list) and blocks:
            return blocks
        if not self.source:
            return []
        return re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)'
            r'</script>', self.source, re.S | re.I)[:5]


# ------------------------------------------------- structured-data parsing

def _walk_access(node, out: list) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() == "isaccessibleforfree":
                out.append(value)
            else:
                _walk_access(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_access(item, out)


def access_for_free(blocks) -> tuple[bool | None, str]:
    """schema.org `isAccessibleForFree`, parsed all three ways it is written.

    Returns `(False, how)` when at least one occurrence says not-free,
    `(True, how)` when every occurrence says free, and `(None, how)` when
    nothing said anything. It NEVER fires alone: three publishers encode this
    field three incompatible ways and one of them reports `true` while
    redacting the data inline, so it is a hint about intent and not a verdict
    about access."""
    seen: list = []
    for raw in blocks or ():
        text = raw if isinstance(raw, str) else json.dumps(raw)
        try:
            _walk_access(json.loads(text), seen)
        except Exception:
            # Nature nests the field under `hasPart` and Le Monde writes the
            # STRING "False", so a block that will not parse as JSON is still
            # worth a bounded regex over the raw text rather than nothing.
            for hit in re.findall(
                    r'"isaccessibleforfree"\s*:\s*("?[a-zA-Z]+"?)',
                    text, re.I)[:8]:
                seen.append(hit.strip('"'))
    if not seen:
        return None, "no isAccessibleForFree field"
    normal = []
    for value in seen:
        if isinstance(value, bool):
            normal.append(value)
        elif isinstance(value, str):
            low = value.strip().strip('"').lower()
            if low in ("false", "0", "no"):
                normal.append(False)
            elif low in ("true", "1", "yes"):
                normal.append(True)
    if not normal:
        return None, "isAccessibleForFree carried an unreadable value"
    if False in normal:
        kinds = "a boolean" if any(
            v is False and isinstance(v, bool) for v in seen) else "a string"
        return False, (f"schema.org isAccessibleForFree parsed as false "
                       f"(encoded as {kinds})")
    return True, "schema.org isAccessibleForFree parsed as true"


# ------------------------------------------------------- family detectors
#
# Each returns `(structural_signals, corroborating_signals)`. The caller
# applies the gates, so no detector can skip one by not knowing it exists.


def _bucket(status: int | None, family: int) -> bool:
    """4xx and 5xx by CLASS, never by equality. NRK answered a missing page
    with 400 Bad Request, and a `status == 404` matcher misses it."""
    return isinstance(status, int) and family <= status < family + 100


def _detect_botwall(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    hit = _walls.header_block(ctx.headers)
    if hit:
        vendor, evidence = hit
        block.append(_sig("header", "block-only", evidence))
    if ctx.status in _walls.REFUSING_STATUSES:
        text_hit = _walls.text_block(ctx.title, ctx.body, ctx.status)
        if text_hit:
            corr.append(_sig("text", "corroborating", text_hit[1]))
        source_hit = _walls.source_block(ctx.source)
        if source_hit:
            corr.append(_sig("source", "corroborating", source_hit[1]))
    if ctx.status == 202:
        block.append(_sig("status", "block-only",
                          "HTTP 202 on a top-level document, which is the "
                          "shape of an anti-automation shell"))
    soft = _walls.soft_block(ctx.status, title=ctx.title, body=ctx.body,
                             landed_url=ctx.landed,
                             visible_chars=ctx.visible_chars)
    if soft:
        block.append(_sig("soft_block", "block-only", soft[1]))
    return block, corr


def _detect_captcha(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    action = ctx.header("x-amzn-waf-action") or ""
    if "captcha" in action:
        block.append(_sig("header", "block-only",
                          "AWS WAF's x-amzn-waf-action named a captcha"))
    if ctx.in_source("px-captcha"):
        block.append(_sig("source", "block-only",
                          "the HUMAN captcha container"))
    kind = _walls.datadome_kind(ctx.source)
    if kind == "captcha":
        block.append(_sig("source", "block-only",
                          "the DataDome config field rt names a solvable "
                          "challenge rather than a refusal"))
    for needle in ("press & hold", "verify you are a human",
                   "enter the characters seen in the image",
                   "i'm not a robot"):
        if ctx.in_text(needle) and (
                ctx.status in _walls.REFUSING_STATUSES
                or ctx.visible_chars < _walls.NO_READABLE_PROSE_CHARS):
            corr.append(_sig("text", "corroborating",
                             f"matched {needle!r}"))
    # A CAPTCHA WIDGET ON A PAGE THAT ALSO HAS CONTENT IS A FORM CONTROL,
    # not a wall. Science's article page loads one for its comment form, and
    # a first cut classified the article as a captcha because of it. The
    # widget corroborates only where the document is a challenge shell or the
    # status already says refused.
    if (ctx.status in _walls.REFUSING_STATUSES
            or ctx.visible_chars < _walls.NO_READABLE_PROSE_CHARS):
        for needle in ("g-recaptcha", "h-captcha", "cf-turnstile",
                       "challenges.cloudflare.com/turnstile"):
            if ctx.in_source(needle):
                corr.append(_sig("source", "corroborating",
                                 f"a challenge widget container ({needle})"))
    return block, corr


def _detect_rate_limited(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    if ctx.status == 429:
        block.append(_sig("status", "block-only", "HTTP 429"))
    retry = ctx.header("retry-after")
    if retry and isinstance(ctx.status, int) and ctx.status >= 400:
        # Retry-After on a 200 or a 3xx is a caching hint and says nothing
        # about a rate limit, which is why the status class is part of the
        # signal rather than a separate check somebody can forget.
        safe = _safe_token(retry)
        block.append(_sig("header", "block-only",
                          "a Retry-After header on a refusing status"
                          + (f" (`retry-after: {safe}`)" if safe else "")))
    for needle in RATE_GATED:
        if ctx.in_text(needle) and isinstance(ctx.status, int) \
                and ctx.status >= 400:
            corr.append(_sig("text", "corroborating", f"matched {needle!r}"))
    return block, corr


def _login_continuation(ctx: _Ctx) -> str | None:
    """A continuation parameter naming where you were going, on a URL that
    landed on a login path. A redirect alone means nothing."""
    landed_path = ctx.landed_path()
    if not landed_path or not LOGIN_PATH.search(landed_path):
        return None
    if ctx.requested and LOGIN_PATH.search(
            (urlparse(ctx.requested).path or "")):
        return None          # a login page somebody asked for is not a wall
    query = parse_qs(urlparse(ctx.landed).query or "")
    for name in query:
        if name.lower() in CONTINUATION_PARAMS:
            return name.lower()
    for hop in ctx.chain:
        target = (hop.get("url") or "").lower()
        if not LOGIN_PATH.search(urlparse(target).path or ""):
            continue
        for name in parse_qs(urlparse(target).query or ""):
            if name.lower() in CONTINUATION_PARAMS:
                return name.lower()
    return None


def _detect_login(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    if ctx.status == 401:
        block.append(_sig("status", "block-only", "HTTP 401"))
    param = _login_continuation(ctx)
    if param:
        block.append(_sig("redirect", "block-only",
                          f"the navigation landed on a login path carrying a "
                          f"{param} continuation parameter"))
    # A PASSWORD FIELD IS NOT A LOGIN WALL. Most of the commercial web
    # carries a sign-in form in a hidden modal, and a first cut classified a
    # SAGE article as a login wall on exactly that. The form corroborates
    # only where the document IS the login page: the landed path says login,
    # or there is no other readable content, or the status already refused.
    document_is_the_form = (
        bool(LOGIN_PATH.search(ctx.landed_path()))
        or ctx.visible_chars < _walls.NO_READABLE_PROSE_CHARS
        or ctx.status in _walls.REFUSING_STATUSES)
    if document_is_the_form:
        if ctx.structural.get("has_password_field"):
            corr.append(_sig("dom", "corroborating",
                             "the document carries a password field"))
        for needle, detail in LOGIN_MARKUP:
            if ctx.in_source(needle):
                corr.append(_sig("markup", "corroborating", detail))
                break
    elif ctx.in_source("cookieabsent"):
        # The session interstitial the corpus caught. It is a landed path
        # rather than a form, so it does not need the gate above.
        corr.append(_sig("markup", "corroborating",
                         "a cookies-required interstitial"))
    for needle in LOGIN_SPECIFIC:
        if ctx.in_text(needle):
            corr.append(_sig("text", "corroborating", f"matched {needle!r}"))
    return block, corr


def _detect_maintenance(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    if ctx.status != 503:
        return block, corr
    if _walls.header_block(ctx.headers) or _walls.source_block(ctx.source):
        return block, corr          # 503 from a vendor is a bot wall
    said = [n for n in MAINTENANCE_GATED if ctx.in_text(n)]
    if said:
        # A DOCUMENTED COMBINATION, on the same footing as Akamai's Access
        # Denied row in `walls.py`: neither half fires alone, and together
        # they are specific enough to carry the verdict. It has to reach
        # `confirmed`, because `maintenance` is one of the categories that
        # maps onto a `wall` and only a confirmed category may.
        block.append(_sig("status+text", "block-only",
                          f"HTTP 503 with maintenance wording (matched "
                          f"{said[0]!r}) and no vendor signature"))
        return block, corr
    corr.append(_sig("status", "corroborating", "HTTP 503"))
    return block, corr


def _detect_http_500(ctx: _Ctx) -> tuple[list, list]:
    if _bucket(ctx.status, 500) and ctx.status != 503:
        return [_sig("status", "block-only", f"HTTP {ctx.status}")], []
    return [], []


def _detect_http_404(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    if ctx.status == 404:
        block.append(_sig("status", "block-only", "HTTP 404"))
    elif _bucket(ctx.status, 400) and ctx.status not in (
            401, 403, 405, 406, 429) and ctx.status != 402:
        # By CLASS, not by equality. This is the NRK case, and the needle is
        # what separates "a 4xx that means gone" from "a 4xx that means
        # something else"; the status alone only corroborates.
        corr.append(_sig("status", "corroborating", f"HTTP {ctx.status}"))
        for needle in NOT_FOUND_GATED:
            if ctx.in_text(needle):
                corr.append(_sig("text", "corroborating",
                                 f"matched {needle!r}"))
                break
    return block, corr


def _detect_soft_404(ctx: _Ctx) -> tuple[list, list]:
    block, corr = [], []
    if ctx.status != 200:
        return block, corr
    title_says = any(n in ctx.title for n in
                     ("page not found", "404", "not found",
                      "seite nicht gefunden", "page introuvable"))
    if not title_says:
        return block, corr
    corr.append(_sig("title", "corroborating",
                     "the title of a 200 response names a missing page"))
    if not ctx.structural.get("has_main_content", True):
        corr.append(_sig("dom", "corroborating",
                         "the document has no main or article content "
                         "region"))
    return block, corr


def _paywall_common(ctx: _Ctx) -> tuple[list, list, bool | None]:
    """The structural signals every paywall family shares."""
    structural, corr = [], []
    for needle, detail in PAYWALL_MARKUP:
        if ctx.in_source(needle) or (
                needle == "data-paywall"
                and ctx.structural.get("paywall_container")):
            structural.append(_sig("markup", "corroborating", detail))
            break
    if ctx.structural.get("paywall_container") and not structural:
        structural.append(_sig("dom", "corroborating",
                               "a paywall container element"))
    for name, deny, detail in ACCESS_HEADERS:
        value = ctx.header(name)
        if value and deny in value:
            structural.append(_sig("header", "corroborating", detail))
    free, how = access_for_free(ctx.json_ld())
    if free is False:
        structural.append(_sig("jsonld", "corroborating", how))
    return structural, corr, free


#: EVERY PAYWALL FAMILY NEEDS A DISCRIMINATOR OF ITS OWN, and this is the
#: single largest precision lesson of the build. The three families share
#: every structural signal there is: a paywall container, a schema.org access
#: flag, a publisher access header. A first cut let those shared signals
#: classify on their own, and a Statista chart, a Financial Times article and
#: a Le Monde article each came back as academic paywalls while a Nature
#: article came back as a news paywall. The shared signals say THAT there is
#: a barrier; only a family discriminator says WHICH KIND, and no family may
#: classify without one.


def _schema_types(ctx: _Ctx) -> set:
    """The schema.org `@type` values the page declares about itself.

    The cleanest family discriminator in the corpus: Le Monde and the
    Financial Times both declare `NewsArticle`, Nature declares
    `ScholarlyArticle`, Statista declares `Dataset`, and the free Medium
    story declares `SocialMediaPosting`. It says nothing about access, which
    is why it is a discriminator and never evidence."""
    types = set()
    for raw in ctx.json_ld():
        text = raw if isinstance(raw, str) else json.dumps(raw)
        for hit in re.findall(r'"@type"\s*:\s*"([A-Za-z]+)"', text)[:40]:
            types.add(hit.lower())
    return types


def _is_academic(ctx: _Ctx) -> bool:
    """The Highwire/Google-Scholar citation meta tags, or a declared
    `ScholarlyArticle`. Both are NEVER-tier as evidence of a barrier (every
    open-access article carries them) and both are how you know you are
    looking at a journal article at all."""
    return (any(ctx.in_source(n) for n in
                ("citation_doi", "citation_journal_title", "citation_title"))
            or "scholarlyarticle" in _schema_types(ctx))


def _is_news(ctx: _Ctx) -> bool:
    return bool(_schema_types(ctx) & {"newsarticle", "reportagenewsarticle",
                                      "liveblogposting", "opinionnewsarticle"})


def _detect_paywall_academic(ctx: _Ctx) -> tuple[list, list]:
    structural, corr, _free = _paywall_common(ctx)
    specific = [n for n in ACADEMIC_SPECIFIC
                if ctx.in_text(n) or ctx.in_source(n)]
    if not _is_academic(ctx) and not specific:
        return [], []
    for needle in specific:
        corr.append(_sig("text", "corroborating", f"matched {needle!r}"))
    if structural:
        for needle in ACADEMIC_GATED:
            if ctx.in_text(needle):
                corr.append(_sig("text", "corroborating",
                                 f"matched {needle!r} (structural gate held)"))
    return [], structural + corr


def _detect_paywall_news(ctx: _Ctx) -> tuple[list, list]:
    structural, corr, _free = _paywall_common(ctx)
    if _is_academic(ctx):
        return [], []          # a journal article is the academic family
    specific = [n for n in NEWS_SPECIFIC if ctx.in_text(n) or ctx.in_source(n)]
    header_denied = any(sig["signal"] == "header" for sig in structural)
    if not (_is_news(ctx) or specific or header_denied):
        return [], []
    for needle in specific:
        corr.append(_sig("text", "corroborating", f"matched {needle!r}"))
    if structural:
        for needle in NEWS_GATED:
            if ctx.in_text(needle):
                corr.append(_sig("text", "corroborating",
                                 f"matched {needle!r} (structural gate held)"))
    return [], structural + corr


def _detect_paywall_saas(ctx: _Ctx) -> tuple[list, list]:
    """THE WEAKEST CATEGORY IN THE TAXONOMY, said here rather than left to be
    discovered. Its one real pattern is redaction-in-place: complete prose
    with individual values swapped for gated elements. The subscribe and
    upgrade vocabulary it shares with `paywall_news` and `login_required` is
    not separable, and the products with the crispest upgrade gates sit
    behind the most aggressive bot protection, so an HTTP client rarely
    reaches them at all. One real sample exists."""
    structural, corr = [], []
    if ctx.in_source("data-paywall-trigger"):
        structural.append(_sig("markup", "corroborating",
                              "a data-paywall-trigger attribute, which is "
                              "the redaction-in-place pattern"))
    landed = ctx.landed_path()
    requested = (urlparse(ctx.requested).path or "").lower()
    if landed and any(landed.startswith(p) for p in PRICING_PATHS) \
            and requested and not any(
                requested.startswith(p) for p in PRICING_PATHS):
        structural.append(_sig("redirect", "corroborating",
                               "a content path redirected to a pricing path"))
    if ctx.status == 402:
        structural.append(_sig("status", "corroborating", "HTTP 402"))
    for needle in SAAS_SPECIFIC:
        if ctx.in_text(needle):
            corr.append(_sig("text", "corroborating", f"matched {needle!r}"))
    return [], structural + corr


def _detect_geo(ctx: _Ctx) -> tuple[list, list]:
    """Ships LOW CONFIDENCE by construction, and the corpus is why. Three
    region-locked broadcasters served complete, ordinary HTTP 200 documents
    to a Korean connection with no notice of any kind, because enforcement
    happens at the playback or API layer after the document loads. A geo
    block is largely undetectable from a landing page, so this category is
    capped at `possible` in `_confidence_for` and says so."""
    structural, corr = [], []
    if ctx.header("x-geo-blocked"):
        structural.append(_sig("header", "corroborating",
                               "a geo-block response header"))
    if ctx.status == 451:
        structural.append(_sig("status", "corroborating", "HTTP 451"))
    landed = ctx.landed_path()
    if landed and any(landed.startswith(p) for p in GEO_PATHS):
        structural.append(_sig("redirect", "corroborating",
                               "the navigation landed on a region-notice "
                               "path"))
    if structural:
        for needle in GEO_GATED:
            if ctx.in_text(needle):
                corr.append(_sig("text", "corroborating",
                                 f"matched {needle!r} (structural gate held)"))
    return [], structural + corr


def _detect_age(ctx: _Ctx) -> tuple[list, list]:
    block, structural, corr = [], [], []
    if ctx.structural.get("dob_form"):
        block.append(_sig("dom", "block-only",
                          "a date-of-birth form blocking the document"))
    for needle, detail in AGE_MARKUP:
        if ctx.in_source(needle) or needle in ctx.landed_path():
            structural.append(_sig("markup", "corroborating", detail))
            break
    if structural or block:
        for needle in AGE_GATED:
            if ctx.in_text(needle):
                corr.append(_sig("text", "corroborating",
                                 f"matched {needle!r} (structural gate held)"))
    return block, structural + corr


def _detect_consent(ctx: _Ctx) -> tuple[list, list]:
    """The blocking gate lives here, and it is the one gate no amount of
    offscreen text can fake: an overlay that answers `elementFromPoint` at
    the centre of the viewport IS blocking, by the only definition that
    matters. `__tcfapi` alone is NEVER-tier, since a site whose visitor
    already consented still exposes it."""
    block, structural, corr = [], [], []
    overlay = ctx.structural.get("blocking_overlay") or {}
    blocking = bool(overlay.get("present"))
    if not blocking:
        # THE BLOCKING OVERLAY IS NECESSARY, not merely helpful, and the
        # corpus is what settled it. A first cut let a named CMP vendor in
        # the source corroborate on its own, and it then classified a
        # Budweiser age gate, two academic paywalls, a 404 and a SAGE session
        # interstitial as consent walls, because a consent-management script
        # and the phrase "we use cookies" are on most of the commercial web.
        # A CMP that is installed is not a banner that is up, and only the
        # overlay tells the two apart. The consequence is that a consent wall
        # is not detectable from a raw HTTP response at all, which is stated
        # in `tests/unit/test_classify.py` rather than hidden.
        return [], []
    vendor = None
    for needle, name in CONSENT_VENDORS:
        if ctx.in_source(needle) or needle in str(
                ctx.structural.get("consent_container") or "").lower():
            vendor = name
            break
    if vendor:
        block.append(_sig("dom", "block-only",
                          f"a {vendor} consent container in an overlay that "
                          f"blocks interaction with the document"))
    else:
        structural.append(_sig("dom", "corroborating",
                               "an overlay that blocks interaction with the "
                               "document"))
    if structural or block:
        for needle in CONSENT_GATED:
            if ctx.in_text(needle):
                corr.append(_sig("text", "corroborating",
                                 f"matched {needle!r} (structural gate held)"))
                break
    return block, structural + corr


DETECTORS: tuple[tuple[str, object], ...] = (
    ("botwall", _detect_botwall),
    ("captcha", _detect_captcha),
    ("rate_limited", _detect_rate_limited),
    ("login_required", _detect_login),
    ("maintenance", _detect_maintenance),
    ("http_500", _detect_http_500),
    ("http_404", _detect_http_404),
    ("soft_404", _detect_soft_404),
    ("paywall_academic", _detect_paywall_academic),
    ("paywall_news", _detect_paywall_news),
    ("paywall_saas", _detect_paywall_saas),
    ("geo_blocked", _detect_geo),
    ("age_gated", _detect_age),
    ("gdpr_consent", _detect_consent),
)


# ------------------------------------------------------------- confidence

def _confidence_for(name: str, block: list, corr: list) -> str | None:
    if block:
        level = "confirmed"
    elif len(corr) >= 2:
        level = "probable"
    elif len(corr) == 1:
        level = "possible"
    else:
        return None
    if name == "geo_blocked" and level != "confirmed":
        # Capped deliberately. See `_detect_geo`.
        level = "possible"
    return level


def _maps_to_wall(name: str, confidence: str) -> str | None:
    """A category only reaches the `wall` vocabulary at `confirmed`.

    This is the compatibility seam and the honest one. `navigate` raises on
    `wall`, so anything that fills it in withholds a page, and withholding a
    page on corroboration alone is exactly the failure the tier contract
    exists to reduce. Every raise the classifier can newly cause therefore
    rests on a block-only signal: a vendor block header, a 401, a 429, a 202,
    a login redirect carrying a continuation parameter, or the soft-block
    pair."""
    if confidence != "confirmed":
        return None
    return WALL_FOR.get(name)


# ------------------------------------------------------------ the entrypoint

def classify(status: int | None, headers: dict | None = None, *,
             title: str = "", body: str = "", source: str = "",
             structural: dict | None = None,
             redirect_chain: list | None = None,
             landed_url: str | None = None,
             requested_url: str | None = None) -> dict:
    """Every category this response belongs to, with its evidence.

    MULTI-LABEL, because the corpus proves a single label is wrong: one
    fixture is a real 404 that also carries the site's age-gate markup, and
    another is simultaneously a consent wall and a news paywall. A caller
    told "404" and not "age gate" goes off fixing a URL that was never
    broken.

    Every input is optional and the confidence is honestly lower when fewer
    are supplied, because a classifier that demands a full probe cannot be
    called from the cheap path."""
    ctx = _Ctx(status, headers, title, body, source, structural,
               redirect_chain, landed_url, requested_url)
    found, ruled_out = [], []
    for name, detector in DETECTORS:
        try:
            block, corr = detector(ctx)
        except Exception:
            # A detector that throws costs its own category and nothing else.
            ruled_out.append(f"{name}: the detector did not complete")
            continue
        level = _confidence_for(name, block, corr)
        if level is None:
            if block or corr:
                ruled_out.append(
                    f"{name}: signals were found but none reached a category")
            continue
        found.append({"category": name, "confidence": level,
                      "evidence": block + corr})

    found.sort(key=lambda e: (-CONFIDENCE_RANK[e["confidence"]],
                              SEVERITY.index(e["category"])))
    result: dict = {
        "categories": found,
        "checked": len(DETECTORS),
    }
    if ctx.absent:
        result["inputs_absent"] = ctx.absent
    vendors = _walls.all_vendors(ctx.headers, ctx.title, ctx.body, ctx.source)
    if vendors:
        result["vendors"] = vendors
    if not found:
        result["category"] = None
        empty_document = (ctx.visible_chars < _walls.NO_READABLE_PROSE_CHARS
                          and (status is None or status == 200)
                          and not _walls.header_block(ctx.headers))
        if empty_document:
            # A THIRD OUTCOME, and it is not "no category". A 20KB
            # client-rendered shell with six visible characters after four
            # redirects is genuinely unknowable without executing the page,
            # and reporting "this reads as an ordinary page" there would be a
            # confident falsehood about a document nobody can read.
            result["confidence"] = "insufficient_evidence"
            result["note"] = NOTES["insufficient_evidence"]
            result["measured"] = {"visible_chars": ctx.visible_chars,
                                  "redirects": len(ctx.chain)}
        else:
            result["confidence"] = "none"
            result["note"] = NOTES["none"]
        if ruled_out:
            result["ruled_out"] = ruled_out
        return result

    top = found[0]
    result["category"] = top["category"]
    result["confidence"] = top["confidence"]
    result["evidence"] = top["evidence"]
    result["access_path"] = ACCESS_PATHS[top["category"]]
    if top["category"] == "geo_blocked":
        result["limitation"] = NOTES["geo_blocked_limitation"]
    if top["category"] == "paywall_saas":
        result["limitation"] = NOTES["paywall_saas_weak"]
    if ruled_out:
        result["ruled_out"] = ruled_out
    return result


def wall_for(classification: dict) -> tuple[str, str] | None:
    """The `wall` value this classification implies, or None.

    Reads the HIGHEST-SEVERITY confirmed category rather than the
    top-confidence one: a page that is both a bot wall and a consent wall is
    a bot wall. Returns `(wall, marker)`."""
    best = None
    for entry in classification.get("categories") or ():
        wall = _maps_to_wall(entry["category"], entry["confidence"])
        if wall is None:
            continue
        rank = SEVERITY.index(entry["category"])
        if best is None or rank < best[0]:
            best = (rank, wall, entry)
    if best is None:
        return None
    _rank, wall, entry = best
    details = "; ".join(sig["detail"] for sig in entry["evidence"][:3])
    return wall, f"{entry['category']}: {details}"
