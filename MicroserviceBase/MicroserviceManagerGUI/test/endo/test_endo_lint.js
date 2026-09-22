// Contract v1 linter: every rule has a failing and a passing case.
//   node test/endo/test_endo_lint.js      (from the GUI folder)
'use strict';

const fs = require('fs');
const path = require('path');
const C = require('../../web/js/endo/contract/lint.js');

const GUI = path.join(__dirname, '..', '..');
const DIR = path.join(GUI, 'web', 'js', 'endo', 'contract');
const schema = JSON.parse(fs.readFileSync(path.join(DIR, 'component.schema.json'), 'utf-8'));
const pluginSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'plugin.schema.json'), 'utf-8'));

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}
const clone = (o) => JSON.parse(JSON.stringify(o));
const lint = (m, opts) => C.lintComponent(m, Object.assign({ schema }, opts || {}));
const errors = (issues) => issues.filter((i) => i.severity === 'error');
const rules = (issues, sev) => issues.filter((i) => !sev || i.severity === sev).map((i) => i.rule);

// A valid manifest that exercises every core kind.
const GOOD = {
  component: 'bits.power-supply',
  version: '1.0.0',
  layer: 'bits',
  title: 'DUT supply',
  requires: { shell: '^2.3', capabilities: ['grpc.call', 'signals.subscribe'] },
  binds: { consul: 'testbench-device-psu', grpc: 'device.v1.PowerSupply' },
  tiles: [
    { id: 'out', size: '1x1', kind: 'live-status', title: 'Output',
      fields: [{ label: 'Voltage', rpc: 'GetOutput', path: 'voltage', unit: 'V', warnAbove: 30 },
               { label: 'Temp', signal: 'bench.psu.temp.degC', unit: '°C' }], refresh: '1s' },
    { id: 'set', size: '1x1', kind: 'command-form', call: 'SetVoltage',
      form: { volts: { type: 'float', min: 0, max: 30 } }, confirm: 'Change the DUT supply?' },
    { id: 'hist', size: '2x2', kind: 'table', rpc: 'History', path: 'entries',
      columns: [{ label: 'Time', path: 'ts' }, { label: 'V', path: 'volts', digits: 2 }] },
    { id: 'log', size: '4x1', kind: 'log', rpc: 'Events', path: 'text', maxLines: 100 },
    { id: 'hdr', size: '4x1', kind: 'text', text: 'Bench 07 supply' },
    { id: 'seq', size: '2x1', kind: 'run-status', flow: 'ramp', steps: ['0 V', '12 V', '16 V'], current: 1 }
  ],
  ribbon: [{ tab: 'user', group: 'Supply', commands: [
    { label: 'Output on', call: 'SetOutput', args: { on: true } },
    { label: 'Set voltage', call: 'SetVoltage', form: { volts: 'float' }, confirm: 'Sure?' }] }],
  dock: ['api', 'details'],
  renderer: 'schema'
};

// ---------- baseline ----------
check('good manifest: no issues at all', lint(GOOD).length === 0, lint(GOOD));
check('SHELL_VERSION is 2.3.x', /^2\.3\./.test(C.SHELL_VERSION));

// ---------- structure ----------
{
  const m = clone(GOOD); delete m.binds;
  check('S: missing binds is a structure error', rules(lint(m)).includes('S'));
  const m2 = clone(GOOD); m2.colour = 'red';
  check('S: unknown top-level field refused', lint(m2).some((i) => i.path === 'colour'));
  const m3 = clone(GOOD); m3.tiles[0].fields = [];
  check('S: live-status needs at least one field', lint(m3).some((i) => i.path === 'tiles[0].fields' && i.rule === 'S'));
  const m4 = clone(GOOD); delete m4.tiles[3].rpc;
  check('S: log needs rpc or lines', lint(m4).some((i) => i.rule === 'S' && /one of/.test(i.message)));
  const m5 = clone(GOOD); m5.tiles[0].refresh = 'fast';
  check('S: refresh must be like 500ms / 2s / 1m', lint(m5).some((i) => i.path === 'tiles[0].refresh'));
  const m6 = clone(GOOD); m6.ribbon[0].tab = 'operator';
  check('S: ribbon tab is user | dev | admin', lint(m6).some((i) => i.path === 'ribbon[0].tab'));
  const m7 = clone(GOOD); m7.tiles[1].form = { volts: 'double' };
  check('S: form field types are string/int/float/bool/json', lint(m7).some((i) => i.path === 'tiles[1].form.volts'));
  check('S: non-object manifest refused', rules(lint([])).includes('S'));
}

// ---------- R1 ----------
{
  const m = clone(GOOD); m.requires.capabilities = ['signals.subscribe'];
  check('R1: RPC use without grpc.call is an error', rules(lint(m), 'error').includes('R1'));
  const m2 = clone(GOOD); m2.requires.capabilities = ['grpc.call'];
  check('R1: signal use without signals.subscribe is an error', lint(m2).some((i) => i.rule === 'R1' && /signals/.test(i.message)));
  const m3 = clone(GOOD); m3.requires.capabilities.push('telemetry.raw');
  check('R1: unknown capability is an error', lint(m3).some((i) => i.rule === 'R1' && /telemetry\.raw/.test(i.message)));
  const m4 = clone(GOOD); m4.requires.capabilities.push('process.spawn');
  check('R1: components may not ask for process.spawn', lint(m4).some((i) => i.rule === 'R1' && /process\.spawn/.test(i.message)));
  const m5 = { component: 'session.header', version: '0.1.0', layer: 'session', title: 'S',
               requires: { shell: '^2.3', capabilities: ['grpc.call'] }, binds: { consul: 'x' },
               tiles: [{ id: 'h', size: '4x1', kind: 'text', text: 'hi' }], renderer: 'schema' };
  check('R1: declared-but-unused grpc.call is a warning', lint(m5).some((i) => i.rule === 'R1' && i.severity === 'warn'));
  const kinds = { 'signal-strip': { plugin: 'charts', needs: ['signals.subscribe'] } };
  const m6 = clone(GOOD); m6.requires.capabilities = ['grpc.call'];
  m6.tiles = [{ id: 's', size: '2x1', kind: 'signal-strip' }];
  check('R1: a plugin kind\'s needs must be declared', lint(m6, { kinds }).some((i) => i.rule === 'R1' && /signal-strip/.test(i.message)));
}

// ---------- R2 ----------
{
  const m = clone(GOOD); m.tiles[0].size = '3x1';
  check('R2: 3x1 is not a tile size', lint(m).some((i) => i.rule === 'R2' && i.path === 'tiles[0].size'));
  ['1x1', '2x1', '2x2', '4x1'].forEach((s) => {
    const ok = clone(GOOD); ok.tiles[0].size = s;
    check('R2: ' + s + ' is accepted', !rules(lint(ok)).includes('R2'));
  });
}

// ---------- R3 ----------
{
  const m = clone(GOOD); m.binds.address = '10.40.2.17:50051';
  check('R3: an address key is refused', lint(m).some((i) => i.rule === 'R3' && i.path === 'binds.address'));
  const m2 = clone(GOOD); m2.binds.consul = '127.0.0.1:8500';
  check('R3: an address as the Consul name is refused', lint(m2).some((i) => i.rule === 'R3' && i.path === 'binds.consul'));
  const m3 = clone(GOOD); m3.binds.backup = 'http://psu.local';
  check('R3: a URL value is refused', lint(m3).some((i) => i.rule === 'R3' && i.path === 'binds.backup'));
  const m4 = clone(GOOD); delete m4.binds.grpc;
  check('R3: RPC use needs binds.grpc', lint(m4).some((i) => i.rule === 'R3' && i.path === 'binds.grpc'));
  const m5 = clone(GOOD); m5.binds.consul = '@self';
  check('R3: "@self" is a valid identity', !rules(lint(m5)).includes('R3'));
}

// ---------- R7 ----------
{
  const m = clone(GOOD); m.layer = 'operator'; m.component = 'operator.bench';
  m.tiles[0].fields[0] = { label: 'Heater', device: 'nidaq_dev0/ai3' };
  check('R7: an operator module naming a device is refused', lint(m).some((i) => i.rule === 'R7'));
  const m2 = clone(GOOD); m2.tiles[0].fields[0] = { label: 'Raw', device: 'nidaq_dev0/ai3' };
  check('R7: a bits module may name a device', !rules(lint(m2)).includes('R7'));
}

// ---------- R8 ----------
{
  const m = clone(GOOD); m.layer = 'hardware';
  check('R8: unknown layer refused', lint(m).some((i) => i.rule === 'R8' && i.path === 'layer'));
  const m2 = clone(GOOD); m2.component = 'signals.power-supply';
  check('R8: id must carry its layer', lint(m2).some((i) => i.rule === 'R8' && i.path === 'component'));
  const m3 = clone(GOOD); m3.tiles[1].id = 'out';
  check('R8: duplicate tile id refused', lint(m3).some((i) => i.rule === 'R8' && /duplicate tile/.test(i.message)));
  const both = C.lintComponents([clone(GOOD), clone(GOOD)], { schema });
  check('R8: duplicate component id on one bench refused', both.some((i) => i.rule === 'R8' && /duplicate component/.test(i.message)));
}

// ---------- R9 ----------
{
  const m = clone(GOOD); m.requires.shell = '^3.0';
  check('R9: ^3.0 refused by shell 2.3', lint(m).some((i) => i.rule === 'R9' && /needs shell/.test(i.message)));
  const m2 = clone(GOOD); m2.requires.shell = '*';
  check('R9: "*" must be pinned', lint(m2).some((i) => i.rule === 'R9' && /pin/.test(i.message)));
  const m3 = clone(GOOD); m3.requires.shell = 'latest';
  check('R9: unreadable range refused', lint(m3).some((i) => i.rule === 'R9' && /cannot read/.test(i.message)));
  check('R9: ^2.3 accepted by 2.3.0', C.satisfies('^2.3', '2.3.0') === true);
  check('R9: ^2.3 accepted by 2.9.1', C.satisfies('^2.3', '2.9.1') === true);
  check('R9: ^2.4 refused by 2.3.0', C.satisfies('^2.4', '2.3.0') === false);
  check('R9: ~2.3.1 refused by 2.4.0', C.satisfies('~2.3.1', '2.4.0') === false);
  check('R9: >=2.0 accepted by 3.1.0', C.satisfies('>=2.0', '3.1.0') === true);
  check('R9: ^0.2.1 refused by 0.3.0', C.satisfies('^0.2.1', '0.3.0') === false);
  check('R9: exact 2.3.0', C.satisfies('2.3.0', '2.3.0') === true && C.satisfies('2.3.0', '2.3.1') === false);
}

// ---------- kinds ----------
{
  const m = clone(GOOD); m.tiles[0] = { id: 'u', size: '2x1', kind: 'uds-console' };
  const issues = lint(m, { knownPluginKinds: { 'uds-console': 'uds-console' } });
  check('K: a plugin kind that is not enabled is a warning, not an error',
        issues.some((i) => i.rule === 'K' && i.severity === 'warn' && /uds-console plugin/.test(i.message)) && !C.hasErrors(issues), issues);
  const kinds = { 'uds-console': { plugin: 'uds-console', schema: { type: 'object', required: ['request'] } } };
  check('K: an enabled plugin kind is validated against its schema',
        lint(m, { kinds }).some((i) => i.rule === 'S' && i.path === 'tiles[0].request'));
  const m2 = clone(GOOD); m2.renderer = 'html';
  check('K: non-schema renderer warns until frames land', lint(m2).some((i) => i.rule === 'K' && /renderer/.test(i.message)));
}

// ---------- plugins ----------
{
  const P = { plugin: 'charts', version: '1.0.0', title: 'Charts', isolation: 'frame',
              requires: { shell: '^2.3', capabilities: ['signals.subscribe'] },
              contributes: { kinds: [{ kind: 'signal-strip', entry: 'strip.js', schema: { type: 'object' }, needs: ['signals.subscribe'] }] } };
  check('plugin: good manifest has no issues', C.lintPlugin(P, { schema: pluginSchema }).length === 0, C.lintPlugin(P, { schema: pluginSchema }));
  const P2 = clone(P); P2.requires.capabilities.push('process.spawn');
  check('plugin: process.spawn needs window isolation', C.lintPlugin(P2, { schema: pluginSchema }).some((i) => i.rule === 'R1'));
  const P3 = clone(P); P3.isolation = 'window';
  check('plugin: window isolation needs main', C.lintPlugin(P3, { schema: pluginSchema }).some((i) => i.path === 'main'));
}

// ---------- every shipped component must lint clean ----------
{
  const servicesDir = path.join(GUI, 'web', 'services');
  const shipped = fs.readdirSync(servicesDir)
    .map((d) => path.join(servicesDir, d, 'component.json'))
    .filter((p) => fs.existsSync(p));
  check('at least one shipped component exists', shipped.length >= 1, shipped);
  shipped.forEach((p) => {
    const issues = lint(JSON.parse(fs.readFileSync(p, 'utf-8')));
    check('shipped ' + path.relative(GUI, p) + ' lints without errors', !C.hasErrors(issues), issues.map(C.formatIssue));
  });
}

console.log('\n' + passes + ' passed, ' + failures + ' failed');
process.exit(failures ? 1 : 0);
