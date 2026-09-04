"""Shared fixtures.

Every test that inspects the registered surface needs a KNOWN launch shape,
because registration is launch-time and therefore process-global. `launch`
tears the surface down, applies the shape asked for, and hands back the
resulting state, then restores the default lite surface afterward so a test
that never calls it still sees something sane.

`live_tools` returns the tool objects FastMCP actually holds, which is the
only honest source for any count or cost: the pack registry tracks membership
by name and deliberately keeps no second copy of the objects.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web import server


@pytest.fixture
def launch(monkeypatch):
    """Configure the server under a named launch shape and return the state.

    Usage:  state = launch()
            state = launch(read_only="browse")
            state = launch(cli_packs=["extract"])
    """
    monkeypatch.delenv("KS4WEB_MODE", raising=False)
    monkeypatch.delenv("KS4WEB_READ_ONLY", raising=False)

    yield server.configure

    server.configure()


@pytest.fixture
def live_tools():
    """{name: Tool} as FastMCP currently holds them."""

    def _get():
        return {t.name: t for t in asyncio.run(server.mcp.list_tools())}

    return _get
