// sessions-demo: the page next to the navigator (same id). A real session
// manager would show the console here: state, devices, testflows, actions.
export function mount(el, ctx) {
  el.innerHTML = '<div class="sd-view"><h3>Session console (demo)</h3><p>Service: <code></code></p></div>';
  el.querySelector('code').textContent = ctx.service || '(none)';
  ctx.notify('info', 'sessions-demo console bound to ' + (ctx.service || '(none)') + ' (uses ' + (ctx.uses || []).join(', ') + ')');

  // Another service, named in binds.uses: "<consul>:<ProtoService>/<Method>".
  // A failure carries the gRPC code, the decoded details and the request id.
  ctx.call('catalog:catalog.v1.Catalog/List', { page: 1 }, { timeout: 3000, metadata: { origin: 'sessions-demo' } })
    .then(() => ctx.notify('info', 'sessions-demo catalog: ok'),
          (e) => ctx.notify('warning', 'sessions-demo catalog: ' + e.code + ' ' +
                            (e.details || []).map((d) => d['@type']).join(',') + ' ' + (e.requestId || '')));
  // A service it did not name is refused in the GUI, before any call.
  ctx.call('configuration-hub:config.v1.Hub/Get', {})
    .catch((e) => ctx.notify('info', 'sessions-demo hub: ' + e.code));
  return { destroy() { el.innerHTML = ''; } };
}
