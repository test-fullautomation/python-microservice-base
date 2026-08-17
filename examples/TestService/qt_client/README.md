# TestService — Qt-native client

Standalone Qt6 GUI client built with **Qt6::Grpc + Qt6::Protobuf**.
Lives in its own CMake project so it can be compiled with the
Qt-installer MinGW toolchain (e.g. `C:\Qt\6.11.0\mingw_64`) without
mixing libraries with the MSYS2-built server.

## Why a separate project?

Qt 6's GRPC/Protobuf modules only provide a **client-side** API — the
service must remain on Google's `grpc::Server` (built via MSYS2 in the
parent project).  Mixing libraries from the two MinGW toolchains in
one binary triggers libstdc++ ABI errors (`nanosleep64`, …), so we
keep them in separate projects, each with its own toolchain.  The two
binaries communicate over the gRPC wire protocol on the same port —
no ABI involved.

## Services available in the GUI

- **ComSetupDeviceService** -- 8 RPC method(s)
- **PowerSupplyService** -- 12 RPC method(s)

## Build (Windows)

### Prerequisites — install via Qt Maintenance Tool

Tick all of these under **Add or remove components**:

| Component                                | Why                                                      |
|------------------------------------------|----------------------------------------------------------|
| Qt 6.x.x → **MinGW 13.1.0 64-bit**       | The Qt 6 libraries built with MinGW                      |
| Qt 6.x.x → **Qt GRPC**                   | Client-side gRPC (stable in 6.8+, Tech Preview in 6.7)   |
| Qt 6.x.x → **Qt Protobuf**               | `QProtobufMessage` runtime                               |
| Qt 6.x.x → **Qt Protobuf WellKnownTypes**| `Empty`, `Timestamp`, etc.                               |
| Qt → Tools → **CMake**                   | CMake bundled with Qt                                    |
| Qt → Tools → **Ninja**                   | Build driver                                             |
| Qt → Tools → **MinGW 13.1.0 64-bit**     | The compiler                                             |

### …plus Google's `protoc` (separate from Qt!)

Qt's `qt_add_grpc` / `qt_add_protobuf` invoke **Google's `protoc.exe`** at
build time — Qt only ships the Qt-side code-generation plugins.  The Qt
installer does **not** bundle protoc, so install it separately.  Easiest
options on Windows:

- **MSYS2** (recommended): `pacman -S mingw-w64-x86_64-protobuf` →
  `protoc.exe` lands at `C:\msys64\mingw64\bin\protoc.exe`.
- **Standalone download** from <https://github.com/protocolbuffers/protobuf/releases>
  (pick a Windows zip, unzip anywhere).

### Build via `build_qt.bat`

```cmd
:: Adjust if your Qt is somewhere else:
set "QT_DIR=C:\Qt\6.11.0\mingw_64"

:: Optional — only needed if protoc isn't auto-discovered by CMakeLists:
set "PROTOC_DIR=C:\msys64\mingw64\bin"

build_qt.bat
```

Output: `build-qt\test_service_qt_gui.exe`.

### Build via Qt Creator

1. **Open** `qt_client/CMakeLists.txt` → tick the **MinGW 13.1.0 64-bit** kit.
2. *(Only if CMake errors with "protoc not found")* — **Projects → Build →
   CMake → Initial Configuration → Add**:

   | Key                            | Type     | Value                                    |
   |--------------------------------|----------|------------------------------------------|
   | `Protobuf_PROTOC_EXECUTABLE`   | FILEPATH | `C:/msys64/mingw64/bin/protoc.exe`       |

   Then click **Re-configure with Initial Parameters** (CMake caches values, so a regular *Run CMake* won't pick this up).
3. **Build → Build All** (Ctrl+B), **Run** (Ctrl+R).

The bundled `CMakeLists.txt` auto-discovers `protoc` in this order:

1. `-DProtobuf_PROTOC_EXECUTABLE=...` (cache / Qt Creator Initial Config)
2. `PROTOC_DIR` env var → `<PROTOC_DIR>/protoc.exe`
3. `C:/msys64/mingw64/bin/protoc.exe`
4. `<VCPKG_ROOT>/installed/x64-windows/tools/protobuf/protoc.exe`
5. `find_program(protoc)` on PATH

If none match, configuration aborts with a clear error message naming
the override variables — set whichever matches your protoc install.

## Build (Linux / macOS)

```bash
export QT_DIR=/opt/Qt/6.11.0/gcc_64
# Linux: `apt install protobuf-compiler` (or equivalent) usually puts
# protoc on PATH already, so no PROTOC_DIR is needed.
./build_qt.sh
```

## Run

```cmd
build-qt\test_service_qt_gui.exe
```

The window has a **Connect** button (defaults to
`http://127.0.0.1:50051`), service / method pickers, and a Send button
that fires the RPC via `QGrpcClient`.  Open
`src/MainWindow.cpp` → `onSendClicked()` and fill in the per-method
dispatch as documented in the inline TODO comment.

## Build for WebAssembly (browser target)

> **Caveat — read first.**  Browser WASM can't open raw TCP, so
> `QGrpcHttp2Channel` won't work unless your server is reachable as
> **gRPC-Web** (via an envoy / grpc-web-proxy in front of it).  The build
> scripts below produce a runnable `.wasm` + `.html`, but actual RPC
> calls require either (a) a `QGrpcWebChannel` in your Qt install (check
> `<QT_WASM_DIR>/include/QtGrpc/qgrpcwebchannel.h`), or (b) a hand-rolled
> `QAbstractGrpcChannel` subclass that frames gRPC-Web over
> `QNetworkAccessManager`.  Plan for this before investing time in the build.

### Prerequisites

| Component | Notes |
|---|---|
| Qt 6.x **WebAssembly (multi-threaded)** kit | Install via Qt Maintenance Tool → Qt 6.x → WebAssembly (multi-threaded) |
| Qt **GRPC** + Qt **Protobuf** + Qt **Protobuf Well Known Types** | **Tick under the WebAssembly target**, not just the desktop one |
| Matching **desktop** Qt of the same version | Needed for moc / rcc at build time (host tools) |
| **emsdk** activated with the version Qt was built against | See `<QT_WASM_DIR>/mkspecs/features/wasm/` or Qt release notes |
| Python 3 (for the dev server) | Stock library only — no extra packages |

### Environment

```cmd
:: Required
set "QT_WASM_DIR=C:\Qt\6.11.0\wasm_multithread"
set "QT_HOST_DIR=C:\Qt\6.11.0\mingw_64"
set "EMSDK_DIR=D:\Project\robot\github\emsdk"

:: Optional (auto-defaulted if Qt-bundled tools are in standard paths)
set "QT_CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
set "QT_NINJA_DIR=C:\Qt\Tools\Ninja"
```

### Build + serve

```cmd
build_wasm.bat          :: Configures + builds; output in build-wasm\
serve_wasm.bat          :: Serves build-wasm\ with COOP/COEP headers on :8000
```

Then open <http://127.0.0.1:8000/test_service_qt_gui.html>.

### Why a dedicated server?

Multi-threaded Qt WASM needs **SharedArrayBuffer**, which browsers gate
behind cross-origin isolation:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

`python -m http.server` and most static hosts don't set these — the page
loads but Qt's threading bootstrap silently hangs.  `serve_wasm.py` is a
3-line `SimpleHTTPRequestHandler` subclass that adds both headers.  For
production hosting (nginx, Caddy, GitHub Pages, …) configure those
response headers there.

### Known gotchas (carried over from internal qt_wasm_build.md notes)

- **Use Ninja, not Visual Studio.**  Emscripten doesn't work with the
  Visual Studio generator.  The build script always passes `-G Ninja`.
- **Don't use `qt-cmake.bat`.**  It hardcodes a Windows generator on
  Windows.  Call `cmake` directly with the toolchain (the script does).
- **`EMSDK_PYTHON` must point at emsdk's bundled Python.**  System
  Python fails inside `emcc` with `ModuleNotFoundError: No module named
  'tools'`.  The build script auto-detects it under `<EMSDK_DIR>/python/`.
- **Don't run `emsdk_env.bat` on Windows.**  It clears unrelated env
  vars; just set `EMSDK_DIR` + `EMSDK_PYTHON` and let the script PATH-prepend.
- **Qt's WASM kit may hardcode an emsdk path from its build host.**  We
  override with `QT_CHAINLOAD_TOOLCHAIN_FILE` pointing at your local emsdk.

## What's generated by the build

- `qt_add_protobuf` produces Qt-style message classes (`QProtobufMessage`
  subclasses) named `<package>::<MessageName>` — with QProperty / setter
  / getter pairs and signal/slot integration.
- `qt_add_grpc(... CLIENT)` produces client classes named
  `<package>::<ServiceName>::Client` whose RPC methods return
  `std::shared_ptr<QGrpcCallReply>`.

These are completely separate from the Google-grpc stubs in the parent
project's `proto/` folder — they don't conflict because they live in a
different binary.
