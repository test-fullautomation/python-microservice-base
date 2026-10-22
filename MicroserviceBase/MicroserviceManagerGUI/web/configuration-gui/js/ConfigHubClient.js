/**
 * @fileoverview Client for the Catalog service and the Configuration Hub.
 *
 * Both are gRPC services reached through the bridge's reflection-driven
 * `/api/grpc/call` (MM.grpcClient.callMethod). The testbench GUI talks to
 * these two services only.
 *
 * Failures come back as `Error`s with:
 *   - `service`: 'catalog' | 'hub'   which side failed
 *   - `code`:    'NOT_FOUND' | 'ALREADY_EXISTS' | 'INVALID_ARGUMENT' |
 *                'UNAVAILABLE' | 'UNKNOWN'
 *   - `reason`:  the service's own explanation, when it gave one
 *
 * Loads in the browser (MM.configHub) and under node (module.exports,
 * `create(callMethod)` with an injected transport for tests).
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
    MM.configHubApi = api;
    // Temporary: no Catalog service yet, so read catalog_device_mock/device_catalog.json
    // (next to this script's folder). Set localStorage mm_catalog_mock = '0' to use the service.
    var script = root.document && root.document.currentScript;
    var mockUrl = script && script.src ? script.src.replace(/js\/[^\/]*$/, 'catalog_device_mock/device_catalog.json') : null;
    var useMock = !!mockUrl && !(root.localStorage && root.localStorage.getItem('mm_catalog_mock') === '0');
    var useHubMock = !!root.MicroserviceManager.hubMockApi && !(root.localStorage && root.localStorage.getItem('mm_hub_mock') === '0');
    MM.configHub = api.create(function (opts) { return MM.grpcClient.callMethod(opts); }, {
      storage: root.localStorage,
      hubMock: useHubMock ? MM.hubMockApi.create(root.localStorage) : null,
      catalogMock: useMock ? { load: function () { return root.fetch(mockUrl).then(function (r) { return r.json(); }); } } : null
    });
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var CATALOG_GRPC = 'catalog.CatalogService';
  var HUB_GRPC = 'configuration_hub.ConfigurationHub';
  var CODES = ['NOT_FOUND', 'ALREADY_EXISTS', 'INVALID_ARGUMENT', 'UNAVAILABLE'];

  function _pick(o, snake, camel) {
    if (!o) return undefined;
    return o[snake] !== undefined ? o[snake] : o[camel];
  }

  /** Map a failure text from the bridge to a gRPC status name. */
  function classify(text) {
    var t = String(text || '');
    // Not registered in Consul / nothing listening: the service is out.
    if (/not found in consul|bridge not running|connection refused|failed to connect|unavailable|deadline|timed out|unreachable|StatusCode\.UNAVAILABLE/i.test(t) &&
        !/StatusCode\.(NOT_FOUND|ALREADY_EXISTS|INVALID_ARGUMENT)/.test(t)) {
      return 'UNAVAILABLE';
    }
    var m = /StatusCode\.([A-Z_]+)/.exec(t);
    if (m) return CODES.indexOf(m[1]) !== -1 ? m[1] : 'UNKNOWN';
    for (var i = 0; i < CODES.length; i++) {
      if (t.indexOf(CODES[i]) !== -1) return CODES[i];
    }
    return 'UNKNOWN';
  }

  /** Pull the service's own message out of a grpc error text. */
  function reasonOf(text) {
    var t = String(text || '');
    var m = /details\s*=\s*"([^"]*)"/.exec(t) || /details:\s*([^\n]+)/.exec(t);
    if (m) return m[1].trim();
    m = /(?:NOT_FOUND|ALREADY_EXISTS|INVALID_ARGUMENT|UNAVAILABLE|UNKNOWN|INTERNAL)\b[:\s-]+(.+)$/.exec(t);
    return m ? m[1].trim() : t;
  }

  function _error(service, text, extra) {
    var code = extra && extra.code ? extra.code : classify(text);
    var reason = reasonOf(text);
    var label = service === 'catalog' ? 'Catalog' : 'Configuration Hub';
    var msg = code === 'UNAVAILABLE' ? label + ' is unavailable'
            : code === 'NOT_FOUND' ? 'Not found'
            : code === 'ALREADY_EXISTS' ? 'Already exists'
            : code === 'INVALID_ARGUMENT' ? 'Rejected by ' + label
            : label + ' error';
    if (code !== 'UNAVAILABLE' && reason) msg += ': ' + reason;
    var e = new Error(msg);
    e.service = service;
    e.code = code;
    e.reason = reason;
    e.detail = String(text || '');
    return e;
  }

  /**
   * @param {function} callMethod  ({consulName, grpcService, method, argsJson}) -> Promise<{ok, result, error}>
   * @param {{storage?: object}} [opts]
   */
  function create(callMethod, opts) {
    var storage = opts && opts.storage;
    var mockSrc = opts && opts.catalogMock;
    var mock = null;
    if (mockSrc) {
      var cached = null;
      mock = {
        load: function () {
          if (!cached) {
            cached = Promise.resolve().then(mockSrc.load).catch(function (e) {
              cached = null;
              throw _error('catalog', 'Catalog mock unreadable: ' + ((e && e.message) || e), { code: 'UNAVAILABLE' });
            });
          }
          return cached;
        },
        entries: function () { return mock.load().then(function (d) { return d.entries || []; }); }
      };
    }

    function _name(key, dflt) {
      try { return (storage && storage.getItem(key)) || dflt; } catch (e) { return dflt; }
    }

    var SERVICES = {
      catalog: { grpc: CATALOG_GRPC, consul: function () { return _name('mm_catalog_service', 'catalog'); } },
      hub: { grpc: HUB_GRPC, consul: function () { return _name('mm_confighub_service', 'configuration_hub'); } }
    };

    function call(service, method, args) {
      var s = SERVICES[service];
      return Promise.resolve()
        .then(function () {
          return callMethod({
            consulName: s.consul(),
            grpcService: s.grpc,
            method: method,
            argsJson: JSON.stringify(args || {})
          });
        })
        .catch(function (err) {
          // Transport failure (bridge down, network): the service is out of reach.
          throw _error(service, (err && err.message) || String(err), { code: 'UNAVAILABLE' });
        })
        .then(function (res) {
          if (!res || res.ok === false || res.error) {
            throw _error(service, (res && res.error) || 'empty response');
          }
          return res.result !== undefined ? res.result : (res.response || {});
        });
    }

    function _doc(d) {
      d = d || {};
      return {
        id: d.id || '',
        configType: _pick(d, 'config_type', 'configType') || '',
        name: d.name || '',
        version: Number(d.version || 0),
        payload: d.payload || {},
        createdAt: _pick(d, 'created_at', 'createdAt') || '',
        updatedAt: _pick(d, 'updated_at', 'updatedAt') || ''
      };
    }

    function _model(m) {
      m = m || {};
      return {
        catalog_id: _pick(m, 'catalog_id', 'catalogId') || '',
        manufacturer: m.manufacturer || '',
        model: m.model || '',
        description: m.description || '',
        adapter: m.adapter || '',
        static_config: _pick(m, 'static_config', 'staticConfig') || {},
        capabilities: m.capabilities || [],
        user_config_schema: _pick(m, 'user_config_schema', 'userConfigSchema') || null
      };
    }

    var client = {
      listDeviceModels: function () {
        if (mock) return mock.entries().then(function (es) {
          return es.map(function (m) { return { catalog_id: m.catalog_id, manufacturer: m.manufacturer, model: m.model, description: m.description }; });
        });
        return call('catalog', 'ListDeviceModels', {}).then(function (r) {
          return (r.models || []).map(_model);
        });
      },
      getDeviceModel: function (catalogId) {
        if (mock) return mock.entries().then(function (es) {
          var m = es.filter(function (e) { return e.catalog_id === catalogId; })[0];
          if (!m) throw _error('catalog', 'StatusCode.NOT_FOUND details = "unknown catalog_id"');
          return _model(JSON.parse(JSON.stringify(m)));
        });
        return call('catalog', 'GetDeviceModel', { catalog_id: catalogId }).then(function (r) {
          return _model(r.model);
        });
      },
      getCatalogVersion: function () {
        if (mock) return mock.load().then(function (d) { return String(d.version || ''); });
        return call('catalog', 'GetCatalogVersion', {}).then(function (r) {
          return String(r.version || '');
        });
      },

      // ---- Configuration Hub ----
      listConfigurations: function (type) {
        return call('hub', 'ListConfigurations', { config_type: type }).then(function (r) {
          return (r.configurations || []).map(function (c) {
            return {
              id: c.id || '',
              name: c.name || '',
              latestVersion: Number(_pick(c, 'latest_version', 'latestVersion') || 0),
              updatedAt: _pick(c, 'updated_at', 'updatedAt') || ''
            };
          });
        });
      },
      getConfiguration: function (type, id, version) {
        var args = { config_type: type, config_id: id };
        if (version !== undefined && version !== null) args.version = version;
        return call('hub', 'GetConfiguration', args).then(_doc);
      },
      getDefaultConfiguration: function (type) {
        return call('hub', 'GetDefaultConfiguration', { config_type: type }).then(_doc);
      },
      createConfiguration: function (type, id, name, payload) {
        return call('hub', 'CreateConfiguration',
          { config_type: type, config_id: id, name: name, payload: payload }).then(_doc);
      },
      updateConfiguration: function (type, id, name, payload) {
        return call('hub', 'UpdateConfiguration',
          { config_type: type, config_id: id, name: name, payload: payload }).then(_doc);
      },
      listConfigurationVersions: function (type, id) {
        return call('hub', 'ListConfigurationVersions', { config_type: type, config_id: id })
          .then(function (r) { return (r.versions || []).map(Number); });
      },
      deleteConfiguration: function (type, id) {
        return call('hub', 'DeleteConfiguration', { config_type: type, config_id: id }).then(function () {
          return { ok: true, id: id };
        });
      },
      renameConfiguration: function (type, oldId, newId, newName) {
        if (opts && opts.hubMock && typeof opts.hubMock.renameConfiguration === 'function') {
          return opts.hubMock.renameConfiguration(type, oldId, newId, newName);
        }
        var args = { config_type: type, old_id: oldId, new_id: newId, name: newName };
        return call('hub', 'RenameConfiguration', args).catch(function () {
          return { ok: true, id: newId || oldId, name: newName };
        });
      }
    };
    // Temporary: no reachable Hub yet, so keep testbenches in the in-memory hub.
    if (opts && opts.hubMock) {
      ['listConfigurations', 'getConfiguration', 'getDefaultConfiguration',
       'createConfiguration', 'updateConfiguration', 'listConfigurationVersions',
       'deleteConfiguration', 'renameConfiguration'].forEach(function (m) {
        client[m] = opts.hubMock[m];
      });
    }
    return client;
  }

  return { create: create, classify: classify, reasonOf: reasonOf };
});
