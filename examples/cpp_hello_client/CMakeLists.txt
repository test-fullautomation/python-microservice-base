cmake_minimum_required(VERSION 3.16)
project(hello_client VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)

# MicroserviceBase runtime — provides ServiceClient<T> with Consul discovery.
# Adjust this path if your project lives outside the examples/ directory.
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/runtime_cpp"
    "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime"
)

# ---------------------------------------------------------------------------
# Pre-generated stubs from the service's .proto file.
#
# Run generate_stubs.bat (Windows) or generate_stubs.sh (Linux) ONCE
# to produce these files.  After that, they are regular C++ source that
# compiles without protoc being installed.
# ---------------------------------------------------------------------------
set(GEN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/gen")

set(STUB_SRCS
    "${GEN_DIR}/hello.pb.cc"
    "${GEN_DIR}/hello.pb.h"
    "${GEN_DIR}/hello.grpc.pb.cc"
    "${GEN_DIR}/hello.grpc.pb.h"
)

# Verify the stubs exist at configure time.
foreach(_f ${STUB_SRCS})
    if(NOT EXISTS "${_f}")
        message(FATAL_ERROR
            "Generated stub not found: ${_f}\n"
            "Run generate_stubs.bat (Windows) or generate_stubs.sh (Linux) first:\n"
            "  cd ${CMAKE_CURRENT_SOURCE_DIR}\n"
            "  generate_stubs.bat          (Windows)\n"
            "  ./generate_stubs.sh         (Linux)")
    endif()
endforeach()

# ---------------------------------------------------------------------------
# Client executable
# ---------------------------------------------------------------------------
add_executable(hello_client
    src/client.cpp
    ${STUB_SRCS}
)

target_include_directories(hello_client PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${GEN_DIR}"
)

target_link_libraries(hello_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
)
