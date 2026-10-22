/**
 * @fileoverview TEMPORARY in-memory Configuration Hub, so the Testbenches UI
 * can be used while the Hub is not reachable. Mimics the hub's behaviour
 * (versions, NOT_FOUND, ALREADY_EXISTS, provider defaults, INVALID_ARGUMENT
 * for obviously bad payloads). Data is kept in localStorage (mm_hub_mock_data)
 * so it survives a reload; clear that key to start over.
 *
 * Switch to the real hub with localStorage mm_hub_mock = '0', then delete this file.
 *
 * @version 1.0.0
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    var MM = root.MicroserviceManager = root.MicroserviceManager || {};
    MM.hubMockApi = api;
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var KEY = 'mm_hub_mock_data';
  var DEFAULTS = { infrastructure: { node: 'client1', datacenters: ['dc1'] } };

  function _err(code, reason) {
    var e = new Error(code === 'NOT_FOUND' ? 'Not found' : code === 'ALREADY_EXISTS' ? 'Already exists'
      : 'Rejected by Configuration Hub: ' + reason);
    e.service = 'hub'; e.code = code; e.reason = reason || ''; e.detail = reason || '';
    return e;
  }

  function _clone(v) { return JSON.parse(JSON.stringify(v)); }

  /** @param {{getItem, setItem}} [storage] */
  function create(storage) {
    var data = { testbench: {}, infrastructure: {} };
    try {
      var raw = storage && storage.getItem(KEY);
      if (raw) data = Object.assign(data, JSON.parse(raw));
    } catch (e) { /* start empty */ }

    function _save() { try { if (storage) storage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* in-memory only */ } }
    function _type(t) {
      if (!data[t]) throw _err('INVALID_ARGUMENT', 'unknown config_type "' + t + '"');
      return data[t];
    }
    function _doc(id, versions, v) {
      var e = versions[v - 1];
      return { id: id, configType: '', name: e.name, version: v, payload: _clone(e.payload), createdAt: e.at, updatedAt: e.at };
    }
    function _validate(type, id, name, payload) {
      if (!id) throw _err('INVALID_ARGUMENT', 'config_id is required');
      if (type === 'testbench') {
        if (!name) throw _err('INVALID_ARGUMENT', "Missing or invalid required field: 'name'");
        if (!payload || !Array.isArray(payload.devices)) throw _err('INVALID_ARGUMENT', "Missing or invalid required field: 'devices'");
        var seen = {};
        payload.devices.forEach(function (d) {
          if (!d.device_id) throw _err('INVALID_ARGUMENT', "Device missing required field: 'device_id'");
          if (seen[d.device_id]) throw _err('INVALID_ARGUMENT', "Duplicate device_id '" + d.device_id + "'");
          seen[d.device_id] = true;
          if (!d.catalog_ref || !d.adapter) throw _err('INVALID_ARGUMENT', "Device '" + d.device_id + "' needs catalog_ref and adapter");
          if ('deployment_descriptor' in d) throw _err('INVALID_ARGUMENT', 'deployment_descriptor must not be sent');
        });
      } else if (type === 'infrastructure') {
        if (!payload || !String(payload.node || '').trim()) throw _err('INVALID_ARGUMENT', 'node must not be empty');
        if (!Array.isArray(payload.datacenters) || !payload.datacenters.length) throw _err('INVALID_ARGUMENT', 'datacenters must be a non-empty list');
      }
    }
    function _push(type, id, name, payload) {
      var t = _type(type);
      t[id] = (t[id] || []).concat([{ name: name, payload: _clone(payload), at: new Date().toISOString() }]);
      _save();
      return _doc(id, t[id], t[id].length);
    }
    function _wrap(fn) { return Promise.resolve().then(fn); }

    return {
      listConfigurations: function (type) {
        return _wrap(function () {
          var t = _type(type);
          return Object.keys(t).map(function (id) {
            var vs = t[id];
            return { id: id, name: vs[vs.length - 1].name, latestVersion: vs.length, updatedAt: vs[vs.length - 1].at };
          });
        });
      },
      getConfiguration: function (type, id, version) {
        return _wrap(function () {
          var vs = _type(type)[id];
          if (!vs) throw _err('NOT_FOUND');
          var v = version || vs.length;
          if (!vs[v - 1]) throw _err('NOT_FOUND');
          return _doc(id, vs, v);
        });
      },
      getDefaultConfiguration: function (type) {
        return _wrap(function () {
          _type(type);
          if (!DEFAULTS[type]) throw _err('NOT_FOUND');
          return { id: type, configType: type, name: type, version: 0, payload: _clone(DEFAULTS[type]), createdAt: '', updatedAt: '' };
        });
      },
      createConfiguration: function (type, id, name, payload) {
        return _wrap(function () {
          var t = _type(type);
          _validate(type, id, name, payload);
          if (t[id]) throw _err('ALREADY_EXISTS', id);
          return _push(type, id, name, payload);
        });
      },
      updateConfiguration: function (type, id, name, payload) {
        return _wrap(function () {
          _type(type);
          _validate(type, id, name, payload);
          return _push(type, id, name, payload);
        });
      },
      listConfigurationVersions: function (type, id) {
        return _wrap(function () {
          return (_type(type)[id] || []).map(function (_, i) { return i + 1; });
        });
      },
      deleteConfiguration: function (type, id) {
        return _wrap(function () {
          var t = _type(type);
          if (!t[id]) throw _err('NOT_FOUND');
          delete t[id];
          _save();
          return { ok: true, id: id };
        });
      },
      renameConfiguration: function (type, oldId, newId, newName) {
        return _wrap(function () {
          var t = _type(type);
          if (!t[oldId]) return { ok: false };
          var vs = t[oldId];
          if (newId && newId !== oldId) {
            delete t[oldId];
            t[newId] = vs;
            vs.forEach(function (x) {
              if (x.payload && x.payload.id !== undefined) x.payload.id = newId;
            });
          }
          var targetId = (newId && newId !== oldId) ? newId : oldId;
          if (newName !== undefined && newName !== null) {
            vs.forEach(function (x) {
              x.name = newName;
              if (x.payload && x.payload.name !== undefined) x.payload.name = newName;
            });
          }
          _save();
          return { ok: true, id: targetId, name: newName };
        });
      }
    };
  }

  return { create: create, KEY: KEY };
});
