# QML Shell — Shared WASM Binary for Service UIs

A single Qt WASM application (~9 MB gzip) that hosts service-specific QML files at runtime. Service developers design UIs in Qt Creator's visual QML editor, and the shell loads them dynamically — no per-service WASM compilation needed.

## Architecture

```
Browser                              Server
┌──────────────────────────────┐     ┌──────────────────────────┐
│  qtshell.wasm (loaded once)  │     │  ServiceUI.qml (per svc) │
│  ├─ QML engine               │◄────│  ├─ Qt Quick Controls    │
│  ├─ ServiceBridge singleton  │     │  └─ ServiceBridge.call() │
│  └─ ShellController          │     └──────────────────────────┘
│       ↕ JS bridge            │
│  QtShellManager.js           │
│       ↕                      │
│  MicroserviceManager (app.js)│
│       ↕ RabbitMQ             │
│  Service Backend (C++)       │
└──────────────────────────────┘
```

## Building

### Prerequisites

- [Emscripten SDK](https://emscripten.org/docs/getting_started/downloads.html)
- Qt 6.x built for WebAssembly (single-threaded)

### Build (Windows)

```cmd
build_wasm.bat              REM Release build (default)
build_wasm.bat debug        REM Debug build
build_wasm.bat clean        REM Delete build folder
```

Edit the configurable paths at the top of `build_wasm.bat` to match your Qt/Emscripten installation.

The script automatically deploys `qtshell.js` and `qtshell.wasm` to `web/qt-shell/`.

### Build (Linux/macOS)

```bash
./build_wasm.sh ~/Qt/6.6.0/wasm_singlethread
```

The script automatically deploys `qtshell.js` and `qtshell.wasm` to `web/qt-shell/`.

## How It Works

1. User clicks a service with a `.qml` file in its GUI folder
2. `app.js` detects the QML file and calls `QtShellManager.loadQml()`
3. First call: loads `qtshell.wasm` (cached by browser for subsequent calls)
4. `QtShellManager` calls `qtshell_loadQml(url)` via Emscripten `ccall`
5. `ShellController` creates a `QQmlComponent` from the URL (async HTTP fetch)
6. QML engine parses and renders the service UI with native Qt Quick controls
7. Service QML calls `ServiceBridge.callService()` → JS bridge → RabbitMQ → backend

## Service Developer Workflow

1. **Design UI** in Qt Creator: File → New → Qt Quick Application → drag-and-drop controls
2. **Import MicroserviceBase**: `import MicroserviceBase 1.0` in your QML
3. **Call services**: `ServiceBridge.callService("MyService", "svc_api_hello", [name])`
4. **Handle results**: Connect to `ServiceBridge.responseReceived` / `errorOccurred`
5. **Deploy**: Copy `ServiceUI.qml` to `web/services/MyService1.0.0/`

## Key Components

| File | Purpose |
|------|---------|
| `src/main.cpp` | QML engine setup, singleton registration, EMSCRIPTEN exports |
| `src/ServiceBridge.h/cpp` | QML singleton — calls microservices via JS bridge |
| `src/ShellController.h/cpp` | Dynamic QML loading/unloading lifecycle manager |
| `src/main.qml` | Root window + module preloads for static linker |
| `CMakeLists.txt` | Qt6 WASM build with size optimizations |

## Static Import Caveat

QML loaded at runtime uses the QML interpreter (no JIT in WASM). For `import QtQuick.Controls` to work, those modules must be statically linked into the shell binary. The shell's `main.qml` imports all commonly needed modules to ensure the static linker keeps them.

If a service needs an additional Qt module (e.g., `QtCharts`), it must be added to:
1. `CMakeLists.txt` → `find_package` and `target_link_libraries`
2. `main.qml` → `import` statement

## Size Budget

| Component | Uncompressed | Gzip |
|-----------|-------------|------|
| Qt Core + Gui + Qml + Quick + Controls | ~15-18 MB | ~6-9 MB |
| Per-service .qml file | ~2-50 KB | ~1-20 KB |
| 10 services total | ~18 MB + ~200 KB | ~9 MB total |
