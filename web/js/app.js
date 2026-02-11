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
      _servicePanels[_activePanelName].style.display = 'none';
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
   *               Session Persistence                         *
   ************************************************************/

  function persistConnections() {
    try {
      var data = Object.keys(MM.connections).map(function (key) {
        var conn = MM.connections[key];
        return { brokerUrl: conn.brokerUrl, routingKey: conn.routingKey };
      });
      sessionStorage.setItem('mm_connections', JSON.stringify(data));
    } catch (e) { /* sessionStorage unavailable */ }
  }

  function loadPersistedConnections() {
    try {
      var raw = sessionStorage.getItem('mm_connections');
      if (raw) {
        return JSON.parse(raw);
      }
      // Legacy fallback
      var savedBrokerUrl = sessionStorage.getItem('mm_brokerUrl');
      var savedRoutingKey = sessionStorage.getItem('mm_routingKey');
      if (savedBrokerUrl) {
        return [{ brokerUrl: savedBrokerUrl, routingKey: savedRoutingKey || '' }];
      }
    } catch (e) { /* sessionStorage unavailable */ }
    return [];
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
        '<div class="toast-body"><strong>' + title + '</strong><br>' + message + '</div>' +
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
    if (confirm('Disconnect from broker ' + brokerUrl + '?')) {
      disconnectBroker(brokerUrl);
    }
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
    if (serviceInfo.gui_support === true) {
      var callBackFunc = function () {
        loadServiceContent(serviceName, DIV_NAME.SERVICE_CONTENT_DIV);
      };
      checkAndGetTheServiceGUIResources(serviceName, callBackFunc);
    } else {
      showServiceAPIExplorer(serviceName);
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
      _servicePanels[serviceName].style.display = '';
      _activePanelName = serviceName;
      // Restore unloadFunction reference
      var unloadName = 'unload' + serviceName;
      unloadFunction = window[unloadName] || null;
      if (callbackName !== '' && typeof window[callbackName] === 'function') {
        window[callbackName]();
      }
      return;
    }

    // --- Cache miss: fetch HTML, create cached wrapper, load script ---
    var folderPath = SERVICES_GUI_FOLDER + '/' + serviceName + MM.servicesInfor[serviceName].version;
    var externalContentFile = folderPath + '/' + serviceName + '.html';

    fetch(externalContentFile)
      .then(function (response) { return response.text(); })
      .then(function (htmlContent) {
        _deactivateCurrentPanel();

        // Create a wrapper div for the cached panel
        var wrapper = document.createElement('div');
        wrapper.setAttribute('data-cached-service', serviceName);
        wrapper.innerHTML = htmlContent;
        contentDiv.appendChild(wrapper);
        _servicePanels[serviceName] = wrapper;
        _activePanelName = serviceName;

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
        console.error('Error loading service content:', error);
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

    var labelSpan = document.createElement('span');
    labelSpan.classList.add('broker-label');
    labelSpan.textContent = brokerUrl;

    var badge = document.createElement('span');
    badge.classList.add('broker-badge');
    badge.textContent = '0';

    var disconnectBtn = document.createElement('button');
    disconnectBtn.classList.add('broker-disconnect-btn');
    disconnectBtn.title = 'Disconnect this broker';
    disconnectBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    disconnectBtn.onclick = function (e) {
      e.stopPropagation();
      confirmDisconnectBroker(brokerUrl);
    };

    header.appendChild(labelSpan);
    header.appendChild(badge);
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
        var listItem = document.createElement('button');
        listItem.type = 'button';
        listItem.classList.add('list-group-item', 'list-group-item-action');
        listItem.setAttribute('aria-current', 'true');
        listItem.setAttribute('data-service-name', item.serviceName);
        if (brokerUrl) {
          listItem.setAttribute('data-broker-url', brokerUrl);
        }

        // Direct function binding instead of eval()
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

        var helperBtn = document.createElement('span');
        helperBtn.classList.add('helper-btn');
        helperBtn.innerHTML = '<i class="bi bi-code-slash"></i>';
        helperBtn.title = 'Code Example';
        helperBtn.onclick = function (e) {
          e.stopPropagation();
          showServiceHelper(item.serviceName);
        };

        listItem.appendChild(icon);
        listItem.appendChild(label);
        listItem.appendChild(helperBtn);
        listGroup.appendChild(listItem);
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
   ************************************************************/

  var helperModal = null;

  /**
   * Generate Python example code for a service using MicroserviceBase transport.
   */
  function _generatePythonCode(serviceName, serviceInfo, brokerHost, brokerPort) {
    var methods = serviceInfo.methods || [];
    var methodsInfo = serviceInfo.methods_info || {};
    var routingKey = serviceInfo.routing_key || serviceName;

    var code = '';
    code += 'from MicroserviceBase import ServiceBase\n';
    code += 'from MicroserviceBase.factory import create_transport\n';
    code += '\n';
    code += '# Create transport (connects to RabbitMQ broker)\n';
    code += 'transport = create_transport(\n';
    code += '    \'rabbitmq\',\n';
    code += '    cmd_args=[\'--host\', \'' + brokerHost + '\', \'--port\', \'' + brokerPort + '\'],\n';
    code += '    service_name=\'MyClient\'\n';
    code += ')\n';
    code += '\n';
    code += 'EXCHANGE = \'' + SERVICES_EXCHANGE_NAME + '\'\n';
    code += 'ROUTING_KEY = \'' + routingKey + '\'\n';
    code += '\n';
    code += 'try:\n';

    if (methods.length > 0) {
      methods.forEach(function (methodName, idx) {
        var methodDetail = methodsInfo[methodName];
        var argsValue = 'None';
        var argsComment = '';

        if (methodDetail && methodDetail.arguments && methodDetail.arguments.length > 0) {
          var argNames = methodDetail.arguments.map(function (a) {
            return a.name || 'arg';
          });
          argsComment = '  # args: ' + argNames.join(', ');
          var argPlaceholders = methodDetail.arguments.map(function (a) {
            var desc = a.description || a.name || 'value';
            if (a.type === 'int' || a.type === 'number') return '0';
            if (a.type === 'bool' || a.type === 'boolean') return 'True';
            return '\'' + desc.replace(/'/g, "\\'") + '\'';
          });
          argsValue = '[' + argPlaceholders.join(', ') + ']';
        }

        if (idx > 0) code += '\n';
        code += '    # ' + methodName + '\n';
        code += '    request = ServiceBase.create_request_data(\'' + methodName + '\', ' + argsValue + ')' + argsComment + '\n';
        code += '    response = transport.rpc_call(request, EXCHANGE, ROUTING_KEY)\n';
        code += '    print(f"[' + methodName + '] {response[\'result\']}: {response[\'result_data\']}")\n';
      });
    } else {
      code += '    # No methods available for this service.\n';
      code += '    pass\n';
    }

    code += '\nfinally:\n';
    code += '    transport.disconnect()\n';
    return code;
  }

  /**
   * Generate Robot Framework example code for a service using QConnectBase.
   */
  function _generateRobotCode(serviceName, serviceInfo, brokerHost, brokerPort) {
    var methods = serviceInfo.methods || [];
    var methodsInfo = serviceInfo.methods_info || {};
    var routingKey = serviceInfo.routing_key || serviceName;

    var code = '';
    code += '*** Settings ***\n';
    code += 'Library    QConnectBase.ConnectionManager\n';
    code += 'Library    Collections\n';
    code += '\n';
    code += '*** Variables ***\n';
    code += '${BROKER_HOST}        ' + brokerHost + '\n';
    code += '${BROKER_PORT}        ' + brokerPort + '\n';
    code += '${ROUTING_KEY}        ' + routingKey + '\n';
    code += '${CONNECTION_NAME}    ' + serviceName + '_conn\n';
    code += '\n';
    code += '*** Test Cases ***\n';

    if (methods.length > 0) {
      methods.forEach(function (methodName) {
        var methodDetail = methodsInfo[methodName];
        var argsValue = 'null';

        if (methodDetail && methodDetail.arguments && methodDetail.arguments.length > 0) {
          var argPlaceholders = methodDetail.arguments.map(function (a) {
            if (a.type === 'int' || a.type === 'number') return '0';
            if (a.type === 'bool' || a.type === 'boolean') return 'true';
            var desc = a.description || a.name || 'value';
            return '"' + desc.replace(/"/g, '\\"') + '"';
          });
          argsValue = '[' + argPlaceholders.join(', ') + ']';
        }

        code += 'Test ' + methodName + '\n';
        code += '    [Documentation]    Call ' + methodName;
        if (methodDetail && methodDetail.description) {
          code += ' - ' + methodDetail.description;
        }
        code += '\n';
        code += '    ${config}=    Evaluate    json.loads(\'{"address":"${BROKER_HOST}","port":"${BROKER_PORT}","routing_key":"${ROUTING_KEY}"}\')    json\n';
        code += '    Connect    conn_name=${CONNECTION_NAME}\n    ...        conn_type=RabbitmqClient\n    ...        conn_conf=${config}\n';
        code += '    ${res}=    Verify    conn_name=${CONNECTION_NAME}\n';
        code += '    ...    send_cmd={ "method": "' + methodName + '", "args": ' + argsValue + ' }\n';
        code += '    ...    search_pattern=(.*)\n';
        code += '    ...    timeout=30\n';
        code += '    Log To Console    ${res}\n';
        code += '    [Teardown]    Disconnect    ${CONNECTION_NAME}\n';
        code += '\n';
      });
    } else {
      code += 'Test No Methods\n';
      code += '    [Documentation]    No methods available for this service.\n';
      code += '    Log    No methods to call.\n';
    }

    return code;
  }

  /**
   * Generate JavaScript example code for a service using the ServiceClient / fetch API.
   */
  function _generateJavaScriptCode(serviceName, serviceInfo, brokerHost, brokerPort) {
    var methods = serviceInfo.methods || [];
    var methodsInfo = serviceInfo.methods_info || {};
    var routingKey = serviceInfo.routing_key || serviceName;
    var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : 'http://localhost:8000';

    var code = '';
    code += '// Using the FastAPI bridge REST endpoint\n';
    code += 'const API_URL   = \'' + apiUrl + '/api/request\';\n';
    code += 'const EXCHANGE  = \'' + SERVICES_EXCHANGE_NAME + '\';\n';
    code += 'const ROUTING_KEY = \'' + routingKey + '\';\n';
    code += '\n';
    code += '/**\n';
    code += ' * Send an RPC request to a service method.\n';
    code += ' * @param {string} method - Service method name.\n';
    code += ' * @param {Array|null} args - Method arguments.\n';
    code += ' * @returns {Promise<object>} Service response.\n';
    code += ' */\n';
    code += 'async function callService(method, args = null) {\n';
    code += '  const res = await fetch(API_URL, {\n';
    code += '    method: \'POST\',\n';
    code += '    headers: { \'Content-Type\': \'application/json\' },\n';
    code += '    body: JSON.stringify({\n';
    code += '      method,\n';
    code += '      args,\n';
    code += '      exchange: EXCHANGE,\n';
    code += '      routing_key: ROUTING_KEY,\n';
    code += '    }),\n';
    code += '  });\n';
    code += '  if (!res.ok) throw new Error(`Request failed: ${res.status}`);\n';
    code += '  return res.json();\n';
    code += '}\n';
    code += '\n';
    code += '// --- Example calls ---\n';

    if (methods.length > 0) {
      code += '(async () => {\n';
      methods.forEach(function (methodName) {
        var methodDetail = methodsInfo[methodName];
        var argsValue = 'null';
        var argsComment = '';

        if (methodDetail && methodDetail.arguments && methodDetail.arguments.length > 0) {
          var argNames = methodDetail.arguments.map(function (a) {
            return a.name || 'arg';
          });
          argsComment = '  // args: ' + argNames.join(', ');
          var argPlaceholders = methodDetail.arguments.map(function (a) {
            var desc = a.description || a.name || 'value';
            if (a.type === 'int' || a.type === 'number') return '0';
            if (a.type === 'bool' || a.type === 'boolean') return 'true';
            return '\'' + desc.replace(/'/g, "\\'") + '\'';
          });
          argsValue = '[' + argPlaceholders.join(', ') + ']';
        }

        code += '\n';
        code += '  // ' + methodName + '\n';
        code += '  const r_' + methodName.replace(/\W/g, '_') + ' = await callService(\'' + methodName + '\', ' + argsValue + ');' + argsComment + '\n';
        code += '  console.log(\'' + methodName + ':\', r_' + methodName.replace(/\W/g, '_') + ');\n';
      });
      code += '})();\n';
    } else {
      code += '// No methods available for this service.\n';
    }

    return code;
  }

  /**
   * Show a modal with example code for calling a service's APIs.
   * Supports multiple languages via tabs (Python, JavaScript).
   *
   * @param {string} serviceName - The service name key in MM.servicesInfor.
   */
  function showServiceHelper(serviceName) {
    var serviceInfo = MM.servicesInfor[serviceName];
    if (!serviceInfo) {
      showToast('Error', 'No information available for ' + serviceName, 'danger');
      return;
    }

    var version = serviceInfo.version || '';
    var description = serviceInfo.description || serviceInfo.shortdesc || '';

    // Resolve broker host/port from the service's owning broker
    var resolvedBroker = resolveBrokerUrlForService(serviceName) || MM.brokerUrl || 'localhost:5672';
    var brokerHost = 'localhost';
    var brokerPort = '5672';
    if (resolvedBroker) {
      var parts = resolvedBroker.split(':');
      brokerHost = parts[0] || 'localhost';
      brokerPort = parts[1] || '5672';
    }

    // Generate code for each language
    var pythonCode = _generatePythonCode(serviceName, serviceInfo, brokerHost, brokerPort);
    var jsCode = _generateJavaScriptCode(serviceName, serviceInfo, brokerHost, brokerPort);
    var robotCode = _generateRobotCode(serviceName, serviceInfo, brokerHost, brokerPort);

    // Build modal body with header + language tabs
    var titleHtml = '<h5>' + _escapeHtml(serviceInfo.name || serviceName) + ' ' +
      '<span class="badge bg-secondary">' + _escapeHtml(version) + '</span></h5>';
    if (description) {
      titleHtml += '<p class="text-muted mb-3">' + _escapeHtml(description) + '</p>';
    }

    var tabsHtml =
      '<ul class="nav nav-tabs helper-lang-tabs" role="tablist">' +
        '<li class="nav-item" role="presentation">' +
          '<button class="nav-link active" data-bs-toggle="tab" data-bs-target="#helperTabPython" ' +
            'type="button" role="tab" aria-selected="true">' +
            '<i class="bi bi-filetype-py me-1"></i>Python</button>' +
        '</li>' +
        '<li class="nav-item" role="presentation">' +
          '<button class="nav-link" data-bs-toggle="tab" data-bs-target="#helperTabJS" ' +
            'type="button" role="tab" aria-selected="false">' +
            '<i class="bi bi-filetype-js me-1"></i>JavaScript</button>' +
        '</li>' +
        '<li class="nav-item" role="presentation">' +
          '<button class="nav-link" data-bs-toggle="tab" data-bs-target="#helperTabRobot" ' +
            'type="button" role="tab" aria-selected="false">' +
            '<i class="bi bi-robot me-1"></i>Robot</button>' +
        '</li>' +
      '</ul>' +
      '<div class="tab-content">' +
        '<div class="tab-pane fade show active" id="helperTabPython" role="tabpanel">' +
          '<pre class="helper-code-pre" id="helperCodePython">' + _escapeHtml(pythonCode) + '</pre>' +
        '</div>' +
        '<div class="tab-pane fade" id="helperTabJS" role="tabpanel">' +
          '<pre class="helper-code-pre" id="helperCodeJS">' + _escapeHtml(jsCode) + '</pre>' +
        '</div>' +
        '<div class="tab-pane fade" id="helperTabRobot" role="tabpanel">' +
          '<pre class="helper-code-pre" id="helperCodeRobot">' + _escapeHtml(robotCode) + '</pre>' +
        '</div>' +
      '</div>';

    document.getElementById('helperModalTitle').textContent = 'Helper \u2014 ' + (serviceInfo.name || serviceName);
    document.getElementById('helperModalBody').innerHTML = titleHtml + tabsHtml;

    if (!helperModal) {
      helperModal = new bootstrap.Modal(document.getElementById('helperModal'));
    }
    helperModal.show();
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
    connect();
  });

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

  // Auto-reconnect from sessionStorage on page refresh
  try {
    var savedConnections = loadPersistedConnections();
    if (savedConnections.length > 0) {
      console.log('[app] Auto-reconnecting', savedConnections.length, 'broker(s) from saved session...');
      savedConnections.forEach(function (saved) {
        if (MM.connections[saved.brokerUrl]) return; // skip duplicates
        addConnection(saved.brokerUrl, saved.routingKey);
        addAliasServiceForBroker(saved.brokerUrl, saved.routingKey);
        requestServicesInforForBroker(saved.brokerUrl);
      });
      updateBrokerHeaders();
    }
  } catch (e) { /* sessionStorage unavailable */ }

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
            serviceName: 'ServiceAlias'
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
    try {
      sessionStorage.removeItem('mm_connections');
      sessionStorage.removeItem('mm_brokerUrl');
      sessionStorage.removeItem('mm_routingKey');
    } catch (e) { /* sessionStorage unavailable */ }
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
      var existingItem = acc.find(function (item) { return item.title === service.group; });
      var newItem = {
        label: service.name,
        iconSrc: IMAGE_PATH.READY,
        serviceName: service.name
      };

      if (!existingItem) {
        if (service.group !== '') {
          acc.push({
            title: service.group,
            contentId: 'content-' + service.group.replace(/ /g, '-').toLowerCase(),
            items: [newItem]
          });
        }
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
    var cachedChecksumKey = 'gui_checksum_' + serviceName;
    var routingKey = MM.servicesInfor[serviceName].routing_key;

    // Local-only services (no routing key) — skip checksum, just check folder
    if (!routingKey) {
      _checkGUIFolderExists(serviceName, folderPath, callbackFunc);
      return;
    }

    // Request checksum from service to detect file changes
    var checksumRequest = { method: 'svc_api_get_gui_checksum', args: null };
    requestService(checksumRequest, SERVICES_EXCHANGE_NAME, routingKey)
      .then(function (data) {
        var remoteChecksum = data.result_data;
        var cachedChecksum = sessionStorage.getItem(cachedChecksumKey);

        var onDownloadSuccess = function () {
          if (remoteChecksum) {
            sessionStorage.setItem(cachedChecksumKey, remoteChecksum);
          }
          if (callbackFunc) callbackFunc();
        };

        // Checksum matches — files are up-to-date
        if (cachedChecksum && cachedChecksum === remoteChecksum) {
          console.log('GUI checksum matches for', serviceName, '- using cached files');
          if (callbackFunc) callbackFunc();
          return;
        }

        // Checksum differs or first download — download fresh
        console.log('GUI checksum changed for', serviceName, '- downloading');
        if (typeof window !== 'undefined' && window.electronAPI) {
          requestServiceGUIResources(serviceName, folderPath, onDownloadSuccess);
        } else {
          requestServiceGUIResourcesBrowser(serviceName, folderPath, onDownloadSuccess);
        }
      })
      .catch(function (error) {
        // Checksum API not available — fall back to folder existence check
        console.warn('GUI checksum not available for', serviceName, ', falling back to folder check');
        _checkGUIFolderExists(serviceName, folderPath, callbackFunc);
      });
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
          console.error('Failed to download GUI resources for', serviceName);
        }
      })
      .catch(function (error) {
        console.error('Error downloading GUI resources:', error);
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
        'The Service Registry on ' + brokerUrl + ' has shut down.',
        'warning'
      );
      disconnectBroker(brokerUrl);
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
                serviceName + ' has disconnected</span>';
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
      if (!svcInfo.group || svcInfo.group === '') return;

      if (!brokerSection.querySelector('.list-group-item[data-service-name="' + serviceName + '"]')) {
        var newServiceData = {};
        newServiceData[serviceName] = svcInfo;
        var newItems = extractServicesInformation(newServiceData);
        createAccordionItems(newItems, brokerUrl);
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
  function requestServicesInforForBroker(brokerUrl) {
    var conn = MM.connections[brokerUrl];
    if (!conn) return;

    var requestData = {
      'method': 'svc_api_get_services_info',
      'args': null
    };

    // Set active broker context for the request
    setRegistryServiceInfo({ brokerUrl: brokerUrl, routingKey: conn.routingKey });

    requestService(requestData, SERVICES_EXCHANGE_NAME, conn.routingKey)
      .then(function (data) {
        console.log('Received service infor from', brokerUrl, ':', data);
        var servicesInfor = JSON.parse(data.result_data);
        conn.services = servicesInfor;
        rebuildMergedServicesInfor();
        var serviceItems = extractServicesInformation(servicesInfor);
        createAccordionItems(serviceItems, brokerUrl);
        updateConnectionBadge();
        showToast('Connected', 'Successfully connected to ' + brokerUrl, 'success');

        // Subscribe to realtime updates from this broker's Registry
        subscribeToRealtimeUpdatesForBroker(brokerUrl);
      })
      .catch(function (error) {
        console.error('Error loading data from', brokerUrl, ':', error);
        disconnectBroker(brokerUrl);
        showToast('Connection Failed', 'Could not connect to ' + brokerUrl + ': ' + (error.message || error), 'danger');
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

  function switchMode(mode) {
    if (mode === _currentMode) return;

    // Deactivate previous mode
    if (_currentMode === 'fleet') {
      deactivateFleetMode();
    } else if (_currentMode === 'creator') {
      deactivateCreatorMode();
    }

    _currentMode = mode;

    // Toggle sidebar panels
    var sidebarServices = document.getElementById('sidebarServices');
    var sidebarFleet = document.getElementById('sidebarFleet');
    var sidebarCreator = document.getElementById('sidebarCreator');
    if (sidebarServices) sidebarServices.classList.toggle('active', mode === 'services');
    if (sidebarFleet) sidebarFleet.classList.toggle('active', mode === 'fleet');
    if (sidebarCreator) sidebarCreator.classList.toggle('active', mode === 'creator');

    // Toggle content panels
    var serviceContent = document.getElementById('serviceContent');
    var fleetContent = document.getElementById('fleetContent');
    var creatorContent = document.getElementById('creatorContent');
    if (serviceContent) serviceContent.style.display = mode === 'services' ? '' : 'none';
    if (fleetContent) fleetContent.style.display = mode === 'fleet' ? '' : 'none';
    if (creatorContent) creatorContent.style.display = mode === 'creator' ? '' : 'none';

    // Toggle nav buttons
    var btnServices = document.getElementById('btnModeServices');
    var btnFleet = document.getElementById('btnModeFleet');
    var btnCreator = document.getElementById('btnModeCreator');
    if (btnServices) btnServices.classList.toggle('active', mode === 'services');
    if (btnFleet) btnFleet.classList.toggle('active', mode === 'fleet');
    if (btnCreator) btnCreator.classList.toggle('active', mode === 'creator');

    // Activate new mode
    if (mode === 'fleet') {
      activateFleetMode();
    } else if (mode === 'creator') {
      activateCreatorMode();
    }
  }

  function activateFleetMode() {
    if (!MM.fleetDashboard || !MM.fleetClient) return;

    // Activate the currently visible sub-tab
    var localTab = document.getElementById('tabLocalHub');
    var isLocalActive = localTab && localTab.classList.contains('active');

    if (isLocalActive) {
      _activateLocalHubSubTab();
    } else {
      _activateFleetRemoteSubTab();
    }

    // Wire sub-tab switch events
    var tabLocalHub = document.getElementById('tabLocalHub');
    var tabFleetRemote = document.getElementById('tabFleetRemote');

    if (tabLocalHub) {
      tabLocalHub._mmHandler = tabLocalHub._mmHandler || function () {
        _deactivateFleetRemoteSubTab();
        _activateLocalHubSubTab();
      };
      tabLocalHub.removeEventListener('shown.bs.tab', tabLocalHub._mmHandler);
      tabLocalHub.addEventListener('shown.bs.tab', tabLocalHub._mmHandler);
    }
    if (tabFleetRemote) {
      tabFleetRemote._mmHandler = tabFleetRemote._mmHandler || function () {
        _deactivateLocalHubSubTab();
        _activateFleetRemoteSubTab();
      };
      tabFleetRemote.removeEventListener('shown.bs.tab', tabFleetRemote._mmHandler);
      tabFleetRemote.addEventListener('shown.bs.tab', tabFleetRemote._mmHandler);
    }
  }

  function _activateFleetRemoteSubTab() {
    MM.fleetDashboard.activate();

    // Bridge URL is available in both browser mode (same origin) and
    // Electron mode (configured via settings / localStorage).
    var bridgeOrigin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    var hasBridge = bridgeOrigin && bridgeOrigin.indexOf('http') === 0;

    if (hasBridge) {
      // Check if bridge has a fleet URL configured before polling.
      fetch(bridgeOrigin + '/api/fleet/config')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data && data.fleet_api_url) {
            MM.fleetClient.startPolling();
          } else {
            // Bridge lost the URL (e.g. restart) — restore from localStorage
            var saved = null;
            try { saved = localStorage.getItem('mm_fleet_api_url'); } catch (e) {}
            if (saved) {
              MM.fleetClient.configure(saved).then(function () {
                MM.fleetClient.startPolling();
              });
            } else {
              MM.fleetDashboard.renderConfigurePrompt();
            }
          }
        })
        .catch(function () {
          MM.fleetDashboard.renderConfigurePrompt();
        });
    } else if (MM.fleetClient.isConfigured()) {
      MM.fleetClient.startPolling();
    } else {
      MM.fleetDashboard.renderConfigurePrompt();
    }
  }

  function _deactivateFleetRemoteSubTab() {
    if (MM.fleetClient) MM.fleetClient.stopPolling();
    if (MM.fleetDashboard) MM.fleetDashboard.deactivate();
  }

  function _activateLocalHubSubTab() {
    if (MM.localHubDashboard) MM.localHubDashboard.activate();
  }

  function _deactivateLocalHubSubTab() {
    if (MM.localHubDashboard) MM.localHubDashboard.deactivate();
  }

  function deactivateFleetMode() {
    if (MM.fleetClient) MM.fleetClient.stopPolling();
    if (MM.fleetDashboard) MM.fleetDashboard.deactivate();
    if (MM.localHubDashboard) MM.localHubDashboard.deactivate();
  }

  function activateCreatorMode() {
    if (MM.serviceCreator) MM.serviceCreator.activate();
  }

  function deactivateCreatorMode() {
    if (MM.serviceCreator) MM.serviceCreator.deactivate();
  }

  // Wire mode toggle buttons
  var btnModeServices = document.getElementById('btnModeServices');
  var btnModeFleet = document.getElementById('btnModeFleet');
  if (btnModeServices) {
    btnModeServices.addEventListener('click', function () { switchMode('services'); });
  }
  if (btnModeFleet) {
    btnModeFleet.addEventListener('click', function () { switchMode('fleet'); });
  }
  var btnModeCreator = document.getElementById('btnModeCreator');
  if (btnModeCreator) {
    btnModeCreator.addEventListener('click', function () { switchMode('creator'); });
  }

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
  MM.showWarningDialog = showWarningDialog;
  MM.activateItemAndLoadContent = activateItemAndLoadContent;
  MM.SERVICES_EXCHANGE_NAME = SERVICES_EXCHANGE_NAME;
  MM.CONNECTION_STATUS = CONNECTION_STATUS;
  MM.SERVICES_GUI_FOLDER = SERVICES_GUI_FOLDER;
  MM.showServiceAPIExplorer = showServiceAPIExplorer;
  MM.showServiceHelper = showServiceHelper;
  MM.switchMode = switchMode;

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
        '<h6 class="fw-semibold mb-3">Infrastructure</h6>' +
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
    var brokerHostInput = document.getElementById('settingBrokerHost');
    var brokerPortInput = document.getElementById('settingBrokerPort');
    var bridgePortInput = document.getElementById('settingBridgePort');
    var newSettings = {
      pythonPath: pythonPathInput ? pythonPathInput.value.trim() : '',
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

  function loadSettings() {
    if (window.electronAPI && window.electronAPI.loadSettings) {
      window.electronAPI.loadSettings()
        .then(function (settings) {
          _settings = settings || {};
          console.log('[app] Settings loaded from file:', Object.keys(_settings));
        })
        .catch(function () {
          _settings = {};
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

})();
