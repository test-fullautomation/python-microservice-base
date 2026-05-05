cmake_minimum_required(VERSION 3.21)

# ===========================================================================
# ServiceCleware WASM — 2-target build (Backend + WASM GUI)
#
#   Backend (ServiceCleware):       C++ service, links ServiceBase + RabbitMQ
#   WASM    (servicecleware_wasm):  Browser GUI compiled to WebAssembly
# ===========================================================================

# --- Qt WASM cross-compilation auto-detection ---
if(NOT DEFINED CMAKE_TOOLCHAIN_FILE AND CMAKE_PREFIX_PATH)
    set(_qt_toolchain "${CMAKE_PREFIX_PATH}/lib/cmake/Qt6/qt.toolchain.cmake")
    if(EXISTS "${_qt_toolchain}")
        set(CMAKE_TOOLCHAIN_FILE "${_qt_toolchain}"
            CACHE PATH "Qt WASM toolchain file (wraps Emscripten)")
    endif()
    unset(_qt_toolchain)
endif()

if(NOT DEFINED QT_HOST_PATH AND DEFINED ENV{QT_HOST_PATH})
    set(QT_HOST_PATH "$ENV{QT_HOST_PATH}" CACHE PATH "Path to host Qt installation")
endif()

# --- vcpkg auto-detection for desktop builds ---
if(NOT EMSCRIPTEN)
    if(EXISTS "${CMAKE_SOURCE_DIR}/CMakePresets.json")
        file(READ "${CMAKE_SOURCE_DIR}/CMakePresets.json" _presets_json)
        string(REGEX MATCH "\"toolchainFile\"[[:space:]]*:[[:space:]]*\"([^\"]+)\""
               _tc_match "${_presets_json}")
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

project(ServiceClewareWasm VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ===========================================================================
# WASM target (Emscripten only)
# ===========================================================================
if(EMSCRIPTEN)

    set(CMAKE_AUTOMOC ON)
    set(CMAKE_AUTOUIC ON)

    if(CMAKE_PREFIX_PATH)
        list(APPEND CMAKE_FIND_ROOT_PATH "${CMAKE_PREFIX_PATH}")
    endif()

    find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

    qt_add_executable(servicecleware_wasm
        wasm/main.cpp
        src/MainWidget.h
        src/MainWidget.cpp
        src/ServiceBridge.h
        src/ServiceBridge.cpp
        src/ServiceUI.ui
    )

    target_include_directories(servicecleware_wasm PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    )

    target_link_libraries(servicecleware_wasm PRIVATE
        Qt6::Core Qt6::Gui Qt6::Widgets
    )

    # Single-threaded WASM
    set_target_properties(servicecleware_wasm PROPERTIES
        QT_WASM_PTHREAD_POOL_SIZE 0
    )

    # Size optimization
    target_compile_options(servicecleware_wasm PRIVATE -Oz -flto)
    target_link_options(servicecleware_wasm PRIVATE -Oz -flto)

    # Exclude unused plugins
    set_target_properties(servicecleware_wasm PROPERTIES QT_PLUGINS "")
    qt_import_plugins(servicecleware_wasm
        INCLUDE_BY_TYPE platforms Qt6::QWasmIntegrationPlugin
        EXCLUDE_BY_TYPE imageformats iconengines
    )

# ===========================================================================
# Desktop target: Backend
# ===========================================================================
else()

    set(_SERVICE_BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp")
    add_subdirectory(
        "${_SERVICE_BASE_DIR}"
        "${CMAKE_CURRENT_BINARY_DIR}/cpp_service_base"
    )

    add_executable(ServiceCleware
        src/main.cpp
        src/ServiceCleware.h
        src/ServiceCleware.cpp
        src/ClewareAccess.h
        src/ClewareAccess.cpp
    )

    target_include_directories(ServiceCleware PRIVATE src)
    target_link_libraries(ServiceCleware PRIVATE CppServiceBase)

endif()

# ===========================================================================
# IDE visibility: show all files regardless of active kit
# ===========================================================================
set(_SERVICE_BASE_INC "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp/include")

if(EMSCRIPTEN)
    set_source_files_properties(
        src/main.cpp src/ServiceCleware.h src/ServiceCleware.cpp
        src/ClewareAccess.h src/ClewareAccess.cpp
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
    target_sources(servicecleware_wasm PRIVATE
        src/main.cpp src/ServiceCleware.h src/ServiceCleware.cpp
        src/ClewareAccess.h src/ClewareAccess.cpp
        service_config.json
    )
    if(EXISTS "${_SERVICE_BASE_INC}")
        target_include_directories(servicecleware_wasm PRIVATE "${_SERVICE_BASE_INC}")
    endif()
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json")
        file(READ "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json" _presets_json)
        string(JSON _tc_path ERROR_VARIABLE _json_err
               GET "${_presets_json}" "configurePresets" 0 "toolchainFile")
        if(NOT _json_err AND _tc_path)
            cmake_path(GET _tc_path PARENT_PATH _vr)
            cmake_path(GET _vr PARENT_PATH _vr)
            cmake_path(GET _vr PARENT_PATH _vr)
            set(_vcpkg_inc "${_vr}/installed/x64-windows/include")
            if(EXISTS "${_vcpkg_inc}")
                target_include_directories(servicecleware_wasm PRIVATE "${_vcpkg_inc}")
            endif()
        endif()
    endif()
else()
    set_source_files_properties(
        wasm/main.cpp src/MainWidget.h src/MainWidget.cpp
        src/ServiceBridge.h src/ServiceBridge.cpp src/ServiceUI.ui
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
    target_sources(ServiceCleware PRIVATE
        wasm/main.cpp
        src/MainWidget.h src/MainWidget.cpp
        src/ServiceBridge.h src/ServiceBridge.cpp
        src/ServiceUI.ui
        service_config.json
    )

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
        add_dependencies(ServiceCleware uic_ide)
        target_include_directories(ServiceCleware PRIVATE
            "${CMAKE_CURRENT_BINARY_DIR}"
        )
    endif()
    if(TARGET Qt6::Widgets)
        target_include_directories(ServiceCleware SYSTEM PRIVATE
            $<TARGET_PROPERTY:Qt6::Core,INTERFACE_INCLUDE_DIRECTORIES>
            $<TARGET_PROPERTY:Qt6::Gui,INTERFACE_INCLUDE_DIRECTORIES>
            $<TARGET_PROPERTY:Qt6::Widgets,INTERFACE_INCLUDE_DIRECTORIES>
        )
    endif()
endif()
