// flow-view: the "Diagram" file view of flow-graph files. Runs in a sandboxed
// frame; the host view pushes the runner's data for the file as the
// selection ({ flow, error?, live?, zoom?, motion?, editable?, undo? }), and a
// click on a node asks the host to show that node in the file
// (ctx.reveal({ node })).
//
// `live` (the Runs view, during and after a run): where the run is -- see
// live.js. The same flow pushed again with a new `live` only moves the
// marks; when the node changes the view tells the host where it is
// (ctx.reveal({ follow, node, top, bottom })), so a tall diagram can keep
// it in sight.
//
// `editable` (the project view, the file open in Script): "Edit flow" turns
// on drag and drop -- see edit.js. Edits go to the host (ctx.edit) and come
// back as new data, like any change of the text.
//
// `breakpoints` / `paused` (a host that debugs, with ctx.breakpoint): dots
// to set breakpoints on the steps, and the step the run is stopped at -- see
// breakpoints.js.
import { render } from './flow.js';
import { ensureStyle } from './style.js';
import { mark, extent, zoom, replay } from './live.js';
import { toolbar, panel, readPanel, insertEdit, kindLabel, findStep } from './edit.js';
import { markBreakpoints } from './breakpoints.js';

export function mount(el, ctx) {
  ensureStyle();
  let drawn = null;      // what is drawn: the flow, error, open sub-flows and edit state, as text
  let followed = null;   // the node the host was last told about
  let memo = {};         // the replay's memory: the last step shown
  let current = null;    // the last data shown, to redraw when a sub-flow opens
  const expanded = {};   // sub-flow call id -> true while opened in place
  // Editing: on/off, the selected step, a message, a sub-flow drop waiting for its file.
  const state = { editing: false, selected: null, message: '', error: false, ask: null, busy: false };

  function redraw() {
    drawn = null;
    show(current);
  }

  function show(data) {
    current = data;
    const flow = data && data.flow;
    if (!flow) {
      el.innerHTML = '<p class="fv-empty">No flow to draw.</p>';
      drawn = null;
      return;
    }
    if (!data.editable) state.editing = false;
    if (state.selected && !findStep(flow, state.selected)) state.selected = null;
    const key = JSON.stringify([flow, data.error || null, expanded, data.editable, data.undo,
                                state.editing, state.selected, state.message, state.ask]);
    if (key !== drawn) {
      el.innerHTML = toolbar(state, data) + panel(state, data) +
        '<div class="fv-scroll' + (state.editing ? ' fv-edit' : '') + '">' +
        render(flow, { error: data.error || null, expanded, edit: state.editing }) + '</div>';
      wireNodes();
      wireEditor();
      drawn = key;
      followed = null;
      memo = {};
    }
    if ('live' in data) {
      const now = mark(el, data.live);
      replay(el, data.live, memo, data.motion, now);
      const id = now ? now.getAttribute('data-node') : null;
      const moved = now && id !== followed;
      if (moved) ctx.reveal(Object.assign({ follow: true, node: id }, extent(now)));
      followed = id;
      zoom(el, data.zoom, moved ? [now] : []);
    } else {
      zoom(el, data.zoom, []);
    }
    markBreakpoints(el, data, ctx.breakpoint ? (id) => ctx.breakpoint(id) : null);
  }

  function wireNodes() {
    el.querySelectorAll('[data-node]').forEach((g) => {
      const id = g.getAttribute('data-node');
      const own = id.indexOf('::') < 0;     // a step of an opened sub-flow is another file's
      if (state.editing && own && id === state.selected) g.classList.add('fv-selected');
      const go = () => {
        if (!own) return;
        if (state.editing) select(id); else ctx.reveal({ node: id });
      };
      g.addEventListener('click', go);
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      });
      if (state.editing && own) {
        g.addEventListener('pointerdown', (e) => startDrag(e, { node: id, label: id }));
      }
    });
    el.querySelectorAll('[data-toggle]').forEach((t) => {
      const flip = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const id = t.getAttribute('data-toggle');
        if (expanded[id]) delete expanded[id]; else expanded[id] = true;
        redraw();
      };
      t.addEventListener('click', flip);
      t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') flip(e); });
    });
  }

  // ---- editing ---------------------------------------------------------------

  function wireEditor() {
    const on = (act, fn) => el.querySelectorAll('[data-act="' + act + '"]').forEach((b) => b.addEventListener('click', fn));
    on('edit', () => { state.editing = true; state.message = ''; redraw(); });
    on('done', () => { Object.assign(state, { editing: false, selected: null, message: '', ask: null }); redraw(); });
    on('undo', () => send({ op: 'undo' }, 'Undone.'));
    on('apply', () => {
      const s = findStep(current.flow, state.selected);
      if (s) send({ op: 'update', node: s.id, attrs: readPanel(el, s.kind) }, 'Changed.');
    });
    on('delete', () => removeSelected());
    on('wrap-loop', () => send({ op: 'wrap', node: state.selected, kind: 'loop' }, 'Wrapped in a loop.'));
    on('wrap-try', () => send({ op: 'wrap', node: state.selected, kind: 'try' }, 'Wrapped in a try.'));
    on('ask-ok', () => {
      const file = (el.querySelector('#fv-ask-file') || {}).value || '';
      const place = state.ask;
      state.ask = null;
      if (file.trim()) send(insertEdit('flow', place, { file: file.trim() }), 'Sub-flow added.');
      else redraw();
    });
    on('ask-cancel', () => { state.ask = null; redraw(); });
    el.querySelectorAll('.fv-chip[data-kind]').forEach((c) =>
      c.addEventListener('pointerdown', (e) => startDrag(e, { kind: c.getAttribute('data-kind'), label: c.textContent })));
  }

  function select(id) {
    state.selected = id;
    state.message = '';
    state.error = false;
    redraw();
  }

  function removeSelected() {
    if (state.selected) send({ op: 'delete', node: state.selected }, 'Deleted.', true);
  }

  /** One edit: the host applies it to the text and pushes the new flow before it answers. */
  function send(change, done, clearSelection) {
    if (state.busy) {
      // One edit at a time: the runner rewrites the text and checks the flow.
      state.error = true;
      state.message = 'The last change is still being applied — try again in a moment.';
      redraw();
      return;
    }
    state.busy = true;
    state.error = false;
    state.message = 'Applying…';
    redraw();
    Promise.resolve(ctx.edit(change)).then((res) => {
      state.busy = false;
      state.error = false;
      state.message = done || '';
      if (clearSelection) state.selected = null;
      else if (res && res.node && change.op !== 'undo') state.selected = res.node;
      redraw();
    }, (err) => {
      state.busy = false;
      state.error = true;
      state.message = (err && err.message) || String(err);
      redraw();
    });
  }

  // Drag with pointer events: a palette item (insert) or a step (move) onto a drop zone.
  let drag = null;
  function startDrag(e, what) {
    if (e.button !== 0) return;
    drag = Object.assign({ x0: e.clientX, y0: e.clientY, started: false, ghost: null, hot: null }, what);
  }

  function hotZone(x, y) {
    const t = document.elementFromPoint(x, y);
    return t && t.closest ? t.closest('.fv-drop') : null;
  }

  function onMove(e) {
    if (!drag) return;
    if (!drag.started) {
      if (Math.abs(e.clientX - drag.x0) + Math.abs(e.clientY - drag.y0) < 6) return;
      drag.started = true;
      drag.ghost = document.createElement('div');
      drag.ghost.className = 'fv-ghost';
      drag.ghost.textContent = drag.kind ? kindLabel(drag.kind) : drag.label;
      document.body.appendChild(drag.ghost);
      el.classList.add('fv-dragging');
    }
    drag.ghost.style.left = (e.clientX + 12) + 'px';
    drag.ghost.style.top = (e.clientY + 8) + 'px';
    const zone = hotZone(e.clientX, e.clientY);
    if (zone !== drag.hot) {
      if (drag.hot) drag.hot.classList.remove('fv-drop-hot');
      if (zone) zone.classList.add('fv-drop-hot');
      drag.hot = zone;
    }
  }

  function onUp() {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.ghost) d.ghost.remove();
    el.classList.remove('fv-dragging');
    if (!d.started || !d.hot) return;      // a click selects (see wireNodes)
    const place = JSON.parse(d.hot.getAttribute('data-drop'));
    if (d.node) {
      if (place.before === d.node || place.after === d.node) return;
      send(Object.assign({ op: 'move', node: d.node }, place), 'Moved.');
    } else if (d.kind === 'flow') {
      state.ask = place;                    // a sub-flow needs its file first
      redraw();
    } else {
      send(insertEdit(d.kind, place), kindLabel(d.kind) + ' added.');
    }
  }

  function onKey(e) {
    if (!state.editing) return;
    const typing = e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    if (typing) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && state.selected) { e.preventDefault(); removeSelected(); }
    if (e.key === 'Escape' && state.selected) { state.selected = null; redraw(); }
  }

  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', onUp);
  document.addEventListener('keydown', onKey);

  show(ctx.selection());
  const off = ctx.onSelection(show);
  return {
    destroy() {
      off();
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      document.removeEventListener('keydown', onKey);
      el.innerHTML = '';
    }
  };
}
