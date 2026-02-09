# ADR-010: Windows Process Lifecycle Fixes

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

Three separate Windows-specific issues prevented reliable process management:

### Issue 1: SIGBREAK Kills Without Cleanup

On Windows, `CTRL_BREAK_EVENT` triggers `SIGBREAK`. The **default SIGBREAK handler calls `ExitProcess`**, which terminates the process immediately — no `finally` blocks, no `atexit` handlers, no service unregistration.

### Issue 2: pika's `start_consuming()` Blocks Python Interrupts

pika's `start_consuming()` enters a C-level I/O loop that **never checks Python's interrupt flag**. Even if `KeyboardInterrupt` is pending (from SIGBREAK handler), the loop never yields to Python to deliver it.

### Issue 3: Subprocess PIPE Buffer Blocking

ProcessHub's `SimpleExecutor` creates processes with `stdout=subprocess.PIPE, stderr=subprocess.PIPE` but never reads the pipes. On Windows, the pipe buffer is ~4KB. Once full, `sys.stdout.write()` **blocks indefinitely**. Python's `logging.StreamHandler(sys.stdout)` will hang the entire logging system.

## Decision

### Fix 1: SIGBREAK → KeyboardInterrupt

In `rabbitmq_adapter.py`, convert SIGBREAK to KeyboardInterrupt:

```python
if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, signal.default_int_handler)
```

`default_int_handler` raises `KeyboardInterrupt`, which Python's `finally` blocks and `except KeyboardInterrupt` handlers can catch.

### Fix 2: Interruptible Consume Loop

Replace `start_consuming()` with a `process_data_events()` loop:

```python
# Before: blocks forever, never checks interrupt flag
channel.start_consuming()

# After: yields to Python every 1 second
self._consuming = True
while self._consuming:
    self._connection.process_data_events(time_limit=1)
```

Between iterations, Python checks its interrupt flag and delivers pending `KeyboardInterrupt`.

### Fix 3: Log File Redirection

In `ServiceExecutor`, redirect stdout/stderr to log files instead of pipes:

```python
log_fh = open(log_path, 'w', encoding='utf-8')
proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh, ...)
```

For services that still use `StreamHandler`, only attach it when running interactively:

```python
if sys.stdout.isatty():
    logging.root.addHandler(logging.StreamHandler())
```

## Consequences

### Positive

- Services unregister from Registry on stop (finally blocks execute)
- No more frozen/hung processes due to pipe buffer
- Process logs are persistent and readable from the dashboard
- CTRL+C works correctly in interactive terminals

### Negative

- `process_data_events(time_limit=1)` adds up to 1 second latency to interrupt delivery
- Log files consume disk space (truncated on each restart)

### Neutral

- These fixes are Windows-specific; Linux behavior is unchanged
- `time_limit=1` has negligible impact on message processing latency

## Alternatives Considered

### 1. Use `subprocess.DEVNULL` Instead of PIPE (Rejected)

Discard all output.

Rejected because:
- Losing stdout/stderr makes debugging impossible
- Log file redirection preserves output AND avoids blocking

### 2. Background Thread to Drain Pipes (Rejected)

Read pipes in a separate thread.

Rejected because:
- Adds threading complexity
- Log files are simpler and persist across process restarts

## References

- Source: `MicroserviceBase/adapters/transport/rabbitmq_adapter.py` (signal handling, consume loop)
- Source: `MicroserviceBase/adapters/local_hub/service_executor.py` (log redirection)
- Related: ADR-006 (Service Executor)
