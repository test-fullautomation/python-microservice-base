# Signal Graph Studio — User Guide

Design a signal graph visually, map its blocks to real bench services, and
generate a deployable `signal_graph` service — no JSON editing required.
Then run it, watch the signals flow, and write setpoints into the running
service.

> One idea to hold on to: since the revision-2 graph schema, **a graph service is just the
> generic `signal_graph` binary plus one `graph.json`**. What this tool
> generates *is* the service.

---

## 1. Starting the tool

In the Manager GUI: **Developer Tools → Signal Graph Studio**. It opens in
its own window, with its live panel pre-filled with the Consul the manager
is connected to and the Python from *Settings*.

Prerequisites, all optional until you use the feature that needs them:

| Feature | Needs |
|---|---|
| ⟳ Consul | a reachable Consul HTTP endpoint |
| ⟳ Signals, ◉ Monitor, Set signal | `grpcurl` on `PATH` |
| ▶ Run graph / ▶ Run cluster | a signals root (the repo's `services/signals`, containing `signal_graph/` + `signal_discovery/`) set in the Live panel or via `MB_SIGNALS_ROOT`, and a Python with `grpcio` + `pydantic-settings` |
| Library… (scaffold, regenerate) | a Python (stdlib only is enough) |

---

## 2. The screen

```
┌────────────────────────── toolbar ──────────────────────────────┐
│ New · Open… · Save · Examples… · Auto-layout · Generate service…│
│ Library… ·  ▶ Run graph · ▶ Run cluster · ■ · ◉ Monitor · pill  │
├───────────┬────────────────────────────────────┬────────────────┤
│  PALETTE  │              CANVAS                │   INSPECTOR    │
│ (block    │  blocks, wires, observe taps       │ nothing        │
│  types by │  · drag block body = move          │ selected →     │
│  family)  │  · drag OUTPUT port → INPUT = wire │ SERVICE panel  │
│           │  · click = select · Delete = remove│ DEVICE mapping │
│           │  · drag empty canvas = pan         │ SETPOINTS      │
│           │  · mouse wheel = zoom              │ LIVE panel     │
├───────────┴────────────────────────────────────┴────────────────┤
│              LOG / CHART drawer   ·   ISSUES (validation)       │
└─────────────────────────────────────────────────────────────────┘
```

Colour code: **teal** source · **violet** function · **green** sink · amber
**◉ name** = observe tap (a published signal).

---

## 3. Create a service from scratch

1. **New** — an empty graph with service defaults.
2. Click empty canvas → the inspector shows the **Service panel**: set
   `name` (lowercase-with-dashes — it becomes the Consul service name and
   the configs folder name), `grpc_port`, `rate_hz`, `flow_mode`.
3. **Map your devices**: in *Device services* add a logical name (e.g.
   `nidaq_dev0`) → Consul service (e.g. `testbench-device-ai-mock`). Press
   **⟳ Consul** first and the field autocompletes from live services.
4. **Add blocks** from the palette. `device` params are **dropdowns** fed by
   your mapping (unmapped is a hard error); a `SubscriberSourceBlock`'s
   `signal_name` offers a live picker after **⟳ Signals**.
5. **Wire**: drag from an output port ⚬ to an input port ⚬. Occupied
   inputs, self-wires, unknown ports and cycles are refused.
6. **Publish signals**: select a block → tick *observe* on an output port
   and give it the public name (`bench.dut.temp.degC` style).
   `SetpointBlock`s register themselves in *setpoints* automatically.
7. Watch the **issues bar** — no errors means generatable.
8. Optional: **Check my names vs live catalog** catches signal names that
   already exist on the bench, before discovery excludes yours.
9. **Generate service…** — pick your configs root; the tool writes:

   | File | Purpose |
   |---|---|
   | `<root>/<name>/graph.json` | the service definition |
   | `<root>/<name>/graph.layout.json` | node positions (tool-only sidecar) |
   | `<root>/testbench_signal_graph_<name>.nomad` | ready Nomad job |
   | `<root>/<name>/RUN.txt` | local run + grpcurl verify commands |

   It also scans every sibling `*/graph.json` for **duplicate signal names**.

> Generated `graph.json` is **config-as-code**: it goes through PR review
> like any other change. The tool makes authoring safe, not review-exempt.

---

## 4. Edit an existing graph

**Open…** a `graph.json` — its `.layout.json` sidecar is picked up
automatically. No sidecar → automatic layout; press **Auto-layout** any
time. If the file changes on disk while open, the tool reloads it silently
when you have no local edits, or shows a choice banner when you do.

Unknown block types (newer library than catalog) still render — gray, ports
inferred from the wiring — but are not type-checked; regenerate the catalog
(§6).

---

## 5. Reading the issues bar

| Level | Examples | Meaning |
|---|---|---|
| **error** | unmapped device · missing required param · input wired twice · wiring cycle · bad `flow_mode` · duplicate signal name · value outside a choice list | the engine would reject or misbehave — Generate is blocked |
| **warn** | no service section · `rate_hz ≤ 0` (engine free-runs!) · unwired input · setpoint orphan · unknown block type | legal but suspicious — read before shipping |

Click an issue naming a block to select it.

---

## 5b. Run it and watch it flow

Toolbar, right side: **▶ Run graph · ▶ Run cluster · ■ · ◉ Monitor** and a
status pill.

1. **◉ Monitor** is the one to reach for on a real bench: it subscribes to
   every signal this graph observes on whatever is already running — your
   Nomad-deployed graph service included. On the canvas you then see
   **`= value` + age** under each ◉ tag with a **sparkline**, a **⇠ value**
   badge on each `SubscriberSourceBlock`, and a **yellow pulse** running
   through the tapped block and everything upstream of it on each update.
2. **▶ Run cluster / ▶ Run graph** is a *local, fully mocked* wiring check
   (in-memory registry + discovery + graph services, nothing real). It needs
   the *signals root for ▶ Run* field (or `MB_SIGNALS_ROOT`) pointing at the
   repo's `services/signals` (the directory with `signal_graph/`), and
   the *python for ▶ Run* field pointing at an interpreter with `grpcio` +
   `pydantic-settings`. Graphs with your own block package add
   `"block_modules"` to `graph.json`; `"device_kinds"` (inferred when
   absent) and `"mock_scripts"` may go there too or into a `graph.mock.json`
   sidecar next to it (shape in `examples/uds-extract-dut.graph.json`); the
   engine ignores them, the runner uses them. "Run graph" runs *your* saved graph (save first —
   unsaved edits are refused so the running service matches the canvas);
   "Run cluster" runs the shipped configs. The **log drawer** shows the
   process output; on `READY` monitoring starts automatically.
3. **Chart tab** — switch the drawer from **Log → Chart** to see the same
   signals as graphs. Every signal gets **its own strip** (own y-scale, so a
   12 V line and a 0/1 flag don't squash each other) over a shared time
   axis: window 10/30/120 s, **pause** freezes the picture while data keeps
   arriving, hover for a **crosshair**, tick signals off in the legend, and
   the right gutter shows latest value with ↑max / ↓min. With many signals
   the strips **scroll** (min height from the **rows** selector) and the time
   axis stays pinned below them; **drag the drawer's top edge** to make the
   whole panel taller (remembered; double-click resets). Up to 32 strips.
4. **Set signal** — select a `SetpointBlock` while the service runs: the
   inspector shows **set signal (live)**. Type a value, press **Set**. It
   goes into the running service through its own `SetSignal` RPC — exactly
   what a Robot `Set Signal` keyword does — and you watch the wired blocks
   react on the canvas and in the Chart. A non-setpoint name is refused by
   the engine, with its reason shown.
5. **■** stops the cluster cleanly (and monitoring with it); Monitor alone
   toggles off with its own button. Closing the studio window stops both.

What you *won't* see: values on un-tapped internal wires. The engine only
publishes observed ports. Want to watch a wire? Give its port an observe
name — that's the intended way.

---

## 6. Keeping the palette truthful — and starting a new block

Toolbar → **Library…**, two tabs:

**Regenerate catalog** — add the library `blocks.py` and any block package
directories as sources (native pickers, remembered for next time), press
**Regenerate**. The palette reloads in place and tells you which block types
were added or removed. Equivalent command line:

```bash
python tools/generate_catalog.py <path-to-blocks.py> [more files or dirs] --update-tool .
```

**New block skeleton** — when a story needs a block type that doesn't exist
yet, fill in the form: where the package lives, its name, the block's type
name, ports, and a params table with the types the palette should show
(device dropdown, choice list, JSON list…). The preview shows the Python
class; **Create package** writes `blocks.py`, a test stub and a README with
the file header — and, with the **layout** box ticked (default), the
hexagonal skeleton around it: `ports/<pkg>_port.py` (what the blocks need
from the outside), `adapters/mock.py` (tests and local runs),
`adapters/grpc_client.py` (the bench adapter, transport left as `TODO`) and
`adapters/registry.py` (adapter kinds for `device_services`). **Append**
adds the class to an existing `blocks.py`. Re-running Create on an older
package only adds the files it is missing and prints the one import line to
add to `__init__.py`. Existing files are never overwritten. The generated code already carries the
`# graph-studio:` hints, so the block appears in the palette with exactly
the param types you chose — the `# TODO` bodies are yours to implement.

The **mode** dropdown (second row) chooses between *new package* and
*append to the existing `blocks.py`*, and the hint under it tells you which
one you are in. After a successful create the dialog switches to append by
itself and offers **Add another block →**, so a package with several blocks
is create-once, append-N. Afterwards it offers **Regenerate catalog now →**.

Param kinds the palette understands: numbers, text, `true/false`, **device**
dropdowns, **signal** pickers, **choice** dropdowns, and **structured**
`list` / `object` params edited as JSON. When a block declares that one
param must come *from* a list param (`# graph-studio: allowed_from
allowlist.service`), the issues bar tells you when the value is not in the
list, when the list is empty, or when an entry misses the field — before you
generate, instead of the service refusing the graph at start-up.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "grpcurl not found on PATH" | install grpcurl or add it to PATH — signal lookups, Monitor and Set signal shell out to it |
| "Consul unreachable" | check the `host:port` in the Live panel |
| Live signals empty but bench runs | discovery may not serve gRPC reflection — set the *proto dir* field, or leave it empty to use the bundled `reference/protos` |
| "no signals root" | ▶ Run needs the Live panel's *signals root* (or `MB_SIGNALS_ROOT`) pointing at `<repo>/services/signals` (must contain `signal_graph/` and `signal_discovery/`) — Monitor against a deployed service needs none of this |
| ▶ Run fails instantly (`ModuleNotFoundError: grpc`) | the *python for ▶ Run* setting points at an interpreter without the deps |
| Monitor shows "waiting…" forever | the service isn't running on `service.grpc_port`, or grpcurl can't dial — check the log drawer; use `127.0.0.1`, not `localhost` (IPv6 resolves to `::1`, the services bind IPv4) |
| Monitor works but no pulse on some blocks | only blocks upstream of a **tapped** port pulse — add observe taps where you want visibility |
| Chart says "no monitored signals yet" | monitoring isn't running (pill shows *idle*) — press ◉ Monitor or ▶ Run |
| Chart strip is flat / one dot | the signal changes slower than the window — pick 120 s, or the source really is constant (mock ADC = fixed value) |
| Device dropdown empty | add mappings in the Device services table first (or ⟳ Consul) |
| Block renders gray | type missing from the catalog — regenerate (§6) |
| "Regenerate catalog" cannot write | the python field points at a missing interpreter, or the sources list is empty |
