# ADR-012: Electron Bridge Lifecycle Decoupling

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

In Electron mode, the FastAPI bridge and Service Registry run as child processes. If Electron kills them on exit, all services become unreachable. This is undesirable in scenarios where:

- The GUI is closed temporarily but services should keep running
- Multiple GUI instances need to connect to the same bridge
- The bridge hosts the Local Hub managing long-running processes

## Decision

**Do not auto-kill the bridge on Electron exit.** The backend (bridge + registry) runs independently of the GUI lifecycle.

**Bridge PID persistence:**

```javascript
// preload.js
function spawnBridge(options) {
    const proc = spawn(pythonPath, args, { detached: true });
    proc.unref();  // Don't keep Electron alive for this child
    _writePid(proc.pid);  // Save PID to bridge.pid
    return { pid: proc.pid };
}
```

**Reconnection on GUI restart:**

```javascript
function isBridgeRunning() {
    const pid = _readSavedPid();
    if (!pid) return { running: false };
    try {
        process.kill(pid, 0);  // Signal 0 = check existence
        return { running: true, pid: pid };
    } catch {
        _removePidFile();
        return { running: false };
    }
}
```

**Flow:**
1. First launch: GUI spawns bridge, saves PID to `bridge.pid`
2. GUI closes: bridge keeps running (detached process)
3. GUI reopens: reads `bridge.pid`, checks if PID is alive
4. If alive: reconnect to existing bridge
5. If dead: spawn new bridge, save new PID

**Dashboard UI** shows bridge status badge (Running/Stopped) with explicit Start/Stop buttons.

## Consequences

### Positive

- Services remain accessible after GUI close
- Multiple GUI sessions can share one bridge
- ProcessHub processes survive GUI restarts

### Negative

- Bridge process must be manually stopped (or via GUI button)
- Orphaned bridge processes possible if PID file is lost

### Neutral

- Browser mode (non-Electron) always connects to an external bridge — no lifecycle management needed

## References

- Source: `MicroserviceBase/MicroserviceManagerGUI/electron/preload.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/electron/main.js`
- Related: ADR-003 (Dual-Host GUI), ADR-004 (FastAPI Bridge)
