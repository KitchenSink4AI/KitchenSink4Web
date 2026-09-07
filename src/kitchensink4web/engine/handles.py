"""Session handle transfer: the token store behind export_handle and
import_handle (feature #15).

WHAT THIS FEATURE ACTUALLY IS. Sessions live in the PROCESS, not in a
conversation: `MANAGER` is a module-level singleton and
`manage_session(action='status')` already lists every session any
conversation opened. So a second conversation reaching an existing browser
is not a capability that needs building; it is the state of things. What
does not exist is a way to do it DELIBERATELY, with a receipt of what is
being picked up, and with a refusal that says which of the several ways a
session can be gone actually happened. The refusal is the feature.

Three properties this module holds, and each one is pinned:

- **The token is never stored in the clear.** The file holds
  `sha256(token)` the way a password file holds a digest, so a leaked
  `handles.json` cannot be replayed. Lookup hashes what it was given.
- **The token is deliberately NOT vaulted** (`policy/credentials`). The
  vault masks every observed secret in every outgoing payload, and the
  export payload is the one place the token has to be readable. Its
  confidentiality comes from the hash at rest, the short TTL, the single
  use, and the audit denylist in `policy/audit.py`, not from redaction.
  Vaulting it would break export silently, which is why pin H-3 exists.
- **The receipt on disk holds what the reconciliation needs and nothing
  else** (V-06, fix wave 2026-09-08). `lanedb.status()` ships a promise
  about this state directory as a shipped string: it never stores "paths,
  query strings, URLs, page titles, times of day, per-visit rows". The lane
  database honours that exactly; `handles.json` did not, because the export
  receipt carried every open page's full URL, query string and all, plus a
  filesystem path to a saved credential state. Only three receipt fields are
  read on the import side, and the URL is read only for an equality test, so
  the stored receipt now carries a DIGEST of each page's URL instead of the
  URL. The salt is minted per process and never written anywhere, which
  costs nothing: a token minted by another process is never honoured, so a
  digest that only this process can recompute is a digest for every reader
  that was ever going to read it.

- **A record outlives its usefulness on purpose.** Consumed and expired
  records are kept until `expires + TOMB_GRACE_S` so import can say "this
  was already used at 20:14" instead of "unknown token", and a record
  minted by a different process is kept so import can say WHICH process
  minted it. A foreign record is never honoured, only explained.

The file is local process state, not a document. Nothing about it is
portable across machines and nothing claims to be: the browser a token
refers to dies with the server process that owns it, by job-object
enforcement (`hygiene.ProcessJob`), and that is a safety property rather
than a limitation to work around.

STANDING NOTE FOR ANY FUTURE IDLE SWEEP. Nothing parks or recycles a
session on its own in this build. If that ever changes, a session holding
an unconsumed, unexpired export token must be exempt from RECYCLING for
the token's remaining TTL, or this feature acquires a silent failure the
day the sweep is switched on.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from . import hygiene

#: The prefix makes a token recognisable in a transcript, so a human knows
#: what they are pasting and a malformed-token refusal can say what one
#: looks like without printing a real one.
TOKEN_PREFIX = "ks4web-h-"

#: 32 bytes of `secrets.token_urlsafe` is 43 url-safe characters.
TOKEN_BYTES = 32
TOKEN_BODY_LEN = 43

DEFAULT_TTL_MIN = 60
TTL_MIN_MIN = 1
TTL_MAX_MIN = 1440

#: How long a consumed or expired record is kept so its refusal can be
#: specific rather than generic.
TOMB_GRACE_S = 3600.0

STORE_VERSION = 1


def valid_shape(token) -> bool:
    """Is this the shape of a KS4Web handle token? Shape only: a
    well-shaped token that was never minted is a lookup miss, not an
    argument fault, and the two refusals say different things."""
    if not isinstance(token, str):
        return False
    if not token.startswith(TOKEN_PREFIX):
        return False
    body = token[len(TOKEN_PREFIX):]
    if len(body) != TOKEN_BODY_LEN:
        return False
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return set(body) <= allowed


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


#: Salt for the receipt's URL digests, minted per process and never written
#: to the store. See the module docstring: a record minted by another
#: process is refused on identity grounds before anything in its receipt is
#: read, so nothing outside this process ever needs to recompute one.
_URL_SALT = secrets.token_bytes(16)


def url_digest(url) -> str:
    """The receipt's stand-in for a page URL.

    The import side asks one question of the stored URL, "is the page still
    on the document it was on at export", and an equality test over digests
    answers it exactly. What the digest cannot do is print the URL back,
    which is the point: a path and a query string are what the state
    directory promises never to hold."""
    raw = url if isinstance(url, str) else ""
    return hashlib.sha256(_URL_SALT + raw.encode("utf-8")).hexdigest()


def expiry_of(record: dict) -> float:
    """One record's expiry, as a number, whatever the record says.

    `_load` defends the FILE against corruption and nothing defended a
    RECORD: a hand-edited `expires_at` that is not a number raised an
    uncaught ValueError out of `prune()`, which runs on both the export and
    the import path, so one unreadable row took down the whole feature
    (V-06, fix wave 2026-09-08). A row whose expiry cannot be read is
    treated as long expired, which routes it to the same place a genuinely
    expired row goes: dropped, with import saying "unknown token"."""
    try:
        return float(record.get("expires_at", 0))
    except (TypeError, ValueError):
        return 0.0


def fingerprint(token) -> str:
    """What the audit trail records in place of a token: enough to tie two
    rows about the same token together, useless for replay."""
    if not isinstance(token, str) or not token:
        return "<handle token, absent>"
    return (f"<handle token, {len(token)} chars, "
            f"sha256 {digest(token)[:8]}>")


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def stored_receipt(receipt: dict) -> dict:
    """The part of an export receipt that is worth writing down.

    WHAT THE IMPORT SIDE ACTUALLY READS, measured rather than assumed
    (V-06): `ops/lite._transfer_report` reads `pages[*]["page"]` as its join
    key, `pages[*]["url"]` for one equality test, `pages[*]["live_refs"]`
    for the surviving-refs sentence, and `cookies` for the before-and-after
    line. Nothing reads `lane`, `opened`, `emulation`, `budget`,
    `pages[*]["focused"]`, `pages[*]["parked"]`, or `auth_state_saved_to`.
    That last one is a filesystem path to a saved credential state, and the
    auth-state sentence an import shows comes from the session TOMBSTONE
    (`engine/session.py`), not from here, so it was a credential-adjacent
    path written to disk for no reader at all.

    So this keeps the four fields that are read, digests the URL, and drops
    the rest. A field nobody reads cannot be worth the promise it breaks."""
    pages = []
    for row in receipt.get("pages") or ():
        if not isinstance(row, dict):
            continue
        pages.append({
            "page": row.get("page"),
            "url_sha256": url_digest(row.get("url")),
            "live_refs": row.get("live_refs", 0),
        })
    return {"pages": pages, "cookies": receipt.get("cookies", 0)}


class HandleStore:
    """`STATE_DIR/handles.json`, written with the same atomic idiom the
    owned-PID journal uses (`tmp.write_text` then `tmp.replace`)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._records: list[dict] | None = None

    @property
    def path(self) -> Path:
        return self._path or (hygiene.STATE_DIR / "handles.json")

    # ------------------------------------------------------------ loading

    def reload(self) -> None:
        self._records = None

    def _load(self) -> list[dict]:
        if self._records is not None:
            return self._records
        records: list[dict] = []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            loaded = raw.get("handles")
            if isinstance(loaded, list):
                records = [r for r in loaded if isinstance(r, dict)]
        except (OSError, ValueError):
            # A store this version cannot read is not a reason to refuse a
            # session transfer that has not happened yet. The worst case is
            # a token that reads as unknown, and that refusal is honest.
            records = []
        self._records = records
        return records

    def _flush(self) -> None:
        records = self._load()
        payload = {
            "version": STORE_VERSION,
            "written": _iso(time.time()),
            "written_by_pid": os.getpid(),
            "handles": records,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # The in-memory record still serves this process, which is the
            # only process a token can be redeemed in anyway.
            pass

    # ------------------------------------------------------------ pruning

    def prune(self) -> None:
        """Drop every record past its grace window, ON DISK.

        THE DROP USED TO BE IN MEMORY ONLY (V-06, fix wave 2026-09-08). This
        rewrote `self._records` and never flushed, so a pruned record left
        the file solely as a side effect of the next `_flush()`, which only
        minting and consuming perform. On the common import path, an
        unknown, expired, or already-consumed token, the call RAISES before
        either, so a store full of records nobody can use survived on disk
        indefinitely in a process that only ever imports. A record's whole
        reason to exist is that a refusal can be specific about it; once
        that is over, it should leave the file that holds it."""
        now = time.time()
        records = [r for r in self._load()
                   if now <= expiry_of(r) + TOMB_GRACE_S]
        if len(records) == len(self._records or []):
            return
        self._records = records
        self._flush()

    # ------------------------------------------------------------ minting

    def mint(self, session_id: str, receipt: dict, note: str | None,
             expires_minutes: int) -> dict:
        """Mint one token and write its record.

        The receipt passed in is the FULL one, which is what the exporting
        conversation gets back in its own response: it is that
        conversation's own session and it may see its own URLs. What is
        written is `stored_receipt`'s reduction of it, and the reduction
        happens here rather than at the call site so that the promise this
        file makes is enforced by the file that makes it."""
        self.prune()
        token = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
        now = time.time()
        record = {
            "token_sha256": digest(token),
            "session": session_id,
            "note": note,
            "minted_at": now,
            "minted": _iso(now),
            "minted_by_pid": os.getpid(),
            "expires_at": now + expires_minutes * 60,
            "expires": _iso(now + expires_minutes * 60),
            "consumed_at": None,
            "receipt": stored_receipt(receipt),
        }
        self._load().append(record)
        self._flush()
        return {"token": token, "record": record}

    # ------------------------------------------------------------ reading

    def find(self, token: str) -> dict | None:
        wanted = digest(token)
        for record in self._load():
            if record.get("token_sha256") == wanted:
                return record
        return None

    def consume(self, record: dict) -> None:
        record["consumed_at"] = time.time()
        record["consumed"] = _iso(record["consumed_at"])
        self._flush()

    def outstanding(self, session_id: str) -> dict | None:
        """Unconsumed, unexpired tokens for one session. An export nobody
        redeemed is a pending intent the user may have forgotten, so the
        status call carries the COUNT and the soonest expiry, never a
        token or a hash."""
        now = time.time()
        live = [r for r in self._load()
                if r.get("session") == session_id
                and r.get("consumed_at") is None
                and expiry_of(r) > now
                and r.get("minted_by_pid") == os.getpid()]
        if not live:
            return None
        return {"outstanding": len(live),
                "soonest_expiry": _iso(min(expiry_of(r) for r in live))}


#: The process store. `ops/lite.py` mints and redeems against it.
STORE = HandleStore()
