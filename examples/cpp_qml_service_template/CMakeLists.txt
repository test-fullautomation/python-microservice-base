cmake_minimum_required(VERSION 3.16)
project(MyQMLService VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# ---------------------------------------------------------------------------
# Qt Quick — enables Qt Creator's Design mode (drag-and-drop QML editor)
# and builds a lightweight preview app for testing the UI locally.
# ---------------------------------------------------------------------------
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)

# QML import path: stubs/ provides a design-time mock ServiceBridge singleton
# so Qt Creator resolves "import MicroserviceBase 1.0" in the designer.
set(QML_IMPORT_PATH "${CMAKE_CURRENT_SOURCE_DIR}/stubs" CACHE STRING "" FORCE)

# ---------------------------------------------------------------------------
# Auto-detect vcpkg root from CMakePresets.json (used for HINTS below).
# When Qt Creator opens the project without the vcpkg toolchain preset,
# find_package / find_library / find_path can still locate vcpkg packages.
# ---------------------------------------------------------------------------
set(_VCPKG_ROOT "")
set(_VCPKG_LIB_HINT "")
set(_VCPKG_INC_HINT "")
if(NOT CMAKE_TOOLCHAIN_FILE AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json")
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json" _presets)
    string(REGEX MATCH "\"toolchainFile\"[^\"]*\"([^\"]+)\"" _match "${_presets}")
    if(CMAKE_MATCH_1)
        # toolchainFile = ".../vcpkg/scripts/buildsystems/vcpkg.cmake"
        # Navigate up 3 levels to get vcpkg root.
        get_filename_component(_VCPKG_ROOT "${CMAKE_MATCH_1}" DIRECTORY)
        get_filename_component(_VCPKG_ROOT "${_VCPKG_ROOT}" DIRECTORY)
        get_filename_component(_VCPKG_ROOT "${_VCPKG_ROOT}" DIRECTORY)
        if(EXISTS "${_VCPKG_ROOT}/installed/x64-windows/include")
            set(_VCPKG_INC_HINT "${_VCPKG_ROOT}/installed/x64-windows/include")
            set(_VCPKG_LIB_HINT "${_VCPKG_ROOT}/installed/x64-windows/lib")
            # Also add to CMAKE_PREFIX_PATH so find_package(CONFIG) works.
            list(APPEND CMAKE_PREFIX_PATH "${_VCPKG_ROOT}/installed/x64-windows")
            message(STATUS "Auto-detected vcpkg root: ${_VCPKG_ROOT}")
        endif()
    endif()
endif()

# ---------------------------------------------------------------------------
# Option: BUILD_BACKEND (ON by default, OFF if deps are missing)
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
# QML Preview app — always built.
# Opens ServiceUI.qml in a native Qt Quick window with the stub
# ServiceBridge. Enables the Design tab in Qt Creator.
#
# Run target: MyQMLServicePreview
# Design:     Open qml/ServiceUI.qml → click "Design" tab
# ---------------------------------------------------------------------------
qt_add_executable(MyQMLServicePreview
    preview/main.cpp
    preview/LiveServiceBridge.h
    preview/LiveServiceBridge.cpp
    # List QML and stub files so they appear in the project tree
    # and Qt Creator knows this is a QML-capable target.
    qml/ServiceUI.qml
    stubs/MicroserviceBase/qmldir
    stubs/MicroserviceBase/ServiceBridge.qml
)

# Launch as a GUI window (no console) on Windows, bundle on macOS.
set_target_properties(MyQMLServicePreview PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)

# Mark non-compiled files so the build system skips them.
set_source_files_properties(
    qml/ServiceUI.qml
    stubs/MicroserviceBase/qmldir
    stubs/MicroserviceBase/ServiceBridge.qml
    PROPERTIES HEADER_FILE_ONLY TRUE
)

target_link_libraries(MyQMLServicePreview PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
)

target_include_directories(MyQMLServicePreview PRIVATE preview)

# Link against CppServiceBase for --live mode (direct RabbitMQ RPC).
# When backend deps are available, the preview can connect to the service
# directly without needing MicroserviceManager.
if(BUILD_BACKEND)
    target_link_libraries(MyQMLServicePreview PRIVATE CppServiceBase)
    target_compile_definitions(MyQMLServicePreview PRIVATE HAS_LIVE_BRIDGE)
else()
    # Without CppServiceBase, LiveServiceBridge won't compile.
    # Exclude it from the build — stub mode only.
    set_source_files_properties(
        preview/LiveServiceBridge.cpp
        PROPERTIES HEADER_FILE_ONLY TRUE
    )
endif()

target_compile_definitions(MyQMLServicePreview PRIVATE
    STUBS_IMPORT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/stubs"
    QML_DIR="${CMAKE_CURRENT_SOURCE_DIR}/qml"
)

# ---------------------------------------------------------------------------
# Backend executable (only if deps are available)
# ---------------------------------------------------------------------------
if(BUILD_BACKEND)
    add_executable(MyQMLService
        src/main.cpp
        src/MyQMLService.h
        src/MyQMLService.cpp
    )
    target_include_directories(MyQMLService PRIVATE src)
    target_link_libraries(MyQMLService PRIVATE CppServiceBase)
else()
    message(STATUS "Backend build skipped. Use MyQMLServicePreview to design the QML UI.")

    # IDE-only OBJECT library: shows backend sources in the project tree
    # with full code model support (include paths, syntax highlighting).
    # EXCLUDE_FROM_ALL ensures it is never actually compiled.
    add_library(MyQMLService_IDE OBJECT EXCLUDE_FROM_ALL
        src/main.cpp
        src/MyQMLService.h
        src/MyQMLService.cpp
    )
    target_include_directories(MyQMLService_IDE PRIVATE
        src
        "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/domain/service_base_cpp/include"
    )

    # Provide nlohmann/json.hpp to the code model.
    find_package(nlohmann_json CONFIG QUIET)
    if(nlohmann_json_FOUND)
        target_link_libraries(MyQMLService_IDE PRIVATE nlohmann_json::nlohmann_json)
    else()
        find_path(_NJ_INC nlohmann/json.hpp HINTS ${_VCPKG_INC_HINT} QUIET)
        if(_NJ_INC)
            target_include_directories(MyQMLService_IDE PRIVATE ${_NJ_INC})
        endif()
    endif()

    # Provide amqp.h to the code model.
    find_package(rabbitmq-c CONFIG QUIET)
    if(rabbitmq-c_FOUND)
        target_link_libraries(MyQMLService_IDE PRIVATE rabbitmq::rabbitmq)
    else()
        find_path(_RMQ_INC amqp.h HINTS ${_VCPKG_INC_HINT} QUIET)
        if(_RMQ_INC)
            target_include_directories(MyQMLService_IDE PRIVATE ${_RMQ_INC})
        endif()
    endif()

    # Non-source files visible in project tree.
    add_custom_target(MyQMLService_ConfigFiles SOURCES
        service_config.json
        README.md
    )
endif()
