/**
 * @fileoverview Main-process side of Bench Endoskeleton plugins: `window`
 * plugins (own BrowserWindow, own main-process module, may start processes).
 *
 * Only plugins on the ALLOW-LIST load. The list is `windowPlugins` in the
 * GUI's settings.json; without it, the bundled window plugins are allowed
 * (Graph Studio works out of the box) and installed ones are not. The user
 * changes it under Administrator -> Plugins; it takes effect at once.
 *
 * A window plugin's plugin.json names its main module ("main"): relative
 * to the Manager GUI folder for bundled plugins (web/plugins/<id>/), to the
 * plugin folder for installed ones (<userData>/plugins/<id>/). The module
 * exports register(), open(opts) and shutdown().
 */

const fs = require('fs');
const path = require('path');

const GUI_ROOT = path.join(__dirname, '..');
const BUNDLED_DIR = path.join(GUI_ROOT, 'web', 'plugins');

const records = new Map();   // id -> { id, source, dir, main, allowed, loaded, error, mod }
let settingsPath = null;

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf-8').replace(/^﻿/, ''));
}

function readSettings() {
  try { return readJson(settingsPath); } catch (e) { return {}; }
}

function writeAllowList(list) {
  const s = readSettings();
  s.windowPlugins = [...new Set(list)].sort();
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  fs.writeFileSync(settingsPath, JSON.stringify(s, null, 2), 'utf-8');
}

/** Window plugins found in a plugins folder: [{ id, dir, manifest }]. */
function scan(dir) {
  let names = [];
  try { names = fs.readdirSync(dir); } catch (e) { return []; }
  const out = [];
  for (const id of names) {
    if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) continue;
    const file = path.join(dir, id, 'plugin.json');
    if (!fs.existsSync(file)) continue;
    try {
      const manifest = readJson(file);
      if (manifest.isolation === 'window' && manifest.main) out.push({ id, dir: path.join(dir, id), manifest });
    } catch (e) {
      out.push({ id, dir: path.join(dir, id), manifest: null, error: 'plugin.json unreadable: ' + e.message });
    }
  }
  return out;
}

function load(rec) {
  if (rec.loaded || rec.error && !rec.manifest) return;
  const root = rec.source === 'bundled' ? GUI_ROOT : rec.dir;
  const mainPath = path.resolve(root, rec.main);
  if (!mainPath.startsWith(root + path.sep)) { rec.error = 'main "' + rec.main + '" is outside ' + root; return; }
  try {
    const mod = require(mainPath);
    if (typeof mod.register !== 'function' || typeof mod.open !== 'function') {
      rec.error = 'the main module must export register() and open()';
      return;
    }
    mod.register();
    rec.mod = mod;
    rec.loaded = true;
    rec.error = '';
  } catch (e) {
    rec.error = e.message;
  }
}

/**
 * Find window plugins and load the allowed ones.
 * @param {{settingsPath: string, userData: string}} opts
 * @returns {string[]} ids of the loaded plugins
 */
function registerWindowPlugins(opts) {
  settingsPath = opts.settingsPath;
  const bundled = scan(BUNDLED_DIR).map((p) => Object.assign(p, { source: 'bundled' }));
  const installed = scan(path.join(opts.userData, 'plugins')).map((p) => Object.assign(p, { source: 'installed' }));
  const s = readSettings();
  const allow = Array.isArray(s.windowPlugins) ? s.windowPlugins : bundled.map((p) => p.id);
  for (const p of bundled.concat(installed)) {   // installed wins over bundled
    records.set(p.id, { id: p.id, source: p.source, dir: p.dir, main: p.manifest && p.manifest.main,
                        manifest: p.manifest, allowed: allow.includes(p.id), loaded: false, error: p.error || '', mod: null });
  }
  for (const rec of records.values()) if (rec.allowed) load(rec);
  return [...records.values()].filter((r) => r.loaded).map((r) => r.id);
}

function list() {
  return [...records.values()].map((r) => ({ id: r.id, source: r.source, allowed: r.allowed, loaded: r.loaded, error: r.error }));
}

/** Allow or block a window plugin (saved in settings.json). */
function setAllowed(id, allowed) {
  const rec = records.get(id);
  if (!rec) return { ok: false, error: 'No window plugin "' + id + '"', plugins: list() };
  const current = [...records.values()].filter((r) => r.allowed).map((r) => r.id);
  rec.allowed = !!allowed;
  writeAllowList(allowed ? current.concat(id) : current.filter((x) => x !== id));
  if (rec.allowed) load(rec);
  else if (rec.loaded && typeof rec.mod.shutdown === 'function') {
    // Its IPC handlers stay registered (Electron cannot remove a required
    // module), but it opens nothing and its processes are stopped.
    try { rec.mod.shutdown(); } catch (e) { rec.error = 'shutdown: ' + e.message; }
  }
  return { ok: true, plugins: list() };
}

/** Open a window plugin. extra is merged into the renderer's opts (e.g. iconPath). */
function openWindowPlugin(id, opts, extra) {
  const rec = records.get(id);
  if (!rec) return { ok: false, error: 'No window plugin "' + id + '"' };
  if (!rec.allowed) return { ok: false, error: '"' + id + '" is not on the window-plugin allow-list (Administrator -> Plugins)' };
  if (!rec.loaded) return { ok: false, error: '"' + id + '" did not load: ' + (rec.error || 'unknown error') };
  try {
    const win = rec.mod.open(Object.assign({}, opts || {}, extra || {}));
    return { ok: !!win };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/** Quit: every loaded window plugin stops its child processes. */
function shutdownWindowPlugins() {
  for (const rec of records.values()) {
    if (!rec.loaded || typeof rec.mod.shutdown !== 'function') continue;
    try { rec.mod.shutdown(); } catch (e) { console.warn('[plugins] ' + rec.id + ' shutdown: ' + e.message); }
  }
}

/** The IPC the renderer uses: list, allow/block, open. */
function registerIpc(ipcMain, extra) {
  ipcMain.handle('plugin-window-list', async () => list());
  ipcMain.handle('plugin-allow', async (_e, req) => setAllowed(req && req.id, req && req.allowed));
  ipcMain.handle('plugin-open', async (_e, req) => openWindowPlugin(req && req.id, req && req.opts, extra));
}

module.exports = { registerWindowPlugins, registerIpc, openWindowPlugin, shutdownWindowPlugins, list, setAllowed, BUNDLED_DIR };
