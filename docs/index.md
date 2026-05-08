# MicroserviceBase repo docs

> 📄 *Also available as HTML:* [`index.html`](index.html)

Framework-level reference: how MicroserviceBase is structured, what each
piece does, and how the runtime fits together. For toolchain setup or
per-example walkthroughs, see [`../examples/docs/`](../examples/docs/).
For the Manager GUI specifically, see [`../MicroserviceBase/MicroserviceManagerGUI/`](../MicroserviceBase/MicroserviceManagerGUI/).

## Where to start

| You want to… | Read |
|---|---|
| Get the 5-minute pitch | [Repo `README.md`](../README.md) |
| Understand the architecture (layers, runtime, transport) | [`architecture.md`](architecture.md) |
| Understand how a single service runs end-to-end | [`runtime_model.md`](runtime_model.md) |
| Look up a term you don't know | [`concepts.md`](concepts.md) |
| See what changed in the recent migration | [`changelog.md`](changelog.md) |
| Diagnose a problem | [`troubleshooting.md`](troubleshooting.md) |
| Find the rationale for a design choice | [`adr/`](adr/) — Architecture Decision Records |
| Read the Manager GUI guides | [`../MicroserviceBase/MicroserviceManagerGUI/docs/md/index.md`](../MicroserviceBase/MicroserviceManagerGUI/docs/md/index.md) |
| Set up a toolchain (MSYS2, Qt6::Grpc, vcpkg+QtMinGW) | [`../examples/docs/md/index.md`](../examples/docs/md/index.md) |
| Walk through generating a service | [`../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md`](../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md) |
| Run Consul + Nomad without two terminals | [`../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md`](../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md) |

## Repo-level docs in this folder

| File | What |
|---|---|
| [`architecture.md`](architecture.md) | Hexagonal layers (domain/ports/adapters), Consul service discovery, Nomad orchestration, gRPC reflection, the FastAPI bridge — where each piece lives and why |
| [`runtime_model.md`](runtime_model.md) | `ServiceRunner` lifecycle (boot → register → serve → graceful shutdown), `ServiceClient` discovery flow, channel pooling, dynamic invocation via reflection |
| [`concepts.md`](concepts.md) | Glossary of terms: bridge, hub (legacy), runtime, port, adapter, scaffold, etc. Modernised from `_legacy/CONCEPT.md` |
| [`changelog.md`](changelog.md) | Migration history — RabbitMQ → gRPC, ServiceRegistry → Consul, ProcessHub → Nomad, prebuilt vcpkg, Manager GUI rewrite |
| [`troubleshooting.md`](troubleshooting.md) | Cross-cutting symptoms keyed to current architecture (gRPC errors, Consul/Nomad agent issues, GUI bridge connectivity, vcpkg/MinGW build problems) |
| [`runtime_cpp_install.md`](runtime_cpp_install.md) | How to install the C++ runtime as a CMake / vcpkg package so generated services can `find_package(MicroserviceBase)` from outside this repo |
| [`adr/`](adr/) | Architecture Decision Records — one file per significant choice, dated, marked Active / Superseded / Deprecated |
| [`diagrams/`](diagrams/) | `.drawio` source + rendered PNGs of the architecture diagrams referenced from `architecture.md` |
| [`imgs/`](imgs/) | Other screenshots / illustrations |
| [`plans/`](plans/) | Forward-looking plans (under audit; some pre-date the migration) |
| [`_legacy/`](_legacy/) | Pre-migration `CONCEPT.md` and `troubleshooting-guide.md` — kept for reference |

## Reading paths

**For a new contributor**: `README.md` (root) → `architecture.md` →
`runtime_model.md` → walk an example (`examples/PowerDeviceService/README.md`)
while the Manager GUI runs in another window.

**For someone migrating a downstream fork**: `changelog.md` first,
then `_legacy/CONCEPT.md` ↔ `concepts.md` side-by-side to map old
terms onto new.

**For an operator who just needs to run things**:
`MicroserviceManagerGUI/README.md` → `ops_consul_nomad.md` (the
GUI-driven path replaces all CLI ops).
