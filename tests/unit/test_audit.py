"""The audit trail (DESIGN 5.6): recorded, redacted at write, bounded,
paginated, and honestly framed."""

from __future__ import annotations

import json

import pytest

from kitchensink4web.errors import RangeOutOfBounds
from kitchensink4web.policy import audit, credentials


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    fresh = audit.AuditLog()
    credentials.VAULT.clear()
    yield fresh
    credentials.VAULT.clear()


def test_records_carry_the_designed_fields(log):
    audit.annotate(session="s1", page="p1", url="http://x/",
                   target={"role": "button", "name": "Send"})
    entry = log.record("click", "ok", args={"location": {"ref": "e1"}})
    assert entry["tool"] == "click"
    assert entry["outcome"] == "ok"
    assert entry["session"] == "s1"
    assert entry["page"] == "p1"
    assert entry["target"]["name"] == "Send"
    assert entry["seq"] == 1 and entry["ts"]


def test_annotations_drain_per_record(log):
    audit.annotate(session="s1")
    log.record("navigate", "ok")
    entry = log.record("navigate", "ok")
    assert "session" not in entry  # the channel does not leak across calls


def test_redaction_happens_at_write(log):
    credentials.VAULT.observe("KS4WEB-LS-SECRET-51be00aa41")
    entry = log.record("leaky", "ok",
                       args={"value": "got KS4WEB-LS-SECRET-51be00aa41"})
    assert "KS4WEB-LS-SECRET" not in json.dumps(entry)
    on_disk = (audit.STATE_DIR / "audit").glob("audit-*.jsonl")
    text = "".join(p.read_text(encoding="utf-8") for p in on_disk)
    assert "KS4WEB-LS-SECRET" not in text


def test_argument_values_are_clipped(log):
    entry = log.record("get_text", "ok", args={"blob": "x" * 5000})
    assert len(entry["args"]["blob"]) < 300
    assert "5000 chars" in entry["args"]["blob"]


def test_read_paginates_and_filters(log):
    for i in range(7):
        audit.annotate(session="s1" if i % 2 else "s2")
        log.record("navigate" if i % 2 else "click", "ok")
    got = log.read(start_index=0, limit=3)
    assert len(got["records"]) == 3
    assert got["next_start_index"] == 3
    assert got["total_matching"] == 7
    only_nav = log.read(tool="navigate")
    assert all(r["tool"] == "navigate" for r in only_nav["records"])
    only_s1 = log.read(session="s1")
    assert all(r["session"] == "s1" for r in only_s1["records"])
    with pytest.raises(RangeOutOfBounds):
        log.read(start_index=-1)


def test_storage_is_bounded_and_the_drop_count_is_reported(
        log, monkeypatch):
    monkeypatch.setattr(audit, "MAX_RECORDS", 5)
    small = audit.AuditLog()
    for i in range(12):
        small.record(f"t{i}", "ok")
    got = small.read(limit=50)
    assert len(got["records"]) == 5
    assert got["retention"]["dropped_from_ring"] == 7
    # The file rotated too: on-disk records stay bounded near the cap.
    path = got["retention"]["file"]
    lines = open(path, encoding="utf-8").read().splitlines()
    assert len(lines) <= 2 * 5


def test_the_framing_is_operational_never_forensic(log):
    got = log.read()
    assert "Not forensic and not evidence" in got["framing"]
