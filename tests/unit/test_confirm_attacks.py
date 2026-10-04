"""Attack cases for the confirmation plumbing, from an independent review.

Independent of `test_confirm_explicit_consent.py`:

- the host side is the RAW mcp SDK `ClientSession` with a raw
  `elicitation_callback` (no fastmcp client-side schema-to-type conversion),
  so every answer reaches the server exactly as written, including answers a
  well-behaved client library would refuse to build;
- the gated tool goes through the REAL `server._wrap` (the S8 wiring: ask,
  confirm.attempt, deposit, re-run) and the REAL `policy.engine.confirm`
  choke point (consent ladder, grants, unattended flag, TOCTOU
  re-validation), not a direct `ENGINE.ask`.

A case "ran" only when the tool body got past the gate and executed.
"""

from __future__ import annotations

import asyncio
import time

import anyio
import mcp.types as mt
import pytest
from fastmcp import FastMCP
from fastmcp.client.transports.memory import FastMCPTransport

from kitchensink4web import confirm
from kitchensink4web import server as srv
from kitchensink4web.policy import audit, consent, engine, gates

TIER1 = "evaluate_script"
TIER2 = "payment_form"
URL = "https://a.example/page"
ORIGIN = "https://a.example"

_ENVS = ("KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_SENSITIVE_ORIGINS",
         "KS4WEB_ALLOW_ORIGINS", "KS4WEB_DENY_ORIGINS", "KS4WEB_ALLOWED_ROOTS",
         "KS4WEB_REMEMBER")

RAN: list[str] = []


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    consent.apply("research")
    consent._reset_runtime_state()
    gates.ENGINE._pending.clear()
    gates.clear_grant()
    RAN.clear()
    monkeypatch.setattr(audit.LOG, "record",
                        lambda *a, **k: {})
    monkeypatch.setattr(audit, "annotate", lambda *a, **k: None,
                        raising=False)
    yield
    gates.ENGINE._pending.clear()
    gates.clear_grant()
    consent._reset_runtime_state()
    consent.apply()


def _app() -> FastMCP:
    app = FastMCP("confirm-attacks")

    async def gated(label: str, action_class: str = TIER1,
                    url: str = URL) -> dict:
        target = {"role": "button", "name": label, "page_key": "k"}
        rec = engine.confirm(action_class, tool="click", session="s1",
                             page="p1", target=target,
                             summary=f"press {label}", url=url)
        RAN.append(label)
        return {"ran": label, "cleared_by": rec.get("cleared_by"),
                "confirmed": (rec.get("confirmed_target") or {}).get("name")}

    gated.__name__ = "gated"
    app.tool(srv._wrap(gated), output_schema=None)
    return app


def _raw(action, content=None, *, construct=False):
    """An ElicitResult exactly as written. `construct` skips pydantic so the
    wire carries values the schema type would refuse (objects, bad actions)."""
    if construct:
        return mt.ElicitResult.model_construct(action=action, content=content)
    return mt.ElicitResult(action=action, content=content)


def run_calls(calls, host=None, *, concurrent=False):
    """Run tool calls through one raw ClientSession. `host(params)` returns
    the ElicitResult (or awaits). Returns (results, asked_params)."""
    asked: list = []

    async def cb(context, params):
        asked.append(params)
        ans = host(params)
        if asyncio.iscoroutine(ans):
            ans = await ans
        return ans

    async def go():
        kwargs = {} if host is None else {"elicitation_callback": cb}
        transport = FastMCPTransport(_app())
        async with transport.connect_session(**kwargs) as session:
            await session.initialize()
            if concurrent:
                results = [None] * len(calls)

                async def one(i, args):
                    results[i] = await session.call_tool("gated", args)

                async with anyio.create_task_group() as tg:
                    for i, args in enumerate(calls):
                        tg.start_soon(one, i, args)
                return results
            out = []
            for args in calls:
                out.append(await session.call_tool("gated", args))
            return out

    return asyncio.run(go()), asked


def _one(content_or_result, klass=TIER1, label="A"):
    ans = content_or_result
    if not isinstance(ans, mt.ElicitResult):
        ans = _raw("accept", ans)
    res, asked = run_calls([{"label": label, "action_class": klass}],
                           lambda p: ans)
    return label in RAN, asked, res


BOTH = pytest.mark.parametrize("klass", [TIER1, TIER2])

# ---------------------------------------------------------------- controls


@BOTH
def test_control_literal_allow_runs(klass):
    ran, asked, _ = _one({"decision": "Allow"}, klass)
    assert ran and len(asked) == 1


@BOTH
def test_extra_unknown_fields_with_literal_allow_still_run(klass):
    """Recorded behaviour: an explicit literal Allow plus junk fields counts.
    The yes-rule reads only the decision field; extra keys are not an
    auto-accept signature on any host studied."""
    ran, _, _ = _one({"decision": "Allow", "zzz": "x", "allow": False}, klass)
    assert ran


# ----------------------------------------------------- near-miss yes values

NEAR_MISSES = [
    {"decision": "allow"}, {"decision": "ALLOW"}, {"decision": " Allow"},
    {"decision": "Allow "}, {"decision": "Allow\n"}, {"decision": "Аllow"},
    {"decision": "Allow​"}, {"decision": "Allow."}, {"decision": "Yes"},
    {"decision": "Allow, Don't allow"}, {"decision": ["Allow"]},
    {"decision": ["Don't allow", "Allow"]}, {"decision": True},
    {"decision": 1}, {"decision": 1.0}, {"decision": None},
    {"Decision": "Allow"}, {"decision ": "Allow"}, {"allow": True},
    {"allow": "Allow"}, {"remember_30_minutes": True}, {},
    {"decision": "Don't allow"}, {"decision": "Don't allow",
                                  "remember_30_minutes": True},
]


@BOTH
@pytest.mark.parametrize("content", NEAR_MISSES, ids=repr)
def test_near_miss_accept_never_runs(klass, content):
    ran, asked, _ = _one(content, klass)
    assert not ran
    assert consent.grants() == []


@BOTH
@pytest.mark.parametrize("content", [None])
def test_accept_with_no_content_never_runs(klass, content):
    ran, _, _ = _one(_raw("accept", None), klass)
    assert not ran


@BOTH
@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_decline_or_cancel_carrying_allow_never_runs(klass, action):
    ran, _, _ = _one(_raw(action, {"decision": "Allow",
                                   "remember_30_minutes": True}), klass)
    assert not ran and consent.grants() == []


# ------------------------------------------------- malformed wire content


@BOTH
@pytest.mark.parametrize("content", [
    {"decision": {"value": "Allow"}},
    {"decision": {"const": "Allow"}},
    {"decision": [{"x": "Allow"}]},
    {"decision": [1, "Allow"]},
], ids=repr)
def test_object_or_mixed_values_on_the_wire_never_run(klass, content):
    """Content the ElicitResult type forbids, sent anyway (pydantic skipped
    on the host side). The server must not run."""
    ran, _, _ = _one(_raw("accept", content, construct=True), klass)
    assert not ran


@BOTH
@pytest.mark.parametrize("action", ["ACCEPT", "Accept", "allow", "yes", ""])
def test_unknown_action_values_never_run(klass, action):
    ran, _, _ = _one(_raw(action, {"decision": "Allow"}, construct=True),
                     klass)
    assert not ran


@BOTH
def test_host_returning_jsonrpc_error_never_runs(klass):
    ans = mt.ErrorData(code=-32602, message="mode not supported")
    res, _ = run_calls([{"label": "A", "action_class": klass}], lambda p: ans)
    assert "A" not in RAN
    assert consent.unattended()        # no_channel path


@BOTH
def test_host_callback_raising_never_runs(klass):
    def boom(p):
        raise RuntimeError("host blew up")
    res, _ = run_calls([{"label": "A", "action_class": klass}], boom)
    assert "A" not in RAN


# ------------------------------------------------------ simulated hosts


def _props(p):
    return (p.requestedSchema or {}).get("properties") or {}


@BOTH
def test_first_enum_preselect_host_never_runs(klass):
    def host(p):
        return _raw("accept", {k: v["enum"][0] for k, v in _props(p).items()
                               if "enum" in v})
    ran, _, _ = _one_host(host, klass)
    assert not ran


@BOTH
def test_defaults_echo_host_never_runs(klass):
    def host(p):
        return _raw("accept", {k: v["default"] for k, v in _props(p).items()
                               if "default" in v})
    ran, _, _ = _one_host(host, klass)
    assert not ran


@BOTH
def test_const_echo_host_never_runs(klass):
    def host(p):
        out = {}
        for k, v in _props(p).items():
            if "const" in v:
                out[k] = v["const"]
            for opt in v.get("oneOf", []) + v.get("anyOf", []):
                if "const" in opt:
                    out[k] = opt["const"]
                    break
        return _raw("accept", out)
    ran, _, _ = _one_host(host, klass)
    assert not ran


@BOTH
def test_fill_required_first_option_and_tick_every_box_host(klass):
    def host(p):
        out = {}
        for k, v in _props(p).items():
            if v.get("type") == "boolean":
                out[k] = True
            elif "enum" in v:
                out[k] = v["enum"][0]
        return _raw("accept", out)
    ran, _, _ = _one_host(host, klass)
    assert not ran and consent.grants() == []


@BOTH
def test_codex_full_access_host_declines_and_session_goes_unattended(klass):
    """accept {} only when properties is empty, else decline (instantly)."""
    def host(p):
        if not _props(p):
            return _raw("accept", {})
        return _raw("decline")
    res, asked = run_calls([{"label": x, "action_class": klass}
                            for x in ("A", "B", "C")], host)
    assert RAN == []
    assert len(asked) == 2                 # third refused without a prompt
    assert consent.unattended()


@BOTH
def test_last_enum_preselect_host_is_the_accepted_residual(klass):
    """INFORMATIONAL: a hypothetical host that silently picks the LAST
    option would redeem. No studied host does; recorded so the residual is
    explicit, not a pass/fail on the fix."""
    def host(p):
        return _raw("accept", {k: v["enum"][-1] for k, v in _props(p).items()
                               if "enum" in v})
    ran, _, _ = _one_host(host, klass)
    assert ran


def _one_host(host, klass, label="A"):
    res, asked = run_calls([{"label": label, "action_class": klass}], host)
    return label in RAN, asked, res


# ------------------------------------------------------------ the schema


@BOTH
def test_wire_schema_matches_2025_11_25_restricted_subset(klass):
    _, asked, _ = _one({"decision": "Don't allow"}, klass)
    p = asked[0]
    s = p.requestedSchema
    assert set(s) == {"type", "properties", "required"}
    assert s["type"] == "object" and s["required"] == ["decision"]
    d = s["properties"]["decision"]
    assert set(d) <= {"type", "title", "description", "enum", "default"}
    assert d["type"] == "string" and "default" not in d
    assert d["enum"] == ["Don't allow", "Allow"]
    if klass == TIER2:
        assert set(s["properties"]) == {"decision"}
    else:
        r = s["properties"]["remember_30_minutes"]
        assert set(r) <= {"type", "title", "description", "default"}
        assert r["type"] == "boolean" and r["default"] is False
    assert getattr(p, "mode", "form") == "form"


# -------------------------------------------------------------- remember


def test_tier1_allow_with_remember_true_mints_one_grant_then_clears():
    host_calls = []

    def host(p):
        host_calls.append(p)
        return _raw("accept", {"decision": "Allow",
                               "remember_30_minutes": True})
    res, asked = run_calls([{"label": "A"}, {"label": "B"}], host)
    assert RAN == ["A", "B"]
    assert len(asked) == 1                  # B cleared by the grant
    assert [g["action_class"] for g in consent.grants()] == [TIER1]
    assert consent.grants()[0]["origin"] == ORIGIN


@pytest.mark.parametrize("remember", ["true", 1, "True", ["true"], None, 1.0],
                         ids=repr)
def test_tier1_remember_must_be_json_true(remember):
    ran, _, _ = _one({"decision": "Allow", "remember_30_minutes": remember})
    assert ran and consent.grants() == []


def test_tier2_never_remembers_even_when_the_host_sends_the_box():
    def host(p):
        return _raw("accept", {"decision": "Allow",
                               "remember_30_minutes": True})
    res, asked = run_calls([{"label": "A", "action_class": TIER2},
                            {"label": "B", "action_class": TIER2}], host)
    assert RAN == ["A", "B"]
    assert len(asked) == 2                  # asked every time
    assert consent.grants() == []


def test_remember_off_drops_the_box_and_mints_nothing(monkeypatch):
    monkeypatch.setenv("KS4WEB_REMEMBER", "off")
    ran, asked, _ = _one({"decision": "Allow", "remember_30_minutes": True})
    assert ran
    assert set(asked[0].requestedSchema["properties"]) == {"decision"}
    assert consent.grants() == []


def test_grant_does_not_cross_origin():
    def host(p):
        return _raw("accept", {"decision": "Allow",
                               "remember_30_minutes": True})
    res, asked = run_calls([{"label": "A"},
                            {"label": "B", "url": "https://b.example/x"}],
                           host)
    assert RAN == ["A", "B"] and len(asked) == 2


# ---------------------------------------------------------------- replay


def test_an_old_allow_is_not_reused_for_a_new_gate():
    answers = iter([_raw("accept", {"decision": "Allow"}),
                    _raw("decline")])
    res, asked = run_calls([{"label": "A"}, {"label": "B"}],
                           lambda p: next(answers))
    assert RAN == ["A"] and len(asked) == 2


def test_redeemed_gate_cannot_be_redeemed_again_and_is_not_reasked():
    async def go():
        from kitchensink4web.errors import ConfirmationRequired
        app = FastMCP("replay")
        out = {}

        @app.tool
        async def t() -> dict:
            try:
                gates.ENGINE.ask(TIER1, tool="click", session="s", page="p",
                                 target={"name": "A"}, summary="x",
                                 origin=ORIGIN)
            except ConfirmationRequired as exc:
                first = await confirm.attempt(exc)
                second = await confirm.attempt(exc)
                out["first"] = first is not None
                out["second"] = second is not None
            return {}

        asked = []

        async def cb(ctx, p):
            asked.append(p)
            return _raw("accept", {"decision": "Allow"})

        async with FastMCPTransport(app).connect_session(
                elicitation_callback=cb) as s:
            await s.initialize()
            await s.call_tool("t", {})
        return out, asked

    out, asked = asyncio.run(go())
    assert out == {"first": True, "second": False}
    assert len(asked) == 1


# ------------------------------------------------------------ concurrency


def test_concurrent_gates_bind_each_answer_to_its_own_gate():
    both_pending = asyncio.Event

    seen = []

    async def host(p):
        seen.append(p.message)
        # hold until both prompts are out, so both gates are pending at once
        for _ in range(200):
            if len(seen) >= 2:
                break
            await asyncio.sleep(0.01)
        if "press A" in p.message:
            await asyncio.sleep(0.05)
            return _raw("accept", {"decision": "Allow"})
        return _raw("accept", {"decision": "Don't allow"})

    res, asked = run_calls([{"label": "A"}, {"label": "B"}], host,
                           concurrent=True)
    assert len(seen) == 2
    assert RAN == ["A"]


def test_concurrent_allows_each_run_against_their_own_target():
    seen = []

    async def host(p):
        seen.append(p.message)
        for _ in range(200):
            if len(seen) >= 2:
                break
            await asyncio.sleep(0.01)
        if "press B" in p.message:
            await asyncio.sleep(0.05)
        return _raw("accept", {"decision": "Allow"})

    res, asked = run_calls([{"label": "A"}, {"label": "B"}], host,
                           concurrent=True)
    assert sorted(RAN) == ["A", "B"]
    confirmed = sorted(_payload(r).get("confirmed") for r in res)
    assert confirmed == ["A", "B"]


def _payload(r) -> dict:
    import json
    for c in r.content:
        try:
            body = json.loads(getattr(c, "text", "") or "{}")
        except ValueError:
            continue
        if isinstance(body, dict):
            if "confirmed" in body:
                return body
            return body.get("result", body)
    return {}


# ----------------------------------------------------------------- expiry


def test_gate_expiring_while_the_human_reads_does_not_run():
    def host(p):
        for g in gates.ENGINE._pending.values():
            g.created -= gates.GATE_TTL_S + 1
        return _raw("accept", {"decision": "Allow",
                               "remember_30_minutes": True})
    ran, _, _ = _one_host(host, TIER1)
    assert not ran
    assert consent.grants() == []


def test_already_expired_gate_is_it_put_to_a_human():
    """Checks the claim 'expired gates are not put to a human'
    (the confirm.attempt comment)."""
    async def go():
        from kitchensink4web.errors import ConfirmationRequired
        app = FastMCP("expired")
        out = {}

        @app.tool
        async def t() -> dict:
            try:
                gates.ENGINE.ask(TIER1, tool="click", session="s", page="p",
                                 target={"name": "A"}, summary="x",
                                 origin=ORIGIN)
            except ConfirmationRequired as exc:
                for g in gates.ENGINE._pending.values():
                    g.created -= gates.GATE_TTL_S + 1
                out["granted"] = (await confirm.attempt(exc)) is not None
            return {}

        asked = []

        async def cb(ctx, p):
            asked.append(p)
            return _raw("accept", {"decision": "Allow"})

        async with FastMCPTransport(app).connect_session(
                elicitation_callback=cb) as s:
            await s.initialize()
            await s.call_tool("t", {})
        return out, asked

    out, asked = asyncio.run(go())
    assert out["granted"] is False
    # The claim says no prompt. Record what actually happens:
    assert len(asked) == 0, ("an EXPIRED (not yet swept) gate was still put "
                             "to the human; peek_pending does not check TTL")


def test_elicit_timeout_never_runs_and_a_late_allow_is_dropped(monkeypatch):
    """The host answers Allow AFTER the server stopped waiting. The late
    JSON-RPC response carries an id the server no longer knows; nothing may
    run, and a later gate is not satisfied by it either."""
    monkeypatch.setattr(confirm, "ELICIT_TIMEOUT_S", 0.3)
    answers = []

    async def host(p):
        answers.append(p)
        if len(answers) == 1:
            await asyncio.sleep(1.0)
            return _raw("accept", {"decision": "Allow"})
        return _raw("decline")

    async def go():
        async def cb(ctx, p):
            return await host(p)
        async with FastMCPTransport(_app()).connect_session(
                elicitation_callback=cb) as s:
            await s.initialize()
            await s.call_tool("gated", {"label": "A"})
            await asyncio.sleep(1.5)       # the late Allow lands now
            await s.call_tool("gated", {"label": "B"})
            await asyncio.sleep(0.2)

    asyncio.run(go())
    assert RAN == []
    assert len(answers) == 2


# ------------------------------------------------- no elicitation channel


@BOTH
def test_client_without_elicitation_is_refused_without_a_prompt(klass):
    res, asked = run_calls([{"label": "A", "action_class": klass},
                            {"label": "B", "action_class": klass}], None)
    assert RAN == []
    assert consent.unattended()
    assert "advertises no confirmation channel" in \
        (consent.unattended_reason() or "")
    second = res[1]
    text = " ".join(getattr(c, "text", "") for c in second.content)
    assert "No human is answering" in text and "Nothing was done" in text


# ------------------------------------------------------- unattended signal


def test_instant_unanswered_accepts_mark_unattended_and_a_slow_allow_clears():
    ran, _, _ = _one({})
    ran2, _, _ = _one({"remember_30_minutes": False}, label="B")
    assert not ran and not ran2
    assert consent.unattended()
    consent._reset_runtime_state()

    async def slow(p):
        await asyncio.sleep(0.6)
        return _raw("accept", {"decision": "Allow"})
    ran3, _, _ = _one_host(slow, TIER1, label="C")
    assert ran3 and not consent.unattended()
