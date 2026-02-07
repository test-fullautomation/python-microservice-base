# MicroserviceBase Library Concept

## Executive Summary

MicroserviceBase is a **pluggable microservice framework** that enables developers to create, register, discover, and invoke services through a message broker. It uses a hexagonal (ports & adapters) architecture to decouple domain logic from infrastructure, making it easy to swap transports (RabbitMQ, EventBus) and UI layers (FastAPI, Electron) without changing business code.

## The Problem We Solve

### Traditional Approach (Without MicroserviceBase)

In a typical distributed test-automation or service-oriented environment:

```
Developer A builds Service X  ──────►  Hardcoded RabbitMQ calls everywhere
Developer B builds Service Y  ──────►  Different message format, incompatible
Operator wants to see services ──────►  No central view, manual discovery
User wants to call a service   ──────►  Must know exact routing key & exchange
Service X changes its API      ──────►  All callers break silently
```

**Common issues:**
- **Tight coupling** - Services hardcode broker connections, message formats, and routing
- **No discovery** - Callers must know the exact routing key of every service
- **No API introspection** - No way to discover what methods a service offers
- **Incompatible messages** - Each service invents its own request/response format
- **No central visibility** - No dashboard to see what services are running
- **Transport lock-in** - Switching from RabbitMQ to another broker requires rewriting everything

### MicroserviceBase Approach

```
                    ┌─────────────────────────────┐
                    │      Service Registry        │
                    │   (Central Discovery Hub)    │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
     ┌────▼────┐             ┌─────▼────┐             ┌─────▼────┐
     │Service A│             │Service B │             │Service C │
     │(extends │             │(extends  │             │(extends  │
     │ Base)   │             │  Base)   │             │  Base)   │
     └─────────┘             └──────────┘             └──────────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     Message Broker            │
                    │  (RabbitMQ / EventBus)        │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    MicroserviceManagerGUI     │
                    │  (Electron / Browser / API)   │
                    └──────────────────────────────┘
```

**MicroserviceBase guarantees:**
- **Auto-registration** - Services announce themselves with full API metadata
- **Auto-discovery** - Clients discover services and their methods at runtime
- **Structured protocol** - All services use the same request/response format
- **Transport independence** - Switch brokers without changing service code
- **GUI reflection** - Registry exposes service info for any UI to render
- **Alias routing** - Registry can map user-friendly names to service methods

## Core Concepts

### 1. Convention-over-Configuration API

Services expose their API by defining methods with the `svc_api_` prefix:

```python
class MyService(ServiceBase):
    _SERVICE_INFO = {
        'name': 'Calculator',
        'description': 'A simple calculator service.',
        'routing_key': 'service.calculator',
    }

    def svc_api_add(self, a, b):
        """
Add two numbers.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First number.

* ``b``

  / *Condition*: required / *Type*: int /

  Second number.

**Returns:**

  / *Type*: int /

  Sum of a and b.
        """
        return int(a) + int(b)
```

At startup, MicroserviceBase:
1. Discovers all `svc_api_*` methods via introspection
2. Parses their docstrings to extract argument types and descriptions
3. Builds a machine-readable API descriptor
4. Registers this information with the Service Registry

### 2. Hexagonal Architecture

MicroserviceBase separates concerns into distinct layers:

```
┌─────────────────────────────────────────────┐
│             Domain Layer                     │  ← Pure business logic
│   (ServiceBase, ServiceRegistry, Models)     │     Zero external deps
├─────────────────────────────────────────────┤
│             Ports Layer                      │  ← Abstract contracts
│   (TransportPort, RegistryPort, UIPort)      │     ABC interfaces
├─────────────────────────────────────────────┤
│           Adapters Layer                     │  ← Concrete impls
│   (RabbitMQ, EventBus, FastAPI)              │     Infrastructure
├─────────────────────────────────────────────┤
│          Factory / Composition Root          │  ← Wiring
│   (create_transport, create_registry, ...)   │     Config-driven
└─────────────────────────────────────────────┘
```

Benefits:
- **Domain logic is testable** without a broker
- **Transports are swappable** (RabbitMQ, EventBus, or custom)
- **UI layers are swappable** (FastAPI, Electron, or custom)
- **Clear boundaries** make the code maintainable

### 3. Service Registration and Discovery

When a service starts, it registers with the Service Registry:

```
Phase 1: STARTUP     Service initializes, discovers its own API
Phase 2: REGISTER    Service publishes metadata to service_information exchange
Phase 3: DISCOVERY   Registry receives event, stores service info
Phase 4: BROADCAST   Registry notifies all UI clients of update
Phase 5: SERVE       Service starts consuming RPC requests
```

When a service stops:

```
Phase 1: UNREGISTER  Service publishes "off" event
Phase 2: CLEANUP     Registry removes service from its tracking dict
Phase 3: BROADCAST   Registry notifies all UI clients of update
```

### 4. Request-Response Protocol

All service calls follow a structured message protocol:

**ServiceRequest:**
```json
{
    "method": "svc_api_add",
    "args": [3, 5]
}
```

**ServiceResponse:**
```json
{
    "request": "svc_api_add",
    "result": "pass",
    "result_data": 8
}
```

Result types:
| Result | Meaning |
|--------|---------|
| `pass` | Method executed successfully |
| `fail` | Method returned a failure indication |
| `exception` | Method raised an exception |

### 5. Alias Routing

The Service Registry supports method aliasing, allowing user-friendly names
to map to specific service methods with pre-configured arguments:

```json
{
    "reset_device": {
        "Service name": "ServiceDebugboard",
        "Method name": "svc_api_reset",
        "Arguments": "${input},hard"
    }
}
```

When a client calls `reset_device(board_id)`:
1. Registry looks up the alias configuration
2. Substitutes `${input}` with the provided argument
3. Routes the request to `ServiceDebugboard.svc_api_reset(board_id, "hard")`
4. Returns the response to the caller

This decouples callers from knowing specific service names and method signatures.

### 6. Pluggable Transport Layer

Communication is abstracted behind a transport interface:

| Transport | Use Case |
|-----------|----------|
| **RabbitMQ (pika)** | Direct AMQP, simple setup, low dependency |
| **EventBus (aio_pika)** | Enterprise, async, JSONP config, shared infrastructure |

All transports implement the same `TransportPort` interface, so switching
requires only a config change:

```python
# RabbitMQ transport
transport = create_transport('rabbitmq', cmd_args=sys.argv[1:])

# EventBus transport
transport = create_transport('eventbus', config_path='config.jsonp')
```

### 7. GUI Reflection

The MicroserviceManagerGUI connects to the Service Registry and renders:
- List of all registered services with status
- API methods for each service with argument descriptions
- Interactive controls to invoke service methods
- Real-time updates when services register or unregister

Any UI (Electron, browser, mobile) can connect via:
- **AMQP** - Direct broker connection (legacy Electron GUI)
- **FastAPI** - REST API + WebSocket for browser-based clients

## Key Features

### For Service Developers

| Feature | Benefit |
|---------|---------|
| `svc_api_*` convention | Just define methods, framework handles the rest |
| Docstring parsing | API documentation is auto-generated from code |
| `ServiceBase` inheritance | One base class provides full service lifecycle |
| Transport injection | Test services without a real broker |

### For System Operators

| Feature | Benefit |
|---------|---------|
| Service Registry | Central view of all running services |
| GUI dashboard | Visual monitoring and control |
| Alias routing | Simplify complex service calls |
| FastAPI bridge | REST API for integration with external tools |

### For Architects

| Feature | Benefit |
|---------|---------|
| Hexagonal architecture | Clean separation of concerns |
| Port interfaces | Explicit contracts between layers |
| Factory pattern | Centralized adapter wiring |
| Pluggable transports | No vendor lock-in |

## Design Principles

### 1. Convention over Configuration

Services declare their API by method naming convention (`svc_api_*`) rather than
explicit registration calls. The framework discovers and documents APIs automatically.

### 2. Zero-Dependency Domain

The domain layer (`domain/`) imports nothing from pika, EventBusClient, FastAPI,
or any other infrastructure library. This ensures:
- Unit tests run without a broker
- Business logic is portable across transports
- Clear dependency direction (adapters depend on domain, never reverse)

### 3. Constructor Injection

Domain objects receive their dependencies (transport, registry) via constructor:
```python
service = ServiceBase(transport=my_transport, registry=my_registry)
```

The factory functions handle wiring for convenience:
```python
transport = create_transport('rabbitmq', cmd_args=sys.argv[1:])
registry = create_registry('rabbitmq', cmd_args=sys.argv[1:])
```

### 4. Backward-Compatible Serialization

All domain models provide `to_dict()` / `from_dict()` methods, ensuring
JSON serialization stays compatible across versions. The wire format uses
plain dicts, not pickled objects.

## Recommended Diagrams

### For Understanding the System

| Purpose | Diagram | File |
|---------|---------|------|
| **Big picture** | System Overview | `overview.puml` |
| **All layers** | Architecture | `architecture.puml` |
| **Component wiring** | Component Diagram | `component.puml` |

### For Understanding Behavior

| Purpose | Diagram | File |
|---------|---------|------|
| **Service registration** | Registration Sequence | `sequence_registration.puml` |
| **RPC call flow** | RPC Sequence | `sequence_rpc.puml` |
| **Alias routing** | Alias Sequence | `sequence_alias.puml` |

### For Understanding Code

| Purpose | Diagram | File |
|---------|---------|------|
| **Domain classes** | Domain Class Diagram | `class_domain.puml` |
| **Port interfaces** | Ports Class Diagram | `class_ports.puml` |
| **Adapter classes** | Adapters Class Diagram | `class_adapters.puml` |

## Summary

MicroserviceBase provides:

1. **Convention-based API** - Define `svc_api_*` methods, get auto-discovery
2. **Central Registry** - Service discovery with alias routing
3. **Structured Protocol** - Typed request/response messages
4. **Pluggable Transport** - RabbitMQ, EventBus, or custom
5. **GUI Reflection** - Any UI can render service information
6. **Clean Architecture** - Hexagonal layers with dependency injection

It is designed for:
- Test automation systems with multiple services
- HIL/SIL environments requiring service orchestration
- Distributed systems needing central service discovery
- Any scenario where services must be discoverable and invocable at runtime
