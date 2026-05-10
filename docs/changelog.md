# Changelog

> 📄 *Also available as HTML:* [`changelog.html`](changelog.html)

Significant changes since the framework's RabbitMQ-era origins.
Architectural records (one file per decision) live in [`adr/`](adr/);
this is the chronological summary.

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
  [`00_canonical_architecture.puml`](diagrams/00_canonical_architecture.puml)
  and [`component.puml`](diagrams/component.puml); 14 legacy diagrams
  archived under [`diagrams/_archive/`](diagrams/_archive/); class /
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
- New doc: [`runtime_cpp_install.md`](runtime_cpp_install.md).

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
[`packagedoc/additional_docs/History.tex`](../packagedoc/additional_docs/History.tex)
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

A full ADR refresh is queued; in the meantime, [`concepts.md`](concepts.md)
has a side-by-side "old term → new term" mapping table.

## See also

- [`architecture.md`](architecture.md) — current shape
- [`concepts.md`](concepts.md) — current terminology
- [`adr/`](adr/) — per-decision rationale
- [`_legacy/CONCEPT.md`](_legacy/CONCEPT.md) — pre-migration architecture in detail
