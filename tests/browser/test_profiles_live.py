"""Site profiles against a real page: the annotate-never-refuse contract.

The unit battery proves the loader is total. These prove the other half:
that a matching profile shows up as a NOTE on a live read, that its
signature never turns a 200 into a refusal, and that a community-authored
note arrives labeled as somebody else's words rather than the server's.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kitchensink4web import packs, profiles
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import extract as _extract
from kitchensink4web.ops import lite
from kitchensink4web.policy import readonly

pytestmark = pytest.mark.browser


@pytest.fixture
def local_profiles(tmp_path):
    """Install a profile set built from files in a temp directory."""
    d = tmp_path / "profiles"
    d.mkdir()

    def install(name: str, doc: dict):
        (d / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
        pset = profiles.load_profiles(extra_dirs=[str(d)])
        profiles.install(pset)
        return pset

    before = profiles.current()
    yield install
    profiles.install(before)


@pytest.fixture(autouse=True)
def loaded_packs(monkeypatch):
    monkeypatch.setattr(packs, "_LOADED",
                        set(packs.PACK_SUMMARIES), raising=False)
    readonly.apply(False)
    yield
    readonly.apply(False)


def _run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()
    return asyncio.run(main())


async def _open(base, path):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    page = session.focused
    await lite.navigate(page=page, url=f"{base}{path}")
    return session, page


def test_a_matching_profile_annotates_a_navigate(fixture_site,
                                                 local_profiles):
    local_profiles("loopback", {
        "format": 1, "profile": "loopback",
        "match": {"hosts": ["127.0.0.1"]},
        "title": "The local fixture site",
        "notes": ["a note from a local profile"],
        "extract": {"title": "the page heading"},
    })

    async def go():
        _sess, page = await _open(fixture_site, "/")
        out = await lite.navigate(page=page, url=f"{fixture_site}/form")
        assert out["profile"]["slug"] == "loopback"
        assert out["profile"]["source"] == "local"
        # A LOCAL profile's prose is not the server's voice.
        blob = json.dumps(out["profile"])
        assert "KS4WEB-PAGE-DATA" in blob
        assert "a note from a local profile" in blob
        assert out["profile"]["title"] == "loopback"

    _run(go())


def test_an_access_signature_never_refuses_a_200(fixture_site,
                                                 local_profiles):
    """The contract that matters most: a profile annotates, it does not
    gate. The signature below matches the fixture index page's own text."""
    local_profiles("loopback", {
        "format": 1, "profile": "loopback",
        "match": {"hosts": ["127.0.0.1"]},
        "access": [{"kind": "paywall",
                    "when": {"status": [200], "text": "form fixture"},
                    "evidence": "a deliberately over-broad matcher"}],
    })

    async def go():
        _sess, page = await _open(fixture_site, "/")
        out = await lite.navigate(page=page, url=f"{fixture_site}/form")
        assert out["status"] == 200
        assert not out["verdict"]["wall"], out["verdict"]
        note = out["profile"].get("access_note")
        assert note is not None, out["profile"]
        assert "advisory" in note["confidence"]
        assert "code" not in note
        # And the read that follows is not gated either.
        text = await lite.get_text(page=page)
        assert text["text"]

    _run(go())


def test_extract_fields_takes_its_schema_from_a_profile(
        fixture_site, local_profiles):
    local_profiles("loopback", {
        "format": 1, "profile": "loopback",
        "match": {"hosts": ["127.0.0.1"]},
        "extract": {"title": "the page heading",
                    "description": "the page summary"},
    })

    async def go():
        _sess, page = await _open(fixture_site, "/")
        filled = await _extract.extract_fields(page=page)
        assert filled["accounting"]["schema_source"] == "profile:loopback"
        assert set(filled["fields"]) == {"title", "description"}
        # A caller's own schema wins outright and is never merged.
        mine = await _extract.extract_fields(page=page, fields=["author"])
        assert set(mine["fields"]) == {"author"}
        assert mine["accounting"]["schema_source"] == "caller"

    _run(go())


def test_no_profile_means_no_block(fixture_site, local_profiles):
    local_profiles("elsewhere", {
        "format": 1, "profile": "elsewhere",
        "match": {"hosts": ["nothing.example"]}})

    async def go():
        _sess, page = await _open(fixture_site, "/")
        out = await lite.navigate(page=page, url=f"{fixture_site}/form")
        assert "profile" not in out

    _run(go())


def test_manage_session_profiles_needs_no_browser():
    """A user debugging a profile file must be able to ask what loaded
    before anything is open."""
    out = _run(lite.manage_session(action="profiles"))
    assert "counts" in out and "problems" in out
    assert "data" in out["note"].lower()
