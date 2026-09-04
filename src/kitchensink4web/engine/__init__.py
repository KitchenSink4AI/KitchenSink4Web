"""Engine: lanes, process hygiene, and the session and page handle model.

**Built in Phase 1.** Three modules exist and one is still deferred:

- `lanes.py`   Lane A/B resolution, lazy install, lazy start, channel
               handling, and the capabilities truth table that backs
               manage_session(capabilities) and every LANE_UNSUPPORTED
               message. Seeded from spike S4's measured table.
- `hygiene.py` The three defenses: a kill-on-close job object alongside
               Playwright's death pipe, a startup reaper keyed on OWNED PID
               only, and the CPU accounting behind the idle park. This is
               the row where the most-installed browser MCP server in the
               world is currently open and unfixed (42 orphaned Chrome roots
               across 83 connections, chrome-devtools-mcp #2621).
- `session.py` The session and page handle model the 2026-07-28 spec asks
               for, one Playwright instance across tool calls, the asyncio
               lock, the bounded per-operation timeout, and the idle park.
- `bidi.py`    NOT BUILT. The thin in-house WebDriver BiDi client for Lane C
               Firefox, to be written FROM THE W3C SPEC and not lifted from
               Playwright's bidi sources (DESIGN 10.3 rule 2). Lane C waits
               on S5 and S6, which are deferred by a standing safety rule
               rather than by a finding, so the lane refuses rather than
               pretending and no public copy may claim it.

Standing rules that bind this package: never touch the user's real browser
profile, and never kill a browser process KS4Web did not spawn. The owned-PID
journal is authoritative and nothing is ever swept by process name.

This package may import from `policy/` and from `projection/`. `policy/` may
import from neither.
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
