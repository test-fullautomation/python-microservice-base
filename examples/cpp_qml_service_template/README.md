# C++ QML Service Template

Demonstrates the **3-part pattern** for building C++ microservices with Qt QML UIs:

1. **Infrastructure** — `ServiceBase` library handles RabbitMQ transport, registration, request dispatch
2. **Business API** — `MyQMLService` implements `svc_api_*` methods (C++ backend)
3. **UI** — `ServiceUI.qml` designed in Qt Creator (loaded by the shared QML Shell)

## Project Structure

```
cpp_qml_service_template/
├── CMakeLists.txt          # Builds the backend, links ServiceBase
├── service_config.json     # Service metadata + broker config
├── src/
│   ├── main.cpp            # Entry point: load config, register, serve
│   ├── MyQMLService.h         # Service class declaration
│   └── MyQMLService.cpp       # svc_api_* method implementations
├── qml/
│   └── ServiceUI.qml       # QML UI (design in Qt Creator)
└── GUIs/
    └── ServiceUI.qml       # Copy for deployment to web/services/
```

## Developer Workflow

### 1. Design the UI

Open `qml/ServiceUI.qml` in Qt Creator's visual QML editor:

- Drag-and-drop Qt Quick Controls (TextField, Button, Label, etc.)
- Set properties in the property editor
- Preview in Qt Creator to verify layout

### 2. Implement the API

Edit `src/MyQMLService.cpp` — add `svc_api_*` methods:

```cpp
json MyQMLService::svc_api_hello(const json& args) {
    std::string name = args[0].get<std::string>();
    return "Hello, " + name + "!";
}
```

Register each method in the constructor:

```cpp
registerMethod("svc_api_hello",
    [this](const json& args) { return svc_api_hello(args); },
    MethodInfo{{{"name", "required", "str", "", "Name to greet"}}, "str"});
```

### 3. Wire UI to API

In the QML file, call `ServiceBridge.callService()`:

```qml
Button {
    text: "Say Hello"
    onClicked: ServiceBridge.callService(
        "MyQMLService", "svc_api_hello", [nameInput.text])
}

Connections {
    target: ServiceBridge
    function onResponseReceived(method, data) {
        resultLabel.text = data
    }
}
```

### 4. Build and Run Backend

```bash
mkdir build && cd build
cmake .. -DCMAKE_PREFIX_PATH=/path/to/vcpkg/installed/x64-windows
cmake --build . --config Release

# Run the service (connects to RabbitMQ)
./MyQMLService ../service_config.json
```

### 5. Deploy UI

Copy the QML file to the service's GUI folder:

```bash
cp qml/ServiceUI.qml /path/to/web/services/MyQMLService1.0.0/ServiceUI.qml
```

### 6. Done

Open MicroserviceManager in the browser. Click "MyQMLService" in the sidebar. The QML UI loads in the shared QML Shell — native Qt Quick controls, no per-service WASM build needed.

## API Methods

| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| `svc_api_hello` | `[name]` | `"Hello, name!"` | Greeting |
| `svc_api_echo` | `[message]` | The message | Echo test |
| `svc_api_compute` | `[[1,2,3]]` | `6` | Sum of numbers |
| `svc_api_get_version` | none | `"1.0.0"` | Built-in |
| `svc_api_shutdown` | none | Stops service | Built-in |

## Dependencies

- **CppServiceBase** library (from `../../MicroserviceBase/domain/service_base_cpp/`)
- **rabbitmq-c** — C client for RabbitMQ (via vcpkg)
- **nlohmann/json** — JSON for Modern C++ (via vcpkg)

## Creating Your Own Service

1. **Copy** this folder and rename:
   ```
   cp -r cpp_qml_service_template/ my_service/
   ```

2. **Rename the service class** — in `src/`:
   - `MyQMLService.h` → `YourService.h`
   - `MyQMLService.cpp` → `YourService.cpp`
   - Replace `MyQMLService` with `YourService` in all files

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
   - Change target name `MyQMLService` → `YourService`
   - Update source file names to match step 2

5. **Add business methods** in `YourService.cpp`:
   ```cpp
   json YourService::svc_api_do_something(const json& args) {
       // Your logic here
       return result;
   }
   ```
   Register in the constructor:
   ```cpp
   registerMethod("svc_api_do_something",
       [this](const json& a) { return svc_api_do_something(a); },
       MethodInfo{{{"param", "required", "str", "", "Description"}}, "str"});
   ```

6. **Design the QML UI** — edit `qml/ServiceUI.qml` in Qt Creator

7. **Build and run**:
   ```bash
   cmake --preset default && cmake --build build/default
   ./build/default/YourService service_config.json
   ```
