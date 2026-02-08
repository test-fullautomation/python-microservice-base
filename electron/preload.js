/**
 * @fileoverview Electron preload script.
 * Exposes a safe bridge API via contextBridge for AMQP and filesystem operations.
 *
 * @version 2.0.0
 */

const { contextBridge, ipcRenderer } = require('electron');

let amqp, fs, os, path, unzipper, child_process;
try {
  amqp = require('amqplib/callback_api');
  fs = require('fs');
  os = require('os');
  path = require('path');
  unzipper = require('unzipper');
  child_process = require('child_process');
  console.log('[preload] All Node.js modules loaded successfully');
} catch (err) {
  console.error('[preload] Failed to load Node.js modules:', err.message);
  console.error('[preload] Make sure you ran "npm install" in the electron/ directory');
}

// Store exchange message callbacks keyed by exchange name
// so messages are only dispatched to the correct subscribers.
const _exchangeCallbacks = {};  // { exchangeName: [callback, ...] }

// Settings file path (persisted alongside electron/)
const _settingsPath = path.join(__dirname, 'settings.json');

// Bridge process management
let _bridgeProcess = null;

// PID file — persists the bridge PID so we can reconnect across GUI sessions
const _pidFilePath = path.join(__dirname, '..', 'python', 'bridge.pid');

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

// Do NOT auto-kill the bridge on Electron exit — let the backend
// (registry + bridge) keep running independently so services stay
// discoverable even after the GUI is closed.

contextBridge.exposeInMainWorld('electronAPI', {

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
      const fullPath = path.join(__dirname, '..', 'web', folderPath);
      fs.access(fullPath, fs.constants.F_OK, (err) => {
        resolve(!err);
      });
    });
  },

  /**
   * Extract a base64-encoded ZIP file to a folder.
   * @param {string} folderPath - Relative path for extraction (under web/).
   * @param {string} base64Data - Base64-encoded ZIP content.
   * @returns {Promise<void>}
   */
  extractGUIZip: (folderPath, base64Data) => {
    return new Promise((resolve, reject) => {
      const fullPath = path.join(__dirname, '..', 'web', folderPath);

      fs.mkdir(fullPath, { recursive: true }, (mkdirErr) => {
        if (mkdirErr) {
          reject(mkdirErr);
          return;
        }

        const decodedBytes = atob(base64Data);
        const bytes = new Uint8Array(decodedBytes.length);
        for (let i = 0; i < decodedBytes.length; i++) {
          bytes[i] = decodedBytes.charCodeAt(i);
        }

        const zipFilePath = path.join(os.tmpdir(), 'mm_gui_' + Date.now() + '.zip');

        fs.writeFile(zipFilePath, Buffer.from(bytes), (writeErr) => {
          if (writeErr) {
            reject(writeErr);
            return;
          }

          fs.createReadStream(zipFilePath)
            .pipe(unzipper.Extract({ path: fullPath }))
            .on('close', () => {
              console.log('All files received and extracted to', fullPath);
              fs.unlink(zipFilePath, (unlinkErr) => {
                if (unlinkErr) {
                  console.error('Error deleting zip file:', unlinkErr);
                }
              });
              resolve();
            })
            .on('error', (extractErr) => {
              fs.unlink(zipFilePath, () => {});
              reject(extractErr);
            });
        });
      });
    });
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
    const launcherPath = path.join(__dirname, '..', 'python', 'launcher.py');
    const configPath = path.join(__dirname, '..', 'python', 'config.json');
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

    // Log file for diagnosing spawn failures
    const logPath = path.join(__dirname, '..', 'python', 'launcher.log');
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
