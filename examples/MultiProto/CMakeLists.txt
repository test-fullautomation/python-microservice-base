cmake_minimum_required(VERSION 3.16)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{VCPKG_ROOT})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "MultiProto: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.  Set VCPKG_ROOT or pass "
        "-DCMAKE_TOOLCHAIN_FILE=... directly.")
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from triplets/ overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${CMAKE_CURRENT_SOURCE_DIR}/triplets"
            CACHE PATH "vcpkg overlay triplets directory")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/ports")
        set(VCPKG_OVERLAY_PORTS "${CMAKE_CURRENT_SOURCE_DIR}/ports"
            CACHE PATH "vcpkg overlay ports directory")
    endif()
endif()

project(MultiProto VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Manifest-mode fallback: when vcpkg toolchain didn't load but a populated
# vcpkg_installed/x64-mingw-qt/ exists in the build dir.
if(EXISTS "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE
   AND EXISTS "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE
        "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc (target triplet)")
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

if(TARGET gRPC::grpc++_reflection)
    set(GRPC_REFL_LIB gRPC::grpc++_reflection)
else()
    set(GRPC_REFL_LIB "")
endif()

# MicroserviceBase runtime (find_package + env-var + in-tree fallback).
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_candidates "")
    if(DEFINED ENV{MICROSERVICEBASE_DIR})
        list(APPEND _mb_candidates
            "$ENV{MICROSERVICEBASE_DIR}/MicroserviceBase/runtime_cpp"
            "$ENV{MICROSERVICEBASE_DIR}/runtime_cpp"
            "$ENV{MICROSERVICEBASE_DIR}")
    endif()
    list(APPEND _mb_candidates
        "${CMAKE_CURRENT_SOURCE_DIR}/../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${_p}/CMakeLists.txt")
            set(_mb_in_tree "${_p}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        add_subdirectory("${_mb_in_tree}"
                         "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Set MICROSERVICEBASE_DIR env var "
            "to your framework checkout, or install + add to CMAKE_PREFIX_PATH "
            "(see docs/runtime_cpp_install.md).")
    endif()
endif()

# ---- Auto-deploy runtime DLLs (POST_BUILD) ----
# Copies vcpkg DLLs + MinGW runtime + (optional) Qt deploy next to each
# .exe so Qt Creator's F5 (Run/Debug) works without manual PATH manipulation
# or pre-running deploy_qt_vcpkg.bat.  Disable with
# -DMB_DEPLOY_RUNTIME_DEPS=OFF (e.g. for CI builds).
option(MB_DEPLOY_RUNTIME_DEPS "Auto-copy runtime DLLs next to each .exe on build" ON)

function(mb_deploy_runtime target)
    if(NOT MB_DEPLOY_RUNTIME_DEPS OR NOT WIN32)
        return()
    endif()
    cmake_parse_arguments(MBD "QT_APP" "" "" ${ARGN})

    set(_dest "$<TARGET_FILE_DIR:${target}>")

    # 1. vcpkg runtime DLLs.  Glob at configure time -- new DLLs require a
    #    CMake re-configure (vcpkg manifest install triggers one anyway).
    set(_vcpkg_bin
        "${CMAKE_BINARY_DIR}/vcpkg_installed/${VCPKG_TARGET_TRIPLET}/bin")
    if(EXISTS "${_vcpkg_bin}")
        file(GLOB _vcpkg_dlls "${_vcpkg_bin}/*.dll")
        if(_vcpkg_dlls)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                        ${_vcpkg_dlls} "${_dest}"
                COMMENT "[mb-deploy] vcpkg DLLs -> $<TARGET_FILE_DIR:${target}>"
                VERBATIM)
        endif()
    endif()

    # 2. MinGW runtime DLLs (libstdc++-6, libgcc_s_seh-1, libwinpthread-1).
    if(DEFINED ENV{QT_MINGW_BIN})
        set(_mingw_dlls "")
        foreach(_d libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll)
            if(EXISTS "$ENV{QT_MINGW_BIN}/${_d}")
                list(APPEND _mingw_dlls "$ENV{QT_MINGW_BIN}/${_d}")
            endif()
        endforeach()
        if(_mingw_dlls)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                        ${_mingw_dlls} "${_dest}"
                COMMENT "[mb-deploy] MinGW runtime -> $<TARGET_FILE_DIR:${target}>"
                VERBATIM)
        endif()
    endif()

    # 3. Qt deployment (Qt6Core/Gui DLLs + plugins) -- Qt apps only.
    if(MBD_QT_APP AND DEFINED ENV{QT_DIR})
        find_program(MB_WINDEPLOYQT_EXE
            NAMES windeployqt-qt6.exe windeployqt6.exe windeployqt.exe
            HINTS "$ENV{QT_DIR}/bin")
        if(MB_WINDEPLOYQT_EXE)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND "${MB_WINDEPLOYQT_EXE}" --no-translations
                        --no-system-d3d-compiler --no-opengl-sw
                        "$<TARGET_FILE:${target}>"
                COMMENT "[mb-deploy] windeployqt ${target}"
                VERBATIM)
        endif()
    endif()
endfunction()


# ---- Proto codegen (one block per .proto file) -----------------------
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/proto")
set(GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}/gen")
file(MAKE_DIRECTORY "${GEN_DIR}")
if(TARGET protobuf::protoc)
    get_target_property(_protoc protobuf::protoc LOCATION)
else()
    find_program(_protoc NAMES protoc protoc.exe
        HINTS "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-windows/tools/protobuf"
              "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
        REQUIRED)
endif()
if(TARGET gRPC::grpc_cpp_plugin)
    get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
else()
    find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
        HINTS "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-windows/tools/grpc"
              "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/tools/grpc"
        REQUIRED)
endif()

add_custom_command(
    OUTPUT
        "${GEN_DIR}/com_config_device.pb.cc"  "${GEN_DIR}/com_config_device.pb.h"
        "${GEN_DIR}/com_config_device.grpc.pb.cc" "${GEN_DIR}/com_config_device.grpc.pb.h"
    COMMAND ${_protoc}
        --proto_path=${PROTO_DIR}
        --cpp_out=${GEN_DIR}
        --grpc_out=${GEN_DIR}
        --plugin=protoc-gen-grpc=${_grpc_cpp}
        ${PROTO_DIR}/com_config_device.proto
    DEPENDS "${PROTO_DIR}/com_config_device.proto"
    COMMENT "Generating gRPC stubs for com_config_device.proto"
    VERBATIM)
set(COM_CONFIG_DEVICE_SRCS
    "${GEN_DIR}/com_config_device.pb.cc"
    "${GEN_DIR}/com_config_device.grpc.pb.cc")
add_custom_command(
    OUTPUT
        "${GEN_DIR}/power_device.pb.cc"  "${GEN_DIR}/power_device.pb.h"
        "${GEN_DIR}/power_device.grpc.pb.cc" "${GEN_DIR}/power_device.grpc.pb.h"
    COMMAND ${_protoc}
        --proto_path=${PROTO_DIR}
        --cpp_out=${GEN_DIR}
        --grpc_out=${GEN_DIR}
        --plugin=protoc-gen-grpc=${_grpc_cpp}
        ${PROTO_DIR}/power_device.proto
    DEPENDS "${PROTO_DIR}/power_device.proto"
    COMMENT "Generating gRPC stubs for power_device.proto"
    VERBATIM)
set(POWER_DEVICE_SRCS
    "${GEN_DIR}/power_device.pb.cc"
    "${GEN_DIR}/power_device.grpc.pb.cc")

# ---- Single executable hosting all services --------------------------
add_executable(multi_proto
    src/main.cpp
    src/Settings.h
    src/com_setup_device_service/domain/ComSetupDeviceService.h
    src/com_setup_device_service/domain/ComSetupDeviceService.cpp
    src/com_setup_device_service/adapters/api/ComSetupDeviceServiceGrpcAdapter.h
    src/com_setup_device_service/adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    src/power_supply_service/domain/PowerSupplyService.h
    src/power_supply_service/domain/PowerSupplyService.cpp
    src/power_supply_service/adapters/api/PowerSupplyServiceGrpcAdapter.h
    src/power_supply_service/adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    ${COM_CONFIG_DEVICE_SRCS}
    ${POWER_DEVICE_SRCS}
)

target_include_directories(multi_proto PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${GEN_DIR}"
)

target_link_libraries(multi_proto PRIVATE
    microservice_base::runtime
    gRPC::grpc++ ${GRPC_REFL_LIB}
    protobuf::libprotobuf
)
mb_deploy_runtime(multi_proto)

# ---- On-demand `dist` target ----
# Builds the .exe (if not already built) then runs deploy_qt_vcpkg.bat
# to package a self-contained dist-qt-vcpkg/ folder.  Invoke from CLI:
#   cmake --build <build-dir> --target dist
# In Qt Creator: Projects -> Build -> Build Steps -> Add "CMake Build" step
# with Targets = "dist".  Doesn't fire on F5 / Build All -- only when
# explicitly requested -- so day-to-day builds stay snappy.
if(WIN32 AND EXISTS "${CMAKE_SOURCE_DIR}/deploy_qt_vcpkg.bat")
    add_custom_target(dist
        COMMAND "${CMAKE_SOURCE_DIR}/deploy_qt_vcpkg.bat"
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        DEPENDS multi_proto
        COMMENT "[mb-dist] Packaging dist-qt-vcpkg/ via deploy_qt_vcpkg.bat"
        USES_TERMINAL
        VERBATIM)
endif()
