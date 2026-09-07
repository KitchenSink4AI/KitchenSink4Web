"""Multi-context sessions (#14): two cookie jars, one session.

The dream-specs §3.10 pin list. Every session opened here is closed here
and the fixture asserts no owned PID survives, which is the standing rule
in `tests/browser/conftest.py` and matters more than usual in this file:
the launch loop takes a process-table baseline PER CONTEXT, and taking it
once outside the loop would make the second context's journal adopt the
first context's browser, so closing c2 would kill c1. That failure is
silent until a close, which is why C13 and C10 exist.

Two of the pre-found bugs live here too: the journal filename must not
carry a colon (Windows refuses the write, and a browser with no journal is
one the reaper is never permitted to kill), and the console and network
recorders must attach to EVERY context or a page in c2 records nothing and
both tools report an empty list as though it were the truth.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kitchensink4web.engine import hygiene
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import (BadParams, TargetNotFound,
                                    ValidationFailed)
from kitchensink4web.ops import lite
from kitchensink4web.policy import budgets as _budgets

pytestmark = pytest.mark.browser


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


# ------------------------------------------------------------------- C1

def test_c1_two_contexts_do_not_share_a_cookie_jar(session_factory,
                                                   fixture_site):
    async def go():
        sess = await session_factory(contexts=2)
        assert sorted(sess.contexts) == ["c1", "c2"]
        await sess.contexts["c1"].context.add_cookies([{
            "name": "who", "value": "admin", "url": fixture_site}])
        c1 = await sess.contexts["c1"].context.cookies()
        c2 = await sess.contexts["c2"].context.cookies()
        assert any(c["name"] == "who" for c in c1)
        assert not any(c["name"] == "who" for c in c2), (
            "the second context can see the first one's cookie, so the "
            "jars are not separate")
        assert sess.contexts["c1"].profile_dir \
            != sess.contexts["c2"].profile_dir

    run(go())


# ------------------------------------------------------------------- C2

def test_c2_page_handles_stay_flat_and_unique(session_factory,
                                              fixture_site):
    async def go():
        sess = await session_factory(contexts=2)
        first = sess.focused
        opened = await lite.manage_tabs(session=sess.session_id,
                                        action="open",
                                        url=f"{fixture_site}/form",
                                        context="c2")
        second = opened["page"]
        assert first != second
        found_session, found = MANAGER.locate(second)
        assert found_session is sess
        assert found.context == "c2"
        rows = {r["page"]: r for r in opened["pages"]}
        assert rows[first]["context"] == "c1"
        assert rows[second]["context"] == "c2"

    run(go())


# ------------------------------------------------------------------- C3

def test_c3_refs_do_not_cross_contexts(session_factory, fixture_site):
    async def go():
        sess = await session_factory(contexts=2)
        first = sess.focused
        await lite.navigate(page=first, url=f"{fixture_site}/form")
        await lite.get_page_view(page=first)
        ref = next(r for r, entry in sess.element_map.entries.items()
                   if entry.handle == first and not entry.gone)
        opened = await lite.manage_tabs(session=sess.session_id,
                                        action="open",
                                        url=f"{fixture_site}/form",
                                        context="c2")
        with pytest.raises(Exception) as caught:
            await lite.get_text(page=opened["page"],
                                location={"ref": ref})
        assert "re-read" not in str(caught.value).lower() or \
            opened["page"] in str(caught.value)

    run(go())


def _first_ref(payload: dict) -> str:
    import re
    found = re.search(r'(e\d+)', json.dumps(payload))
    assert found, "the read minted no refs"
    return found.group(1)


# ------------------------------------------------------------------- C4

def test_c4_the_budget_is_shared_across_contexts(session_factory,
                                                 fixture_site, monkeypatch):
    """A per-context ledger would mean contexts=5 multiplies the action
    budget by five, which is a bypass by construction."""
    async def go():
        monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "3")
        sess = await session_factory(contexts=2)
        _budgets.BOOK.drop(sess.session_id)
        first = sess.focused
        opened = await lite.manage_tabs(session=sess.session_id,
                                        action="open", context="c2")
        second = opened["page"]
        await lite.navigate(page=first, url=f"{fixture_site}/form")
        await lite.navigate(page=second, url=f"{fixture_site}/form")
        await lite.navigate(page=first, url=f"{fixture_site}/big")
        from kitchensink4web.errors import BudgetExhausted
        with pytest.raises(BudgetExhausted):
            await lite.navigate(page=second, url=f"{fixture_site}/big")

    run(go())


# ------------------------------------------------------------------- C5

def test_c5_one_origin_from_two_contexts_costs_one_origin(session_factory,
                                                          fixture_site):
    async def go():
        sess = await session_factory(contexts=2)
        _budgets.BOOK.drop(sess.session_id)
        first = sess.focused
        opened = await lite.manage_tabs(session=sess.session_id,
                                        action="open", context="c2")
        await lite.navigate(page=first, url=f"{fixture_site}/form")
        await lite.navigate(page=opened["page"], url=f"{fixture_site}/big")
        snapshot = _budgets.BOOK.snapshot(sess.session_id)
        assert snapshot["distinct_origins"] == 1

    run(go())


# ------------------------------------------------------------------- C6

def test_c6_auth_state_saves_and_loads_per_jar(session_factory,
                                               fixture_site, tmp_path,
                                               monkeypatch):
    async def go():
        from kitchensink4web import server
        from kitchensink4web.ops import storage as _storage
        from kitchensink4web.policy import gates

        server.configure(cli_packs=["storage"], read_only=False)
        # A gate `ask` that answers the way the real one does on a
        # confirmed re-run. This stub returned None until the consent
        # ladder landed in a sibling wave: the ops layer called `ask`
        # for its side effect and threw the answer away, and there is
        # one door now (policy.engine.confirm) that USES the answer and
        # holds it to the TOCTOU re-validation. A None here models an
        # engine that no longer exists. Same fix the consent wave made
        # to the three stubs in test_fieldlog2_fixes.py.
        def _redeemed(*a, **k):
            action_class = a[0] if a else k["action_class"]
            return gates.Gate(
                token="stub-" + action_class,
                action_class=action_class, tool=k.get("tool", "test"),
                session=k.get("session") or "", page=k.get("page"),
                target={}, summary=k.get("summary", ""), redeemed=True)

        monkeypatch.setattr(gates.ENGINE, "ask", _redeemed)
        sess = await session_factory(contexts=2)
        await lite.navigate(page=sess.focused, url=f"{fixture_site}/form")
        await sess.contexts["c1"].context.add_cookies([{
            "name": "who", "value": "admin", "url": fixture_site}])
        path = str(tmp_path / "c1.json")
        saved = await _storage.save_auth_state(session=sess.session_id,
                                               context="c1", path=path)
        assert saved["cookies_saved"] >= 1
        body = json.loads(Path(path).read_text(encoding="utf-8"))
        assert body["ks4web"]["context_label"] == "c1"
        await _storage.load_auth_state(session=sess.session_id,
                                       context="c2", path=path)
        c2 = await sess.contexts["c2"].context.cookies()
        assert any(c["name"] == "who" for c in c2)

    run(go())


# ------------------------------------------------------------------- C7

def test_c7_the_close_message_is_per_context_and_true(session_factory,
                                                      fixture_site,
                                                      tmp_path):
    """Field finding 41, per context: a session-level 'none were saved'
    while c2 was in fact saved is the same wrong answer in a new shape."""
    async def go():
        from kitchensink4web import server
        from kitchensink4web.ops import storage as _storage

        server.configure(cli_packs=["storage"], read_only=False)
        sess = await session_factory(contexts=2)
        await lite.navigate(page=sess.focused, url=f"{fixture_site}/form")
        for label in ("c1", "c2"):
            await sess.contexts[label].context.add_cookies([{
                "name": "who", "value": label, "url": fixture_site}])
        path = str(tmp_path / "c2.json")
        await _storage.save_auth_state(session=sess.session_id,
                                       context="c2", path=path)
        result = await lite.manage_session(action="close",
                                           session=sess.session_id)
        rows = {r["context"]: r for r in result["contexts"]}
        assert path in str(rows["c2"]["auth_state"])
        assert "none were saved" in str(rows["c1"]["auth_state"])

    run(go())


# ------------------------------------------------------------------- C8

def test_c8_closing_the_last_context_refuses(session_factory):
    async def go():
        sess = await session_factory(contexts=1)
        with pytest.raises(ValidationFailed) as caught:
            await lite.manage_session(action="close",
                                      session=sess.session_id,
                                      context="c1")
        assert "action='close'" in str(caught.value)
        # And the session still works afterwards.
        listed = await lite.manage_tabs(session=sess.session_id,
                                        action="list")
        assert listed["pages"]

    run(go())


# ------------------------------------------------------------------- C9

def test_c9_closing_one_context_invalidates_only_its_refs(session_factory,
                                                          fixture_site):
    async def go():
        sess = await session_factory(contexts=2)
        keep = sess.focused
        await lite.navigate(page=keep, url=f"{fixture_site}/form")
        await lite.get_page_view(page=keep)
        kept_refs = lite._live_refs(sess, keep)
        assert kept_refs > 0
        opened = await lite.manage_tabs(session=sess.session_id,
                                        action="open",
                                        url=f"{fixture_site}/form",
                                        context="c2")
        await lite.get_page_view(page=opened["page"])
        doomed_refs = lite._live_refs(sess, opened["page"])
        assert doomed_refs > 0
        result = await lite.manage_session(action="close",
                                           session=sess.session_id,
                                           context="c2")
        assert lite._live_refs(sess, keep) == kept_refs
        assert lite._live_refs(sess, opened["page"]) == 0
        assert result["refs_invalidated"] == doomed_refs
        assert sorted(sess.contexts) == ["c1"]

    run(go())


# ------------------------------------------------------------------ C10

def test_c10_zero_orphans_after_a_two_context_session(session_factory):
    async def go():
        sess = await session_factory(contexts=2)
        pids = {label: list(handle.journal.pids)
                for label, handle in sess.contexts.items()}
        assert all(pids.values()), "a context journalled no owned PIDs"
        assert set(pids["c1"]).isdisjoint(pids["c2"]), (
            "the two journals share a PID, so the process-table baseline "
            "was taken once instead of once per launch, and closing one "
            "context would kill the other one's browser")
        profiles = [handle.profile_dir for handle in sess.contexts.values()]
        result = await MANAGER.close(sess.session_id)
        assert all(not r["survivors_killed"] for r in result["contexts"])
        for pid in [p for group in pids.values() for p in group]:
            assert not hygiene.alive(pid)
        for profile in profiles:
            assert not Path(profile).exists()

    run(go())


def test_the_journal_filename_carries_no_colon(session_factory):
    """Pre-found bug #4. `OwnedProcesses` names its file
    `session-{owner_pid}-{session_id}.json`, so a colon in the context
    label fails the write on Windows, and a live browser with no journal is
    one the reaper is never permitted to kill."""
    async def go():
        sess = await session_factory(contexts=2)
        for handle in sess.contexts.values():
            name = Path(handle.journal.path).name
            assert ":" not in name, name
            assert Path(handle.journal.path).is_file(), (
                f"{name} was never written")

    run(go())


# ------------------------------------------------------------------ C11

def test_c11_the_recorders_attach_to_every_context(session_factory,
                                                   fixture_site):
    """Pre-found bug #5. The console and network recorders attached to
    `session.context` once, so a page in the second context produced no
    console messages and no request records and both tools reported an
    empty list as though it were the truth. Silent loss, not an error."""
    async def go():
        from kitchensink4web import server
        from kitchensink4web.ops import diag as _diag
        from kitchensink4web.ops import net as _net

        server.configure(cli_packs=["diagnostics", "network"],
                         read_only=False)
        sess = await session_factory(contexts=2)
        opened = await lite.manage_tabs(session=sess.session_id,
                                        action="open",
                                        url=f"{fixture_site}/form",
                                        context="c2")
        page = opened["page"]
        await MANAGER.locate(page)[1].page.evaluate(
            "() => console.error('from c2')")
        console = await _diag.list_console(session=sess.session_id)
        assert "from c2" in json.dumps(console), console
        requests = await _net.list_requests(session=sess.session_id)
        assert f"{fixture_site}/form" in json.dumps(requests), (
            "a request from the second context was never recorded")

    run(go())


# ------------------------------------------------------------------ C12

def test_c12_an_ambiguous_per_jar_call_refuses(session_factory,
                                               fixture_site):
    async def go():
        from kitchensink4web import server
        from kitchensink4web.ops import storage as _storage

        server.configure(cli_packs=["storage"], read_only=False)
        sess = await session_factory(contexts=2)
        await lite.navigate(page=sess.focused, url=f"{fixture_site}/form")
        with pytest.raises(BadParams) as caught:
            await _storage.manage_cookies(session=sess.session_id,
                                          action="list")
        assert "c1" in str(caught.value) and "c2" in str(caught.value)
        # The same call on a single-context session is unchanged.
        solo = await session_factory()
        await lite.navigate(page=solo.focused, url=f"{fixture_site}/form")
        out = await _storage.manage_cookies(session=solo.session_id,
                                            action="list")
        assert "cookies" in out

    run(go())


def test_a_handoff_on_a_multi_jar_session_names_the_jar(session_factory,
                                                        fixture_site):
    """The headed window a human signs into carries ONE identity. Silently
    moving the focused jar's cookies would hand them the wrong one."""
    async def go():
        sess = await session_factory(contexts=2)
        await lite.navigate(page=sess.focused, url=f"{fixture_site}/form")
        with pytest.raises(BadParams) as caught:
            await lite.manage_session(action="handoff",
                                      session=sess.session_id)
        assert "c1" in str(caught.value) and "c2" in str(caught.value)

    run(go())


def test_an_unknown_context_label_lists_the_real_ones(session_factory):
    async def go():
        sess = await session_factory(contexts=2)
        with pytest.raises(TargetNotFound) as caught:
            await lite.manage_tabs(session=sess.session_id, action="open",
                                   context="c9")
        assert "c1" in str(caught.value) and "c2" in str(caught.value)
        assert "never reused" in str(caught.value)

    run(go())


# ------------------------------------------------------------------ C13

def test_c13_a_failed_second_context_tears_down_the_first(monkeypatch,
                                                          session_factory):
    """A launch that fails at context k must leave nothing running and
    return no session handle. Half a session is a state nothing else in
    this code expects."""
    async def go():
        from kitchensink4web.engine import session as _session_mod

        real = _session_mod.hygiene.new_profile_dir
        calls = {"n": 0}

        def explode(prefix):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("the second profile directory could not be "
                              "created")
            return real(prefix)

        monkeypatch.setattr(_session_mod.hygiene, "new_profile_dir", explode)
        before = set(MANAGER.sessions)
        with pytest.raises(Exception):
            await MANAGER.open(headless=True, contexts=2)
        assert set(MANAGER.sessions) == before, (
            "a half-built session was handed back")

    run(go())


# ------------------------------------------------------------------ C14

def test_c14_one_dead_context_does_not_report_a_healthy_session(
        session_factory):
    """`degraded` is the aggregate word. Reporting a session as alive
    because one context is would be the completeness-over-omissions
    failure the doctrine names."""
    async def go():
        sess = await session_factory(contexts=2)
        for pid in list(sess.contexts["c2"].journal.pids):
            hygiene.kill(pid)
        for _ in range(40):
            if sess.contexts["c2"].alive() is False:
                break
            await asyncio.sleep(0.25)
        status = await lite.manage_session(action="status")
        row = next(r for r in status["sessions"]
                   if r["session"] == sess.session_id)
        assert row["browser"] == "degraded"
        rows = {c["context"]: c for c in row["contexts"]}
        assert rows["c1"]["health"] == "alive"
        assert rows["c2"]["health"] == "dead"
        assert "recommendation" in rows["c2"]

    run(go())


# --------------------------------------------------- adding and capping

def test_a_context_can_be_added_to_a_live_session(session_factory,
                                                  fixture_site):
    async def go():
        sess = await session_factory()
        assert sorted(sess.contexts) == ["c1"]
        out = await lite.manage_session(action="open",
                                        session=sess.session_id,
                                        contexts=1)
        assert out["added_context"] == "c2"
        assert sorted(sess.contexts) == ["c1", "c2"]
        assert sess.contexts["c2"].spec.label == sess.spec.label

    run(go())


def test_the_context_cap_refuses_with_the_number(session_factory):
    async def go():
        with pytest.raises(BadParams) as caught:
            await MANAGER.open(headless=True, contexts=99)
        assert "KS4WEB_MAX_CONTEXTS" in str(caught.value)
        assert not MANAGER.sessions

    run(go())


def test_a_single_auth_state_string_refuses_for_two_contexts(monkeypatch):
    async def go():
        from kitchensink4web import server

        server.configure(cli_packs=["storage"], read_only=False)
        with pytest.raises(BadParams) as caught:
            await lite.manage_session(action="open", contexts=2,
                                      auth_state="C:/tmp/one.json")
        assert "c1" in str(caught.value) and "c2" in str(caught.value)
        assert not MANAGER.sessions

    run(go())
