// Library tools — Phase E: (1) scaffold a block package / block class with the
// catalog hints already in place, (2) regenerate the catalog from the GUI and
// hot-reload the palette. Pure string builders on top (headless-testable),
// DOM wiring at the bottom (guarded, so the harness can load this file in a vm).
"use strict";

/* ============================ skeleton builders ============================ */

const PARAM_TYPES = ["string", "int", "float", "bool", "enum", "list", "object", "device_ref", "signal_ref"];

function pyStr(s) { return JSON.stringify(String(s)); }
const PY_KEYWORDS = new Set(["False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue",
  "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda",
  "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield", "match", "case"]);
function pyIdent(s) {
  const id = String(s).replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1");
  return PY_KEYWORDS.has(id) ? id + "_" : id;   // a port called "in" becomes the local `in_`
}
function pyTuple(names) { return names.length ? `(${names.map(pyStr).join(", ")}${names.length === 1 ? "," : ""})` : "()"; }

function pyDefault(p) {
  const d = p.default;
  switch (p.type) {
    case "int": return Number.isFinite(parseInt(d, 10)) ? String(parseInt(d, 10)) : "0";
    case "float": { const f = parseFloat(d); return Number.isFinite(f) ? (Number.isInteger(f) ? f.toFixed(1) : String(f)) : "0.0"; }
    case "bool": return String(d).toLowerCase() === "true" ? "True" : "False";
    case "list": return "[]";
    case "object": return "{}";
    case "enum": return pyStr(d || (p.choices || [])[0] || "");
    default: return pyStr(d ?? "");
  }
}

// One `self.x = params[...]` line per param, with the graph-studio hints the
// catalog generator reads (device_ref / enum / allowed_from …).
function paramLines(p) {
  const key = pyStr(p.name);
  const attr = pyIdent(p.name);
  const hints = [];
  if (p.type === "device_ref") hints.push("device_ref");
  if (p.type === "signal_ref") hints.push("signal_ref");
  if (p.allowedFrom) hints.push(`allowed_from ${p.allowedFrom}`);
  const hint = hints.length ? `  # graph-studio: ${hints.join("; ")}` : "";
  const get = (wrap) => p.required
    ? (wrap ? `${wrap}(params[${key}])` : `params[${key}]`)
    : (wrap ? `${wrap}(params.get(${key}, ${pyDefault(p)}))` : `params.get(${key}, ${pyDefault(p)})`);
  const lines = [];
  switch (p.type) {
    case "int": lines.push(`        self.${attr} = ${get("int")}${hint}`); break;
    case "float": lines.push(`        self.${attr} = ${get("float")}${hint}`); break;
    case "bool": lines.push(`        self.${attr} = ${get("bool")}${hint}`); break;
    case "list": lines.push(`        self.${attr} = list(${get()})${hint}`); break;
    case "object": lines.push(`        self.${attr} = dict(${get()})${hint}`); break;
    case "enum": {
      const choices = (p.choices || []).length ? p.choices : ["a", "b"];
      lines.push(`        self.${attr} = ${get()}${hint}`);
      lines.push(`        if self.${attr} not in ${pyTuple(choices)}:`);
      lines.push(`            raise ValueError(f"${p.name} must be one of ${choices.join("|")} (got {self.${attr}!r})")`);
      break;
    }
    case "device_ref":
      // the adapter itself is injected by build(); keep the logical name for logs
      lines.push(`        self.${attr}_name = ${get()}${hint}`);
      break;
    default: lines.push(`        self.${attr} = ${get()}${hint}`);
  }
  return lines;
}

// opts.pkgName (+ opts.layout) lets a device-backed SOURCE block get the full
// push shape: subscribe in start(), store in _on_response(), report in step().
function buildBlockSkeleton(spec, opts) {
  opts = opts || {};
  const type = pyIdent(spec.typeName || "MyBlock");
  const inputs = (spec.inputs || []).filter(Boolean);
  const outputs = (spec.outputs || []).filter(Boolean);
  const params = (spec.params || []).filter((p) => p && p.name);
  const devices = params.filter((p) => p.type === "device_ref");
  const doc = (spec.doc || `TODO: one line — what this block computes.`).replace(/"""/g, "'''");
  const ctorArgs = devices.map((d) => `, ${pyIdent(d.name)}`).join("");
  // a source block fed by a device adapter → subscription + callback + state
  const pushSource = !inputs.length && devices.length > 0 && opts.layout !== false;
  const P = camel(opts.pkgName || "my_blocks");
  const dev0 = pushSource ? pyIdent(devices[0].name) : null;

  const L = [];
  L.push(`@register_block(${pyStr(type)})`);
  L.push(`class ${type}(Block):`);
  L.push(`    """${doc}"""`);
  L.push(``);
  if (inputs.length) L.push(`    inputs = ${pyTuple(inputs)}`);
  if (outputs.length) L.push(`    outputs = ${pyTuple(outputs)}`);
  if (inputs.length || outputs.length) L.push(``);
  L.push(`    def __init__(self, block_id: str, params: dict${ctorArgs}) -> None:`);
  L.push(`        super().__init__(block_id, params)`);
  for (const d of devices) L.push(`        self._${pyIdent(d.name)}${pushSource ? `: ${P}Port` : ""} = ${pyIdent(d.name)}`);
  for (const p of params) L.push(...paramLines(p));
  if (outputs.length) L.push(`        self.units[${pyStr(outputs[0])}] = params.get("unit", "")`);
  if (!params.length && !outputs.length) L.push(`        # no params`);
  if (pushSource) {
    L.push(`        # --- state written by _on_response(), read by step() (same asyncio loop: no lock) ---`);
    L.push(`        self._last: Value = None          # latest accepted value, None until the first good response`);
    L.push(`        self._rx_ts: float | None = None  # when it arrived (unix s) → age in step()`);
    L.push(`        self._status = 0                  # last status code (0 = ok)`);
    L.push(`        self._count = 0                   # good responses so far`);
    L.push(`        self._unsubscribe = None`);
  }
  L.push(``);
  L.push(`    @classmethod`);
  L.push(`    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "${type}":`);
  for (const d of devices) {
    L.push(`        ${pyIdent(d.name)} = ctx.device_adapters[cfg.params[${pyStr(d.name)}]]  # graph-studio: device_ref`);
  }
  L.push(`        return cls(cfg.id, cfg.params${devices.map((d) => `, ${pyIdent(d.name)}`).join("")})`);
  L.push(``);
  if (pushSource) {
    L.push(`    def _subscribe_key(self) -> str:`);
    L.push(`        """The port key this block listens to (see the key convention in ports/${pyIdent(opts.pkgName || "my_blocks")}_port.py)."""`);
    L.push(`        return "TODO:key"  # e.g. f"periodic:{self.periodic_id}" or f"service:{self.service_name}"`);
    L.push(``);
    L.push(`    async def start(self) -> None:`);
    L.push(`        self._unsubscribe = await self._${dev0}.subscribe(self._subscribe_key(), self._on_response)`);
    L.push(``);
    L.push(`    async def stop(self) -> None:`);
    L.push(`        if self._unsubscribe:`);
    L.push(`            self._unsubscribe()`);
    L.push(`            self._unsubscribe = None`);
    L.push(``);
    L.push(`    def _on_response(self, r: ${P}Response) -> None:`);
    L.push(`        """Store only — called by the adapter whenever a response for our key arrives."""`);
    L.push(`        self._status = r.status`);
    L.push(`        self._rx_ts = r.timestamp`);
    L.push(`        if r.status != 0:`);
    L.push(`            # TODO: negative response policy (keep the last value? clear it?)`);
    L.push(`            return`);
    L.push(`        # TODO: pick the value this block publishes out of r.values (and scale it)`);
    L.push(`        self._last = None`);
    L.push(`        self._count += 1`);
    L.push(``);
    L.push(`    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:`);
    L.push(`        """Report — the engine calls this every tick; a consumer reads staleness from the age."""`);
    L.push(`        age = (time.time() - self._rx_ts) if self._rx_ts is not None else None`);
    L.push(`        # TODO: map state → outputs (first output = the value; add status/age/count ports as needed)`);
    L.push(`        return {${outputs.map((o, i) => `${pyStr(o)}: ${i === 0 ? "self._last" : "None"}`).join(", ")}}  # age=age, status=self._status, count=self._count`);
    return L.join("\n") + "\n";
  }
  if (!inputs.length) {
    L.push(`    async def start(self) -> None:`);
    L.push(`        # TODO: open subscriptions / background tasks that feed this source`);
    L.push(`        pass`);
    L.push(``);
    L.push(`    async def stop(self) -> None:`);
    L.push(`        # TODO: cancel what start() opened`);
    L.push(`        pass`);
    L.push(``);
  }
  L.push(`    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:`);
  if (inputs.length) {
    L.push(`        ${inputs.map((i) => pyIdent(i)).join(", ")}${inputs.length === 1 ? "," : ""} = ${inputs.map((i) => `inputs.get(${pyStr(i)})`).join(", ")}`);
    L.push(`        if ${inputs.map((i) => `${pyIdent(i)} is None`).join(" or ")}:`);
    L.push(`            return {${outputs.map((o) => `${pyStr(o)}: None`).join(", ")}}  # no sample this cycle`);
  }
  L.push(`        # TODO: implement`);
  L.push(`        return {${outputs.map((o) => `${pyStr(o)}: None`).join(", ")}}`);
  return L.join("\n") + "\n";
}

function boschHeader(fileName, description, author, when) {
  const d = when || new Date();
  const month = d.toLocaleString("en-US", { month: "long" });
  const dd = String(d.getDate()).padStart(2, "0"), mm = String(d.getMonth() + 1).padStart(2, "0");
  return [
    `#  Copyright 2020-${d.getFullYear()} Robert Bosch GmbH`,
    `#`,
    `#  Licensed under the Apache License, Version 2.0 (the "License");`,
    `#  you may not use this file except in compliance with the License.`,
    `#  You may obtain a copy of the License at`,
    `#`,
    `#      http://www.apache.org/licenses/LICENSE-2.0`,
    `#`,
    `#  Unless required by applicable law or agreed to in writing, software`,
    `#  distributed under the License is distributed on an "AS IS" BASIS,`,
    `#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.`,
    `#  See the License for the specific language governing permissions and`,
    `#  limitations under the License.`,
    `# *******************************************************************************`,
    `#`,
    `# File: ${fileName}`,
    `#`,
    `# Initially created by ${author} / ${month} ${d.getFullYear()}.`,
    `#`,
    `# Description:`,
    `#   ${description}`,
    `#`,
    `# History:`,
    `#`,
    `# ${dd}.${mm}.${d.getFullYear()} / V 1.0.0 / ${author}`,
    `# - Initial version (story #TODO — TODO-slug).`,
    `#`,
    `# *******************************************************************************`,
    ``,
  ].join("\n");
}

const MODULE_IMPORTS = [
  `from __future__ import annotations`,
  ``,
  `import logging`,
  ``,
  `from signal_graph.core.domain.blocks import Block, BuildContext, Value, register_block`,
  `from signal_graph.core.domain.graph_config import BlockConfig`,
  ``,
  `logger = logging.getLogger(__name__)`,
  ``,
].join("\n");

// Extra imports a device-backed source block needs (the port types + time for age).
function portImports(opts) {
  const pkg = pyIdent(opts.pkgName || "my_blocks");
  const P = camel(pkg);
  return [`import time`, ``, `from ${pkg}.ports.${pkg}_port import ${P}Port, ${P}Response`, ``];
}
function needsPortImports(opts) {
  return opts.layout !== false && (opts.specs || []).some((s) => !(s.inputs || []).filter(Boolean).length && (s.params || []).some((p) => p && p.type === "device_ref"));
}

function buildBlocksModule(opts) {
  // opts: { pkgName, specs[], header:bool, author, description, layout }
  const author = opts.author || "TODO Author (DEPT)";
  const head = opts.header ? boschHeader("blocks.py", opts.description || `${opts.pkgName} block library.`, author) : "";
  const doc = `"""${opts.description || `Blocks of the ${opts.pkgName} package.`}\n\nLoaded into a \`\`signal_graph\`\` instance via \`\`"block_modules": ["${opts.pkgName}.blocks"]\`\`.\n"""\n\n`;
  let imports = MODULE_IMPORTS;
  if (needsPortImports(opts)) {
    // insert after `import logging` (stdlib group) and before the signal_graph imports
    imports = imports.replace("import logging\n\n", "import logging\nimport time\n\n")
                     .replace("logger = logging.getLogger(__name__)", portImports(opts).slice(2, 3).join("") + "\n\nlogger = logging.getLogger(__name__)");
  }
  return head + doc + imports + "\n\n" + opts.specs.map((s) => buildBlockSkeleton(s, opts)).join("\n\n");
}

function buildTestsModule(opts) {
  const author = opts.author || "TODO Author (DEPT)";
  const head = opts.header ? boschHeader("test_blocks.py", `Unit tests for ${opts.pkgName} blocks.`, author) : "";
  const layout = opts.layout !== false;
  const P = camel(opts.pkgName);
  const L = [head, `"""Unit tests for ${opts.pkgName} blocks (engine-free: blocks are plain classes)."""`, ``,
    `from __future__ import annotations`, ``, `import pytest`, ``,
    ...(layout ? [`from ${opts.pkgName}.adapters.mock import Mock${P}Adapter`] : []),
    `from ${opts.pkgName}.blocks import ${opts.specs.map((s) => pyIdent(s.typeName)).join(", ")}`, ``, ``];
  const deviceArg = layout ? `Mock${P}Adapter("dev0")` : "object()";
  for (const s of opts.specs) {
    const type = pyIdent(s.typeName);
    const params = (s.params || []).filter((p) => p && p.name);
    const devices = params.filter((p) => p.type === "device_ref");
    const req = params.filter((p) => p.required && p.type !== "device_ref");
    const example = (p) => {
      switch (p.type) {
        case "int": return "1"; case "float": return "1.0"; case "bool": return "True";
        case "list": return "[]"; case "object": return "{}";
        case "enum": return pyStr((p.choices || ["a"])[0]);
        default: return pyStr(`${p.name}_value`);
      }
    };
    const paramsPy = `{${[...devices.map((d) => `${pyStr(d.name)}: "dev0"`), ...req.map((p) => `${pyStr(p.name)}: ${example(p)}`)].join(", ")}}`;
    L.push(`@pytest.mark.asyncio`);
    L.push(`async def test_${pyIdent(s.typeName).toLowerCase()}_step_returns_all_outputs():`);
    L.push(`    block = ${type}("b1", ${paramsPy}${devices.map(() => `, ${deviceArg}`).join("")})`);
    L.push(`    out = await block.step({${(s.inputs || []).filter(Boolean).map((i) => `${pyStr(i)}: 1.0`).join(", ")}})`);
    const outs = (s.outputs || []).filter(Boolean);
    L.push(`    assert set(out) == ${outs.length ? `{${outs.map(pyStr).join(", ")}}` : "set()"}`);
    L.push(`    # TODO: assert the actual computation once step() is implemented`);
    L.push(``, ``);
  }
  return L.join("\n");
}

function buildPackageReadme(opts) {
  return [
    `# ${opts.pkgName}`, ``,
    opts.description || `Block package for the \`signal_graph\` service.`, ``,
    `## Use in a graph`, ``, "```json",
    `"block_modules": ["${opts.pkgName}.blocks"]`, "```", ``,
    `Block types: ${opts.specs.map((s) => "`" + pyIdent(s.typeName) + "`").join(", ")}.`, ``,
    `## Keep the palette in sync`, ``,
    `Regenerate the block catalog after every change to \`blocks.py\` (the \`# graph-studio:\` hints`,
    `next to the params tell the generator about device references, enums and allowlists).`, ``,
  ].join("\n");
}

/* ---- hexagonal layout: ports/ + adapters/ skeletons ---- */

function camel(s) { return pyIdent(s).split("_").filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(""); }
function deviceParams(specs) {
  const seen = new Set();
  const out = [];
  for (const s of specs) for (const p of (s.params || [])) {
    if (p && p.type === "device_ref" && p.name && !seen.has(p.name)) { seen.add(p.name); out.push(p.name); }
  }
  return out;
}

// ports/<pkg>_port.py — the ONE thing a block may depend on besides the library.
function buildPortModule(opts) {
  const pkg = opts.pkgName, P = camel(pkg);
  const head = opts.header ? boschHeader(`${pkg}_port.py`, `Driven port of the ${pkg} blocks (what a block needs from the outside).`, opts.author || "TODO Author (DEPT)") : "";
  return head + [
    `"""`,
    `Driven port of the ${pkg} blocks.`,
    ``,
    `Blocks receive DECODED values through this port — never bytes, never a`,
    `client stub. Which protocol/codec produces them is the adapter's business`,
    `(adapters/grpc_client.py for the bench, adapters/mock.py for tests and`,
    `local runs). Keep this file free of I/O imports.`,
    `"""`,
    ``,
    `from __future__ import annotations`,
    ``,
    `from dataclasses import dataclass`,
    `from typing import Awaitable, Callable, Mapping, Protocol`,
    ``,
    ``,
    `@dataclass(frozen=True)`,
    `class ${P}Response:`,
    `    """One decoded answer: parameter name -> number, a status code (0 = ok), receive time."""`,
    ``,
    `    values: Mapping[str, float]`,
    `    status: int`,
    `    timestamp: float  # unix seconds, stamped when the data arrived`,
    ``,
    ``,
    `ResponseCallback = Callable[[${P}Response], Awaitable[None] | None]`,
    `Unsubscribe = Callable[[], None]`,
    ``,
    ``,
    `class ${P}Port(Protocol):`,
    `    """What a ${pkg} block may ask of the outside world."""`,
    ``,
    `    async def connect(self) -> None:`,
    `        """Open the underlying connection (called once by signal_graph at start-up)."""`,
    ``,
    `    async def close(self) -> None:`,
    `        """Release the connection (called once at shutdown)."""`,
    ``,
    `    async def subscribe(self, key: str, callback: ResponseCallback) -> Unsubscribe:`,
    `        """`,
    `Deliver every response matching \`key\` to \`callback\`; returns the unsubscribe function.`,
    ``,
    `\`key\` is protocol-specific (a periodic identifier, a service name, a DID ...);`,
    `the block decides which key it needs from its params. TODO: narrow the`,
    `signature if one key kind is enough for this package.`,
    `        """`,
    ``,
  ].join("\n");
}

// adapters/mock.py — same port, no network; drives tests and ▶ Run graph.
function buildMockAdapter(opts) {
  const pkg = opts.pkgName, P = camel(pkg);
  const head = opts.header ? boschHeader("mock.py", `In-memory ${P}Port for tests and local runs.`, opts.author || "TODO Author (DEPT)") : "";
  return head + [
    `"""In-memory \`\`${P}Port\`\`: replays a script, or is pushed from a test."""`,
    ``,
    `from __future__ import annotations`,
    ``,
    `import asyncio`,
    `import time`,
    `from collections import defaultdict`,
    ``,
    `from ${pkg}.ports.${pkg}_port import ${P}Response, ResponseCallback, Unsubscribe`,
    ``,
    ``,
    `class Mock${P}Adapter:`,
    `    """Replays \`script\` = [(key, {param: value}, status), ...] every \`period_s\`; tests call push() directly."""`,
    ``,
    `    def __init__(self, name: str, script=None, period_s: float = 0.5) -> None:`,
    `        self.name = name`,
    `        self._script = list(script or [])   # TODO: a realistic default script for demos`,
    `        self._period = period_s`,
    `        self._subs: dict[str, list[ResponseCallback]] = defaultdict(list)`,
    `        self._task: asyncio.Task | None = None`,
    ``,
    `    async def connect(self) -> None:`,
    `        pass`,
    ``,
    `    async def close(self) -> None:`,
    `        if self._task:`,
    `            self._task.cancel()`,
    `            self._task = None`,
    ``,
    `    async def subscribe(self, key: str, callback: ResponseCallback) -> Unsubscribe:`,
    `        self._subs[key].append(callback)`,
    `        if self._script and self._task is None:`,
    `            self._task = asyncio.create_task(self._replay())`,
    `        return lambda: self._subs[key].remove(callback)`,
    ``,
    `    async def push(self, key: str, values: dict, status: int = 0) -> None:`,
    `        """Deliver one response now — deterministic, no timing (use this in tests)."""`,
    `        response = ${P}Response(values=values, status=status, timestamp=time.time())`,
    `        for callback in list(self._subs.get(key, [])):`,
    `            result = callback(response)`,
    `            if asyncio.iscoroutine(result):`,
    `                await result`,
    ``,
    `    async def _replay(self) -> None:`,
    `        while True:`,
    `            for key, values, status in self._script:`,
    `                await self.push(key, values, status)`,
    `                await asyncio.sleep(self._period)`,
    ``,
  ].join("\n");
}

// adapters/<param>_grpc.py — one bench adapter per device_ref kind (e.g.
// gateway_grpc.py → GrpcGatewayAdapter for kind "<pkg>.gateway"); transport
// specifics are TODOs. With no device_ref param at all: grpc_client.py.
function adapterFileFor(param) { return param ? `${pyIdent(param)}_grpc.py` : "grpc_client.py"; }
function adapterClassFor(opts, param) { return param ? `Grpc${camel(param)}Adapter` : `Grpc${camel(opts.pkgName)}Adapter`; }

function buildGrpcAdapter(opts, param) {
  const pkg = opts.pkgName, P = camel(pkg);
  const cls = adapterClassFor(opts, param);
  const file = adapterFileFor(param);
  const kind = param ? `${pkg}.${pyIdent(param)}` : `${pkg}.default`;
  const head = opts.header ? boschHeader(file, `gRPC ${P}Port adapter for device kind "${kind}" (bench).`, opts.author || "TODO Author (DEPT)") : "";
  return head + [
    `"""gRPC \`\`${P}Port\`\` adapter behind device kind \`\`${kind}\`\`: one stream/connection per graph service, fan-out to the blocks."""`,
    ``,
    `from __future__ import annotations`,
    ``,
    `import asyncio`,
    `import logging`,
    `from collections import defaultdict`,
    ``,
    `from ${pkg}.ports.${pkg}_port import ${P}Response, ResponseCallback, Unsubscribe`,
    ``,
    `logger = logging.getLogger(__name__)`,
    ``,
    ``,
    `class ${cls}:`,
    `    """Resolves \`service_name\` through the registry (Consul), holds the stream, decodes once, fans out by key."""`,
    ``,
    `    def __init__(self, registry, service_name: str, settings=None) -> None:`,
    `        self._registry = registry          # signal_graph's ServiceRegistryPort (Consul / in-memory)`,
    `        self._service_name = service_name  # the Consul service from graph.json device_services`,
    `        self._settings = settings`,
    `        self._subs: dict[str, list[ResponseCallback]] = defaultdict(list)`,
    `        self._task: asyncio.Task | None = None`,
    ``,
    `    async def connect(self) -> None:`,
    `        pass  # the stream opens lazily on the first subscribe()`,
    ``,
    `    async def close(self) -> None:`,
    `        if self._task:`,
    `            self._task.cancel()`,
    `            self._task = None`,
    ``,
    `    async def subscribe(self, key: str, callback: ResponseCallback) -> Unsubscribe:`,
    `        self._subs[key].append(callback)`,
    `        if self._task is None:`,
    `            self._task = asyncio.create_task(self._pump(), name="${pkg}-pump")`,
    `        return lambda: self._subs[key].remove(callback)`,
    ``,
    `    async def _pump(self) -> None:`,
    `        """Hold the connection open; reconnect with backoff; decode once; fan out."""`,
    `        backoff = 0.5`,
    `        while True:`,
    `            try:`,
    `                host, port = await self._registry.resolve(self._service_name)  # TODO: match the registry port's API`,
    `                # TODO: open the gRPC channel/stream to host:port and iterate its messages:`,
    `                #   async for message in stream:`,
    `                #       backoff = 0.5`,
    `                #       await self._dispatch(key_of(message), decode(message), status_of(message), ts_of(message))`,
    `                raise NotImplementedError("wire the gRPC stream here")`,
    `            except asyncio.CancelledError:`,
    `                raise`,
    `            except Exception as exc:  # noqa: BLE001 — keep the pump alive across outages`,
    `                logger.warning("%s: connection lost (%s); retry in %.1fs", self._service_name, exc, backoff)`,
    `                await asyncio.sleep(backoff)`,
    `                backoff = min(backoff * 2, 5.0)`,
    ``,
    `    async def _dispatch(self, key: str, values: dict, status: int, timestamp: float) -> None:`,
    `        if not self._subs.get(key):`,
    `            return`,
    `        response = ${P}Response(values=values, status=status, timestamp=timestamp)`,
    `        for callback in list(self._subs[key]):`,
    `            result = callback(response)`,
    `            if asyncio.iscoroutine(result):`,
    `                await result`,
    ``,
  ].join("\n");
}

// adapters/registry.py — hook #2: device_services entries with these kinds get our adapters.
function buildRegistryModule(opts) {
  const pkg = opts.pkgName, P = camel(pkg);
  const kinds = deviceParams(opts.specs);
  const head = opts.header ? boschHeader("registry.py", `Adapter-kind registration for ${pkg} (signal_graph hook #2).`, opts.author || "TODO Author (DEPT)") : "";
  // one adapter class per device_ref kind; a package without device params gets one default adapter
  const entries = kinds.length
    ? kinds.map((k) => ({ kind: `${pkg}.${pyIdent(k)}`, file: pyIdent(k) + "_grpc", cls: adapterClassFor(opts, k) }))
    : [{ kind: `${pkg}.default`, file: "grpc_client", cls: adapterClassFor(opts, null) }];
  return head + [
    `"""`,
    `Adapter kinds this package provides (signal_graph hook #2).`,
    ``,
    `A \`\`device_services\`\` entry in graph.json selects the adapter by kind::`,
    ``,
    `    "device_services": {`,
    ...entries.map((e) => `        "${e.kind.split(".")[1].slice(0, 8)}_x": {"service": "<consul service>", "kind": "${e.kind}"},`),
    `    }`,
    ``,
    `A plain string entry keeps meaning the built-in device kind. Until the`,
    `hook PR is merged in signal_graph, \`\`register_adapter_factory\`\` is absent and`,
    `this module is a no-op (the import guard below). Adding a block with a new`,
    `device_ref param = one more adapter file + one more KINDS entry here.`,
    `"""`,
    ``,
    `from __future__ import annotations`,
    ``,
    ...entries.map((e) => `from ${pkg}.adapters.${e.file} import ${e.cls}`),
    `from ${pkg}.adapters.mock import Mock${P}Adapter`,
    ``,
    `try:`,
    `    from signal_graph.adapters.outbound.device import register_adapter_factory`,
    `except ImportError:  # hook not merged yet — package still imports fine`,
    `    register_adapter_factory = None`,
    ``,
    `# kind -> gRPC adapter class (the mock adapter serves every kind)`,
    `KINDS = {`,
    ...entries.map((e) => `    ${pyStr(e.kind)}: ${e.cls},`),
    `}`,
    ``,
    `# mock adapter used for every kind when the device backend is "mock"`,
    `# (local runs / tests; the local runner looks this name up by convention)`,
    `MOCK_ADAPTER = Mock${P}Adapter`,
    ``,
    ``,
    `def register() -> None:`,
    `    """Register one factory per kind; called from the package __init__."""`,
    `    if register_adapter_factory is None:`,
    `        return`,
    `    for kind, adapter_cls in KINDS.items():`,
    `        register_adapter_factory(`,
    `            kind,`,
    `            grpc=lambda registry, service_name, settings, _cls=adapter_cls: _cls(registry, service_name, settings),`,
    `            mock=lambda service_name, settings: Mock${P}Adapter(service_name),`,
    `        )`,
    ``,
    ``,
    `register()`,
    ``,
  ].join("\n");
}

// Files for a brand-new package (relative paths). Appending a block to an
// existing blocks.py is handled by write-files with mode "append". With
// opts.layout (default true) the hexagonal skeleton is included; re-running
// on an existing package only adds the missing files (create never clobbers).
function buildPackageFiles(opts) {
  const pkg = pyIdent(opts.pkgName || "my_blocks");
  const o = { ...opts, pkgName: pkg };
  const layout = opts.layout !== false;
  const init = layout
    ? `"""${pkg} — block package for signal_graph."""\n\nfrom ${pkg}.adapters import registry  # noqa: F401 — registers adapter kinds (hook #2)\n`
    : `"""${pkg} — block package for signal_graph."""\n`;
  const files = [
    { rel: `${pkg}/__init__.py`, content: init, mode: "create" },
    { rel: `${pkg}/blocks.py`, content: buildBlocksModule(o), mode: "create" },
    { rel: `${pkg}/tests/__init__.py`, content: "", mode: "create" },
    { rel: `${pkg}/tests/test_blocks.py`, content: buildTestsModule(o), mode: "create" },
    { rel: `${pkg}/README.md`, content: buildPackageReadme(o), mode: "create" },
  ];
  if (layout) {
    files.push(
      { rel: `${pkg}/ports/__init__.py`, content: `"""Ports of ${pkg}: what the blocks need from the outside (no I/O here)."""\n`, mode: "create" },
      { rel: `${pkg}/ports/${pkg}_port.py`, content: buildPortModule(o), mode: "create" },
      { rel: `${pkg}/adapters/__init__.py`, content: `"""Adapters of ${pkg}: mock (tests, local runs) and one gRPC adapter per device kind (bench)."""\n`, mode: "create" },
      { rel: `${pkg}/adapters/mock.py`, content: buildMockAdapter(o), mode: "create" },
      ...adapterFiles(o, deviceParams(o.specs)),
      { rel: `${pkg}/adapters/registry.py`, content: buildRegistryModule(o), mode: "create" },
    );
  }
  return files;
}

// One gRPC adapter file per device_ref param name (gateway → adapters/gateway_grpc.py);
// none at all → a single adapters/grpc_client.py. Also used by append mode for
// the device params a newly appended block introduces.
function adapterFiles(opts, params) {
  const pkg = pyIdent(opts.pkgName);
  const o = { ...opts, pkgName: pkg };
  if (!params.length) return [{ rel: `${pkg}/adapters/grpc_client.py`, content: buildGrpcAdapter(o, null), mode: "create" }];
  return params.map((p) => ({ rel: `${pkg}/adapters/${adapterFileFor(p)}`, content: buildGrpcAdapter(o, p), mode: "create" }));
}

/* ============================ GUI (Electron/browser) ============================ */

if (typeof document !== "undefined") {
  const LIB_KEY = "gs-library";
  const lib = { sources: [], python: "", lastRoot: "", author: "Nguyen Huynh Tri Cuong (MS/EMC51)" };
  try { Object.assign(lib, JSON.parse(localStorage.getItem(LIB_KEY) || "{}")); } catch (_e) { /* fresh */ }
  const saveLib = () => { try { localStorage.setItem(LIB_KEY, JSON.stringify(lib)); } catch (_e) { /* ignore */ } };
  const el = (tag, attrs, parent) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) { if (k === "text") n.textContent = v; else if (k === "html") n.innerHTML = v; else n.setAttribute(k, v); }
    if (parent) parent.appendChild(n);
    return n;
  };

  function openModal(title, tab) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal").classList.remove("hidden");
    for (const b of document.querySelectorAll("#modal-tabs button")) b.classList.toggle("on", b.dataset.tab === tab);
    if (tab === "catalog") renderCatalogTab(); else renderScaffoldTab();
  }
  function closeModal() { document.getElementById("modal").classList.add("hidden"); }

  /* ---- tab 1: scaffold ---- */
  const draft = {
    root: lib.lastRoot || "", pkgName: "uds_blocks", mode: "new", header: true, layout: true,
    description: "UDS extraction / embedding blocks for the signal graph service.",
    typeName: "UdsPeriodicSourceBlock", doc: "Extracts one PDX parameter from XTS 0x2A periodic frames as a scaled signal.",
    inputs: "", outputs: "out, last_nrc, age_s, update_count",
    params: [
      { name: "gateway", type: "device_ref", required: true },
      { name: "periodic_id", type: "int", required: true },
      { name: "parameter", type: "string", required: true },
      { name: "scale", type: "float", required: false, default: "1.0" },
      { name: "on_nrc", type: "enum", required: false, default: "none", choices: ["none", "hold"] },
    ],
  };
  const splitList = (s) => String(s || "").split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
  const specFromDraft = () => ({
    typeName: draft.typeName, doc: draft.doc, inputs: splitList(draft.inputs), outputs: splitList(draft.outputs),
    params: draft.params.filter((p) => p.name),
  });

  function renderScaffoldTab() {
    const body = document.getElementById("modal-body");
    body.innerHTML = "";
    const form = el("div", { class: "lib-form" }, body);
    const row = (label, node, hint) => {
      el("label", { text: label }, form);
      const cell = el("div", {}, form);
      cell.appendChild(node);
      if (hint) el("div", { class: "hint", text: hint }, cell);
      return node;
    };
    const text = (key, ph) => {
      const i = el("input", { type: "text", value: draft[key] || "", placeholder: ph || "" });
      i.addEventListener("change", () => { draft[key] = i.value.trim(); });
      return i;
    };
    // target
    const rootRow = el("div", { class: "obs-row" });
    const rootIn = el("input", { type: "text", value: draft.root, placeholder: "…\\services\\signals" }, rootRow);
    rootIn.addEventListener("change", () => { draft.root = rootIn.value.trim(); });
    const pick = el("button", { text: "…", title: "pick the parent directory" }, rootRow);
    pick.disabled = !isElectron;
    pick.addEventListener("click", async () => {
      const p = await window.bridge.pickPath({ kind: "dir", title: "Parent directory of the block package (e.g. services/signals)" });
      if (p) { draft.root = p; rootIn.value = p; }
    });
    row("parent directory", rootRow, "the package folder is created inside (new) or must already exist (append)");
    row("package name", text("pkgName", "uds_blocks"), "python package → \"block_modules\": [\"<name>.blocks\"] in graph.json");
    const mode = el("select", { html: `<option value="new">new package — create &lt;pkg&gt;/blocks.py, tests, README</option><option value="append">append — add this block to the existing &lt;pkg&gt;/blocks.py</option>` });
    mode.value = draft.mode;
    mode.addEventListener("change", () => { draft.mode = mode.value; renderScaffoldTab(); });
    row("mode", mode, draft.mode === "append"
      ? "the block below is appended to the package's blocks.py (must already exist)"
      : "first block of a new package; switch to append for the second block");
    const hdr = el("input", { type: "checkbox" }); hdr.checked = draft.header;
    hdr.addEventListener("change", () => { draft.header = hdr.checked; });
    const hdrWrap = el("div", { class: "obs-row" }); hdrWrap.appendChild(hdr);
    const authorIn = el("input", { type: "text", value: lib.author, placeholder: "Author (DEPT)" }, hdrWrap);
    authorIn.addEventListener("change", () => { lib.author = authorIn.value.trim(); saveLib(); });
    row("Bosch file header", hdrWrap, "repo convention for new files; author goes into the header");
    row("package description", text("description"));
    const lay = el("input", { type: "checkbox" }); lay.checked = draft.layout !== false;
    lay.addEventListener("change", () => { draft.layout = lay.checked; });
    const layWrap = el("div", { class: "obs-row" }); layWrap.appendChild(lay);
    el("span", { class: "hint", text: "hexagonal layout — ports/<pkg>_port.py, adapters/mock.py, adapters/grpc_client.py, adapters/registry.py (hook #2)" }, layWrap);
    row("layout", layWrap, "new package: full skeleton · re-run on an existing package: only the missing files are added");
    // block
    el("h3", { text: "block" }, form); el("div", {}, form);
    row("type name", text("typeName", "UdsPeriodicSourceBlock"), "→ @register_block(\"…\") and the class name");
    row("docstring (1 line)", text("doc"), "becomes the palette tooltip");
    row("inputs", text("inputs", "in"), "comma-separated; empty = source block");
    row("outputs", text("outputs", "out"), "comma-separated; empty = sink block");
    // params table
    el("h3", { text: "params" }, form); el("div", {}, form);
    const tbl = el("table", { class: "lib-params" }, body);
    tbl.innerHTML = `<tr><th>name</th><th>type</th><th>req</th><th>default</th><th>choices (enum) / allowed_from (param.field)</th><th></th></tr>`;
    const redraw = () => renderScaffoldTab();
    draft.params.forEach((p, idx) => {
      const tr = el("tr", {}, tbl);
      const nm = el("input", { type: "text", value: p.name }, el("td", {}, tr)); nm.addEventListener("change", () => { p.name = nm.value.trim(); });
      const ty = el("select", { html: PARAM_TYPES.map((t) => `<option${t === p.type ? " selected" : ""}>${t}</option>`).join("") }, el("td", {}, tr));
      ty.addEventListener("change", () => { p.type = ty.value; redraw(); });
      const rq = el("input", { type: "checkbox" }, el("td", {}, tr)); rq.checked = !!p.required; rq.addEventListener("change", () => { p.required = rq.checked; });
      const df = el("input", { type: "text", value: p.default ?? "" }, el("td", {}, tr)); df.disabled = !!p.required || ["device_ref", "signal_ref", "list", "object"].includes(p.type);
      df.addEventListener("change", () => { p.default = df.value.trim(); });
      const extraTd = el("td", {}, tr);
      if (p.type === "enum") {
        const ch = el("input", { type: "text", value: (p.choices || []).join("|"), placeholder: "a|b|c" }, extraTd);
        ch.addEventListener("change", () => { p.choices = ch.value.split("|").map((x) => x.trim()).filter(Boolean); });
      } else if (["string", "int", "float"].includes(p.type)) {
        const af = el("input", { type: "text", value: p.allowedFrom || "", placeholder: "allowlist.service (optional)" }, extraTd);
        af.addEventListener("change", () => { p.allowedFrom = af.value.trim(); });
      }
      const rm = el("button", { text: "✕", title: "remove" }, el("td", {}, tr));
      rm.addEventListener("click", () => { draft.params.splice(idx, 1); redraw(); });
    });
    const addBtn = el("button", { text: "+ param" }, body);
    addBtn.addEventListener("click", () => { draft.params.push({ name: "", type: "string", required: false }); redraw(); });

    // preview + actions
    el("h3", { text: "preview (blocks.py excerpt)" }, body);
    const pre = el("pre", { class: "lib-preview" }, body);
    pre.textContent = buildBlockSkeleton(specFromDraft(), { pkgName: draft.pkgName, layout: draft.layout !== false });
    const actions = el("div", { class: "lib-actions" }, body);
    const write = el("button", { class: "primary", text: draft.mode === "append" ? "Append to blocks.py" : "Create package" }, actions);
    write.disabled = !isElectron;
    write.title = isElectron ? "" : "writing files needs the Electron shell — copy the preview instead";
    const copy = el("button", { text: "Copy preview" }, actions);
    copy.addEventListener("click", () => { navigator.clipboard?.writeText(pre.textContent); toast("skeleton copied"); });
    const refresh = el("button", { text: "Refresh preview" }, actions);
    refresh.addEventListener("click", redraw);
    const out = el("div", { class: "lib-out" }, body);
    write.addEventListener("click", async () => {
      if (!draft.root) return toast("pick the parent directory first", true);
      if (!draft.pkgName) return toast("package name is required", true);
      const spec = specFromDraft();
      if (!spec.typeName) return toast("type name is required", true);
      const opts = { pkgName: draft.pkgName, specs: [spec], header: draft.header, author: lib.author,
                     description: draft.description, layout: draft.layout !== false };
      // append: the class goes into blocks.py; a device_ref param the package did not have yet
      // also gets its adapter file (create-only, so an existing one is left alone)
      const files = draft.mode === "append"
        ? [{ rel: `${pyIdent(draft.pkgName)}/blocks.py`, content: "\n\n" + buildBlockSkeleton(spec, opts), mode: "append" },
           ...(opts.layout && deviceParams([spec]).length ? adapterFiles(opts, deviceParams([spec])) : [])]
        : buildPackageFiles(opts);
      const res = await window.bridge.writeFiles({ root: draft.root, files });
      if (res.error) { out.innerHTML = `<span class="err">${res.error}</span>`; return toast(res.error, true); }
      lib.lastRoot = draft.root; saveLib();
      const lines = [];
      for (const f of res.written) lines.push(`✔ wrote     ${f}`);
      for (const f of res.appended) lines.push(`✔ appended  ${f}`);
      for (const f of res.skipped) lines.push(`⚠ exists, left untouched: ${f}`);
      // layout added to a package created before the layout existed: __init__.py was kept,
      // so the registry import that new packages get automatically must be added by hand
      const initSkipped = res.skipped.some((f) => /[\\/]__init__\.py$/.test(f) && !/[\\/](tests|ports|adapters)[\\/]/.test(f));
      const registryWritten = res.written.some((f) => /adapters[\\/]registry\.py$/.test(f));
      if (initSkipped && registryWritten) {
        lines.push(``, `→ add this line to ${pyIdent(draft.pkgName)}/__init__.py (kept as it was):`,
                   `    from ${pyIdent(draft.pkgName)}.adapters import registry  # noqa: F401 — registers adapter kinds (hook #2)`);
      }
      // append wrote a new per-kind adapter → registry.py (kept) must learn the kind by hand
      const newAdapters = res.written.filter((f) => /adapters[\\/][A-Za-z0-9_]+_grpc\.py$/.test(f));
      if (draft.mode === "append" && newAdapters.length) {
        const pkg = pyIdent(draft.pkgName);
        lines.push(``, `→ new device kind(s) — add to ${pkg}/adapters/registry.py:`);
        for (const f of newAdapters) {
          const param = f.replace(/^.*[\\/]/, "").replace(/_grpc\.py$/, "");
          const cls = adapterClassFor({ pkgName: pkg }, param);
          lines.push(`    from ${pkg}.adapters.${param}_grpc import ${cls}`,
                     `    KINDS[${pyStr(`${pkg}.${param}`)}] = ${cls}   # or add it inside the KINDS dict`);
        }
      }
      // an appended push-source block uses `time` and the port types; append never touches the
      // module header, so say which imports blocks.py must have
      if (draft.mode === "append" && res.appended.length && needsPortImports({ ...opts, specs: [spec] })) {
        const pkg = pyIdent(draft.pkgName);
        lines.push(``, `→ this block needs these imports at the top of ${pkg}/blocks.py (add if missing):`,
                   `    import time`, `    from ${pkg}.ports.${pkg}_port import ${camel(pkg)}Port, ${camel(pkg)}Response`);
      }
      out.innerHTML = `<pre>${lines.join("\n")}</pre>`;
      toast(`${res.written.length + res.appended.length} file(s) written`);
      if (draft.mode === "new" && res.written.length) {
        // the package exists now — the natural next action is another block into it
        draft.mode = "append";
        draft.typeName = "";
        draft.doc = "";
        el("div", { class: "hint", text: "Package created. The dialog is now in APPEND mode: enter the next block (e.g. UdsDidSourceBlock) and press “Append to blocks.py”." }, out);
        const again = el("button", { text: "Add another block →" }, out);
        again.addEventListener("click", () => renderScaffoldTab());
      } else if (draft.mode === "append" && res.appended.length) {
        // never let the same form append the same class twice
        draft.typeName = "";
        draft.doc = "";
        el("div", { class: "hint", text: "Appended. The type name is cleared — enter the next block, or regenerate the catalog." }, out);
        const again = el("button", { text: "Add another block →" }, out);
        again.addEventListener("click", () => renderScaffoldTab());
      }
      // offer the next step: the package dir becomes a catalog source
      const pkgDir = `${draft.root.replace(/[\\/]+$/, "")}\\${pyIdent(draft.pkgName)}`;
      if (!lib.sources.includes(pkgDir)) { lib.sources.push(pkgDir); saveLib(); }
      const next = el("button", { class: "primary", text: "Regenerate catalog now →" }, out);
      next.addEventListener("click", () => openModal("Library", "catalog"));
    });
  }

  /* ---- tab 2: regenerate catalog ---- */
  function renderCatalogTab() {
    const body = document.getElementById("modal-body");
    body.innerHTML = "";
    if (!lib.sources.length && state.paths.toolRoot) {
      lib.sources.push(`${state.paths.toolRoot}\\tools\\reference\\blocks.py`);
    }
    el("div", { class: "hint", html: `Sources are merged into one catalog: the library <code>blocks.py</code> plus any block packages. ` +
      `A block type registered twice is an error. Output goes to <code>blocks_catalog.json</code> + <code>app/catalog.js</code>; the palette reloads in place.` }, body);
    const list = el("div", { class: "lib-sources" }, body);
    const redraw = () => renderCatalogTab();
    lib.sources.forEach((s, i) => {
      const r = el("div", { class: "obs-row" }, list);
      el("input", { type: "text", value: s, readonly: "" }, r);
      const rm = el("button", { text: "✕" }, r);
      rm.addEventListener("click", () => { lib.sources.splice(i, 1); saveLib(); redraw(); });
    });
    const add = el("div", { class: "lib-actions" }, body);
    const addFile = el("button", { text: "+ blocks.py file…" }, add);
    const addDir = el("button", { text: "+ package directory…" }, add);
    addFile.disabled = addDir.disabled = !isElectron;
    addFile.addEventListener("click", async () => {
      const p = await window.bridge.pickPath({ kind: "file", title: "Pick a blocks.py", filters: [{ name: "Python", extensions: ["py"] }] });
      if (p && !lib.sources.includes(p)) { lib.sources.push(p); saveLib(); redraw(); }
    });
    addDir.addEventListener("click", async () => {
      const p = await window.bridge.pickPath({ kind: "dir", title: "Pick a block package directory" });
      if (p && !lib.sources.includes(p)) { lib.sources.push(p); saveLib(); redraw(); }
    });
    const form = el("div", { class: "lib-form" }, body);
    el("label", { text: "python" }, form);
    const py = el("input", { type: "text", value: lib.python || state.live.python || "python", placeholder: "python (stdlib only is enough)" }, el("div", {}, form));
    py.addEventListener("change", () => { lib.python = py.value.trim(); saveLib(); });
    const actions = el("div", { class: "lib-actions" }, body);
    const run = el("button", { class: "primary", text: "Regenerate catalog" }, actions);
    run.disabled = !isElectron || !lib.sources.length;
    const out = el("div", { class: "lib-out" }, body);
    run.addEventListener("click", async () => {
      run.disabled = true; out.innerHTML = "<pre>running generate_catalog.py …</pre>";
      const before = new Set(state.catalog.blocks.map((b) => b.type));
      const res = await window.bridge.catalogGenerate({ sources: lib.sources, python: py.value.trim() || "python" });
      run.disabled = false;
      if (!res.ok) {
        out.innerHTML = `<pre class="err">${(res.stderr || res.error || "failed").trim()}</pre>`;
        return toast("catalog generation failed — see output", true);
      }
      const reloaded = await reloadCatalog();
      const after = new Set(state.catalog.blocks.map((b) => b.type));
      const added = [...after].filter((t) => !before.has(t)), removed = [...before].filter((t) => !after.has(t));
      out.innerHTML = `<pre>${(res.stderr || "").trim()}\n\n${reloaded ? "palette reloaded" : "palette NOT reloaded (see toast)"}\n` +
        `types: ${after.size}${added.length ? `  + ${added.join(", ")}` : ""}${removed.length ? `  − ${removed.join(", ")}` : ""}</pre>`;
      toast(`catalog: ${after.size} block types${added.length ? ` (+${added.length} new)` : ""}`);
    });
  }

  async function reloadCatalog() {
    const txt = await window.bridge.loadCatalog();
    if (!txt) { toast("blocks_catalog.json not found after generation", true); return false; }
    try {
      const cat = JSON.parse(txt);
      const problems = checkCatalog(cat);
      if (problems.length) { toast("generated catalog rejected: " + problems[0], true); return false; }
      state.catalog = cat;
      state.catMap = catalogByType(cat);
      renderPalette();
      render(); // unknown blocks may have become known
      return true;
    } catch (e) {
      toast("generated catalog is not valid JSON", true);
      return false;
    }
  }

  document.getElementById("btn-library").addEventListener("click", () => openModal("Library", "scaffold"));
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal").addEventListener("click", (ev) => { if (ev.target.id === "modal") closeModal(); });
  for (const b of document.querySelectorAll("#modal-tabs button")) {
    b.addEventListener("click", () => openModal("Library", b.dataset.tab));
  }
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeModal(); });
}
