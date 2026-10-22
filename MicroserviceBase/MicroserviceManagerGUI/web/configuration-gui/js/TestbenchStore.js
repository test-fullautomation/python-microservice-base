/**
 * @fileoverview State and workflow of the testbench configuration feature.
 * Infrastructure configuration is a separate document with its own store
 * (InfraStore.js); nothing here reads or writes it.
 *
 * No DOM here. The view renders `store.state` and calls the store's methods;
 * the store talks to the Catalog and the Configuration Hub through the
 * injected `api` (see ConfigHubClient.js) and keeps the user's input in
 * memory, so a failed call never loses it.
 *
 * The store contains no device-specific logic: everything about a device
 * comes from its catalog entry (adapter, static_config, user_config_schema).
 * `deployment_descriptor` is never read, kept or sent; the provider
 * generates it.
 *
 * Loads in the browser (MM.testbenchStore) and under node (module.exports).
 *
 * @version 1.0.0
 */
(function (root, factory) {
  'use strict';
  var SF = (typeof module === 'object' && module.exports && typeof require === 'function')
    ? require('./SchemaForm.js')
    : (root.MicroserviceManager || {}).schemaForm;
  var Common = (typeof module === 'object' && module.exports && typeof require === 'function')
    ? require('./ConfigCommon.js')
    : (root.MicroserviceManager || {}).configCommon;
  var api = factory(SF, Common);
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    var MM = root.MicroserviceManager = root.MicroserviceManager || {};
    MM.testbenchStoreApi = api;
  }
})(typeof window !== 'undefined' ? window : globalThis, function (SF, Common) {
  'use strict';

  var TB = 'testbench';
  var VERSION_KEY = 'mm_tb_catalog_version:';
  var ACTIVE_VERSION_KEY = 'mm_tb_active_version:';

  var _clone = Common.clone;
  var canon = Common.canon;
  var _splitList = Common.splitList;

  var _keySeq = 0;

  function createStore(api, opts) {
    opts = opts || {};
    var storage = opts.storage || null;
    var selectedVersions = {};
    var emitter = Common.createEmitter();
    var emit = function () { emitter.emit(state); };
    var subscribe = emitter.subscribe;

    var state = {
      list: { status: 'idle', items: [], error: null },
      catalog: { status: 'idle', models: [], error: null, version: null },
      current: null,
      notice: null,      // {kind, text}
      failure: null      // {service, message, canRetry} of the last failed load
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
      return api.listConfigurations(TB).then(function (items) {
        items.forEach(function (it) {
          var act = _getActiveVersion(it.id);
          if (act !== undefined) it.activeVersion = act;
        });
        state.list = { status: 'ok', items: items, error: null };
        _clearFailure('hub');
        emit();
      }).catch(function (err) {
        state.list.status = 'error';
        state.list.error = err.message;
        _fail(err, loadList);
        emit();
      });
    }

    // --------------------------------------------------------- catalog

    function loadCatalog() {
      state.catalog.status = 'loading';
      emit();
      return api.listDeviceModels().then(function (models) {
        state.catalog.models = models;
        state.catalog.status = 'ok';
        state.catalog.error = null;
        _clearFailure('catalog');
        emit();
      }).catch(function (err) {
        state.catalog.status = 'error';
        state.catalog.error = err.message;
        _fail(err, loadCatalog);
        emit();
      });
    }

    function _noteCatalogVersion(cur) {
      return api.getCatalogVersion().then(function (v) {
        state.catalog.version = v;
        var seen = null;
        try { seen = storage && storage.getItem(VERSION_KEY + cur.id); } catch (e) { seen = null; }
        cur.catalogChanged = !!(seen && seen !== v);
      }).catch(function () { /* version is advisory only */ });
    }

    // --------------------------------------------------------- devices

    function _newKey() { return 'd' + (++_keySeq); }

    function _device(base) {
      return Object.assign({
        key: _newKey(),
        device_id: '', catalog_ref: '', adapter: '',
        static_config: {}, capabilities: [],
        isNew: false,         // added in this session, not yet saved
        editing: false,       // saved device explicitly unlocked via Edit
        savedDeviceId: '',    // device_id as last saved (restored on cancel)
        touched: false,       // user edited a setting: validate it now
        open: false,
        schema: null,
        schemaStatus: 'idle', // idle | loading | ok | missing | error
        schemaError: null,
        model: null,          // catalog entry (manufacturer, model, ...)
        savedUserConfig: {},
        raw: {}
      }, base);
    }

    function _rawFrom(schema, values) {
      var raw = {};
      SF.fields(schema).forEach(function (f) { raw[f.name] = SF.toRaw(f, (values || {})[f.name]); });
      Object.keys(values || {}).forEach(function (k) {
        if (!(k in raw)) raw[k] = values[k];
      });
      return raw;
    }

    function _savedDevice(d) {
      return _device({
        device_id: d.device_id || '',
        savedDeviceId: d.device_id || '',
        catalog_ref: d.catalog_ref || '',
        adapter: d.adapter || '',
        static_config: _clone(d.static_config) || {},
        savedUserConfig: _clone(d.user_config) || {},
        raw: _clone(d.user_config) || {}
      });
    }

    function _suggestId(cur, base) {
      var slug = String(base || 'device').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'device';
      var id = slug, n = 2;
      var used = cur.devices.map(function (d) { return d.device_id; });
      while (used.indexOf(id) !== -1) id = slug + '_' + (n++);
      return id;
    }

    function addDevice(catalogId) {
      var cur = state.current;
      if (!cur || cur.readOnly) return Promise.resolve(false);
      return api.getDeviceModel(catalogId).then(function (m) {
        var dev = _device({
          device_id: _suggestId(cur, m.catalog_id),
          catalog_ref: m.catalog_id,
          adapter: m.adapter,
          static_config: _clone(m.static_config) || {},
          capabilities: m.capabilities,
          schema: m.user_config_schema,
          schemaStatus: 'ok',
          model: m,
          isNew: true,
          open: true
        });
        dev.raw = _rawFrom(dev.schema, SF.defaults(dev.schema));
        cur.devices.push(dev);
        _clearFailure('catalog');
        _noteCatalogVersion(cur).then(emit);
        emit();
        return true;
      }).catch(function (err) {
        _fail(err, function () { return addDevice(catalogId); });
        _notice('danger', err.message);
        emit();
        return false;
      });
    }

    /** Open a device's form: load its catalog entry for the schema. */
    function openDevice(key) {
      var cur = state.current;
      var dev = cur && _find(cur, key);
      if (!dev) return Promise.resolve();
      dev.open = true;
      if (dev.schemaStatus === 'ok' || dev.schemaStatus === 'loading') { emit(); return Promise.resolve(); }
      dev.schemaStatus = 'loading';
      emit();
      return api.getDeviceModel(dev.catalog_ref).then(function (m) {
        dev.model = m;
        dev.schema = m.user_config_schema;
        dev.capabilities = m.capabilities;
        dev.schemaStatus = 'ok';
        dev.raw = _rawFrom(dev.schema, dev.savedUserConfig);
        _clearFailure('catalog');
        return _noteCatalogVersion(cur);
      }).catch(function (err) {
        if (err.code === 'NOT_FOUND') {
          // The model left the catalog: the device stays as it was saved.
          dev.schemaStatus = 'missing';
          dev.schemaError = 'Catalog entry "' + dev.catalog_ref + '" no longer exists. Shown as saved.';
        } else {
          dev.schemaStatus = 'error';
          dev.schemaError = err.message;
          _fail(err, function () { return openDevice(key); });
        }
      }).then(emit);
    }

    function closeDevice(key) {
      var dev = state.current && _find(state.current, key);
      if (dev) { dev.open = false; emit(); }
    }

    function _find(cur, key) {
      for (var i = 0; i < cur.devices.length; i++) if (cur.devices[i].key === key) return cur.devices[i];
      return null;
    }

    /** A saved device is read-only until the user clicks Edit on it. */
    function _locked(cur, dev) {
      return !!cur.readOnly || (!dev.isNew && !dev.editing);
    }

    function isDeviceLocked(key) {
      var cur = state.current;
      var dev = cur && _find(cur, key);
      return !dev || _locked(cur, dev);
    }

    /** Unlock a saved device for editing (and open it so its form is visible). */
    function startEdit(key) {
      var cur = state.current;
      var dev = cur && _find(cur, key);
      if (!dev || cur.readOnly || dev.isNew) return Promise.resolve();
      dev.editing = true;
      return openDevice(key);
    }

    /** Leave edit mode, discarding this device's unsaved changes. */
    function cancelEdit(key) {
      var cur = state.current;
      var dev = cur && _find(cur, key);
      if (!dev || !dev.editing) return;
      dev.device_id = dev.savedDeviceId;
      dev.raw = dev.schema ? _rawFrom(dev.schema, dev.savedUserConfig) : (_clone(dev.savedUserConfig) || {});
      dev.touched = false;
      dev.editing = false;
      emit();
    }

    function removeDevice(key) {
      var cur = state.current;
      var dev = cur && _find(cur, key);
      if (!dev || _locked(cur, dev)) return;
      cur.devices = cur.devices.filter(function (d) { return d.key !== key; });
      emit();
    }

    function setDeviceId(key, value) {
      var dev = state.current && _find(state.current, key);
      if (!dev || _locked(state.current, dev)) return;
      dev.device_id = value;
      emit();
    }

    function setField(key, name, value) {
      var dev = state.current && _find(state.current, key);
      if (!dev || _locked(state.current, dev)) return;
      dev.raw[name] = value;
      dev.touched = true;
      emit();
    }

    function _userConfig(dev) {
      if (!dev.schema || (!dev.isNew && !dev.touched)) {
        return { values: _clone(dev.savedUserConfig) || {}, errors: {} };
      }
      return SF.evaluate(dev.schema, dev.raw);
    }

    // ------------------------------------------------------- testbench

    function _blank(id, name, isNew) {
      return {
        id: id, name: name, isNew: isNew,
        version: 0, readOnly: false, viewingVersion: null,
        devices: [], baseline: null,
        versions: [], versionsError: null,
        saving: false, saveError: null,
        catalogChanged: false
      };
    }

    function _contentPayload(cur) {
      return {
        devices: (cur.devices || []).map(function (d) {
          return {
            device_id: String(d.device_id).trim(),
            catalog_ref: d.catalog_ref,
            adapter: d.adapter,
            static_config: _clone(d.static_config) || {},
            user_config: _userConfig(d).values
          };
        })
      };
    }

    function _payload(cur) {
      return {
        id: cur.id,
        name: cur.name,
        devices: cur.devices.map(function (d) {
          return {
            device_id: String(d.device_id).trim(),
            catalog_ref: d.catalog_ref,
            adapter: d.adapter,
            static_config: _clone(d.static_config) || {},
            user_config: _userConfig(d).values
          };
        })
      };
    }

    function _mark(cur) { cur.baseline = canon(_contentPayload(cur)); }

    function createNew(id, name) {
      id = String(id || '').trim();
      if (!id) return { ok: false, field: 'id', message: 'Testbench id is required' };
      if (name === undefined || name === null) {
        name = id;
      } else {
        name = String(name).trim();
      }
      if (!name) return { ok: false, field: 'name', message: 'Testbench name is required' };
      if (state.list.items.some(function (i) { return i.id === id && !i.isNew; })) {
        return { ok: false, field: 'id', message: 'A testbench with id "' + id + '" already exists' };
      }
      state.current = _blank(id, name, true);
      if (!state.list.items.some(function (i) { return i.id === id; })) {
        state.list.items.push({ id: id, name: name, latestVersion: 'new', isNew: true });
      }
      _notice(null);
      emit();
      return { ok: true };
    }

    function _fromDoc(doc, readOnly) {
      var p = doc.payload || {};
      var cur = _blank(doc.id || p.id, p.name || doc.name, false);
      cur.version = doc.version;
      cur.readOnly = readOnly;
      cur.viewingVersion = readOnly ? doc.version : null;
      cur.devices = (p.devices || []).map(_savedDevice);
      _mark(cur);
      return cur;
    }

    function open(id, optVersion) {
      state.failure = null;
      var targetVer = optVersion;
      if (targetVer === undefined) {
        targetVer = _getActiveVersion(id);
      }
      return api.getConfiguration(TB, id, targetVer).then(function (doc) {
        state.current = _fromDoc(doc, false);
        _notice(null);
        var cur = state.current;
        _saveActiveVersion(id, doc.version);
        emit();
        return loadVersions().then(function () { return cur; });
      }).catch(function (err) {
        if (err.code === 'NOT_FOUND') {
          if (targetVer !== undefined) {
            _saveActiveVersion(id, null);
            return open(id);
          }
          // Not an error: nothing saved under this id yet.
          state.current = _blank(id, id, true);
          _notice('info', 'Testbench "' + id + '" is not created yet. Add devices and save to create it.');
          if (!state.list.items.some(function (i) { return i.id === id; })) {
            state.list.items.push({ id: id, name: id, latestVersion: 'new', isNew: true });
          }
          emit();
          return state.current;
        }
        _fail(err, function () { return open(id, optVersion); });
        _notice('danger', err.message);
        emit();
        return null;
      });
    }

    function openVersion(version) {
      var cur = state.current;
      if (!cur || cur.isNew) return Promise.resolve();
      var id = cur.id;
      return api.getConfiguration(TB, id, version).then(function (doc) {
        var next = _fromDoc(doc, true);
        next.versions = cur.versions;
        next.latestVersion = cur.latestVersion;
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
      if (!cur || cur.isNew) return Promise.resolve(null);
      var id = cur.id;
      return api.getConfiguration(TB, id, version).then(function (doc) {
        var next = _fromDoc(doc, false);
        next.versions = cur.versions;
        next.latestVersion = cur.latestVersion;
        next.readOnly = false;
        next.viewingVersion = null;
        state.current = next;
        _saveActiveVersion(id, doc.version);
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
      return Common.loadVersions({ api: api, type: TB, cur: state.current, emit: emit }).then(function (vs) {
        if (state.current && vs.length) state.current.latestVersion = vs[0];
        return vs;
      });
    }

    function setName(name) {
      if (!state.current || state.current.readOnly) return;
      var cur = state.current;
      var newName = (name !== undefined && name !== null) ? String(name).trim() : '';
      if (!newName || cur.name === newName) return;
      cur.name = newName;
      var it = state.list.items.find(function (x) { return x.id === cur.id; });
      if (it) it.name = newName;
      if (api && typeof api.renameConfiguration === 'function' && !cur.isNew) {
        api.renameConfiguration(TB, cur.id, cur.id, newName).catch(function () {});
      }
      emit();
    }

    function setId(id) {
      if (!state.current || state.current.readOnly) return;
      var cur = state.current;
      var newId = String(id || '').trim();
      if (!newId || cur.id === newId) return;
      var oldId = cur.id;

      if (state.list.items.some(function (x) { return x.id === newId && x !== cur; })) {
        _notice('warning', 'A testbench with ID "' + newId + '" already exists.');
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
          var grpRaw = storage.getItem('mm_tb_groups');
          if (grpRaw) {
            var grps = JSON.parse(grpRaw);
            if (grps[oldId]) {
              grps[newId] = grps[oldId];
              delete grps[oldId];
              storage.setItem('mm_tb_groups', JSON.stringify(grps));
            }
          }
        }
      } catch (e) {}

      if (api && typeof api.renameConfiguration === 'function' && !cur.isNew) {
        api.renameConfiguration(TB, oldId, newId, cur.name).catch(function () {});
      }
      emit();
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

    // ------------------------------------------------------ validation

    /**
     * @returns {{ok: boolean, testbench: object, devices: Object, list: Array}}
     *   devices[key] = {device_id?: msg, fields: {name: msg}}
     */
    function validate() {
      var cur = state.current;
      var out = { ok: true, testbench: {}, devices: {}, list: [] };
      if (!cur) return out;
      function add(msg, target, name, label) {
        out.ok = false;
        out.list.push({ message: label + ' ' + msg, target: target, field: name });
      }
      if (!String(cur.name || '').trim()) {
        out.testbench.name = 'is required';
        add('is required', 'testbench', 'name', 'Testbench name');
      }
      var seen = {};
      cur.devices.forEach(function (d) {
        var entry = { fields: {} };
        out.devices[d.key] = entry;
        var id = String(d.device_id).trim();
        if (!id) {
          entry.device_id = 'Device id is required';
          add('is required', d.key, 'device_id', 'Device id');
        } else if (seen[id]) {
          entry.device_id = 'Device id "' + id + '" is already used in this testbench';
          add('"' + id + '" is already used in this testbench', d.key, 'device_id', 'Device id');
        }
        seen[id] = true;
        var errs = _userConfig(d).errors;
        Object.keys(errs).forEach(function (f) {
          entry.fields[f] = errs[f];
          add(f + ' ' + errs[f], d.key, f, 'Device "' + (id || d.catalog_ref) + '": field');
        });
      });
      return out;
    }

    function isDirty() {
      return testbenchDirty();
    }

    function testbenchDirty() {
      return Common.isDirty(state.current, _contentPayload);
    }

    function canSave() {
      var cur = state.current;
      return Common.canSave(cur, validate().ok, testbenchDirty());
    }

    function save() {
      var cur = state.current;
      if (!cur || cur.readOnly || cur.saving) return Promise.resolve({ ok: false });
      if (!validate().ok) { emit(); return Promise.resolve({ ok: false, blocked: true }); }
      var payload = _payload(cur);
      var creating = cur.isNew;
      cur.saving = true;
      cur.saveError = null;
      emit();
      var call = creating
        ? api.createConfiguration(TB, cur.id, cur.name, payload)
        : api.updateConfiguration(TB, cur.id, cur.name, payload);
      return call.then(function (doc) {
        cur.saving = false;
        cur.isNew = false;
        cur.version = doc.version;
        cur.latestVersion = doc.version;
        _saveActiveVersion(cur.id, doc.version);
        cur.devices.forEach(function (d) {
          if (d.schema && (d.isNew || d.touched)) d.savedUserConfig = _userConfig(d).values;
          d.savedDeviceId = String(d.device_id).trim();
          d.device_id = d.savedDeviceId;
          d.isNew = false;
          d.editing = false;
          d.touched = false;
        });
        _mark(cur);
        if (state.catalog.version && storage) {
          try { storage.setItem(VERSION_KEY + cur.id, state.catalog.version); } catch (e) { /* optional */ }
        }
        cur.catalogChanged = false;
        _notice('success', creating
          ? ('Created testbench as version ' + doc.version + '.')
          : ('Saved as version ' + doc.version + '.'));
        _clearFailure('hub');
        emit();
        loadVersions();
        loadList();
        return { ok: true, version: doc.version, created: creating };
      }).catch(function (err) {
        cur.saving = false;
        // Input stays exactly as the user left it.
        cur.saveError = Common.saveErrorOf(err);
        emit();
        return { ok: false, error: err };
      });
    }

    function deleteItem(id) {
      return Common.deleteItem({
        api: api,
        type: TB,
        id: id,
        state: state,
        emit: emit,
        fail: _fail,
        notice: _notice,
        label: 'Testbench',
        onLocalDelete: function (delId) {
          try { if (storage) storage.removeItem(VERSION_KEY + delId); } catch (e) {}
          _saveActiveVersion(delId, null);
        }
      });
    }

    function duplicate(sourceId, newId, newName) {
      newId = String(newId || '').trim();
      if (!newId) return Promise.resolve({ ok: false, field: 'id', message: 'Testbench id is required' });
      if (newName === undefined || newName === null) {
        newName = newId;
      } else {
        newName = String(newName).trim();
      }
      if (!newName) newName = newId;

      if (state.list.items.some(function (i) { return i.id === newId && !i.isNew; })) {
        return Promise.resolve({ ok: false, field: 'id', message: 'A testbench with id "' + newId + '" already exists' });
      }

      if (state.current && state.current.id === sourceId && state.current.isNew) {
        var srcDevices = _contentPayload(state.current).devices;
        var res = createNew(newId, newName);
        if (!res.ok) return Promise.resolve(res);
        state.current.devices = srcDevices.map(function (d) {
          var dev = _savedDevice(d);
          dev.isNew = true;
          return dev;
        });
        _notice('info', 'Testbench "' + newId + '" duplicated from draft "' + sourceId + '".');
        emit();
        return Promise.resolve({ ok: true, id: newId });
      }

      var sourcePromise;
      if (state.current && state.current.id === sourceId) {
        sourcePromise = Promise.resolve({
          name: state.current.name || sourceId,
          payload: _contentPayload(state.current)
        });
      } else {
        var actVer = _getActiveVersion(sourceId);
        sourcePromise = api.getConfiguration(TB, sourceId, actVer).then(function (doc) {
          return { name: doc.name || sourceId, payload: doc.payload || {} };
        });
      }

      return sourcePromise.then(function (src) {
        var p = src.payload || {};
        var devList = (p.devices || []).map(function (d) {
          return {
            device_id: d.device_id,
            catalog_ref: d.catalog_ref,
            adapter: d.adapter,
            static_config: _clone(d.static_config) || {},
            user_config: _clone(d.user_config) || {}
          };
        });
        var payload = {
          id: newId,
          name: newName,
          devices: devList
        };

        return api.createConfiguration(TB, newId, newName, payload).then(function (res) {
          _notice('info', 'Testbench "' + newId + '" duplicated from "' + sourceId + '".');
          return loadList().then(function () {
            return open(newId).then(function () {
              return { ok: true, id: newId };
            });
          });
        });
      }).catch(function (err) {
        _notice('danger', 'Failed to duplicate testbench: ' + err.message);
        return { ok: false, message: err.message };
      });
    }

    function dismissNotice() { _notice(null); emit(); }

    return {
      state: state,
      subscribe: subscribe,
      loadList: loadList,
      loadCatalog: loadCatalog,
      createNew: createNew,
      duplicate: duplicate,
      deleteItem: deleteItem,
      open: open,
      getActiveVersion: _getActiveVersion,
      openVersion: openVersion,
      loadVersionForUse: loadVersionForUse,
      loadVersions: loadVersions,
      closeCurrent: closeCurrent,
      setName: setName,
      setId: setId,
      addDevice: addDevice,
      openDevice: openDevice,
      closeDevice: closeDevice,
      removeDevice: removeDevice,
      startEdit: startEdit,
      cancelEdit: cancelEdit,
      isDeviceLocked: isDeviceLocked,
      setDeviceId: setDeviceId,
      setField: setField,
      validate: validate,
      isDirty: isDirty,
      testbenchDirty: testbenchDirty,
      canSave: canSave,
      save: save,
      retry: retry,
      dismissNotice: dismissNotice,
      payload: function () { return state.current ? _payload(state.current) : null; }
    };
  }

  return { createStore: createStore, canon: canon };
});
