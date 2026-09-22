/**
 * @fileoverview Bench Endoskeleton component host (contract v1, milestone M1).
 *
 * Mounts one component.json into a panel: lints it against the contract,
 * refuses it visibly when it breaks a rule (R10), otherwise lays its tiles
 * on the 4-column stage and gives each tile a ctx limited to the
 * capabilities the manifest declared (R1).
 *
 *   MM.endo.mountComponent(manifest, el, env) -> Promise<handle>
 *     env:    { consulName, consulUrl, protoPath }
 *     handle: { suspend(), resume(), destroy(), issues }
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};

  var SCHEMA_URL = 'js/endo/contract/component.schema.json';

  /** Kinds that plugins will contribute (M4): used for "enable plugin X" hints. */
  var KNOWN_PLUGIN_KINDS = { 'signal-strip': 'charts', 'uds-console': 'uds-console', 'graph': 'graph-studio' };

  var schemaPromise = null;
  function loadSchema() {
    if (!schemaPromise) {
      schemaPromise = fetch(SCHEMA_URL)
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .catch(function () { schemaPromise = null; return null; });
    }
    return schemaPromise;
  }

  function esc(s) { return MM.endo.util.esc(s); }

  function denied(cap) {
    var e = new Error('CapabilityDenied: ' + cap + ' is not declared in requires.capabilities');
    e.code = 'CapabilityDenied';
    return Promise.reject(e);
  }

  /** The only way a tile reaches the outside world. */
  function makeCtx(manifest, env) {
    var req = manifest.requires || {};
    var caps = {};
    (req.capabilities || []).forEach(function (c) { caps[c] = true; });
    var binds = manifest.binds || {};
    var consulName = binds.consul === '@self' ? env.consulName : binds.consul;
    var methodsP = null;

    return {
      component: manifest.component,
      consulName: consulName,

      call: function (method, args) {
        if (!caps['grpc.call']) return denied('grpc.call');
        return MM.grpcClient.callMethod({
          consulName: consulName,
          consulUrl: env.consulUrl,
          grpcService: binds.grpc,
          method: method,
          argsJson: JSON.stringify(args || {}),
          protoPath: env.protoPath
        }).then(function (d) {
          if (!d || !d.ok) throw new Error((d && d.error) || (method + ' failed'));
          return d;
        });
      },

      describe: function (method) {
        if (!caps['grpc.call']) return denied('grpc.call');
        methodsP = methodsP || MM.grpcClient.getServiceMethods(consulName, env.consulUrl, env.protoPath);
        return methodsP.then(function (data) {
          var svc = ((data && data.grpc_services) || []).filter(function (s) { return s.name === binds.grpc; })[0];
          if (!svc) {
            methodsP = null;   // retry next time: the service may just be starting
            throw new Error(binds.grpc + ' is not served by ' + consulName + (data && data.error ? ' (' + data.error + ')' : ''));
          }
          var m = (svc.methods || []).filter(function (x) { return x.name === method; })[0];
          if (!m) throw new Error(method + ' is not a method of ' + binds.grpc);
          return m;
        });
      },

      signals: {
        subscribe: function () {
          if (!caps['signals.subscribe']) return denied('signals.subscribe');
          return Promise.reject(new Error('Live signals arrive with the host bus (milestone M3).'));
        }
      },

      confirm: function (message) {
        return new Promise(function (resolve) {
          if (MM.showConfirm) MM.showConfirm(message, function () { resolve(true); });
          else resolve(true);
        });
      },

      notify: function (kind, text) {
        if (MM.showToast) MM.showToast(manifest.title || manifest.component, text, kind || 'info');
      }
    };
  }

  function layerVar(layer) {
    var C = window.EndoContract;
    return C && C.LAYERS.indexOf(layer) >= 0 ? 'var(--l-' + layer + ')' : 'var(--l-runner)';
  }

  function headerHtml(manifest, issues, env) {
    var warns = issues.filter(function (i) { return i.severity === 'warn'; });
    var errs = issues.filter(function (i) { return i.severity === 'error'; });
    var badge = errs.length
      ? '<span class="endo-lint bad">refused · ' + errs.length + ' error' + (errs.length > 1 ? 's' : '') + '</span>'
      : warns.length
        ? '<span class="endo-lint warn">contract v1 · ' + warns.length + ' warning' + (warns.length > 1 ? 's' : '') + '</span>'
        : '<span class="endo-lint ok">contract v1 · passes</span>';
    var list = function (arr) {
      return '<ul class="endo-issues">' + arr.map(function (i) {
        return '<li><b>' + esc(i.rule) + '</b> <code>' + esc(i.path) + '</code> ' + esc(i.message) + '</li>';
      }).join('') + '</ul>';
    };
    return '<div class="endo-head">' +
      '<span class="endo-layer">' + esc(manifest.layer || '?') + '</span>' +
      '<h5>' + esc(manifest.title || manifest.component || 'Component') + '</h5>' +
      '<span class="endo-id">' + esc(manifest.component || '') + ' ' + esc(manifest.version || '') +
        ' · ' + esc(env.consulName || '') + '</span>' +
      badge +
      '</div>' +
      (warns.length && !errs.length ? '<details class="endo-warns"><summary>Warnings</summary>' + list(warns) + '</details>' : '') +
      (errs.length ? '<div class="endo-refused" role="alert"><strong>The shell refused this component.</strong> ' +
        'Its slot stays here so the reason is visible (R10). Fix these and reload:' + list(errs) + '</div>' : '');
  }

  function tileClasses(size) {
    var s = (window.EndoContract && window.EndoContract.SIZES[size]) || [2, 1];
    return 'endo-tile w' + s[0] + ' h' + s[1];
  }

  function mountComponent(manifest, el, env) {
    env = env || {};
    return loadSchema().then(function (schema) {
      var C = window.EndoContract;
      var issues;
      if (manifest && manifest.__parseError) {
        issues = [{ rule: 'S', severity: 'error', component: '(component.json)', path: '(file)',
                    message: 'not valid JSON: ' + manifest.__parseError }];
        manifest = { title: 'component.json', layer: '?' };
      } else {
        issues = C.lintComponent(manifest, { schema: schema, knownPluginKinds: KNOWN_PLUGIN_KINDS });
        if (!schema) {
          issues.push({ rule: 'S', severity: 'warn', component: manifest.component || '?', path: '(schema)',
                        message: 'contract schema could not be loaded; only the rules were checked' });
        }
      }

      el.innerHTML = '';
      var root = document.createElement('div');
      root.className = 'endo-comp';
      root.style.setProperty('--layer', layerVar(manifest.layer));
      root.innerHTML = headerHtml(manifest, issues, env);
      el.appendChild(root);

      var instances = [];
      var handle = {
        issues: issues,
        suspend: function () { instances.forEach(function (i) { try { i.suspend(); } catch (e) { /* keep going */ } }); },
        resume: function () { instances.forEach(function (i) { try { i.resume(); } catch (e) { /* keep going */ } }); },
        destroy: function () { instances.forEach(function (i) { try { i.destroy(); } catch (e) { /* keep going */ } }); instances = []; }
      };
      if (C.hasErrors(issues)) return handle;

      var ctx = makeCtx(manifest, env);
      var stage = document.createElement('div');
      stage.className = 'endo-stage';
      root.appendChild(stage);

      (manifest.tiles || []).forEach(function (tile) {
        var section = document.createElement('section');
        section.className = tileClasses(tile.size);
        section.setAttribute('data-tile', tile.id);
        section.innerHTML =
          '<header class="endo-tile-head"><span class="t">' + esc(tile.title || tile.id) + '</span>' +
          '<span class="src">' + esc(tile.kind) + '</span></header>' +
          '<div class="endo-tile-body"></div>';
        stage.appendChild(section);
        var body = section.querySelector('.endo-tile-body');
        var kind = MM.endo.kinds[tile.kind];
        if (!kind) {
          var owner = KNOWN_PLUGIN_KINDS[tile.kind];
          body.innerHTML = '<div class="endo-placeholder">Kind <code>' + esc(tile.kind) + '</code> is not available. ' +
            (owner ? 'It comes from the <strong>' + esc(owner) + '</strong> plugin (plugins arrive with milestone M4).'
                   : 'No plugin provides it.') + '</div>';
          return;
        }
        var inst;
        try { inst = kind.render(body, tile, ctx); }
        catch (e) {
          body.innerHTML = '<div class="endo-error">' + esc(e.message) + '</div>';   // fail small (R10)
          return;
        }
        instances.push(inst);
        if (inst.refresh) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'endo-refresh';
          btn.title = 'Refresh';
          btn.setAttribute('aria-label', 'Refresh ' + (tile.title || tile.id));
          btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
          btn.addEventListener('click', function () { inst.refresh(); });
          section.querySelector('.endo-tile-head').appendChild(btn);
        }
      });
      return handle;
    });
  }

  MM.endo.mountComponent = mountComponent;
  MM.endo.loadSchema = loadSchema;
  /** Exposed for plugin kinds (M4) and tests: the capability-gated context. */
  MM.endo.makeCtx = makeCtx;
})();
