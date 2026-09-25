/**
 * @fileoverview Test project client.
 *
 * Wraps the /api/test-project/* endpoints on the FastAPI bridge: describe
 * a folder, initialize it as a test project, plan or apply the export
 * of a Consul-registered service into it, and run its tests. All file I/O
 * and every process happen in the bridge, so this works the same in
 * Electron and browser mode.
 *
 * IIFE attaching to MM.testProjectClient.
 *
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  function _bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (origin && origin.indexOf('http') === 0) return origin;
    return 'http://localhost:1112';
  }

  function _post(path, body) {
    return fetch(_bridgeOrigin() + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .catch(function (err) {
        if (err instanceof TypeError) {
          var e = new Error('Bridge not running on ' + _bridgeOrigin() +
                            ' — click Start Bridge (top-right LED).');
          e.cause = 'bridge_down';
          throw e;
        }
        throw err;
      })
      .then(function (res) {
        if (res.status === 404) {
          // The endpoint itself is missing: the bridge predates test projects.
          throw new Error('The running bridge does not support test projects yet — ' +
                          'restart it (Bridge ■ then ▶ in the navbar) so it loads the current code.');
        }
        return res.json().then(function (data) {
          if (!res.ok || (data && data.status === 'error')) {
            var detail = data && (data.error || data.detail);
            if (Array.isArray(detail)) {
              detail = detail.map(function (d) { return d.msg || JSON.stringify(d); }).join('; ');
            }
            var err = new Error(detail || ('Test project API error ' + res.status));
            if (data && data.code) err.code = data.code;   // e.g. 'conflict'
            throw err;
          }
          return data;
        });
      });
  }

  MM.testProjectClient = {

    /**
     * What a folder is: initialized or not, runner, layout, exported services.
     * @param {string} root Folder path (on the bridge's machine).
     * @returns {Promise<object>}
     */
    describe: function (root) {
      return _post('/api/test-project/describe', { root: root });
    },

    /**
     * Initialize a folder as a test project. Existing files are left alone.
     * @param {string} root
     * @param {string} [runner]      Runner id, default robotframework-aio.
     * @param {string} [consulAddr]  Seeds the runner config.
     * @returns {Promise<object>}
     */
    init: function (root, runner, consulAddr) {
      return _post('/api/test-project/init', {
        root: root,
        runner: runner || 'robotframework-aio',
        consul_addr: consulAddr || ''
      });
    },

    /**
     * Plan (apply=false) or write (apply=true) one service's files.
     * @param {object} opts {root, consul_name, consul, proto_path,
     *   prefer_reflection, create_starter, apply, overwrite_modified}
     * @returns {Promise<object>} files[] with status, advisories, run_hint, ...
     */
    /**
     * Every project file with role (manifest | generated | starter | yours)
     * and sync state (ok | edited | missing), plus exported services.
     * @param {string} root
     * @returns {Promise<object>}
     */
    tree: function (root) {
      return _post('/api/test-project/tree', { root: root });
    },

    /**
     * Text of one project file (read-only preview).
     * @param {string} root
     * @param {string} path Project-relative path.
     * @returns {Promise<{path: string, size: number, content: string}>}
     */
    file: function (root, path) {
      return _post('/api/test-project/file', { root: root, path: path });
    },

    /**
     * Save a user-owned file. Rejects with err.code === 'conflict' when the
     * file changed on disk since expectedSha was read (unless force).
     * @returns {Promise<{sha256: string, size: number, problems: Array}>}
     */
    saveFile: function (root, path, content, expectedSha, force) {
      return _post('/api/test-project/file/save', {
        root: root, path: path, content: content,
        expected_sha256: expectedSha || '', force: !!force
      });
    },

    /**
     * Robot Framework syntax problems of unsaved text.
     * @returns {Promise<{problems: Array<{line: number, message: string}>}>}
     */
    checkFile: function (path, content) {
      return _post('/api/test-project/file/check', { path: path, content: content });
    },

    /**
     * Create a suite from the runner template, optionally wired to an
     * exported service.
     * @returns {Promise<object>} same shape as saveFile, plus path.
     */
    newSuite: function (root, name, service) {
      return _post('/api/test-project/suite', { root: root, name: name, service: service || '' });
    },

    exportService: function (opts) {
      return _post('/api/test-project/export', opts);
    },

    // ---- running tests (whatever runner the project uses) ------------------

    /**
     * Start a run of one file, or of the whole project (path '').
     * @param {object} opts {variables: {name: value}, dryrun: bool}
     * @returns {Promise<object>} the run: id, run_state, target_label, argv, results_url, ...
     */
    run: function (root, path, opts) {
      opts = opts || {};
      return _post('/api/test-project/run', {
        root: root, path: path || '', variables: opts.variables || {}, dryrun: !!opts.dryrun
      });
    },

    /**
     * A run's state and outcome, plus the console lines after `since`
     * (`next` is the cursor for the following call).
     */
    runStatus: function (root, runId, since) {
      return _post('/api/test-project/run/status', { root: root, run_id: runId, since: since || 0 });
    },

    /** Stop gracefully (teardowns and reports still run); force kills at once. */
    stopRun: function (root, runId, force) {
      return _post('/api/test-project/run/stop', { root: root, run_id: runId, force: !!force });
    },

    /** The project's recent runs, newest first. */
    runs: function (root) {
      return _post('/api/test-project/runs', { root: root });
    },

    /** Read (settings omitted) or replace the project's run settings. */
    runSettings: function (root, settings) {
      var body = { root: root };
      if (settings) body.settings = settings;
      return _post('/api/test-project/run-settings', body);
    },

    /**
     * A file's extra views from the project's runner (a flow's diagram and
     * Robot text). `content` is the editor's text; omit it for the file on disk.
     * @returns {Promise<{ok: boolean, views: object, error: string, node: string, line: number, missing: boolean}>}
     */
    inspect: function (root, path, content) {
      var body = { root: root, path: path };
      if (typeof content === 'string') body.content = content;
      return _post('/api/test-project/inspect', body);
    },

    /** Absolute URL of a file a run left behind (results_url + name). */
    resultUrl: function (run, name) {
      return _bridgeOrigin() + run.results_url + encodeURIComponent(name);
    }
  };

})();
