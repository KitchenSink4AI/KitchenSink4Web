"""Build a wheel, install it somewhere clean, and set a browser up from there.

The unit tests check the package-data declaration and look inside a built
wheel. Neither of them proves the thing that actually matters, which is that
`--setup-browser` works when the code is running out of `site-packages`
instead of a checkout. In a checkout every path resolves whether the wheel
would have shipped the file or not, so a checkout cannot tell you.

So this script does the whole trip:

  1. build a wheel from the repository,
  2. make a fresh venv and install the wheel into it with ``--no-deps``,
  3. run the real setup command IN THAT VENV, against a temp install dir,
  4. compare what landed against what the wheel's own modules generate,
  5. run the removal and check the directory is gone,
  6. delete everything it made.

``--no-deps`` is deliberate. The dependencies are fastmcp and playwright and
this proof is not about them; `extension/setup.py` has its own entry point
precisely so that configuring a browser does not require importing the server.
A run that had to download two hundred megabytes to answer "did the JavaScript
ship?" would be answering a different question slowly.

    python scripts/ext_phase4_wheel_check.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: NEVER the shipped host name. The removal step deliberately looks in the
#: real per-user application directory as well as the one it was handed, so a
#: proof run under the default name would uninstall a working Lane C off the
#: developer's own machine as a side effect of checking a wheel.
TEST_HOST = "ks4web_wheel_proof"

#: Nothing appears on the author's desktop. Every subprocess here is silent,
#: has no stdin, and dies on a timeout rather than waiting for a person.
_QUIET = {
    "stdin": subprocess.DEVNULL,
    "capture_output": True,
    "text": True,
    "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
}


def clean_env() -> dict:
    """The environment a fresh machine would have.

    PYTHONPATH is the one that matters and it is not hypothetical: the
    development runs on this branch set it to the worktree's `src`, and a
    venv inheriting it imports the CHECKOUT while every path in the output
    claims the wheel. The first run of this script did exactly that and the
    site-packages assertion is what caught it, which is the argument for
    keeping that assertion rather than trusting the install.
    """
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(name, None)
    return env


def run(cmd: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess:
    started = time.perf_counter()
    proc = subprocess.run(cmd, timeout=timeout, env=clean_env(), **_QUIET)
    proc.elapsed = time.perf_counter() - started  # type: ignore[attr-defined]
    return proc


def build_wheel(outdir: Path) -> Path:
    proc = run([sys.executable, "-m", "build", "--wheel", "--outdir",
                str(outdir), str(ROOT)])
    if proc.returncode != 0:
        raise SystemExit(f"wheel build failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")
    wheels = sorted(outdir.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one wheel, got {[w.name for w in wheels]}")
    return wheels[0]


def wheel_contents(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        return sorted(zf.namelist())


def make_venv(where: Path) -> Path:
    proc = run([sys.executable, "-m", "venv", str(where)])
    if proc.returncode != 0:
        raise SystemExit(f"venv creation failed:\n{proc.stderr[-2000:]}")
    python = (where / "Scripts" / "python.exe") if os.name == "nt" \
        else (where / "bin" / "python")
    if not python.is_file():
        raise SystemExit(f"no interpreter at {python}")
    return python


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None, help="write findings here")
    parser.add_argument("--keep", action="store_true",
                        help="leave the scratch tree in place for inspection")
    args = parser.parse_args()

    findings: dict = {"steps": [], "ok": False}
    scratch = Path(tempfile.mkdtemp(prefix="ks4web_phase4_wheel_"))
    findings["scratch"] = str(scratch)

    try:
        # 1. The wheel.
        wheel = build_wheel(scratch / "dist")
        names = wheel_contents(wheel)
        assets = [n for n in names if "/extension/assets/" in n]
        projection = [n for n in names if "/projection/" in n and n.endswith(".js")]
        prebuilt = [n for n in names if n.endswith("projection.bundle.js")]
        findings["wheel"] = {
            "name": wheel.name,
            "bytes": wheel.stat().st_size,
            "extension_assets": assets,
            "projection_sources": len(projection),
            "prebuilt_bundle_present": bool(prebuilt),
        }
        findings["steps"].append("built the wheel and listed it")
        assert assets, "the wheel carries no extension assets"
        assert projection, "the wheel carries no projection sources"
        assert not prebuilt, "the wheel carries a prebuilt bundle; it should compile at setup"

        # 2. A clean interpreter that has never seen this project.
        python = make_venv(scratch / "venv")
        proc = run([str(python), "-m", "pip", "install", "--no-deps",
                    "--quiet", str(wheel)])
        if proc.returncode != 0:
            raise SystemExit(f"wheel install failed:\n{proc.stderr[-3000:]}")
        findings["steps"].append("installed the wheel with --no-deps")

        # Where the package actually landed. If this resolves inside the
        # repository the whole proof is void, so it is recorded.
        proc = run([str(python), "-c",
                    "import kitchensink4web, json, sys;"
                    "print(json.dumps({'file': kitchensink4web.__file__}))"])
        if proc.returncode != 0:
            raise SystemExit(f"import failed:\n{proc.stderr[-3000:]}")
        installed_at = json.loads(proc.stdout.strip())["file"]
        findings["installed_at"] = installed_at
        assert "site-packages" in installed_at, (
            f"the package resolved to {installed_at}, not an installed location")
        assert str(ROOT) not in installed_at, "resolved back into the checkout"
        findings["steps"].append("verified the import comes from site-packages")

        # 3. The real command, from the installed copy, registry untouched.
        target = scratch / "installdir"
        proc = run([str(python), "-m", "kitchensink4web.extension.setup",
                    "--browser", "firefox", "--no-registry",
                    "--host-name", TEST_HOST,
                    "--install-dir", str(target)])
        findings["setup_stdout"] = proc.stdout
        findings["setup_returncode"] = proc.returncode
        if proc.returncode != 0:
            raise SystemExit(f"--setup-browser failed:\n{proc.stdout}\n{proc.stderr[-3000:]}")
        findings["steps"].append("ran the setup command from the installed wheel")

        staged = target / "extension" / "firefox"
        landed = sorted(p.name for p in staged.iterdir())
        findings["staged_files"] = landed
        findings["staged_bytes"] = {p.name: p.stat().st_size
                                    for p in sorted(staged.iterdir())}
        assert "projection.bundle.js" in landed, (
            "the bundle was not compiled on the target machine")
        bundle_size = (staged / "projection.bundle.js").stat().st_size
        assert bundle_size > 100_000, f"the bundle is only {bundle_size} bytes"

        # 4. Does the installed copy generate what it staged? This is the
        #    property the packaging decision rests on, asked of the install
        #    rather than of the checkout.
        proc = run([str(python), "-c",
                    "import json,sys;"
                    "from pathlib import Path;"
                    "from kitchensink4web.extension import artifact;"
                    "d=Path(sys.argv[1]);"
                    "want=artifact.files('firefox');"
                    "bad=[n for n,t in want.items() "
                    "if (d/n).read_text(encoding='utf-8')!=t];"
                    "print(json.dumps({'mismatched': bad, "
                    "'digest': artifact.digest('firefox')}))",
                    str(staged)])
        if proc.returncode != 0:
            raise SystemExit(f"comparison failed:\n{proc.stderr[-3000:]}")
        compared = json.loads(proc.stdout.strip())
        findings["compared"] = compared
        assert not compared["mismatched"], compared["mismatched"]
        findings["steps"].append("staged bytes equal what the installed copy generates")

        # 5. And take it back off.
        proc = run([str(python), "-m", "kitchensink4web.extension.setup",
                    "--browser", "firefox", "--remove",
                    "--host-name", TEST_HOST,
                    "--install-dir", str(target)])
        findings["remove_stdout"] = proc.stdout
        findings["remove_returncode"] = proc.returncode
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert not staged.exists(), "the staged extension survived --remove"
        findings["steps"].append("removal took the staged extension off")

        findings["ok"] = True
        return 0
    except AssertionError as exc:
        findings["failure"] = f"{type(exc).__name__}: {exc}"
        return 1
    except SystemExit as exc:
        findings["failure"] = str(exc)
        return 1
    finally:
        if args.json:
            Path(args.json).write_text(json.dumps(findings, indent=2),
                                       encoding="utf-8")
        print(json.dumps({k: v for k, v in findings.items()
                          if k not in ("setup_stdout", "remove_stdout")},
                         indent=2))
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
