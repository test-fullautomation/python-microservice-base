# MultiProto2 Qt Client (Google grpc++ via vcpkg)

Qt Widgets UI client for **MultiProto2** that links Google's
`grpc++` C++ library (built by vcpkg with the **Qt-installer MinGW
13.1.0** toolchain).  Companion to the server in the parent project,
which can also be built with the same toolchain via `..\build_qt_vcpkg.bat`.

## Why this variant

Sibling `qt_client/` (when picked) uses **Qt6::Grpc + Qt6::Protobuf** —
Qt-native, no Google grpc dependency on the client side.  This variant
(`qt_client_grpcpp/`) uses **Google grpc++** end-to-end so client and
server share one transport library.  Tradeoff: ~30–60 min first-time
vcpkg build.

## Prerequisites (one-time)

1. Qt 6.x installed via Online Installer, including **MinGW 13.1.0 64-bit** under Tools.
2. vcpkg cloned + bootstrapped:
   ```bat
   git clone https://github.com/microsoft/vcpkg.git C:\vcpkg
   C:\vcpkg\bootstrap-vcpkg.bat
   setx VCPKG_ROOT C:\vcpkg
   ```
3. Set Qt prefix:
   ```bat
   setx QT_DIR C:\Qt\6.11.0\mingw_64
   ```
4. Optional: override Qt MinGW path: `setx QT_MINGW_BIN C:\Qt\Tools\mingw1310_64\bin`

## Build

```bat
build_qt.bat
```

First run: vcpkg compiles `boringssl + abseil + protobuf + grpc` with Qt
MinGW (~30–60 min wall time, mostly idle).  Subsequent runs hit the
binary cache and complete in seconds.

Output: `build\multi_proto2_qt_gui.exe` linking against vcpkg DLLs in
`build\vcpkg_installed\x64-mingw-qt\bin\`.

## Deploy to another PC (no rebuild)

```bat
deploy_qt.bat
```

Bundles `.exe` + Qt DLLs + vcpkg DLLs + MinGW runtime into `deploy\`.
Zip + copy to any Windows x64 PC; no Qt / vcpkg / MinGW install required
on target.

## Share build artifacts with other developers (skip vcpkg rebuild)

```bat
export_prebuilt.bat
```

Produces:

- `prebuilt\vcpkg_installed_x64-mingw-qt.zip` (~50–80 MB)
- `prebuilt\vcpkg_binary_cache.zip` (vcpkg cache zips)

Receiving PC: unzip the installed tree into `qt_client_grpcpp\build\vcpkg_installed\`,
then `build_qt.bat` skips the install step entirely.

## Troubleshooting

- **`ninja: manifest 'build.ninja' still dirty after 100 tries`** — gcc
  13.1.0 ICE in grpc; the overlay-port at `..\ports\grpc\` includes a
  workaround patch (`00018-gcc13-per-cpu-ice-workaround.patch`).
- **`protoc not found`** — vcpkg installs its own protoc; check
  `build\vcpkg_installed\x64-mingw-qt\tools\protobuf\protoc.exe`.
- **`Failed to find required Qt component`** — set `QT_DIR` or
  `Qt6_DIR` env var pointing at `C:\Qt\6.x.y\mingw_64`.
- **`cmake: Invalid character escape '\Q'`** — old `CMakeFiles\` from
  a previous failed configure; `build_qt.bat` wipes them on each run.

## Use with Qt Creator

Open `CMakeLists.txt` in Qt Creator.  In **Project → Build → CMake →
Initial Configuration**, add:

```
-DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake
-DVCPKG_TARGET_TRIPLET=x64-mingw-qt
-DVCPKG_OVERLAY_TRIPLETS=%{sourceDir}/../triplets
-DVCPKG_OVERLAY_PORTS=%{sourceDir}/../ports
```

Configure → vcpkg toolchain auto-installs deps (or restores from cache).
Drop `build/vcpkg_installed/x64-mingw-qt/` from a teammate's
`export_prebuilt.bat` to skip the install entirely.
