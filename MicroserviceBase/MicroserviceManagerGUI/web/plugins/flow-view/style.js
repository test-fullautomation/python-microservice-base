// flow-view: the diagram's styles. The view runs in a sandboxed frame of its
// own (frame-host.js), which cannot load a stylesheet, so they ship as text
// and style that document only. Light, like the content area of the shell;
// the accent follows the shell's theme (--accent). Neutrals and tints are
// --fv-* variables with the light colour as fallback, so a host can give the
// view a dark palette (the VS Code extension does); strong hues stay literal.
const STYLE = `
#endo-root { padding: 0.25rem 0; }
.fv-empty { color: var(--muted, #5A665F); font-size: 0.84rem; margin: 0; }
/* The frame takes the drawing's height: never a scrollbar of its own up and down. */
.fv-scroll { overflow-x: auto; overflow-y: hidden; }

.flow-view { display: block; max-width: 100%; height: auto; font-family: var(--font-sans, system-ui), system-ui, "Segoe UI", sans-serif; }

.flow-view .fv-lane { fill: var(--fv-lane, #f3f6f8); stroke: var(--fv-line, #dfe6ea); }
.flow-view .fv-lane-title { font: 600 11px Consolas, "Courier New", monospace; letter-spacing: 0.06em; fill: #1a9c83; }

.flow-view .fv-node rect,
.flow-view .fv-node polygon { fill: var(--fv-surface, #ffffff); stroke: var(--fv-border, #b8c4cc); stroke-width: 1.3; }
.flow-view .fv-node { cursor: pointer; outline: none; }
.flow-view .fv-node:hover rect,
.flow-view .fv-node:hover polygon,
.flow-view .fv-node:focus-visible rect,
.flow-view .fv-node:focus-visible polygon { stroke: var(--accent, #127A69); stroke-width: 2.2; }

.flow-view .fv-title { font-size: 13px; font-weight: 600; fill: var(--fv-text, #1a252f); text-anchor: middle; }
.flow-view .fv-sub { font-size: 11px; fill: var(--fv-text-soft, #6c7a86); text-anchor: middle; }

.flow-view .fv-gate polygon { fill: var(--fv-gate-bg, #effaf7); stroke: #1a9c83; stroke-width: 1.8; }
.flow-view .fv-sleep rect { stroke-dasharray: 4 3; }
.flow-view .fv-decision polygon { fill: var(--fv-decision-bg, #fff8e6); stroke: #c9a227; stroke-width: 1.6; }
.flow-view .fv-loop rect { fill: var(--fv-loop-bg, #f4effb); stroke: #7d5ba6; stroke-width: 1.8; }
.flow-view .fv-try rect { fill: var(--fv-try-bg, #eef2f5); stroke: var(--fv-slate, #5d6d7e); stroke-width: 1.8; }
.flow-view .fv-in-recovery rect,
.flow-view .fv-in-recovery polygon { fill: var(--fv-recovery-bg, #fff6e6); stroke: #c77c0e; }
.flow-view .fv-error rect,
.flow-view .fv-error polygon { stroke: #e74c3c; stroke-width: 2.6; }

.flow-view .fv-frame { fill: none; stroke-width: 1.3; stroke-dasharray: 6 4; }
.flow-view .fv-frame-loop { stroke: var(--fv-frame-loop, #b9a3d6); }
.flow-view .fv-frame-try { stroke: var(--fv-frame-try, #aab7c4); }
.flow-view .fv-flow rect { fill: var(--fv-flow-bg, #eef3fb); stroke: #4a6fa5; stroke-width: 1.8; }
.flow-view .fv-flow .fv-bar { stroke: #4a6fa5; stroke-width: 1.4; }
.flow-view .fv-frame-flow { stroke: var(--fv-frame-flow, #9fb4d6); }
.flow-view .fv-toggle { cursor: pointer; }
.flow-view .fv-toggle rect { fill: var(--fv-surface, #ffffff); stroke: #4a6fa5; stroke-width: 1.2; }
.flow-view .fv-toggle text { font: 700 14px system-ui, sans-serif; fill: #4a6fa5; text-anchor: middle; pointer-events: none; }
.flow-view .fv-toggle:hover rect, .flow-view .fv-toggle:focus-visible rect { fill: var(--fv-toggle-hover, #e3ecf8); stroke-width: 2; }
/* Editing (edit.js) */
.fv-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 8px; font: 13px system-ui, sans-serif; }
.fv-palette { display: flex; flex-wrap: wrap; gap: 5px; margin-right: 6px; }
.fv-chip { padding: 3px 10px; border: 1px solid var(--fv-border, #b8c4cc); border-radius: 14px; background: var(--fv-surface, #fff); cursor: grab; user-select: none; touch-action: none; }
.fv-chip:hover { border-color: #127A69; color: #127A69; }
.fv-chip-gate { border-color: #1a9c83; } .fv-chip-decision { border-color: #c9a227; }
.fv-chip-loop { border-color: #7d5ba6; } .fv-chip-flow { border-color: #4a6fa5; }
.fv-btn { font: 13px system-ui, sans-serif; padding: 3px 10px; border: 1px solid var(--fv-border, #b8c4cc); border-radius: 6px; background: var(--fv-surface, #fff); cursor: pointer; }
.fv-btn:hover:not([disabled]) { border-color: #127A69; }
.fv-btn[disabled] { opacity: .45; cursor: default; }
.fv-btn-primary { background: #127A69; border-color: #127A69; color: #fff; }
.fv-btn-danger { color: var(--fv-danger, #b3261e); border-color: var(--fv-danger-line, #e3b6b2); }
.fv-msg { color: var(--fv-slate, #5d6d7e); margin-left: 4px; }
.fv-msg-error { color: var(--fv-danger, #b3261e); font-weight: 600; }
.fv-panel { border: 1px solid var(--fv-line, #dfe6ea); border-radius: 8px; background: var(--fv-panel, #f8fafb); padding: 8px 10px; margin: 0 0 8px; font: 13px system-ui, sans-serif; }
.fv-fields { display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 6px 0; }
.fv-field { display: flex; flex-direction: column; gap: 2px; min-width: 150px; }
.fv-field span { color: var(--fv-slate, #5d6d7e); font-size: 12px; }
.fv-field input, .fv-field select, .fv-field textarea { font: 13px Consolas, monospace; padding: 3px 5px; border: 1px solid var(--fv-border, #b8c4cc); border-radius: 4px; }
.fv-field textarea { min-width: 260px; }
.fv-actions { display: flex; gap: 6px; }
.fv-muted { color: var(--fv-faint, #8a99a6); font-family: Consolas, monospace; }
.flow-view .fv-drop { cursor: copy; }
.flow-view .fv-drop circle { fill: var(--fv-surface, #ffffff); stroke: #127A69; stroke-width: 1.4; stroke-dasharray: 3 2; }
.flow-view .fv-drop text { font: 700 13px system-ui, sans-serif; fill: #127A69; text-anchor: middle; pointer-events: none; }
.fv-dragging .flow-view .fv-drop circle { fill: var(--fv-drop-bg, #e6f5f1); stroke-dasharray: none; }
.flow-view .fv-drop.fv-drop-hot circle { fill: #127A69; r: 12; }
.flow-view .fv-drop.fv-drop-hot text { fill: #ffffff; }
.fv-edit .flow-view .fv-node { cursor: grab; }
.flow-view .fv-selected rect, .flow-view .fv-selected polygon { stroke: #127A69 !important; stroke-width: 3 !important; }
.fv-ghost { position: fixed; z-index: 10; pointer-events: none; padding: 4px 10px; border-radius: 6px; background: #127A69; color: #fff; font: 600 12px system-ui, sans-serif; box-shadow: 0 4px 12px rgba(0,0,0,.2); }
.flow-view .fv-rec-zone { fill: var(--fv-reczone-bg, #fffaf0); stroke: var(--fv-reczone-line, #e8c690); stroke-dasharray: 4 4; }

.flow-view .fv-pill rect { fill: var(--fv-surface, #ffffff); stroke: var(--fv-text, #1a252f); stroke-width: 1.3; }

.flow-view .fv-edge { fill: none; stroke: var(--fv-faint, #8a99a6); stroke-width: 1.5; }
.flow-view .fv-edge-next { stroke: #7d5ba6; }
.flow-view .fv-edge-fail { stroke: #c77c0e; stroke-width: 1.7; }
.flow-view .fv-edge-cont { stroke: #c77c0e; stroke-width: 1.5; stroke-dasharray: 6 4; }

.flow-view .fv-label { font-size: 11px; fill: var(--fv-text-soft, #6c7a86); }
.flow-view .fv-label-next { fill: #7d5ba6; }
.flow-view .fv-label-fail,
.flow-view .fv-label-cont { fill: #c77c0e; }

/* Run groups: one column per member, dashed arrows where they meet. */
.fv-group-note { font-size: 0.84rem; color: var(--muted, #5A665F); margin: 0 0 0.5rem; }
.fv-key { display: inline-block; width: 28px; height: 0; border-top: 2px dashed #1a9c83; vertical-align: middle; margin-right: 0.45rem; }
.flow-group .fv-member-title { font: 700 15px var(--font-sans, system-ui), system-ui, sans-serif; fill: var(--fv-text, #1a252f); }
.flow-group .fv-member-sub { font: 11px Consolas, "Courier New", monospace; fill: var(--fv-text-soft, #6c7a86); }
.flow-group .fv-sync-edge { fill: none; stroke: #1a9c83; stroke-width: 2; stroke-dasharray: 7 5; }
.flow-group .fv-sync-label { font: 600 11px Consolas, "Courier New", monospace; fill: var(--fv-sync-text, #0f6e5c); text-anchor: middle;
  paint-order: stroke; stroke: var(--fv-surface, #ffffff); stroke-width: 4px; stroke-linejoin: round; }
.flow-group .fv-sync { cursor: default; }
.flow-group .fv-sync:hover .fv-sync-edge { stroke-width: 3; stroke-dasharray: none; }
.flow-group .fv-sync-end rect,
.flow-group .fv-sync-end polygon { stroke: #1a9c83; stroke-width: 2.2; }
.flow-group .fv-lit rect,
.flow-group .fv-lit polygon { fill: var(--fv-lit-bg, #e3f6f1); stroke-width: 3; }

/* A run's live position (live.js): the step running now, the loops and
   tries around it, a step that failed just now, and how often each ran. */
.flow-view .fv-on-path > rect,
.flow-view .fv-on-path > polygon { stroke: #2f7de1; stroke-width: 2.4; }
.flow-view .fv-now rect,
.flow-view .fv-now polygon { fill: var(--fv-now-bg, #e4f0ff); stroke: #2f7de1; stroke-width: 3.2; animation: fv-pulse 1.2s ease-in-out infinite; }
.flow-view .fv-now-recovery rect,
.flow-view .fv-now-recovery polygon { fill: var(--fv-now-recovery-bg, #fff0d9); stroke: #c77c0e; }
.flow-view .fv-just-failed rect,
.flow-view .fv-just-failed polygon { fill: var(--fv-failed-bg, #fdecea); stroke: #e74c3c; stroke-width: 3; }
.flow-view .fv-count { font: 600 10px Consolas, "Courier New", monospace; fill: var(--fv-count-pass, #1a7f4b); text-anchor: end; pointer-events: none; }
.flow-view .fv-bp { fill: transparent; cursor: pointer; }
.flow-view [data-node]:hover > .fv-bp { fill: var(--fv-bp-hint, rgba(229, 20, 0, 0.35)); }
.flow-view .fv-has-bp > .fv-bp { fill: #e51400; stroke: var(--fv-surface, #ffffff); stroke-width: 1.5; }
.flow-view .fv-paused > rect, .flow-view .fv-paused > polygon { stroke: #e5a400 !important; stroke-width: 3.5 !important; animation: none !important; }
.flow-view .fv-paused > rect, .flow-view .fv-paused > polygon { fill: var(--fv-paused-bg, #fff6d6); }
.flow-view .fv-count.fv-count-fail { fill: #c0392b; }
/* replay (live.js): the steps since the last push, in order. */
.flow-view .fv-trail rect,
.flow-view .fv-trail polygon { animation: fv-trail 0.8s ease-out; }
.flow-view .fv-hop rect,
.flow-view .fv-hop polygon { fill: var(--fv-now-bg, #e4f0ff); stroke: #2f7de1; stroke-width: 3.2; }
/* From the flash back to the node's own colours (no 100% keyframe). */
@keyframes fv-trail {
  0% { fill: var(--fv-flash-bg, #cfe3ff); stroke: #2f7de1; stroke-width: 3.2; }
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
