/**
 * @fileoverview Schema-driven form logic for catalog device settings.
 *
 * Interprets the `user_config_schema` of a catalog entry (JSON Schema,
 * `type: object`) and knows nothing about any device. DOM-free: the view
 * renders what `fields()` describes and calls `evaluate()` to turn what the
 * user typed into typed values plus per-field errors.
 *
 * Supported keywords: type (integer, number, string, boolean; anything else
 * is edited as JSON), default, enum, minimum, maximum, exclusiveMinimum,
 * exclusiveMaximum (draft-4 boolean and draft-6+ numeric forms), required,
 * description, title, minLength, maxLength, pattern.
 *
 * Loads in the browser (MM.schemaForm) and under node (module.exports).
 *
 * @version 1.0.0
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    var MM = root.MicroserviceManager = root.MicroserviceManager || {};
    MM.schemaForm = api;
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function _isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

  function _has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  function _typeOf(spec) {
    var t = spec.type;
    if (Array.isArray(t)) {
      t = t.filter(function (x) { return x !== 'null'; })[0];
    }
    if (t === 'integer' || t === 'number' || t === 'string' || t === 'boolean') return t;
    if (!t && Array.isArray(spec.enum) && spec.enum.length) {
      var e = typeof spec.enum[0];
      if (e === 'number') return 'number';
      if (e === 'string') return 'string';
      if (e === 'boolean') return 'boolean';
    }
    return 'json';   // object / array / untyped: edited as JSON text
  }

  /** Lower bound as {value, exclusive} or null. */
  function _lower(spec) {
    var ex = spec.exclusiveMinimum;
    if (typeof ex === 'number') return { value: ex, exclusive: true };
    if (typeof spec.minimum === 'number') {
      return { value: spec.minimum, exclusive: ex === true };
    }
    return null;
  }

  function _upper(spec) {
    var ex = spec.exclusiveMaximum;
    if (typeof ex === 'number') return { value: ex, exclusive: true };
    if (typeof spec.maximum === 'number') {
      return { value: spec.maximum, exclusive: ex === true };
    }
    return null;
  }

  /**
   * Describe the editable fields of a schema, in property order.
   *
   * @param {object|null|undefined} schema
   * @returns {Array<object>} {name, label, type, description, hasDefault,
   *   default, enum, min, max, required, minLength, maxLength, pattern}
   */
  function fields(schema) {
    if (!_isObj(schema) || !_isObj(schema.properties)) return [];
    var required = Array.isArray(schema.required) ? schema.required : [];
    return Object.keys(schema.properties).map(function (name) {
      var spec = _isObj(schema.properties[name]) ? schema.properties[name] : {};
      return {
        name: name,
        label: typeof spec.title === 'string' && spec.title ? spec.title : name,
        type: _typeOf(spec),
        description: typeof spec.description === 'string' ? spec.description : '',
        hasDefault: _has(spec, 'default'),
        default: spec.default,
        enum: Array.isArray(spec.enum) ? spec.enum.slice() : null,
        min: _lower(spec),
        max: _upper(spec),
        required: required.indexOf(name) !== -1,
        minLength: typeof spec.minLength === 'number' ? spec.minLength : null,
        maxLength: typeof spec.maxLength === 'number' ? spec.maxLength : null,
        pattern: typeof spec.pattern === 'string' ? spec.pattern : null
      };
    });
  }

  /** The values a new device starts with: every schema `default`. */
  function defaults(schema) {
    var out = {};
    fields(schema).forEach(function (f) {
      if (f.hasDefault) out[f.name] = JSON.parse(JSON.stringify(f.default));
    });
    return out;
  }

  /** Value -> what an input shows (strings for text-like inputs). */
  function toRaw(field, value) {
    if (value === undefined || value === null) return field.type === 'boolean' ? undefined : '';
    if (field.type === 'json') return JSON.stringify(value);
    if (field.type === 'boolean') return !!value;
    if (field.enum) return value;
    return String(value);
  }

  function _fmtBound(b, isMin) {
    return (isMin ? (b.exclusive ? '> ' : '≥ ') : (b.exclusive ? '< ' : '≤ ')) + b.value;
  }

  function _sameEnum(a, b) {
    return a === b || JSON.stringify(a) === JSON.stringify(b);
  }

  /**
   * Check one typed value against a field.
   * @returns {string|null} The reason it is wrong, or null.
   */
  function checkValue(field, value) {
    if (field.enum) {
      var ok = field.enum.some(function (e) { return _sameEnum(e, value); });
      if (!ok) {
        return 'must be one of ' + field.enum.map(function (e) { return JSON.stringify(e); }).join(', ');
      }
    }
    if (field.type === 'integer' || field.type === 'number') {
      if (typeof value !== 'number' || !isFinite(value)) return 'must be a number';
      if (field.type === 'integer' && Math.floor(value) !== value) return 'must be an integer';
      if (field.min && (field.min.exclusive ? value <= field.min.value : value < field.min.value)) {
        return 'must be ' + _fmtBound(field.min, true);
      }
      if (field.max && (field.max.exclusive ? value >= field.max.value : value > field.max.value)) {
        return 'must be ' + _fmtBound(field.max, false);
      }
    } else if (field.type === 'string') {
      if (typeof value !== 'string') return 'must be text';
      if (field.minLength !== null && value.length < field.minLength) {
        return 'must be at least ' + field.minLength + ' characters';
      }
      if (field.maxLength !== null && value.length > field.maxLength) {
        return 'must be at most ' + field.maxLength + ' characters';
      }
      if (field.pattern) {
        var re = null;
        try { re = new RegExp(field.pattern); } catch (e) { re = null; }
        if (re && !re.test(value)) return 'must match ' + field.pattern;
      }
    } else if (field.type === 'boolean') {
      if (typeof value !== 'boolean') return 'must be true or false';
    }
    return null;
  }

  function _empty(raw) {
    return raw === undefined || raw === null || (typeof raw === 'string' && raw.trim() === '');
  }

  /** One raw input -> {value} | {missing: true} | {error}. */
  function parseRaw(field, raw) {
    if (field.type === 'boolean') {
      if (raw === undefined || raw === null || raw === '') return { missing: true };
      if (raw === true || raw === 'true') return { value: true };
      if (raw === false || raw === 'false') return { value: false };
      return { error: 'must be true or false' };
    }
    if (field.enum && typeof raw !== 'string') {
      return raw === undefined || raw === null ? { missing: true } : { value: raw };
    }
    if (_empty(raw)) return { missing: true };
    if (field.type === 'integer' || field.type === 'number') {
      if (typeof raw === 'number') return { value: raw };
      var n = Number(String(raw).trim());
      if (!isFinite(n)) return { error: 'must be ' + (field.type === 'integer' ? 'an integer' : 'a number') };
      return { value: n };
    }
    if (field.type === 'json') {
      try { return { value: typeof raw === 'string' ? JSON.parse(raw) : raw }; }
      catch (e) { return { error: 'must be valid JSON' }; }
    }
    if (field.enum) {
      // A select posts text; map it back to the enum member it stands for.
      for (var i = 0; i < field.enum.length; i++) {
        if (String(field.enum[i]) === raw) return { value: field.enum[i] };
      }
      return { value: raw };
    }
    return { value: raw };
  }

  /**
   * Turn raw form input into typed values and errors.
   *
   * Keys the schema does not describe are carried over untouched, so a
   * saved device whose catalog entry changed keeps what it had.
   *
   * @param {object|null} schema
   * @param {object} raw  name -> raw input (string, boolean or typed value)
   * @returns {{values: object, errors: Object<string,string>}}
   */
  function evaluate(schema, raw) {
    raw = raw || {};
    var fs = fields(schema);
    var known = {};
    var values = {};
    var errors = {};
    fs.forEach(function (f) {
      known[f.name] = true;
      var p = parseRaw(f, raw[f.name]);
      if (p.error) { errors[f.name] = p.error; return; }
      if (p.missing) {
        if (f.required) errors[f.name] = 'is required';
        return;
      }
      var bad = checkValue(f, p.value);
      if (bad) { errors[f.name] = bad; return; }
      values[f.name] = p.value;
    });
    // Required names the schema lists without describing them.
    if (_isObj(schema) && Array.isArray(schema.required)) {
      schema.required.forEach(function (name) {
        if (!known[name] && _empty(raw[name])) errors[name] = 'is required';
      });
    }
    Object.keys(raw).forEach(function (k) {
      if (!known[k] && raw[k] !== undefined) values[k] = raw[k];
    });
    return { values: values, errors: errors };
  }

  return {
    fields: fields,
    defaults: defaults,
    toRaw: toRaw,
    parseRaw: parseRaw,
    checkValue: checkValue,
    evaluate: evaluate
  };
});
