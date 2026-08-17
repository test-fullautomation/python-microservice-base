# TestService — Console client

Connects to the multi-proto server (one Consul registration for the
whole project, one port for all services).

## Hosted services

- **ComSetupDeviceService** (proto package `Com_Setup_Device`)
- **PowerSupplyService** (proto package `power_device`)

## Build

The client is its own CMake project under `client/`.  Build it
independently of the server:

```cmd
cd client
mkdir build && cd build
cmake -G Ninja ..
cmake --build . --config Release
```

The generated `test_service_client.exe` discovers the server via Consul
(default `http://127.0.0.1:8500`, override with `TEST_SERVICE_CONSUL_ADDR`)
or skip Consul with `--direct HOST:PORT`.

## What the scaffold gives you

For each hosted service it instantiates a ready-to-use gRPC stub:

```cpp
auto svc_a_stub = ::pkg_a::v1::ServiceA::NewStub(channel);
auto svc_b_stub = ::pkg_b::v1::ServiceB::NewStub(channel);
// ... call methods on whichever stub you need
```

The stubs share ONE channel because all services live in one binary
on one port — you don't need separate Consul lookups per service.

## Customising

Edit `src/client.cpp` to build request messages for your real RPC
methods; the comment block at the bottom of `main()` shows the shape.
