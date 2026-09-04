"""The registration surface: the lite roster, launch-time packs, read-only
by absence, and the fact that every stub refuses honestly.

This is the Phase 0 gate's surface half. The roster test is a literal list
on purpose: it is the arithmetic the design review flagged as tight, so the
two membership decisions (request_handoff folded, emulate dropped) are
asserted here rather than left to a comment.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from kitchensink4web import envelope, packs, server
from kitchensink4web.errors import BadParams
from kitchensink4web.policy import readonly

# DESIGN 2.1, with the review's arithmetic note applied.
LITE_ROSTER = {
    "get_page_view", "find_elements", "get_text", "navigate", "click",
    "type_text", "fill_form", "press_keys", "scroll", "wait_for",
    "manage_tabs", "manage_session", "get_audit", "get_workflows",
}


def test_lite_roster_is_exactly_the_design(launch):
    state = launch()
    assert set(state["registered"]) == LITE_ROSTER
    assert len(LITE_ROSTER) == 14


def test_request_handoff_folded_and_emulate_dropped(launch, live_tools):
    """The two membership decisions from the design review's arithmetic
    note. request_handoff is an action of manage_session, not a tool;
    emulate belongs to the capture pack, not to lite."""
    launch()
    listed = set(live_tools())
    assert "request_handoff" not in listed
    assert "emulate" not in listed
    assert "manage_session" in listed
    assert "emulate" in packs.PLANNED_MEMBERS["capture"]


def test_lists_over_an_in_process_client(launch):
    """The surface is reachable over a real MCP client, not just in the
    registry."""
    launch()

    async def run():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    assert asyncio.run(run()) == LITE_ROSTER


def test_every_tool_is_packed(launch, live_tools):
    launch()
    listed = set(live_tools())
    packed = {n for members in packs.tool_names().values() for n in members}
    assert listed <= packed, f"unpacked: {sorted(listed - packed)}"


def test_reads_are_marked_read_only_hint(launch, live_tools):
    """Free and inherited: a browser tool without readOnlyHint=true is
    serialized by the client and cannot run in parallel."""
    launch()
    tools = live_tools()
    for name in ("get_page_view", "find_elements", "get_text", "get_audit"):
        assert tools[name].annotations.readOnlyHint is True
    for name in ("click", "type_text", "fill_form"):
        assert tools[name].annotations.readOnlyHint is False


def test_read_only_mode_registers_no_mutating_tools(launch):
    """DESIGN 5.2, the strongest differentiator: the mutating tools are
    ABSENT from tools/list, not merely refused. Nothing to allowlist and
    nothing for an injected instruction to reach for."""
    state = launch(read_only="browse")
    listed = set(state["registered"])
    for name in ("click", "type_text", "fill_form", "press_keys"):
        assert name not in listed
    for name in ("get_page_view", "find_elements", "get_text", "navigate",
                 "scroll", "get_audit"):
        assert name in listed


def test_read_only_absence_is_visible_over_the_client(launch):
    launch(read_only="strict")

    async def run():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    listed = asyncio.run(run())
    assert not (listed & readonly.MUTATING)


def test_read_only_grade_typo_fails_loudly():
    """Never degrade silently. A misspelled grade refuses to start rather
    than quietly falling back to a weaker mode."""
    with pytest.raises(BadParams):
        readonly.parse_grade("stricct")
    assert readonly.parse_grade(True) == "browse"
    assert readonly.parse_grade(None) is None
    assert readonly.parse_grade("strict") == "strict"


def test_every_registered_tool_is_classified(launch, live_tools):
    """A tool nobody classified would be registered in read-only mode by
    accident, which would make the headline claim false."""
    launch()
    for name in live_tools():
        assert isinstance(readonly.is_mutating(name), bool)
    with pytest.raises(BadParams):
        readonly.is_mutating("a_tool_nobody_classified")


def test_packs_are_launch_time_and_typos_fail_loudly(launch):
    assert packs.resolve_startup_packs(mode="lite") == []
    assert packs.resolve_startup_packs(mode="extract,files") == [
        "extract", "files"]
    assert packs.resolve_startup_packs(mode="full") == sorted(
        packs.PACK_SUMMARIES)
    with pytest.raises(BadParams):
        packs.resolve_startup_packs(mode="extrct")


def test_no_runtime_pack_toggle_exists(launch, live_tools):
    """DESIGN 7.2, a conformance decision: KS4Web does not ship the family's
    enable_tools pattern, because varying the tool set as a side effect of a
    request is what MCP 2026-07-28 forbids."""
    launch()
    listed = set(live_tools())
    assert "enable_tools" not in listed
    assert "disable_tools" not in listed
    assert not hasattr(packs, "enable")
    assert not hasattr(packs, "disable")


def test_pack_menu_names_the_launch_flag(launch):
    """Discoverability rule 2, adapted: there is no enable call to name, so
    the menu names the flag and the env var instead (DESIGN 7.4)."""
    launch()
    menu = packs.menu()
    assert set(menu) == set(packs.PACK_SUMMARIES)
    for pack, entry in menu.items():
        assert entry["launch_flag"] == f"--packs {pack}"
        assert entry["env"] == f"KS4WEB_MODE={pack}"
        assert entry["summary"]


def test_pack_hint_names_flag_and_env(launch):
    """A refusal that points at a pack the caller does not have must say how
    to get it, and 'restart with this flag' is the honest instruction here."""
    launch()
    exc = BadParams("that needs a table read")
    exc.hint_tools = ("get_table",)
    hint = envelope.refusal(exc)["error"]["hint"]
    assert "--packs extract" in hint
    assert "KS4WEB_MODE=extract" in hint
    assert "LAUNCH" in hint


def test_stubs_refuse_with_not_implemented(launch):
    """Phase 0 has no engine. Every stub says so in the envelope rather than
    returning plausible output, because a tool that reports success without
    doing anything is the exact disease this product argues against."""
    launch()

    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool(
                "get_page_view", {"page": "p1"}, raise_on_error=False)

    result = asyncio.run(run())
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "NOT_IMPLEMENTED"
    assert "Phase 2" in result.structured_content["error"]["message"]


def test_no_browser_dependency_is_imported():
    """Phase 0's gate says "no browser needed yet" and this proves it: the
    whole package imports with playwright absent from the environment."""
    import sys
    assert "playwright" not in sys.modules
