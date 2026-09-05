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
import functools
import os
import sys

from fastmcp import FastMCP

from . import envelope, packs
from .ops import lite
from .policy import audit, credentials, readonly

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
        "launch flags."
    ),
)


def _wrap(fn):
    """Every tool body runs inside the envelope. Success payloads pass
    through the redaction seam; anything raised becomes a typed refusal with
    isError=true and a hint that names a recovery."""

    @functools.wraps(fn)
    async def inner(*args, **kwargs):
        try:
            result = await fn(*args, **kwargs)
        except envelope.CATCHABLE as exc:
            # The audit trail records refusals too (DESIGN 5.6: every tool
            # call appends a record), and it records them HERE so no tool can
            # forget to. The annotations ops set before raising still land.
            audit.LOG.record(fn.__name__,
                             getattr(exc, "code", None)
                             or envelope.classify(exc),
                             args=kwargs)
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
    mcp.tool(
        _wrap(fn),
        name=name,
        annotations={"readOnlyHint": not readonly.is_mutating(name)},
    )
    packs.register(name, pack)
    return True


def register_all() -> list[str]:
    """Register everything this launch selection calls for. Phase 0: the
    lite core only."""
    registered = []
    for fn in lite.LITE_TOOLS:
        if register(fn, pack=None):
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
        state = configure(
            cli_packs=cli_packs,
            read_only=args.read_only if args.read_only is not None
            else os.environ.get("KS4WEB_READ_ONLY"),
        )
    except Exception as exc:  # startup misconfiguration: fail LOUDLY
        print(f"KS4Web refusing to start: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(
        f"KS4Web: {len(state['registered'])} tools, packs="
        f"{state['packs'] or ['lite']}, read_only={state['read_only']}",
        file=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
