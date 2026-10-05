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

### Guided tour — `docs/html/tour.html`

A tour program for an audience — nine stops, about 55 minutes: what the
GUI gives you, how it is configured, what a service has to provide to
appear in it, and building one live in the wizard. Each stop says what to
show, what to say, and what the takeaway is. Open it from the GUI's help
(**?** in the navbar) or straight from `docs/html/tour.html`; it is a
presenter's page rather than a reference, so it has no Markdown twin.

### [Bench demo](bench_demo.md)

A ten-minute walkthrough of the bench on live services — the climate
chamber, the bench signals and the hello service on one stage:

- What to start first (demo cluster, chamber, `examples/ara_demo.nomad.hcl`)
- The stored composition, and what the bench does without one
- Eight beats: composed not built, tiles from the manifest, gRPC values,
  live signals, the charts plugin, a command from a tile, the sandboxed
  panel, and a second bench from the same services
- Troubleshooting the demo (origins, the proxy, a missing catalog)

## Cross-references

| When you need… | Go to |
|---|---|
| The actual framework architecture (hexagonal layers, runtime model) | [`../../../../docs/architecture/`](../../../../docs/architecture/overview.md) (repo-level) |
| A toolchain setup guide (MSYS2, Qt6::Grpc, vcpkg + Qt MinGW) | [`../../../../examples/docs/md/index.md`](../../../../examples/docs/md/index.md) |
| The lighter in-app help (loaded inside the running GUI) | `../../web/docs/help.html` (or click the **?** in the navbar when the GUI is running) |
| Worked examples (C++ and Python services, a client, multi-proto projects) | [`../../../../examples/README.md`](../../../../examples/README.md) |

## Views: user, admin, developer

What the GUI offers is set by **roles** that combine. *User* is always on;
the others add to it:

| Role | Adds |
|---|---|
| **user** | the Services and Bench views, help |
| **admin** | the Administrator ribbon tab: Nomad jobs and the fleet, the plugin manager |
| **developer** | the Developer ribbon tab and everything behind it: test projects, the Service Creator, explorers, plugin views, the developer inspector |

A lab operator who may start Nomad jobs gets `user+admin`; a test developer
`user+developer`; the default is all three.

Where the view comes from, highest priority first:

| Where | Form |
|---|---|
| Address bar (browser) | `?view=user+admin` — for that window only |
| *Settings → View* | checkboxes for *Administrator* and *Developer* |
| `electron/settings.json` | `"view": "user+admin+developer"` |

Roles may be written `user+admin`, `user admin`, `user,admin` or as a JSON
list; `all` means every role. A view outside the roles stays shut whatever
asks for it — a ribbon tab, a mode pill, a plugin command or a view
restored from the last session — and the developer inspector turns off
without the developer role.

!!! note "Roles are not access control"
    A view only hides parts of the GUI. Anyone who can reach the bridge can
    still call its endpoints; keep the bridge on `localhost` (see
    [Bridge security](#bridge-security-allowed-origins)).

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

**The service can hand the GUI its files.** A service built on
`ServiceRunner` serves its GUI folder over gRPC
(`microservicebase.gui.v1.ServiceGui`, ADR-031): set `gui` and keep the
files next to the service in `gui/<gui>/`, `ui/<gui>/` (what the scaffold
emits) or a folder named after the component, or point `gui_dir` at them.
When the Manager GUI opens a service whose `web/services/<gui>/` is empty,
it asks the service, extracts what comes back and mounts it — so a fresh
machine populates itself, and updating a panel is a service deployment.
The checksum is cached per folder, so later opens download nothing. A
service that does not serve the contract (the C++ runtime, third-party
services) still needs its folder shipped some other way; the GUI says so
instead of showing an empty panel.

| Endpoint | What it does |
|---|---|
| `GET /api/service-gui/info/{service}` | what the service offers: folder, checksum, size |
| `POST /api/service-gui/fetch/{service}` | download, then extract (browser) or return the ZIP (desktop) |

`MB_GUI_SERVICES_DIR` overrides where the bridge extracts.

**A folder may ship both.** When it holds a `component.json` *and* a
classic panel (`<Name>.html`, `ServiceUI.qml`, `ServiceUI.ui`, a Qt WASM
build or `gui_schema.json`), the component is what opens, and
**User → Service view → Tiles | Service window** switches that service
between the two; the pressed button shows which is on screen. The choice is
remembered per service (`mm_classic_panel` in local storage), so the service
opens that way from the sidebar until it is switched back; both buttons are
greyed out for a folder that ships only one kind. They sit on the User tab
because the service window is an operator's screen (e.g. a Qt service's own
window built for WebAssembly), available in every view role. The bench dock offers the same switch through **Open classic
panel**.

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
- **Dropdowns in a form.** A form field (of a `command-form` tile or a ribbon
  command) becomes a dropdown with `options`, a fixed list, or with
  `optionsFrom`, a list the service gives. `current` preselects the
  service's present value; a ↻ next to the dropdown reads it again.

  ```json
  "form": {
    "type":  { "type": "int",
               "options": [{ "value": 0, "label": "RS232" }, { "value": 1, "label": "client" }] },
    "index": { "type": "int",
               "optionsFrom": { "count": { "rpc": "GetDeviceType_ListCount", "path": "index" },
                                "name":  { "rpc": "GetDeviceType_Name", "arg": "index", "path": "name" } },
               "current": { "rpc": "GetDeviceType", "path": "index" },
               "reloadAfter": ["SetDeviceType"] },
    "mode":  { "type": "string",
               "optionsFrom": { "rpc": "ListModes", "path": "modes", "value": "id", "label": "name" } }
  }
  ```

  `optionsFrom` is either a list RPC (`rpc`, `path` to the array, `value`
  / `label` paths per item) or a range of indexes from a count RPC (`count`;
  indexes 0 to count−1, or set `first`, and `inclusive` when the count is
  the highest index), each named by an optional `name` RPC. An argument can
  come from another RPC:
  `"args": { "index": { "$from": { "rpc": "GetDeviceType", "path": "index" } } }`
  — the sub-device list of the selected device type. Lists stop at 256
  choices, and names are read one at a time (a device may not take parallel
  requests).
- **Linked dropdowns.** `reloadAfter` lists RPCs after whose successful call
  the dropdown reads its choices and current value again — from its own tile,
  another tile of the same component or a ribbon command. Give the
  sub-device dropdown `"reloadAfter": ["SetDeviceType"]` and it follows a new
  device type as soon as *Set device type* is run, with no ↻ needed.
  The link follows what the service has **set**, not what is picked in
  another tile: services such as the BITS ones list the sub-device types of
  the device type they currently have.
- `python -m MicroserviceBase.tools.ui_component` writes dropdowns from a
  service's protos: choices listed in a field's comment
  (`0-> RS232; 1-> client`), `Get<X>_ListCount` / `Get<X>_Name` / `Get<X>`
  RPCs (indexes 0 to count−1, as the service's own combo boxes fill them;
  "max index" or "1-n" comments are not trusted, because an index past the
  end can crash a service that does not check it), and `reloadAfter` links:
  `Set<X>` for a list whose count takes `<X>`, and a dropdown's own setter.
- **Tile groups.** `groups` puts tiles under a full-width header that
  expands and collapses (click it, or Enter on it):

  ```json
  "groups": [
    { "id": "commands", "title": "Commands",    "tiles": ["init-device", "set-voltage"] },
    { "id": "device",   "title": "Device type", "tiles": ["set-device-type", "get-device-type"], "collapsed": true }
  ]
  ```

  The header sits where the group's first tile is; keep a group's tiles
  together, and put tiles in no group first (they are not under a header).
  A collapsed group's tiles are hidden **and suspended** (R5): their polling
  and signal streams stop until it opens, and a component that is hidden and
  shown again resumes only its open groups. `collapsed` is how a group starts;
  the user's choice is remembered per component (and, on the bench, per
  composition). The linter refuses a group naming a missing tile, a tile in
  two groups and duplicate group ids. A grouped stage packs its rows in order
  (no dense back-fill), so no tile moves above its header. A shell without
  groups shows every tile flat. The generator groups a component of 7 tiles
  or more: the service's own RPCs as *Commands*, *Readings* and *Streams*
  (open), every other bound service by topic — *Device type*, *Interface*,
  *Connect*, in its proto's order — collapsed.
- **Frame tiles** (`"kind": "frame", "entry": "panel.html"`) show an HTML
  page of the component folder in a **sandboxed frame**: its own process,
  no access to the GUI's page, storage or the network. Its scripts reach
  the service only through `window.endo.ctx` (`call`, `signals.subscribe`,
  …), answered with the component's capabilities. A frame that hangs is
  stopped and its tile says so; the rest of the screen keeps working.
  `web/services/HelloService1.0.0/panel.html` is the example
  (`"renderer": "html"`).
- **Qt tiles** show a Qt UI of the component folder in the tile:
  `"kind": "qml", "entry": "qt/panel.qml"` (run by the GUI's QML shell),
  `"kind": "widget", "entry": "qt/panel.ui"` (a Qt Designer form, built by
  the Widget shell) or `"kind": "wasm", "entry": "myui.js"` (the
  component's own Qt for WebAssembly build: its Emscripten loader, next to
  the `.wasm`). Each tile runs its own Qt instance, so several can share
  the bench.
  - **Calls:** `ServiceBridge.callService(...)` reaches `binds.grpc` over
    gRPC through the component's capabilities, so a Qt tile needs
    `grpc.call`.
  - **Arguments:** one object is the request message; otherwise the values
    fill the request fields in order, typed by gRPC reflection.
  - **Replies:** a response with one scalar field comes back as that
    value; anything else comes back as JSON.
  - **Service name:** pass an empty one (`callService("", "Greet",
    [name])`) so the call stays with its tile. A hard-coded name goes to
    the tile that was clicked last. A `wasm` build gets its tile's token
    as `Module.endoToken`: send that as the service name, so calls made
    from a timer reach the right tile too.
  - **Methods of other bound services:** name them as
    `"<service>/<Method>"` (see `binds.grpc` above).
  - **Tile height:** a Qt canvas does not make the tile grow. Set
    `"minHeight": 520` (px) on the tile to fit a fixed-size window.
  - **Full responses:** a `wasm` build also gets the whole response as
    `result_json` next to `result_data`, to read fields by name.
  - **Where the files go:** keep `.qml` and `.ui` files in a subfolder. A
    top-level one would become the folder's classic panel.
  - **wasm tiles:** they run the component's loader script in the GUI page
    with a classic panel's trust. The linter warns; prefer `qml` or
    `widget`.

  `web/services/HelloService1.0.0/qt/hello.qml` is the example. The
  shells are `web/qt-shell/` and `web/widget-shell/`, built from
  `qt_qml_shell/` and `qt_widget_shell/`.
- **`ribbon[]`** groups of commands (`label`, `call`, optional `args`,
  `form`, `confirm`) appear on their tab while the component is on the
  bench (below).
- **`binds.consul: "@self"`** means the service that declared the component
  through `Meta.gui`. A host, port or IP here is rejected.
- **`binds.grpc`** names the proto service that tiles and commands call.
  For a binary that serves several, list them:
  `"grpc": ["power_device.PowerSupplyService", "config_device.ConfigDeviceService"]`.
  A plain method name (`"call": "SetVoltage"`) calls the first service. Call
  another one as `"<service>/<Method>"`, e.g.
  `"config_device.ConfigDeviceService/SetDeviceType"`. That works in `call`,
  `rpc`, ribbon commands, frame tiles (`ctx.call`) and Qt tiles
  (`ServiceBridge.callService`). The linter rejects a service that is not
  listed.
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
sets `ui_layer`. Multi-service projects don't get one yet, unless the
GUI type is **WASM panel**. With that type, every layout gets a component
per service registration whose main tile is a generated Qt for
WebAssembly panel. It is built from `gui_wasm/` with `build_wasm.bat` or
`.sh`, which also install it when `MM_SERVICES` points at `web/services`.
The panel shows one group per RPC and calls the service over gRPC.
**C++ services** declare their folder the same way: the C++ runtime reads
`<PREFIX>GUI` (e.g. `HELLO_GUI=HelloService1.0.0`) into the `gui` setting,
registers it as `Meta.gui` and serves the folder over `ServiceGui`
(ADR-031), with the same checksum as a Python service. It finds the folder
in `<PREFIX>GUI_DIR`, else `gui/<gui>`, `ui/<gui>`, `GUIs/<gui>`, `<gui>`
or `../interfaces/gui/<gui>` beside the executable (or the working
folder).

**A Qt service's own window as its classic panel.** A Qt Widgets service
can ship its desktop window, ported to WebAssembly, as the classic panel
next to its `component.json`: put the Emscripten `.js` and `.wasm` at the
top of the GUI folder. Operators switch with **User → Service view →
Tiles | Service window**. For a service that is on Consul and not on the
broker, the classic loader routes the panel's `window.callMicroservice`
calls over gRPC:

- the panel gets a token as `Module.endoToken`; it sends that as the
  service name, so its calls (timer-driven ones included) reach it;
- `"Method"` goes to whichever bound service has that method, found by
  reflection; `"<package.Service>/Method"` to that service;
- the request is the proto message as JSON (`args[0]`), the reply has a
  broker reply's shape (`{ result: 'pass', result_data }`) plus
  `result_json`, the whole response.

A broker (Python) service's panel is called through the broker, as before.
The port keeps the window's `.ui` and replaces each device call with an
RPC; it links Qt Widgets only. WebAssembly has no nested event loop, so a
dialog opens with `open()`, never `exec()`.

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
  *unknown signal* and fill in once their service is up. How the host bus
  in the window and the bridge share this work is drawn in
  [Diagrams → Live signals](../../../../docs/architecture/diagrams.md#live-signals-host-bus-and-bridge).
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
| `flow-view` | the *Diagram* tab of flow files and run groups in the project view (file views for types `flow-graph` and `flow-group`) |
| `robot-grid` | the *Grid* tab of suites and resources in the project view (file view for type `robot-grid`) |
| `robot-gen` | *Robot Resources* in the Developer tab's Build group |
| `graph-studio` | *Graph Studio* in the Build group; opens its own window (desktop app only) |

- **Bundled** plugins live in `web/plugins/<id>/` and are listed in
  `web/plugins/index.json`; **installed** ones in
  `%APPDATA%\DevAtServGUI\plugins\<id>\` (they win over a bundled plugin of
  the same id). Installed plugins cannot run in their own window.
- A plugin is a `plugin.json` (`web/js/endo/contract/plugin.schema.json`)
  plus ES modules. Contribution points: `kinds`, `ribbon.groups`,
  `commands`, `navigators`, `stage.views`, `dock.sections`,
  `drawer.tabs`, `file.views`. A contribution names a module (`entry`) or a
  view or action the shell already has (`shell`).
- A **file view** (`file.views`) draws one view type a project's runner
  lists for a file (`for`, e.g. `["flow-graph"]`); it is always a module.
  The project view pushes the runner's data to it as the frame's selection,
  and the view's `ctx.reveal({ node })` shows that node in *Script*.
- A kind's `schema` and `needs` are used when components are linted, so a
  tile of a plugin kind is checked like a core one.
- `node tools/endo-lint.js web/plugins` lints the plugin manifests;
  `test/endo/test_endo_plugins.js` tests the bundled ones.
- **Plugin code runs in sandboxed frames** (`"isolation": "frame"`), like
  frame tiles: the GUI sends the plugin's modules to the frame and answers
  its `ctx` calls. `schema` plugins contain no code.
- **Window plugins** (their own window, may start processes) load only if
  they are on the **allow-list**: `windowPlugins` in the GUI's
  `settings.json`, changed under *Administrator → Plugins*. Without the
  setting, the bundled ones (Graph Studio) are allowed and installed ones
  are not.
- Each frame is a separate process, so a bench with many frame or plugin
  tiles uses noticeably more memory than one of plain tiles.

## Test projects

A test project is a folder the Manager GUI exports services into, so test
authors get working Robot Framework keywords without copying generated
files around by hand.

A complete sample — generated resources, starter files and a hand-written
API suite — is in `examples/hello_test_project/`.

**Open one:** *Developer → Test project → Open project* (or the folder chip
in the developer inspector). A folder that is not a test project yet can be
initialized; existing files are never moved or changed.

**See what's in it:** *Developer → Test project → Project view*, or
**Project** in the left pane's switcher (opening a project lands there too). The sidebar lists every file grouped into suites,
resources, protos and configuration, each marked **gen** (generated),
**starter**, **yours** or **manifest**. A generated file edited since the last
export shows an amber dot, a deleted one a red dot. The overview shows the
exported services with their file state and the command that runs all
suites; from there you can **Re-export** a running service or export
another one.

**See a suite as a grid.** Suites and resources also open with a **Grid**
tab: one row per statement, the keyword it calls, then one cell per argument
labelled with the parameter it fills — through `Run Keyword`-style keywords
too. Keywords are resolved the way the run resolves them (the project's
interpreter, Robot's parser and Libdoc): BuiltIn, the file's libraries and
resources and theirs, and its own keywords. Unknown keywords, values a
keyword does not take and required parameters left out are marked; imports
that cannot be read are listed. Hover a keyword for its parameters and
documentation, click a line number to find it in *Script*. **Click a step to
change it**: the keyword with completion over everything the file can call,
then one input per parameter (required ones marked, defaults shown, `*args`
and named values added with **+**). FOR / IF / ELSE IF / WHILE / EXCEPT rows
edit their header; blocks and branches are added (**+ Add step** or a FOR /
IF / WHILE / TRY block — and THREAD, name and daemon, where the project's
Robot is RobotFramework AIO's; + ELSE IF / ELSE / EXCEPT / FINALLY; steps go
inside a block from its END row, *+ Add step here*, or from a block or branch
row, *Inside*), moved and
deleted; setups and teardowns use the keyword editor; settings, imports and
variables edit their values; **+ Setting** next to a test's or keyword's
name adds its own `[Documentation]`, `[Tags]`, `[Setup]`, `[Teardown]`,
`[Timeout]`, `[Template]` or `[Arguments]`; tests and keywords are added,
renamed and deleted, and a toolbar adds a test, keyword, setting or variable. Every value
input completes the `${variables}` in scope at that step. The runner applies
each change with Robot's own model, so only that part changes (indentation,
comments, line endings kept); the result lands in *Script* as an unsaved
change, and *Undo last change* takes a grid change back. Generated files
stay read-only (`robot-grid` plugin; `/api/test-project/view-edit`).

**Edit suites in place.** Selecting a suite, a starter file or one of your
own files opens it in an editor with Robot Framework highlighting — section
headers, test and keyword names, the keyword each line calls, `[Settings]`,
control words (FOR, IF, TRY, WHILE, THREAD, …), imports, named arguments,
variables, comments — and line numbers (Tab inserts four spaces, Enter
keeps the indentation, **Ctrl+S** saves). **Go to Definition** (**F12**, or
**Ctrl+Click**) on a keyword, an import or a flow's `"keyword"` or
sub-flow `"file"` opens where Robot finds it — the file's own keywords, its
resources and theirs, its Python libraries, BuiltIn — at its line; a
definition outside the project (a library, BuiltIn) is shown read-only. A save refuses to overwrite a file that changed on disk since you
opened it, and offers *Overwrite* or *Reload* instead. On save — or with
**Check** — the bridge parses the file with Robot Framework and lists syntax
problems by line; click one to jump there. Unsaved text survives a reload
and is offered again when you reopen the file. Generated files and the
manifest open read-only. **New suite…** (overview, or **+** next to
*Suites*) creates a suite already wired to an exported service's keywords.

**New flow.** The **+** next to *Flows* (shown even while a project has no
flow yet, when its runner has flow files) asks for a name and the resource
files whose keywords the flow may use. It writes
`flows/<name>.flow.json` from the runner's template — one test with one
step to replace — and opens it on its *Diagram* tab, ready for
*Edit flow* (below).

**Export a service:** select a Consul-registered service, then *Developer →
Selected service → Add to project* (or the button in the inspector's API tab).
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
`python -m robot -d results testsuites/<service>_smoke.robot` — or run it in
the GUI, see [Running tests](#running-tests).

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

### Test runners

`testproject.json` names the project's **runner**, and everything
runner-specific comes from it: which files are tests, flows and resources
(and what the sidebar calls them), the starter files, the syntax check, the
command a run starts and how its results are read. The GUI, the manifest,
proto handling, the plan/apply safety rules and running stay the same for
every runner. Two come with the Manager GUI:

| Runner | Tests | Calls the services through | Results |
|---|---|---|---|
| **Robot Framework AIO** (`robotframework-aio`) | `.robot` suites and `*.flow.json` flows | generated keyword resources | `output.xml`, Log, Report |
| **Temporal (Python SDK)** (`temporal-python`) | pytest files (`*_test.py`, `test_*.py`) that run Temporal workflows | generated activities | JUnit XML |

**Choose one** when you initialize a folder: the dialog lists the runners
with the structure each one writes, and preselects the runner whose files
the folder already holds. A project keeps its runner; to move a suite to
another runner, initialize a new project with it and export the services
again.

Structure for **Temporal (Python SDK)**:

```text
<project>/
├─ testproject.json                   manifest: runner, layout, what was exported
├─ conftest.py                        Temporal server + worker for the tests (starter)
├─ pytest.ini, requirements.txt       test discovery; temporalio, pytest (starter)
├─ activities/<service>/*.py          one activity per RPC, ACTIVITIES in __init__.py (generated)
├─ workflows/<service>_smoke.py       starter workflow per service
├─ tests/<service>_smoke_test.py      starter test per service
└─ proto/<service>/*.proto            copied protos, when available
```

The activities find the service by name through Consul (`CONSUL_ADDR`), or
at `<SERVICE>_ADDR` (e.g. `HELLO_ADDR=127.0.0.1:50051`) when set. A test
runs a workflow with the `temporal` fixture —
`temporal(Greet.run, "bench", workflows=[Greet], activities=ACTIVITIES)` —
against the Temporal server at `TEMPORAL_ADDRESS` or, when that is not set,
a local dev server (the `temporal` CLI at `TEMPORAL_CLI`, else downloaded by
the SDK once). Put these variables, and an interpreter with `temporalio`,
in the project's **Run settings**. Run variables reach the tests as
environment variables; *Stop* lets the running test end and skips the rest.

**Another runner** is one class implementing
`MicroserviceBase/ports/test_project.py`'s `TestProjectRunner`, registered
in code or — from its own package, without changing this one — as an entry
point in the group `microservicebase.test_runners`. See the guide *Adding a
test runner* and ADR-032.

### Running tests

Every file the project's runner can run gets a **▶** in the sidebar (on
hover) and a **Run…** button in its editor; **Run all…** on the overview
runs the whole suites folder. For Robot Framework AIO that is `.robot`
suites and **flow files** (`*.flow.json`, listed under *Flows*): a test plan
drawn as a graph that the RobotFramework AIO fork's `robot.flow` parser
builds into a suite at run time.

- **Script, Diagram, Robot** — a flow file opens with three tabs. *Script*
  is the JSON, the only thing you edit. *Diagram* draws the flow: a lane per
  phase, gates as hexagons, a loop as a frame with its body, `next` return
  and recovery (`on_failure` → `continue` / `abort`), decisions with their
  yes / no branches (drawn by the `flow-view` plugin; turned off, the tab
  says so). *Robot* shows the suite the flow becomes. Both are made
  by the fork itself (`robot.flow`, with the project's run settings) from
  the text in *Script*, unsaved changes included. Click a node to find it in
  *Script*; a flow the fork refuses shows its message and a link to the
  node or line it names.
- **Sub-flows** — a step of kind `flow` calls another flow file with
  arguments (`{"kind": "flow", "file": "sub/step.flow.json", "args": {…}}`).
  The Diagram draws it as one box with its arguments, and its **+** opens
  the sub-flow's steps in place. Those steps belong to the sub-flow's own
  file, so they are shown, not edited, here.
- **Edit flow** — the button above the Diagram (while the file is open in
  *Script*) turns on a palette and drop zones: drag a palette item —
  Keyword, Gate, Sleep, Sub-flow, Decision, Loop, Try, Test — onto a **+**
  to insert it; drag a step onto another **+** to move it; click a step for
  its fields (*Apply*, *Delete*, *Wrap in loop / try*); *Undo* takes the
  last change back. Every change goes through the runner
  (`adapters/test_project/flow_edit.py`), which rewires the edges, has the
  fork validate the result and writes it back to *Script* one node and one
  edge per line; a change that would make the flow invalid is refused with
  the reason. One edit at a time; a drop while one is in flight says so.
- **Run dialog** — variables for this run (`NAME=value`, one per line; they
  override the file's own values) and **Dry run** (check keywords and
  arguments, execute nothing). Both are remembered per file.
- **Runs** (sidebar, under *Overview*) — the run being shown: its verdict
  (**Pass**, **Fail**, **Unknown**, **Skipped**, **Error**), what was run with
  which variables, the console as it happens and, when it ends, one row per
  test with its message. **Log** and **Report** open Robot's `log.html` and
  `report.html` in the browser; **Run again** repeats it with the same
  variables. The history below lists earlier runs; click one to see it.
- **Stop** ends a run gracefully: the running keyword finishes, teardowns
  still run and the reports are written. While it is stopping, **Force stop**
  kills it at once. Only one run per project at a time — two runs would
  fight over the same bench.
- A toast reports the verdict when a run finishes, wherever you are in the
  GUI; the sidebar's *Runs* entry pulses while one is in progress.

Each run gets its own folder, `results/<date-time>_<name>/`, with the
runner's output, `console.log` and `run.json` (what ran, when, the outcome),
so the history survives restarts. **UNKNOWN** is a verdict of its own: the
bench was not ready (a flow's gate timed out), so nothing was tested.

**Run settings…** (overview or *Runs*) are stored in `testproject.json`
under `"run"`, so a project runs the same way for everyone who opens it:

| Setting | Meaning |
|---|---|
| Interpreter | Python that runs the tests; empty means the bridge's own (the one in *Settings*). |
| PYTHONPATH | Folders put in front of the path, relative to the project root — e.g. the `src` of a RobotFramework AIO checkout that brings `robot.flow`. |
| Extra arguments | Added to every run (one per line). |
| Environment | `NAME=value` pairs for every run. |

### Pause, resume, stop and continue a flow

With a RobotFramework AIO fork that has flow control (`robot/flow/control.py`),
a running flow can be held and let go from **Runs**:

- **Pause** holds it at the next step boundary — between two steps, at a
  loop iteration, between two polls of a gate, never inside a keyword (a
  running `Sleep` ends first). Loop deadlines, gate timeouts and watchdogs do
  not run on while it is paused. The meta line says where it holds (phase,
  loop and iteration) and the Diagram marks the step in amber. **Resume**
  lets it go on.
- **Stop** on a flow is the flow's own: it ends at the next step boundary,
  writes a **checkpoint**, ends the running test UNKNOWN, runs the teardown
  and starts no further test. If a step runs on for more than a minute, the
  usual graceful stop follows; a second **Stop** kills.
- **Continue from checkpoint** (on a flow run that was stopped or broke off)
  starts a new run that skips the test phases already finished and goes on
  with the interrupted loop where it stopped, with its saved variables; the
  setup phase runs again. The new run says which run it continues.
- **Step mode** (the Run dialog of a flow) pauses before every step of the
  test phases; **Next step** goes on one step.
- **Run groups**: Pause / Resume act on every member; each member's header
  has its own, for that member alone (its gates' partners may then time
  out waiting for it).

Under the hood the run's signal store is the control channel (the fork's
`python -m robot.flow control <store> pause|resume|stop [--rig member]`, sent
with the project's interpreter); every flow process publishes its state
there. Group members run as rigs named after their ids.

### Debugging

**Debug** next to *Run…* in a suite's or flow's editor runs it under the
debugger, with the variables of its last run.

- **Breakpoints**: click a line number in the editor (a red dot), or the dot
  at the top-left corner of a step on the Diagram. A breakpoint anywhere in a
  step of a flow file is the step's; in a sub-flow's file it stops in every
  call of that sub-flow. Breakpoints are kept per project in the browser and
  can be set or removed while a run is being debugged.
- When the run stops, **Runs** shows the debug panel: the source with the
  line it stopped at (and its breakpoints, which can be clicked there too),
  the **call stack** — flow steps, sub-flow steps (`<sub-flow>::<step>`),
  keywords, Python functions — with their files and lines, the
  **variables** of the selected frame (lists and dictionaries expand), and a
  **console**: `${var}` shows a value, any other line runs a keyword (cells
  separated by two spaces), and where the run is stopped in Python, a Python
  expression. The editor and the Diagram of that file mark the line and the
  step.
- **Continue** (F5), **Step Over** (F10), **Step Into** (F11: into a
  keyword, a sub-flow or the Python function of a keyword of your library),
  **Step Out** (Shift+F11), **Pause**; **Stop** ends the run gracefully, also
  while it is stopped.
- **Into Python**: Step Into on a keyword of your own Python library stops at
  the first line of its function; Step Over / Into / Out then move through
  the Python code (yours, not Robot Framework's or installed packages), and
  when the function returns the run stops at Robot's next step.
- **Stop when a keyword fails** stops where a keyword fails, before its
  callers report the failure.

Debugging is the runner's (`TestProjectRunner.can_debug`): for Robot
Framework AIO, `flow_debug.py` is the listener in the Robot process and
`debugging.py` the bridge's side. The VS Code extension uses the same
listener.

### Run groups: processes that meet

Some tests are more than one process: two blades on one bench, a driver and
a checker, each waiting at a gate for what the other publishes. RobotFramework
AIO's flows do this through the bench's signals — one flow runs twice with
different variables (`BLADE=IVI PEER=ADAS`, then swapped), each announces
itself with `Set Signal` and gates on its peer. A **run group** is that
pairing, kept with the project:

```json
"groups": [
  { "id": "rendezvous", "title": "IVI + ADAS rendezvous",
    "env": { "FLOW_DEMO_SIGNALS": "${RUN_DIR}/signals.json" },
    "members": [
      { "id": "IVI",  "target": "pairs/rendezvous.flow.json", "variables": { "BLADE": "IVI",  "PEER": "ADAS" } },
      { "id": "ADAS", "target": "pairs/rendezvous.flow.json", "variables": { "BLADE": "ADAS", "PEER": "IVI" } } ] }
]
```

- **Sidebar → Run groups** lists them; **+** (or *Edit…* on a group) opens
  the editor: an id, a title, 2–8 members (id, the file it runs, its
  variables) and environment for all of them. `${RUN_DIR}` in a value is the
  run's own folder — a fresh meeting place per run, so a flag left by the
  previous run cannot open a gate — and `${PROJECT_DIR}` the project root.
  Saved in `testproject.json` under `"groups"`.
- **Diagram** (a group of flow files; drawn by the `flow-view` plugin): one
  column per member, read top to bottom, and a dashed arrow across the
  channel wherever a step of one member sets a signal that a gate of another
  waits for. The arrows are read from the flows — a `Set Signal <name>
  <value>` step and a gate whose first argument is the same signal (with
  `==`, the same value), after each member's variables are filled in.
  Click a step to open that member's file on it.
- **▶ / Run…** starts every member at once. *Runs* shows one console column
  per member with its own verdict, **Log** and **Report**; *Results* lists
  every member's tests. The run's verdict is the worst of the members'
  (error, then fail, then unknown). **Stop** stops them all, gracefully
  first. Each member writes to `results/<run>/<member>/`; `console.log` of
  the run interleaves their lines as `[member] …`.
- **Where members meet.** RobotFramework AIO ships `robot.flow.signals`
  (`Set Signal`, `Get Signal`, `Signal Should Be`) for flows to coordinate.
  Every run gets its own store: the members of a group run share
  `results/<run>/signals.json`, a single flow run has one in its folder
  (`ROBOT_FLOW_SIGNALS`, set by the runner adapter's `group_env` /
  `run_plan`; one in the run settings' or the group's environment wins). Two
  runs can never read each other's signals.

#### Resources of a run: RAM and CPU over hours

Tick **Record RAM and CPU of the run** in the Run dialog (of a file, or of a run
group; remembered like the other choices, kept by *Run again*, off by default and
never for a dry run) and the run is watched by a **separate process**
(`adapters/test_project/resmon.py`, so its own work is not counted and it keeps
recording if the runner misbehaves). Every 5 s it samples each process of the run,
and the processes those started:
private memory, working set, CPU (percent of one core), threads and handles, plus
the machine's CPU and memory. Each sample is one line of
`results/<run>/resources.jsonl` -- nothing is lost if the machine goes down.

When the run's processes have ended it writes **`resources.html`**, offered as
**Resources** next to Log and Report. It shows:

- a verdict per process and for the run: **STABLE**, **GROWING** or **SHORT**
  (too little time after the warm-up to judge);
- per process: private memory after the warm-up → at the end, its peak, its trend
  in MB/h, working set, CPU mean / p95 / max, threads and handles;
- one chart over time with a band per metric (private memory, working set, CPU,
  threads, handles, the machine's CPU and memory), shown or hidden with checkboxes,
  as are the processes and the memory trend (dashed). Hovering shows every visible
  value at that moment, with the time since the start and the clock time; dragging
  zooms into a period (double-click or *Reset zoom* for all of it); the arrow keys
  step through the samples. The page needs no network: the samples are in it.

How it judges: the first 10 % of a process's time (at most 10 min) is warm-up, the
last 5 % (at most 1 min) wind-down -- Robot merging its output and writing the log
and report, a short burst at the very end -- and both are left out of the trend
(not of the peak). A least-squares line through the rest gives the trend. GROWING means a
trend above **10 MB/h** *and* more than 5 % above the level after the warm-up;
SHORT means less than 10 min after the warm-up.

`MM_RESMON_INTERVAL` in the run settings' environment sets the seconds between
samples. From the command line, or for processes started elsewhere:

```
python resmon.py record --out r.jsonl --report r.html --pid DRIVER=1234 --pid CHECKER=5678
python resmon.py record --out r.jsonl --match "robot.*endurance" --duration 8h
python resmon.py report r.jsonl -o r.html          # any time, also while recording
```

`--max-growth` (MB/h) and `--min-steady` change the thresholds; `report` exits
with 3 when a process is GROWING, for a build to fail on it.

#### Live Diagram of a run

A run of a flow file, or of a group of flow files, shows its **Diagram
beside the console** (*Runs* → *Console*; the **Diagram** button in the tab
row hides or shows it). The step each process is in right now pulses in
blue, the loop or try around it is outlined, a step that just failed turns
red for a few seconds, and every step carries a count: ✓ passed, ✗ failed.
The divider between console and Diagram drags (or moves with the arrow
keys); **Fit / 75% / 100%** size the drawing, and at 75% and 100% it scrolls
sideways. The view updates about once a second; the steps a process went
through in between are replayed quickly (at most 8, within 0.6 s): **Tail**
flashes them in order and lets them fade, **Hop** moves the mark through
them, **Off** shows only where the run is now. Reduced motion turns the
replay off. The Diagram keeps the running step in view, except for a few
seconds after you scroll it yourself. A finished run keeps its counts: where
the deviations of a long night were. Inside a sub-flow the position names
the step as `<sub-flow>::<step>`: an opened sub-flow marks that step, a
closed one lights its box. Steps Robot reports as not run — the branch a
decision did not take — never count as the position.

How it knows: `robot_boot.py` (which starts every GUI run) loads
`adapters/test_project/flow_position.py` into the Robot process. It numbers
every item the fork builds for a flow node (through the builder's emitters,
before Robot builds the suite) and, as a Robot listener, writes the node the
main thread is in, each node's counts and the trail of the last 30 steps
entered (numbered, so the view replays only what it has not shown) to
`flow_position.json` in the
run's folder, replaced whole on every change. The bridge adds it to
`/run/status` (`position`, or `member_positions` for a group run), which the
view already polls. The cost is a dictionary look-up per keyword and a small
file write per step (a few a second); the Diagram is drawn once and only its
marks move. Runs from the command line and dry runs write nothing.

All of this is runner-neutral: the adapter says which files it can run, the
exact command (`run_plan`) and how to read the outcome (`read_results`),
and which extra views a file has (`file_views`, `inspect_file`: views of
type `flow-graph` or `code`) and a run group has (`group_views`,
`inspect_group`: `flow-group`); the bridge (`/api/test-project/run` — with
`group` for a run group —, `/run/status`, `/run/stop`, `/runs`,
`/run-settings`, `/inspect`, `/view-edit`, `/groups`, `/group/inspect`) and this view stay
the same for any runner; a view type is drawn by whichever plugin
contributes a `file.views` entry for it.

## Signal Graph Studio

**Developer → Build → Graph Studio** opens the Signals & Blocks graph
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
  a wiring check, with the vendored runner `graph-studio/tools/run_cluster.py`.
  The signal services it runs are not vendored: they come from the Live
  panel's signals root, else **`MB_SIGNALS_ROOT`** (a folder containing
  `signal_graph/`, `signal_discovery/` and `common/`); without one the button
  says what is missing. The cluster's signal-discovery listens on the port
  of the Live panel's *signal-discovery host:port*, so a bench job that
  already owns the default port is no obstacle. When `grpcio-reflection` is
  installed in the interpreter that runs it, every server of the cluster
  also answers gRPC reflection, so the Manager GUI lists a graph's methods. Deploying the generated Nomad job
  and using ◉ Monitor is the supported path for a real bench.
- **Library…** has two tabs: *New block skeleton* scaffolds a block package
  (`blocks.py`, test stub, README, file header) with the catalog hints
  already in place and, with the *layout* box ticked, the hexagonal skeleton
  around it (`ports/<pkg>_port.py`, `adapters/mock.py`,
  `adapters/grpc_client.py`, `adapters/registry.py`); it never overwrites an
  existing file, so re-running it on an older package only adds what is
  missing. *Regenerate catalog* runs the generator over chosen sources and
  hot-reloads the palette without a restart.

Live lookups, Monitor and Set signal need `grpcurl` on `PATH` (as the API
Explorer does). Deployed graph services serve no gRPC reflection, so the vendored
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
- Closing the studio keeps its session. Opening it again shows the same
  graph, view and selection. A saved file is read again from disk, and
  unsaved edits come back still marked unsaved (`gs-session` in the
  studio's local storage). A running cluster and the monitor do not
  survive a close.
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
bound to a loopback address the Electron GUI is admitted as well. It loads
from `file://`, which the browser reports as `Origin: null` on its HTTP
requests and as `Origin: file://` on its WebSocket handshakes -- live
signals use the latter, so both spellings are admitted together.

**Configure** without touching code -- highest priority first:

| Where | Form |
|---|---|
| CLI | `python start_bridge.py --allowed-origins "http://10.0.0.5:1112,null,file://"` |
| `python/config.json` | `"bridge_allowed_origins": ["http://10.0.0.5:1112", "null", "file://"]` |
| Environment | `MB_BRIDGE_ALLOWED_ORIGINS=http://10.0.0.5:1112,null,file://` |

Rules:

- An origin is `scheme://host[:port]` -- no path, no trailing slash.
- `null` and `file://` admit the Electron GUI -- list both, or its live
  signals stay disconnected. Add them yourself when the bridge is bound to a
  non-loopback address such as `0.0.0.0`; they are left out of the default
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
