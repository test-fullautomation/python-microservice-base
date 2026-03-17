/**
 * @fileoverview Nomad Dashboard for the Nomad sub-tab.
 *
 * Two-state UI:
 * 1. Setup form — configure and start a Nomad agent, or connect to an
 *    existing one.
 * 2. Connected dashboard — cluster summary, jobs table, quick-links that
 *    open the full Nomad UI in a browser window.
 *
 * IIFE attaching to MM.nomadDashboard.
 *
 * @version 3.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var PANE_ID = 'nomadPane';
  var _active = false;
  var _currentUrl = null;
  var _pollTimer = null;
  var _nomadWindow = null;

  // ===== Helpers ==========================================================

  function _esc(str) {
    if (!str) return '';
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function _pane() {
    return document.getElementById(PANE_ID);
  }

  function _saveUrl(url) {
    try { localStorage.setItem('mm_nomad_url', url); } catch (e) {}
  }

  function _getSavedUrl() {
    try { return localStorage.getItem('mm_nomad_url') || ''; } catch (e) {}
    return '';
  }

  function _clearSavedUrl() {
    try { localStorage.removeItem('mm_nomad_url'); } catch (e) {}
  }

  function _statusIcon(status) {
    var s = (status || '').toLowerCase();
    if (s === 'running') return 'bi-circle-fill text-success';
    if (s === 'pending') return 'bi-clock text-warning';
    return 'bi-circle text-secondary';
  }

  // ===== Setup Form =======================================================

  function renderSetupForm(agentRunning, agentPid) {
    var pane = _pane();
    if (!pane) return;
    _stopPolling();
    _currentUrl = null;

    var savedUrl = _getSavedUrl() || 'http://127.0.0.1:4646';

    pane.innerHTML =
      '<div class="local-hub-setup">' +
        '<div class="local-hub-setup-icon"><i class="bi bi-hdd-rack"></i></div>' +
        '<h5>Nomad Orchestrator</h5>' +
        '<p class="text-muted">Start a local Nomad agent or connect to an existing cluster.</p>' +
        '<div class="local-hub-setup-form">' +
          // Mode
          '<div class="mb-3">' +
            '<label class="form-label fw-semibold">Mode</label>' +
            '<div class="form-check">' +
              '<input class="form-check-input" type="radio" name="nomadMode" id="nomadModeDev" value="dev" checked>' +
              '<label class="form-check-label" for="nomadModeDev">Dev Mode <span class="text-muted">(single-node, in-memory)</span></label>' +
            '</div>' +
            '<div class="form-check">' +
              '<input class="form-check-input" type="radio" name="nomadMode" id="nomadModeConfig" value="config">' +
              '<label class="form-check-label" for="nomadModeConfig">Config File</label>' +
            '</div>' +
            '<div class="form-check">' +
              '<input class="form-check-input" type="radio" name="nomadMode" id="nomadModeExternal" value="external">' +
              '<label class="form-check-label" for="nomadModeExternal">Connect to Existing Cluster</label>' +
            '</div>' +
          '</div>' +
          // Dev mode fields
          '<div id="nomadDevFields">' +
            '<div class="row mb-3">' +
              '<div class="col">' +
                '<label for="nomadNodeName" class="form-label">Node Name</label>' +
                '<input type="text" class="form-control" id="nomadNodeName" placeholder="(auto)">' +
              '</div>' +
              '<div class="col">' +
                '<label for="nomadDc" class="form-label">Datacenter</label>' +
                '<input type="text" class="form-control" id="nomadDc" value="dc1">' +
              '</div>' +
            '</div>' +
          '</div>' +
          // Config mode fields (hidden)
          '<div id="nomadConfigFields" style="display:none;">' +
            '<div class="mb-3">' +
              '<label for="nomadConfigFile" class="form-label">Config File (.hcl)</label>' +
              '<input type="text" class="form-control" id="nomadConfigFile" placeholder="/etc/nomad.d/nomad.hcl">' +
            '</div>' +
            '<div class="row mb-3">' +
              '<div class="col">' +
                '<label for="nomadDataDir" class="form-label">Data Directory</label>' +
                '<input type="text" class="form-control" id="nomadDataDir" placeholder="/opt/nomad/data">' +
              '</div>' +
              '<div class="col">' +
                '<label for="nomadBindAddr" class="form-label">Bind Address</label>' +
                '<input type="text" class="form-control" id="nomadBindAddr" value="0.0.0.0">' +
              '</div>' +
            '</div>' +
            '<div class="row mb-3">' +
              '<div class="col">' +
                '<label for="nomadCfgNodeName" class="form-label">Node Name</label>' +
                '<input type="text" class="form-control" id="nomadCfgNodeName" placeholder="(auto)">' +
              '</div>' +
              '<div class="col">' +
                '<label for="nomadCfgDc" class="form-label">Datacenter</label>' +
                '<input type="text" class="form-control" id="nomadCfgDc" value="dc1">' +
              '</div>' +
            '</div>' +
          '</div>' +
          // External fields (hidden)
          '<div id="nomadExternalFields" style="display:none;">' +
            '<div class="mb-3">' +
              '<label for="nomadExternalUrl" class="form-label">Nomad Agent URL</label>' +
              '<input type="text" class="form-control" id="nomadExternalUrl" value="' + _esc(savedUrl) + '" placeholder="http://127.0.0.1:4646">' +
            '</div>' +
          '</div>' +
          // Advanced
          '<div class="mb-3">' +
            '<a class="text-decoration-none" data-bs-toggle="collapse" href="#nomadAdvanced" role="button" aria-expanded="false">' +
              '<i class="bi bi-gear me-1"></i>Advanced' +
            '</a>' +
          '</div>' +
          '<div class="collapse" id="nomadAdvanced">' +
            '<div class="row mb-3">' +
              '<div class="col">' +
                '<label for="nomadBinPath" class="form-label">Nomad Binary</label>' +
                '<input type="text" class="form-control" id="nomadBinPath" value="nomad" placeholder="nomad">' +
              '</div>' +
              '<div class="col">' +
                '<label for="nomadHttpPort" class="form-label">HTTP Port</label>' +
                '<input type="number" class="form-control" id="nomadHttpPort" value="4646">' +
              '</div>' +
            '</div>' +
          '</div>' +
          // Agent status card (if running)
          (agentRunning
            ? '<div class="card mb-3 border-success">' +
                '<div class="card-header d-flex align-items-center justify-content-between">' +
                  '<span><i class="bi bi-hdd-rack me-2"></i>Nomad Agent</span>' +
                  '<span class="badge bg-success">Running (PID ' + (agentPid || '?') + ')</span>' +
                '</div>' +
                '<div class="card-body">' +
                  '<div class="d-flex gap-2">' +
                    '<button class="btn btn-sm btn-outline-primary" id="nomadBtnViewLog">' +
                      '<i class="bi bi-terminal me-1"></i>View Log</button>' +
                    '<button class="btn btn-sm btn-danger" id="nomadBtnStopAgent">' +
                      '<i class="bi bi-stop-fill me-1"></i>Stop Agent</button>' +
                  '</div>' +
                '</div>' +
              '</div>'
            : '') +
          // Action button
          (agentRunning
            ? '<button class="btn btn-primary" id="nomadBtnConnect">' +
                '<i class="bi bi-plug me-1"></i>Connect to Running Agent</button>'
            : '<button class="btn btn-primary" id="nomadBtnStart">' +
                '<i class="bi bi-play-fill me-1"></i>Start Agent</button>') +
        '</div>' +
      '</div>';

    // Wire mode radio toggle
    var radios = pane.querySelectorAll('input[name="nomadMode"]');
    var devFields = document.getElementById('nomadDevFields');
    var configFields = document.getElementById('nomadConfigFields');
    var externalFields = document.getElementById('nomadExternalFields');
    radios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        var selected = pane.querySelector('input[name="nomadMode"]:checked').value;
        devFields.style.display = selected === 'dev' ? '' : 'none';
        configFields.style.display = selected === 'config' ? '' : 'none';
        externalFields.style.display = selected === 'external' ? '' : 'none';
      });
    });

    // Wire stop agent button
    var stopAgentBtn = document.getElementById('nomadBtnStopAgent');
    if (stopAgentBtn) {
      stopAgentBtn.onclick = function () {
        stopAgentBtn.disabled = true;
        MM.nomadClient.stopAgent()
          .then(function (data) {
            MM.showToast('Nomad', data.message || 'Agent stopped', 'success');
            renderSetupForm(false, null);
          })
          .catch(function (err) {
            MM.showToast('Nomad', 'Stop failed: ' + err.message, 'danger');
            stopAgentBtn.disabled = false;
          });
      };
    }

    // Wire view log button
    var viewLogBtn = document.getElementById('nomadBtnViewLog');
    if (viewLogBtn) {
      viewLogBtn.onclick = function () {
        _showAgentLog();
      };
    }

    // Wire start / connect button
    var startBtn = document.getElementById('nomadBtnStart');
    var connectBtn = document.getElementById('nomadBtnConnect');

    if (startBtn) {
      startBtn.onclick = function () {
        var mode = pane.querySelector('input[name="nomadMode"]:checked').value;

        if (mode === 'external') {
          // Just connect to existing
          var extUrl = (document.getElementById('nomadExternalUrl').value || '').trim()
            || 'http://127.0.0.1:4646';
          extUrl = extUrl.replace(/\/+$/, '');
          startBtn.disabled = true;
          startBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Connecting...';
          _connectToUrl(extUrl, startBtn);
          return;
        }

        // Start agent via bridge
        var options = {
          mode: mode,
          nomad_path: (document.getElementById('nomadBinPath').value || '').trim() || 'nomad',
          http_port: parseInt(document.getElementById('nomadHttpPort').value) || 4646,
        };
        if (mode === 'dev') {
          options.node_name = (document.getElementById('nomadNodeName').value || '').trim();
          options.datacenter = (document.getElementById('nomadDc').value || '').trim() || 'dc1';
        } else if (mode === 'config') {
          options.config_file = (document.getElementById('nomadConfigFile').value || '').trim();
          options.data_dir = (document.getElementById('nomadDataDir').value || '').trim();
          options.bind_addr = (document.getElementById('nomadBindAddr').value || '').trim() || '0.0.0.0';
          options.node_name = (document.getElementById('nomadCfgNodeName').value || '').trim();
          options.datacenter = (document.getElementById('nomadCfgDc').value || '').trim() || 'dc1';
        }

        startBtn.disabled = true;
        startBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Starting...';

        MM.nomadClient.startAgent(options)
          .then(function (data) {
            if (!data.success) {
              MM.showToast('Nomad', data.message || 'Failed to start', 'danger');
              startBtn.disabled = false;
              startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
              return;
            }
            MM.showToast('Nomad', data.message, 'success');
            var url = data.nomad_url || ('http://127.0.0.1:' + options.http_port);
            // Retry connection until agent is ready (up to ~15s)
            _waitAndConnect(url, startBtn);
          })
          .catch(function (err) {
            MM.showToast('Nomad', 'Start failed: ' + err.message, 'danger');
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
          });
      };
    }

    if (connectBtn) {
      connectBtn.onclick = function () {
        var httpPort = parseInt(document.getElementById('nomadHttpPort').value) || 4646;
        var url = 'http://127.0.0.1:' + httpPort;
        connectBtn.disabled = true;
        connectBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Connecting...';
        _connectToUrl(url, connectBtn);
      };
    }
  }

  function _showAgentLog() {
    var pane = _pane();
    if (!pane) return;
    var existing = document.getElementById('nomadAgentLogPanel');
    if (existing) { existing.remove(); return; }

    var div = document.createElement('div');
    div.id = 'nomadAgentLogPanel';
    div.className = 'mt-3';
    div.style.maxWidth = '450px';
    div.style.margin = '1rem auto';
    div.innerHTML =
      '<div class="card local-hub-log-panel">' +
      '  <div class="card-header d-flex justify-content-between align-items-center">' +
      '    <span><i class="bi bi-terminal me-1"></i>Agent Log</span>' +
      '    <button class="btn btn-outline-secondary btn-sm" id="nomadLogRefreshBtn"><i class="bi bi-arrow-clockwise"></i></button>' +
      '  </div>' +
      '  <pre class="lh-log-content" id="nomadAgentLogContent">Loading...</pre>' +
      '</div>';
    // Insert after the setup form
    var setupForm = pane.querySelector('.local-hub-setup');
    if (setupForm) setupForm.appendChild(div);
    else pane.appendChild(div);

    _fetchAgentLog();
    document.getElementById('nomadLogRefreshBtn').onclick = _fetchAgentLog;
  }

  function _fetchAgentLog() {
    var pre = document.getElementById('nomadAgentLogContent');
    if (!pre) return;
    MM.nomadClient.getAgentLog(200)
      .then(function (data) {
        pre.textContent = data.log || '(empty)';
        pre.scrollTop = pre.scrollHeight;
      })
      .catch(function (err) {
        pre.textContent = 'Error: ' + err.message;
      });
  }

  // ===== Connect ==========================================================

  function _waitAndConnect(url, btn, attempt) {
    attempt = attempt || 1;
    var maxAttempts = 8; // ~16s total (2s between each)
    fetch(url + '/v1/agent/self', { method: 'GET' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (info) {
        _saveUrl(url);
        _currentUrl = url;
        var serverName = (info.member || {}).Name || 'unknown';
        MM.showToast('Nomad', 'Connected to ' + serverName, 'success');
        MM.nomadClient.configure(url).catch(function () {});
        _fetchAndRender();
        _startPolling();
      })
      .catch(function () {
        if (attempt < maxAttempts) {
          if (btn) {
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Waiting for agent (' + attempt + '/' + maxAttempts + ')...';
          }
          setTimeout(function () { _waitAndConnect(url, btn, attempt + 1); }, 2000);
        } else {
          MM.showToast('Nomad', 'Agent started but not reachable at ' + url + '. Check agent log.', 'warning');
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
          }
          _checkAgentAndRenderSetup();
        }
      });
  }

  function _connectToUrl(url, btn) {
    fetch(url + '/v1/agent/self', { method: 'GET' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (info) {
        _saveUrl(url);
        _currentUrl = url;
        var serverName = (info.member || {}).Name || 'unknown';
        MM.showToast('Nomad', 'Connected to ' + serverName, 'success');
        MM.nomadClient.configure(url).catch(function () {});
        _fetchAndRender();
        _startPolling();
      })
      .catch(function (err) {
        MM.showToast('Nomad', 'Connection failed: ' + err.message, 'danger');
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-plug me-1"></i>Connect';
        }
      });
  }

  // ===== Polling ==========================================================

  function _startPolling() {
    _stopPolling();
    _pollTimer = setInterval(function () {
      if (_active && _currentUrl) _fetchAndRender();
    }, 5000);
  }

  function _stopPolling() {
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  // ===== Fetch & Render ===================================================

  function _fetchAndRender() {
    if (!_currentUrl) return;
    Promise.all([
      fetch(_currentUrl + '/v1/jobs', { method: 'GET' }).then(function (r) { return r.json(); }),
      fetch(_currentUrl + '/v1/nodes', { method: 'GET' }).then(function (r) { return r.json(); })
    ])
      .then(function (results) {
        renderDashboard(results[0] || [], results[1] || []);
      })
      .catch(function () {
        _stopPolling();
        _currentUrl = null;
        _checkAgentAndRenderSetup();
        MM.showToast('Nomad', 'Connection lost', 'warning');
      });
  }

  // ===== Connected Dashboard ==============================================

  function renderDashboard(jobs, nodes) {
    var pane = _pane();
    if (!pane) return;

    var running = 0, pending = 0, dead = 0;
    for (var i = 0; i < jobs.length; i++) {
      var s = (jobs[i].Status || '').toLowerCase();
      if (s === 'running') running++;
      else if (s === 'pending') pending++;
      else dead++;
    }

    var readyNodes = 0;
    for (var n = 0; n < nodes.length; n++) {
      if ((nodes[n].Status || '').toLowerCase() === 'ready') readyNodes++;
    }

    var html =
      // --- Header ---
      '<div class="local-hub-header">' +
      '  <div>' +
      '    <h5><i class="bi bi-hdd-rack me-2"></i>Nomad Cluster' +
      '      <span class="fleet-status-badge online">Connected</span></h5>' +
      '    <div class="text-muted" style="font-size:0.82rem">' +
      '      <i class="bi bi-link-45deg me-1"></i>' + _esc(_currentUrl) +
      '    </div>' +
      '  </div>' +
      '  <div class="local-hub-toolbar">' +
      '    <button class="btn btn-primary btn-sm" id="nomadOpenUiBtn">' +
      '      <i class="bi bi-box-arrow-up-right me-1"></i>Open Nomad UI</button>' +
      '    <button class="btn btn-outline-secondary btn-sm" id="nomadRefreshBtn">' +
      '      <i class="bi bi-arrow-clockwise"></i></button>' +
      '    <button class="btn btn-outline-danger btn-sm" id="nomadDisconnectBtn">' +
      '      <i class="bi bi-x-circle me-1"></i>Disconnect</button>' +
      '  </div>' +
      '</div>' +
      // --- Summary Cards ---
      '<div class="fleet-summary">' +
      '  <div class="fleet-stat-card">' +
      '    <div class="fleet-stat-value">' + jobs.length + '</div>' +
      '    <div class="fleet-stat-label">Total Jobs</div>' +
      '  </div>' +
      '  <div class="fleet-stat-card">' +
      '    <div class="fleet-stat-value" style="color:#27ae60">' + running + '</div>' +
      '    <div class="fleet-stat-label">Running</div>' +
      '  </div>' +
      '  <div class="fleet-stat-card">' +
      '    <div class="fleet-stat-value" style="color:#f39c12">' + pending + '</div>' +
      '    <div class="fleet-stat-label">Pending</div>' +
      '  </div>' +
      '  <div class="fleet-stat-card">' +
      '    <div class="fleet-stat-value" style="color:#95a5a6">' + dead + '</div>' +
      '    <div class="fleet-stat-label">Dead</div>' +
      '  </div>' +
      '  <div class="fleet-stat-card">' +
      '    <div class="fleet-stat-value" style="color:#3498db">' + readyNodes + '/' + nodes.length + '</div>' +
      '    <div class="fleet-stat-label">Nodes Ready</div>' +
      '  </div>' +
      '</div>' +
      // --- Quick Links ---
      '<div class="row g-3 mb-3">' +
      _quickLink('bi-briefcase', 'Jobs', '/ui/jobs', 'View and manage all jobs') +
      _quickLink('bi-pc-display', 'Clients', '/ui/clients', 'Client nodes and resources') +
      _quickLink('bi-hdd-stack', 'Servers', '/ui/servers', 'Server members and Raft') +
      _quickLink('bi-window-stack', 'Topology', '/ui/topology', 'Cluster topology map') +
      '</div>';

    // --- Jobs Table ---
    if (jobs.length > 0) {
      html +=
        '<div class="card">' +
        '  <div class="card-header d-flex justify-content-between align-items-center">' +
        '    <span><i class="bi bi-briefcase me-1"></i>Jobs</span>' +
        '    <button class="btn btn-outline-primary btn-sm" id="nomadOpenJobsBtn">' +
        '      <i class="bi bi-box-arrow-up-right me-1"></i>Manage in Nomad UI</button>' +
        '  </div>' +
        '  <div class="card-body p-0">' +
        '    <table class="table table-sm table-hover mb-0">' +
        '      <thead><tr>' +
        '        <th style="width:30px"></th>' +
        '        <th>Name</th>' +
        '        <th>Type</th>' +
        '        <th>Status</th>' +
        '        <th>Task Groups</th>' +
        '        <th style="width:40px"></th>' +
        '      </tr></thead>' +
        '      <tbody>';
      for (var j = 0; j < jobs.length; j++) {
        var job = jobs[j];
        var st = job.Status || 'dead';
        var summary = (job.JobSummary || {}).Summary || {};
        var tgInfo = [];
        for (var tg in summary) {
          if (!summary.hasOwnProperty(tg)) continue;
          var ts = summary[tg];
          var r2 = ts.Running || 0;
          tgInfo.push(_esc(tg) + ' (' + r2 + ')');
        }
        html +=
          '<tr>' +
          '  <td><i class="bi ' + _statusIcon(st) + '"></i></td>' +
          '  <td>' +
          '    <a href="#" class="nomad-job-link" data-job-id="' + _esc(job.ID) + '"' +
          '       style="color:inherit;text-decoration:none;font-weight:500">' +
          _esc(job.Name || job.ID) + '</a></td>' +
          '  <td><span class="badge bg-secondary">' + _esc(job.Type) + '</span></td>' +
          '  <td><span class="fleet-status-badge ' + (st === 'running' ? 'online' : st === 'pending' ? 'degraded' : 'offline') + '">' + _esc(st) + '</span></td>' +
          '  <td style="font-size:0.82rem">' + (tgInfo.join(', ') || '-') + '</td>' +
          '  <td>' +
          '    <button class="btn btn-outline-primary btn-sm py-0 px-1 nomad-view-btn" data-job-id="' + _esc(job.ID) + '" title="Open in Nomad UI">' +
          '      <i class="bi bi-box-arrow-up-right"></i></button>' +
          '  </td>' +
          '</tr>';
      }
      html += '</tbody></table></div></div>';
    } else {
      html +=
        '<div class="text-center text-muted py-5">' +
        '  <i class="bi bi-inbox" style="font-size:2.5rem;color:#bdc3c7"></i>' +
        '  <p class="mt-2">No jobs found on this Nomad cluster.</p>' +
        '</div>';
    }

    // --- Agent log panel (if agent managed by us) ---
    html += '<div id="nomadAgentLogPanelDash" class="mt-3"></div>';

    pane.innerHTML = html;

    // --- Wire buttons ---
    _wireBtn('nomadOpenUiBtn', function () { _openNomadUI('/ui/jobs'); });
    _wireBtn('nomadRefreshBtn', function () { _fetchAndRender(); });
    _wireBtn('nomadOpenJobsBtn', function () { _openNomadUI('/ui/jobs'); });
    _wireBtn('nomadDisconnectBtn', function () {
      _stopPolling();
      _currentUrl = null;
      _clearSavedUrl();
      _checkAgentAndRenderSetup();
    });

    // Quick link cards
    var cards = pane.querySelectorAll('.nomad-quick-link');
    for (var c = 0; c < cards.length; c++) {
      cards[c].addEventListener('click', (function (path) {
        return function () { _openNomadUI(path); };
      })(cards[c].getAttribute('data-path')));
    }

    // Job links
    var jobLinks = pane.querySelectorAll('.nomad-job-link');
    for (var l = 0; l < jobLinks.length; l++) {
      jobLinks[l].addEventListener('click', (function (jobId) {
        return function (e) {
          e.preventDefault();
          _openNomadUI('/ui/jobs/' + jobId);
        };
      })(jobLinks[l].getAttribute('data-job-id')));
    }

    var viewBtns = pane.querySelectorAll('.nomad-view-btn');
    for (var v = 0; v < viewBtns.length; v++) {
      viewBtns[v].addEventListener('click', (function (jobId) {
        return function () { _openNomadUI('/ui/jobs/' + jobId); };
      })(viewBtns[v].getAttribute('data-job-id')));
    }
  }

  function _quickLink(icon, title, path, desc) {
    return (
      '<div class="col-md-3 col-sm-6">' +
      '  <div class="fleet-hub-card nomad-quick-link" data-path="' + _esc(path) + '" style="cursor:pointer">' +
      '    <div class="fleet-hub-card-body text-center py-3">' +
      '      <i class="bi ' + icon + '" style="font-size:1.8rem;color:#3498db"></i>' +
      '      <div class="fw-bold mt-1">' + _esc(title) + '</div>' +
      '      <div style="font-size:0.78rem;color:#7f8c8d" class="mt-1">' + _esc(desc) + '</div>' +
      '    </div>' +
      '  </div>' +
      '</div>'
    );
  }

  function _wireBtn(id, handler) {
    var el = document.getElementById(id);
    if (el) el.onclick = handler;
  }

  function _openNomadUI(path) {
    var url = _currentUrl + (path || '/ui/');
    if (_nomadWindow && !_nomadWindow.closed) {
      _nomadWindow.location.href = url;
      _nomadWindow.focus();
    } else {
      _nomadWindow = window.open(url, 'nomad_ui');
    }
  }

  // ===== State check ======================================================

  function _checkAgentAndRenderSetup() {
    // Ask the bridge if it has a managed Nomad agent running
    MM.nomadClient.getAgentStatus()
      .then(function (data) {
        renderSetupForm(data.running, data.pid);
      })
      .catch(function () {
        renderSetupForm(false, null);
      });
  }

  // ===== Public API =======================================================

  MM.nomadDashboard = {

    activate: function () {
      _active = true;

      // If already connected, resume polling
      if (_currentUrl) {
        _fetchAndRender();
        _startPolling();
        return;
      }

      // Try to restore saved URL
      var savedUrl = _getSavedUrl();
      if (savedUrl) {
        var pane = _pane();
        if (pane) {
          pane.innerHTML =
            '<div class="content-loading">' +
            '  <div class="spinner-border" role="status"></div>' +
            '  <span class="ms-2">Connecting to Nomad...</span>' +
            '</div>';
        }
        // Test connectivity
        fetch(savedUrl + '/v1/agent/self', { method: 'GET' })
          .then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
          })
          .then(function () {
            if (!_active) return;
            _currentUrl = savedUrl;
            MM.nomadClient.configure(savedUrl).catch(function () {});
            _fetchAndRender();
            _startPolling();
          })
          .catch(function () {
            if (!_active) return;
            _checkAgentAndRenderSetup();
          });
      } else {
        _checkAgentAndRenderSetup();
      }
    },

    deactivate: function () {
      _active = false;
      _stopPolling();
    }
  };

})();
