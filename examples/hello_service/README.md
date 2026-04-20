# hello_service

Minimal demo microservice for the new MicroserviceBase runtime.

Demonstrates:
- Hexagonal layout (`domain/`, `adapters/`, `context.py`, `main.py`)
- `ServiceRunner` with async gRPC server
- Consul registration + gRPC health check
- gRPC reflection (so `grpcurl` and the GUI can enumerate methods)
- Dynamic port allocation (`HELLO_GRPC_PORT=0`)
- Three RPCs: unary (`Greet`), unary (`Echo`), server streaming (`Tick`)

## Layout

```
hello_service/
├── main.py                      # Entry point — asyncio.run(amain())
├── config.py                    # Pydantic Settings (HELLO_* env vars)
├── context.py                   # DI factory — wires domain + adapter
├── pyproject.toml
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
    └── generate_protos.py       # Regenerate protos after editing .proto
```

## Prerequisites

- Python 3.10+
- MicroserviceBase installed (`pip install -e ..` from repo root)
- Consul agent running locally (`consul agent -dev`)

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

## Verify with grpcurl

Find the service address from Consul:

```bash
curl -s http://localhost:8500/v1/health/service/hello?passing=true | jq '.[0].Service | {Address, Port}'
```

Then call the service directly:

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
