"""S8: raw JSON-RPC probe of KS4Web's own FastMCP server over stdio.

Checks: (a) does FastMCP 3.4.7 answer `server/discover` (MCP 2026-07-28 MUST);
(b) what protocolVersion it negotiates when offered 2026-07-28; (c) whether
tools/list is byte-identical across two fresh connections (launch-time packs).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")


def talk(msgs: list[dict], offered_version: str, timeout: float = 45.0) -> list[dict]:
    env = dict(os.environ)
    p = subprocess.Popen(
        [PY, "-X", "utf8", "-m", "kitchensink4web.server"],
        cwd=os.path.join(REPO, "src"), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    out: list[dict] = []
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": offered_version,
        "capabilities": {"elicitation": {}},
        "clientInfo": {"name": "s8-raw-probe", "version": "0"}}}
    payload = json.dumps(init) + "\n" \
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n" \
        + "".join(json.dumps(m) + "\n" for m in msgs)
    try:
        stdout, stderr = p.communicate(input=payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        stdout, stderr = p.communicate()
    _ = time  # keep import
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if "id" in obj:
            out.append(obj)
    if not out:
        sys.stderr.write((stderr or "")[-800:])
    return out


def main() -> None:
    findings = {}

    # (a)+(b): offer 2026-07-28, ask server/discover and tools/list.
    resp = talk([
        {"jsonrpc": "2.0", "id": 2, "method": "server/discover", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    ], offered_version="2026-07-28")
    by_id = {r.get("id"): r for r in resp}
    init_r = by_id.get(1, {})
    findings["negotiated_when_offered_2026_07_28"] = init_r.get("result", {}).get("protocolVersion")
    disc = by_id.get(2, {})
    findings["server_discover"] = (
        {"error": disc["error"]} if "error" in disc else
        {"result_keys": list(disc.get("result", {}).keys())} if "result" in disc else "NO RESPONSE")
    tl = by_id.get(3, {})
    tools1 = tl.get("result", {}).get("tools", [])
    findings["tools_count_conn1"] = len(tools1)
    h1 = hashlib.sha256(json.dumps(tools1, sort_keys=True).encode()).hexdigest()

    # (c): a second fresh connection, offering the client's real version.
    resp2 = talk([{"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}],
                 offered_version="2025-11-25")
    by_id2 = {r.get("id"): r for r in resp2}
    findings["negotiated_when_offered_2025_11_25"] = by_id2.get(1, {}).get("result", {}).get("protocolVersion")
    tools2 = by_id2.get(3, {}).get("result", {}).get("tools", [])
    findings["tools_count_conn2"] = len(tools2)
    h2 = hashlib.sha256(json.dumps(tools2, sort_keys=True).encode()).hexdigest()
    findings["tools_list_identical_across_connections"] = (h1 == h2)
    findings["sha256"] = h1[:16]

    print(json.dumps(findings, indent=1))


if __name__ == "__main__":
    main()
