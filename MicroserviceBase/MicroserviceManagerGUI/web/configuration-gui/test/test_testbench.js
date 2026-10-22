// Testbench configuration: schema form, hub client errors, store workflow.
//   node test/test_testbench.js      (from web/configuration-gui)
'use strict';

const path = require('path');
const js = (f) => path.join(__dirname, '..', 'js', f);
const SF = require(js('SchemaForm.js'));
const Client = require(js('ConfigHubClient.js'));
const HubMock = require(js('HubMock.js'));
const { createStore } = require(js('TestbenchStore.js'));
const InfraStore = require(js('InfraStore.js'));
const Common = require(js('ConfigCommon.js'));

const BaseView = require(js('ConfigBaseView.js'));

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}

// ---------------------------------------------------------------- common
(function commonTests() {
  const obj = { b: 2, a: 1, arr: [1, 2] };
  const cl = Common.clone(obj);
  check('common clone', cl.b === 2 && cl !== obj);
  check('common canon sorts keys', Common.canon({ z: 1, a: 2 }) === '{"a":2,"z":1}');
  check('common canon nested', Common.canon({ x: { b: 2, a: 1 } }) === '{"x":{"a":1,"b":2}}');
  check('common splitList', Common.splitList('  dc1,  dc2 , , dc3  ').join(',') === 'dc1,dc2,dc3');
  check('common isDirty when new', Common.isDirty({ isNew: true }, () => ({})));
  check('common isDirty matches baseline', !Common.isDirty({ baseline: '{"a":1}' }, () => ({ a: 1 })));
  check('common canSave', Common.canSave({ readOnly: false, saving: false }, true, true));
  check('common canSave blocked if saving', !Common.canSave({ readOnly: false, saving: true }, true, true));
  const errObj = Common.saveErrorOf({ code: 'ALREADY_EXISTS', message: 'exists' });
  check('common saveErrorOf', errObj.code === 'ALREADY_EXISTS' && errObj.message === 'exists');
  const em = Common.createEmitter();
  let received = null;
  const unsub = em.subscribe((st) => { received = st; });
  em.emit('hello');
  check('common emitter fires', received === 'hello');
  unsub();
  em.emit('world');
  check('common emitter unsubscribe', received === 'hello');

  // Base view contract
  const dummyStore = { isDirty: () => false, isChanged: () => false, state: { list: { items: [] } } };
  const bv = BaseView.createBaseView({
    idPrefix: 'test',
    title: 'Test View',
    createStore: () => dummyStore
  });
  check('base view instance created', typeof bv.activate === 'function' && typeof bv.isDirty === 'function');
  check('base view store resolution', bv.getStore() === null);
  bv.init();
  check('base view initialized store', bv.getStore() === dummyStore);
  check('base view not dirty initially', !bv.isDirty());

  // Toast notice helper contract
  check('common toast exports exist', typeof Common.renderToastNotice === 'function' && typeof Common.dismissToast === 'function');
  check('common renderToastNotice null notice', Common.renderToastNotice(null) === null);
  check('common renderToastNotice returns null when document undefined', Common.renderToastNotice({ kind: 'info', text: 'hi' }) === null);
  let dismissedFired = false;
  Common.dismissToast(null, () => { dismissedFired = true; });
  check('common dismissToast null safe', !dismissedFired);
})();

// ---------------------------------------------------------------- schema
const SCHEMA = {
  type: 'object',
  required: ['channels', 'port'],
  properties: {
    channels: { type: 'integer', default: 4, minimum: 1, maximum: 8, description: 'How many channels' },
    port: { type: 'string', enum: ['usb', 'serial'], default: 'usb' },
    gain: { type: 'number', exclusiveMinimum: 0, exclusiveMaximum: 10 },
    legacy: { type: 'number', minimum: 0, exclusiveMinimum: true },
    verbose: { type: 'boolean', default: false },
    label: { type: 'string', minLength: 2, pattern: '^[a-z]+$' },
    extras: { type: 'object' }
  }
};

(function schemaTests() {
  const d = SF.defaults(SCHEMA);
  check('defaults prefill', d.channels === 4 && d.port === 'usb' && d.verbose === false && !('gain' in d), d);
  const f = SF.fields(SCHEMA);
  check('field types', f.map((x) => x.type).join() === 'integer,string,number,number,boolean,string,json');
  check('description kept as hint', f[0].description === 'How many channels');
  check('required flags', f[0].required && f[1].required && !f[2].required);

  const ev = (raw) => SF.evaluate(SCHEMA, Object.assign({ channels: '4', port: 'usb' }, raw));
  check('valid input', Object.keys(ev({}).errors).length === 0, ev({}));
  check('integer parsed to number', ev({ channels: '3' }).values.channels === 3);
  check('integer rejects fraction', /integer/.test(ev({ channels: '2.5' }).errors.channels || ''));
  check('integer rejects text', !!ev({ channels: 'abc' }).errors.channels);
  check('minimum inclusive ok', !ev({ channels: '1' }).errors.channels);
  check('below minimum', /≥ 1/.test(ev({ channels: '0' }).errors.channels || ''));
  check('above maximum', /≤ 8/.test(ev({ channels: '9' }).errors.channels || ''));
  check('enum rejects', /one of/.test(ev({ port: 'bt' }).errors.port || ''));
  check('enum ok', !ev({ port: 'serial' }).errors.port);
  check('exclusiveMinimum numeric rejects bound', /> 0/.test(ev({ gain: '0' }).errors.gain || ''));
  check('exclusiveMinimum numeric accepts above', !ev({ gain: '0.1' }).errors.gain);
  check('exclusiveMaximum numeric rejects bound', /< 10/.test(ev({ gain: '10' }).errors.gain || ''));
  check('draft-4 boolean exclusive', /> 0/.test(ev({ legacy: '0' }).errors.legacy || ''));
  check('required missing', ev({ channels: '' }).errors.channels === 'is required');
  check('optional empty omitted', !('gain' in ev({ gain: '' }).values) && !ev({ gain: '' }).errors.gain);
  check('boolean value', ev({ verbose: true }).values.verbose === true);
  check('string minLength', !!ev({ label: 'a' }).errors.label);
  check('string pattern', /match/.test(ev({ label: 'AB' }).errors.label || ''));
  check('json field invalid', ev({ extras: '{bad' }).errors.extras === 'must be valid JSON');
  check('json field parsed', ev({ extras: '{"a":1}' }).values.extras.a === 1);
  check('unknown keys preserved', SF.evaluate(SCHEMA, { channels: 1, port: 'usb', other: 7 }).values.other === 7);
  check('no schema: no fields', SF.fields(null).length === 0 && Object.keys(SF.defaults(undefined)).length === 0);
})();

// -------------------------------------------------------------- client
(function clientTests() {
  check('classify unavailable', Client.classify('Service \'x\' not found in Consul') === 'UNAVAILABLE');
  check('classify NOT_FOUND', Client.classify('_InactiveRpcError StatusCode.NOT_FOUND details = "no"') === 'NOT_FOUND');
  check('classify ALREADY_EXISTS', Client.classify('StatusCode.ALREADY_EXISTS') === 'ALREADY_EXISTS');
  check('classify INVALID_ARGUMENT', Client.classify('StatusCode.INVALID_ARGUMENT details = "bad"') === 'INVALID_ARGUMENT');
  check('classify UNAVAILABLE status', Client.classify('StatusCode.UNAVAILABLE failed to connect') === 'UNAVAILABLE');
  check('reason extracted', Client.reasonOf('StatusCode.INVALID_ARGUMENT details = "node is empty"') === 'node is empty');
})();

// --------------------------------------------------------------- fakes
const MODELS = {
  'relay-8': {
    catalog_id: 'relay-8', manufacturer: 'Acme', model: 'R8', description: 'Relay',
    adapter: 'acme_relay', static_config: { channels: 8 }, capabilities: ['relay'],
    user_config_schema: SCHEMA
  },
  'plain': {
    catalog_id: 'plain', manufacturer: 'Foo', model: 'P', description: '',
    adapter: 'plain', static_config: {}, capabilities: ['x'], user_config_schema: null
  }
};

function err(service, code, text) {
  const e = new Error(text || code);
  e.service = service; e.code = code; e.reason = text || '';
  return e;
}

function fakeApi() {
  const docs = { testbench: {}, infrastructure: {} };   // type -> id -> [versions]
  const calls = [];
  const down = { catalog: false, hub: false };
  const failNext = {};
  const api = {
    calls, down, docs, failNext, catalogVersion: 'v1', models: Object.assign({}, MODELS),
    _chk(service, op) {
      if (down[service]) return Promise.reject(err(service, 'UNAVAILABLE', service + ' down'));
      if (failNext[op]) { const e = failNext[op]; delete failNext[op]; return Promise.reject(e); }
      return null;
    },
    listDeviceModels() {
      return api._chk('catalog', 'listDeviceModels') ||
        Promise.resolve(Object.values(api.models).map((m) => ({ catalog_id: m.catalog_id, manufacturer: m.manufacturer, model: m.model, description: m.description })));
    },
    getDeviceModel(id) {
      calls.push(['getDeviceModel', id]);
      return api._chk('catalog', 'getDeviceModel') ||
        (api.models[id] ? Promise.resolve(JSON.parse(JSON.stringify(api.models[id]))) : Promise.reject(err('catalog', 'NOT_FOUND')));
    },
    getCatalogVersion() { calls.push(['getCatalogVersion']); return api._chk('catalog', 'getCatalogVersion') || Promise.resolve(api.catalogVersion); },
    listConfigurations(type) {
      const c = api._chk('hub', 'listConfigurations'); if (c) return c;
      return Promise.resolve(Object.keys(docs[type]).map((id) => {
        const vs = docs[type][id]; return { id, name: vs[vs.length - 1].name, latestVersion: vs.length, updatedAt: '' };
      }));
    },
    getConfiguration(type, id, version) {
      calls.push(['getConfiguration', type, id, version]);
      const c = api._chk('hub', 'getConfiguration'); if (c) return c;
      const vs = docs[type][id];
      if (!vs) return Promise.reject(err('hub', 'NOT_FOUND'));
      const v = version || vs.length;
      if (!vs[v - 1]) return Promise.reject(err('hub', 'NOT_FOUND'));
      return Promise.resolve({ id, name: vs[v - 1].name, version: v, payload: JSON.parse(JSON.stringify(vs[v - 1].payload)) });
    },
    getDefaultConfiguration(type) {
      calls.push(['getDefaultConfiguration', type]);
      return Promise.resolve({ id: type, name: type, version: 0, payload: { node: 'client1', datacenters: ['dc1'] } });
    },
    createConfiguration(type, id, name, payload) {
      calls.push(['create', type, id, name, payload]);
      const c = api._chk('hub', 'createConfiguration'); if (c) return c;
      if (docs[type][id]) return Promise.reject(err('hub', 'ALREADY_EXISTS', 'exists'));
      docs[type][id] = [{ name, payload }];
      return Promise.resolve({ id, name, version: 1, payload });
    },
    updateConfiguration(type, id, name, payload) {
      calls.push(['update', type, id, name, payload]);
      const c = api._chk('hub', 'updateConfiguration'); if (c) return c;
      docs[type][id] = (docs[type][id] || []).concat([{ name, payload }]);
      return Promise.resolve({ id, name, version: docs[type][id].length, payload });
    },
    deleteConfiguration(type, id) {
      calls.push(['delete', type, id]);
      const c = api._chk('hub', 'deleteConfiguration'); if (c) return c;
      if (!docs[type] || !docs[type][id]) return Promise.reject(err('hub', 'NOT_FOUND'));
      delete docs[type][id];
      return Promise.resolve({ ok: true, id });
    },
    listConfigurationVersions(type, id) {
      const c = api._chk('hub', 'listConfigurationVersions'); if (c) return c;
      return Promise.resolve((docs[type][id] || []).map((_, i) => i + 1));
    },
    renameConfiguration(type, oldId, newId, newName) {
      calls.push(['rename', type, oldId, newId, newName]);
      const c = api._chk('hub', 'renameConfiguration'); if (c) return c;
      const t = docs[type];
      if (t && t[oldId]) {
        const vs = t[oldId];
        if (newId && newId !== oldId) {
          delete t[oldId];
          t[newId] = vs;
          vs.forEach((x) => { if (x.payload) x.payload.id = newId; });
        }
        if (newName !== undefined && newName !== null) {
          vs.forEach((x) => {
            x.name = newName;
            if (x.payload) x.payload.name = newName;
          });
        }
      }
      return Promise.resolve({ ok: true, id: newId || oldId, name: newName });
    }
  };
  return api;
}

const mem = () => { const s = {}; return { getItem: (k) => (k in s ? s[k] : null), setItem: (k, v) => { s[k] = String(v); } }; };
const last = (api, op) => api.calls.filter((c) => c[0] === op).pop();

async function main() {
  // ---- list
  {
    const api = fakeApi();
    const st = createStore(api, { storage: mem() });
    await st.loadList();
    check('list empty state', st.state.list.status === 'ok' && st.state.list.items.length === 0);
    api.docs.testbench.tb1 = [{ name: 'One', payload: { id: 'tb1', name: 'One', devices: [] } }];
    await st.loadList();
    check('list shows stored testbench + version', st.state.list.items[0].id === 'tb1' && st.state.list.items[0].latestVersion === 1);
    api.down.hub = true;
    await st.loadList();
    check('list hub down is reported with retry', st.state.failure && st.state.failure.service === 'hub' && st.state.failure.canRetry);
    api.down.hub = false;
    await st.retry();
    check('retry recovers list', st.state.list.status === 'ok' && !st.state.failure);
  }

  // ---- open NOT_FOUND = not created yet
  {
    const api = fakeApi();
    const st = createStore(api, { storage: mem() });
    await st.open('ghost');
    check('NOT_FOUND opens as not created', st.state.current.isNew && st.state.notice.kind === 'info' && !st.state.failure);
  }

  // ---- create + add devices + save (create) vs update
  {
    const api = fakeApi();
    const st = createStore(api, { storage: mem() });
    await st.loadList();
    check('create rejects empty id', !st.createNew('', 'n').ok);
    check('create rejects empty name', !st.createNew('x', '').ok);
    check('create defaults name to id when omitted', st.createNew('tb_default').ok && st.state.current.name === 'tb_default');
    st.state.list.items = st.state.list.items.filter((it) => it.id !== 'tb_default');
    check('create ok', st.createNew('tb1', 'Bench 1').ok && st.state.current.isNew);
    check('create adds item to list immediately', st.state.list.items.some((it) => it.id === 'tb1' && it.isNew));
    await st.loadCatalog();
    check('catalog models listed', st.state.catalog.models.length === 2);
    await st.addDevice('relay-8');
    const dev = st.state.current.devices[0];
    check('new device pre-filled with defaults', dev.raw.channels === '4' && dev.raw.port === 'usb' && dev.raw.verbose === false, dev.raw);
    check('static_config comes from catalog', dev.static_config.channels === 8 && dev.adapter === 'acme_relay');
    check('device_id suggested unique', dev.device_id === 'relay_8');
    await st.addDevice('relay-8');
    check('second device gets other id', st.state.current.devices[1].device_id === 'relay_8_2');
    st.setDeviceId(st.state.current.devices[1].key, 'relay_8');
    check('duplicate id blocks save', !st.validate().ok && !st.canSave() && /already used/.test(st.validate().devices[st.state.current.devices[1].key].device_id));
    st.setDeviceId(st.state.current.devices[1].key, '  ');
    check('empty id blocks save', !st.canSave() && /required/.test(st.validate().devices[st.state.current.devices[1].key].device_id));
    st.removeDevice(st.state.current.devices[1].key);
    check('device removed', st.state.current.devices.length === 1);

    st.setField(dev.key, 'channels', '99');
    check('out-of-range blocks save naming field', !st.canSave() && st.validate().list.some((e) => /channels/.test(e.message)));
    const blocked = await st.save();
    check('save blocked makes no hub call', blocked.blocked && !last(api, 'create'));
    st.setField(dev.key, 'channels', '2');
    check('can save now', st.canSave() && st.isDirty());

    // Hub failure keeps input
    api.failNext.createConfiguration = err('hub', 'INVALID_ARGUMENT', 'bad device');
    const r1 = await st.save();
    check('INVALID_ARGUMENT shown, input kept', !r1.ok && st.state.current.saveError.code === 'INVALID_ARGUMENT' &&
      /bad device/.test(st.state.current.saveError.message) && st.state.current.devices[0].raw.channels === '2' && st.state.current.isNew);
    api.down.hub = true;
    await st.save();
    check('unavailable shown, input kept', st.state.current.saveError.code === 'UNAVAILABLE' && st.state.current.devices.length === 1);
    api.down.hub = false;

    const r2 = await st.save();
    const created = last(api, 'create');
    check('new testbench uses CreateConfiguration', r2.ok && r2.created && created && !last(api, 'update'));
    const sent = created[4];
    check('payload id/name/devices', sent.id === 'tb1' && sent.name === 'Bench 1' && sent.devices.length === 1);
    const sd = sent.devices[0];
    check('payload device has catalog_ref/adapter/static/user', sd.device_id === 'relay_8' && sd.catalog_ref === 'relay-8' &&
      sd.adapter === 'acme_relay' && sd.static_config.channels === 8 && sd.user_config.channels === 2 && sd.user_config.port === 'usb', sd);
    check('payload never has deployment_descriptor', !JSON.stringify(sent).includes('deployment_descriptor'));
    check('new version number shown', st.state.current.version === 1 && /version 1/.test(st.state.notice.text));
    check('not dirty after save', !st.isDirty());

    // duplicate create
    const st2 = createStore(api, { storage: mem() });
    await st2.loadList();
    check('create blocks existing id from list', !st2.createNew('tb1', 'x').ok);
    st2.state.list.items = [];
    st2.createNew('tb1', 'again');
    const r3 = await st2.save();
    check('ALREADY_EXISTS shown', !r3.ok && st2.state.current.saveError.code === 'ALREADY_EXISTS');

    // update
    st.setField(dev.key, 'channels', '3');
    check('saved device is read-only until Edit', st.isDeviceLocked(dev.key) && !st.isDirty());
    await st.startEdit(dev.key);
    check('Edit unlocks device and sets editing status', !st.isDeviceLocked(dev.key) && dev.editing);
    st.setField(dev.key, 'channels', '3');
    check('edit marks unsaved', st.isDirty());
    const r4 = await st.save();
    check('existing testbench uses UpdateConfiguration -> version 2', r4.ok && last(api, 'update')[2] === 'tb1' && st.state.current.version === 2);
    check('device locks again after save', st.isDeviceLocked(dev.key) && !dev.editing);

    // Changing name or ID on saved testbench does not mark dirty or activate save button
    st.setName('Renamed Bench');
    check('changing name does not mark dirty', !st.isDirty() && !st.canSave() && st.state.current.name === 'Renamed Bench');
    check('changing name updates list item', st.state.list.items.find((x) => x.id === 'tb1').name === 'Renamed Bench');
    st.setId('tb1_new');
    check('changing id does not mark dirty', !st.isDirty() && !st.canSave() && st.state.current.id === 'tb1_new');
    check('changing id updates list item', st.state.list.items.find((x) => x.id === 'tb1_new') !== undefined);
    st.setId('tb1'); // restore id for subsequent tests
    await st.startEdit(dev.key);
    st.setField(dev.key, 'channels', '4');
    st.setDeviceId(dev.key, 'renamed');
    st.cancelEdit(dev.key);
    check('cancel edit restores saved values and locks', !st.isDirty() && dev.device_id === 'relay_8' && dev.raw.channels === '3' && st.isDeviceLocked(dev.key));
    check('versions listed newest first', st.state.current.versions.join() === '2,1');

    // previous version read-only
    await st.openVersion(1);
    check('previous version is read-only with its data', st.state.current.readOnly && st.state.current.devices[0].savedUserConfig.channels === 2);
    st.setDeviceId(st.state.current.devices[0].key, 'hacked');
    check('read-only ignores edits and cannot save', st.state.current.devices[0].device_id === 'relay_8' && !st.canSave());

    // load version for use
    await st.loadVersionForUse(1);
    check('loaded version for use is not read-only', !st.state.current.readOnly && !st.state.current.viewingVersion);
    check('loaded version is at that version and clean', st.state.current.version === 1 && !st.isDirty() && !st.canSave());

    // Switch to another testbench and switch back - verify loaded version 1 is maintained
    api.docs.testbench.tb2 = [{ name: 'Two', payload: { id: 'tb2', name: 'Two', devices: [] } }];
    await st.open('tb2');
    check('switched to tb2', st.state.current.id === 'tb2');
    await st.open('tb1');
    check('switching back to tb1 keeps loaded version 1 and activeVersion', st.state.current.version === 1 && !st.state.current.readOnly && st.getActiveVersion('tb1') === 1);

    await st.startEdit(st.state.current.devices[0].key);
    st.setField(st.state.current.devices[0].key, 'channels', '5');
    check('dirty after editing loaded version', st.isDirty() && st.canSave());
    const r5 = await st.save();
    check('saving loaded version creates version 3', r5.ok && st.state.current.version === 3);
  }

  // ---- reopen saved testbench; catalog outage / changes
  {
    const api = fakeApi();
    api.docs.testbench.tb = [{ name: 'T', payload: { id: 'tb', name: 'T', devices: [
      { device_id: 'a', catalog_ref: 'relay-8', adapter: 'acme_relay', static_config: { channels: 8 }, user_config: { channels: 50, port: 'usb' }, deployment_descriptor: { x: 1 } },
      { device_id: 'b', catalog_ref: 'gone', adapter: 'old', static_config: {}, user_config: { k: 1 } }
    ] } }];
    const storage = mem();
    const st = createStore(api, { storage });
    api.down.catalog = true;
    await st.open('tb');
    check('catalog outage does not block viewing saved testbench', st.state.current.devices.length === 2 && !st.state.failure);
    await st.openDevice(st.state.current.devices[0].key);
    check('catalog failure reported as catalog + retry', st.state.failure.service === 'catalog' && st.state.failure.canRetry &&
      st.state.current.devices[0].schemaStatus === 'error');
    check('saved device unchanged and not dirty during outage', !st.isDirty());
    api.down.catalog = false;
    await st.retry();
    const a = st.state.current.devices[0];
    check('retry loads schema', a.schemaStatus === 'ok' && a.model.manufacturer === 'Acme');
    check('catalog change: saved out-of-range value shown, not rejected, not dirty', a.raw.channels === '50' && st.validate().ok && !st.isDirty());
    check('catalog version read on device open', api.calls.some((c) => c[0] === 'getCatalogVersion'));
    await st.openDevice(st.state.current.devices[1].key);
    check('removed model stays as saved', st.state.current.devices[1].schemaStatus === 'missing' && st.validate().ok);
    await st.startEdit(a.key);
    st.setField(a.key, 'channels', '5');
    await st.save();
    check('saved payload omits deployment_descriptor and keeps untouched device',
      !JSON.stringify(last(api, 'update')[4]).includes('deployment_descriptor') &&
      last(api, 'update')[4].devices[1].user_config.k === 1);
    // catalog changed after save
    api.catalogVersion = 'v2';
    const st3 = createStore(api, { storage });
    await st3.open('tb');
    await st3.openDevice(st3.state.current.devices[0].key);
    check('catalog changed flag is advisory', st3.state.current.catalogChanged === true && st3.validate().ok);
  }

  // ---- new model in catalog without GUI change; no schema
  {
    const api = fakeApi();
    api.models.fresh = { catalog_id: 'fresh', manufacturer: 'New', model: 'N', description: '', adapter: 'fresh_ad', static_config: {}, capabilities: ['c'],
      user_config_schema: { type: 'object', required: ['speed'], properties: { speed: { type: 'integer', minimum: 10, default: 20, description: 'rpm' } } } };
    const st = createStore(api, { storage: mem() });
    st.createNew('n', 'N');
    await st.loadCatalog();
    check('new catalog model listed', st.state.catalog.models.some((m) => m.catalog_id === 'fresh'));
    await st.addDevice('fresh');
    const d = st.state.current.devices[0];
    check('new model configurable from schema alone', d.raw.speed === '20' && st.validate().ok);
    st.setField(d.key, 'speed', '5');
    check('new model constraint applied', !st.validate().ok);
    await st.addDevice('plain');
    check('model without schema has no fields', st.state.current.devices[1].schema === null);
    api.models.fresh = null; delete api.models.fresh;
    api.down.catalog = true;
    check('add device fails cleanly on catalog outage', (await st.addDevice('plain')) === false && st.state.failure.service === 'catalog' && st.state.current.devices.length === 2);
  }

  // ---- delete testbench
  {
    const api = fakeApi();
    const st = createStore(api, { storage: mem() });
    await st.loadList();
    // 1. Delete unsaved new item
    st.createNew('del-new', 'Delete New');
    check('del-new added to list', st.state.list.items.some((it) => it.id === 'del-new'));
    check('del-new is current', st.state.current && st.state.current.id === 'del-new');
    const r1 = await st.deleteItem('del-new');
    check('delete unsaved ok', r1.ok && !st.state.list.items.some((it) => it.id === 'del-new'));
    check('current cleared after deleting active item', st.state.current === null);
    check('unsaved delete makes no hub call', !api.calls.some((c) => c[0] === 'delete'));

    // 2. Delete saved item
    api.docs.testbench['tb-saved'] = [{ name: 'Saved TB', payload: { id: 'tb-saved', name: 'Saved TB', devices: [] } }];
    await st.loadList();
    check('tb-saved is in list', st.state.list.items.some((it) => it.id === 'tb-saved'));
    await st.open('tb-saved');
    check('tb-saved is open', st.state.current && st.state.current.id === 'tb-saved');
    const r2 = await st.deleteItem('tb-saved');
    check('delete saved ok', r2.ok && !st.state.list.items.some((it) => it.id === 'tb-saved'));
    check('tb-saved removed from backend', !api.docs.testbench['tb-saved']);
    check('current cleared after deleting saved', st.state.current === null);
    check('delete call recorded', last(api, 'delete')[1] === 'testbench' && last(api, 'delete')[2] === 'tb-saved');

    // 3. Delete failure handling
    api.docs.testbench['tb-err'] = [{ name: 'Err TB', payload: { id: 'tb-err', name: 'Err TB', devices: [] } }];
    await st.loadList();
    api.failNext.deleteConfiguration = err('hub', 'UNAVAILABLE', 'down');
    const r3 = await st.deleteItem('tb-err');
    check('delete failure returns error and sets retry', !r3.ok && st.state.failure && st.state.failure.canRetry);
  }

  // ---- infrastructure (independent InfraStore)
  {
    const api = fakeApi();
    const infraSt = InfraStore.createStore(api);
    await infraSt.loadList();
    check('infra list starts empty', infraSt.state.list.items.length === 0);

    // Opening an unsaved id loads provider defaults (v0)
    await infraSt.open('tb1');
    check('default infra shown with version 0, marked default', infraSt.state.current.version === 0 && infraSt.state.current.isDefault && infraSt.state.current.node === 'client1' && infraSt.state.current.datacenters === 'dc1');
    check('default is not an unsaved edit', !infraSt.isChanged());
    check('can accept default and save', infraSt.canSave());

    // Validation
    infraSt.setNode('');
    check('empty node blocks save', !infraSt.canSave() && infraSt.validate().errors.node);
    infraSt.setNode('client2');
    infraSt.setDatacenters('dc1, dc2');
    check('valid infra can save', infraSt.canSave() && infraSt.isChanged());

    // First save creates v1 via UpdateConfiguration
    const r = await infraSt.save();
    const u = last(api, 'update');
    check('first infra save uses Update and creates version 1', r.ok && r.version === 1 && u[1] === 'infrastructure' && u[2] === 'tb1');
    check('infra payload', u[4].node === 'client2' && u[4].datacenters.join() === 'dc1,dc2');
    check('no longer default after save', !infraSt.state.current.isDefault && !infraSt.isChanged());

    // Version history
    check('versions listed', infraSt.state.current.versions.join() === '1');
    infraSt.setNode('client3');
    check('editing marks changed', infraSt.isChanged());

    // Error handling preserves input
    api.failNext.updateConfiguration = err('hub', 'INVALID_ARGUMENT', 'node unknown');
    const r2 = await infraSt.save();
    check('infra error shown, input kept', !r2.ok && infraSt.state.current.saveError.code === 'INVALID_ARGUMENT' && infraSt.state.current.node === 'client3');

    // Subsequent save creates v2
    const r3 = await infraSt.save();
    check('later save creates version 2', r3.version === 2 && infraSt.state.current.versions.join() === '2,1');

    // Changing name or ID on saved infra does not mark dirty or activate save button
    infraSt.setName('Renamed Infra');
    check('infra changing name does not mark dirty', !infraSt.isDirty() && !infraSt.canSave() && infraSt.state.current.name === 'Renamed Infra');
    check('infra changing name updates list item', infraSt.state.list.items.find((x) => x.id === 'tb1').name === 'Renamed Infra');
    infraSt.setId('tb1_new');
    check('infra changing id does not mark dirty', !infraSt.isDirty() && !infraSt.canSave() && infraSt.state.current.id === 'tb1_new');
    check('infra changing id updates list item', infraSt.state.list.items.find((x) => x.id === 'tb1_new') !== undefined);
    infraSt.setId('tb1'); // restore id for subsequent tests

    // Read-only previous version
    await infraSt.openVersion(1);
    check('previous version is read-only', infraSt.state.current.readOnly && infraSt.state.current.node === 'client2');
    infraSt.setNode('hacked');
    check('read-only cannot edit or save', infraSt.state.current.node === 'client2' && !infraSt.canSave());

    // load version for use
    await infraSt.loadVersionForUse(1);
    check('infra loaded version for use is not read-only', !infraSt.state.current.readOnly && !infraSt.state.current.viewingVersion);
    check('infra loaded version is clean initially', infraSt.state.current.version === 1 && !infraSt.isDirty() && !infraSt.canSave());

    // Switch to another infra and switch back - verify loaded version 1 is maintained
    api.docs.infrastructure.tb2 = [{ name: 'tb2', payload: { id: 'tb2', node: 'client-other', datacenters: ['dc1'] } }];
    await infraSt.open('tb2');
    check('switched to infra tb2', infraSt.state.current.id === 'tb2');
    await infraSt.open('tb1');
    check('switching back to tb1 keeps loaded version 1 and activeVersion', infraSt.state.current.version === 1 && !infraSt.state.current.readOnly && infraSt.getActiveVersion('tb1') === 1);

    check('infra loaded version can edit node', (infraSt.setNode('client-restored'), infraSt.state.current.node === 'client-restored'));
    check('infra dirty after editing', infraSt.isDirty() && infraSt.canSave());
    const r4 = await infraSt.save();
    check('saving loaded infra creates version 3', r4.version === 3);

    // Reopen saved infra
    await infraSt.open('tb1');
    check('reopened infra has latest version and is not default', infraSt.state.current.version === 3 && !infraSt.state.current.isDefault && infraSt.state.current.node === 'client-restored');

    // Delete infrastructure
    const delInfra = await infraSt.deleteItem('tb1');
    check('delete infra ok', delInfra.ok && !infraSt.state.list.items.some((it) => it.id === 'tb1'));
    check('deleted infra cleared from backend', !api.docs.infrastructure['tb1']);
    check('current cleared after deleting infra', infraSt.state.current === null);
  }

  // ---- mock catalog (catalog_device_mock/device_catalog.json)
  {
    const data = JSON.parse(require('fs').readFileSync(path.join(__dirname, '..', 'catalog_device_mock', 'device_catalog.json'), 'utf8'));
    const never = () => Promise.reject(new Error('service must not be called'));
    const c = Client.create(never, { catalogMock: { load: () => Promise.resolve(data) } });
    const list = await c.listDeviceModels();
    check('mock lists all entries as summaries', list.length === data.entries.length && list[0].catalog_id && !('adapter' in list[0]), list.length);
    const m = await c.getDeviceModel('gwinstek-psp-2010');
    check('mock entry has adapter/static/schema', m.adapter === 'PspGwInstek2010HardwareAdapter' && m.static_config.pps_channels === 1 && m.user_config_schema.properties.baudrate.minimum === 1200);
    check('mock version', (await c.getCatalogVersion()) === '1');
    let code = null; try { await c.getDeviceModel('nope'); } catch (e) { code = e.code; }
    check('mock unknown id is NOT_FOUND', code === 'NOT_FOUND');
    const bad = Client.create(never, { catalogMock: { load: () => Promise.reject(new Error('404')) } });
    code = null; try { await bad.listDeviceModels(); } catch (e) { code = e.code; }
    check('unreadable mock is a catalog UNAVAILABLE', code === 'UNAVAILABLE');
    const st = createStore(Object.assign(fakeApi(), { getDeviceModel: c.getDeviceModel, listDeviceModels: c.listDeviceModels, getCatalogVersion: c.getCatalogVersion }), { storage: mem() });
    st.createNew('m', 'M');
    await st.addDevice('conrad-relay-card-8');
    let d = st.state.current.devices[0];
    check('mock device pre-filled; required default ok', d.raw.com_port === 'auto' && d.raw.baudrate === '9600' && st.validate().ok);
    st.setField(d.key, 'com_port', '');
    check('required com_port enforced', !st.validate().ok);
    await st.addDevice('kmtronic-usb-relay-8');
    d = st.state.current.devices[1];
    check('kmtronic defaults incl. float', d.raw.timeout === '1' && d.raw.baudrate === '9600');
    st.setField(d.key, 'baudrate', '100');
    check('kmtronic baudrate minimum 1200', /≥ 1200/.test(st.validate().devices[d.key].fields.baudrate));
    st.setField(d.key, 'baudrate', '9600'); st.setField(d.key, 'timeout', '0.05');
    check('kmtronic timeout minimum 0.1', /≥ 0.1/.test(st.validate().devices[d.key].fields.timeout));
  }

  // ---- in-memory hub (UI-only mode)
  {
    const mem2 = mem();
    const hub = HubMock.create(mem2);
    const c = Client.create(() => Promise.reject(new Error('no service')), { hubMock: hub });
    const dev = { device_id: 'a', catalog_ref: 'x', adapter: 'y', static_config: {}, user_config: {} };
    check('hub mock: empty list', (await c.listConfigurations('testbench')).length === 0);
    let code = null; try { await c.getConfiguration('testbench', 't'); } catch (e) { code = e.code; }
    check('hub mock: NOT_FOUND', code === 'NOT_FOUND');
    check('hub mock: default infra v0', (await c.getDefaultConfiguration('infrastructure')).version === 0);
    check('hub mock: create v1', (await c.createConfiguration('testbench', 't', 'T', { id: 't', name: 'T', devices: [dev] })).version === 1);
    code = null; try { await c.createConfiguration('testbench', 't', 'T', { id: 't', name: 'T', devices: [] }); } catch (e) { code = e.code; }
    check('hub mock: ALREADY_EXISTS', code === 'ALREADY_EXISTS');
    code = null; try { await c.updateConfiguration('testbench', 't', 'T', { id: 't', name: 'T', devices: [dev, dev] }); } catch (e) { code = e.code; }
    check('hub mock: INVALID_ARGUMENT on duplicate device', code === 'INVALID_ARGUMENT');
    check('hub mock: update v2 + versions', (await c.updateConfiguration('testbench', 't', 'T2', { id: 't', name: 'T2', devices: [] })).version === 2 &&
      (await c.listConfigurationVersions('testbench', 't')).join() === '1,2');
    check('hub mock: old version readable', (await c.getConfiguration('testbench', 't', 1)).payload.devices.length === 1);
    check('hub mock: first infra save via update is v1', (await c.updateConfiguration('infrastructure', 't', 'T', { id: 't', node: 'n', datacenters: ['dc1'] })).version === 1);
    const again = Client.create(() => Promise.reject(new Error('no service')), { hubMock: HubMock.create(mem2) });
    check('hub mock: persists across reload', (await again.listConfigurations('testbench'))[0].latestVersion === 2);
    check('hub mock: delete existing', (await again.deleteConfiguration('testbench', 't')).ok);
    check('hub mock: deleted item is gone', (await again.listConfigurations('testbench')).length === 0);
    code = null; try { await again.getConfiguration('testbench', 't'); } catch (e) { code = e.code; }
    check('hub mock: get deleted is NOT_FOUND', code === 'NOT_FOUND');
  }

  // ---- group manager
  {
    const storage = mem();
    const gm = Common.createGroupManager('test_groups', storage);
    gm.setGroup('item1', 'Production');
    gm.setGroup('item2', 'Production');
    gm.setGroup('item3', 'Testing');
    check('group manager set and get', gm.getGroup('item1') === 'Production');
    check('group manager getGroupNames', gm.getGroupNames().join() === 'Production,Testing');
    check('group manager getAll', Object.keys(gm.getAll()).length === 3);
    gm.removeGroup('item2');
    check('group manager removeGroup', gm.getGroup('item2') === null);
    gm.renameGroup('Production', 'Prod');
    check('group manager renameGroup', gm.getGroup('item1') === 'Prod');
    gm.deleteGroup('Testing');
    check('group manager deleteGroup', gm.getGroup('item3') === null);
    check('group manager deleteGroup removes from names', gm.getGroupNames().indexOf('Testing') === -1);
    gm.removeGroup('item1');
    check('group manager removeGroup keeps empty group in names', gm.getGroupNames().indexOf('Prod') !== -1);
  }

  // ---- testbench duplicate
  {
    const api = fakeApi();
    const storage = mem();
    const store = createStore(api, { storage });
    await store.loadCatalog();
    store.createNew('tb-orig', 'Original TB');
    await store.addDevice('relay-8');
    const d1 = store.state.current.devices[0];
    store.setDeviceId(d1.key, 'r1');
    store.setField(d1.key, 'channels', '2');
    await store.save();
    check('tb-orig is version 1', store.state.current.version === 1);

    // Duplicate validation: empty id
    const badRes = await store.duplicate('tb-orig', '', 'Copy');
    check('duplicate rejects empty id', !badRes.ok);

    // Duplicate validation: existing id
    const existRes = await store.duplicate('tb-orig', 'tb-orig', 'Copy');
    check('duplicate rejects existing id', !existRes.ok);

    // Duplicate saved tb
    const dupRes = await store.duplicate('tb-orig', 'tb-orig-copy', 'Original TB Copy');
    check('duplicate saved tb ok', dupRes.ok && dupRes.id === 'tb-orig-copy');
    check('duplicated tb is active and open', store.state.current && store.state.current.id === 'tb-orig-copy');
    check('duplicated tb has version 1', store.state.current.version === 1);
    check('duplicated tb has copied devices', store.state.current.devices.length === 1 && store.state.current.devices[0].device_id === 'r1');
    check('duplicated tb is in list', store.state.list.items.some(x => x.id === 'tb-orig-copy'));

    // Duplicate draft tb
    store.createNew('tb-draft', 'Draft TB');
    await store.addDevice('relay-8');
    const d2 = store.state.current.devices[0];
    store.setDeviceId(d2.key, 'draft-dev');
    const draftDupRes = await store.duplicate('tb-draft', 'tb-draft-copy', 'Draft Copy');
    check('duplicate draft tb ok', draftDupRes.ok && draftDupRes.id === 'tb-draft-copy');
    check('duplicated draft tb has device', store.state.current.devices.length === 1 && store.state.current.devices[0].device_id === 'draft-dev');
  }

  // ---- infra duplicate
  {
    const api = fakeApi();
    const storage = mem();
    const store = InfraStore.createStore(api, { storage });
    await store.open('infra-orig');
    store.setNode('prod-node-1');
    store.setDatacenters('dc1, dc2');
    await store.save();
    check('infra-orig saved as v1', store.state.current.version === 1);

    // Duplicate validation: empty id
    const badRes = await store.duplicate('infra-orig', '', 'Copy');
    check('infra duplicate rejects empty id', !badRes.ok);

    // Duplicate validation: existing id
    const existRes = await store.duplicate('infra-orig', 'infra-orig', 'Copy');
    check('infra duplicate rejects existing id', !existRes.ok);

    // Duplicate infra
    const dupRes = await store.duplicate('infra-orig', 'infra-copy', 'Infra Copy');
    check('infra duplicate ok', dupRes.ok && dupRes.id === 'infra-copy');
    check('duplicated infra is active', store.state.current && store.state.current.id === 'infra-copy');
    check('duplicated infra has node', store.state.current.node === 'prod-node-1');
    check('duplicated infra in list', store.state.list.items.some(x => x.id === 'infra-copy'));
  }

  // ---- group migration on ID rename
  {
    const api = fakeApi();
    const storage = mem();
    storage.setItem('mm_tb_groups', JSON.stringify({ 'tb-old': 'Production' }));
    const store = createStore(api, { storage });
    await store.loadCatalog();
    store.createNew('tb-old', 'Old TB');
    await store.save();
    store.setId('tb-renamed');
    const tbGrps = JSON.parse(storage.getItem('mm_tb_groups') || '{}');
    check('tb group migrated on rename', tbGrps['tb-renamed'] === 'Production' && !tbGrps['tb-old']);

    storage.setItem('mm_infra_groups', JSON.stringify({ 'infra-old': 'Staging' }));
    const iStore = InfraStore.createStore(api, { storage });
    await iStore.open('infra-old');
    await iStore.save();
    iStore.setId('infra-renamed');
    const infraGrps = JSON.parse(storage.getItem('mm_infra_groups') || '{}');
    check('infra group migrated on rename', infraGrps['infra-renamed'] === 'Staging' && !infraGrps['infra-old']);
  }

  // ---- base view group manager and sidebar rendering
  {
    const storage = mem();
    const view = BaseView.createBaseView({ idPrefix: 'tb', storage });
    const gm = view.getGroupManager();
    check('base view has group manager', !!gm && typeof gm.setGroup === 'function');
    check('base view has promptDuplicate', typeof view.promptDuplicate === 'function');
    check('base view has promptGroup', typeof view.promptGroup === 'function');
  }

  // ---- DOM sidebar rendering with groups and option button
  {
    const storage = mem();
    storage.setItem('mm_tb_groups', JSON.stringify({ 'tb1': 'Production', 'tb2': 'Production' }));

    function findByClass(node, cls) {
      if (!node) return null;
      if (node.classList && node.classList.contains(cls)) return node;
      for (const k of (node.children || [])) {
        const res = findByClass(k, cls);
        if (res) return res;
      }
      return null;
    }

    function findAllByClass(node, cls, out = []) {
      if (!node) return out;
      if (node.classList && node.classList.contains(cls)) out.push(node);
      for (const k of (node.children || [])) {
        findAllByClass(k, cls, out);
      }
      return out;
    }

    function makeEl(tag) {
      const kids = [];
      const listeners = {};
      const attrs = {};
      const classList = {
        _classes: new Set(),
        add: (c) => classList._classes.add(c),
        remove: (c) => classList._classes.delete(c),
        contains: (c) => classList._classes.has(c)
      };
      const el = {
        tagName: tag.toUpperCase(),
        children: kids,
        childNodes: kids,
        classList,
        style: {},
        get className() { return Array.from(classList._classes).join(' '); },
        set className(v) {
          classList._classes.clear();
          (v || '').split(/\s+/).filter(Boolean).forEach(c => classList._classes.add(c));
        },
        _textContent: '',
        get textContent() { return this._textContent; },
        set textContent(v) {
          this._textContent = v;
          if (v === '') kids.length = 0;
        },
        setAttribute(k, v) {
          attrs[k] = String(v);
          if (k === 'id') elementsById[v] = el;
        },
        getAttribute(k) { return attrs[k]; },
        _listeners: listeners,
        addEventListener(evt, fn) { (listeners[evt] = listeners[evt] || []).push(fn); },
        querySelector(sel) {
          if (sel.startsWith('.')) {
            const cls = sel.slice(1);
            return findByClass(el, cls);
          }
          return null;
        },
        querySelectorAll: () => [],
        contains(target) {
          if (!target) return false;
          if (target === el) return true;
          for (const k of kids) {
            if (k === target || (k.contains && k.contains(target))) return true;
          }
          return false;
        },
        click() { (listeners['click'] || []).forEach(f => f({ stopPropagation() {}, preventDefault() {} })); },
        appendChild(child) {
          kids.push(child);
          child.parentNode = el;
          return child;
        },
        removeChild(c) {
          const idx = kids.indexOf(c);
          if (idx !== -1) kids.splice(idx, 1);
          c.parentNode = null;
          return c;
        },
        remove() {
          if (el.parentNode && el.parentNode.removeChild) {
            el.parentNode.removeChild(el);
          }
        }
      };
      return el;
    }

    const prevDoc = global.document;
    const sidePane = makeEl('div');
    const bodyEl = makeEl('body');
    const docListeners = {};
    const elementsById = { 'tbSidebar': sidePane };
    global.document = {
      body: bodyEl,
      createElement: makeEl,
      createTextNode: (txt) => ({ textContent: txt, tagName: '#text' }),
      getElementById: (id) => elementsById[id] || (id === 'tbSidebar' ? sidePane : null),
      querySelector: (sel) => (sidePane.querySelector ? sidePane.querySelector(sel) : null),
      addEventListener: (evt, fn, capture) => { (docListeners[evt] = docListeners[evt] || []).push({ fn, capture }); },
      removeEventListener: () => {}
    };

    try {
      const api = fakeApi();
      const store = createStore(api, { storage });
      store.state.list = {
        status: 'ok',
        items: [
          { id: 'tb1', name: 'TB 1', latestVersion: 1 },
          { id: 'tb2', name: 'TB 2', latestVersion: 2 },
          { id: 'tb3', name: 'TB 3', latestVersion: 1 }
        ]
      };

      // test: before creating any group, all items default to ungrouped section
      {
        const cleanStorage = mem();
        const cleanSidePane = makeEl('div');
        elementsById['tbCleanSidebar'] = cleanSidePane;
        const cleanView = BaseView.createBaseView({
          idPrefix: 'tbClean',
          fallbackSideId: 'tbCleanSidebar',
          storage: cleanStorage,
          createStore: () => store
        });
        cleanView.init();
        cleanView.renderSide();
        const cleanBody = cleanSidePane.children.find(c => c.className && c.className.includes('tb-list'));
        const defaultUnSec = cleanBody && cleanBody.children.find(c => c.getAttribute('data-group') === '__ungrouped__');
        check('items default to ungrouped section before any group is created', !!defaultUnSec);
        const defaultUnItems = defaultUnSec && defaultUnSec.children.find(c => c.className && c.className.includes('tb-group-items'));
        check('ungrouped section contains all items by default', defaultUnItems && defaultUnItems.children.length === 3);
      }

      const view = BaseView.createBaseView({
        idPrefix: 'tb',
        fallbackSideId: 'tbSidebar',
        hasNameInput: true,
        storage,
        createStore: () => store
      });
      view.init();
      view.renderSide();

      const body = sidePane.children.find(c => c.className && c.className.includes('tb-list'));
      check('sidebar body rendered', !!body);
      const groupSec = body.children.find(c => c.getAttribute('data-group') === 'Production');
      check('Production group section rendered', !!groupSec);
      const groupHead = groupSec.children.find(c => c.className && c.className.includes('tb-group-header'));
      check('group header has title Production', groupHead && groupHead.children.some(c => c.textContent === 'Production'));
      const groupBadge = groupHead.children.find(c => c.className && c.className.includes('tb-group-badge'));
      check('group badge has count 2', groupBadge && groupBadge.textContent === '2');

      const groupItems = groupSec.children.find(c => c.className && c.className.includes('tb-group-items'));
      check('group items has 2 testbenches', groupItems && groupItems.children.length === 2);
      const optBtn = groupItems.children[0].children.find(c => c.className && c.className.includes('tb-item-opt-btn'));
      check('testbench item has option button', !!optBtn);

      const grpOptBtn = groupHead.children.find(c => c.className && c.className.includes('tb-group-opt-btn'));
      check('group header has option button', !!grpOptBtn);
      check('group option button has correct id', grpOptBtn && grpOptBtn.getAttribute('id') === 'tbGroupOptBtn_Production');

      // test clicking group option button opens group menu
      grpOptBtn.click();
      const grpMenu = elementsById['tbGroupMenu'];
      check('clicking group option button opens group menu', !!grpMenu);
      const sortAzBtn = elementsById['tbGroupMenuSortAZ_Production'];
      check('group menu has Sort Items A -> Z', !!sortAzBtn);
      const sortZaBtn = elementsById['tbGroupMenuSortZA_Production'];
      check('group menu has Sort Items Z -> A', !!sortZaBtn);
      const sortGrpsAzBtn = elementsById['tbGroupMenuSortGroupsAZ_Production'];
      check('group menu has Sort Groups A -> Z', !!sortGrpsAzBtn);
      const sortGrpsZaBtn = elementsById['tbGroupMenuSortGroupsZA_Production'];
      check('group menu has Sort Groups Z -> A', !!sortGrpsZaBtn);
      const delGrpMenuBtn = elementsById['tbGroupMenuDel_Production'];
      check('group menu has Delete Group', !!delGrpMenuBtn);

      // test sorting items Z -> A inside Production group
      sortZaBtn.click();
      const sortedSec = sidePane.children.find(c => c.className && c.className.includes('tb-list')).children.find(c => c.getAttribute('data-group') === 'Production');
      const sortedItems = sortedSec.children.find(c => c.className && c.className.includes('tb-group-items')).children;
      check('items in Production sorted Z -> A: first is tb2', sortedItems[0] && sortedItems[0].getAttribute('data-id') === 'tb2');
      check('items in Production sorted Z -> A: second is tb1', sortedItems[1] && sortedItems[1].getAttribute('data-id') === 'tb1');

      // test sorting items A -> Z inside Production group
      const grpOptBtn2 = sortedSec.children.find(c => c.className && c.className.includes('tb-group-header')).children.find(c => c.className && c.className.includes('tb-group-opt-btn'));
      grpOptBtn2.click();
      const sortAzBtn2 = elementsById['tbGroupMenuSortAZ_Production'];
      sortAzBtn2.click();
      const reSortedSec = sidePane.children.find(c => c.className && c.className.includes('tb-list')).children.find(c => c.getAttribute('data-group') === 'Production');
      const reSortedItems = reSortedSec.children.find(c => c.className && c.className.includes('tb-group-items')).children;
      check('items in Production sorted A -> Z: first is tb1', reSortedItems[0] && reSortedItems[0].getAttribute('data-id') === 'tb1');
      check('items in Production sorted A -> Z: second is tb2', reSortedItems[1] && reSortedItems[1].getAttribute('data-id') === 'tb2');

      // test sorting groups
      grpOptBtn2.click();
      const sortGroupsZa = elementsById['tbGroupMenuSortGroupsZA_Production'];
      sortGroupsZa.click();
      check('ui groupsOrder is desc', view.getUI().groupsOrder === 'desc');
      const grpOptBtn3 = sidePane.children.find(c => c.className && c.className.includes('tb-list')).children.find(c => c.getAttribute('data-group') === 'Production').children.find(c => c.className && c.className.includes('tb-group-header')).children.find(c => c.className && c.className.includes('tb-group-opt-btn'));
      grpOptBtn3.click();
      const sortGroupsAz = elementsById['tbGroupMenuSortGroupsAZ_Production'];
      sortGroupsAz.click();
      check('ui groupsOrder is asc', view.getUI().groupsOrder === 'asc');

      // test ungrouped section has option button
      const unSecOptBtn = elementsById['tbGroupOptBtn_Ungrouped'];
      check('ungrouped section header has option button', !!unSecOptBtn);
      unSecOptBtn.click();
      check('ungrouped menu opened', !!elementsById['tbGroupMenu']);
      check('ungrouped menu has Sort Items A -> Z', !!elementsById['tbGroupMenuSortAZ___ungrouped__']);
      check('ungrouped menu does NOT have Delete Group', !elementsById['tbGroupMenuDel___ungrouped__']);
      view.closeActiveMenu();

      // test delete group via menu
      view.getGroupManager().addGroup('ToDeleteGroup');
      view.renderSide();
      const toDelOptBtn = elementsById['tbGroupOptBtn_ToDeleteGroup'];
      check('ToDeleteGroup has option button', !!toDelOptBtn);
      toDelOptBtn.click();
      const toDelMenuBtn = elementsById['tbGroupMenuDel_ToDeleteGroup'];
      check('ToDeleteGroup menu has Delete Group button', !!toDelMenuBtn);
      toDelMenuBtn.click();
      check('ToDeleteGroup deleted from group manager', view.getGroupManager().getGroupNames().indexOf('ToDeleteGroup') === -1);

      const unSec = body.children.find(c => c.getAttribute('data-group') === '__ungrouped__');
      check('ungrouped section rendered for tb3', !!unSec);

      // test collapse
      groupHead.click();
      const savedCollapsed = JSON.parse(storage.getItem('mm_tb_collapsed_groups') || '{}');
      check('clicking group header toggles collapse and saves to storage', savedCollapsed['Production'] === true);

      // test empty group is retained in sidebar when items are removed
      view.getGroupManager().removeGroup('tb1');
      view.getGroupManager().removeGroup('tb2');
      view.renderSide();
      const updatedBody = sidePane.children.find(c => c.className && c.className.includes('tb-list'));
      const emptyProdSec = updatedBody && updatedBody.children.find(c => c.getAttribute('data-group') === 'Production');
      check('empty group Production still rendered in sidebar', !!emptyProdSec);
      const emptyProdBadge = emptyProdSec && emptyProdSec.children.find(c => c.className && c.className.includes('tb-group-header')).children.find(c => c.className && c.className.includes('tb-group-badge'));
      check('empty group Production badge has count 0', emptyProdBadge && emptyProdBadge.textContent === '0');

      // test empty group is retained in sidebar EVEN when entire store list is empty (0 items in total)
      const prevItems = store.state.list.items;
      store.state.list.items = [];
      view.renderSide();
      const emptyStoreBody = sidePane.children.find(c => c.className && c.className.includes('tb-list'));
      const emptyProdWithNoItems = emptyStoreBody && emptyStoreBody.children.find(c => c.getAttribute('data-group') === 'Production');
      check('empty group Production kept in sidebar when store list has 0 items', !!emptyProdWithNoItems);
      const emptyHint = emptyProdWithNoItems && emptyProdWithNoItems.children.find(c => c.className && c.className.includes('tb-group-items')).children.find(c => c.className && c.className.includes('tb-group-empty-hint'));
      check('empty group Production displays empty hint', emptyHint && emptyHint.textContent === 'No items in this group');

      // test adding empty group via addGroup creates tb-group-section
      view.getGroupManager().addGroup('Staging');
      view.renderSide();
      const stagingBody = sidePane.children.find(c => c.className && c.className.includes('tb-list'));
      const stagingSec = stagingBody && stagingBody.children.find(c => c.getAttribute('data-group') === 'Staging');
      check('added empty group Staging rendered as tb-group-section', !!stagingSec);

      // test header NewGroupBtn creates inline input and adds group
      const newGrpBtn = sidePane.children.find(c => c.className && c.className.includes('tb-side-head')).children.find(c => c.getAttribute('id') === 'tbNewGroupBtn');
      check('sidebar header has NewGroupBtn', !!newGrpBtn);
      newGrpBtn.click();
      const createGrpBox = sidePane.children.find(c => c.className && c.className.includes('tb-create'));
      check('clicking NewGroupBtn shows create box', !!createGrpBox);
      const grpNameInput = createGrpBox && createGrpBox.children.find(c => c.getAttribute('id') === 'tbNewGroupName');
      check('create box has group name input', !!grpNameInput);
      grpNameInput.value = 'Lab Testing';
      view.getUI().newGroupName = 'Lab Testing';
      const submitGrpBtn = createGrpBox && createGrpBox.children.find(c => c.className && c.className.includes('tb-row')).children.find(c => c.getAttribute('id') === 'tbCreateGroupBtn');
      check('create box has submit button', !!submitGrpBtn);
      submitGrpBtn.click();
      const afterAddBody = sidePane.children.find(c => c.className && c.className.includes('tb-list'));
      const labSec = afterAddBody && afterAddBody.children.find(c => c.getAttribute('data-group') === 'Lab Testing');
      check('group created via UI rendered as tb-group-section', !!labSec);

      // clean up added groups for subsequent tests
      view.getGroupManager().deleteGroup('Staging');
      view.getGroupManager().deleteGroup('Lab Testing');

      // restore store items and restore tb1, tb2 back to Production for remaining tests
      store.state.list.items = prevItems;
      view.getGroupManager().setGroup('tb1', 'Production');
      view.getGroupManager().setGroup('tb2', 'Production');
      view.renderSide();

      // test duplicate modal rendering & classes
      const bodyEl = makeEl('body');
      global.document.body = bodyEl;
      view.promptDuplicate({ id: 'tb1', name: 'TB 1' });
      const dupBackdrop = bodyEl.children.find(c => c.getAttribute('id') === 'tbDuplicateModalBackdrop');
      check('duplicate modal backdrop created', !!dupBackdrop);


      const srcLabel = findByClass(dupBackdrop, 'tb-modal-source-label');
      check('duplicate modal has source label', srcLabel && srcLabel.textContent === 'Source: ');
      const srcName = findByClass(dupBackdrop, 'tb-modal-source-name');
      check('duplicate modal has source name', srcName && srcName.textContent === 'TB 1 (tb1)');
      const modalInputs = findAllByClass(dupBackdrop, 'tb-modal-input');
      check('duplicate modal has modal inputs with clean light styling class', modalInputs.length >= 1);

      const dupIdIn = elementsById['tbDuplicateIdInput'];
      const dupNameIn = elementsById['tbDuplicateNameInput'];
      check('duplicate modal default id has _copy suffix', dupIdIn && dupIdIn.value === 'tb1_copy');
      check('duplicate modal default name has _copy suffix', dupNameIn && dupNameIn.value === 'TB 1_copy');

      dupIdIn.value = 'tb1_copy_2';
      (dupIdIn._listeners['input'] || []).forEach(f => f({ target: dupIdIn }));
      check('duplicate modal syncs name when id is changed', dupNameIn && dupNameIn.value === 'TB 1_copy_2');

      const dupGrpSelect = elementsById['tbDuplicateGroupSelect'];
      check('duplicate modal has group select', !!dupGrpSelect);
      const grpOptions = dupGrpSelect.children;
      check('duplicate modal has 3 group options', grpOptions.length === 3);
      const opt0Text = (grpOptions[0].children[0] && grpOptions[0].children[0].textContent) || grpOptions[0].textContent;
      check('first option is group name Production without same as source', (grpOptions[0].value === 'Production' || grpOptions[0].getAttribute('value') === 'Production') && opt0Text === 'Production');
      const opt1Text = (grpOptions[1].children[0] && grpOptions[1].children[0].textContent) || grpOptions[1].textContent;
      check('second to last option is Ungrouped', (grpOptions[1].value === '__none__' || grpOptions[1].getAttribute('value') === '__none__') && opt1Text === 'Ungrouped');
      const opt2Text = (grpOptions[2].children[0] && grpOptions[2].children[0].textContent) || grpOptions[2].textContent;
      check('last option is + Create new group...', (grpOptions[2].value === '__new__' || grpOptions[2].getAttribute('value') === '__new__') && opt2Text === '+ Create new group...');

      // test custom group select
      const dupCustomSelect = elementsById['tbDuplicateGroupCustomSelect'];
      check('duplicate modal has modern custom group select', !!dupCustomSelect);
      const dupCustomTrigger = findByClass(dupCustomSelect, 'tb-custom-select-trigger');
      check('duplicate modal group has custom trigger button', !!dupCustomTrigger);
      const dupCustomMenu = findByClass(dupCustomSelect, 'tb-custom-select-menu');
      check('duplicate modal group has custom dropdown menu', !!dupCustomMenu);
      const dupCustomItems = findAllByClass(dupCustomMenu, 'tb-custom-select-item');
      check('duplicate modal group custom menu has 3 items', dupCustomItems.length === 3);

      // test custom version select in version bar
      const vbWrap = Common.renderVersionBar({
        cur: { id: 'tb1', version: 2, versions: [2, 1], readOnly: false },
        store: store,
        idPrefix: 'tbTest'
      });
      const vCustomSelect = elementsById['tbTestVersionCustomSelect'];
      check('version bar renders modern custom select', !!vCustomSelect);
      const vTrigger = findByClass(vCustomSelect, 'tb-custom-select-trigger');
      check('version bar has custom trigger', !!vTrigger);
      const trigLabel = findByClass(vTrigger, 'tb-custom-select-trigger-label');
      check('version trigger text is v2 (current)', trigLabel && trigLabel.textContent === 'v2 (current)');
      const vMenu = findByClass(vCustomSelect, 'tb-custom-select-menu');
      check('version bar has custom dropdown menu', !!vMenu);
      const vItems = findAllByClass(vMenu, 'tb-custom-select-item');
      check('version bar custom menu has items for all versions', vItems.length === 2);
      const firstItemLabel = findByClass(vItems[0], 'tb-custom-select-item-label');
      check('version menu first item text is v2 (current)', firstItemLabel && firstItemLabel.textContent === 'v2 (current)');

      // test promptGroup: new group input only visible when Create new group is selected
      view.promptGroup(['tb1']);
      const groupModalIn = elementsById['tbNewGroupInput'];
      check('assign to group new group input is hidden by default', groupModalIn && (groupModalIn.style.display === 'none' || (groupModalIn.getAttribute('style') || '').includes('display: none')));
      const groupSelectEl = elementsById['tbGroupSelect'];
      check('assign to group has group select', !!groupSelectEl);
      if (groupSelectEl && groupModalIn) {
        groupSelectEl.value = '__new__';
        (groupSelectEl._listeners['change'] || []).forEach(f => f({ target: groupSelectEl }));
        check('new group input shown when __new__ selected', groupModalIn.style.display === '');
        groupSelectEl.value = 'Production';
        (groupSelectEl._listeners['change'] || []).forEach(f => f({ target: groupSelectEl }));
        check('new group input hidden when existing group selected', groupModalIn.style.display === 'none');
      }

      // test search dropdown closes on outside click
      const searchBox = elementsById['tbSearchBox'];
      check('search box rendered', !!searchBox);

      // open dropdown
      view.getUI().searchOpen = true;
      view.renderSide();
      check('search dropdown is open', view.getUI().searchOpen === true);
      const openMenu = elementsById['tbDropdownMenu'];
      check('search dropdown menu exists when open', !!openMenu);

      // click outside search box -> closes dropdown
      const outsideEl = makeEl('div');
      const clickHandlers = (docListeners['click'] || []).concat(docListeners['pointerdown'] || []);
      clickHandlers.forEach(l => l.fn({ target: outsideEl }));
      check('outside click closed search dropdown', view.getUI().searchOpen === false);
      check('search dropdown menu removed after outside click', searchBox.children.indexOf(openMenu) === -1);
    } finally {
      global.document = prevDoc;
    }
  }

  // ---- auto-save on create (testbench and infra)
  {
    const TbView = require(js('TestbenchView.js'));
    const tbSpec = TbView.getSpec();
    const api = fakeApi();
    const tbStore = createStore(api, { storage: mem() });
    await tbStore.loadList();

    const rTb = await tbSpec.onCreate(tbStore, 'tb-auto', 'Auto Saved TB');
    check('testbench onCreate returns ok', rTb.ok === true);
    check('testbench is auto-saved as v1', tbStore.state.current.version === 1 && !tbStore.state.current.isNew);
    check('testbench notice says Created', tbStore.state.notice && tbStore.state.notice.text === 'Created testbench as version 1.');
    check('testbench auto-saved cannot save (clean)', !tbStore.canSave());
    const tbCreated = last(api, 'create');
    check('backend createConfiguration was called for testbench', tbCreated && tbCreated[1] === 'testbench' && tbCreated[2] === 'tb-auto');

    // duplicate testbench creation rejected
    const rTbDup = await tbSpec.onCreate(tbStore, 'tb-auto', 'Again');
    check('duplicate testbench creation rejected', !rTbDup.ok);

    // Infra auto-save on create
    const InfraView = require(js('InfraView.js'));
    const infraSpec = InfraView.getSpec();
    const infraStore = InfraStore.createStore(api, { storage: mem() });
    await infraStore.loadList();

    const rInfra = await infraSpec.onCreate(infraStore, 'infra-auto');
    check('infra onCreate returns ok', rInfra.ok === true);
    check('infra is auto-saved as v1', infraStore.state.current.version === 1 && !infraStore.state.current.isDefault && !infraStore.state.current.isNew);
    check('infra notice says Created', infraStore.state.notice && infraStore.state.notice.text === 'Created infrastructure configuration as version 1.');
    check('infra auto-saved cannot save (clean)', !infraStore.canSave());
    const infraUpdated = last(api, 'update');
    check('backend updateConfiguration was called for infra v1', infraUpdated && infraUpdated[1] === 'infrastructure' && infraUpdated[2] === 'infra-auto');

    // duplicate infra creation rejected
    const rInfraDup = await infraSpec.onCreate(infraStore, 'infra-auto');
    check('duplicate infra creation rejected', !rInfraDup.ok);
  }

  console.log('\n' + passes + ' passed, ' + failures + ' failed');
  process.exit(failures ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
