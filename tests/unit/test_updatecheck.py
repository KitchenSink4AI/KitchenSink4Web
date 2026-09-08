"""The update notice: on demand, once a week, two seconds, and honest when
it could not run.

Every test drives the network seam through a monkeypatched urlopen; nothing
here touches the real PyPI.

REWRITTEN IN FIX WAVE 10 against the author-approved spec. The pins this file
used to carry described the superseded design and several of them asserted
the opposite of the new contract on purpose (a failed check was a silent skip
and wrote no cache; the window was 14 days; the off switch was a different
variable). They are replaced rather than added to, because a suite carrying
both would be pinning two contracts at once.
"""

from __future__ import annotations

import io
import json
import time

import pytest

from kitchensink4web import updatecheck
from kitchensink4web.policy import audit


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _pypi(version):
    return _Resp(json.dumps({"info": {"version": version}}).encode())


def _raw(text: str):
    return _Resp(text.encode() if isinstance(text, str) else text)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv(updatecheck.ENV_TOGGLE, raising=False)
    monkeypatch.delenv(updatecheck.ENV_OPT_OUT, raising=False)
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    monkeypatch.setattr(updatecheck, "_installed_version", lambda: "1.0.0")
    yield tmp_path


# ------------------------------------------------------------ the four states


def test_a_newer_release_is_named_with_both_versions(monkeypatch):
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.2.0"))
    payload = updatecheck.status_line()
    assert payload["state"] == "update_available"
    assert payload["installed"] == "1.0.0" and payload["latest"] == "1.2.0"
    assert "pip install -U kitchensink4web" in payload["note"]


def test_being_current_says_nothing(monkeypatch):
    """The one state with no line. A caller who is up to date does not need a
    paragraph about it on every status call."""
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.0.0"))
    assert updatecheck.status_line() is None
    assert updatecheck.check()["state"] == "current"


def test_running_ahead_of_pypi_is_current_too(monkeypatch, isolated):
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("0.9.0"))
    assert updatecheck.check()["state"] == "current"


def test_the_off_switch_says_it_is_off_rather_than_showing_nothing(
        monkeypatch):
    """THE HONESTY HALF OF THE OFF SWITCH. A check that is not running is a
    thing the server knows and is not telling unless it says so."""
    def boom(*a, **k):
        raise AssertionError("an off check must not reach the network")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", boom)
    monkeypatch.setenv(updatecheck.ENV_TOGGLE, "off")
    payload = updatecheck.status_line()
    assert payload["state"] == "off"
    assert updatecheck.ENV_TOGGLE in payload["why"]
    assert "nothing was sent anywhere" in payload["why"]


def test_the_superseded_opt_out_is_still_honored(monkeypatch):
    """A machine already configured to make no network call must not start
    making one because the variable was renamed."""
    def boom(*a, **k):
        raise AssertionError("the legacy opt-out must not reach the network")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", boom)
    monkeypatch.setenv(updatecheck.ENV_OPT_OUT, "1")
    assert updatecheck.status_line()["state"] == "off"


def test_a_typo_in_the_toggle_leaves_the_check_ON(monkeypatch):
    """BOTH-DIRECTION PIN. Only the word `off` switches it off. A typo that
    silently disabled a check the user believes is running is the failure
    this rule exists to prevent."""
    monkeypatch.setenv(updatecheck.ENV_TOGGLE, "offf")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.2.0"))
    assert updatecheck.check()["state"] == "update_available"


# ------------------------------------------------- the honest failure branch


def test_a_failed_check_reports_the_failure_and_the_age(monkeypatch,
                                                        isolated):
    """This is the point of the conversion. The superseded design swallowed
    this case entirely."""
    (isolated / "update_check.json").write_text(json.dumps(
        {"checked_at": time.time() - updatecheck.CACHE_MAX_AGE_S - 60,
         "last_success_at": time.time() - 3 * 86400,
         "latest": None}), encoding="utf-8")

    def down(*a, **k):
        raise OSError("no route to host")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", down)
    payload = updatecheck.status_line()
    assert payload["state"] == "unknown"
    assert "could not be reached" in payload["why"]
    assert "day(s) ago" in payload["last_successful_check"]
    assert "not a claim that the installed version is current" \
        in payload["note"]


def test_a_machine_that_never_succeeded_says_so(monkeypatch):
    def down(*a, **k):
        raise OSError("no route to host")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", down)
    payload = updatecheck.status_line()
    assert payload["state"] == "unknown"
    assert payload["last_successful_check"] == "never, on this machine"


def test_a_failed_check_still_costs_only_one_call_a_week(monkeypatch,
                                                         isolated):
    """The retry horizon is the same seven days as the success horizon. A
    machine with no network must not attempt a fetch on every status call."""
    calls = []

    def down(*a, **k):
        calls.append(1)
        raise OSError("no route to host")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", down)
    updatecheck.check()
    updatecheck.check()
    updatecheck.check()
    assert len(calls) == 1, "a failed check must record its attempt"


# --------------------------------------------------------------- the cadence


def test_the_window_is_seven_days():
    """AUTHOR RULING 2026-09-08, amending this wave's own 24-hour build. The
    number is pinned rather than left to a comment because it is a product
    decision about how often a small user base hears from this check, not a
    caching tuning knob somebody may reasonably adjust."""
    assert updatecheck.CACHE_MAX_AGE_S == 7 * 24 * 3600


def test_the_timeout_is_two_seconds():
    assert updatecheck.FETCH_TIMEOUT_S == 2.0


def test_a_fresh_cache_answers_without_the_network(monkeypatch, isolated):
    (isolated / "update_check.json").write_text(json.dumps(
        {"checked_at": time.time(), "latest": "2.0.0"}), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("a fresh cache must not reach the network")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", boom)
    assert updatecheck.status_line()["latest"] == "2.0.0"


def test_a_stale_cache_refetches_and_rewrites(monkeypatch, isolated):
    (isolated / "update_check.json").write_text(json.dumps(
        {"checked_at": time.time() - updatecheck.CACHE_MAX_AGE_S - 60,
         "latest": "1.5.0"}), encoding="utf-8")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.6.0"))
    assert updatecheck.status_line()["latest"] == "1.6.0"
    cached = json.loads((isolated / "update_check.json")
                        .read_text(encoding="utf-8"))
    assert cached["latest"] == "1.6.0"


# ------------------------------------------------------- hostile PyPI answers


@pytest.mark.parametrize("body", [
    "not json at all",
    "[]",
    "null",
    '{"info": "a string where an object belongs"}',
    '{"info": {}}',
    '{"info": {"version": null}}',
    '{"info": {"version": ["1", "2", "0"]}}',
    '{"info": {"version": {"major": 9}}}',
    '{"info": {"version": "9.9.9-evil; rm -rf /"}}',
    '{"info": {"version": "' + "1." * 40 + '0"}}',
])
def test_a_hostile_answer_never_crashes_and_never_names_a_version(
        monkeypatch, body):
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _raw(body))
    payload = updatecheck.check()
    assert payload["state"] == "unknown", payload
    assert "latest" not in payload, payload


def test_an_oversized_answer_is_refused_rather_than_read(monkeypatch):
    huge = '{"info": {"version": "9.9.9"}}' + " " * (updatecheck.MAX_BYTES + 8)
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _raw(huge))
    payload = updatecheck.check()
    assert payload["state"] == "unknown"
    assert "larger than expected" in payload["why"]


def test_the_failure_reason_is_a_category_not_the_servers_words(monkeypatch):
    """A remote server does not get to write a sentence into a KS4Web
    payload. Same rule as the driver-text scrubber."""
    def down(*a, **k):
        raise OSError("CONNECT tunnel failed, response 403 from evil.example")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", down)
    payload = updatecheck.check()
    assert "evil.example" not in json.dumps(payload)
    assert "403" not in json.dumps(payload)


def test_an_unparsable_installed_version_is_unknown_not_silence(monkeypatch):
    monkeypatch.setattr(updatecheck, "_installed_version",
                        lambda: "1.0.0.dev3")
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("2.0.0"))
    assert updatecheck.check()["state"] == "unknown"


# ------------------------------------------------------------- the disclosure


def test_every_answer_carries_the_privacy_disclosure(monkeypatch):
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen",
                        lambda *a, **k: _pypi("1.2.0"))
    for payload in (updatecheck.check(),):
        assert "pypi.org" in payload["privacy"]
        assert "sends nothing but the request" in payload["privacy"]
    monkeypatch.setenv(updatecheck.ENV_TOGGLE, "off")
    assert "pypi.org" in updatecheck.check()["privacy"]


def test_nothing_in_this_module_installs_anything():
    import inspect
    source = inspect.getsource(updatecheck)
    for forbidden in ("subprocess", "os.system", "pip.main", "runpy"):
        assert forbidden not in source, forbidden


def test_a_broken_check_never_costs_the_status_call(monkeypatch):
    """A status call is the surface a caller reaches for when everything else
    is refusing. Housekeeping may never be the reason it fails.

    Scoped to Exception deliberately: a KeyboardInterrupt or a SystemExit
    passing through is the interpreter shutting down, and swallowing one of
    those would be a worse bug than the one this guards."""
    def explode(*a, **k):
        raise RuntimeError("the state directory vanished mid-read")
    monkeypatch.setattr(updatecheck, "check", explode)
    assert updatecheck.status_line() is None


# ------------------------------------------- the check has exactly one caller


def test_only_manage_session_status_can_reach_the_check():
    """THE CONTAINMENT PIN. The conversion's first rule is check-on-demand,
    and a second call site added later would break it silently. Asserted
    against the source of the whole package rather than against a list
    somebody has to remember to update."""
    import pathlib

    import kitchensink4web

    root = pathlib.Path(kitchensink4web.__file__).parent
    callers = []
    for path in root.rglob("*.py"):
        if path.name == "updatecheck.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "updatecheck" in text:
            callers.append(path.relative_to(root).as_posix())
    assert callers == ["ops/lite.py"], callers


def test_the_only_call_site_sits_under_the_status_action():
    """One level finer than the file: the import must be inside the status
    branch, not at module scope where any action would run it."""
    import pathlib

    import kitchensink4web

    lite = (pathlib.Path(kitchensink4web.__file__).parent / "ops" / "lite.py")
    lines = lite.read_text(encoding="utf-8").splitlines()
    hits = [i for i, line in enumerate(lines) if "updatecheck" in line]
    assert hits, "the call site vanished"
    for i in hits:
        assert lines[i].startswith("    "), (
            f"line {i + 1} imports or calls updatecheck at module scope")
    # The nearest `if action == "status"` above the first call site, and the
    # nearest branch head of ANY kind above it. If the status test is not the
    # closest gate, the check is reachable under some other action.
    statuses = [i for i, line in enumerate(lines)
                if line.strip().startswith('if action == "status"')]
    guard = max((i for i in statuses if i < min(hits)), default=None)
    assert guard is not None, "no status branch precedes the update check"
    others = [i for i, line in enumerate(lines)
              if guard < i < min(hits)
              and line.strip().startswith(('if action ==', 'elif action =='))]
    assert not others, (
        f"another action branch sits between the status test and the update "
        f"check: lines {[i + 1 for i in others]}")
