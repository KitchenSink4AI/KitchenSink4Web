"""The matcher, the registration, and the shared-source discipline for
`extract_page` and `aggregate`.

The LIVE half is `tests/browser/test_extract_page.py` and
`tests/browser/test_aggregate.py`. Everything here runs without a browser
because it is about the rules rather than about a document: what the matcher
will and will not call a match, that both tools are classified before they can
be registered, and that neither one carries a private copy of a rule that
already exists once in the tree.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from kitchensink4web import packs, projection
from kitchensink4web.ops import extract as extract_ops
from kitchensink4web.policy import readonly

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------- the matcher


def _q(key, name, description=""):
    got = extract_ops._quality(key, name, description)
    return got[0] if got else None


def test_a_one_character_key_can_never_partial_match():
    """`_norm` strips everything that is not alphanumeric, so `t)` becomes `t`,
    and one character is a substring of almost every field description in
    existence. Both sides clear four characters now."""
    assert _q("t)", "price", "the current price") is None
    assert _q("t)", "published", "the publication date") is None
    assert _q("id", "identifier") is None


def test_partial_matching_is_a_word_boundary_rule():
    """A key IS one of the field name's words, or the field name IS one of the
    key's words. Never a bare substring test, which is what produced the wrong
    answers this whole guard exists for."""
    assert _q("price", "unit_price") == "partial"
    assert _q("author", "book_author_name") == "partial"
    # `pric` is inside `price` and is not one of its words.
    assert _q("pric", "price") is None
    # `price` is inside `enterprise` and is not one of its words either.
    assert _q("enterprise", "price") is None


def test_the_description_never_feeds_a_partial():
    """A field `product_name` described as "the product title" reached the
    DOCUMENT title through the key `title`, which is plausible, wrong, and
    confidently labeled."""
    assert _q("title", "product_name", "the product title") is None
    # The description still sharpens the two stronger qualities.
    assert _q("current price", "price", "the current price") == "all-words"
    assert _q("the current price", "price",
              "the current price") == "exact"


def test_specificity_breaks_a_tie_and_a_real_tie_still_refuses():
    """A schema.org Product declares `offers.price` and `offers.priceCurrency`
    and a field named `price` is a subset of both, so without a specificity
    tie-break every commerce page answers ambiguous for its own price. A key
    that says MORE than the field asked for is a worse answer to that field."""
    tight = extract_ops._quality("offers.price", "price", "")
    loose = extract_ops._quality("offers.priceCurrency", "price", "")
    assert tight[0] == loose[0] == "all-words"
    assert tight[1] < loose[1], (tight, loose)
    # Two keys that say exactly the same thing tie, and a tie refuses.
    assert extract_ops._quality("author", "author", "") == \
        extract_ops._quality("author", "author", "")


def test_stop_words_are_function_words_only():
    """Stripping `current` would make "the current price" and "price" the same
    needle, which is the matcher deciding what the caller meant."""
    assert "the" in extract_ops._STOPWORDS
    assert "current" not in extract_ops._STOPWORDS
    assert "listed" not in extract_ops._STOPWORDS
    assert extract_ops._content_words("the current price") == {
        "current", "price"}


def test_camel_case_splits_before_the_word_comparison():
    assert extract_ops._words("priceCurrency") == {"price", "currency"}
    assert extract_ops._words("shipping_weight") == {"shipping", "weight"}
    assert extract_ops._words("offers.price") == {"offers", "price"}


# ---------------------------------------------------------- argument guards


def test_schema_argument_shapes():
    assert extract_ops._schema_arg(["a", "b"]) == {"a": "", "b": ""}
    assert extract_ops._schema_arg({"a": "hint"}) == {"a": "hint"}
    for bad in ([], {}, None, "price", 7):
        with pytest.raises(Exception):
            extract_ops._schema_arg(bad)


def test_schema_cap_refuses_before_anything_runs():
    with pytest.raises(Exception) as exc:
        extract_ops._schema_arg(
            [f"f{i}" for i in range(extract_ops.MAX_SCHEMA_FIELDS + 1)])
    assert "no extraction ran" in str(exc.value)


def test_tiers_argument_and_what_all_admits():
    assert extract_ops._tiers_arg("all") == ("declared", "labeled",
                                             "proximate")
    assert extract_ops._tiers_arg("declared") == ("declared",)
    assert extract_ops._tiers_arg("page-hint") == ("page-hint",)
    # The default surface must not be able to answer from a class token.
    assert "page-hint" not in extract_ops._tiers_arg("all")
    with pytest.raises(Exception):
        extract_ops._tiers_arg("prose")


def test_confidence_is_an_ordinal_name_and_never_a_number():
    """A float would imply a calibration nobody has measured and would invite
    the caller to threshold on it. The tier name is checkable against the page
    with `by` and `matched_key` beside it."""
    assert extract_ops.TIER_ORDER == ("declared", "labeled", "proximate",
                                      "page-hint")
    for tier in extract_ops.TIER_ORDER:
        assert isinstance(tier, str)
        assert not tier.replace(".", "").isdigit()


# ------------------------------------------------------------- registration


def test_extract_page_registration(launch, live_tools):
    launch(cli_packs=["extract"], read_only=False)
    tools = live_tools()
    assert "extract_page" in tools
    assert "extract_page" in packs.PLANNED_MEMBERS["extract"]
    assert "extract_page" in readonly.NON_MUTATING
    assert "extract_page" in readonly.GENUINELY_READ_ONLY
    assert readonly.read_only_hint("extract_page") is True
    assert readonly.is_mutating("extract_page") is False


def test_aggregate_registration(launch, live_tools):
    """`aggregate` NAVIGATES, so it is non-mutating and deliberately NOT
    genuinely read-only, exactly as `read_pages` and `navigate` are."""
    launch(cli_packs=["extract"], read_only=False)
    tools = live_tools()
    assert "aggregate" in tools
    assert "aggregate" in packs.PLANNED_MEMBERS["extract"]
    assert "aggregate" in readonly.NON_MUTATING
    assert "aggregate" not in readonly.GENUINELY_READ_ONLY
    assert readonly.read_only_hint("aggregate") is False


def test_both_are_absent_without_the_extract_pack(launch, live_tools):
    launch(cli_packs=[], read_only=False)
    tools = live_tools()
    assert "extract_page" not in tools
    assert "aggregate" not in tools


def test_both_survive_read_only_mode(launch, live_tools):
    """Neither one clicks, types, submits, uploads, downloads, evaluates
    script, or writes storage, so read-only keeps both."""
    launch(cli_packs=["extract"], read_only="browse")
    tools = live_tools()
    assert "extract_page" in tools
    assert "aggregate" in tools


# -------------------------------------------------- shared-source discipline


def test_schema_js_splices_the_one_visibility_rule():
    """Three private copies of "can a human see this" is the drift
    `visibility.js` was created to end, and a divergence between two
    visibility detectors is a page-controlled channel for showing one thing to
    a human and another to the agent."""
    source = (ROOT / "src" / "kitchensink4web" / "projection"
              / "schema.js").read_text(encoding="utf-8")
    assert "// @@KS4WEB_VISIBILITY@@" in source
    assert "// @@KS4WEB_INSTRUMENT@@" in source
    # No private re-implementation of the rule, under any of its names.
    for banned in ("function ksHiddenReason", "function ksHiddenAnywhere",
                   "function ksHiddenChain", "function ksGeometryHidden"):
        assert banned not in source, banned
    # And the real block is what ships.
    assert projection.VISIBILITY_JS in projection.SCHEMA_JS
    assert "ksHiddenAnywhere" in projection.SCHEMA_JS


def test_the_matcher_is_server_side():
    """A matcher running in page script is a matcher the page can profile
    against, and every confident-wrong-answer defect in this feature lives in
    the matcher."""
    source = (ROOT / "src" / "kitchensink4web" / "projection"
              / "schema.js").read_text(encoding="utf-8")
    assert "schema" not in source.split("(opts) =>")[1].lower() \
        or "opts.schema" not in source
    assert "NOTHING HERE MATCHES" in source


def test_aggregate_composes_rather_than_re_expressing():
    """#7 is `extract_page` in a loop. It calls the SAME collector-and-ladder
    function the single-page tool calls and the SAME `wait_for`, so the batch
    tool cannot drift from the tool it batches."""
    row = inspect.getsource(extract_ops._aggregate_one)
    assert "_schema_read(" in row
    assert "_lite.wait_for(" in row
    assert "_lite._wall_verdict(" in row
    assert "_lite._landed_origin_check(" in row
    assert "_resource.probe_page(" in row
    assert "_policy.approve(" in row
    # And the single-page tool goes through the same door.
    assert "_schema_read(" in inspect.getsource(extract_ops.extract_page)


def test_the_secret_classifier_is_the_shared_one():
    """A field that is secret in the projection must not be readable here, so
    the classification is re-derived through `policy/credentials.py` rather
    than trusted from the page."""
    source = inspect.getsource(extract_ops._is_secret)
    assert "_credentials.is_secret_field" in source
    assert "_credentials.is_payment_field" in source


def test_aggregate_default_tracks_the_navigation_budget(monkeypatch):
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "150")
    assert extract_ops.default_batch_size() == 30
    monkeypatch.setenv("KS4WEB_MAX_NAVIGATIONS", "5")
    assert extract_ops.default_batch_size() == 1
    assert extract_ops.AGGREGATE_URL_CEILING == 50


def test_the_per_url_code_set_is_inside_the_closed_vocabulary():
    """A per-URL error is INDISTINGUISHABLE in shape from a top-level one, so
    it has to speak the same closed vocabulary."""
    from kitchensink4web import envelope
    assert extract_ops._PER_URL_CODES <= envelope.CLOSED_CODES
    # The batch-stopping classes are deliberately NOT in it.
    for code in ("BUDGET_EXHAUSTED", "LOOP_DETECTED", "SESSION_DEAD",
                 "CONFLICT", "BAD_PARAMS"):
        assert code not in extract_ops._PER_URL_CODES, code
