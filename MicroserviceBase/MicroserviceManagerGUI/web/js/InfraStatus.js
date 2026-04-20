/**
 * @fileoverview Infrastructure status pills — Consul + Nomad indicators
 * in the navbar, replacing the legacy RabbitMQ broker connection badge.
 *
 * Polls the bridge-side health proxies every 5 seconds:
 *   GET /api/consul/health  -> { ok, leader, ... }
 *   GET /api/nomad/health   -> { ok, version, ... }
 *
 * The new gRPC + Consul runtime uses Consul for service discovery; Nomad
 * is the optional orchestrator.  Both LEDs go gray whenever the bridge
 * itself is down (emitted via the `mm:bridge-state` event from
 * BridgeControl.js).
 *
 * Clicking a pill jumps to the matching Service Network sub-tab so the
 * user can start the agent or inspect state.
 *
 * IIFE attaching to MM.infraStatus.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var POLL_INTERVAL_MS = 5000;
  var _pollTimer = null;
  var _bridgeUp = false;

  function _bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (origin && origin.indexOf('http') === 0) return origin;
    return 'http://localhost:1112';
  }

  function _fetchJson(path) {
    return fetch(_bridgeOrigin() + path, { method: 'GET', cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
  }

  function _setPill(id, state, title) {
    var led = document.getElementById(id);
    if (!led) return;
    led.classList.remove('up', 'down', 'unknown');
    led.classList.add(state || 'unknown');

    // Update the pill title (tooltip) so hover reveals the reason.
    var pill = led.closest('.infra-pill');
    if (pill && title) pill.title = title;
  }

  function _pollConsul() {
    if (!_bridgeUp) {
      _setPill('infraConsulLed', 'unknown', 'Consul — bridge is down');
      return;
    }
    _fetchJson('/api/consul/health')
      .then(function (data) {
        if (data && data.ok) {
          _setPill('infraConsulLed', 'up',
                   'Consul — leader ' + (data.leader || 'unknown'));
        } else {
          _setPill('infraConsulLed', 'down',
                   'Consul unreachable' + (data && data.error ? ': ' + data.error : ''));
        }
      })
      .catch(function (err) {
        _setPill('infraConsulLed', 'down',
                 'Consul health check failed: ' + (err.message || err));
      });
  }

  function _pollNomad() {
    if (!_bridgeUp) {
      _setPill('infraNomadLed', 'unknown', 'Nomad — bridge is down');
      return;
    }
    _fetchJson('/api/nomad/health')
      .then(function (data) {
        if (data && data.ok) {
          var v = data.version || '';
          _setPill('infraNomadLed', 'up',
                   'Nomad — ' + (v ? 'v' + v : 'connected'));
        } else {
          _setPill('infraNomadLed', 'down',
                   'Nomad unreachable' + (data && data.error ? ': ' + data.error : ''));
        }
      })
      .catch(function (err) {
        _setPill('infraNomadLed', 'down',
                 'Nomad health check failed: ' + (err.message || err));
      });
  }

  function _poll() {
    _pollConsul();
    _pollNomad();
  }

  function _startPolling() {
    if (_pollTimer) return;
    _poll();
    _pollTimer = setInterval(_poll, POLL_INTERVAL_MS);
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  // --- Click handlers: jump to the matching Service Network sub-tab ---

  function _switchToFleetSubTab(tabId) {
    // Click the top-level "Service Network" mode button if not already there.
    var btnModeFleet = document.getElementById('btnModeFleet');
    if (btnModeFleet && !btnModeFleet.classList.contains('active')) {
      btnModeFleet.click();
    }
    // Then click the target sub-tab.
    var tab = document.getElementById(tabId);
    if (tab && window.bootstrap && window.bootstrap.Tab) {
      var bs = window.bootstrap.Tab.getOrCreateInstance(tab);
      bs.show();
    } else if (tab) {
      tab.click();
    }
  }

  function _init() {
    var consulPill = document.getElementById('infraConsulPill');
    var nomadPill = document.getElementById('infraNomadPill');
    if (consulPill) {
      consulPill.addEventListener('click', function () {
        _switchToFleetSubTab('tabConsul');
      });
    }
    if (nomadPill) {
      nomadPill.addEventListener('click', function () {
        _switchToFleetSubTab('tabNomad');
      });
    }

    // React to bridge state — gray out on down, resume on up.
    window.addEventListener('mm:bridge-state', function (ev) {
      var state = ev && ev.detail && ev.detail.state;
      _bridgeUp = (state === 'up');
      if (!_bridgeUp) {
        _setPill('infraConsulLed', 'unknown', 'Consul — bridge is down');
        _setPill('infraNomadLed',  'unknown', 'Nomad — bridge is down');
      } else {
        _poll();   // immediate refresh on bridge-up transition
      }
    });

    // Start with unknown state; polling will fill it in when the bridge
    // is up (the first mm:bridge-state event or first successful poll).
    _setPill('infraConsulLed', 'unknown', 'Consul — unknown');
    _setPill('infraNomadLed',  'unknown', 'Nomad — unknown');

    _startPolling();
  }

  MM.infraStatus = {
    refresh: _poll,
    start:   _startPolling,
    stop:    _stopPolling
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }

})();
