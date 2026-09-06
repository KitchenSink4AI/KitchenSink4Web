"""Local deterministic fixture server for the KS4Web engine spikes (S3/S4/latency).

Everything the BiDi gap probes need lives here so no spike depends on a live
site: POST echo, a download, HTTP basic auth, a redirect that echoes headers,
a CSS-transformed click target, locale/timezone readout, and a synthetic
heavy-DOM page for the latency probe.

Run standalone:  python -X utf8 fixtures_server.py [port]
"""
import base64
import http.server
import json
import socketserver
import sys
import threading
import time

AUTH_USER = "spikeuser"
AUTH_PASS = "spikepass"

INDEX = """<!doctype html><html><head><title>KS4Web spike fixtures</title></head>
<body><h1>fixtures</h1><ul>
<li><a id="lnk-form" href="/form">form</a></li>
<li><a id="lnk-dl" href="/download">download</a></li>
<li><a id="lnk-auth" href="/auth">auth</a></li>
</ul><p id="marker">INDEX-OK</p></body></html>"""

FORM = """<!doctype html><html><head><title>fixture form</title></head><body>
<h1>Form fixture</h1>
<form method="POST" action="/echo">
  <label for="name">Name</label><input id="name" name="name" type="text">
  <label for="msg">Message</label><textarea id="msg" name="msg"></textarea>
  <select id="color" name="color"><option value="r">red</option><option value="b">blue</option></select>
  <input id="chk" name="chk" type="checkbox">
  <button id="submit" type="submit">Send</button>
</form>
<p id="marker">FORM-OK</p>
<button id="counter" onclick="document.getElementById('count').textContent=
  String(Number(document.getElementById('count').textContent)+1)">bump</button>
<span id="count">0</span>
</body></html>"""

DOWNLOAD_PAGE = """<!doctype html><html><head><title>download fixture</title></head><body>
<a id="dl" href="/file.txt" download="spike.txt">download me</a>
<p id="marker">DL-OK</p></body></html>"""

TRANSFORM = """<!doctype html><html><head><title>transform fixture</title>
<style>
#outer{position:absolute;top:120px;left:140px;transform:rotate(37deg) scale(1.6);}
#tgt{width:120px;height:40px;background:#cde;}
</style></head><body>
<div id="outer"><button id="tgt" onclick="document.getElementById('res').textContent='CLICKED'">target</button></div>
<p id="res">none</p></body></html>"""

LOCALE = """<!doctype html><html><head><title>locale fixture</title></head><body>
<p id="tz"></p><p id="lang"></p><p id="date"></p>
<script>
document.getElementById('tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
document.getElementById('lang').textContent = navigator.language;
document.getElementById('date').textContent = new Date(0).toString();
</script></body></html>"""

POSTER = """<!doctype html><html><head><title>poster fixture</title></head><body>
<p id="out">idle</p>
<script>
window.doPost = async () => {
  const r = await fetch('/echo', {method:'POST', headers:{'content-type':'application/json'},
                                 body: JSON.stringify({hello:'world', n:42})});
  const t = await r.text();
  document.getElementById('out').textContent = t;
  return t;
};
</script></body></html>"""


#: A 1x1 PNG, the smallest honest image document.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg==")

#: A minimal one-page PDF. Valid enough for a viewer to accept and for a
#: fetch to save; the test that matters is the media type, not the glyphs.
TINY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n")

CLIPBOARD_PAGE = """<html><body>
<button id="copy" onclick="navigator.clipboard.writeText('copied by the page')">Copy</button>
<p id="marker">clipboard fixture</p>
</body></html>"""


def big_page(n: int) -> str:
    """Synthetic heavy DOM: n nodes, mixed interactive / hidden / styled."""
    parts = ["<!doctype html><html><head><title>big fixture %d</title><style>" % n,
             ".hid{display:none}.ghost{color:#fff;background:#fff}",
             ".tiny{font-size:0.4px}.offs{position:absolute;left:-9999px}",
             "section{border:1px solid #eee;margin:2px}</style></head><body>",
             "<header><nav><a href='/'>home</a><a href='/form'>form</a></nav></header>",
             "<main>"]
    per = 10  # nodes emitted per block
    blocks = max(1, n // per)
    for i in range(blocks):
        cls = ["", "hid", "ghost", "tiny", "offs"][i % 5]
        parts.append(
            "<section class='%s'><h3>Heading %d</h3>"
            "<p>Paragraph %d with some words that make the digest do work.</p>"
            "<ul><li><a href='#a%d'>link %d</a></li><li><span>plain %d</span></li></ul>"
            "<button id='b%d'>button %d</button>"
            "<input id='i%d' type='text' aria-label='field %d'></section>"
            % (cls, i, i, i, i, i, i, i, i, i))
    parts.append("</main><footer><p id='marker'>BIG-OK</p></footer></body></html>")
    return "".join(parts)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, body, code=200, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        q = self.path.split("?")[1] if "?" in self.path else ""
        if path == "/":
            return self._send(INDEX)
        if path == "/form":
            return self._send(FORM)
        if path == "/download":
            return self._send(DOWNLOAD_PAGE)
        if path == "/file.txt":
            return self._send("spike download payload\n" * 20, ctype="text/plain",
                              extra={"Content-Disposition": 'attachment; filename="spike.txt"'})
        if path == "/transform":
            return self._send(TRANSFORM)
        if path == "/locale":
            return self._send(LOCALE)
        if path == "/poster":
            return self._send(POSTER)
        if path == "/headers":
            return self._send(json.dumps(dict(self.headers.items()), indent=1),
                              ctype="application/json")
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/headers")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/auth":
            hdr = self.headers.get("Authorization", "")
            want = "Basic " + base64.b64encode(
                ("%s:%s" % (AUTH_USER, AUTH_PASS)).encode()).decode()
            if hdr == want:
                return self._send("<html><body><p id='marker'>AUTH-OK</p></body></html>")
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="spike"')
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"denied\r\n\r\n"[:9])
            return
        # --- small-parts wave fixtures -------------------------------------
        # A three-part series wired with rel="next", which is what the
        # paginate-until read follows. Part 3 publishes no next link, so the
        # walk has an honest end rather than a cap.
        if path.startswith("/series/"):
            try:
                n = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self._send("<h1>404</h1>", code=404)
            nxt = ('<link rel="next" href="/series/%d">' % (n + 1)
                   if n < 3 else "")
            return self._send(
                "<html><head><title>Series part %d</title>%s</head><body>"
                "<main><h1>Part %d</h1><p>%s</p></main></body></html>"
                % (n, nxt, n, ("series body paragraph %d. " % n) * 40))
        # Two pages whose next links point at each other: the loop stop.
        if path in ("/loop/a", "/loop/b"):
            other = "/loop/b" if path.endswith("a") else "/loop/a"
            return self._send(
                '<html><head><link rel="next" href="%s"></head><body>'
                '<p>%s</p></body></html>' % (other, "loop body " * 30))
        # A real image document: `document.contentType` is image/png and the
        # browser paints it, which is the escape case in its most portable
        # form.
        if path == "/pixel.png":
            return self._send(PIXEL_PNG, ctype="image/png")
        if path == "/doc.pdf":
            return self._send(TINY_PDF, ctype="application/pdf")
        if path == "/clipboard":
            return self._send(CLIPBOARD_PAGE)
        if path == "/hang":
            time.sleep(120)  # never answers within any sane timeout
            return self._send("too late")
        if path == "/big":
            n = 20000
            for kv in q.split("&"):
                if kv.startswith("n="):
                    n = int(kv[2:])
            return self._send(big_page(n))
        return self._send("<h1>404</h1>", code=404)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(ln).decode("utf-8", "replace")
        return self._send(json.dumps({"echo": body, "ctype": self.headers.get("content-type")}),
                          ctype="application/json")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(port=0):
    srv = Server(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    srv, base = start(p)
    print("serving", base)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
