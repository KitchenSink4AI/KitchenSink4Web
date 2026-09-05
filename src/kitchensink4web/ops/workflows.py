"""The `workflows` pack: named replayable flows (DESIGN 2.2, DESIGN 5.6).

Phase 5 registers this pack so the surface and `--packs full` are complete
and every menu entry delivers an honest answer, but its ENGINE is Phase 6
(save from the audit log, dry-run anchor re-resolution, deterministic
replay). Until then these three refuse NOT_IMPLEMENTED naming Phase 6,
exactly as the lite core refused before its engine landed: a tool that
returned a plausible empty workflow would be the silent-false-success this
product argues against.

The pack matters because it closes the #1645 fork: playwright-mcp answered
the macro request by pointing users at an arbitrary-code-execution tool, so
a deployment that disables eval for safety loses workflow reuse. Named
replayable workflows over durable anchors, with a mandatory dry run, are
the safe first-class primitive that closes it. `save_workflow` and
`run_workflow` mutate (they act on replay), so both are absent under
read-only; `list_workflows` reads and is not.
"""

from __future__ import annotations

from ..errors import NotImplementedYet


def _phase6(name: str) -> None:
    raise NotImplementedYet(
        f"{name} is registered but its engine is Phase 6. Phase 5 built the "
        f"capability packs (extract, capture, network, storage, files, "
        f"diagnostics); workflow save and replay over durable anchors, with "
        f"the mandatory dry run DESIGN 5.6 describes, land in Phase 6. Until "
        f"then this refuses rather than returning an empty or plausible "
        f"workflow. The audit trail (get_audit) already records every call "
        f"a workflow would be saved from.")


async def save_workflow(
    session: str | None = None,
    name: str = "",
    start_index: int = 0,
) -> dict:
    """Save a named, replayable workflow from the session's audit log, so a
    multi-step flow can be re-run later without keeping an arbitrary-code
    tool enabled. The steps are recorded as durable content-derived anchors
    rather than coordinates, which is what lets a replay survive a re-render.
    Returns the saved workflow's name and step count. (Engine lands in Phase
    6; this refuses honestly until then rather than saving an empty flow.)
    """
    _phase6("save_workflow")


async def run_workflow(
    name: str = "",
    session: str | None = None,
    dry_run: bool = True,
    page: str | None = None,
) -> dict:
    """Replay a saved workflow. The dry run is mandatory and runs first: it
    re-resolves every anchor against the live page and reports which still
    resolve and which would fail BEFORE anything executes, so a flow that
    broke since it was recorded is caught rather than half-run. Returns the
    per-step resolution report on a dry run, and the per-step outcomes on a
    real run. (Engine lands in Phase 6; this refuses honestly until then.)
    """
    _phase6("run_workflow")


async def list_workflows(session: str | None = None) -> dict:
    """List the saved workflows: each one's name, step count, when it was
    recorded, and the origins it touches. Returns the list so a caller can
    pick one to dry-run before replaying, which is the safe first move
    since a workflow recorded against an earlier version of a page may no
    longer resolve. (Engine lands in Phase 6; this refuses honestly until
    then rather than returning an empty list that looks like 'you have no
    saved workflows' when in fact none can yet be saved.)
    """
    _phase6("list_workflows")


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (save_workflow, run_workflow, list_workflows)
