// Tile groups: a component's "groups" put tiles under headers that expand
// and collapse. Checked in the real page: the headers and the layout, the
// tiles of a collapsed group hidden *and* suspended (R5), a component that
// is hidden and shown again resuming only the open groups, the choice
// remembered, and a whole component mounted through mountComponent.
'use strict';

const { probe } = require('./harness');

// The page side: a stage with five fake tiles in two groups and one ungrouped,
// each tile an instance that counts its suspend/resume.
const SETUP = `(function () {
  var MM = MicroserviceManager;
  var host = document.createElement('div');
  host.id = 'probeGroups';
  host.style.cssText = 'position:fixed;left:20px;top:80px;z-index:99999;width:900px;background:#fff;padding:8px';
  document.body.appendChild(host);
  var stage = document.createElement('div');
  stage.className = 'endo-stage';
  host.appendChild(stage);
  var log = window.__log = {};
  function tile(id) {
    var s = document.createElement('section');
    s.className = 'endo-tile w1 h1';
    s.setAttribute('data-tile', id);
    s.innerHTML = '<header class="endo-tile-head"><span class="t">' + id + '</span></header><div class="endo-tile-body">' + id + '</div>';
    stage.appendChild(s);
    log[id] = { running: true, suspends: 0, resumes: 0 };
    return { tileId: id, section: s, instance: {
      suspend: function () { log[id].running = false; log[id].suspends++; },
      resume: function () { log[id].running = true; log[id].resumes++; },
      destroy: function () {} } };
  }
  var entries = ['free', 'cmd-a', 'cmd-b', 'cfg-a', 'cfg-b'].map(tile);
  var gated = MM.endo.applyGroups(stage, entries, [
    { id: 'commands', title: 'Commands', tiles: ['cmd-a', 'cmd-b'] },
    { id: 'setup', title: 'Set-up', tiles: ['cfg-a', 'cfg-b'], collapsed: true }
  ], { scope: 'probe', component: 'bits.probe' });
  window.__handle = MM.endo.instanceGroup(gated.filter(Boolean));
  return true;
})()`;

const hidden = (g, id) => g.js(`document.querySelector('#probeGroups [data-tile="${id}"]').hidden`);
const running = (g, id) => g.js(`window.__log['${id}'].running`);

probe('GUI probe: tile groups', async (t) => {
  let g = await t.open({ query: { view: 'user' } });
  t.check('the page set up the grouped stage', (await g.js(SETUP)) === true);

  t.check('two headers, each before its first tile',
    (await g.js("[].map.call(document.querySelectorAll('#probeGroups .endo-stage > *'), function (e) { return e.getAttribute('data-group') || e.getAttribute('data-tile'); }).join(',')"))
      === 'free,commands,cmd-a,cmd-b,setup,cfg-a,cfg-b');
  t.check('the header spans the whole row', (await g.js(
    "(function () { var h = document.querySelector('#probeGroups [data-group=commands]'); var s = h.parentNode.getBoundingClientRect(); var r = h.getBoundingClientRect(); return Math.abs(r.width - s.width) < 2; })()")) === true);
  t.check('a grouped stage packs rows in order (no dense back-fill)',
    (await g.js("getComputedStyle(document.querySelector('#probeGroups .endo-stage')).gridAutoFlow")) === 'row');
  t.check('header shows the tile count', (await g.js("document.querySelector('#probeGroups [data-group=setup] .n').textContent")) === '2 tiles');

  // "collapsed": true: hidden and suspended from the start; the open group runs.
  t.check('a group declared collapsed starts hidden', (await hidden(g, 'cfg-a')) && (await hidden(g, 'cfg-b')));
  t.check('...and its tiles are suspended', !(await running(g, 'cfg-a')) && !(await running(g, 'cfg-b')));
  t.check('an open group shows and runs', !(await hidden(g, 'cmd-a')) && (await running(g, 'cmd-a')));
  t.check('aria-expanded tells the state', (await g.js("document.querySelector('#probeGroups [data-group=setup] button').getAttribute('aria-expanded')")) === 'false');

  // Expand with the mouse: shown and resumed.
  await g.click('#probeGroups [data-group=setup] button');
  t.check('click expands: tiles shown', !(await hidden(g, 'cfg-a')) && !(await hidden(g, 'cfg-b')));
  t.check('...and resumed', (await running(g, 'cfg-a')) && (await running(g, 'cfg-b')));

  // Collapse the other group with the keyboard.
  await g.js("document.querySelector('#probeGroups [data-group=commands] button').focus(); true");
  await g.key('Enter');
  t.check('Enter on the header collapses it', (await hidden(g, 'cmd-a')) && !(await running(g, 'cmd-b')));

  // The component is hidden, then shown again: only the open groups resume.
  await g.js('window.__handle.suspend(); true');
  t.check('hiding the component suspends the open group', !(await running(g, 'cfg-a')));
  const before = await g.js("window.__log['cmd-a'].resumes");
  await g.js('window.__handle.resume(); true');
  t.check('showing it again resumes the open group', await running(g, 'cfg-a'));
  t.check('...but not the collapsed one', !(await running(g, 'cmd-a')) && (await g.js("window.__log['cmd-a'].resumes")) === before);
  t.check('an ungrouped tile is untouched by the groups', (await running(g, 'free')) && !(await hidden(g, 'free')));

  // Remembered: the choice wins over "collapsed" next time.
  const prefs = await g.js("JSON.parse(localStorage.getItem('mm_endo_groups') || '{}')");
  t.check('the choice is remembered per scope, component and group',
    prefs['probe|bits.probe|setup'] === true && prefs['probe|bits.probe|commands'] === false, prefs);
  await g.screenshot('tile-groups');

  // A whole component through mountComponent, with the remembered choice.
  g = await t.open({ query: { view: 'user' }, storage: { mm_endo_groups: JSON.stringify({ 'svc|bits.groups-probe|b': true }) } });
  const mounted = await g.js(`(function () {
    var el = document.createElement('div');
    el.id = 'probeMount';
    el.style.cssText = 'position:fixed;left:20px;top:80px;z-index:99999;width:900px;background:#fff';
    document.body.appendChild(el);
    return MicroserviceManager.endo.mountComponent({
      component: 'bits.groups-probe', version: '1.0.0', layer: 'bits', title: 'Groups probe',
      requires: { shell: '^2.3', capabilities: [] }, binds: { consul: '@self' },
      tiles: [ { id: 't1', size: '1x1', kind: 'text', title: 'One', text: 'one' },
               { id: 't2', size: '1x1', kind: 'text', title: 'Two', text: 'two' },
               { id: 't3', size: '2x1', kind: 'text', title: 'Three', text: 'three' } ],
      groups: [ { id: 'a', title: 'First', tiles: ['t1'] },
                { id: 'b', title: 'Second', tiles: ['t2', 't3'], collapsed: true } ],
      renderer: 'schema' }, el, { consulName: 'groups-probe' }).then(function (h) { return h.issues.length; });
  })()`);
  t.check('a manifest with groups mounts and lints clean', mounted === 0, mounted);
  t.check('mountComponent draws the headers',
    (await g.js("document.querySelectorAll('#probeMount [data-group]').length")) === 2);
  t.check('the remembered choice wins over "collapsed": true',
    (await g.js("!document.querySelector('#probeMount [data-tile=t3]').hidden")) === true);
});
