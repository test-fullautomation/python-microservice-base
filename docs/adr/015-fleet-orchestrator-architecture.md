# ADR-015: Fleet Orchestrator for Multi-Hub Process Management

## Status

Accepted

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

In test automation and distributed development environments, microservices often
run on multiple machines (e.g. HIL benches, build servers, developer desktops).
Each machine has its own ProcessHub managing local service processes (ADR-010).

Without fleet coordination, each hub is an isolated island:

- No centralized view of which services run on which machine
- No remote process control (must SSH/RDP into each machine)
- No health monitoring across the fleet
- No way for the GUI to manage multiple hubs from a single dashboard

The question is: how should we coordinate processes across multiple hubs?

### Candidates

| Approach | Description |
|----------|-------------|
| **Custom Fleet Orchestrator** | Purpose-built orchestrator using the existing RabbitMQ infrastructure |
| **Kubernetes** | Container orchestration platform |
| **Ansible / Salt** | Configuration management and remote execution |
| **Consul + Nomad** | Service discovery + job scheduler |

## Decision

Build a custom **Fleet Orchestrator** with a centralized hub-agent topology,
communicating over RabbitMQ via EventBus transport.

### Architecture

```
┌─────────────────────────────────────────────────────┐
│              Orchestrator Hub (Machine A)             │
│                                                       │
│  FleetOrchestrator ── HubRegistry ── FleetWebAPI     │
│         │                                  │          │
│         │ (EventBus)              (REST :2510)        │
│  ProcessHubServer (local)         GUI / API clients   │
│  Self-Agent (heartbeat)                               │
└───────────────────────┬─────────────────────────────┘
                        │
                  RabbitMQ (AMQP)
            Exchange: process_hub_fleet
                        │
         ┌──────────────┴──────────────┐
         │                             │
         ▼                             ▼
┌─────────────────┐          ┌─────────────────┐
│  Agent Hub (B)  │          │  Agent Hub (C)  │
│                 │          │                 │
│  HubAgent       │          │  HubAgent       │
│  ProcessHub     │          │  ProcessHub     │
│  ServiceExec    │          │  ServiceExec    │
└─────────────────┘          └─────────────────┘
```

### Three Operating Modes

`LocalHubManager.start_hub(mode=...)` supports:

| Mode | Components Started | Use Case |
|------|-------------------|----------|
| **standalone** | ProcessHubServer only | Single machine, no fleet |
| **agent** | ProcessHubServer + HubAgent | Joins a remote orchestrator |
| **orchestrator** | ProcessHubServer + FleetOrchestrator + FleetWebAPI + Self-Agent | Central coordinator |

### Message Flow

Communication uses RabbitMQ topic exchange (`process_hub_fleet`) with routing
keys:

| Routing Key | Direction | Purpose |
|-------------|-----------|---------|
| `fleet.hub.announce` | Agent → Orchestrator | Hub joins fleet |
| `fleet.hub.{hub_id}.heartbeat` | Agent → Orchestrator | Periodic alive signal + process snapshot |
| `fleet.hub.{hub_id}.command` | Orchestrator → Agent | Start/stop/reset commands |
| `fleet.hub.{hub_id}.status` | Agent → Orchestrator | Command result + current state |

**Command dispatch path:**

```
GUI (FleetDashboard.js)
  → POST /api/fleet/hubs/{hub_id}/start  (FleetWebAPI or bridge proxy)
    → FleetOrchestrator.dispatch_command(hub_id, "start_process", params)
      → EventBusTransport.send(routing_key="fleet.hub.{hub_id}.command")
        → HubAgent receives, checks fleet_enabled guard
          → ProcessHubServer.request_process_start(names)
            → ServiceExecutor.start(name, config)
              → Subprocess launched, PID tracked
```

### Health Monitoring

HubRegistry tracks three health states per hub:

| State | Condition |
|-------|-----------|
| **online** | Heartbeat within 30 s AND >= 80 % configured processes running |
| **degraded** | Heartbeat within 30 s AND < 80 % processes running |
| **offline** | No heartbeat for > 30 s OR all processes stopped |

**Timing parameters (configurable):**

- Heartbeat interval: 5 s (agent sends)
- Health check tick: 5 s (orchestrator evaluates)
- Offline timeout: 30 s (no heartbeat → offline)

**State transitions:**

```
                ┌──── processes recover ────┐
                ▼                           │
  ┌──────────────────┐              ┌──────────────┐
  │     ONLINE       │ ──────────── │   DEGRADED   │
  │  (>= 80% running)│  fewer procs │ (< 80% run.) │
  └──────────────────┘              └──────────────┘
           │                               │
           │  no heartbeat > 30 s          │  no heartbeat > 30 s
           │  or all stopped               │  or all stopped
           ▼                               ▼
                    ┌──────────────┐
                    │   OFFLINE    │
                    └──────────────┘
                           │
                           │ heartbeat resumes
                           ▼
                    ONLINE or DEGRADED
```

### Fleet REST API

FleetWebAPI exposes the following endpoints (default port 2510):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/fleet/status` | GET | Fleet-wide snapshot: total hubs, online count, total processes |
| `/api/fleet/hubs` | GET | List all hubs with summary |
| `/api/fleet/hubs/{id}` | GET | Hub detail: processes, connections, configs |
| `/api/fleet/hubs/{id}/start` | POST | Start processes on a remote hub |
| `/api/fleet/hubs/{id}/stop` | POST | Stop processes on a remote hub |
| `/api/fleet/hubs/{id}/reset` | POST | Stop all, restart configured processes |
| `/api/fleet/command` | POST | Generic extensible command dispatch |

### Fleet Guard

Not all processes should be remotely controllable.  Each process config has an
optional `fleet_enabled` flag:

```json
{
    "Calculator": {
        "script": "${python}",
        "args": ["-m", "calculator"],
        "fleet_enabled": true
    },
    "LocalDebugTool": {
        "script": "${python}",
        "args": ["-m", "debug_tool"],
        "fleet_enabled": false
    }
}
```

The HubAgent's command handler wraps start/stop with a guard that rejects
processes without `fleet_enabled: true`.  The GUI shows a lock icon on
non-fleet processes.

### Self-Agent Pattern

In orchestrator mode, the hub also manages its own local processes.  To appear
in the fleet dashboard alongside remote agents, it registers a **self-agent**:

```python
# In LocalHubManager._tick_loop() for orchestrator mode:

# 1. Self-agent sends heartbeat via separate EventBusTransport
#    (separate connection avoids routing conflicts with orchestrator)

# 2. Direct heartbeat shortcut: update_heartbeat() called locally
#    (avoids fragile RabbitMQ round-trip in same process)
if self._hub_id:
    self._fleet_orchestrator.registry.update_heartbeat(self._hub_id)
```

### GUI Integration

| Component | Role |
|-----------|------|
| `FleetClient.js` | Low-level API client: `getHubs()`, `startProcesses()`, `stopProcesses()`, polling |
| `FleetDashboard.js` | Hub grid cards, process lists, health dots, start/stop buttons |
| `fastapi_bridge.py` | Proxy endpoints (`/api/fleet/*`) for browser mode (browser cannot reach FleetWebAPI directly) |

**Transport modes:**
- **Electron**: FleetClient calls FleetWebAPI URL directly
- **Browser**: FleetClient calls FastAPI bridge, which proxies to FleetWebAPI

**Change detection:** Dashboard uses fingerprint hashing (ignoring volatile
fields like timestamps) to avoid unnecessary DOM re-renders during polling.

## Comparison with Third-Party Alternatives

### Requirements Matrix

| Requirement | Fleet Orchestrator | Kubernetes | Ansible/Salt | Consul+Nomad |
|-------------|-------------------|------------|--------------|--------------|
| **Uses existing RabbitMQ** (no new infrastructure) | Yes | No (etcd, API server) | No (SSH/ZMQ) | No (Consul cluster) |
| **Embeddable** (runs inside Python process) | Yes | No (cluster) | No (control node) | No (agents + servers) |
| **Process-level control** (start/stop individual services) | Yes | Pod-level | Yes (tasks) | Yes (jobs) |
| **RPC graceful shutdown** (send command to service queue) | Yes (via ServiceExecutor) | No (SIGTERM) | No (shell commands) | No (SIGTERM) |
| **GUI-integrated dashboard** | Native | External (Lens, Dashboard) | External (AWX/Tower) | External (Consul UI) |
| **Fleet guard** (per-process opt-in for remote control) | Yes | Namespace RBAC | Inventory groups | ACL policies |
| **Health monitoring** | Heartbeat (5 s) | Liveness probes | Fact gathering | Health checks |
| **Desktop/lab deployment** (no cloud, no containers) | Yes | Overkill | Possible | Possible |
| **Windows support** | Yes | Limited (WSL2) | Limited | Yes |

### Apache ZooKeeper + Custom Orchestrator (Rejected)

Use ZooKeeper for hub discovery and leader election, with a custom orchestrator
on top.

Rejected because:
- ZooKeeper provides distributed coordination but not process management
- Would still need to build the command dispatch, health aggregation, and REST API
- Adds JVM infrastructure (3+ node ensemble) for consensus we don't need — our orchestrator is a designated central node, not an elected leader
- The RabbitMQ broker already provides reliable message delivery

### Kubernetes (Rejected)

Container orchestration platform with pods, deployments, and services.

Rejected because:
- **Overkill for desktop/lab environments** — our deployment is developer machines and test benches, not cloud clusters
- **Container requirement** — services would need to be containerized; our services are plain Python processes started via `python -m`
- **No RPC shutdown** — Kubernetes sends SIGTERM to pods; our services need `svc_api_shutdown` RPC for graceful RabbitMQ unregistration (ADR-009)
- **Complex infrastructure** — requires etcd, API server, kubelet, kube-proxy
- **Poor Windows support** — Windows containers have significant limitations

### Ansible / Salt (Rejected)

Configuration management tools with remote execution capabilities.

Rejected because:
- **Push-based model** — Ansible connects via SSH, runs tasks, disconnects. No persistent health monitoring or heartbeat.
- **No real-time dashboard** — would need to build polling/WebSocket layer on top
- **No RPC shutdown** — can only execute shell commands (`kill`, `systemctl`), not application-level RPC
- **SSH requirement** — each target machine needs SSH server and key management
- **No embeddability** — runs as a control-node CLI tool, cannot be embedded inside FastAPI

### Consul + Nomad (Rejected)

HashiCorp's service discovery (Consul) + job scheduler (Nomad).

Rejected because:
- **Two separate systems** — Consul for discovery, Nomad for scheduling, each with its own agent and server cluster
- **Infrastructure overhead** — both require multi-node clusters for production reliability
- **No RPC shutdown** — Nomad uses signals and drain/preemption, not application-level RPC
- **Different communication channel** — Consul uses gossip protocol, Nomad uses its own RPC; neither uses our existing RabbitMQ

## Consequences

### Positive

- **Zero additional infrastructure** — uses the same RabbitMQ broker that services already communicate through
- **Embeddable** — orchestrator runs inside the same Python process as LocalHubManager and FastAPI bridge
- **RPC-aware** — fleet commands route through ServiceExecutor, which performs graceful RPC shutdown before signal fallback
- **GUI-native** — FleetDashboard is part of the same web GUI, with real-time polling and per-process controls
- **Fleet guard** — per-process `fleet_enabled` flag prevents accidental remote control of sensitive processes
- **Simple topology** — one designated orchestrator, N agents; no consensus algorithm, no quorum

### Negative

- **Single point of failure** — if the orchestrator crashes, fleet coordination is lost (agents continue running independently)
- **No automatic failover** — orchestrator role is statically assigned, not elected
- **Custom implementation** — we maintain fleet code instead of leveraging a battle-tested orchestration platform
- **RabbitMQ dependency** — fleet communication requires RabbitMQ availability; if the broker goes down, agents cannot send heartbeats

### Neutral

- The orchestrator is lightweight (~500 lines across orchestrator, registry, web API, agent). Maintenance burden is low.
- If the project ever outgrows the centralized model, the EventBus transport could be swapped for a more robust backbone without changing the fleet API.
- Agents degrade gracefully when disconnected — local ProcessHub continues managing processes independently; only remote control and monitoring are lost.

## Alternatives Considered

### 1. Kubernetes (Rejected)

Container orchestration platform.

Rejected because:
- Overkill for desktop/lab deployment (requires etcd, API server, container runtime)
- Services are plain Python processes, not containers
- No application-level RPC shutdown (SIGTERM only)
- Poor Windows support

### 2. Ansible / Salt (Rejected)

Configuration management with remote execution.

Rejected because:
- Push-based model without persistent health monitoring
- SSH-based — no real-time dashboard, no heartbeat
- Cannot send RPC shutdown to service queues
- Cannot embed inside the existing Python process

### 3. Consul + Nomad (Rejected)

Service discovery + job scheduler.

Rejected because:
- Two separate systems with their own infrastructure requirements
- Different communication protocols (gossip, custom RPC) instead of existing RabbitMQ
- No application-level RPC shutdown
- Significant operational overhead for a desktop/lab environment

### 4. Plain SSH / Remote Execution (Rejected)

Direct SSH commands to start/stop processes on remote machines.

Rejected because:
- No persistent health monitoring or heartbeat
- Requires SSH server and key management on every machine
- No centralized fleet state or dashboard
- Windows SSH support is limited and non-standard

## References

- Source: `ProcessHub/fleet/orchestrator.py`, `ProcessHub/fleet/hub_agent.py`, `ProcessHub/fleet/hub_registry.py`
- Source: `ProcessHub/fleet/fleet_web_api.py`
- Source: `ProcessHub/transport/eventbus_transport.py`
- Source: `MicroserviceBase/adapters/local_hub/local_hub_manager.py` (three modes)
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/FleetClient.js`, `FleetDashboard.js`
- Related: ADR-009 (Service Executor with RPC Shutdown), ADR-010 (Local Hub Manager)
