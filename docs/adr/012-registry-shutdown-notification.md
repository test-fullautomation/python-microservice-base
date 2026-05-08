# ADR-012: Registry Shutdown Notification to GUI

## Status

Superseded — Consul deregistration on graceful shutdown handles this case. `ServiceRunner` calls `DELETE /v1/agent/service/deregister/<id>` in its shutdown handler; Consul propagates removal to subscribed clients within ~1s.

## Date

2026-02-03

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-03 | 1.0 | Initial version |

## Context

When the Service Registry shuts down, the GUI has no way to know that services have disappeared. The real-time update subscription simply stops receiving messages, leaving the GUI showing stale service entries. Users see services as "connected" when they are actually unreachable.

## Decision

Implement a **sentinel message** broadcast by the Registry before it exits:

**Registry side** (`service_registry.py`):
```python
def svc_api_shutdown(self):
    # Broadcast shutdown sentinel to all GUI subscribers
    sentinel = json.dumps({"__registry_shutdown__": True})
    self._transport.publish(
        exchange=self._update_exchange,
        routing_key='',
        body=sentinel,
    )
    # Then proceed with normal shutdown
    self.unregister_service()
    self._transport.stop_consuming()
```

**GUI side** (`app.js`):
```javascript
function onRealtimeUpdate(data) {
    if (data.__registry_shutdown__) {
        MM.showToast('Registry', 'Service Registry has shut down.', 'warning');
        clearServicesList();
        return;
    }
    // Normal service update handling...
}
```

The sentinel is published to the **realtime update fanout exchange**, which all subscribed GUI clients receive. The GUI then clears its service list and shows a notification.

## Consequences

### Positive

- GUI immediately reflects Registry shutdown (no stale entries)
- Users get a clear notification explaining why services disappeared
- Clean state reset prevents confusion

### Negative

- If the Registry crashes (ungraceful exit), no sentinel is sent
- Sentinel pattern adds a special-case message to the update channel

### Neutral

- GUI can attempt reconnection after receiving sentinel

## Alternatives Considered

### 1. Heartbeat-Based Detection (Deferred)

GUI periodically pings Registry and detects absence.

Deferred because:
- Adds polling overhead
- Detection latency depends on poll interval
- Sentinel is instant and simpler

## References

- Source: `MicroserviceBase/domain/service_registry.py`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js`
