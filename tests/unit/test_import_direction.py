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


def test_no_module_imports_playwright_yet():
    """Phase 0's gate: no browser needed yet. Playwright is an optional
    extra until Phase 1 opens, so nothing in the package may import it."""
    offenders = [
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if any(n.split(".")[0] == "playwright" for n in _module_imports(p))
    ]
    assert not offenders, f"playwright imported in Phase 0: {offenders}"
