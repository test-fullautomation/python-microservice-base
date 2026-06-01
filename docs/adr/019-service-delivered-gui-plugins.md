# ADR-019: Service-Delivered GUI Plugin Architecture

## Status

Accepted

## Date

2026-02-12

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-12 | 1.0 | Initial version |

## Context

MicroserviceBase supports many different services — calculators, hardware
controllers, device managers — each with unique UI requirements.  The Manager
GUI needs to display service-specific panels without hardcoding knowledge of
every possible service.

The question is: how should service-specific UIs be delivered and loaded?

### Requirements

1. Each service controls its own UI independently
2. Adding a new service's GUI requires no changes to the manager application
3. GUIs must work in both Electron and browser modes (ADR-005)
4. GUIs should only be downloaded when needed (on-demand)
5. GUI assets should be cached to avoid re-downloading on every click

## Decision

Services deliver their own GUI as **HTML/CSS/JS files packaged in a ZIP
archive**, transferred via RPC, and dynamically loaded into the manager
at runtime.

### Architecture

```
Service (Python)                    Manager GUI (Browser/Electron)
  │                                       │
  │  svc_api_get_gui_checksum()           │
  │ <─────────────────────────────────────│  1. Check if cached
  │  → "a1b2c3d4" (MD5)                  │
  │ ─────────────────────────────────────>│
  │                                       │  2. Compare with sessionStorage
  │  svc_api_get_gui_files()              │
  │ <─────────────────────────────────────│  3. Download if changed
  │  → base64-encoded ZIP                 │
  │ ─────────────────────────────────────>│
  │                                       │  4. Extract to web/services/
  │                                       │     ServiceName1.0.0/
  │                                       │     ├── ServiceName.html
  │                                       │     ├── ServiceName.js
  │                                       │     └── (optional .css)
  │                                       │
  │                                       │  5. fetch('ServiceName.html')
  │                                       │     → wrapper.innerHTML = html
  │                                       │
  │                                       │  6. <script src="ServiceName.js">
  │                                       │     → loads, calls load function
```

### Service-Side: Built-In RPC Methods

`ServiceBase` provides two methods automatically:

```python
def svc_api_get_gui_checksum(self):
    """Return MD5 checksum of the GUI directory (for cache invalidation)."""
    # Walks the GUIs/ directory, hashes all file contents
    return md5_hex_string

def svc_api_get_gui_files(self):
    """Return base64-encoded ZIP of the GUIs/ directory."""
    # Creates in-memory ZIP of all files in GUIs/
    return base64_encoded_bytes
```

These are in the `_internal` set — callable via RPC but hidden from the
public API list (ADR-017).

### Client-Side: On-Demand Download with Checksum Caching

```javascript
function checkAndGetTheServiceGUIResources(serviceName, callback) {
    // 1. Request checksum from service
    var checksumRequest = { method: 'svc_api_get_gui_checksum', args: null };
    MM.requestService(checksumRequest, exchange, routingKey)
      .then(function (data) {
          var remoteChecksum = data.result_data;
          var cachedChecksum = sessionStorage.getItem('gui_checksum_' + serviceName);

          // 2. Compare with cached value
          if (remoteChecksum === cachedChecksum) {
              callback();  // Use cached files
              return;
          }

          // 3. Download ZIP from service
          var downloadRequest = { method: 'svc_api_get_gui_files', args: null };
          MM.requestService(downloadRequest, exchange, routingKey)
            .then(function (zipData) {
                // 4. Extract via bridge or Electron
                extractGUI(serviceName, zipData.result_data)
                  .then(function () {
                      sessionStorage.setItem('gui_checksum_' + serviceName, remoteChecksum);
                      callback();
                  });
            });
      });
}
```

### Client-Side: Dynamic Loading and Caching

```javascript
function loadServiceContent(serviceName, containerId) {
    var contentDiv = document.getElementById(containerId);
    var version = MM.servicesInfor[serviceName].version || '';
    var basePath = 'services/' + serviceName + version + '/';

    // Check in-memory panel cache
    if (_servicePanels[serviceName]) {
        // Show cached panel, hide others
        _servicePanels[serviceName].style.display = '';
        return;
    }

    // Fetch HTML, inject, load script
    fetch(basePath + serviceName + '.html')
      .then(function (r) { return r.text(); })
      .then(function (html) {
          var wrapper = document.createElement('div');
          wrapper.innerHTML = html;
          contentDiv.appendChild(wrapper);
          _servicePanels[serviceName] = wrapper;  // cache

          var script = document.createElement('script');
          script.src = basePath + serviceName + '.js';
          document.head.appendChild(script);
      });
}
```

**Lifecycle functions** — service JS files should expose:

```javascript
// Called when panel is loaded or switched to
window.loadServiceName = function () { ... };

// Called when user switches to a different service
window.unloadServiceName = function () { ... };
```

### Plugin Convention

Each service plugin follows this structure:

```
GUIs/                         (in service package)
├── service.html              (main panel markup)
├── service.js                (logic, event handlers)
└── service.css               (optional styles)

→ Extracted to:
web/services/ServiceName1.0.0/
├── ServiceName.html
├── ServiceName.js
└── ServiceName.css
```

**JS convention:**

```javascript
const MM = window.MicroserviceManager;

function loadServiceName() {
    // Initialize UI, bind events
    MM.requestService({method: 'svc_api_get_status', args: null},
        MM.SERVICES_EXCHANGE_NAME, MM.routingKey)
      .then(function (data) { /* render */ });
}

function unloadServiceName() {
    // Cleanup timers, event listeners
}

window.loadServiceName = loadServiceName;
window.unloadServiceName = unloadServiceName;
loadServiceName();
```

### Extraction Paths

| Mode | Extraction Method | Target Directory |
|------|-------------------|------------------|
| **Browser** | `POST /api/service-gui-download/{name}` on FastAPI bridge | `MicroserviceManagerGUI/web/services/` |
| **Electron** | `electronAPI.extractGUIZip()` via preload | `web/services/` (relative to app) |

Both paths include zip-slip protection (ADR path traversal fix).

## Why Not Alternative Approaches

### Static GUI Bundled in Manager (Rejected)

Ship all service GUIs as part of the manager application.

Rejected because:
- Manager must be updated every time a service GUI changes
- Third-party services cannot contribute GUIs
- Tight coupling between manager and service UI code

### iframe-Based Isolation (Rejected)

Load each service GUI in an `<iframe>` with its own origin.

Rejected because:
- Cross-origin restrictions prevent communication with `MM.*` namespace
- Duplicate Bootstrap CDN loads per iframe
- Complex message passing (`postMessage`) instead of direct function calls
- Poor user experience (scrolling, sizing, styling inconsistencies)

### Web Components / Shadow DOM (Deferred)

Encapsulate each service GUI in a custom element with Shadow DOM.

Deferred because:
- Adds complexity without clear benefit for our use case
- Bootstrap 5 styles would need to be duplicated inside each shadow root
- Current `innerHTML` + `<script>` pattern works reliably
- Worth re-evaluating if plugin isolation becomes a problem

### Server-Side Rendering (Rejected)

Services render HTML on the server, manager displays it as-is.

Rejected because:
- No client-side interactivity (every click requires a round-trip)
- Cannot use Bootstrap components, JS event handlers, or real-time updates
- High latency for interactive panels

## Consequences

### Positive

- **Decoupled** — services own their GUI; manager knows nothing about service-specific UI
- **On-demand** — GUIs are only downloaded when a user clicks the service
- **Cached** — checksum comparison avoids re-downloading unchanged files;
  in-memory panel cache avoids re-parsing HTML on service switch
- **Standard web** — plugins use plain HTML/CSS/JS with Bootstrap 5; any web
  developer can create a service GUI
- **Dual-host** — same plugin loading works in Electron and browser (ADR-005)

### Negative

- **No isolation** — plugins share the global DOM and `window` scope; a
  misbehaving plugin can affect other panels
- **Naming collisions** — load/unload functions use `window.loadServiceName`
  convention; name clashes are possible but unlikely (service names are unique)
- **Base64 overhead** — GUI ZIP is transferred as base64 over RPC, adding ~33%
  size overhead

### Neutral

- Plugin HTML/JS is not minified or bundled — acceptable for management UIs
  where file sizes are small
- The checksum mechanism uses session storage (cleared on browser close); a
  fresh session always re-downloads on first access

## References

- Source: `MicroserviceBase/domain/service_base.py` (lines 292-322, svc_api_get_gui_files)
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js` (lines 388-454, 1607-1660)
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py` (lines 207-266)
- Related: ADR-004 (Electron over Qt — service-delivered GUI is the decisive argument)
- Related: ADR-005 (Dual-Host GUI), ADR-017 (svc_api_ Convention)
