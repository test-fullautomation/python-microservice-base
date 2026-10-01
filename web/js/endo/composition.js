/**
 * @fileoverview Bench Endoskeleton compositions: which components one bench
 * shows and in which order (contract v1, milestone M2).
 *
 * Pure functions, shared by the GUI (browser global EndoComposition,
 * MM.endo.composition) and the Node tests. Fetching manifests and drawing
 * the stage are bench.js's job.
 *
 *   defaultComposition(services, bench, role) -> composition
 *   resolveEntries(comp, services)            -> [{ index, entry, service, folder, problem }]
 *   slotsFor(module)                          -> [slot]
 *   orderSlots(slots, order)                  -> { slots, issues }
 *
 * A service is { name, consulUrl, gui, address, port, status, ... } as the
 * Services sidebar knows it. A module is a resolved entry plus its state:
 *   ok       component.json passed the linter; its tiles are placed
 *   refused  component.json broke a rule; one slot lists the rule ids (R10)
 *   legacy   the GUI folder has no component.json; one slot opens its panel
 *   nogui    the service declares no GUI folder
 *   missing  no connected Consul has the service
 *   error    the manifest could not be fetched
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.EndoComposition = api;
    if (root.MicroserviceManager) {
      root.MicroserviceManager.endo = root.MicroserviceManager.endo || {};
      root.MicroserviceManager.endo.composition = api;
    }
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var ROLES = ['user', 'dev', 'admin'];

  /** Size of the one slot a module that shows no tiles gets. */
  var SLOT_SIZE = { refused: '2x1', legacy: '2x1', nogui: '1x1', missing: '1x1', error: '1x1' };

  /**
   * The composition used when none is stored: every service of the
   * connected Consuls that declares a GUI, in sidebar order.
   */
  function defaultComposition(services, bench, role) {
    var seen = {};
    var comps = [];
    (services || []).forEach(function (s) {
      if (!s || !s.gui || seen[s.name]) return;
      seen[s.name] = true;
      comps.push({ from: 'consul', service: s.name });
    });
    return {
      composition: (bench || 'default') + '/all',
      title: 'All components',
      shell: '^2.3',
      role: ROLES.indexOf(role) >= 0 ? role : 'user',
      plugins: [],
      components: comps
    };
  }

  /**
   * Find each entry's service and GUI folder. The first connected Consul
   * that has the service wins (the sidebar lists them in the same order).
   */
  function resolveEntries(comp, services) {
    var byName = {};
    (services || []).forEach(function (s) { if (s && !byName[s.name]) byName[s.name] = s; });
    return ((comp && comp.components) || []).map(function (entry, index) {
      var svc = byName[entry && entry.service] || null;
      var folder = String((entry && entry.gui) || (svc && svc.gui) || '').replace(/^[\/\\]+|[\/\\]+$/g, '');
      var problem = !svc ? 'missing' : !folder ? 'nogui' : null;
      return { index: index, entry: entry, service: svc, folder: folder, problem: problem };
    });
  }

  /** Stable key of a module: its component id when known, else the service. */
  function moduleId(mod) {
    return (mod.manifest && mod.manifest.component) || ('service:' + ((mod.entry && mod.entry.service) || '?'));
  }

  /**
   * Stage slots of one module. An ok module contributes its tiles (filtered
   * by entry.tiles); any other state contributes one slot that says why.
   * Returns [{ key, component, state, size, tile?, module }] and records
   * unknown entry.tiles in mod.warnings.
   */
  function slotsFor(mod) {
    var id = moduleId(mod);
    if (mod.state !== 'ok') {
      return [{ key: id, component: id, state: mod.state, size: SLOT_SIZE[mod.state] || '1x1', module: mod }];
    }
    var tiles = (mod.manifest && mod.manifest.tiles) || [];
    var wanted = mod.entry && Array.isArray(mod.entry.tiles) ? mod.entry.tiles : null;
    if (wanted) {
      var ids = tiles.map(function (t) { return t.id; });
      mod.warnings = (mod.warnings || []).concat(wanted.filter(function (w) { return ids.indexOf(w) < 0; })
        .map(function (w) {
          return { rule: 'C', severity: 'warn', component: id, path: 'components[' + mod.index + '].tiles',
                   message: 'tile "' + w + '" is not a tile of ' + id };
        }));
      tiles = tiles.filter(function (t) { return wanted.indexOf(t.id) >= 0; });
    }
    return tiles.map(function (t) {
      return { key: id + '/' + t.id, component: id, state: 'ok', size: t.size, tile: t, module: mod };
    });
  }

  /** Does an order entry name this slot? */
  function matches(pat, s) {
    if (pat.charAt(0) === '@') {
      var e = s.module && s.module.entry;
      return !!e && e.service === pat.slice(1);
    }
    return s.key === pat || s.component === pat;
  }

  /**
   * Order slots by the composition's `order`: "<component>/<tile>",
   * "<component>" (all its slots), "@<service>" (the slots of that
   * service's module, whatever its state) or "*" (everything not listed).
   * Unlisted slots go where "*" is, or at the end. Patterns that match
   * nothing are reported (C warnings) and skipped.
   */
  function orderSlots(slots, order) {
    var issues = [];
    if (!Array.isArray(order) || !order.length) return { slots: slots.slice(), issues: issues };
    var used = {};
    var head = [], tail = [], starSeen = false;
    order.forEach(function (pat, i) {
      if (pat === '*') { starSeen = true; return; }
      var hit = slots.filter(function (s) { return !used[s.key] && matches(pat, s); });
      if (!hit.length && !slots.some(function (s) { return matches(pat, s); })) {
        issues.push({ rule: 'C', severity: 'warn', component: '(order)', path: 'order[' + i + ']',
                      message: '"' + pat + '" matches no tile on this bench' });
      }
      hit.forEach(function (s) { used[s.key] = true; (starSeen ? tail : head).push(s); });
    });
    var rest = slots.filter(function (s) { return !used[s.key]; });
    return { slots: head.concat(rest, tail), issues: issues };
  }

  return {
    ROLES: ROLES,
    SLOT_SIZE: SLOT_SIZE,
    defaultComposition: defaultComposition,
    resolveEntries: resolveEntries,
    moduleId: moduleId,
    slotsFor: slotsFor,
    orderSlots: orderSlots
  };
});
