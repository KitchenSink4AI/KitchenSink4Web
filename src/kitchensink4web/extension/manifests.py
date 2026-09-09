"""One description of the extension, two manifests.

Spec section 10 asks for Firefox MV2 and Chromium MV3 off the same codebase.
The risk in "two manifests" is that they drift: a permission added to one and
forgotten in the other is a capability that exists on one browser and silently
does not on the other, and the failure surfaces as a tool that works for the
author and not for a user. So neither manifest is a file anybody edits. Both
are PROJECTIONS of the one description below, and `test_ext_manifests.py`
pins the properties that have to hold on both.

What actually differs between MV2 and MV3, and it is a short list because the
API surface `background.js` uses is small:

============================  ===================  =========================
Concern                       Firefox MV2          Chromium MV3
============================  ===================  =========================
background                    persistent page      service worker
host permissions              in ``permissions``   in ``host_permissions``
script injection              ``tabs.executeScript``  ``scripting.executeScript``
the API global                ``browser``          ``chrome``
extension identity            ``gecko.id``         derived from key or path
============================  ===================  =========================

The last three are handled by ``assets/compat.js`` rather than by branching
the two hundred call sites in ``background.js``: on Chromium the shim
publishes a ``browser`` global whose ``tabs.executeScript`` has the MV2
signature and the MV3 implementation. Firefox never loads the shim, so the
Firefox build's JavaScript is byte-identical to what phases 1 through 3
tested. That is the point of doing it this way rather than rewriting the
call sites: the lane that is proven stays proven.
"""

from __future__ import annotations

import json

#: The extension id Firefox pins us to. Native messaging checks it: the host
#: manifest's ``allowed_extensions`` names this exact string, so an id that
#: moved would be a browser that cannot reach the relay.
GECKO_ID = "web@kitchensink4.ai"

#: The extension version. Distinct from the Python package version on purpose:
#: a signed .xpi is a separately versioned artefact and AMO refuses a re-upload
#: of a version it has already seen, so this number moves when the extension's
#: own contents move rather than when the server ships.
VERSION = "0.2.0"

#: Firefox's floor, and it is NOT the version the code needs. The code needs
#: 109, where MV2 `browser.*` promises and the scripting behaviour this build
#: relies on are all present, and that is what the spec and phase 1 wrote.
#:
#: 142 is the version that makes `data_collection_permissions` legal. AMO now
#: requires that key on new extensions, and `web-ext lint` measured all three
#: combinations here:
#:
#:   109 + no key   -> 0 errors, 1 warning (the key AMO will demand)
#:   109 + the key  -> 0 errors, 2 warnings (the key is ignored below 142)
#:   142 + the key  -> 0 errors, 0 warnings
#:
#: Pinned at 142 because this extension has no install base to strand: nobody
#: is running it on Firefox 130 today, so the floor costs nothing that exists,
#: and a clean lint is worth having before the first signing run rather than
#: after. RESIDUAL, and it is the reason this is a constant with a comment
#: rather than a number: Firefox ESR trails the release channel, so an ESR
#: below 142 would be excluded by this. Nobody here has checked which ESR line
#: is current, and the fix if it matters is one string.
STRICT_MIN_FIREFOX = "142.0"

#: Chrome's floor. 110 is the first release where a native messaging port
#: keeps an MV3 service worker alive for as long as the port is open, which
#: is the whole reason Lane C can hold a persistent connection there at all.
MIN_CHROME = "110"

#: The name every human-visible string is waiting on.
NAME = "[COPY PENDING] KitchenSink4Web"
DESCRIPTION = "[COPY PENDING] extension store description"

#: WHAT WE TELL MOZILLA WE COLLECT, and this one is the author's call rather
#: than an engineering default. `web-ext lint` 10.6.0 reports
#: MISSING_DATA_COLLECTION_PERMISSIONS: the key is required for all new
#: Firefox extensions and will become required for new versions of existing
#: ones, so an AMO submission without it is a submission that gets bounced.
#:
#: The value below says the add-on collects nothing. The engineering case for
#: it is that nothing leaves the device: the extension hands page content to a
#: native messaging host the user installed on their own machine, and there is
#: no network call to us or to anyone else anywhere in `background.js`. Mozilla
#: scopes "data collection" to data transmitted to the developer or a third
#: party, and by that scope this is `none`.
#:
#: The case for declaring `websiteContent` instead is that the extension does
#: read page content, including on pages the user is logged into, and a
#: reviewer reading `<all_urls>` plus `nativeMessaging` will be looking hard at
#: exactly that. Over-declaring is cheap and under-declaring is a compliance
#: problem, which is an argument for the more conservative value.
#:
#: FLAGGED FOR THE AUTHOR. This is a statement made to a store about data
#: handling, not a technical default, so it is not an agent's to settle. One
#: list entry changes it.
DATA_COLLECTION_REQUIRED = ["none"]

#: Permissions that mean the same thing under both manifest versions.
_COMMON_PERMISSIONS = ("activeTab", "tabs", "nativeMessaging", "storage",
                       "webNavigation")

#: The host match this extension needs, and the one AMO scrutinises hardest.
#: MV2 carries it in `permissions`; MV3 splits it into `host_permissions`.
ALL_URLS = "<all_urls>"

#: The scripts a content script load is made of, in order. On Chromium the
#: shim has to define `browser` before `content.js` reads it, so the order is
#: load-bearing rather than cosmetic.
_CONTENT_FIREFOX = ("content.js",)
_CONTENT_CHROMIUM = ("compat.js", "content.js")

FLAVORS = ("firefox", "chromium")


def _content_scripts(files: tuple[str, ...]) -> list[dict]:
    return [{
        "matches": [ALL_URLS],
        "js": list(files),
        "run_at": "document_idle",
        # FIELD CORRECTION 2 from the spec: with `all_frames` on, a
        # `tabs.sendMessage` without an explicit frameId can be answered by
        # whichever frame replies first. The background script always names
        # frame 0. This flag is what makes descending into a named subframe
        # possible at all, so it stays on and the discipline lives at the
        # call site.
        "all_frames": True,
    }]


def firefox() -> dict:
    """The MV2 manifest Firefox loads."""
    return {
        "manifest_version": 2,
        "name": NAME,
        "version": VERSION,
        "description": DESCRIPTION,
        "permissions": [*_COMMON_PERMISSIONS, ALL_URLS],
        "background": {
            "scripts": ["background.js"],
            # MV2 persistence is the structural advantage this lane was
            # chosen for: no service-worker cold start, no state to
            # rehydrate, and a native port that simply stays open.
            "persistent": True,
        },
        "content_scripts": _content_scripts(_CONTENT_FIREFOX),
        "browser_specific_settings": {
            "gecko": {
                "id": GECKO_ID,
                "strict_min_version": STRICT_MIN_FIREFOX,
                "data_collection_permissions": {
                    "required": list(DATA_COLLECTION_REQUIRED),
                },
            },
        },
    }


def chromium(*, key: str | None = None) -> dict:
    """The MV3 manifest Chrome, Edge, Brave and Opera load.

    ``key`` pins the extension id. Without it Chromium derives the id from
    the absolute path of the unpacked directory, which means the id changes
    when the directory moves and the native messaging host manifest that
    named the old id stops matching. `setup.py` handles both routes and says
    which one it took.
    """
    manifest = {
        "manifest_version": 3,
        "name": NAME,
        "version": VERSION,
        "description": DESCRIPTION,
        # `scripting` is the MV3 replacement for MV2's tabs.executeScript
        # permission. Everything else is the same word for the same thing.
        "permissions": [*_COMMON_PERMISSIONS, "scripting"],
        "host_permissions": [ALL_URLS],
        "background": {
            # A classic service worker, not a module. `compat.js` is
            # concatenated ahead of `background.js` at staging time rather
            # than imported, because an ES module service worker would
            # change how `background.js` itself is parsed and this build
            # wants that file to stay the file that was tested.
            "service_worker": "background.js",
        },
        "content_scripts": _content_scripts(_CONTENT_CHROMIUM),
        "minimum_chrome_version": MIN_CHROME,
    }
    if key:
        manifest["key"] = key
    return manifest


def build(flavor: str, *, key: str | None = None) -> dict:
    if flavor == "firefox":
        return firefox()
    if flavor == "chromium":
        return chromium(key=key)
    raise ValueError(f"unknown extension flavor {flavor!r}; expected one of {FLAVORS}")


def render(flavor: str, *, key: str | None = None) -> str:
    """The manifest as the bytes that go in the directory."""
    return json.dumps(build(flavor, key=key), indent=2) + "\n"
