/**
 * @fileoverview Local Hub Dashboard — renders the Local Hub sub-tab UI.
 *
 * Two render states:
 *   A. Setup Form   — shown when hub is stopped
 *   B. Dashboard    — shown when hub is running
 *
 * IIFE attaching to MM.localHubDashboard.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var _lastFingerprint = '';
  var _active = false;

  // ---- Helpers ----

  function _esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _fingerprint(status) {
    if (!status) return '';
    return JSON.stringify({
      r: status.running,
      m: status.mode,
      p: (status.processes || []).map(function (p) {
        return p.name + ':' + p.state + ':' + p.pid;
      }),
      cp: status.configured_processes,
      cn: status.connections,
    });
  }

  function _getContainer() {
    return document.getElementById('localHubPane');
  }

  function _isElectron() {
    return typeof window !== 'undefined' && !!window.electronAPI;
  }

  /**
   * Get the saved bridge URL from sessionStorage, or return a default.
   */
  function _getSavedBridgeUrl() {
    try {
      var saved = sessionStorage.getItem('mm_local_hub_bridge_url');
      if (saved) return saved;
    } catch (e) { /* sessionStorage unavailable */ }
    return 'http://localhost:1112';
  }

  /**
   * Ensure localHubClient has the correct bridge URL configured.
   * In browser mode (HTTP origin), the client resolves it automatically.
   * In Electron mode (file:// origin), we must set it explicitly.
   */
  function _ensureBridgeUrl() {
    if (!_isElectron()) return; // browser mode auto-resolves
    var bridgeInput = document.getElementById('lhBridgeUrl');
    var url = bridgeInput ? bridgeInput.value.trim() : _getSavedBridgeUrl();
    if (url) {
      MM.localHubClient.setBridgeUrl(url);
      try { sessionStorage.setItem('mm_local_hub_bridge_url', url); } catch (e) {}
    }
  }

  function _refreshAfterAction() {
    setTimeout(function () {
      MM.localHubClient.getStatus().then(function (data) {
        if (data) _onUpdate(data, null);
      }).catch(function () {});
    }, 1500);
  }

  /**
   * Update the bridge status badge and button states based on electronAPI.
   */
  function _updateBridgeStatusUI() {
    if (!_isElectron() || !window.electronAPI.isBridgeRunning) return;

    var status = window.electronAPI.isBridgeRunning();
    var badge = document.getElementById('lhBridgeStatusBadge');
    var startBtn = document.getElementById('lhBtnStartBridge');
    var stopBtn = document.getElementById('lhBtnStopBridge');
    var hint = document.getElementById('lhBridgePythonHint');

    if (badge) {
      if (status.running) {
        badge.textContent = 'Running (PID ' + status.pid + ')';
        badge.style.background = '#198754';
      } else {
        badge.textContent = 'Stopped';
        badge.style.background = '#6c757d';
      }
    }

    if (startBtn) startBtn.disabled = status.running;
    if (stopBtn) stopBtn.disabled = !status.running;

    // Show hint if Python path not configured
    if (hint) {
      var settings = MM.getSettings ? MM.getSettings() : {};
      hint.style.display = (!settings.pythonPath && !status.running) ? '' : 'none';
    }
  }

  // ---- Setup Form ----

  function renderSetupForm() {
    var container = _getContainer();
    if (!container) return;

    container.innerHTML =
      '<div class="local-hub-setup">' +
        '<div class="local-hub-setup-icon"><i class="bi bi-pc-display"></i></div>' +
        '<h5>Local Process Hub</h5>' +
        '<p class="text-muted">Start a ProcessHub on this machine to manage local processes.</p>' +
        '<div class="local-hub-setup-form">' +
          // Mode
          '<div class="mb-3">' +
            '<label class="form-label fw-semibold">Mode</label>' +
            '<div class="form-check">' +
              '<input class="form-check-input" type="radio" name="lhMode" id="lhModeStandalone" value="standalone" checked>' +
              '<label class="form-check-label" for="lhModeStandalone">Standalone</label>' +
            '</div>' +
            '<div class="form-check">' +
              '<input class="form-check-input" type="radio" name="lhMode" id="lhModeAgent" value="agent">' +
              '<label class="form-check-label" for="lhModeAgent">Agent (join fleet)</label>' +
            '</div>' +
          '</div>' +
          // Agent fields (hidden by default)
          '<div id="lhAgentFields" style="display:none;">' +
            '<div class="mb-3">' +
              '<label for="lhOrchestratorUrl" class="form-label">Orchestrator URL</label>' +
              '<input type="text" class="form-control" id="lhOrchestratorUrl" placeholder="tcp://localhost:5560">' +
            '</div>' +
            '<div class="row mb-3">' +
              '<div class="col">' +
                '<label for="lhHubId" class="form-label">Hub ID</label>' +
                '<input type="text" class="form-control" id="lhHubId" placeholder="local-hub-1">' +
              '</div>' +
              '<div class="col">' +
                '<label for="lhHubName" class="form-label">Hub Name</label>' +
                '<input type="text" class="form-control" id="lhHubName" placeholder="My Local Hub">' +
              '</div>' +
            '</div>' +
          '</div>' +
          // Advanced
          '<div class="mb-3">' +
            '<a class="text-decoration-none" data-bs-toggle="collapse" href="#lhAdvanced" role="button" aria-expanded="false">' +
              '<i class="bi bi-gear me-1"></i>Advanced' +
            '</a>' +
          '</div>' +
          '<div class="collapse' + (_isElectron() ? ' show' : '') + '" id="lhAdvanced">' +
            // Bridge URL — needed in Electron mode where origin is file://
            (_isElectron()
              ? '<div class="mb-3">' +
                  '<label for="lhBridgeUrl" class="form-label">Bridge URL</label>' +
                  '<input type="text" class="form-control" id="lhBridgeUrl" value="' + _esc(_getSavedBridgeUrl()) + '">' +
                  '<div class="form-text">FastAPI bridge address (required in Electron mode)</div>' +
                '</div>'
              : '') +
            '<div class="row mb-3">' +
              '<div class="col">' +
                '<label for="lhXpubPort" class="form-label">XPUB Port</label>' +
                '<input type="number" class="form-control" id="lhXpubPort" value="5555">' +
              '</div>' +
              '<div class="col">' +
                '<label for="lhXsubPort" class="form-label">XSUB Port</label>' +
                '<input type="number" class="form-control" id="lhXsubPort" value="5556">' +
              '</div>' +
            '</div>' +
          '</div>' +
          // Bridge controls (Electron mode only)
          (_isElectron()
            ? '<div class="card mb-3" id="lhBridgeCard">' +
                '<div class="card-header d-flex align-items-center justify-content-between">' +
                  '<span><i class="bi bi-hdd-rack me-2"></i>FastAPI Bridge</span>' +
                  '<span class="badge" id="lhBridgeStatusBadge" style="background:#6c757d;color:#fff;">Stopped</span>' +
                '</div>' +
                '<div class="card-body">' +
                  '<div id="lhBridgePythonHint" class="form-text text-warning mb-2" style="display:none;">' +
                    '<i class="bi bi-exclamation-triangle me-1"></i>Configure Python path in Settings first' +
                  '</div>' +
                  '<div class="d-flex gap-2">' +
                    '<button class="btn btn-sm btn-success" id="lhBtnStartBridge">' +
                      '<i class="bi bi-play-fill me-1"></i>Start Bridge' +
                    '</button>' +
                    '<button class="btn btn-sm btn-danger" id="lhBtnStopBridge" disabled>' +
                      '<i class="bi bi-stop-fill me-1"></i>Stop Bridge' +
                    '</button>' +
                  '</div>' +
                '</div>' +
              '</div>'
            : '') +
          // Start button
          '<button class="btn btn-primary" id="lhBtnStart">' +
            '<i class="bi bi-play-fill me-1"></i>Start Hub' +
          '</button>' +
        '</div>' +
      '</div>';

    // Wire mode radio toggle
    var radios = container.querySelectorAll('input[name="lhMode"]');
    var agentFields = document.getElementById('lhAgentFields');
    radios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        agentFields.style.display = radio.value === 'agent' && radio.checked ? '' : 'none';
      });
    });

    // Wire bridge controls (Electron mode only)
    if (_isElectron()) {
      _updateBridgeStatusUI();

      var startBridgeBtn = document.getElementById('lhBtnStartBridge');
      var stopBridgeBtn = document.getElementById('lhBtnStopBridge');

      if (startBridgeBtn) {
        startBridgeBtn.onclick = function () {
          var settings = MM.getSettings ? MM.getSettings() : {};
          var bridgeInput = document.getElementById('lhBridgeUrl');
          var bridgeUrl = bridgeInput ? bridgeInput.value.trim() : 'http://localhost:1112';
          var bridgePort = parseInt(settings.bridgePort) || 1112;
          try {
            var urlObj = new URL(bridgeUrl);
            bridgePort = parseInt(urlObj.port) || bridgePort;
          } catch (e) {}

          var result = window.electronAPI.spawnBridge({
            pythonPath: settings.pythonPath || 'python',
            brokerHost: settings.brokerHost || 'localhost',
            brokerPort: settings.brokerPort || '5672',
            bridgePort: bridgePort,
          });
          if (result && result.pid) {
            MM.showToast('Bridge', 'Bridge started (PID ' + result.pid + ')', 'success');
          }
          setTimeout(function () { _updateBridgeStatusUI(); }, 500);
        };
      }

      if (stopBridgeBtn) {
        stopBridgeBtn.onclick = function () {
          var result = window.electronAPI.killBridge();
          if (result && result.killed) {
            MM.showToast('Bridge', 'Bridge stopped.', 'success');
          }
          setTimeout(function () { _updateBridgeStatusUI(); }, 500);
        };
      }
    }

    // Wire start button
    var startBtn = document.getElementById('lhBtnStart');
    if (startBtn) {
      startBtn.onclick = function () {
        var mode = container.querySelector('input[name="lhMode"]:checked').value;
        var options = {
          mode: mode,
          xpub_port: parseInt(document.getElementById('lhXpubPort').value) || 5555,
          xsub_port: parseInt(document.getElementById('lhXsubPort').value) || 5556,
        };
        if (mode === 'agent') {
          options.orchestrator_url = document.getElementById('lhOrchestratorUrl').value.trim();
          options.hub_id = document.getElementById('lhHubId').value.trim();
          options.hub_name = document.getElementById('lhHubName').value.trim();
        }

        _ensureBridgeUrl();

        startBtn.disabled = true;
        startBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Starting...';

        MM.localHubClient.startHub(options)
          .then(function (data) {
            if (data.error) {
              MM.showToast('Error', data.error, 'danger');
              startBtn.disabled = false;
              startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Hub';
            } else {
              MM.showToast('Hub Started', 'Local ProcessHub is running.', 'success');
              MM.localHubClient.startPolling();
            }
          })
          .catch(function (err) {
            MM.showToast('Error', err.message, 'danger');
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Hub';
          });
      };
    }
  }

  // ---- Running Dashboard ----

  function renderDashboard(status) {
    var container = _getContainer();
    if (!container) return;

    var processes = status.processes || [];
    var connections = status.connections || [];
    var configs = status.process_configs || {};
    var configured = status.configured_processes || [];

    var runningProcesses = processes.filter(function (p) { return p.state === 'running'; });

    // Process table rows
    var processRows = '';
    if (processes.length === 0) {
      processRows = '<div class="text-muted p-3">No processes configured. Use "Add Process" to add one.</div>';
    } else {
      processes.forEach(function (proc) {
        var isRunning = proc.state === 'running';
        var stateClass = isRunning ? 'running' : 'stopped';
        var stateIcon = isRunning ? 'bi-check-circle-fill' : 'bi-dash-circle';
        var stateLabel = isRunning ? 'Running' : 'Stopped';

        var actionBtn = isRunning
          ? '<button class="btn btn-sm btn-outline-danger lh-action-btn" data-process="' + _esc(proc.name) + '" data-action="stop" title="Stop">' +
              '<i class="bi bi-stop-fill"></i>' +
            '</button>'
          : '<button class="btn btn-sm btn-outline-success lh-action-btn" data-process="' + _esc(proc.name) + '" data-action="start" title="Start">' +
              '<i class="bi bi-play-fill"></i>' +
            '</button>';

        var editBtn =
          '<button class="btn btn-sm btn-outline-info lh-edit-btn" data-process="' + _esc(proc.name) + '" title="Edit config">' +
            '<i class="bi bi-pencil"></i>' +
          '</button>';

        var removeBtn =
          '<button class="btn btn-sm btn-outline-secondary lh-remove-btn" data-process="' + _esc(proc.name) + '" title="Remove config">' +
            '<i class="bi bi-trash"></i>' +
          '</button>';

        processRows +=
          '<div class="fleet-process-item ' + stateClass + '">' +
            '<div class="fleet-process-row">' +
              '<span class="fleet-process-state"><i class="bi ' + stateIcon + '"></i></span>' +
              '<span class="fleet-process-name">' + _esc(proc.name) + '</span>' +
              (proc.pid ? '<span class="badge bg-light text-dark me-1">PID ' + proc.pid + '</span>' : '') +
              '<span class="fleet-process-state-label badge ' + stateClass + '">' + stateLabel + '</span>' +
              actionBtn +
              editBtn +
              removeBtn +
            '</div>' +
          '</div>';
      });
    }

    // Connection rows
    var connectionRows = '';
    if (connections.length === 0) {
      connectionRows = '<div class="text-muted">No connections</div>';
    } else {
      connections.forEach(function (conn) {
        connectionRows += '<div class="fleet-connection-item"><i class="bi bi-link-45deg me-2"></i>' + _esc(conn) + '</div>';
      });
    }

    var modeBadge = status.mode === 'agent'
      ? '<span class="fleet-status-badge degraded">Agent</span>'
      : '<span class="fleet-status-badge online">Standalone</span>';

    var processLabel = runningProcesses.length + '/' + processes.length + ' running';

    var html =
      '<div class="local-hub-dashboard">' +
        '<div class="local-hub-header">' +
          '<div>' +
            '<h5>' + _esc(status.hub_name || status.hub_id) +
              ' <span class="fleet-status-badge online">Running</span> ' +
              modeBadge +
            '</h5>' +
            '<div class="fleet-detail-meta">' +
              '<span><strong>Hub ID:</strong> ' + _esc(status.hub_id) + '</span>' +
              '<span><strong>Mode:</strong> ' + _esc(status.mode) + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="local-hub-toolbar">' +
            '<button class="btn btn-sm btn-success" id="lhBtnStartAll" title="Start all configured processes">' +
              '<i class="bi bi-play-fill me-1"></i>Start All' +
            '</button>' +
            '<button class="btn btn-sm btn-danger" id="lhBtnStopAll" title="Stop all running processes">' +
              '<i class="bi bi-stop-fill me-1"></i>Stop All' +
            '</button>' +
            '<button class="btn btn-sm btn-warning" id="lhBtnReset" title="Reset hub">' +
              '<i class="bi bi-arrow-counterclockwise me-1"></i>Reset' +
            '</button>' +
            '<button class="btn btn-sm btn-outline-danger" id="lhBtnStopHub" title="Stop hub">' +
              '<i class="bi bi-power me-1"></i>Stop Hub' +
            '</button>' +
          '</div>' +
        '</div>' +
        '<div class="row mt-3">' +
          '<div class="col-md-8">' +
            '<div class="card">' +
              '<div class="card-header d-flex justify-content-between align-items-center">' +
                '<span><i class="bi bi-terminal me-2"></i>Processes (' + processLabel + ')</span>' +
                '<button class="btn btn-sm btn-outline-primary" id="lhBtnAddProcess">' +
                  '<i class="bi bi-plus me-1"></i>Add Process' +
                '</button>' +
              '</div>' +
              '<div class="card-body fleet-process-list">' + processRows + '</div>' +
            '</div>' +
            // Inline add config form (hidden by default)
            '<div class="card mt-2 local-hub-config-form" id="lhConfigForm" style="display:none;" data-edit-mode="" data-edit-name="">' +
              '<div class="card-header" id="lhConfigFormHeader"><i class="bi bi-plus-circle me-2"></i>Add Process Configuration</div>' +
              '<div class="card-body">' +
                '<div class="row mb-2">' +
                  '<div class="col-md-4">' +
                    '<label class="form-label">Name</label>' +
                    '<input type="text" class="form-control form-control-sm" id="lhCfgName" placeholder="my_process">' +
                  '</div>' +
                  '<div class="col-md-8">' +
                    '<label class="form-label">Script</label>' +
                    '<input type="text" class="form-control form-control-sm" id="lhCfgScript" placeholder="python">' +
                  '</div>' +
                '</div>' +
                '<div class="row mb-2">' +
                  '<div class="col-md-8">' +
                    '<label class="form-label">Arguments</label>' +
                    '<input type="text" class="form-control form-control-sm" id="lhCfgArgs" placeholder="-c &quot;import time; time.sleep(3600)&quot;">' +
                  '</div>' +
                  '<div class="col-md-4">' +
                    '<label class="form-label">Wait Time (s)</label>' +
                    '<input type="number" class="form-control form-control-sm" id="lhCfgWait" value="1.0" step="0.5">' +
                  '</div>' +
                '</div>' +
                '<div class="mb-2">' +
                  '<label class="form-label">Environment (JSON)</label>' +
                  '<input type="text" class="form-control form-control-sm" id="lhCfgEnv" placeholder=\'{"KEY": "value"}\'>' +
                '</div>' +
                '<div class="d-flex gap-2">' +
                  '<button class="btn btn-sm btn-primary" id="lhBtnSaveConfig">' +
                    '<i class="bi bi-check me-1"></i>Save' +
                  '</button>' +
                  '<button class="btn btn-sm btn-secondary" id="lhBtnCancelConfig">Cancel</button>' +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="col-md-4">' +
            '<div class="card">' +
              '<div class="card-header"><i class="bi bi-link-45deg me-2"></i>Connections (' + connections.length + ')</div>' +
              '<div class="card-body">' + connectionRows + '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    container.innerHTML = html;

    // ---- Wire event handlers ----

    // Start All
    var startAllBtn = document.getElementById('lhBtnStartAll');
    if (startAllBtn) {
      startAllBtn.onclick = function () {
        if (configured.length === 0) {
          MM.showToast('Info', 'No processes configured.', 'info');
          return;
        }
        MM.localHubClient.startProcesses(configured)
          .then(function () { MM.showToast('Command Sent', 'Start all sent.', 'success'); _refreshAfterAction(); })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    // Stop All
    var stopAllBtn = document.getElementById('lhBtnStopAll');
    if (stopAllBtn) {
      stopAllBtn.onclick = function () {
        var runningNames = runningProcesses.map(function (p) { return p.name; });
        if (runningNames.length === 0) {
          MM.showToast('Info', 'No processes running.', 'info');
          return;
        }
        MM.localHubClient.stopProcesses(runningNames)
          .then(function () { MM.showToast('Command Sent', 'Stop all sent.', 'success'); _refreshAfterAction(); })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    // Reset
    var resetBtn = document.getElementById('lhBtnReset');
    if (resetBtn) {
      resetBtn.onclick = function () {
        if (!confirm('Reset the local hub? This will stop all processes and clear connections.')) return;
        MM.localHubClient.resetHub()
          .then(function () { MM.showToast('Reset', 'Hub has been reset.', 'success'); _refreshAfterAction(); })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    // Stop Hub
    var stopHubBtn = document.getElementById('lhBtnStopHub');
    if (stopHubBtn) {
      stopHubBtn.onclick = function () {
        if (!confirm('Stop the local hub?')) return;
        MM.localHubClient.stopHub()
          .then(function () {
            MM.showToast('Hub Stopped', 'Local ProcessHub has been stopped.', 'success');
            MM.localHubClient.stopPolling();
            _lastFingerprint = '';
            renderSetupForm();
          })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    // Individual Start / Stop buttons
    var actionBtns = container.querySelectorAll('.lh-action-btn');
    actionBtns.forEach(function (btn) {
      btn.onclick = function () {
        var procName = btn.getAttribute('data-process');
        var action = btn.getAttribute('data-action');
        if (action === 'start') {
          MM.localHubClient.startProcesses([procName])
            .then(function () { MM.showToast('Started', procName + ' started.', 'success'); _refreshAfterAction(); })
            .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
        } else {
          MM.localHubClient.stopProcesses([procName])
            .then(function () { MM.showToast('Stopped', procName + ' stopped.', 'success'); _refreshAfterAction(); })
            .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
        }
      };
    });

    // Remove config buttons
    var removeBtns = container.querySelectorAll('.lh-remove-btn');
    removeBtns.forEach(function (btn) {
      btn.onclick = function () {
        var procName = btn.getAttribute('data-process');
        if (!confirm('Remove configuration for "' + procName + '"?')) return;
        MM.localHubClient.removeConfig(procName)
          .then(function (data) {
            if (data.success) {
              MM.showToast('Removed', procName + ' config removed.', 'success');
              _refreshAfterAction();
            } else {
              MM.showToast('Error', data.message, 'danger');
            }
          })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    });

    // ---- Config form helpers ----

    var configForm = document.getElementById('lhConfigForm');
    var configFormHeader = document.getElementById('lhConfigFormHeader');
    var cfgNameInput = document.getElementById('lhCfgName');
    var cfgScriptInput = document.getElementById('lhCfgScript');
    var cfgArgsInput = document.getElementById('lhCfgArgs');
    var cfgWaitInput = document.getElementById('lhCfgWait');
    var cfgEnvInput = document.getElementById('lhCfgEnv');

    function _resetConfigForm() {
      if (cfgNameInput) { cfgNameInput.value = ''; cfgNameInput.readOnly = false; }
      if (cfgScriptInput) cfgScriptInput.value = '';
      if (cfgArgsInput) cfgArgsInput.value = '';
      if (cfgWaitInput) cfgWaitInput.value = '1.0';
      if (cfgEnvInput) cfgEnvInput.value = '';
      if (configForm) { configForm.setAttribute('data-edit-mode', ''); configForm.setAttribute('data-edit-name', ''); }
      if (configFormHeader) configFormHeader.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Add Process Configuration';
    }

    function _fillConfigForm(procName, cfg) {
      if (cfgNameInput) { cfgNameInput.value = procName; cfgNameInput.readOnly = true; }
      if (cfgScriptInput) cfgScriptInput.value = cfg.script || '';
      if (cfgArgsInput) cfgArgsInput.value = (cfg.args || []).join(' ');
      if (cfgWaitInput) cfgWaitInput.value = cfg.wait_time || '1.0';
      if (cfgEnvInput) cfgEnvInput.value = cfg.env ? JSON.stringify(cfg.env) : '';
      if (configForm) { configForm.setAttribute('data-edit-mode', 'true'); configForm.setAttribute('data-edit-name', procName); }
      if (configFormHeader) configFormHeader.innerHTML = '<i class="bi bi-pencil me-2"></i>Edit: ' + _esc(procName);
    }

    // Edit config buttons
    var editBtns = container.querySelectorAll('.lh-edit-btn');
    editBtns.forEach(function (btn) {
      btn.onclick = function () {
        var procName = btn.getAttribute('data-process');
        var cfg = configs[procName] || {};
        _fillConfigForm(procName, cfg);
        if (configForm) configForm.style.display = '';
      };
    });

    // Add Process button
    var addBtn = document.getElementById('lhBtnAddProcess');
    if (addBtn && configForm) {
      addBtn.onclick = function () {
        if (configForm.style.display === 'none') {
          _resetConfigForm();
          configForm.style.display = '';
        } else {
          configForm.style.display = 'none';
        }
      };
    }

    // Cancel config form
    var cancelBtn = document.getElementById('lhBtnCancelConfig');
    if (cancelBtn && configForm) {
      cancelBtn.onclick = function () {
        configForm.style.display = 'none';
      };
    }

    // Save config (add or update)
    var saveBtn = document.getElementById('lhBtnSaveConfig');
    if (saveBtn) {
      saveBtn.onclick = function () {
        var isEdit = configForm && configForm.getAttribute('data-edit-mode') === 'true';
        var editName = configForm ? configForm.getAttribute('data-edit-name') : '';
        var name = (cfgNameInput ? cfgNameInput.value : '').trim();
        var script = (cfgScriptInput ? cfgScriptInput.value : '').trim();
        var argsStr = (cfgArgsInput ? cfgArgsInput.value : '').trim();
        var waitTime = parseFloat(cfgWaitInput ? cfgWaitInput.value : '1.0') || 1.0;
        var envStr = (cfgEnvInput ? cfgEnvInput.value : '').trim();

        if (!name) { MM.showToast('Validation', 'Name is required.', 'warning'); return; }
        if (!script) { MM.showToast('Validation', 'Script is required.', 'warning'); return; }

        var args = argsStr ? argsStr.split(/\s+/) : [];
        var env = {};
        if (envStr) {
          try { env = JSON.parse(envStr); } catch (e) {
            MM.showToast('Validation', 'Invalid JSON for environment.', 'warning');
            return;
          }
        }

        var config = {
          script: script,
          args: args,
          wait_time: waitTime,
          process_name: name,
        };
        if (Object.keys(env).length > 0) config.env = env;

        var apiCall = isEdit
          ? MM.localHubClient.updateConfig(editName, config)
          : MM.localHubClient.addConfig(name, config);
        var verb = isEdit ? 'Updated' : 'Added';

        apiCall
          .then(function (data) {
            if (data.success) {
              MM.showToast(verb, name + ' config ' + verb.toLowerCase() + '.', 'success');
              configForm.style.display = 'none';
              _refreshAfterAction();
            } else {
              MM.showToast('Error', data.message, 'danger');
            }
          })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }
  }

  // ---- Update handler (called from polling) ----

  function _onUpdate(status, err) {
    if (!_active) return;

    if (err) {
      // Show setup form on error (hub probably not reachable)
      renderSetupForm();
      return;
    }

    if (!status || !status.running) {
      _lastFingerprint = '';
      renderSetupForm();
      return;
    }

    // Skip re-render if nothing changed
    var fp = _fingerprint(status);
    if (fp === _lastFingerprint) return;
    _lastFingerprint = fp;

    renderDashboard(status);
  }

  // ---- Public API ----

  MM.localHubDashboard = {
    activate: function () {
      _active = true;
      _lastFingerprint = '';
      // In Electron mode, restore saved bridge URL before any API calls
      if (_isElectron()) {
        MM.localHubClient.setBridgeUrl(_getSavedBridgeUrl());
      }
      MM.localHubClient.onUpdate(_onUpdate);
      // Do an initial check — if hub is running, show dashboard; else setup form
      MM.localHubClient.getStatus()
        .then(function (status) {
          if (status && status.running) {
            renderDashboard(status);
            MM.localHubClient.startPolling();
          } else {
            renderSetupForm();
          }
          // Update bridge status UI after form is rendered (Electron only)
          if (_isElectron()) _updateBridgeStatusUI();
        })
        .catch(function () {
          renderSetupForm();
          if (_isElectron()) _updateBridgeStatusUI();
        });
    },
    deactivate: function () {
      _active = false;
      MM.localHubClient.stopPolling();
    },
    renderSetupForm: renderSetupForm,
    renderDashboard: renderDashboard
  };

})();
