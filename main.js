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
    popupWindow = null;
  });
}

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
  // mainWindow.webContents.openDevTools();

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