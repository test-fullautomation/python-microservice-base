const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

let popupWindow;

function createPopupWindow(parentWindow) {
  popupWindow = new BrowserWindow({
    width: 550,
    height: 600,
    title: "Connect to Broker",
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: true, // Enable Node.js integration in the window
      contextIsolation: false
    },
    parent: parentWindow, // Optional: Specify the parent window if you have one
    modal: true, // Optional: Make the popup window modal
    show: false // Hide the window initially
  });

  // popupWindow.webContents.openDevTools();

  popupWindow.loadFile(path.join(__dirname, 'login.html')); // Load an HTML file for the popup window

  popupWindow.on('closed', () => {
    console.log("Closing login window....")
    popupWindow = null;
  });
}

// Function to parse command line arguments
function parseArgs(argName, defaultValue) {
  const arg = process.argv.find(arg => arg.startsWith(`--${argName}=`));
  if (arg) {
    return arg.split('=')[1]; // Get the value part after '='
  }
  return defaultValue;
}

// Get the value of "--abc" argument or use false as default
const debugValue = parseArgs('devTools', false);

// Use the parsed value as needed
// console.log('Value of "--devTools":', debugValue);

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 800,
    height: 1000,
    autoHideMenuBar: true,
    // The lines below solved the issue
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  // Enable debugging for the main process
  if (debugValue == 'true') {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.loadFile(path.join(__dirname, 'index.html')); // Load index.html from the same directory as index.js

  ipcMain.on('open-popup-window', () => {
    if (!popupWindow || popupWindow.isDestroyed()) {
      createPopupWindow(mainWindow);
      popupWindow.show();
    }
  });

  ipcMain.on('login-form-data', (event, formData) => {
    console.log('Received login form data in main:', formData);
    mainWindow.webContents.send("login-data", formData);
    // Handle the received form data here
  });
}

app.whenReady().then(createWindow);