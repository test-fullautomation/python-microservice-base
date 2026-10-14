/**
 * GUI for the Device I/O service (legacy html+js panel, Bootstrap from the host).
 *
 * What is shown follows the service's adapter (DEVICE_HARDWARE_TYPE and the
 * DEVICE_*_CHANNELS of its job): the channels come from <Service>/GetChannelCount,
 * and a capability with no channels (or one the service does not offer) is hidden.
 *
 * Requests are sent one at a time and a new round only starts when the previous
 * one has finished, so a slow bridge or service can never pile requests up.
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  var SVC = {
    ai: 'device.AnalogInputService',
    ao: 'device.AnalogOutputService',
    di: 'device.DigitalInputService',
    do: 'device.DigitalOutputService'
  };
  var CARD = { ai: 'dioCardAi', ao: 'dioCardAo', di: 'dioCardDi', do: 'dioCardDo' };
  var POLL_MS = 2000;
  var CALL_TIMEOUT_MS = 8000;

  var counts = { ai: 0, ao: 0, di: 0, do: 0 };
  var activeRunId = 0;
  var timer = null;
  var failStreak = 0;
  var doPending = {};

  function ctx() {
    if (MM.currentGuiService && MM.currentGuiService.name === 'testbench-device-mock') {
      return { name: 'testbench-device-ai-ao-di-do-mock', consulUrl: MM.currentGuiService.consulUrl };
    }
    return MM.currentGuiService || {};
  }
  function el(id) {
    var els = document.querySelectorAll('#' + id);
    for (var i = 0; i < els.length; i++) {
      if (els[i].offsetParent !== null) return els[i];
    }
    return els[0];
  }

  function call(svc, method, args, timeoutMs) {
    var c = ctx();
    var req = MM.grpcClient.callMethod({
      consulName: c.name,
      consulUrl: c.consulUrl,
      grpcService: svc,
      method: method,
      argsJson: JSON.stringify(args || {})
    });

    var tms = timeoutMs || CALL_TIMEOUT_MS;
    return new Promise(function (resolve, reject) {
      var done = false;
      var t = setTimeout(function () {
        if (done) return;
        done = true;
        reject(new Error('Timeout calling ' + method));
      }, tms);

      req.then(function (data) {
        if (done) return;
        done = true;
        clearTimeout(t);
        resolve(data);
      }).catch(function (err) {
        if (done) return;
        done = true;
        clearTimeout(t);
        reject(err);
      });
    }).then(function (data) {
      if (!data || data.ok === false) throw new Error((data && (data.error || data.message)) || 'Call failed');
      var r = data.result !== undefined ? data.result : (data.response !== undefined ? data.response : data);
      if (r && (r.success === false || (r.success === undefined && r.message))) throw new Error(r.message || 'Command failed');
      return r;
    });
  }

  function showErr(id, msg) {
    var e = el(id);
    if (!e) return;
    e.textContent = msg || '';
    e.classList.toggle('d-none', !msg);
  }
  function pill(state) { return '<span class="dio-pill ' + (state ? 'hi' : 'lo') + '">' + (state ? 'High' : 'Low') + '</span>'; }

  function count(key) {
    try {
      var p = call(SVC[key], 'GetChannelCount', {}, 3000);
      return p.then(function (r) { return Number(r.count) || 0; }).catch(function () { return 0; });
    } catch (e) {
      return Promise.resolve(0);
    }
  }

  function render() {
    var c = ctx();
    var t = el('dioTarget');
    if (t) t.textContent = (c.name || '?') + ' @ ' + (c.address || '?') + ':' + (c.port || '?');
  }

  function buildTables() {
    var i, h;
    var hint = el('dioHint'); if (hint) hint.classList.add('d-none');
    Object.keys(CARD).forEach(function (k) { var e = el(CARD[k]); if (e) e.classList.toggle('d-none', counts[k] === 0); });

    h = '';
    var cHtml = '';
    for (i = 0; i < counts.ao; i++) {
      h += '<tr><td>Analog Output CH' + i + '</td>' +
        '<td class="text-end dio-val text-success fw-bold" id="dioAoVal' + i + '">…</td></tr>';
        
      cHtml += '<tr><td class="align-middle">Analog Output CH' + i + '</td>' +
        '<td class="text-end align-middle pe-3"><div class="input-group input-group-sm d-inline-flex" style="width: 125px;">' +
        '<input type="number" class="form-control text-end text-primary fw-bold" id="dioAoIn' + i + '" step="0.001" value="0.000" placeholder="0.000">' +
        '<span class="input-group-text text-primary fw-bold">V</span>' +
        '</div><div class="text-danger small mt-1 d-none" id="dioAoErr' + i + '"></div></td>' +
        '<td class="text-end align-middle"><button class="btn btn-sm btn-outline-primary fw-bold" data-ao="' + i + '" type="button">Set</button></td></tr>';
    }
    var aoR = el('dioAoRows');
    var aoC = el('dioAoControls');
    if (aoR) aoR.innerHTML = h;
    if (aoC) {
      aoC.innerHTML = cHtml;
      Array.prototype.forEach.call(aoC.querySelectorAll('button[data-ao]'), function (btn) {
        btn.onclick = function () { setAO(Number(btn.getAttribute('data-ao'))); };
      });
      Array.prototype.forEach.call(aoC.querySelectorAll('input[id^="dioAoIn"]'), function (inp) {
        inp.addEventListener('blur', function () {
          if (inp.value) inp.value = Number(inp.value).toFixed(3);
        });
      });
    }

    h = '';
    for (i = 0; i < counts.ai; i++) h += '<tr><td>Analog Input CH' + i + '</td><td class="text-end dio-val" id="dioAi' + i + '">…</td></tr>';
    var aiR = el('dioAiRows'); if (aiR) aiR.innerHTML = h;

    h = '';
    for (i = 0; i < counts.di; i++) h += '<tr><td>Digital Input CH' + i + '</td><td class="text-end"><div class="d-inline-block text-center" style="width: 75px;" id="dioDi' + i + '">…</div></td></tr>';
    var diR = el('dioDiRows'); if (diR) diR.innerHTML = h;

    h = '';
    for (i = 0; i < counts.do; i++) {
      h += '<tr><td>Digital Output CH' + i + '</td>' +
        '<td class="text-end"><div class="d-inline-flex justify-content-center" style="width: 75px;"><div class="form-check form-switch mb-0 text-start">' +
        '<input class="form-check-input" type="checkbox" role="switch" id="dioDoSw' + i + '" data-do="' + i + '" style="cursor:pointer">' +
        '<label class="form-check-label" style="width: 40px; display: inline-block; text-align: left;" for="dioDoSw' + i + '" id="dioDoLbl' + i + '">…</label></div></div>' +
        '<div class="text-danger small mt-1" id="dioDoErr' + i + '"></div></td></tr>';
    }
    var doR = el('dioDoRows');
    if (doR) {
      doR.innerHTML = h;
      Array.prototype.forEach.call(doR.querySelectorAll('input[data-do]'), function (sw) {
        sw.addEventListener('change', function () { setDO(Number(sw.getAttribute('data-do')), sw.checked); });
      });
    }
  }

  function showDO(ch, state) {
    var sw = el('dioDoSw' + ch), lbl = el('dioDoLbl' + ch);
    if (!sw || doPending[ch]) return;
    sw.checked = !!state;
    lbl.textContent = state ? 'High' : 'Low';
    lbl.className = 'form-check-label fw-bold ' + (state ? 'text-success' : 'text-muted');
  }

  function round(myId) {
    var jobs = [];
    function add(svc, method, ch, id, fmt) {
      jobs.push(function () {
        return call(SVC[svc], method, { channel: ch }).then(function (r) {
          var e = el(id + ch); if (e) e.innerHTML = fmt(r);
        });
      });
    }
    var i;
    for (i = 0; i < counts.ao; i++) add('ao', 'ReadAnalogOutput', i, 'dioAoVal', function (r) { return Number(r.value).toFixed(3) + ' V'; });
    for (i = 0; i < counts.ai; i++) add('ai', 'ReadAnalogInput', i, 'dioAi', function (r) { return Number(r.value).toFixed(3) + ' V'; });
    for (i = 0; i < counts.di; i++) add('di', 'ReadDigitalInput', i, 'dioDi', function (r) { return pill(r.state); });
    for (i = 0; i < counts.do; i++) (function (ch) {
      jobs.push(function () { return call(SVC.do, 'ReadDigitalOutput', { channel: ch }).then(function (r) { showDO(ch, r.state); }); });
    })(i);

    var errors = 0;
    return jobs.reduce(function (p, job) {
      return p.then(function () {
        if (myId !== activeRunId) return;
        return job().catch(function () { errors++; });
      });
    }, Promise.resolve()).then(function () {
      if (myId !== activeRunId) return;
      failStreak = errors === jobs.length && jobs.length > 0 ? failStreak + 1 : 0;
    });
  }

  function loop(myId) {
    if (myId !== activeRunId) return;
    var wait = POLL_MS * Math.min(1 + failStreak, 5);
    timer = setTimeout(function () {
      if (myId !== activeRunId) return;
      round(myId).catch(function () { }).then(function () { loop(myId); });
    }, wait);
  }

  function setAO(ch) {
    showErr('dioAoErr' + ch, '');
    var aoIn = el('dioAoIn' + ch);
    if (!aoIn) return;
    var val = parseFloat(aoIn.value);
    if (isNaN(val)) { showErr('dioAoErr' + ch, 'Invalid input'); return; }
    call(SVC.ao, 'SetAnalogOutput', { channel: ch, value: val })
      .then(function () { return call(SVC.ao, 'ReadAnalogOutput', { channel: ch }); })
      .then(function (r) { var v = el('dioAoVal' + ch); if (v) v.textContent = Number(r.value).toFixed(3) + ' V'; })
      .catch(function (e) { showErr('dioAoErr' + ch, e.message); });
  }

  function setDO(ch, state) {
    var err = el('dioDoErr' + ch); if (err) err.textContent = '';
    var sw = el('dioDoSw' + ch);
    doPending[ch] = true; if (sw) sw.disabled = true;
    call(SVC.do, 'SetDigitalOutput', { channel: ch, state: state })
      .then(function () { return call(SVC.do, 'ReadDigitalOutput', { channel: ch }); })
      .then(function (r) { doPending[ch] = false; showDO(ch, r.state); })
      .catch(function (e) {
        doPending[ch] = false;
        if (err) err.textContent = e.message;
        return call(SVC.do, 'ReadDigitalOutput', { channel: ch }).then(function (r) { showDO(ch, r.state); }).catch(function () { if (sw) sw.checked = !state; });
      })
      .then(function () { if (sw) sw.disabled = false; });
  }

  function start() {
    stop();
    var myId = activeRunId;

    render();
    doPending = {};
    failStreak = 0;

    var hint = el('dioHint'); if (hint) hint.classList.remove('d-none');
    showErr('dioError', '');

    var r = {};
    Promise.all(['ai', 'ao', 'di', 'do'].map(function (k) {
      return count(k).then(function (n) { r[k] = n; });
    })).then(function () {
      if (myId !== activeRunId) return;
      counts = { ai: r.ai || 0, ao: r.ao || 0, di: r.di || 0, do: r.do || 0 };
      buildTables();

      if (!(counts.ai || counts.ao || counts.di || counts.do)) {
        showErr('dioError', 'This service reports no I/O channels (check DEVICE_*_CHANNELS and DEVICE_HARDWARE_TYPE of its job).');
        return;
      }

      round(myId).catch(function () { }).then(function () { loop(myId); });
    }).catch(function (e) {
      if (myId !== activeRunId) return;
      showErr('dioError', String((e && e.message) || e));
    });
  }

  // Loader hooks that app.js calls when the panel is shown/hidden
  var svcName = (MM.currentGuiService && MM.currentGuiService.name) || 'DeviceIo';
  var oldLoad = window['load' + svcName];
  window['load' + svcName] = function() { if (oldLoad) oldLoad(); start(); };
  var oldUnload = window['unload' + svcName];
  function stop() {
    activeRunId++; // cancels any running loops or promise chains immediately
    if (timer) { clearTimeout(timer); timer = null; }
  }

  window['unload' + svcName] = function () {
    if (oldUnload) oldUnload();
    stop();
  };

  // Robust fallback for app.js caching mechanism
  window['loadDeviceIo1.0.0'] = function() { start(); };
  window['unloadDeviceIo1.0.0'] = function() { stop(); };

  // Start immediately upon script load
  start();

})();
