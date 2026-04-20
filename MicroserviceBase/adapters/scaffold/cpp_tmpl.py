"""C++ service scaffold templates.

Generates CMake-based projects for gRPC microservices using the
MicroserviceBase C++ runtime (ServiceRunner + ConsulRegistration).
Supports four GUI variants: none, qml, wasm, widget.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from .generator import ScaffoldSpec


def generate(spec: "ScaffoldSpec") -> Dict[str, str]:
    files: Dict[str, str] = {}

    # ---- Service project ----
    files["CMakeLists.txt"] = _cmake(spec)
    files["src/main.cpp"] = _main_cpp(spec)
    files["src/Settings.h"] = _settings_h(spec)
    files[f"src/domain/{spec.service_name}Service.h"] = _domain_h(spec)
    files[f"src/domain/{spec.service_name}Service.cpp"] = _domain_cpp(spec)
    files[f"src/adapters/api/{spec.service_name}GrpcAdapter.h"] = _adapter_h(spec)
    files[f"src/adapters/api/{spec.service_name}GrpcAdapter.cpp"] = _adapter_cpp(spec)

    # Central env var file — all build scripts source this so the user
    # only has to configure paths in one place.
    files["set_env.bat"] = _set_env_bat(spec)
    files["set_env.sh"] = _set_env_sh(spec)

    # Generate stubs scripts go in proto/ (shared by service + client)
    files["proto/generate_stubs.bat"] = _gen_stubs_bat(spec)
    files["proto/generate_stubs.sh"] = _gen_stubs_sh(spec)

    if spec.gen_build_scripts:
        files["build_deploy.bat"] = _build_bat(spec)
        files["build_deploy.sh"] = _build_sh(spec)
        # MinGW variant of the Windows deploy script (Ninja + g++).
        files["build_deploy_mingw.bat"] = _build_mingw_bat(spec)

    if spec.gui_type == "qml":
        files.update(_qml_files(spec))
    elif spec.gui_type == "wasm":
        files.update(_wasm_files(spec))
        if spec.gen_build_scripts:
            files["build_wasm.bat"] = _build_wasm_bat(spec)
            files["build_wasm.sh"] = _build_wasm_sh(spec)
    elif spec.gui_type == "widget":
        files.update(_widget_files(spec))

    # ---- Client subproject ----
    files.update(_client_files(spec))

    return files


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _upper(name: str) -> str:
    return _snake(name).upper()


# -----------------------------------------------------------------------
# CMakeLists.txt
# -----------------------------------------------------------------------

def _cmake(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    gui = spec.gui_type

    # Proto stubs — prefer pre-generated files from proto/ (run
    # proto/generate_stubs.bat once).  Fall back to CMake auto-generation
    # if they don't exist yet.
    proto_block = f'''
# ---------------------------------------------------------------------------
# Proto stubs.  Two modes:
#   1. Pre-generated: run proto/generate_stubs.bat (or .sh) once.
#      Stubs live in proto/ alongside the .proto source.
#   2. Auto-generate: if pre-generated stubs are missing, CMake runs
#      protoc at build time into build/gen/.
# ---------------------------------------------------------------------------
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/proto")

if(EXISTS "${{PROTO_DIR}}/{sn}.pb.h")
    # Pre-generated stubs found — use them directly.
    set({_upper(svc)}_SRCS
        "${{PROTO_DIR}}/{sn}.pb.cc"
        "${{PROTO_DIR}}/{sn}.grpc.pb.cc"
    )
    set({_upper(svc)}_INC "${{PROTO_DIR}}")
    message(STATUS "Using pre-generated proto stubs from ${{PROTO_DIR}}")
else()
    # Auto-generate at build time.
    set(GEN_DIR "${{CMAKE_CURRENT_BINARY_DIR}}/gen")
    file(MAKE_DIRECTORY "${{GEN_DIR}}")
    set({_upper(svc)}_SRCS
        "${{GEN_DIR}}/{sn}.pb.cc"
        "${{GEN_DIR}}/{sn}.grpc.pb.cc"
    )
    set({_upper(svc)}_INC "${{GEN_DIR}}")

    get_target_property(_protoc   protobuf::protoc       LOCATION)
    get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin  LOCATION)

    add_custom_command(
        OUTPUT
            "${{GEN_DIR}}/{sn}.pb.cc"  "${{GEN_DIR}}/{sn}.pb.h"
            "${{GEN_DIR}}/{sn}.grpc.pb.cc" "${{GEN_DIR}}/{sn}.grpc.pb.h"
        COMMAND ${{_protoc}}
            --proto_path="${{PROTO_DIR}}"
            --cpp_out="${{GEN_DIR}}"
            --grpc_out="${{GEN_DIR}}"
            --plugin=protoc-gen-grpc="${{_grpc_cpp}}"
            "${{PROTO_DIR}}/{sn}.proto"
        DEPENDS "${{PROTO_DIR}}/{sn}.proto"
        COMMENT "Auto-generating gRPC stubs (run proto/generate_stubs to pre-generate)"
    )
    message(STATUS "Proto stubs will be auto-generated at build time")
endif()'''

    # Service executable
    exe_block = f'''
add_executable({sn}
    src/main.cpp
    src/Settings.h
    src/domain/{svc}Service.h
    src/domain/{svc}Service.cpp
    src/adapters/api/{svc}GrpcAdapter.h
    src/adapters/api/{svc}GrpcAdapter.cpp
    ${{{_upper(svc)}_SRCS}}
)

target_include_directories({sn} PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{{_upper(svc)}_INC}}"
)

target_link_libraries({sn} PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    gRPC::grpc++_reflection
    protobuf::libprotobuf
)'''

    return f'''cmake_minimum_required(VERSION 3.16)
project({svc} VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Auto-detect vcpkg if CMAKE_TOOLCHAIN_FILE is not set.
# This lets the project build from Qt Creator without manually configuring
# the kit — it reads VCPKG_ROOT from the environment (or a CMakePresets.json
# in the parent tree) and adds the vcpkg installed dir to CMAKE_PREFIX_PATH.
# ---------------------------------------------------------------------------
if(NOT CMAKE_TOOLCHAIN_FILE)
    if(DEFINED ENV{{VCPKG_ROOT}})
        set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
            CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
    elseif(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/CMakePresets.json")
        file(READ "${{CMAKE_CURRENT_SOURCE_DIR}}/CMakePresets.json" _presets)
        string(REGEX MATCH "\\"toolchainFile\\"[^\\"]*\\"([^\\"]+)\\"" _match "${{_presets}}")
        if(CMAKE_MATCH_1)
            set(CMAKE_TOOLCHAIN_FILE "${{CMAKE_MATCH_1}}"
                CACHE PATH "vcpkg toolchain (from CMakePresets.json)")
        endif()
    endif()
endif()

# If vcpkg toolchain is set but packages still aren't found, add the
# installed prefix to CMAKE_PREFIX_PATH so find_package(CONFIG) works
# even when Qt Creator's auto-setup overrides CMAKE_PREFIX_PATH.
if(CMAKE_TOOLCHAIN_FILE AND EXISTS "${{CMAKE_TOOLCHAIN_FILE}}")
    get_filename_component(_vcpkg_root "${{CMAKE_TOOLCHAIN_FILE}}" DIRECTORY)
    get_filename_component(_vcpkg_root "${{_vcpkg_root}}" DIRECTORY)
    get_filename_component(_vcpkg_root "${{_vcpkg_root}}" DIRECTORY)
    if(EXISTS "${{_vcpkg_root}}/installed/x64-windows/share")
        list(APPEND CMAKE_PREFIX_PATH "${{_vcpkg_root}}/installed/x64-windows")
    endif()
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# MicroserviceBase C++ runtime library
# Adjust this path if your project is not inside the examples/ directory.
add_subdirectory(
    "${{CMAKE_CURRENT_SOURCE_DIR}}/../../MicroserviceBase/runtime_cpp"
    "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime"
)
{proto_block}

# Service executable
{exe_block}
'''


# -----------------------------------------------------------------------
# src/main.cpp
# -----------------------------------------------------------------------

def _main_cpp(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    return f'''#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/{svc}Service.h"
#include "adapters/api/{svc}GrpcAdapter.h"

int main() {{
    try {{
        {sn}::Settings settings;
        {sn}::{svc}Service domain;
        {sn}::{svc}GrpcAdapter adapter(domain);

        microservice_base::ServiceRunner runner(settings, {{"v1"}});
        runner.addService(&adapter, "{spec.proto_package}.{svc}Service");
        runner.serveForever();
    }} catch (const std::exception& e) {{
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }}
    return 0;
}}
'''


# -----------------------------------------------------------------------
# src/Settings.h
# -----------------------------------------------------------------------

def _settings_h(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    prefix = spec.env_prefix
    return f'''#pragma once

#include "MicroserviceBase/Settings.h"

namespace {sn} {{

struct Settings : public microservice_base::BaseServiceSettings {{
    Settings() {{
        service_name = "{sn}";
        loadBaseFromEnv("{prefix}");
    }}
}};

}}  // namespace {sn}
'''


# -----------------------------------------------------------------------
# Domain
# -----------------------------------------------------------------------

def _domain_h(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        methods += f"    std::string {_snake(m.name)}({params}) const;\n"

    return f'''#pragma once

#include <string>

namespace {sn} {{

class {svc}Service {{
public:
{methods if methods else "    // Add methods here."}
}};

}}  // namespace {sn}
'''


def _domain_cpp(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        methods += f'''
std::string {svc}Service::{_snake(m.name)}({params}) const {{
    // TODO: implement
    return "not implemented";
}}
'''

    return f'''#include "{svc}Service.h"

namespace {sn} {{
{methods if methods else "// Add implementations here."}
}}  // namespace {sn}
'''


# -----------------------------------------------------------------------
# gRPC Adapter
# -----------------------------------------------------------------------

def _adapter_h(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name

    methods = ""
    for m in spec.methods:
        if m.server_streaming:
            methods += (
                f"    grpc::Status {m.name}(grpc::ServerContext*,\n"
                f"        const {sn}::v1::{m.name}Request*,\n"
                f"        grpc::ServerWriter<{sn}::v1::{m.name}Response>*) override;\n\n"
            )
        else:
            methods += (
                f"    grpc::Status {m.name}(grpc::ServerContext*,\n"
                f"        const {sn}::v1::{m.name}Request*,\n"
                f"        {sn}::v1::{m.name}Response*) override;\n\n"
            )

    return f'''#pragma once

#include <grpcpp/grpcpp.h>
#include "{sn}.grpc.pb.h"
#include "domain/{svc}Service.h"

namespace {sn} {{

class {svc}GrpcAdapter final : public {sn}::v1::{svc}Service::Service {{
public:
    explicit {svc}GrpcAdapter({svc}Service& domain) : m_domain(domain) {{}}

{methods}
private:
    {svc}Service& m_domain;
}};

}}  // namespace {sn}
'''


def _adapter_cpp(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name

    methods = ""
    for m in spec.methods:
        param_reads = "\n".join(
            f"    auto _{p.name} = request->{p.name}();"
            for p in m.params
        )
        args = ", ".join(f"_{p.name}" for p in m.params)

        if m.server_streaming:
            methods += f'''
grpc::Status {svc}GrpcAdapter::{m.name}(
    grpc::ServerContext* ctx,
    const {sn}::v1::{m.name}Request* request,
    grpc::ServerWriter<{sn}::v1::{m.name}Response>* writer) {{
{param_reads}
    // TODO: implement streaming
    {sn}::v1::{m.name}Response resp;
    resp.set_result(m_domain.{_snake(m.name)}({args}));
    writer->Write(resp);
    return grpc::Status::OK;
}}
'''
        else:
            methods += f'''
grpc::Status {svc}GrpcAdapter::{m.name}(
    grpc::ServerContext*,
    const {sn}::v1::{m.name}Request* request,
    {sn}::v1::{m.name}Response* response) {{
{param_reads}
    response->set_result(m_domain.{_snake(m.name)}({args}));
    return grpc::Status::OK;
}}
'''

    return f'''#include "{svc}GrpcAdapter.h"

namespace {sn} {{
{methods}
}}  // namespace {sn}
'''


# -----------------------------------------------------------------------
# Central env var scripts (set_env.bat / set_env.sh)
#
# Every other script calls/sources this file, so the user only edits
# paths here.  Variables already defined in the shell/system are left
# alone — useful when running in CI or when the user prefers global
# System Environment Variables.
# -----------------------------------------------------------------------

def _set_env_bat(spec: "ScaffoldSpec") -> str:
    qt_block = ""
    if spec.gui_type in ("widget", "wasm"):
        qt_block = '''
:: Qt install prefix — needed by the Widgets/WASM GUI client (find_package(Qt6)).
:: Point to the Qt kit that matches your MSVC toolchain.
if not defined QT_DIR set "QT_DIR=C:\\Qt\\6.7.1\\msvc2019_64"
'''

    wasm_block = ""
    if spec.gui_type == "wasm":
        wasm_block = '''
:: ----- Qt / Emscripten paths (only needed for WASM GUI builds) -----
if not defined QT_WASM_DIR  set "QT_WASM_DIR=C:\\Qt\\6.7.1\\wasm_singlethread"
if not defined QT_HOST_DIR  set "QT_HOST_DIR=C:\\Qt\\6.7.1\\msvc2019_64"
if not defined QT_CMAKE_DIR set "QT_CMAKE_DIR=C:\\Qt\\Tools\\CMake_64\\bin"
if not defined QT_NINJA_DIR set "QT_NINJA_DIR=C:\\Qt\\Tools\\Ninja"
if not defined EMSDK_DIR    set "EMSDK_DIR=D:\\emsdk"
'''
    return f'''@echo off
:: Central environment variables for this project.
::
:: Edit the defaults below, then every build script (build_deploy.bat,
:: proto\\generate_stubs.bat, build_wasm.bat) picks them up automatically.
::
:: Variables already set in the shell or System Environment are NOT
:: overwritten — so CI and users with global config still work.

if not defined VCPKG_ROOT set "VCPKG_ROOT=C:\\vcpkg"

:: CMake / Ninja — point these at your installs if they are NOT on PATH.
:: The block below prepends them to PATH so plain `cmake` / `ninja` work
:: from a vanilla cmd window (no Visual Studio Developer Prompt needed).
if not defined CMAKE_DIR set "CMAKE_DIR=C:\\Program Files\\CMake\\bin"
if not defined NINJA_DIR set "NINJA_DIR="

if exist "%CMAKE_DIR%\\cmake.exe" set "PATH=%CMAKE_DIR%;%PATH%"
if defined NINJA_DIR if exist "%NINJA_DIR%\\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"

:: MSVC compiler — call vcvars64.bat so cl.exe, link.exe, and Windows SDK
:: headers are available.  Skip if already initialised (VSCMD_ARG_TGT_ARCH
:: is set by vcvars itself) or from a Developer Command Prompt.
:: Point VS_DEV_CMD at the correct edition (Community / Professional / Enterprise).
if not defined VS_DEV_CMD set "VS_DEV_CMD=C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat"
if not defined VSCMD_ARG_TGT_ARCH (
    if exist "%VS_DEV_CMD%" (
        call "%VS_DEV_CMD%" >nul
    )
)
{qt_block}{wasm_block}
'''


def _set_env_sh(spec: "ScaffoldSpec") -> str:
    qt_block = ""
    if spec.gui_type in ("widget", "wasm"):
        qt_block = '''
# Qt install prefix — needed by the Widgets/WASM GUI client (find_package(Qt6)).
: "${QT_DIR:=$HOME/Qt/6.7.1/gcc_64}"
export QT_DIR
'''

    wasm_block = ""
    if spec.gui_type == "wasm":
        wasm_block = '''
# ----- Qt / Emscripten paths (only needed for WASM GUI builds) -----
: "${QT_WASM_DIR:=$HOME/Qt/6.7.1/wasm_singlethread}"
: "${QT_HOST_DIR:=$HOME/Qt/6.7.1/gcc_64}"
: "${EMSDK_DIR:=$HOME/emsdk}"
export QT_WASM_DIR QT_HOST_DIR EMSDK_DIR
'''
    return f'''#!/usr/bin/env bash
# Central environment variables for this project.
#
# Edit the defaults below, then every build script (build_deploy.sh,
# proto/generate_stubs.sh, build_wasm.sh) sources this file.
#
# Variables already set in the shell are NOT overwritten, so CI and
# users with global exports still work.

: "${{VCPKG_ROOT:=$HOME/vcpkg}}"
export VCPKG_ROOT

# CMake / Ninja — point these at your installs if they are NOT on PATH.
: "${{CMAKE_DIR:=}}"
: "${{NINJA_DIR:=}}"
[ -n "$CMAKE_DIR" ] && [ -x "$CMAKE_DIR/cmake" ] && export PATH="$CMAKE_DIR:$PATH"
[ -n "$NINJA_DIR" ] && [ -x "$NINJA_DIR/ninja" ] && export PATH="$NINJA_DIR:$PATH"

# Compiler — override if the system default (gcc/clang) is not what you want.
: "${{CC:=}}"
: "${{CXX:=}}"
[ -n "$CC" ]  && export CC
[ -n "$CXX" ] && export CXX
{qt_block}{wasm_block}
'''


# -----------------------------------------------------------------------
# Build scripts
# -----------------------------------------------------------------------

def _build_bat(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    windeployqt_block = ""
    if spec.gui_type == "widget":
        windeployqt_block = f'''
:: ----- Deploy Qt runtime for the GUI (Qt6*.dll, platforms\\, styles\\, ...) -----
if exist "%DIST%\\{sn}_gui.exe" (
    if defined QT_DIR (
        if exist "%QT_DIR%\\bin\\windeployqt.exe" (
            echo Running windeployqt for {sn}_gui.exe ...
            "%QT_DIR%\\bin\\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw "%DIST%\\{sn}_gui.exe" >nul
        ) else (
            echo WARNING: windeployqt not found at %QT_DIR%\\bin\\windeployqt.exe
            echo          Qt DLLs will not be deployed; {sn}_gui.exe may fail to start.
        )
    ) else (
        echo WARNING: QT_DIR is not set; skipping windeployqt.
    )
)
'''
    return f'''@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env.bat"

:: ----- Generate proto stubs (idempotent) -----
if not exist "%SCRIPT_DIR%proto\\{sn}.pb.h" (
    call "%SCRIPT_DIR%proto\\generate_stubs.bat"
    if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )
)

:: ----- Build service -----
set "SERVICE_BUILD=%SCRIPT_DIR%build"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build . --config Release
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client -----
:: Seed CMAKE_PREFIX_PATH with QT_DIR so the GUI target can locate Qt6
:: without requiring edits to client\\CMakeLists.txt.
set "QT_PREFIX_ARG="
if defined QT_DIR set "QT_PREFIX_ARG=-DCMAKE_PREFIX_PATH=%QT_DIR%"

set "CLIENT_BUILD=%SCRIPT_DIR%client\\build"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" %QT_PREFIX_ARG% ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build . --config Release
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect binaries + runtime DLLs into dist\\ -----
:: The vcpkg toolchain deploys required DLLs (grpc, protobuf, abseil,
:: openssl, zlib, c-ares, re2, etc.) next to each .exe during the build.
:: We mirror the whole Release folder so the binaries run standalone
:: from dist\\ — Windows otherwise fails the loader silently.
set "DIST=%SCRIPT_DIR%dist"
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%SERVICE_BUILD%\\Release\\*.exe"  "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%SERVICE_BUILD%\\Release\\*.dll"  "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\Release\\*.exe"   "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\Release\\*.dll"   "%DIST%\\" >nul 2>&1
{windeployqt_block}
echo.
echo Build complete.  Binaries + runtime DLLs collected in: %DIST%
endlocal
'''


def _build_mingw_bat(spec: "ScaffoldSpec") -> str:
    """MinGW variant of build_deploy.bat.

    Uses Ninja + g++ instead of MSBuild + cl.exe, with the
    x64-mingw-dynamic vcpkg triplet and the MinGW Qt kit.
    Produces its own build-mingw\\ / dist-mingw\\ folders so the two
    toolchains don't collide.
    """
    sn = spec.snake_name

    windeployqt_block = ""
    if spec.gui_type == "widget":
        windeployqt_block = f'''
:: ----- Deploy Qt runtime for the GUI (Qt6*.dll, platforms\\, styles\\) -----
if exist "%DIST%\\{sn}_gui.exe" (
    if defined QT_DIR (
        if exist "%QT_DIR%\\bin\\windeployqt.exe" (
            echo Running windeployqt for {sn}_gui.exe ...
            "%QT_DIR%\\bin\\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\\{sn}_gui.exe" >nul
        ) else (
            echo WARNING: windeployqt not found at %QT_DIR%\\bin\\windeployqt.exe
        )
    ) else (
        echo WARNING: QT_DIR is not set; skipping windeployqt.
    )
)
'''

    return f'''@echo off
:: MinGW variant of build_deploy.bat.
::
::   - Uses Ninja + MinGW g++ instead of MSBuild + cl.exe
::   - Uses vcpkg triplet x64-mingw-dynamic
::   - Points QT_DIR at the Qt MinGW kit (C:\\Qt\\6.x\\mingw_64)
::
:: Edit the three paths below to match your machine, or export them
:: as global env vars.  Run from the project root:
::
::     build_deploy_mingw.bat
::
:: First-time vcpkg install for the mingw triplet can take 20-60 min
:: (ports compile from source).  Pre-seed with:
::     set VCPKG_DEFAULT_TRIPLET=x64-mingw-dynamic
::     %VCPKG_ROOT%\\vcpkg install grpc:x64-mingw-dynamic ...
setlocal

set "SCRIPT_DIR=%~dp0"

:: ---------------------------------------------------------------------------
:: MinGW-specific environment.  Set BEFORE calling set_env.bat so the MSVC
:: vcvars block inside set_env.bat is skipped (via VSCMD_ARG_TGT_ARCH) and
:: MINGW_DIR / NINJA_DIR / QT_DIR defaults apply.
:: ---------------------------------------------------------------------------
if not defined MINGW_DIR     set "MINGW_DIR=C:\\Qt\\Tools\\mingw1120_64\\bin"
if not defined NINJA_DIR     set "NINJA_DIR=C:\\Qt\\Tools\\Ninja"
if not defined QT_DIR        set "QT_DIR=C:\\Qt\\6.7.1\\mingw_64"
if not defined VCPKG_TRIPLET set "VCPKG_TRIPLET=x64-mingw-dynamic"

:: Sentinel so set_env.bat skips the MSVC vcvars64.bat call.
set "VSCMD_ARG_TGT_ARCH=SKIP_FOR_MINGW"

call "%SCRIPT_DIR%set_env.bat"

:: Put MinGW + Ninja on PATH (idempotent).
if exist "%MINGW_DIR%\\g++.exe"   set "PATH=%MINGW_DIR%;%PATH%"
if exist "%NINJA_DIR%\\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"

where g++ >nul 2>&1
if errorlevel 1 ( echo ERROR: g++ not found.  Check MINGW_DIR=%MINGW_DIR% & exit /b 1 )
where ninja >nul 2>&1
if errorlevel 1 ( echo ERROR: ninja not found.  Check NINJA_DIR=%NINJA_DIR% & exit /b 1 )

:: ----- Generate proto stubs (idempotent) -----
if not exist "%SCRIPT_DIR%proto\\{sn}.pb.h" (
    call "%SCRIPT_DIR%proto\\generate_stubs.bat"
    if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )
)

:: ----- Build service (Ninja + MinGW) -----
set "SERVICE_BUILD=%SCRIPT_DIR%build-mingw"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" ^
      -DVCPKG_TARGET_TRIPLET=%VCPKG_TRIPLET% ^
      ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client (Ninja + MinGW) -----
set "QT_PREFIX_ARG="
if defined QT_DIR set "QT_PREFIX_ARG=-DCMAKE_PREFIX_PATH=%QT_DIR%"

set "CLIENT_BUILD=%SCRIPT_DIR%client\\build-mingw"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" ^
      -DVCPKG_TARGET_TRIPLET=%VCPKG_TRIPLET% ^
      %QT_PREFIX_ARG% ^
      ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect binaries + runtime DLLs into dist-mingw\\ -----
:: With Ninja the exe/dll are directly in the build dir (no Release\\ subdir).
set "DIST=%SCRIPT_DIR%dist-mingw"
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%SERVICE_BUILD%\\*.exe" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%SERVICE_BUILD%\\*.dll" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\*.exe"  "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\*.dll"  "%DIST%\\" >nul 2>&1

:: MinGW C++ runtime libs come from MINGW_DIR, not vcpkg.
if defined MINGW_DIR (
    for %%L in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll) do (
        if exist "%MINGW_DIR%\\%%L" copy /Y "%MINGW_DIR%\\%%L" "%DIST%\\" >nul
    )
)
{windeployqt_block}
echo.
echo MinGW build complete.  Binaries + runtime DLLs collected in: %DIST%
endlocal
'''


def _build_sh(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    gui_copy = ""
    if spec.gui_type == "widget":
        gui_copy = (
            f'cp "$CLIENT_BUILD/{sn}_gui" "$DIST/" 2>/dev/null || true\n'
        )
    return f'''#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

# ----- Generate proto stubs (idempotent) -----
if [ ! -f "$SCRIPT_DIR/proto/{sn}.pb.h" ]; then
    bash "$SCRIPT_DIR/proto/generate_stubs.sh"
fi

# ----- Build service -----
SERVICE_BUILD="$SCRIPT_DIR/build"
mkdir -p "$SERVICE_BUILD"
cmake -S "$SCRIPT_DIR" -B "$SERVICE_BUILD" \\
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \\
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$SERVICE_BUILD" --parallel $(nproc)

# ----- Build client -----
# Seed CMAKE_PREFIX_PATH with QT_DIR so the GUI target can locate Qt6
# without requiring edits to client/CMakeLists.txt.
QT_PREFIX_ARG=()
if [ -n "${{QT_DIR:-}}" ]; then QT_PREFIX_ARG=(-DCMAKE_PREFIX_PATH="$QT_DIR"); fi

CLIENT_BUILD="$SCRIPT_DIR/client/build"
mkdir -p "$CLIENT_BUILD"
cmake -S "$SCRIPT_DIR/client" -B "$CLIENT_BUILD" \\
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \\
    "${{QT_PREFIX_ARG[@]}}" \\
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$CLIENT_BUILD" --parallel $(nproc)

# ----- Collect binaries + shared libraries into dist/ -----
DIST="$SCRIPT_DIR/dist"
mkdir -p "$DIST"
cp "$SERVICE_BUILD/{sn}"       "$DIST/" 2>/dev/null || true
cp "$CLIENT_BUILD/{sn}_client" "$DIST/" 2>/dev/null || true
{gui_copy}
# Copy any *.so / *.so.* shared libraries next to the binaries. vcpkg
# deploys dynamic libs under lib/, plus CMake may leave runtime libs in
# the build trees themselves.
for d in \\
    "$VCPKG_ROOT/installed/x64-linux/lib" \\
    "$SERVICE_BUILD" "$CLIENT_BUILD"; do
    [ -d "$d" ] || continue
    find "$d" -maxdepth 2 -name "*.so*" -type f -exec cp -f {{}} "$DIST/" \\; 2>/dev/null || true
done

# Deploy Qt plugins for the Widgets GUI on Linux.  Qt needs
# platforms/libqxcb.so (or Wayland equivalents) next to the binary.
if [ -f "$DIST/{sn}_gui" ] && [ -n "${{QT_DIR:-}}" ] && [ -d "$QT_DIR/plugins" ]; then
    mkdir -p "$DIST/platforms"
    cp -rf "$QT_DIR/plugins/platforms/"* "$DIST/platforms/" 2>/dev/null || true
    [ -d "$QT_DIR/plugins/xcbglintegrations" ] && \\
        cp -rf "$QT_DIR/plugins/xcbglintegrations" "$DIST/" 2>/dev/null || true
fi

echo ""
echo "Build complete. Binaries + libraries collected in: $DIST"
'''


# -----------------------------------------------------------------------
# Proto stub generation scripts (shared — live in proto/)
# -----------------------------------------------------------------------

def _gen_stubs_bat(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    return f'''@echo off
:: Generate C++ gRPC stubs from {sn}.proto.
:: Run once, then both service and client can build without protoc.
setlocal enabledelayedexpansion

set "PROTO_DIR=%~dp0"
:: Remove trailing backslash
if "!PROTO_DIR:~-1!"=="\\" set "PROTO_DIR=!PROTO_DIR:~0,-1!"

:: Pull VCPKG_ROOT from the central set_env.bat in the project root.
if exist "!PROTO_DIR!\\..\\set_env.bat" call "!PROTO_DIR!\\..\\set_env.bat"

:: ----- Find protoc and grpc_cpp_plugin -----
set "PROTOC="
set "GRPC_PLUGIN="

if defined VCPKG_ROOT (
    if exist "!VCPKG_ROOT!\\installed\\x64-windows\\tools\\protobuf\\protoc.exe" (
        set "PROTOC=!VCPKG_ROOT!\\installed\\x64-windows\\tools\\protobuf\\protoc.exe"
    )
    if exist "!VCPKG_ROOT!\\installed\\x64-windows\\tools\\grpc\\grpc_cpp_plugin.exe" (
        set "GRPC_PLUGIN=!VCPKG_ROOT!\\installed\\x64-windows\\tools\\grpc\\grpc_cpp_plugin.exe"
    )
)

if "!PROTOC!"=="" (
    for /f "delims=" %%P in ('where protoc 2^>nul') do set "PROTOC=%%P"
)
if "!GRPC_PLUGIN!"=="" (
    for /f "delims=" %%P in ('where grpc_cpp_plugin 2^>nul') do set "GRPC_PLUGIN=%%P"
)

if "!PROTOC!"=="" (
    echo ERROR: protoc not found.
    echo   Set VCPKG_ROOT or install: vcpkg install grpc:x64-windows protobuf:x64-windows
    exit /b 1
)
if "!GRPC_PLUGIN!"=="" (
    echo ERROR: grpc_cpp_plugin not found.
    echo   Set VCPKG_ROOT or install: vcpkg install grpc:x64-windows
    exit /b 1
)

echo protoc:          !PROTOC!
echo grpc_cpp_plugin: !GRPC_PLUGIN!
echo.
echo Generating stubs from {sn}.proto into %PROTO_DIR% ...

"!PROTOC!" --proto_path="!PROTO_DIR!" --cpp_out="!PROTO_DIR!" --grpc_out="!PROTO_DIR!" --plugin=protoc-gen-grpc="!GRPC_PLUGIN!" "!PROTO_DIR!\\{sn}.proto"
if errorlevel 1 ( echo FAILED. & exit /b 1 )

echo.
echo Done. Generated files:
dir /b "!PROTO_DIR!\\*.pb.h" "!PROTO_DIR!\\*.pb.cc" 2>nul
echo.
echo Both service and client can now build without protoc.
endlocal
'''


def _gen_stubs_sh(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env bash
# Generate C++ gRPC stubs from {sn}.proto.
# Run once, then both service and client can build without protoc.
set -e
PROTO_DIR="$(cd "$(dirname "$0")" && pwd)"

# Pull VCPKG_ROOT from the central set_env.sh in the project root.
if [ -f "$PROTO_DIR/../set_env.sh" ]; then
    source "$PROTO_DIR/../set_env.sh"
fi

# ----- Find tools -----
PROTOC=$(command -v protoc 2>/dev/null || true)
GRPC_PLUGIN=$(command -v grpc_cpp_plugin 2>/dev/null || true)

if [ -z "$PROTOC" ] && [ -n "$VCPKG_ROOT" ]; then
    PROTOC="$VCPKG_ROOT/installed/x64-linux/tools/protobuf/protoc"
fi
if [ -z "$GRPC_PLUGIN" ] && [ -n "$VCPKG_ROOT" ]; then
    GRPC_PLUGIN="$VCPKG_ROOT/installed/x64-linux/tools/grpc/grpc_cpp_plugin"
fi

if [ -z "$PROTOC" ] || [ ! -f "$PROTOC" ]; then
    echo "ERROR: protoc not found. Set VCPKG_ROOT or install protobuf."
    exit 1
fi
if [ -z "$GRPC_PLUGIN" ] || [ ! -f "$GRPC_PLUGIN" ]; then
    echo "ERROR: grpc_cpp_plugin not found. Set VCPKG_ROOT or install grpc."
    exit 1
fi

echo "protoc:          $PROTOC"
echo "grpc_cpp_plugin: $GRPC_PLUGIN"
echo ""
echo "Generating stubs from {sn}.proto into $PROTO_DIR ..."

"$PROTOC" --proto_path="$PROTO_DIR" \\
    --cpp_out="$PROTO_DIR" \\
    --grpc_out="$PROTO_DIR" \\
    --plugin=protoc-gen-grpc="$GRPC_PLUGIN" \\
    "$PROTO_DIR/{sn}.proto"

echo ""
echo "Done. Both service and client can now build without protoc."
'''


# -----------------------------------------------------------------------
# WASM build scripts
# -----------------------------------------------------------------------

def _build_wasm_bat(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    return f'''@echo off
setlocal enabledelayedexpansion
:: Build the Qt WASM GUI and copy output to GUIs/
::
:: Prerequisites:
::   - Qt 6 with wasm_singlethread target
::   - Emscripten matching your Qt version
::   - CMake + Ninja
::
:: Usage:
::   build_wasm.bat              Build Release
::   build_wasm.bat clean        Delete WASM build folder

set "SCRIPT_DIR=%~dp0"
if "!SCRIPT_DIR:~-1!"=="\\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"

:: Load Qt / Emscripten paths from the central set_env.bat.
call "!SCRIPT_DIR!\\set_env.bat"
set "BUILD_DIR=!SCRIPT_DIR!\\build\\wasm"
set "EMSCRIPTEN_DIR=!EMSDK_DIR!\\upstream\\emscripten"

if /I "%~1"=="clean" (
    if exist "!BUILD_DIR!" rd /s /q "!BUILD_DIR!"
    echo Cleaned. & exit /b 0
)

set "PATH=!EMSCRIPTEN_DIR!;!EMSDK_DIR!;%QT_CMAKE_DIR%;%QT_NINJA_DIR%;!PATH!"
set "EMSDK=!EMSDK_DIR!"

set "QT_TOOLCHAIN=!QT_WASM_DIR!\\lib\\cmake\\Qt6\\qt.toolchain.cmake"
set "EM_TOOLCHAIN=!EMSCRIPTEN_DIR!\\cmake\\Modules\\Platform\\Emscripten.cmake"

cmake -G Ninja -DCMAKE_MAKE_PROGRAM="%QT_NINJA_DIR%\\ninja.exe" -DCMAKE_TOOLCHAIN_FILE="!QT_TOOLCHAIN!" -DQT_CHAINLOAD_TOOLCHAIN_FILE="!EM_TOOLCHAIN!" -B "!BUILD_DIR!" -S "!SCRIPT_DIR!" -DQT_HOST_PATH="%QT_HOST_DIR%" -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 ( echo CMake configure failed. & exit /b 1 )

cmake --build "!BUILD_DIR!" --parallel
if errorlevel 1 ( echo Build failed. & exit /b 1 )

if not exist "!SCRIPT_DIR!\\GUIs" mkdir "!SCRIPT_DIR!\\GUIs"
copy /Y "!BUILD_DIR!\\{sn}_wasm.wasm" "!SCRIPT_DIR!\\GUIs\\" >nul 2>&1
copy /Y "!BUILD_DIR!\\{sn}_wasm.js"   "!SCRIPT_DIR!\\GUIs\\" >nul 2>&1

echo.
echo WASM build complete. Output: GUIs/
endlocal
'''


def _build_wasm_sh(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env bash
# Build the Qt WASM GUI and copy output to GUIs/
#
# Prerequisites:
#   - Qt 6 with wasm_singlethread target
#   - Emscripten matching your Qt version
#   - CMake + Ninja
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load Qt / Emscripten paths from the central set_env.sh.
source "$SCRIPT_DIR/set_env.sh"

BUILD_DIR="$SCRIPT_DIR/build/wasm"
EMSCRIPTEN_DIR="$EMSDK_DIR/upstream/emscripten"

if [ "$1" = "clean" ]; then
    rm -rf "$BUILD_DIR"
    echo "Cleaned."
    exit 0
fi

export PATH="$EMSCRIPTEN_DIR:$EMSDK_DIR:$PATH"

QT_TOOLCHAIN="$QT_WASM_DIR/lib/cmake/Qt6/qt.toolchain.cmake"
EM_TOOLCHAIN="$EMSCRIPTEN_DIR/cmake/Modules/Platform/Emscripten.cmake"

cmake -G Ninja \\
    -DCMAKE_TOOLCHAIN_FILE="$QT_TOOLCHAIN" \\
    -DQT_CHAINLOAD_TOOLCHAIN_FILE="$EM_TOOLCHAIN" \\
    -B "$BUILD_DIR" -S "$SCRIPT_DIR" \\
    -DQT_HOST_PATH="$QT_HOST_DIR" \\
    -DCMAKE_BUILD_TYPE=Release

cmake --build "$BUILD_DIR" --parallel

mkdir -p "$SCRIPT_DIR/GUIs"
cp "$BUILD_DIR/{sn}_wasm.wasm" "$SCRIPT_DIR/GUIs/" 2>/dev/null || true
cp "$BUILD_DIR/{sn}_wasm.js"   "$SCRIPT_DIR/GUIs/" 2>/dev/null || true

echo ""
echo "WASM build complete. Output: GUIs/"
'''


# -----------------------------------------------------------------------
# QML GUI files
# -----------------------------------------------------------------------

def _qml_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    svc = spec.service_name
    return {
        "qml/ServiceUI.qml": f'''import QtQuick 2.15
import QtQuick.Controls 2.15
import MicroserviceBase 1.0

Rectangle {{
    id: root
    width: 600; height: 400
    color: "#f5f5f5"

    Label {{
        anchors.centerIn: parent
        text: "{svc} QML UI"
        font.pixelSize: 24
    }}

    Connections {{
        target: ServiceBridge
        function onResponseReceived(method, data) {{
            console.log(method, "->", data)
        }}
    }}
}}
''',
        "GUIs/ServiceUI.qml": f'''import QtQuick 2.15
import QtQuick.Controls 2.15
import MicroserviceBase 1.0

Rectangle {{
    id: root
    width: 600; height: 400
    color: "#f5f5f5"

    Label {{
        anchors.centerIn: parent
        text: "{svc} QML UI"
        font.pixelSize: 24
    }}
}}
''',
        "stubs/MicroserviceBase/qmldir": "module MicroserviceBase\nsingleton ServiceBridge 1.0 ServiceBridge.qml\n",
        "stubs/MicroserviceBase/ServiceBridge.qml": '''pragma Singleton
import QtQuick 2.15

QtObject {
    property string serviceName: "MockService"
    signal responseReceived(string method, string result)
    signal errorOccurred(string method, string error)

    function callService(serviceName, method, args) {
        console.log("[Stub]", serviceName, method, JSON.stringify(args));
        Qt.callLater(function() {
            responseReceived(method, "(stub response)");
        });
    }
}
''',
    }


# -----------------------------------------------------------------------
# WASM GUI files
# -----------------------------------------------------------------------

def _wasm_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    svc = spec.service_name
    sn = spec.snake_name
    return {
        "wasm/main.cpp": f'''#include <QApplication>
#include "MainWidget.h"

int main(int argc, char *argv[]) {{
    QApplication app(argc, argv);
    MainWidget widget;
    widget.show();
    return app.exec();
}}
''',
        "src/MainWidget.h": f'''#pragma once
#include <QWidget>

class MainWidget : public QWidget {{
    Q_OBJECT
public:
    explicit MainWidget(QWidget *parent = nullptr);
}};
''',
        "src/MainWidget.cpp": f'''#include "MainWidget.h"
#include <QLabel>
#include <QVBoxLayout>

MainWidget::MainWidget(QWidget *parent) : QWidget(parent) {{
    auto *layout = new QVBoxLayout(this);
    layout->addWidget(new QLabel("{svc} WASM UI"));
    setWindowTitle("{svc}");
    resize(400, 300);
}}
''',
        f"GUIs/{svc}.html": f'''<div class="card" style="height: 100%; width: 100%; top: 0;">
  <div class="card-header">
    <h5 class="card-title">{svc}</h5>
    <span class="badge bg-info" id="qtStatusBadge">Loading...</span>
  </div>
  <div class="card-body p-0" style="height: calc(100% - 60px); overflow: hidden;">
    <div id="qtContainer" style="width: 100%; height: 100%;"></div>
  </div>
</div>
''',
    }


# -----------------------------------------------------------------------
# Widget GUI files
# -----------------------------------------------------------------------

def _widget_method_binding(m: "MethodSpec", sn: str) -> str:
    """Emit one `MethodBinding` initializer block for `buildMethodBindings()`.

    Picks the right widget cast + req setter per proto type, and the right
    display expression for the response's `result` field.  Supports unary
    and server-streaming RPCs.
    """
    # Params vector initialiser
    params_init = ", ".join(
        f'{{"{p.name}", "{p.type}"}}' for p in m.params
    )

    # Setter lines (one per param)
    setters = []
    for i, p in enumerate(m.params):
        t = (p.type or "string").lower()
        if t in ("string", "bytes", "str"):
            setters.append(
                f'            req.set_{p.name}('
                f'qobject_cast<QLineEdit*>(ws[{i}])->text().toStdString());'
            )
        elif t in ("int32", "int", "uint32", "int64", "uint64"):
            setters.append(
                f'            req.set_{p.name}('
                f'qobject_cast<QSpinBox*>(ws[{i}])->value());'
            )
        elif t in ("float", "double"):
            setters.append(
                f'            req.set_{p.name}('
                f'qobject_cast<QDoubleSpinBox*>(ws[{i}])->value());'
            )
        elif t == "bool":
            setters.append(
                f'            req.set_{p.name}('
                f'qobject_cast<QCheckBox*>(ws[{i}])->isChecked());'
            )
        else:
            setters.append(
                f'            req.set_{p.name}('
                f'qobject_cast<QLineEdit*>(ws[{i}])->text().toStdString());'
            )
    setters_str = "\n".join(setters) if setters else "            (void)ws;"

    # Return-value display expression (response always has `result` field)
    rt = (m.return_type or "string").lower()
    if rt in ("string", "bytes", "str"):
        ret_expr = "QString::fromStdString(resp.result())"
    elif rt == "bool":
        ret_expr = 'QString(resp.result() ? "true" : "false")'
    else:
        ret_expr = "QString::number(resp.result())"

    if m.server_streaming:
        return f'''    // --- {m.name} (server streaming) ---
    {{
        MethodBinding b;
        b.name = "{m.name}";
        b.params = {{ {params_init} }};
        b.invoke = [this](const std::vector<QWidget*>& ws) -> QString {{
            grpc::ClientContext ctx;
            {sn}::v1::{m.name}Request req;
{setters_str}
            auto reader = m_client->stub().{m.name}(&ctx, req);
            {sn}::v1::{m.name}Response resp;
            QString acc;
            int count = 0;
            while (reader->Read(&resp)) {{
                acc += {ret_expr};
                acc += "\\n";
                ++count;
            }}
            auto st = reader->Finish();
            if (!st.ok()) {{
                return QString("[error] ") + QString::fromStdString(st.error_message());
            }}
            return QString("(%1 messages)\\n%2").arg(count).arg(acc);
        }};
        m_methods.push_back(std::move(b));
    }}'''

    return f'''    // --- {m.name} ---
    {{
        MethodBinding b;
        b.name = "{m.name}";
        b.params = {{ {params_init} }};
        b.invoke = [this](const std::vector<QWidget*>& ws) -> QString {{
            grpc::ClientContext ctx;
            {sn}::v1::{m.name}Request req;
{setters_str}
            {sn}::v1::{m.name}Response resp;
            auto st = m_client->stub().{m.name}(&ctx, req, &resp);
            if (!st.ok()) {{
                return QString("[error] ") + QString::fromStdString(st.error_message());
            }}
            return {ret_expr};
        }};
        m_methods.push_back(std::move(b));
    }}'''


def _widget_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    """Qt Widgets GUI *client* — lives under client/gui/, built alongside
    the console client by the same client/CMakeLists.txt.

    The generated UI is a dynamic multi-method form: a QComboBox picks
    the RPC, a QFormLayout renders param widgets matching the proto
    types (QLineEdit/QSpinBox/QDoubleSpinBox/QCheckBox), one shared
    Send button dispatches to the selected method's lambda, and a
    QTextEdit logs responses.
    """
    svc = spec.service_name
    sn = spec.snake_name

    method_blocks = "\n\n".join(
        _widget_method_binding(m, sn) for m in spec.methods
    )

    ui_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>MainWindow</class>
 <widget class="QWidget" name="MainWindow">
  <property name="geometry">
   <rect><x>0</x><y>0</y><width>640</width><height>520</height></rect>
  </property>
  <property name="windowTitle">
   <string>{svc} Client</string>
  </property>
  <layout class="QVBoxLayout" name="verticalLayout">
   <item>
    <layout class="QHBoxLayout" name="methodRow">
     <item>
      <widget class="QLabel" name="methodLabel">
       <property name="text"><string>Method:</string></property>
      </widget>
     </item>
     <item>
      <widget class="QComboBox" name="methodCombo"/>
     </item>
    </layout>
   </item>
   <item>
    <widget class="QGroupBox" name="paramsGroup">
     <property name="title"><string>Parameters</string></property>
     <layout class="QVBoxLayout" name="paramsOuter">
      <item><widget class="QWidget" name="formContainer" native="true"/></item>
     </layout>
    </widget>
   </item>
   <item>
    <widget class="QPushButton" name="sendButton">
     <property name="text"><string>Send</string></property>
    </widget>
   </item>
   <item>
    <widget class="QTextEdit" name="outputTextEdit">
     <property name="readOnly"><bool>true</bool></property>
     <property name="placeholderText"><string>Responses appear here...</string></property>
    </widget>
   </item>
  </layout>
 </widget>
 <resources/>
 <connections/>
</ui>
'''

    main_cpp = '''#include <QApplication>
#include "MainWindow.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    MainWindow w;
    w.show();
    return app.exec();
}
'''

    header = f'''#pragma once

#include <QString>
#include <QWidget>

#include <functional>
#include <memory>
#include <vector>

#include "MicroserviceBase/ServiceClient.h"
#include "{sn}.grpc.pb.h"

QT_BEGIN_NAMESPACE
class QFormLayout;
namespace Ui {{ class MainWindow; }}
QT_END_NAMESPACE

class MainWindow : public QWidget {{
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);
    ~MainWindow() override;

private slots:
    void onMethodChanged(int idx);
    void onSend();

private:
    struct ParamSpec {{
        QString name;
        QString type;
    }};
    struct MethodBinding {{
        QString name;
        std::vector<ParamSpec> params;
        std::function<QString(const std::vector<QWidget*>&)> invoke;
    }};

    void buildMethodBindings();
    void rebuildForm(int idx);

    Ui::MainWindow *ui;
    QFormLayout   *m_form = nullptr;
    std::vector<MethodBinding>  m_methods;
    std::vector<QWidget*>       m_currentWidgets;
    std::unique_ptr<
        microservice_base::ServiceClient<{sn}::v1::{svc}Service>> m_client;
}};
'''

    source = f'''#include "MainWindow.h"
#include "ui_MainWindow.h"

#include <grpcpp/grpcpp.h>

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QSpinBox>
#include <QTimer>

#include <climits>

namespace {{

// Build an input widget matching a proto scalar type.
QWidget* makeWidgetFor(const QString& type, QWidget* parent) {{
    if (type == "string" || type == "bytes") {{
        return new QLineEdit(parent);
    }}
    if (type == "int32" || type == "int" || type == "uint32" ||
        type == "int64" || type == "uint64") {{
        auto* s = new QSpinBox(parent);
        s->setRange(INT_MIN, INT_MAX);
        return s;
    }}
    if (type == "float" || type == "double") {{
        auto* s = new QDoubleSpinBox(parent);
        s->setRange(-1e12, 1e12);
        s->setDecimals(6);
        return s;
    }}
    if (type == "bool") {{
        return new QCheckBox(parent);
    }}
    return new QLineEdit(parent);  // fallback
}}

}}  // namespace

MainWindow::MainWindow(QWidget *parent)
    : QWidget(parent), ui(new Ui::MainWindow) {{
    ui->setupUi(this);

    m_form = new QFormLayout(ui->formContainer);
    m_form->setContentsMargins(6, 6, 6, 6);

    buildMethodBindings();
    for (const auto& m : m_methods) {{
        ui->methodCombo->addItem(m.name);
    }}

    connect(ui->methodCombo,
            QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::onMethodChanged);
    connect(ui->sendButton, &QPushButton::clicked,
            this, &MainWindow::onSend);

    if (!m_methods.empty()) {{
        rebuildForm(0);
    }}

    // Defer the Consul lookup until after the event loop starts so the
    // window paints immediately even if Consul is slow/unreachable.
    QTimer::singleShot(0, this, [this]() {{
        ui->outputTextEdit->append("Resolving {sn} via Consul...");
        try {{
            m_client = std::make_unique<
                microservice_base::ServiceClient<{sn}::v1::{svc}Service>>("{sn}");
            const QString tgt = QString::fromStdString(m_client->target());
            ui->outputTextEdit->append(tgt.isEmpty()
                ? QString("[warn] Consul returned no healthy instance.")
                : QString("Connected to %1").arg(tgt));
        }} catch (const std::exception& e) {{
            ui->outputTextEdit->append(
                QString("Connection failed: %1").arg(e.what()));
        }}
    }});
}}

MainWindow::~MainWindow() {{
    delete ui;
}}

void MainWindow::onMethodChanged(int idx) {{
    rebuildForm(idx);
}}

void MainWindow::rebuildForm(int idx) {{
    while (m_form->rowCount() > 0) {{
        m_form->removeRow(0);
    }}
    m_currentWidgets.clear();

    if (idx < 0 || idx >= static_cast<int>(m_methods.size())) return;

    const auto& b = m_methods[idx];
    for (const auto& p : b.params) {{
        QWidget* w = makeWidgetFor(p.type, ui->formContainer);
        m_form->addRow(p.name + " (" + p.type + "):", w);
        m_currentWidgets.push_back(w);
    }}
    if (b.params.empty()) {{
        m_form->addRow(new QLabel("(no parameters)", ui->formContainer));
    }}
}}

void MainWindow::onSend() {{
    int idx = ui->methodCombo->currentIndex();
    if (idx < 0 || idx >= static_cast<int>(m_methods.size())) return;
    if (!m_client) {{
        ui->outputTextEdit->append("[not connected]");
        return;
    }}
    const auto& b = m_methods[idx];
    ui->outputTextEdit->append(QString(">> %1").arg(b.name));
    ui->outputTextEdit->append(b.invoke(m_currentWidgets));
}}

void MainWindow::buildMethodBindings() {{
{method_blocks}
}}
'''

    return {
        "client/gui/main.cpp": main_cpp,
        "client/gui/MainWindow.h": header,
        "client/gui/MainWindow.cpp": source,
        "client/gui/MainWindow.ui": ui_xml,
    }


# -----------------------------------------------------------------------
# Client subproject
# -----------------------------------------------------------------------

def _client_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    sn = spec.snake_name
    svc = spec.service_name
    prefix = spec.env_prefix

    gui_block = ""
    if spec.gui_type == "widget":
        gui_block = f'''

# ----- Qt Widgets GUI client ({sn}_gui) ------------------------------
# Qt 6 discovery: honour QT_DIR / Qt6_DIR env vars (set in set_env.bat/.sh).
#   QT_DIR   = Qt install prefix, e.g. C:\\Qt\\6.7.1\\msvc2019_64
#   Qt6_DIR  = directory containing Qt6Config.cmake (overrides QT_DIR)
if(NOT DEFINED Qt6_DIR AND DEFINED ENV{{Qt6_DIR}})
    set(Qt6_DIR "$ENV{{Qt6_DIR}}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{{QT_DIR}} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{{QT_DIR}}")
endif()

find_package(Qt6 COMPONENTS Core Gui Widgets REQUIRED)
qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTOUIC_SEARCH_PATHS "${{CMAKE_CURRENT_SOURCE_DIR}}/gui")

qt_add_executable({sn}_gui
    gui/main.cpp
    gui/MainWindow.cpp
    gui/MainWindow.h
    gui/MainWindow.ui
    ${{STUB_SRCS}}
)

target_include_directories({sn}_gui PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/gui"
    "${{PROTO_DIR}}"
)

target_link_libraries({sn}_gui PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
    Qt6::Widgets
)

set_target_properties({sn}_gui PROPERTIES
    WIN32_EXECUTABLE ON
    MACOSX_BUNDLE    ON
)'''

    return {
        "client/CMakeLists.txt": f'''cmake_minimum_required(VERSION 3.16)
project({svc}Client VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Auto-detect vcpkg from VCPKG_ROOT env var or parent CMakePresets.json
if(NOT CMAKE_TOOLCHAIN_FILE)
    if(DEFINED ENV{{VCPKG_ROOT}})
        set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
            CACHE PATH "vcpkg toolchain")
    endif()
endif()
if(CMAKE_TOOLCHAIN_FILE AND EXISTS "${{CMAKE_TOOLCHAIN_FILE}}")
    get_filename_component(_vr "${{CMAKE_TOOLCHAIN_FILE}}" DIRECTORY)
    get_filename_component(_vr "${{_vr}}" DIRECTORY)
    get_filename_component(_vr "${{_vr}}" DIRECTORY)
    if(EXISTS "${{_vr}}/installed/x64-windows/share")
        list(APPEND CMAKE_PREFIX_PATH "${{_vr}}/installed/x64-windows")
    endif()
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)

# MicroserviceBase runtime — provides ServiceClient<T>
add_subdirectory(
    "${{CMAKE_CURRENT_SOURCE_DIR}}/../../../MicroserviceBase/runtime_cpp"
    "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime"
)

# Proto stubs — shared with the service via ../proto/.
# Run proto/generate_stubs.bat (Win) or .sh (Linux) once from the
# parent project.  The generated .pb.h/.pb.cc files live in proto/.
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/../proto")

set(STUB_SRCS
    "${{PROTO_DIR}}/{sn}.pb.cc"
    "${{PROTO_DIR}}/{sn}.grpc.pb.cc"
)

# Check that stubs exist.
if(NOT EXISTS "${{PROTO_DIR}}/{sn}.pb.h")
    message(FATAL_ERROR
        "Proto stubs not found in ${{PROTO_DIR}}.\\n"
        "Run proto/generate_stubs.bat (Win) or .sh (Linux) first.")
endif()

add_executable({sn}_client
    src/client.cpp
    ${{STUB_SRCS}}
)

target_include_directories({sn}_client PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{PROTO_DIR}}"
)

target_link_libraries({sn}_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
){gui_block}
''',

        "client/src/client.cpp": f'''// client.cpp — gRPC client for {svc} using ServiceClient<T>.
//
// Usage:
//   {sn}_client {sn}                  # all RPCs via Consul
//   {sn}_client {sn} <Method> <args>  # specific RPC
//   {sn}_client --direct host:port    # no Consul

#include <iostream>
#include <string>
#include <grpcpp/grpcpp.h>
#include "{sn}.grpc.pb.h"
#include "MicroserviceBase/ServiceClient.h"

using {sn}::v1::{svc}Service;

int main(int argc, char* argv[]) {{
    if (argc < 2) {{
        std::cerr << "Usage: {sn}_client <service_name|--direct host:port> [method] [args...]" << std::endl;
        return 1;
    }}

    std::string arg1 = argv[1];
    std::unique_ptr<microservice_base::ServiceClient<{svc}Service>> client;

    try {{
        if (arg1 == "--direct") {{
            if (argc < 3) {{ std::cerr << "Missing host:port" << std::endl; return 1; }}
            client = std::make_unique<microservice_base::ServiceClient<{svc}Service>>(
                "{sn}", argv[2], true);
            std::cout << "Connected directly to " << client->target() << std::endl;
        }} else {{
            client = std::make_unique<microservice_base::ServiceClient<{svc}Service>>(arg1);
            std::cout << "Resolved " << arg1 << " via Consul -> "
                      << client->target() << std::endl;
        }}
    }} catch (const std::exception& e) {{
        std::cerr << "Connection failed: " << e.what() << std::endl;
        return 1;
    }}

    auto& stub = client->stub();

    // TODO: Add RPC calls here. Example:
    // grpc::ClientContext ctx;
    // {sn}::v1::DoSomethingRequest req;
    // req.set_input("test");
    // {sn}::v1::DoSomethingResponse resp;
    // auto status = stub.DoSomething(&ctx, req, &resp);

    std::cout << "Client ready. Add RPC calls to src/client.cpp." << std::endl;
    return 0;
}}
''',

        "client/README.md": f'''# {svc} Client

C++ gRPC client for the `{sn}` service.

## Quick start

```bash
# 1. Generate stubs (one time, from the project root)
cd proto
generate_stubs.bat        # Windows
./generate_stubs.sh       # Linux
cd ..

# 2. Build the client
cd client
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release

# 3. Run
{sn}_client {sn}               # Consul discovery
{sn}_client --direct host:port  # direct connection
```

Proto stubs are shared with the service from `../proto/`.
Uses `ServiceClient<{svc}Service>` from MicroserviceBase runtime for
automatic Consul discovery and channel management.
''',
    }
