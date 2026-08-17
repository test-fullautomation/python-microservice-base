# ADR-027: Kafka event bus alongside gRPC

## Status

Proposed

## Date

2026-05-07

## Author

Audit follow-up.  Aligns with the TA reference at
[`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal).

## Reviewer

- (pending)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-05-07 | 1.0 | Initial draft |

## Context

The migration from RabbitMQ to gRPC (ADR-016 superseded; ADR-018
superseded) gave us a clean request/response substrate but left a gap:

- **gRPC is point-to-point** — caller knows the callee.  Fine for
  "set the power supply to 12V" but not for "broadcast that a test
  run started" where N independent subscribers care
- **gRPC server-streaming exists** but is per-client.  If a service
  wants to fan out an event to every interested party, it has to
  enumerate subscribers — back to where RabbitMQ used to help
- **Event history is gone** — RabbitMQ at least kept queues; gRPC
  streams don't replay

Real workloads in this framework include:

- **Test run events** — start/progress/finish broadcast to GUIs,
  loggers, dashboards
- **Hardware telemetry** — periodic samples that 0..N consumers want
- **Audit / observability** — every gRPC call may want to publish a
  trace event without coupling to consumers

The TA reference adds **Kafka** as the event bus for exactly this
class of traffic, while keeping gRPC for command/control.

## Decision

Adopt **Kafka as a pub/sub event bus alongside gRPC**, not as a
replacement.  Two-substrate architecture:

| Pattern | Substrate | Example |
|---|---|---|
| Synchronous request/response | **gRPC** | "Set PPS to 12V" → returns `Ack` |
| Long-running per-client stream | **gRPC server-streaming** | "Stream scope samples to me" |
| Broadcast events to N unknown consumers | **Kafka** | "Test run #42 started" |
| Replayable history | **Kafka** | "What test runs happened today?" → consume from offset |
| Decoupled producer ↔ consumer | **Kafka** | Logger consumes events without service knowing about it |

- **Kafka cluster**: 3-broker minimum in production; single-broker
  Bitnami container fine for dev
- **Topic naming convention**: `mb.<domain>.<event>` (e.g.
  `mb.test.run_started`, `mb.hardware.pps_sample`)
- **Schema**: protobuf-encoded payloads, schema versioned in the same
  `.proto` files used for gRPC.  No separate Avro/JSON schema
  vocabulary
- **Discovery**: Kafka brokers register in Consul with service name
  `kafka` so clients use the same Consul-resolver that gRPC uses
- **MicroserviceBase support**: new `adapters/kafka/` module with
  `KafkaPublisher` and `KafkaSubscriber` ports, scaffold templates
  emit boilerplate when the user opts into "this service publishes
  events"

## Consequences

### Positive

- **Right tool for each pattern** — gRPC for sync, Kafka for fan-out
- **Decoupling** — services publish events without caring who
  consumes them.  Adding a new dashboard / logger doesn't require
  changes to producers
- **Replay** — bug investigations can re-run consumers against
  historical offsets
- **Same schema language** — protobuf for both substrates means one
  source of truth for message shapes
- **Aligns with TA reference**

### Negative

- **Two substrates to operate** — Kafka cluster joins Consul + Nomad
  in the ops surface
- **Schema-evolution discipline** — Kafka topics are long-lived;
  breaking schema changes affect any retained messages.  Need a
  policy (additive-only fields, never remove or renumber)
- **Distinct failure modes** — Kafka durability vs. gRPC's in-memory
  delivery.  Producers must decide: publish-and-forget vs. wait-for-ack
- **Ordering guarantees vary** — Kafka ordering is per-partition;
  events that must be globally ordered need a single partition (and
  its throughput ceiling) or in-payload sequence numbers

### Neutral

- This **does not resurrect RabbitMQ** — Kafka is structurally
  different (log-based, partitioned, replayable; vs. RabbitMQ's
  queue-based delivery)

## Alternatives Considered

### 1. gRPC server-streaming for everything (Rejected)

What we have today.  Forces every producer to track every subscriber;
no replay; doesn't scale to N independent dashboards.

### 2. NATS / Redis Streams (Rejected)

Both work technically.

Rejected because:
- TA reference uses Kafka; consistency reduces ops cognitive load
- Kafka's ecosystem (Kafka Connect, ksqlDB, observability tools) is
  larger
- Bosch internal infrastructure has Kafka deployed; piggybacking on
  it is cheaper than introducing a new service

### 3. Bring back RabbitMQ (Rejected)

Would re-introduce all the problems ADR-016/018 were superseded for
— routing-key spaghetti, schema-less payloads, brittle topology.

Kafka is structurally different and doesn't have those issues.

## References

- Reference architecture:
  [`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
- [`docs/diagrams/00_canonical_architecture.puml`](../diagrams/00_canonical_architecture.puml) —
  shows Kafka in the canonical topology
- [ADR-028 gRPC + reflection as the primary RPC layer](028-grpc-reflection-primary-rpc.md) — sibling decision for the sync substrate
- Supersedes residual scope of [ADR-016 RabbitMQ as message broker](016-rabbitmq-as-message-broker.md) (the broadcast use case)
- Kafka docs: <https://kafka.apache.org/documentation/>
