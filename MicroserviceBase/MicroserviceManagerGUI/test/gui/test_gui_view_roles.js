// View roles: what each role shows, and that views outside the roles stay
// shut whatever asks for them. No bridge needed.
'use strict';

const { probe } = require('./harness');

probe('GUI probe: view roles', async (t) => {
  // user only: no Developer, no Administrator
  let g = await t.open({ query: { view: 'user' } });
  t.check('user: Services tab shown', await g.visible('#btnModeServices'));
  t.check('user: Developer tab hidden', !(await g.visible('#btnDevTools')));
  t.check('user: Administrator tab hidden', !(await g.visible('#btnAdminTools')));
  t.check('user: MM.getView() is "user"', (await g.js('MicroserviceManager.getView()')) === 'user');
  // Tiles | Service window is an operator's choice: on the User tab, greyed out with nothing selected.
  t.check('user: Service view pair on the User tab, disabled until a service ships both',
    (await g.js("['btnViewTiles','btnViewServiceWindow'].every(function (id) { var b = document.querySelector('#ribbonUser #' + id); return b && b.disabled; })")) === true);
  t.check('user: no Classic panel button left on the Developer tab', (await g.js("!document.getElementById('btnDevClassicPanel')")) === true);
  await g.js("MicroserviceManager.switchMode('testproject'); true");
  t.check('user: test projects refused', !(await g.js("document.getElementById('sidebarTestProject').classList.contains('active')")));
  await g.js("MicroserviceManager.switchMode('fleet'); true");
  t.check('user: fleet (Nomad) refused', !(await g.js("document.getElementById('sidebarFleet').classList.contains('active')")));
  await g.js("MicroserviceManager.switchMode('bench'); true");
  t.check('user: bench allowed', await g.js("document.getElementById('sidebarBench').classList.contains('active')"));

  // user + admin: Administrator tab, still no Developer
  g = await t.open({ query: { view: 'user+admin' } });
  t.check('user+admin: Administrator tab shown', await g.visible('#btnAdminTools'));
  t.check('user+admin: Developer tab hidden', !(await g.visible('#btnDevTools')));
  await g.click('#btnAdminTools');
  t.check('user+admin: clicking it opens its ribbon', await g.waitForSelector('#ribbonAdmin', 3000));
  await g.js("MicroserviceManager.switchMode('testproject'); true");
  t.check('user+admin: test projects refused', !(await g.js("document.getElementById('sidebarTestProject').classList.contains('active')")));

  // nothing configured: every role
  g = await t.open({});
  t.check('default: Developer tab shown', await g.visible('#btnDevTools'));
  t.check('default: Administrator tab shown', await g.visible('#btnAdminTools'));
  await g.click('#btnDevTools');
  t.check('default: Developer ribbon opens', await g.waitForSelector('#ribbonDev', 3000));
  t.check('default: view is user+admin+developer',
          (await g.js('MicroserviceManager.getView()')) === 'user+admin+developer');
});
