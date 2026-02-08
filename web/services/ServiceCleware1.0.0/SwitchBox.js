/**
 * @fileoverview SwitchBox GUI plugin - browser-compatible version.
 * Uses MM (window.MicroserviceManager) namespace instead of global.
 *
 * @version 2.0.0
 */

var MM = window.MicroserviceManager;

function handleSwitchBoxContent() {
  console.log('Content inside the div has changed');
  const result = MM.clewareState;
  const deviceNumberSelect = document.getElementById('deviceNumber');
  if (!deviceNumberSelect || !result) return;
  const selectedValue = deviceNumberSelect.value;
  if (!result[selectedValue]) return;
  const valuesArray = Object.values(result[selectedValue]);
  updateIndicators(valuesArray);
}

const mapValue = {
  'in1' : 0,
  'in2' : 1,
  'out1' : 0,
  'out2' : 1,
  'out3' : 2,
  'out4' : 3,
};

const exampleArray = [1, 0, 0, 0, 0, 0, 0, 0];

function toggleLED(element) {
  element.classList.toggle('led-on');
}

function toggleLED(element, value) {
  element.classList.toggle('led-on');
  const currentState = element.classList.contains('led-on') ? 'on' : 'off';
  console.log(`Current state: ${currentState}`);
  updateSwitch(value, currentState);
}

function getOtherLEDValue(containerId) {
  const otherLEDs = document.querySelectorAll(`#${containerId} .led-indicator.led-on`);
  const otherLED = Array.from(otherLEDs).find(led => led.classList.contains('led-on'));
  return mapValue[otherLED.id];
}

function updateSwitch(ledIndex, onOff) {
  console.log(`LED Value: ${ledIndex}, `);
  var index = ledIndex;

  const hexString = "0x10";
  const sw0_idx = parseInt(hexString, 16);

  const deviceNumberSelect = document.getElementById('deviceNumber');
  const selectedValue = deviceNumberSelect.value;

  var jsonData = {
    'method': 'svc_api_set_switch',
    'args': [selectedValue, sw0_idx + index, onOff]
  };
  requestClewareService(jsonData)
    .then(function (data) {
      console.log(`Set sw return: ${data}`);
      getAllDevicesState();
    })
    .catch(function (error) {
      console.error('Error loading data:', error);
    });
}

function updateIndicators(array) {
  const allIndicators = document.querySelectorAll('.led');

  allIndicators.forEach((indicator, i) => {
    if (array[i] === 1)
      indicator.classList.toggle('led-on', true);
    else
      indicator.classList.toggle('led-on', false);
  });
}

// Subscribe to switch state updates via shared ServiceClient
MM.serviceClient.subscribeToExchange('updates_sw_state', function(result) {
  const deviceNumberSelect = document.getElementById('deviceNumber');
  if (!deviceNumberSelect) return; // panel not visible
  const selectedValue = deviceNumberSelect.value;
  if (!result[selectedValue]) return;
  const valuesArray = Object.values(result[selectedValue]);
  updateIndicators(valuesArray);
});
