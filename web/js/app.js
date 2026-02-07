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

  MM.brokerUrl = 'localhost:5672';
  MM.routingKey = '';
  MM.servicesInfor = null;

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
  }

  /**
   * Change the Connect button state when connection status changes.
   *
   * @param {string} status - The connection status.
   */
  function changeConnectButtonState(status) {
    var btnConnect = document.getElementById('btnConnect');
    var dot = document.getElementById('connectionDot');
    var label = document.getElementById('connectionLabel');

    if (status === CONNECTION_STATUS.CONNECTED) {
      btnConnect.innerHTML = '<i class="bi bi-plug"></i> Disconnect';
      btnConnect.title = 'Disconnect';
      btnConnect.classList.add('disconnecting');
      dot.classList.add('connected');
      label.textContent = 'Connected';
      connectedStatus = true;
    } else if (status === CONNECTION_STATUS.DISCONNECTED) {
      btnConnect.innerHTML = '<i class="bi bi-plug"></i> Connect';
      btnConnect.title = 'Connect';
      btnConnect.classList.remove('disconnecting');
      dot.classList.remove('connected');
      label.textContent = 'Disconnected';
      connectedStatus = false;
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
    var folderPath = SERVICES_GUI_FOLDER + '/' + serviceName + MM.servicesInfor[serviceName].version;
    var externalContentFile = folderPath + '/' + serviceName + '.html';
    loadContent(externalContentFile, dynamicContentName, callbackName);
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
              if (callbackName !== '') {
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
            if (callbackName !== '') {
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

  /**
   * Dynamically generates accordion items for services in the sidebar.
   * Replaces eval() with direct function binding.
   *
   * @param {Array} data - Structured information for multiple services.
   */
  function createAccordionItems(data) {
    var accordionElement = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);

    data.forEach(function (section) {
      var accordionItem = document.createElement('div');
      accordionItem.classList.add('accordion-item');

      var accordionHeader = document.createElement('h2');
      accordionHeader.classList.add('accordion-header');

      var accordionButton = document.createElement('button');
      accordionButton.classList.add('accordion-button');
      accordionButton.type = 'button';
      accordionButton.dataset.bsToggle = 'collapse';
      accordionButton.dataset.bsTarget = '#' + section.contentId;
      accordionButton.setAttribute('aria-expanded', 'true');
      accordionButton.textContent = section.title;

      accordionHeader.appendChild(accordionButton);

      var accordionCollapse = document.createElement('div');
      accordionCollapse.id = section.contentId;
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

      accordionElement.appendChild(accordionItem);
    });
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

    if (typeof unloadFunction === 'function') {
      unloadFunction();
      unloadFunction = null;
    }

    var methods = serviceInfo.methods || [];
    var methodsInfo = serviceInfo.methods_info || {};

    // Build method options
    var methodOptions = '<option value="" disabled selected>-- Select a method --</option>';
    methods.forEach(function (m) {
      methodOptions += '<option value="' + _escapeHtml(m) + '">' + _escapeHtml(m) + '</option>';
    });

    contentDiv.innerHTML =
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

    // Parse host and port from the current broker URL
    var brokerHost = 'localhost';
    var brokerPort = '5672';
    if (MM.brokerUrl) {
      var parts = MM.brokerUrl.split(':');
      brokerHost = parts[0] || 'localhost';
      brokerPort = parts[1] || '5672';
    }

    // Generate code for each language
    var pythonCode = _generatePythonCode(serviceName, serviceInfo, brokerHost, brokerPort);
    var jsCode = _generateJavaScriptCode(serviceName, serviceInfo, brokerHost, brokerPort);

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
      '</ul>' +
      '<div class="tab-content">' +
        '<div class="tab-pane fade show active" id="helperTabPython" role="tabpanel">' +
          '<pre class="helper-code-pre" id="helperCodePython">' + _escapeHtml(pythonCode) + '</pre>' +
        '</div>' +
        '<div class="tab-pane fade" id="helperTabJS" role="tabpanel">' +
          '<pre class="helper-code-pre" id="helperCodeJS">' + _escapeHtml(jsCode) + '</pre>' +
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
    var btnConnect = document.getElementById('btnConnect');
    if (btnConnect.title === 'Connect') {
      connect();
    } else {
      disconnect();
    }
  });

  document.getElementById('btnLoginSubmit').addEventListener('click', function () {
    onLoginSubmit();
  });

  // Sidebar search filter
  document.getElementById('searchText').addEventListener('input', function () {
    var query = this.value.toLowerCase().trim();
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

      // Hide entire accordion group if no items match
      section.style.display = visibleCount > 0 ? '' : 'none';

      // Auto-expand groups that have matches when searching
      if (query !== '' && visibleCount > 0) {
        var collapse = section.querySelector('.accordion-collapse');
        if (collapse && !collapse.classList.contains('show')) {
          collapse.classList.add('show');
        }
      }
    });
  });

  // Auto-reconnect from sessionStorage on page refresh
  try {
    var savedBrokerUrl = sessionStorage.getItem('mm_brokerUrl');
    var savedRoutingKey = sessionStorage.getItem('mm_routingKey');
    if (savedBrokerUrl && connectedStatus === false) {
      console.log('[app] Auto-reconnecting from saved session...');
      document.getElementById('brokerUrlInput').value = savedBrokerUrl;
      document.getElementById('routingKeyInput').value = savedRoutingKey || '';
      addAliasService();
      setRegistryServiceInfo({ brokerUrl: savedBrokerUrl, routingKey: savedRoutingKey || '' });
      requestServicesInfor();
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

    var formData = {
      brokerUrl: brokerUrl,
      routingKey: routingKey
    };

    if (loginModal) {
      loginModal.hide();
    }

    if (connectedStatus === false) {
      showToast('Connecting', 'Connecting to broker at ' + brokerUrl + '...', 'info');
      addAliasService();
      setRegistryServiceInfo(formData);
      requestServicesInfor();
    }
  }

  function addAliasService() {
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

    createAccordionItems(aliasServiceData);
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

  /**
   * Disconnect from Registry Service and clean services information.
   */
  function disconnect() {
    MM.brokerUrl = null;
    MM.routingKey = null;
    MM.servicesInfor = null;
    unloadFunction = null;
    clearServiceList();
    clearServiceContent();
    changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
    MM.serviceClient.disconnect();
    try {
      sessionStorage.removeItem('mm_brokerUrl');
      sessionStorage.removeItem('mm_routingKey');
    } catch (e) { /* sessionStorage unavailable */ }
  }

  /**
   * Set Registry Service connection info.
   *
   * @param {object} registryData - The information of the Registry Service.
   */
  function setRegistryServiceInfo(registryData) {
    MM.brokerUrl = registryData.brokerUrl;
    MM.routingKey = registryData.routingKey;
    // Persist for auto-reconnect on page refresh
    try {
      sessionStorage.setItem('mm_brokerUrl', registryData.brokerUrl);
      sessionStorage.setItem('mm_routingKey', registryData.routingKey);
    } catch (e) { /* sessionStorage unavailable */ }
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
   * Check if service GUI resources exist; download if needed.
   */
  function checkAndGetTheServiceGUIResources(serviceName, callbackFunc) {
    callbackFunc = callbackFunc || null;
    var folderPath = SERVICES_GUI_FOLDER + '/' + serviceName + MM.servicesInfor[serviceName].version;

    if (typeof window !== 'undefined' && window.electronAPI) {
      // Electron mode: check filesystem
      window.electronAPI.folderExists(folderPath)
        .then(function (exists) {
          if (exists) {
            if (callbackFunc) callbackFunc();
            console.log('Folder exists');
          } else {
            requestServiceGUIResources(serviceName, folderPath, callbackFunc);
          }
        })
        .catch(function () {
          requestServiceGUIResources(serviceName, folderPath, callbackFunc);
        });
    } else {
      // Browser mode: try to fetch the HTML directly (served by FastAPI)
      // If it fails, request via API to download
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
   * Subscribe to realtime service status updates.
   * - Browser mode: connect WebSocket directly (bridge relays fanout updates).
   * - Electron mode: RPC call to get exchange name, then subscribe via AMQP.
   */
  function subscribeToRealtimeUpdates() {
    if (!window.electronAPI) {
      // Browser mode: WebSocket to FastAPI bridge (bridge already listens on fanout)
      console.log('[app] Browser mode: connecting WebSocket for realtime updates');
      MM.serviceClient.onServicesUpdate(function (message) {
        handleServicesUpdate(message);
      });
      MM.serviceClient.connectUpdates().catch(function (err) {
        console.error('[app] Failed to connect WebSocket updates:', err);
      });
      return;
    }

    // Electron mode: get fanout exchange name from Registry, subscribe via AMQP
    var requestData = {
      'method': 'svc_api_get_realtime_update_exchange',
      'args': null
    };

    requestService(requestData, SERVICES_EXCHANGE_NAME, MM.routingKey)
      .then(function (data) {
        var exchangeName = data.result_data;
        if (!exchangeName) {
          console.warn('[app] No realtime update exchange name received');
          return;
        }
        console.log('[app] Subscribing to realtime update exchange:', exchangeName);
        MM.serviceClient.subscribeToExchange(exchangeName, function (message) {
          handleServicesUpdate(message);
        });
      })
      .catch(function (error) {
        console.error('[app] Failed to get realtime update exchange:', error);
      });
  }

  /**
   * Handle a services update (from either polling or fanout exchange).
   * The message is the full services_information dict (all currently online services).
   * Compare with current sidebar to detect services going on/off.
   *
   * @param {object|string} message - The services information dict or JSON string.
   */
  function handleServicesUpdate(message) {
    console.log('[app] handleServicesUpdate called, services:', Object.keys(typeof message === 'object' ? message : {}));
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

    // Find all sidebar service items
    var allItems = document.querySelectorAll('.list-group-item[data-service-name]');

    allItems.forEach(function (listItem) {
      var serviceName = listItem.getAttribute('data-service-name');
      // Skip the Alias service - it's a local GUI feature, not a real service
      if (serviceName === 'ServiceAlias') return;

      var icon = listItem.querySelector('.icon');
      if (serviceName in updatedServices) {
        // Service is online
        if (listItem.classList.contains('service-disabled')) {
          listItem.classList.remove('service-disabled');
          if (icon) icon.src = IMAGE_PATH.READY;
          console.log('[app] Service came online:', serviceName);
          showToast('Service Online', serviceName + ' is now available.', 'success');
        }
        // Update service info with latest data
        MM.servicesInfor[serviceName] = updatedServices[serviceName];
      } else {
        // Service went offline
        if (!listItem.classList.contains('service-disabled')) {
          // If this service was currently active, clear the content panel
          if (listItem.classList.contains('active')) {
            listItem.classList.remove('active');
            var contentDiv = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);
            if (typeof unloadFunction === 'function') {
              unloadFunction();
              unloadFunction = null;
            }
            contentDiv.innerHTML =
              '<div class="content-placeholder">' +
                '<span><i class="bi bi-exclamation-triangle me-2"></i>' +
                  serviceName + ' has disconnected</span>' +
              '</div>';
          }
          listItem.classList.add('service-disabled');
          if (icon) icon.src = IMAGE_PATH.DISABLED;
          console.log('[app] Service went offline:', serviceName);
          showToast('Service Offline', serviceName + ' is no longer available.', 'warning');
        }
      }
    });

    // Check if any new services appeared that aren't in the sidebar yet
    Object.keys(updatedServices).forEach(function (serviceName) {
      var svcInfo = updatedServices[serviceName];
      // Skip services without a group (e.g. ServiceRegistry) — they are not shown in the sidebar
      if (!svcInfo.group || svcInfo.group === '') return;

      if (!document.querySelector('.list-group-item[data-service-name="' + serviceName + '"]')) {
        // New service appeared - add to servicesInfor and rebuild its group
        MM.servicesInfor[serviceName] = svcInfo;
        var newServiceData = {};
        newServiceData[serviceName] = svcInfo;
        var newItems = extractServicesInformation(newServiceData);
        createAccordionItems(newItems);
        console.log('[app] New service appeared:', serviceName);
        showToast('Service Online', serviceName + ' is now available.', 'success');
      }
    });
  }

  /************************************************************
   *                  Service Request Functions               *
   ************************************************************/

  /**
   * Get all services information from Registry Service.
   */
  function requestServicesInfor() {
    var requestData = {
      'method': 'svc_api_get_services_info',
      'args': null
    };

    requestService(requestData, SERVICES_EXCHANGE_NAME, MM.routingKey)
      .then(function (data) {
        console.log('Received service infor: ', data);
        var servicesInfor = JSON.parse(data.result_data);
        MM.servicesInfor = Object.assign({}, MM.servicesInfor, servicesInfor);
        var serviceItems = extractServicesInformation(servicesInfor);
        createAccordionItems(serviceItems);
        changeConnectButtonState(CONNECTION_STATUS.CONNECTED);
        showToast('Connected', 'Successfully connected to broker.', 'success');

        // Subscribe to realtime updates from Registry
        subscribeToRealtimeUpdates();
      })
      .catch(function (error) {
        console.error('Error loading data:', error);
        changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
        showToast('Connection Failed', 'Could not connect: ' + (error.message || error), 'danger');
      });
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
    MM.serviceClient.setBrokerUrl(MM.brokerUrl);
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
   *               Expose functions for plugins               *
   ************************************************************/

  MM.requestService = requestService;
  MM.requestServiceDirect = function (data, queue) {
    MM.serviceClient.setBrokerUrl(MM.brokerUrl);
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

})();
