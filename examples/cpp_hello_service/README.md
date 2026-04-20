# cpp_hello_service

C++ port of `examples/hello_service/`.  Demonstrates the new
MicroserviceBase C++ runtime (`runtime_cpp/`):

- Hexagonal layout (`domain/`, `adapters/`, `Settings.h`, `main.cpp`)
- `microservice_base::ServiceRunner` with graceful shutdown
- Consul registration via libcurl (`ConsulRegistration`)
- gRPC reflection enabled by the runtime automatically
- Dynamic port allocation (`HELLO_GRPC_PORT=0`)

## Layout

```
cpp_hello_service/
├── CMakeLists.txt
├── proto/
│   └── hello.proto                         # Shared with Python sample
├── src/
│   ├── main.cpp                            # Entry point
│   ├── Settings.h                          # HELLO_* env vars
│   ├── domain/
│   │   ├── HelloService.h                  # Pure logic — no gRPC, no I/O
│   │   └── HelloService.cpp
│   └── adapters/
│       └── api/
│           ├── HelloGrpcAdapter.h          # Wires gRPC to HelloService
│           └── HelloGrpcAdapter.cpp
└── README.md
```

## Prerequisites

- CMake 3.16+
- gRPC + protobuf + libcurl installed via vcpkg:
  ```bash
  vcpkg install grpc protobuf curl
  ```
- MicroserviceBase C++ runtime (built automatically via `add_subdirectory`)
- Consul agent running locally (`consul agent -dev`)

## Build

```bash
cd examples/cpp_hello_service
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release
```

## Run

```bash
# Optional: configure via env vars
set HELLO_GRPC_PORT=50052
set HELLO_GREETING=Bonjour

./hello_service
```

Then verify with `grpcurl` exactly like the Python sample:

```bash
curl -s http://localhost:8500/v1/health/service/hello?passing=true | jq

grpcurl -plaintext -d '{"name": "Cuong"}' <addr>:<port> hello.v1.HelloService/Greet
# -> {"message": "Bonjour, Cuong!"}
```

## Environment variables

Same as the Python sample (`HELLO_*`) — see `../hello_service/README.md`.
