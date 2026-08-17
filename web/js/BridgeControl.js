/**
 * @fileoverview Bridge control — toolbar LED + Start/Stop buttons for the
 * FastAPI bridge subprocess.
 *
 * Modes:
 *   - Electron: uses window.electronAPI.spawnBridge / killBridge / isBridgeRunning
 *   - Browser:  LED-only (no start/stop possible — the bridge hosts this page).
 *
 * Status is probed every 3 seconds by GET-ing /api/version on the bridge origin.
 * In Electron mode, we additionally cross-check with isBridgeRunning() so the
 * LED flips even if /api/version is momentarily unreachable (startup race).
 *
 * IIFE attaching to MM.bridgeControl.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var POLL_INTERVAL_MS = 3000;
  var _pollTimer = null;
  var _lastState = null;   // 'up' | 'down' | 'pending' | null

  function _bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (origin && origin.indexOf('http') === 0) return origin;
    return 'http://localhost:1112';
  }

  function _isElectron() {
    return typeof window.electronAPI === 'object' && window.electronAPI !== null;
  }

  function _setLed(state, text) {
    var led = document.getElementById('bridgeLed');
    var label = document.getElementById('bridgeLabel');
    var startBtn = document.getElementById('btnBridgeStart');
    var stopBtn = document.getElementById('btnBridgeStop');

    if (led) {
      led.classList.remove('up', 'down', 'pending');
      if (state) led.classList.add(state);
    }
    if (label) label.textContent = text || 'Bridge';
    if (startBtn) startBtn.disabled = (state === 'up' || state === 'pending');
    if (stopBtn)  stopBtn.disabled  = (state === 'down' || state === 'pending');

    // Emit a state-change event so dashboards (Nomad, Consul, ...) can
    // react — specifically so they can re-configure the bridge-side client
    // after the bridge is restarted, or reset their local state when the
    // bridge goes down.
    var prev = _lastState;
    _lastState = state;
    if (prev !== state) {
      try {
        window.dispatchEvent(new CustomEvent('mm:bridge-state', {
          detail: { state: state, previous: prev }
        }));
      } catch (e) {}
    }
  }

  function _probe() {
    // Fast HTTP probe — cheap enough to do every 3s.
    return fetch(_bridgeOrigin() + '/api/version', {
      method: 'GET',
      cache: 'no-store'
    })
      .then(function (res) { return res.ok; })
      .catch(function () { return false; });
  }

  function _poll() {
    _probe().then(function (up) {
      if (up) {
        _setLed('up', 'Bridge up');
        return;
      }

      // Not reachable via HTTP — in Electron we can double-check the
      // subprocess state in case the port is still binding.
      if (_isElectron() && window.electronAPI.isBridgeRunning) {
        Promise.resolve(window.electronAPI.isBridgeRunning())
          .then(function (info) {
            if (info && info.running) {
              _setLed('pending', 'Bridge starting...');
            } else {
              _setLed('down', 'Bridge down');
            }
          })
          .catch(function () { _setLed('down', 'Bridge down'); });
      } else {
        _setLed('down', 'Bridge down');
      }
    });
  }

  function _startPolling() {
    if (_pollTimer) return;
    _poll();
    _pollTimer = setInterval(_poll, POLL_INTERVAL_MS);
  }

  function _loadSettings() {
    // Prefer the persistent store (electron settings.json), which is where
    // the Settings modal actually writes.  Fall back to sessionStorage and
    // finally an empty object.
    if (_isElectron() && typeof window.electronAPI.loadSettings === 'function') {
      return Promise.resolve(window.electronAPI.loadSettings())
        .catch(function () { return {}; });
    }
    try {
      var raw = sessionStorage.getItem('mm_settings');
      if (raw) return Promise.resolve(JSON.parse(raw) || {});
    } catch (e) {}
    return Promise.resolve({});
  }

  function _onStartClick() {
    if (!_isElectron() || !window.electronAPI.spawnBridge) {
      MM.showToast('Bridge',
        'Start/stop is only available in the Electron app. In browser mode ' +
        'the bridge must be started from the command line.', 'warning');
      return;
    }

    _setLed('pending', 'Starting bridge...');

    // Forward the Settings modal values to spawnBridge so the spawned
    // subprocess uses the user-configured Python (with the packages it
    // needs installed), and the configured broker/bridge endpoints.
    _loadSettings().then(function (settings) {
      settings = settings || {};
      var spawnOpts = {
        pythonPath: settings.pythonPath || 'python',
        bridgeHost: settings.bridgeHost || '127.0.0.1',
        bridgePort: parseInt(settings.bridgePort, 10) || 1112,
        brokerHost: settings.brokerHost || 'localhost',
        brokerPort: settings.brokerPort || 5672
      };

      console.log('[BridgeControl] spawnBridge options:', spawnOpts);

      return Promise.resolve(window.electronAPI.spawnBridge(spawnOpts));
    })
      .then(function (info) {
        if (!info || !info.pid) {
          _handleStartFailure('Bridge spawn returned no PID.');
          return;
        }

        // Spawn returned a PID, but that only means the subprocess started.
        // The subprocess might crash immediately (missing dep, port conflict,
        // config error).  Verify reachability via HTTP before claiming success.
        _verifyBridgeUp(info.pid);
      })
      .catch(function (err) {
        _handleStartFailure('Start failed: ' + (err && err.message || err));
      });
  }

  // Poll /api/version up to ~8 seconds.  Give up and report failure if the
  // bridge doesn't answer.  Reports success on the first successful probe.
  function _verifyBridgeUp(pid) {
    var attempts = 0;
    var maxAttempts = 16;           // 16 * 500ms = 8s
    _setLed('pending', 'Starting bridge...');

    var label = document.getElementById('bridgeLabel');

    function tick() {
      attempts++;
      _probe().then(function (up) {
        if (up) {
          _setLed('up', 'Bridge up');
          MM.showToast('Bridge', 'Bridge started (PID ' + pid + ')', 'success');
          return;
        }

        // Check if the subprocess is still alive.  If it already exited,
        // don't keep polling — surface the failure immediately.
        var stillRunning = true;
        if (window.electronAPI.isBridgeRunning) {
          Promise.resolve(window.electronAPI.isBridgeRunning())
            .then(function (info) {
              stillRunning = info && info.running;
              if (!stillRunning) {
                _handleStartFailure('Bridge process exited before binding its port.');
              } else if (attempts < maxAttempts) {
                if (label) label.textContent = 'Starting bridge... (' + attempts + '/' + maxAttempts + ')';
                setTimeout(tick, 500);
              } else {
                _handleStartFailure('Bridge did not respond within ' + (maxAttempts / 2) + 's.');
              }
            });
          return;
        }

        if (attempts < maxAttempts) {
          if (label) label.textContent = 'Starting bridge... (' + attempts + '/' + maxAttempts + ')';
          setTimeout(tick, 500);
        } else {
          _handleStartFailure('Bridge did not respond within ' + (maxAttempts / 2) + 's.');
        }
      });
    }
    tick();
  }

  // Report a start failure: set LED red, show a red toast, pop a modal with
  // the tail of launcher.log so the user can see *why* it failed.
  function _handleStartFailure(reason) {
    _setLed('down', 'Bridge down');

    if (!_isElectron() || !window.electronAPI.getBridgeLog) {
      MM.showToast('Bridge', reason, 'danger');
      return;
    }

    Promise.resolve(window.electronAPI.getBridgeLog(40))
      .then(function (result) {
        var logTail = (result && result.log) || '';
        _showLogModal('Bridge failed to start', reason, logTail,
                      result && result.path);
        MM.showToast('Bridge', 'Failed to start — see dialog for details', 'danger');
      })
      .catch(function () {
        MM.showToast('Bridge', reason, 'danger');
      });
  }

  // Render a Bootstrap modal showing reason + launcher.log tail.
  function _showLogModal(title, reason, logTail, logPath) {
    var existing = document.getElementById('bridgeStartErrorModal');
    if (existing) existing.remove();

    var esc = function (s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    };

    var div = document.createElement('div');
    div.id = 'bridgeStartErrorModal';
    div.className = 'modal fade';
    div.setAttribute('tabindex', '-1');
    div.innerHTML =
      '<div class="modal-dialog modal-lg modal-dialog-centered">' +
      '  <div class="modal-content">' +
      '    <div class="modal-header bg-danger text-white">' +
      '      <h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2"></i>' + esc(title) + '</h5>' +
      '      <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>' +
      '    </div>' +
      '    <div class="modal-body">' +
      '      <p class="mb-2"><strong>' + esc(reason) + '</strong></p>' +
      (logPath
        ? '<p class="text-muted small mb-2">Log file: <code>' + esc(logPath) + '</code></p>'
        : '') +
      '      <pre class="mb-0" style="max-height:360px;overflow:auto;background:#1e1e1e;color:#ddd;padding:12px;border-radius:4px;font-size:12px;">' +
             (logTail ? esc(logTail) : '(no log output)') +
      '      </pre>' +
      '    </div>' +
      '    <div class="modal-footer">' +
      '      <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>' +
      '    </div>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(div);

    // Bootstrap 5 modal show
    if (window.bootstrap && window.bootstrap.Modal) {
      var modal = new window.bootstrap.Modal(div);
      modal.show();
      div.addEventListener('hidden.bs.modal', function () { div.remove(); });
    }
  }

  function _onStopClick() {
    if (!_isElectron() || !window.electronAPI.killBridge) {
      MM.showToast('Bridge',
        'Stop is only available in the Electron app.', 'warning');
      return;
    }

    _setLed('pending', 'Stopping bridge...');

    Promise.resolve(window.electronAPI.killBridge())
      .then(function (info) {
        if (info && info.killed) {
          MM.showToast('Bridge', 'Bridge stopped', 'success');
        } else {
          MM.showToast('Bridge', 'Bridge was not running', 'info');
        }
        setTimeout(_poll, 500);
      })
      .catch(function (err) {
        MM.showToast('Bridge', 'Stop failed: ' + (err && err.message || err), 'danger');
        _poll();
      });
  }

  function _init() {
    var startBtn = document.getElementById('btnBridgeStart');
    var stopBtn = document.getElementById('btnBridgeStop');
    if (startBtn) startBtn.addEventListener('click', _onStartClick);
    if (stopBtn)  stopBtn.addEventListener('click',  _onStopClick);

    // In browser mode, hide the Start/Stop buttons — the bridge IS the server
    // serving this page, so the user cannot start or kill it from here.
    if (!_isElectron()) {
      if (startBtn) startBtn.style.display = 'none';
      if (stopBtn)  stopBtn.style.display  = 'none';
    }

    _startPolling();
  }

  // Expose for manual control from other scripts if needed.
  MM.bridgeControl = {
    refresh: _poll,
    start:   _onStartClick,
    stop:    _onStopClick
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }

})();
