# Signal Graph Studio (vendored)

> **Using the tool?** Read [USER_GUIDE.md](USER_GUIDE.md).
> This README is the developer note for the copy hosted by the Manager GUI.

Viewer/editor/**service composer** for Signals & Blocks `graph.json` files
(BITS testbench, PR #253 **revision 2** schema), opened from the Manager
GUI's *Developer Tools → Signal Graph Studio*.

> Rev-2 insight that shapes this tool: a graph service **is** the generic
> `signal_graph` binary + one `graph.json`. Generating a valid config (+ a
> Nomad job) *is* generating the service. No codegen.

## How it is hosted

The renderer under `app/` is the stand-alone tool, vendored unchanged. Only
the shell around it is ours:

| File | Origin | Role |
|---|---|---|
| `app/`, `blocks_catalog.json`, `examples/`, `tools/` | upstream, verbatim | editor, catalog, generator |
| `ipc.js` | ours | replaces the tool's `main.js`: the same handlers, registered by the Manager GUI's main process on `gs:`-prefixed channels, plus the window opener and child-process cleanup |
| `preload.js` | ours | `window.bridge` over those `gs:` channels |
| `reference/protos/signal.proto` | upstream | `-import-path` for grpcurl (graph services serve no reflection) |
| `tests/` | upstream, repathed | headless harness (excluded from the installer) |

Rules that keep re-vendoring cheap:

- Never edit `app/**` — fix upstream and copy the folder over.
- Channel names stay prefixed (`gs:open-graph`, …) so they cannot collide
  with the manager's own IPC.
- The studio owns its document: it gets a frame (its own window), never a
  slice of the manager's DOM.
- `ipc.js` is the only place allowed to know about the host.

## What it does

- **View / edit** — palette of the rev-2 block set, drag output→input
  wiring (occupied-input, self-wire, unknown-port and cycle checks),
  params/id/observe in the inspector, auto-layout, layout kept in a
  `<name>.layout.json` sidecar (never in `graph.json`).
- **Compose** — service panel (`name`, `grpc_port`, `rate_hz`,
  `flow_mode`), `device_services` mapping (device params become dropdowns;
  unmapped is an error), tool-managed `setpoints`.
- **Generate service…** — validation gate, then `<configs-root>/<name>/`
  `graph.json` + layout + `RUN.txt` and
  `testbench_signal_graph_<name>.nomad` (raw_exec wrapper, `signal_graph`
  Consul tag, **never** `initial_status="passing"`), plus a cross-graph
  signal-name collision scan over every sibling `*/graph.json`.
- **Live panel** — ⟳ Consul (`GET /v1/catalog/services`) and ⟳ Signals
  (`ListSignals` / `ListSignalErrors` via `grpcurl`), feeding datalists for
  device and signal params; "check my names vs live catalog" before
  deploying into a discovery exclusion.
- **Run / Monitor / Chart** — see below.
- **Library…** — scaffold a block package (optionally with the hexagonal
  layout: `ports/`, `adapters/{mock,grpc_client,registry}.py`), regenerate
  the catalog from source and hot-reload the palette.

## Run, Monitor, Set signal

- **◉ Monitor** — one long-lived `grpcurl … SignalQueryService/Subscribe`
  child per owning endpoint, its streamed JSON split by
  `tools/jsonstream.js`. Live value + age on every observe tag, a ⇠ badge on
  `SubscriberSourceBlock`s, a pulse through everything upstream of a tapped
  port, and sparklines matching the Chart colours. Works against anything
  already running, a Nomad-deployed graph service included.
- **Chart tab** — small multiples (one strip per signal, own y-scale,
  shared time axis, 10/30/120 s window, crosshair, pause). Canvas 2D only.
  Strips scroll when there are more than fit (min height from the *rows*
  selector) with the axis pinned below them, and the drawer itself resizes
  by dragging its top edge.
- **Set signal** (`SetpointBlock` inspector) — one unary `SetSignal` on the
  owning service's own port; the engine's rejection reason is surfaced.
- **▶ Run graph / ▶ Run cluster** — a local, fully mocked wiring check.
  It spawns the vendored `tools/run_cluster.py --signals-root <dir>`; the
  signals code itself (`signal_graph/`, `signal_discovery/`, `common/` —
  the repo's `services/signals`) is deliberately **not** vendored. The root
  comes from the studio's Live panel field ("signals root for ▶ Run"), else
  **`MB_SIGNALS_ROOT`**, else a sibling-checkout guess; without any, the
  button reports "no signals root" and everything else still works. The
  runner applies the UDS hooks locally (`block_modules`, `device_kinds`
  → package `MOCK_ADAPTER`, optional `mock_scripts`) so graphs with extra
  block packages run before the engine has the hooks.

Honest limit: only **observed** signals are visible — the engine exposes no
per-wire debug stream, so un-tapped wires stay dark by design.

## The block catalog is generated

Palette and type-checking come from the catalog, which is generated from the
library source by AST introspection (never imports the target — no venv, no
grpc, proxy-proof):

```bash
python tools/generate_catalog.py <path-to-blocks.py> [more files or dirs] --update-tool .
```

`--update-tool` rewrites **both** copies (`blocks_catalog.json` and the
`DEFAULT_CATALOG` literal in `app/catalog.js`). Never hand-edit either.
Several files/package directories merge into one catalog (`tests/` skipped,
a type registered twice is an error). *Library… → Regenerate catalog* runs
exactly this and reloads the palette in place.

Inference covers `device_ref` (param traced into `ctx.device_adapters[...]`),
`signal_ref` (via `catalog_client`), `enum` (from `x in ("a","b")` checks),
and `list` / `object` (from `get(k, [])` / `{}` defaults). When the code
doesn't reveal the intent, annotate the line that reads the param:

```python
self._svc = params["request_service"]          # graph-studio: device_ref
policy = params.get("trigger", "on_change")    # graph-studio: enum on_change|every_write|edge
self.service_name = params["service_name"]     # graph-studio: allowed_from allowlist.service
```

Annotations always win over inference. `allowed_from` turns one list param
into the allowed set for another, so the editor refuses at edit time exactly
what the engine refuses at build time.

`tools/reference/blocks.py` is a labeled snapshot of the rev-2 library, kept
as the default source until the PR is checked out.

## Invariants — do not break

1. **Lossless round-trip**: unknown top-level sections and block fields pass
   through untouched; the wire dialect that was read (`signals` objects vs
   legacy `wires` pairs) is written back; key order is preserved.
2. **Layout never enters `graph.json`** — sidecar only.
3. **The catalog is generated**, never hand-edited.
4. Validation severity: errors block Generate; warnings do not.

## Tests

```bash
node tests/test_graph_studio.js                 # 88 checks
GS_PYTHON="C:/Program Files/RobotFramework/python3/python.exe" node tests/test_graph_studio.js
```

Loads `catalog.js`, `model.js`, `layout.js` and `library.js` in a `vm`
context (`editor.js` is DOM-coupled and deliberately not loaded) and covers
catalog sync, lossless round-trips, validations, the generator against
`tests/gen_fixture/`, and the scaffold → `ast.parse` → generator round-trip.
Needs node and a Python on PATH (or `GS_PYTHON`). Run it after any change to
`app/model.js`, `app/catalog.js`, `app/library.js` or
`tools/generate_catalog.py`.

The upstream tool also carries two end-to-end scripts that drive a real
cluster (`test_phase_d_e2e.js`, `test_setsignal_e2e.js`); they need the
signals checkout and grpcurl, so they stay with the upstream tool rather
than in this vendored copy.

## Known limits

- No undo/redo; one graph per window.
- The collision scan covers one configs root; the live check covers what
  discovery currently sees. Neither spans undeployed configs elsewhere.
- Live lookups, Monitor and Set signal need `grpcurl` on `PATH`.
- Signal values are float-only upstream — no categorical signals.
