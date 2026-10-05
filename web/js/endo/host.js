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
    var methodsP = null;
    var open = 0;
    var callWatchers = [];
    // One binary may serve several proto services: the first is the default,
    // the others are called as "<service>/<Method>".
    var services = [].concat(binds.grpc || []);

    function target(method) {
      var s = String(method || '');
      var i = s.lastIndexOf('/');
      if (i < 0) return { service: services[0], method: s };
      var svc = s.slice(0, i);
      if (services.indexOf(svc) < 0) {
        var e = new Error('NotBound: ' + svc + ' is not in binds.grpc');
        e.code = 'NotBound';
        throw e;
      }
      return { service: svc, method: s.slice(i + 1) };
    }

    return {
      component: manifest.component,
      consulName: consulName,
      /** URL of the component (or plugin) folder: where frame tiles find their pages. */
      base: env.base || '',

      /** The proto services this component may call (binds.grpc; the first is the default). */
      services: services.slice(),

      call: function (method, args) {
        if (!caps['grpc.call']) return denied('grpc.call');
        var t;
        try { t = target(method); } catch (e) { return Promise.reject(e); }
        return MM.grpcClient.callMethod({
          consulName: consulName,
          consulUrl: env.consulUrl,
          grpcService: t.service,
          method: t.method,
          argsJson: JSON.stringify(args || {}),
          protoPath: env.protoPath
        }).then(function (d) {
          if (!d || !d.ok) throw new Error((d && d.error) || (method + ' failed'));
          callWatchers.slice().forEach(function (fn) {
            try { fn(method, args || {}); } catch (e) { console.warn('[endo] onCall watcher failed:', e); }
          });
          return d;
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
        methodsP = methodsP || MM.grpcClient.getServiceMethods(consulName, env.consulUrl, env.protoPath);
        return methodsP.then(function (data) {
          var svc = ((data && data.grpc_services) || []).filter(function (s) { return s.name === t.service; })[0];
          if (!svc) {
            methodsP = null;   // retry next time: the service may just be starting
            throw new Error(t.service + ' is not served by ' + consulName + (data && data.error ? ' (' + data.error + ')' : ''));
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

  /**
   * Put a component's tiles under the headers of its "groups".
   *
   * @param {HTMLElement} stage - where the tiles' sections already are
   * @param {Array} entries - [{ tileId, section, instance }] of this component, in stage order
   * @param {Array} groups - the manifest's groups
   * @param {object} opts - { scope, component, source }: the key the open/closed choice is
   *   remembered under, and a label for the header (the bench names the component)
   * @returns {Array} the instances to run, in entries order: gated when grouped
   */
  function applyGroups(stage, entries, groups, opts) {
    opts = opts || {};
    var byTile = {};
    (groups || []).forEach(function (g) {
      (g && Array.isArray(g.tiles) ? g.tiles : []).forEach(function (t) { if (!byTile[t]) byTile[t] = g; });
    });
    var state = {};   // group id -> { open, members: [{ section, gate }], head }
    var out = entries.map(function (e) {
      var g = byTile[e.tileId];
      if (!g) return e.instance;
      var s = state[g.id];
      if (!s) {
        var key = (opts.scope || 'svc') + '|' + (opts.component || '') + '|' + g.id;
        var pref = groupPrefs()[key];
        s = state[g.id] = { key: key, open: pref === undefined ? !g.collapsed : !!pref, members: [] };
        s.head = groupHead(g, opts.source);
        stage.insertBefore(s.head, e.section);   // the header goes where the group's first tile is
        s.head.querySelector('button').addEventListener('click', function () {
          s.open = !s.open;
          setGroupPref(s.key, s.open);
          showGroup(s);
        });
      }
      var gate = e.instance ? gateInstance(e.instance) : null;
      s.members.push({ section: e.section, gate: gate });
      return gate;
    });
    if (Object.keys(state).length) stage.classList.add('grouped');
    Object.keys(state).forEach(function (id) {
      var s = state[id];
      s.head.querySelector('.n').textContent = s.members.length + (s.members.length === 1 ? ' tile' : ' tiles');
      showGroup(s);
    });
    return out;
  }

  function groupHead(g, source) {
    var head = document.createElement('div');
    head.className = 'endo-group';
    head.setAttribute('data-group', g.id);
    head.innerHTML = '<button type="button" class="endo-group-toggle" aria-expanded="true">' +
      '<i class="bi bi-chevron-down" aria-hidden="true"></i>' +
      '<span class="t">' + esc(g.title || g.id) + '</span>' +
      (source ? '<span class="src">' + esc(source) + '</span>' : '') +
      '<span class="n"></span></button>';
    return head;
  }

  function showGroup(s) {
    s.head.classList.toggle('collapsed', !s.open);
    s.head.querySelector('button').setAttribute('aria-expanded', s.open ? 'true' : 'false');
    s.members.forEach(function (m) {
      m.section.hidden = !s.open;
      if (m.gate) m.gate.setOpen(s.open);
    });
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
  MM.endo.issuesListHtml = issuesListHtml;
  MM.endo.layerVar = layerVar;
  MM.endo.KNOWN_PLUGIN_KINDS = KNOWN_PLUGIN_KINDS;
  MM.endo.loadSchema = loadSchema;
  /** Exposed for plugin kinds (M4) and tests: the capability-gated context. */
  MM.endo.makeCtx = makeCtx;
})();
