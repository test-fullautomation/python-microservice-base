/**
 * @fileoverview Consul Dashboard sub-tab.
 *
 * Two UI states:
 *  1. Setup form — start a Consul agent (Dev / Config) or connect to an
 *     existing cluster.
 *  2. Connected dashboard — shows cluster leader, node list, and the live
 *     set of services registered in Consul (replaces the old RabbitMQ
 *     `service_information` exchange).
 *
 * IIFE attaching to MM.consulDashboard.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var PANE_ID = 'consulPane';
  var STORAGE_KEY = 'mm_consul_url';
  var _active = false;
  var _connected = false;
  var _pollTimer = null;
  var _consulWindow = null;

  // True when the currently-connected Consul is the GUI-managed agent
  // (started via the Consul tab's Start Agent flow).  External agents
  // leave this false so the dashboard only shows Disconnect.
  //
  // Persisted to sessionStorage so it survives bridge restarts and
  // tab switches.
  var _MANAGED_KEY = 'mm_consul_managed';
  var _managedByGui = false;

  function _setManaged(val) {
    _managedByGui = !!val;
    try {
      if (_managedByGui) sessionStorage.setItem(_MANAGED_KEY, '1');
      else sessionStorage.removeItem(_MANAGED_KEY);
    } catch (e) {}
  }

  try {
    _managedByGui = sessionStorage.getItem(_MANAGED_KEY) === '1';
  } catch (e) {}

  // ----------------------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------------------

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _pane() { return document.getElementById(PANE_ID); }

  function _saveUrl(url) { try { localStorage.setItem(STORAGE_KEY, url); } catch (e) {} }
  function _getSavedUrl() { try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; } }

  function _wireBtn(id, handler) {
    var btn = document.getElementById(id);
    if (btn) btn.onclick = handler;
  }

  /**
   * Populate the bind-address datalist with the host's actual NICs by
   * fetching /api/system/network-interfaces from the bridge.  The form
   * already has two static <option>s in the datalist (127.0.0.1 +
   * 0.0.0.0) so it stays usable if the fetch fails.
   */
  function _populateBindAddrOptions() {
    var dl = document.getElementById('consulDevBindOptions');
    if (!dl) return;
    var origin = (MM.serviceClient && MM.serviceClient.apiUrl) || window.location.origin;
    fetch(origin + '/api/system/network-interfaces')
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !Array.isArray(data.interfaces)) return;
        // Build new <option>s with friendly labels.
        // Format: <option value="<ip>">IP — Interface name (kind)</option>
        // Datalists in modern browsers show both "value" and "label"; we
        // put the IP in value (so picking it sets the input correctly)
        // and the descriptive text inline.
        var html = data.interfaces.map(function (iface) {
          var label = iface.name + (iface.kind ? ' (' + iface.kind + ')' : '');
          return '<option value="' + iface.ip + '">' + label + '</option>';
        }).join('');
        dl.innerHTML = html;
      })
      .catch(function () { /* keep static defaults */ });
  }

  // ----------------------------------------------------------------------
  // Setup form
  // ----------------------------------------------------------------------

  function renderSetupForm(agentRunning, agentPid) {
    var pane = _pane();
    if (!pane) return;

    var agentCard = '';
    if (agentRunning) {
      agentCard =
        '<div class="alert alert-success d-flex justify-content-between align-items-center">' +
        '  <div>' +
        '    <i class="bi bi-check-circle me-1"></i>' +
        '    <strong>Managed Consul agent running</strong> (PID ' + agentPid + ')' +
        '  </div>' +
        '  <div>' +
        '    <button class="btn btn-sm btn-outline-secondary me-1" id="consulViewLogBtn">' +
        '      <i class="bi bi-terminal me-1"></i>View Log' +
        '    </button>' +
        '    <button class="btn btn-sm btn-outline-danger" id="consulStopAgentBtn">' +
        '      <i class="bi bi-stop-fill me-1"></i>Stop Agent' +
        '    </button>' +
        '  </div>' +
        '</div>';
    }

    pane.innerHTML =
      '<div class="container-fluid py-3" style="max-width: 760px;">' +
      '  <h5 class="mb-3"><i class="bi bi-compass me-2"></i>Consul Setup</h5>' +
      agentCard +
      '  <ul class="nav nav-pills mb-3" role="tablist">' +
      '    <li class="nav-item"><button class="nav-link active" data-mode="dev" type="button">Dev Mode</button></li>' +
      '    <li class="nav-item"><button class="nav-link" data-mode="config" type="button">Config Directory</button></li>' +
      '    <li class="nav-item"><button class="nav-link" data-mode="connect" type="button">Connect to Existing</button></li>' +
      '  </ul>' +

      '  <div class="card">' +
      '    <div class="card-body">' +

      // Dev mode panel
      '      <div class="mode-panel" data-panel="dev">' +
      '        <p class="text-muted small mb-3">' +
      '          Single-node in-memory agent. No persistence. Good for local development.' +
      '        </p>' +
      '        <div class="mb-2"><label class="form-label small">Node name</label>' +
      '          <input class="form-control form-control-sm" id="consulNodeName" placeholder="(auto)"></div>' +
      '        <div class="mb-2"><label class="form-label small">Datacenter</label>' +
      '          <input class="form-control form-control-sm" id="consulDc" value="dc1"></div>' +
      '        <div class="mb-2"><label class="form-label small">Bind address</label>' +
      '          <input class="form-control form-control-sm" id="consulDevBindAddr"' +
      '                 list="consulDevBindOptions" value="127.0.0.1"' +
      '                 placeholder="127.0.0.1">' +
      '          <datalist id="consulDevBindOptions">' +
      '            <option value="127.0.0.1">Loopback &mdash; recommended for local dev</option>' +
      '            <option value="0.0.0.0">All interfaces &mdash; reachable from other machines</option>' +
      '          </datalist>' +
      '          <div class="form-text">' +
      '            On a host with multiple private IPs (VPN / Docker / WSL / VirtualBox),' +
      '            Consul cannot auto-pick which one to advertise. Stick with' +
      '            <code>127.0.0.1</code> for local dev, or pick a specific NIC IP' +
      '            (use <code>0.0.0.0</code> only if you also need other machines' +
      '            to reach this Consul).' +
      '          </div>' +
      '        </div>' +
      '      </div>' +

      // Config mode panel
      '      <div class="mode-panel d-none" data-panel="config">' +
      '        <p class="text-muted small mb-3">' +
      '          Start an agent using configuration files from a directory.' +
      '        </p>' +
      '        <div class="mb-2"><label class="form-label small">Config directory</label>' +
      '          <input class="form-control form-control-sm" id="consulConfigDir" placeholder="/etc/consul.d"></div>' +
      '        <div class="mb-2"><label class="form-label small">Data directory</label>' +
      '          <input class="form-control form-control-sm" id="consulDataDir" placeholder="/opt/consul"></div>' +
      '        <div class="mb-2"><label class="form-label small">Bind address</label>' +
      '          <input class="form-control form-control-sm" id="consulBindAddr" value="0.0.0.0"></div>' +
      '        <div class="mb-2"><label class="form-label small">Node name</label>' +
      '          <input class="form-control form-control-sm" id="consulCfgNodeName" placeholder="(hostname)"></div>' +
      '        <div class="mb-2"><label class="form-label small">Datacenter</label>' +
      '          <input class="form-control form-control-sm" id="consulCfgDc" value="dc1"></div>' +
      '      </div>' +

      // Connect mode panel
      '      <div class="mode-panel d-none" data-panel="connect">' +
      '        <p class="text-muted small mb-3">' +
      '          Connect to a Consul agent or cluster that is already running.' +
      '        </p>' +
      '        <div class="mb-2"><label class="form-label small">Consul URL</label>' +
      '          <div class="input-group input-group-sm">' +
      '            <input class="form-control form-control-sm" id="consulExtUrl" value="' +
                    _esc(_getSavedUrl() || 'http://127.0.0.1:8500') + '">' +
      '            <button class="btn btn-outline-secondary" type="button" id="consulTabDetectBtn" ' +
      '                    title="Scan local processes for running Consul agents">' +
      '              <i class="bi bi-search me-1"></i>Detect' +
      '            </button>' +
      '          </div>' +
      '          <div class="form-text">Click <strong>Detect</strong> to find running <code>consul</code> processes.</div>' +
      '        </div>' +
      '        <div id="consulTabDetectResults"></div>' +
      '      </div>' +

      '      <hr class="my-3">' +
      '      <details class="mb-2">' +
      '        <summary class="small text-muted">Advanced</summary>' +
      '        <div class="mt-2">' +
      '          <div class="mb-2"><label class="form-label small">Consul binary</label>' +
      '            <input class="form-control form-control-sm" id="consulBinPath" value="' +
                       _esc(((MM.getSettings && MM.getSettings()) || {}).consulPath || 'consul') +
                     '"></div>' +
      '          <div class="mb-2"><label class="form-label small">HTTP port</label>' +
      '            <input class="form-control form-control-sm" id="consulHttpPort" value="8500"></div>' +
      '        </div>' +
      '      </details>' +

      '      <div class="d-flex gap-2 mt-3">' +
      '        <button class="btn btn-primary" id="consulStartBtn">' +
      '          <i class="bi bi-play-fill me-1"></i>Start Agent' +
      '        </button>' +
      '      </div>' +
      '    </div>' +
      '  </div>' +
      '</div>';

    // Populate the bind-address datalist with the host's actual NICs.
    // Falls back to the static defaults already in the datalist if the
    // bridge endpoint isn't reachable (older bridge, network glitch).
    _populateBindAddrOptions();

    // Wire tab switching
    var mode = 'dev';
    var tabs = pane.querySelectorAll('.nav-pills .nav-link');
    tabs.forEach(function (tab) {
      tab.onclick = function () {
        tabs.forEach(function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        mode = tab.getAttribute('data-mode');
        pane.querySelectorAll('.mode-panel').forEach(function (p) {
          p.classList.toggle('d-none', p.getAttribute('data-panel') !== mode);
        });
        var startBtn = document.getElementById('consulStartBtn');
        if (startBtn) {
          if (mode === 'connect') {
            startBtn.innerHTML = '<i class="bi bi-plug me-1"></i>Connect';
          } else {
            startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
          }
        }
      };
    });

    _wireBtn('consulStopAgentBtn', function () {
      MM.consulClient.stopAgent().then(function (data) {
        MM.showToast('Consul', data.message || 'Stopped', 'success');
        _checkAgentAndRenderSetup();
      }).catch(function (err) {
        MM.showToast('Consul', 'Stop failed: ' + err.message, 'danger');
      });
    });

    _wireBtn('consulViewLogBtn', _showAgentLog);

    _wireBtn('consulTabDetectBtn', function () {
      var btn = document.getElementById('consulTabDetectBtn');
      var results = document.getElementById('consulTabDetectResults');
      if (!btn || !results) return;

      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scanning...';
      results.innerHTML =
        '<div class="small text-muted mt-2">' +
        '  <span class="spinner-border spinner-border-sm me-1"></span>' +
        '  Looking for running <code>consul</code> processes...' +
        '</div>';

      MM.consulClient.discover()
        .then(function (data) {
          if (data && data.error) {
            results.innerHTML =
              '<div class="alert alert-danger small mt-2 mb-0">' +
              '  <i class="bi bi-exclamation-triangle me-1"></i>' +
                _esc(data.error) +
              '</div>';
            return;
          }
          var instances = (data && data.instances) || [];
          if (instances.length === 0) {
            results.innerHTML =
              '<div class="alert alert-warning small mt-2 mb-0">' +
              '  <i class="bi bi-exclamation-triangle me-1"></i>' +
              '  No running Consul processes found on this machine.' +
              '</div>';
            return;
          }

          var rows = instances.map(function (inst) {
            var roleBadge = inst.server
              ? '<span class="badge bg-primary ms-1">server</span>'
              : '<span class="badge bg-secondary ms-1">client</span>';
            var versionBadge = inst.version
              ? '<span class="badge bg-light text-dark ms-1">v' + _esc(inst.version) + '</span>'
              : '';
            var dcBadge = inst.datacenter
              ? '<span class="badge bg-light text-dark ms-1">' + _esc(inst.datacenter) + '</span>'
              : '';
            var pidBadge = inst.pid
              ? '<span class="badge bg-secondary ms-1">pid ' + inst.pid + '</span>'
              : '';

            return '<button type="button" class="list-group-item list-group-item-action consul-tab-detect-row"' +
                   '  data-url="' + _esc(inst.url) + '">' +
                   '  <div class="d-flex justify-content-between align-items-center">' +
                   '    <div>' +
                   '      <strong>' + _esc(inst.node_name || inst.host + ':' + inst.port) + '</strong>' +
                            roleBadge + versionBadge + dcBadge + pidBadge +
                   '      <div class="small text-muted">' + _esc(inst.url) + '</div>' +
                   '    </div>' +
                   '    <i class="bi bi-chevron-right"></i>' +
                   '  </div>' +
                   '</button>';
          }).join('');

          results.innerHTML =
            '<div class="small text-muted mt-2 mb-1">' +
            '  Found <strong>' + instances.length + '</strong> process(es) — click to select and connect:' +
            '</div>' +
            '<div class="list-group mb-2">' + rows + '</div>';

          // One-click: fill the URL input and trigger Start (which, in
          // connect mode, calls _connectTo directly).
          results.querySelectorAll('.consul-tab-detect-row').forEach(function (row) {
            row.addEventListener('click', function () {
              var url = row.getAttribute('data-url');
              var input = document.getElementById('consulExtUrl');
              if (input) input.value = url;
              results.querySelectorAll('.consul-tab-detect-row.active')
                     .forEach(function (el) { el.classList.remove('active'); });
              row.classList.add('active');
              var startBtn2 = document.getElementById('consulStartBtn');
              if (startBtn2) startBtn2.click();
            });
          });
        })
        .catch(function (err) {
          results.innerHTML =
            '<div class="alert alert-danger small mt-2 mb-0">' +
            '  Detect failed: ' + _esc(err.message || err) +
            '</div>';
        })
        .finally(function () {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-search me-1"></i>Detect';
        });
    });

    _wireBtn('consulStartBtn', function () {
      var startBtn = document.getElementById('consulStartBtn');
      if (mode === 'connect') {
        var extUrl = (document.getElementById('consulExtUrl').value || '').trim();
        if (!extUrl) {
          MM.showToast('Consul', 'Enter a URL first', 'warning');
          return;
        }
        startBtn.disabled = true;
        startBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Connecting...';
        _connectTo(extUrl, startBtn);
        return;
      }

      var httpPort = parseInt(document.getElementById('consulHttpPort').value) || 8500;
      var options = {
        mode: mode,
        consul_path: (document.getElementById('consulBinPath').value || '').trim() || 'consul',
        http_port: httpPort,
      };
      if (mode === 'dev') {
        options.node_name = (document.getElementById('consulNodeName').value || '').trim();
        options.datacenter = (document.getElementById('consulDc').value || '').trim() || 'dc1';
        // User-selectable bind address — defaults to 127.0.0.1 (loopback)
        // to avoid Consul's "Multiple private IPv4 addresses found" error
        // on workstations with VPN / Docker / WSL / VirtualBox NICs.
        // Datalist offers 127.0.0.1 + 0.0.0.0; user can also type a specific IP.
        options.bind_addr = (document.getElementById('consulDevBindAddr').value || '').trim() || '127.0.0.1';
      } else {
        options.config_dir = (document.getElementById('consulConfigDir').value || '').trim();
        options.data_dir = (document.getElementById('consulDataDir').value || '').trim();
        // 127.0.0.1 is the safe default — picks the loopback interface and
        // avoids the "Multiple private IPv4 addresses found" error Consul
        // raises on workstations with VPN / Docker / WSL / VirtualBox NICs.
        // Override to 0.0.0.0 (or a specific IP) only for cluster mode.
        options.bind_addr = (document.getElementById('consulBindAddr').value || '').trim() || '127.0.0.1';
        options.node_name = (document.getElementById('consulCfgNodeName').value || '').trim();
        options.datacenter = (document.getElementById('consulCfgDc').value || '').trim() || 'dc1';
      }

      startBtn.disabled = true;
      startBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Starting...';

      MM.consulClient.startAgent(options)
        .then(function (data) {
          if (!data.success) {
            _showStartError(data.message || 'Failed to start', data.log || '');
            MM.showToast('Consul', 'Failed to start — see details above', 'danger');
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
            return;
          }
          MM.showToast('Consul', data.message, 'success');
          _waitAndConnect(data.consul_url || ('http://127.0.0.1:' + httpPort), startBtn);
        })
        .catch(function (err) {
          _showStartError('Start failed: ' + err.message, '');
          MM.showToast('Consul', 'Start failed — see details above', 'danger');
          startBtn.disabled = false;
          startBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
        });
    });
  }

  function _showStartError(message, logTail) {
    var pane = _pane();
    if (!pane) return;
    var existing = document.getElementById('consulStartError');
    if (existing) existing.remove();

    var container = pane.querySelector('.container-fluid') || pane;
    var div = document.createElement('div');
    div.id = 'consulStartError';
    div.className = 'alert alert-danger mt-3';
    var html =
      '<div class="d-flex justify-content-between align-items-start mb-2">' +
      '  <strong><i class="bi bi-exclamation-triangle me-1"></i>Consul failed to start</strong>' +
      '  <button type="button" class="btn-close" aria-label="Close" id="consulStartErrorClose"></button>' +
      '</div>' +
      '<div class="small" style="white-space: pre-wrap;">' + _esc(message) + '</div>';
    if (logTail) {
      html +=
        '<hr class="my-2">' +
        '<pre class="small mb-0" style="max-height:180px;overflow:auto;background:#1e1e1e;color:#ddd;padding:8px;border-radius:4px;">' +
        _esc(logTail) + '</pre>';
    }
    div.innerHTML = html;
    container.insertBefore(div, container.firstChild);

    _wireBtn('consulStartErrorClose', function () { div.remove(); });
  }

  // ----------------------------------------------------------------------
  // Agent log popup
  // ----------------------------------------------------------------------

  function _showAgentLog() {
    var existing = document.getElementById('consulAgentLogPanel');
    if (existing) { existing.remove(); return; }

    var pane = _pane();
    if (!pane) return;

    var div = document.createElement('div');
    div.id = 'consulAgentLogPanel';
    div.className = 'mt-3';
    div.innerHTML =
      '<div class="card">' +
      '  <div class="card-header d-flex justify-content-between align-items-center">' +
      '    <span><i class="bi bi-terminal me-1"></i>Consul Agent Log</span>' +
      '    <button class="btn btn-outline-secondary btn-sm" id="consulLogRefreshBtn"><i class="bi bi-arrow-clockwise"></i></button>' +
      '  </div>' +
      '  <div class="card-body p-0">' +
      '    <pre id="consulAgentLogBody" class="m-0 p-2 small" style="max-height:260px;overflow:auto;background:#1e1e1e;color:#ddd;">Loading...</pre>' +
      '  </div>' +
      '</div>';
    pane.querySelector('.container-fluid').appendChild(div);

    _fetchAgentLog();
    _wireBtn('consulLogRefreshBtn', _fetchAgentLog);
  }

  function _fetchAgentLog() {
    MM.consulClient.getAgentLog(300).then(function (data) {
      var body = document.getElementById('consulAgentLogBody');
      if (body) body.textContent = data.log || '(empty)';
    });
  }

  // ----------------------------------------------------------------------
  // Connection with retry
  // ----------------------------------------------------------------------

  /**
   * Ask the bridge whether a GUI-managed Consul agent is running at
   * *url* and set _managedByGui accordingly.  Used by the external
   * connect and auto-reconnect paths — any time we end up connected
   * without going through Start Agent directly.
   */
  function _reevaluateManagedOwnership(url) {
    // Ask the bridge if it has a managed agent at this URL.
    // If the bridge is unreachable (down/restarting), KEEP the current
    // _managedByGui value from sessionStorage.
    MM.consulClient.getAgentStatus()
      .then(function (data) {
        if (data && data.running && data.consul_url &&
            String(data.consul_url).replace(/\/+$/, '') ===
              String(url).replace(/\/+$/, '')) {
          _setManaged(true);
        } else if (data && !data.running) {
          _setManaged(false);
        }
        if (_connected) renderDashboard();
      })
      .catch(function () {
        // Bridge unreachable — keep current value.
      });
  }

  function _waitAndConnect(url, btn, attempt) {
    attempt = attempt || 1;
    var maxAttempts = 6;   // ~12 s
    MM.consulClient.testConnection()
      .then(function (data) {
        if (!data.ok) throw new Error(data.error || 'not ready');
        _saveUrl(url);
        _connected = true;
        // This path only runs from Start Agent — GUI owns the lifecycle.
        _setManaged(true);
        MM.showToast('Consul', 'Connected — leader ' + (data.leader || 'unknown'), 'success');
        renderDashboard();
        _startPolling();
      })
      .catch(function () {
        if (attempt < maxAttempts) {
          if (btn) {
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Waiting for agent (' + attempt + '/' + maxAttempts + ')...';
          }
          setTimeout(function () { _waitAndConnect(url, btn, attempt + 1); }, 2000);
        } else {
          MM.showToast('Consul', 'Agent started but not reachable. Check agent log.', 'warning');
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start Agent';
          }
          _checkAgentAndRenderSetup();
        }
      });
  }

  function _connectTo(url, btn) {
    MM.consulClient.testConnection()
      .then(function (data) {
        if (!data.ok) throw new Error(data.error || 'not reachable');
        _saveUrl(url);
        _connected = true;
        _reevaluateManagedOwnership(url);
        MM.showToast('Consul', 'Connected — leader ' + (data.leader || 'unknown'), 'success');
        renderDashboard();
        _startPolling();
      })
      .catch(function (err) {
        MM.showToast('Consul', 'Connection failed: ' + err.message, 'danger');
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-plug me-1"></i>Connect';
        }
      });
  }

  // ----------------------------------------------------------------------
  // Connected dashboard
  // ----------------------------------------------------------------------

  function renderDashboard() {
    var pane = _pane();
    if (!pane) return;

    pane.innerHTML =
      '<div class="container-fluid py-3">' +
      '  <div class="d-flex justify-content-between align-items-center mb-3">' +
      '    <h5 class="mb-0"><i class="bi bi-compass me-2"></i>Consul' +
      '      <span class="badge bg-success ms-2" id="consulStatusBadge">connected</span>' +
      '    </h5>' +
      '    <div>' +
      '      <button class="btn btn-sm btn-outline-primary me-1" id="consulOpenUiBtn">' +
      '        <i class="bi bi-box-arrow-up-right me-1"></i>Open Consul UI' +
      '      </button>' +
      '      <button class="btn btn-sm btn-outline-secondary me-1" id="consulRefreshBtn">' +
      '        <i class="bi bi-arrow-clockwise"></i>' +
      '      </button>' +
      '      <button class="btn btn-sm btn-outline-danger me-1" id="consulDisconnectBtn">' +
      '        <i class="bi bi-plug me-1"></i>Disconnect' +
      '      </button>' +
      (_managedByGui
        ? '      <button class="btn btn-sm btn-danger" id="consulStopAgentDashBtn"' +
          '              title="Stop the GUI-managed Consul agent">' +
          '        <i class="bi bi-stop-fill me-1"></i>Stop Agent' +
          '      </button>'
        : '') +
      '    </div>' +
      '  </div>' +

      '  <div class="row g-2 mb-3">' +
      '    <div class="col"><div class="card text-center"><div class="card-body py-2">' +
      '      <div class="small text-muted">Services</div>' +
      '      <div class="h4 mb-0" id="consulServiceCount">—</div></div></div></div>' +
      '    <div class="col"><div class="card text-center"><div class="card-body py-2">' +
      '      <div class="small text-muted">Nodes</div>' +
      '      <div class="h4 mb-0" id="consulNodeCount">—</div></div></div></div>' +
      '    <div class="col"><div class="card text-center"><div class="card-body py-2">' +
      '      <div class="small text-muted">Leader</div>' +
      '      <div class="small fw-bold" id="consulLeader">—</div></div></div></div>' +
      '  </div>' +

      '  <div class="card">' +
      '    <div class="card-header py-2"><i class="bi bi-hdd-network me-1"></i>Registered Services</div>' +
      '    <div class="table-responsive">' +
      '      <table class="table table-sm mb-0">' +
      '        <thead><tr><th>Name</th><th>Tags</th><th>Healthy instances</th><th></th></tr></thead>' +
      '        <tbody id="consulServicesTable">' +
      '          <tr><td colspan="4" class="text-muted p-3">Loading services...</td></tr>' +
      '        </tbody>' +
      '      </table>' +
      '    </div>' +
      '  </div>' +
      '</div>';

    _wireBtn('consulRefreshBtn', _fetchAndRender);
    _wireBtn('consulOpenUiBtn', function () {
      var url = _getSavedUrl() || 'http://127.0.0.1:8500';
      if (_consulWindow && !_consulWindow.closed) {
        _consulWindow.focus();
        _consulWindow.location.href = url + '/ui/';
      } else {
        _consulWindow = window.open(url + '/ui/', 'consul-ui');
      }
    });
    _wireBtn('consulDisconnectBtn', function () {
      _connected = false;
      _setManaged(false);
      _stopPolling();
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
      _checkAgentAndRenderSetup();
    });

    _wireBtn('consulStopAgentDashBtn', function () {
      if (!confirm('Stop the GUI-managed Consul agent? ' +
                   'Any services registered through it will lose their ' +
                   'health checks.')) return;
      MM.consulClient.stopAgent()
        .then(function (data) {
          MM.showToast('Consul', (data && data.message) || 'Stopped', 'success');
          _connected = false;
          _setManaged(false);
          _stopPolling();
          try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
          _checkAgentAndRenderSetup();
        })
        .catch(function (err) {
          MM.showToast('Consul', 'Stop failed: ' + err.message, 'danger');
        });
    });

    _fetchAndRender();
  }

  var _consecutiveFailures = 0;

  function _fetchAndRender() {
    Promise.all([
      MM.consulClient.testConnection(),
      MM.consulClient.getServices(),
      MM.consulClient.getNodes()
    ]).then(function (results) {
      var health = results[0];
      var services = results[1];
      var nodes = results[2];

      // If Consul is unreachable, track failures and disconnect after 3.
      if (!health || !health.ok) {
        _consecutiveFailures++;
        if (_consecutiveFailures >= 2) {
          _connected = false;
          _stopPolling();
          _consecutiveFailures = 0;
          if (_active) _checkAgentAndRenderSetup();
        }
        // Update status badge to show the problem
        var badge = document.getElementById('consulStatusBadge');
        if (badge) {
          badge.className = 'badge bg-danger';
          badge.textContent = 'unreachable';
        }
        return;
      }
      _consecutiveFailures = 0;

      var leaderEl = document.getElementById('consulLeader');
      if (leaderEl) leaderEl.textContent = health && health.leader ? health.leader : '(unknown)';

      var nodeCountEl = document.getElementById('consulNodeCount');
      if (nodeCountEl) nodeCountEl.textContent = Array.isArray(nodes) ? nodes.length : '—';

      // Hide infrastructure services — Consul registers itself, and
      // Nomad registers `nomad` + `nomad-client` when it talks to Consul.
      var HIDDEN = { 'consul': 1, 'nomad': 1, 'nomad-client': 1 };
      var serviceNames = Object.keys(services || {}).filter(function (n) {
        return !HIDDEN[n];
      });

      var countEl = document.getElementById('consulServiceCount');
      if (countEl) countEl.textContent = serviceNames.length;

      var tbody = document.getElementById('consulServicesTable');
      if (!tbody) return;

      if (serviceNames.length === 0) {
        tbody.innerHTML =
          '<tr><td colspan="4" class="text-muted p-3">' +
          '  No services registered yet. Start a service so it registers with this Consul.' +
          '</td></tr>';
        return;
      }

      // For each service, fetch healthy instance count.
      Promise.all(serviceNames.map(function (name) {
        return MM.consulClient.getServiceDetail(name).catch(function () { return []; });
      })).then(function (details) {
        tbody.innerHTML = serviceNames.map(function (name, idx) {
          var instances = Array.isArray(details[idx]) ? details[idx] : [];
          var tags = (services[name] || []).map(function (t) {
            return '<span class="badge bg-secondary me-1">' + _esc(t) + '</span>';
          }).join('') || '<span class="text-muted small">(none)</span>';

          var instanceList = instances.map(function (inst) {
            var svc = inst.Service || {};
            return _esc((svc.Address || '') + ':' + (svc.Port || ''));
          }).join('<br>') || '<span class="text-muted">—</span>';

          return '<tr>' +
            '<td><strong>' + _esc(name) + '</strong></td>' +
            '<td>' + tags + '</td>' +
            '<td class="small">' + instanceList + '</td>' +
            '<td class="text-end">' +
            '  <span class="badge ' + (instances.length ? 'bg-success' : 'bg-warning text-dark') + '">' +
                 instances.length + ' healthy</span>' +
            '</td>' +
            '</tr>';
        }).join('');
      });
    }).catch(function (err) {
      console.warn('[ConsulDashboard] refresh failed:', err);
      _consecutiveFailures++;
      if (_consecutiveFailures >= 2) {
        _connected = false;
        _stopPolling();
        _consecutiveFailures = 0;
        if (_active) _checkAgentAndRenderSetup();
      }
    });
  }

  // ----------------------------------------------------------------------
  // Polling
  // ----------------------------------------------------------------------

  function _startPolling() {
    _stopPolling();
    _pollTimer = setInterval(function () {
      if (_active && _connected) _fetchAndRender();
    }, 5000);
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  // ----------------------------------------------------------------------
  // Setup entry
  // ----------------------------------------------------------------------

  function _checkAgentAndRenderSetup() {
    MM.consulClient.getAgentStatus()
      .then(function (data) { renderSetupForm(data.running, data.pid); })
      .catch(function () { renderSetupForm(false, null); });
  }

  // ----------------------------------------------------------------------
  // Public API
  // ----------------------------------------------------------------------

  MM.consulDashboard = {

    activate: function () {
      _active = true;
      _consecutiveFailures = 0;

      // Always probe Consul before rendering the connected dashboard.
      // This prevents the jarring "connected → unreachable → setup"
      // sequence when Consul was killed while the user was on another tab.
      //
      // Show a brief spinner, then render connected or setup form based
      // on the probe result.  The spinner is at most ~2 seconds visible.
      var pane = _pane();
      if (pane) {
        pane.innerHTML =
          '<div class="content-loading">' +
          '  <div class="spinner-border" role="status"></div>' +
          '  <span class="ms-2">Checking Consul...</span>' +
          '</div>';
      }

      // Determine which URL to probe — toolbar connection, saved URL, or default.
      var probeUrl = '';
      if (typeof MM.getConnectedConsuls === 'function' &&
          MM.getConnectedConsuls().length > 0) {
        probeUrl = MM.getConnectedConsuls()[0].url;
        MM.consulClient.configure(probeUrl).catch(function () {});
      }

      var settled = false;
      var timeoutId = setTimeout(function () {
        if (settled || !_active) return;
        settled = true;
        _connected = false;
        _checkAgentAndRenderSetup();
      }, 4000);

      MM.consulClient.testConnection()
        .then(function (data) {
          if (settled || !_active) return;
          settled = true;
          clearTimeout(timeoutId);
          if (data && data.ok) {
            _connected = true;
            if (probeUrl) _reevaluateManagedOwnership(probeUrl);
            renderDashboard();
            _startPolling();
          } else {
            _connected = false;
            _checkAgentAndRenderSetup();
          }
        })
        .catch(function () {
          if (settled || !_active) return;
          settled = true;
          clearTimeout(timeoutId);
          _connected = false;
          _checkAgentAndRenderSetup();
        });
    },

    deactivate: function () {
      _active = false;
      _stopPolling();
    }
  };

  // Listen for bridge state transitions.  Consul proxy endpoints depend on
  // the bridge subprocess; when the bridge is killed/restarted we need to
  // reset local state and re-probe on the way back up.
  window.addEventListener('mm:bridge-state', function (ev) {
    var state = ev && ev.detail && ev.detail.state;
    var prev  = ev && ev.detail && ev.detail.previous;

    if (state === 'down') {
      _stopPolling();
      _connected = false;
      // Do NOT reset _managedByGui here — it's persisted in sessionStorage
      // so we remember it was a managed agent when the bridge comes back.
      if (_active) {
        var pane = _pane();
        if (pane) {
          pane.innerHTML =
            '<div class="alert alert-warning m-3">' +
            '  <i class="bi bi-exclamation-triangle me-2"></i>' +
            '  Bridge is down. Start the bridge from the toolbar to reconnect.' +
            '</div>';
        }
      }
      return;
    }

    if (state === 'up' && prev && prev !== 'up') {
      // Bridge is back.  Rehydrate the bridge's Consul URL from localStorage
      // (the bridge forgot it when it was killed), then re-probe.
      var savedUrl = _getSavedUrl();

      var reconfigure = savedUrl
        ? MM.consulClient.configure(savedUrl)
        : Promise.resolve();

      reconfigure
        .then(function () { return MM.consulClient.testConnection(); })
        .then(function (data) {
          if (!data || !data.ok) throw new Error('not reachable');
          _connected = true;
          // Re-evaluate managed ownership now that the bridge is back.
          if (savedUrl) _reevaluateManagedOwnership(savedUrl);
          if (_active) {
            renderDashboard();
            _startPolling();
          }
        })
        .catch(function () {
          if (_active) _checkAgentAndRenderSetup();
        });
    }
  });

})();
