// config-demo: the navigator a configuration hub would deliver. Static rows,
// no calls (the GUI probe runs without a bridge).
export function mount(el, ctx) {
  el.innerHTML = '<div class="cd-nav"><p>Bound to <strong></strong></p><ul><li>testbench-qmm · v4</li><li>testbench-qmm (infrastructure) · v2</li></ul></div>';
  el.querySelector('strong').textContent = ctx.service || '(none)';
  ctx.notify('info', 'config-demo bound to ' + (ctx.service || '(none)'));
  return { destroy() { el.innerHTML = ''; } };
}
