#!/usr/bin/env node
/**
 * Run the GUI probes: every test/gui/test_gui_*.js in its own Electron
 * process, one after the other.
 *
 *   node test/gui/run.js                 all probes
 *   node test/gui/run.js view_roles      probes whose name contains "view_roles"
 *
 * MB_GUI_TEST_PYTHON: interpreter with MicroserviceBase for probes that start
 * a bridge (default "python"); without one those probes skip what needs it.
 * MB_FLOW_SRC: a RobotFramework AIO src folder, for the flow Diagram checks.
 * MB_GUI_TEST_SHOW=1 shows the windows.
 */
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const here = __dirname;
const gui = path.resolve(here, '..', '..');
const electron = require(path.join(gui, 'node_modules', 'electron'));   // path of the binary
const filter = process.argv[2] || '';

const probes = fs.readdirSync(here)
  .filter((f) => /^test_gui_.*\.js$/.test(f) && f.includes(filter))
  .sort();

let failed = 0;
for (const f of probes) {
  const started = Date.now();
  const r = spawnSync(electron, [path.join(here, f)], { cwd: gui, stdio: 'inherit', timeout: 10 * 60 * 1000 });
  const secs = ((Date.now() - started) / 1000).toFixed(1);
  const ok = r.status === 0;
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${f} (${secs} s)\n`);
}
console.log(`${probes.length - failed} of ${probes.length} probe file(s) passed`);
process.exit(failed ? 1 : 0);
