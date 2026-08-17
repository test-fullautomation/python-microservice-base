# ADR-023: Multi-node Consul cluster with serf gossip

## Status

Proposed

## Date

2026-05-07

## Author

Audit follow-up (post-migration alignment).  Aligns with the TA
architecture-proposal design at
[`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal).

## Reviewer

- (pending)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-05-07 | 1.0 | Initial draft |

## Context

ADR-003 (Custom Service Registry over ZooKeeper) was superseded by a
single Consul agent in dev mode.  That works for one-machine
walkthroughs but doesn't reflect the production topology in the TA
reference architecture, which runs multiple Consul agents that
gossip-replicate the catalog.

Real test labs have:

- 3+ machines hosting different hardware (PPS, signal generators,
  scopes, HIL boxes).  Each runs at least one service.
- A central Manager-GUI / orchestration host that needs to see *every*
  service across the lab.
- A requirement to keep working if any one machine reboots.

A single Consul agent makes that machine a single point of failure for
the entire catalog.  Worse, the GUI's `/api/consul/...` endpoints
wouldn't return services that registered at a different agent it
doesn't know about.

## Decision

Adopt a **multi-node Consul cluster with serf gossip**, mirroring the
TA reference design:

- **3 Consul agents minimum** (servers; raft-replicated catalog).
  Production may add more.
- Each Nomad client (workload host) runs a **local Consul agent** in
  client mode and joins the gossip ring.  Services register with
  *their local* agent (lower latency, survives partitions of the
  central servers).
- The Manager GUI / FastAPI bridge can connect to **any** Consul agent
  to read the catalog — gossip ensures convergence within seconds.

```
                          Consul cluster (gossip + raft)
                  ┌───────────┬───────────┬───────────┐
                  │  agent 1  │  agent 2  │  agent 3  │
                  │  :8500    │  :8501    │  :8502    │
                  └───────────┴───────────┴───────────┘
                        ▲           ▲           ▲
                        │  serf gossip          │
                        │           │           │
                  ┌─────┴─────┐ ┌──┴──┐  ┌─────┴─────┐
                  │ Service A │ │ Svc │  │ Manager   │
                  │ registers │ │ B   │  │ GUI       │
                  │ here      │ │     │  │ reads any │
                  └───────────┘ └─────┘  └───────────┘
```

The full picture — including each Nomad client paired with its own
Consul agent — is in
[`docs/diagrams/00_canonical_architecture.puml`](../diagrams/00_canonical_architecture.puml).

## Consequences

### Positive

- **No single point of failure** for service discovery — losing one
  agent doesn't lose the catalog
- **Local registration is fast** — services hit `127.0.0.1:8500` to
  register; no cross-machine RTT on the hot path
- **Gossip handles network partitions gracefully** — when the partition
  heals, agents re-converge
- **Manager GUI can connect to any agent** — operationally resilient

### Negative

- **More agents to operate** — 3+ processes to keep alive vs. one
- **Catalog convergence isn't instantaneous** — gossip takes seconds to
  propagate a new registration cluster-wide.  For tight timing tests,
  the GUI may need to poll the agent that hosts the registering service
- **Cluster bootstrap is non-trivial** — initial server election + ACL
  setup vs. `consul agent -dev`

### Neutral

- Manager GUI's existing multi-cluster connection support (ADR-007,
  refreshed) maps well to the multi-Consul case — same UX, just
  multiple agents instead of multiple brokers

## Alternatives Considered

### 1. Single dev-mode agent (Rejected)

This is the current default and what scaffold-generated services
register against by default.

Rejected because:
- Single point of failure
- Doesn't match the TA reference / production topology
- Doesn't scale beyond one workload machine

### 2. Etcd or ZooKeeper (Deferred)

Both are alternatives to Consul for distributed KV / discovery.

Deferred because:
- Consul is already deployed (ADR-003 supersession)
- Consul's HTTP API + health check model is simpler than ZK's
  ephemeral-node pattern
- Switching now incurs migration cost without a clear win

## References

- Reference architecture:
  [`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
- [`docs/diagrams/00_canonical_architecture.puml`](../diagrams/00_canonical_architecture.puml)
- Consul gossip protocol: <https://developer.hashicorp.com/consul/docs/architecture/gossip>
- Supersedes the discovery aspect of [ADR-003](003-service-registry-over-zookeeper.md)
- Related: [ADR-024 Multi-node Nomad cluster](024-multi-node-nomad-cluster.md)
