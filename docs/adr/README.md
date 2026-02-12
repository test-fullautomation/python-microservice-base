# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the MicroserviceBase restructuring project.

ADRs document important architectural decisions made during the development of the project, along with their context, rationale, and consequences.

## Index

| ADR | Title | Status | Date | Author | Reviewer |
|-----|-------|--------|------|--------|----------|
| [ADR-001](001-hexagonal-architecture.md) | Hexagonal Architecture (Ports and Adapters) | Accepted | 2026-01-15 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-002](002-factory-pattern-dependency-injection.md) | Factory Pattern for Dependency Injection | Accepted | 2026-01-15 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-003](003-service-registry-over-zookeeper.md) | Custom Service Registry over ZooKeeper | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-004](004-electron-over-qt-for-gui-framework.md) | Electron over Qt for GUI Framework | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-005](005-dual-host-gui-architecture.md) | Dual-Host GUI Architecture (Electron + Browser) | Accepted | 2026-01-20 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-006](006-fastapi-bridge-for-browser-gui.md) | FastAPI Bridge for Browser GUI | Accepted | 2026-01-20 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-007](007-multi-broker-connection-architecture.md) | Multi-Broker Connection Architecture | Accepted | 2026-01-25 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-008](008-electron-bridge-lifecycle-decoupling.md) | Electron Bridge Lifecycle Decoupling | Accepted | 2026-02-01 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-009](009-service-executor-with-rpc-shutdown.md) | Service Executor with RPC Graceful Shutdown | Accepted | 2026-02-01 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-010](010-local-hub-manager.md) | Local Hub Manager for ProcessHub Integration | Accepted | 2026-02-01 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-011](011-service-import-with-module-execution.md) | Service Import with Module Execution Pattern | Accepted | 2026-02-05 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-012](012-registry-shutdown-notification.md) | Registry Shutdown Notification to GUI | Accepted | 2026-02-03 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-013](013-windows-process-lifecycle-fixes.md) | Windows Process Lifecycle Fixes | Accepted | 2026-02-01 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-014](014-config-placeholder-persistence.md) | Config Placeholder Persistence | Accepted | 2026-02-01 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-015](015-fleet-orchestrator-architecture.md) | Fleet Orchestrator for Multi-Hub Process Management | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-016](016-rabbitmq-as-message-broker.md) | RabbitMQ as Message Broker | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-017](017-svc-api-naming-convention.md) | svc_api_ Naming Convention for Method Discovery | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-018](018-alias-routing-design.md) | Alias Routing via Service Registry | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-019](019-service-delivered-gui-plugins.md) | Service-Delivered GUI Plugin Architecture | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |
| [ADR-020](020-exchange-topology-design.md) | Exchange Topology Design | Accepted | 2026-02-12 | Nguyen Huynh Tri Cuong | Nguyen Huynh Tri Cuong |

## Summary of Design Decisions

### Core Architecture (ADR-001, ADR-002, ADR-003)

The system is built on hexagonal architecture with factory-based dependency injection:

1. **Hexagonal Architecture** (ADR-001): Four layers — Domain, Ports, Adapters, Factory — with strict dependency direction (outer depends on inner, never reverse).

2. **Factory Pattern** (ADR-002): `create_transport()`, `create_registry()`, and `create_ui_bridge()` centralize adapter wiring, keeping service code transport-agnostic.

3. **Custom Service Registry** (ADR-003): Built as a domain-layer microservice using the same RabbitMQ RPC protocol as all services, providing service discovery, real-time updates, and alias routing — capabilities that external tools (ZooKeeper, Consul, etcd) cannot provide without rebuilding the registry as a bridge.

### Service API & Communication (ADR-016, ADR-017, ADR-018)

Service communication and API patterns:

| Feature | Description | ADR |
|---------|-------------|-----|
| RabbitMQ Broker | Three exchange types (direct, topic, fanout) for RPC, events, and broadcasts | ADR-016 |
| svc_api_ Convention | Naming-based method discovery via `dir()` + prefix filtering, docstring metadata | ADR-017 |
| Alias Routing | `${input}` placeholder substitution in Service Registry for simplified method shortcuts | ADR-018 |
| Exchange Topology | Three exchanges (`services_request`, `service_information`, `services_update`) with type-per-pattern design | ADR-020 |

### GUI Architecture (ADR-004, ADR-005, ADR-006, ADR-007, ADR-008, ADR-019)

The GUI supports dual hosting with multi-broker connectivity and service-delivered plugins:

| Component | Purpose | ADR |
|-----------|---------|-----|
| Electron over Qt | Why Electron: service-delivered HTML GUIs need a real browser engine | ADR-004 |
| Dual-Host GUI | Electron + pure browser from same codebase | ADR-005 |
| FastAPI Bridge | REST + WebSocket gateway for browsers | ADR-006 |
| Multi-Broker | Simultaneous connections to multiple RabbitMQ brokers | ADR-007 |
| Bridge Decoupling | Bridge survives GUI close for persistent service access | ADR-008 |
| Service-Delivered GUI | Services deliver HTML/CSS/JS plugins via RPC, loaded dynamically on demand | ADR-019 |

### Process Management (ADR-009, ADR-010, ADR-011, ADR-015)

Local process management with graceful lifecycle control and multi-hub fleet coordination:

| Feature | Description | ADR |
|---------|-------------|-----|
| RPC Shutdown | Two-phase stop: RPC first, signal fallback | ADR-009 |
| Local Hub Manager | ProcessHub lifecycle + config + status orchestration | ADR-010 |
| Service Import | ZIP/folder import with `python -m` execution and AST validation | ADR-011 |
| Fleet Orchestrator | Multi-hub coordination via RabbitMQ with health monitoring and remote process control | ADR-015 |

### Operational Resilience (ADR-012, ADR-013, ADR-014)

Platform-specific fixes and runtime reliability:

| Feature | Description | ADR |
|---------|-------------|-----|
| Registry Shutdown Sentinel | GUI notified before Registry exits | ADR-012 |
| Windows Fixes | SIGBREAK handling, consume loop, pipe blocking | ADR-013 |
| Config Portability | `${python}` / `${config_dir}` placeholders | ADR-014 |

## Design Principles

These ADRs collectively establish the following design principles:

1. **Zero-Dependency Domain**: Domain layer imports no infrastructure libraries
2. **Transport Independence**: Services work with RabbitMQ, EventBus, or custom transports
3. **Browser Portability**: GUI works in Electron and plain browsers without modification
4. **Graceful Degradation**: Services unregister cleanly on all stop paths
5. **Config Portability**: Placeholder-based configs work across machines
6. **Convention over Configuration**: `svc_api_*` prefix for auto-discovered API methods

## ADR Template

When creating a new ADR, copy [000-template.md](000-template.md) and follow the instructions inside.

## Architecture Diagrams

PlantUML diagrams are maintained in [`docs/diagrams/`](../diagrams/). Each diagram corresponds to one or more ADRs:

| Diagram | Description | Related ADRs |
|---------|-------------|--------------|
| [overview.puml](../diagrams/overview.puml) | System overview with all major components | All |
| [architecture.puml](../diagrams/architecture.puml) | Hexagonal architecture layers | ADR-001, ADR-002 |
| [component.puml](../diagrams/component.puml) | Component diagram with dependencies | ADR-001 through ADR-008 |
| [class_domain.puml](../diagrams/class_domain.puml) | Domain layer class diagram | ADR-001 |
| [class_ports.puml](../diagrams/class_ports.puml) | Port interfaces class diagram | ADR-001 |
| [class_adapters.puml](../diagrams/class_adapters.puml) | Adapter classes (incl. Local Hub) | ADR-001, ADR-009, ADR-010 |
| [gui_architecture.puml](../diagrams/gui_architecture.puml) | Dual-host GUI architecture | ADR-005, ADR-006, ADR-007, ADR-008 |
| [sequence_registration.puml](../diagrams/sequence_registration.puml) | Service registration sequence | ADR-001 |
| [sequence_rpc.puml](../diagrams/sequence_rpc.puml) | RPC request-response sequence | ADR-001 |
| [sequence_alias.puml](../diagrams/sequence_alias.puml) | Alias routing sequence | ADR-001 |
| [sequence_shutdown.puml](../diagrams/sequence_shutdown.puml) | Two-phase shutdown sequence | ADR-009, ADR-013 |
| [sequence_service_import.puml](../diagrams/sequence_service_import.puml) | Service import flow | ADR-011 |
| [state_process_lifecycle.puml](../diagrams/state_process_lifecycle.puml) | Process lifecycle state machine | ADR-009, ADR-010, ADR-013 |
| [sequence_realtime_update.puml](../diagrams/sequence_realtime_update.puml) | Real-time update broadcast flow | ADR-020, ADR-006 |
| [sequence_gui_plugin_loading.puml](../diagrams/sequence_gui_plugin_loading.puml) | GUI plugin loading flow | ADR-019, ADR-006 |

## References

- [ADR GitHub Organization](https://adr.github.io/)
- [Michael Nygard's ADR Article](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- [MicroserviceBase Concept Document](../CONCEPT.md)
