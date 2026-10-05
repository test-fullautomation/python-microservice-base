// Debugging in the project view, with real input: colours of a suite, a
// breakpoint from the editor's gutter, Go to Definition (F12), Debug, the
// debug panel stopping on the breakpoint, Step Into a Python keyword (the
// built-in stepper: its line, its locals, a Python expression in the
// console), Continue to the end; with the fork, a breakpoint from a step's
// dot on the Diagram. Starts its own bridge; temporary folders only.
'use strict';

const fs = require('fs');
const path = require('path');
const { probe, sleep } = require('./harness');

const FLOW_SRC = process.env.MB_FLOW_SRC || '';
const SUITE = 'testsuites/debug_me.robot';

function write(root, rel, text) {
  const file = path.join(root, ...rel.split('/'));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

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

probe('GUI probe: test project debugging', async (t) => {
  const bridge = await t.startBridge();
  if (!bridge) {
    t.skip('everything', 'no Python with MicroserviceBase (set MB_GUI_TEST_PYTHON)');
    return;
  }
  const root = path.join(t.tempDir('mm-gui-debug-'), 'bench_tests');
  fs.mkdirSync(root);
  const init = await t.post(bridge + '/api/test-project/init', { root, runner: 'robotframework-aio' });
  t.check('project initialised', !init.error && init.status !== 'error', init);
  write(root, 'libs/mylib.py', '"""A user library."""\n\n\ndef add_numbers(a, b):\n    """Add."""\n' +
                               '    total = int(a) + int(b)\n    return total\n');
  write(root, 'resources/helpers.resource', '*** Keywords ***\nGreet\n    [Arguments]    ${who}\n    Log    hello ${who}\n');
  write(root, SUITE, '*** Settings ***\nLibrary    ../libs/mylib.py\nResource    ../resources/helpers.resource\n\n' +
                     '*** Test Cases ***\nAdds\n    ${sum}=    Add Numbers    1    2\n    Greet    bench\n' +
                     '    FOR    ${i}    IN RANGE    2\n        Log    ${i}\n    END\n');

  if (FLOW_SRC) {
    await t.post(bridge + '/api/test-project/run-settings', { root, settings: { pythonpath: [FLOW_SRC] } });
    write(root, 'flows/hello.flow.json', JSON.stringify({
      flow: { name: 'Hello', version: 1 },
      nodes: [{ id: 'start', kind: 'start' }, { id: 't', kind: 'phase', role: 'test', name: 'T' },
              { id: 'hi', kind: 'keyword', keyword: 'Log', args: ['hi'] }, { id: 'end', kind: 'end' }],
      edges: [['start', 't'], ['t', 'hi'], ['hi', 'end']] }, null, 2));
  }

  const g = await t.open({ storage: { mm_test_project: root, mm_tpv_tab: 'script' }, bridge });
  await g.js("MicroserviceManager.switchMode('testproject'); true");
  t.check('the suite is listed', await g.waitForSelector(`[data-tpv-path="${SUITE}"]`, 20000));
  await g.click(`[data-tpv-path="${SUITE}"]`);
  t.check('it opens in the editor', await g.waitForSelector('#tpvInput', 10000));

  // Colours: the keyword a line calls, control words, imports, a [Setting]-free name.
  const hl = await g.js("document.getElementById('tpvHl').innerHTML");
  t.check('a keyword call is coloured', /<span class="rf-call">Add Numbers<\/span>/.test(hl), hl.slice(0, 400));
  t.check('control words are coloured', /<span class="rf-ctl">FOR<\/span>/.test(hl) && /<span class="rf-ctl">IN RANGE<\/span>/.test(hl));
  t.check('imports are coloured', /<span class="rf-imp">\.\.\/libs\/mylib\.py<\/span>/.test(hl));
  t.check('a test name is coloured', /<span class="rf-name">Adds<\/span>/.test(hl));

  // A breakpoint from the gutter, on the Add Numbers line.
  await g.click('#tpvGutter [data-line="7"]');
  t.check('the gutter shows the breakpoint', await g.waitForSelector('#tpvGutter [data-line="7"].tpv-bp', 3000));
  const stored = JSON.parse(await g.js(`localStorage.getItem('mm_tp_breakpoints:' + ${JSON.stringify(root)}) || '{}'`));
  t.check('the breakpoint is kept for the project', JSON.stringify(stored[SUITE]) === '[7]', stored);

  // Go to Definition: F12 on "Greet" opens the resource at its definition.
  await g.js(`(function(){ var ta = document.getElementById('tpvInput'); var i = ta.value.indexOf('Greet    bench') + 2;
    ta.focus(); ta.setSelectionRange(i, i); return true; })()`);
  await g.key('F12');
  t.check('F12 opens the resource that defines the keyword',
          await g.waitFor(() => g.js("((document.querySelector('.tpv-file-head code') || {}).textContent || '') === 'resources/helpers.resource'"), 15000));
  t.check('at its line', await g.waitFor(() => g.js(`(function(){ var ta = document.getElementById('tpvInput');
    return !!ta && ta.value.slice(0, ta.selectionStart).split('\\n').length === 2; })()`), 5000));

  // Back to the suite; Debug.
  await g.click(`[data-tpv-path="${SUITE}"]`);
  t.check('Debug is offered', await g.waitForSelector('#tpvDebugFile', 10000));
  await g.click('#tpvDebugFile');
  t.check('the debug panel opens', await g.waitForSelector('#tpdPanel', 15000));
  t.check('the run stops at the breakpoint',
          await g.waitFor(() => g.js("!!document.querySelector('#tpdPanel .tpd-paused') && /debug_me\\.robot:7/.test(document.getElementById('tpdStack').textContent)"), 60000));
  t.check('the source shows the line', await g.js("(document.querySelector('#tpdCode .tpd-current') || {}).getAttribute && document.querySelector('#tpdCode .tpd-current').getAttribute('data-line') === '7'"));

  // Step Into the Python keyword: the built-in stepper.
  await g.click('[data-tpd="stepIn"]');
  t.check('Step Into stops in the Python function',
          await g.waitFor(() => g.js("/libs\\/mylib\\.py:6/.test((document.querySelector('#tpdStack li') || {}).textContent || '')"), 30000));
  t.check('the Python source is coloured, no markup shows',
          await g.js("!!document.querySelector('#tpdCode .rf-set') && !/class=/.test(document.getElementById('tpdCode').textContent)"));
  await g.click('#tpdVars [data-ref]');
  t.check('its locals are shown',
          await g.waitFor(() => g.js("/a\\s*'?1'?/.test(document.getElementById('tpdVars').textContent) && /b/.test(document.getElementById('tpdVars').textContent)"), 10000));
  await g.type('#tpdInput', 'int(a) + int(b) * 10');
  await g.key('Enter');
  t.check('the console evaluates Python there',
          await g.waitFor(() => g.js("/^21$/m.test(Array.from(document.querySelectorAll('#tpdConsole .tpd-out')).map(function (e) { return e.textContent; }).join('\\n'))"), 10000));

  // A look at the panel (test/gui/output/): only a shown window can be captured.
  if (process.env.MB_GUI_TEST_SHOW === '1') await g.screenshot('debug-paused-in-python');
  await g.click('[data-tpd="continue"]');
  t.check('Continue runs to the end', await g.waitFor(() => g.js("/pass/i.test((document.getElementById('tprBadge') || {}).textContent || '')"), 60000));

  if (!FLOW_SRC) {
    t.skip('a breakpoint from the Diagram', 'MB_FLOW_SRC not set (RobotFramework AIO src folder)');
    return;
  }
  t.check('the flow is listed', await g.waitForSelector('[data-tpv-path="flows/hello.flow.json"]', 15000));
  await g.click('[data-tpv-path="flows/hello.flow.json"]');
  t.check('its Diagram tab', await g.waitForSelector('#tpvTabs [data-tpv-tab="diagram"]', 10000));
  await g.click('#tpvTabs [data-tpv-tab="diagram"]');
  const frame = await flowFrame(g, 30000);
  t.check('the Diagram is drawn', !!frame);
  if (!frame) return;
  t.check('each step has a breakpoint dot', await frame.executeJavaScript("!!document.querySelector('[data-node=\"hi\"] circle.fv-bp')"));
  await frame.executeJavaScript("document.querySelector('[data-node=\"hi\"] circle.fv-bp').dispatchEvent(new MouseEvent('click', { bubbles: true })); true");
  const flowLine = fs.readFileSync(path.join(root, 'flows', 'hello.flow.json'), 'utf8').split('\n').findIndex((l) => l.includes('"hi"')) + 1;
  t.check('the dot sets a breakpoint on the step\'s line', await g.waitFor(async () => {
    const bps = JSON.parse(await g.js(`localStorage.getItem('mm_tp_breakpoints:' + ${JSON.stringify(root)}) || '{}'`));
    return JSON.stringify(bps['flows/hello.flow.json']) === JSON.stringify([flowLine]);
  }, 5000));
  t.check('the Diagram shows it', await (async () => {
    const end = Date.now() + 5000;
    while (Date.now() < end) {
      if (await frame.executeJavaScript("!!document.querySelector('[data-node=\"hi\"].fv-has-bp')")) return true;
      await sleep(200);
    }
    return false;
  })());
});
