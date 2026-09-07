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
from urllib.parse import urlparse

from ..anchors import Outcome, ladder
from ..engine.session import MANAGER
from ..errors import (AmbiguousLocation, BadParams, Conflict,
                      ConfirmationRequired, NavigationBlocked,
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

# --------------------------------------------------- parameters (#10)
#
# ALL PROSE IN THIS SECTION IS PLACEHOLDER COPY. The facts each message must
# carry are listed in the build report.
#
# THE DESIGN DECISION, and everything else follows from it: slots are
# STRUCTURAL, stored out of band as spans, never `{{tokens}}` written into
# the recorded text. Three reasons in descending severity. A recorded
# literal can contain `{{`, because the steps come from what an agent
# actually typed on a real page, so a run-time string replace over recorded
# text is a template-injection surface pointed at content nobody controls.
# An in-band token makes substitution a PARSE, and a parse has an error
# mode, an escaping rule, and a nesting question, every one of which is a
# place a value can reach something it should not. And it hides WHERE the
# parameter goes: a reviewer reading the file cannot tell whether `{{url}}`
# sits in a `text` value or a `condition` value without reading every step.
#
# Substitution is therefore a splice by index, `value[:start] + supplied +
# value[end:]`. Nothing is parsed and nothing is escaped.

#: A parameter name is an identifier the caller types into a dict, so it is
#: held tighter than a workflow name.
_PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: THE SLOTTABLE SET, CLOSED, AND THIS IS THE SECURITY BOUNDARY.
#: A parameter is DATA. A parameter is never code, never a selector, never a
#: condition, never a key. Field paths are matched against this table and
#: never resolved by a generic dotted-path walk over `args`, because a
#: generic resolver is how `args.condition` becomes reachable.
SLOTTABLE: dict[str, tuple[str, ...]] = {
    "navigate": ("args.url",),
    "type_text": ("args.text",),
    "wait_for": ("args.value",),
    "fill_form": ("args.fields.<i>.value",),
}

#: `wait_for`'s value is slottable only for these conditions. `condition`
#: itself is not slottable at all, so a recorded text wait can never become
#: a js wait, and a `js` step carries no slots and refuses at load. Two
#: independent guards, both required.
_SLOTTABLE_WAIT_CONDITIONS = ("text", "text_gone", "url")

#: What a slot entry may contain. Unknown keys refuse rather than being
#: ignored: a slot is a security-relevant structure, and tolerating an
#: unknown key there is how a future field gets honored by accident.
_SLOT_KEYS = frozenset({"param", "field", "span", "recorded_origin"})

#: What a declared parameter may contain, in the file.
_PARAM_KEYS = frozenset({"name", "required", "kind", "default",
                         "description", "allow_origin_change"})

#: The value cap. Refuse past it, never truncate.
PARAM_VALUE_CAP = 8192


def _norm_field(field: str) -> str:
    """A field path with its index generalized, for the table lookup."""
    return re.sub(r"\.fields\.\d+\.", ".fields.<i>.", field or "")


def _field_get(step: dict, field: str):
    """Read one CLOSED field path off a step. Never a generic walk."""
    args = step.get("args") or {}
    if field == "args.url":
        return args.get("url")
    if field == "args.text":
        return args.get("text")
    if field == "args.value":
        return args.get("value")
    match = re.fullmatch(r"args\.fields\.(\d+)\.value", field or "")
    if match:
        fields = args.get("fields") or []
        index = int(match.group(1))
        if index < len(fields):
            return (fields[index] or {}).get("value")
    return None


def _field_set(step: dict, field: str, value) -> None:
    args = step.setdefault("args", {})
    if field in ("args.url", "args.text", "args.value"):
        args[field.split(".", 1)[1]] = value
        return
    match = re.fullmatch(r"args\.fields\.(\d+)\.value", field or "")
    if match:
        args["fields"][int(match.group(1))]["value"] = value


def _slottable_fields(step: dict) -> list[str]:
    """Every field path this recorded step actually offers, expanded."""
    tool = step.get("tool")
    args = step.get("args") or {}
    if tool == "wait_for":
        condition = (args.get("condition") or "").strip().lower()
        if condition not in _SLOTTABLE_WAIT_CONDITIONS:
            return []
        return ["args.value"]
    if tool == "fill_form":
        return [f"args.fields.{i}.value"
                for i in range(len(args.get("fields") or []))]
    return [f for f in SLOTTABLE.get(tool, ())
            if _field_get(step, f) is not None]


def _kind_of(step: dict, field: str, value) -> str:
    if step.get("tool") == "navigate" and field == "args.url":
        return "url"
    if isinstance(value, bool):
        return "bool"
    return "text"


def _origin_of(url: str) -> str:
    host = urlparse(str(url or "")).hostname or ""
    return host.lower()


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
    _validate_slots(doc, path.name)
    return doc


def _validate_slots(doc: dict, filename: str) -> None:
    """THE FILE IS SUSPECT, NEVER THE CALLER (feature #10, at load).

    A workflow file is on disk and can be hand-edited, and `_dry_pass`
    already carries that suspicion for the tool of each step. Slots get the
    same treatment, and every refusal here blames the FILE: the caller
    passed a name, not a document."""
    declared = doc.get("parameters")
    if declared is not None and not isinstance(declared, list):
        raise ValidationFailed(
            f"workflow file {filename} carries a `parameters` key that is "
            f"not a list, which is not what save_workflow writes; the file "
            f"may have been edited. Re-record the workflow.")
    names = set()
    for entry in declared or []:
        if not isinstance(entry, dict) or not isinstance(
                entry.get("name"), str) \
                or not _PARAM_NAME_RE.match(entry["name"]):
            raise ValidationFailed(
                f"workflow file {filename} declares a parameter this build "
                f"does not recognize, which is not what save_workflow "
                f"writes; the file may have been edited. Re-record the "
                f"workflow.")
        unknown = sorted(set(entry) - _PARAM_KEYS)
        if unknown:
            raise ValidationFailed(
                f"workflow file {filename} declares parameter "
                f"{entry['name']!r} with unknown key(s) {unknown}. A "
                f"declaration this build did not write is not honored by "
                f"accident. Re-record the workflow.")
        names.add(entry["name"])
    for i, step in enumerate(doc.get("steps") or []):
        if not isinstance(step, dict):
            continue
        args = step.get("args") or {}
        if step.get("tool") == "wait_for" \
                and (args.get("condition") or "").strip().lower() == "js":
            raise ValidationFailed(
                f"workflow file {filename} carries wait_for(condition='js') "
                f"at step {i}, which evaluates JavaScript in the page. "
                f"save_workflow never records one, so this file was edited "
                f"by hand. Workflow replay carries a closed set of recorded "
                f"actions and script evaluation is not in it. Remove the "
                f"step, or run the predicate through evaluate_script, which "
                f"names the capability and is gated on it.")
        slots = step.get("slots")
        if slots is None:
            continue
        if not isinstance(slots, list):
            raise ValidationFailed(
                f"workflow file {filename} carries a `slots` key at step "
                f"{i} that is not a list; the file may have been edited.")
        offered = _slottable_fields(step)
        for slot in slots:
            if not isinstance(slot, dict):
                raise ValidationFailed(
                    f"workflow file {filename} carries a slot at step {i} "
                    f"that is not an object; the file may have been edited.")
            unknown = sorted(set(slot) - _SLOT_KEYS)
            if unknown:
                raise ValidationFailed(
                    f"workflow file {filename} carries a slot at step {i} "
                    f"with key(s) {unknown} that this build does not write. "
                    f"A slot decides where a caller-supplied value lands, "
                    f"so an unrecognized key in one is refused rather than "
                    f"ignored. Re-record the workflow.")
            field = slot.get("field")
            if field not in offered:
                raise ValidationFailed(
                    f"workflow file {filename} carries a slot at step {i} "
                    f"on field {field!r}, which is not one this build makes "
                    f"slottable for a {step.get('tool')!r} step, so the "
                    f"file does not match what save_workflow writes and may "
                    f"have been edited. A parameter is data: it fills in "
                    f"what gets typed or a piece of a URL, never a "
                    f"selector, a wait condition, a key, or a piece of "
                    f"script. The slottable fields here are {offered}. "
                    f"Re-record the workflow.")
            if slot.get("param") not in names:
                raise ValidationFailed(
                    f"workflow file {filename} carries a slot at step {i} "
                    f"for parameter {slot.get('param')!r}, which the file "
                    f"does not declare; it may have been edited. Re-record "
                    f"the workflow.")
            span = slot.get("span")
            value = _field_get(step, field)
            length = len(value) if isinstance(value, str) else 0
            if not (isinstance(span, list) and len(span) == 2
                    and all(isinstance(x, int) for x in span)
                    and 0 <= span[0] <= span[1] <= length):
                raise ValidationFailed(
                    f"workflow file {filename} carries a slot at step {i} "
                    f"whose span {span!r} is not inside the recorded value; "
                    f"the file may have been edited. Re-record the "
                    f"workflow.")


# ------------------------------------------------------------------ saving


async def save_workflow(
    session: str | None = None,
    name: str = "",
    start_index: int = 0,
    end_index: int | None = None,
    parameters: list | None = None,
) -> dict:
    """Save a named, replayable workflow from the session's audit log, so a
    multi-step flow can be re-run later without keeping an arbitrary-code
    tool enabled. Steps are recorded as durable content-derived anchors
    rather than refs or coordinates, which is what lets a replay survive a
    re-render or a later session. start_index and end_index select a slice
    of the session's replayable actions (as numbered by the step listing
    this returns). Returns the saved workflow's name, step list, and file.
    `parameters` turns the recording into a reusable template: declare
    parameters=[{'name': 'title', 'example': 'the value you recorded'}] and
    the value you typed once becomes a slot the next run fills in. A
    PARAMETER IS DATA. A parameter is never code, never a selector, never a
    condition, never a key: a slot can fill in what gets typed, or a piece
    of a URL, and nothing else. Slots are stored as spans out of band rather
    than as tokens inside the recorded text, so a recorded literal that
    happens to contain template syntax stays a literal. A parameter that
    binds nothing refuses and lists every recorded value you could have
    meant, and an example matching several of them refuses rather than
    picking one. Returns which slots each parameter bound to and the
    run_workflow call that fills them.
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
    declared: list = []
    if parameters is not None:
        declared, _slots = _bind_parameters(steps, parameters)
    doc = {
        "name": _slug(name),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session": session,
        "origins": origins,
        **({"parameters": [{k: v for k, v in p.items()
                            if not k.startswith("_")} for p in declared]}
           if declared else {}),
        "steps": steps,
    }
    path = _path_of(name)
    await _write_workflow(path, doc)
    _audit.annotate(workflow=doc["name"])
    slot_count = sum(len(s.get("slots") or []) for s in steps)
    return {
        "name": doc["name"],
        "steps": len(steps),
        "step_list": [_step_line(i, s) for i, s in enumerate(steps)],
        "origins": origins,
        "file": str(path),
        **({"parameters": [
            {"name": p["name"], "required": p["required"], "kind": p["kind"],
             "bound_to": p["_bound_to"],
             **({"recorded_example": p["_example"]}
                if p["_example"] is not None else {})}
            for p in declared],
            "parity": (f'{len(declared)} parameter(s), {slot_count} slot(s), '
                       f'every slot bound and every parameter used')}
           if declared else {}),
        "next": f"run_workflow(name={doc['name']!r}, page=..., "
                f"dry_run=True"
                + (", parameters={"
                   + ", ".join(f"{p['name']!r}: ..." for p in declared) + "}"
                   if declared else "")
                + f") re-resolves every anchor before anything executes."
                + (f" This flow is now findable by site: "
                   f"list_workflows(for_origin={origins[0]!r}) returns it "
                   f"the next time you are there." if origins else ""),
    }


def _recorded_values(steps: list[dict]) -> list[tuple[int, str, object]]:
    """Every slottable value in the recorded flow, in order. This is what a
    refusal lists, so a caller can see what was actually available rather
    than being told their declaration was wrong and left to guess."""
    out = []
    for i, step in enumerate(steps):
        for field in _slottable_fields(step):
            out.append((i, field, _field_get(step, field)))
    return out


def _recorded_listing(values: list) -> str:
    return "; ".join(f"step {i} {f} = {v!r}" for i, f, v in values) \
        or "none: this flow records no slottable value"


def _bind_parameters(steps: list[dict], declared: list) -> tuple[list, list]:
    """Turn the caller's declarations into (parameters, slots), or refuse.

    Every check runs before the file is written, and a parameter that binds
    nothing refuses: a workflow saved with a dangling parameter is a
    workflow that can only fail at run."""
    if not isinstance(declared, list) or not declared:
        raise BadParams(
            "save_workflow(parameters=...) takes a non-empty list of "
            "parameter declarations, for example "
            "parameters=[{'name': 'title', 'example': 'D-pad bug'}] to "
            "replace a recorded value, or "
            "[{'name': 'title', 'step': 1, 'field': 'args.text'}] to name "
            "the address outright.")
    available = _recorded_values(steps)
    listing = _recorded_listing(available)
    params: list[dict] = []
    slots: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for entry in declared:
        decl = {"name": entry} if isinstance(entry, str) else dict(entry or {})
        name = decl.get("name")
        if not isinstance(name, str) or not _PARAM_NAME_RE.match(name):
            raise BadParams(
                f"parameter name {name!r} is not usable: a name is 1 to 32 "
                f"characters, starts with a lowercase letter, and carries "
                f"only lowercase letters, digits, and underscores. It is an "
                f"identifier the caller types into a dict, so it is held "
                f"tighter than a workflow name is.")
        if name in seen:
            raise BadParams(
                f"parameter {name!r} is declared twice; every name in the "
                f"list is distinct, and nothing is merged by position.")
        seen.add(name)
        bound = _bind_one(decl, name, available, listing)
        kind = decl.get("kind") or _kind_of(steps[bound[0]["step"]],
                                            bound[0]["field"],
                                            bound[0]["recorded"])
        for hit in bound:
            step = steps[hit["step"]]
            value = hit["recorded"]
            if kind == "bool" and not isinstance(value, bool):
                raise BadParams(
                    f"parameter {name!r} is declared as a bool and the value "
                    f"it binds to (step {hit['step']} {hit['field']}) is "
                    f"{type(value).__name__}, so it could only ever fail at "
                    f"run. Nothing was saved.")
            slot = {"param": name, "field": hit["field"],
                    "span": [hit["start"], hit["end"]]}
            if kind == "url":
                origin = _origin_of(value)
                if not str(value or "").startswith(("http://", "https://")):
                    raise BadParams(
                        f"parameter {name!r} is declared as a url and the "
                        f"recorded value at step {hit['step']} is not an "
                        f"http or https URL. Nothing was saved.")
                slot["recorded_origin"] = origin
            slots.append((hit["step"], slot))
            step.setdefault("slots", []).append(slot)
        param = {"name": name,
                 "required": bool(decl.get("required", "default" not in decl)),
                 "kind": kind}
        for key in ("default", "description", "allow_origin_change"):
            if key in decl:
                param[key] = decl[key]
        param["_bound_to"] = [f'step {h["step"]} {h["field"]} '
                              f'[{h["start"]}:{h["end"]}]' for h in bound]
        param["_example"] = bound[0]["recorded"] \
            if isinstance(bound[0]["recorded"], (str, bool)) else None
        params.append(param)
    return params, slots


def _bind_one(decl: dict, name: str, available: list, listing: str) -> list:
    """Resolve one declaration to one or more (step, field, span) hits."""
    if decl.get("step") is not None or decl.get("field"):
        step_index, field = decl.get("step"), decl.get("field")
        if step_index is None or not field:
            raise BadParams(
                f"parameter {name!r} names one half of an address: an "
                f"explicit declaration carries both `step` and `field`. The "
                f"recorded slottable values are: {listing}.")
        match = [(i, f, v) for i, f, v in available
                 if i == step_index and f == field]
        if not match:
            raise BadParams(
                f"parameter {name!r} addresses step {step_index} "
                f"{field!r}, which is not a slottable field of that step. A "
                f"parameter is DATA: it can fill in what gets typed or a "
                f"piece of a URL, never a selector, a wait condition, a "
                f"key, or a piece of script. The slottable fields are "
                f"{ {t: list(f) for t, f in SLOTTABLE.items()} }, and a "
                f"wait_for value is slottable only when its recorded "
                f"condition is one of {list(_SLOTTABLE_WAIT_CONDITIONS)}. "
                f"The recorded slottable values are: {listing}.")
        _i, _f, value = match[0]
        span = decl.get("span")
        if span is None:
            span = [0, len(value) if isinstance(value, str) else 0]
        if (not isinstance(span, (list, tuple)) or len(span) != 2
                or not all(isinstance(x, int) for x in span)
                or not 0 <= span[0] <= span[1]
                <= (len(value) if isinstance(value, str) else 0)):
            raise BadParams(
                f"parameter {name!r} carries span {span!r}, which is not "
                f"inside the recorded value at step {step_index} "
                f"({value!r}).")
        return [{"step": step_index, "field": field, "start": span[0],
                 "end": span[1], "recorded": value}]
    example = decl.get("example")
    if example is None:
        raise BadParams(
            f"parameter {name!r} was declared by name alone, and a name is "
            f"not an address. Add `example` (the recorded value it should "
            f"replace, or a piece of one) or `step` and `field`. The "
            f"recorded slottable values are: {listing}.")
    hits = []
    for i, field, value in available:
        if isinstance(value, bool) and value is example:
            hits.append({"step": i, "field": field, "start": 0, "end": 0,
                         "recorded": value})
            continue
        if not isinstance(value, str) or not isinstance(example, str):
            continue
        start = value.find(example)
        while start >= 0:
            hits.append({"step": i, "field": field, "start": start,
                         "end": start + len(example), "recorded": value})
            start = value.find(example, start + 1)
    if not hits:
        raise BadParams(
            f"parameter {name!r} declares example {example!r} and no "
            f"recorded value contains it, so it would bind nothing. A "
            f"workflow is never saved with a dangling parameter. The "
            f"recorded slottable values are: {listing}.")
    if len(hits) > 1 and not decl.get("all"):
        listed = "; ".join(
            f'step {h["step"]} {h["field"]} [{h["start"]}:{h["end"]}]'
            for h in hits)
        raise AmbiguousLocation(
            f"parameter {name!r} declares example {example!r} and "
            f"{len(hits)} recorded values match it. Nothing binds first "
            f"match, for the reason find_and_act refuses on several matches: "
            f"picking one is how the wrong thing gets changed. Candidates: "
            f"{listed}. Name the one you meant with `step` and `field`, or "
            f"declare `all: true` to bind every one of them.")
    return hits


def _check_value(name: str, kind: str, value) -> None:
    """A supplied value is DATA of a declared shape, and nothing else."""
    if kind == "bool":
        if not isinstance(value, bool):
            raise BadParams(
                f"parameter {name!r} is declared as a bool (it fills a "
                f"checkbox) and a {type(value).__name__} arrived. Pass true "
                f"or false.")
        return
    if isinstance(value, bool) or not isinstance(value, str):
        raise BadParams(
            f"parameter {name!r} takes a string and a "
            f"{type(value).__name__} arrived. A parameter fills in text or "
            f"a piece of a URL, so a list or an object has nowhere to land.")
    if len(value) > PARAM_VALUE_CAP:
        raise BadParams(
            f"parameter {name!r} is {len(value):,} characters and the cap "
            f"is {PARAM_VALUE_CAP:,}. It is refused rather than truncated, "
            f"because a value silently cut in half is worse than one that "
            f"did not arrive.")
    bad = [c for c in value if ord(c) < 0x20 and c not in "\n\t"]
    if bad or "\x00" in value:
        raise BadParams(
            f"parameter {name!r} carries a control character, which no "
            f"field on a page takes as input. Newlines and tabs are fine "
            f"and reach the field's own honest refusal where the field is "
            f"single-line.")


def _apply_parameters(doc: dict, supplied: dict | None) -> tuple[dict, dict]:
    """Fill the slots, or refuse. Returns the filled document and the report
    that rides in the result.

    Substitution happens BEFORE the mandatory dry run, so the dry run's step
    lines show what will actually be typed. A dry run that showed the
    template rather than the filled value would be exactly the wrong
    information at exactly the moment it matters."""
    declared = doc.get("parameters") or []
    supplied = dict(supplied or {})
    if not declared:
        if supplied:
            raise BadParams(
                f"workflow {doc.get('name')!r} declares no parameters and "
                f"{sorted(supplied)} arrived. It replays exactly what was "
                f"recorded. To make part of it fill-in-able, re-save it "
                f"with save_workflow(..., parameters=[...]), which reports "
                f"the recorded values you can turn into slots.")
        return doc, {}
    by_name = {p["name"]: p for p in declared}
    extra = sorted(set(supplied) - set(by_name))
    if extra:
        raise BadParams(
            f"workflow {doc.get('name')!r} does not declare "
            f"{extra}; it declares {sorted(by_name)}. An unrecognized "
            f"parameter is refused rather than ignored, because a caller "
            f"that believes it configured something it did not is the worse "
            f"outcome. Nothing was executed.")
    values: dict = {}
    defaulted: list = []
    missing: list = []
    for param in declared:
        name = param["name"]
        if name in supplied:
            _check_value(name, param.get("kind", "text"), supplied[name])
            values[name] = supplied[name]
        elif "default" in param:
            values[name] = param["default"]
            defaulted.append({
                "name": name,
                **({"value_length": len(str(param["default"]))}
                   if param.get("kind") != "bool"
                   else {"value": param["default"]}),
                "note": "the workflow's declared default was used"})
        elif param.get("required", True):
            missing.append(param)
    if missing:
        listed = "; ".join(
            f'{p["name"]} ({p.get("kind", "text")}'
            + (f', {p["description"]}' if p.get("description") else "")
            + ")" for p in declared)
        raise BadParams(
            f"workflow {doc.get('name')!r} needs "
            f"{[p['name'] for p in missing]} and they did not arrive. Its "
            f"parameters are: {listed}. Nothing was executed.")
    filled = _fill(doc, values)
    applied = []
    for i, step in enumerate(filled["steps"]):
        for slot in step.get("slots") or []:
            entry = {"step": i, "field": slot["field"],
                     "param": slot["param"]}
            kind = by_name[slot["param"]].get("kind", "text")
            value = _field_get(step, slot["field"])
            if kind == "url":
                # The resolved URL IS the information, so it rides in full.
                entry["result"] = value
            elif kind == "bool":
                entry["value"] = value
            else:
                # The value came from the caller rather than from the page,
                # but a workflow parameter is exactly the shape a password
                # gets typed into by mistake, so the length is reported and
                # the value is not.
                entry["value_length"] = len(str(values[slot["param"]]))
            applied.append(entry)
    _check_origins(filled, by_name)
    report = {"supplied": sorted(set(supplied)),
              **({"defaulted": defaulted} if defaulted else {}),
              "applied": applied}
    return filled, report


def _fill(doc: dict, values: dict) -> dict:
    """THE SPLICE. `value[:start] + supplied + value[end:]`, by index.

    Nothing is parsed and nothing is escaped, which is the whole reason
    slots are stored as spans rather than as tokens written into the
    recorded text: a recorded literal that happens to contain `{{name}}`
    is a literal here, and a run-time string replace over recorded text
    would be a template-injection surface pointed at content nobody
    controls."""
    filled = json.loads(json.dumps(doc))
    for step in filled.get("steps") or []:
        # Later spans first, so an earlier splice cannot move a later one.
        for slot in sorted(step.get("slots") or [],
                           key=lambda s: s["span"][0], reverse=True):
            if slot["param"] not in values:
                continue
            supplied = values[slot["param"]]
            current = _field_get(step, slot["field"])
            if isinstance(current, str):
                start, end = slot["span"]
                _field_set(step, slot["field"],
                           current[:start] + str(supplied) + current[end:])
            else:
                _field_set(step, slot["field"], supplied)
    return filled


def _check_origins(filled: dict, by_name: dict) -> None:
    """A workflow recorded on one site does not get pointed at another.

    The origin policy already gates off-list origins; the workflow's own
    recorded origin is a tighter and free constraint, and a flow the caller
    trusts BY NAME is exactly the thing that must not quietly retarget."""
    for i, step in enumerate(filled.get("steps") or []):
        for slot in step.get("slots") or []:
            recorded = slot.get("recorded_origin")
            if not recorded:
                continue
            param = by_name.get(slot["param"]) or {}
            now = _origin_of(_field_get(step, slot["field"]))
            if now == recorded:
                continue
            if param.get("allow_origin_change"):
                continue
            raise NavigationBlocked(
                f"step {i} of this workflow was recorded on "
                f"{recorded!r} and parameter {slot['param']!r} points it at "
                f"{now or 'a value that is not an http or https URL'!r}. A "
                f"workflow you trust by name is not silently retargeted at "
                f"another site. Nothing was executed. Re-save the workflow "
                f"with allow_origin_change: true on that parameter if "
                f"moving sites is what it is for.")


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
    slots = "".join(f' <{s["param"]}>' for s in step.get("slots") or [])
    return f'{i}: {step["tool"]}{detail}{target}{slots}'


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
            declared = doc.get("parameters")
            out.append({"name": doc.get("name", path.stem),
                        "steps": len(steps) if isinstance(steps, list) else 0,
                        "created": doc.get("created"),
                        "origins": origins,
                        **({"parameters": [
                            {"name": p.get("name"),
                             "required": p.get("required", True),
                             "kind": p.get("kind", "text"),
                             **({"description": p["description"]}
                                if p.get("description") else {})}
                            for p in declared if isinstance(p, dict)]}
                           if isinstance(declared, list) and declared
                           else {})})
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
    parameters: dict | None = None,
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
    outcomes on a real run. A workflow saved with parameters takes them
    here, as parameters={'title': 'the value for this run'}: values are
    filled in before the dry run, so the dry run shows what will actually be
    typed rather than what was recorded. A missing one refuses and lists
    every parameter the workflow declares; an unexpected one refuses too
    rather than being ignored, since a caller that believes it configured
    something it did not is the worse outcome. A parameter with a default is
    filled from it and the result says so. A URL parameter that would point
    the flow at a different site refuses unless the workflow was saved with
    permission to move.
    """
    doc = _load(name)
    steps = doc.get("steps", [])
    if not steps:
        raise ValidationFailed(
            f"workflow {doc.get('name')!r} holds no steps; re-record it.")
    # The parameter layer runs here, before the page is even required: a
    # declaration that does not add up is answered on the declaration rather
    # than half way into a replay.
    doc, param_report = _apply_parameters(doc, parameters)
    steps = doc.get("steps", [])
    if not page:
        raise BadParams(
            "run_workflow needs the page handle to replay on (open one with "
            "manage_session / manage_tabs). The dry run also runs against "
            "that page, since anchors resolve against a live page.")
    sess, record = MANAGER.locate(page)
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=record.page.url, workflow=doc["name"])
    if param_report:
        # The NAMES, never the values: the log says which template ran with
        # which slots filled without becoming a place secrets accumulate.
        _audit.annotate(workflow_parameters=sorted(
            {a["param"] for a in param_report.get("applied") or []}))

    report = await _dry_pass(record, steps)
    would_fail = [r for r in report
                  if r["verdict"] in ("STALE_ANCHOR", "AMBIGUOUS_LOCATION",
                                      "MODAL_BLOCKED", "not-replayable")]
    if dry_run:
        return {
            "session": sess.session_id, "page": record.handle,
            "workflow": doc["name"], "dry_run": True,
            **({"parameters": param_report} if param_report else {}),
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

    return await _execute(sess, record, doc, report,
                          param_report)


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


async def _execute(sess, record, doc: dict, dry_report: list[dict],
                   param_report: dict | None = None) -> dict:
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
        **({"parameters": param_report} if param_report else {}),
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
