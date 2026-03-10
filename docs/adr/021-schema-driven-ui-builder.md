# ADR-021: Multi-Tier GUI Loading Architecture

## Status

Accepted

## Date

2026-02-25

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-25 | 1.0 | Initial version — schema-driven UI builder |
| 2026-03-10 | 2.0 | Merged ADR-022 — added Qt C++ service template UI loading (Widget / QML / WASM) |

## Context

Service providers currently must hand-write HTML + JS files to create custom GUIs for their microservices. This requires Bootstrap/DOM knowledge and duplicates boilerplate. Most service GUIs follow the same pattern: form fields mapped to method arguments, call buttons, and result areas.

Additionally, Qt C++ services need native-quality UIs that go beyond what HTML/JS can offer. Three distinct Qt rendering strategies exist — QML declarative UI, Qt Designer Widget forms, and fully compiled WASM applications — each with different build requirements, loading mechanisms, and runtime tradeoffs.

We need a unified multi-tier architecture that supports all GUI authoring approaches, from zero-code schema definitions to fully compiled Qt applications, with clear detection priority and consistent lifecycle management.

## Decision

We provide **four tiers** of GUI authoring, grouped by technology. Detection follows a waterfall priority in `_loadServiceGUIMultiTier()` in `app.js`:

### Loading Waterfall

```
Service folder scanned
        │
        ├─ gui_schema.json found?
        │   ├─ renderer: "qt"     ──┐
        │   ├─ renderer: "widget" ──┤── Tier 1: Qt C++
        │   └─ (no renderer)      ──── Tier 2: Schema (Bootstrap)
        │
        ├─ .qml file detected?    ──┐
        ├─ .ui file detected?     ──┤── Tier 1: Qt C++
        ├─ .wasm file detected?   ──┘
        │
        ├─ .html file found?      ──── Tier 3: Custom HTML/JS
        │
        └─ nothing found          ──── Tier 4: Auto-generated API Explorer
```

See [`flow_gui_loading_tiers.puml`](../diagrams/flow_gui_loading_tiers.puml) for the complete decision flow diagram.

---

### Tier 1: Qt C++

Native-quality UIs for Qt C++ services, with three sub-types sharing the same `callMicroservice` JS bridge.

#### 1a. QML Shell (Shared WASM Engine)

**Trigger:** `gui_schema.json` with `"renderer": "qt"`, or `.qml` file detected in service folder
**Loader:** `QtShellManager.js`

When triggered via schema, the QML file path comes from `schema.qml_file` (defaults to `ServiceUI.qml`). When triggered by file detection, `QtShellManager.detect(folderPath)` scans via `/api/list-dir/` and prefers `ServiceUI.qml`.

A shared `qtshell.wasm` (~9 MB gzip) is loaded once. Subsequent services only fetch the `.qml` file (~5 KB), which is hot-swapped into the running QML engine via `qtshell_loadQml(qmlUrl)`.

```
┌─────────────────────────────────────────────┐
│ MicroserviceManagerGUI                       │
│  ┌────────────────────────────────────────┐  │
│  │ qtshell.wasm  (loaded once, ~9 MB gz)  │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │ ServiceUI.qml  (per service)     │  │  │
│  │  │ (~5 KB, hot-swappable)           │  │  │
│  │  └──────────────────────────────────┘  │  │
│  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**Service template:** `examples/cpp_qml_service_template/`
- `.qml` files are NOT compiled — interpreted at runtime by the shell engine
- Desktop: native Qt app runs `.qml` via local QML engine
- Web: `.qml` fetched and loaded into `qtshell.wasm`

#### 1b. Widget Shell (Shared WASM Engine)

**Trigger:** `gui_schema.json` with `"renderer": "widget"`, or `.ui` file detected in service folder
**Loader:** `WidgetShellManager.js`

When triggered via schema, the UI file path comes from `schema.ui_file` (defaults to `ServiceUI.ui`). When triggered by file detection, `WidgetShellManager.detect(folderPath)` scans via `/api/list-dir/` and prefers `ServiceUI.ui`.

A shared `widgetshell.wasm` (~9 MB gzip) is loaded once. `.ui` files (Qt Designer XML) are hot-swapped via `widgetshell_loadUi(uiXml)`.

**Service template:** `examples/cpp_widget_service_template/`
- `.ui` files are XML (Qt Designer format) — NOT compiled, loaded at runtime by `QUiLoader`
- Desktop: native Qt app loads `.ui` via `QUiLoader`
- Web: `.ui` XML loaded into `widgetshell.wasm`

#### 1c. Per-Service WASM (Standalone Binary)

**Trigger:** `.wasm` + matching `.js` file found in service folder
**Loader:** `QtWasmLoader.js`

A fully compiled Qt application rendered into its own `<canvas>`. Each service is a standalone Emscripten binary (multi-MB).

```
┌──────────────────────────────────────────────┐
│ MicroserviceManagerGUI                        │
│  ┌────────────────────────────────────────┐   │
│  │ .card wrapper (Bootstrap)              │   │
│  │  ┌──────────────────────────────────┐  │   │
│  │  │ <canvas>  myservice.wasm         │  │   │
│  │  │ (full Qt app, self-contained)    │  │   │
│  │  └──────────────────────────────────┘  │   │
│  └────────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

Loader searches for init function in order: `window[baseName + '_entry']` → `window.createQtAppInstance` → `window[baseName + 'Module']` → `window.Module`.

**Limitation:** WASM instances cannot be re-created after unload (Emscripten limitation).

**Build requirements:** Qt 6.5+ `wasm_singlethread`, Emscripten 3.1.50+, CMake 3.21+, Ninja.

**Service template:** `examples/qt_wasm_service_template/`

#### Qt Sub-Type Comparison

| Aspect | QML Shell (1a) | Widget Shell (1b) | Per-Service WASM (1c) |
|--------|---------------|-------------------|----------------------|
| **Initial download** | ~9 MB (once) | ~9 MB (once) | Multi-MB (per service) |
| **Per-service cost** | ~5 KB (.qml) | ~10 KB (.ui) | Full binary |
| **Hot-reload** | Yes (swap .qml) | Yes (swap .ui) | No (rebuild required) |
| **Complexity** | Medium | Low (drag-and-drop) | High (full Qt + Emscripten) |
| **Best for** | Animated/dynamic UIs | Form-based UIs | Complex standalone apps |
| **Reusable after unload** | Yes (shell stays) | Yes (shell stays) | No (instance destroyed) |

#### JavaScript Bridge

All three Qt sub-types share the same JS bridge for service communication:

```javascript
window.callMicroservice = function(serviceName, method, args) {
    var serviceInfo = MM.servicesInfor[serviceName];
    var routingKey = serviceInfo.routing_key;
    return MM.requestService(
        { method: method, args: args },
        'services_request',
        routingKey
    );
};
```

For shared shells (QML/Widget), per-service response/error callbacks are managed via `activateBridge()` which re-registers `window._shellResponseCallback()` when switching between services.

---

### Tier 2: Schema-Driven (Bootstrap)

**Trigger:** `gui_schema.json` without `renderer` field (or unrecognized value)
**Loader:** `SchemaRenderer.js`

A JSON descriptor defines the GUI layout, and a runtime renderer generates a fully functional Bootstrap UI — no HTML/JS authoring required.

```json
{
  "$schema": "microservice-gui/1.0",
  "service": "MyService",
  "layout": "tabs",
  "title": "My Service",
  "sections": [
    {
      "id": "greeting",
      "label": "Greeting",
      "components": [
        {
          "type": "method-form",
          "method": "svc_api_hello",
          "fields": [
            { "arg": "name", "label": "Your Name", "widget": "text", "placeholder": "World" }
          ],
          "submit_label": "Say Hello",
          "result_display": "text"
        }
      ]
    }
  ]
}
```

```
Service registration (methods_info)
        │
        ▼
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐
│ gui_schema.json  │────▶│ SchemaRenderer.js │────▶│ Bootstrap DOM │
│ (per service)    │     │ (runtime engine)  │     │ (live UI)     │
└─────────────────┘     └──────────────────┘     └───────────────┘
        ▲
        │ auto-generate
┌─────────────────┐
│ methods_info     │
│ (from registry)  │
└─────────────────┘
```

#### Component Types

| Type | Purpose | Key Properties |
|------|---------|---------------|
| `method-form` | Form → RPC call → result display | `method`, `fields[]`, `submit_label`, `result_display` |
| `result-table` | Display dict/list results as table | `method`, `columns[]`, `auto_refresh` |
| `text` | Static text block | `content` |
| `live-status` | Polling status badge | `method`, `interval_ms`, `format` |
| `custom` | Inline HTML escape hatch | `html`, `script` |

#### Field Widget Types

| Widget | Renders As | For Types |
|--------|-----------|-----------|
| `text` | `<input type="text">` | str (default) |
| `number` | `<input type="number">` | int, float |
| `textarea` | `<textarea>` | str (long text) |
| `select` | `<select>` with options | str (enum) |
| `checkbox` | `<input type="checkbox">` | bool |
| `file` | File picker | file/binary |

#### Result Display Modes

| Mode | Renders As |
|------|-----------|
| `text` | `<div class="alert alert-info">` |
| `json` | `<pre>` with formatted JSON |
| `table` | `<table class="table">` from dict/list |
| `image` | `<img>` from base64 data |
| `none` | No display (fire-and-forget) |

#### Layout Options

| Layout | Behavior |
|--------|----------|
| `single` | All sections rendered vertically |
| `tabs` | Bootstrap nav-tabs, one section per tab |
| `accordion` | Bootstrap accordion, collapsible sections |

---

### Tier 3: Custom HTML/JS

**Trigger:** `{ServiceName}.html` found in service folder (or any `.html` via directory listing)
**Loader:** `_fetchAndRenderServiceGUI()` in `app.js`

Existing behavior — HTML injected via `innerHTML`, companion `.js` loaded via `<script>` tag. Services use `loadServiceName()` / `unloadServiceName()` lifecycle convention.

---

### Tier 4: Auto-Generated API Explorer

**Trigger:** No GUI assets found at all
**Loader:** `showServiceAPIExplorer()` / `SchemaAutoGen.js`

Auto-generates a schema from `methods_info` metadata and renders it via SchemaRenderer.

---

### Panel Caching & Visibility

| Panel type | Hide method | Reason |
|-----------|-------------|--------|
| QML / Widget / WASM | `visibility:hidden` + `position:absolute` | Canvas requires non-zero dimensions; `display:none` would crash `requestAnimationFrame` |
| HTML / Schema | `display:none` | No canvas, safe to remove from layout flow |

Each cached panel stores its type in `data-shell-type` attribute (`'qml'`, `'widget'`, or `'wasm'`).

### Files Created/Modified

#### New Files

| File | Purpose |
|------|---------|
| `web/js/SchemaRenderer.js` | Core renderer — schema JSON → Bootstrap DOM |
| `web/js/SchemaAutoGen.js` | Auto-generate schema from `methods_info` metadata |
| `web/js/QtWasmLoader.js` | Detect, load, unload per-service Qt WASM apps |
| `web/js/QtShellManager.js` | Shared QML shell — load/swap `.qml` files |
| `web/js/WidgetShellManager.js` | Shared Widget shell — load/swap `.ui` files |
| `examples/qt_wasm_service_template/` | Per-service WASM template (CMake, C++, GUIs) |
| `examples/cpp_qml_service_template/` | QML service template |
| `examples/cpp_widget_service_template/` | Widget service template |
| `examples/service_template/GUIs/gui_schema.json` | Example schema file |

#### Modified Files

| File | Changes |
|------|---------|
| `web/index.html` | Added `<script>` tags for new JS files |
| `web/js/app.js` | Multi-tier GUI detection waterfall; panel caching with shell-type awareness |
| `web/js/ServiceCreator.js` | Step 3 redesigned with Schema Builder tab + Custom HTML/JS tab |
| `adapters/ui_bridge/fastapi_bridge.py` | New `/api/service-schema/{service_name}` endpoint; `/api/list-dir/` for file detection |

## Consequences

### Positive

- Service providers can create functional GUIs with zero HTML/JS knowledge — just define a JSON schema
- Auto-generated schema from `methods_info` provides a better default than raw API Explorer
- QML and Widget services share a single WASM shell — avoids multi-MB downloads per service
- `.qml` and `.ui` files are hot-swappable — UI changes don't require rebuilding the shell
- Per-service WASM provides full escape hatch for complex standalone applications
- All Qt types use the same `callMicroservice` JS bridge — consistent service communication
- Fully backward compatible — existing HTML/JS GUIs continue to work unchanged
- ServiceCreator wizard now has a visual schema builder with live preview

### Negative

- Schema format is limited to predefined component types — very custom layouts still need HTML/JS
- Two separate shells (QML + Widget) must be maintained and built independently
- Per-service WASM instances cannot be re-created after unload (Emscripten limitation)
- Shared shell size (~9 MB gzipped) is a large initial download, even though amortized across services

### Neutral

- Schema file is optional — services work without it
- `custom` component type provides an HTML escape hatch within schema-driven GUIs
- Services choose their tier by which files they include — no explicit configuration needed
- Desktop (native Qt) and web (WASM) share the same `.qml`/`.ui` source files

## Alternatives Considered

### 1. Form auto-generation only (no schema file) (Rejected)

Auto-generate all GUIs directly from `methods_info` with no user-authored schema.

Rejected because:
- No control over layout, labels, grouping, or display modes
- All services would look identical
- No way to add static text, live status, or custom components

### 2. Single unified Qt shell for all three types (Rejected)

Combine QML engine + QUiLoader + full widget support into one WASM binary.

Rejected because:
- Would produce an even larger binary (~15-20 MB)
- QML and Widget runtime have different initialization requirements
- Loading both engines when only one is needed wastes resources

### 3. Compile .qml/.ui into per-service WASM binaries (Rejected)

Each service compiles its UI files into a standalone WASM binary.

Rejected because:
- Defeats the purpose of lightweight UI definitions
- Multi-MB download per service, even for a simple form
- No hot-reload — any UI change requires full Emscripten rebuild

### 4. iframe-based Qt WASM embedding (Rejected)

Load Qt WASM apps inside an `<iframe>` instead of directly in the DOM.

Rejected because:
- iframe isolation makes JS bridge communication harder
- Extra overhead and potential security restrictions
- Inconsistent styling with the parent MicroserviceManager theme

### 5. Transpile QML to HTML/JS (Rejected)

Convert QML declarations to equivalent HTML + CSS + JavaScript at build time.

Rejected because:
- QML semantics (property bindings, animations, state machines) have no direct HTML equivalent
- Would produce a fragile, non-standard transpiler requiring ongoing maintenance
- Loses access to Qt's rendering pipeline and native controls

### 6. React/Vue component system (Rejected)

Use a modern JS framework for the schema renderer.

Rejected because:
- Would introduce a build step and Node.js dependency
- Breaks the existing pattern of vanilla JS, browser-compatible, no modules
- Overkill for rendering forms from a JSON descriptor

## References

- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/SchemaRenderer.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/SchemaAutoGen.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/QtWasmLoader.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/QtShellManager.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/WidgetShellManager.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/ServiceCreator.js`
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py`
- Template: `examples/cpp_qml_service_template/`
- Template: `examples/cpp_widget_service_template/`
- Template: `examples/qt_wasm_service_template/`
- Example schema: `examples/service_template/GUIs/gui_schema.json`
- Diagram: [`docs/diagrams/flow_gui_loading_tiers.puml`](../diagrams/flow_gui_loading_tiers.puml)
- Related: [ADR-019: Service-Delivered GUI Plugins](019-service-delivered-gui-plugins.md)
