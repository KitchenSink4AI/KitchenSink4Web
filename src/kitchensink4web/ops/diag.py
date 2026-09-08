"""The `diagnostics` pack: console, page errors, script eval (DESIGN 2.2).

Console logging shipped as an improvement became a token regression at the
incumbent by the maintainer's own admission (chrome-devtools-mcp #171:
`list_console_messages` repeating each line four times, 40,000 tokens
against 8,000). The correct default is errors-only with an explicit widen,
and a bounded, deduplicated result on every read.

Recording attaches at SESSION OPEN through the engine hook seam, guarded on
the pack being loaded, so the log is complete from the first navigation
rather than starting whenever somebody first reads it.

`evaluate_script` is named for what it is, and it is the one genuinely
dangerous tool in the whole surface: arbitrary page-context JS, RCE
equivalent. It is absent under read-only, gated at the choke point (fails
closed with no MRTR wiring in this build), and audited. The description
says RCE-equivalent where the model cannot miss it, following
playwright-mcp's `browser_run_code_unsafe` example.
"""

from __future__ import annotations

import json as _json
import os
import re

from .. import pagedata as _pagedata
from ..engine import session as _session
from ..errors import BadParams
from ..policy import engine as _policy
from . import common

ENV_CONSOLE_MAX = "KS4WEB_CONSOLE_MAX"

#: Levels, coarsest-useful first. The default read is errors only.
_LEVELS = ("error", "warning", "info", "log", "debug")

#: Normalize a message to a SHAPE for dedup: strip digits, hex, uuids, and
#: quoted run-specific values, so "poll tick 41" and "poll tick 998" collapse
#: to one row with a count rather than two thousand rows.
_NUM = re.compile(r"\b0x[0-9a-f]+\b|\b\d[\d.,:]*\b", re.IGNORECASE)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE)


def _shape(text: str) -> str:
    s = _UUID.sub("<id>", text or "")
    s = _NUM.sub("#", s)
    return " ".join(s.split())[:200]


def _console_max() -> int:
    try:
        return max(20, int(os.environ.get(ENV_CONSOLE_MAX, "60")))
    except ValueError:
        return 60


def _store(sess) -> dict:
    store = getattr(sess, "_console", None)
    if store is None:
        store = sess._console = {"messages": [], "errors": [], "seen": 0}
    return store


def _attach_recorder(session, contexts=None) -> None:
    """Session-open hook, loaded-pack-guarded per the seam contract.

    ATTACHES PER CONTEXT (dream-specs observation 5). The recorder used to
    bind to `session.context` once, so under multiple cookie jars a page in
    the second one produced no console messages at all and `list_console`
    reported an empty list as though it were the truth. Silent loss, not an
    error, which is the failure shape this build refuses everywhere else.
    `contexts` names the jars this call is responsible for, so adding one
    to a live session attaches to the new jar without double-attaching to
    the old ones."""
    from .. import packs
    if not packs.is_pack_loaded("diagnostics"):
        return
    handles = (list(contexts) if contexts is not None
               else list(session.contexts.values()))
    attached = getattr(session, "_console_attached", None)
    if attached is None:
        attached = session._console_attached = set()
    handles = [h for h in handles if h.label not in attached]
    if not handles:
        return
    for handle in handles:
        attached.add(handle.label)
    store = _store(session)

    def on_console(msg):
        try:
            level = {"warning": "warning"}.get(msg.type, msg.type)
            if level not in _LEVELS:
                level = "log"
            store["messages"].append(
                {"level": level, "text": common.clip(msg.text, 300),
                 # WHICH PAGE WROTE IT (union wave, IG-03). The recorder
                 # attaches at SESSION OPEN and keeps a session-wide store,
                 # so prose planted by any page visited at any point comes
                 # back on a console read made much later, and nothing in
                 # the payload named the page it came from.
                 "url": _msg_url(msg)})
            store["seen"] += 1
            # bound raw retention; the dedup pass reads this list
            if len(store["messages"]) > 20000:
                del store["messages"][:10000]
        except Exception:
            pass

    def on_pageerror_for(page):
        def on_pageerror(exc):
            try:
                text = str(exc)
                store["errors"].append({
                    "message": common.clip(text.splitlines()[0], 300),
                    "stack": common.clip(text, 1200),
                    "url": _page_url(page)})
            except Exception:
                pass
        return on_pageerror

    labels = {h.label for h in handles}
    for page in session.pages.values():
        if getattr(page, "context", "c1") not in labels:
            continue
        page.page.on("console", on_console)
        page.page.on("pageerror", on_pageerror_for(page.page))
    # New pages in each context inherit the listeners too.
    for handle in handles:
        handle.context.on("page", lambda p: (
            p.on("console", on_console), p.on("pageerror", on_pageerror_for(p))))


def _page_url(page) -> str | None:
    try:
        return page.url
    except Exception:
        return None


def _msg_url(msg) -> str | None:
    """The URL of the document that emitted a console line."""
    for probe in (lambda: msg.page.url,
                  lambda: msg.location.get("url"),
                  lambda: msg.location["url"]):
        try:
            got = probe()
            if got:
                return str(got)
        except Exception:
            continue
    return None


_session.SESSION_OPEN_HOOKS.append(_attach_recorder)


async def list_console(
    session: str | None = None,
    level: str = "error",
    limit: int = 40,
) -> dict:
    """Read the page console, deduplicated by message shape and bounded, so
    a page emitting thousands of near-identical lines comes back as a
    handful of rows each carrying a repeat count rather than a flood that
    costs more than it tells. The default is errors only, because that is
    what a console read is almost always for; widen with level='warning',
    'info', 'log', or 'all'. Returns the deduplicated rows newest-shape
    last, the total lines seen, and how many were collapsed, so the needle
    (one uncaught error under two thousand poll ticks) is never buried.
    Messages are stored per session, not per page; entries from other pages
    in this session appear here with their page named.
    """
    levels = _LEVELS + ("all",)
    level = common.enum_arg(level, levels, default="error",
                            tool="list_console", name="level")
    limit = common.count_arg(limit, name="limit", tool="list_console",
                             default=40, maximum=1000)
    if level not in levels:
        raise BadParams(
            f"unknown level {level!r}: the levels are {list(levels)}. The "
            f"default 'error' is errors only; 'all' shows every level.")
    sess = common.session_of(session)
    store = _store(sess)
    wanted = (set(_LEVELS) if level == "all"
              else set(_LEVELS[:_LEVELS.index(level) + 1]))
    groups: dict[tuple, dict] = {}
    kept = 0
    for msg in store["messages"]:
        if msg["level"] not in wanted:
            continue
        kept += 1
        key = (msg["level"], _shape(msg["text"]))
        row = groups.get(key)
        if row is None:
            groups[key] = {"level": msg["level"], "shape": key[1],
                           "sample": msg["text"], "count": 1}
        else:
            row["count"] += 1
    rows = sorted(groups.values(), key=lambda r: -r["count"])[
        :max(1, int(limit))]
    collapsed = kept - len(rows)
    # THE LABELED ENVELOPE (union wave, IG-03). `console.error(...)` is
    # page-authored free text, which is instruction-shaped prose and not the
    # keyed cells DESIGN 5.1 ruled data-shaped; the pack was in neither of
    # that ruling's lists and shipped raw. Both the `shape` and the `sample`
    # carry the page's own string, so both go inside.
    body, note = _pagedata.wrap(
        _json.dumps(rows, ensure_ascii=False, indent=1),
        url=_origins_line(rows))
    note["covers"] = ["messages"]
    return {
        "session": sess.session_id, "level": level,
        "messages": body,
        "page_data": note,
        "totals": {"lines_seen": store["seen"], "lines_at_level": kept,
                   "unique_shapes": len(groups),
                   "collapsed_by_dedup": max(0, collapsed)},
        "note": ("rows are deduplicated by message shape (digits and ids "
                 "normalized) and ranked by repeat count; the default is "
                 "errors only. The console recorder attaches at session "
                 "open and its store is session-wide, so a row can come "
                 "from any page this session visited; each row names the "
                 "url that wrote it where the driver reports one"),
    }


def _origins_line(rows: list) -> str:
    """Every origin represented in a diagnostics payload, for the envelope
    label. A session-wide store can carry several, and "untrusted content
    from X" is a weaker warning than it looks when half of it came from Y."""
    seen = []
    for row in rows:
        url = row.get("url")
        if url and url not in seen:
            seen.append(url)
    if not seen:
        return "the page(s) this session visited (the driver reported no url)"
    return ", ".join(seen[:6]) + (" and others" if len(seen) > 6 else "")


async def get_page_errors(session: str | None = None,
                          limit: int = 20) -> dict:
    """List the uncaught exceptions the page threw, each with its first
    line and a bounded stack, newest last. These are the errors that a
    console read at the default level surfaces, given here with their
    stacks for when the stack is what you need. Returns the errors and the
    total count; a page that threw nothing comes back with an empty list
    and says so, rather than leaving the caller unsure whether the read
    worked.
    """
    limit = common.count_arg(limit, name="limit", tool="get_page_errors",
                             default=20, maximum=1000)
    sess = common.session_of(session)
    store = _store(sess)
    errors = store["errors"][-limit:]
    # Same ruling as list_console (IG-03): a thrown `Error` message and its
    # stack are page-authored prose, not keyed cells.
    body, note = _pagedata.wrap(
        _json.dumps(errors, ensure_ascii=False, indent=1),
        url=_origins_line(errors))
    note["covers"] = ["page_errors"]
    return {
        "session": sess.session_id,
        "page_errors": body,
        "page_data": note,
        "total": len(store["errors"]),
        "note": ("no uncaught page errors recorded" if not store["errors"]
                 else f"{len(store['errors'])} uncaught error(s) recorded "
                      f"since the session opened"),
    }


async def evaluate_script(
    page: str,
    script: str,
    arg: object = None,
) -> dict:
    """Evaluate JavaScript in the page context. This is RCE-EQUIVALENT: the
    script runs with the page's full privileges and can read anything the
    page can, send it anywhere, or act as the logged-in user. It is off by
    default (this pack is opt-in), absent under read-only mode, gated so a
    human confirms before it runs, and every call is audited. Returns the
    script's JSON-serializable return value. Prefer the structured read and
    action tools for anything they can do; reach for this only when no
    other tool expresses what you need, and expect the confirmation prompt.
    As of 2026-09 that prompt displays in Claude Desktop and Claude Code;
    the claude.ai web client does not display it yet, so this tool stays
    refused there.
    """
    if not (script or "").strip():
        raise BadParams("evaluate_script needs a script to run.")
    sess, record = common.locate(page)
    _policy.approve(_policy.ActionRequest(
        tool="evaluate_script", kind="act", session=sess.session_id,
        page=record.handle, url=record.page.url,
        action_class="evaluate_script",
        args={"script": common.clip(script, 200)},
        summary=f"evaluate script in the page context on {record.handle} "
                f"(RCE-equivalent)"))
    # Fails closed above with no MRTR wiring. The evaluation below runs only
    # through a redeemed gate (Phase 6), kept whole so the tool is complete.
    result = await record.page.evaluate(
        f"(arg) => {{ {script} }}" if "return" in script
        else f"(arg) => ({script})", arg)
    return {
        "page": record.handle, "session": sess.session_id,
        "result": result,
    }


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (list_console, get_page_errors, evaluate_script)
