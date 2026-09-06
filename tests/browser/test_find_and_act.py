"""find_and_act: the composite, and the proof that fusing cost it nothing.

The field measurement is the reason it exists. A four-step workflow cost
sixteen tool calls and half of them were find_elements immediately followed
by click or type_text, with the search existing only to produce a ref the
next call consumed. Fusing that pair is the 80 percent win; fusing it badly
is how a browser tool starts clicking the wrong thing.

So this file is two halves and the second is the larger one.

**Half one: it works.** One call finds and acts, the scope modifier composes,
and the result names the element the search settled on.

**Half two: every gate still fires, and fires the SAME.** The composite does
not reimplement acting. It resolves one target, mints a session ref, and then
calls the very function the two-call path calls. Each scenario below is a
Phase 4 gate scenario re-run through the composite:

  form_submit classification   a submit control gates rather than clicking
  credential blindness         a password field refuses, naming the routes
  TARGET_CHANGED               a swap inside the find-to-act window aborts
  TOCTOU re-validation         the swapped submit gates and never submits
  budget charge                the action counter moves by exactly one
  ambiguity                    several matches refuse, listing actable refs
  zero matches                 refuses with the nearest misses

Read-only absence is the one gate that cannot be proven here, because it is a
property of registration rather than of a call; it is proven in
`tests/unit/test_readonly_invariant.py` over a real MCP client.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from kitchensink4web import envelope
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (AmbiguousLocation, BadParams,
                                    ConfirmationRequired, CredentialRefused,
                                    TargetChanged, TargetNotFound)
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets, credentials, gates, readonly

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def corpus_site():
    handler = functools.partial(_Quiet, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def clean_policy(monkeypatch):
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


async def _open(site, path, read=True):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{site}/{path}")
    if read:
        await lite.get_page_view(page=page)
    return session, page


# ------------------------------------------------------------ half one


def test_one_call_finds_and_clicks(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/pathological.html")
        out = await lite.find_and_act(page=page, query="Cancel order",
                                      timeout_ms=4000)
        assert out["tool"] == "find_and_act"
        assert out["acted"] == "click"
        assert out["target"]["name"] == "Cancel order"
        assert out["changed"]["effect"] != "none-observed"
        assert '"Cancel order"' in out["found"]["match"]
        assert out["found"]["scope"] == "whole page"

    run(go())


def test_one_call_finds_and_types_and_reads_the_value_back(corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        out = await lite.find_and_act(page=page, query="Field 1, email",
                                      action="type", text="a@b.com")
        assert out["acted"] == "type"
        assert out["value_state"] == "a@b.com"

    run(go())


def test_a_match_past_the_extractor_cap_is_still_actable(corpus_site):
    """bigform carries 321 controls and the extractor's return cap is 300, so
    'Submit return' sits past it. The search finds it (the search is uncapped
    by design), and until the pin landed on 2026-09-06 the acting half then
    refused STALE because the ladder was searching a list that stopped at
    300. Reaching the form-submit gate is the proof it resolved."""
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        with pytest.raises(ConfirmationRequired):
            await lite.find_and_act(page=page, query="Submit return",
                                    role="button", timeout_ms=4000)

    run(go())


def test_the_role_filter_narrows_the_composite(corpus_site):
    """The field finding that produced the role filter, applied to the fused
    call: the filter is applied before anything is acted on, so a query that
    matches a button under role='link' finds nothing rather than acting."""
    async def go():
        _, page = await _open(corpus_site, "b/regions_shadow.html")
        with pytest.raises(TargetNotFound) as exc:
            await lite.find_and_act(page=page, query="Publish draft",
                                    role="link")
        assert "with role='link'" in str(exc.value)
        out = await lite.find_and_act(page=page, query="Publish draft",
                                      role="button", timeout_ms=4000)
        assert out["target"]["name"] == "Publish draft"

    run(go())


def test_within_scopes_the_composite_search(corpus_site):
    """`within` is the same scope find_elements takes, so the ambiguity that
    blocks a page-wide Save resolves inside one region that holds one."""
    async def go():
        _, page = await _open(corpus_site, "b/regions_shadow.html")
        with pytest.raises(AmbiguousLocation):
            await lite.find_and_act(page=page, query="Save")
        out = await lite.find_and_act(page=page, query="Save",
                                      within={"region": "r3"}, timeout_ms=4000)
        assert out["target"]["name"] == "Save"
        assert out["found"]["scope"] == {"region": "r3"}
        # And a region that does not hold the string refuses rather than
        # falling back to the page.
        with pytest.raises(TargetNotFound) as gone:
            await lite.find_and_act(page=page, query="Restore archive",
                                    within={"region": "r1"})
        assert "within r1" in str(gone.value)

    run(go())


def test_a_missing_action_argument_refuses_before_anything_resolves(
        corpus_site):
    async def go():
        _, page = await _open(corpus_site, "b/bigform.html")
        with pytest.raises(BadParams) as exc:
            await lite.find_and_act(page=page, query="Work email",
                                    action="type")
        assert "needs `text`" in str(exc.value)
        with pytest.raises(BadParams):
            await lite.find_and_act(page=page, query="x", action="teleport")
        with pytest.raises(BadParams) as bare:
            await lite.find_and_act(page=page, action="click")
        assert "location={'ref': 'e12'}" in str(bare.value)

    run(go())


# ------------------------------------------- half two: the ambiguity contract


def test_several_matches_refuse_and_list_candidates_that_are_actable(
        corpus_site):
    """The non-negotiable half. Five Save controls: the call refuses, lists
    every candidate the way find_elements lists a match, and each ref in that
    refusal is one the caller's next call can act on."""
    async def go():
        session, page = await _open(corpus_site, "b/regions_shadow.html")
        with pytest.raises(AmbiguousLocation) as exc:
            await lite.find_and_act(page=page, query="Save")
        text = str(exc.value)
        assert "5 visible elements match" in text
        assert "no tool acts on first match" in text
        assert "Nothing was done" in text
        # The candidate lines carry refs, and the refs resolve and act. They
        # ride INSIDE the page-data envelope since 2026-09-06 (gauntlet 2 M1):
        # the lines quote accessible names verbatim and an accessible name is
        # page-authored, so the fused tool wraps them the way find_elements
        # already wrapped the identical strings.
        assert "UNTRUSTED PAGE CONTENT" in text
        block = text.split("KS4WEB-PAGE-DATA")[1].split(">>>")[1]
        refs = [chunk.split(" | ")[0].strip()
                for chunk in block.split("; ")]
        refs = [r for r in refs if r.startswith("e")]
        assert len(refs) == 5
        for ref in refs:
            assert session.element_map.entries[ref].kind == "affordance"
        out = await lite.click(page=page, location={"ref": refs[0]},
                               timeout_ms=4000)
        assert out["target"]["name"].startswith("Save")

    run(go())


def test_zero_matches_refuses_the_way_an_action_refuses(corpus_site):
    """An action's zero-match refusal carries the nearest misses so a typo is
    a one-turn recovery. The composite's does the same, in the same words."""
    async def go():
        _, page = await _open(corpus_site, "b/regions_shadow.html")
        with pytest.raises(TargetNotFound) as exc:
            await lite.find_and_act(page=page, query="Publish drft")
        text = str(exc.value)
        assert "nothing visible matches" in text
        assert "Nearest by name:" in text
        assert "Publish draft" in text

    run(go())


def test_a_hidden_match_is_counted_and_never_acted_on(corpus_site):
    """Visibility is the same filter the live resolver applies. A control
    that exists but is hidden is not a target, and the refusal says how many
    were skipped rather than silently acting on one."""
    async def go():
        session, page = await _open(corpus_site, "b/regions_shadow.html")
        await session.page(page).page.evaluate("""() => {
          const b = document.createElement('button');
          b.textContent = 'Detonate';
          b.style.display = 'none';
          document.body.appendChild(b);
        }""")
        with pytest.raises(TargetNotFound) as exc:
            await lite.find_and_act(page=page, query="Detonate")
        assert "1 match(es) are in hidden content" in str(exc.value)

    run(go())


# ------------------------------------------------- half two: the gate parity


def test_form_submit_classification_gates_through_the_composite(corpus_site):
    """Phase 4 gate `credentials_gates`, submit half. A submit-typed control
    is a gated class, so the composite ASKS and, with no confirmation channel
    in this harness, fails closed. The two-call path is driven right after it
    on the same page and refuses identically."""
    async def go():
        session, page = await _open(corpus_site, "b/bigform.html")
        url_before = session.page(page).page.url
        with pytest.raises(ConfirmationRequired) as fused:
            await lite.find_and_act(page=page, query="Submit return",
                                    role="button", timeout_ms=4000)
        with pytest.raises(ConfirmationRequired) as split:
            await lite.click(page=page, location={"css": "#submit-return"},
                             timeout_ms=4000)
        assert (envelope.classify(fused.value)
                == envelope.classify(split.value) == "CONFIRMATION_REQUIRED")
        # Same gated CLASS, read from the closed set rather than from a
        # substring the message happens to carry. `bigform.html` carries a
        # `cc-number` field, and since 2026-09-06 a SUBMISSION is judged by
        # the form rather than by the control that triggered it: the moment
        # the card number leaves is the submission, so submitting a form that
        # holds one is `payment_form` on every path that can cause it
        # (gauntlet 2 C1). Writing an ordinary field in that same form is
        # still ungated; only the submission escalates.
        submit_class = gates.GATED_CLASSES["payment_form"]
        assert str(fused.value).startswith(submit_class)
        assert str(split.value).startswith(submit_class)
        assert session.page(page).page.url == url_before

    run(go())


def test_a_secret_field_refuses_through_the_composite(corpus_site):
    """Phase 4 gate `credentials_gates`, secret half. The credential check
    lives at the choke point, so the fused call cannot route around it."""
    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        page = session.focused
        # The driver's own goto, as the Phase 4 file does it: this fixture
        # advertises an expired session, and `navigate` refuses AUTH_REQUIRED
        # before the test can reach the field it is about.
        await session.pages[page].page.goto(
            f"{corpus_site}/c/expired_login.html")
        with pytest.raises(CredentialRefused) as fused:
            await lite.find_and_act(page=page, query="Password",
                                    action="type", text="hunter2")
        with pytest.raises(CredentialRefused) as split:
            await lite.type_text(page=page,
                                 location={"css": "input[type=password]"},
                                 text="hunter2")
        assert (envelope.classify(fused.value)
                == envelope.classify(split.value) == "CREDENTIAL_REFUSED")
        assert "handoff" in str(fused.value)
        assert "save_auth_state" in str(fused.value)

    run(go())


def test_the_toctou_swap_gates_through_the_composite_and_never_submits(
        corpus_site):
    """Phase 4 gate `toctou_actions`, the plain-click half. The page has
    already swapped its benign Continue for a destructive submit; a fused
    call that finds the destructive control by its new name still meets the
    gate, and the form never posts."""
    async def go():
        session, page = await _open(corpus_site,
                                    "c/toctou.html?swap_ms=100000")
        record = session.pages[page]
        await record.page.evaluate("() => swap()")
        url_before = record.page.url
        with pytest.raises(ConfirmationRequired):
            await lite.find_and_act(page=page, query="Delete account",
                                    timeout_ms=3000)
        assert record.page.url == url_before, "the destructive form submitted"

    run(go())


def test_a_swap_inside_the_find_to_act_window_aborts_target_changed(
        corpus_site, monkeypatch):
    """Phase 4 gate `toctou_actions`, the TARGET_CHANGED half, aimed at the
    one window the composite creates: between the search that mints the ref
    and the action that spends it.

    That window is microseconds wide in production, which is untestable, so
    the harness holds it open: `lite.click` is wrapped to fire the fixture's
    own `rename()` before delegating to the real click. The composite
    resolves 'Save', the element wearing that testid becomes 'Delete
    account', and the rebind ladder refuses rather than clicking it. Nothing
    about the composite is stubbed; only the width of the window is. The
    substitute is `type=button`, so the refusal has to come from the identity
    cross-check rather than from the form-submit gate catching it by luck."""
    async def go():
        session, page = await _open(corpus_site, "b/rename_on_demand.html")
        record = session.pages[page]
        real_click = lite.click

        async def rename_then_click(**kwargs):
            await record.page.evaluate("() => window.rename()")
            return await real_click(**kwargs)

        monkeypatch.setattr(lite, "click", rename_then_click)
        with pytest.raises(TargetChanged) as exc:
            await lite.find_and_act(page=page, query="Save", timeout_ms=3000)
        text = str(exc.value)
        assert "Save" in text and "Delete account" in text
        assert "nothing was done" in text.lower()
        deleted = await record.page.evaluate("() => window.__deleted || 0")
        assert deleted == 0, "the refused click still landed"

    run(go())


def test_the_action_budget_is_charged_exactly_once(corpus_site):
    """The budget charge rides the same choke point, so a fused call costs
    one action, not zero (routing around the charge) and not two (charging
    the search as well)."""
    async def go():
        session, page = await _open(corpus_site, "b/pathological.html")
        before = budgets.BOOK.snapshot(session.session_id)["counters"]
        await lite.find_and_act(page=page, query="Cancel order",
                                timeout_ms=4000)
        after = budgets.BOOK.snapshot(session.session_id)["counters"]
        assert after["actions"] == before["actions"] + 1

    run(go())


def test_the_audit_record_carries_a_replayable_anchor(corpus_site):
    """DESIGN 5.6: the audit trail is the recording substrate, so a fused
    call has to leave the same replayable record the two-call path leaves.
    The replay entry names the tool that ACTED, since replaying a click is
    what re-does the step."""
    async def go():
        from kitchensink4web.policy import audit as _audit
        _, page = await _open(corpus_site, "b/pathological.html")
        await lite.find_and_act(page=page, query="Cancel order",
                                timeout_ms=4000)
        # The record call is the seam the server wrapper owns; the ops layer
        # sets the annotations and the wrapper drains them, so the test
        # reproduces the wrapper's one line rather than routing through MCP.
        _audit.LOG.record("find_and_act", "ok", args={})
        got = _audit.LOG.read(limit=5, tool="find_and_act")
        assert got["records"], got
        replay = got["records"][0].get("replay") or {}
        assert replay.get("tool") == "click"
        assert replay.get("anchor", {}).get("name") == "Cancel order"
        assert replay.get("anchor_id")

    run(go())
