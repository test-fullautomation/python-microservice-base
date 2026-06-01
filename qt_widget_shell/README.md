# Qt Widget Shell

A shared Qt WASM binary that hosts service-specific `.ui` files (Qt Designer forms) at runtime. Like the [QML Shell](../qt_qml_shell/), the Widget Shell is loaded once and cached — switching services just loads a new `.ui` file into the same `QWidget` container.

## Key Difference from QML Shell

| | QML Shell | Widget Shell |
|---|---|---|
| **UI files** | `.qml` (code + layout) | `.ui` (pure XML layout) |
| **Design tool** | Qt Creator QML editor | Qt Designer (visual drag-drop) |
| **Logic** | Written in QML/JS | Auto-wired via dynamic properties |
| **Qt modules** | Quick, QuickControls2 | Widgets, UiTools |

`.ui` files contain **no code**. The Widget Shell auto-wires button clicks to service calls using dynamic properties set in Qt Designer.

## Auto-Wiring Convention

Set these dynamic properties on widgets in Qt Designer:

| Widget | Property | Example | Purpose |
|--------|----------|---------|---------|
| `QPushButton` | `serviceMethod` | `svc_api_hello` | Method to call on click |
| `QPushButton` | `serviceArgs` | `nameInput,ageInput` | Comma-separated objectNames of input widgets |
| `QLabel` | objectName = `resultLabel` | — | Displays service response |

Supported input widget types: `QLineEdit`, `QSpinBox`, `QDoubleSpinBox`, `QComboBox`, `QCheckBox`.

## Architecture

```
Browser                          Widget Shell (WASM)
┌──────────────────┐            ┌────────────────────────┐
│ WidgetShellMgr   │───.ui───→ │ WidgetController       │
│ (JavaScript)     │   XML     │   loadUiSource()       │
│                  │            │   wireButtons()        │
│                  │            │   ↓                    │
│ callMicroservice │←──call───│ ServiceBridge          │
│ (JS bridge)      │───resp──→│   handleResponse()     │
│                  │            │   → resultLabel        │
└──────────────────┘            └────────────────────────┘
```

## Building

### Prerequisites

- **Qt 6.5+** with WebAssembly target (must include `Widgets` and `UiTools` modules)
- **Emscripten SDK** matching your Qt version (e.g., 3.1.50 for Qt 6.7.1)
- **CMake 3.16+** and **Ninja** (both bundled with Qt)

### Windows

```batch
cd MicroserviceBase\MicroserviceManagerGUI\qt_widget_shell
build_wasm.bat              :: Release build (default)
build_wasm.bat debug        :: Debug build
build_wasm.bat clean        :: Delete build folder
```

Edit the paths at the top of `build_wasm.bat` if your Qt/Emscripten is installed elsewhere.

### Linux / macOS

```bash
cd MicroserviceBase/MicroserviceManagerGUI/qt_widget_shell
./build_wasm.sh ~/Qt/6.7.1/wasm_singlethread
```

### Output

The build script deploys to:
```
MicroserviceBase/MicroserviceManagerGUI/web/widget-shell/
├── widgetshell.wasm     # WASM binary
└── widgetshell.js       # Emscripten JS loader
```

## How It Works

1. **Detection**: `WidgetShellManager.detect(folderPath)` checks for `.ui` files in the service folder
2. **Shell load**: On first use, `widgetshell.wasm` is loaded (one-time ~download)
3. **UI load**: `.ui` XML is read via XHR and passed to `WidgetController::loadUiSource()`
4. **QUiLoader**: Parses the XML and creates the `QWidget` tree
5. **Auto-wiring**: `wireButtons()` scans for `QPushButton` children with `serviceMethod` property, connects `clicked()` → `ServiceBridge::callService()`
6. **Response**: Bridge signals route to `resultLabel`

## Key Components

| File | Purpose |
|------|---------|
| `src/main.cpp` | Entry point: QApplication, root widget, WASM exports |
| `src/ServiceBridge.h/.cpp` | Calls `window.callMicroservice()` via EM_ASM |
| `src/WidgetController.h/.cpp` | QUiLoader + auto-wiring logic |
| `CMakeLists.txt` | Build config (Qt Widgets + UiTools) |
| `example/ServiceUI.ui` | Example .ui form with auto-wired buttons |

## Developer Workflow

1. **Design** the UI in Qt Designer — drag buttons, labels, inputs
2. **Set dynamic properties** on buttons: `serviceMethod`, `serviceArgs`
3. **Name the result label** `resultLabel`
4. **Deploy** the `.ui` file to `web/services/MyService1.0.0/`
5. The Widget Shell auto-wires everything — no code needed in the UI file

## Example

See `example/ServiceUI.ui` for a complete form with three auto-wired buttons:
- **Say Hello**: calls `svc_api_hello` with `nameInput` value
- **Echo**: calls `svc_api_echo` with `echoInput` value
- **Compute Sum**: calls `svc_api_compute` with `numbersInput` value
