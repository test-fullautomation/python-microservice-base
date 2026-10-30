# Custom vcpkg triplet pinned to Qt's MinGW 13.1.0 toolchain.
#
# Why a custom triplet?  vcpkg's stock x64-mingw-dynamic builds with
# whatever mingw is on PATH.  If MSYS2's gcc 14 wins the PATH race,
# the resulting grpc DLLs link fine against everything-mingw14 but NOT
# against Qt 6.x (built with mingw 13.1.0).  Pinning the chainloaded
# toolchain guarantees gcc/g++/windres come from Qt's own MinGW so
# every binary shares one libstdc++ ABI.

set(VCPKG_TARGET_ARCHITECTURE x64)
set(VCPKG_CRT_LINKAGE dynamic)
set(VCPKG_LIBRARY_LINKAGE dynamic)
set(VCPKG_CMAKE_SYSTEM_NAME MinGW)
set(VCPKG_ENV_PASSTHROUGH PATH)

# Build Release only - halves build time and works around a gcc 13.1.0
# ICE in grpc 1.76's per_cpu.h (the 00018 overlay-port patch handles
# the same bug from another angle; both together survive both -O0 and -O3).
set(VCPKG_BUILD_TYPE release)

set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE
    "${CMAKE_CURRENT_LIST_DIR}/qt-mingw-toolchain.cmake")
