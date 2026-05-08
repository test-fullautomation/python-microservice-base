# vcpkg overlay-port for the MicroserviceBase C++ runtime.
#
# Usage from a consumer project's vcpkg.json:
#
#     {
#       "dependencies": ["microservice-base"]
#     }
#
# And in the consumer's vcpkg invocation / cmake configure:
#
#     -DVCPKG_OVERLAY_PORTS=<path-to-this-repo>/ports
#
# vcpkg then installs MicroserviceBase into vcpkg_installed/<triplet>/
# alongside grpc, protobuf, curl.  Consumer's CMakeLists.txt does:
#
#     find_package(MicroserviceBase CONFIG REQUIRED)
#     target_link_libraries(my_service PRIVATE microservice_base::runtime)
#
# ---------------------------------------------------------------------------

# Source: this repo, runtime_cpp/ subfolder.  When vcpkg fetches an
# overlay-port the typical pattern is vcpkg_from_github / git_clone, but
# since this is a Bosch-internal port we point directly at the framework
# checkout via VCPKG_MICROSERVICE_BASE_SOURCE env var (or the
# repo-relative default).
if(DEFINED ENV{VCPKG_MICROSERVICE_BASE_SOURCE})
    set(SOURCE_PATH "$ENV{VCPKG_MICROSERVICE_BASE_SOURCE}")
else()
    # Default: the framework repo is one level up from `ports/`.
    get_filename_component(SOURCE_PATH "${CMAKE_CURRENT_LIST_DIR}/../../MicroserviceBase/runtime_cpp" ABSOLUTE)
endif()

if(NOT EXISTS "${SOURCE_PATH}/CMakeLists.txt")
    message(FATAL_ERROR
        "microservice-base overlay-port: source not found at ${SOURCE_PATH}.\n"
        "Set VCPKG_MICROSERVICE_BASE_SOURCE env var to the runtime_cpp/ folder, "
        "or move this overlay-port one level deeper inside the framework repo.")
endif()

vcpkg_cmake_configure(
    SOURCE_PATH "${SOURCE_PATH}"
    OPTIONS
        # No options — runtime_cpp's CMakeLists is self-contained.
)

vcpkg_cmake_install()
vcpkg_cmake_config_fixup(
    PACKAGE_NAME MicroserviceBase
    CONFIG_PATH  lib/cmake/MicroserviceBase
)

# License file (Apache 2.0 from the repo root).
get_filename_component(_repo_root "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
if(EXISTS "${_repo_root}/LICENSE")
    vcpkg_install_copyright(FILE_LIST "${_repo_root}/LICENSE")
else()
    file(WRITE "${CURRENT_PACKAGES_DIR}/share/${PORT}/copyright"
        "Apache License 2.0 — see https://www.apache.org/licenses/LICENSE-2.0\n")
endif()

file(REMOVE_RECURSE
    "${CURRENT_PACKAGES_DIR}/debug/include"
)
