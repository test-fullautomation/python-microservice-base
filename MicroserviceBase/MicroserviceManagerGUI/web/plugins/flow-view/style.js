// flow-view: the diagram's styles. The view runs in a sandboxed frame of its
// own (frame-host.js), which cannot load a stylesheet, so they ship as text
// and style that document only. Light, like the content area of the shell;
// the accent follows the shell's theme (--accent).
const STYLE = `
#endo-root { padding: 0.25rem 0; }
.fv-empty { color: var(--muted, #5A665F); font-size: 0.84rem; margin: 0; }
/* The frame takes the drawing's height: never a scrollbar of its own up and down. */
.fv-scroll { overflow-x: auto; overflow-y: hidden; }

.flow-view { display: block; max-width: 100%; height: auto; font-family: var(--font-sans, system-ui), system-ui, "Segoe UI", sans-serif; }

.flow-view .fv-lane { fill: #f3f6f8; stroke: #dfe6ea; }
.flow-view .fv-lane-title { font: 600 11px Consolas, "Courier New", monospace; letter-spacing: 0.06em; fill: #1a9c83; }

.flow-view .fv-node rect,
.flow-view .fv-node polygon { fill: #ffffff; stroke: #b8c4cc; stroke-width: 1.3; }
.flow-view .fv-node { cursor: pointer; outline: none; }
.flow-view .fv-node:hover rect,
.flow-view .fv-node:hover polygon,
.flow-view .fv-node:focus-visible rect,
.flow-view .fv-node:focus-visible polygon { stroke: var(--accent, #127A69); stroke-width: 2.2; }

.flow-view .fv-title { font-size: 13px; font-weight: 600; fill: #1a252f; text-anchor: middle; }
.flow-view .fv-sub { font-size: 11px; fill: #6c7a86; text-anchor: middle; }

.flow-view .fv-gate polygon { fill: #effaf7; stroke: #1a9c83; stroke-width: 1.8; }
.flow-view .fv-sleep rect { stroke-dasharray: 4 3; }
.flow-view .fv-decision polygon { fill: #fff8e6; stroke: #c9a227; stroke-width: 1.6; }
.flow-view .fv-loop rect { fill: #f4effb; stroke: #7d5ba6; stroke-width: 1.8; }
.flow-view .fv-try rect { fill: #eef2f5; stroke: #5d6d7e; stroke-width: 1.8; }
.flow-view .fv-in-recovery rect,
.flow-view .fv-in-recovery polygon { fill: #fff6e6; stroke: #c77c0e; }
.flow-view .fv-error rect,
.flow-view .fv-error polygon { stroke: #e74c3c; stroke-width: 2.6; }

.flow-view .fv-frame { fill: none; stroke-width: 1.3; stroke-dasharray: 6 4; }
.flow-view .fv-frame-loop { stroke: #b9a3d6; }
.flow-view .fv-frame-try { stroke: #aab7c4; }
.flow-view .fv-rec-zone { fill: #fffaf0; stroke: #e8c690; stroke-dasharray: 4 4; }

.flow-view .fv-pill rect { fill: #ffffff; stroke: #1a252f; stroke-width: 1.3; }

.flow-view .fv-edge { fill: none; stroke: #8a99a6; stroke-width: 1.5; }
.flow-view .fv-edge-next { stroke: #7d5ba6; }
.flow-view .fv-edge-fail { stroke: #c77c0e; stroke-width: 1.7; }
.flow-view .fv-edge-cont { stroke: #c77c0e; stroke-width: 1.5; stroke-dasharray: 6 4; }

.flow-view .fv-label { font-size: 11px; fill: #6c7a86; }
.flow-view .fv-label-next { fill: #7d5ba6; }
.flow-view .fv-label-fail,
.flow-view .fv-label-cont { fill: #c77c0e; }

/* Run groups: one column per member, dashed arrows where they meet. */
.fv-group-note { font-size: 0.84rem; color: var(--muted, #5A665F); margin: 0 0 0.5rem; }
.fv-key { display: inline-block; width: 28px; height: 0; border-top: 2px dashed #1a9c83; vertical-align: middle; margin-right: 0.45rem; }
.flow-group .fv-member-title { font: 700 15px var(--font-sans, system-ui), system-ui, sans-serif; fill: #1a252f; }
.flow-group .fv-member-sub { font: 11px Consolas, "Courier New", monospace; fill: #6c7a86; }
.flow-group .fv-sync-edge { fill: none; stroke: #1a9c83; stroke-width: 2; stroke-dasharray: 7 5; }
.flow-group .fv-sync-label { font: 600 11px Consolas, "Courier New", monospace; fill: #0f6e5c; text-anchor: middle;
  paint-order: stroke; stroke: #ffffff; stroke-width: 4px; stroke-linejoin: round; }
.flow-group .fv-sync { cursor: default; }
.flow-group .fv-sync:hover .fv-sync-edge { stroke-width: 3; stroke-dasharray: none; }
.flow-group .fv-sync-end rect,
.flow-group .fv-sync-end polygon { stroke: #1a9c83; stroke-width: 2.2; }
.flow-group .fv-lit rect,
.flow-group .fv-lit polygon { fill: #e3f6f1; stroke-width: 3; }

/* A run's live position (live.js): the step running now, the loops and
   tries around it, a step that failed just now, and how often each ran. */
.flow-view .fv-on-path > rect,
.flow-view .fv-on-path > polygon { stroke: #2f7de1; stroke-width: 2.4; }
.flow-view .fv-now rect,
.flow-view .fv-now polygon { fill: #e4f0ff; stroke: #2f7de1; stroke-width: 3.2; animation: fv-pulse 1.2s ease-in-out infinite; }
.flow-view .fv-now-recovery rect,
.flow-view .fv-now-recovery polygon { fill: #fff0d9; stroke: #c77c0e; }
.flow-view .fv-just-failed rect,
.flow-view .fv-just-failed polygon { fill: #fdecea; stroke: #e74c3c; stroke-width: 3; }
.flow-view .fv-count { font: 600 10px Consolas, "Courier New", monospace; fill: #1a7f4b; text-anchor: end; pointer-events: none; }
.flow-view .fv-count.fv-count-fail { fill: #c0392b; }
/* replay (live.js): the steps since the last push, in order. */
.flow-view .fv-trail rect,
.flow-view .fv-trail polygon { animation: fv-trail 0.8s ease-out; }
.flow-view .fv-hop rect,
.flow-view .fv-hop polygon { fill: #e4f0ff; stroke: #2f7de1; stroke-width: 3.2; }
/* From the flash back to the node's own colours (no 100% keyframe). */
@keyframes fv-trail {
  0% { fill: #cfe3ff; stroke: #2f7de1; stroke-width: 3.2; }
}
/* zoom 'natural' (live.js): the drawing at its own size, scrolling sideways. */
.fv-natural .flow-view { max-width: none; height: auto; }
@keyframes fv-pulse { 50% { stroke-opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) {
  .flow-view .fv-now rect, .flow-view .fv-now polygon { animation: none; }
}
`;

export function ensureStyle() {
  if (document.querySelector('style[data-endo-plugin="flow-view"]')) return;
  const s = document.createElement('style');
  s.setAttribute('data-endo-plugin', 'flow-view');
  s.textContent = STYLE;
  document.head.appendChild(s);
}
