# Tool annotations

Every tool this server registers ships four MCP annotations: `title`
(see [TOOL_TITLES.md](TOOL_TITLES.md)), `readOnlyHint`, `destructiveHint`
and `openWorldHint`, plus `idempotentHint` where it is obviously true.
The tables are GENERATED from `src/kitchensink4web/policy/tool_annotations.py` and a test in
`tests/unit/test_tool_annotations.py` fails if they disagree, so a row
here is what goes on the wire.

## The rule for `destructiveHint`

ONE rule decides every row, and it is stated here so a reviewer can
dispute any single one of them.

**`false`** only when every code path either

* **(a)** adds new content or a new file without replacing anything that
  was already there, with creation refusing an existing target, or
* **(b)** changes no user data at all: this session's tool surface, the
  viewport, a read performed through a hidden or already-running Office
  instance, or a read taken through a temporary copy.

**`true`** otherwise. That covers everything that deletes, replaces,
overwrites, clears, reorders, moves, applies a batch of edits, saves over
the document the user has open, writes an output file it may silently
overwrite, or acts on a live page. It also covers **every tool that writes
into an existing document**, because the pre-write backup these servers
take is defeatable by the tool's own `backup=False` argument and therefore
cannot be claimed as guaranteed reversibility. And it covers everything
whose reversibility could not be PROVEN by reading the code: an unproven
claim of safety is the one thing this annotation must not make.

Read-only tools carry no `destructiveHint`. The field is meaningful only
when `readOnlyHint` is false, and a value there would be noise.

`idempotentHint` is set true only where repeating the identical call
obviously lands the same state: the pack switches, whose own docstrings
say idempotent, and the whole-value setters that take an address and a
value and carry no action selector. Everything else is left unset rather
than guessed; an absent hint means undeclared, never false.

`openWorldHint` is `true` on every tool that reaches a remote site, which is nearly all of
them. The four exceptions are `get_workflows`, `list_workflows`,
`save_workflow` and `get_audit`, which read or write only local state:
the recipe book, the saved-workflow store, and this session's own
action log.

## Tools that may perform destructive updates (30)

`destructiveHint: true`.

| Tool | Why |
|---|---|
| `aggregate` | navigates to every URL it is given |
| `batch` | runs several page actions per call, clicks included |
| `click` | acts on a live page; the server cannot undo what the site does next |
| `do` | resolves a goal to a click; the server cannot undo what the site does next |
| `download` | writes a file to disk with no proven existing-file check |
| `evaluate_script` | runs caller-supplied script in the page |
| `export_data` | writes a data file with no proven existing-file check |
| `export_har` | writes a HAR file with no proven existing-file check |
| `export_pdf` | writes a PDF with no proven existing-file check |
| `fill_form` | writes values into a live form and may submit it |
| `find_and_act` | clicks the element it resolves |
| `handle_dialog` | answering a native dialog is the click the page was waiting for |
| `load_auth_state` | replaces the browser's cookies and storage wholesale |
| `manage_clipboard` | writes the clipboard the human also uses |
| `manage_cookies` | writes and clears cookies |
| `manage_session` | creates and destroys browser processes |
| `manage_storage` | writes and clears localStorage and sessionStorage |
| `manage_tabs` | closes tabs, and a closed page's state is gone |
| `monitor` | navigates on a timer and writes files while it runs |
| `navigate` | issues an outbound request whose server-side effect cannot be undone |
| `press_keys` | sends keystrokes to a live page |
| `read_pages` | follows the page's own next-page links, navigating each hop |
| `run_workflow` | replays recorded steps, clicks and navigations included |
| `save_auth_state` | writes a credential file with no proven existing-file check |
| `save_page` | writes page files with no proven existing-file check |
| `save_workflow` | writes a workflow file that may already exist |
| `take_screenshot` | writes an image file with no proven existing-file check |
| `type_text` | types into a live page |
| `upload_file` | hands a local file to a remote site |
| `wait_for` | condition='js' evaluates a caller-supplied predicate in the page |
## Tools that may not (4)

`destructiveHint: false`.

| Tool | Why |
|---|---|
| `emulate` | changes reversible session settings and returns the prior state; no page or file content is touched |
| `read_image_text` | recognizes text in pixels this process already holds; writes no file and opens no connection |
| `scroll` | moves the viewport; nothing on the page or on disk changes |
| `set_routing` | changes reversible session settings and returns the prior state; no page or file content is touched |
## Read-only tools (18)

`readOnlyHint: true`, and no `destructiveHint`: the field carries no
meaning for a tool that changes nothing. The classification itself lives
in `policy/readonly.py` and is guarded by
`tests/unit/test_readonly_invariant.py`.

`extract_fields`, `extract_page`, `find_elements`, `get_accessibility`, `get_article`, `get_audit`, `get_links`, `get_list`, `get_metadata`, `get_page_errors`, `get_page_view`, `get_request`, `get_table`, `get_text`, `get_workflows`, `list_console`, `list_requests`, `list_workflows`

## Idempotent tools (0)

`idempotentHint: true`.

None: nothing in this server is an unambiguous whole-value setter.
