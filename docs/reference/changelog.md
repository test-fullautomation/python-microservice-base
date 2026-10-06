# Changelog


Significant changes since the framework's RabbitMQ-era origins.
Architectural records (one file per decision) live in [`adr/`](../adr);
this is the chronological summary.

## Unreleased — Manager GUI: flows, views, live signals

- **View roles.** The GUI opens in a view made of roles — *user* (Services,
  Bench), *admin* (Nomad, plugins), *developer* (test projects, tools) —
  from `settings.json`, *Settings → View* or `?view=` in the address.
- **Flow Diagram editing.** *Edit flow* inserts, moves, changes, deletes and
  wraps steps by drag and drop; each change is validated by the runner and
  written back to the flow file.
- **Sub-flows in the Diagram.** A `flow` step is drawn as one box that opens
  in place; the live position follows a run into it.
- **New flow.** A **+** on the project view's *Flows* group creates a flow
  file from the runner's template and opens its Diagram.
- **Signal Graph Studio.** *Run cluster* uses the Live panel's discovery
  port and serves gRPC reflection from the clusters it starts.
- **Docs.** Diagrams of the host bus and the bridge for live signals.
- **C++ services serve their GUI.** The C++ runtime registers `Meta.gui`
  from `<PREFIX>GUI` and serves the folder over `ServiceGui` (ADR-031),
  with the same checksum as the Python runtime; `<PREFIX>GUI_DIR` or the
  folders beside the executable, `../interfaces/gui/<gui>` included.
- **A Qt service's own window.** The classic Qt WebAssembly panel of a
  Consul gRPC service now reaches the service over gRPC
  (`Module.endoToken`, methods found by reflection). **User → Service
  view → Tiles | Service window** switches a service between its component
  and that window; it moved from the Developer tab, and the button now
  enables itself once a downloaded folder ships both.
- **Dropdowns in forms.** A form field can be a dropdown: fixed `options`,
  or `optionsFrom` the service (a list RPC, or a count RPC with a name per
  index), `current` preselected; `reloadAfter` reads it again after a
  call it depends on, from any tile of the component.
- **Tile groups.** `groups` puts tiles under headers that expand and
  collapse; a collapsed group's tiles are suspended, and the choice is
  remembered.
- **Components from protos.** `python -m MicroserviceBase.tools.ui_component`
  writes a `component.json` from a service's protos: forms, dropdowns
  (indexes 0 to count−1), `reloadAfter` links and groups.
- **Pluggable test runners; Temporal.** A test project's runner now owns
  its file types, the *Initialize* dialog's structure, folder detection,
  *Check*, new tests and flows and the run command; the GUI shows them in
  the runner's words. Other packages add runners as entry points
  (`microservicebase.test_runners`). New runner **Temporal (Python SDK)**:
  pytest tests running workflows, generated activities per service, JUnit
  results (ADR-032, guide *Adding a test runner*). `describe()`'s
  `detected` is now per runner.
- **Themeable Grid and Diagram.** The neutrals and tints of the shared
  `robot-grid` and `flow-view` styles are CSS variables (`--rg-*`,
  `--fv-*`) with the current light colours as fallback: the GUI looks the
  same, and a host such as an editor extension can give them a dark palette.
- **Where a keyword is defined.** `robot_grid.py --define` answers where a
  keyword called in a suite, resource or flow file is defined (file and
  line), resolved like the Grid and the run; Libdoc's `source` and
  `lineno` are kept in the keyword catalog. Editors use it for Go to
  Definition.
- **Pause, resume, stop and continue flow runs.** With the fork's flow
  control: *Pause* / *Resume* a running flow (or one member of a run
  group), where it holds shown in Runs and on the Diagram; *Stop* writes a
  checkpoint; *Continue from checkpoint* starts a run that goes on where it
  stopped; step mode from the Run dialog. Runner port: `can_pause`,
  `control`, `control_state`, `member_env`, `restart_variables`,
  `RunOptions.step`. The live position also follows the fork's checkpointed
  loops, and step mode works with it.
- **Debugging and Go to Definition in the project view.** *Debug* runs a
  suite or flow with breakpoints (the editor's line numbers, the Diagram's
  step dots, sub-flows included), stops on a failed keyword, steps over,
  into (keywords, sub-flows, the Python function of a keyword of the user's
  library) and out, shows the call stack, variables and a console, and marks
  the stopped line and step in the editor and the Diagram. F12 / Ctrl+Click
  goes to where Robot finds a keyword. The editor colours keyword calls,
  control words, imports and named arguments too. The listener
  (`flow_debug.py`) is shared with the VS Code extension; the runner port
  gains `can_debug` and `define`.
- **Breakpoints on the Diagram.** The `flow-view` plugin draws a breakpoint
  dot on each step and marks the step a debugger paused at, when the host
  sends `breakpoints` / `paused` and gives `ctx.breakpoint(id)` (the project
  view's debugger and the VS Code extension do; without them it looks as
  before).
- **Starting the bridge on Linux.** With no Python set in *Settings*, the
  Electron app ran `python`, which Ubuntu does not have, and reported only
  "Bridge spawn returned no PID" with an older part of `launcher.log`. It
  now runs `python3` there (`python` on Windows, or whichever of the two
  is on PATH), waits until the process has started or failed, and says why
  it failed (`spawn python ENOENT`), with the error written to the log first.
- **FastAPI and uvicorn are base dependencies.** They were only the `web`
  extra, so `pip install MicroserviceBase` gave a GUI whose bridge could
  not start. The `web` extra stays, for installs that name it.

## Release 2.2.0 — 2026-05-27 — Robot generator + bridge fixes

Manager GUI + bridge additions on top of 2.1.0. Targets the
last-mile gap between QConnectBase's generic `GrpcClient` connection
type and the per-method readability test authors expect.

**Highlights:**

- **Robot Framework resource generator.** Turns a folder of `.proto`
  files into one `.resource` per service with typed keywords (one per
  RPC), wrapping QConnectBase's `GrpcClient`. Reachable three ways:
  green button in the Manager GUI's methods panel, CLI at
  `python -m MicroserviceBase.tools.robot_gen`, or
  `POST /api/scaffold/robot`. Output conventions: service-prefixed
  keyword names (so two services with same-named methods coexist),
  `${conn_name}` as the first positional arg, Open/Close Connection
  helpers (not Connect/Disconnect — they'd collide with same-named
  RPCs), single-space-only headers (Robot's parser treats 2+ spaces as
  delimiter). Long-form doc:
  [`../MicroserviceBase/MicroserviceManagerGUI/docs/md/robot_generator.md`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/MicroserviceBase/MicroserviceManagerGUI/docs/md/robot_generator.md).
- **Proto3 default-value fix in the bridge.** `MessageToDict` now
  opts into `always_print_fields_with_no_presence=True` (older
  protobuf: `including_default_value_fields=True`). A unary RPC
  returning `{"errorcode": 0}` no longer surfaces as `{}` — tests
  asserting `${res}[errorcode]` resolve to `0` as expected without
  any change.
- **Stricter `.proto`-folder search.** `LocalProtoClient.from_search_paths`
  now prunes `build/`, `build-*`, `vcpkg_installed/`, `node_modules/`,
  `_legacy/`, `.git/`, `__pycache__/` from the recursive glob so
  vendored copies of `google/protobuf/*.proto` no longer feed into
  protoc and produce duplicate-definition failures. When a user types
  an explicit proto folder in the GUI, that folder is used
  **exclusively** (env-var + default fallbacks skipped).
- **QConnectBase compatibility shim.** Added
  `MicroserviceBase.adapters.grpc_bridge.local_proto_client` re-export
  module + accepted a `proto_dir` kwarg on `LocalProtoClient.__init__`,
  so QConnectBase 1.1.4's expected import path and constructor shape
  both work without modifying QConnectBase itself.
- **Helper modal forwards `proto_path`.** The "Code Example" button now
  inherits the same proto folder the main methods panel uses; without
  this, the Helper always failed on no-reflection servers.
- **Native dialogs in Electron.** The Robot generator button uses
  Electron's `dialog.showOpenDialog` / `showMessageBox` for folder
  pickers and confirms — `window.prompt()` / `window.confirm()` are
  disabled in Electron renderers and were silently no-oping.
- **MSB_0019 / MSB_0020 / MSB_0021 regression tests.** Multi-proto +
  Qt6::Grpc client emission, `LocalProtoClient._is_excluded` pruning,
  and Robot resource generator output shape (all three carry
  representative cases that previously broke real generations).

ADR-029 v1.2 records the generator addition and softens the
"JSON-string response surface" negative consequence by pointing at
the mitigation.

## Release 2.1.0 — 2026-05-11

First minor release after the gRPC + Consul + Nomad migration shipped
in 2.0.0.  Focus areas: Manager GUI parity with the new architecture,
Service Creator wizard upgrades, installer modernisation, and a
fully-documented Robot Framework test path.

**Highlights:**

- **`grpcio-tools` promoted to base dependency** (was the
  `[proto-tools]` optional extra).  The Service Creator wizard's
  *Pre-generate proto stubs* feature now works out of the box on
  every fresh install.  ~30 MB heavier; one fewer footgun.
- **ADRs 023–029 added.**  Multi-node Consul, multi-node Nomad,
  wrapper layer for raw_exec, uv-based Python envs, Kafka event bus
  alongside gRPC, gRPC + reflection as the canonical RPC layer, and
  Robot Framework via QConnectBase as the primary test client.  Older
  ADRs (003, 010–018, 020) carry visible *Superseded* / *Archived*
  callouts pointing at the new ones.
- **Service Creator wizard:** multi-proto layout (one process,
  N services on one port, one Consul registration), multi-file
  `.proto` import, new *GUI Support* step with a Schema Builder + a
  Custom HTML/JS editor, language-aware copy throughout (no more
  `.exe` references for Python services).
- **Generated Python + C++ services** now ship with full
  QConnect-style file headers (author, date, history) and per-method
  docstrings / Doxygen blocks.  Author is taken from the OS user's
  full display name; date is the generation date.
- **Manager GUI Settings dialog** got a new *Service infrastructure*
  section with Consul / Nomad executable paths and OS file-picker
  Browse buttons (Electron only); installer writes them automatically
  if it found or installed those tools.
- **Windows installer (NSIS):** new *Infrastructure* wizard page
  detects Consul / Nomad on PATH, in `%ProgramFiles%\HashiCorp\`, in
  the WinGet Links shim folder, and in `WinGet\Packages\Hashicorp.*`;
  offers `winget install` (pinned), Browse-existing-path, or Skip.
  Erlang / RabbitMQ / ProcessHub install steps moved behind
  `ENABLE_LEGACY_BROKER` / `ENABLE_LEGACY_PROCESSHUB` flags (default
  off; flip to re-enable).
- **Linux installer:** new `bootstrap.sh` (interactive) shipped in
  `extraResources` for AppImage users, plus a `.deb` postinst hook
  that launches it when stdin is a TTY.  Detects via `command -v`,
  installs from HashiCorp's official apt / yum repos with version
  pinning, falls back to release-tarball download.
- **QConnectBase `GrpcClient` connection type** contributed upstream
  (`QConnectBase/grpc/grpc_client.py`).  Robot Framework tests now
  drive gRPC services with the same `Connect` / `Send Command` /
  `Verify` / `Disconnect` keywords as TCP / Serial / SSH / RabbitMQ.
  Direct (host:port) and Consul-resolved (service_name + consul_addr)
  modes; reflection client with automatic LocalProtoClient fallback.
- **Documentation refresh:** new canonical
  [`00_canonical_architecture.puml`](../diagrams/00_canonical_architecture.puml)
  and [`component.puml`](../diagrams/component.puml); 14 legacy diagrams
  archived under [`diagrams/_archive/`](../diagrams/_archive); class /
  sequence diagrams refreshed; Service Creator wizard documentation
  rewritten with new screenshots; framework + scaffold + Tier-A
  source files brought in line with QConnect docstring style.

The granular per-area entries below were the work that fed into this
release.

### Migration to gRPC + Consul + Nomad (the "big one")

The framework was originally built around RabbitMQ for service-to-service
communication, an in-process **ServiceRegistry** for discovery, and a
**Local Process Hub** (custom Python supervisor) for lifecycle
management.  All three were replaced:

| Old | New |
|---|---|
| RabbitMQ + custom request/response framing | gRPC over HTTP/2 + protobuf |
| ServiceRegistry (in-process, broker-coupled) | Consul service catalog (`/v1/health/service/...`) |
| Routing keys + alias routing | Fully-qualified gRPC service + method names |
| Local Process Hub (Python subprocess management) | Nomad `raw_exec` jobs + agent supervisor |
| `hub_processes.json` config | per-service `deploy/<svc>.nomad.hcl` |
| Fleet Web API + hub fleet view | Consul + Nomad UIs (`:8500/ui` and `:4646/ui`) + the GUI's Service Network tab |
| `eventbus` transport adapter | (dropped — no broker means no transport adapter) |

The rationale per piece is in the ADRs (especially ADRs 016 and 018,
both flagged "superseded" — see ADR audit list at the bottom).

The hexagonal architecture itself didn't change — the migration
swapped adapters, not domain code. Services that had domain logic
written for the RabbitMQ-era framework needed minor adjustments
(method signatures became `(request_msg, response_msg)` instead of
`svc_api_X(arg1, arg2)`), but the business logic was portable.

### Multi-broker → multi-Consul
- The "connect to multiple brokers" feature became "connect to
  multiple Consul clusters."
- `MM.connections` map keyed by `host:port`.
- Sidebar groups services by which Consul cluster they came from.
- Session persistence in `sessionStorage.mm_connections`.

### C++ runtime now installable as a standalone CMake / vcpkg package
- `runtime_cpp/CMakeLists.txt` now exports `MicroserviceBaseConfig.cmake`
  + `MicroserviceBaseTargets.cmake` via `install(TARGETS … EXPORT)` +
  `CMakePackageConfigHelpers`.  After `cmake --install`, generated
  services can `find_package(MicroserviceBase CONFIG REQUIRED)` and
  link against `microservice_base::runtime` from anywhere on the disk.
- New vcpkg overlay-port at `ports/microservice-base/` so vcpkg-using
  consumers add `"microservice-base"` to their `vcpkg.json` and the
  same find_package call resolves through the vcpkg toolchain.
- Generator (`cpp_tmpl.py`) now emits a hybrid CMake block: tries
  `find_package(MicroserviceBase CONFIG QUIET)` first, falls back to
  `add_subdirectory(.../runtime_cpp)` when the relative path resolves
  (i.e. the service lives inside `<framework>/examples/`).  Means
  generated services are truly standalone — no longer assume the
  framework repo is at `../../MicroserviceBase/` on disk.
- Three target names exported for back-compat: `microservice_base::runtime`
  (modern alias), `microservice_base::microservice_base_runtime` (default
  vcpkg-style), `microservice_base_runtime` (legacy bare name).
- New doc: [`runtime_cpp_install.md`](../guides/runtime-cpp-install.md).

### Python monorepo support added to scaffold generator
- `python_tmpl.generate_monorepo()` mirrors the C++ monorepo emitter:
  one project, N service modules sharing a single `.proto`, one
  `pyproject.toml` registering each service as a `[project.scripts]`
  entry point.
- Service Creator wizard's monorepo radio drops the "(C++ only, v1)"
  label — now valid for both languages.

### Manager GUI in-app help modernised
- `web/docs/help.html` got a "this in-app help is being modernised"
  banner pointing readers to the long-form docs in
  `MicroserviceManagerGUI/docs/`.  Full RabbitMQ → gRPC content
  rewrite is queued.

### Documentation restructure
- `docs/` now contains framework-level reference (architecture,
  runtime model, concepts, troubleshooting, changelog).
- Manager GUI docs live next to the GUI at
  `MicroserviceBase/MicroserviceManagerGUI/docs/`.
- Per-example tutorials live at `examples/docs/`.
- Legacy examples (RabbitMQ-era `01_…08_*.py`, `cpp_*_template/`,
  `fleet_demo/`, etc.) moved to `examples/_legacy/`.
- Legacy framework docs (`CONCEPT.md`, `troubleshooting-guide.md`)
  moved to `docs/_legacy/`.

### Manager GUI: proto-path fallback for servers without reflection
- Bridge endpoints accept an optional `proto_path` so the GUI can
  point `LocalProtoClient` at a folder of `.proto` files when the
  server doesn't ship `grpc++_reflection`.
- New input field appears in the service detail panel when reflection
  + the env-var search paths both fail; persisted per-service in
  `sessionStorage`.

### vcpkg overlay-port forces `gRPC_BUILD_CODEGEN=ON`
- Root cause: vcpkg's manifest-mode feature selection was dropping
  the `codegen` feature for the target triplet, which gates
  upstream's `add_library(grpc++_reflection ...)` block.  Result:
  generated services returned `UNIMPLEMENTED` to every Manager-GUI
  reflection RPC.
- Fix: `init_vcpkg_overlay.bat` now patches upstream's `portfile.cmake`
  to drop the `codegen` row from `vcpkg_check_features` and force
  `set(gRPC_BUILD_CODEGEN ON)` + `-DgRPC_BUILD_CODEGEN=ON` in
  `vcpkg_cmake_configure`.
- Idempotent flags added: `--upgrade` (re-apply patches in place),
  `--reinit` (wipe + re-copy + re-patch from upstream).
- Also fixed: blank context lines in `00018-gcc13-per-cpu-ice-workaround.patch`
  were zero-byte and rejected by `git apply`.  Now use a `{SP}`
  placeholder substituted at emit-time so editors don't strip them.

### `LocalProtoClient` added to `reflect_client.py`
- Same public API as `GrpcReflectClient` (`list_services`,
  `list_methods`, `call_method`) but builds the descriptor pool from
  local `.proto` files via `grpc_tools.protoc` instead of reflection.
- Used by the bridge as a fallback when reflection returns
  `UNIMPLEMENTED`.

## Release 2.0.0 — 2026-02-09

Hexagonal-architecture refactor on top of the original RabbitMQ
broker.  Still broker-era — the gRPC + Consul + Nomad migration came
later in 2.1.0.  See
[`packagedoc/additional_docs/History.tex`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/packagedoc/additional_docs/History.tex)
for the full sub-section list (Architecture / GUI v2.0 / Multi-Broker
Support / Local Process Hub / Service Management / Electron Packaging
/ Windows Process Fixes / Documentation).

### Manager GUI rewrite (v2.0)
- Pure browser-compatible HTML/CSS/JS (no Node.js deps in `web/`).
- Dual hosting: Electron wrapper + Python web mode (FastAPI bridge).
- Bootstrap 5 from CDN, no `node_modules/` for the web UI.
- `window.MicroserviceManager` namespace (alias `MM`) for everything.
- Per-service GUI plugins loaded dynamically from `web/services/`.
- Login replaced with Bootstrap modal (no separate Electron popup
  window).

### Windows process shutdown reliability
- `proc.terminate()` on Windows calls `TerminateProcess` — no cleanup,
  no finally blocks.  Switched to `CTRL_BREAK_EVENT` for graceful
  shutdown.
- `signal.signal(signal.SIGBREAK, signal.default_int_handler)` so
  SIGBREAK becomes `KeyboardInterrupt` and Python `finally` runs.
- Replaced `pika.start_consuming()` (blocks forever, ignores Python
  interrupts) with `process_data_events(time_limit=1)` loop.

### `subprocess.PIPE` blocking fix
- ProcessHub's executor used `stdout=subprocess.PIPE` but never read
  the pipe → on Windows, ~4KB buffer fills, child process blocks on
  next `print()`, hangs the whole logging system.
- Fix: only attach a `StreamHandler` to the root logger when
  `sys.stdout.isatty()`.  Always use `FileHandler` for subprocess
  logging.

### ProcessHub config persistence
- `hub_processes.json` uses `${python}` and `${config_dir}`
  placeholders, resolved at runtime.
- `_raw_config` dict preserves originals for round-tripping so the
  saved file doesn't have absolute paths baked in.

(ProcessHub itself is now legacy — see migration above. These fixes
were made before the Nomad transition; documenting here for git
archaeology.)

## ADR audit list

These ADRs predate the gRPC migration and either need an "Superseded
by ADR-NNN" header or a wholesale rewrite. Until that audit happens,
read them with the migration in mind.

| ADR | Status hint |
|---|---|
| 003 — Service registry over Zookeeper | Superseded — Consul replaces both |
| 010 — Local Hub Manager | Superseded — Nomad replaces |
| 011 — Service Import with module execution | Likely deprecated (Nomad jobs replace runtime "import") |
| 012 — Registry shutdown notification | Superseded — Consul deregistration handles this |
| 015 — Fleet Orchestrator architecture | Superseded — Nomad replaces |
| 016 — RabbitMQ as message broker | **Superseded** — gRPC replaces broker entirely |
| 017 — `svc_api_*` naming convention | Superseded — gRPC method names are explicit |
| 018 — Alias routing design | Superseded — no broker, no aliasing layer |

A full ADR refresh is queued; in the meantime, [`concepts.md`](../architecture/concepts.md)
has a side-by-side "old term → new term" mapping table.

## See also

- [`architecture.md`](../architecture/overview.md) — current shape
- [`concepts.md`](../architecture/concepts.md) — current terminology
- [`adr/`](../adr) — per-decision rationale
- [`_legacy/CONCEPT.md`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/docs/_legacy/CONCEPT.md) — pre-migration architecture in detail
