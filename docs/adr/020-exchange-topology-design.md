# ADR-020: Exchange Topology Design

## Status

Superseded — gRPC has no exchanges. Service-to-service is point-to-point over HTTP/2; service discovery is via Consul; method discovery is via gRPC reflection. The exchange-topology decision is no longer load-bearing.

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

With RabbitMQ chosen as message broker (ADR-016), the system needs a concrete
exchange and queue topology to support three distinct messaging patterns:

1. **RPC (request-response)** — a client sends a method call to a specific
   service and waits for a result
2. **Service registration events** — services announce their arrival or
   departure and the registry records the change
3. **Real-time broadcasts** — the registry pushes the full service list to all
   connected GUI clients after each change

The question is: how many exchanges, of which types, with what naming and
binding conventions?

### Constraints

- Each service must have its own queue (no shared queues between services)
- RPC responses must be correlated back to the correct caller
- Registration events must survive brief broker restarts (durability)
- GUI clients must all receive every broadcast (no competing consumers)
- The topology must be simple enough for a single-node desktop deployment

## Decision

Use **three separate exchanges**, one per messaging pattern, each with the
AMQP exchange type that best matches the pattern's routing semantics.

### Exchange Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                        RabbitMQ Broker                           │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  services_request (DIRECT)                                │    │
│  │                                                            │    │
│  │  routing_key="service.calculator" ──> [Calculator]        │    │
│  │  routing_key="ServiceRegistry"    ──> [ServiceRegistry]   │    │
│  │  routing_key="service.cleware"    ──> [ServiceCleware]    │    │
│  │                                                            │    │
│  │  Temporary exclusive queues (amq.gen-*) for RPC replies   │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  service_information (TOPIC)                              │    │
│  │                                                            │    │
│  │  routing_key="service.information"                        │    │
│  │    ──> [service_infor_queue] (durable)                    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  services_update (FANOUT)                                 │    │
│  │                                                            │    │
│  │  ──> [amq.gen-abc] (GUI client 1, exclusive)              │    │
│  │  ──> [amq.gen-def] (GUI client 2, exclusive)              │    │
│  │  ──> [amq.gen-ghi] (FastAPI bridge, exclusive)            │    │
│  └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Exchange 1: `services_request` (Direct)

**Purpose:** Route RPC method calls to the correct service.

```python
# rabbitmq_adapter.py — service consume setup
channel.exchange_declare(exchange='services_request', exchange_type='direct')
channel.queue_declare(queue=service_name)          # e.g. "Calculator"
channel.queue_purge(queue=service_name)            # clear stale messages
channel.queue_bind(
    exchange='services_request',
    queue=service_name,
    routing_key=routing_key,                       # e.g. "service.calculator"
)
channel.basic_qos(prefetch_count=1)                # one request at a time
```

| Property | Value |
|----------|-------|
| **Exchange name** | `services_request` |
| **Exchange type** | `direct` |
| **Queue names** | Service name (e.g. `Calculator`, `ServiceRegistry`) |
| **Routing keys** | Service-specific (e.g. `service.calculator`, `ServiceRegistry`) |
| **Queue lifecycle** | Exists while service is running; purged on startup |
| **Prefetch count** | 1 (serial request processing) |

**Why direct?** Each RPC call targets exactly one service. Direct exchange
routes by exact routing key match — no wildcards, no fanout, no overhead.
Topic exchange could work but adds unnecessary pattern matching. Fanout would
deliver to all services (wrong semantics).

#### RPC Reply Pattern

```python
# rabbitmq_adapter.py — rpc_call()
result = channel.queue_declare(queue='', exclusive=True)  # temp queue
callback_queue = result.method.queue                       # amq.gen-xxx

channel.basic_publish(
    exchange='services_request',
    routing_key=target_routing_key,
    properties=pika.BasicProperties(
        reply_to=callback_queue,
        correlation_id=str(uuid.uuid4()),
    ),
    body=json.dumps(request_data),
)
```

The caller creates an **exclusive temporary queue** (auto-deleted when the
connection closes) and sets `reply_to` so the service knows where to send the
response. The `correlation_id` matches the response to the request when
multiple RPC calls share a callback queue.

The service publishes the response to the **default exchange** (`''`) with
`routing_key=reply_to`, which routes directly to the callback queue by name.

### Exchange 2: `service_information` (Topic)

**Purpose:** Deliver service registration and unregistration events to the
Service Registry.

```python
# amqp_registry_adapter.py — publish_event()
channel.exchange_declare(exchange='service_information', exchange_type='topic')
channel.queue_declare(queue='service_infor_queue', durable=True)
channel.queue_bind(
    exchange='service_information',
    queue='service_infor_queue',
    routing_key='service.information',
)
channel.basic_publish(
    exchange='service_information',
    routing_key='service.information',
    body=json.dumps({'info': service_info, 'state': 'on'}),
    properties=pika.BasicProperties(delivery_mode=2),  # persistent
)
```

| Property | Value |
|----------|-------|
| **Exchange name** | `service_information` |
| **Exchange type** | `topic` |
| **Queue name** | `service_infor_queue` |
| **Routing key** | `service.information` |
| **Queue durability** | `durable=True` |
| **Message persistence** | `delivery_mode=2` |

**Why topic?** Topic exchange allows pattern-based routing (`service.*`,
`*.information`), which provides extensibility for future event types without
changing the exchange. Currently only `service.information` is used, but the
topic type allows adding keys like `service.health` or `service.metrics`
without creating new exchanges.

**Why durable?** Registration events must not be lost if the broker restarts
between a service registering and the registry processing the event. Both the
queue and messages use persistence (`durable=True`, `delivery_mode=2`).

### Exchange 3: `services_update` (Fanout)

**Purpose:** Broadcast the complete service list to all connected GUI clients
after each registration change.

```python
# amqp_registry_adapter.py — broadcast_update()
channel.exchange_declare(exchange='services_update', exchange_type='fanout')
channel.basic_publish(
    exchange='services_update',
    routing_key='',              # ignored by fanout
    body=json.dumps(services_info),
)

# amqp_registry_adapter.py — subscribe_to_updates()
channel.exchange_declare(exchange='services_update', exchange_type='fanout')
result = channel.queue_declare(queue='', exclusive=True)
queue_name = result.method.queue
channel.queue_bind(exchange='services_update', queue=queue_name)
```

| Property | Value |
|----------|-------|
| **Exchange name** | `services_update` (configurable via `update_exchange_name`) |
| **Exchange type** | `fanout` |
| **Queue names** | Auto-generated exclusive (`amq.gen-*`) |
| **Routing key** | Not used (fanout ignores routing keys) |
| **Queue lifecycle** | Auto-deleted when subscriber disconnects |

**Why fanout?** Every GUI client must receive every update — this is broadcast
semantics. Fanout delivers to all bound queues without routing key filtering.
Topic or direct would require each subscriber to know a specific routing key,
adding unnecessary coupling.

**Why exclusive queues?** Each GUI client creates its own exclusive queue.
When the client disconnects, the queue is automatically deleted — no orphaned
queues accumulate. This also prevents competing consumers (if two GUIs shared
a queue, each would receive only half the updates).

**Why configurable name?** The exchange name is passed via
`update_exchange_name` parameter, defaulting to `'services_update'`. This
allows multiple registry instances on the same broker to use separate update
channels.

### Queue Lifecycle Summary

| Queue | Created By | Lifecycle | Durability |
|-------|-----------|-----------|------------|
| Service queue (e.g. `Calculator`) | Service on startup | Purged on service restart; exists while service runs | Non-durable |
| `service_infor_queue` | Registry on startup | Persistent across broker restarts | Durable |
| RPC callback (`amq.gen-*`) | Client per RPC call | Exclusive; auto-deleted on connection close | Non-durable |
| Update subscriber (`amq.gen-*`) | GUI client on subscribe | Exclusive; auto-deleted on disconnect | Non-durable |

### Queue Purge on Startup

```python
channel.queue_declare(queue=service_name)
channel.queue_purge(queue=service_name)
```

When a service starts, it purges its own queue. This clears any stale messages
left from a previous instance that may have crashed. Without purging, the new
instance could process outdated requests with potentially different state.

## Why Three Separate Exchanges

### Alternative: Single Exchange for Everything (Rejected)

Use one topic exchange with routing key patterns to distinguish message types:

```
single_exchange (topic)
├── rpc.calculator      → Calculator queue
├── rpc.registry        → Registry queue
├── event.registration  → Registry event queue
└── update.services     → GUI clients (how?)
```

Rejected because:
- **Fanout impossible** — a topic exchange cannot broadcast to all queues
  without each subscriber knowing a specific binding pattern
- **Mixed durability** — some queues need durability (events), others don't
  (RPC). A single exchange obscures this distinction.
- **Routing complexity** — every consumer must carefully set binding patterns
  to avoid receiving messages meant for other patterns
- **No isolation** — a misconfigured binding could route RPC messages to the
  event queue or vice versa

### Alternative: Direct + Direct + Direct (Rejected)

Use direct exchanges for all three patterns, including broadcasts.

Rejected because:
- Direct exchange cannot broadcast to multiple queues with the same routing
  key. Each `basic_publish` delivers to exactly one queue. To broadcast, the
  registry would need to iterate over all subscriber queues and publish
  individually — duplicating what fanout does natively.

### Alternative: Per-Service Exchanges (Rejected)

Create a separate exchange for each service (e.g. `exchange.calculator`,
`exchange.registry`).

Rejected because:
- **Proliferation** — N services means N exchanges to manage
- **Discovery coupling** — clients must know the exchange name per service
  (currently they only need the routing key)
- **No benefit** — direct exchange with per-service routing keys achieves the
  same isolation with a single exchange

## Consequences

### Positive

- **Clean separation** — each exchange serves exactly one messaging pattern
  with the optimal exchange type
- **Self-documenting** — exchange names reflect their purpose
  (`services_request`, `service_information`, `services_update`)
- **Correct durability** — registration events are durable; RPC and update
  queues are ephemeral (appropriate for each use case)
- **No competing consumers** — exclusive queues for fanout ensure every
  subscriber gets every message
- **Minimal configuration** — services only need their routing key; exchange
  names are constants in the codebase

### Negative

- **Three exchanges to manage** — slightly more broker configuration than a
  single exchange (mitigated: exchanges are auto-declared in code)
- **Queue purge on startup** — discards any messages queued for a service
  during downtime (acceptable: RPC callers receive timeout errors and can
  retry)

### Neutral

- Exchange declarations are idempotent (`exchange_declare` with same
  parameters is a no-op if the exchange already exists)
- The default exchange (`''`) is used implicitly for RPC replies — this is a
  standard AMQP pattern, not a custom exchange
- `prefetch_count=1` limits throughput to one concurrent request per service;
  this is intentional for services that are not designed for concurrent
  processing

## References

- Source: `MicroserviceBase/adapters/transport/rabbitmq_adapter.py` (lines 150-183, 220-266)
- Source: `MicroserviceBase/adapters/registry/amqp_registry_adapter.py` (lines 49-51, 134-159, 206-270)
- Source: `MicroserviceBase/domain/service_base.py` (line 70, `_SERVICE_REQUEST_EXCHANGE`)
- Related: ADR-016 (RabbitMQ as Message Broker), ADR-001 (Hexagonal Architecture)
