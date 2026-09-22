# Manager GUI documentation

> 📄 *Also available as HTML:* [`../html/index.html`](../html/index.html)

Companion docs to the Microservice Manager GUI. The GUI itself is a
thin client over the FastAPI bridge — these docs explain what the
panels do, how they map to bridge endpoints, and how to script the
same operations from a terminal.

For a one-page overview of the GUI as a whole, start at
[`../../README.md`](../../README.md).

## Guides

### [Operating Consul + Nomad](ops_consul_nomad.md)

How the **Service Network** mode replaces the per-terminal
`consul agent -dev` / `nomad agent -dev` workflow:

- Bridge LED and what each colour means
- Consul tab: Setup form (Dev / Config / Connect) + Connected dashboard
- Nomad tab: same pattern + jobs table + Submit Job dialog
- Navbar infra status pills (live LEDs, click-to-jump)
- Typical end-to-end workflow (open GUI → service running)
- CLI equivalents — every GUI action mapped to its bridge HTTP endpoint
- Troubleshooting (port conflicts, stale PID files, missing services)

8 screenshots showing each state of the panels.

### [Service Creator wizard](service_creator.md)

The 4-step wizard for generating new service scaffolds (proto + domain
+ adapter + clients + Nomad HCL) without writing boilerplate:

- Step 1 — Basic Info (name, language, GUI type)
- Step 2 — Technology (server / client toolchain matrix)
- Step 3 — Methods (manual entry + import .proto)
- Step 4 — Review & Generate (output preview)
- What gets generated, where, and how to build it
- The `mb-scaffold` CLI equivalent + YAML config schema

10 screenshots covering each step + the generated file tree.

### [Generate Robot Framework resources](robot_generator.md)

Turn a folder of `.proto` files into typed Robot Framework keyword
libraries — one `.resource` per service, one keyword per RPC method —
that wrap `QConnectBase.ConnectionManager` so tests don't have to
hand-roll JSON `send_cmd` strings:

- Output conventions (service-prefixed keyword names, `${conn_name}`
  first, `Open/Close Connection` helpers chosen to avoid collisions
  with proto-defined `Connect()` / `Disconnect()` RPCs)
- GUI button location (methods panel toolbar + no-reflection
  fallback card)
- `python -m MicroserviceBase.tools.robot_gen` CLI (works without the
  bridge — CI-friendly)
- `POST /api/scaffold/robot` HTTP endpoint
- Proto3 default-value-omission caveat + the bridge-side fix
- Troubleshooting (Failed to fetch, "no .proto files matched", duplicate
  keyword names — all the regressions previous users hit)

## Cross-references

| When you need… | Go to |
|---|---|
| The actual framework architecture (hexagonal layers, runtime model) | [`../../../../docs/`](../../docs/) (repo-level) |
| A toolchain setup guide (MSYS2, Qt6::Grpc, vcpkg + Qt MinGW) | [`../../../../../examples/docs/md/index.md`](../../../../examples/docs/md/index.md) |
| The lighter in-app help (loaded inside the running GUI) | `../../web/docs/help.html` (or click the **?** in the navbar when the GUI is running) |
| A worked example of a multi-service C++ project | [`../../../../examples/PowerDeviceService/README.md`](../../../../examples/PowerDeviceService/README.md) |

## Providing a GUI for a gRPC service

A service registered in Consul is listed in the Services view with a
**No GUI** marker and opens a runtime card (status, instances, address,
tags). To show a GUI of its own instead, the service declares one and
ships it:

1. **Declare** — set `gui` in the service settings (env var
   `<PREFIX>_GUI`, e.g. `HELLO_GUI=HelloService1.0.0`). `ServiceRunner`
   registers it in Consul as `Meta.gui`.
2. **Ship** — put the plugin folder under the Manager GUI's
   `web/services/<gui>/`. A `component.json` (see below) is tried first;
   without one, any of the loader's tiers works: `gui_schema.json`,
   `ServiceUI.qml`, `ServiceUI.ui`, a Qt WASM build (`.html` + `.js` +
   `.wasm`), or plain `<Name>.html` + `<Name>.js`.
3. **Talk to the service** — from JavaScript use
   `MM.grpcClient.callMethod({ consulName, consulUrl, grpcService, method,
   argsJson })`; the bridge resolves the instance through Consul and
   invokes it via gRPC reflection, so the plugin needs no generated
   stubs. `MM.currentGuiService` holds `{ name, consulUrl, address, port,
   grpcServices }` for the selected instance.

`web/services/HelloService1.0.0/` is a complete example for the
`examples/hello_service` sample; `examples/demo_gui.nomad.hcl` runs that
service with the GUI declared.

### Component manifests (`component.json`)

A component is a declarative panel: the GUI draws it from the manifest,
so the service ships no GUI code. It names its layer of the TAG layer
chart, the capabilities it uses and the tiles it shows:

```json
{
  "component": "operator.hello",
  "version": "1.0.0",
  "layer": "operator",
  "title": "Hello",
  "requires": { "shell": "^2.3", "capabilities": ["grpc.call"] },
  "binds": { "consul": "@self", "grpc": "hello.v1.HelloService" },
  "tiles": [
    { "id": "greet", "size": "1x1", "kind": "command-form", "call": "Greet",
      "form": { "name": "string" }, "resultPath": "message" }
  ],
  "renderer": "schema"
}
```

- **Tile kinds:** `text`, `live-status` (polls RPCs), `command-form` (typed
  form, or built from gRPC reflection when `form` is left out), `table`
  (rows from an RPC, or static `rows`), `log` (server-streaming RPC) and
  `run-status`. **Sizes** on the 4-column stage: `1x1`, `2x1`, `2x2` and
  `4x1`.
- **`ribbon[]`** groups of commands (`label`, `call`, optional `args`,
  `form`, `confirm`) appear on their tab while the component is on the
  bench (below).
- **`binds.consul: "@self"`** means the service that declared the component
  through `Meta.gui`. A host, port or IP here is rejected.
- **Capabilities** are enforced: an RPC or signal call that the manifest
  did not declare fails with `CapabilityDenied`. `signals.subscribe` and
  `signals.set` (write a setpoint) are served by the bridge
  (`WS /api/signals/stream`, `POST /api/signals/set`); `session.*` and
  `config.*` are stubs until the session manager and the configuration
  service exist.
- **Lint** before shipping, from the Manager GUI folder:
  `node tools/endo-lint.js web/services/<gui>/component.json`. It exits
  non-zero on errors. A manifest with errors is not mounted; the GUI shows
  the list of broken rules instead.
- The contract lives in `web/js/endo/contract/component.schema.json`; the
  linter's tests are in `test/endo/test_endo_lint.js`.

The Service Creator and `mb-scaffold` emit a starting manifest in
`ui/<Service><version>/component.json`: one command form per unary RPC
and one log per server-streaming RPC, in the `bits` layer unless the spec
sets `ui_layer`. Multi-service projects don't get one yet. **C++
services:** the C++ runtime does not register `Meta.gui` yet, so a C++
service cannot declare its component itself; a composition can name its
folder instead (below).

### The bench: one screen from many services

**User → Bench** (or the **Bench** tab under the left pane) shows the
tiles of several services' components on one 4-column stage. Which
services, and in which order, is a **composition**:

```json
{
  "composition": "bench07/operator",
  "title": "Bench 07 · operator",
  "shell": "^2.3",
  "role": "user",
  "components": [
    { "from": "consul", "service": "session-service" },
    { "from": "consul", "service": "testbench-device-psu", "tiles": ["out"] },
    { "from": "consul", "service": "cpp-psu", "gui": "PowerSupply2.0.1" }
  ],
  "order": ["session.header", "*", "@cpp-psu"]
}
```

- A composition references services by Consul name and never copies
  their manifests. `gui` names the folder for a service that does not
  register `Meta.gui`; `tiles` shows only some of a component's tiles.
- `order` takes `<component>/<tile>`, `<component>`, `@<service>` and `*`
  (everything not listed); unlisted tiles follow in composition order.
- `role` is the ribbon tab the bench opens on.
- Pick a composition in the **Bench** group of the User tab. **Edit** checks
  one against the contract (S, R3, R9) and saves it through the bridge
  (`GET/PUT/DELETE /api/ui/compositions/{bench}/{role}`) under
  `%APPDATA%\devatservgui\compositions\` (`MB_COMPOSITIONS_DIR` overrides
  it). With nothing stored, the bench shows **All components**: every
  connected service that declares a GUI.
- A module that shows no tiles still keeps a slot saying why: *refused*
  with the broken rule ids, *classic panel* (no `component.json`; **Open
  panel** shows it in the Services view), *no GUI* or *not registered*. The
  rest of the bench keeps working.
- Selecting a tile opens the **dock** with the component's details and,
  when the manifest lists `api`, the API explorer. The dock also opens the
  service in the Services view, or its classic panel when the folder still
  has one.
- The strip under the stage has one badge per module; the left pane lists
  the modules. Tiles stop polling while the bench is hidden.
- **Live signals.** A `live-status` field with `"signal": "<name>"` shows
  that signal's value as it changes (at most 10 times a second); the
  component must declare `signals.subscribe`. The bridge finds
  `signal-discovery` in the connected Consul (or at the address set with
  the **signals** badge under the stage, or `MB_SIGNAL_DISCOVERY_ADDR`),
  keeps **one** stream per graph service that owns a shown signal, and
  closes it when no tile needs it. Names the catalog does not know show
  *unknown signal* and fill in once their service is up.
- `node tools/endo-lint.js <composition.json>` lints a composition in CI.
  `test/endo/fixtures/bench/` holds the proposal's prototype modules and
  compositions; `test/endo/test_endo_bench.js` tests them.

### Plugins

Plugins extend the shell itself; a component shows one service, a plugin
adds something any component or user can use. **Administrator → Plugins**
lists them and turns them on or off on this PC; turning one off removes
what it added at once, and tiles of its kinds show *enable the plugin*.

| Plugin | Adds |
|---|---|
| `charts` | tile kind `signal-strip` (live sparklines), drawer tab *Chart* for the selected tile's signals |
| `test-project` | the *Project* tab under the left pane, the project view, the *Test project* ribbon group |
| `robot-gen` | *Robot Resources* in the Developer tab's Build group |
| `graph-studio` | *Graph Studio* in the Build group; opens its own window (desktop app only) |

- **Bundled** plugins live in `web/plugins/<id>/` and are listed in
  `web/plugins/index.json`; **installed** ones in
  `%APPDATA%\DevAtServGUI\plugins\<id>\` (they win over a bundled plugin of
  the same id). Installed plugins cannot run in their own window.
- A plugin is a `plugin.json` (`web/js/endo/contract/plugin.schema.json`)
  plus ES modules. Contribution points: `kinds`, `ribbon.groups`,
  `commands`, `navigators`, `stage.views`, `dock.sections`,
  `drawer.tabs`. A contribution names a module (`entry`) or a view or
  action the shell already has (`shell`).
- A kind's `schema` and `needs` are used when components are linted, so a
  tile of a plugin kind is checked like a core one.
- `node tools/endo-lint.js web/plugins` lints the plugin manifests;
  `test/endo/test_endo_plugins.js` tests the bundled ones.
- Plugin code runs in the page for now; frame isolation is the next step.

## Test projects

A test project is a folder the Manager GUI exports services into, so test
authors get working Robot Framework keywords without copying generated
files around by hand.

A complete sample — generated resources, starter files and a hand-written
API suite — is in `examples/hello_test_project/`.

**Open one:** *Developer Tools → Open test project…* (or the folder chip in
the developer inspector). A folder that is not a test project yet can be
initialized; existing files are never moved or changed.

**See what's in it:** *Developer Tools → Test project view* (opening a
project lands there too). The sidebar lists every file grouped into suites,
resources, protos and configuration, each marked **gen** (generated),
**starter**, **yours** or **manifest**. A generated file edited since the last
export shows an amber dot, a deleted one a red dot. The overview shows the
exported services with their file state and the command that runs all
suites; from there you can **Re-export** a running service or export
another one.

**Edit suites in place.** Selecting a suite, a starter file or one of your
own files opens it in an editor with Robot Framework highlighting and line
numbers (Tab inserts four spaces, Enter keeps the indentation, **Ctrl+S**
saves). A save refuses to overwrite a file that changed on disk since you
opened it, and offers *Overwrite* or *Reload* instead. On save — or with
**Check** — the bridge parses the file with Robot Framework and lists syntax
problems by line; click one to jump there. Unsaved text survives a reload
and is offered again when you reopen the file. Generated files and the
manifest open read-only. **New suite…** (overview, or **+** next to
*Suites*) creates a suite already wired to an exported service's keywords.

**Export a service:** select a Consul-registered service, then *Developer
Tools → Add to test project* (or the button in the inspector's API tab).
The GUI first shows a plan — every file with its status and a diff for
anything that would change — and writes only when you confirm.

Structure for **Robot Framework AIO** (the first supported runner):

```text
<project>/
├─ testproject.json                   manifest: runner, layout, what was exported
├─ testsuites/
│  ├─ config/robot_config.jsonp       RF AIO config (level 3); CONSUL_ADDR in params.global
│  └─ <service>_smoke.robot           starter suite per service
├─ resources/<service>/*.resource     generated keywords
└─ proto/<service>/*.proto            copied protos, when available
```

Run a starter suite from the project root with the RF AIO interpreter:
`python -m robot -d results testsuites/<service>_smoke.robot`.

| Status | Meaning |
|---|---|
| **new** | The file does not exist yet and will be created. |
| **update** | Written by an earlier export and not edited since; regenerated. |
| **unchanged** | Already identical (the generation date is ignored). |
| **edited locally** | Differs from what the tool last wrote, or was not written by it. Left alone unless you allow overwriting. |
| **kept** | Starter file (suite, config) that already exists — yours, never overwritten. |

How it decides what to generate from:

- **Proto available** — a local `.proto` declaring the service is found
  (a folder you pick first, then `MB_PROTO_SEARCH_PATH` and the default
  locations). It and its local imports are copied to `proto/<service>/`,
  and the resources are generated from exactly those copies.
- **No proto** — the resources are generated from the running service's
  server reflection. Nothing is copied; at test time the connection also
  uses reflection (`${PROTO_DIR}` is empty).

Resources connect through Consul by service name, never by host and port —
Nomad assigns a new port on every placement. Generated resources should not
be edited; put your own keywords in a separate resource.

**Other test runners.** `testproject.json` names the runner, and everything
runner-specific sits behind one interface
(`MicroserviceBase/ports/test_project.py`). Supporting another runner means
adding an adapter next to `adapters/test_project/robot_aio.py` and
registering it; the manifest, proto handling and the plan/apply safety rules
stay the same.

## Signal Graph Studio

**Developer Tools → Signal Graph Studio** opens the Signals & Blocks graph
editor in its own window: draw blocks/wires/observe taps, map device
parameters to Consul services, validate, and generate a deployable graph
service (configs folder + Nomad job + `RUN.txt`, with a cross-graph
signal-name collision scan).

Beyond authoring, the studio also watches a graph run and grows the block
library:

- **◉ Monitor** subscribes to the graph's observed signals (one long-lived
  `grpcurl … SignalQueryService/Subscribe` per owning endpoint) and shows the
  live value and age on every observe tag, a value badge on each
  `SubscriberSourceBlock`, and a pulse through the blocks upstream of each
  update. It works against anything already running — a Nomad-deployed graph
  service included.
- **Chart tab** (log drawer → *Chart*) draws the same signals as small
  multiples over a shared time axis: one strip per signal with its own
  y-scale, 10/30/120 s window, crosshair, pause and per-signal toggles.
- **Set signal** (inspector of a `SetpointBlock`) writes a value into the
  running service through its own `SetSignal` RPC — the same path a Robot
  `Set Signal` keyword takes — so write-direction graphs can be demonstrated
  end to end: set → watch the wired blocks react → see the ack.
- **▶ Run graph / ▶ Run cluster** starts a *local, fully mocked* cluster for
  a wiring check. It needs `run_cluster.py`, which belongs to the signals
  repository and is deliberately not vendored here: point
  **`MB_SIGNALS_ROOT`** at a checkout that contains it, otherwise the button
  reports the snapshot as missing. Deploying the generated Nomad job and
  using ◉ Monitor is the supported path for a real bench.
- **Library…** has two tabs: *New block skeleton* scaffolds a block package
  (`blocks.py`, test stub, README, file header) with the catalog hints
  already in place and, with the *layout* box ticked, the hexagonal skeleton
  around it (`ports/<pkg>_port.py`, `adapters/mock.py`,
  `adapters/grpc_client.py`, `adapters/registry.py`); it never overwrites an
  existing file, so re-running it on an older package only adds what is
  missing. *Regenerate catalog* runs the generator over chosen sources and
  hot-reloads the palette without a restart.

Live lookups, Monitor and Set signal need `grpcurl` on `PATH` (as the API
Explorer does). Graph services serve no gRPC reflection, so the vendored
`reference/protos/signal.proto` is passed as `-import-path`; the Live panel's
*proto dir* overrides it.

It is vendored under `graph-studio/` and hosted, not merged:

- Its renderer (`graph-studio/app/`) is unchanged from the stand-alone
  tool and owns its own document — the manager's DOM and CSS are not
  involved.
- It gets its own preload exposing `window.bridge`, and its IPC channels
  are prefixed `gs:` so they cannot collide with the manager's.
- `graph-studio/ipc.js` replaces the tool's `main.js`: the same handlers,
  registered by the manager's main process, plus the window opener. It also
  owns the studio's child processes — the host stops them on quit and when
  the studio window closes.
- The live panel is pre-filled with the Consul the manager is connected to
  and the Python from *Settings* (a previously saved endpoint in the studio
  wins).
- Closing with unsaved changes asks first.
- The installer unpacks `graph-studio/**` from the asar archive, because
  `grpcurl` and Python are given real file paths (the reference proto, the
  catalog generator, and the catalog it rewrites).

The headless harness lives in `graph-studio/tests/` and is excluded from the
installer. Run it after any change to the vendored model, catalog, generator
or library code:

```bash
node graph-studio/tests/test_graph_studio.js   # GS_PYTHON=<interpreter> if
                                               # "python" is not on PATH
```

**The block catalog is generated.** `graph-studio/blocks_catalog.json`
and the `DEFAULT_CATALOG` inside `app/catalog.js` come from the signals
library's `blocks.py`:

```bash
python graph-studio/tools/generate_catalog.py <path-to-blocks.py> --update-tool graph-studio
```

Never hand-edit either file; regenerate after the library changes. The
vendored `tools/reference/blocks.py` is a snapshot for that generator and
is excluded from the installer.

## Bridge security: allowed origins

The Python bridge (`python/start_bridge.py`) only answers browser requests
whose `Origin` is on an allow-list. Anything else gets `403` with
`{"error": "origin_not_allowed"}`, and the bridge log records the origin
and the setting that would permit it.

**Default** (nothing configured): the bridge's own address plus
`http://localhost:<port>` and `http://127.0.0.1:<port>`. When the bridge is
bound to a loopback address the Electron GUI is admitted as well -- it loads
from `file://`, which browsers report as `Origin: null`.

**Configure** without touching code -- highest priority first:

| Where | Form |
|---|---|
| CLI | `python start_bridge.py --allowed-origins "http://10.0.0.5:1112,null"` |
| `python/config.json` | `"bridge_allowed_origins": ["http://10.0.0.5:1112", "null"]` |
| Environment | `MB_BRIDGE_ALLOWED_ORIGINS=http://10.0.0.5:1112,null` |

Rules:

- An origin is `scheme://host[:port]` -- no path, no trailing slash.
- `null` admits the Electron GUI. Add it yourself when the bridge is bound
  to a non-loopback address such as `0.0.0.0`; it is left out of the default
  there because any local page could otherwise reach the bridge.
- `*` switches the check off entirely (the bridge logs a warning at start).
- An empty or malformed list stops the bridge at startup with a message
  naming the bad entry and showing a valid one.

**What this does not do.** An origin check applies to browsers only. `curl`,
Python scripts and other non-browser clients send no `Origin` header and
pass through. Keep the bridge on `localhost` unless remote access is
needed; controlling who may *call* the bridge is an authentication
feature, not an origin rule.

## In-app help vs long-form docs

| | In-app `web/docs/help.html` | Long-form `docs/` (this folder) |
|---|---|---|
| **Audience** | User running the app right now | Developer learning the framework |
| **Reading context** | Side panel inside the running GUI | GitHub / IDE markdown preview / browser |
| **Length** | Quick lookup (~500 lines) | Comprehensive (~1000-2000 lines per topic) |
| **Cross-links** | Mostly self-contained | Links across the repo (toolchains, examples, runtime) |
| **Screenshots** | 10 (one per major panel) | 18 (each panel state, plus per-wizard-step) |
| **Source of truth** | Mirror of long-form for the topics it covers | ✓ Canonical |

When the two diverge, fix the long-form first, then propagate the
relevant snippet into `help.html`.
