# Changelog

### 1.0.1
- The server now says what it is. Its instructions line, the one block of its own prose a connected agent reads, opens by naming KitchenSink4Web, its PyPI package, and the KitchenSink4AI suite, and a new `get_server_info` tool answers the same question on request: product and package names, version, homepage and repository, the sibling servers, the tool surface registered in this process, and the test figures measured for this release. It is in the lite core, so it is present under the shipped read-only default, and its counts come from the live registry rather than from anything typed by hand.
- `survivors()` asked a creation time whether a process was alive, and a creation time answers a different question. Windows keeps `OpenProcess` succeeding on an exited process for as long as any handle to it remains, and the browser driver holds one for every browser it launched, so a killed browser kept counting as a survivor and `browser_alive()` reported a live browser after every process it owned was dead. The wait object answers liveness now; the creation time keeps its own job, which is defeating PID reuse.
- Published figures restamped from a live measurement: 20 lite tools, 53 with every pack loaded, and 2,066 tests of which 733 drive a real browser. The pack roster in `docs/llms.txt` was two waves behind and now lists what the server registers.

### 1.0.0
- First public release: a browser built for AI agents. Budgeted page reads with an honest account of what went unread, real-browser lanes, a consent ladder that cannot be talked out of payments or credentials, structured extraction with named evidence, monitors, workflows, session transfer, and an accessibility audit. Read-only out of the box.
