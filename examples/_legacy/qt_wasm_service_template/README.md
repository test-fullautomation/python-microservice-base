# Qt WASM Service GUI Template

This template demonstrates how to build a Qt-based GUI for a MicroserviceBase service
that compiles to WebAssembly and runs inside the MicroserviceManager panel.

## Prerequisites

- **Qt 6.5+** with the `wasm_singlethread` target installed
- **Emscripten** (version must match your Qt build — see table below)
- **CMake 3.21+**

> **Critical**: The Emscripten version must **exactly match** what your Qt WASM target
> was built with. A version mismatch causes linker errors (`undefined symbol: _emval_*`).
> Check compatible versions at https://doc.qt.io/qt-6/wasm.html.

| Qt Version | Required Emscripten |
|-----------|-------------------|
| Qt 6.7.1 | 3.1.50 |
| Qt 6.5.3 | 3.1.25 |

### Installing Qt for WebAssembly

```bash
# Using Qt Online Installer, select:
# - Qt > Qt 6.x > WebAssembly (single-threaded)
# Or via aqtinstall (if WASM target was not included in offline install):
pip install aqtinstall
aqt install-qt windows desktop 6.7.1 wasm_singlethread --outputdir "C:/Qt"
```

### Installing Emscripten

```bash
git clone https://github.com/emscripten-core/emsdk.git
cd emsdk
# Install the version matching your Qt (e.g., 3.1.50 for Qt 6.7.1)
./emsdk install 3.1.50
./emsdk activate 3.1.50
source ./emsdk_env.sh
```

## Project Structure

```
qt_wasm_service_template/
├── README.md                    # This file
├── CMakeLists.txt               # Qt6 + Emscripten build system
├── src/
│   ├── main.cpp                 # QApplication entry point
│   ├── MainWidget.h             # Main UI widget header
│   ├── MainWidget.cpp           # Main UI widget with form + service calls
│   ├── ServiceBridge.h          # C++ wrapper around JS bridge header
│   └── ServiceBridge.cpp        # C++ wrapper around JS bridge implementation
├── GUIs/
│   ├── MyQtWasmService.html     # Bootstrap card + canvas container
│   └── MyQtWasmService.js       # Qt WASM loader + lifecycle + JS bridge
└── build_wasm.sh                # Helper build script
```

## Building with Qt Creator (Recommended)

Qt Creator provides a full visual IDE experience — UI designer, one-click build,
and browser preview — making it the easiest way to develop Qt WASM service GUIs.

### 1. Set up the Emscripten Kit

> **Important**: The WebAssembly plugin is **disabled by default** in Qt Creator.
> You must enable it first before Emscripten options become available.

#### Step 1: Enable the WebAssembly plugin

1. **Help** > **About Plugins**
2. Under **Device Support**, find **WebAssembly** and **check** the checkbox
3. **Restart Qt Creator** — this is required for the plugin to load

#### Step 2: Set environment variables

The `CMakeLists.txt` auto-detects the Emscripten toolchain from environment variables.
Set these **permanently** (PowerShell as Administrator, or System Properties > Environment Variables):

```powershell
# PowerShell — set permanently for current user
[Environment]::SetEnvironmentVariable('EMSDK', 'D:\Project\robot\github\emsdk', 'User')
[Environment]::SetEnvironmentVariable('EM_CONFIG', 'D:\Project\robot\github\emsdk\.emscripten', 'User')
[Environment]::SetEnvironmentVariable('EMSDK_PYTHON', 'D:\Project\robot\github\emsdk\python\3.13.3_64bit\python.exe', 'User')
[Environment]::SetEnvironmentVariable('EMSDK_NODE', 'D:\Project\robot\github\emsdk\node\22.16.0_64bit\bin\node.exe', 'User')
[Environment]::SetEnvironmentVariable('QT_HOST_PATH', 'C:\Qt\6.7.1\msvc2019_64', 'User')
```

```bash
# Linux/macOS — add to ~/.bashrc or ~/.zshrc
export EMSDK=/path/to/emsdk
export EM_CONFIG=$EMSDK/.emscripten
export QT_HOST_PATH=/path/to/qt/6.7.1/gcc_64
# EMSDK_PYTHON and EMSDK_NODE are set automatically by emsdk_env.sh on Linux
```

> **Important**: All five environment variables are needed on Windows:
> - `EMSDK` — emsdk root, used by CMakeLists.txt and Qt's toolchain
> - `EM_CONFIG` — points to `.emscripten` config file
> - `EMSDK_PYTHON` — Python used by emcc.bat (without this, emcc fails to import modules)
> - `EMSDK_NODE` — Node.js used by Emscripten
> - `QT_HOST_PATH` — desktop Qt with host tools (moc, rcc, uic) for cross-compilation
>
> The `CMakeLists.txt` auto-detects the toolchain — no manual Kit CMake Configuration needed.

**Restart Qt Creator** after setting environment variables so it picks them up.

#### Step 3: Configure Emscripten SDK in Qt Creator

1. **Edit** > **Preferences** > **Devices** > **WebAssembly** tab
2. Set **Emscripten SDK path** to your emsdk root directory, e.g.:
   ```
   D:\Project\robot\github\emsdk
   ```
   Qt Creator auto-detects `emcc.bat` / `em++.bat` from `upstream\emscripten\`.
3. Go to **Kits** — a WebAssembly kit should now appear automatically.
4. Verify the kit shows a **green checkmark** (valid configuration).

> **Note**: You do **not** need to manually add `CMAKE_TOOLCHAIN_FILE` to the kit's
> CMake Configuration. The `CMakeLists.txt` auto-detects it from the `EMSDK` environment
> variable. Adding it manually to the kit can cause issues where Qt Creator passes
> it as a bare path argument instead of a `-D` flag, and CMake ignores it.

#### Alternative: Manual setup (if plugin is not available)

If your Qt Creator build does not include the WebAssembly plugin:

1. **Edit** > **Preferences** > **Kits** > **Compilers** tab
   - Click **Add** > **C** > **Custom**
     - Name: `Emscripten C`
     - Path: `D:\Project\robot\github\emsdk\upstream\emscripten\emcc.bat`
   - Click **Add** > **C++** > **Custom**
     - Name: `Emscripten C++`
     - Path: `D:\Project\robot\github\emsdk\upstream\emscripten\em++.bat`
2. **Qt Versions** tab > **Add**
   - Browse to: `<Qt install>\<version>\wasm_singlethread\bin\qmake.exe`
   - Example: `C:\Qt\6.5.3\wasm_singlethread\bin\qmake.exe`
3. **Kits** tab > **Add**
   - Name: `Qt WASM`
   - Compiler C: `Emscripten C` from step 1
   - Compiler C++: `Emscripten C++` from step 1
   - Qt version: the WASM version from step 2
   - CMake Tool: default
4. Click **Apply** — a green checkmark means the kit is valid.

> **Tip**: Ensure the Emscripten version matches what your Qt WASM build was
> compiled with (e.g., Qt 6.5.3 requires Emscripten 3.1.25). Check compatible
> versions at https://doc.qt.io/qt-6/wasm.html.

### 2. Open the Project

1. **File** > **Open File or Project** > select `CMakeLists.txt` from this template
2. In the **Configure Project** screen, check the **Emscripten** kit
3. Click **Configure Project**

### 3. Design the UI

You can design your service GUI visually using either approach:

- **Qt Designer (`.ui` files)**: Right-click `src/` > Add New > Qt > Qt Designer Form.
  Drag-and-drop widgets (buttons, inputs, labels), then load the `.ui` in your widget
  constructor with `QUiLoader` or the `setupUi()` pattern.
- **Programmatic layout**: Edit `src/MainWidget.cpp` directly with `QVBoxLayout`,
  `QPushButton`, `QLineEdit`, etc. (this is what the template uses by default).

Both approaches compile to WASM identically.

### 4. Build & Run

1. Select the **Emscripten kit** in the kit selector (bottom-left)
2. Click **Build** (Ctrl+B) — Qt Creator runs CMake + Emscripten automatically
3. Click **Run** (Ctrl+R) — Qt Creator launches a local HTTP server and opens your
   default browser with the WASM app running
4. Use the browser's DevTools (F12) for debugging (console, network, breakpoints)

Output files are in the build directory:
- `myqtwasmservice.js` (Emscripten loader/glue)
- `myqtwasmservice.wasm` (compiled binary)

### 5. Debug

- **Console output**: `qDebug()` statements appear in the browser's developer console
- **Breakpoints**: Qt Creator supports source-level debugging for WASM via Chrome DevTools
  integration (Edit > Preferences > Debugger > set Chrome path)
- **Qt Creator's Application Output** pane shows build warnings and Emscripten diagnostics

## Building from Command Line

For CI/CD pipelines or developers who prefer the terminal.

### Using the build script

```bash
# Edit build_wasm.sh to set your Qt and Emscripten paths, then:
chmod +x build_wasm.sh
./build_wasm.sh
```

### Manual build

```bash
# 1. Source Emscripten environment
source /path/to/emsdk/emsdk_env.sh

# 2. Configure with qt-cmake
/path/to/qt/wasm_singlethread/bin/qt-cmake \
    -B build -S . \
    -DQT_HOST_PATH=/path/to/qt/gcc_64 \
    -DCMAKE_TOOLCHAIN_FILE=/path/to/emsdk/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake

# 3. Build
cmake --build build

# 4. Output files will be in build/:
#    - myqtwasmservice.js    (Emscripten loader/glue)
#    - myqtwasmservice.wasm  (compiled binary)
```

## Deploying to MicroserviceManager

1. Copy the compiled files to the GUIs/ folder:
   ```bash
   cp build/myqtwasmservice.js build/myqtwasmservice.wasm GUIs/
   ```

2. Copy the GUIs/ folder contents to the MicroserviceManager web services directory:
   ```bash
   # The folder name must match: {ServiceName}{Version}/
   cp -r GUIs/* /path/to/MicroserviceManagerGUI/web/services/MyQtWasmService1.0.0/
   ```

3. The MicroserviceManager will automatically detect the `.wasm` file and load
   the Qt WASM app via `QtWasmLoader`.

## How It Works

### JS Bridge

The Qt WASM app communicates with microservices through a JavaScript bridge:

```
Qt C++ code → emscripten::val → window.callMicroservice() → MM.requestService() → RabbitMQ
```

From C++ (via ServiceBridge):
```cpp
m_bridge->callService("MyService", "svc_api_hello", QJsonArray{"World"});
```

The `ServiceBridge` class wraps the Emscripten interop, providing a Qt-friendly
API with signals for responses and errors.

### Rendering

The Qt app renders into its own `<canvas>` element inside the MicroserviceManager
panel. It manages its own event loop and rendering — no DOM integration needed.

### Lifecycle

- **Load**: `QtWasmLoader.load()` injects the Emscripten script, creates the Qt
  module instance, and provides the canvas container.
- **Unload**: When the user switches to another service, `QtWasmLoader.unload()`
  calls `instance.delete()` to clean up the Qt runtime.

## Customizing

1. Rename `MyQtWasmService` throughout to your service name
2. Edit `src/MainWidget.cpp` to add your custom UI widgets and service calls
3. Update `CMakeLists.txt` if you add new source files
4. Rebuild and redeploy

## Creating Your Own Service

1. **Copy** this folder and rename:
   ```
   cp -r qt_wasm_service_template/ my_wasm_service/
   ```

2. **Rename the service class** — in `src/`:
   - `MyQtWasmService.h` → `YourService.h`
   - `MyQtWasmService.cpp` → `YourService.cpp`
   - Replace `MyQtWasmService` with `YourService` in all source files

3. **Update `service_config.json`**:
   ```json
   {
     "name": "YourService",
     "version": "1.0.0",
     "routing_key": "YourService",
     "description": "What your service does.",
     ...
   }
   ```

4. **Update `CMakeLists.txt`**:
   - Change target names `MyQtWasmService`/`myqtwasmservice` → your name
   - Update source file names to match step 2

5. **Add business methods** in `YourService.cpp` (same as QML template):
   ```cpp
   registerMethod("svc_api_do_something",
       [this](const json& a) { return svc_api_do_something(a); },
       MethodInfo{{{"param", "required", "str", "", "Description"}}, "str"});
   ```

6. **Design the Qt Widgets UI** — edit `src/MainWidget.cpp`

7. **Build WASM GUI**: select Emscripten kit, build (produces `.js` + `.wasm`)

8. **Build backend**: select Desktop kit, build

9. **Deploy**: copy `.js`, `.wasm` to `GUIs/`, run backend with `service_config.json`
