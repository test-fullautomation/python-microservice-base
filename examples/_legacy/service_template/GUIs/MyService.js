/**
 * @fileoverview MyService GUI plugin — browser-compatible.
 * Uses MM (window.MicroserviceManager) namespace.
 *
 * Replace this file with your own GUI logic.
 */

var MM = window.MicroserviceManager;

var MyServiceGUI = {
  VERSION: '1.0.0',
  SERVICE_NAME: 'MyService'
};

/**
 * Call the svc_api_hello method and display the result.
 */
function callHello() {
  var name = document.getElementById('inputName').value || 'World';
  var requestData = {
    method: 'svc_api_hello',
    args: [name]
  };

  MM.requestService(requestData, 'services_request',
    MM.servicesInfor[MyServiceGUI.SERVICE_NAME].routing_key)
    .then(function (data) {
      var resultArea = document.getElementById('resultArea');
      var resultText = document.getElementById('resultText');
      resultText.textContent = data.result_data;
      resultArea.style.display = 'block';
    })
    .catch(function (error) {
      MM.showToast('Error', 'Request failed: ' + error.message, 'warning');
    });
}
