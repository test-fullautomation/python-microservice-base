/**
 * @fileoverview Multiplexer GUI plugin - browser-compatible version.
 * Uses MM (window.MicroserviceManager) namespace instead of global.
 *
 * @version 2.0.0
 */

const MM = window.MicroserviceManager;

function handleMultiplexerContent() {
  console.log('Content inside the div has changed');
  const result = MM.clewareState;
  const deviceNumberSelect = document.getElementById('deviceNumber');
  const selectedValue = deviceNumberSelect.value;
  const valuesArray = Object.values(result[selectedValue]);
  updateIndicators(valuesArray);
}

const mapOnOff = {
  0: ['in1', 'out1'],
  1: ['in1', 'out2'],
  2: ['in1', 'out3'],
  3: ['in1', 'out4'],
  4: ['in2', 'out1'],
  5: ['in2', 'out2'],
  6: ['in2', 'out3'],
  7: ['in2', 'out4']
};

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
  const containerId = element.parentElement.id;

  const allLEDs = document.querySelectorAll(`#${containerId} .led-indicator`);

  allLEDs.forEach(led => {
    if (led === element) {
      led.classList.toggle('led-on');
    } else {
      led.classList.remove('led-on');
    }
  });

  const otherLEDValue = getOtherLEDValue(containerId === 'usbIn' ? 'usbOut' : 'usbIn');
  updateSwitch(value, otherLEDValue, containerId);
}

function getOtherLEDValue(containerId) {
  const otherLEDs = document.querySelectorAll(`#${containerId} .led-indicator.led-on`);
  const otherLED = Array.from(otherLEDs).find(led => led.classList.contains('led-on'));
  return mapValue[otherLED.id];
}

function updateSwitch(ledValue, otherLEDValue, containerId) {
  console.log(`LED Value: ${ledValue}, Other LED Value: ${otherLEDValue}`);
  var index = 0;
  if (containerId === 'usbIn') {
    index = ledValue * 4 + otherLEDValue;
  } else {
    index = otherLEDValue * 4 + ledValue;
  }

  const hexString = "0x10";
  const sw0_idx = parseInt(hexString, 16);

  const deviceNumberSelect = document.getElementById('deviceNumber');
  const selectedValue = deviceNumberSelect.value;

  var jsonData = {
    'method': 'svc_api_set_switch',
    'args': [selectedValue, sw0_idx + index, 'on']
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
  const allIndicators = document.querySelectorAll('.led-indicator');

  allIndicators.forEach(indicator => {
    indicator.classList.toggle('led-on', false);
  });

  const onIndex = array.indexOf(1);
  if (onIndex === -1) {
    const inElement = document.getElementById('in1');
    inElement.classList.toggle('led-on', true);
    return;
  }
  const inElement = document.getElementById(onIndex < 4 ? 'in1' : 'in2');
  const outElement = document.getElementById('out' + (onIndex % 4 + 1));
  inElement.classList.toggle('led-on', true);
  outElement.classList.toggle('led-on', true);
}

// Subscribe to switch state updates via shared ServiceClient
MM.serviceClient.subscribeToExchange('updates_sw_state', function(result) {
  const deviceNumberSelect = document.getElementById('deviceNumber');
  const selectedValue = deviceNumberSelect.value;
  const valuesArray = Object.values(result[selectedValue]);
  updateIndicators(valuesArray);
});
