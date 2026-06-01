/**
 * @fileoverview Electron preload script.
 * Exposes a safe bridge API via contextBridge for AMQP and filesystem operations.
 *
 * @version 2.1.0
 */

const { contextBridge, ipcRenderer, shell } = require('electron');

let amqp, fs, os, path, crypto, unzipper, child_process;
try {
  amqp = require('amqplib/callback_api');
  fs = require('fs');
  os = require('os');
  path = require('path');
  crypto = require('crypto');
  unzipper = require('unzipper');
  child_process = require('child_process');
  console.log('[preload] All Node.js modules loaded successfully');
} catch (err) {
  console.error('[preload] Failed to load Node.js modules:', err.message);
  console.error('[preload] Make sure you ran "npm install" in the project directory');
}

// ---- Packaging-aware path constants ----
const _isPackaged = process.env.DASGUI_IS_PACKAGED === '1';
const _userDataPath = process.env.DASGUI_USER_DATA || path.join(__dirname, '..');
const _resourcesPath = _isPackaged
  ? (process.env.DASGUI_RESOURCES_PATH || process.resourcesPath)
  : path.join(__dirname, '..');

// Read-only Python source files (scripts bundled in extraResources)
const _pythonSrcPath = path.join(_resourcesPath, 'python');

// Writable Python data directory (PID, logs, config, user services)
const _pythonDataPath = _isPackaged
  ? path.join(_userDataPath, 'python')
  : path.join(__dirname, '..', 'python');

// Writable web services directory (GUI plugin extraction target)
const _webServicesPath = _isPackaged
  ? path.join(_userDataPath, 'web-services')
  : path.join(__dirname, '..', 'web', 'services');

// Store exchange message callbacks keyed by exchange name
// so messages are only dispatched to the correct subscribers.
const _exchangeCallbacks = {};  // { exchangeName: [callback, ...] }

// Settings file path
const _settingsPath = _isPackaged
  ? path.join(_userDataPath, 'settings.json')
  : path.join(__dirname, 'settings.json');

// Bridge process management
let _bridgeProcess = null;

// PID file — persists the bridge PID so we can reconnect across GUI sessions
const _pidFilePath = path.join(_pythonDataPath, 'bridge.pid');

// ---- First-run initialization (packaged mode only) ----

function _copyDirSync(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  var entries = fs.readdirSync(src, { withFileTypes: true });
  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i];
    var srcPath = path.join(src, entry.name);
    var destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      _copyDirSync(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function _ensureWritableData() {
  if (!_isPackaged) return;

  // Create writable directory structure
  fs.mkdirSync(_pythonDataPath, { recursive: true });
  fs.mkdirSync(path.join(_pythonDataPath, 'services'), { recursive: true });
  fs.mkdirSync(path.join(_pythonDataPath, 'logs'), { recursive: true });
  fs.mkdirSync(_webServicesPath, { recursive: true });

  // Copy entire python resources tree to writable data dir.
  // .py files and subdirs (e.g. services/) are always overwritten (code, not user data).
  // Config files (config.json, hub_processes.json) are only copied if not present (user may customize).
  var userConfigFiles = { 'config.json': true, 'hub_processes.json': true };
  function _syncPythonDir(srcDir, destDir) {
    fs.mkdirSync(destDir, { recursive: true });
    var entries = fs.readdirSync(srcDir, { withFileTypes: true });
    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i];
      var srcPath = path.join(srcDir, entry.name);
      var destPath = path.join(destDir, entry.name);
      if (entry.isDirectory()) {
        _syncPythonDir(srcPath, destPath);
      } else if (userConfigFiles[entry.name] && srcDir === _pythonSrcPath) {
        // User config: copy only if not present
        if (!fs.existsSync(destPath)) {
          fs.copyFileSync(srcPath, destPath);
          console.log('[preload] Copied template:', entry.name);
        }
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  }
  _syncPythonDir(_pythonSrcPath, _pythonDataPath);

  // Copy default settings if not present
  if (!fs.existsSync(_settingsPath)) {
    var defaultSettings = path.join(_resourcesPath, 'settings.json');
    if (fs.existsSync(defaultSettings)) {
      fs.copyFileSync(defaultSettings, _settingsPath);
      console.log('[preload] Copied default settings.json');
    } else {
      fs.writeFileSync(_settingsPath, '{}', 'utf8');
    }
  }

  // Copy bundled web service plugins if writable dir is empty
  var bundledPlugins = path.join(_resourcesPath, 'web-services');
  if (fs.existsSync(bundledPlugins)) {
    var items = fs.readdirSync(bundledPlugins);
    for (var j = 0; j < items.length; j++) {
      var destItem = path.join(_webServicesPath, items[j]);
      if (!fs.existsSync(destItem)) {
        _copyDirSync(path.join(bundledPlugins, items[j]), destItem);
        console.log('[preload] Copied bundled plugin:', items[j]);
      }
    }
  }
}

try {
  _ensureWritableData();
} catch (e) {
  console.error('[preload] First-run init error:', e.message);
}

console.log('[preload] Packaging mode:', _isPackaged ? 'PACKAGED' : 'DEV');
console.log('[preload] Python src:', _pythonSrcPath);
console.log('[preload] Python data:', _pythonDataPath);
console.log('[preload] Web services:', _webServicesPath);
console.log('[preload] Settings:', _settingsPath);

// ---- Helper functions ----

/**
 * Check whether a process with the given PID is still alive.
 */
function _isProcessAlive(pid) {
  try {
    process.kill(pid, 0); // signal 0 = existence check only
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Read the saved bridge PID from disk.  Returns the PID (number) or null.
 */
function _readSavedPid() {
  try {
    const raw = fs.readFileSync(_pidFilePath, 'utf8').trim();
    const pid = parseInt(raw, 10);
    return isNaN(pid) ? null : pid;
  } catch (e) {
    return null;
  }
}

/**
 * Persist a PID to the PID file.
 */
function _writePid(pid) {
  try { fs.writeFileSync(_pidFilePath, String(pid), 'utf8'); } catch (e) {}
}

/**
 * Remove the PID file.
 */
function _removePidFile() {
  try { fs.unlinkSync(_pidFilePath); } catch (e) {}
}

/**
 * Resolve a web/services relative path to the writable services directory.
 * In dev mode, resolves relative to web/. In packaged mode, resolves to _webServicesPath.
 * @param {string} folderPath - Path like "services/ServiceFoo1.0.0"
 * @returns {string} Absolute path
 */
function _resolveServicesPath(folderPath) {
  if (_isPackaged) {
    // Strip "services/" prefix since _webServicesPath already points to the services root
    var subPath = folderPath.replace(/^services\/?/, '');
    return path.join(_webServicesPath, subPath);
  }
  return path.join(__dirname, '..', 'web', folderPath);
}

// Do NOT auto-kill the bridge on Electron exit — let the backend
// (registry + bridge) keep running independently so services stay
// discoverable even after the GUI is closed.

contextBridge.exposeInMainWorld('electronAPI', {

  /**
   * Open an external URL in the default browser.
   * Only allows http/https URLs for safety.
   * @param {string} url - The URL to open.
   * @returns {Promise<void>|undefined}
   */
  openExternal: (url) => {
    if (typeof url === 'string' && (url.startsWith('https://') || url.startsWith('http://'))) {
      return shell.openExternal(url);
    }
  },

  /**
   * Show a native open dialog (folder or file picker).
   * @param {object} options - Electron dialog.showOpenDialog options.
   * @returns {Promise<{filePaths: string[]}>}
   */
  showOpenDialog: (options) => {
    return ipcRenderer.invoke('show-open-dialog', options || {});
  },

  /**
   * Check if a folder exists.
   * @param {string} folderPath - Path to check (relative to web/).
   * @returns {Promise<boolean>}
   */
  folderExists: (folderPath) => {
    return new Promise((resolve) => {
      const fullPath = _resolveServicesPath(folderPath);
      fs.access(fullPath, fs.constants.F_OK, (err) => {
        resolve(!err);
      });
    });
  },

  /**
   * Compute an MD5 checksum of all files in a service GUI folder.
   * Mirrors the Python ServiceBase.svc_api_get_gui_checksum() algorithm:
   *   for each file (sorted), hash relative_path + file_content.
   * @param {string} folderPath - Relative path (e.g. "services/MyService1.0.0").
   * @returns {Promise<string|null>} MD5 hex-digest, or null if folder missing.
   */
  computeGuiChecksum: (folderPath) => {
    return new Promise((resolve) => {
      const fullPath = _resolveServicesPath(folderPath);
      if (!fs.existsSync(fullPath)) { resolve(null); return; }

      // Recursively collect all files with relative paths (sorted)
      const allFiles = [];
      const walk = (dir) => {
        let entries;
        try { entries = fs.readdirSync(dir).sort(); } catch (_) { return; }
        for (const name of entries) {
          const fp = path.join(dir, name);
          try {
            if (fs.statSync(fp).isDirectory()) { walk(fp); }
            else { allFiles.push(path.relative(fullPath, fp).replace(/\\/g, '/')); }
          } catch (_) { /* skip unreadable */ }
        }
      };
      walk(fullPath);

      const hasher = crypto.createHash('md5');
      for (const relPath of allFiles) {
        hasher.update(relPath, 'utf8');
        try {
          const content = fs.readFileSync(path.join(fullPath, relPath));
          hasher.update(content);
        } catch (_) { /* skip unreadable */ }
      }
      resolve(hasher.digest('hex'));
    });
  },

  /**
   * List files in a service GUI folder.
   * @param {string} folderPath - Relative path (e.g. "services/MyService1.0.0").
   * @returns {string[]} Array of filenames (files only, no directories).
   */
  listDir: (folderPath) => {
    const fullPath = _resolveServicesPath(folderPath);
    try {
      return fs.readdirSync(fullPath).filter((f) => {
        try { return fs.statSync(path.join(fullPath, f)).isFile(); }
        catch (_) { return false; }
      });
    } catch (_) {
      return [];
    }
  },

  /**
   * Extract a base64-encoded ZIP file to a folder.
   * @param {string} folderPath - Relative path for extraction (under web/).
   * @param {string} base64Data - Base64-encoded ZIP content.
   * @returns {Promise<void>}
   */
  extractGUIZip: async (folderPath, base64Data) => {
    const fullPath = _resolveServicesPath(folderPath);
    await fs.promises.mkdir(fullPath, { recursive: true });

    // Decode base64 directly to Buffer (avoids atob overhead).
    const zipBuffer = Buffer.from(base64Data, 'base64');
    const zipFilePath = path.join(os.tmpdir(), 'mm_gui_' + Date.now() + '.zip');

    try {
      await fs.promises.writeFile(zipFilePath, zipBuffer);

      // Use Open.file() + entry.buffer() to read each entry fully into
      // memory before writing. The streaming unzipper.Extract() corrupts
      // medium/large files (content appears rotated/shifted).
      const directory = await unzipper.Open.file(zipFilePath);

      for (const entry of directory.files) {
        if (entry.type === 'Directory') {
          await fs.promises.mkdir(path.join(fullPath, entry.path), { recursive: true });
          continue;
        }
        // Ensure parent directory exists.
        const destPath = path.join(fullPath, entry.path);
        await fs.promises.mkdir(path.dirname(destPath), { recursive: true });

        const content = await entry.buffer();
        await fs.promises.writeFile(destPath, content);
      }

      console.log('All files received and extracted to', fullPath);
    } finally {
      fs.unlink(zipFilePath, () => {});
    }
  },

  /**
   * Send an AMQP request via exchange + routing key and get a response.
   * @param {object} requestData - Request data with 'method' and 'args'.
   * @param {string} exchangeName - The exchange name.
   * @param {string} routingKey - The routing key.
   * @param {string} brokerUrl - Broker URL (host:port).
   * @returns {Promise<object>}
   */
  amqpRequest: (requestData, exchangeName, routingKey, brokerUrl) => {
    const RPC_TIMEOUT_MS = 15000;
    return new Promise((resolve, reject) => {
      let settled = false;
      let conn = null;

      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          try { if (conn) conn.close(); } catch (_) {}
          reject(new Error('RPC timeout: no response after ' + (RPC_TIMEOUT_MS / 1000) + 's (is the target service running?)'));
        }
      }, RPC_TIMEOUT_MS);

      amqp.connect(`amqp://${brokerUrl}`, (error0, connection) => {
        if (settled) return;
        if (error0) {
          settled = true;
          clearTimeout(timer);
          reject(error0);
          return;
        }

        conn = connection;

        connection.createChannel((error1, channel) => {
          if (settled) return;
          if (error1) {
            settled = true;
            clearTimeout(timer);
            reject(error1);
            return;
          }

          channel.assertQueue('', { exclusive: true }, (error2, q) => {
            if (settled) return;
            if (error2) {
              settled = true;
              clearTimeout(timer);
              reject(error2);
              return;
            }

            const correlationId = _generateUuid();
            console.log(' [x] Requesting Service with data:', requestData);

            channel.consume(q.queue, (msg) => {
              if (msg.properties.correlationId == correlationId && !settled) {
                settled = true;
                clearTimeout(timer);
                const result = JSON.parse(msg.content.toString());
                console.log(' [.] Got response:', result);
                resolve(result);
                setTimeout(() => { connection.close(); }, 500);
              }
            }, { noAck: true });

            channel.publish(exchangeName, routingKey, Buffer.from(JSON.stringify(requestData)), {
              correlationId: correlationId,
              replyTo: q.queue,
            });
          });
        });
      });
    });
  },

  /**
   * Send a direct AMQP request to a specific queue.
   * @param {object} requestData - Request data.
   * @param {string} queueName - Target queue name.
   * @param {string} brokerUrl - Broker URL (host:port).
   * @returns {Promise<object>}
   */
  amqpRequestDirect: (requestData, queueName, brokerUrl) => {
    const RPC_TIMEOUT_MS = 15000;
    return new Promise((resolve, reject) => {
      let settled = false;
      let conn = null;

      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          try { if (conn) conn.close(); } catch (_) {}
          reject(new Error('RPC timeout: no response after ' + (RPC_TIMEOUT_MS / 1000) + 's (is the target service running?)'));
        }
      }, RPC_TIMEOUT_MS);

      amqp.connect(`amqp://${brokerUrl}`, (error0, connection) => {
        if (settled) return;
        if (error0) {
          settled = true;
          clearTimeout(timer);
          reject(error0);
          return;
        }

        conn = connection;

        connection.createChannel((error1, channel) => {
          if (settled) return;
          if (error1) {
            settled = true;
            clearTimeout(timer);
            reject(error1);
            return;
          }

          channel.assertQueue('', { exclusive: true }, (error2, q) => {
            if (settled) return;
            if (error2) {
              settled = true;
              clearTimeout(timer);
              reject(error2);
              return;
            }

            const correlationId = _generateUuid();
            console.log(' [x] Requesting Service Direct with data:', requestData);

            channel.consume(q.queue, (msg) => {
              if (msg.properties.correlationId == correlationId && !settled) {
                settled = true;
                clearTimeout(timer);
                const result = JSON.parse(msg.content.toString());
                console.log(' [.] Got response:', result);
                resolve(result);
                setTimeout(() => { connection.close(); }, 500);
              }
            }, { noAck: true });

            channel.sendToQueue(queueName, Buffer.from(JSON.stringify(requestData)), {
              correlationId: correlationId,
              replyTo: q.queue,
            });
          });
        });
      });
    });
  },

  /**
   * Subscribe to an AMQP fanout exchange.
   * Messages are delivered directly to registered callbacks (no IPC relay).
   * @param {string} exchangeName - The fanout exchange name.
   * @param {string} brokerUrl - Broker URL (host:port).
   */
  amqpSubscribe: (exchangeName, brokerUrl) => {
    console.log('[preload] amqpSubscribe called for exchange:', exchangeName, 'broker:', brokerUrl);
    amqp.connect(`amqp://${brokerUrl}`, (error0, connection) => {
      if (error0) {
        console.error('[preload] AMQP subscribe connection error:', error0);
        return;
      }
      console.log('[preload] AMQP subscribe connected');

      connection.on('error', (err) => {
        console.error('[preload] AMQP subscribe connection error event:', err.message);
      });

      connection.createChannel((error1, channel) => {
        if (error1) {
          console.error('[preload] AMQP subscribe channel error:', error1);
          return;
        }
        console.log('[preload] AMQP subscribe channel created');

        channel.on('error', (err) => {
          console.error('[preload] AMQP subscribe channel error event:', err.message);
        });

        // amqplib serializes channel operations — call them sequentially (not nested)
        channel.assertExchange(exchangeName, 'fanout', { durable: false });
        console.log('[preload] assertExchange queued for:', exchangeName);

        channel.assertQueue('', { exclusive: true }, (error2, q) => {
          if (error2) {
            console.error('[preload] AMQP subscribe queue error:', error2);
            return;
          }
          console.log('[preload] Queue created:', q.queue);

          channel.bindQueue(q.queue, exchangeName, '');
          console.log('[preload] bindQueue queued:', q.queue, '->', exchangeName);

          channel.consume(q.queue, (msg) => {
            if (msg && msg.content) {
              const raw = msg.content.toString();
              console.log('[preload] Fanout message received, length:', raw.length);
              try {
                const result = JSON.parse(raw);
                const cbs = _exchangeCallbacks[exchangeName] || [];
                cbs.forEach((cb) => {
                  try { cb(result); } catch (e) {
                    console.error('[preload] Exchange callback error (' + exchangeName + '):', e);
                  }
                });
              } catch (parseErr) {
                console.error('[preload] Failed to parse fanout message:', parseErr);
              }
            }
          }, { noAck: true });

          console.log('[preload] Subscribed to exchange:', exchangeName, 'via queue:', q.queue);
        });
      });
    });
  },

  /**
   * Register a callback for a specific exchange's messages.
   * @param {string} exchangeName - The exchange to listen to.
   * @param {Function} callback - Called with parsed message data.
   */
  onExchangeMessage: (exchangeName, callback) => {
    if (!_exchangeCallbacks[exchangeName]) {
      _exchangeCallbacks[exchangeName] = [];
    }
    _exchangeCallbacks[exchangeName].push(callback);
    console.log('[preload] Exchange callback registered for', exchangeName,
      ', total:', _exchangeCallbacks[exchangeName].length);
  },

  // ---- Settings Persistence ----

  /**
   * Load settings from settings.json.
   * @returns {Promise<object>} Settings object (empty if file not found).
   */
  loadSettings: () => {
    return new Promise((resolve) => {
      fs.readFile(_settingsPath, 'utf8', (err, data) => {
        if (err) {
          resolve({});
          return;
        }
        try {
          resolve(JSON.parse(data));
        } catch (parseErr) {
          console.error('[preload] Failed to parse settings.json:', parseErr.message);
          resolve({});
        }
      });
    });
  },

  /**
   * Save settings by merging into existing settings.json.
   * @param {object} settings - Settings key/value pairs to merge.
   * @returns {Promise<void>}
   */
  saveSettings: (settings) => {
    return new Promise((resolve, reject) => {
      // Read existing file first to merge
      fs.readFile(_settingsPath, 'utf8', (readErr, data) => {
        let existing = {};
        if (!readErr && data) {
          try { existing = JSON.parse(data); } catch (e) {}
        }
        const merged = Object.assign({}, existing, settings);
        fs.writeFile(_settingsPath, JSON.stringify(merged, null, 2), 'utf8', (writeErr) => {
          if (writeErr) {
            console.error('[preload] Failed to write settings.json:', writeErr.message);
            reject(writeErr);
            return;
          }
          console.log('[preload] Settings saved:', Object.keys(settings));
          resolve();
        });
      });
    });
  },

  // ---- Bridge Process Management ----

  /**
   * Spawn the FastAPI bridge process.
   * @param {object} options - { pythonPath, bridgeHost, bridgePort, brokerHost, brokerPort }
   * @returns {{ pid: number|null }}
   */
  spawnBridge: (options) => {
    // Check in-memory handle first
    if (_bridgeProcess && !_bridgeProcess.killed) {
      console.log('[preload] Bridge already running (handle), pid:', _bridgeProcess.pid);
      return { pid: _bridgeProcess.pid };
    }
    // Check saved PID from a previous GUI session
    const savedPid = _readSavedPid();
    if (savedPid && _isProcessAlive(savedPid)) {
      console.log('[preload] Bridge already running (saved PID), pid:', savedPid);
      return { pid: savedPid };
    }

    const pythonPath = (options && options.pythonPath) || 'python';
    // launcher.py is a read-only script (from resources in packaged mode)
    const launcherPath = path.join(_pythonSrcPath, 'launcher.py');
    // config.json is writable user data
    const configPath = path.join(_pythonDataPath, 'config.json');
    const args = [launcherPath, '--config', configPath];

    if (options && options.brokerHost) {
      args.push('--broker-host', options.brokerHost);
    }
    if (options && options.brokerPort) {
      args.push('--broker-port', String(options.brokerPort));
    }
    if (options && options.bridgeHost) {
      args.push('--bridge-host', options.bridgeHost);
    }
    if (options && options.bridgePort) {
      args.push('--bridge-port', String(options.bridgePort));
    }

    // Log file for diagnosing spawn failures (writable data dir)
    const logPath = path.join(_pythonDataPath, 'launcher.log');
    const logStream = fs.createWriteStream(logPath, { flags: 'a' });
    const timestamp = new Date().toISOString();
    logStream.write('\n--- Spawn at ' + timestamp + ' ---\n');
    logStream.write('Python: ' + pythonPath + '\n');
    logStream.write('Args: ' + args.join(' ') + '\n');

    console.log('[preload] Spawning bridge:', pythonPath, args.join(' '));
    console.log('[preload] Log file:', logPath);

    _bridgeProcess = child_process.spawn(pythonPath, args, {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      detached: true,   // let the process survive Electron exit
    });

    _bridgeProcess.stdout.on('data', (data) => {
      var line = data.toString().trimEnd();
      console.log('[bridge]', line);
      logStream.write('[stdout] ' + line + '\n');
    });

    _bridgeProcess.stderr.on('data', (data) => {
      var line = data.toString().trimEnd();
      console.error('[bridge]', line);
      logStream.write('[stderr] ' + line + '\n');
    });

    _bridgeProcess.on('close', (code) => {
      console.log('[preload] Bridge process exited with code', code);
      logStream.write('[exit] code ' + code + '\n');
      logStream.end();
      _bridgeProcess = null;
      _removePidFile();
    });

    _bridgeProcess.on('error', (err) => {
      console.error('[preload] Bridge spawn error:', err.message);
      logStream.write('[error] ' + err.message + '\n');
      logStream.end();
      _bridgeProcess = null;
      _removePidFile();
    });

    // Persist PID so a future GUI session can reconnect
    if (_bridgeProcess && _bridgeProcess.pid) {
      _writePid(_bridgeProcess.pid);
    }

    // Allow Electron to exit without waiting for this child process
    _bridgeProcess.unref();

    return { pid: _bridgeProcess ? _bridgeProcess.pid : null };
  },

  /**
   * Kill the running bridge process.
   * @returns {{ killed: boolean }}
   */
  killBridge: () => {
    // Kill via in-memory handle (current session)
    if (_bridgeProcess && !_bridgeProcess.killed) {
      console.log('[preload] Killing bridge process (handle), pid:', _bridgeProcess.pid);
      _bridgeProcess.kill();
      _bridgeProcess = null;
      _removePidFile();
      return { killed: true };
    }
    // Kill via saved PID (previous session)
    const savedPid = _readSavedPid();
    if (savedPid && _isProcessAlive(savedPid)) {
      console.log('[preload] Killing bridge process (saved PID), pid:', savedPid);
      try { process.kill(savedPid); } catch (e) {}
      _removePidFile();
      return { killed: true };
    }
    _removePidFile();
    return { killed: false };
  },

  /**
   * Get the installed version of a Python package.
   * @param {string} [pythonPath='python'] - Path to the Python interpreter.
   * @param {string} [packageName='MicroserviceBase'] - Package name to query.
   * @returns {Promise<string>} Version string or 'unknown'.
   */
  getPackageVersion: (pythonPath, packageName) => {
    return new Promise((resolve) => {
      const py = pythonPath || 'python';
      const pkg = packageName || 'MicroserviceBase';
      const cmd = 'from importlib.metadata import version; print(version("' + pkg + '"))';
      child_process.execFile(py, ['-c', cmd], { timeout: 5000 }, (err, stdout) => {
        if (err) {
          resolve('unknown');
          return;
        }
        resolve(stdout.trim() || 'unknown');
      });
    });
  },

  /**
   * Check if the bridge process is running.
   * @returns {{ running: boolean, pid: number|null }}
   */
  isBridgeRunning: () => {
    // Check in-memory handle (current session)
    if (_bridgeProcess && !_bridgeProcess.killed) {
      return { running: true, pid: _bridgeProcess.pid };
    }
    // Check saved PID (previous session)
    const savedPid = _readSavedPid();
    if (savedPid && _isProcessAlive(savedPid)) {
      return { running: true, pid: savedPid };
    }
    // Stale PID file — clean up
    if (savedPid) _removePidFile();
    return { running: false, pid: null };
  }
});

function _generateUuid() {
  return Math.random().toString() +
    Math.random().toString() +
    Math.random().toString();
}
