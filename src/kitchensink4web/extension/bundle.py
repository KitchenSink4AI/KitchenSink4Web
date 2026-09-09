"""The projection, compiled for the extension's isolated world.

THE PAYLOAD-PARITY SEAM, and it is the one decision Phase 2 rests on.

`projection/` never imports playwright; it takes a page-like object with an
`evaluate` method and returns the same dict whatever ran the walk. So Lane C
does not need its own reader. It needs the SAME `extract.js`, the same
`find.js`, the same `text.js`, running somewhere else, and then every block
downstream of them -- the ranker, the meter, the render ladder, the anchor
map, `act.target_descriptor`, `act.action_class_for`, the gate fingerprint --
applies unchanged because it is looking at the same units.

Two differences from the Playwright path, both structural:

**No eval.** A content script cannot run source text the native host sent it
without `unsafe-eval` in the manifest, which is the single fastest way to
fail AMO review and is a remote-code-execution shape besides. So the scripts
are BAKED into the extension as a static file and the wire carries a NAME
from a closed set. `EXTENSION_SCRIPTS` is that set, and a test pins the file
on disk equal to what this module generates from the projection sources, so
the copy cannot drift.

**The instrument channel lives in the isolated world.** On the Playwright
lane the state hides behind a non-configurable window accessor guarded by a
per-process secret, because the script runs in the page's own realm and the
page could otherwise reach it. A content script has its own global scope that
page script cannot address at all, so the channel is a plain closure here and
the secret is not needed. `instrument.js`'s own RESIDUAL note -- that the
accessor's presence is detectable -- does not apply on this lane: there is no
accessor on `window` to detect.

What that costs, stated rather than papered over: `Element.prototype` reached
from a content script is the Xray view, so patching `attachShadow` there does
not see roots the PAGE creates. Closed shadow roots are therefore NOT COUNTED
on Lane C, and `read()` marks the field `None` rather than reporting a zero
the lane did not earn. `lanes.CAPABILITIES["closed_shadow_count"]` carries the
row and the renderers print the absence.
"""

from __future__ import annotations

from pathlib import Path

from .. import projection as _projection

#: The scripts the extension carries, by the name the wire uses. A closed set:
#: `content.js` looks a name up in this table and refuses anything else, so
#: the native host cannot ask the page to run something the extension did not
#: ship. The names are the projection's own module names.
EXTENSION_SCRIPTS: tuple[str, ...] = ("extract", "find", "text", "article",
                                      "schema")

#: Where the generated file lives, relative to the repository root.
BUNDLE_RELPATH = "extension/projection.bundle.js"

#: The isolated-world instrument channel. Same state object `instrument.js`
#: builds and the same field names, because the projection sources read those
#: fields by name; what is gone is the window accessor, the secret, and the
#: `attachShadow` patch, none of which can do their job from this side of the
#: Xray boundary.
_ISOLATED_STATE = """\
// The instrument channel, isolated-world edition. See extension/bundle.py.
//
// The page cannot reach this object. A content script's global scope is not
// addressable from page script, so the state needs no accessor, no secret,
// and no non-configurable property descriptor: the three mechanisms
// `projection/instrument.js` uses to survive in the page's own realm.
//
// `closed` is null and stays null. Counting closed shadow roots means
// patching Element.prototype.attachShadow where PAGE script will call it,
// and Element.prototype reached from here is the Xray view, so a patch
// applied on this side would count nothing and report a confident zero. A
// number this lane did not earn is worse than no number, so the field is an
// absence and the Python side renders it as one.
const KS4WEB_STATE = {
  refs: new Map(),
  refof: new WeakMap(),
  seq: 0,
  act: Object.create(null),
  actseq: 0,
  closed: null,
  doc: 0,
  frameid: new WeakMap(),
  frameseq: 0
};
"""

#: What the instrument PRELUDE becomes here. The Playwright prelude reaches
#: through the window accessor and returns INSTRUMENT_MISSING when the init
#: script never ran; there is no equivalent failure on this lane, because the
#: state is in the same closure as the code reading it.
_ISOLATED_PRELUDE = "  const KS = KS4WEB_STATE;\n"

#: The window property the bundle publishes itself on. A content script's
#: `window` is the page's window seen through an Xray wrapper, and a property
#: written on it from this side lands in the sandbox's expando store: the
#: extension sees it, page script does not. That is what makes an on-demand
#: `executeScript` injection safe to publish through.
BUNDLE_KEY = "__ks4webScripts"

#: Where the shared state hangs, so a SECOND injection into the same document
#: finds the refs the first one minted instead of starting a fresh registry
#: and invalidating every ref the caller is holding.
STATE_KEY = "__ks4webState"

_HEADER = """\
/*
 * KS4Web projection bundle. GENERATED FILE, DO NOT EDIT.
 *
 * Produced by src/kitchensink4web/extension/bundle.py from the sources in
 * src/kitchensink4web/projection/. `test_ext_bundle.py` pins this file equal
 * to what that module generates, so an edit to a projection source that is
 * not rebuilt here fails the suite rather than shipping a Lane C that reads
 * pages differently from every other lane.
 *
 * Injected ON DEMAND by the background script, never from the manifest. The
 * shared blocks are hoisted once here rather than spliced into each script,
 * which is the difference between 290 KB and 575 KB; even so, parsing this
 * in every frame of every page the user visits is a cost no page that is
 * never read should pay. A page that IS read pays one injection, once,
 * and the guard below makes a second injection into the same document free.
 *
 * Rebuild: python -m kitchensink4web.extension.bundle
 */
"""


#: Mark -> the block that replaces it here. Every entry except the instrument
#: one is the SAME block the Playwright path splices, read from the same file
#: on disk, which is the property `visibility.js` and `payment.js` were
#: consolidated to get: a rule added there reaches both lanes at once.
#:
#: The instrument mark is the exception and it has to be, because
#: `projection.INSTRUMENT_PRELUDE` bakes a secret minted fresh at every
#: process start. Splicing through `projection.instrument()` and substituting
#: afterwards would make this file's bytes depend on which process generated
#: them, and the drift test would then fail on every run for a reason that is
#: not drift.
def _blocks() -> dict[str, str]:
    return {
        "// @@KS4WEB_VISIBILITY@@": _projection.VISIBILITY_JS,
        "// @@KS4WEB_PAYMENT@@": _projection.PAYMENT_JS,
        "// @@KS4WEB_ACTIVATION@@": _projection.ACTIVATION_JS,
        "// @@KS4WEB_ARIA@@": _projection.ARIA_JS,
        "// @@KS4WEB_CONSENT@@": _projection.CONSENT_JS,
        "// @@KS4WEB_HREF@@": _projection.HREF_JS,
        "// @@KS4WEB_RENDERED@@": _projection.RENDERED_JS,
    }


#: The marks a script body carries, in the order they are hoisted. A mark is
#: replaced by nothing in the body and its block is emitted ONCE at bundle
#: scope, where every script body closes over it. The Playwright path cannot
#: do this -- each `evaluate` ships one self-contained function -- and the
#: bundle can, because all five scripts live in one file.
_HOISTED = tuple(_blocks())


def _isolated(source: str) -> str:
    """A script body with its shared blocks removed and its prelude bound.

    The blocks come back at bundle scope; the prelude is replaced in place,
    because `const KS` has to be a binding inside each function rather than
    a shared one (the Playwright path scopes it per evaluate and a script
    that reassigned a shared `KS` would reach across calls)."""
    source = source.replace("// @@KS4WEB_INSTRUMENT@@",
                            _ISOLATED_PRELUDE.rstrip("\n"))
    for mark in _HOISTED:
        source = source.replace(
            mark, f"// (hoisted to bundle scope) {mark[3:]}")
    return source


def _source_of(name: str) -> str:
    path = Path(_projection.__file__).parent / f"{name}.js"
    return _isolated(path.read_text(encoding="utf-8"))


def build() -> str:
    """The bundle text, generated from the projection sources on disk."""
    parts = [
        _HEADER,
        "(function () {",
        "  'use strict';",
        f'  if (window["{BUNDLE_KEY}"]) {{ return; }}',
        "",
        _ISOLATED_STATE,
        "",
        "// ---- the shared blocks, hoisted once ----",
    ]
    for block in _blocks().values():
        parts.append(block.rstrip())
    parts += ["", "// ---- the scripts ----", "const KS4WEB_SCRIPTS = {"]
    for name in EXTENSION_SCRIPTS:
        parts.append(f"  {name}: (")
        parts.append(_source_of(name).rstrip())
        parts.append("  ),")
    parts += [
        "};",
        "",
        f'  window["{STATE_KEY}"] = KS4WEB_STATE;',
        f'  window["{BUNDLE_KEY}"] = KS4WEB_SCRIPTS;',
        "})();",
    ]
    return "\n".join(parts) + "\n"


def bundle_path(root: Path | None = None) -> Path:
    """Where the generated file lives. `root` is the repository root."""
    here = Path(__file__).resolve()
    base = root if root is not None else here.parents[3]
    return Path(base) / BUNDLE_RELPATH


def write(root: Path | None = None) -> Path:
    path = bundle_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(), encoding="utf-8", newline="\n")
    return path


def main() -> int:  # pragma: no cover - a developer convenience
    path = write()
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
