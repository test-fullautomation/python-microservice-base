/**
 * @fileoverview gRPC method discovery + invocation client.
 *
 * Wraps the new /api/grpc/* endpoints on the FastAPI bridge.  The bridge
 * uses server reflection to enumerate and dynamically call any gRPC
 * service registered in Consul.
 *
 * IIFE attaching to MM.grpcClient.
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
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(_bridgeOrigin() + path, opts).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || data.detail || 'gRPC API error ' + res.status);
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

  MM.grpcClient = {

    /**
     * Enumerate gRPC services and methods for a Consul-registered service.
     *
     * @param {string} consulName The Consul service name.
     * @param {string} [consulUrl] Optional Consul cluster URL (for multi-Consul).
     * @returns {Promise<object>}
     */
    getServiceMethods: function (consulName, consulUrl) {
      return _fetchJson(
        'GET',
        '/api/grpc/services/' + encodeURIComponent(consulName) + _consulQ(consulUrl)
      );
    },

    /**
     * Invoke a unary gRPC method.
     *
     * @param {object} opts
     * @param {string} opts.consulName   Consul service name.
     * @param {string} opts.grpcService  Fully-qualified proto service name.
     * @param {string} opts.method       Method name.
     * @param {string} opts.argsJson     JSON payload for the request message.
     * @param {string} [opts.consulUrl]  Consul cluster URL (for multi-Consul).
     * @returns {Promise<object>}
     */
    callMethod: function (opts) {
      return _fetchJson('POST', '/api/grpc/call', {
        consul_name:  opts.consulName,
        grpc_service: opts.grpcService,
        method:       opts.method,
        args_json:    opts.argsJson || '{}',
        consul:       opts.consulUrl || ''
      });
    }
  };

})();
