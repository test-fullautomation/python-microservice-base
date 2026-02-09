# ADR-002: Factory Pattern for Dependency Injection

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

With hexagonal architecture (ADR-001), services receive their transport and registry via constructor injection. But service developers should not need to know how to instantiate adapters or configure their connection parameters.

```python
# Without factory: developer must know adapter details
from MicroserviceBase.adapters.transport.rabbitmq_adapter import RabbitMQTransportAdapter
from MicroserviceBase.adapters.transport.rabbitmq_config import RabbitMQConfig

config = RabbitMQConfig.from_cmd_args(sys.argv[1:])
transport = RabbitMQTransportAdapter(config)
transport.connect()
```

This leaks infrastructure knowledge into service entry points and makes transport switching tedious.

## Decision

Provide centralized factory functions in `factory.py` as the **composition root**:

```python
from MicroserviceBase import create_transport, create_registry

transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                             service_name='Calculator')
registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],
                            service_name='Calculator')
service = CalculatorService(transport=transport, registry=registry)
```

Switching to EventBus requires changing one argument:

```python
transport = create_transport('eventbus', config_path='config.jsonp')
registry = create_registry('eventbus', config_path='config.jsonp')
```

Factory functions handle:
1. Parsing configuration (CLI args, config files)
2. Instantiating the correct adapter class
3. Connecting to the broker
4. Returning the ready-to-use port instance

## Consequences

### Positive

- Service entry points are clean and transport-agnostic
- Transport switching is a one-line change
- Connection parameters are parsed in one place

### Negative

- Factory is a "magic" layer — must read its code to understand what gets created
- Adding a new transport requires modifying the factory

### Neutral

- Factory pattern is well-known and understood by most developers

## Alternatives Considered

### 1. Dependency Injection Container (Deferred)

Use a DI framework like `dependency-injector` or `inject`.

Deferred because:
- Adds a third-party dependency
- Factory functions are simpler and sufficient for two transport types
- Can migrate to DI container if more adapter types are needed

## References

- Source: `MicroserviceBase/factory.py`
- Related: ADR-001 (Hexagonal Architecture)
