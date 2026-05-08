# Examples

> 📄 *Also available as HTML:* [`README.html`](README.html)

Worked examples of MicroserviceBase services and clients on the
current gRPC + Consul + Nomad runtime. Each folder is a complete
project — clone it as a starting point or run it as-is.

For toolchain setup (MSYS2 / Qt6::Grpc / vcpkg + Qt MinGW), per-feature
walkthroughs, and the Service Creator wizard, see
[`docs/`](docs/README.md).

## Pick an example

| Situation | Go to |
|---|---|
| 🚀 I want to build my **first service** in C++ | [`cpp_hello_service/`](cpp_hello_service/README.md) — single service, ~150 lines, hexagonal layout, all the wiring you need to copy |
| 🐍 Same but in **Python** | [`hello_service/`](hello_service/README.md) — async gRPC + ServiceRunner, three RPC flavours (unary, server-streaming) |
| 🛰 I want a **client** that talks to a service | [`cpp_hello_client/`](cpp_hello_client/README.md) — typed C++ client with generated stubs + `ServiceClient<T>` for Consul lookup |
| 🏭 I want to see a **multi-service** real-world project | [`PowerDeviceService/`](PowerDeviceService/README.md) — 6 services in one C++ monorepo with vcpkg toolchain, Qt client, prebuilt zip workflow — **canonical reference** |
| 📚 I want to learn the toolchain choices | [`docs/`](docs/README.md) — MSYS2 / Qt6::Grpc / vcpkg + Qt MinGW setup guides |
| 🪄 I want the GUI to scaffold one for me | [Service Creator wizard](../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md) — same generator backend as the `mb-scaffold` CLI |

## What's the difference between these examples?

| | Lang | Server | Client | Toolchain | Best for |
|---|---|---|---|---|---|
| `cpp_hello_service/` | C++ | ✅ | (paired with cpp_hello_client) | vcpkg or MSYS2 | First C++ service from scratch |
| `cpp_hello_client/` | C++ | – | ✅ console | vcpkg or MSYS2 | Learning the client-side flow + generated stubs |
| `hello_service/` | Python | ✅ | – | pip | First Python service from scratch |
| `PowerDeviceService/` | C++ | ✅ × 6 | ✅ Qt-Widget + qt_client_grpcpp | vcpkg + Qt MinGW (canonical) | Real-world multi-service architecture |

`cpp_hello_service` + `cpp_hello_client` work as a pair — start the
service, then the client connects via Consul lookup.

## Layout

```
examples/
├── README.md / README.html              ← you are here
├── docs/                                ← toolchain setup + per-feature walkthroughs
│   ├── md/  index | mingw_setup | qt_grpc_setup | vcpkg_setup | service_creation | wasm_cleware
│   └── html/ (mirror)
├── PowerDeviceService/                  ← canonical multi-service C++ monorepo
├── cpp_hello_service/                   ← single C++ service
├── cpp_hello_client/                    ← matching console client
├── hello_service/                       ← single Python service
└── _legacy/                             ← pre-gRPC-migration examples (RabbitMQ-era)
                                          kept for reference / fork maintainers
```

## Running any example: the common loop

The shape of the workflow is the same across all examples:

1. **Start Consul + Nomad** — either `consul agent -dev` and
   `nomad agent -dev` in two terminals, or use the
   [Manager GUI's Service Network tab](../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md)
   to launch both with one click each.
2. **Build the service** — `build_deploy_msys2.bat` (or
   `build_qt_vcpkg.bat`) for C++ scaffolds; `pip install -e .` for
   Python.
3. **Deploy** — `nomad job run deploy/<svc>.nomad.hcl` (or click
   **Submit Job** in the Manager GUI's Nomad tab).
4. **Inspect** — open the Manager GUI → Services tab → click the
   service. gRPC reflection enumerates methods automatically;
   click **Send** on a method to invoke it interactively.

For the per-example specifics (env vars, build flags, deploy variants),
see each folder's README.

## Cross-references

- [Repo docs](../docs/index.md) — framework architecture, runtime
  model, glossary, changelog
- [Manager GUI guides](../MicroserviceBase/MicroserviceManagerGUI/docs/md/index.md)
  — operate Consul + Nomad, drive the Service Creator wizard, invoke
  services
- [Toolchain setup](docs/md/index.md) — MSYS2, Qt6::Grpc, vcpkg + Qt MinGW
- [Troubleshooting](../docs/troubleshooting.md) — symptom-indexed
  problems for current-stack issues

## Pre-migration examples

`_legacy/` holds the RabbitMQ + ServiceRegistry + ProcessHub examples
(`01_basic_service.py` through `08_fleet_demo.py`,
`cpp_qml_service_template/`, `fleet_demo/`, `service_template/`, etc.).
They demonstrate framework features that have since been replaced —
useful for fork maintainers who haven't migrated yet, or for
diff-comparing an old example against its modern counterpart.
See [`_legacy/README.md`](_legacy/README.md) for a per-folder mapping
to current replacements.
