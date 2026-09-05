# Attach spikes (S5 live attach, S6 seeded profile)

Throwaway probes, NOT product code. Run 2026-09-05 in an authorized
Firefox-closed window. Full report:
`internal notes/20260905_ks4web_spikes_s5_s6.md`

## Verdicts
- **S5 GATE PASSES.** All five commands (`session.new`,
  `browsingContext.getTree`, `browsingContext.navigate`, `script.evaluate`,
  `browsingContext.captureScreenshot` + `input.performActions` click)
  round-trip over a raw in-house BiDi client (websocket + JSON per the W3C
  spec, ~140 lines) against a stock user-style Firefox launch
  (`-no-remote -profile <seeded> --remote-debugging-port`). Lane C Firefox is
  real.
- **S6 GATE PASSES.** A logged-in session survives the seeded copy, and the
  measured minimal set for session continuity is
  `cookies.sqlite` + `-wal` + `-shm` ALONE. `key4.db`/`logins.json` are the
  saved-password store, not the session store.
- **Quirk findings:** `about:support` refuses over raw BiDi too (remote-agent
  restriction, not a Playwright artifact). `browsingContext.traverseHistory`
  works TRUTHFULLY over the raw client (163 ms, URL and DOM agree), so the S4
  go_back desync is Playwright's client-side URL tracking, not the protocol.

## Safety contract (enforced in `safety.py`, not by convention)
- The real profile is READ-ONLY SOURCE material: hashed manifest before/after
  (24,170 files, IDENTICAL), never opened by a browser, never written.
- firefox.exe-not-running gate before every copy.
- Seeded copies live in the session scratchpad, content never read except one
  sanctioned cookie-HOST-presence query against a fixed candidate list
  (booleans only), and are random-overwritten then deleted at spike end
  (verified gone).
- Every launch: `-no-remote` + the seeded profile path. Tree-kill by owned
  root PID (identified by command line naming OUR seed dir), zero-firefox
  census at end.

## Files
- `safety.py`       manifest hashing, firefox gate, secure wipe, census
- `bidi_client.py`  the thin raw BiDi client (spec-derived, no Playwright code)
- `run_s5_s6.py`    orchestrator: seed, launch, probe, login check, teardown
- `out/s5_s6_results.json`  sanitized measurements (verdicts and mechanics only)

## Windows launcher-process trap (for Phase C implementation)
`firefox.exe` is a launcher: it spawns the real browser root and exits 0, so
the Popen PID is dead within seconds. Track the browser by command line
(profile dir + `-no-remote`, excluding `-contentproc`) and tree-kill that PID.

## Run
    ../../.venv/Scripts/python.exe -X utf8 run_s5_s6.py

Uses the root venv (playwright 1.62.0 unused here; websockets 17.1 is the only
dependency). Requires the author's Firefox closed; aborts otherwise.
