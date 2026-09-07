# Error / Wall Page Fixture Corpus — Collection Notes

Collected 2026-09-07 (KST) by agent `dream-fixtures`. Egress IP: South Korea.
All samples are real responses from public hosts, fetched with `curl` (no browser, no JS execution),
one request per page, ≥2s apart, desktop Chrome User-Agent, robots.txt checked per host before fetching.
**No HTML in this corpus was written, edited, prettified, or fabricated.** Bodies are byte-for-byte as received.

- 38 host robots.txt files fetched and parsed (`_robots/`, with the evaluation scripts in `_tools/`)
- ~37 content fetches across 25 hosts
- 5 RSS/Crossref metadata calls used only to obtain *valid live URLs* so that fetches would not waste requests on dead links
- Per-sample metadata: `<category>/manifest.json`. Every `markers` string was grep-verified against the saved file
  by `_tools/build_manifests.py`; the build fails loudly on any marker it cannot find. Two markers were caught
  and corrected this way (an HTML-escaped `&amp;` in a title, and a truncated JSON-LD fragment).

---

## (a) Coverage

| Category | Collected | Negative controls | Not collected | Notes |
|---|---|---|---|---|
| `paywall_academic` | 3 | 1 | 0 | Science (Atypon), SAGE (Atypon), Nature (schema.org). OA Nature article kept as must-not-fire control. |
| `paywall_news` | 2 | 0 | 1 | FT (Zephr barrier page), Le Monde (teaser). NYT/WaPo/Economist unreachable — bot layer fires first. |
| `paywall_saas` | 1 | 1 | 1 | Statista inline redaction only. Crunchbase and SimilarWeb both botwalled. **Weakest category.** |
| `login_required` | 4 | 0 | 0 | GitHub, Dropbox (both redirect-with-return-param), SAGE cookie interstitial, Slack (deliberate hard case). |
| `geo_blocked` | 1 | 3 | 1 | Only Pandora exposes geo state in HTML. BBC/Channel 4/NRK all served normally. ITV dropped the TCP connection. |
| `age_gated` | 3 | 0 | 0 | Budweiser (server-rendered), Steam (`/agecheck/` path), Jack Daniel's (client-side, markup only). |
| `captcha` | 1 | 0 | 1 | NYT DataDome captcha (`'rt':'c'`). reCAPTCHA/hCaptcha not honestly triggerable. |
| `botwall` | 5 | 0 | 0 | **Best-covered category.** 4 vendors: Cloudflare ×2, DataDome ×2, AWS WAF ×1. |
| `maintenance` | 1 (synthetic) | 0 | 1 | No real maintenance window occurred. |
| `rate_limited` | 1 (synthetic) | 0 | 1 | Real 429 deliberately not induced — that would mean abusing a host. |
| `http_404` | 5 | 1 | 0 | Real 404s, a 400-instead-of-404, a 404 that is also age-gated, and an empty SPA shell control. |
| `http_500` | 2 (synthetic) | 0 | 1 | No genuine 5xx across 37 fetches. |
| `gdpr_consent` | 3 | 0 | 0 | Zeit (Sourcepoint, strong), Spiegel (weak), Le Monde (dual-labelled with paywall). |

**Totals: 38 manifest entries — 37 unique documents, since the Le Monde article is listed under both
`paywall_news` and `gdpr_consent` (one fetch, file copied). Of the 38: 4 synthetic status endpoints,
6 negative controls, 28 real-world positives. Plus 7 documented gaps recorded as `not_collected`.**

`content_length` in the manifests is the size of the saved file on disk (decompressed), which is larger
than the on-the-wire transfer size for the many hosts that served brotli or gzip.

Files ending `_NEGATIVE` are must-not-fire controls: real pages that carry a category's surface features
without belonging to it. They are the part of this corpus that measures precision.

---

## (b) Cross-category marker table

### Observed by category

| Category | HTTP status seen | Decisive headers | Decisive body markers | body_text_chars |
|---|---|---|---|---|
| `paywall_academic` | 200 | none | `Log in to view the full text`, `Restricted access`, `Purchase 24 hour online access to`, `"hasPart":{"isAccessibleForFree":false,"cssSelector":".main-content"...}` | 32,248–57,051 (high!) |
| `paywall_news` | 200 | `ft-access-decision-policy=DENIED_...`, `x-host: cp-next-barrier-page-*` | `<title>Subscribe to read</title>`, `edi_medium=paywall`, `"isAccessibleForFree": "False"` | 8,652 / 11,190 |
| `paywall_saas` | 200 | none | `data-paywall-trigger="true"` | 9,450 |
| `login_required` | 200 (after 302) | `Location: /login?cont=...` | `return_to`, `login_field`, `<title>Login or Sign Up...</title>`, `cookieAbsent` | 38–3,146 |
| `geo_blocked` | 302 → 200 | none | `unavailable in this country or region`, `<!-- restricted.vm -->` | 412 |
| `age_gated` | 200 (or 301→200) | none | `YOU MUST BE OF LEGAL DRINKING AGE`, `agecheck`, `age-gate`, `ageGate`, `birthdate` | 1,533–5,779 |
| `captcha` | 403 | `server: DataDome`, `x-datadome-riskscore` | `'rt':'c'`, `ct.captcha-delivery.com/c.js` | 55 |
| `botwall` | **403, and 202** | `Cf-Mitigated: challenge`, `X-DataDome: protected`, `x-amzn-waf-action: challenge` | `Just a moment...` / `One moment, please…`, `'rt':'i'` + `i.js`, `window.gokuProps` | 0–133 |
| `maintenance` | 503 | (none present) | none — 0-byte body | 0 |
| `rate_limited` | 429 | (no `Retry-After` present) | none — 0-byte body | 0 |
| `http_404` | 404, **and 400** | none | `Fehler 404`, `Leider gibt es die … Seite nicht`, `Noe gikk galt` | 6–2,900 |
| `http_500` | 500 | none | `500 Internal Server Error` (or nothing) | 0–25 |
| `gdpr_consent` | 200 | none | `__tcfapi`, `sourcepoint`, `Zustimmung` | 11,190–74,031 |

### AMBIGUOUS markers — do not classify on these alone

This is the section that matters. Every item below was observed in this corpus across more than one category.

1. **HTTP 403 is not a category.** It appeared in `botwall` (T&F, Economist, G2), in `captcha` (NYT), and it is
   also what GitHub would return for a private repo. Three different meanings, one status.
2. **HTTP 200 is not success.** Every paywall, every login wall, every consent wall, both age gates and the
   geo-block all finished on 200. Ten of the thirteen categories can present as 200.
3. **HTTP 202 is a block.** SimilarWeb's AWS WAF challenge returns `202 Accepted`. Any rule shaped
   "2xx means we got the page" passes a botwall straight through. This is the single most dangerous status
   assumption in the set.
4. **A 4xx is not necessarily the *right* 4xx.** NRK answered a missing page with `400 Bad Request`.
   Bucket by class (4xx), never by equality (`== 404`).
5. **`Server: cloudflare` means almost nothing.** It appears on `science.org` and `journals.sagepub.com`,
   which both returned complete articles, and on the T&F and Crunchbase challenges. The discriminator is
   **`Cf-Mitigated: challenge`**, not the server name. Likewise `Server: CloudFront` (SimilarWeb) and
   `X-Akamai-Transformed` (Channel 4) are CDN facts, not wall facts.
6. **`'rt':'c'` vs `'rt':'i'` is the entire captcha/botwall boundary.** `captcha/datadome_captcha_nytimes.html`
   and `botwall/datadome_block_economist.html` are the same DataDome template, same 403, same visible string
   `Please enable JS and disable any ad blocker`. Only the response-type field and the loaded script
   (`c.js` vs `i.js`) differ. Nothing human-readable separates a solvable captcha from a refusal.
7. **Cloudflare's title string is not stable.** T&F says `Just a moment...`; Crunchbase says `One moment, please…`
   (note the different ellipsis character). Title matching alone misses one of two samples from the same vendor.
8. **Two bot vendors can stack on one response.** G2 returned a DataDome body while also setting Cloudflare's
   `__cf_bm` cookie. Do not assume one wall per response, and do not stop at the first vendor match.
9. **A geo-looking signal is not a geo-block.** The Economist set `user_geo_country=KR` and then blocked on
   *bot score*. Correct geolocation plus a block is not a geo-block.
10. **`isAccessibleForFree` is unreliable in three separate ways.** Nature encodes it as a boolean (`false`);
    Le Monde encodes it as the **string** `"False"`, which fails a boolean check; and Statista reports
    `true` while redacting data values inline behind `data-paywall-trigger="true"`. Publisher-declared
    access metadata is a hint, never a verdict.
11. **Low `body_text_chars` is not a wall.** Dropbox's login wall has 38 chars, but so do Channel 4's normal
    homepage (44) and Notion's SPA shell (6). Meanwhile the Science paywall has 32,248 chars because the
    site chrome survives. Text length correlates with rendering strategy, not with blocking.
12. **`Sign in` / `Login` / `Subscribe` / the literal token `paywall` are everywhere.** All four appear in
    `paywall_saas/medium_free_story_NEGATIVE.html`, an ordinary free article. Substring matching on
    auth or subscription vocabulary generates false positives at scale.
13. **A redirect to `/login` means login; a redirect alone means nothing.** Nature's 303→302→302→200 chain
    passes through `idp.nature.com` on a fully open-access article. The signal is a *return/continuation
    parameter naming the original URL* (`return_to=`, `cont=`), not the presence of hops.
14. **One document can be two categories.** `http_404/jackdaniels_missing.html` is a real 404 that carries
    the site's age-gate markup. `gdpr_consent/lemonde_article.html` is simultaneously the paywall_news sample.
    A single-label classifier is provably wrong on both files. **Emit multi-label.**
15. **One host serves different walls on different paths.** `journals.sagepub.com` returned a normal article
    for a valid DOI, a `Restricted access` paywall on that same article body, and a
    `/action/cookieAbsent` session interstitial for an invalid DOI — all in this run. Host-level rules
    will not hold.
16. **`meta name="robots" content="noindex"`** appears on the Cloudflare challenge page but is standard on
    countless legitimate pages. Not a wall signal.

---

## (c) Categories not reliably detectable from HTML alone

**`geo_blocked` — largely undetectable.** Three of four samples (BBC iPlayer, Channel 4, NRK TV) are
region-locked services that served complete, unremarkable HTTP 200 documents to a Korean IP with no notice
of any kind. Enforcement happens at the playback/API layer after the document loads. ITV did not even
complete a TCP handshake (curl error 28, 0 bytes after 25s). **Needed instead:** the response to the
*media/API* request rather than the landing page; egress-IP country compared against a known availability
list; and a timeout-with-zero-bytes signal to catch network-level drops, which produce no document at all.

**`rate_limited` — status and headers only.** There is no body to classify; the entire signal is
`429` plus `Retry-After` / `X-RateLimit-*`. **Needed instead:** header inspection, plus request-count and
timing context from the caller (a 429 on request 1 means something different from a 429 on request 500).

**`maintenance` — indistinguishable from a transient 5xx without copy.** A bare `503` cannot be separated
from an overload or a deploy blip. **Needed instead:** `Retry-After` presence, and body text; a real
maintenance page says so in words. Note also that maintenance is inherently rare and unschedulable — this
gap closes by harvesting production traffic, not by collection runs.

**`http_500` — same.** No genuine 5xx occurred across 37 fetches to 25 hosts. Real server errors on major
sites are rare enough that they cannot be induced honestly. Status code is the whole signal.

**`captcha` vs `botwall` — needs vendor-internal fields.** As documented above, the two are visually and
textually identical under DataDome. **Needed instead:** parse the vendor config object (`rt`), or observe
which script URL is requested (`c.js` vs `i.js`), or detect whether an interactive widget
(`challenges.cloudflare.com/turnstile`, `recaptcha/api.js`, `hcaptcha.com/1/api.js`) is actually mounted.

**`paywall_saas` — poorly separable, and hard to collect.** Its vocabulary overlaps `paywall_news`
(subscribe/upgrade) and `login_required` (sign in), and the products with the crispest upgrade gates sit
behind the most aggressive bot protection, so an HTTP client never reaches the paywall. The one genuine
distinguishing pattern observed is **redaction-in-place**: complete prose with individual values swapped for
gated elements, rather than a barrier replacing the body.

**Anything client-rendered.** `notion_spa_shell_NEGATIVE.html` is 20KB of HTML with six visible characters
after a four-hop redirect across two domains. Whether it is a 404, a login wall, or a working page is
genuinely unknowable without executing JavaScript. Any corpus-trained classifier must have an
"insufficient evidence" output; forcing a label here is guessing.

### Practical ordering this corpus supports

Header evidence beat body evidence in every contested case (FT's `ft-access-decision-policy`,
Cloudflare's `Cf-Mitigated`, DataDome's `X-DataDome`, AWS's `x-amzn-waf-action`). A classifier should read,
in order: **vendor-specific headers → redirect chain shape and final URL → structured data (JSON-LD, with the
string/boolean caveat) → markup attributes and ids → visible text.** Visible text is the weakest and most
language-dependent signal — the SPIEGEL 404 contains no English "not found" anywhere.

END OF REPORT
