/**
 * @fileoverview WidgetShellManager — shared Widget Shell lifecycle manager.
 *
 * Manages a single Qt WASM binary (widgetshell.wasm) that loads service .ui files
 * at runtime. The shell is loaded once and cached; switching services just loads
 * a new .ui XML into the same QWidget container.
 *
 * Usage:
 *   WidgetShellManager.detect(folderPath) → Promise<{hasUi, uiFile}>
 *   WidgetShellManager.loadWidget(uiUrl, containerEl, serviceName) → Promise<void>
 *   WidgetShellManager.clear() → void
 *   WidgetShellManager.isLoaded() → boolean
 *
 * Exposed as window.WidgetShellManager.
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var SHELL_BASE_PATH = 'widget-shell';
  var SHELL_JS        = SHELL_BASE_PATH + '/widgetshell.js';

  /** Shell state */
  var _shellLoaded  = false;
  var _shellLoading = false;
  var _shellModule  = null;
  var _qtContainer  = null;   // the container Qt creates its canvas in
  var _currentContainer = null;
  var _currentServiceName = null;

  /** Queued load request while shell is still initializing */
  var _pendingLoad = null;

  var WidgetShellManager = {

    /**
     * Detect whether a service folder contains .ui files.
     * Uses MM.listServiceFiles() (works in both Electron and web modes).
     *
     * @param {string} folderPath - Relative path to the service GUI folder.
     * @returns {Promise<{hasUi: boolean, uiFile: string|null}>}
     */
    detect: function (folderPath) {
      return MM.listServiceFiles(folderPath)
        .then(function (files) {
          // Look for .ui files (prefer ServiceUI.ui)
          var uiFiles = files.filter(function (f) {
            return f.endsWith('.ui');
          });
          if (uiFiles.length === 0) return { hasUi: false, uiFile: null };

          var preferred = uiFiles.find(function (f) {
            return f === 'ServiceUI.ui';
          });
          return {
            hasUi: true,
            uiFile: preferred || uiFiles[0]
          };
        })
        .catch(function () {
          return { hasUi: false, uiFile: null };
        });
    },

    /**
     * Load a .ui service form into a container element.
     *
     * On first call: loads the shared widgetshell.wasm binary.
     * On subsequent calls: reuses the existing shell, just loads a new .ui.
     *
     * @param {string} uiUrl         - Relative URL to the .ui file.
     * @param {HTMLElement} container - DOM element to render the Qt canvas into.
     * @param {string} serviceName   - Active service name.
     * @returns {Promise<void>}
     */
    loadWidget: function (uiUrl, container, serviceName) {
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
              '<small class="text-muted">Qt Widget Application</small>' +
            '</div>' +
            '<span class="badge bg-info" id="widgetShellBadge_' + serviceName + '">Loading Shell...</span>' +
          '</div>' +
          '<div class="card-body p-0" style="height:calc(100% - 60px);overflow:hidden;">' +
            '<div id="widgetShellCanvas_' + serviceName + '" style="width:100%;height:100%;"></div>' +
          '</div>' +
        '</div>';

      var canvasContainer = document.getElementById('widgetShellCanvas_' + serviceName);
      var statusBadge = document.getElementById('widgetShellBadge_' + serviceName);

      if (_shellLoaded) {
        // Shell already loaded — reparent canvas and load new .ui.
        return _reparentAndLoad(uiUrl, canvasContainer, serviceName, statusBadge);
      }

      if (_shellLoading) {
        // Shell is currently loading — queue this request.
        _pendingLoad = {
          uiUrl: uiUrl,
          container: canvasContainer,
          serviceName: serviceName,
          badge: statusBadge
        };
        return Promise.resolve();
      }

      // First load: fetch and initialize the shell.
      _shellLoading = true;
      _pendingLoad = {
        uiUrl: uiUrl,
        container: canvasContainer,
        serviceName: serviceName,
        badge: statusBadge
      };

      return _loadShell();
    },

    /**
     * Clear the currently loaded .ui widget (tell shell to unload).
     */
    clear: function () {
      if (_shellLoaded && _shellModule) {
        try {
          _shellModule._widgetshell_clearUi();
        } catch (e) {
          console.warn('WidgetShellManager: clearUi failed', e);
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
        var factory = window.widgetshell_entry       // Qt 6.5+ qt_add_executable
                   || window.createQtAppInstance     // older Qt WASM
                   || window.widgetshellModule
                   || window.Module;

        if (typeof factory !== 'function') {
          _shellLoading = false;
          reject(new Error('Widget shell factory function not found'));
          return;
        }

        // Qt 6.5+ creates its own <canvas> inside the container element
        // via qtContainerElements.
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
            _reparentAndLoad(p.uiUrl, p.container, p.serviceName, p.badge);
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
        reject(new Error('Failed to load Widget shell script: ' + SHELL_JS));
      };

      document.head.appendChild(script);
    });
  }

  /* ================================================================
   *  Internal: Call exported C functions directly
   *
   *  Qt's qt_add_executable overrides Emscripten EXPORTED_RUNTIME_METHODS,
   *  stripping ccall/cwrap. The C functions (_widgetshell_*) ARE exported
   *  though, so we call them directly with manual UTF-8 string marshaling.
   * ================================================================ */

  /**
   * Allocate a UTF-8 C string on the WASM heap from a JS string.
   * Uses widgetshell_malloc/widgetshell_free (KEEPALIVE'd wrappers).
   * Caller must free the returned pointer via _shellModule._widgetshell_free().
   */
  function _allocUTF8(str) {
    var encoder = new TextEncoder();
    var encoded = encoder.encode(str);
    var ptr = _shellModule._widgetshell_malloc(encoded.length + 1);
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
      _shellModule._widgetshell_free(ptr);
    }
  }

  /* ================================================================
   *  Internal: .ui loading
   * ================================================================ */

  function _reparentAndLoad(uiUrl, canvasContainer, serviceName, statusBadge) {
    // Move Qt's canvas elements into the new container.
    if (_qtContainer && _qtContainer !== canvasContainer) {
      while (_qtContainer.firstChild) {
        canvasContainer.appendChild(_qtContainer.firstChild);
      }
      _qtContainer = canvasContainer;
    }

    // Set the active service name on the bridge.
    try {
      _callWithString('widgetshell_setServiceName', serviceName);
    } catch (e) {
      console.warn('WidgetShellManager: setServiceName failed', e);
    }

    // Read the .ui file in JS and pass source to C++.
    return _readFileAsText(uiUrl).then(function (uiSource) {
      try {
        _loadUiSource(uiSource);
      } catch (e) {
        if (statusBadge) {
          statusBadge.textContent = 'Error';
          statusBadge.className = 'badge bg-danger';
        }
        console.error('WidgetShellManager: loadUiSource failed', e);
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
      console.error('WidgetShellManager: failed to read .ui file', uiUrl, e);
      return Promise.reject(e);
    });
  }

  /**
   * Read a file as text via XHR (works for both file:// and http://).
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
   * Pass .ui XML source string to C++ via heap-allocated string.
   * Unlike QML Shell, no base URL is needed (.ui files have no imports).
   */
  function _loadUiSource(source) {
    _callWithString('widgetshell_loadUiSource', source);
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
   */
  function _callbackResponse(method, resultData) {
    if (!_shellModule || typeof _shellModule._widgetshell_onResponse !== 'function') return;
    var mPtr = _allocUTF8(method);
    var rPtr = _allocUTF8(resultData);
    try {
      _shellModule._widgetshell_onResponse(mPtr, rPtr);
    } finally {
      _shellModule._widgetshell_free(mPtr);
      _shellModule._widgetshell_free(rPtr);
    }
  }

  function _callbackError(method, errMsg) {
    if (!_shellModule || typeof _shellModule._widgetshell_onError !== 'function') return;
    var mPtr = _allocUTF8(method);
    var ePtr = _allocUTF8(errMsg);
    try {
      _shellModule._widgetshell_onError(mPtr, ePtr);
    } finally {
      _shellModule._widgetshell_free(mPtr);
      _shellModule._widgetshell_free(ePtr);
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

  window.WidgetShellManager = WidgetShellManager;

})();
