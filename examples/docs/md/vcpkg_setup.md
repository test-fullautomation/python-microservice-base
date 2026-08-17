# vcpkg + Qt MinGW Setup

The `google_vcpkg` client variant builds Google `grpc++` from source via
**vcpkg** using the **Qt-installer MinGW 13.1.0** toolchain. Same gRPC C++
API as the MSYS2 variant, but compiled with Qt's gcc so client and server
share one libstdc++ ABI end-to-end.

> 📄 *Also available as HTML:* [`../html/vcpkg_setup.html`](../html/vcpkg_setup.html)
>
> 💡 **Independent client + server toggles.** The wizard has two
> separate choices: **Client gRPC stack** (`google` / `qt` /
> `google_vcpkg`) and **Server toolchain** (`msys2` / `vcpkg`). Pick
> any combination — wire format is the same. Picking `vcpkg` for both
> sides is the "one toolchain end-to-end" sweet spot; the vcpkg cache
> is shared so the second build is essentially free.

## When to pick this path

Compared to the other two client variants:

| | `google` (MSYS2) | `qt` (Qt6::Grpc) | **`google_vcpkg`** |
|---|---|---|---|
| Client toolchain | MSYS2 MinGW 14.x | Qt-installer MinGW 13.1.0 | **Qt-installer MinGW 13.1.0** |
| Server toolchain | MSYS2 MinGW 14.x | MSYS2 MinGW 14.x | **Qt-installer MinGW 13.1.0** |
| gRPC stack (client) | Google grpc++ | Qt6::Grpc + Qt6::Protobuf | **Google grpc++** |
| Built from source? | No (MSYS2 pacman) | No (Qt installer) | **Yes (vcpkg, ~30–60 min once)** |
| One toolchain everywhere | No | No | **Yes** |
| Qt signals/slots in RPC code | No | Yes | No (use QtConcurrent worker) |
| Wire-protocol interop | ✅ | ✅ | ✅ |
| Sample folder | `client/` | `qt_client/` | `qt_client_grpcpp/` |

**Pick `google_vcpkg` when**:

- You want one compiler ABI for client + server (no MSYS2 / Qt MinGW
  split). Helpful for shared static libraries between sides, common
  debug experience, and simpler kit setup in Qt Creator.
- You'd rather invest 30–60 min once in a vcpkg build than maintain a
  parallel MSYS2 install.
- You don't need Qt6::Grpc's signal/slot RPC ergonomics — the
  generated `qt_client_grpcpp/MainWindow` uses `QtConcurrent::run` for
  the sync grpc++ stub call, then marshals back to the UI thread.

**Pick `google` (MSYS2)** when you already have MSYS2 set up and don't
want a long first-time vcpkg build.

**Pick `qt`** when you want Qt-native RPC types (signals on responses,
QFuture on calls) and don't need the server's exact same toolchain.

## Prerequisites (one-time)

### 1. Qt 6.x with MinGW 13.1.0

Install via [Qt Online Installer](https://www.qt.io/download-qt-installer).
Required components:

- **Qt 6.x → MinGW 13.1.0 64-bit** — the actual Qt libraries (Core, Gui,
  Widgets, Network, Concurrent).
- **Tools → MinGW 13.1.0 64-bit** — the compiler (gcc/g++/windres).
  Lives at `C:\Qt\Tools\mingw1310_64\`.
- **Tools → CMake** + **Tools → Ninja** — build system.

> Other Qt versions (6.8, 6.9, 6.10, 6.11, …) are fine as long as the
> bundled MinGW is gcc 13.1.0. If your Qt ships a different gcc (e.g.
> Qt 6.9's MinGW 14.x), see [Other Qt compilers](#other-qt-compilers).

### 2. vcpkg

```bat
git clone https://github.com/microsoft/vcpkg.git C:\vcpkg
C:\vcpkg\bootstrap-vcpkg.bat
setx VCPKG_ROOT C:\vcpkg
```

Open a fresh terminal so `setx` takes effect.

### 3. Environment variables

```bat
setx QT_DIR        C:\Qt\6.11.0\mingw_64
setx QT_MINGW_BIN  C:\Qt\Tools\mingw1310_64\bin
setx VCPKG_ROOT    C:\vcpkg
```

(`QT_MINGW_BIN` defaults to `C:\Qt\Tools\mingw1310_64\bin` if not set —
override only if your Qt is installed elsewhere.)

### 4. Windows 10 1803 or later

The bundled `tar.exe` (`%SystemRoot%\System32\tar.exe`) is needed by
`deploy_qt.bat` and `export_prebuilt.bat`. All recent Windows 10/11 ship
this; nothing to install.

## What the scaffold emits

When you scaffold a service with `--client-grpc google_vcpkg` (or pick
that option in the wizard), the generator writes:

```
<service>/
├── CMakeLists.txt              ← server (already vcpkg-compatible)
├── build_qt_vcpkg.bat          ← server build with Qt MinGW + vcpkg
├── triplets/                   ← shared by server + client
│   ├── x64-mingw-qt.cmake
│   └── qt-mingw-toolchain.cmake
├── ports/grpc/                 ← shared overlay-port (filled at first build)
│   └── 00018-gcc13-per-cpu-ice-workaround.patch
├── init_vcpkg_overlay.bat      ← one-shot: copies upstream port + applies patch
├── (server src/, proto/, etc.)
└── qt_client_grpcpp/
    ├── CMakeLists.txt
    ├── vcpkg.json              ← grpc + protobuf
    ├── build_qt.bat            ← client build
    ├── deploy_qt.bat           ← bundle .exe + DLLs into deploy/
    ├── export_prebuilt.bat     ← package vcpkg artifacts for other devs
    ├── README.md
    ├── proto/<svc>.proto
    └── src/{main.cpp, MainWindow.{h,cpp,ui}}
```

## Build workflow

### First build (~30–60 min, mostly idle)

```bat
cd <service>\qt_client_grpcpp
build_qt.bat
```

What happens:

1. **`init_vcpkg_overlay.bat`** runs once if `..\ports\grpc\portfile.cmake`
   doesn't exist. Copies upstream grpc port from `%VCPKG_ROOT%\ports\grpc\`,
   appends `00018-gcc13-per-cpu-ice-workaround.patch` to the PATCHES
   list. Idempotent.
2. **vcpkg install** (manifest mode) reads `vcpkg.json`, downloads +
   builds: zlib, openssl, c-ares, re2, abseil, protobuf, grpc — all
   with the pinned Qt MinGW 13.1.0 toolchain via the custom
   `x64-mingw-qt` triplet.
3. **CMake configure** with `-DCMAKE_TOOLCHAIN_FILE=...vcpkg.cmake` so
   `find_package(gRPC CONFIG REQUIRED)` resolves to the just-built
   artifacts under `build\vcpkg_installed\x64-mingw-qt\`.
4. **Ninja build** compiles generated `.pb.cc` / `.grpc.pb.cc` +
   `MainWindow.cpp` + `main.cpp` → `build\<service>_qt_gui.exe`.

### Subsequent builds

vcpkg hits the binary cache (`%LOCALAPPDATA%\vcpkg\archives\`) and
restores the install tree in seconds. CMake re-configure + ninja
rebuild only your code → ~15 sec total.

### Server with the same toolchain

```bat
cd <service>
build_qt_vcpkg.bat
```

Server uses the same `x64-mingw-qt` triplet and the same overlay-port,
so the `vcpkg install` step is essentially free (cache hit from
client's first build).

## Why a custom triplet?

vcpkg's stock `x64-mingw-dynamic` triplet picks up whatever `gcc.exe`
is first on `PATH`. If MSYS2's bin is ahead of Qt's in your PATH, vcpkg
silently builds with MSYS2's gcc 14 — and the resulting grpc DLLs are
binary-incompatible with Qt 6.x (built with gcc 13.1.0).

The custom triplet `x64-mingw-qt` chainloads
`qt-mingw-toolchain.cmake`, which **pins** the compiler:

```cmake
set(CMAKE_C_COMPILER   "C:/Qt/Tools/mingw1310_64/bin/gcc.exe")
set(CMAKE_CXX_COMPILER "C:/Qt/Tools/mingw1310_64/bin/g++.exe")
```

Result: every port built with this triplet uses Qt's gcc, regardless of
PATH order. ABI matches Qt 6 binaries every time.

## The gcc 13.1.0 ICE workaround

gcc 13.1.0 has an internal compiler error (segmentation fault) when
instantiating this template in grpc 1.76's `src/core/util/per_cpu.h`:

```cpp
std::unique_ptr<T[]> data_{new T[shards_]};   // NSDMI brace-init
```

Reproduces under both `-O0/-g` and `-O3/-DNDEBUG`. Fixed in gcc 13.3+,
but Qt's installer ships exactly 13.1.0 with no easy override.

The patch (`ports/grpc/00018-gcc13-per-cpu-ice-workaround.patch`) moves
the array allocation from NSDMI into the constructor's mem-initializer
list — semantically identical, takes a different front-end path that
doesn't ICE:

```cpp
PerCpu(PerCpuOptions options)
    : shards_(options.Shards()),
      data_(std::unique_ptr<T[]>(new T[shards_])) {}
// ...
std::unique_ptr<T[]> data_;   // declared, init'd in ctor body
```

The overlay-port keeps the project self-contained: vcpkg's stock grpc
port is unchanged on disk; ours just adds one more patch in the
`PATCHES` list.

## Output: DLLs and what to deploy

After build, `qt_client_grpcpp/build/vcpkg_installed/x64-mingw-qt/` has:

- **bin/** — runtime DLLs (protobuf, abseil, openssl, c-ares, re2,
  zlib). About 9 files.
- **lib/** — static `.a` libs (grpc, gpr, upb, abseil submodules,
  utf8_range), plus import libs `.dll.a` for the dynamic deps.
- **include/** — headers (grpcpp/, google/protobuf/, …).
- **share/** — CMake config files for `find_package(gRPC CONFIG)`.
- **tools/** — `protoc.exe`, `grpc_cpp_plugin.exe`.

Note: **grpc itself is static** on Windows (vcpkg's grpc port forces
`vcpkg_check_linkage(ONLY_STATIC_LIBRARY)`). The `.exe` already
contains `libgrpc++.a` baked in; you don't need to ship `libgrpc++.dll`
because there isn't one. The dynamic DLLs in `bin/` are grpc's
*dependencies*, which still need to travel with the binary.

To deploy to a clean PC (no Qt / no vcpkg / no MinGW required on
target):

```bat
deploy_qt.bat
```

Bundles into `deploy\`:

- The `.exe`
- Qt6 runtime DLLs + `platforms\qwindows.dll` + plugins (via `windeployqt-qt6`)
- MinGW runtime: `libstdc++-6.dll`, `libgcc_s_seh-1.dll`, `libwinpthread-1.dll`
- vcpkg runtime DLLs from `vcpkg_installed\x64-mingw-qt\bin\`

Total ~80–120 MB. Zip + copy to any Windows x64 machine, unzip, run.

## Sharing build artifacts (skip 30–60 min on other dev PCs)

```bat
export_prebuilt.bat
```

Produces two archives in `prebuilt\`:

- **`vcpkg_installed_x64-mingw-qt.zip`** (~50–80 MB) — the full
  installed tree. On the receiving PC: unzip into
  `qt_client_grpcpp\build\vcpkg_installed\` and run `build_qt.bat` —
  vcpkg sees "everything installed" and skips the build step.

- **`vcpkg_binary_cache.zip`** (~200–400 MB) — the vcpkg binary cache
  zips. On the receiving PC: unzip into `%LOCALAPPDATA%\vcpkg\` and
  run `build_qt.bat` — vcpkg "Restored from cache" for every port.

For team-wide setup, use a shared cache instead:

```bat
setx VCPKG_BINARY_SOURCES "files,\\fileserver\share\vcpkg-cache,readwrite"
```

First dev to build a port populates the cache; everyone else hits it.

## Use with Qt Creator

Qt Creator is a frontend for cmake — it has no built-in vcpkg knowledge,
but cmake does. To make the project work in Qt Creator:

1. Open `qt_client_grpcpp/CMakeLists.txt` in Qt Creator (or the parent
   server's `CMakeLists.txt`).
2. **Project → Build → CMake → Initial Configuration**, add:
   ```
   -DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake
   -DVCPKG_TARGET_TRIPLET=x64-mingw-qt
   -DVCPKG_OVERLAY_TRIPLETS=%{sourceDir}/../triplets
   -DVCPKG_OVERLAY_PORTS=%{sourceDir}/../ports
   ```
   (For the server's CMakeLists, drop the `../` since `triplets/` and
   `ports/` are siblings.)
3. **Configure** → vcpkg toolchain runs `vcpkg install` automatically.
   Builds from source if cache miss; restores from cache if hit.

To skip the install entirely: drop a pre-built
`build/vcpkg_installed/x64-mingw-qt/` (from a teammate's
`export_prebuilt.bat`) into the build directory before configuring.
vcpkg will see "everything installed" and skip in seconds.

## Other Qt compilers

The current triplet pins `mingw1310_64`. To support a different Qt
toolchain (e.g. Qt 6.9's gcc 14, or Qt's optional `llvm-mingw1706_64`
clang kit), make a parallel triplet:

```
triplets/
├── x64-mingw-qt.cmake          ← current (gcc 13.1.0)
├── x64-mingw-qt-gcc14.cmake    ← new (gcc 14.x)
└── x64-mingw-qt-llvm17.cmake   ← new (clang via llvm-mingw)
```

Each triplet sets `VCPKG_CHAINLOAD_TOOLCHAIN_FILE` to a corresponding
`*-toolchain.cmake` that pins compiler paths. Pick one via
`-DVCPKG_TARGET_TRIPLET=x64-mingw-qt-gcc14`.

Notes per compiler:

- **gcc 14.x** — ABI-compatible with gcc 13.x at libstdc++ level, so
  binaries link fine against Qt 6 built with 13.1.0. The grpc 1.76 ICE
  may not affect 14.x — try without the patch first.
- **llvm-mingw 17 (clang)** — uses libstdc++ (NOT libc++) when shipped
  with Qt, so ABI matches gcc-built Qt. Clang has no ICE on the grpc
  per_cpu.h pattern. Slightly different command-line conventions vs gcc.
- **MSVC** — different beast: needs `x64-windows` triplet (CRT instead
  of MSYS), Qt MSVC kit, vcpkg's stock port works without any patch.

## Troubleshooting

### `... was unexpected at this time` from `.bat` scripts

Windows codepage choking on non-ASCII characters in the script (em-dash
`—`, ellipsis `…`) or LF-only line endings. The generator emits
ASCII-only with CRLF endings. If you edit a `.bat` in Notepad++ /
VSCode, save as **CRLF + ANSI** (or UTF-8 without BOM).

### `ninja: manifest 'build.ninja' still dirty after 100 tries`

vcpkg-built artifacts are fine; the loop comes from in-source codegen
output. Our generated CMakeLists.txt sets
`PROTOC_OUT_DIR=${CMAKE_BINARY_DIR}/grpc_gen` precisely to avoid this.
If you've manually changed it back to the source tree, change it
again.

### `Invalid character escape '\Q'` from CMake

CMake stored a Windows backslash path in `CMakeFiles\<ver>\CMakeCXXCompiler.cmake`
and is now re-parsing it as a script. The generated `build_qt.bat`
converts all paths to forward slashes (`%PATH:\=/%`) precisely to
avoid this. If you customise the script, do the same for any new path
arg.

### vcpkg `BUILD_FAILED` for grpc

99% of the time this is the gcc 13.1.0 ICE in `per_cpu.h`. Verify the
overlay-port has our patch:

```bat
type ports\grpc\portfile.cmake | findstr 00018
```

Should output `00018-gcc13-per-cpu-ice-workaround.patch`. If missing,
delete `ports\grpc\` and re-run `init_vcpkg_overlay.bat`.

For other failures, full log is at:
```
%VCPKG_ROOT%\buildtrees\grpc\install-x64-mingw-qt-rel-out.log
```

### `protoc not found` at CMake configure

vcpkg's grpc port installs `protoc.exe` to
`build\vcpkg_installed\x64-mingw-qt\tools\protobuf\`. The vcpkg
toolchain file adds this to CMake's search path automatically. If not
found, you're probably configuring without the toolchain file — check
that `-DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake`
is in your CMake args.

### `Failed to find required Qt component "Widgets"` (or similar)

`QT_DIR` not set, or pointing at the wrong prefix. Should be
`C:\Qt\6.x.y\mingw_64`, not `C:\Qt\Tools\…`.

## Anatomy of the build infrastructure

For the curious:

- **`triplets/x64-mingw-qt.cmake`** — vcpkg triplet. Sets target
  arch/CRT/library linkage, then chainloads
  `qt-mingw-toolchain.cmake`. Also sets `VCPKG_BUILD_TYPE release`
  to skip the Debug build (halves time, dodges gcc 13.1.0 ICE that
  triggered with `-O0` flags too).
- **`triplets/qt-mingw-toolchain.cmake`** — CMake toolchain that pins
  `CMAKE_C_COMPILER` / `CMAKE_CXX_COMPILER` / etc to absolute paths
  inside Qt's `mingw1310_64\bin`. Reads `QT_MINGW_BIN` env var if set.
- **`ports/grpc/`** — vcpkg overlay-port. Filled by
  `init_vcpkg_overlay.bat` on first build (copies from
  `%VCPKG_ROOT%\ports\grpc\`, then appends our patch). After init,
  contains: portfile.cmake, vcpkg.json, 00001..00017 patches from
  upstream, and our 00018 ICE workaround.
- **`init_vcpkg_overlay.bat`** — one-shot bootstrap. Idempotent:
  re-running is a no-op once `ports/grpc/portfile.cmake` exists.
- **`build_qt.bat` (client)** — drives `vcpkg install` →
  `cmake configure` → `ninja build`. Quotes all paths, normalises
  backslashes, wipes stale `CMakeFiles/`.
- **`build_qt_vcpkg.bat` (server)** — same workflow for the server's
  CMakeLists, using the same triplet + overlay-port so cache is
  shared.

## See also

- **[Service creation guide](service_creation.md)** — once your scaffold
  is generated, the long-form tutorial for filling in the domain.
- **[Service Creator wizard](../../../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md)** — generate the scaffold
  from the Manager GUI's 4-step wizard (pick the third gRPC stack
  option in step 2).
- **[MinGW Setup (MSYS2)](mingw_setup.md)** — the alternative
  toolchain (server uses MSYS2's prebuilt grpc).
- **[Qt6::Grpc Setup](qt_grpc_setup.md)** — the Qt-native client
  variant that doesn't use Google grpc at all.
