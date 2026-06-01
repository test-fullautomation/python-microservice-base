/**
 * @fileoverview Unified transport client supporting AMQP (backward compat)
 * and FastAPI REST (preferred) modes. Replaces per-request amqp.connect() calls
 * and per-module hardcoded connections with a single shared client.
 *
 * @version 1.0.0
 */

const { ServiceRequest, ServiceResponse } = require('./MessageProtocol');

/**
 * Unified service client supporting AMQP and FastAPI REST transport modes.
 */
class ServiceClient {
  /**
   * @param {object} options - Configuration options.
   * @param {string} [options.mode='amqp'] - Transport mode: 'amqp' or 'fastapi'.
   * @param {string} [options.brokerUrl='localhost:5672'] - AMQP broker URL (host:port).
   * @param {string} [options.apiUrl='http://localhost:8000'] - FastAPI bridge base URL.
   */
  constructor(options = {}) {
    this.mode = options.mode || 'amqp';
    this.brokerUrl = options.brokerUrl || 'localhost:5672';
    this.apiUrl = options.apiUrl || 'http://localhost:8000';
    this._ws = null;
    this._wsReady = false;
    this._updateCallbacks = [];
  }

  /**
   * Update the broker URL for AMQP mode.
   * @param {string} brokerUrl - New broker URL (host:port).
   */
  setBrokerUrl(brokerUrl) {
    this.brokerUrl = brokerUrl;
  }

  /**
   * Set the FastAPI bridge base URL.
   * @param {string} apiUrl - Base URL (e.g. 'http://localhost:8000').
   */
  setApiUrl(apiUrl) {
    this.apiUrl = apiUrl;
  }

  /**
   * Connect to the FastAPI WebSocket endpoint for real-time updates.
   * Only needed in fastapi mode when you want push updates.
   * @returns {Promise<void>}
   */
  connectUpdates() {
    return new Promise((resolve, reject) => {
      if (this.mode !== 'fastapi') {
        resolve();
        return;
      }

      const wsUrl = this.apiUrl.replace(/^http/, 'ws') + '/ws/updates';

      try {
        this._ws = new WebSocket(wsUrl);
      } catch (e) {
        reject(new Error(`Failed to connect to update stream: ${e.message}`));
        return;
      }

      this._ws.onopen = () => {
        this._wsReady = true;
        console.log(' [x] Connected to FastAPI update stream at', wsUrl);
        resolve();
      };

      this._ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.action === 'services_update') {
            this._updateCallbacks.forEach(cb => cb(message.data));
          }
        } catch (e) {
          console.error('Error parsing update message:', e);
        }
      };

      this._ws.onerror = (error) => {
        console.error('Update stream error:', error);
        reject(error);
      };

      this._ws.onclose = () => {
        this._wsReady = false;
        console.log(' [x] Update stream disconnected');
      };
    });
  }

  /**
   * Disconnect from the transport.
   */
  disconnect() {
    if (this._ws) {
      this._ws.close();
      this._ws = null;
      this._wsReady = false;
    }
  }

  /**
   * Send a service request and return a Promise with the response.
   *
   * @param {object} requestData - Request data with 'method' and 'args' keys.
   * @param {string} exchangeName - The exchange name (used in AMQP mode).
   * @param {string} routingKey - The routing key for the target service.
   * @returns {Promise<object>} Response data from the service.
   */
  requestService(requestData, exchangeName, routingKey) {
    if (this.mode === 'fastapi') {
      return this._requestViaFastAPI(requestData, exchangeName, routingKey);
    }
    return this._requestViaAMQP(requestData, exchangeName, routingKey);
  }

  /**
   * Send a direct request to a specific service queue.
   *
   * @param {object} requestData - Request data with 'method' and 'args' keys.
   * @param {string} queueName - The target queue name (service name).
   * @returns {Promise<object>} Response data from the service.
   */
  requestServiceDirect(requestData, queueName) {
    if (this.mode === 'fastapi') {
      return this._requestViaFastAPI(requestData, 'services_request', queueName);
    }
    return this._requestDirectViaAMQP(requestData, queueName);
  }

  /**
   * Subscribe to real-time services update events.
   * @param {Function} callback - Called with services info dict on each update.
   */
  onServicesUpdate(callback) {
    this._updateCallbacks.push(callback);
  }

  /**
   * Send request via FastAPI REST endpoint.
   * @private
   */
  _requestViaFastAPI(requestData, exchangeName, routingKey) {
    const url = `${this.apiUrl}/api/request`;
    const body = {
      method: requestData.method,
      args: requestData.args || null,
      exchange: exchangeName,
      routing_key: routingKey,
    };

    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(response => {
        if (!response.ok) {
          throw new Error(`FastAPI bridge returned ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        console.log(' [.] Got response:', data);
        return data;
      });
  }

  /**
   * Send request via AMQP using exchange and routing key.
   * @private
   */
  _requestViaAMQP(requestData, exchangeName, routingKey) {
    const amqp = require('amqplib/callback_api');

    return new Promise((resolve, reject) => {
      amqp.connect(`amqp://${this.brokerUrl}`, function (error0, connection) {
        if (error0) {
          reject(error0);
          return;
        }

        connection.createChannel(function (error1, channel) {
          if (error1) {
            reject(error1);
            return;
          }

          channel.assertQueue('', { exclusive: true }, function (error2, q) {
            if (error2) {
              reject(error2);
              return;
            }

            var correlationId = _generateUuid();

            console.log(' [x] Requesting Service with data:', requestData);

            channel.consume(q.queue, function (msg) {
              if (msg.properties.correlationId == correlationId) {
                const result = JSON.parse(msg.content.toString());
                console.log(' [.] Got response:', result);
                resolve(result);
                setTimeout(function () {
                  connection.close();
                }, 500);
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
  }

  /**
   * Send direct request via AMQP to a specific queue.
   * @private
   */
  _requestDirectViaAMQP(requestData, queueName) {
    const amqp = require('amqplib/callback_api');

    return new Promise((resolve, reject) => {
      amqp.connect(`amqp://${this.brokerUrl}`, function (error0, connection) {
        if (error0) {
          reject(error0);
          return;
        }

        connection.createChannel(function (error1, channel) {
          if (error1) {
            reject(error1);
            return;
          }

          channel.assertQueue('', { exclusive: true }, function (error2, q) {
            if (error2) {
              reject(error2);
              return;
            }

            var correlationId = _generateUuid();

            console.log(' [x] Requesting Service with data:', requestData);

            channel.consume(q.queue, function (msg) {
              if (msg.properties.correlationId == correlationId) {
                const result = JSON.parse(msg.content.toString());
                console.log(' [.] Got response:', result);
                resolve(result);
                setTimeout(function () {
                  connection.close();
                }, 500);
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
  }

  /**
   * Subscribe to a fanout exchange for real-time updates.
   *
   * In fastapi mode, fetches services via GET /api/services and polls,
   * or connects to the /ws/updates WebSocket for push updates.
   * In amqp mode, subscribes directly to the RabbitMQ fanout exchange.
   *
   * @param {string} exchangeName - The fanout exchange to subscribe to.
   * @param {Function} callback - Called with parsed message data on each update.
   */
  subscribeToExchange(exchangeName, callback) {
    if (this.mode === 'fastapi') {
      this.onServicesUpdate(callback);
      return;
    }

    const amqp = require('amqplib/callback_api');

    amqp.connect(`amqp://${this.brokerUrl}`, function (error0, connection) {
      if (error0) {
        throw error0;
      }
      connection.createChannel(function (error1, channel) {
        if (error1) {
          throw error1;
        }

        channel.assertExchange(exchangeName, 'fanout', { durable: false });

        channel.assertQueue('', { exclusive: true }, function (error2, q) {
          if (error2) {
            throw error2;
          }
          console.log(' [*] Waiting for messages in %s. To exit press CTRL+C', q.queue);
          channel.bindQueue(q.queue, exchangeName, '');

          channel.consume(q.queue, function (msg) {
            if (msg.content) {
              console.log(' [x] %s', msg.content.toString());
              const result = JSON.parse(msg.content.toString());
              callback(result);
            }
          }, { noAck: true });
        });
      });
    });
  }
}

/**
 * Generate a UUID string.
 * @returns {string}
 * @private
 */
function _generateUuid() {
  return Math.random().toString() +
    Math.random().toString() +
    Math.random().toString();
}

// Singleton instance for shared usage across the application
const sharedClient = new ServiceClient();

module.exports = {
  ServiceClient,
  sharedClient,
};
