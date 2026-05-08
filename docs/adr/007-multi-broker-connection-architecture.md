# ADR-007: Multi-Broker Connection Architecture

## Status

Accepted (updated post-migration: the "broker" concept now refers to a Consul cluster — the GUI can connect to multiple Consul clusters simultaneously with the same chip-based UI; see [`docs/changelog.md`](../changelog.md)).

## Date

2026-01-25

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-01-25 | 1.0 | Initial version |

## Context

The GUI originally connected to a single RabbitMQ broker. In multi-team environments, services run on different brokers (different hosts/ports). Users need to discover and invoke services across multiple brokers simultaneously.

```javascript
// Before: single global state
global.brokerUrl = 'localhost:5672';
global.routingKey = 'registry_key';
global.servicesInfor = { ... };
```

This prevented connecting to multiple brokers at the same time.

## Decision

Replace single globals with a **connections map** and **reverse lookup table**:

```javascript
// MM.connections — keyed by 'host:port'
MM.connections = {
    'broker-a:5672': {
        brokerUrl: 'broker-a:5672',
        routingKey: 'discovery_key',
        services: { Calculator: {...}, Debugboard: {...} },
        realtimeSubscribed: true,
    },
    'broker-b:5672': {
        brokerUrl: 'broker-b:5672',
        routingKey: 'registry_key',
        services: { ClewareSwitch: {...} },
        realtimeSubscribed: false,
    },
};

// Reverse lookup: service name → broker key
MM.serviceToBroker = {
    Calculator: 'broker-a:5672',
    Debugboard: 'broker-a:5672',
    ClewareSwitch: 'broker-b:5672',
};
```

**Legacy compatibility:** `MM.brokerUrl`, `MM.routingKey`, and `MM.servicesInfor` remain as dynamic aliases pointing to the active/first broker. Existing service GUI plugins work without modification.

**Sidebar DOM structure:**

```
#servicesList
  .broker-section (one per broker)
    .broker-header (hidden in single-broker mode)
    .broker-accordion
      .accordion-item (one per service)
        .list-group-item
```

**Progressive disclosure:** `.broker-header` elements are hidden by default. When multiple brokers are connected, `.multi-broker` class is added to `#servicesList`, making headers visible.

**RPC routing:** `ServiceClient._requestViaFastAPI()` includes `broker_url` in the POST body so the bridge routes to the correct broker:

```javascript
{ method: 'svc_api_add', args: [1, 2], broker_url: 'broker-a:5672' }
```

**Session persistence:** `sessionStorage.mm_connections` stores broker URLs as JSON array for reconnection on page refresh.

## Consequences

### Positive

- Users can discover services across multiple brokers in one GUI session
- Service invocations are automatically routed to the correct broker
- Legacy plugins work unchanged via alias globals
- Clean separation between broker connections

### Negative

- More complex state management in the GUI
- Service name collisions across brokers are not handled (last-write wins)
- FastAPI bridge must support multi-broker RPC routing

### Neutral

- Session storage provides soft persistence (cleared on browser close)

## Alternatives Considered

### 1. Broker Proxy / Federation (Deferred)

Use RabbitMQ federation or a message proxy to merge brokers into one.

Deferred because:
- Requires broker infrastructure changes
- Not all environments allow federation
- Client-side routing is simpler and requires no broker modification

## References

- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js`
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py`
- Related: ADR-005 (Dual-Host GUI), ADR-006 (FastAPI Bridge)
