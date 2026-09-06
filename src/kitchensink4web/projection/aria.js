// KS4Web ARIA state: THE ONE STATE SOURCE for every read that prints an
// affordance.
//
// The field asked a question neither incumbent answers: "which tab is
// active?" The projection carried a partial answer (expanded, selected when
// true, current with its value thrown away) and `find_elements` carried
// almost none (three native DOM properties and nothing declared), so the same
// element described itself two ways depending on which tool found it. That is
// the divergence `visibility.js`, `payment.js`, and `activation.js` were each
// written to end, one classification along.
//
// Two rules the vocabulary follows, and the difference between them is not
// cosmetic:
//
// - A NATIVE property is printed BARE: `disabled`, `checked`, `required`,
//   `readonly`. The browser itself enforces these, so their presence is the
//   whole fact and a `=true` would be noise on every one of them.
// - A DECLARED (aria-) state is printed WITH ITS VALUE: `expanded=false`,
//   `selected=true`, `pressed=mixed`, `current=page`. The value is the
//   answer, and `aria-selected="false"` is a statement the page made, which
//   is a different fact from an element that never spoke. Dropping the false
//   half is what made "which tab is active" unanswerable: with only the true
//   half printed, silence meant either "not selected" or "not a tab", and the
//   caller could not tell which.
//
// COST. The aria half runs one pass over `el.attributes` rather than eight
// `getAttribute` calls, so an element with no aria-* attribute pays for the
// attributes it does have and nothing more. A page of plain links and inputs
// is charged the loop and no branch inside it.
function ksAriaState(el) {
  const native = [];
  if (el.disabled) native.push('disabled');
  if (el.checked) native.push('checked');
  if (el.required) native.push('required');
  if (el.readOnly) native.push('readonly');

  const attrs = el.attributes;
  if (!attrs || !attrs.length) return native;

  // Collected by key first, then emitted in a FIXED order below, so the
  // state string is a property of the element rather than of the order the
  // author happened to type the attributes in. A test that pins
  // `[expanded=false,selected=true]` must not fail because a page shipped
  // the attributes the other way round.
  const declared = {};
  for (let i = 0; i < attrs.length; i++) {
    const name = attrs[i].name;
    if (name.lastIndexOf('aria-', 0) !== 0) continue;
    const raw = attrs[i].value;
    if (typeof raw !== 'string') continue;
    const value = raw.trim().toLowerCase();
    if (!value) continue;
    switch (name) {
      case 'aria-expanded':
        if (value === 'true' || value === 'false') declared.expanded = value;
        break;
      case 'aria-selected':
        if (value === 'true' || value === 'false') declared.selected = value;
        break;
      case 'aria-pressed':
        if (value === 'true' || value === 'false' || value === 'mixed')
          declared.pressed = value;
        break;
      case 'aria-checked':
        // A native `checked` property already answered this for an INPUT.
        // Only a role-built checkbox, radio, switch, or menuitemcheckbox
        // needs the declared value, and printing both would be one fact
        // twice under two spellings.
        if (!('checked' in el)
            && (value === 'true' || value === 'false' || value === 'mixed'))
          declared.checked = value;
        break;
      case 'aria-disabled':
        // Deliberately NOT folded into the bare `disabled`. The browser does
        // not block a click on an aria-disabled div, so an actor that treats
        // the two as identical is wrong about what happens next. Same fact,
        // different enforcement, different spelling.
        if (value === 'true' && !el.disabled) declared.disabled = value;
        break;
      case 'aria-readonly':
        if (value === 'true' && !el.readOnly) declared.readonly = value;
        break;
      case 'aria-required':
        if (value === 'true' && !el.required) declared.required = value;
        break;
      case 'aria-current':
        // The VALUE is the point: `page`, `step`, `date`, `location`, and
        // `true` are five different claims about which item you are on, and
        // the old code printed the bare word `current` for all of them.
        if (value !== 'false') declared.current = value;
        break;
      case 'aria-invalid':
        if (value !== 'false') declared.invalid = value;
        break;
      case 'aria-busy':
        if (value === 'true') declared.busy = value;
        break;
      default:
        break;
    }
  }

  const ORDER = ['expanded', 'selected', 'checked', 'pressed', 'current',
                 'disabled', 'readonly', 'required', 'invalid', 'busy'];
  const out = native.slice();
  for (let i = 0; i < ORDER.length; i++) {
    const key = ORDER[i];
    if (declared[key] !== undefined) out.push(key + '=' + declared[key]);
  }
  return out;
}
