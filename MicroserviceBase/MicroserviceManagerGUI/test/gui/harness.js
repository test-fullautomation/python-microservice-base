/**
 * @fileoverview GUI probe harness: drive the real Manager GUI in Electron.
 *
 * A probe is an Electron main script (test/gui/test_gui_*.js). It opens
 * web/index.html in a BrowserWindow with the real preload, so the page is
 * the one users get, and drives it the way a user does: clicks and typing
 * through webContents.sendInputEvent (not element.click()), so focus, hit
 * testing and pointer handlers all take part.
 *
 * Isolation, so a probe can run on a developer's PC or a bench PC:
 *   - userData is a fresh temporary folder: the user's settings, local
 *     storage and plugins are never read or written;
 *   - a probe that needs the bridge starts its own on a free port
 *     (startBridge) and stops it at the end; nothing is sent to a bridge,
 *     Consul or Nomad the user is running;
 *   - test projects live in temporary folders.
 *
 *   const h = require('./harness');
 *   h.probe('view roles', async (t) => {
 *     const g = await t.open({ query: { view: 'user' } });
 *     t.check('Developer tab hidden', !(await g.visible('#btnDevTools')));
 *   });
 *
 * Output follows test/endo: one line per check, then "N passed, M failed",
 * exit code 1 on any failure. A failed check saves a screenshot under
 * test/gui/output/. MB_GUI_TEST_SHOW=1 shows the window.
 */
'use strict';

const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const http = require('http');

const GUI = path.resolve(__dirname, '..', '..');
const OUT = path.join(__dirname, 'output');

// Before app ready: a throw-away profile, and windows that keep painting
// while covered (otherwise transitions freeze and screenshots come out empty).
const USER_DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'mm-gui-probe-'));
app.setPath('userData', USER_DATA);
app.commandLine.appendSwitch('disable-renderer-backgrounding');
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion');
process.env.DASGUI_IS_PACKAGED = '0';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The page talks to electron/main.js through the preload. A probe runs only
// the page, so the main-process calls the GUI makes on its own get neutral
// answers here: no window plugins, nothing opened, dialogs cancelled.
// (Probes of window plugins or native dialogs need the real main process.)
const MAIN_STUBS = {
  'plugin-window-list': () => [],
  'plugin-allow': () => ({ ok: false, error: 'not available in a GUI probe' }),
  'plugin-open': () => ({ ok: false, error: 'not available in a GUI probe' }),
  'open-graph-studio': () => ({ ok: false, error: 'not available in a GUI probe' }),
  'show-message-box': () => ({ response: 0 }),
  'show-open-dialog': () => ({ canceled: true, filePaths: [] }),
};
app.whenReady().then(() => {
  for (const [channel, answer] of Object.entries(MAIN_STUBS)) {
    try { ipcMain.handle(channel, async () => answer()); } catch (e) { /* a probe registered its own */ }
  }
});

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function httpGet(url, timeoutMs) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs || 3000 }, (res) => {
      res.resume();
      resolve(res.statusCode);
    });
    req.on('error', () => resolve(0));
    req.on('timeout', () => { req.destroy(); resolve(0); });
  });
}

function httpPostJson(url, body) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': data.length } }, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { text += c; });
      res.on('end', () => { try { resolve(JSON.parse(text)); } catch (e) { reject(new Error(text)); } });
    });
    req.on('error', reject);
    req.end(data);
  });
}

/** Python that runs the bridge: MB_GUI_TEST_PYTHON, else "python". */
function bridgePython() {
  const py = process.env.MB_GUI_TEST_PYTHON || 'python';
  const ok = spawnSync(py, ['-c', 'import MicroserviceBase, fastapi'], { encoding: 'utf8', timeout: 60000 });
  return ok.status === 0 ? py : null;
}

class Gui {
  constructor(win, probe) {
    this.win = win;
    this.probe = probe;
  }

  /** Run code in the page; errors come back as { __error }. */
  js(code) {
    return this.win.webContents.executeJavaScript(code, true)
      .catch((e) => ({ __error: String(e && e.message || e) }));
  }

  /** Poll fn() until it resolves true; false after timeoutMs. */
  async waitFor(fn, timeoutMs) {
    const end = Date.now() + (timeoutMs || 15000);
    while (Date.now() < end) {
      if ((await fn()) === true) return true;
      await sleep(150);
    }
    return false;
  }

  waitForSelector(sel, timeoutMs) {
    return this.waitFor(() => this.visible(sel), timeoutMs);
  }

  /** The element exists, is displayed and has a size. */
  visible(sel) {
    return this.js(`(function(){ var e = document.querySelector(${JSON.stringify(sel)});
      if (!e) return false; var r = e.getBoundingClientRect(); var s = getComputedStyle(e);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; })()`);
  }

  /** Click the element's centre with real mouse events. */
  async click(sel) {
    const at = await this.js(`(function(){ var e = document.querySelector(${JSON.stringify(sel)});
      if (!e) return null; e.scrollIntoView({ block: 'center' }); var r = e.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) }; })()`);
    if (!at || at.__error) throw new Error('no element to click: ' + sel);
    const wc = this.win.webContents;
    wc.sendInputEvent({ type: 'mouseMove', x: at.x, y: at.y });
    wc.sendInputEvent({ type: 'mouseDown', x: at.x, y: at.y, button: 'left', clickCount: 1 });
    wc.sendInputEvent({ type: 'mouseUp', x: at.x, y: at.y, button: 'left', clickCount: 1 });
    await sleep(120);
  }

  /** Focus the field, select its text and type over it. */
  async type(sel, text) {
    await this.click(sel);
    await this.js(`(function(){ var e = document.querySelector(${JSON.stringify(sel)}); e.select && e.select(); return true; })()`);
    this.win.webContents.insertText(text);
    await sleep(80);
  }

  async key(keyCode) {
    this.win.webContents.sendInputEvent({ type: 'keyDown', keyCode });
    // A real keyboard also types a character for these; a focused button
    // activates on it, as it does for a user.
    const ch = { Enter: '\r', Return: '\r', Space: ' ' }[keyCode];
    if (ch) this.win.webContents.sendInputEvent({ type: 'char', keyCode: ch });
    this.win.webContents.sendInputEvent({ type: 'keyUp', keyCode });
    await sleep(80);
  }

  async screenshot(name) {
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.join(OUT, name.replace(/[^A-Za-z0-9_.-]+/g, '_') + '.png');
    fs.writeFileSync(file, (await this.win.webContents.capturePage()).toPNG());
    return file;
  }
}

class Probe {
  constructor(name) {
    this.name = name;
    this.passed = 0;
    this.failed = 0;
    this.windows = [];
    this.children = [];
    this.gui = null;
    this.rendererErrors = [];
  }

  /**
   * Open the GUI. opts.query: URL query (e.g. { view: 'user' });
   * opts.storage: localStorage entries set before the app starts;
   * opts.bridge: base URL of a bridge to talk to (from startBridge).
   */
  async open(opts) {
    opts = opts || {};
    const win = new BrowserWindow({
      show: process.env.MB_GUI_TEST_SHOW === '1', width: 1500, height: 950,
      webPreferences: { contextIsolation: true, sandbox: false, backgroundThrottling: false,
                        preload: path.join(GUI, 'electron', 'preload.js') },
    });
    this.windows.push(win);
    win.webContents.on('console-message', (e, level, message) => {
      if (level >= 3) this.rendererErrors.push(message);
    });
    const page = path.join(GUI, 'web', 'index.html');
    const query = opts.query || {};
    await win.loadFile(page, { query });
    if (opts.storage && Object.keys(opts.storage).length) {
      await win.webContents.executeJavaScript(
        `(function(s){ Object.keys(s).forEach(function(k){ localStorage.setItem(k, s[k]); }); return true; })(${JSON.stringify(opts.storage)})`);
      await win.loadFile(page, { query });
    }
    const g = new Gui(win, this);
    await g.waitFor(() => g.js('!!(window.MicroserviceManager && window.MicroserviceManager.switchMode)'), 20000);
    await sleep(600);
    if (opts.bridge) {
      // The isolated bridge runs on its own port; the desktop app's default
      // ("file://" -> localhost:<settings.bridgePort>) would reach the
      // user's bridge instead.
      await g.js(`window.MicroserviceManager.serviceClient.apiUrl = ${JSON.stringify(opts.bridge)}; true`);
    }
    this.gui = g;
    return g;
  }

  /**
   * Start a bridge on a free port for this probe. Returns its base URL, or
   * null when no Python with MicroserviceBase is available (the probe then
   * skips what needs it).
   */
  async startBridge() {
    const py = bridgePython();
    if (!py) return null;
    const port = await freePort();
    const child = spawn(py, [path.join(GUI, 'python', 'launcher.py'), '--bridge-port', String(port)], {
      cwd: path.join(GUI, 'python'), stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
      env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1', PYTHONUTF8: '1' }),
    });
    let log = '';
    child.stdout.on('data', (d) => { log += d; });
    child.stderr.on('data', (d) => { log += d; });
    this.children.push(child);
    const base = `http://127.0.0.1:${port}`;
    const end = Date.now() + 60000;
    while (Date.now() < end) {
      if (child.exitCode !== null) throw new Error('bridge exited at start:\n' + log.slice(-2000));
      if ((await httpGet(base + '/docs')) === 200) return base;
      await sleep(400);
    }
    throw new Error('bridge did not start within 60 s:\n' + log.slice(-2000));
  }

  post(url, body) { return httpPostJson(url, body); }

  tempDir(prefix) { return fs.mkdtempSync(path.join(os.tmpdir(), prefix || 'mm-gui-probe-')); }

  check(label, ok, detail) {
    if (ok) {
      this.passed++;
      console.log('  ok    ' + label);
    } else {
      this.failed++;
      console.log('  FAIL  ' + label + (detail !== undefined ? '  -- ' + JSON.stringify(detail) : ''));
      if (this.gui) this.gui.screenshot(this.name + '-' + label).catch(() => {});
    }
    return ok;
  }

  skip(label, why) { console.log('  skip  ' + label + '  -- ' + why); }

  async close() {
    for (const w of this.windows) { try { w.destroy(); } catch (e) { /* gone */ } }
    for (const c of this.children) {
      if (c.exitCode !== null) continue;
      if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(c.pid), '/T', '/F'], { stdio: 'ignore' });
      else c.kill('SIGTERM');
    }
    try { fs.rmSync(USER_DATA, { recursive: true, force: true }); } catch (e) { /* in use */ }
  }
}

/** Define and run one probe file: setup, checks, summary, exit code. */
function probe(name, body) {
  app.whenReady().then(async () => {
    const t = new Probe(name);
    console.log(name);
    try {
      await body(t);
    } catch (e) {
      t.failed++;
      console.log('  FAIL  ' + (e && e.stack || e));
      if (t.gui) await t.gui.screenshot(name + '-error').catch(() => {});
    }
    const unexpected = t.rendererErrors.filter((m) => !/Failed to fetch|ERR_CONNECTION_REFUSED|favicon/.test(m));
    t.check('no renderer errors', unexpected.length === 0, unexpected.slice(0, 5));
    await t.close();
    console.log(`${t.passed} passed, ${t.failed} failed`);
    app.exit(t.failed ? 1 : 0);
  });
}

module.exports = { probe, sleep };
