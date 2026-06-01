/**
 * @fileoverview SchemaAutoGen — auto-generate a gui_schema from methods_info metadata.
 *
 * Generates a schema suitable for SchemaRenderer from the service's registered
 * method information, providing a reasonable default GUI without any hand-written
 * schema file.
 *
 * Usage:
 *   var schema = SchemaAutoGen.fromMethodsInfo(serviceName, serviceInfo);
 *   SchemaRenderer.render(schema, containerEl, serviceName);
 *
 * Exposed as window.SchemaAutoGen.
 */

(function () {
  'use strict';

  /* ================================================================
   *  Type → widget mapping
   * ================================================================ */

  var TYPE_WIDGET_MAP = {
    'int':    'number',
    'float':  'number',
    'double': 'number',
    'number': 'number',
    'bool':   'checkbox',
    'boolean':'checkbox',
    'str':    'text',
    'string': 'text',
    'list':   'textarea',
    'dict':   'textarea',
    'json':   'textarea',
    'file':   'file',
    'bytes':  'file'
  };

  /* ================================================================
   *  Public API
   * ================================================================ */

  var SchemaAutoGen = {
    /**
     * Generate a gui_schema.json-compatible object from service metadata.
     *
     * @param {string} serviceName  - Service name key.
     * @param {Object} serviceInfo  - MM.servicesInfor[serviceName] object with
     *                                .methods, .methods_info, .version, .description, etc.
     * @returns {Object} A schema descriptor for SchemaRenderer.
     */
    fromMethodsInfo: function (serviceName, serviceInfo) {
      var methods = serviceInfo.methods || [];
      var methodsInfo = serviceInfo.methods_info || {};

      var sections = [];

      methods.forEach(function (methodName) {
        var mInfo = methodsInfo[methodName];
        var fields = [];

        if (mInfo && mInfo.arguments && mInfo.arguments.length > 0) {
          mInfo.arguments.forEach(function (arg) {
            var field = _argToField(arg);
            fields.push(field);
          });
        }

        // Derive a friendly label from the method name
        var label = _methodToLabel(methodName);

        sections.push({
          id: methodName,
          label: label,
          components: [
            {
              type: 'method-form',
              method: methodName,
              fields: fields,
              submit_label: 'Execute',
              result_display: _guessResultDisplay(mInfo)
            }
          ]
        });
      });

      var layout = sections.length > 1 ? 'tabs' : 'single';

      return {
        '$schema': 'microservice-gui/1.0',
        service: serviceName,
        layout: layout,
        title: serviceInfo.name || serviceName,
        subtitle: serviceInfo.description || serviceInfo.shortdesc || '',
        sections: sections
      };
    }
  };

  /* ================================================================
   *  Internal helpers
   * ================================================================ */

  /**
   * Convert a methods_info argument descriptor to a schema field descriptor.
   */
  function _argToField(arg) {
    var type = (arg.type || 'str').toLowerCase();
    var widget = TYPE_WIDGET_MAP[type] || 'text';

    // Long text heuristic: if type is str and name contains 'body', 'content', 'text', 'json'
    if (widget === 'text' && arg.name) {
      var n = arg.name.toLowerCase();
      if (n.indexOf('body') >= 0 || n.indexOf('content') >= 0 ||
          n.indexOf('text') >= 0 || n.indexOf('json') >= 0 ||
          n.indexOf('data') >= 0 || n.indexOf('payload') >= 0) {
        widget = 'textarea';
      }
    }

    var field = {
      arg: arg.name || 'arg',
      label: _argNameToLabel(arg.name || 'arg'),
      widget: widget
    };

    if (arg.description) {
      field.description = arg.description;
      field.placeholder = arg.description;
    }

    if (arg.default != null) {
      field.default = arg.default;
    }

    if (arg.condition === 'required') {
      field.required = true;
    }

    // Enum / choices support
    if (arg.choices && Array.isArray(arg.choices)) {
      field.widget = 'select';
      field.options = arg.choices;
    }

    return field;
  }

  /**
   * Convert a method name like "svc_api_hello_world" to "Hello World".
   */
  function _methodToLabel(methodName) {
    // Strip common prefixes
    var name = methodName
      .replace(/^svc_api_/, '')
      .replace(/^api_/, '')
      .replace(/^svc_/, '');

    // snake_case to Title Case
    return name
      .split('_')
      .map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); })
      .join(' ');
  }

  /**
   * Convert "my_arg_name" to "My Arg Name".
   */
  function _argNameToLabel(name) {
    return name
      .split('_')
      .map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); })
      .join(' ');
  }

  /**
   * Guess the best result_display mode from method info.
   */
  function _guessResultDisplay(mInfo) {
    if (!mInfo) return 'json';

    var returnType = (mInfo.return_type || '').toLowerCase();
    if (returnType === 'dict' || returnType === 'list') return 'table';
    if (returnType === 'image' || returnType === 'bytes') return 'image';
    if (returnType === 'str' || returnType === 'string') return 'text';

    // Default to JSON for structured data visibility
    return 'json';
  }

  /* ================================================================
   *  Expose
   * ================================================================ */

  window.SchemaAutoGen = SchemaAutoGen;

})();
