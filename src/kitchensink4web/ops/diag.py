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

import os
import re

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


def _attach_recorder(session) -> None:
    """Session-open hook, loaded-pack-guarded per the seam contract."""
    from .. import packs
    if not packs.is_pack_loaded("diagnostics"):
        return
    if getattr(session, "_console_attached", False):
        return
    session._console_attached = True
    store = _store(session)

    def on_console(msg):
        try:
            level = {"warning": "warning"}.get(msg.type, msg.type)
            if level not in _LEVELS:
                level = "log"
            store["messages"].append(
                {"level": level, "text": common.clip(msg.text, 300)})
            store["seen"] += 1
            # bound raw retention; the dedup pass reads this list
            if len(store["messages"]) > 20000:
                del store["messages"][:10000]
        except Exception:
            pass

    def on_pageerror(exc):
        try:
            text = str(exc)
            store["errors"].append({
                "message": common.clip(text.splitlines()[0], 300),
                "stack": common.clip(text, 1200)})
        except Exception:
            pass

    for page in session.pages.values():
        page.page.on("console", on_console)
        page.page.on("pageerror", on_pageerror)
    # New pages in the context inherit the listeners too.
    session.context.on("page", lambda p: (
        p.on("console", on_console), p.on("pageerror", on_pageerror)))


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
    """
    levels = _LEVELS + ("all",)
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
    return {
        "session": sess.session_id, "level": level,
        "messages": rows,
        "totals": {"lines_seen": store["seen"], "lines_at_level": kept,
                   "unique_shapes": len(groups),
                   "collapsed_by_dedup": max(0, collapsed)},
        "note": ("rows are deduplicated by message shape (digits and ids "
                 "normalized) and ranked by repeat count; the default is "
                 "errors only"),
    }


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
    sess = common.session_of(session)
    store = _store(sess)
    errors = store["errors"][-max(1, int(limit)):]
    return {
        "session": sess.session_id,
        "page_errors": errors,
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
    page can, exfiltrate it, or act as the logged-in user. It is off by
    default (this pack is opt-in), absent under read-only mode, gated so a
    human confirms before it runs, and every call is audited. Returns the
    script's JSON-serializable return value. Prefer the structured read and
    action tools for anything they can do; reach for this only when no
    other tool expresses what you need, and expect the confirmation prompt.
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
