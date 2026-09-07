"""Fixtures for the tests that need a real browser.

Two standing safety rules bind everything in this directory and they are
enforced here rather than trusted:

- **Every Firefox launch carries `-no-remote` and a freshly created throwaway
  profile.** The author's Firefox may be open, and without `-no-remote` a
  launch can be adopted by an instance the user is already running no matter
  which profile directory was named (S3). Nothing here attaches to, enumerates,
  or otherwise disturbs a browser the user started.
- **Every session opened here is closed here**, and the session fixture fails
  the test if any owned PID outlives it. Zero orphans at exit is a property of
  the suite, not only of the gate script.

The local fixture server is `spikes/engine/fixtures_server.py`, reused rather
than rebuilt so Phase 1 sits on the same deterministic pages the engine spikes
measured against. No test in this directory touches the network.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def _load_fixture_server():
    path = ROOT / "spikes" / "engine" / "fixtures_server.py"
    spec = importlib.util.spec_from_file_location("ks4web_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _playwright_ready() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


pytestmark = pytest.mark.browser


@pytest.fixture(autouse=True)
def known_grade():
    """Every browser test starts and ends on a KNOWN read-only grade.

    The grade is process-global, and most files in this directory already
    reset it in their own `clean` fixture, which is a list rather than a rule:
    the two files that do not inherited whatever the last test to call
    `server.configure()` left behind. Under a reversed file order that put
    `test_copy_guards.py` last among the unit tests, two browser tests failed
    with `ReadOnlyMode` on nothing but their position in the run.

    The call site is fixed too, but a test's grade must not depend on which
    other tests ran first, and this is the one place that can guarantee it for
    all of them."""
    from kitchensink4web.policy import readonly

    readonly.apply(False)
    yield
    readonly.apply(False)


@pytest.fixture(scope="session")
def fixture_site():
    """The local deterministic site, started once for the whole session."""
    if not _playwright_ready():
        pytest.skip("playwright is not installed")
    server = _load_fixture_server()
    srv, base = server.start()
    yield base
    srv.shutdown()



@pytest.fixture(scope="session")
def cross_origin_site():
    """A SECOND fixture server. Same machine, different port, and a
    different port is a different origin, which is the only way to build
    the frame the audit must decline to enter and then say so."""
    if not _playwright_ready():
        pytest.skip("playwright is not installed")
    server = _load_fixture_server()
    srv, base = server.start()
    yield base
    srv.shutdown()

@pytest.fixture
def session_factory():
    """Open sessions, and prove afterward that nothing survived them.

    The teardown is the point. "We called close" is a claim; "every PID this
    session started is gone" is the property, and it is the row where the
    most-installed browser MCP server in the world is currently open."""
    if not _playwright_ready():
        pytest.skip("playwright is not installed")
    from kitchensink4web.engine import hygiene
    from kitchensink4web.engine.session import MANAGER

    opened: list = []

    async def open_one(**kwargs):
        session = await MANAGER.open(headless=True, **kwargs)
        opened.append(session)
        return session

    yield open_one

    # Closing happens INSIDE the test's own event loop, in the `run` helper
    # each test uses. A Playwright instance belongs to the loop that started
    # it, so a teardown running in a fresh loop cannot stop it, and papering
    # over that with a swallowed exception would hide the leak this fixture
    # exists to catch. What is left here is the verification.
    assert not MANAGER.sessions, (
        f"sessions survived the test: {sorted(MANAGER.sessions)}. Every test "
        f"here must close what it opens inside its own loop.")
    leaked = [pid for session in opened for pid in session.journal.pids
              if hygiene.alive(pid)]
    for pid in leaked:                      # never leave the machine dirty
        hygiene.kill(pid)
    assert not leaked, f"orphaned browser processes after teardown: {leaked}"
    for session in opened:
        assert not Path(session.profile_dir).exists(), (
            f"profile directory survived: {session.profile_dir}")
