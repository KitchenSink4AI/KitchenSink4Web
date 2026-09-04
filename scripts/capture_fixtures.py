"""Record one extraction per fixture page, so the projection can be tested
without a browser.

The projection is a pure function of an extraction plus a budget, and keeping
it that way is what lets the ladder, the quotas, the prices, the completeness
accounting, and every accname rule be asserted in a unit test that runs in
milliseconds and cannot flake on a browser download.

The recordings are committed. Re-run this after any change to `extract.js`,
and read the diff: a change in these files IS the change in what every read
sees, which makes them a review surface rather than a build artifact.

Run:  .venv/Scripts/python.exe -X utf8 scripts/capture_fixtures.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures.pages import PAGES  # noqa: E402

from kitchensink4web import projection  # noqa: E402
from kitchensink4web.engine.session import MANAGER  # noqa: E402

OUT = ROOT / "tests" / "data"


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    try:
        record = session.page(session.focused)
        for name, html in PAGES.items():
            await record.page.goto("about:blank")
            await record.page.set_content(html, wait_until="load")
            data = await projection.extract(record.page)
            # Wall-clock varies per run and would make every recording a diff.
            data["completeness"]["extract_ms"] = None
            data["identity"]["url"] = f"https://fixture.invalid/{name}"
            path = OUT / f"extract_{name}.json"
            path.write_text(json.dumps(data, indent=1, sort_keys=True),
                            encoding="utf-8")
            print(f"{name:>10}: {data['completeness']['total_elements']:>5} nodes, "
                  f"{data['completeness']['affordances_collected']:>4} affordances, "
                  f"{len(data['headings']):>3} headings, shape="
                  f"{data['shape']['kind']} -> {path.name}")
    finally:
        await MANAGER.close(session.session_id)


if __name__ == "__main__":
    asyncio.run(main())
