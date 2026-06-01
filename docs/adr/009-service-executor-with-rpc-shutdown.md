# ADR-009: Service Executor with RPC Graceful Shutdown

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
| 2026-02-08 | 1.1 | Added service_name config for correct RPC routing |

## Context

ProcessHub's `SimpleExecutor` stops processes using OS signals: `CTRL_BREAK_EVENT` on Windows, `SIGTERM` on Linux. For MicroserviceBase services, this has two problems:

1. **No graceful cleanup**: The service needs to unregister from the Service Registry before exiting. Signal-based stop races with cleanup code.
2. **Windows SIGBREAK kills immediately**: The default SIGBREAK handler calls `ExitProcess`, bypassing Python `finally` blocks entirely.

Additionally, ProcessHub uses `subprocess.PIPE` for stdout/stderr but never reads the pipes. On Windows, the pipe buffer is ~4KB. Once full, any `write()` to stdout blocks the process, hanging the entire service (including Python logging `StreamHandler`).

## Decision

Create `ServiceExecutor` that wraps `SimpleExecutor` and adds a **two-phase shutdown**:

```
Phase 1: RPC Shutdown (graceful)
  ├── Publish {"method": "svc_api_shutdown"} to service's queue
  ├── svc_api_shutdown() calls unregister_service() → Registry notified
  ├── stop_consuming() → consume loop exits
  └── Wait up to shutdown_timeout for process exit

Phase 2: Signal Fallback (if Phase 1 times out)
  ├── Send CTRL_BREAK_EVENT (Windows) or SIGTERM (Linux)
  ├── SIGBREAK → KeyboardInterrupt → finally block → unregister
  └── Wait up to stop_timeout, then force kill if needed
```

**Key implementation details:**

```python
class ServiceExecutor(ProcessExecutor):
    def stop(self, name, force=False):
        if self._delegate.is_running(name):
            if self._try_rpc_shutdown(name):
                # Graceful exit via RPC
                return True, f"Process {name} stopped gracefully via RPC"
        # Fallback to signal-based stop
        return self._delegate.stop(name, force=force)

    def _try_rpc_shutdown(self, process_name):
        # Use service_name from config (may differ from process name)
        config = self._configs.get(process_name, {})
        queue_name = config.get("service_name") or process_name

        ch.basic_publish(
            exchange="",
            routing_key=queue_name,  # Service's actual RabbitMQ queue
            body=json.dumps({"method": "svc_api_shutdown", "args": None}),
        )
```

**Service queue name resolution:** The hub process name (e.g., `ClewareSwitch`) may differ from the service's RabbitMQ queue name (`_SERVICE_INFO['name']`, e.g., `ServiceCleware`). The config stores `service_name` to resolve this.

**Log file redirection:** Instead of piped stdout/stderr, processes write to `logs/{name}.log`:

```python
log_fh = open(log_path, 'w', encoding='utf-8')
proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh, ...)
```

This avoids the 4KB pipe buffer blocking issue entirely.

**Windows SIGBREAK fix** (in `rabbitmq_adapter.py`):

```python
# Convert SIGBREAK → KeyboardInterrupt for graceful cleanup
if sys.platform == "win32":
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

# Use interruptible loop instead of blocking start_consuming()
while self._consuming:
    self._connection.process_data_events(time_limit=1)
```

## Consequences

### Positive

- Services unregister from Registry before process exit
- GUI sees service disappear cleanly (not as a stale entry)
- Log files persist for debugging failed starts
- No pipe blocking on Windows

### Negative

- RPC shutdown requires a working RabbitMQ connection
- Two-phase stop takes longer than immediate kill (up to 10s total)
- Must maintain `service_name` mapping in config

### Neutral

- Existing processes without `service_name` fall back to using process name as queue name
- `SimpleExecutor` is unchanged — only `ServiceExecutor` has the new behavior

## Alternatives Considered

### 1. Signal-Only Stop (Rejected)

Rely solely on CTRL_BREAK_EVENT / SIGTERM.

Rejected because:
- SIGBREAK default handler kills without cleanup on Windows
- Even with the SIGBREAK fix, the unregister races with process termination

### 2. Named Pipe / IPC Channel (Deferred)

Use a named pipe for shutdown signaling instead of RabbitMQ RPC.

Deferred because:
- Adds platform-specific IPC complexity
- RabbitMQ is already available and the service is already consuming

## References

- Source: `MicroserviceBase/adapters/local_hub/service_executor.py`
- Source: `MicroserviceBase/adapters/transport/rabbitmq_adapter.py` (signal handling)
- Source: `MicroserviceBase/domain/service_base.py` (svc_api_shutdown)
- Related: ADR-010 (Local Hub Manager)
