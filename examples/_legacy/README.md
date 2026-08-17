# Legacy examples — kept for reference only

> **⚠️ These examples target the old runtime architecture and are no
> longer supported.**  They use **RabbitMQ** for service-to-service
> communication and the **Local Process Hub** for lifecycle management
> — both replaced in the current framework by **gRPC + Consul**
> (service discovery) and **Nomad** (orchestration).
>
> They live here so that:
> - Git history is preserved without polluting the main `examples/` tree.
> - Migration questions can be answered by diff-ing an old example
>   against its modern counterpart.
> - Anyone maintaining a downstream fork that still uses the old
>   transport has a working reference to copy from.

## Don't start new work here

For new services, see the modern examples one level up:

| New code path | Use this example |
|---|---|
| Single C++ gRPC service | [`../cpp_hello_service/`](../cpp_hello_service) |
| Matching console + Qt client | [`../cpp_hello_client/`](../cpp_hello_client) |
| Single Python gRPC service | [`../hello_service/`](../hello_service) |
| Multi-service C++ monorepo | [`../PowerDeviceService/`](../PowerDeviceService) |

For the framework guide, start at the [docs index](../docs/md/index.md).

## What's here and why it's here

### Standalone Python tutorials (RabbitMQ-era)

| File | What it taught |
|---|---|
| `01_basic_service.py` | Minimal service publishing to a RabbitMQ topic |
| `02_service_client.py` | RPC-over-RabbitMQ client pattern |
| `03_service_registry.py` | Original in-memory `ServiceRegistry` (replaced by Consul) |
| `04_eventbus_transport.py` | Direct `eventbus`/RabbitMQ transport adapter |
| `05_alias_routing.py` | `alias.json`-based routing keys (deprecated) |
| `06_fastapi_bridge.py` | First-cut bridge over RabbitMQ (replaced by gRPC bridge) |
| `07_mock_fleet_api.py` | Mock for the now-defunct Fleet WebAPI tab |
| `08_fleet_demo.py` | Full demo wiring of the above |

### C++ service templates (RabbitMQ-era)

| Folder | Replacement |
|---|---|
| `cpp_qml_service_template/` | Use `cpp_hello_service/` + a Qt6::Grpc client (see [`docs/md/qt_grpc_setup.md`](../docs/md/qt_grpc_setup.md)) |
| `cpp_wasm_cleware_service/` | No modern WASM example yet — see comment below |
| `cpp_widget_service_template/` | Use `cpp_hello_service/` + the auto-generated widget client from `mb-scaffold` |
| `qt_wasm_service_template/` | No modern WASM example yet — see comment below |
| `service_template/` | Use `mb-scaffold` (the [Service Creator wizard](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md)) |
| `fleet_demo/` | Use `nomad job run` against a generated `.nomad.hcl` (see [`PowerDeviceService/README.md`](../PowerDeviceService/README.md)) |
| `TestService/` | Test scratch from the early gRPC migration; superseded by `cpp_hello_service/` |

### About WASM

The `*_wasm_*` folders pre-date the gRPC migration.  A modern WASM
example (Qt for WebAssembly + gRPC + Consul) hasn't been written yet —
when one lands the legacy WASM folders + the matching
`docs/.../wasm_cleware_service_guide` will be retired.
