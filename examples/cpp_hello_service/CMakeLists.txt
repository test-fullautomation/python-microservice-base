cmake_minimum_required(VERSION 3.16)
project(cpp_hello_service VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# ---------------------------------------------------------------------------
# MicroserviceBase runtime library (shared with other C++ services)
# ---------------------------------------------------------------------------
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/runtime_cpp"
    "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime"
)

# ---------------------------------------------------------------------------
# Generate hello.pb.{h,cc} and hello.grpc.pb.{h,cc} from hello.proto
# ---------------------------------------------------------------------------
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/proto")
set(GEN_DIR   "${CMAKE_CURRENT_BINARY_DIR}/gen")
file(MAKE_DIRECTORY "${GEN_DIR}")

set(HELLO_PROTO "${PROTO_DIR}/hello.proto")
set(HELLO_SRCS
    "${GEN_DIR}/hello.pb.cc"
    "${GEN_DIR}/hello.pb.h"
    "${GEN_DIR}/hello.grpc.pb.cc"
    "${GEN_DIR}/hello.grpc.pb.h"
)

# Locate protoc and the gRPC C++ plugin exposed by the gRPC package.
get_target_property(_protoc_executable protobuf::protoc LOCATION)
get_target_property(_grpc_cpp_plugin   gRPC::grpc_cpp_plugin LOCATION)

add_custom_command(
    OUTPUT ${HELLO_SRCS}
    COMMAND ${_protoc_executable}
        --proto_path="${PROTO_DIR}"
        --cpp_out="${GEN_DIR}"
        --grpc_out="${GEN_DIR}"
        --plugin=protoc-gen-grpc="${_grpc_cpp_plugin}"
        "${HELLO_PROTO}"
    DEPENDS "${HELLO_PROTO}"
    COMMENT "Generating gRPC stubs from hello.proto"
)

# ---------------------------------------------------------------------------
# Hello service executable
# ---------------------------------------------------------------------------
add_executable(hello_service
    src/main.cpp
    src/Settings.h
    src/domain/HelloService.h
    src/domain/HelloService.cpp
    src/adapters/api/HelloGrpcAdapter.h
    src/adapters/api/HelloGrpcAdapter.cpp
    ${HELLO_SRCS}
)

target_include_directories(hello_service PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${GEN_DIR}"
)

target_link_libraries(hello_service PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    gRPC::grpc++_reflection
    protobuf::libprotobuf
)

# The client has been moved to a separate project: examples/cpp_hello_client/
# This demonstrates the real-world workflow where the service and client
# are developed independently — the client only needs the .proto file
# and the MicroserviceBase runtime library.
