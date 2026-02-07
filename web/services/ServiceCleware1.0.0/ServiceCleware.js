/**
 * @fileoverview ServiceCleware GUI plugin - browser-compatible version.
 * Uses MM (window.MicroserviceManager) namespace instead of global/require.
 *
 * @version 2.0.0
 */

const MM = window.MicroserviceManager;

MM.clewareState = null;

var ServiceCleware = {
  VERSION: "1.0.0",
  SERVICE_NAME: "ServiceCleware"
};

var isInitialized = false;

function initializeServiceCleware() {
}

function onInitizlizeCleware() {
  getAllDevicesState();
}

function getAllDevicesState() {
  var jsonData = {
    'method': 'svc_api_get_all_devices_state',
    'args': null
  };
  requestClewareService(jsonData)
    .then(function (data) {
      MM.clewareState = data.result_data;
      populateSelect(data);
    })
    .catch(function (error) {
      console.error('Error loading data:', error);
    });
}

function loadDetailCleware() {
  var selectedIndex = document.getElementById('deviceType').selectedIndex;

  switch (selectedIndex) {
    case 1:
      console.log('Selected Device Type: Cleware USB Multiplexer');
      var clewareDetailPath = 'services/' + ServiceCleware.SERVICE_NAME + ServiceCleware.VERSION + '/Multiplexer.html';
      MM.loadContent(clewareDetailPath, 'SpecificClewareDevice', 'handleMultiplexerContent');
      break;
    case 2:
      console.log('Selected Device Type: Cleware Switch Box');
      var swBoxPath = 'services/' + ServiceCleware.SERVICE_NAME + ServiceCleware.VERSION + '/SwitchBox.html';
      MM.loadContent(swBoxPath, 'SpecificClewareDevice', 'handleSwitchBoxContent');
      break;
    default:
      console.log('Invalid selection');
  }
}

function populateSelect(data) {
  if (!isInitialized) {
    var select = document.getElementById('deviceNumber');

    while (select.options.length > 1) {
      select.remove(1);
    }

    const resultData = data.result_data;
    for (let key in resultData) {
      if (resultData.hasOwnProperty(key)) {
        var option = document.createElement('option');
        option.text = key;
        select.add(option);
      }
    }
    isInitialized = true;
  }
}

function saveComboboxOptions() {
  const comboboxOptions = {
    deviceNumber: getComboboxOptions('deviceNumber'),
    deviceType: getComboboxOptions('deviceType')
  };

  const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};
  savedState.comboboxOptions = comboboxOptions;
  localStorage.setItem('ServiceCleware', JSON.stringify(savedState));
}

function getComboboxOptions(comboboxId) {
  const combobox = document.getElementById(comboboxId);
  const options = Array.from(combobox.options).map(option => ({
    value: option.value,
    text: option.text
  }));
  return options;
}

function restoreComboboxOptions() {
  const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};
  const comboboxOptions = savedState.comboboxOptions || {};

  setComboboxOptions('deviceNumber', comboboxOptions.deviceNumber);
  setComboboxOptions('deviceType', comboboxOptions.deviceType);
}

function setComboboxOptions(comboboxId, options) {
  const combobox = document.getElementById(comboboxId);
  combobox.innerHTML = "";

  options.forEach(option => {
    const newOption = document.createElement('option');
    newOption.value = option.value;
    newOption.text = option.text;
    combobox.appendChild(newOption);
  });
}

function reloadServiceClewareData() {
  return new Promise((resolve, reject) => {
    const deviceNumberCombobox = document.getElementById('deviceNumber');
    const deviceTypeComboBox = document.getElementById('deviceType');

    const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};

    if (JSON.stringify(savedState) !== '{}') {
      restoreComboboxOptions();
      deviceNumberCombobox.value = savedState.deviceNumberComboboxValue || "";
      deviceTypeComboBox.value = savedState.deviceTypeComboBoxValue || "";
      resolve();
    } else {
      reject(new Error('No saved state found'));
    }
  });
}

function loadServiceCleware() {
  reloadServiceClewareData()
    .then(() => {
      loadDetailCleware();
    })
    .catch((error) => {
      console.error('Error during loadServiceCleware:', error.message);
    });
}

function unloadServiceCleware() {
  saveState();
  saveComboboxOptions();
}

function saveState() {
  const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};
  const deviceNumberCombobox = document.getElementById('deviceNumber');
  const deviceTypeComboBox = document.getElementById('deviceType');
  savedState.deviceNumberComboboxValue = deviceNumberCombobox.value;
  savedState.deviceTypeComboBoxValue = deviceTypeComboBox.value;
  localStorage.setItem('ServiceCleware', JSON.stringify(savedState));
}

function requestClewareService(jsonData) {
  return MM.serviceClient.requestServiceDirect(jsonData, 'ServiceCleware');
}
