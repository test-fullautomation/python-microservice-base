// flow-view: lays out a structured test flow as SVG markup.
//
// Input is the runner's structure of the flow (for Robot Framework flow
// files: the RobotFramework AIO fork's own robot.flow.graph.structure(),
// via /api/test-project/inspect) -- phases, each a list of steps, where
// loops and tries carry `body` / `recovery` and decisions `yes` / `no`.
// Because the fork only accepts structured flows, the layout follows from
// the structure: no graph layout library, no crossing edges to untangle.
//
//   one lane per phase (setup, tests, teardown), left to right
//   a sequence runs top to bottom along one centre line
//   a loop / try is a frame: header on its top edge, body inside,
//     recovery to the right; "next" returns along the left side
//   a decision is a diamond whose yes / no branches re-join below
//
// A run group -- flows that run side by side and meet through the bench --
// is drawn by renderGroup(): one column per member, side by side, and a
// dashed arrow across the channel from the step of one member to the gate
// of another that waits for it (the links come from the runner; see
// inspect_group).
//
// No DOM: view.js / group.js put the markup into the frame; tests call
// render() and renderGroup().

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

// Edit mode: a place a step can be dropped -- before a node, after the last
// one of a region, or into an empty decision branch (flow_edit.py's places).
function dropZone(ctx, x, y, place) {
  if (!ctx.edit) return '';
  return '<g class="fv-drop" data-drop="' + esc(JSON.stringify(place)) + '"><title>Drop a step here</title>' +
    '<circle cx="' + x + '" cy="' + y + '" r="9"/><text x="' + x + '" y="' + (y + 4) + '">+</text></g>';
}

function ownId(id) {
  // Steps of an opened sub-flow belong to its own file: not edited here.
  return id != null && String(id).indexOf('::') < 0;
}

function sequence(steps, ctx, inRecovery) {
  steps = steps || [];
  var items = steps.map(function (s) { return step(s, ctx, inRecovery); });
  if (!items.length) {
    return { w: 40, h: 0, cx: 20, empty: true, svg: function () { return ''; } };
  }
  var cx = max(items, function (i) { return i.cx; });
  var right = max(items, function (i) { return i.w - i.cx; });
  var h = items.reduce(function (a, i) { return a + i.h; }, 0) + VG * (items.length - 1);
  var last = steps[steps.length - 1];
  var tail = ctx.edit && ownId(last.id) && last.kind !== 'decision';
  return {
    w: cx + right, h: h + (tail ? VG : 0), cx: cx,
    svg: function (x, y) {
      var out = '';
      var yy = y;
      items.forEach(function (it, k) {
        if (k) {
          out += ctx.arrow(x + cx, yy - VG, x + cx, yy, items[k - 1].kind === 'loop' ? 'done' : '', '');
        }
        out += it.svg(x + cx - it.cx, yy);
        if (ownId(steps[k].id)) {
          // Drawn after the step so the frame of a loop or try does not cover it.
          out += dropZone(ctx, x + cx, yy - VG / 2, { before: steps[k].id });
        }
        yy += it.h + VG;
      });
      if (tail) out += dropZone(ctx, x + cx, yy - VG / 2, { after: last.id });
      return out;
    }
  };
}

function step(s, ctx, inRecovery) {
  if (s.kind === 'loop' || s.kind === 'try') return guarded(s, ctx, inRecovery);
  if (s.kind === 'decision') return decision(s, ctx, inRecovery);
  if (s.kind === 'flow') return subflow(s, ctx, inRecovery);
  return action(s, ctx, inRecovery);
}

function callArgs(s) {
  var args = s.args && !Array.isArray(s.args) ? s.args : {};
  return Object.keys(args).map(function (k) { return k + '=' + args[k]; }).join('  ');
}

function tip(s) {
  var parts = [s.id + ' (' + s.kind + ')'];
  if (s.kind === 'flow') {
    parts.push('sub-flow ' + ((s.subflow && s.subflow.name) || '') + ' · ' + (s.file || ''));
    if (callArgs(s)) parts.push(callArgs(s));
    if (s.subflow && s.subflow.error) parts.push('problem: ' + s.subflow.error);
    parts.push('Click to find it in the file; ＋ / − opens or closes it here');
    return parts.join('\n');
  }
  if (s.keyword) parts.push(s.keyword + ((s.args || []).length ? '  ' + s.args.join('  ') : ''));
  if ((s.assign || []).length) parts.push('assign ' + s.assign.join(', '));
  if (s.kind === 'gate') parts.push('timeout ' + s.timeout + ', every ' + (s.interval || '2s') + ', else ' + (s.on_timeout || 'unknown'));
  if (s.condition) parts.push('if ' + s.condition);
  parts.push('Click to find it in the file');
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
      ctx.at(s.id, x, y, NW, NH);
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
  var bh = Math.max(A.h, B.h, ctx.edit && (A.empty || B.empty) ? 20 : 0);
  var h = top + bh + VG;
  return {
    w: w, h: h, cx: cx, kind: 'decision',
    svg: function (x, y) {
      var dx = x + cx;          // diamond centre
      var yesX = x + ax;        // branch centre lines
      var noX = x + bx;
      var joinY = y + h - 10;
      ctx.at(s.id, dx - NW / 2, y, NW, NH);
      var out = nodeOpen(s, ctx) +
        '<polygon points="' + [(dx - NW / 2) + ',' + (y + NH / 2), dx + ',' + y, (dx + NW / 2) + ',' + (y + NH / 2), dx + ',' + (y + NH)].join(' ') + '"/>' +
        '<text class="fv-title" x="' + dx + '" y="' + (y + NH / 2 + 5) + '">' + esc(clip(s.condition || s.id, 24)) + '</text></g>';
      out += ctx.path('M' + (dx - NW / 2) + ',' + (y + NH / 2) + ' H' + yesX + ' V' + (y + top), '', 'yes',
                      dx - NW / 2 - 8, y + NH / 2 - 6, undefined, 'end');
      out += ctx.path('M' + (dx + NW / 2) + ',' + (y + NH / 2) + ' H' + noX + ' V' + (y + top), '', 'no',
                      dx + NW / 2 + 8, y + NH / 2 - 6);
      out += A.svg(yesX - A.cx, y + top) + B.svg(noX - B.cx, y + top);
      if (ownId(s.id)) {
        if (A.empty) out += dropZone(ctx, yesX, y + top + 6, { branch: { decision: s.id, label: 'yes' } });
        if (B.empty) out += dropZone(ctx, noX, y + top + 6, { branch: { decision: s.id, label: 'no' } });
      }
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
      ctx.at(s.id, hx, y, NW, NH);
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

// A sub-flow's steps carry ids of their own file. The runner reports a
// position inside a sub-flow as '<sub-flow name>::<id>' (the name is unique
// in a suite), so the drawn ids get the same prefix. A nested sub-flow keeps
// its own steps unprefixed here; they get its name when it is opened.
function prefixed(steps, name) {
  return (steps || []).map(function (s) {
    var c = Object.assign({}, s, { id: name + '::' + s.id });
    ['yes', 'no', 'body', 'recovery'].forEach(function (k) {
      if (Array.isArray(s[k])) c[k] = prefixed(s[k], name);
    });
    return c;
  });
}

// "Predefined process": a box with a bar inside each side.
function subflowShape(x, y) {
  return '<rect x="' + x + '" y="' + y + '" width="' + NW + '" height="' + NH + '" rx="4"/>' +
    '<line class="fv-bar" x1="' + (x + 10) + '" y1="' + y + '" x2="' + (x + 10) + '" y2="' + (y + NH) + '"/>' +
    '<line class="fv-bar" x1="' + (x + NW - 10) + '" y1="' + y + '" x2="' + (x + NW - 10) + '" y2="' + (y + NH) + '"/>';
}

function toggle(id, x, y, open) {
  return '<g class="fv-toggle" data-toggle="' + esc(id) + '" tabindex="0" role="button" aria-label="' +
    (open ? 'Close' : 'Open') + ' the sub-flow"><title>' + (open ? 'Close' : 'Open') + ' the sub-flow here</title>' +
    '<rect x="' + (x + NW - 36) + '" y="' + (y + 5) + '" width="20" height="20" rx="4"/>' +
    '<text x="' + (x + NW - 26) + '" y="' + (y + 20) + '">' + (open ? '−' : '+') + '</text></g>';
}

function subflow(s, ctx, inRecovery) {
  var info = s.subflow || {};
  var name = info.name || s.file || s.id;
  var sub = info.error ? '⚠ ' + info.error : (callArgs(s) || 'sub-flow');
  var canOpen = !info.error && Array.isArray(info.steps);
  var open = canOpen && !!(ctx.expanded || {})[s.id];
  var extra = (inRecovery ? ' fv-in-recovery' : '') + (info.error ? ' fv-error' : '');
  function head(x, y) {
    ctx.at(s.id, x, y, NW, NH);
    return nodeOpen(s, ctx, extra) + subflowShape(x, y) + labels(x, y, NW, NH, name, sub) + '</g>' +
      (canOpen ? toggle(s.id, x, y, open) : '');
  }
  if (!open) {
    return { w: NW, h: NH, cx: NW / 2, kind: 'flow', svg: head };
  }
  var body = sequence(prefixed(info.steps, name), ctx, inRecovery);
  var cx = Math.max(PAD + body.cx, NW / 2 + PAD);
  var w = cx + Math.max(body.w - body.cx, NW / 2) + PAD;
  var bodyY = NH + VG;
  var h = bodyY + body.h + PAD + 10;
  return {
    w: w, h: h, cx: cx, kind: 'flow',
    svg: function (x, y) {
      var bodyTop = y + bodyY;
      var out = '<rect class="fv-frame fv-frame-flow" x="' + x + '" y="' + (y + NH / 2) +
        '" width="' + w + '" height="' + (h - NH / 2) + '" rx="10"/>';
      out += head(x + cx - NW / 2, y);
      out += ctx.arrow(x + cx, y + NH, x + cx, bodyTop, '', '');
      out += body.svg(x + cx - body.cx, bodyTop);
      out += ctx.line('M' + (x + cx) + ',' + (bodyTop + body.h) + ' V' + (y + h), '');
      return out;
    }
  };
}

function makeCtx(errorNode, expanded, edit) {
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
    expanded: expanded || {},   // sub-flow call id -> true when opened in place
    edit: !!edit,               // draw drop zones
    pos: {},
    at: function (nodeId, x, y, w, h) { this.pos[nodeId] = { x: x, y: y, w: w, h: h }; },
    syncMarker: 'url(#' + id + 's)',
    defs: '<defs>' +
      '<marker id="' + markers[''] + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill: var(--fv-faint, #8a99a6)"/></marker>' +
      '<marker id="' + markers.next + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7d5ba6"/></marker>' +
      '<marker id="' + markers.fail + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c77c0e"/></marker>' +
      '<marker id="' + id + 's" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a9c83"/></marker>' +
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
 * Lay a flow out: the lanes and everything in them, drawn from (0, 0).
 * @returns {{W: number, H: number, body: string, titles: string[]}|null} null: nothing to draw
 */
function layoutFlow(flow, ctx) {
  var phases = [flow.setup].concat(flow.tests || [], [flow.teardown]).filter(Boolean);
  if (!phases.length) return null;
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
  return { W: W, H: H, body: out, titles: phases.map(laneTitle) };
}

/**
 * SVG markup of a flow.
 * @param {object} flow  {name, setup, tests[], teardown} as the runner reports it
 * @param {object} [opts] {error: node id to mark, expanded: {sub-flow call id: true}, edit: drop zones}
 * @returns {string}
 */
export function render(flow, opts) {
  opts = opts || {};
  var ctx = makeCtx(opts.error || null, opts.expanded, opts.edit);
  var lay = layoutFlow(flow, ctx);
  if (!lay) return '';
  return '<svg class="flow-view" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + lay.W + ' ' + lay.H +
    '" width="' + lay.W + '" height="' + lay.H + '" role="img" aria-label="' +
    esc('Flow ' + (flow.name || '') + ': ' + lay.titles.join(', then ')) + '">' +
    ctx.defs + lay.body + '</svg>';
}

/**
 * Lay a flow out as one column: its phases stacked top to bottom, every
 * step on one centre line -- the shape a run group draws each member in.
 * @returns {{W: number, H: number, body: string}|null} null: nothing to draw
 */
function layoutColumn(flow, ctx) {
  var phases = [flow.setup].concat(flow.tests || [], [flow.teardown]).filter(Boolean);
  if (!phases.length) return null;
  var lanes = phases.map(function (p) { return { p: p, lay: sequence(p.steps, ctx, false) }; });
  // One centre line for every lane: as far right as the widest left part needs.
  var left = Math.max(100, max(lanes, function (l) { return l.lay.cx; }));
  var rightPart = Math.max(100, max(lanes, function (l) { return l.lay.w - l.lay.cx; }));
  var W = left + rightPart + 2 * LP;
  var cx = LP + left;

  var y = 0;
  lanes.forEach(function (l, i) {
    l.first = i === 0;
    l.last = i === lanes.length - 1;
    l.y = y;
    l.top = y + TH + (l.first ? PILL + VG : 6);
    l.bottom = l.top + l.lay.h;
    l.h = l.bottom - y + (l.last ? VG + PILL : 0) + LP;
    y += l.h + LG;
  });
  var H = y - LG;

  var out = '';
  lanes.forEach(function (l) {
    out += '<rect class="fv-lane" x="0" y="' + l.y + '" width="' + W + '" height="' + l.h + '" rx="10"/>' +
           '<text class="fv-lane-title" x="14" y="' + (l.y + 23) + '">' + esc(laneTitle(l.p).toUpperCase()) + '</text>';
  });
  lanes.forEach(function (l, i) {
    if (l.first) {
      out += '<g class="fv-pill"><rect x="' + (cx - 45) + '" y="' + (l.y + TH) + '" width="90" height="' + PILL + '" rx="15"/>' +
             '<text class="fv-title" x="' + cx + '" y="' + (l.y + TH + 20) + '">start</text></g>';
      out += l.lay.empty ? '' : ctx.arrow(cx, l.y + TH + PILL, cx, l.top, '', '');
    }
    out += l.lay.svg(cx - l.lay.cx, l.top);
    var done = lastKind(l.p) === 'loop' ? 'done' : '';
    if (l.last) {
      var ey = l.bottom + VG;
      out += ctx.arrow(cx, l.bottom, cx, ey, done, '');
      out += '<g class="fv-pill"><rect x="' + (cx - 45) + '" y="' + ey + '" width="90" height="' + PILL + '" rx="15"/>' +
             '<text class="fv-title" x="' + cx + '" y="' + (ey + 20) + '">end</text></g>';
    } else {
      out += ctx.arrow(cx, l.bottom, cx, lanes[i + 1].top, done, '');
    }
  });
  return { W: W, H: H, body: out };
}

var BAND = 46;       // a member's title band
var CHANNEL = 210;   // between two members: the links cross it, with their labels

/**
 * SVG markup of a run group: every member's flow as a column, side by side,
 * and a dashed arrow across the channel between them for every link -- a
 * step of one member that a gate of another waits for. Read top to bottom
 * like a sequence diagram.
 * @param {object[]} members [{id, target, variables, flow}]
 * @param {object[]} links   [{from: {member, node}, to: {member, node}, label}]
 * @returns {string}
 */
export function renderGroup(members, links) {
  var ctx = makeCtx(null);
  var placed = {};
  var x = 0;
  var H = 0;
  var out = '';
  (members || []).forEach(function (m) {
    ctx.pos = {};
    var lay = layoutColumn(m.flow || {}, ctx);
    var w = lay ? lay.W : 240;
    var vars = Object.keys(m.variables || {}).map(function (k) { return k + '=' + m.variables[k]; }).join('  ');
    out += '<g class="fv-member" data-member="' + esc(m.id) + '">' +
      '<text class="fv-member-title" x="' + (x + 2) + '" y="20">' + esc(m.id) + '</text>' +
      '<text class="fv-member-sub" x="' + (x + 2) + '" y="37">' +
        esc(clip(m.target + (vars ? '  \u00b7  ' + vars : ''), Math.max(20, Math.floor(w / 6.4)))) + '</text>';
    var at = {};
    if (lay) {
      out += '<g transform="translate(' + x + ',' + BAND + ')">' + lay.body + '</g>';
      Object.keys(ctx.pos).forEach(function (k) {
        var p = ctx.pos[k];
        at[k] = { x: p.x + x, y: p.y + BAND, w: p.w, h: p.h };
      });
      H = Math.max(H, BAND + lay.H);
    }
    placed[m.id] = at;
    out += '</g>';
    x += w + CHANNEL;
  });
  var W = Math.max(0, x - CHANNEL);

  // A link leaves its step on the side facing the other member and enters
  // the gate from that side; its label sits on the curve, in the channel.
  var drawn = 0;
  var labels = [];
  (links || []).forEach(function (link, i) {
    var a = (placed[link.from.member] || {})[link.from.node];
    var b = (placed[link.to.member] || {})[link.to.node];
    if (!a || !b) return;
    drawn++;
    var rightward = a.x + a.w / 2 < b.x + b.w / 2;
    var x1 = rightward ? a.x + a.w : a.x;
    var x2 = rightward ? b.x - 3 : b.x + b.w + 3;
    var y1 = a.y + a.h / 2;
    var y2 = b.y + b.h / 2;
    var dx = (x2 - x1) / 2;
    var d = 'M' + x1 + ',' + y1 + ' C' + (x1 + dx) + ',' + y1 + ' ' + (x2 - dx) + ',' + y2 + ' ' + x2 + ',' + y2;
    // The signal's last two name parts and the value; the tooltip has it all.
    var short = String(link.label || '').replace(/^\S*?([^.\s]+\.[^.\s]+)(\s*=)/, '$1$2');
    var lx = (x1 + x2) / 2;
    var ly = (y1 + y2) / 2 - 6;
    // Labels of links that cross the channel at the same height step apart.
    labels.forEach(function (o) { if (Math.abs(o.x - lx) < 60 && Math.abs(o.y - ly) < 14) ly = o.y + 14; });
    labels.push({ x: lx, y: ly });
    out += '<g class="fv-sync" data-link="' + i + '"><title>' + esc(link.from.member + ' \u2192 ' + link.to.member + ': ' + link.label) + '</title>' +
      '<path class="fv-sync-edge" d="' + d + '" marker-end="' + ctx.syncMarker + '"/>' +
      '<text class="fv-sync-label" x="' + lx + '" y="' + ly + '">' + esc(short) + '</text></g>';
  });

  return '<svg class="flow-view flow-group" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + H +
    '" width="' + W + '" height="' + H + '" role="img" aria-label="' +
    esc('Run group of ' + (members || []).map(function (m) { return m.id; }).join(', ') + ': ' + drawn +
        ' meeting point' + (drawn === 1 ? '' : 's')) + '">' +
    ctx.defs + out + '</svg>';
}

function lastKind(p) {
  var steps = p.steps || [];
  return steps.length ? steps[steps.length - 1].kind : '';
}
