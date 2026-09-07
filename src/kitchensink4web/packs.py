"""Launch-time pack selection. The SHAPE ports from word-mcp `packs.py`; the
runtime `enable_tools` machinery deliberately does NOT (DESIGN 7.2).

This is the one place KS4Web departs from a settled family pattern for a
conformance reason rather than a taste one, so it is worth stating plainly
here where the code lives rather than only in the design doc.

MCP revision 2026-07-28: the tool set "MUST NOT vary per-connection or as a
side effect of other requests on the connection." The family's shipped
pattern registers every tool up front, starts non-lite tools disabled, and
flips packs on mid-session with a list_changed notification. That varies the
set as a side effect of a request, and the request is the enable_tools call
itself. So KS4Web resolves packs ONCE at startup and registers only what is
selected. Every connection to a given process sees an identical tools/list.

The cost is real and the design does not minimize it: a user who needs the
storage pack once a week either pays for it all week or does not have it in
the moment. Family discoverability rule 2 adapts to compensate (DESIGN 7.4):
a refusal names the pack, the launch flag, and the env var, and
get_workflows in lite carries the full menu.

Env contract (Q11, RULED by the author 2026-09-04):

    KS4WEB_MODE          lite | full | comma-separated pack list
    KS4WEB_PACK_POLICY   locked | open   (locked pins the launch selection)
    KS4WEB_ALLOWED_ROOTS os.pathsep list of directories (policy/sandbox.py)

The .mcpb install-screen toggles (Phase 8 config work). Packs are
launch-fixed here, so the Desktop install screen is the ONLY chooser a
non-developer ever sees, and it speaks booleans:

    KS4WEB_ALL_PACKS         master load-all toggle
    KS4WEB_PACK_<NAME>       one per pack (EXTRACT, CAPTURE, NETWORK,
                             STORAGE, FILES, DIAGNOSTICS, WORKFLOWS)

Each accepts the literal strings "true" and "false" (what Desktop writes
for a user_config boolean). Empty means off. Anything else REFUSES at
startup. Precedence: --packs beats KS4WEB_MODE beats the master toggle
beats the per-pack toggles, so a developer's explicit selection is never
silently widened by a leftover checkbox.

A typo in KS4WEB_MODE fails LOUDLY. That is not a stylistic preference: it
inverts chrome-devtools-mcp #2530, where a typo in --browserUrl is silently
ignored and downgrades attach mode to launch mode, and playwright-mcp #1388,
where --storage-state silently applied zero cookies.
"""

from __future__ import annotations

import json
import os

from .errors import BadParams

EVERYTHING = "everything"

#: The packs (DESIGN 2.2). Summaries are one line each and are what a
#: refusal quotes when it signposts a pack the caller does not have.
PACK_SUMMARIES: dict[str, str] = {
    "extract": (
        "deterministic structured extraction: tables with row paging and "
        "rowspan awareness, repeated-record lists, links, page metadata, "
        "schema-directed fields, article-shaped reads with the boilerplate "
        "counted, and CSV/JSON export"
    ),
    "capture": (
        "pixels and documents: screenshots with byte and visual-token caps "
        "and secret masking, local optical reading of canvas and image "
        "text, PDF export, MHTML page save, and device emulation"
    ),
    "network": (
        "request inspection: paginated request lists, budgeted response "
        "bodies, HAR export, and routing (block, mock, throttle, offline)"
    ),
    "diagnostics": (
        "console messages (errors-only by default, deduplicated), uncaught "
        "page errors with stacks, and gated script evaluation"
    ),
    "storage": (
        "cookies, local and session storage, IndexedDB, and auth-state save "
        "and load. Values are masked by default"
    ),
    "files": (
        "download lifecycle into a scoped directory (including the fetch "
        "route out of a browser PDF viewer), uploads including "
        "synthetic-DataTransfer dropzones, and the page clipboard"
    ),
    "workflows": (
        "named replayable flows recorded from the audit log, with a "
        "mandatory dry run that re-resolves every anchor before executing"
    ),
    # NOT folded into `diagnostics`, which is thematically right and
    # practically wrong: that pack carries `evaluate_script`, and packs are
    # fixed at launch, so putting the audit there would make every user who
    # wants an accessibility check run a process with the RCE-equivalent
    # tool registered. That is a bad trade for a one-tool convenience.
    "accessibility": (
        "a WCAG audit through axe-core (an optional pip dependency), "
        "aggregated by rule with a per-rule drilldown, checks the engine "
        "could not decide reported separately, and no score"
    ),
}

#: The DESIGNED pack rosters (DESIGN 2.2). Phase 5 built every row except
#: `workflows`, whose engine is Phase 6 and whose tools register as honest
#: stubs until then. This table stays authoritative: a parity test asserts
#: each ops module's TOOLS matches its row exactly, so the designed surface
#: and the built one cannot drift apart silently, and `measure_surface`
#: still reports any planned-but-unregistered gap.
PLANNED_MEMBERS: dict[str, tuple[str, ...]] = {
    "extract": ("get_table", "get_list", "get_links", "get_metadata",
                "extract_fields", "export_data", "get_article",
                "read_pages"),
    "capture": ("take_screenshot", "read_image_text", "export_pdf",
                "save_page", "emulate"),
    "network": ("list_requests", "get_request", "export_har", "set_routing"),
    "diagnostics": ("list_console", "get_page_errors", "evaluate_script"),
    "storage": ("manage_cookies", "manage_storage", "save_auth_state",
                "load_auth_state"),
    "files": ("download", "upload_file", "manage_clipboard"),
    "workflows": ("save_workflow", "run_workflow", "list_workflows"),
    "accessibility": ("get_accessibility",),
}

#: Membership only: pack -> set of registered tool NAMES. Deliberately not the
#: tool OBJECTS. FastMCP owns those, and a second copy would go stale the first
#: time a tool is transformed or removed. Cost measurement reads the live
#: objects from `mcp.list_tools()` and passes them in.
_REGISTRY: dict[str, set[str]] = {"lite": set()}
_LOADED: set[str] = set()


# ------------------------------------------------------------- registration


def register(tool_name: str, pack: str | None = None) -> None:
    """Record a registered tool against its pack. `pack=None` means lite."""
    key = pack or "lite"
    if key != "lite" and key not in PACK_SUMMARIES:
        raise BadParams(
            f"unknown pack {key!r} for tool {tool_name!r}; known packs are "
            f"{sorted(PACK_SUMMARIES)}"
        )
    _REGISTRY.setdefault(key, set()).add(tool_name)


def pack_names() -> list[str]:
    return list(PACK_SUMMARIES)


def pack_of(tool_name: str) -> str | None:
    """The pack a tool belongs to, whether or not it is loaded. Consults the
    PLANNED table too, so a refusal can signpost a pack whose tools do not
    exist yet without the message becoming a lie about what is registered."""
    for pack, members in _REGISTRY.items():
        if tool_name in members:
            return pack
    for pack, members in PLANNED_MEMBERS.items():
        if tool_name in members:
            return pack
    return None


def is_pack_loaded(pack: str) -> bool:
    return pack == "lite" or pack in _LOADED


def loaded_packs() -> list[str]:
    return sorted(_LOADED)


def tool_names() -> dict[str, list[str]]:
    return {p: sorted(m) for p, m in _REGISTRY.items() if m}


def reset() -> None:
    """Clear the membership registry and the launch selection. Used by the
    test harness and by measure_surface, both of which need to register a
    second launch shape inside one process."""
    _REGISTRY.clear()
    _REGISTRY["lite"] = set()
    _LOADED.clear()


# ------------------------------------------------------------- measurement


def approx_tokens(tool: object) -> int:
    """Rough per-tool client cost: description + JSON schema at ~4 chars per
    token. Honest enough for the surface report and not a billing meter.

    Note that the PUBLISHED page-read numbers use tiktoken on o200k_base
    (DESIGN 3.4) and this estimate is a different thing for a different
    purpose. Do not mix them in one table."""
    desc = getattr(tool, "description", "") or ""
    try:
        schema = json.dumps(getattr(tool, "parameters", {}) or {})
    except (TypeError, ValueError):
        schema = ""
    return round((len(desc) + len(schema)) / 4)


def pack_cost(pack: str, tools: dict[str, object]) -> int:
    """Approximate client cost of one pack, given the LIVE tool objects
    (`{t.name: t for t in await mcp.list_tools()}`). Passing them in rather
    than caching them is what keeps this honest after a removal."""
    return sum(
        approx_tokens(t) for name, t in tools.items()
        if name in _REGISTRY.get(pack, set())
    )


def surface_report(tools: dict[str, object]) -> dict:
    """Counts and approximate token cost per registered pack, plus the
    planned-but-unregistered shape so the gap between the designed surface
    and the built one is visible at every phase rather than at Phase 7."""
    registered = {
        p: {"tools": len(m), "approx_tokens": pack_cost(p, tools)}
        for p, m in _REGISTRY.items() if m
    }
    return {
        "loaded_packs": loaded_packs(),
        "registered": registered,
        "lite_tools": len(_REGISTRY.get("lite", set())),
        "lite_approx_tokens": pack_cost("lite", tools),
        "planned_unregistered": {
            p: sorted(set(names) - _REGISTRY.get(p, set()))
            for p, names in PLANNED_MEMBERS.items()
        },
    }


# ------------------------------------------------------------ launch modes


def _validate(packs: list[str]) -> list[str]:
    unknown = [p for p in packs if p not in PACK_SUMMARIES]
    if unknown:
        raise BadParams(
            f"unknown pack(s) {unknown}: known packs are "
            f"{sorted(PACK_SUMMARIES)}. Packs are selected at launch with "
            f"--packs or KS4WEB_MODE; a typo is an error here rather than a "
            f"silent downgrade."
        )
    return packs


#: The master install-screen toggle and the per-pack boolean prefix.
ENV_ALL_PACKS = "KS4WEB_ALL_PACKS"
ENV_PACK_PREFIX = "KS4WEB_PACK_"


def _toggle_env(name: str) -> bool:
    """One install-screen boolean: the literal strings Desktop writes for a
    user_config checkbox, with the family's loud-typo rule. Empty is off,
    'true' is on, 'false' is off, anything else refuses at startup."""
    raw = os.environ.get(name)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in ("", "false"):
        return False
    if value == "true":
        return True
    raise BadParams(
        f"{name}={raw!r} is not a pack toggle value: use 'true' or 'false' "
        f"(empty means off). A typo is an error here rather than a silent "
        f"downgrade.")


def resolve_startup_packs(
    mode: str | None = None, cli_packs: list[str] | None = None
) -> list[str]:
    """Resolve the launch-time pack selection ONCE, before registration.

    Precedence: explicit --packs beats KS4WEB_MODE beats the install-screen
    master toggle (KS4WEB_ALL_PACKS) beats the per-pack toggles
    (KS4WEB_PACK_<NAME>), so a developer's explicit selection is never
    silently widened by a leftover checkbox. Returns the sorted pack list
    (lite is implicit and never listed, since it is always on). Raises on a
    typo rather than degrading."""
    if cli_packs:
        return sorted(set(_validate([p.strip() for p in cli_packs if p.strip()])))
    raw = mode if mode is not None else os.environ.get("KS4WEB_MODE")
    if raw is not None and raw.strip():
        raw = raw.strip().lower()
        if raw == "lite":
            return []
        tokens = [p.strip() for p in raw.split(",") if p.strip()]
        wants_full = any(t in ("full", EVERYTHING) for t in tokens)
        named = [t for t in tokens if t not in ("lite", "full", EVERYTHING)]
        if named:
            _validate(named)
        if wants_full:
            return sorted(PACK_SUMMARIES)
        return sorted(set(named))
    # The install-screen toggles, reached only when nothing stronger spoke.
    if _toggle_env(ENV_ALL_PACKS):
        return sorted(PACK_SUMMARIES)
    return sorted(p for p in PACK_SUMMARIES
                  if _toggle_env(ENV_PACK_PREFIX + p.upper()))


def apply_startup_packs(packs: list[str]) -> list[str]:
    """Record the resolved selection. Called once, before any registration,
    so `should_register` can gate every tool as it is declared."""
    _LOADED.clear()
    _LOADED.update(_validate(list(packs)))
    return loaded_packs()


def should_register(pack: str | None) -> bool:
    """The gate every registration passes through. Lite is always yes."""
    return pack is None or pack == "lite" or pack in _LOADED


def policy_locked() -> bool:
    """KS4WEB_PACK_POLICY=locked pins the launch selection. There is no
    runtime toggle to lock in this server, so this is forward-compatibility
    for a deployment that wants the setting stated explicitly rather than
    inferred from the absence of a tool."""
    return os.environ.get("KS4WEB_PACK_POLICY", "").strip().lower() == "locked"


def menu() -> dict:
    """The full pack menu, for get_workflows in lite (DESIGN 7.4). Names the
    launch flag and the env var for each pack, since there is no enable
    call to name."""
    return {
        pack: {
            "summary": summary,
            "loaded": is_pack_loaded(pack),
            "launch_flag": f"--packs {pack}",
            "env": f"KS4WEB_MODE={pack}",
        }
        for pack, summary in PACK_SUMMARIES.items()
    }
