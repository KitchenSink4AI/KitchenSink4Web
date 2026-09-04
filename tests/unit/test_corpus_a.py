"""Corpus A is frozen, and this test is what "frozen" means mechanically.

PLAN 1.3 requires the four MEASURED benchmark pages captured to disk with the
fetch date and page revision recorded, so every published KS4Web number
re-derives after the live pages change. A snapshot nobody checks is a snapshot
that silently rots: an editor re-runs the capture, the bytes move, and the
published benchmark quietly starts describing a different page under the same
name.

So the manifest's sha256 is verified against the file on every run. The test
fails loudly if either side moves without the other, which makes a re-freeze a
deliberate act with a visible diff rather than an accident.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus" / "a"

#: PLAN 1.3, transcribed. The set is fixed because MEASURED used exactly these
#: four and the whole point of corpus A is comparability with that baseline.
REQUIRED = {"wikipedia_versailles", "wikipedia_gdp_table", "httpbin_form",
            "example_com"}


def _manifest() -> dict:
    return json.loads((CORPUS / "MANIFEST.json").read_text(encoding="utf-8"))


def test_the_four_measured_pages_are_frozen():
    assert (CORPUS / "MANIFEST.json").is_file(), (
        "corpus A is not frozen; run scripts/freeze_corpus_a.py")
    assert set(_manifest()["pages"]) == REQUIRED


def test_every_frozen_page_matches_its_recorded_digest():
    """The manifest and the bytes are one artifact or they are neither."""
    for name, entry in _manifest()["pages"].items():
        path = ROOT / entry["file"]
        assert path.is_file(), f"{entry['file']} is missing"
        digest = hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        assert digest == entry["sha256"], (
            f"{name} has changed since it was frozen. A re-freeze is fine and "
            f"is a decision: re-run scripts/freeze_corpus_a.py, re-run "
            f"scripts/measure_corpus_a.py, and update DESIGN 3.2, because "
            f"every published number comes from these bytes.")


def test_the_manifest_records_what_a_reader_needs_to_reproduce_it():
    manifest = _manifest()
    assert manifest["fetched_kst"], "no fetch date recorded"
    for name, entry in manifest["pages"].items():
        assert entry["url"] and entry["final_url"]
        assert entry["bytes"] > 0
        # A revision id where the publisher exposes one, and an explicit
        # statement of what stands in for it where nobody does. Silence about
        # provenance is the thing this field exists to prevent.
        assert entry["revision"] or entry["revision_source"]


def test_the_frozen_pages_carry_no_script():
    """A page that rehydrates is not frozen.

    Scripts are stripped at capture, and the reason is reproducibility rather
    than caution: a page that mutates after load makes the benchmark
    irreproducible in exactly the way freezing was supposed to fix."""
    for entry in _manifest()["pages"].values():
        html = (ROOT / entry["file"]).read_text(encoding="utf-8")
        assert "<script" not in html.lower(), (
            f"{entry['file']} still carries script")
