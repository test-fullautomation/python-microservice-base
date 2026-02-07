/**
 * @fileoverview JavaScript mirrors of the Python domain message models.
 * Provides ServiceRequest and ServiceResponse classes for structured communication.
 * Browser-compatible version - no require/module.exports.
 *
 * @version 2.0.0
 */

/**
 * Structured request to a service method.
 * Mirrors Python domain.messages.ServiceRequest.
 */
class ServiceRequest {
  /**
   * @param {string} method - The service method name to call.
   * @param {Array|null} args - Arguments for the method.
   */
  constructor(method, args = null) {
    this.method = method;
    this.args = args;
  }

  toDict() {
    return {
      method: this.method,
      args: this.args,
    };
  }

  toJSON() {
    return JSON.stringify(this.toDict());
  }

  static fromDict(data) {
    return new ServiceRequest(data.method || '', data.args || null);
  }

  static fromJSON(jsonStr) {
    return ServiceRequest.fromDict(JSON.parse(jsonStr));
  }
}

/**
 * Result type constants matching Python domain.messages.ResultType.
 */
const ResultType = {
  PASS: 'pass',
  FAIL: 'fail',
  EXCEPT: 'exception',
};

/**
 * Structured response from a service method.
 * Mirrors Python domain.messages.ServiceResponse.
 */
class ServiceResponse {
  /**
   * @param {string} request - The original request method name.
   * @param {string} result - The result type (pass/fail/exception).
   * @param {*} resultData - The response data.
   */
  constructor(request = '', result = ResultType.PASS, resultData = '') {
    this.request = request;
    this.result = result;
    this.result_data = resultData;
  }

  toDict() {
    return {
      request: this.request,
      result: this.result,
      result_data: this.result_data,
    };
  }

  toJSON() {
    return JSON.stringify(this.toDict());
  }

  static fromDict(data) {
    return new ServiceResponse(
      data.request || '',
      data.result || ResultType.PASS,
      data.result_data || ''
    );
  }

  static fromJSON(jsonStr) {
    return ServiceResponse.fromDict(JSON.parse(jsonStr));
  }
}

/**
 * Service event for registration/unregistration.
 * Mirrors Python domain.messages.ServiceEvent.
 */
class ServiceEvent {
  /**
   * @param {string} serviceName - Name of the service.
   * @param {string} state - State: 'on' or 'off'.
   * @param {object} info - Service metadata dict.
   */
  constructor(serviceName = '', state = '', info = {}) {
    this.serviceName = serviceName;
    this.state = state;
    this.info = info;
  }

  toDict() {
    return {
      info: this.info,
      state: this.state,
    };
  }

  static fromDict(data) {
    const info = data.info || {};
    return new ServiceEvent(
      info.name || '',
      data.state || '',
      info
    );
  }
}

// Expose on global namespace
window.MicroserviceManager = window.MicroserviceManager || {};
Object.assign(window.MicroserviceManager, {
  ServiceRequest,
  ServiceResponse,
  ServiceEvent,
  ResultType,
});
