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
    return fetch(_bridgeOrigin() + path, opts)
      .catch(function (err) {
        if (err instanceof TypeError) {
          var msg = 'Bridge not running on ' + _bridgeOrigin() +
                    ' — click Start Bridge (top-right LED).';
          var e = new Error(msg);
          e.cause = 'bridge_down';
          throw e;
        }
        throw err;
      })
      .then(function (res) {
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

  function _buildQuery(params) {
    // {k: v} -> "?k=v&k2=v2" with proper URL-encoding; skips empty values.
    var parts = [];
    Object.keys(params).forEach(function (k) {
      var v = params[k];
      if (v !== undefined && v !== null && v !== '') {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
      }
    });
    return parts.length ? ('?' + parts.join('&')) : '';
  }

  MM.grpcClient = {

    /**
     * Enumerate gRPC services and methods for a Consul-registered service.
     *
     * @param {string} consulName The Consul service name.
     * @param {string} [consulUrl] Optional Consul cluster URL (for multi-Consul).
     * @param {string} [protoPath] Optional .proto search dir for the
     *     LocalProtoClient fallback (used when the server doesn't ship
     *     gRPC reflection).  Joined with MB_PROTO_SEARCH_PATH on the bridge.
     * @returns {Promise<object>}
     */
    getServiceMethods: function (consulName, consulUrl, protoPath) {
      var query = _buildQuery({
        consul:     consulUrl  || '',
        proto_path: protoPath  || ''
      });
      return _fetchJson(
        'GET',
        '/api/grpc/services/' + encodeURIComponent(consulName) + query
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
     * @param {string} [opts.protoPath]  .proto search dir for the
     *     LocalProtoClient fallback (see getServiceMethods).
     * @returns {Promise<object>}
     */
    callMethod: function (opts) {
      return _fetchJson('POST', '/api/grpc/call', {
        consul_name:  opts.consulName,
        grpc_service: opts.grpcService,
        method:       opts.method,
        args_json:    opts.argsJson || '{}',
        consul:       opts.consulUrl || '',
        proto_path:   opts.protoPath || ''
      });
    }
  };

})();
