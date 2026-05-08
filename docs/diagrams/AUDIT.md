# Diagrams audit (post-migration alignment)

**Status**: 14 files moved into [`_archive/`](_archive/README.md) (2026-05-07).
Refresh / Update batches still pending; verdicts below reflect the
post-move layout.

**Reference architecture**: TA repo at
[`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
(Bosch internal GitHub).  Note: the source PUML files referenced
during this audit (component, class_service, sequence_startup,
sequence_shutdown, sequence_robot_test, state_lifecycle,
flow_full_pipeline) lived in a working copy that hadn't been pushed
upstream yet.  Treat that file list as a snapshot of the design
intent, not a path you can `git clone` and find.

**New canonical diagram** introduced by this audit:
[`00_canonical_architecture.puml`](00_canonical_architecture.puml) —
adapted from the TA reference's `01_component_diagram.puml`.  Every
ASCII / `architecture.puml` reference in `docs/architecture.md` should
point at this going forward.

## Verdict legend

| Verdict | Meaning |
|---|---|
| **Active** | Still describes current behaviour; keep |
| **Active — refresh** | Diagram is correct but uses old terms (broker → Consul, hub → Nomad). Surface-level renaming |
| **Update** | Topic is current but the diagram drifted; redraw to match the new architecture |
| **Archive** | Pre-migration concept (RabbitMQ, ServiceRegistry, LocalHubManager, Fleet Orchestrator). Move to `_archive/` so refs aren't broken but no one looks at them |
| **Replace** | Concept survives but the diagram is structurally wrong; new diagram needed |

## Per-diagram disposition

### Topology / overview

| File | Verdict | Why |
|---|---|---|
| `architecture.puml` | **Replace** by `00_canonical_architecture.puml` | Old top-level architecture diagram — pre-multi-node-cluster era |
| `architecture_overview.puml` | **Replace** by `00_canonical_architecture.puml` | Duplicate of above |
| `overview.puml` | **Replace** by `00_canonical_architecture.puml` | Same |
| `component.puml` + `component.puml.hq.puml` | **Archive** | Old component layout; HQ variant looks like a deduped duplicate. Both pre-Consul/Nomad |
| `00_canonical_architecture.puml` | **Active** (NEW) | Multi-node Consul + Nomad cluster, wrapper layer, gRPC + Kafka |
| `component.puml` | ✅ **New 2026-05-08** | Per-workload component diagram modeled on TA `01_component_diagram.puml`. Sibling of the canonical-architecture diagram: same layers, but zoomed in on one service process (Settings → Runner → Adapter → Domain → DevicePort) so the hexagonal wiring is visible |

### Class diagrams (hexagonal)

| File | Verdict | Why |
|---|---|---|
| `class_domain.puml` | ✅ **Rewritten 2026-05-08** | Modeled on the TA reference's `02_class_diagram_service.puml`. Now shows the framework's actual current domain: `BaseServiceSettings`, `ServiceRunner`, `ConsulRegistration`, `ServiceClient<T>` + per-service hexagonal layers (Configuration / Framework runtime / Domain / driving + driven adapters / composition root). Old broker-era `ServiceBase` / `ServiceRegistry` view dropped — it had become misleading |
| `class_ports.puml` | ✅ **Updated 2026-05-07** | Now leads with HubManagerPort + UIBridgePort; TransportPort / ServiceRegistryPort visibly stereotyped `<<legacy>>` |
| `class_adapters.puml` | ✅ **Updated 2026-05-07** | Adds `adapters.nomad_hub` (NomadHubAdapter / NomadClient), `adapters.grpc_bridge` (GrpcReflectClient / LocalProtoClient), `adapters.scaffold` packages; broker / local_hub adapters retained as `<<legacy>>`; FastAPIBridge surface lists /api/consul, /api/nomad, /api/grpc |

### Fleet / Hub (legacy orchestrator)

| File | Verdict | Why |
|---|---|---|
| `component_fleet.puml` | **Archive** | Fleet Orchestrator → Nomad cluster (ADR-015 Supersede) |
| `component_local_hub.puml` | **Archive** | LocalHubManager → Nomad (ADR-010 Archive) |
| `sequence_fleet_connect.puml` | **Archive** | Fleet UI lifecycle, gone |
| `sequence_fleet_disconnect.puml` | **Archive** | Same |
| `sequence_hub_restart_fleet_reconnect.puml` | **Archive** | Same |
| `sequence_hub_stop_fleet_autodisconnect.puml` | **Archive** | Same |
| `sequence_realtime_update.puml` | **Archive** | Was about ServiceRegistry → GUI realtime push (RabbitMQ-era). Consul polling replaces it |
| `sequence_service_import.puml` | **Archive** | "Service import" was the LocalHubManager mechanism (ADR-011) |

### Communication (gRPC era — keep + refresh)

| File | Verdict | Why |
|---|---|---|
| `sequence_communication.puml` | ✅ **Updated 2026-05-07** | Now shows gRPC + Consul + reflection (was: RabbitMQ AMQP) |
| `sequence_rpc.puml` | ✅ **Updated 2026-05-07** | Now shows gRPC unary + server-streaming with Consul-resolver channel pool |
| `sequence_registration.puml` | ✅ **Updated 2026-05-07** | Now shows Nomad raw_exec → wrapper → ServiceRunner → Consul register |
| `sequence_shutdown.puml` | ✅ **Updated 2026-05-07** | Now shows Nomad signals → ServiceRunner Server::Shutdown → Consul deregister |
| `state_process_lifecycle.puml` | ✅ **Refreshed 2026-05-08** | Title now says "Service Lifecycle (Nomad job + ServiceRunner)". Stopping phases relabelled to "Nomad signal" → "Drain gRPC" → "Force kill". Notes mention Consul deregister + kill_timeout. Legend keys point at ServiceRunner / NomadHubAdapter / wrapper |

### Routing / aliasing (legacy)

| File | Verdict | Why |
|---|---|---|
| `sequence_alias.puml` | **Archive** | Alias routing died with RabbitMQ (ADR-018 Supersede) |

### Qt + GUI templates (still relevant)

| File | Verdict | Why |
|---|---|---|
| `component_qt_service_templates.puml` | ✅ **Refreshed 2026-05-08** | Business-API row labels now say "gRPC servicer + Settings" / "main.cpp + ServiceRunner" instead of `: ServiceBase`. Shared-infra row replaces RabbitMQ with the Consul cluster + bridge endpoint surface |
| `component_qt_template_qml.puml` | **Active** | QML template still emitted by scaffold |
| `component_qt_template_wasm.puml` | **Active** | WASM template still emitted |
| `component_qt_template_widget.puml` | **Active** | Qt Widgets template still emitted |
| `component_flow_qt_ui_loading.puml` | ✅ **Refreshed 2026-05-08** | Backend row replaces RabbitMQ + AMQP publish path with FastAPI → GrpcReflectClient (Consul resolver) → gRPC service. Request payload: `consul_addr` in place of `broker_url` |
| `flow_gui_loading_tiers.puml` | **Active** | 3-tier loading (HTML / QML / WASM) — still valid (ADR-021) |
| `gui_architecture.puml` | ✅ **Refreshed 2026-05-08** | "RabbitMQ Brokers" replaced with "Cluster A / B" boxes (Consul agents + Nomad server + gRPC services). REST endpoints relabeled to /api/grpc, /api/consul, /api/nomad, /api/scaffold. "Multi-Broker State" → "Multi-cluster State" with consul_addr in connection records. Module names refreshed (LocalHubClient → NomadClient, ServiceNetwork) |
| `qml-shell-lifecycle.md` | **Active** | Markdown notes (not a PUML diagram); still describes current QML behavior |

### QML deep-dive (still relevant)

| File | Verdict | Why |
|---|---|---|
| `sequence_gui_plugin_loading.puml` | **Active** | GUI plugin loading mechanism (ADR-019) still in place |
| `sequence_gui_qml_wasm_loading.puml` | **Active** | Same |
| `sequence_qml_first_load.puml` | n/a | Not in tree |
| `sequence_qml_service_call.puml` | ✅ **Refreshed 2026-05-08** | Backend leg rewritten: ServiceClient → /api/grpc/<svc>/<method> → GrpcReflectClient → Consul resolve → gRPC. Method name example switched from svc_api_hello to Greet (proto-style). Error-path note refers to gRPC status codes |
| `sequence_qml_shell_cleanup.puml` | **Active** | QML shell teardown sequence |
| `sequence_qml_shell_first_load.puml` | **Active** | QML shell init |
| `sequence_qml_shell_switch.puml` | **Active** | QML shell service-switch flow |
| `sequence_qml_string_marshaling.puml` | **Active** | C++ ↔ QML string marshaling — implementation detail still applies |

## Summary

| Verdict | Count |
|---|---|
| Active (no change) | 10 |
| Active — refresh | 1 |
| Updated 2026-05-07 | 6 |
| Refreshed 2026-05-08 | 5 |
| Rewritten 2026-05-08 | 1 |
| New 2026-05-08 | 1 |
| Archive | 11 |
| Replace (by canonical) | 3 |
| **Total** | 38 |

## Suggested cleanup order

1. **Land the canonical diagram** (already done — see
   `00_canonical_architecture.puml`).  Update `docs/architecture.md` to
   reference it and demote the old `architecture.puml` /
   `overview.puml` to "see canonical".
2. **Archive batch** — move the 11 Archive files into a new
   `_archive/` subfolder.  Add a `_archive/README.md` explaining the
   pre-migration era.  ~15 min.
3. **Update batch** — redraw the 4 sequence diagrams whose topic
   survived but the content drifted (`sequence_communication`,
   `sequence_rpc`, `sequence_registration`, `sequence_shutdown`).
   ~1 hour.
4. **Refresh batch** — wording-only tweaks on the 8 "Active — refresh"
   files (e.g., "broker" → "Consul").  ~30 min.
5. **Render to PNG** — re-run the PlantUML build so the imgs in
   `docs/imgs/` and `docs/_legacy/` reflect the changes.  Verify links
   from `architecture.md` / READMEs aren't broken.

## Render status (2026-05-08)

- All 24 live PUMLs in `docs/diagrams/` were re-rendered with PlantUML
  1.2021.01 (`D:/Installer/Robotframework/rpa_framework/project/plantuml.jar`).
  Output PNGs land in [`docs/imgs/`](../imgs/) with matching basenames.
- `!theme plain` directives were stripped from the diagrams that had
  them (the directive is a no-op cosmetic and isn't recognised by older
  PlantUML versions; removing it widens compatibility).
- Stale rendered PNGs from archived/replaced diagrams were moved to
  [`docs/imgs/_archive/`](../imgs/_archive/) (16 files).  No live
  Markdown / HTML references survived to those names — checked via
  grep.
- Live references in the following docs were updated to point at the
  current diagram set: `README.md`, `docs/adr/README.md`,
  `docs/adr/001-hexagonal-architecture.md`.  References inside
  `docs/_legacy/` were left as-is — that tree is itself archive
  material.

To re-render in the future:

```bash
cd docs/diagrams
java -jar /path/to/plantuml.jar -tpng -o ../imgs *.puml
```
