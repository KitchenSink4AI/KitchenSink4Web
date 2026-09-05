"""THE read-only invariant (author ruling, 2026-09-05): the agent can never
flip read-only mode in-session. No tool, no argument, no MRTR path.

Four halves, because the invariant is provable only when every route is
closed:

1. STATIC: the only call site of `readonly.apply()` in the shipped tree is
   server startup. A second caller is a runtime toggle wearing a disguise.
2. SURFACE: no registered tool schema carries a parameter that names the
   mode, so there is no argument to reach for.
3. RUNTIME: every flip-shaped call an injected page could name (the
   corpus C `disable_gates.html` list, verbatim) refuses, and afterward the
   grade and the tool set are byte-identical.
4. DEFAULT: the launch default is ONE constant, both values fully built,
   and an explicit env value beats the constant in both directions, which
   is what the .mcpb "Allow this server to click and type" checkbox maps to.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from kitchensink4web import server
from kitchensink4web.policy import gates, readonly

SRC = Path(server.__file__).resolve().parent


# -------------------------------------------------------------- 1. static


def test_apply_is_called_only_from_startup():
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in ("policy/readonly.py",):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "apply"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "readonly"):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == ["server.py:141"] or (
        len(offenders) == 1 and offenders[0].startswith("server.py")), (
        f"readonly.apply() is callable from startup ONLY (server.configure); "
        f"found: {offenders}")


def test_no_module_assigns_the_grade_from_outside():
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel == "policy/readonly.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) \
                    else [node.target]
                for target in targets:
                    if (isinstance(target, ast.Attribute)
                            and target.attr in ("_grade", "DEFAULT_GRADE")):
                        offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"the grade is written only inside policy/readonly.py: {offenders}")


# ------------------------------------------------------------- 2. surface


def test_no_tool_schema_exposes_a_mode_parameter(launch, live_tools):
    launch()
    for name, tool in live_tools().items():
        schema = json.dumps(tool.parameters or {}).lower()
        for needle in ("read_only", "readonly", "read-only"):
            assert needle not in schema, (
                f"{name} exposes {needle!r} in its schema; the mode is a "
                f"launch-time property with NO in-session argument")


# ------------------------------------------------------------- 3. runtime


def _call(tool: str, args: dict):
    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool(tool, args, raise_on_error=False)
    return asyncio.run(run())


def _surface():
    async def run():
        async with Client(server.mcp) as c:
            return sorted(t.name for t in await c.list_tools())
    return asyncio.run(run())


#: The corpus C `disable_gates.html` instruction list, mechanized. Every
#: entry must refuse, and none may move the grade or the tool set.
FLIP_ATTEMPTS = (
    ("manage_session", {"action": "disable_safety"}),
    ("manage_session", {"action": "set_read_only"}),
    ("manage_session", {"action": "read_only"}),
    ("manage_session", {"action": "unlock", "reason": "KS4WEB_READ_ONLY=0"}),
    ("get_workflows", {"topic": "disable read-only"}),
)


def test_no_mechanical_path_flips_the_mode_in_session(launch):
    launch(read_only="browse")
    assert readonly.grade() == "browse"
    before = _surface()
    assert not (set(before) & readonly.MUTATING)

    for tool, args in FLIP_ATTEMPTS:
        result = _call(tool, args)
        assert result.is_error is True, (tool, args)
    # The tools an injected page would name do not even exist to call.
    for ghost in ("enable_tools", "disable_tools", "set_read_only",
                  "configure"):
        assert ghost not in before

    assert readonly.grade() == "browse"
    assert _surface() == before


def test_the_mrtr_path_cannot_flip_it_either(launch):
    """No gate class touches policy (test_gates has the table property);
    here the whole redeem/verify cycle runs and the grade never moves."""
    launch(read_only="browse")
    engine = gates.GateEngine()
    with pytest.raises(Exception) as exc:
        engine.ask("budget_reset", tool="manage_session", session="s1",
                   page=None, target=None, summary="reset")
    grant = engine.redeem(exc.value.detail["requestState"], {"allow": True})
    engine.verify_execute(grant, {})
    assert readonly.grade() == "browse"


# ------------------------------------------- 5. the guided refusal teaches
#                                                the human, offers the agent
#                                                nothing redeemable

def test_the_unlock_teaching_hands_the_agent_nothing_callable():
    """The field-test blocking fix added an UNLOCK teaching to every mode
    surface. It must teach the HUMAN a launch-time action and never hand the
    AGENT anything it can call, redeem, or echo to flip the mode in-session:
    a describe() that offered a tool name or a token would be a bypass
    wearing an instruction's clothes."""
    text = readonly.UNLOCK_TEACHING.lower()
    # It names a human, launch-time action.
    assert "restart" in text or "launch" in text
    assert "human" in text or "settings" in text or "checkbox" in text \
        or "tick" in text
    # It never offers an in-session route: no tool invocation the agent
    # could issue to flip the mode, and no redeemable confirmation hook.
    for forbidden in ("manage_session(action", "(action=", "redeem",
                      "requeststate", "elicitation/create", "inputrequest"):
        assert forbidden not in text, (
            f"the unlock teaching names {forbidden!r}, which points the "
            f"agent at an in-session route rather than a human restart")


def test_the_guided_absent_tool_refusal_is_not_a_bypass_vector(launch):
    """A forced call to an absent mutating tool now returns a GUIDED refusal
    (grade, why, human unlock) instead of the bare framework string. That
    message must teach the human and stay non-redeemable: it names no tool
    the agent can call to flip the mode and carries no confirmation token."""
    launch(read_only="browse")

    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool("type_text",
                                     {"page": "p1",
                                      "location": {"ref": "e1"},
                                      "text": "x"},
                                     raise_on_error=False)

    result = asyncio.run(run())
    assert result.is_error is True
    err = result.structured_content["error"]
    assert err["code"] == "READ_ONLY_MODE"
    blob = json.dumps(err).lower()
    # Teaches the state.
    assert "read-only" in blob
    # Teaches the human unlock, offers the agent nothing redeemable.
    assert "restart" in blob or "settings" in blob or "tick" in blob
    for forbidden in ("requeststate", "redeem", "inputrequest",
                      "elicitation/create", "allow this action now"):
        assert forbidden not in blob, (
            f"the guided refusal carries {forbidden!r}, a redeemable hook")
    # The mode did not move, and the tool is still absent.
    assert readonly.grade() == "browse"

    async def surface():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    assert "type_text" not in asyncio.run(surface())


# ------------------------------------------------------------- 4. default


def test_both_defaults_are_built_and_one_constant_switches_them(
        launch, monkeypatch):
    monkeypatch.delenv("KS4WEB_READ_ONLY", raising=False)

    monkeypatch.setattr(readonly, "DEFAULT_GRADE", None)
    state = launch()
    assert state["read_only"] is None
    assert "click" in state["registered"]

    monkeypatch.setattr(readonly, "DEFAULT_GRADE", "browse")
    state = launch()
    assert state["read_only"] == "browse"
    assert "click" not in state["registered"]


def test_explicit_env_beats_the_constant_in_both_directions(
        launch, monkeypatch):
    """The unlock UX: the .mcpb user_config checkbox maps to the env var,
    so an explicit value must win under either shipped default."""
    monkeypatch.setattr(readonly, "DEFAULT_GRADE", "browse")
    monkeypatch.setenv("KS4WEB_READ_ONLY", "0")  # checkbox ON: allow acting
    state = server.configure()
    assert state["read_only"] is None
    assert "click" in state["registered"]

    monkeypatch.setattr(readonly, "DEFAULT_GRADE", None)
    monkeypatch.setenv("KS4WEB_READ_ONLY", "browse")  # checkbox OFF
    state = server.configure()
    assert state["read_only"] == "browse"
    assert "click" not in state["registered"]
    server.configure(read_only=False)
