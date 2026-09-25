/**
 * @fileoverview Bench Endoskeleton frame host (milestone M5): runs module
 * code in a sandboxed frame and serves its ctx over a MessagePort.
 *
 * A frame is <iframe sandbox="allow-scripts" srcdoc=...>: opaque origin (no
 * access to the shell's DOM, storage or cookies; no forms, popups or top
 * navigation), its own process (Electron: site-per-process +
 * IsolateSandboxedIframes per document, see electron/main.js; in a browser
 * that depends on the browser), and a CSP without network access. It cannot load
 * files, so the shell sends the code as text (frame-sdk.js builds blob:
 * modules from it).
 *
 * Every ctx call is answered by the real ctx of the component or plugin
 * (host.js makeCtx), so capabilities are checked in the shell (R1). The
 * shell enforces R5 at the boundary: a suspended frame loses its signal
 * subscriptions and its calls are refused until it is resumed. A watchdog
 * pings every frame; one that misses `missLimit` pings in a row is removed
 * and its tile says so (R10).
 *
 *   MM.endo.frames.create(el, spec) -> handle { ready, suspend, resume, destroy, setSelection, state }
 *     spec: { mode: 'module' | 'html', base, entry, fn, args, ctx, label, selection }
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};

  var SDK_URL = 'js/endo/frame-sdk.js';
  var CSP = "default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; " +
            "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; " +
            "frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";
  var BASE_CSS = 'html,body{margin:0;padding:0;background:transparent;color:var(--text,#14201A);' +
    'font-family:var(--font-sans,system-ui),system-ui,"Segoe UI",sans-serif;font-size:14px}' +
    '#endo-root{box-sizing:border-box;padding:.65rem .75rem;min-height:100%}*,*::before,*::after{box-sizing:inherit}';
  var THEME_TOKENS = ['--accent', '--surface', '--rule', '--muted', '--text', '--content-bg', '--font-sans', '--font-mono',
    '--good', '--warn', '--bad', '--navbar-bg', '--sidebar-text', '--l-operator', '--l-session', '--l-config',
    '--l-execution', '--l-runner', '--l-signals', '--l-bits'];

  // pingMs x missLimit: how long a frame may stop answering. startMs: how
  // long it may take to start (a new process each, so it varies with load).
  var config = { pingMs: 5000, missLimit: 3, startMs: 10000 };
  var live = new Set();
  var stats = { created: 0, killed: 0, failed: 0 };

  function esc(s) { return MM.endo.util.esc(s); }

  // ------------------------------------------------------------ sources

  var textCache = new Map();
  function fetchText(url) {
    if (!textCache.has(url)) {
      textCache.set(url, fetch(url, { cache: 'no-store' }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
        return r.text();
      }).catch(function (e) { textCache.delete(url); throw e; }));
    }
    return textCache.get(url);
  }

  var sdkP = null;
  function sdkSource() {
    sdkP = sdkP || fetchText(new URL(SDK_URL, document.baseURI).href)
      .then(function (t) { return t.replace(/<\/script/gi, '<\\/script'); });
    return sdkP;
  }

  /** Fetch a module and every module it imports relatively, inside `base` only. */
  function loadModuleGraph(base, entry) {
    var SDK = window.EndoFrameSdk;
    var files = {};
    function load(path) {
      if (path in files) return Promise.resolve();
      files[path] = null;
      return fetchText(new URL(path, base).href).then(function (src) {
        files[path] = src;
        return Promise.all(SDK.importsOf(path, src).map(load));
      });
    }
    var start = SDK.normalize(entry);
    if (!start) return Promise.reject(new Error(entry + ' leaves the plugin folder'));
    return load(start).then(function () { return { files: files, entry: start }; });
  }

  /**
   * The entry HTML with its relative classic scripts and stylesheets inlined
   * (the frame cannot fetch them). Anything else stays and is blocked by CSP.
   */
  function loadHtml(base, entry) {
    var SDK = window.EndoFrameSdk;
    var path = SDK.normalize(entry);
    if (!path) return Promise.reject(new Error(entry + ' leaves the component folder'));
    return fetchText(new URL(path, base).href).then(function (html) {
      var jobs = [];
      var dir = path.indexOf('/') >= 0 ? path.slice(0, path.lastIndexOf('/') + 1) : '';
      html.replace(/<script\b([^>]*)\bsrc=["']([^"']+)["']([^>]*)>\s*<\/script>/gi, function (m, a, src) {
        var rel = /^[a-z]+:|^\/\//i.test(src) ? null : SDK.normalize(dir + src);
        if (rel) jobs.push(fetchText(new URL(rel, base).href).then(function (t) { return [m, '<script>' + t.replace(/<\/script/gi, '<\\/script') + '</script>']; }));
        return m;
      });
      html.replace(/<link\b[^>]*rel=["']stylesheet["'][^>]*>/gi, function (m) {
        var href = (/href=["']([^"']+)["']/i.exec(m) || [])[1];
        var rel = href && !/^[a-z]+:|^\/\//i.test(href) ? SDK.normalize(dir + href) : null;
        if (rel) jobs.push(fetchText(new URL(rel, base).href).then(function (t) { return [m, '<style>' + t + '</style>']; }));
        return m;
      });
      return Promise.all(jobs).then(function (pairs) {
        pairs.forEach(function (p) { html = html.split(p[0]).join(p[1]); });
        return html;
      });
    });
  }

  function documentFor(spec, sdk, html) {
    var head = '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + CSP + '">' +
      '<style>' + BASE_CSS + '</style><script>' + sdk + '</script>';
    if (spec.mode !== 'html') {
      return '<!doctype html><html><head>' + head + '</head><body><div id="endo-root"></div></body></html>';
    }
    // The SDK and the CSP go first, before any of the entry's own markup.
    if (/<head[^>]*>/i.test(html)) return html.replace(/<head[^>]*>/i, function (m) { return m + head; });
    if (/<html[^>]*>/i.test(html)) return html.replace(/<html[^>]*>/i, function (m) { return m + '<head>' + head + '</head>'; });
    return '<!doctype html><html><head>' + head + '</head><body>' + html + '</body></html>';
  }

  // ------------------------------------------------------------ theme

  function themeTokens() {
    var cs = getComputedStyle(document.documentElement);
    var out = {};
    THEME_TOKENS.forEach(function (k) { var v = cs.getPropertyValue(k).trim(); if (v) out[k] = v; });
    return out;
  }
  function broadcastTheme() {
    var t = themeTokens();
    live.forEach(function (f) { f.post({ type: 'theme', tokens: t }); });
  }
  new MutationObserver(broadcastTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', broadcastTheme);
  }

  // ------------------------------------------------------------ one frame

  function create(el, spec) {
    stats.created++;
    var label = spec.label || 'module';
    var iframe = null, port = null;
    var state = 'loading';
    var suspended = false;
    var subs = {};            // sub id -> { names, off }
    var watchdog = null, awaiting = false, misses = 0, pingN = 0;
    var readyResolve, readyReject;
    var ready = new Promise(function (res, rej) { readyResolve = res; readyReject = rej; });
    ready.catch(function () { /* reported in the tile */ });

    el.classList.add('endo-frame-host');
    el.innerHTML = '<div class="endo-frame-status endo-muted">Starting…</div>';
    var banner = null;

    function showBanner(kind, text) {
      if (!banner) {
        banner = document.createElement('div');
        banner.className = 'endo-frame-banner';
        banner.setAttribute('role', 'status');
        el.appendChild(banner);
      }
      banner.className = 'endo-frame-banner ' + kind;
      banner.innerHTML = '<span>' + esc(text) + '</span><button type="button" aria-label="Dismiss">&times;</button>';
      banner.title = text;
      banner.querySelector('button').onclick = function () { banner.remove(); banner = null; };
    }

    function post(msg) { if (port) port.postMessage(msg); }

    function dropSubscriptions() {
      Object.keys(subs).forEach(function (id) { if (subs[id].off) { subs[id].off(); subs[id].off = null; } });
    }
    function subscribe(id) {
      var s = subs[id];
      if (!s || s.off) return;
      var cb = function (name, value, ts) { post({ type: 'signal', sub: id, name: name, value: value, ts: ts }); };
      cb.onStatus = function (st) { post({ type: 'signal', sub: id, status: st }); };
      s.off = spec.ctx.signals.subscribe(s.names, cb);   // throws CapabilityDenied when undeclared
    }

    function startWatchdog() {
      stopWatchdog();
      watchdog = setInterval(function () {
        if (awaiting) {
          misses++;
          if (misses >= config.missLimit) { kill(); return; }
        }
        awaiting = true;
        post({ type: 'ping', n: ++pingN });
      }, config.pingMs);
    }
    function stopWatchdog() { if (watchdog) { clearInterval(watchdog); watchdog = null; } awaiting = false; misses = 0; }

    var handle = {
      ready: ready,
      get state() { return state; },
      post: post,
      suspend: function () {
        if (suspended || !iframe) return;
        suspended = true;
        stopWatchdog();
        dropSubscriptions();          // R5, whatever the module does
        post({ type: 'suspend' });
      },
      resume: function () {
        if (!suspended || !iframe) return;
        suspended = false;
        Object.keys(subs).forEach(function (id) { try { subscribe(id); } catch (e) { /* reported when first denied */ } });
        post({ type: 'resume' });
        if (state === 'live') startWatchdog();
      },
      destroy: function () {
        post({ type: 'destroy' });
        teardown();
        el.innerHTML = '';
        el.classList.remove('endo-frame-host');
      },
      setSelection: function (sel) { post({ type: 'selection', selection: sel }); }
    };

    function teardown() {
      stopWatchdog();
      dropSubscriptions();
      subs = {};
      if (port) { try { port.close(); } catch (e) { /* closed */ } }
      port = null;
      if (iframe) { iframe.remove(); iframe = null; }
      live.delete(handle);
    }

    function fail(message) {
      stats.failed++;
      state = 'failed';
      teardown();
      el.innerHTML = '<div class="endo-error" role="status">' + esc(label + ': ' + message) + '</div>';
      readyReject(new Error(message));
    }

    function kill() {
      stats.killed++;
      state = 'killed';
      teardown();
      el.innerHTML = '<div class="endo-frame-dead" role="alert"><strong>Not responding.</strong> ' + esc(label) +
        ' stopped answering (' + config.missLimit + ' missed checks) and was stopped; the rest of the screen is not affected. ' +
        '<button type="button" class="btn btn-sm btn-outline-primary ms-1">Restart</button></div>';
      el.querySelector('button').onclick = function () { restart(); };
      readyReject(new Error('not responding'));
    }

    function restart() {
      var again = create(el, spec);
      Object.keys(again).forEach(function (k) {
        var d = Object.getOwnPropertyDescriptor(again, k);
        if (d.get) Object.defineProperty(handle, k, d); else handle[k] = again[k];
      });
    }

    // Requests from the frame, answered by the real ctx.
    function answer(msg) {
      var ctx = spec.ctx;
      var reply = function (value) { post({ type: 'result', id: msg.id, value: value === undefined ? null : value }); };
      var refuse = function (e) {
        var err = { code: (e && e.code) || 'Error', message: String((e && e.message) || e) };
        if (err.code === 'CapabilityDenied') showBanner('bad', label + ': ' + err.message);
        post({ type: 'result', id: msg.id, error: err });
      };
      var a = msg.args || [];
      if (suspended && msg.method !== 'unsubscribe' && msg.method !== 'notify') {
        return refuse({ code: 'Suspended', message: 'the tile is hidden (R5)' });
      }
      try {
        switch (msg.method) {
          case 'call': return ctx.call(a[0], a[1]).then(reply, refuse);
          case 'describe': return ctx.describe(a[0]).then(reply, refuse);
          case 'subscribe':
            subs[a[0]] = { names: (a[1] || []).map(String), off: null };
            try { subscribe(a[0]); } catch (e) { delete subs[a[0]]; throw e; }
            return reply(null);
          case 'unsubscribe':
            if (subs[a[0]]) { if (subs[a[0]].off) subs[a[0]].off(); delete subs[a[0]]; }
            return reply(null);
          case 'signals.set': return ctx.signals.set(a[0], a[1]).then(reply, refuse);
          case 'session.current': return ctx.session.current().then(reply, refuse);
          case 'session.label': return ctx.session.label(a[0]).then(reply, refuse);
          case 'config.get': return ctx.config.get(a[0], a[1]).then(reply, refuse);
          case 'config.put': return ctx.config.put(a[0], a[1], a[2]).then(reply, refuse);
          case 'notify': ctx.notify(a[0], String(a[1] || '').slice(0, 500)); return reply(null);
          case 'confirm': return ctx.confirm(String(a[0] || '').slice(0, 500)).then(reply, refuse);
          default: return refuse({ code: 'Unknown', message: 'no ctx method "' + msg.method + '"' });
        }
      } catch (e) { refuse(e); }
    }

    function onMessage(ev) {
      var msg = ev.data || {};
      if (msg.type === 'pong') { awaiting = false; misses = 0; return; }
      if (msg.type === 'hello') {
        post({ type: 'boot', mode: spec.mode, files: spec.files, entry: spec.entryPath, fn: spec.fn,
               args: spec.args || [], theme: themeTokens(), selection: spec.selection || null,
               component: spec.ctx && spec.ctx.component });
        return;
      }
      if (msg.type === 'ready') {
        state = 'live';
        var st = el.querySelector('.endo-frame-status');
        if (st) st.remove();
        if (!suspended) startWatchdog();
        readyResolve(msg.result);
        return;
      }
      if (msg.type === 'size') {
        if (spec.autoHeight && iframe) iframe.style.height = Math.max(40, Math.min(Number(msg.height) || 0, 1600)) + 'px';
        return;
      }
      if (msg.type === 'failed') { fail(msg.message || 'failed to start'); return; }
      if (msg.type === 'error') { showBanner('warn', label + ': ' + String(msg.message || '').split('\n')[0]); return; }
      if (msg.type === 'call') answer(msg);
    }

    var sources = spec.mode === 'html'
      ? Promise.all([sdkSource(), loadHtml(spec.base, spec.entry)]).then(function (r) { return { sdk: r[0], html: r[1] }; })
      : Promise.all([sdkSource(), loadModuleGraph(spec.base, spec.entry)]).then(function (r) {
          spec.files = r[1].files;
          spec.entryPath = r[1].entry;
          return { sdk: r[0] };
        });

    sources.then(function (src) {
      if (state !== 'loading') return;
      iframe = document.createElement('iframe');
      iframe.className = 'endo-frame';
      iframe.setAttribute('sandbox', 'allow-scripts');
      iframe.setAttribute('referrerpolicy', 'no-referrer');
      iframe.setAttribute('title', label);
      iframe.srcdoc = documentFor(spec, src.sdk, src.html);
      iframe.addEventListener('load', function () {
        if (!iframe) return;
        var ch = new MessageChannel();
        port = ch.port1;
        port.onmessage = onMessage;
        iframe.contentWindow.postMessage({ type: 'endo-init' }, '*', [ch.port2]);
      }, { once: true });
      el.appendChild(iframe);
      live.add(handle);
      // A frame that never gets going is as stuck as one that stops answering.
      setTimeout(function () { if (state === 'loading' && iframe) kill(); }, Math.max(config.startMs, config.pingMs * config.missLimit));
    }, function (e) { fail(e.message || String(e)); });

    return handle;
  }

  MM.endo.frames = {
    create: create,
    /** Fetch a module graph without running it (plugins check their kinds on load). */
    loadModules: loadModuleGraph,
    config: config,
    stats: function () { return { live: live.size, created: stats.created, killed: stats.killed, failed: stats.failed }; },
    themeTokens: themeTokens
  };
})();
