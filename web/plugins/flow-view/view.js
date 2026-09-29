// flow-view: the "Diagram" file view of flow-graph files. Runs in a sandboxed
// frame; the host view pushes the runner's data for the file as the
// selection ({ flow, error?, live?, zoom?, motion? }), and a click on a node asks the host to
// show that node in the file (ctx.reveal({ node })).
//
// `live` (the Runs view, during and after a run): where the run is -- see
// live.js. The same flow pushed again with a new `live` only moves the
// marks; when the node changes the view tells the host where it is
// (ctx.reveal({ follow, node, top, bottom })), so a tall diagram can keep
// it in sight.
import { render } from './flow.js';
import { ensureStyle } from './style.js';
import { mark, extent, zoom, replay } from './live.js';

export function mount(el, ctx) {
  ensureStyle();
  let drawn = null;      // what is drawn: the flow and error, as text
  let followed = null;   // the node the host was last told about
  let memo = {};         // the replay's memory: the last step shown

  function show(data) {
    const flow = data && data.flow;
    if (!flow) {
      el.innerHTML = '<p class="fv-empty">No flow to draw.</p>';
      drawn = null;
      return;
    }
    const key = JSON.stringify([flow, data.error || null]);
    if (key !== drawn) {
      el.innerHTML = '<div class="fv-scroll">' + render(flow, { error: data.error || null }) + '</div>';
      el.querySelectorAll('[data-node]').forEach((g) => {
        const go = () => ctx.reveal({ node: g.getAttribute('data-node') });
        g.addEventListener('click', go);
        g.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
        });
      });
      drawn = key;
      followed = null;
      memo = {};
    }
    if ('live' in data) {
      const now = mark(el, data.live);
      replay(el, data.live, memo, data.motion, now);
      const id = now ? now.getAttribute('data-node') : null;
      const moved = now && id !== followed;
      if (moved) ctx.reveal(Object.assign({ follow: true, node: id }, extent(now)));
      followed = id;
      zoom(el, data.zoom, moved ? [now] : []);
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
