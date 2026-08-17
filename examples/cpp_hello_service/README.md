# cpp_hello_service

> ↑ [Examples index](../README.md) · 📄 [HTML version](README.html) · 🐍 [Python equivalent](../hello_service/README.md)

A minimal C++ gRPC service for the MicroserviceBase runtime. Smallest
working scaffold — copy as a starting point for your own service.

Demonstrates:
- Hexagonal layout (`domain/`, `adapters/`, `Settings.h`, `main.cpp`)
- `microservice_base::ServiceRunner` with graceful shutdown
- Consul registration via libcurl (`ConsulRegistration`)
- gRPC reflection enabled by the runtime automatically (so `grpcurl` and the [Manager GUI](../../MicroserviceBase/MicroserviceManagerGUI/README.md) can enumerate methods at runtime)
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

The hexagonal split — `domain/` is pure C++ with zero gRPC / Consul
dependencies; `adapters/api/` is where gRPC enters the building. See
[`../../docs/architecture.md`](../../docs/architecture.md) for the
framework-level rationale.

## Prerequisites

- CMake 3.16+
- gRPC + protobuf + libcurl — pick a toolchain:
  - **MSYS2**: `pacman -S mingw-w64-x86_64-grpc mingw-w64-x86_64-protobuf mingw-w64-x86_64-curl` (see [`../docs/md/mingw_setup.md`](../docs/md/mingw_setup.md))
  - **vcpkg + Qt MinGW**: `vcpkg install grpc protobuf curl` (see [`../docs/md/vcpkg_setup.md`](../docs/md/vcpkg_setup.md) — recommended for new teams)
- MicroserviceBase C++ runtime (built automatically via `add_subdirectory`)
- Consul agent running locally — start with `consul agent -dev` or the [Manager GUI Service Network tab](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md)

## Build

```bash
cd examples/cpp_hello_service
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release
```

For MSYS2 / MinGW workflows, drop the `-DCMAKE_TOOLCHAIN_FILE=...` and
make sure your shell has the MSYS2 mingw64 binaries on `%PATH%`.

## Run

### Direct invocation (smoke test)

```bash
# Optional: configure via env vars
set HELLO_GRPC_PORT=50052
set HELLO_GREETING=Bonjour

./hello_service.exe
```

You should see:

```
[ServiceRunner] gRPC server listening on 0.0.0.0:50052
[ConsulRegistration] Registered service hello (id=hello-xxxxxxxx) at <ip>:50052
[ServiceRunner] Service hello ready.  Press Ctrl+C to stop.
```

### Run via Nomad (the supervised path)

A bare-bones `.hcl` example (adapt paths to your build output):

```hcl
job "hello_service" {
    datacenters = ["dc1"]
    type        = "service"
    group "hello_service" {
        network { port "grpc" {} }
        task "server" {
            driver = "raw_exec"
            config { command = "C:/path/to/cpp_hello_service/build/Release/hello_service.exe" }
            env {
                CONSUL_ADDR        = "http://127.0.0.1:8500"
                HELLO_GRPC_PORT    = "${NOMAD_PORT_grpc}"
            }
        }
    }
}
```

```bash
nomad job run hello.nomad.hcl
```

(For a real-world `.nomad.hcl` template, run `mb-scaffold` and look at
the generated `deploy/<svc>.nomad.hcl`.)

### Run + invoke via the Manager GUI

1. Launch the GUI (`cd MicroserviceBase/MicroserviceManagerGUI && npm start`)
2. **Service Network → Consul → Start Agent** (Dev Mode)
3. **Service Network → Nomad → Submit Job → pick `hello.nomad.hcl`**
4. Switch to **Services** mode → click `hello_service` → invoke `Greet` with `{"name": "Cuong"}`

See [`../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md`](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md)
for the full GUI walkthrough.

## Verify with `grpcurl`

Find the service address from Consul:

```bash
curl -s http://localhost:8500/v1/health/service/hello?passing=true | jq '.[0].Service | {Address, Port}'
```

Then invoke:

```bash
grpcurl -plaintext -d '{"name": "Cuong"}' <addr>:<port> hello.v1.HelloService/Greet
# -> {"message": "Bonjour, Cuong!"}
```

`grpcurl` uses the server's gRPC reflection to discover the schema — no
local `.proto` needed.

## Environment variables

| Var | Default | Description |
|-----|---------|-------------|
| `HELLO_GRPC_PORT` | `0` (random) | gRPC bind port |
| `HELLO_GREETING` | `Hello` | Prefix used by `Greet` |
| `CONSUL_ADDR` | `http://127.0.0.1:8500` | Consul agent HTTP API |

## Cross-references

- [`../hello_service/README.md`](../hello_service/README.md) — Python equivalent (same `.proto`, same protocol)
- [`../cpp_hello_client/README.md`](../cpp_hello_client/README.md) — companion C++ client
- [`../../docs/runtime_model.md`](../../docs/runtime_model.md) — what `ServiceRunner` actually does
- [`../../docs/architecture.md`](../../docs/architecture.md) — hexagonal layers + Consul + Nomad + gRPC reflection
- [`../docs/md/mingw_setup.md`](../docs/md/mingw_setup.md) — MSYS2 toolchain setup
- [`../docs/md/vcpkg_setup.md`](../docs/md/vcpkg_setup.md) — vcpkg + Qt MinGW toolchain setup
- [`../../docs/troubleshooting.md`](../../docs/troubleshooting.md) — symptom-indexed problem fixes
