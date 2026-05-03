# MicroserviceBase Documentation

Build microservices in C++ or Python — pick a toolchain, follow the path.

> 📄 *Also available as HTML:* [`../html/index.html`](../html/index.html)
>
> Each guide ships in two formats — `html/` for nicely-styled in-browser
> reading, `md/` for terminal / IDE preview / `git grep`. Content is
> kept in sync.

## What is MicroserviceBase?

A scaffolding framework for building gRPC-based microservices. It
generates production-ready service projects with a hexagonal
architecture (domain · ports · adapters), Consul service discovery,
Nomad deploy specs, build scripts for multiple toolchains, and matching
client projects with optional Qt GUIs.

This `docs/` folder is split into two layers:

- **Toolchain setup** — install the right compilers / Qt /
  dependencies for the variant you want.
- **Service creation** — the per-feature tutorial (define proto,
  implement domain, wire adapter, build, deploy).

Most users start by picking a toolchain below, then move to the service
creation guide.

## Pick your path

Start here if you're new. The right entry point depends on what you're
building:

| Situation | Go to |
|---|---|
| 📦 Building a service (server) in C++ on Windows | [MinGW setup with MSYS2](mingw_setup.md) — the standard server toolchain (Google grpc++, Google libprotobuf). |
| 🖼 Want a Qt-native GUI client (signals/slots, QML) | [Qt6::Grpc client setup](qt_grpc_setup.md) — uses the Qt-installer toolchain, separate from the server's MSYS2 build. Server stays on Google grpc++ (Qt has no server module). |
| 🔧 Want one toolchain for client AND server (Qt MinGW everywhere) | [vcpkg + Qt MinGW setup](vcpkg_setup.md) — Google grpc++ for both sides, built by vcpkg with the Qt-installer MinGW. ~30–60 min first build, instant after. **Recommended for new teams** — one ABI end-to-end, no MSYS2 / Qt MinGW mismatches. |
| ⏱ Want vcpkg + Qt MinGW but don't want the 30–60 min compile | Download prebuilt artifacts from [SharePoint](https://bosch-my.sharepoint.com/:f:/p/ugc1hc/IgAuLLzLlXVnS6lFL3KREFfNAbw2m_51U7sqOkO8f-mnDrY?e=b43r9x) and run `import_prebuilt.bat <path>.zip` at your project root. See the *Use prebuilt libraries* section in any vcpkg project's `README.html`. |
| 🌐 Adding a browser-rendered UI (WASM) | [WASM Cleware service guide](wasm_cleware_service_guide.md) — full walkthrough of building a service with a Qt-WebAssembly UI. |
| 🛠 Already have the toolchain — want to write the service code | [Service creation guide](service_creation.md) — the long tutorial: proto, domain, adapter, settings, main, build, run, debug. |
| 🪄 Want the boilerplate generated for you | [Service Creator wizard guide](gui_wizard.md) — drive the Manager GUI's 4-step wizard, or use the `mb-scaffold` CLI. |
| 🎛 Don't want to run `consul agent -dev` / `nomad agent -dev` in two terminals | [Manager GUI ops guide](manager_gui_ops.md) — the GUI starts/stops both agents, shows live LEDs, lists registered services, and submits Nomad jobs from a file picker. Replaces the per-terminal CLI workflow. |
| ⚡ Just want to scaffold something fast | Run `python -m MicroserviceBase.tools.scaffold_cli --help` from the project root. |

## All docs

### Toolchain

- **[MinGW Setup (MSYS2)](mingw_setup.md)** — Google grpc++ ·
  libprotobuf · Qt Creator kit. Install MSYS2, install
  `mingw-w64-x86_64-grpc` and friends, point the build scripts at it.
  The standard server toolchain on Windows. Includes a step-by-step
  Qt Creator kit registration. *For: services, Google-grpc clients,
  console clients.*

- **[Qt6::Grpc Client Setup](qt_grpc_setup.md)** — Qt-installer MinGW ·
  Qt6::Protobuf · `qt_client/`. Install Qt 6.8+ with the GRPC and
  Protobuf modules, install Google's `protoc` separately, configure
  the `qt_client/` CMake project. Covers the
  `Protobuf_PROTOC_EXECUTABLE` trap that catches first-time Qt Creator
  users. *For: Qt-native clients (Widgets / QML).*

- **[vcpkg + Qt MinGW Setup](vcpkg_setup.md)** — Google grpc++ via
  vcpkg · custom triplet `x64-mingw-qt` · gcc 13.1.0 ICE workaround
  patch · `qt_client_grpcpp/`. The "single toolchain" path: client
  AND server both built with Qt-installer MinGW 13.1.0. First build
  is slow (vcpkg compiles boringssl + abseil + protobuf + grpc once,
  ~30–60 min); subsequent builds are instant via the binary cache.
  Covers `export_prebuilt.bat` / `import_prebuilt.bat` for sharing
  built artifacts with teammates — download the prebuilt zip from
  [SharePoint](https://bosch-my.sharepoint.com/:f:/p/ugc1hc/IgAuLLzLlXVnS6lFL3KREFfNAbw2m_51U7sqOkO8f-mnDrY?e=b43r9x)
  and skip the rebuild. Each generated project's `README.html`
  includes the full kit-flow walkthrough plus a *Common issues*
  section (Qt Creator `VCPKG_ROOT` quirks, F5 missing-DLL fix,
  `${sourceDir}` macro caveat, etc.). *For: teams who want one ABI
  end-to-end and don't need Qt6::Grpc's signal/slot ergonomics.*
  **Recommended for new teams.**

### Tutorials

- **[Manager GUI — Consul + Nomad ops](manager_gui_ops.md)** —
  Service Network tab · agent start/stop · live LEDs. The easiest
  on-ramp to the runtime: launch the Manager GUI (Electron or browser),
  open *Service Network*, and start Consul + Nomad with one click each.
  Connected dashboards show registered services, running jobs, per-job
  logs, and a submit-from-file picker for the generated `.nomad.hcl`
  files. Navbar pills show live infra health. Same actions are
  available via `POST /api/{consul,nomad}/agent/start` for scripting.
  *For: anyone who'd rather not babysit two terminal windows.*

- **[Service Creator wizard guide](gui_wizard.md)** — Manager GUI ·
  4-step wizard · screenshots. End-to-end walkthrough of generating a
  service scaffold (proto + domain + adapter + clients + Nomad) from
  the Manager GUI without writing boilerplate. Same generator backend
  as the `mb-scaffold` CLI. *For: anyone starting a new service.*

- **[WASM Cleware Service Guide](wasm_cleware_service_guide.md)** — Qt
  for WebAssembly · Cleware USB switch box. End-to-end walkthrough:
  build a Cleware USB device service with a C++ backend and a
  Qt-WebAssembly UI rendered in the browser. Built on top of
  `examples/qt_wasm_service_template`. *For: services with
  browser-rendered Qt UIs.*

- **[Service Creation Guide](service_creation.md)** — Proto · Domain ·
  Adapter · Build · Run. The long-form tutorial: write the `.proto`,
  implement the hexagonal domain, wire the gRPC adapter, configure
  settings, build with MSVC / MinGW / MSYS2, run, debug, deploy with
  Nomad. Originally written against `cpp_hello_service`. *For: anyone
  building a C++ service from scratch.*

## Toolchain & gRPC stack matrix

Quick reference for which combinations work. Each binary uses *one*
toolchain; mixing libstdc++ versions inside one binary causes link
errors. Wire-protocol interop between binaries is always fine because
they only share gRPC over HTTP/2.

| Component | Toolchain | gRPC stack | Setup doc |
|---|---|---|---|
| Service (server) — MSYS2 path | MSYS2 MinGW | Google grpc++ + libprotobuf | [MinGW Setup](mingw_setup.md) |
| Service (server) — vcpkg path | Qt-installer MinGW + vcpkg | Google grpc++ + libprotobuf (vcpkg-built) | [vcpkg Setup](vcpkg_setup.md) |
| Console client (`client/`) | MSYS2 MinGW (same as server) | Google grpc++ | [MinGW Setup](mingw_setup.md) |
| JSON-Widget client (`client/gui/`) | MSYS2 MinGW (same as server) | Google grpc++ + Qt6 Widgets via MSYS2's qt6-base | [MinGW Setup](mingw_setup.md) |
| Qt-native client (`qt_client/`) | Qt-installer MinGW (separate) | Qt6::Grpc + Qt6::Protobuf | [Qt6::Grpc Setup](qt_grpc_setup.md) |
| Qt+grpc++ client (`qt_client_grpcpp/`) | Qt-installer MinGW + vcpkg | Google grpc++ (vcpkg) + Qt6 Widgets | [vcpkg Setup](vcpkg_setup.md) |
| WASM UI | Qt for WebAssembly + Emscripten | Qt6::Grpc (Qt-WASM) | [WASM Guide](wasm_cleware_service_guide.md) |

## Quick reference

### Common environment variables

| Variable | Used by | Typical value |
|---|---|---|
| `MSYS2_ROOT` | MSYS2 build scripts | `C:\msys64\mingw64` |
| `QT_DIR` | Qt-installer build scripts (`build_qt.bat`, `build_qt_vcpkg.bat`) | `C:\Qt\6.11.0\mingw_64` |
| `QT_TOOLS` | `build_qt.bat` (CMake / Ninja / MinGW autodetect) | `C:\Qt\Tools` |
| `QT_MINGW_BIN` | vcpkg path: pin compiler to Qt's MinGW | `C:\Qt\Tools\mingw1310_64\bin` |
| `PROTOC_DIR` | Qt6::Grpc CMakeLists auto-discovery | `C:\msys64\mingw64\bin` |
| `VCPKG_ROOT` | vcpkg-based fallback discovery + vcpkg path | `C:\vcpkg` |
| `VCPKG_BINARY_SOURCES` | Shared vcpkg cache (team setup) | `files,\\fileserver\share\vcpkg-cache,readwrite` |
| `CONSUL_ADDR` | Service runtime + clients | `http://127.0.0.1:8500` |

### One-liner sanity checks

| Check | Command |
|---|---|
| MSYS2 grpc/protobuf installed? | `dir C:\msys64\mingw64\bin\protoc.exe` |
| Qt6 GRPC component installed? | `dir C:\Qt\6.11.0\mingw_64\lib\cmake\Qt6Grpc` |
| Qt-bundled MinGW installed? | `dir C:\Qt\Tools\mingw1310_64\bin\g++.exe` |
| vcpkg bootstrapped? | `dir %VCPKG_ROOT%\vcpkg.exe` |
| vcpkg cache populated? | `dir %LOCALAPPDATA%\vcpkg\archives` |
| Consul running? | `curl http://127.0.0.1:8500/v1/status/leader` |
| Nomad running? | `curl http://127.0.0.1:4646/v1/status/leader` |

---

*Docs source: `examples/docs/`. Generator: `MicroserviceBase/adapters/scaffold/cpp_tmpl.py`.*
