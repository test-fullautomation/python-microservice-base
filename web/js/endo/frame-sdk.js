/**
 * @fileoverview Bench Endoskeleton frame SDK (milestone M5). Runs INSIDE a
 * sandboxed frame (sandbox="allow-scripts", opaque origin, own process,
 * no network by CSP). The shell inlines this file into the frame document.
 *
 * The frame cannot load anything itself: the shell sends the code as text
 * over a MessagePort, and this SDK turns it into blob: modules (relative
 * imports rewritten), then calls the entry:
 *
 *   module mode   import(entry)[fn](root, ...args, ctx)   fn: render | mount | run
 *   html mode     the entry HTML is already the document; scripts use
 *                 window.endo: endo.ctx, endo.on('suspend' | 'resume' | 'theme' | 'selection', fn)
 *
 * ctx here is a proxy: every call goes to the shell, which checks the
 * component's (or plugin's) declared capabilities (R1) and answers.
 * The shell pings; an answer proves the frame's event loop is alive.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;                                   // Node tests
  } else if (typeof document !== 'undefined' && document.currentScript &&
             document.currentScript.hasAttribute('data-endo-shell')) {
    root.EndoFrameSdk = api;                                // the shell: helpers only
  } else {
    api.boot();                                             // inside a frame
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var IMPORT_RE = /(\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])(\.{1,2}\/[^'"\s]+)\2/g;

  /** "a/b/../c.js" -> "a/c.js"; null when it leaves the root. */
  function normalize(p) {
    var out = [];
    var parts = String(p).split('/');
    for (var i = 0; i < parts.length; i++) {
      var s = parts[i];
      if (!s || s === '.') continue;
      if (s === '..') { if (!out.length) return null; out.pop(); }
      else out.push(s);
    }
    return out.join('/');
  }

  function dirname(p) { var i = p.lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i + 1); }

  /** Relative module specifiers of `src`, resolved against the module's path. */
  function importsOf(path, src) {
    var out = [];
    String(src).replace(IMPORT_RE, function (m, pre, q, spec) {
      var r = normalize(dirname(path) + spec);
      if (r && out.indexOf(r) < 0) out.push(r);
      return m;
    });
    return out;
  }

  /** Replace relative specifiers with URLs from `urlOf(resolvedPath)`. */
  function rewriteImports(path, src, urlOf) {
    return String(src).replace(IMPORT_RE, function (m, pre, q, spec) {
      var r = normalize(dirname(path) + spec);
      var url = r && urlOf(r);
      if (!url) throw new Error(path + ' imports ' + spec + ', which was not shipped');
      return pre + q + url + q;
    });
  }

  /**
   * Build blob: URLs for a module graph, leaves first.
   * @param {Object<string,string>} files - path -> source
   * @param {function(string): string} makeUrl - source -> URL
   * @returns {Object<string,string>} path -> URL
   */
  function linkModules(files, makeUrl) {
    var urls = {};
    var visiting = {};
    function visit(p) {
      if (urls[p]) return urls[p];
      if (!(p in files)) throw new Error('module ' + p + ' was not shipped');
      if (visiting[p]) throw new Error('circular import through ' + p);
      visiting[p] = true;
      importsOf(p, files[p]).forEach(visit);
      urls[p] = makeUrl(rewriteImports(p, files[p], function (d) { return urls[d]; }));
      delete visiting[p];
      return urls[p];
    }
    Object.keys(files).forEach(visit);
    return urls;
  }

  // ------------------------------------------------------------ in the frame

  function boot() {
    var port = null;
    var seq = 0;
    var pending = {};
    var subs = {};            // subscription id -> callback
    var handlers = { suspend: [], resume: [], theme: [], selection: [], destroy: [] };
    var instance = null;
    var selection = null;

    // Page scripts may call before the shell hands over the port: queue.
    var queue = [];
    function send(msg) { if (port) port.postMessage(msg); else queue.push(msg); }

    function request(method, args) {
      return new Promise(function (resolve, reject) {
        var id = ++seq;
        pending[id] = { resolve: resolve, reject: reject };
        send({ type: 'call', id: id, method: method, args: args || [] });
      });
    }

    function emit(name, value) {
      (handlers[name] || []).slice().forEach(function (fn) { try { fn(value); } catch (e) { report(e); } });
    }

    function report(err) {
      send({ type: 'error', message: String((err && (err.stack || err.message)) || err).slice(0, 2000) });
    }
    window.addEventListener('error', function (ev) { report(ev.error || ev.message); });
    window.addEventListener('unhandledrejection', function (ev) { report(ev.reason); });

    function applyTheme(tokens) {
      var st = document.documentElement.style;
      Object.keys(tokens || {}).forEach(function (k) { st.setProperty(k, tokens[k]); });
      emit('theme', tokens);
    }

    var ctx = {
      call: function (method, args) { return request('call', [method, args || {}]); },
      describe: function (method) { return request('describe', [method]); },
      signals: {
        subscribe: function (names, cb) {
          var id = 's' + (++seq);
          subs[id] = cb;
          request('subscribe', [id, names]).catch(function (e) {
            delete subs[id];
            if (cb && cb.onStatus) (names || []).forEach(function (n) { cb.onStatus({ name: n, state: 'error', message: e.message }); });
            report(e);
          });
          return function unsubscribe() {
            if (!subs[id]) return;
            delete subs[id];
            send({ type: 'call', id: ++seq, method: 'unsubscribe', args: [id] });
          };
        },
        set: function (name, value) { return request('signals.set', [name, value]); }
      },
      session: {
        current: function () { return request('session.current', []); },
        label: function (labels) { return request('session.label', [labels]); }
      },
      config: {
        get: function (scope, key) { return request('config.get', [scope, key]); },
        put: function (scope, key, value) { return request('config.put', [scope, key, value]); }
      },
      notify: function (kind, text) { send({ type: 'call', id: ++seq, method: 'notify', args: [kind, text] }); },
      confirm: function (message) { return request('confirm', [message]); },
      selection: function () { return selection; },
      onSelection: function (fn) {
        handlers.selection.push(fn);
        return function () { handlers.selection = handlers.selection.filter(function (f) { return f !== fn; }); };
      }
    };

    window.endo = {
      ctx: ctx,
      on: function (name, fn) { if (handlers[name]) handlers[name].push(fn); },
      report: report
    };

    function onMessage(ev) {
      var msg = ev.data || {};
      switch (msg.type) {
        case 'ping': send({ type: 'pong', n: msg.n }); break;
        case 'result': {
          var p = pending[msg.id];
          if (!p) break;
          delete pending[msg.id];
          if (msg.error) {
            var e = new Error(msg.error.message);
            e.code = msg.error.code;
            p.reject(e);
          } else {
            p.resolve(msg.value);
          }
          break;
        }
        case 'signal': {
          var cb = subs[msg.sub];
          if (!cb) break;
          if (msg.status) { if (cb.onStatus) cb.onStatus(msg.status); }
          else cb(msg.name, msg.value, msg.ts);
          break;
        }
        case 'theme': applyTheme(msg.tokens); break;
        case 'selection': selection = msg.selection; emit('selection', selection); break;
        case 'suspend': if (instance && instance.suspend) instance.suspend(); emit('suspend'); break;
        case 'resume': if (instance && instance.resume) instance.resume(); emit('resume'); break;
        case 'destroy': if (instance && instance.destroy) instance.destroy(); emit('destroy'); instance = null; break;
        case 'boot': start(msg); break;
      }
    }

    // Content height, for hosts that size the frame to it (drawer, dock, views).
    var lastH = 0;
    function reportSize() {
      var h = Math.ceil(document.documentElement.scrollHeight);
      if (h !== lastH) { lastH = h; send({ type: 'size', height: h }); }
    }
    if (typeof ResizeObserver === 'function') new ResizeObserver(reportSize).observe(document.documentElement);

    function start(msg) {
      ctx.component = msg.component || '';
      applyTheme(msg.theme);
      selection = msg.selection || null;
      setTimeout(reportSize, 0);
      if (msg.mode !== 'module') { send({ type: 'ready' }); return; }
      var urls;
      try {
        urls = linkModules(msg.files || {}, function (src) {
          return URL.createObjectURL(new Blob([src], { type: 'text/javascript' }));
        });
      } catch (e) { report(e); send({ type: 'failed', message: e.message }); return; }
      import(urls[msg.entry]).then(function (mod) {
        var fn = mod[msg.fn];
        if (typeof fn !== 'function') throw new Error(msg.entry + ' does not export ' + msg.fn + '()');
        // render(el, ...args, ctx) / mount(el, ctx); a command is run(ctx): no element.
        if (msg.fn === 'run') return fn(ctx);
        var rootEl = document.getElementById('endo-root');
        return fn.apply(null, [rootEl].concat(msg.args || []).concat([ctx]));
      }).then(function (inst) {
        instance = inst || {};
        send({ type: 'ready', result: msg.fn === 'run' ? (inst === undefined ? null : inst) : undefined });
      }).catch(function (e) {
        report(e);
        send({ type: 'failed', message: e.message || String(e) });
      });
    }

    window.addEventListener('message', function first(ev) {
      if (!ev.data || ev.data.type !== 'endo-init' || !ev.ports || !ev.ports[0]) return;
      window.removeEventListener('message', first);
      port = ev.ports[0];
      port.onmessage = onMessage;
      send({ type: 'hello' });
      queue.splice(0).forEach(send);
    });
  }

  return { boot: boot, normalize: normalize, importsOf: importsOf, rewriteImports: rewriteImports, linkModules: linkModules };
});
