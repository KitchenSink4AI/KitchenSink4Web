"""The open-core seam, enforced mechanically from commit one.

DESIGN 10.3 rule 3 and PLAN Phase 0: `policy/` is a separate package from
`engine/` and `ops/`, with a ONE-DIRECTION dependency. ops and engine depend
on policy; policy depends on neither, ever.

The reason this is a test rather than a convention: the license decision is
deferred (DESIGN 10), and if open-core is ever chosen, the boundary has to
be architectural rather than retrofitted. A seam is cheap to keep and
expensive to add later, so it is checked on every run whether or not it is
ever used.

The check is static (AST over the source), not import-time, because an
import that only happens inside a function body would pass a runtime probe
and still couple the packages.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "kitchensink4web"
FORBIDDEN_FOR_POLICY = ("ops", "engine")


def _module_imports(path: Path) -> list[str]:
    """Every module name this file imports, absolute and relative alike,
    with relative imports resolved against the package root."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parts = path.relative_to(SRC).with_suffix("").parts
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # depth 1 = this module's package, 2 = its parent, ...
                base = list(parts[: max(0, len(parts) - node.level)])
                target = base + ([node.module] if node.module else [])
                names.append(".".join(["kitchensink4web", *target]))
            elif node.module:
                names.append(node.module)
    return names


def _files(subpackage: str) -> list[Path]:
    return sorted((SRC / subpackage).rglob("*.py"))


def test_the_three_packages_exist():
    for name in ("policy", "engine", "ops"):
        assert (SRC / name / "__init__.py").is_file(), \
            f"{name}/ is missing; the open-core seam is not in place"


def test_policy_imports_neither_ops_nor_engine():
    offenders: list[str] = []
    for path in _files("policy"):
        for name in _module_imports(path):
            tail = name.replace("kitchensink4web.", "")
            head = tail.split(".")[0]
            if head in FORBIDDEN_FOR_POLICY:
                offenders.append(f"{path.name} imports {name}")
    assert not offenders, (
        "policy/ must not depend on ops/ or engine/ (DESIGN 10.3 rule 3): "
        + "; ".join(offenders)
    )


def test_policy_never_imports_site_profiles():
    """PROF-3, bought mechanically rather than by review.

    A site profile is third-party data. The closed list of what it may
    influence is advisory blocks, default extraction hints, workflow names,
    and one lane-seed handoff at load. It may not influence a refusal code,
    a gate decision, a budget, an origin decision, the read-only grade, the
    redaction vault, the wall verdict, or the audit trail. One assertion
    that no policy module can even see the loader buys the whole of it."""
    offenders: list[str] = []
    for path in _files("policy"):
        for name in _module_imports(path):
            tail = name.replace("kitchensink4web.", "")
            if tail.split(".")[0] == "profiles":
                offenders.append(f"{path.name} imports {name}")
    assert not offenders, (
        "policy/ must not depend on profiles (PROF-3): a profile annotates "
        "and can never reach a verdict: " + "; ".join(offenders)
    )


def test_the_direction_is_actually_exercised():
    """A one-direction rule nobody uses is not a seam, it is an empty
    folder. At least one module outside policy/ must depend on it, or this
    test is passing vacuously."""
    users = []
    for sub in ("ops", "engine"):
        for path in _files(sub):
            if any("policy" in n for n in _module_imports(path)):
                users.append(path.name)
    server = SRC / "server.py"
    if any("policy" in n for n in _module_imports(server)):
        users.append("server.py")
    assert users, "nothing depends on policy/, so the seam is untested"


def test_playwright_is_confined_to_the_engine():
    """Phase 1's version of the Phase 0 rule, and a stronger one.

    The driver is the engine's business. `projection/` takes a page-like
    object with an `evaluate` method and never imports playwright, which is
    what keeps it testable against a recorded extraction; `ops/` goes through
    the session manager; `policy/` touches neither. A tool reaching for the
    driver directly is how a lane gap becomes a silent pass-through."""
    offenders = [
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if any(n.split(".")[0] == "playwright" for n in _module_imports(p))
        and p.parent.name != "engine"
    ]
    assert not offenders, (
        f"playwright imported outside engine/: {offenders}. The driver is the "
        f"engine's business; everything else goes through the session manager."
    )


def test_projection_does_not_import_the_engine():
    """The projection is a pure function of an extraction plus a budget.

    That is what lets the ladder, the quotas, the prices, and the completeness
    accounting be tested against a recorded page with no browser running, and
    a projection that reached into the engine would lose it."""
    offenders = []
    for path in _files("projection"):
        for name in _module_imports(path):
            head = name.replace("kitchensink4web.", "").split(".")[0]
            if head in ("engine", "ops"):
                offenders.append(f"{path.name} imports {name}")
    assert not offenders, "; ".join(offenders)


def test_importing_the_package_does_not_start_the_driver():
    """Lazy install is also lazy start (DESIGN 4.1), and codex #21984 names
    eager startup of GUI-capable MCP tools as the root cause of the worst leak
    reports. A server nobody asks to browse must not spawn a Node driver, so
    playwright is imported inside functions rather than at module scope.

    Checked in a FRESH interpreter, because a browser test earlier in the same
    session would leave playwright in sys.modules and make an in-process
    assertion pass for the wrong reason."""
    import subprocess
    import sys

    probe = (
        "import sys;"
        "from kitchensink4web import server;"
        "server.configure();"
        "print('playwright' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-X", "utf8", "-c", probe],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip().endswith("False"), (
        "importing the package and registering the surface imported "
        "playwright, so the driver is no longer lazy")
