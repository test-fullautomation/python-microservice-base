// Plugins a service delivers (Meta.gui_plugin): offered after a Consul
// refresh, blocked until an administrator allows them, applied in frames and
// bound to their service, gone when the service leaves Consul, refused when
// they overreach or take another plugin's id; their calls reach the other
// services they name and bring back the full error. The fixtures in
// test/endo/fixtures/service-plugins stand in for the services; they are
// offered as "local" so nothing is fetched and no bridge is needed.
'use strict';

const { probe } = require('./harness');

const FIX = '../test/endo/fixtures/service-plugins/';
const SESSIONS = { plugin: 'sessions-demo', service: 'session-manager-demo', folder: 'SessionsDemo0.1.0' };
const CONFIG = { plugin: 'config-demo', service: 'configuration-hub-demo', folder: 'ConfigDemo0.1.0' };
const REFUSED = { plugin: 'refused-demo', service: 'overreaching-demo', folder: 'RefusedDemo0.1.0' };
const CLASH = { plugin: 'charts', service: 'impostor-demo', folder: 'SessionsDemo0.1.0' };
const NAV = '#sidebarSwitch [data-mode="plugin:sessions-demo/sessions"]';
const CLASH_ID = 'charts@impostor-demo@http://127.0.0.1:8500';   // id@service@consul

probe('GUI probe: service plugins', async (t) => {
  const g = await t.open({});
  await g.js('MicroserviceManager.endo.plugins.ready.then(function () { return true; })');

  const offer = (list) => g.js(`MicroserviceManager.endo.plugins.offerServicePlugins(${JSON.stringify(list)}.map(function (o) {
      return Object.assign({ consulUrl: 'http://127.0.0.1:8500', local: true,
                             base: new URL(${JSON.stringify(FIX)} + o.folder + '/', document.baseURI).href }, o);
    })).then(function () { return true; })`);
  const info = (id) => g.js(`(MicroserviceManager.endo.plugins.list().filter(function (p) { return p.id === ${JSON.stringify(id)}; })[0]) || null`);
  const toasts = () => g.js("(document.getElementById('toastContainer') || document.body).textContent");

  // ---- offered: known, but nothing downloaded or shown until allowed
  t.check('offering the plugins resolves', (await offer([SESSIONS, CONFIG, REFUSED, CLASH])) === true);
  let s = await info('sessions-demo');
  t.check('sessions-demo is listed as delivered by its service', s && s.source === 'service' && s.service === SESSIONS.service, s);
  t.check('sessions-demo waits for an administrator (blocked)', s && s.state === 'blocked', s);
  t.check('a blocked plugin adds no tab', !(await g.js(`!!document.querySelector(${JSON.stringify(NAV)})`)));
  const clash = await info(CLASH_ID);
  t.check('a service plugin cannot take the id of a plugin shipped with the GUI', clash && clash.state === 'refused' &&
          /bundled plugin "charts"/.test(clash.error), clash);
  t.check('the shipped charts plugin is untouched', (await info('charts')).state === 'active');

  // ---- allowed through the Plugins dialog, with the mouse
  await g.click('#btnAdminTools');
  // The ribbon band slides in; click Plugins once it holds still.
  for (let i = 0; i < 5 && !(await g.visible('#pluginAllow-sessions-demo')); i++) {
    await g.waitForSelector('#btnAdminPlugins', 3000);
    await g.click('#btnAdminPlugins');
    await g.waitForSelector('#pluginAllow-sessions-demo', 1500);
  }
  t.check('the Plugins dialog lists the service plugin with its allow switch',
          await g.waitForSelector('#pluginAllow-sessions-demo', 5000));
  t.check('the row names the service', /service session-manager-demo/.test(
    await g.js("(document.querySelector('[data-plugin=\"sessions-demo\"]') || {}).textContent || ''")));
  await g.click('#pluginAllow-sessions-demo');
  t.check('allowed: sessions-demo becomes active', await g.waitFor(async () => ((await info('sessions-demo')) || {}).state === 'active', 8000),
          await info('sessions-demo'));
  t.check('the allowance is kept for this PC', /sessions-demo@session-manager-demo/.test(
    await g.js("localStorage.getItem('mm_service_plugins_allowed') || ''")));
  // Bootstrap ignores a close while the dialog is still sliding in.
  await g.waitFor(() => g.js("(function(){ var m = bootstrap.Modal.getInstance(document.getElementById('pluginsModal')); return !!m && !m._isTransitioning; })()"), 5000);
  await g.click('#pluginsModal .btn-close');
  t.check('the Plugins dialog closes', await g.waitFor(() =>
    g.js("!document.querySelector('.modal.show') && !document.querySelector('.modal-backdrop')"), 5000));

  // ---- its tab and page, bound to the service that delivered it. The bridge
  // is played by a recorder that fails the catalog call the way a service does.
  await g.js(`(function () {
    var c = MicroserviceManager.grpcClient;
    window.__probeCallMethod = c.callMethod;
    window.__probeCalls = [];
    c.callMethod = function (o) {
      window.__probeCalls.push(o);
      return Promise.resolve({ ok: false, code: 'FAILED_PRECONDITION', error: 'FAILED_PRECONDITION: catalog is read-only',
        details: [{ '@type': 'google.rpc.PreconditionFailure', violations: [{ type: 'STATE', subject: 'catalog', description: 'read-only' }] }],
        request_id: 'req-probe-1' });
    };
    return true;
  })()`);
  t.check('its Sessions tab appears', await g.waitForSelector(NAV, 5000));
  await g.click(NAV);
  t.check('the navigator runs bound to its service', await g.waitFor(async () =>
    /sessions-demo navigator bound to session-manager-demo/.test(await toasts()), 8000), await toasts());
  t.check('the page of the same id runs bound to its service', await g.waitFor(async () =>
    /sessions-demo console bound to session-manager-demo/.test(await toasts()), 8000));
  t.check('its page fills the stage', await g.visible('.app-content > [data-endo-mode="plugin:sessions-demo/sessions"]'));

  // ---- slots 3 and 4: another service it names, and the full error, across the sandbox
  t.check('the frame knows the services it may call (ctx.uses)', /sessions-demo console bound to session-manager-demo \(uses catalog\)/.test(await toasts()), await toasts());
  t.check('the page reaches a service it names in binds.uses, with its options', await g.waitFor(() => g.js(`window.__probeCalls.some(function (o) {
    return o.consulName === 'catalog' && o.grpcService === 'catalog.v1.Catalog' && o.method === 'List' &&
           o.timeout === 3 && o.metadata && o.metadata.origin === 'sessions-demo'; })`), 8000),
    await g.js('JSON.stringify(window.__probeCalls)'));
  t.check('the failed call reaches the frame with code, details and request id', await g.waitFor(async () =>
    /sessions-demo catalog: FAILED_PRECONDITION google\.rpc\.PreconditionFailure req-probe-1/.test(await toasts()), 8000), await toasts());
  t.check('a service it does not name is refused in the GUI', await g.waitFor(async () =>
    /sessions-demo hub: NotBound/.test(await toasts()), 8000), await toasts());
  t.check('the refused service was never called', await g.js("!window.__probeCalls.some(function (o) { return o.consulName === 'configuration-hub'; })"));
  await g.js('MicroserviceManager.grpcClient.callMethod = window.__probeCallMethod; true');

  // ---- an overreaching plugin is refused, even when allowed
  t.check('refused-demo is blocked before anything else', ((await info('refused-demo')) || {}).state === 'blocked');
  await g.js("MicroserviceManager.endo.plugins.setAllowed('refused-demo', true)");
  const r = await info('refused-demo');
  t.check('allowed, refused-demo is refused for its shell entries', r && r.state === 'refused' &&
          r.issues.some((i) => /not "shell"/.test(i)), r);

  // ---- the service leaves Consul, and comes back
  await offer([CONFIG, REFUSED]);
  s = await info('sessions-demo');
  t.check('its service gone: offline', s && s.state === 'offline' && /not registered in Consul/.test(s.error), s);
  t.check('its service gone: the tab is removed', !(await g.js(`!!document.querySelector(${JSON.stringify(NAV)})`)));
  t.check('the GUI leaves the plugin\'s view', (await g.js("!!document.querySelector('.app-content > [data-endo-mode=\"plugin:sessions-demo/sessions\"]')")) === false);
  t.check('the clash entry goes with its service', (await info(CLASH_ID)) === null);
  await offer([SESSIONS, CONFIG, REFUSED]);
  t.check('its service back: active again without asking', await g.waitFor(async () => ((await info('sessions-demo')) || {}).state === 'active', 8000));
  t.check('its service back: the tab is back', await g.waitForSelector(NAV, 5000));

  // ---- the same names in another Consul are another publisher: asked again
  await offer([Object.assign({}, SESSIONS, { consulUrl: 'http://other-cluster:8500' }), CONFIG, REFUSED]);
  s = await info('sessions-demo');
  t.check("another Consul delivering the same plugin is not allowed by this one's allowance", s && s.state === 'blocked', s);
  t.check('and its tab is gone', !(await g.js(`!!document.querySelector(${JSON.stringify(NAV)})`)));
  await offer([SESSIONS, CONFIG, REFUSED]);
  t.check('the allowed Consul back: active again', await g.waitFor(async () => ((await info('sessions-demo')) || {}).state === 'active', 8000));

  // ---- Meta.gui changes under a registered service: the new folder is loaded
  await offer([Object.assign({}, SESSIONS, { folder: 'ConfigDemo0.1.0' }), CONFIG, REFUSED]);
  s = await info('sessions-demo');
  t.check('a new folder is read again (its plugin.json names another id: refused)', s && s.state === 'refused' &&
          s.issues.some((i) => /Meta\.gui_plugin/.test(i)), s);
  t.check("the old folder's tab is gone", !(await g.js(`!!document.querySelector(${JSON.stringify(NAV)})`)));
  await offer([SESSIONS, CONFIG, REFUSED]);
  t.check('the right folder again: active', await g.waitFor(async () => ((await info('sessions-demo')) || {}).state === 'active', 8000));
  await g.waitForSelector(NAV, 5000);

  // ---- an offer with an id outside the plugin-id pattern is ignored
  const EVIL = { plugin: 'x"],body,[data-endo-plugin="x', service: 'evil-demo', folder: 'SessionsDemo0.1.0' };
  await offer([SESSIONS, CONFIG, REFUSED, EVIL]);
  t.check('an invalid plugin id is not listed', !(await g.js("MicroserviceManager.endo.plugins.list().some(function (p) { return /body/.test(p.id); })")));
  await offer([SESSIONS, CONFIG, REFUSED]);
  t.check('and cannot take the page with it', await g.js("!!document.querySelector('.app-content') && !!document.body.children.length"));

  // ---- the administrator withdraws the allowance
  await g.js("MicroserviceManager.endo.plugins.setAllowed('sessions-demo', false)");
  t.check('withdrawn: blocked again', ((await info('sessions-demo')) || {}).state === 'blocked');
  t.check('withdrawn: the tab is removed', !(await g.js(`!!document.querySelector(${JSON.stringify(NAV)})`)));
  t.check('config-demo was never allowed and stays blocked', ((await info('config-demo')) || {}).state === 'blocked');
});
