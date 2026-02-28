cmake_minimum_required(VERSION 3.16)
project(QtQmlShell VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)

qt_add_executable(qtshell
    src/main.cpp
    src/ServiceBridge.cpp
    src/ShellController.cpp
)

qt_add_qml_module(qtshell
    URI MicroserviceBase
    VERSION 1.0
    QML_FILES
        src/main.qml
    SOURCES
        src/ServiceBridge.h src/ServiceBridge.cpp
        src/ShellController.h src/ShellController.cpp
)

target_include_directories(qtshell PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(qtshell PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
)

# --- WASM-specific size optimizations ---
if(EMSCRIPTEN)
    target_link_options(qtshell PRIVATE
        # Export C functions for JS interop
        "SHELL:-s EXPORTED_FUNCTIONS=['_main','_qtshell_loadQml','_qtshell_clearQml','_qtshell_setServiceName']"
        "SHELL:-s EXPORTED_RUNTIME_METHODS=['ccall','cwrap','UTF8ToString','stringToUTF8','lengthBytesUTF8']"
        # Allow memory growth for dynamic QML loading
        "SHELL:-s ALLOW_MEMORY_GROWTH=1"
        # Enable Fetch API for loading QML files over HTTP
        "SHELL:-s FETCH=1"
        # Size optimizations
        "SHELL:-s MINIMAL_RUNTIME=0"
        # Enable embind for emscripten::val (used in URL resolution)
        "--bind"
    )
endif()
