// Graph model: parse / serialize / validate graph.json and topology helpers.
// The canonical on-disk shape (from the revision-2 schema prototypes):
//   { "blocks":  [ { "id", "type", "params" } ],
//     "wires":   [ [ "blockId.port", "blockId.port" ] ],
//     "observe": [ { "port": "blockId.port", "name": "signal_name" } ] }
// Layout (node positions, view) never goes into graph.json — it lives in a
// sidecar <file>.layout.json so the executable artifact stays pure.
"use strict";

function parseRef(ref) {
  if (typeof ref !== "string") return null;
  const i = ref.lastIndexOf(".");
  if (i <= 0 || i === ref.length - 1) return null;
  return { block: ref.slice(0, i), port: ref.slice(i + 1) };
}

function makeRef(block, port) {
  return `${block}.${port}`;
}

// Parse text → { graph, errors }. graph is null on fatal errors.
//
// Two wire dialects are accepted (the concept doc and the revision-2
// prototype disagree -- flagged upstream as doc drift):
//   deck sketch:   "wires":   [ ["a.out", "b.in"], ... ]
//   prototype:     "signals": [ { "from": "a.out", "to": "b.in" }, ... ]
// The dialect that was read is remembered and written back on save, and all
// unknown top-level sections (service, device_services, setpoints, ...) and
// unknown block fields (description, ...) are preserved verbatim.
function parseGraph(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return { graph: null, errors: [`not valid JSON: ${e.message}`] };
  }
  const errors = [];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { graph: null, errors: ["top level must be a JSON object"] };
  }
  const wireKey = raw.signals !== undefined ? "signals" : "wires";
  const graph = {
    blocks: [], wires: [], observe: [],
    wireKey,                      // dialect to write back on save
    topOrder: Object.keys(raw),   // original top-level key order
    extra: {},                    // preserved unknown top-level sections
    // Phase A: first-class, editable sections (rev-2 schema)
    service: (raw.service && typeof raw.service === "object") ? { ...raw.service } : null,
    device_services: (raw.device_services && typeof raw.device_services === "object")
      ? { ...raw.device_services } : {},
    setpoints: Array.isArray(raw.setpoints) ? raw.setpoints.map((e) => ({ ...e })) : [],
  };
  if (raw.blocks !== undefined && !Array.isArray(raw.blocks)) errors.push("'blocks' must be an array");
  if (raw[wireKey] !== undefined && !Array.isArray(raw[wireKey])) errors.push(`'${wireKey}' must be an array`);
  if (raw.observe !== undefined && !Array.isArray(raw.observe)) errors.push("'observe' must be an array");
  if (errors.length) return { graph: null, errors };

  const OWNED = ["blocks", "wires", "signals", "observe",
                 "service", "device_services", "setpoints"];
  for (const key of graph.topOrder) {
    if (!OWNED.includes(key)) graph.extra[key] = raw[key];
  }

  for (const [i, b] of (raw.blocks || []).entries()) {
    if (!b || typeof b !== "object" || typeof b.id !== "string" || typeof b.type !== "string") {
      errors.push(`blocks[${i}]: each block needs string 'id' and 'type'`);
      continue;
    }
    const { id, type, params, ...rest } = b;
    graph.blocks.push({
      id, type,
      params: (params && typeof params === "object") ? params : {},
      extra: rest, // e.g. "description" — kept and written back
    });
  }
  for (const [i, w] of (raw[wireKey] || []).entries()) {
    if (Array.isArray(w) && w.length === 2 && parseRef(w[0]) && parseRef(w[1])) {
      graph.wires.push([w[0], w[1]]);
    } else if (w && typeof w === "object" && parseRef(w.from) && parseRef(w.to)) {
      graph.wires.push([w.from, w.to]);
    } else {
      errors.push(`${wireKey}[${i}]: must be ["block.port","block.port"] or {"from":"block.port","to":"block.port"}`);
    }
  }
  for (const [i, o] of (raw.observe || []).entries()) {
    if (!o || typeof o !== "object" || !parseRef(o.port) || typeof o.name !== "string" || !o.name) {
      errors.push(`observe[${i}]: needs 'port' ("block.port") and non-empty 'name'`);
      continue;
    }
    graph.observe.push({ port: o.port, name: o.name });
  }
  return { graph, errors };
}

// Serialization: writes back the dialect the graph was loaded with (prototype
// "signals" objects by default for new graphs), keeps the original top-level
// key order, and re-emits preserved sections and block fields untouched.
function serializeGraph(graph) {
  const wireKey = graph.wireKey || "signals";
  const wiresOut = wireKey === "signals"
    ? graph.wires.map(([a, b]) => ({ from: a, to: b }))
    : graph.wires;
  const obsOut = graph.observe.map((o) =>
    wireKey === "signals" ? { name: o.name, port: o.port } : { port: o.port, name: o.name });
  const blocksOut = graph.blocks.map((b) => ({ id: b.id, type: b.type, ...(b.extra || {}), params: b.params }));

  const obj = {};
  const order = (graph.topOrder && graph.topOrder.length)
    ? graph.topOrder
    : ["service", "device_services", "blocks", wireKey, "observe", "setpoints"];
  const emit = (k) => {
    if (k === "wires" || k === "signals") obj[wireKey] = wiresOut;
    else if (k === "blocks") obj.blocks = blocksOut;
    else if (k === "observe") obj.observe = obsOut;
    else if (k === "service") { if (graph.service) obj.service = graph.service; }
    else if (k === "device_services") obj.device_services = graph.device_services || {};
    else if (k === "setpoints") obj.setpoints = graph.setpoints || [];
    else if (graph.extra && k in graph.extra) obj[k] = graph.extra[k];
  };
  for (const k of order) emit(k);
  // sections that exist but weren't in the original key order (added in-tool)
  if (graph.service && !("service" in obj)) obj.service = graph.service;
  if (!("device_services" in obj) && Object.keys(graph.device_services || {}).length) {
    obj.device_services = graph.device_services;
  }
  if (!("blocks" in obj)) obj.blocks = blocksOut;
  if (!(wireKey in obj)) obj[wireKey] = wiresOut;
  if (!("observe" in obj)) obj.observe = obsOut;
  if (!("setpoints" in obj) && (graph.setpoints || []).length) obj.setpoints = graph.setpoints;
  for (const k of Object.keys(graph.extra || {})) if (!(k in obj)) obj[k] = graph.extra[k];
  return JSON.stringify(obj, null, 2) + "\n";
}

// Render/validation spec for one block: from the catalog if known, otherwise
// inferred from how the graph references it (forward-compat with catalog drift).
function blockSpec(block, catMap, graph) {
  const known = catMap.get(block.type);
  if (known) return { known: true, family: known.family, inputs: known.inputs || [], outputs: known.outputs || [], params: known.params || [], doc: known.doc || "" };
  const inputs = new Set();
  const outputs = new Set();
  for (const [from, to] of graph.wires) {
    const f = parseRef(from);
    const t = parseRef(to);
    if (f && f.block === block.id) outputs.add(f.port);
    if (t && t.block === block.id) inputs.add(t.port);
  }
  for (const o of graph.observe) {
    const r = parseRef(o.port);
    if (r && r.block === block.id) outputs.add(r.port);
  }
  return {
    known: false, family: "unknown", doc: "type not in catalog",
    inputs: [...inputs].map((n) => ({ name: n, type: "unknown" })),
    outputs: [...outputs].map((n) => ({ name: n, type: "unknown" })),
    params: [],
  };
}

function portType(spec, dir, portName) {
  const list = dir === "in" ? spec.inputs : spec.outputs;
  const p = list.find((x) => x.name === portName);
  return p ? p.type : null;
}

// Blocks involved in at least one cycle (iterative peeling of sources/sinks).
function cycleBlocks(graph) {
  const ids = new Set(graph.blocks.map((b) => b.id));
  const succ = new Map();
  const indeg = new Map();
  for (const id of ids) { succ.set(id, []); indeg.set(id, 0); }
  for (const [from, to] of graph.wires) {
    const f = parseRef(from), t = parseRef(to);
    if (!f || !t || !ids.has(f.block) || !ids.has(t.block)) continue;
    succ.get(f.block).push(t.block);
    indeg.set(t.block, indeg.get(t.block) + 1);
  }
  const queue = [...ids].filter((id) => indeg.get(id) === 0);
  const removed = new Set();
  while (queue.length) {
    const id = queue.pop();
    removed.add(id);
    for (const nxt of succ.get(id)) {
      indeg.set(nxt, indeg.get(nxt) - 1);
      if (indeg.get(nxt) === 0 && !removed.has(nxt)) queue.push(nxt);
    }
  }
  return [...ids].filter((id) => !removed.has(id));
}

// Full validation → [{ level: "error"|"warn", msg, blockId? }]
function validateGraph(graph, catMap) {
  const issues = [];
  const byId = new Map();

  for (const b of graph.blocks) {
    if (byId.has(b.id)) issues.push({ level: "error", msg: `duplicate block id '${b.id}'`, blockId: b.id });
    byId.set(b.id, b);
    const spec = blockSpec(b, catMap, graph);
    if (!spec.known) {
      issues.push({ level: "warn", msg: `block '${b.id}': type '${b.type}' not in catalog (rendered from wiring; not type-checked)`, blockId: b.id });
      continue;
    }
    for (const ps of spec.params) {
      if (ps.required && !(ps.name in b.params)) {
        issues.push({ level: "error", msg: `block '${b.id}': missing required param '${ps.name}'`, blockId: b.id });
      }
    }
    for (const key of Object.keys(b.params)) {
      if (!spec.params.find((p) => p.name === key)) {
        issues.push({ level: "warn", msg: `block '${b.id}': param '${key}' not declared for ${b.type} (kept as-is)`, blockId: b.id });
      }
    }
  }

  const wiredInputs = new Map(); // "id.port" -> count
  for (const [i, [from, to]] of graph.wires.entries()) {
    const f = parseRef(from), t = parseRef(to);
    const fb = f && byId.get(f.block);
    const tb = t && byId.get(t.block);
    // Count input occupancy for every wire whose target resolves — even if the
    // source is dangling, the input is still occupied in the JSON the engine reads.
    if (tb) wiredInputs.set(to, (wiredInputs.get(to) || 0) + 1);
    if (!fb) { issues.push({ level: "error", msg: `wires[${i}]: unknown source block in '${from}'` }); continue; }
    if (!tb) { issues.push({ level: "error", msg: `wires[${i}]: unknown target block in '${to}'` }); continue; }
    const fSpec = blockSpec(fb, catMap, graph);
    const tSpec = blockSpec(tb, catMap, graph);
    const fType = portType(fSpec, "out", f.port);
    const tType = portType(tSpec, "in", t.port);
    if (fSpec.known && fType === null) issues.push({ level: "error", msg: `wires[${i}]: '${fb.type}' has no output port '${f.port}'`, blockId: fb.id });
    if (tSpec.known && tType === null) issues.push({ level: "error", msg: `wires[${i}]: '${tb.type}' has no input port '${t.port}'`, blockId: tb.id });
    if (fType && tType && fType !== "unknown" && tType !== "unknown" && fType !== tType) {
      issues.push({ level: "error", msg: `wires[${i}]: type mismatch ${from} (${fType}) → ${to} (${tType})` });
    }
  }
  for (const [ref, n] of wiredInputs) {
    if (n > 1) issues.push({ level: "error", msg: `input '${ref}' has ${n} incoming wires (max 1 — wires are latches)` });
  }

  // Unwired inputs: functions/sinks with a dangling input never fire usefully.
  for (const b of graph.blocks) {
    const spec = blockSpec(b, catMap, graph);
    if (!spec.known) continue;
    for (const inp of spec.inputs) {
      if (!wiredInputs.has(makeRef(b.id, inp.name))) {
        issues.push({ level: "warn", msg: `block '${b.id}': input '${inp.name}' is not wired`, blockId: b.id });
      }
    }
  }

  const obsNames = new Map();
  for (const [i, o] of graph.observe.entries()) {
    const r = parseRef(o.port);
    const ob = r && byId.get(r.block);
    if (!ob) { issues.push({ level: "error", msg: `observe[${i}]: unknown block in '${o.port}'` }); continue; }
    const spec = blockSpec(ob, catMap, graph);
    if (spec.known && portType(spec, "out", r.port) === null) {
      issues.push({ level: "error", msg: `observe[${i}]: '${ob.type}' has no output port '${r.port}' (only outputs can be observed)`, blockId: ob.id });
    }
    if (obsNames.has(o.name)) issues.push({ level: "error", msg: `observe: duplicate signal name '${o.name}'` });
    obsNames.set(o.name, o.port);
  }

  // ─── Phase A: service section ────────────────────────────────
  if (!graph.service) {
    issues.push({ level: "warn", msg: "no 'service' section — the graph is viewable but not generatable as a service" });
  } else {
    const svc = graph.service;
    if (!svc.name) issues.push({ level: "warn", msg: "service.name is empty — required to generate a service" });
    if (svc.grpc_port !== undefined && (!Number.isInteger(svc.grpc_port) || svc.grpc_port <= 0)) {
      issues.push({ level: "error", msg: `service.grpc_port must be a positive integer (got ${JSON.stringify(svc.grpc_port)})` });
    }
    if (svc.rate_hz !== undefined && !(svc.rate_hz > 0)) {
      issues.push({ level: "warn", msg: `service.rate_hz ${JSON.stringify(svc.rate_hz)} — the engine FREE-RUNS (as fast as the loop allows) when rate_hz <= 0` });
    }
    if (svc.flow_mode !== undefined && !["push", "pull"].includes(svc.flow_mode)) {
      issues.push({ level: "error", msg: `service.flow_mode must be "push" or "pull" (got ${JSON.stringify(svc.flow_mode)})` });
    }
  }

  // ─── Phase A: device mapping ─────────────────────────────────
  const deviceMap = graph.device_services || {};
  for (const [logical, consulName] of Object.entries(deviceMap)) {
    if (!consulName) {
      issues.push({ level: "warn", msg: `device_services['${logical}'] has no Consul service name yet` });
    }
  }
  for (const b of graph.blocks) {
    const spec = blockSpec(b, catMap, graph);
    if (!spec.known) continue;
    for (const ps of spec.params) {
      if (ps.type === "device_ref" && ps.name in b.params) {
        const ref = b.params[ps.name];
        if (!(ref in deviceMap)) {
          issues.push({
            level: "error", blockId: b.id,
            msg: `block '${b.id}': device '${ref}' is not defined in device_services — map it to a Consul service first`,
          });
        }
      }
      if (ps.type === "enum" && ps.name in b.params) {
        const v = b.params[ps.name];
        const choices = Array.isArray(ps.choices) ? ps.choices : [];
        if (!choices.includes(v)) {
          issues.push({
            level: "error", blockId: b.id,
            msg: `block '${b.id}': param '${ps.name}' must be one of ${choices.join(" | ")} (got ${JSON.stringify(v)})`,
          });
        }
      }
      if (ps.type === "list" && ps.name in b.params && !Array.isArray(b.params[ps.name])) {
        issues.push({ level: "error", blockId: b.id, msg: `block '${b.id}': param '${ps.name}' must be a JSON list` });
      }
      if (ps.type === "object" && ps.name in b.params) {
        const v = b.params[ps.name];
        if (v === null || typeof v !== "object" || Array.isArray(v)) {
          issues.push({ level: "error", blockId: b.id, msg: `block '${b.id}': param '${ps.name}' must be a JSON object` });
        }
      }
      // allowlist rule: value must be one of another list param's entries
      // (e.g. service_name ∈ allowlist[*].service) — same refusal the engine makes at build
      if (ps.allowed_from && ps.name in b.params) {
        const { param: srcName, field } = ps.allowed_from;
        const src = b.params[srcName];
        const value = b.params[ps.name];
        if (!Array.isArray(src) || src.length === 0) {
          issues.push({
            level: "error", blockId: b.id,
            msg: `block '${b.id}': '${srcName}' is empty — nothing is allowed for '${ps.name}' (add entries to '${srcName}')`,
          });
        } else {
          const allowed = [];
          src.forEach((e, k) => {
            if (field) {
              if (e && typeof e === "object" && !Array.isArray(e) && field in e) allowed.push(String(e[field]));
              else issues.push({ level: "error", blockId: b.id, msg: `block '${b.id}': ${srcName}[${k}] has no '${field}' field` });
            } else if (typeof e === "string") {
              allowed.push(e);
            } else {
              issues.push({ level: "error", blockId: b.id, msg: `block '${b.id}': ${srcName}[${k}] must be a string` });
            }
          });
          if (!allowed.includes(String(value))) {
            issues.push({
              level: "error", blockId: b.id,
              msg: `block '${b.id}': '${ps.name}' = ${JSON.stringify(value)} is not in '${srcName}' (allowed: ${allowed.join(", ") || "none"})`,
            });
          }
        }
      }
    }
  }

  // ─── Phase A: setpoints ↔ SetpointBlock consistency ─────────
  const setpointBlockNames = new Set(
    graph.blocks.filter((b) => b.type === "SetpointBlock")
      .map((b) => b.params.signal_name).filter(Boolean),
  );
  const setpointEntryNames = new Set((graph.setpoints || []).map((e) => e.name));
  for (const name of setpointBlockNames) {
    if (!setpointEntryNames.has(name)) {
      issues.push({ level: "warn", msg: `SetpointBlock signal '${name}' missing from the setpoints section (the tool can sync it)` });
    }
  }
  for (const name of setpointEntryNames) {
    if (!setpointBlockNames.has(name)) {
      issues.push({ level: "warn", msg: `setpoints entry '${name}' has no SetpointBlock with that signal_name (orphan)` });
    }
  }

  const cyc = cycleBlocks(graph);
  if (cyc.length) {
    issues.push({
      level: "error",
      msg: `cycle through [${cyc.join(", ")}] — the engine rejects cyclic graphs at startup (topological_order raises ValueError); latch-based feedback is a possible future semantics (open contract C1), but today this graph will not boot`,
    });
  }

  return issues;
}
