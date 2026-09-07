import os
from urllib.robotparser import RobotFileParser
FIX=os.environ['FIX']
for host,path in [("www.statista.com","/statistics/272014/global-social-networks-ranked-by-number-of-users/"),
                  ("medium.com","/some-member-story-abc123"),
                  ("www.ticketmaster.com","/"),
                  ("www.budweiser.com","/")]:
    rp=RobotFileParser()
    try:
        rp.parse(open(os.path.join(FIX,"_robots",host+".txt"),encoding="utf-8",errors="replace").read().splitlines())
        ok=rp.can_fetch("Mozilla/5.0","https://"+host+path)
    except Exception as e:
        ok="ERR "+str(e)
    print(("ALLOW" if ok is True else "DENY "), host+path)
