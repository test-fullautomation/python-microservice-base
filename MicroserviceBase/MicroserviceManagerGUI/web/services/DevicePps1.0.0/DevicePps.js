(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  var SVC = { pps: 'device.PPSService' };
  var POLL_MS = 2000;
  var CALL_TIMEOUT_MS = 8000;

  var countPps = 0;
  var activeRunId = 0;
  var timer = null;
  var failStreak = 0;
  var pending = {};
  var optState = {}; // optimistic state for output ON/OFF

  function ctx() {
    if (MM.currentGuiService && MM.currentGuiService.name === 'testbench-device-mock') {
      return { name: 'testbench-device-pps-mock', consulUrl: MM.currentGuiService.consulUrl };
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
      var backdrop = el('ppsConfirmBackdrop');
      var titleEl = el('ppsConfirmTitle');
      var msgEl = el('ppsConfirmMsg');
      var okBtn = el('ppsConfirmOkBtn');
      var cancelBtn = el('ppsConfirmCancelBtn');
      
      if (!backdrop) return resolve(window.confirm(title + ': ' + msg)); // Fallback
      
      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.textContent = msg;
      
      backdrop.classList.remove('d-none');
      
      function cleanup() {
        backdrop.classList.add('d-none');
        okBtn.onclick = null;
        cancelBtn.onclick = null;
      }
      
      okBtn.onclick = function() {
        cleanup();
        resolve(true);
      };
      
      cancelBtn.onclick = function() {
        cleanup();
        resolve(false);
      };
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

  function count() {
    try {
      var p = call(SVC.pps, 'GetChannelCount', {}, 3000);
      return p.then(function (r) { return Number(r.count) || 0; }).catch(function () { return 0; });
    } catch (e) {
      return Promise.resolve(0);
    }
  }

  function render() {
    var c = ctx();
    var t = el('ppsTarget');
    if (t) t.textContent = (c.name || '?') + ' @ ' + (c.address || '?') + ':' + (c.port || '?');
  }

  function buildTables() {
    var hint = el('ppsHint'); if (hint) hint.classList.add('d-none');
    var container = el('ppsChannelsContainer');
    if (!container) return;

    var html = '<div class="row g-3">';
    
    if (countPps > 0) {
      html += '<div class="col-12"><div class="pps-card shadow-sm h-100 mb-0" style="padding: 16px 20px;">' +
        '<div class="text-muted small mb-2 fw-bold"><i class="bi bi-battery-charging me-1"></i>Power Supply Channels</div>' +
        '<div class="row g-3">';
        
      for (var i = 0; i < countPps; i++) {
        optState[i] = undefined;
        html += '<div class="col-12 col-xl-6">' +
          '<div class="border rounded p-3 h-100" id="ppsCard' + i + '">' +
            '<div class="channel-header mb-3" style="border-bottom: 1px solid #eee; padding-bottom: 8px;">' +
              '<div class="text-muted fw-bold">CH ' + i + '</div>' +
              '<div class="form-check form-switch mb-0 d-flex align-items-center">' +
                '<input class="form-check-input" type="checkbox" role="switch" id="ppsOutSw' + i + '" data-pps-out="' + i + '" style="cursor:pointer;">' +
                '<label class="form-check-label ms-2 text-muted" for="ppsOutSw' + i + '" id="ppsOutLbl' + i + '" style="min-width: 35px;">OFF</label>' +
              '</div>' +
            '</div>' +
            '<table class="table table-sm table-hover align-middle pps-tbl mb-0">' +
            '<colgroup><col style="width:50%"><col style="width:50%"></colgroup>' +
            '<tbody>' +
              // Readings
              '<tr><td>Voltage</td><td class="text-end text-success fw-bold" id="ppsV' + i + '">…</td></tr>' +
              '<tr><td>Current Limit</td><td class="text-end text-success fw-bold" id="ppsILim' + i + '">…</td></tr>' +
              '<tr><td>Current</td><td class="text-end text-success fw-bold" id="ppsI' + i + '">…</td></tr>' +
            '</tbody></table>' +
            // Set controls (same layout as DeviceIo analog output)
            '<table class="table table-sm align-middle pps-tbl mb-0 mt-2">' +
            '<colgroup><col style="width:40%"><col><col style="width:55px"></colgroup>' +
            '<tbody>' +
              '<tr>' +
                '<td class="align-middle">Set Voltage</td>' +
                '<td class="text-end align-middle pe-3"><div class="input-group input-group-sm d-inline-flex" style="width: 125px;">' +
                  '<input type="number" class="form-control text-end text-primary fw-bold" id="ppsInpV' + i + '" step="0.001" value="0.000" placeholder="0.000">' +
                  '<span class="input-group-text text-primary fw-bold">V</span>' +
                '</div></td>' +
                '<td class="text-end align-middle"><button class="btn btn-sm btn-outline-primary fw-bold" data-pps-v="' + i + '" type="button">Set</button></td>' +
              '</tr>' +
              '<tr>' +
                '<td class="align-middle border-bottom-0">Set Current Limit</td>' +
                '<td class="text-end align-middle pe-3 border-bottom-0"><div class="input-group input-group-sm d-inline-flex" style="width: 125px;">' +
                  '<input type="number" class="form-control text-end text-primary fw-bold" id="ppsInpILim' + i + '" step="0.001" value="0.000" placeholder="0.000">' +
                  '<span class="input-group-text text-primary fw-bold">A</span>' +
                '</div></td>' +
                '<td class="text-end align-middle border-bottom-0"><button class="btn btn-sm btn-outline-primary fw-bold" data-pps-ilim="' + i + '" type="button">Set</button></td>' +
              '</tr>' +
              '<tr style="display:none;" id="ppsErrRow' + i + '"><td colspan="3" class="p-0 border-0 pt-2"><div class="text-danger small mb-1 text-center" id="ppsErr' + i + '"></div></td></tr>' +
            '</tbody></table>' +
          '</div></div>';
      }
      
      html += '</div></div></div>';
    }
    
    html += '</div>';

    container.innerHTML = html;

    Array.prototype.forEach.call(container.querySelectorAll('input[data-pps-out]'), function (sw) {
      sw.addEventListener('change', function () {
        var originalState = !sw.checked;
        sw.checked = originalState;

        var chNum = sw.getAttribute('data-pps-out');
        var title = 'Channel ' + chNum;
        var targetState = !originalState;
        var msg = targetState
          ? 'Enable power output?'
          : 'Disable power output?';

        confirmAction(title, msg).then(function(confirmed) {
          if (!confirmed) return;
          sw.checked = targetState;
          setOut(Number(chNum), targetState);
        });
      });
    });

    Array.prototype.forEach.call(container.querySelectorAll('button[data-pps-v]'), function (btn) {
      btn.onclick = function () { setV(Number(btn.getAttribute('data-pps-v'))); };
    });
    Array.prototype.forEach.call(container.querySelectorAll('button[data-pps-ilim]'), function (btn) {
      btn.onclick = function () { setILim(Number(btn.getAttribute('data-pps-ilim'))); };
    });

    Array.prototype.forEach.call(container.querySelectorAll('input[id^="ppsInpV"], input[id^="ppsInpILim"]'), function (inp) {
      inp.addEventListener('blur', function () {
        if (inp.value) inp.value = Number(inp.value).toFixed(3);
      });
    });
  }

  function ppsShowErr(ch, msg) {
    var err = el('ppsErr' + ch);
    var row = el('ppsErrRow' + ch);
    if (!err || !row) return;
    err.textContent = msg || '';
    if (msg) row.style.display = '';
    else row.style.display = 'none';
  }

  function showPPS(ch, st) {
    if (!st || pending[ch + '_read']) return;
    var vEl = el('ppsV' + ch);
    var ilimEl = el('ppsILim' + ch);
    var iEl = el('ppsI' + ch);
    
    var sw = el('ppsOutSw' + ch);
    var lbl = el('ppsOutLbl' + ch);
    var card = el('ppsCard' + ch);
    
    var isOutEnabled = st.output_enabled !== undefined ? st.output_enabled : (optState[ch] !== undefined ? optState[ch] : (sw ? sw.checked : false));
    
    if (vEl) vEl.textContent = Number(st.voltage || 0).toFixed(3) + ' V';
    if (ilimEl) ilimEl.textContent = Number(st.current_limit || 0).toFixed(3) + ' A';
    if (iEl) iEl.textContent = Number(st.current || 0).toFixed(3) + ' A';

    if (!pending[ch + '_out']) {
      if (sw) sw.checked = !!isOutEnabled;
      if (lbl) {
        lbl.textContent = isOutEnabled ? 'ON' : 'OFF';
        lbl.className = 'form-check-label ms-2 ' + (isOutEnabled ? 'text-success' : 'text-muted');
      }
      if (card) {
        card.classList.toggle('card-on', !!isOutEnabled);
        card.classList.toggle('card-off', !isOutEnabled);
      }
    }
  }

  function round(myId) {
    var jobs = [];
    for (var i = 0; i < countPps; i++) {
      (function (ch) {
        jobs.push(function () {
          return call(SVC.pps, 'GetPPSState', { channel: ch }).then(function (r) { showPPS(ch, r); });
        });
      })(i);
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

  function setOut(ch, state) {
    ppsShowErr(ch, '');
    var sw = el('ppsOutSw' + ch);
    var lbl = el('ppsOutLbl' + ch);
    var card = el('ppsCard' + ch);
    pending[ch + '_out'] = true; if (sw) sw.disabled = true;
    
    if (lbl) {
      lbl.textContent = state ? 'ON' : 'OFF';
      lbl.className = 'form-check-label ms-2 ' + (state ? 'text-success' : 'text-muted');
    }
    if (card) {
      card.classList.toggle('card-on', !!state);
      card.classList.toggle('card-off', !state);
    }

    pending[ch + '_read'] = true;
    call(SVC.pps, 'SetOutputEnabled', { channel: ch, enabled: state })
      .then(function () { optState[ch] = state; return call(SVC.pps, 'GetPPSState', { channel: ch }); })
      .then(function (r) { pending[ch + '_read'] = false; pending[ch + '_out'] = false; showPPS(ch, r); })
      .catch(function (e) {
        pending[ch + '_read'] = false; pending[ch + '_out'] = false;
        ppsShowErr(ch, e.message);
        if (sw) sw.checked = !state;
        if (lbl) {
          lbl.textContent = !state ? 'ON' : 'OFF';
          lbl.className = 'form-check-label ms-2 ' + (!state ? 'text-success' : 'text-muted');
        }
        if (card) {
          card.classList.toggle('card-on', !state);
          card.classList.toggle('card-off', !!state);
        }
      })
      .then(function () { if (sw) sw.disabled = false; });
  }

  function setV(ch) {
    ppsShowErr(ch, '');
    var inp = el('ppsInpV' + ch);
    if (!inp) return;
    var val = parseFloat(inp.value);
    if (isNaN(val)) { ppsShowErr(ch, 'Invalid input'); return; }
    
    var title = 'Channel ' + ch;
    var msg = 'Change voltage to ' + val.toFixed(3) + ' V?';
    
    confirmAction(title, msg).then(function(confirmed) {
      if (!confirmed) return;
      pending[ch + '_read'] = true;
      call(SVC.pps, 'SetVoltage', { channel: ch, voltage: val })
        .then(function () { return call(SVC.pps, 'GetPPSState', { channel: ch }); })
        .then(function (r) { pending[ch + '_read'] = false; showPPS(ch, r); })
        .catch(function (e) { pending[ch + '_read'] = false; ppsShowErr(ch, e.message); });
    });
  }

  function setILim(ch) {
    ppsShowErr(ch, '');
    var inp = el('ppsInpILim' + ch);
    if (!inp) return;
    var val = parseFloat(inp.value);
    if (isNaN(val)) { ppsShowErr(ch, 'Invalid input'); return; }
    
    var title = 'Channel ' + ch;
    var msg = 'Change current limit to ' + val.toFixed(3) + ' A?';
    
    confirmAction(title, msg).then(function(confirmed) {
      if (!confirmed) return;
      pending[ch + '_read'] = true;
      call(SVC.pps, 'SetCurrentLimit', { channel: ch, current: val }) // current instead of current_limit as per device.proto
        .then(function () { return call(SVC.pps, 'GetPPSState', { channel: ch }); })
        .then(function (r) { pending[ch + '_read'] = false; showPPS(ch, r); })
        .catch(function (e) { pending[ch + '_read'] = false; ppsShowErr(ch, e.message); });
    });
  }

  function stop() {
    activeRunId++; // cancels any running loops or promise chains immediately
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function start() {
    stop();
    var myId = activeRunId;

    pending = {};
    failStreak = 0;

    var hint = el('ppsHint'); if (hint) hint.classList.remove('d-none');
    var eW = el('ppsErrorWrap'); if (eW) eW.classList.add('d-none');

    render();

    count().then(function (n) {
      if (myId !== activeRunId) return;
      countPps = n;
      buildTables();

      if (countPps === 0) {
        if (eW) eW.classList.remove('d-none');
        showErr('ppsError', 'This service reports no PPS channels (check DEVICE_PPS_CHANNELS of its job).');
        return;
      }

      round(myId).catch(function () { }).then(function () { loop(myId); });
    }).catch(function (e) {
      if (myId !== activeRunId) return;
      if (eW) eW.classList.remove('d-none');
      showErr('ppsError', String((e && e.message) || e));
    });
  }

  var svcName = (MM.currentGuiService && MM.currentGuiService.name) || 'DevicePps';
  var oldLoad = window['load' + svcName];
  window['load' + svcName] = function() { if (oldLoad) oldLoad(); start(); };
  var oldUnload = window['unload' + svcName];
  window['unload' + svcName] = function () {
    if (oldUnload) oldUnload();
    stop();
  };

  window['loadDevicePps1.0.0'] = function() { start(); };
  window['unloadDevicePps1.0.0'] = function() { stop(); };

  start();

})();
