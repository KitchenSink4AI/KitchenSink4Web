"""The `network` pack: request inspection, bodies, HAR, routing (DESIGN 2.2).

The strategic row is HAR export: the pattern sophisticated practitioners
already use is capture the traffic, write the API spec, then call the API
directly, and a browser server that helps an agent graduate off the browser
for repeat tasks is aligned with where the users already are.

Recording attaches at SESSION OPEN through the engine's hook seam, so the
log starts when the session does rather than when somebody first asks. The
hook checks its pack is loaded, so an unselected pack records nothing.

Honesty rules specific to this pack:

- **Ad and analytics requests are hidden from listings by default and
  COUNTED**, with `include_analytics=true` to see them; actually blocking
  them at the network level is `set_routing(action='block_ads')`, a
  mutating opt-in. The split is deliberate: `list_requests` is registered
  under read-only mode, so it must not be the thing that changes traffic.
- **Credential-bearing headers are observed into the vault and masked**
  (authorization, cookie, and friends), so a header value can never ride
  out of any payload, this pack's or another's.
- **Request-body READS refuse loudly on Firefox/BiDi** (`LANE_UNSUPPORTED`,
  the measured S4 row): the driver returns None rather than raising there,
  and an explicit refusal beats an empty body that looks like an answer.

Env vars this module adds (for the Q11a ruling): KS4WEB_NETLOG_MAX
(records kept per session, default 2000).
"""

from __future__ import annotations

import json as _json
import os
import time

from urllib.parse import (parse_qsl as _parse_qsl, urlencode as _urlencode,
                          urlparse as _urlparse)

from ..engine import lanes, session as _session
from ..errors import (BadParams, CredentialRefused, LaneUnsupported,
                      NavigationBlocked, TargetNotFound)
from ..policy import budgets as _budgets
from ..policy import credentials as _credentials
from ..policy import engine as _policy
from ..policy import origins as _origins
from . import common

ENV_NETLOG_MAX = "KS4WEB_NETLOG_MAX"

#: Header names whose values are credentials or session material. Observed
#: into the vault BEFORE masking (the DESIGN 5.3 contract), so the
#: serializer catches any later path that would emit them.
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "x-csrf-token", "x-xsrf-token",
})

#: Cookies belong to the storage pack, which gates them (`storage_load`). A
#: second unaudited door into the same asset makes the first door's gate
#: decorative, so this one is refused in every mode and every configuration.
COOKIE_HEADERS = frozenset({"cookie", "set-cookie"})

#: Headers the browser authors. Rewriting them either corrupts the request
#: (`content-length`, `transfer-encoding`) or forges a security signal the
#: server is entitled to trust because the BROWSER wrote it (the `sec-*`
#: family). Refused always; there is no scope and no switch that admits them.
FORBIDDEN_HEADERS = frozenset({
    "host", "content-length", "connection", "transfer-encoding", "upgrade",
    "keep-alive", "te", "trailer", "expect",
})
#: `sec-` only. `proxy-authorization` is a CREDENTIAL, not a forged browser
#: signal, and a prefix rule that swallowed it would send a human to the
#: wrong refusal.
FORBIDDEN_PREFIXES = ("sec-",)

#: Query parameters the curated `preset="tracking"` strips. The same caveat
#: the ad list carries applies word for word: this is a noise filter with an
#: honest count, not a privacy product.
TRACKING_PARAMS = (
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "gclid", "gbraid", "wbraid", "dclid", "fbclid",
    "msclkid", "twclid", "ttclid", "igshid", "mc_cid", "mc_eid", "yclid",
    "_ga", "_gl", "ref_src", "ref_url", "vero_id", "s_kwcid", "icid",
)


def header_class(name) -> str:
    """Classify one request-header NAME: 'cookie', 'forbidden',
    'credential', or 'ordinary'.

    The credential tier seeds from `SENSITIVE_HEADERS` and generalizes
    through `credentials.classify_name`, so a novel name like
    `x-session-key` classifies without a list edit.

    `user-agent` is ordinary and stays ordinary. It is practically a
    bot-evasion lever, and the standing position (BUILD_LOG 2026-09-06) is
    lane steering, no UA patching: changing it does not defeat bot detection
    and the supported answer to a bot wall is a different lane. Silently
    special-casing it here would be a safety claim this server cannot back."""
    text = ("" if name is None else str(name)).strip().lower()
    if not text:
        return "ordinary"
    if text in COOKIE_HEADERS:
        return "cookie"
    if text in FORBIDDEN_HEADERS or text.startswith(FORBIDDEN_PREFIXES):
        return "forbidden"
    if text in SENSITIVE_HEADERS:
        return "credential"
    if _credentials.classify_name(text) == "credential":
        return "credential"
    return "ordinary"

#: The curated ad/analytics domain list. Deliberately small and readable:
#: this is a noise filter with an honest count, not a privacy product.
ANALYTICS_DOMAINS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagmanager.com", "adsystem.",
    "adservice.", "adnxs.com", "criteo.", "taboola.com", "outbrain.com",
    "scorecardresearch.com", "quantserve.com", "hotjar.com", "mixpanel.com",
    "segment.com", "segment.io", "amplitude.com", "facebook.net",
    "connect.facebook.com", "doubleverify.com", "moatads.com",
    "branch.io", "braze.com", "chartbeat.com", "newrelic.com",
    "clarity.ms", "fullstory.com",
)

_seq = 0


def is_analytics(url: str) -> bool:
    lowered = (url or "").lower()
    return any(d in lowered for d in ANALYTICS_DOMAINS)


def _netlog_max() -> int:
    try:
        return max(50, int(os.environ.get(ENV_NETLOG_MAX, "2000")))
    except ValueError:
        return 2000


def _log(sess) -> dict:
    log = getattr(sess, "_netlog", None)
    if log is None:
        log = sess._netlog = {"records": [], "by_id": {}, "seen": 0,
                              "evicted": 0}
    return log


def _record(sess, request) -> None:
    global _seq
    log = _log(sess)
    _seq += 1
    rec = {
        "id": f"n{_seq}",
        "method": request.method,
        "url": request.url,
        "resource_type": request.resource_type,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": None,
        "failure": None,
        "analytics": is_analytics(request.url),
        "_request": request,
        "_response": None,
    }
    log["seen"] += 1
    log["records"].append(rec)
    log["by_id"][rec["id"]] = rec
    by_req = log.setdefault("by_req", {})
    by_req[request] = rec
    cap = _netlog_max()
    while len(log["records"]) > cap:
        old = log["records"].pop(0)
        log["by_id"].pop(old["id"], None)
        log["by_req"].pop(old["_request"], None)
        log["evicted"] += 1


def _attach_recorder(session) -> None:
    """The session-open hook. Loaded-pack-guarded, per the seam contract."""
    from .. import packs
    if not packs.is_pack_loaded("network"):
        return
    if getattr(session, "_netlog_attached", False):
        return
    session._netlog_attached = True

    def on_request(request):
        try:
            _record(session, request)
        except Exception:
            pass

    def on_response(response):
        try:
            rec = _log(session).get("by_req", {}).get(response.request)
            if rec is not None:
                rec["status"] = response.status
                rec["_response"] = response
        except Exception:
            pass

    def on_failed(request):
        try:
            rec = _log(session).get("by_req", {}).get(request)
            if rec is not None:
                failure = getattr(request, "failure", None)
                rec["failure"] = str(failure) if failure else "failed"
        except Exception:
            pass

    session.context.on("request", on_request)
    session.context.on("response", on_response)
    session.context.on("requestfailed", on_failed)


_session.SESSION_OPEN_HOOKS.append(_attach_recorder)


def _redact_headers(headers: dict) -> dict:
    out = {}
    for name, value in (headers or {}).items():
        if name.lower() in SENSITIVE_HEADERS:
            _credentials.VAULT.observe(value)
            out[name] = _credentials.mask_value(value)
        else:
            out[name] = common.clip(value, 300)
    return out


async def list_requests(
    session: str | None = None,
    filter: str | None = None,
    resource_type: str | None = None,
    include_analytics: bool = False,
    start_index: int = 0,
    limit: int = 40,
) -> dict:
    """List the network requests recorded since the session opened, newest
    last: one row per request carrying its id, method, status or failure,
    resource type, and URL. Returns a paged slice with totals, filterable
    by a URL substring or a resource type (document, xhr, fetch, script,
    image, ...). Ad and analytics requests are hidden by default and
    counted honestly; include_analytics=true lists them too. Recording is
    passive: nothing here changes what the page loads (blocking is
    set_routing, a separate mutating tool). Pass a row's id to get_request
    for headers and the budgeted body.
    """
    sess = common.session_of(session)
    log = _log(sess)
    rows = list(log["records"])
    hidden_analytics = sum(1 for r in rows if r["analytics"])
    if not include_analytics:
        rows = [r for r in rows if not r["analytics"]]
    if filter:
        needle = filter.lower()
        rows = [r for r in rows if needle in r["url"].lower()]
    if resource_type:
        rows = [r for r in rows if r["resource_type"] == resource_type]
    chunk, total, nxt = common.page_slice(rows, start_index, limit)
    listed = [{k: (common.clip(r["url"], 160) if k == "url" else r[k])
               for k in ("id", "method", "status", "failure",
                         "resource_type", "url")} for r in chunk]
    more = (f"list_requests(start_index={nxt}) returns the next rows"
            if nxt is not None else "all matching requests are listed")
    return {
        "session": sess.session_id,
        "requests": listed,
        "totals": {
            "recorded": len(log["records"]), "seen": log["seen"],
            "evicted_from_ring": log["evicted"],
            "matched": total,
            "analytics_hidden": (0 if include_analytics
                                 else hidden_analytics),
        },
        "note": ("ad/analytics requests are hidden from this listing by "
                 "default and counted above; include_analytics=true lists "
                 "them. Nothing was blocked."),
        "continue": more,
    }


def _find_request(sess, request_id: str) -> dict:
    rec = _log(sess)["by_id"].get(request_id)
    if rec is None:
        raise TargetNotFound(
            f"no recorded request {request_id!r} in session "
            f"{sess.session_id}. Request ids are minted by the recorder and "
            f"listed by list_requests; the ring keeps the most recent "
            f"{_netlog_max()} and older ones are evicted (evicted so far: "
            f"{_log(sess)['evicted']}).")
    return rec


async def get_request(
    request_id: str,
    session: str | None = None,
    include_request_body: bool = False,
    max_body_chars: int = 4000,
    save_body_to: str | None = None,
) -> dict:
    """Inspect one recorded request by id: method, URL, redacted request and
    response headers (credential-bearing values are masked and can never
    ride out), the status, and the response body under a character budget
    with the true size stated, so a big JSON answer arrives clipped rather
    than whole. save_body_to writes the full body to a sandbox-checked
    file. Request-body reads are refused loudly on Firefox/BiDi lanes,
    where the driver would silently return nothing; the refusal names the
    lanes that support it. Binary bodies report size and type rather than
    bytes.
    """
    sess = common.session_of(session)
    rec = _find_request(sess, request_id)
    request = rec["_request"]
    out: dict = {
        "session": sess.session_id, "id": rec["id"],
        "method": rec["method"], "url": rec["url"],
        "resource_type": rec["resource_type"],
        "status": rec["status"], "failure": rec["failure"],
    }
    try:
        out["request_headers"] = _redact_headers(await request.all_headers())
    except Exception as exc:
        out["request_headers"] = f"unavailable ({type(exc).__name__})"

    if include_request_body:
        lanes.require(sess.spec, "request_body_read")
        body = request.post_data
        out["request_body"] = (
            common.clip(body, max_body_chars) if body
            else "the request carried no body, or the driver holds none")

    response = rec["_response"]
    if response is None:
        out["response"] = ("no response recorded"
                           + (f" (failure: {rec['failure']})"
                              if rec["failure"] else " yet"))
        return out
    resp: dict = {"status": response.status}
    try:
        resp["headers"] = _redact_headers(await response.all_headers())
    except Exception as exc:
        resp["headers"] = f"unavailable ({type(exc).__name__})"
    try:
        data = await response.body()
    except Exception as exc:
        resp["body"] = (f"the body is no longer retrievable "
                        f"({type(exc).__name__}: "
                        f"{str(exc).splitlines()[0][:120]}); bodies do not "
                        f"survive navigation away from the page that "
                        f"produced them")
        out["response"] = resp
        return out
    content_type = ""
    try:
        content_type = (await response.header_value("content-type")) or ""
    except Exception:
        pass
    resp["content_type"] = content_type
    resp["body_bytes"] = len(data)
    textual = any(t in content_type.lower() for t in
                  ("text", "json", "xml", "javascript", "urlencoded", "svg"))
    if textual:
        text = data.decode("utf-8", "replace")
        resp["body"] = text[:max(200, int(max_body_chars))]
        if len(text) > max(200, int(max_body_chars)):
            resp["body_truncated"] = (
                f"{len(text):,} characters total, "
                f"{max(200, int(max_body_chars)):,} returned; raise "
                f"max_body_chars or save_body_to a file")
    else:
        resp["body"] = (f"binary content ({content_type or 'unknown type'}, "
                        f"{len(data):,} bytes); use save_body_to to write "
                        f"it to a file")
    if save_body_to:
        resp["saved_to"] = common.write_bytes_file(
            save_body_to, data, "save response body")
    out["response"] = resp
    return out


async def export_har(
    session: str | None = None,
    path: str | None = None,
    include_analytics: bool = False,
) -> dict:
    """Write the session's recorded traffic as a HAR 1.2 file and return
    the path and entry count, which is the raw material for graduating a
    repeat task off the browser: capture the traffic once, read the HAR,
    and call the API directly next time. Headers are redacted the same way
    every payload is (credential values masked), bodies are omitted, and
    timings are coarse, all three stated in the file's own comment field.
    Analytics requests are excluded unless include_analytics=true. The
    file lands in the scoped downloads directory unless a path is named.
    """
    sess = common.session_of(session)
    log = _log(sess)
    entries = []
    for rec in log["records"]:
        if rec["analytics"] and not include_analytics:
            continue
        request = rec["_request"]
        response = rec["_response"]
        try:
            req_headers = _redact_headers(await request.all_headers())
        except Exception:
            req_headers = {}
        try:
            resp_headers = (_redact_headers(await response.all_headers())
                            if response else {})
        except Exception:
            resp_headers = {}
        entries.append({
            "startedDateTime": rec["started"],
            "time": -1,
            "request": {
                "method": rec["method"], "url": rec["url"],
                "httpVersion": "HTTP/1.1",
                "headers": [{"name": k, "value": str(v)}
                            for k, v in req_headers.items()],
                "queryString": [], "cookies": [],
                "headersSize": -1, "bodySize": -1,
            },
            "response": {
                "status": rec["status"] or 0,
                "statusText": rec["failure"] or "",
                "httpVersion": "HTTP/1.1",
                "headers": [{"name": k, "value": str(v)}
                            for k, v in resp_headers.items()],
                "cookies": [],
                "content": {"size": -1, "mimeType":
                            resp_headers.get("content-type", "")},
                "redirectURL": "", "headersSize": -1, "bodySize": -1,
            },
            "cache": {},
            "timings": {"send": -1, "wait": -1, "receive": -1},
        })
    har = {"log": {
        "version": "1.2",
        "creator": {"name": "kitchensink4web", "version": "phase5"},
        "comment": ("credential-bearing header values are masked, bodies "
                    "are omitted, and timings are coarse; this HAR is a "
                    "traffic map, not a byte-accurate replay capture"),
        "entries": entries,
    }}
    out = path or str(common.downloads_dir()
                      / f"traffic_{common.stamp()}.har")
    saved = common.write_text_file(
        out, _json.dumps(har, indent=2, ensure_ascii=False), "export HAR")
    return {
        "session": sess.session_id,
        "saved_to": saved, "entries": len(entries),
        "excluded_analytics": (0 if include_analytics else
                               sum(1 for r in log["records"]
                                   if r["analytics"])),
    }


def _routing(sess) -> dict:
    state = getattr(sess, "_routing", None)
    if state is None:
        state = sess._routing = {"routes": [], "offline": False,
                                 "extra_headers": {}, "throttle": None}
    return state


async def set_routing(
    session: str | None = None,
    action: str = "status",
    patterns: list[str] | None = None,
    status: int = 200,
    content_type: str = "text/plain",
    body: str = "",
    offline: bool | None = None,
    headers: dict | None = None,
    preset: str | None = None,
    origin: str | None = None,
    header: str | None = None,
    value: str | None = None,
    secret_ref: str | None = None,
    params: list[str] | None = None,
) -> dict:
    """Shape the session's network: block URL patterns, block the curated
    ad and analytics list, mock a pattern with a canned response, go
    offline and back, set extra request headers, throttle (Chromium lanes,
    named presets), or clear everything. Returns the routing state in
    force after the change, so what the session's traffic is subject to is
    always one call away (action='status' reads it without changing
    anything). Routing mutates what pages see, so this tool is absent
    under read-only mode and every change passes the policy choke point.
    `preset=` belongs to action='throttle' alone and its values are
    'slow-3g', 'fast-3g', and 'off'; blocking is driven by `patterns` or by
    action='block_ads', and analytics traffic is a listing filter on
    list_requests, not a routing preset. action='modify' adds one request
    header to one named origin and nothing else, and action='strip_params'
    drops named query parameters from matched request URLs and reports how
    many requests it actually rewrote. Response headers are never modified:
    rewriting a page's own CSP, CORS, or framing headers would disable the
    browser isolation every other protection in this server assumes, and
    testing a site's headers is a job for a proxy a human runs.
    """
    actions = ("status", "block", "block_ads", "mock", "offline",
               "headers", "throttle", "clear", "modify", "strip_params")
    action = common.enum_arg(action, actions, default="status",
                             tool="set_routing")
    if action not in actions:
        raise BadParams(
            f"unknown set_routing action {action!r}: the actions are "
            f"{list(actions)}.")
    sess = common.session_of(session)
    state = _routing(sess)
    if action == "status":
        return {"session": sess.session_id, "routing": _state_view(state)}

    if action == "modify":
        return await _modify(sess, state, origin, header, value, secret_ref)
    if action == "strip_params":
        return await _strip_params(sess, state, params, preset)

    _policy.approve(_policy.ActionRequest(
        tool="set_routing", kind="act", session=sess.session_id,
        # Every argument that makes one set_routing call different from
        # another (fuzzer class 5). Four mock routes with four different
        # statuses used to share one fingerprint and trip LOOP_DETECTED
        # claiming "identical arguments" about calls that differed.
        args={"action": action, "patterns": patterns, "offline": offline,
              "preset": preset, "status": status, "headers": headers,
              "body": _budgets.fingerprint(body) if body else None,
              "content_type": content_type},
        summary=f"set_routing({action}) on session {sess.session_id}"))

    if preset is not None and action not in ("throttle", "strip_params"):
        # AN ARGUMENT THAT DOES NOTHING SAYS SO (Desktop Low-21). `preset`
        # belongs to action='throttle' alone, and passing it with any other
        # action was silently ignored: the field tester asked for
        # preset='analytics', got `ok`, and watched analytics requests sail
        # through. The docstring already said where preset belongs; a
        # docstring is not a refusal.
        raise BadParams(
            f"preset={preset!r} applies to action='throttle' only, and this "
            f"call asked for action={action!r}, so nothing about preset was "
            f"applied. To stop ad and analytics requests use "
            f"set_routing(action='block_ads'), which blocks the curated "
            f"list; to hide them from a listing without blocking them use "
            f"list_requests(include_analytics=False), which is the default. "
            f"The throttle presets are named in this tool's description.")
    if action == "block":
        if not patterns:
            raise BadParams(
                "block needs patterns, for example ['**/*.png', "
                "'**/tracker/**'] (Playwright glob syntax).")
        # An EMPTY pattern matches nothing and was accepted silently
        # (fuzzer class 8), so the caller held a receipt for a block that
        # blocks nothing.
        empty = [i for i, x in enumerate(patterns)
                 if not isinstance(x, str) or not x.strip()]
        if empty:
            raise BadParams(
                f"pattern(s) at index {empty} are empty, so they would "
                f"match no request at all and nothing was installed. A "
                f"pattern is a Playwright glob, for example '**/*.png' or "
                f"'**/tracker/**'.")
        for pattern in patterns:
            async def _abort(route):
                await route.abort()
            await sess.context.route(pattern, _abort)
            state["routes"].append({"kind": "block", "pattern": pattern,
                                    "_handler": _abort})
    elif action == "block_ads":
        def _is_ad(url) -> bool:
            return is_analytics(str(url))

        async def _abort_ad(route):
            await route.abort()
        await sess.context.route(_is_ad, _abort_ad)
        state["routes"].append({"kind": "block_ads",
                                "pattern": "(curated ad/analytics list)",
                                "_matcher": _is_ad, "_handler": _abort_ad})
    elif action == "mock":
        if not patterns or len(patterns) != 1:
            raise BadParams(
                "mock takes exactly one pattern in patterns=[...] plus "
                "status, content_type, and body for the canned response.")
        # A STATUS THAT IS NOT A STATUS REFUSES (fuzzer class 8). `-1`, `0`,
        # `99`, `600` and `2147483648` were all stored verbatim with ok:true
        # and echoed back in `routing.routes`, so the route was registered
        # and the caller had a receipt for a mock the browser will never
        # serve.
        try:
            code = int(status)
        except (TypeError, ValueError):
            code = -1
        if not 100 <= code <= 599:
            raise BadParams(
                f"status={status!r} is not an HTTP status code, so this mock "
                f"was not installed. HTTP statuses run 100 to 599; the ones "
                f"a mock usually wants are 200, 204, 301, 401, 403, 404, "
                f"429, and 500.")
        status = code
        pattern = patterns[0]

        async def _fulfill(route):
            await route.fulfill(status=int(status),
                                content_type=content_type, body=body)
        await sess.context.route(pattern, _fulfill)
        state["routes"].append({"kind": "mock", "pattern": pattern,
                                "status": int(status),
                                "_handler": _fulfill})
    elif action == "offline":
        if offline is None:
            raise BadParams("offline takes offline=true or offline=false.")
        await sess.context.set_offline(bool(offline))
        state["offline"] = bool(offline)
    elif action == "headers":
        if not isinstance(headers, dict) or not headers:
            raise BadParams(
                "headers takes a non-empty dict of extra request headers.")
        # VAULTED AT APPLY TIME, not only when the audit record is written
        # (dream-boundary B2-fix-2). The class-wide fix lives in
        # `audit.observe_secret_args` and runs after the tool body; this runs
        # before it, so a value handed to this action is redactable for every
        # payload in between. Note what this action IS: it sets a
        # CONTEXT-WIDE header, on every origin, every subresource, and every
        # redirect hop, and a value passed here has already entered the
        # model's context. Use a scoped token, not a primary credential, and
        # use action='modify' when you want one origin.
        for _k, _v in headers.items():
            if _credentials.classify_name(_k) == "credential":
                _credentials.VAULT.observe(str(_v))
        await sess.context.set_extra_http_headers(
            {str(k): str(v) for k, v in headers.items()})
        state["extra_headers"] = {str(k): str(v)
                                  for k, v in headers.items()}
    elif action == "throttle":
        if sess.spec.engine != "chromium":
            raise LaneUnsupported(
                f"[lane {sess.spec.label}] throttling rides on the Chromium "
                f"DevTools network conditions and this lane is "
                f"{sess.spec.engine}. Relaunch on lane A (bundled Chromium) "
                f"or lane B chrome/msedge to throttle.")
        presets = {
            "slow-3g": {"latency": 400, "downloadThroughput": 50 * 1024,
                        "uploadThroughput": 50 * 1024},
            "fast-3g": {"latency": 150, "downloadThroughput": 180 * 1024,
                        "uploadThroughput": 84 * 1024},
            "off": None,
        }
        if preset not in presets:
            raise BadParams(
                f"throttle takes preset= one of {sorted(presets)}.")
        conditions = presets[preset]
        for record in sess.pages.values():
            cdp = await sess.context.new_cdp_session(record.page)
            if conditions is None:
                await cdp.send("Network.emulateNetworkConditions",
                               {"offline": False, "latency": 0,
                                "downloadThroughput": -1,
                                "uploadThroughput": -1})
            else:
                await cdp.send("Network.emulateNetworkConditions",
                               {"offline": False, **conditions})
            await cdp.detach()
        state["throttle"] = None if preset == "off" else preset
    elif action == "clear":
        for route in state["routes"]:
            try:
                await sess.context.unroute(
                    route.get("_matcher") or route["pattern"],
                    route["_handler"])
            except Exception:
                pass
        state["routes"] = []
        if state["offline"]:
            await sess.context.set_offline(False)
            state["offline"] = False
        if state["extra_headers"]:
            await sess.context.set_extra_http_headers({})
            state["extra_headers"] = {}
    return {"session": sess.session_id, "action": action,
            "routing": _state_view(state)}


def _origin_of(url: str) -> str | None:
    """scheme://host[:port] for a request URL, or None."""
    try:
        parts = _urlparse(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    netloc = parts.hostname.lower()
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme.lower()}://{netloc}"


def _one_full_origin(origin) -> str:
    """Validate `origin=` as ONE full origin and nothing else.

    A credentialed rule names an ORIGIN, never a pattern. `**/api/**`
    matches `evil.com/api/`, and a wildcard credentialed rule is the shape
    of a successful exfiltration wearing a convenience feature's clothes."""
    text = ("" if origin is None else str(origin)).strip()
    if not text:
        raise BadParams(
            "set_routing(action='modify') needs origin='https://example.com', "
            "one full origin with a scheme. This is the only routing action "
            "that will not take a pattern: a header rule that matched a path "
            "glob would follow the glob onto any host that serves that path.")
    if "*" in text or "?" in text:
        raise BadParams(
            f"origin={text!r} is a pattern, and action='modify' takes one "
            f"full origin. Wildcards are refused here and only here, because "
            f"'**/api/**' matches 'evil.com/api/' and a rule that attaches a "
            f"header cannot be allowed to name a shape instead of a site.")
    normalized = _origin_of(text)
    if not normalized:
        raise BadParams(
            f"origin={text!r} is not an http(s) origin. Write it as "
            f"'https://api.example.com' or 'https://localhost:8443'.")
    rest = text.split("://", 1)[1] if "://" in text else text
    path = rest[rest.find("/"):] if "/" in rest else ""
    if path not in ("", "/"):
        raise BadParams(
            f"origin={text!r} carries a path. A modify rule names an origin, "
            f"never a URL: the header would follow every request to that "
            f"origin regardless, so a path here would describe a scope this "
            f"server cannot actually enforce.")
    return normalized


async def _modify(sess, state, origin, header, value, secret_ref) -> dict:
    """Add one request header to requests bound for ONE named origin.

    THE ORIGIN SCOPE IS THE WHOLE FEATURE. `set_routing(action='headers')`
    is context-wide: every origin, every subresource, every redirect hop. A
    rule installed here matches on the request's own origin and re-checks it
    inside the handler, so a page's `<img>` to a third-party CDN carries
    nothing and a 302 to another host carries nothing on the second hop.

    OFF-LIST IS A REFUSAL AND NOT A GATE, and that is the deliberate
    departure from the ladder everywhere else in this server. Navigating
    somewhere unusual is ambiguous and a human can judge it; attaching a
    credential to an off-allowlist origin is not ambiguous. It is the exact
    shape of a successful prompt-injection exfiltration, and a confirmation
    prompt is a weak defense against an attack whose entire method is
    producing a plausible reason to click yes."""
    named = _one_full_origin(origin)
    name = ("" if header is None else str(header)).strip()
    if not name:
        raise BadParams(
            "set_routing(action='modify') needs header='X-Name', the one "
            "request header this rule sets.")
    if value is not None and secret_ref is not None:
        raise BadParams(
            "value= and secret_ref= are mutually exclusive: value carries a "
            "literal and secret_ref names one the server looks up itself. "
            "Nothing was installed.")
    kind = header_class(name)
    if kind == "cookie":
        raise CredentialRefused(
            f"{name!r} is a cookie header and this tool will not set one. "
            f"Cookies belong to the storage pack, where manage_cookies and "
            f"load_auth_state own them and load_auth_state is confirmation-"
            f"gated. A second unaudited door into the same asset would make "
            f"the first door's gate decorative. Nothing was installed.")
    if kind == "forbidden":
        raise BadParams(
            f"{name!r} is a header the browser authors. Rewriting it either "
            f"corrupts the request or forges a signal a server is entitled "
            f"to trust because the browser wrote it, so it is refused in "
            f"every mode. Nothing was installed.")
    if kind == "credential":
        return await _modify_credential(sess, state, named, name, value,
                                        secret_ref)
    if secret_ref is not None:
        raise BadParams(
            f"secret_ref= is for credential-class headers, and {name!r} is "
            f"an ordinary one. Pass value= instead. Nothing was installed.")
    if not isinstance(value, str) or not value:
        raise BadParams(
            f"set_routing(action='modify', header={name!r}) needs value=, "
            f"the string to send. Nothing was installed.")
    _policy.approve(_policy.ActionRequest(
        tool="set_routing", kind="act", session=sess.session_id,
        url=named,
        args={"action": "modify", "origin": named, "header": name.lower(),
              "source": "literal"},
        summary=f"set the {name} header on requests to {named}"))
    await _install_modify(sess, state, named, name, value, source="literal")
    return {"session": sess.session_id, "action": "modify",
            "routing": _state_view(state)}


async def _modify_credential(sess, state, named, name, value,
                             secret_ref) -> dict:
    """The credentialed branch. SHIPS DARK: default off, and off means the
    branch refuses by naming the switch rather than quietly behaving
    differently."""
    if not _credentials.credential_injection_enabled():
        raise CredentialRefused(
            f"{name!r} is a credential-class header and credential injection "
            f"is not enabled on this server, so nothing was installed. It is "
            f"off by default and a human turns it on at launch with "
            f"{_credentials.ENV_INJECTION}=true, which is a settings choice "
            f"no tool call can make. Ordinary headers and "
            f"action='strip_params' work without it.")
    if value is not None:
        # A REFUSAL THAT ECHOED THE THING IT REFUSED WOULD BE THE LEAK
        # WEARING A DIFFERENT HAT. The submitted value is not in this
        # message and must never be.
        raise CredentialRefused(
            f"{name!r} is a credential-class header and this tool does not "
            f"take a literal secret: a value passed as a tool argument has "
            f"already entered the model's context before any gate could run. "
            f"The route is secret_ref=<NAME>, where a human registered the "
            f"value at launch with {_credentials.ENV_SECRET_PREFIX}<NAME> and "
            f"the server looks it up itself. Registered names: "
            f"{_credentials.secret_ref_names() or 'none'}. Nothing was "
            f"installed and the value you passed is not repeated here.")
    if not secret_ref:
        raise BadParams(
            f"{name!r} is a credential-class header, so it takes "
            f"secret_ref=<NAME> naming a registered secret. Registered "
            f"names: {_credentials.secret_ref_names() or 'none'}.")
    if not _origins.active()["allow"]:
        raise NavigationBlocked(
            f"credential injection needs an origin allowlist and none is "
            f"configured, so nothing was installed. Set "
            f"{_origins.ENV_ALLOW} at launch to the origins this server may "
            f"reach. Everywhere else in this server an unset list means "
            f"unrestricted; here it means refused, deliberately, because the "
            f"unset default is what a first-run user has.")
    verdict = _origins.evaluate(named)
    if verdict != "allowed":
        raise NavigationBlocked(
            f"{named} is {verdict} under the origin policy, so no credential "
            f"was attached to anything and nothing was installed. This is a "
            f"REFUSAL and not a confirmation prompt: attaching a credential "
            f"to an origin outside your allowlist is the exact shape of a "
            f"prompt-injection exfiltration, and a prompt is a weak defense "
            f"against an attack whose whole method is producing a plausible "
            f"reason to say yes. Add {named} to {_origins.ENV_ALLOW} at "
            f"launch if you meant it.")
    # The value is looked up AFTER the gate, so an unknown reference refuses
    # before a human is asked about a rule that could not have worked.
    ref = str(secret_ref).strip().upper()
    _credentials.secret_value(ref)
    _policy.approve(_policy.ActionRequest(
        tool="set_routing", kind="act", session=sess.session_id,
        url=named, action_class="credential_injection",
        # The TOCTOU fingerprint is (origin, header, ref), carried on a
        # SYNTHETIC target using field names FINGERPRINT_FIELDS already
        # has. Widening that tuple would change the comparison for every
        # gate in the system; reusing it costs one comment.
        target={"name": name.lower(), "href": named, "action": ref},
        args={"action": "modify", "origin": named, "header": name.lower(),
              "source": f"secret_ref:{ref}"},
        summary=(f"attach the stored credential {ref} as the {name} header "
                 f"on requests to {named}")))
    await _install_modify(sess, state, named, name,
                          _credentials.secret_value(ref),
                          source=f"secret_ref:{ref}")
    return {"session": sess.session_id, "action": "modify",
            "routing": _state_view(state)}


async def _install_modify(sess, state, named, name, header_value, *,
                          source) -> dict:
    """Install the route. The VALUE lives in this closure and nowhere else:
    it is never returned, never stored in the state dict, and never named in
    a payload."""
    record = {"kind": "modify", "pattern": named, "origin": named,
              "header": name.lower(), "source": source, "applied": 0}

    async def _add_header(route):
        request = route.request
        try:
            # RE-CHECKED INSIDE THE HANDLER, not only in the matcher. A
            # redirect creates a new request at a new URL and a subresource
            # is a request of its own; both reach a context-wide rule and
            # neither may reach this one.
            if _origin_of(request.url) != named:
                await route.continue_()
                return
            merged = dict(request.headers)
            merged[name.lower()] = header_value
            record["applied"] += 1
            await route.continue_(headers=merged)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    def _matcher(url) -> bool:
        return _origin_of(str(url)) == named

    await sess.context.route(_matcher, _add_header)
    record["_matcher"] = _matcher
    record["_handler"] = _add_header
    state["routes"].append(record)
    return record


async def _strip_params(sess, state, params, preset) -> dict:
    """Drop named query parameters from matched request URLs.

    The one capability in this whole feature that REMOVES data instead of
    adding it, so it needs no gate: it cannot exfiltrate anything and there
    is no asset on the other side of it.

    It reports the count of requests actually REWRITTEN, not the count of
    rules installed, the distinction `list_requests` already models with
    `analytics_hidden`. A receipt for work that did not happen is the defect
    the preset='analytics' finding was."""
    names = list(params or [])
    if preset is not None:
        if str(preset).strip().lower() != "tracking":
            raise BadParams(
                f"preset={preset!r} is not a strip_params preset: the only "
                f"one is 'tracking', the curated list. The throttle presets "
                f"belong to action='throttle'.")
        names = list(TRACKING_PARAMS) + names
    cleaned = sorted({str(p).strip() for p in names if str(p).strip()})
    if not cleaned:
        raise BadParams(
            "strip_params needs params=['utm_source', ...] or "
            "preset='tracking' for the curated list. Nothing was installed.")
    _policy.approve(_policy.ActionRequest(
        tool="set_routing", kind="act", session=sess.session_id,
        args={"action": "strip_params", "params": cleaned},
        summary=f"strip {len(cleaned)} query parameter(s) from requests on "
                f"session {sess.session_id}"))
    record = {"kind": "strip_params", "pattern": "**/*",
              "params": cleaned, "rewritten": 0,
              "note": ("a noise filter with an honest count, not a privacy "
                       "product: this strips the named parameters from "
                       "request URLs and nothing else")}
    wanted = set(cleaned)

    async def _strip(route):
        request = route.request
        try:
            parts = _urlparse(request.url)
            if not parts.query:
                await route.continue_()
                return
            kept = [(k, v) for k, v in _parse_qsl(parts.query,
                                                  keep_blank_values=True)
                    if k not in wanted]
            if len(kept) == len(_parse_qsl(parts.query,
                                           keep_blank_values=True)):
                await route.continue_()
                return
            rebuilt = parts._replace(query=_urlencode(kept)).geturl()
            record["rewritten"] += 1
            await route.continue_(url=rebuilt)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    await sess.context.route("**/*", _strip)
    record["_handler"] = _strip
    state["routes"].append(record)
    return {"session": sess.session_id, "action": "strip_params",
            "routing": _state_view(state)}


def _state_view(state: dict) -> dict:
    """Names only, always. A modify rule reports its origin, its header NAME,
    and whether the value came from a reference or a literal; the value
    itself lives in the route handler's closure and has no path to here."""
    return {
        "routes": [{k: v for k, v in r.items()
                    if not k.startswith("_")} for r in state["routes"]],
        "offline": state["offline"],
        "extra_headers": sorted(state["extra_headers"]),
        "throttle": state["throttle"],
    }


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (list_requests, get_request, export_har, set_routing)
