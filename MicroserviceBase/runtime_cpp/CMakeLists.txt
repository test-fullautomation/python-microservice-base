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

# ---------------------------------------------------------------------------
# Install + export
# ---------------------------------------------------------------------------
# Make the runtime consumable as an installed CMake package so generated
# services can:
#
#     find_package(MicroserviceBase CONFIG REQUIRED)
#     target_link_libraries(my_service PRIVATE microservice_base::runtime)
#
# instead of `add_subdirectory()`-ing the framework repo at a relative
# path.  This is what lets generated services be truly standalone.
#
# Install flow (one-time per machine, or via a vcpkg port):
#
#     cmake -S MicroserviceBase/runtime_cpp -B build/runtime_cpp \
#           -DCMAKE_INSTALL_PREFIX=/path/to/install/prefix
#     cmake --build build/runtime_cpp --target install
#
# After that, consumers add `<prefix>` to CMAKE_PREFIX_PATH and
# find_package() picks up MicroserviceBaseConfig.cmake from
# <prefix>/lib/cmake/MicroserviceBase/.
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

install(TARGETS microservice_base_runtime
    EXPORT  MicroserviceBaseTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install(DIRECTORY include/MicroserviceBase
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
    FILES_MATCHING PATTERN "*.h"
)

install(EXPORT MicroserviceBaseTargets
    FILE        MicroserviceBaseTargets.cmake
    NAMESPACE   microservice_base::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/MicroserviceBase
)

# Generate MicroserviceBaseConfig.cmake from a small template.  The
# template re-runs find_package() for our transitive deps so consumers
# only need the one find_package(MicroserviceBase) call.
set(_mb_config_in "${CMAKE_CURRENT_BINARY_DIR}/MicroserviceBaseConfig.cmake.in")
file(WRITE "${_mb_config_in}" [=[
@PACKAGE_INIT@

include(CMakeFindDependencyMacro)
find_dependency(gRPC     CONFIG)
find_dependency(Protobuf CONFIG)
find_dependency(CURL     CONFIG)

include("${CMAKE_CURRENT_LIST_DIR}/MicroserviceBaseTargets.cmake")

# install(EXPORT NAMESPACE microservice_base::) exports the real target
# name as microservice_base::microservice_base_runtime.  Add the modern
# short alias `microservice_base::runtime` so consumers can use the
# pretty name (matches the in-tree ALIAS declared in our CMakeLists).
if(TARGET microservice_base::microservice_base_runtime
   AND NOT TARGET microservice_base::runtime)
    add_library(microservice_base::runtime
                ALIAS microservice_base::microservice_base_runtime)
endif()

# Backwards-compat alias: when this package was bundled in-tree the
# legacy target name was `microservice_base_runtime` (no namespace).
# Provide it here so generated CMakeLists from before the split still
# link correctly.
if(TARGET microservice_base::runtime AND NOT TARGET microservice_base_runtime)
    add_library(microservice_base_runtime
                ALIAS microservice_base::microservice_base_runtime)
endif()

check_required_components(MicroserviceBase)
]=])

configure_package_config_file(
    "${_mb_config_in}"
    "${CMAKE_CURRENT_BINARY_DIR}/MicroserviceBaseConfig.cmake"
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/MicroserviceBase
)

write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/MicroserviceBaseConfigVersion.cmake"
    VERSION       ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/MicroserviceBaseConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/MicroserviceBaseConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/MicroserviceBase
)
