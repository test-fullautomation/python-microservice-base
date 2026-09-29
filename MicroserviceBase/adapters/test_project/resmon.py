"""Resource monitor for long test runs: record RAM / CPU, then report.

A separate process samples the processes of a run -- so its own work is
not counted in theirs, and it keeps recording if the runner misbehaves --
and writes one JSON line per sample. When they have all ended it renders a
self-contained HTML report: charts over time, the memory trend after the
warm-up, and a verdict per process (STABLE / GROWING)::

    python resmon.py record --out resources.jsonl --report resources.html \\
        --pid DRIVER=1234 --pid CHECKER=5678
    python resmon.py record --out r.jsonl --match "robot.*endurance" --duration 8h
    python resmon.py report resources.jsonl -o resources.html

The Manager GUI starts it for every run (``results/<run>/resources.*``).

Per process (and the processes it started): working set (``rss``),
private bytes (Windows) or unique memory, CPU (percent of one core),
threads and handles (file descriptors elsewhere). Per machine: CPU and
memory used. Needs ``psutil``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import math
import os
import platform
import re
import sys
import time

try:
    import psutil
except ImportError:  # pragma: no cover - reported when used
    psutil = None

MB = 1024 * 1024
# Verdict thresholds (``report --max-growth ...``): memory is GROWING when,
# after the warm-up, its trend exceeds this many MB per hour *and* it grew
# by more than this share of its level. A run shorter than MIN_STEADY_S after
# the warm-up is too short to judge.
MAX_GROWTH_MB_PER_H = 10.0
MIN_GROWTH_SHARE = 0.05
MIN_STEADY_S = 600
WARMUP_SHARE = 0.10
WARMUP_MAX_S = 600
# The end is left out as well: Robot writes its log and report there, a last
# burst of memory that is not the run's trend.
WINDDOWN_SHARE = 0.05
WINDDOWN_MAX_S = 60


# ============================================================== recording

def _parse_duration(text: str) -> float:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|m|min|h|d)?\s*", str(text))
    if not m:
        raise argparse.ArgumentTypeError(f"not a duration: {text!r} (e.g. 90s, 30m, 8h)")
    n, unit = float(m.group(1)), (m.group(2) or "s")
    return n * {"s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400}[unit]


class _Watched:
    """One monitored process and the processes it started."""

    def __init__(self, label: str, proc):
        self.label = label
        self.proc = proc
        self.tree = {}          # pid -> psutil.Process (cpu_percent needs the same object)

    def sample(self):
        try:
            members = [self.proc] + self.proc.children(recursive=True)
        except psutil.Error:
            return None
        known = {}
        rss = priv = cpu = threads = handles = 0.0
        alive = False
        for p in members:
            p = self.tree.get(p.pid, p)
            try:
                with p.oneshot():
                    mi = p.memory_info()
                    c = p.cpu_percent(None)
                    t = p.num_threads()
                    h = p.num_handles() if hasattr(p, "num_handles") else p.num_fds()
            except psutil.Error:
                continue
            alive = True
            known[p.pid] = p
            rss += mi.rss
            priv += getattr(mi, "private", 0) or getattr(mi, "rss", 0)
            cpu += c
            threads += t
            handles += h
        self.tree = known
        if not alive:
            return None
        return {"rss": round(rss / MB, 2), "priv": round(priv / MB, 2), "cpu": round(cpu, 1),
                "thr": int(threads), "h": int(handles), "n": len(known)}


def record(args) -> int:
    if psutil is None:
        print("resmon needs psutil (pip install psutil).", file=sys.stderr)
        return 2
    watched: dict[str, _Watched] = {}
    for spec in args.pid or []:
        label, _, pid = spec.rpartition("=")
        try:
            watched[label or pid] = _Watched(label or pid, psutil.Process(int(pid)))
        except (ValueError, psutil.Error) as exc:
            print(f"resmon: skipping {spec}: {exc}", file=sys.stderr)
    pattern = re.compile(args.match, re.I) if args.match else None
    seen_pids = {w.proc.pid for w in watched.values()}

    def discover():
        if not pattern:
            return
        me = os.getpid()
        for p in psutil.process_iter(["pid", "cmdline", "name"]):
            if p.pid in seen_pids or p.pid == me:
                continue
            line = " ".join(p.info.get("cmdline") or []) or (p.info.get("name") or "")
            if pattern.search(line):
                seen_pids.add(p.pid)
                label = f"{p.info.get('name') or 'process'}[{p.pid}]"
                watched[label] = _Watched(label, p)

    discover()
    if not watched and not pattern:
        print("resmon: nothing to watch (--pid or --match).", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    started = time.time()
    deadline = started + args.duration if args.duration else None
    psutil.cpu_percent(None)
    for w in watched.values():
        w.sample()                      # primes cpu_percent
    ended = set()
    reason = "all processes ended"
    with open(args.out, "a", encoding="utf-8") as out:
        def write(obj):
            out.write(json.dumps(obj, separators=(",", ":")) + "\n")
            out.flush()

        write({"type": "meta", "title": args.title or "", "started": started, "interval": args.interval,
               "cpus": psutil.cpu_count() or 1, "ram_mb": round(psutil.virtual_memory().total / MB),
               "host": platform.node(),
               "processes": {k: w.proc.pid for k, w in watched.items()}})
        def gone(proc):
            try:
                return not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
            except psutil.Error:             # ended between the two questions
                return True

        def all_gone():
            return bool(watched) and not pattern and all(gone(w.proc) for w in watched.values())

        try:
            while True:
                # Sleep in short steps: when the processes end, stop now, not a whole interval later.
                wake = time.time() + args.interval
                while time.time() < wake and not all_gone():
                    time.sleep(min(0.25, max(0.0, wake - time.time())))
                discover()
                now = time.time()
                sample = {}
                for label, w in list(watched.items()):
                    if label in ended:
                        continue
                    s = w.sample()
                    if s is None:
                        ended.add(label)
                        write({"type": "exit", "t": now, "label": label})
                    else:
                        sample[label] = s
                vm = psutil.virtual_memory()
                write({"t": round(now, 2), "p": sample,
                       "sys": {"cpu": psutil.cpu_percent(None), "mem": round(vm.used / MB)}})
                if watched and len(ended) == len(watched) and not (pattern and args.duration):
                    break
                if deadline and now >= deadline:
                    reason = "duration reached"
                    break
        except KeyboardInterrupt:
            reason = "stopped"
        write({"type": "end", "t": time.time(), "reason": reason})
    if args.report:
        try:
            render(args.out, args.report, args)
        except Exception as exc:  # noqa: BLE001 -- the data is kept either way
            print(f"resmon: report failed: {exc}", file=sys.stderr)
            return 1
    return 0


# ============================================================== analysis

def load(path: str):
    meta, samples, exits, end = {}, [], {}, None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue           # a line cut by a crash
            kind = obj.get("type")
            if kind == "meta":
                meta = meta or obj
            elif kind == "exit":
                exits[obj["label"]] = obj["t"]
            elif kind == "end":
                end = obj
            elif "t" in obj:
                samples.append(obj)
    return meta, samples, exits, end


def _fit(xs, ys):
    """Least-squares slope and intercept."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx


def _pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def _median(values):
    return _pct(values, 0.5)


def analyse(meta, samples, max_growth=MAX_GROWTH_MB_PER_H, min_share=MIN_GROWTH_SHARE, min_steady=MIN_STEADY_S):
    t0 = meta.get("started") or (samples[0]["t"] if samples else 0)
    labels = []
    for s in samples:
        for k in s["p"]:
            if k not in labels:
                labels.append(k)
    out = {}
    for label in labels:
        pts = [(s["t"] - t0, s["p"][label]) for s in samples if label in s["p"]]
        if not pts:
            continue
        span = pts[-1][0] - pts[0][0]
        warm = min(WARMUP_MAX_S, span * WARMUP_SHARE)
        wind = min(WINDDOWN_MAX_S, span * WINDDOWN_SHARE)
        steady = [(t, v) for t, v in pts if warm <= t - pts[0][0] <= span - wind] or pts
        steady_span = steady[-1][0] - steady[0][0]
        res = {"samples": len(pts), "span_s": span, "warmup_s": warm, "winddown_s": wind, "steady_s": steady_span}
        for key in ("rss", "priv"):
            ys = [v[key] for _, v in steady]
            xs = [t / 3600 for t, _ in steady]
            slope, icpt = _fit(xs, ys)
            k = max(1, len(ys) // 20)
            first, last = _median(ys[:k]), _median(ys[-k:])
            res[key] = {"start": pts[0][1][key], "steady_start": first, "end": last,
                        "peak": max(v[key] for _, v in pts), "slope_mb_h": slope,
                        "intercept": icpt, "growth_mb": last - first}
        cpus = [v["cpu"] for _, v in steady]
        slope, _ = _fit([t / 3600 for t, _ in steady], cpus)
        res["cpu"] = {"mean": sum(cpus) / len(cpus), "p95": _pct(cpus, 0.95), "max": max(v["cpu"] for _, v in pts),
                      "slope_h": slope}
        for key in ("thr", "h"):
            vals = [v[key] for _, v in steady]
            k = max(1, len(vals) // 20)
            res[key] = {"start": _median(vals[:k]), "end": _median(vals[-k:]), "max": max(v[key] for _, v in pts)}
        mem = res["priv"]
        level = max(mem["steady_start"], 1.0)
        if steady_span < min_steady:
            verdict, why = "SHORT", (f"only {_duration(steady_span)} after the warm-up; "
                                     f"{_duration(min_steady)} are needed to judge a trend")
        elif mem["slope_mb_h"] > max_growth and mem["growth_mb"] > level * min_share:
            verdict, why = "GROWING", (f"private memory rises {mem['slope_mb_h']:.1f} MB/h "
                                       f"(limit {max_growth:g} MB/h), +{mem['growth_mb']:.1f} MB since the warm-up")
        else:
            verdict, why = "STABLE", (f"private memory trend {mem['slope_mb_h']:+.1f} MB/h "
                                      f"(limit {max_growth:g} MB/h), {mem['growth_mb']:+.1f} MB since the warm-up")
        res["verdict"], res["why"] = verdict, why
        out[label] = res
    return out


# ============================================================== report

def _duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def _clock(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    return f"{h}:{rem // 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


PALETTE = ["#2f7de1", "#1a9c83", "#c77c0e", "#7d5ba6", "#c0392b", "#5d6d7e", "#b9770e", "#117a65"]

# The interactive chart ("Over time"): the samples go into the page as JSON,
# this script draws them. One band per metric, all on one time axis; the
# checkboxes pick metrics and processes; hovering shows every visible value at
# that moment; dragging zooms into a period (double-click: all of it). No
# library: the report is one file that opens anywhere, offline.
CHART_JS = r"""
(function () {
  var D = JSON.parse(document.getElementById('rm-data').textContent);
  var host = document.getElementById('rm-chart');
  var tip = document.getElementById('rm-tip');
  var SVGNS = 'http://www.w3.org/2000/svg';
  var BANDS = [
    { id: 'priv', title: 'Private memory', unit: 'MB', dec: 1, on: true, fit: true },
    { id: 'rss', title: 'Working set', unit: 'MB', dec: 1, on: false },
    { id: 'cpu', title: 'CPU', unit: '% of one core', dec: 1, on: true },
    { id: 'thr', title: 'Threads', unit: '', dec: 0, on: false },
    { id: 'h', title: D.handles, unit: '', dec: 0, on: false },
    { id: 'scpu', title: 'Machine CPU', unit: '% of all cores', dec: 1, on: false, sys: 'cpu', color: '#5d6d7e' },
    { id: 'smem', title: 'Machine memory in use', unit: 'GB', dec: 2, on: false, sys: 'mem', color: '#7d5ba6' }
  ];
  var L = 66, R = 18, BAND_H = 132, HEAD = 26, AXIS = 26;
  var st = { procs: {}, trend: true, view: null, idx: null, drag: null, layout: null };
  D.procs.forEach(function (p) { st.procs[p.label] = true; });
  var T = D.t, N = T.length;

  // ---- controls
  var ctl = document.getElementById('rm-controls');
  function box(label, checked, onchange, color) {
    var l = document.createElement('label');
    var i = document.createElement('input');
    i.type = 'checkbox'; i.checked = checked;
    i.addEventListener('change', function () { onchange(i.checked); draw(); });
    l.appendChild(i);
    if (color) { var sw = document.createElement('i'); sw.style.background = color; l.appendChild(sw); }
    l.appendChild(document.createTextNode(label));
    return l;
  }
  function group(title, items) {
    var g = document.createElement('fieldset');
    var lg = document.createElement('legend'); lg.textContent = title; g.appendChild(lg);
    items.forEach(function (x) { g.appendChild(x); });
    ctl.appendChild(g);
  }
  group('Show', BANDS.map(function (b) { return box(b.title, b.on, function (v) { b.on = v; }); }));
  group('Processes', D.procs.map(function (p) { return box(p.label, true, function (v) { st.procs[p.label] = v; }, p.color); })
    .concat([box('trend (dashed)', true, function (v) { st.trend = v; })]));
  var reset = document.createElement('button');
  reset.type = 'button'; reset.textContent = 'Reset zoom'; reset.disabled = true;
  reset.addEventListener('click', function () { st.view = null; draw(); });
  var hint = document.createElement('span');
  hint.className = 'rm-hint';
  hint.textContent = 'Hover for the values at a moment · drag to zoom · double-click for all · arrow keys step';
  var bar = document.createElement('div'); bar.className = 'rm-bar'; bar.appendChild(reset); bar.appendChild(hint);
  ctl.appendChild(bar);

  // ---- helpers
  function nice(v) {
    if (v <= 0) return 1;
    var e = Math.pow(10, Math.floor(Math.log10(v)));
    var ms = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < ms.length; i++) if (v <= ms[i] * e) return ms[i] * e;
    return 10 * e;
  }
  function clock(sec) {
    sec = Math.max(0, Math.round(sec));
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
  }
  function wall(sec) { return new Date((D.start + sec) * 1000).toLocaleTimeString(); }
  function nearest(t) {
    var lo = 0, hi = N - 1;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (T[mid] < t) lo = mid; else hi = mid; }
    return Math.abs(T[lo] - t) <= Math.abs(T[hi] - t) ? lo : hi;
  }
  function el(name, attrs, parent) {
    var n = document.createElementNS(SVGNS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function seriesOf(b) {
    if (b.sys) return [{ label: b.sys === 'cpu' ? 'machine' : 'machine', color: b.color, v: D.sys[b.sys] }];
    return D.procs.filter(function (p) { return st.procs[p.label]; })
      .map(function (p) { return { label: p.label, color: p.color, v: p[b.id], fit: b.fit ? p.fit : null }; });
  }
  function fmt(v, b) { return v == null ? '—' : Number(v).toFixed(b.dec) + (b.unit && b.unit.charAt(0) !== '%' ? ' ' + b.unit : (b.unit ? ' %' : '')); }

  // ---- drawing
  function draw() {
    host.innerHTML = '';
    tip.hidden = true;
    var bands = BANDS.filter(function (b) { return b.on; });
    reset.disabled = !st.view;
    if (!N || !bands.length) { host.textContent = N ? 'Tick a metric to show.' : 'No samples.'; return; }
    var W = Math.max(480, host.clientWidth), PW = W - L - R;
    var a = st.view ? st.view[0] : T[0], z = st.view ? st.view[1] : T[N - 1];
    if (z - a < 1) z = a + 1;
    var i0 = Math.max(0, nearest(a) - 1), i1 = Math.min(N - 1, nearest(z) + 1);
    var X = function (t) { return L + PW * (t - a) / (z - a); };
    var H = bands.length * (BAND_H + HEAD) + AXIS;
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img',
      'aria-label': 'Resources over time: ' + bands.map(function (b) { return b.title; }).join(', ') });
    var defs = el('defs', {}, svg);
    var clip = el('clipPath', { id: 'rm-clip' }, defs);
    el('rect', { x: L, y: 0, width: PW, height: H }, clip);
    // time ticks
    var steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];
    var step = steps.filter(function (s) { return (z - a) / s <= 8; })[0] || 43200;
    var layout = [];
    bands.forEach(function (b, n) {
      var top = n * (BAND_H + HEAD) + HEAD, bot = top + BAND_H;
      var ser = seriesOf(b);
      var lo = Infinity, hi = -Infinity;
      ser.forEach(function (s) { for (var i = i0; i <= i1; i++) { var v = s.v[i]; if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } } });
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      if (lo >= hi * 0.5 && hi > 0) lo = lo - (hi - lo) * 0.25; else lo = Math.min(0, lo);
      if (b.unit.charAt(0) === '%' || b.unit === '') lo = Math.max(0, lo);
      var ystep = nice((hi - lo) / 4 || 1);
      lo = Math.floor(lo / ystep) * ystep;
      var top_ = lo + ystep * Math.max(1, Math.ceil((hi - lo) / ystep));
      var Y = function (v) { return bot - (bot - top) * (v - lo) / (top_ - lo); };
      var t = el('text', { x: L, y: top - 9, 'class': 'rm-title' }, svg);
      t.textContent = b.title + (b.unit ? ' (' + b.unit + ')' : '');
      for (var v = lo; v <= top_ + ystep / 2; v += ystep) {
        el('line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v), 'class': 'rm-grid' }, svg);
        var lab = el('text', { x: L - 8, y: Y(v) + 4, 'class': 'rm-ax', 'text-anchor': 'end' }, svg);
        lab.textContent = +v.toFixed(3);
      }
      for (var tt = Math.ceil(a / step) * step; tt <= z; tt += step) {
        el('line', { x1: X(tt), x2: X(tt), y1: top, y2: bot, 'class': 'rm-grid' }, svg);
      }
      var g = el('g', { 'clip-path': 'url(#rm-clip)' }, svg);
      ser.forEach(function (s) {
        // One pixel column at most per point pair: its min and max (spikes survive).
        // A missing value (the process had ended) lifts the pen.
        var d = [], col = null, mn = 0, mx = 0, pen = false;
        function flush() {
          if (col == null) return;
          d.push((pen ? 'L' : 'M') + col + ',' + Y(mn).toFixed(1));
          if (mx !== mn) d.push('L' + col + ',' + Y(mx).toFixed(1));
          pen = true;
        }
        for (var i = i0; i <= i1; i++) {
          var v = s.v[i];
          if (v == null) { flush(); col = null; pen = false; continue; }
          var c = Math.round(X(T[i]));
          if (c !== col) { flush(); col = c; mn = mx = v; }
          else { if (v < mn) mn = v; if (v > mx) mx = v; }
        }
        flush();
        if (d.length) el('path', { d: d.join(' '), fill: 'none', stroke: s.color, 'stroke-width': 1.6, 'stroke-linejoin': 'round' }, g);
        if (s.fit && st.trend) {
          var f = s.fit, from = Math.max(f[2], a), to = Math.min(f[3], z);
          if (to > from) el('line', { x1: X(from), y1: Y(f[1] + f[0] * from), x2: X(to), y2: Y(f[1] + f[0] * to),
            stroke: s.color, 'stroke-width': 1.4, 'stroke-dasharray': '6 5' }, g);
        }
      });
      layout.push({ band: b, ser: ser, Y: Y, top: top, bot: bot });
    });
    // the time axis, under the last band
    var yb = bands.length * (BAND_H + HEAD);
    for (var tk = Math.ceil(a / step) * step; tk <= z; tk += step) {
      var lab2 = el('text', { x: X(tk), y: yb + 16, 'class': 'rm-ax', 'text-anchor': 'middle' }, svg);
      lab2.textContent = clock(tk);
    }
    // cursor, selection, and the surface that takes the mouse
    var cur = el('g', { 'class': 'rm-cursor', visibility: 'hidden' }, svg);
    el('line', { x1: 0, x2: 0, y1: HEAD, y2: yb, 'class': 'rm-cursor-line' }, cur);
    var sel = el('rect', { x: 0, y: HEAD, width: 0, height: yb - HEAD, 'class': 'rm-sel', visibility: 'hidden' }, svg);
    var surf = el('rect', { x: L, y: 0, width: PW, height: yb, fill: 'transparent', 'class': 'rm-surface' }, svg);
    host.appendChild(svg);
    function tAt(ev) {
      var r = svg.getBoundingClientRect();
      var x = (ev.clientX - r.left) * W / r.width;
      return a + (Math.min(Math.max(x, L), W - R) - L) / PW * (z - a);
    }
    st.layout = { W: W, a: a, z: z, X: X, bands: layout, cur: cur, sel: sel, svg: svg, PW: PW, tAt: tAt };
    surf.addEventListener('mousemove', function (ev) {
      var t = tAt(ev);
      if (st.drag != null) {
        var x1 = X(Math.min(st.drag, t)), x2 = X(Math.max(st.drag, t));
        sel.setAttribute('x', x1); sel.setAttribute('width', x2 - x1); sel.setAttribute('visibility', 'visible');
      }
      show(nearest(t), ev);
    });
    surf.addEventListener('mouseleave', function () { if (st.drag == null) hide(); });
    surf.addEventListener('mousedown', function (ev) { ev.preventDefault(); st.drag = tAt(ev); });
    surf.addEventListener('dblclick', function () { st.view = null; draw(); });
    if (st.idx != null && T[st.idx] >= a && T[st.idx] <= z) show(st.idx, null);
  }

  function show(i, ev) {
    var lay = st.layout;
    if (!lay) return;
    st.idx = i;
    var x = lay.X(T[i]);
    var cur = lay.cur;
    cur.setAttribute('visibility', 'visible');
    var line = cur.firstChild;
    line.setAttribute('x1', x); line.setAttribute('x2', x);
    while (cur.childNodes.length > 1) cur.removeChild(cur.lastChild);
    var rows = ['<div class="rm-tip-head"><b>+' + clock(T[i]) + '</b> · ' + wall(T[i]) + '</div>'];
    lay.bands.forEach(function (bl) {
      rows.push('<div class="rm-tip-band">' + bl.band.title + '</div>');
      bl.ser.forEach(function (s) {
        var v = s.v[i];
        if (v != null) el('circle', { cx: x, cy: bl.Y(v), r: 3.6, fill: s.color, 'class': 'rm-dot' }, cur);
        rows.push('<div class="rm-tip-row"><i style="background:' + s.color + '"></i><span>' + s.label +
                  '</span><b>' + fmt(v, bl.band) + '</b></div>');
      });
    });
    tip.innerHTML = rows.join('');
    tip.hidden = false;
    // The tip sits in the chart's card (position: relative): place it there, beside
    // the cursor line, on the side with room, and inside the card.
    var box = tip.offsetParent || host;
    var cr = box.getBoundingClientRect(), sr = lay.svg.getBoundingClientRect(), hr = host.getBoundingClientRect();
    var px = (x / lay.W) * sr.width + (sr.left - cr.left);
    var py = ev ? ev.clientY - cr.top : (hr.top - cr.top) + 40;
    var left = px + 14;
    if (left + tip.offsetWidth > box.clientWidth) left = px - 14 - tip.offsetWidth;
    tip.style.left = Math.max(0, left) + 'px';
    tip.style.top = Math.max(0, Math.min(py - 20, box.clientHeight - tip.offsetHeight)) + 'px';
  }
  function hide() {
    tip.hidden = true;
    if (st.layout) st.layout.cur.setAttribute('visibility', 'hidden');
  }
  host.addEventListener('keydown', function (ev) {
    if (!N) return;
    var stepN = ev.shiftKey ? 10 : 1;
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
      ev.preventDefault();
      var i = st.idx == null ? 0 : st.idx + (ev.key === 'ArrowRight' ? stepN : -stepN);
      show(Math.max(0, Math.min(N - 1, i)), null);
    } else if (ev.key === 'Escape') { hide(); }
  });
  // One handler for the end of a drag, whatever is drawn now.
  window.addEventListener('mouseup', function (ev) {
    var lay = st.layout;
    if (st.drag == null || !lay) return;
    var t = lay.tAt(ev), from = Math.min(st.drag, t), to = Math.max(st.drag, t);
    st.drag = null;
    lay.sel.setAttribute('visibility', 'hidden');
    if (Math.abs(lay.X(to) - lay.X(from)) > 6) { st.view = [from, to]; draw(); }
  });
  var timer = null;
  window.addEventListener('resize', function () { clearTimeout(timer); timer = setTimeout(draw, 120); });
  draw();
})();
"""


CSS = """
:root { --bg:#f6f8f7; --card:#ffffff; --ink:#18221e; --muted:#5b6b64; --rule:#dde5e1; --grid:#e8eeeb;
  --ok:#1a7f4b; --okbg:#e3f5ea; --bad:#b03a2e; --badbg:#fbe7e4; --warn:#9a6700; --warnbg:#fff4d6; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f1513; --card:#172120; --ink:#e8eeea; --muted:#93a39b; --rule:#2a3833;
  --grid:#223029; --ok:#6fd49b; --okbg:#173326; --bad:#f1948a; --badbg:#3a1f1c; --warn:#f8c471; --warnbg:#3a2f14; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 "Segoe UI", system-ui, sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding-block: 28px 60px; padding-inline: 20px; }
h1 { font-size: 1.7rem; margin: 0 0 4px; text-wrap: balance; }
h2 { font-size: 1.15rem; margin: 34px 0 10px; }
.meta { color: var(--muted); font-size: 0.9rem; }
.verdict { display: inline-block; font-weight: 700; letter-spacing: 0.04em; padding: 2px 10px; border-radius: 4px; font-size: 0.85rem; }
.v-STABLE { color: var(--ok); background: var(--okbg); } .v-GROWING { color: var(--bad); background: var(--badbg); }
.v-SHORT { color: var(--warn); background: var(--warnbg); }
.overall { display: flex; align-items: center; gap: 14px; margin: 18px 0 6px; padding: 14px 18px; background: var(--card);
  border: 1px solid var(--rule); border-radius: 10px; }
.overall .verdict { font-size: 1.05rem; padding: 4px 14px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; background: var(--card); border: 1px solid var(--rule); border-radius: 10px;
  font-variant-numeric: tabular-nums; font-size: 0.9rem; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--rule); text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
tr.why-row td { text-align: left; white-space: normal; color: var(--muted); font-size: 0.84rem; padding-top: 0; }
tr:has(+ tr.why-row) td { border-bottom: none; }
.rm-card { position: relative; background: var(--card); border: 1px solid var(--rule); border-radius: 10px; padding: 12px 14px 10px; }
#rm-controls { display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: flex-start; margin-bottom: 6px; }
#rm-controls fieldset { border: 0; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: center; }
#rm-controls legend { float: left; margin-right: 10px; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted); }
#rm-controls label { display: inline-flex; align-items: center; gap: 5px; font-size: 0.88rem; cursor: pointer; }
#rm-controls label i { display: inline-block; width: 16px; height: 3px; border-radius: 2px; }
.rm-bar { flex-basis: 100%; display: flex; align-items: center; gap: 12px; }
.rm-bar button { font: inherit; font-size: 0.82rem; padding: 2px 10px; border-radius: 5px; border: 1px solid var(--rule);
  background: var(--bg); color: var(--ink); cursor: pointer; }
.rm-bar button:disabled { opacity: 0.45; cursor: default; }
.rm-hint { font-size: 0.8rem; color: var(--muted); }
#rm-chart { position: relative; outline: none; }
#rm-chart:focus-visible { box-shadow: 0 0 0 2px var(--ok); border-radius: 6px; }
#rm-chart svg { display: block; width: 100%; height: auto; }
.rm-grid { stroke: var(--grid); stroke-width: 1; }
.rm-ax { fill: var(--muted); font-size: 11px; font-family: Consolas, monospace; }
.rm-title { fill: var(--ink); font-size: 12.5px; font-weight: 600; }
.rm-surface { cursor: crosshair; }
.rm-cursor-line { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 3 3; }
.rm-dot { stroke: var(--card); stroke-width: 1.5; }
.rm-sel { fill: var(--ok); fill-opacity: 0.12; stroke: var(--ok); stroke-opacity: 0.5; }
#rm-tip { position: absolute; z-index: 2; pointer-events: none; min-width: 210px; padding: 8px 10px;
  background: var(--card); border: 1px solid var(--rule); border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,0.18);
  font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.rm-tip-head { margin-bottom: 4px; }
.rm-tip-band { margin-top: 6px; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); }
.rm-tip-row { display: flex; align-items: center; gap: 7px; }
.rm-tip-row i { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.rm-tip-row span { flex: 1; }
@media (prefers-reduced-motion: no-preference) { #rm-tip { transition: left 60ms linear, top 60ms linear; } }
.method { color: var(--muted); font-size: 0.88rem; max-width: 80ch; }
.method li { margin: 3px 0; }
"""


def render(src: str, dst: str, args=None) -> str:
    meta, samples, exits, end = load(src)
    max_growth = getattr(args, "max_growth", None) or MAX_GROWTH_MB_PER_H
    min_steady = getattr(args, "min_steady", None)
    min_steady = MIN_STEADY_S if min_steady is None else min_steady
    res = analyse(meta, samples, max_growth=max_growth, min_steady=min_steady)
    t0 = meta.get("started") or (samples[0]["t"] if samples else time.time())
    t_end = (samples[-1]["t"] - t0) if samples else 0
    labels = list(res)
    colors = {lb: PALETTE[i % len(PALETTE)] for i, lb in enumerate(labels)}

    # The chart's data: one time axis, a value (or null) per sample and series.
    ts = [round(sm["t"] - t0, 1) for sm in samples]
    procs = []
    for lb, r in res.items():
        first = next((sm["t"] - t0 for sm in samples if lb in sm["p"]), 0)
        last = max((sm["t"] - t0 for sm in samples if lb in sm["p"]), default=first)
        entry = {"label": lb, "color": colors[lb],
                 # the trend, as fitted: MB = intercept + slope * hours since the start
                 "fit": [r["priv"]["slope_mb_h"] / 3600, r["priv"]["intercept"],
                         first + r["warmup_s"], last - r.get("winddown_s", 0)]}
        for key in ("priv", "rss", "cpu", "thr", "h"):
            entry[key] = [sm["p"][lb][key] if lb in sm["p"] else None for sm in samples]
        procs.append(entry)
    chart = {"start": t0, "t": ts, "procs": procs, "handles": "Handles" if os.name == "nt" else "Open files",
             "sys": {"cpu": [sm.get("sys", {}).get("cpu") for sm in samples],
                     "mem": [round(sm["sys"]["mem"] / 1024, 3) if "sys" in sm else None for sm in samples]}}
    chart_json = json.dumps(chart, separators=(",", ":")).replace("</", "<\\/")

    verdicts = [r["verdict"] for r in res.values()]
    overall = "GROWING" if "GROWING" in verdicts else ("SHORT" if "SHORT" in verdicts or not verdicts else "STABLE")
    summary = {"STABLE": "No process's memory grows beyond the limit after its warm-up.",
               "GROWING": "At least one process's memory keeps growing after its warm-up.",
               "SHORT": "The run is too short after the warm-up to judge a trend."}[overall]
    rows = []
    for lb, r in res.items():
        p, c = r["priv"], r["cpu"]
        rows.append(
            f'<tr><td><b style="color:{colors[lb]}">{html.escape(lb)}</b></td>'
            f'<td><span class="verdict v-{r["verdict"]}">{r["verdict"]}</span></td>'
            f'<td>{p["steady_start"]:.1f} → {p["end"]:.1f}</td><td>{p["peak"]:.1f}</td>'
            f'<td>{p["slope_mb_h"]:+.2f}</td><td>{r["rss"]["steady_start"]:.1f} → {r["rss"]["end"]:.1f}</td>'
            f'<td>{c["mean"]:.1f} / {c["p95"]:.1f} / {c["max"]:.1f}</td>'
            f'<td>{r["thr"]["start"]:.0f} → {r["thr"]["end"]:.0f}</td><td>{r["h"]["start"]:.0f} → {r["h"]["end"]:.0f}</td>'
            f'<td>{_duration(r["span_s"])}</td></tr>'
            f'<tr class="why-row"><td></td><td colspan="9">{html.escape(r["why"])}</td></tr>')
    started = _dt.datetime.fromtimestamp(t0).strftime("%Y-%m-%d %H:%M:%S")
    ended = _dt.datetime.fromtimestamp((end or {}).get("t", t0 + t_end)).strftime("%Y-%m-%d %H:%M:%S")
    title = meta.get("title") or "Test run"
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resources · {html.escape(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>Resources of the run: {html.escape(title)}</h1>
<div class="meta">{started} → {ended} · {_duration(t_end)} · a sample every {meta.get('interval', '?')} s ({len(samples)} samples)
 · {meta.get('cpus', '?')} CPUs, {meta.get('ram_mb', 0) / 1024:.1f} GB RAM · ended: {html.escape((end or {}).get('reason', 'still running'))}</div>
<div class="overall"><span class="verdict v-{overall}">{overall}</span><span>{summary}</span></div>

<h2>Per process</h2>
<div class="table-wrap"><table>
<thead><tr><th>Process</th><th>Verdict</th><th>Private MB<br>after warm-up → end</th><th>Peak MB</th><th>Trend<br>MB/h</th>
<th>Working set MB</th><th>CPU % of a core<br>mean / p95 / max</th><th>Threads</th><th>Handles</th><th>Watched</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>

<h2>Over time</h2>
<div class="rm-card">
<div id="rm-controls"></div>
<div id="rm-chart" tabindex="0" aria-label="Chart of the run's resources; arrow keys step through the samples"></div>
<div id="rm-tip" hidden></div>
</div>
<script type="application/json" id="rm-data">{chart_json}</script>
<script>{CHART_JS}</script>

<h2>How this is judged</h2>
<ul class="method">
<li>A separate process sampled every {meta.get('interval', '?')} s; each figure includes the processes a watched process started.</li>
<li><b>Private memory</b> (committed memory only this process uses) decides the verdict; the working set can shrink and grow with the OS's paging.</li>
<li>The first {WARMUP_SHARE:.0%} of a process's time (at most {_duration(WARMUP_MAX_S)}) is <b>warm-up</b> — imports, connections, caches — and the last {WINDDOWN_SHARE:.0%} (at most {_duration(WINDDOWN_MAX_S)}) is <b>wind-down</b> — the log and report being written. Both are left out of the trend, not of the peak.</li>
<li>The <b>trend</b> is a least-squares line through the rest. <b>GROWING</b>: steeper than {max_growth:g} MB/h and more than {MIN_GROWTH_SHARE:.0%} above the level after the warm-up. <b>SHORT</b>: less than {_duration(min_steady)} after the warm-up.</li>
<li>CPU is a percentage of one core (100 = one core busy). Data: <code>{html.escape(os.path.basename(src))}</code>, one JSON line per sample.</li>
</ul>
</main></body></html>
"""
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, dst)
    return overall


# ============================================================== command line

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="resmon", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="sample processes until they end (or --duration)")
    r.add_argument("--out", required=True, help="JSON lines file to append samples to")
    r.add_argument("--pid", action="append", help="LABEL=PID of a process to watch (repeatable)")
    r.add_argument("--match", help="also watch every process whose command line matches this regex (checked each sample)")
    r.add_argument("--interval", type=float, default=5.0, help="seconds between samples (default 5)")
    r.add_argument("--duration", type=_parse_duration, help="stop after this long (e.g. 8h)")
    r.add_argument("--title", help="title of the report")
    r.add_argument("--report", help="write the HTML report here at the end")
    r.add_argument("--max-growth", type=float, default=MAX_GROWTH_MB_PER_H, help="MB/h a process may grow (default 10)")
    r.add_argument("--min-steady", type=_parse_duration, default=MIN_STEADY_S,
                   help="time after the warm-up needed for a verdict (default 10m)")
    p = sub.add_parser("report", help="render the HTML report from a samples file (also while recording)")
    p.add_argument("src")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--max-growth", type=float, default=MAX_GROWTH_MB_PER_H)
    p.add_argument("--min-steady", type=_parse_duration, default=MIN_STEADY_S)
    args = ap.parse_args(argv)
    if args.cmd == "record":
        return record(args)
    verdict = render(args.src, args.out, args)
    print(f"{verdict}: {args.out}")
    return 0 if verdict != "GROWING" else 3


if __name__ == "__main__":
    sys.exit(main())
