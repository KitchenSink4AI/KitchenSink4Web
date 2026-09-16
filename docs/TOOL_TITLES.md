# Tool titles

Every tool this server registers ships a `title` annotation, which is what
the Anthropic Connectors Directory requires and what a client shows in
place of the raw tool name. This table is GENERATED from
`src/kitchensink4web/policy/tool_annotations.py` and a test in `tests/unit/test_tool_annotations.py`
fails if the two ever disagree, so the English here is the English on the
wire.

## How a title is derived

The rule is mechanical, so that a new tool gets a title without anyone
inventing one:

1. split the tool name on underscores;
2. replace a leading `com_` with the host application's name and collapse
   an immediately repeated word (`com_word_status` -> `Word Status`);
3. upper-case known acronyms (`pdf` -> `PDF`, `svg` -> `SVG`), Title Case
   the rest, and keep short function words lowercase inside the phrase
   (`add_equation_to_shape` -> `Add Equation to Shape`);
4. a name too short or too generic to read as a title takes a phrase from
   the first clause of its own description instead. Those are the only
   hand-written strings here and the Source column marks them.

Titles are unique within this server and none exceeds 40 characters. No
title carries product or marketing language.

52 tools.

| Tool | Title | Source |
|---|---|---|
| `aggregate` | Extract Across URLs | first clause of its description |
| `batch` | Run Several Actions | first clause of its description |
| `click` | Click | mechanical |
| `do` | Act on a Goal | first clause of its description |
| `download` | Download | mechanical |
| `emulate` | Emulate Page Environment | first clause of its description |
| `evaluate_script` | Evaluate Script | mechanical |
| `export_data` | Export Data | mechanical |
| `export_har` | Export HAR | mechanical |
| `export_pdf` | Export PDF | mechanical |
| `extract_fields` | Extract Fields | mechanical |
| `extract_page` | Extract Page | mechanical |
| `fill_form` | Fill Form | mechanical |
| `find_and_act` | Find and Act | mechanical |
| `find_elements` | Find Elements | mechanical |
| `get_accessibility` | Get Accessibility | mechanical |
| `get_article` | Get Article | mechanical |
| `get_audit` | Read the Action Log | first clause of its description |
| `get_links` | Get Links | mechanical |
| `get_list` | Get List | mechanical |
| `get_metadata` | Get Metadata | mechanical |
| `get_page_errors` | Get Page Errors | mechanical |
| `get_page_view` | Get Page View | mechanical |
| `get_request` | Get Request | mechanical |
| `get_server_info` | Get Server Info | mechanical |
| `get_table` | Get Table | mechanical |
| `get_text` | Get Text | mechanical |
| `get_workflows` | Get Workflows | mechanical |
| `handle_dialog` | Handle Dialog | mechanical |
| `list_console` | List Console | mechanical |
| `list_requests` | List Requests | mechanical |
| `list_workflows` | List Workflows | mechanical |
| `load_auth_state` | Load Auth State | mechanical |
| `manage_clipboard` | Manage Clipboard | mechanical |
| `manage_cookies` | Manage Cookies | mechanical |
| `manage_session` | Manage Session | mechanical |
| `manage_storage` | Manage Storage | mechanical |
| `manage_tabs` | Manage Tabs | mechanical |
| `monitor` | Watch a URL for Change | first clause of its description |
| `navigate` | Navigate | mechanical |
| `press_keys` | Press Keys | mechanical |
| `read_image_text` | Read Image Text | mechanical |
| `read_pages` | Read Pages | mechanical |
| `run_workflow` | Run Workflow | mechanical |
| `save_auth_state` | Save Auth State | mechanical |
| `save_page` | Save Page | mechanical |
| `save_workflow` | Save Workflow | mechanical |
| `scroll` | Scroll | mechanical |
| `set_routing` | Set Routing | mechanical |
| `take_screenshot` | Take Screenshot | mechanical |
| `type_text` | Type Text | mechanical |
| `upload_file` | Upload File | mechanical |
| `wait_for` | Wait For | mechanical |
