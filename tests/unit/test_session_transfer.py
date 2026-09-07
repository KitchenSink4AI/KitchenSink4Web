"""Session handle transfer (#15) and the session tombstone (defect D3).

The pins from the lifecycle spec §8.3 and §8.5, written RED against
`45fc986`. What they hold:

- the token is a bearer string and is treated like one everywhere it is
  stored or logged, and NOWHERE else: it is deliberately not vaulted,
  because the vault would mask it in the one payload that must show it
- every way an import can fail says WHICH way, and the specific answer is
  the whole feature (a stale handle today says only "no session 's1'")
- a closed session leaves a record of how it ended, and every stale-handle
  refusal in the server reads that record, not just import
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import pytest

from kitchensink4web import envelope, errors
from kitchensink4web.engine import handles as _handles
from kitchensink4web.engine import lanes as _lanes
from kitchensink4web.engine import session as _session
from kitchensink4web.ops import lite
from kitchensink4web.policy import audit as _audit

SPEC = _lanes.LaneSpec(lane="B", engine="firefox", channel="moz-firefox")


class _FakeJournal:
    """Enough journal for `browser_alive()` to answer 'cannot tell', which
    is what a session with no recorded PIDs honestly reports."""

    def __init__(self) -> None:
        self.pids: dict[int, int | None] = {}

    def survivors(self) -> list[int]:
        return []

    def close(self) -> None:
        pass


class _FakeContext:
    def __init__(self, cookies: int = 0) -> None:
        self._cookies = [{"name": f"c{i}", "value": "v"} for i in range(cookies)]

    async def cookies(self):
        return list(self._cookies)

    async def close(self):
        return None


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url


def _session_in(manager, sid: str, urls=("https://example.org/a",),
                role: str = "user", cookies: int = 0):
    sess = _session.Session(session_id=sid, spec=SPEC, role=role)
    sess.contexts["c1"] = _session.ContextHandle(
        label="c1", context=_FakeContext(cookies),
        profile_dir=f"C:/tmp/{sid}", journal=_FakeJournal(), spec=SPEC)
    for i, url in enumerate(urls, start=1):
        handle = f"{sid}p{i}"
        record = _session.PageHandle(handle=handle, page=_FakePage(url))
        record.last_nav_url = url
        sess.pages[handle] = record
        if sess.focused is None:
            sess.focused = handle
    manager.sessions[sid] = sess
    return sess


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A handle store on a scratch path, and the process manager cleared."""
    path = tmp_path / "handles.json"
    monkeypatch.setattr(_handles, "STORE", _handles.HandleStore(path))
    _session.MANAGER.sessions.clear()
    _session.MANAGER.tombstones.clear()
    yield _handles.STORE
    _session.MANAGER.sessions.clear()
    _session.MANAGER.tombstones.clear()


def _call(**kwargs) -> dict:
    return asyncio.run(lite.manage_session(**kwargs))


def _refuses(code: str, **kwargs) -> str:
    with pytest.raises(errors.WebMcpError) as caught:
        _call(**kwargs)
    assert envelope.classify(caught.value) == code, (
        f"expected {code}, got {envelope.classify(caught.value)}: "
        f"{caught.value}")
    return str(caught.value)


# ------------------------------------------------------------------- H-1

def test_h1_the_raw_token_is_never_on_disk(store):
    _session_in(_session.MANAGER, "s1")
    out = _call(action="export_handle", session="s1")
    token = out["token"]
    raw = store.path.read_bytes()
    assert token.encode() not in raw, (
        "the raw token is in handles.json; a leaked store would be replayable")
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert digest.encode() in raw, "the store does not hold the token's hash"


# ------------------------------------------------------------------- H-2

def test_h2_the_raw_token_is_never_in_the_audit_trail(store, tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(_audit, "STATE_DIR", tmp_path)
    _audit.LOG.reset()
    _session_in(_session.MANAGER, "s1")
    out = _call(action="export_handle", session="s1")
    token = out["token"]
    _audit.LOG.record("manage_session", "ok",
                      args={"action": "import_handle", "token": token})
    ring = json.dumps(_audit.LOG.read(limit=50)["records"])
    assert token not in ring, "the audit ring holds the raw token"
    on_disk = (tmp_path / "audit").glob("*.jsonl")
    for path in on_disk:
        assert token not in path.read_text(encoding="utf-8"), (
            f"{path.name} holds the raw token")
    assert hashlib.sha256(token.encode()).hexdigest()[:8] in ring, (
        "nothing correlatable survives, so two audit rows about one token "
        "cannot be tied together")


def test_h2b_a_denied_argument_does_not_change_other_tools(store, tmp_path,
                                                           monkeypatch):
    """D4-P. Denying `token` on manage_session must not touch anything else."""
    monkeypatch.setattr(_audit, "STATE_DIR", tmp_path)
    _audit.LOG.reset()
    _audit.LOG.record("navigate", "ok", args={"url": "https://example.org/x"})
    _audit.LOG.record("wait_for", "ok", args={"token": "not-a-handle-token"})
    rows = _audit.LOG.read(limit=10)["records"]
    assert rows[0]["args"]["url"] == "https://example.org/x"
    # `token` on another tool keeps whatever the pre-existing credential
    # path decided for it; what must NOT happen is the handle denylist
    # reaching a tool that does not own the argument.
    assert not str(rows[1]["args"]["token"]).startswith("<withheld"), (
        "the denylist is not scoped to the tool that owns the argument")


# ------------------------------------------------------------------- H-3

def test_h3_the_token_is_not_vaulted(store):
    """The pin that stops a future maintainer 'hardening' export by vaulting
    the token, which would mask it in the one payload it must be readable in."""
    _session_in(_session.MANAGER, "s1")
    out = _call(action="export_handle", session="s1")
    token = out["token"]
    redacted = envelope.redact(dict(out))
    assert token in json.dumps(redacted), (
        "the export payload's own token came back redacted, so the caller "
        "cannot use it")


# ------------------------------------------------------------------- H-4

def test_h4_a_token_works_once(store):
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    first = _call(action="import_handle", token=token)
    assert first["imported"] == "s1"
    message = _refuses("NOT_FOUND", action="import_handle", token=token)
    assert "already used" in message or "used at" in message, message


# ------------------------------------------------------------------- H-5

def test_h5_a_token_expires(store, monkeypatch):
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1",
                  expires_minutes=1)["token"]
    later = time.time() + 3600
    monkeypatch.setattr(_handles.time, "time", lambda: later)
    message = _refuses("NOT_FOUND", action="import_handle", token=token)
    assert "expired" in message


def test_h5b_the_ttl_clamps_and_says_so(store):
    _session_in(_session.MANAGER, "s1")
    out = _call(action="export_handle", session="s1", expires_minutes=99999)
    assert out["expires_minutes"] == _handles.TTL_MAX_MIN
    assert "clamped" in json.dumps(out)


# ------------------------------------------------------------------- H-6

def test_h6_a_foreign_process_refusal_is_specific(store):
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["handles"][0]["minted_by_pid"] = 19004
    store.path.write_text(json.dumps(data), encoding="utf-8")
    store.reload()
    message = _refuses("CONFLICT", action="import_handle", token=token)
    assert "19004" in message, message
    assert str(_handles.os.getpid()) in message, message
    assert "unknown token" not in message.lower(), (
        "a cross-process token is known; saying otherwise hides the answer")


# ------------------------------------------------------------------- H-7

@pytest.mark.parametrize("reason,marker", [
    ("explicit_close", "closed"),
    ("idle_recycle", "recycle"),
    ("crash", "crash"),
])
def test_h7_tombstone_causes_are_distinguished(store, reason, marker):
    sess = _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    _session.MANAGER.entomb(sess, reason)
    _session.MANAGER.sessions.pop("s1")
    message = _refuses("CONFLICT", action="import_handle", token=token)
    assert marker in message.lower(), message


# ------------------------------------------------------------------- H-8

def test_h8_no_tombstone_is_still_an_honest_answer(store):
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    _session.MANAGER.sessions.pop("s1")
    message = _refuses("CONFLICT", action="import_handle", token=token)
    assert "no record" in message.lower(), message


# ------------------------------------------------------------------- H-9

@pytest.mark.parametrize("bad", [
    None, "", 7, "ks4web-x-" + "a" * 43, "ks4web-h-short",
])
def test_h9_a_malformed_token_refuses_bad_params(store, bad):
    _session_in(_session.MANAGER, "s1")
    before = store.path.read_text(encoding="utf-8") \
        if store.path.exists() else ""
    _refuses("BAD_PARAMS", action="import_handle", token=bad)
    after = store.path.read_text(encoding="utf-8") \
        if store.path.exists() else ""
    assert before == after, "a malformed token changed the store"


def test_h9b_a_one_character_change_is_not_a_match(store):
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    _refuses("NOT_FOUND", action="import_handle", token=tampered)


# ------------------------------------------------------------------ H-10

def test_h10_a_monitor_session_is_not_exportable(store):
    _session_in(_session.MANAGER, "s9", role="monitor")
    message = _refuses("BAD_PARAMS", action="export_handle", session="s9")
    assert "monitor" in message.lower(), message


# ------------------------------------------------------------------ H-11

def test_h11_the_action_list_names_both_new_actions(store):
    message = _refuses("BAD_PARAMS", action="nonsense")
    assert "export_handle" in message and "import_handle" in message, message


# ------------------------------------------------------------- D3-P, §7.6

def test_d3p_a_stale_handle_lookup_names_the_cause(store):
    """Every stale-handle refusal in the server reads the ring, not only
    import. Today `MANAGER.session('s1')` can only say the session is not
    open, which cannot distinguish a close from a crash from a restart."""
    sess = _session_in(_session.MANAGER, "s1")
    _session.MANAGER.entomb(sess, "crash")
    _session.MANAGER.sessions.pop("s1")
    with pytest.raises(errors.TargetNotFound) as caught:
        _session.MANAGER.session("s1")
    assert "crash" in str(caught.value).lower(), str(caught.value)


def test_the_tombstone_ring_is_bounded(store):
    for i in range(_session.TOMBSTONE_MAX + 10):
        sess = _session_in(_session.MANAGER, f"t{i}")
        _session.MANAGER.entomb(sess, "explicit_close")
        _session.MANAGER.sessions.pop(f"t{i}")
    assert len(_session.MANAGER.tombstones) == _session.TOMBSTONE_MAX


# ------------------------------------------------- the reconciliation report

def test_a_clean_import_reports_every_page_as_the_same_document(store):
    _session_in(_session.MANAGER, "s1",
                urls=("https://example.org/a", "https://example.org/b"))
    token = _call(action="export_handle", session="s1")["token"]
    report = _call(action="import_handle", token=token)
    assert report["imported"] == "s1"
    assert len(report["pages"]) == 2
    assert all(p["same_document_as_export"] for p in report["pages"])


def test_a_navigation_between_export_and_import_is_reported_per_page(store):
    sess = _session_in(_session.MANAGER, "s1",
                       urls=("https://example.org/a", "https://example.org/b"))
    token = _call(action="export_handle", session="s1")["token"]
    moved = sess.pages["s1p2"]
    moved.page.url = "https://example.org/c"
    report = _call(action="import_handle", token=token)
    rows = {p["page"]: p for p in report["pages"]}
    assert rows["s1p1"]["same_document_as_export"] is True
    assert rows["s1p2"]["same_document_as_export"] is False
    assert "https://example.org/c" in json.dumps(rows["s1p2"])


def test_the_report_does_not_invent_losses(store):
    """Same-process import is a lookup, not a transfer. The report says so
    rather than listing things it 'could not carry' to look thorough."""
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    report = _call(action="import_handle", token=token)
    assert report["carried"], "nothing is listed as carried"
    assert "not_carried" in report


def test_outstanding_tokens_show_in_status_without_the_token(store):
    _session_in(_session.MANAGER, "s1")
    token = _call(action="export_handle", session="s1")["token"]
    row = lite._session_status(_session.MANAGER.sessions["s1"])
    assert row["export_tokens"]["outstanding"] == 1
    assert token not in json.dumps(row)


# ------------------------------------------------------------ closed vocab

def test_every_transfer_refusal_uses_a_shipped_code(store):
    _session_in(_session.MANAGER, "s1", role="monitor")
    seen = set()
    for kwargs in (
        {"action": "export_handle", "session": "s1"},
        {"action": "import_handle", "token": "nope"},
        {"action": "import_handle", "token": "ks4web-h-" + "a" * 43},
        {"action": "export_handle", "session": "s404"},
    ):
        with pytest.raises(errors.WebMcpError) as caught:
            _call(**kwargs)
        seen.add(envelope.classify(caught.value))
    assert seen <= envelope.CLOSED_CODES, seen - envelope.CLOSED_CODES


# ------------------------------------------------- V-06: what reaches disk
#
# `lanedb.status()` ships `never_stores`: "paths, query strings, URLs, page
# titles, times of day, per-visit rows, and any intranet, IP-literal, or
# non-standard-port host". `lanes.json` honours that exactly. `handles.json`
# is written by `export_handle` into the SAME state directory and did not:
# the receipt carried every open page's full URL, query string and all, plus
# a filesystem path to a saved credential state that nothing on the read side
# ever consults. These pins say what may reach disk and what may not.

_SECRET_URL = ("http://127.0.0.1:51952/act?patient=12345&token=SECRETVALUE")


def test_v06_no_page_url_reaches_the_handle_store(store):
    _session_in(_session.MANAGER, "s1", urls=(_SECRET_URL,))
    _call(action="export_handle", session="s1")
    raw = store.path.read_text(encoding="utf-8")
    assert "SECRETVALUE" not in raw, (
        "the export receipt wrote a query string into handles.json, in the "
        "state directory that advertises it never stores query strings")
    assert "patient=12345" not in raw
    assert "/act" not in raw


def test_v06_no_auth_state_path_reaches_the_handle_store(store):
    sess = _session_in(_session.MANAGER, "s1")
    sess.jar_handle.record_auth_save(
        "C:/Users/someone/secrets/shop-auth.json")
    _call(action="export_handle", session="s1")
    raw = store.path.read_text(encoding="utf-8")
    assert "shop-auth.json" not in raw, (
        "the path to a saved credential state is on disk and no read path "
        "consults it")


def test_v06_the_exporting_caller_still_sees_its_own_session(store):
    """The DISK record is the problem, not the response. The conversation
    that just exported its own session is told what it holds."""
    sess = _session_in(_session.MANAGER, "s1", urls=(_SECRET_URL,))
    sess.jar_handle.record_auth_save(
        "C:/Users/someone/secrets/shop-auth.json")
    out = _call(action="export_handle", session="s1")
    assert out["receipt"]["pages"][0]["url"] == _SECRET_URL
    assert out["receipt"]["auth_state_saved_to"].endswith("shop-auth.json")


def test_v06_the_equality_test_still_works_without_the_url(store):
    """The only load-bearing use of the stored URL is an equality test, and
    a digest answers it exactly."""
    sess = _session_in(_session.MANAGER, "s1",
                       urls=(_SECRET_URL, "https://example.org/b"))
    token = _call(action="export_handle", session="s1")["token"]
    moved = sess.pages["s1p2"]
    moved.page.url = "https://example.org/c"
    report = _call(action="import_handle", token=token)
    rows = {p["page"]: p for p in report["pages"]}
    assert rows["s1p1"]["same_document_as_export"] is True
    assert rows["s1p2"]["same_document_as_export"] is False


def test_v06_the_report_does_not_claim_a_url_it_no_longer_holds(store):
    """`url_at_export` was the one human-readable use of the stored URL. It
    cannot be shown any more, so the row says that rather than going
    silent."""
    sess = _session_in(_session.MANAGER, "s1", urls=(_SECRET_URL,))
    token = _call(action="export_handle", session="s1")["token"]
    sess.pages["s1p1"].page.url = "https://example.org/c"
    report = _call(action="import_handle", token=token)
    row = report["pages"][0]
    assert "SECRETVALUE" not in json.dumps(row)
    assert "url_at_export" in row
    assert "digest" in row["url_at_export"]


def test_v06_export_says_a_file_is_written(store):
    _session_in(_session.MANAGER, "s1")
    out = _call(action="export_handle", session="s1")
    assert "handles.json" in out["security"], (
        "export_handle's security note does not mention that a record is "
        "written to disk at all")


# ------------------------------------------------------- the prune defects

def test_v06_prune_flushes_what_it_dropped(store):
    """`prune()` rewrote `self._records` in memory and never flushed, so a
    stale record left disk only as a side effect of the next mint. On the
    common import path the call RAISES before any mint, so a handles.json
    full of expired records outlived every reason to keep it."""
    _session_in(_session.MANAGER, "s1")
    _call(action="export_handle", session="s1")
    assert len(json.loads(store.path.read_text(encoding="utf-8"))
               ["handles"]) == 1
    later = time.time() + (_handles.DEFAULT_TTL_MIN * 60) \
        + _handles.TOMB_GRACE_S + 60
    store.reload()
    fake = _handles.HandleStore(store.path)
    real_time = time.time
    try:
        _handles.time.time = lambda: later
        fake.prune()
    finally:
        _handles.time.time = real_time
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))["handles"]
    assert on_disk == [], (
        "the expired record is still on disk after a prune that dropped it")


def test_v06_a_hand_edited_expiry_does_not_take_down_the_feature(store):
    """`float(r.get("expires_at", 0))` raised uncaught on a record whose
    expiry is not a number, and `prune()` runs on both the import and the
    export path, so one unreadable record broke both. `_load` defended the
    FILE against corruption; nothing defended a RECORD."""
    _session_in(_session.MANAGER, "s1")
    _call(action="export_handle", session="s1")
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["handles"][0]["expires_at"] = "not a number"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    store.reload()
    token = _call(action="export_handle", session="s1")["token"]
    report = _call(action="import_handle", token=token)
    assert report["imported"] == "s1"
