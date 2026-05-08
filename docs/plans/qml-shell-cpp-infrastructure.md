# QML Shell + C++ Service Infrastructure

> **Status: ⚠️ Obsolete (pre-gRPC migration).** This plan describes a
> RabbitMQ-era ServiceBase + ServiceBridge that no longer exists. The
> QML shell idea is still on the roadmap but needs a fresh design
> against the current gRPC + Consul + Nomad runtime. See
> [`../changelog.md`](../changelog.md) for the migration that
> invalidated this design.
>
> Kept for reference because:
> - The Qt-WASM shell architecture concept (one ~9 MB binary loading
>   per-service `.qml` files at runtime) is still useful.
> - The `qml_*_template/` examples in [`examples/_legacy/`](../../examples/_legacy/README.md)
>   were written against this plan and remain in `_legacy/` for fork
>   maintainers.

## Context

Service developers familiar with Qt/C++ need to build microservices with GUIs using familiar tools (Qt Creator, drag-and-drop QML designer). Currently they must hand-write HTML/JS or compile a full ~13MB WASM binary per service.

We solve this with three pieces:
1. **C++ ServiceBase library** — mirrors Python MicroserviceBase, handles RabbitMQ transport, registration, request dispatch
2. **QML Shell** — a shared Qt WASM binary (~9MB, loaded once) that loads `.qml` files at runtime from service folders
3. **Service template** — shows the 3-part pattern: infrastructure (ServiceBase) → business API (`svc_api_*`) → UI (QML wired to the API)

## Architecture Overview

A C++ microservice has **two runtime components**:

```
┌─ Server/Desktop Process ──────────────────────┐    ┌─ Browser (QML Shell WASM) ─────────┐
│                                                │    │                                     │
│  MyQMLService : ServiceBase                       │    │  ServiceUI.qml (loaded at runtime)  │
│  ├─ Infrastructure (ServiceBase)               │    │  ├─ TextField, Button, ListView...  │
│  │   ├─ RabbitMQ transport                     │    │  └─ ServiceBridge.callService(       │
│  │   ├─ Registration / unregistration          │    │        "MyQMLService",                  │
│  │   ├─ Request dispatch (svc_api_* pattern)   │    │        "svc_api_hello", [name])      │
│  │   └─ Graceful shutdown                      │    │                                     │
│  └─ Business API                               │    │  ServiceBridge (C++ singleton)       │
│      ├─ svc_api_hello(name) → "Hello, name"   │    │  └─ emscripten → callMicroservice    │
│      ├─ svc_api_get_version() → "1.0.0"       │    │       → MM.requestService            │
│      └─ svc_api_compute(data) → result         │    │       → RabbitMQ → Service           │
│                                                │    │                                     │
└───────────────┬────────────────────────────────┘    └──────────────────┬──────────────────┘
                │          RabbitMQ                                      │
                └──────────── request/response ─────────────────────────┘
```

## Part 1: C++ ServiceBase Library

Mirrors Python `MicroserviceBase/domain/service_base.py`. Located at `MicroserviceBase/domain/service_base_cpp/`.

### Class Design

```cpp
// ServiceBase — abstract base class for all C++ microservices
class ServiceBase {
public:
    ServiceBase(const ServiceConfig& config);
    virtual ~ServiceBase();

    // Lifecycle
    void registerService();       // Publish to service_information exchange
    void unregisterService();     // Publish state:"off" event
    void serve();                 // Blocking consume loop
    void shutdown();              // Signal consume loop to stop

    // Built-in API methods
    json svc_api_get_version(const json& args);
    json svc_api_shutdown(const json& args);

protected:
    // Subclass registers methods in constructor
    void registerMethod(const std::string& name, ApiHandler handler, MethodInfo info);

    // Service-to-service RPC (call another service)
    json requestService(const json& requestData,
                        const std::string& exchange,
                        const std::string& routingKey,
                        int timeoutSec = 30);

private:
    // Request dispatch (matches Python dispatch_request)
    json dispatchRequest(const json& requestBody);
    void onRequest(/* AMQP callback params */);

    std::map<std::string, ApiHandler> _apiHandlers;
    std::map<std::string, MethodInfo> _methodsInfo;
    RabbitMQConnection _connection;
    ServiceConfig _config;
};
```

### Files

| File | Purpose |
|------|---------|
| `include/ServiceBase.h` | Abstract base class |
| `include/RabbitMQConnection.h` | RAII wrapper around rabbitmq-c |
| `include/ServiceConfig.h` | Config struct (name, version, routing_key, broker) |
| `include/ServiceMessages.h` | ServiceRequest, ServiceResponse, MethodInfo structs |
| `src/ServiceBase.cpp` | Lifecycle, dispatch, registration, consume loop |
| `src/RabbitMQConnection.cpp` | Connection management |
| `CMakeLists.txt` | Builds as a static library, uses vcpkg (rabbitmq-c, nlohmann-json) |

### Protocol Compliance (matches Python exactly)

| Aspect | Value |
|--------|-------|
| Registry exchange | `service_information` (topic) |
| Registry routing key | `service.information` |
| Request exchange | `services_request` (direct) |
| Service queue | `{service_name}` (purged on start) |
| Response | Default exchange, `reply_to` routing key |
| Message format | `{ "method": "...", "args": [...] }` → `{ "request": "...", "result": "pass\|fail\|exception", "result_data": ... }` |
| QoS prefetch | 1 |
| Delivery mode | 2 (persistent) |

### Based on existing code

The `examples/cpp_mfc_service_template/` already has `ServiceBase.h/cpp` and `RabbitMQConnection.h/cpp` that implement this. We extract and clean them into a reusable library (remove MFC/Windows dependencies, make cross-platform).

## Part 2: QML Shell (Shared WASM Binary)

A single Qt WASM app (~9MB compressed) that includes the QML engine. Loads service `.qml` files over HTTP at runtime.

### How It Works

```
User clicks service → app.js fetches service folder
  → finds ServiceUI.qml (or *.qml)
  → QtShellManager.loadQml(qmlUrl, container, serviceName)
    → If shell not loaded: load qtshell.wasm (one-time, cached)
    → Set ServiceBridge.serviceName = serviceName
    → QQmlComponent::loadUrl(qmlUrl, Asynchronous)
    → QML engine fetches .qml over HTTP, parses, renders
    → Service developer's QML UI appears with native Qt controls
```

### Shell C++ Classes

```
MicroserviceBase/MicroserviceManagerGUI/qt_qml_shell/src/

main.cpp
  └─ Registers ServiceBridge as QML singleton
  └─ Creates QQmlApplicationEngine
  └─ Exports EMSCRIPTEN_KEEPALIVE functions for JS calls

ServiceBridge : QObject  (registered as QML singleton "MicroserviceBase.ServiceBridge")
  Q_PROPERTY serviceName     ← set by JS when switching services
  Q_INVOKABLE callService(serviceName, method, args) → Promise via JS bridge
  signal responseReceived(method, resultData)
  signal errorOccurred(method, errorMessage)

ShellController : QObject  (manages QML loading lifecycle)
  Q_INVOKABLE loadQml(url)   ← called from JS via exported C function
  Q_INVOKABLE clearQml()     ← called when switching away
  signal qmlReady()
  signal qmlError(errorString)
```

### Service Developer's QML (example)

```qml
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import MicroserviceBase 1.0          // provided by the shell

ColumnLayout {
    spacing: 12
    padding: 16

    Label { text: "My Service"; font.pixelSize: 22; font.bold: true }

    GroupBox {
        title: "Say Hello"
        Layout.fillWidth: true
        ColumnLayout {
            TextField {
                id: nameInput
                placeholderText: "Enter your name"
                Layout.fillWidth: true
            }
            Button {
                text: "Say Hello"
                onClicked: ServiceBridge.callService(
                    "MyQMLService", "svc_api_hello", [nameInput.text])
            }
        }
    }

    // Result display
    GroupBox {
        title: "Result"
        Layout.fillWidth: true
        Label {
            id: resultLabel
            text: "..."
            wrapMode: Text.Wrap
        }
    }

    Connections {
        target: ServiceBridge
        function onResponseReceived(method, data) {
            resultLabel.text = data
        }
        function onErrorOccurred(method, error) {
            resultLabel.text = "Error: " + error
            resultLabel.color = "red"
        }
    }
}
```

### Shell Files

| File | Purpose |
|------|---------|
| `src/main.cpp` | QML engine setup, singleton registration, EMSCRIPTEN exports |
| `src/ServiceBridge.h/cpp` | QML-accessible service call bridge (enhanced from qt_wasm_service_template) |
| `src/ShellController.h/cpp` | Manages dynamic QML loading/unloading lifecycle |
| `CMakeLists.txt` | Qt6 Core + Gui + Qml + Quick + QuickControls2, size optimizations |
| `build_wasm.sh` | Build helper script |
| `README.md` | Build, deploy, and service developer guide |

### Static Import Caveat

QML loaded at runtime uses the interpreter (no JIT in WASM). For it to use Qt Quick Controls, those imports must exist in the compiled shell. The shell's `main.qml` pre-imports all modules service devs might need:

```qml
// main.qml — preload all commonly used QML modules
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import MicroserviceBase 1.0
// This ensures the static linker keeps these modules in the WASM binary
```

### Size Estimate

| Component | Uncompressed | Gzip |
|-----------|-------------|------|
| Qt Core + Gui + Qml + Quick + Controls | ~15-18 MB | ~6-9 MB |
| Per-service .qml file | ~2-50 KB | ~1-20 KB |
| 10 services | ~18 MB + ~200 KB | ~9 MB total |

## Part 3: JS Integration

### QtShellManager.js (new file)

```
web/js/QtShellManager.js

QtShellManager {
  _shellLoaded: false
  _shellModule: null
  _shellContainer: null

  loadQml(qmlUrl, containerEl, serviceName)
    → First call: load qtshell.wasm, create QML engine
    → Subsequent: reparent canvas, load new .qml URL

  clear()
    → Tell shell to unload current QML

  isLoaded() → bool
}
```

### app.js Integration

Modify `_loadServiceGUIMultiTier` to add QML detection:

```
Tier 1a: gui_schema.json with "renderer": "qt" → QtShellManager (QML Shell)
Tier 1b: gui_schema.json without renderer → SchemaRenderer.js (Bootstrap)
Tier 1c: *.qml file in service folder → QtShellManager (QML Shell)
Tier 2: .wasm file → QtWasmLoader (per-service WASM)
Tier 3: .html file → Custom HTML
Tier 4: API Explorer fallback
```

The detection for `.qml` files uses the existing `/api/list-dir/` endpoint to check if the service folder contains `.qml` files.

## Part 4: Service Template

`examples/cpp_qml_service_template/` — shows the full 3-part pattern.

```
examples/cpp_qml_service_template/
├── CMakeLists.txt                  # Builds the backend service (links ServiceBase lib)
├── service_config.json             # Service metadata (name, version, routing_key, broker)
├── src/
│   ├── main.cpp                    # Create transport, instantiate service, serve()
│   └── MyQMLService.h/cpp             # : ServiceBase, implements svc_api_* methods
├── qml/
│   └── ServiceUI.qml               # QML UI designed in Qt Creator (drag-and-drop)
├── GUIs/
│   └── ServiceUI.qml               # Copy of qml/ for deployment to web/services/
└── README.md                       # Developer guide: design UI, implement API, deploy
```

### Service Developer Workflow

1. **Design UI**: Open Qt Creator → File → New → Qt Quick Application → design `ServiceUI.qml` visually (drag-and-drop controls, set properties)
2. **Implement API**: Write `MyQMLService.cpp` — inherit `ServiceBase`, implement `svc_api_*` methods
3. **Wire UI to API**: In QML, call `ServiceBridge.callService("MyQMLService", "svc_api_method", [args])` from button `onClicked` handlers
4. **Preview locally**: Run QML in Qt Creator to verify layout and interactions
5. **Deploy backend**: Build `MyQMLService.exe`, start it (connects to RabbitMQ, registers)
6. **Deploy UI**: Copy `ServiceUI.qml` to `web/services/MyQMLService1.0.0/`
7. **Done**: MicroserviceManager detects the .qml file, loads it in the shared QML Shell

## Files to Create

### C++ ServiceBase Library (`MicroserviceBase/domain/service_base_cpp/`)

| # | File | Purpose |
|---|------|---------|
| 1 | `CMakeLists.txt` | Static library build (rabbitmq-c, nlohmann-json via vcpkg) |
| 2 | `include/ServiceBase.h` | Abstract base class |
| 3 | `include/RabbitMQConnection.h` | RAII AMQP wrapper |
| 4 | `include/ServiceConfig.h` | Configuration struct |
| 5 | `include/ServiceMessages.h` | Request/Response/MethodInfo structs |
| 6 | `src/ServiceBase.cpp` | Lifecycle, dispatch, registration |
| 7 | `src/RabbitMQConnection.cpp` | Connection management |

### QML Shell (`MicroserviceBase/MicroserviceManagerGUI/qt_qml_shell/`)

| # | File | Purpose |
|---|------|---------|
| 8 | `CMakeLists.txt` | Qt6 + Qml + Quick + QuickControls2, WASM build |
| 9 | `src/main.cpp` | QML engine, singleton registration, EMSCRIPTEN exports |
| 10 | `src/ServiceBridge.h/cpp` | QML singleton for service calls |
| 11 | `src/ShellController.h/cpp` | Dynamic QML loading/unloading |
| 12 | `src/main.qml` | Preloads all QML modules for static linker |
| 13 | `build_wasm.sh` | Build helper |
| 14 | `README.md` | Build and deployment guide |

### Service Template (`examples/cpp_qml_service_template/`)

| # | File | Purpose |
|---|------|---------|
| 15 | `CMakeLists.txt` | Links against ServiceBase library |
| 16 | `service_config.json` | Service metadata |
| 17 | `src/main.cpp` | Entry point |
| 18 | `src/MyQMLService.h/cpp` | Example service with svc_api_* methods |
| 19 | `qml/ServiceUI.qml` | Example QML UI |
| 20 | `README.md` | Developer workflow guide |

### JS Integration

| # | File | Purpose |
|---|------|---------|
| 21 | `web/js/QtShellManager.js` | Shared QML Shell lifecycle manager |

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `web/js/app.js` | Add .qml detection in `_loadServiceGUIMultiTier` |
| 2 | `web/index.html` | Add `<script src="js/QtShellManager.js">` |

## Implementation Phases

### Phase 1: C++ ServiceBase library
Extract and clean up from `cpp_mfc_service_template`, remove MFC dependencies, make it a reusable static library.

### Phase 2: QML Shell WASM binary
Build the shared shell with QML engine, ServiceBridge singleton, ShellController, exported C functions for JS↔C++ bridge.

### Phase 3: QtShellManager.js + app.js integration
JS-side manager for loading shell, reparenting canvas, passing QML URLs. Modify multi-tier detection to find .qml files.

### Phase 4: Service template
Example service showing the 3-part pattern. Include a QML UI designed for the visual editor workflow.

### Phase 5: Build, deploy, test
Build shell, deploy to `web/qt-shell/`, create example service, verify end-to-end.

## Verification

1. **QML Shell builds** → `qtshell.wasm` (~15MB) + `qtshell.js`
2. **Deploy shell** to `web/qt-shell/`
3. **Create example service**: backend registers with RabbitMQ, QML UI in service folder
4. **Open MicroserviceManager** → click service → QML UI renders (native Qt Quick controls)
5. **Interact**: fill form, click button → ServiceBridge → RabbitMQ → backend → response → QML UI updates
6. **Switch services**: canvas reparents, new .qml loads, no WASM reload
7. **Verify caching**: Network tab shows qtshell.wasm loaded only once
8. **Qt Creator workflow**: open ServiceUI.qml in Qt Creator → visual designer works → preview runs
9. **Bootstrap services unaffected**: schema-driven and HTML services still work
