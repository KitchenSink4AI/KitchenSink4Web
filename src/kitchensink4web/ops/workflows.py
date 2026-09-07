"""The `workflows` pack: named replayable flows (DESIGN 2.2, 5.6), Phase 6.

The pack closes the #1645 fork: playwright-mcp answered the macro request by
pointing users at an arbitrary-code-execution tool, so a deployment that
disables eval by policy loses workflow reuse. Named replayable workflows
over durable anchors, with a mandatory dry run, are the first-class
primitive that closes that gap, and nothing in this module can evaluate script:
a step is one of the seven recorded lite actions, nothing else.

Three design facts carry the whole module:

- **The audit trail is the recording substrate.** Replayable tools enrich
  their audit record with a `replay` block (the full arguments and the
  target's durable anchor rather than its ref), and `save_workflow` reads
  those records back. A workflow file therefore records anchors, never refs,
  because a replay in a later session has no refs to speak of (DESIGN 3.5).
- **The dry run is mandatory and runs first.** `run_workflow` re-resolves
  every checkable anchor against the live page BEFORE executing anything,
  refuses outright when any of them fails, and reports the per-step verdict
  either way. A flow that broke since it was recorded is caught rather than
  half-run.
- **Replay goes through the real tools, so it inherits the whole policy
  ladder per step**: read-only absence, credential blindness, origin policy,
  budgets, loop detection, and the confirmation gates. A gated step (a form
  submit, say) asks per step through the S8 elicitation plumbing and FAILS
  CLOSED where no human accepts; the replay stops there with batch
  semantics (completed steps stay completed, the rest report
  not_attempted), because browser actions do not roll back.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from ..anchors import Outcome, ladder
from ..engine.session import MANAGER
from ..errors import (BadParams, Conflict, ConfirmationRequired,
                      TargetNotFound, ValidationFailed)
from ..policy import audit as _audit
from ..policy import gates as _gates
from ..policy import sandbox
from ..projection import extract
from . import common
from . import lite as _lite

#: The tools a workflow step may replay. CLOSED: everything here is a lite
#: action that resolves, gates, and verifies through the Phase 3/4
#: machinery. `evaluate_script` is deliberately absent, which is the point
#: of the pack (DESIGN 6.8).
REPLAYABLE: tuple[str, ...] = ("navigate", "click", "type_text", "fill_form",
                               "press_keys", "scroll", "wait_for")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _workflow_dir() -> Path:
    directory = _audit.STATE_DIR / "workflows"
    if sandbox.active():
        sandbox.check_path(str(directory), "store workflows")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _slug(name: str) -> str:
    slug = (name or "").strip().lower().replace(" ", "-")
    if not _NAME_RE.match(slug):
        raise BadParams(
            f"workflow name {name!r} does not slug cleanly: use 1 to 64 "
            f"characters of lowercase letters, digits, hyphens, and "
            f"underscores (got {slug!r}).")
    return slug


def _path_of(name: str) -> Path:
    return _workflow_dir() / f"{_slug(name)}.json"


def _load(name: str) -> dict:
    path = _path_of(name)
    if not path.exists():
        have = sorted(p.stem for p in _workflow_dir().glob("*.json"))
        raise TargetNotFound(
            f"no workflow named {_slug(name)!r}. "
            + (f"Saved workflows: {have}. "
               "list_workflows(for_origin='the site you are on') narrows "
               "that list to the flows recorded there." if have
               else "Nothing has been saved yet; record a flow and call "
                    "save_workflow."))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationFailed(
            f"workflow file {path.name} could not be read "
            f"({exc.__class__.__name__}); re-save the workflow.") from exc
    # A file that PARSES is not a file that is a workflow (chaos C-10). A
    # top-level list, string, or null sailed past this guard and every
    # consumer then called `.get` on it, so the caller got a raw Python
    # `'list' object has no attribute 'get'` under BAD_PARAMS with a hint
    # about location objects.
    if not isinstance(doc, dict):
        raise ValidationFailed(
            f"workflow file {path.name} parsed as {type(doc).__name__} "
            f"rather than a workflow object; re-save the workflow.")
    return doc


# ------------------------------------------------------------------ saving


async def save_workflow(
    session: str | None = None,
    name: str = "",
    start_index: int = 0,
    end_index: int | None = None,
) -> dict:
    """Save a named, replayable workflow from the session's audit log, so a
    multi-step flow can be re-run later without keeping an arbitrary-code
    tool enabled. Steps are recorded as durable content-derived anchors
    rather than refs or coordinates, which is what lets a replay survive a
    re-render or a later session. start_index and end_index select a slice
    of the session's replayable actions (as numbered by the step listing
    this returns). Returns the saved workflow's name, step list, and file.
    """
    if not name:
        raise BadParams(
            "save_workflow needs a name for the flow, for example "
            "name='nightly-report'.")
    rows = _audit.LOG.read(limit=500, session=session)["records"]
    candidates = []
    for row in rows:
        if row.get("outcome") != "ok":
            continue
        # A COMPOSITE'S ROW EXPANDS, IN ORDER (2026-09-07, with `batch`).
        # One registered tool call writes one audit record, so a tool that
        # drives several replayable tools inside it carries its trail as a
        # LIST. Without this branch a five-step batch would arrive here as
        # whichever single `replay` block was written last and the workflow
        # would replay wrong, quietly. Each member is validated against
        # REPLAYABLE exactly as a single block is, so a step whose tool is
        # outside the closed set is dropped rather than smuggled in.
        for replay in _replay_blocks(row):
            if not isinstance(replay, dict) \
                    or replay.get("tool") not in REPLAYABLE:
                continue
            candidates.append({
                "tool": replay["tool"],
                "args": replay.get("args") or {},
                "anchor": replay.get("anchor"),
                "anchor_id": replay.get("anchor_id"),
                "page_key": replay.get("page_key"),
                "url": row.get("url"),
                "recorded_at": row.get("ts"),
            })
    if not candidates:
        raise ValidationFailed(
            "the audit log holds no replayable actions"
            + (f" for session {session!r}" if session else "")
            + ". A workflow is recorded by DOING the flow once (navigate, "
              "click, type_text, fill_form, press_keys, scroll, wait_for) "
              "and then saving it; get_audit shows what the log holds.")
    stop = end_index if end_index is not None else len(candidates)
    steps = candidates[start_index:stop]
    if not steps:
        raise BadParams(
            f"start_index {start_index} / end_index {end_index} select "
            f"nothing; the session holds {len(candidates)} replayable "
            f"action(s), numbered 0 to {len(candidates) - 1}.")
    origins = sorted({(s.get("url") or "").split("/", 3)[2]
                      for s in steps
                      if (s.get("url") or "").startswith(("http://",
                                                          "https://"))})
    doc = {
        "name": _slug(name),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session": session,
        "origins": origins,
        "steps": steps,
    }
    path = _path_of(name)
    await _write_workflow(path, doc)
    _audit.annotate(workflow=doc["name"])
    return {
        "name": doc["name"],
        "steps": len(steps),
        "step_list": [_step_line(i, s) for i, s in enumerate(steps)],
        "origins": origins,
        "file": str(path),
        "next": f"run_workflow(name={doc['name']!r}, page=..., "
                f"dry_run=True) re-resolves every anchor before anything "
                f"executes."
                + (f" This flow is now findable by site: "
                   f"list_workflows(for_origin={origins[0]!r}) returns it "
                   f"the next time you are there." if origins else ""),
    }


def _replay_blocks(row: dict) -> list:
    """Every replayable action one audit record describes, in order.

    A single action writes `replay`. A composite that drives several of them
    inside one registered tool call writes `replay_steps`, because
    annotations merge into one dict and a per-step `replay` would leave only
    the last one standing. A row carrying both is a composite whose own
    record kept a member's block; the list wins, because it is the complete
    account and the scalar is a fragment of it."""
    steps = row.get("replay_steps")
    if isinstance(steps, list) and steps:
        return steps
    single = row.get("replay")
    return [single] if isinstance(single, dict) else []


#: Serializes save_workflow inside ONE server process. The store is
#: machine-global, so this cannot be the whole answer, which is why the
#: read-back below exists as well.
_SAVE_LOCK = asyncio.Lock()


async def _write_workflow(path, doc: dict) -> None:
    """Write a workflow so no caller holds a receipt for a file it did not
    produce (concurrency C-4).

    Three properties. SERIALIZED in-process, so two concurrent
    `save_workflow` calls in one server cannot interleave. ATOMIC replace,
    so a reader mid-write never sees a half-written document. READ BACK,
    because the store is machine-global (`%LOCALAPPDATA%\\ks4web\\workflows`)
    and the breaker found files there written minutes earlier by a DIFFERENT
    server process: nothing in this process can lock out that writer, so the
    only honest move left is to check what actually landed and say so when
    it is not what this call wrote.

    Re-saving under an existing name still overwrites, which is the ordinary
    thing a caller does after re-recording a flow. What refuses is a receipt
    that would be false."""
    body = json.dumps(doc, ensure_ascii=False, indent=1)
    marker = json.dumps(doc.get("steps"), ensure_ascii=False)
    async with _SAVE_LOCK:
        tmp = path.with_name(f"{path.name}.{os.getpid()}."
                             f"{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(body, encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise common.write_failed(path, "save the workflow", exc) from exc
        try:
            landed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            landed = None
        if not isinstance(landed, dict) or json.dumps(
                landed.get("steps"), ensure_ascii=False) != marker:
            raise Conflict(
                f"the workflow file {path} does not hold what this call "
                f"wrote: another save under the same name landed on top of "
                f"it. The workflow store is shared across every KS4Web "
                f"process on this machine, so a name collision is not "
                f"confined to this session. Nothing here is a receipt for "
                f"the steps you asked to save; re-save under a different "
                f"name.")


def _step_line(i: int, step: dict) -> str:
    anchor = step.get("anchor") or {}
    target = (f' -> {anchor.get("role")} "{anchor.get("name")}"'
              f' [{step.get("anchor_id")}]' if anchor else "")
    detail = ""
    if step["tool"] == "navigate":
        detail = f' {step["args"].get("url", "")}'
    elif step["tool"] == "wait_for":
        detail = f' {step["args"].get("condition", "")}'
    return f'{i}: {step["tool"]}{detail}{target}'


# ----------------------------------------------------------------- listing


def _host_of(text: str) -> str:
    """The host in whatever a caller typed: a bare host, a host with a port,
    or a whole URL. Lowercased, since host comparison is case-insensitive
    and a workflow recorded on Example.com is the same site."""
    value = (text or "").strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0].split("?", 1)[0]
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    return value


def _origin_matches(recorded: str, wanted: str) -> bool:
    """A recorded origin answers for a wanted one when the hosts are equal
    or when the recorded host is a subdomain of it. `www.example.com` is
    what the recorder stored and `example.com` is what a caller types, so a
    strict equality filter would answer "no workflows" for the site the
    user is standing on. It never widens the other way: asking for
    `www.example.com` does not match a workflow recorded on `evil.com`."""
    have = _host_of(recorded).split(":", 1)[0]
    want = wanted.split(":", 1)[0]
    return bool(have) and (have == want or have.endswith("." + want))


async def list_workflows(session: str | None = None,
                         for_origin: str | None = None) -> dict:
    """List the saved workflows. Returns each one's name, step count, when
    it was recorded, and the origins it touches, so a caller can pick one
    to dry-run before replaying. `for_origin` narrows the list to the flows
    recorded on one site, given as a host or any URL on it, which is the
    per-site lookup: standing on a page, ask what has already been recorded
    here before working the flow out again. A subdomain of the host you ask
    for counts as a match and nothing wider does. The dry run is the right
    first move, since a workflow recorded against an earlier version of a
    page may no longer resolve. An empty list means nothing has been saved
    on this machine.
    """
    wanted = _host_of(for_origin) if for_origin else None
    if for_origin and not wanted:
        raise BadParams(
            f"for_origin {for_origin!r} carries no host; it takes a site "
            f"('example.com') or any URL on it "
            f"('https://example.com/reports').")
    out = []
    skipped = 0
    for path in sorted(_workflow_dir().glob("*.json")):
        # ONE BAD FILE MUST NOT BRICK ENUMERATION (chaos C-10). The per-file
        # fallback existed for exactly this and was guarded by the same two
        # exceptions as the parse, so a file that parsed to a list took down
        # the listing of every OTHER workflow in the store with an
        # AttributeError from `doc.get`.
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("not a workflow object")
        except Exception:
            out.append({"name": path.stem, "error": "unreadable; re-save"})
            continue
        try:
            if session and doc.get("session") not in (None, session):
                continue
            origins = doc.get("origins")
            origins = list(origins) if isinstance(origins, list) else []
            steps = doc.get("steps")
            if wanted and not any(_origin_matches(o, wanted)
                                  for o in origins):
                skipped += 1
                continue
            out.append({"name": doc.get("name", path.stem),
                        "steps": len(steps) if isinstance(steps, list) else 0,
                        "created": doc.get("created"),
                        "origins": origins})
        except Exception:
            out.append({"name": path.stem, "error": "unreadable; re-save"})
    return {"workflows": out,
            "directory": str(_workflow_dir()),
            **({"filter": {
                "for_origin": wanted,
                "matched": len(out),
                "excluded": skipped,
                "note": (f"{skipped} saved workflow(s) touch other sites and "
                         f"are not listed; call without for_origin to see "
                         f"all of them" if skipped else
                         "every saved workflow touches this site")}}
               if wanted else {}),
            "next": "run_workflow(name=..., page=..., dry_run=True) "
                    "re-resolves every anchor and reports which still hold "
                    "before anything executes."}


# ------------------------------------------------------------------ replay


async def run_workflow(
    name: str = "",
    session: str | None = None,
    dry_run: bool = True,
    page: str | None = None,
) -> dict:
    """Replay a saved workflow on a page. The dry run is mandatory and runs
    first: every anchor checkable on the current page is re-resolved and
    reported BEFORE anything executes, and a real run refuses outright if
    any of them fails, so a flow that broke since it was recorded is caught
    rather than half-run. A real run then replays each step through the
    real tools, inheriting the whole policy ladder per step: a gated step
    (a form submit, say) asks a human per step and fails closed where no
    accept arrives, stopping the replay with completed steps left completed
    (browser actions do not roll back) and the rest not_attempted. Returns
    the per-step resolution report on a dry run and the per-step verified
    outcomes on a real run.
    """
    doc = _load(name)
    steps = doc.get("steps", [])
    if not steps:
        raise ValidationFailed(
            f"workflow {doc.get('name')!r} holds no steps; re-record it.")
    if not page:
        raise BadParams(
            "run_workflow needs the page handle to replay on (open one with "
            "manage_session / manage_tabs). The dry run also runs against "
            "that page, since anchors resolve against a live page.")
    sess, record = MANAGER.locate(page)
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=record.page.url, workflow=doc["name"])

    report = await _dry_pass(record, steps)
    would_fail = [r for r in report
                  if r["verdict"] in ("STALE_ANCHOR", "AMBIGUOUS_LOCATION",
                                      "MODAL_BLOCKED", "not-replayable")]
    if dry_run:
        return {
            "session": sess.session_id, "page": record.handle,
            "workflow": doc["name"], "dry_run": True,
            "steps": report,
            "would_fail": [r["step"] for r in would_fail],
            "verdict": ("every checkable anchor resolves; run with "
                        "dry_run=False to execute" if not would_fail else
                        f"{len(would_fail)} step(s) would fail; the flow "
                        f"needs re-recording or the page needs to change"),
        }
    if would_fail:
        raise ValidationFailed(
            f"the mandatory dry run found {len(would_fail)} step(s) whose "
            f"anchors no longer resolve "
            f"({[r['step'] for r in would_fail]}); nothing was executed. "
            f"Run with dry_run=True for the full report, or re-record the "
            f"workflow against the current page.")

    return await _execute(sess, record, doc, report)


async def _dry_pass(record, steps: list[dict]) -> list[dict]:
    """Re-resolve every checkable anchor against the live page, executing
    nothing. Steps whose page_key differs from the current page cannot be
    checked from here (replay reaches them only after its own navigate
    steps run) and are reported exactly that way rather than guessed at."""
    data = await extract(record.page)
    page_key = (data.get("identity") or {}).get("page_key") or ""
    report = []
    for i, step in enumerate(steps):
        line = {"step": i, "line": _step_line(i, step)}
        anchor = step.get("anchor")
        # L2 (gauntlet 2026-09-06): a hand-edited file can carry a step
        # whose tool is outside the closed replayable set (an evaluate_script
        # smuggled in with no anchor). Execution already refuses it, but the
        # dry run used to report such a step "replays verbatim" and give the
        # whole flow a green verdict. The dry run's one job is to predict
        # execution, so an un-replayable tool fails the dry run too.
        if step.get("tool") not in REPLAYABLE:
            line.update(verdict="not-replayable",
                        detail=f'step tool {step.get("tool")!r} is not in '
                               f'the closed replayable set '
                               f'{list(REPLAYABLE)}; the workflow file may '
                               f'have been edited. Execution would refuse '
                               f'this step, so the dry run does too.')
        elif step["tool"] == "navigate":
            line.update(verdict="would-navigate",
                        detail=step["args"].get("url"))
        elif not anchor:
            line.update(verdict="no-anchor",
                        detail="no target to check; replays verbatim")
        elif step.get("page_key") and page_key \
                and step["page_key"] != page_key:
            line.update(verdict="deferred-to-execution",
                        detail=f'recorded on {step["page_key"]}, the page '
                               f'is on {page_key}; checked after the '
                               f'navigate steps run')
        else:
            outcome = ladder.resolve_anchor(anchor, data)
            v = outcome["outcome"]
            line.update(
                verdict=("resolves" if v == Outcome.OK else
                         "resolves-rebound" if v == Outcome.REBOUND else v),
                tier=outcome.get("tier"),
                detail=(outcome.get("now") if v == Outcome.REBOUND
                        else outcome.get("recovery")
                        if v not in (Outcome.OK,) else None))
        report.append(line)
    return report


async def _execute(sess, record, doc: dict, dry_report: list[dict]) -> dict:
    steps = doc["steps"]
    per_step: list[dict] = []
    stopped = None
    for i, step in enumerate(steps):
        if stopped is not None:
            per_step.append({"step": i, "line": _step_line(i, step),
                             "status": "not_attempted"})
            continue
        try:
            result = await _run_step(sess, record, step)
        except ConfirmationRequired as exc:
            # Per-step confirmation (S8 wiring). A whole-workflow retry
            # would re-execute completed steps, so the elicitation happens
            # HERE and only this step retries on an accept.
            from .. import confirm
            grant = await confirm.attempt(exc)
            if grant is None:
                per_step.append({
                    "step": i, "line": _step_line(i, step),
                    "status": "failed", "outcome": "CONFIRMATION_REQUIRED",
                    "error": ("the step is a gated class and no human "
                              "accepted the confirmation; it FAILS CLOSED. "
                              + str(exc)[:200])})
                stopped = i
                continue
            _gates.deposit_grant(grant)
            try:
                result = await _run_step(sess, record, step)
            except Exception as exc2:  # noqa: BLE001 - reported per step
                per_step.append({"step": i, "line": _step_line(i, step),
                                 "status": "failed",
                                 "outcome": _err_code(exc2),
                                 "error": str(exc2)[:200]})
                stopped = i
                continue
            finally:
                _gates.clear_grant()
        except Exception as exc:  # noqa: BLE001 - reported per step
            per_step.append({"step": i, "line": _step_line(i, step),
                             "status": "failed", "outcome": _err_code(exc),
                             "error": str(exc)[:200]})
            stopped = i
            continue
        entry = {"step": i, "line": _step_line(i, step),
                 "status": "completed"}
        changed = result.get("changed") if isinstance(result, dict) else None
        if changed:
            entry["effect"] = changed.get("effect")
        if isinstance(result, dict) and result.get("warnings"):
            entry["warnings"] = result["warnings"]
        per_step.append(entry)
    completed = sum(1 for r in per_step if r["status"] == "completed")
    return {
        "session": sess.session_id, "page": record.handle,
        "workflow": doc["name"], "dry_run": False,
        "dry_pass": {"checked": len(dry_report), "all_resolved": True},
        "steps": per_step,
        "completed": completed,
        "stopped_at": stopped,
        "not_attempted": [r["step"] for r in per_step
                          if r["status"] == "not_attempted"],
        "rollback": "none. Browser actions do not roll back; the steps "
                    "listed as completed HAVE happened.",
    }


def _err_code(exc: Exception) -> str:
    return getattr(exc, "code", None) or exc.__class__.__name__


async def _run_step(sess, record, step: dict) -> dict:
    """One step through the REAL tool, so policy, gates, trusted input, and
    verified outcomes all apply exactly as they would to a direct call."""
    tool = step["tool"]
    args = dict(step.get("args") or {})
    page = record.handle
    if tool not in REPLAYABLE:
        raise ValidationFailed(
            f"step tool {tool!r} is not replayable; the closed set is "
            f"{list(REPLAYABLE)}. The workflow file may have been edited.")

    if tool == "navigate":
        return await _lite.navigate(page=page, action="goto",
                                    url=args.get("url"),
                                    wait_until=args.get("wait_until", "load"))
    if tool == "fill_form":
        fields = []
        for f in args.get("fields", []):
            loc = await _anchor_location(sess, record, f.get("anchor"))
            fields.append({**loc, "value": f.get("value")})
        return await _lite.fill_form(page=page, fields=fields,
                                     submit=bool(args.get("submit")))
    location = None
    if step.get("anchor"):
        location = await _anchor_location(sess, record, step["anchor"])
    if tool == "click":
        return await _lite.click(page=page, location=location,
                                 button=args.get("button", "left"),
                                 click_count=args.get("click_count", 1),
                                 modifiers=args.get("modifiers") or None)
    if tool == "type_text":
        return await _lite.type_text(
            page=page, location=location, text=args.get("text", ""),
            clear_first=bool(args.get("clear_first")),
            press_enter=bool(args.get("press_enter")),
            submit=bool(args.get("submit")),
            delay_ms=int(args.get("delay_ms") or 0))
    if tool == "press_keys":
        return await _lite.press_keys(page=page, keys=args.get("keys", ""),
                                      location=location,
                                      repeat=int(args.get("repeat") or 1),
                                      delay_ms=int(args.get("delay_ms") or 0))
    if tool == "scroll":
        return await _lite.scroll(page=page,
                                  action=args.get("action", "by"),
                                  amount=int(args.get("amount") or 1),
                                  location=location)
    # wait_for. THE RECORDING SIDE ALREADY REFUSES A JS PREDICATE ("a
    # workflow must never smuggle evaluate-shaped work past the gate that
    # names it"), and the replay side did not check, so a hand-edited
    # workflow file was a second door onto the same capability (IG-01,
    # defence-in-depth half). `wait_for(condition='js')` is now gated in the
    # tool itself; this stays as the closed-set guard the module's own
    # contract promises.
    if (args.get("condition") or "").strip().lower() == "js":
        raise ValidationFailed(
            "this workflow step is wait_for(condition='js'), which "
            "evaluates caller-supplied JavaScript in the page. Workflow "
            "replay carries a closed set of recorded actions and script "
            "evaluation is not in it; save_workflow never records one, so "
            "this file was edited by hand. Remove the step, or run the "
            "predicate through evaluate_script, which names the capability "
            "and is gated on it.")
    return await _lite.wait_for(page=page,
                                condition=args.get("condition", "load"),
                                value=args.get("value"),
                                location=location,
                                timeout_ms=int(args.get("timeout_ms")
                                               or 30000))


async def _anchor_location(sess, record, anchor: dict | None) -> dict:
    """A stored anchor becomes a live location: re-resolve it against a
    fresh extraction, ABSORB the resolved unit into the session map, and
    hand back the SESSION ref. This used to hand back the raw in-page node
    id, which the field misdirect investigation (2026-09-05) closed as a
    namespace confusion: a per-read node id spelled like a session ref can
    collide with an unrelated session entry, and the action tool would then
    resolve THAT entry's anchor instead of this step's. Refusals carry the
    ladder's own vocabulary, so a stale step fails exactly like a stale ref
    would."""
    if not anchor:
        raise ValidationFailed(
            "this step carries no anchor and no target-free form; the "
            "workflow file may have been edited. Re-record it.")
    data = await extract(record.page)
    outcome = ladder.resolve_anchor(anchor, data)
    v = outcome["outcome"]
    if v in (Outcome.OK, Outcome.REBOUND):
        unit = dict(outcome["unit"] or {})
        node_ref = unit.get("ref")
        if node_ref and unit.get("anchor"):
            shim = {"identity": {"url": record.page.url,
                                 "page_key": (data.get("identity") or {})
                                 .get("page_key", "")},
                    "affordances": [unit], "regions": [], "headings": [],
                    "forms": [], "tables": []}
            sess.element_map.absorb(
                shim, record.handle,
                sess.reads.mint_token(record.handle),
                ts=time.strftime("%Y-%m-%dT%H:%M:%S"), scope="replay")
            return {"ref": unit["ref"]}
        # The unit resolved but carries no live ref (a summarized unit);
        # fall through to the strongest printable selector.
        a = unit.get("anchor") or anchor
        if a.get("attr_testid"):
            return {"testid": a["attr_testid"]}
        if a.get("attr_id"):
            return {"css": f'#{a["attr_id"]}'}
        return {"role": a.get("role"), "name": a.get("name"), "exact": True}
    raise ValidationFailed(
        f'the step\'s anchor no longer resolves ({v}'
        + (f', tier {outcome.get("tier")}' if outcome.get("tier") else "")
        + f'): was {outcome.get("was") or anchor.get("name")!r}. '
        + (outcome.get("recovery") or "re-record the workflow."))


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (save_workflow, run_workflow, list_workflows)
