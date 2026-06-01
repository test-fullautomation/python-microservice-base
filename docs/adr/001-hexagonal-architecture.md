# ADR-001: Hexagonal Architecture (Ports and Adapters)

## Status

Accepted

## Date

2026-01-15

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-01-15 | 1.0 | Initial version |

## Context

The original MicroserviceBase codebase was monolithic with tight coupling between business logic and infrastructure:

```python
# Before: Business logic directly depends on pika (RabbitMQ client)
class ServiceBase:
    def serve(self):
        connection = pika.BlockingConnection(...)  # Hardcoded transport
        channel = connection.channel()
        channel.exchange_declare(...)
        channel.queue_declare(...)
        channel.basic_consume(on_message_callback=self.on_request)
        channel.start_consuming()
```

**Problems:**
- Cannot unit test services without a running RabbitMQ broker
- Cannot swap transport (e.g., from RabbitMQ to EventBus) without rewriting service code
- Business logic, message parsing, and I/O are interleaved in the same class
- Adding a new UI layer (web browser) requires touching domain code

## Decision

Restructure into a hexagonal (ports & adapters) architecture with four layers:

```
┌─────────────────────────────────────────────┐
│             Domain Layer                     │  ← Pure business logic
│   (ServiceBase, ServiceRegistry, Models)     │     Zero external deps
├─────────────────────────────────────────────┤
│             Ports Layer                      │  ← Abstract contracts
│   (TransportPort, RegistryPort, UIPort)      │     ABC interfaces
├─────────────────────────────────────────────┤
│           Adapters Layer                     │  ← Concrete impls
│   (RabbitMQ, EventBus, FastAPI, LocalHub)    │     Infrastructure
├─────────────────────────────────────────────┤
│          Factory / Composition Root          │  ← Wiring
│   (create_transport, create_registry, ...)   │     Config-driven
└─────────────────────────────────────────────┘
```

**Directory structure:**

```
MicroserviceBase/
├── domain/
│   ├── service_base.py      # Core service logic
│   ├── service_registry.py  # Service discovery
│   ├── messages.py          # ServiceRequest, ServiceResponse
│   ├── models.py            # ServiceInfo, ServiceMethod
│   └── exceptions.py        # ServiceError hierarchy
├── ports/
│   ├── transport.py         # TransportPort ABC
│   ├── registry.py          # ServiceRegistryPort ABC
│   └── ui_bridge.py         # UIBridgePort ABC
├── adapters/
│   ├── transport/
│   │   ├── rabbitmq_adapter.py
│   │   └── eventbus_adapter.py
│   ├── registry/
│   │   ├── amqp_registry_adapter.py
│   │   └── eventbus_registry_adapter.py
│   ├── ui_bridge/
│   │   └── fastapi_bridge.py
│   └── local_hub/
│       ├── local_hub_manager.py
│       └── service_executor.py
└── factory.py               # Composition root
```

**After: Domain depends only on abstract ports:**

```python
class ServiceBase:
    def __init__(self, transport=None, registry=None):
        self._transport = transport  # TransportPort (abstract)
        self._registry = registry    # ServiceRegistryPort (abstract)

    def serve(self):
        self._transport.consume(
            service_name=self.name,
            routing_key=self._SERVICE_INFO['routing_key'],
            exchange=self._SERVICE_REQUEST_EXCHANGE,
            handler=self.on_request,
        )
```

**Dependency direction:** Adapters depend on Ports, Ports depend on Domain. Never reverse.

## Consequences

### Positive

- Services can be unit tested without a broker (inject mock transport)
- Transports are swappable via factory configuration (`'rabbitmq'` vs `'eventbus'`)
- Clear file boundaries make code navigation intuitive
- New adapter types (e.g., gRPC transport) can be added without touching domain

### Negative

- More files and indirection than a monolithic approach
- Developers must understand the layered architecture to contribute
- Small overhead from port interface dispatch

### Neutral

- Existing service code (subclasses of ServiceBase) requires no changes
- Wire format (JSON over AMQP) remains the same

## Alternatives Considered

### 1. Keep Monolithic Structure (Rejected)

Continue with direct pika calls in ServiceBase.

Rejected because:
- Impossible to test without broker
- Cannot support EventBus transport without major refactoring

### 2. Plugin-Based Architecture (Deferred)

Load adapters dynamically via entry points.

Deferred because:
- Adds setuptools complexity
- Factory pattern is sufficient for current needs
- Can evolve toward plugins later if needed

## References

- [Hexagonal Architecture (Alistair Cockburn)](https://alistair.cockburn.us/hexagonal-architecture/)
- Source: `MicroserviceBase/domain/`, `MicroserviceBase/ports/`, `MicroserviceBase/adapters/`
- Diagram: `docs/diagrams/architecture.puml`
