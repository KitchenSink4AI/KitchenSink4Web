import sys, os
from urllib.robotparser import RobotFileParser
FIX = os.environ['FIX']
UA = "Mozilla/5.0"
cands = [
 ("www.science.org","/doi/10.1126/science.aac4716"),
 ("link.springer.com","/article/10.1007/s00268-021-06012-8"),
 ("www.tandfonline.com","/doi/full/10.1080/09636412.2019.1604982"),
 ("journals.sagepub.com","/doi/10.1177/0022002720960128"),
 ("www.wsj.com","/articles/some-article-abc123"),
 ("www.ft.com","/content/abc-123"),
 ("www.nytimes.com","/2020/02/26/opinion/coronavirus-trump.html"),
 ("www.economist.com","/leaders/2024/01/01/some-leader"),
 ("www.linkedin.com","/feed/"),
 ("x.com","/home"),
 ("github.com","/torvalds/linux-does-not-exist-zzz"),
 ("www.notion.so","/some-private-page-abc"),
 ("store.steampowered.com","/agecheck/app/1174180/"),
 ("www.jackdaniels.com","/"),
 ("www.spiegel.de","/"),
 ("www.zeit.de","/"),
 ("www.bbc.co.uk","/iplayer"),
 ("www.hulu.com","/"),
 ("www.pandora.com","/"),
 ("www.g2.com","/products/slack/reviews"),
]
for host, path in cands:
    f = os.path.join(FIX, "_robots", host + ".txt")
    rp = RobotFileParser()
    try:
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            rp.parse(fh.read().splitlines())
        ok = rp.can_fetch(UA, "https://"+host+path)
    except Exception as e:
        ok = "ERR:"+str(e)
    print(f"{'ALLOW' if ok is True else 'DENY '} {host}{path}")
