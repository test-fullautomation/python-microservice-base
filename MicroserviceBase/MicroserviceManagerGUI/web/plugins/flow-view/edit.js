// flow-view: editing a flow in its diagram (when the host passes editable: true).
//
// Every change is one edit sent to the host (ctx.edit), which has the runner
// apply it to the text in Script as an unsaved change -- flow_edit.py rewires
// the edges and the fork's validator must accept the result -- and pushes the
// redrawn flow back. So the file stays the one source: Script, the diagram and
// the run read the same text.
//
//   drag a palette item onto a + (drop zone)     insert that kind of step there
//   drag a step onto a +                          move it there
//   click a step                                  its fields; Apply, Delete, Wrap in loop / try
//   Delete / Escape                               delete the selected step / deselect
//   Undo                                          the host puts back the text before the last edit

const PALETTE = [
  ['keyword', 'Keyword', 'Call a keyword: a Python function or a Robot keyword'],
  ['gate', 'Gate', 'Wait until a keyword passes, at most a timeout'],
  ['sleep', 'Sleep', 'Wait a fixed time'],
  ['flow', 'Sub-flow', 'Call another flow file as one step'],
  ['decision', 'Decision', 'Branch on a condition: yes / no'],
  ['loop', 'Loop', 'Repeat a body, bounded'],
  ['try', 'Try', 'Route a failure to a recovery'],
  ['phase', 'Test', 'A new test case (phase)'],
];

// What a new step starts as: runnable at once, refined in its fields.
const DEFAULTS = {
  keyword: { keyword: 'No Operation' },
  gate: { keyword: 'Should Be True', args: ['${True}'], timeout: '30s' },
  sleep: { duration: '1s' },
  decision: { condition: '${True}' },
  loop: { max_loops: 3 },
  try: {},
  phase: { role: 'test', name: 'New Test' },
};

const FIELDS = {
  keyword: ['id', 'keyword', 'args', 'assign'],
  gate: ['id', 'keyword', 'args', 'timeout', 'interval', 'on_timeout', 'assign'],
  sleep: ['id', 'duration'],
  decision: ['id', 'condition'],
  loop: ['id', 'max_loops', 'max_seconds', 'every'],
  try: ['id'],
  flow: ['id', 'file', 'params'],
};

const LABELS = {
  id: 'Id', keyword: 'Keyword', args: 'Arguments (one per line)', assign: 'Assign to',
  timeout: 'Timeout', interval: 'Every', on_timeout: 'On timeout', duration: 'Duration',
  condition: 'Condition', max_loops: 'Max rounds', max_seconds: 'Max time', every: 'Round at least',
  file: 'Sub-flow file', params: 'Arguments (NAME=value, one per line)',
};

export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** The step with `id` in the runner's structure of the flow (not inside sub-flows). */
export function findStep(flow, id) {
  let found = null;
  const walk = (steps) => (steps || []).forEach((s) => {
    if (found) return;
    if (s.id === id) { found = s; return; }
    ['yes', 'no', 'body', 'recovery'].forEach((k) => walk(s[k]));
  });
  [flow && flow.setup].concat((flow && flow.tests) || [], [flow && flow.teardown])
    .filter(Boolean).forEach((p) => walk(p.steps));
  return found;
}

export function toolbar(state, data) {
  if (!data || !data.editable) return '';
  if (!state.editing) {
    return '<div class="fv-toolbar"><button type="button" class="fv-btn" data-act="edit" title="Drag steps in, move them, change their fields">✎ Edit flow</button>' +
      '<span class="fv-msg">' + esc(state.message || '') + '</span></div>';
  }
  const chips = PALETTE.map(([kind, label, title]) =>
    '<span class="fv-chip fv-chip-' + kind + '" data-kind="' + kind + '" title="' + esc(title) + ' — drag onto a +">' +
    esc(label) + '</span>').join('');
  return '<div class="fv-toolbar fv-editing">' +
    '<span class="fv-palette">' + chips + '</span>' +
    '<button type="button" class="fv-btn" data-act="undo"' + (data.undo ? '' : ' disabled') + ' title="Put back the text before the last edit">↶ Undo</button>' +
    '<button type="button" class="fv-btn fv-btn-primary" data-act="done">Done</button>' +
    '<span class="fv-msg' + (state.error ? ' fv-msg-error' : '') + '">' +
    esc(state.message || 'Drag a step onto a + to add it; drag a step to move it; click one to change it.') + '</span></div>';
}

export function panel(state, data) {
  if (!state.editing) return '';
  if (state.ask) {
    return '<div class="fv-panel"><b>New sub-flow</b>' +
      '<label class="fv-field"><span>' + LABELS.file + ' (relative to this file)</span>' +
      '<input type="text" id="fv-ask-file" value="sub/" spellcheck="false"></label>' +
      '<div class="fv-actions"><button type="button" class="fv-btn fv-btn-primary" data-act="ask-ok">Add</button>' +
      '<button type="button" class="fv-btn" data-act="ask-cancel">Cancel</button></div></div>';
  }
  const s = state.selected && findStep(data.flow, state.selected);
  if (!s) return '';
  const fields = FIELDS[s.kind] || ['id'];
  const value = (f) => {
    if (f === 'args') return (s.args || []).join('\n');
    if (f === 'params') return Object.keys(s.args || {}).map((k) => k + '=' + s.args[k]).join('\n');
    if (f === 'assign') return (s.assign || []).join(', ');
    return s[f] == null ? '' : s[f];
  };
  const input = (f) => {
    if (f === 'on_timeout') {
      const v = value(f) || 'unknown';
      return '<select id="fv-f-' + f + '">' + ['unknown', 'fail'].map((o) =>
        '<option' + (o === v ? ' selected' : '') + '>' + o + '</option>').join('') + '</select>';
    }
    if (f === 'args' || f === 'params') {
      return '<textarea id="fv-f-' + f + '" rows="2" spellcheck="false">' + esc(value(f)) + '</textarea>';
    }
    return '<input type="text" id="fv-f-' + f + '" value="' + esc(value(f)) + '" spellcheck="false">';
  };
  const wrap = ['keyword', 'gate', 'sleep', 'flow', 'loop', 'try'].includes(s.kind)
    ? '<button type="button" class="fv-btn" data-act="wrap-loop">Wrap in loop</button>' +
      '<button type="button" class="fv-btn" data-act="wrap-try">Wrap in try</button>' : '';
  return '<div class="fv-panel"><b>' + esc(s.kind) + '</b> <span class="fv-muted">' + esc(s.id) + '</span>' +
    '<div class="fv-fields">' + fields.map((f) =>
      '<label class="fv-field"><span>' + esc(LABELS[f] || f) + '</span>' + input(f) + '</label>').join('') + '</div>' +
    '<div class="fv-actions"><button type="button" class="fv-btn fv-btn-primary" data-act="apply">Apply</button>' +
    wrap + '<button type="button" class="fv-btn fv-btn-danger" data-act="delete">Delete</button></div></div>';
}

/** The fields of the panel as an update's attrs. */
export function readPanel(root, kind) {
  const attrs = {};
  (FIELDS[kind] || ['id']).forEach((f) => {
    const el = root.querySelector('#fv-f-' + f);
    if (!el) return;
    const v = el.value.trim();
    if (f === 'args') attrs.args = v ? v.split('\n').map((x) => x.trim()).filter((x) => x !== '') : null;
    else if (f === 'params') {
      const obj = {};
      v.split('\n').map((x) => x.trim()).filter(Boolean).forEach((line) => {
        const i = line.indexOf('=');
        if (i > 0) obj[line.slice(0, i).trim()] = line.slice(i + 1).trim();
      });
      attrs.args = Object.keys(obj).length ? obj : null;
    } else if (f === 'assign') attrs.assign = v ? v.split(',').map((x) => x.trim()).filter(Boolean) : null;
    else if (f === 'max_loops') attrs.max_loops = v ? Number(v) : null;
    else attrs[f] = v || null;
  });
  return attrs;
}

/** A new step of `kind` at `place`, as an insert edit. */
export function insertEdit(kind, place, extra) {
  return Object.assign({ op: 'insert', kind, attrs: Object.assign({}, DEFAULTS[kind] || {}, extra || {}) }, place);
}

/** The first label of a palette kind, for the drag ghost. */
export function kindLabel(kind) {
  const p = PALETTE.find((x) => x[0] === kind);
  return p ? p[1] : kind;
}
