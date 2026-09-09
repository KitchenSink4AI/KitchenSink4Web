"""The MV3 build, in a real Chromium, doing one round trip.

Spec section 10 asks for the same codebase on both browsers. This module is
what makes that claim checkable: it stages the Chromium flavor, loads it with
``--load-extension`` and no debugging port, and asks the extension to read a
page over native messaging. If the shim is wrong, the service worker throws on
its first line and nothing connects.

Three things are measured rather than assumed, and each is a separate test so
a failure names which one moved:

1. **`navigator.webdriver` under ``--load-extension``.** Phase 1 established
   this question on Firefox and settled it there. It is open on Chromium and
   the whole architecture rests on the answer. Measured through the
   extension's own read, so the probe is not the thing being probed.
2. **The unpacked extension id.** `artifact.unpacked_chromium_id` derives it
   by hashing the directory path, and the native messaging host manifest has
   to name it before the browser has ever run. The profile says what Chromium
   actually assigned.
3. **The service worker lifecycle.** MV2's persistent background page is the
   structural advantage Lane C was built on. MV3 does not have one, and
   whether a native port holds the worker alive is a behavioural difference a
   shim cannot paper over.

Skipped with the reason named when no Chromium-family browser is installed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kitchensink4web.extension import artifact, register  # noqa: E402
from kitchensink4web.extension.bridge import Bridge, BridgeError  # noqa: E402
from tests.fixtures.chromium_harness import (  # noqa: E402
    HeadlessChromium,
    find_chromium,
)
from tests.fixtures.firefox_harness import PageServer  # noqa: E402

pytestmark = pytest.mark.browser

SENTINEL = "SENTINEL-mv3-4c19"
LEAK_CANARY = "hunter2-never-leaves-the-page"

#: The webdriver flag is read by the PAGE and written into the DOM, so the
#: value travels home inside an ordinary `page.read`. Attaching CDP to ask
#: would be attaching the thing whose absence is the measurement.
PAGE = f"""<!doctype html>
<title>KS4Web MV3 round trip</title>
<body>
  <h1>mv3</h1>
  <p id="marker">{SENTINEL}</p>
  <p id="wd">webdriver=<span id="wdval">unread</span></p>
  <form>
    <input type="text" name="user" value="visible-value">
    <input type="password" name="secret" value="{LEAK_CANARY}">
  </form>
  <script>
    document.getElementById("wdval").textContent = String(navigator.webdriver);
  </script>
</body>
"""


@pytest.fixture(scope="module")
def mv3(tmp_path_factory):
    found = find_chromium()
    if not found:
        pytest.skip("no Chromium-family browser on this machine")
    _binary, browser_kind = found

    workdir = tmp_path_factory.mktemp("ks4web-mv3")
    endpoint = workdir / "endpoint.json"
    bridge = Bridge(endpoint_path=endpoint)
    pages = PageServer({"/": PAGE})
    chromium = None
    state = {"browser": browser_kind}
    try:
        # Stage first: the id depends on where this lands.
        ext_dir = workdir / "extension" / "chromium"
        artifact.stage(ext_dir, "chromium")
        derived = artifact.unpacked_chromium_id(ext_dir)
        state["derived_id"] = derived

        register.install(
            workdir / "nativehost",
            extension_id=derived,
            python_executable=sys.executable,
            src_dir=ROOT / "src",
            endpoint=endpoint,
            browser=browser_kind,
        )
        chromium = HeadlessChromium(workdir / "browser", ext_dir,
                                    url=pages.url("/"))
        state["args"] = chromium.args

        connected = bridge.wait_for_browser(60.0)
        state["connected"] = connected
        # The id Chromium assigned, read from the profile. Available whether
        # or not the port ever came up, which is what makes a wrong
        # derivation distinguishable from a broken connection.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not state.get("observed_id"):
            state["observed_id"] = chromium.observed_extension_id()
            if not state.get("observed_id"):
                time.sleep(0.5)

        if connected:
            bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
            deadline = time.monotonic() + 40.0
            while time.monotonic() < deadline:
                try:
                    text = bridge.request("page.read", timeout=30.0).get("text", "")
                except BridgeError:
                    text = ""
                if SENTINEL in text:
                    break
                time.sleep(0.25)
        state["bridge"] = bridge
        yield state
    finally:
        for shutdown in (
            lambda: chromium and chromium.kill(),
            pages.close,
            bridge.close,
        ):
            try:
                shutdown()
            except Exception:  # noqa: BLE001
                pass
        register.unregister_windows(browser=browser_kind)


def test_the_derived_id_is_the_id_chromium_assigned(mv3):
    """The derivation, checked against the browser rather than a spec page.

    If this fails the fix is not the algorithm alone: `--setup-browser` would
    be writing a host manifest naming an extension that does not exist, and
    the user's symptom would be silence.
    """
    observed = mv3.get("observed_id")
    if not observed:
        pytest.skip("chromium did not write an extension id into the profile")
    assert observed == mv3["derived_id"], (
        f"artifact.unpacked_chromium_id derived {mv3['derived_id']} but "
        f"chromium assigned {observed}"
    )


def test_the_mv3_build_connects_over_native_messaging(mv3):
    """The shim works, or the service worker died on its first line."""
    if not mv3["connected"] and not mv3.get("observed_id"):
        # The browser never loaded the directory at all, which is a harness
        # condition rather than a product failure and has to be told apart
        # from one. Chrome 152 does exactly this and says nothing.
        pytest.skip(
            f"{mv3['browser']} ignored --load-extension; nothing was loaded, "
            "so there is no MV3 build here to test"
        )
    if not mv3["connected"]:
        pytest.fail(
            "the MV3 extension never connected to the bridge; the derived id "
            f"was {mv3['derived_id']} and chromium assigned "
            f"{mv3.get('observed_id')}"
        )
    ping = mv3["bridge"].request("bg.ping", timeout=30.0)
    assert ping["pong"] is True
    assert ping["host"] == "ks4web"


def test_the_extension_id_the_worker_reports_matches_the_allowlist(mv3):
    if not mv3["connected"]:
        pytest.skip("no connection; covered by the connection test")
    ping = mv3["bridge"].request("bg.ping", timeout=30.0)
    assert ping["extensionId"] == mv3["derived_id"]


def test_one_page_read_comes_back_through_the_mv3_build(mv3):
    """The round trip the brief asks for: content script, shim, service
    worker, native port, Python."""
    if not mv3["connected"]:
        pytest.skip("no connection; covered by the connection test")
    page = mv3["bridge"].request("page.read", timeout=30.0)
    assert SENTINEL in page["text"]
    assert page["title"] == "KS4Web MV3 round trip"
    assert page["frame"] == "top"


def test_the_password_value_does_not_travel_on_this_build_either(mv3):
    """The refusal is in `content.js`, which is shared, and shared is a claim
    worth checking on the browser that did not prove it."""
    if not mv3["connected"]:
        pytest.skip("no connection; covered by the connection test")
    page = mv3["bridge"].request("page.read", timeout=30.0)
    assert LEAK_CANARY not in page["text"]


def test_navigator_webdriver_under_load_extension(mv3):
    """THE MEASUREMENT. Recorded either way rather than asserted false.

    A true here does not fail the build; it changes what Lane C can honestly
    claim on Chromium, which is a finding for the report and the author, not
    a bug to hide behind a red test.
    """
    if not mv3["connected"]:
        pytest.skip("no connection; covered by the connection test")
    page = mv3["bridge"].request("page.read", timeout=30.0)
    text = page["text"]
    assert "webdriver=" in text, text[:400]
    value = text.split("webdriver=", 1)[1].split()[0].strip()
    assert value in ("true", "false", "undefined"), value
    # Written into the test output so the number is in the record whichever
    # way it went.
    print(f"\nMEASURED navigator.webdriver under --load-extension: {value}")
    assert value != "true", (
        "navigator.webdriver is TRUE under --load-extension on this "
        "Chromium, which is the bot-detection signal the whole extension "
        "architecture exists to avoid. Lane C on Chromium cannot claim what "
        "Lane C on Firefox claims."
    )
