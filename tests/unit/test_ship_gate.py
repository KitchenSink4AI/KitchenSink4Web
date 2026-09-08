"""THE PRE-SHIP GREP GATE: a check that reads the artifact.

Every publishing defect the 2026-09-08 audit found was catchable by one
grep, and not one of them was caught, because what got checked was the
report about the file rather than the file. An order was given, an agent
reported compliance, and nobody opened the manifest. This is the check that
opens it.

Six patterns, all of them things that mean "somebody was still working here"
and none of them things a stranger should ever read:

- ``COPY PENDING`` and ``FACTS TO CONVEY``, the build's own instructions to a
  future writer. Six of these shipped on the release candidate's install
  screen.
- ``PLACEHOLDER``, the marker two sibling products were printing at users out
  of their update-check strings.
- The em dash, banned across every public surface in every language.
- A ``user_config`` entry typed anything but ``boolean``. The install screen
  is checkboxes; a free-text box is a typo waiting to break somebody's
  install, and the manifest schema has no enum type that would make one safe.
- An absolute ``C:\\Users\\`` path, which is a build that only runs on the
  machine that built it.

SCOPE. Everything in ``ENFORCED`` is clean of all six, so every hit after
this is a regression. The scope is TOTAL as of the 2026-09-09 copy fill
wave: ``README.md`` carried the update-check ``[COPY PENDING]`` block until
that wave replaced it, and ``PENDING_FILL`` is gone with it.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Text surfaces scanned today. Every one is clean at the commit that adds
#: this gate.
ENFORCED = (
    "bundle/manifest.json",
    "bundle/dev/manifest.json",
    "docs/llms.txt",
    "README.md",
)

#: The packed artifacts, which are what a human actually installs. A manifest
#: edit that was never repacked ships an install screen nobody wrote.
PACKED = (
    "bundle/kitchensink4web.mcpb",
    "bundle/dev/kitchensink4web-dev.mcpb",
)

#: (needle, what it means) for the plain-text patterns. Written as literals
#: rather than a regex so the failure message can quote the needle back.
FORBIDDEN_TEXT = (
    ("COPY PENDING", "a copy marker aimed at a future writer"),
    ("FACTS TO CONVEY", "build instructions, not product copy"),
    ("PLACEHOLDER", "an unfilled string"),
    ("\u2014", "an em dash, banned on every public surface"),
)

#: The absolute-path pattern, in both the spellings a JSON file can hold it.
HOME_PATHS = ("C:\\Users\\", "C:\\\\Users\\\\")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _packed_manifest(rel: str) -> str:
    with zipfile.ZipFile(ROOT / rel) as bundle:
        return bundle.read("manifest.json").decode("utf-8")


def _sources() -> dict[str, str]:
    out = {rel: _read(rel) for rel in ENFORCED}
    out.update({rel: _packed_manifest(rel) for rel in PACKED})
    return out


@pytest.mark.parametrize("needle,why", FORBIDDEN_TEXT)
def test_no_working_state_reaches_a_shipping_surface(needle, why):
    for where, text in _sources().items():
        assert needle not in text, (
            f"{where} carries {needle!r}: {why}. This is the pattern the "
            f"2026-09-08 audit found on the release candidate's install "
            f"screen; fix the surface, do not loosen the gate.")


def test_no_absolute_home_path_reaches_a_shipping_surface():
    """A hardcoded user directory means the artifact runs on exactly one
    machine. The first release candidate launched
    ``C:\\Users\\...\\venv\\Scripts\\web-mcp.exe`` and could not have
    installed for anybody else."""
    for where, text in _sources().items():
        for pattern in HOME_PATHS:
            assert pattern not in text, (
                f"{where} hardcodes {pattern!r}. The bundle has to launch on "
                f"a machine nobody here owns.")


def test_every_install_screen_field_is_a_checkbox():
    """No typed field, in either manifest or in either packed artifact.

    This is the rule stated as a scan rather than as a parity assertion, so
    it holds for the zip a human installs and not only for the source a test
    reads."""
    for where in ENFORCED + PACKED:
        if not where.endswith((".json", ".mcpb")):
            continue
        raw = (_packed_manifest(where) if where.endswith(".mcpb")
               else _read(where))
        config = json.loads(raw).get("user_config", {})
        typed = sorted(key for key, entry in config.items()
                       if entry.get("type") != "boolean")
        assert not typed, (
            f"{where} ships typed install-screen fields {typed}. The install "
            f"screen is checkboxes; a value a user has to spell correctly "
            f"belongs in a launch file, not on this screen.")


def test_every_enforced_surface_is_still_a_real_file():
    """A row pointing at a renamed file would quietly turn into no gate at
    all, which is how a total scope stops being total."""
    for rel in ENFORCED:
        assert (ROOT / rel).is_file(), rel
