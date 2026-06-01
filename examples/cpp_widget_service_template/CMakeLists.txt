cmake_minimum_required(VERSION 3.21)

# ===========================================================================
# MyWidgetService — Backend-only C++ service with Qt Designer .ui file
#
#   Desktop (MyWidgetService):  C++ service, links ServiceBase + RabbitMQ
#   WASM:                       No WASM target — the .ui file is a static
#                                asset loaded by the Widget Shell at runtime.
#
# The project loads under any Qt Creator kit (desktop or WASM) so that
# source files are visible in the project tree and code model works.
# The backend is only built on desktop (MSVC/GCC/Clang).
# ===========================================================================

# --- Qt WASM cross-compilation auto-detection (MUST be before project()) ---
# Qt Creator's WebAssembly kit may not pass CMAKE_TOOLCHAIN_FILE correctly.
# When CMAKE_PREFIX_PATH points to a Qt WASM installation, auto-set the
# toolchain to Qt's own qt.toolchain.cmake which wraps Emscripten.
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
if(NOT EMSCRIPTEN)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json")
        file(READ "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json" _presets_json)
        string(REGEX MATCH "\"toolchainFile\"[^\"]*\"([^\"]+)\"" _match "${_presets_json}")
        if(CMAKE_MATCH_1)
            string(REPLACE "\\\\" "/" _tc_path "${CMAKE_MATCH_1}")
            get_filename_component(_vcpkg_root "${_tc_path}" DIRECTORY)
            get_filename_component(_vcpkg_root "${_vcpkg_root}" DIRECTORY)
            get_filename_component(_vcpkg_root "${_vcpkg_root}" DIRECTORY)
            list(APPEND CMAKE_PREFIX_PATH
                "${_vcpkg_root}/installed/x64-windows"
                "${_vcpkg_root}/installed/x64-windows/share")
        endif()
    endif()
endif()

project(MyWidgetService VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ===========================================================================
# WASM kit — minimal stub target + IDE code model for backend sources
#
# The .ui file is a static asset loaded by the Widget Shell at runtime.
# A tiny WASM stub compiles so Qt Creator's clangd has compile commands.
# Backend sources are added as HEADER_FILE_ONLY for browsing/navigation.
# ===========================================================================
if(EMSCRIPTEN)

    message(STATUS "Emscripten detected — backend will not be built.")
    message(STATUS "The .ui file is a static asset loaded by the Widget Shell at runtime.")
    message(STATUS "To build the backend, select a desktop kit (MSVC, GCC, Clang).")

    set(CMAKE_AUTOMOC ON)

    # Emscripten cross-compilation: add Qt to CMAKE_FIND_ROOT_PATH.
    if(CMAKE_PREFIX_PATH)
        list(APPEND CMAKE_FIND_ROOT_PATH "${CMAKE_PREFIX_PATH}")
    endif()

    find_package(Qt6 REQUIRED COMPONENTS Core)

    # Minimal stub that actually compiles — gives clangd compile commands.
    qt_add_executable(mywidgetservice_stub
        wasm_stub.cpp
    )

    target_link_libraries(mywidgetservice_stub PRIVATE Qt6::Core)

    # Backend sources: not compiled under Emscripten, but visible in IDE
    # with full code model support (syntax highlighting, go-to-definition).
    set_source_files_properties(
        src/main.cpp src/MyWidgetService.h src/MyWidgetService.cpp
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
    target_sources(mywidgetservice_stub PRIVATE
        src/main.cpp src/MyWidgetService.h src/MyWidgetService.cpp
        service_config.json
        ui/ServiceUI.ui
    )
    set_source_files_properties(
        service_config.json ui/ServiceUI.ui
        PROPERTIES HEADER_FILE_ONLY TRUE
    )

    target_include_directories(mywidgetservice_stub PRIVATE src)

    # NOTE: preview/ sources are NOT listed here — they require Qt Widgets
    # which is unavailable in WASM Qt. Switch to the desktop kit to see
    # and edit preview/ files in the project tree.

    # IDE code model: ServiceBase headers
    set(_SERVICE_BASE_INC "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp/include")
    if(EXISTS "${_SERVICE_BASE_INC}")
        target_include_directories(mywidgetservice_stub PRIVATE "${_SERVICE_BASE_INC}")
    endif()

    # IDE code model: vcpkg headers (amqp.h, nlohmann/json.hpp)
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
                target_include_directories(mywidgetservice_stub PRIVATE "${_vcpkg_inc}")
            endif()
        endif()
    endif()

# ===========================================================================
# Desktop targets: Backend + Widget UI Preview
# ===========================================================================
else()

    set(CMAKE_AUTOMOC ON)

    # --- Qt Widgets (for the preview app) ---
    find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets UiTools)

    # --- Build CppServiceBase from source (same config, same CRT) ---
    option(BUILD_BACKEND "Build the C++ backend service executable" ON)

    if(BUILD_BACKEND)
        find_package(CppServiceBase CONFIG QUIET)
        if(NOT CppServiceBase_FOUND)
            set(_SERVICE_BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp")
            if(EXISTS "${_SERVICE_BASE_DIR}/CMakeLists.txt")
                add_subdirectory(
                    "${_SERVICE_BASE_DIR}"
                    "${CMAKE_CURRENT_BINARY_DIR}/cpp_service_base"
                )
            else()
                message(WARNING "CppServiceBase not found. Backend build disabled.")
                set(BUILD_BACKEND OFF)
            endif()
        endif()
    endif()

    # -----------------------------------------------------------------------
    # Widget UI Preview — always built (loads .ui in a native window).
    #
    # Run target: MyWidgetServicePreview
    # Design:     Open ui/ServiceUI.ui in Qt Designer
    # -----------------------------------------------------------------------
    qt_add_executable(MyWidgetServicePreview
        preview/main.cpp
        preview/LiveServiceBridge.h
        preview/LiveServiceBridge.cpp
        # Show .ui and config in project tree
        ui/ServiceUI.ui
    )

    set_target_properties(MyWidgetServicePreview PROPERTIES
        WIN32_EXECUTABLE TRUE
        MACOSX_BUNDLE TRUE
    )

    set_source_files_properties(
        ui/ServiceUI.ui
        PROPERTIES HEADER_FILE_ONLY TRUE
    )

    target_link_libraries(MyWidgetServicePreview PRIVATE
        Qt6::Core
        Qt6::Gui
        Qt6::Widgets
        Qt6::UiTools
    )

    target_include_directories(MyWidgetServicePreview PRIVATE preview)

    # Link against CppServiceBase for --live mode (direct RabbitMQ RPC).
    if(BUILD_BACKEND)
        target_link_libraries(MyWidgetServicePreview PRIVATE CppServiceBase)
        target_compile_definitions(MyWidgetServicePreview PRIVATE HAS_LIVE_BRIDGE)
    else()
        # Without CppServiceBase, LiveServiceBridge won't compile.
        set_source_files_properties(
            preview/LiveServiceBridge.cpp
            PROPERTIES HEADER_FILE_ONLY TRUE
        )
    endif()

    target_compile_definitions(MyWidgetServicePreview PRIVATE
        UI_DIR="${CMAKE_CURRENT_SOURCE_DIR}/ui"
    )

    # -----------------------------------------------------------------------
    # Backend target: MyWidgetService (C++ service, console app)
    # -----------------------------------------------------------------------
    if(BUILD_BACKEND)
        add_executable(MyWidgetService
            src/main.cpp
            src/MyWidgetService.h
            src/MyWidgetService.cpp
        )
        target_include_directories(MyWidgetService PRIVATE src)
        target_link_libraries(MyWidgetService PRIVATE CppServiceBase)
    else()
        message(STATUS "Backend build skipped. Use MyWidgetServicePreview to design the UI.")
    endif()

    # Non-source files visible in project tree.
    add_custom_target(MyWidgetService_ConfigFiles SOURCES
        service_config.json
        README.md
    )

endif()
