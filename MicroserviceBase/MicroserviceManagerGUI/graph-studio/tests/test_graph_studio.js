// Headless logic test for graph-studio (Phase A / rev-2 schema).
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// Vendored copy: the tool root is this folder's parent. "python" on PATH is
// often a stub on Windows — set GS_PYTHON to pick the interpreter.
const ROOT = path.join(__dirname, "..");
const PY = process.env.GS_PYTHON || "python";
const ctx = vm.createContext({ console });
for (const f of ["app/catalog.js", "app/model.js", "app/layout.js"]) {
  vm.runInContext(fs.readFileSync(path.join(ROOT, f), "utf-8"), ctx, { filename: f });
}
const G = vm.runInContext(
  "({ DEFAULT_CATALOG, checkCatalog, catalogByType, parseGraph, serializeGraph, validateGraph, autoLayout, parseRef, makeRef, cycleBlocks })",
  ctx
);

let failures = 0;
function check(name, cond, extra) {
  if (cond) console.log("PASS", name);
  else { failures++; console.log("FAIL", name, extra !== undefined ? JSON.stringify(extra).slice(0, 300) : ""); }
}
function sortKeys(v) {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === "object") {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = sortKeys(v[k]);
    return o;
  }
  return v;
}
const catMap = G.catalogByType(G.DEFAULT_CATALOG);
const errsOf = (g) => G.validateGraph(g, catMap).filter((i) => i.level === "error");
const warnsOf = (g) => G.validateGraph(g, catMap).filter((i) => i.level === "warn");

// ─── catalog ────────────────────────────────────────────────────────
check("default catalog shape ok", G.checkCatalog(G.DEFAULT_CATALOG).length === 0, G.checkCatalog(G.DEFAULT_CATALOG));
const catFile = JSON.parse(fs.readFileSync(path.join(ROOT, "blocks_catalog.json"), "utf-8"));
check("blocks_catalog.json shape ok", G.checkCatalog(catFile).length === 0, G.checkCatalog(catFile));
check("catalog file matches built-in types",
  JSON.stringify(catFile.blocks.map((b) => b.type).sort()) ===
  JSON.stringify(G.DEFAULT_CATALOG.blocks.map((b) => b.type).sort()));
// The catalog is regenerated against the repo's real block packages too, so a
// superset of the rev-2 set is correct; the invariant is that the set is there.
const REV2_TYPES = ["AdcBlock", "SetpointBlock", "SubscriberSourceBlock", "LinearScaleBlock",
                    "ClampBlock", "DecimatorBlock", "ThresholdBlock", "RecordSignalBlock", "DacBlock"];
check("rev-2 set present (superset allowed) incl SubscriberSourceBlock",
  REV2_TYPES.every((t) => catMap.has(t)) && G.DEFAULT_CATALOG.blocks.length >= REV2_TYPES.length,
  REV2_TYPES.filter((t) => !catMap.has(t)));

// ─── examples: parse, validate, round-trip, layout ─────────────────
for (const ex of ["signal_in", "signal_proc"]) {
  const text = fs.readFileSync(path.join(ROOT, "examples", ex + ".graph.json"), "utf-8");
  const { graph, errors } = G.parseGraph(text);
  check(`${ex}: parses`, graph !== null && errors.length === 0, errors);
  check(`${ex}: zero validation errors`, errsOf(graph).length === 0, errsOf(graph).map((i) => i.msg));
  check(`${ex}: service promoted`, graph.service && typeof graph.service.name === "string");
  const s1 = G.serializeGraph(graph);
  const s2 = G.serializeGraph(G.parseGraph(s1).graph);
  check(`${ex}: serialize round-trip stable`, s1 === s2);
  check(`${ex}: lossless vs source`,
    JSON.stringify(sortKeys(JSON.parse(s1))) === JSON.stringify(sortKeys(JSON.parse(text))));
  const pos = G.autoLayout(graph);
  check(`${ex}: layout covers all blocks`, graph.blocks.every((b) => pos[b.id]));
}

// ─── real rev-1 repo files still work (backward compat) ────────────
for (const rel of ["services/signals/input/graph.json", "services/signals/output/graph.json"]) {
  const p = path.join("D:/Project/TA/taf_repo_proposal", rel);
  if (!fs.existsSync(p)) { console.log("SKIP", rel); continue; }
  const raw = fs.readFileSync(p, "utf-8");
  const { graph, errors } = G.parseGraph(raw);
  check(`${rel}: parses`, graph !== null && errors.length === 0, errors);
  check(`${rel}: zero errors`, errsOf(graph).length === 0, errsOf(graph).map((i) => i.msg));
  check(`${rel}: lossless round-trip`,
    JSON.stringify(sortKeys(JSON.parse(G.serializeGraph(graph)))) === JSON.stringify(sortKeys(JSON.parse(raw))));
}

// ─── Phase A validations ────────────────────────────────────────────
const base = () => ({
  blocks: [], wires: [], observe: [], setpoints: [], extra: {}, topOrder: [],
  wireKey: "signals", device_services: {},
  service: { name: "x", grpc_port: 50200, rate_hz: 10.0, flow_mode: "push" },
});

{ // unmapped device_ref → error
  const g = base();
  g.blocks = [{ id: "a", type: "AdcBlock", params: { device: "ghost_dev", channel: 0 } }];
  check("unmapped device -> error", errsOf(g).some((i) => i.msg.includes("not defined in device_services")));
  g.device_services = { ghost_dev: "testbench-device-ai-mock" };
  check("mapped device -> ok", errsOf(g).length === 0, errsOf(g).map((i) => i.msg));
}
{ // service checks
  const g = base();
  g.service.flow_mode = "sideways";
  check("bad flow_mode -> error", errsOf(g).some((i) => i.msg.includes("flow_mode")));
  g.service.flow_mode = "push";
  g.service.rate_hz = 0;
  check("rate_hz 0 -> free-run warn", warnsOf(g).some((i) => i.msg.includes("FREE-RUNS")));
  const g2 = base(); delete g2.service; g2.service = null;
  check("missing service -> warn", warnsOf(g2).some((i) => i.msg.includes("no 'service' section")));
}
{ // setpoints sync warnings
  const g = base();
  g.blocks = [{ id: "sp", type: "SetpointBlock", params: { signal_name: "s.p" } }];
  check("setpoint block without entry -> warn", warnsOf(g).some((i) => i.msg.includes("missing from the setpoints")));
  g.setpoints = [{ name: "s.p" }, { name: "orphan.x" }];
  check("orphan setpoint entry -> warn", warnsOf(g).some((i) => i.msg.includes("orphan")));
}

// ─── legacy validation still intact ─────────────────────────────────
{
  const g = base();
  g.device_services = { d: "svc" };
  g.blocks = [
    { id: "a", type: "AdcBlock", params: {} },                        // missing device+channel
    { id: "a", type: "LinearScaleBlock", params: { gain: 1 } },       // duplicate id
    { id: "rec", type: "RecordSignalBlock", params: { signal_name: "x" } },
    { id: "mystery", type: "NotInCatalog", params: {} },
  ];
  g.wires = [["a.out", "rec.in"], ["a.out", "rec.in2"], ["ghost.out", "rec.in"]];
  g.observe = [{ port: "rec.in", name: "sig1" }, { port: "a.out", name: "sig1" }];
  const msgs = G.validateGraph(g, catMap).map((i) => `${i.level}:${i.msg}`).join("\n");
  for (const frag of ["duplicate block id 'a'", "missing required param", "not in catalog",
                      "no input port 'in2'", "unknown source block", "incoming wires",
                      "only outputs can be observed", "duplicate signal name 'sig1'"]) {
    check(`legacy: detects ${frag.slice(0, 30)}`, msgs.includes(frag), msgs);
  }
}
{ // cycle detection + cycle-safe layout
  const g = base();
  g.blocks = [
    { id: "s1", type: "LinearScaleBlock", params: { gain: 1 } },
    { id: "s2", type: "LinearScaleBlock", params: { gain: 1 } },
  ];
  g.wires = [["s1.out", "s2.in"], ["s2.out", "s1.in"]];
  check("cycle -> error", errsOf(g).some((i) => i.msg.includes("cycle")));
  check("cycle-safe layout", Object.keys(G.autoLayout(g)).length === 2);
}
{ // synthetic type mismatch (catalog is all-float; use an ad-hoc map)
  const custom = new Map(catMap);
  custom.set("BytesSource", { type: "BytesSource", family: "source", inputs: [], outputs: [{ name: "out", type: "bytes" }], params: [] });
  const g = base();
  g.blocks = [{ id: "b", type: "BytesSource", params: {} },
              { id: "s", type: "LinearScaleBlock", params: { gain: 1 } }];
  g.wires = [["b.out", "s.in"]];
  const errs = G.validateGraph(g, custom).filter((i) => i.level === "error");
  check("type mismatch bytes->float", errs.some((i) => i.msg.includes("type mismatch")));
}
check("parseRef rejects bare name", G.parseRef("noport") === null);
check("parseRef keeps dotted block ids",
  JSON.stringify(G.parseRef("a.b.out")) === JSON.stringify({ block: "a.b", port: "out" }));

// ─── new-graph serialization defaults ───────────────────────────────
{
  const g = base();
  g.blocks = [{ id: "sp", type: "SetpointBlock", params: { signal_name: "n.v" } }];
  g.setpoints = [{ name: "n.v" }];
  const out = JSON.parse(G.serializeGraph(g));
  check("new graph emits service/device_services/setpoints",
    "service" in out && "device_services" in out && "setpoints" in out && "signals" in out,
    Object.keys(out));
}

// ─── enum params (tool-level type) ──────────────────────────────────
{
  const custom = new Map(catMap);
  custom.set("UdsWriteSinkBlock", {
    type: "UdsWriteSinkBlock", family: "sink",
    inputs: [{ name: "value", type: "float" }], outputs: [],
    params: [{ name: "trigger", type: "enum", required: false, choices: ["on_change", "every_write", "edge"] }],
  });
  const g = base();
  g.blocks = [{ id: "w", type: "UdsWriteSinkBlock", params: { trigger: "sometimes" } }];
  let errs = G.validateGraph(g, custom).filter((i) => i.level === "error");
  check("enum: value outside choices -> error", errs.some((i) => i.msg.includes("must be one of on_change | every_write | edge")), errs.map((i) => i.msg));
  g.blocks[0].params.trigger = "edge";
  errs = G.validateGraph(g, custom).filter((i) => i.level === "error");
  check("enum: valid choice -> ok", errs.length === 0, errs.map((i) => i.msg));
  delete g.blocks[0].params.trigger;
  errs = G.validateGraph(g, custom).filter((i) => i.level === "error");
  check("enum: optional unset -> ok", errs.length === 0, errs.map((i) => i.msg));
  const bad = { blocks: [{ type: "X", family: "sink", inputs: [], outputs: [], params: [{ name: "p", type: "enum" }] }] };
  check("checkCatalog: enum without choices flagged", G.checkCatalog(bad).some((p) => p.includes("needs a non-empty 'choices'")));
}

// ─── list/object params + allowlist rule (TODO-5) ───────────────────
{
  const custom = new Map(catMap);
  custom.set("UdsWriteSinkBlock", {
    type: "UdsWriteSinkBlock", family: "sink",
    inputs: [{ name: "value", type: "float" }], outputs: [],
    params: [
      { name: "allowlist", type: "list", required: false },
      { name: "service_name", type: "string", required: true, allowed_from: { param: "allowlist", field: "service" } },
      { name: "limits", type: "object", required: false },
    ],
  });
  custom.set("NamesBlock", {
    type: "NamesBlock", family: "sink", inputs: [{ name: "in", type: "float" }], outputs: [],
    params: [{ name: "names", type: "list" }, { name: "pick", type: "string", allowed_from: { param: "names" } }],
  });
  const errs = (g) => G.validateGraph(g, custom).filter((i) => i.level === "error").map((i) => i.msg);
  const mk = (params) => { const g = base(); g.blocks = [{ id: "w", type: "UdsWriteSinkBlock", params }]; return g; };
  check("allowlist: service in list -> ok",
    errs(mk({ allowlist: [{ service: "IOControl_Fan", min: 0, max: 100 }], service_name: "IOControl_Fan" })).length === 0,
    errs(mk({ allowlist: [{ service: "IOControl_Fan" }], service_name: "IOControl_Fan" })));
  check("allowlist: service NOT in list -> error",
    errs(mk({ allowlist: [{ service: "IOControl_Fan" }], service_name: "WriteDID_F190" })).some((m) => m.includes("is not in 'allowlist'") && m.includes("allowed: IOControl_Fan")));
  check("allowlist: missing/empty list -> error (nothing allowed)",
    errs(mk({ service_name: "IOControl_Fan" })).some((m) => m.includes("'allowlist' is empty")));
  check("allowlist: entry without the field -> error",
    errs(mk({ allowlist: [{ svc: "x" }], service_name: "x" })).some((m) => m.includes("allowlist[0] has no 'service' field")));
  check("list param: wrong shape -> error", errs(mk({ allowlist: "IOControl_Fan", service_name: "IOControl_Fan" })).some((m) => m.includes("must be a JSON list")));
  check("object param: wrong shape -> error", errs(mk({ allowlist: [{ service: "a" }], service_name: "a", limits: [1] })).some((m) => m.includes("must be a JSON object")));
  check("object param: ok shape", errs(mk({ allowlist: [{ service: "a" }], service_name: "a", limits: { rate: 1 } })).length === 0);
  const g2 = base(); g2.blocks = [{ id: "n", type: "NamesBlock", params: { names: ["a", "b"], pick: "b" } }];
  check("allowed_from without field: list of strings ok", errs(g2).length === 0, errs(g2));
  g2.blocks[0].params.pick = "z";
  check("allowed_from without field: not in list -> error", errs(g2).some((m) => m.includes("is not in 'names'")));
  // round trip keeps structured params intact
  const g3 = mk({ allowlist: [{ service: "a", min: 0 }], service_name: "a", limits: { rate: 2 } });
  const back = G.parseGraph(G.serializeGraph(g3)).graph;
  check("structured params survive serialize/parse", JSON.stringify(back.blocks[0].params) === JSON.stringify(g3.blocks[0].params));
  // checkCatalog guards
  const badRef = { blocks: [{ type: "X", family: "sink", inputs: [], outputs: [], params: [{ name: "p", type: "string", allowed_from: { param: "nope" } }] }] };
  check("checkCatalog: allowed_from unknown param flagged", G.checkCatalog(badRef).some((p) => p.includes("unknown param 'nope'")));
  const badType = { blocks: [{ type: "X", family: "sink", inputs: [], outputs: [], params: [{ name: "src", type: "string" }, { name: "p", type: "string", allowed_from: { param: "src" } }] }] };
  check("checkCatalog: allowed_from non-list param flagged", G.checkCatalog(badType).some((p) => p.includes("must be a list param")));
}

// ─── generator: multi-file, annotations, enum inference, skip tests/, dup ──
{
  const { spawnSync } = require("child_process");
  const FIX = path.join(__dirname, "gen_fixture");
  const run = (args) => spawnSync(PY, [path.join(ROOT, "tools/generate_catalog.py"), ...args], { encoding: "utf-8" });
  const r = run([path.join(FIX, "uds_blocks")]);
  check("generator: package dir runs", r.status === 0, r.stderr);
  const data = r.status === 0 ? JSON.parse(r.stdout) : { blocks: [] };
  const byType = Object.fromEntries(data.blocks.map((b) => [b.type, b]));
  const param = (t, n) => (byType[t]?.params || []).find((p) => p.name === n);
  check("generator: merges both files, skips tests/", Object.keys(byType).sort().join(",") === "UdsDecodeBlock,UdsRoutineTriggerBlock,UdsWriteSinkBlock", Object.keys(byType));
  check("generator: annotation device_ref", param("UdsWriteSinkBlock", "request_service")?.type === "device_ref");
  check("generator: annotation signal_ref", param("UdsRoutineTriggerBlock", "routine_name")?.type === "signal_ref");
  check("generator: annotation enum a|b|c", JSON.stringify(param("UdsWriteSinkBlock", "priority")?.choices) === JSON.stringify(["high", "mid", "low"]));
  check("generator: inferred enum from `in (...)` on self attr", JSON.stringify(param("UdsWriteSinkBlock", "trigger")?.choices) === JSON.stringify(["on_change", "every_write", "edge"]));
  check("generator: inferred enum from step()-level check", JSON.stringify(param("UdsDecodeBlock", "on_nrc")?.choices) === JSON.stringify(["none", "hold"]));
  check("generator: int() wrapper still typed", param("UdsRoutineTriggerBlock", "retries")?.type === "int");
  check("generator: list inferred from get(k, [])", param("UdsWriteSinkBlock", "allowlist")?.type === "list");
  check("generator: object inferred from dict(get(k, {}))", param("UdsWriteSinkBlock", "limits")?.type === "object");
  check("generator: allowed_from annotation", JSON.stringify(param("UdsWriteSinkBlock", "service_name")?.allowed_from) === JSON.stringify({ param: "allowlist", field: "service" }));
  check("generator: allowed_from keeps the param's own type", param("UdsWriteSinkBlock", "service_name")?.type === "string");
  check("generator: generated_from is a list for >1 file", Array.isArray(data.generated_from) && data.generated_from.length === 2);
  check("generator: output passes checkCatalog", G.checkCatalog(data).length === 0, G.checkCatalog(data));
  const dup = run([path.join(FIX, "uds_blocks"), path.join(FIX, "dup")]);
  check("generator: duplicate type across inputs -> error", dup.status !== 0 && /registered twice/.test(dup.stderr), dup.stderr);
}

// ─── Phase E: scaffold → python parses → generator reads it back ──────
{
  const { spawnSync } = require("child_process");
  vm.runInContext(fs.readFileSync(path.join(ROOT, "app/library.js"), "utf-8"), ctx, { filename: "app/library.js" });
  const L = vm.runInContext("({ buildBlockSkeleton, buildPackageFiles, buildBlocksModule })", ctx);
  const spec = {
    typeName: "UdsPeriodicSourceBlock", doc: "Extracts one PDX parameter from XTS 0x2A frames.",
    inputs: [], outputs: ["out", "last_nrc", "age_s", "update_count"],
    params: [
      { name: "gateway", type: "device_ref", required: true },
      { name: "periodic_id", type: "int", required: true },
      { name: "parameter", type: "string", required: true, allowedFrom: "allowlist.parameter" },
      { name: "allowlist", type: "list", required: false },
      { name: "scale", type: "float", required: false, default: "0.001" },
      { name: "on_nrc", type: "enum", required: false, default: "none", choices: ["none", "hold"] },
      { name: "limits", type: "object", required: false },
      { name: "verbose", type: "bool", required: false, default: "false" },
    ],
  };
  const fnSpec = { typeName: "GainBlock", doc: "out = in * gain", inputs: ["in"], outputs: ["out"],
                   params: [{ name: "gain", type: "float", required: true }] };
  const skel = L.buildBlockSkeleton(spec);
  check("scaffold: register_block + class", skel.includes('@register_block("UdsPeriodicSourceBlock")') && skel.includes("class UdsPeriodicSourceBlock(Block):"));
  check("scaffold: device_ref hint + ctx.device_adapters in build", skel.includes("# graph-studio: device_ref") && skel.includes('ctx.device_adapters[cfg.params["gateway"]]'));
  check("scaffold: enum guard emitted", skel.includes('if self.on_nrc not in ("none", "hold"):'));
  check("scaffold: allowed_from hint", skel.includes("# graph-studio: allowed_from allowlist.parameter"));
  check("scaffold: source block gets start/stop", skel.includes("async def start(self)") && skel.includes("async def stop(self)"));
  // device-backed source → full push shape (subscribe, callback, state, reporting step)
  const push = L.buildBlockSkeleton(spec, { pkgName: "uds_blocks", layout: true });
  check("scaffold: push-source subscribes in start via the device port", push.includes("self._unsubscribe = await self._gateway.subscribe(self._subscribe_key(), self._on_response)"));
  check("scaffold: push-source has _on_response(r: UdsBlocksResponse) + state fields",
    push.includes("def _on_response(self, r: UdsBlocksResponse) -> None:") && push.includes("self._last: Value = None") && push.includes("self._rx_ts: float | None = None") && push.includes("self._count = 0"));
  check("scaffold: push-source step reports the value and computes age", push.includes("age = (time.time() - self._rx_ts)") && push.includes('"out": self._last'));
  check("scaffold: layout off → plain TODO source skeleton", !L.buildBlockSkeleton(spec, { pkgName: "uds_blocks", layout: false }).includes("_on_response"));
  const mod = L.buildBlocksModule({ pkgName: "uds_blocks", specs: [spec], header: false, layout: true });
  check("scaffold: module imports time + port types for push-source blocks", mod.includes("import time") && mod.includes("from uds_blocks.ports.uds_blocks_port import UdsBlocksPort, UdsBlocksResponse"));
  check("scaffold: function-only module has no port import", !L.buildBlocksModule({ pkgName: "fn", specs: [fnSpec], header: false, layout: true }).includes("ports.fn_port"));
  const fnSkel = L.buildBlockSkeleton(fnSpec);
  check("scaffold: function block reads inputs + None guard (keyword-safe local)", fnSkel.includes('in_, = inputs.get("in")') && fnSkel.includes("if in_ is None:"));

  const OUT = path.join(__dirname, "scaffold_out");
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const files = L.buildPackageFiles({ pkgName: "uds_blocks", specs: [spec, fnSpec], header: true, author: "Test Author (DEPT)", description: "UDS blocks." });
  for (const f of files) { const full = path.join(OUT, f.rel); fs.mkdirSync(path.dirname(full), { recursive: true }); fs.writeFileSync(full, f.content, "utf-8"); }
  check("scaffold: package file set incl. hexagonal layout (one adapter per device kind)", files.map((f) => f.rel).sort().join(",") ===
    "uds_blocks/README.md,uds_blocks/__init__.py,uds_blocks/adapters/__init__.py,uds_blocks/adapters/gateway_grpc.py,uds_blocks/adapters/mock.py,uds_blocks/adapters/registry.py,uds_blocks/blocks.py,uds_blocks/ports/__init__.py,uds_blocks/ports/uds_blocks_port.py,uds_blocks/tests/__init__.py,uds_blocks/tests/test_blocks.py",
    files.map((f) => f.rel).sort());
  check("scaffold: layout off → only the five base files", L.buildPackageFiles({ pkgName: "x", specs: [spec], layout: false }).length === 5);
  check("scaffold: __init__ imports the registry (hook #2)", files.find((f) => f.rel === "uds_blocks/__init__.py").content.includes("from uds_blocks.adapters import registry"));
  const reg = files.find((f) => f.rel.endsWith("registry.py")).content;
  check("scaffold: registry maps kind → per-kind adapter class", reg.includes('"uds_blocks.gateway": GrpcGatewayAdapter') && reg.includes("from uds_blocks.adapters.gateway_grpc import GrpcGatewayAdapter"));
  check("scaffold: registry exposes MOCK_ADAPTER (local runner convention)", reg.includes("MOCK_ADAPTER = MockUdsBlocksAdapter"));
  check("scaffold: per-kind adapter class named after the param", files.find((f) => f.rel.endsWith("gateway_grpc.py")).content.includes("class GrpcGatewayAdapter:"));
  const two = L.buildPackageFiles({ pkgName: "uds_blocks", specs: [spec, { typeName: "UdsDidSourceBlock", inputs: [], outputs: ["out"], params: [{ name: "request_service", type: "device_ref", required: true }] }], layout: true });
  check("scaffold: two device kinds → two adapter files + two registry entries",
    two.some((f) => f.rel === "uds_blocks/adapters/request_service_grpc.py") && two.some((f) => f.rel === "uds_blocks/adapters/gateway_grpc.py")
    && two.find((f) => f.rel.endsWith("registry.py")).content.includes('"uds_blocks.request_service": GrpcRequestServiceAdapter'));
  check("scaffold: no device params → single grpc_client.py", L.buildPackageFiles({ pkgName: "fn", specs: [fnSpec], layout: true }).some((f) => f.rel === "fn/adapters/grpc_client.py"));
  check("scaffold: port named after the package", files.find((f) => f.rel.endsWith("uds_blocks_port.py")).content.includes("class UdsBlocksPort(Protocol)"));
  check("scaffold: test stub injects the mock adapter", files.find((f) => f.rel.endsWith("test_blocks.py")).content.includes('MockUdsBlocksAdapter("dev0")'));
  check("scaffold: Bosch header present", files.find((f) => f.rel.endsWith("blocks.py")).content.startsWith("#  Copyright 2020-"));
  for (const rel of ["uds_blocks/blocks.py", "uds_blocks/tests/test_blocks.py", "uds_blocks/ports/uds_blocks_port.py",
                     "uds_blocks/adapters/mock.py", "uds_blocks/adapters/gateway_grpc.py", "uds_blocks/adapters/registry.py"]) {
    const r = spawnSync(PY, ["-c", `import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())`, path.join(OUT, rel)], { encoding: "utf-8" });
    check(`scaffold: ${rel} is valid Python`, r.status === 0, r.stderr);
  }
  const g = spawnSync(PY, [path.join(ROOT, "tools/generate_catalog.py"), path.join(OUT, "uds_blocks")], { encoding: "utf-8" });
  check("scaffold→generator: runs on the scaffolded package", g.status === 0, g.stderr);
  const cat = g.status === 0 ? JSON.parse(g.stdout) : { blocks: [] };
  const by = Object.fromEntries(cat.blocks.map((b) => [b.type, b]));
  const P = (t, n) => (by[t]?.params || []).find((p) => p.name === n);
  check("scaffold→generator: both types, tests/ skipped", Object.keys(by).sort().join(",") === "GainBlock,UdsPeriodicSourceBlock", Object.keys(by));
  check("scaffold→generator: families", by.UdsPeriodicSourceBlock?.family === "source" && by.GainBlock?.family === "function");
  check("scaffold→generator: device_ref round-trips", P("UdsPeriodicSourceBlock", "gateway")?.type === "device_ref");
  check("scaffold→generator: int required", P("UdsPeriodicSourceBlock", "periodic_id")?.type === "int" && P("UdsPeriodicSourceBlock", "periodic_id")?.required === true);
  check("scaffold→generator: enum choices round-trip", JSON.stringify(P("UdsPeriodicSourceBlock", "on_nrc")?.choices) === JSON.stringify(["none", "hold"]));
  check("scaffold→generator: list/object/bool/float types", P("UdsPeriodicSourceBlock", "allowlist")?.type === "list" && P("UdsPeriodicSourceBlock", "limits")?.type === "object" && P("UdsPeriodicSourceBlock", "verbose")?.type === "bool" && P("UdsPeriodicSourceBlock", "scale")?.type === "float");
  check("scaffold→generator: allowed_from round-trips", JSON.stringify(P("UdsPeriodicSourceBlock", "parameter")?.allowed_from) === JSON.stringify({ param: "allowlist", field: "parameter" }));
  check("scaffold→generator: outputs", (by.UdsPeriodicSourceBlock?.outputs || []).map((o) => o.name).join(",") === "out,last_nrc,age_s,update_count");
  check("scaffold→generator: catalog passes checkCatalog", G.checkCatalog(cat).length === 0, G.checkCatalog(cat));
}

// ─── Chart drawer: strip geometry + the markup it needs ───────────────
// editor.js can't be loaded here (it touches the DOM at top level), so the
// pure geometry helper is lifted out of the source and exercised directly.
{
  const src = fs.readFileSync(path.join(ROOT, "app/editor.js"), "utf-8");
  const html = fs.readFileSync(path.join(ROOT, "app/index.html"), "utf-8");
  const css = fs.readFileSync(path.join(ROOT, "app/style.css"), "utf-8");
  const start = src.indexOf("function chartGeometry(");
  const body = src.slice(start, src.indexOf("\n}\n", start) + 3);
  check("chart: chartGeometry is a pure, liftable helper", start > 0 && !/document|window/.test(body), body.slice(0, 120));
  const geo = new Function(body + "\nreturn chartGeometry;")();
  const fits = geo(3, 300, 48);
  check("chart: few signals fill the visible area, no scroll", fits.rowH === 100 && fits.canvasH === 300 && fits.scrolls === false, fits);
  const many = geo(12, 300, 48);
  check("chart: many signals keep the min row height and scroll", many.rowH === 48 && many.canvasH === 576 && many.scrolls === true, many);
  check("chart: compact rows fit more before scrolling", geo(8, 300, 36).rowH === 37 && geo(8, 300, 36).scrolls === false, geo(8, 300, 36));
  check("chart: tall rows scroll sooner", geo(5, 300, 72).rowH === 72 && geo(5, 300, 72).scrolls === true, geo(5, 300, 72));
  check("chart: zero/one signal never divides by zero", geo(0, 300, 48).rowH === 300 && geo(1, 0, 48).rowH === 48, [geo(0, 300, 48), geo(1, 0, 48)]);
  check("chart: absent row height falls back to the default, tiny ones hit the 24px floor",
    geo(40, 300, 0).rowH === 48 && geo(40, 300, undefined).rowH === 48 && geo(40, 300, 10).rowH === 24,
    [geo(40, 300, 0).rowH, geo(40, 300, 10).rowH]);
  check("chart: markup has the scroller, its own axis canvas and the rows control",
    /id="chart-scroll"/.test(html) && /id="chart-axis"/.test(html) && /id="chart-rowh"/.test(html) && /id="logdrawer-resize"/.test(html));
  check("chart: scroller scrolls vertically only", /#chart-scroll\s*\{[^}]*overflow-y:\s*auto[^}]*\}/.test(css) && /#chart-scroll\s*\{[^}]*overflow-x:\s*hidden/.test(css));
  check("chart: axis canvas is outside the scroller", html.indexOf('id="chart-axis"') > html.indexOf("</div>", html.indexOf('id="chart-scroll"')));
  check("chart: collapsed drawer overrides the resizer's inline height",
    /#logdrawer\.collapsed\s*\{[^}]*height:\s*32px\s*!important/.test(css));
  check("chart: the strip cap is 32, not 8", /const MAX_STRIPS = 32;/.test(src) && !/\.slice\(0, 8\)/.test(src));
  check("chart: drawer height is persisted and resettable", /localStorage\.setItem\("gs-drawer-h"/.test(src) && /localStorage\.removeItem\("gs-drawer-h"/.test(src));
}

console.log(failures === 0 ? "\nALL TESTS PASSED" : `\n${failures} FAILURES`);
process.exit(failures === 0 ? 0 : 1);
