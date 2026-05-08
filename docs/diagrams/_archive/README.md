# Archived diagrams (pre-migration era)

These PlantUML diagrams describe **architecture and runtime mechanisms
that no longer exist** in the current codebase.  They are kept here for:

- **Git archaeology** — when reading old commits or migration PRs.
- **Migration reference** — for downstream forks that haven't migrated yet.
- **Historical record** — so the design intent of the old system isn't lost.

If you're trying to understand the **current** architecture, do **not**
read these.  Read [`00_canonical_architecture.puml`](../00_canonical_architecture.puml)
+ [`../../architecture.md`](../../architecture.md) instead.

## Why each one was archived

| File | Pre-migration role | Replaced by | ADR |
|---|---|---|---|
| `architecture.puml` | Old top-level architecture diagram (single Consul, single Nomad, no wrapper) | [`00_canonical_architecture.puml`](../00_canonical_architecture.puml) | — |
| `architecture_overview.puml` | Duplicate of the above | [`00_canonical_architecture.puml`](../00_canonical_architecture.puml) | — |
| `overview.puml` | Same — third overview duplicate | [`00_canonical_architecture.puml`](../00_canonical_architecture.puml) | — |
| `component.puml` | Pre-Consul/Nomad component layout | [`00_canonical_architecture.puml`](../00_canonical_architecture.puml) | — |
| `component.puml.hq.puml` | Higher-quality variant of `component.puml` | [`00_canonical_architecture.puml`](../00_canonical_architecture.puml) | — |
| `component_fleet.puml` | Fleet Orchestrator topology | Nomad cluster | [ADR-015](../../adr/015-fleet-orchestrator-architecture.md) → [ADR-022](../../adr/022-nomad-orchestrator-integration.md) |
| `component_local_hub.puml` | LocalHubManager process supervisor | Nomad `raw_exec` jobs | [ADR-010](../../adr/010-local-hub-manager.md) → [ADR-022](../../adr/022-nomad-orchestrator-integration.md) |
| `sequence_fleet_connect.puml` | Fleet UI lifecycle (connect) | Manager GUI Service Network tab + Consul HTTP | [ADR-015](../../adr/015-fleet-orchestrator-architecture.md) |
| `sequence_fleet_disconnect.puml` | Fleet UI lifecycle (disconnect) | Same | [ADR-015](../../adr/015-fleet-orchestrator-architecture.md) |
| `sequence_hub_restart_fleet_reconnect.puml` | Fleet auto-reconnect on hub restart | Nomad rescheduling + Consul re-discovery | [ADR-015](../../adr/015-fleet-orchestrator-architecture.md) |
| `sequence_hub_stop_fleet_autodisconnect.puml` | Fleet auto-disconnect on hub stop | Same | [ADR-015](../../adr/015-fleet-orchestrator-architecture.md) |
| `sequence_realtime_update.puml` | ServiceRegistry → GUI realtime push (RabbitMQ-era) | Consul polling + TTL deregistration | [ADR-012](../../adr/012-registry-shutdown-notification.md) |
| `sequence_service_import.puml` | LocalHubManager `import-service` REST endpoint | Nomad job submission | [ADR-011](../../adr/011-service-import-with-module-execution.md) → [ADR-022](../../adr/022-nomad-orchestrator-integration.md) |
| `sequence_alias.puml` | Alias routing via ServiceRegistry (RabbitMQ workaround) | gRPC fully-qualified method names + reflection | [ADR-018](../../adr/018-alias-routing-design.md) |

Total: **14 files** archived 2026-05-07.

See [`../AUDIT.md`](../AUDIT.md) for the full triage including diagrams
that stayed in `docs/diagrams/` but need refresh / update.
