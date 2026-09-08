"""The update notice: one line in `manage_session(action='status')`.

Converted in fix wave 10 from the 14-day silent-skip design to the
author-approved spec. Six points changed and each one is a difference of
principle rather than of taste, so they are listed rather than summarised:

- **Check on demand only.** Nothing runs at startup, nothing runs on a
  thread, and no tool path other than `manage_session(action='status')`
  reaches this module. A status call is a caller asking how the server is;
  a `navigate` call is not, and never pays for this.
- **At most one network request per 24 hours**, cached in the state dir.
- **A two-second timeout**, which is the whole budget: a status call must
  not become slow because PyPI is.
- **Failure is REPORTED, not swallowed.** The old design called silence a
  courtesy. In a product whose entire safety layer is built on saying what
  it did and did not do, a check that quietly did not happen is the one
  thing this file must not be. A failed check says it failed and says how
  old the last success was.
- **The off switch is KS4WEB_UPDATE_CHECK=off**, and when it is off the
  status says so as a fact rather than showing nothing.
- **The privacy disclosure ships with the answer.** This is the only thing
  in the product that talks to a machine the user did not ask it to talk
  to, and that fact belongs beside the result every time, not in a
  document.

Never installs anything. The line names the versions and the command; the
human decides.

A HOSTILE OR MALFORMED PyPI RESPONSE NEVER CRASHES AND NEVER FABRICATES A
VERSION. Everything the network hands back is treated as an untrusted
string of unknown type: the body is size-capped before it is parsed, the
version is required to be a string of a shape this module can compare, and
anything that fails either test is reported as an unreadable answer rather
than being coerced into looking like a release.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

#: The off switch. `off` (case-insensitive) disables the check; every other
#: value leaves it on, including nonsense, because a typo must not silently
#: disable a check the user believes is running.
ENV_TOGGLE = "KS4WEB_UPDATE_CHECK"

#: The superseded spelling, still honored so an existing configuration does
#: not silently start making network calls it had switched off.
ENV_OPT_OUT = "KS4WEB_NO_UPDATE_CHECK"

PACKAGE = "kitchensink4web"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"

#: One network call per 24 hours, whatever the outcome. A failed check
#: writes its attempt time too, so a machine with no network tries once a
#: day rather than on every status call.
CACHE_MAX_AGE_S = 24 * 3600
FETCH_TIMEOUT_S = 2.0

#: PyPI's own JSON for this package is a few tens of kilobytes. The cap is
#: not a performance measure: it is what stops a hostile or misrouted
#: response from being read into memory in full before it is judged.
MAX_BYTES = 256 * 1024

#: What the check sends. Named as a constant so the disclosure below and the
#: code that does it cannot drift apart.
PRIVACY_FACT = (
    "[COPY PENDING: updatecheck.privacy] FACTS: this is the only network "
    "call KS4Web makes that the caller did not ask for. It is a plain HTTPS "
    "GET to pypi.org for the public release index of this package. It sends "
    "no identifier, no usage data, no page content and no session state; it "
    "sends nothing but the request. The answer is a version number. Set "
    f"{ENV_TOGGLE}=off to stop it.")


def _cache_path():
    from .policy import audit as _audit
    return _audit.STATE_DIR / "update_check.json"


def enabled() -> bool:
    """Is the check on? Off requires the word `off`, or the superseded
    opt-out set to anything truthy."""
    if (os.environ.get(ENV_TOGGLE) or "").strip().lower() == "off":
        return False
    legacy = (os.environ.get(ENV_OPT_OUT) or "").strip().lower()
    return legacy in ("", "0", "false", "no", "off")


def _installed_version() -> str | None:
    try:
        from importlib.metadata import version
        return version(PACKAGE)
    except Exception:
        return None


def _parse(version) -> tuple[int, ...] | None:
    """A dotted-numeric version as a comparable tuple, or None.

    Type-checked rather than duck-typed on purpose: `version` arrives from
    a network document on one of its two call paths, so a list, a dict, or
    a number reaching `.split` would be an exception raised inside a status
    call by a remote server's choice of JSON."""
    if not isinstance(version, str):
        return None
    parts = version.strip().split(".")
    if not parts or len(parts) > 8:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _read_cache() -> dict:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(data: dict) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass          # an unwritable cache just means a fetch next time


def _fetch_latest() -> tuple[str | None, str | None]:
    """One request. Returns `(version, None)` or `(None, why_it_failed)`.

    The failure string is a CATEGORY, never the exception's own text: a
    remote server does not get to write a sentence into a KS4Web payload,
    which is the same rule the driver-text scrubber enforces everywhere
    else in this build."""
    try:
        with urllib.request.urlopen(PYPI_URL,
                                    timeout=FETCH_TIMEOUT_S) as response:
            raw = response.read(MAX_BYTES + 1)
    except Exception:
        return None, "pypi.org could not be reached"
    if len(raw) > MAX_BYTES:
        return None, "the answer from pypi.org was larger than expected"
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None, "the answer from pypi.org was not readable JSON"
    if not isinstance(data, dict):
        return None, "the answer from pypi.org was not the expected shape"
    info = data.get("info")
    latest = info.get("version") if isinstance(info, dict) else None
    if _parse(latest) is None:
        # A version this module cannot compare is not a version it will
        # report. Reporting it would put a remote string in front of a user
        # under a label saying it is the newer release.
        return None, "pypi.org did not name a version this build can read"
    return latest, None


def _age_phrase(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)} minute(s) ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hour(s) ago"
    return f"{int(seconds // 86400)} day(s) ago"


def check() -> dict:
    """The update check as a payload, always a dict, never raising.

    `state` is one of `off`, `current`, `update_available`, `unknown`. The
    last one is the honest branch the superseded design did not have: a
    check that could not run says so, says why in categories rather than in
    the remote server's words, and says how long ago the last successful
    one was."""
    installed = _installed_version()
    if not enabled():
        return {
            "state": "off",
            "installed": installed,
            "why": f"{ENV_TOGGLE} is set to off, so no check was made and "
                   f"nothing was sent anywhere.",
            "privacy": PRIVACY_FACT,
        }
    cache = _read_cache()
    now = time.time()
    latest = cache.get("latest")
    error = None
    checked_at = cache.get("checked_at")
    last_success = cache.get("last_success_at")
    fresh = isinstance(checked_at, (int, float)) \
        and 0 <= now - checked_at < CACHE_MAX_AGE_S
    if fresh:
        error = cache.get("error")
    else:
        latest, error = _fetch_latest()
        record = {"checked_at": now, "latest": latest, "error": error}
        if latest:
            record["last_success_at"] = now
            last_success = now
        elif isinstance(last_success, (int, float)):
            record["last_success_at"] = last_success
            record["latest"] = cache.get("latest")
            latest = cache.get("latest")
        _write_cache(record)
    payload: dict = {"installed": installed, "privacy": PRIVACY_FACT,
                     "source": PYPI_URL,
                     "cadence": "at most one request per 24 hours"}
    have = _parse(installed)
    want = _parse(latest)
    if error and want is None:
        payload["state"] = "unknown"
        payload["why"] = error
        payload["last_successful_check"] = (
            _age_phrase(now - last_success)
            if isinstance(last_success, (int, float))
            else "never, on this machine")
        payload["note"] = (
            "[COPY PENDING: updatecheck.unknown] FACTS: the check did not "
            "complete, so this says nothing about whether an update exists. "
            "It is not a claim that the installed version is current. "
            "Nothing was installed and nothing else about this server is "
            "affected.")
        return payload
    if have is None or want is None:
        payload["state"] = "unknown"
        payload["why"] = ("this build's own version is not a shape the "
                          "comparison reads" if have is None else
                          "no release version was available to compare")
        return payload
    payload["latest"] = latest
    if want <= have:
        payload["state"] = "current"
        payload["note"] = (
            "[COPY PENDING: updatecheck.current] FACTS: the installed "
            "version is the newest on PyPI, or newer than it.")
        return payload
    payload["state"] = "update_available"
    payload["note"] = (
        f"[COPY PENDING: updatecheck.available] FACTS: KS4Web {installed} is "
        f"running and {latest} is published on PyPI. Nothing updates itself "
        f"and nothing was installed. The upgrade command is "
        f"`pip install -U {PACKAGE}`, or a uvx launch picks it up on its "
        f"next start. A bundled install upgrades by installing the new "
        f"bundle, not with pip.")
    return payload


def status_line() -> dict | None:
    """What `manage_session(action='status')` puts under its `update` key.

    Returns None only where there is nothing worth a line at all, which is
    the `current` state: a caller who is up to date does not need a
    paragraph saying so on every status call. Off, unknown, and
    update-available all speak, because each of those is a fact about
    whether this server knows something it is not telling."""
    try:
        payload = check()
    except Exception:
        # The check is housekeeping. It may never be the reason a status
        # call fails, which is the surface a caller reaches for precisely
        # when everything else is refusing.
        return None
    return None if payload.get("state") == "current" else payload
