cmake_minimum_required(VERSION 3.16)
project(TestService VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Auto-detect vcpkg if CMAKE_TOOLCHAIN_FILE is not set.
# This lets the project build from Qt Creator without manually configuring
# the kit — it reads VCPKG_ROOT from the environment (or a CMakePresets.json
# in the parent tree) and adds the vcpkg installed dir to CMAKE_PREFIX_PATH.
# ---------------------------------------------------------------------------
if(NOT CMAKE_TOOLCHAIN_FILE)
    if(DEFINED ENV{VCPKG_ROOT})
        set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
            CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
    elseif(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json")
        file(READ "${CMAKE_CURRENT_SOURCE_DIR}/CMakePresets.json" _presets)
        string(REGEX MATCH "\"toolchainFile\"[^\"]*\"([^\"]+)\"" _match "${_presets}")
        if(CMAKE_MATCH_1)
            set(CMAKE_TOOLCHAIN_FILE "${CMAKE_MATCH_1}"
                CACHE PATH "vcpkg toolchain (from CMakePresets.json)")
        endif()
    endif()
endif()

# If vcpkg toolchain is set but packages still aren't found, add the
# installed prefix to CMAKE_PREFIX_PATH so find_package(CONFIG) works
# even when Qt Creator's auto-setup overrides CMAKE_PREFIX_PATH.
if(CMAKE_TOOLCHAIN_FILE AND EXISTS "${CMAKE_TOOLCHAIN_FILE}")
    get_filename_component(_vcpkg_root "${CMAKE_TOOLCHAIN_FILE}" DIRECTORY)
    get_filename_component(_vcpkg_root "${_vcpkg_root}" DIRECTORY)
    get_filename_component(_vcpkg_root "${_vcpkg_root}" DIRECTORY)
    if(EXISTS "${_vcpkg_root}/installed/x64-windows/share")
        list(APPEND CMAKE_PREFIX_PATH "${_vcpkg_root}/installed/x64-windows")
    endif()
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# MicroserviceBase C++ runtime library
# Adjust this path if your project is not inside the examples/ directory.
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/runtime_cpp"
    "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime"
)

# ---------------------------------------------------------------------------
# Proto stubs.  Two modes:
#   1. Pre-generated: run proto/generate_stubs.bat (or .sh) once.
#      Stubs live in proto/ alongside the .proto source.
#   2. Auto-generate: if pre-generated stubs are missing, CMake runs
#      protoc at build time into build/gen/.
# ---------------------------------------------------------------------------
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/proto")

if(EXISTS "${PROTO_DIR}/test_service.pb.h")
    # Pre-generated stubs found — use them directly.
    set(TEST_SERVICE_SRCS
        "${PROTO_DIR}/test_service.pb.cc"
        "${PROTO_DIR}/test_service.grpc.pb.cc"
    )
    set(TEST_SERVICE_INC "${PROTO_DIR}")
    message(STATUS "Using pre-generated proto stubs from ${PROTO_DIR}")
else()
    # Auto-generate at build time.
    set(GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}/gen")
    file(MAKE_DIRECTORY "${GEN_DIR}")
    set(TEST_SERVICE_SRCS
        "${GEN_DIR}/test_service.pb.cc"
        "${GEN_DIR}/test_service.grpc.pb.cc"
    )
    set(TEST_SERVICE_INC "${GEN_DIR}")

    get_target_property(_protoc   protobuf::protoc       LOCATION)
    get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin  LOCATION)

    add_custom_command(
        OUTPUT
            "${GEN_DIR}/test_service.pb.cc"  "${GEN_DIR}/test_service.pb.h"
            "${GEN_DIR}/test_service.grpc.pb.cc" "${GEN_DIR}/test_service.grpc.pb.h"
        COMMAND ${_protoc}
            --proto_path="${PROTO_DIR}"
            --cpp_out="${GEN_DIR}"
            --grpc_out="${GEN_DIR}"
            --plugin=protoc-gen-grpc="${_grpc_cpp}"
            "${PROTO_DIR}/test_service.proto"
        DEPENDS "${PROTO_DIR}/test_service.proto"
        COMMENT "Auto-generating gRPC stubs (run proto/generate_stubs to pre-generate)"
    )
    message(STATUS "Proto stubs will be auto-generated at build time")
endif()

# Service executable

add_executable(test_service
    src/main.cpp
    src/Settings.h
    src/domain/TestServiceService.h
    src/domain/TestServiceService.cpp
    src/adapters/api/TestServiceGrpcAdapter.h
    src/adapters/api/TestServiceGrpcAdapter.cpp
    ${TEST_SERVICE_SRCS}
)

target_include_directories(test_service PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${TEST_SERVICE_INC}"
)

target_link_libraries(test_service PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    gRPC::grpc++_reflection
    protobuf::libprotobuf
)
