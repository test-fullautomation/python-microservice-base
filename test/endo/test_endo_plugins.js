// Plugins (milestone M4): the bundled plugins lint clean, the plugin rules
// catch what they should, a plugin kind's schema and needs reach component
// linting, and the charts plugin's series maths.
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
  check('index lists the four reference plugins',
        JSON.stringify(index.plugins.slice().sort()) === JSON.stringify(['charts', 'graph-studio', 'robot-gen', 'test-project']), index.plugins);
  const manifests = {};
  index.plugins.forEach((id) => {
    const m = manifests[id] = readJson(path.join(PLUGINS, id, 'plugin.json'));
    check('bundled ' + id + ' lints clean', lintP(m).length === 0, lintP(m).map(C.formatIssue));
    check('bundled ' + id + ': id matches its folder', m.plugin === id);
    ((m.contributes && m.contributes.kinds) || []).concat((m.contributes && m.contributes['drawer.tabs']) || [])
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
  }

  // ---------- charts: series maths (ES module) ----------
  const S = await import(pathToFileURL(path.join(PLUGINS, 'charts', 'series.js')).href);
  check('parseWindow', S.parseWindow('120s') === 120000 && S.parseWindow('5m') === 300000 && S.parseWindow('x') === 60000);
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

  console.log('\n' + passes + ' passed, ' + failures + ' failed');
  process.exit(failures ? 1 : 0);
})();
