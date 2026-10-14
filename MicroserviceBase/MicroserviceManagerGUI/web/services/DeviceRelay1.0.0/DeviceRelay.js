(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  var SVC = { 
    relay: 'device.RelayService',
    psw: 'device.PowerSwitchService'
  };
  var POLL_MS = 2000;
  var CALL_TIMEOUT_MS = 8000;

  var countRelay = 0;
  var countPsw = 0;
  var activeRunId = 0;
  var timer = null;
  var failStreak = 0;
  var pending = {};
  var optState = {}; // optimistic state

  function ctx() {
    if (MM.currentGuiService && MM.currentGuiService.name === 'testbench-device-mock') {
      return { name: 'testbench-device-relay-mock', consulUrl: MM.currentGuiService.consulUrl };
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

  function confirmAction(title, msg) {
    return new Promise(function(resolve) {
      var backdrop = el('swConfirmBackdrop');
      var titleEl = el('swConfirmTitle');
      var msgEl = el('swConfirmMsg');
      var okBtn = el('swConfirmOkBtn');
      var cancelBtn = el('swConfirmCancelBtn');
      
      if (!backdrop) return resolve(window.confirm(title + ': ' + msg));
      
      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.textContent = msg;
      
      backdrop.classList.remove('d-none');
      
      function cleanup() {
        backdrop.classList.add('d-none');
        okBtn.onclick = null;
        cancelBtn.onclick = null;
      }
      
      okBtn.onclick = function() { cleanup(); resolve(true); };
      cancelBtn.onclick = function() { cleanup(); resolve(false); };
    });
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
      var t = setTimeout(function () { if (!done) { done = true; reject(new Error('Timeout')); } }, tms);
      req.then(function (data) {
        if (!done) { done = true; clearTimeout(t); resolve(data); }
      }).catch(function (err) {
        if (!done) { done = true; clearTimeout(t); reject(err); }
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

  function swShowErr(type, ch, msg) {
    var err = el('swErr_' + type + '_' + ch);
    if (!err) return;
    err.textContent = msg || '';
    err.classList.toggle('d-none', !msg);
  }

  function render() {
    var c = ctx();
    var t = el('swTarget');
    if (t) t.textContent = (c.name || '?') + ' @ ' + (c.address || '?') + ':' + (c.port || '?');
  }

  function buildTables() {
    var hint = el('swHint'); if (hint) hint.classList.add('d-none');
    var container = el('swChannelsContainer');
    if (!container) return;

    var html = '<div class="row g-3">';
    
    // Function to generate a table column for a subset of channels
    function genCol(type, startCh, endCh) {
      if (startCh >= endCh) return '';
      var out = '<div class="col-12 col-md-6"><table class="table table-sm table-hover align-middle sw-tbl mb-0">' +
          '<thead><tr><th>Channel</th><th class="text-end"><div class="d-inline-block text-center" style="width: 125px;">State</div></th></tr></thead><tbody>';
      for (var i = startCh; i < endCh; i++) {
        optState[type + i] = undefined;
        var lblText = type === 'relay' ? 'OPEN' : 'OFF';
        out += '<tr><td>CH ' + i + '</td>' +
          '<td class="text-end"><div class="form-check form-switch d-inline-block text-start mb-0" style="width: 125px;">' +
            '<input class="form-check-input" type="checkbox" role="switch" id="swOut_' + type + '_' + i + '" data-sw-type="' + type + '" data-sw-ch="' + i + '" style="cursor:pointer;">' +
            '<label class="form-check-label ms-2 text-muted" for="swOut_' + type + '_' + i + '" id="swLbl_' + type + '_' + i + '" style="min-width: 60px;">' + lblText + '</label>' +
          '</div>' +
          '<div class="text-danger small d-none" id="swErr_' + type + '_' + i + '"></div></td></tr>';
      }
      out += '</tbody></table></div>';
      return out;
    }

    // Build Relay Block
    if (countRelay > 0) {
      html += '<div class="col-12"><div class="sw-card shadow-sm h-100 mb-0">' +
        '<div class="text-muted small mb-2 fw-bold"><i class="bi bi-lightning-charge me-1"></i>Relays</div>' +
        '<div class="row">';
      var halfRelay = Math.ceil(countRelay / 2);
      html += genCol('relay', 0, halfRelay);
      html += genCol('relay', halfRelay, countRelay);
      html += '</div></div></div>';
    }

    // Build Power Switch Block
    if (countPsw > 0) {
      html += '<div class="col-12"><div class="sw-card shadow-sm h-100 mb-0">' +
        '<div class="text-muted small mb-2 fw-bold"><i class="bi bi-plug me-1"></i>Power Switches</div>' +
        '<div class="row">';
      var halfPsw = Math.ceil(countPsw / 2);
      html += genCol('psw', 0, halfPsw);
      html += genCol('psw', halfPsw, countPsw);
      html += '</div></div></div>';
    }

    html += '</div>';
    container.innerHTML = html;

    // Attach event listeners
    Array.prototype.forEach.call(container.querySelectorAll('input[data-sw-type]'), function (sw) {
      sw.addEventListener('change', function () {
        var originalState = !sw.checked;
        sw.checked = originalState; // revert visually immediately

        var type = sw.getAttribute('data-sw-type');
        var chNum = sw.getAttribute('data-sw-ch');
        var isRelay = type === 'relay';
        var title = (isRelay ? 'Relay ' : 'Power Switch ') + chNum;
        var targetState = !originalState;
        var actionName = isRelay ? (targetState ? 'close (activate)' : 'open (deactivate)') : (targetState ? 'turn ON' : 'turn OFF');
        var msg = 'Are you sure you want to ' + actionName + ' this channel?';
          
        confirmAction(title, msg).then(function(confirmed) {
          if (!confirmed) return;
          sw.checked = targetState;
          setSwitch(type, Number(chNum), targetState); 
        });
      });
    });
  }
  function showSwitch(type, ch, state) {
    var sw = el('swOut_' + type + '_' + ch);
    var lbl = el('swLbl_' + type + '_' + ch);
    var isRelay = type === 'relay';

    var activeState = state !== undefined ? state : (optState[type + ch] !== undefined ? optState[type + ch] : (sw ? sw.checked : false));
    
    if (!pending[type + ch + '_out']) {
      if (sw) sw.checked = !!activeState;
      if (lbl) {
        lbl.textContent = isRelay ? (activeState ? 'CLOSED' : 'OPEN') : (activeState ? 'ON' : 'OFF');
        lbl.className = 'form-check-label ms-2 ' + (activeState ? 'text-success' : 'text-muted');
      }
    }
  }

  function round(myId) {
    var jobs = [];
    
    for (var i = 0; i < countRelay; i++) {
      (function (ch) {
        jobs.push(function () {
          return call(SVC.relay, 'GetRelay', { channel: ch }).then(function (r) { showSwitch('relay', ch, r.closed); });
        });
      })(i);
    }
    
    for (var j = 0; j < countPsw; j++) {
      (function (ch) {
        jobs.push(function () {
          return call(SVC.psw, 'GetPowerSwitch', { channel: ch }).then(function (r) { showSwitch('psw', ch, r.on); });
        });
      })(j);
    }

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

  function setSwitch(type, ch, state) {
    swShowErr(type, ch, '');
    var sw = el('swOut_' + type + '_' + ch);
    var lbl = el('swLbl_' + type + '_' + ch);
    var isRelay = type === 'relay';

    pending[type + ch + '_out'] = true; 
    if (sw) sw.disabled = true;
    
    if (lbl) {
      lbl.textContent = isRelay ? (state ? 'CLOSED' : 'OPEN') : (state ? 'ON' : 'OFF');
      lbl.className = 'form-check-label ms-2 ' + (state ? 'text-success' : 'text-muted');
    }

    var svc = isRelay ? SVC.relay : SVC.psw;
    var setMethod = isRelay ? 'SetRelay' : 'SetPowerSwitch';
    var getMethod = isRelay ? 'GetRelay' : 'GetPowerSwitch';
    var setArgs = isRelay ? { channel: ch, closed: state } : { channel: ch, on: state };
    var stateField = isRelay ? 'closed' : 'on';

    call(svc, setMethod, setArgs)
      .then(function () { optState[type + ch] = state; return call(svc, getMethod, { channel: ch }); })
      .then(function (r) { pending[type + ch + '_out'] = false; showSwitch(type, ch, r[stateField]); })
      .catch(function (e) {
        pending[type + ch + '_out'] = false;
        swShowErr(type, ch, e.message);
        if (sw) sw.checked = !state;
        if (lbl) {
          lbl.textContent = isRelay ? (!state ? 'CLOSED' : 'OPEN') : (!state ? 'ON' : 'OFF');
          lbl.className = 'form-check-label ms-2 ' + (!state ? 'text-success' : 'text-muted');
        }
      })
      .then(function () { if (sw) sw.disabled = false; });
  }

  function start() {
    stop();
    var myId = activeRunId;

    pending = {};
    failStreak = 0;

    var hint = el('swHint'); if (hint) hint.classList.remove('d-none');
    var eW = el('swErrorWrap'); if (eW) eW.classList.add('d-none');

    render();

    var cRelay, cPsw;
    try {
      cRelay = call(SVC.relay, 'GetChannelCount', {}, 3000).then(function (r) { return Number(r.count) || 0; }).catch(function () { return 0; });
    } catch (e) {
      cRelay = Promise.resolve(0);
    }
    try {
      cPsw = call(SVC.psw, 'GetChannelCount', {}, 3000).then(function (r) { return Number(r.count) || 0; }).catch(function () { return 0; });
    } catch (e) {
      cPsw = Promise.resolve(0);
    }

    Promise.all([cRelay, cPsw]).then(function (res) {
      if (myId !== activeRunId) return;
      countRelay = res[0];
      countPsw = res[1];
      
      buildTables();

      if (countRelay === 0 && countPsw === 0) {
        if (eW) eW.classList.remove('d-none');
        showErr('swError', 'This service reports no Relay or Power Switch channels.');
        return;
      }

      round(myId).catch(function () { }).then(function () { loop(myId); });
    }).catch(function (e) {
      if (myId !== activeRunId) return;
      if (eW) eW.classList.remove('d-none');
      showErr('swError', String((e && e.message) || e));
    });
  }

  var svcName = (MM.currentGuiService && MM.currentGuiService.name) || 'DeviceRelay';
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

  window['loadDeviceRelay1.0.0'] = function() { start(); };
  window['unloadDeviceRelay1.0.0'] = function() { stop(); };

  start();

})();
