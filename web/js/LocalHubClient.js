/**
 * @fileoverview Local Hub API client for the Local Hub sub-tab.
 *
 * IIFE attaching to MM.localHubClient.  Same fetch-based pattern as FleetClient.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var _pollTimer = null;
  var _updateCallbacks = [];
  var _bridgeUrl = null;  // explicitly configured bridge URL

  /**
   * Resolve the FastAPI bridge base URL.
   *
   * The Local Hub API always lives on the FastAPI bridge (Python backend).
   * In browser mode, serviceClient.apiUrl already points there.
   * In Electron mode, origin is file:// so we fall back to the default
   * bridge address (http://localhost:1112) or the explicitly configured URL.
   */
  function _apiUrl(path) {
    if (_bridgeUrl) return _bridgeUrl + path;
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (origin && origin.indexOf('http') === 0) return origin + path;
    // Electron / file:// fallback — use default FastAPI bridge address
    return 'http://localhost:1112' + path;
  }

  function _fetchJson(method, path, body) {
    var opts = {
      method: method,
      headers: { 'Content-Type': 'application/json' }
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    return fetch(_apiUrl(path), opts).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || data.detail || 'Local Hub API error ' + res.status);
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  var localHubClient = {

    /**
     * Set the FastAPI bridge URL explicitly (for Electron or custom setups).
     * @param {string} url - e.g. "http://localhost:8000"
     */
    setBridgeUrl: function (url) {
      _bridgeUrl = url ? url.replace(/\/+$/, '') : null;
    },

    /**
     * Start the local hub.
     * @param {object} options
     */
    startHub: function (options) {
      return _fetchJson('POST', '/api/local-hub/start', options || {});
    },

    /**
     * Stop the local hub.
     */
    stopHub: function () {
      return _fetchJson('POST', '/api/local-hub/stop');
    },

    /**
     * Get local hub status.
     */
    getStatus: function () {
      return _fetchJson('GET', '/api/local-hub/status');
    },

    /**
     * Start named processes.
     * @param {string[]} names
     */
    startProcesses: function (names) {
      return _fetchJson('POST', '/api/local-hub/processes/start', { names: names });
    },

    /**
     * Stop named processes.
     * @param {string[]} names
     * @param {boolean} [force=false]
     */
    stopProcesses: function (names, force) {
      return _fetchJson('POST', '/api/local-hub/processes/stop', {
        names: names,
        force: !!force
      });
    },

    /**
     * Get all process configurations.
     */
    getConfig: function () {
      return _fetchJson('GET', '/api/local-hub/config');
    },

    /**
     * Add a process configuration.
     * @param {string} name
     * @param {object} config
     */
    addConfig: function (name, config) {
      return _fetchJson('POST', '/api/local-hub/config', { name: name, config: config });
    },

    /**
     * Update a process configuration.
     * @param {string} name
     * @param {object} config
     */
    updateConfig: function (name, config) {
      return _fetchJson('PUT', '/api/local-hub/config/' + encodeURIComponent(name), { config: config });
    },

    /**
     * Remove a process configuration.
     * @param {string} name
     */
    removeConfig: function (name) {
      return _fetchJson('DELETE', '/api/local-hub/config/' + encodeURIComponent(name));
    },

    /**
     * Reset the hub.
     */
    resetHub: function () {
      return _fetchJson('POST', '/api/local-hub/reset');
    },

    /**
     * Register an update callback.
     * @param {Function} cb - Receives (status, err).
     */
    onUpdate: function (cb) {
      _updateCallbacks.push(cb);
    },

    /**
     * Start polling hub status.
     * @param {number} [interval=3000]
     */
    startPolling: function (interval) {
      this.stopPolling();
      var self = this;
      interval = interval || 3000;

      function poll() {
        self.getStatus()
          .then(function (data) {
            _updateCallbacks.forEach(function (cb) { cb(data, null); });
          })
          .catch(function (err) {
            _updateCallbacks.forEach(function (cb) { cb(null, err); });
          });
      }

      poll();
      _pollTimer = setInterval(poll, interval);
    },

    /**
     * Stop polling.
     */
    stopPolling: function () {
      if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
      }
    }
  };

  MM.localHubClient = localHubClient;

})();
