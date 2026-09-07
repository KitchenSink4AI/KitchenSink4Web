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
    from kitchensink4web.policy import audit, budgets, consent, gates, readonly

    readonly.apply(False)
    _known_consent(consent)
    _known_audit(audit)
    _known_gates(gates)
    _known_backoff(budgets)
    yield
    readonly.apply(False)
    _known_consent(consent)
    _known_audit(audit)
    _known_gates(gates)
    _known_backoff(budgets)


def _known_audit(audit) -> None:
    """THE THIRD AXIS, and the one that could not clean up after itself.

    `audit._annotations` is a ContextVar holding a plain dict. `annotate()`
    reads it and, when a dict is already there, MUTATES THAT DICT IN PLACE
    rather than setting a new one. `_drain_annotations()` reads it and calls
    `set(None)`. A `set()` inside a task writes the TASK's copy of the
    context, so a dict that reached the THREAD-level context is drained for
    the current task and stays put for the next one, with every key ever
    written into it still on board: drain returns the dict, it never empties
    it.

    That is a one-way valve between the two kinds of test in this repo.
    Synchronous code (the unit suite) runs in the thread's own context, so
    its `set(None)` really does clear. Async code (every test here, through
    `asyncio.run`) can only ever ADD to what the thread level holds. So one
    synchronous `annotate` in the unit suite that is not followed by a
    synchronous `record` seeds a dict at thread level, and from then on
    every browser test in the process writes its annotations into that same
    dict and none of them can take them back out.

    The 2026-09-08 repro, three tests long and deterministic:

        tests/unit/test_consent_ladder.py::test_n26_a_cleared_action_still_aborts_on_a_rebind
        tests/browser/test_workflow_templates_live.py::test_a_workflow_recorded_from_a_batch_can_be_parameterized
        tests/browser/test_phase8_gauntlet_fixes.py::test_c1_workflow_replay_inherits_the_gate

    The unit test seeds the dict. The batch test writes `replay_steps` (the
    two-step list a composite records) into it. The gauntlet pin then calls
    `LOG.record` for its own single click, the drain hands it the shared
    dict, and `_replay_blocks` prefers the stale list: the pin saved a
    TWO-step workflow beginning with a `type_text` into a "Your name" box
    that exists only on `tests/fixtures/workflow_site.html`. That step
    failed `ValidationFailed` against the C1 forms page and the gated click
    the pin exists to check was never attempted. Every browser-only prefix
    passes, which is why it took a full-suite order to surface.

    The reset is the same shape as the two above it, and for the same
    reason: no test's verdict may depend on which other tests ran first.
    The dict is emptied as well as unset, so a task still holding the old
    reference cannot resurrect it.

    `LOG` gets the same treatment. Most files here already build a fresh
    `AuditLog()` in their own `clean` fixture, which is a list rather than a
    rule; the ring is process-global for the ones that do not."""
    pending = audit._annotations.get()
    if isinstance(pending, dict):
        pending.clear()
    audit._annotations.set(None)
    audit.LOG.reset()


def _known_gates(gates) -> None:
    """The gate engine's pending table and the deposited-grant slot.

    Swept out with the audit annotations because they are the same shape:
    process-global (`ENGINE._pending`) or context-local (`_deposited`)
    state that a test writes and no fixture in this directory takes back.
    A run of the C1 matrix leaves three unredeemed gates in the table and
    the next file inherits them; only `tests/unit/test_confirm_wiring.py`
    ever clears it, which is a list rather than a rule.

    `_deposited` is `set()`-only, so a deposit made inside a test's task
    cannot climb back to the thread. The reset is here for the case the
    annotations dict already proved possible: a deposit made from
    synchronous code would sit at thread level and every later test would
    start holding a grant it never asked for."""
    gates.ENGINE._pending.clear()
    gates.clear_grant()


def _known_backoff(budgets) -> None:
    """Every domain here is 127.0.0.1, which makes the backoff table one
    shared key.

    `BOOK._backoff` holds the window a 429 or 503 opened and
    `BOOK._backoff_why` holds the status that opened it, keyed by domain
    and carried separately. `test_monitor_live.py` clears the first in its
    own fixture and not the second, so a 503 recorded there is still the
    answer `backoff_reason()` gives about 127.0.0.1 in every file that runs
    afterwards, long after the window it described expired.

    Every `_backoff*` mapping is swept rather than the two by name. Naming
    them made this fixture the thing that broke against a tree where
    `_backoff_why` did not exist yet, and an AttributeError raised in here
    fails every browser test in the run, which is a spectacular way for a
    cleanup step to behave. The sweep also picks up the next sibling
    somebody adds alongside them."""
    for name, value in vars(budgets.BOOK).items():
        if name.startswith("_backoff") and hasattr(value, "clear"):
            value.clear()


def _known_consent(consent) -> None:
    """AXIS B GETS THE SAME TREATMENT AXIS A ALREADY HAD, and for the
    same reason: a test's verdict must not depend on which other tests
    ran first. The state set here is the one a FRESH PROCESS has, which
    is the state every pin in this directory was written against.

    Found by the seven-branch integration's seeded-random gate on
    2026-09-08. `consent.apply()` is startup-only and process-global, so
    any file that calls it (the consent wave's own two live files do, in
    their `clean` fixture) leaves Axis B ACTIVE for everything that runs
    afterwards. Nine older submit-gate pins then fail, because the
    consent ladder deliberately rules a query-shaped GET submission
    Tier 0 and their fixtures are `method="get"` forms. Forward order
    hid it; a shuffle did not.

    THIS RESETS, IT DOES NOT DECIDE. Two pins contradict each other on
    the same page shape -- `test_a_get_search_form_submits_with_zero_gates_on_every_path`
    says a GET search form submits ungated, and the C1 matrix says a GET
    form's submit button gates -- and which one describes the shipped
    product is the author's call, not a merge resolution. It is written
    up in the integration report. Until it is ruled on, every test here
    starts from the same known Axis-B state and every assertion stands
    exactly as its author wrote it."""
    consent._reset_runtime_state()
    consent._scope = None
    consent._source = "test harness: a known Axis-B state per test"


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
    # EVERY jar, not just the focused one. A session can hold more than one
    # cookie jar and therefore more than one browser process, and a
    # teardown check that only asked the focused jar would miss exactly the
    # leak this fixture exists to catch.
    leaked = [pid for session in opened
              for jar in session.contexts.values()
              for pid in jar.journal.pids if hygiene.alive(pid)]
    for pid in leaked:                      # never leave the machine dirty
        hygiene.kill(pid)
    assert not leaked, f"orphaned browser processes after teardown: {leaked}"
    for session in opened:
        for jar in session.contexts.values():
            assert not Path(jar.profile_dir).exists(), (
                f"profile directory survived: {jar.profile_dir}")
