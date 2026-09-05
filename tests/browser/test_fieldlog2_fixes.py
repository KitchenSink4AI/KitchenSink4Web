"""Field log 2 regressions (2026-09-05 campaign; triage
20260906_web_triage2.md). Each test is the logged repro, asserting the
fixed behavior:

- A2: get_list and get_table on a page with zero candidates fell through an
  empty-but-falsy `choose` list into a KeyError on next_start_index /
  next_start_row, which the envelope mapped to BAD_PARAMS with an "internal
  lookup failed" message. Hacker News (TABLE layout, no semantic lists) and
  httpbin (no tables at all) are the two field pages.
- A3: navigating with the network down came back as BAD_PARAMS, which tells
  an agent it typed the URL wrong.
- A4: a delta read after a single-page-app navigation was LARGER than a
  fresh read, because nothing survived to diff against.
- A5: session close said "none were saved" minutes after an explicit
  save_auth_state.

Plus the three the live ship-route test found the same night
(20260906_web_ship_route_test.md), all on the auth-state open path:

- D1: the load gate borrowed storage_clear's words and asked the human to
  allow "clearing cookies or site storage" for an operation that clears
  nothing.
- D2: a FAILED load left the browser running with no handle returned. The
  ship route watched eleven Firefox processes outlive a rejected file.
- D3: the refusal hint talked about location objects and refs, neither of
  which is anywhere near an auth-state load.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (BadParams, PageUnreachable,
                                    TargetNotFound, ValidationFailed)
from kitchensink4web.ops import extract, lite, storage
from kitchensink4web.policy import (audit, budgets, credentials, gates,
                                    readonly)

pytestmark = pytest.mark.browser


# ------------------------------------------------------------ the fixtures

#: Hacker News in miniature: rows of content laid out in a TABLE used for
#: PAGE STRUCTURE, which is a layout table and therefore not a data table,
#: and no UL/OL anywhere. The page the field test crashed both tools on.
_LAYOUT = """<!doctype html><title>layout table page</title><body>
<table role="presentation" width="100%"><tr><td>
  <span>1.</span> <a href="/a">First story</a> <span>120 points</span>
</td></tr><tr><td>
  <span>2.</span> <a href="/b">Second story</a> <span>98 points</span>
</td></tr></table>
<p>Ordinary prose so the page is not empty.</p>
</body>"""

#: httpbin in miniature: real content, no tables, no lists.
_PLAIN = """<!doctype html><title>plain page</title><body>
<main><h1>Plain</h1><p>One paragraph and nothing structured.</p>
<a href="/next">a link</a></main></body>"""

#: The SPA: one click swaps the entire view and pushes a new URL, so every
#: ref minted before it is gone and nothing stable survives.
_SPA = """<!doctype html><title>spa</title><body>
<main id="view">
  <h1>List view</h1>
  <button id="go" onclick="swap()">Open detail</button>
  <p>Item one</p><p>Item two</p><p>Item three</p>
</main>
<script>
function swap() {
  history.pushState({}, '', '/detail');
  document.getElementById('view').innerHTML =
    '<h1>Detail view</h1><button id="back">Back to list</button>' +
    '<p>Detail line one</p><p>Detail line two</p>';
}
</script></body>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body):
        data = body.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/layout"):
            self._send(_LAYOUT)
        elif self.path.startswith("/spa") or self.path.startswith("/detail"):
            self._send(_SPA)
        else:
            self._send(_PLAIN)


@pytest.fixture(scope="module")
def site():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    credentials.VAULT.clear()
    readonly.apply(False)
    yield
    credentials.VAULT.clear()
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
    await lite.navigate(page=page, url=f"{site}{path}")
    return session, page


# -------------------------------------------------------------------- A2


def test_get_list_refuses_honestly_on_a_page_with_no_lists(site):
    """The httpbin repro. NOT_FOUND naming what the tool looks for, not a
    BAD_PARAMS about an internal lookup."""
    async def go():
        _, page = await _open(site, "/plain")
        with pytest.raises(TargetNotFound) as exc:
            await extract.get_list(page=page)
        return str(exc.value)

    message = run(go())
    assert "no lists" in message
    assert "get_page_view" in message
    assert "internal lookup" not in message


def test_get_table_refuses_honestly_on_a_layout_table_page(site):
    """The Hacker News repro: a TABLE used for page structure is not a data
    table, and the refusal has to say so rather than crashing."""
    async def go():
        _, page = await _open(site, "/layout")
        with pytest.raises(TargetNotFound) as exc:
            await extract.get_table(page=page)
        return str(exc.value)

    message = run(go())
    assert "no data tables" in message
    assert "layout" in message
    assert "internal lookup" not in message


def test_get_list_on_a_layout_table_page_also_refuses(site):
    """The other half of the same field page: rows in a TABLE are not a
    semantic list either."""
    async def go():
        _, page = await _open(site, "/layout")
        with pytest.raises(TargetNotFound) as exc:
            await extract.get_list(page=page)
        return str(exc.value)

    assert "no lists" in run(go())


def test_zero_candidates_with_an_explicit_index_refuses_the_same_way(site):
    """index=0 on a page with zero candidates used to produce "valid
    indexes are 0 to -1"."""
    async def go():
        _, page = await _open(site, "/plain")
        with pytest.raises(TargetNotFound) as exc:
            await extract.get_table(page=page, index=0)
        return str(exc.value)

    assert "no data tables" in run(go())


# -------------------------------------------------------------------- A3


def test_unresolvable_host_is_page_unreachable_not_bad_params(site):
    """A .invalid host never resolves and never leaves the machine (RFC
    2606), so this tests the DNS path without touching the network."""
    async def go():
        _, page = await _open(site, "/plain")
        with pytest.raises(PageUnreachable) as exc:
            await lite.navigate(page=page,
                                url="https://ks4web-does-not-exist.invalid/",
                                timeout_ms=15000)
        return str(exc.value)

    message = run(go())
    assert "never reached a server" in message
    assert "DNS" in message


def test_a_malformed_url_is_still_bad_params(site):
    """A6: the URL pre-validation predates this wave and still owns the
    genuinely malformed case, so the two refusals stay distinguishable."""
    async def go():
        _, page = await _open(site, "/plain")
        out = {}
        for bad in ("not a url at all", "https://", "htp://x.com"):
            with pytest.raises(BadParams) as exc:
                await lite.navigate(page=page, url=bad)
            out[bad] = str(exc.value)
        return out

    messages = run(go())
    assert "no host" in messages["https://"]
    assert all("never reached a server" not in m for m in messages.values())


# -------------------------------------------------------------------- A4


def test_spa_navigation_falls_back_to_a_full_read_instead_of_a_worse_delta(
        site):
    """The delta after a client-side navigation used to list every old unit
    as gone and every new one as added, costing more than the fresh read it
    replaces."""
    async def go():
        _, page = await _open(site, "/spa")
        first = await lite.get_page_view(page=page)
        await lite.click(page=page, location={"css": "#go"})
        second = await lite.get_page_view(page=page, since=first["read_token"])
        return first, second

    first, second = run(go())
    delta = second["delta"]
    assert delta["fell_back_to_full_read"] is True
    assert delta["navigated"] is True
    assert "cheaper" not in delta["why"]  # it states the fact, not a boast
    assert "no unit survived" in delta["why"]
    # The projection is the FULL read, so the new view is actually in it.
    assert "Detail view" in second["projection"]


# -------------------------------------------------------------------- A5


def test_close_reports_an_earlier_save_instead_of_contradicting_it(
        site, tmp_path, monkeypatch):
    """Field finding 41: close said "none were saved" right after an
    explicit save_auth_state."""
    monkeypatch.setenv("KS4WEB_MODE", "storage")
    from kitchensink4web import packs
    saved_packs = packs.loaded_packs()
    packs.apply_startup_packs(["storage"])

    async def go():
        session, page = await _open(site, "/plain")
        await lite.navigate(page=page, url=f"{site}/plain")
        await session.context.add_cookies([{
            "name": "session_token", "value": "KS4WEB-TEST-SESSION-a1b2c3d4",
            "url": f"{site}/"}])
        out = str(tmp_path / "auth.json")
        await storage.save_auth_state(session=session.session_id, path=out)
        return await lite.manage_session(action="close",
                                         session=session.session_id), out

    try:
        result, out = run(go())
    finally:
        packs.apply_startup_packs(list(saved_packs))
    note = result["auth_state"]
    assert "saved earlier this session" in note
    assert "none were saved" not in note
    assert out in note


# ------------------------------------------------- ship-route test (D1-D3)


def test_the_auth_load_gate_asks_about_loading_not_clearing():
    """D1: the human was asked to allow "clearing cookies or site storage"
    for an operation that clears nothing. A carefully read decline of a load
    that describes itself as a wipe is the failure this prevents."""
    text = gates.GATED_CLASSES["storage_load"]
    assert "clear" not in text
    engine = gates.GateEngine()
    with pytest.raises(Exception) as exc:
        engine.ask("storage_load", tool="manage_session", session=None,
                   page=None, target=None,
                   summary="Open a session and load saved authentication "
                           "state from state.json?")
    message = str(exc.value)
    assert "loading a saved signed-in session" in message
    assert "clearing cookies" not in message


def test_a_failed_auth_load_tears_the_session_down_and_says_why(
        tmp_path, monkeypatch):
    """D2 and D3 together, on the ship route's own repro: a state file whose
    cookie expiry is in MILLISECONDS (which is how a Firefox profile stores
    it) is rejected by the driver for the whole batch.

    D2: the session must not survive the failure. The ship route watched
    eleven browser processes outlive a rejected file with no handle ever
    returned to the caller.
    D3: the refusal must name the file, the offending cookie, and the units,
    not location objects and refs."""
    from kitchensink4web import packs
    before = list(packs.loaded_packs())
    packs.apply_startup_packs(["storage"])
    # The gate is not the subject here; the teardown and the refusal are.
    monkeypatch.setattr(gates.ENGINE, "ask",
                        lambda *a, **k: None)
    state = tmp_path / "bad_state.json"
    state.write_text(json.dumps({"cookies": [{
        "name": "probe", "value": "v", "domain": "127.0.0.1", "path": "/",
        "expires": 1788000000000, "httpOnly": False, "secure": False,
        "sameSite": "Lax"}], "origins": []}), encoding="utf-8")

    async def go():
        """The assertions about MANAGER.sessions have to run INSIDE the
        loop, before this module's own close_all sweep, or the sweep would
        hide exactly the leak under test."""
        try:
            await lite.manage_session(
                action="open", lane="A", auth_state=str(state))
        except ValidationFailed as exc:
            return {"stranded": list(MANAGER.sessions), "message": str(exc)}
        raise AssertionError("the bad state file was accepted")

    try:
        out = run(go())
        # D2: nothing stranded, checked before any teardown of ours.
        assert out["stranded"] == [], (
            f"a failed auth load stranded {out['stranded']}")
        # D3: the refusal is about the file, not about refs.
        message = out["message"]
        assert str(state) in message
        assert "MILLISECOND" in message
        assert "probe" in message
        assert "location object" not in message
        assert "nothing partial was left behind" in message
    finally:
        packs.apply_startup_packs(before)
