"use strict";

// contextBridge for the Signal Graph Studio window (window.bridge).
//
// Channels carry the "gs:" prefix so they cannot collide with the Manager
// GUI's own IPC; the handlers live in ipc.js. The editor only knows the
// method names below, never the channel strings.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("bridge", {
  // Files
  openGraph: () => ipcRenderer.invoke("gs:open-graph"),
  reloadGraph: (p) => ipcRenderer.invoke("gs:reload-graph", p),
  saveGraph: (payload) => ipcRenderer.invoke("gs:save-graph", payload),
  generateService: (payload) => ipcRenderer.invoke("gs:generate-service", payload),
  onFileChanged: (cb) => ipcRenderer.on("gs:file-changed", (_ev, p) => cb(p)),

  // Live bench lookups
  fetchConsulServices: (opts) => ipcRenderer.invoke("gs:fetch-consul-services", opts),
  fetchDiscoverySignals: (opts) => ipcRenderer.invoke("gs:fetch-discovery-signals", opts),

  // Where the studio lives (tool root, reference protos, run_cluster.py)
  getPaths: () => ipcRenderer.invoke("gs:get-paths"),

  // Run a local mocked cluster
  runStart: (opts) => ipcRenderer.invoke("gs:run-start", opts),
  runStop: () => ipcRenderer.invoke("gs:run-stop"),
  onRunOutput: (cb) => ipcRenderer.on("gs:run-output", (_ev, p) => cb(p)),
  onRunStatus: (cb) => ipcRenderer.on("gs:run-status", (_ev, p) => cb(p)),

  // Subscribe to live signal values / write a setpoint
  monitorStart: (opts) => ipcRenderer.invoke("gs:monitor-start", opts),
  monitorStop: () => ipcRenderer.invoke("gs:monitor-stop"),
  onMonitorUpdate: (cb) => ipcRenderer.on("gs:monitor-update", (_ev, p) => cb(p)),
  onMonitorStatus: (cb) => ipcRenderer.on("gs:monitor-status", (_ev, p) => cb(p)),
  setSignal: (opts) => ipcRenderer.invoke("gs:set-signal", opts),

  // Library tools: scaffold a block package, regenerate the catalog
  pickPath: (opts) => ipcRenderer.invoke("gs:pick-path", opts),
  writeFiles: (payload) => ipcRenderer.invoke("gs:write-files", payload),
  catalogGenerate: (opts) => ipcRenderer.invoke("gs:catalog-generate", opts),
  loadCatalog: () => ipcRenderer.invoke("gs:load-catalog"),
});
