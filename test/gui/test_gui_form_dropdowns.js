// command-form dropdowns: fixed choices (options), choices read from the
// service (optionsFrom: a count + a name per index, an argument read from
// another RPC), the current value preselected, reload, the automatic reload
// of a linked dropdown in another tile (reloadAfter), and the typed value
// sent on submit. The tiles are rendered in the real page with a stand-in
// ctx that answers like a device service with a configuration service.
'use strict';

const { probe, sleep } = require('./harness');

const CFG = 'config_device.ConfigDeviceService/';
const TILES = [
  { id: 'set-device-type', size: '1x1', kind: 'command-form', title: 'Set device type', call: CFG + 'SetDeviceType',
    submitLabel: 'Set device type',
    form: { index: { type: 'int', label: 'Index',
      optionsFrom: { count: { rpc: CFG + 'GetDeviceType_ListCount', path: 'index' },
                     name: { rpc: CFG + 'GetDeviceType_Name', arg: 'index', path: 'name' } },
      current: { rpc: CFG + 'GetDeviceType', path: 'index' },
      reloadAfter: [CFG + 'SetDeviceType'] } } },
  { id: 'set-sub-device-type', size: '1x1', kind: 'command-form', title: 'Set sub device type', call: CFG + 'SetSubDeviceType',
    submitLabel: 'Set sub device type',
    form: { index: { type: 'int', label: 'Index',
      optionsFrom: { count: { rpc: CFG + 'GetSubDeviceType_ListCount', path: 'index',
                              args: { index: { $from: { rpc: CFG + 'GetDeviceType', path: 'index' } } } },
                     name: { rpc: CFG + 'GetSubDeviceType_Name', arg: 'index', path: 'name' } },
      current: { rpc: CFG + 'GetSubDeviceType', path: 'index' },
      reloadAfter: [CFG + 'SetDeviceType', CFG + 'SetSubDeviceType'] } } },
  { id: 'set-interface-type', size: '1x1', kind: 'command-form', title: 'Set interface type', call: CFG + 'SetInterfaceType',
    submitLabel: 'Set interface type',
    form: { type: { type: 'int', label: 'Type',
      options: [{ value: 0, label: 'RS232' }, { value: 1, label: 'client' }, { value: 2, label: 'NI-Visa' },
                { value: 3, label: 'AG-Visa' }, { value: 4, label: 'Extern-API' }],
      current: { rpc: CFG + 'GetInterfaceType', path: 'type' } } } },
];

// The page side: a stand-in service and the three tiles mounted on it.
const MOUNT = `(function (tiles) {
  // Indexes from 0, counts are counts: like the real BITS services.
  var state = { device: 1, sub: 1, iface: 1, devices: ['Demo', 'Keithley 2200', 'TTi CPX400'],
                subs: { 0: ['default'], 1: ['single', 'dual'], 2: ['A', 'B', 'C'] } };
  var calls = window.__calls = [];
  var watchers = [];
  var M = ${JSON.stringify(CFG)};
  var answers = {
    GetDeviceType_ListCount: function () { return { errorcode: 0, index: state.devices.length }; },
    GetDeviceType_Name: function (a) { return { errorcode: 0, name: state.devices[a.index] || '' }; },
    GetDeviceType: function () { return { errorcode: 0, index: state.device }; },
    GetSubDeviceType_ListCount: function (a) { return { errorcode: 0, index: (state.subs[a.index] || []).length }; },
    GetSubDeviceType_Name: function (a) { return { errorcode: 0, name: (state.subs[state.device] || [])[a.index] || '' }; },
    GetSubDeviceType: function () { return { errorcode: 0, index: state.sub }; },
    GetInterfaceType: function () { return { type: state.iface }; },
    SetDeviceType: function (a) { state.device = a.index; return { errorcode: 0 }; },
    SetSubDeviceType: function (a) { state.sub = a.index; return { errorcode: 0 }; },
    SetInterfaceType: function (a) { state.iface = a.type; return { errorcode: 0 }; }
  };
  var ctx = {
    call: function (rpc, args) {
      calls.push({ rpc: rpc, args: args || {} });
      var fn = answers[rpc.slice(M.length)];
      return new Promise(function (ok, bad) {
        setTimeout(function () { fn ? ok({ result: fn(args || {}) }) : bad(new Error('no such method ' + rpc)); }, 5);
      }).then(function (d) {
        watchers.slice().forEach(function (w) { w(rpc, args || {}); });
        return d;
      });
    },
    // Like host.js: every successful call of the component, from any tile.
    onCall: function (fn) {
      watchers.push(fn);
      return function () { watchers.splice(watchers.indexOf(fn), 1); };
    },
    describe: function () { return Promise.reject(new Error('not used')); },
    confirm: function () { return Promise.resolve(true); }
  };
  window.__state = state;
  var host = document.createElement('div');
  host.id = 'probeTiles';
  host.style.cssText = 'position:fixed;left:20px;top:80px;z-index:99999;width:420px;background:#fff;padding:8px';
  document.body.appendChild(host);
  tiles.forEach(function (t) {
    var el = document.createElement('div');
    el.id = 'tile-' + t.id;
    el.style.marginBottom = '10px';
    host.appendChild(el);
    MicroserviceManager.endo.kinds['command-form'].render(el, t, ctx);
  });
  return true;
})(${JSON.stringify(TILES)})`;

const options = (g, tile) => g.js(`[].map.call(document.querySelectorAll('#tile-${tile} select option'), function (o) {
  return { value: o.value, label: o.textContent, selected: o.selected }; })`);
const selected = (g, tile) => g.js(`(document.querySelector('#tile-${tile} select') || {}).value`);

probe('GUI probe: command-form dropdowns', async (t) => {
  const g = await t.open({ query: { view: 'user' } });
  t.check('the page mounted the three forms', (await g.js(MOUNT)) === true);
  const loaded = await g.waitFor(async () => (await g.js(
    "[].every.call(document.querySelectorAll('#probeTiles select'), function (s) { return !s.disabled && !/Loading/.test(s.textContent); })")) === true, 8000);
  t.check('dropdowns finished loading', loaded);

  // Device types: a count (0..count-1) named one by one, the current one selected.
  const dev = await options(g, 'set-device-type');
  t.check('device types listed from the service', dev.map((o) => o.label).join('|') === '0 · Demo|1 · Keithley 2200|2 · TTi CPX400', dev);
  t.check('no index past the end was asked for',
          (await g.js("window.__calls.filter(function (c) { return /_Name$/.test(c.rpc) && c.args.index >= 3; }).length")) === 0);
  t.check('current device type preselected', (await selected(g, 'set-device-type')) === '1');

  // Sub-device types depend on the device type: the count got index=1 from GetDeviceType.
  const subCount = await g.js(`window.__calls.filter(function (c) { return /GetSubDeviceType_ListCount$/.test(c.rpc); })[0]`);
  t.check('sub-device count asked for the selected device type', subCount && subCount.args.index === 1, subCount);
  const sub = await options(g, 'set-sub-device-type');
  t.check('sub-device types listed (0..count-1)', sub.map((o) => o.label).join('|') === '0 · single|1 · dual', sub);
  t.check('current sub-device type preselected', (await selected(g, 'set-sub-device-type')) === '1');

  // Fixed choices with the current one from the service.
  const ifc = await options(g, 'set-interface-type');
  t.check('interface types from the fixed list', ifc.length === 5 && ifc[0].label === 'RS232' && ifc[4].label === 'Extern-API', ifc);
  t.check('current interface type preselected', (await selected(g, 'set-interface-type')) === '1');

  // Pick with the keyboard and submit with the mouse: the typed value is sent.
  await g.js("document.querySelector('#tile-set-device-type select').focus(); true");
  await g.key('Down');
  t.check('keyboard moves the choice to the next device', (await selected(g, 'set-device-type')) === '2');
  await g.click('#tile-set-device-type button[type="submit"]');
  await g.waitFor(() => g.js("/Done/.test(document.querySelector('#tile-set-device-type .endo-result').textContent)"), 5000);
  const sent = await g.js("window.__calls.filter(function (c) { return /SetDeviceType$/.test(c.rpc); }).pop()");
  t.check('SetDeviceType sent the chosen index as a number', sent && sent.args.index === 2 && typeof sent.args.index === 'number', sent);

  // Linked tiles: the sub-device list follows the new device type (2 -> A, B, C)
  // by itself, without its reload button (reloadAfter SetDeviceType).
  const followed = await g.waitFor(async () => (await options(g, 'set-sub-device-type')).length === 3, 5000);
  const sub2 = await options(g, 'set-sub-device-type');
  t.check('sub-device list reloads itself after Set device type', followed && sub2.map((o) => o.label).join('|') === '0 · A|1 · B|2 · C', sub2);
  t.check('the device-type dropdown still shows the one just set', (await selected(g, 'set-device-type')) === '2');

  // Reload button: the service changed behind the GUI's back.
  await g.js("window.__state.subs[2] = ['A', 'B', 'C', 'D']; true");
  await g.click('#tile-set-sub-device-type [data-reload]');
  await g.waitFor(async () => (await options(g, 'set-sub-device-type')).length === 4, 5000);
  t.check('reload button reads the list again', (await options(g, 'set-sub-device-type')).length === 4);

  await g.js("document.querySelector('#tile-set-interface-type select').value = '2'; true");
  await g.click('#tile-set-interface-type button[type="submit"]');
  await sleep(200);
  t.check('fixed choice sent typed', (await g.js('window.__state.iface')) === 2);
  await g.screenshot('form-dropdowns');
});
