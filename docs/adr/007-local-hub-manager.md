# ADR-007: Local Hub Manager for ProcessHub Integration

## Status

Accepted

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

## Alternatives Considered

### 1. Direct ProcessHub API in FastAPI Endpoints (Rejected)

Call ProcessHub methods directly from route handlers.

Rejected because:
- Config management, placeholder resolution, and status merging would be scattered across endpoint handlers
- No single source of truth for hub state

## References

- Source: `MicroserviceBase/adapters/local_hub/local_hub_manager.py`
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py` (hub endpoints)
- Related: ADR-006 (Service Executor), ADR-008 (Service Import)
