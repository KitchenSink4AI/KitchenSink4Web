"""A confirmation counts only when a human picked the yes option.

The gate logic was sound; the SHAPE of the question was not. Two hosts can
answer `accept` with nobody choosing anything, and both shapes `confirm.py`
sent counted a bare `accept` as yes:

- CODEX / CHATGPT DESKTOP in "Full access" (`approval_policy = never`):
  `can_auto_accept_elicitation` in codex-rs/codex-mcp/src/elicitation.rs
  answers `accept` with `content: {}` to any form whose `properties` is
  empty ("Auto-accept confirm/approval elicitations without schema
  requirements"), and declines forms that have fields. The Tier 2 prompt
  (money, credentials, deletion, legal) was exactly that empty form.
- VS CODE: typing a new chat message while the question card is open calls
  `ChatQuestionCarouselPart.skip()`, which submits `getDefaultAnswers()`
  (each field's schema `default`, nothing for a field without one), and
  `McpElicitationService._elicitForm` resolves any submitted answer map,
  even an empty one, as `action: 'accept'`.
- CHATGPT ON WINDOWS: the app-server parses `requestedSchema` into
  `McpElicitationSchema` (codex-rs/app-server-protocol/src/protocol/v2/
  mcp.rs), which is `deny_unknown_fields` with only `$schema`, `type`,
  `properties` and `required` at the root, so the root `title` the Tier 1
  dataclass schema carried made the host cancel before anyone saw it
  (openai/codex #46003).

The hosts are simulated here by an in-memory MCP client whose elicitation
handler behaves as the cited source does, so the question travels the real
wire path (schema serialization, request context, session) that a host sees.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitResult

from kitchensink4web import confirm
from kitchensink4web.errors import ConfirmationRequired
from kitchensink4web.policy import audit, consent, gates

#: One class from each tier. Tier 1 offers the "remember" box; Tier 2 (money,
#: credentials, deletion, legal...) never does.
TIER1 = "evaluate_script"
TIER2 = "payment_form"
BOTH = pytest.mark.parametrize("klass", [TIER1, TIER2])

ORIGIN = "https://a.example"

#: The wire contract, spelled out here rather than imported so a run against
#: the build BEFORE the fix fails on the attack, not on a missing name.
#: `test_the_wire_contract_is_pinned` holds confirm.py to the same values.
DECISION = "decision"
ALLOW = "Allow"
REMEMBER = "remember_30_minutes"

_ENVS = ("KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_SENSITIVE_ORIGINS",
         "KS4WEB_ALLOW_ORIGINS", "KS4WEB_DENY_ORIGINS", "KS4WEB_ALLOWED_ROOTS",
         "KS4WEB_REMEMBER")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    consent.apply("research")
    consent._reset_runtime_state()
    gates.ENGINE._pending.clear()
    gates.clear_grant()
    records: list[tuple] = []
    monkeypatch.setattr(audit.LOG, "record",
                        lambda tool, outcome, args=None, **kw:
                        records.append((tool, outcome, args)) or {})
    yield records
    gates.ENGINE._pending.clear()
    gates.clear_grant()
    consent._reset_runtime_state()
    consent.apply()


def _server(*, drop_gate: bool = False) -> FastMCP:
    """A tool that raises a REAL gate and runs the REAL confirmation."""
    app = FastMCP("confirm-gate")

    @app.tool
    async def gated(action_class: str) -> dict:
        try:
            gates.ENGINE.ask(
                action_class, tool="click", session="s1", page="p1",
                target={"role": "button", "name": "Go", "page_key": "k"},
                summary="go?", origin=ORIGIN)
        except ConfirmationRequired as exc:
            if drop_gate:
                gates.ENGINE._pending.clear()
            grant = await confirm.attempt(exc)
            return {"granted": grant is not None}
        return {"granted": "no gate was raised"}

    return app


def _run(klass: str, host=None, *, drop_gate: bool = False):
    """Call the gated tool once through `host`: (granted, questions)."""
    asked: list = []

    async def handler(message, response_type, params, context):
        asked.append(params)
        answer = host(params)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def go():
        kwargs = {} if host is None else {"elicitation_handler": handler}
        async with Client(_server(drop_gate=drop_gate), **kwargs) as c:
            result = await c.call_tool("gated", {"action_class": klass})
            return result.structured_content["granted"]

    return asyncio.run(go()), asked


# ----------------------------------------------------------- simulated hosts


def codex_full_access(params) -> ElicitResult:
    """codex-rs/codex-mcp/src/elicitation.rs under approval_policy=never."""
    if not (params.requestedSchema.get("properties") or {}):
        return ElicitResult(action="accept", content={})
    return ElicitResult(action="decline")


def vscode_new_message(params) -> ElicitResult:
    """VS Code `skip()`: the schema defaults, submitted as accept."""
    props = params.requestedSchema.get("properties") or {}
    return ElicitResult(action="accept", content={
        name: field["default"] for name, field in props.items()
        if "default" in field})


def bare_accept(params) -> ElicitResult:
    return ElicitResult(action="accept", content={})


def accept_without_content(params) -> ElicitResult:
    return ElicitResult(action="accept", content=None)


def answers(content):
    return lambda params: ElicitResult(action="accept", content=content)


def human_allows(params) -> ElicitResult:
    return ElicitResult(action="accept",
                        content={DECISION: ALLOW})


# ------------------------------------------------- the question's own shape


def test_the_wire_contract_is_pinned():
    pinned = (confirm.DECISION_FIELD, confirm.ALLOW, confirm.REMEMBER_FIELD)
    assert pinned == (DECISION, ALLOW, REMEMBER)
    assert confirm.ALLOW not in confirm.REFUSE_CHOICES


def _question(klass):
    granted, asked = _run(klass, lambda p: ElicitResult(action="cancel"))
    assert granted is False and len(asked) == 1
    return asked[0]


@BOTH
def test_the_question_is_never_an_empty_form(klass):
    schema = _question(klass).requestedSchema
    assert schema["properties"], "Full access auto-accepts an empty form"
    assert DECISION in schema.get("required", [])
    decision = schema["properties"][DECISION]
    assert "default" not in decision, "a preset answer is what VS Code submits"
    assert ALLOW in decision["enum"]
    assert len(set(decision["enum"])) >= 2, "a real choice, not a lone yes"


@BOTH
def test_the_question_fits_the_schema_chatgpt_on_windows_parses(klass):
    schema = _question(klass).requestedSchema
    assert set(schema) <= {"$schema", "type", "properties", "required"}, (
        f"root keys {sorted(schema)}: anything beyond these, a root title "
        f"included, makes the ChatGPT app cancel it (openai/codex #46003)")
    assert schema["type"] == "object"
    allowed = {
        "string": {"type", "title", "description", "enum", "enumNames",
                   "default", "oneOf", "minLength", "maxLength", "format"},
        "boolean": {"type", "title", "description", "default"},
    }
    for name, field in schema["properties"].items():
        assert field["type"] in allowed, (name, field)
        extra = set(field) - allowed[field["type"]]
        assert not extra, f"{name} carries {extra}, which the host rejects"


def test_only_tier_1_offers_the_remember_box():
    t1 = _question(TIER1).requestedSchema["properties"]
    t2 = _question(TIER2).requestedSchema["properties"]
    assert REMEMBER in t1
    assert REMEMBER not in t2
    assert REMEMBER not in _question(TIER1).requestedSchema.get(
        "required", [])


@BOTH
def test_the_prompt_no_longer_says_accept_means_allow(klass):
    message = _question(klass).message
    assert "accept to allow" not in message.lower()


# ------------------------------------------- the auto-answers are refused


@BOTH
def test_full_access_auto_accept_is_refused(klass):
    granted, asked = _run(klass, codex_full_access)
    assert asked, "the question must still be put to the host"
    assert granted is False


@BOTH
def test_vscode_default_submit_is_refused(klass):
    granted, _ = _run(klass, vscode_new_message)
    assert granted is False


@BOTH
def test_a_bare_accept_is_not_consent(klass):
    granted, _ = _run(klass, bare_accept)
    assert granted is False


@BOTH
def test_an_accept_with_no_content_is_not_consent(klass):
    granted, _ = _run(klass, accept_without_content)
    assert granted is False


@BOTH
@pytest.mark.parametrize("content", [
    {"decision": "Don't allow"},
    {"decision": "allow"},
    {"decision": "ALLOW"},
    {"decision": "Allow "},
    {"decision": True},
    {"decision": ["Allow"]},
    {"decision": None},
    {"allow": True},
    {"value": "Allow"},
    {"remember_30_minutes": True},
], ids=lambda c: repr(c))
def test_only_the_exact_yes_value_counts(klass, content):
    granted, _ = _run(klass, answers(content))
    assert granted is False, content


@BOTH
@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_decline_and_cancel_still_refuse(klass, action):
    granted, _ = _run(klass, lambda p: ElicitResult(action=action))
    assert granted is False


@BOTH
def test_a_host_error_refuses(klass):
    granted, _ = _run(klass, lambda p: RuntimeError("host blew up"))
    assert granted is False


@BOTH
def test_a_client_that_cannot_elicit_is_refused_at_once(klass):
    granted, asked = _run(klass, None)
    assert granted is False and asked == []
    assert consent.unattended() is True


# ------------------------------------------------ the human's yes still works


@BOTH
def test_the_human_pick_redeems_the_gate(klass):
    granted, _ = _run(klass, human_allows)
    assert granted is True


def test_remember_needs_the_yes_and_a_real_true(clean):
    granted, _ = _run(TIER1, answers({DECISION: ALLOW,
                                      REMEMBER: True}))
    assert granted is True
    assert [g["action_class"] for g in consent.grants()] == [TIER1]
    assert any(r[0] == "consent_grant" for r in clean)


@pytest.mark.parametrize("content", [
    {"decision": "Don't allow", "remember_30_minutes": True},
    {"remember_30_minutes": True},
    {"decision": "Allow", "remember_30_minutes": "true"},
    {"decision": "Allow", "remember_30_minutes": 1},
    {"decision": "Allow", "remember_30_minutes": False},
    {"decision": "Allow"},
], ids=lambda c: repr(c))
def test_no_grant_is_remembered_without_both(content):
    _run(TIER1, answers(content))
    assert consent.grants() == []


def test_tier_2_never_remembers_even_if_the_host_sends_the_box():
    granted, _ = _run(TIER2, answers({DECISION: ALLOW,
                                      REMEMBER: True}))
    assert granted is True
    assert consent.grants() == []


# ----------------------------------------------- what the channel tells us


def test_instant_unanswered_accepts_mark_the_session_unattended():
    """A host answering `accept` with no choice in under FAST_CANCEL_S is a
    machine, the same evidence an instant cancel is."""
    _run(TIER2, bare_accept)
    _run(TIER2, bare_accept)
    assert consent.unattended() is True


def test_a_human_yes_clears_the_unattended_evidence():
    _run(TIER2, bare_accept)
    _run(TIER2, bare_accept)
    assert consent.unattended() is True
    _run(TIER2, human_allows)
    assert consent.unattended() is False


def test_a_gate_already_gone_is_never_put_to_a_human():
    """Nothing a human says can redeem an expired or spent gate, so asking
    would only collect a yes that does nothing."""
    granted, asked = _run(TIER2, human_allows, drop_gate=True)
    assert granted is False
    assert asked == []
