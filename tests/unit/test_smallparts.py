"""The small-parts wave, in the parts that need no browser.

Five features and one correction ship together here, and each one has a
property worth pinning without a driver in the loop:

1. **PDF and blob escape.** The classifier is a pure function of a probe
   dict, so every media type, every URL scheme, and the wording of the
   refusal are testable without asking a browser to render a PDF. The one
   thing that must never regress is the blob branch: it may not offer a
   re-fetch route, because a blob URL names memory inside a page and no
   re-request can reach it.
2. **Context emulation at open.** Device presets, viewport spellings, and
   the loud refusals: an unknown preset is an error rather than the desktop
   default, and a mobile preset on Firefox names the engine that can do it.
3. **Per-site workflow lookup.** Subdomain matching goes one way only.
4. **Clipboard.** Classified as ACTING, so read-only hides it.
5. **Paginate-until.** Registered as a navigating read, so read-only keeps
   it and the genuinely-read-only hint does not claim it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kitchensink4web import envelope, packs
from kitchensink4web.engine import lanes
from kitchensink4web.errors import BadParams, LaneUnsupported
from kitchensink4web.ops import resource, workflows
from kitchensink4web.policy import readonly

# ------------------------------------------------------- 1. the escape hatch


def probe(content_type="text/html", url="https://example.com/a",
          embedded=(), pdf_js=False):
    return {"content_type": content_type, "url": url,
            "embedded_types": list(embedded), "pdf_js_viewer": pdf_js}


def test_an_ordinary_html_page_classifies_as_nothing():
    """The common case pays a dict lookup and moves on. A classifier that
    intercepted normal pages would break every read in the product."""
    assert resource.classify(probe()) is None
    assert resource.classify(probe("text/html; charset=utf-8")) is None
    assert resource.classify(probe("application/xhtml+xml")) is None


@pytest.mark.parametrize("ctype", ["application/pdf", "APPLICATION/PDF",
                                   "application/pdf; charset=binary"])
def test_a_pdf_document_is_recognized_by_its_own_content_type(ctype):
    info = resource.classify(probe(ctype, "https://x.test/report.pdf"))
    assert info["kind"] == "pdf"
    assert info["filename"] == "report.pdf"
    assert info["readable_as_text"] is False


def test_a_chromium_pdf_embed_and_a_firefox_pdfjs_shell_both_count():
    """Two engines, two shells, one honest verdict. Chromium hands the
    document to a plugin embed; Firefox swaps in the pdf.js viewer, whose
    document is HTML, so the content type alone would miss it."""
    assert resource.classify(
        probe("text/html", embedded=["application/pdf"]))["kind"] == "pdf"
    assert resource.classify(
        probe("text/html", pdf_js=True))["kind"] == "pdf"


def test_images_and_archives_are_binary_and_text_is_not():
    assert resource.classify(probe("image/png"))["kind"] == "binary"
    assert resource.classify(probe("application/zip"))["kind"] == "binary"
    assert resource.classify(
        probe("application/vnd.openxmlformats-officedocument.spreadsheetml."
              "sheet"))["kind"] == "binary"
    assert resource.classify(probe("text/plain")) is None
    assert resource.classify(probe("application/json")) is None


def test_a_blob_url_never_gets_offered_a_refetch_route():
    """The property this whole module exists to keep honest. A `blob:` URL
    names data held in the page, so no client can re-request it, and a
    route that told the caller to fetch it would be a promise the server
    cannot keep."""
    info = resource.classify(
        probe("application/pdf", "blob:https://x.test/9f3e-uuid"))
    assert info["page_local"] is True
    route = resource.escape_route(info)
    assert "action=\"fetch\"" not in route and "action='fetch'" not in route
    assert "page-local" in route
    assert "action=\"click\"" in route


def test_an_http_pdf_gets_the_fetch_route_naming_its_own_url():
    info = resource.classify(probe("application/pdf",
                                   "https://x.test/q1/report.pdf"))
    route = resource.escape_route(info)
    assert "https://x.test/q1/report.pdf" in route
    assert "report.pdf" in route


def test_the_read_refusal_is_typed_and_signposts_the_files_pack():
    info = resource.classify(probe("application/pdf",
                                   "https://x.test/report.pdf"))
    exc = resource.read_refusal(info, "get_text")
    assert envelope.classify(exc) == "UNSUPPORTED_CONTENT"
    assert envelope.refusal(exc)["error"]["code"] == "UNSUPPORTED_CONTENT"
    assert "get_text" in str(exc)
    # The pack signpost is declared by NAME, never scanned out of the text,
    # so the envelope can tell the caller which launch flag would load it.
    assert exc.hint_tools == ("download",)
    assert exc.detail["kind"] == "pdf"


def test_a_filename_comes_from_content_disposition_before_the_url():
    """A server that names the file wins over the path, which is what stops
    a download from landing as a bare UUID."""
    assert resource.filename_for(
        "https://x.test/dl?id=99",
        'attachment; filename="Q1 report.pdf"') == "Q1 report.pdf"
    assert resource.filename_for(
        "https://x.test/dl",
        "attachment; filename*=UTF-8''Q1%20r%C3%A9sum%C3%A9.pdf"
    ) == "Q1 résumé.pdf"
    assert resource.filename_for("https://x.test/a/b/sheet.xlsx") \
        == "sheet.xlsx"
    assert resource.filename_for("blob:https://x.test/uuid") is None


def test_the_navigate_note_says_reads_will_refuse():
    note = resource.navigate_note(
        resource.classify(probe("application/pdf", "https://x.test/a.pdf")))
    assert note["readable"] is False
    assert "get_text" in note["why"]
    assert "download" in note["route"]


# --------------------------------------------- 2. emulation at session open


class _FakePlaywright:
    """Playwright's device table, in the shape the real one has: snake_case
    keys plus the `default_browser_type` field that
    launch_persistent_context does not accept."""

    devices = {
        "iPhone 15": {"user_agent": "Mozilla/5.0 (iPhone)",
                      "viewport": {"width": 393, "height": 852},
                      "device_scale_factor": 3, "is_mobile": True,
                      "has_touch": True, "default_browser_type": "webkit"},
        "Desktop Chrome": {"viewport": {"width": 1280, "height": 720},
                           "device_scale_factor": 1, "is_mobile": False,
                           "has_touch": False,
                           "default_browser_type": "chromium"},
    }


def chromium():
    return lanes.resolve(lane="A", engine="chromium")


def firefox():
    return lanes.resolve(lane="A", engine="firefox")


def test_no_emulation_asked_for_changes_no_default():
    kwargs, report = lanes.emulation_kwargs(chromium(), _FakePlaywright())
    assert kwargs == {} and report == {}
    launch = lanes.launch_kwargs(chromium(), "C:/tmp/profile", kwargs)
    assert launch["viewport"] == {"width": 1280, "height": 900}


def test_a_device_preset_is_applied_whole_minus_the_field_playwright_rejects():
    kwargs, report = lanes.emulation_kwargs(
        chromium(), _FakePlaywright(), device="iPhone 15")
    assert "default_browser_type" not in kwargs
    assert kwargs["is_mobile"] is True and kwargs["has_touch"] is True
    assert kwargs["viewport"] == {"width": 393, "height": 852}
    assert report["device"] == "iPhone 15"


def test_an_explicit_viewport_overrides_the_preset_rather_than_fighting_it():
    kwargs, report = lanes.emulation_kwargs(
        chromium(), _FakePlaywright(), device="iPhone 15",
        viewport="360x640")
    assert kwargs["viewport"] == {"width": 360, "height": 640}
    assert kwargs["is_mobile"] is True          # the rest of the preset holds
    assert report["viewport"] == {"width": 360, "height": 640}


def test_an_unknown_device_is_an_error_not_the_desktop_default():
    """The lane subsystem's founding rule, applied to one more argument:
    chrome-devtools-mcp #2530 silently downgrades a mistyped flag, and this
    refuses instead."""
    with pytest.raises(BadParams) as caught:
        lanes.emulation_kwargs(chromium(), _FakePlaywright(),
                               device="iphone fifteen")
    assert "iphone fifteen" in str(caught.value)
    assert "iPhone 15" in str(caught.value)     # the near match is offered


def test_a_mobile_preset_on_firefox_refuses_and_names_the_engine():
    with pytest.raises(LaneUnsupported) as caught:
        lanes.emulation_kwargs(firefox(), _FakePlaywright(),
                               device="iPhone 15")
    assert "is_mobile" in str(caught.value)
    assert "Chromium" in str(caught.value) and "WebKit" in str(caught.value)


def test_a_desktop_preset_on_firefox_is_fine():
    kwargs, _ = lanes.emulation_kwargs(firefox(), _FakePlaywright(),
                                       device="Desktop Chrome")
    assert kwargs["viewport"] == {"width": 1280, "height": 720}


@pytest.mark.parametrize("given,want", [
    ("390x844", {"width": 390, "height": 844}),
    ("1280 x 900", {"width": 1280, "height": 900}),
    ({"width": 800, "height": 600}, {"width": 800, "height": 600}),
])
def test_viewport_takes_both_spellings(given, want):
    assert lanes.parse_viewport(given) == want


@pytest.mark.parametrize("bad", ["wide", "800", "800x", {"width": 800}])
def test_a_viewport_that_is_not_a_size_refuses_rather_than_picking_one(bad):
    with pytest.raises(BadParams):
        lanes.parse_viewport(bad)


def test_locale_and_timezone_land_on_the_playwright_names():
    kwargs, report = lanes.emulation_kwargs(
        chromium(), _FakePlaywright(), locale="ko-KR",
        timezone="Asia/Seoul")
    assert kwargs == {"locale": "ko-KR", "timezone_id": "Asia/Seoul"}
    assert report == {"locale": "ko-KR", "timezone": "Asia/Seoul"}


@pytest.mark.parametrize("locale", ["", "korean (south korea)", "k" * 20])
def test_a_locale_that_is_not_a_tag_refuses(locale):
    with pytest.raises(BadParams):
        lanes.emulation_kwargs(chromium(), _FakePlaywright(), locale=locale)


def test_a_timezone_with_a_space_refuses_and_names_the_shape():
    with pytest.raises(BadParams) as caught:
        lanes.emulation_kwargs(chromium(), _FakePlaywright(),
                               timezone="Asia Seoul")
    assert "Asia/Seoul" in str(caught.value)


def test_every_emulation_option_is_a_playwright_native():
    """Nothing invented. Each key this route can set is an argument
    `launch_persistent_context` already takes, which is what keeps the
    feature a wiring job rather than a simulation."""
    kwargs, _ = lanes.emulation_kwargs(chromium(), _FakePlaywright(),
                                       device="iPhone 15", locale="de-DE",
                                       timezone="Europe/Berlin")
    assert set(kwargs) <= set(lanes.EMULATION_KEYS)


def test_the_emulate_tool_no_longer_promises_a_route_that_does_not_exist():
    """The correction the features audit filed (§3.6 item 2): `emulate`'s
    docstring told callers to reopen the session for locale and timezone
    when `manage_session(open)` took neither. It now names the arguments
    that exist."""
    from kitchensink4web.ops import capture, lite

    assert "reopen the session" not in capture.emulate.__doc__
    assert "manage_session" in capture.emulate.__doc__
    for arg in ("device", "viewport", "locale", "timezone"):
        assert arg in lite.manage_session.__doc__


# ----------------------------------------------- 3. per-site workflow lookup


@pytest.mark.parametrize("typed,host", [
    ("example.com", "example.com"),
    ("https://example.com/reports/2026", "example.com"),
    ("HTTPS://Example.COM", "example.com"),
    # The port used to ride along here and its one consumer, _origin_matches,
    # cut it off again. It comes off at the source since 2026-09-08, when the
    # two host extractors in workflows.py were merged onto urlparse: the
    # manual `split(':', 1)` that did the cutting turned an IPv6 literal into
    # the empty string.
    ("http://user:pw@example.com:8443/x", "example.com"),
    ("http://[::1]:8080/x", "::1"),
])
def test_for_origin_takes_a_host_or_any_url_on_it(typed, host):
    assert workflows._host_of(typed) == host


def test_a_subdomain_answers_for_its_parent_and_never_the_reverse():
    """`www.example.com` is what the recorder stored and `example.com` is
    what a caller standing on the page types, so the match has to widen in
    that direction. It must not widen the other way, or a lookup for one
    site would return flows recorded on a different one."""
    assert workflows._origin_matches("www.example.com", "example.com")
    assert workflows._origin_matches("example.com:8443", "example.com")
    assert not workflows._origin_matches("example.com", "www.example.com")
    assert not workflows._origin_matches("notexample.com", "example.com")
    assert not workflows._origin_matches("example.com.evil.test",
                                         "example.com")


def _write_workflow(tmp_path, name, origins):
    (tmp_path / f"{name}.json").write_text(json.dumps({
        "name": name, "created": "2026-09-06T00:00:00", "session": None,
        "origins": origins,
        "steps": [{"tool": "navigate", "args": {}, "url": "x"}]}),
        encoding="utf-8")


@pytest.fixture
def flow_dir(monkeypatch, tmp_path):
    from kitchensink4web.policy import audit

    monkeypatch.setattr(workflows, "_workflow_dir", lambda: tmp_path)
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    return tmp_path


def test_list_workflows_narrows_to_one_site_and_says_what_it_hid(flow_dir):
    _write_workflow(flow_dir, "invoices", ["billing.example.com"])
    _write_workflow(flow_dir, "elsewhere", ["other.test"])

    everything = asyncio.run(workflows.list_workflows())
    assert len(everything["workflows"]) == 2
    assert "filter" not in everything

    narrowed = asyncio.run(workflows.list_workflows(for_origin="example.com"))
    assert [w["name"] for w in narrowed["workflows"]] == ["invoices"]
    assert narrowed["filter"]["excluded"] == 1
    assert "call without for_origin" in narrowed["filter"]["note"]

    by_url = asyncio.run(workflows.list_workflows(
        for_origin="https://billing.example.com/invoices/new"))
    assert [w["name"] for w in by_url["workflows"]] == ["invoices"]


def test_a_for_origin_with_no_host_refuses(flow_dir):
    with pytest.raises(BadParams):
        asyncio.run(workflows.list_workflows(for_origin="///"))


def test_saving_a_flow_teaches_the_per_site_lookup(flow_dir):
    """Discoverability: the recorder already stores origins, so the moment a
    flow is saved is the moment to say it can be found by site."""
    from kitchensink4web.policy import audit

    audit.LOG.record(
        "navigate", "ok", args={}, url="https://shop.test/cart",
        replay={"tool": "navigate",
                "args": {"url": "https://shop.test/cart"}})
    saved = asyncio.run(workflows.save_workflow(name="checkout"))
    assert saved["origins"] == ["shop.test"]
    assert "for_origin='shop.test'" in saved["next"]


def test_a_missing_workflow_points_at_the_per_site_lookup(flow_dir):
    _write_workflow(flow_dir, "invoices", ["billing.example.com"])
    with pytest.raises(Exception) as caught:
        workflows._load("nothing-here")
    assert "for_origin" in str(caught.value)


# --------------------------------------------- 4 and 5. the two new tools


def test_the_two_new_tools_register_in_the_packs_that_own_them(launch):
    state = launch(cli_packs=packs.pack_names(), read_only=False)
    assert "manage_clipboard" in state["registered"]
    assert "read_pages" in state["registered"]
    assert packs.pack_of("manage_clipboard") == "files"
    assert packs.pack_of("read_pages") == "extract"


def test_clipboard_is_acting_classed_and_absent_under_read_only(launch):
    """Reading a clipboard needs a permission, reaches past the page, and can
    surface text the human never meant a site to see. A read-only mode that
    let a tool drain it would not be one."""
    assert readonly.is_mutating("manage_clipboard") is True
    assert readonly.read_only_hint("manage_clipboard") is False
    state = launch(cli_packs=packs.pack_names(), read_only="browse")
    assert "manage_clipboard" not in state["registered"]
    assert "manage_clipboard" in readonly.describe()["absent_tools"]


def test_paginate_until_survives_read_only_but_is_not_hinted_read_only(launch):
    """It follows the page's own links and navigates, exactly as `navigate`
    does, so it is permitted under `browse` and held to the allowlist under
    `strict`. It writes browser state, so the readOnlyHint stays false."""
    assert readonly.is_mutating("read_pages") is False
    assert readonly.read_only_hint("read_pages") is False
    state = launch(cli_packs=packs.pack_names(), read_only="browse")
    assert "read_pages" in state["registered"]


def test_the_new_tools_carry_descriptions_that_pass_the_house_rules(
        launch, live_tools):
    launch(cli_packs=packs.pack_names(), read_only=False)
    tools = live_tools()
    for name in ("manage_clipboard", "read_pages"):
        desc = tools[name].description or ""
        assert "—" not in desc
        assert len(desc) <= 2048
        assert "Returns" in desc


def test_the_download_tool_gained_fetch_without_losing_a_route(launch,
                                                              live_tools):
    launch(cli_packs=packs.pack_names(), read_only=False)
    schema = json.dumps(live_tools()["download"].parameters)
    assert "fetch" in (live_tools()["download"].description or "")
    assert "url" in schema
