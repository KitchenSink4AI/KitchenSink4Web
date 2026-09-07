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
from pathlib import Path

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

#: Spellings a caller reasonably guesses, mapped to the channel Playwright
#: actually takes. Field log 2 item U18: `moz-firefox` is genuinely
#: undocumented upstream, `docs/src/browsers.md` never mentions it, and the
#: tester's first guess was `firefox`, which cost a round trip to a refusal
#: that listed the real names. The refusal was right and the round trip was
#: avoidable. An alias is NOT a silent degrade: it lands on the same lane the
#: caller obviously meant, and every wrong name still refuses loudly.
CHANNEL_ALIASES: dict[str, str] = {
    "firefox": "moz-firefox",
    "firefox-beta": "moz-firefox-beta",
    "firefox-nightly": "moz-firefox-nightly",
    "mozilla-firefox": "moz-firefox",
    "edge": "msedge",
    "edge-beta": "msedge-beta",
    "edge-dev": "msedge-dev",
    "google-chrome": "chrome",
}


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


def lane_key(spec: LaneSpec) -> str:
    """The key the lane database records this lane under.

    The same move `capability_key` makes, at a finer grain: a verdict does not
    generalize by channel name, it generalizes by what a site can OBSERVE.
    `engine:backend:headless` is that, and it is what makes a record portable
    between a user driving installed Chrome and one driving bundled Chromium,
    since the thing that got them turned away (the `HeadlessChrome` user agent,
    the driver's TLS signature) is the same on both.

    Headed and headless are separate keys because headless is the block vector
    on Chromium. Collapsing them would teach the database the wrong lesson
    about a headed lane that works fine."""
    if spec.engine == "firefox":
        backend = "bidi" if spec.is_bidi_firefox else "juggler"
    elif spec.engine == "webkit":
        backend = "wk"
    else:
        backend = "cdp"
    return (f"{spec.engine}:{backend}:"
            f"{'headless' if spec.headless else 'headed'}")


#: The `lane=` argument that opens each lane key, for the refusal that names
#: a lane worth trying. A key is what a SITE sees; this is what a CALLER
#: types, and the two are deliberately different vocabularies.
_LANE_ARGUMENT: dict[str, str] = {
    "chromium:cdp": "A",
    "firefox:juggler": "A:firefox",
    "firefox:bidi": "B:moz-firefox",
    "webkit:wk": "A:webkit",
}


def lane_argument(key: str) -> str | None:
    """The `manage_session(action='open', lane=...)` value for a lane key."""
    try:
        engine, backend, headless = key.split(":")
    except ValueError:
        return None
    base = _LANE_ARGUMENT.get(f"{engine}:{backend}")
    if base is None:
        return None
    return base if headless == "headless" else base + "+headed"


def _bundled_present(engine: str) -> bool:
    """Whether a Playwright download for this engine is already on disk.

    Asked WITHOUT a running driver and without launching anything, because the
    only caller is the session-birth lane choice and a choice that triggers a
    two-hundred-megabyte download nobody asked for is not a better default."""
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root in ("0", ""):
        root = None
    base = Path(root) if root else (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
        if sys.platform.startswith("win")
        else Path.home() / ".cache" / "ms-playwright")
    try:
        return any(base.glob(f"{engine}-*"))
    except OSError:
        return False


def lane_available(key: str) -> bool:
    """Whether this machine can open the lane a database record names.

    Lane B needs the browser installed (a stat, never a launch); lane A needs
    the Playwright download already fetched."""
    try:
        engine, backend, _headless = key.split(":")
    except ValueError:
        return False
    if backend == "bidi":
        return any(b["channel"] == "moz-firefox" for b in detect_installed())
    if backend == "cdp":
        return _bundled_present("chromium") or any(
            b["channel"] in ("chrome", "msedge") for b in detect_installed())
    return _bundled_present(engine)


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
        channel = CHANNEL_ALIASES.get(channel.lower(), channel)
        if channel not in CHANNELS:
            raise BadParams(
                f"unknown channel {channel!r} for lane B: the channels are "
                f"{sorted(CHANNELS)}, and these spellings are accepted as "
                f"well: {sorted(CHANNEL_ALIASES)}. Lane B drives your "
                f"INSTALLED browser, so the channel names which one.")
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


# -------------------------------------------- what is installed, and steering

#: One row per browser worth detecting: the lane B channel that drives it, the
#: display name, and where to look. Windows first because that is where the
#: author works; the macOS and Linux entries are the same lookup with
#: different paths rather than a second mechanism.
_DETECTABLE: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("moz-firefox", "Firefox", "firefox.exe", (
        r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe",
        r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe",
        "/Applications/Firefox.app/Contents/MacOS/firefox",
        "/usr/bin/firefox", "/snap/bin/firefox",
    )),
    ("chrome", "Chrome", "chrome.exe", (
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
    )),
    ("msedge", "Edge", "msedge.exe", (
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/microsoft-edge",
    )),
)

#: Detection result for this process. Browsers are not installed and
#: uninstalled inside one session, and a status call that shells out or reads
#: the registry every time would be a cost paid on every status.
_DETECTED: list[dict] | None = None


def _app_paths_lookup(exe: str) -> str | None:
    """Windows App Paths, which is where an installer registers its binary.
    Consulted after the known paths, so a standard install never pays for a
    registry read at all."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
    except ImportError:
        return None
    key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value = winreg.QueryValueEx(handle, "")[0]
        except OSError:
            continue
        value = os.path.expandvars(str(value).strip('"'))
        if os.path.exists(value):
            return value
    return None


def detect_installed(refresh: bool = False) -> list[dict]:
    """The browsers installed on this machine that lane B could drive.

    Known paths first, then the Windows App Paths registry, then PATH. Every
    step is a stat or a registry read; nothing is launched and nothing is
    asked for its version, because a detection that starts browsers to find
    out what is there is worse than no detection.
    """
    global _DETECTED
    if _DETECTED is not None and not refresh:
        return _DETECTED
    found = []
    for channel, name, exe, paths in _DETECTABLE:
        path = None
        for candidate in paths:
            expanded = os.path.expandvars(candidate)
            if "%" not in expanded and os.path.exists(expanded):
                path = expanded
                break
        path = path or _app_paths_lookup(exe) or shutil.which(
            exe[:-4] if exe.endswith(".exe") else exe)
        if path and os.path.exists(path):
            found.append({"name": name, "channel": channel, "path": path,
                          "lane": f"B({channel})"})
    _DETECTED = found
    return found


def recommended_lane(refresh: bool = False) -> dict:
    """Which lane to open, given what is installed. STEERING ONLY.

    Nothing here switches a lane, and `manage_session(action='open')` reads
    none of it: a tool that quietly relaunched on a different browser than
    the caller asked for would be the silent downgrade this subsystem exists
    to prevent. The caller decides; this says what the machine offers.

    The doctrine, in two lines. A bundled Chromium is the default because it
    is reproducible, parallel-safe, and installs itself. An INSTALLED stock
    Firefox is the research default, because the field campaign measured the
    difference: Reddit served Chromium headless a 17-node blank page and
    served both Firefox lanes the real one, and the block is the stock
    HeadlessChrome user agent rather than anything KS4Web does.
    """
    installed = detect_installed(refresh=refresh)
    firefox = next((b for b in installed if b["channel"] == "moz-firefox"),
                   None)
    research = {
        "lane": firefox["lane"] if firefox else "A(firefox)",
        "why": ("your installed Firefox, on a KS4Web-owned profile: sites "
                "that block automated Chromium served the Firefox lanes the "
                "real page in the field campaign"
                if firefox else
                "the bundled Firefox, since no installed Firefox was found: "
                "sites that block automated Chromium served the Firefox "
                "lanes the real page in the field campaign. An installed "
                "Firefox would be the better one"),
    }
    return {
        "installed": [{"name": b["name"], "lane": b["lane"], "path": b["path"]}
                      for b in installed],
        "default": {
            "lane": "A(chromium)",
            "why": ("the bundled Chromium: reproducible, parallel-safe, and "
                    "it installs itself on first use"),
        },
        "research": research,
        "note": ("steering only. Nothing switches lanes on its own; pass "
                 "lane= and channel= to manage_session(action='open') when "
                 "you want one of these."),
    }


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


def launch_kwargs(spec: LaneSpec, profile_dir: str,
                  emulation: dict | None = None) -> dict:
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
    if emulation:
        kwargs.update(emulation)
    identity = agent_identity()
    if identity:
        kwargs["extra_http_headers"] = dict(identity["headers"])
    return kwargs

# ------------------------------------------------------ agent identification

#: The header KS4Web sends when the caller has switched identification ON.
#: A dedicated field rather than the User-Agent, and the reason is a fidelity
#: one: Playwright takes a user agent at CONTEXT CONSTRUCTION, so appending a
#: product token to the real one would mean either guessing the base string
#: (which is a lie waiting to happen) or setting it as a request header after
#: launch, which leaves `navigator.userAgent` saying one thing and the wire
#: saying another. An inconsistent fingerprint is the class of thing the
#: no-spoofing rule exists to prevent, so identification rides its own field
#: and the browser keeps saying exactly what it is.
AGENT_HEADER = "X-KS4Web-Agent"

ENV_AGENT_ID = "KS4WEB_AGENT_ID"


def _agent_toggle() -> bool:
    """The install-screen boolean, with the family's loud-typo rule.

    Same shape as the pack toggles (`packs._toggle_env`): empty is off, the
    literal 'true' is on, 'false' is off, anything else refuses. It is a
    CHECKBOX and not a free-text field on purpose: a caller who could type the
    header value could type a claim about who they are, and this feature only
    exists because it never does that."""
    raw = os.environ.get(ENV_AGENT_ID)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in ("", "false", "0", "off", "no"):
        return False
    if value in ("true", "1", "on", "yes"):
        return True
    raise BadParams(
        f"{ENV_AGENT_ID}={raw!r} is not an identification toggle value: use "
        f"'true' or 'false' (empty means off). It is a switch rather than a "
        f"field, because the identity KS4Web declares is not something a "
        f"caller gets to compose.")


def _product_version() -> str:
    try:
        from importlib.metadata import version
        return version("kitchensink4web")
    except Exception:
        return "unknown"


def agent_identity() -> dict | None:
    """The identification headers this session sends, or None when off.

    DEFAULT OFF, and the default is not timidity: a context-level header goes
    out on every request the session makes, to every host it touches, so
    turning it on is a decision to announce this machine's tooling broadly.
    Turned on, it states one true thing (the product and its version) and
    claims nothing else: no operator, no purpose, no permission, and no
    assertion that any site has granted access. KS4Web never lies about what
    it is in either setting, and nothing here is a bot-verification
    credential."""
    if not _agent_toggle():
        return None
    version = _product_version()
    return {
        "headers": {AGENT_HEADER: f"KitchenSink4Web/{version}"},
        "on": True,
        "version": version,
        "applies_to": "every request this session makes, on every host",
        "user_agent": "unchanged; the browser reports its own",
        "verification": ("this is a self-declaration and not a signed "
                         "credential: a site can read it and cannot verify "
                         "it"),
        "off_switch": f"{ENV_AGENT_ID}=false",
    }



# -------------------------------------------------- context emulation at open

#: Context options a caller may set when a session OPENS. Every one is a
#: Playwright native passed straight to `launch_persistent_context`; nothing
#: here is a KS4Web invention, and nothing here is applied unless it was
#: asked for. The defaults are unchanged by this route existing.
EMULATION_KEYS: tuple[str, ...] = (
    "viewport", "screen", "locale", "timezone_id", "user_agent",
    "is_mobile", "has_touch", "device_scale_factor",
)

#: Playwright's own device table drops `default_browser_type` into every
#: preset, and `launch_persistent_context` does not take it.
_DEVICE_DROP = ("default_browser_type",)


def parse_viewport(value) -> dict:
    """{'width': N, 'height': N} from a dict or from a '390x844' string.

    The string spelling exists because a caller typing one argument should
    not have to nest a dict to say how wide the window is, and the dict
    spelling exists because it is what Playwright and `emulate` already
    take. Anything else refuses rather than picking a size."""
    if isinstance(value, str):
        parts = value.lower().replace(" ", "").split("x")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return _checked_viewport(int(parts[0]), int(parts[1]), value)
        raise BadParams(
            f"viewport {value!r} is not a size: use '1280x900' or "
            f"{{'width': 1280, 'height': 900}} in CSS pixels.")
    if isinstance(value, dict) and value.get("width") and value.get("height"):
        return _checked_viewport(int(value["width"]), int(value["height"]),
                                 value)
    raise BadParams(
        "viewport takes {'width': N, 'height': N} in CSS pixels, or the "
        "'1280x900' spelling.")


#: The smallest viewport this build will open. One pixel is a legitimate
#: test case (the hostile round read a 1x1 page successfully); zero is not a
#: window at all.
MIN_VIEWPORT_PX = 1

#: Past this, the browser refuses at launch with a protocol error whose text
#: names nothing a caller can act on, so the refusal happens here instead.
MAX_VIEWPORT_PX = 32767


def _checked_viewport(width: int, height: int, given) -> dict:
    """ONE validator for BOTH spellings (fuzzer class 8).

    `manage_session(viewport="0x0")` and `"0x900"` opened a session with a
    zero-pixel viewport and returned ok, while the dict spelling of the same
    values refused BAD_PARAMS: two spellings of one parameter validating
    differently, because the string branch only asked whether the parts were
    digits and the dict branch happened to be falsy-checked. Everything
    downstream is meaningless on a zero-pixel viewport -- in-view,
    occlusion, screenshots, scroll -- so it never opens."""
    if width < MIN_VIEWPORT_PX or height < MIN_VIEWPORT_PX:
        raise BadParams(
            f"viewport {given!r} has a zero dimension, so nothing would be "
            f"in view and no screenshot, scroll, or visibility answer from "
            f"it would mean anything. The smallest this opens is "
            f"{MIN_VIEWPORT_PX}x{MIN_VIEWPORT_PX} CSS pixels.")
    if width > MAX_VIEWPORT_PX or height > MAX_VIEWPORT_PX:
        raise BadParams(
            f"viewport {given!r} is past what the browser accepts "
            f"({MAX_VIEWPORT_PX} CSS pixels per side); a launch with it "
            f"fails inside the driver with a protocol error that names "
            f"nothing you can act on.")
    return {"width": width, "height": height}


def device_names(pw: object) -> list[str]:
    try:
        return sorted(getattr(pw, "devices", {}) or {})
    except Exception:
        return []


def emulation_kwargs(spec: LaneSpec, pw: object, device: str | None = None,
                     viewport=None, locale: str | None = None,
                     timezone: str | None = None) -> tuple[dict, dict]:
    """Resolve what the caller asked the new context to look like.

    Returns `(kwargs, report)`: the Playwright options to launch with, and
    the plain account of what was applied, which `manage_session` prints so
    a session never quietly disagrees with what was requested.

    A named device is Playwright's own preset, applied whole (user agent,
    viewport, scale factor, touch, mobile flag) and then overridden by any
    explicit viewport, so 'iPhone 15' plus a viewport means that phone at
    that size rather than a silent argument fight. **A typo in a device
    name is an error**, never the desktop default, for the reason the whole
    lane subsystem exists: a silent downgrade is the failure this product
    argues against.
    """
    kwargs: dict = {}
    report: dict = {}
    if device:
        table = getattr(pw, "devices", None) or {}
        preset = table.get(device)
        if preset is None:
            names = device_names(pw)
            close = [n for n in names if device.lower() in n.lower()][:8]
            raise BadParams(
                f"unknown device preset {device!r}. The presets are "
                f"Playwright's own device descriptors"
                + (f"; these match what you typed: {close}" if close else
                   f" ({len(names)} of them, from 'iPhone 15' to "
                   f"'Desktop Chrome')")
                + ". Pass viewport / locale / timezone directly when you "
                  "want a shape no preset carries.")
        for key, value in preset.items():
            if key not in _DEVICE_DROP:
                kwargs[key] = value
        report["device"] = device
        # is_mobile is a Chromium and WebKit capability; Playwright's Firefox
        # rejects it outright. Refusing here names the lane that can do it
        # rather than launching a phone-shaped window that is not a phone.
        if kwargs.get("is_mobile") and spec.engine == "firefox":
            raise LaneUnsupported(
                f"[lane {spec.label}] the device preset {device!r} sets "
                f"is_mobile, and Playwright's Firefox does not support it: "
                f"the driver refuses the launch rather than approximating a "
                f"phone. Open this session on Chromium (lane 'A' or "
                f"'B:chrome') or WebKit (lane 'A:webkit') for mobile device "
                f"emulation, or pass viewport / user agent parts you do "
                f"want without a preset.")
    if viewport is not None:
        kwargs["viewport"] = parse_viewport(viewport)
        report["viewport"] = kwargs["viewport"]
    elif "viewport" in kwargs:
        report["viewport"] = kwargs["viewport"]
    if locale is not None:
        text = str(locale).strip()
        if not (2 <= len(text) <= 12) or not text.replace("-", "").replace(
                "_", "").isalnum():
            raise BadParams(
                f"locale {locale!r} is not a BCP 47 tag; it looks like "
                f"'en-US', 'ko-KR', or 'de'.")
        kwargs["locale"] = text
        report["locale"] = text
    if timezone is not None:
        text = str(timezone).strip()
        if not text or " " in text:
            raise BadParams(
                f"timezone {timezone!r} is not an IANA time zone id; it "
                f"looks like 'Asia/Seoul', 'America/New_York', or 'UTC'. "
                f"The browser is the authority on the list.")
        kwargs["timezone_id"] = text
        report["timezone"] = text
    for key in kwargs:
        if key not in EMULATION_KEYS:                   # pragma: no cover
            raise BadParams(
                f"{key!r} is not a context option this route sets; the "
                f"options are {list(EMULATION_KEYS)}.")
    return kwargs, report
