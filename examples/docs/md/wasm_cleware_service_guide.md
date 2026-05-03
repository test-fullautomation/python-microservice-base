# Step-by-Step Guide: Building a WASM Cleware Service from Scratch

This guide walks through implementing a Cleware USB switch box service with a Qt
WebAssembly UI and a C++ backend, following the patterns from
`examples/qt_wasm_service_template` and `examples/cpp_qml_cleware_service`.

> 📄 *Also available as HTML:* [`../html/wasm_cleware_service_guide.html`](../html/wasm_cleware_service_guide.html)
>
> Companion docs: [← Docs index](index.md) ·
> [MinGW (MSYS2) setup](mingw_setup.md) ·
> [Qt6::Grpc setup](qt_grpc_setup.md) ·
> [Service creation](service_creation.md)

---

## Prerequisites — Tools to Install

### 1. Qt 6 (with WebAssembly + MSVC kits)
Install via [Qt Online Installer](https://www.qt.io/download-qt-installer):
- **Qt 6.7.3 or later (recommended)** — the Online Installer now ships
  WebAssembly support and a matching Emscripten SDK as ordinary
  components. No manual `emsdk` clone needed.
- **Qt 6.7.2 or earlier** — WebAssembly isn't a first-class component;
  you have to install Emscripten yourself (see [Step 2 — fallback for
  Qt < 6.7.3](#2-emscripten-sdk-only-for-qt--673)).

Components to tick in Maintenance Tool:
- `MSVC 2019 64-bit` (or `MinGW 13.1.0 64-bit`) — needed for host tools (moc, uic, rcc) and desktop backend
- `WebAssembly (single-threaded)` — for browser GUI
- `Qt Quick Controls 2`, `Qt Widgets`
- **Qt Creator** (latest)
- Qt → Tools → **CMake**, **Ninja**, and (for Qt 6.7.3+) **Emscripten** under the WebAssembly group

Default install path: `C:\Qt\<version>\`.

### 2. Emscripten SDK *(only for Qt < 6.7.3)*

> **Skip this step on Qt 6.7.3+** — the Online Installer ships a
> matching Emscripten SDK and Qt Creator auto-discovers it.  The
> instructions below apply only when Qt's Maintenance Tool doesn't
> offer Emscripten as a tickable component.

Install the SDK matching your Qt version (e.g. Qt 6.7.1 → Emscripten 3.1.50):
```bash
cd D:\Project\robot\github
git clone https://github.com/emscripten-core/emsdk.git
cd emsdk
emsdk install 3.1.50    # MUST match Qt's required Emscripten version
emsdk activate 3.1.50
```

The required Emscripten version per Qt release is documented at
<https://doc.qt.io/qt-6/wasm.html#installing-emscripten>.

**Configure Qt Creator to use the manual Emscripten install:**
1. Open Qt Creator → **Edit → Preferences → Devices → WebAssembly** (or
   **Tools → Options → Devices → WebAssembly** on older versions).
2. Set **Emscripten SDK path** to `D:\Project\robot\github\emsdk`.
3. Qt Creator validates the version and shows a green check if it matches
   the Qt WebAssembly kit's required Emscripten version.
4. Go to **Edit → Preferences → Kits**. Confirm a **Qt 6.x.x WebAssembly
   (single-threaded)** kit appears with no warnings.
5. If the kit is missing, click **Add**, set:
   - **Compiler**: `Emscripten Compiler` (auto-detected from step 2)
   - **Qt version**: `Qt 6.x.x wasm_singlethread`
   - **CMake Tool**: the one bundled with Qt (`C:\Qt\Tools\CMake_64\bin\cmake.exe`)
   - **CMake generator**: `Ninja`

### 3. Visual Studio 2019 Build Tools
Install [Visual Studio 2019 Community](https://visualstudio.microsoft.com/vs/older-downloads/) with:
- "Desktop development with C++" workload
- MSVC v142 toolchain, Windows 10 SDK

### 4. vcpkg (for backend dependencies)
```bash
cd D:\Project\Out
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat
.\vcpkg install librabbitmq:x64-windows nlohmann-json:x64-windows
```

### 5. RabbitMQ Server
Download from [rabbitmq.com](https://www.rabbitmq.com/install-windows.html) — installs Erlang + RabbitMQ. Verify it runs on `localhost:5672`.

### 6. Python 3.x + MicroserviceBase
The MicroserviceBase repo bundles a Python distribution at `RobotFramework\python3\`. After cloning:
```bash
cd D:\Project\robot\github\python-microservice-base
pip install .
pip install pika fastapi uvicorn
```

### 7. Cleware USB Hardware
- Cleware switch box or USB multiplexer device
- USB cable + driver (auto-installs on Windows)

---

## Source Code

### Clone the repositories
```bash
cd D:\Project\robot\github

# Main MicroserviceBase framework (includes the WASM template + CppServiceBase)
git clone -b ugc1hc/feat/restructure_microservice_base \
    https://github.com/test-fullautomation/python-microservice-base.git

# Original Python Cleware service (source for Cleware USB DLL + reference)
git clone <develop_ms_cleware-url> develop_ms_cleware
```

---

## Implementation Steps

### Step 1 — Create the project structure

#### Option A — Command line
```bash
cd D:\Project\robot\github\python-microservice-base\examples
mkdir cpp_wasm_cleware_service
cd cpp_wasm_cleware_service
mkdir src wasm GUIs libs\Windows
```

#### Option B — Qt Creator UI
1. **File → New Project → Non-Qt Project → Plain C++ Application** (we'll
   replace the auto-generated `CMakeLists.txt` later).
2. **Name**: `cpp_wasm_cleware_service`
3. **Location**: `D:\Project\robot\github\python-microservice-base\examples`
4. **Build system**: `CMake`
5. **Kit selection**: tick both **Desktop Qt 6.7.1 MSVC2019 64bit** and
   **Qt 6.7.1 WebAssembly (single-threaded)** — Qt Creator will create a build
   directory per kit.
6. After the project opens, right-click the project root in the **Projects
   pane** → **Add New → General → Empty File** to create each subfolder by
   typing the path (e.g. `src/ClewareAccess.h`). Qt Creator creates missing
   folders automatically.
7. For binary files (`libs/Windows/USBaccessX64.dll`, `.lib`, `.h`), copy them
   in Explorer first, then right-click the project → **Add Existing Files** to
   make them visible in the project tree.

### Step 2 — Copy the Cleware USB library from the Python project
```bash
copy ..\..\..\develop_ms_cleware\MicroserviceClewareSwitch\libs\Windows\USBaccessX64.dll  libs\Windows\
copy ..\..\..\develop_ms_cleware\MicroserviceClewareSwitch\libs\Windows\USBaccessX64.lib  libs\Windows\
copy ..\..\..\develop_ms_cleware\MicroserviceClewareSwitch\libs\Windows\USBaccess.h       libs\Windows\
```

### Step 3 — Create `service_config.json`
Service metadata + RabbitMQ broker config. **Critical**: `routing_key` must equal
the service `name` (otherwise the LiveServiceBridge can't reach the backend).

### Adding source files in Qt Creator

For **every C++ file** in Steps 4 and 5 below, the workflow in Qt Creator is the
same:

1. In the **Projects pane** (left sidebar), right-click the target folder
   (e.g. `src/`) → **Add New…**
2. Choose the template:
   - C++ header: **C/C++ → C++ Header File**
   - C++ source: **C/C++ → C++ Source File**
   - Qt Designer form: **Qt → Qt Designer Form** → **Widget**
3. Enter the file name (e.g. `ClewareAccess.h`) — leave the path as the
   selected folder.
4. Tick **Add to project** so the new file is added to `CMakeLists.txt`
   automatically (Qt Creator will offer to update it).
5. Paste the code into the editor. Save with **Ctrl+S**.

> **Tip:** If you prefer to edit `CMakeLists.txt` manually, untick the "Add to
> project" option and add the file under the correct `qt_add_executable()` /
> `add_executable()` source list yourself.

For the **`.ui` file** (`src/ServiceUI.ui`), Qt Creator opens it in the visual
**Design** mode where you can drag widgets from the palette. To paste the XML
directly: **Right-click the form file → Open With → Plain Text Editor**, then
overwrite with the XML content.

### Step 4 — Implement the C++ backend

**`src/ClewareAccess.h/cpp`** — Runtime wrapper for `USBaccessX64.dll`:
- Use `LoadLibrary` + `GetProcAddress` (Windows) / `dlopen` + `dlsym` (Linux)
- Resolve `FCWInitObject`, `FCWOpenCleware`, `FCWSetSwitch`, `FCWGetSwitch`, `FCWGetSerialNumber`
- Expose `getAllDevicesState()` returning `nlohmann::json`

**`src/ServiceCleware.h/cpp`** — Microservice extending `ServiceBase`:
- `svc_api_get_all_devices_state` — returns `m_cleware.getAllDevicesState()`
- `svc_api_set_switch(device_no, switch_id, state)` — calls `m_cleware.setSwitch()` then publishes update
- `notifyUpdates()` — opens a separate `RabbitMQConnection`, declares fanout exchange `updates_sw_state`, publishes new state

**`src/main.cpp`** — Entry point that loads `service_config.json`, creates
`ServiceCleware`, registers signal handlers, calls `registerService()` + `serve()`.

### Step 5 — Implement the WASM GUI

**`src/ServiceUI.ui`** — Qt Designer form with:
- Header label
- Device combo + Initialize button + Type combo (Switch Box / Multiplexer)
- `QStackedWidget` with two pages:
  - Page 0: 8 toggle `QPushButton`s (sw0–sw7) + All On / All Off / Refresh
  - Page 1: 2 IN buttons + 4 OUT buttons + route label

**`src/MainWidget.h/cpp`** — Logic:
- Constructor: `setupUi`, create `ServiceBridge`, wire button signals
- `onSwitchToggled(i)` — read state, call `setSwitch(0x10+i, "on"/"off")`
- `onMuxInClicked(in)` / `onMuxOutClicked(out)` — compute `switchIndex = in*4 + out`
- `onResponse(method, result)` — parse JSON, update combo + button states/colors
- `updateSwitchUI()` / `updateMuxUI()` — apply stylesheets (green=on, blue=in, orange=out)

**`src/ServiceBridge.h/cpp`** — Copy verbatim from `qt_wasm_service_template/src/`.
Implements EM_JS-based polling bridge to `window.callMicroservice`.

**`wasm/main.cpp`** — Trivial: `QApplication app; MainWidget w; w.show(); app.exec();`

### Step 6 — Create CMakeLists.txt
Dual-target build:
- **`if(EMSCRIPTEN)`** branch: builds `servicecleware_wasm` with Qt Widgets +
  ServiceBridge + MainWidget (`-Oz -flto`, `QT_WASM_PTHREAD_POOL_SIZE 0`)
- **`else()`** branch: builds `ServiceCleware.exe` linking `CppServiceBase`
  (added via `add_subdirectory`)
- IDE-visibility section so Qt Creator shows backend files when in WASM kit and vice versa

### Step 7 — Create `CMakePresets.json`
Two presets (`default` Debug, `release` Release) with `toolchainFile` pointing to
`D:/Project/Out/vcpkg/scripts/buildsystems/vcpkg.cmake` for the desktop backend.

### Step 8 — Create build scripts

**`build_wasm.bat`** — Sets `QT_WASM_DIR`, `QT_HOST_DIR`, `EMSDK_DIR`. Runs
`cmake -G Ninja` with Qt's WASM toolchain + Emscripten chainload. Copies
`servicecleware_wasm.{wasm,js}` to `GUIs/`.

**`build_deploy.bat`** — Calls `vcvars64.bat`, runs `cmake --preset release`,
builds `ServiceCleware.exe`, copies executable + `service_config.json` + `libs/`
+ vcpkg DLLs (`rabbitmq.4.dll`, `libssl-3-x64.dll`, `libcrypto-3-x64.dll`) into
`deploy/`.

### Step 9 — Create `serve_dev.py` + `serve.bat`
HTTP server that:
- Serves files from `build/wasm/` (with `application/wasm` MIME type)
- Injects `window.callMicroservice` JavaScript bridge into HTML responses
- POST `/api/request` → uses `RabbitMQTransportAdapter` to RPC-call
  `services_request` exchange with routing_key = service name
- Sets COOP/COEP headers for SharedArrayBuffer

### Step 10 — Build inside Qt Creator (optional)

You can build entirely from Qt Creator instead of using the `.bat` scripts:

1. **Bottom-left kit selector** → switch between
   **Desktop Qt 6.7.1 MSVC2019 64bit** (backend) and
   **Qt 6.7.1 WebAssembly (single-threaded)** (WASM GUI).
2. **Build → Run CMake** to reconfigure when switching kits.
3. **Build → Build Project "ServiceClewareWasm"** (Ctrl+B).
4. The active target appears next to the kit selector — pick `ServiceCleware`
   (backend) or `servicecleware_wasm` (WASM).
5. **Run** (Ctrl+R) — for the backend this launches `ServiceCleware.exe`; for
   the WASM target Qt Creator starts its own dev server and opens the browser.
6. To use the project's own dev server with the RabbitMQ bridge, run
   `serve.bat` in a terminal instead of Qt Creator's built-in WASM server.

### Step 11 — Build and run from the command line

```bash
# 1. Start RabbitMQ (should already be running as a Windows service)
net start RabbitMQ

# 2. Build the WASM GUI
cd D:\Project\robot\github\python-microservice-base\examples\cpp_wasm_cleware_service
build_wasm.bat
# Output: GUIs\servicecleware_wasm.{js,wasm}

# 3. Build the backend
build_deploy.bat
# Output: deploy\ServiceCleware.exe

# 4. Plug in the Cleware USB device

# 5. Start the backend
cd deploy
ServiceCleware.exe
# Should print: "[ClewareAccess] Initialized. Devices found: N"
#               "[INFO] ServiceCleware v1.0.0 started."

# 6. In another terminal, start the dev server
cd ..
serve.bat
# Opens http://localhost:8090/servicecleware_wasm.html

# 7. In the browser:
#    - Click "Initialize" → device serial appears in dropdown
#    - Click LED buttons → switches toggle on the physical device
#    - Switch to "USB Multiplexer" type → IN/OUT matrix view
```

---

## Troubleshooting Checklist

| Issue                                  | Fix                                                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------- |
| `cmake: command not found`             | Add `C:\Qt\Tools\CMake_64\bin` to PATH                                             |
| `emcc not found`                       | Run `emsdk activate 3.1.50` first                                                  |
| `librabbitmq not found`                | Run `vcpkg install librabbitmq:x64-windows`                                        |
| Backend builds but service not reached | Check `routing_key == name` in `service_config.json`                               |
| `404 /api/nomad/agent/start`           | Reinstall MicroserviceBase: `pip install .`                                        |
| WASM compile but blank page            | Check browser console; verify `serve.bat` is running and bridge script is injected |
| Cleware DLL not loaded                 | Make sure `libs/Windows/USBaccessX64.dll` is next to `ServiceCleware.exe`          |
| No devices found                       | Check Cleware device is plugged in and not in use by another process               |

---

## Reference Templates

- **WASM template** (UI pattern): `examples/qt_wasm_service_template/`
- **C++ QML version** (same backend): `examples/cpp_qml_cleware_service/`
- **Original Python service** (reference for hardware API + Cleware DLL):
  `develop_ms_cleware/MicroserviceClewareSwitch/`
