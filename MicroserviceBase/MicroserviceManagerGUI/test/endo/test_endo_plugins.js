// Plugins (milestone M4): the bundled plugins lint clean, the plugin rules
// catch what they should, a plugin kind's schema and needs reach component
// linting, the charts plugin's series maths, the flow-view layout and the
// robot-grid markup.
//   node test/endo/test_endo_plugins.js      (from the GUI folder)
'use strict';

const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const C = require('../../web/js/endo/contract/lint.js');

const GUI = path.join(__dirname, '..', '..');
const DIR = path.join(GUI, 'web', 'js', 'endo', 'contract');
const PLUGINS = path.join(GUI, 'web', 'plugins');
const pluginSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'plugin.schema.json'), 'utf-8'));
const componentSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'component.schema.json'), 'utf-8'));
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf-8'));

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}
const clone = (o) => JSON.parse(JSON.stringify(o));
const lintP = (m) => C.lintPlugin(m, { schema: pluginSchema });
const rules = (issues, sev) => issues.filter((i) => !sev || i.severity === sev).map((i) => i.rule);

(async () => {
  // ---------- the bundled plugins ----------
  const index = readJson(path.join(PLUGINS, 'index.json'));
  check('index lists the six reference plugins',
        JSON.stringify(index.plugins.slice().sort()) === JSON.stringify(['charts', 'flow-view', 'graph-studio', 'robot-gen', 'robot-grid', 'test-project']), index.plugins);
  const manifests = {};
  index.plugins.forEach((id) => {
    const m = manifests[id] = readJson(path.join(PLUGINS, id, 'plugin.json'));
    check('bundled ' + id + ' lints clean', lintP(m).length === 0, lintP(m).map(C.formatIssue));
    check('bundled ' + id + ': id matches its folder', m.plugin === id);
    ((m.contributes && m.contributes.kinds) || []).concat((m.contributes && m.contributes['drawer.tabs']) || [],
                                                     (m.contributes && m.contributes['file.views']) || [])
      .filter((e) => e.entry).forEach((e) => {
        check('bundled ' + id + ': entry ' + e.entry + ' exists', fs.existsSync(path.join(PLUGINS, id, e.entry)));
      });
    check('bundled ' + id + ' has a README', fs.existsSync(path.join(PLUGINS, id, 'README.md')));
  });
  const gs = manifests['graph-studio'];
  check('graph-studio: the main module exports the window-plugin interface', (() => {
    const src = fs.readFileSync(path.join(GUI, gs.main), 'utf-8');
    return /register:\s*registerGraphStudioIpc/.test(src) && /open:\s*openGraphStudio/.test(src) && /shutdown:\s*shutdownGraphStudio/.test(src);
  })());

  // ---------- plugin rules ----------
  const P = clone(manifests['robot-gen']);
  {
    const a = clone(P); a.contributes.commands[0].id = 'other.run'; a.contributes['ribbon.groups'][0].commands[0].id = 'other.run';
    check('P2: command ids start with the plugin id', rules(lintP(a), 'error').includes('P2'), lintP(a));
    const b = clone(P); b.contributes['ribbon.groups'][0].commands[0].id = 'robot-gen.nope';
    check('S: a ribbon command must name a declared command', lintP(b).some((i) => /not in contributes.commands/.test(i.message)));
    const c = clone(P); c.contributes.commands.push(clone(c.contributes.commands[0]));
    check('P2: duplicate command ids', lintP(c).some((i) => /duplicate command id/.test(i.message)));
    const d = clone(P); d.contributes.commands[0] = { id: 'robot-gen.run', title: 'x', window: true };
    check('S: only window plugins open a window', lintP(d).some((i) => /only window plugins/.test(i.message)));
    const e = clone(P); e.contributes.commands[0] = { id: 'robot-gen.run', title: 'x' };
    check('S: a command needs entry, shell or window', rules(lintP(e), 'error').includes('S'));
    const f = clone(manifests.charts); f.contributes.kinds[0].kind = 'table';
    check('P2: a plugin cannot redefine a core kind', lintP(f).some((i) => /is a core kind/.test(i.message)));
    const g = clone(manifests.charts); g.contributes.kinds[0].needs = ['telemetry.raw'];
    check('R1: kinds need known capabilities', rules(lintP(g), 'error').includes('R1'));
    const h = clone(manifests['test-project']); delete h.contributes.navigators[0].shell;
    check('S: a navigator needs entry or shell', rules(lintP(h), 'error').includes('S'));
    const i2 = clone(P); i2.contributes.renderers = [{ id: 'x', title: 'X', entry: 'x.js' }];
    check('K: renderers warn until M5', lintP(i2).some((x) => x.rule === 'K' && x.severity === 'warn'));
    const j = clone(P); j.requires.shell = '^3.0';
    check('R9: plugins version against the shell', rules(lintP(j), 'error').includes('R9'));
    const fv = manifests['flow-view'];
    const k = clone(fv); delete k.contributes['file.views'][0].entry; k.contributes['file.views'][0].shell = 'flow';
    check('S: a file view is a module', lintP(k).some((x) => x.severity === 'error' && /give it an entry/.test(x.message)));
    const l = clone(fv); l.contributes['file.views'][0].for = [];
    check('S: a file view names the view types it draws', lintP(l).some((x) => x.severity === 'error' && /view types/.test(x.message)));
    const m2 = clone(fv); m2.contributes['file.views'].push(clone(m2.contributes['file.views'][0]));
    check('P2: duplicate file view ids', lintP(m2).some((x) => /duplicate id/.test(x.message)));
    const n2 = clone(fv); n2.isolation = 'schema';
    check('P: schema plugins cannot ship a file view module', rules(lintP(n2), 'error').includes('P'));
  }

  // ---------- a plugin kind's schema and needs, in component linting ----------
  const kinds = {};
  manifests.charts.contributes.kinds.forEach((k) => { kinds[k.kind] = { plugin: 'charts', schema: k.schema, needs: k.needs }; });
  const monitor = readJson(path.join(__dirname, 'fixtures', 'bench', 'services', 'SignalMonitor1.0.0', 'component.json'));
  const withCharts = C.lintComponent(monitor, { schema: componentSchema, kinds });
  check('with charts active, the signal-strip fixture lints clean', withCharts.length === 0, withCharts.map(C.formatIssue));
  const without = C.lintComponent(monitor, { schema: componentSchema, knownPluginKinds: { 'signal-strip': 'charts' } });
  check('with charts off, the same tile only warns (K) and names the plugin',
        !C.hasErrors(without) && without.some((i) => i.rule === 'K' && /charts plugin/.test(i.message)), without.map(C.formatIssue));
  {
    const m = clone(monitor); delete m.tiles[0].signals;
    check('the kind schema is enforced (signals required)', C.lintComponent(m, { schema: componentSchema, kinds })
      .some((i) => i.rule === 'S' && /signals/.test(i.path)));
    const n = clone(monitor); n.requires.capabilities = [];
    check('a kind\'s needs are enforced (R1)', C.lintComponent(n, { schema: componentSchema, kinds })
      .some((i) => i.rule === 'R1' && /signal-strip needs signals.subscribe|reads signals/.test(i.message)));
    const z = clone(monitor); z.tiles[0].window = '0s';
    check('a zero window is refused by the kind schema', C.lintComponent(z, { schema: componentSchema, kinds })
      .some((i) => i.rule === 'S' && /window/.test(i.path)));
  }

  // ---------- charts: series maths (ES module) ----------
  const S = await import(pathToFileURL(path.join(PLUGINS, 'charts', 'series.js')).href);
  check('parseWindow', S.parseWindow('120s') === 120000 && S.parseWindow('5m') === 300000 && S.parseWindow('x') === 60000);
  check('a zero window falls back to the default', S.parseWindow('0s') === 60000 && S.parseWindow('0m') === 60000);
  {
    const z = new S.Series(0); z.push(1000, 1); z.push(1000, 2); z.push(400, 3);
    check('a zero-window series still gives finite pixels',
      z.toPixels(1000, 100, 50, ...z.range()).every(([x, y]) => isFinite(x) && isFinite(y)));
  }
  {
    const s = new S.Series(10000);
    for (let t = 0; t <= 30000; t += 1000) s.push(t, t / 1000);
    check('series keeps only the window (plus one sample before it)', s.length === 12 && s.t[0] === 19000, [s.length, s.t[0]]);
    check('series last value', s.last === 30);
    s.push(29000, 99);   // clock stepped back: kept in order
    check('series stays ordered when time steps back', s.t[s.t.length - 1] === 30000 && s.last === 99);
    s.push(31000, NaN);
    check('non-numbers are ignored', s.last === 99);
    const [lo, hi] = s.range();
    check('range pads around the data', lo < 20 && hi > 99, [lo, hi]);
    const flat = new S.Series(1000); flat.push(0, 5); flat.push(500, 5);
    const [flo, fhi] = flat.range();
    check('a flat line gets a non-empty range', flo < 5 && fhi > 5, [flo, fhi]);
    check('fixed min/max win', JSON.stringify(flat.range(0, 10)) === '[0,10]');
    const px = flat.toPixels(1000, 100, 50, 0, 10);
    check('pixels: left edge is now - window, y is flipped', px[0][0] === 0 && px[0][1] === 25 && px[1][0] === 50, px);
    const cap = new S.Series(1e9, 5);
    for (let t = 0; t < 20; t++) cap.push(t, t);
    check('series caps the number of points', cap.length === 5 && cap.t[0] === 15);
  }

  // ---------- flow-view: layout (ES module, no DOM) ----------
  const F = await import(pathToFileURL(path.join(PLUGINS, 'flow-view', 'flow.js')).href);
  {
    const act = (id, keyword) => ({ id, kind: 'action', keyword, args: [] });
    const flow = {
      name: 'sample',
      setup: { role: 'setup', steps: [act('open', 'Open Bench')] },
      tests: [{ role: 'test', name: 'soak', steps: [
        { id: 'wait', kind: 'gate', keyword: 'Temp Reached', timeout: '60s' },
        { id: 'cycle', kind: 'loop', max_loops: 3, body: [act('flash', 'Flash')] },
        { id: 'guard', kind: 'try', then: 'abort', body: [act('read', 'Read DTC')], recovery: [act('reset', 'Reset')] },
        { id: 'ok', kind: 'decision', condition: '${dtc} == 0', yes: [act('pass', 'Log')], no: [] }
      ] }],
      teardown: { role: 'teardown', steps: [act('close', 'Close Bench')] }
    };
    const svg = F.render(flow, { error: 'read' });
    const ids = [...svg.matchAll(/data-node="([^"]+)"/g)].map((x) => x[1]);
    check('flow-view: every step is a clickable node',
          JSON.stringify(ids.slice().sort()) === JSON.stringify(['close', 'cycle', 'flash', 'guard', 'ok', 'open', 'pass', 'read', 'reset', 'wait']), ids);
    check('flow-view: one lane per phase', (svg.match(/class="fv-lane"/g) || []).length === 3);
    check('flow-view: the error node is marked', /fv-error" data-node="read"/.test(svg));
    check('flow-view: recovery steps are marked', /fv-in-recovery" data-node="reset"/.test(svg));
    check('flow-view: sizes are finite', !/NaN|undefined|Infinity/.test(svg));
    check('flow-view: text is escaped', !F.render({ name: '<x>', tests: [{ steps: [act('a', '<b>')] }] }).includes('<b>'));
    check('flow-view: nothing to draw gives no markup', F.render({}) === '');
    const two = F.render(flow) + F.render(flow);
    const markers = [...two.matchAll(/<marker id="([^"]+)"/g)].map((x) => x[1]);
    check('flow-view: marker ids differ between drawings', new Set(markers).size === markers.length, markers);
  }

  // ---------- flow-view: sub-flows ----------
  {
    const act = (id, keyword) => ({ id, kind: 'keyword', keyword, args: [] });
    const inner = { id: 'deep', kind: 'flow', file: 'deeper.flow.json', args: {},
                    subflow: { name: 'Deeper', steps: [act('z', 'Log')] } };
    const call = { id: 'power', kind: 'flow', file: 'sub/power.flow.json', args: { VOLTS: '${V}' },
                   subflow: { name: 'Power', steps: [act('on', 'Power On'),
                     { id: 'd', kind: 'decision', condition: '$X', yes: [act('y', 'Log')], no: [] }, inner] } };
    const broken = { id: 'bad', kind: 'flow', file: 'nope.flow.json', args: {}, subflow: { name: null, error: 'not found' } };
    const flow = { name: 's', tests: [{ role: 'test', name: 't', steps: [call, broken] }] };
    const ids = (svg) => [...svg.matchAll(/data-node="([^"]+)"/g)].map((x) => x[1]);
    const closed = F.render(flow);
    check('flow-view sub-flow: closed, only the call box is drawn', JSON.stringify(ids(closed)) === '["power","bad"]', ids(closed));
    check('flow-view sub-flow: drawn as a predefined process with its arguments',
          (closed.match(/class="fv-bar"/g) || []).length === 4 && closed.includes('VOLTS=${V}'));
    check('flow-view sub-flow: an opener only where the sub-flow could be read',
          /data-toggle="power"/.test(closed) && !/data-toggle="bad"/.test(closed));
    check('flow-view sub-flow: a sub-flow that cannot be read shows why', /fv-error[^>]*data-node="bad"/.test(closed) && closed.includes('not found'));
    const open = F.render(flow, { expanded: { power: true } });
    check('flow-view sub-flow: opened, its steps carry the runner\'s "<name>::<id>"',
          JSON.stringify(ids(open)) === '["power","Power::on","Power::d","Power::y","Power::deep","bad"]', ids(open));
    check('flow-view sub-flow: a nested sub-flow stays closed until opened itself', /data-toggle="Power::deep"/.test(open) && !open.includes('Deeper::z'));
    const both = F.render(flow, { expanded: { power: true, 'Power::deep': true } });
    check('flow-view sub-flow: a nested one opens with its own name', ids(both).includes('Deeper::z'), ids(both));
    check('flow-view sub-flow: sizes are finite', !/NaN|undefined|Infinity/.test(open + both));
  }

  // ---------- flow-view: a run group ----------
  {
    const act = (id, keyword, args) => ({ id, kind: 'action', keyword, args: args || [] });
    const gate = (id, args) => ({ id, kind: 'gate', keyword: 'Signal Should Be', args, timeout: '5s' });
    const flow = (name, setup, test) => ({ name, setup: { role: 'setup', steps: setup }, tests: [{ role: 'test', name: 'T', steps: test }], teardown: null });
    const members = [
      { id: 'IVI', target: 'pairs/r.flow.json', variables: { BLADE: 'IVI' },
        flow: flow('R', [act('announce', 'Set Signal', ['bench.IVI.ready', '1'])], [gate('meet', ['bench.ADAS.ready', '==', '1'])]) },
      { id: 'ADAS', target: 'pairs/r.flow.json', variables: { BLADE: '<ADAS>' },
        flow: flow('R', [act('announce', 'Set Signal', ['bench.ADAS.ready', '1'])], [gate('meet', ['bench.IVI.ready', '==', '1'])]) }
    ];
    const links = [
      { from: { member: 'IVI', node: 'announce' }, to: { member: 'ADAS', node: 'meet' }, label: 'bench.IVI.ready = 1' },
      { from: { member: 'ADAS', node: 'announce' }, to: { member: 'IVI', node: 'meet' }, label: 'bench.ADAS.ready = 1' },
      { from: { member: 'IVI', node: 'nope' }, to: { member: 'ADAS', node: 'meet' }, label: 'x = 1' }
    ];
    const svg = F.renderGroup(members, links);
    const bands = [...svg.matchAll(/data-member="([^"]+)"/g)].map((x) => x[1]);
    check('flow-view group: one column per member, in order', JSON.stringify(bands) === '["IVI","ADAS"]', bands);
    check('flow-view group: every member keeps its own nodes',
          (svg.match(/data-node="announce"/g) || []).length === 2 && (svg.match(/data-node="meet"/g) || []).length === 2);
    check('flow-view group: a link per meeting point; one to an unknown node is left out',
          (svg.match(/class="fv-sync"/g) || []).length === 2 && /2 meeting points/.test(svg));
    check('flow-view group: labels are short, the tooltip has the full name',
          /class="fv-sync-label"[^>]*>IVI\.ready = 1</.test(svg) && /IVI \u2192 ADAS: bench\.IVI\.ready = 1/.test(svg));
    check('flow-view group: member text is escaped', svg.includes('&lt;ADAS&gt;') && !svg.includes('<ADAS>'));
    const cols = [...svg.matchAll(/<g transform="translate\(([\d.]+),/g)].map((x) => Number(x[1]));
    const labelsX = [...svg.matchAll(/class="fv-sync-label" x="([\d.]+)"/g)].map((x) => Number(x[1]));
    check('flow-view group: members side by side, labels in the channel between them',
          cols.length === 2 && cols[0] === 0 && cols[1] > 0 && labelsX.every((x) => x < cols[1]), [cols, labelsX]);
    check('flow-view group: sizes are finite', !/NaN|undefined|Infinity/.test(svg));
    check('flow-view group: nothing to draw is still an svg', F.renderGroup([], []).startsWith('<svg'));
  }

  // ---------- robot-grid: markup (ES module, no DOM) ----------
  const G = await import(pathToFileURL(path.join(PLUGINS, 'robot-grid', 'render.js')).href);
  {
    const kw = { name: 'Wait Until Keyword Succeeds', owner: 'BuiltIn', owner_type: 'library', shortdoc: 'Runs it until it passes.',
                 doc: 'Runs the specified keyword and retries if it fails.',
                 args: [{ name: 'retry', kind: 'POSITIONAL_OR_NAMED', required: true, default: null, type: null },
                        { name: 'retry_interval', kind: 'POSITIONAL_OR_NAMED', required: true, default: null, type: null },
                        { name: 'name', kind: 'POSITIONAL_OR_NAMED', required: true, default: null, type: null },
                        { name: 'args', kind: 'VAR_POSITIONAL', required: false, default: null, type: null }] };
    const set = { name: 'Set Signal', owner: 'bench_signals', owner_type: 'resource', shortdoc: 'Write a setpoint.', doc: '',
                  args: [{ name: 'name', kind: 'POSITIONAL_OR_NAMED', required: true, default: null, type: 'str' },
                         { name: 'value', kind: 'POSITIONAL_OR_NAMED', required: false, default: '0', type: null }] };
    const data = {
      catalog: 227,
      keywords: { 'builtin.waituntilkeywordsucceeds': kw, 'benchsignals.setsignal': set },
      imports: [{ type: 'resource', name: '../res/a.resource', line: 3, ok: true, keywords: 11 },
                { type: 'library', name: 'Nope<Lib>', line: 4, ok: false, error: 'No module named Nope' }],
      grid: { sections: [
        { type: 'settings', title: 'Settings', line: 1, rows: [
          { line: 3, depth: 0, type: 'RESOURCE', label: 'Resource', keyword: null, kw: null, cells: [{ v: '../res/a.resource', p: null, kw: null }], missing: [], comment: '' }] },
        { type: 'tests', title: 'Test Cases', line: 6, items: [{ name: 'Setpoint <Reaches> DAC', line: 7, rows: [
          { line: 8, depth: 0, type: 'KEYWORD', label: '', assign: ['${res}'], keyword: 'Set Signal', kw: 'benchsignals.setsignal',
            cells: [{ v: 'bench.x', p: 'name', kw: null }, { v: '${TARGET}', p: 'value', kw: null }, { v: 'oops', p: '(extra)', kw: null }], missing: [], comment: '# why' },
          { line: 9, depth: 0, type: 'FOR', label: 'FOR', keyword: null, kw: null, cells: [{ v: '${i}', p: null, kw: null }], missing: [], comment: '' },
          { line: 10, depth: 1, type: 'KEYWORD', label: '', assign: [], keyword: 'Wait Until Keyword Succeeds', kw: 'builtin.waituntilkeywordsucceeds',
            cells: [{ v: '3s', p: 'retry', kw: null }, { v: 'Set Signal', p: 'name', kw: 'benchsignals.setsignal' }], missing: ['retry_interval'], comment: '' },
          { line: 11, depth: 1, type: 'KEYWORD', label: '', assign: [], keyword: 'No Such Keyword', kw: null, cells: [], missing: [], comment: '' },
          { line: 12, depth: 0, type: 'END', label: 'END', keyword: null, kw: null, cells: [], missing: [], comment: '' }] }] }] }
    };
    const html = G.renderGrid(data);
    check('robot-grid: every row carries its line', ['3', '8', '9', '10', '11', '12'].every((l) => html.includes('data-line="' + l + '"')));
    check('robot-grid: cells are labelled with their parameters',
          /class="rg-p">name<\/span><span class="rg-v">bench\.x/.test(html) && html.includes('class="rg-p">retry<'));
    check('robot-grid: extra values, missing parameters and unknown keywords are marked',
          html.includes('rg-cell-extra') && html.includes('needs retry_interval') && /rg-kw rg-unknown"[^>]*>No Such Keyword/.test(html));
    check('robot-grid: a keyword named in a cell is hoverable too',
          /rg-nested" data-kw="benchsignals\.setsignal">Set Signal/.test(html));
    check('robot-grid: blocks are indented', /data-line="10"><td class="rg-line">10<\/td><td class="rg-kwcell" style="padding-left:1\.6rem"/.test(html));
    check('robot-grid: variables, assignments and comments show', html.includes('<span class="rg-var">${TARGET}</span>') &&
          html.includes('class="rg-assign"') && html.includes('rg-comment"># why'));
    check('robot-grid: a broken import is listed', html.includes('rg-imports-bad') && html.includes('No module named Nope'));
    check('robot-grid: text is escaped', html.includes('Setpoint &lt;Reaches&gt; DAC') && html.includes('Nope&lt;Lib&gt;') && !html.includes('<Reaches>'));
    check('robot-grid: the count of usable keywords', html.includes('227 keywords available'));
    const card = G.renderCard(kw);
    check('robot-grid: the card shows parameters in call order', G.signature(kw) === 'retry, retry_interval, name, *args' &&
          card.indexOf('retry_interval') < card.indexOf('*args') && card.includes('required'));
    check('robot-grid: the card shows types and defaults', G.renderCard(set).includes('rg-card-type">str') && G.renderCard(set).includes('= 0'));
    check('robot-grid: an empty file', G.renderGrid({ grid: { sections: [] } }).includes('Nothing in this file yet'));
  }

  // ---------- robot-grid: editing a step (ES module, no DOM) ----------
  const E = await import(pathToFileURL(path.join(PLUGINS, 'robot-grid', 'edit.js')).href);
  const G2 = E;
  {
    const P = (name, required, def) => ({ name, kind: 'POSITIONAL_OR_NAMED', required, default: def === undefined ? null : def });
    const wuks = { name: 'Wait Until Keyword Succeeds', args: [P('retry', true), P('retry_interval', true), P('name', true), { name: 'args', kind: 'VAR_POSITIONAL' }] };
    const rv = { name: 'Read Voltage', args: [P('channel', true), P('gain', false, '1'), { name: 'unit', kind: 'NAMED_ONLY', required: false, default: 'V' }] };
    const three = { name: 'X', args: [P('a', true), P('b', false, '1'), P('c', false, '2')] };
    const logAll = { name: 'Log All', args: [{ name: 'values', kind: 'VAR_POSITIONAL' }, { name: 'options', kind: 'VAR_NAMED' }] };

    const s = E.slotsFor(wuks, [{ v: '3s', p: 'retry' }, { v: '0.2s', p: 'retry_interval' }, { v: 'Signal Should Be', p: 'name', kw: 'k' },
      { v: 'bench.x', p: 'name' }, { v: '==', p: 'op' }, { v: '2', p: 'expected' }]);
    check('robot-grid edit: the cells after a named keyword stay its arguments',
          JSON.stringify(s.varargs.values) === '["bench.x","==","2"]' && s.positional[2].value === 'Signal Should Be');
    check('robot-grid edit: an unchanged call gives the same cells back',
          JSON.stringify(E.argsFromSlots(wuks, s).args) === '["3s","0.2s","Signal Should Be","bench.x","==","2"]');

    const n = E.slotsFor(rv, [{ v: 'ch0', p: 'channel' }, { v: 'unit=mV', p: 'unit' }]);
    check('robot-grid edit: named values fill their parameter, without the name',
          n.named[0].value === 'mV' && JSON.stringify(E.argsFromSlots(rv, n).args) === '["ch0","unit=mV"]');
    check('robot-grid edit: a missing required parameter is refused', /Fill in channel/.test(E.argsFromSlots(rv, E.slotsFor(rv, [])).error));
    const g = E.slotsFor(three, []); g.positional[0].value = 'A'; g.positional[2].value = 'C';
    check('robot-grid edit: after a skipped optional parameter the rest go by name',
          JSON.stringify(E.argsFromSlots(three, g).args) === '["A","c=C"]');
    const e = E.slotsFor(rv, []); e.positional[0].value = 'channel=5';
    check('robot-grid edit: a value that looks named is escaped', E.argsFromSlots(rv, e).args[0] === 'channel\\=5');
    const kw = E.slotsFor(logAll, [{ v: 'a', p: '*values' }, { v: 'level=INFO', p: '**options' }]);
    check('robot-grid edit: *args and **kwargs round-trip',
          JSON.stringify(E.argsFromSlots(logAll, kw).args) === '["a","level=INFO"]' && kw.kwargs.pairs[0].key === 'level');

    const free = E.slotsFor(null, [{ v: 'x', p: null }, { v: 'y', p: null }]);
    check('robot-grid edit: an unknown keyword keeps its values as written', JSON.stringify(E.argsFromSlots(null, free).args) === '["x","y"]');
    const carried = E.carrySlots(free, three);
    check('robot-grid edit: choosing a keyword carries the values over',
          carried.positional[0].value === 'x' && carried.positional[1].value === 'y');
    const byName = E.carrySlots(E.slotsFor(rv, [{ v: 'ch1', p: 'channel' }]), { name: 'Other', args: [P('gain', false), P('channel', true)] });
    check('robot-grid edit: values carry over by parameter name', byName.positional[1].value === 'ch1' && byName.positional[0].value === '');

    const lst = [{ name: 'Log', owner: 'BuiltIn' }, { name: 'Log Many', owner: 'BuiltIn' }, { name: 'Set Signal', owner: 'bench' },
      { name: 'Should Be Equal', owner: 'BuiltIn' }, { name: 'Signal Should Be', owner: 'bench' }];
    check('robot-grid edit: completion puts names starting with the text first',
          JSON.stringify(E.filterKeywords(lst, 'log').map((k) => k.name)) === '["Log","Log Many"]');
    check('robot-grid edit: completion matches words anywhere',
          JSON.stringify(E.filterKeywords(lst, 'sh be').map((k) => k.name)) === '["Should Be Equal","Signal Should Be"]');
    check('robot-grid edit: "Owner." narrows to one library or resource',
          JSON.stringify(E.filterKeywords(lst, 'bench.s').map((k) => k.name)) === '["Set Signal","Signal Should Be"]');
    check('robot-grid edit: names match like Robot does', E.norm('Set_Signal') === E.norm(' set signal '));
    const eq = ['Should Not Be Equal', 'Lists Should Be Equal', 'Should Be Equal As Numbers', 'Should Be Equal']
      .map((name) => ({ name, owner: 'BuiltIn' }));
    check('robot-grid edit: typed words lined up with the name rank first',
          JSON.stringify(E.filterKeywords(eq, 'sh be eq').map((k) => k.name)) ===
          '["Should Be Equal","Should Be Equal As Numbers","Should Not Be Equal","Lists Should Be Equal"]');
  }

  // ---------- robot-grid: variables in scope, block headers ----------
  {
    const cell = (v) => ({ v, p: null, kw: null });
    const data = {
      variables: [{ name: '${LIMIT}', source: 's.robot' }, { name: '${FROM_RES}', source: 'vars.resource' }],
      grid: { sections: [{ type: 'keywords', title: 'Keywords', items: [{ name: 'Helper', line: 10, rows: [
        { line: 11, type: 'ARGUMENTS', label: '[Arguments]', cells: [cell('${x}'), cell('${y}=2'), cell('@{rest}')] },
        { line: 12, type: 'KEYWORD', keyword: 'Get Count', assign: ['${count}='], cells: [] },
        { line: 13, type: 'FOR', label: 'FOR', cells: [cell('${i}'), cell('IN RANGE'), cell('${count}')] },
        { line: 14, type: 'KEYWORD', keyword: 'Set Test Variable', assign: [], cells: [cell('\\${shared}'), cell('1')] },
        { line: 15, type: 'END', label: 'END', cells: [] },
        { line: 16, type: 'EXCEPT', label: 'EXCEPT', cells: [cell('boom'), cell('AS'), cell('${err}')] },
        { line: 17, type: 'KEYWORD', keyword: 'Log', assign: ['${late}='], cells: [] }] }] }] }
    };
    const at16 = G2.variablesInScope(data, 16).map((v) => v.name);
    check('robot-grid scope: arguments, assignments, FOR and Set Test Variable above the line',
          ['${x}', '${y}', '@{rest}', '${count}', '${i}', '${shared}'].every((n) => at16.includes(n)) && !at16.includes('${late}'), at16.slice(0, 8));
    check('robot-grid scope: nearest first, then the file, then Robot',
          at16[0] === '${shared}' && at16.indexOf('${LIMIT}') > at16.indexOf('${x}') && at16.indexOf('${EMPTY}') > at16.indexOf('${FROM_RES}'));
    check('robot-grid scope: EXCEPT AS counts below it', G2.variablesInScope(data, 17).some((v) => v.name === '${err}'));
    const found = G2.variableAt('Log    ${co', 10, G2.variablesInScope(data, 16));
    check('robot-grid scope: the variable being typed is completed', found && found.start === 7 && found.hits[0].insert === '${count}', found);
    const list = G2.variableAt('x @{LI}', 5, [{ name: '${LIMIT}', source: '' }]);
    check('robot-grid scope: the typed sigil is kept, the closing brace replaced', list.hits[0].insert === '@{LIMIT}' && list.end === 7);
    check('robot-grid scope: nothing typed, nothing offered', G2.variableAt('plain text', 5, [{ name: '${A}' }]) === null);
    check('robot-grid headers: FOR', JSON.stringify(G2.parseFor([cell('${i}'), cell('${j}'), cell('IN ZIP'), cell('@{a}'), cell('@{b}')])) ===
          JSON.stringify({ variables: ['${i}', '${j}'], flavor: 'IN ZIP', values: ['@{a}', '@{b}'] }));
    check('robot-grid headers: WHILE with a limit', JSON.stringify(G2.parseWhile([cell('${n} < 3'), cell('limit=10')])) ===
          JSON.stringify({ condition: '${n} < 3', limit: '10' }));
    check('robot-grid headers: THREAD name and daemon (RobotFramework AIO)',
          JSON.stringify(G2.parseThread([cell('WORKER1'), cell('False')])) === JSON.stringify({ name: 'WORKER1', daemon: false }) &&
          G2.parseThread([cell('W')]).daemon === true);
    check('robot-grid headers: EXCEPT patterns, type and AS', JSON.stringify(G2.parseExcept([cell('Err*'), cell('type=glob'), cell('AS'), cell('${e}')])) ===
          JSON.stringify({ patterns: ['Err*'], type: 'glob', variable: '${e}' }));
  }

  // ---------- plugins a service delivers (Meta.gui_plugin) ----------
  {
    const SP = path.join(__dirname, 'fixtures', 'service-plugins');
    const lintS = (m) => C.lintPlugin(m, { schema: pluginSchema, source: 'service' });
    const sessions = readJson(path.join(SP, 'SessionsDemo0.1.0', 'plugin.json'));
    const config = readJson(path.join(SP, 'ConfigDemo0.1.0', 'plugin.json'));
    const refused = readJson(path.join(SP, 'RefusedDemo0.1.0', 'plugin.json'));
    check('service fixture sessions-demo lints clean as a service plugin', lintS(sessions).length === 0, lintS(sessions).map(C.formatIssue));
    check('service fixture config-demo lints clean as a service plugin', lintS(config).length === 0, lintS(config).map(C.formatIssue));
    [['SessionsDemo0.1.0', sessions], ['ConfigDemo0.1.0', config]].forEach(([dir, m]) => {
      Object.values(m.contributes).forEach((list) => list.filter((e) => e.entry).forEach((e) => {
        check('service fixture ' + m.plugin + ': entry ' + e.entry + ' exists', fs.existsSync(path.join(SP, dir, e.entry)));
      }));
    });
    const rr = lintS(refused).filter((i) => i.severity === 'error' && i.rule === 'P');
    check('P: a service plugin may not use shell views or actions', rr.length === 2 && rr.every((i) => /not "shell"/.test(i.message)), rr);
    check('the same shell entries are fine in a plugin shipped with the GUI',
          !lintP(refused).some((i) => i.rule === 'P'), lintP(refused).map(C.formatIssue));
    const a = clone(sessions); a.isolation = 'schema'; a.contributes = {};
    check('P: a service plugin runs in frames', lintS(a).some((i) => i.rule === 'P' && i.path === 'isolation'));
    const b = clone(sessions); b.isolation = 'window'; b.main = 'x.js'; b.contributes = {};
    check('P: a service plugin has no main-process code', lintS(b).some((i) => i.rule === 'P' && i.path === 'main'));
    const c = clone(sessions); delete c.binds;
    check('P: grpc.call without binds.grpc warns', lintS(c).some((i) => i.rule === 'P' && i.severity === 'warn' && i.path === 'binds.grpc'));
    check('P: binds on a plugin shipped with the GUI warns (no service to call)',
          lintP(sessions).some((i) => i.rule === 'P' && i.severity === 'warn' && i.path === 'binds'));
    const e = clone(sessions); e.requires.capabilities.push('files.project');
    check('P: a service plugin may not reach this PC\'s files', lintS(e).some((i) => i.rule === 'P' && i.severity === 'error' &&
          /files\.project/.test(i.message)));
    const k = clone(sessions); k.contributes.kinds = [{ kind: 'session-badge', title: 'Session', entry: 'view.js' }];
    check('P: a service plugin adds no tile kinds (they would run with another component\'s ctx)',
          lintS(k).some((i) => i.rule === 'P' && i.severity === 'error' && i.path === 'contributes.kinds[0]'), lintS(k));
    const d = clone(sessions); d.binds = { grpc: ['a'], consul: 'other-service' };
    check('S: binds names proto services only; the service is the one that delivered it',
          rules(lintS(d), 'error').includes('S'), lintS(d));

    // ---------- slot 3: other services it calls (binds.uses) ----------
    const u = clone(sessions); u.binds.uses = ['configuration-hub', 'catalog'];
    check('P: binds.uses with Consul names lints clean', lintS(u).length === 0, lintS(u).map(C.formatIssue));
    const ua = clone(u); ua.binds.uses = ['10.0.0.5:50051', 'catalog/x', 'catalog'];
    check('P: binds.uses refuses addresses and paths',
          lintS(ua).filter((i) => i.rule === 'P' && i.severity === 'error').map((i) => i.path).join() === 'binds.uses[0],binds.uses[1]', lintS(ua));
    const ub = clone(u); ub.binds.uses = ['catalog', 'catalog'];
    check('P: a service named twice in binds.uses warns', lintS(ub).some((i) => i.path === 'binds.uses[1]' && i.severity === 'warn'));
    const uc = clone(u); uc.requires.capabilities = ['session.read'];
    check('P: binds.uses without grpc.call warns', lintS(uc).some((i) => i.path === 'binds.uses' && i.severity === 'warn'));
    const ud = clone(u); ud.binds.other = 1;
    check('S: binds takes only grpc and uses', rules(lintS(ud), 'error').includes('S'));

    // ---------- configuration-hub platform service plugin ----------
    const confighubManifest = readJson(path.join(SP, 'ConfigurationHub1.0.0', 'plugin.json'));
    check('configuration-hub platform service plugin lints clean as a service plugin', lintS(confighubManifest).length === 0, lintS(confighubManifest).map(C.formatIssue));
  }

  // ---------- slots 3 and 4: ctx.call to other services, options, full errors ----------
  {
    const vm = require('vm');
    const window = { MicroserviceManager: { endo: { util: { esc: String } } } };
    vm.runInNewContext(fs.readFileSync(path.join(GUI, 'web', 'js', 'endo', 'host.js'), 'utf-8'),
                       { window, document: { addEventListener() {} }, console, URL, fetch: () => Promise.reject(new Error('offline')) });
    const MM = window.MicroserviceManager;
    const sent = [];
    let answer = { ok: true, result: {}, request_id: 'r1' };
    MM.grpcClient = {
      callMethod: (o) => { sent.push(o); return typeof answer === 'function' ? answer(o) : Promise.resolve(answer); },
      getServiceMethods: (name) => Promise.resolve({ grpc_services: [{ name: name === 'catalog' ? 'catalog.v1.Catalog' : 'session.v1.SessionManager',
                                                                       methods: [{ name: name === 'catalog' ? 'List' : 'Open', input_fields: [] }] }] })
    };
    const ctx = MM.endo.makeCtx({ component: 'plugin.sessions', requires: { capabilities: ['grpc.call'] },
                                  binds: { consul: 'session-manager', grpc: ['session.v1.SessionManager'], uses: ['catalog'] } },
                                { consulName: 'session-manager', consulUrl: 'http://consul:8500', protoPath: 'protos' });
    const last = () => sent[sent.length - 1];
    await ctx.call('Open', {});
    check('slot 3: a plain method still goes to the own service',
          last().consulName === 'session-manager' && last().grpcService === 'session.v1.SessionManager' && last().protoPath === 'protos', last());
    await ctx.call('catalog:catalog.v1.Catalog/List', { page: 1 });
    check('slot 3: "<consul>:<ProtoService>/<Method>" goes to that service, on the same Consul, without the own proto path',
          last().consulName === 'catalog' && last().grpcService === 'catalog.v1.Catalog' && last().method === 'List' &&
          last().consulUrl === 'http://consul:8500' && last().protoPath === '', last());
    await ctx.call('session-manager:session.v1.SessionManager/Open', {});
    check('slot 3: the own Consul name as prefix is the own service', last().consulName === 'session-manager' && last().method === 'Open', last());
    const n = sent.length;
    const refusedWith = (p) => p.then(() => null, (e) => e);
    let e = await refusedWith(ctx.call('configuration-hub:config.v1.Hub/Get', {}));
    check('slot 3: a service not in binds.uses is refused before any call', e && e.code === 'NotBound' && sent.length === n, e && e.message);
    e = await refusedWith(ctx.call('catalog:List', {}));
    check('slot 3: another service needs its proto service named', e && e.code === 'NotBound' && /ProtoService/.test(e.message), e && e.message);
    const d = await ctx.describe('catalog:catalog.v1.Catalog/List');
    check('slot 3: describe reaches a used service', d && d.name === 'List', d);
    check('slot 3: ctx lists the services it uses', JSON.stringify(ctx.uses) === '["catalog"]', ctx.uses);

    await ctx.call('Open', {}, { timeout: 2500, metadata: { tenant: 'lab-3', n: 7 } });
    check('slot 4: timeout (ms) and metadata reach the bridge (s, strings)',
          last().timeout === 2.5 && JSON.stringify(last().metadata) === '{"tenant":"lab-3","n":"7"}', last());
    e = await refusedWith(ctx.call('Open', {}, { timeout: -1 }));
    check('slot 4: a bad timeout is refused', e && e.code === 'BadOptions', e && e.message);
    e = await refusedWith(ctx.call('Open', {}, { metadata: ['x'] }));
    check('slot 4: metadata must be an object', e && e.code === 'BadOptions', e && e.message);

    const details = [{ '@type': 'google.rpc.BadRequest', field_violations: [{ field: 'name', description: 'required' }] }];
    answer = { ok: false, error: 'INVALID_ARGUMENT: the session is not valid', code: 'INVALID_ARGUMENT', details: details, request_id: 'r9' };
    e = await refusedWith(ctx.call('Open', {}));
    check('slot 4: a failed call rejects with code, details and requestId',
          e && e.code === 'INVALID_ARGUMENT' && JSON.stringify(e.details) === JSON.stringify(details) && e.requestId === 'r9' &&
          e.message === 'INVALID_ARGUMENT: the session is not valid', e && { code: e.code, details: e.details, id: e.requestId });
    answer = { ok: false, error: "Service 'session-manager' not found in Consul", code: '', details: [], request_id: 'r10' };
    e = await refusedWith(ctx.call('Open', {}));
    check('slot 4: a call that never reached the service is a BridgeError', e && e.code === 'BridgeError' && e.requestId === 'r10', e && e.code);
    answer = () => Promise.reject(new Error('Bridge not running'));
    e = await refusedWith(ctx.call('Open', {}));
    check('slot 4: a bridge that is down is a BridgeError too', e && e.code === 'BridgeError' && /Bridge not running/.test(e.message), e && e.code);

    // The frame boundary keeps the full status (frame-host refuse -> frame-sdk).
    const hostSrc = fs.readFileSync(path.join(GUI, 'web', 'js', 'endo', 'frame-host.js'), 'utf-8');
    const sdkSrc = fs.readFileSync(path.join(GUI, 'web', 'js', 'endo', 'frame-sdk.js'), 'utf-8');
    check('slot 4: the frame host passes details, requestId and the call options across the port',
          /err\.details = /.test(hostSrc) && /err\.requestId = /.test(hostSrc) && /ctx\.call\(a\[0\], a\[1\], a\[2\]\)/.test(hostSrc));
    check('slot 4: the frame SDK puts them back on the Error',
          /e\.details = msg\.error\.details/.test(sdkSrc) && /e\.requestId = msg\.error\.requestId/.test(sdkSrc));
  }

  console.log('\n' + passes + ' passed, ' + failures + ' failed');
  process.exit(failures ? 1 : 0);
})();
