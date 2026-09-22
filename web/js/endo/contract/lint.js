/**
 * @fileoverview Bench Endoskeleton contract v1: schema validation and the
 * component rules (R1, R2, R3, R7, R8, R9) as code.
 *
 * One file for both places that must agree: the GUI (a browser global,
 * EndoContract) and CI (a Node module used by tools/endo-lint.js and the
 * tests). The JSON Schemas are passed in by the caller: Node reads the .json
 * files, the GUI fetches them.
 *
 * An issue is { rule, severity: 'error' | 'warn', component, path, message }.
 * The shell refuses a component with any error.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.EndoContract = api;
    if (root.MicroserviceManager) {
      root.MicroserviceManager.endo = root.MicroserviceManager.endo || {};
      root.MicroserviceManager.endo.contract = api;
    }
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Shell API version. Minor bumps for additive contract changes. */
  var SHELL_VERSION = '2.3.0';

  var LAYERS = ['operator', 'session', 'config', 'execution', 'runner', 'signals', 'bits'];

  var CAPABILITIES = ['grpc.call', 'signals.subscribe', 'signals.set', 'session.read',
                      'session.label', 'config.read', 'config.write', 'files.project',
                      'process.spawn'];

  /** Tile sizes on the 4-column stage: [columns, rows]. */
  var SIZES = { '1x1': [1, 1], '2x1': [2, 1], '2x2': [2, 2], '4x1': [4, 1] };

  var CORE_KINDS = ['text', 'live-status', 'command-form', 'table', 'log', 'run-status', 'frame'];

  /** Reserved binds.consul value: the service that declared this component. */
  var SELF = '@self';

  // ------------------------------------------------------------------
  // Minimal JSON Schema (draft-07 subset used by our schemas)
  // ------------------------------------------------------------------

  function typeOf(v) {
    if (v === null) return 'null';
    if (Array.isArray(v)) return 'array';
    if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'number';
    return typeof v;
  }

  function typeMatches(want, v) {
    var got = typeOf(v);
    if (want === 'number') return got === 'number' || got === 'integer';
    return want === got;
  }

  function resolveRef(rootSchema, ref) {
    if (ref.indexOf('#/') !== 0) throw new Error('Unsupported $ref ' + ref);
    return ref.slice(2).split('/').reduce(function (node, key) {
      if (!node || !(key in node)) throw new Error('Unresolved $ref ' + ref);
      return node[key];
    }, rootSchema);
  }

  function joinPath(base, key) {
    if (typeof key === 'number') return base + '[' + key + ']';
    return base ? base + '.' + key : key;
  }

  /**
   * Validate `value` against `schema`. Returns [{ path, message }].
   * @param {object} schema
   * @param {*} value
   * @param {object} [rootSchema] - resolves $ref; defaults to schema
   */
  function validateSchema(schema, value, rootSchema, path) {
    rootSchema = rootSchema || schema;
    path = path || '';
    var errs = [];
    if (schema.$ref) return validateSchema(resolveRef(rootSchema, schema.$ref), value, rootSchema, path);

    if (schema.type) {
      var types = Array.isArray(schema.type) ? schema.type : [schema.type];
      if (!types.some(function (t) { return typeMatches(t, value); })) {
        errs.push({ path: path || '(root)', message: 'must be ' + types.join(' or ') + ', not ' + typeOf(value) });
        return errs;
      }
    }
    if (schema.enum && schema.enum.indexOf(value) < 0) {
      errs.push({ path: path || '(root)', message: 'must be one of ' + schema.enum.join(', ') });
    }
    if (typeof value === 'string') {
      if (schema.minLength != null && value.length < schema.minLength) {
        errs.push({ path: path, message: 'must not be empty' });
      }
      if (schema.pattern && !new RegExp(schema.pattern).test(value)) {
        errs.push({ path: path, message: '"' + value + '" does not match ' + schema.pattern });
      }
    }
    if (typeof value === 'number' && schema.minimum != null && value < schema.minimum) {
      errs.push({ path: path, message: 'must be >= ' + schema.minimum });
    }
    if (Array.isArray(value)) {
      if (schema.minItems != null && value.length < schema.minItems) {
        errs.push({ path: path, message: 'needs at least ' + schema.minItems + ' item(s)' });
      }
      if (schema.maxItems != null && value.length > schema.maxItems) {
        errs.push({ path: path, message: 'allows at most ' + schema.maxItems + ' item(s)' });
      }
      if (schema.items) {
        value.forEach(function (item, i) {
          errs = errs.concat(validateSchema(schema.items, item, rootSchema, joinPath(path, i)));
        });
      }
    }
    if (typeOf(value) === 'object') {
      (schema.required || []).forEach(function (k) {
        if (!(k in value)) errs.push({ path: joinPath(path, k), message: 'is required' });
      });
      var props = schema.properties || {};
      Object.keys(value).forEach(function (k) {
        if (props[k]) {
          errs = errs.concat(validateSchema(props[k], value[k], rootSchema, joinPath(path, k)));
        } else if (schema.additionalProperties === false) {
          errs.push({ path: joinPath(path, k), message: 'is not a known field' });
        } else if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
          errs = errs.concat(validateSchema(schema.additionalProperties, value[k], rootSchema, joinPath(path, k)));
        }
      });
    }
    if (schema.anyOf) {
      var ok = schema.anyOf.some(function (s) { return validateSchema(s, value, rootSchema, path).length === 0; });
      if (!ok) {
        var alts = schema.anyOf.map(function (s) {
          return s.required ? s.required.join(' + ') : (s.type || s.enum || 'alternative');
        });
        errs.push({ path: path || '(root)', message: 'needs one of: ' + alts.join(' | ') });
      }
    }
    return errs;
  }

  // ------------------------------------------------------------------
  // Semver ranges (the subset R9 needs)
  // ------------------------------------------------------------------

  function parseVersion(v) {
    var m = /^(\d+)\.(\d+)(?:\.(\d+))?/.exec(String(v || '').trim());
    return m ? [Number(m[1]), Number(m[2]), Number(m[3] || 0)] : null;
  }

  function cmp(a, b) {
    for (var i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
    return 0;
  }

  /**
   * Does `version` satisfy `range`? Supports ^x.y[.z], ~x.y[.z], >=x.y[.z]
   * and exact x.y.z. Returns null for a range it cannot read.
   */
  function satisfies(range, version) {
    var v = parseVersion(version);
    var r = String(range || '').trim();
    var op = r.charAt(0) === '^' ? '^' : r.charAt(0) === '~' ? '~' : r.indexOf('>=') === 0 ? '>=' : '=';
    var base = parseVersion(op === '=' ? r : r.slice(op.length));
    if (!v || !base) return null;
    if (cmp(v, base) < 0) return false;
    if (op === '>=') return true;
    if (op === '=') return cmp(v, base) === 0;
    if (op === '~') return v[0] === base[0] && v[1] === base[1];
    // caret: same left-most non-zero component
    if (base[0] > 0) return v[0] === base[0];
    if (base[1] > 0) return v[0] === 0 && v[1] === base[1];
    return v[0] === 0 && v[1] === 0 && v[2] === base[2];
  }

  // ------------------------------------------------------------------
  // Component rules
  // ------------------------------------------------------------------

  var ADDRESS_KEY = /^(host|hostname|port|address|addr|ip|url|uri|endpoint|target)$/i;
  var ADDRESS_VALUE = /(\b\d{1,3}(\.\d{1,3}){3}\b)|(:\d{2,5}(\/|$))|(^[a-z][a-z0-9+.-]*:\/\/)/i;

  /** Tiles, ribbon commands and fields that call RPCs or read signals. */
  function uses(manifest) {
    var u = { rpc: [], signals: [], devices: [] };
    (manifest.tiles || []).forEach(function (t, i) {
      var p = 'tiles[' + i + ']';
      if (t.rpc) u.rpc.push(p + '.rpc');
      if (t.call) u.rpc.push(p + '.call');
      if (t.device) u.devices.push({ path: p + '.device', value: t.device });
      (t.fields || []).forEach(function (f, j) {
        var fp = p + '.fields[' + j + ']';
        if (f.rpc) u.rpc.push(fp + '.rpc');
        if (f.signal) u.signals.push(fp + '.signal');
        if (f.device) u.devices.push({ path: fp + '.device', value: f.device });
      });
      (t.signals || []).forEach(function (_, j) { u.signals.push(p + '.signals[' + j + ']'); });
    });
    (manifest.ribbon || []).forEach(function (g, i) {
      (g.commands || []).forEach(function (c, j) {
        if (c.call) u.rpc.push('ribbon[' + i + '].commands[' + j + '].call');
      });
    });
    return u;
  }

  /**
   * Lint one component manifest.
   *
   * @param {object} manifest
   * @param {object} opts
   * @param {object} opts.schema - component.schema.json
   * @param {string} [opts.shell] - shell version (default SHELL_VERSION)
   * @param {Object<string, {plugin: string, schema?: object, needs?: string[]}>} [opts.kinds]
   *   - kinds contributed by enabled plugins
   * @param {Object<string, string>} [opts.knownPluginKinds] - kind -> plugin id,
   *   for kinds of plugins that exist but are not enabled (better hints)
   * @returns {object[]} issues
   */
  function lintComponent(manifest, opts) {
    opts = opts || {};
    var shell = opts.shell || SHELL_VERSION;
    var issues = [];
    var id = (manifest && manifest.component) || '(no id)';
    function add(rule, severity, path, message) {
      issues.push({ rule: rule, severity: severity, component: id, path: path, message: message });
    }

    if (typeOf(manifest) !== 'object') {
      add('S', 'error', '(root)', 'a component manifest must be a JSON object');
      return issues;
    }

    // Structure
    if (opts.schema) {
      validateSchema(opts.schema, manifest).forEach(function (e) { add('S', 'error', e.path, e.message); });
    }

    // R8: one layer, id prefixed with it, unique tile ids
    if (manifest.layer != null && LAYERS.indexOf(manifest.layer) < 0) {
      add('R8', 'error', 'layer', '"' + manifest.layer + '" is not a layer; use one of ' + LAYERS.join(', '));
    } else if (manifest.layer && typeof manifest.component === 'string' &&
               manifest.component.indexOf(manifest.layer + '.') !== 0) {
      add('R8', 'error', 'component', 'must start with "' + manifest.layer + '." (its layer)');
    }
    var seenTiles = {};
    (manifest.tiles || []).forEach(function (t, i) {
      if (t && t.id) {
        if (seenTiles[t.id]) add('R8', 'error', 'tiles[' + i + '].id', 'duplicate tile id "' + t.id + '"');
        seenTiles[t.id] = true;
      }
    });

    // R9: version against the shell
    var req = manifest.requires || {};
    if (typeof req.shell === 'string') {
      if (/^\s*\*?\s*$/.test(req.shell)) {
        add('R9', 'error', 'requires.shell', 'pin a range such as "^' + shell.split('.').slice(0, 2).join('.') + '"');
      } else {
        var sat = satisfies(req.shell, shell);
        if (sat === null) add('R9', 'error', 'requires.shell', 'cannot read range "' + req.shell + '"; use ^x.y, ~x.y, >=x.y or x.y.z');
        else if (!sat) add('R9', 'error', 'requires.shell', 'needs shell ' + req.shell + ', this shell is ' + shell);
      }
    }

    // R1: declared capabilities, known, and covering what is used
    var caps = Array.isArray(req.capabilities) ? req.capabilities : [];
    caps.forEach(function (c, i) {
      if (CAPABILITIES.indexOf(c) < 0) add('R1', 'error', 'requires.capabilities[' + i + ']', 'unknown capability "' + c + '"');
      else if (c === 'process.spawn') add('R1', 'error', 'requires.capabilities[' + i + ']', 'process.spawn is for window plugins, not components');
    });
    var u = uses(manifest);
    if (u.rpc.length && caps.indexOf('grpc.call') < 0) {
      add('R1', 'error', u.rpc[0], 'calls RPCs but grpc.call is not in requires.capabilities');
    }
    if (u.signals.length && caps.indexOf('signals.subscribe') < 0) {
      add('R1', 'error', u.signals[0], 'reads signals but signals.subscribe is not in requires.capabilities');
    }
    var kinds = opts.kinds || {};
    (manifest.tiles || []).forEach(function (t, i) {
      var k = t && kinds[t.kind];
      (k && k.needs || []).forEach(function (need) {
        if (caps.indexOf(need) < 0) {
          add('R1', 'error', 'tiles[' + i + ']', 'kind ' + t.kind + ' needs ' + need + ' in requires.capabilities');
        }
      });
    });
    if (caps.indexOf('grpc.call') >= 0 && !u.rpc.length && !(manifest.dock || []).length) {
      add('R1', 'warn', 'requires.capabilities', 'grpc.call is declared but nothing calls an RPC; declare only what you use');
    }

    // R2: sizes on the grid
    (manifest.tiles || []).forEach(function (t, i) {
      if (t && t.size != null && !SIZES[t.size]) {
        add('R2', 'error', 'tiles[' + i + '].size', '"' + t.size + '" is not a tile size; use 1x1, 2x1, 2x2 or 4x1');
      }
    });

    // R3: identities, not addresses
    var b = manifest.binds || {};
    Object.keys(b).forEach(function (k) {
      var v = String(b[k]);
      if (ADDRESS_KEY.test(k)) add('R3', 'error', 'binds.' + k, 'is an address; bind by Consul name instead');
      else if (ADDRESS_VALUE.test(v)) add('R3', 'error', 'binds.' + k, '"' + v + '" looks like an address; bind by Consul name instead');
    });
    if (typeof b.consul === 'string' && b.consul !== SELF && /[:/\s]/.test(b.consul)) {
      add('R3', 'error', 'binds.consul', '"' + b.consul + '" is not a Consul service name');
    }
    if (u.rpc.length && !b.grpc) {
      add('R3', 'error', 'binds.grpc', 'required when tiles or commands call RPCs (the fully-qualified proto service)');
    }

    // R7: above BITS, read signals, not devices
    if (manifest.layer && manifest.layer !== 'bits') {
      u.devices.forEach(function (d) {
        add('R7', 'error', d.path, 'names device "' + d.value + '"; above the BITS layer name a signal instead');
      });
    }

    // Kinds: core, contributed by an enabled plugin, or missing
    (manifest.tiles || []).forEach(function (t, i) {
      if (!t || !t.kind) return;
      var p = 'tiles[' + i + ']';
      var kindSchema = null;
      if (CORE_KINDS.indexOf(t.kind) >= 0) {
        kindSchema = opts.schema && opts.schema.definitions && opts.schema.definitions.kinds &&
                     opts.schema.definitions.kinds[t.kind];
        if (kindSchema) {
          validateSchema(kindSchema, t, opts.schema, p).forEach(function (e) { add('S', 'error', e.path, e.message); });
        }
        // Rows from an RPC are objects: every column has to say where its value is.
        if (t.kind === 'table' && t.rpc) {
          (t.columns || []).forEach(function (c, j) {
            if (c && c.path == null) add('S', 'error', p + '.columns[' + j + '].path', 'is required when the rows come from an RPC');
          });
        }
      } else if (kinds[t.kind]) {
        if (kinds[t.kind].schema) {
          validateSchema(kinds[t.kind].schema, t, kinds[t.kind].schema, p).forEach(function (e) { add('S', 'error', e.path, e.message); });
        }
      } else {
        var owner = (opts.knownPluginKinds || {})[t.kind];
        add('K', 'warn', p + '.kind', 'kind "' + t.kind + '" is not available' +
            (owner ? '; enable the ' + owner + ' plugin' : '; no enabled plugin provides it'));
      }
    });

    // "html": code runs in frame tiles. "wasm", "qml", "widget" are not hosted yet.
    var frames = (manifest.tiles || []).filter(function (t) { return t && t.kind === 'frame'; });
    if (manifest.renderer === 'html' && !frames.length) {
      add('K', 'warn', 'renderer', 'renderer "html" means frame tiles; this component has none');
    } else if (manifest.renderer && manifest.renderer !== 'schema' && manifest.renderer !== 'html') {
      add('K', 'warn', 'renderer', 'renderer "' + manifest.renderer + '" is not supported by shell ' + shell +
          ' yet; its tiles still render');
    }
    return issues;
  }

  /** Lint several components together: adds cross-component duplicates (R8). */
  function lintComponents(manifests, opts) {
    var issues = [];
    var seen = {};
    (manifests || []).forEach(function (m) {
      issues = issues.concat(lintComponent(m, opts));
      var id = m && m.component;
      if (id) {
        if (seen[id]) issues.push({ rule: 'R8', severity: 'error', component: id, path: 'component', message: 'duplicate component id on this bench' });
        seen[id] = true;
      }
    });
    return issues;
  }

  /** Lint a plugin manifest (structure + R1 + R9). */
  function lintPlugin(manifest, opts) {
    opts = opts || {};
    var shell = opts.shell || SHELL_VERSION;
    var issues = [];
    var id = (manifest && manifest.plugin) || '(no id)';
    function add(rule, severity, path, message) {
      issues.push({ rule: rule, severity: severity, component: id, path: path, message: message });
    }
    if (typeOf(manifest) !== 'object') { add('S', 'error', '(root)', 'a plugin manifest must be a JSON object'); return issues; }
    if (opts.schema) validateSchema(opts.schema, manifest).forEach(function (e) { add('S', 'error', e.path, e.message); });
    var req = manifest.requires || {};
    if (typeof req.shell === 'string') {
      var sat = satisfies(req.shell, shell);
      if (sat === null) add('R9', 'error', 'requires.shell', 'cannot read range "' + req.shell + '"');
      else if (!sat) add('R9', 'error', 'requires.shell', 'needs shell ' + req.shell + ', this shell is ' + shell);
    }
    (req.capabilities || []).forEach(function (c, i) {
      if (CAPABILITIES.indexOf(c) < 0) add('R1', 'error', 'requires.capabilities[' + i + ']', 'unknown capability "' + c + '"');
      else if (c === 'process.spawn' && manifest.isolation !== 'window') {
        add('R1', 'error', 'requires.capabilities[' + i + ']', 'process.spawn needs "isolation": "window"');
      }
    });
    if (manifest.isolation === 'window' && !manifest.main) add('S', 'error', 'main', 'window plugins name their main-process module');

    // P2: namespaced ids; ribbon commands name declared commands.
    var c = manifest.contributes || {};
    var cmdIds = {};
    (Array.isArray(c.commands) ? c.commands : []).forEach(function (cmd, i) {
      var p = 'contributes.commands[' + i + ']';
      if (!cmd || typeof cmd.id !== 'string') return;
      if (cmd.id.indexOf(id + '.') !== 0) add('P2', 'error', p + '.id', 'command ids start with the plugin id ("' + id + '.")');
      if (cmdIds[cmd.id]) add('P2', 'error', p + '.id', 'duplicate command id "' + cmd.id + '"');
      cmdIds[cmd.id] = true;
      if (cmd.window && manifest.isolation !== 'window') add('S', 'error', p + '.window', 'only window plugins open a window');
      if (cmd.entry && cmd.shell) add('S', 'warn', p, 'has both entry and shell; the entry is used');
    });
    (Array.isArray(c['ribbon.groups']) ? c['ribbon.groups'] : []).forEach(function (g, i) {
      ((g && g.commands) || []).forEach(function (rc, j) {
        if (rc && rc.id && !cmdIds[rc.id]) {
          add('S', 'error', 'contributes["ribbon.groups"][' + i + '].commands[' + j + '].id',
              '"' + rc.id + '" is not in contributes.commands');
        }
      });
    });
    ['navigators', 'stage.views', 'dock.sections', 'drawer.tabs'].forEach(function (point) {
      var seen = {};
      (Array.isArray(c[point]) ? c[point] : []).forEach(function (e, i) {
        if (!e || !e.id) return;
        if (seen[e.id]) add('P2', 'error', 'contributes["' + point + '"][' + i + '].id', 'duplicate id "' + e.id + '"');
        seen[e.id] = true;
      });
    });
    var kseen = {};
    (Array.isArray(c.kinds) ? c.kinds : []).forEach(function (k, i) {
      if (!k || !k.kind) return;
      if (CORE_KINDS.indexOf(k.kind) >= 0) add('P2', 'error', 'contributes.kinds[' + i + '].kind', '"' + k.kind + '" is a core kind');
      if (kseen[k.kind]) add('P2', 'error', 'contributes.kinds[' + i + '].kind', 'duplicate kind "' + k.kind + '"');
      kseen[k.kind] = true;
      (k.needs || []).forEach(function (n, j) {
        if (CAPABILITIES.indexOf(n) < 0) add('R1', 'error', 'contributes.kinds[' + i + '].needs[' + j + ']', 'unknown capability "' + n + '"');
      });
    });
    // Code runs in frames (frame) or its own window (window); schema plugins ship none.
    if (manifest.isolation === 'schema' || manifest.isolation === 'window') {
      ['kinds', 'navigators', 'stage.views', 'dock.sections', 'drawer.tabs', 'commands'].forEach(function (point) {
        (Array.isArray(c[point]) ? c[point] : []).forEach(function (e, i) {
          if (e && e.entry) {
            add('P', 'error', 'contributes["' + point + '"][' + i + '].entry',
                manifest.isolation + ' plugins run no module in the shell; use "isolation": "frame" for code');
          }
        });
      });
    }
    if (Array.isArray(c.renderers) && c.renderers.length) {
      add('K', 'warn', 'contributes.renderers', 'renderers are not loaded by shell ' + shell + ' yet (milestone M5)');
    }
    return issues;
  }

  /**
   * Lint a composition (structure + R3 + R9, and C for composition rules).
   * The components it references are linted when the bench resolves them.
   *
   * @param {object} comp
   * @param {object} opts
   * @param {object} [opts.schema] - composition.schema.json
   * @param {string} [opts.shell] - shell version (default SHELL_VERSION)
   * @returns {object[]} issues ({ component } holds the composition id)
   */
  function lintComposition(comp, opts) {
    opts = opts || {};
    var shell = opts.shell || SHELL_VERSION;
    var issues = [];
    var id = (comp && comp.composition) || '(composition)';
    function add(rule, severity, path, message) {
      issues.push({ rule: rule, severity: severity, component: id, path: path, message: message });
    }
    if (typeOf(comp) !== 'object') { add('S', 'error', '(root)', 'a composition must be a JSON object'); return issues; }
    if (opts.schema) validateSchema(opts.schema, comp).forEach(function (e) { add('S', 'error', e.path, e.message); });

    if (typeof comp.shell === 'string') {
      var sat = /^\s*\*?\s*$/.test(comp.shell) ? null : satisfies(comp.shell, shell);
      if (sat === null) add('R9', 'error', 'shell', 'pin a range such as "^' + shell.split('.').slice(0, 2).join('.') + '"');
      else if (!sat) add('R9', 'error', 'shell', 'needs shell ' + comp.shell + ', this shell is ' + shell);
    }

    var seen = {};
    (Array.isArray(comp.components) ? comp.components : []).forEach(function (e, i) {
      var p = 'components[' + i + ']';
      if (typeOf(e) !== 'object') return;
      Object.keys(e).forEach(function (k) {
        if (ADDRESS_KEY.test(k)) add('R3', 'error', p + '.' + k, 'is an address; reference the component by its Consul service name');
      });
      if (typeof e.service === 'string' && (/[:/\s]/.test(e.service) || ADDRESS_VALUE.test(e.service))) {
        add('R3', 'error', p + '.service', '"' + e.service + '" is not a Consul service name');
      }
      var key = e.service + '|' + (e.gui || '');
      if (seen[key]) add('C', 'warn', p, 'lists ' + e.service + ' again; its tiles would appear twice');
      seen[key] = true;
      var tseen = {};
      (Array.isArray(e.tiles) ? e.tiles : []).forEach(function (t, j) {
        if (tseen[t]) add('C', 'warn', p + '.tiles[' + j + ']', 'tile "' + t + '" is listed twice');
        tseen[t] = true;
      });
    });
    if (Array.isArray(comp.components) && !comp.components.length) {
      add('C', 'warn', 'components', 'is empty; the bench shows nothing');
    }
    var oseen = {};
    (Array.isArray(comp.order) ? comp.order : []).forEach(function (o, i) {
      if (oseen[o]) add('C', 'warn', 'order[' + i + ']', '"' + o + '" is listed twice');
      oseen[o] = true;
    });
    return issues;
  }

  function hasErrors(issues) {
    return (issues || []).some(function (i) { return i.severity === 'error'; });
  }

  function formatIssue(i) {
    return i.rule + ' ' + i.severity.toUpperCase() + ' ' + i.component + ' ' + i.path + ': ' + i.message;
  }

  return {
    SHELL_VERSION: SHELL_VERSION,
    LAYERS: LAYERS,
    CAPABILITIES: CAPABILITIES,
    SIZES: SIZES,
    CORE_KINDS: CORE_KINDS,
    SELF: SELF,
    validateSchema: validateSchema,
    satisfies: satisfies,
    lintComponent: lintComponent,
    lintComponents: lintComponents,
    lintPlugin: lintPlugin,
    lintComposition: lintComposition,
    hasErrors: hasErrors,
    formatIssue: formatIssue
  };
});
