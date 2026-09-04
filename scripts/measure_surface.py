"""Measure the real tool surface: counts and approximate token bills per pack.

Ported from word-mcp / KS4PPT. Imports the server, registers the launch
selection, and prints from the LIVE registry. Every published figure comes
from running this, never from hand-math (house rule, inherited).

Two KS4Web-specific things this reports that the siblings' version does not:

- the READ-ONLY surface alongside the full one, since "no mutating tools are
  registered" is a claim that should be measurable rather than asserted
- the PLANNED-but-unregistered packs, so the gap between the design's
  surface and the built one is visible at every phase rather than
  discovered at Phase 7

Run:  .venv/Scripts/python.exe -X utf8 scripts/measure_surface.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kitchensink4web import packs, server  # noqa: E402


def _fmt(n: int) -> str:
    return f"{n / 1000:.2f}k"


def _measure(label: str, **kw) -> None:
    """Fresh registration under one launch shape, reported."""
    server.configure(**kw)
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    cost = sum(packs.approx_tokens(t) for t in tools.values())
    print(f"\n{label}")
    print("-" * 56)
    print(f"{'pack':<16} {'tools':>5} {'~tokens':>9}")
    for pack, members in sorted(packs.tool_names().items()):
        print(f"{pack:<16} {len(members):>5} "
              f"{_fmt(packs.pack_cost(pack, tools)):>9}")
    print(f"{'TOTAL':<16} {len(tools):>5} {_fmt(cost):>9}")
    worst = max(
        ((n, packs.approx_tokens(t)) for n, t in tools.items()),
        key=lambda kv: kv[1], default=("none", 0),
    )
    schemas = {
        n: round(len(json.dumps(t.parameters or {})) / 4)
        for n, t in tools.items()
    }
    worst_schema = max(schemas.items(), key=lambda kv: kv[1],
                       default=("none", 0))
    print(f"largest tool total : {worst[0]} (~{worst[1]} tok)")
    print(f"largest schema     : {worst_schema[0]} "
          f"(~{worst_schema[1]} tok, ceiling 250)")
    descs = sum(len(t.description or "") for t in tools.values())
    print(f"split              : ~{_fmt(round(descs / 4))} descriptions + "
          f"~{_fmt(round(sum(len(json.dumps(t.parameters or {})) for t in tools.values()) / 4))} schemas")


def main() -> None:
    print("KS4Web surface report. Targets (DESIGN 3.2): lite under 1.5k, "
          "full surface under 4k, largest single schema under 250.")
    _measure("LITE (no flags)")
    _measure("LITE, READ-ONLY 'browse'", read_only="browse")
    _measure("FULL (--packs full)", cli_packs=packs.pack_names())

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    planned = packs.surface_report(tools)["planned_unregistered"]
    outstanding = {p: n for p, n in planned.items() if n}
    if outstanding:
        print("\nPLANNED, NOT YET REGISTERED (design surface minus built "
              "surface)")
        print("-" * 56)
        for pack, names in sorted(outstanding.items()):
            print(f"{pack:<16} {len(names):>5}  {', '.join(names)}")
    print("\nNote: this estimator is chars/4 and measures TOOL SCHEMAS. The "
          "published PAGE-READ numbers use tiktoken on o200k_base "
          "(DESIGN 3.4). Do not mix them in one table.")


if __name__ == "__main__":
    main()
