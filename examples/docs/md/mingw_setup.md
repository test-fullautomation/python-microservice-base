# MinGW Setup on Windows — Step-by-Step Guide

From zero to a working MinGW build environment using **MSYS2**.

> 📄 *Also available as HTML:* [`../html/mingw_setup.html`](../html/mingw_setup.html)
>
> Companion docs: [← Docs index](index.md) ·
> [Qt6::Grpc client setup](qt_grpc_setup.md) ·
> [vcpkg + Qt MinGW setup](vcpkg_setup.md) ·
> [Service creation](service_creation.md) ·
> [WASM service](wasm_cleware_service_guide.md)
>
> 💡 *Alternative:* if you'd rather build the server with Qt's
> MinGW toolchain (one ABI for client + server, no MSYS2 install),
> see [vcpkg + Qt MinGW setup](vcpkg_setup.md). MSYS2 is the
> traditional path; vcpkg is the newer all-in-one path.

## Quick Start

> Install **MSYS2** → `pacman -Syu` twice → install the compiler +
> packages → run `build_deploy_msys2.bat`. Total time: **~20 minutes**,
> most of it downloading.

```bash
# One-liner after MSYS2 is installed and updated:
pacman -S --needed --noconfirm \
    mingw-w64-x86_64-gcc \
    mingw-w64-x86_64-gdb \
    mingw-w64-x86_64-cmake \
    mingw-w64-x86_64-ninja \
    mingw-w64-x86_64-grpc \
    mingw-w64-x86_64-protobuf \
    mingw-w64-x86_64-curl \
    mingw-w64-x86_64-qt6-base \
    mingw-w64-x86_64-qt6-tools
```

## Why MSYS2 for MinGW on Windows?

The honest reason: **MSYS2 is the only MinGW distribution where
`pacman` will install pre-built `grpc`, `protobuf`, and `Qt6` for you**.
Plain MinGW (TDM, mingw-w64 standalone) requires you to build all
dependencies from source — hours of vcpkg or manual compilation per
machine.

Other reasons:

- Current GCC (14.x at time of writing).
- Coherent libstdc++ ABI across all packages — no version-mixing
  headaches.
- The `mingw-w64-x86_64-grpc` package pulls in matching abseil, re2,
  cares, openssl, etc. as proper dependencies.
- Updates are one `pacman -Syuu` command.

## MinGW vs. MSVC — what's the honest difference?

For this project, **either works**. Differences worth knowing:

| Concern | MinGW (MSYS2) | MSVC |
|---|---|---|
| Compile-time diagnostics | Slower, more standards-strict | Faster, sometimes more permissive |
| C++ runtime | `libstdc++` (GCC) | Microsoft's STL |
| Dependencies | `pacman -S` | vcpkg builds from source |
| Binary size | Larger by ~2-5× (static libstdc++ if used) | Smaller |
| Debugging | gdb (very capable, but Qt Creator's gdb is best) | MSVC debugger / Visual Studio |
| Profiling | Limited Windows tools | VTune, Visual Studio Profiler |
| Bundled DLLs at runtime | libstdc++-6, libgcc, libwinpthread | MSVC runtime (often pre-installed on user machines) |

The generated build scripts support all three: `build_deploy.bat`
(MSVC), `build_deploy_mingw.bat` (vcpkg+MinGW), `build_deploy_msys2.bat`
(this guide). Pick whichever your team already uses.

## "I already have Qt for MinGW from the Qt installer — can I skip MSYS2's Qt?"

**Short answer: don't mix them.** The Qt installer's MinGW (GCC 11.x or
13.x depending on version) and MSYS2's MinGW (GCC 14.x) have
incompatible libstdc++ ABIs. Mixing libraries from both in one binary
produces obscure link errors (`nanosleep64`, `__cxa_throw_bad_array_*`).

Two safe options:

1. **All MSYS2** (this guide) — install Qt6 via `pacman -S
   mingw-w64-x86_64-qt6-base` so it matches the rest of your stack.
2. **All Qt-installer** — see [Qt6::Grpc setup](qt_grpc_setup.md) for
   the alternative path that uses `C:\Qt\...\mingw_64` exclusively.

Each project picks one and stays inside it.

## ![1] Install MSYS2

Download from <https://www.msys2.org/> and run the installer. Default
install location: `C:\msys64`. If you pick a different path, remember
it — every script in this guide assumes the default.

After install, launch **MSYS2 UCRT64** (or **MSYS2 MINGW64** — both
work) from the Start Menu.

> Don't use plain "MSYS2 MSYS" — that's the POSIX-emulation shell
> intended for MSYS2's own bootstrap. We want one of the *native*
> MinGW shells.

## ![2] First-Time Update (One-Time)

```bash
pacman -Syu
```

You'll be prompted to **close the terminal** (it's updating pacman
itself). Close it, reopen MSYS2 UCRT64, then run the update again to
finish:

```bash
pacman -Syu
```

This second pass updates the rest of the system.

## ![3] Install Compiler + Libraries

Still inside the MSYS2 terminal:

```bash
pacman -S --needed --noconfirm \
    mingw-w64-x86_64-gcc \
    mingw-w64-x86_64-gdb \
    mingw-w64-x86_64-cmake \
    mingw-w64-x86_64-ninja \
    mingw-w64-x86_64-grpc \
    mingw-w64-x86_64-protobuf \
    mingw-w64-x86_64-curl \
    mingw-w64-x86_64-qt6-base \
    mingw-w64-x86_64-qt6-tools
```

### What each package does

| Package | Purpose |
|---|---|
| `mingw-w64-x86_64-gcc` | The C++ compiler (`g++.exe`) + libstdc++ |
| `mingw-w64-x86_64-gdb` | Debugger (`gdb.exe`) — used by Qt Creator's F5 debug and command-line crash traces |
| `mingw-w64-x86_64-cmake` | Build-system generator |
| `mingw-w64-x86_64-ninja` | Fast parallel build driver |
| `mingw-w64-x86_64-grpc` | gRPC++ runtime + `grpc_cpp_plugin` for code generation |
| `mingw-w64-x86_64-protobuf` | Protobuf runtime + `protoc` compiler |
| `mingw-w64-x86_64-curl` | Used by `ConsulRegistration` to talk to Consul |
| `mingw-w64-x86_64-qt6-base` | Qt 6 Core / GUI / Widgets — for the Widgets GUI client |
| `mingw-w64-x86_64-qt6-tools` | Qt tools (incl. `windeployqt-qt6.exe`) for packaging |

> **Tip:** if you prefer a single command, `mingw-w64-x86_64-toolchain`
> is a meta-package that pulls in `gcc`, `gdb`, `binutils`, and the
> rest of the core toolchain at once. It adds ~100 MB you probably
> won't use, so the explicit list above is the lean option.

> **Expected time: 5–15 minutes.** Download size ~500 MB, installed
> size ~1.5 GB. No compilation — these are prebuilt.

When the prompt returns, close the MSYS2 terminal. You're done with it
for this project.

## ![4] Verify the Install

Open a **plain Windows cmd** (Win+R → `cmd` → Enter). Run:

```cmd
dir C:\msys64\mingw64\bin\g++.exe
dir C:\msys64\mingw64\bin\gdb.exe
dir C:\msys64\mingw64\bin\protoc.exe
dir C:\msys64\mingw64\bin\grpc_cpp_plugin.exe
dir C:\msys64\mingw64\share\grpc
```

All five should list files (no *"File Not Found"*). If they do, your
MinGW stack is ready. Check the debugger runs:

```cmd
C:\msys64\mingw64\bin\gdb.exe --version
```

Should print `GNU gdb (GDB) 14.x` or newer — that's the binary Qt
Creator's kit (step 7) will point at for F5 debug.

## ![5] Point the Project at MSYS2

The generated scaffolds include `set_env_msys2.bat` that hardcodes:

```bat
set "MSYS2_ROOT=C:\msys64\mingw64"
set "QT_DIR=%MSYS2_ROOT%"
set "PATH=%MSYS2_ROOT%\bin;%PATH%"
set "MSBASE_ENV_LOADED=msys2"
```

If your MSYS2 install isn't at the default `C:\msys64`, edit
`MSYS2_ROOT` accordingly. Every other build script in the project
sources this file, so one change covers all of them.

## ![6] Build

```cmd
build_deploy_msys2.bat
```

This script:
1. Forces stub regeneration with MSYS2's `protoc` (avoids stale-stub
   ABI mismatches).
2. Configures CMake with Ninja, pointing at the MSYS2 prefix.
3. Builds the service + the console client + (if Qt Widgets selected)
   the GUI client.
4. Runs `windeployqt-qt6` on the GUI exe.
5. Copies all binaries + transitive DLLs into `dist-msys2\`.
6. Emits per-binary `run_<name>.bat` launchers that prepend MSYS2 bin
   to PATH (avoids 0xC0000135 STATUS_DLL_NOT_FOUND silent deaths).

The folder is self-contained — copy it to another Windows machine and
it runs without MSYS2 installed there.

## ![7] Register MSYS2 MinGW64 as a Qt Creator kit

If you use Qt Creator for day-to-day work, register the MSYS2 toolchain
as a kit. You then get one-click build + F5 debug against the same
compiler, Qt, gRPC, and Protobuf that `build_deploy_msys2.bat` uses on
the command line — no switching between two worlds.

Open **Tools → Options…** (Preferences on Linux/macOS) → **Kits**.
Across the top: *Kits | Qt Versions | Compilers | Debuggers | CMake*.
Work through the other four tabs first; the *Kits* tab references
everything else.

### 7a. Compilers tab

Click **Add → MinGW → C** and fill in:

| Field | Value |
|---|---|
| Name | `MinGW-w64 MSYS2 (x86_64) C` |
| Compiler path | `C:\msys64\mingw64\bin\gcc.exe` |
| ABI | leave auto-detect (`x86-windows-msys-pe-64bit`) |

Click **Apply**, then **Add → MinGW → C++**:

| Field | Value |
|---|---|
| Name | `MinGW-w64 MSYS2 (x86_64) C++` |
| Compiler path | `C:\msys64\mingw64\bin\g++.exe` |

### 7b. Debuggers tab

Click **Add**:

| Field | Value |
|---|---|
| Name | `GDB (MSYS2 MinGW64)` |
| Path | `C:\msys64\mingw64\bin\gdb.exe` |
| Type | auto-detected as `GDB` |

### 7c. Qt Versions tab

Click **Add…** and browse to:

```
C:\msys64\mingw64\bin\qmake6.exe
```

Qt Creator runs `qmake6 -query` and auto-fills the fields. Rename it
to `Qt 6 (MSYS2 MinGW64)`. If you see a warning triangle, the Qt
install is incomplete — re-run the `mingw-w64-x86_64-qt6-base` line
from Step 3.

### 7d. CMake tab

| Field | Value |
|---|---|
| Name | `CMake (MSYS2 MinGW64)` |
| Path | `C:\msys64\mingw64\bin\cmake.exe` |
| Version | should auto-detect to 3.25+ |

### 7e. Kits tab — assemble the kit

Click **Add** for a blank kit:

| Field | Value |
|---|---|
| Name | `MSYS2 MinGW 64-bit` |
| Device type | `Desktop` |
| Device | `Local PC (Default)` |
| Compiler — C | `MinGW-w64 MSYS2 (x86_64) C` |
| Compiler — C++ | `MinGW-w64 MSYS2 (x86_64) C++` |
| Debugger | `GDB (MSYS2 MinGW64)` |
| Qt version | `Qt 6 (MSYS2 MinGW64)` |
| CMake Tool | `CMake (MSYS2 MinGW64)` |
| CMake generator | click **Change…** and pick **Ninja** |

### 7f. Environment

Click **Change…** next to *Environment* and add:

```
PATH=C:\msys64\mingw64\bin;${PATH}
MSYSTEM=MINGW64
CHERE_INVOKING=1
```

- `PATH` makes `protoc`, DLLs, and `windeployqt` findable at build and
  run time.
- `MSYSTEM=MINGW64` tells MSYS-aware helpers (`pkg-config`, some `.sh`
  scripts) which subsystem is active.
- `CHERE_INVOKING` keeps MSYS2 bash scripts in the project dir instead
  of `/home/<user>`.

### 7g. CMake Configuration

Click **Change…** next to *CMake Configuration*:

```
CMAKE_PREFIX_PATH:PATH=%{Qt:QT_INSTALL_PREFIX};C:/msys64/mingw64
CMAKE_BUILD_TYPE:STRING=Release
```

The semicolon turns `CMAKE_PREFIX_PATH` into a two-entry CMake list:
Qt's own install first (so `find_package(Qt6)` works), then MSYS2 (so
`find_package(gRPC|Protobuf|absl)` works). Use forward slashes —
CMake prefers them on Windows.

Click the star next to the kit name to make it the default.

### 7h. Verify

Open the project's `CMakeLists.txt`. When prompted for a kit, tick
**MSYS2 MinGW 64-bit** and click **Configure Project**. The General
Messages pane should include:

```
-- The CXX compiler identification is GNU 13.x.x
-- Found Qt6:   ... C:/msys64/mingw64/lib/cmake/Qt6/Qt6Config.cmake
-- Found gRPC: ... C:/msys64/mingw64/lib/cmake/grpc/gRPCConfig.cmake
-- Found Protobuf: ... C:/msys64/mingw64/lib/cmake/protobuf
-- Configuring done
-- Generating done
```

Ctrl+B builds; F5 launches under `gdb.exe` with stdout in the
Application Output pane and working breakpoints.

### Qt Creator kit gotchas

| Symptom | Fix |
|---|---|
| Red triangle on kit: "No Qt version set" | Section *7c* didn't save — re-add `qmake6.exe` and click **Apply**. |
| `find_package(gRPC)` fails inside Qt Creator but works on the command line | `CMAKE_PREFIX_PATH` didn't save, or you deleted the existing `%{Qt:QT_INSTALL_PREFIX}` entry. Re-edit *7g*, keep the semicolon-joined form. |
| Build succeeds but exe silent-dies when you press Run | `PATH` in *7f* wasn't applied. Re-open Environment, confirm the three lines survived a Qt Creator restart. |
| Clang code model squiggles on `<grpcpp/grpcpp.h>` even though builds pass | Edit → Preferences → C++ → Code Model → enable *Add project include paths*, then close + reopen the project. |
| `fatal error: 'bits/c++config.h'` in the Issues pane | Clang code model is pointing at a non-MSYS2 compiler. In the kit, confirm C++ compiler is *MinGW-w64 MSYS2 (x86_64) C++*. |
| `windeployqt` missing when building the GUI target | `pacman -S mingw-w64-x86_64-qt6-tools` — it's separate from `qt6-base`. |

After this, everything `build_deploy_msys2.bat` does on the command
line — compile, link, stub generation via MSYS2 `protoc`, Qt
deployment via `windeployqt` — works inside Qt Creator with one-click
build + F5 debug. Same binaries, same DLLs, no split toolchain.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pacman: command not found` | You opened plain cmd instead of the MSYS2 terminal. Launch **"MSYS2 UCRT64"** from Start Menu. |
| Mirror / SSL errors during Step 3 | Re-run the `pacman -S` command 2–3 times; pacman rotates mirrors. If persistent, temporarily disable VPN or corporate proxy. |
| `signature is unknown trust` / `signature is invalid` | Your MSYS2 install is old and its PGP keyring expired. Fix: `pacman -Sy --needed --noconfirm msys2-keyring && pacman-key --init && pacman-key --populate msys2 && pacman -Scc --noconfirm && pacman -Syu --noconfirm` |
| `HTTP server doesn't seem to support byte ranges` | Partial / corrupted cached package. Delete the cache and retry: `pacman -Scc --noconfirm` |
| `ERROR: g++ not found` when running `build_deploy_msys2.bat` | Check `MSYS2_ROOT` in `set_env_msys2.bat` points at the folder containing `bin\g++.exe`. |
| `MSYS2 package mingw-w64-x86_64-grpc is not installed` | Step 3 was skipped or didn't finish. Re-run it from MSYS2 UCRT64. |
| `PROTOBUF_NAMESPACE_OPEN does not name a type` | Stale stubs from a different toolchain. Fix: `del proto\my_service.pb.* proto\my_service.grpc.pb.* && rmdir /s /q build-msys2 client\build-msys2 && build_deploy_msys2.bat` |
| `my_service_gui.exe` exits silently (no window) | Qt runtime wasn't deployed. Re-run `build_deploy_msys2.bat`; it invokes `windeployqt-qt6.exe` to copy `Qt6*.dll` and `platforms\qwindows.dll` into `dist-msys2\`. |
| Error mentions `vcpkg` even though I'm using MSYS2 | You ran `build_deploy_mingw.bat` (vcpkg-based) or `build_deploy.bat` (MSVC), not `build_deploy_msys2.bat`. Check the exact filename. |

## Uninstall / Reset

If the keyring is hopelessly corrupted and you'd rather start fresh:

```cmd
:: From Windows cmd (NOT inside MSYS2):
rmdir /s /q C:\msys64
:: Then re-download the installer from msys2.org and repeat Step 1.
```

A fresh install ships a current keyring, so Steps 2–3 take maybe
15 minutes and avoid all the "key expired" errors.

### Disk-space tip

`C:\msys64` weighs ~3 GB after Step 3. The cache of downloaded
packages (`/var/cache/pacman/pkg/`) accounts for ~700 MB of that and
can be cleared safely:

```bash
pacman -Scc --noconfirm
```
