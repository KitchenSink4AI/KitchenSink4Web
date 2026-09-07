"""The learned lane database: which browser lane a site actually served.

KS4Web has three practical browser lanes and no universally safe one. A site
that turns away automated Chromium often serves Firefox, and until now the
only thing the product could say about that was a hardcoded guess in one
refusal sentence. This module replaces the guess with a measurement taken on
THIS machine.

**It ships empty.** There is no starter database, no bundled seed file, and no
measured host list inside the wheel. KS4Web ships capabilities and formats,
never managed data (author ruling, 2026-09-07): every row in this store was
produced by a request this machine made. That is also why nothing here phones
home, downloads a list, or reads one out of the package.

**What it learns from.** Only outcomes that prove a request reached a server
and that describe the LANE rather than the account, the network, or the
moment: a clean navigation, a wall refusal, and a connection-level drop. A
login wall is account state. A 429 is temporal and identical on every lane. A
DNS failure is this machine's problem. A timeout is ambiguous, and a wrong
`dropped` on a good lane is the expensive error. All four write nothing, and
the table in `record()` is the whole contract.

**It is a browsing record, so it is stored like one.** Hostnames, a lane key,
three integer counts, one verdict word, and dates at DAY resolution. No paths,
no query strings, no URLs, no titles, no times of day, no per-visit rows.
Intranet names, IP literals, single-label hosts, and anything on a
non-standard port are never written at all, because a corporate hostname is
the most sensitive thing this feature could accidentally collect and the rule
that keeps it out has to be mechanical rather than careful.

**It advises; it does not switch.** `resolve()`'s "never degrade silently" and
`recommended_lane()`'s "nothing switches lanes on its own" both still hold. A
lane is a browser process with its own profile, cookies, and capability table,
so switching an open session would log the user out in the name of being
helpful. The one exception is the initial choice at session birth, where there
is nothing to lose, and it is gated separately.

Nothing in this module is evasion. It records which honest lane a site served
and reports the date it did.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path

#: Same env var the journal and the audit trail use. Duplicated rather than
#: imported for the same reason `policy/audit.py` duplicates it: the packages
#: keep a one-direction dependency and this constant is not worth a coupling.
STATE_DIR = Path(
    os.environ.get("KS4WEB_STATE_DIR")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ks4web")
)

DB_NAME = "lanes.json"

#: The schema this build writes. A file carrying a HIGHER number is read and
#: never rewritten: destroying a future format because an older build did not
#: recognize it is worse than not learning for one session.
SCHEMA = 1

#: The closed lane-key vocabulary. Verdicts do not generalize by channel name
#: (`B(moz-firefox)` is one machine's label), they generalize by what a site
#: can observe: the engine, the automation backend, and whether the window is
#: headless, which on Chromium is the block vector itself. Anything outside
#: this set is dropped on load and refused on write.
LANE_KEYS: frozenset[str] = frozenset({
    "chromium:cdp:headless", "chromium:cdp:headed",
    "firefox:juggler:headless", "firefox:juggler:headed",
    "firefox:bidi:headless", "firefox:bidi:headed",
    "webkit:wk:headless", "webkit:wk:headed",
})

#: The three outcomes that are ever recorded.
OUTCOMES: tuple[str, ...] = ("ok", "blocked", "dropped")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HOSTNAME = re.compile(r"^[a-z0-9.-]{1,253}$")

#: Multi-label public suffixes, used for exactly two jobs: stopping the upward
#: lookup walk at the registrable domain, and answering "is this a public host
#: at all" for the privacy filter. A small built-in table rather than a public
#: suffix list dependency, which the dependency ledger's rule is not worth
#: breaking for: a wrong answer here costs one missed fallback lookup and
#: never a wrong verdict.
_MULTI_SUFFIXES: frozenset[str] = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "net.uk", "sch.uk", "me.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp", "lg.jp",
    "co.kr", "or.kr", "ne.kr", "re.kr", "pe.kr", "go.kr", "ac.kr",
    "com.br", "net.br", "org.br", "gov.br", "edu.br",
    "co.in", "net.in", "org.in", "gov.in", "ac.in", "edu.in",
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "co.za", "org.za", "net.za", "gov.za", "ac.za",
    "com.mx", "com.ar", "com.tr", "com.sg", "com.hk", "com.tw",
    "com.my", "com.ph", "com.vn", "com.pk", "com.ua", "com.pl",
    "co.nz", "net.nz", "org.nz", "govt.nz", "ac.nz",
    "co.il", "org.il", "ac.il", "gov.il",
    "com.es", "com.it", "co.id", "or.id", "go.id",
})

#: Host suffixes that name a private network by convention. Never recorded.
_PRIVATE_SUFFIXES: tuple[str, ...] = (
    ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp",
    ".localdomain", ".test", ".invalid", ".example", ".onion",
)

#: Host names that are private outright.
_PRIVATE_EXACT: frozenset[str] = frozenset({
    "localhost", "localhost.localdomain", "local", "ip6-localhost",
})


# ------------------------------------------------------------------ settings


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def _int_env(name: str, default: int, floor: int = 1) -> int:
    try:
        return max(floor, int(_env(name, str(default))))
    except ValueError:
        return default


def ttl_days() -> int:
    return _int_env("KS4WEB_LANE_DB_TTL_DAYS", 60)


def decay_days() -> int:
    return _int_env("KS4WEB_LANE_DB_DECAY_DAYS", 30)


def max_hosts() -> int:
    return _int_env("KS4WEB_LANE_DB_MAX_HOSTS", 5000)


def max_bytes() -> int:
    return _int_env("KS4WEB_LANE_DB_MAX_BYTES", 8 * 1024 * 1024)


def flush_seconds() -> float:
    try:
        return max(0.0, float(_env("KS4WEB_LANE_DB_FLUSH_S", "5")))
    except ValueError:
        return 5.0


def autopick_enabled() -> bool:
    return _env("KS4WEB_LANE_AUTOPICK", "1").lower() \
        not in ("0", "false", "off", "no")


#: The three settings of the learning switch, and what each one does.
MODES: tuple[str, ...] = ("learn", "read", "off")


def mode() -> str:
    """`learn` (default), `read`, or `off`, with read-only grade forced.

    An UNRECOGNIZED value resolves to `off` rather than to the default. This
    is the one place where a typo does not become a loud refusal, because the
    refusal would have to fire inside `navigate` and a lane database must
    never fail a navigation. Resolving the wrong way costs a user their
    learning; resolving the other wrong way collects a browsing record from
    someone who was trying to switch it off. The mistake is named in the
    degraded note instead."""
    raw = _env("KS4WEB_LANE_DB", "").lower()
    if not raw:
        return _readonly_forced("learn")
    if raw in MODES:
        return _readonly_forced(raw)
    if raw in ("1", "true", "on", "yes"):
        return _readonly_forced("learn")
    if raw in ("0", "false", "no"):
        return "off"
    _note(f"KS4WEB_LANE_DB={raw!r} is not one of {list(MODES)}, so the lane "
          f"database is off for this run rather than defaulting to learning.")
    return "off"


def _readonly_forced(want: str) -> str:
    """A read-only server grade never learns. A deployment whose promise is
    that it does not act, quietly accumulating a record of which sites the
    machine visited, would be contradicting the grade in its own state
    directory."""
    if want != "learn":
        return want
    try:
        from ..policy import readonly
        if readonly.active():
            return "read"
    except Exception:
        pass
    return want


# ------------------------------------------------------------- the one note


_lock = threading.RLock()
_pending_note: str | None = None


def _note(text: str) -> None:
    """A degraded-state fact, carried once and then cleared.

    Every operation in this module is wrapped so it cannot raise into a tool
    call, which means a failure has to surface somewhere or it never surfaces
    at all. It rides in the next result that asks for it."""
    global _pending_note
    with _lock:
        if _pending_note is None:
            _pending_note = text


def take_note() -> str | None:
    """The pending degraded note, cleared as it is taken."""
    global _pending_note
    with _lock:
        note, _pending_note = _pending_note, None
        return note


# ------------------------------------------------------------------- hosts


def _today() -> str:
    return date.today().isoformat()


def _days_since(stamp: str | None) -> int | None:
    if not stamp or not _DATE.match(stamp):
        return None
    try:
        y, m, d = (int(p) for p in stamp.split("-"))
        return max(0, (date.today() - date(y, m, d)).days)
    except ValueError:
        return None


def _is_ip_literal(host: str) -> bool:
    if host.startswith("[") or ":" in host:
        return True                     # bracketed or bare IPv6
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def public_suffix_split(host: str) -> tuple[str, str] | None:
    """`(registrable_domain, suffix)` for a public host, or None.

    None means the host has no public suffix this build recognizes, which is
    how a single-label intranet name is told apart from a real site."""
    labels = host.split(".")
    if len(labels) < 2:
        return None
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_SUFFIXES:
        if len(labels) < 3:
            return None
        return ".".join(labels[-3:]), last_two
    return last_two, labels[-1]


def storable_host(url_or_host: str | None, *, port: int | None = None
                  ) -> str | None:
    """The key this URL may be stored under, or None to store nothing.

    The privacy filter is mechanical on purpose. Everything below the host is
    discarded here rather than downstream, so no later code path can leak a
    path or a query string into the file: this function is the only thing that
    produces a key, and it produces one from a host name."""
    text = (url_or_host or "").strip()
    if not text:
        return None
    host = text
    scheme = ""
    if "://" in text:
        from urllib.parse import urlparse
        parsed = urlparse(text)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None                 # file:, data:, about:, chrome:
        host = parsed.hostname or ""
        port = parsed.port if port is None else port
    host = host.strip().strip(".").lower()
    if not host or " " in host:
        return None
    if port is not None and port not in (80, 443):
        # A non-standard port is how a development server, a corporate
        # application, and a local fixture all present themselves.
        return None
    if _is_ip_literal(host):
        return None
    if host in _PRIVATE_EXACT or host.endswith(_PRIVATE_SUFFIXES):
        return None
    if not _HOSTNAME.match(host):
        return None
    if public_suffix_split(host) is None:
        return None                     # single-label intranet name
    if host.startswith("www."):
        host = host[4:]
    return host or None


def lookup_chain(host: str) -> list[str]:
    """The keys a lookup for this host may answer from, most specific first.

    The walk goes UP to the registrable domain and never past it, and never
    DOWN: a verdict on `google.com` says nothing about `scholar.google.com`,
    which the probe campaign measured behaving differently on the same lane.
    """
    chain = [host]
    split = public_suffix_split(host)
    if split is None:
        return chain
    registrable = split[0]
    labels = host.split(".")
    while len(labels) > len(registrable.split(".")):
        labels = labels[1:]
        candidate = ".".join(labels)
        if candidate not in chain:
            chain.append(candidate)
    return chain


def siblings(key: str) -> list[str]:
    """Lane keys that may ANSWER for this one when it has no record.

    Same engine, same headless state, different backend. The two Firefox
    lanes agreed on every site in the 2026-09-07 probe campaign, and bundled
    Chromium and an installed Chrome both drive headless CDP behind the same
    `HeadlessChrome` user agent. Engines are never siblings of each other,
    since the engine is the whole variable. A sibling answer is always marked
    and never drives the auto-pick."""
    try:
        engine, backend, headless = key.split(":")
    except ValueError:
        return []
    return sorted(
        other for other in LANE_KEYS
        if other != key and other.startswith(f"{engine}:")
        and other.endswith(f":{headless}")
    )


# ------------------------------------------------------------------ storage


class _Store:
    """The in-memory database and its file.

    Loaded lazily on the first lookup of the process, never at import (the
    package's no-eager-work rule), and flushed on a debounce rather than on
    every navigation."""

    def __init__(self) -> None:
        self.hosts: dict[str, dict] = {}
        #: Every host key this process has ever held, INCLUDING ones the cap
        #: has since evicted. The flush merge reads it to tell "somebody
        #: else's record" from "a record I deliberately dropped".
        self.seen: set[str] = set()
        self.loaded = False
        self.dirty = False
        self.frozen = False         # a newer schema: read, never rewrite
        self.writable = True
        self.last_flush = 0.0
        self.file_schema = SCHEMA

    def reset(self) -> None:
        self.__init__()


_STORE = _Store()


def path() -> Path:
    return STATE_DIR / DB_NAME


def _checked_path() -> Path | None:
    """The database path, or None when the sandbox refuses it.

    An active sandbox that does not contain the state directory disables the
    database rather than failing the tool: a lane hint is not worth a
    refusal."""
    target = path()
    try:
        from ..policy import sandbox
        if sandbox.active():
            sandbox.check_path(target, purpose="lane database")
    except Exception as exc:
        _note(f"the lane database path is outside the configured sandbox "
              f"roots, so nothing is read or written this run "
              f"({type(exc).__name__}).")
        return None
    return target


def _quarantine(target: Path, why: str) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    spoiled = target.with_name(f"lanes.corrupt-{stamp}.json")
    try:
        target.replace(spoiled)
        _note(f"the lane database file could not be read ({why}); it was set "
              f"aside as {spoiled.name} and a fresh one starts from empty. "
              f"Nothing else is affected.")
    except OSError:
        _note(f"the lane database file could not be read ({why}) and could "
              f"not be set aside either, so it is ignored for this run.")


def _coerce_record(raw) -> dict | None:
    """One (host, lane) record, coerced or dropped whole.

    Per-record tolerance, matching `list_workflows`: one bad row never costs
    the whole store. A value that fails its clamp is dropped rather than
    truncated, which is the same doctrine `walls._safe_reference` applies to
    a hostile header."""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for field in ("ok", "blocked", "dropped"):
        value = raw.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if value < 0 or value > 10 ** 9:
            return None
        out[field] = value
    last = raw.get("last")
    if last is not None and last not in OUTCOMES:
        return None
    out["last"] = last
    for field in ("last_ok", "last_bad"):
        stamp = raw.get(field)
        if stamp is None:
            out[field] = None
        elif isinstance(stamp, str) and _DATE.match(stamp):
            out[field] = stamp
        else:
            return None
    for field in ("vendor", "wall", "source"):
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > 120:
            return None
        out[field] = value
    return out


def _coerce_payload(data) -> tuple[dict[str, dict], int] | None:
    if not isinstance(data, dict):
        return None
    schema = data.get("schema")
    if not isinstance(schema, int) or schema < 1:
        return None
    raw_hosts = data.get("hosts")
    if not isinstance(raw_hosts, dict):
        return None
    hosts: dict[str, dict] = {}
    for host, lanes_raw in raw_hosts.items():
        if not isinstance(host, str) or not isinstance(lanes_raw, dict):
            continue
        key = storable_host(host)
        if key is None or key != host.lower():
            continue
        kept: dict[str, dict] = {}
        for lane, record in lanes_raw.items():
            if lane not in LANE_KEYS:
                continue
            coerced = _coerce_record(record)
            if coerced is not None:
                kept[lane] = coerced
        if kept:
            hosts[key] = kept
    return hosts, schema


def _load() -> None:
    store = _STORE
    if store.loaded:
        return
    store.loaded = True
    if mode() == "off":
        return
    target = _checked_path()
    if target is None:
        store.writable = False
        return
    try:
        if target.is_symlink():
            _note("the lane database path is a symlink, so nothing is "
                  "written through it; the database is read-only this run.")
            store.writable = False
        if not target.exists():
            return
        size = target.stat().st_size
        if size > max_bytes():
            _quarantine(target, f"{size} bytes, past the {max_bytes()} cap")
            return
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        try:
            if target.exists():
                _quarantine(target, type(exc).__name__)
        except OSError:
            pass
        return
    coerced = _coerce_payload(data)
    if coerced is None:
        _quarantine(target, "the file is not a lane database")
        return
    hosts, schema = coerced
    store.hosts = hosts
    store.seen.update(hosts)
    store.file_schema = schema
    if schema > SCHEMA:
        store.frozen = True
        _note(f"the lane database on disk is schema {schema} and this build "
              f"writes schema {SCHEMA}, so it is read and never rewritten. "
              f"Nothing is learned this run and nothing is lost.")


def _decayed(record: dict) -> dict:
    """Halve the counts of a record whose evidence has aged past the decay
    bound, before a new verdict is applied to it. Old evidence fades without
    the file having to hold a per-event history."""
    latest = _latest_date(record)
    age = _days_since(latest)
    if age is None or age <= decay_days():
        return record
    for field in ("ok", "blocked", "dropped"):
        record[field] = record[field] // 2
    return record


def _latest_date(record: dict) -> str | None:
    stamps = [s for s in (record.get("last_ok"), record.get("last_bad")) if s]
    return max(stamps) if stamps else None


def _blank() -> dict:
    return {"ok": 0, "blocked": 0, "dropped": 0, "last": None,
            "last_ok": None, "last_bad": None}


def _evict_if_full() -> None:
    """At the cap, the hosts with the oldest evidence go first. A learned
    database that can fill a disk is the audit trail's rotation problem again
    and gets the same answer."""
    cap = max_hosts()
    if len(_STORE.hosts) <= cap:
        return
    def oldest(item):
        host, lanes_ = item
        stamps = [_latest_date(r) for r in lanes_.values()]
        return min([s for s in stamps if s] or ["0000-00-00"])
    ordered = sorted(_STORE.hosts.items(), key=oldest)
    for host, _ in ordered[:len(_STORE.hosts) - cap]:
        _STORE.hosts.pop(host, None)


# --------------------------------------------------------------- public API


def record(url_or_host: str | None, lane_key: str, outcome: str, *,
           vendor: str | None = None, wall: str | None = None) -> bool:
    """Record ONE observed outcome. Returns whether anything was stored.

    Wrapped so it cannot raise: a lane database that can fail a navigation
    would be worse than no lane database."""
    try:
        with _lock:
            if mode() != "learn":
                return False
            if outcome not in OUTCOMES or lane_key not in LANE_KEYS:
                return False
            host = storable_host(url_or_host)
            if host is None:
                return False
            _load()
            if _STORE.frozen:
                return False
            lanes_ = _STORE.hosts.setdefault(host, {})
            _STORE.seen.add(host)
            entry = _decayed(lanes_.get(lane_key) or _blank())
            entry[outcome] += 1
            entry["last"] = outcome
            if outcome == "ok":
                entry["last_ok"] = _today()
            else:
                entry["last_bad"] = _today()
            if vendor and isinstance(vendor, str):
                entry["vendor"] = vendor[:120]
            if wall and isinstance(wall, str):
                entry["wall"] = wall[:120]
            entry.pop("source", None)   # a local observation is not imported
            lanes_[lane_key] = entry
            _evict_if_full()
            _STORE.dirty = True
            _arm_exit_flush()
        maybe_flush()
        return True
    except Exception as exc:            # never into a tool call
        _note(f"the lane database could not record an outcome "
              f"({type(exc).__name__}); nothing else is affected.")
        return False


def belief(record_: dict | None) -> str:
    """`believed_good`, `believed_bad`, or `unknown`.

    One good observation always clears a warning: a site that stopped
    blocking you must stop nagging you. The counts keep the history visible
    for anyone who looks."""
    if not record_:
        return "unknown"
    last = record_.get("last")
    if last == "ok":
        return "believed_good"
    if last in ("blocked", "dropped"):
        bad = record_.get("blocked", 0) + record_.get("dropped", 0)
        if bad >= record_.get("ok", 0):
            return "believed_bad"
    return "unknown"


def lookup(url_or_host: str | None, lane_key: str) -> dict | None:
    """What is known about this lane on this host, or None.

    The answer names WHICH key answered, because a parent-domain answer and a
    sibling-lane answer are weaker facts than a direct hit and reporting them
    as the same fact would be the silent degrade this product argues
    against."""
    try:
        with _lock:
            if mode() == "off":
                return None
            host = storable_host(url_or_host)
            if host is None or lane_key not in LANE_KEYS:
                return None
            _load()
            for candidate in lookup_chain(host):
                lanes_ = _STORE.hosts.get(candidate)
                if not lanes_:
                    continue
                direct = lanes_.get(lane_key)
                if direct:
                    return _view(candidate, lane_key, direct,
                                 host_asked=host, sibling=None)
                for other in siblings(lane_key):
                    got = lanes_.get(other)
                    if got:
                        return _view(candidate, lane_key, got,
                                     host_asked=host, sibling=other)
            return None
    except Exception as exc:
        _note(f"the lane database could not be read "
              f"({type(exc).__name__}); nothing else is affected.")
        return None


def _view(host_key: str, lane_key: str, entry: dict, *,
          host_asked: str, sibling: str | None) -> dict:
    latest = _latest_date(entry)
    age = _days_since(latest)
    return {
        "host": host_key,
        "exact_host": host_key == host_asked,
        "lane_key": lane_key,
        "answered_by": sibling or lane_key,
        "from_sibling_lane": sibling is not None,
        "belief": belief(entry),
        "ok": entry.get("ok", 0),
        "blocked": entry.get("blocked", 0),
        "dropped": entry.get("dropped", 0),
        "last": entry.get("last"),
        "last_ok": entry.get("last_ok"),
        "last_bad": entry.get("last_bad"),
        "measured_days_ago": age,
        "stale": age is not None and age > ttl_days(),
        **({"vendor": entry["vendor"]} if entry.get("vendor") else {}),
        **({"wall": entry["wall"]} if entry.get("wall") else {}),
        **({"source": entry["source"]} if entry.get("source") else {}),
    }


def good_lanes(url_or_host: str | None) -> list[dict]:
    """Every lane believed to read this host, freshest evidence first.

    Direct hits only: a sibling answer advises and never drives a choice."""
    out: list[dict] = []
    for key in sorted(LANE_KEYS):
        got = lookup(url_or_host, key)
        if got and not got["from_sibling_lane"] \
                and got["belief"] == "believed_good":
            out.append(got)
    out.sort(key=lambda r: (r["measured_days_ago"] is None,
                            r["measured_days_ago"] or 0))
    return out


def all_lanes_failed(url_or_host: str | None) -> bool:
    """True when this host has records and every one of them is bad.

    The case where naming another lane would waste the caller's turns."""
    known = report(url_or_host).get("lanes") or []
    if not known:
        return False
    return all(row["belief"] == "believed_bad" for row in known)


def report(url_or_host: str | None) -> dict:
    """Everything known about one host, across every lane key."""
    try:
        with _lock:
            if mode() == "off":
                return {"host": None, "learning": "off", "lanes": []}
            host = storable_host(url_or_host)
            if host is None:
                return {"host": None, "learning": mode(), "lanes": [],
                        "recordable": False, "recorded": False}
            _load()
            rows: list[dict] = []
            for key in sorted(LANE_KEYS):
                for candidate in lookup_chain(host):
                    entry = (_STORE.hosts.get(candidate) or {}).get(key)
                    if entry:
                        rows.append(_view(candidate, key, entry,
                                          host_asked=host, sibling=None))
                        break
            # TWO FACTS, AND THE WORD USED TO CARRY ONLY THE WRONG ONE.
            # `recorded: true` meant "this host is one this database is
            # allowed to store", and it sat beside `lanes: []` on a host the
            # database has never seen. On a surface whose whole job is
            # answering "what do you hold on me", that is the reading nobody
            # takes. (Verify round V-11.)
            return {"host": host, "learning": mode(), "lanes": rows,
                    "recordable": True, "recorded": bool(rows)}
    except Exception as exc:
        _note(f"the lane database could not be read "
              f"({type(exc).__name__}); nothing else is affected.")
        return {"host": None, "learning": "unavailable", "lanes": []}


def status() -> dict:
    """The one-line summary the session status block carries."""
    try:
        with _lock:
            current = mode()
            if current == "off":
                return {"learning": "off", "hosts": 0, "file": None}
            _load()
            target = _checked_path()
            return {
                "learning": "read-only" if (current == "read"
                                            or _STORE.frozen) else "learning",
                "hosts": len(_STORE.hosts),
                "file": str(target) if target else None,
                "file_exists": bool(target and target.exists()),
                "ttl_days": ttl_days(),
                "auto_pick": autopick_enabled(),
                "stores": ("hostnames, one lane key, three counts, one "
                           "verdict word, and dates at day resolution"),
                "never_stores": ("paths, query strings, URLs, page titles, "
                                 "times of day, per-visit rows, and any "
                                 "intranet, IP-literal, or non-standard-port "
                                 "host"),
                "erase": "manage_session(action='lanes', op='forget', all=True)",
            }
    except Exception:
        return {"learning": "unavailable", "hosts": 0, "file": None}


def forget(*, site: str | None = None, source: str | None = None,
           all_records: bool = False) -> dict:
    """Erase part or all of the learned record.

    A one-call, no-ceremony way to erase the browsing record is part of
    taking the privacy claim seriously, so this deletes rather than
    tombstones."""
    with _lock:
        _load()
        if all_records:
            count = len(_STORE.hosts)
            _STORE.hosts = {}
            _STORE.dirty = True
            target = _checked_path()
            removed = False
            try:
                if target and target.exists():
                    target.unlink()
                    removed = True
            except OSError as exc:
                _note(f"the lane database file could not be deleted "
                      f"({type(exc).__name__}); its contents were cleared in "
                      f"memory and the file is rewritten empty.")
            _STORE.dirty = not removed
            return {"forgot": "all", "hosts_removed": count,
                    "file_deleted": removed}
        if site:
            host = storable_host(site)
            gone = _STORE.hosts.pop(host, None) if host else None
            _STORE.dirty = _STORE.dirty or gone is not None
            return {"forgot": host, "hosts_removed": 1 if gone else 0}
        if source:
            removed = 0
            for host in list(_STORE.hosts):
                lanes_ = _STORE.hosts[host]
                for key in list(lanes_):
                    if lanes_[key].get("source") == source:
                        lanes_.pop(key)
                        removed += 1
                if not lanes_:
                    _STORE.hosts.pop(host, None)
            _STORE.dirty = _STORE.dirty or removed > 0
            return {"forgot": source, "records_removed": removed}
    return {"forgot": None, "hosts_removed": 0}


# ----------------------------------------------------------------- sharing


EXPORT_FORMAT = "ks4web-lane-db"


def export(*, scope: str = "blocked-only", min_observations: int = 1) -> dict:
    """The shareable payload. Hostnames and dates, nothing else.

    Default scope is blocked-only: "these sites refuse automated browsers" is
    the shareable public good, and a block list says far less about a person
    than a list of sites they successfully used."""
    with _lock:
        _load()
        hosts: dict[str, dict] = {}
        for host, lanes_ in _STORE.hosts.items():
            if storable_host(host) is None:
                continue            # belt and braces on the privacy rule
            kept = {}
            for key, entry in lanes_.items():
                total = (entry.get("ok", 0) + entry.get("blocked", 0)
                         + entry.get("dropped", 0))
                if total < max(1, min_observations):
                    continue
                bad = entry.get("blocked", 0) + entry.get("dropped", 0)
                if scope != "all" and bad == 0:
                    continue
                kept[key] = {k: v for k, v in entry.items()
                             if k in ("ok", "blocked", "dropped", "last",
                                      "last_ok", "last_bad", "vendor", "wall")}
            if kept:
                hosts[host] = kept
        return {"format": EXPORT_FORMAT, "schema": SCHEMA,
                "exported": _today(), "scope": scope,
                "lane_keys": sorted(LANE_KEYS), "hosts": hosts}


def import_payload(data, *, label: str = "imported",
                   dry_run: bool = True) -> dict:
    """Merge a shared database. Dry run by default.

    Counts add, the newer date wins `last`, and a LOCAL observation outranks
    an imported one on a same-date tie, because a block is partly local: IP
    reputation, geography, and the user's own account state all move it."""
    coerced = _coerce_payload(data) if isinstance(data, dict) else None
    if coerced is None:
        return {"merged": False, "error": "not a lane database payload"}
    incoming, _schema = coerced
    with _lock:
        _load()
        new_hosts, conflicts, records = 0, 0, 0
        for host, lanes_ in incoming.items():
            mine = _STORE.hosts.get(host)
            if mine is None:
                new_hosts += 1
            for key, entry in lanes_.items():
                records += 1
                existing = (mine or {}).get(key)
                if existing and existing.get("last") != entry.get("last"):
                    conflicts += 1
                if dry_run:
                    continue
                merged = existing or _blank()
                for field in ("ok", "blocked", "dropped"):
                    merged[field] = merged.get(field, 0) + entry.get(field, 0)
                theirs = _latest_date(entry)
                ours = _latest_date(merged)
                if ours is None or (theirs is not None and theirs > ours):
                    merged["last"] = entry.get("last")
                for field in ("last_ok", "last_bad"):
                    stamps = [s for s in (merged.get(field), entry.get(field))
                              if s]
                    merged[field] = max(stamps) if stamps else None
                for field in ("vendor", "wall"):
                    if entry.get(field) and not merged.get(field):
                        merged[field] = entry[field]
                if existing is None:
                    merged["source"] = f"imported:{label}"
                _STORE.hosts.setdefault(host, {})[key] = merged
        if not dry_run:
            _STORE.dirty = True
            _evict_if_full()
        return {"merged": not dry_run, "dry_run": dry_run,
                "new_hosts": new_hosts, "records": records,
                "conflicts": conflicts, "label": f"imported:{label}"}


# ------------------------------------------------------------------- flush


def maybe_flush(force: bool = False) -> bool:
    """Write the file, at most once per debounce window.

    A per-navigation disk write is not acceptable on a hot path, and a
    last-write-wins flush would silently lose another KS4Web process's
    learning: several of them share one state directory, so the flush
    re-reads and merges before it replaces."""
    try:
        with _lock:
            store = _STORE
            if not store.dirty or store.frozen or not store.writable:
                return False
            if mode() != "learn":
                return False
            now = time.monotonic()
            if not force and (now - store.last_flush) < flush_seconds():
                return False
            target = _checked_path()
            if target is None:
                return False
            merged = dict(store.hosts)
            try:
                if target.exists() and target.stat().st_size <= max_bytes():
                    on_disk = _coerce_payload(
                        json.loads(target.read_text(encoding="utf-8")))
                    if on_disk is not None:
                        merged = _merge_for_flush(on_disk[0], store.hosts)
            except (OSError, ValueError, UnicodeDecodeError):
                pass                # a spoiled file is replaced, not merged
            store.hosts = merged
            _evict_if_full()
            merged = store.hosts
            payload = {"schema": SCHEMA, "updated": _today(), "hosts": merged}
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(target)
            store.dirty = False
            store.last_flush = now
            return True
    except OSError as exc:
        _STORE.writable = False
        _note(f"the lane database could not be written "
              f"({type(exc).__name__}), so nothing is learned this run. "
              f"Reads and navigation are unaffected.")
        return False
    except Exception as exc:
        _note(f"the lane database could not be written "
              f"({type(exc).__name__}); nothing else is affected.")
        return False


def _merge_for_flush(on_disk: dict[str, dict],
                     mine: dict[str, dict]) -> dict[str, dict]:
    """Carry over what ANOTHER process learned; never re-import my own past.

    The rule is per host, and it is deliberately not an arithmetic merge. A
    host this process has held in memory is a host whose current state IS the
    truth as far as this process is concerned: its counts already include what
    was loaded from the file, minus whatever decay and eviction have since
    done to them. Adding the file's copy back would undo both, which is
    exactly what the first version of this function did (a decayed record
    sprang back to its old count on the very next flush).

    A host this process has never seen belongs to somebody else's session
    sharing the same state directory, and it is copied through untouched.
    That is what the merge is for."""
    seen = _STORE.seen
    out = {host: {k: dict(v) for k, v in lanes_.items()}
           for host, lanes_ in on_disk.items() if host not in seen}
    for host, lanes_ in mine.items():
        out[host] = {k: dict(v) for k, v in lanes_.items()}
    return out


def flush() -> bool:
    """Force the pending write. Called on session close and at exit."""
    return maybe_flush(force=True)


_exit_armed = False


def _arm_exit_flush() -> None:
    """Register the exit flush once, on the first write rather than at import.

    The debounce means a short-lived process can learn something and end
    before the window elapses. A server nobody asks to browse still registers
    nothing."""
    global _exit_armed
    if _exit_armed:
        return
    _exit_armed = True
    try:
        import atexit
        atexit.register(flush)
    except Exception:
        pass


def reset_for_tests() -> None:
    """Drop the in-memory state. The suite's only supported reset."""
    global _pending_note
    with _lock:
        _STORE.reset()
        _pending_note = None
