// Auto-layout: longest-path layering (sources left → sinks right) with
// barycenter ordering inside each layer. Deliberately simple — good enough
// for testbench-sized graphs; positions are hand-tunable afterwards and
// persisted in the layout sidecar.
"use strict";

const LAYER_DX = 260;
const NODE_DY = 120;
const ORIGIN = { x: 60, y: 60 };

function autoLayout(graph) {
  const ids = graph.blocks.map((b) => b.id);
  const idSet = new Set(ids);
  const preds = new Map();
  const succs = new Map();
  for (const id of ids) { preds.set(id, []); succs.set(id, []); }
  for (const [from, to] of graph.wires) {
    const f = parseRef(from), t = parseRef(to);
    if (!f || !t || !idSet.has(f.block) || !idSet.has(t.block)) continue;
    if (f.block === t.block) continue;
    preds.get(t.block).push(f.block);
    succs.get(f.block).push(t.block);
  }

  // Longest-path layer via bounded relaxation (cycle-safe: caps at n rounds).
  const layer = new Map(ids.map((id) => [id, 0]));
  const n = ids.length;
  for (let round = 0; round < n; round++) {
    let changed = false;
    for (const id of ids) {
      for (const p of preds.get(id)) {
        const want = layer.get(p) + 1;
        if (want > layer.get(id) && want < n + 1) {
          layer.set(id, want);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }

  const layers = new Map();
  for (const id of ids) {
    const l = layer.get(id);
    if (!layers.has(l)) layers.set(l, []);
    layers.get(l).push(id);
  }
  const layerKeys = [...layers.keys()].sort((a, b) => a - b);

  // Initial order: as authored; then one barycenter pass left→right.
  const orderIndex = new Map();
  for (const key of layerKeys) {
    layers.get(key).forEach((id, i) => orderIndex.set(id, i));
  }
  for (const key of layerKeys.slice(1)) {
    const arr = layers.get(key);
    arr.sort((a, b) => bary(a) - bary(b));
    arr.forEach((id, i) => orderIndex.set(id, i));
  }
  function bary(id) {
    const ps = preds.get(id);
    if (!ps.length) return orderIndex.get(id);
    return ps.reduce((s, p) => s + orderIndex.get(p), 0) / ps.length;
  }

  const positions = {};
  for (const key of layerKeys) {
    layers.get(key).forEach((id, i) => {
      positions[id] = { x: ORIGIN.x + key * LAYER_DX, y: ORIGIN.y + i * NODE_DY };
    });
  }
  return positions;
}
