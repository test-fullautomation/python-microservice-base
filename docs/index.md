# MicroserviceBase

Framework-level reference: how MicroserviceBase is structured, what each
piece does, and how the runtime fits together.

MicroserviceBase is a hexagonal microservice framework. Services expose
**gRPC** with server reflection, register themselves in **Consul** for
discovery, and are launched and supervised by **Nomad**. A Manager GUI
(Electron + FastAPI bridge) drives all of it, and a scaffold generator
produces new services in Python or C++/Qt.

!!! info "Recently migrated"
    The framework moved off RabbitMQ. gRPC + Consul + Nomad replaced the
    broker, service registry and process hub respectively. The AMQP
    adapters still exist and still work, but they are superseded — see
    [ADR-028](adr/028-grpc-reflection-primary-rpc.md) for the rationale
    and the [Changelog](reference/changelog.md) for what changed.

## Where to start

**Get oriented**

| You want to… | Read |
|---|---|
| Get the 5-minute pitch | [Repo README](https://github.com/test-fullautomation/python-microservice-base/blob/develop/README.md) |
| Understand the architecture (layers, runtime, transport) | [Architecture overview](architecture/overview.md) |
| Understand how a single service runs end-to-end | [Runtime model](architecture/runtime-model.md) |
| See it rather than read it | [Diagrams](architecture/diagrams.md) |
| Look up a term you don't know | [Concepts glossary](architecture/concepts.md) |

**Operate**

| You want to… | Read |
|---|---|
| Learn the Manager GUI | [Manager GUI overview](gui/index.md) |
| Run Consul + Nomad without two terminals | [Operating Consul + Nomad](gui/ops_consul_nomad.md) |
| Diagnose a problem | [Troubleshooting](reference/troubleshooting.md) |

**Develop**

| You want to… | Read |
|---|---|
| Generate a new service | [Service Creator wizard](gui/service_creator.md) |
| Generate Robot Framework keywords from `.proto` | [Robot resource generator](gui/robot_generator.md) |
| Walk through building a service by hand | [Creating a service](examples/service_creation.md) |
| Set up a C++ toolchain | [Examples and toolchain](examples/index.md) |
| Install the C++ runtime as a CMake / vcpkg package | [C++ runtime install](guides/runtime-cpp-install.md) |

**Reference**

| You want to… | Read |
|---|---|
| See what changed in the migration | [Changelog](reference/changelog.md) |
| Find the rationale for a design choice | [Architecture Decision Records](adr/README.md) |

## What's in this site

| Section | Contents |
|---|---|
| [Architecture](architecture/overview.md) | Hexagonal layers (domain / ports / adapters), Consul discovery, Nomad orchestration, gRPC reflection, the FastAPI bridge — where each piece lives and why |
| [Runtime model](architecture/runtime-model.md) | `ServiceRunner` lifecycle (boot → register → serve → graceful shutdown), `ServiceClient` discovery, channel pooling, dynamic invocation via reflection |
| [Diagrams](architecture/diagrams.md) | Every `.puml` in the repo, rendered — architecture, class structure, runtime sequences, GUI internals, Qt templates |
| [Concepts](architecture/concepts.md) | Glossary: bridge, runtime, port, adapter, scaffold, hub (legacy) |
| [Manager GUI](gui/index.md) | The Electron + web GUI: service creation, Consul/Nomad operation, Robot generation |
| [Examples and toolchain](examples/index.md) | MinGW, vcpkg, Qt + gRPC setup; building a service end to end; the WASM Cleware walkthrough |
| [Architecture decisions](adr/README.md) | One record per significant choice, dated and marked Active / Superseded / Archived |
| [Changelog](reference/changelog.md) | Migration history — RabbitMQ → gRPC, ServiceRegistry → Consul, ProcessHub → Nomad, Manager GUI rewrite |
| [Troubleshooting](reference/troubleshooting.md) | Symptoms keyed to the current architecture: gRPC errors, Consul/Nomad agents, GUI bridge connectivity, vcpkg/MinGW builds |

## Reading paths

**New contributor** — [Architecture overview](architecture/overview.md) →
[Runtime model](architecture/runtime-model.md) →
[Diagrams](architecture/diagrams.md), then walk a real example
([`cpp_hello_service`](https://github.com/test-fullautomation/python-microservice-base/tree/develop/examples/cpp_hello_service))
with the Manager GUI open in another window.

**Migrating a downstream fork** — [Changelog](reference/changelog.md)
first, then read [Concepts](architecture/concepts.md) against the
pre-migration
[`_legacy/CONCEPT.md`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/docs/_legacy/CONCEPT.md)
side by side to map old terms onto new.

**Operator who just needs to run things** —
[Manager GUI overview](gui/index.md) →
[Operating Consul + Nomad](gui/ops_consul_nomad.md). The GUI-driven path
replaces the CLI operations entirely.

---

!!! note "Building these docs"
    ```
    python -m properdocs build --clean     # render to site/
    python -m properdocs serve             # live preview on :8000
    python tools/verify_diagrams.py site   # decode SVGs, catch render errors
    ```
    PlantUML renders through the vendored `tools/plantuml.jar`, so no
    `plantuml.com` round-trip is needed. The Manager GUI and examples
    pages are copied in at build time from their canonical locations by
    `docs_hooks/copy_external_docs.py`.
