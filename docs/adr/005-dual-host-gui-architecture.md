# ADR-005: Dual-Host GUI Architecture (Electron + Browser)

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

The original MicroserviceManagerGUI was a monolithic Electron application:

- `index.html`, `index.js`, `main.js`, `renderer.js` all in the root directory
- Heavy use of `require()` for Node.js modules (amqplib, fs, path)
- `global.*` namespace for inter-module communication
- `notifier.notify()` for desktop notifications
- `eval()` for dynamic function binding
- `dialog.showMessageBox()` for confirmations
- Service GUI files in `servicesGUI/` folder

**Problems:**
- Cannot run in a web browser (depends on Node.js APIs)
- Tight coupling between UI and Electron-specific APIs
- No REST API for external tools or automation
- Difficult to test UI without full Electron setup

## Decision

Split the GUI into two hosting modes sharing the same web code:

```
MicroserviceManagerGUI/
├── electron/              # Electron wrapper (thin)
│   ├── main.js            # BrowserWindow, IPC handlers
│   ├── preload.js         # contextBridge: AMQP, FS, bridge lifecycle
│   └── settings.json      # Persisted settings
├── web/                   # Pure browser code (no Node.js deps)
│   ├── index.html         # Bootstrap 5 CDN
│   ├── js/
│   │   ├── app.js         # Main orchestration
│   │   ├── ServiceClient.js
│   │   ├── LocalHubClient.js
│   │   ├── LocalHubDashboard.js
│   │   ├── FleetClient.js
│   │   ├── FleetDashboard.js
│   │   └── ServiceCreator.js
│   ├── css/
│   │   ├── style.css
│   │   ├── creator.css
│   │   └── fleet.css
│   ├── img/               # Static assets (was Image/)
│   └── services/          # Dynamic service plugins (was servicesGUI/)
└── python/
    ├── start_bridge.py    # Launch FastAPI bridge
    ├── start_registry.py  # Launch Service Registry
    ├── hub_processes.json  # ProcessHub config
    └── services/           # Imported service packages
```

**Key architectural patterns:**

1. **Namespace pattern**: `window.MicroserviceManager` (alias `MM`) replaces `global.*`
2. **IIFE modules**: Each JS file is an IIFE attaching to `MM`
3. **Feature detection**: `window.electronAPI` presence determines Electron vs browser mode
4. **Bootstrap 5 CDN**: No node_modules, no build step
5. **Login via modal**: Bootstrap modal replaces Electron popup window

**Pattern replacements:**

| Before (Electron-only) | After (Browser-compatible) |
|---|---|
| `require('amqplib')` | `MM.serviceClient` (via FastAPI) |
| `global.brokerUrl` | `MM.brokerUrl` |
| `eval('fn()')` | Direct function binding |
| `notifier.notify()` | `MM.showToast()` |
| `dialog.showMessageBox()` | `MM.showToast()` (warning) |

**Electron preload** exposes safe APIs via `contextBridge`:
```javascript
contextBridge.exposeInMainWorld('electronAPI', {
    amqp: { ... },          // AMQP operations
    showOpenDialog: ...,     // Native file dialogs
    spawnBridge: ...,        // Start FastAPI bridge
    killBridge: ...,         // Stop bridge
    isBridgeRunning: ...,    // Check bridge PID
});
```

## Consequences

### Positive

- GUI works in any modern browser without Electron
- Electron mode adds native features (file dialogs, bridge management)
- No build step required — open `index.html` in browser
- Bootstrap CDN means zero npm dependencies in `web/`

### Negative

- Two code paths for Electron-specific features (file dialog, bridge lifecycle)
- Must test in both browser and Electron modes
- Service plugins must be browser-compatible (no require())

### Neutral

- Existing service GUI plugins need porting from `require()` to `MM.*` namespace
- Image paths changed from `Image/` to `img/`

## Alternatives Considered

### 1. Keep Electron-Only (Rejected)

Continue with monolithic Electron app.

Rejected because:
- Cannot be used without Electron installation
- No REST API for automation/integration
- Heavy dependency on Node.js ecosystem

### 2. React/Vue Single-Page App (Rejected)

Modern SPA framework with build toolchain.

Rejected because:
- Adds npm/webpack complexity
- Build step conflicts with "open index.html and go" simplicity
- Service plugin loading is easier with plain JS

## References

- Source: `MicroserviceBase/MicroserviceManagerGUI/electron/`, `MicroserviceBase/MicroserviceManagerGUI/web/`
- Related: ADR-006 (FastAPI Bridge)
