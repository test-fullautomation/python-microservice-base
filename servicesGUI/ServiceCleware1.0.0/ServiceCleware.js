// var amqp = require('amqplib/callback_api');
// var path = require('path');

global.clewareState = null;
const VERSION = "1.0.0";
const SERVICE_NAME = "ServiceCleware";
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
      const clewareDetailPath = path.resolve(`servicesGUI/${SERVICE_NAME}${VERSION}/Multiplexer.html`);
      loadContent(clewareDetailPath, 'SpecificClewareDevice', 'handleMultiplexerContent');
      
      // Add your specific logic here
      break;
    case 2:
      // Action for the second index
      console.log('Selected Device Type: Cleware Switch Box');
      const swBoxPath = path.resolve(`servicesGUI/${SERVICE_NAME}${VERSION}/SwitchBox.html`);
      loadContent(swBoxPath, 'SpecificClewareDevice', 'handleSwitchBoxContent');
      // Add your specific logic here
      break;
    // Add more cases as needed

    default:
      // Default action if index doesn't match any case
      console.log('Invalid selection');
  }
}

function populateSelect(data) {
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
  // // Add new options based on the data
  // data.result_data.forEach(function (value) {
  //   var option = document.createElement('option');
  //   option.text = value;
  //   select.add(option);
  // });
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