// var amqp = require('amqplib/callback_api');
// var path = require('path');

// global.clewareState = null;
// component1.js
var ServiceAlias = {
  VERSION: "1.0.0",
  SERVICE_NAME: "ServiceAlias"
};

let rowIndex = 1; // Track the index of rows

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
        input.type = 'text';
        input.value = key;
        input.dataset.type = 'name';
        cell.appendChild(input);
      } else if (colIndex === 3)
      {
        const input = document.createElement('input');
        input.type = 'text';
        input.value = data[key][header];
        input.dataset.type = 'args';
        cell.appendChild(input);
      } else {
        const select = document.createElement('select');
        select.classList.add("form-control");
        const option = document.createElement('option');
        option.value = data[key][header];
        option.style.width = "100px";
        option.textContent = data[key][header];
        select.appendChild(option);
        cell.appendChild(select);
      }
    });

    

    const minusCell = row.insertCell();
    const minusButton = document.createElement('button');
    minusButton.textContent = '-';
    minusButton.onclick = function() {
      row.remove();
    };
    minusButton.classList.add('btn', 'btn-danger');
    minusCell.appendChild(minusButton);

    if (index === Object.keys(data).length - 1) {
      const plusCell = row.insertCell();
      const plusButton = document.createElement('button');
      plusButton.textContent = '+';
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

// Function to populate options for combobox1
function populateServiceCombobox(combobox) {
  Object.keys(global.servicesInfor).forEach(key => {
    const option = document.createElement('option');
    option.value = key;
    option.textContent = key;
    combobox.appendChild(option);
  });
}

// Function to populate options for combobox2 based on the selected value of combobox1
function populateMethodCombobox(selectedValue, combobox) {
  const selectedObj = global.servicesInfor[selectedValue].methods;
  combobox.innerHTML = ''; // Clear existing options

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

  requestService(requestData, SERVICES_EXCHANGE_NAME, global.routingKey).then(function (data) {
    console.log("Received service infor: ", data);    
    const aliasInfor = JSON.parse(data.result_data);
    console.log(aliasInfor);
    populateTable(aliasInfor);
    // global.servicesInfor = servicesInfor;
    
  })
  .catch(function (error) {
    console.error('Error loading data:', error);
    changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
  });
}

function requestUpdateAliasInfor(data) {
  var requestData = {
    'method': 'svc_api_update_alias_conf',
    'args': data
  };

  requestService(requestData, SERVICES_EXCHANGE_NAME, global.routingKey).then(function (data) {
    console.log("Received service infor: ", data);    
    const retValue = JSON.parse(data.result_data);
    console.log(retValue);
    
  })
  .catch(function (error) {
    console.error('Error loading data:', error);
    changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
  });
}


// Add new row to the table
function addRow() {
  const tableBody = document.querySelector('#data-table tbody');
  const newRow = document.createElement('tr');
  
  newRow.innerHTML = `
    <td class="col-3"><input type="text" class="textbox" data-type="name" placeholder="Declare alias name here..."/></td>
    <td class="col-3" style="width:100px"><select class="form-control combobox1"></select></td>
    <td class="col-3" style="width:100px"><select class="form-control combobox2"></select></td>
    <td class="col-3"><input type="text" class="textbox" data-type="args" /></td>
  `;
  
  // Add a "-" button to remove the row
  const minusBtn = document.createElement('button');
  minusBtn.textContent = '-';
  minusBtn.onclick = function () {
    removeRow(newRow);
  };
  minusBtn.classList.add('btn', 'btn-danger'); // Add Bootstrap classes or any desired classes

  // Append the "-" button to the last cell
  const minusCell = document.createElement('td');
  minusCell.appendChild(minusBtn);
  newRow.appendChild(minusCell);

  // Remove "+" button from the previous last row
  const prevLastRow = tableBody.querySelector(`tr:nth-last-child(1)`);
  if (prevLastRow) {
    const prevLastCell = prevLastRow.lastElementChild;
    prevLastCell.innerHTML = ''; // Clear the last cell content
  }

  tableBody.appendChild(newRow);

  // Add "+" button to the last row
  const plusBtn = document.createElement('button');
  plusBtn.textContent = '+';
  plusBtn.onclick = addRow;
  plusBtn.classList.add('btn', 'btn-primary'); // Add Bootstrap classes or any desired classes

  const plusCell = document.createElement('td');
  plusCell.appendChild(plusBtn);
  newRow.appendChild(plusCell);

  rowIndex++;

  const serviceCombobox = newRow.querySelector('.combobox1');
  const methodCombobox = newRow.querySelector('.combobox2');

  // Populate options for combobox1 in the new row
  populateServiceCombobox(serviceCombobox);

  // Event listener for combobox1 change in the new row
  serviceCombobox.addEventListener('change', function () {
    const selectedValue = serviceCombobox.value;
    populateMethodCombobox(selectedValue, methodCombobox);
  });

  // Initially populate options for combobox2 in the new row based on the first option of combobox1
  populateMethodCombobox(serviceCombobox.value, methodCombobox);
}

function removeRow(row) {
  const table = document.getElementById('data-table');
  const tableBody = table.querySelector('tbody');

  const rows = tableBody.querySelectorAll('tr');
  if (rows.length > 1) {
    const lastRow = rows[rows.length - 1];
    const prevLastRow = tableBody.querySelector('tr:nth-last-child(2)');

    prevLastRow.querySelector('td:last-child').innerHTML = '<button class="btn btn-primary" onclick="addRow()">+</button>';
    tableBody.removeChild(lastRow);
  }
}

function getAliasConfiguration()
{
  document.getElementById('errorMessage').style.display = 'none';
  // Perform other actions if all textboxes are filled
  const table = document.getElementById('data-table');
  const rows = table.querySelectorAll('tbody tr');

  const jsonData = {};

  rows.forEach((row) => {
    const columns = row.querySelectorAll('td');
    const firstColumnValue = columns[0].querySelector('input').value;
    const rowData = {};

    for (let i = 1; i < columns.length - 2; i++) {
      const columnHeader = document.querySelector(`#data-table thead th:nth-child(${i + 1})`).innerText;
      const cellValue = columns[i].querySelector('input, select').value;
      rowData[columnHeader] = cellValue;
    }

    jsonData[firstColumnValue] = rowData;
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
          textboxes[j].classList.add('is-invalid'); // Adding Bootstrap validation class
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
  }
}
