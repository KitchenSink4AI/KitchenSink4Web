"""Tool titles, declared by name.

Every registered tool ships a `title` annotation: the Anthropic Connectors
Directory requires one, and a client shows it to a human instead of the
raw tool name. `readOnlyHint` lives in policy/readonly.py and is not repeated here.

The title is derived mechanically, so that a new tool gets one without
anyone inventing it: the tool name, split on underscores, Title Cased,
with known acronyms upper-cased, a leading `com_` replaced by the host
application's name, and short function words kept lowercase inside the
phrase. A handful of names too short or too generic to read as a title
take a phrase from the first clause of their own description instead;
those are the only hand-written strings in the table, and
docs/TOOL_TITLES.md marks each one.

Titles are unique within this server and none exceeds 40 characters. An
unknown name RAISES at registration, the same contract policy/readonly.py
already holds this surface to.
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


def annotations(name: str, read_only: bool) -> dict:
    """The annotation dict for one tool, ready for registration."""
    return {
        "title": title(name),
        "readOnlyHint": read_only,
    }
