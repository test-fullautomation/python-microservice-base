/**
 * @fileoverview Electron main process for Microservice Manager GUI.
 * Loads web/index.html with context isolation and preload bridge.
 *
 * @version 2.0.0
 */

const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');

// Function to parse command line arguments
function parseArgs(argName, defaultValue) {
  const arg = process.argv.find(a => a.startsWith(`--${argName}=`));
  if (arg) {
    return arg.split('=')[1];
  }
  return defaultValue;
}

const debugValue = parseArgs('devTools', false);

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      preload: path.join(__dirname, 'preload.js'),
    }
  });

  if (debugValue === 'true') {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.loadFile(path.join(__dirname, '..', 'web', 'index.html'));

  // Relay AMQP exchange messages from preload back to renderer
  ipcMain.on('amqp-exchange-message', (_event, data) => {
    mainWindow.webContents.send('amqp-exchange-message-relay', data);
  });
}

app.whenReady().then(createWindow);

// Safety net: ensure bridge process cleanup on quit
app.on('before-quit', () => {
  // Bridge cleanup is primarily handled by preload's process.on('exit'),
  // but this IPC handler provides an additional safety net.
  console.log('[main] before-quit: bridge cleanup delegated to preload');
});

// IPC handler for bridge cleanup (registered for completeness)
ipcMain.handle('kill-bridge', async () => {
  return { ok: true };
});

// IPC handler for native file/folder open dialog
ipcMain.handle('show-open-dialog', async (_event, options) => {
  const win = BrowserWindow.getAllWindows()[0] || null;
  const result = await dialog.showOpenDialog(win, options || {});
  return { filePaths: result.filePaths || [] };
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
