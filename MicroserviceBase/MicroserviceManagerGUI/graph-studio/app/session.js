// Session: what the studio showed when its window closed, so opening it
// again continues there — the graph and its file, the view, the selection
// and unsaved edits. Kept in localStorage ("gs-session"); DOM-free so the
// tests can load it. The editor saves it (saveSession) and brings it back
// at boot (restoreSession).
"use strict";

const SESSION_KEY = "gs-session";

/** The session record of the editor state. */
function makeSession(st) {
  return {
    version: 1,
    filePath: st.filePath || null,
    fileName: st.fileName || null,
    dirty: !!st.dirty,
    graph: serializeGraph(st.graph),
    positions: st.positions || {},
    view: st.view || { x: 0, y: 0, scale: 1 },
    selection: st.selection || null,
  };
}

/**
 * How to bring a session back, or null when there is none to use:
 *   "file"     — a saved file without edits: read it again (the disk may
 *                have moved on), keep the session's view and selection
 *   "snapshot" — unsaved edits, an example or a browser-mode graph: the
 *                session's own copy
 */
function restorePlan(s, electron) {
  if (!s || s.version !== 1 || typeof s.graph !== "string") return null;
  if (!parseGraph(s.graph).graph) return null;
  if (electron && s.filePath && !s.dirty) return "file";
  return "snapshot";
}

/** The session's layout in the sidecar's shape (for loadGraphText). */
function sessionLayoutText(s) {
  return JSON.stringify({ version: 1, positions: s.positions || {}, view: s.view || { x: 0, y: 0, scale: 1 } });
}

/** A saved selection that still points at something in the graph, or null. */
function validSelection(sel, graph) {
  if (!sel || !graph) return null;
  if (sel.kind === "block") return graph.blocks.some((b) => b.id === sel.id) ? sel : null;
  if (sel.kind === "wire") {
    return Number.isInteger(sel.index) && sel.index >= 0 && sel.index < graph.wires.length ? sel : null;
  }
  return null;
}

/** A view that can be applied (finite numbers, a sane zoom), or null. */
function validView(v) {
  if (!v || ![v.x, v.y, v.scale].every((n) => typeof n === "number" && isFinite(n))) return null;
  if (v.scale < 0.25 || v.scale > 2.5) return null;
  return { x: v.x, y: v.y, scale: v.scale };
}
