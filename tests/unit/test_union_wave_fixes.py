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


# ------------------------------------------- class 6: secrets never on disk


def test_a_credential_argument_never_lands_in_the_audit_file(tmp_path,
                                                             monkeypatch):
    """The credential-on-disk defect (dream-boundary review, 2026-09-07).

    `record()` scrubs its entry against the vault and the vault only holds
    what something called `observe` on; NOTHING on the tool-call path ever
    did. `server._wrap` records `args=kwargs` for every successful call, so
    a bearer token handed to
    `set_routing(action='headers', headers={'Authorization': 'Bearer ...'})`
    was written verbatim into `audit-<pid>.jsonl`.

    Pinned as the CLASS: any tool argument whose key is credential-shaped,
    at any nesting depth, must be vaulted before the record is built."""
    import json
    from kitchensink4web.policy import audit, credentials

    token = "Bearer uw-secret-9f3c2b71d4e6a8c05127bd3e4f6a9b0c"
    api = "uw-apikey-51ff90aa2be34c7d"
    credentials.VAULT.clear()
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    log = audit.AuditLog()
    log.record("set_routing", "ok", args={
        "action": "headers",
        "headers": {"Authorization": token, "X-Api-Key": api,
                    "Accept": "text/html"},
    })
    written = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (tmp_path / "audit").glob("audit-*.jsonl"))
    assert written, "the audit file was never written"
    assert token not in written, "a bearer token reached the audit file"
    assert api not in written, "an api key reached the audit file"
    assert "text/html" in written, "the scrub ate an ordinary header value"
    payload = json.loads(written.strip().splitlines()[-1])
    assert payload["tool"] == "set_routing"
    credentials.VAULT.clear()


def test_the_scrub_runs_before_the_clip():
    """A 200-character clip applied FIRST leaves a prefix the vault's
    substring match no longer recognizes, so a long secret sails past the
    scrub in pieces."""
    from kitchensink4web.policy import audit, credentials
    long_token = "uw-" + ("a1b2c3d4" * 40)          # 323 chars
    credentials.VAULT.clear()
    credentials.VAULT.observe(long_token)
    try:
        out = audit.summarize_args({"authorization": long_token})
        assert long_token[:100] not in out["authorization"]
    finally:
        credentials.VAULT.clear()


def test_preference_shaped_arguments_are_not_vaulted():
    """The guard on the guard: the 2026-09-05 over-redaction lesson holds.
    A five-character `light` in the vault garbles every read that quotes
    it, so the argument classifier reuses the cookie calibration."""
    from kitchensink4web.policy import audit, credentials
    credentials.VAULT.clear()
    audit.observe_secret_args({"theme": "light", "locale": "ko-KR",
                               "viewport": "390x844"})
    assert len(credentials.VAULT) == 0
    credentials.VAULT.clear()


# ------------------------------------------- class 7: the security surface


def test_wait_for_js_is_gated_like_evaluate_script():
    """IG-01, HIGH. `wait_for(condition='js')` reached `page.evaluate` in
    the precheck and `page.wait_for_function` in the wait with NO
    `_policy.approve` call anywhere in the tool, so none of the seven ladder
    checks ran. Under the SHIPPED read-only default one predicate changed
    the title, inserted a DOM node, wrote localStorage, wrote a cookie, and
    fetched an origin the deny list refuses at the front door."""
    import inspect
    from kitchensink4web.ops import lite
    source = inspect.getsource(lite.wait_for)
    assert 'action_class="evaluate_script"' in source
    approve = source.index("_policy.approve")
    js_branch = source.index('if cond == "js"')
    assert js_branch < approve, "the gate does not run on the js branch"


def test_wait_for_no_longer_claims_the_read_only_hint():
    """The metadata half of IG-01: `readOnlyHint: true` is a static claim
    about the TOOL, and a tool that can carry an evaluator in one of its
    arguments cannot make it."""
    from kitchensink4web.policy import readonly
    assert readonly.read_only_hint("wait_for") is False
    assert "wait_for" not in readonly.GENUINELY_READ_ONLY


def test_the_origin_policy_reaches_every_content_surface():
    """IG-02. The origin twin of the wall gate was at the read doors and
    the act doors and nowhere else, so on a document no door ruled on
    `find_elements` returned the policed origin's element inventory,
    `take_screenshot` returned its pixels, `export_pdf` and `save_page`
    wrote it to disk, and `manage_storage` listed its localStorage keys —
    and every one of them left the browser sitting on it."""
    import inspect
    from kitchensink4web.ops import capture, lite, storage
    for module, name in ((lite, "find_elements"), (lite, "scroll"),
                         (capture, "take_screenshot"),
                         (capture, "export_pdf"), (capture, "save_page"),
                         (storage, "manage_storage")):
        source = inspect.getsource(getattr(module, name))
        assert "_ensure_vetted" in source, f"{name} still skips the check"


def test_the_diagnostics_pack_envelopes_its_page_prose():
    """IG-03. `console.error(...)` and a thrown `Error` are page-authored
    free text — instruction-shaped prose, not the keyed cells DESIGN 5.1
    ruled data-shaped — and the pack was in neither of that ruling's lists.
    Both payloads also carried the session id and no url at all, while the
    recorder attaches at SESSION OPEN and keeps a session-wide store."""
    import inspect
    from kitchensink4web.ops import diag
    for name in ("list_console", "get_page_errors"):
        source = inspect.getsource(getattr(diag, name))
        assert "_pagedata.wrap" in source, f"{name} ships raw page prose"
        assert '"page_data"' in source, f"{name} has no provenance note"


def test_a_workflow_cannot_smuggle_a_js_predicate_through_replay():
    """IG-01, the defence-in-depth half. `save_workflow` refuses to RECORD
    a js predicate on the ground that "a workflow must never smuggle
    evaluate-shaped work past the gate that names it", and `_run_step`
    forwarded `condition` and `value` with no check at all."""
    import inspect
    from kitchensink4web.ops import workflows
    source = inspect.getsource(workflows._run_step)
    assert '"js"' in source, "the replay side still forwards a js predicate"


# ------------------------------ class 8: no confident wrong extraction


def test_extract_fields_partial_needs_both_guards():
    """The extract_fields defect (dream-extraction review, 2026-09-07).

    `_norm` strips everything non-alphanumeric, so a source key of `"t)"`
    normalizes to `"t"`, and the length guard was on the NEEDLE only. One
    character is a substring of almost every field description, so on the
    frozen Wikipedia Versailles page the field `price` with the hint "the
    current price" matched the key `"t)"` and confidently returned
    "destroyers" at `match: partial` — and returned the same value for
    `published`. Two confident wrong answers from a shipped read tool."""
    from kitchensink4web.ops.extract import _norm, _partial_matches
    by_norm = {_norm("t)"): {"key": "t)", "value": "destroyers",
                             "by": "table-row"},
               _norm("Signed"): {"key": "Signed", "value": "28 June 1919",
                                 "by": "table-row"}}
    assert _partial_matches(_norm("the current price"), by_norm) == []
    assert _partial_matches(_norm("published"), by_norm) == []
    assert _partial_matches(_norm("price"), by_norm) == []


def test_a_real_partial_still_matches():
    """The guard on the guard: the floor must not kill the feature."""
    from kitchensink4web.ops.extract import _norm, _partial_matches
    by_norm = {_norm("priceCurrency"): {"key": "priceCurrency",
                                        "value": "USD", "by": "json-ld"},
               _norm("offers_price"): {"key": "offers_price",
                                       "value": "49.99", "by": "json-ld"}}
    got = _partial_matches(_norm("price"), by_norm)
    assert got, "a genuine substring match was refused"
    # offers_price is the better cover (5/11 vs 5/13), so it ranks first
    # and the ranking is deterministic rather than dict-ordered.
    assert got[0][3]["key"] == "offers_price"


def test_a_short_source_key_still_matches_exactly():
    """`sku`, `url`, and `id` are below the partial floor and are still
    reachable, because an EXACT match needs no guard."""
    from kitchensink4web.ops.extract import _norm
    by_norm = {_norm("sku"): {"key": "sku", "value": "A-1"}}
    assert _norm("SKU") in by_norm


def test_the_partial_ranking_is_deterministic():
    """The old `next(...)` returned whichever key the PAGE happened to emit
    first, so a wrong answer was not even reproducible."""
    from kitchensink4web.ops.extract import _norm, _partial_matches
    rows = {"key": "x", "value": "v", "by": "meta"}
    a = {_norm("published_date"): {**rows, "key": "published_date"},
         _norm("date_published"): {**rows, "key": "date_published"}}
    b = dict(reversed(list(a.items())))
    assert [r[2] for r in _partial_matches(_norm("published"), a)] == \
           [r[2] for r in _partial_matches(_norm("published"), b)]


# --------------------------- class 9: no inert defense reads as a live one


def test_no_automatic_park_or_recycle_and_the_surface_says_so():
    """endurance F3. `park_idle` was implemented, complete, and had NO
    CALLER anywhere in the shipped tree, while the status payload reported
    `idle_park_s` and `idle_recycle_s` inside the same hygiene block as the
    job object and the startup reaper, both of which really do act on their
    own. A session left alone for 6.7x the recycle bound still held five
    browser processes and about 500 MB.

    Closed by REMOVING the claim rather than arming the mechanism: an
    automatic recycle closes a session out from under a caller, and with no
    session tombstone the next call answers "no session 's1'", which is
    indistinguishable from a close the caller made itself."""
    import inspect
    from kitchensink4web.engine import session as session_mod
    from kitchensink4web.ops import lite

    source = inspect.getsource(session_mod)
    calls = [line for line in source.splitlines()
             if "park_idle(" in line and "def park_idle" not in line]
    assert not calls, f"park_idle has a caller again: {calls}"

    status = inspect.getsource(lite.manage_session)
    assert '"idle_advisory"' in status, "the bounds are unlabelled again"
    assert '"automatic_action": "none"' in status
    block = status[status.index('"hygiene": {"job_object": '
                                '_session.hygiene.JOB.status,\n'
                                '                        "startup_reap"'):]
    assert "idle_park_s" not in block[:200], (
        "the idle bounds are back inside the hygiene block, beside two "
        "defenses that really do act")


def test_park_idle_invalidates_what_it_destroys():
    """The latent half: `park_idle` navigated to about:blank without
    calling `invalidate_page`, so a ref minted before the park survived it
    and resolved against a blank document. Never observed in the wild only
    because nothing ever called the method."""
    import inspect
    from kitchensink4web.engine import session as session_mod
    source = inspect.getsource(session_mod.SessionManager.park_idle)
    assert "invalidate_page" in source
    assert source.index("invalidate_page") < source.index("PARKED_URL")


# ---------------------------- class 10: bounds, enums, and honest counts


def test_every_tool_call_is_bounded():
    """chaos L-01/L-02. `session.with_timeout` existed and `navigate` used
    it; the read, act, and capture paths did not. Against a SUSPENDED
    browser `navigate(timeout_ms=8000)` returned honestly at 8.01 s while
    `get_page_view` ran past 120 s, `take_screenshot` past 120 s, and
    `click(timeout_ms=6000)` past 120 s with its EXPLICIT argument ignored,
    twenty times over. `get_text` and `get_page_view` take no `timeout_ms`
    at all, so a caller could not even ask for a bound."""
    import asyncio
    from kitchensink4web import server

    async def forever():
        await asyncio.sleep(30)

    forever.__name__ = "get_page_view"

    async def drive():
        with pytest.raises(errors.Timeout) as caught:
            await server._bounded(forever, (), {})
        return caught.value

    old = server.TOOL_CEILING_MS
    server.TOOL_CEILING_MS = 200
    try:
        exc = asyncio.run(drive())
    finally:
        server.TOOL_CEILING_MS = old
    assert "did not return within 200 ms" in str(exc)
    assert "manage_session" in str(exc)


def test_an_explicit_caller_timeout_widens_the_ceiling():
    """The ceiling is a BACKSTOP and must never fire before the tool's own
    honest timeout does, or a caller asking for a long wait would get the
    wrong message about it."""
    from kitchensink4web import server

    def click():
        pass
    click.__name__ = "click"
    assert server._ceiling_ms(click, {"timeout_ms": 300000}) \
        >= 300000 + server.TOOL_CEILING_SLACK_MS
    assert server._ceiling_ms(click, {}) == server.TOOL_CEILING_MS


def test_enum_arguments_normalize_the_same_way_everywhere():
    """fuzzer class 9. `manage_session` accepted "OPEN", "open " and
    "opeN" while `manage_storage` refused "LOCAL", so case and whitespace
    tolerance was per-tool rather than a property of the surface. And
    `manage_session(action="")` PERFORMED `status` while `action=" "`
    refused, though both normalize to the same empty string."""
    from kitchensink4web.ops import common
    allowed = ("open", "close", "status")
    for spelling in ("OPEN", "open ", " opeN", "Open"):
        assert common.enum_arg(spelling, allowed, default="status",
                               tool="t") == "open"
    assert common.enum_arg("", allowed, default="status", tool="t") \
        == common.enum_arg("  ", allowed, default="status", tool="t") \
        == common.enum_arg(None, allowed, default="status", tool="t")


def test_an_unknown_enum_quotes_what_the_caller_sent():
    """The refusal quoted the value AFTER stripping, so sending a single
    space came back as "unknown manage_session action ''" and misreported
    what the call contained."""
    from kitchensink4web.ops import common
    with pytest.raises(errors.BadParams) as caught:
        common.enum_arg(" NOPE ", ("open", "close"), default="open",
                        tool="manage_session")
    assert "' NOPE '" in str(caught.value)


def test_a_degenerate_count_refuses_instead_of_being_clamped_up():
    """fuzzer class 8. `get_links(limit=0)` and `limit=-1` both returned
    ONE link, because every paging site wrote `max(1, int(limit))`.
    Clamping UP answers a caller with something it did not ask for."""
    from kitchensink4web.ops import common
    for bad in (0, -1, -100):
        with pytest.raises(errors.RangeOutOfBounds):
            common.count_arg(bad, name="limit", tool="get_links", default=40)
    assert common.count_arg(5, name="limit", tool="get_links",
                            default=40) == 5


def test_both_viewport_spellings_validate_the_same_way():
    """fuzzer class 8. `viewport="0x0"` and `"0x900"` OPENED a session with
    a zero-pixel viewport and returned ok, while the dict spelling of the
    same values refused: two spellings of one parameter validating
    differently. Everything downstream is meaningless on a zero-pixel
    viewport."""
    from kitchensink4web.engine import lanes
    for spelling in ("0x0", "0x900", {"width": 0, "height": 0},
                     {"width": 0, "height": 900}):
        with pytest.raises(errors.BadParams):
            lanes.parse_viewport(spelling)
    assert lanes.parse_viewport("390x844") == {"width": 390, "height": 844}
    assert lanes.parse_viewport({"width": 1, "height": 1}) \
        == {"width": 1, "height": 1}


def test_a_mock_status_that_is_not_a_status_refuses():
    """fuzzer class 8. -1, 0, 99, 600 and 2147483648 were stored verbatim
    with ok:true and echoed back in `routing.routes`, so the caller held a
    receipt for a mock the browser will never serve."""
    import inspect
    from kitchensink4web.ops import net
    source = inspect.getsource(net.set_routing)
    assert "100 <= code <= 599" in source


def test_an_ignored_preset_argument_refuses():
    """Desktop Low-21. `preset` belongs to action='throttle' alone, and
    passing it with any other action was silently ignored: the field
    tester asked for preset='analytics', got ok, and watched analytics
    requests sail through."""
    import inspect
    from kitchensink4web.ops import net
    source = inspect.getsource(net.set_routing)
    # `strip_params` joined the preset-taking actions on 2026-09-07 with its
    # curated 'tracking' list, and it has its own unknown-preset refusal;
    # every OTHER action still refuses a preset rather than ignoring it.
    assert ('preset is not None and action not in ("throttle", '
            '"strip_params")') in source
    assert "block_ads" in source


def test_a_write_receipt_is_checked_against_the_field():
    """concurrency C-3. `type_text` read the field back and never COMPARED
    the reading to what it was asked to write, so with `clear_first` on,
    four concurrent calls all returned ok and all four reported
    `value: 'value3'`: three writes silently lost under a success
    receipt."""
    from kitchensink4web.ops import lite
    assert lite._write_mismatch("alpha", "alpha", True) is None
    assert lite._write_mismatch("alpha", "gamma", True)
    # With clear_first off the field legitimately holds more than this
    # call typed, so only containment is checkable.
    assert lite._write_mismatch("alpha", "betaalpha", False) is None
    assert lite._write_mismatch("alpha", "beta", False)


def test_writes_to_one_page_are_serialized():
    """concurrency C-3. Nothing serialized writes to a page or an element:
    `SessionManager._lock` guards session open and close and nothing else,
    so four concurrent `type_text` calls interleaved at the KEYSTROKE level
    and left a field holding a shuffle of all four strings while all four
    returned ok."""
    import inspect
    from kitchensink4web.engine import session as session_mod
    from kitchensink4web.ops import lite
    assert hasattr(session_mod.PageHandle, "write_lock")
    for fn in (lite.type_text, lite.fill_form):
        assert "write_lock()" in inspect.getsource(fn), fn.__name__


def test_a_navigate_that_becomes_a_download_names_the_download_route():
    """Desktop High-6. A direct file URL makes the browser start a download
    instead of rendering; `goto` rejected with "Download is starting",
    which shipped as BAD_PARAMS, and the download was lost because nothing
    had armed a listener."""
    import inspect
    from kitchensink4web.ops import lite
    source = inspect.getsource(lite.navigate)
    assert "download is starting" in source
    assert "action='goto'" in source


def test_a_session_closed_under_a_navigation_is_a_conflict():
    """concurrency C-5. `manage_session(close)` racing an in-flight
    navigate produced BAD_PARAMS with the driver's raw call log in the
    message and a hint about location objects. The sibling
    close-during-READ race already answered CONFLICT; this was the fourth
    of four races disagreeing with the other three."""
    import inspect
    from kitchensink4web.ops import lite
    source = inspect.getsource(lite._raise_if_unreachable)
    assert "_session_is_gone" in source
    assert source.index("_session_is_gone") < source.index("_NET_CAUSES")


def test_the_redaction_vault_does_not_eat_common_words():
    """Desktop High-4, verified rather than re-fixed: the length floor, the
    non-security exclusion list, and token-boundary matching for short
    values all landed in an earlier wave. The author's own username
    redacted from every GitHub URL is the acceptance test."""
    from kitchensink4web.policy import credentials
    credentials.VAULT.clear()
    try:
        credentials.VAULT.observe_cookie(
            {"name": "preferred_color_mode", "value": "light"})
        credentials.VAULT.observe_cookie(
            {"name": "dotcom_user", "value": "nometalalchemist"})
        text = ("Community highlights on "
                "https://github.com/nometalalchemist/web-mcp in light mode")
        assert credentials.redactor(text) == text
    finally:
        credentials.VAULT.clear()
