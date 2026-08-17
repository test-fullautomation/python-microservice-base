# ADR-028: gRPC + reflection as the primary RPC layer

## Status

Proposed (consolidates the gRPC migration formalised piecemeal across ADR-016/017/018 supersessions)

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
| 2026-05-22 | 1.1 | Bridge-side fix recorded: `MessageToDict` on the bridge now opts into `always_print_fields_with_no_presence=True` (older protobuf: `including_default_value_fields=True`) so proto3 scalar fields holding their default value (0, false, "") are surfaced in the JSON response dict.  Without it, a successful unary RPC returning `{"errorcode": 0}` would appear as `{}` to clients (notably Robot tests via QConnectBase's `verify`).  Code in `MicroserviceBase/adapters/grpc_bridge/reflect_client.py::_msg_to_dict`. |

## Context

The framework migrated away from RabbitMQ but the rationale for the
*replacement substrate* was scattered across the supersession callouts
on ADR-016 (broker), ADR-017 (svc/api naming), and ADR-018 (alias
routing).  No single ADR captures **why gRPC** beyond "it's the
standard now."

That gap matters because:

- New contributors ask "why not REST? why not Thrift? why not raw TCP?"
- The reflection-based dynamic-call story (used heavily by the Manager
  GUI's API Explorer and by `LocalProtoClient`) isn't documented as
  an architectural commitment — it looks like an implementation detail
- The "Kafka for events" decision (ADR-027) only makes sense with this
  ADR as its counterpart

This ADR consolidates the rationale and locks in the **gRPC + protobuf
+ server reflection** triple as the framework's primary RPC layer.

## Decision

The framework's **synchronous substrate is gRPC** with the following
commitments:

- **Transport**: HTTP/2 + protobuf-encoded messages, insecure for
  on-LAN dev, mTLS for cross-machine (deferred ADR — ACL & TLS
  rollout)
- **Schemas**: `.proto` files are the source of truth.  Multi-file
  `.proto` import works via the scaffold's `multi_proto` layout
  (already shipped in the Service Creator wizard)
- **Server reflection**: **always enabled** — every service registers
  the gRPC reflection service alongside its business RPCs
- **Discovery**: Consul-resolver pattern — gRPC channels resolve
  service names against Consul rather than hardcoded host:port
  (matches ADR-023's gossip-cluster model)
- **Streaming**: server-streaming RPCs for "stream telemetry to *this*
  client"; broadcast/fan-out goes to Kafka instead (ADR-027)
- **Code generation**: `protoc` + `grpc_cpp_plugin` / `grpcio-tools`,
  driven by the scaffold generator.  Output checked in (not built on
  the fly) so consumers don't need protoc to use a service

Why each commitment:

| Commitment | Why |
|---|---|
| HTTP/2 protobuf | Compact wire format, widespread tool support |
| Reflection on | Powers the GUI's API Explorer, dynamic clients, ad-hoc `grpcurl` debugging.  Cost is negligible (~50KB of metadata per service) |
| Consul resolver | Decouples client from server placement — same code works in single-host dev and multi-node cluster |
| Generated code checked in | Avoids "consumer needs protoc" friction; .proto + generated code reviewed together |

## Consequences

### Positive

- **Single canonical answer** to "how do I make a service?" — no
  per-team variation
- **Reflection-driven debugging** — the API Explorer tab and
  `grpcurl <addr> list` both work against any service without a
  client SDK
- **Strong contracts** — protobuf forces schema discipline; no
  "what's in this JSON blob?" ambiguity that RabbitMQ had
- **First-class streaming** — server-streaming covers most "long
  query" cases without needing a custom protocol
- **Wide ecosystem** — gRPC clients exist for every language Bosch
  uses (C++, Python, Go, Robot Framework)

### Negative

- **Steeper learning curve than REST** — operators need protoc,
  generated code, channels.  Mitigated by scaffold templates that
  hide most of it
- **HTTP/2 quirks** — proxies/load balancers need HTTP/2 awareness;
  some legacy network kit doesn't terminate HTTP/2 cleanly
- **Reflection has a cost** — exposing every method's schema makes
  fingerprinting easier.  Disable in production if security review
  flags it (env var hook in `ServiceRunner` already exists)

### Neutral

- This does not preclude REST/HTTP for *external* boundaries.  The
  FastAPI bridge is HTTP/JSON for browser consumption, calling
  internal gRPC services.  External integrations can do the same

## Alternatives Considered

### 1. REST + JSON Schema (Rejected)

Familiar, but:
- No streaming support comparable to gRPC's
- JSON Schema is weaker than protobuf at evolution discipline
- Reflection / discovery story is ad-hoc (OpenAPI helps but isn't
  universal)

### 2. Thrift / Cap'n Proto (Rejected)

Both are technically credible.  Rejected because:
- Smaller ecosystems than gRPC
- TA reference uses gRPC — staying consistent reduces cognitive load
- gRPC's reflection is more polished

### 3. RabbitMQ / AMQP (Rejected — already superseded)

What ADR-016/017/018 documented superseding.  gRPC won that contest.

### 4. Custom binary protocol (Rejected)

Considered briefly during the migration.  Rejected because reinventing
HTTP/2 framing and flow control is a multi-quarter project with no
upside over gRPC.

## References

- Reference architecture:
  [`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
- [`docs/diagrams/sequence_communication.puml`](../diagrams/sequence_communication.puml) — end-to-end gRPC + Consul flow
- [`docs/diagrams/sequence_rpc.puml`](../diagrams/sequence_rpc.puml) — unary + server-streaming
- Supersedes (consolidates) the rationale in:
  - [ADR-016 RabbitMQ as message broker](016-rabbitmq-as-message-broker.md)
  - [ADR-017 svc/api naming convention](017-svc-api-naming-convention.md)
  - [ADR-018 Alias routing design](018-alias-routing-design.md)
  - [ADR-020 Exchange topology design](020-exchange-topology-design.md)
- Related: [ADR-023 Multi-node Consul cluster](023-multi-node-consul-cluster.md) — Consul-resolver dependency
- Related: [ADR-027 Kafka event bus](027-kafka-event-bus-alongside-grpc.md) — companion async substrate
- gRPC server reflection: <https://grpc.io/docs/guides/reflection/>
