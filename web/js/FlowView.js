/**
 * @fileoverview Flow diagram: draws a structured test flow as SVG.
 *
 * Input is the runner's structure of the flow (for Robot Framework flow
 * files: the RobotFramework AIO fork's own robot.flow.graph.structure(),
 * via /api/test-project/inspect) -- phases, each a list of steps, where
 * loops and tries carry `body` / `recovery` and decisions `yes` / `no`.
 * Because the fork only accepts structured flows, the layout follows from
 * the structure: no graph layout library, no crossing edges to untangle.
 *
 *   one lane per phase (setup, tests, teardown), left to right
 *   a sequence runs top to bottom along one centre line
 *   a loop / try is a frame: header on its top edge, body inside,
 *     recovery to the right; "next" returns along the left side
 *   a decision is a diamond whose yes / no branches re-join below
 *
 * IIFE attaching to MM.flowView.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var NW = 236;   // node width
  var NH = 50;    // node height
  var VG = 30;    // vertical gap between steps (holds the arrow)
  var CG = 44;    // gap between side-by-side columns
  var PAD = 18;   // inner padding of a loop / try frame
  var LP = 22;    // inner padding of a lane
  var LG = 34;    // gap between lanes
  var TH = 36;    // lane title band
  var PILL = 30;  // start / end height

  var _renders = 0;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function clip(s, n) {
    s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  function max(list, fn) {
    return list.reduce(function (m, x) { return Math.max(m, fn(x)); }, 0);
  }

  // Every layout is { w, h, cx, kind, svg(x, y) }: cx is where the incoming
  // arrow enters (top) and the outgoing one leaves (bottom).

  function sequence(steps, ctx, inRecovery) {
    var items = (steps || []).map(function (s) { return step(s, ctx, inRecovery); });
    if (!items.length) {
      return { w: 40, h: 0, cx: 20, empty: true, svg: function () { return ''; } };
    }
    var cx = max(items, function (i) { return i.cx; });
    var right = max(items, function (i) { return i.w - i.cx; });
    var h = items.reduce(function (a, i) { return a + i.h; }, 0) + VG * (items.length - 1);
    return {
      w: cx + right, h: h, cx: cx,
      svg: function (x, y) {
        var out = '';
        var yy = y;
        items.forEach(function (it, k) {
          if (k) {
            out += ctx.arrow(x + cx, yy - VG, x + cx, yy, items[k - 1].kind === 'loop' ? 'done' : '', '');
          }
          out += it.svg(x + cx - it.cx, yy);
          yy += it.h + VG;
        });
        return out;
      }
    };
  }

  function step(s, ctx, inRecovery) {
    if (s.kind === 'loop' || s.kind === 'try') return guarded(s, ctx, inRecovery);
    if (s.kind === 'decision') return decision(s, ctx, inRecovery);
    return action(s, ctx, inRecovery);
  }

  function tip(s) {
    var parts = [s.id + ' (' + s.kind + ')'];
    if (s.keyword) parts.push(s.keyword + ((s.args || []).length ? '  ' + s.args.join('  ') : ''));
    if ((s.assign || []).length) parts.push('assign ' + s.assign.join(', '));
    if (s.kind === 'gate') parts.push('timeout ' + s.timeout + ', every ' + (s.interval || '2s') + ', else ' + (s.on_timeout || 'unknown'));
    if (s.condition) parts.push('if ' + s.condition);
    parts.push('Click to show it in Script');
    return parts.join('\n');
  }

  function nodeOpen(s, ctx, extra) {
    return '<g class="fv-node fv-' + esc(s.kind) + (extra || '') + (ctx.error === s.id ? ' fv-error' : '') +
      '" data-node="' + esc(s.id) + '" tabindex="0"><title>' + esc(tip(s)) + '</title>';
  }

  function labels(x, y, w, h, title, sub) {
    var cx = x + w / 2;
    return sub
      ? '<text class="fv-title" x="' + cx + '" y="' + (y + h / 2 - 3) + '">' + esc(clip(title, 30)) + '</text>' +
        '<text class="fv-sub" x="' + cx + '" y="' + (y + h / 2 + 14) + '">' + esc(clip(sub, 40)) + '</text>'
      : '<text class="fv-title" x="' + cx + '" y="' + (y + h / 2 + 5) + '">' + esc(clip(title, 30)) + '</text>';
  }

  function action(s, ctx, inRecovery) {
    var title = s.keyword || s.label || s.id;
    var sub = '';
    if (s.kind === 'gate') {
      sub = 'gate · ' + (s.timeout || '?') + ' · every ' + (s.interval || '2s') +
            ' · else ' + (s.on_timeout || 'unknown');
    } else if (s.kind === 'sleep') {
      title = 'Sleep';
      sub = s.duration || '';
    } else {
      sub = (s.args || []).join('  ');
      if ((s.assign || []).length) sub = (sub ? sub + '  ' : '') + '→ ' + s.assign.join(', ');
    }
    return {
      w: NW, h: NH, cx: NW / 2, kind: s.kind,
      svg: function (x, y) {
        var shape;
        if (s.kind === 'gate') {
          var k = 14;
          shape = '<polygon points="' + [
            (x + k) + ',' + y, (x + NW - k) + ',' + y, (x + NW) + ',' + (y + NH / 2),
            (x + NW - k) + ',' + (y + NH), (x + k) + ',' + (y + NH), x + ',' + (y + NH / 2)
          ].join(' ') + '"/>';
        } else {
          shape = '<rect x="' + x + '" y="' + y + '" width="' + NW + '" height="' + NH + '" rx="7"/>';
        }
        return nodeOpen(s, ctx, inRecovery ? ' fv-in-recovery' : '') + shape + labels(x, y, NW, NH, title, sub) + '</g>';
      }
    };
  }

  function decision(s, ctx, inRecovery) {
    var A = sequence(s.yes, ctx, inRecovery);
    var B = sequence(s.no, ctx, inRecovery);
    // An empty branch still takes a node's width, so both columns clear the
    // diamond's corners and the yes / no lines never run back across it.
    var aw = Math.max(A.w, NW);
    var bw = Math.max(B.w, NW);
    var ax = (aw - A.w) / 2 + A.cx;                  // branch centre lines, relative
    var bx = aw + CG + (bw - B.w) / 2 + B.cx;
    var cx = (ax + bx) / 2;                          // diamond between the branches
    var w = aw + CG + bw;
    var top = NH + VG;
    var bh = Math.max(A.h, B.h);
    var h = top + bh + VG;
    return {
      w: w, h: h, cx: cx, kind: 'decision',
      svg: function (x, y) {
        var dx = x + cx;          // diamond centre
        var yesX = x + ax;        // branch centre lines
        var noX = x + bx;
        var joinY = y + h - 10;
        var out = nodeOpen(s, ctx) +
          '<polygon points="' + [(dx - NW / 2) + ',' + (y + NH / 2), dx + ',' + y, (dx + NW / 2) + ',' + (y + NH / 2), dx + ',' + (y + NH)].join(' ') + '"/>' +
          '<text class="fv-title" x="' + dx + '" y="' + (y + NH / 2 + 5) + '">' + esc(clip(s.condition || s.id, 24)) + '</text></g>';
        out += ctx.path('M' + (dx - NW / 2) + ',' + (y + NH / 2) + ' H' + yesX + ' V' + (y + top), '', 'yes',
                        dx - NW / 2 - 8, y + NH / 2 - 6, undefined, 'end');
        out += ctx.path('M' + (dx + NW / 2) + ',' + (y + NH / 2) + ' H' + noX + ' V' + (y + top), '', 'no',
                        dx + NW / 2 + 8, y + NH / 2 - 6);
        out += A.svg(yesX - A.cx, y + top) + B.svg(noX - B.cx, y + top);
        out += ctx.line('M' + yesX + ',' + (y + top + A.h) + ' V' + joinY + ' H' + dx + ' V' + (y + h), '');
        out += ctx.line('M' + noX + ',' + (y + top + B.h) + ' V' + joinY + ' H' + dx, '');
        return out;
      }
    };
  }

  function guarded(s, ctx, inRecovery) {
    var isLoop = s.kind === 'loop';
    var body = sequence(s.body, ctx, inRecovery);
    var rec = s.recovery ? sequence(s.recovery, ctx, true) : null;
    var bodyX = 40;                    // room for the "next" return on the left
    var cx = bodyX + body.cx;
    var shift = Math.max(0, NW / 2 + 28 - cx);
    bodyX += shift;
    cx += shift;
    var recX = bodyX + body.w + CG;
    var bodyY = NH + VG;
    var w = Math.max(rec ? recX + rec.w + PAD + 14 : bodyX + body.w + PAD, cx + NW / 2 + PAD);
    var h = bodyY + Math.max(body.h, rec ? rec.h : 0) + PAD + 16;
    var sub = isLoop
      ? [s.max_loops ? 'max ' + s.max_loops : '', s.max_seconds ? 'max ' + s.max_seconds : '',
         s.every ? 'every ' + s.every : ''].filter(Boolean).join(' · ')
      : 'recovery: ' + (s.then || 'none');
    return {
      w: w, h: h, cx: cx, kind: s.kind,
      svg: function (x, y) {
        var hx = x + cx - NW / 2;       // header left
        var hr = hx + NW;               // header right
        var bodyTop = y + bodyY;
        var bodyBottom = bodyTop + body.h;
        var out = '<rect class="fv-frame fv-frame-' + s.kind + '" x="' + x + '" y="' + (y + NH / 2) +
          '" width="' + w + '" height="' + (h - NH / 2) + '" rx="14"/>';
        out += nodeOpen(s, ctx) +
          '<rect x="' + hx + '" y="' + y + '" width="' + NW + '" height="' + NH + '" rx="' + (NH / 2) + '"/>' +
          labels(hx, y, NW, NH, isLoop ? 'loop' : 'try', sub) + '</g>';
        out += ctx.arrow(x + cx, y + NH, x + cx, bodyTop, 'body', '');
        out += body.svg(x + cx - body.cx, bodyTop);
        if (isLoop) {
          out += ctx.path('M' + (x + cx) + ',' + bodyBottom + ' V' + (bodyBottom + 12) + ' H' + (x + 14) +
                          ' V' + (y + NH / 2 + 8) + ' H' + (hx - 2), 'next', 'next', x + 18, bodyBottom + 26, true);
        } else {
          out += ctx.line('M' + (x + cx) + ',' + bodyBottom + ' V' + (y + h), '');
        }
        if (rec) {
          var rcx = x + recX + rec.cx;
          var recBottom = bodyTop + rec.h;
          out += '<rect class="fv-rec-zone" x="' + (x + recX - 8) + '" y="' + (bodyTop - 8) +
                 '" width="' + (rec.w + 16) + '" height="' + (rec.h + 16) + '" rx="10"/>';
          out += ctx.path('M' + hr + ',' + (y + NH * 0.38) + ' H' + rcx + ' V' + (bodyTop - 10), 'fail',
                          'on_failure', hr + 8, y + NH * 0.38 - 6, true);
          out += rec.svg(x + recX, bodyTop);
          if (s.then === 'abort') {
            out += ctx.path('M' + rcx + ',' + (recBottom + 8) + ' V' + (y + h), 'fail', 'abort', rcx + 6, y + h - 6, false);
          } else {
            out += ctx.path('M' + rcx + ',' + (recBottom + 8) + ' V' + (recBottom + 20) + ' H' + (x + w - 12) +
                            ' V' + (y + NH * 0.72) + ' H' + (hr + 2), 'cont', 'continue', x + w - 16, recBottom + 34, true, 'end');
          }
        }
        return out;
      }
    };
  }

  function makeCtx(errorNode) {
    var id = 'fv' + (++_renders);
    var markers = { '': id + 'm', next: id + 'n', fail: id + 'f', cont: id + 'f' };
    function marker(kind) { return 'url(#' + markers[kind || ''] + ')'; }
    function text(label, kind, lx, ly, anchor) {
      return label
        ? '<text class="fv-label fv-label-' + (kind || 'then') + '" x="' + lx + '" y="' + ly + '"' +
          (anchor === 'end' ? ' text-anchor="end"' : '') + '>' + esc(label) + '</text>'
        : '';
    }
    return {
      error: errorNode,
      defs: '<defs>' +
        '<marker id="' + markers[''] + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8a99a6"/></marker>' +
        '<marker id="' + markers.next + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7d5ba6"/></marker>' +
        '<marker id="' + markers.fail + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c77c0e"/></marker>' +
        '</defs>',
      arrow: function (x1, y1, x2, y2, label, kind) {
        return '<path class="fv-edge fv-edge-' + (kind || 'then') + '" d="M' + x1 + ',' + y1 + ' V' + (y2 - 1) +
          '" marker-end="' + marker(kind) + '"/>' + text(label, kind, x1 + 7, (y1 + y2) / 2 + 4);
      },
      path: function (d, kind, label, lx, ly, withArrow, anchor) {
        return '<path class="fv-edge fv-edge-' + (kind || 'then') + '" d="' + d + '"' +
          (withArrow === false ? '' : ' marker-end="' + marker(kind) + '"') + '/>' + text(label, kind, lx, ly, anchor);
      },
      line: function (d, kind) {
        return '<path class="fv-edge fv-edge-' + (kind || 'then') + '" d="' + d + '"/>';
      }
    };
  }

  function laneTitle(p) {
    if (p.role === 'setup') return 'Setup · Flow Setup';
    if (p.role === 'teardown') return 'Teardown · Flow Teardown';
    return 'Test · ' + (p.name || 'test');
  }

  /**
   * SVG markup of a flow.
   * @param {object} flow  {name, setup, tests[], teardown} as the runner reports it
   * @param {object} [opts] {error: node id to mark}
   * @returns {string}
   */
  function render(flow, opts) {
    opts = opts || {};
    var ctx = makeCtx(opts.error || null);
    var phases = [flow.setup].concat(flow.tests || [], [flow.teardown]).filter(Boolean);
    if (!phases.length) return '';
    var lanes = phases.map(function (p) { return { p: p, lay: sequence(p.steps, ctx, false) }; });

    var x = 0;
    lanes.forEach(function (l, i) {
      l.first = i === 0;
      l.last = i === lanes.length - 1;
      l.inner = Math.max(l.lay.w, 200);
      l.w = l.inner + 2 * LP;
      l.x = x;
      l.cx = x + LP + (l.inner - l.lay.w) / 2 + l.lay.cx;
      l.top = TH + (l.first ? PILL + VG : 16);
      l.bottom = l.top + l.lay.h;
      x += l.w + LG;
    });
    var W = x - LG;
    var H = max(lanes, function (l) { return l.bottom + (l.last ? VG + PILL : 0); }) + LP + 24;

    var out = '';
    lanes.forEach(function (l) {
      out += '<rect class="fv-lane" x="' + l.x + '" y="0" width="' + l.w + '" height="' + H + '" rx="10"/>' +
             '<text class="fv-lane-title" x="' + (l.x + 14) + '" y="23">' + esc(laneTitle(l.p).toUpperCase()) + '</text>';
    });
    lanes.forEach(function (l, i) {
      if (l.first) {
        out += '<g class="fv-pill"><rect x="' + (l.cx - 45) + '" y="' + TH + '" width="90" height="' + PILL + '" rx="15"/>' +
               '<text class="fv-title" x="' + l.cx + '" y="' + (TH + 20) + '">start</text></g>';
        out += l.lay.empty ? '' : ctx.arrow(l.cx, TH + PILL, l.cx, l.top, '', '');
      }
      out += l.lay.svg(l.cx - l.lay.cx, l.top);
      if (l.last) {
        var ey = l.bottom + VG;
        out += ctx.arrow(l.cx, l.bottom, l.cx, ey, lastKind(l.p) === 'loop' ? 'done' : '', '');
        out += '<g class="fv-pill"><rect x="' + (l.cx - 45) + '" y="' + ey + '" width="90" height="' + PILL + '" rx="15"/>' +
               '<text class="fv-title" x="' + l.cx + '" y="' + (ey + 20) + '">end</text></g>';
      } else {
        // down, along the bottom, up the gap, into the next lane's first step
        var n = lanes[i + 1];
        var gapX = n.x - LG / 2;
        out += ctx.path('M' + l.cx + ',' + l.bottom + ' V' + (H - 12) + ' H' + gapX + ' V' + (TH - 4) +
                        ' H' + n.cx + ' V' + (n.top - 1), '', lastKind(l.p) === 'loop' ? 'done' : '',
                        l.cx + 7, l.bottom + 16);
      }
    });

    return '<svg class="flow-view" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + H +
      '" width="' + W + '" height="' + H + '" role="img" aria-label="' +
      esc('Flow ' + (flow.name || '') + ': ' + phases.map(laneTitle).join(', then ')) + '">' +
      ctx.defs + out + '</svg>';
  }

  function lastKind(p) {
    var steps = p.steps || [];
    return steps.length ? steps[steps.length - 1].kind : '';
  }

  /**
   * Draw into a container; clicking (or Enter on) a node calls onNode(id).
   */
  function mount(container, flow, opts) {
    opts = opts || {};
    container.innerHTML = render(flow, opts);
    if (opts.onNode) {
      container.querySelectorAll('[data-node]').forEach(function (g) {
        function go() { opts.onNode(g.getAttribute('data-node')); }
        g.addEventListener('click', go);
        g.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
      });
    }
  }

  MM.flowView = { render: render, mount: mount };
})();
