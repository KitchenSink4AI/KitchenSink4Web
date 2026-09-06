"""Pack both .mcpb bundles and smoke-test them.

Two bundles here, not one: `bundle/` is what ships and `bundle/dev/` is the
field-test build. They are packed together so the pair never drifts, which is
the failure a hand-run `mcpb pack` in one directory produces.

Steps, in order:
  1. Regenerate both icons from make_icon.py (deterministic, so a clean tree
     stays clean).
  2. `mcpb pack` each directory. The .mcpbignore files keep the tooling out
     of the archives, so each one is exactly manifest.json + icon.png.
  3. Run bundle/smoke_test.py over both.

Needs the mcpb CLI on PATH (`npm i -g @anthropic-ai/mcpb`). Without it the
pack step cannot run and this exits non-zero rather than pretending.

Usage: python -X utf8 scripts/pack_bundles.py [--no-smoke]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"

#: (source directory, output .mcpb) for each bundle.
TARGETS = (
    (BUNDLE, BUNDLE / "kitchensink4web.mcpb"),
    (BUNDLE / "dev", BUNDLE / "dev" / "kitchensink4web-dev.mcpb"),
)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, text=True, shell=False, **kw)


def main() -> int:
    mcpb = shutil.which("mcpb")
    if not mcpb:
        print("mcpb CLI not on PATH. Install it with "
              "`npm i -g @anthropic-ai/mcpb` and run this again.")
        return 1

    # 1. icons
    r = run([sys.executable, "-X", "utf8", str(BUNDLE / "make_icon.py")])
    if r.returncode:
        return r.returncode

    # 2. pack
    for src, out in TARGETS:
        version = json.loads((src / "manifest.json")
                             .read_text(encoding="utf-8"))["version"]
        print(f"\npacking {src.name or 'bundle'} at version {version}")
        out.unlink(missing_ok=True)
        r = run([mcpb, "pack", str(src), str(out)])
        if r.returncode:
            return r.returncode
        print(f"  -> {out} ({out.stat().st_size} bytes)")

    # 3. smoke
    if "--no-smoke" in sys.argv:
        print("\nsmoke test skipped (--no-smoke)")
        return 0
    print()
    r = run([sys.executable, "-X", "utf8", str(BUNDLE / "smoke_test.py")])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
