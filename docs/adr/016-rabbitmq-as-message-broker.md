# ADR-016: RabbitMQ as Message Broker

> **⚠ Superseded** — 2026-05-07.  Pre-migration decision; no longer
> applies to the gRPC + Consul + Nomad architecture.  See the existing
> Status note below for the immediate successor, and
> [`docs/changelog.md`](../changelog.md) +
> [`docs/adr/AUDIT.md`](AUDIT.md) for the full triage.  Kept here for
> git archaeology.

## Status

**Superseded** — replaced by direct gRPC over HTTP/2 with Consul-based service discovery. See [`docs/changelog.md`](../changelog.md) for the migration rationale and [`docs/architecture.md`](../architecture.md) for the current shape. RabbitMQ + the broker-coupled `ServiceRegistry` are gone; service-to-service traffic is now point-to-point.

## Date

2026-02-12

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-12 | 1.0 | Initial version |

## Context

MicroserviceBase needs a message broker for inter-service communication
supporting three distinct messaging patterns:

1. **RPC (request-response)** — synchronous calls where a client sends a
   request and blocks for a response (e.g. GUI calls `svc_api_add(1, 2)`)
2. **Event broadcasting** — one-to-many updates when services register or
   unregister (e.g. registry pushes updated service list to all GUIs)
3. **Topic-based routing** — publish to a topic exchange where consumers bind
   with routing key patterns (e.g. `service.information` for registration events)

The broker must also support:
- Per-service queues with routing-key-based dispatch
- Correlation-based RPC (match response to request)
- Exclusive temporary queues (auto-deleted callback queues)
- Durable queues for the registry (survive broker restarts)
- Lightweight enough for desktop/lab deployment (single node)

## Decision

Use **RabbitMQ** with AMQP 0-9-1 protocol as the message broker, accessed via
the **pika** Python client library.

### Exchange Architecture

Three exchange types serve the three messaging patterns:

```
┌─────────────────────────────────────────────────────────────┐
│                        RabbitMQ Broker                       │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  services_request (direct)                            │    │
│  │  ├─ routing_key="service.calculator" → Calculator Q  │    │
│  │  ├─ routing_key="service.registry"   → Registry Q    │    │
│  │  └─ routing_key="service.cleware"    → Cleware Q     │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  service_information (topic)                          │    │
│  │  └─ routing_key="service.information" → registry Q   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  registry_update_<uuid> (fanout)                      │    │
│  │  ├─ → GUI client 1 (exclusive queue)                  │    │
│  │  ├─ → GUI client 2 (exclusive queue)                  │    │
│  │  └─ → GUI client N (exclusive queue)                  │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

| Exchange | Type | Purpose | Routing Key |
|----------|------|---------|-------------|
| `services_request` | direct | RPC calls to services | Service's `routing_key` (e.g. `service.calculator`) |
| `service_information` | topic | Registration/unregistration events | `service.information` |
| `registry_update_<uuid>` | fanout | Real-time service list broadcasts | (none — fanout to all) |

### RPC Pattern

```
Client                          Broker                       Service
  │                               │                             │
  │  publish(exchange=services_request,                         │
  │    routing_key=service.calculator,                          │
  │    reply_to=amq.gen-abc,                                    │
  │    correlation_id=uuid-123,                                 │
  │    body={"method":"svc_api_add","args":[1,2]})              │
  │ ──────────────────────────────> │ ──────────────────────────>│
  │                               │                             │
  │                               │    publish(exchange='',     │
  │                               │      routing_key=amq.gen-abc,
  │                               │      correlation_id=uuid-123,
  │                               │      body={"result":"pass", │
  │                               │        "result_data":"3"})  │
  │ <────────────────────────────── │ <──────────────────────────│
  │                               │                             │
  │  (match by correlation_id)    │                             │
```

- Client creates exclusive callback queue (auto-generated name, auto-delete)
- `reply_to` property tells the service where to send the response
- `correlation_id` (UUID) matches response to request
- Default timeout: 30 seconds via `process_data_events(time_limit=...)`

### Transport Independence

The domain layer never imports pika. The `TransportPort` interface abstracts
all broker operations:

```python
class TransportPort(ABC):
    def connect(self): ...
    def disconnect(self): ...
    def consume(self, callback, exchange, routing_key): ...
    def stop_consuming(self): ...
    def rpc_call(self, request_data, exchange, routing_key, timeout=30): ...
    def publish(self, body, exchange, routing_key): ...
```

`RabbitMQTransportAdapter` implements this interface. Swapping brokers means
writing a new adapter — no domain code changes.

## Comparison with Alternatives

| Feature | RabbitMQ | Apache Kafka | NATS | ZeroMQ | gRPC |
|---------|----------|-------------|------|--------|------|
| **RPC (request-response)** | Native (`reply_to` + `correlation_id`) | Not native (need request-reply pattern on top) | Native (request-reply) | Manual (dealer-router) | Native (unary RPC) |
| **Fan-out broadcasts** | Fanout exchange | Consumer groups (all partitions) | Pub/sub subjects | Pub-sub pattern | Server streaming |
| **Topic routing** | Topic exchange with patterns | Topic partitions | Subject hierarchy | Topic filter (manual) | N/A |
| **Per-service queues** | Declare per-service queue, bind to exchange | Partition-per-consumer | Queue groups | N/A (manual) | N/A |
| **Message persistence** | Per-message (delivery_mode=2) | Log-based (always persistent) | JetStream (opt-in) | No broker (P2P) | No broker |
| **Exclusive temp queues** | Native (auto-delete, exclusive) | Not available | Not available | N/A | N/A |
| **Single-node deployment** | Yes (single binary) | Requires ZooKeeper/KRaft | Yes (single binary) | No broker needed | No broker needed |
| **Management UI** | Built-in (port 15672) | Separate tools (Kafka UI) | Separate (nats-top) | N/A | N/A |
| **Python client** | pika (mature, blocking/async) | confluent-kafka | nats-py | pyzmq | grpcio |
| **Protocol** | AMQP 0-9-1 | Custom binary | Custom text/binary | Custom binary | HTTP/2 + protobuf |

### Apache Kafka (Rejected)

Distributed event streaming platform optimized for high-throughput log
processing.

Rejected because:
- **No native RPC** — Kafka is designed for event streams, not request-response.
  Implementing RPC requires a request topic + response topic + correlation ID
  matching + consumer group management. RabbitMQ provides this natively.
- **Overkill for desktop/lab** — Kafka requires ZooKeeper or KRaft for
  metadata management, even for a single node. Our deployment is a single
  developer machine.
- **No exclusive temporary queues** — Kafka has persistent topic partitions.
  Our RPC pattern needs auto-deleted callback queues per request.
- **No fine-grained routing** — Kafka routes by topic + partition, not by
  routing key patterns. We need direct routing to specific services.

### NATS (Deferred)

Lightweight messaging system with request-reply support.

Deferred because:
- **Native request-reply** — NATS supports the RPC pattern natively, which is
  a good fit.
- **Lightweight** — single binary, no external dependencies.
- However: **smaller ecosystem in enterprise Python** — pika/RabbitMQ has
  stronger adoption in our organization's existing infrastructure.
- **JetStream for persistence** — adds complexity comparable to RabbitMQ.
- Worth re-evaluating if RabbitMQ becomes a deployment bottleneck.

### ZeroMQ (Rejected)

Brokerless messaging library with socket patterns.

Rejected because:
- **No broker** — ZeroMQ is a library, not a service. Each service must know
  the addresses of other services directly (or via a custom broker).
- **No built-in persistence** — messages are lost if a consumer is offline.
- **No management UI** — no way to inspect queues, exchanges, or message rates.
- **Manual routing** — topic filtering and RPC correlation must be implemented
  from scratch.
- Note: ZeroMQ IS used internally by ProcessHub for local inter-process
  communication (ZmqTransport), where brokerless P2P is appropriate.

### gRPC (Rejected)

HTTP/2-based RPC framework with Protocol Buffers.

Rejected because:
- **Point-to-point only** — gRPC connects client to server directly. No broker
  means no fan-out broadcasts, no topic-based routing, no message queuing.
- **Schema-first** — requires `.proto` files and code generation. Our
  `svc_api_*` convention discovers methods at runtime via reflection (ADR-017).
- **No pub/sub** — server streaming exists but is not equivalent to a fanout
  exchange where multiple independent subscribers receive the same event.
- **Tight coupling** — client must know the server's address and port. RabbitMQ
  decouples producers from consumers via exchanges and queues.

## Consequences

### Positive

- Three exchange types map cleanly to three messaging patterns (RPC, events, broadcasts)
- Native RPC support via `reply_to` + `correlation_id` — no custom protocol needed
- Single-node deployment for desktop/lab; can scale to clustered deployment if needed
- Built-in management UI for debugging and monitoring
- Mature Python client (pika) with blocking and async modes
- Transport port abstraction allows swapping brokers without domain changes

### Negative

- External infrastructure dependency — RabbitMQ server must be running
- AMQP protocol adds latency compared to direct TCP (acceptable for our use case)
- pika's `start_consuming()` blocks indefinitely on Windows — required workaround
  with `process_data_events(time_limit=1)` loop (ADR-013)

### Neutral

- RabbitMQ is widely deployed in enterprise environments, reducing adoption friction
- Docker-based setup (`docker run rabbitmq:management`) provides instant development environment

## References

- Source: `MicroserviceBase/adapters/transport/rabbitmq_adapter.py`
- Source: `MicroserviceBase/adapters/registry/amqp_registry_adapter.py`
- Source: `MicroserviceBase/ports/transport.py`
- Related: ADR-001 (Hexagonal Architecture), ADR-003 (Custom Service Registry)
