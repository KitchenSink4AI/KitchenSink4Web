"""Engine: lanes, process hygiene, and the session and page handle model.

**EMPTY IN PHASE 0, deliberately.** PLAN Phase 0's gate says "no browser
needed yet," and that is a scope statement rather than a convenience: the
architecture does not freeze until the spike gate, and writing engine code
before S2 reports would be building against an unfrozen design.

What lands in Phase 1 (PLAN 1.2):

- `lanes.py`   Lane A/B/C resolution, lazy install, lazy start, channel
               handling, and the capabilities truth table that backs
               manage_session(capabilities) and every LANE_UNSUPPORTED
               message. Seeded from spike S4.
- `hygiene.py` The three defenses: own process group plus a death-pipe
               sentinel, a startup reaper keyed on OWNED PID only, and an
               idle timeout that parks dormant pages to about:blank. This
               is the row where the most-installed browser MCP server in
               the world is currently open and unfixed (42 orphaned Chrome
               roots across 83 connections, chrome-devtools-mcp #2621), and
               the Phase 1 gate is zero orphans after 50 cycles including
               SIGKILL of the parent.
- `bidi.py`    The thin in-house WebDriver BiDi client for Lane C Firefox,
               written FROM THE W3C SPEC and not lifted from Playwright's
               bidi sources (DESIGN 10.3 rule 2, a license-futures decision
               made now because it is cheap now and expensive later).

Standing rules that bind this package from before it exists: never touch the
user's real browser profile, and never kill a browser process KS4Web did not
spawn. The owned-PID journal is authoritative and nothing is ever swept by
process name.

This package may import from `policy/`. `policy/` may not import from here.
"""

from __future__ import annotations

#: Arguments KS4Web adds to EVERY Firefox launch, on every lane, in every mode,
#: with no flag to disable them.
#:
#: Spike S3 (2026-09-05) found that Playwright's `BidiFirefox.defaultArgs`
#: builds `["--remote-debugging-port=0", "--headless"|"--foreground",
#: "--profile", <dir>]` and does NOT pass `-no-remote`, unlike its own Juggler
#: Firefox path, which does. Without it a launch can be ADOPTED BY AN INSTANCE
#: THE USER IS ALREADY RUNNING, no matter what profile directory was named. The
#: whole profile-safety rule (DESIGN 4.6) exists to keep KS4Web out of the
#: user's browser, and a fresh profile directory alone does not deliver that on
#: this lane.
#:
#: This constant lives here, in an otherwise empty Phase 0 package, precisely
#: so it cannot be forgotten when Phase 1 writes the launch path. It is not a
#: default and it is not configurable.
FIREFOX_SAFETY_ARGS: tuple[str, ...] = ("-no-remote",)
