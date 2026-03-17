cmake_minimum_required(VERSION 3.16)
project(ServiceCleware VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# ---------------------------------------------------------------------------
# Qt Quick
# ---------------------------------------------------------------------------
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)

set(QML_IMPORT_PATH "${CMAKE_CURRENT_SOURCE_DIR}/stubs" CACHE STRING "" FORCE)

# ---------------------------------------------------------------------------
# Auto-detect vcpkg root from CMakePresets.json
# ---------------------------------------------------------------------------
set(_VCPKG_ROOT "")
set(_VCPKG_LIB_HINT "")
set(_VCPKG_INC_HINT "")
if(NOT CMAKE_TOOLCHAIN_FILE AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json")
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json" _presets)
    string(REGEX MATCH "\"toolchainFile\"[^\"]*\"([^\"]+)\"" _match "${_presets}")
    if(CMAKE_MATCH_1)
        get_filename_component(_VCPKG_ROOT "${CMAKE_MATCH_1}" DIRECTORY)
        get_filename_component(_VCPKG_ROOT "${_VCPKG_ROOT}" DIRECTORY)
        get_filename_component(_VCPKG_ROOT "${_VCPKG_ROOT}" DIRECTORY)
        if(EXISTS "${_VCPKG_ROOT}/installed/x64-windows/include")
            set(_VCPKG_INC_HINT "${_VCPKG_ROOT}/installed/x64-windows/include")
            set(_VCPKG_LIB_HINT "${_VCPKG_ROOT}/installed/x64-windows/lib")
            list(APPEND CMAKE_PREFIX_PATH "${_VCPKG_ROOT}/installed/x64-windows")
            message(STATUS "Auto-detected vcpkg root: ${_VCPKG_ROOT}")
        endif()
    endif()
endif()

# ---------------------------------------------------------------------------
# Option: BUILD_BACKEND
# ---------------------------------------------------------------------------
option(BUILD_BACKEND "Build the C++ backend service executable" ON)

if(BUILD_BACKEND)
    find_package(CppServiceBase CONFIG QUIET)
    if(NOT CppServiceBase_FOUND)
        if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp/CMakeLists.txt")
            find_package(rabbitmq-c CONFIG QUIET)
            if(NOT rabbitmq-c_FOUND)
                find_library(RABBITMQ_LIBRARY NAMES rabbitmq rabbitmq.4
                    HINTS ${_VCPKG_LIB_HINT} QUIET)
            endif()
            find_package(nlohmann_json CONFIG QUIET)
            if(NOT nlohmann_json_FOUND)
                find_path(NLOHMANN_JSON_INCLUDE nlohmann/json.hpp
                    HINTS ${_VCPKG_INC_HINT} QUIET)
            endif()

            if((rabbitmq-c_FOUND OR RABBITMQ_LIBRARY) AND (nlohmann_json_FOUND OR NLOHMANN_JSON_INCLUDE))
                add_subdirectory(
                    "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp"
                    "${CMAKE_CURRENT_BINARY_DIR}/cpp_service_base"
                )
            else()
                message(WARNING
                    "CppServiceBase dependencies not found (rabbitmq-c, nlohmann-json).\n"
                    "  Backend build disabled. QML preview and Design mode still work.\n"
                    "  To build the backend:\n"
                    "    vcpkg install librabbitmq:x64-windows nlohmann-json:x64-windows\n"
                    "    cmake -DCMAKE_TOOLCHAIN_FILE=.../vcpkg.cmake ..")
                set(BUILD_BACKEND OFF)
            endif()
        else()
            message(WARNING "CppServiceBase not found. Backend build disabled.")
            set(BUILD_BACKEND OFF)
        endif()
    endif()
endif()

# ---------------------------------------------------------------------------
# QML Preview app — always built
# ---------------------------------------------------------------------------
qt_add_executable(ServiceClewarePreview
    preview/main.cpp
    preview/LiveServiceBridge.h
    preview/LiveServiceBridge.cpp
    qml/ServiceUI.qml
    stubs/MicroserviceBase/qmldir
    stubs/MicroserviceBase/ServiceBridge.qml
)

set_target_properties(ServiceClewarePreview PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)

set_source_files_properties(
    qml/ServiceUI.qml
    stubs/MicroserviceBase/qmldir
    stubs/MicroserviceBase/ServiceBridge.qml
    PROPERTIES HEADER_FILE_ONLY TRUE
)

target_link_libraries(ServiceClewarePreview PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
)

target_include_directories(ServiceClewarePreview PRIVATE preview)

if(BUILD_BACKEND)
    target_link_libraries(ServiceClewarePreview PRIVATE CppServiceBase)
    target_compile_definitions(ServiceClewarePreview PRIVATE HAS_LIVE_BRIDGE)
else()
    set_source_files_properties(
        preview/LiveServiceBridge.cpp
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
endif()

target_compile_definitions(ServiceClewarePreview PRIVATE
    STUBS_IMPORT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/stubs"
    QML_DIR="${CMAKE_CURRENT_SOURCE_DIR}/qml"
)

# ---------------------------------------------------------------------------
# Backend executable
# ---------------------------------------------------------------------------
if(BUILD_BACKEND)
    add_executable(ServiceCleware
        src/main.cpp
        src/ServiceCleware.h
        src/ServiceCleware.cpp
        src/ClewareAccess.h
        src/ClewareAccess.cpp
    )
    target_include_directories(ServiceCleware PRIVATE src)
    target_link_libraries(ServiceCleware PRIVATE CppServiceBase)
else()
    message(STATUS "Backend build skipped. Use ServiceClewarePreview to design the QML UI.")

    add_library(ServiceCleware_IDE OBJECT EXCLUDE_FROM_ALL
        src/main.cpp
        src/ServiceCleware.h
        src/ServiceCleware.cpp
        src/ClewareAccess.h
        src/ClewareAccess.cpp
    )
    target_include_directories(ServiceCleware_IDE PRIVATE
        src
        "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp/include"
    )

    find_package(nlohmann_json CONFIG QUIET)
    if(nlohmann_json_FOUND)
        target_link_libraries(ServiceCleware_IDE PRIVATE nlohmann_json::nlohmann_json)
    else()
        find_path(_NJ_INC nlohmann/json.hpp HINTS ${_VCPKG_INC_HINT} QUIET)
        if(_NJ_INC)
            target_include_directories(ServiceCleware_IDE PRIVATE ${_NJ_INC})
        endif()
    endif()

    find_package(rabbitmq-c CONFIG QUIET)
    if(rabbitmq-c_FOUND)
        target_link_libraries(ServiceCleware_IDE PRIVATE rabbitmq::rabbitmq)
    else()
        find_path(_RMQ_INC amqp.h HINTS ${_VCPKG_INC_HINT} QUIET)
        if(_RMQ_INC)
            target_include_directories(ServiceCleware_IDE PRIVATE ${_RMQ_INC})
        endif()
    endif()

    add_custom_target(ServiceCleware_ConfigFiles SOURCES
        service_config.json
    )
endif()
