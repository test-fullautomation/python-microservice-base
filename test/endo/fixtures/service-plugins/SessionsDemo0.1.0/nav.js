// sessions-demo: the navigator a session manager would deliver. Static rows,
// no calls: the GUI probe runs without a bridge. It says which service its
// ctx is bound to, which is what the probe checks.
const SESSIONS = [
  { id: 'S-2026-10-19-001', state: 'ACTIVE' },
  { id: 'S-2026-10-18-007', state: 'CLOSED' }
];

export function mount(el, ctx) {
  el.innerHTML = '<div class="sd-nav"><p class="sd-bound">Bound to <strong></strong></p><ul></ul></div>';
  el.querySelector('.sd-bound strong').textContent = ctx.service || '(none)';
  const ul = el.querySelector('ul');
  SESSIONS.forEach((s) => {
    const li = document.createElement('li');
    li.textContent = s.id + ' · ' + s.state;
    ul.appendChild(li);
  });
  ctx.notify('info', 'sessions-demo navigator bound to ' + (ctx.service || '(none)'));
  return { destroy() { el.innerHTML = ''; } };
}
