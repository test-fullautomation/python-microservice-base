# cpp_hello_client

Standalone C++ client for the `hello` gRPC service.

This project demonstrates the **client-side workflow**: you receive a
`.proto` file from the service team, generate C++ stubs once, and develop
against the generated API using `ServiceClient<T>` for Consul-based
service discovery.

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

This produces four files in `gen/`.  You can commit them to your repo —
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

### 3. Run

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

## Dependencies

| Package | Purpose | Install |
| --- | --- | --- |
| `grpc` | gRPC C++ runtime | `vcpkg install grpc` |
| `protobuf` | Protobuf C++ runtime | pulled by grpc |
| MicroserviceBase runtime | `ServiceClient<T>` + Consul resolver | `add_subdirectory(...)` in CMake |

No `libcurl` needed on the client side — the Consul resolver uses raw sockets.
