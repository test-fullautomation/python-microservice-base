// Test projects with another runner than Robot Framework: the Initialize
// dialog lists the runners with their own structure and preselects the one
// whose files the folder holds; the project view takes its groups, words,
// suffixes, run command and syntax check from the project's runner
// (Temporal, Python SDK). Starts its own bridge; temporary folders only.
'use strict';

const fs = require('fs');
const path = require('path');
const { ipcMain } = require('electron');
const { probe } = require('./harness');

// The folder the "Open test project" dialog answers with (set below).
let picked = '';
ipcMain.handle('show-open-dialog', async () => ({ canceled: !picked, filePaths: picked ? [picked] : [] }));

function write(root, rel, text) {
  const file = path.join(root, ...rel.split('/'));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

probe('GUI probe: test project runners', async (t) => {
  const bridge = await t.startBridge();
  if (!bridge) {
    t.skip('everything', 'no Python with MicroserviceBase (set MB_GUI_TEST_PYTHON)');
    return;
  }
  const root = path.join(t.tempDir('mm-gui-runners-'), 'workflow_tests');
  write(root, 'legacy/old_flow.py', 'from temporalio import workflow\n');
  picked = root;

  const g = await t.open({ bridge });
  // A probe window is never painted, so CSS transitions never end and a
  // Bootstrap modal would never finish hiding; without them it does at once.
  await g.js("var st = document.createElement('style'); st.textContent = '*, *::before, *::after { transition: none !important; }'; document.head.appendChild(st); true");
  await g.js("MicroserviceManager.switchMode('testproject'); true");
  t.check('no project yet: the view offers to open one', await g.waitForSelector('#tpvOpen', 15000));
  await g.click('#tpvOpen');

  // ---- Initialize: the runners describe themselves
  t.check('Initialize dialog lists the runners', await g.waitForSelector('#tpRunner', 20000));
  const ids = await g.js("[].map.call(document.querySelectorAll('#tpRunner option'), function (o) { return o.value; })");
  t.check('Robot Framework AIO and Temporal offered',
          ids.includes('robotframework-aio') && ids.includes('temporal-python'), ids);
  t.check('the runner whose files the folder holds is preselected',
          await g.js("document.getElementById('tpRunner').value") === 'temporal-python');
  t.check('what was found is named',
          await g.js("/1 Python file using temporalio/.test(document.getElementById('testProjectModalBody').textContent)"));
  t.check("structure is the runner's own",
          await g.js("/conftest\\.py/.test(document.getElementById('tpRunnerTree').textContent)"));
  await g.js("var s = document.getElementById('tpRunner'); s.value = 'robotframework-aio'; s.dispatchEvent(new Event('change')); true");
  t.check('choosing another runner shows its structure',
          await g.js("/robot_config\\.jsonp/.test(document.getElementById('tpRunnerTree').textContent) && !/conftest/.test(document.getElementById('tpRunnerTree').textContent)"));
  await g.js("var s = document.getElementById('tpRunner'); s.value = 'temporal-python'; s.dispatchEvent(new Event('change')); true");
  await g.click('#btnTestProjectApply');
  const manifest = path.join(root, 'testproject.json');
  t.check('initialized with the chosen runner',
          await g.waitFor(async () => fs.existsSync(manifest) &&
                          JSON.parse(fs.readFileSync(manifest, 'utf8')).runner === 'temporal-python', 10000));
  t.check("the runner's starter files are written", fs.existsSync(path.join(root, 'conftest.py')));

  // ---- project view in the runner's words
  write(root, 'workflows/order.py', 'from temporalio import workflow\n');
  write(root, 'activities/bench/power.py', 'from temporalio import activity\n');
  await g.js("MicroserviceManager.switchMode('testproject'); true");
  if (await g.waitForSelector('#tpvRefresh', 15000)) await g.click('#tpvRefresh');
  t.check('groups titled by the runner',
          await g.waitFor(() => g.js("(function(){ var t = [].map.call(document.querySelectorAll('.tpv-group-title > span:first-child'), function (e) { return e.textContent.trim(); });" +
                                     " return t.indexOf('Tests') >= 0 && t.indexOf('Workflows') >= 0 && t.indexOf('Activities') >= 0 && t.indexOf('Suites') < 0; })()"), 15000));

  await g.click('[data-tpv-new-suite]');
  t.check('New test form, not New suite', await g.waitFor(() => g.js("/New test/.test((document.querySelector('.tpv-file-head strong') || {}).textContent || '')"), 5000));
  t.check('the suffix is the runner\'s',
          await g.js("[].some.call(document.querySelectorAll('.tpv-new-suite .input-group-text'), function (e) { return e.textContent === '_test.py'; })"));
  await g.type('#tpvSuiteName', 'probe');
  await g.click('#tpvSuiteCreate');
  const created = path.join(root, 'tests', 'probe_test.py');
  t.check('test file created in the tests folder', await g.waitFor(async () => fs.existsSync(created), 10000));

  // The new file opens in the editor: run command and syntax check are the runner's.
  t.check('opens in the editor', await g.waitForSelector('#tpvInput', 10000));
  t.check('Run offered for a test file', await g.waitForSelector('#tpvRunFile', 5000));
  t.check('Run command is pytest',
          await g.js("(document.getElementById('tpvCopyRun') || {getAttribute: function(){return ''}}).getAttribute('data-run-hint')") ===
          'python -m pytest tests/probe_test.py');
  await g.type('#tpvInput', 'def broken(:\n    pass\n');
  await g.click('#tpvCheck');
  t.check('Python syntax error reported by the runner',
          await g.waitFor(() => g.js("/SyntaxError/.test((document.getElementById('tpvProblems') || {}).textContent || '')"), 8000));
});
