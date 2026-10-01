// robot-grid: the "Grid" view of Robot Framework suites and resources
// (file view type robot-grid). Runs in a sandboxed frame; the project view
// pushes what the runner found in the text in Script as the selection.
//
// Reading: hover a keyword for its parameters and documentation; click a
// line number (or any row of a read-only file) to show it in Script
// (ctx.reveal({ line })).
//
// Editing (when the host passes editable: true), every change is one edit
// sent to the host (ctx.edit), which has the runner apply it to the text in
// Script as an unsaved change and pushes the new grid back:
//   a keyword step or a setup / teardown   keyword with completion, one input per parameter
//   FOR / IF / ELSE IF / WHILE / EXCEPT    the header's fields; the block's actions (move, delete, branches)
//   TRY / ELSE / FINALLY                   the block's actions
//   a block's END                          + Add step here: steps (or blocks) at the end of the block
//   (and every block / branch row offers "Inside": the same, at the end of that part)
//   a setting, an import or a variable     its values (Documentation as text)
//   a test's or keyword's name             rename, delete
//   the end of a test or keyword           + Add step, or a FOR / IF / WHILE / TRY block (and THREAD,
//                                          when the project's Robot has it: RobotFramework AIO)
//   the end of the grid                    + Test case, Keyword, Setting, Variable
// Every value input completes ${variables} in scope.
import { renderGrid, renderCard, signature, esc } from './render.js';
import {
  filterKeywords, slotsFor, carrySlots, argsFromSlots, norm,
  variablesInScope, variableAt, parseFor, parseWhile, parseExcept, parseThread
} from './edit.js';
import { ensureStyle } from './style.js';

const FIXTURES = new Set(['SETUP', 'TEARDOWN', 'SUITE SETUP', 'SUITE TEARDOWN', 'TEST SETUP', 'TEST TEARDOWN']);
const HEADERS = new Set(['FOR', 'IF', 'ELSE IF', 'WHILE', 'EXCEPT', 'THREAD']);
const BLOCKS = new Set(['FOR', 'IF', 'WHILE', 'TRY', 'THREAD']);
const BRANCHES = new Set(['ELSE IF', 'ELSE', 'EXCEPT', 'FINALLY']);
const VALUE_ROWS = new Set(['DOCUMENTATION', 'TAGS', 'TIMEOUT', 'TEMPLATE', 'ARGUMENTS', 'RETURN STATEMENT', 'RETURN',
  'LIBRARY', 'RESOURCE', 'VARIABLES', 'METADATA', 'FORCE TAGS', 'DEFAULT TAGS', 'KEYWORD TAGS', 'VARIABLE',
  'TEST TIMEOUT', 'TEST TEMPLATE']);
const NEW_SETTINGS = ['Library', 'Resource', 'Variables', 'Documentation', 'Metadata', 'Suite Setup', 'Suite Teardown',
  'Test Setup', 'Test Teardown', 'Test Tags', 'Default Tags', 'Keyword Tags', 'Test Timeout', 'Test Template'];
const FLAVORS = ['IN', 'IN RANGE', 'IN ENUMERATE', 'IN ZIP'];

export function mount(el, ctx) {
  ensureStyle();
  let data = null;
  let editor = null;          // the open editor: { close() }
  let flashLine = null;       // highlight this row after the grid is redrawn
  const card = document.createElement('div');
  card.className = 'rg-card';
  card.hidden = true;

  // ---- floating boxes (hover card, completion lists) ----------------------
  function placeFloating(box, target, width) {
    const r = target.getBoundingClientRect();
    const docH = el.getBoundingClientRect().height;
    const w = Math.min(width, el.clientWidth - 16);
    box.style.width = w + 'px';
    box.style.left = Math.max(8, Math.min(r.left + window.scrollX, el.clientWidth - w - 8)) + 'px';
    const below = r.bottom + window.scrollY + 4;
    const h = box.offsetHeight;
    // Below the target; above it when that would run past the content (the
    // frame is as tall as its content, so a floating box must not make it grow).
    box.style.top = (below + h <= docH || r.top < h + 8 ? below : r.top + window.scrollY - h - 4) + 'px';
  }

  function keywordByKey(key) {
    if (!data) return null;
    if (data.keywords && data.keywords[key]) return data.keywords[key];
    return (data.catalog_list || []).find((k) => k.key === key) || null;
  }

  function hideCard() { card.hidden = true; }

  function showCard(target) {
    const kw = keywordByKey(target.getAttribute('data-kw'));
    if (!kw) return;
    card.innerHTML = renderCard(kw);
    card.hidden = false;
    placeFloating(card, target, 460);
  }

  // A completion list under an input: items [{html}], pick(i).
  function makeDrop() {
    const drop = document.createElement('div');
    drop.className = 'rg-drop';
    drop.hidden = true;
    el.appendChild(drop);
    const d = { el: drop, items: [], active: 0, pick: null, anchor: null };
    d.show = (anchor, items, pick, width) => {
      d.items = items; d.pick = pick; d.anchor = anchor;
      if (!items.length) { drop.hidden = true; return; }
      d.active = Math.min(d.active, items.length - 1);
      drop.innerHTML = items.map((it, i) => '<div class="rg-drop-item' + (i === d.active ? ' rg-active' : '') + '" data-i="' + i + '">' +
        it.html + '</div>').join('');
      drop.hidden = false;
      placeFloating(drop, anchor, width || 520);
      drop.querySelectorAll('.rg-drop-item').forEach((n) => n.addEventListener('mousedown', (e) => {
        e.preventDefault();
        d.pick(Number(n.getAttribute('data-i')));
      }));
    };
    d.hide = () => { drop.hidden = true; };
    d.visible = () => !drop.hidden && d.items.length > 0;
    /** Arrow keys, Enter / Tab and Escape while the list is open; true when handled. */
    d.key = (e) => {
      if (!d.visible()) return false;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        d.active = (d.active + (e.key === 'ArrowDown' ? 1 : -1) + d.items.length) % d.items.length;
        d.show(d.anchor, d.items, d.pick);
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        d.pick(d.active);
      } else if (e.key === 'Escape') {
        d.hide();
      } else {
        return false;
      }
      e.preventDefault();
      e.stopPropagation();
      return true;
    };
    return d;
  }

  // ${variables} in scope, completed in any value input of an editor.
  function completeVariables(root, line) {
    const drop = makeDrop();
    const vars = variablesInScope(data, line || 0);
    function update(input) {
      const at = variableAt(input.value, input.selectionStart || 0, vars, 12);
      if (!at || !at.hits.length) { drop.hide(); return; }
      drop.show(input, at.hits.map((v) => ({
        html: '<span class="rg-drop-name">' + esc(v.insert) + '</span><span class="rg-drop-owner">' + esc(v.source) + '</span>'
      })), (i) => {
        const v = at.hits[i];
        input.value = input.value.slice(0, at.start) + v.insert + input.value.slice(at.end);
        const caret = at.start + v.insert.length;
        input.setSelectionRange(caret, caret);
        drop.hide();
        input.focus();
      }, 360);
    }
    root.addEventListener('input', (e) => {
      if (e.target.matches('input.rg-in:not(.rg-in-kw), textarea.rg-in')) { drop.active = 0; update(e.target); }
    });
    root.addEventListener('keydown', (e) => {
      if (e.target.matches('input.rg-in:not(.rg-in-kw), textarea.rg-in')) drop.key(e);
    }, true);
    // Leaving the input closes the list (a click on the list keeps focus: mousedown is prevented).
    root.addEventListener('focusout', () => setTimeout(() => {
      if (document.activeElement !== drop.anchor) drop.hide();
    }, 150));
    return drop;
  }

  // ---- the grid -----------------------------------------------------------
  function show(next) {
    data = next || null;
    if (editor) editor.close();
    editor = null;
    el.querySelectorAll('.rg-drop').forEach((d) => d.remove());
    hideCard();
    if (!data || !data.grid) {
      el.innerHTML = '<p class="rg-empty">Nothing to show.</p>';
      return;
    }
    el.innerHTML = renderGrid(data);
    el.appendChild(card);
    el.classList.toggle('rg-editable', !!data.editable);
    const note = el.querySelector('.rg-note');
    if (note && data.editable) {
      note.insertAdjacentHTML('beforeend', ' <span class="rg-edit-hint">Click a row to change it.</span>' +
        (data.undo ? ' <button type="button" class="rg-btn rg-undo" title="Put back the text from before the last grid change">' +
                     'Undo last change</button>' : ''));
      const undo = note.querySelector('.rg-undo');
      if (undo) undo.addEventListener('click', () => sendFromNote({ op: 'undo' }, undo));
    }
    el.querySelectorAll('[data-kw]').forEach((k) => {
      k.addEventListener('mouseenter', () => { if (!editor) showCard(k); });
      k.addEventListener('mouseleave', hideCard);
    });
    el.querySelectorAll('.rg-section-title[data-line]').forEach((h) => {
      const line = Number(h.getAttribute('data-line'));
      if (line) h.addEventListener('click', () => ctx.reveal({ line }));
    });
    el.querySelectorAll('tr.rg-row[data-line]').forEach((tr) => {
      const line = Number(tr.getAttribute('data-line'));
      const row = findRow(line);
      const can = data.editable && row && editableRow(row);
      if (can) tr.classList.add('rg-row-editable');
      tr.addEventListener('click', (e) => {
        if (!line) return;
        if (can && !e.target.closest('.rg-line')) openFor(tr, row);
        else ctx.reveal({ line });
      });
    });
    if (data.editable) addEditControls();
    else {
      el.querySelectorAll('.rg-item-name[data-line]').forEach((h) => {
        const line = Number(h.getAttribute('data-line'));
        if (line) h.addEventListener('click', () => ctx.reveal({ line }));
      });
    }
    if (flashLine) {
      const tr = el.querySelector('tr.rg-row[data-line="' + flashLine + '"]');
      if (tr) tr.classList.add('rg-flash');
      flashLine = null;
    }
  }

  function findRow(line) {
    for (const s of (data.grid.sections || [])) {
      for (const r of (s.rows || [])) if (r.line === line) return Object.assign({ _section: s.type }, r);
      for (const it of (s.items || [])) {
        for (const r of it.rows) if (r.line === line) return Object.assign({ _section: s.type, _item: it }, r);
      }
    }
    return null;
  }

  function editableRow(r) {
    const t = String(r.type || '').toUpperCase();
    return t === 'KEYWORD' || FIXTURES.has(t) || HEADERS.has(t) || t === 'TRY' || t === 'ELSE' || t === 'FINALLY' ||
      t === 'END' || VALUE_ROWS.has(t);
  }

  /** The block or branch an END closes: the last FOR / IF / ELSE ... row above it at its depth. */
  function openerOf(end) {
    const rows = (end._item && end._item.rows) || [];
    let found = null;
    for (const r of rows) {
      if (r.line >= end.line) break;
      const t = String(r.type || '').toUpperCase();
      if ((r.depth || 0) === (end.depth || 0) && (BLOCKS.has(t) || BRANCHES.has(t))) found = r;
    }
    return found;
  }

  function openFor(tr, r) {
    const t = String(r.type || '').toUpperCase();
    if (t === 'KEYWORD') return openStep(tr, r, { op: 'set', line: r.line });
    if (FIXTURES.has(t)) return openStep(tr, r, { op: 'set', line: r.line }, { fixture: true });
    if (HEADERS.has(t)) return openHeader(tr, t, r, { op: 'header', line: r.line });
    if (t === 'TRY' || t === 'ELSE' || t === 'FINALLY') return openBlockBar(tr, t, r);
    if (t === 'END') return openEndBar(tr, r);
    if (VALUE_ROWS.has(t)) return openValues(tr, r, { op: 'values', line: r.line });
    return null;
  }

  // Add controls: steps and blocks at the end of every test and keyword,
  // rename / delete on their names, settings and variables at the end of
  // their sections, and a toolbar for new tests, keywords, settings, variables.
  function addEditControls() {
    el.querySelectorAll('.rg-item').forEach((item) => {
      const nameEl = item.querySelector('.rg-item-name');
      const itemLine = Number(nameEl.getAttribute('data-line'));
      const rows = item.querySelectorAll('tr.rg-row[data-line]');
      const last = rows.length ? Number(rows[rows.length - 1].getAttribute('data-line')) : null;
      const where = last ? { after: last } : { item: itemLine };
      let tbody = item.querySelector('tbody');
      if (!tbody) {
        item.querySelector('.rg-empty').outerHTML = '<div class="rg-scroll"><table class="rg-table"><tbody></tbody></table></div>';
        tbody = item.querySelector('tbody');
      }
      const add = document.createElement('tr');
      add.className = 'rg-add';
      add.innerHTML = '<td class="rg-line"></td><td colspan="40">' + addButtons() + '</td>';
      tbody.appendChild(add);
      wireAddButtons(add, add, where, last || itemLine);
      // The name: rename, delete.
      const name = nameEl.textContent;
      nameEl.innerHTML = '<span class="rg-item-title" title="Click to find it in Script">' + esc(name) + '</span>' +
        '<span class="rg-item-tools"><button type="button" class="rg-btn rg-mini rg-add-setting" ' +
        'title="[Documentation], [Tags], [Setup], [Teardown], ...">+ Setting</button>' +
        '<button type="button" class="rg-btn rg-mini rg-rename">Rename</button>' +
        '<button type="button" class="rg-btn rg-mini rg-btn-danger rg-del-item">Delete</button></span>';
      nameEl.querySelector('.rg-item-title').addEventListener('click', () => ctx.reveal({ line: itemLine }));
      nameEl.querySelector('.rg-add-setting').addEventListener('click', () => openItemSetting(nameEl, itemLine));
      nameEl.querySelector('.rg-rename').addEventListener('click', () => openRename(nameEl, name, itemLine));
      confirmButton(nameEl.querySelector('.rg-del-item'), 'Delete ' + name + '?', (b) => sendFromNote({ op: 'delete_item', line: itemLine }, b));
    });
    el.querySelectorAll('.rg-section').forEach((sec) => {
      const type = (sec.className.match(/rg-s-(\w+)/) || [])[1];
      if (type !== 'settings' && type !== 'variables') return;
      const tbody = sec.querySelector('tbody');
      if (!tbody) return;
      const add = document.createElement('tr');
      add.className = 'rg-add';
      add.innerHTML = '<td class="rg-line"></td><td colspan="40"><button type="button" class="rg-btn rg-add-btn">+ Add ' +
        (type === 'settings' ? 'setting' : 'variable') + '</button></td>';
      tbody.appendChild(add);
      add.querySelector('button').addEventListener('click', () =>
        openValues(add, null, { op: 'setting', section: type }, { before: true }));
    });
    const bar = document.createElement('div');
    bar.className = 'rg-toolbar';
    bar.innerHTML = '<span class="rg-toolbar-label">Add</span>' +
      '<button type="button" class="rg-btn" data-new="tests">+ Test case</button>' +
      '<button type="button" class="rg-btn" data-new="keywords">+ Keyword</button>' +
      '<button type="button" class="rg-btn" data-new="settings">+ Setting</button>' +
      '<button type="button" class="rg-btn" data-new="variables">+ Variable</button>';
    el.querySelector('.rg').appendChild(bar);
    bar.querySelectorAll('[data-new]').forEach((b) => b.addEventListener('click', () => {
      const kind = b.getAttribute('data-new');
      if (kind === 'tests' || kind === 'keywords') openNewItem(bar, kind);
      else openValues(bar, null, { op: 'setting', section: kind }, { panel: true });
    }));
  }

  /** The blocks this project's Robot has: THREAD only with RobotFramework AIO's. */
  function blockKinds() {
    return ['FOR', 'IF', 'WHILE', 'TRY'].concat(data && data.features && data.features.thread ? ['THREAD'] : []);
  }

  function addButtons() {
    return '<span class="rg-add-group"><button type="button" class="rg-btn rg-add-btn" data-add="step">+ Add step</button>' +
      '<span class="rg-add-or">or</span>' +
      blockKinds().map((b) => '<button type="button" class="rg-btn rg-add-btn rg-add-block" data-add="' + b + '">' + b + '</button>').join('') +
      '</span>';
  }

  function wireAddButtons(scope, anchor, where, line) {
    scope.querySelectorAll('[data-add]').forEach((b) => b.addEventListener('click', (e) => {
      e.stopPropagation();
      const what = b.getAttribute('data-add');
      if (what === 'step') openStep(anchor, null, Object.assign({ op: 'insert' }, where), { line, before: true });
      else if (what === 'TRY') sendAndReport({ op: 'block', ...where, block: { type: 'TRY' } }, b);
      else openHeader(anchor, what, null, Object.assign({ op: 'block' }, where), { before: true, line });
    }));
  }

  /** A button that asks again before doing something that cannot be seen in the grid first. */
  function confirmButton(button, question, run) {
    const label = button.textContent;
    let armed = false;
    button.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!armed) {
        armed = true;
        button.textContent = question + ' Click again';
        button.classList.add('rg-armed');
        setTimeout(() => { armed = false; button.textContent = label; button.classList.remove('rg-armed'); }, 3500);
        return;
      }
      run(button);
    });
  }

  // ---- one editor at a time ------------------------------------------------
  /**
   * An editor under `anchor` (a table row: a new row; anything else: a panel
   * after it). {box, q, msg, submit(edit, button), close}.
   */
  function openBox(anchor, lineLabel, html, opts) {
    if (editor) editor.close();
    hideCard();
    opts = opts || {};
    let box;
    const isRow = anchor.tagName === 'TR';
    if (isRow) {
      box = document.createElement('tr');
      box.className = 'rg-editor-row';
      box.innerHTML = '<td class="rg-line">' + esc(lineLabel) + '</td><td colspan="40"><div class="rg-editor">' + html + '</div></td>';
      if (opts.before) anchor.parentNode.insertBefore(box, anchor);
      else anchor.parentNode.insertBefore(box, anchor.nextSibling);
      if (opts.hideAnchor) anchor.hidden = true;
    } else {
      box = document.createElement('div');
      box.className = 'rg-editor rg-editor-panel';
      box.innerHTML = html;
      anchor.parentNode.insertBefore(box, anchor.nextSibling);
    }
    const q = (s) => box.querySelector(s);
    const drops = [completeVariables(box, opts.line)];
    const ed = {
      box, q,
      drops,
      close() {
        drops.forEach((d) => d.el.remove());
        box.remove();
        if (opts.hideAnchor) anchor.hidden = false;
        if (editor === ed) editor = null;
      },
      msg(text, bad) {
        const m = q('.rg-ed-msg');
        if (m) { m.textContent = text || ''; m.className = 'rg-ed-msg' + (bad ? ' rg-bad' : ''); }
      },
      submit(edit, button) {
        ed.msg('Applying…');
        if (button) button.disabled = true;
        return send(edit).catch((err) => {
          if (button) button.disabled = false;
          ed.msg(err.message || String(err), true);
        });
      }
    };
    box.addEventListener('click', (e) => e.stopPropagation());
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); ed.close(); return; }
      if (e.key === 'Enter' && !e.shiftKey && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'BUTTON' &&
          !e.target.classList.contains('rg-in-kw') && ed.apply) {
        e.preventDefault();
        ed.apply();
      }
    });
    editor = ed;
    return ed;
  }

  function input(value, placeholder, cls, title) {
    return '<input class="rg-in ' + (cls || '') + '" value="' + esc(value == null ? '' : value) + '" placeholder="' + esc(placeholder || '') + '"' +
      (title ? ' title="' + esc(title) + '"' : '') + ' spellcheck="false">';
  }

  /** A list of value inputs with + and ×: html, and read(). */
  function valueList(box, cls, values, placeholder, addLabel) {
    const holder = box.querySelector('.' + cls + '-list');
    function draw(vals) {
      holder.innerHTML = vals.map((v, i) => '<span class="rg-ed-param rg-ed-row-in">' + input(v, placeholder, cls) +
        '<button type="button" class="rg-x" data-i="' + i + '" title="Remove">×</button></span>').join('') +
        '<button type="button" class="rg-btn rg-add-val">' + esc(addLabel || '+ value') + '</button>';
      holder.querySelectorAll('.rg-x').forEach((b) => b.addEventListener('click', () => {
        const cur = read(); cur.splice(Number(b.getAttribute('data-i')), 1); draw(cur);
      }));
      holder.querySelector('.rg-add-val').addEventListener('click', () => {
        const cur = read(); cur.push(''); draw(cur);
        const ins = holder.querySelectorAll('input'); ins[ins.length - 1].focus();
      });
    }
    function read() { return Array.prototype.map.call(holder.querySelectorAll('input.' + cls), (i) => i.value); }
    draw(values && values.length ? values.slice() : ['']);
    return { read };
  }

  function actionsHtml(r, extra) {
    return '<div class="rg-ed-actions">' +
      '<button type="button" class="rg-btn rg-btn-primary rg-apply">Apply</button>' +
      '<button type="button" class="rg-btn rg-cancel">Cancel</button>' + (extra || '') +
      '<span class="rg-ed-msg"></span></div>';
  }

  function moveHtml() {
    return '<span class="rg-ed-sep"></span>' +
      '<button type="button" class="rg-btn rg-mini rg-up" title="Move it above the step before">↑ Move up</button>' +
      '<button type="button" class="rg-btn rg-mini rg-down" title="Move it below the step after">↓ Move down</button>';
  }

  function belowHtml() {
    return '<span class="rg-ed-sep"></span><span class="rg-ed-glabel">Insert below</span>' +
      '<button type="button" class="rg-btn rg-mini" data-below="step">step</button>' +
      blockKinds().map((b) => '<button type="button" class="rg-btn rg-mini" data-below="' + b + '">' + b + '</button>').join('');
  }

  /** Steps and blocks at the end of the block or branch on `line`. */
  function insideHtml() {
    return '<span class="rg-ed-sep"></span><span class="rg-ed-glabel">Inside</span>' +
      '<button type="button" class="rg-btn rg-mini" data-inside="step" title="A step at the end of this part">step</button>' +
      blockKinds().map((b) => '<button type="button" class="rg-btn rg-mini" data-inside="' + b + '">' + b + '</button>').join('');
  }

  function wireInside(ed, tr, into) {
    ed.box.querySelectorAll('[data-inside]').forEach((b) => b.addEventListener('click', () => {
      const what = b.getAttribute('data-inside');
      ed.close();
      if (what === 'step') openStep(tr, null, { op: 'insert', into }, { line: into + 1 });
      else if (what === 'TRY') sendAndReport({ op: 'block', into, block: { type: 'TRY' } }, null);
      else openHeader(tr, what, null, { op: 'block', into }, { line: into + 1 });
    }));
  }

  // ---- a block's END: add at the end of the block ---------------------------
  function openEndBar(anchor, row) {
    const opener = openerOf(row);
    if (!opener) { ctx.reveal({ line: row.line }); return; }
    const kind = String(opener.type || '').toUpperCase();
    const ed = openBox(anchor, row.line,
      '<div class="rg-ed-top"><span class="rg-label rg-ed-block">END of ' + esc(kind) + ' (line ' + opener.line + ')</span></div>' +
      '<div class="rg-ed-actions"><button type="button" class="rg-btn rg-btn-primary rg-add-here">+ Add step here</button>' +
      '<span class="rg-add-or">or a block</span>' +
      blockKinds().map((b) => '<button type="button" class="rg-btn rg-mini" data-inside="' + b + '">' + b + '</button>').join('') +
      '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-cancel">Close</button><span class="rg-ed-msg"></span></div>',
      { line: row.line });
    ed.q('.rg-add-here').addEventListener('click', () => {
      ed.close();
      openStep(anchor, null, { op: 'insert', into: opener.line }, { line: row.line, before: true });
    });
    ed.box.querySelectorAll('[data-inside]').forEach((b) => b.addEventListener('click', () => {
      const what = b.getAttribute('data-inside');
      ed.close();
      if (what === 'TRY') sendAndReport({ op: 'block', into: opener.line, block: { type: 'TRY' } }, null);
      else openHeader(anchor, what, null, { op: 'block', into: opener.line }, { line: row.line, before: true });
    }));
    ed.q('.rg-cancel').addEventListener('click', () => ed.close());
  }

  function wireCommon(ed, tr, r) {
    const up = ed.q('.rg-up');
    const down = ed.q('.rg-down');
    if (up) up.addEventListener('click', () => ed.submit({ op: 'move', line: r.line, dir: -1 }, up));
    if (down) down.addEventListener('click', () => ed.submit({ op: 'move', line: r.line, dir: 1 }, down));
    ed.box.querySelectorAll('[data-below]').forEach((b) => b.addEventListener('click', () => {
      const what = b.getAttribute('data-below');
      const after = { after: r.line };
      ed.close();
      if (what === 'step') openStep(tr, null, Object.assign({ op: 'insert' }, after), { line: r.line + 1 });
      else if (what === 'TRY') sendAndReport({ op: 'block', after: r.line, block: { type: 'TRY' } }, null);
      else openHeader(tr, what, null, Object.assign({ op: 'block' }, after), { line: r.line + 1 });
    }));
    ed.q('.rg-cancel').addEventListener('click', () => ed.close());
  }

  // ---- a keyword step (or a setup / teardown) -----------------------------
  function openStep(anchor, row, target, opts) {
    opts = opts || {};
    const list = data.catalog_list || [];
    const inItem = !row || !!row._item;
    const fixture = !!opts.fixture;
    const kw0 = row && row.kw ? keywordByKey(row.kw) : null;
    const state = {
      keyword: row ? row.keyword || '' : '',
      kw: kw0,
      slots: slotsFor(kw0, row ? row.cells : [])
    };
    const extra = (row ? moveHtml() : '') + (row && inItem && !fixture ? belowHtml() : '') +
      (row ? '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-btn-danger rg-delete">Delete ' +
             (fixture ? (row.label || 'setting') : 'step') + '</button>' : '');
    const ed = openBox(anchor, row ? row.line : '+',
      '<div class="rg-ed-top">' +
      (fixture ? '<span class="rg-label rg-ed-fixture">' + esc(row.label) + '</span>'
               : '<input class="rg-in rg-in-assign" placeholder="${result}" title="Variable to put the result in (optional)" spellcheck="false">' +
                 '<span class="rg-ed-eq">=</span>') +
      '<span class="rg-ed-kwwrap"><input class="rg-in rg-in-kw" placeholder="Keyword — type to search" spellcheck="false" autocomplete="off"></span>' +
      '<span class="rg-ed-sig"></span></div>' +
      '<div class="rg-ed-params"></div><div class="rg-ed-doc"></div>' +
      actionsHtml(row, fixture || !inItem ? (row ? '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-btn-danger rg-delete">Delete ' + esc(row.label || 'setting') + '</button>' : '') : extra),
      { before: opts.before, hideAnchor: !!row, line: row ? row.line : opts.line });
    const q = ed.q;
    const inAssign = q('.rg-in-assign');
    const inKw = q('.rg-in-kw');
    const params = q('.rg-ed-params');
    if (inAssign) inAssign.value = row ? (row.assign || []).map((a) => a.replace(/\s*=$/, '')).join('    ') : '';
    inKw.value = state.keyword;

    function drawParams() {
      const s = state.slots;
      let html = '';
      if (s.free) {
        html += '<div class="rg-ed-group"><div class="rg-ed-glabel">' +
          (state.keyword ? 'Arguments <span class="rg-ed-unknown">(keyword not found: values as written)</span>' : 'Arguments') + '</div>' +
          s.free.map((v, i) => '<span class="rg-ed-param rg-ed-row-in">' + input(v, 'value', 'rg-free') +
            '<button type="button" class="rg-x" data-free="' + i + '" title="Remove">×</button></span>').join('') +
          '<button type="button" class="rg-btn rg-add-free">+ value</button></div>';
      } else {
        if (s.positional.length) {
          html += '<div class="rg-ed-group">' + s.positional.map((p) =>
            '<label class="rg-ed-param"><span class="rg-ed-pname' + (p.required ? ' rg-req' : '') + '">' + esc(p.name) +
            (p.type ? ' <i>' + esc(p.type) + '</i>' : '') + '</span>' +
            input(p.value, p.required ? 'required' : (p.default != null ? '= ' + p.default : 'optional'), 'rg-pos') +
            '</label>').join('') + '</div>';
        }
        if (s.varargs) {
          html += '<div class="rg-ed-group"><div class="rg-ed-glabel">*' + esc(s.varargs.name) + '</div>' +
            s.varargs.values.map((v, i) => '<span class="rg-ed-param rg-ed-row-in">' + input(v, 'value', 'rg-var-in') +
              '<button type="button" class="rg-x" data-var="' + i + '" title="Remove">×</button></span>').join('') +
            '<button type="button" class="rg-btn rg-add-var">+ value</button></div>';
        }
        if (s.named.length) {
          html += '<div class="rg-ed-group">' + s.named.map((p) =>
            '<label class="rg-ed-param"><span class="rg-ed-pname' + (p.required ? ' rg-req' : '') + '">' + esc(p.name) + '=</span>' +
            input(p.value, p.required ? 'required' : (p.default != null ? '= ' + p.default : 'optional'), 'rg-named') +
            '</label>').join('') + '</div>';
        }
        if (s.kwargs) {
          html += '<div class="rg-ed-group"><div class="rg-ed-glabel">**' + esc(s.kwargs.name) + '</div>' +
            s.kwargs.pairs.map((p, i) => '<span class="rg-ed-param rg-ed-pair">' + input(p.key, 'name', 'rg-kw-key') +
              '<span class="rg-ed-eq">=</span>' + input(p.value, 'value', 'rg-kw-val') +
              '<button type="button" class="rg-x" data-kwarg="' + i + '" title="Remove">×</button></span>').join('') +
            '<button type="button" class="rg-btn rg-add-kwarg">+ named</button></div>';
        }
        if (s.extra.length) {
          html += '<div class="rg-ed-group"><div class="rg-ed-glabel rg-ed-unknown">More values than the keyword takes</div>' +
            s.extra.map((v, i) => '<span class="rg-ed-param rg-ed-row-in">' + input(v, 'value', 'rg-extra-in') +
              '<button type="button" class="rg-x" data-extra="' + i + '" title="Remove">×</button></span>').join('') + '</div>';
        }
        if (!html) html = '<div class="rg-ed-glabel">No arguments.</div>';
      }
      params.innerHTML = html;
      q('.rg-ed-sig').textContent = state.kw ? '(' + signature(state.kw) + ')' : '';
      q('.rg-ed-doc').textContent = state.kw ? (state.kw.shortdoc || '') + (state.kw.owner ? '  — ' + state.kw.owner : '') : '';
      wireParams();
    }
    function readParams() {
      const s = state.slots;
      const vals = (cls) => Array.prototype.map.call(params.querySelectorAll('.' + cls), (i) => i.value);
      if (s.free) { s.free = vals('rg-free'); return; }
      vals('rg-pos').forEach((v, i) => { s.positional[i].value = v; });
      if (s.varargs) s.varargs.values = vals('rg-var-in');
      vals('rg-named').forEach((v, i) => { s.named[i].value = v; });
      if (s.kwargs) {
        const keys = vals('rg-kw-key');
        const values = vals('rg-kw-val');
        s.kwargs.pairs = keys.map((k, i) => ({ key: k, value: values[i] }));
      }
      s.extra = vals('rg-extra-in');
    }
    function wireParams() {
      const on = (sel, fn) => params.querySelectorAll(sel).forEach((b) => b.addEventListener('click', (e) => {
        e.preventDefault(); readParams(); fn(b); drawParams();
        const ins = params.querySelectorAll('input');
        if (ins.length && b.className.includes('rg-add')) ins[ins.length - 1].focus();
      }));
      on('.rg-add-free', () => state.slots.free.push(''));
      on('.rg-add-var', () => state.slots.varargs.values.push(''));
      on('.rg-add-kwarg', () => state.slots.kwargs.pairs.push({ key: '', value: '' }));
      on('[data-free]', (b) => state.slots.free.splice(Number(b.getAttribute('data-free')), 1));
      on('[data-var]', (b) => state.slots.varargs.values.splice(Number(b.getAttribute('data-var')), 1));
      on('[data-kwarg]', (b) => state.slots.kwargs.pairs.splice(Number(b.getAttribute('data-kwarg')), 1));
      on('[data-extra]', (b) => state.slots.extra.splice(Number(b.getAttribute('data-extra')), 1));
    }

    // The keyword, with completion.
    const drop = makeDrop();
    ed.drops.push(drop);
    let hits = [];
    function choose(kw) {
      readParams();
      state.kw = kw;
      state.keyword = kw ? kw.name : inKw.value.trim();
      inKw.value = state.keyword;
      state.slots = carrySlots(state.slots, kw);
      drop.hide();
      drawParams();
      const first = params.querySelector('input');
      if (first) first.focus();
    }
    function drawDrop() {
      hits = filterKeywords(list, inKw.value, 12);
      drop.show(inKw, hits.map((k) => ({
        html: '<span class="rg-drop-name">' + esc(k.name) + '</span><span class="rg-drop-owner">' + esc(k.owner) + '</span>' +
          '<span class="rg-drop-sig">' + esc(signature(k)) + '</span>' +
          (k.shortdoc ? '<span class="rg-drop-doc">' + esc(k.shortdoc) + '</span>' : '')
      })), (i) => choose(hits[i]));
    }
    inKw.addEventListener('input', () => { drop.active = 0; drawDrop(); });
    inKw.addEventListener('focus', drawDrop);
    inKw.addEventListener('blur', () => setTimeout(() => {
      drop.hide();
      // A name typed out in full is the keyword, even without picking it.
      const typed = inKw.value.trim();
      if (typed && norm(typed) !== norm(state.kw ? state.kw.name : '')) {
        const exact = list.find((k) => norm(k.name) === norm(typed) || norm(k.owner + '.' + k.name) === norm(typed));
        if (exact) choose(exact);
        else if (norm(typed) !== norm(state.keyword)) {
          readParams(); state.kw = null; state.keyword = typed; state.slots = carrySlots(state.slots, null); drawParams();
        }
      }
    }, 120));
    inKw.addEventListener('keydown', (e) => {
      if (drop.key(e)) return;
      if (e.key === 'Enter') { e.preventDefault(); ed.apply(); }
    });

    ed.apply = () => {
      readParams();
      const keyword = inKw.value.trim();
      if (!keyword) { ed.msg('Choose a keyword.', true); return; }
      const same = state.kw && norm(state.kw.name) === norm(keyword);
      const built = argsFromSlots(same ? state.kw : null, same ? state.slots : carrySlots(state.slots, null));
      if (built.error) { ed.msg(built.error, true); return; }
      const assign = inAssign ? inAssign.value.split(/\s{2,}|\t/).map((a) => a.trim()).filter(Boolean) : [];
      ed.submit(Object.assign({}, target, { row: { assign, keyword, args: built.args } }), q('.rg-apply'));
    };
    q('.rg-apply').addEventListener('click', ed.apply);
    const del = q('.rg-delete');
    if (del) del.addEventListener('click', () => ed.submit({ op: 'delete', line: row.line }, del));
    wireCommon(ed, anchor, row || { line: opts.line });
    drawParams();
    (row && row.kw ? params.querySelector('input') || inKw : inKw).focus();
  }

  // ---- FOR / IF / ELSE IF / WHILE / EXCEPT headers -------------------------
  function openHeader(anchor, kind, row, target, opts) {
    opts = opts || {};
    const cells = row ? row.cells : [];
    let fields = '';
    if (kind === 'FOR') {
      const f = parseFor(cells);
      fields = '<div class="rg-ed-group"><div class="rg-ed-glabel">Loop variables</div><span class="rg-for-vars-list"></span></div>' +
        '<div class="rg-ed-group"><select class="rg-in rg-flavor">' +
        FLAVORS.map((x) => '<option' + (x === f.flavor ? ' selected' : '') + '>' + x + '</option>').join('') + '</select>' +
        '<span class="rg-for-vals-list"></span></div>';
      opts._for = f;
    } else if (kind === 'IF' || kind === 'ELSE IF') {
      fields = '<label class="rg-ed-param rg-ed-wide"><span class="rg-ed-pname rg-req">condition</span>' +
        input(cells.length ? cells[0].v : '', 'e.g. ${value} > 2', 'rg-cond') + '</label>';
    } else if (kind === 'WHILE') {
      const w = parseWhile(cells);
      fields = '<div class="rg-ed-group"><label class="rg-ed-param rg-ed-wide"><span class="rg-ed-pname rg-req">condition</span>' +
        input(w.condition, 'e.g. ${count} < 5', 'rg-cond') + '</label>' +
        '<label class="rg-ed-param"><span class="rg-ed-pname">limit</span>' + input(w.limit, 'e.g. 10 or 1 min', 'rg-limit') + '</label></div>';
    } else if (kind === 'THREAD') {
      const th = parseThread(cells);
      fields = '<div class="rg-ed-group"><label class="rg-ed-param"><span class="rg-ed-pname rg-req">thread name</span>' +
        input(th.name || 'WORKER1', 'e.g. WORKER1', 'rg-thread-name') + '</label>' +
        '<label class="rg-ed-param"><span class="rg-ed-pname">runs</span><select class="rg-in rg-daemon">' +
        '<option value="True"' + (th.daemon ? ' selected' : '') + '>until its test ends (daemon: True)</option>' +
        '<option value="False"' + (th.daemon ? '' : ' selected') + '>on to the end of the suite (daemon: False)</option>' +
        '</select></label></div>';
    } else if (kind === 'EXCEPT') {
      const x = parseExcept(cells);
      opts._except = x;
      fields = '<div class="rg-ed-group"><div class="rg-ed-glabel">Error patterns</div><span class="rg-patterns-list"></span></div>' +
        '<div class="rg-ed-group"><label class="rg-ed-param"><span class="rg-ed-pname">AS</span>' +
        input(x.variable, '${error}', 'rg-as') + '</label></div>';
    } else {
      fields = '<div class="rg-ed-glabel">' + esc(kind) + '</div>';
    }
    const existing = !!row;
    const isBlock = existing && BLOCKS.has(kind);
    const isBranch = existing && BRANCHES.has(kind);
    let extra = '';
    if (isBlock || isBranch) extra += insideHtml();
    if (isBlock) {
      extra += moveHtml() + belowHtml();
      if (kind === 'IF') extra += '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-mini" data-branch="ELSE IF">+ ELSE IF</button>' +
        '<button type="button" class="rg-btn rg-mini" data-branch="ELSE">+ ELSE</button>';
      extra += '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-btn-danger rg-delete">Delete ' + kind + ' block</button>';
    } else if (isBranch) {
      extra += '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-btn-danger rg-delete">Delete this ' + kind + '</button>';
    }
    const title = existing ? kind : (target.op === 'branch' ? 'New ' + kind : 'New ' + kind + ' block');
    const ed = openBox(anchor, existing ? row.line : '+',
      '<div class="rg-ed-top"><span class="rg-label rg-ed-block">' + esc(title) + '</span></div>' +
      '<div class="rg-ed-params">' + fields + '</div>' + actionsHtml(row, extra),
      { before: opts.before, hideAnchor: existing, line: existing ? row.line : opts.line });
    let forVars, forVals, patterns;
    if (kind === 'FOR') {
      forVars = valueList(ed.box, 'rg-for-vars', opts._for.variables.length ? opts._for.variables : ['${item}'], '${item}', '+ variable');
      forVals = valueList(ed.box, 'rg-for-vals', opts._for.values, 'value');
    }
    if (kind === 'EXCEPT') patterns = valueList(ed.box, 'rg-patterns', opts._except.patterns, 'pattern (empty: any error)', '+ pattern');
    function header() {
      if (kind === 'FOR') {
        return { variables: forVars.read().filter(Boolean), flavor: ed.q('.rg-flavor').value, values: forVals.read().filter((v) => v !== '') };
      }
      if (kind === 'IF' || kind === 'ELSE IF') return { condition: ed.q('.rg-cond').value };
      if (kind === 'WHILE') return { condition: ed.q('.rg-cond').value, limit: ed.q('.rg-limit').value };
      if (kind === 'EXCEPT') return { patterns: patterns.read().filter((v) => v !== ''), variable: ed.q('.rg-as').value, type: opts._except.type || '' };
      if (kind === 'THREAD') return { name: ed.q('.rg-thread-name').value.trim(), daemon: ed.q('.rg-daemon').value };
      return {};
    }
    ed.apply = () => {
      if (target.op === 'header') ed.submit({ op: 'header', line: target.line, header: header() }, ed.q('.rg-apply'));
      else if (target.op === 'branch') ed.submit({ op: 'branch', line: target.line, branch: { type: kind, header: header() } }, ed.q('.rg-apply'));
      else ed.submit(Object.assign({}, target, { block: { type: kind, header: header() } }), ed.q('.rg-apply'));
    };
    ed.q('.rg-apply').addEventListener('click', ed.apply);
    const del = ed.q('.rg-delete');
    if (del) confirmButton(del, isBlock ? 'Delete it with every step in it?' : 'Delete it with its steps?',
                           (b) => ed.submit({ op: 'delete', line: row.line }, b));
    ed.box.querySelectorAll('[data-branch]').forEach((b) => b.addEventListener('click', () => {
      const type = b.getAttribute('data-branch');
      ed.close();
      if (type === 'ELSE' || type === 'FINALLY') sendAndReport({ op: 'branch', line: row.line, branch: { type } }, null);
      else openHeader(anchor, type, null, { op: 'branch', line: row.line }, { line: row.line + 1 });
    }));
    wireCommon(ed, anchor, row || { line: opts.line });
    if (existing) wireInside(ed, anchor, row.line);
    const first = ed.box.querySelector('input.rg-in');
    if (first) first.focus();
  }

  // ---- TRY / ELSE / FINALLY: the block's actions ---------------------------
  function openBlockBar(anchor, kind, row) {
    let extra = '';
    if (kind === 'TRY') {
      extra = insideHtml() + moveHtml() + belowHtml() +
        '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-mini" data-branch="EXCEPT">+ EXCEPT</button>' +
        '<button type="button" class="rg-btn rg-mini" data-branch="FINALLY">+ FINALLY</button>' +
        '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-btn-danger rg-delete">Delete TRY block</button>';
    } else {
      extra = insideHtml() + '<span class="rg-ed-sep"></span>' +
        '<button type="button" class="rg-btn rg-btn-danger rg-delete">Delete this ' + kind + '</button>';
    }
    const ed = openBox(anchor, row.line,
      '<div class="rg-ed-top"><span class="rg-label rg-ed-block">' + esc(kind) + '</span></div>' +
      '<div class="rg-ed-actions">' + extra + '<button type="button" class="rg-btn rg-cancel">Close</button><span class="rg-ed-msg"></span></div>',
      { hideAnchor: true, line: row.line });
    confirmButton(ed.q('.rg-delete'), kind === 'TRY' ? 'Delete it with every step in it?' : 'Delete it with its steps?',
                  (b) => ed.submit({ op: 'delete', line: row.line }, b));
    ed.box.querySelectorAll('[data-branch]').forEach((b) => b.addEventListener('click', () => {
      const type = b.getAttribute('data-branch');
      ed.close();
      if (type === 'FINALLY') sendAndReport({ op: 'branch', line: row.line, branch: { type } }, null);
      else openHeader(anchor, type, null, { op: 'branch', line: row.line }, { line: row.line + 1 });
    }));
    wireCommon(ed, anchor, row);
    wireInside(ed, anchor, row.line);
  }

  // ---- a setting, an import or a variable -----------------------------------
  function openValues(anchor, row, target, opts) {
    opts = opts || {};
    const t = row ? String(row.type || '').toUpperCase() : '';
    const isNew = !row;
    const isVariable = t === 'VARIABLE' || (isNew && target.section === 'variables');
    const isDoc = t === 'DOCUMENTATION';
    const values = row ? (row.cells || []).map((c) => c.v) : [];
    let top;
    if (isVariable) {
      top = '<label class="rg-ed-param"><span class="rg-ed-pname rg-req">variable</span>' +
        input(row ? row.label : '${NAME}', '${NAME}, @{LIST} or &{DICT}', 'rg-var-name') + '</label>';
    } else if (isNew) {
      top = '<label class="rg-ed-param"><span class="rg-ed-pname rg-req">setting</span><select class="rg-in rg-setting-name">' +
        NEW_SETTINGS.map((s) => '<option>' + s + '</option>').join('') + '</select></label>';
    } else {
      top = '<span class="rg-label rg-ed-block">' + esc(row.label) + '</span>';
    }
    const body = isDoc
      ? '<textarea class="rg-in rg-doc" rows="' + Math.min(10, Math.max(3, (values[0] || '').split('\n').length + 1)) + '" spellcheck="true"></textarea>'
      : '<div class="rg-ed-group"><span class="rg-vals-list"></span></div>';
    const del = row ? '<span class="rg-ed-sep"></span><button type="button" class="rg-btn rg-btn-danger rg-delete">Delete</button>' : '';
    const ed = openBox(anchor, row ? row.line : '+',
      '<div class="rg-ed-top">' + top + '</div><div class="rg-ed-params">' + body + '</div>' + actionsHtml(row, del),
      { before: opts.before, hideAnchor: !!row, line: row ? row.line : 0 });
    let list = null;
    if (isDoc) ed.q('.rg-doc').value = values[0] || '';
    else list = valueList(ed.box, 'rg-vals', values, 'value');
    ed.apply = () => {
      const vals = isDoc ? [ed.q('.rg-doc').value] : list.read();
      if (isNew) {
        const name = isVariable ? ed.q('.rg-var-name').value.trim() : ed.q('.rg-setting-name').value;
        ed.submit({ op: 'setting', section: isVariable ? 'variables' : 'settings', name, values: vals.filter((v, i) => v !== '' || i === 0 && isVariable) }, ed.q('.rg-apply'));
      } else {
        const edit = { op: 'values', line: row.line, values: isDoc ? vals : vals.filter((v) => v !== '') };
        if (isVariable) edit.name = ed.q('.rg-var-name').value.trim();
        ed.submit(edit, ed.q('.rg-apply'));
      }
    };
    ed.q('.rg-apply').addEventListener('click', ed.apply);
    ed.q('.rg-cancel').addEventListener('click', () => ed.close());
    const d = ed.q('.rg-delete');
    if (d) d.addEventListener('click', () => ed.submit({ op: 'delete', line: row.line }, d));
    const first = ed.box.querySelector('input.rg-in, textarea.rg-in');
    if (first) first.focus();
  }

  // ---- tests and keywords --------------------------------------------------
  const ITEM_SETTINGS = {
    tests: ['[Documentation]', '[Tags]', '[Setup]', '[Teardown]', '[Timeout]', '[Template]'],
    keywords: ['[Documentation]', '[Arguments]', '[Tags]', '[Teardown]', '[Timeout]']
  };
  const SETTING_TYPES = { '[Documentation]': 'DOCUMENTATION', '[Tags]': 'TAGS', '[Setup]': 'SETUP', '[Teardown]': 'TEARDOWN',
    '[Timeout]': 'TIMEOUT', '[Template]': 'TEMPLATE', '[Arguments]': 'ARGUMENTS' };

  function itemAt(line) {
    for (const s of (data.grid.sections || [])) {
      for (const it of (s.items || [])) if (it.line === line) return { section: s.type, item: it };
    }
    return null;
  }

  /** A test's or keyword's own [Documentation], [Tags], [Setup], ... -- the ones it has not got yet. */
  function openItemSetting(nameEl, line) {
    const found = itemAt(line);
    if (!found) return;
    const have = new Set(found.item.rows.map((r) => String(r.type || '').toUpperCase()));
    const offer = (ITEM_SETTINGS[found.section] || []).filter((s) => !have.has(SETTING_TYPES[s]));
    if (!offer.length) { report(new Error('It has every setting already; click a setting row to change it.')); return; }
    const ed = openBox(nameEl, '', '<div class="rg-ed-top"><label class="rg-ed-param"><span class="rg-ed-pname rg-req">setting</span>' +
      '<select class="rg-in rg-item-setting">' + offer.map((s) => '<option>' + esc(s) + '</option>').join('') + '</select></label>' +
      '<span class="rg-ed-doc rg-item-setting-hint"></span></div>' +
      '<div class="rg-ed-params rg-item-setting-body"></div>' + actionsHtml(null, ''),
      { line: found.item.rows.length ? found.item.rows[0].line : line + 1 });
    const select = ed.q('.rg-item-setting');
    const bodyEl = ed.q('.rg-item-setting-body');
    const hints = {
      '[Documentation]': 'What the ' + (found.section === 'tests' ? 'test checks' : 'keyword does') + '; one paragraph per line.',
      '[Tags]': 'Tags to select or report the test by.',
      '[Setup]': 'A keyword run before the test, with its arguments.',
      '[Teardown]': 'A keyword run after it, even when it fails, with its arguments.',
      '[Timeout]': 'e.g. 1 min, 30 s.',
      '[Template]': 'The keyword every row of the test calls.',
      '[Arguments]': '${name}, ${name}=default, @{list} or &{dict}.'
    };
    let list = null;
    function draw() {
      const s = select.value;
      ed.q('.rg-item-setting-hint').textContent = hints[s] || '';
      if (s === '[Documentation]') {
        bodyEl.innerHTML = '<textarea class="rg-in rg-doc" rows="3" spellcheck="true" placeholder="Documentation"></textarea>';
        list = null;
        bodyEl.querySelector('textarea').focus();
      } else {
        bodyEl.innerHTML = '<div class="rg-ed-group"><span class="rg-isv-list"></span></div>';
        const first = s === '[Setup]' || s === '[Teardown]' || s === '[Template]' ? 'keyword' : s === '[Arguments]' ? '${name}' : 'value';
        list = valueList(bodyEl, 'rg-isv', [''], first, s === '[Setup]' || s === '[Teardown]' ? '+ argument' : '+ value');
        const i = bodyEl.querySelector('input'); if (i) i.focus();
      }
    }
    select.addEventListener('change', draw);
    draw();
    ed.apply = () => {
      const values = list ? list.read() : [ed.q('.rg-doc').value];
      ed.submit({ op: 'item_setting', item: line, name: select.value, values }, ed.q('.rg-apply'));
    };
    ed.q('.rg-apply').addEventListener('click', ed.apply);
    ed.q('.rg-cancel').addEventListener('click', () => ed.close());
  }

  function openRename(nameEl, name, line) {
    const ed = openBox(nameEl, '', '<div class="rg-ed-top"><input class="rg-in rg-in-name" spellcheck="false">' +
      '<button type="button" class="rg-btn rg-btn-primary rg-apply">Rename</button>' +
      '<button type="button" class="rg-btn rg-cancel">Cancel</button><span class="rg-ed-msg"></span></div>');
    const inp = ed.q('.rg-in-name');
    inp.value = name;
    ed.apply = () => ed.submit({ op: 'rename', line, name: inp.value.trim() }, ed.q('.rg-apply'));
    ed.q('.rg-apply').addEventListener('click', ed.apply);
    ed.q('.rg-cancel').addEventListener('click', () => ed.close());
    inp.focus();
    inp.select();
  }

  function openNewItem(anchor, kind) {
    const what = kind === 'tests' ? 'test case' : 'keyword';
    const ed = openBox(anchor, '', '<div class="rg-ed-top"><span class="rg-label rg-ed-block">New ' + what + '</span>' +
      '<input class="rg-in rg-in-name" placeholder="Name of the ' + what + '" spellcheck="false">' +
      '<button type="button" class="rg-btn rg-btn-primary rg-apply">Add</button>' +
      '<button type="button" class="rg-btn rg-cancel">Cancel</button><span class="rg-ed-msg"></span></div>');
    ed.apply = () => ed.submit({ op: 'item', section: kind, name: ed.q('.rg-in-name').value.trim() }, ed.q('.rg-apply'));
    ed.q('.rg-apply').addEventListener('click', ed.apply);
    ed.q('.rg-cancel').addEventListener('click', () => ed.close());
    ed.q('.rg-in-name').focus();
  }

  // ---- sending ---------------------------------------------------------------
  /**
   * Send one edit. The host pushes the redrawn grid (as the selection) before
   * it answers; the answer says which row to light up.
   */
  function send(edit) {
    return ctx.edit(edit).then((res) => {
      const line = res && res.line;
      const tr = line && el.querySelector('tr.rg-row[data-line="' + line + '"]');
      if (tr) tr.classList.add('rg-flash');
      else if (line) flashLine = line;
      return res;
    });
  }

  function report(err) {
    const note = el.querySelector('.rg-note');
    if (note) {
      note.querySelectorAll('.rg-note-error').forEach((n) => n.remove());
      note.insertAdjacentHTML('beforeend', ' <span class="rg-bad rg-note-error">' + esc(err.message || String(err)) + '</span>');
    }
  }

  function sendAndReport(edit, button) {
    if (button) button.disabled = true;
    return send(edit).catch((err) => { if (button) button.disabled = false; report(err); });
  }

  function sendFromNote(edit, button) { return sendAndReport(edit, button); }

  show(ctx.selection());
  const off = ctx.onSelection(show);
  return {
    destroy() { off(); if (editor) editor.close(); el.innerHTML = ''; }
  };
}
