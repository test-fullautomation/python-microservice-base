# ADR-021: Schema-Driven UI Builder for Services

## Status

Accepted

## Date

2026-02-25

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-25 | 1.0 | Initial version |

## Context

Service providers currently must hand-write HTML + JS files to create custom GUIs for their microservices. This requires Bootstrap/DOM knowledge and duplicates boilerplate (card layout, form inputs, request handling, result display). Most service GUIs follow the same pattern: form fields mapped to method arguments, call buttons, and result areas.

We need a simpler way for service providers to create GUIs, while still supporting complex/specialized UIs for advanced use cases.

## Decision

We provide **three tiers** of GUI authoring for service providers:

1. **Schema-driven** (recommended for most services) — define GUI in a JSON descriptor (`gui_schema.json`). A runtime renderer generates a fully functional Bootstrap UI — no HTML/JS authoring required.
2. **Qt for WebAssembly** (for complex/specialized UIs) — build a rich native-quality GUI in Qt/C++, compile to WASM, and load it as a self-contained app inside the MicroserviceManager panel.
3. **Hand-written HTML/JS** (full escape hatch) — write custom Bootstrap HTML + vanilla JS, as currently supported.

### Architecture

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
2. Else if `.wasm` file exists → load via QtWasmLoader
3. Else if `{ServiceName}.html` exists → load as custom GUI (current behavior)
4. Else → show API Explorer (auto-generated schema from `methods_info`)

### Schema Format

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

### Qt WASM Integration

A Qt WASM service GUI is a self-contained application compiled from C++ to WebAssembly. It renders into its own `<canvas>` inside a Bootstrap card wrapper and communicates with microservices via the `window.callMicroservice` JS bridge.

```
┌──────────────────────────────────────────────────┐
│ MicroserviceManager GUI (#serviceContent)         │
│  ┌─────────────────────────────────────────────┐  │
│  │ .card wrapper (Bootstrap)                    │  │
│  │  ┌───────────────────────────────────────┐  │  │
│  │  │ <canvas>  Qt WASM app renders here    │  │  │
│  │  └───────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────┘  │
│  JS Bridge: window.callMicroservice(name,method,  │
│             args) → MM.requestService(...)         │
└──────────────────────────────────────────────────┘
```

### Files Created/Modified

#### New Files

| File | Purpose |
|------|---------|
| `web/js/SchemaRenderer.js` | Core renderer — schema JSON → Bootstrap DOM |
| `web/js/SchemaAutoGen.js` | Auto-generate schema from `methods_info` metadata |
| `web/js/QtWasmLoader.js` | Detect, load, unload Qt WASM apps |
| `examples/qt_wasm_service_template/` | Complete Qt WASM template (CMake, C++, GUIs) |
| `examples/service_template/GUIs/gui_schema.json` | Example schema file |

#### Modified Files

| File | Changes |
|------|---------|
| `web/index.html` | Added `<script>` tags for new JS files |
| `web/js/app.js` | Multi-tier GUI detection in `loadServiceContent`; SchemaAutoGen in API Explorer |
| `web/js/ServiceCreator.js` | Step 3 redesigned with Schema Builder tab + Custom HTML/JS tab |
| `adapters/ui_bridge/fastapi_bridge.py` | New `/api/service-schema/{service_name}` endpoint; schema support in scaffold |

## Consequences

### Positive

- Service providers can create functional GUIs with zero HTML/JS knowledge — just define a JSON schema
- Auto-generated schema from `methods_info` provides a better default than raw API Explorer
- Qt WASM support enables rich, native-quality UIs for complex services (HMI, visualization)
- ServiceCreator wizard now has a visual schema builder with live preview
- Fully backward compatible — existing HTML/JS GUIs continue to work unchanged

### Negative

- Schema format is limited to predefined component types — very custom layouts still need HTML/JS
- Qt WASM requires Qt 6.5+ and Emscripten toolchain — higher barrier for that tier
- Additional JS files loaded on every page (SchemaRenderer, SchemaAutoGen, QtWasmLoader)

### Neutral

- Schema file is optional — services work without it
- `custom` component type provides an HTML escape hatch within schema-driven GUIs
- Three-tier approach means providers must choose which tier fits their needs

## Alternatives Considered

### 1. Form auto-generation only (no schema file) (Rejected)

Auto-generate all GUIs directly from `methods_info` with no user-authored schema.

Rejected because:
- No control over layout, labels, grouping, or display modes
- All services would look identical
- No way to add static text, live status, or custom components

### 2. iframe-based Qt WASM embedding (Rejected)

Load Qt WASM apps inside an `<iframe>` instead of directly in the DOM.

Rejected because:
- iframe isolation makes JS bridge communication harder
- Extra overhead and potential security restrictions
- Inconsistent styling with the parent MicroserviceManager theme

### 3. React/Vue component system (Rejected)

Use a modern JS framework for the schema renderer.

Rejected because:
- Would introduce a build step and Node.js dependency
- Breaks the existing pattern of vanilla JS, browser-compatible, no modules
- Overkill for rendering forms from a JSON descriptor

## References

- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/SchemaRenderer.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/SchemaAutoGen.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/QtWasmLoader.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js`
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/ServiceCreator.js`
- Source: `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py`
- Template: `examples/qt_wasm_service_template/`
- Example schema: `examples/service_template/GUIs/gui_schema.json`
