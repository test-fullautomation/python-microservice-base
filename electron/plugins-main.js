/**
 * @fileoverview Main-process side of Bench Endoskeleton plugins: loads the
 * bundled `window` plugins (own BrowserWindow, own main-process module).
 *
 * A window plugin's plugin.json names its main module ("main"), relative
 * to the Manager GUI folder; the module exports register(), open(opts) and
 * shutdown(). Only BUNDLED plugins (web/plugins/<id>/) get here: installed
 * plugins cannot run main-process code until the allow-list (milestone M5).
 */

const fs = require('fs');
const path = require('path');

const GUI_ROOT = path.join(__dirname, '..');
const BUNDLED_DIR = path.join(GUI_ROOT, 'web', 'plugins');

const loaded = new Map();   // plugin id -> { manifest, mod }

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf-8').replace(/^﻿/, ''));
}

/** Load and register every bundled window plugin. Returns their ids. */
function registerWindowPlugins() {
  let ids = [];
  try {
    ids = fs.readdirSync(BUNDLED_DIR).filter((d) => fs.existsSync(path.join(BUNDLED_DIR, d, 'plugin.json')));
  } catch (e) {
    return [];
  }
  for (const id of ids) {
    let manifest;
    try { manifest = readJson(path.join(BUNDLED_DIR, id, 'plugin.json')); }
    catch (e) { console.warn('[plugins] ' + id + ': plugin.json unreadable: ' + e.message); continue; }
    if (manifest.isolation !== 'window' || !manifest.main) continue;
    const mainPath = path.resolve(GUI_ROOT, manifest.main);
    if (!mainPath.startsWith(GUI_ROOT + path.sep)) {
      console.warn('[plugins] ' + id + ': main ' + manifest.main + ' is outside the GUI folder; not loaded');
      continue;
    }
    try {
      const mod = require(mainPath);
      if (typeof mod.register !== 'function' || typeof mod.open !== 'function') {
        console.warn('[plugins] ' + id + ': main module must export register() and open()');
        continue;
      }
      mod.register();
      loaded.set(manifest.plugin || id, { manifest, mod });
    } catch (e) {
      console.warn('[plugins] ' + id + ': ' + e.message);
    }
  }
  return [...loaded.keys()];
}

/** Open a window plugin. extra is merged into the renderer's opts (e.g. iconPath). */
function openWindowPlugin(id, opts, extra) {
  const p = loaded.get(id);
  if (!p) return { ok: false, error: 'No window plugin "' + id + '" is loaded' };
  try {
    const win = p.mod.open(Object.assign({}, opts || {}, extra || {}));
    return { ok: !!win };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/** Quit: every window plugin stops its child processes. */
function shutdownWindowPlugins() {
  for (const [id, p] of loaded) {
    try { if (typeof p.mod.shutdown === 'function') p.mod.shutdown(); }
    catch (e) { console.warn('[plugins] ' + id + ' shutdown: ' + e.message); }
  }
}

module.exports = { registerWindowPlugins, openWindowPlugin, shutdownWindowPlugins, BUNDLED_DIR };
