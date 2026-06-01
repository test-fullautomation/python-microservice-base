/**
 * @fileoverview Nomad API client for the Nomad Dashboard sub-tab.
 *
 * Handles bridge-side Nomad agent lifecycle management and API proxy calls.
 *
 * IIFE attaching to MM.nomadClient.
 *
 * @version 3.0.0
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
          var err = new Error(data.error || data.detail || 'Nomad API error ' + res.status);
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  var nomadClient = {

    // ---- Bridge-side Nomad URL config ----

    configure: function (url) {
      return _fetchJson('POST', '/api/nomad/config', { nomad_url: url || '' });
    },

    // ---- Agent lifecycle (via bridge) ----

    startAgent: function (options) {
      return _fetchJson('POST', '/api/nomad/agent/start', options || {});
    },

    stopAgent: function () {
      return _fetchJson('POST', '/api/nomad/agent/stop');
    },

    getAgentStatus: function () {
      return _fetchJson('GET', '/api/nomad/agent/status');
    },

    getAgentLog: function (tail) {
      var q = tail ? '?tail=' + tail : '';
      return _fetchJson('GET', '/api/nomad/agent/log' + q);
    },

    // ---- Nomad API proxy (via bridge) ----

    testConnection: function () {
      return _fetchJson('GET', '/api/nomad/health');
    },

    getJobs: function () {
      return _fetchJson('GET', '/api/nomad/jobs');
    },

    getJobDetail: function (jobId) {
      return _fetchJson('GET', '/api/nomad/jobs/' + encodeURIComponent(jobId));
    },

    getAllocations: function (jobId) {
      return _fetchJson('GET', '/api/nomad/jobs/' + encodeURIComponent(jobId) + '/allocations');
    },

    startJob: function (jobId) {
      return _fetchJson('POST', '/api/nomad/jobs/' + encodeURIComponent(jobId) + '/start');
    },

    stopJob: function (jobId, purge) {
      return _fetchJson('POST', '/api/nomad/jobs/' + encodeURIComponent(jobId) + '/stop',
        { purge: !!purge });
    },

    getJobLogs: function (jobId, logType) {
      var q = logType ? '?type=' + logType : '';
      return _fetchJson('GET', '/api/nomad/jobs/' + encodeURIComponent(jobId) + '/logs' + q);
    }
  };

  MM.nomadClient = nomadClient;

})();
