/**
 * @fileoverview Bench Endoskeleton host bus (milestone M3): live signals for
 * every tile of this window over ONE WebSocket to the bridge.
 *
 * Tiles never talk to the bus directly: they get ctx.signals from host.js,
 * which checks the manifest's capabilities first (R1). The bus counts
 * subscribers per signal name and tells the bridge only about the first
 * subscriber and the last one leaving, so 20 tiles on the same signal are
 * one name on the wire; the bridge in turn keeps one upstream stream per
 * owning graph service (adapters/signals/hub.py).
 *
 *   MM.endo.bus.subscribe(names, cb)  -> unsubscribe()    cb(name, value, ts)
 *   MM.endo.bus.onStatus(names, cb)   -> off()            cb({name, state, message})
 *   MM.endo.bus.set(name, value)      -> Promise<{success, message}>
 *   MM.endo.bus.configure({ getConsul })
 *   MM.endo.bus.stats()               -> { names, subscribers, socket, ... }
 *
 * Where signal-discovery is: the "Signal discovery" address the user set
 * (localStorage mm_signal_discovery, host:port), else the bridge looks up
 * the signal-discovery service in the first connected Consul.
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  MM.endo = MM.endo || {};

  var DISCOVERY_KEY = 'mm_signal_discovery';

  var subs = {};        // name -> Set of callbacks
  var statusSubs = {};  // name -> Set of callbacks
  var last = {};        // name -> { value, ts }
  var nameState = {};   // name -> { state, message }
  var ws = null;
  var wsState = 'idle'; // idle | connecting | open | retrying
  var discovery = '';   // as the bridge reported it
  var lastError = '';
  var retryTimer = null;
  var retryDelay = 1000;
  var closeTimer = null;
  var cfg = { getConsul: function () { return ''; } };
  var listeners = [];   // bus-level status listeners (status strip)

  function bridgeOrigin() {
    var origin = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    return origin && origin.indexOf('http') === 0 ? origin : 'http://localhost:1112';
  }

  function discoveryOverride() {
    try { return localStorage.getItem(DISCOVERY_KEY) || ''; } catch (e) { return ''; }
  }

  function names() { return Object.keys(subs); }

  function notify() {
    var s = stats();
    listeners.forEach(function (fn) { try { fn(s); } catch (e) { /* listener's problem */ } });
  }

  function setNameState(list, state, message) {
    list.forEach(function (n) {
      nameState[n] = { state: state, message: message || '' };
      (statusSubs[n] ? Array.from(statusSubs[n]) : []).forEach(function (cb) {
        try { cb({ name: n, state: state, message: message || '' }); } catch (e) { /* tile's problem */ }
      });
    });
  }

  // ------------------------------------------------------------ socket

  function send(msg) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
  }

  function subscribeMsg(list) {
    return { op: 'subscribe', names: list, discovery: discoveryOverride() || undefined,
             consul: (cfg.getConsul && cfg.getConsul()) || undefined };
  }

  function connect() {
    if (ws || !names().length) return;
    clearTimeout(retryTimer);
    wsState = 'connecting';
    notify();
    var url = bridgeOrigin().replace(/^http/, 'ws') + '/api/signals/stream';
    var sock;
    try { sock = new WebSocket(url); }
    catch (e) { lastError = e.message; scheduleRetry(); return; }
    ws = sock;
    sock.onopen = function () {
      if (ws !== sock) return;
      wsState = 'open';
      retryDelay = 1000;
      lastError = '';
      var list = names();
      if (list.length) send(subscribeMsg(list));
      notify();
    };
    sock.onmessage = function (ev) {
      if (ws !== sock) return;
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'update') {
        var changed = false;
        if (/^signal-discovery at /.test(lastError)) { lastError = ''; changed = true; }
        (msg.values || []).forEach(function (v) {
          last[v.name] = { value: v.value, ts: v.ts };
          if (!nameState[v.name] || nameState[v.name].state !== 'live') {
            setNameState([v.name], 'live', '');
            changed = true;
          }
          (subs[v.name] ? Array.from(subs[v.name]) : []).forEach(function (cb) {
            try { cb(v.name, v.value, v.ts); } catch (e) { /* tile's problem */ }
          });
        });
        if (changed) notify();
      } else if (msg.type === 'ready') {
        discovery = msg.discovery || '';
        notify();
      } else if (msg.type === 'unknown') {
        setNameState(msg.names || [], 'unknown', msg.message || 'not in the signal catalog');
        // Discovery itself failing is the cause worth showing, not the names.
        if (/^signal-discovery at /.test(msg.message || '')) lastError = msg.message;
        notify();
      } else if (msg.type === 'status') {
        lastError = msg.state === 'retrying' ? (msg.endpoint + ': ' + (msg.message || 'retrying')) : '';
        notify();
      } else if (msg.type === 'error') {
        lastError = msg.message || 'error';
        setNameState(names().filter(function (n) { return !last[n]; }), 'error', lastError);
        notify();
      }
    };
    sock.onclose = function () {
      if (ws !== sock) return;
      ws = null;
      if (names().length) {
        lastError = lastError || 'bridge connection closed';
        scheduleRetry();
      } else {
        wsState = 'idle';
        notify();
      }
    };
    sock.onerror = function () {
      lastError = 'cannot reach the bridge at ' + bridgeOrigin();
    };
  }

  function scheduleRetry() {
    wsState = 'retrying';
    setNameState(names(), 'retrying', lastError);
    notify();
    clearTimeout(retryTimer);
    retryTimer = setTimeout(function () { ws = null; connect(); }, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 15000);
  }

  /** No subscriber left: close the socket shortly after (a re-render re-subscribes at once). */
  function maybeClose() {
    clearTimeout(closeTimer);
    if (names().length) return;
    closeTimer = setTimeout(function () {
      if (names().length) return;
      clearTimeout(retryTimer);
      if (ws) { var s = ws; ws = null; try { s.close(); } catch (e) { /* closing */ } }
      wsState = 'idle';
      notify();
    }, 1500);
  }

  // ------------------------------------------------------------ public

  /**
   * Subscribe to signal names. The callback gets the last known value at
   * once when there is one, then every update (<= 10 Hz per signal).
   * @returns {function} unsubscribe; calling it twice is harmless
   */
  function subscribe(list, cb) {
    list = (list || []).filter(function (n) { return typeof n === 'string' && n; });
    var added = [];
    list.forEach(function (n) {
      if (!subs[n]) { subs[n] = new Set(); added.push(n); }
      subs[n].add(cb);
      if (last[n]) setTimeout(function () { if (subs[n] && subs[n].has(cb)) cb(n, last[n].value, last[n].ts); }, 0);
    });
    clearTimeout(closeTimer);
    if (added.length) {
      if (ws && ws.readyState === 1) send(subscribeMsg(added));
      else connect();
    }
    notify();
    var done = false;
    return function unsubscribe() {
      if (done) return;
      done = true;
      var removed = [];
      list.forEach(function (n) {
        if (!subs[n]) return;
        subs[n].delete(cb);
        if (!subs[n].size) { delete subs[n]; delete last[n]; delete nameState[n]; removed.push(n); }
      });
      if (removed.length) send({ op: 'unsubscribe', names: removed });
      maybeClose();
      notify();
    };
  }

  /** Per-name state changes: live, unknown, retrying, error. */
  function onStatus(list, cb) {
    list.forEach(function (n) {
      (statusSubs[n] = statusSubs[n] || new Set()).add(cb);
      var now = nameState[n];
      if (now) {
        setTimeout(function () {
          if (statusSubs[n] && statusSubs[n].has(cb)) cb({ name: n, state: now.state, message: now.message });
        }, 0);
      }
    });
    return function off() {
      list.forEach(function (n) {
        if (!statusSubs[n]) return;
        statusSubs[n].delete(cb);
        if (!statusSubs[n].size) delete statusSubs[n];
      });
    };
  }

  function set(name, value) {
    return fetch(bridgeOrigin() + '/api/signals/set', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, value: value, discovery: discoveryOverride() || undefined,
                             consul: (cfg.getConsul && cfg.getConsul()) || undefined })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || d.status !== 'ok') throw new Error((d && d.error) || 'set failed');
      if (!d.success) throw new Error(d.message || (name + ' was not written'));
      return d;
    });
  }

  function stats() {
    var n = names();
    return {
      names: n.length,
      subscribers: n.reduce(function (a, k) { return a + subs[k].size; }, 0),
      socket: wsState,
      discovery: discovery || discoveryOverride(),
      discoveryOverride: discoveryOverride(),
      live: n.filter(function (k) { return nameState[k] && nameState[k].state === 'live'; }).length,
      unknown: n.filter(function (k) { return nameState[k] && nameState[k].state === 'unknown'; }),
      error: lastError
    };
  }

  function setDiscovery(addr) {
    try {
      if (addr) localStorage.setItem(DISCOVERY_KEY, addr);
      else localStorage.removeItem(DISCOVERY_KEY);
    } catch (e) { /* storage unavailable */ }
    // Re-bind: the bridge picks discovery on the first subscribe of a socket.
    if (ws) { var s = ws; ws = null; try { s.close(); } catch (e) { /* closing */ } }
    last = {};
    nameState = {};
    discovery = '';
    connect();
    notify();
  }

  MM.endo.bus = {
    subscribe: subscribe,
    onStatus: onStatus,
    set: set,
    stats: stats,
    setDiscovery: setDiscovery,
    configure: function (c) { cfg = Object.assign(cfg, c || {}); },
    onChange: function (fn) {
      listeners.push(fn);
      return function () { listeners = listeners.filter(function (f) { return f !== fn; }); };
    },
    DISCOVERY_KEY: DISCOVERY_KEY
  };
})();
