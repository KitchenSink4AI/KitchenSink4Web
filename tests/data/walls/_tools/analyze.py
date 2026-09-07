import sys, os, re, html
CANDS = [
 "Just a moment...", "cf-browser-verification", "challenges.cloudflare.com", "cf_chl_opt",
 "Enable JavaScript and cookies to continue", "DataDome", "captcha-delivery.com", "px-captcha",
 "_pxhd", "Access to this page has been denied", "PerimeterX", "Attention Required",
 "isAccessibleForFree", "Institutional access", "institutional access", "Sign in via your institution",
 "Get full access to this article", "Purchase this article", "Add to cart", "Buy this article",
 "subscribe", "Subscribe", "Subscription", "paywall", "Paywall", "meteredContent", "metered",
 "Already a subscriber", "Sign In", "Sign in", "Log in", "Login", "login",
 "noindex", "Retry-After", "429", "Too Many Requests",
 "not available in your country", "not available in your region", "only available in the UK",
 "geo", "geoblock", "geo-restrict", "unavailable in your location",
 "age", "Are you over", "of legal drinking age", "birthdate", "age-gate", "agecheck", "Enter your date of birth",
 "maintenance", "Maintenance", "temporarily unavailable", "be right back",
 "404", "Page Not Found", "page not found", "Not Found", "not found",
 "__tcfapi", "consent", "Consent", "Zustimmung", "Akzeptieren", "Einwilligung", "Cookies akzeptieren",
 "sourcepoint", "onetrust", "OneTrust", "quantcast", "Sirdata", "didomi", "Didomi", "usercentrics",
 "Accepter", "Accepter et continuer", "Continuer sans accepter",
 "recaptcha", "reCAPTCHA", "hcaptcha", "turnstile", "Turnstile",
 "This story is for members", "member-only", "Upgrade to", "Premium", "premium",
]
def visible_text(h):
    h = re.sub(r'(?is)<(script|style|noscript|template)[^>]*>.*?</\1>', ' ', h)
    h = re.sub(r'(?s)<!--.*?-->', ' ', h)
    h = re.sub(r'(?s)<[^>]+>', ' ', h)
    h = html.unescape(h)
    return re.sub(r'\s+', ' ', h).strip()
for p in sys.argv[1:]:
    body = open(p, encoding='utf-8', errors='replace').read()
    hp = p[:-5] + '.headers'
    hdrs = open(hp, encoding='utf-8', errors='replace').read() if os.path.exists(hp) else ''
    vt = visible_text(body)
    print("="*70)
    print("FILE:", os.path.basename(p), "| html_bytes:", len(body.encode('utf-8','replace')), "| visible_text_chars:", len(vt))
    st = [l for l in hdrs.splitlines() if l.startswith('HTTP/')]
    print("STATUS LINES:", st)
    interesting = [l.strip() for l in hdrs.splitlines() if re.match(r'(?i)^(server|cf-|x-|retry-after|location|set-cookie|content-type|www-authenticate|vary|x-robots)', l)]
    print("HDRS:", "; ".join(interesting[:14]))
    ti = re.search(r'(?is)<title[^>]*>(.*?)</title>', body)
    print("TITLE:", html.unescape(ti.group(1)).strip()[:160] if ti else None)
    hits = sorted({c for c in CANDS if c in body}, key=len, reverse=True)
    print("MARKERS:", hits[:40])
    print("TEXT HEAD:", vt[:400])
