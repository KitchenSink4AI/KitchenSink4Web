"""Smoke test for the KitchenSink4Web .mcpb bundles.

This repo ships TWO bundles, which is the difference from the siblings: the
shipped one (`bundle/manifest.json`) and the field-test one
(`bundle/dev/manifest.json`). They carry the same boxes and differ only in
which ones start ticked. Both are checked here, because a pack cycle that
only ever exercises one of them is how the other ships broken.

Checks, per bundle, in order:
  1. The .mcpb unzips and contains exactly manifest.json + icon.png.
  2. manifest.json parses, carries the required fields, declares the
     binary/uvx launcher shape, pins the PyPI version to the manifest
     version, wires every user_config box to the server's own environment
     variable, and has NO tools array (Smithery cli bug #787).
  3. Acting is OFF by default on both bundles. The safety default is not a
     field-test convenience.
  4. If the mcpb CLI is on PATH, `mcpb validate` passes on each extracted
     manifest.

Then, once for the pair (one package, one download):
  5. If uvx is available (PATH or next to this interpreter), launches
     `uvx kitchensink4web==<ver>` and performs a real MCP stdio initialize
     handshake, proving the launch command Claude Desktop will run actually
     starts the server.

TRAP, carried forward from the XL ship: right after a PyPI publish this step
false-fails until `uvx --refresh-package kitchensink4web`, because uv's index
cache goes stale and keeps resolving the version it already knew about.

Usage: python -X utf8 smoke_test.py [path/to/a.mcpb ...]
Exit code 0 = all mandatory checks passed (steps 4-5 skip with a note when
the tool is absent).
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
FAILURES = []

#: Every pack box, and the environment variable each one has to reach.
PACKS = ("extract", "capture", "network", "storage", "files", "diagnostics",
         "workflows", "accessibility")

#: The boxes that are not packs, and their variables.
PLAIN = {
    "allow_acting": "KS4WEB_ALLOW_ACTING",
    "consent_scope": "KS4WEB_CONSENT",
}

#: THE BOXES THAT START TICKED. Both are read-only capabilities, so the
#: safety default is untouched: acting is off, storage is off, and anything
#: that can change a page, reach the filesystem, or run a script is still a
#: deliberate tick. The field-test bundle adds storage on top.
DEFAULT_ON = ("extract", "capture")

#: Retired boxes. Browser selection is not an install-screen setting on
#: either bundle: the manifest schema has no enum type, a text box for a
#: lane or a channel name is a typo that breaks the install, and the engine
#: reads these variables directly for developers who need them. The
#: pre-authorization box joined them on 2026-09-08 for the same reason,
#: after one wave on the screen: it is a launch-file setting now, and the
#: teaching string says so.
#:
#: `all_packs` joined them the same day, for a reason only an install test
#: could find: the form is STATIC, so a master switch cannot make the ten
#: boxes below it visibly change, and a control that looks inert reads as
#: broken. KS4WEB_ALL_PACKS still works at launch. Every entry here is a
#: variable the server still honors and a box the screen no longer shows.
RETIRED = {
    "browser_lane": "KS4WEB_LANE",
    "browser_channel": "KS4WEB_CHANNEL",
    "preauth": "KS4WEB_PREAUTH",
    "all_packs": "KS4WEB_ALL_PACKS",
}


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def find_uvx() -> str | None:
    hit = shutil.which("uvx")
    if hit:
        return hit
    beside = Path(sys.executable).parent / ("uvx.exe" if os.name == "nt" else "uvx")
    return str(beside) if beside.exists() else None


def png_size(data: bytes) -> tuple[int, int]:
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def check_bundle(mcpb_path: Path, dev: bool) -> str | None:
    """Run every per-bundle check. Returns the uvx pin the manifest declares,
    so the caller can run one handshake for the pair."""
    tag = "dev" if dev else "shipped"
    print(f"\n=== {tag} bundle: {mcpb_path} ===")
    if not mcpb_path.exists():
        check(f"{tag}: bundle file exists", False, str(mcpb_path))
        return None
    check(f"{tag}: bundle file exists", True, f"{mcpb_path.stat().st_size} bytes")

    with tempfile.TemporaryDirectory() as td:
        # 1. unzip + contents
        with zipfile.ZipFile(mcpb_path) as zf:
            names = sorted(zf.namelist())
            zf.extractall(td)
        check(f"{tag}: archive contents",
              names == ["icon.png", "manifest.json"], str(names))

        icon = (Path(td) / "icon.png").read_bytes()
        check(f"{tag}: icon is a PNG", icon[:8] == b"\x89PNG\r\n\x1a\n")
        w, h = png_size(icon)
        check(f"{tag}: icon is 512x512", (w, h) == (512, 512), f"{w}x{h}")

        # 2. manifest shape
        mpath = Path(td) / "manifest.json"
        m = json.loads(mpath.read_text(encoding="utf-8"))
        for field in ("manifest_version", "name", "version", "description",
                      "author", "server"):
            check(f"{tag}: manifest has {field}", field in m)
        expected_name = "kitchensink4web-dev" if dev else "kitchensink4web"
        check(f"{tag}: name", m.get("name") == expected_name, str(m.get("name")))
        srv = m.get("server", {})
        check(f"{tag}: server.type is binary",
              srv.get("type") == "binary", str(srv.get("type")))
        cfg = srv.get("mcp_config", {})
        check(f"{tag}: command is uvx",
              cfg.get("command") == "uvx", str(cfg.get("command")))
        ver = m.get("version", "")
        expected_arg = f"kitchensink4web=={ver}"
        check(
            f"{tag}: args pin PyPI version to manifest version",
            cfg.get("args") == [expected_arg],
            str(cfg.get("args")),
        )
        check(f"{tag}: no tools array (Smithery bug #787)", "tools" not in m)
        check(f"{tag}: license is AGPL-3.0-only",
              m.get("license") == "AGPL-3.0-only", str(m.get("license")))
        check(f"{tag}: icon is declared",
              m.get("icon") == "icon.png", str(m.get("icon")))

        # user_config wiring: the form has to reach the server's own env vars,
        # or every checkbox on the install screen is decoration.
        uc = m.get("user_config", {})
        env = cfg.get("env", {})
        expected_keys = len(PACKS) + len(PLAIN)
        check(f"{tag}: install screen offers {expected_keys} settings",
              len(uc) == expected_keys, f"{len(uc)} present")

        for pack in PACKS:
            key = f"pack_{pack}"
            var = f"KS4WEB_PACK_{pack.upper()}"
            check(f"{tag}: {key} is a checkbox",
                  uc.get(key, {}).get("type") == "boolean",
                  str(uc.get(key, {}).get("type")))
            check(f"{tag}: {key} is wired to {var}",
                  env.get(var) == f"${{user_config.{key}}}", str(env.get(var)))
        for key, var in PLAIN.items():
            check(f"{tag}: {key} is a checkbox",
                  uc.get(key, {}).get("type") == "boolean",
                  str(uc.get(key, {}).get("type")))
            check(f"{tag}: {key} is wired to {var}",
                  env.get(var) == f"${{user_config.{key}}}", str(env.get(var)))

        # 3. the shipped defaults, which are the product's whole first claim.
        check(f"{tag}: acting is off by default",
              uc.get("allow_acting", {}).get("default") is False,
              str(uc.get("allow_acting", {}).get("default")))
        on = {"storage"} if dev else set(DEFAULT_ON)
        check(f"{tag}: only {sorted(on)} load by default",
              all(uc[f"pack_{p}"]["default"] is (p in on) for p in PACKS),
              str(sorted(p for p in PACKS if uc[f"pack_{p}"]["default"])))
        check(f"{tag}: routine form submission asks by default",
              uc.get("consent_scope", {}).get("default") is False,
              str(uc.get("consent_scope", {}).get("default")))

        for key, var in RETIRED.items():
            check(f"{tag}: no {key} box", key not in uc)
            check(f"{tag}: nothing wires {var}", var not in env)
        check(f"{tag}: every setting is a checkbox",
              all(e.get("type") == "boolean" for e in uc.values()),
              str(sorted({e.get("type") for e in uc.values()})))

        # 4. mcpb validate, if available
        mcpb_cli = shutil.which("mcpb")
        if mcpb_cli:
            r = subprocess.run(
                [mcpb_cli, "validate", str(mpath)],
                capture_output=True, text=True, timeout=60, shell=False,
            )
            tail = (r.stdout + r.stderr).strip().splitlines()
            check(f"{tag}: mcpb validate", r.returncode == 0,
                  tail[-1] if tail else "")
        else:
            print(f"[SKIP] {tag}: mcpb validate - mcpb CLI not on PATH")

        return expected_arg


def handshake(expected_arg: str) -> None:
    """5. uvx launch + a real MCP initialize handshake."""
    uvx = find_uvx()
    if not uvx:
        print("\n[SKIP] uvx handshake - uvx not found (PATH or venv Scripts)")
        return
    print(f"\nLaunching: {uvx} {expected_arg}  "
          f"(first run may download from PyPI)")
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "0"},
        },
    }
    proc = subprocess.Popen(
        [uvx, expected_arg],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    try:
        out, err = proc.communicate(json.dumps(init) + "\n", timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    resp = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                cand = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cand.get("id") == 1 and "result" in cand:
                resp = cand
                break
    ok = resp is not None
    if ok:
        si = resp["result"].get("serverInfo", {})
        info = f"serverInfo={si.get('name')} {si.get('version')}"
    else:
        info = ("no initialize response; stderr tail: "
                + " | ".join(err.strip().splitlines()[-3:])
                + "  (right after a publish, try "
                  "`uvx --refresh-package kitchensink4web` first)")
    check("uvx stdio initialize handshake", ok, info)


def main() -> int:
    if len(sys.argv) > 1:
        targets = [(Path(a), "dev" in Path(a).name) for a in sys.argv[1:]]
    else:
        targets = [
            (HERE / "kitchensink4web.mcpb", False),
            (HERE / "dev" / "kitchensink4web-dev.mcpb", True),
        ]

    pin = None
    for path, dev in targets:
        got = check_bundle(path, dev)
        if got and not dev:
            pin = got
    if pin:
        handshake(pin)

    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("RESULT: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
