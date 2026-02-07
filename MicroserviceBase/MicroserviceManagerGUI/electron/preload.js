/**
 * @fileoverview Electron preload script.
 * Exposes a safe bridge API via contextBridge for AMQP and filesystem operations.
 *
 * @version 2.0.0
 */

const { contextBridge, ipcRenderer } = require('electron');

let amqp, fs, os, path, unzipper;
try {
  amqp = require('amqplib/callback_api');
  fs = require('fs');
  os = require('os');
  path = require('path');
  unzipper = require('unzipper');
  console.log('[preload] All Node.js modules loaded successfully');
} catch (err) {
  console.error('[preload] Failed to load Node.js modules:', err.message);
  console.error('[preload] Make sure you ran "npm install" in the electron/ directory');
}

// Store exchange message callbacks keyed by exchange name
// so messages are only dispatched to the correct subscribers.
const _exchangeCallbacks = {};  // { exchangeName: [callback, ...] }

contextBridge.exposeInMainWorld('electronAPI', {

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
    return new Promise((resolve, reject) => {
      amqp.connect(`amqp://${brokerUrl}`, (error0, connection) => {
        if (error0) {
          reject(error0);
          return;
        }

        connection.createChannel((error1, channel) => {
          if (error1) {
            reject(error1);
            return;
          }

          channel.assertQueue('', { exclusive: true }, (error2, q) => {
            if (error2) {
              reject(error2);
              return;
            }

            const correlationId = _generateUuid();
            console.log(' [x] Requesting Service with data:', requestData);

            channel.consume(q.queue, (msg) => {
              if (msg.properties.correlationId == correlationId) {
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
    return new Promise((resolve, reject) => {
      amqp.connect(`amqp://${brokerUrl}`, (error0, connection) => {
        if (error0) {
          reject(error0);
          return;
        }

        connection.createChannel((error1, channel) => {
          if (error1) {
            reject(error1);
            return;
          }

          channel.assertQueue('', { exclusive: true }, (error2, q) => {
            if (error2) {
              reject(error2);
              return;
            }

            const correlationId = _generateUuid();
            console.log(' [x] Requesting Service Direct with data:', requestData);

            channel.consume(q.queue, (msg) => {
              if (msg.properties.correlationId == correlationId) {
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
  }
});

function _generateUuid() {
  return Math.random().toString() +
    Math.random().toString() +
    Math.random().toString();
}
