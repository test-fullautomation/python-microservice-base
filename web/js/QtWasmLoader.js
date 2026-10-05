/**
 * @fileoverview QtWasmLoader — detect, load, and unload Qt WASM service GUIs.
 *
 * Qt WASM apps render into a <canvas> inside a Bootstrap card wrapper.
 * They communicate with microservices via the window.callMicroservice JS bridge.
 *
 * A broker (RabbitMQ) service is reached by name, as before. A Consul
 * service that serves gRPC (a C++ ServiceRunner service, the panel shown
 * through Meta.gui) is not on the broker: its panel gets a route of its own
 * (QtBridge.addRoute) that calls the service's RPCs through the bridge, and
 * the route's token as Module.endoToken, so its calls reach it by name.
 * "Method" goes to the bound service that has it (found by reflection),
 * "<package.Service>/Method" to that service.
 *
 * Usage:
 *   QtWasmLoader.detect(folderPath) → Promise<boolean>
 *   QtWasmLoader.load(folderPath, containerEl, serviceName) → Promise<void>
 *   QtWasmLoader.unload(serviceName) → void
 *
 * Exposed as window.QtWasmLoader.
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  /** Map of loaded Qt instances: { serviceName: { instance, container } } */
  var _instances = {};

  var QtWasmLoader = {

    /**
     * Detect whether a service folder contains a Qt WASM app.
     * Checks for the presence of a .wasm file via list-dir API.
     *
     * @param {string} folderPath - Relative path to the service GUI folder.
     * @returns {Promise<boolean>} True if a .wasm file is found.
     */
    detect: function (folderPath) {
      return MM.listServiceFiles(folderPath)
        .then(function (files) {
          return files.some(function (f) { return f.endsWith('.wasm'); });
        })
        .catch(function () {
          return false;
        });
    },

    /**
     * Load a Qt WASM app into a container element.
     *
     * @param {string} folderPath   - Relative path to the service GUI folder.
     * @param {HTMLElement} container - DOM element to render into.
     * @param {string} serviceName   - Service name.
     * @returns {Promise<void>}
     */
    load: function (folderPath, container, serviceName) {
      // Set up JS bridge if not already defined
      _ensureBridge();

      // Build card wrapper with canvas placeholder
      container.innerHTML =
        '<div class="card" style="height:100%;width:100%;top:0;">' +
          '<div class="card-header d-flex justify-content-between align-items-center">' +
            '<div>' +
              '<h5 class="card-title mb-0">' + _esc(serviceName) + '</h5>' +
              '<small class="text-muted">Qt WASM Application</small>' +
            '</div>' +
            '<span class="badge bg-info" id="qtStatusBadge_' + serviceName + '">Loading...</span>' +
          '</div>' +
          '<div class="card-body p-0" style="height:calc(100% - 60px);overflow:hidden;">' +
            '<div id="qtContainer_' + serviceName + '" style="width:100%;height:100%;"></div>' +
          '</div>' +
        '</div>';

      var qtContainer = document.getElementById('qtContainer_' + serviceName);
      var statusBadge = document.getElementById('qtStatusBadge_' + serviceName);

      // A gRPC service from Consul: calls go to it over gRPC, not the broker.
      var grpcSvc = _grpcServiceFor(serviceName);
      var route = grpcSvc ? MM.qtBridge.addRoute(qtContainer, _grpcAnswer(grpcSvc)) : null;
      var moduleArgs = { qtContainerElements: [qtContainer] };
      if (route) moduleArgs.endoToken = route.token;

      // Find the Emscripten loader JS file
      return MM.listServiceFiles(folderPath)
        .then(function (files) {
          // Find the emscripten-generated .wasm file
          var wasmFile = files.find(function (f) { return f.endsWith('.wasm'); });
          if (!wasmFile) throw new Error('No .wasm file found');

          // The Emscripten loader JS has the same base name as the .wasm file.
          // Use case-insensitive matching because Windows FS may change casing.
          var baseName = wasmFile.replace('.wasm', '');
          var expectedJs = baseName + '.js';
          var loaderJs = files.find(function (f) {
            return f.toLowerCase() === expectedJs.toLowerCase();
          });
          if (!loaderJs) {
            // Fallback: any .js file in the folder
            loaderJs = files.find(function (f) { return f.endsWith('.js'); });
            if (!loaderJs) throw new Error('No Emscripten loader JS found');
          }

          return { loaderJs: loaderJs, baseName: baseName };
        })
        .then(function (info) {
          return new Promise(function (resolve, reject) {
            var script = document.createElement('script');
            script.src = folderPath + '/' + info.loaderJs;
            script.onload = function () {
              // Find the Emscripten module factory function.
              // Qt/Emscripten uses EXPORT_NAME = "<target>_entry" with MODULARIZE=1.
              var initFn = window[info.baseName + '_entry']
                        || window.createQtAppInstance
                        || window[info.baseName + 'Module']
                        || window.Module;
              if (typeof initFn !== 'function') {
                statusBadge.textContent = 'Error';
                statusBadge.className = 'badge bg-danger';
                console.error('QtWasmLoader: no init function found for', info.baseName,
                              '(tried: ' + info.baseName + '_entry, createQtAppInstance, ' +
                              info.baseName + 'Module, Module)');
                reject(new Error('No Emscripten init function found'));
                return;
              }

              try {
                statusBadge.textContent = 'Initializing...';
                var result = initFn(moduleArgs);
                if (result && typeof result.then === 'function') {
                  result
                    .then(function (instance) {
                      _instances[serviceName] = { instance: instance, container: qtContainer, route: route };
                      statusBadge.textContent = 'Running';
                      statusBadge.className = 'badge bg-success';
                      resolve();
                    })
                    .catch(function (err) {
                      statusBadge.textContent = 'Error';
                      statusBadge.className = 'badge bg-danger';
                      console.error('QtWasmLoader: init failed for', serviceName, err);
                      reject(err);
                    });
                } else {
                  _instances[serviceName] = { instance: result, container: qtContainer, route: route };
                  statusBadge.textContent = 'Running';
                  statusBadge.className = 'badge bg-success';
                  resolve();
                }
              } catch (err) {
                statusBadge.textContent = 'Error';
                statusBadge.className = 'badge bg-danger';
                console.error('QtWasmLoader: exception for', serviceName, err);
                reject(err);
              }
            };
            script.onerror = function () {
              statusBadge.textContent = 'Load Failed';
              statusBadge.className = 'badge bg-danger';
              reject(new Error('Failed to load Qt WASM script'));
            };
            document.head.appendChild(script);
          });
        })
        .catch(function (err) {
          // It did not start: its gRPC route must not outlive it.
          if (route && !(_instances[serviceName] && _instances[serviceName].route === route)) route.remove();
          throw err;
        });
    },

    /**
     * Unload a Qt WASM instance and clean up.
     *
     * @param {string} serviceName - Service name to unload.
     */
    unload: function (serviceName) {
      var entry = _instances[serviceName];
      if (!entry) return;

      if (entry.instance && typeof entry.instance.delete === 'function') {
        try {
          entry.instance.delete();
        } catch (e) {
          console.warn('QtWasmLoader: error deleting instance for', serviceName, e);
        }
      }

      if (entry.route) entry.route.remove();
      if (entry.container) {
        entry.container.innerHTML = '';
      }

      delete _instances[serviceName];
    },

    /**
     * Check if a service has a loaded Qt WASM instance.
     *
     * @param {string} serviceName
     * @returns {boolean}
     */
    isLoaded: function (serviceName) {
      return !!_instances[serviceName];
    }
  };

  /* ================================================================
   *  Internal helpers
   * ================================================================ */

  /**
   * Ensure the window.callMicroservice JS bridge is available
   * for Qt C++ code to call via emscripten::val.
   */
  function _ensureBridge() {
    // The shared bridge (QtBridge.js): classic panels and bench tiles.
    MM.qtBridge.install();
    // Per-service WASM handles responses via emscripten::val — clear shell callbacks.
    window._shellResponseCallback = null;
    window._shellErrorCallback = null;
  }

  /**
   * The Consul service shown through Meta.gui, when it is the one being
   * loaded and serves gRPC; null for a broker service.
   */
  function _grpcServiceFor(serviceName) {
    var svc = MM.currentGuiService;
    if (!svc || svc.name !== serviceName || !svc.consulUrl || !MM.grpcClient) return null;
    if (MM.servicesInfor && MM.servicesInfor[serviceName]) return null;   // on the broker: as before
    return svc;
  }

  /**
   * callMicroservice(token, method, args) of a gRPC service's panel: the
   * request is args[0] (or args), the answer has a broker reply's shape
   * ({ result: 'pass', result_data }) plus result_json, the whole response.
   */
  function _grpcAnswer(svc) {
    var servicesP = null;
    function services() {
      servicesP = servicesP || MM.grpcClient.getServiceMethods(svc.name, svc.consulUrl, svc.protoPath || '')
        .then(function (data) {
          var list = (data && data.grpc_services) || [];
          if (!list.length) throw new Error(svc.name + ' lists no gRPC services' + (data && data.error ? ': ' + data.error : ''));
          return list;
        });
      servicesP.catch(function () { servicesP = null; });   // try again on the next call
      return servicesP;
    }
    function target(method) {
      var s = String(method || '');
      var i = s.lastIndexOf('/');
      if (i >= 0) return Promise.resolve({ service: s.slice(0, i), method: s.slice(i + 1) });
      return services().then(function (list) {
        var hit = list.filter(function (g) {
          return (g.methods || []).some(function (m) { return m.name === s; });
        })[0];
        if (!hit) throw new Error(s + ' is not a method of ' + svc.name);
        return { service: hit.name, method: s };
      });
    }
    return function (method, args) {
      var req = Array.isArray(args) ? args[0] : args;
      if (typeof req === 'string') { try { req = JSON.parse(req); } catch (e) { req = {}; } }
      if (!req || typeof req !== 'object') req = {};
      return target(method).then(function (t) {
        return MM.grpcClient.callMethod({
          consulName: svc.name,
          consulUrl: svc.consulUrl,
          grpcService: t.service,
          method: t.method,
          argsJson: JSON.stringify(req),
          protoPath: svc.protoPath || ''
        });
      }).then(function (d) {
        if (!d || !d.ok) throw new Error((d && d.error) || (method + ' failed'));
        var res = d.result == null ? {} : d.result;
        return { result: 'pass', result_data: typeof res === 'object' ? JSON.stringify(res) : String(res),
                 result_json: JSON.stringify(res) };
      });
    };
  }

  function _esc(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ================================================================
   *  Expose
   * ================================================================ */

  window.QtWasmLoader = QtWasmLoader;

})();
