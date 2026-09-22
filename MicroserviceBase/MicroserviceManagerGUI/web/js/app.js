/**
 * @fileoverview Manages actions and interactions for the Services Manager GUI.
 * Refactored for dual hosting (Electron + browser). No Node.js dependencies.
 *
 * @author Nguyen Huynh Tri Cuong
 * @version 2.0.0
 */

(function () {
  'use strict';

  const MM = window.MicroserviceManager;

  /************************************************************
   *                    Global Variables                      *
   ************************************************************/

  // Legacy globals — kept as dynamic aliases for backward compatibility.
  // They reflect the *currently active* broker (set on service click).
  MM.brokerUrl = 'localhost:5672';
  MM.routingKey = '';
  MM.servicesInfor = null;

  // Multi-broker data model
  MM.connections = {};       // { 'host:port': { brokerUrl, routingKey, services: {}, realtimeSubscribed } }
  MM.activeBrokerUrl = null; // set when user clicks a service item
  var serviceToBroker = {};  // { serviceName: 'host:port' } — reverse lookup

  const SERVICES_EXCHANGE_NAME = 'services_request';
  const SERVICES_GUI_FOLDER = 'services';
  const SERVICE_CONTENT_DIV = 'serviceContent';
  const SERVICE_LIST_DIV = 'servicesList';

  const DIV_NAME = {
    SERVICE_CONTENT_DIV: 'serviceContent',
    SERVICE_LIST_DIV: 'servicesList'
  };

  const CONNECTION_STATUS = {
    CONNECTED: 'connected',
    DISCONNECTED: 'disconnected'
  };

  const DEFAULT_GROUP = 'Other';

  // Internal services hidden from the sidebar.
  const HIDDEN_SERVICES = ['ServiceRegistry'];

  const IMAGE_PATH = {
    READY: 'img/ready.png',
    NOT_READY: 'img/not_ready.png',
    DISABLED: 'img/_not_ready.png',
    CONNECTED: 'img/connected.png',
    UNCONNECTED: 'img/unconnected.png'
  };

  var connectedStatus = false;
  var unloadFunction = null;
  var loginModal = null;
  var _servicePanels = {};     // { serviceName: HTMLElement }
  var _activePanelName = null; // name of the currently visible cached panel
  var _classicPanels = {};     // { serviceName: true } while the cached panel is a classic panel shown instead of a component

  /**
   * Hides the active cached service panel, calls unloadFunction,
   * and removes any non-cached content (API explorer, placeholders).
   */
  function _deactivateCurrentPanel() {
    var contentDiv = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);
    if (typeof unloadFunction === 'function') {
      unloadFunction();
      unloadFunction = null;
    }
    if (_activePanelName && _servicePanels[_activePanelName]) {
      var panel = _servicePanels[_activePanelName];
      var shellType = panel.getAttribute('data-shell-type');
      if (shellType === 'wasm' || shellType === 'qml' || shellType === 'widget') {
        // Canvas-based panels: use visibility:hidden instead of display:none
        // to keep non-zero dimensions. display:none makes canvas 0x0 which
        // crashes the WASM requestAnimationFrame loop (createImageData fails).
        // Anchor the absolute panel to fill its parent so it never collapses.
        // The original height (calc-based) is preserved — never overwritten.
        contentDiv.style.position = 'relative';
        panel.style.visibility = 'hidden';
        panel.style.position = 'absolute';
        panel.style.pointerEvents = 'none';
        panel.style.left = '0';
        panel.style.top = '0';
        panel.style.width = '100%';
      } else {
        panel.style.display = 'none';
      }
    }
    _activePanelName = null;
    // Remove non-cached children (API explorer, placeholders)
    Array.from(contentDiv.children).forEach(function (child) {
      if (!child.hasAttribute('data-cached-service')) {
        contentDiv.removeChild(child);
      }
    });
  }

  /************************************************************
   *               Multi-Broker Helper Functions               *
   ************************************************************/

  function addConnection(brokerUrl, routingKey) {
    MM.connections[brokerUrl] = {
      brokerUrl: brokerUrl,
      routingKey: routingKey,
      services: {},
      realtimeSubscribed: false
    };
  }

  function removeConnection(brokerUrl) {
    delete MM.connections[brokerUrl];
    rebuildMergedServicesInfor();
  }

  function rebuildMergedServicesInfor() {
    var merged = {};
    serviceToBroker = {};
    Object.keys(MM.connections).forEach(function (key) {
      var conn = MM.connections[key];
      Object.keys(conn.services).forEach(function (svcName) {
        merged[svcName] = conn.services[svcName];
        serviceToBroker[svcName] = key;
      });
    });
    // Preserve ServiceAlias (local-only, not from any broker)
    if (MM.servicesInfor && MM.servicesInfor.ServiceAlias) {
      merged.ServiceAlias = MM.servicesInfor.ServiceAlias;
    }
    MM.servicesInfor = merged;
  }

  function getConnectionCount() {
    return Object.keys(MM.connections).length;
  }

  function sanitizeBrokerId(brokerUrl) {
    return brokerUrl.replace(/[^a-zA-Z0-9]/g, '-');
  }

  /**
   * Resolve the broker URL for a given routing key.
   */
  function resolveBrokerUrl(routingKey) {
    // Check serviceToBroker for any service with matching routing_key
    var keys = Object.keys(serviceToBroker);
    for (var i = 0; i < keys.length; i++) {
      var svcName = keys[i];
      if (MM.servicesInfor[svcName] && MM.servicesInfor[svcName].routing_key === routingKey) {
        var brokerKey = serviceToBroker[svcName];
        if (MM.connections[brokerKey]) return brokerKey;
      }
    }
    // Check connections for matching registry routingKey
    var connKeys = Object.keys(MM.connections);
    for (var j = 0; j < connKeys.length; j++) {
      if (MM.connections[connKeys[j]].routingKey === routingKey) {
        return connKeys[j];
      }
    }
    // Fall back to active broker
    if (MM.activeBrokerUrl && MM.connections[MM.activeBrokerUrl]) return MM.activeBrokerUrl;
    // Fall back to first connection
    if (connKeys.length > 0) return connKeys[0];
    return null;
  }

  /**
   * Resolve the broker URL for a given service name.
   */
  function resolveBrokerUrlForService(serviceName) {
    if (serviceToBroker[serviceName] && MM.connections[serviceToBroker[serviceName]]) {
      return serviceToBroker[serviceName];
    }
    if (MM.activeBrokerUrl && MM.connections[MM.activeBrokerUrl]) return MM.activeBrokerUrl;
    var connKeys = Object.keys(MM.connections);
    if (connKeys.length > 0) return connKeys[0];
    return null;
  }

  /************************************************************
   *               Connection Persistence                      *
   ************************************************************/

  // Connections live in localStorage so they survive an application
  // restart, not just a page refresh: sessionStorage is wiped when the
  // renderer process ends, which is exactly what closing the app does.
  // (Consul URLs further down already use localStorage for this reason.)
  var CONNECTIONS_STORAGE_KEY = 'mm_connections';

  function persistConnections() {
    try {
      var data = Object.keys(MM.connections).map(function (key) {
        var conn = MM.connections[key];
        return { brokerUrl: conn.brokerUrl, routingKey: conn.routingKey };
      });
      localStorage.setItem(CONNECTIONS_STORAGE_KEY, JSON.stringify(data));
    } catch (e) { /* storage unavailable */ }
  }

  function _isValidSavedConnection(entry) {
    return !!(entry && typeof entry.brokerUrl === 'string' && entry.brokerUrl.trim());
  }

  function loadPersistedConnections() {
    try {
      var raw = localStorage.getItem(CONNECTIONS_STORAGE_KEY);
      if (raw) {
        var parsed = JSON.parse(raw);
        // Drop malformed entries instead of aborting the whole restore.
        return Array.isArray(parsed) ? parsed.filter(_isValidSavedConnection) : [];
      }

      // Migration: earlier builds saved to sessionStorage. Move whatever
      // is still there across once, then stop looking at it.
      var legacy = sessionStorage.getItem(CONNECTIONS_STORAGE_KEY);
      if (legacy) {
        var migrated = JSON.parse(legacy);
        migrated = Array.isArray(migrated) ? migrated.filter(_isValidSavedConnection) : [];
        localStorage.setItem(CONNECTIONS_STORAGE_KEY, JSON.stringify(migrated));
        sessionStorage.removeItem(CONNECTIONS_STORAGE_KEY);
        return migrated;
      }
      var savedBrokerUrl = sessionStorage.getItem('mm_brokerUrl');
      var savedRoutingKey = sessionStorage.getItem('mm_routingKey');
      if (savedBrokerUrl) {
        return [{ brokerUrl: savedBrokerUrl, routingKey: savedRoutingKey || '' }];
      }
    } catch (e) { /* storage unavailable or corrupt -- start clean */ }
    return [];
  }

  function clearPersistedConnections() {
    try {
      localStorage.removeItem(CONNECTIONS_STORAGE_KEY);
      sessionStorage.removeItem(CONNECTIONS_STORAGE_KEY);
      sessionStorage.removeItem('mm_brokerUrl');
      sessionStorage.removeItem('mm_routingKey');
    } catch (e) { /* storage unavailable */ }
  }

  /************************************************************
   *                    Toast Notifications                   *
   ************************************************************/

  /**
   * Show a Bootstrap toast notification.
   *
   * @param {string} title - Toast title.
   * @param {string} message - Toast message body.
   * @param {string} [type='info'] - Type: 'success', 'warning', 'danger', 'info'.
   */
  function showToast(title, message, type) {
    type = type || 'info';
    var bgClass = 'bg-' + type;
    var container = document.getElementById('toastContainer');

    var toastEl = document.createElement('div');
    toastEl.className = 'toast align-items-center text-white ' + bgClass + ' border-0';
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML =
      '<div class="d-flex">' +
        '<div class="toast-body"><strong>' + _escapeHtml(title) + '</strong><br>' + _escapeHtml(message) + '</div>' +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
      '</div>';

    container.appendChild(toastEl);
    var toast = new bootstrap.Toast(toastEl, { autohide: true, delay: 4000 });
    toast.show();

    toastEl.addEventListener('hidden.bs.toast', function () {
      toastEl.remove();
    });
  }

  /**
   * Show a warning dialog (toast-based replacement for Electron dialog).
   *
   * @param {string} message - Warning message.
   */
  function showWarningDialog(message) {
    showToast('Warning', message, 'warning');
  }

  /**
   * Show a confirmation modal (Bootstrap-based replacement for native confirm()).
   * Native confirm() causes an Electron focus bug on Windows where all inputs
   * become unresponsive after the dialog is dismissed.
   *
   * @param {string} message - The confirmation message to display.
   * @param {Function} onConfirm - Callback invoked when the user clicks Confirm.
   */
  function showConfirm(message, onConfirm) {
    var modalEl = document.getElementById('confirmModal');
    var bodyEl = document.getElementById('confirmModalBody');
    var okBtn = document.getElementById('confirmModalOkBtn');
    bodyEl.textContent = message;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    // Clone-replace OK button to remove old listeners
    var newOk = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOk, okBtn);
    newOk.id = 'confirmModalOkBtn';

    newOk.onclick = function () {
      modal.hide();
      onConfirm();
    };

    modal.show();
  }

  /************************************************************
   *               Functions: GUI Element Handling             *
   ************************************************************/

  /**
   * Activates an HTML element by adding the 'active' CSS class to it.
   *
   * @param {HTMLElement} element - The HTML element to be activated.
   */
  function activateItem(element) {
    var buttons = document.querySelectorAll('.list-group-item');
    buttons.forEach(function (btn) { btn.classList.remove('active'); });
    element.classList.add('active');
  }

  /**
   * Removes all service items from the GUI list.
   */
  function clearServiceList() {
    var accordion = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    while (accordion.firstChild) {
      accordion.removeChild(accordion.firstChild);
    }
  }

  /**
   * Removes service content GUI.
   */
  function clearServiceContent() {
    var contentService = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);
    while (contentService.firstChild) {
      contentService.removeChild(contentService.firstChild);
    }
    _servicePanels = {};
    _activePanelName = null;
  }

  /**
   * Update navbar connection badge based on connection count.
   */
  function updateConnectionBadge() {
    var dot = document.getElementById('connectionDot');
    var label = document.getElementById('connectionLabel');
    var count = getConnectionCount();

    if (count === 0) {
      dot.classList.remove('connected');
      label.textContent = 'Disconnected';
      connectedStatus = false;
    } else if (count === 1) {
      dot.classList.add('connected');
      label.textContent = 'Connected';
      connectedStatus = true;
    } else {
      dot.classList.add('connected');
      label.textContent = count + ' brokers';
      connectedStatus = true;
    }

    renderBrokerChips();
  }

  /**
   * Render broker chips in the navbar showing each connected broker.
   */
  function renderBrokerChips() {
    var container = document.getElementById('connectedBrokers');
    container.innerHTML = '';

    Object.keys(MM.connections).forEach(function (brokerUrl) {
      var chip = document.createElement('span');
      chip.classList.add('broker-chip');

      var chipLabel = document.createElement('span');
      chipLabel.textContent = brokerUrl;

      var closeBtn = document.createElement('button');
      closeBtn.classList.add('broker-chip-close');
      closeBtn.title = 'Disconnect ' + brokerUrl;
      closeBtn.innerHTML = '<i class="bi bi-x"></i>';
      closeBtn.onclick = function (e) {
        e.stopPropagation();
        confirmDisconnectBroker(brokerUrl);
      };

      chip.appendChild(chipLabel);
      chip.appendChild(closeBtn);
      container.appendChild(chip);
    });
  }

  /**
   * Show a confirm dialog before disconnecting a broker.
   *
   * @param {string} brokerUrl - The broker address to disconnect.
   */
  function confirmDisconnectBroker(brokerUrl) {
    MM.showConfirm('Disconnect from broker ' + brokerUrl + '?', function () {
      disconnectBroker(brokerUrl);
    });
  }

  /**
   * Change the Connect button state when connection status changes.
   * Kept for backward compatibility — wraps updateConnectionBadge().
   *
   * @param {string} status - The connection status.
   */
  function changeConnectButtonState(status) {
    if (status === CONNECTION_STATUS.CONNECTED || status === CONNECTION_STATUS.DISCONNECTED) {
      updateConnectionBadge();
    }
  }

  /**
   * Activates the GUI list item element and loads the content for the service.
   *
   * @param {HTMLElement} element - The HTML element representing the service.
   * @param {string} serviceName - The name of the service to load.
   */
  function activateItemAndLoadContent(element, serviceName) {
    activateItem(element);

    // Set active broker context from clicked element
    var brokerUrl = element.getAttribute('data-broker-url');
    if (brokerUrl && MM.connections[brokerUrl]) {
      MM.activeBrokerUrl = brokerUrl;
      MM.brokerUrl = brokerUrl;
      MM.routingKey = MM.connections[brokerUrl].routingKey;
      MM.serviceClient.setBrokerUrl(brokerUrl);
    }

    var serviceInfo = MM.servicesInfor[serviceName];
    _selectedService = { name: serviceName, infoKey: serviceName, consul: null, info: serviceInfo };
    if (_devMode) _renderInspector(_selectedService);

    if (serviceInfo.gui_support === true) {
      var callBackFunc = function () {
        loadServiceContent(serviceName, DIV_NAME.SERVICE_CONTENT_DIV);
      };
      checkAndGetTheServiceGUIResources(serviceName, callBackFunc);
    } else {
      // Runtime view: what the service is and whether it is up. The
      // method explorer is a developer tool (Developer Tools -> API Explorer).
      _showServiceOverview(_selectedService);
    }
  }

  /**
   * Loads GUI resources of a service into a dynamic div.
   *
   * @param {string} serviceName - The name of the service for loading GUI content.
   * @param {string} dynamicContentName - The name of the div where content will be loaded.
   * @param {string} callbackName - Optional callback function name after loading.
   */
  function loadServiceContent(serviceName, dynamicContentName, callbackName) {
    callbackName = callbackName || '';
    var contentDiv = document.getElementById(dynamicContentName);

    // --- Cache hit: show existing panel without re-running loadFunction ---
    if (_servicePanels[serviceName]) {
      _deactivateCurrentPanel();
      var panel = _servicePanels[serviceName];
      var shellType = panel.getAttribute('data-shell-type');
      // Restore visibility — undo the absolute-positioning hide
      panel.style.display = '';
      panel.style.visibility = '';
      panel.style.position = '';
      panel.style.pointerEvents = '';
      panel.style.left = '';
      panel.style.top = '';
      panel.style.width = '';
      _activePanelName = serviceName;
      // Restore unloadFunction reference
      var unloadName = 'unload' + serviceName;
      unloadFunction = window[unloadName] || null;

      // Re-register the correct shell's response callbacks so the active
      // shell receives service responses (not the previously active shell).
      if (shellType === 'qml' && window.QtShellManager) {
        window.QtShellManager.activateBridge();
      } else if (shellType === 'widget' && window.WidgetShellManager) {
        window.WidgetShellManager.activateBridge();
      }

      if (callbackName !== '' && typeof window[callbackName] === 'function') {
        window[callbackName]();
      }
      return;
    }

    // --- Cache miss: multi-tier GUI detection ---
    var folderPath = SERVICES_GUI_FOLDER + '/' + serviceName + MM.servicesInfor[serviceName].version;

    _loadServiceGUIMultiTier(serviceName, folderPath, contentDiv, callbackName);
  }

  /**
   * Multi-tier GUI loading: schema → QML/Widget Shell → Qt WASM → HTML → API Explorer.
   *
   * Tier 1a: gui_schema.json "renderer":"qt"      → QtShellManager (QML Shell)
   * Tier 1b: gui_schema.json "renderer":"widget"   → WidgetShellManager (Widget Shell)
   * Tier 1c: gui_schema.json (no renderer)         → SchemaRenderer (Bootstrap)
   * Tier 1d: *.qml file in service folder           → QtShellManager (QML Shell)
   * Tier 1e: *.ui file in service folder            → WidgetShellManager (Widget Shell)
   * Tier 2:  .wasm file                             → QtWasmLoader (per-service WASM)
   * Tier 3:  .html file                             → Custom HTML
   * Tier 4:  Fallback                               → API Explorer
   */
  function _loadServiceGUIMultiTier(serviceName, folderPath, contentDiv, callbackName) {
    var schemaUrl = folderPath + '/gui_schema.json';
    var htmlUrl = folderPath + '/' + serviceName + '.html';

    // Tier 1: Try gui_schema.json
    fetch(schemaUrl)
      .then(function (resp) {
        if (!resp.ok) throw new Error('no schema');
        return resp.json();
      })
      .then(function (schema) {
        // Tier 1a: Schema with renderer:"qt" → load via QML Shell
        if (schema.renderer === 'qt' && window.QtShellManager) {
          var qmlFile = schema.qml_file || 'ServiceUI.qml';
          var qmlUrl = folderPath + '/' + qmlFile;
          _loadQmlShellGUI(serviceName, qmlUrl, contentDiv, callbackName);
          return;
        }

        // Tier 1b: Schema with renderer:"widget" → load via Widget Shell
        if (schema.renderer === 'widget' && window.WidgetShellManager) {
          var uiFile = schema.ui_file || 'ServiceUI.ui';
          var uiUrl = folderPath + '/' + uiFile;
          _loadWidgetShellGUI(serviceName, uiUrl, contentDiv, callbackName);
          return;
        }

        // Tier 1c: Schema without renderer → render via SchemaRenderer (Bootstrap)
        _deactivateCurrentPanel();
        var wrapper = document.createElement('div');
        wrapper.setAttribute('data-cached-service', serviceName);
        contentDiv.appendChild(wrapper);
        _servicePanels[serviceName] = wrapper;
        _activePanelName = serviceName;
        window.SchemaRenderer.render(schema, wrapper, serviceName);
        // Set unload to cleanup live timers
        window['unload' + serviceName] = function () {
          window.SchemaRenderer.cleanup();
        };
        unloadFunction = window['unload' + serviceName];
        if (callbackName && typeof window[callbackName] === 'function') {
          window[callbackName]();
        }
      })
      .catch(function () {
        // Tier 1d: Check for .qml files → QML Shell (only if shell runtime is loaded)
        // Tier 1e: Check for .ui files → Widget Shell
        var qmlPromise = window.QtShellManager
          ? window.QtShellManager.detect(folderPath)
          : Promise.resolve({ hasQml: false, qmlFile: null });
        var uiPromise = window.WidgetShellManager
          ? window.WidgetShellManager.detect(folderPath)
          : Promise.resolve({ hasUi: false, uiFile: null });

        Promise.all([qmlPromise, uiPromise]).then(function (results) {
          var qmlResult = results[0];
          var uiResult = results[1];

          if (qmlResult.hasQml) {
            var qmlUrl = folderPath + '/' + qmlResult.qmlFile;
            _loadQmlShellGUI(serviceName, qmlUrl, contentDiv, callbackName,
                             folderPath, htmlUrl);
          } else if (uiResult.hasUi) {
            var uiUrl = folderPath + '/' + uiResult.uiFile;
            _loadWidgetShellGUI(serviceName, uiUrl, contentDiv, callbackName,
                                folderPath, htmlUrl);
          } else {
            _tryQtWasmOrHtml(serviceName, folderPath, htmlUrl, contentDiv, callbackName);
          }
        });
      });
  }

  /**
   * Load a service GUI via the shared QML Shell.
   * Falls through to WASM/HTML tier on failure when folderPath/htmlUrl provided.
   */
  function _loadQmlShellGUI(serviceName, qmlUrl, contentDiv, callbackName,
                             folderPath, htmlUrl) {
    _deactivateCurrentPanel();
    var wrapper = document.createElement('div');
    wrapper.setAttribute('data-cached-service', serviceName);
    wrapper.style.cssText = 'height:calc(100vh - var(--navbar-height) - var(--ribbon-height) - 3rem);';
    contentDiv.appendChild(wrapper);
    _servicePanels[serviceName] = wrapper;
    _activePanelName = serviceName;

    wrapper.setAttribute('data-shell-type', 'qml');

    window.QtShellManager.loadQml(qmlUrl, wrapper, serviceName)
      .catch(function (err) {
        console.warn('QtShellManager failed for', serviceName, err);
        // Remove the failed panel and fall through to next tier.
        if (folderPath) {
          wrapper.remove();
          delete _servicePanels[serviceName];
          _activePanelName = null;
          _tryQtWasmOrHtml(serviceName, folderPath, htmlUrl, contentDiv, callbackName);
        }
      });

    // No-op: panel cache hides/shows via display:none.
    window['unload' + serviceName] = function () {};
    unloadFunction = window['unload' + serviceName];
    if (callbackName && typeof window[callbackName] === 'function') {
      window[callbackName]();
    }
  }

  /**
   * Load a service GUI via the shared Widget Shell.
   * Falls through to WASM/HTML tier on failure when folderPath/htmlUrl provided.
   */
  function _loadWidgetShellGUI(serviceName, uiUrl, contentDiv, callbackName,
                                folderPath, htmlUrl) {
    _deactivateCurrentPanel();
    var wrapper = document.createElement('div');
    wrapper.setAttribute('data-cached-service', serviceName);
    wrapper.style.cssText = 'height:calc(100vh - var(--navbar-height) - var(--ribbon-height) - 3rem);';
    contentDiv.appendChild(wrapper);
    _servicePanels[serviceName] = wrapper;
    _activePanelName = serviceName;

    wrapper.setAttribute('data-shell-type', 'widget');

    window.WidgetShellManager.loadWidget(uiUrl, wrapper, serviceName)
      .catch(function (err) {
        console.warn('WidgetShellManager failed for', serviceName, err);
        // Remove the failed panel and fall through to next tier.
        if (folderPath) {
          wrapper.remove();
          delete _servicePanels[serviceName];
          _activePanelName = null;
          _tryQtWasmOrHtml(serviceName, folderPath, htmlUrl, contentDiv, callbackName);
        }
      });

    // No-op: panel cache hides/shows via display:none.
    window['unload' + serviceName] = function () {};
    unloadFunction = window['unload' + serviceName];
    if (callbackName && typeof window[callbackName] === 'function') {
      window[callbackName]();
    }
  }

  /**
   * Tier 2/3 fallback: try per-service Qt WASM, then custom HTML.
   */
  function _tryQtWasmOrHtml(serviceName, folderPath, htmlUrl, contentDiv, callbackName) {
    if (window.QtWasmLoader) {
      window.QtWasmLoader.detect(folderPath)
        .then(function (hasWasm) {
          if (hasWasm) {
            _deactivateCurrentPanel();
            var wrapper = document.createElement('div');
            wrapper.setAttribute('data-cached-service', serviceName);
            wrapper.setAttribute('data-shell-type', 'wasm');
            wrapper.style.cssText = 'height:calc(100vh - var(--navbar-height) - var(--ribbon-height) - 3rem);';
            contentDiv.appendChild(wrapper);
            _servicePanels[serviceName] = wrapper;
            _activePanelName = serviceName;

            window.QtWasmLoader.load(folderPath, wrapper, serviceName)
              .catch(function (err) {
                console.warn('QtWasmLoader failed for', serviceName, err);
                MM.showToast('Qt WASM', 'Failed to load: ' + err.message, 'warning');
              });

            // No-op: panel cache hides/shows via display:none.
            // QtWasmLoader.unload() destroys the WASM instance which
            // cannot be re-created on cache-hit, so only call it on
            // full teardown (e.g., disconnect).
            window['unload' + serviceName] = function () {};
            unloadFunction = window['unload' + serviceName];
            if (callbackName && typeof window[callbackName] === 'function') {
              window[callbackName]();
            }
          } else {
            // Tier 3: Try custom HTML
            _fetchAndRenderServiceGUI(serviceName, htmlUrl, contentDiv, callbackName);
          }
        });
    } else {
      // Tier 3: Try custom HTML (QtWasmLoader not loaded)
      _fetchAndRenderServiceGUI(serviceName, htmlUrl, contentDiv, callbackName);
    }
  }

  /**
   * Fetch a service GUI HTML file and render it in the content panel.
   * Also loads the companion .js script.
   */
  function _fetchAndRenderServiceGUI(serviceName, htmlUrl, contentDiv, callbackName) {
    fetch(htmlUrl)
      .then(function (response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return response.text();
      })
      .then(function (htmlContent) {
        _deactivateCurrentPanel();

        // Create a wrapper div for the cached panel
        var wrapper = document.createElement('div');
        wrapper.setAttribute('data-cached-service', serviceName);
        wrapper.innerHTML = htmlContent;
        contentDiv.appendChild(wrapper);
        _servicePanels[serviceName] = wrapper;
        _activePanelName = serviceName;

        var scriptSrc = htmlUrl.replace('.html', '.js');
        if (!isScriptAlreadyAdded(scriptSrc)) {
          var script = document.createElement('script');
          script.src = scriptSrc;
          script.type = 'text/javascript';
          document.head.appendChild(script);

          script.onload = function () {
            if (callbackName !== '' && typeof window[callbackName] === 'function') {
              window[callbackName]();
            }
            var unloadName = 'unload' + serviceName;
            unloadFunction = window[unloadName] || null;
          };
        } else {
          console.log('Script \'' + scriptSrc + '\' has already been loaded.');
          var loadFunctionName = 'load' + serviceName;
          var loadFunction = window[loadFunctionName];
          if (typeof loadFunction === 'function') {
            loadFunction();
          }
          if (callbackName !== '' && typeof window[callbackName] === 'function') {
            window[callbackName]();
          }
          var unloadName = 'unload' + serviceName;
          unloadFunction = window[unloadName] || null;
        }
      })
      .catch(function (error) {
        // <ServiceName>.html not found — try discovering the actual .html file
        var folderPath = htmlUrl.substring(0, htmlUrl.lastIndexOf('/'));
        MM.listServiceFiles(folderPath)
          .then(function (files) {
            var htmlFile = files.find(function (f) { return f.endsWith('.html'); });
            if (htmlFile) {
              var altUrl = folderPath + '/' + htmlFile;
              console.log('Retrying with discovered file:', altUrl);
              _fetchAndRenderServiceGUI(serviceName, altUrl, contentDiv, callbackName);
            } else {
              console.warn('No .html file found in', folderPath, '- showing API explorer');
              showToast('Service GUI',
                'No GUI files were found for ' + serviceName + ' - showing the API view instead.',
                'warning');
              showServiceAPIExplorer(serviceName);
            }
          })
          .catch(function (discoverError) {
            console.warn('Cannot discover GUI files for', serviceName, '- showing API explorer');
            showToast('Service GUI',
              'The GUI for ' + serviceName + ' could not be loaded (' +
              ((discoverError && discoverError.message) || error.message || 'unknown error') +
              ') - showing the API view instead.',
              'warning');
            showServiceAPIExplorer(serviceName);
          });
      });
  }

  function normalizePath(p) {
    p = p.replace(/\\/g, '/');
    if (!p.startsWith('/') && !p.match(/^\w+:/)) {
      var baseURL = new URL(window.location.href);
      p = new URL(p, baseURL).href;
    }
    if (p.match(/^\w:/)) {
      p = 'file:///' + p;
    }
    return p;
  }

  function isScriptAlreadyAdded(scriptPath) {
    var absoluteScriptPath = normalizePath(scriptPath);
    return Array.from(document.head.querySelectorAll('script'))
      .some(function (script) { return normalizePath(script.src) === absoluteScriptPath; });
  }

  /**
   * Loads external content from an HTML file into a specified div.
   *
   * @param {string} externalContentFile - Path to the external HTML file.
   * @param {string} dynamicContentName - The name of the div for external content.
   * @param {string} callbackName - Optional callback function name after loading.
   */
  function loadContent(externalContentFile, dynamicContentName, callbackName) {
    callbackName = callbackName || '';
    console.log('Loading service content...');
    var dynamicContentDiv = document.getElementById(dynamicContentName);

    if (externalContentFile) {
      fetch(externalContentFile)
        .then(function (response) { return response.text(); })
        .then(function (htmlContent) {
          if (dynamicContentName === 'serviceContent' && typeof unloadFunction === 'function') {
            unloadFunction();
          }
          dynamicContentDiv.innerHTML = htmlContent;

          var scriptSrc = externalContentFile.replace('.html', '.js');
          if (!isScriptAlreadyAdded(scriptSrc)) {
            var script = document.createElement('script');
            script.src = scriptSrc;
            script.type = 'text/javascript';
            document.head.appendChild(script);

            script.onload = function () {
              if (callbackName !== '' && typeof window[callbackName] === 'function') {
                window[callbackName]();
              }
              if (dynamicContentName === 'serviceContent') {
                var filename = externalContentFile.split(/[\\/]/).pop().replace(/\..+$/, '');
                var functionName = 'unload' + filename;
                unloadFunction = window[functionName];
              }
            };
          } else {
            console.log('Script \'' + scriptSrc + '\' has already been loaded.');
            var filename = externalContentFile.split(/[\\/]/).pop().replace(/\..+$/, '');
            var loadFunctionName = 'load' + filename;
            var loadFunction = window[loadFunctionName];
            if (typeof loadFunction === 'function') {
              loadFunction();
            }
            if (callbackName !== '' && typeof window[callbackName] === 'function') {
              window[callbackName]();
            }
            if (dynamicContentName === 'serviceContent') {
              var unloadFunctionName = 'unload' + filename;
              unloadFunction = window[unloadFunctionName];
            }
          }
        })
        .catch(function (error) {
          console.error('Error loading external content:', error);
        });
    }
  }

  /************************************************************
   *              Broker Section DOM Management                *
   ************************************************************/

  /**
   * Create or retrieve the broker section wrapper for a given broker URL.
   *
   * @param {string} brokerUrl - The broker address (host:port).
   * @returns {HTMLElement} The broker section element.
   */
  function createBrokerSection(brokerUrl) {
    var servicesList = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    var brokerId = sanitizeBrokerId(brokerUrl);
    var existing = servicesList.querySelector('.broker-section[data-broker-url="' + brokerUrl + '"]');
    if (existing) return existing;

    var section = document.createElement('div');
    section.classList.add('broker-section');
    section.setAttribute('data-broker-url', brokerUrl);

    // Header (hidden in single-broker mode via CSS)
    var header = document.createElement('div');
    header.classList.add('broker-header');

    // Per-source connection state. A source that cannot be reached stays
    // in the list marked offline rather than vanishing, so the user can
    // see which machine is the problem and retry or remove it.
    var statusDot = document.createElement('span');
    statusDot.classList.add('broker-status');
    statusDot.title = 'Connecting…';

    var labelSpan = document.createElement('span');
    labelSpan.classList.add('broker-label');
    labelSpan.textContent = brokerUrl;

    var badge = document.createElement('span');
    badge.classList.add('broker-badge');
    badge.textContent = '0';

    var retryBtn = document.createElement('button');
    retryBtn.classList.add('broker-retry-btn');
    retryBtn.title = 'Retry connection';
    retryBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
    retryBtn.onclick = function (e) {
      e.stopPropagation();
      retryBroker(brokerUrl);
    };

    var disconnectBtn = document.createElement('button');
    disconnectBtn.classList.add('broker-disconnect-btn');
    disconnectBtn.title = 'Disconnect this broker';
    disconnectBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    disconnectBtn.onclick = function (e) {
      e.stopPropagation();
      confirmDisconnectBroker(brokerUrl);
    };

    header.appendChild(statusDot);
    header.appendChild(labelSpan);
    header.appendChild(badge);
    header.appendChild(retryBtn);
    header.appendChild(disconnectBtn);

    var accordion = document.createElement('div');
    accordion.classList.add('broker-accordion');

    section.appendChild(header);
    section.appendChild(accordion);
    servicesList.appendChild(section);

    return section;
  }

  /**
   * Update the service count badge on a broker header.
   *
   * @param {string} brokerUrl - The broker address.
   */
  function updateBrokerBadge(brokerUrl) {
    var servicesList = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    var section = servicesList.querySelector('.broker-section[data-broker-url="' + brokerUrl + '"]');
    if (!section) return;
    var items = section.querySelectorAll('.list-group-item[data-service-name]');
    var badge = section.querySelector('.broker-badge');
    if (badge) badge.textContent = items.length;
  }

  function _getBrokerSection(brokerUrl) {
    var servicesList = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    return servicesList.querySelector('.broker-section[data-broker-url="' + brokerUrl + '"]');
  }

  /**
   * Show a source's connection state on its header.
   *
   * @param {string} brokerUrl - The broker address.
   * @param {string} state - 'connecting' | 'online' | 'offline'.
   * @param {string} [detail] - Tooltip text (defaults per state).
   */
  function setBrokerStatus(brokerUrl, state, detail) {
    var section = _getBrokerSection(brokerUrl);
    if (!section) return;
    section.classList.remove('broker-connecting', 'broker-online', 'broker-offline');
    section.classList.add('broker-' + state);
    var dot = section.querySelector('.broker-status');
    if (dot) {
      dot.title = detail || {
        connecting: 'Connecting…',
        online: 'Connected',
        offline: 'Unreachable'
      }[state] || state;
    }
  }

  /**
   * Mark a source unreachable without removing it: its services are
   * greyed out, the header turns red and offers a retry, and the saved
   * connection is kept so it is tried again on the next start.
   *
   * @param {string} brokerUrl - The broker address.
   * @param {string} reason - Why it went offline (shown as tooltip).
   */
  function markBrokerOffline(brokerUrl, reason) {
    var conn = MM.connections[brokerUrl];
    if (conn) {
      // Force a fresh subscription when the retry succeeds.
      conn.realtimeSubscribed = false;
    }
    var section = _getBrokerSection(brokerUrl);
    if (section) {
      var activeItem = section.querySelector('.list-group-item.active');
      if (activeItem) {
        activeItem.classList.remove('active');
        _deactivateCurrentPanel();
        clearServiceContent();
      }
      section.querySelectorAll('.list-group-item[data-service-name]').forEach(function (listItem) {
        listItem.classList.add('service-disabled');
        var icon = listItem.querySelector('.icon');
        if (icon) icon.src = IMAGE_PATH.DISABLED;
      });
    }
    setBrokerStatus(brokerUrl, 'offline', reason);
    updateBrokerHeaders();
  }

  /**
   * Re-attempt a source that is marked offline.
   *
   * @param {string} brokerUrl - The broker address.
   */
  function retryBroker(brokerUrl) {
    var conn = MM.connections[brokerUrl];
    if (!conn) return;
    // Rebuild the section from scratch; createAccordionItems appends and
    // would otherwise duplicate the greyed-out entries.
    var section = _getBrokerSection(brokerUrl);
    if (section) {
      var accordion = section.querySelector('.broker-accordion');
      if (accordion) accordion.innerHTML = '';
    }
    conn.services = {};
    rebuildMergedServicesInfor();
    addAliasServiceForBroker(brokerUrl, conn.routingKey);
    requestServicesInforForBroker(brokerUrl, { restored: true });
  }

  /**
   * Toggle multi-broker class for progressive disclosure.
   * When only one broker is connected, broker headers are hidden.
   */
  function updateBrokerHeaders() {
    var servicesList = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    if (getConnectionCount() > 1) {
      servicesList.classList.add('multi-broker');
    } else {
      servicesList.classList.remove('multi-broker');
    }
  }

  /**
   * Create a single service list-item button for the sidebar.
   *
   * @param {object} item - { label, iconSrc, serviceName, downloadable }
   * @param {string} [brokerUrl] - The broker URL to tag on the element.
   * @returns {HTMLElement}
   */
  function _createServiceListItem(item, brokerUrl) {
    var listItem = document.createElement('button');
    listItem.type = 'button';
    listItem.classList.add('list-group-item', 'list-group-item-action');
    listItem.setAttribute('aria-current', 'true');
    listItem.setAttribute('data-service-name', item.serviceName);
    if (brokerUrl) {
      listItem.setAttribute('data-broker-url', brokerUrl);
    }

    listItem.onclick = function () {
      if (listItem.classList.contains('service-disabled')) {
        return;
      }
      activateItemAndLoadContent(listItem, item.serviceName);
    };

    var icon = document.createElement('img');
    icon.src = item.iconSrc;
    icon.alt = 'Icon';
    icon.classList.add('icon');

    var label = document.createTextNode(item.label);

    listItem.appendChild(icon);
    listItem.appendChild(label);

    // A service without a GUI is still listed -- users need the full
    // picture of what is running -- but says so up front instead of
    // silently opening the API view on click.
    if (!item.guiSupport) {
      var noGuiBadge = document.createElement('span');
      noGuiBadge.classList.add('no-gui-badge');
      noGuiBadge.textContent = 'No GUI';
      noGuiBadge.title = 'No GUI available - selecting this service shows its runtime info';
      listItem.appendChild(noGuiBadge);
    }

    // No per-row developer buttons (code examples, download): those are
    // reachable from Developer Tools for the selected service, keeping the
    // sidebar an operator's list.
    return listItem;
  }

  /**
   * Dynamically generates accordion items for services in the sidebar.
   * Supports multi-broker by appending to the correct broker section.
   *
   * @param {Array} data - Structured information for multiple services.
   * @param {string} [brokerUrl] - The broker URL to scope items to.
   */
  function createAccordionItems(data, brokerUrl) {
    var targetElement;

    if (brokerUrl) {
      var section = createBrokerSection(brokerUrl);
      targetElement = section.querySelector('.broker-accordion');
    } else {
      targetElement = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    }

    var prefix = brokerUrl ? sanitizeBrokerId(brokerUrl) + '_' : '';

    data.forEach(function (section) {
      var contentId = prefix + section.contentId;

      var accordionItem = document.createElement('div');
      accordionItem.classList.add('accordion-item');

      var accordionHeader = document.createElement('h2');
      accordionHeader.classList.add('accordion-header');

      var accordionButton = document.createElement('button');
      accordionButton.classList.add('accordion-button');
      accordionButton.type = 'button';
      accordionButton.dataset.bsToggle = 'collapse';
      accordionButton.dataset.bsTarget = '#' + contentId;
      accordionButton.setAttribute('aria-expanded', 'true');
      accordionButton.textContent = section.title;

      accordionHeader.appendChild(accordionButton);

      var accordionCollapse = document.createElement('div');
      accordionCollapse.id = contentId;
      accordionCollapse.classList.add('accordion-collapse', 'collapse', 'show');

      var accordionBody = document.createElement('div');
      accordionBody.classList.add('accordion-body');

      var listGroup = document.createElement('div');
      listGroup.classList.add('list-group');

      section.items.forEach(function (item) {
        listGroup.appendChild(_createServiceListItem(item, brokerUrl));
      });

      accordionBody.appendChild(listGroup);
      accordionCollapse.appendChild(accordionBody);

      accordionItem.appendChild(accordionHeader);
      accordionItem.appendChild(accordionCollapse);

      targetElement.appendChild(accordionItem);
    });

    if (brokerUrl) {
      updateBrokerBadge(brokerUrl);
    }
  }

  /************************************************************
   *             Service API Explorer (non-GUI services)      *
   ************************************************************/

  /**
   * Renders a generic API explorer for services without custom GUI.
   *
   * @param {string} serviceName - The service name key in MM.servicesInfor.
   */
  function showServiceAPIExplorer(serviceName) {
    var serviceInfo = MM.servicesInfor[serviceName];
    var contentDiv = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);

    _deactivateCurrentPanel();

    var methods = serviceInfo.methods || [];
    var methodsInfo = serviceInfo.methods_info || {};

    // If SchemaAutoGen + SchemaRenderer are available and methods_info has data,
    // generate a schema-driven UI instead of the raw API explorer.
    if (window.SchemaAutoGen && window.SchemaRenderer &&
        methods.length > 0 && Object.keys(methodsInfo).length > 0) {
      var schema = window.SchemaAutoGen.fromMethodsInfo(serviceName, serviceInfo);
      var wrapper = document.createElement('div');
      wrapper.setAttribute('data-cached-service', serviceName);
      contentDiv.appendChild(wrapper);
      _servicePanels[serviceName] = wrapper;
      _activePanelName = serviceName;
      window.SchemaRenderer.render(schema, wrapper, serviceName);
      window['unload' + serviceName] = function () {
        window.SchemaRenderer.cleanup();
      };
      unloadFunction = window['unload' + serviceName];
      return;
    }

    // Fallback: manual API Explorer for services with no metadata

    // Build method options
    var methodOptions = '<option value="" disabled selected>-- Select a method --</option>';
    methods.forEach(function (m) {
      methodOptions += '<option value="' + _escapeHtml(m) + '">' + _escapeHtml(m) + '</option>';
    });

    var wrapper = document.createElement('div');
    wrapper.innerHTML =
      '<div class="card api-explorer-card">' +
        '<div class="card-header d-flex align-items-center justify-content-between">' +
          '<div>' +
            '<h5 class="mb-0">' + _escapeHtml(serviceInfo.name || serviceName) + ' ' +
              '<span class="badge bg-secondary">' + _escapeHtml(serviceInfo.version || '') + '</span>' +
            '</h5>' +
            '<small class="text-muted">' + _escapeHtml(serviceInfo.description || serviceInfo.shortdesc || '') + '</small>' +
          '</div>' +
        '</div>' +
        '<div class="card-body">' +

          // Method selector
          '<div class="mb-3">' +
            '<label for="apiMethodSelect" class="form-label fw-semibold">Method</label>' +
            '<select class="form-select" id="apiMethodSelect">' +
              methodOptions +
            '</select>' +
          '</div>' +

          // Arguments area (populated dynamically)
          '<div id="apiArgsContainer" class="mb-3" style="display:none;">' +
            '<label class="form-label fw-semibold">Arguments</label>' +
            '<div id="apiArgsFields"></div>' +
          '</div>' +

          // Execute button
          '<button class="btn btn-primary" id="apiExecuteBtn" disabled>' +
            '<i class="bi bi-play-fill me-1"></i>Execute' +
          '</button>' +

          // Response area
          '<div id="apiResponseContainer" class="mt-4" style="display:none;">' +
            '<label class="form-label fw-semibold">Response</label>' +
            '<div class="d-flex align-items-center mb-2">' +
              '<span class="badge me-2" id="apiResultBadge">-</span>' +
              '<small class="text-muted" id="apiResponseTime"></small>' +
            '</div>' +
            '<pre class="api-response-pre" id="apiResponseData"></pre>' +
          '</div>' +

        '</div>' +
      '</div>';

    contentDiv.appendChild(wrapper);

    // Wire events
    var methodSelect = document.getElementById('apiMethodSelect');
    var executeBtn = document.getElementById('apiExecuteBtn');

    methodSelect.addEventListener('change', function () {
      _renderArgsFields(serviceName, methodSelect.value);
      executeBtn.disabled = false;
    });

    executeBtn.addEventListener('click', function () {
      _executeAPIMethod(serviceName, methodSelect.value);
    });
  }

  /**
   * Render argument input fields for a selected method.
   */
  function _renderArgsFields(serviceName, methodName) {
    var serviceInfo = MM.servicesInfor[serviceName];
    var methodsInfo = serviceInfo.methods_info || {};
    var argsContainer = document.getElementById('apiArgsContainer');
    var argsFields = document.getElementById('apiArgsFields');

    argsFields.innerHTML = '';

    var methodDetail = methodsInfo[methodName];
    if (methodDetail && methodDetail.arguments && methodDetail.arguments.length > 0) {
      argsContainer.style.display = '';
      methodDetail.arguments.forEach(function (arg, idx) {
        var fieldId = 'apiArg_' + idx;
        var conditionBadge = '';
        if (arg.condition) {
          conditionBadge = '<span class="badge bg-' +
            (arg.condition === 'required' ? 'danger' : 'secondary') +
            ' ms-1">' + _escapeHtml(arg.condition) + '</span>';
        }
        var typeBadge = '';
        if (arg.type) {
          typeBadge = '<span class="badge bg-info text-dark ms-1">' + _escapeHtml(arg.type) + '</span>';
        }

        var fieldHtml =
          '<div class="api-arg-field mb-2">' +
            '<label for="' + fieldId + '" class="form-label mb-1">' +
              '<code>' + _escapeHtml(arg.name || 'arg' + idx) + '</code>' +
              conditionBadge + typeBadge +
            '</label>' +
            '<input type="text" class="form-control form-control-sm api-arg-input" ' +
              'id="' + fieldId + '" ' +
              'data-arg-index="' + idx + '" ' +
              'placeholder="' + _escapeHtml(arg.description || '') + '"' +
              (arg.default != null ? ' value="' + _escapeHtml(String(arg.default)) + '"' : '') +
            '>' +
          '</div>';

        argsFields.innerHTML += fieldHtml;
      });
    } else {
      // No known argument info — show a single JSON textarea
      argsContainer.style.display = '';
      argsFields.innerHTML =
        '<textarea class="form-control form-control-sm font-monospace" id="apiArgsRaw" rows="3" ' +
          'placeholder="Arguments as JSON array, e.g. [&quot;value1&quot;, 123] or leave empty for null"></textarea>';
    }
  }

  /**
   * Execute the selected API method and display the response.
   */
  function _executeAPIMethod(serviceName, methodName) {
    var serviceInfo = MM.servicesInfor[serviceName];
    var methodsInfo = serviceInfo.methods_info || {};
    var methodDetail = methodsInfo[methodName];

    // Collect arguments
    var args = null;
    var rawTextarea = document.getElementById('apiArgsRaw');
    if (rawTextarea) {
      // Free-form JSON input
      var rawVal = rawTextarea.value.trim();
      if (rawVal !== '') {
        try {
          args = JSON.parse(rawVal);
        } catch (e) {
          showToast('Invalid Arguments', 'Could not parse JSON: ' + e.message, 'danger');
          return;
        }
      }
    } else if (methodDetail && methodDetail.arguments && methodDetail.arguments.length > 0) {
      // Structured input fields
      var argValues = [];
      var argInputs = document.querySelectorAll('.api-arg-input');
      argInputs.forEach(function (input) {
        var val = input.value.trim();
        if (val === '') {
          argValues.push(null);
        } else {
          // Try to parse as JSON (number, bool, object), fall back to string
          try {
            argValues.push(JSON.parse(val));
          } catch (e) {
            argValues.push(val);
          }
        }
      });
      // Only send args if there are non-null values
      var hasValues = argValues.some(function (v) { return v !== null; });
      if (hasValues) {
        args = argValues;
      }
    }

    var requestData = {
      method: methodName,
      args: args
    };

    // Determine routing: use service's routing_key via exchange, or direct queue
    var executeBtn = document.getElementById('apiExecuteBtn');
    executeBtn.disabled = true;
    executeBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Executing...';

    var responseContainer = document.getElementById('apiResponseContainer');
    responseContainer.style.display = 'none';

    var startTime = Date.now();

    var requestPromise;
    if (serviceInfo.routing_key) {
      requestPromise = requestService(requestData, SERVICES_EXCHANGE_NAME, serviceInfo.routing_key);
    } else {
      requestPromise = MM.requestServiceDirect(requestData, serviceName);
    }

    requestPromise
      .then(function (data) {
        var elapsed = Date.now() - startTime;
        _showAPIResponse(data, elapsed);
      })
      .catch(function (error) {
        var elapsed = Date.now() - startTime;
        _showAPIResponse({
          request: methodName,
          result: 'exception',
          result_data: error.message || String(error)
        }, elapsed);
      })
      .finally(function () {
        executeBtn.disabled = false;
        executeBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Execute';
      });
  }

  /**
   * Display the API response in the response area.
   */
  function _showAPIResponse(data, elapsedMs) {
    var responseContainer = document.getElementById('apiResponseContainer');
    var badge = document.getElementById('apiResultBadge');
    var timeEl = document.getElementById('apiResponseTime');
    var dataEl = document.getElementById('apiResponseData');

    responseContainer.style.display = '';

    var result = data.result || 'unknown';
    var badgeClass = 'bg-success';
    if (result === 'fail') badgeClass = 'bg-warning text-dark';
    if (result === 'exception') badgeClass = 'bg-danger';

    badge.className = 'badge me-2 ' + badgeClass;
    badge.textContent = result;
    timeEl.textContent = elapsedMs + ' ms';

    var resultData = data.result_data;
    // Try to pretty-print if it's JSON string
    if (typeof resultData === 'string') {
      try {
        resultData = JSON.parse(resultData);
      } catch (e) {
        // not JSON, keep as string
      }
    }

    if (typeof resultData === 'object') {
      dataEl.textContent = JSON.stringify(resultData, null, 2);
    } else {
      dataEl.textContent = String(resultData);
    }
  }

  /************************************************************
   *             Service Helper Modal (multi-language)         *
   *                                                            *
   * Reflection-driven client snippets for Python / C++ /       *
   * Robot Framework.  Pulls method list + message schemas      *
   * from the bridge (/api/grpc/services/<name>) so the snippet *
   * shows real argument names and a JSON skeleton instead of   *
   * placeholders.                                              *
   ************************************************************/

  var helperModal = null;

  // ---- Per-method skeleton helpers --------------------------------------

  /**
   * Indent a JSON string by 4 spaces per nesting level (so it lines up
   * inside a Python triple-quoted block or a C++ raw-string literal).
   */
  function _indentedJson(obj, indent) {
    indent = indent || '';
    if (obj === null || obj === undefined) return indent + 'null';
    return JSON.stringify(obj, null, 2)
      .split('\n')
      .map(function (l) { return indent + l; })
      .join('\n');
  }

  /**
   * Build a one-liner human comment listing the request fields.
   * e.g. "  # fields: a:int32, b:int32"
   */
  function _fieldsComment(method, prefix) {
    prefix = prefix || '#';
    var fields = method.input_fields || [];
    if (!fields.length) return '';
    var parts = fields.map(function (f) { return f.name + ':' + f.type; });
    return '  ' + prefix + ' fields: ' + parts.join(', ');
  }

  // ---- Snippet generators (one per language) ----------------------------

  /**
   * Python snippet: call the gRPC method through the FastAPI bridge.
   *
   * Uses the bridge's reflection-driven /api/grpc/call endpoint so the
   * caller doesn't need a local .proto / generated stubs.  This is the
   * fastest path for "I want to drive this service from a script today";
   * for performance-critical paths the project's generate_protos.py +
   * stub-based grpc.insecure_channel(...) approach is better.
   */
  function _generatePythonReflect(serviceInfo, refl, bridgeOrigin) {
    var consulName = serviceInfo.name;
    var consulUrl  = serviceInfo.consulUrl || '';
    var grpcServices = (refl && refl.grpc_services) || [];

    var lines = [];
    lines.push('import json');
    lines.push('import httpx');
    lines.push('');
    lines.push('# Reflection-driven invocation through the Manager GUI bridge.');
    lines.push('# The bridge resolves ' + consulName + ' via Consul, opens a gRPC');
    lines.push('# channel, and serialises the request from the JSON schema below.');
    lines.push('BRIDGE = "' + bridgeOrigin + '"');
    if (consulUrl) {
      lines.push('CONSUL = "' + consulUrl + '"');
    } else {
      lines.push('CONSUL = ""   # leave blank to use the bridge\'s default Consul');
    }
    lines.push('SERVICE = "' + consulName + '"');
    lines.push('');
    lines.push('def call(grpc_service: str, method: str, request: dict) -> dict:');
    lines.push('    res = httpx.post(f"{BRIDGE}/api/grpc/call", json={');
    lines.push('        "consul_name":  SERVICE,');
    lines.push('        "grpc_service": grpc_service,');
    lines.push('        "method":       method,');
    lines.push('        "args_json":    json.dumps(request),');
    lines.push('        "consul":       CONSUL,');
    lines.push('    }, timeout=10.0)');
    lines.push('    return res.json()');
    lines.push('');

    if (!grpcServices.length) {
      lines.push('# No gRPC services advertised \u2014 is reflection enabled and the agent registered?');
      return lines.join('\n');
    }

    grpcServices.forEach(function (svc) {
      lines.push('# --- ' + svc.name + ' ---');
      var methods = svc.methods || [];
      if (!methods.length) {
        lines.push('# (no methods)');
        return;
      }
      methods.forEach(function (m) {
        lines.push('# ' + m.name + ' (' + (m.input_type || '') + ' -> ' + (m.output_type || '') + ')'
                   + (m.server_streaming ? '  [server-streaming]' : ''));
        lines.push('request = ' + _indentedJson(m.input_skeleton || {}, ''));
        lines.push('print(call("' + svc.name + '", "' + m.name + '", request))');
        lines.push('');
      });
    });

    return lines.join('\n').trimEnd();
  }

  /**
   * C++ snippet: stub-based call using generated gRPC headers.
   *
   * C++ has no production-grade equivalent of dynamic invocation, so we
   * show the stub-based form developers will actually paste into their
   * project after running protoc on the .proto.
   */
  function _generateCppReflect(serviceInfo, refl) {
    var grpcServices = (refl && refl.grpc_services) || [];
    var target = (refl && refl.target) ||
                 ((serviceInfo.address || '127.0.0.1') + ':' + (serviceInfo.port || 0));

    var lines = [];
    lines.push('// Build dependency: link against gRPC + the generated stubs');
    lines.push('// from your project\'s proto/<service>.proto (run');
    lines.push('// proto/generate_stubs.{bat,sh} to produce *.pb.h / *.grpc.pb.h).');
    lines.push('//');
    lines.push('// In production resolve "' + (serviceInfo.name || '') + '" via Consul');
    lines.push('// (GET /v1/health/service/<name>?passing=true) instead of hard-');
    lines.push('// coding host:port \u2014 this snippet uses the address Consul currently');
    lines.push('// reports for the service so you can run it as-is.');
    lines.push('');
    lines.push('#include <grpcpp/grpcpp.h>');
    lines.push('#include <iostream>');
    var hdrHints = {};
    grpcServices.forEach(function (svc) {
      // For an FQN like calc.v1.CalculatorService the first dotted part
      // (calc) is the proto package's root, which by mb-scaffold convention
      // is also the .proto filename \u2014 so calc.proto -> calc.grpc.pb.h.
      // The user must adjust if their project deviates.
      var hint = (svc.name.split('.')[0] || 'service');
      if (!hdrHints[hint]) {
        lines.push('#include "' + hint + '.grpc.pb.h"');
        hdrHints[hint] = true;
      }
    });
    lines.push('');
    lines.push('int main() {');
    lines.push('    auto channel = grpc::CreateChannel(');
    lines.push('        "' + target + '",');
    lines.push('        grpc::InsecureChannelCredentials());');
    lines.push('');

    if (!grpcServices.length) {
      lines.push('    // No gRPC services advertised \u2014 is reflection enabled and the agent registered?');
      lines.push('    return 0;');
      lines.push('}');
      return lines.join('\n');
    }

    grpcServices.forEach(function (svc) {
      // FQN namespace: calc.v1.CalculatorService -> calc::v1, type CalculatorService
      var parts = svc.name.split('.');
      var typeName = parts.pop();
      var ns = parts.join('::');
      var stubVar = typeName.charAt(0).toLowerCase() + typeName.slice(1) + 'Stub';

      lines.push('    // --- ' + svc.name + ' ---');
      lines.push('    auto ' + stubVar + ' = ' + ns + '::' + typeName + '::NewStub(channel);');
      lines.push('');

      (svc.methods || []).forEach(function (m) {
        // Input/output type name (last component of FQN)
        var inT  = (m.input_type  || '').split('.').pop() || 'Request';
        var outT = (m.output_type || '').split('.').pop() || 'Response';
        lines.push('    {');
        lines.push('        // ' + m.name + ' (' + (m.input_type || '') + ' -> ' + (m.output_type || '') + ')');
        lines.push('        ' + ns + '::' + inT + '  req;');
        // Show field assignments derived from input_fields where possible.
        var fields = m.input_fields || [];
        fields.forEach(function (f) {
          var setter = 'set_' + f.name;
          // reflect_client emits lowercase descriptor types: int32, string,
          // bool, bytes, message, ... and labels: optional, required, repeated.
          if (f.label === 'repeated') {
            lines.push('        // req.add_' + f.name + '(...);   // repeated ' + f.type);
          } else if (f.type === 'bool') {
            lines.push('        req.' + setter + '(false);');
          } else if (f.type === 'string' || f.type === 'bytes') {
            lines.push('        req.' + setter + '("");');
          } else if (f.type === 'message') {
            lines.push('        // req.mutable_' + f.name + '()->...   // nested ' + (f.message_type || 'message'));
          } else {
            lines.push('        req.' + setter + '(0);');
          }
        });
        lines.push('        ' + ns + '::' + outT + ' resp;');
        lines.push('        grpc::ClientContext ctx;');
        if (m.server_streaming) {
          lines.push('        auto reader = ' + stubVar + '->' + m.name + '(&ctx, req);');
          lines.push('        while (reader->Read(&resp)) {');
          lines.push('            std::cout << resp.DebugString();');
          lines.push('        }');
          lines.push('        auto status = reader->Finish();');
        } else {
          lines.push('        auto status = ' + stubVar + '->' + m.name + '(&ctx, req, &resp);');
        }
        lines.push('        if (!status.ok()) {');
        lines.push('            std::cerr << "' + m.name + ' failed: " << status.error_message() << "\\n";');
        lines.push('        } else {');
        lines.push('            std::cout << "' + m.name + ' OK:\\n" << resp.DebugString();');
        lines.push('        }');
        lines.push('    }');
        lines.push('');
      });
    });

    lines.push('    return 0;');
    lines.push('}');
    return lines.join('\n');
  }

  /**
   * Robot Framework snippet: QConnectBase GrpcClient connection type.
   *
   * Mirrors the QConnectBase house style (see python-process-hub /
   * QConnectBase test suites): import ConnectionManager `WITH NAME
   * conn_manager`, build the conn_conf as a `&{Param}` Create Dictionary,
   * then call `conn_manager.connect / verify / disconnect`.  The
   * GrpcClient ``send_cmd`` is a JSON document
   * ``{"method": "...", "args": {...}}`` (or with an explicit
   * ``"service": "<pkg.Service>"`` to target a specific service when the
   * connection's ``full_service_name`` differs).
   */
  function _generateRobotReflect(serviceInfo, refl) {
    var consulName = serviceInfo.name;
    var consulUrl  = serviceInfo.consulUrl || 'http://127.0.0.1:8500';
    var grpcServices = (refl && refl.grpc_services) || [];

    // Pick the first gRPC service as the connection's default
    // ``full_service_name``; per-test ``send_cmd`` can override with
    // ``"service": "<pkg.Service>"``.
    var defaultFqn = (grpcServices[0] && grpcServices[0].name) || '';

    var lines = [];
    lines.push('*** Settings ***');
    lines.push('Library    QConnectBase.ConnectionManager    WITH NAME    conn_manager');
    lines.push('');
    lines.push('*** Variables ***');
    lines.push('${SERVICE_NAME}        ' + consulName);
    lines.push('${CONSUL_ADDR}         ' + consulUrl);
    if (defaultFqn) {
      lines.push('${FULL_SERVICE_NAME}   ' + defaultFqn);
    }
    lines.push('');
    lines.push('*** Test Cases ***');

    if (!grpcServices.length) {
      lines.push(consulName + ' Smoke');
      lines.push('    [Documentation]    Connect to ${SERVICE_NAME} via Consul.');
      lines.push('    set_test_variable    ${connection_name}    ' + consulName + '-Connection');
      lines.push('    &{GrpcParam}=    Create Dictionary    conn_type=GrpcClient');
      lines.push('    ...                                   service_name=${SERVICE_NAME}');
      lines.push('    ...                                   consul_addr=${CONSUL_ADDR}');
      lines.push('');
      lines.push('    conn_manager.connect       conn_name=${connection_name}');
      lines.push('    ...                        conn_conf=${GrpcParam}');
      lines.push('    # No gRPC services advertised yet \u2014 is reflection enabled');
      lines.push('    # and the service registered in Consul?');
      lines.push('    conn_manager.disconnect    ${connection_name}');
      return lines.join('\n');
    }

    grpcServices.forEach(function (svc) {
      // FQN like calculator.v1.CalculatorService \u2192 bare type name for the
      // test-case label (CalculatorService).
      var bareType = svc.name.split('.').pop();
      (svc.methods || []).forEach(function (m) {
        var caseName = bareType + ' ' + m.name;

        lines.push(caseName);
        lines.push('    [Documentation]    Call ' + svc.name + '.' + m.name +
                   ' via the GrpcClient connection.');
        if (m.input_fields && m.input_fields.length) {
          lines.push('    ...                request fields: ' + m.input_fields.map(function (f) {
            return f.name + ':' + f.type;
          }).join(', '));
        }

        lines.push('');
        lines.push('    set_test_variable    ${connection_name}    ' +
                   bareType + '-' + m.name + '-Connection');
        lines.push('');
        lines.push('    # connection parameter for this test');
        lines.push('    &{GrpcParam}=    Create Dictionary    conn_type=GrpcClient');
        lines.push('    ...                                   service_name=${SERVICE_NAME}');
        lines.push('    ...                                   consul_addr=${CONSUL_ADDR}');
        lines.push('    ...                                   full_service_name=' + svc.name);
        lines.push('');
        lines.push('    conn_manager.connect       conn_name=${connection_name}');
        lines.push('    ...                        conn_conf=${GrpcParam}');
        lines.push('');

        // send_cmd payload \u2014 JSON document, single line so the Robot cell
        // parser doesn't trip on the embedded spaces.
        var sendCmd = JSON.stringify({
          method: m.name,
          args: m.input_skeleton || {}
        });
        lines.push('    ${res}=    conn_manager.verify    conn_name=${connection_name}');
        lines.push('    ...                               send_cmd=' + sendCmd);
        lines.push('    Log    ${res}');
        lines.push('');
        lines.push('    [Teardown]    conn_manager.disconnect    ${connection_name}');
        lines.push('');
      });
    });

    return lines.join('\n').trimEnd();
  }

  // ---- Modal entrypoint -------------------------------------------------

  /**
   * Show the multi-language client-snippet modal for a service.  Fetches
   * the service's reflected method list from the bridge before rendering
   * so the snippets contain real method names + JSON skeletons.
   *
   * @param {string} serviceName Key into MM.servicesInfor
   *     (e.g. "calculator@http://127.0.0.1:8500").
   */
  function showServiceHelper(serviceName) {
    var serviceInfo = MM.servicesInfor[serviceName];
    if (!serviceInfo) {
      showToast('Error', 'No information available for ' + serviceName, 'danger');
      return;
    }

    var version     = serviceInfo.version || '';
    var description = serviceInfo.description || serviceInfo.shortdesc || '';
    var displayName = serviceInfo.name || serviceName;

    var target = (serviceInfo.address || '') + (serviceInfo.port ? ':' + serviceInfo.port : '');
    var titleHtml =
      '<div class="dev-modal-head">' +
      '  <div class="dev-breadcrumb"><i class="bi bi-code-slash me-1"></i>Developer Tools' +
      '    <span class="dev-breadcrumb-sep">/</span>Code Examples</div>' +
      '  <div class="dev-title-row">' +
      '    <h5 class="dev-title">' + _escapeHtml(displayName) + '</h5>' +
      (version ? '<span class="dev-tag">' + _escapeHtml(version) + '</span>' : '') +
      (target ? '<code class="dev-target" title="Service address">' + _escapeHtml(target) + '</code>' : '') +
      '  </div>' +
      (description ? '<p class="dev-subtitle">' + _escapeHtml(description) + '</p>' : '') +
      '</div>';

    var spinnerHtml =
      '<div class="d-flex align-items-center text-muted small p-3">' +
      '  <span class="spinner-border spinner-border-sm me-2"></span>' +
      '  Discovering methods via gRPC reflection&hellip;' +
      '</div>';

    document.getElementById('helperModalTitle').textContent = 'Code Examples \u2014 ' + displayName;
    document.getElementById('helperModalBody').innerHTML = titleHtml + spinnerHtml;

    if (!helperModal) {
      helperModal = new bootstrap.Modal(document.getElementById('helperModal'));
    }
    helperModal.show();

    // Fire the reflection lookup AFTER the modal is shown so the user
    // sees the spinner immediately even on slow Consul lookups.
    var bridgeOrigin = (MM.serviceClient && MM.serviceClient.apiUrl) || window.location.origin;

    // Forward the stored proto path so the Helper benefits from the same
    // fallback the main methods panel uses.  Without this, a server
    // without grpc++_reflection always lands in the "Reflection failed
    // … search paths (<empty>)" error path even when the user has
    // already typed a folder for the main panel.
    var helperProtoPath = _getStoredProtoPath(serviceInfo.name);
    MM.grpcClient.getServiceMethods(serviceInfo.name, serviceInfo.consulUrl, helperProtoPath)
      .then(function (refl) {
        if (refl.error && (!refl.grpc_services || !refl.grpc_services.length)) {
          // Bridge couldn't talk to the service at all \u2014 show the error and
          // generate snippets with empty schemas so the user still gets the
          // boilerplate.
          var errBlock =
            '<div class="alert alert-warning small mb-3">' +
            '  <i class="bi bi-exclamation-triangle me-1"></i>' +
            '  Reflection failed: <code>' + _escapeHtml(String(refl.error)) + '</code>.<br>' +
            '  Showing snippets with empty request schemas \u2014 fill in the fields by hand.' +
            '</div>';
          _renderHelperTabs(serviceInfo, refl, bridgeOrigin, titleHtml + errBlock);
          return;
        }
        _renderHelperTabs(serviceInfo, refl, bridgeOrigin, titleHtml);
      })
      .catch(function (err) {
        var errHtml =
          titleHtml +
          '<div class="alert alert-danger small">' +
          '  <i class="bi bi-x-octagon me-1"></i>' +
          '  Couldn\'t reach the bridge: <code>' + _escapeHtml(err.message || String(err)) + '</code>' +
          '</div>';
        document.getElementById('helperModalBody').innerHTML = errHtml;
      });
  }

  /**
   * Render the Python / C++ / Robot tabs into the modal body.  Internal
   * helper called once reflection data (or an error) has arrived.
   */
  function _renderHelperTabs(serviceInfo, refl, bridgeOrigin, headerHtml, opts) {
    opts = opts || {};
    var prefix = opts.idPrefix || 'helper';
    var pythonCode = _generatePythonReflect(serviceInfo, refl, bridgeOrigin);
    var cppCode    = _generateCppReflect(serviceInfo, refl);
    var robotCode  = _generateRobotReflect(serviceInfo, refl);

    var base = String(serviceInfo.name || 'service').toLowerCase().replace(/[^a-z0-9]+/g, '_');
    var tabs = [
      { id: 'Python', icon: 'bi-filetype-py',  file: base + '_client.py',  code: pythonCode },
      { id: 'Cpp',    icon: 'bi-filetype-cpp', file: base + '_client.cpp', code: cppCode,
        label: 'C++' },
      { id: 'Robot',  icon: 'bi-robot',        file: base + '.resource',   code: robotCode }
    ];

    var navHtml = '<ul class="nav nav-tabs helper-lang-tabs" role="tablist">' +
      tabs.map(function (t, i) {
        return '<li class="nav-item" role="presentation">' +
               '<button class="nav-link' + (i === 0 ? ' active' : '') + '" data-bs-toggle="tab"' +
               ' data-bs-target="#' + prefix + 'Tab' + t.id + '" type="button" role="tab"' +
               ' aria-selected="' + (i === 0 ? 'true' : 'false') + '">' +
               '<i class="bi ' + t.icon + ' me-1"></i>' + (t.label || t.id) +
               '<span class="dev-file">' + _escapeHtml(t.file) + '</span></button></li>';
      }).join('') + '</ul>';

    var panesHtml = '<div class="tab-content">' +
      tabs.map(function (t, i) {
        return '<div class="tab-pane fade' + (i === 0 ? ' show active' : '') + '" id="' + prefix + 'Tab' + t.id + '"' +
               ' role="tabpanel">' +
               '<pre class="helper-code-pre" id="' + prefix + 'Code' + t.id + '">' + _numberedCode(t.code) + '</pre>' +
               '</div>';
      }).join('') + '</div>';

    document.getElementById(opts.containerId || 'helperModalBody').innerHTML = headerHtml + navHtml + panesHtml;
  }

  /**
   * Wrap each line in a span so CSS can draw a line-number gutter. Lines
   * stay joined by real newlines, so `pre.textContent` (used by Copy) is
   * still the plain code.
   */
  function _numberedCode(code) {
    return _escapeHtml(code).split('\n').map(function (line) {
      return '<span class="code-line">' + (line === '' ? ' ' : line) + '</span>';
    }).join('\n');
  }

  /**
   * Get the code text from the currently active helper tab.
   * @returns {string}
   */
  function _getActiveHelperCode() {
    var activePane = document.querySelector('#helperModalBody .tab-pane.active.show');
    if (!activePane) return '';
    var pre = activePane.querySelector('pre');
    return pre ? pre.textContent : '';
  }

  // Copy button handler
  document.getElementById('btnCopyHelper').addEventListener('click', function () {
    var code = _getActiveHelperCode();
    if (!code) return;
    navigator.clipboard.writeText(code).then(function () {
      showToast('Copied', 'Code copied to clipboard.', 'success');
    }).catch(function () {
      // Fallback for older browsers
      var textarea = document.createElement('textarea');
      textarea.value = code;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      showToast('Copied', 'Code copied to clipboard.', 'success');
    });
  });

  /**
   * Escape HTML special characters.
   */
  function _escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /************************************************************
   *             Element Events Handling Section              *
   ************************************************************/

  // Detect transport mode on startup
  if (window.electronAPI) {
    console.log('[app] Running in Electron mode (preload bridge detected)');
  } else {
    console.log('[app] Running in Browser mode (FastAPI transport)');
  }

  document.getElementById('btnConnect').addEventListener('click', function () {
    // New flow: the Connect button opens the Consul connect modal.  The
    // legacy broker login (connect() -> loginModal) is no longer reachable
    // from the UI but still works if called programmatically.
    _openConsulConnectModal();
  });

  var _consulConnectModal = null;

  // Multi-Consul state: each entry is { url, leader, services: [...] }
  // where ``services`` is the raw service list fetched from this Consul.
  var _connectedConsuls = [];   // array kept in insertion order
  var CONSULS_STORAGE_KEY = 'mm_consul_urls';     // JSON array of URLs

  function _saveConsulUrls() {
    try {
      var urls = _connectedConsuls.map(function (c) { return c.url; });
      localStorage.setItem(CONSULS_STORAGE_KEY, JSON.stringify(urls));
    } catch (e) {}
  }

  function _loadSavedConsulUrls() {
    try {
      var raw = localStorage.getItem(CONSULS_STORAGE_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }

  function _openConsulConnectModal() {
    var modalEl = document.getElementById('consulConnectModal');
    if (!modalEl) return;
    if (!_consulConnectModal) {
      _consulConnectModal = new bootstrap.Modal(modalEl);
    }

    // Prefill with a reasonable default or the most recent URL typed.
    try {
      var saved = localStorage.getItem('mm_consul_last_input_url');
      document.getElementById('consulConnectUrl').value =
        saved || 'http://127.0.0.1:8500';
    } catch (e) {}

    _setConsulConnectResult('', '');
    _consulConnectModal.show();
  }

  function _setConsulConnectResult(kind, html) {
    var el = document.getElementById('consulConnectResult');
    if (!el) return;
    if (!kind) {
      el.className = 'small';
      el.innerHTML = '';
    } else {
      el.className = 'small alert alert-' + kind + ' py-2 mb-0 mt-2';
      el.innerHTML = html;
    }
  }

  var _btnConsulConnectSubmit = document.getElementById('btnConsulConnectSubmit');
  if (_btnConsulConnectSubmit) {
    _btnConsulConnectSubmit.addEventListener('click', function () {
      _submitConsulConnect();
    });
  }

  var _btnConsulDetect = document.getElementById('btnConsulDetect');
  if (_btnConsulDetect) {
    _btnConsulDetect.addEventListener('click', function () {
      _runConsulDetect();
    });
  }

  function _runConsulDetect() {
    var btn = document.getElementById('btnConsulDetect');
    var results = document.getElementById('consulDetectResults');
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
              _escapeHtml(data.error) +
            '</div>';
          return;
        }
        var instances = (data && data.instances) || [];
        // Hide instances that are already in _connectedConsuls so the
        // user isn't offered to re-add what they already have.
        var already = {};
        _connectedConsuls.forEach(function (c) { already[c.url] = 1; });
        instances = instances.filter(function (i) { return !already[i.url]; });

        if (instances.length === 0) {
          results.innerHTML =
            '<div class="alert alert-warning small mt-2 mb-0">' +
            '  <i class="bi bi-exclamation-triangle me-1"></i>' +
            '  No new Consul processes found. ' +
            '</div>';
          return;
        }

        var rows = instances.map(function (inst) {
          var roleBadge = inst.server
            ? '<span class="badge bg-primary ms-1">server</span>'
            : '<span class="badge bg-secondary ms-1">client</span>';
          var versionBadge = inst.version
            ? '<span class="badge bg-light text-dark ms-1">v' + _escapeHtml(inst.version) + '</span>'
            : '';
          var dcBadge = inst.datacenter
            ? '<span class="badge bg-light text-dark ms-1">' + _escapeHtml(inst.datacenter) + '</span>'
            : '';
          var pidBadge = inst.pid
            ? '<span class="badge bg-secondary ms-1">pid ' + inst.pid + '</span>'
            : '';

          return '<button type="button" class="list-group-item list-group-item-action consul-detect-row"' +
                 '  data-url="' + _escapeHtml(inst.url) + '">' +
                 '  <div class="d-flex justify-content-between align-items-center">' +
                 '    <div>' +
                 '      <strong>' + _escapeHtml(inst.node_name || inst.host + ':' + inst.port) + '</strong>' +
                          roleBadge + versionBadge + dcBadge + pidBadge +
                 '      <div class="small text-muted">' + _escapeHtml(inst.url) + '</div>' +
                 '    </div>' +
                 '    <i class="bi bi-chevron-right"></i>' +
                 '  </div>' +
                 '</button>';
        }).join('');

        results.innerHTML =
          '<div class="small text-muted mb-1">' +
          '  Found <strong>' + instances.length + '</strong> Consul process(es) — click to select:' +
          '</div>' +
          '<div class="list-group mb-2">' + rows + '</div>';

        // Wire each row: fill the URL input.  Don't auto-submit — let the
        // user review and click Connect themselves (there might be an
        // ACL token they want to fill in first).
        results.querySelectorAll('.consul-detect-row').forEach(function (row) {
          row.addEventListener('click', function () {
            var url = row.getAttribute('data-url');
            var input = document.getElementById('consulConnectUrl');
            if (input) input.value = url;
            results.querySelectorAll('.consul-detect-row.active')
                   .forEach(function (el) { el.classList.remove('active'); });
            row.classList.add('active');
          });
        });
      })
      .catch(function (err) {
        results.innerHTML =
          '<div class="alert alert-danger small mt-2 mb-0">' +
          '  Detect failed: ' + _escapeHtml(err.message || err) +
          '</div>';
      })
      .finally(function () {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-search me-1"></i>Detect';
      });
  }

  // Clear detect results when the modal closes so stale rows don't
  // linger into the next Connect attempt.
  (function () {
    var modalEl = document.getElementById('consulConnectModal');
    if (modalEl) {
      modalEl.addEventListener('hidden.bs.modal', function () {
        var results = document.getElementById('consulDetectResults');
        if (results) results.innerHTML = '';
      });
    }
  })();

  function _submitConsulConnect() {
    var rawUrl = (document.getElementById('consulConnectUrl').value || '').trim();

    if (!rawUrl) {
      _setConsulConnectResult('warning', 'Consul URL is required.');
      return;
    }
    var url = rawUrl.replace(/\/+$/, '');   // trim trailing slashes
    try { localStorage.setItem('mm_consul_last_input_url', url); } catch (e) {}

    // Dedupe
    var existing = _connectedConsuls.find(function (c) { return c.url === url; });
    if (existing) {
      _setConsulConnectResult('warning', 'Already connected to ' + url + '.');
      return;
    }

    var btn = document.getElementById('btnConsulConnectSubmit');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Connecting...';
    }
    _setConsulConnectResult('info', 'Probing Consul...');

    _connectConsulUrl(url)
      .then(function (conn) {
        _connectedConsuls.push(conn);
        _saveConsulUrls();
        _renderConsulChips();
        _renderAllConnectedConsuls();

        _setConsulConnectResult('success',
          'Connected. ' + conn.services.length + ' service(s) registered.');
        showToast('Consul',
          'Connected to ' + url + ' — ' +
          conn.services.length + ' service(s).', 'success');
        setTimeout(function () {
          if (_consulConnectModal) _consulConnectModal.hide();
        }, 800);
      })
      .catch(function (err) {
        _setConsulConnectResult('danger', 'Connect failed: ' + (err.message || err));
        showToast('Consul', 'Connect failed: ' + (err.message || err), 'danger');
      })
      .finally(function () {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-plug me-1"></i>Connect';
        }
      });
  }

  /**
   * Probe a Consul URL, fetch its service catalog (with details), and
   * return a Promise resolving to a connection object
   *   { url, leader, services: [ {name, tags, address, port, grpcServices, instances} ] }
   *
   * The services list is pre-filtered to remove infrastructure entries
   * (consul/nomad/nomad-client).
   */
  function _connectConsulUrl(url) {
    var HIDDEN = { 'consul': 1, 'nomad': 1, 'nomad-client': 1 };
    var leader = '';

    return MM.consulClient.testConnection(url)
      .then(function (health) {
        if (!health || !health.ok) {
          throw new Error((health && health.error) || 'Consul not reachable');
        }
        leader = health.leader || '';
        return MM.consulClient.getServices(url);
      })
      .then(function (servicesMap) {
        var names = Object.keys(servicesMap || {}).filter(function (n) {
          return n && !HIDDEN[n];
        }).sort();
        var detailPromises = names.map(function (name) {
          return MM.consulClient.getServiceDetail(name, url)
            .catch(function () { return []; });
        });
        return Promise.all(detailPromises).then(function (details) {
          var services = names.map(function (name, i) {
            var instances = Array.isArray(details[i]) ? details[i] : [];
            var first = instances[0] || {};
            var svc = first.Service || {};
            return {
              name: name,
              tags: (servicesMap[name] || []),
              address: svc.Address || '',
              port: svc.Port || 0,
              grpcServices: (svc.Meta && svc.Meta.grpc_services) || '',
              // Plugin folder under web/services/ the service asks the
              // Manager GUI to show (ServiceRunner registers settings.gui
              // as Meta.gui). Empty = no GUI.
              gui: (svc.Meta && svc.Meta.gui) || '',
              instances: instances.length,
              status: _computeServiceStatus(instances)
            };
          });
          return { url: url, leader: leader, services: services, alive: true };
        });
      });
  }

  function _removeConsulConnection(url) {
    _connectedConsuls = _connectedConsuls.filter(function (c) {
      return c.url !== url;
    });
    _saveConsulUrls();
    _renderConsulChips();
    _renderAllConnectedConsuls();
    showToast('Consul', 'Disconnected from ' + url, 'info');
  }

  function _renderConsulChips() {
    var container = document.getElementById('consulChips');
    if (!container) return;
    container.innerHTML = '';

    _connectedConsuls.forEach(function (conn) {
      var chip = document.createElement('div');
      var alive = conn.alive !== false;
      chip.className = 'consul-chip' + (alive ? '' : ' consul-chip-down');
      chip.title = conn.url +
        (conn.leader ? '  (leader: ' + conn.leader + ')' : '') +
        (!alive ? '  — unreachable' + (conn.lastError ? ': ' + conn.lastError : '') : '');

      var label = _shortenConsulUrl(conn.url);
      var iconCls = alive
        ? 'bi bi-compass consul-chip-icon'
        : 'bi bi-plug consul-chip-icon consul-chip-icon-down';

      chip.innerHTML =
        '<i class="' + iconCls + '"></i>' +
        '<span class="consul-chip-label">' + _escapeHtml(label) + '</span>' +
        '<button type="button" class="consul-chip-close" aria-label="Disconnect">' +
        '  <i class="bi bi-x"></i>' +
        '</button>';

      chip.querySelector('.consul-chip-close').addEventListener('click', function (e) {
        e.stopPropagation();
        _removeConsulConnection(conn.url);
      });

      container.appendChild(chip);
    });
  }

  function _shortenConsulUrl(url) {
    // Strip http(s):// for compactness; keep host:port.
    return String(url || '').replace(/^https?:\/\//, '');
  }

  /**
   * Given a list of instance entries from /v1/health/service/{name}, return
   * an overall status object usable for the sidebar indicator.  The entry
   * shape is { Node, Service, Checks: [{Status, ...}] }.
   *
   * Status precedence (worst wins): critical > warning > passing > unknown.
   * Returns:
   *    { kind: 'passing' | 'warning' | 'critical' | 'unknown',
   *      label: string,
   *      passing: N, warning: N, critical: N }
   */
  function _computeServiceStatus(instances) {
    if (!Array.isArray(instances) || instances.length === 0) {
      return { kind: 'unknown', label: 'no instances',
               passing: 0, warning: 0, critical: 0 };
    }
    var p = 0, w = 0, c = 0;
    instances.forEach(function (inst) {
      // Reduce the per-instance checks to one status (worst wins).
      var checks = (inst && inst.Checks) || [];
      var worst = 'passing';
      for (var i = 0; i < checks.length; i++) {
        var s = checks[i].Status;
        if (s === 'critical') { worst = 'critical'; break; }
        if (s === 'warning' && worst !== 'critical') worst = 'warning';
      }
      if (worst === 'critical') c++;
      else if (worst === 'warning') w++;
      else p++;
    });

    var total = p + w + c;
    var kind = 'passing';
    var label = 'running';
    if (c > 0 && p === 0 && w === 0) {
      kind = 'critical';
      label = 'critical';
    } else if (c > 0 || w > 0) {
      kind = 'warning';
      label = 'degraded ' + p + '/' + total;
    } else {
      kind = 'passing';
      label = total > 1 ? ('running ' + p + '/' + total) : 'running';
    }
    return { kind: kind, label: label, passing: p, warning: w, critical: c };
  }

  /**
   * Render the sidebar from the current set of _connectedConsuls.  One
   * accordion group per Consul URL, with its services inside.  Called
   * whenever the connection list changes (add, remove, reload).
   */
  function _renderAllConnectedConsuls() {
    var container = document.getElementById('servicesList');
    if (!container) return;

    container.classList.remove('multi-broker');
    container.innerHTML = '';

    // Rebuild MM.servicesInfor for method lookup and search.  Keys are
    // scoped by URL so two services with the same name on different
    // Consuls don't collide.
    MM.servicesInfor = {};
    _connectedConsuls.forEach(function (conn) {
      conn.services.forEach(function (svc) {
        var key = svc.name + '@' + conn.url;
        MM.servicesInfor[key] = {
          name: svc.name,
          routing_key: svc.name,
          version: '1.0.0',
          tag: svc.tags.join(','),
          shortdesc: svc.grpcServices || 'gRPC service',
          description: 'Consul ' + conn.url + ' @ ' +
                        (svc.address || '?') + ':' + (svc.port || '?'),
          methods: [],
          gui_support: !!svc.gui,
          gui: svc.gui || '',
          address: svc.address,
          port: svc.port,
          consulUrl: conn.url
        };
      });
    });

    // If the service shown on the right (API explorer / cached panel) was
    // just deregistered (process killed, Nomad job stopped, agent down,
    // or its Consul cluster disconnected), clear it.  Without this the
    // user is left with a stale panel showing methods for a service that
    // no longer exists.  Also drop the cached panel so re-registration
    // picks up fresh metadata instead of resurrecting the stale element.
    // The bench composes from the same services; it recomposes only when a
    // name, GUI folder or address changed.
    if (MM.endo && MM.endo.bench) MM.endo.bench.servicesChanged();

    if (_activePanelName && !MM.servicesInfor[_activePanelName]) {
      var goneName = _activePanelName;
      _deactivateCurrentPanel();
      if (_servicePanels[goneName]) {
        try { _servicePanels[goneName].remove(); } catch (e) { /* ignore */ }
        delete _servicePanels[goneName];
      }
    }

    if (_connectedConsuls.length === 0) {
      container.innerHTML =
        '<div class="sidebar-empty-hint">' +
        '  Click <strong>Connect</strong> in the toolbar to connect to a ' +
        '  Consul cluster.' +
        '</div>';
      return;
    }

    _connectedConsuls.forEach(function (conn, idx) {
      var groupId = 'consulGroup_' + idx;
      var shortUrl = _shortenConsulUrl(conn.url);
      var alive = conn.alive !== false;

      var item = document.createElement('div');
      item.className = 'accordion-item' + (alive ? '' : ' consul-group-down');
      item.innerHTML =
        '  <h2 class="accordion-header">' +
        '    <button class="accordion-button" type="button"' +
        '            data-bs-toggle="collapse" data-bs-target="#' + groupId + '"' +
        '            aria-expanded="true">' +
        '      <i class="bi ' + (alive ? 'bi-compass' : 'bi-plug') + ' me-2"></i>' +
        '      <span class="me-2">' + _escapeHtml(shortUrl) + '</span>' +
        (alive && conn.leader
          ? '<span class="badge bg-secondary me-1">' + _escapeHtml(conn.leader) + '</span>'
          : '') +
        (alive
          ? '<span class="badge bg-info">' + conn.services.length + '</span>'
          : '<span class="badge bg-danger">unreachable</span>') +
        '    </button>' +
        '  </h2>' +
        '  <div id="' + groupId + '" class="accordion-collapse collapse show">' +
        '    <div class="accordion-body p-0">' +
        '      <ul class="list-group list-group-flush"></ul>' +
        '    </div>' +
        '  </div>';
      container.appendChild(item);

      var list = item.querySelector('ul.list-group');

      if (!alive) {
        list.innerHTML =
          '<li class="list-group-item sidebar-empty-row">' +
          '  <i class="bi bi-exclamation-triangle me-1"></i>' +
          '  <em>Consul is unreachable</em>' +
          (conn.lastError
            ? '<div class="small text-muted mt-1">' + _escapeHtml(conn.lastError) + '</div>'
            : '') +
          '</li>';
        return;
      }

      if (conn.services.length === 0) {
        list.innerHTML =
          '<li class="list-group-item sidebar-empty-row">' +
          '  <em>No services registered yet.</em>' +
          '</li>';
        return;
      }

      conn.services.forEach(function (svc) {
        var row = document.createElement('li');
        row.className = 'list-group-item';
        row.setAttribute('data-service-name', svc.name);

        var status = svc.status || { kind: 'unknown', label: 'unknown' };
        // Key into MM.servicesInfor — must match the format used at
        // line ~2160 (svc.name + '@' + conn.url) so showServiceHelper
        // can look the service up.
        var infoKey = svc.name + '@' + conn.url;

        // Wrap stacked text in a single block child of the flex row.
        // Operator view only: no per-row developer buttons -- code
        // snippets, method calls and generators live under Developer Tools.
        // A service without Meta.gui is marked so up front.
        row.innerHTML =
          '<div class="svc-row">' +
          '  <div class="svc-name">' +
          '    <span class="svc-status svc-status-' + status.kind + '"' +
          '          title="' + _escapeHtml(status.label) + '"></span>' +
                 _escapeHtml(svc.name) +
          (svc.gui
            ? ''
            : '    <span class="no-gui-badge" title="No GUI available - selecting this service shows its runtime info">No GUI</span>') +
          '  </div>' +
          '  <div class="svc-hint">' +
               _escapeHtml((svc.address || '?') + ':' + (svc.port || '?')) +
               (svc.tags.length
                 ? ' · ' + svc.tags.slice(0, 3).map(_escapeHtml).join(', ')
                 : '') +
          '  </div>' +
          '</div>';

        // Attach the Consul URL so the gRPC panel can route its calls
        // through the right bridge query param.
        var svcWithUrl = Object.assign({}, svc, { consulUrl: conn.url });

        row.addEventListener('click', function () {
          _selectedService = { name: svc.name, infoKey: infoKey, consul: svcWithUrl, info: null };
          if (svc.gui) _openConsulServiceGui(_selectedService);
          else _showServiceOverview(_selectedService);
          if (_devMode) _renderInspector(_selectedService);
          // Visual selection across all groups
          document
            .querySelectorAll('#servicesList .list-group-item.active')
            .forEach(function (el) { el.classList.remove('active'); });
          row.classList.add('active');
        });

        list.appendChild(row);
      });
    });
  }

  /** Every service of every reachable Consul, with its consulUrl (the bench composes from these). */
  function _allConnectedServices() {
    var out = [];
    _connectedConsuls.forEach(function (conn) {
      if (conn.alive === false) return;
      (conn.services || []).forEach(function (svc) {
        out.push(Object.assign({}, svc, { consulUrl: conn.url }));
      });
    });
    return out;
  }

  /**
   * Show a service in the Services view, as a click on its sidebar row
   * would. opts.classic shows the classic panel of a folder that also has
   * a component.json (the bench dock offers it).
   */
  function _openServiceFromBench(svc, opts) {
    switchMode('services');
    var infoKey = svc.name + '@' + svc.consulUrl;
    _selectedService = { name: svc.name, infoKey: infoKey, consul: svc, info: null };
    document.querySelectorAll('#servicesList .list-group-item.active').forEach(function (el) { el.classList.remove('active'); });
    var row = Array.prototype.filter.call(
      document.querySelectorAll('#servicesList .list-group-item[data-service-name]'),
      function (el) { return el.getAttribute('data-service-name') === svc.name; })[0];
    if (row) row.classList.add('active');
    if (svc.gui) _openConsulServiceGui(_selectedService, opts);
    else _showServiceOverview(_selectedService);
    if (_devMode) _renderInspector(_selectedService);
  }

  /**
   * Show the GUI a Consul-registered service declares through Meta.gui:
   * the name of a plugin folder under web/services/ (e.g. HelloService1.0.0),
   * loaded with the same tiers as registry services (schema, QML, Widget,
   * Qt WASM, HTML). The panel is cached per service name. The plugin
   * learns which instance it drives from MM.currentGuiService.
   */
  function _openConsulServiceGui(sel, opts) {
    var svc = sel.consul;
    var contentDiv = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);
    if (!contentDiv || !svc || !svc.gui) return;
    var classic = !!(opts && opts.classic);

    MM.currentGuiService = {
      name: svc.name,
      consulUrl: svc.consulUrl,
      address: svc.address,
      port: svc.port,
      grpcServices: svc.grpcServices,
      gui: svc.gui
    };

    // One cached panel per service: drop it when the other kind is wanted
    // (classic panel from the bench dock <-> the component from the sidebar).
    var cachedPanel = _servicePanels[sel.name];
    if (cachedPanel && (classic ? !!cachedPanel.__endoHandle : _classicPanels[sel.name])) {
      if (_activePanelName === sel.name) _deactivateCurrentPanel();
      if (cachedPanel.__endoHandle) cachedPanel.__endoHandle.destroy();
      try { cachedPanel.remove(); } catch (e) { /* already gone */ }
      delete _servicePanels[sel.name];
    }
    _classicPanels[sel.name] = classic;

    if (_servicePanels[sel.name]) {
      // Cache hit: loadServiceContent only consults servicesInfor on a
      // miss, so it is safe to reuse its show-cached-panel path here.
      loadServiceContent(sel.name, DIV_NAME.SERVICE_CONTENT_DIV);
      // A component was suspended when it was hidden (R5); start it again.
      var cached = _servicePanels[sel.name];
      if (cached && cached.__endoHandle) cached.__endoHandle.resume();
      return;
    }
    _deactivateCurrentPanel();
    var folder = String(svc.gui).replace(/^[\/\\]+|[\/\\]+$/g, '');
    var folderPath = SERVICES_GUI_FOLDER + '/' + folder;
    // A folder with component.json is a Bench Endoskeleton component
    // (contract v1); anything else loads through the legacy tiers unchanged.
    if (classic) {
      _loadServiceGUIMultiTier(sel.name, folderPath, contentDiv, '');
      return;
    }
    _tryMountComponent(sel, svc, folderPath, contentDiv).then(function (mounted) {
      if (!mounted) _loadServiceGUIMultiTier(sel.name, folderPath, contentDiv, '');
    });
  }

  /** The component shown in the Services view, if the open panel is one. */
  function _activeComponentHandle() {
    var panel = _activePanelName && _servicePanels[_activePanelName];
    return (panel && panel.__endoHandle) || null;
  }
  function _suspendActiveComponent() {
    var h = _activeComponentHandle();
    if (h) h.suspend();
  }
  function _resumeActiveComponent() {
    var h = _activeComponentHandle();
    if (h) h.resume();
  }

  /**
   * Mount <folder>/component.json as a component panel, if there is one.
   * Resolves true when this function handled the service (mounted, refused
   * or superseded by a newer selection), false to fall back to the legacy
   * loader.
   */
  function _tryMountComponent(sel, svc, folderPath, contentDiv) {
    if (!MM.endo || !MM.endo.mountComponent) return Promise.resolve(false);
    return fetch(folderPath + '/component.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.text() : null; })
      .catch(function () { return null; })
      .then(function (text) {
        if (text === null) return false;
        // The user may have picked another service while this loaded.
        if (!MM.currentGuiService || MM.currentGuiService.name !== svc.name) return true;
        var manifest;
        try { manifest = JSON.parse(text); } catch (e) { manifest = { __parseError: e.message }; }
        var wrapper = document.createElement('div');
        wrapper.setAttribute('data-cached-service', sel.name);
        wrapper.className = 'endo-panel';
        contentDiv.appendChild(wrapper);
        _servicePanels[sel.name] = wrapper;
        _activePanelName = sel.name;
        return MM.endo.mountComponent(manifest, wrapper, {
          consulName: svc.name,
          consulUrl: svc.consulUrl,
          protoPath: _getStoredProtoPath(svc.name),
          base: new URL(folderPath + '/', document.baseURI).href   // frame tiles' pages
        }).then(function (handle) {
          wrapper.__endoHandle = handle;
          // Hiding the panel runs unload<Name>: stop polling while hidden (R5).
          window['unload' + sel.name] = function () { handle.suspend(); };
          unloadFunction = window['unload' + sel.name];
          return true;
        });
      });
  }

  /**
   * Operator's view of a service that has no GUI: what it is, where it
   * runs, whether it is healthy. Calling methods, code snippets and
   * generators are developer tools and live under the Developer Tools
   * menu, so the runtime view stays free of them.
   *
   * @param {object} sel - { name, consul: <Consul svc + consulUrl> | null,
   *                         info: <MM.servicesInfor entry> | null }
   */
  function _showServiceOverview(sel) {
    var contentDiv = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);
    if (!contentDiv) return;

    // Hide any cached GUI panel and drop previous non-cached content. The
    // overview is itself non-cached, so the next selection replaces it.
    _deactivateCurrentPanel();

    var svc = sel.consul;
    var info = sel.info || {};
    var st = (svc && svc.status) || { kind: 'passing', label: 'available' };
    var kind = st.kind || 'unknown';

    var rows = [];
    function add(label, value) {
      if (value === undefined || value === null || value === '') return;
      rows.push('<tr><th>' + _escapeHtml(label) + '</th><td>' + value + '</td></tr>');
    }
    if (svc) {
      add('Address', '<code>' + _escapeHtml((svc.address || '?') + ':' + (svc.port || '?')) + '</code>');
      add('Instances', _escapeHtml(String(svc.instances || 0)));
      add('Tags', (svc.tags || []).map(function (t) {
        return '<span class="dev-tag">' + _escapeHtml(t) + '</span>';
      }).join(' '));
      add('gRPC services', svc.grpcServices
        ? svc.grpcServices.split(',').map(function (g) { return '<code>' + _escapeHtml(g) + '</code>'; }).join(' ')
        : '');
      add('Registry', _escapeHtml(svc.consulUrl || ''));
    } else {
      add('Description', _escapeHtml(info.description || info.shortdesc || ''));
      add('Version', _escapeHtml(info.version || ''));
      add('Group', _escapeHtml(info.group || ''));
      add('Broker', _escapeHtml(MM.activeBrokerUrl || ''));
    }

    var wrap = document.createElement('div');
    wrap.className = 'svc-overview';
    wrap.setAttribute('data-runtime-card', sel.name);
    wrap.innerHTML =
      '<div class="svc-ov-head">' +
      '  <span class="svc-ov-dot svc-ov-dot-' + _escapeHtml(kind) + '"></span>' +
      '  <h4 class="svc-ov-title">' + _escapeHtml(sel.name) + '</h4>' +
      '  <span class="svc-ov-pill svc-ov-pill-' + _escapeHtml(kind) + '">' + _escapeHtml(st.label || kind) + '</span>' +
      '  <span class="no-gui-badge" title="This service ships no GUI; use the actions below">No GUI</span>' +
      '  <div class="svc-ov-tools">' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" id="svcOvRefresh" title="Refresh status and instances">' +
      '      <i class="bi bi-arrow-clockwise"></i></button>' +
      '  </div>' +
      '</div>' +
      '<div class="svc-ov-grid">' +
      '  <section class="svc-ov-card">' +
      '    <h6 class="svc-ov-card-title"><i class="bi bi-info-circle me-1"></i>Overview</h6>' +
      '    <table class="svc-card-table">' + rows.join('') + '</table>' +
      '  </section>' +
      '  <section class="svc-ov-card">' +
      '    <h6 class="svc-ov-card-title"><i class="bi bi-hdd-stack me-1"></i>Instances</h6>' +
      '    <div id="svcOvInstances">' + (svc ? _devLoading('Loading instances\u2026') : '<span class="text-muted small">Not tracked for registry services.</span>') + '</div>' +
      '  </section>' +
      '</div>' +
      '<section class="svc-ov-card svc-ov-actions-card">' +
      '  <h6 class="svc-ov-card-title"><i class="bi bi-lightning-charge me-1"></i>Actions' +
      '    <span class="svc-ov-card-hint">Invoke the service directly. Fields are derived from its API.</span></h6>' +
      '  <div id="svcOvActions">' + (svc ? _devLoading('Discovering actions\u2026') : '') + '</div>' +
      '</section>';
    contentDiv.appendChild(wrap);

    var refresh = document.getElementById('svcOvRefresh');
    if (refresh) refresh.addEventListener('click', function () { _showServiceOverview(sel); });

    if (!svc) {
      var act = document.getElementById('svcOvActions');
      if (act) {
        act.innerHTML =
          '<p class="text-muted small mb-2">Registry services are invoked through the legacy explorer.</p>' +
          '<button type="button" class="btn btn-sm btn-primary" id="svcOvLegacy">' +
          '<i class="bi bi-diagram-3 me-1"></i>Open explorer</button>';
        var b = document.getElementById('svcOvLegacy');
        if (b) b.addEventListener('click', function () { showServiceAPIExplorer(sel.name); });
      }
      return;
    }

    _renderOverviewInstances(svc);
    _renderOverviewActions(svc);
  }

  function _worstCheck(checks) {
    var worst = 'passing';
    (checks || []).forEach(function (c) {
      if (c.Status === 'critical') worst = 'critical';
      else if (c.Status === 'warning' && worst !== 'critical') worst = 'warning';
    });
    return worst;
  }

  function _renderOverviewInstances(svc) {
    var el = document.getElementById('svcOvInstances');
    if (!el) return;
    MM.consulClient.getServiceDetail(svc.name, svc.consulUrl)
      .then(function (entries) {
        if (!Array.isArray(entries) || entries.length === 0) {
          el.innerHTML = '<span class="text-muted small">No instances registered.</span>';
          return;
        }
        var rows = entries.map(function (e) {
          var s = e.Service || {};
          var worst = _worstCheck(e.Checks);
          var checks = (e.Checks || []).map(function (c) {
            return '<span class="svc-ov-check svc-ov-check-' + _escapeHtml(c.Status || 'unknown') + '"' +
                   ' title="' + _escapeHtml((c.Name || '') + (c.Output ? ': ' + c.Output : '')) + '">' +
                   _escapeHtml(c.Name || c.CheckID || 'check') + '</span>';
          }).join('');
          return '<tr>' +
                 '<td><span class="svc-ov-dot svc-ov-dot-' + worst + '"></span>' + _escapeHtml(s.ID || '') + '</td>' +
                 '<td><code>' + _escapeHtml((s.Address || '?') + ':' + (s.Port || '?')) + '</code></td>' +
                 '<td>' + _escapeHtml((e.Node && e.Node.Node) || '') + '</td>' +
                 '<td>' + checks + '</td>' +
                 '</tr>';
        }).join('');
        el.innerHTML =
          '<div class="svc-ov-table-wrap"><table class="svc-ov-table">' +
          '<thead><tr><th>Instance</th><th>Address</th><th>Node</th><th>Checks</th></tr></thead>' +
          '<tbody>' + rows + '</tbody></table></div>';
      })
      .catch(function (err) {
        el.innerHTML = _devAlert('warning', 'Could not load instances', err.message || err);
      });
  }

  // ---- Operator actions: typed forms generated from the service API -----

  function _fieldControl(id, f) {
    var t = String(f.type || '').toLowerCase();
    var repeated = f.label === 'repeated';
    if (!repeated && t === 'bool') {
      return '<div class="form-check form-switch"><input class="form-check-input op-field" type="checkbox"' +
             ' id="' + id + '" data-field="' + _escapeHtml(f.name) + '" data-kind="bool">' +
             '<label class="form-check-label small" for="' + id + '">' + _escapeHtml(f.name) + '</label></div>';
    }
    var label = '<label class="form-label op-label" for="' + id + '">' + _escapeHtml(f.name) +
                '<span class="op-type">' + _escapeHtml(t + (repeated ? '[]' : '')) + '</span></label>';
    if (!repeated && /^(u?int|s?fixed|sint|float|double)/.test(t)) {
      return '<div class="op-field-wrap">' + label +
             '<input type="number" step="any" class="form-control form-control-sm op-field" id="' + id + '"' +
             ' data-field="' + _escapeHtml(f.name) + '" data-kind="number"></div>';
    }
    if (!repeated && (t === 'string' || t === 'bytes' || t === 'enum')) {
      return '<div class="op-field-wrap">' + label +
             '<input type="text" class="form-control form-control-sm op-field" id="' + id + '"' +
             ' data-field="' + _escapeHtml(f.name) + '" data-kind="string"></div>';
    }
    return '<div class="op-field-wrap">' + label +
           '<textarea class="form-control form-control-sm op-field op-json" rows="3" id="' + id + '"' +
           ' data-field="' + _escapeHtml(f.name) + '" data-kind="json" placeholder="JSON"></textarea></div>';
  }

  function _collectArgs(form) {
    var args = {};
    var bad = null;
    form.querySelectorAll('.op-field').forEach(function (inp) {
      var name = inp.getAttribute('data-field');
      var kind = inp.getAttribute('data-kind');
      if (kind === 'bool') { args[name] = !!inp.checked; return; }
      var v = inp.value;
      if (v === '' || v === null) return;
      if (kind === 'number') { args[name] = Number(v); return; }
      if (kind === 'json') {
        try { args[name] = JSON.parse(v); } catch (e) { bad = name + ': ' + e.message; }
        return;
      }
      args[name] = v;
    });
    if (bad) throw new Error('Invalid JSON in ' + bad);
    return args;
  }

  function _renderOverviewActions(svc) {
    var el = document.getElementById('svcOvActions');
    if (!el) return;
    var protoPath = _getStoredProtoPath(svc.name);
    MM.grpcClient.getServiceMethods(svc.name, svc.consulUrl, protoPath)
      .then(function (data) {
        if (!data || data.error || !(data.grpc_services || []).length) {
          el.innerHTML = _devAlert('warning', 'No actions available',
            (data && data.error) || 'The service exposes no callable methods.');
          return;
        }
        var html = '';
        data.grpc_services.forEach(function (s, si) {
          if (s.error) { html += _devAlert('warning', s.name, s.error); return; }
          (s.methods || []).forEach(function (m, mi) {
            var id = 'op_' + si + '_' + mi;
            var clientStream = !!m.client_streaming;
            var fields = (m.input_fields || []).map(function (f, fi) {
              return _fieldControl(id + '_f' + fi, f);
            }).join('');
            html +=
              '<form class="op-action" id="' + id + '" data-grpc-svc="' + _escapeHtml(s.name) + '"' +
              '      data-method="' + _escapeHtml(m.name) + '" data-stream="' + (m.server_streaming ? '1' : '') + '">' +
              '  <div class="op-action-head">' +
              '    <span class="op-action-name">' + _escapeHtml(m.name) + '</span>' +
              '    <span class="op-action-sig">' + _escapeHtml(m.input_type) + ' \u2192 ' + _escapeHtml(m.output_type) + '</span>' +
              (m.server_streaming ? '<span class="dev-stream dev-stream-server">server stream</span>' : '') +
              (clientStream ? '<span class="dev-stream dev-stream-client">client stream</span>' : '') +
              '  </div>' +
              (fields ? '<div class="op-fields">' + fields + '</div>' : '<div class="op-fields op-fields-empty">No input required.</div>') +
              '  <div class="op-run-row">' +
              '    <button type="submit" class="btn btn-sm btn-primary"' + (clientStream ? ' disabled' : '') + '>' +
              '      <i class="bi bi-play-fill me-1"></i>' + (m.server_streaming ? 'Collect' : 'Run') + '</button>' +
              (clientStream ? '<span class="dev-hint">Client-streaming calls need a custom client.</span>' : '') +
              '  </div>' +
              '  <div class="op-result" hidden></div>' +
              '</form>';
          });
        });
        el.innerHTML = html || '<span class="text-muted small">No methods.</span>';

        el.querySelectorAll('.op-action').forEach(function (form) {
          form.addEventListener('submit', function (e) {
            e.preventDefault();
            var result = form.querySelector('.op-result');
            var btn = form.querySelector('button[type="submit"]');
            var args;
            try { args = _collectArgs(form); }
            catch (err) {
              result.hidden = false;
              result.className = 'op-result op-result-error';
              result.textContent = err.message;
              return;
            }
            result.hidden = false;
            result.className = 'op-result op-result-pending';
            result.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Running\u2026';
            btn.disabled = true;
            var t0 = performance.now();
            MM.grpcClient.callMethod({
              consulName: svc.name,
              consulUrl: svc.consulUrl,
              grpcService: form.getAttribute('data-grpc-svc'),
              method: form.getAttribute('data-method'),
              argsJson: JSON.stringify(args),
              protoPath: protoPath
            }).then(function (data) {
              var ms = Math.round(performance.now() - t0);
              if (!data || !data.ok) {
                result.className = 'op-result op-result-error';
                result.textContent = (data && data.error) || 'Call failed';
                return;
              }
              var payload = data.streaming ? (data.events || []) : data.result;
              var pretty; try { pretty = JSON.stringify(payload, null, 2); } catch (e2) { pretty = String(payload); }
              result.className = 'op-result op-result-ok';
              result.innerHTML =
                '<div class="op-result-meta"><span class="op-result-ok-label">Done</span> ' + ms + ' ms' +
                (data.streaming ? ' \u00b7 ' + (data.events || []).length + ' event(s)' : '') + '</div>' +
                '<pre class="op-result-body">' + _escapeHtml(pretty) + '</pre>';
            }).catch(function (err) {
              result.className = 'op-result op-result-error';
              result.textContent = err.message || String(err);
            }).finally(function () { btn.disabled = false; });
          });
        });
      })
      .catch(function (err) {
        el.innerHTML = _devAlert('warning', 'Could not discover actions', err.message || err);
      });
  }

  /**
   * Render the method panel for a selected service in #serviceContent.
   *
   * Fetches the method list via GET /api/grpc/services/{name} and builds
   * an accordion: one item per gRPC method, each with a JSON textarea
   * pre-filled from the reflected schema, a Call button, and a response
   * display area below.
   */
  function _showGrpcServicePanel(svc, opts) {
    opts = opts || {};
    var content = document.getElementById(opts.containerId || 'serviceContent');
    if (!content) return;

    var status = svc.status || { kind: 'unknown', label: 'unknown' };
    var target = (svc.address || '?') + ':' + (svc.port || '?');
    var tags = (svc.tags || []).map(function (t) {
      return '<span class="dev-tag">' + _escapeHtml(t) + '</span>';
    }).join('');

    var toolbarHtml =
      '      <div class="dev-toolbar">' +
      '        <button type="button" class="btn btn-sm btn-outline-secondary" id="grpcRefresh"' +
      '                title="Re-discover methods"><i class="bi bi-arrow-clockwise"></i></button>' +
      '        <button type="button" class="btn btn-sm btn-outline-secondary" id="grpcCodeExamples"' +
      '                title="Client code for this service (Python / C++ / Robot)">' +
      '          <i class="bi bi-file-earmark-code me-1"></i>Code</button>' +
      '        <button type="button" class="btn btn-sm btn-outline-secondary" id="grpcGenRobotTop"' +
      '                title="Generate one Robot Framework .resource per service from a .proto folder">' +
      '          <i class="bi bi-robot me-1"></i>Robot</button>' +
      '        <button type="button" class="btn btn-sm btn-outline-primary" id="grpcAddToProject"' +
      '                title="Export this service\'s Robot resources, protos and a starter suite into the open test project">' +
      '          <i class="bi bi-box-arrow-in-down me-1"></i>Add to test project</button>' +
      '      </div>';

    // Compact: inside the inspector, which already shows the service
    // header; only the toolbar and the method list are rendered.
    content.innerHTML = opts.compact
      ? '<div class="dev-panel dev-panel-compact" data-dev-panel="api-explorer">' +
        '  <div class="dev-compact-bar"><span class="dev-discovery" id="grpcDiscovery"></span>' + toolbarHtml + '</div>' +
        '  <div id="grpcMethodList">' + _devLoading('Discovering methods\u2026') + '</div>' +
        '</div>'
      : '<div class="dev-panel" data-dev-panel="api-explorer">' +
      '  <div class="dev-header">' +
      '    <div class="dev-breadcrumb">' +
      '      <i class="bi bi-code-slash me-1"></i>Developer Tools' +
      '      <span class="dev-breadcrumb-sep">/</span>API Explorer' +
      '    </div>' +
      '    <div class="dev-title-row">' +
      '      <span class="svc-status svc-status-' + _escapeHtml(status.kind) + '"' +
      '            title="' + _escapeHtml(status.label) + '"></span>' +
      '      <h4 class="dev-title">' + _escapeHtml(svc.name) + '</h4>' +
      '      <code class="dev-target" id="grpcTarget" title="Copy address">' + _escapeHtml(target) + '</code>' +
             tags +
      '      <span class="dev-discovery" id="grpcDiscovery"></span>' +
             toolbarHtml +
      '    </div>' +
      '    <p class="dev-subtitle">' +
      '      Methods are discovered through gRPC server reflection, or by compiling local ' +
      '      <code>.proto</code> files when the server ships none (<code>MB_PROTO_SEARCH_PATH</code>).' +
      '    </p>' +
      '  </div>' +
      '  <div id="grpcMethodList">' +
           _devLoading('Discovering methods on ' + _escapeHtml(svc.name) + '\u2026') +
      '  </div>' +
      '</div>';

    // Per-service proto path (typed by the user when reflection +
    // MB_PROTO_SEARCH_PATH both fail).  Persisted in sessionStorage so
    // it survives sidebar navigation but not a full reload.
    svc.protoPath = _getStoredProtoPath(svc.name);

    var targetEl = document.getElementById('grpcTarget');
    if (targetEl) targetEl.addEventListener('click', function () { _copyText(target, 'Address'); });
    var refresh = document.getElementById('grpcRefresh');
    if (refresh) refresh.addEventListener('click', function () { _showGrpcServicePanel(svc, opts); });
    var examples = document.getElementById('grpcCodeExamples');
    if (examples) {
      examples.addEventListener('click', function () {
        if (opts.compact) _setInspectorTab('code');
        else showServiceHelper(svc.name + '@' + (svc.consulUrl || ''));
      });
    }
    // Robot generation needs a proto folder; _runRobotGen prompts for one
    // when svc.protoPath is unset.
    var genTop = document.getElementById('grpcGenRobotTop');
    if (genTop) {
      genTop.addEventListener('click', function () { _runRobotGen(svc.protoPath || '', genTop); });
    }
    var addToProject = document.getElementById('grpcAddToProject');
    if (addToProject) {
      addToProject.addEventListener('click', function () {
        exportToTestProject({ name: svc.name, infoKey: svc.name + '@' + (svc.consulUrl || ''),
                              consul: svc, info: null });
      });
    }

    MM.grpcClient.getServiceMethods(svc.name, svc.consulUrl, svc.protoPath)
      .then(function (data) { _renderGrpcMethods(svc, data); })
      .catch(function (err) {
        var list = document.getElementById('grpcMethodList');
        if (list) {
          list.innerHTML =
            _devAlert('danger', 'Failed to load methods', err.message || err) +
            _renderProtoPathForm(svc);
          _wireProtoPathForm(svc);
        }
      });
  }

  // ---- Developer-view helpers -------------------------------------------

  function _devLoading(text) {
    return '<div class="dev-loading"><span class="spinner-border spinner-border-sm me-2"></span>' +
           text + '</div>';
  }

  function _devAlert(kind, title, detail) {
    return '<div class="dev-alert dev-alert-' + kind + '">' +
           '<strong>' + _escapeHtml(title) + '</strong>' +
           (detail ? '<div>' + _escapeHtml(String(detail)) + '</div>' : '') +
           '</div>';
  }

  function _copyText(text, label) {
    function done() { showToast(label || 'Copied', 'Copied to clipboard.', 'success'); }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e) { /* best effort */ }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallback(); done(); });
    } else {
      fallback();
      done();
    }
  }

  // ---- Proto-path override (for servers without gRPC reflection) -----

  function _protoPathStorageKey(consulName) {
    return 'mm_proto_path_' + consulName;
  }
  function _getStoredProtoPath(consulName) {
    try { return sessionStorage.getItem(_protoPathStorageKey(consulName)) || ''; }
    catch (e) { return ''; }
  }
  function _setStoredProtoPath(consulName, value) {
    try {
      if (value) sessionStorage.setItem(_protoPathStorageKey(consulName), value);
      else       sessionStorage.removeItem(_protoPathStorageKey(consulName));
    } catch (e) { /* private mode etc. */ }
  }

  /**
   * Render an inline form letting the user supply a folder containing
   * the service's .proto file, used as an extra search path for the
   * bridge's LocalProtoClient fallback when reflection + the env var
   * search paths both came up empty.
   *
   * Returned as an HTML fragment; caller is responsible for injecting
   * it into the DOM and then calling _wireProtoPathForm(svc).
   */
  function _renderProtoPathForm(svc) {
    var current = _getStoredProtoPath(svc.name);
    return '' +
      '<div class="card mt-3 mb-2">' +
      '  <div class="card-body py-3">' +
      '    <div class="mb-2">' +
      '      <i class="bi bi-folder2-open me-1"></i>' +
      '      <strong>Provide a <code>.proto</code> folder</strong>' +
      '    </div>' +
      '    <p class="small text-muted mb-2">' +
      '      The bridge will compile every <code>*.proto</code> under this folder ' +
      '      (recursively) and use the result to discover + invoke methods on ' +
      '      this service.  Persisted for the rest of this browser session.' +
      '    </p>' +
      '    <div class="input-group input-group-sm">' +
      '      <span class="input-group-text"><i class="bi bi-folder me-1"></i>Folder path</span>' +
      '      <input type="text" class="form-control" id="grpcProtoPathInput"' +
      '             value="' + _escapeHtml(current) + '"' +
      '             placeholder="e.g. D:\\Project\\.\\examples\\PowerDeviceService\\proto"' +
      '             spellcheck="false">' +
      '      <button class="btn btn-primary" id="grpcProtoPathApply" type="button">' +
      '        <i class="bi bi-arrow-repeat me-1"></i>Use this path' +
      '      </button>' +
      '      <button class="btn btn-outline-secondary" id="grpcProtoPathClear" type="button"' +
      (current ? '' : ' disabled') + '>' +
      '        Clear' +
      '      </button>' +
      '      <button class="btn btn-outline-success" id="grpcProtoGenRobot" type="button"' +
      '              title="Generate Robot Framework resource files (one per service) from this .proto folder">' +
      '        <i class="bi bi-file-earmark-code me-1"></i>Generate Robot resources' +
      '      </button>' +
      '    </div>' +
      '    <p class="small text-muted mt-2 mb-0">' +
      '      Tip: a permanent fix is either rebuilding the server with ' +
      '      <code>grpc++_reflection</code> linked, or setting ' +
      '      <code>MB_PROTO_SEARCH_PATH</code> in the bridge environment.' +
      '      <br>' +
      '      <i class="bi bi-info-circle me-1"></i>' +
      '      <em>Generate Robot resources</em>: emits one ' +
      '      <code>.resource</code> file per service into a folder you pick &mdash; ' +
      '      each contains typed Robot keywords (one per RPC) that wrap ' +
      '      <code>QConnectBase.ConnectionManager</code>.' +
      '    </p>' +
      '  </div>' +
      '</div>';
  }

  function _wireProtoPathForm(svc) {
    var input = document.getElementById('grpcProtoPathInput');
    var apply = document.getElementById('grpcProtoPathApply');
    var clear = document.getElementById('grpcProtoPathClear');
    if (!input || !apply) return;

    function submit(value) {
      _setStoredProtoPath(svc.name, value);
      svc.protoPath = value;
      // Re-render with a spinner, then re-fetch.
      var target = document.getElementById('grpcMethodList');
      if (target) {
        target.innerHTML =
          '<div class="text-muted small">' +
          '  <span class="spinner-border spinner-border-sm me-2"></span>' +
          '  Re-discovering methods using ' + _escapeHtml(value || '(default search paths)') + '...' +
          '</div>';
      }
      MM.grpcClient.getServiceMethods(svc.name, svc.consulUrl, value)
        .then(function (data) { _renderGrpcMethods(svc, data); })
        .catch(function (err) {
          var t = document.getElementById('grpcMethodList');
          if (t) {
            t.innerHTML =
              '<div class="alert alert-danger">' +
              '  <strong>Still failed:</strong> ' +
              _escapeHtml(err.message || err) +
              '</div>' +
              _renderProtoPathForm(svc);
            _wireProtoPathForm(svc);
          }
        });
    }

    apply.addEventListener('click', function () { submit(input.value.trim()); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submit(input.value.trim()); }
    });
    if (clear) {
      clear.addEventListener('click', function () {
        input.value = '';
        submit('');
      });
    }

    var genRobot = document.getElementById('grpcProtoGenRobot');
    if (genRobot) {
      genRobot.addEventListener('click', function () {
        _runRobotGen(input.value.trim(), genRobot);
      });
    }
  }

  // Shared by both entry points (fallback-card button + methods-panel
  // toolbar button).  Uses Electron's native dialogs when available —
  // renderer-side window.prompt() / window.confirm() are disabled by
  // default in Electron (they return null/false silently with no UI),
  // which is exactly the "I click but nothing happens" failure mode.
  // Falls back to the browser dialogs in non-Electron mode.
  function _runRobotGen(protoDir, btn) {
    var isElectron = !!(window.electronAPI && window.electronAPI.showOpenDialog);

    function pickProtoDir() {
      if (protoDir) return Promise.resolve(protoDir);
      if (isElectron) {
        return window.electronAPI.showOpenDialog({
          title: 'Pick the .proto folder to scan',
          properties: ['openDirectory']
        }).then(function (res) {
          return ((res && res.filePaths && res.filePaths[0]) || '').trim();
        });
      }
      return Promise.resolve((window.prompt(
        'Proto folder to scan (one .resource per service will be emitted):',
        ''
      ) || '').trim());
    }

    function pickOutDir(resolvedProtoDir) {
      var sep = resolvedProtoDir.indexOf('\\') >= 0 ? '\\' : '/';
      var parts = resolvedProtoDir.split(sep);
      if (parts[parts.length - 1].toLowerCase() === 'proto') parts.pop();
      var suggested = parts.join(sep) + sep + 'robot';

      if (isElectron) {
        return window.electronAPI.showOpenDialog({
          title: 'Pick the output folder for the .resource files',
          defaultPath: suggested,
          properties: ['openDirectory', 'createDirectory']
        }).then(function (res) {
          return ((res && res.filePaths && res.filePaths[0]) || '').trim();
        });
      }
      return Promise.resolve((window.prompt(
        'Output folder for the generated .resource files:\n' +
        '(one .resource per service; existing files are skipped unless you confirm overwrite)',
        suggested
      ) || '').trim());
    }

    function confirmOverwrite(nSkipped, outDir) {
      if (isElectron && window.electronAPI.showMessageBox) {
        return window.electronAPI.showMessageBox({
          type: 'question',
          title: 'Files already exist',
          message: nSkipped + ' .resource file(s) already exist in ' + outDir,
          detail: 'Overwrite them with the freshly generated content?',
          buttons: ['Overwrite', 'Cancel'],
          defaultId: 1, cancelId: 1
        }).then(function (res) { return (res && res.response === 0); });
      }
      return Promise.resolve(window.confirm(
        nSkipped + ' file(s) already exist in ' + outDir + '.  Overwrite them?'));
    }

    // Resolve the bridge origin.  In Electron mode MM.serviceClient.apiUrl
    // is `file://...` (truthy but unfetchable); fall back to localhost:<bridgePort>.
    // Matches the pattern used by ServiceCreator / ConsulClient / etc.
    var apiUrl = (MM.serviceClient && MM.serviceClient.apiUrl) || '';
    if (!apiUrl || apiUrl === 'null' ||
        apiUrl.indexOf('file:') === 0 ||
        apiUrl.indexOf('http') !== 0) {
      var settings2 = MM.getSettings ? MM.getSettings() : {};
      var bridgePort = settings2.bridgePort || 1112;
      apiUrl = 'http://localhost:' + bridgePort;
    }
    var bridgeOrigin = apiUrl;
    var originalHtml = btn ? btn.innerHTML : null;

    function send(resolvedProtoDir, outDir, forceFlag) {
      if (btn) {
        btn.disabled = true;
        btn.innerHTML =
          '<span class="spinner-border spinner-border-sm me-1"></span>Generating...';
      }
      return fetch(bridgeOrigin + '/api/scaffold/robot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proto_dir: resolvedProtoDir, out_dir: outDir, force: forceFlag
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status !== 'ok') {
            MM.showToast('Robot generator',
              data.error || 'Generation failed.', 'danger');
            return;
          }
          var nW = (data.written || []).length;
          var nS = (data.skipped || []).length;
          if (nS && !nW) {
            return confirmOverwrite(nS, outDir).then(function (ok) {
              if (ok) return send(resolvedProtoDir, outDir, true);
              MM.showToast('Robot generator',
                'No files written (existing files skipped).', 'warning');
            });
          }
          var msg = 'Wrote ' + nW + ' .resource file(s) to ' + outDir +
                    (nS ? ' (' + nS + ' skipped)' : '');
          MM.showToast('Robot generator', msg, 'success');
        })
        .catch(function (err) {
          MM.showToast('Robot generator',
            'Failed: ' + (err.message || err), 'danger');
        })
        .finally(function () {
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
          }
        });
    }

    pickProtoDir().then(function (resolvedProtoDir) {
      if (!resolvedProtoDir) return;
      pickOutDir(resolvedProtoDir).then(function (outDir) {
        if (!outDir) return;
        send(resolvedProtoDir, outDir, false);
      });
    });
  }

  function _renderGrpcMethods(svc, data) {
    var target = document.getElementById('grpcMethodList');
    if (!target) return;

    var src = (data && data.discovery_source) || '';
    var localProto = src.indexOf('local_proto:') === 0;
    var protoDirs = localProto ? src.substring('local_proto:'.length) : '';

    // Discovery source shown as a badge in the header, not as a banner.
    var discovery = document.getElementById('grpcDiscovery');
    if (discovery) {
      discovery.innerHTML = localProto
        ? '<i class="bi bi-file-earmark-text me-1"></i>local .proto'
        : (src || (data && data.grpc_services) ? '<i class="bi bi-broadcast me-1"></i>reflection' : '');
      discovery.title = localProto
        ? 'Server ships no reflection; methods compiled from ' + protoDirs
        : 'Discovered through gRPC server reflection';
    }

    if (data && data.error) {
      // Reflection failed AND the bridge's local-proto fallback found
      // nothing.  Render the proto-path input so the user can point us
      // at the right folder without restarting the bridge.
      var needsProtoPath = /Reflection unavailable|no \.proto files matched/i.test(data.error);
      target.innerHTML =
        _devAlert('danger', 'Method discovery failed', data.error) +
        (needsProtoPath ? _renderProtoPathForm(svc) : '');
      if (needsProtoPath) _wireProtoPathForm(svc);
      return;
    }

    var services = (data && data.grpc_services) || [];
    if (services.length === 0) {
      target.innerHTML = _devAlert('warning', 'No gRPC services found',
        'Nothing is exposed at ' + ((data && data.target) || 'the target') + '.');
      return;
    }

    var html = '';
    if (localProto) {
      html += '<div class="dev-note">' +
              '  <i class="bi bi-info-circle me-1"></i>' +
              '  Reflection is not available on this server; methods were compiled from ' +
              '  <code>' + _escapeHtml(protoDirs) + '</code>. ' +
              '  <a href="#" id="grpcShowProtoForm">Use a different .proto folder</a>' +
              '</div>' +
              '<div id="grpcProtoFormSlot"></div>';
    }

    services.forEach(function (s, si) {
      if (s.error) {
        html += _devAlert('warning', s.name, s.error);
        return;
      }
      var methods = s.methods || [];
      html += '<section class="dev-card">' +
              '  <header class="dev-card-header">' +
              '    <i class="bi bi-diagram-3 me-2"></i>' +
              '    <code class="dev-card-title">' + _escapeHtml(s.name) + '</code>' +
              '    <span class="dev-card-count">' + methods.length + ' method' +
                   (methods.length === 1 ? '' : 's') + '</span>' +
              '  </header>' +
              '  <div class="accordion dev-methods" id="grpcAcc_' + si + '">';

      methods.forEach(function (m, mi) {
        var itemId = 'grpcMethod_' + si + '_' + mi;
        var bodyId = itemId + '_body';
        var textareaId = itemId + '_json';
        var resultId = itemId + '_result';

        var streamKind = (m.client_streaming && m.server_streaming) ? 'bidi'
                       : m.client_streaming ? 'client'
                       : m.server_streaming ? 'server' : 'unary';
        var streamBadge = '<span class="dev-stream dev-stream-' + streamKind + '">' +
                          (streamKind === 'unary' ? 'unary' : streamKind + ' stream') + '</span>';

        var skeleton = '{}';
        try { skeleton = JSON.stringify(m.input_skeleton || {}, null, 2); } catch (e) { /* keep {} */ }
        _grpcSkeletons[textareaId] = skeleton;

        var fieldsHtml = (m.input_fields || []).map(function (f) {
          var repeat = (f.label === 'repeated') ? '[]' : '';
          return '<span class="dev-field">' +
                 '<span class="dev-field-name">' + _escapeHtml(f.name) + '</span>' +
                 '<span class="dev-field-type">' + _escapeHtml(f.type + repeat) + '</span>' +
                 '</span>';
        }).join('');

        // Client/bidi streaming cannot be driven from a single textarea.
        // Server streaming is collected bridge-side and returned when the
        // stream ends.
        var unsupported = !!m.client_streaming;
        var btnLabel = m.server_streaming ? 'Collect stream' : 'Call';

        html +=
          '<div class="accordion-item dev-method">' +
          '  <h2 class="accordion-header">' +
          '    <button class="accordion-button collapsed" type="button"' +
          '            data-bs-toggle="collapse" data-bs-target="#' + bodyId + '">' +
          '      <code class="dev-method-name">' + _escapeHtml(m.name) + '</code>' +
          '      <span class="dev-method-sig">' + _escapeHtml(m.input_type) +
          '        <i class="bi bi-arrow-right mx-1"></i>' + _escapeHtml(m.output_type) + '</span>' +
                 streamBadge +
          '    </button>' +
          '  </h2>' +
          '  <div id="' + bodyId + '" class="accordion-collapse collapse" data-bs-parent="#grpcAcc_' + si + '">' +
          '    <div class="accordion-body dev-method-body">' +
          '      <div class="dev-block-label">Request' +
          (fieldsHtml ? '<span class="dev-fields">' + fieldsHtml + '</span>' : '') +
          '      </div>' +
          '      <textarea id="' + textareaId + '" class="dev-json" rows="8" spellcheck="false">' +
                   _escapeHtml(skeleton) + '</textarea>' +
          '      <div class="dev-req-toolbar">' +
          '        <button type="button" class="btn btn-sm btn-primary grpc-call-btn"' +
          (unsupported ? ' disabled title="Client-streaming RPCs cannot be called from the explorer"' : '') +
          '                data-svc="' + _escapeHtml(svc.name) + '"' +
          '                data-consul-url="' + _escapeHtml(svc.consulUrl || '') + '"' +
          '                data-grpc-svc="' + _escapeHtml(s.name) + '"' +
          '                data-method="' + _escapeHtml(m.name) + '"' +
          '                data-textarea="' + textareaId + '"' +
          '                data-result="' + resultId + '">' +
          '          <i class="bi bi-play-fill me-1"></i>' + btnLabel + '</button>' +
          '        <button type="button" class="btn btn-sm btn-outline-secondary dev-format-btn"' +
          '                data-textarea="' + textareaId + '" title="Pretty-print the request">Format</button>' +
          '        <button type="button" class="btn btn-sm btn-outline-secondary dev-reset-btn"' +
          '                data-textarea="' + textareaId + '" title="Restore the generated skeleton">Reset</button>' +
          '        <span class="dev-hint">Ctrl+Enter to call</span>' +
          (m.server_streaming
            ? '<span class="dev-hint">collects up to 100 events or 15 s</span>'
            : '') +
          '      </div>' +
          '      <div id="' + resultId + '" class="dev-response" hidden></div>' +
          '    </div>' +
          '  </div>' +
          '</div>';
      });

      html += '  </div>' +
              '</section>';
    });

    target.innerHTML = html;

    // "Use a different .proto folder" in the local-proto note reveals the
    // same form that appears on hard failures.
    var showLink = document.getElementById('grpcShowProtoForm');
    var slot = document.getElementById('grpcProtoFormSlot');
    if (showLink && slot) {
      showLink.addEventListener('click', function (e) {
        e.preventDefault();
        if (!slot.innerHTML) {
          slot.innerHTML = _renderProtoPathForm(svc);
          _wireProtoPathForm(svc);
          showLink.style.display = 'none';
        }
      });
    }

    target.querySelectorAll('.dev-format-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var ta = document.getElementById(b.getAttribute('data-textarea'));
        if (!ta) return;
        try {
          ta.value = JSON.stringify(JSON.parse(ta.value || '{}'), null, 2);
          ta.classList.remove('is-invalid');
        } catch (e) {
          ta.classList.add('is-invalid');
          showToast('Request', 'Not valid JSON: ' + e.message, 'warning');
        }
      });
    });
    target.querySelectorAll('.dev-reset-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var ta = document.getElementById(b.getAttribute('data-textarea'));
        if (!ta) return;
        ta.value = _grpcSkeletons[ta.id] || '{}';
        ta.classList.remove('is-invalid');
      });
    });
    target.querySelectorAll('.dev-json').forEach(function (ta) {
      ta.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
          e.preventDefault();
          var btn = target.querySelector('.grpc-call-btn[data-textarea="' + ta.id + '"]');
          if (btn && !btn.disabled) btn.click();
        }
      });
    });
    target.querySelectorAll('.grpc-call-btn').forEach(function (btn) {
      btn.addEventListener('click', function () { _invokeGrpcMethod(svc, btn); });
    });
  }

  // Generated request skeletons, keyed by textarea id, for the Reset button.
  var _grpcSkeletons = {};

  function _invokeGrpcMethod(svc, btn) {
    var textarea = document.getElementById(btn.getAttribute('data-textarea'));
    var resultEl = document.getElementById(btn.getAttribute('data-result'));
    var method = btn.getAttribute('data-method');
    var argsJson = textarea ? textarea.value : '{}';

    // Validate locally: a malformed request should not cost a round trip.
    try {
      JSON.parse(argsJson || '{}');
      if (textarea) textarea.classList.remove('is-invalid');
    } catch (e) {
      if (textarea) textarea.classList.add('is-invalid');
      _renderGrpcResult(resultEl, { ok: false, error: 'Request is not valid JSON: ' + e.message }, method, 0);
      return;
    }

    if (resultEl) {
      resultEl.hidden = false;
      resultEl.className = 'dev-response dev-response-pending';
      resultEl.innerHTML =
        '<div class="dev-response-head"><span class="spinner-border spinner-border-sm me-2"></span>' +
        'Calling ' + _escapeHtml(method) + '\u2026</div>';
    }
    btn.disabled = true;
    var t0 = performance.now();

    MM.grpcClient.callMethod({
      consulName: btn.getAttribute('data-svc'),
      consulUrl: btn.getAttribute('data-consul-url') || '',
      grpcService: btn.getAttribute('data-grpc-svc'),
      method: method,
      argsJson: argsJson,
      // svc.protoPath is set by _showGrpcServicePanel from sessionStorage;
      // falsy when reflection works server-side.
      protoPath: svc && svc.protoPath ? svc.protoPath : ''
    }).then(function (data) {
      _renderGrpcResult(resultEl, data, method, performance.now() - t0);
    }).catch(function (err) {
      _renderGrpcResult(resultEl, { ok: false, error: err.message || String(err) }, method, performance.now() - t0);
    }).finally(function () {
      btn.disabled = false;
    });
  }

  function _renderGrpcResult(resultEl, data, method, elapsedMs) {
    if (!resultEl) return;
    var ok = !!(data && data.ok);
    var kind = ok ? 'ok' : 'error';
    var bodyText = '';
    var extra = '';

    if (ok && data.streaming) {
      var events = data.events || [];
      if (events.length === 0) kind = 'warn';
      bodyText = events.map(function (ev, i) {
        var pretty;
        try { pretty = JSON.stringify(ev, null, 2); } catch (e) { pretty = String(ev); }
        return '// event #' + i + '\n' + pretty;
      }).join('\n');
      extra = events.length + ' event' + (events.length === 1 ? '' : 's') +
              (data.truncated ? ' (truncated)' : '');
      if (data.error) extra += ' \u00b7 stream error: ' + data.error;
    } else if (ok) {
      try { bodyText = JSON.stringify(data.result, null, 2); } catch (e) { bodyText = String(data.result); }
    } else {
      bodyText = (data && data.error) || 'Unknown error';
    }

    var meta = _escapeHtml(method) + ' \u00b7 ' + Math.round(elapsedMs) + ' ms \u00b7 ' +
               _escapeHtml(new Date().toLocaleTimeString()) +
               (extra ? ' \u00b7 ' + _escapeHtml(extra) : '');

    resultEl.hidden = false;
    resultEl.className = 'dev-response dev-response-' + kind;
    resultEl.innerHTML =
      '<div class="dev-response-head">' +
      '  <span class="dev-response-status">' + (ok ? 'OK' : 'ERROR') + '</span>' +
      '  <span class="dev-response-meta">' + meta + '</span>' +
      '  <button type="button" class="btn btn-sm btn-link dev-copy-btn" title="Copy response">' +
      '    <i class="bi bi-clipboard"></i></button>' +
      '</div>' +
      '<pre class="dev-response-body">' + _escapeHtml(bodyText) + '</pre>';
    var copy = resultEl.querySelector('.dev-copy-btn');
    if (copy) copy.addEventListener('click', function () { _copyText(bodyText, 'Response'); });
  }

  function _escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Render the initial empty sidebar state + any chips from localStorage.
  _renderAllConnectedConsuls();

  // Expose the multi-Consul connection list so other modules (notably
  // ConsulDashboard) can check whether any Consul is already connected
  // without needing to duplicate the state machine.
  MM.getConnectedConsuls = function () {
    return _connectedConsuls.slice();   // defensive copy
  };

  // --------------------------------------------------------------------
  // Periodic refresh of connected Consuls
  // --------------------------------------------------------------------
  //
  // Each connection is re-probed every 10 seconds so chips and sidebar
  // groups reflect the live state:
  //   - If a Consul becomes unreachable (agent killed, bridge down),
  //     the chip + sidebar group fade to gray and show "unreachable".
  //   - If services come and go, the sidebar rows appear/disappear
  //     without a manual refresh.
  //   - Auto-recovers when a down Consul comes back.

  var CONSUL_POLL_INTERVAL_MS = 10000;
  var _consulPollTimer = null;

  function _sameServices(a, b) {
    // Quick deep-equal for the list of service summaries we render.
    if (!Array.isArray(a) || !Array.isArray(b)) return false;
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      var x = a[i], y = b[i];
      if (!x || !y) return false;
      if (x.name !== y.name || x.address !== y.address ||
          x.port !== y.port || x.instances !== y.instances) return false;
      // Status kind is the most likely field to change.
      var sx = (x.status && x.status.kind) || '';
      var sy = (y.status && y.status.kind) || '';
      if (sx !== sy) return false;
    }
    return true;
  }

  function _refreshConsul(conn) {
    // Re-run the same fetch used by initial connect, but tolerate
    // errors — on failure we mark the connection unreachable instead
    // of throwing.
    return _connectConsulUrl(conn.url)
      .then(function (fresh) {
        var changed = !conn.alive || conn.leader !== fresh.leader ||
                      !_sameServices(conn.services, fresh.services);
        conn.alive = true;
        conn.leader = fresh.leader;
        conn.services = fresh.services;
        delete conn.lastError;
        return changed;
      })
      .catch(function (err) {
        var wasDown = conn.alive === false;
        conn.alive = false;
        conn.lastError = (err && err.message) || String(err);
        conn.services = [];   // hide services of an unreachable cluster
        return !wasDown;  // changed if it was previously up
      });
  }

  function _pollConnectedConsuls() {
    if (_connectedConsuls.length === 0) return;
    Promise.all(_connectedConsuls.map(_refreshConsul))
      .then(function (flags) {
        if (flags.some(Boolean)) {
          _renderConsulChips();
          _renderAllConnectedConsuls();
        }
      });
  }

  function _startConsulPolling() {
    if (_consulPollTimer) return;
    _consulPollTimer = setInterval(_pollConnectedConsuls, CONSUL_POLL_INTERVAL_MS);
  }

  _startConsulPolling();

  // When the bridge goes down/up, poll immediately so the UI reacts
  // within a second instead of waiting up to 10s for the next tick.
  window.addEventListener('mm:bridge-state', function () {
    setTimeout(_pollConnectedConsuls, 200);
  });

  // Auto-reconnect to every Consul URL saved from a previous session.
  // Wait briefly so the bridge has time to probe first (and so polling
  // from InfraStatus doesn't race us).
  (function _autoReconnectConsuls() {
    var urls = _loadSavedConsulUrls();
    if (!urls.length) return;
    setTimeout(function () {
      urls.forEach(function (url) {
        // Skip duplicates (in case user also had connections pending)
        if (_connectedConsuls.find(function (c) { return c.url === url; })) return;
        _connectConsulUrl(url)
          .then(function (conn) {
            conn.alive = true;
            _connectedConsuls.push(conn);
            _renderConsulChips();
            _renderAllConnectedConsuls();
          })
          .catch(function (err) {
            // Still add a placeholder entry marked unreachable so the
            // chip is visible; the poll will recover it if Consul
            // comes back.
            _connectedConsuls.push({
              url: url,
              leader: '',
              services: [],
              alive: false,
              lastError: (err && err.message) || String(err)
            });
            _renderConsulChips();
            _renderAllConnectedConsuls();
            console.warn('[app] Consul auto-reconnect failed for', url, err);
          });
      });
    }, 1500);
  })();

  document.getElementById('btnLoginSubmit').addEventListener('click', function () {
    onLoginSubmit();
  });

  // Sidebar search filter — traverses 3-level hierarchy (broker > group > service)
  document.getElementById('searchText').addEventListener('input', function () {
    var query = this.value.toLowerCase().trim();
    var brokerSections = document.querySelectorAll('#' + DIV_NAME.SERVICE_LIST_DIV + ' > .broker-section');

    // If no broker sections exist yet (legacy/empty state), fall back to old behavior
    if (brokerSections.length === 0) {
      var accordionItems = document.querySelectorAll('#' + DIV_NAME.SERVICE_LIST_DIV + ' > .accordion-item');
      accordionItems.forEach(function (section) {
        var listItems = section.querySelectorAll('.list-group-item');
        var visibleCount = 0;
        listItems.forEach(function (item) {
          var serviceName = (item.getAttribute('data-service-name') || '').toLowerCase();
          var label = (item.textContent || '').toLowerCase();
          var match = query === '' || serviceName.indexOf(query) !== -1 || label.indexOf(query) !== -1;
          item.style.display = match ? '' : 'none';
          if (match) visibleCount++;
        });
        section.style.display = visibleCount > 0 ? '' : 'none';
        if (query !== '' && visibleCount > 0) {
          var collapse = section.querySelector('.accordion-collapse');
          if (collapse && !collapse.classList.contains('show')) collapse.classList.add('show');
        }
      });
      return;
    }

    brokerSections.forEach(function (brokerSection) {
      var brokerVisibleCount = 0;
      var groups = brokerSection.querySelectorAll('.accordion-item');

      groups.forEach(function (group) {
        var listItems = group.querySelectorAll('.list-group-item');
        var groupVisibleCount = 0;

        listItems.forEach(function (item) {
          var serviceName = (item.getAttribute('data-service-name') || '').toLowerCase();
          var label = (item.textContent || '').toLowerCase();
          var match = query === '' || serviceName.indexOf(query) !== -1 || label.indexOf(query) !== -1;
          item.style.display = match ? '' : 'none';
          if (match) groupVisibleCount++;
        });

        group.style.display = groupVisibleCount > 0 ? '' : 'none';
        brokerVisibleCount += groupVisibleCount;

        // Auto-expand groups that have matches when searching
        if (query !== '' && groupVisibleCount > 0) {
          var collapse = group.querySelector('.accordion-collapse');
          if (collapse && !collapse.classList.contains('show')) collapse.classList.add('show');
        }
      });

      // Hide entire broker section if no items match
      brokerSection.style.display = brokerVisibleCount > 0 ? '' : 'none';
    });
  });

  // Restore saved connections on startup. Each source is attempted
  // independently: one that is down is shown offline and does not stop
  // the others from coming up.
  try {
    var savedConnections = loadPersistedConnections();
    if (savedConnections.length > 0) {
      console.log('[app] Restoring', savedConnections.length, 'saved connection(s)...');
      savedConnections.forEach(function (saved) {
        if (MM.connections[saved.brokerUrl]) return; // skip duplicates
        addConnection(saved.brokerUrl, saved.routingKey);
        addAliasServiceForBroker(saved.brokerUrl, saved.routingKey);
        requestServicesInforForBroker(saved.brokerUrl, { restored: true });
      });
      updateBrokerHeaders();
    }
  } catch (e) { /* storage unavailable */ }

  /************************************************************
   *          Functions: Logic and Interaction with Services   *
   ************************************************************/

  /**
   * Open the login modal to connect to the broker.
   */
  function connect() {
    if (!loginModal) {
      loginModal = new bootstrap.Modal(document.getElementById('loginModal'));
    }
    loginModal.show();
  }

  /**
   * Handle the login form submission from the modal.
   */
  function onLoginSubmit() {
    var brokerUrl = document.getElementById('brokerUrlInput').value.trim();
    var routingKey = document.getElementById('routingKeyInput').value.trim();

    if (!brokerUrl) {
      showToast('Validation Error', 'Broker URL is required.', 'danger');
      return;
    }

    if (loginModal) {
      loginModal.hide();
    }

    // Duplicate-connection check
    if (MM.connections[brokerUrl]) {
      showToast('Already Connected', 'Already connected to ' + brokerUrl, 'warning');
      return;
    }

    // Handle fleet API URL from advanced settings
    var fleetApiUrlInput = document.getElementById('fleetApiUrlInput');
    var fleetApiUrl = fleetApiUrlInput ? fleetApiUrlInput.value.trim() : '';
    if (fleetApiUrl && MM.fleetClient) {
      MM.fleetClient.configure(fleetApiUrl)
        .then(function () {
          try { localStorage.setItem('mm_fleet_api_url', fleetApiUrl); } catch (e) {}
        })
        .catch(function (err) {
          console.warn('[app] Failed to configure fleet URL:', err);
        });
    }

    showToast('Connecting', 'Connecting to broker at ' + brokerUrl + '...', 'info');
    addConnection(brokerUrl, routingKey);
    addAliasServiceForBroker(brokerUrl, routingKey);
    requestServicesInforForBroker(brokerUrl);
    persistConnections();
    updateBrokerHeaders();
  }

  /**
   * Add the Alias service GUI entry for a specific broker.
   *
   * @param {string} brokerUrl - The broker address.
   * @param {string} routingKey - The registry routing key for this broker.
   */
  function addAliasServiceForBroker(brokerUrl, routingKey) {
    var aliasServiceData = [
      {
        title: 'Alias Manager',
        contentId: 'content-accordion-alias',
        items: [
          {
            label: 'Alias',
            iconSrc: IMAGE_PATH.READY,
            serviceName: 'ServiceAlias',
            guiSupport: true
          }
        ]
      }
    ];

    createAccordionItems(aliasServiceData, brokerUrl);
    if (!MM.servicesInfor) {
      MM.servicesInfor = {};
    }

    MM.servicesInfor.ServiceAlias = {
      description: 'Service to alias specific service api to an api name.',
      group: '',
      gui_support: true,
      methods: [],
      name: 'ServiceRegistry',
      routing_key: '',
      shortdesc: 'Alias service',
      tag: '',
      version: '1.0.0'
    };
  }

  // Backward-compat wrapper
  function addAliasService() {
    var firstBroker = Object.keys(MM.connections)[0] || MM.brokerUrl;
    var routingKey = firstBroker && MM.connections[firstBroker] ? MM.connections[firstBroker].routingKey : MM.routingKey;
    addAliasServiceForBroker(firstBroker, routingKey);
  }

  /**
   * Disconnect a single broker and remove its sidebar section.
   *
   * @param {string} brokerUrl - The broker address to disconnect.
   */
  function disconnectBroker(brokerUrl) {
    // Remove DOM section
    var servicesList = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    var section = servicesList.querySelector('.broker-section[data-broker-url="' + brokerUrl + '"]');
    if (section) {
      // If active service was on this broker, clear content panel
      var activeItem = section.querySelector('.list-group-item.active');
      if (activeItem) {
        _deactivateCurrentPanel();
        clearServiceContent();
        MM.activeBrokerUrl = null;
      }
      section.remove();
    }

    removeConnection(brokerUrl);
    updateConnectionBadge();
    persistConnections();
    updateBrokerHeaders();

    // If no connections remain, reset legacy globals
    if (getConnectionCount() === 0) {
      MM.brokerUrl = null;
      MM.routingKey = null;
      MM.servicesInfor = null;
      MM.serviceClient.disconnect();
    }
  }

  /**
   * Disconnect all brokers.
   */
  function disconnect() {
    var brokerUrls = Object.keys(MM.connections);
    brokerUrls.forEach(function (url) {
      disconnectBroker(url);
    });
    unloadFunction = null;
    clearServiceList();
    clearServiceContent();
    clearPersistedConnections();
  }

  /**
   * Set Registry Service connection info (legacy, updates active broker alias).
   *
   * @param {object} registryData - The information of the Registry Service.
   */
  function setRegistryServiceInfo(registryData) {
    MM.brokerUrl = registryData.brokerUrl;
    MM.routingKey = registryData.routingKey;
    MM.activeBrokerUrl = registryData.brokerUrl;
  }

  /**
   * Extracts and structures services information from parsed JSON data.
   *
   * @param {object} data - Parsed JSON data containing services information.
   * @returns {Array} - A structured representation of services information.
   */
  function extractServicesInformation(data) {
    var accordionData = Object.values(data).reduce(function (acc, service) {
      if (HIDDEN_SERVICES.indexOf(service.name) !== -1) return acc;
      var group = service.group || DEFAULT_GROUP;
      var existingItem = acc.find(function (item) { return item.title === group; });
      var newItem = {
        label: service.name,
        iconSrc: IMAGE_PATH.READY,
        serviceName: service.name,
        downloadable: !!service.downloadable,
        guiSupport: service.gui_support === true
      };

      if (!existingItem) {
        acc.push({
          title: group,
          contentId: 'content-' + group.replace(/ /g, '-').toLowerCase(),
          items: [newItem]
        });
      } else {
        existingItem.items.push(newItem);
      }

      return acc;
    }, []);

    console.log(accordionData);
    return accordionData;
  }

  /**
   * Check if service GUI resources exist and are up-to-date; download if needed.
   * Uses a checksum from the service to detect file changes, with a fallback
   * to simple folder-existence checks for services that lack checksum support.
   */
  function checkAndGetTheServiceGUIResources(serviceName, callbackFunc) {
    callbackFunc = callbackFunc || null;
    var serviceVersion = MM.servicesInfor[serviceName].version;
    var folderPath = SERVICES_GUI_FOLDER + '/' + serviceName + serviceVersion;
    var routingKey = MM.servicesInfor[serviceName].routing_key;

    // Local-only services (no routing key) — skip checksum, just check folder
    if (!routingKey) {
      _checkGUIFolderExists(serviceName, folderPath, callbackFunc);
      return;
    }

    // Request remote checksum, then compare against local files on disk.
    // No localStorage/sessionStorage needed — the truth is on disk.
    var checksumRequest = { method: 'svc_api_get_gui_checksum', args: null };
    requestService(checksumRequest, SERVICES_EXCHANGE_NAME, routingKey)
      .then(function (data) {
        var remoteChecksum = data.result_data;

        var _doDownload = function () {
          var onSuccess = function () { if (callbackFunc) callbackFunc(); };
          if (window.electronAPI) {
            requestServiceGUIResources(serviceName, folderPath, onSuccess);
          } else {
            requestServiceGUIResourcesBrowser(serviceName, folderPath, onSuccess);
          }
        };

        // Compute checksum from local files and compare with remote
        _computeLocalChecksum(folderPath, function (localChecksum) {
          if (localChecksum && localChecksum === remoteChecksum) {
            console.log('GUI checksum matches for', serviceName, '- using cached files');
            if (callbackFunc) callbackFunc();
          } else if (localChecksum && localChecksum !== remoteChecksum) {
            console.log('GUI checksum changed for', serviceName, '- downloading');
            _doDownload();
          } else {
            // localChecksum is null: either folder missing or checksum not
            // computable (browser mode). Check if folder exists on disk —
            // if yes, assume files are current and skip the download.
            _checkGUIFolderExists(serviceName, folderPath, callbackFunc);
          }
        });
      })
      .catch(function (error) {
        // Checksum API not available — fall back to folder existence check
        console.warn('GUI checksum not available for', serviceName, ', falling back to folder check');
        _checkGUIFolderExists(serviceName, folderPath, callbackFunc);
      });
  }

  /**
   * Lightweight folder-existence check (calls back with boolean).
   * Used by checksum logic to verify files are actually on disk.
   */
  /**
   * Compute MD5 checksum of local GUI files on disk.
   * Mirrors Python ServiceBase.svc_api_get_gui_checksum() algorithm.
   * Calls back with the hex-digest string, or null if folder doesn't exist.
   *
   * Electron: uses electronAPI.computeGuiChecksum() (Node crypto).
   * Browser:  uses SubtleCrypto (Web Crypto API).
   */
  function _computeLocalChecksum(folderPath, callback) {
    if (window.electronAPI && window.electronAPI.computeGuiChecksum) {
      window.electronAPI.computeGuiChecksum(folderPath)
        .then(function (checksum) { callback(checksum); })
        .catch(function () { callback(null); });
    } else {
      // Browser mode: fetch file list, then hash each file.
      // Requires FastAPI to serve directory listings.
      _computeLocalChecksumBrowser(folderPath, callback);
    }
  }

  /**
   * Browser-mode local checksum: read files via fetch and hash with SubtleCrypto.
   * Falls back to null if listing or hashing fails.
   */
  function _computeLocalChecksumBrowser(folderPath, callback) {
    // Try to get file listing from the folder
    fetch(folderPath + '/')
      .then(function (r) {
        if (!r.ok) { callback(null); return Promise.reject('no folder'); }
        return r.text();
      })
      .then(function (html) {
        // Parse file links from directory listing (FastAPI serves <a href="file">)
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, 'text/html');
        var links = Array.from(doc.querySelectorAll('a[href]'));
        var files = links
          .map(function (a) { return decodeURIComponent(a.getAttribute('href')); })
          .filter(function (h) { return h && !h.startsWith('/') && !h.startsWith('..'); })
          .sort();

        if (files.length === 0) { callback(null); return; }

        // Fetch all files as ArrayBuffers
        var fetches = files.map(function (f) {
          return fetch(folderPath + '/' + f).then(function (r) {
            return r.ok ? r.arrayBuffer() : null;
          }).catch(function () { return null; });
        });

        Promise.all(fetches).then(function (buffers) {
          // Concatenate (relPath + content) for each file — same as Python algo
          var encoder = new TextEncoder();
          var totalLen = 0;
          var parts = [];
          for (var i = 0; i < files.length; i++) {
            if (!buffers[i]) continue;
            var pathBytes = encoder.encode(files[i]);
            parts.push(pathBytes);
            parts.push(new Uint8Array(buffers[i]));
            totalLen += pathBytes.length + buffers[i].byteLength;
          }
          var combined = new Uint8Array(totalLen);
          var offset = 0;
          for (var j = 0; j < parts.length; j++) {
            combined.set(parts[j], offset);
            offset += parts[j].length;
          }

          // SubtleCrypto doesn't support MD5. Use a simple MD5 or fall back.
          // If crypto.subtle is available, we can't use it for MD5.
          // Fall back to folder-exists check (checksum not computable in browser).
          callback(null);
        });
      })
      .catch(function () { callback(null); });
  }

  /**
   * Fallback: check folder existence only (for services without checksum support).
   */
  function _checkGUIFolderExists(serviceName, folderPath, callbackFunc) {
    if (typeof window !== 'undefined' && window.electronAPI) {
      window.electronAPI.folderExists(folderPath)
        .then(function (exists) {
          if (exists) {
            if (callbackFunc) callbackFunc();
          } else {
            requestServiceGUIResources(serviceName, folderPath, callbackFunc);
          }
        })
        .catch(function () {
          requestServiceGUIResources(serviceName, folderPath, callbackFunc);
        });
    } else {
      var testUrl = folderPath + '/' + serviceName + '.html';
      fetch(testUrl, { method: 'HEAD' })
        .then(function (response) {
          if (response.ok) {
            if (callbackFunc) callbackFunc();
          } else {
            requestServiceGUIResourcesBrowser(serviceName, folderPath, callbackFunc);
          }
        })
        .catch(function () {
          requestServiceGUIResourcesBrowser(serviceName, folderPath, callbackFunc);
        });
    }
  }

  /**
   * Request GUI resources download via FastAPI bridge (browser mode).
   */
  function requestServiceGUIResourcesBrowser(serviceName, folderPath, callbackFunc) {
    var apiUrl = MM.serviceClient.apiUrl;
    var routingKey = MM.servicesInfor[serviceName].routing_key;
    fetch(apiUrl + '/api/service-gui-download/' + encodeURIComponent(serviceName) + '?routing_key=' + encodeURIComponent(routingKey), {
      method: 'POST'
    })
      .then(function (response) {
        if (response.ok) {
          console.log('GUI resources downloaded for', serviceName);
          if (callbackFunc) callbackFunc();
        } else {
          console.warn('Failed to download GUI resources for', serviceName, '- showing API explorer');
          showServiceAPIExplorer(serviceName);
        }
      })
      .catch(function (error) {
        console.warn('Error downloading GUI resources:', error, '- showing API explorer');
        showServiceAPIExplorer(serviceName);
      });
  }

  /************************************************************
   *             Realtime Service Status Updates              *
   ************************************************************/

  /**
   * Subscribe to realtime service status updates for a specific broker.
   *
   * @param {string} brokerUrl - The broker to subscribe to.
   */
  function subscribeToRealtimeUpdatesForBroker(brokerUrl) {
    var conn = MM.connections[brokerUrl];
    if (!conn || conn.realtimeSubscribed) return;

    if (!window.electronAPI) {
      // Browser mode: WebSocket to FastAPI bridge (shared, broker-agnostic)
      // Only connect once; messages are dispatched to all brokers
      console.log('[app] Browser mode: connecting WebSocket for realtime updates (broker:', brokerUrl, ')');
      MM.serviceClient.onServicesUpdate(function (message) {
        handleServicesUpdateForBroker(message, brokerUrl);
      });
      if (!MM.serviceClient._wsReady && !MM.serviceClient._ws) {
        MM.serviceClient.connectUpdates().catch(function (err) {
          console.error('[app] Failed to connect WebSocket updates:', err);
        });
      }
      conn.realtimeSubscribed = true;
      return;
    }

    // Electron mode: get fanout exchange name from Registry, subscribe via AMQP
    var requestData = {
      'method': 'svc_api_get_realtime_update_exchange',
      'args': null
    };

    MM.serviceClient.setBrokerUrl(brokerUrl);
    requestService(requestData, SERVICES_EXCHANGE_NAME, conn.routingKey)
      .then(function (data) {
        var exchangeName = data.result_data;
        if (!exchangeName) {
          console.warn('[app] No realtime update exchange name received from', brokerUrl);
          return;
        }
        console.log('[app] Subscribing to realtime update exchange:', exchangeName, 'on', brokerUrl);
        MM.serviceClient.setBrokerUrl(brokerUrl);
        MM.serviceClient.subscribeToExchange(exchangeName, function (message) {
          handleServicesUpdateForBroker(message, brokerUrl);
        });
        conn.realtimeSubscribed = true;
      })
      .catch(function (error) {
        console.error('[app] Failed to get realtime update exchange from', brokerUrl, ':', error);
      });
  }

  // Legacy wrapper
  function subscribeToRealtimeUpdates() {
    if (MM.activeBrokerUrl) {
      subscribeToRealtimeUpdatesForBroker(MM.activeBrokerUrl);
    }
  }

  /**
   * Handle a services update scoped to a specific broker.
   *
   * @param {object|string} message - The services information dict or JSON string.
   * @param {string} brokerUrl - The broker this update belongs to.
   */
  function handleServicesUpdateForBroker(message, brokerUrl) {
    console.log('[app] handleServicesUpdateForBroker called for', brokerUrl);
    var updatedServices;
    if (typeof message === 'string') {
      try {
        updatedServices = JSON.parse(message);
      } catch (e) {
        console.error('[app] Failed to parse services update:', e);
        return;
      }
    } else {
      updatedServices = message;
    }

    // Detect registry shutdown sentinel
    if (updatedServices && updatedServices.__registry_shutdown__) {
      console.warn('[app] Registry shutdown detected for broker:', brokerUrl);
      showToast(
        'Registry Disconnected',
        'The Service Registry on ' + brokerUrl + ' has shut down. ' +
        'It stays listed so you can retry or remove it.',
        'warning'
      );
      markBrokerOffline(brokerUrl, 'Service Registry has shut down');
      return;
    }

    // Scope queries to this broker's section
    var servicesList = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);
    var brokerSection = servicesList.querySelector('.broker-section[data-broker-url="' + brokerUrl + '"]');
    if (!brokerSection) return;

    var allItems = brokerSection.querySelectorAll('.list-group-item[data-service-name]');

    allItems.forEach(function (listItem) {
      var serviceName = listItem.getAttribute('data-service-name');
      if (serviceName === 'ServiceAlias') return;

      var icon = listItem.querySelector('.icon');
      if (serviceName in updatedServices) {
        if (listItem.classList.contains('service-disabled')) {
          listItem.classList.remove('service-disabled');
          if (icon) icon.src = IMAGE_PATH.READY;
          console.log('[app] Service came online:', serviceName, 'on', brokerUrl);
          showToast('Service Online', serviceName + ' is now available.', 'success');
        }
      } else {
        if (!listItem.classList.contains('service-disabled')) {
          if (listItem.classList.contains('active')) {
            listItem.classList.remove('active');
            var contentDiv = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);
            _deactivateCurrentPanel();
            // Remove the disconnected service's cached panel
            if (_servicePanels[serviceName]) {
              if (_servicePanels[serviceName].parentNode) {
                _servicePanels[serviceName].parentNode.removeChild(_servicePanels[serviceName]);
              }
              delete _servicePanels[serviceName];
            }
            // Append placeholder as non-cached child
            var placeholder = document.createElement('div');
            placeholder.className = 'content-placeholder';
            placeholder.innerHTML =
              '<span><i class="bi bi-exclamation-triangle me-2"></i>' +
                _escapeHtml(serviceName) + ' has disconnected</span>';
            contentDiv.appendChild(placeholder);
          }
          listItem.classList.add('service-disabled');
          if (icon) icon.src = IMAGE_PATH.DISABLED;
          console.log('[app] Service went offline:', serviceName, 'on', brokerUrl);
          showToast('Service Offline', serviceName + ' is no longer available.', 'warning');
        }
      }
    });

    // Check if any new services appeared on this broker
    Object.keys(updatedServices).forEach(function (serviceName) {
      var svcInfo = updatedServices[serviceName];

      if (!brokerSection.querySelector('.list-group-item[data-service-name="' + serviceName + '"]')) {
        var newServiceData = {};
        newServiceData[serviceName] = svcInfo;
        var newItems = extractServicesInformation(newServiceData);

        // Try to append to an existing group before creating a new one.
        var added = false;
        var prefix = sanitizeBrokerId(brokerUrl) + '_';
        newItems.forEach(function (group) {
          var existingCollapse = brokerSection.querySelector('#' + prefix + group.contentId);
          if (existingCollapse) {
            var listGroup = existingCollapse.querySelector('.list-group');
            if (listGroup) {
              group.items.forEach(function (item) {
                listGroup.appendChild(_createServiceListItem(item, brokerUrl));
              });
              added = true;
            }
          }
        });

        if (!added) {
          createAccordionItems(newItems, brokerUrl);
        }

        console.log('[app] New service appeared:', serviceName, 'on', brokerUrl);
        showToast('Service Online', serviceName + ' is now available.', 'success');
      }
    });

    // Update per-broker service store and rebuild merged view
    var conn = MM.connections[brokerUrl];
    if (conn) {
      conn.services = updatedServices;
      rebuildMergedServicesInfor();
    }
    updateBrokerBadge(brokerUrl);
  }

  /**
   * Legacy wrapper for backward compat.
   */
  function handleServicesUpdate(message) {
    // Route to the active broker or first broker
    var brokerUrl = MM.activeBrokerUrl || Object.keys(MM.connections)[0];
    if (brokerUrl) {
      handleServicesUpdateForBroker(message, brokerUrl);
    }
  }

  /************************************************************
   *                  Service Request Functions               *
   ************************************************************/

  /**
   * Get all services information from Registry Service for a specific broker.
   *
   * @param {string} brokerUrl - The broker to query.
   */
  /**
   * @param {string} brokerUrl - The broker to query.
   * @param {object} [opts]
   * @param {boolean} [opts.restored] - True when re-attaching a saved
   *   connection (startup restore or manual retry). A failure then keeps
   *   the source listed as offline instead of discarding it: the user
   *   chose it once, and it may simply not be up yet.
   */
  function requestServicesInforForBroker(brokerUrl, opts) {
    opts = opts || {};
    var conn = MM.connections[brokerUrl];
    if (!conn) return;

    var requestData = {
      'method': 'svc_api_get_services_info',
      'args': null
    };

    // Set active broker context for the request
    setRegistryServiceInfo({ brokerUrl: brokerUrl, routingKey: conn.routingKey });

    createBrokerSection(brokerUrl);
    setBrokerStatus(brokerUrl, 'connecting');

    requestService(requestData, SERVICES_EXCHANGE_NAME, conn.routingKey)
      .then(function (data) {
        console.log('Received service infor from', brokerUrl, ':', data);
        var servicesInfor = JSON.parse(data.result_data);
        conn.services = servicesInfor;
        rebuildMergedServicesInfor();
        var serviceItems = extractServicesInformation(servicesInfor);
        createAccordionItems(serviceItems, brokerUrl);
        setBrokerStatus(brokerUrl, 'online');
        updateConnectionBadge();
        showToast('Connected',
          (opts.restored ? 'Restored connection to ' : 'Successfully connected to ') + brokerUrl,
          'success');

        // Subscribe to realtime updates from this broker's Registry
        subscribeToRealtimeUpdatesForBroker(brokerUrl);
      })
      .catch(function (error) {
        console.error('Error loading data from', brokerUrl, ':', error);
        var reason = error.message || String(error);
        if (opts.restored) {
          markBrokerOffline(brokerUrl, 'Could not connect: ' + reason);
          showToast('Connection Failed',
            'Could not restore ' + brokerUrl + ': ' + reason +
            '. Use the retry button on its header, or remove it.',
            'warning');
        } else {
          disconnectBroker(brokerUrl);
          showToast('Connection Failed', 'Could not connect to ' + brokerUrl + ': ' + reason, 'danger');
        }
      });
  }

  /**
   * Legacy wrapper — get services info from the active broker.
   */
  function requestServicesInfor() {
    if (MM.brokerUrl && MM.connections[MM.brokerUrl]) {
      requestServicesInforForBroker(MM.brokerUrl);
    }
  }

  /**
   * Retrieves GUI resources of a service (Electron mode).
   *
   * @param {string} serviceName - The name of the service.
   * @param {string} folderPath - The path of the folder to store resources.
   * @param {Function|null} callbackFunc - Optional callback.
   */
  function requestServiceGUIResources(serviceName, folderPath, callbackFunc) {
    callbackFunc = callbackFunc || null;
    var requestData = {
      'method': 'svc_api_get_gui_files',
      'args': null
    };

    requestService(requestData, SERVICES_EXCHANGE_NAME, MM.servicesInfor[serviceName].routing_key)
      .then(function (data) {
        console.log('Received service GUI data');
        if (window.electronAPI) {
          return window.electronAPI.extractGUIZip(folderPath, data.result_data)
            .then(function () {
              console.log('GUI files extracted to', folderPath);
              if (callbackFunc) callbackFunc();
            });
        } else {
          // Fallback: browser mode should use requestServiceGUIResourcesBrowser
          if (callbackFunc) callbackFunc();
        }
      })
      .catch(function (error) {
        console.error('Error loading GUI data:', error);
        changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
      });
  }

  /**
   * Downloads the full service source directory as a ZIP file.
   *
   * @param {string} serviceName - The name of the service to download.
   */
  function downloadServiceFiles(serviceName) {
    var serviceInfo = MM.servicesInfor[serviceName];
    if (!serviceInfo) {
      MM.showToast('Error', 'Service info not found for ' + serviceName, 'warning');
      return;
    }

    var requestData = { method: 'svc_api_get_service_files', args: null };
    var requestPromise;
    if (serviceInfo.routing_key) {
      requestPromise = requestService(requestData, SERVICES_EXCHANGE_NAME, serviceInfo.routing_key);
    } else {
      requestPromise = MM.requestServiceDirect(requestData, serviceName);
    }

    requestPromise
      .then(function (data) {
        if (!data.result_data) {
          MM.showToast('Error', 'No file data received from ' + serviceName, 'warning');
          return;
        }
        var byteChars = atob(data.result_data);
        var byteNumbers = new Array(byteChars.length);
        for (var i = 0; i < byteChars.length; i++) {
          byteNumbers[i] = byteChars.charCodeAt(i);
        }
        var byteArray = new Uint8Array(byteNumbers);
        var blob = new Blob([byteArray], { type: 'application/zip' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = serviceName + '.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      })
      .catch(function (error) {
        console.error('Error downloading service files:', error);
        MM.showToast('Error', 'Failed to download service files: ' + error.message, 'warning');
      });
  }

  /**
   * Sends a request to a service via the shared client.
   *
   * @param {object} requestData - The JSON-formatted data to be sent.
   * @param {string} exchangeName - The name of the exchange.
   * @param {string} routingKey - The routing key for the target service.
   * @returns {Promise} A Promise that resolves with the response.
   */
  function requestService(requestData, exchangeName, routingKey) {
    var broker = resolveBrokerUrl(routingKey) || MM.brokerUrl;
    MM.serviceClient.setBrokerUrl(broker);
    return MM.serviceClient.requestService(requestData, exchangeName, routingKey);
  }

  /************************************************************
   *                  Utility Functions                       *
   ************************************************************/

  function generateUuid() {
    return Math.random().toString() +
      Math.random().toString() +
      Math.random().toString();
  }

  /************************************************************
   *               Mode Switching (Services / Fleet)          *
   ************************************************************/

  var _currentMode = 'services';
  var _helpVisible = false;
  var _helpLoaded = false;
  var _modeBeforeHelp = null;

  function switchMode(mode) {
    // If help overlay is open, close it first then switch
    if (_helpVisible) {
      _closeHelpOverlay();
    }
    if (mode === _currentMode) return;

    // Deactivate previous mode
    if (_currentMode === 'fleet') {
      deactivateFleetMode();
    } else if (_currentMode === 'creator') {
      deactivateCreatorMode();
    }
    // Leaving the Services view hides the open component: stop its polling (R5).
    if (_currentMode === 'services' && mode !== 'services') _suspendActiveComponent();

    _currentMode = mode;
    _syncInspector();

    // Toggle sidebar panels
    var sidebarServices = document.getElementById('sidebarServices');
    var sidebarFleet = document.getElementById('sidebarFleet');
    var sidebarCreator = document.getElementById('sidebarCreator');
    if (sidebarServices) sidebarServices.classList.toggle('active', mode === 'services');
    if (sidebarFleet) sidebarFleet.classList.toggle('active', mode === 'fleet');
    if (sidebarCreator) sidebarCreator.classList.toggle('active', mode === 'creator');
    var sidebarTestProject = document.getElementById('sidebarTestProject');
    if (sidebarTestProject) sidebarTestProject.classList.toggle('active', mode === 'testproject');
    var sidebarBench = document.getElementById('sidebarBench');
    if (sidebarBench) sidebarBench.classList.toggle('active', mode === 'bench');
    var benchContent = document.getElementById('benchContent');
    if (benchContent) benchContent.style.display = mode === 'bench' ? '' : 'none';
    // Plugin views (navigators and stage views with their own containers).
    document.querySelectorAll('[data-endo-mode]').forEach(function (el) {
      var on = el.getAttribute('data-endo-mode') === mode;
      if (el.classList.contains('sidebar-mode')) el.classList.toggle('active', on);
      else el.style.display = on ? '' : 'none';
    });

    // Toggle content panels
    var serviceContent = document.getElementById('serviceContent');
    var fleetContent = document.getElementById('fleetContent');
    var creatorContent = document.getElementById('creatorContent');
    if (serviceContent) serviceContent.style.display = mode === 'services' ? '' : 'none';
    if (fleetContent) fleetContent.style.display = mode === 'fleet' ? '' : 'none';
    if (creatorContent) creatorContent.style.display = mode === 'creator' ? '' : 'none';
    var testProjectContent = document.getElementById('testProjectContent');
    if (testProjectContent) testProjectContent.style.display = mode === 'testproject' ? '' : 'none';

    // Toggle nav buttons. Developer / Administrator Tools are menus; the
    // menu button lights up while one of its views is active so the user
    // can tell where they are.
    var btnServices = document.getElementById('btnModeServices');
    var btnDevTools = document.getElementById('btnDevTools');
    var btnAdminTools = document.getElementById('btnAdminTools');
    if (btnServices) btnServices.classList.toggle('active', mode === 'services' || mode === 'bench');
    var btnBench = document.getElementById('btnModeBench');
    if (btnBench) btnBench.classList.toggle('active', mode === 'bench');
    if (btnDevTools) btnDevTools.classList.toggle('active', mode === 'creator' || mode === 'testproject');
    if (btnAdminTools) btnAdminTools.classList.toggle('active', mode === 'fleet');
    _syncSidebarSwitch();
    _setRibbonTab(_ribbonTabForMode(mode), { fromMode: true });
    // The bench's tiles poll only while it is on screen (R5). After the
    // ribbon tab: a composition may open on its own role's tab.
    if (MM.endo && MM.endo.bench) MM.endo.bench.setActive(mode === 'bench');
    if (MM.endo && MM.endo.plugins) MM.endo.plugins.modeChanged(mode);

    // Activate new mode
    if (mode === 'fleet') {
      activateFleetMode();
    } else if (mode === 'creator') {
      activateCreatorMode();
    } else if (mode === 'testproject') {
      renderTestProjectView();
    } else if (mode === 'services') {
      if (_reopenOnServices) _reopenSelectedService();
      else _resumeActiveComponent();
    }
  }

  function activateFleetMode() {
    // Only Nomad and Consul sub-tabs remain after ProcessHub removal.
    var nomadTab = document.getElementById('tabNomad');
    var consulTab = document.getElementById('tabConsul');
    var isConsulActive = consulTab && consulTab.classList.contains('active');

    if (isConsulActive) {
      _activateConsulSubTab();
    } else {
      _activateNomadSubTab();
    }

    // Wire sub-tab switch events
    if (nomadTab) {
      nomadTab._mmHandler = nomadTab._mmHandler || function () {
        _deactivateConsulSubTab();
        _activateNomadSubTab();
      };
      nomadTab.removeEventListener('shown.bs.tab', nomadTab._mmHandler);
      nomadTab.addEventListener('shown.bs.tab', nomadTab._mmHandler);
    }
    if (consulTab) {
      consulTab._mmHandler = consulTab._mmHandler || function () {
        _deactivateNomadSubTab();
        _activateConsulSubTab();
      };
      consulTab.removeEventListener('shown.bs.tab', consulTab._mmHandler);
      consulTab.addEventListener('shown.bs.tab', consulTab._mmHandler);
    }
  }

  function _showContentSpinner(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div class="content-loading">' +
      '  <div class="spinner-border" role="status"></div>' +
      '  <span>Loading...</span>' +
      '</div>';
  }

  function _activateNomadSubTab() {
    if (MM.nomadDashboard) MM.nomadDashboard.activate();
  }

  function _deactivateNomadSubTab() {
    if (MM.nomadDashboard) MM.nomadDashboard.deactivate();
  }

  function _activateConsulSubTab() {
    var pane = document.getElementById('consulPane');
    if (pane && !pane.hasChildNodes()) _showContentSpinner('consulPane');
    if (MM.consulDashboard) MM.consulDashboard.activate();
  }

  function _deactivateConsulSubTab() {
    if (MM.consulDashboard) MM.consulDashboard.deactivate();
  }

  function deactivateFleetMode() {
    if (MM.nomadDashboard) MM.nomadDashboard.deactivate();
    if (MM.consulDashboard) MM.consulDashboard.deactivate();
  }

  function activateCreatorMode() {
    if (MM.serviceCreator) MM.serviceCreator.activate();
  }

  function deactivateCreatorMode() {
    if (MM.serviceCreator) MM.serviceCreator.deactivate();
  }

  // Wire the navbar. Services is the default runtime view; everything
  // else lives behind the Developer Tools / Administrator Tools menus so
  // it is reachable without being in the operator's way.
  function _wire(id, handler) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', handler);
  }
  // btnModeServices (the User tab) is wired with the ribbon tabs below: it
  // opens Services, or keeps the bench when that is showing.

  // Developer Tools -- generate and test
  _wire('btnModeCreator', function () { switchMode('creator'); });
  _wire('btnDevApiExplorer', function () {
    // The explorer lives in the inspector so the service stays in view.
    switchMode('services');
    setDevMode(true, { tab: 'api', silent: true });
  });
  _wire('btnDevCodeExamples', function () {
    _withSelectedService('Code Examples', function (sel) {
      switchMode('services');
      showServiceHelper(sel.infoKey);
    });
  });
  // Robot resources and test projects are reached through plugins
  // (web/plugins/robot-gen, web/plugins/test-project); their commands call
  // these shell actions (see the plugins init below).
  function _testProjectView() {
    if (_getTestProject()) switchMode('testproject');
    else openTestProject();   // lands in the view once a project is open
  }
  _wire('btnDevExportToProject', function () {
    _withSelectedService('Add to test project', function (sel) { exportToTestProject(sel); });
  });
  (function () {
    var apply = document.getElementById('btnTestProjectApply');
    if (!apply) return;
    apply.addEventListener('click', function () {
      if (!_tpState) return;
      if (_tpState.action === 'init') _applyInit();
      else if (_tpState.action === 'export') _applyExport();
    });
  })();

  /************************************************************
   *                      Test projects                        *
   ************************************************************/

  // The open project is a folder path on the bridge's machine; the bridge
  // does all file I/O, so this also works in browser mode.
  var TEST_PROJECT_KEY = 'mm_test_project';
  var _testProjectModal = null;
  var _tpState = null;   // { action: 'init' | 'export' | 'done', ... }

  var TP_STATUS = {
    create:    ['new', 'Will be created'],
    update:    ['update', 'Generated earlier and not edited since: will be regenerated'],
    unchanged: ['unchanged', 'Already up to date'],
    modified:  ['edited locally', 'Differs from what this tool last wrote, or was not written by it: left alone unless you allow overwriting'],
    keep:      ['kept', 'Yours to edit: never overwritten']
  };

  function _getTestProject() {
    try { return localStorage.getItem(TEST_PROJECT_KEY) || ''; } catch (e) { return ''; }
  }

  function _setTestProject(root) {
    try {
      if (root) localStorage.setItem(TEST_PROJECT_KEY, root);
      else localStorage.removeItem(TEST_PROJECT_KEY);
    } catch (e) { /* storage unavailable */ }
    _inspectorKey = null;
    _syncSidebarSwitch();
    if (_devMode) _renderInspector(_selectedService);
  }

  function _projectLabel(root) {
    var parts = String(root || '').replace(/[\\\/]+$/, '').split(/[\\\/]/);
    return parts[parts.length - 1] || String(root || '');
  }

  function _pickFolder(title, current) {
    if (window.electronAPI && window.electronAPI.showOpenDialog) {
      return window.electronAPI.showOpenDialog({
        title: title,
        defaultPath: current || undefined,
        properties: ['openDirectory', 'createDirectory']
      }).then(function (res) {
        return ((res && res.filePaths && res.filePaths[0]) || '').trim();
      });
    }
    return Promise.resolve((window.prompt(title + ' — folder path:', current || '') || '').trim());
  }

  function _tpBody(html) {
    document.getElementById('testProjectModalBody').innerHTML = html;
  }

  function _tpSetApply(html) {
    var apply = document.getElementById('btnTestProjectApply');
    var cancel = document.getElementById('btnTestProjectCancel');
    apply.hidden = !html;
    apply.disabled = false;
    if (html) apply.innerHTML = html;
    cancel.textContent = html ? 'Cancel' : 'Close';
  }

  function _tpShow(titleHtml, bodyHtml, applyHtml) {
    document.getElementById('testProjectModalTitle').innerHTML = titleHtml;
    _tpBody(bodyHtml);
    _tpSetApply(applyHtml);
    if (!_testProjectModal) {
      _testProjectModal = new bootstrap.Modal(document.getElementById('testProjectModal'));
    }
    _testProjectModal.show();
  }

  /** Run fn once the modal has finished hiding (Bootstrap cannot re-show mid-transition). */
  function _afterModalHidden(fn) {
    var el = document.getElementById('testProjectModal');
    if (!el.classList.contains('show')) { fn(); return; }
    el.addEventListener('hidden.bs.modal', function handler() {
      el.removeEventListener('hidden.bs.modal', handler);
      fn();
    });
    _testProjectModal.hide();
  }

  function openTestProject(onReady) {
    return _pickFolder('Open test project', _getTestProject())
      .then(function (root) {
        if (!root) return null;
        return MM.testProjectClient.describe(root).then(function (d) {
          if (!d.exists) throw new Error('Folder does not exist: ' + root);
          if (d.initialized) {
            _setTestProject(d.root);
            showToast('Test project', 'Opened ' + d.name + ' (' + d.runner_name + ', ' +
              d.services.length + ' exported service' + (d.services.length === 1 ? '' : 's') + ').',
              'success');
            if (onReady) onReady(d);
            else _showTestProjectView();
          } else {
            _showInitDialog(d, onReady);
          }
          return d;
        });
      })
      .catch(function (err) {
        showToast('Test project', err.message || String(err), 'danger');
      });
  }

  function _showInitDialog(d, onReady) {
    var runners = (d.runners || []).map(function (r) {
      return '<option value="' + _escapeHtml(r.id) + '">' + _escapeHtml(r.name) + '</option>';
    }).join('');
    var detected = d.detected || {};
    var existing = detected.robot_suites
      ? '<div class="dev-note"><i class="bi bi-info-circle me-1"></i>The folder already holds ' +
        detected.robot_suites + ' .robot file' + (detected.robot_suites === 1 ? '' : 's') +
        '. Existing files are never moved or changed.</div>'
      : '';
    var tree =
      _escapeHtml(d.name) + '/\n' +
      '├─ testproject.json                     manifest: runner, layout, what was exported\n' +
      '├─ testsuites/\n' +
      '│  ├─ config/robot_config.jsonp         RF AIO config (level 3), CONSUL_ADDR in params.global\n' +
      '│  └─ &lt;service&gt;_smoke.robot            starter suite per service — yours to edit\n' +
      '├─ resources/&lt;service&gt;/*.resource       generated keywords — refreshed on export\n' +
      '└─ proto/&lt;service&gt;/*.proto              copied protos, when available';

    _tpState = { action: 'init', root: d.root, onReady: onReady };
    _tpShow('<i class="bi bi-folder-plus me-2"></i>Initialize test project',
      '<p class="mb-2"><code>' + _escapeHtml(d.root) + '</code> is not a test project yet.</p>' +
      existing +
      '<div class="mb-3">' +
      '  <label class="form-label small" for="tpRunner">Test runner</label>' +
      '  <select class="form-select form-select-sm tp-runner" id="tpRunner">' + runners + '</select>' +
      '  <div class="form-text">The runner adapter decides layout and generated files; other runners can be added without changing projects that already exist.</div>' +
      '</div>' +
      '<div class="tp-layout"><div class="small text-muted mb-1">Structure exports will use</div><pre>' + tree + '</pre></div>',
      '<i class="bi bi-check2 me-1"></i>Initialize');
  }

  function _applyInit() {
    var st = _tpState;
    var runner = (document.getElementById('tpRunner') || {}).value || 'robotframework-aio';
    var consul = _connectedConsuls.length ? _connectedConsuls[0].url : '';
    var apply = document.getElementById('btnTestProjectApply');
    apply.disabled = true;
    apply.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Initializing…';
    MM.testProjectClient.init(st.root, runner, consul)
      .then(function (d) {
        _setTestProject(d.root);
        st.action = 'done';
        showToast('Test project', 'Initialized ' + d.name + ' (' + d.runner_name + ').', 'success');
        _afterModalHidden(function () {
          if (st.onReady) st.onReady(d);
          else _showTestProjectView();
        });
      })
      .catch(function (err) {
        _tpBody(_devAlert('danger', 'Initialization failed', err.message || err));
        _tpSetApply(null);
      });
  }

  function exportToTestProject(sel) {
    if (!sel || !sel.consul) {
      showToast('Add to test project',
        'Only Consul-registered gRPC services can be exported — select one in the Services view.', 'info');
      return;
    }
    var root = _getTestProject();
    if (!root) {
      openTestProject(function () { exportToTestProject(sel); });
      return;
    }
    _tpState = {
      action: 'export',
      sel: sel,
      opts: {
        root: root,
        consul_name: sel.consul.name,
        consul: sel.consul.consulUrl || '',
        proto_path: _getStoredProtoPath(sel.consul.name),
        prefer_reflection: false,
        create_starter: true,
        overwrite_modified: false
      }
    };
    _tpShow('<i class="bi bi-box-arrow-in-down me-2"></i>Add <code>' + _escapeHtml(sel.consul.name) +
            '</code> to test project <code>' + _escapeHtml(_projectLabel(root)) + '</code>',
            '', null);
    _planExport();
  }

  function _planExport() {
    var st = _tpState;
    _tpBody(_devLoading('Planning the export…'));
    _tpSetApply(null);
    MM.testProjectClient.exportService(Object.assign({}, st.opts, { apply: false }))
      .then(function (plan) {
        if (_tpState !== st) return;
        st.plan = plan;
        _renderExportPlan(plan);
      })
      .catch(function (err) {
        if (_tpState !== st) return;
        _tpBody(_devAlert('danger', 'The export could not be planned', err.message || err) +
          '<div class="tp-links"><a href="#" id="tpPickProto">Use a .proto folder…</a>' +
          '<a href="#" id="tpOpenOther">Open another test project…</a></div>');
        _wirePickProto(st);
        var other = document.getElementById('tpOpenOther');
        if (other) {
          other.addEventListener('click', function (e) {
            e.preventDefault();
            _afterModalHidden(function () {
              openTestProject(function () { exportToTestProject(st.sel); });
            });
          });
        }
      });
  }

  function _wirePickProto(st) {
    var pick = document.getElementById('tpPickProto');
    if (!pick) return;
    pick.addEventListener('click', function (e) {
      e.preventDefault();
      _pickFolder('Folder holding the .proto of ' + st.opts.consul_name, st.opts.proto_path)
        .then(function (dir) {
          if (!dir) return;
          st.opts.proto_path = dir;
          st.opts.prefer_reflection = false;
          _setStoredProtoPath(st.opts.consul_name, dir);
          _planExport();
        });
    });
  }

  function _tpWrites(plan, overwrite) {
    return plan.files.filter(function (f) {
      return f.status === 'create' || f.status === 'update' || (overwrite && f.status === 'modified');
    }).length;
  }

  function _renderExportPlan(plan) {
    var st = _tpState;
    var src = plan.source || {};
    var modified = plan.files.filter(function (f) { return f.status === 'modified'; }).length;

    var sourceHtml = src.kind === 'proto'
      ? '<i class="bi bi-file-earmark-code me-1"></i>Generated from <code>' + _escapeHtml(src.path) +
        '</code>; that proto and its local imports are copied into the project.'
      : '<i class="bi bi-broadcast me-1"></i>Generated from the server reflection of <code>' +
        _escapeHtml(src.path || '') + '</code>. No proto is copied; the suite reaches the service through reflection.';
    var links = '<a href="#" id="tpPickProto">Use a .proto folder…</a>' +
      (src.kind === 'proto' ? '<a href="#" id="tpUseReflection">Generate from server reflection instead</a>' : '');

    var rows = plan.files.map(function (f) {
      var meta = TP_STATUS[f.status] || [f.status, ''];
      return '<tr>' +
        '<td><span class="tp-status tp-status-' + _escapeHtml(f.status) + '" title="' + _escapeHtml(meta[1]) + '">' +
        _escapeHtml(meta[0]) + '</span></td>' +
        '<td><code>' + _escapeHtml(f.path) + '</code>' +
        (f.diff ? '<details class="tp-diff"><summary>Show diff</summary><pre>' + _escapeHtml(f.diff) + '</pre></details>' : '') +
        '</td>' +
        '<td class="tp-role">' + (f.role === 'starter' ? 'starter' : 'generated') + '</td>' +
        '</tr>';
    }).join('');

    var notes = (plan.warnings || []).concat(plan.advisories || []).map(function (a) {
      return '<div class="dev-note"><i class="bi bi-exclamation-circle me-1"></i>' + _escapeHtml(a) + '</div>';
    }).join('');

    _tpBody(
      '<div class="tp-source">' + sourceHtml + '<div class="tp-links">' + links + '</div></div>' +
      notes +
      '<div class="dev-note" id="tpUpToDate" hidden><i class="bi bi-check2-circle me-1"></i>Nothing to write — the project is up to date.</div>' +
      '<div class="tp-options">' +
      '  <div class="form-check form-switch"><input class="form-check-input" type="checkbox" id="tpStarter"' +
      (st.opts.create_starter ? ' checked' : '') + '>' +
      '    <label class="form-check-label small" for="tpStarter">Create a starter suite and RF AIO config when missing</label></div>' +
      (modified
        ? '  <div class="form-check form-switch"><input class="form-check-input" type="checkbox" id="tpOverwrite"' +
          (st.opts.overwrite_modified ? ' checked' : '') + '>' +
          '    <label class="form-check-label small" for="tpOverwrite">Overwrite ' + modified + ' locally edited file' +
          (modified === 1 ? '' : 's') + '</label></div>'
        : '') +
      '</div>' +
      '<table class="tp-table"><thead><tr><th>Status</th><th>File</th><th>Kind</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<div class="tp-hint"><span class="small text-muted">Run it from the project root</span>' +
      '<code id="tpRunHint" title="Copy">' + _escapeHtml(plan.run_hint || '') + '</code></div>'
    );

    function refreshApply() {
      var n = _tpWrites(plan, st.opts.overwrite_modified);
      document.getElementById('tpUpToDate').hidden = n > 0;
      _tpSetApply(n ? '<i class="bi bi-check2 me-1"></i>Write ' + n + ' file' + (n === 1 ? '' : 's') : null);
    }

    var starter = document.getElementById('tpStarter');
    if (starter) {
      starter.addEventListener('change', function () {
        st.opts.create_starter = starter.checked;
        _planExport();
      });
    }
    var overwrite = document.getElementById('tpOverwrite');
    if (overwrite) {
      overwrite.addEventListener('change', function () {
        st.opts.overwrite_modified = overwrite.checked;
        refreshApply();
      });
    }
    _wirePickProto(st);
    var refl = document.getElementById('tpUseReflection');
    if (refl) {
      refl.addEventListener('click', function (e) {
        e.preventDefault();
        st.opts.prefer_reflection = true;
        _planExport();
      });
    }
    var hint = document.getElementById('tpRunHint');
    if (hint) hint.addEventListener('click', function () { _copyText(plan.run_hint, 'Command'); });
    refreshApply();
  }

  function _applyExport() {
    var st = _tpState;
    var apply = document.getElementById('btnTestProjectApply');
    apply.disabled = true;
    apply.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Writing…';
    MM.testProjectClient.exportService(Object.assign({}, st.opts, { apply: true }))
      .then(function (res) {
        if (_tpState !== st) return;
        st.action = 'done';
        _renderExportResult(res);
      })
      .catch(function (err) {
        if (_tpState !== st) return;
        _tpBody(_devAlert('danger', 'Export failed', err.message || err));
        _tpSetApply(null);
      });
  }

  function _renderExportResult(res) {
    var written = res.written || [];
    var skipped = res.skipped || [];
    function list(paths) {
      return '<ul class="tp-list">' + paths.map(function (p) {
        return '<li><code>' + _escapeHtml(p) + '</code></li>';
      }).join('') + '</ul>';
    }
    _tpBody(
      '<div class="dev-alert dev-alert-ok"><strong>' + written.length + ' file' + (written.length === 1 ? '' : 's') +
      ' written to <code>' + _escapeHtml(res.root) + '</code></strong></div>' +
      (written.length ? list(written) : '') +
      (skipped.length
        ? '<div class="dev-note"><i class="bi bi-shield-check me-1"></i>Left alone because they were edited locally:</div>' + list(skipped)
        : '') +
      '<div class="tp-hint"><span class="small text-muted">Run it from the project root</span>' +
      '<code id="tpRunHint" title="Copy">' + _escapeHtml(res.run_hint || '') + '</code></div>'
    );
    var hint = document.getElementById('tpRunHint');
    if (hint) hint.addEventListener('click', function () { _copyText(res.run_hint, 'Command'); });
    _tpSetApply(null);
    showToast('Test project', written.length + ' file(s) written' +
      (skipped.length ? ', ' + skipped.length + ' left alone' : '') + '.', 'success');
    if (_currentMode === 'testproject') renderTestProjectView();
  }

  /************************************************************
   *                   Test project view                       *
   ************************************************************/

  // Sidebar: the project's files grouped by kind, with role and sync state.
  // Content: an overview (exported services, re-export, add a running
  // service) or a read-only preview of the selected file.
  var _tpView = { selected: null, data: null };

  var TPV_GROUPS = [
    { kind: 'suite', title: 'Suites', icon: 'bi-play-circle' },
    { kind: 'resource', title: 'Resources', icon: 'bi-puzzle' },
    { kind: 'proto', title: 'Protos', icon: 'bi-file-earmark-code' },
    { kind: 'config', title: 'Configuration', icon: 'bi-sliders' },
    { kind: 'other', title: 'Other files', icon: 'bi-file-earmark' }
  ];

  var TPV_ROLE = {
    manifest:  ['manifest', 'Written by the tool: runner, layout and what was exported'],
    generated: ['gen', 'Generated: refreshed by exports; do not edit'],
    starter:   ['starter', 'Created once by an export, then yours'],
    yours:     ['yours', 'Not written by an export']
  };

  function _showTestProjectView() {
    _tpView.selected = null;
    if (_currentMode === 'testproject') renderTestProjectView();
    else switchMode('testproject');
  }

  function _tpvGroupOf(f) {
    return (f.kind === 'suite' || f.kind === 'resource' || f.kind === 'proto' || f.kind === 'config')
      ? f.kind : 'other';
  }

  function _tpvLabel(data, f) {
    var layout = data.layout || {};
    var prefixes = [layout.suites, layout.resources, layout.proto].filter(Boolean);
    for (var i = 0; i < prefixes.length; i++) {
      if (f.path.indexOf(prefixes[i] + '/') === 0) return f.path.slice(prefixes[i].length + 1);
    }
    return f.path;
  }

  function _tpvNote(text) {
    return '<div class="dev-note"><i class="bi bi-info-circle me-1"></i>' + _escapeHtml(text) + '</div>';
  }

  /** A running (Consul-discovered) service as a selection object, or null. */
  function _findDiscoveredService(name) {
    for (var i = 0; i < _connectedConsuls.length; i++) {
      var conn = _connectedConsuls[i];
      var svc = (conn.services || []).filter(function (s) { return s.name === name; })[0];
      if (svc) {
        return { name: svc.name, infoKey: svc.name + '@' + conn.url,
                 consul: Object.assign({}, svc, { consulUrl: conn.url }), info: null };
      }
    }
    return null;
  }

  function _tpvWireOpen() {
    var open = document.getElementById('tpvOpen');
    if (open) open.addEventListener('click', function (e) { e.preventDefault(); openTestProject(); });
  }

  function renderTestProjectView() {
    var sidebar = document.getElementById('testProjectTree');
    var content = document.getElementById('testProjectContent');
    if (!sidebar || !content) return;
    var root = _getTestProject();
    if (!root) {
      _tpvEditor = null;
      sidebar.innerHTML = '<div class="tpv-empty">No test project open.</div>';
      content.innerHTML =
        '<div class="content-placeholder"><span><i class="bi bi-folder2-open me-2"></i>' +
        'No test project is open. <a href="#" id="tpvOpen">Open one\u2026</a></span></div>';
      _tpvWireOpen();
      return;
    }
    sidebar.innerHTML = '<div class="tpv-empty">Reading the project\u2026</div>';
    MM.testProjectClient.tree(root)
      .then(function (data) {
        if (_getTestProject() !== root) return;
        _tpView.data = data;
        // Never throw away unsaved edits because the view was re-entered.
        if (_tpvDirty() && _tpView.selected === _tpvEditor.path) {
          _renderTpvSidebar(data);
          return;
        }
        var keep = _tpView.selected && data.files.some(function (f) { return f.path === _tpView.selected; });
        if (!keep) _tpView.selected = null;
        _renderTpvSidebar(data);
        if (_tpView.selected) _showTpvFile(_tpView.selected);
        else _renderTpvOverview(data);
      })
      .catch(function (err) {
        sidebar.innerHTML = '';
        content.innerHTML =
          _devAlert('danger', 'Could not read the test project', err.message || err) +
          '<div class="tp-links"><a href="#" id="tpvOpen">Open another test project\u2026</a></div>';
        _tpvWireOpen();
      });
  }

  function _renderTpvSidebar(data) {
    var sidebar = document.getElementById('testProjectTree');
    var html =
      '<div class="tpv-project">' +
      '  <div class="tpv-project-name"><i class="bi bi-folder2-open me-1"></i>' + _escapeHtml(data.name) + '</div>' +
      '  <div class="tpv-project-meta">' + _escapeHtml(data.runner_name) + '</div>' +
      '</div>' +
      '<button type="button" class="tpv-item' + (_tpView.selected ? '' : ' active') + '" data-tpv-overview="1">' +
      '  <i class="bi bi-grid-1x2"></i><span class="tpv-item-label">Overview</span></button>';

    TPV_GROUPS.forEach(function (g) {
      var files = data.files.filter(function (f) { return _tpvGroupOf(f) === g.kind; });
      if (!files.length) return;
      html += '<div class="tpv-group"><div class="tpv-group-title"><span><i class="bi ' + g.icon + ' me-1"></i>' +
              g.title + '</span><span>' +
              (g.kind === 'suite'
                ? '<button type="button" class="tpv-add" data-tpv-new-suite="1" title="New suite">' +
                  '<i class="bi bi-plus-lg"></i></button>'
                : '') +
              files.length + '</span></div>';
      files.forEach(function (f) {
        var role = TPV_ROLE[f.role] || [f.role, ''];
        var state = f.state === 'edited' ? ' \u2014 edited since the last export'
                  : f.state === 'missing' ? ' \u2014 deleted since the last export' : '';
        var open = _tpView.selected === f.path;
        html +=
          '<button type="button" class="tpv-item' + (open ? ' active' : '') + '"' +
          ' data-tpv-path="' + _escapeHtml(f.path) + '" title="' + _escapeHtml(f.path + state) + '">' +
          '  <span class="tpv-dot tpv-state-' + _escapeHtml(f.state) + '"></span>' +
          '  <span class="tpv-item-label">' + _escapeHtml(_tpvLabel(data, f)) +
          (open && _tpvDirty() ? ' <span class="tpv-unsaved" title="Unsaved changes">\u25cf</span>' : '') + '</span>' +
          '  <span class="tpv-role tpv-role-' + _escapeHtml(f.role) + '" title="' + _escapeHtml(role[1]) + '">' +
               _escapeHtml(role[0]) + '</span>' +
          '</button>';
      });
      html += '</div>';
    });
    if (data.truncated) html += '<div class="tpv-empty">Only the first 2000 files are listed.</div>';
    sidebar.innerHTML = html;

    sidebar.querySelectorAll('[data-tpv-overview]').forEach(function (b) {
      b.addEventListener('click', function () {
        _tpvGuard(function () {
          _tpView.selected = null;
          _renderTpvSidebar(data);
          _renderTpvOverview(data);
        });
      });
    });
    sidebar.querySelectorAll('[data-tpv-path]').forEach(function (b) {
      b.addEventListener('click', function () {
        var path = b.getAttribute('data-tpv-path');
        if (path === _tpView.selected && _tpvEditor) return;
        _tpvGuard(function () {
          _tpView.selected = path;
          _renderTpvSidebar(data);
          _showTpvFile(path);
        });
      });
    });
    sidebar.querySelectorAll('[data-tpv-new-suite]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _tpvGuard(function () { _showTpvNewSuite(data); });
      });
    });
  }

  function _renderTpvOverview(data) {
    var content = document.getElementById('testProjectContent');
    function count(kind) {
      return data.files.filter(function (f) { return f.kind === kind && f.state !== 'missing'; }).length;
    }
    function stat(value, label) {
      return '<div><div class="tpv-stat-value">' + value + '</div><div class="tpv-stat-label">' + label + '</div></div>';
    }

    var rows = data.services.map(function (s) {
      var c = s.files || {};
      var parts = ['<span class="tpv-files-ok">' + (c.ok || 0) + ' ok</span>'];
      if (c.edited) parts.push('<span class="tpv-files-edited">' + c.edited + ' edited locally</span>');
      if (c.missing) parts.push('<span class="tpv-files-missing">' + c.missing + ' missing</span>');
      var src = s.source || {};
      var running = _findDiscoveredService(s.name);
      return '<tr>' +
        '<td><strong>' + _escapeHtml(s.name) + '</strong></td>' +
        '<td>' + (s.grpc_services || []).map(function (g) { return '<code>' + _escapeHtml(g) + '</code>'; }).join('<br>') + '</td>' +
        '<td>' + (src.kind === 'proto' ? '<i class="bi bi-file-earmark-code me-1"></i>proto'
                 : src.kind === 'reflection' ? '<i class="bi bi-broadcast me-1"></i>reflection' : '—') + '</td>' +
        '<td>' + _escapeHtml(String(s.exported_at || '').replace('T', ' ')) + '</td>' +
        '<td>' + parts.join(' · ') + '</td>' +
        '<td><button type="button" class="btn btn-sm btn-outline-primary" data-tpv-reexport="' + _escapeHtml(s.name) + '"' +
        (running ? ' title="Plan a fresh export from the running service"' : ' disabled title="Not running in a connected Consul"') +
        '><i class="bi bi-arrow-repeat me-1"></i>Re-export</button></td>' +
        '</tr>';
    }).join('');

    var exported = {};
    data.services.forEach(function (s) { exported[s.name] = true; });
    var discovered = [];
    _connectedConsuls.forEach(function (conn) {
      (conn.services || []).forEach(function (svc) {
        if (discovered.indexOf(svc.name) < 0) discovered.push(svc.name);
      });
    });
    discovered.sort(function (a, b) { return (exported[a] ? 1 : 0) - (exported[b] ? 1 : 0) || a.localeCompare(b); });
    var addHtml = discovered.length
      ? '<div class="tpv-add-row"><select class="form-select form-select-sm" id="tpvAddSelect">' +
          discovered.map(function (n) {
            return '<option value="' + _escapeHtml(n) + '">' + _escapeHtml(n) + (exported[n] ? ' (exported)' : '') + '</option>';
          }).join('') +
        '</select><button type="button" class="btn btn-sm btn-primary" id="tpvAddButton">' +
        '<i class="bi bi-box-arrow-in-down me-1"></i>Export…</button></div>' +
        '<div class="small text-muted mt-2">Services running in the connected Consul' +
        (_connectedConsuls.length === 1 ? ' (' + _escapeHtml(_connectedConsuls[0].url) + ')' : 's') + '.</div>'
      : '<div class="small text-muted">No running services — connect to a Consul in the Services view first.</div>';

    content.innerHTML =
      '<div class="tpv-view">' +
      '  <div class="svc-ov-head">' +
      '    <h4 class="svc-ov-title"><i class="bi bi-kanban me-2"></i>' + _escapeHtml(data.name) + '</h4>' +
      '    <span class="dev-tag">' + _escapeHtml(data.runner_name) + '</span>' +
      '    <code class="dev-target" id="tpvRoot" title="Copy path">' + _escapeHtml(data.root) + '</code>' +
      '    <div class="svc-ov-tools">' +
      '      <button type="button" class="btn btn-sm btn-outline-secondary" id="tpvRefresh" title="Re-read the project">' +
      '        <i class="bi bi-arrow-clockwise"></i></button>' +
      '      <button type="button" class="btn btn-sm btn-outline-secondary" id="tpvChange">' +
      '        <i class="bi bi-folder2-open me-1"></i>Change project…</button>' +
      '    </div>' +
      '  </div>' +
      '  <div class="svc-ov-grid">' +
      '    <section class="svc-ov-card"><h6 class="svc-ov-card-title"><i class="bi bi-bar-chart me-1"></i>Project</h6>' +
      '      <div class="tpv-stats">' + stat(count('suite'), 'suites') + stat(count('resource'), 'resources') +
               stat(count('proto'), 'protos') + stat(data.services.length, 'services') + '</div>' +
      (data.run_hint
        ? '<div class="tp-hint"><span class="small text-muted">Run all suites from the project root</span>' +
          '<code id="tpvRunHint" title="Copy">' + _escapeHtml(data.run_hint) + '</code></div>'
        : '') +
      '      <div class="mt-3"><button type="button" class="btn btn-sm btn-outline-primary" id="tpvNewSuite">' +
      '        <i class="bi bi-file-earmark-plus me-1"></i>New suite\u2026</button></div>' +
      '    </section>' +
      '    <section class="svc-ov-card"><h6 class="svc-ov-card-title"><i class="bi bi-plus-circle me-1"></i>Add a service</h6>' +
             addHtml + '</section>' +
      '  </div>' +
      '  <section class="svc-ov-card"><h6 class="svc-ov-card-title"><i class="bi bi-hdd-stack me-1"></i>Exported services</h6>' +
      (data.services.length
        ? '<div class="svc-ov-table-wrap"><table class="svc-ov-table"><thead><tr><th>Service</th><th>gRPC services</th>' +
          '<th>Source</th><th>Exported</th><th>Files</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        : '<div class="small text-muted">Nothing exported yet — pick a running service above.</div>') +
      '  </section>' +
      '</div>';

    function on(id, fn) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', fn);
    }
    on('tpvRefresh', function () { renderTestProjectView(); });
    on('tpvChange', function () { openTestProject(); });
    on('tpvRoot', function () { _copyText(data.root, 'Path'); });
    on('tpvRunHint', function () { _copyText(data.run_hint, 'Command'); });
    on('tpvNewSuite', function () { _showTpvNewSuite(data); });
    on('tpvAddButton', function () {
      var name = document.getElementById('tpvAddSelect').value;
      exportToTestProject(_findDiscoveredService(name));
    });
    content.querySelectorAll('[data-tpv-reexport]').forEach(function (b) {
      b.addEventListener('click', function () {
        exportToTestProject(_findDiscoveredService(b.getAttribute('data-tpv-reexport')));
      });
    });
  }

  function _showTpvFile(path) {
    var content = document.getElementById('testProjectContent');
    var data = _tpView.data || { files: [] };
    var f = data.files.filter(function (x) { return x.path === path; })[0] ||
            { path: path, role: 'yours', state: 'yours', kind: 'other' };
    var role = TPV_ROLE[f.role] || [f.role, ''];
    _tpvEditor = null;

    var head =
      '<div class="tpv-file-head">' +
      '  <a href="#" class="tpv-back" id="tpvBack"><i class="bi bi-arrow-left me-1"></i>Overview</a>' +
      '  <code>' + _escapeHtml(path) + '</code>' +
      '  <span class="tp-status tp-status-' + (f.role === 'generated' ? 'update' : f.role === 'starter' ? 'create' : 'unchanged') +
      '" title="' + _escapeHtml(role[1]) + '">' + _escapeHtml(f.role) + '</span>' +
      (f.state === 'edited' ? '<span class="tp-status tp-status-modified">edited locally</span>' : '') +
      (f.state === 'missing' ? '<span class="tp-status tp-status-modified">missing</span>' : '') +
      (f.service ? '<span class="dev-tag">' + _escapeHtml(f.service) + '</span>' : '') +
      '  <span class="tpv-edit-status" id="tpvEditStatus"></span>' +
      '  <div class="tpv-file-tools" id="tpvTools"></div>' +
      '</div>';

    var note = '';
    if (f.role === 'generated' && f.state === 'edited') {
      note = _tpvNote('Edited locally since the last export. An export leaves it alone unless you allow overwriting \u2014 ' +
                      'keep your own keywords in a hand-written resource instead.');
    } else if (f.role === 'generated') {
      note = _tpvNote('Generated by an export and refreshed by the next one, so it is read-only here \u2014 ' +
                      'put your own keywords in a separate file.');
    } else if (f.role === 'manifest') {
      note = _tpvNote('Maintained by the tool; read-only.');
    }

    if (f.state === 'missing') {
      content.innerHTML = '<div class="tpv-view">' + head +
        _devAlert('warning', 'Missing', 'An export wrote this file and it has been deleted since. Re-export ' +
                  (f.service || 'the service') + ' to restore it.') + '</div>';
      _tpvWireBack(data);
      return;
    }

    content.innerHTML = '<div class="tpv-view">' + head + note +
      '<div id="tpvBanner"></div><div id="tpvFileBody">' + _devLoading('Loading\u2026') + '</div></div>';
    _tpvWireBack(data);

    MM.testProjectClient.file(_getTestProject(), path)
      .then(function (res) {
        if (_tpView.selected !== path) return;
        if (res.editable) _tpvOpenEditor(f, res);
        else _tpvShowPreview(f, res);
      })
      .catch(function (err) {
        if (_tpView.selected !== path) return;
        document.getElementById('tpvFileBody').innerHTML = _devAlert('warning', 'No preview', err.message || err);
      });
  }

  // ---- Editing ---------------------------------------------------------------

  // The file open for editing: { root, path, sha, original, textarea, lines, savedAt }.
  // `sha` is the hash of what is on disk as last read or saved; a save sends
  // it so the bridge can refuse to overwrite a change made meanwhile.
  var _tpvEditor = null;
  var _tpvDraftTimer = null;

  function _tpvDirty() {
    return !!(_tpvEditor && _tpvEditor.textarea && _tpvEditor.textarea.value !== _tpvEditor.original);
  }

  /** Run proceed(), after confirming when the open file has unsaved changes. */
  function _tpvGuard(proceed) {
    if (!_tpvDirty()) {
      _tpvEditor = null;
      proceed();
      return;
    }
    var ed = _tpvEditor;
    showConfirm('Discard your unsaved changes to ' + ed.path + '?', function () {
      _tpvClearDraft(ed.root, ed.path);
      _tpvEditor = null;
      proceed();
    });
  }

  function _tpvWireBack(data) {
    var back = document.getElementById('tpvBack');
    if (!back) return;
    back.addEventListener('click', function (e) {
      e.preventDefault();
      _tpvGuard(function () {
        _tpView.selected = null;
        _renderTpvSidebar(data);
        _renderTpvOverview(data);
      });
    });
  }

  function _tpvCopyRunButton(f) {
    return f.kind === 'suite'
      ? '<button type="button" class="btn btn-sm btn-outline-secondary" id="tpvCopyRun" title="Copy the command that runs this suite">' +
        '<i class="bi bi-terminal me-1"></i>Run command</button>'
      : '';
  }

  function _tpvWireCopyRun(path) {
    var copyRun = document.getElementById('tpvCopyRun');
    if (copyRun) {
      copyRun.addEventListener('click', function () {
        _copyText('python -m robot -d results ' + path, 'Command');
      });
    }
  }

  function _tpvShowPreview(f, res) {
    document.getElementById('tpvTools').innerHTML = _tpvCopyRunButton(f) +
      '<button type="button" class="btn btn-sm btn-outline-secondary" id="tpvCopyFile">' +
      '<i class="bi bi-clipboard me-1"></i>Copy</button>';
    document.getElementById('tpvFileBody').innerHTML =
      '<pre class="helper-code-pre tpv-preview">' + _numberedCode(res.content) + '</pre>';
    _tpvWireCopyRun(res.path);
    document.getElementById('tpvCopyFile').addEventListener('click', function () { _copyText(res.content, 'File'); });
  }

  function _tpvOpenEditor(f, res) {
    var root = _getTestProject();
    document.getElementById('tpvTools').innerHTML =
      '<button type="button" class="btn btn-sm btn-outline-secondary" id="tpvCheck" title="Check the Robot Framework syntax">' +
      '<i class="bi bi-check2-square me-1"></i>Check</button>' +
      _tpvCopyRunButton(f) +
      '<button type="button" class="btn btn-sm btn-outline-secondary" id="tpvRevert" disabled title="Back to the saved version">' +
      '<i class="bi bi-arrow-counterclockwise me-1"></i>Revert</button>' +
      '<button type="button" class="btn btn-sm btn-primary" id="tpvSave" disabled title="Save (Ctrl+S)">' +
      '<i class="bi bi-save me-1"></i>Save</button>';

    document.getElementById('tpvFileBody').innerHTML =
      '<div class="tpv-editor">' +
      '  <div class="tpv-gutter"><div id="tpvGutter"></div></div>' +
      '  <div class="tpv-code">' +
      '    <pre class="tpv-hl" id="tpvHl" aria-hidden="true"></pre>' +
      '    <textarea class="tpv-input" id="tpvInput" spellcheck="false" wrap="off" autocomplete="off"' +
      '              autocapitalize="off" aria-label="' + _escapeHtml(res.path) + '"></textarea>' +
      '  </div>' +
      '</div>' +
      '<div class="tpv-problems" id="tpvProblems" hidden></div>';

    var ta = document.getElementById('tpvInput');
    ta.value = res.content;
    var ed = _tpvEditor = { root: root, path: res.path, sha: res.sha256, original: res.content,
                            textarea: ta, lines: -1, savedAt: '' };
    _tpvRefreshEditor();

    ta.addEventListener('input', function () {
      if (_tpvEditor !== ed) return;
      _tpvRefreshEditor();
      _tpvStoreDraft(ed);
    });
    ta.addEventListener('scroll', _tpvSyncScroll);
    ta.addEventListener('keydown', _tpvKeydown);
    document.getElementById('tpvSave').addEventListener('click', function () { _tpvSave(false); });
    document.getElementById('tpvCheck').addEventListener('click', _tpvCheck);
    document.getElementById('tpvRevert').addEventListener('click', function () {
      showConfirm('Revert ' + ed.path + ' to the saved version? Your changes are lost.', function () {
        if (_tpvEditor !== ed) return;
        ta.value = ed.original;
        _tpvClearDraft(ed.root, ed.path);
        _tpvRefreshEditor();
        _tpvShowProblems([], false);
      });
    });
    _tpvWireCopyRun(res.path);

    // Offer unsaved changes left over from an earlier session.
    var draft = _tpvLoadDraft(root, res.path);
    if (draft && typeof draft.content === 'string' && draft.content !== res.content) {
      var changed = draft.base && draft.base !== res.sha256;
      var banner = document.getElementById('tpvBanner');
      banner.innerHTML =
        '<div class="dev-note"><i class="bi bi-clock-history me-1"></i>You have unsaved changes to this file from ' +
        'an earlier session' + (changed ? ', and the file has changed on disk since \u2014 restoring and saving would replace that change' : '') +
        '. <span class="tp-links d-inline-flex ms-1"><a href="#" id="tpvRestoreDraft">Restore them</a>' +
        '<a href="#" id="tpvDropDraft">Discard them</a></span></div>';
      document.getElementById('tpvRestoreDraft').addEventListener('click', function (e) {
        e.preventDefault();
        if (_tpvEditor !== ed) return;
        ta.value = draft.content;
        banner.innerHTML = '';
        _tpvRefreshEditor();
      });
      document.getElementById('tpvDropDraft').addEventListener('click', function (e) {
        e.preventDefault();
        _tpvClearDraft(root, res.path);
        banner.innerHTML = '';
      });
    }
  }

  function _tpvRefreshEditor() {
    var ed = _tpvEditor;
    if (!ed || !ed.textarea) return;
    var hl = document.getElementById('tpvHl');
    if (!hl) return;
    var value = ed.textarea.value;
    hl.innerHTML = _rfHighlight(value);
    var lines = value.split('\n').length;
    if (lines !== ed.lines) {
      ed.lines = lines;
      var nums = [];
      for (var i = 1; i <= lines; i++) nums.push(i);
      document.getElementById('tpvGutter').textContent = nums.join('\n');
    }
    _tpvSyncScroll();
    var dirty = value !== ed.original;
    var save = document.getElementById('tpvSave');
    var revert = document.getElementById('tpvRevert');
    if (save) save.disabled = !dirty;
    if (revert) revert.disabled = !dirty;
    _tpvStatus(dirty ? '\u25cf Unsaved changes' : (ed.savedAt ? 'Saved at ' + ed.savedAt : ''), dirty);
    var item = document.querySelector('#testProjectTree [data-tpv-path="' + ed.path.replace(/"/g, '\\"') + '"] .tpv-item-label');
    if (item) {
      var dot = item.querySelector('.tpv-unsaved');
      if (dirty && !dot) item.insertAdjacentHTML('beforeend', ' <span class="tpv-unsaved" title="Unsaved changes">\u25cf</span>');
      if (!dirty && dot) dot.remove();
    }
  }

  function _tpvStatus(text, dirty) {
    var el = document.getElementById('tpvEditStatus');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('dirty', !!dirty);
  }

  function _tpvSyncScroll() {
    var ed = _tpvEditor;
    if (!ed || !ed.textarea) return;
    var hl = document.getElementById('tpvHl');
    var gutter = document.getElementById('tpvGutter');
    if (hl) hl.style.transform = 'translate(' + (-ed.textarea.scrollLeft) + 'px,' + (-ed.textarea.scrollTop) + 'px)';
    if (gutter) gutter.style.transform = 'translateY(' + (-ed.textarea.scrollTop) + 'px)';
  }

  function _tpvKeydown(e) {
    var ta = e.target;
    if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
      e.preventDefault();
      _tpvSave(false);
      return;
    }
    if (e.key === 'Tab' && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      if (!e.shiftKey) {
        // Robot separates cells with 2+ spaces; 4 keeps columns readable.
        document.execCommand('insertText', false, '    ');
        return;
      }
      var s = ta.selectionStart;
      var lineStart = ta.value.lastIndexOf('\n', s - 1) + 1;
      var lead = /^ {1,4}/.exec(ta.value.slice(lineStart));
      if (lead) {
        ta.setSelectionRange(lineStart, lineStart + lead[0].length);
        document.execCommand('delete');
        var pos = Math.max(lineStart, s - lead[0].length);
        ta.setSelectionRange(pos, pos);
      }
      return;
    }
    if (e.key === 'Enter' && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) {
      var start = ta.selectionStart;
      var ls = ta.value.lastIndexOf('\n', start - 1) + 1;
      var indent = /^[ \t]*/.exec(ta.value.slice(ls, start))[0];
      if (indent) {
        e.preventDefault();
        document.execCommand('insertText', false, '\n' + indent);
      }
    }
  }

  function _tpvSave(force) {
    var ed = _tpvEditor;
    if (!ed || !ed.textarea) return;
    var content = ed.textarea.value;
    if (content === ed.original && !force) return;
    var save = document.getElementById('tpvSave');
    if (save) save.disabled = true;
    _tpvStatus('Saving\u2026', false);
    MM.testProjectClient.saveFile(ed.root, ed.path, content, ed.sha, force)
      .then(function (res) {
        if (_tpvEditor !== ed) return;
        ed.sha = res.sha256;
        ed.original = content;
        ed.savedAt = new Date().toLocaleTimeString();
        _tpvClearDraft(ed.root, ed.path);
        document.getElementById('tpvBanner').innerHTML = '';
        _tpvRefreshEditor();
        var problems = res.problems || [];
        _tpvShowProblems(problems, false);
        showToast('Saved', ed.path + (problems.length
          ? ' \u2014 ' + problems.length + ' syntax problem' + (problems.length === 1 ? '' : 's')
          : ''), problems.length ? 'warning' : 'success');
        _tpvRefreshTree();
      })
      .catch(function (err) {
        if (_tpvEditor !== ed) return;
        _tpvRefreshEditor();
        if (err.code === 'conflict') {
          var banner = document.getElementById('tpvBanner');
          banner.innerHTML =
            '<div class="dev-alert dev-alert-warning"><strong>Changed on disk</strong>' +
            '<div>' + _escapeHtml(err.message || '') + '</div>' +
            '<div class="tp-links"><a href="#" id="tpvOverwrite">Overwrite with my version</a>' +
            '<a href="#" id="tpvReloadDisk">Reload from disk (drops my changes)</a></div></div>';
          document.getElementById('tpvOverwrite').addEventListener('click', function (e) {
            e.preventDefault();
            _tpvSave(true);
          });
          document.getElementById('tpvReloadDisk').addEventListener('click', function (e) {
            e.preventDefault();
            _tpvClearDraft(ed.root, ed.path);
            _tpvEditor = null;
            _showTpvFile(ed.path);
          });
          _tpvStatus('Not saved \u2014 changed on disk', true);
        } else {
          _tpvStatus('Not saved', true);
          showToast('Save failed', err.message || String(err), 'danger');
        }
      });
  }

  function _tpvCheck() {
    var ed = _tpvEditor;
    if (!ed || !ed.textarea) return;
    MM.testProjectClient.checkFile(ed.path, ed.textarea.value)
      .then(function (res) {
        if (_tpvEditor === ed) _tpvShowProblems(res.problems || [], true);
      })
      .catch(function (err) {
        showToast('Check', err.message || String(err), 'danger');
      });
  }

  function _tpvShowProblems(problems, announceClean) {
    var box = document.getElementById('tpvProblems');
    if (!box) return;
    if (!problems.length) {
      box.hidden = !announceClean;
      box.className = 'tpv-problems tpv-problems-ok';
      box.innerHTML = '<i class="bi bi-check2-circle me-1"></i>No syntax problems.';
      return;
    }
    box.hidden = false;
    box.className = 'tpv-problems';
    box.innerHTML =
      '<div class="tpv-problems-title"><i class="bi bi-exclamation-triangle me-1"></i>' + problems.length +
      ' syntax problem' + (problems.length === 1 ? '' : 's') + '</div>' +
      problems.map(function (p) {
        return '<div class="tpv-problem" data-line="' + (p.line || 1) + '">Line ' + (p.line || '?') + ': ' +
               _escapeHtml(p.message || '') + '</div>';
      }).join('');
    box.querySelectorAll('.tpv-problem').forEach(function (el) {
      el.addEventListener('click', function () { _tpvGotoLine(parseInt(el.getAttribute('data-line'), 10)); });
    });
  }

  function _tpvGotoLine(line) {
    var ed = _tpvEditor;
    if (!ed || !ed.textarea) return;
    var ta = ed.textarea;
    var idx = 0;
    for (var i = 1; i < line; i++) {
      var next = ta.value.indexOf('\n', idx);
      if (next < 0) break;
      idx = next + 1;
    }
    ta.focus();
    var end = ta.value.indexOf('\n', idx);
    ta.setSelectionRange(idx, end < 0 ? ta.value.length : end);
    var lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 18;
    ta.scrollTop = Math.max(0, (line - 4) * lineHeight);
    _tpvSyncScroll();
  }

  function _tpvRefreshTree() {
    var root = _getTestProject();
    MM.testProjectClient.tree(root)
      .then(function (data) {
        if (_getTestProject() !== root) return;
        _tpView.data = data;
        _renderTpvSidebar(data);
      })
      .catch(function () { /* the sidebar keeps its last state */ });
  }

  // Drafts: unsaved text survives a reload (localStorage, per project + file).
  function _tpvDraftKey(root, path) {
    return 'mm_tpv_draft:' + root + '|' + path;
  }

  function _tpvStoreDraft(ed) {
    clearTimeout(_tpvDraftTimer);
    _tpvDraftTimer = setTimeout(function () {
      try {
        var key = _tpvDraftKey(ed.root, ed.path);
        if (ed.textarea.value === ed.original) localStorage.removeItem(key);
        else localStorage.setItem(key, JSON.stringify({ base: ed.sha, content: ed.textarea.value, at: Date.now() }));
      } catch (e) { /* storage unavailable or full */ }
    }, 400);
  }

  function _tpvLoadDraft(root, path) {
    try {
      var raw = localStorage.getItem(_tpvDraftKey(root, path));
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function _tpvClearDraft(root, path) {
    clearTimeout(_tpvDraftTimer);
    try { localStorage.removeItem(_tpvDraftKey(root, path)); } catch (e) { /* storage unavailable */ }
  }

  /**
   * Robot Framework highlighting for the editor overlay: sections, comments,
   * settings, test/keyword names, [settings], variables and continuations.
   * Output must stay character-for-character aligned with the textarea, so
   * only spans are added -- never text.
   */
  function _rfHighlight(text) {
    var section = '';
    return text.split('\n').map(function (line) {
      var head = /^\s*\*{3}\s*([^*]+?)\s*\*{3}/.exec(line);
      if (head) {
        section = head[1].toLowerCase();
        return '<span class="rf-sec">' + _escapeHtml(line) + '</span>';
      }
      if (/^\s*#/.test(line)) return '<span class="rf-com">' + _escapeHtml(line) + '</span>';

      var code = line;
      var comment = '';
      var cm = /(?: {2,}|\t)#/.exec(line);
      if (cm) {
        code = line.slice(0, cm.index);
        comment = '<span class="rf-com">' + _escapeHtml(line.slice(cm.index)) + '</span>';
      }
      var out = _escapeHtml(code)
        .replace(/((?:[$@%]|&amp;)\{[^}\n]*\})/g, '<span class="rf-var">$1</span>')
        // [Tags] etc. are settings only at the start of a cell; ${d}[key] is item access.
        .replace(/(^\s+|\t| {2,})(\[[A-Za-z][A-Za-z ]*\])/g, '$1<span class="rf-set">$2</span>')
        .replace(/^(\s*)(\.\.\.)/, '$1<span class="rf-cont">$2</span>');

      if (code.trim() && !/^\s/.test(code) && !/^\.\.\./.test(code)) {
        if (section.indexOf('setting') === 0) {
          out = out.replace(/^(\S(?:.*?\S)?)( {2,}|\t|$)/, '<span class="rf-key">$1</span>$2');
        } else if (section.indexOf('test case') === 0 || section.indexOf('task') === 0 ||
                   section.indexOf('keyword') === 0) {
          out = '<span class="rf-name">' + out + '</span>';
        }
      }
      return out + comment;
    }).join('\n') + '\n';
  }

  function _showTpvNewSuite(data) {
    _tpView.selected = null;
    _tpvEditor = null;
    _renderTpvSidebar(data);
    var content = document.getElementById('testProjectContent');
    var layout = data.layout || {};
    var options = data.services.map(function (s) {
      return '<option value="' + _escapeHtml(s.name) + '">' + _escapeHtml(s.name) + '</option>';
    }).join('');

    content.innerHTML =
      '<div class="tpv-view">' +
      '  <div class="tpv-file-head">' +
      '    <a href="#" class="tpv-back" id="tpvBack"><i class="bi bi-arrow-left me-1"></i>Overview</a>' +
      '    <strong>New suite</strong>' +
      '  </div>' +
      '  <section class="svc-ov-card tpv-new-suite">' +
      '    <div class="mb-3">' +
      '      <label class="form-label small" for="tpvSuiteName">Name</label>' +
      '      <div class="input-group input-group-sm">' +
      '        <input type="text" class="form-control" id="tpvSuiteName" placeholder="e.g. greeting_checks" spellcheck="false">' +
      '        <span class="input-group-text">.robot</span>' +
      '      </div>' +
      '      <div class="form-text">Created in <code>' + _escapeHtml(layout.suites || '') + '/</code>. Letters, digits, <code>_</code> or <code>-</code>.</div>' +
      '    </div>' +
      '    <div class="mb-3">' +
      '      <label class="form-label small" for="tpvSuiteService">Service</label>' +
      '      <select class="form-select form-select-sm" id="tpvSuiteService">' +
      '        <option value="">None \u2014 an empty suite</option>' + options +
      '      </select>' +
      '      <div class="form-text">Imports the service\'s generated keywords and opens its connection in the suite setup.</div>' +
      '    </div>' +
      '    <div id="tpvSuiteError"></div>' +
      '    <button type="button" class="btn btn-sm btn-primary" id="tpvSuiteCreate">' +
      '      <i class="bi bi-file-earmark-plus me-1"></i>Create and edit</button>' +
      '  </section>' +
      '</div>';

    if (data.services.length) document.getElementById('tpvSuiteService').value = data.services[0].name;
    _tpvWireBack(data);
    var name = document.getElementById('tpvSuiteName');
    var create = document.getElementById('tpvSuiteCreate');
    function submit() {
      create.disabled = true;
      document.getElementById('tpvSuiteError').innerHTML = '';
      MM.testProjectClient.newSuite(_getTestProject(), name.value.trim(), document.getElementById('tpvSuiteService').value)
        .then(function (res) {
          showToast('New suite', res.path + ' created.', 'success');
          _tpView.selected = res.path;
          renderTestProjectView();
        })
        .catch(function (err) {
          create.disabled = false;
          document.getElementById('tpvSuiteError').innerHTML = _devAlert('warning', 'Not created', err.message || err);
        });
    }
    create.addEventListener('click', submit);
    name.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    });
    name.focus();
  }
  // Signal Graph Studio: its own window (own preload + "gs:" IPC), so it
  // is Electron-only. Seed its live panel with the Consul we are on and the
  // interpreter from Settings — the studio runs Python for "Run cluster"
  // and "Regenerate catalog", and a bare "python" is often a stub.
  // Reached through the graph-studio plugin's command (shell action).
  function _openGraphStudio() {
    if (!window.electronAPI || !window.electronAPI.openGraphStudio) {
      showToast('Signal Graph Studio',
        'Available in the Electron app only — it opens a separate window.', 'warning');
      return;
    }
    var consul = _connectedConsuls.length ? _connectedConsuls[0].url : '';
    var python = (_settings && _settings.pythonPath) || '';
    window.electronAPI.openGraphStudio({ consulUrl: consul, python: python })
      .then(function () {
        showToast('Signal Graph Studio', 'Opened in a separate window.', 'info');
      })
      .catch(function (err) {
        showToast('Signal Graph Studio', 'Could not open: ' + (err.message || err), 'danger');
      });
  }
  _wire('btnDevDownload', function () {
    _withSelectedService('Download service files', function (sel) {
      if (!sel.info || !sel.info.downloadable) {
        showToast('Download service files',
          sel.name + ' does not offer downloadable files (only registry services with a GUI package do).',
          'info');
        return;
      }
      downloadServiceFiles(sel.name);
    });
  });

  // Administrator Tools -- configure infrastructure
  _wire('btnAdminConsul', function () { switchToFleetSubTab('tabConsul'); });
  _wire('btnAdminNomad', function () { switchToFleetSubTab('tabNomad'); });

  /**
   * Footer tabs at the bottom of the left pane. Services and the test
   * project are the two things the pane can show, so they switch here
   * instead of only through the Developer Tools menu. Neither tab is
   * highlighted in the Service Network / Creator views; clicking one
   * leaves those views the same way the navbar does.
   */
  function _syncSidebarSwitch() {
    // Built-in tabs and plugin navigators alike carry data-mode.
    document.querySelectorAll('#sidebarSwitch .sidebar-switch-tab[data-mode]').forEach(function (btn) {
      var on = _currentMode === btn.getAttribute('data-mode');
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    var project = document.querySelector('#sidebarSwitch .sidebar-switch-tab[data-mode="testproject"]');
    if (project) {
      var root = _getTestProject();
      // The tab works either way: with no project open the view offers to
      // open one, so say that instead of looking broken.
      project.title = root ? 'Test project: ' + root
                           : 'No test project open — click to choose a folder';
    }
  }

  _wire('sidebarSwitchServices', function () { switchMode('services'); });
  _wire('sidebarSwitchBench', function () { switchMode('bench'); });
  _wire('btnModeBench', function () { switchMode('bench'); });
  _syncSidebarSwitch();

  /************************************************************
   *                         Ribbon                            *
   ************************************************************/
  // Three tabs name the command groups; the band below shows the selected
  // group. User and Administrator also open their view. Developer does
  // not: its "selected service" commands act on the service selected in
  // the Services view, so switching away would break them.

  var RIBBON_PIN_KEY = 'mm_ribbon_pinned';
  var _ribbonTab = 'user';
  var _ribbonOpenTab = null;   // tab whose band is dropped down (auto-hide)

  var RIBBON_TABS = {
    user:  { btn: 'btnModeServices', panel: 'ribbonUser' },
    dev:   { btn: 'btnDevTools',     panel: 'ribbonDev' },
    admin: { btn: 'btnAdminTools',   panel: 'ribbonAdmin' }
  };

  function _ribbonTabForMode(mode) {
    if (mode === 'fleet') return 'admin';
    if (mode === 'creator' || mode === 'testproject') return 'dev';
    if (mode === 'services' || mode === 'bench') return 'user';
    return _ribbonTab;
  }

  /**
   * Show one group's commands.
   *
   * @param {string} tab - 'user' | 'dev' | 'admin'
   * @param {{fromMode?: boolean}} [opts] - set when called by switchMode,
   *   so a view change moves the ribbon without re-entering switchMode.
   */
  function _setRibbonTab(tab, opts) {
    if (!RIBBON_TABS[tab]) return;
    _ribbonTab = tab;
    Object.keys(RIBBON_TABS).forEach(function (key) {
      var on = key === tab;
      var btn = document.getElementById(RIBBON_TABS[key].btn);
      var panel = document.getElementById(RIBBON_TABS[key].panel);
      if (btn) {
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
      }
      if (panel) {
        panel.classList.toggle('active', on);
        panel.hidden = !on;
      }
    });
  }

  function _ribbonPinned() {
    return document.body.classList.contains('ribbon-pinned');
  }

  function _ribbonIsOpen() {
    var ribbon = document.getElementById('ribbon');
    return !!ribbon && ribbon.classList.contains('peek');
  }

  // Auto-hide (default): drop the band down over the content for one tab.
  function _openRibbon(tab) {
    if (_ribbonPinned()) return;
    var ribbon = document.getElementById('ribbon');
    if (ribbon) ribbon.classList.add('peek');
    _ribbonOpenTab = tab;
  }

  function _closeRibbon() {
    var ribbon = document.getElementById('ribbon');
    if (ribbon) ribbon.classList.remove('peek');
    _ribbonOpenTab = null;
  }

  // Pinned: the band stays open and the layout makes room for it.
  function _setRibbonPinned(on) {
    on = !!on;
    document.body.classList.toggle('ribbon-pinned', on);
    _closeRibbon();
    try { localStorage.setItem(RIBBON_PIN_KEY, on ? '1' : '0'); } catch (e) { /* storage unavailable */ }
    var btn = document.getElementById('btnRibbonToggle');
    if (btn) {
      btn.title = on ? 'Unpin the ribbon (hide it after each use)' : 'Pin the ribbon open';
      var icon = btn.querySelector('i');
      if (icon) icon.className = on ? 'bi bi-pin-angle-fill' : 'bi bi-pin-angle';
    }
    if (MM._alignInspector) MM._alignInspector();
  }

  Object.keys(RIBBON_TABS).forEach(function (key) {
    var btn = document.getElementById(RIBBON_TABS[key].btn);
    if (!btn) return;
    btn.addEventListener('click', function () {
      // Decide open/close from the band's state before this click, not from
      // _ribbonTab.
      var closeIt = _ribbonIsOpen() && _ribbonOpenTab === key;
      // Always select the tab here. Relying on switchMode alone left a tab
      // dead whenever its view was already showing (switchMode returns
      // early for the current mode), e.g. Developer -> User on Services.
      _setRibbonTab(key);
      // User keeps the bench when it is showing: its components' commands are on this tab.
      if (key === 'user' && _currentMode !== 'bench') switchMode('services');
      else if (key === 'admin') switchToFleetSubTab('tabConsul');
      if (closeIt) _closeRibbon(); else _openRibbon(key);
    });
  });

  _wire('btnRibbonToggle', function () { _setRibbonPinned(!_ribbonPinned()); });

  // Hide the dropped-down band after a command, a click anywhere else, Esc,
  // or focus leaving the window (clicks into an embedded GUI's iframe never
  // reach this document). Toggles and bridge buttons keep it open, since
  // their feedback is in the band itself.
  var _ribbonEl = document.getElementById('ribbon');
  if (_ribbonEl) {
    _ribbonEl.addEventListener('click', function (ev) {
      if (ev.target.closest('.ribbon-btn, .btn-connect, .infra-pill')) _closeRibbon();
    });
  }
  document.addEventListener('mousedown', function (ev) {
    if (!_ribbonIsOpen()) return;
    if (ev.target.closest('#ribbon, .ribbon-tab, #btnRibbonToggle')) return;
    _closeRibbon();
  }, true);
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && _ribbonIsOpen()) _closeRibbon();
  });
  window.addEventListener('blur', function () { if (_ribbonIsOpen()) _closeRibbon(); });

  try {
    localStorage.removeItem('mm_ribbon_collapsed');   // superseded by the pin
    _setRibbonPinned(localStorage.getItem(RIBBON_PIN_KEY) === '1');
  } catch (e) { _setRibbonPinned(false); }
  _setRibbonTab(_ribbonTabForMode(_currentMode), { fromMode: true });

  // Live signals: without an explicit discovery address the bridge looks
  // signal-discovery up in the first reachable Consul this window uses.
  if (MM.endo && MM.endo.bus) {
    MM.endo.bus.configure({
      getConsul: function () {
        var c = _connectedConsuls.filter(function (x) { return x.alive !== false; })[0];
        return c ? c.url : '';
      }
    });
  }

  var _reopenOnServices = false;
  function _reopenSelectedService() {
    _reopenOnServices = false;
    if (_selectedService && _selectedService.consul && _selectedService.consul.gui) _openConsulServiceGui(_selectedService);
  }

  // Plugins (js/endo/plugins.js): the shell actions and views their
  // commands and navigators may name, and nothing else.
  if (MM.endo && MM.endo.plugins) {
    MM.endo.plugins.init({
      actions: {
        robotGen: function () { _runRobotGen('', null); },
        openGraphStudio: _openGraphStudio,
        testProjectView: _testProjectView,
        openTestProject: function () { return openTestProject(); }
      },
      views: {
        testproject: { sidebar: 'sidebarTestProject', content: 'testProjectContent' }
      },
      switchMode: function (mode) { switchMode(mode); },
      currentMode: function () { return _currentMode; }
    });
    MM.endo.plugins.onChange(function (ev) {
      _syncSidebarSwitch();
      if (ev && ev.ready) return;
      // A kind came or went: component panels in the Services view are
      // mounted again so their tiles pick it up (or show the placeholder).
      var dropActive = false;
      Object.keys(_servicePanels).forEach(function (name) {
        var panel = _servicePanels[name];
        if (!panel || !panel.__endoHandle) return;
        if (_activePanelName === name) { _deactivateCurrentPanel(); dropActive = true; }
        panel.__endoHandle.destroy();
        try { panel.remove(); } catch (e) { /* already gone */ }
        delete _servicePanels[name];
      });
      // Remount the shown one now, or when the Services view comes back
      // (mounting it hidden would start polling off-screen, R5).
      if (dropActive) {
        if (_currentMode === 'services') _reopenSelectedService();
        else _reopenOnServices = true;
      }
      if (MM.endo.bench) MM.endo.bench.pluginsChanged();
    });
  }

  // The bench view (js/endo/bench.js) composes components of the services
  // this window is connected to; it reaches the rest of the GUI only here.
  if (MM.endo && MM.endo.bench) {
    MM.endo.bench.init({
      getServices: _allConnectedServices,
      openService: _openServiceFromBench,
      openInspector: function (svc, tab) {
        _openServiceFromBench(svc);
        setDevMode(true, { tab: tab, silent: true });
      },
      showApi: function (svc, containerId) {
        // The explorer wires its controls by id: keep one copy in the DOM.
        var box = document.getElementById(containerId);
        document.querySelectorAll('[data-dev-panel="api-explorer"]').forEach(function (p) {
          if (!box || !box.contains(p)) p.remove();
        });
        _inspectorKey = null;   // the inspector re-renders when shown again
        _showGrpcServicePanel(svc, { containerId: containerId, compact: true });
        // The dock has its own Code tab; this button targets the inspector.
        var code = box && box.querySelector('#grpcCodeExamples');
        if (code) code.hidden = true;
      },
      protoPathFor: _getStoredProtoPath,
      setRibbonTab: function (tab) { _setRibbonTab(tab); }
    });
  }

  /**
   * The service currently highlighted in the sidebar, recorded by both
   * click paths. Consul-discovered rows and legacy registry items key
   * MM.servicesInfor differently (name@consulUrl vs. name) and open
   * different explorers, so the menu tools read this instead of guessing.
   *   { name, infoKey, consul: <svc object with consulUrl> | null }
   */
  var _selectedService = null;

  /************************************************************
   *                Developer mode + inspector                 *
   ************************************************************/

  // Developer mode is a persistent switch, like a browser's devtools:
  // the runtime view stays exactly as it is and an inspector docks on
  // the right showing the selected service's API, details and client
  // code. Turning it off removes the inspector and nothing else.
  var DEV_MODE_KEY = 'mm_dev_mode';
  var _devMode = false;
  var _inspectorTab = 'api';
  var _inspectorKey = null;   // what the inspector currently shows

  function setDevMode(on, opts) {
    opts = opts || {};
    on = !!on;
    _devMode = on;
    try { localStorage.setItem(DEV_MODE_KEY, on ? '1' : '0'); } catch (e) { /* storage unavailable */ }
    document.body.classList.toggle('dev-mode', on);
    var sw = document.getElementById('devModeSwitch');
    if (sw) sw.checked = on;
    var pill = document.getElementById('devModePill');
    if (pill) pill.hidden = !on;
    var btn = document.getElementById('btnDevTools');
    if (btn) btn.classList.toggle('dev-on', on);
    if (opts.tab) _inspectorTab = opts.tab;
    _syncInspector();
    if (!opts.silent) {
      showToast('Developer mode', on
        ? 'On \u2014 the inspector shows the API, details and client code of the selected service.'
        : 'Off', 'info');
    }
  }
  MM.setDevMode = setDevMode;
  MM.isDevMode = function () { return _devMode; };

  function _syncInspector() {
    var el = document.getElementById('devInspector');
    var layout = document.querySelector('.app-layout');
    if (!el || !layout) return;
    var show = _devMode && _currentMode === 'services';
    el.hidden = !show;
    layout.classList.toggle('with-inspector', show);
    if (show) {
      if (MM._alignInspector) MM._alignInspector();
      _renderInspector(_selectedService);
    }
  }

  function _setInspectorTab(tab) {
    _inspectorTab = tab;
    _inspectorKey = null;
    _renderInspector(_selectedService);
  }

  function _renderInspector(sel) {
    var el = document.getElementById('devInspector');
    if (!el || el.hidden) return;
    var key = (sel ? sel.infoKey : '') + '|' + _inspectorTab;
    if (key === _inspectorKey) return;
    _inspectorKey = key;

    var testProject = _getTestProject();
    var head =
      '<div class="dev-inspector-head">' +
      '  <div class="dev-inspector-crumb"><i class="bi bi-code-slash me-1"></i>Developer</div>' +
      '  <div class="dev-inspector-title">' + (sel ? _escapeHtml(sel.name) : 'Inspector') + '</div>' +
      (sel && sel.consul
        ? '<code class="dev-inspector-target">' + _escapeHtml((sel.consul.address || '?') + ':' + (sel.consul.port || '?')) + '</code>'
        : '') +
      '  <button type="button" class="dev-project-chip" id="devProjectChip"' +
      '          title="' + (testProject ? 'Test project: ' + _escapeHtml(testProject) + ' (click to change)' : 'Open a test project') + '">' +
      '    <i class="bi bi-folder2' + (testProject ? '-open' : '') + ' me-1"></i>' +
             (testProject ? _escapeHtml(_projectLabel(testProject)) : 'No test project') + '</button>' +
      '  <button type="button" class="dev-inspector-close" id="devInspectorClose" title="Turn developer mode off">' +
      '    <i class="bi bi-x-lg"></i></button>' +
      '</div>';

    if (!sel) {
      el.innerHTML = head +
        '<div class="dev-inspector-empty">' +
        '  <i class="bi bi-cursor"></i>' +
        '  <div>Select a service in the sidebar to inspect its API, details and client code.</div>' +
        '</div>';
      _wireInspectorClose();
      return;
    }

    var tabs = [['api', 'bi-diagram-3', 'API'], ['details', 'bi-list-ul', 'Details'], ['code', 'bi-file-earmark-code', 'Code']];
    el.innerHTML = head +
      '<div class="dev-inspector-tabs">' +
      tabs.map(function (t) {
        return '<button type="button" class="dev-inspector-tab' + (t[0] === _inspectorTab ? ' active' : '') + '"' +
               ' data-tab="' + t[0] + '"><i class="bi ' + t[1] + ' me-1"></i>' + t[2] + '</button>';
      }).join('') +
      '</div>' +
      '<div class="dev-inspector-body" id="devInspectorBody"></div>';
    _wireInspectorClose();
    el.querySelectorAll('.dev-inspector-tab').forEach(function (b) {
      b.addEventListener('click', function () { _setInspectorTab(b.getAttribute('data-tab')); });
    });

    var body = document.getElementById('devInspectorBody');
    if (_inspectorTab === 'api') {
      if (sel.consul) _showGrpcServicePanel(sel.consul, { containerId: 'devInspectorBody', compact: true });
      else body.innerHTML = _devAlert('warning', 'Registry service',
        'Reflection-based exploration needs a Consul-registered gRPC service. Use Code Examples for this one.');
    } else if (_inspectorTab === 'details') {
      _renderInspectorDetails(sel, body);
    } else {
      _renderInspectorCode(sel, body);
    }
  }

  function _wireInspectorClose() {
    var c = document.getElementById('devInspectorClose');
    if (c) c.addEventListener('click', function () { setDevMode(false); });
    var chip = document.getElementById('devProjectChip');
    if (chip) chip.addEventListener('click', function () { openTestProject(); });
  }

  function _renderInspectorDetails(sel, body) {
    var svc = sel.consul;
    var info = sel.info || MM.servicesInfor[sel.infoKey] || {};
    function table(rows) {
      return '<table class="svc-card-table">' + rows.map(function (r) {
        return '<tr><th>' + _escapeHtml(r[0]) + '</th><td>' + r[1] + '</td></tr>';
      }).join('') + '</table>';
    }
    if (!svc) {
      body.innerHTML = '<div class="dev-inspector-section"><h6>Registry entry</h6>' +
        table(Object.keys(info).map(function (k) {
          return [k, '<code>' + _escapeHtml(typeof info[k] === 'object' ? JSON.stringify(info[k]) : String(info[k])) + '</code>'];
        })) + '</div>';
      return;
    }
    body.innerHTML =
      '<div class="dev-inspector-section"><h6>Service</h6>' +
      table([
        ['Name', _escapeHtml(svc.name)],
        ['Registry', '<code>' + _escapeHtml(svc.consulUrl || '') + '</code>'],
        ['Tags', (svc.tags || []).map(function (t) { return '<span class="dev-tag">' + _escapeHtml(t) + '</span>'; }).join(' ') || '<span class="text-muted">none</span>'],
        ['gRPC services', svc.grpcServices ? '<code>' + _escapeHtml(svc.grpcServices) + '</code>' : '<span class="text-muted">unknown</span>'],
        ['GUI plugin', svc.gui ? '<code>' + _escapeHtml(svc.gui) + '</code>' : '<span class="text-muted">none</span>']
      ]) + '</div>' +
      '<div class="dev-inspector-section"><h6>Instances</h6><div id="devInspInstances">' + _devLoading('Loading\u2026') + '</div></div>';

    MM.consulClient.getServiceDetail(svc.name, svc.consulUrl)
      .then(function (entries) {
        var el = document.getElementById('devInspInstances');
        if (!el) return;
        if (!Array.isArray(entries) || !entries.length) { el.innerHTML = '<span class="text-muted small">None registered.</span>'; return; }
        el.innerHTML = entries.map(function (e) {
          var s = e.Service || {};
          var meta = s.Meta || {};
          return '<div class="dev-inst">' +
            '<div class="dev-inst-head"><span class="svc-ov-dot svc-ov-dot-' + _worstCheck(e.Checks) + '"></span>' +
            '<code>' + _escapeHtml(s.ID || '') + '</code><span class="dev-inst-addr">' + _escapeHtml((s.Address || '?') + ':' + (s.Port || '?')) + '</span></div>' +
            (Object.keys(meta).length
              ? '<div class="dev-inst-meta">' + Object.keys(meta).map(function (k) {
                  return '<span><b>' + _escapeHtml(k) + '</b> ' + _escapeHtml(String(meta[k])) + '</span>';
                }).join('') + '</div>'
              : '') +
            '<div class="dev-inst-checks">' + (e.Checks || []).map(function (c) {
              return '<span class="svc-ov-check svc-ov-check-' + _escapeHtml(c.Status || 'unknown') + '" title="' + _escapeHtml(c.Output || '') + '">' + _escapeHtml(c.Name || c.CheckID || 'check') + '</span>';
            }).join('') + '</div>' +
            '</div>';
        }).join('');
      })
      .catch(function (err) {
        var el = document.getElementById('devInspInstances');
        if (el) el.innerHTML = _devAlert('warning', 'Could not load instances', err.message || err);
      });
  }

  function _renderInspectorCode(sel, body) {
    var serviceInfo = MM.servicesInfor[sel.infoKey];
    if (!serviceInfo) {
      body.innerHTML = _devAlert('warning', 'No service information', 'Nothing known about ' + sel.name + '.');
      return;
    }
    body.innerHTML =
      '<div class="dev-inspector-codebar">' +
      '  <span class="text-muted small">Client snippets generated from the live API.</span>' +
      '  <button type="button" class="btn btn-sm btn-outline-secondary" id="devInspCopy" title="Copy the active tab">' +
      '    <i class="bi bi-clipboard me-1"></i>Copy</button>' +
      '</div>' +
      '<div id="devInspCode">' + _devLoading('Discovering methods\u2026') + '</div>';
    var copy = document.getElementById('devInspCopy');
    if (copy) {
      copy.addEventListener('click', function () {
        var pane = body.querySelector('#devInspCode .tab-pane.active pre');
        if (pane) _copyText(pane.textContent, 'Code');
      });
    }
    var bridgeOrigin = (MM.serviceClient && MM.serviceClient.apiUrl) || window.location.origin;
    MM.grpcClient.getServiceMethods(serviceInfo.name, serviceInfo.consulUrl, _getStoredProtoPath(serviceInfo.name))
      .then(function (refl) {
        var note = (refl.error && (!refl.grpc_services || !refl.grpc_services.length))
          ? _devAlert('warning', 'Reflection failed', String(refl.error) + ' \u2014 snippets use empty request schemas.')
          : '';
        _renderHelperTabs(serviceInfo, refl, bridgeOrigin, note, { containerId: 'devInspCode', idPrefix: 'devInsp' });
      })
      .catch(function (err) {
        var el = document.getElementById('devInspCode');
        if (el) el.innerHTML = _devAlert('danger', 'Could not reach the bridge', err.message || err);
      });
  }

  // The inspector covers the content pane, so its left edge must follow
  // the sidebar, which the user can resize.
  (function () {
    var panel = document.getElementById('devInspector');
    var sidebar = document.querySelector('.app-sidebar');
    if (!panel || !sidebar) return;
    function align() {
      panel.style.left = Math.round(sidebar.getBoundingClientRect().right) + 'px';
    }
    align();
    if (window.ResizeObserver) new ResizeObserver(align).observe(sidebar);
    window.addEventListener('resize', align);
    MM._alignInspector = align;
  })();

  var devSwitch = document.getElementById('devModeSwitch');
  if (devSwitch) {
    devSwitch.addEventListener('change', function () { setDevMode(devSwitch.checked); });
    // Keep the dropdown open when toggling the switch.
    devSwitch.closest('.dropdown-item') && devSwitch.closest('.dropdown-item').addEventListener('click', function (e) { e.stopPropagation(); });
  }
  try {
    if (localStorage.getItem(DEV_MODE_KEY) === '1') setDevMode(true, { silent: true });
  } catch (e) { /* storage unavailable */ }

  /**
   * Run a per-service developer tool against the service selected in the
   * sidebar, or say why nothing happened.
   */
  function _withSelectedService(toolName, fn) {
    var active = document.querySelector('#servicesList .list-group-item.active[data-service-name]');
    var name = active && active.getAttribute('data-service-name');
    if (!name || !_selectedService || _selectedService.name !== name) {
      showToast(toolName, 'Select a service in the Services view first.', 'info');
      return;
    }
    fn(_selectedService);
  }

  /**
   * Open the Service Network view on a given sub-tab (Consul / Nomad).
   * Also used by the infra status pills in the navbar.
   */
  function switchToFleetSubTab(tabId) {
    switchMode('fleet');
    var tab = document.getElementById(tabId);
    if (tab && window.bootstrap && window.bootstrap.Tab) {
      window.bootstrap.Tab.getOrCreateInstance(tab).show();
    } else if (tab) {
      tab.click();
    }
  }
  MM.switchToFleetSubTab = switchToFleetSubTab;

  // Restore fleet URL from localStorage on page load
  try {
    var savedFleetUrl = localStorage.getItem('mm_fleet_api_url');
    if (savedFleetUrl && MM.fleetClient) {
      MM.fleetClient.configure(savedFleetUrl);
    }
  } catch (e) { /* localStorage unavailable */ }

  /************************************************************
   *               Expose functions for plugins               *
   ************************************************************/

  MM.requestService = requestService;
  MM.requestServiceDirect = function (data, queue) {
    var broker = resolveBrokerUrlForService(queue) || MM.brokerUrl;
    MM.serviceClient.setBrokerUrl(broker);
    return MM.serviceClient.requestServiceDirect(data, queue);
  };
  MM.loadContent = loadContent;
  MM.changeConnectButtonState = changeConnectButtonState;
  MM.showToast = showToast;
  MM.showConfirm = showConfirm;
  MM.showWarningDialog = showWarningDialog;
  MM.activateItemAndLoadContent = activateItemAndLoadContent;
  MM.SERVICES_EXCHANGE_NAME = SERVICES_EXCHANGE_NAME;
  MM.CONNECTION_STATUS = CONNECTION_STATUS;
  MM.SERVICES_GUI_FOLDER = SERVICES_GUI_FOLDER;

  /**
   * List files in a service GUI folder.
   * Works in both Electron (via preload) and web/FastAPI (via API) modes.
   * @param {string} folderPath - Relative path (e.g. "services/MyService1.0.0").
   * @returns {Promise<string[]>} Array of filenames.
   */
  MM.listServiceFiles = function (folderPath) {
    // Electron mode: use preload's synchronous fs.readdirSync
    if (window.electronAPI && typeof window.electronAPI.listDir === 'function') {
      return Promise.resolve(window.electronAPI.listDir(folderPath));
    }
    // Web/FastAPI mode: use list-dir API
    var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    return fetch(apiUrl + '/api/list-dir/' + encodeURIComponent(folderPath))
      .then(function (resp) {
        if (!resp.ok) throw new Error('list-dir failed');
        return resp.json();
      })
      .then(function (data) { return data.files || []; });
  };
  MM.showServiceAPIExplorer = showServiceAPIExplorer;
  MM.showServiceHelper = showServiceHelper;
  MM.switchMode = switchMode;

  /************************************************************
   *               Help Overlay                                 *
   ************************************************************/

  function openHelp() {
    if (_helpVisible) return;
    _modeBeforeHelp = _currentMode;
    _currentMode = '__help__';
    _helpVisible = true;

    // Hide sidebar, the ribbon and all content panels. The ribbon goes too:
    // its commands act on the views help is covering. A component behind
    // help stops polling (R5); closeHelp -> switchMode resumes it.
    _suspendActiveComponent();
    if (MM.endo && MM.endo.bench) MM.endo.bench.setActive(false);
    var sidebar = document.querySelector('.app-sidebar');
    if (sidebar) sidebar.style.display = 'none';

    var ribbon = document.getElementById('ribbon');
    if (ribbon) { ribbon.style.display = 'none'; ribbon.classList.remove('peek'); }

    ['serviceContent', 'fleetContent', 'creatorContent', 'testProjectContent', 'benchContent'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    document.querySelectorAll('.app-content > [data-endo-mode]').forEach(function (el) { el.style.display = 'none'; });
    if (MM.endo && MM.endo.plugins) MM.endo.plugins.modeChanged('__help__');

    // Unlight the ribbon tabs while help is on screen (closeHelp restores
    // them through switchMode).
    document.querySelectorAll('.ribbon-tab').forEach(function (btn) {
      btn.classList.remove('active');
    });

    // Highlight help button
    var btnHelp = document.getElementById('btnHelp');
    if (btnHelp) btnHelp.classList.add('active');

    // Show help content
    var helpContent = document.getElementById('helpContent');
    if (helpContent) {
      helpContent.style.display = '';
      // Load HTML on first open, refresh versions every time
      if (!_helpLoaded) {
        fetch('docs/help.html')
          .then(function (res) { return res.text(); })
          .then(function (html) {
            helpContent.innerHTML = html;
            _helpLoaded = true;
            _wireHelpTOC();
            _refreshHelpVersions();
          })
          .catch(function (err) {
            helpContent.innerHTML =
              '<div style="padding:2rem;color:#e74c3c;">' +
              '<i class="bi bi-exclamation-triangle me-2"></i>Failed to load help: ' +
              err.message + '</div>';
          });
      } else {
        _refreshHelpVersions();
      }
    }
  }

  /**
   * Internal: hide help overlay and restore DOM state, but do NOT call switchMode.
   */
  function _closeHelpOverlay() {
    if (!_helpVisible) return;
    _helpVisible = false;

    var btnHelp = document.getElementById('btnHelp');
    if (btnHelp) btnHelp.classList.remove('active');

    var helpContent = document.getElementById('helpContent');
    if (helpContent) helpContent.style.display = 'none';

    // Restore sidebar and ribbon
    var sidebar = document.querySelector('.app-sidebar');
    if (sidebar) sidebar.style.display = '';

    var ribbon = document.getElementById('ribbon');
    if (ribbon) ribbon.style.display = '';
  }

  function closeHelp() {
    if (!_helpVisible) return;
    var restoreMode = _modeBeforeHelp || 'services';
    _closeHelpOverlay();
    // Force switchMode by temporarily resetting _currentMode
    _currentMode = '__help__';
    switchMode(restoreMode);
  }

  function toggleHelp() {
    if (_helpVisible) {
      closeHelp();
    } else {
      openHelp();
    }
  }

  /**
   * Fetch and display version info. Called every time help is opened
   * so it picks up a bridge that started after first load.
   */
  function _refreshHelpVersions() {
    var helpContent = document.getElementById('helpContent');
    if (!helpContent) return;

    var guiVersionEl = helpContent.querySelector('#docsGuiVersion');
    var baseVersionEl = helpContent.querySelector('#docsBaseVersion');

    if (guiVersionEl && !guiVersionEl._loaded) {
      fetch('version.json')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          guiVersionEl.textContent = data.version || 'unknown';
          guiVersionEl._loaded = true;
        })
        .catch(function () {
          guiVersionEl.textContent = 'unknown';
        });
    }

    if (baseVersionEl) {
      if (window.electronAPI && window.electronAPI.getPackageVersion) {
        // Electron mode: query the Python configured in Settings
        var pythonPath = (_settings && _settings.pythonPath) || 'python';
        window.electronAPI.getPackageVersion(pythonPath, 'MicroserviceBase')
          .then(function (ver) {
            baseVersionEl.textContent = ver;
          });
      } else {
        baseVersionEl.textContent = 'unknown';
      }
    }
  }

  function _wireHelpTOC() {
    var helpContent = document.getElementById('helpContent');
    if (!helpContent) return;

    // Close button
    var closeBtn = helpContent.querySelector('#docsCloseBtn');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () { closeHelp(); });
    }

    // Smooth-scroll TOC links
    var tocLinks = helpContent.querySelectorAll('.docs-toc a[href^="#"]');
    var docsBody = helpContent.querySelector('#docsBody');

    tocLinks.forEach(function (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        var targetId = link.getAttribute('href').substring(1);
        var target = document.getElementById(targetId);
        if (target && docsBody) {
          var targetRect = target.getBoundingClientRect();
          var bodyRect = docsBody.getBoundingClientRect();
          docsBody.scrollTo({
            top: docsBody.scrollTop + (targetRect.top - bodyRect.top),
            behavior: 'smooth'
          });
        }
      });
    });

    // Scroll-spy: highlight active TOC link on scroll
    if (docsBody && tocLinks.length > 0) {
      var sections = helpContent.querySelectorAll('.docs-section[id]');
      docsBody.addEventListener('scroll', function () {
        var bodyRect = docsBody.getBoundingClientRect();
        var activeId = '';
        sections.forEach(function (sec) {
          var secRect = sec.getBoundingClientRect();
          if (secRect.top - bodyRect.top <= 40) {
            activeId = sec.id;
          }
        });
        tocLinks.forEach(function (link) {
          var isActive = link.getAttribute('href') === '#' + activeId;
          link.classList.toggle('active', isActive);
        });
      });
      // Trigger initial highlight
      tocLinks[0].classList.add('active');
    }

    // Click-to-zoom lightbox for images
    var docImages = helpContent.querySelectorAll('.docs-figure img');
    docImages.forEach(function (img) {
      img.addEventListener('click', function () {
        var overlay = document.createElement('div');
        overlay.className = 'docs-lightbox';
        var zoomed = document.createElement('img');
        zoomed.src = img.src;
        zoomed.alt = img.alt;
        overlay.appendChild(zoomed);
        overlay.addEventListener('click', function () {
          document.body.removeChild(overlay);
        });
        document.body.appendChild(overlay);
      });
    });
  }

  // Wire help button
  var btnHelp = document.getElementById('btnHelp');
  if (btnHelp) {
    btnHelp.addEventListener('click', function () { toggleHelp(); });
  }

  MM.toggleHelp = toggleHelp;
  MM.closeHelp = closeHelp;

  /************************************************************
   *               Settings Management                         *
   ************************************************************/

  var _settings = {};
  var settingsModal = null;

  function renderSettingsForm() {
    var body = document.getElementById('settingsModalBody');
    if (!body) return;

    body.innerHTML =
      '<form id="settingsForm">' +
        '<div class="mb-3">' +
          '<label for="settingPythonPath" class="form-label fw-semibold">Python Path</label>' +
          '<input type="text" class="form-control" id="settingPythonPath" ' +
            'placeholder="python" value="' + _escapeHtml(_settings.pythonPath || '') + '">' +
          '<div class="form-text">Path to Python interpreter (used by Electron to spawn the bridge)</div>' +
        '</div>' +

        '<hr>' +
        '<h6 class="fw-semibold mb-3">Service infrastructure</h6>' +
        '<div class="form-text mb-3 small">' +
          'Lookup priority for each binary: <strong>this setting</strong> &rarr; ' +
          '<code>PATH</code> &rarr; default install location ' +
          '(<code>%ProgramFiles%\\HashiCorp\\</code>). Leave empty to skip the ' +
          'override and let the bridge resolve via PATH.' +
        '</div>' +
        '<div class="mb-3">' +
          '<label for="settingConsulPath" class="form-label fw-semibold">Consul executable</label>' +
          '<div class="input-group">' +
            '<input type="text" class="form-control" id="settingConsulPath" ' +
              'placeholder="(auto-detect via PATH)" value="' +
              _escapeHtml(_settings.consulPath || '') + '">' +
            (window.electronAPI && window.electronAPI.showOpenDialog ?
              '<button class="btn btn-outline-secondary" type="button" id="btnBrowseConsulPath">' +
                '<i class="bi bi-folder2 me-1"></i>Browse&hellip;' +
              '</button>' : '') +
          '</div>' +
          '<div class="form-text">Used when starting the local Consul agent from the Service Network tab.</div>' +
        '</div>' +
        '<div class="mb-3">' +
          '<label for="settingNomadPath" class="form-label fw-semibold">Nomad executable</label>' +
          '<div class="input-group">' +
            '<input type="text" class="form-control" id="settingNomadPath" ' +
              'placeholder="(auto-detect via PATH)" value="' +
              _escapeHtml(_settings.nomadPath || '') + '">' +
            (window.electronAPI && window.electronAPI.showOpenDialog ?
              '<button class="btn btn-outline-secondary" type="button" id="btnBrowseNomadPath">' +
                '<i class="bi bi-folder2 me-1"></i>Browse&hellip;' +
              '</button>' : '') +
          '</div>' +
          '<div class="form-text">Used when starting the local Nomad agent from the Service Network tab.</div>' +
        '</div>' +

        '<hr>' +
        '<h6 class="fw-semibold mb-3">Bridge &amp; broker</h6>' +
        '<div class="row mb-3">' +
          '<div class="col">' +
            '<label for="settingBrokerHost" class="form-label fw-semibold">Broker Host</label>' +
            '<input type="text" class="form-control" id="settingBrokerHost" ' +
              'placeholder="localhost" value="' + _escapeHtml(_settings.brokerHost || '') + '">' +
          '</div>' +
          '<div class="col">' +
            '<label for="settingBrokerPort" class="form-label fw-semibold">Broker Port</label>' +
            '<input type="text" class="form-control" id="settingBrokerPort" ' +
              'placeholder="5672" value="' + _escapeHtml(_settings.brokerPort || '') + '">' +
          '</div>' +
        '</div>' +
        '<div class="mb-3">' +
          '<label for="settingBridgePort" class="form-label fw-semibold">Bridge Port</label>' +
          '<input type="number" class="form-control" id="settingBridgePort" ' +
            'placeholder="1112" value="' + _escapeHtml(_settings.bridgePort || '') + '">' +
          '<div class="form-text">Port for the FastAPI bridge (REST API &amp; WebSocket)</div>' +
        '</div>' +
      '</form>';

    _wireSettingsBrowseButtons();
  }

  // Wire the optional Browse buttons next to Consul/Nomad path inputs.
  // Only present in Electron — plain browsers can't open the OS file
  // picker (an <input type="file"> would work but the browser redacts
  // the absolute path on submit, which is exactly what we need).
  function _wireSettingsBrowseButtons() {
    if (!window.electronAPI || !window.electronAPI.showOpenDialog) return;

    function _pickExecutable(forTool, inputId) {
      var binName = forTool === 'consul' ? 'consul.exe' : 'nomad.exe';
      window.electronAPI.showOpenDialog({
        properties: ['openFile'],
        title: 'Locate the ' + forTool + ' executable',
        filters: [
          { name: forTool + ' executable', extensions: ['exe'] },
          { name: 'All files',             extensions: ['*'] }
        ],
        defaultPath: binName
      }).then(function (result) {
        if (!result || result.canceled) return;
        var picked = result.filePaths && result.filePaths[0];
        if (!picked) return;
        var input = document.getElementById(inputId);
        if (input) input.value = picked;
      }).catch(function (err) {
        console.error('[settings] Browse dialog failed:', err);
      });
    }

    var consulBtn = document.getElementById('btnBrowseConsulPath');
    if (consulBtn) {
      consulBtn.addEventListener('click', function () {
        _pickExecutable('consul', 'settingConsulPath');
      });
    }
    var nomadBtn = document.getElementById('btnBrowseNomadPath');
    if (nomadBtn) {
      nomadBtn.addEventListener('click', function () {
        _pickExecutable('nomad', 'settingNomadPath');
      });
    }
  }

  function openSettings() {
    renderSettingsForm();
    if (!settingsModal) {
      settingsModal = new bootstrap.Modal(document.getElementById('settingsModal'));
    }
    settingsModal.show();
  }

  function saveSettings() {
    var pythonPathInput = document.getElementById('settingPythonPath');
    var consulPathInput = document.getElementById('settingConsulPath');
    var nomadPathInput  = document.getElementById('settingNomadPath');
    var brokerHostInput = document.getElementById('settingBrokerHost');
    var brokerPortInput = document.getElementById('settingBrokerPort');
    var bridgePortInput = document.getElementById('settingBridgePort');
    var newSettings = {
      pythonPath: pythonPathInput ? pythonPathInput.value.trim() : '',
      consulPath: consulPathInput ? consulPathInput.value.trim() : '',
      nomadPath:  nomadPathInput  ? nomadPathInput.value.trim()  : '',
      brokerHost: brokerHostInput ? brokerHostInput.value.trim() : '',
      brokerPort: brokerPortInput ? brokerPortInput.value.trim() : '',
      bridgePort: bridgePortInput ? bridgePortInput.value.trim() : ''
    };

    _settings = Object.assign(_settings, newSettings);

    if (window.electronAPI && window.electronAPI.saveSettings) {
      window.electronAPI.saveSettings(_settings)
        .then(function () {
          showToast('Settings', 'Settings saved.', 'success');
        })
        .catch(function (err) {
          showToast('Error', 'Failed to save settings: ' + err.message, 'danger');
        });
    } else {
      try {
        sessionStorage.setItem('mm_settings', JSON.stringify(_settings));
        showToast('Settings', 'Settings saved.', 'success');
      } catch (e) {
        showToast('Error', 'Failed to save settings.', 'danger');
      }
    }

    if (settingsModal) settingsModal.hide();
  }

  function _fetchBaseVersion() {
    if (window.electronAPI && window.electronAPI.getPackageVersion) {
      var pyPath = (_settings && _settings.pythonPath) || 'python';
      window.electronAPI.getPackageVersion(pyPath, 'MicroserviceBase')
        .then(function (ver) { MM._baseVersion = ver; })
        .catch(function () {});
    } else if (MM.serviceClient && MM.serviceClient.apiUrl) {
      fetch(MM.serviceClient.apiUrl + '/api/version')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data && data.version) {
            MM._baseVersion = data.version;
          }
        })
        .catch(function () {});
    }
  }

  function loadSettings() {
    if (window.electronAPI && window.electronAPI.loadSettings) {
      window.electronAPI.loadSettings()
        .then(function (settings) {
          _settings = settings || {};
          console.log('[app] Settings loaded from file:', Object.keys(_settings));
          _fetchBaseVersion();
        })
        .catch(function () {
          _settings = {};
          _fetchBaseVersion();
        });
    } else {
      try {
        var raw = sessionStorage.getItem('mm_settings');
        if (raw) {
          _settings = JSON.parse(raw);
          console.log('[app] Settings loaded from sessionStorage:', Object.keys(_settings));
        }
      } catch (e) {
        _settings = {};
      }
      _fetchBaseVersion();
    }
  }

  // Wire settings button and save button
  var btnSettings = document.getElementById('btnSettings');
  if (btnSettings) {
    btnSettings.addEventListener('click', function () {
      openSettings();
    });
  }

  var btnSettingsSave = document.getElementById('btnSettingsSave');
  if (btnSettingsSave) {
    btnSettingsSave.addEventListener('click', function () {
      saveSettings();
    });
  }

  // Load settings on startup
  loadSettings();

  // Expose getSettings for other modules (e.g., LocalHubDashboard)
  MM.getSettings = function () { return _settings; };

  /************************************************************
   *               Report Issue                                 *
   ************************************************************/

  var reportIssueModal = null;
  var GITHUB_ISSUES_URL = 'https://github.com/test-fullautomation/python-microservice-base/issues/new';

  /**
   * Open a URL in the default browser (Electron) or a new tab (browser mode).
   */
  function _openUrl(url) {
    if (window.electronAPI && window.electronAPI.openExternal) {
      window.electronAPI.openExternal(url);
    } else {
      window.open(url, '_blank', 'noopener');
    }
  }

  /**
   * Collect environment info as a markdown string for the issue body.
   */
  function _collectEnvironmentInfo() {
    var lines = [];

    lines.push('## Environment');

    // GUI version — prefer eagerly-cached value, fall back to help page element
    var guiVersion = MM._guiVersion || 'unknown';
    if (guiVersion === 'unknown') {
      var guiVersionEl = document.querySelector('#docsGuiVersion');
      if (guiVersionEl && guiVersionEl.textContent && guiVersionEl.textContent !== 'loading...') {
        guiVersion = guiVersionEl.textContent;
      }
    }
    lines.push('- **GUI Version**: ' + guiVersion);

    // MicroserviceBase version
    var baseVersion = MM._baseVersion || 'unknown';
    lines.push('- **MicroserviceBase Version**: ' + baseVersion);

    // Platform
    lines.push('- **Platform**: ' + navigator.platform);
    lines.push('- **User Agent**: ' + navigator.userAgent);

    // Connected brokers
    var brokerKeys = Object.keys(MM.connections || {});
    if (brokerKeys.length > 0) {
      lines.push('- **Connected Brokers**: ' + brokerKeys.join(', '));
    } else {
      lines.push('- **Connected Brokers**: none');
    }

    // Services count
    var serviceCount = MM.servicesInfor ? Object.keys(MM.servicesInfor).length : 0;
    lines.push('- **Services**: ' + serviceCount + ' loaded');

    return lines.join('\n');
  }

  function openReportIssue() {
    // Clear previous input
    var titleInput = document.getElementById('issueTitle');
    var bodyInput = document.getElementById('issueBody');
    if (titleInput) titleInput.value = '';
    if (bodyInput) bodyInput.value = '';

    if (!reportIssueModal) {
      reportIssueModal = new bootstrap.Modal(document.getElementById('reportIssueModal'));
    }
    reportIssueModal.show();
  }

  function submitReportIssue() {
    var titleInput = document.getElementById('issueTitle');
    var bodyInput = document.getElementById('issueBody');

    var title = titleInput ? titleInput.value.trim() : '';
    if (!title) {
      showToast('Validation', 'Please provide a summary for the issue.', 'warning');
      titleInput.focus();
      return;
    }

    var userBody = bodyInput ? bodyInput.value.trim() : '';
    var envInfo = _collectEnvironmentInfo();

    var bodyParts = ['## Description'];
    if (userBody) {
      bodyParts.push(userBody);
    } else {
      bodyParts.push('_No additional details provided._');
    }
    bodyParts.push('');
    bodyParts.push(envInfo);

    var body = bodyParts.join('\n');

    var url = GITHUB_ISSUES_URL + '?title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(body);

    // URL length safety: browsers/GitHub typically support ~8000 chars
    var MAX_URL_LENGTH = 7500;
    if (url.length > MAX_URL_LENGTH) {
      var truncatedNote = '\n\n_(Details truncated due to URL length limits. Please add remaining details manually.)_';
      var availableBodyLength = MAX_URL_LENGTH
        - (GITHUB_ISSUES_URL + '?title=' + encodeURIComponent(title) + '&body=').length;
      // Decode, truncate, re-encode
      var truncatedBody = body.substring(0, Math.max(100, availableBodyLength / 3)) + truncatedNote;
      url = GITHUB_ISSUES_URL + '?title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(truncatedBody);
    }

    _openUrl(url);

    if (reportIssueModal) reportIssueModal.hide();
    showToast('Report Issue', 'Issue page opened in your browser.', 'success');
  }

  // Wire Report Issue button
  var btnReportIssue = document.getElementById('btnReportIssue');
  if (btnReportIssue) {
    btnReportIssue.addEventListener('click', function () {
      openReportIssue();
    });
  }

  // Wire submit button
  var btnSubmitIssue = document.getElementById('btnSubmitIssue');
  if (btnSubmitIssue) {
    btnSubmitIssue.addEventListener('click', function () {
      submitReportIssue();
    });
  }

  // Eagerly fetch versions so env info is available even if help was never opened
  fetch('version.json')
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data && data.version) {
        MM._guiVersion = data.version;
      }
    })
    .catch(function () {});

  // App initialization complete — hide loading overlay
  var _loadingOverlay = document.getElementById('loadingOverlay');
  if (_loadingOverlay) _loadingOverlay.classList.remove('active');

})();
