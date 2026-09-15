"""Tool titles and the write-shape annotations, declared by name.

Every registered tool ships four MCP annotations. `readOnlyHint` lives in
policy/readonly.py and is not repeated here. The other three live here:

* **title** -- the human-readable name a client shows instead of the raw
  tool name. Derived mechanically: the tool name, split on underscores,
  Title Cased, with known acronyms upper-cased, a leading `com_` replaced
  by the host application's name, and short function words kept lowercase
  inside the phrase. A handful of names too short or too generic to read
  as a title take a phrase from the first clause of their own description
  instead; those are the only hand-written strings in the table and
  docs/TOOL_TITLES.md marks each one. Titles are unique within this
  server and none exceeds 40 characters.

* **destructiveHint** -- whether the tool may perform a destructive
  update. ONE rule decides it, and docs/TOOL_ANNOTATIONS.md states the
  rule alongside a per-tool reason so a reviewer can dispute any single
  row:

      false only when every code path either (a) adds new content or a new
      file without replacing anything that was already there, creation
      refusing an existing target, or (b) changes no user data at all
      (this session's tool surface, the viewport, a read performed through
      a hidden or already-running Office instance, a read taken through a
      temporary copy).

      true otherwise. That covers everything that deletes, replaces,
      overwrites, clears, reorders, moves, applies a batch of edits, saves
      over the document the user has open, or writes an output file it may
      silently overwrite. It also covers every tool that writes into an
      existing document, because the pre-write backup these servers take
      is defeatable by the tool's own `backup=False` argument and so
      cannot be claimed as guaranteed reversibility, and everything whose
      reversibility could not be PROVEN by reading the code.

  Read-only tools carry no destructiveHint: the field is meaningful only
  when readOnlyHint is false, and a value there would be noise.

* **idempotentHint** -- true only where repeating the identical call
  obviously lands the same state: the pack switches, whose own docstrings
  say idempotent, and the whole-value setters that take an address and a
  value and carry no action selector. Everything else is left unset rather
  than guessed.

* **openWorldHint** -- true on every tool that reaches a remote site, which is
  nearly all of them. The four exceptions in CLOSED_WORLD read or write
  only local state: the recipe book, the saved-workflow store, and this
  session's own action log.

An unclassified name RAISES at registration, the same contract
policy/readonly.py already holds this surface to.
"""

from __future__ import annotations

#: tool name -> the title a client shows. Unique, at most 40
#: characters, and mirrored into docs/TOOL_TITLES.md, which a test
#: checks against this table so the published English cannot drift
#: from what goes on the wire.
TITLES: dict[str, str] = {
    "aggregate":         "Extract Across URLs",
    "batch":             "Run Several Actions",
    "click":             "Click",
    "do":                "Act on a Goal",
    "download":          "Download",
    "emulate":           "Emulate Page Environment",
    "evaluate_script":   "Evaluate Script",
    "export_data":       "Export Data",
    "export_har":        "Export HAR",
    "export_pdf":        "Export PDF",
    "extract_fields":    "Extract Fields",
    "extract_page":      "Extract Page",
    "fill_form":         "Fill Form",
    "find_and_act":      "Find and Act",
    "find_elements":     "Find Elements",
    "get_accessibility": "Get Accessibility",
    "get_article":       "Get Article",
    "get_audit":         "Read the Action Log",
    "get_links":         "Get Links",
    "get_list":          "Get List",
    "get_metadata":      "Get Metadata",
    "get_page_errors":   "Get Page Errors",
    "get_page_view":     "Get Page View",
    "get_request":       "Get Request",
    "get_table":         "Get Table",
    "get_text":          "Get Text",
    "get_workflows":     "Get Workflows",
    "handle_dialog":     "Handle Dialog",
    "list_console":      "List Console",
    "list_requests":     "List Requests",
    "list_workflows":    "List Workflows",
    "load_auth_state":   "Load Auth State",
    "manage_clipboard":  "Manage Clipboard",
    "manage_cookies":    "Manage Cookies",
    "manage_session":    "Manage Session",
    "manage_storage":    "Manage Storage",
    "manage_tabs":       "Manage Tabs",
    "monitor":           "Watch a URL for Change",
    "navigate":          "Navigate",
    "press_keys":        "Press Keys",
    "read_image_text":   "Read Image Text",
    "read_pages":        "Read Pages",
    "run_workflow":      "Run Workflow",
    "save_auth_state":   "Save Auth State",
    "save_page":         "Save Page",
    "save_workflow":     "Save Workflow",
    "scroll":            "Scroll",
    "set_routing":       "Set Routing",
    "take_screenshot":   "Take Screenshot",
    "type_text":         "Type Text",
    "upload_file":       "Upload File",
    "wait_for":          "Wait For",
}

#: destructiveHint: true. Deletes, replaces, overwrites, clears,
#: reorders, moves, batch-edits, saves over the open document, writes
#: an output file it may overwrite, acts on a live page, or could not
#: be proven reversible. docs/TOOL_ANNOTATIONS.md carries the reason
#: for every row.
DESTRUCTIVE: frozenset[str] = frozenset({
    "aggregate", "batch", "click", "do", "download", "evaluate_script",
    "export_data", "export_har", "export_pdf", "fill_form",
    "find_and_act", "handle_dialog", "load_auth_state",
    "manage_clipboard", "manage_cookies", "manage_session",
    "manage_storage", "manage_tabs", "monitor", "navigate",
    "press_keys", "read_pages", "run_workflow", "save_auth_state",
    "save_page", "save_workflow", "take_screenshot", "type_text",
    "upload_file", "wait_for"
})

#: destructiveHint: false. Every code path either only ADDS, or
#: changes no user data at all. Each row's reason is in
#: docs/TOOL_ANNOTATIONS.md.
NON_DESTRUCTIVE: frozenset[str] = frozenset({
    "emulate", "read_image_text", "scroll", "set_routing"
})

#: idempotentHint: true. Repeating the identical call lands the same
#: state. Anything absent here is left UNSET rather than guessed.
IDEMPOTENT: frozenset[str] = frozenset({

})

#: openWorldHint: false. These four never reach a remote site.
CLOSED_WORLD: frozenset[str] = frozenset({
    "get_audit", "get_workflows", "list_workflows", "save_workflow"
})


def title(name: str) -> str:
    """The MCP title for one tool. Unknown names RAISE, because a tool that
    reaches tools/list without a title fails the directory's annotation
    requirement and a name-shaped fallback would hide that from the test."""
    try:
        return TITLES[name]
    except KeyError:
        raise RuntimeError(
            f"tool {name!r} has no title in this module. Every registered "
            f"tool needs one: the Anthropic directory requires a title on "
            f"every tool, and a generated fallback would pass the check "
            f"while shipping 'Com Export Pdf' to a user."
        ) from None


def destructive_hint(name: str) -> bool | None:
    """The MCP destructiveHint, or None for a read-only tool, where the
    field carries no meaning. An unclassified mutating name returns None
    and `annotations` raises on it."""
    if name in NON_DESTRUCTIVE:
        return False
    if name in DESTRUCTIVE:
        return True
    return None


def idempotent_hint(name: str) -> bool | None:
    """True where repeating the call lands the same state, else None. Never
    false: an unlisted tool is unclassified, not proven non-idempotent."""
    return True if name in IDEMPOTENT else None


def open_world_hint(name: str) -> bool:
    """True for every tool that reaches a remote site."""
    return name not in CLOSED_WORLD


def annotations(name: str, read_only: bool) -> dict:
    """The full annotation dict for one tool, ready for registration.
    destructiveHint is omitted on read-only tools and idempotentHint is
    omitted where it was not classified, so an absent field means
    "undeclared" rather than "false"."""
    ann: dict = {
        "title": title(name),
        "readOnlyHint": read_only,
        "openWorldHint": open_world_hint(name),
    }
    if not read_only:
        destructive = destructive_hint(name)
        if destructive is None:
            raise RuntimeError(
                f"tool {name!r} is not classified DESTRUCTIVE or "
                f"NON_DESTRUCTIVE in this module. Every tool that can "
                f"change something must declare whether the change may be "
                f"destructive before it can be registered."
            )
        ann["destructiveHint"] = destructive
    idempotent = idempotent_hint(name)
    if idempotent is not None:
        ann["idempotentHint"] = idempotent
    return ann
