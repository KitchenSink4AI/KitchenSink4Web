"""`do(intent=...)`: goal to mechanism, against live Chromium.

Red-first pins for feature #6. The fixture is `tests/fixtures/do_site.html`.

The boundary is the point, and these pins are that boundary. A calling model
can translate a goal into a label, so a tool that only did that would be a
wrapper with a hallucination surface. What a model cannot do is answer WHICH
ELEMENT, WHEN ACTIVATED, SUBMITS THIS FORM: it looks for the word "Submit",
so it misses `<input type=image>` (a real incident in this codebase, the
2026-09-06 re-attack R1, where clicking one submitted a checkout form
carrying a live card number with no gate computed), it misses a typeless
`<button>`, and it clicks a `<label>` instead of the control the label
forwards its activation to.

The second half of the boundary is the refusal: two forms with two
submitters is not a thing to pick between, and the listing IS the product.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import re
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import confirm
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (AmbiguousLocation, BadParams,
                                    ConfirmationRequired, CredentialRefused,
                                    TargetNotFound)
from kitchensink4web.ops import lite
from kitchensink4web.policy import (audit, budgets, credentials, gates,
                                    readonly)

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
PATH = "tests/fixtures/do_site.html"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(_Quiet, directory=str(ROOT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
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


async def _open(site, variant):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{PATH}?form={variant}")
    await lite.get_page_view(page=page)
    return session, page


async def _gated(fn, **kwargs):
    """One call through the gate, the way `server._wrap` redeems it: a
    single action re-runs safely, which is exactly the property a composite
    does NOT have and why `batch` confirms per step instead."""
    try:
        return await fn(**kwargs)
    except ConfirmationRequired as exc:
        token = (getattr(exc, "detail", {}) or {}).get("requestState")
        grant = gates.ENGINE.redeem(token, {"allow": True})
        gates.deposit_grant(grant)
        try:
            return await fn(**kwargs)
        finally:
            gates.clear_grant()


async def _submits(page):
    _sess, record = MANAGER.locate(page)
    return await record.page.evaluate("() => window.__submits")


# ------------------------------------------- the mechanism a model misses


def test_do_submit_resolves_input_type_image(site):
    """R1, pinned. `<input type=image>` is a submit button with a picture on
    it and has been in the language since HTML 2.0. A model looking for the
    word Submit does not see it."""
    async def go():
        _, page = await _open(site, "image")
        out = await _gated(lite.do, page=page, intent="submit the form")
        assert out["tool"] == "do"
        assert out["acted"] == "click"
        assert out["resolution"]["stage"] == "goal-pattern:submit-form"
        assert "type=image" in out["resolution"]["mechanism"]
        assert (await _submits(page)).get("image") == 1

    run(go())


def test_do_submit_resolves_typeless_button(site):
    """A `<button>` with no type attribute inside a form IS a submit button
    per the HTML spec; only 'button' and 'reset' opt out."""
    async def go():
        _, page = await _open(site, "typeless")
        out = await _gated(lite.do, page=page, intent="submit the form")
        assert out["resolution"]["stage"] == "goal-pattern:submit-form"
        assert (await _submits(page)).get("typeless") == 1

    run(go())


def test_do_submit_does_not_click_the_label(site):
    """A `<label for=go>` carries the words a search would hit and forwards
    its activation to the control. The control is what gets resolved."""
    async def go():
        _, page = await _open(site, "label")
        out = await _gated(lite.do, page=page, intent="submit the form")
        assert out["target"]["role"] != "label"
        assert out["target"]["name"] != "Send it", out["target"]
        assert (await _submits(page)).get("label") == 1

    run(go())


def test_do_login_resolves_the_password_form(site):
    """"log in" is not a label lookup either: it is the submitter of the
    form that carries a password field."""
    async def go():
        _, page = await _open(site, "password")
        out = await _gated(lite.do, page=page, intent="log in")
        assert out["resolution"]["stage"] == "goal-pattern:log-in"
        assert (await _submits(page)).get("login") == 1

    run(go())


# --------------------------------------------------- the refusal contract


def test_do_two_forms_refuse(site):
    """Two forms, two submitters. The model asked to click "Submit"
    resolves the ambiguity by picking; this refuses and lists, with actable
    refs, and nothing is clicked."""
    async def go():
        _, page = await _open(site, "two")
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.do(page=page, intent="submit the form")
        text = str(exc.value)
        assert "2" in text
        assert "Nothing was done" in text
        assert await _submits(page) == {}

    run(go())


def test_do_scoped_within_resolves(site):
    """The same page, scoped. `within` narrows the mechanism search to one
    form, and the ambiguity goes away because the caller answered it."""
    async def go():
        _, page = await _open(site, "two")
        view = await lite.get_page_view(page=page)
        assert "f2" in view["projection"], view["projection"]
        out = await _gated(lite.do, page=page, intent="submit the form",
                           within={"form": "f2"})
        assert out["resolution"]["scope"] == {"form": "f2"}
        assert (await _submits(page)).get("second") == 1

    run(go())


def test_do_refuses_a_goal_whose_mechanism_is_absent(site):
    """A form with no submit control. The refusal names the goal shape that
    matched, the mechanism looked for, and what the page has instead."""
    async def go():
        _, page = await _open(site, "none")
        with pytest.raises(TargetNotFound) as exc:
            await lite.do(page=page, intent="submit the form")
        text = str(exc.value)
        assert "submit" in text.lower()
        assert "find_elements" in text

    run(go())


def test_do_unknown_verb_refuses_and_never_defaults_to_click(site):
    async def go():
        _, page = await _open(site, "typeless")
        with pytest.raises(BadParams) as exc:
            await lite.do(page=page, intent="ponder the login form")
        assert "ponder" in str(exc.value)
        assert await _submits(page) == {}

    run(go())


def test_do_multi_goal_refuses(site):
    """One goal per call. Decomposing a multi-step intent is a workflow,
    three gates, and the batch tool, not this."""
    async def go():
        _, page = await _open(site, "typeless")
        with pytest.raises(BadParams) as exc:
            await lite.do(page=page, intent="type hello and press enter")
        assert "one" in str(exc.value).lower()
        assert await _submits(page) == {}

    run(go())


def test_do_type_without_text_refuses_and_invents_nothing(site):
    """No text is ever parsed out of the intent string: a value the tool
    invented from prose is a value the caller never approved."""
    async def go():
        _, page = await _open(site, "password")
        with pytest.raises(BadParams) as exc:
            await lite.do(page=page, intent='type "hunter2" in the username')
        assert "text" in str(exc.value)
        _sess, record = MANAGER.locate(page)
        assert await record.page.evaluate(
            "() => document.getElementById('u').value") == ""

    run(go())


def test_do_empty_intent_refuses(site):
    async def go():
        _, page = await _open(site, "typeless")
        with pytest.raises(BadParams) as exc:
            await lite.do(page=page, intent="   ")
        assert "find_and_act" in str(exc.value)

    run(go())


# ------------------------------------------ the handoff, proven not claimed


def test_do_inherits_the_submit_gate(site, monkeypatch):
    """A submit-shaped `do` on a payment form raises the same class the
    direct path raises, which proves the handoff rather than a parallel
    path."""
    async def refuse(_exc):
        return None
    monkeypatch.setattr(confirm, "attempt", refuse)

    async def go():
        _, page = await _open(site, "payment")
        with pytest.raises(ConfirmationRequired):
            await lite.do(page=page, intent="submit the form")
        assert await _submits(page) == {}

    run(go())


def test_do_inherits_credential_blindness(site):
    async def go():
        _, page = await _open(site, "password")
        with pytest.raises(CredentialRefused):
            await lite.do(page=page, intent="type into the Password field",
                          text="hunter2")

    run(go())


def test_do_charges_exactly_one_action(site):
    """Resolution is a read, and a read that resolves nothing must not spend
    an action budget."""
    async def go():
        # A NON-GATED goal, deliberately: a gated one re-runs through the
        # confirmation and the retry is the wrapper's business, not this
        # tool's arithmetic.
        session, page = await _open(site, "none")
        before = budgets.BOOK.snapshot(session.session_id)["counters"]
        await lite.do(page=page, intent="click Do nothing")
        after = budgets.BOOK.snapshot(session.session_id)["counters"]
        assert after["actions"] - before["actions"] == 1

    run(go())


def test_do_resolution_failure_costs_no_budget(site):
    async def go():
        session, page = await _open(site, "two")
        before = budgets.BOOK.snapshot(session.session_id)["counters"]
        with pytest.raises(AmbiguousLocation):
            await lite.do(page=page, intent="submit the form")
        after = budgets.BOOK.snapshot(session.session_id)["counters"]
        assert after["actions"] == before["actions"]

    run(go())


def test_do_ambiguity_rides_the_nonce_envelope(site):
    """Candidate names are page-authored, and page-authored text never rides
    raw in the server's voice."""
    async def go():
        _, page = await _open(site, "two")
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.do(page=page, intent="submit the form")
        assert "KS4WEB-PAGE-DATA" in str(exc.value)

    run(go())


def test_do_falls_through_to_describe_and_says_so(site):
    """An intent that matches no goal shape does not fall through to a text
    search silently: it reaches the describe selector and the payload says
    which stage resolved it."""
    async def go():
        _, page = await _open(site, "none")
        out = await lite.do(page=page, intent="click Do nothing")
        assert out["resolution"]["stage"] == "describe"
        assert out["acted"] == "click"

    run(go())


def test_the_image_submitter_is_named_by_its_alt_text(site):
    """The accname gap this feature found. `<input type=image>` takes its
    accessible name from `alt` (HTML-AAM) and no rung read it, so the one
    submit control this build calls out by name read as unnamed. An unnamed
    control anchors turn-local, so the ref minted for it did not survive its
    own re-resolution and the click refused."""
    async def go():
        _, page = await _open(site, "image")
        found = await lite.find_elements(page=page, query="Send it")
        assert "Send it" in found["results"]
        out = await _gated(lite.do, page=page, intent="submit the form")
        assert "Send it" in out["resolution"]["match"]

    run(go())


def test_a_scope_that_cannot_be_honored_refuses(site):
    """A `within` the ladder could not use is a refusal, never a silent
    widening: the goal matched no shape, so the search fell through to word
    overlap over the whole page, and acting there would be acting outside
    the scope the caller asked for."""
    async def go():
        _, page = await _open(site, "two")
        view = await lite.get_page_view(page=page)
        form = re.search(r"\bf\d+\b", view["projection"]).group(0)
        with pytest.raises(BadParams) as exc:
            await lite.do(page=page, intent="click Query",
                          within={"form": form})
        assert "find_and_act" in str(exc.value)
        assert await _submits(page) == {}

    run(go())
