/**
 * @fileoverview Fleet API client for the Service Network tab.
 *
 * Supports two transport modes:
 *   - **Direct mode** (Electron or when fleet URL is known):
 *     Calls the FleetWebAPI directly at the configured URL.
 *   - **Proxy mode** (browser via FastAPI bridge):
 *     Calls /api/fleet/* on the same origin; the bridge forwards to the fleet.
 *
 * Direct mode is used whenever a fleet URL has been configured (via
 * ``configure()``). Proxy mode is the fallback when running inside the
 * FastAPI-hosted GUI and no explicit fleet URL has been set yet.
 *
 * @version 1.1.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var _fleetApiUrl = null;  // e.g. "http://localhost:2510"
  var _pollTimer = null;
  var _updateCallbacks = [];

  /**
   * Determine whether to use the FastAPI bridge proxy.
   * Always proxy when a bridge URL is available — avoids CORS issues and
   * ensures the fleet URL only needs to be configured on the bridge side.
   * Falls back to direct mode only in Electron when no bridge is available.
   */
  function _useProxy() {
    var origin = window.location.origin || '';
    if (origin.indexOf('http') === 0) return true;   // browser: always proxy
    // Electron: proxy through bridge if bridge URL is available
    var bridgeUrl = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (bridgeUrl && bridgeUrl.indexOf('http') === 0) return true;
    return false;
  }

  /**
   * Resolve the base URL for a fleet API call.
   * - Direct mode: fleet URL + path  (e.g. http://localhost:2510/api/fleet/status)
   * - Proxy mode:  same-origin + path (e.g. /api/fleet/status)
   */
  function _resolveUrl(path) {
    if (_useProxy()) {
      var origin = MM.serviceClient ? MM.serviceClient.apiUrl : window.location.origin;
      return origin + path;
    }
    if (_fleetApiUrl) {
      return _fleetApiUrl.replace(/\/+$/, '') + path;
    }
    return path; // should not happen — caller checks isConfigured()
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

      // Inform the bridge so proxy mode works.
      // In browser mode this is the primary config path; in Electron it's
      // best-effort (bridge may not be running).
      var bridgeOrigin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
      if (bridgeOrigin && bridgeOrigin.indexOf('http') === 0) {
        return fetch(bridgeOrigin + '/api/fleet/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fleet_api_url: fleetApiUrl || '' })
        })
          .then(function (res) { return res.json(); })
          .catch(function () { return { fleet_api_url: _fleetApiUrl }; });
      }

      return Promise.resolve({ fleet_api_url: _fleetApiUrl });
    },

    /**
     * Check if a fleet API URL is configured.
     * @returns {boolean}
     */
    isConfigured: function () {
      return !!_fleetApiUrl || _useProxy();
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
      try { sessionStorage.removeItem('mm_fleet_api_url'); } catch (e) {}

      // Best-effort: clear the bridge-side URL too
      var bridgeOrigin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
      if (bridgeOrigin && bridgeOrigin.indexOf('http') === 0) {
        fetch(bridgeOrigin + '/api/fleet/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fleet_api_url: '' })
        }).catch(function () {});
      }

      return Promise.resolve();
    }
  };

  MM.fleetClient = fleetClient;

})();
