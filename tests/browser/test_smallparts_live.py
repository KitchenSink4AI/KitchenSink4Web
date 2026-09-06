"""The small-parts wave against a real browser.

The unit battery pins the pure functions; this pins the behaviour that only
a driver can show:

- a tab holding a non-HTML resource reports what it holds and REFUSES to be
  read as prose, and the fetch route saves the real bytes through the
  session that opened it
- a session opened with a locale, a time zone, and a viewport produces a
  page that reports all three itself, read back rather than assumed
- the paginate-until read walks a rel="next" chain, stops honestly at each
  of its three stop conditions, and charges the navigation budget per hop
- the clipboard round-trips and comes back inside the labeled envelope

Every route these tests use lives in the shared fixture server, so nothing
here touches the network.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web import packs
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.errors import UnsupportedContent
from kitchensink4web.ops import common, extract, files, lite
from kitchensink4web.policy import credentials, gates, readonly

pytestmark = pytest.mark.browser


@pytest.fixture(autouse=True)
def loaded_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "_LOADED",
                        set(packs.PACK_SUMMARIES), raising=False)
    monkeypatch.setenv(common.ENV_DOWNLOAD_DIR, str(tmp_path / "dl"))
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


async def _open(base, path, **kwargs):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True,
                                 **kwargs)
    page = session.focused
    await lite.navigate(page=page, url=f"{base}{path}")
    return session, page


async def _allowed(call):
    """Answer the gate rather than dodge it: saving to disk is a gated class
    and these tests are about what the call does once it may run."""
    from kitchensink4web.errors import ConfirmationRequired
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


# ---------------------------------------------------- 1. PDF / blob escape


def test_a_tab_holding_an_image_says_so_and_refuses_to_be_read(fixture_site):
    """The inverted finding, end to end. Navigation is not blocked, because
    going to a file in order to save it is a normal thing to do; the reads
    are, because prose scraped out of a browser's own viewer is reordered
    and partial and would arrive looking like a successful read."""
    async def go():
        session, page = await _open(fixture_site, "/pixel.png")
        landed = await lite.navigate(page=page,
                                     url=f"{fixture_site}/pixel.png")
        assert landed["resource"]["kind"] == "binary"
        assert landed["resource"]["media_type"] == "image/png"
        assert landed["resource"]["filename"] == "pixel.png"
        assert landed["resource"]["readable"] is False
        assert "download" in landed["resource"]["route"]

        with pytest.raises(UnsupportedContent) as view:
            await lite.get_page_view(page=page)
        assert "pixel.png" in str(view.value)
        with pytest.raises(UnsupportedContent) as text:
            await lite.get_text(page=page)
        assert "action=\"fetch\"" in str(text.value)
        return session
    run(go())


def test_an_ordinary_page_is_read_normally_and_carries_no_resource_block(
        fixture_site):
    """The guard on the guard: the escape hatch must not intercept the
    pages the whole product exists to read."""
    async def go():
        session, page = await _open(fixture_site, "/")
        landed = await lite.navigate(page=page, url=f"{fixture_site}/form")
        assert "resource" not in landed
        view = await lite.get_page_view(page=page)
        assert view["projection"]
        return session
    run(go())


def test_fetch_saves_the_real_bytes_through_the_session(fixture_site,
                                                        tmp_path):
    async def go():
        session, page = await _open(fixture_site, "/pixel.png")
        saved = await _allowed(lambda: files.download(
            page=page, action="fetch"))
        assert saved["suggested_filename"] == "pixel.png"
        assert saved["media_type"] == "image/png"
        with open(saved["saved_to"], "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
        assert saved["bytes"] > 0
        return session
    run(go())


def test_fetch_keeps_the_name_the_server_gave_the_file(fixture_site):
    """Content-Disposition beats the URL path, which is what stops a
    download from landing as a bare UUID (browser-use #1951)."""
    async def go():
        session, page = await _open(fixture_site, "/")
        saved = await _allowed(lambda: files.download(
            page=page, action="fetch", url=f"{fixture_site}/file.txt"))
        assert saved["suggested_filename"] == "spike.txt"
        return session
    run(go())


def test_fetch_refuses_a_blob_url_instead_of_promising_a_re_request(
        fixture_site):
    async def go():
        session, page = await _open(fixture_site, "/")
        with pytest.raises(UnsupportedContent) as caught:
            await files.download(page=page, action="fetch",
                                 url="blob:http://127.0.0.1/9f3e-uuid")
        assert "inside the page" in str(caught.value)
        assert "action='click'" in str(caught.value)
        return session
    run(go())


# ------------------------------------- 2. device, locale, timezone at open


def test_a_session_opens_with_the_locale_timezone_and_viewport_asked_for(
        fixture_site):
    """Read back from the page rather than assumed, which is the whole
    reason the competitors' emulation bugs (cdt#2115, cdt#280) are state
    desync rather than missing features."""
    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True, locale="ko-KR",
                                     timezone="Asia/Seoul",
                                     viewport="390x844")
        page = session.focused
        await lite.navigate(page=page, url=f"{fixture_site}/")
        reported = await session.pages[page].page.evaluate(
            "() => ({lang: navigator.language,"
            " tz: Intl.DateTimeFormat().resolvedOptions().timeZone,"
            " w: innerWidth, h: innerHeight})")
        assert reported["lang"] == "ko-KR"
        assert reported["tz"] == "Asia/Seoul"
        assert reported["w"] == 390 and reported["h"] == 844
        assert session.emulation == {"viewport": {"width": 390,
                                                  "height": 844},
                                     "locale": "ko-KR",
                                     "timezone": "Asia/Seoul"}
        status = await lite.manage_session(action="status")
        row = next(s for s in status["sessions"]
                   if s["session"] == session.session_id)
        assert row["emulation"]["timezone"] == "Asia/Seoul"
        return session
    run(go())


def test_a_session_opened_with_nothing_asked_for_reports_no_emulation(
        fixture_site):
    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        assert session.emulation == {}
        opened = await lite.manage_session(action="status")
        row = next(s for s in opened["sessions"]
                   if s["session"] == session.session_id)
        assert "emulation" not in row
        return session
    run(go())


def test_manage_session_open_carries_the_emulation_through(fixture_site):
    async def go():
        opened = await lite.manage_session(action="open", lane="A",
                                           locale="de-DE",
                                           timezone="Europe/Berlin")
        assert opened["emulation"]["locale"] == "de-DE"
        assert opened["emulation"]["applied_at"] == "open"
        return MANAGER.session(opened["session"])
    run(go())


# ------------------------------------------------------ 3. paginate-until


def test_read_pages_walks_a_rel_next_chain_to_its_honest_end(fixture_site):
    async def go():
        session, page = await _open(fixture_site, "/series/1")
        got = await extract.read_pages(page=page, max_pages=10)
        assert got["pages_read"] == 3
        assert [u.rsplit("/", 1)[1] for u in got["urls"]] == ["1", "2", "3"]
        assert got["stopped"]["reason"] == "end"
        # Every page is labeled with the URL it came from, in its own
        # nonce-carrying envelope.
        for entry, url in zip(got["pages"], got["urls"]):
            assert entry["url"] == url
            assert entry["page_data"]["nonce"] in entry["text"]
            assert url in entry["page_data"]["label"]
        assert "Part 2" in got["pages"][1]["text"]
        return session
    run(go())


def test_read_pages_stops_at_the_page_cap_and_says_where_to_resume(
        fixture_site):
    async def go():
        session, page = await _open(fixture_site, "/series/1")
        got = await extract.read_pages(page=page, max_pages=2)
        assert got["pages_read"] == 2
        assert got["stopped"]["reason"] == "page-cap"
        assert "/series/2" in got["resume"]
        return session
    run(go())


def test_read_pages_stops_at_the_character_budget(fixture_site):
    async def go():
        session, page = await _open(fixture_site, "/series/1")
        got = await extract.read_pages(page=page, max_pages=10,
                                       budget_chars=100)
        assert got["pages_read"] == 1
        assert got["stopped"]["reason"] == "char-budget"
        return session
    run(go())


def test_read_pages_names_a_loop_rather_than_circling(fixture_site):
    async def go():
        session, page = await _open(fixture_site, "/loop/a")
        got = await extract.read_pages(page=page, max_pages=10)
        assert got["pages_read"] == 2
        assert got["stopped"]["reason"] == "loop"
        assert "/loop/a" in got["stopped"]["detail"]
        return session
    run(go())


def test_read_pages_charges_the_navigation_budget_per_hop(fixture_site):
    """A walk is not a way around a budget: each hop goes through the same
    policy ladder a manual navigate would."""
    async def go():
        session, page = await _open(fixture_site, "/series/1")
        before = session.counters["navigations"]
        await extract.read_pages(page=page, max_pages=10)
        assert session.counters["navigations"] == before + 2
        budget = await lite.manage_session(action="budget",
                                           session=session.session_id)
        assert budget["enforced"]["counters"]["navigations"] >= 3
        return session
    run(go())


def test_read_pages_stops_on_a_resource_it_cannot_read(fixture_site):
    async def go():
        session, page = await _open(fixture_site, "/pixel.png")
        got = await extract.read_pages(page=page)
        assert got["pages_read"] == 0
        assert got["stopped"]["reason"] == "unreadable-resource"
        assert "download" in got["stopped"]["route"]
        return session
    run(go())


# ------------------------------------------------------------ 4. clipboard


def test_the_clipboard_round_trips_and_arrives_labeled(fixture_site):
    """127.0.0.1 counts as a secure context, so the clipboard API is
    available exactly as it would be on an https site."""
    async def go():
        session, page = await _open(fixture_site, "/clipboard")
        wrote = await files.manage_clipboard(page=page, action="write",
                                             text="hello from the test")
        assert wrote["chars_written"] == 19
        got = await files.manage_clipboard(page=page, action="read")
        assert "hello from the test" in got["text"]
        # Provenance, not censorship: the text is byte-identical inside the
        # envelope and the label states who could have authored it.
        from kitchensink4web import pagedata
        assert pagedata.unwrap(got["text"]) == "hello from the test"
        assert got["page_data"]["nonce"] in got["text"]
        assert "clipboard" in got["provenance"]
        assert got["chars"]["clipped"] is False
        return session
    run(go())


def test_a_page_written_clipboard_reads_back_as_page_authored(fixture_site):
    """The provenance claim, demonstrated: a copy button decides what lands
    on the clipboard, so a later read hands the model text the PAGE wrote.
    The write call first is what grants the page its clipboard-write
    permission; the read grants its own."""
    async def go():
        session, page = await _open(fixture_site, "/clipboard")
        await files.manage_clipboard(page=page, action="write", text="seed")
        await lite.click(page=page, location={"css": "#copy"})
        got = await files.manage_clipboard(page=page, action="read")
        assert "copied by the page" in got["text"]
        assert "the page" in got["provenance"]
        return session
    run(go())
