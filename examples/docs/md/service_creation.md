# Building a C++ gRPC Microservice — Step-by-Step Guide

> 📄 *Also available as HTML:* [`../html/service_creation.html`](../html/service_creation.html)
>
> Companion docs: [← Docs index](index.md) ·
> [MinGW (MSYS2) setup](mingw_setup.md) ·
> [Qt6::Grpc setup](qt_grpc_setup.md) ·
> [vcpkg + Qt MinGW setup](vcpkg_setup.md) ·
> [WASM service](wasm_cleware_service_guide.md)

This guide walks you through creating a C++ microservice from scratch using
the MicroserviceBase runtime library.  By the end you will have:

- A service that registers itself with Consul and exposes gRPC methods
- A client that discovers the service via Consul and calls it
- Both visible in the MicroserviceManagerGUI

The `hello_service` example in this directory is the reference implementation.

---

## Prerequisites

### 1. Install vcpkg (C++ package manager)

Choose a location for vcpkg (e.g. `~/vcpkg` on Linux/macOS or `C:\vcpkg` on
Windows):

**Windows:**
```cmd
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat
```

**Linux / macOS:**
```bash
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
./bootstrap-vcpkg.sh
```

### 2. Install required C++ packages

**Windows (x64):**
```cmd
vcpkg install grpc:x64-windows protobuf:x64-windows curl:x64-windows
```

**Linux (x64):**
```bash
vcpkg install grpc:x64-linux protobuf:x64-linux curl:x64-linux
```

> **Note:** `grpc` pulls in `protobuf` and `abseil` automatically.  We list
> `protobuf` explicitly for clarity.  `curl` is used by `ConsulRegistration`
> to talk to the Consul HTTP API.

Verify:
```bash
vcpkg list | grep -i grpc
vcpkg list | grep -i curl
```

### 3. Install build tools

#### Windows

| Tool | Purpose | Install |
| --- | --- | --- |
| **CMake 3.16+** | Build system | [cmake.org/download](https://cmake.org/download/) or bundled with Qt |
| **Visual Studio 2019+** | MSVC compiler | [Download](https://visualstudio.microsoft.com/) — "Desktop development with C++" workload |
| **Ninja** (optional) | Faster builds | [github.com/ninja-build/ninja](https://github.com/ninja-build/ninja/releases) or bundled with Qt |

Ensure CMake is on your PATH:
```cmd
cmake --version
```
If not found, add it (example for Qt-bundled CMake):
```cmd
set PATH=C:\Qt\Tools\CMake_64\bin;%PATH%
```

#### Linux

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install -y cmake g++ ninja-build pkg-config

# Fedora / RHEL
sudo dnf install cmake gcc-c++ ninja-build
```

### 4. Install Consul

**Windows:**
```cmd
choco install consul
```
Or download the binary from
[developer.hashicorp.com/consul/install](https://developer.hashicorp.com/consul/install).

**Linux:**
```bash
# Debian / Ubuntu
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install consul

# Or just download the binary:
# https://developer.hashicorp.com/consul/install
```

### 5. Clone the MicroserviceBase repository

```bash
git clone -b ugc1hc/feat/restructure_microservice_base \
    https://github.com/test-fullautomation/python-microservice-base.git
cd python-microservice-base
```

---

## Project Structure

Every C++ microservice follows the same hexagonal layout:

```
my_service/
├── CMakeLists.txt                  # Build configuration
├── proto/
│   └── my_service.proto            # gRPC service definition
├── src/
│   ├── main.cpp                    # Entry point — wires everything together
│   ├── Settings.h                  # Service-specific env var configuration
│   │
│   ├── domain/                     # Pure business logic (no gRPC, no I/O)
│   │   ├── MyService.h
│   │   └── MyService.cpp
│   │
│   └── adapters/
│       └── api/                    # Inbound adapter: gRPC → domain
│           ├── MyGrpcAdapter.h
│           └── MyGrpcAdapter.cpp
│
└── docs/                           # Documentation (this file)
```

**Key principle**: the `domain/` folder has zero dependencies on gRPC, Consul,
or any framework code.  It's pure C++ with standard library only.  The
`adapters/` folder translates between gRPC and the domain.  `main.cpp` wires
them together via the runtime library.

---

## Step 1 — Define the Proto

Create `proto/my_service.proto`:

```protobuf
syntax = "proto3";

package myservice.v1;

service MyService {
  // Unary RPC — simple request-response.
  rpc DoSomething (DoSomethingRequest) returns (DoSomethingResponse);

  // Server-streaming RPC — service pushes multiple responses.
  rpc StreamEvents (StreamRequest) returns (stream Event);
}

message DoSomethingRequest {
  string input = 1;
}

message DoSomethingResponse {
  string output = 1;
}

message StreamRequest {
  int32 count = 1;
}

message Event {
  int32 sequence = 1;
  string data    = 2;
}
```

---

## Step 2 — Implement the Domain

`src/domain/MyService.h`:

```cpp
#pragma once

#include <string>

class MyService {
public:
    std::string doSomething(const std::string& input) const;
};
```

`src/domain/MyService.cpp`:

```cpp
#include "MyService.h"

std::string MyService::doSomething(const std::string& input) const {
    return "Processed: " + input;
}
```

No `#include <grpcpp/grpcpp.h>` anywhere in this folder — that's the rule.

---

## Step 3 — Implement the gRPC Adapter

`src/adapters/api/MyGrpcAdapter.h`:

```cpp
#pragma once

#include <grpcpp/grpcpp.h>
#include "my_service.grpc.pb.h"      // generated from proto
#include "domain/MyService.h"

class MyGrpcAdapter final : public myservice::v1::MyService::Service {
public:
    explicit MyGrpcAdapter(::MyService& domain) : m_domain(domain) {}

    grpc::Status DoSomething(grpc::ServerContext* ctx,
                             const myservice::v1::DoSomethingRequest* req,
                             myservice::v1::DoSomethingResponse* resp) override;

    grpc::Status StreamEvents(grpc::ServerContext* ctx,
                              const myservice::v1::StreamRequest* req,
                              grpc::ServerWriter<myservice::v1::Event>* writer) override;

private:
    ::MyService& m_domain;
};
```

`src/adapters/api/MyGrpcAdapter.cpp`:

```cpp
#include "MyGrpcAdapter.h"
#include <thread>
#include <chrono>

grpc::Status MyGrpcAdapter::DoSomething(
    grpc::ServerContext*,
    const myservice::v1::DoSomethingRequest* req,
    myservice::v1::DoSomethingResponse* resp)
{
    resp->set_output(m_domain.doSomething(req->input()));
    return grpc::Status::OK;
}

grpc::Status MyGrpcAdapter::StreamEvents(
    grpc::ServerContext* ctx,
    const myservice::v1::StreamRequest* req,
    grpc::ServerWriter<myservice::v1::Event>* writer)
{
    for (int i = 0; i < req->count() && !ctx->IsCancelled(); ++i) {
        myservice::v1::Event ev;
        ev.set_sequence(i);
        ev.set_data("event #" + std::to_string(i));
        if (!writer->Write(ev)) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    return grpc::Status::OK;
}
```

---

## Step 4 — Service Settings

`src/Settings.h`:

```cpp
#pragma once

#include "MicroserviceBase/Settings.h"

struct MySettings : public microservice_base::BaseServiceSettings {
    // Add service-specific fields here.
    // They are read from environment variables with the prefix you choose.

    MySettings() {
        service_name = "my_service";
        loadBaseFromEnv("MYSERVICE_");
        // Example: readEnv("MYSERVICE_CUSTOM_OPTION", some_field);
    }
};
```

**Common base settings** (inherited from `BaseServiceSettings`):

| Env Var | Field | Default | Description |
| --- | --- | --- | --- |
| `*_GRPC_PORT` | `grpc_port` | `0` (dynamic) | TCP port for the gRPC server |
| `*_SERVICE_HOST` | `service_host` | `0.0.0.0` | Bind address |
| `*_ADVERTISE_ADDR` | `advertise_addr` | (auto) | Address announced to Consul |
| `*_CONSUL_ADDR` | `consul_addr` | `http://localhost:8500` | Consul HTTP API |
| `*_CONSUL_TOKEN` | `consul_token` | (empty) | Optional ACL token |
| `*_LOG_LEVEL` | `log_level` | `INFO` | Log level |

---

## Step 5 — Entry Point

`src/main.cpp`:

```cpp
#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/MyService.h"
#include "adapters/api/MyGrpcAdapter.h"

int main() {
    try {
        MySettings settings;
        MyService domain;
        MyGrpcAdapter adapter(domain);

        microservice_base::ServiceRunner runner(settings, {"v1"});
        runner.addService(&adapter, "myservice.v1.MyService");
        runner.serveForever();
    } catch (const std::exception& e) {
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
```

**What `ServiceRunner` does automatically:**
1. Starts the gRPC server (dynamic port if `grpc_port=0`)
2. Enables gRPC health check protocol (for Consul)
3. Enables gRPC reflection (for the GUI + `grpcurl`)
4. Registers with Consul (including a health check)
5. Installs signal handlers (`SIGINT`, `SIGTERM`, `SIGBREAK` on Windows)
6. Blocks until shutdown signal
7. Deregisters from Consul
8. Stops the gRPC server gracefully

---

## Step 6 — CMakeLists.txt

```cmake
cmake_minimum_required(VERSION 3.16)
project(my_service VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Dependencies (installed via vcpkg)
find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# MicroserviceBase C++ runtime library
# Adjust the path below if your project is not inside examples/.
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../MicroserviceBase/runtime_cpp"
    "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime"
)

# Generate C++ stubs from proto
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/proto")
set(GEN_DIR   "${CMAKE_CURRENT_BINARY_DIR}/gen")
file(MAKE_DIRECTORY "${GEN_DIR}")

set(MY_PROTO "${PROTO_DIR}/my_service.proto")
set(MY_SRCS
    "${GEN_DIR}/my_service.pb.cc"
    "${GEN_DIR}/my_service.pb.h"
    "${GEN_DIR}/my_service.grpc.pb.cc"
    "${GEN_DIR}/my_service.grpc.pb.h"
)

get_target_property(_protoc   protobuf::protoc       LOCATION)
get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin  LOCATION)

add_custom_command(
    OUTPUT ${MY_SRCS}
    COMMAND ${_protoc}
        --proto_path="${PROTO_DIR}"
        --cpp_out="${GEN_DIR}"
        --grpc_out="${GEN_DIR}"
        --plugin=protoc-gen-grpc="${_grpc_cpp}"
        "${MY_PROTO}"
    DEPENDS "${MY_PROTO}"
    COMMENT "Generating gRPC stubs from my_service.proto"
)

# Service executable
add_executable(my_service
    src/main.cpp
    src/Settings.h
    src/domain/MyService.h
    src/domain/MyService.cpp
    src/adapters/api/MyGrpcAdapter.h
    src/adapters/api/MyGrpcAdapter.cpp
    ${MY_SRCS}
)

target_include_directories(my_service PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${GEN_DIR}"
)

target_link_libraries(my_service PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    gRPC::grpc++_reflection
    protobuf::libprotobuf
)
```

---

## Step 7 — Build

### Windows

```cmd
cd my_service
mkdir build && cd build

cmake -DCMAKE_TOOLCHAIN_FILE=<path-to-vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release
```

Output: `Release\my_service.exe`

### Linux

```bash
cd my_service
mkdir -p build && cd build

cmake \
    -DCMAKE_TOOLCHAIN_FILE=<path-to-vcpkg>/scripts/buildsystems/vcpkg.cmake \
    -DCMAKE_BUILD_TYPE=Release \
    ..
cmake --build . --parallel $(nproc)
```

Output: `./my_service`

> **Tip:** replace `<path-to-vcpkg>` with the absolute path to where you
> cloned vcpkg (e.g. `~/vcpkg` or `C:\vcpkg`).

---

## Step 8 — Run

### Start Consul (dev mode)

```bash
consul agent -dev
```

### Start the service

**Windows:**
```cmd
set MYSERVICE_GRPC_PORT=0
set MYSERVICE_CONSUL_ADDR=http://127.0.0.1:8500
.\Release\my_service.exe
```

**Linux:**
```bash
export MYSERVICE_GRPC_PORT=0
export MYSERVICE_CONSUL_ADDR=http://127.0.0.1:8500
./my_service
```

You should see:
```
[ServiceRunner] gRPC server listening on 0.0.0.0:<port>
[ConsulRegistration] Registering service my_service (id=my_service-xxxxxxxx) at 127.0.0.1:<port>
[ServiceRunner] Service my_service ready.
```

### Verify with grpcurl

```bash
# List services exposed by the server
grpcurl -plaintext 127.0.0.1:<port> list

# Call a method
grpcurl -plaintext -d '{"input": "test"}' \
    127.0.0.1:<port> myservice.v1.MyService/DoSomething
```

### Verify with the GUI

1. Open MicroserviceManagerGUI
2. Click **Connect** → confirm Consul URL → Connect
3. `my_service` appears in the sidebar with a green dot
4. Click it → methods expand → type JSON → Call

---

## Step 9 — Build a Client (Optional)

A C++ client that calls the service:

```cpp
#include <iostream>
#include <grpcpp/grpcpp.h>
#include "my_service.grpc.pb.h"

int main() {
    // 1. Create channel (use Consul lookup or hardcode for testing)
    auto channel = grpc::CreateChannel(
        "127.0.0.1:50051", grpc::InsecureChannelCredentials());
    auto stub = myservice::v1::MyService::NewStub(channel);

    // 2. Build request
    myservice::v1::DoSomethingRequest req;
    req.set_input("hello from client");

    // 3. Call the RPC
    myservice::v1::DoSomethingResponse resp;
    grpc::ClientContext ctx;

    grpc::Status status = stub->DoSomething(&ctx, req, &resp);
    if (status.ok()) {
        std::cout << "Response: " << resp.output() << std::endl;
    } else {
        std::cerr << "Error: " << status.error_message() << std::endl;
    }
    return 0;
}
```

See the separate `examples/cpp_hello_client/` project for a full example with:
- `ServiceClient<T>` from the MicroserviceBase runtime library
- Consul service discovery (auto-resolves `host:port` from service name)
- All three RPC types (unary, echo, server-streaming)
- Standalone `generate_stubs` scripts for one-time proto compilation
- Both direct (`--direct host:port`) and Consul-based (`hello greet Cuong`) modes

---

## Step 10 — Deploy with Nomad (Optional)

Create a `my_service.nomad.hcl` job file:

```hcl
job "my_service" {
  datacenters = ["dc1"]
  type        = "service"

  group "default" {
    count = 1

    network {
      port "grpc" {}
    }

    task "server" {
      driver = "raw_exec"

      config {
        # Use the full path to the built executable.
        command = "/path/to/my_service"     # Linux
        # command = "C:/path/to/my_service.exe"  # Windows
      }

      env {
        MYSERVICE_GRPC_PORT      = "${NOMAD_PORT_grpc}"
        MYSERVICE_ADVERTISE_ADDR = "127.0.0.1"
        MYSERVICE_CONSUL_ADDR    = "http://127.0.0.1:8500"
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
```

Submit from the GUI: **Service Network → Nomad → Submit Job → Load from file → Submit**

Or from the command line:
```bash
nomad job run my_service.nomad.hcl
```

---

## Library Reference

### `microservice_base::ServiceRunner`

```cpp
#include "MicroserviceBase/ServiceRunner.h"

ServiceRunner(const BaseServiceSettings& settings,
              std::vector<std::string> tags = {});

void addService(grpc::Service* service,
                const std::string& full_service_name);

int  start();             // Start gRPC server, return bound port
void serveForever();      // start() + Consul register + block until signal
void requestShutdown();   // Trigger graceful shutdown from any thread
int  boundPort() const;   // Port after start()
```

### `microservice_base::BaseServiceSettings`

```cpp
#include "MicroserviceBase/Settings.h"

struct BaseServiceSettings {
    std::string service_name;
    std::string service_host   = "0.0.0.0";
    int         grpc_port      = 0;
    std::string advertise_addr;
    std::string consul_addr    = "http://localhost:8500";
    std::string consul_token;
    std::string log_level      = "INFO";

    void loadBaseFromEnv(const std::string& prefix);

    static void readEnv(const std::string& key, std::string& out);
    static void readEnv(const std::string& key, int& out);
};
```

### `microservice_base::ConsulRegistration`

```cpp
#include "MicroserviceBase/ConsulRegistration.h"

ConsulRegistration(std::string name, std::string address, int port,
                   std::string consul_addr = "http://localhost:8500",
                   std::vector<std::string> tags = {},
                   std::map<std::string, std::string> meta = {},
                   std::string token = "",
                   std::string health_interval = "10s",
                   std::string health_timeout = "2s",
                   std::string deregister_after = "1m");

bool registerService();      // PUT /v1/agent/service/register
void deregisterService();    // PUT /v1/agent/service/deregister/{id}
```

You normally don't use this directly — `ServiceRunner` handles it.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `cmake: command not found` | Install CMake or add it to PATH |
| `gRPC::grpc++ not found` | Pass `-DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake` |
| `protoc not found` | `vcpkg install protobuf` (with your triplet) |
| `CURL not found` | `vcpkg install curl` (with your triplet) |
| `LNK2019 unresolved external` (Windows) | Check `target_link_libraries` includes all deps |
| `undefined reference` (Linux) | Same — also ensure `-lpthread` if needed |
| Service starts but not in Consul | Check `ADVERTISE_ADDR` is `127.0.0.1` (not `::1`) |
| Health check fails in Consul | Make sure `grpc_port` matches the Consul check target |
| gRPC `UNAVAILABLE` error | Wrong host:port — check Consul or service log for the real port |
| `WSA Error` on client (Windows) | Service isn't listening — verify port with `netstat -ano \| findstr :<port>` |
| `Connection refused` (Linux) | Same — `ss -tlnp \| grep <port>` |
