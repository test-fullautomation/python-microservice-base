/**
 * @fileoverview State and workflow of the infrastructure configuration feature.
 *
 * Infrastructure configuration is a separate document in the Configuration Hub
 * (config_type: "infrastructure"), keyed by the same id as its testbench.
 * It manages Nomad node placement (node, datacenters).
 *
 * DOM-free: runs under node tests and in browser (MM.infraStoreApi).
 * Uses shared helpers from ConfigCommon.js.
 *
 * @version 1.0.0
 */
(function (root, factory) {
  'use strict';
  var Common = (typeof module === 'object' && module.exports && typeof require === 'function')
    ? require('./ConfigCommon.js')
    : (root.MicroserviceManager || {}).configCommon;
  var api = factory(Common);
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    var MM = root.MicroserviceManager = root.MicroserviceManager || {};
    MM.infraStoreApi = api;
  }
})(typeof window !== 'undefined' ? window : globalThis, function (Common) {
  'use strict';

  var INFRA = 'infrastructure';
  var TB = 'testbench';

  var _clone = Common.clone;
  var canon = Common.canon;
  var _splitList = Common.splitList;

  var ACTIVE_VERSION_KEY = 'mm_infra_active_version:';

  function createStore(api, opts) {
    opts = opts || {};
    var storage = opts.storage || null;
    var selectedVersions = {};
    var emitter = Common.createEmitter();
    var emit = function () { emitter.emit(state); };
    var subscribe = emitter.subscribe;

    var state = {
      list: { status: 'idle', items: [], error: null },
      testbenches: [], // known testbenches from hub, so dropdown can suggest IDs
      current: null,
      notice: null,    // { kind, text }
      failure: null    // { service, message, canRetry }
    };

    var failHandler = Common.createFailureHandler(state, emit);
    var _fail = failHandler.fail;
    var _clearFailure = failHandler.clear;
    var retry = failHandler.retry;

    function _notice(kind, text) { Common.setNotice(state, kind, text); }

    function _saveActiveVersion(id, ver) {
      if (ver !== undefined && ver !== null) {
        selectedVersions[id] = ver;
      } else {
        delete selectedVersions[id];
      }
      try {
        if (storage) {
          if (ver !== undefined && ver !== null) {
            storage.setItem(ACTIVE_VERSION_KEY + id, String(ver));
          } else {
            storage.removeItem(ACTIVE_VERSION_KEY + id);
          }
        }
      } catch (e) {}
      if (state.list && state.list.items) {
        var it = state.list.items.find(function (x) { return x.id === id; });
        if (it) it.activeVersion = ver;
      }
    }

    function _getActiveVersion(id) {
      if (selectedVersions[id] !== undefined) return selectedVersions[id];
      try {
        if (storage) {
          var saved = storage.getItem(ACTIVE_VERSION_KEY + id);
          if (saved !== null && saved !== undefined && saved !== '') {
            var n = Number(saved);
            if (!isNaN(n)) {
              selectedVersions[id] = n;
              return n;
            }
          }
        }
      } catch (e) {}
      return undefined;
    }

    // ------------------------------------------------------------ list

    function loadList() {
      state.list.status = 'loading';
      emit();

      // Load both infrastructure configs and testbenches for dropdown suggestion
      var pInfra = api.listConfigurations(INFRA);
      var pTb = api.listConfigurations(TB).catch(function () { return []; });

      return Promise.all([pInfra, pTb]).then(function (results) {
        var items = results[0] || [];
        items.forEach(function (it) {
          var act = _getActiveVersion(it.id);
          if (act !== undefined) it.activeVersion = act;
        });
        state.list = { status: 'ok', items: items, error: null };
        state.testbenches = results[1] || [];
        _clearFailure();
        emit();
      }).catch(function (err) {
        state.list.status = 'error';
        state.list.error = err.message;
        _fail(err, loadList);
        emit();
      });
    }

    // ---------------------------------------------------------- config

    function _blank(id) {
      return {
        id: id,
        name: id,
        node: 'client1',
        datacenters: 'dc1',
        version: 0,
        isDefault: true,
        isNew: true,
        readOnly: false,
        viewingVersion: null,
        baseline: null,
        versions: [],
        versionsError: null,
        saving: false,
        saveError: null
      };
    }

    function _contentPayload(cur) {
      return {
        node: String(cur.node || '').trim(),
        datacenters: _splitList(cur.datacenters)
      };
    }

    function _payload(cur) {
      return {
        id: cur.id,
        node: String(cur.node || '').trim(),
        datacenters: _splitList(cur.datacenters)
      };
    }

    function _mark(cur) {
      cur.baseline = canon(_contentPayload(cur));
    }

    function open(id, optVersion) {
      id = String(id || '').trim();
      if (!id) return Promise.resolve(null);

      _clearFailure();
      _notice(null);

      var targetVer = optVersion;
      if (targetVer === undefined) {
        targetVer = _getActiveVersion(id);
      }

      return api.getConfiguration(INFRA, id, targetVer).then(function (doc) {
        var p = doc.payload || {};
        var cur = _blank(doc.id || id);
        cur.name = doc.name || doc.id || id;
        cur.node = p.node || '';
        cur.datacenters = Array.isArray(p.datacenters) ? p.datacenters.join(', ') : (p.datacenters || '');
        cur.version = doc.version;
        cur.isDefault = false;
        cur.isNew = false;
        _mark(cur);
        state.current = cur;
        _saveActiveVersion(id, doc.version);
        emit();
        return loadVersions().then(function () { return cur; });
      }).catch(function (err) {
        if (err.code === 'NOT_FOUND') {
          if (targetVer !== undefined) {
            _saveActiveVersion(id, null);
            return open(id);
          }
          // Fall back to default config (v0)
          return api.getDefaultConfiguration(INFRA).then(function (def) {
            var cur = _blank(id);
            if (def && def.payload) {
              cur.node = def.payload.node || 'client1';
              cur.datacenters = Array.isArray(def.payload.datacenters) ? def.payload.datacenters.join(', ') : (def.payload.datacenters || 'dc1');
            }
            cur.version = 0;
            cur.isDefault = true;
            cur.isNew = true;
            _mark(cur);
            state.current = cur;
            _notice('info', 'Showing default infrastructure settings for "' + id + '". Click Save to configure.');
            emit();
            return cur;
          }).catch(function (defErr) {
            _fail(defErr, function () { return open(id, optVersion); });
            emit();
            return null;
          });
        }
        _fail(err, function () { return open(id, optVersion); });
        _notice('danger', err.message);
        emit();
        return null;
      });
    }

    function openVersion(version) {
      var cur = state.current;
      if (!cur || cur.isDefault) return Promise.resolve();

      return api.getConfiguration(INFRA, cur.id, version).then(function (doc) {
        var next = _clone(cur);
        var p = doc.payload || {};
        next.node = p.node || '';
        next.datacenters = Array.isArray(p.datacenters) ? p.datacenters.join(', ') : (p.datacenters || '');
        next.version = doc.version;
        next.readOnly = true;
        next.viewingVersion = doc.version;
        _mark(next);
        state.current = next;
        _notice(null);
        emit();
      }).catch(function (err) {
        _fail(err, function () { return openVersion(version); });
        _notice('danger', err.message);
        emit();
      });
    }

    function loadVersionForUse(version) {
      var cur = state.current;
      if (!cur || cur.isDefault) return Promise.resolve(null);

      return api.getConfiguration(INFRA, cur.id, version).then(function (doc) {
        var next = _clone(cur);
        var p = doc.payload || {};
        next.node = p.node || '';
        next.datacenters = Array.isArray(p.datacenters) ? p.datacenters.join(', ') : (p.datacenters || '');
        next.version = doc.version;
        next.readOnly = false;
        next.viewingVersion = null;
        _mark(next);
        state.current = next;
        _saveActiveVersion(cur.id, doc.version);
        _notice('success', 'Loaded version ' + version + ' to use.');
        emit();
        return next;
      }).catch(function (err) {
        _fail(err, function () { return loadVersionForUse(version); });
        _notice('danger', err.message);
        emit();
        return null;
      });
    }

    function loadVersions() {
      return Common.loadVersions({ api: api, type: INFRA, cur: state.current, emit: emit });
    }

    function setNode(val) {
      if (!state.current || state.current.readOnly) return;
      state.current.node = val;
      emit();
    }

    function setDatacenters(val) {
      if (!state.current || state.current.readOnly) return;
      state.current.datacenters = val;
      emit();
    }

    function setId(id) {
      if (!state.current || state.current.readOnly) return;
      var cur = state.current;
      var newId = String(id || '').trim();
      if (!newId || cur.id === newId) return;
      var oldId = cur.id;

      if (state.list.items.some(function (x) { return x.id === newId && x !== cur; })) {
        _notice('warning', 'An infrastructure configuration with ID "' + newId + '" already exists.');
        emit();
        return;
      }

      cur.id = newId;
      var it = state.list.items.find(function (x) { return x.id === oldId; });
      if (it) it.id = newId;

      var act = _getActiveVersion(oldId);
      if (act !== undefined) {
        _saveActiveVersion(oldId, null);
        _saveActiveVersion(newId, act);
      }

      try {
        if (storage) {
          var grpRaw = storage.getItem('mm_infra_groups');
          if (grpRaw) {
            var grps = JSON.parse(grpRaw);
            if (grps[oldId]) {
              grps[newId] = grps[oldId];
              delete grps[oldId];
              storage.setItem('mm_infra_groups', JSON.stringify(grps));
            }
          }
        }
      } catch (e) {}

      if (api && typeof api.renameConfiguration === 'function' && !cur.isNew && !cur.isDefault) {
        api.renameConfiguration(INFRA, oldId, newId, cur.name).catch(function () {});
      }
      emit();
    }

    function setName(name) {
      if (!state.current || state.current.readOnly) return;
      var cur = state.current;
      var newName = (name !== undefined && name !== null) ? String(name).trim() : '';
      if (!newName || cur.name === newName) return;
      cur.name = newName;
      var it = state.list.items.find(function (x) { return x.id === cur.id; });
      if (it) it.name = newName;
      if (api && typeof api.renameConfiguration === 'function' && !cur.isNew && !cur.isDefault) {
        api.renameConfiguration(INFRA, cur.id, cur.id, newName).catch(function () {});
      }
      emit();
    }

    function validate() {
      var cur = state.current;
      var errors = {};
      if (!cur) return { ok: true, errors: errors };

      if (!String(cur.node || '').trim()) {
        errors.node = 'Node is required';
      }
      if (!_splitList(cur.datacenters).length) {
        errors.datacenters = 'At least one datacenter is required';
      }
      return { ok: Object.keys(errors).length === 0, errors: errors };
    }

    function isDirty() {
      var cur = state.current;
      if (!cur || cur.readOnly) return false;
      return cur.isDefault || canon(_contentPayload(cur)) !== cur.baseline;
    }

    function isChanged() {
      var cur = state.current;
      if (!cur || cur.readOnly) return false;
      return canon(_contentPayload(cur)) !== cur.baseline;
    }

    function canSave() {
      var cur = state.current;
      return Common.canSave(cur, validate().ok, isDirty());
    }

    function save() {
      var cur = state.current;
      if (!cur || cur.readOnly || cur.saving) return Promise.resolve({ ok: false });

      var v = validate();
      if (!v.ok) { emit(); return Promise.resolve({ ok: false, blocked: true }); }

      var creating = cur.isDefault || cur.isNew || (cur.version === 0);
      var payload = _payload(cur);
      cur.saving = true;
      cur.saveError = null;
      emit();

      // Always UpdateConfiguration (creates v1 if version 0 default, v2+ if already exists)
      return api.updateConfiguration(INFRA, cur.id, cur.name || cur.id, payload).then(function (doc) {
        cur.saving = false;
        cur.isDefault = false;
        cur.isNew = false;
        cur.version = doc.version;
        cur.latestVersion = doc.version;
        _saveActiveVersion(cur.id, doc.version);
        _mark(cur);
        _notice('success', creating
          ? ('Created infrastructure configuration as version ' + doc.version + '.')
          : ('Infrastructure configuration saved as version ' + doc.version + '.'));
        _clearFailure();
        emit();
        loadVersions();
        loadList();
        return { ok: true, version: doc.version };
      }).catch(function (err) {
        cur.saving = false;
        cur.saveError = Common.saveErrorOf(err);
        emit();
        return { ok: false, error: err };
      });
    }

    function closeCurrent() {
      var cur = state.current;
      if (cur && cur.isNew) {
        state.list.items = state.list.items.filter(function (x) { return x.id !== cur.id; });
      }
      state.current = null;
      _notice(null);
      emit();
    }

    function dismissNotice() {
      _notice(null);
      emit();
    }

    function duplicate(sourceId, newId, newName) {
      newId = String(newId || '').trim();
      if (!newId) return Promise.resolve({ ok: false, field: 'id', message: 'Infrastructure id is required' });
      if (newName === undefined || newName === null) {
        newName = newId;
      } else {
        newName = String(newName).trim();
      }
      if (!newName) newName = newId;

      if (state.list.items.some(function (i) { return i.id === newId && !i.isNew; })) {
        return Promise.resolve({ ok: false, field: 'id', message: 'An infrastructure with id "' + newId + '" already exists' });
      }

      var sourcePromise;
      if (state.current && state.current.id === sourceId) {
        sourcePromise = Promise.resolve({
          name: state.current.name || sourceId,
          payload: {
            node: state.current.node,
            datacenters: _splitList(state.current.datacenters)
          }
        });
      } else {
        var actVer = _getActiveVersion(sourceId);
        sourcePromise = api.getConfiguration(INFRA, sourceId, actVer).then(function (doc) {
          var p = doc.payload || {};
          return {
            name: doc.name || doc.id || sourceId,
            payload: {
              node: p.node || 'client1',
              datacenters: Array.isArray(p.datacenters) ? p.datacenters : _splitList(p.datacenters || 'dc1')
            }
          };
        }).catch(function () {
          return api.getDefaultConfiguration(INFRA).then(function (def) {
            var dp = (def && def.payload) || {};
            return {
              name: sourceId,
              payload: {
                node: dp.node || 'client1',
                datacenters: Array.isArray(dp.datacenters) ? dp.datacenters : _splitList(dp.datacenters || 'dc1')
              }
            };
          });
        });
      }

      return sourcePromise.then(function (src) {
        var p = src.payload || {};
        var content = {
          node: String(p.node || 'client1').trim(),
          datacenters: Array.isArray(p.datacenters) ? p.datacenters : _splitList(p.datacenters || 'dc1')
        };

        return api.updateConfiguration(INFRA, newId, newName, content).then(function (res) {
          _notice('info', 'Infrastructure "' + newId + '" duplicated from "' + sourceId + '".');
          return loadList().then(function () {
            return open(newId).then(function () {
              return { ok: true, id: newId };
            });
          });
        });
      }).catch(function (err) {
        _notice('danger', 'Failed to duplicate infrastructure: ' + err.message);
        return { ok: false, message: err.message };
      });
    }

    function deleteItem(id) {
      return Common.deleteItem({
        api: api,
        type: INFRA,
        id: id,
        state: state,
        emit: emit,
        fail: _fail,
        notice: _notice,
        label: 'Infrastructure',
        onLocalDelete: function (delId) {
          _saveActiveVersion(delId, null);
        }
      });
    }

    return {
      state: state,
      subscribe: subscribe,
      loadList: loadList,
      open: open,
      duplicate: duplicate,
      deleteItem: deleteItem,
      openVersion: openVersion,
      loadVersionForUse: loadVersionForUse,
      loadVersions: loadVersions,
      setNode: setNode,
      setDatacenters: setDatacenters,
      setId: setId,
      setName: setName,
      validate: validate,
      isDirty: isDirty,
      isChanged: isChanged,
      canSave: canSave,
      save: save,
      closeCurrent: closeCurrent,
      getActiveVersion: _getActiveVersion,
      retry: retry,
      dismissNotice: dismissNotice,
      payload: function () { return state.current ? _payload(state.current) : null; }
    };
  }

  return { createStore: createStore, canon: canon };
});
