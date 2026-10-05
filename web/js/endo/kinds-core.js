/**
 * @fileoverview Bench Endoskeleton core tile kinds (contract v1):
 * text, live-status, command-form, table, log, run-status.
 *
 * A kind is { render(el, tile, ctx) } returning an instance
 * { suspend(), resume(), destroy(), refresh? }. Kinds only reach services
 * through ctx (see host.js), so they never gain more access than the
 * component that placed the tile. After suspend() nothing runs (R5).
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};
  var kinds = MM.endo.kinds = MM.endo.kinds || {};

  // ---------------------------------------------------------------- helpers

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /** Read a dotted path such as "a.b[0].c" from protojson (camelCase too). */
  function getPath(obj, path) {
    if (!path) return obj;
    var parts = String(path).replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean);
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      var k = parts[i];
      if (k in Object(cur)) { cur = cur[k]; continue; }
      // protojson turns interval_ms into intervalMs
      var camel = k.replace(/_([a-z])/g, function (_, c) { return c.toUpperCase(); });
      cur = cur[camel];
    }
    return cur;
  }

  function parseMs(s) {
    var m = /^(\d+)(ms|s|m)$/.exec(String(s || ''));
    if (!m) return 0;
    return Number(m[1]) * (m[2] === 'ms' ? 1 : m[2] === 's' ? 1000 : 60000);
  }

  function fmt(v, digits, unit) {
    if (v === undefined || v === null || v === '') return '—';
    var s;
    if (typeof v === 'number') s = digits != null ? v.toFixed(digits) : String(v);
    else if (typeof v === 'object') s = JSON.stringify(v);
    else s = String(v);
    return unit ? s + ' ' + unit : s;
  }

  var runningTimers = 0;   // pollers with a live interval (R5: 0 while everything is suspended)

  /** Run fn now and every ms (0 = once); never overlaps; stops cleanly. */
  function poller(ms, fn) {
    var timer = null, running = false, busy = false;
    function tick() {
      if (!running || busy) return;
      busy = true;
      Promise.resolve().then(fn).catch(function () { /* the kind shows its own error */ })
        .then(function () { busy = false; });
    }
    return {
      start: function () {
        if (running) return;
        running = true;
        tick();
        if (ms > 0) { timer = setInterval(tick, ms); runningTimers++; }
      },
      stop: function () {
        running = false;
        if (timer) { clearInterval(timer); timer = null; runningTimers--; }
      },
      now: function () { var was = running; running = true; tick(); running = was; }
    };
  }
  poller.running = function () { return runningTimers; };

  function errorLine(err) {
    return '<div class="endo-error" role="status">' + esc((err && err.message) || err) + '</div>';
  }

  /** A kind whose content is (re)loaded by one function, optionally on a timer. */
  function polled(tile, load) {
    var p = poller(parseMs(tile.refresh), load);
    p.start();
    return {
      suspend: p.stop,
      resume: p.start,
      destroy: p.stop,
      refresh: p.now
    };
  }

  MM.endo.util = { esc: esc, getPath: getPath, parseMs: parseMs, fmt: fmt, poller: poller };

  // ------------------------------------------------------------------ text

  kinds['text'] = {
    render: function (el, tile, ctx) {
      if (!tile.rpc) {
        el.innerHTML = '<p class="endo-text">' + esc(tile.text) + '</p>';
        return { suspend: function () {}, resume: function () {}, destroy: function () {} };
      }
      el.innerHTML = '<p class="endo-text endo-muted">Loading…</p>';
      return polled(tile, function () {
        return ctx.call(tile.rpc, tile.args).then(function (d) {
          el.innerHTML = '<p class="endo-text">' + esc(fmt(getPath(d.result, tile.path))) + '</p>';
        }, function (err) { el.innerHTML = errorLine(err); });
      });
    }
  };

  // ----------------------------------------------------------- live-status

  kinds['live-status'] = {
    render: function (el, tile, ctx) {
      var fields = tile.fields || [];
      el.innerHTML = fields.map(function (f, i) {
        return '<div class="endo-kv"><span class="k">' + esc(f.label) + '</span>' +
               '<span class="v" data-f="' + i + '">' + (f.signal ? '—' : '…') + '</span></div>';
      }).join('') +
      '<div class="endo-foot" hidden></div>';

      // One call per distinct rpc + args, shared by the fields that read it.
      var groups = {};
      fields.forEach(function (f, i) {
        if (!f.rpc) return;
        var key = f.rpc + ' ' + JSON.stringify(f.args || {});
        (groups[key] = groups[key] || { rpc: f.rpc, args: f.args, idx: [] }).idx.push(i);
      });
      var keys = Object.keys(groups);
      var foot = el.querySelector('.endo-foot');

      function show(i, value) {
        var f = fields[i];
        var cell = el.querySelector('[data-f="' + i + '"]');
        if (!cell) return;
        var high = typeof value === 'number' && f.warnAbove != null && value > f.warnAbove;
        var low = typeof value === 'number' && f.warnBelow != null && value < f.warnBelow;
        cell.innerHTML = esc(fmt(value, f.digits, f.unit)) +
          (high ? ' <span class="endo-chip warn">high</span>' : low ? ' <span class="endo-chip warn">low</span>' : '');
      }

      // Signal fields: one subscription for the tile, held only while shown (R5).
      var sigNames = [];
      var sigIdx = {};
      fields.forEach(function (f, i) {
        if (!f.signal) return;
        if (!sigIdx[f.signal]) { sigIdx[f.signal] = []; sigNames.push(f.signal); }
        sigIdx[f.signal].push(i);
      });
      var unsub = null;
      function onValue(name, value) {
        (sigIdx[name] || []).forEach(function (i) { show(i, value); });
      }
      onValue.onStatus = function (s) {
        if (s.state === 'live') return;
        (sigIdx[s.name] || []).forEach(function (i) {
          var cell = el.querySelector('[data-f="' + i + '"]');
          if (!cell) return;
          var label = s.state === 'unknown' ? 'unknown signal' : s.state === 'retrying' ? 'reconnecting' : 'unavailable';
          cell.innerHTML = '<span class="endo-chip warn" title="' + esc(s.name + ': ' + (s.message || s.state)) + '">' + label + '</span>';
        });
      };
      var signals = {
        start: function () {
          if (unsub || !sigNames.length) return;
          try { unsub = ctx.signals.subscribe(sigNames, onValue); }
          catch (e) {
            sigNames.forEach(function (n) { onValue.onStatus({ name: n, state: 'error', message: e.message }); });
          }
        },
        stop: function () { if (unsub) { unsub(); unsub = null; } }
      };
      signals.start();

      if (!keys.length) {
        return { suspend: signals.stop, resume: signals.start, destroy: signals.stop };
      }
      var inst = polled(tile, function () {
        return Promise.all(keys.map(function (key) {
          var g = groups[key];
          return ctx.call(g.rpc, g.args).then(function (d) {
            g.idx.forEach(function (i) { show(i, getPath(d.result, fields[i].path)); });
            return null;
          }, function (err) {
            g.idx.forEach(function (i) {
              var cell = el.querySelector('[data-f="' + i + '"]');
              if (cell) cell.innerHTML = '<span class="endo-bad">error</span>';
            });
            return err;
          });
        })).then(function (errs) {
          var first = errs.filter(Boolean)[0];
          foot.hidden = false;
          foot.innerHTML = first ? errorLine(first)
                                 : '<span class="endo-muted">updated ' + new Date().toLocaleTimeString() + '</span>';
        });
      });
      return {
        suspend: function () { inst.suspend(); signals.stop(); },
        resume: function () { inst.resume(); signals.start(); },
        destroy: function () { inst.destroy(); signals.stop(); },
        refresh: inst.refresh
      };
    }
  };

  // ---------------------------------------------------------- command-form

  function formFromManifest(form) {
    return Object.keys(form || {}).map(function (name) {
      var spec = form[name];
      if (typeof spec === 'string') spec = { type: spec };
      return { name: name, type: spec.type, label: spec.label || name, min: spec.min, max: spec.max, def: spec['default'],
               options: spec.options, optionsFrom: spec.optionsFrom, current: spec.current,
               reloadAfter: spec.reloadAfter };
    });
  }

  // ---- dropdown fields: a fixed list (options) or one read from the service (optionsFrom)

  var MAX_OPTIONS = 256;

  function optionItem(o) {
    return (o && typeof o === 'object') ? { value: o.value, label: o.label != null ? o.label : String(o.value) }
                                        : { value: o, label: String(o) };
  }

  function optionTags(items, selected) {
    return items.map(function (o) {
      var v = String(o.value);
      return '<option value="' + esc(v) + '"' + (selected != null && String(selected) === v ? ' selected' : '') + '>' +
             esc(o.label) + '</option>';
    }).join('');
  }

  /** args with { "$from": { rpc, args, path } } values read from those RPCs first. */
  function resolveArgs(ctx, args) {
    var keys = Object.keys(args || {});
    return Promise.all(keys.map(function (k) {
      var v = args[k];
      if (!(v && typeof v === 'object' && v.$from)) return v;
      return readValue(ctx, v.$from);
    })).then(function (vals) {
      var out = {};
      keys.forEach(function (k, i) { out[k] = vals[i]; });
      return out;
    });
  }

  function readValue(ctx, spec) {
    return resolveArgs(ctx, spec.args).then(function (args) {
      return ctx.call(spec.rpc, args);
    }).then(function (d) { return getPath(d.result, spec.path); });
  }

  /** The choices of an optionsFrom field: [{ value, label }]. */
  function readOptions(ctx, from) {
    if (from.rpc) {
      return resolveArgs(ctx, from.args).then(function (args) { return ctx.call(from.rpc, args); }).then(function (d) {
        var list = getPath(d.result, from.path);
        if (!Array.isArray(list)) throw new Error(from.rpc + (from.path ? ' ' + from.path : '') + ' is not a list');
        return list.slice(0, MAX_OPTIONS).map(function (it) {
          if (it === null || typeof it !== 'object') return { value: it, label: String(it) };
          var v = getPath(it, from.value || 'value');
          var l = getPath(it, from.label || 'label');
          return { value: v, label: l != null ? String(l) : String(v) };
        });
      });
    }
    // A range of indexes from a count RPC, each named by an optional name RPC.
    return readValue(ctx, from.count).then(function (count) {
      var n = Number(count) || 0;
      var first = from.first || 0;
      var last = from.inclusive ? n : first + n - 1;
      var idx = [];
      for (var i = first; i <= last && idx.length < MAX_OPTIONS; i++) idx.push(i);
      if (!from.name) return idx.map(function (i) { return { value: i, label: String(i) }; });
      // One at a time: a device behind the service may not take parallel requests.
      var items = [];
      return idx.reduce(function (p, i) {
        return p.then(function () {
          return resolveArgs(ctx, from.name.args).then(function (base) {
            var args = Object.assign({}, base);
            args[from.name.arg] = i;
            return ctx.call(from.name.rpc, args);
          }).then(function (d) {
            var label = getPath(d.result, from.name.path);
            items.push({ value: i, label: label != null && label !== '' ? i + ' · ' + label : String(i) });
          }, function () { items.push({ value: i, label: String(i) }); });
        });
      }, Promise.resolve()).then(function () { return items; });
    });
  }

  /**
   * Fill the dropdowns of a rendered form that read their choices (or
   * their current value) from the service. Called once when the form is
   * shown and by each dropdown's reload button.
   */
  function loadOptions(form, fields, ctx, only) {
    return Promise.all(fields.map(function (f) {
      if (!(f.optionsFrom || f.current) || (only && only !== f.name)) return null;
      var sel = form.querySelector('select[data-name="' + f.name + '"]');
      if (!sel) return null;
      var keep = sel.value;
      var listP = f.optionsFrom
        ? (sel.disabled = true, sel.innerHTML = '<option value="">Loading…</option>', readOptions(ctx, f.optionsFrom))
        : Promise.resolve(null);
      var currentP = f.current ? readValue(ctx, f.current).catch(function () { return undefined; }) : Promise.resolve(undefined);
      return Promise.all([listP, currentP]).then(function (r) {
        var items = r[0], current = r[1];
        if (items) {
          var pick = current != null ? current : (keep !== '' ? keep : f.def);
          sel.innerHTML = items.length ? optionTags(items, pick) : '<option value="">(none)</option>';
        } else if (current != null) {
          sel.value = String(current);
        }
        sel.title = '';
      }, function (err) {
        sel.innerHTML = '<option value="">could not load</option>';
        sel.title = (err && err.message) || String(err);
      }).then(function () { sel.disabled = false; });
    }));
  }

  function formFromReflection(inputFields) {
    return (inputFields || []).map(function (f) {
      var t = String(f.type || '').toLowerCase();
      var repeated = f.label === 'repeated';
      var type = repeated ? 'json'
        : t === 'bool' ? 'bool'
        : /^(float|double)$/.test(t) ? 'float'
        : /^(u?int|s?fixed|sint)/.test(t) ? 'int'
        : /^(string|bytes|enum)$/.test(t) ? 'string'
        : 'json';
      return { name: f.name, type: type, label: f.name };
    });
  }

  function fieldHtml(id, f) {
    var lbl = '<label class="endo-field-label" for="' + id + '">' + esc(f.label) +
              '<span class="endo-type">' + esc(f.type) + '</span></label>';
    var common = ' id="' + id + '" data-name="' + esc(f.name) + '" data-type="' + esc(f.type) + '"';
    if (f.options || f.optionsFrom) {
      var initial = f.options ? optionTags(f.options.slice(0, MAX_OPTIONS).map(optionItem), f.def)
                              : '<option value="">Loading…</option>';
      return '<div class="endo-field">' + lbl + '<div class="endo-select-row">' +
             '<select class="form-select form-select-sm"' + common + '>' + initial + '</select>' +
             (f.optionsFrom || f.current
               ? '<button type="button" class="btn btn-sm btn-outline-secondary endo-reload" data-reload="' + esc(f.name) +
                 '" title="Read the choices from the service again" aria-label="Reload ' + esc(f.label) + '">↻</button>'
               : '') +
             '</div></div>';
    }
    if (f.type === 'bool') {
      return '<div class="form-check form-switch endo-field"><input class="form-check-input" type="checkbox"' + common +
             (f.def ? ' checked' : '') + '><label class="form-check-label" for="' + id + '">' + esc(f.label) + '</label></div>';
    }
    if (f.type === 'json') {
      return '<div class="endo-field">' + lbl + '<textarea class="form-control form-control-sm" rows="2" placeholder="JSON"' +
             common + '>' + esc(f.def != null ? JSON.stringify(f.def) : '') + '</textarea></div>';
    }
    var num = f.type === 'int' || f.type === 'float';
    return '<div class="endo-field">' + lbl + '<input class="form-control form-control-sm" type="' + (num ? 'number' : 'text') + '"' +
           (num ? ' step="' + (f.type === 'int' ? '1' : 'any') + '"' : '') +
           (f.min != null ? ' min="' + f.min + '"' : '') + (f.max != null ? ' max="' + f.max + '"' : '') +
           (f.def != null ? ' value="' + esc(f.def) + '"' : '') + common + '></div>';
  }

  function collect(form) {
    var args = {};
    form.querySelectorAll('[data-name]').forEach(function (inp) {
      var name = inp.getAttribute('data-name');
      var type = inp.getAttribute('data-type');
      if (inp.tagName === 'SELECT' && type === 'bool') {
        if (inp.value !== '') args[name] = inp.value === 'true';
        return;
      }
      if (type === 'bool') { args[name] = !!inp.checked; return; }
      var v = inp.value;
      if (v === '') return;
      if (type === 'int' || type === 'float') {
        var n = Number(v);
        if (!isFinite(n)) throw new Error(name + ' must be a number');
        if (inp.min !== '' && n < Number(inp.min)) throw new Error(name + ' must be at least ' + inp.min);
        if (inp.max !== '' && n > Number(inp.max)) throw new Error(name + ' must be at most ' + inp.max);
        args[name] = type === 'int' ? Math.trunc(n) : n;
        return;
      }
      if (type === 'json') {
        try { args[name] = JSON.parse(v); } catch (e) { throw new Error(name + ' is not valid JSON: ' + e.message); }
        return;
      }
      args[name] = v;
    });
    return args;
  }

  // Ribbon commands (bench.js) build the same forms.
  MM.endo.util.form = { fromManifest: formFromManifest, fieldHtml: fieldHtml, collect: collect,
                        loadOptions: loadOptions, wireReload: wireReload };

  /**
   * The reload buttons of a form's dropdowns, and the automatic reload of a
   * dropdown after a call it depends on (reloadAfter: e.g. the sub-device
   * types after SetDeviceType, from this tile or another one of the
   * component). Returns off() for the automatic part.
   */
  function wireReload(form, fields, ctx) {
    form.querySelectorAll('[data-reload]').forEach(function (b) {
      b.addEventListener('click', function () { loadOptions(form, fields, ctx, b.getAttribute('data-reload')); });
    });
    var linked = fields.filter(function (f) { return f.reloadAfter && f.reloadAfter.length && (f.optionsFrom || f.current); });
    if (!linked.length || !ctx || typeof ctx.onCall !== 'function') return function () {};
    return ctx.onCall(function (method) {
      linked.forEach(function (f) {
        if (f.reloadAfter.indexOf(method) >= 0) loadOptions(form, fields, ctx, f.name);
      });
    });
  }

  var formSeq = 0;
  kinds['command-form'] = {
    render: function (el, tile, ctx) {
      var id = 'endoForm' + (++formSeq);
      el.innerHTML = '<form class="endo-form" id="' + id + '" novalidate><div class="endo-fields">' +
                     '<span class="endo-muted">Reading the method…</span></div>' +
                     '<div class="endo-actions"><button type="submit" class="btn btn-sm btn-primary" disabled>' +
                     esc(tile.submitLabel || 'Run') + '</button></div>' +
                     '<div class="endo-result" hidden></div></form>';
      var form = el.querySelector('form');
      var box = form.querySelector('.endo-fields');
      var btn = form.querySelector('button');
      var out = form.querySelector('.endo-result');

      var fieldsP = tile.form
        ? Promise.resolve(formFromManifest(tile.form))
        : ctx.describe(tile.call).then(function (m) {
            if (m.client_streaming) throw new Error(tile.call + ' is client-streaming; a form cannot call it');
            return formFromReflection(m.input_fields);
          });

      var unlink = function () {};
      var gone = false;
      fieldsP.then(function (fields) {
        if (gone) return;
        box.innerHTML = fields.length
          ? fields.map(function (f, i) { return fieldHtml(id + '_' + i, f); }).join('')
          : '<span class="endo-muted">No input needed.</span>';
        btn.disabled = false;
        unlink = wireReload(form, fields, ctx);
        loadOptions(form, fields, ctx);
      }, function (err) { box.innerHTML = errorLine(err); });

      function run() {
        var args;
        try { args = Object.assign({}, tile.args || {}, collect(form)); }
        catch (e) { out.hidden = false; out.className = 'endo-result bad'; out.textContent = e.message; return; }
        btn.disabled = true;
        out.hidden = false;
        out.className = 'endo-result';
        out.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running…';
        var t0 = performance.now();
        ctx.call(tile.call, args).then(function (d) {
          var ms = Math.round(performance.now() - t0);
          var payload = d.streaming ? (d.events || []) : d.result;
          var shown = tile.resultPath && !d.streaming ? getPath(payload, tile.resultPath) : payload;
          out.className = 'endo-result ok';
          out.innerHTML = '<div class="endo-result-meta">Done · ' + ms + ' ms' +
            (d.streaming ? ' · ' + (d.events || []).length + ' event(s)' : '') + '</div>' +
            (typeof shown === 'string' ? '<div class="endo-result-value">' + esc(shown) + '</div>'
                                       : '<pre class="endo-pre">' + esc(JSON.stringify(shown, null, 2)) + '</pre>');
        }, function (err) {
          out.className = 'endo-result bad';
          out.textContent = err.message || String(err);
        }).then(function () { btn.disabled = false; });
      }

      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (tile.confirm) ctx.confirm(tile.confirm).then(function (ok) { if (ok) run(); });
        else run();
      });
      // A form is idle until submitted: nothing to suspend.
      return { suspend: function () {}, resume: function () {},
               destroy: function () { gone = true; unlink(); } };
    }
  };

  // ----------------------------------------------------------------- table

  /**
   * Rows are objects read through each column's path, or (static rows)
   * arrays read by position when a column has no path.
   */
  function drawTable(el, cols, rows) {
    if (!rows.length) { el.innerHTML = '<span class="endo-muted">No rows.</span>'; return; }
    var head = cols.length ? cols : (Array.isArray(rows[0]) ? rows[0].map(function () { return { label: '' }; }) : []);
    el.innerHTML = '<div class="endo-table-wrap"><table class="endo-table">' +
      (head.some(function (c) { return c.label; })
        ? '<thead><tr>' + head.map(function (c) { return '<th>' + esc(c.label) + '</th>'; }).join('') + '</tr></thead>' : '') +
      '<tbody>' +
      rows.map(function (r) {
        return '<tr>' + head.map(function (c, i) {
          var v = c.path != null ? getPath(r, c.path) : (Array.isArray(r) ? r[i] : undefined);
          return '<td>' + esc(fmt(v, c.digits)) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  kinds['table'] = {
    render: function (el, tile, ctx) {
      var cols = tile.columns || [];
      if (!tile.rpc) {
        drawTable(el, cols, tile.rows || []);
        return { suspend: function () {}, resume: function () {}, destroy: function () {} };
      }
      el.innerHTML = '<span class="endo-muted">Loading…</span>';
      return polled(tile, function () {
        return ctx.call(tile.rpc, tile.args).then(function (d) {
          var rows = getPath(d.result, tile.path);
          if (!Array.isArray(rows)) { el.innerHTML = errorLine(tile.path + ' is not a list in the ' + tile.rpc + ' response'); return; }
          drawTable(el, cols, rows);
        }, function (err) { el.innerHTML = errorLine(err); });
      });
    }
  };

  // ------------------------------------------------------------------- log

  kinds['log'] = {
    render: function (el, tile, ctx) {
      var max = tile.maxLines || 200;
      if (!tile.rpc) {
        el.innerHTML = '<pre class="endo-log">' + esc((tile.lines || []).slice(-max).join('\n')) + '</pre>';
        return { suspend: function () {}, resume: function () {}, destroy: function () {} };
      }
      el.innerHTML = '<pre class="endo-log endo-muted">Collecting…</pre>';
      return polled(tile, function () {
        return ctx.call(tile.rpc, tile.args).then(function (d) {
          var items = d.streaming ? (d.events || []) : [d.result];
          var lines = items.map(function (ev) {
            var v = getPath(ev, tile.path);
            return typeof v === 'string' ? v : JSON.stringify(v);
          }).slice(-max);
          el.innerHTML = '<pre class="endo-log">' + esc(lines.join('\n') || '(no events)') + '</pre>' +
                         '<div class="endo-foot"><span class="endo-muted">' + items.length + ' event(s) · ' +
                         new Date().toLocaleTimeString() + '</span></div>';
        }, function (err) { el.innerHTML = errorLine(err); });
      });
    }
  };

  // ----------------------------------------------------------------- frame

  // An HTML page of the component folder in a sandboxed frame (frame-host.js).
  // Its scripts reach the service only through window.endo.ctx, which the
  // shell answers with this component's ctx.
  kinds['frame'] = {
    render: function (el, tile, ctx) {
      if (!ctx.base || !MM.endo.frames) {
        el.innerHTML = errorLine('frame tiles need the component folder');
        return { suspend: function () {}, resume: function () {}, destroy: function () {} };
      }
      el.classList.add('endo-frame-body');
      var h = MM.endo.frames.create(el, {
        mode: 'html', base: ctx.base, entry: tile.entry, ctx: ctx,
        label: (tile.title || tile.id) + ' (' + ctx.component + ')'
      });
      // Through the handle, not bound to it: a restarted frame replaces its methods.
      return {
        suspend: function () { h.suspend(); },
        resume: function () { h.resume(); },
        destroy: function () { h.destroy(); }
      };
    }
  };

  // ------------------------------------------------------------ run-status

  function drawRun(el, flow, steps, current) {
    steps = steps || [];
    current = Math.max(0, Math.min(current || 0, steps.length));
    el.innerHTML = '<div class="endo-kv"><span class="k">' + esc(flow || 'run') + '</span>' +
      '<span class="v endo-small">' + esc(steps[current] || (current >= steps.length ? 'done' : '')) + '</span></div>' +
      '<div class="endo-steps" role="img" aria-label="step ' + Math.min(current + 1, steps.length) + ' of ' + steps.length + '">' +
      steps.map(function (s, i) {
        return '<i class="' + (i < current ? 'done' : i === current ? 'now' : '') + '" title="' + esc(s) + '"></i>';
      }).join('') + '</div>' +
      '<div class="endo-muted endo-small">step ' + Math.min(current + 1, steps.length) + ' of ' + steps.length + '</div>';
  }

  kinds['run-status'] = {
    render: function (el, tile, ctx) {
      if (!tile.rpc) {
        drawRun(el, tile.flow, tile.steps, tile.current);
        return { suspend: function () {}, resume: function () {}, destroy: function () {} };
      }
      el.innerHTML = '<span class="endo-muted">Loading…</span>';
      return polled(tile, function () {
        return ctx.call(tile.rpc, tile.args).then(function (d) {
          var r = getPath(d.result, tile.path) || {};
          drawRun(el, r.flow || tile.flow, r.steps || tile.steps, r.current);
        }, function (err) { el.innerHTML = errorLine(err); });
      });
    }
  };
})();
