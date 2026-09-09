"""The Phase 1 claim, against a real Firefox.

One browser is launched for the whole module, headless, on a scratch profile,
with the extension loaded as a temporary add-on over the DevTools protocol.
The tests then ask it things. Skipped with the reason named when Firefox is
absent rather than failed, which is what the rest of this suite does about
resources that only exist on a developer machine.

The registry key this writes uses the shipped host name, because that is the
thing under test, and it is removed in teardown.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kitchensink4web.extension import register  # noqa: E402
from kitchensink4web.extension.bridge import Bridge, BridgeError  # noqa: E402
from tests.fixtures.firefox_harness import (  # noqa: E402
    HeadlessFirefox,
    PageServer,
    RDPClient,
    find_firefox,
    free_port,
    probe_webdriver,
)

pytestmark = pytest.mark.browser

SENTINEL = "SENTINEL-live-8b41"
LEAK_CANARY = "hunter2-never-leaves-the-page"

PAGE = f"""<!doctype html>
<title>KS4Web live round trip</title>
<body>
  <h1>live</h1>
  <p id="marker">{SENTINEL}</p>
  <form>
    <input type="text" name="user" value="visible-value">
    <input type="password" name="secret" value="{LEAK_CANARY}">
  </form>
</body>
"""


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    if not find_firefox():
        pytest.skip("no Firefox on this machine")

    workdir = tmp_path_factory.mktemp("ks4web-live")
    endpoint = workdir / "endpoint.json"
    bridge = Bridge(endpoint_path=endpoint)
    pages = PageServer({"/": PAGE})
    browser = None
    rdp = None
    try:
        register.install(
            workdir / "nativehost",
            python_executable=sys.executable,
            src_dir=ROOT / "src",
            endpoint=endpoint,
        )
        port = free_port()
        browser = HeadlessFirefox(workdir / "browser", url=pages.url("/"), debugger_port=port)
        rdp = RDPClient(port)
        rdp.install_temporary_addon(ROOT / "extension")
        if not bridge.wait_for_browser(60.0):
            pytest.fail("the extension never connected to the bridge")
        # THE EXTENSION SHIPS DENYING (Phase 2). Until a session records the
        # consent ladder's answer browser-side, every page command refuses:
        # an unconfigured gate and an empty one are different states and
        # only one of them is "allow nothing". A connected extension that
        # nobody has authorized touches no page, which is why this line has
        # to be here and did not have to be in Phase 1.
        bridge.request("consent.set", {"origins": ["*"]}, timeout=30.0)
        # document_idle can land after the add-on does, so settle on the
        # sentinel rather than on a fixed sleep.
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
        # A BROWSER STILL STARTING HAS `about:blank` ON SCREEN, and the
        # extension refuses privileged schemes rather than trying and
        # failing -- correctly, and this loop is what has to tolerate it.
        # Without the guard the fixture dies on the refusal instead of
        # polling past it, which is a harness defect that looks exactly
        # like a product one: it reproduces on phase 2 code as soon as a
        # third extension module joins the suite (measured at one run in
        # four), and it is why phase 3 saw ten module-setup errors in a
        # full-suite run that no isolated run could reproduce.
            try:
                text = bridge.request("page.read", timeout=30.0).get("text", "")
            except BridgeError:
                text = ""
            if SENTINEL in text:
                break
            time.sleep(0.25)
        yield bridge
    finally:
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
        register.unregister_windows()


def test_the_extension_answers_over_native_messaging(live):
    ping = live.request("bg.ping", timeout=30.0)
    assert ping["pong"] is True
    assert ping["host"] == "ks4web"
    # The declared gecko id survives a temporary install, which is what makes
    # allowed_extensions in the host manifest a real allowlist rather than a
    # field that happens to match today.
    assert ping["extensionId"] == register.EXTENSION_ID


def test_the_content_script_returns_the_page_text(live):
    page = live.request("page.read", timeout=30.0)
    assert SENTINEL in page["text"]
    assert page["title"] == "KS4Web live round trip"
    assert page["chars"] == len(page["text"])
    assert page["frame"] == "top"


def test_the_read_comes_from_the_top_frame_not_a_child(live):
    # all_frames is true, so every frame has a listener. A read that did not
    # pin frameId 0 would sometimes answer from an iframe.
    assert live.request("page.read", timeout=30.0)["frame"] == "top"


def test_navigator_webdriver_is_false_on_the_page_the_extension_read(live):
    assert live.request("page.read", timeout=30.0)["webdriver"] is False


def test_password_values_never_leave_the_page(live):
    import json as _json

    page = live.request("page.read", timeout=30.0)
    assert page["passwordFields"] == [{"name": "secret", "id": None, "value": "[PROTECTED]"}]
    assert LEAK_CANARY not in _json.dumps(page)


def test_an_unknown_method_is_refused_with_its_name(live):
    with pytest.raises(BridgeError) as caught:
        live.request("no.such.method", timeout=30.0)
    assert "UNKNOWN_METHOD" in str(caught.value)
    assert "no.such.method" in str(caught.value)


def test_a_known_method_is_not_refused(live):
    # The other direction of the same pin: a validator that refuses
    # everything would pass the test above on its own.
    assert live.request("bg.ping", timeout=30.0)["pong"] is True


def test_a_payload_far_over_the_folklore_limit_survives_unchunked(live):
    size = 4 * 1024 * 1024
    result = live.request("diag.payload", {"bytes": size, "maxChunk": 0}, timeout=90.0)
    assert result["bytes"] == size


def test_a_payload_returned_in_chunks_reassembles(live):
    size = 3 * 1024 * 1024
    result = live.request("diag.payload", {"bytes": size, "maxChunk": 256 * 1024}, timeout=90.0)
    assert result["bytes"] == size


def test_tabs_can_be_listed_from_the_background_script(live):
    tabs = live.request("bg.tabs", timeout=30.0)["tabs"]
    assert any("127.0.0.1" in (tab.get("url") or "") for tab in tabs)


@pytest.mark.parametrize("mode, expected", [("plain", "false"), ("debugger", "false"), ("remote", "true")])
def test_only_the_remote_agent_flags_the_browser(tmp_path, mode, expected):
    """The measurement the whole architecture rests on.

    ``--remote-debugging-port`` is the flag the CDP approach needed and it
    really does set ``navigator.webdriver``. The DevTools server this harness
    uses to load the add-on does not, which is why a reading taken through
    the extension is a reading of an unflagged browser.
    """
    if not find_firefox():
        pytest.skip("no Firefox on this machine")
    assert probe_webdriver(tmp_path / mode, mode)["webdriver"] == expected
