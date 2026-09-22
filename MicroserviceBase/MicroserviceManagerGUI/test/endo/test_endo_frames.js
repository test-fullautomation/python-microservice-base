// Frames (milestone M5): the SDK's module linking (the frame builds blob:
// modules from shipped sources, so relative imports are rewritten), the
// frame tile kind and the rule that only frame plugins ship code.
//   node test/endo/test_endo_frames.js      (from the GUI folder)
'use strict';

const fs = require('fs');
const path = require('path');
const SDK = require('../../web/js/endo/frame-sdk.js');
const C = require('../../web/js/endo/contract/lint.js');

const GUI = path.join(__dirname, '..', '..');
const DIR = path.join(GUI, 'web', 'js', 'endo', 'contract');
const componentSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'component.schema.json'), 'utf-8'));
const pluginSchema = JSON.parse(fs.readFileSync(path.join(DIR, 'plugin.schema.json'), 'utf-8'));
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf-8'));

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}
const clone = (o) => JSON.parse(JSON.stringify(o));
const throwsWith = (fn, re) => { try { fn(); return false; } catch (e) { return re.test(e.message); } };

// ---------- paths ----------
check('normalize', SDK.normalize('a/./b/../c.js') === 'a/c.js' && SDK.normalize('./x.js') === 'x.js');
check('normalize refuses leaving the root', SDK.normalize('../x.js') === null && SDK.normalize('a/../../x.js') === null);

// ---------- imports ----------
{
  const src = "import { a } from './a.js';\nimport b from \"../lib/b.js\";\nimport './side.js';\n" +
              "export { c } from './c.js';\nconst m = import('./lazy.js');\nimport x from 'bare';\nconst s = 'from ./not.js';";
  const found = SDK.importsOf('sub/mod.js', src);
  check('importsOf finds static, side-effect, re-export and dynamic imports',
        JSON.stringify(found) === JSON.stringify(['sub/a.js', 'lib/b.js', 'sub/side.js', 'sub/c.js', 'sub/lazy.js']), found);
  const out = SDK.rewriteImports('sub/mod.js', src, (p) => 'blob:' + p);
  check('rewriteImports swaps each relative specifier', /from 'blob:sub\/a\.js'/.test(out) && /from "blob:lib\/b\.js"/.test(out) &&
        /import 'blob:sub\/side\.js'/.test(out) && /import\('blob:sub\/lazy\.js'\)/.test(out), out);
  check('bare specifiers and strings are left alone', /from 'bare'/.test(out) && /'from \.\/not\.js'/.test(out));
  check('an import that was not shipped is an error', throwsWith(() => SDK.rewriteImports('m.js', "import './x.js'", () => null), /not shipped/));
}

// ---------- linking a module graph ----------
{
  const files = {
    'strip.js': "import { S } from './series.js';\nexport const v = S;",
    'series.js': "import { k } from './util/k.js';\nexport const S = k;",
    'util/k.js': 'export const k = 1;'
  };
  const order = [];
  const urls = SDK.linkModules(files, (src) => { order.push(src); return 'blob:' + order.length; });
  check('leaves are linked first', /export const k = 1/.test(order[0]) && /blob:1/.test(order[1]) && /blob:2/.test(order[2]), order);
  check('every file gets a URL', Object.keys(urls).sort().join() === 'series.js,strip.js,util/k.js');
  check('a missing module is reported', throwsWith(() => SDK.linkModules({ 'a.js': "import './b.js'" }, () => 'x'), /b\.js was not shipped/));
  check('a cycle is reported', throwsWith(() => SDK.linkModules({ 'a.js': "import './b.js'", 'b.js': "import './a.js'" }, () => 'x'), /circular/));
}

// ---------- the charts plugin's graph links ----------
{
  const base = path.join(GUI, 'web', 'plugins', 'charts');
  const files = {};
  const load = (p) => { if (files[p]) return; files[p] = fs.readFileSync(path.join(base, p), 'utf-8'); SDK.importsOf(p, files[p]).forEach(load); };
  load('drawer.js');
  check('charts drawer ships drawer, strip and series', Object.keys(files).sort().join() === 'drawer.js,series.js,strip.js', Object.keys(files));
  let n = 0;
  check('charts graph links', Object.keys(SDK.linkModules(files, () => 'blob:' + (++n))).length === 3);
}

// ---------- frame tiles ----------
{
  const hello = readJson(path.join(GUI, 'web', 'services', 'HelloService1.0.0', 'component.json'));
  const issues = C.lintComponent(hello, { schema: componentSchema });
  check('Hello (with a frame tile, renderer html) lints clean', issues.length === 0, issues.map(C.formatIssue));
  check('Hello ships its frame page', fs.existsSync(path.join(GUI, 'web', 'services', 'HelloService1.0.0', hello.tiles.filter((t) => t.kind === 'frame')[0].entry)));
  const m = clone(hello); m.tiles.find((t) => t.kind === 'frame').entry = '../../index.html';
  check('a frame entry cannot leave the component folder', C.lintComponent(m, { schema: componentSchema }).some((i) => i.rule === 'S'));
  const m2 = clone(hello); delete m2.tiles.find((t) => t.kind === 'frame').entry;
  check('a frame tile needs an entry', C.lintComponent(m2, { schema: componentSchema }).some((i) => i.rule === 'S'));
  const m3 = clone(hello); m3.tiles = m3.tiles.filter((t) => t.kind !== 'frame');
  check('renderer html without frame tiles warns', C.lintComponent(m3, { schema: componentSchema }).some((i) => i.rule === 'K'));
  const m4 = clone(hello); m4.renderer = 'wasm';
  check('renderer wasm still warns (not hosted yet)', C.lintComponent(m4, { schema: componentSchema }).some((i) => i.rule === 'K' && /wasm/.test(i.message)));
}

// ---------- only frame plugins ship code ----------
{
  const charts = readJson(path.join(GUI, 'web', 'plugins', 'charts', 'plugin.json'));
  const s = clone(charts); s.isolation = 'schema';
  check('a schema plugin with a kind module is refused', C.lintPlugin(s, { schema: pluginSchema }).some((i) => i.rule === 'P' && /run no module/.test(i.message)));
  const w = clone(charts); w.isolation = 'window'; w.main = 'm.js';
  check('a window plugin with a kind module is refused', C.lintPlugin(w, { schema: pluginSchema }).some((i) => i.rule === 'P'));
  check('the frame plugin itself is fine', C.lintPlugin(charts, { schema: pluginSchema }).length === 0);
}

// ---------- the shell side of the Electron setup ----------
{
  const main = fs.readFileSync(path.join(GUI, 'electron', 'main.js'), 'utf-8');
  check('main.js isolates sandboxed frames in their own process',
        /appendSwitch\('site-per-process'\)/.test(main) && /IsolateSandboxedIframes/.test(main));
  const host = fs.readFileSync(path.join(GUI, 'web', 'js', 'endo', 'frame-host.js'), 'utf-8');
  check('frames are sandboxed with scripts only', /setAttribute\('sandbox', 'allow-scripts'\)/.test(host) && !/allow-same-origin/.test(host.replace(/\/\/.*$/gm, '')));
  check('frames have no network (CSP connect-src none)', /connect-src 'none'/.test(host));
}

console.log('\n' + passes + ' passed, ' + failures + ' failed');
process.exit(failures ? 1 : 0);
