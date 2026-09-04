"""Lane resolution, channels, lazy install, and the capabilities truth table.

DESIGN 4.2 through 4.5a. Three lanes, and the differences between them are
product surface rather than implementation detail, which is why the truth
table lives in code that `manage_session(action="capabilities")` reads rather
than in a document somebody has to remember to update.

- **Lane A, driven.** A bundled browser on a KS4Web-owned profile. The
  reproducible, parallel-safe, CI-capable lane and what most users get.
- **Lane B, branded.** The user's INSTALLED Chrome, Edge, or Firefox, still on
  a KS4Web-owned profile. `channel="moz-firefox"` is the dogfood lane and S3
  confirmed it holds on playwright-python 1.62.0, launching the installed
  Firefox 154 with no flag gating and no `executable_path` contingency.
- **Lane C, live attach.** Deferred: S5 and S6 are DEFERRED BY SAFETY and the
  Firefox differentiator is UNVERIFIED until they run, so the lane is declared
  here and refuses rather than pretending. Nothing public may claim it.

**The Firefox safety constant.** Playwright's `BidiFirefox.defaultArgs` does
not pass `-no-remote`, unlike its own Juggler path, so a launch can be adopted
by a Firefox the user is already running no matter which profile directory was
named. Every Firefox launch this module builds carries
`engine.FIREFOX_SAFETY_ARGS`, unconditionally, with no flag to disable it.

**Playwright is imported lazily, inside functions.** Lazy install is also lazy
start (DESIGN 4.1), and codex #21984 names eager startup of GUI-capable MCP
tools as the root cause of the worst leak reports. A test asserts that
importing the package does not import playwright.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from ..errors import BadParams, LaneUnsupported
from . import FIREFOX_SAFETY_ARGS

#: Lane A engines: Playwright's own downloads.
BUNDLED = ("chromium", "firefox", "webkit")

#: Lane B channels, keyed to the Playwright browser type that owns them.
#: `moz-firefox` is undocumented (`docs/src/browsers.md` never mentions it)
#: and routes to the BiDi backend rather than the patched Juggler build, which
#: is exactly why it can drive the browser the author actually uses.
CHANNELS: dict[str, str] = {
    "chrome": "chromium", "chrome-beta": "chromium", "chrome-dev": "chromium",
    "chrome-canary": "chromium", "msedge": "chromium",
    "msedge-beta": "chromium", "msedge-dev": "chromium",
    "moz-firefox": "firefox", "moz-firefox-beta": "firefox",
    "moz-firefox-nightly": "firefox",
}

#: Channels routed to Playwright's BiDi Firefox backend, which is where every
#: row of the S4 gap table applies.
FIREFOX_CHANNELS = frozenset(
    c for c, engine in CHANNELS.items() if engine == "firefox")


@dataclass(frozen=True)
class LaneSpec:
    """A resolved launch shape. Everything the session manager needs and
    nothing it has to guess."""

    lane: str                     # "A" | "B" | "C"
    engine: str                   # chromium | firefox | webkit
    channel: str | None = None    # Lane B only
    headless: bool = True
    args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_firefox(self) -> bool:
        return self.engine == "firefox"

    @property
    def is_bidi_firefox(self) -> bool:
        """Firefox over Playwright's BiDi backend, which is the branded lane.

        The bundled Firefox is the Juggler build and does NOT carry the S4
        gaps; conflating the two would attach a capability table to the wrong
        browser."""
        return self.channel in FIREFOX_CHANNELS

    @property
    def label(self) -> str:
        what = self.channel or self.engine
        return f"{self.lane}({what}{'' if self.headless else ', headed'})"


# ------------------------------------------------------- the truth table


#: What each lane supports, degrades, or cannot do. Seeded from S4's measured
#: table (DESIGN 4.5a), which replaced the research's stale hole list after
#: twenty probes ran on both `moz-firefox` and Chromium with Chromium as the
#: control. Every probe passed on Chromium, so each Firefox row below is a
#: genuine lane difference rather than a broken probe.
#:
#: Three kinds of row and the difference matters: `ok`, `unsupported` (refuses
#: loudly, never a silent pass-through), and `cost` (works, and is slow). An
#: operation that works and is slow is a different fact from one that does not
#: work, and collapsing the two is how a capability table stops being useful.
CAPABILITIES: dict[str, dict] = {
    "response_body_read": {
        "chromium": "ok", "firefox_bidi": "ok",
        "note": "S4 REFUTED the documented gap: 708 bytes for a document and "
                "a full JSON body on an XHR POST, on both lanes.",
    },
    "request_body_read": {
        "chromium": "ok", "firefox_bidi": "unsupported",
        "message": (
            "request body capture is unavailable on Firefox/BiDi. Playwright "
            "returns null rather than raising, so KS4Web refuses explicitly "
            "instead of returning an empty body. Chromium supports it; "
            "relaunch on Lane A or Lane B Chrome to read request bodies."
        ),
    },
    "request_body_write": {
        "chromium": "ok", "firefox_bidi": "ok",
        "note": "route.continue_(post_data=...) was accepted and the fixture "
                "server received the tampered body verbatim. The honest "
                "capability row is 'write yes, read no'.",
    },
    "history_navigation": {
        "chromium": "ok", "firefox_bidi": "unsupported",
        "message": (
            "history navigation (back and forward) is unavailable on "
            "Firefox/BiDi. The page does navigate, but the driver never "
            "reports it and page.url goes stale afterward, so KS4Web refuses "
            "rather than calling it. Navigate to the previous URL directly "
            "instead; KS4Web tracks page history for exactly this. Chromium "
            "supports back and forward normally."
        ),
    },
    "downloads": {
        "chromium": "ok", "firefox_bidi": "ok",
        "note": "S4 REFUTED: the download event fired and the file landed on "
                "disk at 460 bytes.",
    },
    "http_auth": {
        "chromium": "ok", "firefox_bidi": "ok",
        "note": "S4 REFUTED: a 401 challenge was answered and the protected "
                "resource returned.",
    },
    "header_override_across_redirect": {"chromium": "ok", "firefox_bidi": "ok"},
    "click_in_css_transform": {"chromium": "ok", "firefox_bidi": "ok"},
    "locale_timezone_emulation": {"chromium": "ok", "firefox_bidi": "ok"},
    "pdf_export": {
        "chromium": "ok", "firefox_bidi": "cost",
        "message": (
            "PDF export works on Firefox/BiDi and is roughly 45x slower: S4 "
            "measured 232 KB in 8.7 s against Chromium's 240 KB in 0.2 s. "
            "This is a cost, not a gap, and it is named in the result rather "
            "than refused."
        ),
    },
    "about_pages": {
        "chromium": "ok", "firefox_bidi": "unsupported",
        "message": (
            "about: pages cannot be navigated on Firefox/BiDi. The driver "
            "refuses with 'Navigation to about:support is not allowed in this "
            "context', so version banners, profile provenance, and "
            "about:config reads are unavailable on this lane. KS4Web reads "
            "provenance from the process table and the user-agent string "
            "instead."
        ),
    },
}

#: Never trusted after a history traversal on Firefox/BiDi (DESIGN 4.5a rule
#: 2). No anchor logic, no wait_for_url, and no load-state wait may derive
#: from `page.url` there. The refusal above means KS4Web does not traverse
#: history on that lane at all, and this constant is why: if the traversal
#: were ever allowed, the URL it reports would be a lie rather than an absence.
URL_UNTRUSTED_AFTER_HISTORY = ("firefox_bidi",)


def capability_key(spec: LaneSpec) -> str:
    """Which column of the truth table a lane reads."""
    return "firefox_bidi" if spec.is_bidi_firefox else "chromium"


def capability(spec: LaneSpec, name: str) -> str:
    row = CAPABILITIES.get(name)
    if row is None:
        raise BadParams(
            f"unknown capability {name!r}; the table carries "
            f"{sorted(CAPABILITIES)}")
    return row.get(capability_key(spec), "ok")


def require(spec: LaneSpec, name: str) -> None:
    """Refuse LOUDLY when the current lane cannot do a thing.

    Both real S4 gaps fail silently or misleadingly in the driver, which is
    the failure class this whole product argues against, so both become
    refusals here rather than pass-throughs. A cost row never refuses."""
    state = capability(spec, name)
    if state != "unsupported":
        return
    row = CAPABILITIES[name]
    raise LaneUnsupported(
        f"[lane {spec.label}] {row.get('message', name + ' is unavailable')}")


def capabilities_report(spec: LaneSpec) -> dict:
    """The `manage_session(action="capabilities")` payload: what this lane
    supports, what it degrades, and what it cannot do at all, with the lane
    that would support each gap named."""
    key = capability_key(spec)
    supported, degraded, unsupported = [], [], []
    for name, row in CAPABILITIES.items():
        state = row.get(key, "ok")
        entry = {"capability": name}
        if row.get("note"):
            entry["note"] = row["note"]
        if state == "ok":
            supported.append(name)
        elif state == "cost":
            degraded.append({**entry, "detail": row.get("message", "")})
        else:
            unsupported.append({**entry, "detail": row.get("message", ""),
                                "supported_on": "Lane A or Lane B Chromium"})
    return {
        "lane": spec.lane,
        "label": spec.label,
        "engine": spec.engine,
        "channel": spec.channel,
        "headless": spec.headless,
        "supported": sorted(supported),
        "degraded_with_a_cost": degraded,
        "unsupported": unsupported,
        "measured": "S4, 2026-09-05, twenty probes per lane with Chromium as "
                    "the control",
        "url_trust": (
            "page.url is not trusted after a history traversal on this lane"
            if key in URL_UNTRUSTED_AFTER_HISTORY
            else "page.url is trusted"),
    }


# ---------------------------------------------------------------- resolving


def resolve(lane: str | None = None, engine: str | None = None,
            channel: str | None = None, headless: bool | None = None
            ) -> LaneSpec:
    """Resolve a launch shape from what the caller asked for.

    A typo is an error rather than a shrug. chrome-devtools-mcp #2530 silently
    ignores a mistyped `--browserUrl` and DOWNGRADES attach mode to launch
    mode; playwright-mcp #1388 silently applied zero cookies from a bad
    `--storage-state` and was closed "works for me." Never degrade silently is
    the whole subsystem in four words."""
    lane = (lane or os.environ.get("KS4WEB_LANE") or "A").strip().upper()
    channel = (channel or os.environ.get("KS4WEB_CHANNEL") or "").strip() or None
    engine = (engine or os.environ.get("KS4WEB_ENGINE") or "").strip() or None
    if headless is None:
        headless = os.environ.get("KS4WEB_HEADLESS", "1").strip().lower() \
            not in ("0", "false", "off", "no")

    if lane == "C":
        raise LaneUnsupported(
            "Lane C (attaching to a browser you are already running) is not "
            "built. Its two spikes are deferred by a standing safety rule "
            "rather than by a finding: KS4Web does not attach to the author's "
            "live browser, so the Firefox live-attach path is UNVERIFIED and "
            "the lane refuses rather than claiming it. Use lane='A' (a "
            "bundled browser) or lane='B' (your installed Chrome, Edge, or "
            "Firefox), both on a KS4Web-owned profile."
        )
    if lane not in ("A", "B"):
        raise BadParams(
            f"unknown lane {lane!r}: the lanes are 'A' (bundled browser), "
            f"'B' (your installed browser, still on a KS4Web-owned profile), "
            f"and 'C' (live attach, not built). Set KS4WEB_LANE or pass "
            f"lane= explicitly.")

    if lane == "B":
        channel = channel or "chrome"
        if channel not in CHANNELS:
            raise BadParams(
                f"unknown channel {channel!r} for lane B: the channels are "
                f"{sorted(CHANNELS)}. Lane B drives your INSTALLED browser, "
                f"so the channel names which one.")
        engine = CHANNELS[channel]
    else:
        engine = engine or "chromium"
        channel = None
        if engine not in BUNDLED:
            raise BadParams(
                f"unknown engine {engine!r} for lane A: the bundled engines "
                f"are {list(BUNDLED)}.")

    args: tuple[str, ...] = ()
    if engine == "firefox":
        # DESIGN 4.3 and 4.6, and it is a constant rather than a default.
        args = FIREFOX_SAFETY_ARGS
    return LaneSpec(lane=lane, engine=engine, channel=channel,
                    headless=headless, args=args)


# ------------------------------------------------------ lazy browser install


def executable_path(spec: LaneSpec, pw: object | None = None) -> str | None:
    """Where the browser this lane wants actually lives, or None.

    Lane B resolves through the installed-browser lookup rather than the
    Playwright download, which is the whole point of the lane. Lane A asks
    the RUNNING driver, because the sync API refuses to run inside an asyncio
    loop (the guard is in `sync_api/_context_manager.py`) and every caller
    here is inside one."""
    if spec.channel in FIREFOX_CHANNELS:
        for candidate in (
                os.environ.get("KS4WEB_FIREFOX_PATH"),
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
                shutil.which("firefox")):
            if candidate and os.path.exists(candidate):
                return candidate
        return None
    if spec.channel:
        return shutil.which(spec.channel) or _known_chromium_channel(spec)
    if pw is None:
        return None
    try:
        return getattr(pw, spec.engine).executable_path
    except Exception:
        return None


def _known_chromium_channel(spec: LaneSpec) -> str | None:
    roots = [os.environ.get("PROGRAMFILES", ""),
             os.environ.get("PROGRAMFILES(X86)", ""),
             os.environ.get("LOCALAPPDATA", "")]
    rel = {"chrome": r"Google\Chrome\Application\chrome.exe",
           "msedge": r"Microsoft\Edge\Application\msedge.exe"}.get(
               spec.channel or "")
    if not rel:
        return None
    for root in roots:
        if root and os.path.exists(os.path.join(root, rel)):
            return os.path.join(root, rel)
    return None


def is_installed(spec: LaneSpec, pw: object | None = None) -> bool:
    path = executable_path(spec, pw)
    return bool(path) and os.path.exists(path)


def ensure_installed(spec: LaneSpec, pw: object | None = None,
                     auto: bool | None = None) -> dict:
    """Lazy install: fetch a bundled engine on first use, once.

    KS4Web ships with no browsers (DESIGN 4.1: the wheel is 38.2 MB because it
    bundles a Node runtime, and the browsers are another 180 to 281 MB each).
    Lane B installs nothing ever, by definition, so a missing installed
    browser there is a refusal naming the lane rather than a download."""
    if is_installed(spec, pw):
        return {"installed": True, "action": "already present"}
    if spec.lane == "B":
        raise BadParams(
            f"lane B drives your installed browser and {spec.channel!r} is "
            f"not installed on this machine. Install it, or use lane='A' for "
            f"a KS4Web-managed browser download.")
    if auto is None:
        auto = os.environ.get("KS4WEB_AUTO_INSTALL", "1").strip().lower() \
            not in ("0", "false", "off", "no")
    if not auto:
        raise BadParams(
            f"the {spec.engine} browser is not installed and automatic "
            f"install is off (KS4WEB_AUTO_INSTALL=0). Run "
            f"`python -m playwright install {spec.engine}` and retry.")
    res = subprocess.run(
        [sys.executable, "-m", "playwright", "install", spec.engine],
        capture_output=True, text=True, timeout=900)
    if res.returncode != 0 or not is_installed(spec, pw):
        raise BadParams(
            f"installing the {spec.engine} browser failed: "
            f"{(res.stderr or res.stdout or '')[-400:]}. Run "
            f"`python -m playwright install {spec.engine}` by hand to see the "
            f"full output.")
    return {"installed": True, "action": "downloaded on first use"}


def launch_kwargs(spec: LaneSpec, profile_dir: str) -> dict:
    """The `launch_persistent_context` keyword arguments for this lane.

    Persistent context on every lane, not just Lane B: it is the shape that
    owns a profile DIRECTORY, and an owned profile directory is half of the
    profile-safety rule. The other half is `-no-remote`, which is in `args`
    for every Firefox and cannot be turned off."""
    kwargs: dict = {
        "user_data_dir": profile_dir,
        "headless": spec.headless,
        "viewport": {"width": 1280, "height": 900},
    }
    if spec.channel:
        kwargs["channel"] = spec.channel
    if spec.args:
        kwargs["args"] = list(spec.args)
    return kwargs
