# Runtime model


What actually happens inside one service from `main()` to handling
the first RPC, and what `ServiceClient` does when invoking. For the
big picture (where Consul, Nomad, and the bridge sit) see
[`architecture.md`](overview.md).

## Server-side: ServiceRunner

`ServiceRunner` is the boot helper every generated service uses. C++
version lives in `MicroserviceBase/runtime_cpp/include/MicroserviceBase/ServiceRunner.h`,
Python version in `MicroserviceBase/runtime/service_runner.py` —
identical lifecycle.

### Lifecycle

```
main()
  │
  ├─ 1. Parse env + settings
  │     - <PREFIX>_GRPC_PORT  (Nomad sets via ${NOMAD_PORT_grpc})
  │     - CONSUL_ADDR         (default http://127.0.0.1:8500)
  │     - LOG_LEVEL, etc.
  │
  ├─ 2. Build the gRPC server
  │     - grpc::ServerBuilder
  │     - .AddListeningPort(0.0.0.0:<port>, InsecureServerCredentials())
  │     - Register concrete service implementations:
  │         AnalogInputServiceGrpcAdapter(domain),  RelayServiceGrpcAdapter(domain), …
  │     - InitProtoReflectionServerBuilderPlugin()       ← enables runtime introspection
  │
  ├─ 3. Start serving
  │     - server->Start()  (non-blocking)
  │
  ├─ 4. Register in Consul
  │     - PUT /v1/agent/service/register
  │       { Name: "analog_input_service", Address: <host>, Port: <port>,
  │         Tags: ["v1"], Meta: { grpc_services: "device.AnalogInputService,…" },
  │         Check: { TCP: "<host>:<port>", Interval: "5s" } }
  │
  ├─ 5. Install signal handlers
  │     - SIGINT  / Ctrl+C        → mark stopping
  │     - SIGTERM / SIGBREAK      → mark stopping
  │     - (Windows: SIGBREAK is delivered when Nomad sends CTRL_BREAK_EVENT)
  │
  ├─ 6. Wait for shutdown
  │     - server->Wait()   blocks until server->Shutdown() called
  │
  └─ 7. Graceful shutdown
        - DELETE /v1/agent/service/deregister/<name>      ← Consul tells callers we're gone
        - server->Shutdown(deadline)                       ← in-flight RPCs finish or 5s grace
        - return 0
```

### Key choices

- **One process per service**, even in a monorepo (PowerDeviceService
  has 6 binaries, one per service). Easier port allocation, easier
  to tune resources per Nomad job, simpler failure isolation.
- **Insecure (TCP) gRPC** locally; a TLS adapter exists for prod.
- **Dynamic port** allocated by Nomad — services don't fight over
  hardcoded ports, the same `.hcl` template scales to N replicas.
- **Reflection always on** — generated servers always link
  `grpc++_reflection` so `ServiceClient` and the GUI can introspect
  without `.proto` files.
- **Consul deregistration on clean shutdown** — Nomad's `kill_signal`
  is `SIGINT` for raw_exec; `Wait()` returns and the deregister fires
  before the process exits. Crashes leave the registration to be
  reaped by Consul's failed-health-check eviction (~30s default).

## Client-side: ServiceClient

`ServiceClient` (Python: `MicroserviceBase/runtime/service_client.py`,
C++: same name in `runtime_cpp/`) is the typical client-side helper.

### Discovery + invoke flow

```
client.invoke("analog_input_service", "ReadAnalogInput", {channel: 0})
  │
  ├─ 1. Resolve via Consul
  │     - GET /v1/health/service/analog_input_service?passing=true
  │     - Returns [{Service: {Address, Port}, Checks: [...]}]
  │     - Pick a healthy one (first, or load-balance if multiple)
  │
  ├─ 2. Open / reuse a gRPC channel
  │     - grpc::CreateChannel("<addr>:<port>", InsecureChannelCredentials())
  │     - Cached in a per-target dict; cheap to reuse
  │
  ├─ 3. Resolve method via reflection (first call to this service only)
  │     - ServerReflectionInfo({list_services})        → enumerate services
  │     - ServerReflectionInfo({file_containing_symbol: "device.AnalogInputService"})
  │       → fetches the FileDescriptorProto, builds local DescriptorPool
  │     - Cache the descriptor pool keyed by service-name
  │
  ├─ 4. Build the request message dynamically
  │     - GetMessageClass(method.input_type) returns a runtime type
  │     - Parse({"channel": 0}, request_msg) populates fields
  │
  ├─ 5. Invoke via grpc.Channel.unary_unary
  │     - path = "/device.AnalogInputService/ReadAnalogInput"
  │     - serializer = request_class.SerializeToString
  │     - deserializer = response_class.FromString
  │
  └─ 6. Convert response to dict + return
        - MessageToDict(response, preserving_proto_field_name=True)
```

### Why dynamic invocation?

Generated `.proto` stubs would be faster (no reflection round-trip,
no DescriptorPool building). But:

- The Manager GUI doesn't know what services exist at build time, so
  it has to use reflection anyway.
- For test scripts and one-off scripting, "give me a method by name
  and I'll JSON-marshal the args" is the right ergonomics.
- For service-to-service calls in production code, generated stubs
  are still encouraged (and we provide the `.proto` files in each
  scaffold's `proto/` folder for that purpose).

So `ServiceClient` is the convenience layer; `grpc.aio.Channel` +
generated stubs is the perf-sensitive path.

## End-to-end: GUI invoking a service method

```
User clicks "Send" in Manager GUI
  │
  ▼
GUI: POST /api/grpc/call
  { consul_name: "analog_input_service",
    grpc_service: "device.AnalogInputService",
    method: "ReadAnalogInput",
    args_json: '{"channel": 0}' }
  │
  ▼
Bridge: _open_grpc_client(target)
  ├─ try: GrpcReflectClient(target).list_services()
  │       └─ gRPC reflection RPC to <host>:<port>
  │
  └─ on UNIMPLEMENTED:
        LocalProtoClient.from_search_paths(target, MB_PROTO_SEARCH_PATH + GUI override)
        └─ shells out to grpc_tools.protoc to compile .protos
  │
  ▼
client.call_method("device.AnalogInputService", "ReadAnalogInput", '{"channel": 0}')
  ├─ build dynamic request (GetMessageClass + Parse)
  ├─ unary_unary on the channel
  └─ MessageToDict(response)
  │
  ▼
Bridge response: {ok: true, result: {value: 4.2}, discovery_source: "reflection"}
  │
  ▼
GUI renders the JSON in the response panel
```

The whole cycle is typically ~5–20 ms locally. The reflection RPC is
done once per channel and the descriptor pool is cached, so
subsequent calls only do steps 4–6.

## Concurrency model

- **Server**: gRPC's default `ServerBuilder` thread-pool model.
  Domain methods are called concurrently — keep them stateless or
  protect shared state.
- **Client**: `grpc.Channel` is thread-safe. `ServiceClient` is not —
  one instance per request thread.
- **Bridge**: FastAPI's default uvicorn workers (single-process,
  async I/O). Subprocess management for Consul/Nomad agents uses a
  background thread per agent for stdout/stderr drain (see
  `_drain_pipe` in `fastapi_bridge.py`).

## Logging

- Services log to stdout/stderr; Nomad captures into per-alloc files
  visible via `nomad alloc logs <id>` or the Nomad UI Logs tab
- The bridge writes structured logs to its own stdout
- The Manager GUI's bridge LED reflects the bridge's `/health`
  endpoint, polled every few seconds

For production, point Nomad at a log shipper (Loki / ELK / file
rotation in the `.hcl` `logs` block).

## Failure modes (and what handles them)

| Failure | Detected by | Handled by |
|---|---|---|
| Service crashes | Nomad's process supervisor | Restart according to `restart` stanza in the .hcl |
| Service hangs | Consul TCP health check | Marked failing; clients skip it via `?passing=true` |
| Network partition between client and server | gRPC RPC fails with `UNAVAILABLE` | Caller decides — retry, fail, fallback |
| Consul agent down | Bridge's `/api/consul/health` | GUI infra pill goes red; clients can't resolve |
| Nomad agent down | Bridge's `/api/nomad/health` | GUI infra pill goes red; existing jobs keep running (Nomad's allocation supervisor is per-client-node) |
| Reflection unavailable | Bridge's `_open_grpc_client` catches `UNIMPLEMENTED` | Falls back to `LocalProtoClient` (compiles `.proto` from disk) |
| Bridge crashes | GUI's bridge LED → red | User clicks ▶ to restart (Electron mode); browser-mode user re-launches |

## See also

- [`architecture.md`](overview.md) — overall layering
- [`concepts.md`](concepts.md) — terminology
- [`troubleshooting.md`](../reference/troubleshooting.md) — symptom-keyed problems + fixes
- `MicroserviceBase/adapters/grpc_bridge/reflect_client.py` — `GrpcReflectClient` + `LocalProtoClient` source
- `MicroserviceBase/runtime_cpp/include/MicroserviceBase/ServiceRunner.h` — the canonical lifecycle
