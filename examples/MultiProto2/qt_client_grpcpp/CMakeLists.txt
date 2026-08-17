cmake_minimum_required(VERSION 3.20)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
# Mirrors the parent server CMakeLists; overlays live in the PARENT project.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{VCPKG_ROOT})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "qt_client_grpcpp: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.")
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (parent overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${CMAKE_CURRENT_SOURCE_DIR}/../triplets"
            CACHE PATH "vcpkg overlay triplets")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../ports")
        set(VCPKG_OVERLAY_PORTS "${CMAKE_CURRENT_SOURCE_DIR}/../ports"
            CACHE PATH "vcpkg overlay ports")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{VCPKG_ROOT})
        file(GLOB _vcpkg_ninja "$ENV{VCPKG_ROOT}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${_vcpkg_ninja})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${_n}")
            set(CMAKE_MAKE_PROGRAM "${_n}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project(MultiProto2QtClientGrpcpp VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED Qt6_DIR AND DEFINED ENV{Qt6_DIR})
    set(Qt6_DIR "$ENV{Qt6_DIR}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{QT_DIR} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{QT_DIR}")
endif()
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network Concurrent)

if(EXISTS "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE
   AND EXISTS "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE
        "${CMAKE_BINARY_DIR}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc")
endif()

find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC     CONFIG REQUIRED)

qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)

# Generate stubs into the build tree for ALL .proto files (multi_proto).
# protobuf_generate accepts a CMake list of .proto sources and produces
# stubs for every one in a single invocation.
set(_proto_path "${CMAKE_CURRENT_SOURCE_DIR}/proto")
set(_gen_dir    "${CMAKE_CURRENT_BINARY_DIR}/grpc_gen")
file(MAKE_DIRECTORY "${_gen_dir}")

set(_proto_files
    "${_proto_path}/com_config_device.proto"
    "${_proto_path}/power_device.proto")

protobuf_generate(
    LANGUAGE       cpp
    OUT_VAR        PROTO_SRCS
    PROTOS         ${_proto_files}
    PROTOC_OUT_DIR "${_gen_dir}"
    IMPORT_DIRS    "${_proto_path}")

protobuf_generate(
    LANGUAGE             grpc
    OUT_VAR              GRPC_SRCS
    PROTOS               ${_proto_files}
    PROTOC_OUT_DIR       "${_gen_dir}"
    IMPORT_DIRS          "${_proto_path}"
    GENERATE_EXTENSIONS  .grpc.pb.h .grpc.pb.cc
    PLUGIN               "protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>")

qt_add_executable(multi_proto2_qt_gui
    src/main.cpp
    src/MainWindow.cpp
    src/MainWindow.h
    src/MainWindow.ui
    ${PROTO_SRCS}
    ${GRPC_SRCS})

set(CMAKE_AUTOUIC_SEARCH_PATHS "${CMAKE_CURRENT_SOURCE_DIR}/src")

target_include_directories(multi_proto2_qt_gui PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${_gen_dir}")

target_link_libraries(multi_proto2_qt_gui PRIVATE
    Qt6::Widgets Qt6::Network Qt6::Concurrent
    protobuf::libprotobuf
    gRPC::grpc++)

set_target_properties(multi_proto2_qt_gui PROPERTIES
    WIN32_EXECUTABLE ON MACOSX_BUNDLE ON)

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

mb_deploy_runtime(multi_proto2_qt_gui QT_APP)
