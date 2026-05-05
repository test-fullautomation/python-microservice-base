cmake_minimum_required(VERSION 3.21)

# ===========================================================================
# MyQtWasmService — 2-target build (Backend + WASM)
#
#   Backend (MyQtWasmService):  C++ service, links ServiceBase + RabbitMQ
#   WASM    (myqtwasmservice):  Browser GUI compiled to WebAssembly
#
# The WASM target is only built when cross-compiling with Emscripten.
# The Backend target is only built on desktop (MSVC/GCC/Clang).
# No desktop preview needed — use serve.bat to test the WASM GUI in a browser.
# ===========================================================================

# --- Qt WASM cross-compilation auto-detection ---
# Qt Creator's WebAssembly kit may not pass CMAKE_TOOLCHAIN_FILE correctly.
# When CMAKE_PREFIX_PATH points to a Qt WASM installation, auto-set the
# toolchain to Qt's own qt.toolchain.cmake.
if(NOT DEFINED CMAKE_TOOLCHAIN_FILE AND CMAKE_PREFIX_PATH)
    set(_qt_toolchain "${CMAKE_PREFIX_PATH}/lib/cmake/Qt6/qt.toolchain.cmake")
    if(EXISTS "${_qt_toolchain}")
        set(CMAKE_TOOLCHAIN_FILE "${_qt_toolchain}"
            CACHE PATH "Qt WASM toolchain file (wraps Emscripten)")
    endif()
    unset(_qt_toolchain)
endif()

# QT_HOST_PATH for cross-compilation (host tools: moc, rcc, uic).
if(NOT DEFINED QT_HOST_PATH AND DEFINED ENV{QT_HOST_PATH})
    set(QT_HOST_PATH "$ENV{QT_HOST_PATH}" CACHE PATH "Path to host Qt installation")
endif()

# --- vcpkg auto-detection for desktop builds (backend) ---
# Parse CMakePresets.json to find the vcpkg toolchain file, then add
# the vcpkg installed dir to CMAKE_PREFIX_PATH so add_subdirectory'd
# CppServiceBase can find rabbitmq-c and nlohmann-json.
if(NOT EMSCRIPTEN)
    if(EXISTS "${CMAKE_SOURCE_DIR}/CMakePresets.json")
        file(READ "${CMAKE_SOURCE_DIR}/CMakePresets.json" _presets_json)
        string(REGEX MATCH "\"toolchainFile\"[[:space:]]*:[[:space:]]*\"([^\"]+)\""
               _tc_match "${_presets_json}")
        if(CMAKE_MATCH_1)
            string(REPLACE "\\\\" "/" _tc_path "${CMAKE_MATCH_1}")
            get_filename_component(_vcpkg_root "${_tc_path}" DIRECTORY)  # scripts/buildsystems
            get_filename_component(_vcpkg_root "${_vcpkg_root}" DIRECTORY)  # scripts
            get_filename_component(_vcpkg_root "${_vcpkg_root}" DIRECTORY)  # vcpkg root
            list(APPEND CMAKE_PREFIX_PATH
                "${_vcpkg_root}/installed/x64-windows"
                "${_vcpkg_root}/installed/x64-windows/share")
        endif()
    endif()
endif()

project(MyQtWasmService VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ===========================================================================
# WASM target (Emscripten only) — requires Qt 6
# ===========================================================================
if(EMSCRIPTEN)

    set(CMAKE_AUTOMOC ON)
    set(CMAKE_AUTOUIC ON)

    # Emscripten cross-compilation: add Qt to CMAKE_FIND_ROOT_PATH.
    if(CMAKE_PREFIX_PATH)
        list(APPEND CMAKE_FIND_ROOT_PATH "${CMAKE_PREFIX_PATH}")
    endif()

    find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

    qt_add_executable(myqtwasmservice
        wasm/main.cpp
        src/MainWidget.h
        src/MainWidget.cpp
        src/ServiceBridge.h
        src/ServiceBridge.cpp
        src/ServiceUI.ui
    )

    target_include_directories(myqtwasmservice PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    )

    target_link_libraries(myqtwasmservice PRIVATE
        Qt6::Core Qt6::Gui Qt6::Widgets
    )

    # Container-based rendering (no standalone HTML).
    set_target_properties(myqtwasmservice PROPERTIES
        QT_WASM_PTHREAD_POOL_SIZE 0
    )

    # Size optimization.
    target_compile_options(myqtwasmservice PRIVATE -Oz -flto)
    target_link_options(myqtwasmservice PRIVATE -Oz -flto)

    # Disable unused image format plugins to save ~1-2 MB.
    set_target_properties(myqtwasmservice PROPERTIES QT_PLUGINS "")
    qt_import_plugins(myqtwasmservice
        INCLUDE_BY_TYPE platforms Qt6::QWasmIntegrationPlugin
        EXCLUDE_BY_TYPE imageformats iconengines
    )

# ===========================================================================
# Desktop target: Backend (pure C++, no Qt dependency)
# ===========================================================================
else()

    # --- Build CppServiceBase from source (same config, same CRT) ---
    set(_SERVICE_BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp")
    add_subdirectory(
        "${_SERVICE_BASE_DIR}"
        "${CMAKE_CURRENT_BINARY_DIR}/cpp_service_base"
    )

    # -----------------------------------------------------------------------
    # Backend target: MyQtWasmService (C++ service, console app)
    # -----------------------------------------------------------------------
    add_executable(MyQtWasmService
        src/main.cpp
        src/MyQtWasmService.h
        src/MyQtWasmService.cpp
    )

    target_include_directories(MyQtWasmService PRIVATE src)

    target_link_libraries(MyQtWasmService PRIVATE CppServiceBase)

endif()

# ===========================================================================
# Make ALL source files visible in Qt Creator regardless of active kit.
# These are not compiled — they just appear in the project tree for browsing.
# ===========================================================================
set(_SERVICE_BASE_INC "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp/include")

if(EMSCRIPTEN)
    # Backend files aren't compiled under Emscripten, but show them in IDE.
    # Add include paths so Qt Creator's code model can resolve ServiceBase.h etc.
    set_source_files_properties(
        src/main.cpp src/MyQtWasmService.h src/MyQtWasmService.cpp
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
    target_sources(myqtwasmservice PRIVATE
        src/main.cpp src/MyQtWasmService.h src/MyQtWasmService.cpp
        service_config.json
    )
    # Include paths for IDE code model (not compiled, just for Qt Creator).
    # ServiceBase headers
    if(EXISTS "${_SERVICE_BASE_INC}")
        target_include_directories(myqtwasmservice PRIVATE "${_SERVICE_BASE_INC}")
    endif()
    # vcpkg headers (amqp.h, nlohmann/json.hpp) — resolve from CMakePresets.json
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json")
        file(READ "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json" _presets_json)
        string(JSON _tc_path ERROR_VARIABLE _json_err
               GET "${_presets_json}" "configurePresets" 0 "toolchainFile")
        if(NOT _json_err AND _tc_path)
            cmake_path(GET _tc_path PARENT_PATH _vr)   # .../scripts/buildsystems
            cmake_path(GET _vr PARENT_PATH _vr)         # .../scripts
            cmake_path(GET _vr PARENT_PATH _vr)         # vcpkg root
            set(_vcpkg_inc "${_vr}/installed/x64-windows/include")
            if(EXISTS "${_vcpkg_inc}")
                target_include_directories(myqtwasmservice PRIVATE "${_vcpkg_inc}")
            endif()
        endif()
    endif()
else()
    # WASM/GUI files aren't compiled on desktop, but show them in IDE
    set_source_files_properties(
        wasm/main.cpp src/MainWidget.h src/MainWidget.cpp
        src/ServiceBridge.h src/ServiceBridge.cpp src/ServiceUI.ui
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
    target_sources(MyQtWasmService PRIVATE
        wasm/main.cpp
        src/MainWidget.h src/MainWidget.cpp
        src/ServiceBridge.h src/ServiceBridge.cpp
        src/ServiceUI.ui
        service_config.json
    )

    # --- IDE code-model support (desktop kit) ---
    # When Qt is installed on the host, run uic to generate ui_ServiceUI.h
    # and add Qt include paths so Qt Creator can resolve symbols in WASM
    # source files.  The backend does NOT link Qt — this is purely for IDE
    # browsing and code navigation.
    find_package(Qt6 QUIET COMPONENTS Widgets)
    if(TARGET Qt6::uic)
        add_custom_command(
            OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/ui_ServiceUI.h"
            COMMAND Qt6::uic
                "${CMAKE_CURRENT_SOURCE_DIR}/src/ServiceUI.ui"
                -o "${CMAKE_CURRENT_BINARY_DIR}/ui_ServiceUI.h"
            DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/ServiceUI.ui"
            COMMENT "uic: generating ui_ServiceUI.h (IDE code model)"
        )
        add_custom_target(uic_ide ALL
            DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/ui_ServiceUI.h"
        )
        add_dependencies(MyQtWasmService uic_ide)
        target_include_directories(MyQtWasmService PRIVATE
            "${CMAKE_CURRENT_BINARY_DIR}"
        )
    endif()
    if(TARGET Qt6::Widgets)
        target_include_directories(MyQtWasmService SYSTEM PRIVATE
            $<TARGET_PROPERTY:Qt6::Core,INTERFACE_INCLUDE_DIRECTORIES>
            $<TARGET_PROPERTY:Qt6::Gui,INTERFACE_INCLUDE_DIRECTORIES>
            $<TARGET_PROPERTY:Qt6::Widgets,INTERFACE_INCLUDE_DIRECTORIES>
        )
    endif()
endif()
