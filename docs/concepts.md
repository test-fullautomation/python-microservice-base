# Concepts & glossary

> 📄 *Also available as HTML:* [`concepts.html`](concepts.html)

Quick lookup for terms that show up across the docs and the codebase.
For the architectural shape see [`architecture.md`](architecture.md);
for the runtime lifecycle see [`runtime_model.md`](runtime_model.md).

This file replaces [`_legacy/CONCEPT.md`](_legacy/CONCEPT.md), which
described the older RabbitMQ-era runtime — kept for fork maintainers.

## A → Z

### Adapter

The outer layer of the hexagonal architecture. Concrete
implementations of the abstract ports — e.g. the gRPC adapter
implements the transport port, the Consul adapter implements the
service-registry port. Lives in `adapters/` directories. Free to
import third-party libraries (grpc, consul, fastapi, qt, etc.).

### Bridge (FastAPI bridge)

The Python process at `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py`.
Single HTTP front-end at `http://127.0.0.1:1112` that the Manager GUI
talks to. Wraps the scaffold generator, gRPC reflection client,
Consul/Nomad agent management, and Consul/Nomad HTTP API
pass-through. **Not** a message bus — the name "bridge" predates the
gRPC migration when it bridged the Electron GUI to RabbitMQ.

### Channel (gRPC)

A long-lived TCP connection to a gRPC server, multiplexed via HTTP/2.
`ServiceClient` caches one channel per resolved target so repeat
calls don't pay the connect cost.

### Consul

HashiCorp's service-discovery + health-check daemon. We use it as
the canonical "where is service X right now" lookup. Generated
services register on startup, deregister on clean shutdown. Local
dev runs `consul agent -dev`; the Manager GUI Service Network tab
launches it for you.

### Descriptor pool

Protobuf's runtime registry of message + service definitions. The
gRPC reflection client builds one by ingesting `FileDescriptorProto`
bytes returned by the server's reflection RPCs. Lets us serialize /
deserialize messages without compile-time-generated stubs.

### Domain

The innermost layer — pure business logic, zero infrastructure
imports. Plain functions and value types. Unit-testable by
construction. Lives in `domain/` directories (framework-level: `MicroserviceBase/domain/`;
service-level: `<service>/src/<svc>/domain/`).

### gRPC reflection

The standard `grpc.reflection.v1alpha.ServerReflection` service.
Lets a client ask the server "what services + methods do you offer
and what do their messages look like" at runtime. Our generated
servers always link `grpc++_reflection` and call
`InitProtoReflectionServerBuilderPlugin()` so this works.

### Hexagonal architecture

Domain in the centre, surrounded by ports (interfaces), surrounded
by adapters (concrete implementations). The point: domain depends on
nothing outside itself, infra adapts to domain via ports. Swapping
RabbitMQ for gRPC was an adapter change, not a domain change.

### Local Process Hub *(legacy)*

The pre-Nomad service supervisor. Spawned services as subprocesses
of the Manager GUI's Electron host. Replaced by Nomad. Code is
gone; the term may still appear in old ADRs and `_legacy/CONCEPT.md`.

### Manager GUI

The Bootstrap-based desktop / browser app at
`MicroserviceBase/MicroserviceManagerGUI/`. Three modes: **Services**
(browse + invoke registered services), **Service Network** (start /
stop Consul + Nomad), **Service Creator** (the scaffold wizard).
See [`MicroserviceManagerGUI/README.md`](../MicroserviceBase/MicroserviceManagerGUI/README.md).

### `mb-scaffold`

Friendly nickname for `python -m MicroserviceBase.tools.scaffold_cli`
— the CLI front-end to the scaffold generator. Same backend as the
Manager GUI's Service Creator wizard.

### Method (gRPC)

An RPC entry point on a gRPC service. Four flavours: **unary-unary**
(default — single request, single response), **server-streaming**,
**client-streaming**, **bidi**. Our reflection client supports
unary + server-streaming; client + bidi need a different UI pattern
and are intentionally rejected.

### Nomad

HashiCorp's workload orchestrator. We use it to launch + supervise
services as `raw_exec` jobs (Windows + Linux native processes, no
container required). Each generated service ships a
`deploy/<service>.nomad.hcl`. Submit with `nomad job run` or via the
Manager GUI Nomad tab.

### Overlay-port (vcpkg)

A local copy of an upstream vcpkg port that takes precedence when
vcpkg looks up the package. We ship one for `grpc` at
`<project>/ports/grpc/` so we can apply the gcc 13 ICE patch and
force `gRPC_BUILD_CODEGEN=ON`. See [`changelog.md`](changelog.md) for
why.

### Port (hexagonal)

An interface / protocol definition in the hexagonal layering. Lives
in `ports/`. No implementations, just typing. Implemented by adapters,
consumed by domain. **Different from a TCP port.**

### Port (TCP)

The numeric address on which a gRPC server listens. Allocated by
Nomad (dynamic, exported as `${NOMAD_PORT_grpc}`) — services don't
hardcode them.

### `raw_exec` (Nomad driver)

Runs the task command directly as a child process — no container, no
chroot, no namespace isolation. Cross-platform (Windows + Linux),
which is why we default to it. Production deployments can swap to
`exec` / `docker` without touching the framework.

### `ServiceClient`

The convenience helper for outbound calls. Resolves via Consul,
opens a channel, uses reflection to discover methods, dynamically
builds + sends + parses messages. See
[`runtime_model.md`](runtime_model.md). Source:
`MicroserviceBase/runtime/service_client.py` (Python),
`MicroserviceBase/runtime_cpp/include/MicroserviceBase/ClientRegistry.h` (C++).

### Service Registry *(legacy)*

The pre-Consul in-process registry. Service started → published a
"hello" message on a RabbitMQ exchange → registry stored it →
clients asked the registry. Replaced by Consul (which does the same
thing, much better). Code is gone; term may still appear in ADRs
and the legacy CONCEPT.

### `ServiceRunner`

The boot helper every generated service uses. Builds the gRPC
server, registers in Consul, installs signal handlers, blocks until
shutdown, deregisters on exit. See
[`runtime_model.md`](runtime_model.md). Source:
`MicroserviceBase/runtime/service_runner.py` (Python),
`MicroserviceBase/runtime_cpp/include/MicroserviceBase/ServiceRunner.h` (C++).

### Triplet (vcpkg)

A vcpkg build configuration: target architecture + ABI + linkage
choices. We ship a custom `x64-mingw-qt` triplet that pins the
compiler to Qt installer's MinGW 13.1.0 so generated services share
ABI with Qt clients.

## Term migration table (for fork maintainers)

| Pre-migration | Current |
|---|---|
| RabbitMQ broker | gRPC channels (point-to-point, no broker) |
| Service Registry | Consul service catalog |
| Routing key | (n/a — gRPC uses fully-qualified service + method names) |
| Alias routing | (dropped — gRPC method names are explicit, no aliasing layer) |
| Local Process Hub | Nomad agent + per-service `.hcl` |
| Fleet / hub node | Nomad client node |
| Hub config (`hub_processes.json`) | Nomad job HCL files |
| `service_information` exchange | Consul services API (`/v1/health/service/...`) |
| Multi-broker chips | Multi-Consul-cluster chips |
| Service publishes status to broker | Service registers in Consul + TCP health check |
| `eventbus` transport adapter | (dropped) |

The architectural ideas that **didn't** change:

- Hexagonal layering (domain / ports / adapters)
- Convention-over-configuration (auto-discovery of `svc_api_*` methods)
- Zero-dependency domain
- Constructor injection
- Service-delivered GUI plugins (still loaded from `web/services/<ServiceName>/`)
- Dual-host GUI (Electron + browser)

## See also

- [`architecture.md`](architecture.md) — what the pieces are and how they connect
- [`runtime_model.md`](runtime_model.md) — how a service runs and how a client invokes
- [`changelog.md`](changelog.md) — when each change happened and why
- [`_legacy/CONCEPT.md`](_legacy/CONCEPT.md) — pre-migration concept doc
