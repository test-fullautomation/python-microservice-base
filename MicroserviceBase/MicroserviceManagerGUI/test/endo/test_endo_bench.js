// Compositions (milestone M2): the composition rules, how a bench resolves
// services to modules and orders its tiles, and the prototype fixtures.
//   node test/endo/test_endo_bench.js      (from the GUI folder)
'use strict';

const fs = require('fs');
const path = require('path');
const C = require('../../web/js/endo/contract/lint.js');
const K = require('../../web/js/endo/composition.js');

const GUI = path.join(__dirname, '..', '..');
const DIR = path.join(GUI, 'web', 'js', 'endo', 'contract');
const componentSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'component.schema.json'), 'utf-8'));
const schema = JSON.parse(fs.readFileSync(path.join(DIR, 'composition.schema.json'), 'utf-8'));
const FIX = path.join(__dirname, 'fixtures', 'bench');

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}
const clone = (o) => JSON.parse(JSON.stringify(o));
const lint = (c) => C.lintComposition(c, { schema });
const rules = (issues, sev) => issues.filter((i) => !sev || i.severity === sev).map((i) => i.rule);
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf-8'));

const GOOD = {
  composition: 'bench07/operator',
  title: 'Bench 07',
  shell: '^2.3',
  role: 'user',
  plugins: ['charts'],
  components: [
    { from: 'consul', service: 'session-service' },
    { from: 'consul', service: 'testbench-device-psu', tiles: ['out'] },
    { from: 'consul', service: 'cpp-psu', gui: 'PowerSupply2.0.1' }
  ],
  order: ['session.header', '*', 'bits.power-supply/out']
};

// ---------- composition rules ----------
check('composition: good one has no issues', lint(GOOD).length === 0, lint(GOOD));
{
  const c = clone(GOOD); delete c.shell;
  check('S: shell is required', rules(lint(c)).includes('S'));
  const c2 = clone(GOOD); c2.shell = '^3.0';
  check('R9: a composition for another shell is refused', rules(lint(c2), 'error').includes('R9'));
  const c3 = clone(GOOD); c3.shell = '*';
  check('R9: "*" is not a range', rules(lint(c3), 'error').includes('R9'));
  const c4 = clone(GOOD); c4.components[0].address = '10.0.0.5:50051';
  check('R3: an entry with an address is refused', rules(lint(c4), 'error').includes('R3'), lint(c4));
  const c5 = clone(GOOD); c5.components[0].service = 'localhost:8500';
  check('R3: a service that is an address is refused', rules(lint(c5), 'error').includes('R3'), lint(c5));
  const c6 = clone(GOOD); c6.components.push({ from: 'consul', service: 'session-service' });
  check('C: the same service twice warns', lint(c6).some((i) => i.rule === 'C' && i.severity === 'warn'));
  const c7 = clone(GOOD); c7.role = 'operator';
  check('S: role is user, dev or admin', rules(lint(c7)).includes('S'));
  const c8 = clone(GOOD); c8.components[0].from = 'folder';
  check('S: entries come from consul', rules(lint(c8)).includes('S'));
  const c9 = clone(GOOD); c9.order = ['Bad Pattern'];
  check('S: order entries are <component>[/<tile>] or *', rules(lint(c9)).includes('S'));
  const c10 = clone(GOOD); c10.components = [];
  check('C: an empty bench warns', lint(c10).some((i) => i.rule === 'C' && /empty/.test(i.message)));
}

// ---------- resolving services ----------
const SERVICES = [
  { name: 'session-service', gui: 'SessionHeader0.1.0', consulUrl: 'http://a:8500' },
  { name: 'testbench-device-psu', gui: 'PowerSupply2.0.1', consulUrl: 'http://a:8500' },
  { name: 'testbench-device-psu', gui: 'Other', consulUrl: 'http://b:8500' },
  { name: 'cpp-psu', gui: '', consulUrl: 'http://a:8500' },
  { name: 'no-gui', gui: '', consulUrl: 'http://a:8500' }
];
{
  const r = K.resolveEntries(GOOD, SERVICES);
  check('resolve: the first Consul that has the service wins', r[1].service.consulUrl === 'http://a:8500' && r[1].folder === 'PowerSupply2.0.1');
  check('resolve: an entry names the folder for a service without Meta.gui', r[2].folder === 'PowerSupply2.0.1' && !r[2].problem);
  const r2 = K.resolveEntries({ components: [{ from: 'consul', service: 'gone' }, { from: 'consul', service: 'no-gui' }] }, SERVICES);
  check('resolve: an unregistered service is missing', r2[0].problem === 'missing');
  check('resolve: a service with no GUI folder is nogui', r2[1].problem === 'nogui');
  const d = K.defaultComposition(SERVICES, 'bench07', 'dev');
  check('default: every service with a GUI, once, in order',
        JSON.stringify(d.components.map((e) => e.service)) === JSON.stringify(['session-service', 'testbench-device-psu']), d);
  check('default: passes the composition rules', lint(d).length === 0, lint(d));
  check('default: keeps the role', d.role === 'dev');
}

// ---------- slots and order ----------
function mod(id, tiles, st, entry) {
  return { index: 0, state: st || 'ok', entry: entry || { service: id }, manifest: { component: id, tiles: tiles || [] }, issues: [], warnings: [] };
}
{
  const a = mod('session.header', [{ id: 'hdr', size: '4x1' }]);
  const b = mod('bits.power-supply', [{ id: 'out', size: '1x1' }, { id: 'set', size: '1x1' }]);
  const c = mod('execution.testflow', [{ id: 'run', size: '2x1' }]);
  const bad = { index: 3, state: 'refused', entry: { service: 'bench-heater' }, manifest: { component: 'bench-heater' }, issues: [] };
  const gone = { index: 4, state: 'missing', entry: { service: 'gone' }, manifest: null, issues: [] };
  const slots = [].concat(K.slotsFor(b), K.slotsFor(c), K.slotsFor(a), K.slotsFor(bad), K.slotsFor(gone));
  check('slots: an ok module places each tile', K.slotsFor(b).length === 2 && K.slotsFor(b)[0].key === 'bits.power-supply/out');
  check('slots: a refused module keeps one 2x1 slot (R10)', K.slotsFor(bad).length === 1 && K.slotsFor(bad)[0].size === '2x1');
  check('slots: a missing service keeps a slot keyed by its name', K.slotsFor(gone)[0].key === 'service:gone');

  const o = K.orderSlots(slots, ['session.header', '*', 'bits.power-supply/out']);
  const keys = o.slots.map((s) => s.key);
  check('order: listed component first, * for the rest, then listed after *',
        JSON.stringify(keys) === JSON.stringify(['session.header/hdr', 'bits.power-supply/set', 'execution.testflow/run',
                                                  'bench-heater', 'service:gone', 'bits.power-supply/out']), keys);
  check('order: no order keeps composition order', JSON.stringify(K.orderSlots(slots).slots.map((s) => s.key)) ===
        JSON.stringify(slots.map((s) => s.key)));
  const o3 = K.orderSlots(slots, ['@gone', '@bench-heater', '*']);
  check('order: @<service> places a module that shows no component',
        o3.slots[0].key === 'service:gone' && o3.slots[1].key === 'bench-heater', o3.slots.map((s) => s.key));
  check('order: @<service> is valid in a composition', lint(Object.assign(clone(GOOD), { order: ['@session-service', '*'] })).length === 0);
  const o2 = K.orderSlots(slots, ['nope.thing']);
  check('order: a pattern that matches nothing warns', o2.issues.some((i) => i.rule === 'C' && /matches no tile/.test(i.message)));
  check('order: every slot is placed exactly once', o.slots.length === slots.length && new Set(keys).size === keys.length);

  const filtered = mod('bits.power-supply', [{ id: 'out', size: '1x1' }, { id: 'set', size: '1x1' }], 'ok',
                       { service: 'psu', tiles: ['set', 'ghost'] });
  const fs2 = K.slotsFor(filtered);
  check('slots: entry.tiles filters the tiles', fs2.length === 1 && fs2[0].tile.id === 'set');
  check('slots: an unknown entry tile warns', (filtered.warnings || []).some((w) => /ghost/.test(w.message)));
}

// ---------- the prototype fixtures ----------
{
  const svcMap = readJson(path.join(FIX, 'services.json'));
  const folders = fs.readdirSync(path.join(FIX, 'services'));
  check('fixtures: every folder is mapped to a service', folders.every((f) => Object.values(svcMap).includes(f)), folders);
  const manifests = {};
  folders.forEach((f) => { manifests[f] = readJson(path.join(FIX, 'services', f, 'component.json')); });
  folders.forEach((f) => {
    const issues = C.lintComponent(manifests[f], { schema: componentSchema });
    if (f === 'BenchHeater0.9.0') {
      const r = new Set(rules(issues, 'error'));
      check('fixture BenchHeater0.9.0 breaks S R1 R2 R3 R7 R8 R9',
            ['S', 'R1', 'R2', 'R3', 'R7', 'R8', 'R9'].every((x) => r.has(x)), [...r]);
    } else {
      check('fixture ' + f + ' passes', !C.hasErrors(issues), issues.map(C.formatIssue));
    }
  });
  const services = Object.keys(svcMap).map((name) => ({ name, gui: svcMap[name], consulUrl: 'http://127.0.0.1:8500' }));
  ['operator', 'signals', 'testdev', 'lint'].forEach((n) => {
    const comp = readJson(path.join(FIX, 'compositions', n + '.json'));
    check('composition ' + n + ' passes', lint(comp).length === 0, lint(comp));
    const resolved = K.resolveEntries(comp, services);
    check('composition ' + n + ' resolves every service', resolved.every((r) => !r.problem), resolved.map((r) => r.problem));
  });
  // The three prototype benches place the tiles the proposal shows.
  const expectTiles = {
    operator: ['session.header/hdr', 'execution.testflow/run', 'bits.climate-chamber/state', 'bits.power-supply/out', 'signals.monitor/trend'],
    signals: ['session.header/hdr', 'signals.graph-view/g', 'signals.monitor/trend', 'bits.climate-chamber/state'],
    testdev: ['execution.testflow/run', 'runner.robot-results/res', 'bits.uds-tester/req', 'bits.dlt-viewer/log']
  };
  Object.keys(expectTiles).forEach((n) => {
    const comp = readJson(path.join(FIX, 'compositions', n + '.json'));
    const mods = K.resolveEntries(comp, services).map((r) => Object.assign({}, r, {
      state: 'ok', manifest: manifests[r.folder], issues: [], warnings: [] }));
    const keys = K.orderSlots([].concat.apply([], mods.map(K.slotsFor)), comp.order).slots.map((s) => s.key);
    check('prototype ' + n + ' places ' + expectTiles[n].length + ' tiles in order',
          JSON.stringify(keys) === JSON.stringify(expectTiles[n]), keys);
  });
}

console.log('\n' + passes + ' passed, ' + failures + ' failed');
process.exit(failures ? 1 : 0);
