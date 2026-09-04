# S2: anchor durability

Prototype of DESIGN 3.5's two-address scheme (turn-local `ref`, durable
content-derived `anchor`) and the rebind ladder, measured against real React
and real react-window.

```
.venv/Scripts/python.exe -X utf8 spikes/s2/run_s2.py
```

Report: `internal notes/20260905_ks4web_spike_s2.md`.
Raw results: `out/s2.json`.

## What is here

| file | what it is |
|---|---|
| `anchor_extract.js` | the in-page pass: role, accessible name, scoping path, stable attributes, page key, plus two instruments |
| `anchors.py` | the key ladder, the sticky element map, the rebind ladder, and DESIGN 3.5's five entry conditions |
| `run_s2.py` | thirteen scenarios across two tuning knobs, plus the entry-condition probes |
| `fixtures/app.html` | a React SPA: node-replacing remount, label change, list reorder, hash routing, duplicate control names, a modal |
| `fixtures/virtual.html` | a react-window `FixedSizeList`, 20 rendered of 5,000 |
| `fixtures/other.html` | a different page carrying the same landmarks and the same control names |
| `fixtures/vendor/` | React 18.3.1 and react-window 1.8.10 UMD builds, vendored so there is no build step and no network at run time |

## The two instruments, and why they are marked as instruments

Every interactive element in the fixtures carries `data-truth`, a stable
semantic identity the fixture preserves across every mutation. **The anchor
scheme never reads it**, enforced by `anchors.assert_no_instruments()`, because
a scheme that fingerprinted ground truth would score a perfect run and mean
nothing. It exists so the harness can say whether a rebind landed on the right
element, which is the only way "correct" is measurable here.

`node_uid` is a serial handed out from a `WeakMap` that outlives the evaluate.
It answers "did this DOM node survive" as distinct from "did this element
survive", which is the exact distinction a React re-render destroys and the one
a `backendNodeId`-style scheme depends on. On the remount scenario 22.7 percent
of nodes survive and 100 percent of distinguishable elements keep their refs,
which is the whole argument for content fingerprints in one pair of numbers.

## The two knobs the run sweeps

**`weak_keys`** turns the two ordinal rungs of the key ladder on or off. On,
they are the sole source of every false identity in the run: 44 cases, all on
the virtualized list, where a recycled node put row 0's ref onto row 3,998.

**`fuzzy`** turns the ladder's name-only tier on or off. It changed no
resolution's correctness anywhere in the run. It only converted eight
`STALE_ANCHOR` refusals into eight `AMBIGUOUS_LOCATION` refusals.
