/**
 * @fileoverview Fleet Dashboard — renders the Service Network UI.
 * Populates #fleetContent (main area) and #sidebarFleet (sidebar hub list).
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var _activeHubId = null;
  var _lastFleetData = null;
  var _lastFleetJson = '';

  // ---- Helpers ----

  function _escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /**
   * Build a fingerprint of fleet data for change detection.
   * Excludes volatile fields (last_seen, timestamp) that change every heartbeat.
   */
  function _fleetFingerprint(data) {
    if (!data || !data.hubs) return '';
    var parts = data.hubs.map(function (h) {
      return JSON.stringify({
        id: h.hub_id,
        st: h.status,
        p: h.processes,
        cp: h.configured_processes,
        cn: h.connections,
        pc: h.process_configs,
        v: h.version,
      });
    });
    return parts.join('|');
  }

  /**
   * Trigger a fleet status refresh after a short delay.
   * Gives the backend time to process the command before we poll.
   */
  function _refreshAfterAction() {
    setTimeout(function () {
      if (MM.fleetClient && MM.fleetClient.getFleetStatus) {
        MM.fleetClient.getFleetStatus().then(function (data) {
          if (data) MM.fleetDashboard.onUpdate(data, null);
        }).catch(function () {});
      }
    }, 2000);
  }

  function _statusClass(status) {
    if (status === 'online') return 'online';
    if (status === 'degraded') return 'degraded';
    return 'offline';
  }

  function _timeSince(timestamp) {
    if (!timestamp) return 'N/A';
    var seconds = Math.floor(Date.now() / 1000 - timestamp);
    if (seconds < 60) return seconds + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    return Math.floor(seconds / 3600) + 'h ago';
  }

  // ---- Sidebar ----

  function renderSidebar(data) {
    var container = document.getElementById('fleetHubList');
    if (!container) return;

    var hubs = data && data.hubs ? data.hubs : [];

    // Update summary badges
    var totalEl = document.getElementById('fleetTotalHubs');
    var onlineEl = document.getElementById('fleetOnlineHubs');
    if (totalEl) totalEl.textContent = data ? data.total_hubs : 0;
    if (onlineEl) onlineEl.textContent = data ? data.online_hubs : 0;

    container.innerHTML = '';

    if (hubs.length === 0) {
      container.innerHTML = '<div class="fleet-empty-msg">No hubs connected</div>';
      return;
    }

    hubs.forEach(function (hub) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'hub-item';
      if (hub.hub_id === _activeHubId) item.classList.add('active');

      var configuredCount = (hub.configured_processes || []).length;
      var runningCount = hub.process_count || 0;
      var countLabel = configuredCount > 0 ? (runningCount + '/' + configuredCount) : String(runningCount);

      item.innerHTML =
        '<span class="hub-status-dot ' + _statusClass(hub.status) + '"></span>' +
        '<span class="hub-item-name">' + _escapeHtml(hub.hub_name || hub.hub_id) + '</span>' +
        '<span class="hub-item-count badge">' + countLabel + '</span>';

      item.onclick = function () {
        _activeHubId = hub.hub_id;
        renderSidebar(_lastFleetData);
        renderHubDetail(hub);
      };

      container.appendChild(item);
    });
  }

  // ---- Dashboard (no hub selected) ----

  function renderDashboard(data) {
    var content = document.getElementById('fleetRemotePane');
    if (!content) return;

    if (!data) {
      content.innerHTML =
        '<div class="content-placeholder">' +
          '<span><i class="bi bi-cloud-slash me-2"></i>Unable to load fleet data</span>' +
        '</div>';
      return;
    }

    var hubs = data.hubs || [];

    var html =
      '<div class="fleet-summary">' +
        '<div class="fleet-stat-card">' +
          '<div class="fleet-stat-value">' + data.total_hubs + '</div>' +
          '<div class="fleet-stat-label">Total Hubs</div>' +
        '</div>' +
        '<div class="fleet-stat-card">' +
          '<div class="fleet-stat-value">' + data.online_hubs + '</div>' +
          '<div class="fleet-stat-label">Online</div>' +
        '</div>' +
        '<div class="fleet-stat-card">' +
          '<div class="fleet-stat-value">' + data.total_processes + '</div>' +
          '<div class="fleet-stat-label">Processes</div>' +
        '</div>' +
      '</div>';

    if (hubs.length === 0) {
      html += '<div class="content-placeholder"><span>No hubs have joined the fleet yet.</span></div>';
    } else {
      html += '<div class="fleet-hub-grid">';
      hubs.forEach(function (hub) {
        var configured = hub.configured_processes || [];
        var running = hub.processes || [];
        var displayProcs = configured.length > 0 ? configured : running;
        var runningSet = {};
        running.forEach(function (p) { runningSet[p] = true; });

        var processList = displayProcs.slice(0, 5).map(function (p) {
          var cls = 'fleet-process-tag' + (runningSet[p] ? ' running' : ' stopped');
          return '<span class="' + cls + '">' + _escapeHtml(p) + '</span>';
        }).join('');
        var moreCount = displayProcs.length - 5;
        if (moreCount > 0) processList += '<span class="fleet-process-tag more">+' + moreCount + '</span>';

        var configuredCount = configured.length;
        var runningCount = running.length;
        var processLabel = configuredCount > 0
          ? (runningCount + '/' + configuredCount + ' running')
          : (runningCount + ' processes');

        html +=
          '<div class="fleet-hub-card" data-hub-id="' + _escapeHtml(hub.hub_id) + '">' +
            '<div class="fleet-hub-card-header">' +
              '<span class="fleet-status-badge ' + _statusClass(hub.status) + '">' + _escapeHtml(hub.status) + '</span>' +
              '<span class="fleet-hub-card-title">' + _escapeHtml(hub.hub_name || hub.hub_id) + '</span>' +
            '</div>' +
            '<div class="fleet-hub-card-body">' +
              '<div class="fleet-hub-meta">' +
                '<span><i class="bi bi-pc-display me-1"></i>' + _escapeHtml(hub.host) + '</span>' +
                '<span><i class="bi bi-gear me-1"></i>' + processLabel + '</span>' +
                '<span><i class="bi bi-link-45deg me-1"></i>' + hub.connection_count + ' connections</span>' +
              '</div>' +
              '<div class="fleet-hub-processes">' + processList + '</div>' +
            '</div>' +
            '<div class="fleet-hub-card-actions">' +
              '<button class="btn btn-sm btn-outline-primary fleet-card-detail-btn" title="View details">' +
                '<i class="bi bi-eye me-1"></i>Details' +
              '</button>' +
            '</div>' +
          '</div>';
      });
      html += '</div>';
    }

    content.innerHTML = html;

    // Wire card click handlers
    var cards = content.querySelectorAll('.fleet-hub-card');
    cards.forEach(function (card) {
      var hubId = card.getAttribute('data-hub-id');
      var detailBtn = card.querySelector('.fleet-card-detail-btn');
      function openDetail() {
        var hub = hubs.find(function (h) { return h.hub_id === hubId; });
        if (hub) {
          _activeHubId = hubId;
          renderSidebar(_lastFleetData);
          renderHubDetail(hub);
        }
      }
      if (detailBtn) detailBtn.onclick = openDetail;
      card.ondblclick = openDetail;
    });
  }

  // ---- Hub Detail ----

  /**
   * Render a single process config detail block (collapsible).
   */
  function _renderProcessConfigDetail(procName, configs) {
    var cfg = (configs && configs[procName]) || null;
    if (!cfg) return '';

    var rows = '';

    if (cfg.description) {
      rows += '<tr><td class="fleet-cfg-label">Description</td><td>' + _escapeHtml(cfg.description) + '</td></tr>';
    }
    if (cfg.script) {
      rows += '<tr><td class="fleet-cfg-label">Script</td><td><code>' + _escapeHtml(cfg.script) + '</code></td></tr>';
    }
    if (cfg.args && cfg.args.length > 0) {
      rows += '<tr><td class="fleet-cfg-label">Arguments</td><td><code>' + _escapeHtml(cfg.args.join(' ')) + '</code></td></tr>';
    }
    if (cfg.wait_time !== undefined) {
      rows += '<tr><td class="fleet-cfg-label">Wait Time</td><td>' + cfg.wait_time + 's</td></tr>';
    }
    if (cfg.env && Object.keys(cfg.env).length > 0) {
      var envRows = '';
      Object.keys(cfg.env).forEach(function (k) {
        var val = String(cfg.env[k]);
        if (val.length > 80) val = val.substring(0, 77) + '...';
        envRows += '<div><code>' + _escapeHtml(k) + '</code> = <code>' + _escapeHtml(val) + '</code></div>';
      });
      rows += '<tr><td class="fleet-cfg-label">Environment</td><td>' + envRows + '</td></tr>';
    }
    if (cfg.enable !== undefined) {
      rows += '<tr><td class="fleet-cfg-label">Enabled</td><td>' + (cfg.enable !== false ? 'Yes' : 'No') + '</td></tr>';
    }
    if (cfg.mandatory) {
      rows += '<tr><td class="fleet-cfg-label">Mandatory</td><td>Yes</td></tr>';
    }

    if (!rows) return '';

    return '<table class="fleet-cfg-table">' + rows + '</table>';
  }

  function renderHubDetail(hub) {
    var content = document.getElementById('fleetRemotePane');
    if (!content) return;

    var running = hub.processes || [];
    var configured = hub.configured_processes || [];
    var connections = hub.connections || [];
    var configs = hub.process_configs || {};

    // Build a set of running process names for quick lookup
    var runningSet = {};
    running.forEach(function (p) { runningSet[p] = true; });

    // Use configured list as the source of truth; fall back to running if empty
    var allProcesses = configured.length > 0 ? configured : running;
    var runningCount = running.length;
    var totalCount = allProcesses.length;
    var hasConfigs = Object.keys(configs).length > 0;

    var processRows = '';
    if (totalCount === 0) {
      processRows = '<div class="text-muted">No processes configured</div>';
    } else {
      allProcesses.forEach(function (proc, idx) {
        var isRunning = !!runningSet[proc];
        var stateClass = isRunning ? 'running' : 'stopped';
        var stateLabel = isRunning ? 'Running' : 'Stopped';
        var stateIcon = isRunning ? 'bi-check-circle-fill' : 'bi-dash-circle';

        var actionBtn = isRunning
          ? '<button class="btn btn-sm btn-outline-danger fleet-action-process-btn" data-process="' + _escapeHtml(proc) + '" data-action="stop" title="Stop">' +
              '<i class="bi bi-stop-fill"></i>' +
            '</button>'
          : '<button class="btn btn-sm btn-outline-success fleet-action-process-btn" data-process="' + _escapeHtml(proc) + '" data-action="start" title="Start">' +
              '<i class="bi bi-play-fill"></i>' +
            '</button>';

        var expandBtn = hasConfigs && configs[proc]
          ? '<button class="btn btn-sm btn-outline-secondary fleet-cfg-toggle-btn" data-target="fleetCfg' + idx + '" title="Show configuration">' +
              '<i class="bi bi-chevron-down"></i>' +
            '</button>'
          : '';

        var cfgDetail = _renderProcessConfigDetail(proc, configs);
        var cfgHtml = cfgDetail
          ? '<div class="fleet-cfg-detail" id="fleetCfg' + idx + '" style="display:none;">' + cfgDetail + '</div>'
          : '';

        processRows +=
          '<div class="fleet-process-item ' + stateClass + '">' +
            '<div class="fleet-process-row">' +
              '<span class="fleet-process-state"><i class="bi ' + stateIcon + '"></i></span>' +
              '<span class="fleet-process-name">' + _escapeHtml(proc) + '</span>' +
              '<span class="fleet-process-state-label badge ' + stateClass + '">' + stateLabel + '</span>' +
              expandBtn +
              actionBtn +
            '</div>' +
            cfgHtml +
          '</div>';
      });
    }

    var connectionRows = '';
    if (connections.length === 0) {
      connectionRows = '<div class="text-muted">No connections</div>';
    } else {
      connections.forEach(function (conn) {
        connectionRows += '<div class="fleet-connection-item"><i class="bi bi-link-45deg me-2"></i>' + _escapeHtml(conn) + '</div>';
      });
    }

    var processHeader = totalCount > 0
      ? 'Processes (' + runningCount + '/' + totalCount + ' running)'
      : 'Processes';

    var html =
      '<div class="fleet-detail-panel">' +
        '<div class="fleet-detail-breadcrumb">' +
          '<a href="#" class="fleet-back-link"><i class="bi bi-arrow-left me-1"></i>Back to Dashboard</a>' +
        '</div>' +
        '<div class="fleet-detail-header">' +
          '<h4>' + _escapeHtml(hub.hub_name || hub.hub_id) +
            ' <span class="fleet-status-badge ' + _statusClass(hub.status) + '">' + _escapeHtml(hub.status) + '</span></h4>' +
          '<div class="fleet-detail-meta">' +
            '<span><strong>Hub ID:</strong> ' + _escapeHtml(hub.hub_id) + '</span>' +
            '<span><strong>Host:</strong> ' + _escapeHtml(hub.host) + '</span>' +
            '<span><strong>Version:</strong> ' + _escapeHtml(hub.version || 'N/A') + '</span>' +
            '<span><strong>Last Seen:</strong> ' + _timeSince(hub.last_seen) + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="fleet-detail-toolbar">' +
          '<button class="btn btn-sm btn-success" id="fleetBtnStartAll" title="Start all configured processes">' +
            '<i class="bi bi-play-fill me-1"></i>Start All' +
          '</button>' +
          '<button class="btn btn-sm btn-danger" id="fleetBtnStopAll" title="Stop all running processes">' +
            '<i class="bi bi-stop-fill me-1"></i>Stop All' +
          '</button>' +
          '<button class="btn btn-sm btn-warning" id="fleetBtnReset" title="Reset hub">' +
            '<i class="bi bi-arrow-counterclockwise me-1"></i>Reset' +
          '</button>' +
        '</div>' +
        '<div class="row mt-3">' +
          '<div class="col-md-7">' +
            '<div class="card">' +
              '<div class="card-header"><i class="bi bi-terminal me-2"></i>' + processHeader + '</div>' +
              '<div class="card-body fleet-process-list">' + processRows + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="col-md-5">' +
            '<div class="card">' +
              '<div class="card-header"><i class="bi bi-link-45deg me-2"></i>Connections (' + connections.length + ')</div>' +
              '<div class="card-body">' + connectionRows + '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    content.innerHTML = html;

    // Wire config toggle buttons
    var cfgToggles = content.querySelectorAll('.fleet-cfg-toggle-btn');
    cfgToggles.forEach(function (btn) {
      btn.onclick = function () {
        var targetId = btn.getAttribute('data-target');
        var target = document.getElementById(targetId);
        if (!target) return;
        var icon = btn.querySelector('i');
        if (target.style.display === 'none') {
          target.style.display = 'block';
          if (icon) icon.className = 'bi bi-chevron-up';
        } else {
          target.style.display = 'none';
          if (icon) icon.className = 'bi bi-chevron-down';
        }
      };
    });

    // Wire actions
    var backLink = content.querySelector('.fleet-back-link');
    if (backLink) {
      backLink.onclick = function (e) {
        e.preventDefault();
        _activeHubId = null;
        renderSidebar(_lastFleetData);
        renderDashboard(_lastFleetData);
      };
    }

    // Start All — starts all configured processes
    var startAllBtn = document.getElementById('fleetBtnStartAll');
    if (startAllBtn) {
      startAllBtn.onclick = function () {
        if (allProcesses.length === 0) {
          MM.showToast('Info', 'No processes configured.', 'info');
          return;
        }
        MM.fleetClient.startProcesses(hub.hub_id, allProcesses)
          .then(function () { MM.showToast('Command Sent', 'Start command sent to ' + (hub.hub_name || hub.hub_id), 'success'); _refreshAfterAction(); })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    // Stop All — stops all running processes
    var stopAllBtn = document.getElementById('fleetBtnStopAll');
    if (stopAllBtn) {
      stopAllBtn.onclick = function () {
        if (running.length === 0) {
          MM.showToast('Info', 'No processes running.', 'info');
          return;
        }
        MM.fleetClient.stopProcesses(hub.hub_id, running)
          .then(function () { MM.showToast('Command Sent', 'Stop command sent to ' + (hub.hub_name || hub.hub_id), 'success'); _refreshAfterAction(); })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    var resetBtn = document.getElementById('fleetBtnReset');
    if (resetBtn) {
      resetBtn.onclick = function () {
        if (!confirm('Reset hub ' + (hub.hub_name || hub.hub_id) + '?')) return;
        MM.fleetClient.resetHub(hub.hub_id)
          .then(function () { MM.showToast('Command Sent', 'Reset command sent to ' + (hub.hub_name || hub.hub_id), 'success'); _refreshAfterAction(); })
          .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
      };
    }

    // Wire individual start/stop buttons
    var actionBtns = content.querySelectorAll('.fleet-action-process-btn');
    actionBtns.forEach(function (btn) {
      btn.onclick = function () {
        var procName = btn.getAttribute('data-process');
        var action = btn.getAttribute('data-action');
        if (action === 'start') {
          MM.fleetClient.startProcesses(hub.hub_id, [procName])
            .then(function () { MM.showToast('Command Sent', 'Start ' + procName + ' sent.', 'success'); _refreshAfterAction(); })
            .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
        } else {
          MM.fleetClient.stopProcesses(hub.hub_id, [procName])
            .then(function () { MM.showToast('Command Sent', 'Stop ' + procName + ' sent.', 'success'); _refreshAfterAction(); })
            .catch(function (err) { MM.showToast('Error', err.message, 'danger'); });
        }
      };
    });
  }

  // ---- Configure prompt (no fleet URL set) ----

  function renderConfigurePrompt() {
    var content = document.getElementById('fleetRemotePane');
    if (!content) return;

    content.innerHTML =
      '<div class="fleet-configure-prompt">' +
        '<div class="fleet-configure-icon"><i class="bi bi-hdd-network"></i></div>' +
        '<h5>Service Network Not Configured</h5>' +
        '<p class="text-muted">Enter the Fleet API URL to connect to the fleet orchestrator.</p>' +
        '<div class="fleet-configure-form">' +
          '<div class="input-group">' +
            '<input type="text" class="form-control" id="fleetInlineUrlInput" placeholder="http://localhost:2510">' +
            '<button class="btn btn-primary" id="fleetInlineConnectBtn">' +
              '<i class="bi bi-plug me-1"></i>Connect' +
            '</button>' +
          '</div>' +
          '<div class="form-text">FleetWebAPI address (e.g. http://localhost:2510)</div>' +
        '</div>' +
      '</div>';

    var input = document.getElementById('fleetInlineUrlInput');
    var btn = document.getElementById('fleetInlineConnectBtn');
    if (btn && input) {
      btn.onclick = function () {
        var url = input.value.trim();
        if (!url) return;
        MM.fleetClient.configure(url)
          .then(function () {
            try { sessionStorage.setItem('mm_fleet_api_url', url); } catch (e) {}
            MM.showToast('Fleet Connected', 'Fleet API URL set to ' + url, 'success');
            MM.fleetClient.startPolling();
          })
          .catch(function (err) {
            MM.showToast('Error', 'Failed to configure fleet: ' + err.message, 'danger');
          });
      };
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') btn.click();
      });
    }
  }

  // ---- Error state ----

  function renderError(err) {
    var content = document.getElementById('fleetRemotePane');
    if (!content) return;

    content.innerHTML =
      '<div class="fleet-configure-prompt">' +
        '<div class="fleet-configure-icon text-danger"><i class="bi bi-exclamation-triangle"></i></div>' +
        '<h5>Fleet Unreachable</h5>' +
        '<p class="text-muted">' + _escapeHtml(err.message || String(err)) + '</p>' +
        '<button class="btn btn-outline-primary" id="fleetRetryBtn">' +
          '<i class="bi bi-arrow-clockwise me-1"></i>Retry' +
        '</button>' +
      '</div>';

    var retryBtn = document.getElementById('fleetRetryBtn');
    if (retryBtn) {
      retryBtn.onclick = function () {
        MM.fleetClient.startPolling();
      };
    }
  }

  // ---- Update handler (called from FleetClient polling) ----

  function onFleetUpdate(data, err) {
    if (err) {
      // Only show error if we don't have any cached data
      if (!_lastFleetData) {
        renderError(err);
      }
      renderSidebar(_lastFleetData);
      return;
    }

    // Skip re-render if nothing meaningful changed — preserves UI state
    // (expanded config panels, scroll position, etc.)
    // Exclude volatile fields (timestamps) that change every heartbeat.
    var json = _fleetFingerprint(data);
    if (json === _lastFleetJson) return;
    _lastFleetJson = json;

    _lastFleetData = data;
    renderSidebar(data);

    if (_activeHubId) {
      // Refresh hub detail if that hub is selected
      var hub = (data.hubs || []).find(function (h) { return h.hub_id === _activeHubId; });
      if (hub) {
        renderHubDetail(hub);
      } else {
        // Hub disappeared
        _activeHubId = null;
        renderDashboard(data);
      }
    } else {
      renderDashboard(data);
    }
  }

  // ---- Public API ----

  MM.fleetDashboard = {
    activate: function () {
      _activeHubId = null;
      _lastFleetData = null;
      _lastFleetJson = '';
      MM.fleetClient.onUpdate(onFleetUpdate);
    },
    deactivate: function () {
      _activeHubId = null;
    },
    renderConfigurePrompt: renderConfigurePrompt,
    renderDashboard: renderDashboard,
    renderSidebar: renderSidebar
  };

})();
