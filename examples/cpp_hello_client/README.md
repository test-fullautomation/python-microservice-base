# cpp_hello_client

> ↑ [Examples index](../README.md) · 📄 [HTML version](README.html) · ⚙️ [Server side](../cpp_hello_service/README.md)

Standalone C++ client for the `hello` gRPC service. Demonstrates the
**client-side workflow**: receive a `.proto` from the service team,
generate stubs once, then develop against the generated API using
`ServiceClient<T>` for Consul-based service discovery.

Pair with [`cpp_hello_service/`](../cpp_hello_service/README.md) for an
end-to-end demo.

## Project layout

```
cpp_hello_client/
├── proto/
│   └── hello.proto           # received from the service team
├── gen/                      # generated .h/.cc (after running generate_stubs)
│   ├── hello.pb.h
│   ├── hello.pb.cc
│   ├── hello.grpc.pb.h
│   └── hello.grpc.pb.cc
├── src/
│   └── client.cpp            # client code — uses ServiceClient<T>
├── CMakeLists.txt            # builds against pre-generated stubs
├── generate_stubs.bat        # one-time stub generation (Windows)
├── generate_stubs.sh         # one-time stub generation (Linux)
└── README.md
```

The client owns its own copy of `hello.proto` and the generated stubs.
The server's `.proto` (in [`../cpp_hello_service/proto/`](../cpp_hello_service/proto/))
is the source of truth — when it changes, copy and regenerate.

## Quick start

### 1. Generate stubs (one-time)

**Windows:**
```cmd
cd examples\cpp_hello_client
generate_stubs.bat
```

**Linux:**
```bash
cd examples/cpp_hello_client
chmod +x generate_stubs.sh
./generate_stubs.sh
```

This produces four files in `gen/`. You can commit them to your repo —
after this step, `protoc` is no longer needed.

### 2. Build

**Windows:**
```cmd
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<path-to-vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release
```

**Linux:**
```bash
mkdir -p build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<path-to-vcpkg>/scripts/buildsystems/vcpkg.cmake \
      -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --parallel $(nproc)
```

For toolchain details, see [`../docs/md/vcpkg_setup.md`](../docs/md/vcpkg_setup.md)
(recommended) or [`../docs/md/mingw_setup.md`](../docs/md/mingw_setup.md).

### 3. Run

Make sure the [server](../cpp_hello_service/README.md) is running and
registered in Consul.

```bash
# Consul discovery (service must be registered):
cpp_hello_client hello greet Cuong

# Direct connection (no Consul needed):
cpp_hello_client --direct 127.0.0.1:50051 greet Cuong

# All RPCs at once:
cpp_hello_client hello
```

## How the client code works

```cpp
#include "MicroserviceBase/ServiceClient.h"   // the library
#include "hello.grpc.pb.h"                     // generated from proto

// One line to create a client with Consul discovery:
microservice_base::ServiceClient<HelloService> client("hello");

// Then use the stub normally — standard gRPC API:
auto& stub = client.stub();
grpc::ClientContext ctx;
GreetRequest req;
req.set_name("Cuong");
GreetResponse resp;
stub.Greet(&ctx, req, &resp);
```

`ServiceClient<T>` handles:
- Consul HTTP lookup (`/v1/health/service/{name}?passing=true`)
- gRPC channel creation and caching
- Thread-safe stub access
- `reconnect()` for re-resolution after failures
- `CONSUL_ADDR` env var for Consul URL configuration

For the runtime model behind it (channel pool, descriptor caching,
fallback to `LocalProtoClient` when reflection is unavailable), see
[`../../docs/runtime_model.md`](../../docs/runtime_model.md).

## Compared to dynamic invocation (Manager GUI)

| Approach | Generated stubs (this client) | Dynamic via reflection (the GUI) |
|---|---|---|
| Compile-time type safety | ✅ | ❌ — JSON dict |
| Performance | Native protobuf serialization | Slightly slower (reflection round-trip on first call) |
| Setup | Generate stubs once, link | None — works against any reflection-enabled server |
| Best for | Production code, perf-sensitive paths | Test scripting, ops, exploring an unknown service |

Both end up at the same gRPC call. Use whichever fits the situation.

## Dependencies

| Package | Purpose | Install |
| --- | --- | --- |
| `grpc` | gRPC C++ runtime | `vcpkg install grpc` |
| `protobuf` | Protobuf C++ runtime | pulled by grpc |
| MicroserviceBase runtime | `ServiceClient<T>` + Consul resolver | `add_subdirectory(...)` in CMake |

No `libcurl` needed on the client side — the Consul resolver uses raw
sockets.

## Cross-references

- [`../cpp_hello_service/README.md`](../cpp_hello_service/README.md) — the matching server
- [`../../docs/runtime_model.md`](../../docs/runtime_model.md) — `ServiceClient` discovery + invocation flow
- [`../../docs/architecture.md`](../../docs/architecture.md) — where `ServiceClient` fits in the layers
- [`../docs/md/vcpkg_setup.md`](../docs/md/vcpkg_setup.md) — vcpkg + Qt MinGW toolchain (recommended)
- [`../docs/md/mingw_setup.md`](../docs/md/mingw_setup.md) — MSYS2 alternative
- [`../../docs/troubleshooting.md`](../../docs/troubleshooting.md) — symptom-indexed problem fixes
