# Service Creator Wizard — Manager GUI

Generate a complete service scaffold (proto + domain + adapter + build
scripts + clients + Nomad spec) from the Manager GUI without writing
any boilerplate yourself.

> 📄 *Also available as HTML:* [`../html/service_creator.html`](../html/service_creator.html)
>
> Companion docs: [← Docs index](../../../../examples/docs/md/index.md) ·
> [MinGW (MSYS2) setup](../../../../examples/docs/md/mingw_setup.md) ·
> [Qt6::Grpc setup](../../../../examples/docs/md/qt_grpc_setup.md) ·
> [Service creation tutorial (manual)](../../../../examples/docs/md/service_creation.md)

---

## When to use the wizard

| You want to… | The wizard is the right tool? |
|---|---|
| Create a brand-new service from a description of methods | ✅ Yes |
| Import an existing `.proto` file and get a matching server + client | ✅ Yes — `Import .proto…` button on Step 3 |
| Generate multiple services from one or many `.proto` files | ✅ Yes — pick the layout on the import dialog: `multi_proto` (single binary, N services on one port), `monorepo` (single project, N executables), or `separate` (N independent projects). See [Step 3 — Import](#b-import-from-a-proto-file). |
| Edit an *existing* service | ❌ No — edit the source files directly. Re-running the wizard would overwrite. |
| Add a single new RPC to an existing service | ❌ No — easier to edit `.proto` + adapter by hand. See [service_creation.md](../../../../examples/docs/md/service_creation.md). |

The wizard is equivalent to `mb-scaffold` (the
[command-line tool](#alternative-the-mb-scaffold-cli)) — same generator
backend, just nicer to drive interactively.

---

## Prerequisites

1. **MicroserviceBase Manager GUI** running. See the
   [Manager GUI setup](#starting-the-manager-gui) below.
2. **Bridge** running (the GUI launches it automatically; for headless
   use start with
   `python -m MicroserviceBase.adapters.ui_bridge.fastapi_bridge`).
3. *(For C++ scaffolds)* The toolchain you'll build with —
   [MinGW (MSYS2)](../../../../examples/docs/md/mingw_setup.md) for Google grpc++ services or
   [Qt-installer](../../../../examples/docs/md/qt_grpc_setup.md) for Qt-native clients.

---

## Starting the Manager GUI

### One-time fresh-PC setup

```cmd
cd MicroserviceBase\MicroserviceManagerGUI
setup_and_start.bat
```

This downloads a portable Node.js (~30 MB), runs `npm install`, and
launches the GUI. Subsequent runs skip the download — just
`npm start` or re-run `setup_and_start.bat`.

### From an existing dev install

```cmd
cd MicroserviceBase\MicroserviceManagerGUI
npm start
```

The Electron window opens. The bridge starts in the background on
`http://127.0.0.1:1112`.

![Microservice Manager main window — empty state](../img/gui_wizard_01.png)

The header shows the active **Bridge**, **Consul**, and **Nomad**
status pills plus a quick **Connect** button for brokers. The left
sidebar lists registered services (empty here because no service is
running yet).

---

## Reaching the wizard

Click the **Service Creator** tab in the **top navigation bar** —
between *Services* and *Service Network*. It opens the wizard in the
main pane.

![Service Creator tab highlighted](../img/gui_wizard_02.png)

You don't need a broker connection to use the wizard — it talks
directly to the bridge over its REST API.

---

## Step 1 — Basic Info

The first step captures the project's identity and metadata.

![Step 1 — Basic Information filled in](../img/gui_wizard_03.png)

| Field | Required | Notes |
|---|---|---|
| **Service Name** | ✅ | PascalCase. Becomes the project folder name, the C++ class name, and (for monorepo) the parent directory. e.g. `SampleService`, `PowerServices`. |
| **Version** | ✅ | Semver. Default `1.0.0`. Surfaces in the .proto package, generated CMake `project(... VERSION ...)`, and `service_config.json`. |
| **Description** | optional | Longer free-text. Goes into the README. |
| **Short Description** | optional | One-liner for the Manager GUI's service card. |
| **Group** | optional | Logical grouping shown in the GUI sidebar (e.g. "Sensors", "pps"). |
| **Tag** | optional | Free-form tag string (e.g. `v1`). |
| **Routing Key** | auto | Auto-generated from the service name (e.g. `service.sample_service`); editable. Carried in the generated config for back-compat — gRPC services do not use routing keys, so it's effectively cosmetic for new (gRPC) scaffolds. |
| **Transport Type** | dropdown | `RabbitMQ` (default) or `EventBus`. Carried into the generated Python `main.py` to choose the legacy transport adapter. C++ scaffolds ignore this — they always emit a gRPC server with `ServiceRunner`. |

> **Naming tip.** If you're going to import a `.proto` later, set
> Service Name to whatever the proto's `service X { ... }` block
> declares. That way the generator doesn't have to choose for you.

Click **Next** to advance.

---

## Step 2 — Technology

Pick the language, GUI variant, and infrastructure files to generate.

### Language

| Choice | Generates |
|---|---|
| **Python** | `runtime/`-style Python service with FastAPI bridge integration. GUI options are `none` or `html` only. |
| **C++** | CMake project, hexagonal architecture, Google grpc++ server. GUI options expand to include Qt variants. |

### GUI Type

| Variant | Output | Toolchain doc |
|---|---|---|
| **None** | Service-only, no UI | — |
| **HTML / JS** *(Python only)* | Browser-based UI loaded by Manager GUI | — |
| **Widget** *(C++)* | Native Qt Widgets desktop client | [MinGW setup](../../../../examples/docs/md/mingw_setup.md) |
| **QML** *(C++)* | Qt Quick UI in C++ client | [MinGW setup](../../../../examples/docs/md/mingw_setup.md) |
| **WASM** *(C++)* | Qt Widgets compiled to WebAssembly | [WASM service guide](../../../../examples/docs/md/wasm_cleware_service_guide.md) |

### Client gRPC Stack *(C++ only, when GUI ≠ None)*

Three options, all wire-compatible (you can mix any client variant
with any server):

| Choice | Where client lives | Toolchain | What you get |
|---|---|---|---|
| **Google grpc++** *(default)* | `client/` (next to server) | MSYS2 MinGW (same as server) | Console + optional Qt6 Widgets GUI from MSYS2's qt6-base. JSON-based dispatch via `google::protobuf::util::JsonStringToMessage`. |
| **Qt6::Grpc + Qt6::Protobuf** | `qt_client/` (separate project) | Qt-installer MinGW (separate from server) | Qt-native RPC types with signal/slot integration. **Requires Qt 6.8+ with Qt GRPC + Qt Protobuf modules.** Server stays on MSYS2. See [Qt6::Grpc setup](../../../../examples/docs/md/qt_grpc_setup.md). |
| **Google grpc++ via vcpkg + Qt MinGW** | `qt_client_grpcpp/` (separate project) | Qt-installer MinGW (same as server) | One toolchain end-to-end. vcpkg builds grpc/protobuf/abseil with Qt's MinGW. **First build ~30–60 min**; subsequent instant via cache. Also re-targets the server's CMakeLists to use vcpkg. See [vcpkg setup](../../../../examples/docs/md/vcpkg_setup.md). |

If you pick **Qt6::Grpc**, the wizard shows a yellow alert with the Qt
version requirements — don't skip reading it; Qt 6.7 has the modules
as Tech Preview (must be ticked manually in Qt Maintenance Tool), Qt
6.6 doesn't have them at all.

If you pick **Google grpc++ via vcpkg + Qt MinGW**, the wizard shows a
blue prerequisites alert reminding you to set `VCPKG_ROOT`,
`QT_MINGW_BIN`, and `QT_DIR` before running `build_qt.bat`. First-time
build is slow because vcpkg compiles boringssl + abseil + protobuf +
grpc from source with Qt's gcc.

**With Google grpc++ selected** — the simplest case, no Qt-installer
needed:

![Step 2 — C++ + Widget + Google grpc++](../img/gui_wizard_04a.png)

**With Qt6::Grpc selected** — the alert with the version requirements
appears below the radio:

![Step 2 — C++ + Widget + Qt6::Grpc with version-requirement alert](../img/gui_wizard_04b.png)

**With Google grpc++ via vcpkg + Qt MinGW selected** — emits
`qt_client_grpcpp/` plus shared `triplets/` and `ports/` overlays at
project root. See the [vcpkg setup guide](../../../../examples/docs/md/vcpkg_setup.md) for the
prerequisites and full workflow including the gcc 13.1.0 ICE
workaround patch the generator emits automatically.

### Server Toolchain *(C++ only)*

Independent of the Client gRPC Stack choice. The server is always
Google grpc++; the toggle just picks how it's compiled and from which
prebuilt:

| Choice | What you get |
|---|---|
| **MSYS2 prebuilt** *(default)* | `mingw-w64-x86_64-grpc` from MSYS2's pacman tree. Build via `build_deploy_msys2.bat`. No vcpkg required. |
| **vcpkg + Qt MinGW** | grpc/protobuf/abseil compiled by vcpkg with the Qt-installer MinGW 13.1.0. Build via `build_qt_vcpkg.bat`. Emits the same shared `triplets/` + `ports/` overlay used by `qt_client_grpcpp/`. |

The wizard auto-suggests `vcpkg` for the server when you pick
`google_vcpkg` for the client (one toolchain end-to-end), but the
toggle is independent — you can pick any combination. The two notable
cases:

- **Client `google_vcpkg` + Server `msys2`** → mixed toolchains.
  Wire-protocol still works, but client and server use different
  libstdc++ ABIs. Wizard shows a warning.
- **Client `google` or `qt` + Server `vcpkg`** → server-only vcpkg.
  The `vcpkg install` populates a cache that's reusable later if you
  switch the client to `google_vcpkg` (same triplet, same overlay).
  Wizard shows an info note.

### Infrastructure files

Three checkboxes for what's generated alongside the service (right column):

- **Nomad job file** (`<service>.nomad.hcl`) — for Nomad deployment
- **Build scripts** (`build_deploy*.bat/sh`) — MSVC, MinGW, MSYS2 variants
- **README.md**

All on by default. Untick any you don't need. The actual Nomad job
configuration (datacenter, driver, CPU, memory, Consul address) is
captured later on **Step 5 — Review & Generate**.

Click **Next**.

---

## Step 3 — Methods

Define the RPC methods. Two paths:

### A. Manual entry

Click **Add Method** and fill in:

| Field | Notes |
|---|---|
| **Name** | PascalCase, e.g. `Greet`, `ReadAnalogInput` |
| **Description** | Goes into the .proto comments + README |
| **Server streaming** | Tick if the method returns `stream <Response>` |
| **Return type** | Conventionally a single field. Default `string`. |
| **Parameters** | Each row: name, type (`string` / `int32` / `bool` / `float` / `double` / `bytes`), required flag, description |

The wizard generates a corresponding `.proto` with `<Method>Request`
and `<Method>Response` messages following the parameter list.

![Step 3 — gRPC Methods with two manual methods](../img/gui_wizard_05.png)

The lower half of this step has a **Pre-generate proto stubs**
section (ticked by default for C++) — when on, the bridge runs
`protoc` at scaffold time so the project builds without needing
`generate_stubs.bat` first. You can leave the `VCPKG_ROOT` /
`protoc path` / `grpc_cpp_plugin path` fields blank for auto-detect.

### B. Import from `.proto` file(s)

Click **Import .proto…** and pick **one or many** `.proto` files from
the OS file picker (the input is multi-select):

![Import .proto file picker](../img/gui_wizard_06.png)

The bridge parses each file via `protoc --descriptor_set_out`. What
happens next depends on what you imported:

| Import shape | Behaviour |
|---|---|
| **One file with one service** | Methods are loaded into the wizard immediately; you advance to Step 4/5 normally. |
| **One file with N services** | A **service picker modal** opens (image below). You tick the services to include and pick a layout. |
| **N files** (multi-select) | Every service from every file is loaded automatically. The layout is forced to `multi_proto` (one binary on one port). The picker modal does not appear — there's no per-file selection because the assumption is "I'm pointing at the proto-set for one device." |

#### Service picker modal (single-file, multi-service path)

![Service picker modal — multi-service .proto with output-layout radio](../img/gui_wizard_07.png)

The modal has three layout options:

| Layout | Result |
|---|---|
| **Single binary, multiple services** (`multi_proto`) | One `.exe` hosts every selected service on the **same** `grpc::ServerBuilder` — one Consul registration, one port, atomic lifecycle. Best for one logical device with multiple capability surfaces (e.g. Power Supply: config + control). |
| **Single project (monorepo)** — N executables (`monorepo`) | One project folder (single `CMakeLists.txt` for C++, single `pyproject.toml` for Python) that produces N entry points sharing the same `.proto`. Each service has its own port and Consul registration. Good for services that may scale independently. |
| **One folder per service** (`separate`) | Each selected service becomes a self-contained scaffold with its own `proto/`, `CMakeLists.txt`, build script, Nomad job, and README. Good for services that ship separately or are owned by different teams. |

#### Inline layout switch on Step 3

After import, Step 3 shows a green summary card with the picked
services and a **layout selector** at the top of that card. You can
flip between `multi_proto`, `monorepo`, and `separate` without
re-importing — the generator picks up the choice when you click
**Save to Path** on Step 5.

> **Note.** The imported `.proto` text is preserved verbatim
> (comments, options, imports). Only the structural metadata
> (services, methods, params) is read out for the wizard's internal
> tracking. The generated adapter and domain stubs use the **real**
> message types from the proto (e.g. `device::ChannelRequest`), not
> fabricated `<Method>Request` names.

> **Imported proto + GUI = smart placeholder code.** Because we can't
> guess how your domain class maps to arbitrary message fields, the
> generated adapter emits `UNIMPLEMENTED` stubs with TODO comments,
> and the GUI client uses JSON serialization for any message shape.
> This compiles immediately; you fill in the body when you're ready.

Click **Next**.

---

## Step 4 — GUI Support *(Python + HTML/JS only)*

> This step is **skipped automatically** for C++ projects (where the
> GUI is defined by the Step 2 GUI Type radio — QML / WASM / Widget)
> and for any project with `gui_type=none`. Skipped steps don't show
> in the left sidebar, so for those flows you go from Step 3
> straight to Step 5.

When the step does show, the top of the panel has a **Generate GUI**
toggle. Off ⇒ no UI files emitted. On ⇒ two tabs appear:

### Tab A — Schema Builder *(recommended)*

![Step 4 — Schema Builder tab with seeded sections + live preview](../img/gui_wizard_04c_schema.png)

A declarative builder that produces a `gui_schema.json`. The Manager
GUI's loader then renders it at runtime — no HTML/JS to maintain by
hand.

- **Layout** — `tabs` / `single` / `accordion`. Drives how sections
  are arranged.
- **Title / Subtitle** — show in the rendered UI's header.
- **Sections** — each section has an `id`, a `label`, and a list of
  components. Click **Add Section** to append; the trash icon
  removes.
- **Components** (4 types):

  | Type | What it does |
  |---|---|
  | **Method Form** | Form that calls one of your gRPC methods. Picking the method auto-populates the field list from the method's params. Per-field widget choices: `text`, `number`, `textarea`, `checkbox`, `select`, `file`. Result-display modes: `text`, `json`, `table`, `image`, `none`. |
  | **Result Table** | Renders the result of a method call as a table; optional auto-refresh interval (ms). |
  | **Static Text** | Plain text/HTML block. |
  | **Live Status** | Polls a method on an interval and renders it through a format string (e.g. `Voltage: {voltage} V`). |

- **Live preview** — below the editor, the schema is rendered via
  `SchemaRenderer` so you see exactly what the user will see.
- **Export as JSON** — download the resolved schema for version
  control or hand-editing.

The wizard seeds an initial schema from the methods you defined on
Step 3 (one section per method, each with a Method Form component).

### Tab B — Custom HTML/JS

![Step 4 — Custom HTML/JS tab with editor + live preview side-by-side](../img/gui_wizard_04d_custom.png)

For when the schema builder isn't enough (charts, third-party
libraries, custom layouts).

- **HTML editor** (left) + **live preview** (right) side-by-side
  with debounced refresh.
- **Reset to Template** restores a default Bootstrap card scaffold.
- **Upload HTML** (button + drag-and-drop into the editor) loads
  your hand-written HTML.
- **JavaScript File** dropzone (below the editor) accepts a single
  `.js` file. Drag-drop or click. The uploaded filename appears as
  a badge and survives navigation between steps.

The editor's text and the JS upload are committed to `_formData`
when you click **Next** (or any sidebar step).

Click **Next** to advance to Review.

---

## Step 5 — Review & Generate

> Note: in the wizard sidebar this step is labelled **Step 5** even
> when Step 4 (GUI Support) is hidden. Skipping a step doesn't
> renumber the remaining ones.

The left card summarises the service:

- **Header** — service name + version, or for multi-service imports:
  service name + a **service-count badge** + a **layout badge**
  (`multi-proto (1 .exe)` / `monorepo (N .exe)` / `separate
  projects`).
- **Language**, **GUI**, **Client gRPC** *(C++ + GUI only)*,
  **Server toolchain** *(C++ only)*, Description, Group,
  **Infrastructure** badges (Nomad HCL / Build scripts / README /
  Proto stubs), and the imported `.proto` file name when relevant.
- **Methods block** — flat list for single-service, per-service
  blocks for multi-service imports. Each method shown as
  `rpc Name(field:type, …) → returnType` with a `stream` badge for
  server-streaming methods.

The right pane has the **Nomad Job Configuration** form (only when
"Nomad job file" is ticked on Step 2):

- **Datacenter** (default `dc1`)
- **Driver** — `raw_exec` (default), `exec` (Linux chroot), or
  `docker` (container)
- **Command path** — absolute path to the service binary/script
- **Consul address** — where the service registers itself
- **CPU (MHz)** + **Memory (MB)** — Nomad resource limits

A help line below the form notes that `<PREFIX>_GRPC_PORT` and
`ADVERTISE_ADDR` are populated automatically from Nomad's dynamic
port allocation; `CONSUL_ADDR` uses the address configured above.

![Step 5 — Review & Generate (monorepo example)](../img/gui_wizard_08.png)

### Generating

Three controls at the bottom:

| Button | Result |
|---|---|
| **Browse…** *(Electron only)* | Pick the output folder via OS dialog (sets the **Output Path** field). Hidden in plain-browser mode where you have to type the path manually. |
| **Download ZIP** | Pure client-side — generates a Python-only minimal scaffold and downloads `<ServiceName>.zip` directly. **Does not** support the multi-service `multi_proto` / `monorepo` / `separate` layouts or the C++ scaffold path; use **Save to Path** for those. |
| **Save to Path** | POSTs to `/api/scaffold/generate-v2` on the bridge. Behaviour by import shape: |

| Import shape | Save behaviour |
|---|---|
| Single-service (manual or imported) | One POST → one project folder. |
| Multi-service import + `multi_proto` | One POST → one project folder containing N services on one binary. |
| Multi-service import + `monorepo` | One POST → one project folder with N executables. |
| Multi-service import + `separate` | N sequential POSTs (one per service); progress reflected in a single summary toast. Partial failures show a yellow "X ok / Y failed" toast. |

A success toast (bottom-right) confirms the path; a red toast
surfaces any error from the bridge.

![Success toast — Monorepo with 6 services saved](../img/gui_wizard_09.png)

---

## What gets generated

For a typical C++ + Widget + Google-grpc scaffold:

```
DemoService/
├── CMakeLists.txt
├── README.md
├── DemoService.nomad.hcl
├── service_config.json
├── set_env.bat / .sh / _mingw.bat / _msys2.bat
├── build_deploy.bat / .sh / _mingw.bat / _msys2.bat
├── proto/
│   ├── demo_service.proto
│   ├── generate_stubs.bat / .sh
│   ├── demo_service.pb.h / .cc
│   └── demo_service.grpc.pb.h / .cc
├── src/
│   ├── main.cpp
│   ├── Settings.h
│   ├── domain/DemoService.h / .cpp
│   └── adapters/api/DemoServiceGrpcAdapter.h / .cpp
└── client/
    ├── CMakeLists.txt
    ├── README.md
    ├── src/client.cpp
    └── gui/                 ← only when GUI ≠ None
        ├── main.cpp
        ├── MainWindow.h / .cpp / .ui
        └── ClientRegistry.h / .cpp
```

For Qt6::Grpc client mode, you additionally get `qt_client/` (a
parallel Qt-installer-toolchain project) — see
[qt_grpc_setup.md](../../../../examples/docs/md/qt_grpc_setup.md) for its layout.

For Google-grpc-via-vcpkg client mode, you additionally get
`qt_client_grpcpp/` plus shared `triplets/`, `ports/grpc/`,
`init_vcpkg_overlay.bat`, and `build_qt_vcpkg.bat` at project root.
See [vcpkg_setup.md](../../../../examples/docs/md/vcpkg_setup.md) for the layout, build flow,
and the gcc 13.1.0 ICE workaround.

For **monorepo** mode, you get one project folder with `src/<svc>/...`
per service, one shared `proto/`, and per-service
`deploy/<svc>.nomad.hcl`.

For **multi_proto** mode, you get one project folder with
**`proto/<file_a>.proto` … `proto/<file_n>.proto`** preserved
verbatim from the imports, one `main.cpp` (or `main.py`) that
constructs every servicer and registers them all on a single
`grpc::ServerBuilder`, and **one** `.nomad.hcl` for the unified
binary. There is one Consul registration with all service
full-names listed in the `tags` field.

For **separate** mode, you get N sibling project folders, each
fully self-contained — the same as running the wizard N times,
just batched.

---

## After generation

1. **Build**:
   - MSYS2: `build_deploy_msys2.bat` (see [mingw_setup.md](../../../../examples/docs/md/mingw_setup.md))
   - Qt-installer + Qt6::Grpc: `qt_client/build_qt.bat` (see [qt_grpc_setup.md](../../../../examples/docs/md/qt_grpc_setup.md))
   - Qt-installer + Google grpc++ (vcpkg): `qt_client_grpcpp/build_qt.bat` and `build_qt_vcpkg.bat` (server) (see [vcpkg_setup.md](../../../../examples/docs/md/vcpkg_setup.md))
2. **Start Consul + Nomad** (one-time per session):
   ```cmd
   start /b consul agent -dev -client=0.0.0.0 -ui
   start /b nomad agent -dev -config=C:\nomad\dev.hcl
   ```
3. **Run the service**:
   ```cmd
   :: From cmd:
   nomad job run deploy\<service>.nomad.hcl
   :: Or directly:
   dist-msys2\run_<service>.bat
   ```
4. **Use the GUI client**:
   ```cmd
   dist-msys2\run_<service>_gui.bat
   ```
5. **Edit the domain logic** — the generator emits TODO stubs in
   `src/.../domain/` and `src/.../adapters/api/`. Fill them in to
   wire up your business logic / hardware access.

For a worked walkthrough of editing the generated code, see
[service_creation.md](../../../../examples/docs/md/service_creation.md).

---

## Alternative: the `mb-scaffold` CLI

The wizard is a thin frontend over the same generator that
`mb-scaffold` calls. If you'd rather script it (for CI / repeat runs):

```cmd
python -m MicroserviceBase.tools.scaffold_cli ^
    --name DemoService --language cpp --gui widget ^
    --output .\out
```

Or with a YAML/JSON config file:

```cmd
python -m MicroserviceBase.tools.scaffold_cli --config demo.yaml
```

`mb-scaffold` is a friendly nickname for
`python -m MicroserviceBase.tools.scaffold_cli` — there is no installed
binary, but you can wrap the long form in a `mb-scaffold.bat` on your
`PATH` if you use it often. Requires the bridge to be running
(`http://127.0.0.1:1112` by default; set with `--bridge-url` or
`MB_BRIDGE_URL`).

### Config file structure (`demo.yaml`)

The CLI accepts YAML or JSON. Only `service_name` and `output_path` are
required (and you can pass them via `--name` / `--output` instead).

**Minimal example**:

```yaml
service_name: HelloService
output_path: ./out
language: cpp
```

**Full example** — single service, C++ Qt widget client built with the
vcpkg + Qt MinGW toolchain:

```yaml
service_name: HelloService
version: "1.0.0"
description: "Demo service"
short_desc: "Hello"
group: "demo"
tag: "v1"

language: cpp                  # python | cpp
gui_type: widget               # none | html | qml | wasm | widget
client_grpc_kind: google_vcpkg # google | qt | google_vcpkg
server_grpc_kind: vcpkg        # msys2 | vcpkg
output_path: ./out

# Generation toggles (defaults shown)
gen_nomad:         true
gen_build_scripts: true
gen_readme:        true
gen_stubs:         true

# Toolchain hints (only when scripts can't auto-detect)
vcpkg_root: ""                 # default: $VCPKG_ROOT
protoc_path: ""                # default: $PATH lookup
grpc_plugin_path: ""

# Nomad job template
nomad_dc:          "dc1"
nomad_driver:      "raw_exec"
nomad_command:     ""           # auto-derived from service_name if empty
nomad_cpu:         100          # MHz
nomad_mem:         128          # MB
nomad_consul_addr: "http://127.0.0.1:8500"

# RPC methods
methods:
  - name: SayHello
    description: "Greet a caller by name"
    return_type: string
    server_streaming: false
    params:
      - name: name
        type: string            # string|int32|int64|uint32|uint64|bool|float|double|bytes|...
        required: true
        description: "Caller name"

# Verbatim .proto override (skip auto-synth from methods)
proto_content_override: ""
proto_package: ""               # only set when proto_content_override is set
```

> **CLI gap.** As of 2026-05-08 the CLI only supports `--monorepo` for
> multi-service imports — it does **not** yet support the GUI's
> `multi_proto` (one binary, N services) or `separate` (N independent
> projects) layouts. Use the GUI for those flows, or the bridge HTTP
> API directly if you need to script them. Tracked as a TODO on
> `MicroserviceBase/tools/scaffold_cli.py`.

**Monorepo example** — one project, N executables (one per service):

```yaml
service_name: PowerDeviceService
output_path: ./out
language: cpp
gui_type: widget
client_grpc_kind: google_vcpkg
server_grpc_kind: vcpkg
monorepo: true                  # ← key flag
proto_package: power.v1

services:                       # ← list of services instead of `methods`
  - name: AnalogInputService
    methods:
      - name: ReadChannel
        params: [{name: channel, type: int32}]
        return_type: double
      - name: ReadAllChannels
        return_type: string
        server_streaming: true

  - name: RelayService
    methods:
      - name: SetRelay
        params: [{name: id, type: int32}, {name: state, type: bool}]
        return_type: bool
```

### Field reference

| Field | Type | Default | Notes |
|---|---|---|---|
| `service_name` | str | **required** | Top-level service name (or monorepo project name) |
| `version` | str | `"1.0.0"` | |
| `description` / `short_desc` / `group` / `tag` | str | `""` | Metadata only |
| `language` | str | `"python"` | `python` \| `cpp` |
| `gui_type` | str | `"none"` | `none` \| `html` \| `qml` \| `wasm` \| `widget` |
| `client_grpc_kind` | str | `"google"` | `google` \| `qt` \| `google_vcpkg` (only when `gui_type != "none"`) |
| `server_grpc_kind` | str | `"msys2"` | `msys2` \| `vcpkg` — independent of client |
| `gen_nomad` / `gen_build_scripts` / `gen_readme` / `gen_stubs` | bool | `true` | |
| `vcpkg_root` / `protoc_path` / `grpc_plugin_path` | str | `""` | Override autodetect |
| `nomad_dc` | str | `"dc1"` | |
| `nomad_driver` | str | `"raw_exec"` | |
| `nomad_command` | str | `""` (auto) | |
| `nomad_cpu` / `nomad_mem` | int | `100` / `128` | MHz / MB |
| `nomad_consul_addr` | str | `"http://127.0.0.1:8500"` | |
| `methods` | list[Method] | `[]` | Single-service mode |
| `services` | list[Service] | `[]` | Monorepo mode (`monorepo: true`) |
| `output_path` | str | **required** | Service folder is created inside this |
| `monorepo` | bool | `false` | |
| `proto_content_override` | str | `""` | Verbatim `.proto` text |
| `proto_package` | str | `""` | When overriding proto |

**Method object**:

```yaml
- name: MyRpc                # required
  params: []                 # list of Param objects
  return_type: string        # primitive — used to synth *Response message
  description: ""
  server_streaming: false    # → stream<...> on the return side
  input_type:  ""            # fully-qualified proto type (imported protos only)
  output_type: ""            # fully-qualified proto type (imported protos only)
```

**Param object**:

```yaml
- name: foo                  # required
  type: string               # string|int32|int64|uint32|uint64|bool|float|double|bytes|...
  required: true
  description: ""
```

**Service object** (only used in monorepo `services:` list):

```yaml
- name: MyService
  methods: [<Method>, ...]
```

### Inline-flag overrides

Flags compose with the config — flag values win. Useful flags:

| Flag | Maps to |
|---|---|
| `-c FILE` / `--config FILE` | Load YAML/JSON config |
| `-n NAME` / `--name NAME` | `service_name` |
| `-l LANG` / `--language LANG` | `language` |
| `--gui {none,html,qml,wasm,widget}` | `gui_type` |
| `--client-grpc {google,qt,google_vcpkg}` | `client_grpc_kind` |
| `--server-grpc {msys2,vcpkg}` | `server_grpc_kind` |
| `-o DIR` / `--output DIR` | `output_path` |
| `--version VER` | `version` |
| `--description TEXT` | `description` |
| `--proto FILE` | Import `.proto` (overrides `methods`/`services`) |
| `--proto-service NAME` | Pick one service from a multi-service `.proto` |
| `--monorepo` | `monorepo: true` |
| `--no-nomad` / `--no-build-scripts` / `--no-stubs` | Disable generation toggles |
| `--bridge-url URL` | Override bridge endpoint (default `$MB_BRIDGE_URL` or `http://127.0.0.1:1112`) |
| `--dry-run` | Print the resolved JSON payload and exit |
| `-q` / `--quiet` | Print only the target path on success |

### Verify the config before sending

`--dry-run` prints the resolved JSON the CLI would POST to the bridge —
the easiest way to check that your YAML maps to the expected fields:

```cmd
python -m MicroserviceBase.tools.scaffold_cli -c demo.yaml --dry-run
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Service Creator button does nothing | Bridge not running. Check `http://127.0.0.1:1112/health` returns 200. Restart the Manager GUI. |
| "Failed to reach bridge" toast | Same as above, plus check no other process holds port 1112 (`netstat -ano \| findstr :1112`). |
| Import .proto returns "parse error" | The proto is malformed or uses syntax the bundled `protoc` doesn't support. Test with: `protoc --descriptor_set_out=NUL your.proto` |
| Import .proto succeeds but "service picker" is empty | Your .proto has no `service X { ... }` block — only messages. Add at least one service. |
| Generated build fails with "fabricated `<Method>Request` not declared" | Old generator bug. Make sure you're on the latest commit and regenerate. |
| Save succeeds but folder is empty | Bridge couldn't write to `output_path` — check write permissions. Defaults to wherever the bridge process runs. |
| C++ + Qt6::Grpc + monorepo emits two folders (`client/` and `qt_client/`) | This is intentional. `client/` has the Google-grpc console client (works without Qt installer); `qt_client/` is the Qt-native UI client. Use whichever fits. |
| Multi-service picker only shows two layout options | You're on a stale build. Pull and rebuild — the picker has had **three** layouts (`multi_proto`, `monorepo`, `separate`) since 2026-05. |
| Multi-file `.proto` import skipped the picker modal | Expected. Selecting N files forces `multi_proto` automatically (no per-file selection step). To use a different layout, import the protos one at a time, or change the layout via the inline selector on Step 3 after import. |
| **Download ZIP** produces a tiny / bare scaffold | The ZIP path is client-side-only and emits a minimal Python scaffold for sharing without the bridge. Use **Save to Path** for full C++ scaffolds, multi-service imports, and any `multi_proto` / `monorepo` / `separate` layout. |

---

## Screenshot status (2026-05-08)

The doc was diffed against `web/js/ServiceCreator.js` on 2026-05-08
and all flagged screenshots were captured the same day.

| Screenshot | Status | What it shows |
|---|---|---|
| `gui_wizard_01.png` | unchanged | Manager main window — empty state. |
| `gui_wizard_02.png` | unchanged | Service Creator tab highlighted in top nav. |
| `gui_wizard_03.png` | unchanged | Step 1 — Basic Info filled in. |
| `gui_wizard_04a.png` | ✅ updated 2026-05-08 | Step 2 — C++ + Widget + Google grpc++; the new two-column layout with the Server Toolchain block visible. |
| `gui_wizard_04b.png` | ✅ updated 2026-05-08 | Step 2 — C++ + Widget + Qt6::Grpc; the version-requirement alert is captured with the refreshed wording. |
| `gui_wizard_04c_schema.png` | ✨ new 2026-05-08 | Step 4 — Schema Builder tab with seeded sections, components, and the live preview. |
| `gui_wizard_04d_custom.png` | ✨ new 2026-05-08 | Step 4 — Custom HTML/JS tab with editor + preview side-by-side. |
| `gui_wizard_05.png` | unchanged | Step 3 — manual gRPC method entry. |
| `gui_wizard_06.png` | unchanged | OS file picker (now multi-select capable). |
| `gui_wizard_07.png` | ✅ updated 2026-05-08 | Multi-service picker modal with all three layout radios (`multi_proto` / `monorepo` / `separate`). |
| `gui_wizard_08.png` | ✅ updated 2026-05-08 | Step 5 review with the new layout badge + Server toolchain summary row. |
| `gui_wizard_09.png` | unchanged | Success toast. |

Both the Markdown and the HTML mirror at
[`../html/service_creator.html`](../html/service_creator.html) were
edited in the same pass, including image references for the two new
Step 4 captures.

