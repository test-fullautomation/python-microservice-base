// var amqp = require('amqplib/callback_api');
// var path = require('path');

global.clewareState = null;
var ServiceCleware = {
  VERSION: "1.0.0",
  SERVICE_NAME: "ServiceCleware"
};
// let VERSION = "1.0.0";
// let SERVICE_NAME = "ServiceCleware";
// document.addEventListener('DOMContentLoaded', function () {
//   // Your JSON data
//   var jsonData = {
//     'method': 'get_all_devices_state',
//     'args': null
//   };
//   // Call the requestABC function when the page is loaded
//   requestClewareService(jsonData)
//     .then(function (data) {
//       // Assuming data is an array of values
//       populateSelect(data);
//     })
//     .catch(function (error) {
//       console.error('Error loading data:', error);
//     });
// });
var isInitialized = false;
function initializeServiceCleware()
{
  
}


function onInitizlizeCleware()
{
  getAllDevicesState();
  
}

function getAllDevicesState()
{
  var jsonData = {
    'method': 'svc_api_get_all_devices_state',
    'args': null
  };
  requestClewareService(jsonData)
    .then(function (data) {
      // Assuming data is an array of values
      global.clewareState = data.result_data;
      populateSelect(data);
    })
    .catch(function (error) {
      console.error('Error loading data:', error);
    });
}



function loadDetailCleware (){
  // Get the selected index
  var selectedIndex = document.getElementById('deviceType').selectedIndex;

  // Perform actions based on the selected index
  switch (selectedIndex) {
    case 1:
      // Action for the first index
      console.log('Selected Device Type: Cleware USB Multiplexer');
      const clewareDetailPath = path.resolve(`servicesGUI/${ServiceCleware.SERVICE_NAME}${ServiceCleware.VERSION}/Multiplexer.html`);
      loadContent(clewareDetailPath, 'SpecificClewareDevice', 'handleMultiplexerContent');
      break;
    case 2:
      // Action for the second index
      console.log('Selected Device Type: Cleware Switch Box');
      const swBoxPath = path.resolve(`servicesGUI/${ServiceCleware.SERVICE_NAME}${ServiceCleware.VERSION}/SwitchBox.html`);
      loadContent(swBoxPath, 'SpecificClewareDevice', 'handleSwitchBoxContent');
      break;

    default:
      // Default action if index doesn't match any case
      console.log('Invalid selection');
  }
}

function populateSelect(data) {
  if (!isInitialized)
  {
    var select = document.getElementById('deviceNumber');

    // Clear existing options
    while (select.options.length > 1) {
      select.remove(1);
    }

    // Access 'result_data' from 'data'
    const resultData = data.result_data;
    for (let key in resultData) {
      // Check if the key is a direct property of the object (not inherited)
      if (resultData.hasOwnProperty(key)) {
        var option = document.createElement('option');
        option.text = key;
        select.add(option);
      }
    }
    isInitialized = true;
  }
  // // Add new options based on the data
  // data.result_data.forEach(function (value) {
  //   var option = document.createElement('option');
  //   option.text = value;
  //   select.add(option);
  // });
}

function saveComboboxOptions() {
  const comboboxOptions = {
      deviceNumber: getComboboxOptions('deviceNumber'),
      deviceType: getComboboxOptions('deviceType')
      // Add more combobox options as needed
  };

  const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};
  savedState.comboboxOptions = comboboxOptions;

  localStorage.setItem('ServiceCleware', JSON.stringify(savedState));
}

// Function to get combobox options from localStorage
function getComboboxOptions(comboboxId) {
  const combobox = document.getElementById(comboboxId);
  const options = Array.from(combobox.options).map(option => ({
      value: option.value,
      text: option.text
  }));
  return options;
}

// Function to restore combobox options from localStorage
function restoreComboboxOptions() {
  const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};
  const comboboxOptions = savedState.comboboxOptions || {};

  setComboboxOptions('deviceNumber', comboboxOptions.deviceNumber);
  setComboboxOptions('deviceType', comboboxOptions.deviceType);
  // Restore options for other comboboxes as needed
}

// Function to set combobox options
function setComboboxOptions(comboboxId, options) {
  const combobox = document.getElementById(comboboxId);
  combobox.innerHTML = ""; // Clear existing options

  options.forEach(option => {
      const newOption = document.createElement('option');
      newOption.value = option.value;
      newOption.text = option.text;
      combobox.appendChild(newOption);
  });
}


function reloadServiceClewareData(){
  return new Promise((resolve, reject) => {
    const deviceNumberCombobox = document.getElementById('deviceNumber');
    const deviceTypeComboBox = document.getElementById('deviceType');

    // Example asynchronous task (getAllDevicesState)
    // getAllDevicesState();

    // Load saved state from localStorage
    const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};

    if (JSON.stringify(savedState) !== '{}') {
      restoreComboboxOptions();
      deviceNumberCombobox.value = savedState.deviceNumberComboboxValue || "";
      deviceTypeComboBox.value = savedState.deviceTypeComboBoxValue || "";
      resolve(); // Resolve the promise once tasks are complete
    } else {
      reject(new Error('No saved state found')); // Reject if no saved state
    }
  });
}

function loadServiceCleware()
{
  // const deviceNumberCombobox = document.getElementById('deviceNumber');
  // const deviceTypeComboBox = document.getElementById('deviceType');
  // getAllDevicesState();

  // // Load saved state from localStorage
  // const savedState = JSON.parse(localStorage.getItem('ServiceCleware')) || {};

  // if (JSON.stringify(savedState) !== '{}') {
  //   deviceNumberCombobox.value = savedState.deviceNumberComboboxValue || "";
  //   deviceTypeComboBox.value = savedState.deviceTypeComboBoxValue || "";
  //   loadDetailCleware();
  // }
  reloadServiceClewareData()
  .then(() => {
    // Only after loadServiceCleware has completed successfully,
    // we execute loadDetailCleware
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
  return new Promise((resolve, reject) => {
    amqp.connect('amqp://localhost', function(error0, connection) {
      if (error0) {
        reject(error0);
      }

      connection.createChannel(function(error1, channel) {
        if (error1) {
          reject(error1);
        }

        channel.assertQueue('', {
          exclusive: true
        }, function(error2, q) {
          if (error2) {
            reject(error2);
          }

          var correlationId = generateUuid();

          console.log(' [x] Requesting Cleware Service with data:', jsonData);

          channel.consume(q.queue, function(msg) {
            if (msg.properties.correlationId == correlationId) {
              const result = JSON.parse(msg.content.toString());
              console.log(' [.] Got response:', result);
              resolve(result);
              setTimeout(function() {
                connection.close();
                // process.exit(0);
              }, 500);
            }
          }, {
            noAck: true
          });

          channel.sendToQueue('ServiceCleware',
            Buffer.from(JSON.stringify(jsonData)),{
              correlationId: correlationId,
              replyTo: q.queue
            });
        });
      });
    });
  });
}

function generateUuid() {
  return Math.random().toString() +
         Math.random().toString() +
         Math.random().toString();
}

// Export the requestABC function
module.exports = requestClewareService;