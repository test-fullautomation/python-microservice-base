// flow-view: the "Diagram" view of a run group (flow-group). Every member's
// flow as a column, side by side, and a dashed arrow where one member waits
// for another. Runs in a sandboxed frame; the project view pushes the runner's
// data as the selection ({ members, links, live?, zoom?, motion? }), and a click on a node asks
// the host to show it in that member's file (ctx.reveal({ member, node })).
//
// `live` (the Runs view): { <member id>: position } -- see live.js. Only the
// marks move; when a member's node changes the view tells the host where
// each member is (ctx.reveal({ follow, nodes: [{ member, node, top, bottom }] })).
import { renderGroup } from './flow.js';
import { ensureStyle } from './style.js';
import { mark, extent, zoom, replay } from './live.js';

export function mount(el, ctx) {
  ensureStyle();
  let drawn = null;      // what is drawn: members and links, as text
  let followed = null;   // the members' nodes the host was last told about
  let memos = {};        // per member: the replay's memory

  function draw(data) {
    const members = data.members;
    const links = data.links || [];
    el.innerHTML =
      '<p class="fv-group-note">' + (links.length
        ? '<span class="fv-key"></span>' + links.length + ' meeting point' + (links.length === 1 ? '' : 's') +
          ': a step of one member sets a signal that a gate of another waits for (read from the flows).'
        : 'The members do not wait for each other: no gate waits for a signal another member sets.') +
      '</p><div class="fv-scroll">' + renderGroup(members, links) + '</div>';

    // The ends of every link stand out.
    links.forEach((l) => {
      [l.from, l.to].forEach((end) => {
        const g = el.querySelector('[data-member="' + CSS.escape(end.member) + '"] [data-node="' + CSS.escape(end.node) + '"]');
        if (g) g.classList.add('fv-sync-end');
      });
    });
    // Hovering a link lights its two ends.
    el.querySelectorAll('.fv-sync').forEach((g) => {
      const l = links[Number(g.getAttribute('data-link'))];
      const ends = [l.from, l.to].map((end) =>
        el.querySelector('[data-member="' + CSS.escape(end.member) + '"] [data-node="' + CSS.escape(end.node) + '"]'));
      g.addEventListener('mouseenter', () => ends.forEach((n) => n && n.classList.add('fv-lit')));
      g.addEventListener('mouseleave', () => ends.forEach((n) => n && n.classList.remove('fv-lit')));
    });
    el.querySelectorAll('[data-member] [data-node]').forEach((g) => {
      const member = g.closest('[data-member]').getAttribute('data-member');
      const go = () => ctx.reveal({ member, node: g.getAttribute('data-node') });
      g.addEventListener('click', go);
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      });
    });
  }

  function show(data) {
    const members = (data && data.members) || [];
    if (!members.length) {
      el.innerHTML = '<p class="fv-empty">No members to draw.</p>';
      drawn = null;
      return;
    }
    const key = JSON.stringify([members, data.links || []]);
    if (key !== drawn) {
      draw(data);
      drawn = key;
      followed = null;
      memos = {};
    }
    if ('live' in data) {
      const live = data.live || {};
      const nodes = [];
      el.querySelectorAll('[data-member]').forEach((col) => {
        const id = col.getAttribute('data-member');
        const now = mark(col, live[id] || null);
        replay(col, live[id] || null, memos[id] = memos[id] || {}, data.motion, now);
        if (now) nodes.push(Object.assign({ member: id, node: now.getAttribute('data-node') }, extent(now)));
      });
      const at = JSON.stringify(nodes.map((n) => [n.member, n.node]));
      const moved = nodes.length && at !== followed;
      if (moved) ctx.reveal({ follow: true, nodes });
      followed = at;
      zoom(el, data.zoom, moved ? Array.prototype.slice.call(el.querySelectorAll('[data-member] .fv-now')) : []);
    } else {
      zoom(el, data.zoom, []);
    }
  }

  show(ctx.selection());
  const off = ctx.onSelection(show);
  return {
    destroy() { off(); el.innerHTML = ''; }
  };
}
