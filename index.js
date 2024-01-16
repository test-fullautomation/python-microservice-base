/**
 * @fileoverview Manages actions and interactions for the Services Manager GUI.
 * This file contains functions responsible for handling user actions and events
 * within the Services Manager, such as connecting and configuring services.
 * 
 * @author Nguyen Huynh Tri Cuong
 * @version 1.0.0
 */

/************************************************************
 *                    Import Libraries                      *
 ************************************************************/

// Libraries and modules being imported
var amqp = require('amqplib/callback_api');
const fs = require('fs');
const unzipper = require('unzipper');
const { saveAs } = require('file-saver');
const path = require('path');
const { app, BrowserWindow } = require('electron');
const { ipcRenderer } = require('electron');
const { dialog } = require('electron');
const { title } = require('process');

/************************************************************
 *                    Global Variables                      *
 ************************************************************/

// Constants and global variables declared

global.brokerUrl = "localhost:5672";
global.routingKey = "";
global.servicesInfor = null;

const SERVICES_EXCHANGE_NAME = "services_request";
const SERVICES_GUI_FOLDER = "servicesGUI";
const SERVICE_CONTENT_DIV = "serviceContent";
const SERVICE_LIST_DIV = "servicesList";

const DIV_NAME = {
  SERVICE_CONTENT_DIV: "serviceContent",
  SERVICE_LIST_DIV: "servicesList"
};

const CONNECTION_STATUS = {  
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected'
};

const IMAGE_PATH = {
  NOT_READY: 'Image/not_ready.png',
  CONNECTED: 'Image/connected.png',
  UNCONNECTED: 'Image/unconnected.png'
};

const templateItem = {
  title: 'Switch Boxes',
  contentId: 'content-accordion-1',
  items: [
    {
      label: 'Cleware Controllers',
      iconSrc: IMAGE_PATH.NOT_READY,
      onClickFunction: 'activateItemAndLoadContent(this, "cleware")'
    }
    // Add more items as needed
  ]
};

var connectedStatus = false;
var unloadFunction = null;

ipcRenderer.on("login-data", (event, formData) => {
  console.log('Received login form data in index:', formData);
  if (connectedStatus === false)
  {
    // Add Alias service at beginning
    addAliasService();
    
    // Handle the received form data here
    setRegistryServiceInfo(formData);
    requestServicesInfor();
  }
});

/************************************************************
 *               Functions: GUI Element Handling             *
 ************************************************************/

/**
 * Activates an HTML element by adding the 'active' CSS class to it.
 *
 * @param {HTMLElement} element - The HTML element to be activated.
 */
 function activateItem(element) {
  // Remove 'active' class from all buttons
  const buttons = document.querySelectorAll('.list-group-item');
  buttons.forEach(btn => btn.classList.remove('active'));

  // Add 'active' class to the clicked button
  element.classList.add('active');
}

/**
 * Function to removes all service items from the GUI list.
 */
function clearServiceList()
{
  const accordion = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);

  // Remove all child elements (accordion items)
  while (accordion.firstChild) {
    accordion.removeChild(accordion.firstChild);
  }
}

/**
 * Function to removes service content GUI.
 */
function clearServiceContent()
{
  const contentService = document.getElementById(DIV_NAME.SERVICE_CONTENT_DIV);

  // Remove all child elements (accordion items)
  while (contentService.firstChild) {
    contentService.removeChild(contentService.firstChild);
  }
}

/**
 * Function to change the Connect button state when connection status changed.
 * 
 * @param {string} status - The connection status.
 */
function changeConnectButtonState(status) {
  const btnConnect = document.getElementById('btnConnect');

    // Update button state based on the status
    if (status === CONNECTION_STATUS.CONNECTED) {
        btnConnect.title = 'Disconnect'; // Update the title
        btnConnect.querySelector('img').src = 'Image/unconnected.png'; // Update the icon
        connectedStatus = true;
    } else if (status === CONNECTION_STATUS.DISCONNECTED) {
        btnConnect.title = 'Connect'; // Update the title
        btnConnect.querySelector('img').src = 'Image/connected.png'; // Update the icon
        connectedStatus = false;
    }
}

/**
 * Activates the GUI list item element of the specified service in the list and loads the content for that service.
 * 
 * @param {HTMLElement} element - The HTML element representing the service to be activated.
 * @param {string} serviceName - The name of the service to load the content for.
 */
function activateItemAndLoadContent(element, serviceName) {
  // Call activateItem function
  activateItem(element);

  if (global.servicesInfor[serviceName].gui_support === true)
  {
    const callBackFunc = () => loadServiceContent(serviceName, DIV_NAME.SERVICE_CONTENT_DIV);
    checkAndGetTheServiceGUIResources(serviceName, callBackFunc);
  }  
}

/**
 * Loads GUI resources of a service into a dynamic div.
 * 
 * @param {string} serviceName - The name of the service for loading GUI content.
 * @param {string} dynamicContentName - The name of the div where the service content will be loaded.
 * @param {string} callbackName - The name of the function to be called after loading the content.
 */
function loadServiceContent(serviceName, dynamicContentName, callbackName = '') {
  const folderPath = `${SERVICES_GUI_FOLDER}/${serviceName}${global.servicesInfor[serviceName].version}`;
  const externalContentFile = `${folderPath}/${serviceName}.html`;
  loadContent(externalContentFile, dynamicContentName, callbackName);
}



function normalizePath(path) {
  // Convert backslashes to forward slashes
  path = path.replace(/\\/g, '/');

  // If the path is relative, convert it to an absolute path
  if (!path.startsWith('/') && !path.match(/^\w+:/)) {
      // Assuming base URL is the same as the current page's URL
      const baseURL = new URL(window.location.href);
      path = new URL(path, baseURL).href;
  }

  // Add 'file://' prefix if it's a file system path
  if (path.match(/^\w:/)) {
      path = 'file:///' + path;
  }

  return path;
}

function isScriptAlreadyAdded(scriptPath) {
  const absoluteScriptPath = normalizePath(scriptPath);

  // Check if a script with the specified absolute source is already present
  Array.from(document.head.querySelectorAll('script')).forEach(scripObj => {
    console.log(`script child: ${normalizePath(scripObj.src)}`);
    console.log(`compare: ${absoluteScriptPath}`);
  });
  return Array.from(document.head.querySelectorAll('script'))
      .some(script => normalizePath(script.src) === absoluteScriptPath);
}

/**
 * Loads external content from an HTML file into a specified div.
 *
 * @param {string} externalContentFile - Path to the external HTML file.
 * @param {string} dynamicContentName - The name of the div where the external content will be loaded.
 * @param {string} callbackName - The name of the callback function to execute after loading.
 */
function loadContent(externalContentFile, dynamicContentName, callbackName = '') {
  
  console.log("Loading service content...");
  const dynamicContentDiv = document.getElementById(dynamicContentName);
  
  if (externalContentFile) {
    // Fetch and load the external content
    fetch(externalContentFile)
      .then(response => response.text())
      .then(htmlContent => {
        if (dynamicContentName === "serviceContent" && typeof unloadFunction === 'function') {
          unloadFunction();
       }
        dynamicContentDiv.innerHTML = htmlContent;      
        // Check if the script has been loaded
        const scriptSrc = externalContentFile.replace('.html', '.js');
        // if (!document.querySelector(`script[src="${scriptSrc}"]`)) {
        if (!isScriptAlreadyAdded(scriptSrc)) {
          
          // Create a new script element and set its attributes
          const script = document.createElement('script');
          script.src = scriptSrc;
          script.type = 'text/javascript';
          
          

          // Append the script to the document head
          document.head.appendChild(script);
           // When the script is loaded, execute the callback
          script.onload = function() {
            if (callbackName !== '') {
              // callback();
              window[callbackName]();
            }

            if (dynamicContentName === "serviceContent") {
              // Extract the filename without extension
              const filename = externalContentFile.split(/[\\/]/).pop().replace(/\..+$/, '');
  
              // Add the "load" prefix
              const functionName = "unload" + filename;
              unloadFunction = window[functionName];
            }
          };
        } else {
          // if (typeof unloadFunction === 'function') {
          //     unloadFunction();
          // }
          console.log(`Script '${scriptSrc}' has already been loaded.`);
          const filename = externalContentFile.split(/[\\/]/).pop().replace(/\..+$/, '');

            // Add the "load" prefix
          const functionName = "load" + filename;
          const loadFunction = window[functionName];
          if (typeof loadFunction === 'function') {
            loadFunction();
          }

          if (callbackName !== '') {
            // callback();
            window[callbackName]();
          }

          if (dynamicContentName === "serviceContent") {
            // Extract the filename without extension
            const filename = externalContentFile.split(/[\\/]/).pop().replace(/\..+$/, '');

            // Add the "load" prefix
            const functionName = "unload" + filename;
            unloadFunction = window[functionName];
          }
        }
  
      })
      .catch(error => {
        console.error('Error loading external content:', error);
      });
  } else {
    // Handle case where content type is not mapped
    console.error('Content type not found:', contentType);
  }
}

/**
 * Dynamically generates accordion items based on the provided service information data
 * and displays them in the GUI.
 *
 * @param {object} data - A structured information for multiple services.
 * @returns {void} - Displays accordion items for services in the GUI.
 */
function createAccordionItems(data) {
  const accordionElement = document.getElementById(DIV_NAME.SERVICE_LIST_DIV);

  data.forEach(section => {
    const accordionItem = document.createElement('div');
    accordionItem.classList.add('accordion-item', 'my-3', 'shadow');

    const accordionHeader = document.createElement('h2');
    accordionHeader.classList.add('accordion-header');

    const accordionButton = document.createElement('button');
    accordionButton.classList.add('accordion-button');
    accordionButton.type = 'button';
    accordionButton.dataset.bsToggle = 'collapse';
    accordionButton.dataset.bsTarget = `#${section.contentId}`;
    accordionButton.setAttribute('aria-expanded', 'true');
    accordionButton.textContent = section.title;

    accordionHeader.appendChild(accordionButton);

    const accordionCollapse = document.createElement('div');
    accordionCollapse.id = section.contentId;
    accordionCollapse.classList.add('accordion-collapse', 'collapse', 'show');
    accordionCollapse.dataset.bsParent = '#servicesList';

    const accordionBody = document.createElement('div');
    accordionBody.classList.add('accordion-body');

    const listGroup = document.createElement('div');
    listGroup.classList.add('list-group');

    section.items.forEach(item => {
      const listItem = document.createElement('button');
      listItem.type = 'button';
      listItem.classList.add('list-group-item', 'list-group-item-action');
      listItem.setAttribute('aria-current', 'true');
      listItem.onclick = () => eval(item.onClickFunction);
      
      const icon = document.createElement('img');
      icon.src = item.iconSrc;
      icon.alt = 'Icon';
      icon.classList.add('icon');

      const label = document.createTextNode(item.label);

      listItem.appendChild(icon);
      listItem.appendChild(label);
      listGroup.appendChild(listItem);
    });

    accordionBody.appendChild(listGroup);
    accordionCollapse.appendChild(accordionBody);
    
    accordionItem.appendChild(accordionHeader);
    accordionItem.appendChild(accordionCollapse);
    
    accordionElement.appendChild(accordionItem);
  });
}

// Function to display a warning dialog
function showWarningDialog(message) {
  const options = {
      type: 'warning',
      buttons: ['OK'],
      defaultId: 0,
      title: 'Warning',
      message: 'Warning!',
      detail: message,
  };

  dialog.showMessageBox(null, options);
}

/************************************************************
 *             Element Events Handling Section              *
 ************************************************************/

/**
 * Function to handle click event on Connect button.
 */
document.getElementById('btnConnect').addEventListener('click', () => {
  const btnConnect = document.getElementById('btnConnect');
  if (btnConnect.title === 'Connect') {
    connect();
  }
  else {
    disconnect();
  }
});

/**
 * Function to handle splitter..
 */
document.addEventListener('DOMContentLoaded', function () {
  // Query the element
  const resizer = document.getElementById('dragMe');
  const leftSide = resizer.previousElementSibling;
  const rightSide = resizer.nextElementSibling;

  // The current position of mouse
  let x = 0;
  let y = 0;
  let leftWidth = 0;

  // Handle the mousedown event
  // that's triggered when user drags the resizer
  const mouseDownHandler = function (e) {
      // Get the current mouse position
      x = e.clientX;
      y = e.clientY;
      leftWidth = leftSide.getBoundingClientRect().width;

      // Attach the listeners to document
      document.addEventListener('mousemove', mouseMoveHandler);
      document.addEventListener('mouseup', mouseUpHandler);
  };

  const mouseMoveHandler = function (e) {
      // How far the mouse has been moved
      const dx = e.clientX - x;
      const dy = e.clientY - y;

      const newLeftWidth = ((leftWidth + dx) * 100) / resizer.parentNode.getBoundingClientRect().width;
      leftSide.style.width = newLeftWidth + '%';

      resizer.style.cursor = 'col-resize';
      document.body.style.cursor = 'col-resize';

      leftSide.style.userSelect = 'none';
      leftSide.style.pointerEvents = 'none';

      rightSide.style.userSelect = 'none';
      rightSide.style.pointerEvents = 'none';
  };

  const mouseUpHandler = function () {
      resizer.style.removeProperty('cursor');
      document.body.style.removeProperty('cursor');

      leftSide.style.removeProperty('user-select');
      leftSide.style.removeProperty('pointer-events');

      rightSide.style.removeProperty('user-select');
      rightSide.style.removeProperty('pointer-events');

      // Remove the handlers of mousemove and mouseup
      document.removeEventListener('mousemove', mouseMoveHandler);
      document.removeEventListener('mouseup', mouseUpHandler);
  };

  // Attach the handler
  resizer.addEventListener('mousedown', mouseDownHandler);
});


/************************************************************
 *          Functions: Logic and Interaction with Services   *
 ************************************************************/

/**
 * Connect to Registry Service and get all services information.
 */
function connect() {
  ipcRenderer.send('open-popup-window');
  // ipcRenderer.on("login-data", (event, formData) => {
  //   console.log('Received login form data in index:', formData);
  //   if (connectedStatus === false)
  //   {
  //     // Add Alias service at beginning
  //     addAliasService();
      
  //     // Handle the received form data here
  //     setRegistryServiceInfo(formData);
  //     requestServicesInfor();
  //   }
  // });
}

function addAliasService() {
  const aliasServiceData = [
    {
      title: 'Alias Manager',
      contentId: 'content-accordion-alias',
      items: [
        {
          label: 'Alias',
          iconSrc: IMAGE_PATH.NOT_READY,
          onClickFunction: 'activateItemAndLoadContent(listItem, "ServiceAlias")'
        },
      ]
    },
  ];

  createAccordionItems(aliasServiceData);
  if (!global.servicesInfor) {
    global.servicesInfor = {};
  }

  global.servicesInfor.ServiceAlias = {
    description : "Service to alias specific sevice api to a api name.",
    group : "",
    gui_support : true,
    methods : [],
    name : "ServiceRegistry",
    routing_key: "",
    shortdesc : "Alias service",
    tag: "",
    version: "1.0.0"
  }
}

/**
 * Disconnect to Registry Service and clean services information.
 */
function disconnect() {
  global.brokerUrl = null;
  global.routingKey = null;
  global.servicesInfor = null;
  unloadFunction = null;
  clearServiceList();
  clearServiceContent();
  changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
}

/**
 * 
 * @param {object} registryData - The information of the Registry Service.
 */
function setRegistryServiceInfo(registryData)
{
  global.brokerUrl = registryData.brokerUrl;
  global.routingKey = registryData.routingKey;
}

/**
 * Extracts and structures services information from parsed JSON data.
 *
 * @param {object} data - Parsed JSON data containing services information.
 * @returns {object} - A structured representation of services information.
 */
function extractServicesInformation(data)
{
  const accordionData = Object.values(data).reduce((acc, service) => {
    const existingItem = acc.find(item => item.title === service.group);
    const newItem = {
      label: service.name,
      iconSrc: 'Image/not_ready.png',
      onClickFunction: `activateItemAndLoadContent(listItem, "${service.name}")`
      // Add other properties as needed
    };
  
    if (!existingItem) {
      if (service.group !== '')
        acc.push({
          title: service.group,
          contentId: `content-${service.group.replace(/ /g, "-").toLowerCase()}`,
          items: [newItem]
        });
    } else {
      existingItem.items.push(newItem);
    }
  
    return acc;
  }, []);
  
  console.log(accordionData); // Output the generated templateItems array
  return accordionData;
}

function checkAndGetTheServiceGUIResources(serviceName, callbackFunc=null)
{
  const folderPath = `${SERVICES_GUI_FOLDER}/${serviceName}${global.servicesInfor[serviceName].version}`;

  fs.access(folderPath, fs.constants.F_OK, (err) => {
    if (err) {
      // console.error('Folder does not exist');
      fs.mkdir(folderPath, { recursive: true }, (err) => {
        if (err) {
          console.error('Error creating folder:', err);
        } else {
          console.log(`Folder '${folderPath}' created successfully.`);
          requestServiceGUIResources(serviceName, folderPath, callbackFunc);
        }
      });
      
      return;
    }

    callbackFunc();
    console.log('Folder exists');
  });
}


/************************************************************
 *                  Service Request Functions               *
 ************************************************************/

/**
 * Function to get all services information from Registry Service.
 */
function requestServicesInfor() {
  var requestData = {
    'method': 'svc_api_get_services_info',
    'args': null
  };

  requestService(requestData, SERVICES_EXCHANGE_NAME, global.routingKey).then(function (data) {
    console.log("Received service infor: ", data);    
    const servicesInfor = JSON.parse(data.result_data);
    // global.servicesInfor = servicesInfor;
    global.servicesInfor = { ...global.servicesInfor, ...servicesInfor };
    const serviceItems = extractServicesInformation(servicesInfor);
    createAccordionItems(serviceItems);
    changeConnectButtonState(CONNECTION_STATUS.CONNECTED);
  })
  .catch(function (error) {
    console.error('Error loading data:', error);
    changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
  });
}
 
/**
 * Retrieves GUI resources of a service to be displayed on the GUI Manager.
 *
 * @param {string} serviceName - The name of the service for requesting GUI resources.
 * @param {string} folderPath - The path of the folder to store the resources.
 * @param {Function|null} [callbackFunc=null] - Optional callback function to be called after obtaining the resources. Defaults to null if not provided.
 */
function requestServiceGUIResources(serviceName, folderPath, callbackFunc=null)
{
  var requestData = {
    'method': 'svc_api_get_gui_files',
    'args': null
  };

  requestService(requestData, SERVICES_EXCHANGE_NAME, global.servicesInfor[serviceName].routing_key).then(function (data) {
    console.log("Received service infor: ", data);
    // const guiData = JSON.parse(data.result_data);
    let decodedBytes = atob(data.result_data);
    // const zipFilePath = 'received_files.zip';
    // fs.writeFileSync(zipFilePath, decodedBytes);
    // Convert the decoded string back to bytes
    const bytes = new Uint8Array(decodedBytes.length);
    for (let i = 0; i < decodedBytes.length; i++) {
      bytes[i] = decodedBytes.charCodeAt(i);
    }

    fs.writeFile(folderPath + '/received_files.zip', Buffer.from(bytes), (err) => {
      if (err) {
        console.error(err);
        // Handle error while saving file
      } else {
        console.log('File saved successfully:', folderPath + '/received_files.zip');
        // File saved successfully
        // Extract files from the received ZIP file
        fs.createReadStream(folderPath + '/received_files.zip')
        .pipe(unzipper.Extract({ path: folderPath })) // Replace with the path to save the extracted files
        .on('close', () => {
            console.log('All files received and extracted.');
            if (callbackFunc !== null)
              // callbackFunc(serviceName, 'serviceContent'); // Invoke the callback function after all files are received
              callbackFunc();

            fs.unlink(folderPath + '/received_files.zip', (err) => {
              if (err) {
                console.error('Error deleting file:', err);
              } else {
                console.log(`File '${folderPath}'/received_files.zip was successfully deleted.`);
              }
            });
        });
      }
    });
    
  })
  .catch(function (error) {
    console.error('Error loading data:', error);
    changeConnectButtonState(CONNECTION_STATUS.DISCONNECTED);
  });
}

/**
 * Sends a request data to a service via RabbitMQ.
 * 
 * @param {object} requestData - The JSON-formatted data to be sent.
 * @param {string} exchangeName - The name of the RabbitMQ exchange.
 * @param {string} routingKey - The routing key to route the data to the corresponding queue.
 * @returns {Promise} A Promise that resolves when the request is sent successfully, and rejects on failure.
 */
function requestService(requestData, exchangeName, routingKey) {
  return new Promise((resolve, reject) => {
    amqp.connect(`amqp://${global.brokerUrl}`, function(error0, connection) {
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

          console.log(' [x] Requesting Service with data:', requestData);

          channel.consume(q.queue, function(msg) {
            if (msg.properties.correlationId == correlationId) {
              const result = JSON.parse(msg.content.toString());
              console.log(' [.] Got response:', result);
              resolve(result);
              setTimeout(function() {
                connection.close();
              }, 500);
            }
          }, {
            noAck: true
          });

          // console.log(' [x] Requesting data in string:',JSON.stringify(requestData));
          channel.publish(exchangeName, routingKey, Buffer.from(JSON.stringify(requestData)),{
                correlationId: correlationId,
                replyTo: q.queue
          });
        });
      });
    });
  });
}


/************************************************************
 *                  Utility Functions                       *
 ************************************************************/

/**
 * Generates a Universally Unique Identifier (UUID) using a random-based algorithm.
 *
 * @returns {string} The generated UUID.
 */
function generateUuid() {
  return Math.random().toString() +
         Math.random().toString() +
         Math.random().toString();
}

/**
 * Creates a file in the specified folder from input bytes with a given file name.
 * 
 * @param {Uint8Array} bytes - The input bytes to be written into the file.
 * @param {string} fileName - The name of the file to be created.
 * @param {string} folderPath - The path of the folder where the file will be saved.
 * @returns {Promise<string>} A promise resolving to the full path of the created file.
 */
function createFileFromBytes(bytes, fileName, folderPath) {
  // Implementation to create a file from bytes in the specified folder with the given filename
}