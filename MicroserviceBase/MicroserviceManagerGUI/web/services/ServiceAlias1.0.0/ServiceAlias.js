/**
 * @fileoverview ServiceAlias GUI plugin - browser-compatible version.
 * Uses MM (window.MicroserviceManager) namespace instead of global/require.
 *
 * @version 2.0.0
 */

var MM = window.MicroserviceManager;

var ServiceAlias = {
  VERSION: "1.0.0",
  SERVICE_NAME: "ServiceAlias"
};

let rowIndex = 1;

const jsonData = {};

requestAliasInfor();

function populateTable(data) {
  const table = document.getElementById('data-table');
  const tbody = table.getElementsByTagName('tbody')[0];
  const headers = Array.from(table.querySelector('thead tr').children).map(th => th.textContent).slice(0,4);

  if (data === null || data == "" || data.length === 0 || JSON.stringify(data) === '{}')
  {
    addRow();
  }
  Object.keys(data).forEach((key, index) => {
    const row = tbody.insertRow();

    headers.forEach((header, colIndex) => {
      const cell = row.insertCell();
      if (colIndex === 0) {
        const input = document.createElement('input');
        input.classList.add("form-control");
        input.style.width = "180px";
        input.type = 'text';
        input.value = key;
        input.dataset.type = 'name';
        cell.appendChild(input);
      } else if (colIndex === 3)
      {
        const input = document.createElement('input');
        input.classList.add("form-control");
        input.style.width = "180px";
        input.type = 'text';
        input.value = data[key][header];
        input.dataset.type = 'args';
        cell.appendChild(input);
      } else {
        const select = document.createElement('select');
        select.classList.add("form-control");
        select.style.width = "180px";
        const option = document.createElement('option');
        option.value = data[key][header];
        option.textContent = data[key][header];
        select.appendChild(option);
        cell.appendChild(select);
      }
    });

    const minusCell = row.insertCell();
    const minusButton = document.createElement('button');
    minusButton.textContent = '-';
    minusButton.style.width = "38px";
    minusButton.onclick = function() {
      row.remove();
    };
    minusButton.classList.add('btn', 'btn-danger');
    minusCell.appendChild(minusButton);

    if (index === Object.keys(data).length - 1) {
      const plusCell = row.insertCell();
      const plusButton = document.createElement('button');
      plusButton.textContent = '+';
      plusButton.style.width = "38px";
      plusButton.onclick = addRow;
      plusButton.classList.add('btn', 'btn-primary');
      plusCell.appendChild(plusButton);
    } else {
      row.insertCell();
    }
  });
}

function unloadServiceAlias() {
}

function loadServiceAlias() {
  requestAliasInfor();
}

function saveAliasState(){
}

function populateServiceCombobox(combobox) {
  Object.keys(MM.servicesInfor).forEach(key => {
    const option = document.createElement('option');
    option.value = key;
    option.textContent = key;
    combobox.appendChild(option);
  });
}

function populateMethodCombobox(selectedValue, combobox) {
  const selectedObj = MM.servicesInfor[selectedValue].methods;
  combobox.innerHTML = '';

  if (selectedObj) {
    selectedObj.forEach(key => {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = key;
      combobox.appendChild(option);
    });
  }
}

function requestAliasInfor() {
  var requestData = {
    'method': 'svc_api_get_alias_conf',
    'args': null
  };

  MM.requestService(requestData, MM.SERVICES_EXCHANGE_NAME, MM.routingKey).then(function (data) {
    console.log("Received service infor: ", data);
    const aliasInfor = JSON.parse(data.result_data);
    console.log(aliasInfor);
    populateTable(aliasInfor);
  })
  .catch(function (error) {
    console.error('Error loading data:', error);
    MM.changeConnectButtonState(MM.CONNECTION_STATUS.DISCONNECTED);
  });
}

function requestUpdateAliasInfor(data) {
  var requestData = {
    'method': 'svc_api_update_alias_conf',
    'args': data
  };

  MM.requestService(requestData, MM.SERVICES_EXCHANGE_NAME, MM.routingKey).then(function (data) {
    console.log("Received service infor: ", data);
    const retValue = JSON.parse(data.result_data);
    console.log(retValue);
  })
  .catch(function (error) {
    console.error('Error loading data:', error);
    MM.changeConnectButtonState(MM.CONNECTION_STATUS.DISCONNECTED);
  });
}

function addRow() {
  const tableBody = document.querySelector('#data-table tbody');
  const newRow = document.createElement('tr');

  newRow.innerHTML = `
    <td class="col-3"><input type="text" class="form-control textbox" data-type="name" placeholder="Declare alias name here..."/></td>
    <td class="col-3"><select class="form-control combobox combobox1" style="width: 180px;"></select></td>
    <td class="col-3"><select class="form-control combobox combobox2" style="width: 180px;"></select></td>
    <td class="col-3"><input type="text" class="form-control textbox" data-type="args" /></td>
  `;

  const minusBtn = document.createElement('button');
  minusBtn.textContent = '-';
  minusBtn.style.width = "38px";
  minusBtn.onclick = function () {
    removeRow(newRow);
  };
  minusBtn.classList.add('btn', 'btn-danger');

  const minusCell = document.createElement('td');
  minusCell.appendChild(minusBtn);
  newRow.appendChild(minusCell);

  const prevLastRow = tableBody.querySelector(`tr:nth-last-child(1)`);
  if (prevLastRow) {
    const prevLastCell = prevLastRow.lastElementChild;
    prevLastCell.innerHTML = '';
  }

  tableBody.appendChild(newRow);

  const plusBtn = document.createElement('button');
  plusBtn.textContent = '+';
  plusBtn.style.width = "38px";
  plusBtn.onclick = addRow;
  plusBtn.classList.add('btn', 'btn-primary');

  const plusCell = document.createElement('td');
  plusCell.appendChild(plusBtn);
  newRow.appendChild(plusCell);

  rowIndex++;

  const serviceCombobox = newRow.querySelector('.combobox1');
  const methodCombobox = newRow.querySelector('.combobox2');

  populateServiceCombobox(serviceCombobox);

  serviceCombobox.addEventListener('change', function () {
    const selectedValue = serviceCombobox.value;
    populateMethodCombobox(selectedValue, methodCombobox);
  });

  populateMethodCombobox(serviceCombobox.value, methodCombobox);

  methodCombobox.addEventListener('change', function () {
    const selectedMethod = methodCombobox.value;
    const selectedService = serviceCombobox.value;
    addMethodArgumentRows(selectedService, selectedMethod, newRow);
  });
}

function addMethodArgumentRows(serviceName, methodName, row)
{
  const tableBody = document.querySelector('#data-table tbody');

  // Remove any previously added dynamic hint rows for this row
  var sib = row.nextSibling;
  while (sib && sib.getAttribute('data-dynamic-row') === 'true') {
    var toRemove = sib;
    sib = sib.nextSibling;
    tableBody.removeChild(toRemove);
  }

  const argumentsArray = MM.servicesInfor[serviceName].methods_info[methodName].arguments;
  var cell = row.children[3].children[0];
  cell.placeholder = argumentsArray[0].description;
  const argumentsArrayExt = argumentsArray.slice(1);
  var nextSib = row.nextSibling;
  row.style.border = 'none';

  argumentsArrayExt.forEach((placeholderObj, index, array) => {
      const newRow = document.createElement('tr');
      const isLast = index === array.length - 1;
      newRow.innerHTML = `
        <td colspan="3"></td>
        <td style="width: 180px; border-top: none;">
          <input class="form-control" type="text" data-type="args" style="width: 180px;" placeholder="${placeholderObj.description}">
        </td>
      `;
      newRow.setAttribute('data-dynamic-row', 'true');
      if (!isLast) {
        newRow.style.border = 'none';
      } else {
        newRow.style.borderTop = 'none';
      }

       tableBody.insertBefore(newRow, nextSib);
       nextSib = newRow.nextSibling;
  });

}

function removeRow(mainRow) {
  const table = document.getElementById('data-table');
  const tableBody = table.querySelector('tbody');

  let nextSibling = mainRow.nextSibling;

  while (nextSibling && nextSibling.getAttribute('data-dynamic-row') === 'true') {
    tableBody.removeChild(nextSibling);
    nextSibling = mainRow.nextSibling;
  }

  tableBody.removeChild(mainRow);
}

function getAliasConfiguration()
{
  document.getElementById('errorMessage').style.display = 'none';
  const table = document.getElementById('data-table');
  const rows = table.querySelectorAll('tbody tr');

  const jsonData = {};

  rows.forEach((row) => {
    if (row.getAttribute('data-dynamic-row') !== 'true') {
      const columns = row.querySelectorAll('td');
      const firstColumnValue = columns[0].querySelector('input').value;
      const rowData = {};

      for (let i = 1; i < columns.length - 2; i++) {
        const columnHeader = document.querySelector(`#data-table thead th:nth-child(${i + 1})`).innerText;
        const cellValue = columns[i].querySelector('input, select').value;
        rowData[columnHeader] = cellValue;
      }

      let nextSibling = row.nextSibling;

      while (nextSibling && nextSibling.getAttribute('data-dynamic-row') === 'true') {
        const siblingColumns = nextSibling.querySelectorAll('td');
        const siblingColumnHeader = document.querySelector(`#data-table thead th:nth-child(${4})`).innerText;
        const siblingCellValue = siblingColumns[1].querySelector('input, select').value;
        rowData[siblingColumnHeader] += "," + siblingCellValue;
        nextSibling = nextSibling.nextSibling;
      }

      jsonData[firstColumnValue] = rowData;
    }
  });

  console.log(jsonData);
  return jsonData;
}

function validateConfigurations()
{
  var isValid = false;
  var isAnyTextBoxEmpty = false;
  var table = document.getElementById('data-table');
  var rows = table.getElementsByTagName('tr');
  for (var i = 0; i < rows.length; i++) {
    var textboxes = rows[i].querySelectorAll('input[type="text"]');
    for (var j = 0; j < textboxes.length; j++) {
      if (textboxes[j].value.trim() === '') {
        if (textboxes[j].dataset.type === "args") {
          textboxes[j].value = null;
        } else {
          isAnyTextBoxEmpty = true;
          textboxes[j].classList.add('is-invalid');
        }
      } else {
        textboxes[j].classList.remove('is-invalid');
      }
    }
  }

  if (isAnyTextBoxEmpty) {
    document.getElementById('errorMessage').style.display = 'block';
  } else {
    document.getElementById('errorMessage').style.display = 'none';
    isValid = true;
  }

  return isValid;
}

function applyAliasConfig() {
  if (validateConfigurations()) {
    const jsonData = getAliasConfiguration();
    const jsonString = JSON.stringify(jsonData);
    requestUpdateAliasInfor(jsonString);
    MM.showToast('Alias Information', 'Updated!', 'success');
  }
}

// ---------------------------------------------------------------------------
// Code Helper — generate example code for calling aliases
// ---------------------------------------------------------------------------

function _escapeHtmlAlias(str) {
  var div = document.createElement('div');
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}

/**
 * Count ${input} placeholders in an alias arguments string.
 */
function _countInputPlaceholders(argsString) {
  if (!argsString) return 0;
  var matches = argsString.match(/\$\{input\}/g);
  return matches ? matches.length : 0;
}

/**
 * Generate Python example code for calling aliases via the Service Registry.
 */
function _generateAliasPythonCode(aliases, brokerHost, brokerPort, registryKey) {
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
  code += 'EXCHANGE = \'' + MM.SERVICES_EXCHANGE_NAME + '\'\n';
  code += 'ROUTING_KEY = \'' + registryKey + '\'  # Service Registry resolves aliases\n';
  code += '\n';
  code += 'try:\n';

  var aliasNames = Object.keys(aliases);
  if (aliasNames.length > 0) {
    aliasNames.forEach(function (aliasName, idx) {
      var alias = aliases[aliasName];
      var serviceName = alias['Service name'] || '';
      var methodName = alias['Method name'] || '';
      var argsTemplate = alias['Arguments'] || '';
      var inputCount = _countInputPlaceholders(argsTemplate);

      var argsValue = 'None';
      if (inputCount > 0) {
        var placeholders = [];
        for (var i = 1; i <= inputCount; i++) {
          placeholders.push('\'arg' + i + '\'');
        }
        argsValue = '[' + placeholders.join(', ') + ']';
      }

      if (idx > 0) code += '\n';
      code += '    # ' + aliasName + ' \u2192 ' + serviceName + '.' + methodName + '(' + argsTemplate + ')\n';
      code += '    request = ServiceBase.create_request_data(\'' + aliasName + '\', ' + argsValue + ')\n';
      code += '    response = transport.rpc_call(request, EXCHANGE, ROUTING_KEY)\n';
      code += '    print(f"[' + aliasName + '] {response[\'result\']}: {response[\'result_data\']}")\n';
    });
  } else {
    code += '    # No aliases configured.\n';
    code += '    pass\n';
  }

  code += '\nfinally:\n';
  code += '    transport.disconnect()\n';
  return code;
}

/**
 * Generate Robot Framework example code for calling aliases via the Service Registry.
 */
function _generateAliasRobotCode(aliases, brokerHost, brokerPort, registryKey) {
  var code = '';
  code += '*** Settings ***\n';
  code += 'Library    QConnectBase.ConnectionManager\n';
  code += 'Library    Collections\n';
  code += '\n';
  code += '*** Variables ***\n';
  code += '${BROKER_HOST}        ' + brokerHost + '\n';
  code += '${BROKER_PORT}        ' + brokerPort + '\n';
  code += '${ROUTING_KEY}        ' + registryKey + '\n';
  code += '${CONNECTION_NAME}    Alias_conn\n';
  code += '\n';
  code += '*** Test Cases ***\n';

  var aliasNames = Object.keys(aliases);
  if (aliasNames.length > 0) {
    aliasNames.forEach(function (aliasName) {
      var alias = aliases[aliasName];
      var serviceName = alias['Service name'] || '';
      var methodName = alias['Method name'] || '';
      var argsTemplate = alias['Arguments'] || '';
      var inputCount = _countInputPlaceholders(argsTemplate);

      var argsValue = 'null';
      if (inputCount > 0) {
        var placeholders = [];
        for (var i = 1; i <= inputCount; i++) {
          placeholders.push('"arg' + i + '"');
        }
        argsValue = '[' + placeholders.join(', ') + ']';
      }

      code += 'Test Alias ' + aliasName + '\n';
      code += '    [Documentation]    Alias: ' + aliasName + ' -> ' + serviceName + '.' + methodName + '(' + argsTemplate + ')\n';
      code += '    ${config}=    Evaluate    json.loads(\'{"address":"${BROKER_HOST}","port":"${BROKER_PORT}","routing_key":"${ROUTING_KEY}"}\')    json\n';
      code += '    Connect    conn_name=${CONNECTION_NAME}\n    ...        conn_type=RabbitmqClient\n    ...        conn_conf=${config}\n';
      code += '    ${res}=    Verify    conn_name=${CONNECTION_NAME}\n';
      code += '    ...    send_cmd={ "method": "' + aliasName + '", "args": ' + argsValue + ' }\n';
      code += '    ...    search_pattern=(.*)\n';
      code += '    ...    timeout=30\n';
      code += '    Log To Console    ${res}\n';
      code += '    [Teardown]    Disconnect    ${CONNECTION_NAME}\n';
      code += '\n';
    });
  } else {
    code += 'Test No Aliases\n';
    code += '    [Documentation]    No aliases configured.\n';
    code += '    Log    No aliases to call.\n';
  }

  return code;
}

/**
 * Generate JavaScript example code for calling aliases via the FastAPI bridge.
 */
function _generateAliasJavaScriptCode(aliases, brokerHost, brokerPort, registryKey) {
  var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : 'http://localhost:8000';

  var code = '';
  code += '// Using the FastAPI bridge REST endpoint\n';
  code += 'const API_URL   = \'' + apiUrl + '/api/request\';\n';
  code += 'const EXCHANGE  = \'' + MM.SERVICES_EXCHANGE_NAME + '\';\n';
  code += 'const ROUTING_KEY = \'' + registryKey + '\';  // Service Registry resolves aliases\n';
  code += '\n';
  code += '/**\n';
  code += ' * Send an RPC request to the Service Registry to invoke an alias.\n';
  code += ' * @param {string} aliasName - The alias name.\n';
  code += ' * @param {Array|null} args - Arguments for the alias.\n';
  code += ' * @returns {Promise<object>} Service response.\n';
  code += ' */\n';
  code += 'async function callAlias(aliasName, args = null) {\n';
  code += '  const res = await fetch(API_URL, {\n';
  code += '    method: \'POST\',\n';
  code += '    headers: { \'Content-Type\': \'application/json\' },\n';
  code += '    body: JSON.stringify({\n';
  code += '      method: aliasName,\n';
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

  var aliasNames = Object.keys(aliases);
  if (aliasNames.length > 0) {
    code += '(async () => {\n';
    aliasNames.forEach(function (aliasName) {
      var alias = aliases[aliasName];
      var serviceName = alias['Service name'] || '';
      var methodName = alias['Method name'] || '';
      var argsTemplate = alias['Arguments'] || '';
      var inputCount = _countInputPlaceholders(argsTemplate);

      var argsValue = 'null';
      if (inputCount > 0) {
        var placeholders = [];
        for (var i = 1; i <= inputCount; i++) {
          placeholders.push('\'arg' + i + '\'');
        }
        argsValue = '[' + placeholders.join(', ') + ']';
      }

      var varName = 'r_' + aliasName.replace(/\W/g, '_');
      code += '\n';
      code += '  // ' + aliasName + ' \u2192 ' + serviceName + '.' + methodName + '(' + argsTemplate + ')\n';
      code += '  const ' + varName + ' = await callAlias(\'' + aliasName + '\', ' + argsValue + ');\n';
      code += '  console.log(\'' + aliasName + ':\', ' + varName + ');\n';
    });
    code += '})();\n';
  } else {
    code += '// No aliases configured.\n';
  }

  return code;
}

/**
 * Show the Code Helper modal with example code for all configured aliases.
 */
function showAliasHelper() {
  var aliases = getAliasConfiguration();
  if (!aliases || Object.keys(aliases).length === 0) {
    MM.showToast('Code Helper', 'No aliases configured.', 'warning');
    return;
  }

  // Resolve broker host/port
  var brokerUrl = MM.brokerUrl || 'localhost:5672';
  var parts = brokerUrl.split(':');
  var brokerHost = parts[0] || 'localhost';
  var brokerPort = parts[1] || '5672';

  // Registry routing key — aliases are resolved by the Service Registry
  var registryKey = MM.routingKey || 'ServiceRegistry';

  // Generate code for each language
  var pythonCode = _generateAliasPythonCode(aliases, brokerHost, brokerPort, registryKey);
  var jsCode = _generateAliasJavaScriptCode(aliases, brokerHost, brokerPort, registryKey);
  var robotCode = _generateAliasRobotCode(aliases, brokerHost, brokerPort, registryKey);

  // Build modal body with language tabs (same structure as service helper)
  var titleHtml = '<h5>Alias Code Helper</h5>' +
    '<p class="text-muted mb-3">Example code for calling aliases via the Service Registry.</p>';

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
        '<pre class="helper-code-pre" id="helperCodePython">' + _escapeHtmlAlias(pythonCode) + '</pre>' +
      '</div>' +
      '<div class="tab-pane fade" id="helperTabJS" role="tabpanel">' +
        '<pre class="helper-code-pre" id="helperCodeJS">' + _escapeHtmlAlias(jsCode) + '</pre>' +
      '</div>' +
      '<div class="tab-pane fade" id="helperTabRobot" role="tabpanel">' +
        '<pre class="helper-code-pre" id="helperCodeRobot">' + _escapeHtmlAlias(robotCode) + '</pre>' +
      '</div>' +
    '</div>';

  document.getElementById('helperModalTitle').textContent = 'Helper \u2014 Alias';
  document.getElementById('helperModalBody').innerHTML = titleHtml + tabsHtml;

  var modal = new bootstrap.Modal(document.getElementById('helperModal'));
  modal.show();
}
