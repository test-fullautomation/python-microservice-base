# GUI Loading Mechanism — Multi-Tier Detection & Rendering

## Overview

When a user clicks a service in the sidebar, the GUI loading mechanism detects what type of UI assets the service provides and selects the appropriate renderer. The detection follows a priority waterfall — the first match wins.

## Tier Summary

| Tier | Trigger | Renderer | Loader | Unload |
|------|---------|----------|--------|--------|
| **1a** | `gui_schema.json` with `"renderer": "qt"` | Qt QML (shared shell) | `QtShellManager.loadQml()` | `QtShellManager.clear()` |
| **1b** | `gui_schema.json` without `renderer` | Bootstrap (generated) | `SchemaRenderer.render()` | `SchemaRenderer.cleanup()` |
| **1c** | `.qml` file in service folder | Qt QML (shared shell) | `QtShellManager.loadQml()` | `QtShellManager.clear()` |
| **2** | `.wasm` file in service folder | Qt WASM (per-service binary) | `QtWasmLoader.load()` | `QtWasmLoader.unload()` |
| **3** | `.html` file in service folder | Custom HTML + JS | `_fetchAndRenderServiceGUI()` | `window['unload' + name]()` |
| **4** | No GUI assets found | Auto-generated API form | `showServiceAPIExplorer()` | N/A |

## Entry Point

```
selectService(serviceName)
  → gui_support === true?
    → Yes: checkAndGetTheServiceGUIResources() → loadServiceContent()
    → No:  showServiceAPIExplorer()  (Tier 4)
```

`loadServiceContent()` first checks the DOM cache (`_servicePanels`). On a cache miss it calls `_loadServiceGUIMultiTier()` which runs the detection waterfall.

## Detection Waterfall

### Step 1 — Fetch gui_schema.json

```
fetch(folderPath + '/gui_schema.json')
```

- **Found + `renderer: "qt"`** → Tier 1a: extract `qml_file` (default `ServiceUI.qml`), load via `QtShellManager`
- **Found + no renderer** → Tier 1b: pass schema to `SchemaRenderer.render()`
- **Not found** → proceed to Step 2

### Step 2 — Detect .qml files

```
QtShellManager.detect(folderPath) → { hasQml, qmlFile }
```

Calls `/api/list-dir/` to scan for `.qml` files (prefers `ServiceUI.qml`).

- **Found** → Tier 1c: load via `QtShellManager.loadQml()`
- **Not found** → proceed to Step 3

### Step 3 — Detect .wasm files

```
QtWasmLoader.detect(folderPath) → boolean
```

Calls `/api/list-dir/` to scan for `.wasm` files.

- **Found** → Tier 2: load per-service WASM via `QtWasmLoader.load()`
- **Not found** → proceed to Step 4

### Step 4 — Fetch HTML

```
fetch(folderPath + '/' + serviceName + '.html')
```

- **Found** → Tier 3: inject HTML + load companion JS
- **Not found** → calls `/api/list-dir/` to discover any `.html` file
  - **Found** → Tier 3 (alternate file)
  - **Not found** → Tier 4: API Explorer fallback

## QML Shell Lifecycle

The QML Shell (`qtshell.wasm`) is a shared binary loaded once and reused across services:

- **First QML service**: downloads `qt-shell/qtshell.js` + `qtshell.wasm` (~9 MB gzip), initializes QML engine
- **Subsequent QML services**: reparents the canvas element, calls `qtshell_loadQml(newUrl)` — only the `.qml` file is fetched (~5 KB)
- **Switching away**: `QtShellManager.clear()` calls `qtshell_clearQml()` to destroy the QML item tree

## QML Shell vs Per-Service WASM

| Scenario | QML Shell (Tier 1a/1c) | Per-Service WASM (Tier 2) |
|----------|------------------------|---------------------------|
| First service | ~9 MB shell + ~5 KB QML | ~13 MB per-service WASM |
| Second service | ~5 KB QML only | ~13 MB another WASM |
| 10 services total | ~9.05 MB | ~130 MB |
| UI design tool | Qt Creator visual editor | Qt Creator (full compile) |
| Iteration speed | Copy .qml file | Full WASM rebuild |

## Diagrams

See `docs/diagrams/` for PlantUML sequence and flow diagrams:

- `flow_gui_loading_tiers.puml` — decision flow from click to renderer
- `sequence_qml_shell_first_load.puml` — first-time QML Shell loading
- `sequence_qml_shell_switch.puml` — switching between QML services
- `sequence_qml_service_call.puml` — runtime QML → RabbitMQ → backend round-trip

## Key Source Files

| File | Role |
|------|------|
| `web/js/app.js` : `_loadServiceGUIMultiTier()` | Detection waterfall orchestrator |
| `web/js/app.js` : `_loadQmlShellGUI()` | Creates wrapper, delegates to QtShellManager |
| `web/js/app.js` : `_tryQtWasmOrHtml()` | Tier 2/3 fallback chain |
| `web/js/QtShellManager.js` | Shared QML Shell lifecycle (detect, loadQml, clear) |
| `web/js/QtWasmLoader.js` | Per-service WASM lifecycle (detect, load, unload) |
| `web/js/SchemaRenderer.js` | Bootstrap form generation from JSON schema |
