cmake_minimum_required(VERSION 3.16)
project(QtWidgetShell VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets UiTools)

qt_add_executable(widgetshell
    src/main.cpp
    src/ServiceBridge.cpp
    src/WidgetController.cpp
)

target_include_directories(widgetshell PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(widgetshell PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::UiTools
)

# --- WASM-specific settings ---
if(EMSCRIPTEN)
    target_link_options(widgetshell PRIVATE
        # Export C functions for JS interop
        "SHELL:-s EXPORTED_FUNCTIONS=['_main','_widgetshell_malloc','_widgetshell_free','_widgetshell_loadUiSource','_widgetshell_clearUi','_widgetshell_setServiceName','_widgetshell_onResponse','_widgetshell_onError']"
        "SHELL:-s EXPORTED_RUNTIME_METHODS=['UTF8ToString','stringToUTF8','lengthBytesUTF8']"
        # Allow memory growth for dynamic UI loading
        "SHELL:-s ALLOW_MEMORY_GROWTH=1"
        # Enable embind for emscripten::val (used in ServiceBridge)
        "--bind"
    )
endif()
