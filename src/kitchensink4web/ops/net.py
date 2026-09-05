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

from ..engine import lanes, session as _session
from ..errors import BadParams, LaneUnsupported, TargetNotFound
from ..policy import credentials as _credentials
from ..policy import engine as _policy
from . import common

ENV_NETLOG_MAX = "KS4WEB_NETLOG_MAX"

#: Header names whose values are credentials or session material. Observed
#: into the vault BEFORE masking (the DESIGN 5.3 contract), so the
#: serializer catches any later path that would emit them.
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "x-csrf-token", "x-xsrf-token",
})

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
    list_requests, not a routing preset.
    """
    actions = ("status", "block", "block_ads", "mock", "offline",
               "headers", "throttle", "clear")
    if action not in actions:
        raise BadParams(
            f"unknown set_routing action {action!r}: the actions are "
            f"{list(actions)}.")
    sess = common.session_of(session)
    state = _routing(sess)
    if action == "status":
        return {"session": sess.session_id, "routing": _state_view(state)}

    _policy.approve(_policy.ActionRequest(
        tool="set_routing", kind="act", session=sess.session_id,
        args={"action": action, "patterns": patterns, "offline": offline,
              "preset": preset},
        summary=f"set_routing({action}) on session {sess.session_id}"))

    if action == "block":
        if not patterns:
            raise BadParams(
                "block needs patterns, for example ['**/*.png', "
                "'**/tracker/**'] (Playwright glob syntax).")
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


def _state_view(state: dict) -> dict:
    return {
        "routes": [{k: v for k, v in r.items()
                    if not k.startswith("_")} for r in state["routes"]],
        "offline": state["offline"],
        "extra_headers": sorted(state["extra_headers"]),
        "throttle": state["throttle"],
    }


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (list_requests, get_request, export_har, set_routing)
