cmake_minimum_required(VERSION 3.16)
project(TestServiceQtClient VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Qt 6 discovery — honour both Qt6_DIR (cmake config dir) and QT_DIR
# (Qt install prefix), so users can point this anywhere from the env
# without touching CMakeLists.
if(NOT DEFINED Qt6_DIR AND DEFINED ENV{Qt6_DIR})
    set(Qt6_DIR "$ENV{Qt6_DIR}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{QT_DIR} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{QT_DIR}")
endif()

# ---- Locate Google's protoc ---------------------------------------------
# Qt's qt_add_grpc / qt_add_protobuf invoke `protoc` at build time (Qt
# only ships the Qt-side plugins).  Make the path discoverable without
# relying on PATH, so the build works from Qt Creator, raw cmake, or
# build_qt.bat.  Override priority:
#   1. -DProtobuf_PROTOC_EXECUTABLE=...
#   2. PROTOC_DIR env var (folder containing protoc.exe)
#   3. C:/msys64/mingw64/bin
#   4. <VCPKG_ROOT>/installed/x64-windows/tools/protobuf
#   5. find_program() on PATH
if(NOT Protobuf_PROTOC_EXECUTABLE)
    set(_protoc_candidates)
    if(DEFINED ENV{PROTOC_DIR})
        list(APPEND _protoc_candidates
            "$ENV{PROTOC_DIR}/protoc.exe"
            "$ENV{PROTOC_DIR}/protoc")
    endif()
    list(APPEND _protoc_candidates
        "C:/msys64/mingw64/bin/protoc.exe"
        "C:/msys64/ucrt64/bin/protoc.exe")
    if(DEFINED ENV{VCPKG_ROOT})
        list(APPEND _protoc_candidates
            "$ENV{VCPKG_ROOT}/installed/x64-windows/tools/protobuf/protoc.exe")
    endif()
    foreach(_c IN LISTS _protoc_candidates)
        if(EXISTS "${_c}")
            set(Protobuf_PROTOC_EXECUTABLE "${_c}"
                CACHE FILEPATH "protoc executable used by qt_add_grpc / qt_add_protobuf")
            break()
        endif()
    endforeach()
    if(NOT Protobuf_PROTOC_EXECUTABLE)
        find_program(Protobuf_PROTOC_EXECUTABLE NAMES protoc protoc.exe)
    endif()
endif()

# Whatever set Protobuf_PROTOC_EXECUTABLE — auto-discovery above OR an
# externally-passed `-DProtobuf_PROTOC_EXECUTABLE=...` — also propagate
# PATH + CMAKE_PREFIX_PATH so Qt's WrapProtoc (which does its own
# find_program(protoc)) and FindProtobuf (wants headers + libs) succeed.
if(Protobuf_PROTOC_EXECUTABLE)
    message(STATUS "Using protoc: ${Protobuf_PROTOC_EXECUTABLE}")
    get_filename_component(_protoc_dir "${Protobuf_PROTOC_EXECUTABLE}" DIRECTORY)
    set(ENV{PATH} "${_protoc_dir};$ENV{PATH}")

    get_filename_component(_protoc_prefix "${_protoc_dir}/.." ABSOLUTE)
    list(APPEND CMAKE_PREFIX_PATH "${_protoc_prefix}")
    message(STATUS "Adding to CMAKE_PREFIX_PATH for Protobuf headers/libs: ${_protoc_prefix}")
else()
    message(FATAL_ERROR
        "protoc not found.  Qt's qt_add_grpc / qt_add_protobuf needs "
        "Google's protoc at build time.  Install MSYS2's "
        "mingw-w64-x86_64-protobuf, or download a Windows release "
        "from https://github.com/protocolbuffers/protobuf/releases "
        "and pass -DProtobuf_PROTOC_EXECUTABLE=<path/to/protoc.exe>.")
endif()

find_package(Qt6 REQUIRED COMPONENTS
    Core
    Gui
    Widgets
    Network
    Grpc
    Protobuf
    ProtobufWellKnownTypes)

qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)

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


qt_add_executable(test_service_qt_gui
    src/main.cpp
    src/MainWindow.cpp
    src/MainWindow.h
    src/MainWindow.ui)

# Make AUTOUIC look in src/ for the .ui file
set(CMAKE_AUTOUIC_SEARCH_PATHS "${CMAKE_CURRENT_SOURCE_DIR}/src")

# Generate Qt-style protobuf message classes (QProtobufMessage subclasses).
# OUTPUT_DIRECTORY MUST live under the build tree — writing generated
# `*.qpb.{h,cpp}` back into the source tree causes ninja to detect the
# source dir as "dirty" on every build and re-run cmake forever
# ("manifest 'build.ninja' still dirty after 100 tries").  IDEs pick up
# the generated headers via compile_commands.json / the target's include
# dirs.  proto/generate_qt_stubs.bat runs the same protoc command
# outside CMake for one-shot pre-generation if you want to browse stubs
# alongside the .proto source.
qt_add_protobuf(test_service_qt_gui
    PROTO_FILES
        proto/com_config_device.proto
        proto/power_device.proto
    OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/qt_proto_gen")

# Generate Qt-style gRPC client stubs (no SERVER variant — Qt 6 doesn't
# provide one; the service is built with Google grpc++ separately).
qt_add_grpc(test_service_qt_gui CLIENT
    PROTO_FILES
        proto/com_config_device.proto
        proto/power_device.proto
    OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/qt_proto_gen")

target_include_directories(test_service_qt_gui PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${CMAKE_CURRENT_BINARY_DIR}/qt_proto_gen")

target_link_libraries(test_service_qt_gui PRIVATE
    Qt6::Widgets
    Qt6::Network
    Qt6::Grpc
    Qt6::Protobuf
    Qt6::ProtobufWellKnownTypes)

set_target_properties(test_service_qt_gui PROPERTIES
    WIN32_EXECUTABLE ON
    MACOSX_BUNDLE    ON)

mb_deploy_runtime(test_service_qt_gui QT_APP)
