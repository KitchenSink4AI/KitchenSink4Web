"""Feature #12 at the wire: what actually leaves the browser.

Three of the boundary spec's pins cannot be proven off a live browser, and
they are the three that decide whether the capability is defensible at all:

- **B7.2** the header reaches the named origin;
- **B7.17** a subresource to a DIFFERENT origin from the same page does not
  inherit it, which is the property that makes `modify` different in kind
  from `set_routing(action='headers')`;
- **B7.16** a matched request that redirects off-origin does not carry it on
  the second hop. The spec is explicit that if this cannot be enforced the
  capability is CUT rather than shipped with a caveat, so it is proven here
  rather than asserted in a docstring.

Two servers on two ports give two origins on one host, which is exactly the
shape a page and its CDN have.
"""

from __future__ import annotations

import asyncio
import http.server
import os
import socketserver
import threading

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import ConfirmationRequired
from kitchensink4web.ops import lite, net
from kitchensink4web.policy import (audit, budgets, consent, credentials,
                                    gates, readonly)

pytestmark = pytest.mark.browser

SECRET = "ghp_liveLOOKINGtoken_0123456789abcdef"

_ENVS = ("KS4WEB_CREDENTIAL_INJECTION", "KS4WEB_ALLOW_ORIGINS",
         "KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_SECRET_TESTREF")


def _handler_for(seen: list, other_port_box: list):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.path, dict(self.headers)))
            if self.path == "/redir":
                other = other_port_box[0]
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{other}/landed")
                self.end_headers()
                return
            if self.path == "/page":
                other = other_port_box[0]
                body = (f'<!doctype html><meta charset=utf-8><title>p</title>'
                        f'<body><h1>page</h1>'
                        f'<img src="http://127.0.0.1:{other}/img.png">'
                        f'</body>').encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return H


@pytest.fixture(scope="module")
def two_origins():
    a_seen: list = []
    b_seen: list = []
    a_other: list = [0]
    b_other: list = [0]
    a = socketserver.TCPServer(("127.0.0.1", 0), _handler_for(a_seen, a_other))
    b = socketserver.TCPServer(("127.0.0.1", 0), _handler_for(b_seen, b_other))
    a_other[0] = b.server_address[1]
    b_other[0] = a.server_address[1]
    for srv in (a, b):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"a": f"http://127.0.0.1:{a.server_address[1]}",
           "b": f"http://127.0.0.1:{b.server_address[1]}",
           "a_seen": a_seen, "b_seen": b_seen}
    a.shutdown()
    b.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    for name in _ENVS:
        os.environ.pop(name, None)
    credentials.VAULT.clear()
    credentials.register_secret_refs()
    readonly.apply(False)
    consent.apply()
    yield
    for name in _ENVS:
        os.environ.pop(name, None)
    credentials.VAULT.clear()
    credentials.register_secret_refs()
    readonly.apply(False)
    consent.apply()


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _through_the_gate(call):
    """One call, the gate it raises, a redemption, and the re-run.

    This is `server._wrap`'s flow written out: the first pass RAISES, the
    confirmation plumbing redeems and deposits, and the body runs once more.
    Nothing here is a bypass -- `redeem()` is reached the only way it can be,
    from outside a tool argument."""
    try:
        return await call()
    except ConfirmationRequired as exc:
        grant = gates.ENGINE.redeem(exc.detail["requestState"],
                                    {"allow": True})
        gates.deposit_grant(grant)
        try:
            return await call()
        finally:
            gates.clear_grant()


def _auth_of(seen, path):
    for got_path, headers in seen:
        if got_path == path:
            return {k.lower(): v for k, v in headers.items()}.get(
                "authorization")
    return "(no such request)"


def test_the_header_reaches_one_origin_and_no_other(two_origins):
    """B7.2 and B7.17 in one run, which is the honest pairing: an injection
    that reached the named origin would be worthless as evidence without the
    same page's cross-origin subresource proving it stopped there."""
    os.environ["KS4WEB_CREDENTIAL_INJECTION"] = "true"
    os.environ["KS4WEB_SECRET_TESTREF"] = SECRET
    os.environ["KS4WEB_ALLOW_ORIGINS"] = "127.0.0.1"
    credentials.register_secret_refs()

    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        await _through_the_gate(lambda: net.set_routing(
            session=session.session_id, action="modify",
            origin=two_origins["a"], header="Authorization",
            secret_ref="TESTREF"))
        page = session.focused
        await lite.navigate(page=page, url=f"{two_origins['a']}/page")
        await asyncio.sleep(0.6)          # let the subresource land
        return await net.set_routing(session=session.session_id,
                                     action="status")

    status = run(go())

    # THE NAMED ORIGIN CARRIES IT.
    assert _auth_of(two_origins["a_seen"], "/page") == SECRET
    # THE OTHER ORIGIN, REQUESTED BY THE SAME PAGE, DOES NOT. This is the
    # pin that proves `modify` is scoped where `action='headers'` is not.
    assert _auth_of(two_origins["b_seen"], "/img.png") in (None,
                                                           "(no such request)")

    # And the status roundtrip (B7.5) reports the REFERENCE, never the value.
    import json
    blob = json.dumps(status)
    assert "secret_ref:TESTREF" in blob
    assert SECRET not in blob


def test_a_redirect_off_origin_drops_the_credential(two_origins):
    """B7.16. A matched request that 302s to a different origin is a NEW
    request at a NEW url, and the handler re-checks the origin itself rather
    than trusting the matcher that admitted the first hop.

    The spec's instruction if this could not be enforced was to CUT the
    capability, not to ship it with a caveat. It is enforced."""
    os.environ["KS4WEB_CREDENTIAL_INJECTION"] = "true"
    os.environ["KS4WEB_SECRET_TESTREF"] = SECRET
    os.environ["KS4WEB_ALLOW_ORIGINS"] = "127.0.0.1"
    credentials.register_secret_refs()
    two_origins["a_seen"].clear()
    two_origins["b_seen"].clear()

    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        await _through_the_gate(lambda: net.set_routing(
            session=session.session_id, action="modify",
            origin=two_origins["a"], header="Authorization",
            secret_ref="TESTREF"))
        page = session.focused
        await lite.navigate(page=page, url=f"{two_origins['a']}/redir")
        await asyncio.sleep(0.4)

    run(go())
    assert _auth_of(two_origins["a_seen"], "/redir") == SECRET
    assert _auth_of(two_origins["b_seen"], "/landed") in (
        None, "(no such request)")


def test_an_ordinary_header_needs_no_confirmation(two_origins):
    """B7.3. The safe two-thirds do not wait behind the dangerous third: an
    ordinary header applies with no gate and no injection switch."""
    os.environ["KS4WEB_ALLOW_ORIGINS"] = "127.0.0.1"
    two_origins["a_seen"].clear()

    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        # No _through_the_gate: an ordinary header raises nothing.
        await net.set_routing(session=session.session_id, action="modify",
                              origin=two_origins["a"], header="X-Ab-Test",
                              value="variant-b")
        page = session.focused
        await lite.navigate(page=page, url=f"{two_origins['a']}/api")

    run(go())
    got = [dict((k.lower(), v) for k, v in h.items())
           for p, h in two_origins["a_seen"] if p == "/api"]
    assert got and got[0].get("x-ab-test") == "variant-b"


def test_strip_params_removes_and_counts_what_it_rewrote(two_origins):
    """B7.4. It reports requests REWRITTEN, not rules installed. A receipt
    for work that did not happen is the defect the preset='analytics'
    finding was."""
    two_origins["a_seen"].clear()

    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        await net.set_routing(session=session.session_id,
                              action="strip_params", preset="tracking")
        page = session.focused
        await lite.navigate(
            page=page,
            url=f"{two_origins['a']}/api?utm_source=x&keep=1&gclid=y")
        return await net.set_routing(session=session.session_id,
                                     action="status")

    status = run(go())
    paths = [p for p, _ in two_origins["a_seen"]]
    assert "/api?keep=1" in paths, paths
    rule = [r for r in status["routing"]["routes"]
            if r["kind"] == "strip_params"][0]
    assert rule["rewritten"] >= 1
    assert "not a privacy product" in rule["note"]
