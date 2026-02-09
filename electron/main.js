/**
 * @fileoverview Electron main process for Microservice Manager GUI.
 * Loads web/index.html with context isolation and preload bridge.
 *
 * @version 2.1.0
 */

const { app, BrowserWindow, dialog, ipcMain, protocol } = require('electron');
const path = require('path');
const fs = require('fs');

// Function to parse command line arguments
function parseArgs(argName, defaultValue) {
  const arg = process.argv.find(a => a.startsWith(`--${argName}=`));
  if (arg) {
    return arg.split('=')[1];
  }
  return defaultValue;
}

const debugValue = parseArgs('devTools', false);

// Expose packaging metadata to preload via environment variables
process.env.DASGUI_IS_PACKAGED = app.isPackaged ? '1' : '0';
process.env.DASGUI_USER_DATA = app.getPath('userData');
process.env.DASGUI_RESOURCES_PATH = process.resourcesPath || '';

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

app.whenReady().then(() => {
  // In packaged mode, intercept file:// requests for web/services/*
  // and redirect them to the writable user data directory.
  // Service plugins are extracted to %APPDATA%/DevAtServGUI/web-services/
  // but the HTML references them as relative paths (services/FooService/...).
  if (app.isPackaged) {
    protocol.interceptFileProtocol('file', (request, callback) => {
      const url = decodeURI(request.url);

      // Detect requests for service plugins (web/services/...)
      if (url.includes('/web/services/')) {
        const relPath = url.split('/web/services/').pop();
        // Check writable user data first
        const userServicesDir = path.join(app.getPath('userData'), 'web-services');
        const localPath = path.join(userServicesDir, relPath);
        if (fs.existsSync(localPath)) {
          callback({ path: localPath });
          return;
        }
        // Fall back to bundled plugins in resources/
        const bundledPath = path.join(process.resourcesPath, 'web-services', relPath);
        if (fs.existsSync(bundledPath)) {
          callback({ path: bundledPath });
          return;
        }
      }

      // Default handling (including asar reads)
      let filePath = new URL(request.url).pathname;
      // On Windows, remove leading slash from /C:/...
      if (process.platform === 'win32' && filePath.startsWith('/')) {
        filePath = filePath.substring(1);
      }
      callback({ path: decodeURIComponent(filePath) });
    });
  }

  createWindow();
});

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
