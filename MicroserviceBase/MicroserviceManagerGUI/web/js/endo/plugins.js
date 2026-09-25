/**
 * @fileoverview Bench Endoskeleton plugins (milestone M4): find, lint,
 * enable and apply plugin contributions.
 *
 * Where plugins come from:
 *   bundled    web/plugins/<id>/plugin.json, listed in web/plugins/index.json
 *   installed  <userData>/plugins/<id>/ (desktop app; wins over bundled)
 *
 * A plugin is enabled unless the user turned it off (Administrator →
 * Plugins; stored per PC). An enabled plugin that passes the linter is
 * applied: its kinds are imported and registered in MM.endo.kinds, its
 * ribbon groups, navigators (tabs under the left pane), stage views and
 * commands appear. Turning it off removes all of that; tiles of its kinds
 * become "enable plugin X" placeholders when the bench recomposes.
 *
 * A contribution is implemented by an ES module of the plugin ("entry") or
 * by a view or action the shell already has ("shell"). Until frame
 * isolation (milestone M5), "frame" plugins run in the page.
 *
 * app.js passes what plugins may reach through init(hooks):
 *   actions      { name: fn }   shell actions for commands ("robotGen", ...)
 *   views        { name: { sidebar, content } }  shell views for navigators
 *   switchMode(mode), currentMode()
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};

  var DISABLED_KEY = 'mm_plugins_disabled';
  var SCHEMA_URL = 'js/endo/contract/plugin.schema.json';
  var PANEL = { user: 'ribbonUser', dev: 'ribbonDev', admin: 'ribbonAdmin' };

  var hooks = { actions: {}, views: {}, switchMode: function () {}, currentMode: function () { return ''; } };
  var plugins = [];          // { id, manifest, base, source, state, issues, error, applied }
  var listeners = [];
  var readyResolve;
  var ready = new Promise(function (res) { readyResolve = res; });
  var viewInstances = {};    // mode -> { sidebar, content } instances of entry views

  function esc(s) { return MM.endo.util.esc(s); }
  function C() { return window.EndoContract; }

  // ------------------------------------------------------------ state

  function disabledSet() {
    try { return new Set(JSON.parse(localStorage.getItem(DISABLED_KEY) || '[]')); } catch (e) { return new Set(); }
  }
  function saveDisabled(set) {
    try { localStorage.setItem(DISABLED_KEY, JSON.stringify(Array.from(set).sort())); } catch (e) { /* storage unavailable */ }
  }
  function byId(id) { return plugins.filter(function (p) { return p.id === id; })[0] || null; }
  function isActive(p) { return !!p && p.state === 'active'; }

  function notify(what) {
    listeners.forEach(function (fn) { try { fn(what); } catch (e) { console.warn('[plugins] listener:', e); } });
  }

  // ------------------------------------------------------------ discovery

  function fetchJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
      return r.text();
    }).then(function (t) { return JSON.parse(t.replace(/^﻿/, '')); });
  }

  function discover() {
    var bundledBase = new URL('plugins/', document.baseURI).href;
    var bundled = fetchJson(bundledBase + 'index.json').then(function (idx) {
      return Promise.all((idx.plugins || []).map(function (id) {
        var base = bundledBase + id + '/';
        return fetchJson(base + 'plugin.json').then(function (m) {
          return { id: id, manifest: m, base: base, source: 'bundled' };
        }, function (e) {
          return { id: id, manifest: null, base: base, source: 'bundled', error: e.message };
        });
      }));
    }).catch(function (e) {
      console.warn('[plugins] no bundled plugin index:', e.message);
      return [];
    });
    var installed = Promise.resolve().then(function () {
      var api = window.electronAPI;
      if (!api || typeof api.listInstalledPlugins !== 'function') return [];
      return (api.listInstalledPlugins() || []).map(function (e) {
        return { id: e.id, manifest: e.manifest || null, base: e.base, source: 'installed', error: e.error };
      });
    }).catch(function () { return []; });
    return Promise.all([bundled, installed]).then(function (r) {
      var out = {};
      r[0].concat(r[1]).forEach(function (p) { out[p.id] = p; });   // installed wins
      return Object.keys(out).map(function (k) { return out[k]; });
    });
  }

  var windowRecords = {};   // id -> { allowed, loaded, error } from the main process

  /** A window plugin's standing with the main process: null when it may run. */
  function windowBlock(p) {
    if (!window.electronAPI || typeof window.electronAPI.openPlugin !== 'function') {
      return { state: 'unavailable', error: 'needs the desktop app (its own window)' };
    }
    var rec = windowRecords[p.id];
    if (!rec) return { state: 'error', error: 'the main process did not find it' };
    if (!rec.allowed) return { state: 'blocked', error: 'not on the window-plugin allow-list: allow it here to let it start processes' };
    if (!rec.loaded) return { state: 'error', error: rec.error || 'its main module did not load' };
    return null;
  }

  /** Lint and decide each plugin's state before anything is applied. */
  function assess(list, schema) {
    var off = disabledSet();
    list.forEach(function (p) {
      p.issues = [];
      p.error = p.error || '';
      if (!p.manifest) { p.state = 'error'; return; }
      p.issues = C().lintPlugin(p.manifest, { schema: schema });
      if (p.manifest.plugin && p.manifest.plugin !== p.id) {
        p.issues.push({ rule: 'S', severity: 'error', component: p.id, path: 'plugin',
                        message: 'must match the folder name "' + p.id + '"' });
      }
      if (C().hasErrors(p.issues)) { p.state = 'refused'; return; }
      if (p.manifest.isolation === 'window') {
        var block = windowBlock(p);
        if (block) { p.state = block.state; p.error = block.error; return; }
      }
      p.state = off.has(p.id) ? 'disabled' : 'pending';
    });
  }

  /** Allow or block a window plugin (the main process owns the list). */
  function setAllowed(id, allowed) {
    var p = byId(id);
    var api = window.electronAPI;
    if (!p || !api || typeof api.setWindowPluginAllowed !== 'function') return Promise.resolve(false);
    return api.setWindowPluginAllowed(id, allowed).then(function (res) {
      windowRecords = {};
      ((res && res.plugins) || []).forEach(function (r) { windowRecords[r.id] = r; });
      var block = windowBlock(p);
      if (block) {
        removeAll(p);
        p.state = block.state;
        p.error = block.error;
        notify({ plugin: id, enabled: false });
        return false;
      }
      p.error = '';
      if (disabledSet().has(id)) { p.state = 'disabled'; return true; }
      return apply(p).then(function () {
        notify({ plugin: id, enabled: p.state === 'active' });
        return p.state === 'active';
      });
    });
  }

  // ------------------------------------------------------------ apply / remove

  function contrib(p, point) {
    var c = (p.manifest && p.manifest.contributes) || {};
    return Array.isArray(c[point]) ? c[point] : [];
  }

  /**
   * Run one entry of a plugin in a sandboxed frame (frame-host.js): its own
   * process, no DOM of the shell, ctx over a port. fn: render | mount | run.
   */
  function inFrame(p, el, entry, fn, args, ctx, label, selection) {
    el.classList.add('endo-frame-body');
    return MM.endo.frames.create(el, {
      mode: 'module', base: p.base, entry: entry, fn: fn, args: args || [], ctx: ctx,
      label: label || ((p.manifest && p.manifest.title) || p.id), selection: selection,
      // Tiles fill their cell; drawer, dock and views take the content's height.
      autoHeight: fn !== 'render' || !(args && args[0] && args[0].kind)
    });
  }

  /** The instance shape shells expect, calling through the (restartable) frame handle. */
  function frameInstance(h, extraDestroy) {
    return {
      suspend: function () { h.suspend(); },
      resume: function () { h.resume(); },
      destroy: function () { if (extraDestroy) extraDestroy(); h.destroy(); }
    };
  }

  /** Kinds first (they must exist before tiles render), then the rest. */
  function apply(p) {
    p.state = 'loading';
    p.error = '';
    var kinds = contrib(p, 'kinds');
    // Check that every kind's module graph can be shipped before registering.
    return Promise.all(kinds.map(function (k) {
      return MM.endo.frames.loadModules(p.base, k.entry).then(function () { return k; });
    })).then(function (loaded) {
      loaded.forEach(function (k) {
        MM.endo.kinds[k.kind] = {
          plugin: p.id,
          render: function (el, tile, ctx) {
            // The using component's ctx: the kind gets no more than it (R1).
            return frameInstance(inFrame(p, el, k.entry, 'render', [tile], ctx, k.kind + ' (' + p.manifest.title + ')'));
          }
        };
      });
      applyRibbon(p);
      applyNavigators(p);
      p.state = 'active';
    }).catch(function (e) {
      removeAll(p);
      p.state = 'error';
      p.error = e.message || String(e);
      console.warn('[plugins] ' + p.id + ' failed to load:', e);
    });
  }

  function removeAll(p) {
    contrib(p, 'kinds').forEach(function (k) {
      if (MM.endo.kinds[k.kind] && MM.endo.kinds[k.kind].plugin === p.id) delete MM.endo.kinds[k.kind];
    });
    document.querySelectorAll('[data-endo-plugin="' + p.id + '"]').forEach(function (el) { el.remove(); });
    // Groups a plugin created and no other plugin still uses.
    document.querySelectorAll('#ribbon .ribbon-group.endo-plugin-group').forEach(function (g) {
      if (!g.querySelector('.ribbon-btn')) g.remove();
    });
    contrib(p, 'navigators').concat(contrib(p, 'stage.views')).forEach(function (e) {
      var mode = modeFor(p, e);
      if (viewInstances[mode]) {
        ['sidebar', 'content'].forEach(function (k) {
          var inst = viewInstances[mode][k];
          if (inst && inst.destroy) { try { inst.destroy(); } catch (x) { /* keep going */ } }
        });
        delete viewInstances[mode];
      }
      if (hooks.currentMode() === mode) hooks.switchMode('services');
    });
  }

  // ---- ribbon groups: join a group of the same name, or add one

  function groupLabel(g) {
    var l = g.querySelector('.ribbon-group-label');
    return l ? l.textContent.trim().toLowerCase() : '';
  }

  function applyRibbon(p) {
    var cmds = {};
    contrib(p, 'commands').forEach(function (c) { cmds[c.id] = c; });
    contrib(p, 'ribbon.groups').forEach(function (g) {
      var panel = document.getElementById(PANEL[g.tab]);
      if (!panel) return;
      var group = Array.prototype.filter.call(panel.querySelectorAll(':scope > .ribbon-group'), function (el) {
        return !el.classList.contains('endo-contrib') && groupLabel(el) === g.group.toLowerCase();
      })[0];
      if (!group) {
        group = document.createElement('div');
        group.className = 'ribbon-group endo-plugin-group';
        group.innerHTML = '<div class="ribbon-group-items"></div><div class="ribbon-group-label">' + esc(g.group) + '</div>';
        var grow = panel.querySelector(':scope > .ribbon-group-grow');
        panel.insertBefore(group, grow || null);
      }
      var items = group.querySelector('.ribbon-group-items');
      // Keep the plugins' order (index.json, then installed) in a shared
      // group, also when a plugin is turned back on later.
      var myIndex = plugins.indexOf(p);
      var before = Array.prototype.filter.call(items.querySelectorAll('[data-endo-plugin]'), function (el) {
        return plugins.indexOf(byId(el.getAttribute('data-endo-plugin'))) > myIndex;
      })[0] || null;
      g.commands.forEach(function (rc) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'ribbon-btn';
        b.id = 'plugin-' + rc.id.replace(/[^A-Za-z0-9-]/g, '-');
        b.setAttribute('data-endo-plugin', p.id);
        b.setAttribute('data-endo-command', rc.id);
        b.title = rc.title || (cmds[rc.id] && cmds[rc.id].title) || rc.label;
        b.innerHTML = '<i class="bi bi-' + esc(rc.icon || 'puzzle') + '"></i><span>' + esc(rc.label) + '</span>';
        b.addEventListener('click', function () { run(rc.id).catch(function () { /* reported by run() */ }); });
        items.insertBefore(b, before);
      });
    });
  }

  // ---- navigators (tabs under the left pane) and stage views

  function modeFor(p, e) { return e.shell || ('plugin:' + p.id + '/' + e.id); }

  function applyNavigators(p) {
    var group = document.querySelector('#sidebarSwitch .sidebar-switch-group');
    contrib(p, 'navigators').forEach(function (nav) {
      var mode = modeFor(p, nav);
      if (nav.shell && !hooks.views[nav.shell]) {
        console.warn('[plugins] ' + p.id + ': the shell has no view "' + nav.shell + '"');
        return;
      }
      if (!nav.shell) ensureViewContainers(p, nav, mode);
      if (!group) return;
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'sidebar-switch-tab';
      b.id = 'sidebarSwitch-' + mode.replace(/[^A-Za-z0-9-]/g, '-');
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', 'false');
      b.setAttribute('data-mode', mode);
      b.setAttribute('data-endo-plugin', p.id);
      b.title = nav.title;
      b.innerHTML = '<i class="bi bi-' + esc(nav.icon || 'puzzle') + '"></i><span>' + esc(nav.title) + '</span>';
      b.addEventListener('click', function () { hooks.switchMode(mode); });
      var myIndex = plugins.indexOf(p);
      var before = Array.prototype.filter.call(group.querySelectorAll('[data-endo-plugin]'), function (el) {
        return plugins.indexOf(byId(el.getAttribute('data-endo-plugin'))) > myIndex;
      })[0] || null;
      group.insertBefore(b, before);
    });
    // A stage view without a navigator of the same id gets containers too.
    contrib(p, 'stage.views').forEach(function (v) {
      if (!v.shell) ensureViewContainers(p, v, modeFor(p, v));
    });
  }

  function ensureViewContainers(p, entry, mode) {
    if (document.querySelector('[data-endo-mode="' + mode + '"]')) return;
    var aside = document.querySelector('.app-sidebar');
    var sw = document.getElementById('sidebarSwitch');
    var side = document.createElement('div');
    side.className = 'sidebar-mode';
    side.setAttribute('data-endo-mode', mode);
    side.setAttribute('data-endo-plugin', p.id);
    side.innerHTML = '<div class="sidebar-content"></div>';
    if (aside) aside.insertBefore(side, sw || null);
    var main = document.querySelector('.app-content');
    var content = document.createElement('div');
    content.style.display = 'none';
    content.setAttribute('data-endo-mode', mode);
    content.setAttribute('data-endo-plugin', p.id);
    if (main) main.appendChild(content);
  }

  /** app.js calls this on every view change: mount, resume or suspend entry views (R5). */
  function modeChanged(mode) {
    Object.keys(viewInstances).forEach(function (m) {
      if (m === mode) return;
      ['sidebar', 'content'].forEach(function (k) {
        var inst = viewInstances[m][k];
        if (inst && inst.suspend) { try { inst.suspend(); } catch (e) { /* keep going */ } }
      });
    });
    if (!/^plugin:/.test(mode)) return;
    var m = /^plugin:([^/]+)\/(.+)$/.exec(mode);
    var p = m && byId(m[1]);
    if (!isActive(p)) return;
    var nav = contrib(p, 'navigators').filter(function (e) { return e.id === m[2] && !e.shell; })[0];
    var view = contrib(p, 'stage.views').filter(function (e) { return e.id === m[2] && !e.shell; })[0];
    var slot = viewInstances[mode] = viewInstances[mode] || {};
    var side = document.querySelector('.sidebar-mode[data-endo-mode="' + mode + '"] .sidebar-content');
    var content = document.querySelector('.app-content > [data-endo-mode="' + mode + '"]');
    [['sidebar', nav, side], ['content', view, content]].forEach(function (t) {
      var key = t[0], spec = t[1], el = t[2];
      if (!spec || !el) return;
      if (slot[key]) { slot[key].resume(); return; }
      slot[key] = frameInstance(inFrame(p, el, spec.entry, 'mount', [], pluginCtx(p), spec.title + ' (' + p.manifest.title + ')'));
    });
  }

  // ------------------------------------------------------------ commands

  /** A plugin's own ctx: its declared capabilities, no service binding. */
  function pluginCtx(p) {
    return MM.endo.makeCtx({ component: 'plugin.' + p.id, title: p.manifest.title,
                             requires: p.manifest.requires || {}, binds: { consul: '' } }, { base: p.base });
  }

  function findCommand(id) {
    for (var i = 0; i < plugins.length; i++) {
      var p = plugins[i];
      if (!isActive(p)) continue;
      var c = contrib(p, 'commands').filter(function (x) { return x.id === id; })[0];
      if (c) return { plugin: p, command: c };
    }
    return null;
  }

  /** Run a plugin command by id. Resolves when the command has run. */
  function run(id) {
    var hit = findCommand(id);
    if (!hit) return Promise.reject(new Error('No active plugin provides the command "' + id + '"'));
    var p = hit.plugin, c = hit.command;
    var fail = function (e) {
      if (MM.showToast) MM.showToast(p.manifest.title, (c.title || id) + ' failed: ' + (e.message || e), 'danger');
      throw e;
    };
    if (c.entry) {
      // A short-lived, invisible frame: run(ctx) and gone.
      var holder = document.createElement('div');
      holder.className = 'endo-frame-command';
      holder.hidden = true;
      document.body.appendChild(holder);
      var h = inFrame(p, holder, c.entry, 'run', [], pluginCtx(p), c.title + ' (' + p.manifest.title + ')');
      var done = function () { h.destroy(); holder.remove(); };
      return h.ready.then(function (result) { done(); return result; }, function (e) { done(); return fail(e); });
    }
    if (c.window) {
      return window.electronAPI.openPlugin(p.id, {}).then(function (r) {
        if (!r || !r.ok) throw new Error((r && r.error) || 'the window did not open');
        return r;
      }).catch(fail);
    }
    var action = hooks.actions[c.shell];
    if (typeof action !== 'function') return fail(new Error('the shell has no action "' + c.shell + '"'));
    return Promise.resolve().then(function () { return action(); }).catch(fail);
  }

  // ------------------------------------------------------------ public queries

  /** Kinds of active plugins, for the linter: kind -> { plugin, schema, needs }. */
  function kindInfo() {
    var out = {};
    plugins.forEach(function (p) {
      if (!isActive(p)) return;
      contrib(p, 'kinds').forEach(function (k) { out[k.kind] = { plugin: p.id, schema: k.schema, needs: k.needs || [] }; });
    });
    return out;
  }

  /** Every kind a known plugin (active or not) provides: kind -> { plugin, title, state }. */
  function knownKinds() {
    var out = {};
    plugins.forEach(function (p) {
      contrib(p, 'kinds').forEach(function (k) {
        out[k.kind] = { plugin: p.id, title: (p.manifest && p.manifest.title) || p.id, state: p.state };
      });
    });
    return out;
  }

  function entriesOf(point, filter) {
    var out = [];
    plugins.forEach(function (p) {
      if (!isActive(p)) return;
      contrib(p, point).forEach(function (e) {
        if (!filter || filter(e)) out.push({ plugin: p, entry: e, key: p.id + '/' + e.id });
      });
    });
    return out;
  }

  /** Drawer tabs of active plugins: [{ key, title, icon, mount(el, extraCtx) }]. */
  function drawerTabs() {
    return entriesOf('drawer.tabs').map(function (t) {
      return {
        key: t.key, title: t.entry.title, icon: t.entry.icon, plugin: t.plugin.id,
        mount: function (el, extra) {
          var sel = extra && extra.selection ? extra.selection() : null;
          var h = inFrame(t.plugin, el, t.entry.entry, 'mount', [], pluginCtx(t.plugin), t.entry.title + ' (' + t.plugin.manifest.title + ')', sel);
          // The frame reads the selection from pushes, not by calling back.
          var off = extra && extra.onSelection ? extra.onSelection(function (s) { h.setSelection(s); }) : null;
          return Promise.resolve(frameInstance(h, off));
        }
      };
    });
  }

  /** Dock sections for a component layer: [{ key, title, render(el, selection, extra) }]. */
  function dockSections(layer) {
    return entriesOf('dock.sections', function (e) { return !e.for || !e.for.length || e.for.indexOf(layer) >= 0; })
      .map(function (s) {
        return {
          key: s.key, title: s.entry.title, plugin: s.plugin.id,
          render: function (el, selection) {
            var h = inFrame(s.plugin, el, s.entry.entry, 'render', [selection], pluginCtx(s.plugin),
                            s.entry.title + ' (' + s.plugin.manifest.title + ')', selection);
            return Promise.resolve(frameInstance(h));
          }
        };
      });
  }

  function list() {
    return plugins.map(function (p) {
      return { id: p.id, title: (p.manifest && p.manifest.title) || p.id, version: p.manifest && p.manifest.version,
               source: p.source, isolation: p.manifest && p.manifest.isolation, state: p.state,
               error: p.error || '', issues: (p.issues || []).map(function (i) { return i.rule + ' ' + i.path + ': ' + i.message; }) };
    });
  }

  function state(id) { var p = byId(id); return p ? p.state : 'missing'; }

  // ------------------------------------------------------------ enable / disable

  function setEnabled(id, on) {
    var p = byId(id);
    if (!p || p.state === 'refused' || p.state === 'unavailable' || p.state === 'blocked') return Promise.resolve(false);
    var off = disabledSet();
    if (on) off.delete(id); else off.add(id);
    saveDisabled(off);
    if (!on) {
      removeAll(p);
      p.state = 'disabled';
      notify({ plugin: id, enabled: false });
      return Promise.resolve(true);
    }
    if (p.state === 'active') return Promise.resolve(true);
    return apply(p).then(function () {
      notify({ plugin: id, enabled: p.state === 'active' });
      return p.state === 'active';
    });
  }

  // ------------------------------------------------------------ manager (Administrator → Plugins)

  var STATE_TEXT = { active: 'active', disabled: 'off', refused: 'refused', error: 'failed to load',
                     unavailable: 'desktop app only', loading: 'loading', pending: 'pending', blocked: 'not allowed' };

  function contributionsText(p) {
    var c = (p.manifest && p.manifest.contributes) || {};
    return Object.keys(c).map(function (k) {
      var arr = c[k] || [];
      var names = arr.map(function (e) { return e.kind || e.group || e.title || e.id; });
      return k + ': ' + names.join(', ');
    }).join(' · ');
  }

  var managerModal = null;
  function openManager() {
    var el = document.getElementById('pluginsModal');
    if (!el) {
      el = document.createElement('div');
      el.className = 'modal fade';
      el.id = 'pluginsModal';
      el.tabIndex = -1;
      el.setAttribute('aria-labelledby', 'pluginsModalTitle');
      el.setAttribute('aria-hidden', 'true');
      el.innerHTML = '<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content">' +
        '<div class="modal-header"><h5 class="modal-title" id="pluginsModalTitle">Plugins</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
        '<div class="modal-body"><p class="endo-note mb-2">Plugins add tile kinds, tabs, views and commands to this GUI. ' +
        'Turning one off takes effect at once, on this PC only. Installed plugins live in ' +
        '<code>%APPDATA%\\DevAtServGUI\\plugins\\&lt;id&gt;\\</code>.</p><div id="pluginsList"></div></div></div></div>';
      document.body.appendChild(el);
    }
    managerModal = bootstrap.Modal.getOrCreateInstance(el);
    renderManager();
    managerModal.show();
  }

  function renderManager() {
    var box = document.getElementById('pluginsList');
    if (!box) return;
    box.innerHTML = plugins.map(function (p) {
      var m = p.manifest || {};
      var canToggle = p.state !== 'refused' && p.state !== 'unavailable' && p.state !== 'blocked' && !!p.manifest;
      var isWindow = m.isolation === 'window' && p.state !== 'refused' && p.state !== 'unavailable';
      var allowed = isWindow && windowRecords[p.id] && windowRecords[p.id].allowed;
      var on = p.state === 'active' || p.state === 'loading' || p.state === 'pending' || p.state === 'error';
      var errs = (p.issues || []).filter(function (i) { return i.severity === 'error'; });
      return '<div class="plugin-row state-' + p.state + '" data-plugin="' + esc(p.id) + '">' +
        '<div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" role="switch"' +
        ' id="pluginToggle-' + esc(p.id) + '"' + (on ? ' checked' : '') + (canToggle ? '' : ' disabled') +
        ' aria-label="' + esc((m.title || p.id) + ' enabled') + '"></div>' +
        '<div class="plugin-main"><div class="plugin-title"><strong>' + esc(m.title || p.id) + '</strong> ' +
        '<code>' + esc(p.id) + '</code> <span class="endo-muted">' + esc(m.version || '') + ' · ' + esc(p.source) +
        ' · ' + esc(m.isolation || '?') + '</span>' +
        '<span class="plugin-state">' + esc(STATE_TEXT[p.state] || p.state) + '</span></div>' +
        (m.description ? '<div class="plugin-desc">' + esc(m.description) + '</div>' : '') +
        '<div class="plugin-contrib">' + esc(contributionsText(p)) + '</div>' +
        (isWindow ? '<div class="form-check form-switch plugin-allow mt-1"><input class="form-check-input" type="checkbox" role="switch"' +
          ' id="pluginAllow-' + esc(p.id) + '"' + (allowed ? ' checked' : '') + '>' +
          '<label class="form-check-label" for="pluginAllow-' + esc(p.id) + '">Allowed to open its own window and start processes' +
          ' <span class="endo-muted">(window-plugin allow-list)</span></label></div>' : '') +
        (p.error ? '<div class="endo-error mt-1">' + esc(p.error) + '</div>' : '') +
        (errs.length ? '<div class="endo-refused mt-1">' + MM.endo.issuesListHtml(errs) + '</div>' : '') +
        '</div></div>';
    }).join('') || '<p class="endo-muted">No plugins found.</p>';
    box.querySelectorAll('.form-check-input').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var id = inp.closest('.plugin-row').getAttribute('data-plugin');
        inp.disabled = true;
        var change = /^pluginAllow-/.test(inp.id) ? setAllowed(id, inp.checked) : setEnabled(id, inp.checked);
        change.then(renderManager, renderManager);
      });
    });
  }

  // ------------------------------------------------------------ init

  function init(h) {
    hooks = Object.assign(hooks, h || {});
    var btn = document.getElementById('btnAdminPlugins');
    if (btn) btn.addEventListener('click', openManager);
    var api = window.electronAPI;
    var winList = api && typeof api.windowPlugins === 'function'
      ? Promise.resolve(api.windowPlugins()).catch(function () { return []; }) : Promise.resolve([]);
    Promise.all([discover(), fetchJson(SCHEMA_URL).catch(function () { return null; }), winList])
      .then(function (r) {
        (r[2] || []).forEach(function (rec) { windowRecords[rec.id] = rec; });
        plugins = r[0];
        assess(plugins, r[1]);
        // Apply in index order so ribbon contributions keep a stable order.
        return plugins.reduce(function (chain, p) {
          return chain.then(function () { return p.state === 'pending' ? apply(p) : null; });
        }, Promise.resolve());
      })
      .catch(function (e) { console.warn('[plugins] loading failed:', e); })
      .then(function () {
        readyResolve();
        notify({ ready: true });
      });
    return ready;
  }

  MM.endo.plugins = {
    init: init,
    ready: ready,
    run: run,
    list: list,
    state: state,
    setEnabled: setEnabled,
    kindInfo: kindInfo,
    knownKinds: knownKinds,
    drawerTabs: drawerTabs,
    dockSections: dockSections,
    modeChanged: modeChanged,
    openManager: openManager,
    onChange: function (fn) {
      listeners.push(fn);
      return function () { listeners = listeners.filter(function (f) { return f !== fn; }); };
    }
  };
})();
