"""``kitchensink4web --setup-browser``: put Lane C on a machine, and take it off.

Four things happen, in this order, and the order is forced by the data rather
than chosen:

1. **Stage the extension.** `artifact.stage` compiles the projection bundle
   from the sources THIS install has and writes a loadable directory. It goes
   first because step 3 needs its path.
2. **Write the relay wrapper.** The script Firefox or Chrome will execute.
3. **Write the host manifest and register it.** The manifest has to name the
   extension id, and on Chromium the id is DERIVED FROM THE STAGED
   DIRECTORY'S PATH, which is why step 1 cannot come later.
4. **Say what the human still has to do.** Which is a real step, not a
   formality: no command can add an extension to a browser on the user's
   behalf, and pretending otherwise would leave them with a working host and
   no extension, wondering why nothing connects.

WHAT THIS COMMAND WILL NOT DO. It does not launch a browser, it does not
click "Add", and it does not write outside the per-user application directory
and the browser's own registration location. Those are the same boundaries
the extension itself keeps, and a setup command that reached further than the
thing it is setting up would be the wrong shape.

Removal is the same list backwards, reported piece by piece, in `remove()`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import artifact, manifests, register

#: The flavor each browser loads. Firefox takes MV2, everything else MV3.
_FLAVOR_OF = {"firefox": "firefox", "chrome": "chromium",
              "chromium": "chromium", "edge": "chromium"}


def default_install_dir() -> Path:
    """Where a normal install puts its own files.

    Per-user, never system-wide: registering a native messaging host under
    HKLM or ``/usr/lib`` would offer the relay to every account on the
    machine, and this extension talks to one person's browser session.
    """
    if os.name == "nt":
        return register._windows_app_dir()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KitchenSink4Web"
    return Path.home() / ".local" / "share" / "KitchenSink4Web"


def staged_extension_dir(install_dir: Path, browser: str) -> Path:
    return Path(install_dir) / "extension" / _FLAVOR_OF[browser]


def install(
    browser: str = "firefox",
    *,
    install_dir: Path | None = None,
    endpoint: Path | None = None,
    extension_id: str | None = None,
    dev_src: Path | None = None,
    python_executable: str | None = None,
    touch_registry: bool = True,
    host_name: str = register.HOST_NAME,
) -> dict:
    """Stage the extension, register the relay, and report every path.

    ``extension_id`` overrides the derived id. It exists because a PACKED
    Chromium extension keeps the id its signing key gives it, and that id
    cannot be computed from a path. Absent one, an unpacked Chromium load
    gets the path-derived id and Firefox gets the id its manifest pins.

    ``host_name`` is not a knob a user needs and exists for the tests: the
    author's machine carries a live `ks4web` registration, and a test that
    wrote to the real name would break their browser to prove a point.
    """
    if browser not in _FLAVOR_OF:
        raise ValueError(
            f"unknown browser {browser!r}; expected one of {sorted(_FLAVOR_OF)}"
        )
    install_dir = Path(install_dir) if install_dir else default_install_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    flavor = _FLAVOR_OF[browser]

    # 1. The extension, compiled here, from this install's projection.
    ext_dir = staged_extension_dir(install_dir, browser)
    staged = artifact.stage(ext_dir, flavor)

    # 2 and 3. Which id the host manifest will trust.
    if extension_id:
        resolved_id, id_source = extension_id, "supplied by the caller"
    elif flavor == "firefox":
        resolved_id, id_source = manifests.GECKO_ID, "pinned in the manifest"
    else:
        resolved_id = artifact.unpacked_chromium_id(ext_dir)
        id_source = "derived from the unpacked directory path"

    registration = register.install(
        install_dir,
        host_name=host_name,
        extension_id=resolved_id,
        python_executable=python_executable,
        src_dir=dev_src,
        endpoint=endpoint,
        touch_registry=touch_registry,
        browser=browser,
    )

    return {
        "action": "install",
        "browser": browser,
        "flavor": flavor,
        "install_dir": str(install_dir),
        "extension": staged,
        "extension_id": resolved_id,
        "extension_id_source": id_source,
        "registration": registration,
        "where": register.describe(browser),
        "verified": verify(browser, install_dir=install_dir,
                           host_name=host_name),
    }


def remove(browser: str = "firefox", *, install_dir: Path | None = None,
           keep_extension: bool = False,
           host_name: str = register.HOST_NAME) -> dict:
    """Take the registration off the machine.

    The staged extension directory goes too unless asked otherwise, because
    leaving 300 KB of compiled projection behind after an uninstall is
    litter, and a later reinstall regenerates it in a few milliseconds
    anyway. What this CANNOT remove is the add-on inside the browser: only
    the person at the keyboard can do that, and the returned dict says so
    rather than reporting a clean removal that left half the system in place.
    """
    install_dir = Path(install_dir) if install_dir else default_install_dir()
    result = register.uninstall(install_dir, host_name=host_name,
                                browser=browser)

    ext_dir = staged_extension_dir(install_dir, browser)
    removed_extension = False
    if not keep_extension and ext_dir.is_dir():
        import shutil
        shutil.rmtree(ext_dir)
        removed_extension = True

    # Only if it is empty. An install directory that still holds another
    # browser's staging is not ours to delete.
    for candidate in (ext_dir.parent, install_dir):
        try:
            if candidate.is_dir() and not any(candidate.iterdir()):
                candidate.rmdir()
        except OSError:
            pass

    return {
        "action": "remove",
        "browser": browser,
        "install_dir": str(install_dir),
        "removed": {**result["removed"], "extension": removed_extension},
        "still_registered": register.read_registration(host_name, browser=browser),
        # Stated as a fact rather than buried: the browser still has the
        # add-on installed and no command here can change that.
        "requires_human": "remove the add-on in the browser's own add-ons page",
    }


def verify(browser: str = "firefox", *, install_dir: Path | None = None,
           host_name: str = register.HOST_NAME) -> dict:
    """Check what is actually on the machine, not what we just tried to write.

    Phase 1's discipline: write it, then read it back through the same oracle
    the browser will use. A registration that reported success and left
    nothing findable is the failure this catches.
    """
    install_dir = Path(install_dir) if install_dir else default_install_dir()
    flavor = _FLAVOR_OF.get(browser, "firefox")
    ext_dir = staged_extension_dir(install_dir, browser)
    found = register.read_registration(host_name, browser=browser)

    expected = set(artifact.files(flavor))
    present = {p.name for p in ext_dir.iterdir()} if ext_dir.is_dir() else set()
    manifest_path = Path(found) if found else None

    return {
        "host_registered": found is not None,
        "host_manifest": found,
        "host_manifest_exists": bool(manifest_path and manifest_path.is_file()),
        "extension_staged": ext_dir.is_dir(),
        "extension_dir": str(ext_dir),
        "extension_complete": bool(present) and not (expected - present),
        "missing_files": sorted(expected - present),
        "digest": artifact.digest(flavor) if ext_dir.is_dir() else None,
    }


# ------------------------------------------------------------------ the print
#
# Every sentence a human reads is [COPY PENDING]. The STRUCTURE and the FACTS
# are settled here -- which paths, which order, which step needs a person --
# and the wording is the author's to write. An agent writing product copy is
# the thing the standing rule forbids, and a setup command's output is
# product copy: it is the first prose most users will ever see from this
# project.

def render(result: dict) -> str:
    """The text `--setup-browser` prints."""
    lines: list[str] = []
    if result["action"] == "remove":
        removed = result["removed"]
        lines.append(f"KS4Web browser setup removed for {result['browser']}.")
        for piece in ("registry_key", "manifest", "wrapper", "extension"):
            state = "removed" if removed.get(piece) else "nothing to remove"
            lines.append(f"  {piece}: {state}")
        if result["still_registered"]:
            lines.append(f"  STILL REGISTERED: {result['still_registered']}")
        lines.append("")
        lines.append("[COPY PENDING] the one step this command cannot do for you: "
                     f"{result['requires_human']}.")
        return "\n".join(lines)

    ext = result["extension"]
    reg = result["registration"]
    where = result["where"]
    verified = result["verified"]

    lines.append(f"KS4Web browser setup for {result['browser']} "
                 f"(extension {ext['version']}, manifest v"
                 f"{2 if result['flavor'] == 'firefox' else 3}).")
    lines.append("")
    lines.append("Written:")
    lines.append(f"  extension   {ext['path']}")
    lines.append(f"              {len(ext['files'])} files, "
                 f"{sum(ext['bytes'].values())} bytes, digest {ext['digest']}")
    lines.append(f"  relay       {reg['wrapper']}")
    lines.append(f"  host        {reg['manifest']}")
    if reg["registry_key"]:
        lines.append(f"  registered  {reg['registry_key']}")
    elif where["mechanism"] == "manifest directory":
        # On POSIX the manifest's location IS the registration, so writing
        # the file was the whole act and there is nothing else to report.
        lines.append(f"  registered  {where['location']}")
    else:
        # Windows with the registry left alone. Saying "registered" here
        # would be the confident wrong line: the files exist and the browser
        # cannot find them.
        lines.append(f"  NOT registered (registry untouched); the key this "
                     f"browser reads is {where['location']}")
    lines.append(f"  extension id {result['extension_id']} "
                 f"({result['extension_id_source']})")
    lines.append("")

    lines.append("Verified on disk:")
    lines.append(f"  host registration found: {verified['host_registered']}")
    lines.append(f"  extension staged and complete: {verified['extension_complete']}")
    if verified["missing_files"]:
        lines.append(f"  MISSING: {', '.join(verified['missing_files'])}")
    if not where["proven_on_this_platform"]:
        lines.append(f"  NOTE: {where['browser']} on {where['platform']} is "
                     "written from vendor documentation and has not been "
                     "exercised by the project's own tests.")
    lines.append("")

    lines.append("[COPY PENDING] next steps heading: this command cannot add the "
                 "extension to your browser; you do that yourself.")
    for n, step in enumerate(_next_steps(result), start=1):
        lines.append(f"  {n}. {step}")
    lines.append("")
    lines.append("[COPY PENDING] the two permission warnings the browser will "
                 "show, what each one actually means, and what the extension "
                 "refuses to do.")
    lines.append("[COPY PENDING] how to undo this: "
                 f"kitchensink4web --setup-browser --browser {result['browser']} --remove")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """``python -m kitchensink4web.extension.setup``.

    The same command `--setup-browser` runs, reachable without importing the
    MCP server. That is not a convenience: `server.py` pulls in fastmcp, and
    setting up a browser should not require the machinery it is setting the
    browser up FOR. It also means the installed-wheel proof can run the real
    command rather than a stand-in for it.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kitchensink4web.extension.setup",
        description=("Install or remove the KS4Web browser extension and its "
                     "native messaging host registration."),
    )
    parser.add_argument("--browser", default="firefox",
                        choices=sorted(_FLAVOR_OF))
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--extension-id", default=None)
    parser.add_argument("--install-dir", default=None)
    parser.add_argument("--no-registry", action="store_true",
                        help="write the files and leave the registry alone.")
    args = parser.parse_args(argv)

    where = Path(args.install_dir) if args.install_dir else None
    try:
        if args.remove:
            result = remove(args.browser, install_dir=where)
        else:
            result = install(args.browser, install_dir=where,
                             extension_id=args.extension_id,
                             touch_registry=not args.no_registry)
    except Exception as exc:
        print(f"KS4Web browser setup failed: {exc}", file=sys.stderr)
        return 2

    print(render(result))
    if result["action"] == "remove":
        return 0
    verified = result["verified"]
    if verified["extension_complete"] and (
            verified["host_registered"] or args.no_registry):
        return 0
    return 1


def _next_steps(result: dict) -> list[str]:
    """The FACTS of the manual half. Wording is the author's."""
    path = result["extension"]["path"]
    if result["flavor"] == "firefox":
        return [
            f"[COPY PENDING] open about:debugging#/runtime/this-firefox",
            f"[COPY PENDING] Load Temporary Add-on, and pick "
            f"{Path(path) / 'manifest.json'}",
            "[COPY PENDING] a temporary add-on is dropped on restart; a signed "
            ".xpi installs permanently and is not built yet",
        ]
    return [
        "[COPY PENDING] open the browser's extensions page and turn on "
        "Developer mode",
        f"[COPY PENDING] Load unpacked, and pick {path}",
        f"[COPY PENDING] confirm the id the browser shows is "
        f"{result['extension_id']}; if it differs, re-run with "
        f"--extension-id <the id shown>",
    ]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
