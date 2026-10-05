// Pause, resume, stop with a checkpoint, continue, and step mode of a flow run,
// in the Runs view with real input (the fork's flow control). Needs the
// RobotFramework AIO fork with robot/flow/control.py (MB_FLOW_SRC). Starts
// its own bridge; temporary folders only.
'use strict';

const fs = require('fs');
const path = require('path');
const { probe } = require('./harness');

const FLOW_SRC = process.env.MB_FLOW_SRC || '';
const FLOW = 'flows/cycle.flow.json';

function write(root, rel, text) {
  const file = path.join(root, ...rel.split('/'));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

probe('GUI probe: pause and resume a flow', async (t) => {
  if (!FLOW_SRC || !fs.existsSync(path.join(FLOW_SRC, 'robot', 'flow', 'control.py'))) {
    t.skip('everything', 'MB_FLOW_SRC does not name a fork with robot.flow.control');
    return;
  }
  const bridge = await t.startBridge();
  if (!bridge) {
    t.skip('everything', 'no Python with MicroserviceBase (set MB_GUI_TEST_PYTHON)');
    return;
  }
  const root = path.join(t.tempDir('mm-gui-pause-'), 'bench_tests');
  fs.mkdirSync(root);
  await t.post(bridge + '/api/test-project/init', { root, runner: 'robotframework-aio' });
  await t.post(bridge + '/api/test-project/run-settings', { root, settings: { pythonpath: [FLOW_SRC] } });
  write(root, FLOW, JSON.stringify({
    flow: { name: 'Cycle', version: 1 },
    nodes: [{ id: 'start', kind: 'start' }, { id: 'test', kind: 'phase', role: 'test', name: 'Cycle' },
            { id: 'loop', kind: 'loop', max_loops: 30 },
            { id: 'tick', kind: 'keyword', keyword: 'Log', args: ['tick'] },
            { id: 'wait', kind: 'keyword', keyword: 'Sleep', args: ['0.25s'] }, { id: 'end', kind: 'end' }],
    edges: [['start', 'test'], ['test', 'loop'], { from: 'loop', to: 'tick', label: 'body' }, ['tick', 'wait'],
            { from: 'wait', to: 'loop', label: 'next' }, { from: 'loop', to: 'end', label: 'done' }] }, null, 2));

  const g = await t.open({ storage: { mm_test_project: root, mm_tpv_tab: 'script' }, bridge });
  // Probe windows are never painted: without transitions a modal hides at once.
  await g.js("var st = document.createElement('style'); st.textContent = '*, *::before, *::after { transition: none !important; }'; document.head.appendChild(st); true");
  await g.js("MicroserviceManager.switchMode('testproject'); true");
  await g.waitForSelector(`[data-tpv-path="${FLOW}"]`, 20000);
  await g.click(`[data-tpv-path="${FLOW}"]`);
  t.check('Run is offered', await g.waitForSelector('#tpvRunFile', 10000));
  await g.click('#tpvRunFile');
  t.check('the Run dialog offers step mode for a flow', await g.waitForSelector('#tprStep', 5000));
  await g.click('#btnTestProjectApply');

  const flowText = () => g.js("(document.getElementById('tprMeta') || {}).textContent || ''");
  t.check('a running flow offers Pause', await g.waitForSelector('#tprPause', 30000));
  t.check('its state is shown', await g.waitFor(async () => /flow running/.test(await flowText()), 10000), await flowText());
  await g.click('#tprPause');
  t.check('Pause holds it: Resume is offered', await g.waitForSelector('#tprResume', 15000));
  t.check('and it says where', await g.waitFor(async () => /flow paused · phase Cycle, loop loop iteration \d+/.test(await flowText()), 10000),
          await flowText());
  // A look (test/gui/output/): only a shown window can be captured.
  if (process.env.MB_GUI_TEST_SHOW === '1') await g.screenshot('flow-paused');
  await g.click('#tprResume');
  t.check('Resume: Pause is offered again', await g.waitForSelector('#tprPause', 15000));
  t.check('the Stop button says it keeps a checkpoint',
          /checkpoint/.test(await g.js("document.getElementById('tprStop').title")));
  await g.click('#tprStop');
  t.check('Stop ends it UNKNOWN', await g.waitFor(() => g.js("/unknown/i.test((document.getElementById('tprBadge') || {}).textContent || '')"), 60000));
  t.check('Continue from checkpoint is offered', await g.waitForSelector('#tprContinue', 10000));
  const firstRun = await g.js("(document.getElementById('tprTarget') || {}).textContent");
  await g.click('#tprContinue');
  t.check('the continued run says what it continues',
          await g.waitFor(async () => /continues \d{8}-\d{6}/.test(await flowText()), 20000), await flowText());
  t.check('and passes', await g.waitFor(() => g.js("/pass/i.test((document.getElementById('tprBadge') || {}).textContent || '')"), 90000));
  t.check('same file', firstRun === await g.js("(document.getElementById('tprTarget') || {}).textContent"));

  // Step mode: Next step goes one step at a time.
  await g.click(`[data-tpv-path="${FLOW}"]`);
  await g.waitForSelector('#tpvRunFile', 10000);
  await g.click('#tpvRunFile');
  await g.waitForSelector('#tprStep', 5000);
  await g.click('#tprStep');
  await g.click('#btnTestProjectApply');
  t.check('step mode holds before the first step: Next step',
          await g.waitFor(() => g.js("/Next step/.test((document.getElementById('tprResume') || {}).textContent || '')"), 30000));
  t.check('the meta line says step mode', /step mode/.test(await flowText()));
  await g.click('#tprResume');
  t.check('after one step it holds again',
          await g.waitFor(() => g.js("!!document.getElementById('tprResume')"), 15000));
  await g.click('#tprStop');
  t.check('and stops', await g.waitFor(() => g.js("/unknown|pass|fail/i.test((document.getElementById('tprBadge') || {}).textContent || '')"), 60000));
});
