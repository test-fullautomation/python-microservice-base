/**
 * @fileoverview Bench Endoskeleton bench view (milestone M2): one stage
 * composed from the components of many services.
 *
 * A composition (composition.js) lists services; each service's GUI folder
 * is resolved to a module: a component.json that is linted and mounted, or
 * a slot that says why nothing is mounted (refused, classic panel, no GUI,
 * not registered). Around the stage:
 *
 *   navigator     left pane (#benchNav): the modules, click to select
 *   dock          right of the stage: details / API of the selected tile
 *   status strip  below the stage: one badge per module
 *   ribbon        components' ribbon[] groups on their tab while the bench shows
 *
 * app.js owns the view switching and passes what the bench needs through
 * MM.endo.bench.init(hooks):
 *   getServices()                  -> [{ name, consulUrl, gui, address, port, status, tags }]
 *   openService(svc, { classic })  show the service in the Services view
 *   openInspector(svc, tab)        Services view + developer inspector on tab
 *   showApi(svc, containerId)      render the API explorer into a container
 *   protoPathFor(name)             stored .proto folder for a service
 *   setRibbonTab(tab)              select a ribbon tab
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};

  var SEL_KEY = 'mm_bench_selection';
  var COMPOSITION_SCHEMA_URL = 'js/endo/contract/composition.schema.json';
  var ROLE_LABEL = { user: 'User', dev: 'Developer', admin: 'Administrator' };
  var STATE_LABEL = {
    ok: 'ok', refused: 'refused', legacy: 'classic panel', nogui: 'no GUI',
    missing: 'not registered', error: 'unavailable'
  };

  var hooks = {};
  var state = {
    selection: null,     // { bench, role } of a stored composition, or null = all components
    comp: null,          // the composition shown
    stored: false,       // comp came from the store
    note: '',            // why the default is shown (bridge down, ...)
    compIssues: [],
    modules: [],
    slots: [],
    group: null,         // instanceGroup of every mounted tile
    selectedKey: null,
    active: false,
    dirty: true,
    signature: '',
    token: 0,
    list: [],            // stored compositions, for the picker
    dir: ''
  };

  function esc(s) { return MM.endo.util.esc(s); }
  function C() { return window.EndoContract; }
  function K() { return window.EndoComposition; }

  // ------------------------------------------------------------ bridge

  function bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    return origin && origin.indexOf('http') === 0 ? origin : 'http://localhost:1112';
  }

  function api(method, path, body) {
    return fetch(bridgeOrigin() + path, {
      method: method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined
    }).catch(function () {
      var e = new Error('Bridge not running on ' + bridgeOrigin() + '. Start it from the User tab.');
      e.code = 'bridge_down';
      throw e;
    }).then(function (res) {
      if (res.status === 404) {
        var old = new Error('The running bridge has no composition store yet. Restart the bridge so it loads the current code.');
        old.code = 'bridge_old';
        throw old;
      }
      return res.json().then(function (data) {
        if (!res.ok || (data && data.status === 'error')) {
          var err = new Error((data && (data.error || data.detail)) || ('HTTP ' + res.status));
          err.code = data && data.code;
          throw err;
        }
        return data;
      });
    });
  }

  var compositionSchemaP = null;
  function loadCompositionSchema() {
    if (!compositionSchemaP) {
      compositionSchemaP = fetch(COMPOSITION_SCHEMA_URL)
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .catch(function () { compositionSchemaP = null; return null; });
    }
    return compositionSchemaP;
  }

  function lintComp(comp) {
    return loadCompositionSchema().then(function (schema) {
      return C().lintComposition(comp, { schema: schema });
    });
  }

  // ------------------------------------------------------------ selection

  function readSelection() {
    try {
      var v = JSON.parse(localStorage.getItem(SEL_KEY) || 'null');
      if (v && v.bench && K().ROLES.indexOf(v.role) >= 0) return { bench: v.bench, role: v.role };
    } catch (e) { /* storage unavailable */ }
    return null;
  }

  function writeSelection(sel) {
    try { localStorage.setItem(SEL_KEY, JSON.stringify(sel)); } catch (e) { /* storage unavailable */ }
  }

  function services() { return (hooks.getServices && hooks.getServices()) || []; }

  function signatureOf(list) {
    return list.map(function (s) {
      return [s.name, s.gui, s.consulUrl, s.address, s.port].join('|');
    }).sort().join('\n');
  }

  // ------------------------------------------------------------ loading

  /** Fetch the selected composition (or build the default) and render it. */
  function reload() {
    var sel = state.selection;
    var svc = services();
    var done = function (comp, stored, note) {
      state.comp = comp;
      state.stored = stored;
      state.note = note || '';
      return render();
    };
    if (!sel) return done(K().defaultComposition(svc, 'default', 'user'), false, '');
    return api('GET', '/api/ui/compositions/' + encodeURIComponent(sel.bench) + '/' + encodeURIComponent(sel.role))
      .then(function (data) { return done(data.composition, true, ''); })
      .catch(function (err) {
        var note = err.code === 'not_found'
          ? 'No composition is stored for ' + sel.bench + '/' + sel.role + '; showing all components.'
          : err.message + ' Showing all components.';
        return done(K().defaultComposition(svc, sel.bench, sel.role), false, note);
      });
  }

  function refreshList() {
    return api('GET', '/api/ui/compositions').then(function (data) {
      state.list = data.compositions || [];
      state.dir = data.dir || '';
    }, function () { state.list = []; }).then(renderPicker);
  }

  function fetchManifest(folder) {
    var base = (MM.SERVICES_GUI_FOLDER || 'services') + '/' + folder;
    return fetch(base + '/component.json', { cache: 'no-store' })
      .then(function (r) {
        if (r.status === 404) return { missing: true };
        if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + base + '/component.json');
        return r.text().then(function (text) {
          try { return { manifest: JSON.parse(text) }; } catch (e) { return { manifest: { __parseError: e.message } }; }
        });
      }, function (err) {
        // file:// in Electron reports a missing file as a network error.
        return { missing: true, error: err };
      });
  }

  /** Resolve every entry to a module and prepare the components. */
  function resolveModules(comp) {
    var entries = K().resolveEntries(comp, services());
    return Promise.all(entries.map(function (r) {
      var mod = { index: r.index, entry: r.entry, service: r.service, folder: r.folder, state: r.problem,
                  manifest: null, issues: [], ctx: null, warnings: [] };
      if (r.problem) return mod;
      return fetchManifest(r.folder).then(function (res) {
        if (res.missing) { mod.state = 'legacy'; return mod; }
        var svc = r.service;
        return MM.endo.prepareComponent(res.manifest, {
          consulName: svc.name,
          consulUrl: svc.consulUrl,
          protoPath: hooks.protoPathFor ? hooks.protoPathFor(svc.name) : ''
        }).then(function (prep) {
          mod.manifest = prep.manifest;
          mod.issues = prep.issues;
          mod.ctx = prep.ctx;
          mod.state = prep.ok ? 'ok' : 'refused';
          return mod;
        });
      }).catch(function (err) {
        mod.state = 'error';
        mod.error = err.message || String(err);
        return mod;
      });
    })).then(function (mods) {
      // Two services must not bring the same component id (R8).
      var seen = {};
      mods.forEach(function (m) {
        if (m.state !== 'ok') return;
        var id = m.manifest.component;
        if (seen[id]) {
          m.state = 'refused';
          m.issues = m.issues.concat([{ rule: 'R8', severity: 'error', component: id, path: 'component',
            message: 'duplicate component id on this bench (also from ' + seen[id] + ')' }]);
          m.ctx = null;
        } else {
          seen[id] = m.service.name;
        }
      });
      return mods;
    });
  }

  // ------------------------------------------------------------ rendering

  function root() { return document.getElementById('benchContent'); }

  function teardown() {
    if (state.group) state.group.destroy();
    state.group = null;
    closeDrawerInstance();
    destroyDockInstance();
    removeRibbonGroups();
  }

  // ------------------------------------------------------------ selection (for plugins)

  var selectionListeners = [];

  /** What the selected tile shows: plugins' drawer tabs and dock sections read this. */
  function selectionInfo() {
    var slot = state.slots.filter(function (s) { return s.key === state.selectedKey; })[0];
    if (!slot) return null;
    var mod = slot.module, m = mod.manifest || {}, t = slot.tile || {};
    var signals = [];
    (t.fields || []).forEach(function (f) { if (f.signal && signals.indexOf(f.signal) < 0) signals.push(f.signal); });
    (t.signals || []).forEach(function (n) { if (signals.indexOf(n) < 0) signals.push(n); });
    return { key: slot.key, component: m.component || slot.component, title: (t.title || m.title || slot.component),
             layer: m.layer || '', tile: slot.tile || null, service: mod.entry && mod.entry.service, signals: signals };
  }

  function emitSelection() {
    var sel = selectionInfo();
    selectionListeners.slice().forEach(function (fn) { try { fn(sel); } catch (e) { console.warn('[bench] selection listener:', e); } });
  }

  function selectionCtx() {
    return {
      selection: selectionInfo,
      onSelection: function (fn) {
        selectionListeners.push(fn);
        return function () { selectionListeners = selectionListeners.filter(function (f) { return f !== fn; }); };
      }
    };
  }

  // ------------------------------------------------------------ drawer (plugins' drawer tabs)

  var drawer = { key: null, inst: null, token: 0 };

  function closeDrawerInstance() {
    drawer.token++;
    if (drawer.inst && drawer.inst.destroy) { try { drawer.inst.destroy(); } catch (e) { /* keep going */ } }
    drawer.inst = null;
  }

  function drawDrawer() {
    var box = document.getElementById('benchDrawer');
    if (!box) return;
    var tabs = MM.endo.plugins ? MM.endo.plugins.drawerTabs() : [];
    if (!tabs.length) { box.hidden = true; box.innerHTML = ''; drawer.key = null; return; }
    box.hidden = false;
    if (drawer.key && !tabs.some(function (t) { return t.key === drawer.key; })) drawer.key = null;
    box.innerHTML = '<div class="bench-drawer-tabs" role="tablist">' + tabs.map(function (t) {
      var on = t.key === drawer.key;
      return '<button type="button" class="bench-drawer-tab' + (on ? ' active' : '') + '" role="tab" aria-selected="' + on + '"' +
        ' data-key="' + esc(t.key) + '"><i class="bi bi-' + esc(t.icon || 'layout-text-window') + ' me-1"></i>' + esc(t.title) + '</button>';
    }).join('') + '</div><div class="bench-drawer-panel" id="benchDrawerPanel"' + (drawer.key ? '' : ' hidden') + '></div>';
    box.querySelectorAll('.bench-drawer-tab').forEach(function (b) {
      b.addEventListener('click', function () {
        var key = b.getAttribute('data-key');
        closeDrawerInstance();
        drawer.key = drawer.key === key ? null : key;
        drawDrawer();
      });
    });
    if (drawer.key && !drawer.inst) {
      var tab = tabs.filter(function (t) { return t.key === drawer.key; })[0];
      var panel = box.querySelector('#benchDrawerPanel');
      var token = ++drawer.token;
      tab.mount(panel, selectionCtx()).then(function (inst) {
        if (token !== drawer.token) { if (inst.destroy) inst.destroy(); return; }
        drawer.inst = inst;
        if (!state.active && inst.suspend) inst.suspend();
      }, function (e) {
        panel.innerHTML = '<div class="endo-error">' + esc(tab.title + ': ' + (e.message || e)) + '</div>';
      });
    }
  }

  // ------------------------------------------------------------ dock sections from plugins

  var dockInst = null;
  function destroyDockInstance() {
    if (dockInst && dockInst.destroy) { try { dockInst.destroy(); } catch (e) { /* keep going */ } }
    dockInst = null;
  }

  function render() {
    var el = root();
    if (!el) return Promise.resolve();
    var token = ++state.token;
    var comp = state.comp;
    state.signature = signatureOf(services());
    state.dirty = false;
    teardown();   // the old tiles stop before their DOM goes (R5)
    el.innerHTML = '<div class="bench-loading"><span class="spinner-border spinner-border-sm me-2"></span>Composing the bench…</div>';

    return lintComp(comp).then(function (compIssues) {
      if (token !== state.token) return null;
      state.compIssues = compIssues;
      if (C().hasErrors(compIssues)) return [];
      return resolveModules(comp);
    }).then(function (mods) {
      if (token !== state.token || mods === null) return;
      teardown();
      state.modules = mods;
      var slots = [];
      mods.forEach(function (m) { slots = slots.concat(K().slotsFor(m)); });
      var ordered = K().orderSlots(slots, comp.order);
      state.slots = ordered.slots;
      state.orderIssues = ordered.issues;
      draw(el);
      if (!state.active) state.group.suspend();
      if (hooks.setRibbonTab && state.active && comp.role) hooks.setRibbonTab(comp.role);
    });
  }

  function compHeadHtml() {
    var comp = state.comp || {};
    var errs = state.compIssues.filter(function (i) { return i.severity === 'error'; });
    var warns = state.compIssues.concat(state.orderIssues || []).concat(
      state.modules.reduce(function (a, m) { return a.concat(m.warnings || []); }, []))
      .filter(function (i) { return i.severity === 'warn'; });
    var sel = state.selection;
    var where = state.stored
      ? esc(sel.bench) + ' · ' + esc(ROLE_LABEL[sel.role] || sel.role)
      : 'not saved';
    var badge = errs.length
      ? '<span class="endo-lint bad">refused · ' + errs.length + ' error' + (errs.length > 1 ? 's' : '') + '</span>'
      : warns.length
        ? '<span class="endo-lint warn">' + warns.length + ' warning' + (warns.length > 1 ? 's' : '') + '</span>'
        : '<span class="endo-lint ok">composition passes</span>';
    return '<div class="bench-head">' +
      '<h5>' + esc(comp.title || comp.composition || 'Bench') + '</h5>' +
      '<span class="endo-id">' + esc(comp.composition || '') + ' · ' + where + '</span>' +
      badge +
      '</div>' +
      (state.note ? '<div class="bench-note">' + esc(state.note) + '</div>' : '') +
      (warns.length && !errs.length ? '<details class="endo-warns"><summary>Warnings</summary>' + MM.endo.issuesListHtml(warns) + '</details>' : '') +
      (errs.length ? '<div class="endo-refused" role="alert"><strong>The shell refused this composition.</strong> ' +
        'Fix it in <em>Edit composition</em>:' + MM.endo.issuesListHtml(errs) + '</div>' : '');
  }

  function draw(el) {
    var instances = [];
    state.group = MM.endo.instanceGroup(instances);
    el.innerHTML =
      '<div class="bench">' +
      '  <div class="bench-main">' + compHeadHtml() +
      '    <div class="endo-stage bench-stage" id="benchStage"></div>' +
      (state.modules.length || C().hasErrors(state.compIssues) ? '' :
        '    <div class="bench-empty"><i class="bi bi-grid-1x2"></i><div>' +
        (services().length ? 'No service on the connected Consuls declares a GUI yet.'
                           : 'Connect to a Consul (User tab) to fill the bench.') + '</div></div>') +
      '  </div>' +
      '  <aside class="bench-dock" id="benchDock" hidden></aside>' +
      '  <section class="bench-drawer" id="benchDrawer" aria-label="Drawer"></section>' +
      '  <footer class="bench-status" id="benchStatus" aria-label="Modules on this bench"></footer>' +
      '</div>';
    var stage = el.querySelector('#benchStage');

    state.slots.forEach(function (slot) {
      var mod = slot.module;
      var section;
      if (slot.state === 'ok') {
        var r = MM.endo.renderTile(slot.tile, mod.ctx, { layer: mod.manifest.layer, source: mod.manifest.title });
        section = r.section;
        if (r.instance) instances.push(r.instance);
      } else {
        section = slotSection(slot);
      }
      section.setAttribute('data-key', slot.key);
      section.setAttribute('data-component', slot.component);
      section.tabIndex = 0;
      section.addEventListener('click', function (ev) {
        if (ev.target.closest('button, a, input, select, textarea, label, summary, pre')) return;
        select(slot.key);
      });
      section.addEventListener('keydown', function (ev) {
        if ((ev.key === 'Enter' || ev.key === ' ') && ev.target === section) { ev.preventDefault(); select(slot.key); }
      });
      stage.appendChild(section);
    });

    drawStatus();
    drawNav();
    drawDrawer();
    addRibbonGroups();
    if (state.selectedKey && state.slots.some(function (s) { return s.key === state.selectedKey; })) select(state.selectedKey);
    else state.selectedKey = null;
  }

  function slotSection(slot) {
    var mod = slot.module;
    var svcName = (mod.entry && mod.entry.service) || '?';
    var layer = mod.manifest && C().LAYERS.indexOf(mod.manifest.layer) >= 0 ? mod.manifest.layer : null;
    var s = C().SIZES[slot.size] || [1, 1];
    var section = document.createElement('section');
    section.className = 'endo-tile w' + s[0] + ' h' + s[1] + ' bench-slot state-' + slot.state;
    if (layer) section.style.setProperty('--layer', MM.endo.layerVar(layer));
    var title = (mod.manifest && mod.manifest.title) || svcName;
    var body;
    if (slot.state === 'refused') {
      var rules = {};
      mod.issues.forEach(function (i) { if (i.severity === 'error') rules[i.rule] = true; });
      body = '<div class="bench-slot-msg"><strong>Refused by the shell</strong> · ' +
        Object.keys(rules).map(function (r) { return '<span class="bench-rule">' + esc(r) + '</span>'; }).join(' ') + '</div>' +
        MM.endo.issuesListHtml(mod.issues.filter(function (i) { return i.severity === 'error'; }).slice(0, 4)) +
        (mod.issues.filter(function (i) { return i.severity === 'error'; }).length > 4
          ? '<div class="endo-note">Select the tile for the full list.</div>' : '');
    } else if (slot.state === 'legacy') {
      body = '<div class="bench-slot-msg"><strong>' + esc(svcName) + '</strong> has a classic panel (<code>' +
        esc(mod.folder) + '</code> has no component.json).</div>' +
        '<div><button type="button" class="btn btn-sm btn-outline-primary bench-open">' +
        '<i class="bi bi-box-arrow-up-right me-1"></i>Open panel</button></div>';
    } else if (slot.state === 'nogui') {
      body = '<div class="bench-slot-msg"><strong>' + esc(svcName) + '</strong> declares no GUI. ' +
        'Set <code>gui</code> on the service (Meta.gui), or name the folder in this composition.</div>';
    } else if (slot.state === 'missing') {
      body = '<div class="bench-slot-msg"><strong>' + esc(svcName) + '</strong> is not registered in any connected Consul.</div>';
    } else {
      body = '<div class="endo-error">' + esc(mod.error || 'unavailable') + '</div>';
    }
    section.innerHTML =
      '<header class="endo-tile-head"><span class="t">' + esc(title) + '</span>' +
      '<span class="src">' + esc(STATE_LABEL[slot.state] || slot.state) + '</span></header>' +
      '<div class="endo-tile-body">' + body + '</div>';
    var open = section.querySelector('.bench-open');
    if (open) open.addEventListener('click', function () { openPanel(mod, false); });
    return section;
  }

  function moduleBadgeText(m) {
    if (m.state === 'refused') {
      var rules = {};
      m.issues.forEach(function (i) { if (i.severity === 'error') rules[i.rule] = true; });
      return 'refused · ' + Object.keys(rules).join(' ');
    }
    return STATE_LABEL[m.state] || m.state;
  }

  function drawStatus() {
    var bar = document.getElementById('benchStatus');
    if (!bar) return;
    var plugins = (state.comp && state.comp.plugins) || [];
    bar.innerHTML = state.modules.map(function (m) {
      var layer = m.manifest && C().LAYERS.indexOf(m.manifest.layer) >= 0 ? m.manifest.layer : null;
      var id = K().moduleId(m);
      return '<button type="button" class="bench-badge state-' + m.state + '" data-component="' + esc(id) + '"' +
        (layer ? ' style="--layer:' + MM.endo.layerVar(layer) + '"' : '') +
        ' title="' + esc(id + ' · ' + ((m.entry && m.entry.service) || '')) + '">' +
        '<i class="dot" aria-hidden="true"></i>' +
        '<span class="n">' + esc((m.manifest && m.manifest.title) || (m.entry && m.entry.service) || id) + '</span>' +
        '<span class="s">' + esc(moduleBadgeText(m)) + '</span></button>';
    }).join('') +
    (plugins.length ? '<span class="bench-plugins">plugins: ' + plugins.map(function (id) {
      var st = MM.endo.plugins ? MM.endo.plugins.state(id) : 'missing';
      var cls = st === 'active' ? 'ok' : st === 'missing' ? 'bad' : 'warn';
      var label = st === 'active' ? '' : st === 'missing' ? ' (not installed)' : st === 'disabled' ? ' (off)' : ' (' + st + ')';
      return '<span class="bench-plugin ' + cls + '" title="' + esc(id + ': ' + st) + '">' + esc(id + label) + '</span>';
    }).join(', ') + '</span>' : '') +
    '<button type="button" class="bench-signals" id="benchSignals" title="Live signals: click to set where signal-discovery is"></button>';
    bar.querySelectorAll('.bench-badge').forEach(function (b) {
      b.addEventListener('click', function () { selectComponent(b.getAttribute('data-component')); });
    });
    bar.querySelector('#benchSignals').addEventListener('click', openSignalsDialog);
    drawSignals();
  }

  // ------------------------------------------------------------ live signals

  var SOCKET_LABEL = { idle: 'off', connecting: 'connecting', open: 'connected', retrying: 'reconnecting' };

  /** The status strip's signal badge: socket state, discovery, live/unknown counts. */
  function drawSignals() {
    var b = document.getElementById('benchSignals');
    if (!b || !MM.endo.bus) return;
    var s = MM.endo.bus.stats();
    var state = s.error && (s.socket !== 'open' || (s.names && !s.live)) ? 'bad'
      : s.unknown.length || s.error ? 'warn' : s.socket === 'open' ? 'ok' : 'idle';
    b.className = 'bench-signals state-' + state;
    b.innerHTML = '<i class="bi bi-activity"></i>' +
      '<span>signals · ' + esc(SOCKET_LABEL[s.socket] || s.socket) +
      (s.names ? ' · ' + s.live + '/' + s.names + ' live' : '') +
      (s.unknown.length ? ' · ' + s.unknown.length + ' unknown' : '') + '</span>' +
      (s.discovery ? '<code>' + esc(s.discovery) + '</code>' : '');
    b.title = (s.error ? s.error + '\n' : '') +
      (s.unknown.length ? 'Not in the signal catalog: ' + s.unknown.join(', ') + '\n' : '') +
      'Click to set where signal-discovery is.';
  }

  var sigModal = null;
  function openSignalsDialog() {
    var el = document.getElementById('benchSignalsModal');
    if (!el) {
      el = document.createElement('div');
      el.className = 'modal fade';
      el.id = 'benchSignalsModal';
      el.tabIndex = -1;
      el.setAttribute('aria-labelledby', 'benchSignalsTitle');
      el.setAttribute('aria-hidden', 'true');
      el.innerHTML = '<div class="modal-dialog modal-dialog-centered"><form class="modal-content" novalidate>' +
        '<div class="modal-header"><h5 class="modal-title" id="benchSignalsTitle">Live signals</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
        '<div class="modal-body">' +
        '  <label class="form-label" for="benchSignalsAddr">Signal discovery address</label>' +
        '  <input class="form-control" id="benchSignalsAddr" placeholder="host:port, e.g. 127.0.0.1:50210" autocomplete="off">' +
        '  <div class="form-text">Leave empty to use the <code>signal-discovery</code> service of the connected Consul. ' +
        '  The bridge keeps one stream per graph service and sends each value at most 10 times a second.</div>' +
        '  <div class="mt-3 endo-small" id="benchSignalsState"></div>' +
        '  <div class="endo-result bad mt-2" id="benchSignalsError" hidden></div>' +
        '</div>' +
        '<div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>' +
        '<button type="submit" class="btn btn-primary">Use this address</button></div></form></div>';
      document.body.appendChild(el);
      el.querySelector('form').addEventListener('submit', function (ev) {
        ev.preventDefault();
        var v = el.querySelector('#benchSignalsAddr').value.trim();
        var err = el.querySelector('#benchSignalsError');
        if (v && !/^[A-Za-z0-9._-]+:\d{1,5}$/.test(v)) {
          err.hidden = false;
          err.textContent = 'Use host:port, e.g. 127.0.0.1:50210.';
          return;
        }
        MM.endo.bus.setDiscovery(v);
        sigModal.hide();
      });
    }
    sigModal = bootstrap.Modal.getOrCreateInstance(el);
    var s = MM.endo.bus.stats();
    el.querySelector('#benchSignalsAddr').value = s.discoveryOverride || '';
    el.querySelector('#benchSignalsError').hidden = true;
    el.querySelector('#benchSignalsState').innerHTML =
      'Now: <strong>' + esc(SOCKET_LABEL[s.socket] || s.socket) + '</strong>' +
      (s.discovery ? ' via <code>' + esc(s.discovery) + '</code>' : '') +
      ' · ' + s.names + ' signal(s), ' + s.subscribers + ' subscriber(s)' +
      (s.error ? '<div class="endo-bad mt-1">' + esc(s.error) + '</div>' : '');
    sigModal.show();
  }

  function drawNav() {
    var nav = document.getElementById('benchNav');
    if (!nav) return;
    var comp = state.comp || {};
    if (!state.modules.length) {
      nav.innerHTML = '<div class="sidebar-empty-hint">' +
        (C().hasErrors(state.compIssues) ? 'The composition was refused.' : 'No modules on this bench.') + '</div>';
      return;
    }
    nav.innerHTML =
      '<div class="bench-nav-head">' + esc(comp.title || comp.composition || 'Bench') + '</div>' +
      '<ul class="list-group list-group-flush">' +
      state.modules.map(function (m) {
        var layer = m.manifest && C().LAYERS.indexOf(m.manifest.layer) >= 0 ? m.manifest.layer : null;
        var id = K().moduleId(m);
        return '<li class="list-group-item bench-nav-item state-' + m.state + '" tabindex="0" data-component="' + esc(id) + '"' +
          (layer ? ' style="--layer:' + MM.endo.layerVar(layer) + '"' : '') + '>' +
          '<div class="svc-row"><div class="svc-name"><i class="bench-layer-dot" aria-hidden="true"></i>' +
          esc((m.manifest && m.manifest.title) || (m.entry && m.entry.service) || id) + '</div>' +
          '<div class="svc-hint">' + esc(layer || '—') + ' · ' + esc((m.entry && m.entry.service) || '') +
          ' · ' + esc(moduleBadgeText(m)) + '</div></div></li>';
      }).join('') + '</ul>';
    nav.querySelectorAll('.bench-nav-item').forEach(function (li) {
      var go = function () { selectComponent(li.getAttribute('data-component')); };
      li.addEventListener('click', go);
      li.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') go(); });
    });
  }

  // ------------------------------------------------------------ selection + dock

  function selectComponent(id) {
    var slot = state.slots.filter(function (s) { return s.component === id; })[0];
    if (slot) {
      select(slot.key);
      var el = document.querySelector('#benchStage [data-key="' + cssEsc(slot.key) + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
    } else {
      // A module with tiles all filtered out has no slot; still show its details.
      var mod = state.modules.filter(function (m) { return K().moduleId(m) === id; })[0];
      if (mod) { state.selectedKey = null; showDock(mod, null); }
    }
  }

  function cssEsc(s) { return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/"/g, '\\"'); }

  function select(key) {
    state.selectedKey = key;
    document.querySelectorAll('#benchStage .endo-tile').forEach(function (t) {
      t.classList.toggle('selected', t.getAttribute('data-key') === key);
    });
    var slot = state.slots.filter(function (s) { return s.key === key; })[0];
    if (!slot) return closeDock();
    var id = slot.component;
    document.querySelectorAll('#benchNav .bench-nav-item').forEach(function (li) {
      li.classList.toggle('active', li.getAttribute('data-component') === id);
    });
    showDock(slot.module, slot);
    emitSelection();
  }

  function closeDock() {
    var dock = document.getElementById('benchDock');
    if (dock) { dock.hidden = true; dock.innerHTML = ''; }
    var b = document.querySelector('.bench');
    if (b) b.classList.remove('with-dock');
    state.selectedKey = null;
    destroyDockInstance();
    document.querySelectorAll('#benchStage .endo-tile.selected').forEach(function (t) { t.classList.remove('selected'); });
    document.querySelectorAll('#benchNav .bench-nav-item.active').forEach(function (li) { li.classList.remove('active'); });
    emitSelection();
  }

  function svcWithUrl(mod) { return mod.service ? Object.assign({}, mod.service) : null; }

  function showDock(mod, slot, tab) {
    var dock = document.getElementById('benchDock');
    if (!dock) return;
    var m = mod.manifest || {};
    var tabs = ['details'];
    var sections = {};   // plugin dock sections for this component's layer
    if (mod.state === 'ok') {
      (m.dock || []).forEach(function (t) { if (tabs.indexOf(t) < 0 && (t === 'api' || t === 'code')) tabs.push(t); });
      (MM.endo.plugins ? MM.endo.plugins.dockSections(m.layer) : []).forEach(function (s) {
        sections['plugin:' + s.key] = s;
        tabs.push('plugin:' + s.key);
      });
    }
    tab = tabs.indexOf(tab) >= 0 ? tab : 'details';
    destroyDockInstance();
    var layer = C().LAYERS.indexOf(m.layer) >= 0 ? m.layer : null;
    dock.hidden = false;
    document.querySelector('.bench').classList.add('with-dock');
    dock.style.setProperty('--layer', layer ? MM.endo.layerVar(layer) : 'var(--l-runner)');
    dock.innerHTML =
      '<div class="bench-dock-head">' +
      (layer ? '<span class="endo-layer">' + esc(layer) + '</span>' : '') +
      '<div class="bench-dock-title">' + esc(m.title || (mod.entry && mod.entry.service) || 'Module') + '</div>' +
      '<button type="button" class="dev-inspector-close" id="benchDockClose" title="Close" aria-label="Close the dock">' +
      '<i class="bi bi-x-lg"></i></button></div>' +
      (slot && slot.tile ? '<div class="bench-dock-sub">Tile <code>' + esc(slot.tile.id) + '</code> · ' + esc(slot.tile.kind) + ' · ' + esc(slot.tile.size) + '</div>' : '') +
      (tabs.length > 1 ? '<div class="dev-inspector-tabs">' + tabs.map(function (t) {
        return '<button type="button" class="dev-inspector-tab' + (t === tab ? ' active' : '') + '" data-tab="' + esc(t) + '">' +
          esc(sections[t] ? sections[t].title : ({ details: 'Details', api: 'API', code: 'Code' })[t]) + '</button>';
      }).join('') + '</div>' : '') +
      '<div class="bench-dock-body" id="benchDockBody"></div>';
    dock.querySelector('#benchDockClose').addEventListener('click', closeDock);
    dock.querySelectorAll('.dev-inspector-tab').forEach(function (b) {
      b.addEventListener('click', function () { showDock(mod, slot, b.getAttribute('data-tab')); });
    });
    var body = dock.querySelector('#benchDockBody');
    if (sections[tab]) {
      var key = state.selectedKey;
      sections[tab].render(body, selectionInfo(), selectionCtx()).then(function (inst) {
        if (state.selectedKey !== key) { if (inst.destroy) inst.destroy(); return; }
        dockInst = inst;
      }, function (e) { body.innerHTML = '<div class="endo-error">' + esc(e.message || e) + '</div>'; });
    } else if (tab === 'api') {
      if (hooks.showApi && mod.service) hooks.showApi(svcWithUrl(mod), 'benchDockBody');
    } else if (tab === 'code') {
      body.innerHTML = '<p class="endo-note">Client code for Python, C++ and Robot Framework is in the developer inspector.</p>' +
        '<button type="button" class="btn btn-sm btn-outline-primary" id="benchDockCode">' +
        '<i class="bi bi-file-earmark-code me-1"></i>Open in the inspector</button>';
      body.querySelector('#benchDockCode').addEventListener('click', function () {
        if (hooks.openInspector) hooks.openInspector(svcWithUrl(mod), 'code');
      });
    } else {
      detailsHtml(mod, body);
    }
  }

  function detailsHtml(mod, body) {
    var m = mod.manifest || {};
    var svc = mod.service;
    var req = m.requires || {};
    var binds = m.binds || {};
    var rows = [];
    if (m.component) rows.push(['Component', '<code>' + esc(m.component) + '</code> ' + esc(m.version || '')]);
    rows.push(['State', esc(moduleBadgeText(mod))]);
    rows.push(['Service', esc((mod.entry && mod.entry.service) || '—')]);
    if (svc) {
      rows.push(['Instance', '<code>' + esc((svc.address || '?') + ':' + (svc.port || '?')) + '</code>']);
      rows.push(['Health', esc((svc.status && svc.status.label) || 'unknown')]);
      rows.push(['Consul', '<code>' + esc(svc.consulUrl || '') + '</code>']);
    }
    if (mod.folder) rows.push(['GUI folder', '<code>' + esc(mod.folder) + '</code>' + (mod.entry && mod.entry.gui ? ' (from the composition)' : '')]);
    if (binds.grpc) rows.push(['gRPC', '<code>' + esc(binds.grpc) + '</code>']);
    if (m.requires) rows.push(['Capabilities', (req.capabilities || []).length
      ? (req.capabilities || []).map(function (c) { return '<code>' + esc(c) + '</code>'; }).join(' ') : 'none']);
    if (m.requires) rows.push(['Shell', '<code>' + esc(req.shell || '') + '</code>']);
    var errs = mod.issues.filter(function (i) { return i.severity === 'error'; });
    var warns = mod.issues.concat(mod.warnings || []).filter(function (i) { return i.severity === 'warn'; });
    body.innerHTML =
      '<table class="svc-card-table">' + rows.map(function (r) {
        return '<tr><th>' + esc(r[0]) + '</th><td>' + r[1] + '</td></tr>';
      }).join('') + '</table>' +
      (errs.length ? '<div class="endo-refused mt-2"><strong>Refused.</strong> Fix these in <code>' + esc(mod.folder) +
        '/component.json</code> and reload the bench:' + MM.endo.issuesListHtml(errs) + '</div>' : '') +
      (warns.length ? '<details class="endo-warns mt-2" open><summary>Warnings</summary>' + MM.endo.issuesListHtml(warns) + '</details>' : '') +
      (mod.state === 'missing' ? '<p class="endo-note mt-2">Start the service, or connect to the Consul it registers in.</p>' : '') +
      '<div class="bench-dock-actions" id="benchDockActions"></div>';
    var actions = body.querySelector('#benchDockActions');
    if (!svc) return;
    addAction(actions, 'bi-box-arrow-up-right', mod.state === 'legacy' ? 'Open panel' : 'Open in Services view',
      function () { openPanel(mod, false); });
    if (mod.state === 'ok' || mod.state === 'refused') {
      // Offer the service's classic panel when the folder still has one.
      hasClassicPanel(mod.folder).then(function (yes) {
        if (yes && actions.isConnected) {
          addAction(actions, 'bi-window', 'Open classic panel', function () { openPanel(mod, true); });
        }
      });
    }
  }

  function addAction(container, icon, label, fn) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-sm btn-outline-primary';
    b.innerHTML = '<i class="bi ' + icon + ' me-1"></i>' + esc(label);
    b.addEventListener('click', fn);
    container.appendChild(b);
  }

  var CLASSIC_FILE = /(\.html|\.qml|\.ui|\.wasm|^gui_schema\.json)$/i;
  function hasClassicPanel(folder) {
    if (!MM.listServiceFiles || !folder) return Promise.resolve(false);
    return MM.listServiceFiles((MM.SERVICES_GUI_FOLDER || 'services') + '/' + folder)
      .then(function (files) { return (files || []).some(function (f) { return CLASSIC_FILE.test(f); }); })
      .catch(function () { return false; });
  }

  function openPanel(mod, classic) {
    if (!mod.service || !hooks.openService) return;
    var svc = svcWithUrl(mod);
    if (mod.entry && mod.entry.gui) svc.gui = mod.entry.gui;
    hooks.openService(svc, { classic: !!classic });
  }

  // ------------------------------------------------------------ ribbon

  var RIBBON_PANEL = { user: 'ribbonUser', dev: 'ribbonDev', admin: 'ribbonAdmin' };

  function removeRibbonGroups() {
    document.querySelectorAll('#ribbon .endo-contrib').forEach(function (g) { g.remove(); });
  }

  /** Components' ribbon[] groups, after each tab's own groups. Refused components contribute nothing. */
  function addRibbonGroups() {
    removeRibbonGroups();
    state.modules.forEach(function (mod) {
      if (mod.state !== 'ok') return;
      (mod.manifest.ribbon || []).forEach(function (g) {
        var panel = document.getElementById(RIBBON_PANEL[g.tab]);
        if (!panel) return;
        var group = document.createElement('div');
        group.className = 'ribbon-group endo-contrib';
        group.hidden = !state.active;
        group.setAttribute('data-component', mod.manifest.component);
        group.style.setProperty('--layer', MM.endo.layerVar(mod.manifest.layer));
        group.innerHTML = '<div class="ribbon-group-items"></div>' +
          '<div class="ribbon-group-label"><i class="bench-layer-dot" aria-hidden="true"></i>' + esc(g.group) + '</div>';
        var items = group.querySelector('.ribbon-group-items');
        (g.commands || []).forEach(function (cmd) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'ribbon-btn';
          b.title = cmd.label + ' · ' + mod.manifest.title + ' (' + cmd.call + ')';
          b.innerHTML = '<i class="bi bi-' + esc(/^[a-z0-9-]+$/.test(cmd.icon || '') ? cmd.icon : 'lightning') + '"></i>' +
            '<span>' + esc(cmd.label) + '</span>';
          b.addEventListener('click', function () { runCommand(mod, cmd); });
          items.appendChild(b);
        });
        panel.appendChild(group);
      });
    });
  }

  function syncRibbonGroups() {
    document.querySelectorAll('#ribbon .endo-contrib').forEach(function (g) { g.hidden = !state.active; });
  }

  /**
   * One line for a toast: gRPC errors carry the whole channel state; keep
   * the part a person can act on. The full text goes to the console.
   */
  function shortError(err) {
    var msg = String((err && err.message) || err || 'failed');
    var details = /details = "([^"]+)"/.exec(msg);
    if (details) msg = details[1];
    msg = msg.split('\n')[0];
    return msg.length > 160 ? msg.slice(0, 157) + '…' : msg;
  }

  function runCommand(mod, cmd) {
    var title = mod.manifest.title || mod.manifest.component;
    var go = function (formArgs) {
      var args = Object.assign({}, cmd.args || {}, formArgs || {});
      mod.ctx.call(cmd.call, args).then(function () {
        MM.showToast(title, cmd.label + ': done', 'success');
      }, function (err) {
        console.warn('[bench] ' + mod.manifest.component + ' ' + cmd.call + ' failed:', err);
        MM.showToast(title, cmd.label + ' failed: ' + shortError(err), 'danger');
      });
    };
    var confirmed = function (formArgs) {
      if (cmd.confirm) mod.ctx.confirm(cmd.confirm).then(function (ok) { if (ok) go(formArgs); });
      else go(formArgs);
    };
    if (cmd.form && Object.keys(cmd.form).length) askForm(title, cmd, confirmed);
    else confirmed(null);
  }

  var cmdModal = null;
  function askForm(title, cmd, done) {
    var util = MM.endo.util.form;
    var el = document.getElementById('benchCmdModal');
    if (!el) {
      el = document.createElement('div');
      el.className = 'modal fade';
      el.id = 'benchCmdModal';
      el.tabIndex = -1;
      el.setAttribute('aria-hidden', 'true');
      el.innerHTML = '<div class="modal-dialog modal-dialog-centered"><form class="modal-content" novalidate>' +
        '<div class="modal-header"><h5 class="modal-title" id="benchCmdTitle"></h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
        '<div class="modal-body"><div class="endo-fields" id="benchCmdFields"></div>' +
        '<div class="endo-result bad mt-2" id="benchCmdError" hidden></div></div>' +
        '<div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>' +
        '<button type="submit" class="btn btn-primary" id="benchCmdRun">Run</button></div></form></div>';
      document.body.appendChild(el);
      // Bootstrap ignores hide() while the modal is still opening.
      el.addEventListener('shown.bs.modal', function () { el.__shown = true; });
      el.addEventListener('hidden.bs.modal', function () {
        el.__shown = false;
        var next = el.__afterHide;
        el.__afterHide = null;
        if (next) next();
      });
    }
    cmdModal = bootstrap.Modal.getOrCreateInstance(el);
    el.__afterHide = null;
    var fields = util.fromManifest(cmd.form);
    el.querySelector('#benchCmdTitle').textContent = title + ': ' + cmd.label;
    el.querySelector('#benchCmdFields').innerHTML = fields.map(function (f, i) { return util.fieldHtml('benchCmdF' + i, f); }).join('');
    var errBox = el.querySelector('#benchCmdError');
    errBox.hidden = true;
    el.querySelector('#benchCmdRun').textContent = cmd.label;
    var form = el.querySelector('form');
    form.onsubmit = function (ev) {
      ev.preventDefault();
      var args;
      try { args = util.collect(form); } catch (e) { errBox.hidden = false; errBox.textContent = e.message; return; }
      // Run (or ask for confirmation) once this modal is gone: two modals
      // at once leave a backdrop behind.
      el.__afterHide = function () { done(args); };
      if (el.__shown) cmdModal.hide();
      else el.addEventListener('shown.bs.modal', function () { cmdModal.hide(); }, { once: true });
    };
    cmdModal.show();
  }

  // ------------------------------------------------------------ picker + editor

  function selectionValue(sel) { return sel ? sel.bench + '|' + sel.role : '__all__'; }

  function renderPicker() {
    var pick = document.getElementById('benchPicker');
    if (!pick) return;
    var cur = selectionValue(state.selection);
    var opts = [['__all__', 'All components (not saved)']].concat(state.list.map(function (c) {
      return [c.bench + '|' + c.role, c.bench + ' · ' + (ROLE_LABEL[c.role] || c.role)];
    }));
    if (cur !== '__all__' && !opts.some(function (o) { return o[0] === cur; })) {
      opts.push([cur, state.selection.bench + ' · ' + (ROLE_LABEL[state.selection.role] || state.selection.role) + ' (not stored)']);
    }
    pick.innerHTML = opts.map(function (o) {
      return '<option value="' + esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
    }).join('');
  }

  function choose(value) {
    if (value === '__all__') state.selection = null;
    else {
      var p = String(value).split('|');
      state.selection = { bench: p[0], role: p[1] };
    }
    writeSelection(state.selection);
    state.selectedKey = null;
    closeDock();
    renderPicker();
    return reload();
  }

  var editModal = null;
  function openEditor() {
    var el = document.getElementById('benchEditModal');
    if (!el) {
      el = document.createElement('div');
      el.className = 'modal fade';
      el.id = 'benchEditModal';
      el.tabIndex = -1;
      el.setAttribute('aria-labelledby', 'benchEditTitle');
      el.setAttribute('aria-hidden', 'true');
      el.innerHTML =
        '<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content">' +
        '<div class="modal-header"><h5 class="modal-title" id="benchEditTitle">Edit composition</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
        '<div class="modal-body">' +
        '  <div class="row g-2 mb-2">' +
        '    <div class="col-sm-6"><label class="form-label" for="benchEditBench">Bench</label>' +
        '      <input class="form-control form-control-sm" id="benchEditBench" placeholder="bench07" autocomplete="off"></div>' +
        '    <div class="col-sm-6"><label class="form-label" for="benchEditRole">Role (ribbon tab)</label>' +
        '      <select class="form-select form-select-sm" id="benchEditRole">' +
        K().ROLES.map(function (r) { return '<option value="' + r + '">' + ROLE_LABEL[r] + '</option>'; }).join('') +
        '      </select></div>' +
        '  </div>' +
        '  <label class="form-label" for="benchEditJson">Composition (JSON)</label>' +
        '  <textarea class="form-control bench-json" id="benchEditJson" rows="16" spellcheck="false"></textarea>' +
        '  <div class="form-text" id="benchEditDir"></div>' +
        '  <div class="mt-2" id="benchEditIssues"></div>' +
        '</div>' +
        '<div class="modal-footer">' +
        '  <button type="button" class="btn btn-outline-secondary me-auto" id="benchEditAll">Start from all components</button>' +
        '  <button type="button" class="btn btn-outline-danger" id="benchEditDelete">Delete</button>' +
        '  <button type="button" class="btn btn-outline-primary" id="benchEditCheck">Check</button>' +
        '  <button type="button" class="btn btn-primary" id="benchEditSave">Save</button>' +
        '</div></div></div>';
      document.body.appendChild(el);
      el.querySelector('#benchEditCheck').addEventListener('click', function () { checkEditor(); });
      el.querySelector('#benchEditSave').addEventListener('click', saveEditor);
      el.querySelector('#benchEditDelete').addEventListener('click', deleteEditor);
      el.querySelector('#benchEditAll').addEventListener('click', function () {
        var bench = el.querySelector('#benchEditBench').value.trim() || 'default';
        var role = el.querySelector('#benchEditRole').value;
        el.querySelector('#benchEditJson').value = JSON.stringify(K().defaultComposition(services(), bench, role), null, 2);
        checkEditor();
      });
    }
    editModal = bootstrap.Modal.getOrCreateInstance(el);
    var sel = state.selection || { bench: 'default', role: 'user' };
    el.querySelector('#benchEditBench').value = sel.bench;
    el.querySelector('#benchEditRole').value = sel.role;
    var comp = JSON.parse(JSON.stringify(state.comp || K().defaultComposition(services(), sel.bench, sel.role)));
    if (!state.stored && state.selection === null) comp.composition = sel.bench + '/' + sel.role;
    el.querySelector('#benchEditJson').value = JSON.stringify(comp, null, 2);
    el.querySelector('#benchEditDir').textContent = state.dir ? 'Stored in ' + state.dir : '';
    el.querySelector('#benchEditIssues').innerHTML = '';
    el.querySelector('#benchEditDelete').hidden = !state.stored;
    editModal.show();
  }

  function editorValue() {
    var el = document.getElementById('benchEditModal');
    var text = el.querySelector('#benchEditJson').value;
    try { return { comp: JSON.parse(text) }; } catch (e) { return { error: 'Not valid JSON: ' + e.message }; }
  }

  function showEditorIssues(html) {
    document.getElementById('benchEditIssues').innerHTML = html;
  }

  function checkEditor() {
    var v = editorValue();
    if (v.error) { showEditorIssues('<div class="endo-refused">' + esc(v.error) + '</div>'); return Promise.resolve(null); }
    return lintComp(v.comp).then(function (issues) {
      var errs = issues.filter(function (i) { return i.severity === 'error'; });
      var warns = issues.filter(function (i) { return i.severity === 'warn'; });
      showEditorIssues(
        (errs.length ? '<div class="endo-refused"><strong>' + errs.length + ' error(s).</strong>' + MM.endo.issuesListHtml(errs) + '</div>'
                     : '<span class="endo-lint ok">composition passes</span>') +
        (warns.length ? '<details class="endo-warns mt-2" open><summary>Warnings</summary>' + MM.endo.issuesListHtml(warns) + '</details>' : ''));
      return errs.length ? null : v.comp;
    });
  }

  function saveEditor() {
    var el = document.getElementById('benchEditModal');
    var bench = el.querySelector('#benchEditBench').value.trim();
    var role = el.querySelector('#benchEditRole').value;
    checkEditor().then(function (comp) {
      if (!comp) return;
      return api('PUT', '/api/ui/compositions/' + encodeURIComponent(bench) + '/' + encodeURIComponent(role), comp)
        .then(function () {
          editModal.hide();
          MM.showToast('Bench', 'Saved ' + bench + '/' + role, 'success');
          return refreshList().then(function () { return choose(bench + '|' + role); });
        });
    }).catch(function (err) {
      showEditorIssues('<div class="endo-refused">' + esc(err.message) + '</div>');
    });
  }

  function deleteEditor() {
    if (!state.selection || !state.stored) return;
    var sel = state.selection;
    MM.showConfirm('Delete the composition ' + sel.bench + '/' + sel.role + '?', function () {
      api('DELETE', '/api/ui/compositions/' + encodeURIComponent(sel.bench) + '/' + encodeURIComponent(sel.role))
        .then(function () {
          if (editModal) editModal.hide();
          MM.showToast('Bench', 'Deleted ' + sel.bench + '/' + sel.role, 'info');
          return refreshList().then(function () { return choose('__all__'); });
        })
        .catch(function (err) { MM.showToast('Bench', err.message, 'danger'); });
    });
  }

  // ------------------------------------------------------------ public

  /** Show (true) or hide (false) the bench: tiles poll only while shown (R5). */
  function setActive(on) {
    on = !!on;
    if (on === state.active) return;
    state.active = on;
    syncRibbonGroups();
    if (on) {
      if (state.dirty || signatureOf(services()) !== state.signature) { reload(); return; }
      if (state.group) state.group.resume();
      if (drawer.inst && drawer.inst.resume) drawer.inst.resume();
      if (dockInst && dockInst.resume) dockInst.resume();
      if (hooks.setRibbonTab && state.comp && state.comp.role) hooks.setRibbonTab(state.comp.role);
    } else {
      if (state.group) state.group.suspend();
      if (drawer.inst && drawer.inst.suspend) drawer.inst.suspend();
      if (dockInst && dockInst.suspend) dockInst.suspend();
    }
  }

  /** A plugin was turned on or off: its kinds, drawer tabs and dock sections changed. */
  function pluginsChanged() {
    if (state.active) reload();
    else state.dirty = true;
  }

  /** The connected services changed: recompose if a name, folder or address moved. */
  function servicesChanged() {
    if (signatureOf(services()) === state.signature) return;
    if (state.active) reload();
    else state.dirty = true;
  }

  function init(h) {
    hooks = h || {};
    state.selection = readSelection();
    var pick = document.getElementById('benchPicker');
    if (pick) pick.addEventListener('change', function () { choose(pick.value); });
    var edit = document.getElementById('btnBenchEdit');
    if (edit) edit.addEventListener('click', openEditor);
    var rl = document.getElementById('btnBenchReload');
    if (rl) rl.addEventListener('click', function () { refreshList(); reload(); });
    renderPicker();
    refreshList();
    if (MM.endo.bus) MM.endo.bus.onChange(drawSignals);
  }

  MM.endo.bench = {
    init: init,
    setActive: setActive,
    servicesChanged: servicesChanged,
    pluginsChanged: pluginsChanged,
    selection: selectionInfo,
    reload: reload,
    choose: choose,
    /** For probes and tests: what the bench currently shows. */
    snapshot: function () {
      return {
        selection: state.selection,
        stored: state.stored,
        composition: state.comp && state.comp.composition,
        compIssues: state.compIssues,
        modules: state.modules.map(function (m) {
          return { id: K().moduleId(m), service: m.entry && m.entry.service, state: m.state,
                   issues: m.issues.map(function (i) { return i.rule + ':' + i.severity; }) };
        }),
        slots: state.slots.map(function (s) { return s.key; }),
        active: state.active
      };
    }
  };
})();
