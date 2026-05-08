# Schema-Driven UI Builder for MicroserviceBase Services

> **Status: ✅ Active.** Foundational plan for [ADR-021 Schema-Driven UI Builder](../adr/021-schema-driven-ui-builder.md).
> The schema-driven tier is implemented in `MicroserviceManagerGUI/web/js/SchemaRenderer.js`
> and is the first match in the [GUI loading waterfall](gui-loading-flow.md).
> Service providers can drop a `gui_schema.json` next to their service
> plugin to get a generated Bootstrap UI without writing HTML/JS.
>
> Note: the original "method discovery" flow described below referred to
> the RabbitMQ-era `methods_info` payload. With gRPC, the equivalent is
> server reflection — the same schema-driven UI generation works against
> the descriptor pool instead. See [`../runtime_model.md`](../runtime_model.md).

## Context

Service providers currently must hand-write HTML + JS files to create custom GUIs for their microservices. This requires Bootstrap/DOM knowledge and duplicates boilerplate (card layout, form inputs, request handling, result display). Most service GUIs follow the same pattern: form fields mapped to method arguments, call buttons, and result areas.

We provide **three tiers** of GUI authoring for service providers:

1. **Schema-driven** (recommended for most services) — define GUI in a JSON descriptor (`gui_schema.json`). A runtime renderer generates a fully functional Bootstrap UI — no HTML/JS authoring required.
2. **Qt for WebAssembly** (for complex/specialized UIs) — build a rich native-quality GUI in Qt/C++, compile to WASM, and load it as a self-contained app inside the MicroserviceManager panel. The Qt app handles its own rendering and communicates with the service via a JS bridge to `MM.serviceClient`.
3. **Hand-written HTML/JS** (full escape hatch) — write custom Bootstrap HTML + vanilla JS, as currently supported.

## Architecture

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

**Loading priority** in `loadServiceContent`:
1. If `gui_schema.json` exists in service folder → render via SchemaRenderer
2. Else if `{ServiceName}.wasm` (or `qtloader.js`) exists → load as Qt WASM app
3. Else if `{ServiceName}.html` exists → load as custom GUI (current behavior)
4. Else → show API Explorer (current fallback)

## Schema Format

```json
{
  "$schema": "microservice-gui/1.0",
  "service": "MyService",
  "layout": "tabs",
  "title": "My Service",
  "subtitle": "Does amazing things",
  "sections": [
    {
      "id": "greeting",
      "label": "Greeting",
      "components": [
        {
          "type": "method-form",
          "method": "svc_api_hello",
          "fields": [
            {
              "arg": "name",
              "label": "Your Name",
              "widget": "text",
              "placeholder": "World"
            }
          ],
          "submit_label": "Say Hello",
          "result_display": "text"
        }
      ]
    },
    {
      "id": "status",
      "label": "Status",
      "components": [
        {
          "type": "method-form",
          "method": "svc_api_get_version",
          "fields": [],
          "submit_label": "Get Version",
          "result_display": "text"
        },
        {
          "type": "text",
          "content": "Version information is fetched from the service."
        }
      ]
    }
  ]
}
```

### Component Types

| Type | Purpose | Key Properties |
|------|---------|---------------|
| `method-form` | Form → RPC call → result display | `method`, `fields[]`, `submit_label`, `result_display` |
| `result-table` | Display dict/list results as table | `method`, `columns[]`, `auto_refresh` |
| `text` | Static markdown/text block | `content` |
| `live-status` | Polling status badge | `method`, `interval_ms`, `format` |
| `custom` | Inline HTML escape hatch | `html`, `script` |

### Field Widget Types

| Widget | Renders As | For Types |
|--------|-----------|-----------|
| `text` | `<input type="text">` | str (default) |
| `number` | `<input type="number">` | int, float |
| `textarea` | `<textarea>` | str (long text) |
| `select` | `<select>` with options | str (enum) |
| `checkbox` | `<input type="checkbox">` | bool |
| `file` | File picker (base64 encode) | file/binary |

### Result Display Modes

| Mode | Renders As |
|------|-----------|
| `text` | `<div class="alert alert-info">` with text content |
| `json` | `<pre>` with formatted JSON |
| `table` | `<table class="table">` from dict/list |
| `image` | `<img>` from base64 data |
| `none` | No display (fire-and-forget) |

### Layout Options

| Layout | Behavior |
|--------|----------|
| `single` | All sections rendered vertically |
| `tabs` | Bootstrap nav-tabs, one section per tab |
| `accordion` | Bootstrap accordion, collapsible sections |

## Qt WASM Integration

### How It Works

A Qt WASM service GUI is a self-contained application compiled from C++ to WebAssembly. It runs inside the MicroserviceManager panel within a `<div>` container (no iframe). The Qt app owns its own canvas/rendering and communicates with the microservice backend via a JavaScript bridge exposed by `MM.serviceClient`.

```
┌──────────────────────────────────────────────────┐
│ MicroserviceManager GUI (#serviceContent)         │
│                                                    │
│  ┌─────────────────────────────────────────────┐  │
│  │ .card wrapper (Bootstrap)                    │  │
│  │  ┌───────────────────────────────────────┐  │  │
│  │  │ <canvas id="qtcanvas">                │  │  │
│  │  │   Qt WASM app renders here            │  │  │
│  │  │   (self-contained, own event loop)    │  │  │
│  │  └───────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────┘  │
│                                                    │
│  JS Bridge: window.callMicroservice(name,method,  │
│             args) → MM.serviceClient.request...   │
└──────────────────────────────────────────────────┘
```

### Qt WASM Service Folder Structure

```
web/services/MyQtService1.0.0/
├── MyQtService.html          # Bootstrap card with <canvas> placeholder
├── MyQtService.js            # Loader: init Qt module, expose JS bridge, lifecycle hooks
├── myqtservice.js            # Emscripten-generated JS (Qt loader/glue)
├── myqtservice.wasm          # Compiled Qt WASM binary
└── qtlogo.svg                # (optional) assets
```

### JS Bridge Pattern

The Qt WASM app calls microservice methods through a global JS bridge:

```javascript
// Exposed by MyQtService.js — callable from Qt C++ via emscripten::val
window.callMicroservice = function(serviceName, method, args) {
    var routingKey = MM.servicesInfor[serviceName].routing_key;
    return MM.requestService(
        { method: method, args: args },
        'services_request',
        routingKey
    );
};
```

From Qt C++ side (using Emscripten):
```cpp
#include <emscripten/val.h>
emscripten::val window = emscripten::val::global("window");
emscripten::val result = window.call<emscripten::val>(
    "callMicroservice", std::string("MyService"),
    std::string("svc_api_hello"), emscripten::val::array(args));
```

### Template Example: `examples/qt_wasm_service_template/`

A complete template for building Qt WASM service GUIs:

```
examples/qt_wasm_service_template/
├── README.md                         # Build instructions, Qt setup, deployment guide
├── CMakeLists.txt                    # Qt6 + Emscripten build system
├── src/
│   ├── main.cpp                      # QApplication entry, main window
│   ├── MainWidget.h/cpp              # Main UI widget with controls
│   └── ServiceBridge.h/cpp           # C++ wrapper around JS bridge (callMicroservice)
├── GUIs/
│   ├── MyQtWasmService.html          # Bootstrap card + canvas container
│   └── MyQtWasmService.js            # Qt WASM loader + lifecycle + JS bridge
└── build_wasm.sh                     # Helper script: cmake + emscripten toolchain
```

#### Key template files:

**`GUIs/MyQtWasmService.html`** — Container loaded by MicroserviceManager:
```html
<div class="card" style="height: 100%; width: 100%; top: 0;">
  <div class="card-header d-flex justify-content-between align-items-center">
    <div>
      <h5 class="card-title mb-0">MyQtWasmService</h5>
      <small class="text-muted">Qt WASM Template Service</small>
    </div>
    <span class="badge bg-info" id="qtStatusBadge">Loading...</span>
  </div>
  <div class="card-body p-0" style="height: calc(100% - 60px); overflow: hidden;">
    <div id="qtContainer" style="width: 100%; height: 100%;"></div>
  </div>
</div>
```

**`GUIs/MyQtWasmService.js`** — Loader and bridge:
```javascript
var MM = window.MicroserviceManager;
var QtWasmApp = { instance: null, SERVICE_NAME: 'MyQtWasmService' };

// JS bridge for Qt C++ to call microservice methods
window.callMicroservice = function(serviceName, method, args) {
    var routingKey = MM.servicesInfor[serviceName].routing_key;
    return MM.requestService(
        { method: method, args: args },
        'services_request', routingKey
    );
};

function loadMyQtWasmService() {
    var container = document.getElementById('qtContainer');
    var badge = document.getElementById('qtStatusBadge');
    var folderBase = 'services/' + QtWasmApp.SERVICE_NAME +
        MM.servicesInfor[QtWasmApp.SERVICE_NAME].version + '/';

    var script = document.createElement('script');
    script.src = folderBase + 'myqtwasmservice.js';
    script.onload = function() {
        // Emscripten module init
        createQtAppInstance({ qtContainerElements: [container] })
            .then(function(instance) {
                QtWasmApp.instance = instance;
                badge.textContent = 'Running';
                badge.className = 'badge bg-success';
            })
            .catch(function(err) {
                badge.textContent = 'Error';
                badge.className = 'badge bg-danger';
                MM.showToast('Qt WASM', 'Failed to load: ' + err, 'warning');
            });
    };
    document.head.appendChild(script);
}

function unloadMyQtWasmService() {
    if (QtWasmApp.instance) {
        QtWasmApp.instance.delete();
        QtWasmApp.instance = null;
    }
}

window.loadMyQtWasmService = loadMyQtWasmService;
window.unloadMyQtWasmService = unloadMyQtWasmService;
loadMyQtWasmService();
```

**`src/ServiceBridge.h`** — C++ helper for calling microservices from Qt:
```cpp
#pragma once
#include <QObject>
#include <QString>
#include <QJsonArray>
#include <QJsonObject>

class ServiceBridge : public QObject {
    Q_OBJECT
public:
    // Call a microservice method via the JS bridge
    Q_INVOKABLE void callService(const QString& serviceName,
                                  const QString& method,
                                  const QJsonArray& args);
signals:
    void responseReceived(const QString& method, const QJsonObject& result);
    void errorOccurred(const QString& method, const QString& error);
};
```

**`src/MainWidget.cpp`** — Example Qt UI calling a service:
```cpp
void MainWidget::onHelloClicked() {
    QJsonArray args;
    args.append(m_nameEdit->text());
    m_bridge->callService("MyQtWasmService", "svc_api_hello", args);
}

void MainWidget::onResponse(const QString& method, const QJsonObject& result) {
    m_resultLabel->setText(result["result_data"].toString());
}
```

### Build & Deploy

Service developers have two build workflows:

#### Qt Creator (Recommended for development)

Qt Creator provides a full visual IDE experience for WASM development:

1. **Kit setup**: Edit > Preferences > Kits — add Emscripten compiler + Qt WASM target.
   Qt Creator auto-detects Emscripten if `emsdk` is on `PATH`.
2. **Open project**: File > Open > select `CMakeLists.txt` > choose Emscripten kit.
3. **UI design**: Use **Qt Designer** (`.ui` files with drag-and-drop) or programmatic
   layout (`QVBoxLayout`, `QPushButton`, etc.) — both compile to WASM identically.
4. **Build & Run**: Click Build (Ctrl+B), then Run (Ctrl+R) — auto-launches browser preview.
5. **Debug**: `qDebug()` output appears in browser DevTools console; Qt Creator supports
   source-level WASM debugging via Chrome DevTools integration.

#### Command line (for CI/CD)

```bash
# Prerequisites: Qt 6.5+ with wasm_singlethread target, Emscripten 3.1.25+
# 1. Configure
qt-cmake -B build -S . -DQT_HOST_PATH=/path/to/qt/gcc_64 \
    -DCMAKE_TOOLCHAIN_FILE=/path/to/emsdk/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake

# 2. Build
cmake --build build

# 3. Deploy — copy outputs to GUIs/ folder
cp build/myqtwasmservice.js build/myqtwasmservice.wasm GUIs/

# 4. Install in MicroserviceManager
# Copy GUIs/ contents to web/services/MyQtWasmService1.0.0/
```

## Files to Create/Modify

### New Files

1. **`web/js/SchemaRenderer.js`** — Core renderer module (~300 lines)
   - `SchemaRenderer.render(schema, containerEl, serviceName)` — main entry
   - `_renderLayout(schema, container)` — tabs/accordion/single layout
   - `_renderSection(section, container)` — section wrapper
   - `_renderComponent(component, container, serviceName)` — dispatch by type
   - `_renderMethodForm(comp, container, serviceName)` — form + submit + result
   - `_renderResultTable(comp, container, serviceName)` — auto-refresh table
   - `_renderText(comp, container)` — static text
   - `_renderLiveStatus(comp, container, serviceName)` — polling badge
   - `_renderCustom(comp, container)` — innerHTML + eval script
   - `_buildField(field, methodInfo)` — create input from widget spec
   - `_collectArgs(formEl, fields)` — gather values, cast types
   - `_displayResult(resultEl, data, mode)` — render by display mode
   - `_callMethod(serviceName, method, args)` — wrapper around `MM.requestService()`
   - Exposed as `window.SchemaRenderer` (follows MM namespace pattern)

2. **`web/js/SchemaAutoGen.js`** — Auto-generate schema from methods_info (~100 lines)
   - `SchemaAutoGen.fromMethodsInfo(serviceName, serviceInfo)` → schema JSON
   - Maps `condition: "required"` → no default; `type: "int"` → widget `number`, etc.
   - Generates one section per method, `layout: "tabs"` if >1 method, `single` if 1
   - Used as fallback when no `gui_schema.json` and no custom HTML exists

3. **`web/js/QtWasmLoader.js`** — Qt WASM loading utility (~80 lines)
   - `QtWasmLoader.detect(folderPath)` — check if folder contains `.wasm` file
   - `QtWasmLoader.load(folderPath, containerEl, serviceName)` — load Qt WASM app into container
   - `QtWasmLoader.unload(serviceName)` — cleanup Qt instance
   - Sets up `window.callMicroservice` JS bridge if not already defined
   - Exposed as `window.QtWasmLoader`

4. **`examples/qt_wasm_service_template/`** — Complete Qt WASM template
   - `README.md` — Prerequisites (Qt 6.5+, Emscripten), build instructions, deployment guide
   - `CMakeLists.txt` — Qt6 WASM build config
   - `src/main.cpp` — QApplication entry point
   - `src/MainWidget.h/cpp` — Example Qt widget with form + service calls
   - `src/ServiceBridge.h/cpp` — C++ wrapper around JS bridge (`callMicroservice`)
   - `GUIs/MyQtWasmService.html` — Bootstrap card with canvas container
   - `GUIs/MyQtWasmService.js` — Loader, lifecycle hooks, JS bridge setup
   - `build_wasm.sh` — Build helper script

### Modified Files

5. **`web/js/app.js`** — Integration points
   - `loadServiceContent` (~line 440): Add multi-tier GUI detection
     1. Try fetch `gui_schema.json` → `SchemaRenderer.render()`
     2. Check for `.wasm` file → `QtWasmLoader.load()`
     3. Try fetch `{ServiceName}.html` → custom HTML (current behavior)
     4. Fallback → API Explorer
   - `showServiceAPIExplorer` (~line 807): Use SchemaAutoGen + SchemaRenderer
     - If `methods_info` available → `SchemaAutoGen.fromMethodsInfo()` → `SchemaRenderer.render()`
     - Else → existing manual API Explorer HTML (fallback for services with no metadata)

6. **`web/index.html`** — Add script tags
   - `<script src="js/SchemaRenderer.js"></script>`
   - `<script src="js/SchemaAutoGen.js"></script>`
   - `<script src="js/QtWasmLoader.js"></script>`

7. **`web/js/ServiceCreator.js`** — Redesign Step 3 (GUI Support)
   - Replace raw HTML editor with schema builder form
   - Visual section/component editor using the schema format
   - Method selector pulls from Step 2's defined methods
   - Live preview using SchemaRenderer
   - "Export as HTML/JS" button for providers who want to customize further
   - Keep "Upload custom HTML/JS" as alternative tab

8. **`adapters/ui_bridge/fastapi_bridge.py`** — Schema endpoint
   - New `/api/service-schema/{service_name}` endpoint
   - Returns `gui_schema.json` content from service folder if exists
   - Falls back to auto-generated schema from `methods_info`

## Key Design Decisions

1. **Three-tier approach** — Schema-driven for standard services (80% of cases), Qt WASM for complex/specialized UIs (HMI, visualization), hand-written HTML/JS as escape hatch.

2. **Schema file is optional** — services work without it. Auto-generation from `methods_info` provides a reasonable default that's better than raw API Explorer.

3. **Qt WASM is self-contained** — no DOM integration needed. The Qt app renders into its own `<canvas>` inside a Bootstrap card wrapper. It communicates with the service via the `window.callMicroservice` JS bridge, not via DOM manipulation.

4. **SchemaRenderer is pure client-side** — no server changes needed for rendering. The schema is just a JSON file in the service's GUI folder.

5. **Backward compatible** — existing HTML/JS GUIs continue to work unchanged. Detection order: schema → Qt WASM → HTML → API Explorer.

6. **No new dependencies** — uses Bootstrap 5 (already loaded via CDN) and vanilla JS (matches codebase pattern: no modules, `var`, browser-compatible). Qt WASM dependencies are per-service (compiled by the service provider).

7. **`method-form` and Qt bridge both reuse `MM.requestService()`** — same RPC pattern as hand-written GUIs, consistent transport layer.

## Implementation Phases

### Phase 1: SchemaRenderer core (`web/js/SchemaRenderer.js`)
- Implement all component types and layout modes
- Add to `web/index.html`
- Test standalone with a hardcoded schema

### Phase 2: SchemaAutoGen (`web/js/SchemaAutoGen.js`)
- Generate schema from `methods_info`
- Map argument types → widget types
- Test with SampleService and MyCppService metadata

### Phase 3: QtWasmLoader (`web/js/QtWasmLoader.js`)
- Implement WASM detection and loading
- Set up `window.callMicroservice` JS bridge
- Handle lifecycle (load/unload, cleanup on panel switch)

### Phase 4: app.js integration
- Modify `loadServiceContent` with multi-tier detection (schema → WASM → HTML → API Explorer)
- Modify `showServiceAPIExplorer` to use SchemaAutoGen + SchemaRenderer
- Test full flow for all three tiers

### Phase 5: Qt WASM template (`examples/qt_wasm_service_template/`)
- Create complete template with CMakeLists.txt, source files, GUIs/ folder
- ServiceBridge C++ helper wrapping the JS bridge
- Example MainWidget with form + service calls
- README with build instructions (Qt 6.5+ / Emscripten)
- build_wasm.sh helper script

### Phase 6: ServiceCreator Step 3 redesign
- Replace HTML editor with schema builder form
- Visual section/component editor
- Live preview panel
- Export options (schema JSON, or HTML/JS pair)
- Keep "Upload custom HTML/JS" as alternative tab

### Phase 7: Bridge endpoint + documentation
- Add `/api/service-schema/{service_name}` endpoint
- Create example `gui_schema.json` in `examples/service_template/GUIs/`
- Update README / docs

## Verification

### Schema-Driven
1. Start RabbitMQ + SampleService (no gui_schema.json) → auto-generated schema UI renders with proper forms, replacing raw API Explorer
2. Create `gui_schema.json` for SampleService with tabs layout → tabbed UI appears with form fields matching methods
3. Click "Execute" on a method-form → RPC call fires, result displays in chosen mode (text/json/table)
4. Test all layout modes: single, tabs, accordion
5. Test all widget types: text, number, textarea, select, checkbox
6. Test all result display modes: text, json, table, image, none

### Qt WASM
7. Build Qt WASM template with Emscripten → produces `.wasm` + `.js` output files
8. Copy compiled files to `web/services/MyQtWasmService1.0.0/` → QtWasmLoader detects and loads
9. Qt app renders in canvas inside Bootstrap card → status badge shows "Running"
10. Click button in Qt UI → `callMicroservice()` bridge fires RPC → result displayed in Qt widget
11. Switch to another service panel → `unloadMyQtWasmService()` cleans up Qt instance

### Backward Compatibility
12. Service with existing HTML/JS GUI (e.g., MyCppService) → still loads custom HTML unchanged
13. Service with no GUI files at all → API Explorer fallback still works

### ServiceCreator
14. ServiceCreator wizard Step 3 → visual schema editor → live preview matches → generates valid `gui_schema.json`
