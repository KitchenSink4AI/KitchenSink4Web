# MERGE NOTES — branch `build/senses` (features #9, #16, #17)

Base: `45fc986`. Three commits, nothing pushed.

## Files this branch touches that other parallel branches are likely to touch too

| File | What changed here | Conflict risk |
|---|---|---|
| `src/kitchensink4web/packs.py` | added the `accessibility` pack (`PACK_SUMMARIES` + `PLANNED_MEMBERS`); added `read_image_text` to the `capture` roster and reworded the capture summary | **HIGH.** Every builder adding a tool edits these two dicts. Both are plain dict entries; take both sides. |
| `src/kitchensink4web/server.py` | added `profiles` to the import line, the `load_profiles()` call in `configure()`, `"profiles"` in the returned dict, the startup line, and `"accessibility": ".ops.a11y"` in `_PACK_MODULES` | **HIGH**, same reason. All additive. |
| `src/kitchensink4web/policy/readonly.py` | `read_image_text` and `get_accessibility` added to `NON_MUTATING`; `get_accessibility` added to `GENUINELY_READ_ONLY` | **HIGH**, additive set entries. |
| `src/kitchensink4web/ops/lite.py` | `_profile_block()` helper + one line in `navigate`'s return; `manage_session(action='profiles')`; two `get_workflows` topics (`profiles`, `accessibility`); two docstring sentences | **MEDIUM.** `manage_session`'s action tuple and the `get_workflows` recipe dict are shared surfaces. |
| `src/kitchensink4web/ops/extract.py` | `extract_fields(fields=...)` is now optional and falls back to a matching profile; `accounting.schema_source` added | LOW unless another wave touched `extract_fields`. |
| `src/kitchensink4web/ops/capture.py` | substantially reworked: pixel cap, `target="region"`, `pad_px`, `read_image_text` | LOW; nobody else was in this module. |
| `src/kitchensink4web/ops/common.py` | added `image_dimensions()` beside `sniff_image()` | LOW, one new function. |
| `src/kitchensink4web/projection/render.py` | the canvas completeness line grew a capability clause and an image-borne-text clause; `_ocr` import | **MEDIUM.** The completeness block is metered, so a second wave adding a line there needs to re-measure (see the rung note below). |
| `src/kitchensink4web/projection/extract.js` | collects `mute_images` (laid-out `<img>`, >=200x80, no alt/aria-label/aria-labelledby/title) and reports it in `completeness` | LOW, one new collector. |
| `spikes/engine/fixtures_server.py` | two clearly-marked route blocks (`# --- senses wave fixtures`, `# --- accessibility fixtures`) plus their page constants | **MEDIUM.** Every wave adds routes to the same `do_GET`. The blocks are contiguous; take both sides. |
| `tests/browser/conftest.py` | new session-scoped `cross_origin_site` fixture (a second fixture server = a second origin) | LOW. Useful to other waves; keep it. |
| `pyproject.toml` | `profile_data/*.json` in package-data; two optional extras (`ocr`, `accessibility`) | LOW. |
| `DEPENDENCY_LEDGER.md` | six new optional-extra rows, the Tesseract decision, the axe license/currency finding, and the expired-rationale correction | LOW. |
| `bundle/manifest.json`, `bundle/dev/manifest.json`, `README.md` | the `accessibility` pack checkbox and its README row | LOW, but see the COPY FLAG below. |

## Pins another branch will hit

- **`tests/unit/test_packs_phase5.py` tool count: 45 -> 47** (46 for `read_image_text`, 47 for `get_accessibility`). Two assertions, both in `test_full_surface_is_forty_seven_tools`. Any other branch adding a tool must add its own delta on top; do not take one side.
- **`tests/browser/test_shadow_traversal.py::test_a_shadow_free_page_pays_nothing_for_the_traversal`: 4500/rung 6 -> 4311/rung 7.** See the rung note below. If another wave also changes the completeness block, re-measure rather than merging either number.
- **`tests/browser/test_phase2_reads.py::test_a_page_view_can_be_scoped_to_a_region_and_costs_less`** now scopes to the CHEAPEST priced region rather than the first one listed. The old form measured which region happened to print first, which is rung-dependent; the new form measures what the test's name claims. Keep the new form.

## The rung note, which is the one judgment call worth a second opinion

The Wikipedia corpus page used by two pins was sitting EXACTLY on its budget
ceiling (4,500 used against a 5,000 budget less the 500-token margin). It had
zero headroom, so the one clause this wave added to the completeness block —
naming the twelve images on that page that contribute no text to any read —
pushed it down one rung of the projection ladder.

Nothing is silent about it: the rung is in the payload, the totals are intact,
and the clause was cut to the shortest honest form (a count, no criteria
prose, and a capability clause under 80 characters). But it is a real trade,
it is the first time a completeness addition has cost that page a rung, and
the author may prefer the rung back. Reversing it is one edit: drop the
`mute_clause` from `render.py` and the `mute_images` collector from
`extract.js`. The OCR capability clause on the canvas line is free on pages
without canvases and is not part of the trade.

## Assumptions about the dream-smartlanes branch (we did not import each other)

`profiles.py` calls one optional function behind a capability check:

```python
def _smartlanes():
    from . import lanestore          # ImportError -> None
    return lanestore if hasattr(lanestore, "seed_observations") else None
```

- The module is assumed to be `src/kitchensink4web/lanestore.py`. If smartlanes
  named it something else, change the one import in `profiles._smartlanes`.
- The function is assumed to be
  `seed_observations(rows: list[dict], *, origin: str) -> int`, with rows shaped
  `{"host", "lane", "outcome", "observed", "wall"}` and `origin="profile:<slug>"`.
- Seeds are expected to enter at the store's LOWEST precedence tier and never
  overwrite an observation it learned itself.
- If smartlanes ships its own seed file instead, nothing here moves: `lane_seed`
  is validated, dropped, and the profile loads unchanged. `test_p16_49` covers
  both the present and the absent case.
- **`Profile` deliberately exposes no lane accessor at all** and `test_p16_50`
  asserts it, so a lane question cannot be answered from a profile even by
  accident. Do not add one when wiring the two together.

## COPY FLAG — needs a human, not an agent

`bundle/manifest.json`, `bundle/dev/manifest.json`, and the README pack table
now carry a sentence for the accessibility checkbox. It is a plain factual
placeholder written only so the parity test is not left red. Install-screen
wording and README rows are user-facing product copy, which agents do not
write. The current sentence is:

> Checks a page against the WCAG accessibility rules using axe-core, groups
> what it finds by rule, and says plainly what automated testing cannot check.

Rewrite it in all three places together; the parity test asserts the README
quotes the manifest verbatim.

## Two things the specs asked for that are NOT here, and why

- **No starter profile pack.** The spec proposed eight shipped profiles; the
  author ruling was format plus docs plus ONE clearly-labeled example. One
  ships, matching `example.com`, and `test_p16_48b` asserts the directory
  holds exactly one file whose hosts end in the reserved documentation domain.
  That pin is the doctrine, so deleting it is the decision to grow a registry.
- **No `engine="native"` fallback for the audit.** The spec kept one behind a
  parameter in case vendoring was refused. The author ruled the engine in as a
  dependency, so the fallback has no trigger and a parameter with one legal
  value is a schema that lies. A missing extra refuses by name instead.
