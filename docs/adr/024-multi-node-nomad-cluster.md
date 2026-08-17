# ADR-024: Multi-node Nomad cluster

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

[ADR-022](022-nomad-orchestrator-integration.md) introduced Nomad as
the replacement for the LocalHubManager (ADR-010, archived).  That ADR
covered "what is Nomad and why use it" but assumed a single-agent dev
configuration.  The TA reference architecture and any production lab
runs **multiple Nomad clients** so different services can run on
different hardware (e.g. the PPS service on the box wired to the power
supply, the scope service on the box wired to the oscilloscope).

Open questions left by ADR-022:

- How do multiple Nomad clients coordinate?
- Where does the Nomad **server** live, and how many do we run?
- How do jobs get pinned to specific machines (when a service must run
  on the box with the hardware)?
- What happens when a client disconnects?

## Decision

Adopt a **Nomad cluster with one server (or 3 for HA) and N clients**,
matching the TA reference:

- **1 Nomad server** in single-host labs; **3 servers (raft quorum)**
  for fault tolerance in production.
- **N Nomad clients**, one per workload machine.  Each client runs the
  `raw_exec` driver and gets paired with a local Consul agent
  (see [ADR-023](023-multi-node-consul-cluster.md)).
- **Client constraints** in the job HCL pin services to specific
  machines using node attributes (`${attr.unique.hostname}`,
  `${meta.has_pps}`, etc.) — same mechanism Nomad uses for any
  cluster.
- Manager GUI's `/api/nomad/*` endpoints talk to the **server**, not
  individual clients — the server handles scheduling.

```
                  ┌──────────────────────┐
                  │  Nomad server :4646  │
                  │  (scheduler + UI)    │
                  └──────────┬───────────┘
                             │ register + heartbeat
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌────────────┐ ┌────────────┐ ┌────────────┐
       │ client 1   │ │ client 2   │ │ client 3   │
       │ raw_exec   │ │ raw_exec   │ │ raw_exec   │
       │ + Consul 1 │ │ + Consul 2 │ │ + Consul 3 │
       └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
             │              │              │
       ┌─────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
       │ Service A  │ │ Service B  │ │ Service C  │
       │ (PPS box)  │ │ (scope box)│ │ (HIL box)  │
       └────────────┘ └────────────┘ └────────────┘
```

Job HCL example for hardware pinning:

```hcl
job "pps_service" {
  constraint {
    attribute = "${meta.has_pps}"
    value     = "true"
  }
  group "pps" { task "server" { driver = "raw_exec" ... } }
}
```

Operators set `meta.has_pps = "true"` on the Nomad client config of
the machine that owns the power supply.  Nomad's scheduler does the
rest — no hand-rolled fleet logic.

## Consequences

### Positive

- **Hardware-aware scheduling** — services pinned to the machine that
  has the device.  Was previously hand-coded in LocalHubManager
  configs
- **Failover free** — if a client disconnects, Nomad reschedules
  rescheduling-eligible jobs onto another client (best-effort; many
  hardware-bound jobs can't migrate, but software-only ones can)
- **GUI sees the whole lab** — the Service Network tab pulls from the
  Nomad server's `/v1/jobs` and `/v1/nodes`
- **Standard Nomad UX** — operators familiar with Nomad don't have to
  learn a custom orchestrator

### Negative

- **More moving parts** — server + N clients vs. a single dev agent
- **Client config divergence is a real risk** — if `meta.has_pps =
  true` is set on two machines by mistake, Nomad picks one arbitrarily.
  Operators need a config-distribution discipline (Ansible, manual
  audit, or a checked-in `nomad/` config tree like the TA reference has)
- **Network partitions** can split the cluster — clients re-join when
  partition heals; jobs in flight may get killed and rescheduled

### Neutral

- The Manager GUI's existing Nomad tab works against a multi-client
  cluster without changes — it talks to the server, not clients

## Alternatives Considered

### 1. Single dev-mode agent (Rejected for production)

Fine for one-laptop walkthroughs and CI smoke tests.

Rejected for production because the lab has multiple physical
machines wired to different hardware; a single agent can't span them.

### 2. Kubernetes (Rejected)

K8s is the obvious "industry standard" for orchestration.

Rejected because:
- `raw_exec` on Windows is the killer feature (lab boxes are Windows);
  K8s' Windows support is comparatively weak
- K8s assumes containerised workloads; many of our services use
  proprietary Windows-only device drivers that don't containerise
  cleanly
- K8s adds a control-plane operations burden the lab doesn't need

### 3. Custom Fleet Orchestrator (Rejected, see ADR-015 supersession)

Was the original plan.  Replaced by Nomad in the migration.

## References

- Reference architecture:
  [`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
- [`docs/diagrams/00_canonical_architecture.puml`](../diagrams/00_canonical_architecture.puml)
- [ADR-022 Nomad Orchestrator Integration](022-nomad-orchestrator-integration.md) — establishes Nomad as the orchestrator
- [ADR-023 Multi-node Consul cluster](023-multi-node-consul-cluster.md) — discovery side of the same topology
- Supersedes [ADR-015 Fleet Orchestrator architecture](015-fleet-orchestrator-architecture.md)
- Nomad constraints: <https://developer.hashicorp.com/nomad/docs/job-specification/constraint>
