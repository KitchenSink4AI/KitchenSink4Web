# Corpus B: the pathological fixture site

Every landmine PLAN 1.3 names, deliberately, served from the repo. Synthetic,
no real user data, no live third-party site, no framework build step, and no
network at run time. React 18.3.1 and react-window 1.8.10 are vendored as UMD
builds in `vendor/`. The two `https://example.com` iframes fail to load
offline and that is the intended behaviour: the iframe element is the fixture,
not its content.

| File | What it is for | Nodes |
|---|---|---|
| `dom50k.html` | 50,000 elements of ordinary document, so the degradation rungs and the latency ladder have a page that reaches them | 50,000 |
| `infinite.html` | an infinite-scroll feed that appends 25 more items every time the sentinel is seen, so there is no bottom to find | 112 at load |
| `virtual.html` | a real react-window `FixedSizeList` rendering 20 of 5,000 rows, so node RECYCLING breaks positional identity | 59 |
| `app.html` | a React SPA: node-replacing remount, label change, list reorder, hash routing, two identically named controls in one region, a modal | 54 |
| `other.html` | the look-alike page for the cross-navigation rebind trap | 20 |
| `canvas.html` | a 900x520 canvas painting a whole toolbar and chart, with no text in the DOM to project | 11 |
| `iframes.html` | top of the frame chain, plus a cross-origin frame at the top level | 16 |
| `iframe_l2.html` | level 2, same origin, carrying its own controls | 12 |
| `iframe_l3.html` | level 3, and the cross-origin frame at the bottom of the chain | 10 |
| `shadow.html` | two open shadow roots and three closed ones, one closed root nested inside an open one | 15 light DOM |
| `cookiewall.html` | a consent notice and a subscribe modal stacked over an ordinary article, both above it in the DOM and on screen | 28 |
| `mutating.html` | text, labels, list order, and one whole button node replaced every 100ms | 37 |
| `tables.html` | a rowspan/colspan table, a `role=table` of divs, a `role=grid` of divs, and a layout table that carries no data | 97 |
| `lazy.html` | five lazy images across three placeholder techniques, plus two more below a tall spacer | 39 |
| `pathological.html` | five ways a click reports success and does nothing: an `isTrusted` check, a `<div onclick>`, a click-intercepting overlay, a target animating under the cursor, and a portal-rendered dropdown | 42 |
| `console_flood.html` | 4,000 console lines before load and 40 more per second, with two real errors buried in them | 12 |
| `secrets.html` | a checkout form with populated password, one-time-code, and `cc-number` fields, plus a token field outside the form | 49 |
| `loose_controls.html` | an app shell with 19 controls outside any `<form>` and a 6-control form for contrast (Phase 2 gate) | 163 |
| `bigform.html` | 320 fields in one form, submit button last, secrets past field 240 (Phase 2 gate, rung-5 capped inventory) | 758 |

## Tooling

| File | Purpose |
|---|---|
| `_generate.py` | writes `dom50k.html` and `bigform.html`. The generator emits the file and the FILE is committed, so the node count is a property of the bytes on disk rather than of how fast the machine ran. No inline script builds nodes. |
| `_check.py` | serves the directory over localhost with the bundled Chromium, loads every page, prints node and control counts plus any page or console error. `--manifest` rewrites `MANIFEST.json` with MEASURED counts. Exit 0 means every page loaded. |
| `MANIFEST.json` | file to landmines, plus measured counts, sha256, and an inverted `landmine_index`. |

## Provenance

`app.html`, `other.html`, `virtual.html`, and `vendor/` were **copied** from
`spikes/s2/fixtures/`, per PLAN 1.3's note that the S2 subset moves into
corpus B proper before Phase 2 closes. They were copied rather than moved so
`spikes/s2` still runs and the spike record stays reproducible.

## Ground truth

Three pages set `window.__truth` with counts a human wrote down:
`shadow.html` (2 open roots, 3 closed, 1 closed nested in an open one),
`loose_controls.html` (19 loose controls, 6 form controls), and the S2 pages'
`data-truth` attributes. **The projection must never read any of them.** They
exist so a harness can score an answer as right or wrong; a scheme that peeked
would score perfectly and mean nothing.
