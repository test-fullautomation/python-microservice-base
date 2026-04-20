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

target_link_libraries(microservice_base_runtime
    PUBLIC
        gRPC::grpc++
        gRPC::grpc++_reflection
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
