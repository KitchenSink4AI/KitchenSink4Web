# Spike S1: the projection proof

Throwaway prototype, NOT product code. Tests whether `get_page_view` can hand a
blind agent an actionable orientation under a hard token budget.

Full report: `internal notes/20260905_ks4web_spike_s1.md`
Verdict: VALIDATED-WITH-CAVEATS.

## Files
- `extract.js`    one in-page evaluate: regions, affordances, digest, forms, tables, completeness facts
- `projector.py`  the 8 blocks, token accounting, and the 5-rung degradation ladder
- `run_spike.py`  driver: 11 live pages, Lane A bundled Chromium only, writes out/
- `ladder_test.py` re-projects cached extractions at descending budgets
- `out/*.projection.txt`  the projections
- `out/metrics.json`, `out/ladder.json`  the numbers
- `blind/`  the exact projection files handed to the blind-agent trials (frozen)

## Setup
    python -m venv .venv
    .venv/Scripts/python.exe -m pip install playwright tiktoken
    .venv/Scripts/python.exe -m playwright install chromium

## Run
    .venv/Scripts/python.exe -X utf8 run_spike.py            # all pages (live)
    .venv/Scripts/python.exe -X utf8 run_spike.py github_repo
    .venv/Scripts/python.exe -X utf8 ladder_test.py          # offline, cached

## Safety
Lane A only. Bundled Chromium, ephemeral context, no user profile, no Firefox,
nothing written outside this directory.
