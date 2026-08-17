# Installing the C++ runtime


How to make `MicroserviceBase`'s C++ runtime available to a generated
service that lives **outside** this framework repo. After install,
consumer `CMakeLists.txt` does:

```cmake
find_package(MicroserviceBase CONFIG REQUIRED)
target_link_libraries(my_service PRIVATE microservice_base::runtime)
```

…just like any other CMake-packaged library (gRPC, Protobuf, etc.).

## Three install paths

Pick the one that matches your team's existing setup:

| Path | When to use | Setup |
|---|---|---|
| **A. CMake install** | You don't use vcpkg; or one team / one machine | Build + `cmake --install` to a prefix; consumers add prefix to `CMAKE_PREFIX_PATH` |
| **B. vcpkg overlay-port** | You already use vcpkg (recommended for the Qt+vcpkg toolchain) | Add `microservice-base` to your `vcpkg.json`; pass the overlay path |
| **C. In-tree (legacy)** | You're working inside this framework repo (e.g. on `examples/`) | The generated `CMakeLists.txt` falls back to `add_subdirectory()` automatically |

The generator emits this hybrid pattern:

```cmake
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_in_tree "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/runtime_cpp")
    if(EXISTS "${_mb_in_tree}/CMakeLists.txt")
        add_subdirectory("${_mb_in_tree}" "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime")
    else()
        message(FATAL_ERROR "MicroserviceBase runtime not found ...")
    endif()
endif()
```

So all three paths above work with the same generated service.

---

## Path A — CMake install

### Build + install the runtime

One-time per machine (or per CI agent):

```bash
# Configure
cmake -S MicroserviceBase/runtime_cpp -B build/runtime_cpp \
      -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake \
      -DVCPKG_TARGET_TRIPLET=x64-mingw-qt \
      -DCMAKE_INSTALL_PREFIX=$HOME/.local/microservice-base

# Build + install
cmake --build build/runtime_cpp
cmake --install build/runtime_cpp
```

The toolchain file ensures `find_package(gRPC)` etc. resolve via
vcpkg. If you're not using vcpkg, drop the `-DCMAKE_TOOLCHAIN_FILE`
and rely on system gRPC + Protobuf + libcurl.

Installed tree:

```
$HOME/.local/microservice-base/
├── include/MicroserviceBase/
│   ├── ConsulRegistration.h
│   ├── ServiceClient.h
│   ├── ServiceRunner.h
│   └── Settings.h
└── lib/
    ├── libmicroservice_base_runtime.a
    └── cmake/MicroserviceBase/
        ├── MicroserviceBaseConfig.cmake          ← what find_package() loads
        ├── MicroserviceBaseConfigVersion.cmake
        ├── MicroserviceBaseTargets.cmake
        └── MicroserviceBaseTargets-noconfig.cmake
```

### Consume from a generated service

```bash
cd my-generated-service
cmake -S . -B build \
      -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake \
      -DCMAKE_PREFIX_PATH=$HOME/.local/microservice-base
cmake --build build
```

`CMAKE_PREFIX_PATH` tells CMake where to look for the
`MicroserviceBaseConfig.cmake` file. The generated `CMakeLists.txt`'s
`find_package(MicroserviceBase CONFIG REQUIRED)` finds it; `gRPC` /
`Protobuf` / `CURL` come from vcpkg as before.

### Where to put the prefix

| Linux / macOS | Windows |
|---|---|
| `~/.local/microservice-base` (per-user) | `%LOCALAPPDATA%\microservice-base` |
| `/opt/microservice-base` (system-wide) | `C:\Program Files\microservice-base` (admin install) |

A shared CI / dev environment can host the prefix on a network drive
and have every machine point `CMAKE_PREFIX_PATH` at it.

---

## Path B — vcpkg overlay-port (recommended for vcpkg-using teams)

The framework ships an overlay-port at [`ports/microservice-base/`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/ports/README.md).

### Wire it into your project's `vcpkg.json`

```json
{
  "name": "my-generated-service",
  "version": "1.0.0",
  "dependencies": [
    "microservice-base",
    { "name": "grpc", "default-features": false, "features": ["codegen"] },
    "protobuf",
    "curl"
  ]
}
```

### Pass the overlay path on configure

```bash
cmake -S . -B build \
      -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake \
      -DVCPKG_OVERLAY_PORTS=<framework-repo>/ports
```

Or set it persistently:

```bash
export VCPKG_OVERLAY_PORTS=<framework-repo>/ports
```

vcpkg installs `microservice-base` into `vcpkg_installed/<triplet>/`
alongside grpc, protobuf, curl. The generated `find_package` call
resolves through the same vcpkg toolchain that resolves the others.

### How the overlay-port finds the framework source

`portfile.cmake` reads from one of:

1. `VCPKG_MICROSERVICE_BASE_SOURCE` env var if set
2. Otherwise: `<overlay-path>/../MicroserviceBase/runtime_cpp` (assumes
   the overlay is part of the framework repo checkout)

For CI or dev machines that don't have the framework cloned, point
the env var at a tarball-extracted snapshot:

```bash
export VCPKG_MICROSERVICE_BASE_SOURCE=/opt/microservice-base-snapshot/runtime_cpp
```

---

## Path C — In-tree (no install)

The generator's CMakeLists falls back to `add_subdirectory()` when
`find_package(MicroserviceBase)` fails. This works automatically when
the generated service lives at `<framework>/examples/<svc>/` (the
relative path `../../MicroserviceBase/runtime_cpp` resolves).

No setup needed — it's the default for examples shipped with the
framework. Generated services that **leave** the repo lose this
fallback (the relative path no longer resolves) and must use Path A
or B.

---

## Verification

After install + configure, sanity-check with a one-line consumer:

```cmake
# /tmp/check-mb/CMakeLists.txt
cmake_minimum_required(VERSION 3.16)
project(check_mb LANGUAGES CXX)
find_package(MicroserviceBase CONFIG REQUIRED)
add_executable(check_mb main.cpp)
target_link_libraries(check_mb PRIVATE microservice_base::runtime)
```

```cpp
// /tmp/check-mb/main.cpp
#include <MicroserviceBase/ServiceRunner.h>
#include <iostream>
int main() {
    std::cout << "MicroserviceBase runtime found + linkable.\n";
    return 0;
}
```

```bash
cmake -S /tmp/check-mb -B /tmp/check-mb/build \
      -DCMAKE_PREFIX_PATH=$HOME/.local/microservice-base
cmake --build /tmp/check-mb/build
/tmp/check-mb/build/check_mb
```

Should print "MicroserviceBase runtime found + linkable."

## Troubleshooting

### `Could not find a package configuration file provided by "MicroserviceBase"`

`CMAKE_PREFIX_PATH` doesn't include the install prefix, OR the
overlay-port wasn't passed on the vcpkg configure. Check:

```bash
echo $CMAKE_PREFIX_PATH    # Path A
echo $VCPKG_OVERLAY_PORTS  # Path B
```

### `microservice_base::runtime target was not found` (after `find_package` succeeded)

Probably an old install with the legacy target name. The current
package exports three target names:

| Modern (preferred) | Direct vcpkg-style | Legacy (back-compat) |
|---|---|---|
| `microservice_base::runtime` | `microservice_base::microservice_base_runtime` | `microservice_base_runtime` |

Re-install from the current source tree to get all three.

### Transitive deps (gRPC / Protobuf / CURL) not found

`MicroserviceBaseConfig.cmake` calls `find_dependency(gRPC CONFIG)` etc.
For these to resolve, the consumer's `CMAKE_PREFIX_PATH` (or the vcpkg
toolchain) must also include the gRPC install. Easiest: use the same
vcpkg setup for both.

## See also

- [`../ports/README.md`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/ports/README.md) — overlay-port details
- [`architecture.md`](../architecture/overview.md) — where the C++ runtime fits in the stack
- [`runtime_model.md`](../architecture/runtime-model.md) — what `ServiceRunner` actually does
- [`changelog.md`](../reference/changelog.md) — when this packaging landed
