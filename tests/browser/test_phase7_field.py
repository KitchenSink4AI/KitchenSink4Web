"""Phase 7: the field-feedback punch list, proven through the real tools.

Each test here pins one accumulated ruling from the 2026-09-05 field
report (Developer Feedback/General Feedback/KS4Web_feedback_log.md):
auto-session inside navigate, malformed-URL refusals, scroll aliases,
check-before-wait for every wait_for condition, the find_elements role
filter, the get_page_view links mode, the type_text newline contract, and
the close-time auth-state offer.
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import BadParams
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets, readonly

pytestmark = pytest.mark.browser


_PAGE = """<!doctype html>
<title>Punch list fixture</title>
<body>
<main>
  <h1>An article about widgets</h1>
  <p>The discussion continues in <a href="/thread#c1">this comment</a> and
     also in <a href="/thread#c2">another comment</a> with more prose
     around <a href="/thread#c3">a third link</a>.</p>
  <button id="cmt">Comment</button>
  <a href="/comments">Comment policy</a>
  <span>Comment culture is discussed here too</span>
  <input id="single" aria-label="Comment title">
  <textarea id="multi" aria-label="Comment body"></textarea>
</main>
</body>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = _PAGE if self.path.startswith("/page") else \
            "<title>other</title><body><p>other</p></body>"
        data = body.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.send_header("set-cookie", "sid=abc123; Path=/")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    readonly.apply(False)
    yield
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


def test_first_navigate_opens_its_own_session(site):
    """Release condition 2: the manage_session round-trip (and its
    permission prompt) is optional; the first navigate creates the
    session and says so."""
    async def go():
        assert not MANAGER.sessions
        res = await lite.navigate(url=f"{site}/page")
        assert res["auto_session"]
        assert res["session"] in MANAGER.sessions
        assert res["status"] == 200
        # A second bare navigate reuses the session rather than stacking.
        res2 = await lite.navigate(url=f"{site}/page2")
        assert "auto_session" not in res2
        assert len(MANAGER.sessions) == 1
    run(go())


def test_malformed_urls_refuse_bad_params(site):
    async def go():
        page = (await lite.navigate(url=f"{site}/page"))["page"]
        with pytest.raises(BadParams) as no_scheme:
            await lite.navigate(page=page, url="example.com/x")
        assert "https://example.com/x" in str(no_scheme.value)
        with pytest.raises(BadParams):
            await lite.navigate(page=page, url="ht!tp:@@nonsense")
        with pytest.raises(BadParams):
            await lite.navigate(page=page, url="https://")
    run(go())


def test_scroll_accepts_the_alias_spellings(site):
    async def go():
        page = (await lite.navigate(url=f"{site}/page"))["page"]
        res = await lite.scroll(page=page, action="to_end")
        assert res["action"] == "end"
        res = await lite.scroll(page=page, action="bottom")
        assert res["action"] == "end"
        res = await lite.scroll(page=page, action="to_top")
        assert res["action"] == "top"
    run(go())


def test_wait_for_url_checks_before_waiting(site):
    """The field's URL wait expired on a navigation that had already
    finished. Every condition now checks current state first, and a URL
    value without wildcards matches as a substring."""
    async def go():
        page = (await lite.navigate(url=f"{site}/page"))["page"]
        res = await lite.wait_for(page=page, condition="url", value="/page",
                                  timeout_ms=2000)
        assert res["resolved"] is True
        assert "already" in res
        # And the text condition takes the same shortcut.
        res = await lite.wait_for(page=page, condition="text",
                                  value="widgets", timeout_ms=2000)
        assert "already" in res
    run(go())


def test_find_elements_role_filter_narrows(site):
    async def go():
        page = (await lite.navigate(url=f"{site}/page"))["page"]
        broad = await lite.find_elements(page=page, query="Comment")
        narrow = await lite.find_elements(page=page, query="Comment",
                                          role="button")
        assert broad["matched"] > narrow["matched"]
        assert narrow["matched"] == 1
        assert "role='button'" in narrow["results"]
    run(go())


def test_page_view_links_mode_includes_in_prose_links(site):
    async def go():
        page = (await lite.navigate(url=f"{site}/page"))["page"]
        plain = await lite.get_page_view(page=page)
        linked = await lite.get_page_view(page=page, mode="links")
        assert "suppressed by design" in plain["projection"]
        assert "included at the caller's request" in linked["projection"]
        assert "/thread#c3" in linked["projection"]
        assert "/thread#c3" not in plain["projection"]
    run(go())


def test_type_text_newline_contract(site):
    """Real newlines in a textarea, never Enter keydowns; a single-line
    control refuses text carrying one."""
    async def go():
        page = (await lite.navigate(url=f"{site}/page"))["page"]
        res = await lite.type_text(page=page, location={"css": "#multi"},
                                   text="line one\nline two")
        assert res["value_state"] == "line one\nline two"
        with pytest.raises(BadParams) as caught:
            await lite.type_text(page=page, location={"css": "#single"},
                                 text="title\noops")
        assert "single-line" in str(caught.value)
    run(go())


def test_close_offers_to_save_an_authenticated_state(site):
    """Ruling 6: never auto-save, always offer. The fixture sets a cookie,
    so the close response must say the login was NOT saved and name the
    route that keeps it."""
    async def go():
        res = await lite.navigate(url=f"{site}/page")
        closed = await lite.manage_session(action="close",
                                           session=res["session"])
        note = closed.get("auth_state") or ""
        assert "none were saved" in note
        assert "auth_state='save'" in note
    run(go())


def test_open_auth_state_needs_the_storage_pack(site):
    from kitchensink4web import packs
    async def go():
        await lite.manage_session(action="open",
                                  auth_state="C:/nonexistent/state.json")
    if packs.is_pack_loaded("storage"):
        pytest.skip("storage pack loaded in this process")
    with pytest.raises(BadParams) as caught:
        run(go())
    assert "--packs storage" in str(caught.value)
