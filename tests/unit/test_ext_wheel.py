"""Does the wheel actually carry the extension?

A `package-data` glob is a claim, and the way this claim fails is quiet: a
typo'd pattern builds a wheel that installs cleanly, imports cleanly, and
refuses at `--setup-browser` on a user's machine with a missing-file error.
Nothing in a source checkout notices, because in a checkout the files are
right there next to the module whether the wheel would have shipped them or
not.

So one test asserts the DECLARATION and one BUILDS A WHEEL and looks inside
it. The second is slow and marked; the first runs always and catches the
common case, which is somebody adding an asset and not the glob.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from kitchensink4web.extension import artifact

ROOT = Path(__file__).resolve().parents[2]


def _package_data_globs() -> list[str]:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        config = tomllib.load(fh)
    return config["tool"]["setuptools"]["package-data"]["kitchensink4web"]


def test_every_asset_on_disk_is_covered_by_a_package_data_glob():
    """The cheap check, and the one that catches the realistic mistake.

    Someone adds `assets/options.js`, the glob still says `assets/*.js`, and
    this passes. Someone adds `assets/icons/16.png` and it does not, which is
    the moment to think about it rather than three weeks later.
    """
    globs = _package_data_globs()
    for asset in artifact.assets_dir().iterdir():
        if not asset.is_file():
            continue
        relative = f"extension/assets/{asset.name}"
        assert any(Path(relative).match(g) for g in globs), (
            f"{relative} is on disk but no package-data glob in pyproject.toml "
            f"would put it in a wheel: {globs}"
        )


def test_the_projection_sources_are_declared_too():
    """The bundle is compiled from these at setup time. A wheel without them
    installs a server that cannot stage an extension at all."""
    globs = _package_data_globs()
    assert any(Path("projection/extract.js").match(g) for g in globs)


@pytest.mark.slow
def test_a_freshly_built_wheel_contains_the_extension_sources(tmp_path):
    """Build one and look inside it.

    This is the only check that tests what `pip install` will actually
    deliver. It is slow because it shells out to the build backend, so it
    carries a marker and the phase 4 script runs the fuller version that also
    installs into a scratch venv and calls `--setup-browser` from there.
    """
    try:
        import build  # noqa: F401
    except ImportError:  # pragma: no cover - depends on the dev environment
        pytest.skip("the `build` package is not installed")

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path),
         str(ROOT)],
        capture_output=True, text=True, timeout=600,
        # Nothing on the author's desktop. See the silent-subprocess rule.
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]

    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, [w.name for w in wheels]

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())

    for asset in artifact.assets_dir().iterdir():
        if asset.is_file():
            expected = f"kitchensink4web/extension/assets/{asset.name}"
            assert expected in names, (
                f"{expected} is missing from the wheel; package-data did not "
                "pick it up"
            )

    # And the projection, without which the bundle cannot be compiled on the
    # target machine.
    assert "kitchensink4web/projection/extract.js" in names

    # The prebuilt bundle must NOT be in there. Shipping one would put the
    # drift this design removes straight back in.
    assert not any(n.endswith("projection.bundle.js") for n in names), (
        "a prebuilt projection bundle is in the wheel; the whole point of "
        "compiling at setup time is that no build machine's copy travels"
    )
