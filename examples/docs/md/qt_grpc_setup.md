# Qt6::Grpc Client Setup

Building `qt_client/` with the Qt-installer toolchain (separate from MSYS2).

> 📄 *Also available as HTML:* [`../html/qt_grpc_setup.html`](../html/qt_grpc_setup.html)
>
> Companion docs: [← Docs index](index.md) ·
> [MinGW (MSYS2) setup](mingw_setup.md) ·
> [vcpkg + Qt MinGW setup](vcpkg_setup.md) ·
> [Service creation](service_creation.md) ·
> [WASM service](wasm_cleware_service_guide.md)

## Why a separate `qt_client/` project?

When the wizard generates a service with GUI and you pick the
**Qt6::Grpc** client option, it emits a parallel CMake project at
`qt_client/`. This sits next to the existing Google-grpc `client/`
folder, but is built with a *different* toolchain. The three client
variants coexist; you pick whichever you prefer to run.

| Folder | Toolchain | gRPC stack | Code style |
|---|---|---|---|
| `client/` | MSYS2 MinGW (g++ 14.x) | Google grpc++ + libprotobuf | `grpc::ClientContext`, `JsonStringToMessage` |
| `qt_client/` | Qt-installer MinGW (g++ 13.x) | Qt6::Grpc + Qt6::Protobuf | `QGrpcClient`, `QProtobufJsonSerializer` |
| `qt_client_grpcpp/` | Qt-installer MinGW (g++ 13.x) + vcpkg | Google grpc++ (vcpkg-built) | `grpc::ClientContext` on `QtConcurrent::run`, `JsonStringToMessage` |

> 💡 **Three options coexist.** This doc covers the **`qt_client/`**
> variant. For **`qt_client_grpcpp/`** — Google grpc++ but compiled
> via vcpkg with Qt MinGW so client + server share one ABI — see the
> [vcpkg + Qt MinGW setup guide](vcpkg_setup.md).

> ⚠ **Don't mix the two.** MSYS2's libstdc++ (GCC 14) and Qt-installer's
> libstdc++ (GCC 13) ABIs are not compatible inside a *single* binary
> — you'd get cryptic link errors like `undefined reference to
> nanosleep64`. Each project keeps its own toolchain; they only share
> the *wire protocol*, which is fine because Qt6::Grpc and Google grpc++
> both speak the same HTTP/2 dialect.

The server side *always* uses Google grpc++ (built with MSYS2 in the
parent project) — **Qt 6 has no server module**, only client. So
`qt_client/` talks to the same `analog_input_service.exe`,
`pps_service.exe`, etc. that the Google-grpc `client/` talks to. Wire
interop is automatic.

## TL;DR

> **Three things to install**: Qt + MinGW kit, Qt's GRPC and Protobuf
> modules, Google's `protoc.exe` (separate from Qt!). Then either run
> `build_qt.bat` or open in Qt Creator.
>
> **If Qt Creator complains "protoc not found"**: add
> `Protobuf_PROTOC_EXECUTABLE` to *Projects → Build → CMake → Initial
> Configuration*, pointing at your `protoc.exe`.

## ![1] Qt components

Install via the **Qt Maintenance Tool** (the same tool you used for Qt
itself). Open *Add or remove components* and tick every entry below
under your chosen Qt version + MinGW kit:

| Component | Why |
|---|---|
| Qt 6.x.x → **MinGW 13.1.0 64-bit** | Qt 6 libraries built with MinGW |
| Qt 6.x.x → **Qt GRPC** | Client-side gRPC. Stable in **6.8+**; *Tech Preview* in 6.7 (works but API may shift). **Not installed by default.** |
| Qt 6.x.x → **Qt Protobuf** | `QProtobufMessage` runtime. Same caveat as Qt GRPC. |
| Qt 6.x.x → **Qt Protobuf WellKnownTypes** | `Empty`, `Timestamp`, etc. |
| Qt → Tools → **CMake** | CMake bundled with Qt (typically `C:\Qt\Tools\CMake_64`) |
| Qt → Tools → **Ninja** | Build driver |
| Qt → Tools → **MinGW 13.1.0 64-bit** | The compiler (typically `C:\Qt\Tools\mingw1310_64`) |

> **Qt 6.7 vs 6.8+:** in 6.7 the GRPC/Protobuf modules are *Tech
> Preview* — they exist but you have to opt in explicitly. In 6.8 they
> were promoted to stable and bundled by default with the MinGW kit.
> Strongly recommend 6.8 or later.

### Verify the install

From a Windows `cmd`:

```cmd
dir C:\Qt\6.11.0\mingw_64\lib\cmake\Qt6\Qt6Config.cmake
dir C:\Qt\6.11.0\mingw_64\lib\cmake\Qt6Grpc\Qt6GrpcConfig.cmake
dir C:\Qt\6.11.0\mingw_64\lib\cmake\Qt6Protobuf\Qt6ProtobufConfig.cmake
dir C:\Qt\Tools\mingw1310_64\bin\g++.exe
dir C:\Qt\Tools\CMake_64\bin\cmake.exe
dir C:\Qt\Tools\Ninja\ninja.exe
```

All six should list files. If `Qt6GrpcConfig.cmake` is missing, Qt
GRPC wasn't ticked — rerun the Maintenance Tool.

## ![2] Install Google's `protoc`

> ⚠ **The Qt installer does NOT bundle `protoc`.** Qt's `qt_add_grpc` /
> `qt_add_protobuf` CMake macros internally invoke Google's `protoc.exe`
> with Qt-supplied plugins (`protoc-gen-qtprotobuf`,
> `protoc-gen-qtgrpc`). Qt ships only the plugins.

Once code generation is done, the resulting binary doesn't link against
Google's `libprotobuf` — it uses Qt's own `QProtobufMessage` runtime.
You only need `protoc.exe` at build time.

### Easiest: MSYS2 (recommended if MSYS2 is already installed)

```bash
pacman -S mingw-w64-x86_64-protobuf
```

Lands at `C:\msys64\mingw64\bin\protoc.exe`. The generated
`CMakeLists.txt` auto-discovers this path.

### Standalone download

From <https://github.com/protocolbuffers/protobuf/releases>:

1. Download `protoc-<version>-win64.zip`.
2. Unzip anywhere, e.g. `C:\tools\protoc`.
3. Either add the `bin` folder to `PATH`, or set
   `PROTOC_DIR=C:\tools\protoc\bin` in your environment.

## ![3] Build via `build_qt.bat`

The fastest one-shot build. Open Windows `cmd` in the `qt_client/`
folder:

```cmd
:: Adjust if your Qt is somewhere else:
set "QT_DIR=C:\Qt\6.11.0\mingw_64"

:: Optional — only needed if protoc isn't auto-discovered:
set "PROTOC_DIR=C:\msys64\mingw64\bin"

build_qt.bat
```

The script discovers the rest of the toolchain automatically:

| Tool | Looked up under |
|---|---|
| MinGW g++ | `%QT_TOOLS%\mingw1310_64\bin\g++.exe` (with fallbacks) |
| CMake | `%QT_TOOLS%\CMake_64\bin\cmake.exe` |
| Ninja | `%QT_TOOLS%\Ninja\ninja.exe` |
| protoc | `PROTOC_DIR` → MSYS2 → vcpkg → PATH |

Default `QT_TOOLS` is `C:\Qt\Tools`. If any required tool is missing,
the script aborts with a message naming exactly which Maintenance Tool
component to install.

Output: `build-qt\<project>_qt_gui.exe`.

## ![4] Build via Qt Creator

### 4a. Open the project

1. **File → Open File or Project…** → pick `qt_client/CMakeLists.txt`.
2. In the kit picker, tick the **Desktop Qt 6.11.x MinGW 13.1.0 64-bit**
   kit.
3. Click **Configure Project**.

### 4b. If you see "protoc not found" / "Failed to find required Qt component Grpc"

Qt Creator's kit doesn't always have your shell's `PATH`, so the
auto-discovery built into `CMakeLists.txt` may not find `protoc`. Tell
it explicitly:

1. Click **Projects** in the left rail.
2. Under your kit → **Build → CMake** section.
3. Find **Initial Configuration** → click **Add**:

| Field | Value |
|---|---|
| Key | `Protobuf_PROTOC_EXECUTABLE` |
| Type | **FILEPATH** |
| Value | `C:/msys64/mingw64/bin/protoc.exe` (use forward slashes) |

> 🚫 **You must click "Re-configure with Initial Parameters", not the
> regular Run CMake.** Initial Configuration is only consulted when
> CMake's cache is rebuilt; a normal *Run CMake* uses the stale cache
> and the variable won't take effect. If unsure, right-click the
> project → **Clear CMake Configuration** first.

### 4c. Build + run

- **Ctrl+B** — Build All
- **Ctrl+R** — Run
- **F5** — Debug (runs under Qt's bundled GDB)

### 4d. Alternative: via the kit Environment

If you'd rather not change per-project settings, edit the kit env:
**Tools → Options → Kits** → your MinGW kit → *Environment → Change…*,
add:

```
PROTOC_DIR=C:\msys64\mingw64\bin
```

The `CMakeLists.txt` picks up `PROTOC_DIR` before falling back to its
other candidates. Restart Qt Creator after editing kit env.

## How `CMakeLists.txt` finds `protoc`

The generated `qt_client/CMakeLists.txt` contains an auto-discovery
block that runs before `find_package(Qt6 ...)`. It checks these
candidates in order, and uses the first one that exists:

| # | Candidate | How to override |
|---|---|---|
| 1 | Cache variable `Protobuf_PROTOC_EXECUTABLE` already set | Pass `-DProtobuf_PROTOC_EXECUTABLE=...` to CMake, or set in Qt Creator Initial Configuration. |
| 2 | `$PROTOC_DIR/protoc.exe` | Set `PROTOC_DIR` env var before invoking CMake / build_qt.bat. |
| 3 | `C:/msys64/mingw64/bin/protoc.exe` | Built-in default for MSYS2 mingw64. |
| 4 | `C:/msys64/ucrt64/bin/protoc.exe` | Built-in default for MSYS2 ucrt64. |
| 5 | `$VCPKG_ROOT/installed/x64-windows/tools/protobuf/protoc.exe` | If you use vcpkg. |
| 6 | `find_program(protoc)` on `PATH` | Make sure protoc is on Qt Creator's kit `PATH`. |

Once a candidate matches, CMakeLists also:

- Prepends the protoc folder to `ENV{PATH}` so Qt's `WrapProtoc` module
  (which does its own `find_program(protoc)`) sees it.
- Adds the install prefix (the parent of `bin/`) to `CMAKE_PREFIX_PATH`
  so `find_package(Protobuf)` finds matching `libprotobuf` headers + libs.

> Qt's GRPC build hooks transitively call `find_dependency(Protobuf)` —
> it wants the executable *and* headers + libs, even though Qt doesn't
> link against `libprotobuf` at runtime. When `protoc.exe` is on PATH,
> the standard `FindProtobuf.cmake` derives those automatically;
> otherwise the prefix push above is what makes it succeed.

## Qt 6 API differences (6.5 → 6.11)

The generated `MainWindow.cpp` targets **Qt 6.8 or later**. If you're
on 6.5–6.7 you'll hit these differences:

| API | 6.5–6.7 | 6.8+ |
|---|---|---|
| Channel options + URL | `QGrpcChannelOptions opts(QUrl(...));`<br>`QGrpcHttp2Channel ch(opts);` | `QGrpcHttp2Channel ch(QUrl(...));` |
| RPC return type | `std::shared_ptr<QGrpcCallReply>` | `std::unique_ptr<QGrpcCallReply>` |
| Reply read | `bool reply->read(Msg*)` | `std::optional<T> reply->read<T>()` |

The generic `invokeRpc<Req, Resp>` template in the generated
`MainWindow.h` uses the 6.8+ shape:

```cpp
auto reply = callRpc(req);
auto* raw  = reply.get();
connect(raw, &QGrpcCallReply::finished, this,
    [r = std::move(reply), done](const QGrpcStatus& st) {
        if (!st.isOk()) { done(false, "RPC failed: " + st.message()); return; }
        auto resp = r->template read<Resp>();
        if (!resp) { done(false, "Failed to read"); return; }
        done(true, QString::fromUtf8(resp->serialize(&ser)));
    });
```

Note `std::move` capture (because `reply` is `unique_ptr`, not
`shared_ptr`), and the `r->template read<Resp>()` disambiguator
(because `Resp` is a dependent type inside a function template).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'protoc' executable is not found` | Install protoc (see [Step 2](#2-install-googles-protoc)) and either set `PROTOC_DIR` or pass `-DProtobuf_PROTOC_EXECUTABLE=...` in Qt Creator Initial Configuration. Don't forget to click *Re-configure with Initial Parameters*. |
| `Failed to find required Qt component "Grpc"` — but `Qt6GrpcConfig.cmake` exists | This usually chains from a missing protoc or a missing Protobuf headers/libs. Check that `C:\Qt\<ver>\mingw_64\lib\cmake\Qt6Grpc\` exists, and verify the `--> Using protoc:` line shows up in the General Messages pane during configure. |
| `Failed to find required Qt component "Grpc"` — `Qt6GrpcConfig.cmake` does NOT exist | Qt GRPC component wasn't installed. Open Qt Maintenance Tool → tick *Qt 6.x.x → Qt GRPC*, install, retry. |
| Compiler picked up is `C:/StPerl532_x64/c/bin/c++.exe` or another stray g++ | Strawberry Perl / random MinGW on PATH. The generated `build_qt.bat` refuses this and forces Qt's bundled MinGW; if you're configuring from Qt Creator, make sure the kit's C++ compiler is the Qt-installer MinGW (*Tools → Options → Kits → Compilers*). |
| Cryptic link errors mentioning `nanosleep64`, `__cxa_throw_bad_array_*` | You're mixing libstdc++ from two MinGW versions in one binary. Don't add MSYS2's `C:\msys64\mingw64` to `CMAKE_PREFIX_PATH` for a Qt-installer build. The auto-discovery only adds it for protoc's parent *directory*, which doesn't bring libstdc++ along. |
| Configure fails after a successful build, with stale variables | Right-click the project in Qt Creator → **Clear CMake Configuration**, or delete `build/Desktop_Qt_*`. CMake caches things aggressively; an "unset" env var doesn't clear an old cache value. |
| `'unique_ptr<QGrpcCallReply>' use of deleted copy constructor` while compiling MainWindow | You're on Qt 6.5–6.7 (where the API uses `shared_ptr`) but using the 6.8+ generated code. Easiest fix: upgrade Qt to 6.8 or later. Or hand-edit the lambda capture from `[reply, done]` to `[r = std::move(reply), done]`. |
| `QGrpcChannelOptions(QUrl)` — no matching ctor | Same root cause: code expects 6.5–6.7 ctor. In 6.8+ pass the URL directly to `QGrpcHttp2Channel(QUrl(...))`. See the [Qt 6 API differences](#qt-6-api-differences-65--611) table. |
| Build succeeds but exe silent-dies on Run | Almost always Qt's *platform plugin* (`platforms\qwindows.dll`) can't be found. Install *Qt → Tools → Qt Tools* which gives you `windeployqt.exe`, then run it on your output binary. Or set `QT_PLUGIN_PATH=C:\Qt\<ver>\mingw_64\plugins` in your shell. |

---

*Companion to [mingw_setup.md](mingw_setup.md) — this page covers the
Qt-installer / Qt6::Grpc workflow; that one covers the MSYS2 / Google
grpc++ workflow. Both are valid, just pick one toolchain per binary.*
