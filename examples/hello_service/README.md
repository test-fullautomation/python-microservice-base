# hello_service

> ↑ [Examples index](../README.md) · 📄 [HTML version](README.html) · ⚙️ [C++ equivalent](../cpp_hello_service/README.md)

Minimal Python demo microservice for the MicroserviceBase runtime.
Smallest working scaffold — copy as a starting point for your own
Python service.

Demonstrates:
- Hexagonal layout (`domain/`, `adapters/`, `context.py`, `main.py`)
- `ServiceRunner` with async gRPC server
- Consul registration + gRPC health check
- gRPC reflection (so `grpcurl` and the [Manager GUI](../../MicroserviceBase/MicroserviceManagerGUI/README.md) can enumerate methods)
- Dynamic port allocation (`HELLO_GRPC_PORT=0`)
- Three RPCs: unary (`Greet`), unary (`Echo`), server streaming (`Tick`)

## Layout

```
hello_service/
├── main.py                      # Entry point — asyncio.run(amain())
├── config.py                    # Pydantic Settings (HELLO_* env vars)
├── context.py                   # DI factory — wires domain + adapter
├── pyproject.toml
├── hello.nomad.hcl              # Nomad job spec for raw_exec deployment
│
├── proto/
│   ├── hello.proto              # Service definition
│   ├── hello_pb2.py             # GENERATED — do not edit
│   └── hello_pb2_grpc.py        # GENERATED — do not edit
│
├── domain/
│   └── hello_service.py         # Pure business logic, no gRPC/Consul
│
├── adapters/
│   └── api/
│       └── grpc_adapter.py      # Wires generated stubs to domain object
│
└── scripts/
    └── generate_protos.py       # Regenerate stubs after editing .proto
```

The hexagonal split — `domain/` is pure Python with zero gRPC / Consul
imports; `adapters/api/` is where gRPC enters the building. See
[`../../docs/architecture.md`](../../docs/architecture.md) for the
framework-level rationale.

## Prerequisites

- Python 3.10+
- MicroserviceBase installed (`pip install -e ..` from repo root)
- Consul agent running locally — `consul agent -dev` or via the
  [Manager GUI Service Network tab](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md)

## First run

```bash
cd examples/hello_service

# Generate protobuf Python stubs
python scripts/generate_protos.py

# Start the service
python main.py
```

You should see:

```
INFO MicroserviceBase.runtime.server: gRPC server listening on 0.0.0.0:<port>
INFO MicroserviceBase.runtime.consul: Registering service hello (id=hello-xxxxxxxx) with Consul at <ip>:<port>
INFO MicroserviceBase.runtime.server: Service hello ready.
```

## Run via Nomad (the supervised path)

The folder ships a `hello.nomad.hcl`:

```bash
nomad job run hello.nomad.hcl
```

Or **Submit Job** in the Manager GUI's Nomad tab. See
[`../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md`](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md).

## Verify

Find the service address from Consul:

```bash
curl -s http://localhost:8500/v1/health/service/hello?passing=true | jq '.[0].Service | {Address, Port}'
```

Then:

```bash
# List services exposed by the server (via reflection)
grpcurl -plaintext <addr>:<port> list

# Describe one service
grpcurl -plaintext <addr>:<port> describe hello.v1.HelloService

# Unary call
grpcurl -plaintext -d '{"name": "Cuong"}' <addr>:<port> hello.v1.HelloService/Greet
# -> {"message": "Hello, Cuong!"}

# Server streaming
grpcurl -plaintext -d '{"count": 5, "interval_ms": 500}' <addr>:<port> hello.v1.HelloService/Tick
```

`grpcurl` uses the server's gRPC reflection to discover the schema — no
local `.proto` needed.

### Or invoke via the Manager GUI

1. Launch the GUI (`cd MicroserviceBase/MicroserviceManagerGUI && npm start`)
2. **Service Network → Consul → Start Agent** (Dev Mode)
3. Switch to **Services** mode → click `hello` → invoke methods
   interactively (the panel uses the same gRPC reflection that
   `grpcurl` does)

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `HELLO_GRPC_PORT` | `0` | gRPC port. `0` = OS-assigned (dynamic). |
| `HELLO_SERVICE_HOST` | `0.0.0.0` | Bind address |
| `HELLO_ADVERTISE_ADDR` | (hostname) | Address announced to Consul |
| `HELLO_CONSUL_ADDR` | `http://localhost:8500` | Consul HTTP API endpoint |
| `HELLO_CONSUL_TOKEN` | `` | Optional Consul ACL token |
| `HELLO_GREETING` | `Hello` | Greeting prefix used by `Greet` |
| `HELLO_LOG_LEVEL` | `INFO` | Python logging level |

## Cross-references

- [`../cpp_hello_service/README.md`](../cpp_hello_service/README.md) — C++ equivalent (same `.proto`)
- [`../cpp_hello_client/README.md`](../cpp_hello_client/README.md) — typed C++ client that talks to either equivalent
- [`../../docs/runtime_model.md`](../../docs/runtime_model.md) — what `ServiceRunner` does end-to-end
- [`../../docs/architecture.md`](../../docs/architecture.md) — hexagonal layers + Consul + Nomad + gRPC reflection
- [`../../docs/troubleshooting.md`](../../docs/troubleshooting.md) — symptom-indexed problem fixes
