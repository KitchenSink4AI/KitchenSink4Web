"""Emit corpus B's two GENERATED fixtures, deterministically: `dom50k.html`
and `bigform.html`.

Every other page in corpus B is hand-written, because a fixture you cannot
read is a fixture you cannot trust. These two are not hand-written for the
same reason: 50,000 nodes and 320 form fields are not reviewable by eye, and
a hand-maintained file at that size drifts the moment anybody edits it.

PLAN 1.3 names a 50,000-node DOM and S1 needs it for the degradation rungs
and the latency ladder. There are two honest ways to build one and this
repository picks the first, stated here so nobody has to reverse-engineer the
choice from the output:

  1. **A generator writes the file and the FILE is committed.** The fixture on
     disk is the fixture the browser loads. Byte-identical every run, no
     script executes, and the node count is a property of the file rather
     than a property of how fast the machine ran.
  2. An inline script builds the nodes synchronously before load completes.
     Cheaper to commit and worse to trust: the page is then only as
     deterministic as the engine that runs it, and corpus B already carries a
     mutating page, a console flood, and a virtualized list, so adding a
     fourth page whose node count depends on timing would make the one
     measurement this page exists for the least reliable number in the set.

Regenerating is idempotent. The count is computed rather than eyeballed, and
the script asserts the total before it writes, so a future edit to the block
shape cannot silently produce a 47,000-node "50k" page.

Run:  .venv/Scripts/python.exe -X utf8 corpus/b/_generate.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = 50_000

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Corpus B: a 50,000-node DOM</title>
<style>
body { font: 13px system-ui, sans-serif; margin: 0; padding: 12px; }
table { border-collapse: collapse; margin: 0 0 8px; }
td { border: 1px solid #ddd; padding: 1px 4px; }
h2 { font-size: 14px; margin: 8px 0 2px; }
</style>
</head>
<body>
<h1>Fifty thousand nodes</h1>
<p>A deliberately large but otherwise ordinary document: sections, headings,
tables, and in-prose links. Nothing here is adversarial. The only thing being
tested is size, so the projection has to reach its capped rungs on shape it
would otherwise handle comfortably.</p>
<main>
"""

TAIL = """</main>
<footer><p>End of the large document.</p></footer>
</body>
</html>
"""

#: Every tag in HEAD and TAIL, counted once so the arithmetic below is
#: checkable by reading rather than by running.
FIXED = 11  # html head meta title style body h1 p main footer p

ROWS_PER_SECTION = 16
#: section + h2 + table + tbody, then each row is tr + 3 td + 1 a.
PER_SECTION = 4 + ROWS_PER_SECTION * 5


def section(k: int) -> str:
    rows = "".join(
        f'<tr><td>{k}.{i}</td>'
        f'<td><a href="/record/{k}-{i}">Record {k}-{i}</a></td>'
        f'<td>ok</td></tr>'
        for i in range(ROWS_PER_SECTION))
    return (f'<section id="s{k}"><h2>Section {k}</h2>'
            f'<table><tbody>{rows}</tbody></table></section>\n')


def build() -> tuple[str, int]:
    parts = [HEAD]
    total = FIXED
    k = 0
    # Reserve one element for the padding container, so the pad can always
    # close the remaining gap exactly.
    while total + PER_SECTION <= TARGET - 1:
        parts.append(section(k))
        total += PER_SECTION
        k += 1
    pad = TARGET - total - 1
    parts.append('<div id="pad">' + "<span>.</span>" * pad + "</div>\n")
    total += 1 + pad
    parts.append(TAIL)
    return "".join(parts), total


# ---------------------------------------------------------------------------
# bigform.html: the capped-inventory fixture
# ---------------------------------------------------------------------------
#
# The degradation ladder's fifth rung caps the form inventory, and a cap that
# has never been exercised is a cap nobody has debugged. Corpus A's httpbin
# form has eleven controls and every hand-written fixture in the repo has
# fewer than twenty, so nothing in the corpus reaches the rung. This page
# does: 320 controls in one form, across sixteen fieldsets, with a mix of
# types so the inventory cannot cap by taking the first N of one shape.
#
# Two things are planted for the cap to be judged against. The SUBMIT button
# is the last control in the document, so an inventory that truncates by
# document order loses the only control that does anything. And three secret
# fields sit at positions 240, 241, and 300, well past any plausible cap, so
# a redaction rule that only runs over the retained slice leaks them.

FIELD_TYPES = ("text", "email", "tel", "url", "number", "date")
BIGFORM_FIELDS = 320
BIGFORM_PER_SET = 20

#: (index, id, kind) for the fields that are not ordinary text.
BIGFORM_SECRETS = {
    240: ("password", "password", "current-password"),
    241: ("otp", "text", "one-time-code"),
    300: ("cardnumber", "text", "cc-number"),
}


def bigform_field(i: int) -> str:
    if i in BIGFORM_SECRETS:
        name, itype, auto = BIGFORM_SECRETS[i]
        return (f'<label for="f{i}">Sensitive field {i}</label>'
                f'<input id="f{i}" name="{name}_{i}" type="{itype}" '
                f'autocomplete="{auto}">\n')
    if i % 17 == 0:
        opts = "".join(f"<option>Choice {j}</option>" for j in range(1, 5))
        return (f'<label for="f{i}">Field {i}, a choice</label>'
                f'<select id="f{i}" name="field_{i}">{opts}</select>\n')
    if i % 11 == 0:
        return (f'<label><input id="f{i}" name="field_{i}" type="checkbox"> '
                f'Field {i}, a flag</label>\n')
    if i % 23 == 0:
        return (f'<label for="f{i}">Field {i}, free text</label>'
                f'<textarea id="f{i}" name="field_{i}" rows="2"></textarea>\n')
    kind = FIELD_TYPES[i % len(FIELD_TYPES)]
    return (f'<label for="f{i}">Field {i}, {kind}</label>'
            f'<input id="f{i}" name="field_{i}" type="{kind}">\n')


def build_bigform() -> str:
    parts = ["""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Corpus B: a form with 320 fields</title>
<style>
body { font: 13px system-ui, sans-serif; margin: 0; padding: 12px; }
label { display: block; margin-top: 4px; }
fieldset { margin: 10px 0; }
</style>
</head>
<body>
<h1>Annual compliance return</h1>
<p>Three hundred and twenty controls in one form, which is what a government
return or an enterprise settings page actually looks like. The submit button
is the last control in the document and three sensitive fields sit past field
two hundred, so an inventory that caps by document order loses the action and
a redaction that only covers the retained slice leaks the secrets.</p>
<form name="return" method="post" action="/compliance/submit">
"""]
    for i in range(BIGFORM_FIELDS):
        if i % BIGFORM_PER_SET == 0:
            if i:
                parts.append("</fieldset>\n")
            parts.append(f'<fieldset><legend>Part '
                         f'{i // BIGFORM_PER_SET + 1}</legend>\n')
        parts.append(bigform_field(i))
    parts.append("</fieldset>\n")
    parts.append("""<button type="submit" id="submit-return">Submit return
</button>
</form>
</body>
</html>
""")
    return "".join(parts)


def main() -> None:
    html, total = build()
    assert total == TARGET, f"built {total} elements, wanted {TARGET}"
    out = HERE / "dom50k.html"
    out.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {out} : {total} elements, "
          f"{len(html.encode('utf-8')) / 1024:.0f} KB")

    form = build_bigform()
    controls = form.count("<input") + form.count("<select") + \
        form.count("<textarea") + form.count("<button")
    assert controls == BIGFORM_FIELDS + 1, \
        f"built {controls} controls, wanted {BIGFORM_FIELDS + 1}"
    out = HERE / "bigform.html"
    out.write_text(form, encoding="utf-8", newline="\n")
    print(f"wrote {out} : {controls} controls "
          f"({BIGFORM_FIELDS} fields plus submit), "
          f"{len(form.encode('utf-8')) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
