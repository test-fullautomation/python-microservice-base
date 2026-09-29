// robot-grid: what editing a step needs, without a DOM (tests call these):
// finding keywords as the user types, laying a call's values out on the
// keyword's parameters, and turning the filled parameters back into the
// argument cells Robot reads.

/** Robot's name matching: case, spaces and underscores do not count. */
export function norm(s) {
  return String(s == null ? '' : s).replace(/[\s_]+/g, '').toLowerCase();
}

/** How the typed words sit in a name: 1 starts its words in order, 2 in order with words between, 0 not. */
function wordOrder(nameWords, words) {
  let at = 0;
  let gaps = false;
  for (const w of words) {
    let found = -1;
    for (let j = at; j < nameWords.length; j++) {
      if (nameWords[j].startsWith(w)) { found = j; break; }
    }
    if (found < 0) return 0;
    if (found !== at) gaps = true;
    at = found + 1;
  }
  return gaps ? 2 : 1;
}

/**
 * Keywords for a typed text, best first: a name that starts with it; then
 * one whose words start with the typed words, in order ("sh be eq" -> Should
 * Be Equal), then with other words between (Should Not Be Equal); then one
 * containing every word; then any containing the text. "Owner.Name" narrows
 * to one library or resource.
 * @param {object[]} list  catalog_list entries ({name, owner, owner_type, args, shortdoc})
 * @returns {object[]}
 */
export function filterKeywords(list, query, limit) {
  limit = limit || 12;
  const raw = String(query || '').trim();
  let owner = '';
  let q = raw;
  const dot = raw.lastIndexOf('.');
  if (dot > 0) { owner = norm(raw.slice(0, dot)); q = raw.slice(dot + 1); }
  const nq = norm(q);
  const words = q.toLowerCase().split(/[\s_]+/).filter(Boolean);
  const scored = [];
  (list || []).forEach((k, i) => {
    if (owner && norm(k.owner) !== owner) return;
    const n = norm(k.name);
    const lower = k.name.toLowerCase();
    let score;
    if (!nq) score = 5;
    else if (n.startsWith(nq)) score = 0;
    else {
      const order = words.length ? wordOrder(lower.split(/[\s_]+/), words) : 0;
      if (order) score = order;
      else if (words.every((w) => lower.includes(w))) score = 3;
      else if (n.includes(nq)) score = 4;
      else return;
    }
    scored.push({ k, score, i });
  });
  scored.sort((a, b) => a.score - b.score || a.k.name.length - b.k.name.length || a.i - b.i);
  return scored.slice(0, limit).map((s) => s.k);
}

function kinds(kw) {
  const args = (kw && kw.args) || [];
  return {
    positional: args.filter((a) => a.kind === 'POSITIONAL_ONLY' || a.kind === 'POSITIONAL_OR_NAMED'),
    varPos: args.find((a) => a.kind === 'VAR_POSITIONAL') || null,
    namedOnly: args.filter((a) => a.kind === 'NAMED_ONLY'),
    varNamed: args.find((a) => a.kind === 'VAR_NAMED') || null
  };
}

function stripName(value, name) {
  return value.startsWith(name + '=') ? value.slice(name.length + 1) : value;
}

/**
 * A call's values on the keyword's parameters: what the editor shows.
 * `cells` are the grid's cells of the row ({v, p, kw}); `kw` the keyword, or
 * null for one the file cannot resolve (then every value is a free cell).
 * The cells after a keyword named in a cell (Run Keyword and friends) are
 * that keyword's, so they stay together as the outer keyword's *args.
 */
export function slotsFor(kw, cells) {
  cells = cells || [];
  if (!kw) return { free: cells.map((c) => c.v) };
  const k = kinds(kw);
  const slots = {
    positional: k.positional.map((a) => ({ name: a.name, required: !!a.required, default: a.default, type: a.type, value: '' })),
    varargs: k.varPos ? { name: k.varPos.name, values: [] } : null,
    named: k.namedOnly.map((a) => ({ name: a.name, required: !!a.required, default: a.default, type: a.type, value: '' })),
    kwargs: k.varNamed ? { name: k.varNamed.name, pairs: [] } : null,
    extra: []
  };
  let nested = false;
  cells.forEach((c) => {
    const p = c.p || '';
    if (nested) {
      if (slots.varargs) slots.varargs.values.push(c.v); else slots.extra.push(c.v);
      return;
    }
    const pos = slots.positional.find((s) => s.name === p);
    const named = slots.named.find((s) => s.name === p);
    if (pos) {
      pos.value = stripName(c.v, p);
      if (c.kw) nested = true;
    } else if (named) {
      named.value = stripName(c.v, p);
    } else if (p.startsWith('**') && slots.kwargs) {
      const at = c.v.indexOf('=');
      slots.kwargs.pairs.push({ key: at > 0 ? c.v.slice(0, at) : c.v, value: at > 0 ? c.v.slice(at + 1) : '' });
    } else if (p.startsWith('*') && slots.varargs) {
      slots.varargs.values.push(c.v);
    } else {
      slots.extra.push(c.v);
    }
  });
  return slots;
}

/** Move values onto another keyword's parameters, by name where they match. */
export function carrySlots(from, kw) {
  const to = slotsFor(kw, []);
  if (!from) return to;
  if (to.free) {
    to.free = []
      .concat((from.positional || []).map((s) => s.value).filter((v) => v !== ''))
      .concat(from.varargs ? from.varargs.values : [])
      .concat(from.free || []);
    return to;
  }
  const byName = {};
  (from.positional || []).concat(from.named || []).forEach((s) => { if (s.value !== '') byName[s.name] = s.value; });
  to.positional.forEach((s) => { if (byName[s.name] != null) s.value = byName[s.name]; });
  to.named.forEach((s) => { if (byName[s.name] != null) s.value = byName[s.name]; });
  if (from.free && from.free.length) {
    // An unknown keyword's values fill the new one's parameters in order.
    const rest = from.free.slice();
    to.positional.forEach((s) => { if (s.value === '' && rest.length) s.value = rest.shift(); });
    if (to.varargs) to.varargs.values = rest; else to.extra = rest;
  }
  return to;
}

/**
 * The argument cells for filled slots, or {error}. Positional values go in
 * order; after a skipped optional one the rest are passed by name (then
 * *args cannot follow: the skipped ones get their defaults instead). A
 * value that looks like "name=..." for a parameter is escaped ("name\=...")
 * so Robot does not take it as a named argument.
 */
export function argsFromSlots(kw, slots) {
  if (slots.free) return { args: slots.free.filter((v) => v !== '') };
  const k = kinds(kw);
  const namedNames = new Set(k.positional.map((a) => a.name).concat(k.namedOnly.map((a) => a.name)));
  const escape = (v) => {
    const m = /^([^=\\]+)=/.exec(v);
    return m && (namedNames.has(m[1]) || slots.kwargs) ? v.replace('=', '\\=') : v;
  };
  const out = [];
  const pos = slots.positional;
  let last = -1;
  pos.forEach((s, i) => { if (s.value !== '') last = i; });
  const vargs = slots.varargs ? slots.varargs.values.filter((v) => v !== '') : [];
  if (vargs.length) last = pos.length - 1;
  let byName = false;
  for (let i = 0; i <= last; i++) {
    const s = pos[i];
    if (s.value === '') {
      if (s.required) return { error: 'Fill in ' + s.name + '.' };
      if (vargs.length) {
        if (s.default == null) return { error: 'Fill in ' + s.name + ': the values after it are positional.' };
        out.push(String(s.default));
        continue;
      }
      byName = true;
      continue;
    }
    out.push(byName ? s.name + '=' + s.value : escape(s.value));
  }
  for (let i = last + 1; i < pos.length; i++) {
    if (pos[i].required) return { error: 'Fill in ' + pos[i].name + '.' };
  }
  vargs.forEach((v) => out.push(escape(v)));
  for (const s of slots.named) {
    if (s.value === '') {
      if (s.required) return { error: 'Fill in ' + s.name + '.' };
      continue;
    }
    out.push(s.name + '=' + s.value);
  }
  if (slots.kwargs) {
    for (const p of slots.kwargs.pairs) {
      if (!p.key && !p.value) continue;
      if (!/^[^=\s]+$/.test(p.key)) return { error: 'A named argument needs a name.' };
      out.push(p.key + '=' + p.value);
    }
  }
  (slots.extra || []).forEach((v) => { if (v !== '') out.push(v); });
  return { args: out };
}

// ---- variables in scope ------------------------------------------------------

/** Robot's own variables, always there. */
export const BUILTIN_VARIABLES = [
  '${EMPTY}', '@{EMPTY}', '&{EMPTY}', '${SPACE}', '${TRUE}', '${FALSE}', '${NONE}', '${/}', '${:}', '${\\n}',
  '${CURDIR}', '${TEMPDIR}', '${EXECDIR}', '${OUTPUT DIR}', '${OUTPUT FILE}', '${LOG FILE}', '${REPORT FILE}',
  '${TEST NAME}', '@{TEST TAGS}', '${TEST DOCUMENTATION}', '${TEST STATUS}', '${TEST MESSAGE}',
  '${PREV TEST NAME}', '${PREV TEST STATUS}', '${PREV TEST MESSAGE}', '${SUITE NAME}', '${SUITE SOURCE}',
  '${SUITE DOCUMENTATION}', '&{SUITE METADATA}', '${SUITE STATUS}', '${SUITE MESSAGE}', '${KEYWORD STATUS}',
  '${KEYWORD MESSAGE}', '${LOG LEVEL}', '&{OPTIONS}'
];

const VAR_RE = /^[$@&%]\{(.+)\}$/;

/** "${a}=" / "@{a}" / "${a}=default" -> "${a}", "@{a}". */
function varName(cell) {
  const m = /^([$@&]\{[^}]+\})/.exec(String(cell || '').trim());
  return m ? m[1] : null;
}

function* itemsOf(data) {
  for (const s of ((data && data.grid && data.grid.sections) || [])) {
    for (const it of (s.items || [])) yield { section: s, item: it };
  }
}

/**
 * The variables a step on `line` can use, nearest first:
 *   the test's / keyword's own -- [Arguments], assignments and FOR / EXCEPT
 *   variables of the rows above it, Set Test / Suite / Global / Local
 *   Variable -- then the file's and its resources' Variables sections, then
 *   Robot's built-in ones. [{name, source}], each name once.
 */
export function variablesInScope(data, line) {
  const out = [];
  const seen = new Set();
  const add = (name, source) => {
    if (!name) return;
    const key = norm(name.slice(2, -1)) + name[0];
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ name, source });
  };
  for (const { item } of itemsOf(data)) {
    const rows = item.rows || [];
    const inside = rows.some((r) => r.line === line) || (item.line <= line && rows.length && rows[rows.length - 1].line >= line);
    if (!inside) continue;
    const local = [];
    for (const r of rows) {
      if (r.line >= line) break;
      const cells = (r.cells || []).map((c) => c.v);
      if (r.type === 'ARGUMENTS') cells.forEach((c) => local.push([varName(c), 'argument']));
      (r.assign || []).forEach((a) => local.push([varName(a), 'assigned on line ' + r.line]));
      if (r.type === 'FOR') {
        for (const c of cells) { if (/^IN( RANGE| ENUMERATE| ZIP)?$/.test(c)) break; local.push([varName(c), 'FOR on line ' + r.line]); }
      }
      if (r.type === 'EXCEPT') {
        const as = cells.indexOf('AS');
        if (as >= 0) local.push([varName(cells[as + 1]), 'EXCEPT on line ' + r.line]);
      }
      if (/^set (test|suite|global|local|task) variable$/i.test(String(r.keyword || '')) && cells.length) {
        const v = cells[0].replace(/^\\/, '');
        local.push([varName(v) || (/^[$@&]/.test(v) ? null : '${' + v + '}'), 'set on line ' + r.line]);
      }
    }
    local.reverse().forEach(([n, s]) => add(n, s));
    break;
  }
  ((data && data.variables) || []).forEach((v) => add(varName(v.name), v.source));
  BUILTIN_VARIABLES.forEach((n) => add(n, 'Robot'));
  return out;
}

/**
 * The variable being typed at `caret` in `text` -- "${ab" in "x ${ab|" -- and
 * the matching ones: {start, end, hits} or null. The sigil typed is kept:
 * "@{" offers ${LIST} as @{LIST}.
 */
export function variableAt(text, caret, vars, limit) {
  const before = String(text).slice(0, caret);
  const m = /([$@&%])\{([^{}]*)$/.exec(before);
  if (!m) return null;
  const sigil = m[1];
  const typed = norm(m[2]);
  const after = String(text).slice(caret);
  const close = /^[^{}\s]*\}/.exec(after);
  const hits = (vars || []).filter((v) => norm(v.name.slice(2, -1)).includes(typed))
    .sort((a, b) => (norm(a.name.slice(2, -1)).startsWith(typed) ? 0 : 1) - (norm(b.name.slice(2, -1)).startsWith(typed) ? 0 : 1))
    .slice(0, limit || 12)
    .map((v) => Object.assign({}, v, { insert: sigil + v.name.slice(1) }));
  return { start: m.index, end: caret + (close ? close[0].length : 0), hits };
}

// ---- block headers -----------------------------------------------------------

const FLAVOR_RE = /^IN( RANGE| ENUMERATE| ZIP)?$/;

/** A FOR row's cells as {variables, flavor, values}. */
export function parseFor(cells) {
  const v = (cells || []).map((c) => (typeof c === 'string' ? c : c.v));
  const at = v.findIndex((c) => FLAVOR_RE.test(c));
  return at < 0 ? { variables: v, flavor: 'IN', values: [] }
    : { variables: v.slice(0, at), flavor: v[at], values: v.slice(at + 1) };
}

/** A WHILE row's cells as {condition, limit}. */
export function parseWhile(cells) {
  const v = (cells || []).map((c) => (typeof c === 'string' ? c : c.v));
  const limit = v.find((c) => /^limit=/i.test(c));
  return { condition: v[0] || '', limit: limit ? limit.slice(6) : '' };
}

/** A THREAD row's cells (RobotFramework AIO) as {name, daemon}; daemon defaults to true. */
export function parseThread(cells) {
  const v = (cells || []).map((c) => (typeof c === 'string' ? c : c.v));
  const d = String(v[1] == null ? 'true' : v[1]).trim().toLowerCase();
  return { name: v[0] || '', daemon: !['false', 'no', 'f', '0'].includes(d) };
}

/** An EXCEPT row's cells as {patterns, type, variable}. */
export function parseExcept(cells) {
  const v = (cells || []).map((c) => (typeof c === 'string' ? c : c.v));
  const as = v.indexOf('AS');
  const body = as >= 0 ? v.slice(0, as) : v;
  const type = body.find((c) => /^type=/i.test(c));
  return { patterns: body.filter((c) => !/^type=/i.test(c)), type: type ? type.slice(5) : '', variable: as >= 0 ? v[as + 1] || '' : '' };
}
