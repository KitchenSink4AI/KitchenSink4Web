"""The read-only field test's four hygiene findings, proven fixed.

Report: internal notes/20260905_ks4web_readonly_field_
test.md, section 4. Each finding below was observed live on the real web and
each fix has a regression here:

- (a) a raw Playwright string ("Execution context was destroyed") rode out
  of press_keys through the refusal envelope: the wrapper backstop and the
  verify-during-navigation guard both close it;
- (b) three wall-classifier misses (a 202 anomaly shell, a 503 sorry page, a
  login redirect) now carry honest wall labels;
- (c) type_text gains submit=true, the one-call search idiom;
- (d) the CREDENTIAL_REFUSED copy names only routes that exist (covered in
  test_phase4_actions and test_credentials).
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets, readonly

pytestmark = pytest.mark.browser


class _WallHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html", extra=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        for k, v in (extra or {}):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/anomaly":
            self._send(202, "<title>Just a moment</title><body>"
                            "<p>Verifying</p></body>")
        elif self.path == "/sorry":
            self._send(503, "<title>Sorry!</title><body>"
                            "<h1>Sorry! Something went wrong.</h1></body>")
        elif self.path == "/protected":
            self.send_response(302)
            self.send_header("location", "/login")
            self.end_headers()
        elif self.path == "/login":
            self._send(200, "<title>Sign in</title><body>"
                            "<form><input type=text></form></body>")
        elif self.path == "/search":
            self._send(200, "<title>Search</title><body>"
                            "<form action='/results' method='get'>"
                            "<input name='q' id='q'></form></body>")
        elif self.path.startswith("/results"):
            self._send(200, "<title>Results</title><body>"
                            "<h1>Results page</h1></body>")
        elif self.path == "/ok":
            self._send(200, "<title>Fine</title><body><p>ok</p></body>")
        else:
            self._send(404, "<title>nope</title>")


@pytest.fixture(scope="module")
def wall_site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _WallHandler)
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


async def _open(site, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    return session, page


def test_202_anomaly_shell_is_a_wall(wall_site):
    async def go():
        _, page = await _open(wall_site, "")
        res = await lite.navigate(page=page, url=f"{wall_site}/anomaly")
        # A 202 top-level load is flagged rather than reported as content.
        # (The "just a moment" title also trips the marker; either way the
        # verdict is a wall, which is the fix: it was null in the field.)
        return res
    # navigate raises BlockedBySite on a wall verdict, so a clean return is
    # a failure of the classifier; assert the raise.
    from kitchensink4web.errors import BlockedBySite
    with pytest.raises(BlockedBySite):
        run(go())


def test_503_sorry_page_is_a_wall(wall_site):
    from kitchensink4web.errors import BlockedBySite
    async def go():
        _, page = await _open(wall_site, "")
        await lite.navigate(page=page, url=f"{wall_site}/sorry")
    with pytest.raises(BlockedBySite):
        run(go())


def test_login_redirect_is_an_auth_wall(wall_site):
    from kitchensink4web.errors import AuthRequired
    async def go():
        _, page = await _open(wall_site, "")
        await lite.navigate(page=page, url=f"{wall_site}/protected")
    with pytest.raises(AuthRequired):
        run(go())


def test_deliberately_opening_a_login_page_is_not_a_wall(wall_site):
    """The redirect classifier must not fire when the login page was the
    requested destination: only a REDIRECT to login is a wall."""
    async def go():
        _, page = await _open(wall_site, "")
        res = await lite.navigate(page=page, url=f"{wall_site}/login")
        assert res["verdict"]["wall"] is None
    run(go())


async def _confirmed(call):
    """Run a gated call the way the server's elicitation plumbing does: let
    the first pass ASK, redeem the gate a human would have answered, deposit
    it, and run the same call again.

    Both callers below submit a real form, and since 2026-09-06 a submission
    is a gated class on EVERY path that can cause one rather than only on a
    click (gauntlet 2 C1/H1). These tests are about what the call DOES once
    it is allowed to run, so they answer the gate rather than dodge it."""
    from kitchensink4web.errors import ConfirmationRequired
    from kitchensink4web.policy import gates
    try:
        return await call()
    except ConfirmationRequired as ask:
        grant = gates.ENGINE.redeem(ask.detail["requestState"],
                                    {"allow": True})
        gates.deposit_grant(grant)
        try:
            return await call()
        finally:
            gates.clear_grant()


def test_type_text_submit_navigates_in_one_call(wall_site):
    """The submit idiom: type the query and submit, landing on the results
    page, in a single call rather than a type plus a racing Enter."""
    async def go():
        _, page = await _open(wall_site, "")
        await lite.navigate(page=page, url=f"{wall_site}/search")
        res = await _confirmed(lambda: lite.type_text(
            page=page, location={"css": "#q"}, text="widgets", submit=True))
        assert "/results" in res["url"]
        assert res["changed"]["effect"] == "navigated"
    run(go())


def test_verify_during_navigation_never_leaks_a_raw_driver_string(wall_site):
    """The press_keys leak (finding a): a keystroke that navigates mid-verify
    must resolve to an honest navigated outcome, never a raw Playwright
    'Execution context was destroyed' string riding out of the envelope."""
    async def go():
        _, page = await _open(wall_site, "")
        await lite.navigate(page=page, url=f"{wall_site}/search")
        # Focus the field, then press Enter to submit: the verify probe races
        # the navigation exactly as the field report's press_keys did.
        res = await _confirmed(lambda: lite.press_keys(
            page=page, keys="Enter", location={"css": "#q"}))
        blob = str(res)
        assert "Execution context was destroyed" not in blob
        assert "Traceback" not in blob
    run(go())
