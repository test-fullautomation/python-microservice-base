cmake_minimum_required(VERSION 3.16)
project(CppServiceBase VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
# rabbitmq-c: try vcpkg CONFIG first, then pkg-config, then manual hints.
# nlohmann-json: try vcpkg CONFIG first, then find header on include path.
#
# On Windows with MSVC, install both via vcpkg:
#   vcpkg install rabbitmq-c:x64-windows nlohmann-json:x64-windows
# Then pass -DCMAKE_TOOLCHAIN_FILE=.../vcpkg/scripts/buildsystems/vcpkg.cmake
# ---------------------------------------------------------------------------

# --- Auto-detect vcpkg root when used as a subdirectory ---
# The parent project may set CMAKE_PREFIX_PATH, but find_library / find_path
# also benefit from explicit HINTS to the vcpkg installed directories.
set(_VCPKG_LIB_DIR "")
set(_VCPKG_INC_DIR "")
foreach(_prefix ${CMAKE_PREFIX_PATH})
    if(EXISTS "${_prefix}/lib")
        set(_VCPKG_LIB_DIR "${_prefix}/lib")
    endif()
    if(EXISTS "${_prefix}/include")
        set(_VCPKG_INC_DIR "${_prefix}/include")
    endif()
endforeach()

# --- rabbitmq-c ---
set(_RABBITMQ_FOUND FALSE)

find_package(rabbitmq-c CONFIG QUIET)
if(rabbitmq-c_FOUND)
    set(_RABBITMQ_FOUND TRUE)
    set(_RABBITMQ_TARGET rabbitmq::rabbitmq)
endif()

if(NOT _RABBITMQ_FOUND)
    # Try FindAMQP-style (some distros ship a Find module).
    find_library(RABBITMQ_LIBRARY NAMES rabbitmq rabbitmq.4
        HINTS ${_VCPKG_LIB_DIR} QUIET)
    find_path(RABBITMQ_INCLUDE_DIR amqp.h
        HINTS ${_VCPKG_INC_DIR} QUIET)
    if(RABBITMQ_LIBRARY AND RABBITMQ_INCLUDE_DIR)
        set(_RABBITMQ_FOUND TRUE)
        add_library(rabbitmq::rabbitmq UNKNOWN IMPORTED)
        set_target_properties(rabbitmq::rabbitmq PROPERTIES
            IMPORTED_LOCATION "${RABBITMQ_LIBRARY}"
            INTERFACE_INCLUDE_DIRECTORIES "${RABBITMQ_INCLUDE_DIR}"
        )
        set(_RABBITMQ_TARGET rabbitmq::rabbitmq)
    endif()
endif()

if(NOT _RABBITMQ_FOUND AND NOT WIN32)
    # Linux/macOS fallback: pkg-config.
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        pkg_check_modules(RABBITMQ QUIET librabbitmq)
        if(RABBITMQ_FOUND)
            set(_RABBITMQ_FOUND TRUE)
        endif()
    endif()
endif()

if(NOT _RABBITMQ_FOUND)
    message(FATAL_ERROR
        "rabbitmq-c not found.\n"
        "  Windows: vcpkg install rabbitmq-c:x64-windows  (+ pass CMAKE_TOOLCHAIN_FILE)\n"
        "  Linux:   sudo apt install librabbitmq-dev\n"
        "  macOS:   brew install rabbitmq-c")
endif()

# --- nlohmann-json ---
find_package(nlohmann_json CONFIG QUIET)
if(NOT nlohmann_json_FOUND)
    find_path(NLOHMANN_JSON_INCLUDE nlohmann/json.hpp
        HINTS ${_VCPKG_INC_DIR})
    if(NLOHMANN_JSON_INCLUDE)
        add_library(nlohmann_json::nlohmann_json INTERFACE IMPORTED)
        target_include_directories(nlohmann_json::nlohmann_json INTERFACE
            ${NLOHMANN_JSON_INCLUDE})
    else()
        message(FATAL_ERROR
            "nlohmann/json.hpp not found.\n"
            "  Windows: vcpkg install nlohmann-json:x64-windows\n"
            "  Linux:   sudo apt install nlohmann-json3-dev\n"
            "  macOS:   brew install nlohmann-json")
    endif()
endif()

# ---------------------------------------------------------------------------
# Library target
# ---------------------------------------------------------------------------

add_library(CppServiceBase STATIC
    src/ServiceBase.cpp
    src/RabbitMQConnection.cpp
)

target_include_directories(CppServiceBase PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

target_link_libraries(CppServiceBase PUBLIC
    nlohmann_json::nlohmann_json
)

# Link rabbitmq-c (vcpkg / manual / pkg-config).
if(_RABBITMQ_TARGET)
    target_link_libraries(CppServiceBase PUBLIC ${_RABBITMQ_TARGET})
elseif(RABBITMQ_FOUND)
    # pkg-config path
    target_include_directories(CppServiceBase PUBLIC ${RABBITMQ_INCLUDE_DIRS})
    target_link_libraries(CppServiceBase PUBLIC ${RABBITMQ_LIBRARIES})
endif()

# Platform threading
find_package(Threads REQUIRED)
target_link_libraries(CppServiceBase PUBLIC Threads::Threads)

# Optional zlib for ZIP DEFLATE compression in svc_api_get_service_files.
# Opt-in only — set -DSERVICEBASE_USE_ZLIB=ON to enable.
# Avoids accidental runtime dependency on zlib DLL when vcpkg auto-detects it.
option(SERVICEBASE_USE_ZLIB "Enable DEFLATE compression (requires zlib)" OFF)
if(SERVICEBASE_USE_ZLIB)
    find_package(ZLIB REQUIRED)
    target_link_libraries(CppServiceBase PRIVATE ZLIB::ZLIB)
    target_compile_definitions(CppServiceBase PRIVATE HAS_ZLIB)
endif()
