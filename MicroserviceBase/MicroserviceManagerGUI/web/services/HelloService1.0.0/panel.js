// Hello panel (framed): every call goes through window.endo.ctx.
// The frame is sandboxed without forms, so the form is never submitted:
// the button and Enter call Greet directly.
(function () {
  'use strict';
  var ctx = window.endo.ctx;
  var answer = document.getElementById('answer');
  var name = document.getElementById('name');
  var greetBtn = document.getElementById('greet');

  function show(el, text, bad) {
    el.textContent = text;
    el.className = el.className.replace(/\s*bad\b/, '') + (bad ? ' bad' : '');
  }

  function greet() {
    greetBtn.disabled = true;
    ctx.call('Greet', { name: name.value })
      .then(function (d) { show(answer, (d.result && d.result.message) || JSON.stringify(d.result)); },
            function (e) { show(answer, e.message, true); })
      .then(function () { greetBtn.disabled = false; });
  }

  greetBtn.addEventListener('click', greet);
  name.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); greet(); } });

  document.getElementById('ticks').addEventListener('click', function () {
    var list = document.getElementById('tickList');
    var state = document.getElementById('tickState');
    state.textContent = 'streaming…';
    list.innerHTML = '';
    ctx.call('Tick', { count: 5, interval_ms: 100 }).then(function (d) {
      (d.events || []).forEach(function (ev) {
        var li = document.createElement('li');
        li.textContent = ev.message || JSON.stringify(ev);
        list.appendChild(li);
      });
      state.textContent = (d.events || []).length + ' event(s)';
    }, function (e) { state.textContent = e.message; });
  });

  // Greet once so the panel opens with an answer; again after being hidden.
  greet();
  window.endo.on('resume', greet);
})();
