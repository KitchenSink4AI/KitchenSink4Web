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


def fingerprint(token) -> str:
    """What the audit trail records in place of a token: enough to tie two
    rows about the same token together, useless for replay."""
    if not isinstance(token, str) or not token:
        return "<handle token, absent>"
    return (f"<handle token, {len(token)} chars, "
            f"sha256 {digest(token)[:8]}>")


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


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
        now = time.time()
        records = [r for r in self._load()
                   if now <= float(r.get("expires_at", 0)) + TOMB_GRACE_S]
        self._records = records

    # ------------------------------------------------------------ minting

    def mint(self, session_id: str, receipt: dict, note: str | None,
             expires_minutes: int) -> dict:
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
            "receipt": receipt,
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
                and float(r.get("expires_at", 0)) > now
                and r.get("minted_by_pid") == os.getpid()]
        if not live:
            return None
        return {"outstanding": len(live),
                "soonest_expiry": _iso(min(float(r["expires_at"])
                                           for r in live))}


#: The process store. `ops/lite.py` mints and redeems against it.
STORE = HandleStore()
