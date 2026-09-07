"""The workflow origin lock, and the per-step failure record (fix wave
2026-09-08).

Two findings and one class sweep, all of them red before the fix.

V-05, the origin lock had two bypasses. `_check_origins` is the stated
guarantee that "a workflow recorded on one site does not get pointed at
another", and it only fires on a slot carrying `recorded_origin`. That key
used to be written only when the parameter's `kind` came out "url", and
`kind` is caller-supplied: declaring `kind: 'text'` on a navigate URL slot
turned the lock off at save time, and a hand-edited file that simply dropped
the line turned it off at load time. Both are pinned here.

V-15, the same field: `kind` had no allowlist anywhere, so `kind: 'banana'`
was stored and treated as text.

V-13, the per-step failure record: three sites wrote `str(exc)[:200]`, which
cuts a house refusal mid-word and throws away the half that says what to do
about it. The record now carries the refusal's own structure.

The class sweep on `_origin_of` is here too. It compared HOSTS, so a slot
recorded on `https://example.com` matched a spliced `http://example.com` and
a spliced `https://example.com:8443`.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from kitchensink4web.errors import (BadParams, ConfirmationRequired,
                                    NavigationBlocked, TargetNotFound,
                                    ValidationFailed)
from kitchensink4web.ops import workflows
from kitchensink4web.policy import audit


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    yield tmp_path


def _write(name: str, doc: dict) -> None:
    workflows._path_of(name).write_text(json.dumps(doc), encoding="utf-8")


def _log(rows):
    for row in rows:
        audit.annotate(replay=row, url=row.get("url"))
        audit.LOG.record(row["tool"], "ok", args={})


def _nav(url: str = "https://example.com/new") -> dict:
    return {"tool": "navigate", "args": {"url": url}, "anchor": None,
            "anchor_id": None, "page_key": url, "url": url}


def _doc(steps, parameters=None) -> dict:
    doc = {"name": "wf", "created": "2026-09-08T00:00:00", "session": "s1",
           "origins": ["example.com"], "steps": steps}
    if parameters is not None:
        doc["parameters"] = parameters
    return doc


def _url_doc(recorded_origin, url="https://example.com/new") -> dict:
    slot = {"param": "u", "field": "args.url", "span": [0, len(url)]}
    if recorded_origin is not None:
        slot["recorded_origin"] = recorded_origin
    return _doc([{"tool": "navigate", "args": {"url": url}, "slots": [slot]}],
                [{"name": "u", "required": True, "kind": "url"}])


def save(**kwargs):
    return asyncio.run(workflows.save_workflow(**kwargs))


def run(**kwargs):
    return asyncio.run(workflows.run_workflow(**kwargs))


def _saved(name: str) -> dict:
    return json.loads(workflows._path_of(name).read_text(encoding="utf-8"))


def _saved_url_workflow(name: str) -> None:
    """A one-step navigate workflow with a URL slot, recorded the way the
    build actually records one. The origin comparison pins go through this
    rather than hand-writing `recorded_origin`, so they measure what this
    build writes rather than what the test wishes it wrote."""
    _log([_nav()])
    save(name=name, parameters=[{"name": "u", "step": 0,
                                 "field": "args.url"}])


# ------------------------------------------------- V-05 bypass 1, at SAVE


def test_a_declared_kind_cannot_turn_the_origin_lock_off():
    """BYPASS 1. `kind` is caller-supplied, and declaring it short-circuited
    the derivation that wrote `recorded_origin`. A navigate URL slot gets an
    origin because of WHAT IT IS, not because of what the declaration says."""
    _log([_nav()])
    save(name="wf", parameters=[{"name": "u", "step": 0,
                                 "field": "args.url", "kind": "text"}])
    slot = _saved("wf")["steps"][0]["slots"][0]
    assert slot.get("recorded_origin"), \
        "a navigate args.url slot was saved with no origin lock"
    with pytest.raises(NavigationBlocked):
        run(name="wf", page="p1", dry_run=True,
            parameters={"u": "https://evil.example/pwn"})


def test_the_lock_survives_every_declared_kind():
    """The bypass is the declaration itself, so no value of it may unlock."""
    for kind in ("text", "bool", "url"):
        _log([_nav()])
        name = f"wf-{kind}"
        try:
            save(name=name, parameters=[{"name": "u", "step": 0,
                                         "field": "args.url", "kind": kind}])
        except BadParams:
            continue          # a bool on a string value refuses outright
        assert _saved(name)["steps"][0]["slots"][0].get("recorded_origin")


# ------------------------------------------------- V-05 bypass 2, at LOAD


def test_a_file_whose_navigate_slot_lost_its_origin_refuses():
    """BYPASS 2. `_validate_slots` checked field, param, span, and unknown
    keys, and never REQUIRED the one key the origin lock runs on, so a
    hand-edited file that dropped a single line retargeted freely."""
    _write("gone", _url_doc(None))
    with pytest.raises(ValidationFailed) as exc:
        run(name="gone", page="p1", dry_run=True,
            parameters={"u": "https://evil.example/pwn"})
    text = str(exc.value)
    assert "recorded_origin" in text and "edited" in text.lower()
    for accusation in ("you passed", "your ", "you gave"):
        assert accusation not in text.lower()


def test_a_file_this_build_wrote_still_loads():
    """The requirement is on the key, not on the caller: a file this build
    saved passes the new check and the lock does its job."""
    _saved_url_workflow("kept")
    with pytest.raises(NavigationBlocked):
        run(name="kept", page="p1", dry_run=True,
            parameters={"u": "https://evil.example/pwn"})


# ------------------------------------------------------ V-15, the kind set


def test_an_unrecognized_kind_refuses_at_save():
    _log([_nav()])
    with pytest.raises(BadParams) as exc:
        save(name="wf", parameters=[{"name": "u", "step": 0,
                                     "field": "args.url", "kind": "banana"}])
    assert "banana" in str(exc.value)
    assert not workflows._path_of("wf").exists()


def test_an_unrecognized_kind_in_a_file_refuses_at_load():
    doc = _url_doc("https://example.com")
    doc["parameters"][0]["kind"] = "banana"
    _write("bad", doc)
    with pytest.raises(ValidationFailed) as exc:
        run(name="bad", page="p1", dry_run=True, parameters={"u": "x"})
    assert "banana" in str(exc.value)


# ----------------------------------------- class sweep: what an origin IS


def test_the_recorded_origin_carries_the_scheme():
    _log([_nav()])
    save(name="wf", parameters=[{"name": "u", "step": 0,
                                 "field": "args.url"}])
    assert _saved("wf")["steps"][0]["slots"][0]["recorded_origin"] \
        == "https://example.com"


def test_a_scheme_downgrade_is_a_different_origin():
    """Host-only comparison let `https://example.com` be spliced to
    `http://example.com`, which puts everything the flow types on the wire in
    the clear and compared equal."""
    _saved_url_workflow("s")
    with pytest.raises(NavigationBlocked):
        run(name="s", page="p1", dry_run=True,
            parameters={"u": "http://example.com/new"})


def test_a_port_change_is_a_different_origin():
    _saved_url_workflow("p")
    with pytest.raises(NavigationBlocked):
        run(name="p", page="p1", dry_run=True,
            parameters={"u": "https://example.com:8443/new"})


def test_the_default_port_is_the_same_origin():
    """`https://example.com:443` and `https://example.com` are one origin,
    which is what the term means everywhere else."""
    _saved_url_workflow("d")
    with pytest.raises(Exception) as exc:
        run(name="d", page="p1", dry_run=True,
            parameters={"u": "https://example.com:443/new"})
    assert not isinstance(exc.value, NavigationBlocked)


def test_a_spliced_non_http_url_refuses():
    """Regression pin, green before the fix and green after: a recorded https
    navigate does not become a file:// read."""
    _saved_url_workflow("f")
    with pytest.raises(NavigationBlocked):
        run(name="f", page="p1", dry_run=True,
            parameters={"u": "file:///etc/passwd"})


def test_a_legacy_host_only_origin_still_locks():
    """A file written by an earlier build carries a bare host. It keeps
    comparing by host, which is the stated limit of the legacy shape."""
    _write("legacy", _url_doc("example.com"))
    with pytest.raises(NavigationBlocked):
        run(name="legacy", page="p1", dry_run=True,
            parameters={"u": "https://evil.example/x"})
    with pytest.raises(Exception) as exc:
        run(name="legacy", page="p1", dry_run=True,
            parameters={"u": "https://example.com/other"})
    assert not isinstance(exc.value, NavigationBlocked)


def test_one_host_extractor_and_it_handles_what_a_caller_types():
    """Two extractors lived in this file and disagreed on malformed input.
    The listing filter's manual string splitting is gone; both shapes come
    off one parser now."""
    assert workflows._host_of("Example.com") == "example.com"
    assert workflows._host_of("https://example.com:8443/x?y") == "example.com"
    assert workflows._host_of("user:pw@example.com/x") == "example.com"
    assert workflows._host_of("http://[::1]:8080/x") == "::1"
    assert workflows._host_of("") == ""
    # The subdomain widening rule the listing filter promises still holds.
    assert workflows._origin_matches("www.example.com", "example.com")
    assert not workflows._origin_matches("evil.com", "www.example.com")


# --------------------------------------------- V-13, the per-step record


_LONG = ("the step's anchor no longer resolves (STALE_ANCHOR, tier 3): was "
         "'Submit issue'. The recorded element is gone from this page and no "
         "candidate scored high enough to rebind to, which happens when a "
         "flow is replayed against a page that has been redesigned since it "
         "was recorded. Re-record the workflow against the current page.")


def _fake_run(sess, record, doc):
    return asyncio.run(workflows._execute(
        sess, record, doc, [{"step": 0}], None))


def _harness():
    sess = SimpleNamespace(session_id="s1")
    record = SimpleNamespace(handle="p1")
    doc = {"name": "wf", "steps": [{"tool": "navigate",
                                    "args": {"url": "https://example.com/"}}]}
    return sess, record, doc


def test_a_failed_step_carries_the_whole_refusal_not_200_bytes(monkeypatch):
    """V-13. The clip cut a house refusal mid-word and delivered zero
    recovery text."""
    async def boom(*a, **k):
        raise TargetNotFound(_LONG)
    monkeypatch.setattr(workflows, "_run_step", boom)
    out = _fake_run(*_harness())
    step = out["steps"][0]
    assert step["status"] == "failed"
    assert step["error"].endswith("Re-record the workflow against the "
                                  "current page.")
    assert step["hint"]


def test_a_gated_step_keeps_both_its_prefix_and_its_recovery(monkeypatch):
    """The site that genuinely lost its recovery: ~90 characters of fixed
    prefix ate half the budget before the refusal was appended."""
    from kitchensink4web import confirm

    async def boom(*a, **k):
        raise ConfirmationRequired(_LONG)

    async def declined(exc):
        return None
    monkeypatch.setattr(workflows, "_run_step", boom)
    monkeypatch.setattr(confirm, "attempt", declined)
    out = _fake_run(*_harness())
    step = out["steps"][0]
    assert step["outcome"] == "CONFIRMATION_REQUIRED"
    assert "FAILS CLOSED" in step["error"]
    assert step["error"].endswith("Re-record the workflow against the "
                                  "current page.")


def test_a_failed_step_carries_the_candidates_an_ambiguity_names(monkeypatch):
    """An ambiguity refusal's whole value is its candidate list, and the
    rendered-string clip was the one thing guaranteed to drop it."""
    from kitchensink4web.errors import AmbiguousLocation

    async def boom(*a, **k):
        exc = AmbiguousLocation("three elements matched. " + _LONG)
        exc.matches = [{"ref": "e1"}, {"ref": "e2"}, {"ref": "e3"}]
        raise exc
    monkeypatch.setattr(workflows, "_run_step", boom)
    out = _fake_run(*_harness())
    assert len(out["steps"][0]["matches"]) == 3
