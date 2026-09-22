// Signal Graph Studio — editor/viewer main module.
// Phase 0: load graph.json → auto-laid-out diagram, live reload (Electron).
// Phase 1: palette from catalog, type-checked wiring, param/observe editing,
//          validation panel, save graph.json + <name>.layout.json sidecar.
"use strict";

/* ============================== state ============================== */

const state = {
  graph: { blocks: [], wires: [], observe: [] },
  positions: {},                 // blockId -> {x,y}
  view: { x: 0, y: 0, scale: 1 },
  filePath: null,                // Electron only; browser mode keeps a display name
  fileName: null,
  dirty: false,
  selection: null,               // {kind:"block", id} | {kind:"wire", index}
  catalog: DEFAULT_CATALOG,
  catMap: catalogByType(DEFAULT_CATALOG),
  // Phase B: live-integration state (endpoints + cached lookups)
  live: {
    consulHost: "127.0.0.1", consulPort: 8500,
    discoveryHost: "127.0.0.1", discoveryPort: 50210,
    protoDir: "",              // optional: -import-path for grpcurl if no reflection
    python: "python",          // interpreter for Run (needs grpcio + pydantic-settings)
    signalsRoot: "",           // dir with signal_graph/ + signal_discovery/ for Run ("" = main's guess)
    consulServices: [],        // [{name, tags}]
    signals: [],               // [{name, kind, unit, host, port}]
    collisions: [],            // discovery-reported name collisions
  },
  // Phase D: run + monitor
  paths: { toolRoot: "", referenceSignals: "", referenceProtos: "", runner: "", signalsRoot: "", hasReferenceSignals: false },
  run: { active: false, ready: false, stopping: false, mode: null, python: "python" },
  drawerH: null,               // log/chart drawer height in px when the user resized it
  monitor: {
    active: false,
    values: new Map(),         // signal name -> {value, timestamp, rx}
    history: new Map(),        // signal name -> [[t_ms, value], ...] (ring, ≤ HISTORY_MS)
    colors: new Map(),         // signal name -> hex (fixed order by entity, never cycled)
    hidden: new Set(),         // signals unticked in the chart panel
    paused: false,
    windowS: 30,
    rowH: 48,                  // minimum strip height (px) — below this the chart scrolls
    pulseNodes: new Map(),     // blockId -> expiry (ms)
    pulseWires: new Map(),     // "from->to" -> expiry (ms)
    updates: 0,
  },
};

// Categorical palette — dark slots validated against the drawer surface
// #0e1628 (dataviz validate_palette.js: all checks pass, 6 adjacent slots).
// Assigned in fixed order by entity (signal name); a 7th+ signal gets the
// neutral ink — its identity is carried by the row label, never by hue.
const SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"];
const SERIES_NEUTRAL = "#94a3b8";
const HISTORY_MS = 120_000;

// Examples use the rev-2 schema: service + device_services + "signals"
// wiring dialect (+ setpoints). The parser also accepts the older
// deck-sketch "wires" pairs dialect.
const EXAMPLES = {
  signal_in: {
    service: { name: "signal-in", grpc_port: 50200, rate_hz: 20.0, flow_mode: "push" },
    device_services: { nidaq_dev0: "testbench-device-ai-mock" },
    blocks: [
      { id: "adc_ch0", type: "AdcBlock", params: { device: "nidaq_dev0", channel: 0, unit: "V" } },
      { id: "conv_ch0", type: "LinearScaleBlock", params: { gain: 10.0, offset: -5.0, out_unit: "degC" } },
      { id: "rec0", type: "RecordSignalBlock", params: { signal_name: "bench.dut.temp.degC" } },
    ],
    signals: [
      { from: "adc_ch0.out", to: "conv_ch0.in" },
      { from: "conv_ch0.out", to: "rec0.in" },
    ],
    observe: [{ name: "bench.dut.temp.degC", port: "conv_ch0.out" }],
    setpoints: [],
  },
  signal_proc: {
    service: { name: "signal-proc-demo", grpc_port: 50202, rate_hz: 10.0, flow_mode: "push" },
    device_services: {},
    blocks: [
      { id: "sub_temp", type: "SubscriberSourceBlock", params: { signal_name: "bench.dut.temp.degC", unit: "degC" } },
      { id: "overtemp", type: "ThresholdBlock", params: { threshold: 40.0, unit: "bool" } },
      { id: "rec", type: "RecordSignalBlock", params: { signal_name: "bench.dut.overtemp.flag", batch_size: 20 } },
    ],
    signals: [
      { from: "sub_temp.out", to: "overtemp.in" },
      { from: "overtemp.out", to: "rec.in" },
    ],
    observe: [
      { name: "bench.dut.temp.mirror.degC", port: "sub_temp.out" },
      { name: "bench.dut.overtemp.flag", port: "overtemp.out" },
    ],
    setpoints: [],
  },
};

/* ============================== geometry ============================== */

const NODE_W = 180;
const PORT_Y0 = 40;
const PORT_DY = 20;

function nodeSpec(block) {
  return blockSpec(block, state.catMap, state.graph);
}

function nodeGeom(block) {
  const spec = nodeSpec(block);
  const rows = Math.max(spec.inputs.length, spec.outputs.length, 1);
  const hasParams = Object.keys(block.params).length > 0;
  const h = PORT_Y0 + rows * PORT_DY + (hasParams ? 16 : 2);
  return { spec, w: NODE_W, h };
}

function portXY(block, dir, portName) {
  const pos = state.positions[block.id] || { x: 0, y: 0 };
  const { spec } = nodeGeom(block);
  const list = dir === "in" ? spec.inputs : spec.outputs;
  const i = Math.max(0, list.findIndex((p) => p.name === portName));
  return {
    x: pos.x + (dir === "in" ? 0 : NODE_W),
    y: pos.y + PORT_Y0 + i * PORT_DY,
  };
}

function blockById(id) {
  return state.graph.blocks.find((b) => b.id === id) || null;
}

/* ============================== svg render ============================== */

const svg = document.getElementById("canvas");
const SVGNS = "http://www.w3.org/2000/svg";
let worldG = null;
let tempWireEl = null;

function el(name, attrs, parent) {
  const e = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

function wirePath(x1, y1, x2, y2) {
  const dx = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function render() {
  svg.innerHTML = "";
  worldG = el("g", { id: "world" }, svg);
  applyView();

  const wiresG = el("g", {}, worldG);
  const nodesG = el("g", {}, worldG);

  // wires
  state.graph.wires.forEach(([from, to], index) => {
    const f = parseRef(from), t = parseRef(to);
    const fb = f && blockById(f.block), tb = t && blockById(t.block);
    if (!fb || !tb) return; // dangling wires are reported in the issues panel
    const a = portXY(fb, "out", f.port);
    const b = portXY(tb, "in", t.port);
    const spec = nodeSpec(fb);
    const color = typeColor(portType(spec, "out", f.port) || "unknown");
    const d = wirePath(a.x, a.y, b.x, b.y);
    const selected = state.selection && state.selection.kind === "wire" && state.selection.index === index;
    const pulsing = state.monitor.active && (state.monitor.pulseWires.get(`${from}->${to}`) || 0) > Date.now();
    el("path", { d, class: "wire" + (selected ? " selected" : "") + (pulsing ? " pulse" : ""), stroke: color }, wiresG);
    const hit = el("path", { d, class: "wire-hit" }, wiresG);
    hit.addEventListener("mousedown", (ev) => {
      ev.stopPropagation();
      select({ kind: "wire", index });
    });
  });

  // nodes
  for (const block of state.graph.blocks) {
    if (!state.positions[block.id]) state.positions[block.id] = { x: 80, y: 80 };
    renderNode(block, nodesG);
  }

  renderIssues();
  renderInspector();
  renderFileLabel();
}

function renderNode(block, parent) {
  const pos = state.positions[block.id];
  const { spec, w, h } = nodeGeom(block);
  const style = FAMILY_STYLE[spec.family] || FAMILY_STYLE.unknown;
  const selected = state.selection && state.selection.kind === "block" && state.selection.id === block.id;

  const pulsing = state.monitor.active && (state.monitor.pulseNodes.get(block.id) || 0) > Date.now();
  const g = el("g", { class: "node" + (selected ? " selected" : "") + (pulsing ? " pulse" : ""), transform: `translate(${pos.x},${pos.y})` }, parent);
  el("rect", { class: "body", width: w, height: h, rx: 9, fill: style.fill, stroke: style.stroke, "stroke-width": 1.6 }, g);
  const title = el("text", { class: "title", x: 10, y: 17 }, g);
  title.textContent = block.id;
  const sub = el("text", { class: "subtitle", x: 10, y: 31 }, g);
  sub.textContent = block.type + (spec.known ? "" : "  (unknown)");

  // live value of a foreign signal feeding a SubscriberSourceBlock
  if (state.monitor.active && block.type === "SubscriberSourceBlock" && block.params.signal_name) {
    const live = state.monitor.values.get(block.params.signal_name);
    const badge = el("text", { class: "sub-badge", x: 10, y: 52 }, g);
    badge.textContent = live ? `⇠ ${fmtVal(live.value)}  (${fmtAge(live.rx)})` : "⇠ waiting…";
  }

  // params summary
  const paramKeys = Object.keys(block.params);
  if (paramKeys.length) {
    const summary = paramKeys.map((k) => `${k}=${JSON.stringify(block.params[k])}`).join("  ");
    const pt = el("text", { class: "params", x: 10, y: h - 6 }, g);
    pt.textContent = summary.length > 30 ? summary.slice(0, 29) + "…" : summary;
  }

  // ports
  spec.inputs.forEach((p, i) => {
    const cy = PORT_Y0 + i * PORT_DY;
    const c = el("circle", { class: "port", cx: 0, cy, r: 5.5, fill: "#0b1120", stroke: typeColor(p.type) }, g);
    c.dataset.block = block.id; c.dataset.port = p.name; c.dataset.dir = "in";
    const lbl = el("text", { class: "portlabel", x: 10, y: cy + 3.5 }, g);
    lbl.textContent = p.name;
  });
  spec.outputs.forEach((p, i) => {
    const cy = PORT_Y0 + i * PORT_DY;
    const c = el("circle", { class: "port", cx: w, cy, r: 5.5, fill: "#0b1120", stroke: typeColor(p.type) }, g);
    c.dataset.block = block.id; c.dataset.port = p.name; c.dataset.dir = "out";
    const lbl = el("text", { class: "portlabel", x: w - 10, y: cy + 3.5, "text-anchor": "end" }, g);
    lbl.textContent = p.name;
    c.addEventListener("mousedown", (ev) => {
      ev.stopPropagation();
      startWireDrag(block.id, p.name, p.type);
    });

    // observe tag
    const obs = state.graph.observe.find((o) => o.port === makeRef(block.id, p.name));
    if (obs) {
      el("path", { class: "obs-line", d: `M ${w + 6} ${cy} L ${w + 26} ${cy - 14}` }, g);
      const tag = el("text", { class: "obs-tag", x: w + 29, y: cy - 17 }, g);
      tag.textContent = `◉ ${obs.name}`;
      const live = state.monitor.active ? state.monitor.values.get(obs.name) : null;
      if (live) {
        const val = el("text", { class: "live-val", x: w + 29, y: cy - 4 }, g);
        val.textContent = `= ${fmtVal(live.value)}`;
        const age = el("text", { class: "live-age", x: w + 29, y: cy + 8 }, g);
        age.textContent = fmtAge(live.rx) + " ago";
        // sparkline beside the text — last window, own scale
        const hist = state.monitor.history.get(obs.name) || [];
        if (hist.length >= 2) {
          const SW = 90, SH = 16, x0 = w + 29, y0 = cy + 12;
          const t1 = Date.now(), t0 = t1 - state.monitor.windowS * 1000;
          const pts = hist.filter((p) => p[0] >= t0);
          if (pts.length >= 2) {
            let lo = Infinity, hi = -Infinity;
            for (const [, v] of pts) { if (v < lo) lo = v; if (v > hi) hi = v; }
            if (hi === lo) { hi += 0.5; lo -= 0.5; }
            const d = pts.map(([t, v]) =>
              `${(x0 + ((t - t0) / (t1 - t0)) * SW).toFixed(1)},${(y0 + SH - ((v - lo) / (hi - lo)) * SH).toFixed(1)}`,
            ).join(" ");
            el("polyline", { class: "spark", points: d, stroke: seriesColor(obs.name) }, g);
          }
        }
      } else if (state.monitor.active) {
        const wait = el("text", { class: "live-age", x: w + 29, y: cy - 4 }, g);
        wait.textContent = "waiting…";
      }
    }
  });

  // drag / select on body
  g.addEventListener("mousedown", (ev) => {
    if (ev.target.classList.contains("port")) return;
    ev.stopPropagation();
    select({ kind: "block", id: block.id });
    const world = screenToWorld(ev);
    drag = { kind: "node", id: block.id, dx: world.x - pos.x, dy: world.y - pos.y };
  });
}

function applyView() {
  if (worldG) worldG.setAttribute("transform", `translate(${state.view.x},${state.view.y}) scale(${state.view.scale})`);
}

function screenToWorld(ev) {
  const r = svg.getBoundingClientRect();
  return {
    x: (ev.clientX - r.left - state.view.x) / state.view.scale,
    y: (ev.clientY - r.top - state.view.y) / state.view.scale,
  };
}

/* ============================== interactions ============================== */

let drag = null; // {kind:"node"|"pan"|"wire", ...}

svg.addEventListener("mousedown", (ev) => {
  select(null);
  drag = { kind: "pan", sx: ev.clientX, sy: ev.clientY, ox: state.view.x, oy: state.view.y };
  svg.classList.add("panning");
});

document.addEventListener("mousemove", (ev) => {
  if (!drag) return;
  if (drag.kind === "node") {
    const world = screenToWorld(ev);
    state.positions[drag.id] = { x: Math.round(world.x - drag.dx), y: Math.round(world.y - drag.dy) };
    drag.moved = true;
    render();
  } else if (drag.kind === "pan") {
    state.view.x = drag.ox + (ev.clientX - drag.sx);
    state.view.y = drag.oy + (ev.clientY - drag.sy);
    applyView();
  } else if (drag.kind === "wire") {
    const world = screenToWorld(ev);
    const a = portXY(blockById(drag.from.block), "out", drag.from.port);
    tempWireEl.setAttribute("d", wirePath(a.x, a.y, world.x, world.y));
  }
});

document.addEventListener("mouseup", (ev) => {
  if (drag && drag.kind === "wire") {
    const t = ev.target;
    if (t && t.classList && t.classList.contains("port") && t.dataset.dir === "in") {
      tryAddWire(makeRef(drag.from.block, drag.from.port), makeRef(t.dataset.block, t.dataset.port));
    }
    if (tempWireEl) { tempWireEl.remove(); tempWireEl = null; }
  }
  if (drag && drag.kind === "node" && drag.moved) markDirty();
  svg.classList.remove("panning");
  drag = null;
});

svg.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  const r = svg.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  const factor = Math.exp(-ev.deltaY * 0.0012);
  const ns = Math.min(2.5, Math.max(0.25, state.view.scale * factor));
  const k = ns / state.view.scale;
  state.view.x = mx - k * (mx - state.view.x);
  state.view.y = my - k * (my - state.view.y);
  state.view.scale = ns;
  applyView();
}, { passive: false });

document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Delete" && ev.key !== "Backspace") return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  deleteSelection();
});

function startWireDrag(blockId, portName, portTypeName) {
  drag = { kind: "wire", from: { block: blockId, port: portName, type: portTypeName } };
  tempWireEl = el("path", { class: "temp-wire", d: "" }, worldG);
}

function tryAddWire(fromRef, toRef) {
  const f = parseRef(fromRef), t = parseRef(toRef);
  if (f.block === t.block) return toast("self-wire not allowed", true);
  if (state.graph.wires.some(([a, b]) => a === fromRef && b === toRef)) return toast("wire already exists", true);
  if (state.graph.wires.some(([, b]) => b === toRef)) {
    return toast(`input '${toRef}' already wired (inputs are latches — max one incoming wire)`, true);
  }
  const fSpec = nodeSpec(blockById(f.block));
  const tSpec = nodeSpec(blockById(t.block));
  const fType = portType(fSpec, "out", f.port);
  const tType = portType(tSpec, "in", t.port);
  if (fType && tType && fType !== "unknown" && tType !== "unknown" && fType !== tType) {
    return toast(`type mismatch: ${fromRef} is ${fType}, ${toRef} expects ${tType}`, true);
  }
  state.graph.wires.push([fromRef, toRef]);
  markDirty();
  const cyc = cycleBlocks(state.graph);
  if (cyc.length) toast("wire added — note: this creates a cycle (see issues panel)", false);
  render();
}

function select(sel) {
  state.selection = sel;
  render();
}

function deleteSelection() {
  const sel = state.selection;
  if (!sel) return;
  if (sel.kind === "wire") {
    state.graph.wires.splice(sel.index, 1);
  } else if (sel.kind === "block") {
    state.graph.blocks = state.graph.blocks.filter((b) => b.id !== sel.id);
    state.graph.wires = state.graph.wires.filter(([a, b]) => {
      const pa = parseRef(a), pb = parseRef(b);
      return pa.block !== sel.id && pb.block !== sel.id;
    });
    state.graph.observe = state.graph.observe.filter((o) => parseRef(o.port).block !== sel.id);
    delete state.positions[sel.id];
    syncSetpoints();
  }
  state.selection = null;
  markDirty();
  render();
}

/* ============================== palette ============================== */

function renderPalette() {
  const pal = document.getElementById("palette");
  pal.innerHTML = "";
  for (const family of ["source", "function", "sink"]) {
    const h = document.createElement("h3");
    h.textContent = family + " blocks";
    pal.appendChild(h);
    for (const b of state.catalog.blocks.filter((x) => x.family === family)) {
      const item = document.createElement("div");
      item.className = "pal-item";
      item.title = b.doc || "";
      const sw = FAMILY_STYLE[family];
      item.innerHTML = `<span class="fam" style="background:${sw.stroke}"></span><b>${b.type}</b>` +
        (b.origin === "proposed" ? `<span class="origin">proposed</span>` : "") +
        `<span class="doc">${(b.doc || "").split(".")[0]}.</span>`;
      item.addEventListener("click", () => addBlock(b));
      pal.appendChild(item);
    }
  }
}

function freshId(type) {
  const base = type.replace(/Block$/, "").replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
  let n = 1;
  while (blockById(`${base}${n}`)) n++;
  return `${base}${n}`;
}

function addBlock(catEntry) {
  const id = freshId(catEntry.type);
  const params = {};
  for (const p of catEntry.params || []) {
    if (!p.required) continue;
    if (p.type === "device_ref") {
      params[p.name] = Object.keys(state.graph.device_services || {})[0] || "";
    } else if (p.type === "enum") {
      params[p.name] = (p.choices || [])[0] || "";
    } else if (p.type === "list") {
      params[p.name] = [];
    } else if (p.type === "object") {
      params[p.name] = {};
    } else {
      params[p.name] = p.type === "string" ? "" : p.type === "bool" ? false : 0;
    }
  }
  state.graph.blocks.push({ id, type: catEntry.type, params });
  if (catEntry.type === "SetpointBlock") syncSetpoints();
  // place at current view centre
  const r = svg.getBoundingClientRect();
  state.positions[id] = {
    x: Math.round((r.width / 2 - state.view.x) / state.view.scale - NODE_W / 2),
    y: Math.round((r.height / 2 - state.view.y) / state.view.scale - 40),
  };
  state.selection = { kind: "block", id };
  markDirty();
  render();
}

/* ============================== inspector ============================== */

// ─── Phase A: service / device-mapping / setpoints panels ─────────────

function syncSetpoints() {
  // The setpoints section is tool-managed: one entry per SetpointBlock
  // signal_name; extra fields of kept entries are preserved.
  const wanted = new Map(); // name -> existing entry (or null)
  for (const b of state.graph.blocks) {
    if (b.type === "SetpointBlock" && b.params.signal_name) {
      wanted.set(b.params.signal_name, null);
    }
  }
  for (const entry of state.graph.setpoints || []) {
    if (wanted.has(entry.name)) wanted.set(entry.name, entry);
  }
  state.graph.setpoints = [...wanted.entries()].map(
    ([name, existing]) => existing || { name },
  );
}

function renderConfigPanels(ins) {
  const svc = state.graph.service || {};
  const devs = state.graph.device_services || {};

  const html = [];
  html.push(`<h3>Service (graph.json → service)</h3>`);
  html.push(`<label>name</label><input type="text" id="svc-name" value="${svc.name ?? ""}" placeholder="signal-in">`);
  html.push(`<label>grpc_port</label><input type="text" id="svc-port" value="${svc.grpc_port ?? ""}" placeholder="50200">`);
  html.push(`<label>rate_hz</label><input type="text" id="svc-rate" value="${svc.rate_hz ?? ""}" placeholder="20.0">`);
  html.push(`<label>flow_mode</label><select id="svc-flow">
      <option value="push"${svc.flow_mode === "push" ? " selected" : ""}>push</option>
      <option value="pull"${svc.flow_mode === "pull" ? " selected" : ""}>pull</option>
    </select>`);

  html.push(`<h3>Device services (logical → Consul name)</h3>`);
  for (const [logical, consul] of Object.entries(devs)) {
    html.push(`<div class="obs-row" data-dev="${logical}">
        <input type="text" value="${logical}" disabled style="width:40%">
        <input type="text" class="dev-consul" data-dev="${logical}" value="${consul ?? ""}" placeholder="consul service name" list="dl-consul">
        <button class="dev-del" data-dev="${logical}" title="remove">✕</button>
      </div>`);
  }
  html.push(`<div class="obs-row">
      <input type="text" id="dev-new-logical" placeholder="logical (e.g. nidaq_dev0)" style="width:40%">
      <input type="text" id="dev-new-consul" placeholder="consul service name" list="dl-consul">
      <button id="dev-add">+</button>
    </div>`);
  html.push(`<div class="hint">Device params on Adc/Dac blocks become dropdowns fed from this table.</div>`);

  const lv = state.live;
  html.push(`<h3>Live (Phase B${isElectron ? "" : " — needs Electron"})</h3>`);
  html.push(`<div class="obs-row">
      <input type="text" id="lv-consul" value="${lv.consulHost}:${lv.consulPort}" title="Consul host:port" style="width:46%">
      <button id="lv-fetch-consul"${isElectron ? "" : " disabled"}>⟳ Consul</button>
    </div>`);
  html.push(`<div class="obs-row">
      <input type="text" id="lv-disc" value="${lv.discoveryHost}:${lv.discoveryPort}" title="signal-discovery host:port" style="width:46%">
      <button id="lv-fetch-signals"${isElectron ? "" : " disabled"}>⟳ Signals</button>
    </div>`);
  html.push(`<label>proto dir (grpcurl fallback if no reflection)</label>
    <input type="text" id="lv-proto" value="${lv.protoDir}" placeholder="D:\\...\\taf_repo_proposal\\protos">`);
  html.push(`<button id="lv-check"${isElectron ? "" : " disabled"} style="margin-top:8px; width:100%">Check my names vs live catalog</button>`);
  html.push(`<label>python for ▶ Run (needs grpcio + pydantic-settings)</label>
    <input type="text" id="lv-python" value="${lv.python || "python"}" placeholder="python  or  D:\\...\\.venv\\Scripts\\python.exe">`);
  html.push(`<label>signals root for ▶ Run (dir with signal_graph/, signal_discovery/)</label>
    <input type="text" id="lv-signals-root" value="${lv.signalsRoot || ""}" placeholder="${(state.paths.signalsRoot || "D:\\...\\taf_repo_proposal\\services\\signals").replace(/\\/g, "\\\\")}">
    <div class="hint">empty = auto (${state.paths.signalsRoot ? "found: " + state.paths.signalsRoot : "nothing found — set it"})</div>`);
  html.push(`<div class="hint">cached: ${lv.consulServices.length} consul services · ${lv.signals.length} live signals${lv.collisions.length ? ` · <b style="color:var(--bad)">${lv.collisions.length} collision(s)</b>` : ""}</div>`);

  const sp = state.graph.setpoints || [];
  html.push(`<h3>Setpoints (tool-managed)</h3>`);
  html.push(sp.length
    ? `<div class="hint">${sp.map((e) => e.name).join("<br>")}</div>`
    : `<div class="hint">none — add a SetpointBlock and its signal_name appears here</div>`);

  html.push(`<div class="hint" style="margin-top:14px">· drag output → input to wire · click palette to add
      · Delete removes selection · <b>Generate service…</b> writes graph.json + Nomad job</div>`);
  ins.innerHTML = html.join("");

  const bindSvc = (id, key, parse) => {
    ins.querySelector(id).addEventListener("change", (ev) => {
      if (!state.graph.service) state.graph.service = {};
      const raw = ev.target.value.trim();
      if (raw === "") delete state.graph.service[key];
      else {
        const v = parse ? parse(raw) : raw;
        if (v === undefined) return toast(`invalid value for ${key}`, true);
        state.graph.service[key] = v;
      }
      markDirty();
      render();
    });
  };
  bindSvc("#svc-name", "name");
  bindSvc("#svc-port", "grpc_port", (r) => { const n = parseInt(r, 10); return Number.isNaN(n) ? undefined : n; });
  bindSvc("#svc-rate", "rate_hz", (r) => { const n = parseFloat(r); return Number.isNaN(n) ? undefined : n; });
  bindSvc("#svc-flow", "flow_mode");

  ins.querySelectorAll(".dev-consul").forEach((inp) => {
    inp.addEventListener("change", () => {
      state.graph.device_services[inp.dataset.dev] = inp.value.trim();
      markDirty();
      render();
    });
  });
  ins.querySelectorAll(".dev-del").forEach((btn) => {
    btn.addEventListener("click", () => {
      delete state.graph.device_services[btn.dataset.dev];
      markDirty();
      render();
    });
  });
  ins.querySelector("#dev-add").addEventListener("click", () => {
    const logical = ins.querySelector("#dev-new-logical").value.trim();
    const consul = ins.querySelector("#dev-new-consul").value.trim();
    if (!logical) return toast("logical device name must not be empty", true);
    if (logical in state.graph.device_services) return toast(`'${logical}' already mapped`, true);
    state.graph.device_services[logical] = consul;
    markDirty();
    render();
  });

  // Phase B handlers
  const bindEndpoint = (id, hostKey, portKey) => {
    ins.querySelector(id).addEventListener("change", (ev) => {
      const [h, p] = ev.target.value.split(":");
      if (h) state.live[hostKey] = h.trim();
      const n = parseInt(p, 10);
      if (!Number.isNaN(n)) state.live[portKey] = n;
      saveLive();
    });
  };
  bindEndpoint("#lv-consul", "consulHost", "consulPort");
  bindEndpoint("#lv-disc", "discoveryHost", "discoveryPort");
  ins.querySelector("#lv-proto").addEventListener("change", (ev) => {
    state.live.protoDir = ev.target.value.trim();
    saveLive();
  });
  ins.querySelector("#lv-python").addEventListener("change", (ev) => {
    state.live.python = ev.target.value.trim() || "python";
    saveLive();
  });
  ins.querySelector("#lv-signals-root").addEventListener("change", (ev) => {
    state.live.signalsRoot = ev.target.value.trim();
    saveLive();
  });
  ins.querySelector("#lv-fetch-consul").addEventListener("click", fetchConsulServices);
  ins.querySelector("#lv-fetch-signals").addEventListener("click", () => fetchDiscoverySignals(false));
  ins.querySelector("#lv-check").addEventListener("click", checkLiveNames);
}

function renderInspector() {
  const ins = document.getElementById("inspector");
  const sel = state.selection;
  if (!sel) {
    renderConfigPanels(ins);
    return;
  }
  ins.innerHTML = "";

  if (sel.kind === "wire") {
    const [from, to] = state.graph.wires[sel.index] || ["?", "?"];
    ins.innerHTML = `<h3>Wire</h3><div class="type-line">${from} → ${to}</div>`;
    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "Delete wire";
    del.addEventListener("click", deleteSelection);
    ins.appendChild(del);
    return;
  }

  const block = blockById(sel.id);
  if (!block) return;
  const spec = nodeSpec(block);

  ins.innerHTML = `<h3>Block</h3><div class="type-line">${block.type}</div><div class="doc">${spec.doc || ""}</div>`;

  // id
  const idLabel = document.createElement("label");
  idLabel.textContent = "id";
  ins.appendChild(idLabel);
  const idInput = document.createElement("input");
  idInput.type = "text";
  idInput.value = block.id;
  idInput.addEventListener("change", () => {
    const nid = idInput.value.trim();
    if (!nid || (nid !== block.id && blockById(nid))) {
      idInput.classList.add("invalid");
      return toast(nid ? `id '${nid}' already exists` : "id must not be empty", true);
    }
    renameBlock(block.id, nid);
  });
  ins.appendChild(idInput);

  // params
  const psHead = document.createElement("h3");
  psHead.textContent = "params";
  ins.appendChild(psHead);
  const declared = new Set((spec.params || []).map((p) => p.name));
  const rows = [...(spec.params || [])];
  for (const k of Object.keys(block.params)) {
    if (!declared.has(k)) rows.push({ name: k, type: "string", undeclared: true });
  }
  if (!rows.length) {
    const d = document.createElement("div");
    d.className = "hint";
    d.textContent = "no params";
    ins.appendChild(d);
  }
  for (const ps of rows) {
    const lab = document.createElement("label");
    lab.textContent = ps.name + (ps.required ? " *" : "") + (ps.undeclared ? " (undeclared)" : "");
    ins.appendChild(lab);
    let inp;
    if (ps.type === "signal_ref") {
      // Phase B: live-signal picker (datalist from discovery + refresh)
      const row = document.createElement("div");
      row.className = "obs-row";
      inp = document.createElement("input");
      inp.type = "text";
      inp.setAttribute("list", "dl-signals");
      inp.placeholder = "signal name (⟳ loads live catalog)";
      inp.value = ps.name in block.params ? String(block.params[ps.name]) : "";
      inp.addEventListener("change", () => {
        const raw = inp.value.trim();
        if (raw === "") delete block.params[ps.name];
        else block.params[ps.name] = raw;
        markDirty();
        render();
      });
      const btn = document.createElement("button");
      btn.textContent = "⟳";
      btn.title = "load live signals from discovery";
      btn.disabled = !isElectron;
      btn.addEventListener("click", () => fetchDiscoverySignals(false));
      row.appendChild(inp);
      row.appendChild(btn);
      ins.appendChild(row);
      continue;
    }
    if (ps.type === "device_ref") {
      // dropdown fed from the device_services mapping (Phase A)
      inp = document.createElement("select");
      const current = block.params[ps.name];
      const keys = Object.keys(state.graph.device_services || {});
      if (current !== undefined && !keys.includes(current)) keys.unshift(current);
      inp.innerHTML = `<option value="">— pick a device —</option>` + keys.map((k) => {
        const unmapped = !(k in (state.graph.device_services || {}));
        return `<option value="${k}"${k === current ? " selected" : ""}>${k}${unmapped ? " (unmapped!)" : ""}</option>`;
      }).join("");
      inp.addEventListener("change", () => {
        if (inp.value === "") delete block.params[ps.name];
        else block.params[ps.name] = inp.value;
        markDirty();
        render();
      });
    } else if (ps.type === "list" || ps.type === "object") {
      // JSON text for structured params (e.g. an allowlist of {service, min, max});
      // stored parsed, so graph.json carries real lists/objects, not strings
      inp = document.createElement("textarea");
      inp.className = "json";
      inp.rows = 4;
      inp.spellcheck = false;
      inp.placeholder = ps.type === "list" ? '[ {"service": "…"}, … ]' : "{ … }";
      inp.value = ps.name in block.params ? JSON.stringify(block.params[ps.name], null, 1) : "";
      if (ps.allowed_from === undefined && ps.name in block.params) {
        const v = block.params[ps.name];
        if (ps.type === "list" ? !Array.isArray(v) : (v === null || typeof v !== "object" || Array.isArray(v))) inp.classList.add("invalid");
      }
      inp.addEventListener("change", () => {
        const raw = inp.value.trim();
        if (raw === "") { delete block.params[ps.name]; markDirty(); render(); return; }
        let v;
        try { v = JSON.parse(raw); } catch (e) { inp.classList.add("invalid"); return toast(`'${ps.name}': not valid JSON — ${e.message}`, true); }
        const okShape = ps.type === "list" ? Array.isArray(v) : (v !== null && typeof v === "object" && !Array.isArray(v));
        if (!okShape) { inp.classList.add("invalid"); return toast(`'${ps.name}' must be a JSON ${ps.type}`, true); }
        block.params[ps.name] = v;
        markDirty();
        render();
      });
      ins.appendChild(inp);
      const h = document.createElement("div");
      h.className = "hint";
      const used = (spec.params || []).filter((q) => q.allowed_from && q.allowed_from.param === ps.name);
      h.textContent = used.length
        ? `JSON ${ps.type}. Entries here are the allowed values for: ${used.map((q) => `${q.name}${q.allowed_from.field ? " (via ." + q.allowed_from.field + ")" : ""}`).join(", ")}.`
        : `JSON ${ps.type}.`;
      ins.appendChild(h);
      continue;
    } else if (ps.type === "enum") {
      // dropdown from the catalog's choices; a stale value is kept visible but flagged
      inp = document.createElement("select");
      const current = block.params[ps.name];
      const choices = [...(ps.choices || [])];
      const stale = current !== undefined && !choices.includes(current);
      if (stale) choices.unshift(current);
      inp.innerHTML = (ps.required ? "" : `<option value="">— unset —</option>`) + choices.map((c) =>
        `<option value="${c}"${c === current ? " selected" : ""}>${c}${stale && c === current ? " (not a valid choice!)" : ""}</option>`,
      ).join("");
      if (stale) inp.classList.add("invalid");
      inp.addEventListener("change", () => {
        if (inp.value === "") delete block.params[ps.name];
        else block.params[ps.name] = inp.value;
        markDirty();
        render();
      });
    } else {
      inp = document.createElement("input");
      inp.type = "text";
      inp.value = ps.name in block.params ? String(block.params[ps.name]) : "";
      inp.addEventListener("change", () => {
        const raw = inp.value.trim();
        if (raw === "") { delete block.params[ps.name]; syncIfSetpoint(); markDirty(); render(); return; }
        let v = raw;
        if (ps.type === "int") { v = parseInt(raw, 10); if (Number.isNaN(v)) { inp.classList.add("invalid"); return toast(`'${ps.name}' must be an int`, true); } }
        else if (ps.type === "float") { v = parseFloat(raw); if (Number.isNaN(v)) { inp.classList.add("invalid"); return toast(`'${ps.name}' must be a number`, true); } }
        else if (ps.type === "bool") { if (raw !== "true" && raw !== "false") { inp.classList.add("invalid"); return toast(`'${ps.name}' must be true or false`, true); } v = raw === "true"; }
        block.params[ps.name] = v;
        syncIfSetpoint();
        markDirty();
        render();
      });
    }
    const syncIfSetpoint = () => {
      if (block.type === "SetpointBlock" && ps.name === "signal_name") syncSetpoints();
    };
    ins.appendChild(inp);
  }

  // observe
  if (spec.outputs.length) {
    const oHead = document.createElement("h3");
    oHead.textContent = "observe (published signals)";
    ins.appendChild(oHead);
    for (const out of spec.outputs) {
      const ref = makeRef(block.id, out.name);
      const existing = state.graph.observe.find((o) => o.port === ref);
      const row = document.createElement("div");
      row.className = "obs-row";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !!existing;
      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.placeholder = `${out.name} → signal name`;
      nameInput.value = existing ? existing.name : "";
      nameInput.disabled = !existing;
      cb.addEventListener("change", () => {
        if (cb.checked) {
          state.graph.observe.push({ port: ref, name: nameInput.value || `${block.id}_${out.name}` });
        } else {
          state.graph.observe = state.graph.observe.filter((o) => o.port !== ref);
        }
        markDirty();
        render();
      });
      nameInput.addEventListener("change", () => {
        const o = state.graph.observe.find((x) => x.port === ref);
        if (o) { o.name = nameInput.value.trim(); markDirty(); render(); }
      });
      row.appendChild(cb);
      row.appendChild(nameInput);
      ins.appendChild(row);
    }
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = "Only observed outputs are visible to the signal gateway; un-tapped wires stay internal.";
    ins.appendChild(hint);
  }

  // live write: a SetpointBlock's value can be pushed into the RUNNING service
  if (block.type === "SetpointBlock") {
    const sHead = document.createElement("h3");
    sHead.textContent = "set signal (live)";
    ins.appendChild(sHead);
    const row = document.createElement("div");
    row.className = "obs-row";
    const val = document.createElement("input");
    val.type = "text";
    val.placeholder = "value (float)";
    const last = state.monitor.values.get(block.params.signal_name);
    if (last && typeof last.value === "number") val.value = String(last.value);
    const btn = document.createElement("button");
    btn.textContent = "Set";
    btn.className = "primary";
    const port = (state.graph.service || {}).grpc_port;
    const ready = isElectron && !!block.params.signal_name && !!port;
    btn.disabled = !ready;
    btn.title = ready
      ? `SetSignal ${block.params.signal_name} on 127.0.0.1:${port}`
      : "needs Electron, a signal_name and service.grpc_port (and the service running)";
    const fire = () => setSignalLive(block.params.signal_name, val.value);
    btn.addEventListener("click", fire);
    val.addEventListener("keydown", (ev) => { if (ev.key === "Enter") fire(); });
    row.appendChild(val);
    row.appendChild(btn);
    ins.appendChild(row);
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = "Writes through the service's own SetSignal RPC — the same path a test's Set Signal keyword uses. Watch the wired blocks react in Monitor.";
    ins.appendChild(hint);
  }

  const del = document.createElement("button");
  del.className = "danger";
  del.textContent = "Delete block";
  del.addEventListener("click", deleteSelection);
  ins.appendChild(del);
}

function renameBlock(oldId, newId) {
  const block = blockById(oldId);
  block.id = newId;
  state.graph.wires = state.graph.wires.map(([a, b]) => [
    remapRef(a, oldId, newId), remapRef(b, oldId, newId),
  ]);
  state.graph.observe.forEach((o) => { o.port = remapRef(o.port, oldId, newId); });
  state.positions[newId] = state.positions[oldId];
  delete state.positions[oldId];
  state.selection = { kind: "block", id: newId };
  markDirty();
  render();
}

function remapRef(ref, oldId, newId) {
  const r = parseRef(ref);
  return r.block === oldId ? makeRef(newId, r.port) : ref;
}

/* ============================== issues panel ============================== */

function renderIssues() {
  const box = document.getElementById("issues");
  const issues = validateGraph(state.graph, state.catMap);
  if (!issues.length) {
    box.innerHTML = `<div class="ok">✓ graph valid — ${state.graph.blocks.length} blocks, ${state.graph.wires.length} wires, ${state.graph.observe.length} observed signals</div>`;
    return;
  }
  box.innerHTML = "";
  for (const iss of issues) {
    const d = document.createElement("div");
    d.className = `issue ${iss.level}`;
    d.innerHTML = `<span class="lv">${iss.level}</span>${iss.msg}`;
    if (iss.blockId) d.addEventListener("click", () => select({ kind: "block", id: iss.blockId }));
    box.appendChild(d);
  }
}

/* ============================== file handling ============================== */

const isElectron = typeof window.bridge !== "undefined";

/* ---- Phase B: live Consul / discovery integration ---- */

function loadLive() {
  try {
    const saved = JSON.parse(localStorage.getItem("gs-live") || "{}");
    Object.assign(state.live, saved);
  } catch (_e) { /* fresh profile / blocked storage — defaults are fine */ }
}

function saveLive() {
  try {
    const { consulHost, consulPort, discoveryHost, discoveryPort, protoDir, python, signalsRoot,
            consulServices, signals } = state.live;
    localStorage.setItem("gs-live", JSON.stringify(
      { consulHost, consulPort, discoveryHost, discoveryPort, protoDir, python, signalsRoot,
        consulServices, signals },
    ));
  } catch (_e) { /* best-effort */ }
}

function ensureDatalists() {
  for (const id of ["dl-consul", "dl-signals"]) {
    if (!document.getElementById(id)) {
      const dl = document.createElement("datalist");
      dl.id = id;
      document.body.appendChild(dl);
    }
  }
  refreshDatalists();
}

function refreshDatalists() {
  const consul = document.getElementById("dl-consul");
  if (consul) {
    consul.innerHTML = state.live.consulServices
      .map((s) => `<option value="${s.name}">`).join("");
  }
  const sigs = document.getElementById("dl-signals");
  if (sigs) {
    sigs.innerHTML = state.live.signals
      .map((s) => `<option value="${s.name}">${s.unit || ""} @ ${s.host}:${s.port}</option>`)
      .join("");
  }
}

async function fetchConsulServices() {
  if (!isElectron) return toast("live Consul lookup needs the Electron shell", true);
  const res = await window.bridge.fetchConsulServices({
    host: state.live.consulHost, port: state.live.consulPort,
  });
  if (res.error) return toast(res.error, true);
  state.live.consulServices = res.services;
  saveLive();
  refreshDatalists();
  toast(`Consul: ${res.services.length} services loaded into the device dropdown`);
}

async function fetchDiscoverySignals(silent) {
  if (!isElectron) { if (!silent) toast("live signal lookup needs the Electron shell", true); return false; }
  const res = await window.bridge.fetchDiscoverySignals({
    host: state.live.discoveryHost, port: state.live.discoveryPort,
    protoDir: state.live.protoDir || undefined,
  });
  if (res.error) { if (!silent) toast(res.error, true); return false; }
  state.live.signals = res.signals;
  state.live.collisions = res.collisions || [];
  saveLive();
  refreshDatalists();
  if (!silent) {
    toast(`discovery: ${res.signals.length} live signals` +
          (state.live.collisions.length ? ` — ${state.live.collisions.length} collision(s)!` : ""));
  }
  return true;
}

async function checkLiveNames() {
  const ok = await fetchDiscoverySignals(true);
  if (!ok) return toast("could not reach signal-discovery — check the Live panel endpoints", true);
  const liveByName = new Map(state.live.signals.map((s) => [s.name, s]));
  const clashes = [];
  for (const obs of state.graph.observe) {
    const owner = liveByName.get(obs.name);
    if (owner) clashes.push(`  ${obs.name}  — already owned by ${owner.host}:${owner.port}`);
  }
  const reported = state.live.collisions.map((c) => `  ${c.name}  — ${c.reason}`);
  if (!clashes.length && !reported.length) {
    return toast("no conflicts: none of this graph's names exist in the live catalog");
  }
  alert(
    (clashes.length ? `⚠ This graph's observe names ALREADY EXIST live\n(deploying would trigger discovery's collision exclusion):\n\n${clashes.join("\n")}\n\n` : "") +
    (reported.length ? `Discovery is currently reporting these collisions:\n\n${reported.join("\n")}` : ""),
  );
}

/* ---- Phase D: run a local cluster + live monitoring ---- */

const PULSE_MS = 600;

function logLine(text, cls) {
  const body = document.getElementById("logdrawer-body");
  const drawer = document.getElementById("logdrawer");
  const span = document.createElement("span");
  span.className = cls || "";
  span.textContent = text + "\n";
  body.appendChild(span);
  while (body.childNodes.length > 400) body.removeChild(body.firstChild);
  body.scrollTop = body.scrollHeight;
  if (drawer.classList.contains("collapsed") && cls === "err") drawer.classList.remove("collapsed");
}

function setMonStatus(text, cls) {
  const pill = document.getElementById("mon-status");
  pill.textContent = text;
  pill.className = "pill" + (cls ? " " + cls : "");
}

function monitorTargets() {
  // Own service: everything this graph observes, served on its own port.
  const svc = state.graph.service || {};
  const targets = new Map(); // "host:port" -> {host, port, names:Set}
  const add = (host, port, name) => {
    const key = `${host}:${port}`;
    if (!targets.has(key)) targets.set(key, { host, port, names: new Set() });
    targets.get(key).names.add(name);
  };
  if (svc.grpc_port) {
    for (const obs of state.graph.observe) add("127.0.0.1", svc.grpc_port, obs.name);
  }
  // Foreign inputs: SubscriberSourceBlocks → owner resolved from the live catalog.
  const liveByName = new Map(state.live.signals.map((s) => [s.name, s]));
  for (const b of state.graph.blocks) {
    if (b.type !== "SubscriberSourceBlock" || !b.params.signal_name) continue;
    const owner = liveByName.get(b.params.signal_name);
    if (owner) add(owner.host, owner.port, b.params.signal_name);
  }
  return [...targets.values()].map((t) => ({ host: t.host, port: t.port, names: [...t.names] }));
}

async function startMonitor() {
  if (!isElectron) return toast("monitoring needs the Electron shell (grpcurl streaming)", true);
  if (state.graph.blocks.some((b) => b.type === "SubscriberSourceBlock") && !state.live.signals.length) {
    await fetchDiscoverySignals(true); // resolve foreign owners, best-effort
  }
  const targets = monitorTargets();
  if (!targets.length) return toast("nothing to monitor: set service.grpc_port and observe at least one port", true);
  const res = await window.bridge.monitorStart({
    targets, protoDir: state.live.protoDir || state.paths.referenceProtos,
  });
  state.monitor.active = true;
  state.monitor.updates = 0;
  state.monitor.history.clear();
  state.monitor.colors.clear();
  state.monitor.paused = false;
  document.getElementById("chart-pause").textContent = "pause";
  document.getElementById("btn-monitor").classList.add("on");
  setMonStatus(`subscribing ${targets.reduce((n, t) => n + t.names.length, 0)} signals`, "on");
  logLine(`[monitor] subscribed: ${res.started.join(", ") || "(already active)"}`, "mon");
  render();
}

async function stopMonitor(silent) {
  if (!state.monitor.active) return;
  if (isElectron) await window.bridge.monitorStop();
  state.monitor.active = false;
  state.monitor.pulseNodes.clear();
  state.monitor.pulseWires.clear();
  document.getElementById("btn-monitor").classList.remove("on");
  setMonStatus("idle");
  if (!silent) logLine("[monitor] stopped", "mon");
  render();
}

async function setSignalLive(name, raw) {
  // Push a setpoint into the running service (SetSignal on its own port).
  if (!isElectron) return toast("set signal needs the Electron shell (grpcurl)", true);
  const port = (state.graph.service || {}).grpc_port;
  if (!name || !port) return toast("needs a signal_name and service.grpc_port", true);
  const value = parseFloat(String(raw).trim());
  if (Number.isNaN(value)) return toast("value must be a number", true);
  const res = await window.bridge.setSignal({
    host: "127.0.0.1", port, name, value,
    protoDir: state.live.protoDir || (state.paths && state.paths.referenceProtos),
  });
  if (res.error) {
    logLine(`[set] ${name} = ${value} → ${res.error}`, "err");
    return toast(`SetSignal failed: ${res.error}`, true);
  }
  if (res.success === false) {
    logLine(`[set] ${name} = ${value} → rejected: ${res.message || "(no reason)"}`, "err");
    return toast(`SetSignal rejected: ${res.message || "not a setpoint?"}`, true);
  }
  logLine(`[set] ${name} = ${value} → ok${res.message ? " (" + res.message + ")" : ""}`, "mon");
  toast(`${name} = ${value}`);
}

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; render(); });
}

function seriesColor(name) {
  const m = state.monitor.colors;
  if (!m.has(name)) {
    // fixed order: this graph's observe list first (stable per graph), then foreign inputs
    const order = [
      ...state.graph.observe.map((o) => o.name),
      ...state.graph.blocks.filter((b) => b.type === "SubscriberSourceBlock").map((b) => b.params.signal_name),
    ].filter(Boolean);
    const idx = order.indexOf(name);
    m.set(name, idx >= 0 && idx < SERIES_COLORS.length ? SERIES_COLORS[idx] : SERIES_NEUTRAL);
  }
  return m.get(name);
}

function onMonitorUpdate(u) {
  if (!state.monitor.active) return;
  const now = Date.now();
  state.monitor.values.set(u.name, { value: u.value, timestamp: u.timestamp, rx: now });
  state.monitor.updates++;
  if (!state.monitor.paused) {
    let h = state.monitor.history.get(u.name);
    if (!h) { h = []; state.monitor.history.set(u.name, h); }
    h.push([now, u.value]);
    while (h.length && h[0][0] < now - HISTORY_MS) h.shift();
  }
  scheduleChart();
  // pulse the tapped block and everything upstream of it
  const obs = state.graph.observe.find((o) => o.name === u.name);
  const seeds = [];
  if (obs) seeds.push(parseRef(obs.port).block);
  for (const b of state.graph.blocks) {
    if (b.type === "SubscriberSourceBlock" && b.params.signal_name === u.name) seeds.push(b.id);
  }
  const seen = new Set();
  const stack = [...seeds];
  while (stack.length) {
    const id = stack.pop();
    if (seen.has(id)) continue;
    seen.add(id);
    state.monitor.pulseNodes.set(id, now + PULSE_MS);
    for (const [from, to] of state.graph.wires) {
      if (parseRef(to).block === id) {
        state.monitor.pulseWires.set(`${from}->${to}`, now + PULSE_MS);
        stack.push(parseRef(from).block);
      }
    }
  }
  if (state.monitor.updates % 50 === 0) setMonStatus(`live · ${state.monitor.updates} updates`, "on");
  scheduleRender();
}

function fmtVal(v) {
  if (v === undefined || v === null) return "—";
  const a = Math.abs(v);
  return a >= 100 ? v.toFixed(1) : a >= 1 ? v.toFixed(3) : v.toFixed(4);
}

function fmtAge(rx) {
  const s = (Date.now() - rx) / 1000;
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`;
}

async function runCluster(mode) {
  if (!isElectron) return toast("running a cluster needs the Electron shell", true);
  const signalsRoot = state.live.signalsRoot || state.paths.signalsRoot || "";
  if (!signalsRoot) {
    return toast("no signals root — set \"signals root\" in the Service panel (Live) to <repo>/services/signals", true);
  }
  const python = state.live.python || "python";
  let opts = { mode: "all", python, signalsRoot };
  if (mode === "graph") {
    if (!state.filePath) return toast("save the graph to a file first — Run graph starts the saved graph.json", true);
    if (state.dirty) return toast("unsaved edits — save first so the running graph matches the canvas", true);
    opts = { mode: "configs", configs: [state.filePath], python, signalsRoot };
  }
  document.getElementById("logdrawer").classList.remove("collapsed");
  const res = await window.bridge.runStart(opts);
  if (res.error) return toast(res.error, true);
  state.run.active = true;
  state.run.ready = false;
  state.run.stopping = false;
  state.run.mode = mode;
  setMonStatus("cluster starting…", "warn");
  renderRunButtons();
  logLine(`[run] started pid ${res.pid} (${mode === "graph" ? state.filePath : "shipped configs"})`, "mon");
}

async function stopCluster() {
  if (!isElectron) return;
  await stopMonitor(true);
  const res = await window.bridge.runStop();
  if (res.stopped) {
    state.run.stopping = true;
    renderRunButtons();
    setMonStatus("cluster stopping…", "warn");
    logLine("[run] stop requested", "mon");
  } else {
    toast("no cluster is running", true);
  }
}

// The toolbar run buttons mirror state.run: idle → "▶", starting → "⏳",
// ready → "● Running" (click = stop), stopping → "…". The other run
// button is disabled while a cluster is up (one cluster at a time — the
// shell refuses a second one anyway).
function renderRunButtons() {
  const graph = document.getElementById("btn-run-graph");
  const all = document.getElementById("btn-run-all");
  const stop = document.getElementById("btn-stop");
  const labels = { graph: "Run graph", all: "Run cluster" };
  const buttons = { graph, all };
  const r = state.run;
  for (const [mode, btn] of Object.entries(buttons)) {
    btn.classList.remove("starting", "running", "stopping");
    if (!r.active) {
      btn.textContent = `▶ ${labels[mode]}`;
      btn.disabled = !isElectron;
      btn.title = btn.dataset.title || btn.title;
      continue;
    }
    btn.dataset.title = btn.dataset.title || btn.title;
    if (mode !== r.mode) {              // the other one: parked while a cluster is up
      btn.textContent = `▶ ${labels[mode]}`;
      btn.disabled = true;
      btn.title = "a cluster is already running — stop it first";
    } else if (r.stopping) {
      btn.textContent = `… ${labels[mode]}`;
      btn.classList.add("stopping");
      btn.disabled = true;
      btn.title = "stopping";
    } else if (r.ready) {
      btn.textContent = `● ${labels[mode]} — running`;
      btn.classList.add("running");
      btn.disabled = false;
      btn.title = "cluster is running (READY) — click to stop";
    } else {
      btn.textContent = `⏳ ${labels[mode]} — starting`;
      btn.classList.add("starting");
      btn.disabled = true;
      btn.title = "cluster starting — waiting for READY";
    }
  }
  stop.disabled = !isElectron || !r.active || r.stopping;
  stop.classList.toggle("armed", r.active && !r.stopping);
}

function wireBridgeEvents() {
  if (!isElectron) return;
  window.bridge.onRunOutput(({ stream, line }) => logLine(line, stream === "stderr" ? "err" : ""));
  window.bridge.onRunStatus(async (s) => {
    if (s.state === "ready") {
      state.run.ready = true;
      setMonStatus("cluster READY", "on");
      renderRunButtons();
      logLine("[run] cluster ready — starting monitor", "mon");
      await startMonitor();
    } else if (s.state === "exited") {
      state.run.active = false;
      state.run.ready = false;
      state.run.stopping = false;
      renderRunButtons();
      setMonStatus(s.code ? `cluster exited (code ${s.code})` : "cluster stopped", s.code ? "bad" : undefined);
      logLine(`[run] cluster exited (code ${s.code})`, s.code ? "err" : "mon");
      if (s.code) toast(`cluster exited with code ${s.code} — see the log drawer`, true);
      await stopMonitor(true);
    } else if (s.state === "error") {
      state.run.active = false;
      state.run.ready = false;
      state.run.stopping = false;
      renderRunButtons();
      setMonStatus("cluster failed", "bad");
      logLine(`[run] error: ${s.message}`, "err");
      toast(`cluster failed to start: ${s.message}`, true);
    }
  });
  window.bridge.onMonitorUpdate(onMonitorUpdate);
  window.bridge.onMonitorStatus((s) => {
    if (s.state === "error") { logLine(`[monitor ${s.key}] ${s.message}`, "err"); toast(s.message, true); }
    else if (s.state === "exited" && state.monitor.active) {
      logLine(`[monitor ${s.key}] stream ended${s.message ? ": " + s.message : ""}`, s.code ? "err" : "mon");
    }
  });
  // age refresh while monitoring
  setInterval(() => { if (state.monitor.active) { scheduleRender(); scheduleChart(); } }, 1000);
}

/* ---- Phase D2: strip chart (small multiples, shared time axis) ---- */

const chart = { hoverX: null, pausedAt: null, lastDraw: 0, queued: false, sig: "" };

function chartVisible() {
  const d = document.getElementById("logdrawer");
  return d.dataset.tab === "chart" && !d.classList.contains("collapsed");
}

function scheduleChart() {
  if (chart.queued || !chartVisible()) return;
  chart.queued = true;
  requestAnimationFrame(() => {
    chart.queued = false;
    const now = performance.now();
    if (now - chart.lastDraw < 60) { chart.queued = true; setTimeout(() => { chart.queued = false; scheduleChart(); }, 60); return; }
    chart.lastDraw = now;
    renderChart();
  });
}

function signalUnit(name) {
  const obs = state.graph.observe.find((o) => o.name === name);
  if (obs) {
    const b = blockById(parseRef(obs.port).block);
    if (b) return b.params.out_unit || b.params.unit || "";
  }
  const live = state.live.signals.find((s) => s.name === name);
  return live ? live.unit || "" : "";
}

function chartSeries() {
  const order = [
    ...state.graph.observe.map((o) => o.name),
    ...state.graph.blocks.filter((b) => b.type === "SubscriberSourceBlock").map((b) => b.params.signal_name),
  ].filter((n, i, a) => n && a.indexOf(n) === i);
  return order.filter((n) => state.monitor.history.has(n));
}

function renderSignalToggles(names) {
  const sig = names.join("|");
  if (sig === chart.sig) return;
  chart.sig = sig;
  const box = document.getElementById("chart-signals");
  box.innerHTML = names.map((n) => `<label>
      <input type="checkbox" data-sig="${n}"${state.monitor.hidden.has(n) ? "" : " checked"}>
      <span class="sw" style="background:${seriesColor(n)}"></span>${n}</label>`).join("")
    + (names.length ? `<span class="ch-hint">${names.length} signal${names.length > 1 ? "s" : ""} · strips scroll · drag the drawer's top edge to resize</span>` : "");
  box.querySelectorAll("input").forEach((cb) => cb.addEventListener("change", () => {
    if (cb.checked) state.monitor.hidden.delete(cb.dataset.sig); else state.monitor.hidden.add(cb.dataset.sig);
    renderChart();
  }));
}

const MAX_STRIPS = 32;

// Strip layout. Few signals fill the visible area (as before); beyond that each
// strip keeps `minRowH` and #chart-scroll scrolls instead of squeezing them.
// Pure — no DOM — so the geometry is checkable without a browser.
function chartGeometry(count, availH, minRowH) {
  const n = Math.max(1, count);
  const min = Math.max(24, minRowH || 48);
  const rowH = Math.max(min, Math.floor(Math.max(0, availH) / n));
  const canvasH = rowH * n;
  return { rowH, canvasH, scrolls: canvasH > availH + 1 };
}

function renderChart() {
  const panel = document.getElementById("chart-panel");
  const scroll = document.getElementById("chart-scroll");
  const cv = document.getElementById("chart");
  const all = chartSeries();
  renderSignalToggles(all);
  const shown = all.filter((n) => !state.monitor.hidden.has(n));
  const names = shown.slice(0, MAX_STRIPS);
  panel.classList.toggle("has-data", all.length > 0);
  if (!all.length) { clearChartAxis(); return; }

  // The strips canvas grows with the signal count and scrolls; the shared time
  // axis is drawn on its own canvas below the scroller so it never scrolls away.
  const dpr = window.devicePixelRatio || 1;
  const W = scroll.clientWidth;
  const geo = chartGeometry(names.length, scroll.clientHeight, state.monitor.rowH);
  const H = geo.canvasH;
  if (cv.style.height !== H + "px") cv.style.height = H + "px";
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const INK = "#f1f5f9", MUTED = "#94a3b8", GRID = "rgba(241,245,249,0.10)";
  const rightGutter = 78, left = 8;
  const plotW = W - left - rightGutter;
  const t1 = state.monitor.paused && chart.pausedAt ? chart.pausedAt : Date.now();
  const t0 = t1 - state.monitor.windowS * 1000;
  const rowH = geo.rowH;
  const xOf = (t) => left + ((t - t0) / (t1 - t0)) * plotW;

  ctx.font = "11px Consolas, monospace";
  ctx.textBaseline = "middle";

  names.forEach((name, i) => {
    const top = i * rowH, bottom = top + rowH - 6;
    const pts = (state.monitor.history.get(name) || []).filter((p) => p[0] >= t0 && p[0] <= t1);
    // recessive grid: row baseline + separator
    ctx.strokeStyle = GRID; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, bottom + 0.5); ctx.lineTo(left + plotW, bottom + 0.5); ctx.stroke();
    // row label (ink, not series colour) with a colour swatch beside it
    ctx.fillStyle = seriesColor(name); ctx.fillRect(left, top + 6, 8, 8);
    ctx.fillStyle = INK; ctx.textAlign = "left";
    const unit = signalUnit(name);
    ctx.fillText(`${name}${unit ? "  [" + unit + "]" : ""}`, left + 13, top + 10);
    if (pts.length < 2) { ctx.fillStyle = MUTED; ctx.fillText("waiting for data…", left + 13, top + rowH / 2); return; }

    let lo = Infinity, hi = -Infinity;
    for (const [, v] of pts) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (hi === lo) { hi += 0.5; lo -= 0.5; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const yTop = top + 18, yBot = bottom - 4;
    const yOf = (v) => yBot - ((v - lo) / (hi - lo)) * (yBot - yTop);

    // 2px line, no markers
    ctx.strokeStyle = seriesColor(name); ctx.lineWidth = 2; ctx.lineJoin = "round";
    ctx.beginPath();
    pts.forEach(([t, v], k) => { const x = xOf(t), y = yOf(v); if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    ctx.stroke();

    // direct labels in ink: latest value at line end; min/max in the gutter
    const [, last] = pts[pts.length - 1];
    ctx.fillStyle = INK; ctx.textAlign = "left"; ctx.font = "bold 12px Consolas, monospace";
    ctx.fillText(fmtVal(last), left + plotW + 8, yOf(last));
    ctx.font = "10px Consolas, monospace"; ctx.fillStyle = MUTED;
    ctx.fillText(`↑${fmtVal(hi + 0)}`, left + plotW + 8, yTop);
    ctx.fillText(`↓${fmtVal(lo + 0)}`, left + plotW + 8, yBot);
    ctx.font = "11px Consolas, monospace";

    // crosshair value marker for this row
    if (chart.hoverX !== null) {
      const tH = t0 + ((chart.hoverX - left) / plotW) * (t1 - t0);
      let best = null;
      for (const p of pts) { if (p[0] <= tH) best = p; else break; }
      if (best) {
        const x = xOf(best[0]), y = yOf(best[1]);
        ctx.fillStyle = "#0e1628"; ctx.beginPath(); ctx.arc(x, y, 5.5, 0, Math.PI * 2); ctx.fill();   // surface ring
        ctx.fillStyle = seriesColor(name); ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
        const label = fmtVal(best[1]);
        ctx.font = "bold 11px Consolas, monospace";
        const tw = ctx.measureText(label).width + 8;
        const lx = Math.min(x + 8, left + plotW - tw);
        ctx.fillStyle = "rgba(14,22,40,0.92)"; ctx.fillRect(lx, y - 9, tw, 16);
        ctx.fillStyle = INK; ctx.fillText(label, lx + 4, y);
        ctx.font = "11px Consolas, monospace";
      }
    }
  });

  // crosshair spans every strip; its time label lives on the axis canvas
  if (chart.hoverX !== null && chart.hoverX >= left && chart.hoverX <= left + plotW) {
    ctx.strokeStyle = "rgba(241,245,249,0.35)"; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(chart.hoverX + 0.5, 0); ctx.lineTo(chart.hoverX + 0.5, H); ctx.stroke();
    ctx.setLineDash([]);
  }
  if (shown.length > names.length) {
    ctx.fillStyle = MUTED; ctx.textAlign = "right"; ctx.font = "10px Consolas, monospace";
    ctx.fillText(`showing ${names.length} of ${shown.length} — untick some to see the rest`, W - 4, 8);
  }
  renderChartAxis(W, left, plotW, t0, t1);
}

// The shared time axis, on a fixed canvas under the scroller so it stays put
// while the strips scroll. Width is pinned to the scroller's inner width, so
// the ticks stay aligned with the plots when a scrollbar appears.
function renderChartAxis(W, left, plotW, t0, t1) {
  const ax = document.getElementById("chart-axis");
  const dpr = window.devicePixelRatio || 1, H = 20;
  if (ax.style.width !== W + "px") ax.style.width = W + "px";
  if (ax.width !== Math.round(W * dpr) || ax.height !== Math.round(H * dpr)) {
    ax.width = Math.round(W * dpr); ax.height = Math.round(H * dpr);
  }
  const ctx = ax.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "rgba(241,245,249,0.10)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(left, 0.5); ctx.lineTo(left + plotW, 0.5); ctx.stroke();
  ctx.textBaseline = "middle"; ctx.textAlign = "center";
  ctx.font = "10px Consolas, monospace"; ctx.fillStyle = "#94a3b8";
  const ticks = 5;
  for (let k = 0; k <= ticks; k++) {
    const t = t0 + (k / ticks) * (t1 - t0);
    ctx.fillText(k === ticks ? (state.monitor.paused ? "paused" : "now") : `−${((t1 - t) / 1000).toFixed(0)} s`,
                 left + (k / ticks) * plotW, 11);
  }
  if (chart.hoverX !== null && chart.hoverX >= left && chart.hoverX <= left + plotW) {
    const tH = ((chart.hoverX - left) / plotW) * (t1 - t0);
    ctx.fillStyle = "#f1f5f9"; ctx.font = "bold 10px Consolas, monospace";
    ctx.fillText(`−${((t1 - t0 - tH) / 1000).toFixed(1)} s`, chart.hoverX, 11);
  }
}

function clearChartAxis() {
  const ax = document.getElementById("chart-axis");
  if (!ax) return;
  const ctx = ax.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, ax.width, ax.height);
}

function wireChartControls() {
  const drawer = document.getElementById("logdrawer");
  drawer.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => {
    drawer.dataset.tab = btn.dataset.tab;
    drawer.classList.remove("collapsed");
    document.getElementById("logdrawer-toggle").textContent = "▼";
    if (btn.dataset.tab === "chart") renderChart();
  }));
  document.getElementById("chart-window").addEventListener("change", (ev) => {
    state.monitor.windowS = parseInt(ev.target.value, 10) || 30;
    renderChart(); scheduleRender();
  });
  document.getElementById("chart-pause").addEventListener("click", (ev) => {
    state.monitor.paused = !state.monitor.paused;
    chart.pausedAt = state.monitor.paused ? Date.now() : null;
    ev.target.textContent = state.monitor.paused ? "resume" : "pause";
    renderChart();
  });
  document.getElementById("chart-rowh").addEventListener("change", (ev) => {
    state.monitor.rowH = parseInt(ev.target.value, 10) || 48;
    renderChart();
  });
  // hover anywhere over the strips or the axis (the strips scroll, so the
  // listener sits on the scroller, not on the canvas)
  const scroll = document.getElementById("chart-scroll");
  const ax = document.getElementById("chart-axis");
  const onMove = (ev) => {
    chart.hoverX = ev.clientX - scroll.getBoundingClientRect().left;
    renderChart();
  };
  const onLeave = () => { chart.hoverX = null; renderChart(); };
  scroll.addEventListener("mousemove", onMove);
  scroll.addEventListener("mouseleave", onLeave);
  ax.addEventListener("mousemove", onMove);
  ax.addEventListener("mouseleave", onLeave);
  window.addEventListener("resize", () => { if (chartVisible()) renderChart(); });
}

/* ---- drawer height: drag the top edge, remembered per profile ---- */

const DRAWER_MIN = 110;

function applyDrawerHeight(px) {
  const d = document.getElementById("logdrawer");
  d.style.height = px == null ? "" : px + "px";
  d.style.maxHeight = px == null ? "" : px + "px";   // the CSS max-height would clamp it
}

function loadDrawerHeight() {
  try {
    const v = parseInt(localStorage.getItem("gs-drawer-h"), 10);
    if (v >= DRAWER_MIN) { state.drawerH = v; applyDrawerHeight(v); }
  } catch (_e) { /* fresh profile / blocked storage */ }
}

function wireDrawerResize() {
  const d = document.getElementById("logdrawer");
  const grip = document.getElementById("logdrawer-resize");
  let start = null;
  grip.addEventListener("mousedown", (ev) => {
    d.classList.remove("collapsed");
    document.getElementById("logdrawer-toggle").textContent = "▼";
    start = { y: ev.clientY, h: d.getBoundingClientRect().height };
    d.classList.add("resizing");
    ev.preventDefault();
  });
  window.addEventListener("mousemove", (ev) => {
    if (!start) return;
    const max = Math.max(DRAWER_MIN, window.innerHeight - 150);   // always leave the canvas usable
    state.drawerH = Math.min(max, Math.max(DRAWER_MIN, Math.round(start.h + (start.y - ev.clientY))));
    applyDrawerHeight(state.drawerH);
    if (chartVisible()) renderChart();
  });
  window.addEventListener("mouseup", () => {
    if (!start) return;
    start = null;
    d.classList.remove("resizing");
    try { localStorage.setItem("gs-drawer-h", String(state.drawerH)); } catch (_e) { /* ignore */ }
  });
  grip.addEventListener("dblclick", () => {
    state.drawerH = null;
    applyDrawerHeight(null);
    try { localStorage.removeItem("gs-drawer-h"); } catch (_e) { /* ignore */ }
    if (chartVisible()) renderChart();
  });
}

function renderFileLabel() {
  const lbl = document.getElementById("file-label");
  const name = state.filePath || state.fileName || "unsaved graph";
  lbl.innerHTML = (state.dirty ? `<span class="dirty">● </span>` : "") + name;
}

function markDirty() {
  state.dirty = true;
  renderFileLabel();
}

function loadGraphText(text, layoutText, pathOrName) {
  if (state.monitor.active) stopMonitor(true);   // targets change with the graph
  const { graph, errors } = parseGraph(text);
  if (!graph) return toast("cannot load: " + errors.join("; "), true);
  if (errors.length) toast("loaded with problems: " + errors.join("; "), true);
  state.graph = graph;
  state.selection = null;
  let layout = null;
  if (layoutText) {
    try { layout = JSON.parse(layoutText); } catch (_e) { toast("layout sidecar unreadable — auto-layouting", true); }
  }
  if (layout && layout.positions) {
    state.positions = layout.positions;
    if (layout.view) state.view = layout.view;
    // any block missing from the sidecar gets an automatic spot
    const auto = autoLayout(graph);
    for (const b of graph.blocks) if (!state.positions[b.id]) state.positions[b.id] = auto[b.id];
  } else {
    state.positions = autoLayout(graph);
    state.view = { x: 0, y: 0, scale: 1 };
  }
  if (isElectron && pathOrName && (pathOrName.includes("\\") || pathOrName.includes("/"))) {
    state.filePath = pathOrName;
    state.fileName = null;
  } else {
    state.filePath = null;
    state.fileName = pathOrName || null;
  }
  state.dirty = false;
  hideBanner();
  render();
}

function layoutContent() {
  return JSON.stringify({ version: 1, positions: state.positions, view: state.view }, null, 2) + "\n";
}

async function doOpen() {
  if (isElectron) {
    const res = await window.bridge.openGraph();
    if (!res) return;
    loadGraphText(res.content, res.layout, res.path);
  } else {
    document.getElementById("file-input").click();
  }
}

async function doSave() {
  const graphContent = serializeGraph(state.graph);
  if (isElectron) {
    const res = await window.bridge.saveGraph({ path: state.filePath, graphContent, layoutContent: layoutContent() });
    if (!res) return;
    state.filePath = res.path;
    state.dirty = false;
    renderFileLabel();
    toast(`saved ${res.path} (+ layout sidecar)`);
  } else {
    const base = (state.fileName || "graph.json").replace(/\.json$/i, "");
    download(`${base}.json`, graphContent);
    download(`${base}.layout.json`, layoutContent());
    state.dirty = false;
    renderFileLabel();
    toast("downloaded graph + layout sidecar (browser mode)");
  }
}

function download(name, content) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---- Phase A: generate a deployable graph service ---- */

function buildNomadJob(name, port) {
  return `job "testbench-signal-graph-${name}" {
    datacenters = ["dc1"]
    type        = "service"

    constraint {
      attribute = "\${node.unique.name}"
      value     = "client1"
    }
    constraint {
      attribute = "\${attr.kernel.name}"
      value     = "windows"
    }

    update {
      min_healthy_time  = "3s"
      healthy_deadline  = "1m"
      progress_deadline = "2m"
      auto_revert       = true
    }

    group "signal-graph-${name}-group" {
      count = 1
      network {
        mode = "host"
        port "grpc" {
          static       = ${port}
          host_network = "loopback"
        }
      }

      service {
        name    = "${name}"
        port    = "grpc"
        address = "127.0.0.1"
        # signal-discovery finds graph services by this tag.
        tags    = ["signals", "signal_graph"]
        check {
          type     = "grpc"
          interval = "3s"
          timeout  = "1s"
          # NOTE deliberately no initial_status = "passing" — a check must
          # earn its first passing state (recurring review finding).
        }
      }

      task "signal-graph-${name}" {
        driver = "raw_exec"
        config {
          command = "uv"
          args = [
            "run", "--active",
            "--directory", "\${node.meta.repo_root}/nomad/tools/raw_exec_wrapper",
            "python", "wrapper.py",
            "--event", "\${NOMAD_ALLOC_ID}_shutdown",
            "--grace", "10",
            "--",
            "uv", "run", "--active",
            "--directory", "\${node.meta.repo_root}/services/signals",
            "python", "-m", "signal_graph.main",
            "--config", "signal_graph/configs/${name}/graph.json",
          ]
        }
        kill_timeout = "15s"

        env {
          PYTHONUTF8      = "1"
          TAF_DRIVERS_DIR = "C:\\\\TAF\\\\drivers"

          # Registry / discovery (defaults shown; graph.json owns the port):
          # SIGNAL_GRAPH_KV_BACKEND       = "consul"
          # SIGNAL_GRAPH_KV_HOST          = "127.0.0.1"
          # SIGNAL_GRAPH_DISCOVERY_HOST   = "127.0.0.1"
          # SIGNAL_GRAPH_DEVICE_BACKEND   = "grpc"     # or "mock"
          # SIGNAL_GRAPH_STORAGE_BACKEND  = "timescale" # or "mock"
        }
      }
    }
  }
`;
}

function buildRunTxt(name, port) {
  return `Generated by Graph Studio (Phase A) — service "${name}"

This folder IS the service: since PR #253 rev 2, a graph service is the
generic signal_graph binary + this graph.json. Deploy by placing this
folder at:

    services/signals/signal_graph/configs/${name}/

Run locally (from services/signals):

    python -m signal_graph.main --config signal_graph/configs/${name}/graph.json

Verify:

    grpcurl -plaintext localhost:${port} signal.SignalQueryService/ListSignals
    grpcurl -plaintext localhost:50210 signal.SignalDiscoveryService/ListSignals   # after next catalog refresh
    grpcurl -plaintext localhost:50210 signal.SignalDiscoveryService/ListSignalErrors  # name collisions

Nomad: use the generated testbench_signal_graph_${name}.nomad next to this
folder (move it to nomad/jobs/ in the repo).

Remember: graph.json is config-as-code — this file goes through PR review
like any other change.
`;
}

async function doGenerate() {
  syncSetpoints();
  const svc = state.graph.service || {};
  if (!svc.name || !/^[a-z0-9][a-z0-9-]*$/.test(svc.name)) {
    select(null);
    return toast("service.name is required (lowercase, digits, dashes) — set it in the Service panel", true);
  }
  if (!Number.isInteger(svc.grpc_port) || svc.grpc_port <= 0) {
    select(null);
    return toast("service.grpc_port must be a positive integer — set it in the Service panel", true);
  }
  const errors = validateGraph(state.graph, state.catMap).filter((i) => i.level === "error");
  if (errors.length) {
    return toast(`fix ${errors.length} validation error(s) first: ${errors[0].msg}`, true);
  }

  const payload = {
    serviceName: svc.name,
    graphContent: serializeGraph(state.graph),
    layoutContent: layoutContent(),
    nomadContent: buildNomadJob(svc.name, svc.grpc_port),
    runContent: buildRunTxt(svc.name, svc.grpc_port),
  };

  if (isElectron) {
    const res = await window.bridge.generateService(payload);
    if (!res) return;
    toast(`service '${svc.name}' generated: ${res.files.length} files in ${res.root}`);
    if (res.collisions.length) {
      const lines = res.collisions.map((c) => `  ${c.name}  ←  ${c.services.join(", ")}`).join("\n");
      alert(`⚠ Signal-name collisions across the configs directory\n` +
            `(discovery would EXCLUDE these names — see ListSignalErrors):\n\n${lines}`);
    }
  } else {
    download(`${svc.name}__graph.json`, payload.graphContent);
    download(`${svc.name}__graph.layout.json`, payload.layoutContent);
    download(`testbench_signal_graph_${svc.name}.nomad`, payload.nomadContent);
    download(`${svc.name}__RUN.txt`, payload.runContent);
    toast("4 files downloaded (browser mode — cross-graph collision scan needs the Electron shell)");
  }
}

document.getElementById("file-input").addEventListener("change", async (ev) => {
  const files = [...ev.target.files];
  ev.target.value = "";
  if (!files.length) return;
  const layoutFile = files.find((f) => f.name.endsWith(".layout.json"));
  const graphFile = files.find((f) => !f.name.endsWith(".layout.json"));
  if (!graphFile) return toast("select the graph.json (optionally plus its .layout.json)", true);
  const text = await graphFile.text();
  const layoutText = layoutFile ? await layoutFile.text() : null;
  loadGraphText(text, layoutText, graphFile.name);
});

/* ---- external change banner (Electron watch) ---- */

function showBanner(text) {
  document.getElementById("banner-text").textContent = text;
  document.getElementById("banner").classList.add("show");
}
function hideBanner() {
  document.getElementById("banner").classList.remove("show");
}

if (isElectron) {
  window.bridge.onFileChanged(async (p) => {
    if (p !== state.filePath) return;
    if (!state.dirty) {
      const res = await window.bridge.reloadGraph(p);
      loadGraphText(res.content, res.layout, res.path);
      toast("file changed on disk — reloaded");
    } else {
      showBanner("The file changed on disk but you have unsaved edits.");
    }
  });
  document.getElementById("banner-reload").addEventListener("click", async () => {
    const res = await window.bridge.reloadGraph(state.filePath);
    loadGraphText(res.content, res.layout, res.path);
  });
  document.getElementById("banner-dismiss").addEventListener("click", hideBanner);
}

/* ============================== toolbar ============================== */

document.getElementById("btn-open").addEventListener("click", doOpen);
document.getElementById("btn-save").addEventListener("click", doSave);
document.getElementById("btn-new").addEventListener("click", () => {
  state.graph = {
    blocks: [], wires: [], observe: [],
    wireKey: "signals",
    service: { name: "", grpc_port: 50200, rate_hz: 10.0, flow_mode: "push" },
    device_services: {}, setpoints: [], extra: {}, topOrder: [],
  };
  state.positions = {};
  state.view = { x: 0, y: 0, scale: 1 };
  state.filePath = null;
  state.fileName = null;
  state.dirty = false;
  state.selection = null;
  hideBanner();
  render();
});
document.getElementById("btn-generate").addEventListener("click", doGenerate);
// a run button that shows "● running" acts as the stop button (toggle)
const runOrStop = (mode) => (state.run.active && state.run.mode === mode ? stopCluster() : runCluster(mode));
document.getElementById("btn-run-graph").addEventListener("click", () => runOrStop("graph"));
document.getElementById("btn-run-all").addEventListener("click", () => runOrStop("all"));
document.getElementById("btn-stop").addEventListener("click", stopCluster);
document.getElementById("btn-monitor").addEventListener("click", () => {
  if (state.monitor.active) stopMonitor(false); else startMonitor();
});
document.getElementById("logdrawer-toggle").addEventListener("click", () => {
  const d = document.getElementById("logdrawer");
  d.classList.toggle("collapsed");
  document.getElementById("logdrawer-toggle").textContent = d.classList.contains("collapsed") ? "▲" : "▼";
});
document.getElementById("logdrawer-clear").addEventListener("click", () => {
  const drawer = document.getElementById("logdrawer");
  if (drawer.dataset.tab === "chart") { state.monitor.history.clear(); chart.sig = ""; renderChart(); }
  else document.getElementById("logdrawer-body").innerHTML = "";
});
wireChartControls();
wireDrawerResize();
loadDrawerHeight();
document.getElementById("btn-layout").addEventListener("click", () => {
  state.positions = autoLayout(state.graph);
  markDirty();
  render();
});
document.getElementById("sel-example").addEventListener("change", (ev) => {
  const key = ev.target.value;
  ev.target.value = "";
  if (!key || !EXAMPLES[key]) return;
  loadGraphText(JSON.stringify(EXAMPLES[key]), null, `${key} (example)`);
  markDirty(); // examples are unsaved content
});

window.addEventListener("beforeunload", (ev) => {
  if (state.dirty) { ev.preventDefault(); ev.returnValue = ""; }
});

/* ============================== toast ============================== */

let toastTimer = null;
function toast(msg, isError) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, isError ? 4200 : 2600);
}

/* ============================== boot ============================== */

async function boot() {
  if (isElectron) {
    const txt = await window.bridge.loadCatalog();
    if (txt) {
      try {
        const cat = JSON.parse(txt);
        const problems = checkCatalog(cat);
        if (problems.length) {
          toast("blocks_catalog.json rejected: " + problems[0] + " — using built-in placeholder", true);
        } else {
          state.catalog = cat;
          state.catMap = catalogByType(cat);
        }
      } catch (e) {
        toast("blocks_catalog.json is not valid JSON — using built-in placeholder", true);
      }
    }
  }
  loadLive();
  ensureDatalists();
  if (isElectron) {
    try { Object.assign(state.paths, await window.bridge.getPaths()); } catch (_e) { /* older shell */ }
    wireBridgeEvents();
    renderRunButtons();   // idle: ■ disabled until a cluster is up
  } else {
    for (const id of ["btn-run-graph", "btn-run-all", "btn-stop", "btn-monitor"]) {
      document.getElementById(id).disabled = true;
      document.getElementById(id).title += " (Electron only)";
    }
  }
  renderPalette();
  loadGraphText(JSON.stringify(EXAMPLES.signal_in), null, "signal_in (example)");
  state.dirty = false;
  renderFileLabel();
}

boot();
