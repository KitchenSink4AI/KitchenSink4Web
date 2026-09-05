"""The 14-day update check (Phase 8 config work, item b).

One calm line in `manage_session(action='status')` when a newer release is
on PyPI, and nothing else. The full contract:

- **Never installs anything.** The line names the versions and the command;
  the human decides.
- **At most one network request per 14 days**, cached in the state dir, so
  the check costs nothing on the sessions in between.
- **Opt-out**: KS4WEB_NO_UPDATE_CHECK set to anything truthy skips the
  check entirely, cache and network both.
- **Network failure is a silent skip.** A safety product must not turn its
  own housekeeping into noise: no warning, no retry storm, no stale-cache
  guess. The next status call after the window simply tries again.
- The comparison is numeric-dotted-parts only; anything it cannot parse
  (dev builds, pre-releases) is a silent skip too.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

ENV_OPT_OUT = "KS4WEB_NO_UPDATE_CHECK"
PYPI_URL = "https://pypi.org/pypi/kitchensink4web/json"
CACHE_MAX_AGE_S = 14 * 24 * 3600
_FETCH_TIMEOUT_S = 3


def _cache_path():
    from .policy import audit as _audit
    return _audit.STATE_DIR / "update_check.json"


def _opted_out() -> bool:
    value = (os.environ.get(ENV_OPT_OUT) or "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


def _installed_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("kitchensink4web")
    except Exception:
        return None


def _parse(version: str) -> tuple[int, ...] | None:
    parts = (version or "").strip().split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _latest_version() -> str | None:
    """The newest release on PyPI, from the 14-day cache or one fetch."""
    path = _cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(cached.get("checked_at", 0)) < CACHE_MAX_AGE_S:
            return cached.get("latest") or None
    except Exception:
        pass  # no cache, or an unreadable one: fetch fresh
    try:
        with urllib.request.urlopen(PYPI_URL,
                                    timeout=_FETCH_TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
        latest = data["info"]["version"]
    except Exception:
        return None  # the silent skip: network trouble is not the user's
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": time.time(),
                                    "latest": latest}), encoding="utf-8")
    except Exception:
        pass  # an unwritable cache just means a fetch next time
    return latest


def status_line() -> str | None:
    """The one calm line for manage_session status, or None.

    None means: opted out, up to date, network trouble, or a version shape
    the comparison does not parse. Only a confirmed newer release speaks."""
    if _opted_out():
        return None
    installed = _installed_version()
    have = _parse(installed) if installed else None
    if have is None:
        return None
    latest = _latest_version()
    want = _parse(latest) if latest else None
    if want is None or want <= have:
        return None
    return (f"KS4Web {installed} is running and {latest} is on PyPI. "
            f"Nothing updates itself; when convenient, upgrade with "
            f"pip install -U kitchensink4web (or let uvx pick it up on "
            f"the next launch). Set {ENV_OPT_OUT}=1 to silence this check.")
