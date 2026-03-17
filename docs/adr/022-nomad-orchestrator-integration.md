# ADR-022: Nomad Orchestrator Integration

## Status

Proposed

## Date

2026-03-12

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-03-12 | 1.0 | Initial version |

## Context

The current process management architecture uses `LocalHubManager` (ADR-010) to manage microservice processes on a single machine. For production and multi-node lab environments, we need a container/job orchestrator that can:

- Schedule and run services across multiple machines
- Provide health checks, restarts, and rolling deployments
- Integrate into the existing MicroserviceManagerGUI dashboard

HashiCorp Nomad provides a lightweight orchestrator with a comprehensive HTTP API (`http://<host>:4646/v1/`) that maps well to our existing `LocalHubManager` interface. Unlike Kubernetes, Nomad supports both container (`docker`) and raw binary (`raw_exec`, `exec`) workloads — important because our services run as Python processes, not exclusively in containers.

### Why Nomad over Kubernetes

| Criterion | Nomad | Kubernetes |
|-----------|-------|------------|
| Binary workloads (`raw_exec`) | Native driver | Requires container wrapping |
| Infrastructure weight | Single binary, no etcd | etcd + API server + scheduler + kubelet |
| Lab/desktop deployment | Runs in dev mode (`nomad agent -dev`) | Requires minikube/kind + significant RAM |
| API simplicity | REST + JSON, blocking queries | Complex API with CRDs, RBAC, webhooks |
| Windows support | Native agent | Limited (Windows nodes, not control plane) |
| Learning curve | Low — job files are flat HCL/JSON | High — YAML manifests, Helm, operators |

## Decision

### 1. Adapter Architecture

Create a `NomadHubAdapter` in the adapters layer that implements the same logical interface as `LocalHubManager`, translating calls to Nomad's HTTP API:

```
Adapters Layer
├── local_hub/
│   ├── local_hub_manager.py    ← manages local processes (existing)
│   └── service_executor.py     ← process lifecycle (existing)
└── nomad_hub/
    ├── nomad_hub_adapter.py    ← manages Nomad jobs (new)
    └── nomad_client.py         ← HTTP client for Nomad API (new)
```

### 2. HubManagerPort (New Port Interface)

Currently `LocalHubManager` is a concrete class with no port abstraction. To support both local and Nomad backends, introduce a `HubManagerPort`:

```python
# ports/hub_manager.py
from abc import ABC, abstractmethod
from typing import Optional

class HubManagerPort(ABC):
    """Abstract interface for process/job orchestration backends."""

    @abstractmethod
    def start_hub(self, mode: str = 'standalone', **kwargs) -> dict:
        """Start the orchestration backend."""

    @abstractmethod
    def stop_hub(self) -> dict:
        """Stop the orchestration backend."""

    @abstractmethod
    def get_status(self) -> dict:
        """Get status snapshot of all managed services."""

    @abstractmethod
    def start_processes(self, names: list) -> dict:
        """Start named services/jobs."""

    @abstractmethod
    def stop_processes(self, names: list, force: bool = False) -> dict:
        """Stop named services/jobs."""

    @abstractmethod
    def get_config(self) -> dict:
        """Get all service/job configurations."""

    @abstractmethod
    def add_config(self, name: str, config: dict) -> dict:
        """Add a service/job configuration."""

    @abstractmethod
    def update_config(self, name: str, config: dict) -> dict:
        """Update a service/job configuration."""

    @abstractmethod
    def remove_config(self, name: str) -> dict:
        """Remove a service/job configuration."""

    @abstractmethod
    def get_service_log(self, name: str, tail: int = 100) -> dict:
        """Read service/job log output."""

    @abstractmethod
    def import_service(self, name: str, source_path: str = '',
                       zip_data: str = '', wait_time: float = 1.0) -> dict:
        """Import a service package."""
```

Both `LocalHubManager` and `NomadHubAdapter` implement this port.

### 3. Nomad API Mapping

Map `HubManagerPort` methods to Nomad HTTP API endpoints:

| HubManagerPort Method | Nomad API | Notes |
|----------------------|-----------|-------|
| `start_hub()` | Connect to Nomad agent | Verify agent health via `GET /v1/agent/self` |
| `stop_hub()` | Disconnect | No Nomad-side action needed |
| `get_status()` | `GET /v1/jobs` + `GET /v1/job/:id/allocations` | Merge job status with allocation states |
| `start_processes(names)` | `POST /v1/jobs` | Submit job spec per service |
| `stop_processes(names)` | `DELETE /v1/job/:id` | Optional `?purge=true` for full removal |
| `get_config()` | `GET /v1/jobs` | Return job specs as config dict |
| `add_config(name, config)` | `POST /v1/jobs` with `count=0` | Register job without running |
| `update_config(name, config)` | `POST /v1/job/:id` | Update existing job spec |
| `remove_config(name)` | `DELETE /v1/job/:id?purge=true` | Remove job entirely |
| `get_service_log(name)` | `GET /v1/client/fs/logs/:alloc_id?task=...&type=stdout` | Requires allocation ID lookup |
| `import_service(name)` | Upload artifact + `POST /v1/jobs` | Use Nomad `artifact` stanza or external storage |

### 4. Nomad HTTP Client

Thin client wrapping Nomad's REST API with ACL support:

```python
# adapters/nomad_hub/nomad_client.py
import requests

class NomadClient:
    """HTTP client for Nomad API v1."""

    def __init__(self, address: str = 'http://127.0.0.1:4646',
                 token: str = '', namespace: str = 'default',
                 timeout: float = 30.0):
        self._address = address.rstrip('/')
        self._namespace = namespace
        self._timeout = timeout
        self._session = requests.Session()
        if token:
            self._session.headers['X-Nomad-Token'] = token
        self._last_index = {}  # endpoint -> X-Nomad-Index for blocking queries

    def _url(self, path: str) -> str:
        return f'{self._address}/v1/{path.lstrip("/")}'

    def _request(self, method: str, path: str, **kwargs) -> dict:
        kwargs.setdefault('timeout', self._timeout)
        params = kwargs.pop('params', {})
        params.setdefault('namespace', self._namespace)
        resp = self._session.request(method, self._url(path),
                                     params=params, **kwargs)
        resp.raise_for_status()
        # Track blocking query index
        if 'X-Nomad-Index' in resp.headers:
            self._last_index[path] = resp.headers['X-Nomad-Index']
        return resp.json() if resp.content else {}

    # --- Jobs ---
    def list_jobs(self, prefix: str = '') -> list:
        params = {'prefix': prefix} if prefix else {}
        return self._request('GET', '/jobs', params=params)

    def get_job(self, job_id: str) -> dict:
        return self._request('GET', f'/job/{job_id}')

    def register_job(self, job_spec: dict) -> dict:
        return self._request('POST', '/jobs', json={'Job': job_spec})

    def stop_job(self, job_id: str, purge: bool = False) -> dict:
        params = {'purge': 'true'} if purge else {}
        return self._request('DELETE', f'/job/{job_id}', params=params)

    # --- Allocations ---
    def get_allocations(self, job_id: str) -> list:
        return self._request('GET', f'/job/{job_id}/allocations')

    # --- Logs ---
    def get_logs(self, alloc_id: str, task: str,
                 log_type: str = 'stdout', plain: bool = True) -> str:
        params = {'task': task, 'type': log_type,
                  'plain': 'true' if plain else 'false',
                  'origin': 'end', 'offset': 50000}
        resp = self._session.get(
            self._url(f'/client/fs/logs/{alloc_id}'),
            params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.text

    # --- Blocking queries (long-poll) ---
    def list_jobs_blocking(self, prefix: str = '',
                           wait: str = '30s') -> list:
        params = {'prefix': prefix} if prefix else {}
        index = self._last_index.get('/jobs', '0')
        params.update({'index': index, 'wait': wait})
        return self._request('GET', '/jobs', params=params)

    # --- Health ---
    def agent_self(self) -> dict:
        return self._request('GET', '/agent/self')
```

### 5. Job Spec Generation

Convert `hub_processes.json` config format to Nomad job spec:

```python
def config_to_job_spec(name: str, config: dict,
                       datacenter: str = 'dc1') -> dict:
    """Convert a LocalHub process config to a Nomad job spec."""
    return {
        'ID': name.lower().replace(' ', '-'),
        'Name': name,
        'Type': 'service',
        'Datacenters': [datacenter],
        'TaskGroups': [{
            'Name': name.lower(),
            'Count': 1,
            'Tasks': [{
                'Name': name.lower(),
                'Driver': 'raw_exec',  # Python processes, not containers
                'Config': {
                    'command': config.get('script', 'python'),
                    'args': config.get('args', []),
                },
                'Resources': {
                    'CPU': config.get('cpu', 500),
                    'MemoryMB': config.get('memory_mb', 256),
                },
                'Env': config.get('env', {}),
            }]
        }]
    }
```

### 6. Real-Time Updates via Blocking Queries

Nomad supports long-poll via `?index=N&wait=T` on most GET endpoints. Use a background thread to poll for job/allocation changes and push updates through the existing WebSocket broadcast:

```python
def _poll_loop(self):
    """Background thread: long-poll Nomad for status changes."""
    while self._running:
        try:
            jobs = self._client.list_jobs_blocking(wait='30s')
            status = self._build_status(jobs)
            if status != self._last_status:
                self._last_status = status
                self._on_status_change(status)  # → WebSocket broadcast
        except requests.exceptions.Timeout:
            continue  # Normal for blocking queries
        except Exception as e:
            logger.error('Nomad poll error: %s', e)
            time.sleep(5)
```

### 7. FastAPI Bridge Integration

The FastAPI bridge currently creates `LocalHubManager` via `_get_local_hub_manager()`. Extend this with a factory that selects the backend:

```python
def _get_hub_manager() -> HubManagerPort:
    """Get hub manager based on configuration."""
    hub_type = os.environ.get('DASGUI_HUB_TYPE', 'local')

    if hub_type == 'nomad':
        from ..nomad_hub.nomad_hub_adapter import NomadHubAdapter
        nomad_addr = os.environ.get('NOMAD_ADDR', 'http://127.0.0.1:4646')
        nomad_token = os.environ.get('NOMAD_TOKEN', '')
        return NomadHubAdapter(address=nomad_addr, token=nomad_token)
    else:
        from ..local_hub.local_hub_manager import LocalHubManager
        return LocalHubManager(config_path=_resolve_config_path())
```

Existing `/api/local-hub/*` endpoints remain unchanged — they call `HubManagerPort` methods regardless of backend.

### 8. GUI Dashboard Changes

The GUI (`LocalHubDashboard.js`) needs minimal changes since it already calls REST endpoints:

| Feature | Local Hub | Nomad Hub |
|---------|-----------|-----------|
| Start/Stop processes | Same endpoints | Same endpoints (routed to Nomad) |
| Status display | Process PID + state | Allocation ID + state |
| Log viewing | File-based log tail | Nomad log API stream |
| Config editing | `hub_processes.json` fields | Same fields + Nomad-specific (CPU, memory) |
| Import service | ZIP upload to local dir | ZIP upload + artifact config |

Add a backend indicator in the dashboard header to show whether connected to Local Hub or Nomad.

## Consequences

### Positive

- Services can be managed across multiple machines without Fleet mode complexity
- Nomad handles restarts, health checks, and resource allocation automatically
- Same GUI dashboard works for both local and Nomad backends
- `raw_exec` driver runs Python processes directly — no Docker required
- Blocking queries provide near-real-time status updates without WebSocket on the Nomad side
- Lightweight — Nomad is a single binary, runs in dev mode for testing

### Negative

- Nomad is an additional infrastructure dependency for production deployments
- `raw_exec` driver requires Nomad agent running on the same machine as the service — less isolation than Docker
- Log streaming requires allocation ID lookup (two API calls vs one file read)
- RPC graceful shutdown (`svc_api_shutdown`) not natively supported — must be implemented as a pre-stop task or custom health check
- ACL token management adds operational complexity

### Neutral

- `LocalHubManager` remains the default for development and single-machine use
- Nomad integration is opt-in via `DASGUI_HUB_TYPE=nomad` environment variable
- The `python-nomad` PyPI package exists as an alternative to the custom `NomadClient`, but the custom client avoids an external dependency and maps directly to our needs
- Fleet mode (ADR-015) and Nomad serve different scales: Fleet for small labs (2-5 hubs), Nomad for larger deployments

## Alternatives Considered

### 1. Kubernetes (Deferred)

Use Kubernetes for container orchestration.

Deferred because:
- Heavyweight infrastructure (etcd, API server, scheduler, kubelet) unsuitable for lab/desktop use
- Forces containerization — our services run as Python processes with local file dependencies
- Complex YAML manifests and Helm charts vs Nomad's simpler JSON job specs
- May be revisited when services are fully containerized

### 2. Docker Compose (Rejected)

Use Docker Compose for multi-service management.

Rejected because:
- No scheduling or multi-node support — single host only
- No health check driven restarts (basic restart policies only)
- No API for dynamic job submission — requires file-based config
- Forces Docker containers — same issue as Kubernetes

### 3. python-nomad Library (Deferred)

Use the `python-nomad` PyPI package instead of a custom HTTP client.

Deferred because:
- Adds an external dependency for what is essentially REST calls
- Custom client gives us control over blocking query integration and error handling
- May adopt later if the API surface we use grows significantly

### 4. Nomad Event Stream (Deferred)

Use `GET /v1/event/stream` (Server-Sent Events) instead of blocking queries for real-time updates.

Deferred because:
- SSE requires persistent HTTP connection management
- Blocking queries are simpler and sufficient for dashboard refresh rates
- May adopt for features requiring sub-second update latency

## References

- Source: `MicroserviceBase/adapters/local_hub/local_hub_manager.py` (existing hub manager)
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py` (hub endpoints)
- Source: `MicroserviceBase/ports/` (existing port interfaces)
- Related: ADR-010 (Local Hub Manager), ADR-009 (RPC Shutdown), ADR-015 (Fleet Orchestrator)
- External: [Nomad HTTP API](https://developer.hashicorp.com/nomad/api-docs)
- External: [Nomad Job Specification](https://developer.hashicorp.com/nomad/docs/job-specification)
- External: [python-nomad](https://github.com/jrxFive/python-nomad)
