// Tile groups: a component's "groups" put tiles in boxes that expand
// and collapse. Checked in the real page: the boxes and the layout, the
// tiles of a collapsed group hidden *and* suspended (R5), a component that
// is hidden and shown again resuming only the open groups, the choice
// remembered, a whole component mounted through mountComponent, and the
// bench's shaped groups (one connected piece each, outlined, packed together).
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

  const order = (sel) => g.js("[].map.call(document.querySelectorAll('" + sel + "'), function (e) { return e.getAttribute('data-group') || e.getAttribute('data-tile'); }).join(',')");
  t.check('two boxes on the stage, each where its first tile was',
    (await order('#probeGroups .endo-stage > *')) === 'free,commands,setup');
  t.check('...holding their tiles, in order',
    (await order('#probeGroups [data-group=commands] > .endo-tile')) === 'cmd-a,cmd-b');
  // Geometry: a box of two 1x1 tiles is two stage columns wide and one row
  // high, and its tiles sit on the stage's columns (subgrid).
  const geo = await g.js(`(function () {
    var r = function (sel) { return document.querySelector('#probeGroups ' + sel).getBoundingClientRect(); };
    var free = r('[data-tile=free]'), box = r('[data-group=commands]'), a = r('[data-tile=cmd-a]'), b = r('[data-tile=cmd-b]');
    return { free: free.width, box: box.width, a: a.width, b: b.width, sameRow: Math.abs(a.top - b.top) < 2,
             boxBesideFree: Math.abs(box.top - free.top) < 2 && box.left > free.right };
  })()`);
  t.check('the box is two columns wide', Math.abs(geo.box - (2 * geo.free + 12)) < 4, geo);
  t.check('its tiles are as wide as a loose 1x1 tile and side by side',
    Math.abs(geo.a - geo.free) < 2 && Math.abs(geo.b - geo.free) < 2 && geo.sameRow, geo);
  t.check('the box packs beside the loose tile, not on a row of its own', geo.boxBesideFree, geo);
  t.check('a grouped stage still packs densely',
    /dense/.test(await g.js("getComputedStyle(document.querySelector('#probeGroups .endo-stage')).gridAutoFlow")));
  t.check('the box shows the tile count', (await g.js("document.querySelector('#probeGroups [data-group=setup] .n').textContent")) === '2 tiles');
  t.check('a collapsed box is one cell wide',
    (await g.js("(function () { var s = document.querySelector('#probeGroups [data-tile=free]').getBoundingClientRect(); var c = document.querySelector('#probeGroups [data-group=setup]').getBoundingClientRect(); return Math.abs(c.width - s.width) < 2 && c.height < s.height; })()")) === true);

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

  // ---------- shaped groups (the bench) ----------
  // The packer alone: a group is one connected piece, and loose tiles fill its notches.
  const packed = await g.js(`(function () {
    var P = MicroserviceManager.endo.packShapes;
    // A 1x1 and a 2x1 of group A on 4 columns, then a loose 1x1, then group B: two 2x1.
    var spots = P([{ w: 1, h: 1, group: 'A' }, { w: 2, h: 1, group: 'A' }, { w: 1, h: 1, group: null },
                   { w: 2, h: 1, group: 'B' }, { w: 2, h: 1, group: 'B' }], 4);
    function cells(list) { var o = {}; list.forEach(function (s) { for (var y = s.r; y < s.r + s.h; y++) for (var x = s.c; x < s.c + s.w; x++) o[y + ',' + x] = 1; }); return o; }
    function connected(list) {
      var c = cells(list), keys = Object.keys(c), seen = {}, todo = [keys[0]];
      while (todo.length) { var k = todo.pop(); if (seen[k] || !c[k]) continue; seen[k] = 1;
        var p = k.split(',').map(Number); todo.push((p[0]-1)+','+p[1], (p[0]+1)+','+p[1], p[0]+','+(p[1]-1), p[0]+','+(p[1]+1)); }
      return Object.keys(seen).length === keys.length;
    }
    var all = cells(spots), overlap = spots.reduce(function (a, s) { return a + s.w * s.h; }, 0) !== Object.keys(all).length;
    return { spots: spots, aConnected: connected(spots.slice(0, 2)), bConnected: connected(spots.slice(3, 5)), overlap: overlap,
             rows: Math.max.apply(null, spots.map(function (s) { return s.r + s.h; })) };
  })()`);
  t.check('shaped: a group is placed as one connected piece', packed.aConnected && packed.bConnected, packed);
  t.check('shaped: no two tiles share a cell', !packed.overlap, packed);
  t.check('shaped: pieces and loose tiles pack into two rows of four', packed.rows === 2, packed);

  const outline = await g.js(`(function () {
    var O = MicroserviceManager.endo.outlinePath;
    // An L of three cells (two on top, one below left) is one ring of six corners;
    // two rectangles a sub-pixel apart are still one piece.
    return { L: O([[0, 0, 10, 10], [10, 0, 20, 10], [0, 10, 10, 20]]), near: O([[0, 0, 10, 10], [0, 10.4, 10, 20]]) };
  })()`);
  t.check('shaped: an L outline is one ring of six corners',
    (outline.L.match(/M/g) || []).length === 1 && (outline.L.match(/L/g) || []).length === 6, outline);
  t.check('shaped: rectangles a sub-pixel apart make one ring', (outline.near.match(/M/g) || []).length === 1, outline);

  // A shaped stage: two groups and a loose tile; outlines drawn, tabs on them,
  // and closing a group lays the stage out again with its chip.
  await g.js(`(function () {
    var MM = MicroserviceManager;
    var el = document.createElement('div');
    el.id = 'probeShape';
    el.style.cssText = 'position:fixed;left:20px;top:80px;z-index:99999;width:900px;background:#fff;container-type:inline-size';
    el.innerHTML = '<div class="endo-stage bench-stage"></div>';
    document.body.appendChild(el);
    var stage = el.firstChild;
    function tile(id, size) {
      var s = document.createElement('section');
      s.className = 'endo-tile ' + size;
      s.setAttribute('data-tile', id);
      s.innerHTML = '<header class="endo-tile-head"><span class="t">' + id + '</span></header><div class="endo-tile-body">' + id + '</div>';
      stage.appendChild(s);
      return { tileId: id, section: s, instance: null };
    }
    var a = [tile('a1', 'w1 h1'), tile('a2', 'w2 h1'), tile('a3', 'w2 h1')];
    var loose = tile('loose', 'w1 h1');
    var b = [tile('b1', 'w2 h1'), tile('b2', 'w1 h1')];
    MM.endo.applyGroups(stage, a, [{ id: 'a', title: 'Group A', tiles: ['a1', 'a2', 'a3'] }], { scope: 'shape', component: 'p.a', shape: true, piece: 1 });
    MM.endo.applyGroups(stage, b, [{ id: 'b', title: 'Group B', tiles: ['b1', 'b2'] }], { scope: 'shape', component: 'p.b', shape: true, piece: 2 });
    window.__shapeHandle = MM.endo.shapeStage(stage);
    return true;
  })()`);
  await new Promise((r) => setTimeout(r, 300));
  const shaped = await g.js(`(function () {
    var st = document.querySelector('#probeShape .endo-stage');
    var tab = st.querySelector('.endo-group-tab[data-group="a"]'), a1 = st.querySelector('[data-tile=a1]');
    var tr = tab.getBoundingClientRect(), ar = a1.getBoundingClientRect();
    return { rings: st.querySelectorAll('.endo-shapes path.line').length,
             tabAbove: tr.bottom <= ar.top + 2 && tr.bottom > ar.top - 30,
             placed: [].every.call(st.querySelectorAll('.endo-tile'), function (t) { return /span/.test(t.style.gridColumn); }) };
  })()`);
  t.check('shaped: one outline per open group', shaped.rings === 2, shaped);
  t.check('shaped: every tile is placed by the packer', shaped.placed, shaped);
  t.check('shaped: the title tab sits on the piece, just above its top tile', shaped.tabAbove, shaped);
  const colours = await g.js(`(function () {
    var lines = document.querySelectorAll('#probeShape .endo-shapes path.line');
    var tabs = document.querySelectorAll('#probeShape .endo-group-tab');
    return { lines: [].map.call(lines, function (l) { return getComputedStyle(l).stroke; }),
             tabs: [].map.call(tabs, function (t) { return getComputedStyle(t).borderTopColor; }),
             piece1: getComputedStyle(document.documentElement).getPropertyValue('--piece-1').trim() };
  })()`);
  t.check('shaped: each component has its own piece colour', colours.lines.length === 2 && colours.lines[0] !== colours.lines[1], colours);
  t.check('shaped: the piece colours come from the theme tokens', colours.piece1 === '#2F6FB0', colours);
  t.check('shaped: a tab has its piece colour', colours.tabs[0] !== colours.tabs[1], colours);
  await g.click('#probeShape .endo-group-tab[data-group="b"] button');
  await new Promise((r) => setTimeout(r, 300));
  const closed = await g.js(`(function () {
    var st = document.querySelector('#probeShape .endo-stage'), tab = st.querySelector('.endo-group-tab[data-group="b"]');
    return { rings: st.querySelectorAll('.endo-shapes path.line').length, chip: getComputedStyle(tab).position, hidden: st.querySelector('[data-tile=b1]').hidden,
             chipPlaced: /span/.test(tab.style.gridColumn) };
  })()`);
  t.check('shaped: closing a group drops its outline and shows its chip in the grid',
    closed.rings === 1 && closed.chip === 'static' && closed.hidden && closed.chipPlaced, closed);
});
