"""S1 spike: projection assembly + degradation ladder. Throwaway prototype."""
from __future__ import annotations

import json
import math
from pathlib import Path

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")


def ntok(s: str) -> int:
    return len(ENC.encode(s))


HERE = Path(__file__).parent
EXTRACT_JS = (HERE / "extract.js").read_text(encoding="utf-8")

CLOSED_SHADOW_HOOK = """
(() => {
  window.__ks4web_closedShadow = 0;
  const orig = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function(init) {
    if (init && init.mode === 'closed') window.__ks4web_closedShadow++;
    return orig.apply(this, arguments);
  };
})();
"""


def est_expand(reg: dict) -> int:
    """Estimated token cost to expand a region."""
    return int(reg["chars"] / 4 + reg["interactive"] * 9 + reg["text_blocks"] * 2 + 15)


def fmt_num(n) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------- block builders

def block_identity(d, meta):
    i = d["identity"]
    lines = [
        "## 1 IDENTITY",
        f'url: {i["url"]}',
        f'title: {i["title"]}',
        f'status: {meta["status"]} | load: {meta["load_state"]} | lane: A(bundled chromium) | page: p1 '
        f'| read_token: rt1 | t={meta["ts"]}',
        f'viewport: {i["viewport"]} | page height: {i["screens"]} screens | dom nodes: '
        f'{fmt_num(d["completeness"]["total_elements"])}',
    ]
    return lines


def block_shape(d, expanded: bool, cap: int | None = None):
    lines = ["", "## 2 PAGE SHAPE (regions; expand cost is an estimate)"]
    regs = d["regions"]
    dropped = 0
    if cap is not None and len(regs) > cap:
        dropped = len(regs) - cap
        regs = regs[:cap]
    for r in regs:
        vp = "in-view" if r["in_viewport"] else f'y={r["top"]}'
        lines.append(
            f'{r["ref"]} | {r["kind"]:<13} | "{r["label"]}" | {r["interactive"]} act, '
            f'{r["text_blocks"]} blocks, {r["images"]} img | {vp} | ~{fmt_num(est_expand(r))} tok to expand'
        )
    if dropped:
        lines.append(f"[{dropped} smaller regions not listed; get_page_view(view='outline', detail='full')]")
    return lines


def block_affordances(d, cap: int):
    lines = ["", f"## 3 AFFORDANCES (ranked: in-viewport, then main/dialog, then weight)"]
    items = d["affordances"]
    # collapse identical role+name into one line carrying up to 4 refs
    groups: list[dict] = []
    seen: dict[tuple, dict] = {}
    for a in items:
        k = (a["role"], a["name"])
        if k in seen and a["name"]:
            g = seen[k]
            g["refs"].append(a["ref"])
            g["n"] += 1
            continue
        g = {"refs": [a["ref"]], "n": 1, **a}
        seen[k] = g
        groups.append(g)
    shown = groups[:cap]
    for g in shown:
        refs = ",".join(g["refs"][:3]) + ("+" if len(g["refs"]) > 3 else "")
        dup = f' (x{g["n"]})' if g["n"] > 1 else ""
        st = f' [{g["state"]}]' if g["state"] else ""
        sec = " [secret:true value-never-read]" if g["secret"] else ""
        name = g["name"] or "(unnamed)"
        lines.append(f'{refs} | {g["role"]} | "{name}"{dup}{st}{sec} | in {g["region"]}')
    omitted_groups = len(groups) - len(shown)
    omitted_elems = d["aff_total"] - sum(g["n"] for g in shown)
    if omitted_groups > 0:
        lines.append(
            f"[{omitted_elems} more interactive elements in {omitted_groups} groups not listed. "
            f"Next: get_page_view(page='p1', view='act', cursor='aff:{cap}') "
            f"or find_elements(query=...) or scope to a region.]"
        )
    return lines


def block_digest(d, mode: str):
    """mode: full | headings | none"""
    if mode == "none":
        return []
    lines = ["", "## 4 CONTENT DIGEST" + ("  (readable-article projection)" if d["readable"] else "  (app-shell projection)")]
    if mode == "full" and d["lead"]:
        lead = d["lead"]
        lines.append("lead: " + (lead[:420] + ("..." if len(lead) > 420 else "")))
    hs = d["headings"]
    if not hs:
        lines.append("(no headings; page is not article-shaped)")
        return lines
    cap = 40 if mode == "full" else 25
    for h in hs[:cap]:
        ind = "  " * (h["level"] - 1)
        cost = int(h["chars"] / 4) + 10
        lines.append(f'{ind}{h["ref"]} | h{h["level"]} | {h["text"]} | ~{fmt_num(cost)} tok')
    if len(hs) > cap:
        lines.append(f"[{len(hs) - cap} more headings; get_page_view(view='outline')]")
    lines.append(f'prose: ~{fmt_num(d["prose_chars"])} chars total; expand one section with '
                 f"get_page_view(page='p1', view='read', location={{'ref':'h<n>'}})")
    return lines


def block_forms(d):
    if not d["forms"]:
        return []
    lines = ["", "## 5 FORMS"]
    for f in d["forms"][:12]:
        lines.append(f'{f["ref"]} | "{f["name"] or f["action"]}" | {f["method"]} {f["action"]} | '
                     f'{len(f["fields"])} fields | in {f["region"]}')
        for fl in f["fields"][:25]:
            req = " required" if fl["required"] else ""
            sec = " secret=true(value never read)" if fl["secret"] else ""
            pay = " PAYMENT-SHAPED(gated)" if fl["payment"] else ""
            lines.append(f'   {fl["ref"] or "-"} | {fl["label"] or "(unlabeled)"} | {fl["type"]}{req} | '
                         f'{fl["value_state"]}{sec}{pay}')
        if len(f["fields"]) > 25:
            lines.append(f'   [{len(f["fields"]) - 25} more fields]')
    if len(d["forms"]) > 12:
        lines.append(f'[{len(d["forms"]) - 12} more forms]')
    return lines


def block_tables(d):
    if not d["tables"] and not d["div_tables"]:
        return []
    lines = ["", "## 6 TABLES (structure only; cells come from get_table)"]
    for t in d["tables"][:12]:
        sp = f', {t["spans"]} spanned cells' if t["spans"] else ""
        hdr = " | ".join(t["headers"]) if t["headers"] else "(no th)"
        lines.append(f'{t["ref"]} | "{t["caption"]}" | {t["rows"]}x{t["cols"]}{sp} | cols: {hdr} '
                     f'| in {t["region"]} | ~{fmt_num(int(t["chars"] / 4))} tok if fully read')
    if len(d["tables"]) > 12:
        lines.append(f'[{len(d["tables"]) - 12} more tables]')
    if d["div_tables"]:
        lines.append(f'[{d["div_tables"]} div-rendered grids (role=table/grid) detected; get_list handles these]')
    return lines


def block_completeness(d, rung, used, budget, unexpanded):
    c = d["completeness"]
    lines = ["", "## 7 COMPLETENESS (what this read did NOT see)"]
    if c["frames"]:
        lines.append(f'iframes not traversed: {c["frames_same"]} same-origin, {c["frames_cross"]} cross-origin')
        for fr in c["frames"][:6]:
            lines.append(f'   {fr["ref"]} | {"same-origin" if fr["same_origin"] else "cross-origin"} | '
                         f'{fr["title"] or fr["src"]}  -> get_page_view(location={{"frame":"{fr["ref"]}"}})')
    else:
        lines.append("iframes: none")
    lines.append(f'shadow roots: {c["open_shadow_roots"]} open (traversed=no, prototype limit), '
                 f'{c["closed_shadow_roots"]} closed (unreachable by any tool)')
    if c["virtual"]:
        for v in c["virtual"][:4]:
            claimed = f'; page reports ~{v["claimed"]} total' if v["claimed"] else "; total unknown"
            lines.append(f'virtualized/infinite container in {v["region"]}: {v["dom_count"]} nodes in DOM{claimed}')
    else:
        lines.append("virtualized/infinite containers: none detected")
    lines.append(f'below the fold: {d["identity"]["screens"]} screens of content (this read covered the whole DOM, '
                 f'not just the viewport)')
    hr = ", ".join(f"{k}={v}" for k, v in sorted(c["hidden_reasons"].items(), key=lambda x: -x[1])[:5])
    lines.append(f'hidden interactive elements stripped: {c["hidden_interactive"]} ({hr or "none"})')
    if c["canvases"]:
        lines.append(f'canvas-rendered regions with no text projection: {len(c["canvases"])} '
                     f'-> enable the "capture" pack (--packs capture) for pixels')
    else:
        lines.append("canvas-rendered regions: none")
    lines.append(f'BUDGET: {fmt_num(used)}/{fmt_num(budget)} tokens | degradation rung {rung}/5 | '
                 f'{unexpanded} regions not expanded')
    return lines


def block_continuation(d, rung, cap_aff):
    lines = ["", "## 8 NEXT CALLS"]
    regs = sorted(d["regions"], key=lambda r: -est_expand(r))[:3]
    for r in regs:
        lines.append(f'expand {r["ref"]} ("{r["label"]}"): '
                     f'get_page_view(page="p1", location={{"region":"{r["ref"]}"}}, detail="standard")  '
                     f'~{fmt_num(est_expand(r))} tok')
    if d["tables"]:
        t = d["tables"][0]
        lines.append(f'read table {t["ref"]}: get_table(page="p1", ref="{t["ref"]}", rows="1-50")  '
                     f'({t["rows"]} rows total)')
    if d["aff_total"] > cap_aff:
        lines.append(f'more controls: get_page_view(page="p1", view="act", cursor="aff:{cap_aff}")')
    lines.append('act on any ref: click(page="p1", ref="e<n>") | type_text(page="p1", ref="e<n>", text=...) '
                 '| fill_form(page="p1", form="f<n>", values={...})')
    lines.append('changed-only re-read: get_page_view(page="p1", since="rt1")')
    return lines


# ---------------------------------------------------------------- the ladder

RUNGS = [
    # (rung, region_cap, aff_cap, digest_mode)
    (1, None, 40, "full"),
    (2, 12, 30, "full"),
    (3, 10, 18, "full"),
    (4, 8, 12, "headings"),
    (5, 6, 8, "none"),
]


def render(d, meta, rung_spec, budget):
    rung, region_cap, aff_cap, digest_mode = rung_spec
    unexpanded = 0 if region_cap is None else max(0, len(d["regions"]) - region_cap)
    body = []
    body += block_identity(d, meta)
    body += block_shape(d, expanded=(rung == 1), cap=region_cap)
    body += block_affordances(d, aff_cap)
    body += block_digest(d, digest_mode)
    body += block_forms(d)
    body += block_tables(d)
    tail_used = 0  # completeness needs the count, so render twice cheaply
    core = "\n".join(body)
    used_est = ntok(core)
    body2 = body + block_completeness(d, rung, used_est, budget, unexpanded) + \
        block_continuation(d, rung, aff_cap)
    text = "\n".join(body2)
    # one fixup pass so the printed budget line matches the real total
    real = ntok(text)
    body3 = body + block_completeness(d, rung, real, budget, unexpanded) + \
        block_continuation(d, rung, aff_cap)
    return "\n".join(body3)


def project(d, meta, budget=5000):
    """Run the degradation ladder. Returns (text, rung, tokens, trace)."""
    trace = []
    for spec in RUNGS:
        text = render(d, meta, spec, budget)
        t = ntok(text)
        trace.append({"rung": spec[0], "region_cap": spec[1], "aff_cap": spec[2],
                      "digest": spec[3], "tokens": t})
        if t <= budget:
            return text, spec[0], t, trace
    # floor still over budget: refuse rather than mutilate
    refusal = (
        "PAGE_TOO_LARGE: even the floor projection (rung 5) exceeds the budget "
        f"({trace[-1]['tokens']} > {budget} tokens).\n"
        "Cheaper routes: get_page_view(view='outline'), "
        "get_page_view(location={'region':'r1'}), find_elements(query=...)."
    )
    return refusal, 6, ntok(refusal), trace
