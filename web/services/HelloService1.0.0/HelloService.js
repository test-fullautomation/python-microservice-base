/**
 * GUI for the hello sample service (gRPC-native).
 *
 * Loaded by the Manager GUI when a Consul-registered service declares
 * Meta.gui = "HelloService1.0.0". Talks to the service through the bridge's
 * reflection-based call endpoint (MM.grpcClient), so it needs no generated
 * stubs and works against whichever instance the user selected --
 * MM.currentGuiService says which one that is.
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  function ctx() { return MM.currentGuiService || {}; }
  function el(id) { return document.getElementById(id); }

  function render() {
    var c = ctx();
    var target = el('helloGuiTarget');
    if (target) {
      target.textContent = (c.name || '?') + ' @ ' + (c.address || '?') + ':' + (c.port || '?');
    }
  }

  function show(kind, text) {
    var out = el('helloGuiResult');
    if (!out) return;
    out.className = 'alert alert-' + kind + ' py-2 small mb-0';
    out.textContent = text;
  }

  function greet() {
    var c = ctx();
    var name = ((el('helloGuiName') || {}).value || 'World').trim();
    show('info', 'Calling Greet…');
    MM.grpcClient.callMethod({
      consulName: c.name,
      consulUrl: c.consulUrl,
      grpcService: 'hello.v1.HelloService',
      method: 'Greet',
      argsJson: JSON.stringify({ name: name })
    }).then(function (data) {
      if (!data || data.ok === false) {
        show('danger', (data && (data.error || data.message)) || 'Call failed');
        return;
      }
      var result = data.result !== undefined ? data.result : (data.response !== undefined ? data.response : data);
      var message = result && typeof result === 'object' && 'message' in result ? result.message : JSON.stringify(result);
      show('success', message);
    }).catch(function (err) {
      show('danger', String((err && err.message) || err));
    });
  }

  var btn = el('helloGuiGreet');
  if (btn) btn.addEventListener('click', greet);
  var input = el('helloGuiName');
  if (input) {
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); greet(); }
    });
  }

  // Loader hooks (called on re-show when the panel is cached).
  window.loadHelloService = render;
  window.unloadHelloService = function () {};

  render();
})();
