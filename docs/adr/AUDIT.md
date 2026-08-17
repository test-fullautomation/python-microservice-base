# ADR audit (post-migration alignment)

**Status**: triage list — verdicts proposed, not yet applied to the ADR
files themselves.  Edit this file (or override individual rows) before
the follow-up rewrite pass touches the actual ADRs.

**Reference architecture**: the canonical TA architecture lives at
[`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
(Bosch internal GitHub).  Key shifts vs. the ADRs below:

- **Multi-node Nomad cluster**: server + N clients (was: single dev agent)
- **Multi-node Consul cluster**: 3 agents with serf gossip; each Nomad
  client paired with its own Consul agent (was: single Consul agent)
- **Wrapper layer** spawns service processes via `raw_exec`
  (was: direct `raw_exec` of the binary)
- **uv** package manager for Python service environments (was: `pip`
  with editable installs)
- **Kafka event bus** for streaming/async (alongside gRPC; was: gRPC only)
- **Robot Framework + grpcurl** as primary test clients
  (was: Manager GUI as primary)
- The Manager GUI is **still relevant** as an operations console but
  is no longer the only entry point.

## Verdict legend

| Verdict | Meaning |
|---|---|
| **Active** | Decision still holds; no changes needed |
| **Active — minor refresh** | Decision holds; needs date / wording update or a "Reaffirmed" note |
| **Supersede** | Decision is invalid post-migration; replace with a new ADR (link in `Superseded by` field) |
| **Archive** | Decision is purely historical; mark `Archived` and stop linking from current docs |
| **Rewrite** | Topic still relevant but content drifted enough that a fresh ADR is cleaner than patching |
| **Needs new ADR** | Concept has no ADR yet; one needs to be written |

## Per-ADR disposition

| # | Title | Verdict | Why / what to do |
|---|---|---|---|
| 000 | template | **Active** | Keep as-is — used for new ADRs |
| 001 | Hexagonal Architecture | **Active — minor refresh** | Pattern unchanged; refresh wording so examples reference the gRPC + Consul + Nomad adapters (not RabbitMQ + ServiceRegistry). Add a "Reaffirmed 2026-05" note |
| 002 | Factory Pattern for DI | **Active — minor refresh** | Same as 001. The pattern survived the migration; refresh examples to match current `factory.py` |
| 003 | Custom Service Registry over ZooKeeper | **Supersede** | Already implicitly superseded by Consul. Replace with `Superseded by ADR-NNN-consul-cluster-service-discovery` (the new ADR for multi-Consul + serf) |
| 004 | Electron over Qt for GUI | **Active** | Decision still applies to MicroserviceManagerGUI; no change |
| 005 | Dual-Host GUI (Electron + Browser) | **Active** | Same — both modes still supported |
| 006 | FastAPI Bridge for Browser GUI | **Active — minor refresh** | Bridge still exists; refresh "uses subprocess agents" to match the current Consul + Nomad lifecycle endpoints |
| 007 | Multi-Broker Connection Architecture | **Rewrite** as **Multi-Cluster Connection Architecture** | The pattern (multiple connections in the GUI) is still needed but the connection target changed: was multiple RabbitMQ brokers, is now multiple Consul clusters. Same UX, completely different backend |
| 008 | Electron Bridge Lifecycle Decoupling | **Active** | Pattern still holds; the bridge process is decoupled from Electron in both modes |
| 009 | Service Executor with RPC Graceful Shutdown | **Supersede** | The "Service Executor" was internal to LocalHubManager. Now Nomad owns lifecycle; graceful shutdown is via SIGBREAK (Windows) / SIGTERM (Linux). Replace with new ADR `Graceful shutdown via Nomad signals` |
| 010 | Local Hub Manager | **Archive** | LocalHubManager is gone; Nomad replaces it entirely. Mark `Archived 2026-05` with link to ADR-022 |
| 011 | Service Import with Module Execution | **Archive** | The "service import" mechanism died with LocalHubManager. Service binaries are now packaged + Nomad-launched. Mark `Archived 2026-05` |
| 012 | Registry Shutdown Notification | **Archive** | Was about ServiceRegistry → GUI notification. Consul handles this transparently via TTL-based deregistration; no app-level notification needed |
| 013 | Windows Process Lifecycle Fixes | **Active** | The fixes (SIGBREAK handling, subprocess.PIPE blocking, etc.) still apply to wrapper.py + ServiceRunner. Keep with a "Still in effect under wrapper architecture" footnote |
| 014 | Config Placeholder Persistence | **Active** | The `${python}` / `${config_dir}` pattern lives on in `prep_nomad_paths.bat` (project README explicitly references this). Keep |
| 015 | Fleet Orchestrator Architecture | **Supersede** | Fleet Orchestrator → Nomad + Consul cluster. Replace with new ADR `Multi-node Nomad + Consul cluster` |
| 016 | RabbitMQ as Message Broker | **Supersede** | Already noted as superseded in the changelog; needs an explicit `Superseded by` link to a new `gRPC over HTTP/2 as primary transport` ADR (could merge with 020) |
| 017 | svc_api_ Naming Convention | **Supersede** | Replaced by gRPC method names (PascalCase). New ADR: `gRPC method naming + reflection over name conventions` |
| 018 | Alias Routing Design | **Supersede** | Alias routing is gone — gRPC method addressing replaces it. Mark superseded with link to ADR-016 successor |
| 019 | Service-Delivered GUI Plugins | **Active** | The pattern of services dropping HTML/JS into `web/services/` still works; refresh wording to mention `mb-scaffold` emits these |
| 020 | Exchange Topology Design | **Archive** | Pure RabbitMQ exchange topology — irrelevant under gRPC. Mark `Archived 2026-05` |
| 021 | Multi-Tier GUI Loading | **Active — minor refresh** | The 3-tier GUI loading (HTML / QML / WASM) still applies in the scaffold generator. Reference the multi_proto layout in examples |
| 022 | Nomad Orchestrator Integration | **Active → Accepted** | Status is currently "Proposed". With the migration done, change to "Accepted" and link to the new ADR for multi-node cluster |

## New ADRs needed

These topics are currently undocumented but are core to the new architecture:

| Proposed # | Title | Topic |
|---|---|---|
| 023 | Multi-node Consul cluster with serf gossip | 3-Consul-agent topology, each paired with a Nomad client, gossip-based catalog convergence |
| 024 | Multi-node Nomad cluster | Server + N clients, raw_exec on Windows, GitHub Actions / CI integration story |
| 025 | Wrapper layer for `raw_exec` workloads | Why `wrapper.py` exists between `raw_exec` and the service process; PATH / env setup; uv venv activation |
| 026 | uv-based Python service environments | Per-service `pyproject.toml` + `uv.lock`; isolation guarantees; CI reproducibility |
| 027 | Kafka event bus alongside gRPC | When to use Kafka (streaming, async fan-out) vs. gRPC (request/response); topic naming; consumer groups |
| 028 | gRPC + reflection as primary RPC layer | Replaces ADR-016/017/018: reflection for discovery, gRPC method names for addressing, no broker |
| 029 | Robot Framework as primary test client | `grpc_api_keywords.py`, Consul-driven discovery, replaces Manager-GUI-only test flow |

Six of these (023–028) are direct replacements for superseded ADRs;
029 documents a workflow that was previously informal.

## Suggested next steps

1. **Review this audit** — override any verdicts you disagree with.
2. **First rewrite batch** — header + status updates for the eight
   "Supersede" / "Archive" verdicts.  Mechanical edits, ~30 min.
3. **New ADR drafts** — write 023–028 in skeleton form (Context /
   Decision / Consequences) referencing the TA architecture.  ~2–3
   hours.
4. **Active-with-refresh batch** — touch up wording in 001, 002, 006,
   007, 019, 021.  ~30 min.
5. **Cross-link audit** — make sure every superseded ADR has a
   `Superseded by ADR-NNN` line at the top, every archived ADR points
   at the section of the changelog that explains the why.

Total follow-up effort after this audit: **~4 hours focused editing**.
