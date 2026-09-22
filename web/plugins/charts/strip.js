// charts: the "signal-strip" tile kind. One sparkline row per signal over a
// sliding window. Redraws at most 10 times a second; after suspend() no
// subscription, timer or animation frame is left (P4).
import { Series, parseWindow } from './series.js';

const MAX_REDRAW_MS = 100;

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// The plugin's own styles, namespaced "charts-" (P2). The shell removes
// everything marked data-endo-plugin="charts" when the plugin is turned
// off, so this is (re)added whenever a strip is created.
const STYLE = `
.charts-strip { display: grid; gap: 0.35rem; min-width: 0; }
.charts-row { display: grid; gap: 0.1rem; min-width: 0; }
.charts-meta { display: flex; justify-content: space-between; gap: 0.5rem; font-size: 0.74rem; min-width: 0; }
.charts-name { color: var(--muted, #5A665F); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono, monospace); }
.charts-last { font-family: var(--font-mono, monospace); font-variant-numeric: tabular-nums; white-space: nowrap; }
.charts-canvas { width: 100%; height: 2.4rem; display: block; background: color-mix(in srgb, var(--accent, #127A69) 4%, transparent); border-radius: 4px; }
.charts-foot { font-size: 0.68rem; color: var(--muted, #5A665F); }
.charts-warn { color: var(--warn, #A96A12); font-size: 0.72rem; }
.charts-empty { color: var(--muted, #5A665F); font-size: 0.84rem; margin: 0; }
.charts-drawer-head { font-size: 0.84rem; margin-bottom: 0.4rem; }
.charts-drawer-body .charts-canvas { height: 3.2rem; }
`;
function ensureStyle() {
  if (document.querySelector('style[data-endo-plugin="charts"]')) return;
  const s = document.createElement('style');
  s.setAttribute('data-endo-plugin', 'charts');
  s.textContent = STYLE;
  document.head.appendChild(s);
}

function token(el, name, fallback) {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || fallback;
}

/**
 * A strip chart of `names` in `el`, fed through ctx.signals.subscribe.
 * opts: { window, min, max, digits }
 * Returns { suspend, resume, destroy, names }.
 */
export function createStrip(el, names, ctx, opts = {}) {
  ensureStyle();
  const windowMs = parseWindow(opts.window);
  const series = new Map(names.map((n) => [n, new Series(windowMs)]));
  el.innerHTML = '<div class="charts-strip">' + names.map((n, i) =>
    '<div class="charts-row" data-i="' + i + '">' +
    '<div class="charts-meta"><span class="charts-name" title="' + esc(n) + '">' + esc(n) + '</span>' +
    '<span class="charts-last" data-last="' + i + '">—</span></div>' +
    '<canvas class="charts-canvas" data-canvas="' + i + '" data-points="0"></canvas></div>').join('') +
    '<div class="charts-foot">last ' + Math.round(windowMs / 1000) + ' s</div></div>';
  const canvases = names.map((_, i) => el.querySelector('[data-canvas="' + i + '"]'));
  const lasts = names.map((_, i) => el.querySelector('[data-last="' + i + '"]'));

  let unsub = null;
  let raf = 0;
  let timer = 0;
  let lastDraw = 0;
  let running = false;

  function draw() {
    raf = 0;
    lastDraw = performance.now();
    const now = Date.now();
    const line = token(el, '--accent', '#127A69');
    const grid = token(el, '--rule', '#D3D9D1');
    names.forEach((n, i) => {
      const s = series.get(n);
      const c = canvases[i];
      if (!c) return;
      const w = c.clientWidth, h = c.clientHeight;
      if (!w || !h) return;
      const dpr = window.devicePixelRatio || 1;
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
        c.width = Math.round(w * dpr);
        c.height = Math.round(h * dpr);
      }
      const g = c.getContext('2d');
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      g.strokeStyle = grid;
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(0, h - 0.5);
      g.lineTo(w, h - 0.5);
      g.stroke();
      s.trim(now);
      c.dataset.points = String(s.length);
      if (s.length < 1) return;
      const [lo, hi] = s.range(opts.min, opts.max);
      const pts = s.toPixels(now, w, h - 2, lo, hi);
      g.strokeStyle = line;
      g.lineWidth = 1.5;
      g.beginPath();
      pts.forEach(([x, y], k) => { if (k) g.lineTo(x, y + 1); else g.moveTo(x, y + 1); });
      if (pts.length === 1) g.lineTo(w, pts[0][1] + 1);
      g.stroke();
    });
  }

  function schedule() {
    if (!running || raf || timer) return;
    const wait = MAX_REDRAW_MS - (performance.now() - lastDraw);
    if (wait > 0) {
      timer = setTimeout(() => { timer = 0; if (running) raf = requestAnimationFrame(draw); }, wait);
    } else {
      raf = requestAnimationFrame(draw);
    }
  }

  function onValue(name, value, ts) {
    const s = series.get(name);
    if (!s) return;
    s.push(ts ? ts * 1000 : Date.now(), value);
    const i = names.indexOf(name);
    if (lasts[i]) lasts[i].textContent = typeof value === 'number' && opts.digits != null ? value.toFixed(opts.digits) : String(value);
    schedule();
  }
  onValue.onStatus = (st) => {
    const i = names.indexOf(st.name);
    if (i >= 0 && st.state !== 'live' && lasts[i]) {
      lasts[i].innerHTML = '<span class="charts-warn" title="' + esc(st.message || st.state) + '">' +
        (st.state === 'unknown' ? 'unknown signal' : st.state === 'retrying' ? 'reconnecting' : 'unavailable') + '</span>';
    }
  };

  const resizer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => schedule()) : null;

  function start() {
    if (running) return;
    running = true;
    try { unsub = ctx.signals.subscribe(names, onValue); }
    catch (e) {
      el.querySelector('.charts-foot').innerHTML = '<span class="charts-warn">' + esc(e.message) + '</span>';
    }
    if (resizer) canvases.forEach((c) => c && resizer.observe(c));
    schedule();
  }
  function stop() {
    running = false;
    if (unsub) { unsub(); unsub = null; }
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    if (timer) { clearTimeout(timer); timer = 0; }
    if (resizer) resizer.disconnect();
  }
  start();
  return { suspend: stop, resume: start, destroy: stop, names };
}

/** Kind entry: the shell calls render(el, tile, ctx) for each tile. */
export function render(el, tile, ctx) {
  return createStrip(el, tile.signals || [], ctx, { window: tile.window, min: tile.min, max: tile.max, digits: tile.digits });
}
