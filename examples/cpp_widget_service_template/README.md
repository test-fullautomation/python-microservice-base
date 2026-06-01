# C++ Widget Service Template

A template for building C++ microservices with a Qt Widget UI (`.ui` file). The backend is a pure C++ console app that communicates via RabbitMQ. The UI is a `.ui` file designed in Qt Designer — no code in the UI, no WASM build needed for the service.

## Architecture: 3-Part Pattern

```
┌─────────────────────────┐
│  1. Infrastructure      │  ServiceBase (CppServiceBase library)
│     RabbitMQ transport   │  Registration, dispatch, heartbeat
│     Message protocol     │  Handled automatically
├─────────────────────────┤
│  2. Business API        │  MyWidgetService (this template)
│     svc_api_hello()     │  Your service logic goes here
│     svc_api_echo()      │  Each method = one API endpoint
│     svc_api_compute()   │  Return JSON, throw on error
├─────────────────────────┤
│  3. UI                  │  ServiceUI.ui (Qt Designer form)
│     No code needed      │  Buttons auto-wired via dynamic properties
│     Deploy .ui file     │  Widget Shell renders it in browser
└─────────────────────────┘
```

## How It Differs from `cpp_qml_service_template`

| | QML Template | Widget Template (this) |
|---|---|---|
| **UI file** | `ServiceUI.qml` | `ServiceUI.ui` |
| **UI design tool** | Qt Creator QML editor | Qt Designer (visual drag-drop) |
| **Logic in UI** | Yes (JavaScript in QML) | No (auto-wired via properties) |
| **UI build** | No build (interpreted) | No build (XML parsed at runtime) |
| **Shell runtime** | QML Shell (`qtshell.wasm`) | Widget Shell (`widgetshell.wasm`) |
| **Qt dependency** | Backend: none, Preview: Qt Quick | Backend: none, UI: none |

## Project Structure

```
cpp_widget_service_template/
├── CMakeLists.txt          # Backend build (pure C++, no Qt)
├── CMakePresets.json        # Default (Debug), Release presets
├── service_config.json      # Service metadata + broker config
├── src/
│   ├── main.cpp             # Entry point: load config, register, serve
│   ├── MyWidgetService.h    # Service class declaration
│   └── MyWidgetService.cpp  # svc_api_hello, svc_api_echo, svc_api_compute
├── ui/
│   └── ServiceUI.ui         # Qt Designer form (source of truth)
├── GUIs/
│   └── ServiceUI.ui         # Deployed copy (served to web clients)
└── README.md
```

## Developer Workflow

### 1. Design the UI

Open `ui/ServiceUI.ui` in Qt Designer (standalone or via Qt Creator).

**Auto-wiring convention** — set these dynamic properties on `QPushButton` widgets:

| Property | Type | Example | Purpose |
|----------|------|---------|---------|
| `serviceMethod` | `QString` | `svc_api_hello` | Method to call on click |
| `serviceArgs` | `QString` | `nameInput,ageInput` | Comma-separated objectNames of input widgets |
| `serviceResult` | `QString` | `helloResult` | objectName of the widget to display the response (optional) |

If `serviceResult` is not set, the response falls back to a QLabel named `resultLabel`.

Supported input widget types: `QLineEdit`, `QSpinBox`, `QDoubleSpinBox`, `QComboBox`, `QCheckBox`.

### 2. Implement the Backend

Edit `src/MyWidgetService.cpp`:
- Add `svc_api_*` methods for your business logic
- Register them in the constructor with `registerMethod()`
- Each method receives `json args` and returns `json`

### 3. Build the Backend

```bash
# Using vcpkg preset
cmake --preset default
cmake --build build/default

# Or Release
cmake --preset release
cmake --build build/release
```

**Dependencies**: `CppServiceBase`, `rabbitmq-c`, `nlohmann-json` (install via vcpkg).

### 4. Deploy

Copy to your deployment folder:
```
deploy/
├── MyWidgetService.exe     # Backend executable
├── service_config.json      # Service config
├── GUIs/
│   └── ServiceUI.ui         # UI file
└── (DLLs)                   # rabbitmq, OpenSSL, vc_redist
```

Copy `GUIs/ServiceUI.ui` to the MicroserviceManager web folder:
```
web/services/MyWidgetService1.0.0/ServiceUI.ui
```

### 5. Run

1. Start RabbitMQ
2. Start the backend: `MyWidgetService.exe service_config.json`
3. Open MicroserviceManager GUI
4. Connect to broker
5. Click on MyWidgetService in the sidebar
6. The Widget Shell loads and renders the `.ui` form
7. Click buttons to call service methods

## API Methods

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `svc_api_hello` | `["name"]` | `"Hello, name!"` | Greet someone |
| `svc_api_echo` | `["message"]` | `"message"` | Echo back input |
| `svc_api_compute` | `["1,2,3"]` | `6.0` | Sum comma-separated numbers |

## Creating Your Own Service

1. Copy this template folder
2. Rename `MyWidgetService` → `YourServiceName` in all files
3. Update `service_config.json` with your service metadata
4. Design your UI in Qt Designer (`ui/ServiceUI.ui`)
5. Implement your `svc_api_*` methods
6. Build, deploy, and run
