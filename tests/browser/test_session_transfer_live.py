"""Session handle transfer against a real browser (lifecycle spec §8.4).

The unit half proves the token and the refusals. This half proves the
reconciliation report, which is the part that can only lie in the presence
of a real page: a ref count is a claim about a document, and the document
is what changes between an export and an import.

Everything runs on the local deterministic fixture site. Nothing touches
the network.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web.engine import handles as _handles
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import Conflict, SessionDead
from kitchensink4web.ops import lite

pytestmark = pytest.mark.browser


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


@pytest.fixture(autouse=True)
def scratch_store(tmp_path, monkeypatch):
    monkeypatch.setattr(_handles, "STORE",
                        _handles.HandleStore(tmp_path / "handles.json"))
    MANAGER.tombstones.clear()
    yield
    MANAGER.tombstones.clear()


async def _read(handle):
    """One read, so the session mints refs worth counting."""
    return await lite.get_page_view(page=handle)


# ------------------------------------------------------------------ H-12

def test_h12_a_clean_import_loses_nothing_and_says_so(session_factory,
                                                      fixture_site):
    async def go():
        sess = await session_factory()
        page = sess.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        await _read(page)
        minted = lite._live_refs(sess, page)
        assert minted > 0, "the fixture read minted no refs to compare"

        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        report = await lite.manage_session(action="import_handle",
                                           token=export["token"])
        assert report["imported"] == sess.session_id
        row = next(r for r in report["pages"] if r["page"] == page)
        assert row["same_document_as_export"] is True
        assert row["live_refs"] == minted
        assert "nothing was copied" in report["not_carried"]

    run(go())


# ------------------------------------------------------------------ H-13

def test_h13_a_navigation_is_reported_per_page_not_globally(session_factory,
                                                            fixture_site):
    async def go():
        sess = await session_factory()
        stay = sess.focused
        await lite.navigate(page=stay, url=f"{fixture_site}/form")
        await _read(stay)
        opened = await lite.manage_tabs(session=sess.session_id, action="open",
                                        url=f"{fixture_site}/big")
        moves = opened["page"]
        await _read(moves)
        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        await lite.navigate(page=moves, url=f"{fixture_site}/form")
        report = await lite.manage_session(action="import_handle",
                                           token=export["token"])
        rows = {r["page"]: r for r in report["pages"]}
        assert rows[stay]["same_document_as_export"] is True
        assert rows[stay]["live_refs"] > 0
        assert rows[moves]["same_document_as_export"] is False
        assert rows[moves]["live_refs"] == 0
        assert "navigated" in rows[moves]["refs"]

    run(go())


# ------------------------------------------------------------------ H-14

def test_h14_a_parked_page_does_not_claim_live_refs(session_factory,
                                                    fixture_site):
    """The second D2 pin, from this feature's side. A park is a navigation,
    so the refs minted on the old document die with it; a reconciliation
    that counted them as live would be inventing usable addresses."""
    async def go():
        sess = await session_factory()
        page = sess.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        await _read(page)
        assert lite._live_refs(sess, page) > 0
        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        await MANAGER.park_idle(force=True)
        report = await lite.manage_session(action="import_handle",
                                           token=export["token"])
        row = next(r for r in report["pages"] if r["page"] == page)
        assert row["live_refs"] == 0
        assert row["same_document_as_export"] is False

    run(go())


# ------------------------------------------------------------------ H-15

def test_h15_a_crashed_page_is_reported_at_import(session_factory,
                                                  fixture_site):
    async def go():
        sess = await session_factory()
        page = sess.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        sess.pages[page].crashed = "the renderer crashed at 00:00:00"
        report = await lite.manage_session(action="import_handle",
                                           token=export["token"])
        row = next(r for r in report["pages"] if r["page"] == page)
        assert "dead" in row, (
            "a crashed page was reported as an ordinary one, so the next "
            "call discovers it instead of the report naming it")

    run(go())


# ------------------------------------------------------------------ H-16

def test_h16_a_held_dialog_is_reported_at_import(session_factory,
                                                 fixture_site):
    async def go():
        from kitchensink4web import dialogs as _dialogs

        sess = await session_factory()
        page = sess.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        desk = _dialogs.desk(sess)
        desk.note_pending(_dialogs.Pending(
            dialog_id=desk.next_id("d"), kind="confirm",
            message="are you sure", default_value="", page=page,
            url=sess.pages[page].page.url, driver=None))
        report = await lite.manage_session(action="import_handle",
                                           token=export["token"])
        row = next(r for r in report["pages"] if r["page"] == page)
        assert "dialog_held" in row
        assert "handle_dialog" in row["dialog_held"]
        desk.resolve_pending(page)

    run(go())


# ------------------------------------------------------------------ H-17

def test_h17_budget_spend_carries_and_is_disclosed(session_factory,
                                                   fixture_site):
    async def go():
        sess = await session_factory()
        page = sess.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        await lite.navigate(page=page, url=f"{fixture_site}/big")
        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        spent = export["receipt"]["budget"]["navigations"]
        assert spent >= 2
        report = await lite.manage_session(action="import_handle",
                                           token=export["token"])
        assert report["budget"]["navigations"] >= spent
        assert "spent" in report["budget"]["note"]

    run(go())


# ------------------------------------------------------------------ H-18

def test_h18_a_dead_browser_refuses_with_the_health_verdict(session_factory,
                                                            fixture_site):
    """One verdict, quoted. Two features computing liveness separately is
    how they end up disagreeing about the same browser."""
    async def go():
        from kitchensink4web.engine import hygiene

        sess = await session_factory()
        page = sess.focused
        await lite.navigate(page=page, url=f"{fixture_site}/form")
        export = await lite.manage_session(action="export_handle",
                                           session=sess.session_id)
        for pid in list(sess.journal.pids):
            hygiene.kill(pid)
        for _ in range(40):
            if sess.browser_alive() is False:
                break
            await asyncio.sleep(0.25)
        assert sess.browser_alive() is False, "the browser did not die"
        expected = lite._session_status(sess)["health"]
        with pytest.raises(SessionDead) as caught:
            await lite.manage_session(action="import_handle",
                                      token=export["token"])
        assert str(caught.value) == expected

    run(go())


# ------------------------------------------------- the tombstone, live

def test_an_imported_handle_after_a_close_names_the_close(session_factory,
                                                          fixture_site):
    async def go():
        sess = await session_factory()
        sid = sess.session_id
        await lite.navigate(page=sess.focused,
                            url=f"{fixture_site}/form")
        export = await lite.manage_session(action="export_handle",
                                           session=sid)
        await lite.manage_session(action="close", session=sid)
        with pytest.raises(Conflict) as caught:
            await lite.manage_session(action="import_handle",
                                      token=export["token"])
        assert "closed" in str(caught.value)

    run(go())
