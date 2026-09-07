"""The consent ladder against a real browser and real forms.

The unit pins prove the DECISION; these prove the whole path: the in-page
census, the descriptor, the classifier, the choke point, and the gate, on
one page, through every write path a caller has.

Two properties are load-bearing here and neither is provable off a browser:

- **PIN 2, the four write paths.** A GET search form submits with ZERO gates
  through `click`, `press_keys`, `fill_form(submit=True)`, and
  `find_and_act`. Parity across paths is what stops a fifth path being added
  that quietly skips the classifier, and it is extended here to the classes
  the ladder added rather than forked into a parallel test.
- **PIN 12/13, the same parity on the refusing side.** A GET CHECKOUT form
  gates as payment through every one of those paths and at every scope.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import os
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import ConfirmationRequired, CredentialRefused
from kitchensink4web.ops import lite
from kitchensink4web.policy import (audit, budgets, consent, credentials,
                                    readonly)

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "corpus" / "consent"

_ENVS = ("KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_SENSITIVE_ORIGINS",
         "KS4WEB_ALLOW_ORIGINS", "KS4WEB_ALLOWED_ROOTS")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(_Quiet, directory=str(SITE))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    credentials.VAULT.clear()
    for name in _ENVS:
        os.environ.pop(name, None)
    readonly.apply(False)
    consent.apply()
    yield
    for name in _ENVS:
        os.environ.pop(name, None)
    credentials.VAULT.clear()
    readonly.apply(False)
    consent.apply()


def scope(name):
    readonly.apply(False)
    return consent.apply(name)


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
    await lite.navigate(page=page, url=f"{site}/{path}")
    return session, page


async def _verdict(call) -> str:
    """The gate class a call lands on, or 'ran' when nothing gated it."""
    try:
        await call()
        return "ran"
    except ConfirmationRequired as exc:
        text = str(exc)
        if "payment-shaped" in text:
            return "payment_form"
        # THE FINER CLASSES ARE TESTED FIRST, and the order is load-bearing:
        # `credential_submit`'s sentence BEGINS "submitting a form that
        # carries...", so a generic prefix test above it reports the class
        # the ladder exists to stop reporting.
        for phrase, cls in (
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


async def _all_paths(site, page_name, *, query, submit_css, field_css):
    """One fixture, four write paths, one verdict. The same shape
    `test_gate_parity_across_every_write_path` pins for payment."""
    _, page = await _open(site, page_name)
    return {
        "click": await _verdict(lambda: lite.click(
            page=page, location={"css": submit_css})),
        "find_and_act": await _verdict(lambda: lite.find_and_act(
            page=page, query=query, action="click", timeout_ms=3000)),
        "press_keys": await _verdict(lambda: lite.press_keys(
            page=page, keys="Enter", location={"css": field_css})),
        "fill_form": await _verdict(lambda: lite.fill_form(
            page=page, fields=[{"css": field_css, "value": "x"}],
            submit=True)),
    }


# =====================================================================
# PIN 1 + PIN 2 — the friction goes away, on every path
# =====================================================================


def test_a_get_search_form_submits_with_zero_gates_on_every_path(site):
    """PIN 1 and PIN 2. Under the NARROW scope, and through all four write
    paths. This is the single change that removes the majority of the
    author's routine-research prompts, and it removes them for a stated
    reason (RFC 9110 9.2.1 makes GET a safe method) rather than for
    convenience."""
    scope("research")
    seen = run(_all_paths(site, "search.html", query="Search",
                          submit_css="#go", field_css="#terms"))
    assert set(seen.values()) == {"ran"}, seen


def test_a_post_search_asks_under_research_and_is_silent_under_full(site):
    """PIN 4, live. The same form, the same page, two scopes, and the
    difference between them IS the consent declaration.

    The honest limit ships with it: a site that implements search over POST
    still gates under `research`. That is the site making a claim about its
    own operation and this server taking it at its word."""
    scope("research")
    asked = run(_all_paths(site, "postsearch.html", query="Search",
                           submit_css="#go", field_css="#terms"))
    assert set(asked.values()) == {"form_submit"}, asked

    scope("full")
    silent = run(_all_paths(site, "postsearch.html", query="Search",
                            submit_css="#go", field_css="#terms"))
    assert set(silent.values()) == {"ran"}, silent


# =====================================================================
# The negative side, on the same four paths
# =====================================================================


def test_a_get_checkout_form_still_gates_on_every_path_at_every_scope(site):
    """PIN 12 and PIN 13 together, and this is the pin that stops a future
    refactor from inverting the rule. The GET admission test never becomes a
    Tier 2 exemption: payment is classified before the method is consulted,
    so a GET checkout gates through every mechanism and under `full`."""
    for name in ("research", "full"):
        scope(name)
        seen = run(_all_paths(site, "getcheckout.html", query="Pay now",
                              submit_css="#go", field_css="#card"))
        # Writing the card field itself is refused outright by credential
        # blindness rather than gated, which is the stronger answer.
        assert set(seen.values()) <= {"payment_form", "credential_refused"}, \
            (name, seen)
        assert "payment_form" in set(seen.values()), (name, seen)


def test_a_password_carrying_form_gates_as_credential_submit(site):
    """PIN 14, live. The gap the old table did not cover: the agent cannot
    TYPE the secret and could still press the button that sends it."""
    scope("full")
    seen = run(_all_paths(site, "login.html", query="Sign in",
                          submit_css="#go", field_css="#u"))
    assert set(seen.values()) == {"credential_submit"}, seen


def test_a_post_with_free_text_and_a_send_word_is_a_broadcast(site):
    """PIN 16, live, WITH ITS CONTROL ARM on the same page and in the same
    run. The single most consequential gap in the old table was that a post
    to other humans and a search were the same class."""
    scope("full")

    async def go():
        _, page = await _open(site, "broadcast.html")
        posted = await _verdict(lambda: lite.click(
            page=page, location={"css": "#go"}))
        searched = await _verdict(lambda: lite.click(
            page=page, location={"css": "#find"}))
        return posted, searched

    posted, searched = run(go())
    assert posted == "broadcast_submit"
    assert searched == "ran", (
        "the control arm gated: a gate that fires on everything is the same "
        "failure as a gate that fires on nothing, from the other side")


def test_an_i_agree_checkbox_form_gates_as_legal_assent(site):
    """PIN 18, live."""
    scope("full")

    async def go():
        _, page = await _open(site, "terms.html")
        return await _verdict(lambda: lite.click(
            page=page, location={"css": "#go"}))

    assert run(go()) == "legal_assent"


def test_a_sensitive_origin_gates_an_ordinary_click(site):
    """The human's own list, live. Acting on a listed origin is Tier 2 even
    when the action carries no gated class of its own, and a READ on the
    same origin is untouched."""
    os.environ["KS4WEB_SENSITIVE_ORIGINS"] = "127.0.0.1"
    scope("full")

    async def go():
        _, page = await _open(site, "search.html")
        gated = await _verdict(lambda: lite.click(
            page=page, location={"css": "#field"}))
        read = await lite.get_text(page=page)
        return gated, read

    gated, read = run(go())
    assert gated == "gated"
    assert read, "reading a listed origin is not gated: the list gates acting"


def test_the_audit_records_why_a_cleared_action_was_cleared(site):
    """PIN 27, live and end to end. The record must say `grade`, never
    `human`: an operational log that claimed a human answered when the scope
    cleared it would be a false record.

    The record is written by the server's tool wrapper rather than by the op,
    so the test drains the annotation the same way the wrapper does. What is
    being pinned is the ANNOTATION the choke point set, which is the only
    thing the op controls and the only thing that can be wrong here."""
    scope("research")

    async def go():
        _, page = await _open(site, "search.html")
        await lite.click(page=page, location={"css": "#go"})
        return audit.LOG.record("click", "ok", args={})

    record = run(go())
    assert record["gate"]["cleared_by"] == "grade"
    assert record["gate"]["cleared_by"] != "human"
    assert "9110" in record["gate"]["cleared_because"]
