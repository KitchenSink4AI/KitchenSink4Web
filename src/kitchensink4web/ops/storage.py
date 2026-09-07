"""The `storage` pack: cookies, web storage, and auth-state (DESIGN 2.2).

The key move nobody frames as a safety feature: `save_auth_state` writes
session state to a FILE, so authentication is reused across runs without
ever passing through the model's context. Playwright ships the mechanism;
this pack frames it for what it is.

Values are MASKED by default everywhere in this module. A cookie value or a
storage value is credential material as often as not, so:

- reads return names, domains, flags, and sizes with values masked;
- `unmask=true` is per-call, explicit, audited, and REFUSED under
  KS4WEB_CREDENTIAL_BLIND=strict (the default);
- every value the module touches is observed into the vault BEFORE masking,
  so the serializer catches any later path that would emit it.

The whole module mutates or reads credential state, so `manage_cookies`,
`manage_storage`, `save_auth_state`, and `load_auth_state` are all absent
under read-only mode, and the two clearing paths and the state load pass
the policy choke point (a storage clear and an auth load are gated
classes).
"""

from __future__ import annotations

import time
from pathlib import Path

from ..errors import BadParams, TargetNotFound
from ..policy import credentials as _credentials
from ..policy import engine as _policy
from ..policy import gates as _gates
from ..policy import sandbox
from . import common
from . import lite as _lite


def _mask_cookie(cookie: dict, unmask: bool) -> dict:
    value = cookie.get("value", "")
    # Vault only the credential-shaped ones. Vaulting every cookie is what
    # the 2026-09-05 field test caught shredding ordinary reads: a
    # preference cookie's value gets redacted out of unrelated page text
    # for the rest of the session. The VALUE is still masked in this
    # payload either way; masking and vaulting are different guarantees.
    _credentials.VAULT.observe_cookie(cookie)
    return {
        "name": cookie.get("name"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "secure": cookie.get("secure"),
        "httpOnly": cookie.get("httpOnly"),
        "sameSite": cookie.get("sameSite"),
        "expires": cookie.get("expires"),
        "value": (common.clip(value, 300) if unmask
                  else _credentials.mask_value(value)),
    }


async def manage_cookies(
    session: str | None = None,
    action: str = "list",
    name: str | None = None,
    url: str | None = None,
    unmask: bool = False,
) -> dict:
    """List, count, or clear the session's cookies. Listing returns each
    cookie's name, domain, path, flags, and expiry with the VALUE masked by
    default, because a cookie value is session material; unmask=true is
    per-call, audited, and refused under the strict credential-blind
    default. Clearing is a gated action that fails closed until a human
    confirms. Returns the cookies (masked) or the count cleared. Values
    touched here are observed into the redaction vault, so a cookie can
    never ride out of any later payload either.
    """
    action = common.enum_arg(action, ("list", "count", "clear"),
                             default="list", tool="manage_cookies")
    sess = common.session_of(session)
    if unmask:
        _credentials.check_unmask("manage_cookies(unmask=true)")
    cookies = await sess.context.cookies(url) if url \
        else await sess.context.cookies()
    if name:
        cookies = [c for c in cookies if c.get("name") == name]
    if action == "count":
        return {"session": sess.session_id, "count": len(cookies),
                "url_filter": url, "name_filter": name}
    if action == "clear":
        _gates.ENGINE.ask(
            "storage_clear", tool="manage_cookies",
            session=sess.session_id, page=None, target=None,
            summary=(f"Clear {len(cookies)} cookie(s) from session "
                     f"{sess.session_id}"
                     + (f" matching {name!r}" if name else "")
                     + (f" for {url}" if url else "") + "?"))
    return {
        "session": sess.session_id,
        "cookies": [_mask_cookie(c, unmask) for c in cookies],
        "count": len(cookies),
        "note": ("values are masked by default; unmask=true is per-call and "
                 "audited" if not unmask else "values unmasked for this "
                 "audited call"),
    }


_STORAGE_JS = r"""
(opts) => {
  const which = opts.which === 'session' ? sessionStorage : localStorage;
  const out = [];
  for (let i = 0; i < which.length; i++) {
    const key = which.key(i);
    const value = which.getItem(key);
    out.push({ key: key, chars: (value || '').length,
      value: opts.unmask ? String(value).slice(0, 300) : null });
  }
  return { count: which.length, items: out };
}
"""


async def manage_storage(
    page: str,
    action: str = "list",
    kind: str = "local",
    key: str | None = None,
    unmask: bool = False,
) -> dict:
    """Read or clear a page's localStorage or sessionStorage. Listing
    returns each key with its value length and the value masked by default;
    unmask=true is per-call, audited, and refused under the strict
    credential-blind default. Clearing is a gated action that fails closed
    until a human confirms. IndexedDB is reported as present-or-absent with
    its database names rather than dumped, because a full IndexedDB read is
    unbounded and rarely what a caller wants. Values touched here are
    observed into the redaction vault.
    """
    action = common.enum_arg(action, ("list", "clear"), default="list",
                             tool="manage_storage")
    kind = common.enum_arg(kind, ("local", "session", "indexeddb"),
                           default="local", tool="manage_storage",
                           name="kind")
    sess, record = common.locate(page)
    # THE ORIGIN POLICY HERE TOO (union wave, IG-02). `manage_storage`
    # called its own gate engine for CLEARING only, so on a document no door
    # ruled on a deny-listed origin's localStorage KEY NAMES and value
    # lengths (`session_token`, `account_email`) came back as an ordinary
    # inventory while get_text on the same page refused and parked.
    await _lite._ensure_vetted(sess, record, tool="manage_storage")
    if unmask:
        _credentials.check_unmask("manage_storage(unmask=true)")

    if kind == "indexeddb":
        if action == "clear":
            _gates.ENGINE.ask(
                "storage_clear", tool="manage_storage",
                session=sess.session_id, page=record.handle, target=None,
                summary=f"Clear all IndexedDB databases on {record.handle}?")
        names = await record.page.evaluate(
            "async () => { if (!indexedDB.databases) return "
            "['(this browser does not enumerate databases)']; "
            "const dbs = await indexedDB.databases(); "
            "return dbs.map(d => d.name); }")
        return {"page": record.handle, "session": sess.session_id,
                "kind": "indexeddb", "databases": names,
                "note": ("IndexedDB is reported by name rather than dumped; "
                         "a full read is unbounded")}

    got = await record.page.evaluate(
        _STORAGE_JS, {"which": kind, "unmask": unmask})
    for item in got["items"]:
        if item.get("value") is not None:
            _credentials.VAULT.observe_storage_item(
                item.get("key"), item["value"])
    if key:
        got["items"] = [i for i in got["items"] if i["key"] == key]
    if action == "clear":
        _gates.ENGINE.ask(
            "storage_clear", tool="manage_storage",
            session=sess.session_id, page=record.handle, target=None,
            summary=(f"Clear {got['count']} {kind}Storage entr"
                     f"{'y' if got['count'] == 1 else 'ies'} on "
                     f"{record.handle}?"))
    return {
        "page": record.handle, "session": sess.session_id, "kind": kind,
        "count": got["count"], "items": got["items"],
        "note": ("values are masked by default; only their lengths are "
                 "shown" if not unmask else "values unmasked for this "
                 "audited call"),
    }


async def save_auth_state(
    session: str | None = None,
    path: str | None = None,
) -> dict:
    """Write the session's authentication state (cookies and origin
    storage) to a file, so a login done once can be reused across runs
    without the credentials ever passing through the model's context. This
    is the sanctioned answer to a login wall: hand off, let the human sign
    in, then save the state here. Returns the saved path and a count of
    what was written, never the values. The file lands in the scoped
    downloads directory unless a path is named, checked against
    KS4WEB_ALLOWED_ROOTS, and it holds real credentials, so it belongs
    somewhere the sandbox governs. The file records when its earliest
    authentication cookie expires, and a load whose login has run out or is
    about to says so in one line.
    """
    import json
    sess = common.session_of(session)
    # The engine tag in the name (field finding U17): a directory holding a
    # Chromium file and a Firefox file wants to say which is which, and the
    # cross-engine load question the field log raised is unanswerable when
    # both are called auth_<timestamp>.
    out = path or str(common.downloads_dir()
                      / f"auth_{sess.spec.engine}_{common.stamp()}.json")
    # Union wave: ONE resolution for every output path (fuzzer class 4).
    # `~`, `%TEMP%`, and a relative path were echoed back unresolved here
    # too, and this is the receipt a caller quotes into load_auth_state.
    checked = str(common.resolve_out_path(out, "save auth state"))
    try:
        state = await sess.context.storage_state(path=checked)
    except OSError as exc:
        raise common.write_failed(Path(checked), "save auth state",
                                  exc) from exc
    n_cookies = len(state.get("cookies", []))
    n_origins = len(state.get("origins", []))
    # EXPIRY, recorded in the file at save time (field finding U10, asked
    # twice). Playwright has already written the file; this rewrites it with
    # one extra top-level key, which nothing in the load path reads as a
    # cookie, so the file still loads anywhere a storage_state file loads.
    expiry = common.auth_expiry(state.get("cookies", []))
    state["ks4web"] = {
        "saved_at": time.time(),
        "engine": sess.spec.engine,
        "auth_expiry": expiry,
    }
    common.write_text_file(checked, json.dumps(state), "save auth state")
    # The session remembers the save, so close can say "saved earlier" (field
    # finding 41) instead of contradicting a save made minutes ago.
    sess.record_auth_save(checked)
    warning = common.expiry_note(expiry)
    return {
        "session": sess.session_id, "saved_to": checked,
        "cookies_saved": n_cookies, "origins_saved": n_origins,
        "auth_expiry": _expiry_report(expiry),
        **({"warnings": [warning]} if warning else {}),
        "note": ("this file holds real session credentials; it was written "
                 "to a sandbox-checked path and its values never entered "
                 "the transcript. Reuse it with load_auth_state."),
    }


def _expiry_report(expiry: dict | None) -> str:
    """The expiry fact, in words, whether or not it is worth a warning."""
    if not expiry:
        return ("no authentication cookie in this state carries an expiry "
                "date, so there is nothing to age out")
    if "expires" not in expiry:
        return (f'{expiry["session_cookies"]} authentication cookie(s) are '
                f'session cookies with no expiry date of their own')
    when = time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.localtime(expiry["expires"]))
    # Quoted, capped, and attributed to the site (gauntlet 2 M2). This line
    # sits beside a note stating that credential VALUES never entered the
    # transcript, and until 2026-09-06 the NAME rode into it raw, unbounded,
    # in the server's own voice. Cookie names are attacker-controlled on any
    # page the agent visits.
    return (f'the earliest authentication cookie (name as set by the site: '
            f'{_credentials.quoted_name(expiry["name"])}) expires {when}'
            + (f'; {expiry["session_cookies"]} more are session cookies with '
               f'no expiry date' if expiry.get("session_cookies") else ''))


async def load_auth_state(
    session: str | None = None,
    path: str = "",
) -> dict:
    """Load a previously saved authentication state file into the session,
    so a login captured in an earlier run is restored without any
    credential passing through the model. The file is read from a
    sandbox-checked path, and because loading credentials into a live
    session is consequential it is a gated action that fails closed until a
    human confirms. Cookies apply immediately; per-origin storage is
    applied on the next navigation to each origin, which the result states.
    Returns what was loaded, never the values. A file this server wrote
    loads as-is; a hand-built or profile-exported one must carry `expires`
    in SECONDS, since a browser profile may store milliseconds and the
    driver rejects the whole batch over one such cookie. A file whose
    earliest authentication cookie has expired or is close to it says so in
    one line, so a run that is about to fail on a dead login learns it here
    rather than three navigations later. Client note as of
    2026-09:
    the confirmation prompt displays in Claude Desktop and Claude Code, and
    the claude.ai web client does not display it yet, so this call cannot
    complete there and refuses instead of loading credentials unconfirmed.
    """
    import json
    if not path:
        raise BadParams(
            "load_auth_state needs the path to a state file previously "
            "written by save_auth_state.")
    sess = common.session_of(session)
    checked = sandbox.check_path(path, "load auth state")
    _gates.ENGINE.ask(
        "storage_load", tool="load_auth_state", session=sess.session_id,
        page=None, target=None,
        summary=f"Load saved authentication state from {checked} into "
                f"session {sess.session_id}? This restores a real login.")
    # Fails closed above; the code below runs only through a redeemed gate
    # (Phase 6 wiring). Kept complete so the tool is whole when that lands.
    try:
        data = json.loads(
            sandbox.check_path(checked, "read auth state") and
            open(checked, encoding="utf-8").read())
    except Exception as exc:
        raise BadParams(
            f"could not read the state file {checked}: "
            f"{type(exc).__name__}.") from exc
    cookies = data.get("cookies", [])
    if cookies:
        try:
            await sess.context.add_cookies(cookies)
        except Exception as exc:
            # Names the file, the offending cookie, and the units. The
            # generic BAD_PARAMS this used to raise carried a hint about
            # location objects and refs (ship-route test, 2026-09-06).
            raise common.auth_file_refusal(checked, cookies, exc) from exc
    for c in cookies:
        _credentials.VAULT.observe_cookie(c)
    # Computed from the cookies actually present rather than read out of the
    # block save_auth_state writes, so a file written before that block
    # existed, exported from a profile, or edited by hand gets the same
    # warning. The block is the file describing itself; this is the truth.
    expiry = common.auth_expiry(cookies)
    warning = common.expiry_note(expiry)
    return {
        "session": sess.session_id, "loaded_from": checked,
        "cookies_loaded": len(cookies),
        "origins_pending": len(data.get("origins", [])),
        "auth_expiry": _expiry_report(expiry),
        **({"warnings": [warning]} if warning else {}),
        "saved_by": data.get("ks4web") or None,
        "note": ("cookies are active now; per-origin localStorage applies "
                 "on the next navigation to each origin"),
    }


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (manage_cookies, manage_storage, save_auth_state, load_auth_state)
