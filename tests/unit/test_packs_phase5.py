"""Phase 5's surface half: the packs register conformantly, hide their
mutating tools under read-only identically to the lite core, and the built
surface matches the designed one exactly.

The runtime behavior of each pack (table extraction, media-type
correctness, console dedup, the download lifecycle) is proven against a
real browser in tests/browser/test_phase5_packs.py; this file is the pure
registration-and-classification battery that needs no browser.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastmcp import Client

from kitchensink4web import packs, server
from kitchensink4web.policy import readonly

PACK_MODULES = {
    "extract": "kitchensink4web.ops.extract",
    "capture": "kitchensink4web.ops.capture",
    "network": "kitchensink4web.ops.net",
    "storage": "kitchensink4web.ops.storage",
    "files": "kitchensink4web.ops.files",
    "diagnostics": "kitchensink4web.ops.diag",
    "workflows": "kitchensink4web.ops.workflows",
}


def test_every_module_roster_matches_the_design_table():
    """The designed surface (packs.PLANNED_MEMBERS) and the built surface
    (each module's TOOLS) cannot drift: they are asserted equal here, so a
    tool added to a module without updating the design table, or the
    reverse, fails immediately."""
    for pack, modname in PACK_MODULES.items():
        module = importlib.import_module(modname)
        built = {fn.__name__ for fn in module.TOOLS}
        designed = set(packs.PLANNED_MEMBERS[pack])
        assert built == designed, (
            f"pack {pack!r}: built {sorted(built)} != designed "
            f"{sorted(designed)}")


def test_full_surface_is_forty_six_tools(launch):
    """Forty until 2026-09-06, when find_and_act joined the lite core;
    forty-two later the same day, when handle_dialog did;
    forty-three when get_article joined the extract pack;
    forty-five after the small-parts wave added read_pages to
    extract and manage_clipboard to files; and forty-six on 2026-09-08,
    when `monitor` joined the lite core."""
    state = launch(cli_packs=packs.pack_names(), read_only=False)
    assert len(state["registered"]) == 46
    assert len(set(state["registered"])) == 46


def test_full_surface_under_read_only_hides_every_mutating_pack_tool(launch):
    """The read-only invariant extended to the packs (the brief's standing
    ruling): a read-only grade hides mutating pack tools by ABSENCE exactly
    as it hides the lite mutating tools. Nothing to allowlist, and nothing
    for an injected page to reach."""
    state = launch(cli_packs=packs.pack_names(), read_only="browse")
    listed = set(state["registered"])
    assert not (listed & readonly.MUTATING), (
        f"mutating tools present under read-only: "
        f"{sorted(listed & readonly.MUTATING)}")
    # The read pack tools survive.
    for name in ("get_table", "get_metadata", "take_screenshot",
                 "list_requests", "list_console", "export_har"):
        assert name in listed, name
    # The mutating pack tools are gone.
    for name in ("set_routing", "manage_cookies", "download", "upload_file",
                 "evaluate_script", "save_workflow", "emulate"):
        assert name not in listed, name


def test_read_only_absence_holds_over_a_real_client_with_packs(launch):
    launch(cli_packs=packs.pack_names(), read_only="browse")

    async def run():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    listed = asyncio.run(run())
    assert not (listed & readonly.MUTATING)
    assert "get_table" in listed


def test_every_pack_tool_is_classified(launch):
    """A pack tool nobody classified would register in read-only mode by
    accident. Every one must answer is_mutating cleanly."""
    launch(cli_packs=packs.pack_names(), read_only=False)
    for pack, modname in PACK_MODULES.items():
        module = importlib.import_module(modname)
        for fn in module.TOOLS:
            assert isinstance(readonly.is_mutating(fn.__name__), bool), \
                fn.__name__


def test_pack_tools_carry_read_only_hint_correctly(launch, live_tools):
    launch(cli_packs=packs.pack_names(), read_only=False)
    tools = live_tools()
    for name in ("get_table", "list_requests", "list_console"):
        assert tools[name].annotations.readOnlyHint is True, name
    for name in ("set_routing", "download", "evaluate_script"):
        assert tools[name].annotations.readOnlyHint is False, name


def test_unloaded_pack_call_is_guided_not_bare(launch):
    """Discoverability rule 2 over the middleware: a call to a tool that
    exists in the design but lives in an unloaded pack names the pack and
    the launch flag, never the bare framework 'Unknown tool' string."""
    launch(read_only=False)  # lite only, no packs

    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool("get_table", {"page": "p1"},
                                     raise_on_error=False)

    result = run_sync(run())
    assert result.is_error is True
    hint = result.structured_content["error"]["hint"]
    assert "--packs extract" in hint


def run_sync(coro):
    return asyncio.run(coro)


def test_image_sniff_derives_type_from_bytes_and_refuses_garbage():
    """The media-type chokepoint (playwright-mcp #1211): format and media
    type come from the bytes, so they can never disagree, and bytes that are
    neither PNG nor JPEG are refused rather than mislabeled."""
    from kitchensink4web.ops import common
    from kitchensink4web.errors import UnsupportedContent

    assert common.sniff_image(b"\x89PNG\r\n\x1a\n rest") == ("png", "image/png")
    assert common.sniff_image(b"\xff\xd8\xff\xe0 rest") == ("jpeg",
                                                            "image/jpeg")
    with pytest.raises(UnsupportedContent):
        common.sniff_image(b"GIF89a not supported")
    with pytest.raises(UnsupportedContent):
        common.sniff_image(b"<html>an api 400 error page, not an image</html>")


def test_pack_docstrings_have_no_em_dashes_and_say_what_returns(launch,
                                                                live_tools):
    """The docstring rules bind pack tools identically to lite ones."""
    launch(cli_packs=packs.pack_names(), read_only=False)
    tools = live_tools()
    pack_names = {n for members in packs.PLANNED_MEMBERS.values()
                  for n in members}
    for name in pack_names:
        tool = tools[name]
        desc = tool.description or ""
        assert "—" not in desc, f"{name} has an em dash"
        assert len(desc) <= 2048, f"{name} would be truncated"
        low = desc.lower()
        assert any(w in low for w in ("return", "reports", "carries",
                                      "names", "says", "state", "get back")), \
            f"{name} never says what it returns"
