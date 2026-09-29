// Qt tile kinds (qml, widget, wasm): the contract, how a ServiceBridge call
// becomes a gRPC request and back, and how QtBridge.js routes calls.
//   node test/endo/test_endo_qt.js      (from the GUI folder)
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const C = require('../../web/js/endo/contract/lint.js');

const GUI = path.join(__dirname, '..', '..');
const DIR = path.join(GUI, 'web', 'js', 'endo', 'contract');
const componentSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'component.schema.json'), 'utf-8'));
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf-8'));

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}
const clone = (o) => JSON.parse(JSON.stringify(o));
const lint = (m) => C.lintComponent(m, { schema: componentSchema });

/** Load a browser script with a stand-in window and document. */
function load(file, extra) {
  const listeners = {};
  const window = { MicroserviceManager: {} };
  const document = {
    addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); }
  };
  const sandbox = Object.assign({ window, document, console, URL, TextEncoder }, extra || {});
  vm.runInNewContext(fs.readFileSync(path.join(GUI, 'web', 'js', file), 'utf-8'), sandbox);
  return { window, MM: window.MicroserviceManager, fire: (type, target) => (listeners[type] || []).forEach((f) => f({ target })) };
}

const QT = {
  component: 'operator.qt', version: '1.0.0', layer: 'operator', title: 'Qt',
  requires: { shell: '^2.3', capabilities: ['grpc.call'] },
  binds: { consul: '@self', grpc: 'hello.v1.HelloService' },
  tiles: [{ id: 'ui', size: '2x2', kind: 'qml', entry: 'qt/panel.qml' }],
  renderer: 'qml'
};

// ---------- contract ----------
{
  check('a qml tile lints clean', lint(QT).length === 0, lint(QT).map(C.formatIssue));
  const hello = readJson(path.join(GUI, 'web', 'services', 'HelloService1.0.0', 'component.json'));
  const q = hello.tiles.filter((t) => t.kind === 'qml')[0];
  check('Hello ships its QML tile', q && fs.existsSync(path.join(GUI, 'web', 'services', 'HelloService1.0.0', q.entry)));
  check('Hello keeps its QML file out of the folder top (the classic panel stays HTML)', q && q.entry.indexOf('/') > 0);
  check('Hello lints clean with it', lint(hello).length === 0, lint(hello).map(C.formatIssue));

  const w = clone(QT); w.tiles[0] = { id: 'ui', size: '2x2', kind: 'widget', entry: 'ServiceUI.ui' }; w.renderer = 'widget';
  check('a widget tile lints clean', lint(w).length === 0, lint(w).map(C.formatIssue));
  const bad = clone(QT); bad.tiles[0].entry = 'panel.html';
  check('a qml entry must be a .qml file', lint(bad).some((i) => i.rule === 'S'));
  const up = clone(QT); up.tiles[0].entry = '../other/panel.qml';
  check('a qml entry cannot leave the component folder', lint(up).some((i) => i.rule === 'S'));
  const noEntry = clone(QT); delete noEntry.tiles[0].entry;
  check('a qml tile needs an entry', lint(noEntry).some((i) => i.rule === 'S'));
  const noCap = clone(QT); noCap.requires.capabilities = [];
  check('a Qt tile calls the service: grpc.call is required', lint(noCap).some((i) => i.rule === 'R1' && i.severity === 'error'));
  const noGrpc = clone(QT); delete noGrpc.binds.grpc;
  check('... and binds.grpc', lint(noGrpc).some((i) => i.rule === 'R3' && /binds\.grpc/.test(i.path)));
  check('grpc.call is not reported as unused', !lint(QT).some((i) => /declared but nothing calls/.test(i.message)));

  const tall = clone(QT); tall.tiles[0].minHeight = 520;
  check('a Qt tile may set minHeight (px)', lint(tall).length === 0, lint(tall).map(C.formatIssue));
  const tooTall = clone(QT); tooTall.tiles[0].minHeight = 5000;
  check('minHeight is bounded', lint(tooTall).some((i) => i.rule === 'S' && /minHeight/.test(i.path)));

  const wasm = clone(QT); wasm.tiles[0] = { id: 'ui', size: '2x2', kind: 'wasm', entry: 'myui.js' }; wasm.renderer = 'wasm';
  const wi = lint(wasm);
  check('a wasm tile passes with a warning that its script is not sandboxed',
        !C.hasErrors(wi) && wi.some((i) => i.rule === 'K' && i.severity === 'warn' && /not sandboxed/.test(i.message)), wi.map(C.formatIssue));
  const wasmBad = clone(wasm); wasmBad.tiles[0].entry = 'myui.wasm';
  check('a wasm entry is the loader .js', lint(wasmBad).some((i) => i.rule === 'S'));

  const none = clone(QT); none.renderer = 'widget';
  check('renderer widget without widget tiles warns', lint(none).some((i) => i.rule === 'K' && /widget tiles/.test(i.message)));
  const schema = clone(QT); schema.renderer = 'schema';
  check('renderer schema with a qml tile is fine', lint(schema).length === 0, lint(schema).map(C.formatIssue));
}

// ---------- ServiceBridge call -> gRPC request -> answer ----------
{
  const { MM } = load('endo/kinds-qt.js');
  const K = MM.endo.qtKinds;
  check('the three kinds are registered', ['qml', 'widget', 'wasm'].every((k) => typeof MM.endo.kinds[k].render === 'function'));

  const described = [];
  const ctx = {
    describe: (m) => {
      described.push(m);
      return Promise.resolve({ input_fields: [
        { name: 'name', type: 'string' }, { name: 'count', type: 'int32' },
        { name: 'on', type: 'bool' }, { name: 'tags', type: 'string', label: 'repeated' }] });
    }
  };
  const cases = [
    [[], {}, 'no args: an empty request'],
    [[{ payload: 'x' }], { payload: 'x' }, 'one object: the request itself'],
    [{ payload: 'y' }, { payload: 'y' }, 'an object (not a list): the request itself'],
    [['bench'], { name: 'bench' }, 'positional: the fields in order'],
    [['a', '5', 'true', 'p, q'], { name: 'a', count: 5, on: true, tags: ['p', 'q'] }, 'positional values take the field types'],
    [['a', 'x5'], { name: 'a', count: 'x5' }, 'a value that is not a number stays as sent'],
    [['a', 1, false, '["r"]'], { name: 'a', count: 1, on: false, tags: ['r'] }, 'a JSON list for a repeated field']
  ];
  Promise.all(cases.map((c) => K.toRequest(ctx, 'Greet', c[0]).then((req) => {
    check('toRequest: ' + c[2], JSON.stringify(req) === JSON.stringify(c[1]), req);
  }))).then(() => {
    check('reflection is only asked for positional args', described.length === 4, described);
    return K.toRequest(ctx, 'Greet', ['a', 1, true, 'x', 'extra']).then(
      () => check('too many values is an error', false),
      (e) => check('too many values is an error', /takes 4 field\(s\); the UI sent 5/.test(e.message), e.message));
  }).then(() => {
    check('replyText: one scalar field is its value', K.replyText({ message: 'Hello, bench!' }) === 'Hello, bench!');
    check('replyText: an empty field is empty text', K.replyText({ payload: null }) === '');
    check('replyText: several fields are JSON', K.replyText({ a: 1, b: 2 }) === '{"a":1,"b":2}');
    check('replyText: a nested field is JSON', K.replyText({ a: { b: 1 } }) === '{"a":{"b":1}}');
    check('replyText: nothing is empty text', K.replyText(undefined) === '');

    // ---------- QtBridge routing ----------
    const calls = [];
    const B = load('QtBridge.js');
    const MMB = B.MM;
    MMB.servicesInfor = { Legacy: { routing_key: 'rk.legacy' } };
    MMB.requestService = (req, ex, rk) => { calls.push(['broker', rk, req.method]); return Promise.resolve({ result_data: 'ok' }); };
    MMB.qtBridge.install();
    const cm = B.window.callMicroservice;
    const tileA = { contains: (t) => t === 'inA' };
    const tileB = { contains: (t) => t === 'inB' };
    const a = MMB.qtBridge.addRoute(tileA, (m) => { calls.push(['A', m]); return Promise.resolve(); });
    const b = MMB.qtBridge.addRoute(tileB, (m) => { calls.push(['B', m]); return Promise.resolve(); });
    check('each route gets its own token', a.token !== b.token && /^endo-tile-\d+$/.test(a.token));
    cm(b.token, 'M1', []);
    B.fire('pointerdown', 'inA');
    cm(b.token, 'M2', []);
    check('a call with a tile token goes to that tile, wherever the last click was',
          JSON.stringify(calls) === JSON.stringify([['B', 'M1'], ['B', 'M2']]), calls);
    calls.length = 0;
    cm('HardCoded', 'M3', []);
    B.fire('pointerdown', 'inB');
    cm('HardCoded', 'M4', []);
    check('a hard-coded name goes to the tile last clicked', JSON.stringify(calls) === JSON.stringify([['A', 'M3'], ['B', 'M4']]), calls);
    calls.length = 0;
    B.fire('pointerdown', 'elsewhere');
    cm('Legacy', 'M5', []);
    check('after a click outside every tile, calls take the broker path', JSON.stringify(calls) === JSON.stringify([['broker', 'rk.legacy', 'M5']]), calls);
    calls.length = 0;
    B.fire('focusin', 'inA');
    a.remove();
    cm(a.token, 'M6', []).catch(() => {});
    check('a removed tile gets no calls', !calls.some((c) => c[0] === 'A'), calls);
    check('install keeps one bridge', (MMB.qtBridge.install(), B.window.callMicroservice === cm));
    b.remove();
    return multiService();
  }).then(() => {
    console.log('\n' + passes + ' passed, ' + failures + ' failed');
    process.exit(failures ? 1 : 0);
  }).catch((e) => { console.log('FAIL (exception)', e && e.stack); process.exit(1); });
}

// ---------- one binary, several proto services (binds.grpc as a list) ----------
function multiService() {
  const H = load('endo/host.js');
  const sent = [];
  H.MM.grpcClient = {
    callMethod: (o) => { sent.push([o.grpcService, o.method]); return Promise.resolve({ ok: true, result: {} }); },
    getServiceMethods: () => Promise.resolve({ grpc_services: [
      { name: 'power_device.PowerSupplyService', methods: [{ name: 'SetVoltage', input_fields: [{ name: 'channel' }] }] },
      { name: 'config_device.ConfigDeviceService', methods: [{ name: 'SetDeviceType', input_fields: [{ name: 'index' }] }] }] })
  };
  const m = { component: 'bits.power', requires: { capabilities: ['grpc.call'] },
              binds: { consul: '@self', grpc: ['power_device.PowerSupplyService', 'config_device.ConfigDeviceService'] } };
  const ctx = H.MM.endo.makeCtx(m, { consulName: 'bits_platform_power_service' });
  check('ctx lists the bound services, the default first',
        JSON.stringify(ctx.services) === JSON.stringify(m.binds.grpc), ctx.services);
  return ctx.call('SetVoltage', {})
    .then(() => ctx.call('config_device.ConfigDeviceService/SetDeviceType', { index: 1 }))
    .then(() => {
      check('a plain method goes to the first service; "<service>/<Method>" to that one',
            JSON.stringify(sent) === JSON.stringify([['power_device.PowerSupplyService', 'SetVoltage'],
                                                     ['config_device.ConfigDeviceService', 'SetDeviceType']]), sent);
      return ctx.call('other.Service/X').then(() => check('a service that is not bound is refused', false),
        (e) => check('a service that is not bound is refused', e.code === 'NotBound' && sent.length === 2, e.message));
    })
    .then(() => ctx.describe('config_device.ConfigDeviceService/SetDeviceType'))
    .then((d) => {
      check('describe finds a method of the second service', d && d.input_fields[0].name === 'index', d);
      return ctx.describe('SetDeviceType').then(() => check('describe of a plain name looks in the first service only', false),
        (e) => check('describe of a plain name looks in the first service only', /not a method of power_device\.PowerSupplyService/.test(e.message), e.message));
    })
    .then(() => {
      const one = H.MM.endo.makeCtx({ requires: { capabilities: ['grpc.call'] }, binds: { consul: 'x', grpc: 'hello.v1.HelloService' } }, {});
      sent.length = 0;
      return one.call('Greet', {}).then(() => check('a single bound service still works as before',
        JSON.stringify(sent) === JSON.stringify([['hello.v1.HelloService', 'Greet']]), sent));
    });
}
