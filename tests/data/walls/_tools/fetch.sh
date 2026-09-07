#!/usr/bin/env bash
# usage: fetch.sh <category> <slug> <url>
FIX="C:/Users/nykal/AppData/Local/Temp/claude/C--Users-nykal-Documents-Obsidian-Vault/f925f48a-0998-429b-ab76-2bf0df1ee236/scratchpad/dream-specs/fixtures"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
ACC="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
cat="$1"; slug="$2"; url="$3"
d="$FIX/$cat"; mkdir -p "$d"
res=$(curl -sS -L --max-time 25 --compressed \
  -A "$UA" -H "Accept: $ACC" -H "Accept-Language: en-US,en;q=0.9" \
  -D "$d/$slug.headers" -o "$d/$slug.html" \
  -w '%{http_code} %{url_effective} %{size_download}' "$url" 2>"$d/$slug.err")
rc=$?
if [ $rc -ne 0 ]; then
  # single retry on transport error only
  sleep 3
  res=$(curl -sS -L --max-time 25 --compressed \
    -A "$UA" -H "Accept: $ACC" -H "Accept-Language: en-US,en;q=0.9" \
    -D "$d/$slug.headers" -o "$d/$slug.html" \
    -w '%{http_code} %{url_effective} %{size_download}' "$url" 2>"$d/$slug.err")
  rc=$?
fi
echo "[$cat/$slug] rc=$rc $res  src=$url"
