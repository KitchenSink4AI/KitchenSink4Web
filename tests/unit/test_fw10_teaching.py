"""Fix wave 10: what a caller is told when a capability is absent.

The field report's items 4 and 19 are one complaint seen twice: KS4Web
refuses correctly and does not reliably say what would make the call work,
or that the fix is a human's launch-time act rather than something the
assistant can arrange. This file pins the answers that were missing, and the
both-direction partner of each one, because every fix here is a widening of
what a message says and a widened message is easy to widen into a lie.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from kitchensink4web import envelope, packs
from kitchensink4web.policy import consent, engine, gates, readonly

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ------------------------------------------------ optional-feature visibility


def test_status_reports_every_optional_feature_before_it_is_needed():
    rows = packs.optional_features()
    for name in ("accessibility", "ocr"):
        row = rows[name]
        assert isinstance(row["installed"], bool)
        assert row["why"].strip()
        assert row["provides"], name
        assert row["engine"].strip()
        # The pack is the half that is easy to miss: a caller who installed
        # the extra and still cannot see the tool has no way to work out
        # which of the two halves is missing.
        assert row["also_needs_pack"] in packs.pack_names()
        assert isinstance(row["pack_loaded"], bool)


def test_the_ocr_row_states_the_windows_truth():
    """Not a packaging gap. On macOS and Linux the extra installs and there
    is still no engine, and a row that only said 'not installed' would send
    a user to install something that cannot help."""
    row = packs.optional_features()["ocr"]
    assert row["platforms"] == "Windows only"
    assert "Windows" in row["platform_note"]


def test_the_advertised_extras_exist_in_pyproject():
    """FIELD REPORT Q1, answered mechanically. The tester doubted the extra
    names printed in refusals. This asserts the printed name is the name
    pyproject actually declares, so the doubt cannot come back."""
    import tomllib
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = set(data["project"]["optional-dependencies"])
    for spec in packs.OPTIONAL_FEATURES:
        assert spec["extra"] in declared, spec["extra"]
    from kitchensink4web import ocr
    from kitchensink4web.ops import a11y
    assert a11y.EXTRA == data["project"]["name"] + "[accessibility]"
    assert ocr.EXTRA == data["project"]["name"] + "[ocr]"


def test_a_missing_feature_names_both_install_routes():
    """The pip sentence is right for one install route and wrong for the
    other, and this process cannot reliably tell which one started it, so
    both are published rather than one being guessed."""
    rows = packs.optional_features()
    for name in ("accessibility", "ocr"):
        row = rows[name]
        if row["installed"]:
            continue
        assert set(row["install"]) == set(packs.INSTALL_ROUTES)
        assert "pip install" in row["install"]["pip_or_uv"]
        assert "bundle" in row["install"]["desktop_bundle"]


def test_an_installed_feature_prints_no_install_instruction():
    """BOTH-DIRECTION PIN. Telling a caller how to install something they
    already have is the same class of untruth as not telling them at all."""
    for row in packs.optional_features().values():
        if isinstance(row, dict) and row.get("installed"):
            assert "install" not in row, row


def test_the_optional_feature_block_says_enabling_is_launch_time():
    text = packs.optional_features()["how_this_works"]
    assert "launch-time" in text
    assert "cannot be turned on by a tool call" in text


# ------------------------------------------------------- the read-only route


def test_no_refusal_tells_a_default_install_to_remove_a_flag_it_never_set():
    """AUDIT GAPS 1 AND 2. The shipped default grade is `browse` with no
    --read-only flag present, so 'restart without --read-only' was a no-op
    instruction printed on every read-only refusal in the product."""
    assert readonly.DEFAULT_GRADE == "browse"
    hint = envelope.HINTS["READ_ONLY_MODE"]
    assert "without --read-only" not in hint, hint
    assert "KS4WEB_ALLOW_ACTING" in hint


def test_the_ladders_own_read_only_refusal_names_the_switch(monkeypatch):
    monkeypatch.setattr(readonly, "grade", lambda: "browse")
    request = engine.ActionRequest(tool="click", kind="act", session="s1")
    with pytest.raises(Exception) as caught:
        engine.approve(request)
    message = str(caught.value)
    assert "KS4WEB_ALLOW_ACTING" in message
    assert "not something any tool call can do" in message


def test_the_read_only_hint_and_the_message_do_not_contradict():
    """BOTH-DIRECTION PIN. The hint rides underneath messages that already
    name the real switch; the two must name the same one."""
    assert "KS4WEB_ALLOW_ACTING" in readonly.UNLOCK_TEACHING
    assert "KS4WEB_ALLOW_ACTING" in envelope.HINTS["READ_ONLY_MODE"]


# ---------------------------------------------------- the consent-scope route


def test_a_gated_action_learns_why_its_class_asked():
    """AUDIT GAP 4. `consent.decide` composes a sentence naming the scope in
    force and the setting that would clear the class, the ladder used it on
    the CLEARED branch, and the ASK branch dropped it. A caller gated under
    `research` was never told KS4WEB_CONSENT exists."""
    with pytest.raises(Exception) as caught:
        gates.ENGINE.ask("form_submit", tool="click", session="s1",
                         page="p1", target={"ref": "e1"},
                         summary="Submit the form.", unattended=True,
                         reason="this class asks under the consent scope "
                                "'research'")
    assert "consent scope" in str(caught.value)


def test_the_ask_still_works_with_no_reason_to_give():
    """BOTH-DIRECTION PIN. `reason` is optional and a gate raised without
    one must still be a complete refusal."""
    with pytest.raises(Exception) as caught:
        gates.ENGINE.ask("form_submit", tool="click", session="s1",
                         page="p1", target={"ref": "e1"},
                         summary="Submit the form.", unattended=True)
    message = str(caught.value)
    assert "needs a human confirmation" in message
    assert message.rstrip().endswith(".")


def test_the_preauth_teaching_still_names_the_launch_time_fact():
    assert "KS4WEB_PREAUTH" in consent.PREAUTH_TEACHING
    assert "not something any tool call can do" in consent.PREAUTH_TEACHING


# ----------------------------------------------------------- the setup topic


def test_get_workflows_carries_a_setup_topic():
    from kitchensink4web.ops import lite
    setup = asyncio.run(lite.get_workflows(topic="setup"))["workflow"]
    for key in ("acting", "packs", "optional_extras", "consent",
                "dependencies", "how_to_check"):
        assert key in setup, key
    assert "KS4WEB_ALLOW_ACTING" in setup["acting"]
    assert "launch" in setup["packs"]
    assert "manage_session(action='status')" in setup["how_to_check"]


def test_the_setup_topic_does_not_answer_what_status_answers():
    """One source of truth for what is installed. A second copy here is a
    second opinion that can disagree with the first."""
    from kitchensink4web.ops import lite
    setup = asyncio.run(lite.get_workflows(topic="setup"))["workflow"]
    blob = json.dumps(setup)
    assert '"installed"' not in blob
    assert "pack_loaded" not in blob
