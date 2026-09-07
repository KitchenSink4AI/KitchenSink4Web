import os
from urllib.robotparser import RobotFileParser
FIX = os.environ['FIX']
cands = [
 ("app.slack.com","/client"),
 ("www.dropbox.com","/home"),
 ("www.nature.com","/articles/s41586-021-03819-2"),
 ("www.cambridge.org","/core/journals/american-political-science-review/article/abs/x/ABCDEF"),
 ("www.thetimes.co.uk","/article/some-article-abc"),
 ("www.lemonde.fr","/international/article/2024/01/01/x_123_3.html"),
 ("httpbin.org","/status/500"),
]
for host, path in cands:
    f = os.path.join(FIX, "_robots", host + ".txt")
    rp = RobotFileParser()
    with open(f, "r", encoding="utf-8", errors="replace") as fh:
        rp.parse(fh.read().splitlines())
    ok = rp.can_fetch("Mozilla/5.0", "https://"+host+path)
    print(f"{'ALLOW' if ok else 'DENY '} {host}{path}")
print("--- httpbin robots.txt ---")
print(open(os.path.join(FIX,"_robots","httpbin.org.txt")).read())
