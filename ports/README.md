# vcpkg overlay-ports

Custom vcpkg ports owned by this repo.  Use them by passing
`--overlay-ports=<this-folder>` to vcpkg, or by setting
`VCPKG_OVERLAY_PORTS=<this-folder>` in your CMake configure.

## Ports

### `microservice-base`

The MicroserviceBase C++ runtime, packaged so generated services can
declare it as a vcpkg dependency:

```json
{
  "dependencies": ["microservice-base"]
}
```

After vcpkg installs it, consumers `find_package(MicroserviceBase CONFIG REQUIRED)`
and link against `microservice_base::runtime`.

The port reads the framework source from the repo (one level up from
this `ports/` folder by default; override with
`VCPKG_MICROSERVICE_BASE_SOURCE` env var pointing at
`<framework>/MicroserviceBase/runtime_cpp`).

See [`docs/runtime_cpp_install.md`](../docs/runtime_cpp_install.md)
for the full install + consume workflow.

## Usage from a generated service

The scaffold-generator emits a `CMakeLists.txt` that prefers
`find_package(MicroserviceBase)`.  To wire vcpkg-based discovery,
the consumer's `vcpkg.json` adds `microservice-base` to its
`dependencies`, and the consumer's CMake configure has access to
this overlay path:

```cmd
cmake -S . -B build ^
    -DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake ^
    -DVCPKG_OVERLAY_PORTS=<path-to-microsoft-base-develop>\ports
```

vcpkg installs `microservice-base` into
`vcpkg_installed/<triplet>/` alongside grpc / protobuf / curl, and the
generated `find_package` call resolves automatically.

## Why an overlay (not upstream vcpkg)?

This is a Bosch-internal package — not meant for the public vcpkg
registry.  Overlay-ports are the standard pattern for private deps:
they share the vcpkg machinery (binary cache, triplet handling,
dependency resolution) without polluting the public registry.

The same overlay pattern is used for our patched `grpc` port at
`examples/PowerDeviceService/ports/grpc/` (gcc 13 ICE workaround +
`gRPC_BUILD_CODEGEN=ON` force).
