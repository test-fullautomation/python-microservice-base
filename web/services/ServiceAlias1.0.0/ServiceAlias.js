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
