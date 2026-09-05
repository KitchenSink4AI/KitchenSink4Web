"""Docstring measurement and the copy guards.

AUTHOR RULING 2026-09-05, and it reshapes this file: **token budgets are
SOFT.** A browser tool that delivers may cost what it costs (the author's
own words allow 7-10k for a delivering tool), and useful docstring
information is NEVER deleted to hit a cap. So the lite ratchet and the
per-tool caps become ADVISORY WITH MEASURED HONESTY: every number is still
measured on every run and published to `gates/docstring_budget.json`, the
published copy quotes the honest figure, and nothing here deletes a word.

What stays HARD, because each protects information rather than chasing a
number:

- the 2,048-character client truncation (a description over it silently
  LOSES its tail, which is deletion by another name)
- descriptions exist, say what the tool returns, and carry no em dashes
- the ADVISORY numbers are actually written, so honesty is mechanical

The retired hard caps are kept as reference constants so the report can say
how far each tool sits from the old target. DESIGN 3.2's lite row and the
Phase 7 gate carry the same ruling.
"""

from __future__ import annotations

import json
from pathlib import Path

from kitchensink4web import packs

DESC_MIN, DESC_REF_MAX = 80, 120     # reference, advisory since 2026-09-05
SCHEMA_REF_CAP = 250                 # reference, advisory since 2026-09-05
LITE_REF_TARGET = 1500               # reference, advisory since 2026-09-05

GATES_DIR = Path(__file__).resolve().parents[2] / "gates"


def _tools(launch, live_tools):
    # The whole surface, honestly: read-only is the shipped default (browse),
    # which would register only the read tools, but the docstring report
    # covers every tool that CAN ship. Unlock and load every pack.
    from kitchensink4web import packs
    launch(cli_packs=packs.pack_names(), read_only=False)
    return list(live_tools().values())


def _tok(text: str) -> int:
    return round(len(text) / 4)


def test_no_em_dashes_in_descriptions(launch, live_tools):
    """Standing rule: no em dashes anywhere public, in any language."""
    for tool in _tools(launch, live_tools):
        assert "—" not in (tool.description or ""), \
            f"{tool.name} description has an em dash"


def test_every_tool_has_a_description_of_substance(launch, live_tools):
    """The MINIMUM stands: it is a quality floor, not a cap, and nothing
    about the soft-budget ruling licenses a one-line description."""
    for tool in _tools(launch, live_tools):
        desc = tool.description or ""
        assert desc, f"{tool.name} has no description"
        assert _tok(desc) >= DESC_MIN, (
            f"{tool.name} description is ~{_tok(desc)} tokens, under the "
            f"{DESC_MIN} floor")


def test_description_fits_the_client_truncation(launch, live_tools):
    """HARD, and it survives the soft-budget ruling for the same reason the
    ruling exists: a description over 2,048 characters loses its tail
    silently (DESIGN 7.3), which is exactly the information loss the ruling
    forbids. The fix for a breach is restructuring, never deletion."""
    for tool in _tools(launch, live_tools):
        assert len(tool.description or "") <= 2048, \
            f"{tool.name} description would be truncated by the client"


def test_measured_honesty_is_published(launch, live_tools):
    """The advisory half of the ruling, made mechanical: every run measures
    the real numbers and writes them where the published copy reads from.
    A missing report would let a stale figure survive, so THIS is the hard
    assertion the soft budgets left behind."""
    tools = _tools(launch, live_tools)
    launch()
    lite_cost = packs.pack_cost("lite", {t.name: t for t in tools})
    rows = {}
    for tool in sorted(tools, key=lambda t: t.name):
        desc = _tok(tool.description or "")
        schema = _tok(json.dumps(tool.parameters or {}))
        rows[tool.name] = {
            "description_tokens": desc,
            "schema_tokens": schema,
            "total_tokens": desc + schema,
            "over_reference_caps": bool(desc > DESC_REF_MAX
                                        or schema > SCHEMA_REF_CAP),
        }
    report = {
        "ruling": ("2026-09-05: token budgets are SOFT; these figures are "
                   "published honestly rather than enforced as caps. "
                   "Estimator: chars/4 (approximate; page-read numbers use "
                   "tiktoken o200k_base and the two are never mixed)."),
        "lite_total_tokens": lite_cost,
        "reference_targets": {"lite": LITE_REF_TARGET,
                              "description": [DESC_MIN, DESC_REF_MAX],
                              "schema": SCHEMA_REF_CAP},
        "tools": rows,
    }
    GATES_DIR.mkdir(exist_ok=True)
    out = GATES_DIR / "docstring_budget.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert lite_cost > 0
    assert len(rows) >= 14


def test_every_description_says_what_the_tool_returns(launch, live_tools):
    """House discoverability rule: a description that names only the verb
    leaves the model guessing whether the result is actionable. Every one of
    ours states the shape of what comes back."""
    for tool in _tools(launch, live_tools):
        low = (tool.description or "").lower()
        assert any(w in low for w in ("return", "get back", "reports",
                                      "comes back", "carries", "names",
                                      "says", "arrives", "state")), \
            f"{tool.name} description never says what the caller gets"
