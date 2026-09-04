"""Design constants that must survive Phase 1, checked while Phase 1 is still
empty.

There is exactly one of these today and it earns its own file because it is a
safety constant rather than a preference. The pattern is deliberate: a rule
that lives only in a design document gets re-derived by whoever writes the
launch path, and a rule that lives in a test does not.
"""

from __future__ import annotations

from kitchensink4web import engine


def test_firefox_launches_always_carry_no_remote():
    """S3, 2026-09-05: Playwright's BidiFirefox.defaultArgs omits -no-remote,
    so a Firefox launch can be adopted by an instance the user is already
    running regardless of which profile directory was named. An owned profile
    directory alone does not keep KS4Web out of the author's browser.

    This is a constant, not a default. If Phase 1 ever needs to remove it,
    the removal fails here first and someone has to argue for it."""
    assert "-no-remote" in engine.FIREFOX_SAFETY_ARGS


def test_the_safety_args_are_immutable_in_shape():
    """A tuple rather than a list, so no launch path can append to it and
    quietly mutate the constant for every later caller."""
    assert isinstance(engine.FIREFOX_SAFETY_ARGS, tuple)
