"""Local deterministic fixture server for S9 (Chrome/Edge lane probes).

Adds what the engine fixture server lacks: cookie mint / cookie echo with
SERVER-SIDE observation (the ABE probe reads what the browser actually sent,
never the page), plus a small interactive page for the drive batteries.

127.0.0.1 only. Never networked beyond loopback.
"""
import http.server
import json
import socketserver
import threading
import time
from urllib.parse import urlparse, parse_qs

COOKIE_NAME = "ks4web_s9_abe"
COOKIE_VALUE = "SPIKE9-COOKIE-VALUE-20260905"

PAGE = """<!doctype html><html><head><title>s9 fixture</title></head><body>
<h1 id="hdr">S9 fixture</h1>
<button id="bump" onclick="document.getElementById('count').textContent=
  String(Number(document.getElementById('count').textContent)+1)">bump</button>
<span id="count">0</span>
<input id="field" type="text">
<a id="lnk" href="/other">other page</a>
<p id="marker">S9-INDEX-OK</p></body></html>"""

OTHER = """<!doctype html><html><head><title>s9 other</title></head><body>
<p id="marker">S9-OTHER-OK</p></body></html>"""

EVENTS = []          # server-side observation log
_LOCK = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _html(self, body, extra_headers=()):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        with _LOCK:
            EVENTS.append({"t": time.time(), "path": u.path,
                           "tag": (q.get("tag") or [""])[0],
                           "cookie": self.headers.get("Cookie", "")})
        if u.path == "/":
            self._html(PAGE)
        elif u.path == "/other":
            self._html(OTHER)
        elif u.path == "/set-cookie":
            exp = "Expires=Fri, 04 Sep 2027 00:00:00 GMT"
            self._html(
                "<!doctype html><title>cookie set</title><p id='marker'>COOKIE-SET</p>",
                extra_headers=[("Set-Cookie",
                                "%s=%s; %s; Path=/" % (COOKIE_NAME, COOKIE_VALUE, exp))])
        elif u.path == "/cookie-echo":
            got = self.headers.get("Cookie", "")
            self._html("<!doctype html><title>cookie echo</title>"
                       "<p id='marker'>ECHO:%s</p>" % got)
        elif u.path == "/events":
            data = json.dumps(EVENTS).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(port=8853):
    srv = Server(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % port


def events_since(t0):
    with _LOCK:
        return [e for e in EVENTS if e["t"] >= t0]


if __name__ == "__main__":
    srv, base = start()
    print("serving at", base)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
