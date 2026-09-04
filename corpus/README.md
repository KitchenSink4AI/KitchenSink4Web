# The corpus

Three fixture sets, per PLAN 1.3, and none of them is optional.

## A: the frozen benchmark set (`corpus/a/`)

The four pages the banked MEASURED baseline used, captured once and committed,
so every published KS4Web token number is reproducible after the live pages
change. `MANIFEST.json` records the fetch DTG in KST, the final URL, the
MediaWiki revision id where the publisher exposes one, a sha256 per file, and
what the capture strips. `tests/unit/test_corpus_a.py` verifies the digests, so
a re-freeze is a deliberate act with a visible diff rather than a drift.

| file | page | nodes at capture |
|---|---|---|
| `wikipedia_versailles.html` | Treaty of Versailles | 10,744 |
| `wikipedia_gdp_table.html` | List of countries by GDP (nominal) | 5,651 |
| `httpbin_form.html` | httpbin.org/forms/post | 46 |
| `example_com.html` | example.com | 12 |

**What "frozen" means here.** A single `outerHTML` dump is not frozen: it loses
every stylesheet, and visibility on the web is a CSS property, so a projection
run against that dump would compute different hidden-content answers than the
live page did. The capture serializes the post-load DOM, inlines every
stylesheet in document order with external sheets fetched through the browser's
own request context, and strips `<script>` and `<noscript>` because a page that
rehydrates or mutates after load is irreproducible in the way freezing was
supposed to fix.

**No `<base>` tag is injected, deliberately.** Wikipedia's internal links are
root-relative, so a page served from localhost still matches origin and still
prints paths rather than full URLs, which is what keeps the token count
comparable to a live read. A base pointing at the live origin would make every
internal link cross-origin and inflate the number this corpus exists to fix.

### Rebuilding and measuring

```
.venv/Scripts/python.exe -X utf8 scripts/freeze_corpus_a.py
.venv/Scripts/python.exe -X utf8 scripts/measure_corpus_a.py --live
```

The freeze needs the network. The measurement does not: the frozen pages are
served over localhost with every off-origin request aborted, so the run is
hermetic. `--live` adds the drift check PLAN 1.3 asks for, which re-measures
the live pages and reports the gap. The drift check is never the benchmark. Its
only job is to answer whether the frozen copy still tells the truth about the
real page.

Results land in `gates/corpus_a.json`, with the rendered projections in
`corpus/a/out/` so a reviewer can read what the numbers describe. DESIGN 3.2
publishes from that file.

## B: the pathological fixture site

The Phase 1 slice lives in `tests/fixtures/pages.py` (five hand-written pages,
one per failure class) with recorded extractions in `tests/data/`. The rest,
including the S2 anchor fixtures, lands before Phase 2 closes.

## C: the adversarial safety fixture

Due before Phase 3, whose gate is corpus C driven end to end. Synthetic, never
networked.
