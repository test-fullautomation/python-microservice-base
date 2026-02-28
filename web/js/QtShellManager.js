/**
 * @fileoverview QtShellManager — shared QML Shell lifecycle manager.
 *
 * Manages a single Qt WASM binary (qtshell.wasm) that loads service .qml files
 * at runtime. The shell is loaded once and cached; switching services just loads
 * a new .qml URL into the same QML engine.
 *
 * Usage:
 *   QtShellManager.detect(folderPath) → Promise<{hasQml, qmlFile}>
 *   QtShellManager.loadQml(qmlUrl, containerEl, serviceName) → Promise<void>
 *   QtShellManager.clear() → void
 *   QtShellManager.isLoaded() → boolean
 *
 * Exposed as window.QtShellManager.
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var SHELL_BASE_PATH = 'qt-shell';
  var SHELL_JS        = SHELL_BASE_PATH + '/qtshell.js';

  /** Shell state */
  var _shellLoaded  = false;
  var _shellLoading = false;
  var _shellModule  = null;
  var _qtContainer  = null;   // the container Qt creates its canvas in
  var _currentContainer = null;
  var _currentServiceName = null;

  /** Queued load request while shell is still initializing */
  var _pendingLoad = null;

  var QtShellManager = {

    /**
     * Detect whether a service folder contains QML files.
     * Uses MM.listServiceFiles() (works in both Electron and web modes).
     *
     * @param {string} folderPath - Relative path to the service GUI folder.
     * @returns {Promise<{hasQml: boolean, qmlFile: string|null}>}
     */
    detect: function (folderPath) {
      return MM.listServiceFiles(folderPath)
        .then(function (files) {
          // Look for .qml files (prefer ServiceUI.qml)
          var qmlFiles = files.filter(function (f) {
            return f.endsWith('.qml');
          });
          if (qmlFiles.length === 0) return { hasQml: false, qmlFile: null };

          var preferred = qmlFiles.find(function (f) {
            return f === 'ServiceUI.qml';
          });
          return {
            hasQml: true,
            qmlFile: preferred || qmlFiles[0]
          };
        })
        .catch(function () {
          return { hasQml: false, qmlFile: null };
        });
    },

    /**
     * Load a QML service UI into a container element.
     *
     * On first call: loads the shared qtshell.wasm binary.
     * On subsequent calls: reuses the existing QML engine, just loads a new .qml URL.
     *
     * @param {string} qmlUrl        - Relative URL to the .qml file.
     * @param {HTMLElement} container - DOM element to render the Qt canvas into.
     * @param {string} serviceName   - Active service name.
     * @returns {Promise<void>}
     */
    loadQml: function (qmlUrl, container, serviceName) {
      // Ensure the JS bridge is available for ServiceBridge C++ calls.
      _ensureBridge();

      _currentContainer = container;
      _currentServiceName = serviceName;

      // Build the wrapper UI.
      container.innerHTML =
        '<div class="card" style="height:100%;width:100%;top:0;">' +
          '<div class="card-header d-flex justify-content-between align-items-center">' +
            '<div>' +
              '<h5 class="card-title mb-0">' + _esc(serviceName) + '</h5>' +
              '<small class="text-muted">Qt QML Application</small>' +
            '</div>' +
            '<span class="badge bg-info" id="qtShellBadge_' + serviceName + '">Loading Shell...</span>' +
          '</div>' +
          '<div class="card-body p-0" style="height:calc(100% - 60px);overflow:hidden;">' +
            '<div id="qtShellCanvas_' + serviceName + '" style="width:100%;height:100%;"></div>' +
          '</div>' +
        '</div>';

      var canvasContainer = document.getElementById('qtShellCanvas_' + serviceName);
      var statusBadge = document.getElementById('qtShellBadge_' + serviceName);

      if (_shellLoaded) {
        // Shell already loaded — reparent canvas and load new QML.
        return _reparentAndLoad(qmlUrl, canvasContainer, serviceName, statusBadge);
      }

      if (_shellLoading) {
        // Shell is currently loading — queue this request.
        _pendingLoad = {
          qmlUrl: qmlUrl,
          container: canvasContainer,
          serviceName: serviceName,
          badge: statusBadge
        };
        return Promise.resolve();
      }

      // First load: fetch and initialize the shell.
      _shellLoading = true;
      _pendingLoad = {
        qmlUrl: qmlUrl,
        container: canvasContainer,
        serviceName: serviceName,
        badge: statusBadge
      };

      return _loadShell();
    },

    /**
     * Clear the currently loaded QML (tell shell to unload).
     */
    clear: function () {
      if (_shellLoaded && _shellModule) {
        try {
          _shellModule._qtshell_clearQml();
        } catch (e) {
          console.warn('QtShellManager: clearQml failed', e);
        }
      }
      _currentServiceName = null;
    },

    /**
     * Check if the shared shell is loaded and ready.
     * @returns {boolean}
     */
    isLoaded: function () {
      return _shellLoaded;
    }
  };

  /* ================================================================
   *  Internal: Shell loading
   * ================================================================ */

  function _loadShell() {
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = SHELL_JS;

      script.onload = function () {
        // The Qt WASM loader exposes a factory function.
        var factory = window.qtshell_entry       // Qt 6.5+ qt_add_executable
                   || window.createQtAppInstance // older Qt WASM
                   || window.qtshellModule
                   || window.Module;

        if (typeof factory !== 'function') {
          // Qt 6.5+ may use a different pattern.
          _shellLoading = false;
          reject(new Error('Qt shell factory function not found'));
          return;
        }

        // Qt 6.5+ creates its own <canvas> inside the container element
        // via qtContainerElements. We just provide the container — no manual
        // canvas creation needed.
        _qtContainer = _pendingLoad ? _pendingLoad.container : document.body;

        var initResult;
        try {
          initResult = factory({
            qtContainerElements: [_qtContainer]
          });
        } catch (e) {
          _shellLoading = false;
          reject(e);
          return;
        }

        var onReady = function (instance) {
          _shellModule = instance || window.Module;
          _shellLoaded = true;
          _shellLoading = false;

          // Process any pending load.
          if (_pendingLoad) {
            var p = _pendingLoad;
            _pendingLoad = null;
            _reparentAndLoad(p.qmlUrl, p.container, p.serviceName, p.badge);
          }

          resolve();
        };

        if (initResult && typeof initResult.then === 'function') {
          initResult.then(onReady).catch(function (err) {
            _shellLoading = false;
            reject(err);
          });
        } else {
          onReady(initResult);
        }
      };

      script.onerror = function () {
        _shellLoading = false;
        reject(new Error('Failed to load Qt shell script: ' + SHELL_JS));
      };

      document.head.appendChild(script);
    });
  }

  /* ================================================================
   *  Internal: Call exported C functions directly
   *
   *  Qt's qt_add_executable overrides Emscripten EXPORTED_RUNTIME_METHODS,
   *  stripping ccall/cwrap. The C functions (_qtshell_*) ARE exported though,
   *  so we call them directly with manual UTF-8 string marshaling.
   * ================================================================ */

  /**
   * Allocate a UTF-8 C string on the WASM heap from a JS string.
   * Uses qtshell_malloc/qtshell_free (KEEPALIVE'd wrappers) since Qt's
   * qt_add_executable strips Emscripten's _malloc/_free exports.
   * Caller must free the returned pointer via _shellModule._qtshell_free().
   */
  function _allocUTF8(str) {
    var encoder = new TextEncoder();
    var encoded = encoder.encode(str);
    var ptr = _shellModule._qtshell_malloc(encoded.length + 1);
    _shellModule.HEAPU8.set(encoded, ptr);
    _shellModule.HEAPU8[ptr + encoded.length] = 0;
    return ptr;
  }

  /**
   * Call an exported C function that takes a single const char* argument.
   */
  function _callWithString(funcName, str) {
    var func = _shellModule['_' + funcName];
    if (typeof func !== 'function') {
      throw new Error(funcName + ' not found on Module');
    }
    var ptr = _allocUTF8(str);
    try {
      func(ptr);
    } finally {
      _shellModule._qtshell_free(ptr);
    }
  }

  /* ================================================================
   *  Internal: QML loading
   * ================================================================ */

  function _reparentAndLoad(qmlUrl, canvasContainer, serviceName, statusBadge) {
    // Move Qt's canvas elements into the new container.
    if (_qtContainer && _qtContainer !== canvasContainer) {
      // Move all children (canvas + input overlays) that Qt created.
      while (_qtContainer.firstChild) {
        canvasContainer.appendChild(_qtContainer.firstChild);
      }
      _qtContainer = canvasContainer;
    }

    // Set the active service name on the bridge.
    try {
      _callWithString('qtshell_setServiceName', serviceName);
    } catch (e) {
      console.warn('QtShellManager: setServiceName failed', e);
    }

    // Read the QML file in JS and pass source to C++.
    // WASM's Fetch API can't access file:// URLs (Electron), so we read
    // via XHR (which supports both file:// and http://) and use setData().
    return _readFileAsText(qmlUrl).then(function (qmlSource) {
      try {
        _loadQmlSource(qmlSource, qmlUrl);
      } catch (e) {
        if (statusBadge) {
          statusBadge.textContent = 'Error';
          statusBadge.className = 'badge bg-danger';
        }
        console.error('QtShellManager: loadQmlSource failed', e);
        return Promise.reject(e);
      }

      if (statusBadge) {
        statusBadge.textContent = 'Running';
        statusBadge.className = 'badge bg-success';
      }
    }).catch(function (e) {
      if (statusBadge) {
        statusBadge.textContent = 'Error';
        statusBadge.className = 'badge bg-danger';
      }
      console.error('QtShellManager: failed to read QML file', qmlUrl, e);
      return Promise.reject(e);
    });
  }

  /**
   * Read a file as text via synchronous XHR (works for both file:// and http://).
   */
  function _readFileAsText(url) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('GET', url, true);
      xhr.onload = function () {
        if (xhr.status === 200 || xhr.status === 0) { // status 0 for file://
          resolve(xhr.responseText);
        } else {
          reject(new Error('HTTP ' + xhr.status + ' loading ' + url));
        }
      };
      xhr.onerror = function () {
        reject(new Error('XHR error loading ' + url));
      };
      xhr.send();
    });
  }

  /**
   * Pass QML source string + base URL to C++ via heap-allocated strings.
   */
  function _loadQmlSource(source, baseUrl) {
    var srcPtr = _allocUTF8(source);
    var urlPtr = _allocUTF8(baseUrl);
    try {
      _shellModule._qtshell_loadQmlSource(srcPtr, urlPtr);
    } finally {
      _shellModule._qtshell_free(srcPtr);
      _shellModule._qtshell_free(urlPtr);
    }
  }

  /* ================================================================
   *  Internal: JS bridge for ServiceBridge C++ calls
   * ================================================================ */

  function _ensureBridge() {
    if (typeof window.callMicroservice === 'function') return;

    window.callMicroservice = function (serviceName, method, args) {
      var serviceInfo = MM.servicesInfor[serviceName];
      if (!serviceInfo) {
        _callbackError(method, 'Service "' + serviceName + '" not found');
        return Promise.reject(new Error('Service "' + serviceName + '" not found'));
      }
      var routingKey = serviceInfo.routing_key;
      return MM.requestService(
        { method: method, args: args },
        'services_request',
        routingKey
      ).then(function (resp) {
        // Route the response back to C++ ServiceBridge via exported function.
        var resultData = (resp && resp.result_data !== undefined)
          ? (typeof resp.result_data === 'string'
              ? resp.result_data
              : JSON.stringify(resp.result_data))
          : JSON.stringify(resp);
        _callbackResponse(method, resultData);
        return resp;
      }).catch(function (err) {
        _callbackError(method, err.message || String(err));
        throw err;
      });
    };
  }

  /**
   * Route a service response back to C++ ServiceBridge.
   * Uses our _allocUTF8 helper (which works) instead of EM_ASM internal functions.
   */
  function _callbackResponse(method, resultData) {
    if (!_shellModule || typeof _shellModule._qtshell_onResponse !== 'function') return;
    var mPtr = _allocUTF8(method);
    var rPtr = _allocUTF8(resultData);
    try {
      _shellModule._qtshell_onResponse(mPtr, rPtr);
    } finally {
      _shellModule._qtshell_free(mPtr);
      _shellModule._qtshell_free(rPtr);
    }
  }

  function _callbackError(method, errMsg) {
    if (!_shellModule || typeof _shellModule._qtshell_onError !== 'function') return;
    var mPtr = _allocUTF8(method);
    var ePtr = _allocUTF8(errMsg);
    try {
      _shellModule._qtshell_onError(mPtr, ePtr);
    } finally {
      _shellModule._qtshell_free(mPtr);
      _shellModule._qtshell_free(ePtr);
    }
  }

  function _esc(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ================================================================
   *  Expose
   * ================================================================ */

  window.QtShellManager = QtShellManager;

})();
