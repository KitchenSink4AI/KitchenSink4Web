"""Shared fixtures.

Every test that inspects the registered surface needs a KNOWN launch shape,
because registration is launch-time and therefore process-global. `launch`
tears the surface down, applies the shape asked for, and hands back the
resulting state, then restores the default lite surface afterward so a test
that never calls it still sees something sane.

`live_tools` returns the tool objects FastMCP actually holds, which is the
only honest source for any count or cost: the pack registry tracks membership
by name and deliberately keeps no second copy of the objects.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web import server


@pytest.fixture(autouse=True)
def _no_grade_leak():
    """A test may not change the process read-only grade and walk away.

    The grade is launch-time and therefore process-global, and several
    behaviours read it silently rather than refusing on it: the lane
    database, for one, returns `read` instead of `learn` under a read-only
    grade and records nothing. A test that leaves the grade armed does not
    fail itself, it fails whatever the shuffle runs next, which is why this
    is caught here instead of in a review.

    `pytest-randomly` reorders every run, so a leak like this is a lottery
    rather than a stable red. One did ship: `test_p16_28` cleared the grade
    and then re-armed it with a bare `configure()`, and six lane tests went
    red on any seed that put `test_profiles` before `test_lane_wiring`.
    """
    from kitchensink4web.policy import readonly
    before = readonly.grade()
    yield
    after = readonly.grade()
    if after != before:
        readonly.apply(False if before is None else before)
        pytest.fail(
            f"this test left the process read-only grade at {after!r}, "
            f"where it found {before!r}. The grade is process-global, so "
            f"the cost lands on whatever runs next. Restore it explicitly: "
            f"a bare server.configure() re-resolves the SHIPPED default "
            f"grade rather than clearing it, so pass read_only=False.")


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    """No test touches the network. The update check is switched off for the
    whole suite; its own tests delenv this and drive the fetch through a
    monkeypatched urlopen. BOTH spellings are set: the current toggle and
    the superseded opt-out, so this fixture holds whichever a future edit
    leaves in force."""
    monkeypatch.setenv("KS4WEB_UPDATE_CHECK", "off")
    monkeypatch.setenv("KS4WEB_NO_UPDATE_CHECK", "1")


@pytest.fixture
def launch(monkeypatch):
    """Configure the server under a named launch shape and return the state.

    Usage:  state = launch()
            state = launch(read_only="browse")
            state = launch(cli_packs=["extract"])
    """
    monkeypatch.delenv("KS4WEB_MODE", raising=False)
    monkeypatch.delenv("KS4WEB_READ_ONLY", raising=False)
    monkeypatch.delenv("KS4WEB_ALLOW_ACTING", raising=False)
    monkeypatch.delenv("KS4WEB_ALL_PACKS", raising=False)
    # Axis B is launch-time too (consent ladder, 2026-09-07), and it is
    # process-global for exactly the reason the grade is, so a test that
    # inspects the surface needs a known consent shape as much as it needs a
    # known grade. A stray KS4WEB_PREAUTH in the developer's environment
    # would otherwise clear gates in tests that exist to prove they fire.
    for _consent_env in ("KS4WEB_CONSENT", "KS4WEB_PREAUTH",
                         "KS4WEB_SENSITIVE_ORIGINS", "KS4WEB_REMEMBER",
                         "KS4WEB_CREDENTIAL_INJECTION"):
        monkeypatch.delenv(_consent_env, raising=False)
    for _name in [k for k in list(__import__("os").environ)
                  if k.startswith("KS4WEB_SECRET_")]:
        monkeypatch.delenv(_name, raising=False)
    for _pack in ("EXTRACT", "CAPTURE", "NETWORK", "STORAGE", "FILES",
                  "DIAGNOSTICS", "WORKFLOWS"):
        monkeypatch.delenv(f"KS4WEB_PACK_{_pack}", raising=False)

    yield server.configure

    # `read_only=False` and not a bare `configure()`. A bare call resolves the
    # SHIPPED default grade, `browse`, so every test that used this fixture
    # left the process read-only for whatever ran next, and a browser test
    # that asserts the process is actable failed purely on file order
    # (`pytest tests/unit tests/browser` red, `pytest tests` green). A fresh
    # process starts with no grade applied at all, so the honest restore is
    # the un-graded surface this fixture found, not the launch default.
    server.configure(read_only=False)


@pytest.fixture
def live_tools():
    """{name: Tool} as FastMCP currently holds them."""

    def _get():
        return {t.name: t for t in asyncio.run(server.mcp.list_tools())}

    return _get
