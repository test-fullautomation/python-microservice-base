# Troubleshooting Guide Map

A problem-oriented index for MicroserviceBase developers. Find the symptom you
observe, then follow the links to ADRs, diagrams, and source files that explain
the relevant subsystem.

> **How to use:** Ctrl+F for a keyword (e.g. "timeout", "not updating",
> "stuck"), or browse the symptom categories below. Each entry links to the
> architecture decisions, diagrams, and source code relevant to that problem
> area.

---

## Quick Symptom Index

| # | Symptom | Category |
|---|---------|----------|
| [1](#1-service-does-not-appear-on-the-dashboard) | Service does not appear on the dashboard | Dashboard |
| [2](#2-dashboard-shows-service-but-status-never-updates) | Dashboard shows service but status never updates | Dashboard |
| [3](#3-rpc-call-times-out-after-30-seconds) | RPC call times out after 30 seconds | Communication |
| [4](#4-service-receives-no-requests) | Service receives no requests | Communication |
| [5](#5-alias-call-returns-non-supported-request) | Alias call returns "Non-supported request" | Alias |
| [6](#6-alias-returns-wrong-number-of-arguments) | Alias returns wrong number of arguments | Alias |
| [7](#7-method-not-visible-in-gui-api-explorer) | Method not visible in GUI API Explorer | Service API |
| [8](#8-service-gui-plugin-does-not-load) | Service GUI plugin does not load | GUI Plugin |
| [9](#9-service-gui-shows-stale-content) | Service GUI shows stale content | GUI Plugin |
| [10](#10-process-wont-stop-gracefully-on-windows) | Process won't stop gracefully on Windows | Process |
| [11](#11-service-process-hangs-after-some-output) | Service process hangs after some output | Process |
| [12](#12-hub-config-lost-after-moving-to-another-machine) | Hub config lost after moving to another machine | Config |
| [13](#13-gui-works-in-electron-but-not-in-browser) | GUI works in Electron but not in browser | GUI |
| [14](#14-killed-process-not-reflected-on-gui) | Killed process not reflected on GUI | Process |
| [15](#15-fleet-hub-shows-offline-after-running-fine) | Fleet hub shows "Offline" after running fine | Fleet |
| [16](#16-service-import-fails-with-validation-error) | Service import fails with validation error | Import |
| [17](#17-registry-shuts-down-but-gui-still-shows-services) | Registry shuts down but GUI still shows services | Registry |
| [18](#18-multiple-brokers-but-services-appear-under-wrong-broker) | Multiple brokers but services appear under wrong broker | Multi-Broker |
| [19](#19-gui-works-in-browser-but-websocket-disconnects) | GUI works in browser but WebSocket disconnects | Bridge |
| [20](#20-service-registers-but-disappears-immediately) | Service registers but disappears immediately | Registration |
| [21](#21-fleet-dashboard-stuck-at-loading-fleet-data) | Fleet Dashboard stuck at "Loading fleet data..." | Fleet |
| [22](#22-fleet-shows-fleet-unreachable-loop-after-disconnect) | Fleet shows "Fleet Unreachable" loop after disconnect | Fleet |
| [23](#23-port-2510-not-released-after-hub-restart-errno-10048) | Port 2510 not released after hub restart (Errno 10048) | Fleet |
| [24](#24-fleet-api-calls-fail-with-err_connection_refused-in-electron) | Fleet API calls fail with ERR_CONNECTION_REFUSED in Electron | Fleet |

---

## Dashboard & Real-Time Updates

### 1. Service does not appear on the dashboard

The service starts but the GUI sidebar never shows it.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-020](adr/020-exchange-topology-design.md) | Is the service bound to `services_request` exchange with the correct routing key? |
| [ADR-016](adr/016-rabbitmq-as-message-broker.md) | Is RabbitMQ running and reachable? Check `localhost:15672` management UI. |
| [ADR-003](adr/003-service-registry-over-zookeeper.md) | Is the Service Registry running? Services register via the registry. |
| [sequence_registration.puml](diagrams/sequence_registration.puml) | Full registration message flow |
| [`amqp_registry_adapter.py`](../MicroserviceBase/adapters/registry/amqp_registry_adapter.py) | `publish_event()` — publishes to `service_information` topic exchange |
| [`service_base.py`](../MicroserviceBase/domain/service_base.py) | `register_service()` — calls registry port |

**Common causes:**
- Registry not running (no consumer on `service_information` exchange)
- Service's `_SERVICE_INFO['routing_key']` doesn't match what the registry expects
- RabbitMQ connection params (host/port) differ between service and registry
- The `service_infor_queue` is not declared (registry didn't start first)

---

### 2. Dashboard shows service but status never updates

The service appears in the sidebar, but real-time changes (new services, removed
services) don't push to the GUI.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-020](adr/020-exchange-topology-design.md) | Is the `services_update` fanout exchange created? Are GUI clients subscribed with exclusive queues? |
| [ADR-006](adr/006-fastapi-bridge-for-browser-gui.md) | Is the FastAPI bridge running? Browser GUI depends on the bridge for WebSocket updates. |
| [ADR-008](adr/008-electron-bridge-lifecycle-decoupling.md) | Did the bridge process die while the GUI stayed open? |
| [gui_architecture.puml](diagrams/gui_architecture.puml) | GUI dual-host architecture — Electron vs browser data flow |
| [`amqp_registry_adapter.py`](../MicroserviceBase/adapters/registry/amqp_registry_adapter.py) | `broadcast_update()` — publishes to fanout; `subscribe_to_updates()` — creates exclusive queue |
| [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | WebSocket handler at `/ws/updates` — relays fanout messages to browser |
| [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | WebSocket client connection and `onmessage` handler |

**Common causes:**
- `update_exchange_name` not configured in `config.json` (defaults to `'services_update'`)
- Bridge WebSocket connection dropped — check browser console for WS errors
- Fanout exchange exists but no queue is bound (subscriber crashed)

---

## Communication & RPC

### 3. RPC call times out after 30 seconds

Calling a service method returns a timeout error.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-020](adr/020-exchange-topology-design.md) | Is the target service's queue bound to `services_request` with the correct routing key? |
| [ADR-016](adr/016-rabbitmq-as-message-broker.md) | RPC pattern: `reply_to` callback queue + `correlation_id` matching |
| [sequence_rpc.puml](diagrams/sequence_rpc.puml) | Full RPC request-response sequence |
| [`rabbitmq_adapter.py`](../MicroserviceBase/adapters/transport/rabbitmq_adapter.py) | `rpc_call()` — creates callback queue, publishes, waits for response |
| [`service_base.py`](../MicroserviceBase/domain/service_base.py) | `dispatch_request()` — processes incoming RPC and sends response |

**Common causes:**
- Target service is not running (nobody consuming from its queue)
- Wrong routing key (message goes to exchange but no queue matches)
- Service crashed while processing the request (no response published)
- `prefetch_count=1` and the service is stuck processing a previous request
- Network firewall blocking AMQP port 5672

---

### 4. Service receives no requests

The service is running and registered, but never receives any RPC calls.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-020](adr/020-exchange-topology-design.md) | Queue binding: is `queue_bind(exchange, queue, routing_key)` correct? |
| [ADR-017](adr/017-svc-api-naming-convention.md) | Is the method name prefixed with `svc_api_`? Only `svc_api_*` methods are dispatchable. |
| [ADR-013](adr/013-windows-process-lifecycle-fixes.md) | On Windows, is `process_data_events(time_limit=1)` loop running? (not `start_consuming()`) |
| [`rabbitmq_adapter.py`](../MicroserviceBase/adapters/transport/rabbitmq_adapter.py) | `consume()` — exchange declare, queue declare, queue bind, consume loop |

**Common causes:**
- Queue was purged by a second instance starting (`queue_purge` on startup)
- Service name collision: two services with the same queue name
- `consume()` not called (service registered but never called `serve()`)
- Routing key mismatch between client and service

---

## Alias Routing

### 5. Alias call returns "Non-supported request"

Calling an alias name returns a failure instead of routing to the target service.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-018](adr/018-alias-routing-design.md) | Alias routing flow: Registry looks up `_alias_dict`, substitutes `${input}`, forwards to target |
| [sequence_alias.puml](diagrams/sequence_alias.puml) | Alias request flow through the Registry |
| [`service_registry.py`](../MicroserviceBase/domain/service_registry.py) | `is_specific_request()` — checks if alias exists; `on_specific_request()` — handles alias routing |
| [`service_base.py`](../MicroserviceBase/domain/service_base.py) | `dispatch_request()` — three-level fallback: `_api_dict` → `is_specific_request()` → fail |

**Common causes:**
- Alias name not in `alias.json` (typo or not saved via GUI)
- RPC call sent to the target service directly instead of the Registry
- Registry not running (alias calls must go through the Registry's routing key)
- `alias.json` was updated but the registry process was not restarted / `svc_api_update_alias_conf()` was not called

---

### 6. Alias returns wrong number of arguments

The alias resolves but the target method receives too many or too few arguments.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-018](adr/018-alias-routing-design.md) | `${input}` placeholder mechanism: count of `${input}` must match count of caller args |
| [`service_registry.py`](../MicroserviceBase/domain/service_registry.py) | `handle_alias_request()` — `"${input}"` → `"{}"` → `.format(*args)` → `.split(',')` |
| [ServiceAlias GUI](../MicroserviceBase/MicroserviceManagerGUI/web/services/ServiceAlias1.0.0/) | Alias editor table and arguments hint |

**Common causes:**
- Arguments template has 2 `${input}` but caller sends 1 (or vice versa)
- Comma inside a fixed argument value breaks `.split(',')` parsing
- Empty arguments field but caller sends args (or vice versa)

---

## Service API

### 7. Method not visible in GUI API Explorer

A method exists in the service code but doesn't show in the GUI's method list.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-017](adr/017-svc-api-naming-convention.md) | Method must be prefixed with `svc_api_`. The `_internal` set hides certain methods from the public list. |
| [`service_base.py`](../MicroserviceBase/domain/service_base.py) | `get_svc_api_methods_dict()` — `dir(self)` + `startswith('svc_api')` filtering |

**Common causes:**
- Method name typo (e.g. `svc_ap_add` instead of `svc_api_add`)
- Method is in the `_internal` set (`svc_api_shutdown`, `svc_api_get_gui_files`, etc.)
- Method is not callable (property or attribute instead of function)
- `gui_support=False` in `_SERVICE_INFO` hides `svc_api_get_gui_files`

---

## Service GUI Plugins

### 8. Service GUI plugin does not load

Clicking a service in the sidebar shows a blank panel or an error.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-019](adr/019-service-delivered-gui-plugins.md) | Plugin lifecycle: checksum check → ZIP download → extract to `web/services/` → fetch HTML → inject script |
| [ADR-005](adr/005-dual-host-gui-architecture.md) | Dual-host: extraction path differs between Electron and browser |
| [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | `checkAndGetTheServiceGUIResources()` — checksum + download flow; `loadServiceContent()` — HTML fetch + script injection |
| [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | `/api/service-gui-download/{name}` — server-side ZIP extraction for browser mode |
| [`service_base.py`](../MicroserviceBase/domain/service_base.py) | `svc_api_get_gui_files()` — returns base64 ZIP of `GUIs/` directory |

**Common causes:**
- Service has `gui_support: false` in `_SERVICE_INFO` (no GUI shipped)
- `GUIs/` directory missing or empty in the service package
- ZIP extraction failed (path permissions, zip-slip protection triggered)
- JavaScript error in the plugin's `.js` file (check browser console)
- Plugin HTML references external resources that are not available

---

### 9. Service GUI shows stale content

The service's GUI was updated but the old version still displays.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-019](adr/019-service-delivered-gui-plugins.md) | Checksum caching: `sessionStorage` stores MD5, compared before download |
| [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | `checkAndGetTheServiceGUIResources()` — `sessionStorage.getItem('gui_checksum_' + serviceName)` |

**Common causes:**
- In-memory panel cache (`_servicePanels[serviceName]`) still holds the old DOM
  — reloading the page clears it
- `sessionStorage` checksum matches (the service-side `svc_api_get_gui_checksum()`
  returns the same hash because GUIs/ was not actually changed)
- Browser cache — hard refresh (Ctrl+Shift+R) or clear browser cache

---

## Process Management

### 10. Process won't stop gracefully on Windows

Stopping a service from the Local Hub kills it instantly without cleanup.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-009](adr/009-service-executor-with-rpc-shutdown.md) | Two-phase stop: RPC `svc_api_shutdown` first, then signal fallback |
| [ADR-013](adr/013-windows-process-lifecycle-fixes.md) | `CTRL_BREAK_EVENT` → SIGBREAK → default handler calls `ExitProcess` (no cleanup). Fix: `signal.SIGBREAK` → `default_int_handler` |
| [sequence_shutdown.puml](diagrams/sequence_shutdown.puml) | Two-phase shutdown sequence |
| [state_process_lifecycle.puml](diagrams/state_process_lifecycle.puml) | Process state machine |
| [`service_executor.py`](../MicroserviceBase/adapters/local_hub/service_executor.py) | `stop()` — RPC shutdown attempt, then `CTRL_BREAK_EVENT` |
| [`rabbitmq_adapter.py`](../MicroserviceBase/adapters/transport/rabbitmq_adapter.py) | `consume()` — installs `signal.SIGBREAK` handler, uses `process_data_events(time_limit=1)` loop |

**Common causes:**
- Service does not handle `svc_api_shutdown` (RPC phase fails, falls through to signal)
- `signal.signal(signal.SIGBREAK, signal.default_int_handler)` not installed (SIGBREAK kills without KeyboardInterrupt)
- `start_consuming()` used instead of `process_data_events()` loop (pika blocks Python interrupt flag)
- Service does not have `finally` block for cleanup after `KeyboardInterrupt`

---

### 11. Service process hangs after some output

A service works initially but freezes after running for a while.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-013](adr/013-windows-process-lifecycle-fixes.md) | `subprocess.PIPE` blocking: pipe buffer (~4KB on Windows) fills, `sys.stdout.write()` blocks |
| [`service_executor.py`](../MicroserviceBase/adapters/local_hub/service_executor.py) | `subprocess.Popen()` — check `stdout`/`stderr` params |

**Common causes:**
- Process launched with `stdout=subprocess.PIPE` but nobody reads the pipe
- Python `logging.StreamHandler(sys.stdout)` writes to a pipe that nobody reads
- Fix: only add `StreamHandler` when `sys.stdout.isatty()`; always use `FileHandler` for subprocess logging

---

### 14. Killed process not reflected on GUI

A process was killed externally (Task Manager, `kill`) but the GUI still shows
it as running.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-010](adr/010-local-hub-manager.md) | Local Hub Manager polls process status via `ProcessHubServer` |
| [ADR-012](adr/012-registry-shutdown-notification.md) | If killed without cleanup, no unregister event is sent |
| [`local_hub_manager.py`](../MicroserviceBase/adapters/local_hub/local_hub_manager.py) | Status polling — checks `poll()` on subprocess handles |
| [`service_executor.py`](../MicroserviceBase/adapters/local_hub/service_executor.py) | Process state tracking |

**Common causes:**
- Process killed externally without going through the executor's `stop()` method
- Hub status polling interval hasn't elapsed yet
- Multiple processes killed at once but only the first status update was processed

---

## Configuration

### 12. Hub config lost after moving to another machine

The `hub_processes.json` config references absolute paths that don't exist on
the new machine.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-014](adr/014-config-placeholder-persistence.md) | `${python}` and `${config_dir}` placeholders — resolved at runtime, saved as placeholders |
| [`local_hub_manager.py`](../MicroserviceBase/adapters/local_hub/local_hub_manager.py) | `_load_config_file()` — resolves placeholders; `_save_config_file()` — preserves `_raw_config` with placeholders |

**Common causes:**
- Config was saved with resolved absolute paths instead of `${python}`/`${config_dir}`
  placeholders (bug in save logic)
- `_raw_config` was overwritten with resolved values
- New machine has Python installed at a different path than `${python}` resolves to

---

## GUI Framework

### 13. GUI works in Electron but not in browser

Features work in the Electron desktop app but fail when accessed via
`http://localhost:1112`.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-005](adr/005-dual-host-gui-architecture.md) | Dual-host: browser uses FastAPI bridge; Electron uses `electronAPI` preload |
| [ADR-006](adr/006-fastapi-bridge-for-browser-gui.md) | FastAPI bridge provides REST + WebSocket + static file serving |
| [ADR-004](adr/004-electron-over-qt-for-gui-framework.md) | Why Electron: service-delivered HTML GUIs need a browser engine |
| [gui_architecture.puml](diagrams/gui_architecture.puml) | Electron vs browser data flow |
| [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | All REST endpoints and WebSocket handlers |
| [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | `isElectron` detection — different code paths for Electron vs browser |

**Common causes:**
- FastAPI bridge not running (`start_bridge.py` not started)
- Bridge port (default 1112) occupied by another process
- Feature uses `electronAPI.*` (preload) which is not available in browser
- CORS or mixed-content issues in browser
- Static files not served (bridge's `StaticFiles` mount misconfigured)

---

### 18. Multiple brokers but services appear under wrong broker

Services from different brokers are grouped incorrectly in the sidebar.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-007](adr/007-multi-broker-connection-architecture.md) | `MM.connections` map, `serviceToBroker` reverse lookup |
| [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | `MM.connections` map structure, broker section DOM rendering |

**Common causes:**
- `serviceToBroker` reverse lookup has stale entries
- Two brokers have a service with the same name
- Session storage (`sessionStorage.mm_connections`) has stale connection data from previous session

---

### 19. GUI works in browser but WebSocket disconnects

The GUI loads initially but stops receiving real-time updates.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-006](adr/006-fastapi-bridge-for-browser-gui.md) | FastAPI bridge WebSocket at `/ws/updates` |
| [ADR-008](adr/008-electron-bridge-lifecycle-decoupling.md) | Bridge lifecycle independent of GUI |
| [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | WebSocket handler — connection management |
| [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | WebSocket `onclose`/`onerror` handlers, reconnect logic |

**Common causes:**
- Bridge process crashed or was restarted
- Network interruption between browser and bridge
- Browser tab was suspended (background tab throttling)
- Proxy or firewall closing idle WebSocket connections

---

## Fleet Management

### 15. Fleet hub shows "Offline" after running fine

A remote hub was online but now shows as offline in the Fleet dashboard.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-015](adr/015-fleet-orchestrator-architecture.md) | Health monitoring: 3 states (online/degraded/offline), heartbeat intervals |
| [component_fleet.puml](diagrams/component_fleet.puml) | Fleet orchestrator component diagram |
| [`FleetClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetClient.js) | Fleet client communication |
| [`FleetDashboard.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetDashboard.js) | Hub status rendering |

**Common causes:**
- Remote hub's heartbeat stopped (hub process crashed)
- Network partition between the fleet orchestrator and the remote hub
- RabbitMQ connection to the remote hub's broker dropped
- Heartbeat timeout elapsed (hub transitions: online → degraded → offline)

---

### 21. Fleet Dashboard stuck at "Loading fleet data..."

The Fleet tab shows a spinner or "Loading fleet data..." forever after clicking
Connect.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [sequence_fleet_connect.puml](diagrams/sequence_fleet_connect.puml) | Full fleet connect sequence: configure → poll → render |
| [`FleetDashboard.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetDashboard.js) | `onFleetUpdate()` — fingerprint comparison, `_lastFleetJson` initial value |
| [`FleetClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetClient.js) | `_resolveUrl()` — is the poll reaching the bridge? Check browser console for network errors |
| [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | `/api/fleet/status` proxy — is `bridge._fleet_api_url` set? |

**Common causes:**
- `_lastFleetJson` initialized to `''` instead of `null`, causing the first
  render to be skipped when `_fleetFingerprint()` also returns `''` for empty
  hub data — the fingerprints match so no render is triggered
- `onUpdate(onFleetUpdate)` callback not registered before `startPolling()` —
  poll results fire but nobody handles them
- Bridge `_fleet_api_url` is `None` — the `/api/fleet/status` proxy returns 503
  but the dashboard doesn't show the error (error handler only fires after the
  first successful load)
- `_updateCallbacks` accumulated duplicate callbacks from repeated `activate()`
  calls — a `TypeError` in one callback prevents subsequent callbacks from
  firing

---

### 22. Fleet shows "Fleet Unreachable" loop after disconnect

Clicking Disconnect shows the configure prompt briefly, then immediately flips
back to "Fleet Unreachable — Failed to fetch".

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [sequence_fleet_disconnect.puml](diagrams/sequence_fleet_disconnect.puml) | Manual disconnect sequence |
| [`FleetDashboard.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetDashboard.js) | Disconnect handler — does it re-register `onUpdate` after `disconnect()`? |
| [`FleetClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetClient.js) | `disconnect()` — does it clear `_updateCallbacks`? |

**Common causes:**
- **Race condition:** disconnect handler calls `fleetClient.disconnect()` (which
  clears callbacks and stops polling), then immediately calls
  `fleetClient.onUpdate(onFleetUpdate)` again, re-registering the callback.  An
  in-flight poll (initiated before `disconnect()`) resolves and triggers the
  freshly-registered callback with an error, which renders the error screen and
  starts a new cycle
- Fix: do **not** call `onUpdate()` in the disconnect handler — only register it
  in the Connect button handler

---

### 23. Port 2510 not released after hub restart (Errno 10048)

Starting the hub as orchestrator after a stop fails with:
`[Errno 10048] error while attempting to bind on address ('0.0.0.0', 2510)`

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [sequence_hub_stop_fleet_autodisconnect.puml](diagrams/sequence_hub_stop_fleet_autodisconnect.puml) | Hub stop sequence — uvicorn graceful shutdown |
| [sequence_hub_restart_fleet_reconnect.puml](diagrams/sequence_hub_restart_fleet_reconnect.puml) | Hub restart — `_wait_for_port_free` before bind |
| [`local_hub_manager.py`](../MicroserviceBase/adapters/local_hub/local_hub_manager.py) | `stop_hub()` — uvicorn `should_exit` + thread join; `_start_orchestrator()` — `_wait_for_port_free()` |

**Common causes:**
- **`FleetWebAPI.stop()` is a no-op** — it logs a message but never actually
  shuts down the uvicorn server thread.  The daemon thread keeps running and
  holds the socket.  Fix: manage `uvicorn.Server` directly in
  `LocalHubManager`, bypass `FleetWebAPI.start()`, and set
  `server.should_exit = True` on stop
- Orphan process from a previous session holds the port — `_wait_for_port_free()`
  detects this and force-kills the holder on Windows (`netstat` + `taskkill`)
- `_wait_for_port_free()` probed `127.0.0.1` but the server was bound to
  `0.0.0.0` — on Windows these are separate bindings, the probe may succeed even
  when the port is still in use
- Thread join timeout too short — uvicorn may take several seconds to close all
  connections and release the socket

---

### 24. Fleet API calls fail with ERR_CONNECTION_REFUSED in Electron

Browser console shows `GET http://localhost:2510/api/fleet/status net::ERR_CONNECTION_REFUSED`
instead of proxying through the bridge at port 1112.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [sequence_fleet_connect.puml](diagrams/sequence_fleet_connect.puml) | Fleet connect — `_bridgeOrigin()` resolution |
| [`FleetClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetClient.js) | `_bridgeOrigin()` — does it return `http://localhost:1112` in Electron? |
| [`LocalHubClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/LocalHubClient.js) | `_apiUrl()` — reference implementation with correct Electron fallback |
| [`ServiceClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/ServiceClient.js) | `constructor()` — `apiUrl` defaults to `window.location.origin` which is `file://` in Electron |

**Common causes:**
- `MM.serviceClient.apiUrl` is `file://` in Electron (set from
  `window.location.origin` in the `ServiceClient` constructor, and never updated
  to the bridge URL).  `_useProxy()` checked this value and returned `false`,
  causing FleetClient to hit port 2510 directly instead of proxying through the
  bridge
- Fix: replace `_useProxy()` / `_resolveUrl()` with a `_bridgeOrigin()` helper
  that falls back to `http://localhost:1112` when `apiUrl` is not HTTP — same
  pattern as `LocalHubClient._apiUrl()`
- `setApiUrl()` is defined on `ServiceClient` but never called from `app.js`
  (the bridge URL is never propagated to the client after bridge startup)

---

## Service Import

### 16. Service import fails with validation error

Importing a service ZIP or folder fails during validation.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-011](adr/011-service-import-with-module-execution.md) | Import flow: validate structure → extract → configure `python -m` execution |
| [sequence_service_import.puml](diagrams/sequence_service_import.puml) | Service import sequence diagram |
| [`local_hub_manager.py`](../MicroserviceBase/adapters/local_hub/local_hub_manager.py) | `import_service()` — validation, extraction, path safety checks |
| [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | `/api/local-hub/import-service` — REST endpoint |

**Common causes:**
- Service package missing `__main__.py` (required for `python -m` execution)
- ZIP contains path traversal entries (zip-slip protection blocks extraction)
- Service name contains invalid characters (`/`, `\`, `..`)
- Target directory already exists (name collision with existing service)

---

## Registry

### 17. Registry shuts down but GUI still shows services

The Registry process exits but the GUI doesn't clear the service list.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-012](adr/012-registry-shutdown-notification.md) | Registry shutdown sentinel: broadcasts empty service list before exiting |
| [`service_registry.py`](../MicroserviceBase/domain/service_registry.py) | Shutdown sequence — unregister all services, broadcast empty list |
| [`amqp_registry_adapter.py`](../MicroserviceBase/adapters/registry/amqp_registry_adapter.py) | `broadcast_update({})` — final fanout with empty dict |

**Common causes:**
- Registry was killed with `TerminateProcess` (no shutdown sequence executed)
- Registry's `finally` block didn't run (SIGBREAK without handler on Windows)
- Fanout exchange was deleted before the shutdown broadcast could be sent

---

### 20. Service registers but disappears immediately

A service shows up briefly in the GUI and then vanishes.

**Investigate:**

| Resource | What to check |
|----------|---------------|
| [ADR-003](adr/003-service-registry-over-zookeeper.md) | Registry maintains `services_information` dict; services register `'on'` and unregister `'off'` |
| [ADR-020](adr/020-exchange-topology-design.md) | `service_information` topic exchange with durable queue |
| [sequence_registration.puml](diagrams/sequence_registration.puml) | Registration sequence |
| [`service_base.py`](../MicroserviceBase/domain/service_base.py) | `register_service()` → `serve()` — if `serve()` fails, `finally` block calls `unregister_service()` |

**Common causes:**
- Service crashes immediately after registering (exception in `serve()` → `finally` unregisters)
- Service's `consume()` raises an error (bad routing key, exchange mismatch)
- Another service with the same name registers (overwrites the entry, then crashes)
- Service connects to a different broker than the registry

---

## Cross-Reference: Architecture Layer Map

When you know *which layer* is involved, use this table to find all relevant
resources for that layer.

### Domain Layer

| Component | Source | ADRs | Diagrams |
|-----------|--------|------|----------|
| ServiceBase | [`service_base.py`](../MicroserviceBase/domain/service_base.py) | [001](adr/001-hexagonal-architecture.md), [017](adr/017-svc-api-naming-convention.md) | [class_domain.puml](diagrams/class_domain.puml) |
| ServiceRegistry | [`service_registry.py`](../MicroserviceBase/domain/service_registry.py) | [003](adr/003-service-registry-over-zookeeper.md), [018](adr/018-alias-routing-design.md) | [class_domain.puml](diagrams/class_domain.puml), [sequence_alias.puml](diagrams/sequence_alias.puml) |
| Factory | [`factory.py`](../MicroserviceBase/factory.py) | [002](adr/002-factory-pattern-dependency-injection.md) | [architecture.puml](diagrams/architecture.puml) |

### Ports Layer

| Component | Source | ADRs | Diagrams |
|-----------|--------|------|----------|
| TransportPort | [`transport.py`](../MicroserviceBase/ports/transport.py) | [001](adr/001-hexagonal-architecture.md), [016](adr/016-rabbitmq-as-message-broker.md) | [class_ports.puml](diagrams/class_ports.puml) |
| ServiceRegistryPort | [`registry.py`](../MicroserviceBase/ports/registry.py) | [001](adr/001-hexagonal-architecture.md) | [class_ports.puml](diagrams/class_ports.puml) |
| UIBridgePort | [`ui_bridge.py`](../MicroserviceBase/ports/ui_bridge.py) | [001](adr/001-hexagonal-architecture.md), [006](adr/006-fastapi-bridge-for-browser-gui.md) | [class_ports.puml](diagrams/class_ports.puml) |

### Adapters Layer

| Component | Source | ADRs | Diagrams |
|-----------|--------|------|----------|
| RabbitMQ Transport | [`rabbitmq_adapter.py`](../MicroserviceBase/adapters/transport/rabbitmq_adapter.py) | [016](adr/016-rabbitmq-as-message-broker.md), [020](adr/020-exchange-topology-design.md), [013](adr/013-windows-process-lifecycle-fixes.md) | [class_adapters.puml](diagrams/class_adapters.puml), [sequence_rpc.puml](diagrams/sequence_rpc.puml) |
| AMQP Registry | [`amqp_registry_adapter.py`](../MicroserviceBase/adapters/registry/amqp_registry_adapter.py) | [020](adr/020-exchange-topology-design.md), [012](adr/012-registry-shutdown-notification.md) | [sequence_registration.puml](diagrams/sequence_registration.puml) |
| FastAPI Bridge | [`fastapi_bridge.py`](../MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py) | [006](adr/006-fastapi-bridge-for-browser-gui.md), [008](adr/008-electron-bridge-lifecycle-decoupling.md) | [gui_architecture.puml](diagrams/gui_architecture.puml) |
| Service Executor | [`service_executor.py`](../MicroserviceBase/adapters/local_hub/service_executor.py) | [009](adr/009-service-executor-with-rpc-shutdown.md), [013](adr/013-windows-process-lifecycle-fixes.md) | [sequence_shutdown.puml](diagrams/sequence_shutdown.puml), [state_process_lifecycle.puml](diagrams/state_process_lifecycle.puml) |
| Local Hub Manager | [`local_hub_manager.py`](../MicroserviceBase/adapters/local_hub/local_hub_manager.py) | [010](adr/010-local-hub-manager.md), [014](adr/014-config-placeholder-persistence.md) | [component_local_hub.puml](diagrams/component_local_hub.puml), [sequence_hub_stop_fleet_autodisconnect.puml](diagrams/sequence_hub_stop_fleet_autodisconnect.puml), [sequence_hub_restart_fleet_reconnect.puml](diagrams/sequence_hub_restart_fleet_reconnect.puml) |

### GUI Layer

| Component | Source | ADRs | Diagrams |
|-----------|--------|------|----------|
| Main App | [`app.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/app.js) | [005](adr/005-dual-host-gui-architecture.md), [007](adr/007-multi-broker-connection-architecture.md), [019](adr/019-service-delivered-gui-plugins.md) | [gui_architecture.puml](diagrams/gui_architecture.puml) |
| Service Client | [`ServiceClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/ServiceClient.js) | [016](adr/016-rabbitmq-as-message-broker.md) | [sequence_rpc.puml](diagrams/sequence_rpc.puml) |
| Local Hub Dashboard | [`LocalHubDashboard.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/LocalHubDashboard.js) | [010](adr/010-local-hub-manager.md) | [component_local_hub.puml](diagrams/component_local_hub.puml) |
| Fleet Dashboard | [`FleetDashboard.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetDashboard.js) | [015](adr/015-fleet-orchestrator-architecture.md) | [component_fleet.puml](diagrams/component_fleet.puml), [sequence_fleet_connect.puml](diagrams/sequence_fleet_connect.puml), [sequence_fleet_disconnect.puml](diagrams/sequence_fleet_disconnect.puml) |
| Fleet Client | [`FleetClient.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/FleetClient.js) | [015](adr/015-fleet-orchestrator-architecture.md) | [sequence_fleet_connect.puml](diagrams/sequence_fleet_connect.puml), [sequence_fleet_disconnect.puml](diagrams/sequence_fleet_disconnect.puml) |
| Service Creator | [`ServiceCreator.js`](../MicroserviceBase/MicroserviceManagerGUI/web/js/ServiceCreator.js) | [011](adr/011-service-import-with-module-execution.md) | — |
| Electron Wrapper | [`electron/`](../MicroserviceBase/MicroserviceManagerGUI/electron/) | [004](adr/004-electron-over-qt-for-gui-framework.md), [005](adr/005-dual-host-gui-architecture.md) | [gui_architecture.puml](diagrams/gui_architecture.puml) |

---

## Message Flow Quick Reference

For tracing a message through the system, start with the relevant sequence
diagram:

| Scenario | Diagram | Key Source Files |
|----------|---------|-----------------|
| Service registration | [sequence_registration.puml](diagrams/sequence_registration.puml) | `service_base.py` → `amqp_registry_adapter.py` → `service_registry.py` |
| RPC request-response | [sequence_rpc.puml](diagrams/sequence_rpc.puml) | `ServiceClient.js` → `fastapi_bridge.py` → `rabbitmq_adapter.py` → `service_base.py` |
| Alias routing | [sequence_alias.puml](diagrams/sequence_alias.puml) | Client → `service_registry.py` → `rabbitmq_adapter.py` → target service |
| Graceful shutdown | [sequence_shutdown.puml](diagrams/sequence_shutdown.puml) | `service_executor.py` → `rabbitmq_adapter.py` → `service_base.py` |
| Service import | [sequence_service_import.puml](diagrams/sequence_service_import.puml) | `LocalHubDashboard.js` → `fastapi_bridge.py` → `local_hub_manager.py` |
| GUI plugin loading | [sequence_gui_plugin_loading.puml](diagrams/sequence_gui_plugin_loading.puml) | `app.js` → `fastapi_bridge.py` → `service_base.py` (`svc_api_get_gui_files`) |
| Real-time update broadcast | [sequence_realtime_update.puml](diagrams/sequence_realtime_update.puml) | `service_registry.py` → `amqp_registry_adapter.py` (fanout) → `fastapi_bridge.py` (WS) → `app.js` |
| Fleet connect | [sequence_fleet_connect.puml](diagrams/sequence_fleet_connect.puml) | `FleetDashboard.js` → `FleetClient.js` → `fastapi_bridge.py` → FleetWebAPI |
| Fleet disconnect (manual) | [sequence_fleet_disconnect.puml](diagrams/sequence_fleet_disconnect.puml) | `FleetDashboard.js` → `FleetClient.js` → `fastapi_bridge.py` |
| Hub stop → fleet auto-disconnect | [sequence_hub_stop_fleet_autodisconnect.puml](diagrams/sequence_hub_stop_fleet_autodisconnect.puml) | `LocalHubDashboard.js` → `fastapi_bridge.py` → `local_hub_manager.py` (uvicorn shutdown) |
| Hub restart → fleet reconnect | [sequence_hub_restart_fleet_reconnect.puml](diagrams/sequence_hub_restart_fleet_reconnect.puml) | `LocalHubDashboard.js` → `fastapi_bridge.py` → `local_hub_manager.py` → FleetWebAPI |
