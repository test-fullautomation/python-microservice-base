// Test project view: the Flows group's +, creating a flow, opening its
// Diagram, and (with the RobotFramework AIO fork) drawing it with Edit flow.
// Starts its own bridge on a free port and uses a temporary project folder.
'use strict';

const fs = require('fs');
const path = require('path');
const { probe, sleep } = require('./harness');

const FLOW_SRC = process.env.MB_FLOW_SRC || '';

/** The frame (plugin view) that draws a flow, or null. */
async function flowFrame(g, timeoutMs) {
  const end = Date.now() + (timeoutMs || 20000);
  while (Date.now() < end) {
    for (const f of g.win.webContents.mainFrame.framesInSubtree) {
      if (f === g.win.webContents.mainFrame) continue;
      const has = await f.executeJavaScript("!!document.querySelector('svg.flow-view')").catch(() => false);
      if (has) return f;
    }
    await sleep(250);
  }
  return null;
}

probe('GUI probe: test project flows', async (t) => {
  const bridge = await t.startBridge();
  if (!bridge) {
    t.skip('everything', 'no Python with MicroserviceBase (set MB_GUI_TEST_PYTHON)');
    return;
  }
  const root = path.join(t.tempDir('mm-gui-project-'), 'bench_tests');
  fs.mkdirSync(root);
  const init = await t.post(bridge + '/api/test-project/init', { root, runner: 'robotframework-aio' });
  t.check('project initialised through the bridge', !init.error && init.status !== 'error', init);
  fs.mkdirSync(path.join(root, 'resources'), { recursive: true });
  fs.writeFileSync(path.join(root, 'resources', 'power.resource'), '*** Keywords ***\nPower On\n    Log    on\n');
  if (FLOW_SRC) {
    await t.post(bridge + '/api/test-project/run-settings', { root, settings: { pythonpath: [FLOW_SRC] } });
  }

  const g = await t.open({ storage: { mm_test_project: root, mm_tpv_tab: 'script' }, bridge });
  await g.js("MicroserviceManager.switchMode('testproject'); true");

  t.check('Flows group offers + while it has no flow', await g.waitForSelector('[data-tpv-new-flow]', 20000));
  await g.click('[data-tpv-new-flow]');
  t.check('New flow form opens', await g.waitForSelector('#tpvFlowName', 5000));
  t.check('form lists the project resource',
          await g.js("[].some.call(document.querySelectorAll('.tpv-flow-res'), function (c) { return /power\\.resource$/.test(c.value); })"));

  // A name the runner refuses: the form says why and nothing is written.
  await g.type('#tpvFlowName', 'bad name');
  await g.click('#tpvFlowCreate');
  t.check('invalid name refused in the form',
          await g.waitFor(() => g.js("/Invalid flow name/.test((document.getElementById('tpvFlowError') || {}).textContent || '')"), 8000));
  t.check('nothing written for the refused name', !fs.existsSync(path.join(root, 'flows', 'bad name.flow.json')));

  // A good one, importing the resource.
  await g.type('#tpvFlowName', 'probe_flow');
  await g.click('.tpv-flow-res');
  await g.click('#tpvFlowCreate');
  const file = path.join(root, 'flows', 'probe_flow.flow.json');
  t.check('flow file written', await g.waitFor(async () => fs.existsSync(file), 10000));
  if (fs.existsSync(file)) {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    t.check('flow named after the file', data.flow && data.flow.name === 'Probe Flow', data.flow);
    t.check('flow imports the ticked resource',
            JSON.stringify(data.imports || {}).includes('../resources/power.resource'), data.imports);
  }
  t.check('new flow selected in the sidebar',
          await g.waitForSelector('[data-tpv-path="flows/probe_flow.flow.json"].active', 10000));
  t.check('opens on its Diagram tab',
          await g.waitForSelector('#tpvTabs [data-tpv-tab="diagram"].active', 10000));

  if (!FLOW_SRC) {
    t.skip('Diagram drawn and Edit flow', 'MB_FLOW_SRC not set (RobotFramework AIO src folder)');
    return;
  }
  const frame = await flowFrame(g, 30000);
  t.check('Diagram drawn by the flow-view plugin', !!frame);
  if (!frame) return;
  const nodes = await frame.executeJavaScript("[].map.call(document.querySelectorAll('[data-node]'), function (n) { return n.getAttribute('data-node'); })");
  t.check('the template step is drawn', nodes.includes('first'), nodes);
  t.check('Edit flow offered', await frame.executeJavaScript("!!document.querySelector('[data-act=\"edit\"]')"));
});
