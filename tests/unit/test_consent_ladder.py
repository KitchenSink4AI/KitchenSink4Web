"""THE CONSENT LADDER's pin list (DESIGN 5.4a, 2026-09-07).

Every test here fails on the build before the ladder landed. The POSITIVE
pins prove the friction actually goes away; the NEGATIVE pins prove it did
not open a hole, and the negative list is the longer one on purpose. A
streamlining feature is only as good as the set of things it refused to
streamline, so those are written first and there are four times as many.

The numbering follows the spec's pin list so a reviewer can walk the two
side by side.
"""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path

import pytest

from kitchensink4web import server
from kitchensink4web.errors import (BadParams, ConfirmationRequired,
                                    TargetChanged)
from kitchensink4web.policy import (audit, consent, engine, gates, readonly,
                                    submissions)

SRC = Path(server.__file__).resolve().parent

_ENVS = ("KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_SENSITIVE_ORIGINS",
         "KS4WEB_ALLOW_ORIGINS", "KS4WEB_DENY_ORIGINS", "KS4WEB_ALLOWED_ROOTS")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    yield
    # The teardown clears the environment ITSELF rather than leaning on
    # monkeypatch, because monkeypatch is torn down AFTER this fixture: a
    # test that set a refusing KS4WEB_PREAUTH would otherwise leave it set
    # while this line re-applies, and the whole file would error in teardown
    # on a launch value the test deliberately made illegal.
    for name in _ENVS:
        os.environ.pop(name, None)
    readonly.apply(False)
    consent.apply()


def setup(monkeypatch, *, scope="research", preauth=None, sensitive=None,
          allow=None, roots=None, read_only=False):
    """Apply one launch shape, exactly the way `server.configure` does."""
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    if preauth:
        monkeypatch.setenv("KS4WEB_PREAUTH", preauth)
    if sensitive:
        monkeypatch.setenv("KS4WEB_SENSITIVE_ORIGINS", sensitive)
    if allow:
        monkeypatch.setenv("KS4WEB_ALLOW_ORIGINS", allow)
    if roots:
        monkeypatch.setenv("KS4WEB_ALLOWED_ROOTS", roots)
    readonly.apply(read_only)
    return consent.apply(scope)


def census(**over) -> dict:
    base = {"method": "GET", "secret": False, "payment": False,
            "has_file": False, "enctype": "", "field_count": 1,
            "textarea": False, "recipient": False, "submitter": "Search",
            "action": "/search", "checkbox_labels": ""}
    base.update(over)
    return base


def desc(**over) -> dict:
    """A resolved descriptor carrying a form census."""
    out = {"role": "button", "name": over.pop("name", "Search"),
           "page_key": "https://example.com/x"}
    out["form_census"] = census(**over)
    return out


# =====================================================================
# POSITIVE PINS 1-6 — the friction must actually go away
# =====================================================================


def test_p1_get_search_form_is_in_grade_under_research(monkeypatch):
    """PIN 1. A GET form with no secret, payment, or file field submits with
    ZERO gates raised, under the NARROW scope. RFC 9110 9.2.1 defines GET as
    a safe method, so this is spec-backed rather than a guess, and it is the
    single change that removes the majority of the author's routine-research
    prompts."""
    setup(monkeypatch, scope="research")
    d = consent.decide("form_submit", url="https://example.com/s",
                       desc=desc(method="GET"))
    assert d.outcome == consent.IN_GRADE
    assert d.cleared_by == "grade"
    assert "9110" in d.reason


def test_p3_download_into_a_configured_sandbox_is_in_grade(monkeypatch, tmp_path):
    """PIN 3. The author's single most-cited blocked workflow: open-access
    PDF retrieval from a client that cannot render an elicitation. With a
    sandbox configured, containment, the downloads budget, and the audit
    trail already bound the harm."""
    setup(monkeypatch, scope="research", roots=str(tmp_path))
    inside = str(tmp_path / "paper.pdf")
    d = consent.decide("download_to_disk", url="https://example.com/p.pdf",
                       dest_path=inside)
    assert d.outcome == consent.IN_GRADE

    # And the same call with NO sandbox configured still asks, because then
    # the destination is anywhere on the disk.
    setup(monkeypatch, scope="research")
    assert consent.decide("download_to_disk", dest_path=inside).outcome \
        == consent.ASK


def test_p4_post_residual_is_full_only(monkeypatch):
    """PIN 4. A POST form matching no Tier 2 class is silent under `full`
    and asks under `research`. That difference IS the consent scope."""
    post = desc(method="POST", submitter="Search", action="/search")
    setup(monkeypatch, scope="full")
    assert consent.decide("form_submit", desc=post).outcome \
        == consent.IN_GRADE
    setup(monkeypatch, scope="research")
    assert consent.decide("form_submit", desc=post).outcome == consent.ASK


def test_p5_preauth_clears_a_named_origin_and_says_so(monkeypatch):
    """PIN 5. The claude.ai-web answer: a human ticks a settings field and
    `evaluate_script` on the named origin stops asking. The audit says
    `preauth`, never `human`."""
    setup(monkeypatch, scope="research",
          preauth="evaluate_script@localhost")
    d = consent.decide("evaluate_script", url="http://localhost:8000/x")
    assert d.outcome == consent.PREAUTH
    assert d.cleared_by == "preauth"
    # Another origin is untouched by it.
    assert consent.decide("evaluate_script",
                          url="https://evil.example/x").outcome == consent.ASK


def test_p6_storage_clear_is_grade_cleared(monkeypatch):
    """PIN 6. Being logged out is a recoverable annoyance, not a danger, and
    the phishing chain dead-ends because credential blindness refuses the
    password write in both grades."""
    setup(monkeypatch, scope="full")
    assert consent.decide("storage_clear").outcome == consent.IN_GRADE
    setup(monkeypatch, scope="research")
    assert consent.decide("storage_clear").outcome == consent.ASK


# =====================================================================
# NEGATIVE PINS 7-30 — an exceeds-grade action must STILL gate under
# every streamlining path
# =====================================================================


def test_n7_payment_gates_under_full(monkeypatch):
    setup(monkeypatch, scope="full")
    d = consent.decide("payment_form", url="https://shop.example/checkout")
    assert d.outcome == consent.ASK_LIVE_ONLY
    assert not d.clears


def test_n8_preauthorizing_a_tier2_class_refuses_to_start(monkeypatch):
    """PIN 8. Not a silent drop. A silently-ignored entry looks exactly like
    one that is working, and the human would believe they had configured
    something they had not."""
    for entry in ("payment_form@*", "budget_reset@github.com",
                  "credential_submit@*", "broadcast_submit@mysite.com",
                  "destructive_submit@*", "legal_assent@*",
                  "navigation_offlist@*", "action_offlist@*",
                  "age_gate_detected@*", "sensitive_origin@*",
                  "credential_injection@*"):
        with pytest.raises(BadParams) as exc:
            setup(monkeypatch, preauth=entry)
        assert entry.split("@")[0] in str(exc.value)


def test_n8b_an_unknown_class_or_a_malformed_entry_refuses_to_start(
        monkeypatch):
    """The other half of parsing strictly in BOTH directions. A misspelled
    class fails safe on its own; a well-spelled class with a sloppily-parsed
    origin is how a parser widens consent to every origin by accident."""
    for entry in ("evaluate_scrpit@localhost",      # typo'd class
                  "evaluate_script",                # no origin
                  "evaluate_script@",               # empty origin
                  "evaluate_script@localhost:3000",  # port with no scheme
                  "evaluate_script@example.com/api",  # a path
                  "evaluate_script@https://x.com/api?q=1",
                  "evaluate_script@localhost:9z",   # malformed ttl unit
                  "evaluate_script@localhost:0h"):  # a ttl that grants nothing
        with pytest.raises(BadParams):
            setup(monkeypatch, preauth=entry)


def test_n9_an_in_session_grant_never_clears_tier_2(monkeypatch):
    setup(monkeypatch, scope="full")
    assert consent.add_grant("payment_form", "https://shop.example") is None
    assert consent.decide("payment_form",
                          url="https://shop.example/pay").outcome \
        == consent.ASK_LIVE_ONLY


def test_n10_an_allowlisted_origin_does_not_clear_payment(monkeypatch):
    setup(monkeypatch, scope="full", allow="shop.example")
    assert consent.decide("payment_form", url="https://shop.example/pay",
                          origin_verdict="allowed").outcome \
        == consent.ASK_LIVE_ONLY


def test_n11_the_tier_is_a_property_of_the_class_not_the_tool(monkeypatch):
    """PIN 11. A workflow replay confirms per STEP, and each step reaches the
    same `decide()` with the same class, so nothing about being inside a
    replay changes the verdict. The tier is a property of the ACTION CLASS,
    never of an input string and never of the caller."""
    setup(monkeypatch, scope="full")
    for tool_kind in ("act", "download", "navigate"):
        assert consent.decide("payment_form", kind=tool_kind).outcome \
            == consent.ASK_LIVE_ONLY


def test_n13_a_get_checkout_form_still_gates(monkeypatch):
    """PIN 13, and it is the one that stops a future refactor from inverting
    the rule. The GET rule is a TIER 0 ADMISSION TEST and never a TIER 2
    EXEMPTION: payment is classified before the method is ever consulted."""
    setup(monkeypatch, scope="full")
    # The classifier: payment wins, so the class is never `form_submit`.
    from kitchensink4web.ops import act
    assert act.action_class_for(
        {"form_payment": True, "type": "submit", "tag": "BUTTON",
         "in_form": True, "form_census": census(method="GET", payment=True)},
        submitting=True) == "payment_form"
    # And the query-shaped test itself refuses a payment-carrying GET form.
    assert consent.query_shaped(census(method="GET", payment=True)) is False
    assert consent.query_shaped(census(method="GET", secret=True)) is False
    assert consent.query_shaped(census(method="GET", has_file=True)) is False
    assert consent.query_shaped(
        census(method="GET", enctype="multipart/form-data")) is False
    assert consent.query_shaped(census(method="POST")) is False


def test_n14_a_password_carrying_form_is_credential_submit(monkeypatch):
    """PIN 14, and it is one of the two gaps the old table did not cover.
    Credential blindness refuses the tool WRITING a password; nothing
    refused it pressing the button that sends one a human typed."""
    setup(monkeypatch, scope="full")
    found = submissions.classify(census(method="POST", secret=True,
                                        submitter="Sign in"))
    assert found[0] == "credential_submit"
    assert consent.decide("credential_submit").outcome \
        == consent.ASK_LIVE_ONLY


def test_n15_a_one_time_code_field_counts_as_secret():
    """PIN 15. The in-page census mirrors `credentials.SECRET_AUTOCOMPLETE`,
    so `autocomplete="one-time-code"` classifies with `type=password`."""
    from kitchensink4web.policy import credentials
    assert "one-time-code" in credentials.SECRET_AUTOCOMPLETE
    js = (SRC / "projection" / "consent.js").read_text(encoding="utf-8")
    for token in credentials.SECRET_AUTOCOMPLETE:
        assert f"'{token}'" in js, (
            f"{token!r} is secret server-side and invisible to the in-page "
            f"census, which is a field that is secret at the choke point and "
            f"absent from the form's own description")


def test_n16_broadcast_fires_in_every_shipped_language_with_a_control_arm(
        monkeypatch):
    """PIN 16. The payment list was English-only until a live PAN arrived in
    `Kartennummer`; that lesson does not need learning twice.

    THE CONTROL ARM IS HALF THE TEST. A gate that fires on everything is the
    same failure as a gate that fires on nothing, from the other side."""
    setup(monkeypatch, scope="full")
    posts = ["Post", "Veroffentlichen", "Publier", "Publicar", "Pubblica",
             "Comentar", "게시", "投稿", "发布", "發佈"]
    for label in posts:
        found = submissions.classify(
            census(method="POST", textarea=True, submitter=label,
                   action="/x"))
        assert found and found[0] == "broadcast_submit", label
    # CONTROL ARM: an ordinary POST search in the same run stays out of
    # every Tier 2 class.
    assert submissions.classify(
        census(method="POST", submitter="Search", action="/search")) is None
    assert consent.decide(
        "form_submit", desc=desc(method="POST", submitter="Search")).outcome \
        == consent.IN_GRADE


def test_n16b_a_bare_send_word_needs_a_corroborating_signal(monkeypatch):
    """`Enviar` is the standard Spanish label on an ordinary search button
    and `Senden` is the German one. A single signal that also names ordinary
    furniture is not a classification, so the bare send verbs fire only with
    a textarea or a recipient field beside them. Same multi-signal rule the
    payment classifier follows."""
    setup(monkeypatch, scope="full")
    alone = census(method="POST", submitter="Enviar", action="/buscar")
    assert submissions.classify(alone) is None
    withtext = census(method="POST", submitter="Enviar", textarea=True,
                      action="/mensajes")
    assert submissions.classify(withtext)[0] == "broadcast_submit"


def test_n16c_a_recipient_field_plus_free_text_is_a_broadcast(monkeypatch):
    setup(monkeypatch, scope="full")
    found = submissions.classify(
        census(method="POST", textarea=True, recipient=True,
               submitter="Go", action="/x"))
    assert found[0] == "broadcast_submit"


def test_n17_a_delete_account_submitter_is_destructive(monkeypatch):
    """PIN 17, with its control arm."""
    setup(monkeypatch, scope="full")
    for label in ["Delete my account permanently", "Konto loschen",
                  "Supprimer le compte", "Eliminar cuenta", "Elimina",
                  "Excluir conta", "계정 삭제", "アカウントを削除",
                  "删除账户"]:
        found = submissions.classify(
            census(method="POST", submitter=label, action="/account"))
        assert found and found[0] == "destructive_submit", label
    assert submissions.classify(
        census(method="POST", submitter="Save changes",
               action="/account")) is None
    # `delete` inside `deleted items` is a LABEL and not a verb on this
    # button: the match is boundary-aware.
    assert submissions.classify(
        census(method="POST", submitter="Search deleted items",
               action="/mail")) is None


def test_n17b_the_action_path_is_read_without_its_host():
    """A form posting to `deleteme.example.com/search` is a search on a
    badly-named host. The path is where a site says what an endpoint does."""
    assert submissions.classify(
        census(method="POST", submitter="Go",
               action="https://deleteme.example.com/search")) is None
    assert submissions.classify(
        census(method="POST", submitter="Go",
               action="https://example.com/account/delete"))[0] \
        == "destructive_submit"


def test_n18_an_i_agree_checkbox_is_legal_assent(monkeypatch):
    """PIN 18."""
    setup(monkeypatch, scope="full")
    found = submissions.classify(
        census(method="POST", submitter="Continue",
               checkbox_labels="I agree to the Terms and Conditions"))
    assert found[0] == "legal_assent"
    for labels in ["Ich stimme zu den AGB", "J accepte les conditions "
                   "generales", "Acepto los terminos y condiciones",
                   "이용약관에 동의합니다", "利用規約に同意します",
                   "我同意服务条款"]:
        found = submissions.classify(
            census(method="POST", submitter="OK", checkbox_labels=labels))
        assert found and found[0] == "legal_assent", labels
    # CONTROL ARM: an ordinary opt-in checkbox is not a legal assent.
    assert submissions.classify(
        census(method="POST", submitter="Sign up",
               checkbox_labels="Email me about new features")) is None


def test_n19_budget_reset_is_irreducible_everywhere(monkeypatch):
    """PIN 19. A budget the model could reset by calling a tool would not be
    a budget, and that stays true at every scope and under every setting."""
    setup(monkeypatch, scope="full")
    assert consent.decide("budget_reset").outcome == consent.ASK_LIVE_ONLY
    with pytest.raises(BadParams):
        setup(monkeypatch, scope="full", preauth="budget_reset@*")


def test_n20_offlist_still_gates_under_full_and_under_a_wrong_preauth(
        monkeypatch):
    """PIN 20. Both off-list classes are Tier 2, and a preauth for the same
    class on a DIFFERENT origin clears nothing here."""
    setup(monkeypatch, scope="full", allow="example.com",
          preauth="evaluate_script@example.com")
    for klass in ("navigation_offlist", "action_offlist"):
        assert consent.decide(klass, url="https://elsewhere.test/x",
                              origin_verdict="off-list").outcome \
            == consent.ASK_LIVE_ONLY


def test_n20b_a_wildcard_preauth_does_not_clear_a_configured_allowlist(
        monkeypatch):
    """PIN 20's other half, and it is a hole that was open until it was
    looked for.

    `navigation_offlist` and `action_offlist` are Tier 2, but the choke point
    only ASSIGNS them when the action carries no class of its own. So
    `evaluate_script` on an off-list origin arrives at the ladder wearing its
    OWN class, and a `evaluate_script@*` pre-authorization would have cleared
    it -- quietly widening an allowlist the human configured, using a setting
    they wrote for a different purpose. The allowlist is the narrower of the
    two settings and it wins."""
    setup(monkeypatch, scope="full", allow="example.com",
          preauth="evaluate_script@*,download_to_disk@*,clipboard_read@*")
    for klass in ("evaluate_script", "download_to_disk", "clipboard_read",
                  "form_submit", "storage_clear"):
        d = consent.decide(klass, url="https://elsewhere.test/x",
                           desc=desc(method="GET"),
                           origin_verdict="off-list")
        assert d.outcome == consent.ASK_LIVE_ONLY, klass
        assert not d.clears, klass
    # And ON the allowlist the same preauth works, which is the point of
    # having written it.
    assert consent.decide("evaluate_script", url="https://example.com/x",
                          origin_verdict="allowed").outcome == consent.PREAUTH


def test_n21_a_grant_for_origin_a_does_not_clear_origin_b(monkeypatch):
    """PIN 21. The scope of a grant is (origin, class, ttl) and never a raw
    string: that is the difference between a consent unit and the useless
    blanket 'always allow'."""
    setup(monkeypatch, scope="research")
    consent.add_grant("evaluate_script", "https://a.example")
    assert consent.decide("evaluate_script",
                          url="https://a.example/x").outcome == consent.GRANT
    assert consent.decide("evaluate_script",
                          url="https://b.example/x").outcome == consent.ASK
    # A port is part of the origin, so it is part of the key.
    assert consent.decide("evaluate_script",
                          url="https://a.example:8443/x").outcome \
        == consent.ASK


def test_n22_an_expired_grant_gates_again(monkeypatch):
    """PIN 22."""
    setup(monkeypatch, scope="research")
    consent.add_grant("evaluate_script", "https://a.example", ttl_s=0.05)
    assert consent.decide("evaluate_script",
                          url="https://a.example/x").outcome == consent.GRANT
    time.sleep(0.08)
    assert consent.decide("evaluate_script",
                          url="https://a.example/x").outcome == consent.ASK


def test_n22b_a_grant_can_never_outlive_its_ceiling(monkeypatch):
    setup(monkeypatch, scope="research")
    record = consent.add_grant("evaluate_script", "https://a.example",
                               ttl_s=999999)
    assert record["expires_in_s"] == int(consent.GRANT_MAX_TTL_S)


def test_n23_a_grant_for_class_x_does_not_clear_class_y(monkeypatch):
    """PIN 23."""
    setup(monkeypatch, scope="research")
    consent.add_grant("evaluate_script", "https://a.example")
    assert consent.decide("clipboard_read",
                          url="https://a.example/x").outcome == consent.ASK


def test_n24_no_registered_tool_schema_names_the_consent_surface(
        launch, live_tools):
    """PIN 24, the surface half. There is no argument to reach for: the
    scope, the pre-authorization table, and the sensitive-origin list are
    launch-time properties with no in-session parameter anywhere."""
    launch(read_only=False)
    for name, tool in live_tools().items():
        import json
        schema = json.dumps(tool.parameters or {}).lower()
        for needle in ("consent", "preauth", "ks4web_secret", "grant"):
            assert needle not in schema, (
                f"{name} exposes {needle!r} in its schema; Axis B is a "
                f"launch-time property with NO in-session argument")


def test_n25_consent_apply_has_exactly_one_caller():
    """PIN 25. A second caller is a runtime consent toggle wearing a
    disguise, so the same static scan that guards `readonly.apply()` covers
    `consent.apply()`."""
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel == "policy/consent.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "apply"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "consent"):
                offenders.append(f"{rel}:{node.lineno}")
    assert len(offenders) == 1 and offenders[0].startswith("server.py"), (
        f"consent.apply() is callable from startup ONLY "
        f"(server.configure); found: {offenders}")


def test_n25b_nothing_outside_the_module_writes_the_scope_or_the_tables():
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel == "policy/consent.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) \
                    else [node.target]
                for target in targets:
                    if (isinstance(target, ast.Attribute)
                            and target.attr in ("_scope", "_preauth",
                                                "_sensitive", "_grants",
                                                "DEFAULT_SCOPE",
                                                "IRREDUCIBLE",
                                                "GRADE_CLEARED")):
                        offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"the consent state is written only inside policy/consent.py: "
        f"{offenders}")


def test_n26_a_cleared_action_still_aborts_on_a_rebind(monkeypatch):
    """PIN 26. A clearance is permission to skip the QUESTION, never
    permission to skip the VERIFICATION. A rebind may be legitimate on its
    own terms and it still never launders a standing consent: the scope
    covers a class of action, not an element that moved underneath one."""
    setup(monkeypatch, scope="full")
    with pytest.raises(TargetChanged):
        engine.approve(engine.ActionRequest(
            tool="click", kind="act", session="s1", page="p1",
            url="https://example.com/x", target=desc(method="POST"),
            action_class="form_submit", resolution="rebound",
            summary="click Submit"))
    # And the same call without the rebind proceeds, cleared by grade.
    permit = engine.approve(engine.ActionRequest(
        tool="click", kind="act", session="s2", page="p1",
        url="https://example.com/x", target=desc(method="POST"),
        action_class="form_submit", summary="click Submit"))
    assert permit["gate"]["cleared_by"] == "grade"


def test_n27_the_audit_never_records_human_for_a_cleared_action(monkeypatch):
    """PIN 27. An audit trail that recorded a grade-cleared action as though
    a human answered would be a false record, and the audit's own framing as
    an operational log for the user cannot survive one."""
    setup(monkeypatch, scope="research", preauth="evaluate_script@localhost")
    permit = engine.approve(engine.ActionRequest(
        tool="evaluate_script", kind="act", session="s3", page="p1",
        url="http://localhost:9000/x", action_class="evaluate_script",
        summary="evaluate"))
    assert permit["gate"]["cleared_by"] == "preauth"
    assert permit["gate"]["cleared_by"] != "human"
    assert "localhost" in permit["gate"]["cleared_because"]

    setup(monkeypatch, scope="full")
    permit = engine.approve(engine.ActionRequest(
        tool="click", kind="act", session="s4", page="p1",
        url="https://example.com/x", target=desc(method="POST"),
        action_class="form_submit", summary="submit"))
    assert permit["gate"]["cleared_by"] == "grade"


def test_n27b_the_cleared_by_label_reaches_the_audit_record(monkeypatch):
    setup(monkeypatch, scope="full")
    engine.approve(engine.ActionRequest(
        tool="click", kind="act", session="s5", page="p1",
        url="https://example.com/x", target=desc(method="POST"),
        action_class="form_submit", summary="submit"))
    record = audit.LOG.record("click", "ok", args={})
    assert record["gate"]["cleared_by"] == "grade"


def test_n28_the_gate_ttl_did_not_move_and_no_queue_exists():
    """PIN 28. `GATE_TTL_S` is still 180 and there is no deferred-execution
    buffer anywhere: the TOCTOU fingerprint expires with the gate, so a
    decision approved forty minutes later CANNOT execute the original
    target. Extending the TTL to make a queue work would open precisely the
    hole the gate system exists to close, so the unattended answer is a
    refusal (author ruling, 2026-09-07)."""
    assert gates.GATE_TTL_S == 180.0
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "pending_decisions" not in text
        assert "queue_and_hold" not in text


def test_n29_read_only_is_unaffected_and_axis_b_is_inert(
        launch, monkeypatch):
    """PIN 29. `KS4WEB_CONSENT=full` under a read-only grade changes no
    tool's presence and clears nothing. The two axes are separate so the
    provable absence property survives the whole redesign intact."""
    monkeypatch.setenv("KS4WEB_CONSENT", "full")
    state = launch(read_only="browse")
    assert state["read_only"] == "browse"
    assert state["consent"] is None
    assert "click" not in state["registered"]
    assert not (set(state["registered"]) & readonly.MUTATING)
    assert consent.active() is False
    assert consent.decide("form_submit", desc=desc()).outcome == consent.ASK
    assert consent.describe()["consent_scope"] is None


def test_n29b_a_bad_scope_value_refuses_to_start(monkeypatch):
    with pytest.raises(BadParams):
        setup(monkeypatch, scope="everything")
    # And an EMPTY value fails closed to the narrowest scope rather than
    # widening, the same polarity KS4WEB_ALLOW_ACTING was fixed to.
    readonly.apply(False)
    monkeypatch.setenv("KS4WEB_CONSENT", "")
    assert consent.apply() == "research"


def test_n30_an_unattended_session_refuses_and_does_not_queue(monkeypatch):
    """PIN 30, as the author ruled it (v1: refuse, never queue). A queue
    entry for a purchase or a password invites someone to approve it later
    without the page context that made it meaningful, and the refusal is
    honest where a stale queued purchase is not."""
    setup(monkeypatch, scope="research")
    consent.note_confirmation("no_channel", 0.0)
    assert consent.unattended() is True
    for klass in ("payment_form", "form_submit"):
        with pytest.raises(ConfirmationRequired) as exc:
            engine.approve(engine.ActionRequest(
                tool="click", kind="act", session="s6", page="p1",
                url="https://example.com/x",
                target=desc(method="POST", submitter="Pay now"),
                action_class=klass, summary="do it"))
        text = str(exc.value)
        assert "no human is answering" in text.lower()
        # NOT QUEUED, in each branch's own ratified words: Tier 1 says the
        # confirmation expires so the work is not queued; Tier 2 says the
        # action proceeds only with a human answering at the moment of
        # asking, which is the same fact for a class no setting reaches.
        assert ("not queued" in text if klass == "form_submit"
                else "at the moment of asking" in text), text
        assert text.startswith("Refused:") and "Nothing was done." in text
        # A refusal must not carry an elicitation payload nobody can render.
        assert getattr(exc.value, "detail", None) is None
    # Tier 2 says no setting reaches it; Tier 1 names the preauth route.
    consent.note_confirmation("accepted", 1.0)
    assert consent.unattended() is False


def test_n30b_two_instant_cancels_mark_the_session_unattended(monkeypatch):
    """DETECTION, NOT ASSUMPTION. S8 measured a headless client
    auto-cancelling in 0.0 s; one fast decline by a human with a hair
    trigger is not evidence of anything."""
    setup(monkeypatch, scope="research")
    consent.note_confirmation("cancelled", 0.01)
    assert consent.unattended() is False
    consent.note_confirmation("cancelled", 0.01)
    assert consent.unattended() is True
    assert "under 0.5s" in consent.unattended_reason()
    # A human answer clears it: the flag says a human could not be reached.
    consent.note_confirmation("accepted", 4.0)
    assert consent.unattended() is False
    # A SLOW cancel is a human declining, and says nothing about presence.
    consent.note_confirmation("cancelled", 9.0)
    consent.note_confirmation("cancelled", 9.0)
    assert consent.unattended() is False


# =====================================================================
# The surfaces and the two content-adjacent classes
# =====================================================================


def test_the_sensitive_origin_list_is_the_humans_own(monkeypatch):
    """No topic classifier ships and none is planned: any list of risky
    topics imposes one person's values on every user and would gate a
    nuclear-weapons and DPRK research corpus on day one. The human names
    their own categories and the server holds no opinion."""
    setup(monkeypatch, scope="full", sensitive="private.example,*.vault.test")
    assert consent.decide("form_submit", url="https://private.example/x",
                          desc=desc()).outcome == consent.ASK_LIVE_ONLY
    assert consent.decide("form_submit", url="https://a.vault.test/x",
                          desc=desc()).outcome == consent.ASK_LIVE_ONLY
    # And a READ on the same origin is untouched: the list gates acting.
    assert consent.decide("form_submit", url="https://private.example/x",
                          desc=desc(), kind="navigate").outcome \
        == consent.IN_GRADE
    assert consent.decide("form_submit", url="https://other.example/x",
                          desc=desc()).outcome == consent.IN_GRADE


def test_the_age_gate_relays_the_pages_own_declaration(monkeypatch):
    """The server relays a claim the PAGE made about itself. It makes no
    judgment of content anywhere, and there is no code path that could."""
    setup(monkeypatch, scope="full")
    assert consent.decide("form_submit", desc=desc(),
                          age_declared=True).outcome == consent.ASK_LIVE_ONLY
    js = (SRC / "projection" / "consent.js").read_text(encoding="utf-8")
    assert "rating" in js and "RTA" in js.upper()


def test_an_ordinary_action_on_a_sensitive_origin_gets_a_class(monkeypatch):
    """A click with no gated class at all still has to reach a gate on a
    listed origin, so the choke point supplies the class."""
    setup(monkeypatch, scope="full", sensitive="private.example")
    with pytest.raises(ConfirmationRequired) as exc:
        engine.approve(engine.ActionRequest(
            tool="click", kind="act", session="s7", page="p1",
            url="https://private.example/x", target={"role": "button"},
            summary="click"))
    assert "always" in str(exc.value)


def test_the_status_surface_states_the_limit_beside_the_permission(
        monkeypatch):
    """The same honesty grammar `readonly.describe()` uses. A surface that
    listed what is allowed without listing what still asks would teach the
    wrong lesson to the one person reading it."""
    setup(monkeypatch, scope="full", preauth="evaluate_script@localhost:8h",
          sensitive="private.example")
    shown = consent.describe()
    assert shown["consent_scope"] == "full"
    assert "payment_form" in shown["always_asks"]
    assert "budget_reset" in shown["always_asks"]
    assert shown["preauthorized"] == [
        {"action_class": "evaluate_script", "origin": "localhost",
         "expires_in_s": pytest.approx(8 * 3600, abs=5)}]
    assert shown["sensitive_origins"] == ["private.example"]
    assert shown["unattended"] is False
    # NAMES AND PATTERNS ONLY, in a NORMALIZED form. The raw environment
    # string is not echoed back: what a caller needs is what is in force,
    # and echoing the setting verbatim is how a surface starts leaking the
    # shape of settings that DO carry values.
    import json
    blob = json.dumps(shown)
    assert "evaluate_script@localhost:8h" not in blob
    assert "KS4WEB_SECRET" not in blob


def test_the_preauth_teaching_hands_the_agent_nothing_callable():
    """The property `readonly.UNLOCK_TEACHING` is already held to, applied to
    its analog. A teaching that named an in-session route would be a bypass
    wearing an instruction's clothes, and this one sits in a payload the
    model reads."""
    text = consent.PREAUTH_TEACHING.lower()
    assert "restart" in text or "settings" in text
    assert "human" in text or "settings" in text
    # It says the irreducible set can never be pre-authorized, which is the
    # half that stops someone trying and finding out at launch.
    assert "never be pre-authorized" in text or "can never" in text
    for forbidden in ("manage_session(action", "(action=", "redeem",
                      "requeststate", "elicitation/create", "inputrequest"):
        assert forbidden not in text, (
            f"the preauth teaching names {forbidden!r}, which points the "
            f"agent at an in-session route rather than a human restart")


def test_the_permits_line_states_the_limit_beside_the_permission(monkeypatch):
    """`readonly.describe()["permits"]`'s grammar, applied to Axis B. A
    surface that listed what is allowed without listing what still asks
    teaches the wrong lesson to the one person reading it."""
    for name in consent.SCOPES:
        line = consent.PERMITS[name].lower()
        assert "ask" in line, (
            f"the {name!r} permits line names no limit; it has to say what "
            f"still asks, not only what stopped asking")
    setup(monkeypatch, scope="research")
    assert consent.describe()["permits"] == consent.PERMITS["research"]


def test_a_ttl_is_read_as_a_ttl_and_a_port_as_a_port(monkeypatch):
    """`:8443` is a port and `:8h` is a time-to-live. Requiring the unit is
    what keeps the two apart in one grammar."""
    setup(monkeypatch, preauth="evaluate_script@https://x.test:8443")
    assert consent.preauth_entries()[0]["origin"] == "https://x.test:8443"
    assert consent.preauth_entries()[0]["expires_in_s"] is None
    setup(monkeypatch, preauth="evaluate_script@https://x.test:8443:30m")
    entry = consent.preauth_entries()[0]
    assert entry["origin"] == "https://x.test:8443"
    assert entry["expires_in_s"] == pytest.approx(1800, abs=5)


def test_a_wildcard_preauth_must_be_spelled_out(monkeypatch):
    setup(monkeypatch, scope="research", preauth="download_to_disk@*")
    assert consent.decide("download_to_disk",
                          url="https://anywhere.test/f.pdf").outcome \
        == consent.PREAUTH
    setup(monkeypatch, scope="research", preauth="download_to_disk@*.x.test")
    assert consent.decide("download_to_disk",
                          url="https://a.x.test/f.pdf").outcome \
        == consent.PREAUTH
    assert consent.decide("download_to_disk",
                          url="https://y.test/f.pdf").outcome == consent.ASK


def test_the_remember_answer_is_offered_on_tier_1_only(monkeypatch):
    """The 30-minute button changes how a prompt renders on every client, so
    it is offered only where it can do any good. Money, credentials, sends,
    deletions, terms, off-list, and budgets keep the bare accept/decline
    they ship with."""
    setup(monkeypatch, scope="research")
    assert consent.grantable("evaluate_script") is True
    for klass in sorted(consent.IRREDUCIBLE):
        assert consent.grantable(klass) is False, klass
    monkeypatch.setenv("KS4WEB_REMEMBER", "off")
    assert consent.grantable("evaluate_script") is False


def test_grants_die_with_the_session(monkeypatch):
    setup(monkeypatch, scope="research")
    consent.add_grant("clipboard_read", "https://a.example")
    assert consent.grants()
    consent.clear_grants()
    assert consent.grants() == []


def test_every_gated_class_has_its_own_sentence():
    """The `storage_load` incident is the standing reminder: a borrowed
    sentence asked a human to allow 'clearing cookies or site storage' for
    an operation that clears nothing, and someone reading carefully declines
    the wrong thing."""
    sentences = list(gates.GATED_CLASSES.values())
    assert len(sentences) == len(set(sentences))
    for klass in ("credential_submit", "broadcast_submit",
                  "destructive_submit", "legal_assent", "age_gate_detected",
                  "sensitive_origin", "credential_injection"):
        assert gates.GATED_CLASSES[klass]


def test_the_tier_tables_partition_the_gate_table():
    """Every gated class has exactly one tier, and no class is both
    irreducible and pre-authorizable. A class in neither table would be
    silently un-clearable-and-un-askable, which is the kind of gap a table
    written by hand grows."""
    both = consent.IRREDUCIBLE & consent.PREAUTHORIZABLE
    assert not both, both
    covered = consent.IRREDUCIBLE | consent.PREAUTHORIZABLE
    assert covered == set(gates.GATED_CLASSES), (
        set(gates.GATED_CLASSES) ^ covered)
    assert set(consent.GRADE_CLEARED) <= consent.PREAUTHORIZABLE


#: The ONE sanctioned direct caller of the gate engine, named here rather
#: than discovered by the test. `fill_form`'s submit branch keeps its own
#: `ask` because it re-resolves the anchor field AFTER the fills and holds
#: the gate to that fresh read, which is a stronger verification than routing
#: through the choke point would give it; it consults `consent.decide()`
#: itself, immediately above the call.
_SANCTIONED_DIRECT_ASK = {("lite.py", "fill_form")}


def test_every_gated_door_goes_through_the_consent_ladder():
    """THE MECHANICAL HALF, and it is the pin that would have caught the
    integration gap this wave found late.

    Eleven sites in `ops/` reached a gate WITHOUT `approve()`, each of them
    legitimate on its own terms, and every one of them called
    `gates.ENGINE.ask()` directly. So they never saw the consent scope:
    `storage_clear` under `full` still asked, and
    `KS4WEB_PREAUTH=storage_load@github.com` cleared `load_auth_state` while
    leaving `manage_session(open, auth_state=...)` asking, which is the same
    operation spelled differently. A ladder with eleven doors around it is
    not a ladder.

    A twelfth door added later fails here rather than shipping."""
    offenders = []
    for path in (SRC / "ops").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=path.name)
        func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Call)
                            and isinstance(inner.func, ast.Attribute)
                            and inner.func.attr == "ask"
                            and isinstance(inner.func.value, ast.Attribute)
                            and inner.func.value.attr == "ENGINE"):
                        func = (path.name, node.name)
                        if func not in _SANCTIONED_DIRECT_ASK:
                            offenders.append(
                                f"{path.name}:{inner.lineno} in {node.name}")
    assert not offenders, (
        f"these sites reach the gate engine without the consent ladder, so "
        f"the scope, the pre-authorizations, and the unattended refusal do "
        f"not apply to them: {offenders}. Call policy.engine.confirm().")


def test_confirm_is_the_one_place_a_class_meets_the_ladder():
    """`approve()` step 7 and `confirm()` are the same code, not two copies:
    a second implementation is how the two drift and how one of them quietly
    stops honoring a pre-authorization."""
    import inspect
    source = inspect.getsource(engine.approve)
    assert "confirm(" in source
    assert "consent.decide" not in source.split("def confirm")[0].split(
        "gate_record = confirm")[-1]
    assert "consent.decide" in inspect.getsource(engine.confirm)


def test_the_environment_is_not_read_at_decide_time(monkeypatch):
    """The scope is resolved ONCE at startup. A runtime read would let a
    process that mutated its own environment widen its consent mid-session,
    which is the property `readonly` established and this module inherits."""
    setup(monkeypatch, scope="research")
    os.environ["KS4WEB_CONSENT"] = "full"
    try:
        assert consent.scope() == "research"
        assert consent.decide("storage_clear").outcome == consent.ASK
    finally:
        os.environ.pop("KS4WEB_CONSENT", None)
