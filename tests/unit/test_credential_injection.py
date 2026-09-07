"""Feature #12's pin list: credential injection BY REFERENCE, shipped dark.

The negative pins ARE the specification here. The positive ones say the
feature works; the negative ones say the thing that makes it defensible, and
there are three times as many because a credential-injection primitive on a
server whose headline claim is credential blindness earns exactly that ratio.

The load-bearing pin is the first one. Every row of the redaction-coverage
table rests on the registration-time `VAULT.observe`, and if that regresses
every other row silently becomes false.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from kitchensink4web import server
from kitchensink4web.errors import (BadParams, CredentialRefused,
                                    NavigationBlocked, TargetNotFound)
from kitchensink4web.ops import net
from kitchensink4web.policy import audit, credentials, gates

SRC = Path(server.__file__).resolve().parent
SECRET = "ghp_liveLOOKINGtoken_0123456789abcdef"

_ENVS = ("KS4WEB_CREDENTIAL_INJECTION", "KS4WEB_ALLOW_ORIGINS",
         "KS4WEB_DENY_ORIGINS")


def _clear_env():
    for name in _ENVS:
        os.environ.pop(name, None)
    for name in [k for k in list(os.environ)
                 if k.startswith("KS4WEB_SECRET_")]:
        os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def clean():
    _clear_env()
    credentials.VAULT.clear()
    credentials.register_secret_refs()
    yield
    _clear_env()
    credentials.VAULT.clear()
    credentials.register_secret_refs()


def enable(**secrets):
    os.environ["KS4WEB_CREDENTIAL_INJECTION"] = "true"
    for name, value in secrets.items():
        os.environ[f"KS4WEB_SECRET_{name}"] = value
    return credentials.register_secret_refs()


def run(coro):
    return asyncio.run(coro)


# =====================================================================
# SHIP DARK — the default state must be INERT, not merely refusing
# =====================================================================


def test_the_default_state_is_truly_inert():
    """AUTHOR RULING (2026-09-07): built, and off. Off means nothing
    happens, not that something happens quietly.

    With the switch unset and a `KS4WEB_SECRET_*` variable present: no name
    is registered, the value never enters the redaction vault, no status
    surface mentions the subsystem, and the credentialed branch refuses by
    NAMING the switch rather than behaving differently."""
    os.environ["KS4WEB_SECRET_GITHUB"] = SECRET
    assert credentials.credential_injection_enabled() is False
    assert credentials.register_secret_refs() == []
    assert credentials.secret_ref_names() == []
    # Nothing was vaulted, because nothing was scanned.
    assert credentials.VAULT.scrub({"t": SECRET}) == {"t": SECRET}
    with pytest.raises(CredentialRefused) as exc:
        run(net._modify(None, None, "https://api.example.com",
                        "Authorization", None, "GITHUB"))
    assert credentials.ENV_INJECTION in str(exc.value)


def test_the_dark_switch_does_not_darken_the_safe_two_thirds():
    """Ordinary headers and tracking-parameter stripping are not part of the
    dangerous capability and do not wait behind its switch."""
    assert net.header_class("x-ab-test") == "ordinary"
    assert "strip_params" in net.set_routing.__doc__
    assert net.TRACKING_PARAMS


# =====================================================================
# POSITIVE PINS B7.1-5
# =====================================================================


def test_b1_secret_registration_vaults_at_startup():
    """THE LOAD-BEARING PIN. Registration observes the value into the vault
    BEFORE it is stored anywhere, which is what converts every downstream
    path -- tool payload, audit record, error message, spill file, HAR --
    from "audited by inspection" to "covered by the serializer". If this
    regresses, every row of the coverage table silently becomes false."""
    enable(GITHUB=SECRET)
    assert credentials.secret_ref_names() == ["GITHUB"]
    nested = {"a": [{"b": f"prefix {SECRET} suffix"}], "c": (SECRET,)}
    scrubbed = credentials.VAULT.scrub(nested)
    blob = json.dumps(scrubbed)
    assert SECRET not in blob
    assert credentials.MASK in blob


def test_b5_the_state_view_reports_the_reference_not_the_value():
    """`action='status'` after a modify reports `source: 'secret_ref:GITHUB'`.
    Header NAMES and reference NAMES only, the pattern `extra_headers`
    already established by returning `sorted(...)` of its keys."""
    state = {"routes": [{"kind": "modify", "origin": "https://api.example.com",
                         "header": "authorization",
                         "source": "secret_ref:GITHUB", "applied": 3,
                         "_handler": object(), "_matcher": object()}],
             "offline": False, "extra_headers": {}, "throttle": None}
    view = net._state_view(state)
    blob = json.dumps(view)
    assert "secret_ref:GITHUB" in blob
    assert "_handler" not in blob and "_matcher" not in blob
    assert SECRET not in blob


def test_b4_strip_params_is_the_one_capability_that_removes_data():
    """No gate, because it cannot exfiltrate anything and there is no asset
    on the other side of it. And it reports what it REWROTE, not what was
    installed: a receipt for work that did not happen is the defect the
    preset='analytics' finding was."""
    src = net._strip_params.__doc__
    assert "rewrote" in src.lower() or "rewritten" in src.lower()
    assert "utm_source" in net.TRACKING_PARAMS
    assert "gclid" in net.TRACKING_PARAMS


# =====================================================================
# NEGATIVE PINS B7.6-20 — these are the specification
# =====================================================================


def test_b6_no_registered_tool_output_can_carry_a_registered_secret(
        launch, live_tools):
    """The sweep half. With a secret registered, no tool SCHEMA and no tool
    NAME anywhere in the surface names it, and the serializer redactor is
    installed process-wide so any payload that did carry it would be
    scrubbed on the way out."""
    enable(GITHUB=SECRET)
    launch(read_only=False, cli_packs=["network"])
    blob = json.dumps({name: (tool.parameters or {})
                       for name, tool in live_tools().items()})
    assert SECRET not in blob
    assert "KS4WEB_SECRET_GITHUB" not in blob
    from kitchensink4web import envelope
    assert envelope.redact({"leak": SECRET})["leak"] != SECRET


def test_b7_a_secret_never_reaches_the_audit_log_on_disk(tmp_path,
                                                        monkeypatch):
    """B2's defect, pinned. `set_routing(action='headers', headers={...})`
    wrote whatever value it was handed VERBATIM into `audit-<pid>.jsonl`,
    inside a subsystem whose docstring says the log cannot hold what the
    transcript must not. The mechanism only covered values something had
    OBSERVED, and a token that only ever appeared as a tool argument was
    never observed by anything.

    Run against the literal-value path too, because that is the one that
    failed and the reason this pin exists."""
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    log = audit.AuditLog()
    log.record("set_routing", "ok",
               args={"action": "headers",
                     "headers": {"Authorization": f"Bearer {SECRET}"}})
    written = "".join(p.read_text(encoding="utf-8")
                      for p in (tmp_path / "audit").glob("*.jsonl"))
    assert written
    assert SECRET not in written
    assert credentials.MASK in written


def test_b8_an_offlist_origin_refuses_and_is_not_routed_to_the_gate():
    """The deliberate departure from the ladder. Everywhere else in this
    server off-list is a GATE CLASS, because navigating somewhere unusual is
    ambiguous and a human can judge it. Attaching a credential to an
    off-allowlist origin is not ambiguous: it is the exact shape of a
    successful prompt-injection exfiltration, and a confirmation prompt is a
    weak defense against an attack whose whole method is producing a
    plausible reason to click yes.

    This pin exists to catch a future refactor that "helpfully" routes it to
    the gate ladder like every other off-list action."""
    enable(GITHUB=SECRET)
    os.environ["KS4WEB_ALLOW_ORIGINS"] = "api.github.com"
    with pytest.raises(NavigationBlocked) as exc:
        run(net._modify(None, None, "https://api.evil.test",
                        "Authorization", None, "GITHUB"))
    assert "off-list" in str(exc.value)
    assert "REFUSAL" in str(exc.value)


def test_b9_no_allowlist_refuses_credential_injection_entirely():
    """The unset default is what a first-run user has, so here alone an
    unset list means refused rather than unrestricted."""
    enable(GITHUB=SECRET)
    with pytest.raises(NavigationBlocked) as exc:
        run(net._modify(None, None, "https://api.github.com",
                        "Authorization", None, "GITHUB"))
    assert "KS4WEB_ALLOW_ORIGINS" in str(exc.value)


def test_b10_a_wildcard_or_a_glob_origin_refuses():
    """`**/api/**` matches `evil.com/api/`. A credentialed rule names an
    ORIGIN, never a path glob."""
    for bad in ("*.github.com", "**/api/**", "*", "https://x.test/api",
                "github.com/api", "not-a-url"):
        with pytest.raises(BadParams):
            net._one_full_origin(bad)
    assert net._one_full_origin("https://api.github.com") \
        == "https://api.github.com"
    assert net._one_full_origin("https://api.github.com:8443") \
        == "https://api.github.com:8443"


def test_b11_a_literal_secret_refuses_and_the_refusal_does_not_echo_it():
    """A refusal that echoes the thing it refused is the leak wearing a
    different hat."""
    enable(GITHUB=SECRET)
    os.environ["KS4WEB_ALLOW_ORIGINS"] = "api.github.com"
    with pytest.raises(CredentialRefused) as exc:
        run(net._modify(None, None, "https://api.github.com",
                        "Authorization", f"Bearer {SECRET}", None))
    text = str(exc.value)
    assert SECRET not in text
    assert "secret_ref" in text


def test_b12_an_unknown_reference_is_not_an_oracle():
    """The message lists the REGISTERED names and reveals nothing about
    unregistered ones: whether a similarly-spelled variable exists is
    exactly what an attacker probing this would want to learn."""
    enable(GITHUB=SECRET)
    with pytest.raises(TargetNotFound) as exc:
        credentials.secret_value("GITHUB_PROD")
    text = str(exc.value)
    assert "GITHUB" in text            # the registered name, listed
    assert SECRET not in text
    for leak in ("exists", "similar", "did you mean", "close"):
        assert leak not in text.lower()


def test_b13_a_cookie_header_is_refused_always():
    """Cookies belong to the storage pack, which gates them. A second
    unaudited door into the same asset makes the first door's gate
    decorative."""
    enable(GITHUB=SECRET)
    os.environ["KS4WEB_ALLOW_ORIGINS"] = "api.github.com"
    for name in ("Cookie", "cookie", "Set-Cookie"):
        with pytest.raises(CredentialRefused) as exc:
            run(net._modify(None, None, "https://api.github.com", name,
                            "a=b", None))
        assert "storage" in str(exc.value)


def test_b14_browser_authored_headers_are_refused():
    """Rewriting these either corrupts the request or forges a signal a
    server is entitled to trust because the BROWSER wrote it."""
    for name in ("host", "content-length", "connection",
                 "transfer-encoding", "upgrade", "sec-fetch-mode",
                 "Sec-Fetch-Site"):
        assert net.header_class(name) == "forbidden", name
        with pytest.raises(BadParams):
            run(net._modify(None, None, "https://api.github.com", name,
                            "x", None))


def test_b14b_the_credential_class_generalizes_beyond_the_seed_list():
    """A novel name like `x-session-key` classifies without a list edit,
    because the tier seeds from SENSITIVE_HEADERS and generalizes through
    the same `classify_name` the cookie and storage doors use."""
    for name in ("authorization", "proxy-authorization", "x-api-key",
                 "x-auth-token", "x-session-key", "x-refresh-token"):
        assert net.header_class(name) == "credential", name
    for name in ("accept-language", "x-ab-test", "user-agent", "referer"):
        assert net.header_class(name) == "ordinary", name


def test_b15_no_code_path_modifies_a_response_header():
    """SPECCED OUT by name. Rewriting a page's CSP, CORS, or framing headers
    would disable the browser isolation every other protection in this
    server assumes, on a page this server is simultaneously treating as
    untrusted content. A static scan, because the point is that the
    capability does not EXIST rather than that it refuses."""
    offenders = []
    for path in SRC.rglob("*.py"):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if "route.fulfill(" in line and "headers" in line:
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        f"a response-header modification path exists: {offenders}")
    src = net.set_routing.__doc__
    assert "Response headers are never modified" in src


def test_b16_and_b17_the_handler_bounds_both_hops():
    """The unit half; `tests/browser/test_credential_injection_live.py` has
    the wire half, and the wire half is the one that mattered.

    A subresource is a request of its own, so the handler re-checks the
    origin rather than trusting the matcher that admitted it. A REDIRECT is
    worse and was a live leak on the first run of the live pin:
    `route.continue_(headers=...)` hands the headers to the network stack and
    the stack RE-SENDS them itself on a 302, with the route handler never
    consulted for the second hop. Fetching with `max_redirects=0` and
    fulfilling the redirect back to the browser makes the second hop a new
    request the browser issues, which passes the matcher again and does not
    match."""
    import inspect
    source = inspect.getsource(net._install_modify)
    assert "_origin_of(request.url) != named" in source
    assert "max_redirects=0" in source
    assert "await route.continue_(headers=" not in source, (
        "continue_ with headers lets the network stack re-send them across a "
        "redirect, which is the leak the live pin caught")
    assert net._origin_of("https://api.example.com/v1/x?q=1") \
        == "https://api.example.com"
    assert net._origin_of("https://cdn.other.com/a.png") \
        != "https://api.example.com"
    assert net._origin_of("file:///C:/x") is None


def test_b18_a_short_secret_refuses_at_startup():
    """A secret too short to redact is a secret this server cannot protect,
    and discovering that at call time is discovering it too late. The
    message names the variable, matching the loud-typo doctrine."""
    os.environ["KS4WEB_CREDENTIAL_INJECTION"] = "true"
    os.environ["KS4WEB_SECRET_X"] = "abc"
    with pytest.raises(BadParams) as exc:
        credentials.register_secret_refs()
    assert "KS4WEB_SECRET_X" in str(exc.value)
    assert str(credentials.MIN_SECRET_LENGTH) in str(exc.value)


def test_b19_the_new_gate_class_touches_no_policy():
    """The closed-set assertion, re-run with `credential_injection` present.
    It authorizes ONE data flow to ONE origin: it names no policy, unlocks
    no mode, widens no origin list, and loads no pack."""
    assert "credential_injection" in gates.GATED_CLASSES
    sentence = gates.GATED_CLASSES["credential_injection"]
    assert "origin" in sentence and "credential" in sentence
    for forbidden in ("read_only", "unlock", "disable", "policy"):
        assert forbidden not in "credential_injection"


def test_b20_the_toctou_fingerprint_is_origin_header_and_reference():
    """Reusing FINGERPRINT_FIELDS rather than widening it: widening that
    tuple changes the comparison for every gate in the system, and reusing
    it costs one comment."""
    asked = gates.fingerprint({"name": "authorization",
                               "href": "https://api.github.com",
                               "action": "GITHUB"})
    assert asked == {"name": "authorization",
                     "href": "https://api.github.com", "action": "GITHUB"}
    engine = gates.GateEngine()
    with pytest.raises(Exception) as exc:
        engine.ask("credential_injection", tool="set_routing", session="s1",
                   page=None, target={"name": "authorization",
                                      "href": "https://api.github.com",
                                      "action": "GITHUB"},
                   summary="attach")
    grant = engine.redeem(exc.value.detail["requestState"], {"allow": True})
    from kitchensink4web.errors import TargetChanged
    with pytest.raises(TargetChanged):
        engine.verify_execute(grant, {"name": "authorization",
                                      "href": "https://api.evil.test",
                                      "action": "GITHUB"})


def test_the_secret_value_never_travels_as_a_tool_argument():
    """T5, the structural one. If the secret is a tool argument, credential
    blindness is already lost before any gate runs, because the model typed
    it. The signature takes `secret_ref`, and `value` is refused for every
    credential-class header."""
    import inspect
    params = inspect.signature(net.set_routing).parameters
    assert "secret_ref" in params
    assert params["secret_ref"].default is None
    src = inspect.getsource(net._modify_credential)
    assert "value is not None" in src
