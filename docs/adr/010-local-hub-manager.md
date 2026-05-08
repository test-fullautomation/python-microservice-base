# ADR-010: Local Hub Manager for ProcessHub Integration

> **⚠ Superseded** — 2026-05-07.  Pre-migration decision; no longer
> applies to the gRPC + Consul + Nomad architecture.  See the existing
> Status note below for the immediate successor, and
> [`docs/changelog.md`](../changelog.md) +
> [`docs/adr/AUDIT.md`](AUDIT.md) for the full triage.  Kept here for
> git archaeology.

## Status

Superseded by [ADR-022 Nomad Orchestrator Integration](022-nomad-orchestrator-integration.md). The Local Hub process supervisor was replaced by Nomad `raw_exec` jobs; lifecycle management moved out of the GUI process and into the Nomad agent.

## Date

2026-02-01

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-01 | 1.0 | Initial version |
| 2026-02-12 | 1.1 | Added comparison with third-party process managers |

## Context

The MicroserviceManagerGUI needs to start, stop, and manage a local ProcessHub instance. Users should be able to manage process configurations and monitor process status from the browser dashboard.

ProcessHub provides `ProcessHubServer` for runtime management, but it needs configuration, lifecycle management, and a REST-compatible interface layer.

## Decision

Create `LocalHubManager` as the orchestration layer between FastAPI endpoints and ProcessHub:

```python
class LocalHubManager:
    def __init__(self, config_path=None, broker_host='localhost', broker_port=5672):
        self._config_path = config_path
        self._process_config = {}     # Resolved configs (runtime)
        self._raw_config = {}         # Original configs with placeholders
        self._server = None           # ProcessHubServer instance
        self._executor = None         # ServiceExecutor instance

    def start_hub(self, mode='standalone', ...):
        """Start ProcessHub with ServiceExecutor and ZMQ transport."""

    def stop_hub(self):
        """Stop ProcessHub and all managed processes."""

    def get_status(self):
        """Get hub state snapshot + configs for UI rendering."""

    def start_processes(self, names):
        """Start named processes via ServiceExecutor."""

    def stop_processes(self, names, force=False):
        """Stop named processes (RPC first, signal fallback)."""

    def import_service(self, name, source_path='', zip_data=''):
        """Import a microservice package into the hub."""

    def remove_service(self, name):
        """Remove service config + managed files."""
```

**Config persistence with placeholders:**

```json
{
    "ServiceRegistry": {
        "script": "${config_dir}/start_registry.py",
        "args": ["--config", "${config_dir}/config.json"],
        "process_name": "ServiceRegistry",
        "wait_time": 2.0
    },
    "ClewareSwitch": {
        "script": "${python}",
        "args": ["-m", "ClewareSwitch"],
        "cwd": "${config_dir}/services",
        "process_name": "ClewareSwitch",
        "service_name": "ServiceCleware",
        "wait_time": 1.0
    }
}
```

`${python}` resolves to `sys.executable`, `${config_dir}` to the directory containing `hub_processes.json`. The `_raw_config` dict preserves placeholders for saving; `_process_config` holds resolved values for runtime.

**Status endpoint aggregation:**

`get_status()` merges ProcessHub's `get_state_snapshot()` with local config data:
- Processes from snapshot (running state, PID)
- Configured-but-not-running processes (stopped state)
- Process configs for the edit form

## Consequences

### Positive

- Single class manages the full ProcessHub lifecycle
- Config placeholders make configs portable across machines
- REST endpoints map cleanly to manager methods
- Status merging provides a complete view for the dashboard

### Negative

- Manager holds mutable state (_process_config, _raw_config) that must stay synchronized with the JSON file
- Direct access to `self._server.core._registry` for cleanup is not ideal

### Neutral

- ProcessHub remains a separate library — LocalHubManager is a thin adapter

## Why ProcessHub over Third-Party Process Managers

A key design question is: why build a custom process manager (ProcessHub) instead
of adopting an established third-party solution?

### Requirements

MicroserviceBase's process management has several domain-specific needs:

| Requirement | Description |
|-------------|-------------|
| **RPC-based lifecycle** | Services must unregister from RabbitMQ before exit; a plain SIGTERM kills the process without cleanup |
| **Two-phase shutdown** | Send `svc_api_shutdown` RPC first, fall back to OS signal only if RPC times out (ADR-009) |
| **GUI-integrated status** | Dashboard needs real-time process state merged with stored configs (running, stopped, dead) |
| **Fleet coordination** | Multiple hubs across machines, coordinated via message bus with health monitoring |
| **Embedded operation** | Runs inside the same Python process as FastAPI — no separate daemon to install or configure |
| **Service import** | ZIP/folder import with AST validation, `__main__.py` generation, config placeholder persistence |
| **Windows robustness** | SIGBREAK handling, pipe-blocking avoidance, process tree management (ADR-013) |

### Comparison Matrix

| Feature | ProcessHub | ZooKeeper | Supervisor | systemd | PM2 |
|---------|-----------|-----------|------------|---------|-----|
| **RPC shutdown** (send command to service queue before kill) | Yes | No | No | No | No |
| **Embeddable** (runs inside Python process, no daemon) | Yes | No (JVM daemon) | No (daemon) | No (PID 1) | No (Node.js daemon) |
| **Fleet multi-hub** (coordinate processes across machines) | Yes (EventBus) | Yes (distributed consensus) | No (single host) | No (single host) | No (single host) |
| **GUI state merging** (snapshot + config for dashboard) | Yes (native API) | Manual | Manual (XML-RPC) | Manual (D-Bus) | Manual (CLI/API) |
| **Restart FSM** (DEAD → ACK → RESTART with health checks) | Yes | No (watches only) | Yes (simple) | Yes (simple) | Yes (simple) |
| **Windows support** | Yes | Yes (JVM) | No (Linux/macOS) | No (Linux only) | Yes |
| **Config placeholders** (`${python}`, `${config_dir}`) | Yes | No | No | No | No |
| **Zero external dependencies** | Yes | JVM + ZK cluster | Python package | Linux kernel | Node.js runtime |
| **Service-aware** (knows about RabbitMQ routing keys, exchanges) | Yes | No | No | No | No |

### Candidate Analysis

#### Apache ZooKeeper (Rejected)

ZooKeeper is a distributed coordination service for maintaining configuration,
naming, and synchronization across clusters.

**Where it overlaps:**
- Distributed service registry and health monitoring
- Leader election for fleet orchestration

**Why it does not fit:**
- **Heavyweight infrastructure** — requires a JVM-based ZooKeeper ensemble (3+ nodes recommended for production). Our use case is a single developer machine or small test lab.
- **No process management** — ZooKeeper tracks ephemeral nodes and watches, but does not start, stop, or restart OS processes. We would still need a process manager alongside ZooKeeper.
- **No RPC shutdown** — ZooKeeper has no concept of sending a domain-specific RPC command to a service queue before termination. It can only detect that a node disappeared.
- **Operational overhead** — installing and maintaining a ZooKeeper cluster adds significant complexity for what is fundamentally a desktop/lab application.
- **Wrong abstraction level** — ZooKeeper solves distributed consensus; we need local process lifecycle control with optional multi-hub coordination.

#### Supervisor (Rejected)

Supervisor is a process control system for Unix-like operating systems.

**Where it overlaps:**
- Starts, stops, and restarts OS processes
- Process grouping, log capture, status monitoring
- XML-RPC API for programmatic control

**Why it does not fit:**
- **No Windows support** — Supervisor runs on Linux and macOS only. Our primary deployment target is Windows (ADR-013).
- **No RPC shutdown** — Supervisor sends OS signals (SIGTERM, SIGKILL) only. Services cannot gracefully unregister from RabbitMQ before being killed.
- **Separate daemon** — Supervisor runs as `supervisord` (a root-level daemon). It cannot be embedded inside our FastAPI process.
- **No fleet coordination** — manages processes on a single host only. Multi-machine orchestration would require an additional layer.
- **Static configuration** — INI-file based config with no placeholder resolution or dynamic import.

#### systemd (Rejected)

systemd is the Linux init system and service manager.

**Where it overlaps:**
- Robust process lifecycle with restart policies
- Socket activation, dependency ordering
- Journal-based log management

**Why it does not fit:**
- **Linux only** — not available on Windows or macOS.
- **Requires root/system privileges** — user-level units exist but are limited and non-trivial to manage from a GUI.
- **No RPC shutdown** — sends signals only (`ExecStop=`, `KillSignal=`). No way to send an application-level RPC before kill.
- **Not embeddable** — systemd is PID 1; it cannot be embedded inside another process.
- **No fleet coordination** — single-host only.
- **Inappropriate scope** — systemd manages OS services; our processes are user-level microservice instances in a development/test environment.

#### PM2 (Rejected)

PM2 is a Node.js process manager with load balancing.

**Where it overlaps:**
- Process start/stop/restart with auto-restart on crash
- Log management, monitoring dashboard
- Windows support (partial)

**Why it does not fit:**
- **Node.js dependency** — requires a Node.js runtime, which is an unnecessary dependency for a Python-based system.
- **No RPC shutdown** — PM2 sends OS signals. Custom shutdown hooks (`SIGINT` handler in Node.js) are Node-specific and do not support sending RabbitMQ RPC commands.
- **Separate daemon** — runs as `pm2 daemon`; cannot embed inside FastAPI.
- **No fleet coordination** — PM2 Plus (cloud service) offers multi-host monitoring but not coordinated process control.
- **Designed for Node.js** — Python process management is a secondary use case with limited support.

### Summary

The common gap across all third-party candidates:

1. **No RPC-based graceful shutdown** — all rely on OS signals, but our services
   need to unregister from RabbitMQ before exiting (otherwise the broker still
   routes messages to a dead queue).

2. **Not embeddable** — all run as separate daemons, adding installation and
   operational complexity to what should be a single-process desktop application.

3. **No fleet coordination** (except ZooKeeper, which solves the wrong problem) —
   ProcessHub's fleet mode with EventBus transport provides multi-hub
   orchestration without external infrastructure.

ProcessHub exists because the intersection of these requirements (RPC shutdown +
embedded operation + fleet mode + Windows support + GUI integration) is not
served by any existing tool.

## Alternatives Considered

### 1. Direct ProcessHub API in FastAPI Endpoints (Rejected)

Call ProcessHub methods directly from route handlers.

Rejected because:
- Config management, placeholder resolution, and status merging would be scattered across endpoint handlers
- No single source of truth for hub state

### 2. Apache ZooKeeper for Process Coordination (Rejected)

Use ZooKeeper for service discovery and health monitoring.

Rejected because:
- Heavyweight JVM infrastructure for a desktop/lab use case
- Does not manage OS processes — still needs a process manager
- No RPC-based graceful shutdown
- Operational overhead of maintaining a ZooKeeper ensemble

### 3. Supervisor for Process Management (Rejected)

Use Supervisor as the process control backend.

Rejected because:
- No Windows support (primary deployment target)
- Signal-only shutdown — no RPC graceful unregister
- Separate daemon — cannot embed inside FastAPI process
- No multi-hub fleet coordination

### 4. systemd Service Units (Rejected)

Manage services as systemd units.

Rejected because:
- Linux only
- Requires system privileges
- No RPC shutdown, not embeddable, no fleet coordination
- Wrong scope (OS services vs user-level test processes)

### 5. PM2 Process Manager (Rejected)

Use PM2 for cross-platform process management.

Rejected because:
- Adds Node.js runtime dependency to a Python project
- Signal-only shutdown — no RPC graceful unregister
- Separate daemon — cannot embed inside FastAPI process
- No fleet coordination (PM2 Plus is a cloud monitoring service, not a coordination layer)

## References

- Source: `MicroserviceBase/adapters/local_hub/local_hub_manager.py`
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py` (hub endpoints)
- Related: ADR-009 (Service Executor), ADR-011 (Service Import)
