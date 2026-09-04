# Engine-lane spikes (S3, S4, S7-Windows, S1 latency)

Throwaway probes, NOT product code. Full report:
`internal notes/20260905_ks4web_engine_spikes.md`

## Safety contract (enforced in `common.py`, not by convention)
- Every Firefox launch uses a **freshly created throwaway profile directory**
  (`tempfile.mkdtemp`, prefix `ks4web_spike_`) plus **`-no-remote`**. Playwright's
  own `BidiFirefox.defaultArgs` does NOT pass `-no-remote`, so `common.SAFE_FF_ARGS`
  supplies it on every launch in this directory.
- The user's real Firefox profile is never read, copied, or seeded from.
- Lane C (live attach to a user-launched browser) is **out of scope here** and
  was not run.
- Orphan sweeps clear two fences before killing anything: the PID must be absent
  from the pre-run census AND its command line must name one of our throwaway
  profile dirs.

## Files
- `common.py`             safety contract, process census, job/kill helpers
- `fixtures_server.py`    local deterministic fixtures (POST echo, download,
                          basic auth, redirect, CSS transform, locale, /hang,
                          synthetic N-node page)
- `s3_moz_firefox.py`     S3: does `channel="moz-firefox"` drive the installed Firefox
- `s3b_headed_check.py`   S3: the same, headed (Lane B dogfood mode), briefly
- `s4_bidi_gaps.py`       S4: 20-probe gap inventory, per lane (`moz-firefox|chromium|both`)
- `s4b_gap_detail.py`     S4: exact failure shapes for the two Firefox gaps found
- `s7_process_hygiene.py` S7: kill/orphan scenarios per lane + reaper mechanics
- `s7_child.py`           S7 victim process (optionally self-assigning to a job object)
- `s7b_job_context.py`    S7: rules out the ambient-job confound (CREATE_BREAKAWAY_FROM_JOB)
- `latency_probe.py`      S1's missing latency gate, on the unmodified S1 projector
- `out/*.json`            all measurements

## Run
    ../s1/.venv/Scripts/python.exe -X utf8 s3_moz_firefox.py
    ../s1/.venv/Scripts/python.exe -X utf8 s4_bidi_gaps.py both
    ../s1/.venv/Scripts/python.exe -X utf8 s7_process_hygiene.py
    ../s1/.venv/Scripts/python.exe -X utf8 s7b_job_context.py
    ../s1/.venv/Scripts/python.exe -X utf8 latency_probe.py

Reuses the S1 venv (playwright 1.62.0, tiktoken). No new installs.
