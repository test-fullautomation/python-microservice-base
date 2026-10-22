/**
 * @fileoverview Bench Endoskeleton component host (contract v1).
 *
 * Mounts one component.json into a panel: lints it against the contract,
 * refuses it visibly when it breaks a rule (R10), otherwise lays its tiles
 * on the 4-column stage and gives each tile a ctx limited to the
 * capabilities the manifest declared (R1).
 *
 *   MM.endo.mountComponent(manifest, el, env) -> Promise<handle>
 *     env:    { consulName, consulUrl, protoPath }
 *     handle: { suspend(), resume(), destroy(), issues }
 *
 * The bench (bench.js) mixes tiles of many components on one stage and
 * uses the pieces directly: prepareComponent(), renderTile(),
 * instanceGroup().
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};

  var SCHEMA_URL = 'js/endo/contract/component.schema.json';

  /**
   * Kinds of plugins that are planned but not installed here, for a better
   * hint than "no plugin provides it". Installed plugins answer for
   * themselves through MM.endo.plugins.knownKinds().
   */
  var KNOWN_PLUGIN_KINDS = { 'uds-console': 'uds-console', 'graph': 'graph-studio' };

  /** kind -> plugin id of every kind a plugin could provide (installed or planned). */
  function pluginKindOwners() {
    var out = Object.assign({}, KNOWN_PLUGIN_KINDS);
    var known = MM.endo.plugins ? MM.endo.plugins.knownKinds() : {};
    Object.keys(known).forEach(function (k) { out[k] = known[k].plugin; });
    return out;
  }

  /** The "not available" text of a tile whose kind no active plugin provides. */
  function missingKindHtml(kind) {
    var known = (MM.endo.plugins ? MM.endo.plugins.knownKinds() : {})[kind];
    if (known) {
      var why = known.state === 'disabled' ? 'is turned off: enable it under <em>Administrator → Plugins</em>.'
        : known.state === 'refused' ? 'was refused by the shell (see <em>Administrator → Plugins</em>).'
        : known.state === 'error' ? 'failed to load (see <em>Administrator → Plugins</em>).'
        : 'is not active.';
      return 'Kind <code>' + esc(kind) + '</code> comes from the <strong>' + esc(known.title) + '</strong> plugin, which ' + why;
    }
    var owner = KNOWN_PLUGIN_KINDS[kind];
    return 'Kind <code>' + esc(kind) + '</code> is not available. ' +
      (owner ? 'It comes from the <strong>' + esc(owner) + '</strong> plugin, which is not installed.' : 'No plugin provides it.');
  }

  var schemaPromise = null;
  function loadSchema() {
    if (!schemaPromise) {
      schemaPromise = fetch(SCHEMA_URL)
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .catch(function () { schemaPromise = null; return null; });
    }
    return schemaPromise;
  }

  function esc(s) { return MM.endo.util.esc(s); }

  function deniedError(cap) {
    var e = new Error('CapabilityDenied: ' + cap + ' is not declared in requires.capabilities');
    e.code = 'CapabilityDenied';
    return e;
  }
  function denied(cap) { return Promise.reject(deniedError(cap)); }

  /** Local stand-in for the configuration service (stub until it exists). */
  function configKey(scope, key) { return 'mm_config_stub:' + scope + ':' + key; }

  /** The only way a tile reaches the outside world. */
  function makeCtx(manifest, env) {
    var req = manifest.requires || {};
    var caps = {};
    (req.capabilities || []).forEach(function (c) { caps[c] = true; });
    var binds = manifest.binds || {};
    var consulName = binds.consul === '@self' ? env.consulName : binds.consul;
    // No prototype: Consul names such as "constructor" are plain keys here.
    var methodsP = Object.create(null);
    var open = 0;
    var callWatchers = [];
    // One binary may serve several proto services: the first is the default,
    // the others are called as "<service>/<Method>".
    var services = [].concat(binds.grpc || []);
    // Other Consul services this one may call (a plugin a service delivers,
    // binds.uses), as "<consul>:<ProtoService>/<Method>".
    var uses = [].concat(binds.uses || []);

    function notBound(text) {
      var e = new Error('NotBound: ' + text);
      e.code = 'NotBound';
      return e;
    }

    function target(method) {
      var s = String(method || '');
      var c = s.indexOf(':');
      if (c > 0 && s.slice(0, c) !== consulName) {
        var other = s.slice(0, c), rest = s.slice(c + 1), j = rest.lastIndexOf('/');
        if (uses.indexOf(other) < 0) throw notBound(other + ' is not in binds.uses');
        if (j <= 0) throw notBound('name the proto service of ' + other + ': "' + other + ':<ProtoService>/<Method>"');
        return { consul: other, service: rest.slice(0, j), method: rest.slice(j + 1) };
      }
      if (c > 0) s = s.slice(c + 1);
      var i = s.lastIndexOf('/');
      if (i < 0) return { consul: consulName, service: services[0], method: s };
      var svc = s.slice(0, i);
      if (services.indexOf(svc) < 0) throw notBound(svc + ' is not in binds.grpc');
      return { consul: consulName, service: svc, method: s.slice(i + 1) };
    }

    /** A failed call as an Error with the service's full status (slot 4). */
    function callError(method, d) {
      d = d || {};
      var e = new Error(d.error || (method + ' failed'));
      // The gRPC status name, or BridgeError when the call never reached the service.
      e.code = d.code || 'BridgeError';
      e.details = Array.isArray(d.details) ? d.details : [];
      e.requestId = d.request_id || '';
      return e;
    }

    /** { timeout: ms, metadata: {key: value} } of a call, in the bridge's words. */
    function callOptions(opts) {
      opts = opts || {};
      var out = {};
      var t = Number(opts.timeout);
      if (opts.timeout != null && !(t > 0)) throw Object.assign(new Error('timeout must be a positive number of milliseconds'), { code: 'BadOptions' });
      if (t > 0) out.timeout = t / 1000;
      if (opts.metadata != null) {
        if (typeof opts.metadata !== 'object' || Array.isArray(opts.metadata)) {
          throw Object.assign(new Error('metadata must be an object of key: value'), { code: 'BadOptions' });
        }
        out.metadata = {};
        Object.keys(opts.metadata).forEach(function (k) { out.metadata[k] = String(opts.metadata[k]); });
      }
      return out;
    }

    return {
      component: manifest.component,
      consulName: consulName,
      /** URL of the component (or plugin) folder: where frame tiles find their pages. */
      base: env.base || '',

      /** The proto services this component may call (binds.grpc; the first is the default). */
      services: services.slice(),

      /** The other Consul services this component may call (binds.uses). */
      uses: uses.slice(),

      /**
       * Unary gRPC call: "<Method>", "<ProtoService>/<Method>" or, for a
       * service in binds.uses, "<consul>:<ProtoService>/<Method>".
       * opts: { timeout: ms, metadata: {key: value} }. A failure rejects
       * with an Error carrying code (gRPC status name, BridgeError,
       * NotBound, CapabilityDenied), details (decoded google.rpc details)
       * and requestId.
       */
      call: function (method, args, opts) {
        if (!caps['grpc.call']) return denied('grpc.call');
        var t, o;
        try { t = target(method); o = callOptions(opts); } catch (e) { return Promise.reject(e); }
        return MM.grpcClient.callMethod({
          consulName: t.consul,
          consulUrl: env.consulUrl,
          grpcService: t.service,
          method: t.method,
          argsJson: JSON.stringify(args || {}),
          protoPath: t.consul === consulName ? env.protoPath : '',
          timeout: o.timeout,
          metadata: o.metadata
        }).then(function (d) {
          if (!d || !d.ok) throw callError(method, d);
          callWatchers.slice().forEach(function (fn) {
            try { fn(method, args || {}); } catch (e) { console.warn('[endo] onCall watcher failed:', e); }
          });
          return d;
        }, function (err) {
          throw callError(method, { error: err && err.message });
        });
      },

      /**
       * fn(method, args) after each successful call of this component, from
       * any of its tiles: dropdowns that depend on a setting read their
       * choices again (reloadAfter). Returns off().
       */
      onCall: function (fn) {
        callWatchers.push(fn);
        return function off() {
          var i = callWatchers.indexOf(fn);
          if (i >= 0) callWatchers.splice(i, 1);
        };
      },

      describe: function (method) {
        if (!caps['grpc.call']) return denied('grpc.call');
        var t;
        try { t = target(method); } catch (e) { return Promise.reject(e); }
        methodsP[t.consul] = methodsP[t.consul] ||
          MM.grpcClient.getServiceMethods(t.consul, env.consulUrl, t.consul === consulName ? env.protoPath : '');
        return methodsP[t.consul].then(function (data) {
          var svc = ((data && data.grpc_services) || []).filter(function (s) { return s.name === t.service; })[0];
          if (!svc) {
            delete methodsP[t.consul];   // retry next time: the service may just be starting
            throw new Error(t.service + ' is not served by ' + t.consul + (data && data.error ? ' (' + data.error + ')' : ''));
          }
          var m = (svc.methods || []).filter(function (x) { return x.name === t.method; })[0];
          if (!m) throw new Error(t.method + ' is not a method of ' + t.service);
          return m;
        });
      },

      signals: {
        /**
         * Live values of signal names: cb(name, value, ts), at most 10 Hz.
         * Returns unsubscribe(); throws CapabilityDenied when the manifest
         * did not declare signals.subscribe. Kinds unsubscribe on suspend (R5).
         */
        subscribe: function (names, cb) {
          if (!caps['signals.subscribe']) throw deniedError('signals.subscribe');
          var off = MM.endo.bus.subscribe(names, cb);
          var offStatus = cb.onStatus ? MM.endo.bus.onStatus(names, cb.onStatus) : function () {};
          open++;
          var done = false;
          return function unsubscribe() {
            if (done) return;
            done = true;
            open--;
            off();
            offStatus();
          };
        },
        /** Write a setpoint on the service that owns it. */
        set: function (name, value) {
          if (!caps['signals.set']) return denied('signals.set');
          return MM.endo.bus.set(name, value);
        }
      },

      // Stubs until the session manager and the configuration service exist.
      session: {
        current: function () {
          if (!caps['session.read']) return denied('session.read');
          return Promise.resolve(null);
        },
        label: function (labels) {
          if (!caps['session.label']) return denied('session.label');
          console.info('[endo] ' + manifest.component + ' would label the session:', labels);
          return Promise.resolve({ stored: false });
        }
      },
      config: {
        get: function (scope, key) {
          if (!caps['config.read']) return denied('config.read');
          try { return Promise.resolve(JSON.parse(localStorage.getItem(configKey(scope, key)) || 'null')); }
          catch (e) { return Promise.resolve(null); }
        },
        put: function (scope, key, value) {
          if (!caps['config.write']) return denied('config.write');
          try { localStorage.setItem(configKey(scope, key), JSON.stringify(value)); } catch (e) { /* storage unavailable */ }
          return Promise.resolve({ stored: 'local' });
        }
      },

      /** Open signal subscriptions of this component (R5: 0 after suspend). */
      openSubscriptions: function () { return open; },

      confirm: function (message) {
        return new Promise(function (resolve) {
          if (MM.showConfirm) MM.showConfirm(message, function () { resolve(true); });
          else resolve(true);
        });
      },

      notify: function (kind, text) {
        if (MM.showToast) MM.showToast(manifest.title || manifest.component, text, kind || 'info');
      }
    };
  }

  function layerVar(layer) {
    var C = window.EndoContract;
    return C && C.LAYERS.indexOf(layer) >= 0 ? 'var(--l-' + layer + ')' : 'var(--l-runner)';
  }

  /** The n-th (1-based) bench piece colour; the six colours repeat. */
  var PIECE_COLOURS = 6;
  /** A component's groups, in their order: shades of its colour (the
      fill's tone and strength), so neighbouring groups of one component
      differ while their outlines keep the component's colour. */
  var PIECE_SHADES = [
    { mix: '', tint: '16%' },
    { mix: 'white 40%', tint: '24%' },
    { mix: 'black 25%', tint: '13%' },
    { mix: 'white 15%', tint: '30%' }
  ];
  function pieceVar(n) {
    return 'var(--piece-' + (((Math.max(1, Math.floor(n)) - 1) % PIECE_COLOURS) + 1) + ')';
  }

  function headerHtml(manifest, issues, env) {
    var warns = issues.filter(function (i) { return i.severity === 'warn'; });
    var errs = issues.filter(function (i) { return i.severity === 'error'; });
    var badge = errs.length
      ? '<span class="endo-lint bad">refused · ' + errs.length + ' error' + (errs.length > 1 ? 's' : '') + '</span>'
      : warns.length
        ? '<span class="endo-lint warn">contract v1 · ' + warns.length + ' warning' + (warns.length > 1 ? 's' : '') + '</span>'
        : '<span class="endo-lint ok">contract v1 · passes</span>';
    var list = issuesListHtml;
    return '<div class="endo-head">' +
      '<span class="endo-layer">' + esc(manifest.layer || '?') + '</span>' +
      '<h5>' + esc(manifest.title || manifest.component || 'Component') + '</h5>' +
      '<span class="endo-id">' + esc(manifest.component || '') + ' ' + esc(manifest.version || '') +
        ' · ' + esc(env.consulName || '') + '</span>' +
      badge +
      '</div>' +
      (warns.length && !errs.length ? '<details class="endo-warns"><summary>Warnings</summary>' + list(warns) + '</details>' : '') +
      (errs.length ? '<div class="endo-refused" role="alert"><strong>The shell refused this component.</strong> ' +
        'Its slot stays here so the reason is visible (R10). Fix these and reload:' + list(errs) + '</div>' : '');
  }

  function tileClasses(size) {
    var s = (window.EndoContract && window.EndoContract.SIZES[size]) || [2, 1];
    return 'endo-tile w' + s[0] + ' h' + s[1];
  }

  /**
   * Lint a manifest (or the parse error of its file) and, when it passes,
   * build its capability-gated ctx.
   *
   * @returns {Promise<{manifest, issues, ok, ctx}>} ctx is null when refused
   */
  function prepareComponent(manifest, env) {
    env = env || {};
    // Plugin kinds must be registered before tiles are linted and drawn.
    var pluginsReady = MM.endo.plugins ? MM.endo.plugins.ready : Promise.resolve();
    return Promise.all([loadSchema(), pluginsReady]).then(function (r) {
      var schema = r[0];
      var C = window.EndoContract;
      var issues;
      if (manifest && manifest.__parseError) {
        issues = [{ rule: 'S', severity: 'error', component: '(component.json)', path: '(file)',
                    message: 'not valid JSON: ' + manifest.__parseError }];
        manifest = { title: 'component.json', layer: '?' };
      } else {
        issues = C.lintComponent(manifest, {
          schema: schema,
          kinds: MM.endo.plugins ? MM.endo.plugins.kindInfo() : {},   // active plugins: their schemas and needs
          knownPluginKinds: pluginKindOwners()
        });
        if (!schema) {
          issues.push({ rule: 'S', severity: 'warn', component: manifest.component || '?', path: '(schema)',
                        message: 'contract schema could not be loaded; only the rules were checked' });
        }
      }
      var ok = !C.hasErrors(issues);
      return { manifest: manifest, issues: issues, ok: ok, ctx: ok ? makeCtx(manifest, env) : null };
    });
  }

  /**
   * Render one tile of a component into a new <section>. A tile that fails
   * shows its error in place and the others keep working (R10).
   *
   * @param {object} tile - the manifest's tile
   * @param {object} ctx - from prepareComponent
   * @param {object} [opts] - { layer, source }: header colour and a label
   *   naming the component (the bench shows tiles of many components)
   * @returns {{section: HTMLElement, instance: object|null}}
   */
  function renderTile(tile, ctx, opts) {
    opts = opts || {};
    var section = document.createElement('section');
    section.className = tileClasses(tile.size);
    section.setAttribute('data-tile', tile.id);
    if (opts.layer) section.style.setProperty('--layer', layerVar(opts.layer));
    section.innerHTML =
      '<header class="endo-tile-head"><span class="t">' + esc(tile.title || tile.id) + '</span>' +
      '<span class="src">' + esc(opts.source || tile.kind) + '</span></header>' +
      '<div class="endo-tile-body"></div>';
    var body = section.querySelector('.endo-tile-body');
    var kind = MM.endo.kinds[tile.kind];
    if (!kind) {
      body.innerHTML = '<div class="endo-placeholder">' + missingKindHtml(tile.kind) + '</div>';
      return { section: section, instance: null };
    }
    var inst;
    try { inst = kind.render(body, tile, ctx); }
    catch (e) {
      body.innerHTML = '<div class="endo-error">' + esc(e.message) + '</div>';   // fail small (R10)
      return { section: section, instance: null };
    }
    if (inst && inst.refresh) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'endo-refresh';
      btn.title = 'Refresh';
      btn.setAttribute('aria-label', 'Refresh ' + (tile.title || tile.id));
      btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
      btn.addEventListener('click', function (ev) { ev.stopPropagation(); inst.refresh(); });
      section.querySelector('.endo-tile-head').appendChild(btn);
    }
    return { section: section, instance: inst || null };
  }

  /** suspend/resume/destroy over a list of tile instances; one failing never stops the rest. */
  function instanceGroup(instances) {
    function each(fn) {
      return function () { instances.forEach(function (i) { try { i[fn](); } catch (e) { /* keep going */ } }); };
    }
    return {
      suspend: each('suspend'),
      resume: each('resume'),
      destroy: function () { each('destroy')(); instances.length = 0; }
    };
  }

  // ------------------------------------------------------------ tile groups

  // Open/closed per scope, component and group, remembered per user. The
  // manifest's "collapsed" is only how a group starts.
  var GROUPS_KEY = 'mm_endo_groups';
  function groupPrefs() {
    try { return JSON.parse(localStorage.getItem(GROUPS_KEY) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function setGroupPref(key, open) {
    var prefs = groupPrefs();
    prefs[key] = open;
    try { localStorage.setItem(GROUPS_KEY, JSON.stringify(prefs)); } catch (e) { /* storage unavailable */ }
  }

  /**
   * A tile instance that runs only while its component is shown *and* its
   * group is open (R5): suspend/resume from the component, setOpen from the
   * group's header. A tile starts running, as rendered.
   */
  function gateInstance(inst) {
    var shown = true, open = true, running = true;
    function sync() {
      var want = shown && open;
      if (want === running) return;
      running = want;
      try { if (want) inst.resume(); else inst.suspend(); } catch (e) { /* fail small */ }
    }
    return {
      suspend: function () { shown = false; sync(); },
      resume: function () { shown = true; sync(); },
      destroy: function () { inst.destroy(); },
      refresh: inst.refresh,
      setOpen: function (v) { open = !!v; sync(); },
      isRunning: function () { return running; }
    };
  }

  /** A tile section's width and height in stage cells, from its w1..w4 and h1..h2 classes. */
  function tileCells(section) {
    var w = /\bw([124])\b/.exec(section.className), h = /\bh([12])\b/.exec(section.className);
    return [w ? +w[1] : 2, h ? +h[1] : 1];
  }

  /**
   * Rows that cells (each [w, h]) take when packed densely into `cols`
   * columns, as CSS grid's "row dense" places them: each item at the first
   * free spot, top to bottom, left to right. A cell wider than cols is cut
   * to cols, as the box's CSS does.
   */
  function packedRows(cells, cols) {
    var used = [];   // used[row][col]
    function free(r, c, w, h) {
      for (var y = r; y < r + h; y++) for (var x = c; x < c + w; x++) if (used[y] && used[y][x]) return false;
      return true;
    }
    var rows = 0;
    cells.forEach(function (cell) {
      var w = Math.min(cell[0], cols), h = cell[1];
      for (var r = 0; ; r++) {
        for (var c = 0; c + w <= cols; c++) {
          if (!free(r, c, w, h)) continue;
          for (var y = r; y < r + h; y++) {
            used[y] = used[y] || [];
            for (var x = c; x < c + w; x++) used[y][x] = true;
          }
          rows = Math.max(rows, r + h);
          return;
        }
      }
    });
    return Math.max(rows, 1);
  }

  /**
   * Put a component's tiles into the boxes of its "groups".
   *
   * A group is one box on the stage, as big as its tiles: its width the sum
   * of theirs up to the stage's 4 columns (or the group's "w"), its height
   * the rows they pack into. The box takes its columns and rows from the
   * stage (subgrid), so grouped and loose tiles line up, and the stage packs
   * boxes and loose tiles together. The box sits where the group's first
   * tile was. Collapsed, it shrinks to its title.
   *
   * @param {HTMLElement} stage - where the tiles' sections already are
   * @param {Array} entries - [{ tileId, section, instance }] of this component, in stage order
   * @param {Array} groups - the manifest's groups
   * With opts.shape (the bench), the tiles stay loose on the stage: the group
   * is a title tab and a mark on its tiles, and shapeStage() places them as
   * one connected piece and draws its outline, so groups of any shape fit
   * into each other like Tetris pieces.
   *
   * @param {object} opts - { scope, component, source, layer, piece, shape }: the key
   *   the open/closed choice is remembered under, a label for the title (the bench
   *   names the component), the layer whose color the box takes, the component's
   *   colour on the bench (1-6, the --piece-N tokens; else the layer colour), and
   *   the shaped layout
   * @returns {Array} the instances to run, in entries order: gated when grouped
   */
  function applyGroups(stage, entries, groups, opts) {
    opts = opts || {};
    // Keyed by ids from component.json: no inherited keys ("constructor", ...).
    var byTile = Object.create(null);
    (groups || []).forEach(function (g) {
      (g && Array.isArray(g.tiles) ? g.tiles : []).forEach(function (t) { if (!byTile[t]) byTile[t] = g; });
    });
    var state = Object.create(null);   // group id -> { open, members: [{ section, gate }], head }
    var out = entries.map(function (e) {
      var g = byTile[e.tileId];
      if (!g) return e.instance;
      var s = state[g.id];
      if (!s) {
        var key = (opts.scope || 'svc') + '|' + (opts.component || '') + '|' + g.id;
        var pref = groupPrefs()[key];
        s = state[g.id] = { key: key, open: pref === undefined ? !g.collapsed : !!pref, members: [], group: g,
                            shape: !!opts.shape, stage: stage };
        s.head = groupBox(g, opts.source, s.shape);
        if (s.shape) s.head.setAttribute('data-group-key', key);
        if (opts.layer) s.head.style.setProperty('--layer', layerVar(opts.layer));
        if (opts.piece) {
          // The component's colour, in a shade of its own for each group.
          var shade = PIECE_SHADES[groups.indexOf(g) % PIECE_SHADES.length];
          s.head.style.setProperty('--piece', pieceVar(opts.piece));
          s.head.style.setProperty('--piece-tone', shade.mix ? 'color-mix(in oklab, ' + pieceVar(opts.piece) + ', ' + shade.mix + ')' : pieceVar(opts.piece));
          s.head.style.setProperty('--piece-tint', shade.tint);
        }
        stage.insertBefore(s.head, e.section);   // the box goes where the group's first tile is
        s.head.querySelector('button').addEventListener('click', function () {
          s.open = !s.open;
          setGroupPref(s.key, s.open);
          showGroup(s);
        });
      }
      var gate = e.instance ? gateInstance(e.instance) : null;
      if (s.shape) e.section.setAttribute('data-group-key', s.key);
      else s.head.appendChild(e.section);   // into the box, in the component's order
      s.members.push({ section: e.section, gate: gate });
      return gate;
    });
    if (Object.keys(state).length) stage.classList.add('grouped');
    Object.keys(state).forEach(function (id) {
      var s = state[id];
      s.head.querySelector('.n').textContent = s.members.length + (s.members.length === 1 ? ' tile' : ' tiles');
      if (!s.shape) sizeGroup(s);
      showGroup(s);
    });
    return out;
  }

  function groupBox(g, source, shape) {
    var box = document.createElement('div');
    box.className = shape ? 'endo-group-tab' : 'endo-group';
    box.setAttribute('data-group', g.id);
    box.setAttribute('role', 'group');
    box.innerHTML = '<div class="endo-group-head"><button type="button" class="endo-group-toggle" aria-expanded="true">' +
      '<i class="bi bi-chevron-down" aria-hidden="true"></i>' +
      '<span class="t">' + esc(g.title || g.id) + '</span>' +
      (source ? '<span class="src">' + esc(source) + '</span>' : '') +
      '<span class="n"></span></button></div>';
    box.setAttribute('aria-label', g.title || g.id);
    return box;
  }

  /**
   * The box's columns and rows for each stage width the CSS knows (4, 2 and
   * 1 columns), as custom properties: --gw4/--gr4, --gw2/--gr2, --gr1.
   */
  function sizeGroup(s) {
    var cells = s.members.map(function (m) { return tileCells(m.section); });
    var sum = cells.reduce(function (a, c) { return a + c[0]; }, 0);
    var widest = cells.reduce(function (a, c) { return Math.max(a, c[0]); }, 1);
    var w4 = s.group.w >= 1 && s.group.w <= 4 ? Math.floor(s.group.w) : Math.min(4, Math.max(sum, widest));
    var w2 = Math.min(w4, 2);
    s.head.classList.add('gw' + w4);
    s.head.style.setProperty('--gw4', w4);
    s.head.style.setProperty('--gr4', packedRows(cells, w4));
    s.head.style.setProperty('--gw2', w2);
    s.head.style.setProperty('--gr2', packedRows(cells, w2));
    s.head.style.setProperty('--gr1', packedRows(cells, 1));
  }

  function showGroup(s) {
    s.head.classList.toggle('collapsed', !s.open);
    s.head.querySelector('button').setAttribute('aria-expanded', s.open ? 'true' : 'false');
    s.members.forEach(function (m) {
      m.section.hidden = !s.open;
      if (m.gate) m.gate.setOpen(s.open);
    });
    if (s.shape) s.stage.dispatchEvent(new CustomEvent('endo:relayout'));
  }

  // ------------------------------------------------------------ shaped groups (the bench)

  /**
   * Where each item goes on a grid of `cols` columns: [{ r, c, w, h }] in
   * items order. items: [{ w, h, group }]; group is null for a loose item.
   *
   * A loose item takes the first free spot, top to bottom, left to right.
   * A group is placed as one connected piece the first time one of its items
   * comes up: its first item at every free spot in turn, each next item at
   * the first free spot touching the piece; the spot whose piece ends
   * highest wins (as in Tetris, the stack stays low), the earlier on a tie.
   * A piece may take any shape, and later items fill its notches.
   */
  function packShapes(items, cols) {
    var used = Object.create(null);   // "r,c" -> true
    var rows = 0;
    var out = new Array(items.length);
    function free(u, r, c, w, h) {
      if (c < 0 || c + w > cols || r < 0) return false;
      for (var y = r; y < r + h; y++) for (var x = c; x < c + w; x++) if (u[y + ',' + x]) return false;
      return true;
    }
    function take(u, r, c, w, h) {
      for (var y = r; y < r + h; y++) for (var x = c; x < c + w; x++) u[y + ',' + x] = true;
    }
    function touches(mine, r, c, w, h) {
      for (var x = c; x < c + w; x++) if (mine[(r - 1) + ',' + x] || mine[(r + h) + ',' + x]) return true;
      for (var y = r; y < r + h; y++) if (mine[y + ',' + (c - 1)] || mine[y + ',' + (c + w)]) return true;
      return false;
    }
    function firstFree(u, w, h, maxRow, mine) {
      for (var r = 0; r <= maxRow; r++) {
        for (var c = 0; c + w <= cols; c++) {
          if (free(u, r, c, w, h) && (!mine || touches(mine, r, c, w, h))) return { r: r, c: c };
        }
      }
      return null;
    }
    function dims(it) { return { w: Math.min(Math.max(it.w, 1), cols), h: Math.max(it.h, 1) }; }

    var done = Object.create(null);
    items.forEach(function (it, i) {
      if (it.group == null) {
        var d = dims(it);
        var p = firstFree(used, d.w, d.h, rows);
        take(used, p.r, p.c, d.w, d.h);
        out[i] = { r: p.r, c: p.c, w: d.w, h: d.h };
        rows = Math.max(rows, p.r + d.h);
        return;
      }
      if (done[it.group]) return;
      done[it.group] = true;
      var idx = [];
      items.forEach(function (o, j) { if (o.group === it.group) idx.push(j); });
      var sizes = idx.map(function (j) { return dims(items[j]); });
      var tall = sizes.reduce(function (a, d) { return a + d.h; }, 0);
      var best = null;
      for (var r0 = 0; r0 <= rows; r0++) {
        for (var c0 = 0; c0 + sizes[0].w <= cols; c0++) {
          if (!free(used, r0, c0, sizes[0].w, sizes[0].h)) continue;
          var u = Object.create(used), mine = Object.create(null), spots = [], bottom = 0;
          var ok = sizes.every(function (d, k) {
            var p = k === 0 ? { r: r0, c: c0 } : firstFree(u, d.w, d.h, r0 + tall + 1, mine);
            if (!p) return false;
            take(u, p.r, p.c, d.w, d.h);
            take(mine, p.r, p.c, d.w, d.h);
            spots.push({ r: p.r, c: p.c, w: d.w, h: d.h });
            bottom = Math.max(bottom, p.r + d.h);
            return true;
          });
          if (ok && (!best || bottom < best.bottom)) best = { bottom: bottom, spots: spots };
        }
      }
      best.spots.forEach(function (s, k) {
        take(used, s.r, s.c, s.w, s.h);
        out[idx[k]] = s;
      });
      rows = Math.max(rows, best.bottom);
    });
    return out;
  }

  /**
   * The outline of a union of rectangles ([x0, y0, x1, y1]) that touch or
   * overlap, as an SVG path: one closed loop per edge ring, clockwise.
   */
  function outlinePath(rects) {
    // Edges closer than 1.5px are one edge: two tiles' half-gaps meet with
    // sub-pixel rounding, and must not leave a sliver between them.
    function snapper(vals) {
      var sorted = vals.slice().sort(function (p, q) { return p - q; }), keep = [];
      sorted.forEach(function (v) { if (!keep.length || v - keep[keep.length - 1] > 1.5) keep.push(v); });
      return function (v) { return keep.reduce(function (a, k) { return Math.abs(k - v) < Math.abs(a - v) ? k : a; }, keep[0]); };
    }
    var sx = snapper([].concat.apply([], rects.map(function (r) { return [r[0], r[2]]; })));
    var sy = snapper([].concat.apply([], rects.map(function (r) { return [r[1], r[3]]; })));
    rects = rects.map(function (r) { return [sx(r[0]), sy(r[1]), sx(r[2]), sy(r[3])]; });
    function uniq(a) { return a.sort(function (p, q) { return p - q; }).filter(function (v, i) { return i === 0 || v !== a[i - 1]; }); }
    var xs = uniq([].concat.apply([], rects.map(function (r) { return [r[0], r[2]]; })));
    var ys = uniq([].concat.apply([], rects.map(function (r) { return [r[1], r[3]]; })));
    function inside(i, j) {
      if (i < 0 || j < 0 || i >= xs.length - 1 || j >= ys.length - 1) return false;
      var cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2;
      return rects.some(function (r) { return cx > r[0] && cx < r[2] && cy > r[1] && cy < r[3]; });
    }
    var edges = [];   // [x0, y0, x1, y1], clockwise around the covered cells
    for (var i = 0; i < xs.length - 1; i++) {
      for (var j = 0; j < ys.length - 1; j++) {
        if (!inside(i, j)) continue;
        if (!inside(i, j - 1)) edges.push([xs[i], ys[j], xs[i + 1], ys[j]]);
        if (!inside(i + 1, j)) edges.push([xs[i + 1], ys[j], xs[i + 1], ys[j + 1]]);
        if (!inside(i, j + 1)) edges.push([xs[i + 1], ys[j + 1], xs[i], ys[j + 1]]);
        if (!inside(i - 1, j)) edges.push([xs[i], ys[j + 1], xs[i], ys[j]]);
      }
    }
    var from = Object.create(null);
    edges.forEach(function (e) { (from[e[0] + ',' + e[1]] = from[e[0] + ',' + e[1]] || []).push(e); });
    var left = edges.length, d = '';
    edges.forEach(function (start) {
      if (start.used) return;
      var pts = [[start[0], start[1]]], e = start;
      while (e && !e.used) {
        e.used = true; left--;
        pts.push([e[2], e[3]]);
        e = (from[e[2] + ',' + e[3]] || []).filter(function (n) { return !n.used; })[0];
      }
      // Drop the points in the middle of a straight run.
      var keep = pts.filter(function (p, k) {
        if (k === 0 || k === pts.length - 1) return true;
        var a = pts[k - 1], b = pts[k + 1];
        return !((a[0] === p[0] && p[0] === b[0]) || (a[1] === p[1] && p[1] === b[1]));
      });
      d += 'M' + keep.map(function (p) { return p[0] + ' ' + p[1]; }).join('L') + 'Z';
    });
    return d;
  }

  var shapeIds = 0;

  /**
   * Lay out a stage whose groups were applied with opts.shape: place every
   * shown item (packShapes), draw each open group's outline around its
   * tiles in the stage's gaps, and put its title tab on the outline's top
   * edge. Lays out again when the stage changes width (its column count
   * may change) or height (a tile grew), and when a group opens or closes.
   *
   * @returns {{ suspend, resume, destroy }} an instance for the stage's instanceGroup
   */
  function shapeStage(stage) {
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'endo-shapes');
    svg.setAttribute('aria-hidden', 'true');
    stage.insertBefore(svg, stage.firstChild);
    stage.classList.add('shaped');
    var id = 'endo-shape-' + (++shapeIds);
    var lastCols = 0, frame = 0, live = true;

    function items() {
      return [].filter.call(stage.children, function (el) {
        if (el === svg || el.hidden) return false;
        return !(el.classList.contains('endo-group-tab') && !el.classList.contains('collapsed'));
      });
    }
    // The declared column count (--cols beside each grid-template-columns in
    // endo.css): the computed track list also counts the implicit columns
    // our own placement made. 0 while the stage is not shown.
    function cols() {
      if (!stage.offsetWidth) return 0;
      return parseInt(getComputedStyle(stage).getPropertyValue('--cols'), 10) || 4;
    }
    function place() {
      var n = cols();
      if (!n) return false;
      lastCols = n;
      // An open group's tab is drawn on the outline, not placed in the grid.
      [].forEach.call(stage.querySelectorAll(':scope > .endo-group-tab:not(.collapsed)'), function (tab) {
        tab.style.gridColumn = tab.style.gridRow = '';
      });
      var els = items();
      var spots = packShapes(els.map(function (el) {
        var tab = el.classList.contains('endo-group-tab');
        var cells = tab ? [1, 1] : tileCells(el);
        return { w: cells[0], h: cells[1], group: tab ? null : el.getAttribute('data-group-key') };
      }), n);
      els.forEach(function (el, i) {
        var s = spots[i];
        el._endoSpot = s;
        el.style.gridColumn = (s.c + 1) + ' / span ' + s.w;
        el.style.gridRow = (s.r + 1) + ' / span ' + s.h;
      });
      return true;
    }
    function draw() {
      var cs = getComputedStyle(stage);
      var cg = parseFloat(cs.columnGap) || 0, rg = parseFloat(cs.rowGap) || 0;
      // The grid's tracks as laid out: a piece is drawn around the cells its
      // tiles were given, not around the tiles (a tile may be shorter than its row).
      function edges(list, gap, start) {
        var at = [start];
        (list || '').trim().split(/\s+/).forEach(function (t) { at.push(at[at.length - 1] + (parseFloat(t) || 0) + gap); });
        return at;   // at[i] = where track i starts; at[i + 1] - gap = where it ends
      }
      var xs = edges(cs.gridTemplateColumns, cg, parseFloat(cs.paddingLeft) || 0);
      var ys = edges(cs.gridTemplateRows, rg, parseFloat(cs.paddingTop) || 0);
      function edge(at, i) { return at[Math.min(i, at.length - 1)]; }
      svg.setAttribute('width', stage.scrollWidth);
      svg.setAttribute('height', stage.scrollHeight);
      var groups = Object.create(null), order = [];
      [].forEach.call(stage.querySelectorAll(':scope > [data-group-key]:not(.endo-group-tab)'), function (el) {
        var s = el._endoSpot;
        if (el.hidden || !s) return;
        var k = el.getAttribute('data-group-key');
        if (!groups[k]) { groups[k] = []; order.push(k); }
        groups[k].push([edge(xs, s.c) - cg / 2, edge(ys, s.r) - rg / 2,
                        edge(xs, s.c + s.w) - cg / 2, edge(ys, s.r + s.h) - rg / 2]);
      });
      var html = '';
      order.forEach(function (k, n) {
        var tab = stage.querySelector(':scope > .endo-group-tab[data-group-key="' + cssEsc(k) + '"]');
        var layer = tab ? tab.style.getPropertyValue('--layer') : '';
        var piece = '';
        if (tab) ['--piece', '--piece-tone', '--piece-tint'].forEach(function (v) {
          var val = tab.style.getPropertyValue(v);
          if (val) piece += ';' + v + ':' + val;
        });
        var d = outlinePath(groups[k].map(function (r) { return r.map(function (v) { return Math.round(v * 2) / 2; }); }));
        var m = id + '-' + n;
        // The mask keeps the inside of the outline, 2px in from it, so two
        // pieces side by side keep a gap between their lines.
        html += '<g style="--layer:' + esc(layer) + esc(piece) + '">' +
          '<mask id="' + m + '" maskUnits="userSpaceOnUse"><path d="' + d + '" fill="#fff"/>' +
          '<path d="' + d + '" fill="none" stroke="#000" stroke-width="4" stroke-linejoin="round"/></mask>' +
          '<path class="fill" d="' + d + '" mask="url(#' + m + ')"/>' +
          '<path class="line" d="' + d + '" fill="none" stroke-width="7" stroke-linejoin="round" mask="url(#' + m + ')"/></g>';
        if (tab) {
          // The title on the piece's top edge, at its top-left tile.
          var top = groups[k].reduce(function (a, r) { return !a || r[1] < a[1] || (r[1] === a[1] && r[0] < a[0]) ? r : a; }, null);
          tab.style.left = (top[0] + 6) + 'px';
          tab.style.top = (top[1] + 2 - tab.offsetHeight / 2) + 'px';
        }
      });
      svg.innerHTML = html;
    }
    function layout() {
      frame = 0;
      if (!live || !stage.isConnected) return;
      if (place()) draw();
    }
    function schedule() { if (!frame && live) frame = requestAnimationFrame(layout); }

    var ro = typeof ResizeObserver === 'function' ? new ResizeObserver(function () {
      if (cols() !== lastCols) schedule();
      else if (!frame) frame = requestAnimationFrame(function () { frame = 0; if (live) draw(); });
    }) : null;
    if (ro) ro.observe(stage);
    // A group opened or closed: lay out now, so no frame shows the old layout.
    function relayout() { if (frame) { cancelAnimationFrame(frame); frame = 0; } layout(); }
    stage.addEventListener('endo:relayout', relayout);
    layout();

    return {
      suspend: function () {},
      resume: schedule,
      relayout: layout,
      destroy: function () {
        live = false;
        if (ro) ro.disconnect();
        if (frame) cancelAnimationFrame(frame);
        stage.removeEventListener('endo:relayout', relayout);
      }
    };
  }

  function cssEsc(s) {
    return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&');
  }

  function issuesListHtml(arr) {
    return '<ul class="endo-issues">' + arr.map(function (i) {
      return '<li><b>' + esc(i.rule) + '</b> <code>' + esc(i.path) + '</code> ' + esc(i.message) + '</li>';
    }).join('') + '</ul>';
  }

  function mountComponent(manifest, el, env) {
    env = env || {};
    return prepareComponent(manifest, env).then(function (prep) {
      el.innerHTML = '';
      var root = document.createElement('div');
      root.className = 'endo-comp';
      root.style.setProperty('--layer', layerVar(prep.manifest.layer));
      root.innerHTML = headerHtml(prep.manifest, prep.issues, env);
      el.appendChild(root);

      var instances = [];
      var handle = instanceGroup(instances);
      handle.issues = prep.issues;
      if (!prep.ok) return handle;

      var stage = document.createElement('div');
      stage.className = 'endo-stage';
      root.appendChild(stage);
      var entries = (prep.manifest.tiles || []).map(function (tile) {
        var r = renderTile(tile, prep.ctx);
        stage.appendChild(r.section);
        return { tileId: tile.id, section: r.section, instance: r.instance };
      });
      applyGroups(stage, entries, prep.manifest.groups, { scope: 'svc', component: prep.manifest.component })
        .forEach(function (inst) { if (inst) instances.push(inst); });
      return handle;
    });
  }

  MM.endo.mountComponent = mountComponent;
  MM.endo.prepareComponent = prepareComponent;
  MM.endo.renderTile = renderTile;
  MM.endo.instanceGroup = instanceGroup;
  MM.endo.applyGroups = applyGroups;
  MM.endo.shapeStage = shapeStage;
  MM.endo.packShapes = packShapes;
  MM.endo.outlinePath = outlinePath;
  MM.endo.issuesListHtml = issuesListHtml;
  MM.endo.layerVar = layerVar;
  MM.endo.pieceVar = pieceVar;
  MM.endo.KNOWN_PLUGIN_KINDS = KNOWN_PLUGIN_KINDS;
  MM.endo.loadSchema = loadSchema;
  /** Exposed for plugin kinds (M4) and tests: the capability-gated context. */
  MM.endo.makeCtx = makeCtx;
})();
