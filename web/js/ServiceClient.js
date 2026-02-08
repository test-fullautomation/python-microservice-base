/**
 * @fileoverview Unified transport client supporting dual hosting:
 * - Electron mode: delegates AMQP calls to window.electronAPI (preload bridge)
 * - Browser mode: uses fetch() and WebSocket via FastAPI bridge
 *
 * No Node.js dependencies. Browser-compatible.
 *
 * @version 2.0.0
 */

(function () {
  'use strict';

  /**
   * Detect if running inside Electron with the preload bridge available.
   * @returns {boolean}
   */
  function isElectron() {
    return typeof window !== 'undefined' && !!window.electronAPI;
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

  /**
   * Unified service client supporting AMQP (via Electron preload) and FastAPI REST transport.
   */
  class ServiceClient {
    /**
     * @param {object} options - Configuration options.
     * @param {string} [options.brokerUrl='localhost:5672'] - AMQP broker URL (host:port).
     * @param {string} [options.apiUrl='http://localhost:8000'] - FastAPI bridge base URL.
     */
    constructor(options = {}) {
      this.brokerUrl = options.brokerUrl || 'localhost:5672';
      this.apiUrl = options.apiUrl || window.location.origin;
      this._ws = null;
      this._wsReady = false;
      this._updateCallbacks = [];
    }

    /**
     * Determine current transport mode based on environment.
     * @returns {string} 'electron' or 'fastapi'
     */
    get mode() {
      return isElectron() ? 'electron' : 'fastapi';
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
     * Only used in browser (FastAPI) mode.
     * @returns {Promise<void>}
     */
    connectUpdates() {
      return new Promise((resolve, reject) => {
        if (this.mode === 'electron') {
          resolve();
          return;
        }

        const wsUrl = this.apiUrl.replace(/^http/, 'ws') + '/ws/updates';

        try {
          this._ws = new WebSocket(wsUrl);
        } catch (e) {
          reject(new Error('Failed to connect to update stream: ' + e.message));
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
      if (this.mode === 'electron') {
        return window.electronAPI.amqpRequest(requestData, exchangeName, routingKey, this.brokerUrl);
      }
      return this._requestViaFastAPI(requestData, exchangeName, routingKey);
    }

    /**
     * Send a direct request to a specific service queue.
     *
     * @param {object} requestData - Request data with 'method' and 'args' keys.
     * @param {string} queueName - The target queue name (service name).
     * @returns {Promise<object>} Response data from the service.
     */
    requestServiceDirect(requestData, queueName) {
      if (this.mode === 'electron') {
        return window.electronAPI.amqpRequestDirect(requestData, queueName, this.brokerUrl);
      }
      return this._requestViaFastAPI(requestData, 'services_request', queueName);
    }

    /**
     * Subscribe to real-time services update events.
     * @param {Function} callback - Called with services info dict on each update.
     */
    onServicesUpdate(callback) {
      this._updateCallbacks.push(callback);
    }

    /**
     * Subscribe to a fanout exchange for real-time updates.
     *
     * @param {string} exchangeName - The fanout exchange to subscribe to.
     * @param {Function} callback - Called with parsed message data on each update.
     */
    subscribeToExchange(exchangeName, callback) {
      if (this.mode === 'electron') {
        window.electronAPI.amqpSubscribe(exchangeName, this.brokerUrl);
        window.electronAPI.onExchangeMessage(exchangeName, callback);
        return;
      }

      // In browser mode, use WebSocket updates
      this.onServicesUpdate(callback);
      if (!this._wsReady && !this._ws) {
        this.connectUpdates().catch(function (err) {
          console.error('[ServiceClient] Failed to connect WebSocket updates:', err);
        });
      }
    }

    /**
     * Send request via FastAPI REST endpoint.
     * @private
     */
    _requestViaFastAPI(requestData, exchangeName, routingKey) {
      const url = this.apiUrl + '/api/request';
      const body = {
        method: requestData.method,
        args: requestData.args || null,
        exchange: exchangeName,
        routing_key: routingKey,
        broker_url: this.brokerUrl,
      };

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);

      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
        .then(response => {
          clearTimeout(timeoutId);
          if (!response.ok) {
            throw new Error('FastAPI bridge returned ' + response.status);
          }
          return response.json();
        })
        .then(data => {
          console.log(' [.] Got response:', data);
          return data;
        })
        .catch(err => {
          clearTimeout(timeoutId);
          if (err.name === 'AbortError') {
            throw new Error('Request timeout: no response after 15s (is the target service running?)');
          }
          throw err;
        });
    }
  }

  // Expose on global namespace
  window.MicroserviceManager = window.MicroserviceManager || {};
  window.MicroserviceManager.ServiceClient = ServiceClient;
  window.MicroserviceManager.serviceClient = new ServiceClient();

})();
