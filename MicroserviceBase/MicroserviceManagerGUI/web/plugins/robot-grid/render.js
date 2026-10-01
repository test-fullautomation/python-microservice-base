// robot-grid: a Robot Framework suite or resource as a grid, one row per
// statement, the way the runner parsed it (robot_grid.py): the keyword a row
// calls in the first column, then one cell per argument, each labelled with
// the parameter it fills. No DOM: grid.js puts the markup into the frame;
// tests call renderGrid().

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** A value with its ${variables} marked. */
function value(v) {
  return esc(v).replace(/([$@&%]\{[^}]*\})/g, '<span class="rg-var">$1</span>');
}

/** "retry, retry_interval, name, *args" -- a keyword's parameters, in call order. */
export function signature(kw) {
  return (kw && kw.args || []).map((a) => {
    const prefix = a.kind === 'VAR_POSITIONAL' ? '*' : a.kind === 'VAR_NAMED' ? '**' : '';
    return prefix + a.name + (a.default != null && a.default !== '' ? '=' + a.default : '') +
      (a.type ? ': ' + a.type : '');
  }).join(', ');
}

const CONTROL = new Set(['FOR', 'END', 'IF', 'ELSE IF', 'ELSE', 'INLINE IF', 'WHILE', 'TRY', 'EXCEPT',
  'FINALLY', 'BREAK', 'CONTINUE', 'RETURN STATEMENT', 'RETURN', 'THREAD']);

function row(r, keywords) {
  const cls = ['rg-row', 'rg-t-' + String(r.type || '').toLowerCase().replace(/[^a-z]+/g, '-')];
  if (r.error) cls.push('rg-has-error');
  const pad = 'padding-left:' + (0.5 + 1.1 * (r.depth || 0)) + 'rem';
  let first;
  if (r.keyword != null && r.keyword !== '') {
    const known = r.kw && keywords[r.kw];
    const assign = (r.assign || []).map((a) => '<span class="rg-assign">' + value(a) + '</span>').join('');
    const label = r.label ? '<span class="rg-label">' + esc(r.label) + '</span>' : '';
    first = '<td class="rg-kwcell" style="' + pad + '">' + label + assign +
      '<span class="rg-kw' + (known ? '' : ' rg-unknown') + '"' + (known ? ' data-kw="' + esc(r.kw) + '"' : '') +
      (known ? '' : ' title="Not found among the keywords this file can use"') + '>' + esc(r.keyword) + '</span></td>';
  } else {
    const control = CONTROL.has(String(r.type || '').toUpperCase());
    first = '<td class="rg-kwcell' + (control ? ' rg-control' : ' rg-setting') + '" style="' + pad + '">' +
      '<span class="rg-label">' + esc(r.label || (r.comment ? '' : r.type)) + '</span></td>';
  }
  const cells = (r.cells || []).map((c) => {
    const p = c.p ? '<span class="rg-p' + (c.p === '(extra)' ? ' rg-extra' : '') + '">' + esc(c.p) + '</span>' : '';
    const v = c.kw
      ? '<span class="rg-kw rg-nested" data-kw="' + esc(c.kw) + '">' + esc(c.v) + '</span>'
      : '<span class="rg-v">' + value(c.v) + '</span>';
    return '<td class="rg-cell' + (c.p === '(extra)' ? ' rg-cell-extra' : '') + '"' +
      (c.p === '(extra)' ? ' title="More values than the keyword takes"' : '') + '>' + p + v + '</td>';
  }).join('');
  const missing = (r.missing || []).length
    ? '<td class="rg-missing" title="Required, not given">needs ' + r.missing.map(esc).join(', ') + '</td>' : '';
  const comment = r.comment ? '<td class="rg-comment">' + esc(r.comment) + '</td>' : '';
  const error = r.error ? '<td class="rg-error">' + esc(r.error) + '</td>' : '';
  return '<tr class="' + cls.join(' ') + '" data-line="' + (r.line || '') + '">' +
    '<td class="rg-line">' + (r.line || '') + '</td>' + first + cells + missing + comment + error + '</tr>';
}

function table(rows, keywords) {
  if (!rows || !rows.length) return '<div class="rg-empty">Empty.</div>';
  return '<div class="rg-scroll"><table class="rg-table"><tbody>' +
    rows.map((r) => row(r, keywords)).join('') + '</tbody></table></div>';
}

/**
 * HTML of the whole grid.
 * @param {object} data {grid: {sections}, keywords, imports, catalog} as robot_grid.py reports it
 * @returns {string}
 */
export function renderGrid(data) {
  const keywords = (data && data.keywords) || {};
  const sections = (data && data.grid && data.grid.sections) || [];
  const imports = (data && data.imports) || [];
  const broken = imports.filter((i) => !i.ok);
  let html = '<div class="rg">';
  html += '<p class="rg-note">' + (data && data.catalog || 0) + ' keywords available from BuiltIn, ' +
    imports.filter((i) => i.ok).length + ' import' + (imports.filter((i) => i.ok).length === 1 ? '' : 's') +
    ' and the file itself. Hover a keyword for its arguments and documentation; click a row to find it in Script.</p>';
  if (broken.length) {
    html += '<ul class="rg-imports-bad">' + broken.map((i) =>
      '<li><strong>' + esc(i.name) + '</strong>' + (i.line ? ' (line ' + i.line + ')' : i.via ? ' (via ' + esc(i.via) + ')' : '') +
      ': ' + esc(i.error) + '</li>').join('') + '</ul>';
  }
  sections.forEach((s) => {
    html += '<section class="rg-section rg-s-' + esc(s.type) + '"><h3 class="rg-section-title" data-line="' + (s.line || '') + '">' +
      esc(s.title) + '</h3>';
    if (s.items) {
      html += s.items.length ? s.items.map((it) =>
        '<div class="rg-item"><div class="rg-item-name" data-line="' + (it.line || '') + '">' + esc(it.name) + '</div>' +
        table(it.rows, keywords) + '</div>').join('') : '<div class="rg-empty">Empty.</div>';
    } else {
      html += table(s.rows, keywords);
    }
    html += '</section>';
  });
  if (!sections.length) html += '<p class="rg-empty">Nothing in this file yet.</p>';
  return html + '</div>';
}

/** The hover card of a keyword. */
export function renderCard(kw) {
  if (!kw) return '';
  const params = (kw.args || []).map((a) => {
    const prefix = a.kind === 'VAR_POSITIONAL' ? '*' : a.kind === 'VAR_NAMED' ? '**' : '';
    return '<li><code>' + esc(prefix + a.name) + '</code>' +
      (a.type ? ' <span class="rg-card-type">' + esc(a.type) + '</span>' : '') +
      (a.default != null && a.default !== '' ? ' <span class="rg-card-default">= ' + esc(a.default) + '</span>'
        : a.required ? ' <span class="rg-card-req">required</span>' : '') +
      (a.kind === 'NAMED_ONLY' ? ' <span class="rg-card-default">named only</span>' : '') + '</li>';
  }).join('');
  const doc = String(kw.doc || kw.shortdoc || '').trim();
  return '<div class="rg-card-head"><span class="rg-card-name">' + esc(kw.name) + '</span>' +
    '<span class="rg-card-owner">' + esc(kw.owner) + ' · ' + esc(kw.owner_type) + '</span></div>' +
    (params ? '<ul class="rg-card-args">' + params + '</ul>' : '<div class="rg-card-none">No arguments.</div>') +
    (doc ? '<div class="rg-card-doc">' + esc(doc.length > 700 ? doc.slice(0, 700) + '…' : doc) + '</div>' : '');
}
