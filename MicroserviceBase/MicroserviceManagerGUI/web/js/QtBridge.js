/**
 * @fileoverview QtBridge — the one window.callMicroservice every Qt UI calls.
 *
 * Qt UIs (the QML shell, the Widget shell and per-service Qt WASM builds)
 * call window.callMicroservice(serviceName, method, args) from C++. Where
 * the call goes depends on where the UI is shown:
 *
 *   - a classic service panel: the service's broker queue, looked up by
 *     name in MM.servicesInfor; the answer goes back through
 *     window._shellResponseCallback / _shellErrorCallback (the shells) or
 *     the returned promise (per-service builds).
 *   - a bench tile (endo/kinds-qt.js): the tile answers over gRPC with its
 *     component's capabilities.
 *
 * Every Qt instance calls the same global, so a tile's calls are found by
 * name: the tile sets its instance's service name to its own token, and a
 * UI that calls with an empty name (the Widget shell always does; QML:
 * ServiceBridge.callService("", ...)) is matched exactly. A UI that
 * hard-codes a service name is matched by the last pointer, key or focus
 * event: inside a tile, that tile; anywhere else, the classic path.
 *
 *   MM.qtBridge.install()                  make window.callMicroservice this bridge
 *   MM.qtBridge.addRoute(el, fn) -> route  { token, remove() }; calls go to fn(method, args)
 *   MM.qtBridge.classicCall(name, method, args)
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var routes = [];
  var active = null;
  var seq = 0;

  /** The broker call of classic panels (the service is known by name). */
  function classicCall(serviceName, method, args) {
    var serviceInfo = MM.servicesInfor && MM.servicesInfor[serviceName];
    if (!serviceInfo) {
      if (window._shellErrorCallback) window._shellErrorCallback(method, 'Service "' + serviceName + '" not found');
      return Promise.reject(new Error('Service "' + serviceName + '" not found'));
    }
    return MM.requestService(
      { method: method, args: args },
      'services_request',
      serviceInfo.routing_key
    ).then(function (resp) {
      var resultData = (resp && resp.result_data !== undefined)
        ? (typeof resp.result_data === 'string'
            ? resp.result_data
            : JSON.stringify(resp.result_data))
        : JSON.stringify(resp);
      if (window._shellResponseCallback) window._shellResponseCallback(method, resultData);
      return resp;
    }).catch(function (err) {
      if (window._shellErrorCallback) window._shellErrorCallback(method, err.message || String(err));
      throw err;
    });
  }

  function routeOf(target) {
    for (var i = 0; i < routes.length; i++) {
      if (routes[i].el.contains(target)) return routes[i];
    }
    return null;
  }

  // Capture phase: Qt handles these events itself and may stop them.
  ['pointerdown', 'touchstart', 'keydown', 'focusin'].forEach(function (type) {
    document.addEventListener(type, function (ev) { active = routeOf(ev.target); }, true);
  });

  function callMicroservice(serviceName, method, args) {
    for (var i = 0; i < routes.length; i++) {
      if (routes[i].token === serviceName) return routes[i].fn(method, args);
    }
    if (active && routes.indexOf(active) >= 0) return active.fn(method, args);
    return classicCall(serviceName, method, args);
  }

  MM.qtBridge = {
    install: function () {
      if (window.callMicroservice !== callMicroservice) window.callMicroservice = callMicroservice;
    },
    addRoute: function (el, fn) {
      var r = { el: el, fn: fn, token: 'endo-tile-' + (++seq) };
      routes.push(r);
      return {
        token: r.token,
        remove: function () {
          var i = routes.indexOf(r);
          if (i >= 0) routes.splice(i, 1);
          if (active === r) active = null;
        }
      };
    },
    classicCall: classicCall
  };
})();
