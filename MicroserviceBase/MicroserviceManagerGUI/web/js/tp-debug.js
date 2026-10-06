/**
 * Debugging test-project runs in the project view (MM.tpDebug).
 *
 * - Breakpoints: lines of the project's files, kept per project in local
 *   storage (they outlive a run, like an editor's). A line of a flow file is
 *   the step written there: it snaps to the step's "id" line. The editor's
 *   gutter, the Diagram's step dots and the debug panel's source view all
 *   set them; a debugged run gets them at its start and every change after.
 * - Go to Definition: what the caret is on -- a cell of a Robot line, or a
 *   string of a flow file and its key -- for the bridge's /define.
 * - The debug panel of a debugged run (the Runs view): Continue, Step Over /
 *   Into / Out, Pause; the call stack; the variables of the selected frame;
 *   a console for ${variables}, keyword calls and, in Python, expressions;
 *   the source around the line the run is stopped at.
 *
 * The run's side: adapters/test_project/debugging.py (the bridge) and
 * flow_debug.py (the listener in the Robot process).
 */
(function () {
  'use strict';
  var MM = window.MicroserviceManager = window.MicroserviceManager || {};

  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }

  // ---- lines of a flow file and its steps ---------------------------------

  var ID_RE = /"id"\s*:\s*"((?:[^"\\]|\\.)*)"/;

  /** [{ id, line, first, last }]: each step's "id" line and the lines its object spans. */
  function anchors(text) {
    var lines = String(text || '').split(/\r?\n/);
    var edges = lines.length + 1;
    var out = [];
    lines.forEach(function (line, i) {
      if (/^\s*"edges"\s*:/.test(line)) edges = Math.min(edges, i + 1);
      var m = ID_RE.exec(line);
      if (!m || i + 1 >= edges) return;
      var first = i + 1;
      if (line.slice(0, m.index).indexOf('{') < 0) {
        for (var j = i - 1; j >= Math.max(0, i - 3); j--) {
          if (/^\s*\{\s*$/.test(lines[j])) { first = j + 1; break; }
          if (lines[j].trim()) break;
        }
      }
      var id;
      try { id = JSON.parse('"' + m[1] + '"'); } catch (e) { id = m[1]; }
      out.push({ id: id, line: i + 1, first: first, last: 0 });
    });
    out.forEach(function (a, k) {
      a.last = out[k + 1] ? out[k + 1].first - 1 : Math.min(edges - 1, lines.length);
    });
    return out;
  }
  function stepAt(list, line) {
    for (var i = 0; i < list.length; i++) if (line >= list[i].first && line <= list[i].last) return list[i];
    return null;
  }
  function lineOf(list, id) {
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i].line;
    return null;
  }
  function isFlow(path) { return /\.flow\.json$/i.test(path || ''); }

  // ---- breakpoints ------------------------------------------------------------

  var BP_KEY = 'mm_tp_breakpoints:';
  var bpListeners = [];

  function bpLoad(root) {
    try {
      var data = JSON.parse(localStorage.getItem(BP_KEY + root) || '{}');
      return data && typeof data === 'object' ? data : {};
    } catch (e) { return {}; }
  }
  function bpSave(root, all) {
    try { localStorage.setItem(BP_KEY + root, JSON.stringify(all)); } catch (e) { /* storage full or off */ }
  }

  var bp = {
    /** The breakpoint lines of one file, sorted. */
    lines: function (root, path) { return (bpLoad(root)[path] || []).slice().sort(function (a, b) { return a - b; }); },
    /** { path: [lines] } of the whole project. */
    all: function (root) { return bpLoad(root); },
    /** Set or remove the breakpoint of `line` (`text`: the file's text, to snap a flow line to its step). */
    toggle: function (root, path, line, text) {
      if (isFlow(path)) {
        var step = stepAt(anchors(text), line);
        if (!step) return bp.lines(root, path);
        line = step.line;
      }
      var all = bpLoad(root);
      var list = all[path] || [];
      var at = list.indexOf(line);
      if (at >= 0) list.splice(at, 1); else list.push(line);
      if (list.length) all[path] = list; else delete all[path];
      bpSave(root, all);
      bpListeners.forEach(function (fn) { try { fn(root, path); } catch (e) { /* a listener's problem */ } });
      return bp.lines(root, path);
    },
    clear: function (root) {
      var all = bpLoad(root);
      bpSave(root, {});
      Object.keys(all).forEach(function (path) { bpListeners.forEach(function (fn) { fn(root, path); }); });
    },
    /** fn(root, path) after a change. */
    onChange: function (fn) { bpListeners.push(fn); },
    /** The steps of a flow that have one (its own ids), from its text. */
    steps: function (root, path, text) {
      var list = anchors(text);
      return bp.lines(root, path).map(function (l) { var s = stepAt(list, l); return s && s.id; }).filter(Boolean);
    },
    /** The line of a step of a flow, to toggle it from the Diagram. */
    lineOfStep: function (text, id) { return lineOf(anchors(text), id); }
  };

  // ---- Go to Definition: what the caret is on --------------------------------------

  var SEP = /( {2,}|\t+|\s+\|\s+|^\|\s+|\s+\|$)/g;

  /** The Robot cell at column `col` of `line` (0-based): { text, start, end } or null. */
  function robotCellAt(line, col) {
    var cells = [], last = 0, m;
    SEP.lastIndex = 0;
    while ((m = SEP.exec(line))) {
      if (m.index > last) cells.push({ text: line.slice(last, m.index), start: last, end: m.index });
      last = m.index + m[0].length;
      if (!m[0].length) SEP.lastIndex++;
    }
    if (last < line.length) cells.push({ text: line.slice(last), start: last, end: line.length });
    var cell = cells.filter(function (c) { return col >= c.start && col <= c.end; })[0];
    if (!cell) return null;
    var text = cell.text.trim();
    if (!text || text.charAt(0) === '#' || text === '...' || /^[$@&%]\{[^}]*\}\s?=?$/.test(text)) return null;
    if (/^\*/.test(line.replace(/^\s+/, '')) || /^\[[^\]]+\]$/.test(text)) return null;
    return { text: text, start: cell.start, end: cell.end };
  }

  /** The JSON string at column `col` and the key it is the value of (null in an array). */
  function flowStringAt(line, col) {
    var re = /"((?:[^"\\]|\\.)*)"/g, m, found = null;
    while ((m = re.exec(line))) {
      var after = line.slice(m.index + m[0].length);
      if (/^\s*:/.test(after)) continue;
      if (col >= m.index && col <= m.index + m[0].length) {
        var key = /"([^"]+)"\s*:\s*$/.exec(line.slice(0, m.index));
        var text;
        try { text = JSON.parse(m[0]); } catch (e) { text = m[1]; }
        found = { text: text, key: key ? key[1] : null };
      }
    }
    return found;
  }

  /** What to look up at offset `pos` of `text` in file `path`: { name } or { file } (a path in it), or null. */
  function lookupAt(path, text, pos) {
    var start = text.lastIndexOf('\n', pos - 1) + 1;
    var end = text.indexOf('\n', pos);
    var line = text.slice(start, end < 0 ? text.length : end).replace(/\r$/, '');
    var col = pos - start;
    if (isFlow(path)) {
      var s = flowStringAt(line, col);
      if (!s || !s.text.trim()) return null;
      if (s.key === 'keyword') return { name: s.text };
      if (/\.(flow\.json|robot|resource|py|json|ya?ml)$/i.test(s.text)) return { file: s.text, name: s.text };
      return s.key === null ? { name: s.text } : null;
    }
    var cell = robotCellAt(line, col);
    if (!cell) return null;
    return { name: cell.text };
  }

  /** `rel` (as written in `fromPath`, a project file) as a project path, or null outside it. */
  function resolveRelative(fromPath, rel) {
    var parts = fromPath.split('/').slice(0, -1);
    String(rel).replace(/\\/g, '/').split('/').forEach(function (p) {
      if (p === '..') parts.pop(); else if (p && p !== '.') parts.push(p);
    });
    return parts.join('/');
  }

  // ---- source -----------------------------------------------------------------

  // One pass over the raw line: a string, a keyword or a comment -- each piece
  // escaped on its own, so no rule ever sees another's markup.
  var PY_TOKENS = /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(#.*$)|\b(def|class|return|if|elif|else|for|while|try|except|finally|with|as|import|from|in|not|and|or|is|None|True|False|pass|raise|yield|lambda|async|await|break|continue|global|nonlocal)\b/g;

  function pyHighlight(text) {
    return String(text).split('\n').map(function (line) {
      var out = '', last = 0, m;
      PY_TOKENS.lastIndex = 0;
      while ((m = PY_TOKENS.exec(line))) {
        out += esc(line.slice(last, m.index));
        var cls = m[1] ? 'rf-var' : m[2] ? 'rf-com' : 'rf-set';
        out += '<span class="' + cls + '">' + esc(m[0]) + '</span>';
        last = m.index + m[0].length;
        if (!m[0].length) PY_TOKENS.lastIndex++;
      }
      return out + esc(line.slice(last));
    }).join('\n');
  }

  function highlight(path, text) {
    var h = MM.tpHighlight || {};
    if (/\.py$/i.test(path || '')) return pyHighlight(text);
    if (/\.json$/i.test(path || '') && h.json) return h.json(text);
    if (h.robot) return h.robot(text);
    return esc(text);
  }

  // ---- the debug panel ------------------------------------------------------------------

  var FILTERS_KEY = 'mm_tp_debug_filters';
  function storedFilters() {
    try { return JSON.parse(localStorage.getItem(FILTERS_KEY) || '[]'); } catch (e) { return []; }
  }

  var REASONS = { breakpoint: 'a breakpoint', step: 'a step', pause: 'Pause', exception: 'a failure' };

  /**
   * The panel of one debugged run in `el`. host: { root, runId, state() -> the
   * status's `debug`, openFile(path, line), toast(title, text, kind) }.
   * Returns { update() } -- call it on every poll.
   */
  function panel(el, host) {
    var client = MM.testProjectClient;
    var p = { seq: -1, frame: 0, expanded: {}, children: {}, sources: {}, history: [], busy: false };

    el.innerHTML =
      '<div class="tpd-bar">' +
      '  <span class="tpd-buttons" role="toolbar" aria-label="Debug">' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-tpd="continue" title="Continue (F5)"><i class="bi bi-play-fill"></i></button>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-tpd="next" title="Step Over (F10): the next step at this level"><i class="bi bi-arrow-90deg-right"></i></button>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-tpd="stepIn" title="Step Into (F11): into the keyword, sub-flow or Python function"><i class="bi bi-arrow-down"></i></button>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-tpd="stepOut" title="Step Out (Shift+F11)"><i class="bi bi-arrow-up"></i></button>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-tpd="pause" title="Pause at the next step"><i class="bi bi-pause-fill"></i></button>' +
      '  </span>' +
      '  <span class="tpd-where" id="tpdWhere"></span>' +
      '  <label class="tpd-filter"><input type="checkbox" id="tpdFailed"> Stop when a keyword fails</label>' +
      '</div>' +
      '<div class="tpd-body">' +
      '  <div class="tpd-source"><div class="tpd-source-head" id="tpdSourceHead"></div><div class="tpd-code" id="tpdCode"></div></div>' +
      '  <div class="tpd-side">' +
      '    <section><h6>Call stack</h6><ol class="tpd-stack" id="tpdStack"></ol></section>' +
      '    <section><h6>Variables</h6><div class="tpd-vars" id="tpdVars"></div></section>' +
      '    <section><h6>Console</h6><div class="tpd-console" id="tpdConsole"></div>' +
      '      <input type="text" class="form-control form-control-sm tpd-input" id="tpdInput" spellcheck="false"' +
      '             placeholder="${var}, a keyword (cells: two spaces), or Python where stopped in Python" disabled></section>' +
      '  </div>' +
      '</div>';

    var failed = el.querySelector('#tpdFailed');
    failed.checked = storedFilters().indexOf('failed') >= 0;
    failed.addEventListener('change', function () {
      var filters = failed.checked ? ['failed'] : [];
      try { localStorage.setItem(FILTERS_KEY, JSON.stringify(filters)); } catch (e) { /* off */ }
      client.debug(host.root, host.runId, { filters: filters }).catch(function () { /* the run ended */ });
    });

    el.querySelectorAll('[data-tpd]').forEach(function (b) {
      b.addEventListener('click', function () { command(b.getAttribute('data-tpd')); });
    });

    function command(cmd) {
      var st = host.state() || {};
      if (cmd !== 'pause' && !st.stopped) return;
      if (cmd === 'pause' && st.stopped) return;
      client.debug(host.root, host.runId, { command: cmd }).catch(function (err) {
        host.toast('Debug', err.message || String(err), 'warning');
      });
      // Shown as running at once; the next poll says where it stopped.
      if (cmd !== 'pause') { st.stopped = null; render(st); }
    }

    // F5 / F10 / F11 / Shift+F11 while the panel is on screen.
    function onKey(e) {
      if (!document.body.contains(el)) { document.removeEventListener('keydown', onKey, true); return; }
      var map = { F5: 'continue', F10: 'next', F11: e.shiftKey ? 'stepOut' : 'stepIn' };
      var cmd = map[e.key];
      if (!cmd || e.ctrlKey || e.altKey) return;
      e.preventDefault();
      command(cmd);
    }
    document.addEventListener('keydown', onKey, true);

    var input = el.querySelector('#tpdInput');
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && input.value.trim()) {
        var expr = input.value;
        p.history.push(expr);
        input.value = '';
        evaluate(expr);
      }
    });

    function log(html) {
      var c = el.querySelector('#tpdConsole');
      c.insertAdjacentHTML('beforeend', html);
      c.scrollTop = c.scrollHeight;
    }

    function evaluate(expr) {
      log('<div class="tpd-in">&gt; ' + esc(expr) + '</div>');
      client.debug(host.root, host.runId, { expression: expr }).then(function (r) {
        if (!r.ok) { log('<div class="tpd-err">' + esc(r.error || 'No answer.') + '</div>'); return; }
        log('<div class="tpd-out">' + esc((r.body || {}).result) + '</div>');
      }).catch(function (err) { log('<div class="tpd-err">' + esc(err.message || err) + '</div>'); });
    }

    // ---- variables: scopes of the selected frame, expanded on demand

    function scopes(frame) {
      if (frame.python) return [{ name: 'Locals', ref: frame.ref }];
      return [{ name: 'Variables', ref: 1 }, { name: 'Arguments', ref: 2 }];
    }

    function varRow(name, value, type, ref, depth) {
      var key = String(ref);
      var open = ref && p.expanded[key];
      var row = '<div class="tpd-var" style="padding-left:' + (depth * 14) + 'px"' + (ref ? ' data-ref="' + ref + '"' : '') + '>' +
        (ref ? '<i class="bi bi-chevron-' + (open ? 'down' : 'right') + ' tpd-twisty"></i>' : '<span class="tpd-twisty"></span>') +
        '<span class="tpd-var-name">' + esc(name) + '</span>' +
        (value != null ? ' <span class="tpd-var-value" title="' + esc(type || '') + '">' + esc(value) + '</span>' : '') + '</div>';
      if (open) {
        var kids = p.children[key];
        row += kids ? kids.map(function (v) { return varRow(v.name, v.value, v.type, v.variablesReference, depth + 1); }).join('')
                    : '<div class="tpd-var tpd-muted" style="padding-left:' + ((depth + 1) * 14) + 'px">…</div>';
      }
      return row;
    }

    function renderVars(st) {
      var box = el.querySelector('#tpdVars');
      if (!st.stopped) { box.innerHTML = '<div class="tpd-muted">While the run is stopped.</div>'; return; }
      var frame = st.stopped.frames[p.frame] || st.stopped.frames[0];
      box.innerHTML = scopes(frame).map(function (s) { return varRow(s.name, null, '', s.ref, 0); }).join('');
      box.querySelectorAll('[data-ref]').forEach(function (row) {
        row.addEventListener('click', function () {
          var ref = row.getAttribute('data-ref');
          p.expanded[ref] = !p.expanded[ref];
          if (p.expanded[ref] && !p.children[ref]) {
            client.debug(host.root, host.runId, { ref: Number(ref) }).then(function (r) {
              p.children[ref] = r.ok ? (r.body || []) : [{ name: r.error || 'No answer.', value: '' }];
              renderVars(host.state() || {});
            });
          }
          renderVars(host.state() || {});
        });
      });
    }

    // ---- source around the selected frame's line, with its breakpoints

    function source(frame) {
      var head = el.querySelector('#tpdSourceHead');
      var code = el.querySelector('#tpdCode');
      if (!frame || !frame.line) {
        head.textContent = frame ? frame.name : '';
        code.innerHTML = '<div class="tpd-muted">' + (frame ? 'No source line for this frame.' : 'Running…') + '</div>';
        return;
      }
      var label = frame.path || frame.abs || '';
      head.innerHTML = '<code>' + esc(label) + ':' + frame.line + '</code>' +
        (frame.path ? ' <a href="#" id="tpdOpen">Open in the editor</a>' : ' <span class="tpd-muted">(outside the project, read-only)</span>');
      var open = head.querySelector('#tpdOpen');
      if (open) open.addEventListener('click', function (e) { e.preventDefault(); host.openFile(frame.path, frame.line); });
      var got = frame.path
        ? (p.sources[frame.path] || (p.sources[frame.path] = client.file(host.root, frame.path).then(function (r) { return { text: r.content, first: 1 }; })))
        : Promise.resolve(frame.snippet ? { text: frame.snippet.lines.join('\n'), first: frame.snippet.first } : null);
      got.then(function (src) {
        if (!src) { code.innerHTML = '<div class="tpd-muted">The file cannot be shown.</div>'; return; }
        var lines = highlight(frame.path || frame.abs, src.text).replace(/\n$/, '').split('\n');
        var marks = frame.path ? bp.lines(host.root, frame.path) : [];
        code.innerHTML = lines.map(function (html, i) {
          var n = src.first + i;
          return '<div class="tpd-line' + (n === frame.line ? ' tpd-current' : '') + '" data-line="' + n + '">' +
            '<span class="tpd-ln' + (marks.indexOf(n) >= 0 ? ' tpd-bp' : '') + '"' +
            (frame.path ? ' title="Set or remove a breakpoint"' : '') + '>' + n + '</span>' +
            '<span class="tpd-text">' + (html || ' ') + '</span></div>';
        }).join('');
        if (frame.path) {
          code.querySelectorAll('.tpd-ln').forEach(function (ln) {
            ln.addEventListener('click', function () {
              bp.toggle(host.root, frame.path, Number(ln.parentNode.getAttribute('data-line')), src.text);
              source(frame);
            });
          });
        }
        var cur = code.querySelector('.tpd-current');
        if (cur) code.scrollTop = Math.max(0, cur.offsetTop - code.clientHeight / 3);
      }).catch(function () { code.innerHTML = '<div class="tpd-muted">The file cannot be read.</div>'; });
    }

    function render(st) {
      var stopped = st && st.stopped;
      el.classList.toggle('tpd-stopped', !!stopped);
      el.querySelectorAll('[data-tpd]').forEach(function (b) {
        b.disabled = b.getAttribute('data-tpd') === 'pause' ? !!stopped || !st.connected : !stopped;
      });
      input.disabled = !stopped;
      var where = el.querySelector('#tpdWhere');
      if (!st.connected && !st.ended) where.textContent = 'Starting…';
      else if (stopped) {
        var top = stopped.frames[0] || {};
        where.innerHTML = '<span class="tpd-paused">Paused</span> on ' + esc(REASONS[stopped.reason] || stopped.reason) +
          (stopped.description ? ': ' + esc(stopped.description) : '') +
          (top.name ? ' — <strong>' + esc(top.name) + '</strong>' : '');
      } else where.textContent = st.ended ? 'The run ended.' : 'Running…';

      var stack = el.querySelector('#tpdStack');
      var frames = stopped ? stopped.frames : [];
      if (p.frame >= frames.length) p.frame = 0;
      stack.innerHTML = frames.map(function (f, i) {
        return '<li class="' + (i === p.frame ? 'active' : '') + (f.python ? ' tpd-py' : '') + '" data-frame="' + i + '">' +
          '<span class="tpd-frame-name">' + esc(f.name) + '</span>' +
          '<span class="tpd-frame-where">' + esc(f.path || (f.abs ? f.abs.split(/[\\/]/).pop() : '')) + (f.line ? ':' + f.line : '') + '</span></li>';
      }).join('') || '<li class="tpd-muted">—</li>';
      stack.querySelectorAll('[data-frame]').forEach(function (li) {
        li.addEventListener('click', function () { p.frame = Number(li.getAttribute('data-frame')); render(host.state() || {}); });
      });
      source(frames[p.frame]);
      renderVars(st);
    }

    return {
      update: function () {
        var st = host.state() || {};
        if (st.seq === p.seq) return;
        // A new stop: its own variables, the top frame, the files as they are now.
        if (st.stopped) { p.frame = 0; p.expanded = {}; p.children = {}; }
        p.seq = st.seq;
        render(st);
      },
      /** The breakpoints of a file changed (the editor, the Diagram): show them. */
      refresh: function () { render(host.state() || {}); }
    };
  }

  MM.tpDebug = {
    anchors: anchors,
    stepAt: stepAt,
    lineOf: lineOf,
    isFlow: isFlow,
    breakpoints: bp,
    robotCellAt: robotCellAt,
    flowStringAt: flowStringAt,
    lookupAt: lookupAt,
    resolveRelative: resolveRelative,
    highlight: highlight,
    storedFilters: storedFilters,
    panel: panel
  };
})();
