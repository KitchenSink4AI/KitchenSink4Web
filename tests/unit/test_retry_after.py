"""Retry-After, in both spellings, on both statuses that carry it.

The header was read on 429 alone and parsed as a bare number alone, so a 503
with a wait attached lost the number entirely and an HTTP-date was thrown
away in favour of the default. Both are the responses a rate-limiting edge
actually sends.

The other half of the contract is that nothing sleeps. `timeout_ms` is the
caller's allotment for a navigation, and spending it inside a wait would turn
"the site asked for ninety seconds" into a timeout that blames the wrong
party, so the window is honored by refusing the next request and the number
is reported as a fact.
"""

from __future__ import annotations

import time
from email.utils import formatdate

import pytest

from kitchensink4web.errors import BlockedBySite
from kitchensink4web.policy import budgets


@pytest.fixture
def book():
    return budgets.BudgetBook()


# ------------------------------------------------------------------ parsing


def test_delta_seconds_is_read():
    assert budgets.parse_retry_after("120") == 120.0
    assert budgets.parse_retry_after(" 7 ") == 7.0
    assert budgets.parse_retry_after("0") == 0.0


def test_an_http_date_is_read_rather_than_thrown_away():
    when = formatdate(time.time() + 60, usegmt=True)
    got = budgets.parse_retry_after(when)
    assert got is not None and 50 <= got <= 70


def test_a_date_already_past_means_the_window_has_passed():
    when = formatdate(time.time() - 600, usegmt=True)
    assert budgets.parse_retry_after(when) == 0.0


def test_a_negative_delta_never_becomes_a_negative_wait():
    assert budgets.parse_retry_after("-30") == 0.0


def test_an_absurd_wait_is_clamped_rather_than_believed():
    assert budgets.parse_retry_after("99999999") == budgets.MAX_RETRY_AFTER_S


@pytest.mark.parametrize("raw", [
    None, "", "   ", "soon", "later please", "NaN", "inf", "-inf",
    "Mon, 99 Zzz 9999 99:99:99 GMT", "12,34", "1e400",
])
def test_an_unparseable_header_is_none_rather_than_a_guess(raw):
    assert budgets.parse_retry_after(raw) is None


# ------------------------------------------------------- honoring the window


def test_the_header_is_honored_and_reported(book):
    got = book.note_retry_after("api.example.org", "45", status=429,
                                budget_ms=30000)
    assert got["seconds"] == 45.0
    assert got["source"] == "Retry-After header"
    assert got["waited"] is False, "KS4Web never sleeps the caller's budget"
    assert got["fits_in_budget"] is False
    with pytest.raises(BlockedBySite):
        book.check_domain("API.EXAMPLE.ORG")


def test_a_short_wait_is_reported_as_fitting_the_call_budget(book):
    got = book.note_retry_after("api.example.org", "2", status=429,
                                budget_ms=30000)
    assert got["fits_in_budget"] is True
    assert got["call_budget_s"] == 30.0


def test_a_429_with_no_header_falls_back_to_the_documented_default(book):
    got = book.note_retry_after("api.example.org", None, status=429)
    assert got["seconds"] == budgets.DEFAULT_RETRY_AFTER_S
    assert "default" in got["source"]
    assert got.get("header") is None


def test_a_malformed_header_is_named_rather_than_silently_defaulted(book):
    got = book.note_retry_after("api.example.org", "soon", status=429)
    assert got["header"] == "soon"
    assert got["header_unparsed"] is True
    assert got["seconds"] == budgets.DEFAULT_RETRY_AFTER_S


def test_503_is_one_of_the_statuses_that_carries_a_wait():
    assert 503 in budgets.RETRY_AFTER_STATUSES
    assert 429 in budgets.RETRY_AFTER_STATUSES
    assert 403 not in budgets.RETRY_AFTER_STATUSES


def test_the_window_only_ever_grows(book):
    book.note_retry_after("api.example.org", "300", status=429)
    book.note_retry_after("api.example.org", "1", status=429)
    with pytest.raises(BlockedBySite) as caught:
        book.check_domain("api.example.org")
    assert "s left" in str(caught.value)


def test_another_domain_is_untouched(book):
    book.note_retry_after("api.example.org", "300", status=429)
    book.check_domain("other.example.org")
