"""Phase 1 validation: Python -> native messaging -> content script -> Python.

Run it and it answers, in order, the four questions Phase 1 exists to settle:

1. Does native messaging work on Windows, registered the way a shipped
   install would register it?
2. Does the content script inject, and does the pre-injected listener answer
   a command routed through the background script?
3. Does the payload come back intact, and where is the real ceiling on the
   extension-to-server direction?
4. Is ``navigator.webdriver`` still false on the page the extension read?

Everything it starts is hidden and everything it starts, it kills. The
registry key it writes is removed on the way out, so a run leaves the machine
as it found it.

    python scripts/ext_phase1_validate.py [--keep] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from kitchensink4web.extension import register  # noqa: E402
from kitchensink4web.extension.bridge import Bridge  # noqa: E402
from tests.fixtures.firefox_harness import (  # noqa: E402
    HeadlessFirefox,
    PageServer,
    RDPClient,
    find_firefox,
    free_port,
    probe_webdriver,
)

TEST_HOST_NAME = "ks4web"

FIXTURE_PAGE = """<!doctype html>
<title>KS4Web Phase 1 fixture</title>
<body>
  <h1>Phase 1 round trip</h1>
  <p id="marker">SENTINEL-9f3a2c the content script must return this string</p>
  <form>
    <input type="text" name="user" value="visible-value">
    <input type="password" name="secret" value="hunter2-never-leaves-the-page">
  </form>
  <p>Trailing paragraph so innerText has more than one node.</p>
</body>
"""

SENTINEL = "SENTINEL-9f3a2c"
LEAK_CANARY = "hunter2-never-leaves-the-page"


def measure_ping(bridge: Bridge, rounds: int = 25) -> dict:
    """The pipe on its own, with no page in it.

    bg.ping is answered in the background script, so this is Python -> relay
    -> native messaging -> background -> back. Subtracting it from a page.read
    leaves the cost of the tab hop and the DOM work, which is the part any
    Phase 3 optimisation has to move.
    """
    for _ in range(3):
        bridge.request("bg.ping")
    samples = []
    for _ in range(rounds):
        start = time.perf_counter()
        bridge.request("bg.ping")
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    return {
        "rounds": rounds,
        "min_ms": round(samples[0], 2),
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 2),
        "max_ms": round(samples[-1], 2),
    }


def heavy_page(sections: int = 400) -> str:
    """A page the size of a real article, so the latency number means something.

    The fixture above is 138 characters of innerText. Timing a read of that
    measures the pipe and nothing else, which would make the round-trip figure
    look better than any page a user will actually point this at.
    """
    blocks = []
    for index in range(sections):
        blocks.append(
            f"<section id='s{index}'><h2>Section {index}</h2>"
            f"<p>{'Paragraph body text for the heavy fixture. ' * 12}</p>"
            f"<ul><li>item {index}a</li><li>item {index}b</li><li>item {index}c</li></ul>"
            f"<a href='#s{index}'>jump to {index}</a></section>"
        )
    return (
        "<!doctype html><title>KS4Web Phase 1 heavy fixture</title><body>"
        f"<h1>Heavy fixture</h1><p id='marker'>{SENTINEL}</p>"
        f"<form><input type='text' name='user' value='visible-value'>"
        f"<input type='password' name='secret' value='{LEAK_CANARY}'></form>"
        + "".join(blocks)
        + "</body>"
    )


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def measure_latency(bridge: Bridge, tab_id: int | None = None, rounds: int = 25) -> dict:
    """Round-trip wall time for page.read, warmed up first."""
    params = {"tabId": tab_id} if tab_id is not None else {}
    for _ in range(3):
        bridge.request("page.read", params)
    samples = []
    chars = 0
    for _ in range(rounds):
        start = time.perf_counter()
        result = bridge.request("page.read", params)
        samples.append((time.perf_counter() - start) * 1000.0)
        chars = result.get("chars", 0)
    samples.sort()
    return {
        "page_chars": chars,
        "rounds": rounds,
        "min_ms": round(samples[0], 2),
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 2),
        "max_ms": round(samples[-1], 2),
    }


def find_payload_ceiling(bridge: Bridge) -> dict:
    """Walk a size ladder to find where the extension-to-server hop breaks.

    The documented limit in this direction is 4 GB and the one field report
    of Windows trouble was closed without a reproduction, so the number this
    returns is the first thing anyone has actually measured here.
    """
    ladder = [
        64 * 1024,
        256 * 1024,
        768 * 1024,
        1024 * 1024,
        4 * 1024 * 1024,
        16 * 1024 * 1024,
        64 * 1024 * 1024,
    ]
    results = []
    largest_ok = 0
    for size in ladder:
        entry: dict = {"requested_bytes": size}
        start = time.perf_counter()
        try:
            # maxChunk 0 turns chunking OFF, so this measures the raw hop
            # rather than the workaround built on top of it.
            result = bridge.request(
                "diag.payload", {"bytes": size, "maxChunk": 0}, timeout=60.0
            )
            entry["elapsed_ms"] = round((time.perf_counter() - start) * 1000.0, 1)
            entry["returned_bytes"] = result.get("bytes")
            entry["ok"] = result.get("bytes") == size
            if entry["ok"]:
                largest_ok = size
        except Exception as exc:  # noqa: BLE001 - the failure IS the measurement
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
            results.append(entry)
            break
        results.append(entry)
    chunked = {}
    if largest_ok < ladder[-1]:
        # If the raw hop has a ceiling, prove the chunked path clears it.
        target = ladder[min(len(ladder) - 1, ladder.index(largest_ok) + 1)] if largest_ok in ladder else ladder[-1]
        try:
            result = bridge.request("diag.payload", {"bytes": target}, timeout=90.0)
            chunked = {"requested_bytes": target, "returned_bytes": result.get("bytes"),
                       "ok": result.get("bytes") == target}
        except Exception as exc:  # noqa: BLE001
            chunked = {"requested_bytes": target, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ladder": results, "largest_unchunked_ok": largest_ok, "chunked_retry": chunked}


def run(workdir: Path, keep: bool) -> dict:
    findings: dict = {"workdir": str(workdir), "started": time.strftime("%Y-%m-%d %H:%M:%S")}

    binary = find_firefox()
    if not binary:
        raise SystemExit("no Firefox found")
    findings["firefox"] = binary

    say("[1/6] probing navigator.webdriver across launch modes")
    findings["webdriver_probe"] = {
        mode: probe_webdriver(workdir / f"probe-{mode}", mode)["webdriver"]
        for mode in ("plain", "debugger", "remote")
    }
    say(f"      {findings['webdriver_probe']}")

    endpoint = workdir / "endpoint.json"
    host_dir = workdir / "nativehost"
    bridge = Bridge(endpoint_path=endpoint)
    browser = None
    rdp = None
    registration = None
    pages = PageServer({"/": heavy_page(), "/light": FIXTURE_PAGE})
    try:
        say("[2/6] registering the native messaging host")
        registration = register.install(
            host_dir,
            host_name=TEST_HOST_NAME,
            python_executable=sys.executable,
            src_dir=ROOT / "src",
            endpoint=endpoint,
        )
        findings["registration"] = registration
        findings["registry_readback"] = register.read_registration(TEST_HOST_NAME)
        say(f"      {findings['registry_readback']}")

        say("[3/6] launching headless Firefox and installing the extension")
        port = free_port()
        browser = HeadlessFirefox(
            workdir / "browser", url=pages.url("/"), debugger_port=port
        )
        rdp = RDPClient(port)
        installed = rdp.install_temporary_addon(ROOT / "extension")
        findings["addon"] = installed.get("addon", installed)
        say(f"      addon id {findings['addon'].get('id')}")

        say("[4/6] waiting for the relay to dial the bridge")
        connect_start = time.perf_counter()
        if not bridge.wait_for_browser(45.0):
            raise RuntimeError("the extension never connected to the bridge")
        findings["connect_ms"] = round((time.perf_counter() - connect_start) * 1000.0, 1)
        say(f"      connected in {findings['connect_ms']} ms")

        ping = bridge.request("bg.ping", timeout=30.0)
        findings["ping"] = ping
        say(f"      bg.ping from extension {ping.get('extensionId')}")

        say("[5/6] reading the page through the content script")
        # The first read can wait on document_idle, so it gets its own budget
        # and is reported separately from the warm numbers.
        first_start = time.perf_counter()
        page = None
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            page = bridge.request("page.read", timeout=30.0)
            if SENTINEL in page.get("text", ""):
                break
            time.sleep(0.25)
        findings["first_read_ms"] = round((time.perf_counter() - first_start) * 1000.0, 1)
        findings["page"] = {
            "url": page.get("url"),
            "title": page.get("title"),
            "chars": page.get("chars"),
            "webdriver": page.get("webdriver"),
            "frame": page.get("frame"),
            "readMs": page.get("readMs"),
            "passwordFields": page.get("passwordFields"),
            "sentinel_present": SENTINEL in page.get("text", ""),
            "password_value_leaked": LEAK_CANARY in json.dumps(page),
        }
        say(f"      {findings['page']['chars']} chars, webdriver={findings['page']['webdriver']}, "
            f"sentinel={findings['page']['sentinel_present']}, "
            f"leak={findings['page']['password_value_leaked']}")

        findings["latency_ping"] = measure_ping(bridge)
        say(f"      pipe only {findings['latency_ping']}")
        findings["latency"] = measure_latency(bridge)
        say(f"      warm page read {findings['latency']}")

        say("[6/6] finding the payload ceiling")
        findings["payload"] = find_payload_ceiling(bridge)
        say(f"      largest unchunked ok: {findings['payload']['largest_unchunked_ok']} bytes")

        # Refusals, pinned in both directions here as well as in the unit
        # tests: the extension must answer a bad method with a refusal, not a
        # silence and not a crash.
        refusals = {}
        try:
            bridge.request("no.such.method", timeout=15.0)
            refusals["unknown_method"] = "ACCEPTED (wrong)"
        except Exception as exc:  # noqa: BLE001
            refusals["unknown_method"] = f"refused: {exc}"
        findings["refusals"] = refusals
        say(f"      {refusals}")

        findings["ok"] = bool(
            findings["page"]["sentinel_present"]
            and findings["page"]["webdriver"] is False
            and not findings["page"]["password_value_leaked"]
        )
    finally:
        # Torn down in the order they were built on top of each other, and
        # every one of them by our own handle: nothing here reaches for a
        # process this run did not start.
        for shutdown in (
            lambda: rdp and rdp.close(),
            lambda: browser and browser.kill(),
            pages.close,
            bridge.close,
        ):
            try:
                shutdown()
            except Exception:  # noqa: BLE001
                pass
        if registration is not None and not keep:
            register.unregister_windows(TEST_HOST_NAME)
        findings["registry_after_cleanup"] = register.read_registration(TEST_HOST_NAME)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the registry key and workdir in place")
    parser.add_argument("--json", type=Path, help="write the findings to this path")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="ks4web-phase1-"))
    try:
        findings = run(workdir, args.keep)
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)
    text = json.dumps(findings, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if findings.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
