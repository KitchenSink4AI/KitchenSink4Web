"""Union wave (2026-09-07) — the unit-level pins for the insane round.

Six breakers plus the author's Desktop field test, deduped into five
cross-breaker super-classes and a set of uniques. Every row here is
RED on `8ef2aba` and green after the wave; the live-browser half of the
same wave is in `tests/browser/test_union_wave_fixes.py`.

The classes pinned here:

1. BACKSTOP REFUSAL HONESTY — no raw driver or stdlib exception string is
   ever the whole message, and no infrastructure failure wears BAD_PARAMS
   (fuzzer class 1, chaos C-01/C-05/C-10/C-11/C-12, hostile H-01/H-02).
2. TRUTHFUL RECEIPTS — `saved_to` names where the bytes actually went, and
   a write that persisted nothing refuses (fuzzer class 4, chaos C-11).
3. COUNTERS AND BUDGETS — one writer per number, and no counter billed for
   work a later check refused (endurance F1/F2/F6, concurrency C-7).
4. LOOP DETECTION — a refusal may not assert something false about the call
   it refused (fuzzer class 5, concurrency C-6).
5. THE ENUM AND SCHEMA SURFACE — no advertised parameter that always
   refuses, no scaffold code in a shipped refusal, no two spellings of one
   parameter validating differently (fuzzer classes 6-9).
"""

from __future__ import annotations

import os

import pytest

from kitchensink4web import envelope, errors


# --------------------------------------------------------------- class 1


class _FakeDriverError(Exception):
    """Stands in for a Playwright error: the same shape, no import."""


def _refuse(exc: BaseException) -> dict:
    return envelope.refusal(exc)["error"]


@pytest.mark.parametrize("text", [
    "Page.goto: net::ERR_ABORTED at http://127.0.0.1:50921/hang",
    "Page.reload: Protocol error (Page.reload): Not attached to an active page",
    "Page.goto: NS_ERROR_NET_PARTIAL_TRANSFER",
    "BrowserContext.set_extra_http_headers: Protocol error "
    "(Network.setExtraHTTPHeaders): Invalid header name",
    "Page.evaluate: SecurityError: Failed to read the 'localStorage' property",
])
def test_no_driver_failure_is_ever_answered_bad_params(text):
    """chaos C-01, the structural half. `_NET_CAUSES` is an allowlist and
    everything it did not recognize fell through to the argument-blaming
    terminal return, so a browser that died mid-navigation was reported as
    a malformed URL nine runs in ten."""
    code = envelope.classify(_FakeDriverError(text))
    assert code != "BAD_PARAMS", f"{text!r} classified as BAD_PARAMS"


def test_a_dead_browser_is_its_own_code():
    """chaos C-02/C-04, endurance F7, Desktop Critical-1/High-5/Med-17."""
    exc = _FakeDriverError(
        "Page.goto: Target page, context or browser has been closed")
    assert envelope.classify(exc) == "SESSION_DEAD"
    err = _refuse(exc)
    assert "manage_session" in err["message"]
    assert "close" in err["message"]


def test_a_redirect_loop_blames_the_site_not_the_caller():
    """hostile H-01: the URL was well formed, there was no location object,
    and the site built the loop; the refusal sent the agent to fix
    arguments that were correct."""
    err = _refuse(_FakeDriverError(
        "Page.goto: net::ERR_TOO_MANY_REDIRECTS at http://x/redir/loop"))
    assert err["code"] == "NAVIGATION_FAILED"
    assert "location object" not in err["hint"]


def test_a_driver_dump_is_clipped_and_de_identified():
    """chaos C-12: a 2,368-character message carrying the whole
    chrome-headless-shell launch line, the local ms-playwright install
    path, and GPU crash lines with foreign PIDs, inside a refusal."""
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    raw = (
        "BrowserType.launch_persistent_context: Protocol error\n"
        "Call log:\n"
        f"  - <launching> {home}\\AppData\\Local\\ms-playwright\\"
        "chromium_headless_shell-1234\\chrome-headless-shell.exe "
        + ("--disable-field-trial-config " * 200)
        + "\nBrowser logs:\n[pid=9999] GPU crash")
    err = _refuse(_FakeDriverError(raw))
    assert len(err["message"]) < 600, "the driver dump still rides out"
    assert "Call log:" not in err["message"]
    assert "Browser logs:" not in err["message"]
    assert "--disable-field-trial-config" not in err["message"]
    if home:
        assert home not in err["message"], "local path disclosed in a refusal"


def test_scrub_keeps_a_short_driver_string_intact():
    """The guard on the guard: scrubbing must not eat an ordinary message."""
    assert envelope.scrub_driver_text("Page.goto: net::ERR_ABORTED at http://x") \
        == "Page.goto: net::ERR_ABORTED at http://x"


def test_a_bare_stdlib_message_is_never_the_whole_refusal():
    """fuzzer class 1d: `navigate(url="https://[")` shipped urllib's
    "Invalid IPv6 URL" and nothing else."""
    err = _refuse(OSError(13, "Permission denied", "C:\\x\\y.png"))
    assert err["code"] == "FILE_WRITE_FAILED"
    assert err["message"] != "[Errno 13] Permission denied: 'C:\\x\\y.png'"
    assert "location object" not in err["hint"]


def test_a_lone_surrogate_cannot_collapse_the_envelope():
    """fuzzer class 11: the refusal echoes its arguments, so an unpaired
    surrogate made the refusal itself unserializable and the caller got the
    framework's bare exception text instead of an envelope."""
    result = envelope.refuse(errors.BadParams("bad page \ud800 handle"))
    assert result["ok"] is False
    assert "\ud800" not in result["error"]["message"]


def test_a_raise_site_hint_wins_over_the_generic_one():
    """hostile H-02: the crashed-renderer message says "this handle is dead,
    open a NEW tab" and CONFLICT's own hint said "re-read to re-establish a
    baseline" directly underneath it."""
    exc = errors.Conflict("page p1 is dead")
    exc.hint = "open a new tab"
    assert _refuse(exc)["hint"] == "open a new tab"


def test_every_new_code_names_a_recovery():
    for code in ("SESSION_DEAD", "NAVIGATION_FAILED", "FILE_WRITE_FAILED",
                 "DRIVER_FAILURE"):
        assert code in envelope.CLOSED_CODES
        assert envelope.HINTS[code].strip()


# --------------------------------------------------------------- class 2


def test_a_device_name_refuses_instead_of_reporting_a_saved_file(tmp_path):
    """fuzzer class 4: `path='CON'` returned ok, `saved_to: "CON"`, and
    `bytes: 1188`, and nothing was persisted anywhere."""
    from kitchensink4web.ops import common
    for name in ("CON", "NUL", "nul.png"):
        with pytest.raises(errors.FileWriteFailed):
            common.write_text_file(name, "x", "save probe")


def test_a_stream_name_refuses(tmp_path):
    from kitchensink4web.ops import common
    with pytest.raises(errors.FileWriteFailed):
        common.write_text_file(str(tmp_path / "x.txt:stream"), "x", "save probe")


def test_shell_tokens_are_expanded_before_the_receipt(tmp_path, monkeypatch):
    """fuzzer class 4: `~/x.txt` created a literal directory named `~`,
    `%TEMP%/x.txt` one named `%TEMP%`, and a relative path was echoed
    unresolved while the file landed relative to a server CWD the caller
    cannot see."""
    from kitchensink4web.ops import common
    monkeypatch.setenv("UW_PROBE_DIR", str(tmp_path))
    where = common.write_text_file("%UW_PROBE_DIR%/probe.txt", "x", "save probe")
    assert where == str(tmp_path / "probe.txt")
    assert (tmp_path / "probe.txt").read_text() == "x"
    assert "%" not in where


def test_a_relative_path_is_reported_absolute(tmp_path, monkeypatch):
    from kitchensink4web.ops import common
    monkeypatch.chdir(tmp_path)
    where = common.write_text_file("probe2.txt", "x", "save probe")
    assert os.path.isabs(where)


def test_an_unwritable_target_refuses_with_a_typed_code(tmp_path):
    """chaos C-11: five tools answered BAD_PARAMS with a bare Errno 13."""
    from kitchensink4web.ops import common
    blocker = tmp_path / "in_the_way"
    blocker.mkdir()
    with pytest.raises(errors.FileWriteFailed) as caught:
        common.write_bytes_file(str(blocker), b"x", "save screenshot")
    err = _refuse(caught.value)
    assert err["code"] == "FILE_WRITE_FAILED"
    assert str(blocker) in err["message"]


# --------------------------------------------------------------- class 3


def test_a_refused_origin_does_not_bill_a_navigation():
    """endurance F6: `charge()` incremented the navigation counter and THEN
    checked the distinct-origins limit, so the ledger printed
    `navigations=31` for 30 navigations performed."""
    from kitchensink4web.policy import budgets
    book = budgets.BookKeeper() if hasattr(budgets, "BookKeeper") \
        else type(budgets.BOOK)()
    os.environ["KS4WEB_MAX_NEW_ORIGINS"] = "2"
    try:
        book.charge("sU", "navigations", origin="a.example")
        book.charge("sU", "navigations", origin="b.example")
        before = book.snapshot("sU")["counters"]["navigations"]
        with pytest.raises(errors.BudgetExhausted):
            book.charge("sU", "navigations", origin="c.example")
        after = book.snapshot("sU")["counters"]["navigations"]
        assert after == before, "a refused navigation was billed anyway"
    finally:
        os.environ.pop("KS4WEB_MAX_NEW_ORIGINS", None)


# --------------------------------------------------------------- class 4


def test_the_loop_fingerprint_carries_what_makes_a_call_distinct():
    """concurrency C-6 and fuzzer class 5. The loop signature is
    `(tool, target_fp, args_fp)` and `args_fp` is built from the dict each
    op hands `approve()`, so a value left out of that dict is a value two
    different calls share. Five `type_text` calls carrying five DIFFERENT
    strings tripped LOOP_DETECTED with "with identical arguments"; four
    `set_routing` mocks with four different statuses did the same; four
    `download` calls with four different paths did the same.

    Pinned at the dict literal because that is where the defect is: the
    behaviour pin (five distinct types in a row do not trip) is in the
    browser file, and this row is what fails first when somebody adds a
    parameter and forgets the fingerprint."""
    import inspect
    from kitchensink4web.ops import files as files_ops
    from kitchensink4web.ops import lite, net

    body = inspect.getsource(lite.type_text)
    approve = body[body.index('tool="type_text"'):]
    assert '"text"' in approve[:approve.index("summary=")], (
        "type_text's loop fingerprint still omits the text it types")

    body = inspect.getsource(net.set_routing)
    approve = body[body.index('tool="set_routing"'):]
    head = approve[:approve.index("summary=")]
    for key in ('"status"', '"body"', '"headers"', '"content_type"'):
        assert key in head, f"set_routing's loop fingerprint omits {key}"

    body = inspect.getsource(files_ops.download)
    assert body.count('"path": path') >= 2, (
        "download's loop fingerprint still omits the destination path")


def test_the_signature_really_separates_distinct_arguments():
    """The mechanism behind the pin above: distinct argument fingerprints
    must produce distinct signatures, so a repeat trip means a real repeat."""
    from kitchensink4web.policy import budgets
    book = type(budgets.BOOK)()
    for status in (599, 600, 601, 602, 603, 604):
        book.note_call("sL", "set_routing", None,
                       budgets.fingerprint({"action": "mock",
                                            "status": status}))
    one = budgets.fingerprint({"location": {"css": "#a"}, "text": "alpha"})
    two = budgets.fingerprint({"location": {"css": "#a"}, "text": "beta"})
    assert one != two


# --------------------------------------------------------------- class 5


def test_no_scaffold_code_can_ship():
    """fuzzer class 6: `envelope.py` states "Nothing outside this set may
    appear in a shipped refusal" and the Phase 9 gate asserts SCAFFOLD_CODES
    is empty; `get_page_view(cursor='c1')` reached NOT_IMPLEMENTED through a
    parameter documented in the published schema."""
    import inspect
    from kitchensink4web.ops import lite
    source = inspect.getsource(lite.get_page_view)
    assert "_stub(" not in source, (
        "get_page_view can still reach the NOT_IMPLEMENTED scaffold code")
    signature = inspect.signature(lite.get_page_view).parameters
    assert "cursor" not in signature, "the schema still advertises cursor"
    assert "include_hidden" not in signature, (
        "the schema still advertises a knob that always refuses")


def test_workflow_files_that_parse_but_are_not_workflows_refuse_cleanly():
    """chaos C-10: `'list' object has no attribute 'get'` shipped as
    BAD_PARAMS with a hint about location objects."""
    import json
    from kitchensink4web.ops import workflows
    directory = workflows._workflow_dir()
    path = directory / "uw-corrupt-probe.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    try:
        with pytest.raises(errors.ValidationFailed):
            workflows._load("uw-corrupt-probe")
    finally:
        path.unlink(missing_ok=True)


def test_one_corrupt_workflow_does_not_brick_the_listing():
    """chaos C-10, the serious half: one bad file took down enumeration of
    EVERY workflow, and the per-file `unreadable; re-save` fallback that
    exists for exactly this was guarded by the same two exceptions as the
    parse, so it never fired."""
    import asyncio
    import json
    from kitchensink4web.ops import workflows
    directory = workflows._workflow_dir()
    bad = directory / "uw-corrupt-probe.json"
    good = directory / "uw-good-probe.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    good.write_text(json.dumps(
        {"name": "uw-good-probe", "steps": [], "origins": []}),
        encoding="utf-8")
    try:
        out = asyncio.run(workflows.list_workflows())
        names = {row["name"] for row in out["workflows"]}
        assert "uw-good-probe" in names
        assert any(row.get("error") for row in out["workflows"]
                   if row["name"] == "uw-corrupt-probe")
    finally:
        bad.unlink(missing_ok=True)
        good.unlink(missing_ok=True)


def test_upload_file_checks_the_element_types_not_just_the_list():
    """fuzzer class 1b: the guard checked `not files or not isinstance(
    files, list)` and never the element types, so `files=[None]` reached
    `os.fspath` and came back as a raw TypeError string."""
    import asyncio
    from kitchensink4web.ops import files as files_ops
    for payload in ([None], [0], [[]], [{}], ["ok.txt", None], [""]):
        with pytest.raises(errors.BadParams):
            asyncio.run(files_ops.upload_file(
                page="p1", location={"css": "#f"}, files=payload))
