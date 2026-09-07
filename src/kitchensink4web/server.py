"""The KS4Web server: the registration gate, the refusal wrapper, and main().

Phase 0 registers the lite core as stubs. There is no browser here.

**Registration is where two of the design's properties are made true**, so
this small module carries more weight than its size suggests:

1. Read-only mode is enforced by ABSENCE (DESIGN 5.2). A mutating tool in
   read-only mode is never handed to FastMCP, so it is not in tools/list,
   so there is nothing to allowlist and nothing for an injected page
   instruction to reach for.
2. Packs are resolved ONCE at launch (DESIGN 7.3). Every connection to this
   process sees an identical tool set, which is what MCP 2026-07-28 requires
   and what the family's runtime enable_tools pattern cannot satisfy.

Both are launch-time properties for the same reason, and both are provable
rather than asserted because of it.

The refusal wrapper is the third piece: every tool body runs inside it, so
no exception ever reaches a caller as a raw string. That is a property of
the response framework rather than a discipline applied per tool, because
per-tool discipline fails the moment someone adds a feature. The incumbent's
own console-logging regression is the proof.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import importlib
import os
import sys

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.exceptions import ValidationError as _FmcpValidationError
from fastmcp.server.middleware import Middleware
from pydantic import ValidationError as _PydanticValidationError

from . import confirm, envelope, packs
from .errors import (BadParams, ConfirmationRequired, ReadOnlyMode,
                     Timeout, ValidationFailed)
from .ops import lite
from .policy import audit, credentials, gates, readonly

# Redaction lives in the serializer (DESIGN 5.3): installed at import, before
# any tool can run, so there is no window where a payload rides out unscrubbed.
# The Phase 3 gate proves it here by driving a deliberately leaky test tool.
envelope.set_redactor(credentials.redactor)

mcp = FastMCP(
    name="kitchensink4web",
    instructions=(
        "Browser automation with a cheap first read. get_page_view returns "
        "an orientation of any page under a token budget it never exceeds, "
        "with references you can act on; find_elements is the cheap "
        "targeted follow-up when what you need was not in that read. Call "
        "get_workflows for recipes and for the capability packs and their "
        "launch flags. This server may be running read-only (the shipped "
        "default), in which case mutating tools are absent from the tool "
        "list; manage_session(action='status') names the grade in force and "
        "how a human unlocks acting at the next launch."
    ),
)


class GuidedAbsenceMiddleware(Middleware):
    """The field test's blocking finding, fixed at the one conformant layer.

    A forced call to an absent mutating tool used to return the bare
    framework string ("Unknown tool: 'type_text'"), which names neither the
    mode, the grade, nor the unlock. The tool stays UNREGISTERED, so
    tools/list is untouched and the launch-time contract holds; only the
    error a call gets back improves. The message teaches the HUMAN the
    launch-time unlock and hands the AGENT nothing callable or redeemable,
    which the read-only invariant test asserts over this text directly.

    The same interception serves discoverability rule 2 for packs: a call
    to a tool that exists in the design but lives in an unloaded pack gets
    the pack name and the launch flag instead of the bare unknown-tool
    string.
    """

    async def on_call_tool(self, context, call_next):
        name = getattr(context.message, "name", None) or ""
        try:
            return await call_next(context)
        except (_FmcpValidationError, _PydanticValidationError) as exc:
            # M2 (gauntlet 2026-09-06): FastMCP's input coercion runs ABOVE
            # the per-tool refusal wrapper, so a wrong-type scalar argument
            # used to ride out as a raw pydantic string, leaking the
            # pydantic version and the internal callable name. It becomes
            # the same typed envelope every other refusal wears, here at
            # the one layer that sees the validation failure.
            refusal = BadParams(_argument_message(name, exc))
            audit.LOG.record(name or "(unnamed tool)", "BAD_PARAMS", args={})
            return envelope.refuse(refusal)
        except (NotFoundError, ToolError) as exc:
            if "unknown tool" not in str(exc).lower():
                raise
            if readonly.active() and name in readonly.MUTATING:
                grade = readonly.grade()
                refusal = ReadOnlyMode(
                    f"{name} is not registered because this server is "
                    f"running read-only (grade {grade!r}), the shipped "
                    f"default. No tool in this mode can click, type, "
                    f"submit, upload, download, evaluate script, or write "
                    f"storage; the read surface is fully available. "
                    f"{readonly.UNLOCK_TEACHING}")
                return envelope.refuse(refusal)
            pack = packs.pack_of(name)
            if pack not in (None, "lite") and not packs.is_pack_loaded(pack):
                refusal = BadParams(
                    f"{name} exists in the design but its pack is not "
                    f"loaded in this process.")
                refusal.hint_tools = (name,)
                return envelope.refuse(refusal)
            # L1 (gauntlet 2026-09-06): a name that is neither an absent
            # mutating tool nor an unloaded pack member used to fall through
            # to the bare framework string. Nothing rides out raw, this
            # included.
            refusal = ValidationFailed(
                f"no tool named {name!r} exists in this process, under any "
                f"launch shape. tools/list is the authority on what is "
                f"loaded; get_workflows lists the capability packs and "
                f"their launch flags. Check the spelling before retrying.")
            audit.LOG.record(name or "(unnamed tool)", "VALIDATION_FAILED",
                             args={})
            return envelope.refuse(refusal)


#: Parameters a tool USED to advertise and no longer does, with the sentence
#: that used to be their refusal. Union wave, fuzzer classes 6 and 7: a
#: schema that advertises a knob which always refuses is a schema that lies,
#: and `get_page_view(cursor=...)` additionally reached NOT_IMPLEMENTED —
#: a scaffold code this build's own gate says must never ship. Removing them
#: from the signature fixes the schema; this table is how the good teaching
#: sentence survives the removal for a caller who still sends one.
#: FLAGGED: both sentences are lifted verbatim from the refusals they
#: replace, not newly written.
WITHDRAWN_PARAMS: dict[tuple[str, str], str] = {
    ("get_page_view", "include_hidden"): (
        "get_page_view never includes hidden content: the orientation "
        "reports hidden regions in its completeness block and stops there. "
        "The labeled route is get_text(page=..., include_hidden=True), "
        "which returns hidden blocks in a separately labeled section with "
        "the hiding technique named per block."),
    ("get_page_view", "cursor"): (
        "get_page_view takes no cursor. Spill-to-file paging was never "
        "built, and the region and section reads plus get_text's "
        "start_index pagination cover the cases it was for."),
}


def _withdrawn_note(tool: str, exc: BaseException) -> str | None:
    """The sentence for a withdrawn parameter, when the failure names one."""
    text = str(exc)
    for (name, param), sentence in WITHDRAWN_PARAMS.items():
        if name == tool and param in text:
            return (f"{tool} has no {param!r} parameter and nothing was "
                    f"executed. {sentence}")
    return None


def _argument_message(tool: str, exc: BaseException) -> str:
    """One honest sentence per malformed argument, built from pydantic's
    structured error entries rather than its rendered string, so neither the
    pydantic version, its docs URLs, nor the internal callable naming
    (`call[click]`) reaches a caller."""
    entries = None
    for source in (getattr(exc, "__cause__", None), exc):
        errors = getattr(source, "errors", None)
        if callable(errors):
            try:
                entries = errors(include_url=False)
                break
            except Exception:  # a shape this version does not serve
                entries = None
    label = tool or "this tool"
    withdrawn = _withdrawn_note(tool, exc)
    if withdrawn:
        return withdrawn
    if not entries:
        return (f"{label} was called with malformed arguments and nothing "
                f"was executed. Check each argument against the tool's "
                f"schema (get_workflows carries usage recipes).")
    bits = []
    for entry in entries[:6]:
        loc = ".".join(str(p) for p in entry.get("loc", ())) or "(call)"
        msg = entry.get("msg", "invalid value")
        if "input" in entry:
            got = entry["input"]
            got_name = "null" if got is None else type(got).__name__
            bits.append(f"{loc}: {msg} (got {got_name})")
        else:
            bits.append(f"{loc}: {msg}")
    more = len(entries) - 6
    return (f"{label} was called with malformed argument(s): "
            + "; ".join(bits)
            + (f"; and {more} more" if more > 0 else "")
            + ". Nothing was executed. Fix the named argument(s) and "
              "retry; the tool's schema in tools/list is the authority.")


mcp.add_middleware(GuidedAbsenceMiddleware())


#: EVERY TOOL CALL IS BOUNDED (union wave 2026-09-07, chaos L-01/L-02).
#:
#: `session.with_timeout` exists and its docstring is exactly right ("a hung
#: navigation must free the server rather than wedge it"). `navigate` used
#: it and the read, act, and capture paths did not, so against a SUSPENDED
#: browser `navigate(timeout_ms=8000)` returned honestly at 8.01 s while
#: `get_page_view` ran past 120 s, `take_screenshot` past 120 s, and
#: `click(timeout_ms=6000)` past 120 s with its EXPLICIT argument ignored,
#: twenty times over. Against a slow-loris origin a `get_text` blocked for
#: 82 s and `get_text` and `get_page_view` accept no `timeout_ms` at all, so
#: a caller could not even ask for a bound.
#:
#: One bound at the wrapper covers every tool, including the ones that take
#: no timeout argument, which is the half a per-call parameter cannot reach.
TOOL_CEILING_MS = int(os.environ.get("KS4WEB_TOOL_CEILING_MS", "90000"))

#: Slack over a caller's own `timeout_ms`, so this ceiling never fires
#: BEFORE the tool's own honest timeout does. An explicit caller bound must
#: be answered by the tool that owns it, with the message that names what
#: was awaited; this is the backstop for when that bound is not honored.
TOOL_CEILING_SLACK_MS = 15000

#: Tools whose work is legitimately N times one operation. A page walk is N
#: navigations and a workflow replay is N actions, so one bound for both
#: shapes would be either useless or wrong.
_CEILING_MULTIPLIER = {"read_pages": 12, "run_workflow": 12,
                       "export_har": 3, "export_pdf": 3}


def _ceiling_ms(fn, kwargs: dict) -> int:
    ceiling = TOOL_CEILING_MS * _CEILING_MULTIPLIER.get(fn.__name__, 1)
    for key in ("timeout_ms", "budget_ms"):
        asked = kwargs.get(key)
        if isinstance(asked, (int, float)) and asked > 0:
            ceiling = max(ceiling, int(asked) + TOOL_CEILING_SLACK_MS)
    return ceiling


async def _bounded(fn, args, kwargs):
    """Run one tool body under a finite ceiling."""
    ceiling = _ceiling_ms(fn, kwargs)
    try:
        return await asyncio.wait_for(fn(*args, **kwargs),
                                      timeout=ceiling / 1000)
    except asyncio.TimeoutError as exc:
        raise Timeout(
            f"{fn.__name__} did not return within {ceiling} ms and was "
            f"abandoned, so the server is free even though the browser is "
            f"not. Nothing here says the operation did not happen: it was "
            f"still running when the bound expired. A browser that is "
            f"suspended, thrashing, or waiting on an origin that never "
            f"finishes answering looks exactly like this. Check the session "
            f"with manage_session(action='status'), and close and reopen it "
            f"if the browser is gone. KS4WEB_TOOL_CEILING_MS sets this "
            f"bound.") from exc


def _wrap(fn):
    """Every tool body runs inside the envelope. Success payloads pass
    through the redaction seam; anything raised becomes a typed refusal with
    isError=true and a hint that names a recovery."""

    @functools.wraps(fn)
    async def inner(*args, **kwargs):
        try:
            try:
                result = await _bounded(fn, args, kwargs)
            except ConfirmationRequired as gate_exc:
                # S8 wiring: put the gate's question to the client over
                # elicitation. An explicit human ACCEPT redeems the gate,
                # deposits it, and re-runs THIS call once; the re-run
                # re-resolves its target and the TOCTOU re-validation holds
                # it to the fingerprint the human confirmed. Anything short
                # of an accept (headless auto-cancel, decline, timeout, a
                # client with no elicitation) returns the original refusal:
                # fail closed, exactly as measured.
                #
                # run_workflow never lets a step's gate reach here (a
                # whole-workflow retry would re-execute completed steps); it
                # confirms per step through the same confirm.attempt().
                grant = await confirm.attempt(gate_exc)
                if grant is None:
                    raise
                gates.deposit_grant(grant)
                try:
                    result = await _bounded(fn, args, kwargs)
                finally:
                    gates.clear_grant()
        except envelope.CATCHABLE as exc:
            # The audit trail records refusals too (DESIGN 5.6: every tool
            # call appends a record), and it records them HERE so no tool can
            # forget to. The annotations ops set before raising still land.
            audit.LOG.record(fn.__name__,
                             getattr(exc, "code", None)
                             or envelope.classify(exc),
                             args=kwargs)
            return envelope.refuse(exc)
        except Exception as exc:  # noqa: BLE001 - the no-raw-string backstop
            # NOTHING rides out raw. The field test caught a driver error
            # ("Execution context was destroyed", a mid-keystroke navigation)
            # reaching the caller as a bare Playwright string because it is
            # not in CATCHABLE. Typed refusals are still the rule and ops
            # guards still fire first with better messages; this backstop
            # exists so an exception class nobody anticipated becomes an
            # honest envelope refusal instead of a traceback.
            audit.LOG.record(fn.__name__, envelope.classify(exc), args=kwargs)
            return envelope.refuse(exc)
        audit.LOG.record(fn.__name__, "ok", args=kwargs)
        if isinstance(result, dict) and "ok" not in result:
            return envelope.success(result)
        return envelope.redact(result)

    return inner


def register(fn, pack: str | None = None) -> bool:
    """The registration gate. Returns True when the tool was registered.

    Order matters and is deliberate: the read-only check runs FIRST and
    raises on an unclassified tool, so a new tool cannot reach tools/list
    without someone having decided in policy/readonly.py whether it
    mutates. A tool that slips through unclassified in read-only mode would
    make the headline claim false, so the failure is loud and at startup."""
    name = fn.__name__
    if not readonly.should_register(name):
        return False
    if not packs.should_register(pack):
        return False
    # Every tool must be classified, loudly, on every launch shape: when the
    # server is not read-only should_register never consults the tables, so
    # the check is explicit here rather than a side effect of the hint.
    readonly.is_mutating(name)
    # readOnlyHint is the GENUINE set, not merely the non-mutating one:
    # navigate, scroll, and the session/tab/export tools all modify
    # something, and an optimistic hint would be a false safety claim in
    # metadata.
    mcp.tool(
        _wrap(fn),
        name=name,
        annotations={"readOnlyHint": readonly.read_only_hint(name)},
    )
    packs.register(name, pack)
    return True


#: Pack -> ops module (relative to this package). Imported ONLY when the
#: launch selection includes the pack, so an unselected pack costs nothing
#: and its recorders never attach. Every module exports `TOOLS`.
_PACK_MODULES: dict[str, str] = {
    "extract": ".ops.extract",
    "capture": ".ops.capture",
    "network": ".ops.net",
    "storage": ".ops.storage",
    "files": ".ops.files",
    "diagnostics": ".ops.diag",
    "workflows": ".ops.workflows",
}


def register_all() -> list[str]:
    """Register everything this launch selection calls for: the lite core
    always, plus every selected pack's roster (Phase 5). Pack tools pass the
    same registration gate as lite ones, so read-only absence and the
    launch-time pack contract hold identically across the whole surface."""
    registered = []
    for fn in lite.LITE_TOOLS:
        if register(fn, pack=None):
            registered.append(fn.__name__)
    for pack, modname in _PACK_MODULES.items():
        if not packs.should_register(pack):
            continue
        module = importlib.import_module(modname, __package__)
        for fn in module.TOOLS:
            if register(fn, pack=pack):
                registered.append(fn.__name__)
    return registered


def deregister_all() -> None:
    """Tear the surface down so a second launch shape can be registered in
    the same process. Only the harness and measure_surface need this: a real
    server resolves its shape once and never changes it, which is the whole
    point of launch-time selection."""
    for members in list(packs.tool_names().values()):
        for name in members:
            try:
                mcp.local_provider.remove_tool(name)
            except Exception:  # already gone; nothing to undo
                pass
    packs.reset()


def configure(
    mode: str | None = None,
    cli_packs: list[str] | None = None,
    read_only: str | bool | None = None,
) -> dict:
    """Resolve launch-time configuration, then register. Called once by
    main(), and by tests that need a specific launch shape."""
    deregister_all()
    readonly.apply(read_only)
    selected = packs.resolve_startup_packs(mode=mode, cli_packs=cli_packs)
    packs.apply_startup_packs(selected)
    names = register_all()
    return {
        "packs": packs.loaded_packs(),
        "read_only": readonly.grade(),
        "registered": names,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="web-mcp",
        description=(
            "KitchenSink4Web: browser automation with a cheap first read. "
            "Packs and read-only mode are chosen at LAUNCH and are "
            "identical for every connection to this process."
        ),
    )
    parser.add_argument(
        "--packs", default=None,
        help=("comma-separated capability packs to load "
              f"({', '.join(packs.pack_names())}), or 'full'. A typo is an "
              "error rather than a silent downgrade."),
    )
    parser.add_argument(
        "--read-only", nargs="?", const="browse", default=None,
        choices=[None, *readonly.GRADES],
        help=("run with no mutating tools registered at all. 'browse' "
              "(the default when the flag is bare) permits reads, "
              "navigation, and scrolling; 'strict' additionally limits "
              "navigation to the origin allowlist."),
    )
    args = parser.parse_args()

    cli_packs = None
    if args.packs:
        raw = [p.strip() for p in args.packs.split(",") if p.strip()]
        cli_packs = (
            packs.pack_names() if any(p in ("full", packs.EVERYTHING)
                                      for p in raw) else raw
        )

    try:
        # A bare `configure(read_only=None)` resolves the env precedence
        # itself: KS4WEB_ALLOW_ACTING (positive polarity, the Desktop
        # checkbox), then the deprecated KS4WEB_READ_ONLY, then the shipped
        # default. An empty value under either name fails closed to browse.
        state = configure(cli_packs=cli_packs, read_only=args.read_only)
    except Exception as exc:  # startup misconfiguration: fail LOUDLY
        print(f"KS4Web refusing to start: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(
        f"KS4Web: {len(state['registered'])} tools, packs="
        f"{state['packs'] or ['lite']}, read_only={state['read_only']} "
        f"(decided by {readonly.source()})",
        file=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
