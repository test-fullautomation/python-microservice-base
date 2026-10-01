// flow-view: a run's live position on a drawn diagram. The host (the Runs
// view) pushes the same flow again with `live` -- where each process is,
// from the runner's position file -- and only these marks change; the
// diagram itself is not drawn again.
//
//   position = { node, stack, last: { node, status, time }, counts: { id: { pass, fail } },
//                step, trail: [[step, node], ...], done }
//
//   the node a process is in       .fv-now (pulses), its loops / tries .fv-on-path
//   a step that failed just now    .fv-just-failed, for FAILED_FOR_S
//   every step that ran            a small count, ✓ passes and ✗ failures
//   the steps since the last push  replay(): a fading tail in their order
//                                  (.fv-trail), or the mark hopping through
//                                  them (.fv-hop) -- the view's `motion`
//
// No layout here: the marks sit on the nodes flow.js drew ([data-node]).

var FAILED_FOR_S = 8;
var MARKS = ['fv-now', 'fv-on-path', 'fv-just-failed', 'fv-now-recovery'];
// Frames of loops and tries hold other steps: their counts say little.
var COUNTED = { keyword: 1, gate: 1, sleep: 1, decision: 1, flow: 1 };

function kindOf(g) {
  var m = /(?:^|\s)fv-(keyword|gate|sleep|decision|loop|try)(?:\s|$)/.exec(g.getAttribute('class') || '');
  return m ? m[1] : '';
}

function shape(g) {
  return g.querySelector('rect, polygon');
}

function badge(g, count) {
  var text = g.querySelector('text.fv-count');
  var label = count ? ('✓' + count.pass + (count.fail ? '  ✗' + count.fail : '')) : '';
  if (!label) { if (text) text.remove(); return; }
  if (!text) {
    var box = shape(g);
    if (!box) return;
    var b = box.getBBox();
    text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('class', 'fv-count');
    text.setAttribute('x', String(b.x + b.width - 6));
    text.setAttribute('y', String(b.y + 12));
    g.appendChild(text);
  }
  if (text.textContent !== label) text.textContent = label;
  text.classList.toggle('fv-count-fail', !!count.fail);
}

/**
 * Mark `position` on the nodes under `scope` (the svg of a flow, or one
 * member's column). Returns the element of the node the process is in, if any.
 */
export function mark(scope, position) {
  scope.querySelectorAll('.' + MARKS.join(', .')).forEach(function (g) {
    MARKS.forEach(function (c) { g.classList.remove(c); });
  });
  var nodes = {};
  scope.querySelectorAll('[data-node]').forEach(function (g) { nodes[g.getAttribute('data-node')] = g; });
  var counts = (position && position.counts) || {};
  Object.keys(nodes).forEach(function (id) {
    if (COUNTED[kindOf(nodes[id])]) badge(nodes[id], counts[id]);
  });
  if (!position) return null;
  var stack = position.done ? [] : (position.stack || (position.node ? [position.node] : []));
  // The deepest node that is drawn: inside a closed sub-flow, its call box.
  var deepest = -1;
  stack.forEach(function (id, i) { if (nodes[id]) deepest = i; });
  stack.slice(0, deepest).forEach(function (id) { if (nodes[id]) nodes[id].classList.add('fv-on-path'); });
  var now = deepest >= 0 ? nodes[stack[deepest]] : null;
  if (now) {
    now.classList.add('fv-now');
    if (now.classList.contains('fv-in-recovery')) now.classList.add('fv-now-recovery');
  }
  var last = position.last;
  // The runner and this view share the machine's clock.
  var left = last ? FAILED_FOR_S - (Date.now() / 1000 - last.time) : 0;
  if (last && last.status === 'FAIL' && nodes[last.node] && left > 0) {
    var failed = nodes[last.node];
    failed.classList.add('fv-just-failed');
    setTimeout(function () { failed.classList.remove('fv-just-failed'); }, left * 1000);
  }
  return now;
}

/** The part of the document a node takes, for the host to keep it in view. */
export function extent(g) {
  var r = (shape(g) || g).getBoundingClientRect();
  var y = window.scrollY || 0;
  return { top: Math.round(r.top + y), bottom: Math.round(r.bottom + y) };
}

/**
 * `zoom`: 'fit' (default) scales the drawing to the frame's width;
 * 'natural' draws it at its own size, a number (0.75) at that share of it,
 * and the frame scrolls sideways. Then the nodes a run is in are kept in
 * view sideways here (the host keeps them in view up and down).
 */
export function zoom(el, mode, nodes) {
  var scale = mode === 'natural' ? 1 : (typeof mode === 'number' && mode > 0 ? mode : 0);
  el.classList.toggle('fv-natural', scale > 0);
  el.querySelectorAll('svg.flow-view').forEach(function (svg) {
    var w = Number(svg.getAttribute('width')) || 0;
    svg.style.width = scale && w ? Math.round(w * scale) + 'px' : '';
  });
  var scroller = el.querySelector('.fv-scroll');
  if (!scale || !scroller || !nodes || !nodes.length) return;
  var box = scroller.getBoundingClientRect();
  var r = (shape(nodes[0]) || nodes[0]).getBoundingClientRect();
  var margin = 24;
  if (r.left < box.left + margin) scroller.scrollLeft -= box.left + margin - r.left;
  else if (r.right > box.right - margin) scroller.scrollLeft += r.right - (box.right - margin);
}

// ---- replay: what happened between two pushes -------------------------------

var REPLAY_MS = 600;   // a replay ends well before the next push (about 1 s)
var STEP_MS = 90;      // per step, when there are few
var REPLAY_MAX = 8;    // the latest steps only; older ones are history

/**
 * End a replay: its marks go at once. `restore`: give the running mark back
 * to the node a hop took it from -- not when a new push has just marked
 * the nodes afresh.
 */
function settle(memo, restore) {
  (memo.timers || []).forEach(clearTimeout);
  memo.timers = [];
  (memo.lit || []).forEach(function (g) { g.classList.remove('fv-trail', 'fv-hop'); });
  memo.lit = [];
  if (memo.held && restore) memo.held.classList.add('fv-now');
  memo.held = null;
}

/**
 * Replay the steps `position` entered since the last call with the same
 * `memo` (per process: one memo object each, kept by the view), then leave
 * the marks mark() set. `motion`: 'tail' (default) -- each step flashes and
 * fades, in order; 'hop' -- the running mark jumps through them before it
 * settles; 'off' -- nothing. The first call only remembers where the run
 * is: a replay is for what changed while watching.
 */
export function replay(scope, position, memo, motion, now) {
  settle(memo, false);
  var seen = memo.step;
  memo.step = position ? position.step || 0 : 0;
  if (!position || position.done || seen == null || motion === 'off') return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var trail = (position.trail || []).filter(function (t) { return t[0] > seen; });
  // The last entered is where the run is: mark() shows it already.
  if (trail.length && trail[trail.length - 1][1] === position.node) trail.pop();
  trail = trail.slice(-REPLAY_MAX);
  if (!trail.length) return;
  var nodes = {};
  scope.querySelectorAll('[data-node]').forEach(function (g) { nodes[g.getAttribute('data-node')] = g; });
  var gap = Math.min(STEP_MS, Math.floor(REPLAY_MS / (trail.length + 1)));
  var hop = motion === 'hop';
  if (hop && now) { now.classList.remove('fv-now'); memo.held = now; }
  trail.forEach(function (t, i) {
    var g = nodes[t[1]];
    if (!g) return;
    memo.timers.push(setTimeout(function () {
      if (hop) {
        memo.lit.forEach(function (x) { x.classList.remove('fv-hop'); });
        g.classList.add('fv-hop');
      } else {
        g.classList.remove('fv-trail');
        void g.getBoundingClientRect();    // restart the fade on a node lit again
        g.classList.add('fv-trail');
      }
      memo.lit.push(g);
    }, i * gap));
  });
  memo.timers.push(setTimeout(function () {
    if (hop) settle(memo, true);
    // tail: each flash fades out by itself (CSS); clear the classes after it.
    else memo.timers.push(setTimeout(function () { settle(memo, true); }, 900));
  }, trail.length * gap));
}
