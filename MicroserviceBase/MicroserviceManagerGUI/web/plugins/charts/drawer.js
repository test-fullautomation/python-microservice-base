// charts: the "Chart" drawer tab. Plots the signals of the tile selected on
// the bench (its signal fields, or a signal-strip's signals).
import { createStrip } from './strip.js';

const MAX_SIGNALS = 8;

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function mount(el, ctx) {
  let strip = null;
  let suspended = false;

  function show(sel) {
    if (strip) { strip.destroy(); strip = null; }
    const names = (sel && sel.signals) || [];
    if (!names.length) {
      el.innerHTML = '<p class="charts-empty">Select a tile that shows signals to chart them here.</p>';
      return;
    }
    el.innerHTML = '<div class="charts-drawer-head"><strong>' + esc(sel.title || sel.component) + '</strong>' +
      (names.length > MAX_SIGNALS ? ' <span class="charts-warn">first ' + MAX_SIGNALS + ' of ' + names.length + ' signals</span>' : '') +
      '</div><div class="charts-drawer-body"></div>';
    strip = createStrip(el.querySelector('.charts-drawer-body'), names.slice(0, MAX_SIGNALS), ctx, { window: '120s', digits: 3 });
    if (suspended) strip.suspend();
  }

  show(ctx.selection && ctx.selection());
  const off = ctx.onSelection ? ctx.onSelection(show) : () => {};
  return {
    suspend() { suspended = true; if (strip) strip.suspend(); },
    resume() { suspended = false; if (strip) strip.resume(); },
    destroy() { off(); if (strip) strip.destroy(); strip = null; }
  };
}
