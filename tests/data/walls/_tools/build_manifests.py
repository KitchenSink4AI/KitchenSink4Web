import os, re, json, html, datetime
FIX = os.environ['FIX']

def visible_text(h):
    h = re.sub(r'(?is)<(script|style|noscript|template)[^>]*>.*?</\1>', ' ', h)
    h = re.sub(r'(?s)<!--.*?-->', ' ', h)
    h = re.sub(r'(?s)<[^>]+>', ' ', h)
    return re.sub(r'\s+', ' ', html.unescape(h)).strip()

def parse_headers(p):
    if not os.path.exists(p): return [], {}, []
    raw = open(p, encoding='utf-8', errors='replace').read()
    blocks = re.split(r'\r?\n\r?\n', raw)
    statuses, last = [], {}
    locations = []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if not lines or not lines[0].startswith('HTTP/'): continue
        statuses.append(lines[0].strip())
        d = {}
        for l in lines[1:]:
            if ':' in l:
                k, v = l.split(':', 1); d[k.strip().lower()] = v.strip()
        if 'location' in d: locations.append(d['location'])
        last = d
    return statuses, last, locations

def when(hdrs):
    d = hdrs.get('date')
    if not d: return None, None
    try:
        dt = datetime.datetime.strptime(d, '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None, None
    kst = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ'), kst.strftime('%Y-%m-%dT%H:%M:%S+09:00')

SPEC = json.load(open(os.path.join(FIX, '_tools', 'spec.json'), encoding='utf-8'))
unverified = []
for cat, entries in SPEC.items():
    out = []
    for e in entries:
        if e.get('status') == 'not_collected':
            out.append(e); continue
        slug = e['slug']
        bp = os.path.join(FIX, cat, slug + '.html')
        hp = os.path.join(FIX, cat, slug + '.headers')
        body = open(bp, encoding='utf-8', errors='replace').read()
        raw_bytes = os.path.getsize(bp)
        statuses, lasth, locs = parse_headers(hp)
        code = int(statuses[-1].split()[1]) if statuses else None
        u_utc, u_kst = when(lasth)
        good, bad = [], []
        for m in e['markers']:
            (good if m['s'] in body or (m.get('hdr') and m['s'].lower() in open(hp,encoding='utf-8',errors='replace').read().lower()) else bad).append(m['s'])
        if bad: unverified.append((cat, slug, bad))
        rec = {
            "url": e['url'],
            "fetched_utc": u_utc, "fetched_kst": u_kst,
            "category": cat,
            "http_status": code,
            "status_chain": [s.split(None,2)[1] for s in statuses],
            "final_url": e['final_url'],
            "content_length": raw_bytes,
            "robots_allowed": e['robots'],
            "markers": good,
            "distinguishing_from": e['dist'],
            "body_text_chars": len(visible_text(body)),
            "status": "collected",
            "files": {"html": slug + ".html", "headers": slug + ".headers"},
            "notes": e['notes'],
        }
        if e.get('synthetic'): rec["synthetic_endpoint"] = True
        if e.get('negative'): rec["negative_control"] = True
        out.append(rec)
    with open(os.path.join(FIX, cat, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"{cat}: {sum(1 for r in out if r.get('status')=='collected')} collected, {sum(1 for r in out if r.get('status')=='not_collected')} not_collected")
print()
if unverified:
    print("!! UNVERIFIED MARKERS (dropped):")
    for c,s,b in unverified: print("  ", c, s, b)
else:
    print("ALL MARKERS VERIFIED PRESENT IN SAVED FILES")
