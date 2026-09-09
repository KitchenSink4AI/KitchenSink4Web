"""Stage, lint and pack the extension. Signing is a flag away and not taken.

    python scripts/ext_phase4_package.py --json out.json
    python scripts/ext_phase4_package.py --sign --channel unlisted   (needs AMO)

WHY THE UNSIGNED ARTEFACT IS NOT THE SHIPPING ARTEFACT. `web-ext build`
produces a .zip. It is structurally a .xpi and Firefox will not install it:
release Firefox requires the add-on to be signed, and signing is what turns
the .zip into an installable .xpi. Until then the only install route is Load
Temporary Add-on, which is dropped on every restart. So this script builds and
lints, and `--setup-browser` points at the unpacked directory rather than at a
package that cannot be installed.


READY TO RUN, WHEN THE AMO ACCOUNT EXISTS
=========================================

Verified against web-ext 10.6.0, whose flags are quoted here from its own
`sign --help` rather than from memory.

1. Make the credentials. addons.mozilla.org -> Tools -> Manage API Keys.
   It gives a JWT issuer and a secret. THE SECRET IS SHOWN ONCE.

2. Put them in the environment, never on the command line. web-ext reads
   `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET`, and a secret passed as
   `--api-key`/`--api-secret` lands in the shell history and in the process
   list where any other process on the machine can read it.

       $env:WEB_EXT_API_KEY    = "user:12345678:123"
       $env:WEB_EXT_API_SECRET = "..."

3. Choose the channel, and it is a real choice rather than a formality.

       --channel unlisted   signed for self-distribution, no human review,
                            usually minutes. THIS IS THE FIRST ONE TO USE.
       --channel listed     goes on addons.mozilla.org, human review, and
                            `<all_urls>` plus `nativeMessaging` is the
                            highest-scrutiny permission pair Mozilla has.

4. Run it against a STAGED directory, never the repository:

       node .../web-ext.js sign \\
         --source-dir <staged firefox dir> \\
         --artifacts-dir <where the .xpi should land> \\
         --channel unlisted \\
         --upload-source-code <source archive, see step 5>

   The signed .xpi appears in `--artifacts-dir`. AMO refuses a version it has
   already seen, so `manifests.VERSION` moves before every re-sign.

5. `--upload-source-code` IS NOT OPTIONAL FOR US, and it is the step most
   likely to be skipped. `projection.bundle.js` is 300 KB of generated code:
   `bundle.py` compiles it from `src/kitchensink4web/projection/*.js` and
   hoists the shared blocks. Mozilla requires human-readable source plus
   build instructions whenever the submitted code is generated or minified,
   and a submission without it gets held. The archive needs the projection
   sources, `bundle.py`, `artifact.py`, `manifests.py`, and one line saying
   `python -m kitchensink4web.extension.artifact` rebuilds the directory.

6. After signing, `--setup-browser` should hand the user the .xpi instead of
   the unpacked directory. NOT BUILT: the flow, the hosting location for the
   .xpi, and the update manifest for self-distribution are all decisions that
   need the account to exist first.

WHAT IS BLOCKING. There is no AMO account, so none of this has been run. The
lint is clean and the package builds, which is everything that can be proven
without one.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from kitchensink4web.extension import artifact, manifests  # noqa: E402

_QUIET = {
    "stdin": subprocess.DEVNULL,
    "capture_output": True,
    "text": True,
    "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
}


def find_web_ext() -> list[str] | None:
    """web-ext, however it is installed on this machine.

    Not a project dependency: it is a Node tool used at release time, and
    adding a node_modules to a Python package to lint an extension nobody is
    signing yet would be the wrong trade.
    """
    direct = shutil.which("web-ext")
    if direct:
        return [direct]
    for env in ("WEB_EXT_BIN", "KS4WEB_WEB_EXT"):
        candidate = os.environ.get(env)
        if candidate and Path(candidate).is_file():
            return [shutil.which("node") or "node", candidate]
    node = shutil.which("node")
    if node:
        for base in (ROOT, Path.cwd()):
            script = base / "node_modules" / "web-ext" / "bin" / "web-ext.js"
            if script.is_file():
                return [node, str(script)]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None,
                        help="where to stage and pack (default: a temp dir)")
    parser.add_argument("--json", default=None)
    parser.add_argument("--sign", action="store_true",
                        help="submit to AMO. Needs WEB_EXT_API_KEY and "
                             "WEB_EXT_API_SECRET in the environment.")
    parser.add_argument("--channel", default="unlisted",
                        choices=["unlisted", "listed"])
    args = parser.parse_args()

    out = Path(args.out) if args.out else Path(
        __import__("tempfile").mkdtemp(prefix="ks4web_package_"))
    out.mkdir(parents=True, exist_ok=True)
    findings: dict = {"out": str(out), "version": manifests.VERSION}

    # Stage both, because a packaging run that only ever exercised one of
    # them would let the other rot between releases.
    for flavor in manifests.FLAVORS:
        staged = artifact.stage(out / "staged" / flavor, flavor)
        findings.setdefault("staged", {})[flavor] = {
            "path": staged["path"],
            "files": staged["files"],
            "digest": staged["digest"],
            "bytes": sum(staged["bytes"].values()),
        }

    web_ext = find_web_ext()
    findings["web_ext"] = web_ext
    if not web_ext:
        findings["lint"] = "SKIPPED: web-ext is not installed"
        findings["build"] = "SKIPPED: web-ext is not installed"
    else:
        firefox_dir = out / "staged" / "firefox"

        lint = subprocess.run(
            [*web_ext, "lint", "--source-dir", str(firefox_dir),
             "--no-config-discovery", "--output", "json"],
            timeout=600, **_QUIET)
        findings["lint"] = _summarise_lint(lint)

        build = subprocess.run(
            [*web_ext, "build", "--source-dir", str(firefox_dir),
             "--artifacts-dir", str(out / "artifacts"), "--overwrite-dest",
             "--no-config-discovery"],
            timeout=600, **_QUIET)
        findings["build"] = {"returncode": build.returncode,
                             "stderr": build.stderr[-1500:]}
        packages = sorted((out / "artifacts").glob("*.zip")) + \
            sorted((out / "artifacts").glob("*.xpi"))
        if packages:
            package = packages[0]
            with zipfile.ZipFile(package) as zf:
                names = sorted(zf.namelist())
            findings["package"] = {
                "path": str(package),
                "bytes": package.stat().st_size,
                "contents": names,
                # The one check that says the pack is the staging: a build
                # that silently dropped the 300 KB bundle would still
                # produce a plausible-looking artefact.
                "matches_staging": names == sorted(artifact.files("firefox")),
            }

        if args.sign:
            if not (os.environ.get("WEB_EXT_API_KEY")
                    and os.environ.get("WEB_EXT_API_SECRET")):
                findings["sign"] = ("REFUSED: WEB_EXT_API_KEY and "
                                    "WEB_EXT_API_SECRET are not in the "
                                    "environment")
            else:
                signed = subprocess.run(
                    [*web_ext, "sign", "--source-dir", str(firefox_dir),
                     "--artifacts-dir", str(out / "signed"),
                     "--channel", args.channel, "--no-config-discovery"],
                    timeout=1800, **_QUIET)
                findings["sign"] = {
                    "returncode": signed.returncode,
                    "channel": args.channel,
                    "artifacts": [str(p) for p in
                                  sorted((out / "signed").glob("*"))],
                    "stderr": signed.stderr[-2000:],
                }
        else:
            findings["sign"] = "NOT ATTEMPTED: no AMO account yet"

    if args.json:
        Path(args.json).write_text(json.dumps(findings, indent=2),
                                   encoding="utf-8")
    print(json.dumps(findings, indent=2))

    lint_result = findings.get("lint")
    if isinstance(lint_result, dict) and lint_result.get("errors"):
        return 1
    return 0


def _summarise_lint(proc: subprocess.CompletedProcess) -> dict:
    """Counts, and the messages when there are any.

    `--output json` puts the report on stdout. A non-zero return code from
    web-ext lint means errors were found, which is a result rather than a
    crash, so it is recorded rather than raised.
    """
    summary: dict = {"returncode": proc.returncode}
    try:
        report = json.loads(proc.stdout)
    except ValueError:
        summary["raw"] = (proc.stdout or proc.stderr)[-2000:]
        return summary
    for level in ("errors", "warnings", "notices"):
        items = report.get(level) or []
        summary[level] = len(items)
        if items:
            summary[f"{level}_detail"] = [
                {"code": i.get("code"), "message": i.get("message")}
                for i in items
            ]
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
