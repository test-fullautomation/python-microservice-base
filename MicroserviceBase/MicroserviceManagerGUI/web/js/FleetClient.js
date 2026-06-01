/**
 * @fileoverview Fleet API client for the Service Network tab.
 *
 * All fleet API calls are proxied through the FastAPI bridge
 * (``/api/fleet/*``).  The bridge forwards requests to the fleet
 * orchestrator URL configured via ``/api/fleet/config``.
 *
 * @version 1.2.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var _fleetApiUrl = null;  // e.g. "http://localhost:2510"
  var _pollTimer = null;
  var _updateCallbacks = [];

  /**
   * Return the FastAPI bridge base URL.
   * In browser mode, serviceClient.apiUrl already points to the bridge.
   * In Electron, origin is file:// so we fall back to the default bridge
   * address (http://localhost:1112) — same pattern as LocalHubClient.
   */
  function _bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (origin && origin.indexOf('http') === 0) return origin;
    return 'http://localhost:1112';
  }

  /**
   * Resolve the URL for a fleet API call.
   * Always proxies through the FastAPI bridge — the bridge forwards to the
   * fleet orchestrator URL configured via /api/fleet/config.
   */
  function _resolveUrl(path) {
    return _bridgeOrigin() + path;
  }

  function _fetchJson(method, path, body) {
    var opts = {
      method: method,
      headers: { 'Content-Type': 'application/json' }
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    return fetch(_resolveUrl(path), opts).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || data.detail || 'Fleet API error ' + res.status);
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  var fleetClient = {
    /**
     * Configure the fleet API URL.
     * Stores it locally for direct calls and also tells the FastAPI bridge
     * (if reachable) so proxy mode works too.
     *
     * @param {string} fleetApiUrl - e.g. "http://localhost:2510"
     * @returns {Promise}
     */
    configure: function (fleetApiUrl) {
      _fleetApiUrl = fleetApiUrl ? fleetApiUrl.replace(/\/+$/, '') : null;

      // Tell the bridge so it can proxy fleet requests.
      return fetch(_bridgeOrigin() + '/api/fleet/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fleet_api_url: fleetApiUrl || '' })
      })
        .then(function (res) { return res.json(); })
        .catch(function () { return { fleet_api_url: _fleetApiUrl }; });
    },

    /**
     * Check if a fleet API URL is configured.
     * @returns {boolean}
     */
    isConfigured: function () {
      return !!_fleetApiUrl;
    },

    /**
     * Get the currently configured fleet API URL (local state).
     * @returns {string|null}
     */
    getFleetUrl: function () {
      return _fleetApiUrl;
    },

    /**
     * Get full fleet status (hubs + summary).
     */
    getFleetStatus: function () {
      return _fetchJson('GET', '/api/fleet/status');
    },

    /**
     * Get list of hubs.
     */
    getHubs: function () {
      return _fetchJson('GET', '/api/fleet/hubs');
    },

    /**
     * Get detail for a single hub.
     * @param {string} hubId
     */
    getHubDetail: function (hubId) {
      return _fetchJson('GET', '/api/fleet/hubs/' + encodeURIComponent(hubId));
    },

    /**
     * Start processes on a hub.
     * @param {string} hubId
     * @param {string[]} processList
     */
    startProcesses: function (hubId, processList) {
      return _fetchJson('POST', '/api/fleet/hubs/' + encodeURIComponent(hubId) + '/start', {
        process_list: processList
      });
    },

    /**
     * Stop processes on a hub.
     * @param {string} hubId
     * @param {string[]} processList
     * @param {boolean} [force=false]
     */
    stopProcesses: function (hubId, processList, force) {
      return _fetchJson('POST', '/api/fleet/hubs/' + encodeURIComponent(hubId) + '/stop', {
        process_list: processList,
        force: !!force
      });
    },

    /**
     * Reset a hub.
     * @param {string} hubId
     */
    resetHub: function (hubId) {
      return _fetchJson('POST', '/api/fleet/hubs/' + encodeURIComponent(hubId) + '/reset');
    },

    /**
     * Send a raw fleet command.
     * @param {string} hubId
     * @param {string} action
     * @param {object} [params={}]
     */
    sendCommand: function (hubId, action, params) {
      return _fetchJson('POST', '/api/fleet/command', {
        hub_id: hubId,
        action: action,
        params: params || {}
      });
    },

    /**
     * Register a callback for fleet data updates (from polling).
     * @param {Function} callback - Receives (data, err).
     */
    onUpdate: function (callback) {
      _updateCallbacks.push(callback);
    },

    /**
     * Start polling fleet status.
     * @param {number} [interval=5000] - Poll interval in ms.
     */
    startPolling: function (interval) {
      this.stopPolling();
      var self = this;
      interval = interval || 5000;

      function poll() {
        self.getFleetStatus()
          .then(function (data) {
            _updateCallbacks.forEach(function (cb) { cb(data, null); });
          })
          .catch(function (err) {
            _updateCallbacks.forEach(function (cb) { cb(null, err); });
          });
      }

      poll(); // immediate first fetch
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
    },

    /**
     * Disconnect from the fleet — stop polling, clear URL, clear session.
     * Returns a Promise (for chaining).
     */
    disconnect: function () {
      this.stopPolling();
      _fleetApiUrl = null;
      _updateCallbacks = [];
      try { localStorage.removeItem('mm_fleet_api_url'); } catch (e) {}

      // Best-effort: clear the bridge-side URL too
      fetch(_bridgeOrigin() + '/api/fleet/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fleet_api_url: '' })
      }).catch(function () {});

      return Promise.resolve();
    }
  };

  MM.fleetClient = fleetClient;

})();
