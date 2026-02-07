/**
 * @fileoverview ServiceDebugboard GUI plugin - browser-compatible version.
 * Uses MM (window.MicroserviceManager) namespace instead of global.
 *
 * @version 2.0.0
 */

var MM = window.MicroserviceManager;

var ServiceDebugboard = {
  VERSION: "1.0.0",
  SERVICE_NAME: "ServiceDebugboard"
};

function requestDebugboardService(jsonData) {
  return MM.serviceClient.requestServiceDirect(jsonData, 'ServiceDebugboard');
}

function updateDebugboardDeviceList() {
  var jsonData = {
    'method': 'svc_api_get_list_devices',
    'args': null
  };
  requestDebugboardService(jsonData)
    .then(function (data) {
      MM.debugBoardState = data.result_data;
      populateDebugBoardDevices(data.result_data);
    })
    .catch(function (error) {
      console.error('Error loading data:', error);
    });
}

function sendCommand() {
  const commandInput = document.getElementById('commandInput').value;
  const commandOutput = document.getElementById('commandOutput');

  var jsonData = {
    'method': 'svc_api_call_remote_tool_command',
    'args': [commandInput]
  };
  requestDebugboardService(jsonData)
    .then(function (data) {
      commandOutput.value += data.result_data;
      commandOutput.value += '\n';
    })
    .catch(function (error) {
      console.error('Error loading data:', error);
    });
}

function showSuggestions() {
  const input = document.getElementById('commandInput').value;
  const suggestions = document.getElementById('suggestions');
  const commands = [
    'GET VERSION',
    'SET PROFILE=',
    'SET PORT='
  ];

  const filteredCommands = commands.filter(command => command.startsWith(input));

  suggestions.innerHTML = '';

  if (filteredCommands.length > 0 && input !== '') {
    suggestions.style.display = 'block';
    filteredCommands.forEach(command => {
      const suggestionItem = document.createElement('div');
      suggestionItem.classList.add('suggestion-item', 'p-2');
      suggestionItem.textContent = command;
      suggestionItem.onclick = () => {
        document.getElementById('commandInput').value = command;
        suggestions.style.display = 'none';
      };
      suggestions.appendChild(suggestionItem);
    });
  } else {
    suggestions.style.display = 'none';
  }
}

function populateDebugBoardDevices(data) {
  const debugBoardSelect = document.getElementById('connectedDebugBoard');

  debugBoardSelect.innerHTML = '';

  data.forEach(option => {
    const opt = document.createElement('option');
    opt.value = option;
    opt.text = option;
    debugBoardSelect.add(opt);
  });
}
