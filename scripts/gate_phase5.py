"""The Phase 5 gate: the capability packs, proven against real pages, plus
the phase-level properties PLAN Phase 5 names and the field-test rulings
folded in.

Parts, each GREEN or RED, written to gates/phase5.json:

  1 surface_conformant   the built surface is the designed surface: 40 tools,
                         each pack module's TOOLS matches its design row, and
                         --packs full registers them all over a real client
  2 read_only_invariant  extended to the packs: under a read-only grade NO
                         mutating pack tool is in tools/list, identically to
                         the lite core; the read pack tools survive
  3 media_type_correct   a screenshot round-trip cannot produce a mismatched
                         media type under any code path (the #1211 defect that
                         permanently poisons sessions), and unidentifiable
                         bytes are refused rather than mislabeled
  4 console_bounded      list_console on the thousand-line flood fixture
                         returns a bounded, deduplicated result that still
                         carries the two needle errors
  5 extract_deterministic  a spanned table extracts rectangular with spans
                         carried, a div-table is detected and named, and
                         extract_fields is honest about what it cannot fill
  6 network_redacts      request recording attaches at session open and
                         credential-bearing headers are masked in every read
  7 default_and_unlock   the shipped default is browse (read-only) and a
                         forced call to an absent mutating tool returns a
                         GUIDED refusal (grade, why, human unlock) rather
                         than the bare framework string, tool still absent
  8 orphan_census        every session opened by the gate is closed and no
                         owned browser PID survives (the family hygiene claim
                         holds across the new surface)

Exit 0 only when every part is green.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import importlib
import json
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastmcp import Client  # noqa: E402

from kitchensink4web import packs, server  # noqa: E402
from kitchensink4web.engine import hygiene  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402
from kitchensink4web.errors import (AmbiguousLocation,  # noqa: E402
                                    ConfirmationRequired, UnsupportedContent)
from kitchensink4web.ops import (capture, common, diag,  # noqa: E402
                                 extract, net)
from kitchensink4web.ops import lite  # noqa: E402
from kitchensink4web.policy import budgets, credentials, readonly  # noqa: E402

CORPUS = ROOT / "corpus"
GATES = ROOT / "gates"
PARTS: dict[str, dict] = {}

PACK_MODULES = {
    "extract": "kitchensink4web.ops.extract",
    "capture": "kitchensink4web.ops.capture",
    "network": "kitchensink4web.ops.net",
    "storage": "kitchensink4web.ops.storage",
    "files": "kitchensink4web.ops.files",
    "diagnostics": "kitchensink4web.ops.diag",
    "workflows": "kitchensink4web.ops.workflows",
}

META_PAGE = (
    b"<!doctype html><html lang=en><head><meta charset=utf-8>"
    b"<title>Meta</title>"
    b"<meta property='og:title' content='OG Title'>"
    b"<script type='application/ld+json'>"
    b'{"@context":"https://schema.org","@type":"Product","name":"Widget",'
    b'"offers":{"@type":"Offer","price":"19.99"}}</script></head>'
    b"<body><main><h1>Widget</h1>"
    b"<dl><dt>Material</dt><dd>Aluminium</dd></dl>"
    b"<ul id=feats><li>A</li><li>B</li></ul></main></body></html>")


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/meta":
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.send_header("content-length", str(len(META_PAGE)))
            self.end_headers()
            self.wfile.write(META_PAGE)
            return
        return super().do_GET()


def part(name: str, green: bool, **evidence):
    PARTS[name] = {"green": bool(green), **evidence}
    print(f"  {name:<22} {'GREEN' if green else 'RED'}")
    for key, value in evidence.items():
        if not green:
            print(f"      {key}: {value}")


async def _list(**kw):
    server.configure(**kw)
    async with Client(server.mcp) as c:
        return sorted(t.name for t in await c.list_tools())


async def gate_surface_conformant():
    ev = {}
    parity = True
    for pack, modname in PACK_MODULES.items():
        module = importlib.import_module(modname)
        built = {fn.__name__ for fn in module.TOOLS}
        designed = set(packs.PLANNED_MEMBERS[pack])
        if built != designed:
            parity = False
            ev[f"{pack}_mismatch"] = sorted(built ^ designed)
    full = await _list(cli_packs=packs.pack_names(), read_only=False)
    ev["full_surface"] = len(full)
    # 40 until 2026-09-06, when find_and_act joined the lite core; 42
    # later that day with handle_dialog; 43 with get_article; 45 after
    # the small-parts wave added read_pages and manage_clipboard.
    green = parity and len(full) == 45
    part("surface_conformant", green, **ev)


async def gate_read_only_invariant():
    listed = set(await _list(cli_packs=packs.pack_names(), read_only="browse"))
    leaked = sorted(listed & readonly.MUTATING)
    reads_present = all(n in listed for n in
                        ("get_table", "get_metadata", "take_screenshot",
                         "list_requests", "list_console", "export_har"))
    part("read_only_invariant", not leaked and reads_present,
         mutating_leaked=leaked, read_tools_present=reads_present,
         surface_size=len(listed))


async def gate_media_type_correct(site):
    server.configure(cli_packs=packs.pack_names(), read_only=False)
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    ev = {}
    try:
        page = session.focused
        await lite.navigate(page=page, url=f"{site}/meta")
        ok = True
        for fmt in ("png", "jpeg"):
            res = await capture.take_screenshot(page=page, format=fmt)
            payload = getattr(res, "structured_content", res)
            fmt_ok = (payload["format"] == fmt
                      and payload["media_type"] == f"image/{fmt}")
            ev[f"{fmt}_media_type"] = payload["media_type"]
            ok = ok and fmt_ok
        # unidentifiable bytes are refused, never mislabeled.
        refused = False
        try:
            common.sniff_image(b"not-an-image-payload")
        except UnsupportedContent:
            refused = True
        ev["garbage_refused"] = refused
        part("media_type_correct", ok and refused, **ev)
    finally:
        await MANAGER.close(session.session_id)


async def gate_console_bounded(site):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    ev = {}
    try:
        page = session.focused
        await lite.navigate(page=page, url=f"{site}/b/console_flood.html")
        await session.pages[page].page.wait_for_timeout(300)
        errs = await diag.list_console(session=session.session_id,
                                       level="error")
        samples = " ".join(r["sample"] for r in errs["messages"])
        needles = "TypeError" in samples and "401" in samples
        allm = await diag.list_console(session=session.session_id,
                                       level="all")
        ev["lines_seen"] = allm["totals"]["lines_seen"]
        ev["rows_returned"] = len(allm["messages"])
        ev["collapsed"] = allm["totals"]["collapsed_by_dedup"]
        bounded = (allm["totals"]["lines_seen"] > 1000
                   and len(allm["messages"]) < 60)
        part("console_bounded", needles and bounded,
             needles_kept=needles, **ev)
    finally:
        await MANAGER.close(session.session_id)


async def gate_extract_deterministic(site):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    ev = {}
    try:
        page = session.focused
        await lite.navigate(page=page, url=f"{site}/b/tables.html")
        t0 = await extract.get_table(page=page, index=0)
        rect = all(len(r) == t0["table"]["columns"]
                   for r in t0["table"]["rows"])
        carried = any("North America" in " ".join(r)
                      for r in t0["table"]["rows"])
        t1 = await extract.get_table(page=page, index=1)
        divtable = t1["table"]["kind"] in ("div-table", "div-grid")
        ambiguous = False
        try:
            await extract.get_table(page=page)
        except AmbiguousLocation:
            ambiguous = True
        await lite.navigate(page=page, url=f"{site}/meta")
        fields = await extract.extract_fields(
            page=page, fields=["price", "nope_missing"])
        honest = (fields["fields"]["price"]["found"] is True
                  and fields["fields"]["nope_missing"]["found"] is False)
        ev.update(rectangular=rect, span_carried=carried,
                  divtable_named=divtable, inventory_refuses=ambiguous,
                  fields_honest=honest)
        part("extract_deterministic",
             rect and carried and divtable and ambiguous and honest, **ev)
    finally:
        await MANAGER.close(session.session_id)


async def gate_network_redacts(site):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    ev = {}
    try:
        page = session.focused
        await lite.navigate(page=page, url=f"{site}/meta")
        reqs = await net.list_requests(session=session.session_id)
        recorded = reqs["totals"]["recorded"] >= 1
        doc = next((r for r in reqs["requests"]
                    if r["resource_type"] == "document"), None)
        masked_ok = True
        if doc:
            got = await net.get_request(request_id=doc["id"],
                                        session=session.session_id)
            for name, value in (got.get("request_headers") or {}).items():
                if name.lower() in net.SENSITIVE_HEADERS \
                        and "masked" not in str(value):
                    masked_ok = False
        ev.update(recorded=reqs["totals"]["recorded"], masked_ok=masked_ok)
        part("network_redacts", recorded and masked_ok, **ev)
    finally:
        await MANAGER.close(session.session_id)


async def gate_default_and_unlock():
    os.environ.pop("KS4WEB_READ_ONLY", None)
    state = server.configure()          # bare launch
    default_browse = state["read_only"] == "browse"
    mutating_absent = not (set(state["registered"]) & readonly.MUTATING)

    async with Client(server.mcp) as c:
        res = await c.call_tool(
            "type_text",
            {"page": "p1", "location": {"ref": "e1"}, "text": "x"},
            raise_on_error=False)
    err = res.structured_content["error"]
    blob = json.dumps(err).lower()
    guided = (err["code"] == "READ_ONLY_MODE"
              and ("restart" in blob or "tick" in blob or "settings" in blob))
    not_bypass = all(t not in blob for t in
                     ("requeststate", "redeem", "elicitation/create"))
    part("default_and_unlock",
         default_browse and mutating_absent and guided and not_bypass,
         default=state["read_only"], guided_code=err["code"],
         not_bypass=not_bypass)


def gate_orphan_census(before_pids):
    after = {p["pid"] for p in hygiene.snapshot_processes()}
    survivors = [pid for pid in before_pids if pid in after
                 and hygiene.alive(pid)]
    part("orphan_census", not MANAGER.sessions and not survivors,
         open_sessions=sorted(MANAGER.sessions),
         owned_survivors=survivors)


async def main() -> int:
    print("PHASE 5 GATE")
    handler = functools.partial(_Handler, directory=str(CORPUS))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{httpd.server_address[1]}"
    for env in ("KS4WEB_READ_ONLY", "KS4WEB_DENY_ORIGINS",
                "KS4WEB_ALLOW_ORIGINS"):
        os.environ.pop(env, None)
    budgets.BOOK = budgets.BudgetBook()
    credentials.VAULT.clear()
    readonly.apply(False)
    owned_before = MANAGER.owned_pids()
    try:
        await gate_surface_conformant()
        await gate_read_only_invariant()
        # acting must be allowed for the pack behavior gates to resolve refs
        readonly.apply(False)
        await gate_media_type_correct(site)
        await gate_console_bounded(site)
        await gate_extract_deterministic(site)
        await gate_network_redacts(site)
        await gate_default_and_unlock()
    finally:
        await MANAGER.close_all()
        httpd.shutdown()
        credentials.VAULT.clear()
        readonly.apply(False)
    gate_orphan_census(owned_before)

    GATES.mkdir(exist_ok=True)
    out = GATES / "phase5.json"
    green = all(p["green"] for p in PARTS.values())
    out.write_text(json.dumps(
        {"measured_kst": time.strftime("%Y-%m-%d %H:%M"),
         "phase": 5,
         "packs": sorted(PACK_MODULES),
         "surface_tools": 40,
         "corpus": "B (pathological) plus a local meta/download fixture, "
                   "synthetic, never networked",
         "lane": "A(chromium) headless",
         "default_grade": readonly.DEFAULT_GRADE,
         "parts": PARTS, "green": green}, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"PHASE 5 GATE {'GREEN' if green else 'RED'}")
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
