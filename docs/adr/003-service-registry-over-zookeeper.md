# ADR-003: Custom Service Registry over ZooKeeper

> **⚠ Superseded** — 2026-05-07.  Pre-migration decision; no longer
> applies to the gRPC + Consul + Nomad architecture.  See the existing
> Status note below for the immediate successor, and
> [`docs/changelog.md`](../reference/changelog.md) +
> [`docs/adr/AUDIT.md`](AUDIT.md) for the full triage.  Kept here for
> git archaeology.

## Status

Superseded — replaced by Consul service catalog (see [ADR-022](022-nomad-orchestrator-integration.md) for the Nomad+Consul rationale).

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

MicroserviceBase needs a **service registry** — a central component that:

1. Tracks which services are online and their metadata (methods, version, routing key)
2. Provides service discovery so the GUI can list available services
3. Broadcasts real-time updates when services come online or go offline
4. Routes alias requests to target services (virtual method → real method forwarding)
5. Delivers alias configuration management (CRUD on `alias.json`)

The question is: should we build a custom `ServiceRegistry` service, or adopt an
established service discovery tool like Apache ZooKeeper, HashiCorp Consul, or
etcd?

### Current Architecture

ServiceRegistry is itself a microservice — it runs on the same RabbitMQ broker
as the services it tracks, uses the same RPC protocol, and is managed by the
same ProcessHub:

```
┌─────────────┐   register(state='on')    ┌──────────────────┐
│  ServiceA   │ ──────────────────────────>│  ServiceRegistry │
│  (Python)   │   exchange: service_info   │                  │
└─────────────┘   routing: service.info    │  tracks:         │
                                           │  - services_info │
┌─────────────┐   register(state='on')     │  - alias_dict    │
│  ServiceB   │ ──────────────────────────>│                  │
│  (Python)   │                            │  publishes:      │
└─────────────┘                            │  - fanout updates│
                                           └────────┬─────────┘
                                                    │
                            svc_api_get_services_info (RPC)
                            fanout: registry_update<uuid>
                                                    │
                                                    ▼
                                           ┌────────────────┐
                                           │   GUI Client    │
                                           │  (Browser/      │
                                           │   Electron)     │
                                           └────────────────┘
```

Key design properties:

- **Same protocol**: Registry communicates via the same RabbitMQ RPC as every
  other service — no additional protocol or port.
- **Self-registering**: Registry itself is a `ServiceBase` subclass with
  `svc_api_*` methods, discoverable like any other service.
- **Fanout real-time updates**: GUI subscribes to a fanout exchange for
  push-based service list changes.
- **Alias routing**: Registry intercepts alias method names, resolves them to
  target service + method + fixed arguments, and forwards the RPC.

## Decision

Build a custom `ServiceRegistry` as a domain-layer microservice rather than
adopting a third-party service discovery system.

The core reasoning: the registry is not just a key-value store of service
addresses — it is an **active participant in the RPC protocol** that routes
alias requests, broadcasts real-time updates over RabbitMQ fanout exchanges,
and exposes its own `svc_api_*` methods. This domain-specific behaviour cannot
be replicated by a generic service discovery tool without significant glue code.

## Comparison with Third-Party Alternatives

### Requirements Matrix

| Requirement | ServiceRegistry | ZooKeeper | Consul | etcd |
|-------------|----------------|-----------|--------|------|
| **RabbitMQ-native RPC** (same exchange, same protocol as services) | Yes | No | No | No |
| **Alias routing** (forward virtual methods to real service + args) | Yes | No | No | No |
| **Fanout real-time updates** (push via RabbitMQ exchange) | Yes | ZK Watches | Blocking queries | Watch API |
| **`svc_api_*` interface** (discoverable like any other service) | Yes | No | No | No |
| **Service metadata** (methods, arguments, version, description, gui_support) | Yes (full) | KV bytes | KV + tags | KV bytes |
| **Zero additional infrastructure** | Yes (runs on existing RabbitMQ) | JVM cluster (3+ nodes) | Go binary + Raft | Go binary + Raft |
| **GUI integration** (service list, real-time sidebar, alias config) | Native | Manual bridge | Manual bridge | Manual bridge |
| **Graceful shutdown sentinel** (notify GUI before exit) | Yes | Session expiry (delayed) | Deregister event | Key delete watch |

### Candidate Analysis

#### Apache ZooKeeper (Rejected)

ZooKeeper provides distributed coordination: ephemeral nodes, watches, leader
election, and distributed locks.

**Where it overlaps:**
- Ephemeral znodes can represent online services (auto-removed on disconnect)
- Watches notify clients when a znode changes
- Hierarchical namespace can organize service metadata

**Why it does not fit:**

- **Different communication layer** — ZooKeeper uses its own TCP protocol.
  Services communicate via RabbitMQ RPC. Introducing ZooKeeper means every
  service needs two connections: one to RabbitMQ (for RPC) and one to ZooKeeper
  (for registration). The current design uses a single RabbitMQ connection for
  both.

- **No alias routing** — ZooKeeper is a passive data store. It cannot intercept
  an RPC request, resolve an alias, rewrite the method/arguments, forward to a
  target service, and return the response. This would require a separate proxy
  service on top of ZooKeeper — essentially rebuilding the registry.

- **No RPC method exposure** — the GUI calls `svc_api_get_services_info()` and
  `svc_api_get_alias_conf()` as standard RPC requests through the same
  `ServiceClient` used for all services. ZooKeeper cannot serve RPC responses
  on a RabbitMQ queue.

- **Watch model mismatch** — ZooKeeper watches are one-shot (must re-register
  after each event) and delivered over the ZK connection. Our GUI expects a
  persistent RabbitMQ fanout subscription that pushes the full service list on
  every change.

- **Heavyweight infrastructure** — a production ZooKeeper ensemble requires 3+
  JVM nodes. Our deployment is a single developer machine or small test lab.

- **Metadata limitations** — ZooKeeper stores opaque byte arrays per znode. Our
  `services_information` includes structured data: method lists with typed
  arguments, descriptions, version strings, GUI support flags. This would
  require serialization/deserialization layers on both sides.

#### HashiCorp Consul (Rejected)

Consul provides service discovery with health checking, KV store, and DNS/HTTP
interface.

**Where it overlaps:**
- Service registration with health checks
- HTTP API for service queries
- Blocking queries for change notification (long-poll)

**Why it does not fit:**

- **Separate infrastructure** — Consul runs as a Go binary with Raft consensus.
  It requires its own agent process on each machine and a server cluster.

- **HTTP-based discovery** — Consul's service catalog is queried via HTTP or
  DNS. Our GUI queries via RabbitMQ RPC. Bridging these protocols would require
  a translation layer.

- **No alias routing** — Consul routes traffic at the network level (service
  mesh, Connect proxies), not at the application/RPC level. It cannot rewrite
  method names or inject fixed arguments.

- **No RabbitMQ integration** — Consul's health checks use HTTP, TCP, or script
  probes. Our services already report health via RabbitMQ registration events.
  Adding Consul health checks would be redundant.

- **Blocking queries, not fanout** — Consul's change notification uses HTTP
  long-polling with blocking index. Our GUI expects a persistent RabbitMQ
  fanout subscription.

#### etcd (Rejected)

etcd is a distributed key-value store used by Kubernetes for cluster state.

**Where it overlaps:**
- Key-value storage for service metadata
- Watch API for change notifications
- Lease-based ephemeral keys (TTL + keepalive)

**Why it does not fit:**

- **Same fundamental gaps as ZooKeeper/Consul** — separate infrastructure,
  separate protocol, no alias routing, no RPC method exposure.
- **Kubernetes-centric** — etcd is designed as Kubernetes' backing store. Using
  it standalone for a desktop application is over-engineering.
- **gRPC API** — etcd uses gRPC, adding yet another protocol to the stack
  (RabbitMQ + gRPC + HTTP for GUI).

### The Fundamental Mismatch

All three external tools share the same structural problem:

```
┌──────────┐                    ┌──────────────┐                    ┌─────────┐
│ Services │ ── RabbitMQ RPC ──>│  ??? Bridge   │ ── ZK/Consul/  ──>│ External│
│          │                    │  (must build) │    etcd protocol  │ Registry│
└──────────┘                    └──────────────┘                    └─────────┘
                                       ▲
                                       │
                               This bridge IS the registry.
                               We'd be building it anyway.
```

Because services already communicate via RabbitMQ, any external registry needs a
**bridge service** that:
1. Listens on RabbitMQ for registration events
2. Translates them into ZK/Consul/etcd writes
3. Watches ZK/Consul/etcd for changes
4. Publishes updates back to RabbitMQ for the GUI
5. Handles alias routing (the external tool cannot do this)

This bridge would be nearly identical to the current `ServiceRegistry` — but
with added complexity from maintaining two communication channels and two points
of failure. The external tool adds infrastructure without eliminating code.

## Consequences

### Positive

- **Single protocol** — services, registry, and GUI all communicate via RabbitMQ. No additional connections, ports, or protocols.
- **Alias routing is native** — the registry intercepts RPC requests and forwards them within the same message broker. No external proxy needed.
- **Zero additional infrastructure** — runs on the same RabbitMQ broker that services already use. No JVM, no Go binary, no cluster.
- **Full metadata support** — `services_information` carries structured service info (methods, arguments, types, version, GUI support) natively in the RPC response.
- **Self-describing** — the registry exposes `svc_api_*` methods like any service, so the GUI discovers it through the same mechanism it uses for all services.
- **Graceful lifecycle** — shutdown sentinel notifies GUI immediately, rather than waiting for session expiry or TTL timeout.

### Negative

- **Single point of failure** — if the registry process crashes, service discovery is unavailable until it restarts. ZooKeeper's ensemble provides inherent redundancy.
- **No distributed consensus** — in a multi-broker setup, each broker has its own registry instance. There is no cross-broker service discovery (by design — each broker is an independent domain).
- **Custom implementation** — we maintain our own registry code instead of relying on a battle-tested external system.

### Neutral

- The registry is a small, focused service (~260 lines of domain logic). The maintenance burden is low compared to operating an external coordination cluster.
- If the project ever scales to require cross-broker service discovery, a federation layer could be added on top of the existing registry without replacing it.

## Alternatives Considered

### 1. Apache ZooKeeper (Rejected)

Distributed coordination service with ephemeral nodes and watches.

Rejected because:
- Requires separate JVM infrastructure (3+ node ensemble)
- Cannot route alias RPC requests (passive data store)
- Cannot expose `svc_api_*` methods on RabbitMQ
- Watch model (one-shot, ZK protocol) mismatches our fanout subscription model
- Would still need a bridge service that duplicates most registry logic

### 2. HashiCorp Consul (Rejected)

Service mesh and discovery platform with HTTP/DNS interface.

Rejected because:
- Separate Go binary infrastructure with Raft consensus
- HTTP/DNS discovery protocol requires bridging to RabbitMQ RPC
- No application-level alias routing (only network-level routing)
- Blocking-query change notification mismatches RabbitMQ fanout model

### 3. etcd (Rejected)

Distributed key-value store (Kubernetes backing store).

Rejected because:
- Kubernetes-centric design, overkill for desktop/lab deployment
- gRPC protocol adds a third communication channel
- Same fundamental gaps: no alias routing, no RPC exposure, needs bridge

### 4. DNS-Based Service Discovery (Rejected)

Use DNS SRV records for service location.

Rejected because:
- DNS provides only host:port resolution, not rich metadata (methods, arguments, version)
- No real-time push notifications (TTL-based polling only)
- No alias routing capability
- Requires a DNS server or mDNS infrastructure

## References

- Source: `MicroserviceBase/domain/service_registry.py`
- Source: `MicroserviceBase/adapters/registry/amqp_registry_adapter.py`
- Source: `MicroserviceBase/ports/registry.py`
- Related: ADR-001 (Hexagonal Architecture), ADR-010 (Local Hub Manager)
