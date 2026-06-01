# ADR-006: FastAPI Bridge for Browser GUI

## Status

Accepted

## Date

2026-01-20

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-01-20 | 1.0 | Initial version |

## Context

In the dual-host GUI architecture (ADR-005), browser clients cannot use AMQP directly. Browsers have no TCP socket access, so a server-side bridge is needed to proxy requests between the browser and RabbitMQ.

Requirements:
- REST API for service invocation (`POST /api/request`)
- WebSocket for real-time service updates
- Service discovery endpoint (`GET /api/services`)
- CORS support for cross-origin browser requests
- Embeddable in a background thread (not blocking the main process)

## Decision

Use **FastAPI** with **Uvicorn** running in a daemon thread:

```python
class FastAPIBridge:
    def start(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
        )
        self._thread.start()
```

**Key endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/request` | Forward RPC request to service via broker |
| GET | `/api/services` | Get all registered services |
| WS | `/ws/updates` | Push real-time service updates |
| POST | `/api/local-hub/start` | Start ProcessHub |
| POST | `/api/local-hub/stop` | Stop ProcessHub |
| GET | `/api/local-hub/status` | Get hub status |
| POST | `/api/local-hub/processes/start` | Start processes |
| POST | `/api/local-hub/processes/stop` | Stop processes |
| POST | `/api/local-hub/import-service` | Import a service package |
| DELETE | `/api/local-hub/service/{name}` | Remove a service |
| GET | `/api/local-hub/service/{name}/log` | Get process log |
| POST | `/api/scaffold/generate` | Generate service scaffold |

**Browser ↔ Bridge ↔ Broker flow:**

```
Browser                FastAPI Bridge              RabbitMQ
  │                        │                          │
  │── POST /api/request ──>│                          │
  │                        │── rpc_call() ──────────>│
  │                        │<── response ────────────│
  │<── JSON response ─────│                          │
  │                        │                          │
  │── WS /ws/updates ────>│                          │
  │                        │<── service events ──────│
  │<── push update ────────│                          │
```

## Consequences

### Positive

- Browser clients get full access to service infrastructure via HTTP/WS
- Automatic OpenAPI documentation at `/docs`
- Pydantic models validate all request/response payloads
- Uvicorn in daemon thread does not block Electron or other processes

### Negative

- Extra process (bridge) must be running alongside the broker
- Network hop adds latency vs. direct AMQP in Electron mode
- Bridge PID must be managed (start/stop/reconnect)

### Neutral

- Default port 1112 (configurable)
- CORS enabled for all origins in development

## Alternatives Considered

### 1. Flask (Rejected)

Synchronous, no native WebSocket, no async support.

Rejected because:
- WebSocket requires Flask-SocketIO (extra dependency)
- No automatic API docs
- Blocking I/O model

### 2. Plain WebSocket Server (Rejected)

Custom WebSocket server without REST.

Rejected because:
- No REST endpoints for simple request/response
- Must build routing/validation manually
- No API documentation

## References

- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py`
- Related: ADR-005 (Dual-Host GUI)
- Diagram: `docs/diagrams/component.puml`
