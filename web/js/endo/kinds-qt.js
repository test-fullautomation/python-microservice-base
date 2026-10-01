/**
 * @fileoverview Bench Endoskeleton Qt tile kinds (contract v1): qml, widget, wasm.
 *
 *   { "kind": "qml",    "entry": "ServiceUI.qml" }       the QML shell (qt-shell/) runs the file
 *   { "kind": "widget", "entry": "ServiceUI.ui" }        the Widget shell (widget-shell/) builds the form
 *   { "kind": "wasm",   "entry": "myui.js" }             the component's own Qt build (loader .js + .wasm)
 *   optional "minHeight": 520                           tile body height in px
 *
 * Every tile gets its own Qt instance, so tiles of several components can
 * share the bench. Their ServiceBridge calls reach the service over gRPC
 * through the component's ctx (grpc.call, binds.grpc), never the broker:
 * QtBridge.js routes each call to the tile that made it. A method is a
 * method of the first bound service, or "<service>/<Method>" for another
 * one (binds.grpc may list several). A call's args
 * are the request message (one object), or positional values matched to
 * the request fields in order (from gRPC reflection). The answer is the
 * single field's value when the response has one scalar field, otherwise
 * the response as JSON.
 *
 * A per-service build (wasm) cannot be told its service name by the page;
 * it gets the tile's routing token as Module.endoToken and should call with
 * it (see QtBridge.js), or its timer-driven calls go to the last-clicked tile.
 *
 * qml and widget files are data for the shipped shells. A wasm tile runs
 * the component's loader script in the GUI page, with the trust of a
 * classic panel; the linter says so.
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};
  var kinds = MM.endo.kinds = MM.endo.kinds || {};

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function errorLine(err) {
    return '<div class="endo-error">' + esc((err && err.message) || err) + '</div>';
  }

  // ------------------------------------------------------------ loading

  var factories = {};   // loader URL -> Promise<factory>

  /** Load an Emscripten loader script once; resolves its module factory. */
  function loadFactory(url, names) {
    if (!factories[url]) {
      factories[url] = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = url;
        s.onload = function () {
          var f = names.map(function (n) { return window[n]; })
            .filter(function (x) { return typeof x === 'function'; })[0];
          if (f) resolve(f);
          else { delete factories[url]; reject(new Error('no Qt entry function (' + names.join(', ') + ') in ' + url)); }
        };
        s.onerror = function () { delete factories[url]; reject(new Error('cannot load ' + url)); };
        document.head.appendChild(s);
      });
    }
    return factories[url];
  }

  /** XHR, not fetch: it also reads file:// pages in the desktop app. */
  function readText(url) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('GET', url, true);
      xhr.onload = function () {
        if (xhr.status === 200 || xhr.status === 0) resolve(xhr.responseText);
        else reject(new Error('HTTP ' + xhr.status + ' loading ' + url));
      };
      xhr.onerror = function () { reject(new Error('cannot read ' + url)); };
      xhr.send();
    });
  }

  /** The entry's URL, which must stay inside the component folder. */
  function entryUrl(ctx, entry) {
    if (!ctx.base) throw new Error('Qt tiles need the component folder');
    var url = new URL(entry, ctx.base).href;
    if (url.indexOf(ctx.base) !== 0) throw new Error(entry + ' leaves the component folder');
    return url;
  }

  // ------------------------------------------------- calls to the service

  function coerce(field, v) {
    var t = String(field.type || '').toLowerCase();
    if (field.label === 'repeated') {
      if (Array.isArray(v)) return v;
      if (typeof v === 'string') {
        try { var parsed = JSON.parse(v); if (Array.isArray(parsed)) return parsed; } catch (e) { /* a list */ }
        return v.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
      }
      return [v];
    }
    if (typeof v !== 'string') return v;
    if (t === 'bool') return v === 'true' || v === '1';
    if (/^(float|double|u?int|s?fixed|sint)/.test(t) && v.trim() !== '' && !isNaN(Number(v))) return Number(v);
    return v;
  }

  /** The request message of a ServiceBridge call. */
  function toRequest(ctx, method, args) {
    if (args && typeof args === 'object' && !Array.isArray(args)) return Promise.resolve(args);
    var list = Array.isArray(args) ? args : (args == null ? [] : [args]);
    if (!list.length) return Promise.resolve({});
    if (list.length === 1 && list[0] && typeof list[0] === 'object' && !Array.isArray(list[0])) {
      return Promise.resolve(list[0]);
    }
    return ctx.describe(method).then(function (m) {
      var fields = m.input_fields || [];
      if (list.length > fields.length) {
        throw new Error(method + ' takes ' + fields.length + ' field(s); the UI sent ' + list.length + ' value(s)');
      }
      var req = {};
      list.forEach(function (v, i) { req[fields[i].name] = coerce(fields[i], v); });
      return req;
    });
  }

  /** What the UI gets back: one scalar field as text, anything else as JSON. */
  function replyText(result) {
    if (result == null) return '';
    if (typeof result !== 'object') return String(result);
    var keys = Object.keys(result);
    if (keys.length === 1) {
      var v = result[keys[0]];
      if (v == null || typeof v !== 'object') return v == null ? '' : String(v);
    }
    return JSON.stringify(result);
  }

  function ask(ctx, method, args) {
    return askFull(ctx, method, args).then(function (r) { return r.text; });
  }

  /** The answer as text (replyText) and as the whole response in JSON. */
  function askFull(ctx, method, args) {
    return toRequest(ctx, method, args)
      .then(function (req) { return ctx.call(method, req); })
      .then(function (d) { return { text: replyText(d.result), json: JSON.stringify(d.result == null ? {} : d.result) }; });
  }

  // --------------------------------------------------- C string helpers

  function withStrings(mod, prefix, strs, fn) {
    var enc = new TextEncoder();
    var ptrs = strs.map(function (s) {
      var bytes = enc.encode(String(s));
      var p = mod['_' + prefix + '_malloc'](bytes.length + 1);
      mod.HEAPU8.set(bytes, p);
      mod.HEAPU8[p + bytes.length] = 0;
      return p;
    });
    try { return fn.apply(null, ptrs); }
    finally { ptrs.forEach(function (p) { mod['_' + prefix + '_free'](p); }); }
  }

  function callC(mod, prefix, name, strs) {
    var f = mod && mod['_' + prefix + '_' + name];
    if (typeof f !== 'function') throw new Error(prefix + '_' + name + ' is not exported');
    return withStrings(mod, prefix, strs, f);
  }

  // ------------------------------------------------------- start quietly

  /** Is node inside a Qt tile? Qt keeps its elements in a shadow root of the tile. */
  function inQtTile(node) {
    for (var n = node; n; n = n.parentNode || (n.host || null)) {
      if (n.classList && n.classList.contains('endo-qt-body')) return true;
    }
    return false;
  }

  // Qt focuses its own (hidden) input elements, on start and when a widget
  // takes focus. The browser would scroll each one into view and the page
  // would jump to the tile. The tile is already where the user looks.
  if (typeof HTMLElement !== 'undefined' && !HTMLElement.prototype.focus.__endoQt) {
    var nativeFocus = HTMLElement.prototype.focus;
    var quietFocus = function (opts) {
      if (inQtTile(this)) return nativeFocus.call(this, Object.assign({}, opts || {}, { preventScroll: true }));
      return nativeFocus.apply(this, arguments);
    };
    quietFocus.__endoQt = true;
    HTMLElement.prototype.focus = quietFocus;
  }

  /**
   * A starting Qt app focuses its first input field, and the browser scrolls
   * that into view: with several Qt tiles the page jumps to the last one.
   * Keep the scroll positions around the tile and drop that focus, unless
   * the user clicked or typed meanwhile. Returns settle(): call it when the
   * app runs; it restores now and twice more (Qt focuses a bit later).
   */
  function holdStill(el) {
    var saved = [];
    // Every ancestor: one that cannot scroll yet may by the time Qt focuses.
    for (var n = el.parentElement; n; n = n.parentElement) saved.push([n, n.scrollTop, n.scrollLeft]);
    var page = document.scrollingElement || document.documentElement;
    saved.push([page, page.scrollTop, page.scrollLeft]);
    var focused = document.activeElement;
    var touched = false;
    function mark() { touched = true; }
    ['pointerdown', 'keydown', 'wheel'].forEach(function (t) { document.addEventListener(t, mark, true); });
    function restore() {
      if (touched) return;
      if (el.contains(document.activeElement)) {
        document.activeElement.blur();
        if (focused && focused !== document.body && typeof focused.focus === 'function') {
          try { focused.focus({ preventScroll: true }); } catch (e) { /* gone */ }
        }
      }
      saved.forEach(function (s) { s[0].scrollTop = s[1]; s[0].scrollLeft = s[2]; });
    }
    return function settle() {
      restore();
      setTimeout(restore, 150);
      setTimeout(restore, 600);
      setTimeout(function () {
        restore();
        ['pointerdown', 'keydown', 'wheel'].forEach(function (t) { document.removeEventListener(t, mark, true); });
      }, 1500);
    };
  }

  // ---------------------------------------------------------------- tile

  function frame(el, what) {
    el.classList.add('endo-qt-body');
    el.innerHTML = '<div class="endo-qt-canvas"></div>' +
      '<div class="endo-qt-status endo-muted" role="status">Starting ' + esc(what) + '…</div>';
    return { box: el.querySelector('.endo-qt-canvas'), status: el.querySelector('.endo-qt-status') };
  }

  /**
   * A Qt tile: start an instance in the tile, route its calls to ctx.
   *
   * @param {object} spec
   * @param {string} spec.what - shown while starting
   * @param {function(tile, ctx): {script: string, names: string[]}} spec.loader
   * @param {function(mod, route, tile, ctx): (Promise|void)} spec.start - after the instance runs
   * @param {function(mod, route): function(method, args): Promise} spec.answer
   * @param {function(mod)} [spec.stop]
   */
  function qtKind(spec) {
    return {
      render: function (el, tile, ctx) {
        var ui = frame(el, spec.what);
        // A Qt canvas does not make the tile grow; minHeight (px) gives it room.
        if (typeof tile.minHeight === 'number') el.style.minHeight = tile.minHeight + 'px';
        var mod = null;
        var suspended = false;
        var dead = false;
        if (!MM.qtBridge) {
          ui.status.innerHTML = errorLine('the Qt bridge (QtBridge.js) is not loaded');
          return { suspend: function () {}, resume: function () {}, destroy: function () {} };
        }
        MM.qtBridge.install();
        var answer = null;
        // A Qt app may call while its module is still starting (its main()
        // runs inside the factory): those calls wait until the tile answers.
        var markReady, markFailed;
        var ready = new Promise(function (resolve, reject) { markReady = resolve; markFailed = reject; });
        ready.catch(function () { /* reported in the tile */ });
        var route = MM.qtBridge.addRoute(el, function (method, args) {
          if (suspended || dead) return Promise.reject(new Error('the tile is not shown; ' + method + ' was not called'));
          if (answer) return answer(method, args);
          return ready.then(function () { return answer(method, args); });
        });

        var loader;
        try { loader = spec.loader(tile, ctx); }
        catch (e) { ui.status.innerHTML = errorLine(e); return stopped(); }

        var settle = holdStill(el);
        loadFactory(loader.script, loader.names)
          .then(function (factory) {
            if (dead) return null;
            // endoToken: a per-service build reads it as Module.endoToken and
            // passes it as the service name, so its calls always reach this tile.
            // endoServices: the proto services the component binds (binds.grpc),
            // so one build can serve several components and show only theirs.
            return factory({ qtContainerElements: [ui.box], endoToken: route.token,
                             endoServices: (ctx.services || []).slice() });
          })
          .then(function (m) {
            if (dead || !m) return null;
            mod = m;
            answer = spec.answer(mod, route, ctx);
            markReady();
            return spec.start(mod, route, tile, ctx);
          })
          .then(function () {
            if (!dead && mod) ui.status.hidden = true;
            settle();
          })
          .catch(function (err) {
            markFailed(err);
            console.warn('[endo] Qt tile ' + tile.id + ' of ' + ctx.component + ':', err);
            ui.status.hidden = false;
            ui.status.innerHTML = errorLine(err);
          });

        function stopped() {
          return {
            suspend: function () { suspended = true; },
            resume: function () { suspended = false; },
            destroy: function () {
              dead = true;
              route.remove();
              if (mod && spec.stop) { try { spec.stop(mod); } catch (e) { /* already gone */ } }
              // Emscripten cannot free a running Qt instance; drop its canvas.
              ui.box.innerHTML = '';
              mod = null;
            }
          };
        }
        return stopped();
      }
    };
  }

  /** Shell answer: the reply goes back through <prefix>_onResponse / _onError. */
  function shellAnswer(prefix) {
    return function (mod, route, ctx) {
      return function (method, args) {
        return ask(ctx, method, args).then(function (text) {
          callC(mod, prefix, 'onResponse', [method, text]);
        }, function (err) {
          callC(mod, prefix, 'onError', [method, (err && err.message) || String(err)]);
        });
      };
    };
  }

  kinds['qml'] = qtKind({
    what: 'the QML shell',
    loader: function (tile, ctx) {
      entryUrl(ctx, tile.entry);
      return { script: 'qt-shell/qtshell.js', names: ['qtshell_entry', 'createQtAppInstance'] };
    },
    start: function (mod, route, tile, ctx) {
      var url = entryUrl(ctx, tile.entry);
      return readText(url).then(function (source) {
        callC(mod, 'qtshell', 'setServiceName', [route.token]);
        callC(mod, 'qtshell', 'loadQmlSource', [source, url]);
      });
    },
    answer: shellAnswer('qtshell'),
    stop: function (mod) { mod._qtshell_clearQml(); }
  });

  kinds['widget'] = qtKind({
    what: 'the Widget shell',
    loader: function (tile, ctx) {
      entryUrl(ctx, tile.entry);
      return { script: 'widget-shell/widgetshell.js', names: ['widgetshell_entry', 'createQtAppInstance'] };
    },
    start: function (mod, route, tile, ctx) {
      return readText(entryUrl(ctx, tile.entry)).then(function (source) {
        callC(mod, 'widgetshell', 'setServiceName', [route.token]);
        callC(mod, 'widgetshell', 'loadUiSource', [source]);
      });
    },
    // No stop: the shell exports widgetshell_clearUi, but its controller has no clearUi().
    answer: shellAnswer('widgetshell')
  });

  // A per-service Qt build reads the answer from the promise it gets back,
  // in the shape a broker reply has, plus result_json: the whole response,
  // for builds that read fields by name.
  kinds['wasm'] = qtKind({
    what: 'the Qt application',
    loader: function (tile, ctx) {
      var url = entryUrl(ctx, tile.entry);
      var base = url.replace(/^.*\//, '').replace(/\.js$/i, '');
      return { script: url, names: [base + '_entry', 'createQtAppInstance', base + 'Module'] };
    },
    start: function () {},
    answer: function (mod, route, ctx) {
      return function (method, args) {
        return askFull(ctx, method, args).then(function (r) {
          return { result: 'pass', result_data: r.text, result_json: r.json };
        });
      };
    }
  });

  MM.endo.qtKinds = { toRequest: toRequest, replyText: replyText };
})();
