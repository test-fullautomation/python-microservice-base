// Host bus (milestone M3): subscribers are counted per signal name, so the
// bridge hears about a name once however many tiles show it; the socket
// closes when nothing is subscribed and resubscribes after a reconnect.
//   node test/endo/test_endo_bus.js      (from the GUI folder)
'use strict';

const path = require('path');

let failures = 0;
let passes = 0;
function check(name, cond, extra) {
  if (cond) { passes++; console.log('PASS', name); }
  else { failures++; console.log('FAIL', name, extra !== undefined ? JSON.stringify(extra).slice(0, 400) : ''); }
}
const tick = (ms) => new Promise((r) => setTimeout(r, ms || 0));

// ---- a browser-ish global: localStorage, a fake WebSocket, fetch ----
const sockets = [];
class FakeSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    sockets.push(this);
    setTimeout(() => { this.readyState = 1; this.onopen && this.onopen(); }, 0);
  }
  send(text) { this.sent.push(JSON.parse(text)); }
  close() { this.readyState = 3; this.closed = true; }
  push(msg) { this.onmessage && this.onmessage({ data: JSON.stringify(msg) }); }
  drop() { this.readyState = 3; this.onclose && this.onclose(); }
}
const store = {};
global.window = global;
global.WebSocket = FakeSocket;
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; }
};
global.MicroserviceManager = { serviceClient: { apiUrl: 'http://127.0.0.1:1199' } };
require(path.join(__dirname, '..', '..', 'web', 'js', 'endo', 'bus.js'));
const bus = global.MicroserviceManager.endo.bus;
bus.configure({ getConsul: () => 'http://127.0.0.1:8500' });

const sentOps = (s) => s.sent.map((m) => m.op + ':' + (m.names || []).join(','));

(async () => {
  const A = 'bench.dut.temp.degC';
  const B = 'bench.dut.adc_ch0.raw_V';
  const seen = [];
  const offs = [];
  for (let i = 0; i < 20; i++) offs.push(bus.subscribe([A, B], (n, v) => seen.push([i, n, v])));
  await tick(5);
  check('one socket for all subscribers', sockets.length === 1, sockets.length);
  const s = sockets[0];
  check('socket goes to the bridge', s.url === 'ws://127.0.0.1:1199/api/signals/stream', s.url);
  check('20 subscribers of 2 names: one subscribe with both names',
        JSON.stringify(sentOps(s)) === JSON.stringify(['subscribe:' + A + ',' + B]), sentOps(s));
  check('the first subscribe carries the Consul for discovery', s.sent[0].consul === 'http://127.0.0.1:8500');
  check('stats count names and subscribers', bus.stats().names === 2 && bus.stats().subscribers === 40, bus.stats());

  s.push({ type: 'ready', discovery: '127.0.0.1:50210' });
  s.push({ type: 'update', values: [{ name: A, value: 21.5, ts: 1 }] });
  check('an update reaches every subscriber of that name', seen.filter((x) => x[1] === A).length === 20);
  check('the name is live', bus.stats().live === 1 && bus.stats().discovery === '127.0.0.1:50210', bus.stats());

  // A late subscriber gets the last value at once.
  let late = null;
  const offLate = bus.subscribe([A], (n, v) => { late = v; });
  await tick(5);
  check('a late subscriber gets the last value', late === 21.5, late);
  check('a known name is not subscribed again', sentOps(s).length === 1, sentOps(s));
  offLate();

  for (let i = 0; i < 19; i++) offs[i]();
  check('names stay while one subscriber is left', sentOps(s).length === 1, sentOps(s));
  offs[19]();
  offs[19]();   // twice is harmless
  check('the last subscriber leaving unsubscribes both names',
        sentOps(s)[1] === 'unsubscribe:' + A + ',' + B, sentOps(s));
  await tick(1700);
  check('the socket closes when nothing is subscribed', s.closed === true && bus.stats().socket === 'idle', bus.stats());

  // Reconnect: every current name is subscribed again on the new socket.
  const off1 = bus.subscribe([A], () => {});
  const off2 = bus.subscribe([B], () => {});
  await tick(5);
  const s2 = sockets[sockets.length - 1];
  s2.drop();
  check('a dropped socket retries', bus.stats().socket === 'retrying', bus.stats());
  await tick(1100);
  const s3 = sockets[sockets.length - 1];
  await tick(5);
  check('after reconnecting, current names are subscribed again',
        s3 !== s2 && s3.sent.length === 1 && s3.sent[0].names.sort().join(',') === [A, B].sort().join(','), s3.sent);

  // Unknown names and discovery errors are reported per name.
  let status = null;
  const offS = bus.onStatus([B], (st) => { status = st; });
  s3.push({ type: 'unknown', names: [B], message: 'signal-discovery at 127.0.0.1:1: failed' });
  check('unknown names reach status listeners', status && status.state === 'unknown', status);
  check('a discovery failure becomes the bus error', /signal-discovery at/.test(bus.stats().error), bus.stats());
  offS(); off1(); off2();

  // The discovery address the user set goes with the next subscribe.
  bus.setDiscovery('10.0.0.5:50210');
  const off3 = bus.subscribe([A], () => {});
  await tick(5);
  const s4 = sockets[sockets.length - 1];
  check('a discovery override is sent', s4.sent.some((m) => m.discovery === '10.0.0.5:50210'), s4.sent);
  off3();
  bus.setDiscovery('');

  console.log('\n' + passes + ' passed, ' + failures + ' failed');
  process.exit(failures ? 1 : 0);
})();
