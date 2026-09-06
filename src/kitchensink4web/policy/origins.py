"""The origin allow/deny evaluator, deny evaluated first (DESIGN 5.9).

Env contract:

    KS4WEB_DENY_ORIGINS    comma-separated patterns; a match REFUSES, always
    KS4WEB_ALLOW_ORIGINS   comma-separated patterns; when set, anything
                           unlisted is OFF-LIST (gated under normal mode,
                           refused under read-only `strict`)

A pattern is a hostname (`example.com`), a wildcard (`*.example.com`, which
matches subdomains AND the bare domain), or a full origin
(`https://example.com:8443`). Deny is evaluated first, so a host on both
lists is denied; that is the only safe way to resolve the conflict.

The standing caveat, copied from the honest phrasing playwright-mcp uses for
its own file guardrail: an origin list is a convenience defense to catch
unintended navigation, not a security boundary.

Four verdicts, and who acts on each:

    denied        -> `NAVIGATION_BLOCKED`, raised HERE
    denied-scheme -> `NAVIGATION_BLOCKED`, raised HERE: the scheme names no
                     web origin (file:, data:, anything non-web), so no list
                     can rule on it and nothing widens it (gauntlet 3, F7)
    off-list      -> a GATED action class (navigation outside the allowlist
                     is confirmation-gated per DESIGN 5.4, refused outright
                     under read-only `strict` per DESIGN 5.2), decided by
                     the caller
    allowed       -> proceed

The MID-ACTION rule (corpus C's redirect case): the check applies to where a
navigation LANDED, not only to where it was aimed. The ops layer re-evaluates
the final URL after every navigation and aborts to `about:blank` on a denied
verdict, so a redirect cannot launder a blocked origin.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from ..errors import NavigationBlocked, ReadOnlyMode

ENV_DENY = "KS4WEB_DENY_ORIGINS"
ENV_ALLOW = "KS4WEB_ALLOW_ORIGINS"

#: Browser-internal schemes that never carry a web origin worth policing.
#: `about:blank` in particular must always be reachable, because it is where
#: an aborted navigation parks. `data:` is NOT here any more (gauntlet 3,
#: F7): a hostname-less scheme that early-returned "allowed" bypassed even a
#: configured allowlist, and `file:` rode the same hole into local-file
#: disclosure. Anything that is neither web nor browser-internal is denied.
EXEMPT_SCHEMES = ("about", "chrome", "chrome-error", "edge")

#: The schemes that name a web origin. Everything the deny/allow lists were
#: built to police lives here; a URL outside this set and outside
#: EXEMPT_SCHEMES is refused outright, allowlist or not, because a `file:`
#: or `data:` URL reads outside the web entirely and no origin pattern can
#: ever match it.
WEB_SCHEMES = ("http", "https")


def _patterns(env: str) -> tuple[str, ...]:
    raw = os.environ.get(env, "")
    return tuple(p.strip().lower() for p in raw.split(",") if p.strip())


def _matches(pattern: str, url_parts) -> bool:
    host = (url_parts.hostname or "").lower()
    if not host:
        return False
    if "://" in pattern:  # full origin: scheme, host, and explicit port
        want = urlparse(pattern)
        return (want.scheme == url_parts.scheme.lower()
                and (want.hostname or "").lower() == host
                and (want.port or None) == (url_parts.port or None))
    if pattern.startswith("*."):
        bare = pattern[2:]
        return host == bare or host.endswith("." + bare)
    return host == pattern


def evaluate(url: str) -> str:
    """One verdict per URL: 'denied', 'denied-scheme', 'off-list', or
    'allowed'.

    'denied-scheme' is the F7 fix (gauntlet 3): a URL whose scheme is
    neither http(s) nor browser-internal, or that carries no hostname at
    all, used to early-return "allowed" here — before the deny list, before
    the allow list — which is exactly the hole a page-published
    `file:///C:/...` next-link rode into a local-file read. The refusal is
    unconditional: no env var and no allowlist widens it."""
    parts = urlparse(url)
    scheme = parts.scheme.lower()
    if scheme in EXEMPT_SCHEMES:
        return "allowed"
    if scheme not in WEB_SCHEMES or not parts.hostname:
        return "denied-scheme"
    for pattern in _patterns(ENV_DENY):  # deny first, always
        if _matches(pattern, parts):
            return "denied"
    allow = _patterns(ENV_ALLOW)
    if allow and not any(_matches(p, parts) for p in allow):
        return "off-list"
    return "allowed"


def active() -> dict:
    return {"deny": list(_patterns(ENV_DENY)),
            "allow": list(_patterns(ENV_ALLOW))}


def check_navigation(url: str, read_only_grade: str | None = None,
                     phase: str = "requested") -> str:
    """Raise on a denied or strict-off-list URL; return the verdict
    otherwise, so the caller can route 'off-list' to the confirmation gate.

    `phase` names when the check ran ('requested' before the navigation,
    'landed' after it), because a mid-action redirect refusal has to say the
    navigation already happened and was aborted, which is a different fact
    from a navigation that never started."""
    verdict = evaluate(url)
    landed = phase == "landed"
    if verdict == "denied-scheme":
        raise NavigationBlocked(
            f'{url} is not an http(s) URL, so the origin policy refuses it: '
            f'a scheme that names no web origin (file:, data:, or anything '
            f'else non-web) reads outside the web entirely, and no deny or '
            f'allow list can ever rule on it. '
            + ('The page had already navigated there mid-action, so it was '
               'parked to about:blank and nothing was read from it.'
               if landed else 'The navigation was not started.'))
    if verdict == "denied":
        raise NavigationBlocked(
            f'{url} is on the deny list ({ENV_DENY}), evaluated before the '
            f'allow list, always. '
            + ('The page had already redirected there mid-action, so it was '
               'parked to about:blank and nothing was read from it. '
               if landed else 'The navigation was not started. ')
            + f'Remove the origin from {ENV_DENY} at launch to allow it.')
    if verdict == "off-list" and read_only_grade == "strict":
        raise ReadOnlyMode(
            f'{url} is outside the origin allowlist and this server is '
            f'read-only at grade "strict", which limits navigation to '
            f'{ENV_ALLOW}. Grade "browse" permits open navigation; restart '
            f'without --read-only strict, or add the origin to the '
            f'allowlist at launch.')
    return verdict
