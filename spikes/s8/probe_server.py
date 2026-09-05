"""S8 probe: a raw stdio MCP server that logs every wire message.

No framework on purpose: the point of S8 is to observe what the INSTALLED
client actually sends and does, so the server is plain JSON-RPC over
line-delimited stdio with a JSONL wire log (PROBE_LOG env var).

Tools:
  emit           returns exactly n_tokens tokens (tiktoken o200k_base)
  mrtr_gate      returns a 2026-07-28 MRTR-shaped input_required result
  elicit_gate    sends elicitation/create to the client and reports the answer
  confirm_submit a fail-closed-class simulation gated through elicitation
  slow_read      3s sleep, readOnlyHint true  (concurrency probe)
  slow_write     3s sleep, no annotations     (concurrency control)
  truncme        ~3,000-char description with a tail sentinel (truncation probe)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

LOG_PATH = os.environ.get("PROBE_LOG", os.path.join(os.path.dirname(__file__), "probe_log.jsonl"))

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("o200k_base")
except Exception:  # pragma: no cover
    _ENC = None

_pending: dict[int, asyncio.Future] = {}
_next_id = 1000
_writer_lock = asyncio.Lock()


def log(direction: str, msg) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "dir": direction, "msg": msg}) + "\n")


async def send(obj) -> None:
    async with _writer_lock:
        line = json.dumps(obj)
        log("out", obj)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


async def request_client(method: str, params) -> dict:
    """Server-initiated request (elicitation)."""
    global _next_id
    rid = _next_id
    _next_id += 1
    fut = asyncio.get_event_loop().create_future()
    _pending[rid] = fut
    await send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    try:
        return await asyncio.wait_for(fut, timeout=120)
    except asyncio.TimeoutError:
        return {"__timeout__": True}
    finally:
        _pending.pop(rid, None)


def emit_tokens(n: int) -> str:
    """Exactly n o200k_base tokens (best effort without tiktoken)."""
    parts = []
    i = 0
    if _ENC is None:
        return ("word%06d " % 0) * max(1, n // 3)
    total = 0
    while total < n:
        piece = f" {i:06d}"
        total += len(_ENC.encode(piece))
        parts.append(piece)
        i += 1
    text = "".join(parts)
    toks = _ENC.encode(text)
    if len(toks) > n:
        text = _ENC.decode(toks[:n])
    return text


TRUNC_DESC = (
    "Truncation probe tool. " + "The quick brown fox jumps over the lazy dog. " * 62
    + " HEAD-MARKER-AT-2000: " + "x" * 20 + ". "
    + "More filler to push well past two thousand characters so the client's "
      "silent truncation, if present, must cut before the tail. "
    + "z" * 120
    + " TAIL-SENTINEL-ZQXW9-THE-VERY-END"
)

TOOLS = [
    {
        "name": "emit",
        "description": "Returns exactly n_tokens tokens of numbered filler text ending in END-OF-EMIT.",
        "inputSchema": {"type": "object", "properties": {"n_tokens": {"type": "integer"}},
                        "required": ["n_tokens"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "mrtr_gate",
        "description": "Returns an MCP 2026-07-28 MRTR input_required result carrying requestState. Retry with inputResponses to complete.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string"},
            "inputResponses": {"type": "array", "items": {"type": "object"}},
            "requestState": {"type": "string"}}},
    },
    {
        "name": "elicit_gate",
        "description": "Sends an elicitation/create request to the client asking for confirmation, then reports the client's exact answer.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "confirm_submit",
        "description": "Simulated gated form submit: asks the human for confirmation via elicitation; submits only on accept.",
        "inputSchema": {"type": "object", "properties": {"form": {"type": "string"}}},
    },
    {
        "name": "slow_read",
        "description": "Sleeps 3 seconds then returns its start and end timestamps. Read-only.",
        "inputSchema": {"type": "object", "properties": {"tag": {"type": "string"}}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "slow_write",
        "description": "Sleeps 3 seconds then returns its start and end timestamps. Not marked read-only.",
        "inputSchema": {"type": "object", "properties": {"tag": {"type": "string"}}},
    },
    {
        "name": "truncme",
        "description": TRUNC_DESC,
        "inputSchema": {"type": "object", "properties": {}},
    },
]


_MANY = int(os.environ.get("PROBE_MANY_TOOLS", "0"))
if _MANY:
    _FILLER_DESC = (
        "Filler tool for the deferral probe. It does nothing useful and exists only "
        "to inflate the tool-definition bill past the client's deferral threshold. "
        + "It processes hypothetical widget batches with configurable strategies. " * 6
    )
    for _i in range(_MANY):
        TOOLS.append({
            "name": f"filler_{_i:03d}",
            "description": _FILLER_DESC,
            "inputSchema": {"type": "object", "properties": {
                "widget": {"type": "string", "description": "the widget batch identifier"},
                "strategy": {"type": "string", "description": "the processing strategy name"}}},
        })
    TOOLS.append({
        "name": "special_always",
        "description": "Deferral probe: this tool carries anthropic/alwaysLoad true and should stay in context.",
        "inputSchema": {"type": "object", "properties": {}},
        "_meta": {"anthropic/alwaysLoad": True},
    })
    TOOLS.append({
        "name": "special_hint",
        "description": "Deferral probe: carries a searchHint with distinctive nonsense words.",
        "inputSchema": {"type": "object", "properties": {}},
        "_meta": {"anthropic/searchHint": "zebraquantum unicornfjord obsidian carousel"},
    })


async def handle_tool_call(rid, name: str, args: dict):
    if name.startswith("filler_") or name in ("special_always", "special_hint"):
        return {"content": [{"type": "text", "text": f"{name} ran. MARKER-OK-4471"}]}
    if name == "emit":
        n = int(args.get("n_tokens", 100))
        text = emit_tokens(max(1, n - 8)) + " END-OF-EMIT"
        return {"content": [{"type": "text", "text": text}]}

    if name == "mrtr_gate":
        if args.get("inputResponses") or args.get("requestState"):
            # A retry arrived: MRTR round-tripped.
            return {"content": [{"type": "text", "text":
                    "MRTR-RETRY-RECEIVED requestState=%r inputResponses=%r" %
                    (args.get("requestState"), args.get("inputResponses"))}]}
        # First call: return the 2026-07-28 MRTR shape.
        return {
            "resultType": "input_required",
            "requestState": "probe-gate-token-8842",
            "inputRequests": [{
                "id": "q1",
                "method": "elicitation/create",
                "params": {
                    "message": "Probe gate: type CONFIRM to proceed with the gated action.",
                    "requestedSchema": {"type": "object", "properties": {
                        "answer": {"type": "string"}}, "required": ["answer"]},
                },
            }],
            "content": [{"type": "text", "text":
                        "input_required: answer the input request and retry with requestState."}],
        }

    if name in ("elicit_gate", "confirm_submit"):
        t0 = time.time()
        resp = await request_client("elicitation/create", {
            "message": ("Probe: confirm the simulated form submit?" if name == "confirm_submit"
                        else "Probe: please confirm (yes/no)."),
            "requestedSchema": {"type": "object", "properties": {
                "confirm": {"type": "boolean",
                            "description": "true to confirm, false to refuse"}},
                "required": ["confirm"]},
        })
        dt = time.time() - t0
        if resp.get("__timeout__"):
            return {"content": [{"type": "text", "text":
                    f"ELICIT-TIMEOUT after {dt:.1f}s: no response from client"}]}
        if "error" in resp:
            return {"content": [{"type": "text", "text":
                    f"ELICIT-ERROR after {dt:.1f}s: {json.dumps(resp['error'])}"}]}
        result = resp.get("result", {})
        action = result.get("action")
        content = result.get("content")
        if name == "confirm_submit":
            if action == "accept" and (content or {}).get("confirm") is True:
                return {"content": [{"type": "text", "text":
                        f"SUBMITTED after human confirmation ({dt:.1f}s round trip)."}]}
            return {"content": [{"type": "text", "text":
                    f"REFUSED-FAIL-CLOSED: elicitation action={action!r} content={content!r} "
                    f"({dt:.1f}s); nothing was submitted."}], "isError": True}
        return {"content": [{"type": "text", "text":
                f"ELICIT-ANSWER after {dt:.1f}s: action={action!r} content={content!r}"}]}

    if name in ("slow_read", "slow_write"):
        t0 = time.time()
        await asyncio.sleep(3)
        t1 = time.time()
        return {"content": [{"type": "text", "text":
                f"{name} tag={args.get('tag')} start={t0:.3f} end={t1:.3f}"}]}

    if name == "truncme":
        return {"content": [{"type": "text", "text": "truncme ran."}]}

    return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


async def handle(msg):
    if "method" not in msg:
        # A response to one of OUR requests (elicitation).
        rid = msg.get("id")
        fut = _pending.get(rid)
        if fut and not fut.done():
            fut.set_result(msg)
        return

    method = msg["method"]
    rid = msg.get("id")

    if method == "initialize":
        params = msg.get("params", {})
        await send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "probe", "version": "0.1"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        await send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}

        async def run():
            try:
                result = await handle_tool_call(rid, name, args)
            except Exception as e:  # pragma: no cover
                result = {"content": [{"type": "text", "text": f"probe error: {e!r}"}],
                          "isError": True}
            await send({"jsonrpc": "2.0", "id": rid, "result": result})

        asyncio.get_event_loop().create_task(run())
    elif method == "ping":
        await send({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif rid is not None:
        await send({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}})


async def main():
    # Windows: connect_read_pipe on sys.stdin silently delivers nothing under
    # the Proactor loop, so stdin is read on a thread.
    loop = asyncio.get_event_loop()
    log("meta", {"event": "probe start", "pid": os.getpid()})
    while True:
        line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            log("in-bad", line.decode("utf-8", "replace"))
            continue
        log("in", msg)
        await handle(msg)
    log("meta", {"event": "stdin closed"})


if __name__ == "__main__":
    asyncio.run(main())
