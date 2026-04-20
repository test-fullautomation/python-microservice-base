/**
 * @fileoverview Consul API client for the Consul Dashboard sub-tab.
 *
 * Handles bridge-side Consul agent lifecycle management and API proxy calls.
 * Service discovery via Consul replaces the old RabbitMQ
 * `service_information` exchange — services register themselves on startup
 * and the GUI lists them via /api/consul/services.
 *
 * IIFE attaching to MM.consulClient.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  function _bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (origin && origin.indexOf('http') === 0) return origin;
    return 'http://localhost:1112';
  }

  function _fetchJson(method, path, body) {
    var opts = {
      method: method,
      headers: { 'Content-Type': 'application/json' }
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    return fetch(_bridgeOrigin() + path, opts).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || data.detail || 'Consul API error ' + res.status);
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  function _consulQ(consulUrl) {
    return consulUrl ? ('?consul=' + encodeURIComponent(consulUrl)) : '';
  }

  var consulClient = {

    // ---- Bridge-side Consul URL config ----
    //
    // The bridge keeps a default `_consul_url` in memory (used when no
    // ``?consul=...`` override is passed).  After a bridge restart the
    // dashboard calls configure() to rehydrate it from the URL saved in
    // localStorage.  Multi-Consul callers can skip this and pass an
    // explicit URL to each method below.

    configure: function (url) {
      return _fetchJson('POST', '/api/consul/config', { consul_url: url || '' });
    },

    // ---- Agent lifecycle (via bridge) ----

    startAgent: function (options) {
      return _fetchJson('POST', '/api/consul/agent/start', options || {});
    },

    stopAgent: function () {
      return _fetchJson('POST', '/api/consul/agent/stop');
    },

    getAgentStatus: function () {
      return _fetchJson('GET', '/api/consul/agent/status');
    },

    getAgentLog: function (tail) {
      var q = tail ? '?tail=' + tail : '';
      return _fetchJson('GET', '/api/consul/agent/log' + q);
    },

    // ---- Consul HTTP API proxy (via bridge) ----
    //
    // All methods accept an optional `consulUrl` so the caller can talk
    // to multiple Consul clusters without mutating bridge-side state.

    testConnection: function (consulUrl) {
      return _fetchJson('GET', '/api/consul/health' + _consulQ(consulUrl));
    },

    getServices: function (consulUrl) {
      return _fetchJson('GET', '/api/consul/services' + _consulQ(consulUrl));
    },

    getServiceDetail: function (name, consulUrl) {
      return _fetchJson(
        'GET',
        '/api/consul/services/' + encodeURIComponent(name) + _consulQ(consulUrl)
      );
    },

    getNodes: function (consulUrl) {
      return _fetchJson('GET', '/api/consul/nodes' + _consulQ(consulUrl));
    },

    /**
     * Find running Consul agents on the local machine by inspecting
     * processes named ``consul`` and probing their listening TCP ports.
     *
     * @returns {Promise<{instances: Array, error?: string}>}
     */
    discover: function () {
      return _fetchJson('GET', '/api/consul/discover');
    }
  };

  MM.consulClient = consulClient;

})();
