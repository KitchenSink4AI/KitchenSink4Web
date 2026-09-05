"""Cookie expiry: which cookie is asked, and when it is worth a word.

Field log 2, item U10, asked twice in two separate parts. A saved login that
has quietly run out is the worst silent auth failure there is: the load
reports the cookie count it always reports, the navigation that follows
lands on a sign-in page, and nothing in the transcript connects the two.

Two rules do the whole job and both are here rather than in the tool:

1. **Only auth-relevant cookies are asked.** A consent banner cookie that
   dies at midnight is not a login about to lapse, and the same classifier
   the redaction vault uses decides which is which. Getting this wrong would
   produce a warning on almost every load, which is the same as no warning.
2. **Silence is the common case.** The line appears when the earliest auth
   cookie has expired or is inside a day of it, and never otherwise.
"""

from __future__ import annotations

import time

from kitchensink4web.ops import common

NOW = 1_800_000_000.0


def _cookie(name, expires, **kw):
    return {"name": name, "value": "x", "domain": "example.com",
            "path": "/", "expires": expires, **kw}


# ---------------------------------------------------------- which cookie


def test_a_preference_cookie_is_not_a_login():
    """The calibration case, straight out of the vault's own tuning: a
    theme cookie expiring in an hour must not be reported as a login about
    to lapse."""
    info = common.auth_expiry([
        _cookie("color_mode", NOW + 600),
        _cookie("session_token", NOW + 90 * 86400),
    ])
    assert info["name"] == "session_token"


def test_httponly_counts_as_auth_whatever_it_is_called():
    """A site that put a value out of scripting's reach meant it."""
    info = common.auth_expiry([
        _cookie("wat", NOW + 600, httpOnly=True),
        _cookie("csrftoken", NOW + 86400 * 30),
    ])
    assert info["name"] == "wat"


def test_the_earliest_auth_cookie_wins():
    info = common.auth_expiry([
        _cookie("auth_a", NOW + 5000),
        _cookie("auth_b", NOW + 50),
        _cookie("auth_c", NOW + 500000),
    ])
    assert info["name"] == "auth_b"
    assert info["expires"] == NOW + 50


def test_session_cookies_are_counted_not_dated():
    """`expires` at or below zero is a session cookie: it has no date to age
    out, so it is counted and never reported as an expiry."""
    info = common.auth_expiry([_cookie("sessionid", -1),
                              _cookie("authtoken", 0)])
    assert info == {"session_cookies": 2}
    assert common.expiry_note(info) is None


def test_a_millisecond_expiry_is_read_as_milliseconds():
    """Firefox writes `moz_cookies.expiry` in milliseconds, which the load
    refusal already teaches. Read as seconds it would be the year 55000 and
    every such file would report a login good for fifty thousand years."""
    info = common.auth_expiry([_cookie("sessionid", (NOW + 100) * 1000)])
    assert abs(info["expires"] - (NOW + 100)) < 1


def test_no_auth_cookies_at_all_is_none():
    assert common.auth_expiry([_cookie("theme", NOW + 10)]) is None
    assert common.auth_expiry([]) is None
    assert common.expiry_note(None) is None


# ------------------------------------------------------------- the line


def test_a_healthy_login_says_nothing():
    info = common.auth_expiry([_cookie("sessionid", NOW + 40 * 86400)])
    assert common.expiry_note(info, now=NOW) is None


def test_an_expired_login_says_how_long_ago():
    info = common.auth_expiry([_cookie("sessionid", NOW - 2 * 86400)])
    line = common.expiry_note(info, now=NOW)
    assert "expired 2 day(s) ago" in line
    assert "a fresh login is likely needed" in line
    assert "sessionid" in line


def test_a_login_inside_a_day_says_how_long_is_left():
    info = common.auth_expiry([_cookie("sessionid", NOW + 3 * 3600)])
    line = common.expiry_note(info, now=NOW)
    assert "expires in 3 hour(s)" in line
    assert "likely needed soon" in line


def test_the_boundary_is_a_day_and_it_is_not_off_by_one():
    just_inside = common.auth_expiry(
        [_cookie("sessionid", NOW + common.NEAR_EXPIRY_S - 60)])
    just_outside = common.auth_expiry(
        [_cookie("sessionid", NOW + common.NEAR_EXPIRY_S + 60)])
    assert common.expiry_note(just_inside, now=NOW) is not None
    assert common.expiry_note(just_outside, now=NOW) is None


def test_the_note_defaults_to_the_real_clock():
    """No `now` argument means now, which is what every caller passes."""
    info = common.auth_expiry([_cookie("sessionid", time.time() - 3600)])
    assert "expired" in common.expiry_note(info)
