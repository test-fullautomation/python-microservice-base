// robot-grid: the grid's styles. The view runs in a sandboxed frame of its
// own (frame-host.js), which cannot load a stylesheet, so they ship as text
// and style that document only. Namespaced "rg-" (P2). Neutrals and tints are
// --rg-* variables with the light colour as fallback, so a host can give the
// view a dark palette (the VS Code extension does); strong hues stay literal.
const STYLE = `
#endo-root { padding: 0.25rem 0 0.5rem; position: relative; }
.rg { font-size: 13px; color: var(--text, #14201A); }
.rg-note { font-size: 0.82rem; color: var(--muted, #5A665F); margin: 0 0 0.6rem; }
.rg-empty { color: var(--muted, #5A665F); font-size: 0.84rem; padding: 0.3rem 0; }
.rg-imports-bad { margin: 0 0 0.8rem; padding: 0.45rem 0.8rem 0.45rem 1.6rem; font-size: 0.8rem;
  background: var(--rg-warn-bg, #fff6e6); border-left: 3px solid #c77c0e; border-radius: 4px; }
.rg-section { margin-bottom: 1rem; }
.rg-section-title { font: 600 11px Consolas, "Courier New", monospace; letter-spacing: 0.08em; text-transform: uppercase;
  color: #1a9c83; margin: 0 0 0.4rem; cursor: pointer; }
.rg-item { margin-bottom: 0.7rem; }
.rg-item-name { font-weight: 700; padding: 0.15rem 0.1rem; cursor: pointer; }
.rg-item-name:hover { color: var(--accent, #127A69); }
.rg-scroll { overflow-x: auto; }
.rg-table { border-collapse: collapse; width: max-content; min-width: 100%; }
.rg-row { cursor: pointer; }
.rg-row:hover td { background: color-mix(in srgb, var(--accent, #127A69) 7%, var(--rg-surface, #ffffff)); }
.rg-table td { border: 1px solid var(--rg-cell-line, #e1e7eb); padding: 0.22rem 0.5rem; vertical-align: top; background: var(--rg-surface, #ffffff); max-width: 22rem; }
.rg-line { color: var(--rg-faint, #9aa7b1); font: 11px Consolas, "Courier New", monospace; text-align: right; width: 2.6rem;
  background: var(--rg-gutter, #f6f8f9) !important; }
.rg-kwcell { min-width: 14rem; white-space: nowrap; }
.rg-kw { font-weight: 600; color: var(--rg-text-strong, #1a252f); border-bottom: 1px dotted transparent; }
.rg-kw[data-kw]:hover { border-bottom-color: var(--accent, #127A69); color: var(--accent, #127A69); }
.rg-kw.rg-unknown { color: var(--rg-bad, #a0392b); border-bottom: 1px dashed #e74c3c; }
.rg-nested { font-weight: 600; }
.rg-assign { font-family: Consolas, "Courier New", monospace; font-size: 12px; color: #7d5ba6; margin-right: 0.4rem; }
.rg-assign::after { content: " ="; color: var(--rg-faint, #9aa7b1); }
.rg-label { font-family: Consolas, "Courier New", monospace; font-size: 12px; color: var(--rg-slate, #5d6d7e); margin-right: 0.4rem; }
.rg-control .rg-label { color: #7d5ba6; font-weight: 700; }
.rg-setting .rg-label { color: #1a9c83; }
.rg-cell { min-width: 5rem; }
.rg-p { display: block; font: 10px Consolas, "Courier New", monospace; color: var(--rg-faint, #9aa7b1); line-height: 1.1; margin-bottom: 1px; }
.rg-p.rg-extra { color: #c0392b; }
.rg-cell-extra { background: var(--rg-error-bg, #fdf0ee) !important; }
.rg-v { font-family: Consolas, "Courier New", monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
.rg-var { color: #7d5ba6; }
.rg-missing { color: var(--rg-bad, #a0392b); font-size: 0.78rem; font-style: italic; white-space: nowrap; background: var(--rg-error-bg, #fdf0ee) !important; }
.rg-comment { color: var(--rg-text-soft, #6c7a86); font-style: italic; font-size: 0.8rem; }
.rg-error { color: var(--rg-bad, #a0392b); font-size: 0.78rem; }
.rg-has-error td { background: var(--rg-error-bg, #fdf0ee); }
.rg-card { position: absolute; z-index: 5; background: var(--rg-surface, #ffffff); border: 1px solid var(--rg-border, #cfd8de); border-radius: 8px;
  box-shadow: 0 6px 18px rgba(20, 32, 26, 0.16); padding: 0.55rem 0.7rem; font-size: 12.5px; pointer-events: none; }
.rg-card-head { display: flex; justify-content: space-between; gap: 0.6rem; align-items: baseline; margin-bottom: 0.3rem; }
.rg-card-name { font-weight: 700; }
.rg-card-owner { color: var(--rg-text-soft, #6c7a86); font-size: 11px; white-space: nowrap; }
.rg-card-args { margin: 0 0 0.35rem; padding-left: 1.1rem; }
.rg-card-args code { font-size: 12px; color: var(--rg-text-strong, #1a252f); }
.rg-card-type { color: #1a9c83; font-size: 11px; }
.rg-card-default { color: var(--rg-text-soft, #6c7a86); font-size: 11px; }
.rg-card-req { color: #c77c0e; font-size: 11px; }
.rg-card-none { color: var(--rg-text-soft, #6c7a86); margin-bottom: 0.35rem; }
.rg-card-doc { white-space: pre-wrap; color: var(--rg-doc-text, #34495e); border-top: 1px solid var(--rg-line-soft, #eef2f4); padding-top: 0.35rem; max-height: 14rem; overflow: hidden; }

/* Editing */
.rg-edit-hint { color: #1a9c83; }
.rg-bad { color: var(--rg-bad, #a0392b); }
.rg-btn { font: inherit; font-size: 12px; border: 1px solid var(--rg-border, #cfd8de); background: var(--rg-surface, #ffffff); color: var(--rg-text-strong, #1a252f); border-radius: 5px;
  padding: 0.18rem 0.6rem; cursor: pointer; }
.rg-btn:hover { border-color: var(--accent, #127A69); color: var(--accent, #127A69); }
.rg-btn:disabled { opacity: 0.5; cursor: default; }
.rg-btn-primary { background: var(--accent, #127A69); border-color: var(--accent, #127A69); color: #ffffff; }
.rg-btn-primary:hover { color: #ffffff; filter: brightness(1.08); }
.rg-btn-danger { color: var(--rg-bad, #a0392b); }
.rg-btn-danger:hover { border-color: #c0392b; color: #c0392b; }
.rg-undo { margin-left: 0.4rem; }
.rg-row-editable .rg-kwcell { cursor: text; }
.rg-row-editable:hover .rg-kwcell .rg-kw::after { content: " \\270E"; color: var(--rg-faint, #9aa7b1); font-weight: 400; }
.rg-add td { border: none !important; background: transparent !important; padding-top: 0.3rem; }
.rg-add-btn { color: #1a9c83; border-style: dashed; }
.rg-flash td { animation: rg-flash 1.6s ease-out; }
@keyframes rg-flash { from { background: var(--rg-flash, #d7f3ea); } to { background: var(--rg-surface, #ffffff); } }
.rg-editor-row > td { background: var(--rg-editor-bg, #f7fbfa) !important; border-color: var(--rg-editor-line, #b7dfd4) !important; }
.rg-editor { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.3rem 0.1rem; white-space: normal; }
.rg-ed-top { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; }
.rg-in { font: 12px Consolas, "Courier New", monospace; border: 1px solid var(--rg-border, #cfd8de); border-radius: 4px; padding: 0.25rem 0.4rem;
  background: var(--rg-surface, #ffffff); color: var(--rg-text-strong, #1a252f); min-width: 0; }
.rg-in:focus { outline: none; border-color: var(--accent, #127A69); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent, #127A69) 20%, transparent); }
.rg-in-assign { width: 9rem; color: #7d5ba6; }
.rg-in-kw { width: 22rem; font-weight: 700; font-family: inherit; font-size: 13px; }
.rg-ed-eq { color: var(--rg-faint, #9aa7b1); }
.rg-ed-sig { font: 11px Consolas, "Courier New", monospace; color: var(--rg-text-soft, #6c7a86); }
.rg-ed-params { display: flex; flex-direction: column; gap: 0.4rem; }
.rg-ed-group { display: flex; flex-wrap: wrap; gap: 0.4rem 0.6rem; align-items: flex-end; }
.rg-ed-glabel { font: 11px Consolas, "Courier New", monospace; color: var(--rg-text-soft, #6c7a86); align-self: center; margin-right: 0.2rem; }
.rg-ed-unknown { color: #c77c0e; font-family: inherit; }
.rg-ed-param { display: inline-flex; flex-direction: column; gap: 2px; }
.rg-ed-pair, .rg-ed-group > .rg-ed-param:has(.rg-x) { flex-direction: row; align-items: center; gap: 2px; }
.rg-ed-param .rg-in { width: 11rem; }
.rg-ed-pname { font: 10px Consolas, "Courier New", monospace; color: var(--rg-text-soft, #6c7a86); }
.rg-ed-pname i { color: #1a9c83; font-style: normal; }
.rg-ed-pname.rg-req::after { content: " *"; color: #c77c0e; }
.rg-x { border: none; background: none; color: var(--rg-faint, #9aa7b1); cursor: pointer; font-size: 14px; line-height: 1; padding: 0 0.2rem; }
.rg-x:hover { color: #c0392b; }
.rg-ed-doc { font-size: 0.8rem; color: var(--rg-slate, #5d6d7e); }
.rg-ed-doc:empty { display: none; }
.rg-ed-actions { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
.rg-ed-msg { font-size: 0.8rem; color: var(--rg-text-soft, #6c7a86); }
.rg-mini { font-size: 11px; padding: 0.1rem 0.45rem; }
.rg-armed { background: var(--rg-armed-bg, #fdecea); border-color: #e74c3c; color: var(--rg-bad, #a0392b); }
.rg-ed-sep { width: 1px; align-self: stretch; background: var(--rg-line, #dfe6ea); margin: 0 0.15rem; }
.rg-add-group { display: inline-flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
.rg-add-or { color: var(--rg-faint, #9aa7b1); font-size: 11px; margin: 0 0.1rem; }
.rg-add-block { font: 600 11px Consolas, "Courier New", monospace; color: #7d5ba6; padding: 0.1rem 0.45rem; }
.rg-item-name { display: flex; align-items: center; gap: 0.6rem; }
.rg-item-title { cursor: pointer; }
.rg-item-title:hover { color: var(--accent, #127A69); }
.rg-item-tools { display: inline-flex; gap: 0.3rem; opacity: 0.45; transition: opacity 0.15s; }
.rg-item:hover .rg-item-tools, .rg-item-tools:focus-within { opacity: 1; }
.rg-item-tools .rg-btn { font-size: 11px; font-weight: 400; padding: 0.05rem 0.45rem; }
.rg-toolbar { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-top: 0.8rem; padding-top: 0.6rem;
  border-top: 1px dashed var(--rg-line, #dfe6ea); }
.rg-toolbar-label { font: 600 11px Consolas, "Courier New", monospace; letter-spacing: 0.08em; text-transform: uppercase; color: #1a9c83; }
.rg-editor-panel { margin-top: 0.5rem; padding: 0.6rem 0.7rem; border: 1px solid var(--rg-editor-line, #b7dfd4); border-radius: 8px; background: var(--rg-editor-bg, #f7fbfa); }
.rg-ed-block, .rg-ed-fixture { font-weight: 700; color: #7d5ba6; }
.rg-ed-fixture { color: #1a9c83; }
.rg-ed-wide { flex: 1 1 22rem; }
.rg-ed-wide .rg-in { width: 100%; }
.rg-ed-row-in { flex-direction: row; align-items: center; gap: 2px; }
.rg-doc { width: 100%; font-family: inherit; font-size: 13px; resize: vertical; }
select.rg-in { font-family: inherit; font-size: 12px; }
.rg-drop { position: absolute; z-index: 6; background: var(--rg-surface, #ffffff); border: 1px solid var(--rg-border, #cfd8de); border-radius: 8px;
  box-shadow: 0 8px 22px rgba(20, 32, 26, 0.18); max-height: 18rem; overflow-y: auto; padding: 0.2rem; }
.rg-drop-item { display: grid; grid-template-columns: 1fr auto; gap: 0 0.6rem; padding: 0.3rem 0.5rem; border-radius: 5px; cursor: pointer; }
.rg-drop-item.rg-active, .rg-drop-item:hover { background: color-mix(in srgb, var(--accent, #127A69) 10%, var(--rg-surface, #ffffff)); }
.rg-drop-name { font-weight: 600; }
.rg-drop-owner { color: var(--rg-text-soft, #6c7a86); font-size: 11px; text-align: right; }
.rg-drop-sig { grid-column: 1 / -1; font: 11px Consolas, "Courier New", monospace; color: #1a9c83; }
.rg-drop-doc { grid-column: 1 / -1; font-size: 11px; color: var(--rg-text-soft, #6c7a86); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
`;

export function ensureStyle() {
  if (document.querySelector('style[data-endo-plugin="robot-grid"]')) return;
  const s = document.createElement('style');
  s.setAttribute('data-endo-plugin', 'robot-grid');
  s.textContent = STYLE;
  document.head.appendChild(s);
}
