"use strict";

// Signal Graph Studio, hosted by the Manager GUI.
//
// The studio is the stand-alone Signals & Blocks tool, vendored as-is under
// app/ (renderer) with this file replacing its main.js: the same IPC
// handlers, now registered by the host's main process under "gs:"-prefixed
// channels, plus a window opener the host calls from its Developer Tools
// menu.
//
// Only the studio window is created here; the host owns app lifecycle. The
// host must call shutdownGraphStudio() on quit — the studio can hold child
// processes (a local cluster, one grpcurl per monitored endpoint).

const { BrowserWindow, ipcMain, dialog } = require("electron");
const fs = require("fs");
const path = require("path");
const { spawn, execFile } = require("child_process");
const { JsonObjectStream } = require("./tools/jsonstream");

const CH = (name) => "gs:" + name;

// Anything handed to a child process (python, grpcurl) or written to must be
// a real file, not a path inside app.asar. electron-builder unpacks
// graph-studio/** (see package.json "asarUnpack"), so rewrite the archive
// segment; outside a packaged app this is a no-op.
function unpacked(p) {
  const seg = path.sep + "app.asar" + path.sep;
  return p.includes(seg) ? p.replace(seg, path.sep + "app.asar.unpacked" + path.sep) : p;
}

const TOOL_ROOT = unpacked(__dirname);
const REF_PROTOS = path.join(TOOL_ROOT, "reference", "protos");

// The local runner (tools/run_cluster.py) is ours and vendored; the signals
// code it runs is NOT — only reference/protos/signal.proto is vendored
// (grpcurl needs it — graph services serve no reflection). "Run graph" /
// "Run cluster" need a signals root: a directory containing signal_graph/,
// signal_discovery/ and common/ (the repo's services/signals). It comes
// from the studio's Live panel field, else MB_SIGNALS_ROOT, else the
// sibling-checkout guess below (taf_repo_proposal next to this repository).
const SIGNALS_ROOT_ENV = "MB_SIGNALS_ROOT";
const RUNNER = path.join(TOOL_ROOT, "tools", "run_cluster.py");
const REPO_SIGNALS_GUESS = path.resolve(TOOL_ROOT, "..", "..", "..", "..", "taf_repo_proposal", "services", "signals");

function isSignalsRoot(dir) {
  return !!dir && fs.existsSync(path.join(dir, "signal_graph", "app.py"))
              && fs.existsSync(path.join(dir, "signal_discovery", "app.py"));
}
function signalsRoot() {
  if (isSignalsRoot(process.env[SIGNALS_ROOT_ENV])) return process.env[SIGNALS_ROOT_ENV];
  if (isSignalsRoot(REPO_SIGNALS_GUESS)) return REPO_SIGNALS_GUESS;
  const ref = path.join(TOOL_ROOT, "reference", "signals");
  if (isSignalsRoot(ref)) return ref;
  return "";
}

let studioWin = null;
let watcher = null;
let watchedPath = null;
let registered = false;
let runChild = null;                  // the local cluster (python)
const monitorChildren = new Map();    // "host:port" -> grpcurl child

function sidecarPath(graphPath) {
  return graphPath.replace(/\.json$/i, "") + ".layout.json";
}

function sendToStudio(channel, payload) {
  if (studioWin && !studioWin.isDestroyed()) studioWin.webContents.send(channel, payload);
}

function killTree(child) {
  if (!child || child.killed) return;
  try {
    if (process.platform === "win32") {
      // The python runner spawns graph services; kill the whole tree.
      spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      child.kill("SIGTERM");
    }
  } catch (_e) { /* already gone */ }
}

function stopWatch() {
  if (watcher) {
    watcher.close();
    watcher = null;
    watchedPath = null;
  }
}

function startWatch(filePath) {
  stopWatch();
  watchedPath = filePath;
  try {
    watcher = fs.watch(filePath, { persistent: false }, () => {
      // Debounce: editors often fire several events per save.
      clearTimeout(startWatch._t);
      startWatch._t = setTimeout(() => {
        if (studioWin && !studioWin.isDestroyed() && watchedPath) {
          sendToStudio(CH("file-changed"), watchedPath);
        }
      }, 150);
    });
  } catch (_e) {
    // Watching is best-effort (e.g. network drives); the tool works without it.
  }
}

function readGraph(graphPath) {
  const out = { path: graphPath, content: null, layout: null, layoutPath: sidecarPath(graphPath) };
  out.content = fs.readFileSync(graphPath, "utf-8");
  try {
    out.layout = fs.readFileSync(out.layoutPath, "utf-8");
  } catch (_e) {
    out.layout = null; // no sidecar yet: auto-layout will be used
  }
  return out;
}

/**
 * Stop everything the studio may have started. Safe to call repeatedly;
 * the host calls it on quit, and the studio window calls it when closed.
 */
function shutdownGraphStudio() {
  stopWatch();
  for (const child of monitorChildren.values()) killTree(child);
  monitorChildren.clear();
  if (runChild) {
    try { runChild.stdin.end(); } catch (_e) { /* ignore */ }
    killTree(runChild);
    runChild = null;
  }
}

/**
 * Register the studio's IPC handlers. Idempotent; call once from the
 * host's main process (before or after app ready).
 */
function registerGraphStudioIpc() {
  if (registered) return;
  registered = true;

  // ─── files ─────────────────────────────────────────────────────────

  ipcMain.handle(CH("open-graph"), async () => {
    const res = await dialog.showOpenDialog(studioWin, {
      title: "Open graph.json",
      filters: [{ name: "Graph JSON", extensions: ["json"] }],
      properties: ["openFile"],
    });
    if (res.canceled || res.filePaths.length === 0) return null;
    const out = readGraph(res.filePaths[0]);
    startWatch(out.path);
    return out;
  });

  ipcMain.handle(CH("reload-graph"), async (_ev, graphPath) => readGraph(graphPath));

  ipcMain.handle(CH("save-graph"), async (_ev, payload) => {
    // payload: { path|null, graphContent, layoutContent }
    let graphPath = payload.path;
    if (!graphPath) {
      const res = await dialog.showSaveDialog(studioWin, {
        title: "Save graph.json",
        defaultPath: "graph.json",
        filters: [{ name: "Graph JSON", extensions: ["json"] }],
      });
      if (res.canceled || !res.filePath) return null;
      graphPath = res.filePath;
    }
    // Suspend the watcher during our own write so it does not ping us back.
    stopWatch();
    fs.writeFileSync(graphPath, payload.graphContent, "utf-8");
    fs.writeFileSync(sidecarPath(graphPath), payload.layoutContent, "utf-8");
    startWatch(graphPath);
    return { path: graphPath, layoutPath: sidecarPath(graphPath) };
  });

  ipcMain.handle(CH("generate-service"), async (_ev, payload) => {
    // payload: { serviceName, graphContent, layoutContent, nomadContent, runContent }
    const res = await dialog.showOpenDialog(studioWin, {
      title: "Choose the configs root directory (a folder per service is created inside)",
      properties: ["openDirectory", "createDirectory"],
    });
    if (res.canceled || res.filePaths.length === 0) return null;
    const root = res.filePaths[0];
    const svcDir = path.join(root, payload.serviceName);
    fs.mkdirSync(svcDir, { recursive: true });
    const files = [];
    const writeOut = (p, content) => { fs.writeFileSync(p, content, "utf-8"); files.push(p); };
    writeOut(path.join(svcDir, "graph.json"), payload.graphContent);
    writeOut(path.join(svcDir, "graph.layout.json"), payload.layoutContent);
    writeOut(path.join(root, `testbench_signal_graph_${payload.serviceName}.nomad`), payload.nomadContent);
    writeOut(path.join(svcDir, "RUN.txt"), payload.runContent);

    // Cross-graph signal-name collision scan over every */graph.json under root.
    const owners = {}; // signal name -> [service dirs]
    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const gp = path.join(root, entry.name, "graph.json");
      if (!fs.existsSync(gp)) continue;
      try {
        const g = JSON.parse(fs.readFileSync(gp, "utf-8"));
        for (const obs of g.observe || []) {
          (owners[obs.name] = owners[obs.name] || []).push(entry.name);
        }
      } catch (_e) { /* unparseable sibling: not this feature's problem */ }
    }
    const collisions = Object.entries(owners)
      .filter(([, dirs]) => dirs.length > 1)
      .map(([name, dirs]) => ({ name, services: dirs }));

    return { root, files, collisions };
  });

  // ─── live bench lookups ────────────────────────────────────────────

  ipcMain.handle(CH("fetch-consul-services"), async (_ev, opts) => {
    // Consul catalog over plain HTTP: { serviceName: [tags...], ... }
    const host = (opts && opts.host) || "127.0.0.1";
    const port = (opts && opts.port) || 8500;
    const url = `http://${host}:${port}/v1/catalog/services`;
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(4000) });
      if (!resp.ok) return { error: `Consul answered HTTP ${resp.status}` };
      const data = await resp.json();
      return { services: Object.entries(data).map(([name, tags]) => ({ name, tags })) };
    } catch (e) {
      return { error: `Consul unreachable at ${host}:${port} (${e.message})` };
    }
  });

  ipcMain.handle(CH("fetch-discovery-signals"), async (_ev, opts) => {
    // signal-discovery speaks gRPC only; shell out to grpcurl, which the
    // Manager GUI already requires on PATH.
    const endpoint = `${(opts && opts.host) || "127.0.0.1"}:${(opts && opts.port) || 50210}`;
    const call = (method) => new Promise((resolve) => {
      const args = ["-plaintext", "-d", "{}"];
      // Reflection may be off on discovery: allow a proto fallback.
      if (opts && opts.protoDir) {
        args.push("-import-path", opts.protoDir, "-proto", "signal.proto");
      }
      args.push(endpoint, `signal.SignalDiscoveryService/${method}`);
      execFile("grpcurl", args, { timeout: 5000 }, (err, stdout, stderr) => {
        if (err) {
          const reason = err.code === "ENOENT"
            ? "grpcurl not found on PATH"
            : (stderr || err.message).toString().split("\n")[0];
          resolve({ error: reason });
        } else {
          try { resolve({ data: JSON.parse(stdout || "{}") }); }
          catch (_e) { resolve({ error: "grpcurl returned non-JSON output" }); }
        }
      });
    });

    const signals = await call("ListSignals");
    if (signals.error) return { error: signals.error };
    const errors = await call("ListSignalErrors"); // best-effort
    return {
      signals: (signals.data.signals || []).map((s) => ({
        name: s.name, kind: s.kind || "", unit: s.unit || "",
        host: (s.endpoint && s.endpoint.host) || "", port: (s.endpoint && s.endpoint.port) || 0,
      })),
      collisions: ((errors.data && errors.data.errors) || []).map((e) => ({
        name: e.signalName || e.signal_name, reason: e.reason || "",
      })),
    };
  });

  // ─── paths ─────────────────────────────────────────────────────────

  ipcMain.handle(CH("get-paths"), async () => {
    const root = signalsRoot();
    return {
      toolRoot: TOOL_ROOT,
      referenceSignals: root,
      referenceProtos: REF_PROTOS,
      runner: RUNNER,
      signalsRoot: root,                  // best guess; the Live panel field overrides it
      hasReferenceSignals: !!root,        // legacy name: "a signals root is available"
    };
  });

  // ─── run a local mocked cluster ────────────────────────────────────

  ipcMain.handle(CH("run-start"), async (_ev, opts) => {
    // opts: { mode: "all" | "configs", configs?: [paths], python?, signalsRoot?, discoveryPort? }
    if (runChild) return { error: "a cluster is already running — stop it first" };
    const root = (opts && opts.signalsRoot) || signalsRoot();
    if (!isSignalsRoot(root)) {
      return { error: `no signals root: ${root || "(none)"} — set "signals root" in the Live panel ` +
                      `(or ${SIGNALS_ROOT_ENV}) to <repo>/services/signals (must contain ` +
                      "signal_graph/ and signal_discovery/)" };
    }
    if (!fs.existsSync(RUNNER)) return { error: `runner missing: ${RUNNER}` };
    const args = [RUNNER, "--signals-root", root, "--exit-on-stdin-close",
                  "--discovery-port", String((opts && opts.discoveryPort) || 50210)];
    if (opts && opts.mode === "all") args.push("--all");
    for (const c of (opts && opts.configs) || []) args.push("--config", c);

    let child;
    try {
      child = spawn((opts && opts.python) || "python", args, {
        cwd: root,
        env: Object.assign({}, process.env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1" }),
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (e) {
      return { error: e.message };
    }
    runChild = child;
    const relay = (stream) => (chunk) => {
      for (const line of String(chunk).split(/\r?\n/)) {
        if (!line) continue;
        sendToStudio(CH("run-output"), { stream, line });
        if (line.trim() === "READY") sendToStudio(CH("run-status"), { state: "ready" });
      }
    };
    child.stdout.on("data", relay("stdout"));
    child.stderr.on("data", relay("stderr"));
    child.on("error", (e) => {
      const message = e.code === "ENOENT"
        ? `python not found: ${(opts && opts.python) || "python"}`
        : e.message;
      sendToStudio(CH("run-status"), { state: "error", message });
      if (runChild === child) runChild = null;
    });
    child.on("exit", (code) => {
      sendToStudio(CH("run-status"), { state: "exited", code });
      if (runChild === child) runChild = null;
    });
    sendToStudio(CH("run-status"), { state: "starting", pid: child.pid });
    return { pid: child.pid };
  });

  ipcMain.handle(CH("run-stop"), async () => {
    if (!runChild) return { stopped: false };
    const child = runChild;
    try { child.stdin.end(); } catch (_e) { /* ignore */ }  // graceful: stdin EOF stops the cluster
    setTimeout(() => { if (runChild === child) killTree(child); }, 2500);
    return { stopped: true };
  });

  // ─── monitor live signals / write a setpoint ────────────────────────

  ipcMain.handle(CH("monitor-start"), async (_ev, opts) => {
    // opts: { targets: [{host, port, names: [...]}], protoDir? }
    const protoDir = (opts && opts.protoDir) || REF_PROTOS;
    const started = [];
    for (const t of (opts && opts.targets) || []) {
      const key = `${t.host}:${t.port}`;
      if (monitorChildren.has(key)) continue;
      const args = [
        "-plaintext", "-import-path", protoDir, "-proto", "signal.proto",
        "-d", JSON.stringify({ signal_names: t.names }),
        key, "signal.SignalQueryService/Subscribe",
      ];
      const child = spawn("grpcurl", args, { stdio: ["ignore", "pipe", "pipe"] });
      const parser = new JsonObjectStream((obj) => {
        sendToStudio(CH("monitor-update"), {
          host: t.host, port: t.port,
          name: obj.signalName || obj.signal_name,
          value: obj.value, timestamp: obj.timestamp,
        });
      });
      child.stdout.on("data", (c) => parser.feed(c));
      let errText = "";
      child.stderr.on("data", (c) => { errText += String(c); });
      child.on("error", (e) => sendToStudio(CH("monitor-status"), {
        key, state: "error",
        message: e.code === "ENOENT" ? "grpcurl not found on PATH" : e.message,
      }));
      child.on("exit", (code) => {
        monitorChildren.delete(key);
        sendToStudio(CH("monitor-status"), {
          key, state: "exited", code, message: errText.trim().split("\n")[0] || "",
        });
      });
      monitorChildren.set(key, child);
      started.push(key);
    }
    return { started };
  });

  ipcMain.handle(CH("monitor-stop"), async () => {
    for (const child of monitorChildren.values()) killTree(child);
    monitorChildren.clear();
    return { stopped: true };
  });

  ipcMain.handle(CH("set-signal"), async (_ev, opts) => {
    // opts: { host, port, name, value, protoDir? } — one unary SetSignal on
    // the owning graph service (setpoints are written on its own port).
    const protoDir = (opts && opts.protoDir) || REF_PROTOS;
    const endpoint = `${(opts && opts.host) || "127.0.0.1"}:${opts && opts.port}`;
    const args = [
      "-plaintext", "-import-path", protoDir, "-proto", "signal.proto",
      "-d", JSON.stringify({ name: opts && opts.name, value: Number(opts && opts.value) }),
      endpoint, "signal.SignalQueryService/SetSignal",
    ];
    return new Promise((resolve) => {
      execFile("grpcurl", args, { timeout: 5000 }, (err, stdout, stderr) => {
        if (err) {
          const reason = err.code === "ENOENT"
            ? "grpcurl not found on PATH"
            : (stderr || err.message).toString().trim().split("\n").pop();
          return resolve({ error: reason });
        }
        try {
          const data = JSON.parse(stdout || "{}");
          // protojson omits `success` when false — normalise to a boolean.
          resolve({ success: data.success === true, message: data.message || "" });
        } catch (_e) {
          resolve({ error: "grpcurl returned non-JSON output" });
        }
      });
    });
  });

  // ─── library tools: scaffold blocks, regenerate the catalog ─────────

  ipcMain.handle(CH("pick-path"), async (_ev, opts) => {
    // opts: { kind: "file" | "dir", title?, filters? } -> absolute path or null
    const res = await dialog.showOpenDialog(studioWin, {
      title: (opts && opts.title) || "Pick",
      properties: opts && opts.kind === "dir" ? ["openDirectory", "createDirectory"] : ["openFile"],
      filters: (opts && opts.filters) || undefined,
    });
    if (res.canceled || res.filePaths.length === 0) return null;
    return res.filePaths[0];
  });

  ipcMain.handle(CH("write-files"), async (_ev, payload) => {
    // payload: { root, files: [{ rel, content, mode: "create" | "append" | "overwrite" }] }
    // "create" never clobbers: an existing file is reported in `skipped`.
    const root = path.resolve((payload && payload.root) || "");
    if (!root || !fs.existsSync(root)) return { error: `parent directory does not exist: ${root}` };
    const written = [], appended = [], skipped = [];
    for (const f of (payload && payload.files) || []) {
      const full = path.resolve(root, f.rel);
      if (!full.startsWith(root + path.sep)) return { error: `refusing to write outside ${root}: ${f.rel}` };
      fs.mkdirSync(path.dirname(full), { recursive: true });
      const exists = fs.existsSync(full);
      if (f.mode === "append") {
        if (!exists) return { error: `cannot append — file does not exist: ${full}` };
        fs.appendFileSync(full, f.content, "utf-8");
        appended.push(full);
      } else if (exists && f.mode !== "overwrite") {
        skipped.push(full);
      } else {
        fs.writeFileSync(full, f.content, "utf-8");
        written.push(full);
      }
    }
    return { written, appended, skipped };
  });

  ipcMain.handle(CH("catalog-generate"), async (_ev, opts) => {
    // opts: { sources: [paths], python? } -> tools/generate_catalog.py --update-tool <toolRoot>
    const script = path.join(TOOL_ROOT, "tools", "generate_catalog.py");
    const sources = ((opts && opts.sources) || []).filter(Boolean);
    if (!sources.length) return { ok: false, error: "no sources given" };
    if (!fs.existsSync(script)) {
      return { ok: false, error: `generate_catalog.py not found at ${script}` };
    }
    const args = [script, ...sources, "--update-tool", TOOL_ROOT];
    return new Promise((resolve) => {
      execFile((opts && opts.python) || "python", args,
        { timeout: 30000, env: Object.assign({}, process.env, { PYTHONUTF8: "1" }) },
        (err, stdout, stderr) => {
          if (err) {
            resolve({
              ok: false, stdout, stderr: stderr || "",
              error: err.code === "ENOENT"
                ? `python not found: ${(opts && opts.python) || "python"}`
                : err.message,
            });
          } else {
            resolve({ ok: true, stdout, stderr });
          }
        });
    });
  });

  ipcMain.handle(CH("load-catalog"), async () => {
    // blocks_catalog.json next to this file replaces the built-in catalog.
    // It is GENERATED (tools/generate_catalog.py); never hand-edit it. Read
    // the unpacked copy first — that is the one "Regenerate catalog" writes.
    for (const dir of [TOOL_ROOT, __dirname]) {
      try {
        return fs.readFileSync(path.join(dir, "blocks_catalog.json"), "utf-8");
      } catch (_e) { /* try the next location */ }
    }
    return null;
  });
}

/**
 * Open (or focus) the studio window.
 *
 * @param {object} [opts]
 * @param {string} [opts.consulUrl] - e.g. "http://127.0.0.1:8501"; seeds
 *   the studio's live panel unless the user already saved endpoints.
 * @param {string} [opts.python]    - interpreter for Run / Regenerate
 *   catalog; seeded the same way (the GUI's configured Python beats the
 *   bare "python" default, which on Windows is often a store stub).
 * @param {string} [opts.iconPath]  - window icon.
 * @returns {BrowserWindow}
 */
function openGraphStudio(opts) {
  opts = opts || {};
  if (studioWin && !studioWin.isDestroyed()) {
    studioWin.show();
    studioWin.focus();
    return studioWin;
  }

  studioWin = new BrowserWindow({
    width: 1440,
    height: 900,
    backgroundColor: "#0b1120",
    icon: opts.iconPath,
    title: "Signal Graph Studio",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  studioWin.setMenuBarVisibility(false);

  // Pre-fill the live panel with the Consul the Manager GUI is connected to
  // and the Python it uses. The editor keeps these in localStorage
  // ("gs-live"); a saved choice wins over ours.
  let seed = null;
  if (opts.consulUrl) {
    try {
      const u = new URL(opts.consulUrl);
      seed = { host: u.hostname, port: parseInt(u.port, 10) || 8500 };
    } catch (_e) { /* not a URL: skip */ }
  }
  const python = (opts.python || "").trim();
  studioWin.webContents.on("did-finish-load", () => {
    if (!seed && !python) return;
    studioWin.webContents.executeJavaScript(
      "(function () {" +
      "  try { if (localStorage.getItem('gs-live')) return 'kept'; } catch (e) {}" +
      "  if (typeof state === 'undefined' || !state.live) return 'no-state';" +
      (seed
        ? "  state.live.consulHost = " + JSON.stringify(seed.host) + ";" +
          "  state.live.consulPort = " + seed.port + ";"
        : "") +
      (python ? "  state.live.python = " + JSON.stringify(python) + ";" : "") +
      "  if (typeof saveLive === 'function') saveLive();" +
      "  if (typeof render === 'function') render();" +
      "  return 'seeded';" +
      "})()", true).catch(() => {});
  });

  // Closing with unsaved changes: the editor's beforeunload would just
  // swallow the close silently; ask instead.
  studioWin.on("close", (event) => {
    if (studioWin.__forceClose) return;
    event.preventDefault();
    const win = studioWin;
    win.webContents.executeJavaScript("typeof state !== 'undefined' && !!state.dirty", true)
      .catch(() => false)
      .then(async (dirty) => {
        if (dirty) {
          const r = await dialog.showMessageBox(win, {
            type: "warning",
            buttons: ["Discard and close", "Keep editing"],
            defaultId: 1,
            cancelId: 1,
            title: "Unsaved graph",
            message: "The graph has unsaved changes.",
            detail: "Close anyway? The changes will be lost.",
          });
          if (r.response !== 0) return;
        }
        win.__forceClose = true;
        win.destroy();
      });
  });

  studioWin.on("closed", () => {
    // A closed studio must not leave a cluster or grpcurl streams behind.
    shutdownGraphStudio();
    studioWin = null;
  });

  studioWin.loadFile(path.join(__dirname, "app", "index.html"));
  return studioWin;
}

module.exports = {
  registerGraphStudioIpc, openGraphStudio, shutdownGraphStudio,
  // The window-plugin interface (web/plugins/graph-studio/plugin.json "main").
  register: registerGraphStudioIpc, open: openGraphStudio, shutdown: shutdownGraphStudio,
};
