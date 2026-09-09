"""Lane C against a page that only a logged-in browser can see.

THE STAND-IN FOR THE ONE TEST NOBODY HAS RUN. Every fixture in phases 1 to
4 is a local page any browser could fetch, so the claim the whole lane
exists to make, that an agent can read what the human is already logged
into without ever handling the human's credentials, has been argued from
architecture rather than shown. This file shows it on a server that really
does refuse anonymous readers.

What is synthetic here and what is not, stated plainly so nobody reads more
into a green run than it earns:

  REAL      the cookie jar, the redirect for an unauthenticated request, the
            member-only content that is absent before the cookie exists and
            present after, the extension reading it through an ordinary
            content script, the classifier's verdict on a real password
            form, and the refusals.
  SYNTHETIC the login itself. A human types their password into their own
            window; nothing in this project may. So the browser establishes
            the cookie out of band, through a route that stands in for the
            human having signed in before the agent was asked to do
            anything. That is the same posture the morning acceptance run
            takes against JSTOR, WSJ and Zoho: sign in first, then ask.
  UNTESTED  a real identity provider, a real session cookie's flags, a
            single-sign-on redirect chain, and anything that depends on a
            site the author actually pays for. Those are the author's step
            and this file does not replace it.
"""

from __future__ import annotations

import asyncio
import http.cookies
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kitchensink4web import anchors                              # noqa: E402
from kitchensink4web.engine import lanes                         # noqa: E402
from kitchensink4web.engine import session as _session           # noqa: E402
from kitchensink4web.errors import (ConfirmationRequired,        # noqa: E402
                                    CredentialRefused)
from kitchensink4web.extension import lane as _extlane           # noqa: E402
from kitchensink4web.extension import register                   # noqa: E402
from kitchensink4web.extension.bridge import (Bridge,            # noqa: E402
                                              BridgeError)
from kitchensink4web.ops import extops                           # noqa: E402
from kitchensink4web.policy import consent, readonly             # noqa: E402
from tests.fixtures.firefox_harness import (                     # noqa: E402
    HeadlessFirefox, RDPClient, find_firefox, free_port)

pytestmark = pytest.mark.browser

#: The password sitting in the login form's value attribute. A real login
#: page does not ship one; this one does so the "never leaves the page" pin
#: has something that COULD leak rather than an empty string that cannot.
PASSWORD = "hunter2-never-leaves-the-page"

#: Two cookies, and the pair is the point. `ks4session` is HttpOnly, so page
#: script cannot see it and only the server ever does. `ks4visible` is not,
#: so `document.cookie` in the page's own world returns it. An extractor
#: that scraped cookies would leak the second one while the first stayed
#: safe, which is exactly the failure a test using only an HttpOnly cookie
#: would miss.
SESSION_COOKIE = "ks4session-9f2a4c7e1b6d8035-secret"
VISIBLE_COOKIE = "ks4visible-3e7b1d9a5c024f68-secret"

#: Present in the members-only article and nowhere else. A read that
#: contains this string came from a session the server accepted.
MEMBER_MARK = "MEMBER-ONLY-LEDGER-4471"

LOGIN = f"""<!doctype html>
<title>KS4Web member sign in</title>
<body>
  <h1>Sign in</h1>
  <p>Members only beyond this point.</p>
  <form method="post" action="/login">
    <label for="user">Username</label>
    <input id="user" name="user" type="text" autocomplete="username"
           value="reader">
    <label for="pw">Password</label>
    <input id="pw" name="pw" type="password" autocomplete="current-password"
           value="{PASSWORD}">
    <button id="signin" type="submit">Sign in</button>
  </form>
  <a id="about" href="/public">About this archive</a>
</body>
"""

ACCOUNT = """<!doctype html>
<title>KS4Web member account</title>
<body>
  <h1>Account</h1>
  <p>Signed in as reader@example.test</p>
  <a id="read" href="/article">Read the members-only report</a>
  <a id="docs" href="/public">Public documents</a>
  <form method="get" action="/search">
    <label for="q">Search the archive</label>
    <input id="q" name="q" type="search">
    <button id="go" type="submit">Search</button>
  </form>
  <form method="post" action="/close">
    <button id="close" type="submit">Delete my account</button>
  </form>
</body>
"""

#: THE PAGE SHAPED LIKE THE ONE THE AUTHOR WILL ACTUALLY TEST. The morning
#: run reads a paywalled article, not a dashboard, and the projection treats
#: the two differently: an app-shaped page gets its prose summarized down to
#: a character count, while an article-shaped one gets the prose itself. A
#: fixture with three sentences on it would have proved the read reached the
#: page without ever proving the reader could see what was written there.
ARTICLE = f"""<!doctype html>
<title>KS4Web members-only report</title>
<body>
  <main>
    <article>
      <h1>The quarterly ledger</h1>
      <p>{MEMBER_MARK}. This paragraph sits behind the session cookie and
         no anonymous request will ever be handed it, which is the whole
         point of putting it here rather than on the public page.</p>
      <p>The archive holds forty years of quarterly returns, and the
         members-only report is the part that is not syndicated anywhere
         else. A reader without a session gets the sign-in page instead,
         with the same status code an ordinary redirect carries.</p>
      <p>Nothing on this page asks for a password, carries a payment field
         or destroys anything, so a reader working through it should never
         see a confirmation prompt. That absence is as much a part of the
         test as the refusals are.</p>
      <p>The last section is deliberately long enough that the projection
         treats the document as prose rather than as an application, since
         the two shapes are budgeted differently and only one of them puts
         the sentences in front of the caller.</p>
    </article>
  </main>
  <a id="back" href="/account">Back to the account</a>
</body>
"""

PUBLIC = """<!doctype html>
<title>KS4Web public documents</title>
<body><h1>Public documents</h1><p>Anyone may read this.</p>
<a href="/account">Back to the account</a></body>
"""

RESULTS = """<!doctype html>
<title>KS4Web archive results</title>
<body><h1>Results</h1><p>Nothing matched, and that is fine.</p></body>
"""


class LoginServer:
    """A local site that really does refuse a reader without a cookie.

    Two routes matter. `/account` is 302 to `/login` without the session
    cookie and the member page with it, which is what makes "Lane C read a
    logged-in page" a claim with a control arm rather than an assertion.
    `/session/open` is the stand-in for the human's own sign-in: it sets the
    cookies and nothing else, because the agent must never be the thing that
    types a password.
    """

    def __init__(self) -> None:
        outer = self
        self.posts: "queue.Queue[str]" = queue.Queue()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _send(self, code, body=b"", headers=()):
                self.send_response(code)
                for key, value in headers:
                    self.send_header(key, value)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _authed(self) -> bool:
                jar = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
                got = jar.get("ks4session")
                return bool(got) and got.value == SESSION_COOKIE

            def do_GET(self):  # noqa: N802
                path, _, _query = self.path.partition("?")
                if path == "/session/open":
                    self._send(200, b"<!doctype html><title>signed in</title>"
                                    b"<body><h1>Signed in</h1></body>",
                               headers=(
                                   ("Set-Cookie",
                                    f"ks4session={SESSION_COOKIE}; Path=/; "
                                    f"HttpOnly"),
                                   ("Set-Cookie",
                                    f"ks4visible={VISIBLE_COOKIE}; Path=/"),
                               ))
                    return
                if path == "/session/close":
                    self._send(200, b"<!doctype html><title>signed out</title>"
                                    b"<body><h1>Signed out</h1></body>",
                               headers=(
                                   ("Set-Cookie",
                                    "ks4session=; Path=/; Max-Age=0"),
                                   ("Set-Cookie",
                                    "ks4visible=; Path=/; Max-Age=0"),
                               ))
                    return
                if path in ("/", "/account", "/article"):
                    if not self._authed():
                        self._send(302, b"", headers=(("Location", "/login"),))
                        return
                    body = ARTICLE if path == "/article" else ACCOUNT
                    self._send(200, body.encode("utf-8"))
                    return
                if path == "/login":
                    self._send(200, LOGIN.encode("utf-8"))
                    return
                if path == "/public":
                    self._send(200, PUBLIC.encode("utf-8"))
                    return
                if path == "/search":
                    self._send(200, RESULTS.encode("utf-8"))
                    return
                self._send(404, b"<!doctype html><title>not found</title>"
                                b"<body><h1>Not found</h1></body>")

            def do_POST(self):  # noqa: N802
                path, _, _query = self.path.partition("?")
                length = int(self.headers.get("Content-Length") or 0)
                outer.posts.put(path + "?" + self.rfile.read(length).decode(
                    "utf-8", "replace"))
                self._send(200, b"<!doctype html><title>posted</title>"
                                b"<body><h1>Posted</h1></body>")

            def log_message(self, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def run(coro):
    return asyncio.run(coro)


class _Ctx:
    def __init__(self, bridge):
        self.context = _extlane.ExtensionContext(bridge)


class _Sess:
    _seq = 0

    def __init__(self, bridge):
        _Sess._seq += 1
        self.session_id = f"login{_Sess._seq}"
        self.spec = lanes.LaneSpec(lane="C", engine="extension",
                                   headless=False)
        self.element_map = anchors.ElementMap()
        self.reads = anchors.ReadStore()
        self.contexts = {"c1": _Ctx(bridge)}
        self.bumped = []

    def bump(self, kind, page=None):
        self.bumped.append(kind)

    def invalidate_page(self, handle, why):
        return {"why": why}


def active_url(bridge):
    for tab in bridge.request("bg.tabs", timeout=30.0).get("tabs") or []:
        if tab.get("active"):
            return tab.get("url") or ""
    return ""


def settle(bridge, url, timeout=30.0):
    """The tab reset the lane C module needed, for the same reason.

    `bg.tabs` is answered by the background script without passing the rate
    limit, so a reset that finds the tab already in place costs nothing.
    """
    deadline = time.monotonic() + timeout
    last = "no attempt completed"
    while time.monotonic() < deadline:
        try:
            if active_url(bridge) == url:
                return
            bridge.request("page.navigate",
                           {"url": url, "waitUntil": "complete"}, timeout=30.0)
            if active_url(bridge) == url:
                return
            last = "the navigate did not leave the tab on the fixture page"
        except BridgeError as exc:  # noqa: PERF203
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError(f"the shared tab never came back to {url}: {last}")


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    if not find_firefox():
        pytest.skip("no Firefox on this machine")

    workdir = tmp_path_factory.mktemp("ks4web-login")
    endpoint = workdir / "endpoint.json"
    bridge = Bridge(endpoint_path=endpoint)
    site = LoginServer()
    browser = None
    rdp = None
    try:
        register.install(workdir / "nativehost",
                         python_executable=sys.executable,
                         src_dir=ROOT / "src", endpoint=endpoint)
        port = free_port()
        browser = HeadlessFirefox(workdir / "browser",
                                  url=site.url("/login"), debugger_port=port)
        rdp = RDPClient(port)
        rdp.install_temporary_addon(ROOT / "extension")
        if not bridge.wait_for_browser(60.0):
            pytest.fail("the extension never connected to the bridge")
        bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                text = bridge.request("page.read",
                                      timeout=30.0).get("text", "")
            except BridgeError:
                text = ""
            if "Sign in" in text:
                break
            time.sleep(0.25)
        yield bridge, site
    finally:
        for shutdown in (lambda: rdp and rdp.close(),
                         lambda: browser and browser.kill(),
                         site.close, bridge.close):
            try:
                shutdown()
            except Exception:  # noqa: BLE001
                pass
        register.unregister_windows()


@pytest.fixture
def signed_in(live):
    """THE HUMAN'S STEP, re-taken for every test that needs it.

    Navigating to `/session/open` is the browser establishing its own
    cookies, which is what a person signing in at their own keyboard leaves
    behind. Nothing in this project types the password, and the fixture is
    written this way to keep that true rather than as a shortcut.

    Function scope rather than module scope, and the reason is the defect
    this phase spent its first hours on. One test here deliberately signs
    the browser OUT to prove the server really refuses anonymous readers,
    and a module-scoped sign-in would hand every test after it a browser
    whose session that test had thrown away.
    """
    bridge, site = live
    bridge.request("page.navigate",
                   {"url": site.url("/session/open"), "waitUntil": "complete"},
                   timeout=30.0)
    yield bridge, site


@pytest.fixture(autouse=True)
def fresh_tab(live):
    bridge, site = live
    bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
    settle(bridge, site.url("/login"))
    yield


@pytest.fixture
def lane(live, fresh_tab):
    bridge, site = live
    before = readonly.grade()
    readonly.apply(False)
    consent.apply("full")
    sess = _Sess(bridge)
    page = _extlane.ExtensionPage(bridge, url=site.url("/login"))
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    try:
        yield sess, record, site
    finally:
        readonly.apply(False if before is None else before)
        consent.apply(None)
        from kitchensink4web.policy import budgets
        budgets.BOOK.drop(sess.session_id)


def ref_named(sess, name):
    for ref, entry in sess.element_map.entries.items():
        if entry.anchor.get("name") == name:
            return ref
    raise AssertionError(
        f"no ref for {name!r}; minted: "
        f"{[e.anchor.get('name') for e in sess.element_map.entries.values()]}")


def verdict(call):
    try:
        run(call())
    except ConfirmationRequired as exc:
        text = str(exc)
        for phrase, cls in (
                ("payment-shaped form", "payment_form"),
                ("password or a one-time code", "credential_submit"),
                ("reaches other people", "broadcast_submit"),
                ("deletes, cancels", "destructive_submit"),
                ("agreeing to terms", "legal_assent")):
            if phrase in text:
                return cls
        if "submitting a form" in text:
            return "form_submit"
        return "gated"
    except CredentialRefused:
        return "credential_refused"
    return "ungated"


# ------------------------------------------------- the site really does gate


def test_the_account_page_is_refused_to_a_browser_with_no_session(lane):
    """THE CONTROL ARM, and without it every claim below is decoration.

    A fixture that served the member page to anybody would let a read of it
    pass while proving nothing about sessions at all.
    """
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/session/close")))
    result = run(extops.navigate(sess, record, url=site.url("/article")))
    assert result["url"].endswith("/login")
    payload = run(extops.get_page_view(sess, record, budget_tokens=6000))
    assert MEMBER_MARK not in payload["projection"]
    assert "Sign in" in payload["projection"]


def test_lane_c_reads_a_page_that_only_a_signed_in_browser_can_see(
        signed_in, lane):
    """THE CLAIM THE LANE EXISTS FOR, and the first time it has been shown.

    The browser holds a cookie a human's sign-in left behind, the server
    hands out the member page only against that cookie, and the read comes
    back through the same content script and the same projection every other
    fixture uses. No credential was handled by anything in this project.
    """
    sess, record, site = lane
    result = run(extops.navigate(sess, record, url=site.url("/article")))
    assert result["url"].endswith("/article")
    payload = run(extops.get_page_view(sess, record, budget_tokens=6000))
    assert MEMBER_MARK in payload["projection"]
    assert payload["lane"] == "C"
    assert payload["webdriver"] is False
    assert payload["budget"]["used"] <= payload["budget"]["limit"]


def test_neither_cookie_travels_with_the_read(signed_in, lane):
    """The fear a person has about an extension on a logged-in page, checked
    on both halves of it.

    `ks4session` is HttpOnly and page script cannot reach it. `ks4visible` is
    not, so `document.cookie` in the page's own world returns it, and an
    extractor that scraped cookies would leak that one while the HttpOnly one
    stayed safe. A test with only the first cookie would pass on a build that
    leaks the second.
    """
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/article")))
    payload = run(extops.get_page_view(sess, record, budget_tokens=6000))
    whole = str(payload)
    assert SESSION_COOKIE not in whole
    assert VISIBLE_COOKIE not in whole
    assert "ks4session" not in whole
    assert "ks4visible" not in whole


# -------------------------------------------------- the gate on the login form


def test_the_login_forms_submit_gates_as_a_credential_submission(lane):
    """The consent gate on the door a person cares most about.

    The classifier is looking at a real form with a real password field in
    it, extracted by the same `extract.js` the Playwright lanes run, so this
    is the descriptor rather than the plumbing.

    THE GATE FIRED BEFORE THE WRITE, and the second half asks the server
    rather than the client. Every refusal in this file is a Python
    exception, and a build that raised the exception after sending the form
    would look identical from in here. The server counts what arrived.
    """
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/login")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert verdict(lambda: extops.click(
        sess, record,
        location={"ref": ref_named(sess, "Sign in")})) == "credential_submit"
    assert site.posts.empty(), "the login form was sent despite the refusal"


def test_the_password_field_refuses_to_be_typed_into(lane):
    """Credential blindness on the extension path. The agent cannot type a
    password even when a human has cleared everything else."""
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/login")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert verdict(lambda: extops.type_text(
        sess, record, location={"ref": ref_named(sess, "Password")},
        text="anything")) == "credential_refused"


def test_the_password_value_never_leaves_the_page(lane):
    """The projection's own guarantee against a field that really holds a
    secret rather than an empty one."""
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/login")))
    payload = run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert PASSWORD not in str(payload)


# ------------------------------------------- the rest of an authenticated page


def test_a_destructive_button_on_the_member_page_gates_as_destructive(
        signed_in, lane):
    """An authenticated page is where the dangerous buttons live, which is
    why the ladder's classes have to hold on one."""
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/account")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert verdict(lambda: extops.click(
        sess, record,
        location={"ref": ref_named(sess, "Delete my account")})
    ) == "destructive_submit"
    assert site.posts.empty(), "the account was closed despite the refusal"


def test_an_ordinary_link_on_the_member_page_is_not_gated(signed_in, lane):
    """THE OTHER CONTROL ARM. A build that refused everything would pass
    every refusal test above and be useless."""
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/account")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    result = run(extops.click(sess, record,
                              location={"ref": ref_named(sess,
                                                         "Public documents")}))
    assert result["effect"] in ("navigated", "same-page")
    assert result["is_trusted"] is False


def test_a_query_shaped_search_on_the_member_page_stays_in_grade(
        signed_in, lane):
    """Tier 0 on an authenticated page. A GET form with no secret, payment or
    file field is a safe method under RFC 9110, and gating it would be the
    friction the ladder exists to remove."""
    sess, record, site = lane
    run(extops.navigate(sess, record, url=site.url("/account")))
    run(extops.get_page_view(sess, record, budget_tokens=4000))
    assert verdict(lambda: extops.type_text(
        sess, record, location={"ref": ref_named(sess, "Search the archive")},
        text="ledger", submit=True)) == "ungated"


def test_the_credential_class_cannot_be_pre_authorized_away(monkeypatch):
    """The reason the login gate has no "yes, always" and never will.

    `credential_submit` is Tier 2, so naming it in the pre-authorization
    environment does not quietly do nothing: the server refuses to start.
    Both directions, because a refusal that refused everything would pass
    the first half on its own.
    """
    from kitchensink4web.errors import BadParams

    monkeypatch.setenv("KS4WEB_PREAUTH", "credential_submit@127.0.0.1")
    with pytest.raises(BadParams):
        consent.apply(None)
    monkeypatch.setenv("KS4WEB_PREAUTH", "evaluate_script@127.0.0.1")
    consent.apply(None)
    monkeypatch.delenv("KS4WEB_PREAUTH")
    consent.apply(None)
