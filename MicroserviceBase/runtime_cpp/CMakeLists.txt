cmake_minimum_required(VERSION 3.16)
project(MicroserviceBaseRuntime VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# ---------------------------------------------------------------------------
# microservice_base_runtime — shared C++ library used by every service
# ---------------------------------------------------------------------------
add_library(microservice_base_runtime STATIC
    src/ConsulRegistration.cpp
    src/ConsulResolver.cpp
    src/ServiceRunner.cpp
)

target_include_directories(microservice_base_runtime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

# gRPC server reflection - both supported toolchains (MSYS2's stock
# grpc, and our vcpkg overlay-port which forces gRPC_BUILD_CODEGEN=ON)
# ship `grpc++_reflection`, so this branch is normally taken.  Kept as a
# guard so non-default grpc distributions that omit reflection still
# build (the Manager GUI then falls back to LocalProtoClient on the
# bridge side - see MicroserviceBase/adapters/grpc_bridge/reflect_client.py).
# When the target is present we define MB_HAVE_GRPC_REFLECTION=1 so
# ServiceRunner.h / .cpp can guard the include + the InitProto... call.
if(TARGET gRPC::grpc++_reflection)
    set(_mb_grpc_refl gRPC::grpc++_reflection)
    target_compile_definitions(microservice_base_runtime
        PUBLIC MB_HAVE_GRPC_REFLECTION=1)
else()
    set(_mb_grpc_refl "")
endif()

target_link_libraries(microservice_base_runtime
    PUBLIC
        gRPC::grpc++
        ${_mb_grpc_refl}
        protobuf::libprotobuf
    PRIVATE
        CURL::libcurl
)

# Qt Creator / IDE: expose header tree so it's visible in the project pane.
target_sources(microservice_base_runtime
    PRIVATE
        include/MicroserviceBase/Settings.h
        include/MicroserviceBase/ConsulRegistration.h
        include/MicroserviceBase/ServiceRunner.h
        include/MicroserviceBase/ServiceClient.h
)

# Modern alias so consumers can link against microservice_base::runtime.
add_library(microservice_base::runtime ALIAS microservice_base_runtime)
